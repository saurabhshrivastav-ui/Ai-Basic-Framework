"""
================================================================================
 utils/text.py - SMALL TEXT HELPERS SHARED ACROSS AGENTS
================================================================================
Three tiny, dependency-free functions several agents all need. Pulling
them out here (instead of each agent re-writing its own copy) follows
the spec's own AUTOMATION STANDARDS rule: "Never generate... Duplicate
code."

  - slugify(text)                 "Login Checkout!" -> "login_checkout"
                                   used for folder/file/function names.
  - tokenize(text)                "Click the Login button" -> {"click","the","login","button"}
                                   breaks text into a set of lowercase words.
  - jaccard_score(a, b)           how much two word-sets overlap, 0.0-1.0.
                                   The same lexical-matching math
                                   rag/knowledge_base.py uses for RAG
                                   search, reused by
                                   agents/script_writer_agent.py to match
                                   a test-case step to the right
                                   page-object method.
================================================================================
"""
from __future__ import annotations

import re

_WORD_RE = re.compile(r"[a-z0-9]+")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "item"


def tokenize(text: str) -> set[str]:
    return set(_WORD_RE.findall(str(text).lower()))


def jaccard_score(a: set[str], b: set[str]) -> float:
    """0.0 = nothing in common, 1.0 = identical word sets."""
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0