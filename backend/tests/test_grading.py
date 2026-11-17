"""Grader golden cases: correct / wrong / boundary per type (docs/06 §2, §8)."""
from decimal import Decimal as D

import pytest

from leetmath.grading import sandbox
from leetmath.grading.engine import grade

R = {"x": "real"}
P = {"x": "positive"}
PA = {"x": "positive", "a": "real"}

EXPR = [
    # (expected, input, assumptions, status)
    ("ln(x)+1-a", "ln(x)-(a-1)", PA, "accepted"),                      # §8.1
    ("ln(x)+1-a", "\\ln x + 1 - a", PA, "accepted"),
    ("ln(x)+1-a", "ln(abs(x))+1-a", PA, "accepted"),                   # §8.2 valid only because x>0
    ("ln(x)+1-a", "ln|x|+1-a", PA, "accepted"),
    ("1", "x/x", R, "pending_review"),                                 # §8.3 domain differs at x=0
    ("x", "sqrt(x^2)", R, "rejected"),                                 # §8.4
    ("x", "sqrt(x^2)", P, "accepted"),
    ("abs(x)", "sqrt(x^2)", R, "accepted"),
    ("tan(x)", "sin(x)/cos(x)", R, "accepted"),                        # §8.5 same poles
    ("1", "(x-1)/(x-1)", R, "pending_review"),                         # §8.6
    ("x+1", "(x^2-1)/(x-1)", R, "pending_review"),
    ("x+1", "(x^2-1)/(x-1)", P, "pending_review"),                     # x=1 is still positive
    ("2*x", "x+x", R, "accepted"),
    ("x^2-1", "(x-1)(x+1)", R, "accepted"),
    ("x^2-1", "(x-1)^2", R, "rejected"),
    ("(x+1)^2", "x^2+2x+1", R, "accepted"),
    ("sin(2*x)", "2sin(x)cos(x)", R, "accepted"),
    ("cos(2*x)", "1-2sin^2 x", R, "accepted"),
    ("cos(2*x)", "2cos(x)^2+1", R, "rejected"),
    ("exp(x)", "e^x", R, "accepted"),
    ("e^(a-1)", "\\mathrm{e}^{a-1}", {"a": "real"}, "accepted"),
    ("e^(a-1)", "e^a/e", {"a": "real"}, "accepted"),
    ("ln(x^2)", "2ln(x)", P, "accepted"),
    ("ln(x^2)", "2ln(x)", {"x": "nonzero"}, "pending_review"),        # differs for x<0 → never auto-accept
    ("1/(x+1)", "\\frac{1}{x+1}", P, "accepted"),
    ("1/(x+1)", "\\dfrac{1}{x+1}", P, "accepted"),
    ("sqrt(2)/2", "1/sqrt(2)", {}, "accepted"),
    ("sqrt(6)/3", "\\frac{\\sqrt{6}}{3}", {}, "accepted"),
    ("sqrt(6)/3", "sqrt(2/3)", {}, "accepted"),
    ("12*sqrt(2)/7", "12/7*sqrt(2)", {}, "accepted"),
    ("12*sqrt(2)/7", "12/7", {}, "rejected"),
    ("24/7", "3.4285714", {}, "rejected"),                              # exact mode: decimals are exact rationals
    ("1/3", "0.333", {}, "rejected"),                                   # §8.7 exact mode
    ("2*pi", "2\\pi", {}, "accepted"),
    ("2*pi", "6.2832", {}, "rejected"),
    ("2*sin(x+pi/3)", "sin(x)+sqrt(3)cos(x)", R, "accepted"),
    ("2*sin(x+pi/3)", "2sin(x+pi/6)", R, "rejected"),
    ("4n-1", "3+4(n-1)", {"n": "positive_integer"}, "accepted"),
    ("4n-1", "4n+3", {"n": "positive_integer"}, "rejected"),
    ("x*ln(x)-a*x", "x\\ln x-ax", PA, "accepted"),
    ("x*ln(x)-a*x", "x(ln x - a)", PA, "accepted"),
    ("3x^2-3", "3(x-1)(x+1)", R, "accepted"),
    ("9x-16", "y=9x-16", R, "accepted"),
    ("9x-16", "f(x)=9(x-2)+2", R, "accepted"),
    ("-e^(a-1)", "-\\mathrm{e}^{a-1}", {"a": "real"}, "accepted"),
    ("x^3", "x*x*x", R, "accepted"),
    ("x^(1/2)", "sqrt(x)", P, "accepted"),
    ("abs(x-1)", "|x-1|", R, "accepted"),
    ("abs(x-1)", "x-1", R, "rejected"),
    ("1/x", "x^-1", {"x": "nonzero"}, "accepted"),
    ("2^10", "1024", {}, "accepted"),
    ("5!", "120", {}, "accepted"),
    ("x+y", "y+x", {"x": "real", "y": "real"}, "accepted"),
]

