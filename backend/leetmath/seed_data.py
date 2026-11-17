"""Original demo content (NOT official Shanghai exam items). Math checked by the author; still requires
human teaching-research review before any real-world use. Covers every P0 response type."""
from __future__ import annotations

import copy
import json

from .config import ROOT
from .services.adapters import text_to_richtext as T

SOURCE = "leetmath-original-demo"
GRANT = "sample-original-internal-review-required"
CUR = {"curriculum_code": "CN-SH-SENIOR-HIGH", "release_code": "DEMO-2026"}

CURRICULUM = {
    "system": {"code": "CN-SH-SENIOR-HIGH", "region": "CN-SH", "grade_band": "senior_high", "label": "上海高中数学（试点目录，非官方）"},
    "release": {"release_code": "DEMO-2026", "label": "演示版 2026", "source_ref": "LeetMath pilot taxonomy — not an official curriculum"},
    "nodes": [
        ("SETS", None, "集合与常用逻辑"),
        ("FUNC", None, "函数"),
        ("FUNC-DOMAIN", "FUNC", "函数的定义域"),
        ("FUNC-PARITY", "FUNC", "函数的奇偶性"),
        ("LOG", "FUNC", "对数与对数函数"),
        ("TRIG", "FUNC", "三角函数"),
        ("DERIVATIVES", None, "导数及其应用"),
        ("DERIV-RULES", "DERIVATIVES", "求导法则"),
        ("DERIV-MONOTONIC", "DERIVATIVES", "导数与单调性、极值最值"),
        ("DERIV-TANGENT", "DERIVATIVES", "导数的几何意义（切线）"),
        ("INEQUALITY", None, "不等式"),
        ("EQUATIONS", None, "方程与解集"),
        ("SEQUENCE", None, "数列"),
        ("ANAG", None, "解析几何"),
        ("ANAG-ELLIPSE", "ANAG", "椭圆的标准方程与性质"),
        ("ANAG-CHORD", "ANAG", "直线与圆锥曲线：弦长与面积"),
        ("GEO3", None, "空间几何"),
        ("PROB", None, "概率"),
        ("STATS", None, "统计"),
    ],
    "edges": [("DERIV-RULES", "DERIV-MONOTONIC", "prerequisite"), ("DERIV-RULES", "DERIV-TANGENT", "prerequisite"),
              ("FUNC-DOMAIN", "LOG", "prerequisite"), ("ANAG-ELLIPSE", "ANAG-CHORD", "prerequisite")],
}

USERS = [
    # username, password, display, roles
    ("admin", "admin-pass-123", "平台管理员", ["admin"]),
    ("editor", "editor-pass-123", "教研编辑 王老师", ["editor"]),
    ("reviewer", "reviewer-pass-123", "数学审校 李老师", ["reviewer"]),
    ("rights", "rights-pass-123", "版权审核 赵", ["rights_reviewer"]),
    ("ops", "ops-pass-123", "题源运营 陈", ["source_manager"]),
    ("auditor", "auditor-pass-123", "审计员", ["auditor"]),
    ("student", "student-pass-123", "学生 小明", ["student"]),
    ("student2", "student-pass-123", "学生 小红", ["student"]),
]


def km(*codes: str, rel: str = "tested") -> list[dict]:
    return [{**CUR, "knowledge_code": c, "relation_type": rel} for c in codes]


def para(*spans) -> dict:
    return {"blocks": [{"type": "paragraph", "spans": list(spans)}]}


def opt(i: str, text: str) -> dict:
    return {"id": i, "content": T(text)}


def sol(*steps: str) -> list[dict]:
    return [{"type": "worked", "review_state": "reviewed", "steps": list(steps)}]


def doc(n: int, slug: str, title: str, statement: dict, parts: list[dict], md: dict) -> dict:
    return {
        "schema_version": "1.0.0",
        "sample_only": True,
        "problem": {"display_id": f"LM-SH-{n:06d}", "slug": slug, "grade_band": "senior_high", "subject": "mathematics"},
        "revision": {"locale": "zh-CN", "title": title, "shared_statement": statement,
                     "content_metadata": {"region_hints": ["CN-SH"], "grade_band": "senior_high", "verified_exam": False,
                                          "solution_visibility": "after_submit", **md},
                     "parts": [{"display_order": i, **p} for i, p in enumerate(parts, start=1)]},
        "source_record_refs": [{"source_code": SOURCE, "external_id": f"demo-{n:03d}", "external_revision": "1",
                                "record_kind": "original_example", "note": "原创演示题，非真实考试题"}],
        "rights_policy_ref": GRANT,
        "assets": [],
        "lineage": [],
    }


