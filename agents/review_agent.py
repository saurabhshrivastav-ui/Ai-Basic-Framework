"""
================================================================================
 AGENT 10 - THE REVIEW AGENT
================================================================================
THINK OF IT LIKE: a strict but fair teacher marking homework with a
checklist, not just a red pen. The teacher isn't grading whether the
ANSWER is correct (that's Agent 9's job, and pytest's, when the tests
actually run) - they're grading whether the homework was written the
way the class was taught to write it: neat handwriting (naming),
no copy-pasted paragraphs (reusability), nothing fragile that will
fall apart later (stability), and nothing that will confuse the next
student who has to read it (maintainability).

This agent reads every Page Object (`pages/*.py`) and every test file
(`tests/**/*.py`) and checks them - using Python's own `ast` module,
which reads code the same way a compiler does, not just as plain text -
against five things the spec asks for by name:

    1. POM Compliance      - rule from the spec: "No assertions inside
                              page objects." A page object that
                              contains `assert` is breaking that rule.
    2. Naming Convention   - classes should be PascalCase
                              (e.g. `LoginPage`), functions/methods
                              should be snake_case (e.g. `login_page`).
    3. Reusability          - a test calling `page.locator(...)`
                              directly (instead of going through a page
                              object method) duplicates locator logic
                              that should live in ONE place.
    4. Stability            - `time.sleep(...)` anywhere is a red flag:
                              the AUTOMATION STANDARDS section of the
                              spec explicitly says "Never generate...
                              Sleep statements" - a fixed sleep is
                              either too short (flaky) or too long
                              (slow) almost every time.
    5. Maintainability      - functions that have grown very long, or
                              have no docstring explaining what they do.

WHY run this automatically instead of just reading the code yourself?
Because a framework that GENERATES code (which is the whole point of
this project) needs a way to catch itself breaking its own rules,
without a human having to re-read every generated file by hand every
time.

Run this any time after generating or changing pages/*.py or
tests/**/*.py:

    python agents/review_agent.py

It writes:
    reports/review_report.json  - every finding, machine-readable
    reports/review_report.txt   - the same thing, easy to read in a terminal
================================================================================
"""
from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.ai_client import ai_client  # noqa: E402
from utils.logger import get_logger  # noqa: E402

logger = get_logger("agent.review")

PAGES_DIR = ROOT / "pages"
TESTS_DIR = ROOT / "tests"
REPORT_JSON = ROOT / "reports" / "review_report.json"
REPORT_TEXT = ROOT / "reports" / "review_report.txt"

SNAKE_CASE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
PASCAL_CASE_RE = re.compile(r"^[A-Z][a-zA-Z0-9]*$")

# A function/method longer than this many lines gets flagged as "consider
# splitting this up" - not a hard science, just a common rule-of-thumb
# threshold real style guides use.
MAX_REASONABLE_FUNCTION_LINES = 40


@dataclass
class Finding:
    file: str
    line: int
    category: str      # POM Compliance / Naming Convention / Reusability / Stability / Maintainability
    severity: str       # "high" | "medium" | "low"
    message: str


def _iter_py_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(p for p in directory.rglob("*.py") if p.name != "__init__.py")


