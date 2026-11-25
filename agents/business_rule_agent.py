"""
================================================================================
 AGENT 2 - THE BUSINESS RULE AGENT
================================================================================
THINK OF IT LIKE: the fine print under a coupon.

The requirement tells you WHAT to do ("log in and buy a t-shirt"). The
business rules tell you the CONDITIONS attached to that - the things
that must be true, or must NOT be allowed, for the feature to count as
"working correctly."

Example, using a login page:
  - "Username and password are both required" - a rule the requirement
    paragraph never spells out loud, but every login page has it.
  - "A locked-out account must not be able to log in."

This agent reads the structured requirement Agent 1 produced and pulls
out two kinds of rules:
  1. EXPLICIT rules - ones that were actually written down (look for
     words like "must", "should", "only", "cannot").
  2. HIDDEN rules - ones every experienced tester assumes for a given
     type of page, even if nobody wrote them down. These live in a
     small, editable "rule library" below, keyed by module name.
================================================================================
"""
from __future__ import annotations

from utils.ai_client import ai_client
from utils.logger import get_logger

logger = get_logger("agent.business_rule")


# A small, hand-written knowledge base of "obvious but unwritten" rules
# per module. This is exactly the kind of thing the RAG layer (see the
# rag/ folder) will eventually grow and look up automatically instead of
# living as a fixed Python dictionary.
_HIDDEN_RULE_LIBRARY: dict[str, list[str]] = {
    "login": [
        "Username field must not be submittable while empty",
        "Password field must not be submittable while empty",
        "A locked-out or disabled account must be rejected with a clear error message",
        "Password characters must be masked on screen",
    ],
    "cart": [
        "The cart item-count badge must match the number of items actually added",
        "Removing the only item in the cart must hide the item-count badge",
    ],
    "checkout": [
        "All required checkout fields must be filled before the order can continue",
        "The order total shown at the end must equal item total plus tax",
    ],
}


def extract_business_rules(structured_requirement: dict) -> dict:
    """
    Input: the dictionary produced by Agent 1 (analyze_requirement).
    Output: {"business_rules": [...]}
    """
    logger.info("Agent 2 (Business Rule Agent): extracting rules for module=%s",
                structured_requirement.get("module"))

    ai_result = ai_client.complete(
        system_prompt=(
            "You are Agent 2: Business Rule Agent. Given a structured "
            "requirement, list explicit and hidden business rules as "
            'JSON: {"business_rules": [...]}'
        ),
        user_prompt=str(structured_requirement),
    )
    if ai_result:
        pass  # Phase 2: parse the AI's JSON reply here instead.

    rules: list[str] = []

    # 1. Explicit rules: anything in the preconditions/workflow that
    #    reads like a rule.
    rule_signal_words = ("must", "should", "only", "cannot", "required")
    for source in structured_requirement.get("preconditions", []) + structured_requirement.get("workflow", []):
        if any(word in source.lower() for word in rule_signal_words):
            rules.append(source)

    # 2. Hidden rules, looked up by module name.
    module = structured_requirement.get("module", "").lower()
    rules.extend(_HIDDEN_RULE_LIBRARY.get(module, []))

    # De-duplicate while keeping the original order.
    seen: set[str] = set()
    unique_rules: list[str] = []
    for rule in rules:
        if rule not in seen:
            unique_rules.append(rule)
            seen.add(rule)

    logger.info("Agent 2 output: %d business rules found", len(unique_rules))
    return {"business_rules": unique_rules}