def diff(v: int) -> dict:
    return {"platform_difficulty": {"value": v, "origin": "editorial_estimate", "rated_by": "seed", "confidence": "low"}}


def auto(rtype: str, checker: str, score: str, prompt: str, expected, solution: list[str], **spec) -> dict:
    p = {"part_key": spec.pop("key"), "response_type": rtype, "max_score": score, "prompt": T(prompt),
         "answer_spec": {"spec_version": 1, "grading_mode": "automatic", "checker_type": checker, "expected": expected, **spec},
         "solutions": sol(*solution)}
    if "knowledge_codes" in p["answer_spec"]:
        p["knowledge_codes"] = p["answer_spec"].pop("knowledge_codes")
    if "options" in p["answer_spec"]:
        p["options"] = p["answer_spec"].pop("options")
    return p


def problem_001() -> dict:
    """The repository's own example (docs/examples/problem-sh-function-001.json) + reasoning steps."""
    d = json.loads((ROOT / "docs" / "examples" / "problem-sh-function-001.json").read_text("utf-8"))
    d = copy.deepcopy(d)
    d["revision"].pop("status", None)
    d["revision"]["content_metadata"]["curriculum_mappings"] = km("DERIV-RULES", "DERIV-MONOTONIC", "INEQUALITY")
    d["revision"]["content_metadata"]["solution_visibility"] = "after_submit"
    p1, p2, p3 = d["revision"]["parts"]
    p1["knowledge_codes"] = ["DERIV-RULES"]
    p1["answer_spec"]["golden_cases"] = [
        {"input": "ln(x)-(a-1)", "expect": "accepted"},
        {"input": "\\ln x+1-a", "expect": "accepted"},
        {"input": "ln(x)-a", "expect": "rejected"},
        {"input": "ln(x)+1-a+x/x-1", "expect": "accepted"},  # x>0 so x/x is safe
    ]
    p2["knowledge_codes"] = ["DERIV-MONOTONIC"]
    p3["knowledge_codes"] = ["DERIV-MONOTONIC", "INEQUALITY"]
    p1["reasoning_steps"] = [
        {"semantic_key": "product_rule", "order": 1, "recall_cue": "x·ln x 是两个函数之积，第一步该用哪条求导法则？",
         "reference_latex": "(x\\ln x)'=1\\cdot\\ln x+x\\cdot\\frac{1}{x}=\\ln x+1", "explanation": "乘积法则 (uv)'=u'v+uv'。",
         "max_points": "1.00", "criticality": "normal", "knowledge_codes": ["DERIV-RULES"]},
        {"semantic_key": "final_derivative", "order": 2, "recall_cue": "再处理 −ax 这一项，写出完整的 f'(x)。",
         "reference_latex": "f'(x)=\\ln x+1-a", "explanation": "(−ax)'=−a，与上一步相加。",
         "max_points": "2.00", "criticality": "key", "knowledge_codes": ["DERIV-RULES"]},
    ]
    p2["reasoning_steps"] = [
        {"semantic_key": "critical_point", "order": 1, "recall_cue": "单调性的分界点从哪里来？令什么等于 0？",
         "reference_latex": "f'(x)=0\\iff\\ln x=a-1\\iff x=e^{a-1}", "explanation": "x>0 时 ln x 单调，方程有唯一解。",
         "max_points": "2.00", "criticality": "key", "knowledge_codes": ["DERIV-MONOTONIC"]},
        {"semantic_key": "sign_analysis", "order": 2, "recall_cue": "在分界点两侧，f'(x) 的符号分别是什么？",
         "reference_latex": "0<x<e^{a-1}\\Rightarrow f'(x)<0;\\quad x>e^{a-1}\\Rightarrow f'(x)>0",
         "explanation": "f'(x)=ln x−(a−1) 关于 x 递增。", "max_points": "2.00", "criticality": "key",
         "knowledge_codes": ["DERIV-MONOTONIC"]},
        {"semantic_key": "min_value", "order": 3, "recall_cue": "最小值是多少？把分界点代回原函数。",
         "reference_latex": "f(e^{a-1})=e^{a-1}(a-1)-ae^{a-1}=-e^{a-1}", "explanation": "先减后增 ⇒ 在分界点取最小值。",
         "max_points": "1.00", "criticality": "normal", "knowledge_codes": ["DERIV-MONOTONIC"]},
    ]
    p3["reasoning_steps"] = [
        {"semantic_key": "use_minimum", "order": 1, "recall_cue": "要证的不等式右边 −e^{a−1} 看起来像什么？如何借用第二问？",
         "reference_latex": "\\forall x>0:\\ f(x)\\ge f(e^{a-1})", "explanation": "不等式即“函数值 ≥ 最小值”。",
         "max_points": "3.00", "criticality": "key", "knowledge_codes": ["DERIV-MONOTONIC", "INEQUALITY"]},
        {"semantic_key": "domain_note", "order": 2, "recall_cue": "结论对哪些 x、a 成立？需要说明什么？",
         "reference_latex": "x>0,\\ a\\in\\mathbb R\\ \\text{均满足第二问的条件}", "explanation": "说明适用范围，避免遗漏定义域。",
         "max_points": "1.00", "criticality": "normal", "knowledge_codes": ["INEQUALITY"]},
        {"semantic_key": "equality_case", "order": 3, "recall_cue": "等号何时成立？",
         "reference_latex": "x\\ln x-ax\\ge -e^{a-1},\\ \\text{当且仅当 } x=e^{a-1}", "explanation": "严格单调 ⇒ 最小值点唯一。",
         "max_points": "2.00", "criticality": "key", "knowledge_codes": ["INEQUALITY"]},
    ]
    for p in (p1, p2, p3):
        for s in p["solutions"]:
            s["review_state"] = "reviewed"
    return d


