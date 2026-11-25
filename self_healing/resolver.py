"""
================================================================================
 AGENT 7 + AGENT 11 - THE LOCATOR AGENT AND THE SELF-HEALING AGENT
================================================================================
THINK OF IT LIKE: giving a delivery driver five different ways to find a
house, instead of just one.

If you give a driver ONLY the house's exact street address, and the
street is renamed, the driver is stuck. But if you also give them the
owner's name, a description of the house, and its GPS coordinates, a
small change in ONE of those clues doesn't stop them from finding the
house - they just use the next clue that still works.

That is exactly what "self-healing locators" means here. For every
element on a page (a button, a text box...), we don't store ONE way to
find it - we store SEVERAL, ranked from most-trustworthy to
least-trustworthy:

    1. data-test / data-testid  (a locator the developers put there on
       purpose, specifically so tools like ours would use it - the
       most stable option, because a developer has to break it on
       purpose)
    2. role + name              (e.g. "the button whose accessible role
       is 'button' and whose name is 'Login'" - very stable, because it
       reflects what the element IS, not how it happens to be styled)
    3. visible text              (e.g. "the element that says 'Login'" -
       stable unless the wording changes)
    4. CSS selector              (e.g. "#login-button" - can break if a
       developer renames an id or class)
    5. XPath                     (a path through the page's structure -
       the LEAST stable, because it can break just from re-arranging
       elements, even if nothing about them actually changed)

WHY does the order matter? Because we always want to try the most
reliable clue first, and only fall back to a shakier one if we have to.
The framework spec calls this "self-healing": if a locator quietly
starts failing (say, the CSS class changed), we don't want the whole
test to crash - we want it to notice, and quietly try the next-best
clue instead, then LOG that it had to do so. A human can later glance at
that log and update the primary locator, instead of a test just
mysteriously turning red.

THIS FILE does two things:
  1. `resolve()` - given an element's locator entry (several possible
     clues) and a live Playwright page, tries each clue in priority
     order and returns the first one that actually finds the element.
  2. It writes every attempt to self_healing/healing_log.json, so you
     have a permanent record of which locators are quietly relying on a
     fallback - the exact "locator memory" the spec describes.
================================================================================
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page

from utils.logger import get_logger

logger = get_logger("self_healing")

ROOT = Path(__file__).resolve().parent.parent
HEALING_LOG_PATH = ROOT / "self_healing" / "healing_log.json"

# Rough, made-up-but-reasonable "confidence" score per tier, standing in
# for the DOM/visual/text-similarity comparison the full spec describes
# (steps 2-6 under Agent 11). A real implementation could compute this
# from actual similarity scoring; this keeps the framework runnable
# without any of that machinery.
_TIER_CONFIDENCE = {
    "data_test": 99,
    "role": 92,
    "text": 85,
    "css": 78,
    "xpath": 60,
}


class ElementNotFoundError(Exception):
    """Raised when NONE of an element's known locators can find it."""


def resolve(page: Page, page_name: str, element_name: str, locator_entry: dict[str, Any]) -> Locator:
    """
    Try each locator strategy for one element, in priority order, and
    return the first Playwright Locator that actually matches something
    on the page. Logs which tier was used (and healing_log.json remembers
    it) so the "primary" locator can be reviewed and fixed later.
    """
    attempts: list[tuple[str, Locator | None]] = [
        ("data_test", _try_data_test(page, locator_entry)),
        ("role", _try_role(page, locator_entry)),
        ("text", _try_text(page, locator_entry)),
        ("css", _try_css(page, locator_entry)),
        ("xpath", _try_xpath(page, locator_entry)),
    ]

    # The "primary" tier is the highest-priority strategy this element
    # actually *has a value for* - e.g. if an element has no data_test
    # and no role, but does have a css selector, css IS its primary
    # locator, not a fallback. "Healed" should only mean "we skipped
    # past a defined, higher-priority locator because it stopped
    # matching" - not "this element happens to rank low."
    defined_tiers = [tier for tier, locator in attempts if locator is not None]
    primary_tier = defined_tiers[0] if defined_tiers else None

    # A locator has to match EXACTLY ONE element to count as "found" -
    # not "at least one". This matters a lot on real, busy pages: a
    # product-grid page (or any list of similar rows - a to-do list, an
    # admin table...) very often has SEVERAL buttons that all say the
    # same visible text ("Add to cart" on every product, "Delete" on
    # every row). A locator that matches several of them isn't actually
    # a resolution - clicking it would either crash outright (Playwright
    # refuses to guess which one you meant) or silently click the WRONG
    # one. Real bug this caught: SauceDemo's live inventory page has 6
    # products, all with "Add to cart" buttons - the generic `text` tier
    # matched all 6 and crashed, even though the far more specific `css`
    # tier (a unique per-product id) would have worked fine. So an
    # ambiguous (>1) match is treated the same as a zero match here:
    # keep trying the next, more specific clue instead of accepting it.
    ambiguous_tiers: list[str] = []
    for tier, locator in attempts:
        if locator is None:
            continue
        try:
            count = locator.count()
        except Exception:  # noqa: BLE001 - a bad selector should not crash the run
            continue
        if count == 1:
            healed = tier != primary_tier
            _record_attempt(page_name, element_name, tier, healed)
            if healed:
                logger.warning(
                    "Self-healing: '%s.%s' found via fallback tier '%s' "
                    "(primary locator may need updating)",
                    page_name, element_name, tier,
                )
            return locator
        if count > 1:
            ambiguous_tiers.append(tier)

    detail = f"Tried: {[t for t, l in attempts if l is not None]}"
    if ambiguous_tiers:
        detail += (
            f". {ambiguous_tiers} matched MORE THAN ONE element on the page - "
            "too ambiguous to click/fill safely, not treated as a match."
        )
    raise ElementNotFoundError(
        f"None of the known locators for '{page_name}.{element_name}' resolved to exactly one "
        f"element. {detail}"
    )


def _try_data_test(page: Page, entry: dict) -> Locator | None:
    value = entry.get("data_test") or entry.get("id")
    if not value:
        return None
    return page.locator(f'[data-test="{value}"]')


def _try_role(page: Page, entry: dict) -> Locator | None:
    role = entry.get("role")
    if not role:
        return None
    name = entry.get("name")
    return page.get_by_role(role, name=name) if name else page.get_by_role(role)


def _try_text(page: Page, entry: dict) -> Locator | None:
    text = entry.get("text")
    if not text:
        return None
    return page.get_by_text(text, exact=False)


def _try_css(page: Page, entry: dict) -> Locator | None:
    css = entry.get("css")
    if not css:
        return None
    return page.locator(css)


def _try_xpath(page: Page, entry: dict) -> Locator | None:
    xpath = entry.get("xpath")
    if not xpath:
        return None
    return page.locator(f"xpath={xpath}")


def _record_attempt(page_name: str, element_name: str, tier: str, healed: bool) -> None:
    HEALING_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    history = []
    if HEALING_LOG_PATH.exists():
        try:
            history = json.loads(HEALING_LOG_PATH.read_text())
        except json.JSONDecodeError:
            history = []

    history.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "page": page_name,
        "element": element_name,
        "strategy_used": tier,
        "healed": healed,
        "confidence": _TIER_CONFIDENCE.get(tier, 50),
    })
    HEALING_LOG_PATH.write_text(json.dumps(history, indent=2))