def _check_pom_compliance(path: Path, tree: ast.AST, findings: list[Finding]) -> None:
    """PAGE OBJECT RULE #1 in the spec: 'No assertions inside page objects.'"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            findings.append(Finding(
                file=str(path.relative_to(ROOT)), line=node.lineno,
                category="POM Compliance", severity="high",
                message="assert found inside a page object - assertions belong only in tests/*.py",
            ))


def _check_naming(path: Path, tree: ast.AST, findings: list[Finding]) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and not PASCAL_CASE_RE.match(node.name):
            findings.append(Finding(
                file=str(path.relative_to(ROOT)), line=node.lineno,
                category="Naming Convention", severity="low",
                message=f"class '{node.name}' should be PascalCase, e.g. 'LoginPage'",
            ))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("__"):
            if not SNAKE_CASE_RE.match(node.name):
                findings.append(Finding(
                    file=str(path.relative_to(ROOT)), line=node.lineno,
                    category="Naming Convention", severity="low",
                    message=f"function '{node.name}' should be snake_case, e.g. 'get_error_text'",
                ))


def _check_forbidden_patterns(path: Path, source: str, findings: list[Finding]) -> None:
    """AUTOMATION STANDARDS in the spec: never generate hardcoded
    credentials, hardcoded URLs, or sleep statements."""
    for i, line in enumerate(source.splitlines(), start=1):
        if re.search(r"\btime\.sleep\s*\(", line):
            findings.append(Finding(
                file=str(path.relative_to(ROOT)), line=i,
                category="Stability", severity="high",
                message="time.sleep() found - use Playwright's explicit/auto waits instead of a fixed sleep",
            ))
        if re.search(r"https?://", line) and "config" not in line.lower():
            findings.append(Finding(
                file=str(path.relative_to(ROOT)), line=i,
                category="Reusability", severity="medium",
                message="hardcoded URL found - read it from utils/config.py instead",
            ))
        if re.search(r"password\s*=\s*[\"'][^\"']+[\"']", line, re.IGNORECASE):
            findings.append(Finding(
                file=str(path.relative_to(ROOT)), line=i,
                category="POM Compliance", severity="high",
                message="possible hardcoded credential - load it from data/test_data.json or .env instead",
            ))


def _check_maintainability(path: Path, tree: ast.AST, findings: list[Finding]) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        length = (node.end_lineno or node.lineno) - node.lineno
        if length > MAX_REASONABLE_FUNCTION_LINES:
            findings.append(Finding(
                file=str(path.relative_to(ROOT)), line=node.lineno,
                category="Maintainability", severity="medium",
                message=f"function '{node.name}' is {length} lines long - consider splitting it up",
            ))
        is_private_or_test = node.name.startswith("_") or node.name.startswith("test_")
        if ast.get_docstring(node) is None and not is_private_or_test:
            findings.append(Finding(
                file=str(path.relative_to(ROOT)), line=node.lineno,
                category="Maintainability", severity="low",
                message=f"'{node.name}' has no docstring explaining what it does",
            ))


def _check_reusability_direct_locator_use(path: Path, source: str, findings: list[Finding]) -> None:
    """Tests should drive the app only through page-object methods, never
    by calling page.locator(...) / page.get_by_...(...) directly - doing
    so bypasses the self-healing resolver and duplicates locator logic
    that should live in exactly one place (locators/*.json)."""
    if TESTS_DIR not in path.parents:
        return
    for i, line in enumerate(source.splitlines(), start=1):
        if re.search(r"\bpage\.(locator|get_by_\w+)\s*\(", line):
            findings.append(Finding(
                file=str(path.relative_to(ROOT)), line=i,
                category="Reusability", severity="medium",
                message="test calls a raw Playwright locator directly - add a method to the page object instead",
            ))


def review_framework() -> dict:
    """Statically reviews every page object and test file. Returns (and
    writes to reports/) a dict with every finding plus a rough 0-100
    compliance score."""
    logger.info("Agent 10 (Review Agent): reviewing pages/ and tests/ ...")

    ai_client.complete(
        system_prompt=(
            "You are Agent 10: Review Agent. Review the given Playwright "
            "Python automation code for POM compliance, naming convention, "
            "reusability, stability and maintainability. Suggest improvements."
        ),
        user_prompt="(Phase 2: the actual file contents would be sent here.)",
    )  # Always None today - falls back to the static checks below (see utils/ai_client.py).

    files = _iter_py_files(PAGES_DIR) + _iter_py_files(TESTS_DIR)
    findings: list[Finding] = []

    for path in files:
        source = path.read_text()
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            findings.append(Finding(
                file=str(path.relative_to(ROOT)), line=exc.lineno or 0,
                category="Maintainability", severity="high",
                message=f"file has a syntax error and could not be parsed: {exc.msg}",
            ))
            continue

        if PAGES_DIR in path.parents:
            _check_pom_compliance(path, tree, findings)
        _check_naming(path, tree, findings)
        _check_forbidden_patterns(path, source, findings)
        _check_maintainability(path, tree, findings)
        _check_reusability_direct_locator_use(path, source, findings)

    total = len(findings)
    high = sum(1 for f in findings if f.severity == "high")
    medium = sum(1 for f in findings if f.severity == "medium")
    # A simple, readable scoring rule - not a scientific formula: high
    # severity findings cost the most, medium a bit less, low the least.
    low = total - high - medium
    score = max(0, 100 - high * 15 - medium * 5 - low * 2)

    summary = {
        "files_reviewed": len(files),
        "findings_count": total,
        "high_severity_count": high,
        "medium_severity_count": medium,
        "low_severity_count": low,
        "compliance_score_percent": score,
        "findings": [f.__dict__ for f in findings],
    }

    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(summary, indent=2))
    REPORT_TEXT.write_text(render_text_report(summary))
    logger.info(
        "Agent 10 output: %d finding(s) across %d file(s) (%d high severity) - compliance score %d%%",
        total, len(files), high, score,
    )
    return summary


def render_text_report(summary: dict) -> str:
    lines = [
        f"Files reviewed  : {summary['files_reviewed']}",
        f"Findings        : {summary['findings_count']} "
        f"({summary['high_severity_count']} high, {summary['medium_severity_count']} medium, "
        f"{summary['low_severity_count']} low)",
        f"Compliance score: {summary['compliance_score_percent']}%",
        "",
    ]
    if summary["findings"]:
        lines.append("Findings:")
        for f in summary["findings"]:
            lines.append(f"  [{f['severity'].upper():6}] {f['category']:16} {f['file']}:{f['line']} - {f['message']}")
    else:
        lines.append("No issues found - the reviewed files follow every rule checked here.")
    return "\n".join(lines)


if __name__ == "__main__":
    result = review_framework()
    print(render_text_report(result))