def build_problems() -> list[dict]:
    out = [problem_001()]
    out.append(doc(2, "set-intersection-union-intervals", "一元二次不等式与集合运算",
                   T("设集合 $A=\\{x\\mid x^2-3x+2\\le 0\\}$，$B=\\{x\\mid 1<x<4\\}$。"),
                   [auto("interval", "interval_set", "4.00", "用区间表示 $A\\cap B$。", "(1,2]",
                         ["x^2-3x+2\\le0\\iff 1\\le x\\le 2，即 A=[1,2]", "A\\cap B=(1,2]"], key="1",
                         knowledge_codes=["SETS", "INEQUALITY"],
                         golden_cases=[{"input": "[1,2]", "expect": "rejected"}, {"input": "(1, 2]", "expect": "accepted"}]),
                    auto("interval", "interval_set", "4.00", "用区间表示 $A\\cup B$。", "[1,4)",
                         ["A\\cup B=[1,2]\\cup(1,4)=[1,4)"], key="2", knowledge_codes=["SETS"])],
                   {**diff(3), "curriculum_mappings": km("SETS", "INEQUALITY"), "problem_type": ["set", "inequality"]}))
    out.append(doc(3, "log-function-domain-choice", "对数函数的定义域（单选）",
                   T("函数 $f(x)=\\log_2(x-1)$。"),
                   [auto("single_choice", "choice_exact", "4.00", "$f(x)$ 的定义域是（　　）", "A",
                         ["真数须大于 0：x-1>0，即 x>1"], key="1", knowledge_codes=["FUNC-DOMAIN", "LOG"],
                         options=[opt("A", "$(1,+\\infty)$"), opt("B", "$[1,+\\infty)$"), opt("C", "$(0,+\\infty)$"), opt("D", "$\\mathbb{R}$")])],
                   {**diff(2), "curriculum_mappings": km("FUNC-DOMAIN", "LOG"), "problem_type": ["function"],
                    "solution_visibility": "after_submit"}))
    out.append(doc(4, "odd-functions-multiple-choice", "奇函数的判断（多选）",
                   T("下列函数中，在 $\\mathbb{R}$ 上为奇函数的有（　　）"),
                   [auto("multiple_choice", "choice_set", "6.00", "选出所有正确选项（少选按比例得分，错选不得分）。", ["A", "B", "D"],
                         ["f(-x)=-f(x) 对 x^3、\\sin x、e^x-e^{-x} 成立", "x^2+1 是偶函数"], key="1",
                         partial_credit="proportional", knowledge_codes=["FUNC-PARITY"],
                         options=[opt("A", "$y=x^3$"), opt("B", "$y=\\sin x$"), opt("C", "$y=x^2+1$"), opt("D", "$y=e^x-e^{-x}$")],
                         golden_cases=[{"input": "A,B", "expect": "partial"}, {"input": "A,C", "expect": "rejected"}])],
                   {**diff(3), "curriculum_mappings": km("FUNC-PARITY"), "problem_type": ["function"]}))
    out.append(doc(5, "arithmetic-sequence-basics", "等差数列的通项与求和",
                   T("等差数列 $\\{a_n\\}$ 中，$a_1=3$，公差 $d=4$。"),
                   [auto("integer", "integer_exact", "3.00", "求 $a_{10}$。", "39", ["a_{10}=a_1+9d=3+36=39"], key="1",
                         knowledge_codes=["SEQUENCE"]),
                    auto("integer", "integer_exact", "3.00", "求前 10 项和 $S_{10}$。", "210",
                         ["S_{10}=10a_1+\\frac{10\\cdot9}{2}d=30+180=210"], key="2", knowledge_codes=["SEQUENCE"]),
                    auto("expression", "symbolic_equivalence", "4.00", "写出通项公式 $a_n$（用 $n$ 表示）。", "4n-1",
                         ["a_n=3+(n-1)\\cdot4=4n-1"], key="3", assumptions={"n": "positive_integer"}, knowledge_codes=["SEQUENCE"],
                         golden_cases=[{"input": "3+4(n-1)", "expect": "accepted"}, {"input": "4n+3", "expect": "rejected"}])],
                   {**diff(2), "curriculum_mappings": km("SEQUENCE"), "problem_type": ["sequence"]}))
    out.append(doc(6, "draw-two-balls-probability", "不放回摸球的概率与期望",
                   T("袋中有 3 个红球、2 个白球，除颜色外完全相同。从中不放回地随机摸出 2 个球。"),
                   [auto("rational", "rational_exact", "3.00", "求两个都是红球的概率（写成最简分数）。", "3/10",
                         ["P=\\frac{C_3^2}{C_5^2}=\\frac{3}{10}"], key="1", knowledge_codes=["PROB"]),
                    auto("rational", "rational_exact", "3.00", "求恰好一红一白的概率。", "3/5",
                         ["P=\\frac{C_3^1C_2^1}{C_5^2}=\\frac{6}{10}=\\frac35"], key="2", knowledge_codes=["PROB"]),
                    auto("rational", "rational_exact", "4.00", "设摸出红球个数为 $X$，求数学期望 $E(X)$。", "6/5",
                         ["X\\sim H(5,3,2)，E(X)=2\\cdot\\frac35=\\frac65"], key="3", knowledge_codes=["PROB"])],
                   {**diff(4), "curriculum_mappings": km("PROB"), "problem_type": ["probability"]}))
    out.append(doc(7, "solution-sets-and-extraneous-roots", "方程的解集（注意增根）",
                   para({"type": "text", "text": "求下列方程的解集，答案写成集合形式，如 {1,2}。"}),
                   [auto("set", "finite_set", "4.00", "$x^2-5x+6=0$。", "{2,3}", ["(x-2)(x-3)=0"], key="1",
                         solve_for="x", knowledge_codes=["EQUATIONS"], golden_cases=[{"input": "x=3或x=2", "expect": "accepted"}]),
                    auto("set", "finite_set", "6.00", "$\\log_2 x+\\log_2(x-2)=3$。", "{4}",
                         ["定义域 x>2", "x(x-2)=8 ⇒ x=4 或 x=-2", "x=-2 不满足定义域，舍去"], key="2",
                         solve_for="x", knowledge_codes=["EQUATIONS", "LOG"],
                         golden_cases=[{"input": "{4,-2}", "expect": "rejected"}])],
                   {**diff(4), "curriculum_mappings": km("EQUATIONS", "LOG"), "problem_type": ["equation"]}))
    out.append(ellipse_problem())
    out.append(doc(9, "auxiliary-angle-sine", "辅助角公式",
                   T("已知函数 $f(x)=\\sin x+\\sqrt3\\cos x$，$x\\in\\mathbb R$。"),
                   [auto("expression", "symbolic_equivalence", "4.00", "将 $f(x)$ 化为 $A\\sin(x+\\varphi)$ 的形式。", "2*sin(x+pi/3)",
                         ["f(x)=2\\left(\\tfrac12\\sin x+\\tfrac{\\sqrt3}{2}\\cos x\\right)=2\\sin\\left(x+\\tfrac{\\pi}{3}\\right)"], key="1",
                         assumptions={"x": "real"}, knowledge_codes=["TRIG"],
                         golden_cases=[{"input": "2sin(x+pi/3)", "expect": "accepted"}, {"input": "2sin(x+pi/6)", "expect": "rejected"}]),
                    auto("integer", "integer_exact", "2.00", "求 $f(x)$ 的最大值。", "2", ["\\sin 的最大值为 1，故最大值为 2"], key="2",
                         knowledge_codes=["TRIG"]),
                    auto("expression", "symbolic_equivalence", "2.00", "求 $f(x)$ 的最小正周期。", "2*pi", ["T=2\\pi"], key="3",
                         knowledge_codes=["TRIG"])],
                   {**diff(3), "curriculum_mappings": km("TRIG"), "problem_type": ["trigonometry"]}))
    out.append(doc(10, "absolute-and-fraction-inequalities", "绝对值不等式与分式不等式",
                   para({"type": "text", "text": "解下列不等式，用区间表示解集。"}),
                   [auto("interval", "interval_set", "4.00", "$|2x-1|<3$。", "(-1,2)", ["-3<2x-1<3 ⇒ -1<x<2"], key="1",
                         knowledge_codes=["INEQUALITY"]),
                    auto("interval", "interval_set", "6.00", "$\\dfrac{x-1}{x+2}\\ge 0$。", "(-oo,-2)∪[1,+oo)",
                         ["(x-1)(x+2)\\ge0 且 x\\ne-2", "解集 (-\\infty,-2)\\cup[1,+\\infty)"], key="2", knowledge_codes=["INEQUALITY"],
                         golden_cases=[{"input": "(-∞,-2]∪[1,+∞)", "expect": "rejected"}])],
                   {**diff(4), "curriculum_mappings": km("INEQUALITY"), "problem_type": ["inequality"]}))
    out.append(doc(11, "cube-diagonal-and-tetrahedron", "正方体中的对角线与四面体",
                   T("棱长为 2 的正方体 $ABCD\\text{-}A_1B_1C_1D_1$。"),
                   [auto("expression", "symbolic_equivalence", "3.00", "求体对角线 $AC_1$ 的长。", "2*sqrt(3)",
                         ["AC_1=\\sqrt{2^2+2^2+2^2}=2\\sqrt3"], key="1", knowledge_codes=["GEO3"]),
                    auto("expression", "symbolic_equivalence", "3.00", "求 $AC_1$ 与底面 $ABCD$ 所成角的余弦值。", "sqrt(6)/3",
                         ["投影为 AC=2\\sqrt2", "\\cos\\theta=\\frac{2\\sqrt2}{2\\sqrt3}=\\frac{\\sqrt6}{3}"], key="2", knowledge_codes=["GEO3"]),
                    auto("rational", "rational_exact", "4.00", "求四面体 $AB_1CD_1$ 的体积。", "8/3",
                         ["V=8-4\\cdot\\frac16\\cdot2\\cdot2\\cdot2=8-\\frac{16}{3}=\\frac83"], key="3", knowledge_codes=["GEO3"])],
                   {**diff(5), "curriculum_mappings": km("GEO3"), "problem_type": ["solid_geometry"]}))
    out.append(cubic_problem())
    out.append(doc(13, "mean-variance-coefficient", "平均数、方差与变异系数",
                   T("一组数据：2, 4, 4, 4, 5, 5, 7, 9。"),
                   [auto("integer", "integer_exact", "2.00", "求平均数。", "5", ["\\bar x=40/8=5"], key="1", knowledge_codes=["STATS"]),
                    auto("decimal", "decimal_tolerance", "3.00", "求（总体）方差。", "4", ["s^2=\\frac{9+1+1+1+0+0+4+16}{8}=4"], key="2",
                         knowledge_codes=["STATS"]),
                    auto("decimal", "decimal_tolerance", "3.00", "求变异系数（标准差 ÷ 平均数），保留两位小数。", "0.4",
                         ["s=2，CV=2/5=0.40"], key="3", tolerance={"abs": "0.005"}, knowledge_codes=["STATS"],
                         golden_cases=[{"input": "0.40", "expect": "accepted"}, {"input": "0.41", "expect": "rejected"}])],
                   {**diff(2), "curriculum_mappings": km("STATS"), "problem_type": ["statistics"], "solution_visibility": "always"}))
    return out


