"""
================================================================================
 AGENT 15 - THE REPORTING AGENT
================================================================================
THINK OF IT LIKE: a sports scoreboard, not a play-by-play commentary.

A manager who has never touched this framework does not want to read
"test_login_blocked_with_empty_password[chromium] ... PASSED" - they
want to know, in five seconds: did today's run go well, and if not,
why not? That is exactly what this agent produces - a short "Business
Summary" built from the same Allure result files pytest already wrote,
in the format the original spec asked for:

    Total Tests : 50
    Passed : 47
    Failed : 3
    Blocked : 0
    Failure Reason:
      1. Payment API Timeout
      2. Locator Change
      3. Network Error
    Automation Health: 94%

Run this AFTER a pytest run (it reads reports/allure-results/*.json,
which pytest + allure-pytest already write for you):

    python agents/reporting_agent.py
================================================================================
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.logger import get_logger  # noqa: E402

logger = get_logger("agent.reporting")

ALLURE_RESULTS_DIR = ROOT / "reports" / "allure-results"
SUMMARY_JSON_PATH = ROOT / "reports" / "business_summary.json"
SUMMARY_TEXT_PATH = ROOT / "reports" / "business_summary.txt"


def generate_business_summary(results_dir: Path = ALLURE_RESULTS_DIR) -> dict:
    """
    Reads every Allure `*-result.json` file (one per test) and rolls
    them up into the small "Business Summary" dict described above.
    """
    result_files = sorted(results_dir.glob("*-result.json")) if results_dir.exists() else []
    results = [json.loads(f.read_text()) for f in result_files]

    total = len(results)
    passed = sum(1 for r in results if r.get("status") == "passed")
    failed = sum(1 for r in results if r.get("status") in ("failed", "broken"))
    blocked = sum(1 for r in results if r.get("status") == "skipped")
    health = round((passed / total) * 100, 1) if total else 0.0

    failure_reasons = []
    for r in results:
        if r.get("status") in ("failed", "broken"):
            details = r.get("statusDetails") or {}
            message = (details.get("message") or "Unknown failure").splitlines()[0]
            failure_reasons.append(f"{r.get('name', 'unknown test')}: {message}")

    return {
        "total_tests": total,
        "passed": passed,
        "failed": failed,
        "blocked": blocked,
        "automation_health_percent": health,
        "failure_reasons": failure_reasons,
    }


def render_text_summary(summary: dict) -> str:
    lines = [
        f"Total Tests : {summary['total_tests']}",
        f"Passed : {summary['passed']}",
        f"Failed : {summary['failed']}",
        f"Blocked : {summary['blocked']}",
        "",
        "Failure Reason:",
    ]
    if summary["failure_reasons"]:
        lines += [f"  {i}. {reason}" for i, reason in enumerate(summary["failure_reasons"], start=1)]
    else:
        lines.append("  (none)")
    lines += ["", f"Automation Health: {summary['automation_health_percent']}%"]
    return "\n".join(lines)


def write_reports() -> dict:
    summary = generate_business_summary()
    SUMMARY_JSON_PATH.write_text(json.dumps(summary, indent=2))
    text = render_text_summary(summary)
    SUMMARY_TEXT_PATH.write_text(text)
    logger.info(
        "Agent 15 output: %d/%d passed (%.1f%% health) - written to %s",
        summary["passed"], summary["total_tests"],
        summary["automation_health_percent"], SUMMARY_TEXT_PATH,
    )
    return summary


if __name__ == "__main__":
    result = write_reports()
    print(render_text_summary(result))