"""
================================================================================
 AGENT 7 - THE LOCATOR DISCOVERY AGENT (real DOM scraping)
================================================================================
THINK OF IT LIKE: a building inspector who walks through a real house
with a clipboard, writing down exactly where every light switch, door
handle and window latch is - instead of someone guessing from an old
blueprint.

Earlier versions of this framework had locators/*.json HAND-TYPED by a
human who already knew SauceDemo's HTML. This agent replaces that: you
give it a REAL URL, it opens an actual browser (Playwright), visits the
page, and reads the ACTUAL DOM to find every clickable/fillable element
on screen - then writes locators/<story>/<page_name>.json in the exact
same schema the rest of the framework already understands (data_test,
role, name, placeholder, text, css, xpath), plus one new field: "kind"
("click" / "fill" / "toggle" / "text"), which agents/pom_generator_agent.py
uses to decide what KIND of method to generate for each element.

EVERY DISCOVERY IS SCOPED TO ONE STORY (`--story`). WHY: two different
stories can point at two completely different websites, and both will
very often want to discover a page named "login". If everything landed
in one shared, global locators/ folder, the second story's "login"
would silently overwrite the first story's. Scoping every discovery
under locators/<story>/ instead means "login" can mean a different
website in two different stories at once, with zero collision - see
utils/fixture_factory.py's docstring for how the generated tests stay
isolated too. (The framework's original hand-typed locators/*.json -
no story folder - are untouched leftovers from before this existed;
Flow A still reads them directly and this agent never touches them.)

WHY multiple locator strategies per element, captured all at once?
Exactly the same reason as before (see self_healing/resolver.py's
docstring) - a `data-testid`/`data-test` attribute is the most stable
thing to find an element by, then role+name, then visible text, then
CSS, then XPath as a last resort. This agent captures ALL of them for
every element in one visit, so the self-healing resolver has real
fallbacks to try later, not just one brittle selector.

HOW ELEMENTS ARE FOUND:
A single JavaScript snippet (see _EXTRACTOR_JS below) runs INSIDE the
browser page and collects every <input>, <textarea>, <select>,
<button>, <a href>, and anything with an interactive ARIA role. For
each one it works out:
  - a role (explicit `role="..."` attribute, or a sensible default
    based on the tag - e.g. <button> -> "button")
  - a stable-as-possible CSS selector (prefers #id or a data-test
    attribute; falls back to a short parent-chain selector)
  - an XPath (prefers #id; falls back to a position-based path)
  - visible text, placeholder, aria-label/name - whatever exists

LOGGING IN FIRST (some pages need it):
Pages like a shopping cart or checkout screen usually don't exist until
you're logged in - you can't just `goto()` their URL from a fresh
browser. Pass --login-first --username U --password P and this agent
will: find whichever existing page object has `auto_open = True` (the
app's entry point - see pages/base_page.py), open it, call its
`.login(username, password)` method, THEN navigate to --url and scrape
the page you actually wanted. This only works once that entry-point
page object already exists (run this agent on the login page itself
first, then run agents/pom_generator_agent.py, THEN discover pages that
need a login).

USAGE:
    # A page anyone can reach directly, no login needed:
    python agents/locator_discovery_agent.py --story login_checkout \\
        --url https://www.saucedemo.com/ --page-name login

    # A page that only exists after logging in:
    python agents/locator_discovery_agent.py --story login_checkout \\
        --url https://www.saucedemo.com/inventory.html --page-name inventory \\
        --login-first --username standard_user --password secret_sauce

    # Any local file works too - no internet needed - handy for testing:
    python agents/locator_discovery_agent.py --story my_story \\
        --url file:///path/to/some_page.html --page-name my_page

Usually you won't run this directly at all - `agents/orchestrator.py
--story <name>` (the "brain") calls this for you, reading the URL from
your .env file's BASE_URL. Use this file directly only when you want to
discover ONE extra page on its own.
================================================================================
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import datetime, timezone  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

from rag import knowledge_base as rag  # noqa: E402
from utils.logger import get_logger  # noqa: E402
from utils.text import slugify  # noqa: E402

logger = get_logger("agent.locator_discovery")

LOCATORS_DIR = ROOT / "locators"
PAGES_DIR = ROOT / "pages"

# Runs INSIDE the browser page (page.evaluate). Finds every interactive
# element and returns a plain-JSON-friendly description of each one.
_EXTRACTOR_JS = r"""
() => {
  function cssPath(el) {
    if (el.id) return '#' + CSS.escape(el.id);
    const dt = el.getAttribute('data-testid') || el.getAttribute('data-test');
    if (dt) return `[data-test${el.getAttribute('data-testid') ? 'id' : ''}="${dt}"]`;
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 6) {
      let sel = node.tagName.toLowerCase();
      if (node.className && typeof node.className === 'string' && node.className.trim()) {
        sel += '.' + node.className.trim().split(/\s+/).slice(0, 2).join('.');
      }
      const parent = node.parentElement;
      if (parent) {
        const sameTag = Array.from(parent.children).filter(c => c.tagName === node.tagName);
        if (sameTag.length > 1) sel += `:nth-of-type(${sameTag.indexOf(node) + 1})`;
      }
      parts.unshift(sel);
      node = parent;
    }
    return parts.join(' > ');
  }
  function xPath(el) {
    if (el.id) return `//*[@id="${el.id}"]`;
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1) {
      let index = 1, sib = node.previousElementSibling;
      while (sib) { if (sib.tagName === node.tagName) index++; sib = sib.previousElementSibling; }
      parts.unshift(`${node.tagName.toLowerCase()}[${index}]`);
      node = node.parentElement;
    }
    return '/' + parts.join('/');
  }
  function impliedRole(el) {
    const tag = el.tagName.toLowerCase();
    if (tag === 'button') return 'button';
    if (tag === 'a') return 'link';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      const t = (el.getAttribute('type') || 'text').toLowerCase();
      if (t === 'checkbox') return 'checkbox';
      if (t === 'radio') return 'radio';
      if (t === 'submit' || t === 'button') return 'button';
      return 'textbox';
    }
    return null;
  }
  const nodes = Array.from(document.querySelectorAll(
    "input, textarea, select, button, a[href], [role='button'], [role='link'], " +
    "[role='textbox'], [role='checkbox'], [role='radio'], [onclick]"
  ));
  return nodes
    .filter(el => el.offsetParent !== null || el.tagName.toLowerCase() === 'a')
    .map(el => ({
      tag: el.tagName.toLowerCase(),
      id: el.id || null,
      data_test: el.getAttribute('data-testid') || el.getAttribute('data-test') || null,
      role: el.getAttribute('role') || impliedRole(el),
      name: el.getAttribute('aria-label') || el.getAttribute('name') || null,
      placeholder: el.getAttribute('placeholder') || null,
      text: ((el.innerText || el.value || '').trim().slice(0, 60)) || null,
      css: cssPath(el),
      xpath: xPath(el),
    }));
}
"""

# role -> what KIND of page-object method this element should become.
_ROLE_TO_KIND = {
    "button": "click", "link": "click", "menuitem": "click", "tab": "click",
    "textbox": "fill", "searchbox": "fill", "combobox": "fill",
    "checkbox": "toggle", "radio": "toggle",
}


def _element_key(raw: dict, used: set[str]) -> str:
    """Pick a readable, unique dict key for one discovered element,
    preferring the most human-meaningful identifier available."""
    candidate = (
        raw.get("data_test") or raw.get("id") or raw.get("name")
        or raw.get("placeholder") or raw.get("text") or raw.get("tag")
    )
    base = slugify(str(candidate))
    if raw.get("tag") == "input" and not base.endswith(("input", "field")):
        base = f"{base}_input"
    key, i = base, 2
    while key in used:
        key = f"{base}_{i}"
        i += 1
    used.add(key)
    return key


def _discover_on_page(pw_page, page_name: str) -> dict[str, dict[str, Any]]:
    raw_elements = pw_page.evaluate(_EXTRACTOR_JS)
    logger.info("Agent 7: found %d interactive element(s) on the live page", len(raw_elements))

    locators: dict[str, dict[str, Any]] = {}
    used_keys: set[str] = set()
    for raw in raw_elements:
        key = _element_key(raw, used_keys)
        role = raw.get("role")
        locators[key] = {
            "page": page_name,
            "element": key,
            "data_test": raw.get("data_test"),
            "role": role,
            "name": raw.get("name"),
            "placeholder": raw.get("placeholder"),
            "text": raw.get("text"),
            "css": raw.get("css"),
            "xpath": raw.get("xpath"),
            "kind": _ROLE_TO_KIND.get(role, "text"),
        }
    return locators


def _generic_login(entry_page, username: str, password: str) -> None:
    """Logs in using whatever fields the entry page's OWN locator file
    says it has - no hand-written `.login()` method required.

    WHY this exists: --login-first used to only work if the entry page
    happened to already have a hand-written `.login(username, password)`
    method (like this project's original SauceDemo pages do). But a page
    object THIS agent just auto-generated (via pom_generator_agent.py)
    only ever gets one small method per element - fill_username_input,
    fill_password_input, click_login_button - never a combined "login"
    convenience method, because nothing told it those three belong
    together. So discovering a brand-new site's second page (which needs
    logging in first) would fail right after discovering the first page,
    which defeats the point of automatic discovery.

    Instead, this looks at the SAME locators/*.json file every generated
    method already came from and guesses, by NAME, which entry is the
    username box, which is the password box, and which is the submit
    button - then drives them with BasePage's own generic fill()/click()
    (the same ones every generated method calls) - no bespoke method
    needed on the page object at all.

    A hand-written page's real `.login()` method (if it has one) is
    always tried FIRST and preferred when present - it's more reliable
    than guessing, since a human wrote it on purpose."""
    if hasattr(entry_page, "login"):
        entry_page.login(username, password)
        return

    locators = entry_page._locators  # the exact dict every generated method already reads from

    def _find(*needles: str, kind_hint: str | None = None) -> str | None:
        for key, entry in locators.items():
            if kind_hint and entry.get("kind") != kind_hint:
                continue
            if any(needle in key.lower() for needle in needles):
                return key
        return None

    user_key = _find("user", "email", "login", kind_hint="fill") or _find("user", "email", "login")
    pass_key = _find("pass", kind_hint="fill") or _find("pass")
    submit_key = _find("login", "submit", "sign", kind_hint="click") or _find("login", "submit", "sign")

    if not (user_key and pass_key and submit_key):
        raise RuntimeError(
            "--login-first: couldn't work out which locators are the username/password/"
            "submit fields on the entry page just from their names. Give the entry page "
            "a hand-written .login(username, password) method instead, or rename the "
            "relevant elements so they contain 'user'/'pass'/'login' in their key."
        )

    entry_page.fill(user_key, username)
    entry_page.fill(pass_key, password)
    entry_page.click(submit_key)


def _find_entry_page_class(story: str):
    """Scans pages/<story>/*.py (NOT the global pages/ folder - see the
    module docstring) for the one page-object class with auto_open =
    True (this story's login/landing page) and returns the class
    object."""
    story_pages_dir = PAGES_DIR / story
    for path in sorted(story_pages_dir.glob("*_page.py")):
        module = importlib.import_module(f"pages.{story}.{path.stem}")
        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, type) and getattr(obj, "auto_open", False):
                return obj
    return None


def discover(
    url: str,
    page_name: str,
    story: str,
    login_first: bool = False,
    username: str | None = None,
    password: str | None = None,
    headless: bool = True,
) -> Path:
    """Opens a real (or local file://) page, logs in first if asked,
    scrapes every interactive element, and writes
    locators/<story>/<page_name>_page.json. Returns the path written.

    `story` scopes EVERYTHING this call touches - where it reads an
    existing entry page from (for --login-first) and where it writes
    to - so discovering pages for one story never reads or overwrites
    another story's locators, even if both happen to use the same
    page_name (e.g. "login"). See the module docstring."""
    logger.info("Agent 7 (Locator Discovery Agent): visiting %s as '%s' (story: %s)", url, page_name, story)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        pw_page = browser.new_page()
        try:
            if login_first:
                entry_cls = _find_entry_page_class(story)
                if entry_cls is None:
                    raise RuntimeError(
                        f"--login-first was given, but no page object in pages/{story}/ has "
                        "auto_open = True yet. Discover + generate this story's login page first."
                    )
                logger.info("Agent 7: logging in via %s before scraping", entry_cls.__name__)
                entry_page = entry_cls(pw_page)
                entry_page.open()
                _generic_login(entry_page, username, password)

            pw_page.goto(url)
            pw_page.wait_for_load_state("networkidle")
            locators = _discover_on_page(pw_page, page_name)
        finally:
            browser.close()

    if not locators:
        logger.warning("Agent 7: no interactive elements found at %s - is the page fully loaded?", url)

    # RAG check (informational only - the live DOM is always the source
    # of truth, so this never blocks writing the file): warn if a page
    # with very similar elements already exists (in ANY story - this
    # check intentionally looks across story boundaries, since "you
    # already built something very like this for another story" is
    # useful to know even though the two are never auto-merged). The
    # index key is story-qualified so two stories' same-named pages
    # never overwrite each other's entry in the knowledge base either.
    rag_key = f"{story}:{page_name}"
    query = " ".join([page_name] + list(locators.keys()))
    matches = rag.search_page_objects(query, top_k=2, exclude_key=rag_key)
    for match in matches:
        if match["score"] >= 0.3:
            logger.warning(
                "Agent 7: '%s' looks similar (%.0f%% word overlap) to already-discovered "
                "page '%s' - double check this isn't a duplicate.",
                rag_key, match["score"] * 100, match["key"],
            )

    story_locators_dir = LOCATORS_DIR / story
    story_locators_dir.mkdir(parents=True, exist_ok=True)
    out_path = story_locators_dir / f"{page_name}_page.json"
    out_path.write_text(json.dumps(locators, indent=2))

    # A small companion file recording WHERE this page lives, so
    # agents/pom_generator_agent.py can work out the page object's
    # `path` (relative to config.BASE_URL) without guessing.
    meta_path = story_locators_dir / f"{page_name}_page.meta.json"
    meta_path.write_text(json.dumps({
        "page_name": page_name,
        "story": story,
        "url": url,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "element_count": len(locators),
    }, indent=2))

    logger.info("Agent 7 output: %d element(s) written to %s", len(locators), out_path)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover real locators from a live (or local) web page, scoped to one story.")
    parser.add_argument("--story", required=True, help="Story this page belongs to, e.g. 'login_checkout' -> locators/login_checkout/<page>_page.json")
    parser.add_argument("--url", required=True, help="Page to visit, e.g. https://example.com/login")
    parser.add_argument("--page-name", required=True, help="Short name, e.g. 'login' -> locators/<story>/login_page.json")
    parser.add_argument("--login-first", action="store_true", help="Log in via this story's entry-point page object first")
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--headed", action="store_true", help="Show the browser instead of running invisibly")
    args = parser.parse_args()

    if args.login_first and not (args.username and args.password):
        parser.error("--login-first requires --username and --password")

    discover(
        url=args.url,
        page_name=args.page_name,
        story=args.story,
        login_first=args.login_first,
        username=args.username,
        password=args.password,
        headless=not args.headed,
    )


if __name__ == "__main__":
    main()