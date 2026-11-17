"""Content Contract v1: JSON Schema + semantic preflight + canonical hashing (docs/03 §8, docs/08 §4).

Issues are {code, severity, path, message}. severity="blocking" can never be waived;
"warning" may be overridden by a reviewer with a reason.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from ..config import ROOT
from ..grading.engine import CHECKERS_FOR_RESPONSE, MANUAL_ONLY, grade
from .richtext import is_empty, iter_asset_ids, iter_latex, latex_issues, normalize_for_dedup, to_plain_text

SCHEMA_PATH = ROOT / "content-schema" / "v1" / "problem.schema.json"
NORMALIZER_VERSION = "math-normalizer-v1"
SUPPORTED_MAJOR = 1


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(Path(SCHEMA_PATH).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def issue(code: str, path: str, message: str, severity: str = "blocking") -> dict:
    return {"code": code, "severity": severity, "path": path, "message": message}


def schema_issues(doc: Any) -> list[dict]:
    out = []
    for err in sorted(_validator().iter_errors(doc), key=lambda e: list(e.absolute_path)):
        path = "/" + "/".join(str(p) for p in err.absolute_path)
        out.append(issue("SCHEMA_VIOLATION", path, err.message[:300]))
    return out


def _dec(s: str) -> Decimal:
    return Decimal(str(s))


def preflight(doc: dict, known_assets: set[str] | None = None, run_golden: bool = True) -> list[dict]:
    """Full content check. Returns issues; any blocking issue prevents submit-for-review/publish."""
    issues = schema_issues(doc)
    if issues:
        return issues  # semantic checks assume structural validity
    rev = doc["revision"]
    asset_ids = {a["asset_id"] for a in doc.get("assets", [])} | (known_assets or set())

    def check_rt(rt: dict, path: str) -> None:
        for latex in iter_latex(rt):
            for msg in latex_issues(latex):
                issues.append(issue("LATEX_RENDER_FATAL", path, f"{msg}: {latex[:60]}"))
        for aid in iter_asset_ids(rt):
            if aid not in asset_ids:
                issues.append(issue("ASSET_MISSING", path, f"asset {aid} not found"))
        for i, block in enumerate(rt.get("blocks", [])):
            if block.get("type") == "display_math" and not block.get("alt_text"):
                issues.append(issue("MISSING_ALT", f"{path}/blocks/{i}", "display math has no alt_text", "warning"))
            if block.get("type") == "image" and not block.get("alt", "").strip():
                issues.append(issue("MISSING_ALT", f"{path}/blocks/{i}", "image has no alt text", "warning"))

    check_rt(rev["shared_statement"], "/revision/shared_statement")
    shared_empty = is_empty(rev["shared_statement"])

    parts = rev["parts"]
    orders = [p["display_order"] for p in parts]
    keys = [p["part_key"] for p in parts]
    if len(set(orders)) != len(orders):
        issues.append(issue("DUPLICATE_DISPLAY_ORDER", "/revision/parts", "display_order must be unique"))
    if len(set(keys)) != len(keys):
        issues.append(issue("DUPLICATE_PART_KEY", "/revision/parts", "part_key must be unique"))
    lids = [p.get("logical_part_id") for p in parts if p.get("logical_part_id")]
    if len(set(lids)) != len(lids):
        issues.append(issue("DUPLICATE_LOGICAL_PART", "/revision/parts", "logical_part_id must be unique"))

    any_content = not shared_empty
    for idx, part in enumerate(parts):
        pp = f"/revision/parts/{idx}"
        check_rt(part["prompt"], f"{pp}/prompt")
        if is_empty(part["prompt"]):
            if shared_empty:
                issues.append(issue("PART_EMPTY", f"{pp}/prompt", "part has no visible content"))
        else:
            any_content = True
        max_score = _dec(part["max_score"])
        if max_score <= 0:
            issues.append(issue("MAX_SCORE_NOT_POSITIVE", f"{pp}/max_score", "max_score must be > 0"))
        rtype = part["response_type"]
        spec = part["answer_spec"]
        mode = spec["grading_mode"]
        ctype = spec["checker_type"]
        rubric = part.get("rubric")

        if rubric:
            total = sum(_dec(c["max_points"]) for c in rubric["criteria"])
            if total != max_score:
                issues.append(issue("RUBRIC_SUM_MISMATCH", f"{pp}/rubric", f"rubric total {total} ≠ max_score {max_score}"))
            ids = [c["id"] for c in rubric["criteria"]]
            if len(set(ids)) != len(ids):
                issues.append(issue("RUBRIC_DUPLICATE_ID", f"{pp}/rubric", "criterion ids must be unique"))

        if rtype in ("single_choice", "multiple_choice"):
            opts = part.get("options") or []
            oids = [o["id"] for o in opts]
            if len(opts) < 2:
                issues.append(issue("CHOICE_OPTIONS_MISSING", f"{pp}/options", "choice parts need ≥2 options"))
            if len(set(oids)) != len(oids):
                issues.append(issue("CHOICE_DUPLICATE_ID", f"{pp}/options", "option ids must be unique"))
            for j, o in enumerate(opts):
                check_rt(o["content"], f"{pp}/options/{j}")
            exp = spec.get("expected")
            exp_set = set(exp) if isinstance(exp, list) else {exp}
            if not exp_set or not exp_set <= set(oids):
                issues.append(issue("CHOICE_EXPECTED_INVALID", f"{pp}/answer_spec/expected", "expected option(s) not among options"))
            if rtype == "single_choice" and isinstance(exp, list):
                issues.append(issue("CHOICE_EXPECTED_INVALID", f"{pp}/answer_spec/expected", "single choice expects one id"))

        if mode in ("automatic", "hybrid"):
            if rtype in MANUAL_ONLY:
                issues.append(issue("AUTO_GRADING_UNSUPPORTED", f"{pp}/answer_spec", f"{rtype} cannot be auto-graded in P0; use manual"))
            elif ctype not in CHECKERS_FOR_RESPONSE.get(rtype, set()):
                issues.append(issue("CHECKER_MISMATCH", f"{pp}/answer_spec/checker_type", f"{ctype} invalid for {rtype}"))
            elif "expected" not in spec and "canonical_expr" not in spec:
                issues.append(issue("ANSWER_MISSING", f"{pp}/answer_spec", "automatic grading needs an expected answer"))
            else:
                if rtype == "expression":
                    _check_assumptions(spec, pp, issues)
                if run_golden and not any(i["severity"] == "blocking" and i["path"].startswith(pp) for i in issues):
                    _golden(part, pp, issues)
        else:  # manual / practice_only
            if mode == "manual" and not rubric:
                issues.append(issue("RUBRIC_MISSING", f"{pp}/rubric", "manual grading requires a rubric"))

        sols = part.get("solutions") or []
        if not sols:
            issues.append(issue("NO_SOLUTION", f"{pp}/solutions", "part has no worked solution", "warning"))
        for j, s in enumerate(sols):
            if s.get("review_state") not in ("reviewed", "verified"):
                issues.append(issue("SOLUTION_UNREVIEWED", f"{pp}/solutions/{j}", "solution not yet reviewed", "warning"))
            for k, step in enumerate(s["steps"]):
                for msg in latex_issues(step):
                    issues.append(issue("LATEX_RENDER_FATAL", f"{pp}/solutions/{j}/steps/{k}", msg))

        steps = part.get("reasoning_steps") or []
        if steps:
            total = sum(_dec(s["max_points"]) for s in steps)
            if total != max_score:
                issues.append(issue("STEP_POINTS_MISMATCH", f"{pp}/reasoning_steps", f"step points {total} ≠ max_score {max_score}"))
            sorders = [s["order"] for s in steps]
            skeys = [s["semantic_key"] for s in steps]
            if len(set(sorders)) != len(sorders) or len(set(skeys)) != len(skeys):
                issues.append(issue("STEP_DUPLICATE", f"{pp}/reasoning_steps", "step order/semantic_key must be unique"))
            for k, s in enumerate(steps):
                for msg in latex_issues(s["reference_latex"]):
                    issues.append(issue("LATEX_RENDER_FATAL", f"{pp}/reasoning_steps/{k}", msg))

    if not any_content:
        issues.append(issue("STATEMENT_EMPTY", "/revision", "problem has no visible content"))

    md = rev["content_metadata"]
    if "platform_difficulty" not in md:
        issues.append(issue("NO_DIFFICULTY", "/revision/content_metadata", "no platform difficulty", "warning"))
    if not md.get("curriculum_mappings"):
        issues.append(issue("NO_KNOWLEDGE", "/revision/content_metadata", "no knowledge mapping", "warning"))
    if md.get("verified_exam") and not (md.get("verified_by") and md.get("verification_ref")):
        issues.append(issue("EXAM_UNVERIFIED", "/revision/content_metadata", "verified_exam requires verified_by + verification_ref"))
    return issues


def _check_assumptions(spec: dict, pp: str, issues: list) -> None:
    from ..grading.mathparse import MathInputError, parse

    src = spec.get("canonical_expr") or spec.get("expected")
    declared = set(spec.get("assumptions") or {}) | set(spec.get("variables") or [])
    try:
        _, used = parse(str(src), declared, allow_unknown=True)
    except MathInputError as e:
        issues.append(issue("ANSWER_UNPARSABLE", f"{pp}/answer_spec", e.message))
        return
    missing = used - declared
    if missing:
        issues.append(issue("ASSUMPTIONS_INCOMPLETE", f"{pp}/answer_spec/assumptions",
                            f"declare domain assumptions for: {', '.join(sorted(missing))}"))


def _golden(part: dict, pp: str, issues: list) -> None:
    """The expected answer must grade as accepted against itself, plus any declared golden cases."""
    spec = part["answer_spec"]
    ms = _dec(part["max_score"])
    oids = {o["id"] for o in part.get("options") or []}
    exp = spec.get("expected", spec.get("canonical_expr"))
    self_input = ",".join(exp) if isinstance(exp, list) else str(exp)
    cases = [{"input": self_input, "expect": "accepted"}] + list(spec.get("golden_cases") or [])
    for case in cases:
        r = grade(part["response_type"], spec["grading_mode"], spec["checker_type"], spec, case["input"], ms, oids)
        if r.status != case["expect"]:
            issues.append(issue("GOLDEN_CASE_FAILED", f"{pp}/answer_spec",
                                f"input {case['input']!r}: expected {case['expect']}, got {r.status} ({r.result_code})"))


# ─────────────────────────── hashing ───────────────────────────
def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(s: str | bytes) -> str:
    return hashlib.sha256(s.encode("utf-8") if isinstance(s, str) else s).hexdigest()


_PART_HASH_FIELDS = ("part_key", "display_order", "response_type", "max_score", "prompt", "options",
                     "answer_spec", "rubric", "solutions", "reasoning_steps")


def content_hash(doc: dict) -> str:
    """Hash of the semantic content of a revision (ids, statuses and provenance excluded)."""
    rev = doc["revision"]
    payload = {
        "locale": rev["locale"],
        "title": rev["title"],
        "shared_statement": rev["shared_statement"],
        "parts": [{k: p.get(k) for k in _PART_HASH_FIELDS} for p in sorted(rev["parts"], key=lambda p: p["display_order"])],
        "assets": sorted(a["sha256"] for a in doc.get("assets", [])),
    }
    return sha256_text(canonical_json(payload))


def statement_fingerprint(doc: dict) -> str:
    """Text used for L1/L2 duplicate signals: statement + part prompts (no answers, no ids)."""
    rev = doc["revision"]
    texts = [to_plain_text(rev["shared_statement"])]
    for p in sorted(rev["parts"], key=lambda p: p["display_order"]):
        texts.append(to_plain_text(p["prompt"]))
    return normalize_for_dedup("|".join(texts))


def schema_major(doc: dict) -> int | None:
    try:
        return int(str(doc.get("schema_version", "")).split(".")[0])
    except ValueError:
        return None
