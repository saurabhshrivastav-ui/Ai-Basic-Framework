"""
================================================================================
 utils/fixture_factory.py - SHARED DYNAMIC PAGE-OBJECT FIXTURE FACTORY
================================================================================
THINK OF IT LIKE: a vending machine that builds a pytest fixture for
every page object it finds in a folder. Used in TWO places in this
project, and this file exists so the tricky part of that logic (see the
`name=` comment below) only has to be written once:

  1. conftest.py (project root) - registers a fixture for every
     hand-written page in pages/*.py (Flow A: login_page, inventory_page,
     cart_page, checkout_page - one shared app, unchanged since before
     this file existed).

  2. Every tests/generated/<story>/conftest.py (auto-written by
     agents/script_writer_agent.py) - registers a fixture for every page
     object Agent 6 discovered for THAT ONE story, under
     pages/<story>/*.py - and ONLY for that story.

WHY per-story isolation matters: two different stories can target two
COMPLETELY DIFFERENT websites, and both will very often have a page
named "login" (agents/orchestrator.py even defaults ENTRY_PAGE_NAME to
"login" for every story). If every story shared one global pages/
folder and one global set of fixtures, story B's "login" page would
silently overwrite story A's the moment it was discovered. Story-scoped
folders (pages/<story>/) plus a story-scoped conftest.py (which pytest
only applies to tests inside that same folder) means "login_page" can
mean a completely different class in two different stories' tests at
the same time, with zero collision - pytest resolves fixtures from the
CLOSEST conftest.py to the test file, not from a single flat namespace.
================================================================================
"""
from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest
from playwright.sync_api import Page

from pages.base_page import BasePage
from utils.config import config
from utils.logger import get_logger

logger = get_logger("fixture_factory")


def discover_page_classes(pages_dir: Path, import_module_prefix: str) -> dict[str, type[BasePage]]:
    """Scans pages_dir/*_page.py for every BasePage subclass DEFINED IN
    (not just imported into) that module, and returns
    {fixture_name: class}, e.g. {"login_page": LoginPage}.

    `import_module_prefix` is the dotted Python package the files under
    pages_dir are importable as - "pages" for the global pages/ folder,
    "pages.<story_id>" for a story-scoped pages/<story_id>/ folder.
    Returns an empty dict (not an error) if pages_dir doesn't exist yet
    or has no *_page.py files - see register_page_fixtures()'s docstring
    for why that's the right behavior here."""
    discovered: dict[str, type[BasePage]] = {}
    if not pages_dir.is_dir():
        return discovered
    for path in sorted(pages_dir.glob("*_page.py")):
        module = importlib.import_module(f"{import_module_prefix}.{path.stem}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BasePage) and obj is not BasePage and obj.__module__ == module.__name__:
                discovered[path.stem] = obj
                break
    return discovered


def _make_page_fixture(fixture_name: str, page_cls: type[BasePage]):
    # `name=fixture_name` matters: pytest registers a fixture under the
    # name given to @pytest.fixture, NOT under whatever variable/module
    # attribute we assign the result to below - without this, every
    # dynamically built fixture would end up registered as "_fixture"
    # instead of e.g. "login_page", and every generated test would fail
    # to find it.
    @pytest.fixture(name=fixture_name)
    def _fixture(page: Page):
        page.set_default_timeout(config.DEFAULT_TIMEOUT_MS)
        instance = page_cls(page)
        if instance.auto_open:
            instance.open()
        return instance

    return _fixture


def register_page_fixtures(
    namespace: dict, pages_dir: Path, import_module_prefix: str, log_label: str = "conftest",
) -> list[str]:
    """Discovers every page object under pages_dir and injects a
    matching pytest fixture straight into `namespace` (pass `globals()`
    from the calling conftest.py). Returns the sorted list of fixture
    names registered, so the caller can log something useful.

    SAFE ON A MISSING/EMPTY FOLDER: if pages_dir doesn't exist yet or
    has no *_page.py files (e.g. a story whose pages haven't been
    discovered by the brain yet), this simply registers zero fixtures
    instead of crashing - the generated test file will then fail with a
    clear, ordinary pytest "fixture not found" error pointing at
    exactly what's missing, rather than pytest refusing to even start
    collecting tests."""
    discovered = discover_page_classes(pages_dir, import_module_prefix)
    for fixture_name, page_cls in discovered.items():
        namespace[fixture_name] = _make_page_fixture(fixture_name, page_cls)
    names = sorted(discovered)
    logger.info(
        "%s: registered %d page-object fixture(s) from %s: %s",
        log_label, len(names), pages_dir, ", ".join(names) or "(none yet)",
    )
    return names