"""
================================================================================
 AGENT 3 - THE SCENARIO AGENT
================================================================================
THINK OF IT LIKE: a film director planning every version of one scene.

Given one workflow ("log in, add an item to the cart, check out"), this
agent imagines every realistic way that scene could play out:

  - Happy Path     : everything goes right (correct username/password)
  - Negative       : something is deliberately wrong on purpose (locked
                      account, wrong password, empty required field)
  - Alternate Flow : a different-but-still-valid route to the same goal
  - Boundary       : an edge-of-the-rules case (exactly one item in the
                      cart, the shortest/longest allowed input)
  - Error Handling : the app is asked to cope with something broken
                      (a network drop, a server error page)

WHY do we need all five kinds, not just the happy path? Because a real
customer will eventually hit every one of these by accident. A test
framework that only checks the happy path only proves the feature works
when absolutely nothing goes wrong - which, in practice, is the least
useful thing to know about it.
================================================================================
"""
from __future__ import annotations

from utils.ai_client import ai_client
from utils.logger import get_logger

logger = get_logger("agent.scenario")


def generate_scenarios(structured_requirement: dict, business_rules: dict) -> list[dict]:
    """
    Output: a list of scenario dicts, e.g.
        {"id": "SCN-01", "type": "Happy Path", "title": "..."}
    """
    module = structured_requirement.get("module", "Feature")
    logger.info("Agent 3 (Scenario Agent): generating scenarios for module=%s", module)

    ai_result = ai_client.complete(
        system_prompt=(
            "You are Agent 3: Scenario Agent. Given a structured "
            "requirement and its business rules, generate Happy Path, "
            "Negative, Alternate Flow, Boundary, and Error Handling "
            "scenarios as a JSON list."
        ),
        user_prompt=str({"requirement": structured_requirement, "rules": business_rules}),
    )
    if ai_result:
        pass  # Phase 2: parse the AI's JSON reply here instead.

    scenarios: list[dict] = []
    counter = 1

    def add(scenario_type: str, title: str) -> None:
        nonlocal counter
        scenarios.append({
            "id": f"SCN-{counter:02d}",
            "type": scenario_type,
            "title": title,
        })
        counter += 1

    add("Happy Path", f"{module}: complete the flow with fully valid data")
    add("Negative", f"{module}: attempt the flow with an invalid or locked account")
    add("Negative", f"{module}: attempt the flow with a required field left empty")
    add("Boundary", f"{module}: attempt the flow with exactly one item / minimum valid input")
    add("Alternate Flow", f"{module}: reach the same goal via a different valid path")
    add("Error Handling", f"{module}: attempt the flow while the app returns an error page")

    logger.info("Agent 3 output: %d scenarios generated", len(scenarios))
    return scenarios