INVALID = [
    "", "   ", "__import__('os').system('id')", "lambda: 1", "x; import os", "9^9^9^9", "10^100000",
    "(" * 60 + "x" + ")" * 60, "x" * 600, "eval(x)", "open('/etc/passwd')", "x +* 2", "sin()", "\\input{x}",
    "\\def\\x{1}", "1/0", "zz", "x = = 1", "$x$", "{{x}", "1000!",
]


@pytest.mark.parametrize("expected,inp,ass,status", EXPR)
def test_expression(expected, inp, ass, status):
    r = grade("expression", "automatic", "symbolic_equivalence", {"expected": expected, "assumptions": ass}, inp, D("3"))
    assert r.status == status, (inp, r.result_code, r.message)
    if status == "accepted":
        assert r.score == "3.00"
    if status in ("pending_review", "invalid_response"):
        assert r.score is None  # never a fake zero


@pytest.mark.parametrize("inp", INVALID)
def test_expression_invalid_never_executes(inp):
    r = grade("expression", "automatic", "symbolic_equivalence", {"expected": "x", "assumptions": R}, inp, D("1"))
    assert r.status == "invalid_response", (inp, r.status, r.result_code)


def test_engine_timeout_is_not_a_math_error(monkeypatch):
    monkeypatch.setattr(sandbox.settings, "grader_timeout_s", 0.001)
    r = sandbox.run_sandboxed({"checker_type": "symbolic_equivalence", "spec": {"expected": "x", "assumptions": R},
                               "raw": "sin(x)^2+cos(x)^2+x-1", "max_score": "3", "option_ids": []}, timeout_s=0.001)
    assert r.status == "pending_review" and r.result_code == "MATH_PARSER_TIMEOUT" and r.score is None


NUMERIC = [
    ("integer", "integer_exact", {"expected": "39"}, "39", "accepted"),
    ("integer", "integer_exact", {"expected": "39"}, "+039", "accepted"),
    ("integer", "integer_exact", {"expected": "-2"}, "-2", "accepted"),
    ("integer", "integer_exact", {"expected": "39"}, "40", "rejected"),
    ("integer", "integer_exact", {"expected": "39"}, "39.0", "invalid_response"),
    ("integer", "integer_exact", {"expected": "39"}, "三十九", "invalid_response"),
    ("rational", "rational_exact", {"expected": "3/10"}, "3/10", "accepted"),
    ("rational", "rational_exact", {"expected": "3/10"}, "6/20", "accepted"),
    ("rational", "rational_exact", {"expected": "3/10"}, "0.3", "accepted"),
    ("rational", "rational_exact", {"expected": "3/10"}, "\\frac{3}{10}", "accepted"),
    ("rational", "rational_exact", {"expected": "3/10"}, "1/3", "rejected"),
    ("rational", "rational_exact", {"expected": "3/10"}, "3/0", "invalid_response"),
    ("rational", "rational_exact", {"expected": "-6/5"}, "-1.2", "accepted"),
    ("decimal", "decimal_tolerance", {"expected": "1/3", "tolerance": {"abs": "0.001"}}, "0.333", "accepted"),  # §8.7
    ("decimal", "decimal_tolerance", {"expected": "1/3", "tolerance": {"abs": "0.0001"}}, "0.333", "rejected"),
    ("decimal", "decimal_tolerance", {"expected": "1/3"}, "0.333", "rejected"),
    ("decimal", "decimal_tolerance", {"expected": "100", "tolerance": {"rel": "0.01"}}, "100.9", "accepted"),
    ("decimal", "decimal_tolerance", {"expected": "100", "tolerance": {"rel": "0.01"}}, "101.1", "rejected"),
    ("decimal", "decimal_tolerance", {"expected": "4"}, "4.00", "accepted"),
    ("decimal", "decimal_tolerance", {"expected": "4"}, "NaN", "invalid_response"),
    ("decimal", "decimal_tolerance", {"expected": "4"}, "1e999999", "invalid_response"),
    ("rational", "rational_exact", {"expected": "1/3"}, "1" * 70 + "/3", "invalid_response"),
]


@pytest.mark.parametrize("rtype,checker,spec,inp,status", NUMERIC)
def test_numeric(rtype, checker, spec, inp, status):
    assert grade(rtype, "automatic", checker, spec, inp, D("2")).status == status


CHOICE_OPTS = {"A", "B", "C", "D"}


@pytest.mark.parametrize("inp,status", [("A", "accepted"), (" A ", "accepted"), ("B", "rejected"), ("A,B", "invalid_response"),
                                        ("E", "invalid_response"), ('["A"]', "accepted")])
