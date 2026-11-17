"""Content Contract v1: positive fixtures pass, every negative fixture fails with its expected blocking code (LM-102)."""
import json
from pathlib import Path

import pytest

from leetmath.content.contract import content_hash, preflight, statement_fingerprint
from leetmath.content.richtext import latex_issues

ROOT = Path(__file__).resolve().parents[2]
POS = sorted((ROOT / "fixtures" / "positive").glob("*.json"))
NEG = sorted((ROOT / "fixtures" / "negative").glob("*.json"))


@pytest.mark.parametrize("path", POS + [ROOT / "docs/examples/problem-sh-function-001.json"], ids=lambda p: p.name)
def test_positive_fixtures(path):
    issues = preflight(json.loads(path.read_text("utf-8")))
    assert not [i for i in issues if i["severity"] == "blocking"], issues


@pytest.mark.parametrize("path", NEG, ids=lambda p: p.name)
def test_negative_fixtures(path):
    doc = json.loads(path.read_text("utf-8"))
    expected = doc.pop("_expect_blocking").split("__")[0]
    doc.pop("_note")
    codes = {i["code"] for i in preflight(doc) if i["severity"] == "blocking"}
    assert expected in codes, codes


def test_fixture_counts():
    assert len(POS) >= 13 and len(NEG) >= 15


def test_content_hash_ignores_ids_and_status_but_not_math():
    doc = json.loads(POS[0].read_text("utf-8"))
    h = content_hash(doc)
    d2 = json.loads(json.dumps(doc))
    d2["revision"]["status"] = "published"
    d2["problem"]["slug"] = "other"
    assert content_hash(d2) == h
    d3 = json.loads(json.dumps(doc))
    d3["revision"]["parts"][0]["answer_spec"]["canonical_expr"] = "log(x)-a"
    assert content_hash(d3) != h


def test_fingerprint_distinguishes_gt_and_geq():
    doc = json.loads(POS[0].read_text("utf-8"))
    a = statement_fingerprint(doc)
    d2 = json.loads(json.dumps(doc).replace("x>0", "x\\\\geq 0"))
    assert statement_fingerprint(d2) != a


@pytest.mark.parametrize("latex,ok", [("\\frac{1}{2}", True), ("x^{2}", True), ("\\href{http://a}{b}", False),
                                      ("\\newcommand{\\x}{1}", False), ("\\left( x", False), ("{x", False),
                                      ("\\htmlClass{a}{b}", False), ("\\begin{cases}x\\end{cases}", True)])
def test_latex_safety(latex, ok):
    assert (not latex_issues(latex)) == ok
