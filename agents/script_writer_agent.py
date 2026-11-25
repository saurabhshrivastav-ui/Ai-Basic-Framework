"""
================================================================================
 agents/script_writer_agent.py - AGENT 8 - THE SCRIPT WRITER AGENT
================================================================================
THINK OF IT LIKE: a translator standing between a customer and a chef
who only understands a fixed set of hand signals. The customer says, in
plain English, "add a product to the cart." The translator doesn't
speak the chef's language either - but they've got a phrasebook (the
page-object manifests) mapping common phrases to hand signals, so they
find the closest match and make that signal. If nothing in the
phrasebook is close enough, the translator says so honestly instead of
guessing and hoping.

THIS IS STEP 2 of the flow you asked for:

    you write a story -> test_case_pipeline.py generates test cases in
    their own folder -> [THIS FILE writes a real, runnable script using
    your page objects] -> you run it

For one story (a folder under test_cases/<slug>/), this agent:
  1. Loads that story's test_cases.json and test_data.json.
  2. Loads every page object's "phrasebook" - either a real
     pages/<x>_page.manifest.json (written by agents/pom_generator_agent.py),
     or, for hand-written pages that have no manifest file, one built on
     the fly by reading the page class's own method names (see
     `_introspect_manifest()` below) - so this works for BOTH
     auto-generated and hand-written page objects.
  3. For every step in every test case, scores it against every known
     method's phrases using the exact same word-overlap math as
     rag/knowledge_base.py (see utils/text.py's `jaccard_score`), and
     picks the best match above a minimum confidence.
  4. Works out what VALUE to pass a method that needs one (e.g.
     fill_username_input needs a username) by matching the method's
     parameter names against the story's own test_data.json - preferring
     a locked/invalid account's data for a step that sounds negative.
  5. Writes tests/generated/<slug>/test_<slug>.py - one test function
     per test case, importing nothing extra (it uses the same dynamic
     page-object fixtures conftest.py already provides), with the
     matched step turned into a real method call, and anything it
     could NOT confidently match left as a clearly marked `# TODO`
     instead of a guess that might silently do the wrong thing.

HONEST LIMITATION: this is keyword matching, not real language
understanding - it will occasionally miss an unusually-phrased step, or
match the wrong element when two elements are described very
similarly. Every generated test is meant to be glanced over before
being trusted, and every uncertain line says so in a comment. Wiring a
real AI model into utils/ai_client.py (Phase 2) would let this step
understand phrasing this version can't - the matching function below is
built so that upgrade only touches ONE function, `_best_method()`.

USAGE:
    python agents/script_writer_agent.py login_checkout
    # -> writes tests/generated/login_checkout/test_login_checkout.py

    pytest tests/generated/login_checkout/ -v   # then just run it
================================================================================
"""
from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import importlib  # noqa: E402

from pages.base_page import BasePage  # noqa: E402
from utils.logger import get_logger  # noqa: E402
from utils.text import jaccard_score, slugify, tokenize  # noqa: E402

logger = get_logger("agent.script_writer")

TEST_CASES_DIR = ROOT / "test_cases"
PAGES_DIR = ROOT / "pages"
GENERATED_TESTS_DIR = ROOT / "tests" / "generated"

# A step needs at least this much word-overlap with a method's phrases
# to be matched to it automatically. Below this, we'd rather leave an
# honest TODO than silently call the wrong method.
MATCH_THRESHOLD = 0.10

# Methods every BasePage subclass inherits - never candidates for
# step-matching themselves (their wrapped, element-specific versions are).
_BASE_METHODS = {"open", "click", "fill", "text_of", "is_visible", "current_url", "element"}


