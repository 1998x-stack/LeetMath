"""Deterministic checkers (docs/06 §2 matrix). Pure functions; heavy ones run inside the sandbox.

Status vocabulary: accepted / rejected / partial are mathematical verdicts. invalid_response is a
format problem, pending_review means "could not decide" and is *never* reported as wrong.
"""
from __future__ import annotations

import json
import math
import random
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any

import sympy as sp

from .mathparse import MathInputError, make_symbols, parse, to_sympy

GRADER_VERSION = "1.0.0"


@dataclass
class GradeResult:
    status: str
    score: str | None
    max_score: str
    result_code: str
    message: str
    details: dict = field(default_factory=dict)
    grader_name: str = "leetmath-deterministic"
    grader_version: str = GRADER_VERSION

    def to_dict(self) -> dict:
        return asdict(self)


def _q(d: Decimal) -> str:
    return str(d.quantize(Decimal("0.01")))


def accepted(max_score: Decimal, code="EQUIVALENT", msg="答案正确", **details) -> GradeResult:
    return GradeResult("accepted", _q(max_score), _q(max_score), code, msg, details)


def rejected(max_score: Decimal, code="NOT_EQUIVALENT", msg="答案与标准答案不等价", **details) -> GradeResult:
    return GradeResult("rejected", _q(Decimal(0)), _q(max_score), code, msg, details)


def invalid(max_score: Decimal, code="INVALID_MATH_INPUT", msg="无法解析输入格式", **details) -> GradeResult:
    return GradeResult("invalid_response", None, _q(max_score), code, msg, details)


def pending(max_score: Decimal, code="NEEDS_REVIEW", msg="无法自动判定，已转人工复核", **details) -> GradeResult:
    return GradeResult("pending_review", None, _q(max_score), code, msg, details)


# ─────────────────────────── choices ───────────────────────────
def _parse_choice_input(raw: str) -> list[str]:
    raw = raw.strip()
    if raw.startswith("["):
        try:
            val = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return [str(v).strip() for v in val] if isinstance(val, list) else []
    return [p for p in re.split(r"[\s,，、;；]+", raw) if p]


def check_single_choice(spec: dict, raw: str, max_score: Decimal, option_ids: set[str]) -> GradeResult:
    sel = _parse_choice_input(raw)
    if len(sel) != 1 or (option_ids and sel[0] not in option_ids):
        return invalid(max_score, "INVALID_CHOICE", "请选择且仅选择一个有效选项")
    return accepted(max_score, "CORRECT_OPTION") if sel[0] == spec["expected"] else rejected(max_score, "WRONG_OPTION", "选项不正确")


def check_multiple_choice(spec: dict, raw: str, max_score: Decimal, option_ids: set[str]) -> GradeResult:
    sel = set(_parse_choice_input(raw))
    if not sel or (option_ids and not sel <= option_ids):
        return invalid(max_score, "INVALID_CHOICE", "请选择有效选项")
    correct = set(spec["expected"])
    if sel == correct:
        return accepted(max_score, "CORRECT_SET")
    if spec.get("partial_credit") == "proportional" and sel < correct:
        score = (max_score * len(sel) / len(correct)).quantize(Decimal("0.01"))
        return GradeResult("partial", _q(score), _q(max_score), "PARTIAL_SUBSET", "少选：部分得分", {})
    return rejected(max_score, "WRONG_SET", "选项集合不正确")


# ─────────────────────────── numbers ───────────────────────────
_INT_RE = re.compile(r"^[+-]?\d+$")
_FRAC_LATEX = re.compile(r"^([+-]?)\\d?frac\{\s*([+-]?\d+)\s*\}\{\s*([+-]?\d+)\s*\}$")


