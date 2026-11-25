"""
================================================================================
 utils/config.py - ONE PLACE FOR ALL SETTINGS (NO HARDCODED URLS!)
================================================================================
WHY: the spec explicitly says "never hardcode URLs." If the base URL of
the app you're testing is typed directly inside a test file, then every
test file needs to be edited by hand when the environment changes
(e.g. testing against staging instead of production). Instead, every
test and page object reads BASE_URL from here - and this file reads it
from an environment variable (or your .env file), with one safe default
so the framework runs out of the box.
================================================================================
"""
from __future__ import annotations

import os

# Loads variables from a local .env file if python-dotenv is installed
# and a .env file exists. Safe to skip if neither is present.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


class Config:
    # The public SauceDemo practice site - our Phase 1 target app.
    # THIS is the URL the orchestrator's "brain" (agents/orchestrator.py,
    # --story mode) reads to know WHERE to discover the entry/login page
    # from - change it here (or in .env) and the orchestrator points at
    # a brand-new site with zero code changes.
    BASE_URL: str = os.environ.get("BASE_URL", "https://www.saucedemo.com/")

    # "chromium", "firefox", or "webkit"
    BROWSER: str = os.environ.get("BROWSER", "chromium")

    # Run with a visible browser window (False) or invisibly (True).
    HEADLESS: bool = os.environ.get("HEADLESS", "true").lower() == "true"

    # How long Playwright waits for something to appear, in milliseconds.
    DEFAULT_TIMEOUT_MS: int = int(os.environ.get("DEFAULT_TIMEOUT_MS", "10000"))

    # Which AI provider Phase 2 should use - "none" today.
    AI_PROVIDER: str = os.environ.get("AI_PROVIDER", "none")

    # The short name the orchestrator gives BASE_URL's own page when it
    # discovers it automatically, e.g. "login" -> pages/login_page.py,
    # locators/login_page.json. Change this if BASE_URL's landing page
    # isn't a login screen (e.g. "home").
    ENTRY_PAGE_NAME: str = os.environ.get("ENTRY_PAGE_NAME", "login")

    # Optional demo/test credentials the orchestrator uses ONLY to log in
    # while discovering pages that sit behind a login wall (--pages).
    # Never used inside a test itself - Agent 5 (Test Data Agent) still
    # generates the real data every test uses.
    DEMO_USERNAME: str = os.environ.get("DEMO_USERNAME", "")
    DEMO_PASSWORD: str = os.environ.get("DEMO_PASSWORD", "")

config = Config()