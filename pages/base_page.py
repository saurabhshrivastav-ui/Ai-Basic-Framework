"""
================================================================================
 pages/base_page.py - SHARED CODE EVERY PAGE OBJECT BUILDS ON
================================================================================
THINK OF IT LIKE: a universal remote control.

Every page object below (LoginPage, InventoryPage, CartPage,
CheckoutPage) needs to do the same handful of things: open a URL, find
an element on screen, click something, type into something. Instead of
writing that logic five times, we write it ONCE here, and every page
object "inherits" it - the same way every room in a house can share one
universal remote instead of each room getting its own reinvented one.

WHY does this matter for Page Object Model (POM) rules?
  - "No assertions inside page objects" - this file (and every page
    object built on it) only ever DOES things or RETURNS information.
    It never calls `assert`. Checking whether something is correct is
    the test's job, not the page's job - see PAGE OBJECT RULES in the
    original spec.
  - "Use environment-based URLs" - `self.base_url` comes from
    utils/config.py, never a URL typed directly into this file.
  - Every element lookup goes through the self-healing resolver
    (self_healing/resolver.py), so if SauceDemo tweaks its HTML, the
    framework tries a fallback locator instead of breaking outright.
================================================================================
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page

from self_healing.resolver import resolve
from utils.config import config
from utils.logger import get_logger

ROOT = Path(__file__).resolve().parent.parent
LOCATORS_DIR = ROOT / "locators"


class BasePage:
    # Every subclass sets this to match its locator JSON file's name,
    # e.g. "login_page" -> locators/login_page.json
    locator_file: str = ""
    # The path this page lives at, relative to config.BASE_URL.
    path: str = ""
    # Set to True only on the ONE page that is the app's entry point
    # (e.g. the login page). conftest.py's dynamic fixture factory reads
    # this flag and calls .open() automatically for that page only - every
    # other page is reached by clicking through the app, not by visiting
    # a URL directly, so they leave this False.
    auto_open: bool = False

    def __init__(self, page: Page):
        self.page = page
        self.base_url = config.BASE_URL
        self.logger = get_logger(f"page.{self.locator_file or 'base'}")
        self._locators: dict[str, dict[str, Any]] = self._load_locators()

    # ---------------------------------------------------------------- #
    # Navigation
    # ---------------------------------------------------------------- #
    def open(self) -> None:
        url = self.base_url.rstrip("/") + "/" + self.path.lstrip("/")
        self.logger.info("Navigating to %s", url)
        self.page.goto(url)

    # ---------------------------------------------------------------- #
    # Element lookup (self-healing)
    # ---------------------------------------------------------------- #
    def element(self, name: str) -> Locator:
        """
        Return a Playwright Locator for the named element, defined in
        this page's locators/*.json file. Tries multiple strategies in
        priority order (see self_healing/resolver.py) so small HTML
        changes don't automatically break every test.
        """
        entry = self._locators.get(name)
        if entry is None:
            raise KeyError(
                f"No locator named '{name}' in locators/{self.locator_file}.json"
            )
        page_name = self.locator_file.replace("_page", "")
        return resolve(self.page, page_name, name, entry)

    # ---------------------------------------------------------------- #
    # Small reusable actions (no assertions - see class docstring)
    # ---------------------------------------------------------------- #
    def click(self, name: str) -> None:
        self.element(name).click()

    def fill(self, name: str, value: str) -> None:
        self.element(name).fill(value)

    def text_of(self, name: str) -> str:
        return self.element(name).inner_text()

    def is_visible(self, name: str) -> bool:
        return self.element(name).is_visible()

    def current_url(self) -> str:
        return self.page.url

    # ---------------------------------------------------------------- #
    # Internal helpers
    # ---------------------------------------------------------------- #
    def _load_locators(self) -> dict[str, dict[str, Any]]:
        if not self.locator_file:
            return {}
        locator_path = LOCATORS_DIR / f"{self.locator_file}.json"
        if not locator_path.exists():
            return {}
        return json.loads(locator_path.read_text())