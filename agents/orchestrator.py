"""
================================================================================
 THE ORCHESTRATOR - the framework's "brain"
================================================================================
THINK OF IT LIKE: the head chef in a kitchen with many stations. Every
agent (1-8, plus RAG) is one station - one person doing one job well.
The orchestrator does not cook anything itself. It just carries the
plate from station to station, in the right order, so YOU don't have to
run four separate commands by hand every time.

THIS FILE DOES TWO DIFFERENT JOBS - pick the one you need:

  1. `python agents/orchestrator.py`
     Flow A - the original, no-setup-required demo. Runs Agents 1-5
     against one hardcoded requirement and writes to data/. No browser,
     no internet, no .env needed. Good for a first look at the
     framework, or for CI smoke-checking that Agents 1-5 still work.

  2. `python agents/orchestrator.py --story <name>`
     Flow B - THE BRAIN. Runs the FULL story -> real script pipeline
     for one story in user_stories/<name>.txt, using utils/config.py's
     BASE_URL (which reads your .env file) to know WHERE to discover
     pages from - you never type a URL on the command line for this.
     See "WHAT --story ACTUALLY DOES" below.

WHY keep these separate instead of one giant do-everything function?
Flow A always writes to the SAME data/ folder (one requirement, one
output). Flow B writes to a NEW folder per story (test_cases/<story>/,
tests/generated/<story>/) and needs a real URL. Merging them would make
neither one easy to follow - see each mode's own section below for the
full reasoning.

--------------------------------------------------------------------------------
WHAT --story ACTUALLY DOES (the brain's job, step by step)
--------------------------------------------------------------------------------
  1. ENTRY PAGE - the one page at BASE_URL itself (e.g. the login page).
     If pages/<ENTRY_PAGE_NAME>_page.py doesn't exist yet, the brain:
       a. Opens BASE_URL in a real browser and reads its real DOM
          (Agent 7 - agents/locator_discovery_agent.py)
       b. Generates a real Page Object class from what it found
          (Agent 6 - agents/pom_generator_agent.py)
     If that page object already exists, this step is SKIPPED (it's
     already done) - pass --force-discover to redo it anyway (e.g. the
     real site changed its HTML since you last ran this).

  2. EXTRA PAGES (only if you pass --pages) - any further pages your
     story's flow needs that live behind BASE_URL (e.g. an inventory or
     dashboard page you only reach after logging in). For each one not
     already in pages/, the brain logs in (using --username/--password,
     or DEMO_USERNAME/DEMO_PASSWORD from .env) and discovers + generates
     it the same way as step 1.

  3. STORY -> TEST CASES (Agents 1-5, reused) - turns
     user_stories/<story>.txt into test_cases/<story>/*.json.
     (agents/test_case_pipeline.py)

  4. TEST CASES -> RUNNABLE SCRIPT (Agent 8) - matches every test-case
     step to a real page-object method and writes
     tests/generated/<story>/test_<story>.py.
     (agents/script_writer_agent.py)

  5. (Only with --run) Actually runs the generated test with pytest.
     Off by default on purpose - every generated test can contain
     honest `# TODO` lines for steps it wasn't confident about (see
     agents/script_writer_agent.py's docstring), and those deserve a
     quick human glance before being trusted, the same way you'd
     skim a junior engineer's first draft before merging it.

USAGE EXAMPLES:
    # Simplest case - BASE_URL's landing page IS the whole flow's entry
    # point, story doesn't need any other pages discovered:
    python agents/orchestrator.py --story login_checkout

    # Story also needs an inventory page that only exists after login:
    python agents/orchestrator.py --story login_checkout \\
        --pages inventory:/inventory.html \\
        --username standard_user --password secret_sauce

    # Also run the generated test immediately after writing it:
    python agents/orchestrator.py --story login_checkout --run

    # The real site's HTML changed - rediscover the entry page:
    python agents/orchestrator.py --story login_checkout --force-discover
================================================================================
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Make sure this framework's root folder is importable as "agents.X" /
# "utils.X" no matter how this file is launched (as a script, as a
# module, or imported by something else).
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json  # noqa: E402

from agents.business_rule_agent import extract_business_rules  # noqa: E402
from agents.locator_discovery_agent import discover  # noqa: E402
from agents.pom_generator_agent import generate_page_object  # noqa: E402
from agents.requirement_agent import analyze_requirement  # noqa: E402
from agents.scenario_agent import generate_scenarios  # noqa: E402
from agents.script_writer_agent import write_script_for_story  # noqa: E402
from agents.test_case_agent import generate_test_cases  # noqa: E402
from agents.test_case_pipeline import run_for_story  # noqa: E402
from agents.test_data_agent import generate_test_data  # noqa: E402
from utils.config import config  # noqa: E402
from utils.logger import get_logger  # noqa: E402

logger = get_logger("orchestrator")

PAGES_DIR = ROOT / "pages"
USER_STORIES_DIR = ROOT / "user_stories"

SAMPLE_REQUIREMENT = """
As a registered customer, I want to log in to the store, add a product
to my cart, and complete checkout, so that I can purchase the items I
need.

