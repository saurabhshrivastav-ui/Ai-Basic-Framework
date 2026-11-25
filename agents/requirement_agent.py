"""
================================================================================
 AGENT 1 - THE REQUIREMENT AGENT
================================================================================
THINK OF IT LIKE: a waiter at a restaurant.

A customer (you) describes what they want in plain, everyday language
("I'd like something spicy, not too heavy, and I'm allergic to peanuts").
The waiter doesn't cook anything. The waiter's ONLY job is to turn that
into a clear, structured order the kitchen can work from:

    dish: "spicy noodles"
    spice_level: "high"
    allergies: ["peanuts"]

That is exactly what this agent does with a business requirement. It
reads your plain-English description of a feature and turns it into a
small, structured dictionary that every other agent downstream can rely
on having, every single time:

    {
      "module": "...",
      "actor": "...",
      "preconditions": [...],
      "workflow": [...],
      "expected_result": "..."
    }

WHY does this need its own agent, instead of every later step just
re-reading the raw paragraph? Because raw text is messy, and everyone
(and everything) reads it a little differently. A structured dictionary
is predictable - Agent 2, 3 and 4 can all trust it has exactly these
five fields, every time, no matter how the original paragraph was
worded.
================================================================================
"""
from __future__ import annotations

import re

from utils.ai_client import ai_client
from utils.logger import get_logger

logger = get_logger("agent.requirement")


def analyze_requirement(requirement_text: str) -> dict:
    """
    Turn a plain-English requirement into the structured dictionary shown
    above.

    Today this is done with simple, readable rules (no AI call, no
    internet needed). Later, you can make this understand much messier,
    more varied English by asking a real AI model to do the same job -
    see the `ai_client.complete(...)` call below; when AI_PROVIDER is
    configured in Phase 2, its reply is used instead of the rules.
    """
    logger.info("Agent 1 (Requirement Agent): analyzing requirement text")

    ai_result = ai_client.complete(
        system_prompt=(
            "You are Agent 1: Requirement Agent. Read the business "
            "requirement below and return ONLY JSON with these keys: "
            "module, actor, preconditions (list), workflow (list), "
            "expected_result (string)."
        ),
        user_prompt=requirement_text,
    )
    if ai_result:
        # Phase 2: parse the AI's JSON reply here instead of the rules
        # below, e.g. `return json.loads(ai_result)`.
        pass

    # ---------------- RULE-BASED VERSION (works today) ----------------
    lines = [l.strip("-• \t") for l in requirement_text.strip().splitlines() if l.strip()]

    result = {
        "module": _find_module(requirement_text),
        "actor": _find_actor(requirement_text),
        "preconditions": _find_preconditions(lines),
        "workflow": _find_workflow_steps(lines),
        "expected_result": _find_expected_result(lines),
    }
    logger.info("Agent 1 output: module=%s actor=%s", result["module"], result["actor"])
    return result


def _find_actor(text: str) -> str:
    match = re.search(r"[Aa]s an?\s+([A-Za-z ]+?),", text)
    if match:
        return match.group(1).strip()
    return "User"


def _find_module(text: str) -> str:
    for keyword in ["login", "checkout", "cart", "payment", "registration", "search"]:
        if keyword in text.lower():
            return keyword.capitalize()
    return "General"


def _find_preconditions(lines: list[str]) -> list[str]:
    preconditions: list[str] = []
    capturing = False
    for line in lines:
        low = line.lower()
        if low.startswith("precondition"):
            capturing = True
            continue
        if capturing:
            if low.startswith(("workflow", "steps", "acceptance", "expected")):
                break
            preconditions.append(line)
    if not preconditions:
        preconditions = ["User has a valid account", "Application is reachable"]
    return preconditions


def _find_workflow_steps(lines: list[str]) -> list[str]:
    steps: list[str] = []
    capturing = False
    for line in lines:
        low = line.lower()
        if low.startswith(("workflow", "steps")):
            capturing = True
            continue
        if low.startswith("i want to"):
            steps.append(line)
            continue
        if capturing:
            if low.startswith(("expected", "acceptance")):
                break
            steps.append(line)
    if not steps:
        steps = [lines[0]] if lines else ["No workflow described"]
    return steps


def _find_expected_result(lines: list[str]) -> str:
    for i, line in enumerate(lines):
        low = line.lower()
        if low.startswith(("expected", "so that")):
            # If this line is just a header like "Expected Result:" with
            # nothing else on it, the real sentence is the next line.
            remainder = line.split(":", 1)[1].strip() if ":" in line else line
            if remainder:
                return remainder
            if i + 1 < len(lines):
                return lines[i + 1]
    return "Action completes successfully"