def parse_rational(raw: str) -> Fraction:
    s = raw.strip().replace(" ", "").replace("−", "-")
    m = _FRAC_LATEX.match(s)
    if m:
        sign, a, b = m.groups()
        s = f"{sign}{a}/{b}"
    if "/" in s:
        a, b = s.split("/", 1)
        if not _INT_RE.match(a) or not _INT_RE.match(b) or len(a) > 60 or len(b) > 60:
            raise MathInputError("INVALID_MATH_INPUT", "not a fraction")
        if int(b) == 0:
            raise MathInputError("INVALID_MATH_INPUT", "denominator is zero")
        return Fraction(int(a), int(b))
    try:
        d = Decimal(s)
    except InvalidOperation as e:
        raise MathInputError("INVALID_MATH_INPUT", "not a number") from e
    if not d.is_finite():
        raise MathInputError("INVALID_MATH_INPUT", "not finite")
    if abs(d.adjusted()) > 60 or len(s) > 80:  # bound size: no million-digit integers outside the sandbox
        raise MathInputError("INVALID_MATH_INPUT", "number out of range")
    return Fraction(d)


def check_integer(spec: dict, raw: str, max_score: Decimal) -> GradeResult:
    s = raw.strip().replace(" ", "")
    if len(s) > 60 or not _INT_RE.match(s):
        return invalid(max_score, "NOT_AN_INTEGER", "请输入整数")
    return accepted(max_score) if int(s) == int(spec["expected"]) else rejected(max_score)


def check_rational(spec: dict, raw: str, max_score: Decimal) -> GradeResult:
    try:
        got = parse_rational(raw)
    except MathInputError as e:
        return invalid(max_score, e.code, "请输入整数、分数或有限小数")
    return accepted(max_score) if got == parse_rational(str(spec["expected"])) else rejected(max_score)


def check_decimal(spec: dict, raw: str, max_score: Decimal) -> GradeResult:
    try:
        got = parse_rational(raw)
    except MathInputError as e:
        return invalid(max_score, e.code, "请输入数值")
    exp = parse_rational(str(spec["expected"]))
    tol = spec.get("tolerance") or {}
    abs_tol = Fraction(Decimal(tol["abs"])) if tol.get("abs") else Fraction(0)
    rel_tol = Fraction(Decimal(tol["rel"])) if tol.get("rel") else Fraction(0)
    allowed = max(abs_tol, rel_tol * abs(exp))
    diff = abs(got - exp)
    if diff <= allowed:
        return accepted(max_score, "WITHIN_TOLERANCE" if allowed else "EQUIVALENT", tolerance=str(float(allowed)))
    return rejected(max_score, "OUT_OF_TOLERANCE" if allowed else "NOT_EQUIVALENT")


# ─────────────────────────── symbolic expressions ───────────────────────────
_SAMPLES = {
    "positive": [Fraction(1, 7), Fraction(1, 2), Fraction(1), Fraction(3, 2), Fraction(2), Fraction(27, 10), Fraction(5), Fraction(73, 10)],
    "nonnegative": [Fraction(0), Fraction(1, 3), Fraction(1), Fraction(5, 2), Fraction(4)],
    "negative": [Fraction(-1, 3), Fraction(-1), Fraction(-5, 2), Fraction(-4)],
    "nonzero": [Fraction(-3), Fraction(-1, 2), Fraction(1, 3), Fraction(1), Fraction(5, 2)],
    "integer": [Fraction(-3), Fraction(-1), Fraction(0), Fraction(1), Fraction(2), Fraction(5)],
    "positive_integer": [Fraction(1), Fraction(2), Fraction(3), Fraction(7)],
    "real": [Fraction(-31, 10), Fraction(-1), Fraction(0), Fraction(1, 2), Fraction(1), Fraction(27, 10), Fraction(4)],
}


def _satisfies(kind: str, v: sp.Expr) -> bool:
    if not v.is_real:
        return False
    return {
        "positive": v > 0, "negative": v < 0, "nonnegative": v >= 0, "nonzero": v != 0,
        "integer": v.is_integer, "positive_integer": bool(v.is_integer and v > 0), "real": True,
    }.get(kind, True)


def _num(e: sp.Expr, subs: dict) -> complex | None:
    try:
        v = complex(sp.N(e.subs(subs), 30))
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
    if math.isnan(v.real) or math.isnan(v.imag) or math.isinf(v.real) or math.isinf(v.imag):
        return None
    return v


