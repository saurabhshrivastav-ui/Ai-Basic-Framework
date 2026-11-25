"""
================================================================================
 conftest.py - SHARED TEST SETUP (FIXTURES) FOR THE WHOLE FRAMEWORK
================================================================================
THINK OF IT LIKE: the pre-flight checklist before every flight takes off.

Every test needs a browser tab open, the right page objects built on top
of it, and its test data loaded, before it can do anything useful.
Instead of repeating that in every test file, pytest lets us write it
ONCE here. Anything defined below as a `@pytest.fixture` becomes
available to any test simply by asking for it as a function argument -
e.g. `def test_x(login_page, inventory_page): ...`.

`pytest-playwright` (installed via requirements.txt) already provides a
ready-to-use `page` fixture (one open browser tab per test, closed
automatically afterwards). Everything below builds on top of that one
fixture.

WHY the page-object fixtures below are built DYNAMICALLY instead of
hand-written (like `def login_page(page): return LoginPage(page)`):
agents/pom_generator_agent.py can create a brand-new pages/<x>_page.py
file at any time. If every fixture had to be hand-added here first, a
freshly generated page object would be unusable until a human
remembered to wire it up. Instead, this file scans pages/*_page.py
itself, finds every Page Object class, and builds a matching fixture
for each one automatically - a generated page is testable the moment
it exists, with zero manual steps. The actual scanning/registering
logic lives in utils/fixture_factory.py, shared with a second copy of
this idea - see that file's docstring for why.

NOTE - this root conftest.py only ever looks at the GLOBAL pages/
folder (Flow A's hand-written pages: login_page, inventory_page,
cart_page, checkout_page). Every Flow B story generated via
`agents/orchestrator.py --story <name>` gets its OWN, separate
pages/<story>/ folder and its OWN small conftest.py inside
tests/generated/<story>/ (auto-written by agents/script_writer_agent.py)
- so two different stories' page objects (very often both named
"login_page"!) never collide. See utils/fixture_factory.py's docstring
for the full reasoning.

This file also auto-saves a screenshot the moment a test fails, so you
never have to guess what the screen looked like when something broke -
this covers Agent 8's "Screenshots" responsibility and Agent 12's
"collect screenshots on failure." This hook applies to EVERY test in
the whole project, including Flow B's, since pytest hooks (unlike
fixtures) aren't folder-scoped the way this file's page fixtures are.
================================================================================
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from playwright.sync_api import Page  # noqa: E402

from utils.fixture_factory import register_page_fixtures  # noqa: E402
from utils.logger import get_logger  # noqa: E402

logger = get_logger("conftest")

SCREENSHOTS_DIR = ROOT / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
DATA_PATH = ROOT / "data" / "test_data.json"
PAGES_DIR = ROOT / "pages"


# -------------------------------------------------------------------- #
# Test data fixture
# -------------------------------------------------------------------- #
@pytest.fixture
def test_data() -> dict:
    """Loads data/test_data.json, produced by Agent 5 (Test Data Agent).

    Run `python agents/orchestrator.py` once before your first test run
    if this file doesn't exist yet.
    """
    if not DATA_PATH.exists():
        pytest.skip(
            "data/test_data.json not found - run "
            "`python agents/orchestrator.py` once first."
        )
    return json.loads(DATA_PATH.read_text())


# -------------------------------------------------------------------- #
# Page object fixtures - auto-discovered, matching the spec's own
# example: def test_purchase_plan(login_page, plan_page, payment_page): ...
# Global pages/ only (Flow A) - see the module docstring for why Flow B
# stories get their own separate conftest.py instead of being included
# here too.
# -------------------------------------------------------------------- #
register_page_fixtures(globals(), PAGES_DIR, "pages", log_label="conftest (root/Flow A)")


# -------------------------------------------------------------------- #
# Automatic screenshot-on-failure
# -------------------------------------------------------------------- #
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    Runs after every phase of every test. We only act when a test's
    actual body fails (the "call" phase) - that's the moment we grab a
    screenshot from whatever `page` fixture the test used, and attach it
    to the Allure report if Allure is available.
    """
    outcome = yield
    report = outcome.get_result()

    if report.when == "call" and report.failed:
        page: Page | None = item.funcargs.get("page")
        if page is not None:
            screenshot_path = SCREENSHOTS_DIR / f"{item.name}.png"
            try:
                page.screenshot(path=str(screenshot_path))
                logger.error(
                    "Test '%s' FAILED - screenshot saved to %s",
                    item.name, screenshot_path,
                )
                try:
                    import allure
                    allure.attach.file(
                        str(screenshot_path),
                        name="failure-screenshot",
                        attachment_type=allure.attachment_type.PNG,
                    )
                except ImportError:
                    pass
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not capture failure screenshot: %s", exc)