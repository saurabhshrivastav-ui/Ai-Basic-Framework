"""
================================================================================
 AGENT 6 - THE PAGE OBJECT AGENT (real code generation)
================================================================================
THINK OF IT LIKE: a furniture assembly robot. Agent 7 (see
locator_discovery_agent.py) already measured every drawer, handle and
hinge on the real piece of furniture and wrote it all down. This agent
reads that list and actually BUILDS the finished piece - a real,
importable Python file in pages/<story>/ - without a human hand-typing
it.

EVERY PAGE IS SCOPED TO ONE STORY (`--story`), matching Agent 7 - see
that file's module docstring for why (two stories, two different
websites, both wanting a page called "login"). A generated page's
`locator_file` attribute is set to "<story>/<page>_page" so
pages/base_page.py automatically reads locators/<story>/<page>_page.json
- no extra wiring needed anywhere else.

WHAT IT GENERATES, per element, based on the "kind" Agent 7 recorded:

    kind "click"   -> def click_<element>(self) -> None:
                           self.click("<element>")

    kind "fill"    -> def fill_<element>(self, value: str) -> None:
                           self.fill("<element>", value)

    kind "toggle"  -> def toggle_<element>(self) -> None:
                           self.click("<element>")

    kind "text"    -> def get_<element>_text(self) -> str:
                           return self.text_of("<element>")

Every generated method is a one-liner that calls a BasePage helper
(pages/base_page.py) - which already goes through the self-healing
resolver (self_healing/resolver.py). So every auto-generated page
object is self-healing for free, with zero extra code.

ALONGSIDE each pages/<name>_page.py, this agent also writes
pages/<name>_page.manifest.json - a list of every generated method plus
a handful of plain-English "trigger phrases" someone might use to
describe that action in a user story or test-case step (e.g. the
`fill_username_input` method's phrases include "enter username",
"enter a valid username", "type username"). agents/script_writer_agent.py
uses this manifest to match a test case's plain-English steps to the
right method call, and rag/knowledge_base.py indexes it so future pages
can be checked for overlap before being generated again.

SAFETY RULE: this agent NEVER overwrites a page object that already
exists in pages/, unless you pass --force. That protects hand-written
page objects (like this project's original SauceDemo ones) from being
silently clobbered by a regeneration run.

USAGE:
    # Generate (or update) every page for one story that has a
    # locators/<story>/*_page.json but no pages/<story>/*_page.py yet:
    python agents/pom_generator_agent.py --story login_checkout

    # Generate just one, and mark it as that story's entry point (the
    # ONE page its generated conftest.py should open automatically):
    python agents/pom_generator_agent.py --story login_checkout --page login --entry-page login

    # Re-generate an existing one on purpose (overwrites the .py file):
    python agents/pom_generator_agent.py --story login_checkout --page login --force

Usually you won't run this directly at all - `agents/orchestrator.py
--story <name>` (the "brain") calls this for you right after Agent 7
discovers each page.
================================================================================
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag import knowledge_base as rag  # noqa: E402
from utils.config import config  # noqa: E402
from utils.logger import get_logger  # noqa: E402

logger = get_logger("agent.pom_generator")

LOCATORS_DIR = ROOT / "locators"
PAGES_DIR = ROOT / "pages"

# element "kind" (set by Agent 7, or inferred below for hand-written
# locator files that predate the "kind" field) -> how to generate its
# method, and the generic verb phrases that action tends to be
# described with in plain-English test steps.
_KIND_TEMPLATES = {
    "click": {
        "prefix": "click",
        "signature": "def {method}(self) -> None:",
        "body": '        self.click("{element}")',
        "verbs": ["click", "press", "select", "tap", "choose"],
    },
    "fill": {
        "prefix": "fill",
        "signature": "def {method}(self, value: str) -> None:",
        "body": '        self.fill("{element}", value)',
        "verbs": ["enter", "type", "fill", "input"],
    },
    "toggle": {
        "prefix": "toggle",
        "signature": "def {method}(self) -> None:",
        "body": '        self.click("{element}")',
        "verbs": ["check", "toggle", "tick", "select"],
    },
    "text": {
        "prefix": "get",
        "suffix": "_text",
        "signature": "def {method}(self) -> str:",
        "body": '        return self.text_of("{element}")',
        "verbs": ["see", "read", "verify", "check"],
    },
}


def _infer_kind(entry: dict) -> str:
    """Back-compat for locator files written before "kind" existed
    (e.g. by hand): guess from role first, then from the element's own
    name."""
    if entry.get("kind") in _KIND_TEMPLATES:
        return entry["kind"]
    role = (entry.get("role") or "").lower()
    role_map = {"button": "click", "link": "click", "menuitem": "click", "tab": "click",
                "textbox": "fill", "searchbox": "fill", "combobox": "fill",
                "checkbox": "toggle", "radio": "toggle"}
    if role in role_map:
        return role_map[role]
    name = entry.get("element", "").lower()
    if any(k in name for k in ("button", "btn", "link", "checkout", "submit", "continue", "finish")):
        return "click"
    if any(k in name for k in ("input", "field", "username", "password", "email", "code", "name")):
        return "fill"
    return "text"


def _to_pascal_case(page_name: str) -> str:
    return "".join(word.capitalize() for word in page_name.replace("-", "_").split("_")) + "Page"


def _humanize(key: str) -> str:
    return key.replace("_", " ").replace("input", "").replace("button", "").strip()


def _phrases_for(element_key: str, entry: dict, kind: str) -> list[str]:
    # dict.fromkeys() dedupes while keeping order - e.g. when an
    # element's "text" and "name" happen to be the same word, it should
    # only appear once in the generated phrase list.
    raw_words = [_humanize(element_key)] + [entry.get("text"), entry.get("placeholder"), entry.get("name")]
    words = " ".join(dict.fromkeys(w.strip().lower() for w in raw_words if w and w.strip()))
    verbs = _KIND_TEMPLATES[kind]["verbs"]
    phrases = [f"{verb} {words}".strip() for verb in verbs]
    phrases += [f"{verb} the {words}".strip() for verb in verbs]
    return sorted(set(p for p in phrases if p))


def _method_name(element_key: str, kind: str) -> str:
    template = _KIND_TEMPLATES[kind]
    return f"{template['prefix']}_{element_key}{template.get('suffix', '')}"


def _load_meta(page_name: str, story: str) -> dict:
    meta_path = LOCATORS_DIR / story / f"{page_name}_page.meta.json"
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _compute_path(url: str | None) -> str:
    if not url:
        return ""
    base = config.BASE_URL.rstrip("/")
    if url.startswith(base):
        return url[len(base):] or "/"
    return url  # different host/scheme than BASE_URL - kept as-is; see the TODO comment generated below.


def generate_page_object(page_name: str, story: str, entry_page: bool = False, force: bool = False) -> dict:
    """Reads locators/<story>/<page_name>_page.json and writes
    pages/<story>/<page_name>_page.py (+ a .manifest.json alongside
    it), creating pages/<story>/__init__.py the first time so it's a
    proper importable Python package. Returns a small summary dict.
    Raises FileNotFoundError if the locator file doesn't exist, and
    skips (returns {"skipped": True, ...}) if the page object already
    exists and force=False."""
    locator_path = LOCATORS_DIR / story / f"{page_name}_page.json"
    if not locator_path.exists():
        raise FileNotFoundError(
            f"locators/{story}/{page_name}_page.json not found - run "
            f"agents/locator_discovery_agent.py --story {story} --page-name {page_name} first."
        )

    story_pages_dir = PAGES_DIR / story
    py_path = story_pages_dir / f"{page_name}_page.py"
    if py_path.exists() and not force:
        logger.info("Agent 6: pages/%s/%s_page.py already exists - skipping (pass --force to regenerate)", story, page_name)
        return {"page_name": page_name, "story": story, "skipped": True, "path": str(py_path)}

    entries: dict[str, dict[str, Any]] = json.loads(locator_path.read_text())
    meta = _load_meta(page_name, story)

    # RAG check: is this page suspiciously similar to one we already
    # generated (in ANY story - see agents/locator_discovery_agent.py's
    # matching comment)? Informational only - never blocks generation,
    # since a human explicitly asked to discover/build this specific
    # page. The index key is story-qualified so two stories' same-named
    # pages never overwrite each other's RAG entry.
    rag_key = f"{story}:{page_name}"
    query = page_name + " " + " ".join(entries.keys())
    for match in rag.search_page_objects(query, top_k=2, exclude_key=rag_key):
        if match["score"] >= 0.4:
            logger.warning(
                "Agent 6: '%s' overlaps %.0f%% in wording with existing page '%s' - "
                "check you're not duplicating an existing page object.",
                rag_key, match["score"] * 100, match["key"],
            )

    class_name = _to_pascal_case(page_name)
    path_value = _compute_path(meta.get("url"))
    is_entry = entry_page or path_value in ("", "/")

    methods_code: list[str] = []
    manifest: list[dict] = []
    for element_key, entry in sorted(entries.items()):
        kind = _infer_kind(entry)
        method = _method_name(element_key, kind)
        template = _KIND_TEMPLATES[kind]
        signature = template["signature"].format(method=method)
        body = template["body"].format(element=element_key)
        methods_code.append(f"    {signature}\n{body}\n\n")
        manifest.append({
            "method": method,
            "kind": kind,
            "element": element_key,
            "phrases": _phrases_for(element_key, entry, kind),
        })

    url_comment = (
        f"    # discovered at: {meta['url']}\n" if meta.get("url") else
        "    # path not auto-detected - fill this in, or re-run locator_discovery_agent.py\n"
    )
    methods_block = "".join(methods_code) if methods_code else "    pass\n"
    source = f'''"""