def _defined(constraints: list[tuple[str, sp.Expr]], subs: dict) -> bool:
    for kind, e in constraints:
        v = _num(e, subs)
        if v is None or abs(v.imag) > 1e-12:
            return False
        r = v.real
        if kind == "nonzero" and abs(r) < 1e-12:
            return False
        if kind == "positive" and r <= 1e-15:
            return False
        if kind == "nonneg" and r < -1e-15:
            return False
    return True


def _singular_points(constraints, symbols: dict[str, sp.Symbol], base: dict) -> list[dict]:
    """Points where a constraint expression hits its boundary (zeros of denominators etc.)."""
    pts: list[dict] = []
    for _kind, e in constraints:
        free = [s for s in e.free_symbols if s in symbols.values()]
        for sym in free[:2]:
            others = {k: v for k, v in base.items() if k != sym}
            try:
                sol = sp.solveset(sp.Eq(e.subs(others), 0), sym, domain=sp.S.Reals)
            except Exception:  # noqa: BLE001 — solver limitations are non-fatal
                continue
            cands: list[sp.Expr] = []
            if isinstance(sol, sp.FiniteSet):
                cands = list(sol)[:6]
            elif isinstance(sol, sp.Union):
                for a in sol.args:
                    if isinstance(a, sp.FiniteSet):
                        cands += list(a)[:3]
                    elif isinstance(a, sp.ImageSet):
                        lam = a.lamda
                        cands += [lam(n) for n in (-1, 0, 1)]
            elif isinstance(sol, sp.ImageSet):
                cands = [sol.lamda(n) for n in (-1, 0, 1)]
            for c in cands:
                if c.free_symbols:
                    continue
                p = dict(base)
                p[sym] = c
                pts.append(p)
    return pts


