"""
================================================================================
 THE RAG AGENT - rag/knowledge_base.py
================================================================================
THINK OF IT LIKE: a librarian who has read every test the team has ever
written, and can instantly say "this sounds like the returns-policy
test we wrote in March" the moment you describe a new one - without
needing to have memorized the exact wording.

WHY this exists: the original spec says, before generating anything
new, search a knowledge base of existing scripts/page objects/test
cases/business rules and REUSE whatever already fits, instead of
quietly generating near-duplicate automation every time. That is
exactly what this file does.

WHAT KIND OF "AI" IS THIS? An honest, working one that needs NO API
key, NO internet, and NO vector database - a real Phase 1 RAG, not a
placeholder. It compares two pieces of text by which WORDS they share
in common (this is called "lexical" or "keyword" search), scored with
a well-known, simple formula called Jaccard similarity:

    similarity = (words both texts share) / (all words either text has)

Example: "log in with valid credentials" vs "log in with a locked
account" share {log, in, with} out of 7 unique words total -> ~0.43
similarity. Good enough to say "these two are clearly related" -
nowhere near as smart as a real AI model that understands MEANING
(which would also catch "sign in" as similar to "log in", even though
they share zero words), but it costs nothing to run and never needs
credentials.

PHASE 2 UPGRADE PATH: replace the body of `_score()` with a call to a
real embedding model (e.g. `ai_client`-style, or a local
sentence-transformers model) and everything that CALLS search_*()
below keeps working unchanged - the function signatures are the
"socket", exactly like utils/ai_client.py is for the other agents.

WHAT GETS INDEXED (and by whom):
    index_test_cases(story_id, test_cases)   <- called by agents/test_case_pipeline.py
    index_page_object(page_name, manifest)   <- called by agents/pom_generator_agent.py
    index_business_rules(module, rules)      <- called by agents/test_case_pipeline.py

WHAT GETS SEARCHED (and by whom):
    search_test_cases(query)     <- test_case_pipeline.py, before generating new ones
    search_page_objects(query)   <- locator_discovery_agent.py / pom_generator_agent.py,
                                     before scraping/generating a page that might already exist
    search_business_rules(query) <- test_case_pipeline.py, to reuse known rules for a module

Everything is stored as plain JSON under rag/index/ - readable,
diffable, and needs nothing installed beyond Python itself.
================================================================================
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.text import jaccard_score, tokenize as _tokenize  # noqa: E402

INDEX_DIR = ROOT / "rag" / "index"
TEST_CASES_INDEX = INDEX_DIR / "test_cases_index.json"
PAGE_OBJECTS_INDEX = INDEX_DIR / "page_objects_index.json"
BUSINESS_RULES_INDEX = INDEX_DIR / "business_rules_index.json"


def _score(query_tokens: set[str], doc_tokens: set[str]) -> float:
    """Jaccard similarity: 0.0 (nothing in common) to 1.0 (identical
    word sets) - see utils/text.py. See this module's own docstring
    above for the plain-English version of what that means here."""
    return jaccard_score(query_tokens, doc_tokens)


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _save(path: Path, data: dict[str, Any]) -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _search(index: dict[str, dict], query: str, top_k: int, exclude_key: str | None = None) -> list[dict]:
    query_tokens = _tokenize(query)
    scored = []
    for key, entry in index.items():
        if key == exclude_key:
            continue
        score = _score(query_tokens, set(entry.get("tokens", [])))
        if score > 0:
            scored.append({**{k: v for k, v in entry.items() if k != "tokens"}, "key": key, "score": round(score, 3)})
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:top_k]


# -------------------------------------------------------------------- #
# Test cases
# -------------------------------------------------------------------- #
def index_test_cases(story_id: str, test_cases: list[dict]) -> None:
    """Adds/updates every test case from one story into the knowledge
    base, so future stories can be checked for overlap against it."""
    index = _load(TEST_CASES_INDEX)
    for tc in test_cases:
        key = f"{story_id}:{tc.get('test_case_id', 'TC')}"
        text = " ".join([tc.get("title", ""), " ".join(tc.get("steps", [])), tc.get("expected_result", "")])
        index[key] = {
            "story_id": story_id,
            "test_case_id": tc.get("test_case_id"),
            "title": tc.get("title"),
            "tokens": sorted(_tokenize(text)),
        }
    _save(TEST_CASES_INDEX, index)


def search_test_cases(query: str, top_k: int = 3, exclude_story: str | None = None) -> list[dict]:
    index = _load(TEST_CASES_INDEX)
    if exclude_story:
        index = {k: v for k, v in index.items() if v.get("story_id") != exclude_story}
    return _search(index, query, top_k)


# -------------------------------------------------------------------- #
# Page objects
# -------------------------------------------------------------------- #
def index_page_object(page_name: str, manifest: list[dict]) -> None:
    """`manifest` is the list produced by agents/pom_generator_agent.py:
    one entry per generated method, each with its trigger phrases."""
    index = _load(PAGE_OBJECTS_INDEX)
    phrases = []
    for entry in manifest:
        phrases.append(entry.get("method", ""))
        phrases.extend(entry.get("phrases", []))
    text = page_name + " " + " ".join(phrases)
    index[page_name] = {
        "page_name": page_name,
        "method_count": len(manifest),
        "tokens": sorted(_tokenize(text)),
    }
    _save(PAGE_OBJECTS_INDEX, index)


def search_page_objects(query: str, top_k: int = 3, exclude_key: str | None = None) -> list[dict]:
    index = _load(PAGE_OBJECTS_INDEX)
    return _search(index, query, top_k, exclude_key=exclude_key)


# -------------------------------------------------------------------- #
# Business rules
# -------------------------------------------------------------------- #
def index_business_rules(module: str, rules: list[str]) -> None:
    index = _load(BUSINESS_RULES_INDEX)
    text = module + " " + " ".join(rules)
    index[module] = {
        "module": module,
        "rule_count": len(rules),
        "rules": rules,
        "tokens": sorted(_tokenize(text)),
    }
    _save(BUSINESS_RULES_INDEX, index)


def search_business_rules(query: str, top_k: int = 3) -> list[dict]:
    index = _load(BUSINESS_RULES_INDEX)
    return _search(index, query, top_k)


if __name__ == "__main__":
    # Tiny demo/self-check - safe to run any time, touches no other file.
    index_test_cases("demo_story", [
        {"test_case_id": "TC-01", "title": "Happy Path - log in and check out",
         "steps": ["Open the login page", "Enter a valid username", "Enter a valid password"],
         "expected_result": "Order completes"},
    ])
    print("search_test_cases('login with valid credentials'):")
    for r in search_test_cases("login with valid credentials"):
        print(" ", r)