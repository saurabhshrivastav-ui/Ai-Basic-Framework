"""
================================================================================
 AGENT 14 - THE AUTO REPAIR AGENT
================================================================================
THINK OF IT LIKE: a smart GPS that has re-routed around the same closed
road five times in a row. After enough repeat trips, it just accepts
"this road is closed" as a fact and stops suggesting the old route at
all - it doesn't wait for someone to manually update the map.

That is what this agent does with self_healing/healing_log.json (the
"locator memory" Agent 11 writes every time it has to fall back past an
element's normal #1 locator). If ONE element has needed a fallback
locator again and again, that is no longer bad luck - it is evidence
the PRIMARY locator (say, a `data-test` attribute) is genuinely broken,
while a lower-priority one (say, its CSS selector) keeps working.

WHAT "repairing" means in THIS framework (read this before the code):
  - `locators/<page>_page.json` already stores SEVERAL locator
    strategies for the same element side by side (see Agent 7). This
    agent does not invent a brand-new selector value by inspecting a
    live page - that would need the DOM/visual-comparison step the
    full spec describes under Agent 11's steps 2-6, which needs a real
    AI model or an open browser (see the Phase 2 note in
    self_healing/resolver.py). What it CAN do honestly, using only the
    healing log, is flag which stored tier has become unreliable and
    record which tier is now carrying that element in practice.
  - Because pages/base_page.py loads locators/*.json FRESH every time a
    page object is built (see `_load_locators`), updating that JSON
    file is a real, immediate repair - no Python page-object code needs
    to be regenerated or touched for this kind of fix.

Following the spec's own rule ("If confidence > 90%: Automatically heal
locator"), this agent:
  - AUTO-APPLIES the repair (writes it straight into locators/*.json)
    when the working fallback tier's confidence is above 90%.
  - Otherwise just SUGGESTS it in reports/auto_repair_report.txt, for a
    human to confirm.

Every auto-applied repair is also appended to self_healing/repair_log.json
- a permanent, append-only audit trail of every change this agent has
ever made on its own.

Run this AFTER a pytest run that produced some self-healing events:

    python agents/auto_repair_agent.py
================================================================================
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.ai_client import ai_client  # noqa: E402
from utils.logger import get_logger  # noqa: E402

logger = get_logger("agent.auto_repair")

HEALING_LOG_PATH = ROOT / "self_healing" / "healing_log.json"
REPAIR_LOG_PATH = ROOT / "self_healing" / "repair_log.json"
LOCATORS_DIR = ROOT / "locators"
REPORT_TEXT = ROOT / "reports" / "auto_repair_report.txt"

# Matches the spec's own worked example: "If confidence > 90%:
# Automatically heal locator."
AUTO_APPLY_CONFIDENCE_THRESHOLD = 90

# Same priority order resolver.py tries elements in - used here to work
# out which tier COUNTS as "primary" for a given locator entry (the
# highest-priority tier that actually has a value stored).
_TIER_PRIORITY = ["data_test", "role", "text", "css", "xpath"]


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def _primary_tier(entry: dict) -> str | None:
    for tier in _TIER_PRIORITY:
        if entry.get(tier):
            return tier
    return None


def generate_repairs() -> dict:
    """Reads self_healing/healing_log.json, groups events by (page,
    element), and either auto-applies or suggests a repair for every
    element that has needed a fallback locator at least once. Returns
    (and writes to reports/) {"applied": [...], "pending_review": [...]}."""
    logger.info("Agent 14 (Auto Repair Agent): scanning healing_log.json for repeat fallbacks ...")

    ai_client.complete(
        system_prompt=(
            "You are Agent 14: Auto Repair Agent. Given a history of "
            "self-healing locator fallback events, decide which locators "
            "should be repaired and generate the updated locator data."
        ),
        user_prompt="(Phase 2: the actual healing_log.json contents would be sent here.)",
    )  # Always None today - falls back to the rule-based repair logic below.

    healing_log = _load_json(HEALING_LOG_PATH, [])
    if not healing_log:
        logger.info("Agent 14: no self-healing events logged yet - nothing to repair.")
        summary = {"applied": [], "pending_review": []}
        REPORT_TEXT.parent.mkdir(parents=True, exist_ok=True)
        REPORT_TEXT.write_text(render_text_report(summary))
        return summary

    # Group events by (page, element) so a repair decision is based on
    # an element's FULL history, not a single lucky/unlucky run.
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for entry in healing_log:
        grouped[(entry["page"], entry["element"])].append(entry)

    applied: list[dict] = []
    pending: list[dict] = []

    for (page, element), events in grouped.items():
        healed_events = [e for e in events if e.get("healed")]
        if not healed_events:
            continue  # this element's primary locator has never needed a fallback - nothing to do

        latest = healed_events[-1]
        confidence = latest.get("confidence", 0)

        locator_path = LOCATORS_DIR / f"{page}_page.json"
        locator_data = _load_json(locator_path, {})
        entry = locator_data.get(element)
        if entry is None:
            continue  # locator file doesn't know this element (shouldn't normally happen)

        old_primary = _primary_tier(entry)
        working_tier = latest["strategy_used"]

        repair = {
            "page": page,
            "element": element,
            "old_primary_tier": old_primary,
            "working_tier": working_tier,
            "confidence": confidence,
            "times_fallen_back": len(healed_events),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if confidence > AUTO_APPLY_CONFIDENCE_THRESHOLD and old_primary != working_tier:
            entry["flagged_unreliable_tier"] = old_primary
            entry["last_verified_working_tier"] = working_tier
            entry["last_repaired_at"] = repair["timestamp"]
            locator_data[element] = entry
            locator_path.write_text(json.dumps(locator_data, indent=2))

            repair["applied"] = True
            applied.append(repair)
            logger.warning(
                "Agent 14: AUTO-REPAIRED locators/%s_page.json -> '%s': flagged '%s' as unreliable, "
                "verified fallback '%s' works (confidence %d%%)",
                page, element, old_primary, working_tier, confidence,
            )
        else:
            repair["applied"] = False
            pending.append(repair)

    if applied:
        history = _load_json(REPAIR_LOG_PATH, [])
        history.extend(applied)
        REPAIR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPAIR_LOG_PATH.write_text(json.dumps(history, indent=2))

    summary = {"applied": applied, "pending_review": pending}
    REPORT_TEXT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_TEXT.write_text(render_text_report(summary))
    logger.info(
        "Agent 14 output: %d repair(s) auto-applied, %d flagged for human review",
        len(applied), len(pending),
    )
    return summary


def render_text_report(summary: dict) -> str:
    lines: list[str] = []
    if summary["applied"]:
        lines.append(f"AUTO-REPAIRED (confidence > {AUTO_APPLY_CONFIDENCE_THRESHOLD}%):")
        for r in summary["applied"]:
            lines += [
                f"  {r['page']}.{r['element']}",
                "    Old:",
                f"      {r['old_primary_tier']}",
                "    New:",
                f"      {r['working_tier']}",
                f"    Confidence: {r['confidence']}%",
                "",
            ]
    if summary["pending_review"]:
        lines.append("FLAGGED FOR HUMAN REVIEW (confidence at or below the auto-apply threshold):")
        for r in summary["pending_review"]:
            lines.append(
                f"  {r['page']}.{r['element']} - fell back to '{r['working_tier']}' "
                f"({r['times_fallen_back']} time(s), confidence {r['confidence']}%)"
            )
    if not lines:
        lines.append("No repeat fallbacks found in self_healing/healing_log.json - "
                      "every locator's primary tier is working fine.")
    return "\n".join(lines)


if __name__ == "__main__":
    result = generate_repairs()
    print(render_text_report(result))