def _sample_points(symbols: dict[str, sp.Symbol], assumptions: dict[str, str], n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    names = sorted(symbols)
    pts = []
    for i in range(n):
        p = {}
        for name in names:
            pool = _SAMPLES.get(assumptions.get(name, "real"), _SAMPLES["real"])
            v = pool[(i + rng.randrange(len(pool))) % len(pool)]
            p[symbols[name]] = sp.Rational(v.numerator, v.denominator)
        pts.append(p)
    return pts


def _equal_symbolic(diff: sp.Expr) -> bool | None:
    try:
        for f in (lambda d: d, sp.simplify, lambda d: sp.simplify(sp.expand_log(d)), sp.trigsimp,
                  lambda d: sp.simplify(sp.expand(sp.powsimp(d)))):
            r = f(diff)
            if r == 0:
                return True
            if r.is_number and r.is_zero is False:
                return False
    except Exception:  # noqa: BLE001
        return None
    return None


def check_expression(spec: dict, raw: str, max_score: Decimal) -> GradeResult:
    assumptions: dict[str, str] = dict(spec.get("assumptions") or {})
    variables = set(assumptions) | set(spec.get("variables") or [])
    for v in variables:
        assumptions.setdefault(v, "real")
    symbols = make_symbols(assumptions)
    expected_src = spec.get("canonical_expr") or spec.get("expected")
    try:
        exp_ast, _ = parse(str(expected_src), variables)
        E = to_sympy(exp_ast, symbols)
    except MathInputError as e:
        return GradeResult("engine_error", None, _q(max_score), "BAD_ANSWER_SPEC", f"standard answer unparsable: {e.message}")
    try:
        resp_ast, _ = parse(raw, variables)
        R = to_sympy(resp_ast, symbols)
    except MathInputError as e:
        return invalid(max_score, e.code, f"格式解析失败：{e.message}")

    eq = _equal_symbolic(sp.simplify(R.expr - E.expr))
    samples = _sample_points(symbols, assumptions, 14, seed=7)
    probes = samples + _singular_points(R.constraints + E.constraints, symbols, samples[0] if samples else {})
    domain_mismatch = None
    counterexample = None
    for p in probes:
        if not all(_satisfies(assumptions.get(str(s), "real"), v) for s, v in p.items()):
            continue
        dR, dE = _defined(R.constraints, p), _defined(E.constraints, p)
        if dR != dE and domain_mismatch is None:
            domain_mismatch = {str(k): str(v) for k, v in p.items()}
        if dR and dE and counterexample is None and eq is not True:
            a, b = _num(R.expr, p), _num(E.expr, p)
            if a is not None and b is not None and abs(a - b) > 1e-9 * (1 + abs(b)):
                counterexample = {str(k): str(v) for k, v in p.items()}
    details = {"assumptions": assumptions, "parser": "leetmath-rd-1"}
    if eq is True and domain_mismatch is None:
        return accepted(max_score, "EQUIVALENT", "答案正确（在题设条件下符号等价）", **details)
    if counterexample is not None:
        return rejected(max_score, "COUNTEREXAMPLE", "答案与标准答案不等价", **details)
    if eq is False:
        return rejected(max_score, "NOT_EQUIVALENT", "答案与标准答案不等价", **details)
    if domain_mismatch is not None:
        return pending(max_score, "DOMAIN_MISMATCH", "表达式定义域与标准答案不同，已转人工复核", **details)
    return pending(max_score, "INCONCLUSIVE", "无法自动证明等价，已转人工复核", **details)


# ─────────────────────────── intervals & finite sets ───────────────────────────
_EMPTY = {"∅", "\\emptyset", "\\varnothing", "emptyset", "{}", "空集"}
_REALS = {"R", "\\mathbb{R}", "ℝ", "(-oo,oo)", "(-∞,+∞)", "(-\\infty,+\\infty)"}


def _split_top(s: str, seps: tuple[str, ...]) -> list[str]:
    parts, depth, cur, i = [], 0, "", 0
    while i < len(s):
        ch = s[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        matched = next((sep for sep in seps if depth == 0 and s.startswith(sep, i)), None)
        if matched:
            parts.append(cur)
            cur = ""
            i += len(matched)
            continue
        cur += ch
        i += 1
    parts.append(cur)
    return [p.strip() for p in parts]


def _parse_interval_union(raw: str, variables: set[str], symbols) -> list[tuple]:
    s = raw.strip().replace(" ", "").replace("\\left", "").replace("\\right", "")
    s = re.sub(r"^[A-Za-z]\\in|^[A-Za-z]∈", "", s)
    if s in _EMPTY:
        return []
    if s in _REALS:
        return [(-sp.oo, sp.oo, True, True)]
    pieces = _split_top(s, ("\\cup", "∪", "U"))
    out = []
    for piece in pieces:
        if len(piece) < 5 or piece[0] not in "([" or piece[-1] not in ")]":
            raise MathInputError("INVALID_MATH_INPUT", "区间格式应为 (a,b] 等")
        inner = _split_top(piece[1:-1], (",",))
        if len(inner) != 2:
            raise MathInputError("INVALID_MATH_INPUT", "区间需要两个端点")
        ends = []
        for t in inner:
            t = t.replace("+", "", 1) if t.startswith("+") else t
            ends.append(to_sympy(parse(t, variables)[0], symbols).expr)
        lo, hi = ends
        lo_open, hi_open = piece[0] == "(", piece[-1] == ")"
        if (lo in (sp.oo, -sp.oo) and not lo_open) or (hi in (sp.oo, -sp.oo) and not hi_open):
            raise MathInputError("INVALID_MATH_INPUT", "无穷端点必须为开")
        out.append((lo, hi, lo_open, hi_open))
    return out


def _same(a: sp.Expr, b: sp.Expr) -> bool:
    if a in (sp.oo, -sp.oo) or b in (sp.oo, -sp.oo):
        return a == b
    return _equal_symbolic(sp.simplify(a - b)) is True


def _match_multiset(xs: list, ys: list, eq) -> bool:
    if len(xs) != len(ys):
        return False
    used = [False] * len(ys)
    for x in xs:
        for j, y in enumerate(ys):
            if not used[j] and eq(x, y):
                used[j] = True
                break
        else:
            return False
    return True


def check_interval(spec: dict, raw: str, max_score: Decimal) -> GradeResult:
    assumptions = dict(spec.get("assumptions") or {})
    variables = set(assumptions) | set(spec.get("variables") or [])
    symbols = make_symbols({v: assumptions.get(v, "real") for v in variables})
    exp = _parse_interval_union(str(spec["expected"]), variables, symbols)
    try:
        got = _parse_interval_union(raw, variables, symbols)
    except MathInputError as e:
        return invalid(max_score, e.code, e.message)
    if all(not x.free_symbols for iv in got + exp for x in iv[:2]):
        to_set = lambda ivs: sp.Union(*[sp.Interval(lo, hi, lo_o, hi_o) for lo, hi, lo_o, hi_o in ivs]) if ivs else sp.S.EmptySet  # noqa: E731
        A, B = to_set(got), to_set(exp)
        if A == B or (A.symmetric_difference(B)) == sp.S.EmptySet:
            return accepted(max_score)
        return rejected(max_score, "INTERVAL_MISMATCH", "区间不正确（注意端点与开闭）")
    ok = _match_multiset(got, exp, lambda x, y: x[2:] == y[2:] and _same(x[0], y[0]) and _same(x[1], y[1]))
    return accepted(max_score) if ok else rejected(max_score, "INTERVAL_MISMATCH", "区间不正确（注意端点与开闭）")


def check_finite_set(spec: dict, raw: str, max_score: Decimal) -> GradeResult:
    assumptions = dict(spec.get("assumptions") or {})
    variables = set(assumptions) | set(spec.get("variables") or [])
    symbols = make_symbols({v: assumptions.get(v, "real") for v in variables})
    solve_var = spec.get("solve_for")

    def elems(s: str) -> list[sp.Expr]:
        s = s.strip()
        if s in _EMPTY:
            return []
        if s.startswith("\\{") and s.endswith("\\}"):
            s = s[2:-2]
        elif s.startswith("{") and s.endswith("}"):
            s = s[1:-1]
        items = [p for p in _split_top(s.replace("或", ",").replace("，", ","), (",", ";")) if p]
        out = []
        for it in items:
            if solve_var:
                it = re.sub(rf"^{re.escape(solve_var)}\s*=", "", it)
            out.append(to_sympy(parse(it, variables - ({solve_var} if solve_var else set()))[0], symbols).expr)
        return out

    exp = elems(str(spec["expected"]))
    try:
        got = elems(raw)
    except MathInputError as e:
        return invalid(max_score, e.code, e.message)
    if len({sp.srepr(sp.nsimplify(g)) for g in got}) != len(got) and not spec.get("allow_repeats"):
        got = list({sp.srepr(g): g for g in got}.values())
    if _match_multiset(got, exp, _same):
        return accepted(max_score)
    missing = len(exp) - sum(1 for e in exp if any(_same(e, g) for g in got))
    extra = len(got) - sum(1 for g in got if any(_same(e, g) for e in exp))
    return rejected(max_score, "SET_MISMATCH", "解集不正确", missing=missing, extra=extra)


# ─────────────────────────── dispatcher ───────────────────────────
SANDBOXED = {"symbolic_equivalence", "interval_set", "finite_set"}


def run_checker(checker_type: str, spec: dict, raw: str, max_score: Decimal, option_ids: set[str] | None = None) -> GradeResult:
    option_ids = option_ids or set()
    if checker_type == "choice_exact":
        return check_single_choice(spec, raw, max_score, option_ids)
    if checker_type == "choice_set":
        return check_multiple_choice(spec, raw, max_score, option_ids)
    if checker_type == "integer_exact":
        return check_integer(spec, raw, max_score)
    if checker_type == "rational_exact":
        return check_rational(spec, raw, max_score)
    if checker_type == "decimal_tolerance":
        return check_decimal(spec, raw, max_score)
    if checker_type == "symbolic_equivalence":
        return check_expression(spec, raw, max_score)
    if checker_type == "interval_set":
        return check_interval(spec, raw, max_score)
    if checker_type == "finite_set":
        return check_finite_set(spec, raw, max_score)
    return pending(max_score, "MANUAL_GRADING", "此题型需人工批改")


def _sandbox_entry(payload: dict) -> dict[str, Any]:
    r = run_checker(payload["checker_type"], payload["spec"], payload["raw"], Decimal(payload["max_score"]), set(payload["option_ids"]))
    return r.to_dict()
