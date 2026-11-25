"""
================================================================================
 tests/generated/saucedemo_checkout/conftest.py - AGENT 8 OUTPUT (auto-generated)
================================================================================
Registers a pytest fixture for every page object story 'saucedemo_checkout'
discovered (pages/saucedemo_checkout/*.py) - and ONLY this story's pages, so a
fixture like "login_page" here can never collide with another story's
same-named fixture. See utils/fixture_factory.py's docstring.

Do not hand-edit - re-run agents/script_writer_agent.py to regenerate.
================================================================================
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.fixture_factory import register_page_fixtures  # noqa: E402

register_page_fixtures(
    globals(),
    ROOT / "pages" / "saucedemo_checkout",
    "pages.saucedemo_checkout",
    log_label="conftest (tests/generated/saucedemo_checkout)",
)