================================================================================
 pages/{story}/{page_name}_page.py - AGENT 6 OUTPUT (auto-generated, do not hand-edit)
================================================================================
Generated by agents/pom_generator_agent.py from locators/{story}/{page_name}_page.json.
Story: {story} - see that story's own folder (test_cases/{story}/,
tests/generated/{story}/) for everything else that goes with it.
To change this page's behavior, either:
  1. Re-run agents/locator_discovery_agent.py against the real site (the
     site changed), then agents/pom_generator_agent.py --story {story} --page {page_name} --force, or
  2. Add hand-written methods in a subclass elsewhere, rather than
     editing this generated file directly - the next --force run will
     overwrite it.

No assertions live here (POM RULE 1) - only actions and getters. Every
method below calls a BasePage helper, so every element lookup already
goes through the self-healing resolver (self_healing/resolver.py).
================================================================================
"""
from __future__ import annotations

from pages.base_page import BasePage


class {class_name}(BasePage):
    # "{story}/{page_name}_page" - the story prefix is what makes
    # pages/base_page.py read locators/{story}/{page_name}_page.json
    # instead of some OTHER story's same-named page.
    locator_file = "{story}/{page_name}_page"
{url_comment}    path = "{path_value}"
    auto_open = {is_entry}

{methods_block}'''.rstrip() + "\n"

    story_pages_dir.mkdir(parents=True, exist_ok=True)
    init_path = story_pages_dir / "__init__.py"
    if not init_path.exists():
        init_path.write_text("")  # makes pages/<story>/ a proper importable package
    py_path.write_text(source)

    manifest_path = story_pages_dir / f"{page_name}_page.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    rag.index_page_object(rag_key, manifest)

    logger.info(
        "Agent 6 output: %s (%d methods) -> %s, entry_page=%s",
        class_name, len(manifest), py_path, is_entry,
    )
    return {
        "page_name": page_name, "story": story, "class_name": class_name, "path": str(py_path),
        "manifest_path": str(manifest_path), "method_count": len(manifest),
        "auto_open": is_entry, "skipped": False,
    }


def generate_all(story: str, force: bool = False) -> list[dict]:
    """Generates a page object for every locators/<story>/*_page.json
    that doesn't already have one in pages/<story>/ (unless force=True)."""
    results = []
    for locator_path in sorted((LOCATORS_DIR / story).glob("*_page.json")):
        page_name = locator_path.stem.removesuffix("_page")
        results.append(generate_page_object(page_name, story, force=force))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Page Object Model files from discovered locators, scoped to one story.")
    parser.add_argument("--story", required=True, help="Story this page belongs to, e.g. 'login_checkout' -> pages/login_checkout/<page>_page.py")
    parser.add_argument("--page", default=None, help="Generate just this page (matches locators/<story>/<page>_page.json); omit to generate every undone page for this story")
    parser.add_argument("--entry-page", default=None, help="Mark this page as this story's entry point (auto_open)")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing pages/<story>/<page>_page.py")
    args = parser.parse_args()

    if args.page:
        result = generate_page_object(args.page, args.story, entry_page=(args.page == args.entry_page), force=args.force)
        print(json.dumps(result, indent=2))
    else:
        results = generate_all(args.story, force=args.force)
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()