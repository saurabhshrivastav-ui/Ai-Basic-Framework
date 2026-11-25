"""
================================================================================
 agents/test_case_pipeline.py - USER STORY -> test_cases/<story>/ FOLDER
================================================================================
THINK OF IT LIKE: dropping a request into an in-tray and getting back a
labeled folder with everything sorted inside - one folder per request,
never mixed together.

THIS IS STEP 1 of the flow you asked for:

    you write a story  ->  [THIS FILE generates test cases in their
                             own folder]  ->  a script gets written
                             using your page objects  ->  you run it

You write a plain-English user story as a .txt file in user_stories/
(see user_stories/login_checkout.txt for an example already in this
project). This file reads it and runs it through Agents 1-5 - the same
five agents agents/orchestrator.py already used (Requirement -> Business
Rule -> Scenario -> Test Case -> Test Data) - except instead of dumping
everything into one shared data/ folder, EVERY story gets its own
folder under test_cases/, named after the story file:

    user_stories/login_checkout.txt
        -> test_cases/login_checkout/requirement_analysis.json
        -> test_cases/login_checkout/business_rules.json
        -> test_cases/login_checkout/scenarios.json
        -> test_cases/login_checkout/test_cases.json
        -> test_cases/login_checkout/test_data.json
        -> test_cases/login_checkout/rag_matches.json
        -> test_cases/login_checkout/pipeline_output.json  (all of the above, combined)

WHY a separate folder per story? Two reasons. First, so ten different
stories never overwrite each other's test cases - today's login story
and next week's search-feature story can both live in this project at
once. Second, agents/script_writer_agent.py (the next step) takes a
story's folder name and knows exactly where to find everything it
needs to write that story's test script.

RAG CHECK: before generating anything, this file asks rag/knowledge_base.py
"have we already written a test case that sounds like this one?" - the
spec's RAG AGENT requirement ("search knowledge base... reuse existing
components... avoid duplicate automation"). Matches are logged AND
saved to rag_matches.json, so a human can glance at them and decide
whether this story is genuinely new work or overlaps with something
already automated. It never blocks generation - a human decides.

USAGE:
    python agents/test_case_pipeline.py user_stories/login_checkout.txt
================================================================================
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.business_rule_agent import extract_business_rules  # noqa: E402
from agents.requirement_agent import analyze_requirement  # noqa: E402
from agents.scenario_agent import generate_scenarios  # noqa: E402
from agents.test_case_agent import generate_test_cases  # noqa: E402
from agents.test_data_agent import generate_test_data  # noqa: E402
from rag import knowledge_base as rag  # noqa: E402
from utils.logger import get_logger  # noqa: E402
from utils.text import slugify as _slugify  # noqa: E402

logger = get_logger("agent.test_case_pipeline")

TEST_CASES_DIR = ROOT / "test_cases"


def run_for_story(story_path: Path) -> dict:
    """Reads one user_stories/*.txt file, runs Agents 1-5 on it, and
    writes every result into its own test_cases/<slug>/ folder. Returns
    the full combined result dict (also written as pipeline_output.json)."""
    story_text = story_path.read_text()
    story_id = _slugify(story_path.stem)
    out_dir = TEST_CASES_DIR / story_id
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Pipeline: processing '%s' -> test_cases/%s/", story_path.name, story_id)

    rag_hits = rag.search_test_cases(story_text, top_k=3, exclude_story=story_id)
    if rag_hits:
        logger.warning("RAG: %d existing test case(s) look similar to this story - review before duplicating effort:",
                        len(rag_hits))
        for hit in rag_hits:
            logger.warning("  %.0f%% similar: %s '%s' (from story '%s')",
                            hit["score"] * 100, hit["test_case_id"], hit["title"], hit["story_id"])

    structured_requirement = analyze_requirement(story_text)
    business_rules = extract_business_rules(structured_requirement)
    rag.index_business_rules(structured_requirement.get("module", "General"), business_rules["business_rules"])

    scenarios = generate_scenarios(structured_requirement, business_rules)
    test_cases = generate_test_cases(scenarios, business_rules)
    test_data = generate_test_data(test_cases, out_dir / "test_data.json")

    rag.index_test_cases(story_id, test_cases)

    (out_dir / "requirement_analysis.json").write_text(json.dumps(structured_requirement, indent=2))
    (out_dir / "business_rules.json").write_text(json.dumps(business_rules, indent=2))
    (out_dir / "scenarios.json").write_text(json.dumps(scenarios, indent=2))
    (out_dir / "test_cases.json").write_text(json.dumps(test_cases, indent=2))
    (out_dir / "rag_matches.json").write_text(json.dumps(rag_hits, indent=2))

    result = {
        "story_id": story_id,
        "story_file": str(story_path),
        "out_dir": str(out_dir),
        "requirement_analysis": structured_requirement,
        "business_rules": business_rules,
        "scenarios": scenarios,
        "test_cases": test_cases,
        "test_data": test_data,
        "rag_matches": rag_hits,
    }
    (out_dir / "pipeline_output.json").write_text(json.dumps(result, indent=2))

    logger.info("Pipeline output: %d test case(s), %d scenario(s) written to %s",
                len(test_cases), len(scenarios), out_dir)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Turn a user story into test cases, in their own folder.")
    parser.add_argument("story", help="Path to a user_stories/*.txt file")
    args = parser.parse_args()

    result = run_for_story(Path(args.story))
    print(json.dumps({
        "story_id": result["story_id"],
        "out_dir": result["out_dir"],
        "test_case_count": len(result["test_cases"]),
        "similar_existing_test_cases": len(result["rag_matches"]),
    }, indent=2))


if __name__ == "__main__":
    main()