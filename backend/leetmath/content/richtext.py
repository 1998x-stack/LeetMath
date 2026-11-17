"""MathRichText safety + text extraction (docs/03 §4).

Rich text is structured blocks, never raw HTML. The browser renders text spans with textContent
and formulas with KaTeX (trust=false). Here we additionally reject LaTeX commands that can
fetch resources, define macros or inject markup, and check structural balance as a render pre-check.
"""
from __future__ import annotations

import re
from typing import Any, Iterator

# Commands that can load resources, define macros, emit HTML/links or run IO in some engines.
FORBIDDEN_LATEX = {
    "href", "url", "include", "input", "def", "gdef", "edef", "xdef", "newcommand", "renewcommand",
    "providecommand", "let", "futurelet", "write", "immediate", "openout", "openin", "read", "csname",
    "htmlClass", "htmlId", "htmlStyle", "htmlData", "includegraphics", "special", "catcode", "loop",
    "expandafter", "usepackage", "documentclass", "begingroup", "endgroup", "global",
}
_CMD_RE = re.compile(r"\\([A-Za-z]+)")


def latex_issues(latex: str) -> list[str]:
    """Return a list of blocking problems with a LaTeX fragment (empty = OK)."""
    issues: list[str] = []
    for cmd in _CMD_RE.findall(latex):
        if cmd in FORBIDDEN_LATEX:
            issues.append(f"forbidden command \\{cmd}")
    depth = 0
    escaped = False
    for ch in latex:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                issues.append("unbalanced braces")
                break
    if depth > 0:
        issues.append("unbalanced braces")
    if len(re.findall(r"\\left\b", latex)) != len(re.findall(r"\\right\b", latex)):
        issues.append("unbalanced \\left/\\right")
    if latex.count("\\begin{") != latex.count("\\end{"):
        issues.append("unbalanced \\begin/\\end")
    return issues


def iter_spans(rt: dict | None) -> Iterator[dict]:
    for block in (rt or {}).get("blocks", []):
        t = block.get("type")
        if t == "paragraph":
            yield from block.get("spans", [])
        elif t == "table":
            for row in block.get("rows", []):
                for cell in row:
                    yield from cell
        elif t == "list":
            for item in block.get("items", []):
                yield from item


def iter_latex(rt: dict | None) -> Iterator[str]:
    for span in iter_spans(rt):
        if span.get("type") == "inline_math":
            yield span["latex"]
    for block in (rt or {}).get("blocks", []):
        if block.get("type") == "display_math":
            yield block["latex"]


def iter_asset_ids(rt: dict | None) -> Iterator[str]:
    for block in (rt or {}).get("blocks", []):
        if block.get("type") in ("image", "diagram") and block.get("asset_id"):
            yield block["asset_id"]


def is_empty(rt: dict | None) -> bool:
    for block in (rt or {}).get("blocks", []):
        t = block.get("type")
        if t in ("display_math", "image", "diagram", "table", "list"):
            return False
        if t == "paragraph" and any(
            (s.get("text") or s.get("latex") or "").strip() for s in block.get("spans", [])
        ):
            return False
    return True


def to_plain_text(rt: dict | None) -> str:
    """Searchable text: words + raw LaTeX (for display_id/LaTeX-literal search)."""
    out: list[str] = []
    for block in (rt or {}).get("blocks", []):
        t = block.get("type")
        if t == "display_math":
            out.append(block["latex"])
        elif t in ("image", "diagram"):
            out.append(block.get("alt", ""))
    for span in iter_spans(rt):
        out.append(span.get("text") or span.get("latex") or "")
    return " ".join(x for x in out if x)


_LATEX_NOISE = re.compile(r"\\(left|right|displaystyle|,|;|!|quad|qquad)|\s+")


def normalize_for_dedup(text: str) -> str:
    """Normalisation used *only* for duplicate-candidate signals, never to rewrite content."""
    t = _LATEX_NOISE.sub("", text)
    t = t.replace("\\geqslant", "\\geq").replace("\\leqslant", "\\leq").replace("\\ge", "\\geq")
    t = t.replace("，", ",").replace("。", ".").replace("：", ":").replace("（", "(").replace("）", ")")
    return t


def walk(obj: Any) -> Iterator[Any]:
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)