def test_single_choice(inp, status):
    assert grade("single_choice", "automatic", "choice_exact", {"expected": "A"}, inp, D("4"), CHOICE_OPTS).status == status


@pytest.mark.parametrize("inp,status,score", [("A,B,D", "accepted", "6.00"), ("D,B,A", "accepted", "6.00"),
                                              ("A,B", "partial", "4.00"), ("A", "partial", "2.00"),
                                              ("A,B,C,D", "rejected", "0.00"), ("C", "rejected", "0.00"),
                                              ("A，B、D", "accepted", "6.00"), ("Q", "invalid_response", None)])
def test_multiple_choice_partial(inp, status, score):
    r = grade("multiple_choice", "automatic", "choice_set", {"expected": ["A", "B", "D"], "partial_credit": "proportional"},
              inp, D("6"), CHOICE_OPTS)
    assert (r.status, r.score) == (status, score)


def test_multiple_choice_default_all_or_nothing():
    r = grade("multiple_choice", "automatic", "choice_set", {"expected": ["A", "B"]}, "A", D("4"), CHOICE_OPTS)
    assert r.status == "rejected"


INTERVALS = [
    ("(1,2]", "(1,2]", {}, "accepted"),
    ("(1,2]", "(1, 2]", {}, "accepted"),
    ("(1,2]", "[1,2]", {}, "rejected"),
    ("(1,2]", "(1,2)", {}, "rejected"),
    ("(-oo,-2)∪[1,+oo)", "(-∞,-2)∪[1,+∞)", {}, "accepted"),
    ("(-oo,-2)∪[1,+oo)", "[1,+∞)∪(-∞,-2)", {}, "accepted"),
    ("(-oo,-2)∪[1,+oo)", "(-\\infty,-2)\\cup[1,+\\infty)", {}, "accepted"),
    ("(-oo,-2)∪[1,+oo)", "(-∞,-2]∪[1,+∞)", {}, "rejected"),
    ("(-oo,-2)∪[1,+oo)", "(-∞,-2)", {}, "rejected"),
    ("[1,4)", "[1,2]∪(1,4)", {}, "accepted"),          # equal as sets
    ("(0, e^(a-1))", "(0,\\mathrm{e}^{a-1})", {"a": "real"}, "accepted"),
    ("(0, e^(a-1))", "(0,e^a)", {"a": "real"}, "rejected"),
    ("∅", "∅", {}, "accepted"),
    ("R", "(-∞,+∞)", {}, "accepted"),
    ("(1,2]", "[-∞,2]", {}, "invalid_response"),
    ("(1,2]", "1<x<=2", {}, "invalid_response"),
]


@pytest.mark.parametrize("expected,inp,ass,status", INTERVALS)
def test_interval(expected, inp, ass, status):
    r = grade("interval", "automatic", "interval_set", {"expected": expected, "assumptions": ass}, inp, D("4"))
    assert r.status == status, (inp, r.result_code, r.message)


SETS = [
    ("{2,3}", "{3,2}", "accepted"), ("{2,3}", "x=2或x=3", "accepted"), ("{2,3}", "2, 3", "accepted"),
    ("{2,3}", "{2}", "rejected"), ("{4}", "{4,-2}", "rejected"),       # extraneous root
    ("{4}", "{4}", "accepted"), ("{-1,1}", "{1,-1}", "accepted"), ("{-1,1}", "{1,-1,1}", "accepted"),
    ("{1/2}", "{0.5}", "accepted"), ("{sqrt(2)}", "{\\sqrt{2}}", "accepted"), ("∅", "∅", "accepted"),
    ("{2,3}", "{2,", "invalid_response"),
]


@pytest.mark.parametrize("expected,inp,status", SETS)
def test_finite_set(expected, inp, status):
    r = grade("set", "automatic", "finite_set", {"expected": expected, "solve_for": "x"}, inp, D("4"))
    assert r.status == status, (inp, r.result_code)


@pytest.mark.parametrize("rtype,mode,checker", [("proof", "manual", "rubric_manual"), ("derivation", "manual", "rubric_manual"),
                                                ("short_text", "practice_only", "rubric_manual"),
                                                ("proof", "automatic", "symbolic_equivalence")])
def test_manual_types_pending(rtype, mode, checker):
    r = grade(rtype, mode, checker, {"expected": "x"}, "证明如下……", D("6"))
    assert r.status == "pending_review" and r.score is None


def test_empty_response_invalid():
    assert grade("integer", "automatic", "integer_exact", {"expected": "1"}, "  ", D("1")).status == "invalid_response"


def test_case_count_meets_regression_floor():
    total = len(EXPR) + len(INVALID) + len(NUMERIC) + 6 + 8 + 1 + len(INTERVALS) + len(SETS) + 4 + 2
    assert total >= 140  # docs/06 §9 targets 300+ labelled cases before launch; this is the seed set