def ellipse_problem() -> dict:
    d = doc(8, "ellipse-focal-chord-area", "椭圆的焦点弦长与三角形面积",
            T("已知椭圆 $C:\\dfrac{x^2}{4}+\\dfrac{y^2}{3}=1$，左、右焦点分别为 $F_1,F_2$。过 $F_1$ 且斜率为 1 的直线 $l$ 与 $C$ 交于 $A,B$ 两点。"),
            [auto("rational", "rational_exact", "2.00", "求椭圆 $C$ 的离心率。", "1/2", ["a=2,\\ b=\\sqrt3,\\ c=1", "e=c/a=1/2"], key="1",
                  knowledge_codes=["ANAG-ELLIPSE"]),
             auto("expression", "symbolic_equivalence", "4.00", "求弦长 $|AB|$。", "24/7",
                  ["l: y=x+1，代入得 7x^2+8x-8=0", "|x_1-x_2|=\\frac{\\sqrt{64+224}}{7}=\\frac{12\\sqrt2}{7}",
                   "|AB|=\\sqrt{1+k^2}\\,|x_1-x_2|=\\frac{24}{7}"], key="2", knowledge_codes=["ANAG-CHORD"]),
             auto("expression", "symbolic_equivalence", "4.00", "求 $\\triangle F_2AB$ 的面积。", "12*sqrt(2)/7",
                  ["F_2(1,0) 到 l: x-y+1=0 的距离 d=\\frac{2}{\\sqrt2}=\\sqrt2", "S=\\frac12|AB|\\,d=\\frac{12\\sqrt2}{7}"], key="3",
                  knowledge_codes=["ANAG-CHORD"],
                  golden_cases=[{"input": "\\frac{12\\sqrt{2}}{7}", "expect": "accepted"}, {"input": "12/7", "expect": "rejected"}])],
            {**diff(6), "curriculum_mappings": km("ANAG-ELLIPSE", "ANAG-CHORD"), "problem_type": ["analytic_geometry"]})
    p1, p2, p3 = d["revision"]["parts"]
    p1["reasoning_steps"] = [
        {"semantic_key": "read_abc", "order": 1, "recall_cue": "从标准方程读出 a、b，再怎样求 c？", "reference_latex": "a^2=4,\\ b^2=3,\\ c^2=a^2-b^2=1",
         "max_points": "1.00", "criticality": "normal", "knowledge_codes": ["ANAG-ELLIPSE"]},
        {"semantic_key": "eccentricity", "order": 2, "recall_cue": "离心率的定义？", "reference_latex": "e=\\frac{c}{a}=\\frac12",
         "max_points": "1.00", "criticality": "normal", "knowledge_codes": ["ANAG-ELLIPSE"]}]
    p2["reasoning_steps"] = [
        {"semantic_key": "line_equation", "order": 1, "recall_cue": "直线过 F₁(−1,0)、斜率 1，方程是什么？", "reference_latex": "l:\\ y=x+1",
         "max_points": "1.00", "criticality": "normal", "knowledge_codes": ["ANAG-CHORD"]},
        {"semantic_key": "substitute", "order": 2, "recall_cue": "联立直线与椭圆，得到关于 x 的什么方程？", "reference_latex": "3x^2+4(x+1)^2=12\\iff 7x^2+8x-8=0",
         "max_points": "1.00", "criticality": "key", "knowledge_codes": ["ANAG-CHORD"]},
        {"semantic_key": "chord_formula", "order": 3, "recall_cue": "不解出交点，怎样用韦达定理求弦长？",
         "reference_latex": "|AB|=\\sqrt{1+k^2}\\cdot\\frac{\\sqrt{\\Delta}}{|a|}=\\sqrt2\\cdot\\frac{12\\sqrt2}{7}=\\frac{24}{7}",
         "explanation": "Δ=64+224=288。", "max_points": "2.00", "criticality": "key", "knowledge_codes": ["ANAG-CHORD"]}]
    p3["reasoning_steps"] = [
        {"semantic_key": "height", "order": 1, "recall_cue": "以 AB 为底，高是哪一段？", "reference_latex": "d(F_2,l)=\\frac{|1-0+1|}{\\sqrt2}=\\sqrt2",
         "max_points": "2.00", "criticality": "key", "knowledge_codes": ["ANAG-CHORD"]},
        {"semantic_key": "area", "order": 2, "recall_cue": "面积公式代入。", "reference_latex": "S=\\frac12\\cdot\\frac{24}{7}\\cdot\\sqrt2=\\frac{12\\sqrt2}{7}",
         "max_points": "2.00", "criticality": "normal", "knowledge_codes": ["ANAG-CHORD"]}]
    return d


