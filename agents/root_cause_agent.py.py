"""
================================================================================
 AGENT 13 - THE ROOT CAUSE AGENT
================================================================================
THINK OF IT LIKE: an insurance investigator arriving after a small car
crash. They don't just write "car got damaged" - they look at the skid
marks, the dashcam, the weather report, and give a specific answer:
"the driver braked late because the road was wet," with a confidence
level, and a recommendation ("repaint the faded lane markings here").

When a test fails, this agent plays that role. It reads what evidence
this framework actually has for a failed test:

    1. The error message and stack trace Allure already saved
       (reports/allure-results/*-result.json - written automatically
       by pytest + allure-pytest, no extra setup needed).
    2. Whether the Self-Healing Agent (Agent 11, see
       self_healing/resolver.py) had to fall back to a backup locator
       for this page around the same time the test failed - that is
       strong evidence the PRIMARY locator is what broke.
    3. The failure screenshot conftest.py already saves to
       screenshots/<test name>.png.

...and turns that into exactly the shape the spec asks for:

    Failure:
    Locator Changed
    Old:
    submit_btn
    New:
    save_btn
    Confidence:
    98%

HONEST LIMITATION (Phase 1): the full spec also mentions inspecting
"Console" and "Network" data and comparing "Visual similarity" - this
framework doesn't record browser console logs, network traffic, or
screenshots-for-comparison yet (see Agent 12's status in README.md), so
those signals aren't available to reason about today. This agent uses
the two signals that DO exist (the error message/trace, and the
self-healing log) with plain pattern matching - readable, wrong less
often than a guess, and an easy thing to replace with a real AI model
later (see utils/ai_client.py) without changing anything that calls it.

Run this AFTER a pytest run (it reads files pytest + the self-healing
resolver already wrote for you):

    python agents/root_cause_agent.py
================================================================================
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.ai_client import ai_client  # noqa: E402
from utils.logger import get_logger  # noqa: E402

logger = get_logger("agent.root_cause")

ALLURE_RESULTS_DIR = ROOT / "reports" / "allure-results"
HEALING_LOG_PATH = ROOT / "self_healing" / "healing_log.json"
SCREENSHOTS_DIR = ROOT / "screenshots"
REPORT_JSON = ROOT / "reports" / "root_cause_report.json"
REPORT_TEXT = ROOT / "reports" / "root_cause_report.txt"

# How close (in seconds) a self-healing fallback event has to be to a
# test's failure time to count as evidence for THAT test. Generous on
# purpose - Phase 1 has no per-step timestamps to be more precise with.
HEALING_EVENT_WINDOW_SECONDS = 120

# Ordered rules: (regex to look for in the error message/trace, root
# cause label, confidence %, suggested fix). Checked top to bottom -
# first match wins. This is the Phase-1 stand-in for the AI-based
# trace/console/network/DOM reasoning the full spec describes.
_RULES: list[tuple[str, str, int, str]] = [
    (r"net::ERR_|ERR_CONNECTION|ERR_TUNNEL|ECONNREFUSED",
     "Network Error - the application could not be reached", 90,
     "Check that BASE_URL in .env is correct and the environment is reachable from where the test runs."),
    (r"strict mode violation",
     "Locator matches more than one element - the page structure changed", 80,
     "Narrow the locator (e.g. add/use a data-test attribute) so it matches exactly one element."),
    (r"Timeout .*exceeded|waiting for (selector|locator)",
     "Element Timeout - the locator never matched anything in time", 70,
     "Either the element loads slowly (raise DEFAULT_TIMEOUT_MS) or the locator is stale - "
     "see self_healing/healing_log.json for that element."),
    (r"Target (page|browser|context) (closed|crashed)",
     "Browser/page crashed mid-test", 60,
     "Re-run the test; if it keeps happening, check memory/resources in the environment running the tests."),
]


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def _find_recent_healing_events(healing_log: list[dict], around: datetime) -> list[dict]:
    """Self-healing events logged close to a failure are circumstantial
    but strong evidence: the element WAS found, just via a lower-priority
    fallback locator, which usually means the primary one just broke."""
    events = []
    for entry in healing_log:
        try:
            ts = datetime.fromisoformat(entry["timestamp"])
        except (KeyError, ValueError):
            continue
        if entry.get("healed") and abs((ts - around).total_seconds()) <= HEALING_EVENT_WINDOW_SECONDS:
            events.append(entry)
    return events


def _classify_by_message(text: str) -> tuple[str, int, str] | None:
    for pattern, cause, confidence, fix in _RULES:
        if re.search(pattern, text, re.IGNORECASE):
            return cause, confidence, fix
    return None


def analyze_failures() -> dict:
    """Reads every failed/broken result under reports/allure-results and
    self_healing/healing_log.json, and produces one root-cause finding
    per failure. Returns (and writes to reports/) the full result."""
    logger.info("Agent 13 (Root Cause Agent): analyzing failed tests ...")

    ai_client.complete(
        system_prompt=(
            "You are Agent 13: Root Cause Agent. Given a failing test's "
            "error message, trace, and recent self-healing events, identify "
            "the root cause, a confidence score, and a suggested fix."
        ),
        user_prompt="(Phase 2: the actual failure evidence would be sent here.)",
    )  # Always None today - falls back to the rule-based classification below.

    result_files = sorted(ALLURE_RESULTS_DIR.glob("*-result.json")) if ALLURE_RESULTS_DIR.exists() else []
    healing_log = _load_json(HEALING_LOG_PATH, [])

    findings = []
    for result_file in result_files:
        result = _load_json(result_file, {})
        if result.get("status") not in ("failed", "broken"):
            continue

        details = result.get("statusDetails") or {}
        message = details.get("message") or ""
        trace = details.get("trace") or ""
        test_name = result.get("name", result_file.stem)

        stop_ms = result.get("stop")
        healing_hits = (
            _find_recent_healing_events(healing_log, datetime.fromtimestamp(stop_ms / 1000, tz=timezone.utc))
            if stop_ms else []
        )

        if healing_hits:
            # Strongest evidence available in Phase 1: a locator actually
            # needed a fallback around the moment this test failed.
            worst = healing_hits[0]
            root_cause = (
                f"Locator Changed - '{worst['page']}.{worst['element']}' needed a fallback locator"
            )
            confidence = worst.get("confidence", 70)
            fix = (
                f"Update locators/{worst['page']}_page.json - the primary locator for "
                f"'{worst['element']}' stopped matching, but the '{worst['strategy_used']}' tier still "
                f"works. Run `python agents/auto_repair_agent.py` to flag/apply this automatically."
            )
        else:
            classification = _classify_by_message(message) or _classify_by_message(trace)
            if classification:
                root_cause, confidence, fix = classification
            else:
                root_cause = "Unknown - the error text did not match a known pattern"
                confidence = 40
                fix = "Open the screenshot below and the full error message, and review manually."

        screenshot = SCREENSHOTS_DIR / f"{test_name}.png"
        findings.append({
            "test": test_name,
            "root_cause": root_cause,
            "confidence": confidence,
            "suggested_fix": fix,
            "error_message": message.splitlines()[0] if message else "",
            "screenshot": str(screenshot.relative_to(ROOT)) if screenshot.exists() else None,
        })

    summary = {"failures_analyzed": len(findings), "findings": findings}
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(summary, indent=2))
    REPORT_TEXT.write_text(render_text_report(summary))
    logger.info("Agent 13 output: %d failure(s) analyzed", len(findings))
    return summary


def render_text_report(summary: dict) -> str:
    if not summary["findings"]:
        return "No failed/broken tests found in reports/allure-results - nothing to analyze."
    lines = []
    for f in summary["findings"]:
        lines += [
            f"Test: {f['test']}",
            "Failure:",
            f"  {f['root_cause']}",
            f"Confidence: {f['confidence']}%",
            f"Suggested Fix: {f['suggested_fix']}",
        ]
        if f["error_message"]:
            lines.append(f"Error: {f['error_message']}")
        if f["screenshot"]:
            lines.append(f"Screenshot: {f['screenshot']}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    result = analyze_failures()
    print(render_text_report(result))