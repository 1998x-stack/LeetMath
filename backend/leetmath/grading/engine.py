"""Public grading facade: maps a part's answer spec + response to a GradeResult."""
from __future__ import annotations

from decimal import Decimal

from .checkers import SANDBOXED, GradeResult, invalid, pending, run_checker
from .sandbox import run_sandboxed

# Which checker types are valid per response_type (preflight uses this).
CHECKERS_FOR_RESPONSE = {
    "single_choice": {"choice_exact"},
    "multiple_choice": {"choice_set"},
    "integer": {"integer_exact"},
    "rational": {"rational_exact"},
    "decimal": {"decimal_tolerance"},
    "expression": {"symbolic_equivalence"},
    "interval": {"interval_set"},
    "set": {"finite_set"},
    "equation_set": {"finite_set"},
}
MANUAL_ONLY = {"proof", "derivation", "drawing", "short_text", "matrix", "vector"}


def grade(
    response_type: str,
    grading_mode: str,
    checker_type: str,
    spec: dict,
    raw_input: str,
    max_score: Decimal,
    option_ids: set[str] | None = None,
    sandbox: bool = True,
) -> GradeResult:
    if not isinstance(raw_input, str) or not raw_input.strip():
        return invalid(max_score, "EMPTY_RESPONSE", "答案不能为空")
    if len(raw_input) > 2000:
        return invalid(max_score, "INVALID_MATH_INPUT", "输入过长")
    if grading_mode in ("manual",) or response_type in MANUAL_ONLY or checker_type == "rubric_manual":
        return pending(max_score, "MANUAL_GRADING", "已提交，等待教师按评分点批改")
    if grading_mode == "practice_only":
        return pending(max_score, "PRACTICE_ONLY", "练习模式：不自动评分，请对照解析自查")
    if checker_type not in CHECKERS_FOR_RESPONSE.get(response_type, set()):
        return pending(max_score, "UNSUPPORTED_CHECKER", "不支持的判题配置，已转人工")
    if sandbox and checker_type in SANDBOXED:
        result = run_sandboxed(
            {
                "checker_type": checker_type,
                "spec": spec,
                "raw": raw_input,
                "max_score": str(max_score),
                "option_ids": sorted(option_ids or []),
            }
        )
    else:
        result = run_checker(checker_type, spec, raw_input, max_score, option_ids)
    if grading_mode == "hybrid" and result.status == "accepted":
        # hybrid: auto-accept the final answer, but steps still need teacher review for full marks
        result.details["hybrid"] = True
    return result