def cubic_problem() -> dict:
    d = doc(12, "cubic-tangent-and-extrema", "三次函数的切线与极值",
            T("已知函数 $f(x)=x^3-3x$。"),
            [auto("expression", "symbolic_equivalence", "3.00", "求 $f'(x)$。", "3x^2-3", ["f'(x)=3x^2-3"], key="1",
                  assumptions={"x": "real"}, knowledge_codes=["DERIV-RULES"],
                  golden_cases=[{"input": "3(x-1)(x+1)", "expect": "accepted"}, {"input": "3x^2", "expect": "rejected"}]),
             auto("expression", "symbolic_equivalence", "3.00", "求曲线 $y=f(x)$ 在 $x=2$ 处的切线方程（写成 $y=\\cdots$）。", "9x-16",
                  ["f(2)=2,\\ f'(2)=9", "y-2=9(x-2)，即 y=9x-16"], key="2", assumptions={"x": "real"}, knowledge_codes=["DERIV-TANGENT"],
                  golden_cases=[{"input": "y=9x-16", "expect": "accepted"}, {"input": "y=9(x-2)+2", "expect": "accepted"}]),
             auto("set", "finite_set", "4.00", "求 $f(x)$ 的所有极值点组成的集合。", "{-1,1}",
                  ["f'(x)=0 ⇒ x=\\pm1", "两侧导数异号，均为极值点（x=-1 极大，x=1 极小）"], key="3", solve_for="x",
                  knowledge_codes=["DERIV-MONOTONIC"])],
            {**diff(4), "curriculum_mappings": km("DERIV-RULES", "DERIV-TANGENT", "DERIV-MONOTONIC"), "problem_type": ["function", "calculus"]})
    p1, p2, p3 = d["revision"]["parts"]
    p1["reasoning_steps"] = [
        {"semantic_key": "power_rule", "order": 1, "recall_cue": "幂函数 xⁿ 的导数？", "reference_latex": "(x^3)'=3x^2,\\ (3x)'=3,\\ f'(x)=3x^2-3",
         "max_points": "3.00", "criticality": "normal", "knowledge_codes": ["DERIV-RULES"]}]
    p2["reasoning_steps"] = [
        {"semantic_key": "slope", "order": 1, "recall_cue": "切线斜率等于什么？", "reference_latex": "k=f'(2)=9,\\ f(2)=2",
         "max_points": "2.00", "criticality": "key", "knowledge_codes": ["DERIV-TANGENT"]},
        {"semantic_key": "point_slope", "order": 2, "recall_cue": "点斜式写出切线。", "reference_latex": "y-2=9(x-2)\\iff y=9x-16",
         "max_points": "1.00", "criticality": "normal", "knowledge_codes": ["DERIV-TANGENT"]}]
    p3["reasoning_steps"] = [
        {"semantic_key": "stationary", "order": 1, "recall_cue": "极值点的候选从哪里来？", "reference_latex": "f'(x)=3(x-1)(x+1)=0\\Rightarrow x=\\pm1",
         "max_points": "2.00", "criticality": "key", "knowledge_codes": ["DERIV-MONOTONIC"]},
        {"semantic_key": "sign_change", "order": 2, "recall_cue": "候选点一定是极值点吗？还要检查什么？",
         "reference_latex": "f'\\text{ 在 }x=-1\\text{ 由正变负（极大）},\\ x=1\\text{ 由负变正（极小）}",
         "max_points": "2.00", "criticality": "key", "knowledge_codes": ["DERIV-MONOTONIC"]}]
    return d