# ---------------------------------------------------------------------- #
# Building a "phrasebook" (manifest) for every known page
# ---------------------------------------------------------------------- #
def _discover_pages(story: str) -> dict[str, type[BasePage]]:
    """Only ever looks inside pages/<story>/ - NOT the global pages/
    folder. See agents/locator_discovery_agent.py's module docstring
    for why: this story's own pages might belong to a completely
    different website than some other story's, so a script for THIS
    story must never accidentally match a step to some OTHER story's
    same-named page."""
    pages: dict[str, type[BasePage]] = {}
    story_pages_dir = PAGES_DIR / story
    for path in sorted(story_pages_dir.glob("*_page.py")):
        module = importlib.import_module(f"pages.{story}.{path.stem}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BasePage) and obj is not BasePage and obj.__module__ == module.__name__:
                page_name = path.stem.removesuffix("_page")
                pages[page_name] = obj
                break
    return pages


def _introspect_manifest(page_cls: type[BasePage]) -> list[dict]:
    """Builds phrasebook entries straight from a page class's own public
    methods, for pages that have no *_page.manifest.json on disk (i.e.
    hand-written ones, like this project's original SauceDemo pages)."""
    manifest = []
    for name, member in inspect.getmembers(page_cls, predicate=inspect.isfunction):
        if name.startswith("_") or name in _BASE_METHODS:
            continue
        if name.startswith("click_"):
            kind, words = "click", name[len("click_"):]
        elif name.startswith("fill_"):
            kind, words = "fill", name[len("fill_"):]
        elif name.startswith("toggle_"):
            kind, words = "toggle", name[len("toggle_"):]
        elif name.startswith("get_") and name.endswith("_text"):
            kind, words = "text", name[len("get_"):-len("_text")]
        elif name.startswith("get_"):
            kind, words = "text", name[len("get_"):]
        else:
            params = [p for p in inspect.signature(member).parameters if p != "self"]
            kind, words = ("fill" if params else "click"), name
        readable = words.replace("_", " ").strip()
        verbs = {"click": ["click", "press", "select", "tap"], "fill": ["enter", "type", "fill", "input"],
                 "toggle": ["check", "toggle"], "text": ["see", "read", "verify", "check"]}[kind]
        phrases = {f"{v} {readable}".strip() for v in verbs} | {f"{v} the {readable}".strip() for v in verbs}
        # A handful of very common test-step phrasings that share no
        # words at all with their obvious method (e.g. "log in" vs a
        # method literally named "login") - without this, keyword
        # matching alone would miss them despite being an obvious match
        # to a human reader. Small, explicit, and honestly limited to
        # the couple of cases common enough to be worth hardcoding.
        if name == "login":
            phrases |= {"log in", "log in with valid credentials", "log into the app", "sign in", "authenticate"}
        manifest.append({"method": name, "kind": kind, "element": words, "phrases": sorted(phrases)})
    return manifest


def _load_manifests(story: str) -> dict[str, list[dict]]:
    manifests: dict[str, list[dict]] = {}
    for page_name, page_cls in _discover_pages(story).items():
        manifest_path = PAGES_DIR / story / f"{page_name}_page.manifest.json"
        if manifest_path.exists():
            manifests[page_name] = json.loads(manifest_path.read_text())
        else:
            manifests[page_name] = _introspect_manifest(page_cls)
            logger.info("Script Writer: no manifest for '%s' page - introspected %d method(s) from its own code",
                        page_name, len(manifests[page_name]))
    return manifests


# ---------------------------------------------------------------------- #
# Matching a step to a method
# ---------------------------------------------------------------------- #
# These words appear in EVERY phrase of a given kind - the templates in
# _introspect_manifest() glue "click"/"press"/"select"/"tap" onto every
# single click-kind method, "enter"/"type"/"fill"/"input" onto every
# fill-kind method, and so on. Sharing one of these words alone proves
# NOTHING about which specific method a step means - "click the login
# button" and "click the remove-item button" both contain "click".
_ACTION_VERBS = {
    "click", "press", "select", "tap",
    "enter", "type", "fill", "input",
    "check", "toggle",
    "see", "read", "verify",
}
# Articles/prepositions/etc - filler words that say nothing about
# content OR kind, just noise either way.
_STOPWORDS = {
    "the", "a", "an", "to", "of", "on", "for", "with",
    "is", "are", "was", "were", "be", "and", "via", "in",
}


def _topic_words(tokens: set[str]) -> set[str]:
    """What a step/phrase is actually ABOUT - strips both filler words
    and generic action verbs, leaving only the specific, distinguishing
    words (e.g. "login", "backpack", "checkout"). Used as a GATE below:
    two phrases that share only filler/verb words have zero topic
    overlap and are NOT a match, no matter how similar their generic
    words look."""
    return tokens - _STOPWORDS - _ACTION_VERBS


def _best_method(
    text: str,
    manifests: dict[str, list[dict]],
    kind_filter: str | None = None,
    exclude: set[tuple[str, str]] | None = None,
):
    """Returns (page_name, manifest_entry, score) for the best match, or
    None if nothing qualifies. This is the ONE function a real AI model
    would replace in Phase 2 - see the module docstring.

    THINK OF IT LIKE checking two job applicants' resumes for overlap:
    both mention "experience" and "team" (everyone's resume does - that
    proves nothing), but only a real match shares the SPECIFIC skill you
    need. Scoring here works the same way, in two layers - added after a
    real bug caught during testing: comparing raw word sets let the step
    "Click the Login button" match a completely unrelated "remove item
    from cart" method, purely because both phrases happened to contain
    "click" and "the" - words that appear in nearly every phrase of that
    kind and say nothing about which specific element is meant.

      1. GATE - the step and a candidate method must share at least one
         TOPIC word (see _topic_words() above - filler and generic verbs
         don't count). Zero topic overlap means the candidate is not
         even considered, however similar its generic words look.
      2. RANK - candidates that pass the gate are ranked by Jaccard
         similarity with only FILLER words removed (the action verbs
         stay in for this part). That keeps a real, useful signal: a
         step that says "fill in the details" still gets a boost toward
         a fill-kind method over an unrelated click-kind method that
         happens to share the same topic word - useful once the gate
         has already ruled out the pure-filler false matches.

    `exclude` is a set of (page_name, method) pairs to skip entirely -
    see _generate_test_function()'s docstring for WHY: a method that
    already got matched to an earlier step in this same test case is
    excluded from matching again, because a page-object method changes
    the page's state (a login button submits the form; you can't submit
    it a second time on a page that already moved on). Without this, two
    separately-worded steps that are both "close enough" to the SAME
    method (e.g. "Enter a valid username" and "Enter a valid password"
    both being vaguely near login()) would generate that method call
    TWICE in a row - the second call breaking at runtime because the
    page has already navigated away from where that method expects to
    start.
    """
    step_tokens = tokenize(text)
    step_topic = _topic_words(step_tokens)
    step_full = step_tokens - _STOPWORDS
    exclude = exclude or set()

    best = None
    for page_name, entries in manifests.items():
        for entry in entries:
            if kind_filter and entry["kind"] != kind_filter:
                continue
            if (page_name, entry["method"]) in exclude:
                continue
            phrase_tokens: set[str] = set()
            for phrase in entry["phrases"]:
                phrase_tokens |= tokenize(phrase)
            if not (step_topic & _topic_words(phrase_tokens)):
                continue  # shares nothing but filler/generic words - not a real match
            phrase_full = phrase_tokens - _STOPWORDS
            score = jaccard_score(step_full, phrase_full)
            if best is None or score > best[2]:
                best = (page_name, entry, score)
    return best


# ---------------------------------------------------------------------- #
# Resolving a method's parameter values from test_data.json
# ---------------------------------------------------------------------- #
def _flatten(data: Any, flat: dict[str, Any] | None = None) -> dict[str, Any]:
    flat = {} if flat is None else flat
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                _flatten(value, flat)
            else:
                flat.setdefault(key, value)
    elif isinstance(data, list):
        for item in data:
            _flatten(item, flat)
    return flat


# Every auto-generated fill-kind method takes a parameter literally
# named "value" (see agents/pom_generator_agent.py's _KIND_TEMPLATES -
# `def fill_<element>(self, value: str)`). That name carries ZERO
# meaning - it can't tell "value" apart from a username, a password, an
# email, or a zip code. This maps patterns found in the REAL element
# name Agent 7 discovered (e.g. "user-name" -> "username_input") to the
# semantic field it almost certainly is - the same way a person reads a
# field's id/placeholder on a real form to know what belongs in it,
# instead of trusting the generic Python variable name. Longest/most
# specific patterns are listed first.
_ELEMENT_NAME_TO_SEMANTIC_KEY: tuple[tuple[str, str], ...] = (
    ("confirm_password", "password"),
    ("confirm_email", "email"),
    ("password", "password"),
    ("passcode", "password"),
    ("email", "email"),
    ("user_name", "username"),
    ("username", "username"),
    ("first_name", "first_name"),
    ("last_name", "last_name"),
    ("postal_code", "postal_code"),
    ("zip", "postal_code"),
    ("phone", "phone"),
)


def _semantic_key_for_element(element_name: str) -> str | None:
    """See _ELEMENT_NAME_TO_SEMANTIC_KEY's comment above for WHY this
    exists. Returns None if nothing recognizable is found - the caller
    then falls back to the honest "CHANGE_ME" TODO, exactly as before."""
    name = (element_name or "").lower().replace("-", "_")
    for pattern, key in _ELEMENT_NAME_TO_SEMANTIC_KEY:
        if pattern in name:
            return key
    return None


def _value_for_param(
    param_name: str, test_data: dict, test_case: dict, element_name: str | None = None,
) -> tuple[str, bool]:
    """Returns (python_literal_source, resolved). Prefers a
    locked/invalid account's data when the test case itself sounds
    negative - e.g. TC titled "attempt ... with an invalid or locked
    account" gets the locked user's username, not the valid one's.

    `element_name` (optional) is the REAL locator element name this
    parameter is filling (e.g. "username_input") - used as a fallback
    ONLY when looking up `param_name` itself finds nothing, which is
    always the case for auto-generated methods (see
    _ELEMENT_NAME_TO_SEMANTIC_KEY above for why)."""
    title = f"{test_case.get('title', '')} {test_case.get('linked_scenario', '')}".lower()
    users = test_data.get("users", {})

    def _try_key(key: str) -> tuple[str, bool] | None:
        if key in ("username", "password") and users:
            if "locked" in title and "locked_user" in users and key in users["locked_user"]:
                return repr(users["locked_user"][key]), True
            if ("invalid" in title or "problem" in title) and "problem_user" in users and key in users["problem_user"]:
                return repr(users["problem_user"][key]), True
            if "valid_user" in users and key in users["valid_user"]:
                return repr(users["valid_user"][key]), True
        flat = _flatten(test_data)
        if key in flat:
            return repr(flat[key]), True
        return None

    found = _try_key(param_name)
    if found:
        return found

    if element_name:
        semantic_key = _semantic_key_for_element(element_name)
        if semantic_key and semantic_key != param_name:
            found = _try_key(semantic_key)
            if found:
                return found

    return '"CHANGE_ME"', False


# ---------------------------------------------------------------------- #
# Generating one step's line(s) of code
# ---------------------------------------------------------------------- #
def _looks_like_a_navigation_step(step: str) -> bool:
    low = step.lower()
    return low.startswith("open ") and "page" in low


def _is_composite_login_step(step: str) -> bool:
    """True for a step that describes the WHOLE login action in one
    sentence ("Log in with valid credentials") rather than three
    separate steps (enter username / enter password / click login -
    see agents/test_case_agent.py's _STEP_LIBRARY, where both shapes
    are used by different scenario types). A hand-written page with a
    real combined login(username, password) method already matches a
    step like this fine through the normal _best_method() path below -
    this only matters as a FALLBACK for a page Agent 6 auto-generated,
    which never gets a combined login() method, only individual
    fill_username_input/fill_password_input/click_login_button ones."""
    low = step.lower()
    has_login_verb = "log in" in low or "log on" in low or "sign in" in low
    has_credentials_word = "credential" in low or "valid" in low
    return has_login_verb and has_credentials_word


def _find_login_page(
    manifests: dict[str, list[dict]],
) -> tuple[str, dict, dict, dict] | None:
    """Generic composite-login helper: finds whichever page in THIS
    story has a username field, a password field, and a submit-shaped
    clickable element - regardless of what the page or its story is
    actually named, so this works for any freshly-discovered site, not
    just SauceDemo-shaped ones. Returns
    (page_name, username_entry, password_entry, submit_entry), or None
    if no page in this story looks like a login form at all."""
    for page_name, entries in manifests.items():
        username_entry = password_entry = submit_entry = None
        for entry in entries:
            key = _semantic_key_for_element(entry.get("element", ""))
            if entry["kind"] == "fill" and key == "username" and username_entry is None:
                username_entry = entry
            elif entry["kind"] == "fill" and key == "password" and password_entry is None:
                password_entry = entry
            elif entry["kind"] == "click" and submit_entry is None:
                name = entry.get("element", "").lower()
                if any(w in name for w in ("login", "log_in", "signin", "sign_in", "submit")):
                    submit_entry = entry
        if username_entry and password_entry and submit_entry:
            return page_name, username_entry, password_entry, submit_entry
    return None


def _try_composite_login(
    step: str, manifests: dict[str, list[dict]], test_data: dict, test_case: dict,
    used_methods: set[tuple[str, str]],
) -> tuple[str, str | None] | None:
    """Only called once normal step-to-method matching has already
    failed (see _generate_step_code below). Synthesizes the three real
    calls a combined "log in" step actually means - fill username, fill
    password, click submit - by finding the story's own login-shaped
    page, the same way a person would spot a login form on any random
    website without being told which one it is. Returns None (meaning
    "still no match, leave the honest TODO") if no login-shaped page
    exists in this story, or its fields are already used up."""
    if not _is_composite_login_step(step):
        return None
    found = _find_login_page(manifests)
    if not found:
        return None
    page_name, user_entry, pass_entry, submit_entry = found
    trio = [(page_name, user_entry["method"]), (page_name, pass_entry["method"]), (page_name, submit_entry["method"])]
    if any(pair in used_methods for pair in trio):
        return None  # this login was already done earlier in the same test

    user_val, user_ok = _value_for_param("value", test_data, test_case, element_name=user_entry["element"])
    pass_val, pass_ok = _value_for_param("value", test_data, test_case, element_name=pass_entry["element"])
    used_methods.update(trio)
    fixture = f"{page_name}_page"
    lines = [
        f"        {fixture}.{user_entry['method']}({user_val})  # step: {step!r} - composite login (username)",
        f"        {fixture}.{pass_entry['method']}({pass_val})  # composite login (password)",
        f"        {fixture}.{submit_entry['method']}()  # composite login (submit)",
    ]
    if not (user_ok and pass_ok):
        lines.insert(0, "        # TODO: no matching value found in test_data.json for one of these arguments - fill it in")
    return "\n".join(lines), page_name


def _generate_step_code(
    step: str,
    manifests: dict[str, list[dict]],
    page_classes: dict[str, type[BasePage]],
    test_data: dict,
    test_case: dict,
    used_methods: set[tuple[str, str]],
) -> tuple[str, str | None]:
    """Returns (one or more lines of generated code, page_name used or None).
    `used_methods` is shared across every step of ONE test case (see
    _generate_test_function()) so the same stateful method never gets
    matched twice in a row - see _best_method()'s docstring for why."""
    if _looks_like_a_navigation_step(step):
        return f"        # {step!r} - handled automatically (the entry page's fixture opens it)", None

    match = _best_method(step, manifests, exclude=used_methods)
    if not match or match[2] < MATCH_THRESHOLD:
        composite = _try_composite_login(step, manifests, test_data, test_case, used_methods)
        if composite:
            return composite
        return f"        # TODO: no confident match for this step - implement it by hand:\n        # {step!r}", None

    page_name, entry, score = match
    used_methods.add((page_name, entry["method"]))
    fixture = f"{page_name}_page"
    method = entry["method"]
    func = getattr(page_classes[page_name], method)
    params = [p for p in inspect.signature(func).parameters if p != "self"]

    if not params:
        return f"        {fixture}.{method}()  # step: {step!r} (matched {score:.0%})", page_name

    args, unresolved = [], False
    for param in params:
        literal, resolved = _value_for_param(param, test_data, test_case, element_name=entry.get("element"))
        args.append(literal)
        unresolved = unresolved or not resolved

    call = f"        {fixture}.{method}({', '.join(args)})  # step: {step!r} (matched {score:.0%})"
    if unresolved:
        call = "        # TODO: no matching value found in test_data.json for one of these arguments - fill it in\n" + call
    return call, page_name


# ---------------------------------------------------------------------- #
# Generating one whole test function
# ---------------------------------------------------------------------- #
def _generate_test_function(
    test_case: dict, manifests: dict[str, list[dict]], page_classes: dict[str, type[BasePage]], test_data: dict,
) -> str:
    func_name = "test_" + slugify(f"{test_case['test_case_id']}_{test_case['title']}")
    body_lines: list[str] = []
    used_pages: set[str] = set()
    # One test case = one shared "already used" set, so the SAME method
    # (e.g. login()) never gets matched to two different steps in the
    # same test - see _best_method()'s docstring for the runtime bug
    # this prevents.
    used_methods: set[tuple[str, str]] = set()

    for step in test_case["steps"]:
        code, page_used = _generate_step_code(step, manifests, page_classes, test_data, test_case, used_methods)
        body_lines.append(code)
        if page_used:
            used_pages.add(page_used)

    exp_match = _best_method(test_case["expected_result"], manifests, kind_filter="text", exclude=used_methods)
    if exp_match and exp_match[2] >= MATCH_THRESHOLD:
        page_name, entry, score = exp_match
        used_pages.add(page_name)
        body_lines.append(f"        actual_result = {page_name}_page.{entry['method']}()  # matched {score:.0%}")
        body_lines.append(f"        # TODO: confirm this is the exact expected text: {test_case['expected_result']!r}")
        body_lines.append('        assert actual_result, "Expected a non-empty confirmation, got nothing"')
    else:
        body_lines.append("        # TODO: add a real assertion for the expected result:")
        body_lines.append(f"        # {test_case['expected_result']!r}")
        body_lines.append("        assert True  # placeholder - replace with a real check above")

    fixture_params = ", ".join(["self"] + sorted(f"{p}_page" for p in used_pages))
    lines = [
        f"    @pytest.mark.{test_case.get('suite', 'regression')}",
        f"    def {func_name}({fixture_params}):",
        f'        """{test_case["test_case_id"]}: {test_case["title"]}"""',
        *body_lines,
        "",
    ]
    return "\n".join(lines)


def _write_story_conftest(story_id: str, out_dir: Path) -> Path:
    """Writes tests/generated/<story_id>/conftest.py - registers a
    pytest fixture for every page object THIS STORY discovered
    (pages/<story_id>/*.py), and ONLY this story's pages. pytest applies
    a conftest.py to tests in its own folder and below, so a fixture
    called "login_page" here can never collide with another story's (or
    Flow A's global) "login_page" fixture - see
    utils/fixture_factory.py's docstring for the full reasoning."""
    conftest_path = out_dir / "conftest.py"
    source = f'''"""
================================================================================
 tests/generated/{story_id}/conftest.py - AGENT 8 OUTPUT (auto-generated)
================================================================================
Registers a pytest fixture for every page object story '{story_id}'
discovered (pages/{story_id}/*.py) - and ONLY this story's pages, so a
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
    ROOT / "pages" / "{story_id}",
    "pages.{story_id}",
    log_label="conftest (tests/generated/{story_id})",
)
'''
    conftest_path.write_text(source)
    return conftest_path


# ---------------------------------------------------------------------- #
# Top level: one story -> one generated test file
# ---------------------------------------------------------------------- #
def write_script_for_story(story_id: str) -> Path:
    story_dir = TEST_CASES_DIR / story_id
    test_cases_path = story_dir / "test_cases.json"
    test_data_path = story_dir / "test_data.json"
    if not test_cases_path.exists():
        raise FileNotFoundError(
            f"test_cases/{story_id}/test_cases.json not found - run "
            f"`python agents/test_case_pipeline.py user_stories/{story_id}.txt` first."
        )
    if not (PAGES_DIR / story_id).is_dir():
        raise FileNotFoundError(
            f"pages/{story_id}/ not found - this story has no discovered pages yet. Run "
            f"`python agents/orchestrator.py --story {story_id}` (the brain) first, which "
            f"discovers pages AND writes this script in one go."
        )

    logger.info("Agent 8 (Script Writer Agent): writing a script for story '%s'", story_id)

    test_cases = json.loads(test_cases_path.read_text())
    test_data = json.loads(test_data_path.read_text()) if test_data_path.exists() else {}
    manifests = _load_manifests(story_id)
    page_classes = _discover_pages(story_id)

    # MUST start with "Test" - pytest's default python_classes = Test*
    # only auto-discovers classes with that prefix (matching this
    # project's hand-written `class TestPurchaseFlow` in
    # tests/smoke/test_purchase_flow.py). A "...Tests" suffix instead of
    # a "Test..." prefix would silently produce a file pytest collects
    # zero tests from - an easy, non-obvious mistake worth this comment.
    class_name = "Test" + "".join(w.capitalize() for w in story_id.split("_"))
    functions = [_generate_test_function(tc, manifests, page_classes, test_data) for tc in test_cases]

    source = f'''"""
================================================================================
 tests/generated/{story_id}/test_{story_id}.py - AGENT 8 OUTPUT (auto-generated)
================================================================================
Generated by agents/script_writer_agent.py from test_cases/{story_id}/.
Every method call below was matched from a plain-English test step to a
page-object method by comparing shared keywords (see the docstring in
agents/script_writer_agent.py) - review any line marked TODO before
trusting this test, the same way you'd review a junior engineer's
first draft.

Uses this story's OWN dynamic page-object fixtures, registered by the
conftest.py sitting right next to this file (auto-written by Agent 8
below, from pages/{story_id}/ only) - a different story's same-named
page never collides with this one. See utils/fixture_factory.py's
docstring for the full reasoning.
================================================================================
"""
from __future__ import annotations

import allure
import pytest


@allure.epic("Generated")
@allure.feature("{story_id}")
class {class_name}:

{"".join(functions)}'''.rstrip() + "\n"

    out_dir = GENERATED_TESTS_DIR / story_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"test_{story_id}.py"
    out_path.write_text(source)

    conftest_path = _write_story_conftest(story_id, out_dir)

    logger.info(
        "Agent 8 output: %d test function(s) written to %s (fixtures via %s)",
        len(test_cases), out_path, conftest_path,
    )
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a runnable pytest script from a story's generated test cases.")
    parser.add_argument("story_id", help="Folder name under test_cases/, e.g. 'login_checkout'")
    args = parser.parse_args()
    out_path = write_script_for_story(args.story_id)
    print(f"Written: {out_path}\nRun it with: pytest {out_path.parent} -v")


if __name__ == "__main__":
    main()