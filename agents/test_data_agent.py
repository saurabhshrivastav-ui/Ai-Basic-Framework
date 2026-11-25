"""
================================================================================
 AGENT 5 - THE TEST DATA AGENT
================================================================================
THINK OF IT LIKE: the props department for a film shoot.

The script (the test cases) says "the actor logs in with a valid
username and password." Someone still has to hand the actor an actual
username and an actual password to type. That is what this agent does -
it produces the concrete values (usernames, passwords, product names...)
that the Playwright scripts will actually type into the browser.

WHY keep data separate from the test steps? So you can change WHO logs
in (swap in a different test account) without touching a single line of
test logic - and so nobody ever has to hardcode a password inside a
script.
================================================================================
"""
from __future__ import annotations

import json
from pathlib import Path

from utils.ai_client import ai_client
from utils.logger import get_logger

logger = get_logger("agent.test_data")


# NOTE: these are SauceDemo's own published, public demo accounts - not
# real credentials, so it is fine to keep them in a plain data file for
# this practice project. For a real client project, credentials belong
# in your CI's secret store or a local, un-committed .env file, never
# in a JSON file that could end up in version control.
_SAUCEDEMO_USERS = {
    "valid_user": {"username": "standard_user", "password": "secret_sauce"},
    "locked_user": {"username": "locked_out_user", "password": "secret_sauce"},
    "problem_user": {"username": "problem_user", "password": "secret_sauce"},
}


def generate_test_data(test_cases: list[dict], out_path: str | Path) -> dict:
    logger.info("Agent 5 (Test Data Agent): generating test data for %d test cases", len(test_cases))

    ai_result = ai_client.complete(
        system_prompt=(
            "You are Agent 5: Test Data Agent. Given a list of test "
            "cases, produce realistic JSON test data (users, products, "
            "checkout info) needed to execute them."
        ),
        user_prompt=str(test_cases),
    )
    if ai_result:
        pass  # Phase 2: parse the AI's JSON reply here instead.

    data = {
        "users": _SAUCEDEMO_USERS,
        "products": {
            "primary": "Sauce Labs Backpack",
        },
        "checkout_info": {
            "first_name": "Rahul",
            "last_name": "Sharma",
            "postal_code": "400001",
        },
    }

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2))
    logger.info("Agent 5 output: test data written to %s", out_path)
    return data