Preconditions:
- The user must already have a registered account
- The application must be reachable

Workflow:
- User opens the login page
- User enters username and password
- User must not be able to log in if the account is locked
- User adds a product to the cart
- User opens the cart and proceeds to checkout
- User fills in the required checkout details and completes the order

Expected Result:
The order is placed successfully and a confirmation is shown to the user
"""


# ============================================================================ #
# FLOW A - the original, no-setup demo (Agents 1-5 only, one hardcoded story)
# ============================================================================ #
def run_pipeline(requirement_text: str = SAMPLE_REQUIREMENT) -> dict:
    logger.info("===== Flow A pipeline started =====")

    structured_requirement = analyze_requirement(requirement_text)
    business_rules = extract_business_rules(structured_requirement)
    scenarios = generate_scenarios(structured_requirement, business_rules)
    test_cases = generate_test_cases(scenarios, business_rules)
    test_data = generate_test_data(test_cases, ROOT / "data" / "test_data.json")

    result = {
        "requirement_analysis": structured_requirement,
        "business_rules": business_rules,
        "scenarios": scenarios,
        "test_cases": test_cases,
        "test_data": test_data,
    }

    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "test_cases.json").write_text(json.dumps(test_cases, indent=2))
    (ROOT / "data" / "pipeline_output.json").write_text(json.dumps(result, indent=2))

    logger.info("===== Flow A pipeline finished: %d test cases produced =====", len(test_cases))
    return result


# ============================================================================ #
# FLOW B - the brain: story -> real, runnable script, driven by .env's BASE_URL
# ============================================================================ #
def _ensure_page(
    story_id: str,
    page_name: str,
    url: str,
    entry_page: bool,
    force_discover: bool,
    login_first: bool = False,
    username: str | None = None,
    password: str | None = None,
) -> None:
    """Makes sure pages/<story_id>/<page_name>_page.py exists,
    discovering + generating it if it doesn't (or if force_discover says
    redo it anyway). Skipping when it already exists is the SAME safety
    rule agents/pom_generator_agent.py already follows on its own - the
    brain just applies it one level up, before even calling Agent 7.

    STORY-SCOPED: every page this story discovers lives under
    pages/<story_id>/ and locators/<story_id>/, never in a shared,
    global folder - see utils/fixture_factory.py's docstring for why
    that matters (two stories can both have a page called "login" and
    never collide)."""
    py_path = PAGES_DIR / story_id / f"{page_name}_page.py"
    if py_path.exists() and not force_discover:
        logger.info(
            "Brain: pages/%s/%s_page.py already exists - skipping discovery (use --force-discover to redo it)",
            story_id, page_name,
        )
        return

    logger.info("Brain: discovering '%s' from %s (story '%s')", page_name, url, story_id)
    discover(
        url=url,
        page_name=page_name,
        story=story_id,
        login_first=login_first,
        username=username,
        password=password,
        headless=config.HEADLESS,
    )
    generate_page_object(page_name, story=story_id, entry_page=entry_page, force=force_discover)


def run_story(
    story_id: str,
    extra_pages: dict[str, str] | None = None,
    username: str | None = None,
    password: str | None = None,
    force_discover: bool = False,
    run_tests: bool = False,
) -> Path:
    """THE BRAIN. Runs the full Flow B pipeline for one story, using
    utils/config.py's BASE_URL (your .env file) as the site to
    discover pages from. Returns the path to the generated test file.

    `extra_pages` is {page_name: path_relative_to_BASE_URL}, e.g.
    {"inventory": "/inventory.html"} - for any page besides the entry
    page (BASE_URL itself) that this story's flow needs. Each one is
    reached by logging in first via `username`/`password` (falling back
    to config.DEMO_USERNAME/DEMO_PASSWORD from .env if not given)."""
    story_path = USER_STORIES_DIR / f"{story_id}.txt"
    if not story_path.exists():
        raise FileNotFoundError(
            f"user_stories/{story_id}.txt not found - write your story there first."
        )

    logger.info("===== Brain: running Flow B for story '%s' (BASE_URL=%s) =====", story_id, config.BASE_URL)

    # Step 1: the entry page - BASE_URL itself.
    _ensure_page(story_id, config.ENTRY_PAGE_NAME, config.BASE_URL, entry_page=True, force_discover=force_discover)

    # Step 2: any further pages this story's flow needs.
    username = username or config.DEMO_USERNAME or None
    password = password or config.DEMO_PASSWORD or None
    for page_name, rel_path in (extra_pages or {}).items():
        url = config.BASE_URL.rstrip("/") + "/" + rel_path.lstrip("/")
        _ensure_page(
            story_id, page_name, url, entry_page=False, force_discover=force_discover,
            login_first=True, username=username, password=password,
        )

    # Step 3: story -> test cases (Agents 1-5, in their own folder).
    run_for_story(story_path)

    # Step 4: test cases -> a real, runnable script (Agent 8).
    out_path = write_script_for_story(story_id)

    logger.info("===== Brain finished: %s is ready =====", out_path)

    # Step 5 (optional): actually run it.
    if run_tests:
        logger.info("Brain: running the generated test now (--run was passed)")
        subprocess.run([sys.executable, "-m", "pytest", str(out_path.parent), "-v"], cwd=ROOT, check=False)
    else:
        print(f"\nGenerated: {out_path}")
        print("Review any '# TODO' lines, then run it yourself with:")
        print(f"    pytest {out_path.parent} -v")

    return out_path


def _parse_pages(raw: list[str] | None) -> dict[str, str]:
    """--pages inventory:/inventory.html cart:/cart.html -> a dict."""
    pages: dict[str, str] = {}
    for item in raw or []:
        if ":" not in item:
            raise SystemExit(f"--pages entries must look like name:/path, got: {item!r}")
        name, path = item.split(":", 1)
        pages[name.strip()] = path.strip()
    return pages


def main() -> None:
    parser = argparse.ArgumentParser(
        description="The framework's brain. No args = Flow A demo. --story = Flow B, driven by .env's BASE_URL."
    )
    parser.add_argument("--story", default=None, help="Run Flow B for user_stories/<story>.txt")
    parser.add_argument(
        "--pages", nargs="*", default=None,
        help="Extra pages this story needs, as name:/path (e.g. inventory:/inventory.html), space-separated",
    )
    parser.add_argument("--username", default=None, help="Login used to discover --pages (falls back to .env's DEMO_USERNAME)")
    parser.add_argument("--password", default=None, help="Login used to discover --pages (falls back to .env's DEMO_PASSWORD)")
    parser.add_argument("--force-discover", action="store_true", help="Re-discover pages even if they already exist")
    parser.add_argument("--run", action="store_true", help="Also run the generated test with pytest when done")
    args = parser.parse_args()

    if args.story:
        run_story(
            story_id=args.story,
            extra_pages=_parse_pages(args.pages),
            username=args.username,
            password=args.password,
            force_discover=args.force_discover,
            run_tests=args.run,
        )
    else:
        output = run_pipeline()
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()