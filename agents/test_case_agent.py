"""
================================================================================
 AGENT 4 - THE TEST CASE AGENT
================================================================================
THINK OF IT LIKE: turning a scene description into an actual shot list.

Agent 3 handed us a *list of ideas* ("Happy Path: log in and check out").
This agent turns each idea into a precise, step-by-step recipe that a
robot (Playwright) can follow with zero guesswork:

    TC-01
    Title: Happy Path - complete the flow with fully valid data
    Steps:
      1. Open the login page
      2. Enter a valid username
      3. Enter a valid password
      4. Click the Login button
      ...
    Expected Result: The order completes and a confirmation is shown
    Priority: High

WHY keep this separate from the Scenario Agent? A scenario is an IDEA
("what if the account is locked?"). A test case is an EXACT RECIPE.
Keeping them as two separate agents means you can change how detailed
the recipes are without ever having to re-invent the list of ideas.
================================================================================
"""
from __future__ import annotations

from utils.ai_client import ai_client
from utils.logger import get_logger

logger = get_logger("agent.test_case")


# Step "recipes" per scenario type, written for our SauceDemo
# login + cart + checkout flow. In Phase 2, a real AI model could write
# recipes like these dynamically for ANY application; today they are
# explicit, readable Python so the framework runs with zero setup.
_STEP_LIBRARY: dict[str, dict] = {
    "Happy Path": {
        "steps": [
            "Open the login page",
            "Enter a valid username",
            "Enter a valid password",
            "Click the Login button",
            "Add a product to the cart",
            "Open the cart",
            "Proceed to checkout and fill in the required details",
            "Finish the order",
        ],
        "expected": "The order completes and a confirmation message is shown",
        "priority": "High",
        "suite": "smoke",
    },
    "Negative": {
        "steps": [
            "Open the login page",
            "Enter credentials that are invalid or belong to a locked account",
            "Click the Login button",
        ],
        "expected": "Login is rejected and a clear error message is shown",
        "priority": "High",
        "suite": "regression",
    },
    "Negative - Empty Field": {
        "steps": [
            "Open the login page",
            "Leave a required field (username or password) empty",
            "Click the Login button",
        ],
        "expected": "The action is blocked and a 'field required' error message is shown",
        "priority": "High",
        "suite": "regression",
    },
    "Boundary": {
        "steps": [
            "Log in with valid credentials",
            "Add exactly one product to the cart",
            "Open the cart",
        ],
        "expected": "The cart shows exactly one item with the correct count badge",
        "priority": "Medium",
        "suite": "sanity",
    },
    "Alternate Flow": {
        "steps": [
            "Log in with valid credentials",
            "Reach the cart via a different valid navigation path",
        ],
        "expected": "The same cart contents are reachable either way",
        "priority": "Low",
        "suite": "regression",
    },
    "Error Handling": {
        "steps": [
            "Log in with valid credentials",
            "Trigger a condition that would normally cause a server or network error",
        ],
        "expected": "The app shows a graceful error message instead of crashing",
        "priority": "Medium",
        "suite": "regression",
    },
}


def generate_test_cases(scenarios: list[dict], business_rules: dict) -> list[dict]:
    logger.info("Agent 4 (Test Case Agent): generating test cases for %d scenarios", len(scenarios))

    ai_result = ai_client.complete(
        system_prompt=(
            "You are Agent 4: Test Case Agent. Given a list of "
            "scenarios and business rules, produce detailed test cases "
            "as JSON, each with test_case_id, title, preconditions, "
            "steps, expected_result, priority."
        ),
        user_prompt=str({"scenarios": scenarios, "rules": business_rules}),
    )
    if ai_result:
        pass  # Phase 2: parse the AI's JSON reply here instead.

    test_cases: list[dict] = []
    for scenario in scenarios:
        recipe_key = scenario["type"]
        if scenario["type"] == "Negative" and "empty" in scenario["title"].lower():
            recipe_key = "Negative - Empty Field"
        recipe = _STEP_LIBRARY.get(recipe_key, _STEP_LIBRARY["Happy Path"])
        test_cases.append({
            "test_case_id": scenario["id"].replace("SCN", "TC"),
            "title": scenario["title"],
            "preconditions": ["Application is reachable", "Test data is available"],
            "steps": recipe["steps"],
            "expected_result": recipe["expected"],
            "priority": recipe["priority"],
            "suite": recipe["suite"],
            "linked_scenario": scenario["id"],
        })

    logger.info("Agent 4 output: %d test cases generated", len(test_cases))
    return test_cases