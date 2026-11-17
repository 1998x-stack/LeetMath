"""Source adapters (docs/05 §2). Adapters only *parse + normalise* to Contract v1 — they never publish.

New sources add an adapter + config; core tables never change.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from typing import Iterator

from ..content.contract import NORMALIZER_VERSION, sha256_text


class AdapterError(Exception):
    def __init__(self, stage: str, code: str, message: str):
        super().__init__(message)
        self.stage, self.code, self.message = stage, code, message


@dataclass
class RawRow:
    row_no: int
    raw: bytes
    key_hint: str | None = None


@dataclass
class IntakeRecord:
    external_id: str
    external_revision: str
    doc: dict
    warnings: list[str] = field(default_factory=list)


# ─────────────────────────── rich-text helpers ───────────────────────────
_DOLLAR = re.compile(r"\$([^$]+)\$")
_MATHY = re.compile(r"([A-Za-z0-9\\^_{}()'+\-=<>|.,\s]*\\[A-Za-z]+[A-Za-z0-9\\^_{}()'+\-=<>|.\s]*|[A-Za-z]\([A-Za-z]\)'?|[A-Za-z]'\([A-Za-z]\))")


def text_to_richtext(text: str) -> dict:
    """'已知 $f(x)=x^2$ 求…' → paragraph spans. Without $…$, LaTeX-looking runs become inline math."""
    spans = []
    if "$" in text:
        pos = 0
        for m in _DOLLAR.finditer(text):
            if m.start() > pos:
                spans.append({"type": "text", "text": text[pos:m.start()]})
            spans.append({"type": "inline_math", "latex": m.group(1).strip()})
            pos = m.end()
        if pos < len(text):
            spans.append({"type": "text", "text": text[pos:]})
    else:
        pos = 0
        for m in _MATHY.finditer(text):
            seg = m.group(0).strip()
            if not seg:
                continue
            if m.start() > pos:
                spans.append({"type": "text", "text": text[pos:m.start()]})
            spans.append({"type": "inline_math", "latex": seg})
            pos = m.end()
        if pos < len(text):
            spans.append({"type": "text", "text": text[pos:]})
    spans = [sp for sp in spans if sp.get("text", sp.get("latex", "")).strip()]
    return {"blocks": [{"type": "paragraph", "spans": spans}]} if spans else {"blocks": []}


def _pseudo_revision(raw: bytes) -> str:
    return "h:" + sha256_text(raw)[:16]


# ─────────────────────────── adapters ───────────────────────────
class ContractJsonlAdapter:
    """Each line is a full Content Contract v1 document (our own / partner native format)."""

    adapter_version = "contract-jsonl-v1"

    def rows(self, data: bytes) -> Iterator[RawRow]:
        for i, line in enumerate(data.decode("utf-8").splitlines(), start=1):
            if line.strip():
                yield RawRow(i, line.encode("utf-8"))

    def parse(self, row: RawRow, source_code: str) -> IntakeRecord:
        try:
            doc = json.loads(row.raw)
        except json.JSONDecodeError as e:
            raise AdapterError("parse", "PARSE_FAILED", f"invalid JSON: {e.msg}") from e
        if not isinstance(doc, dict):
            raise AdapterError("parse", "PARSE_FAILED", "record is not an object")
        refs = doc.get("source_record_refs") or []
        ref = next((r for r in refs if r.get("source_code") == source_code), None)
        if ref is None:
            raise AdapterError("normalize", "NORMALIZE_FAILED", f"no source_record_ref for source {source_code}")
        for k in ("id",):
            (doc.get("problem") or {}).pop(k, None)
            (doc.get("revision") or {}).pop(k, None)
        for p in (doc.get("revision") or {}).get("parts", []) or []:
            p.pop("id", None)
            p.pop("logical_part_id", None)
        (doc.get("problem") or {}).pop("display_id", None)
        (doc.get("revision") or {}).pop("status", None)
        return IntakeRecord(str(ref["external_id"]), str(ref.get("external_revision") or _pseudo_revision(row.raw)), doc)


class DemoJsonlAdapter:
    """docs/examples/demo-source.jsonl shape: {external_id, version, title, stem_latex, parts[{key, question}]}.

    The format carries no answers → parts become practice-only drafts that editors must complete.
    """

    adapter_version = "demo-jsonl-v1"

    def rows(self, data: bytes) -> Iterator[RawRow]:
        yield from ContractJsonlAdapter().rows(data)

    def parse(self, row: RawRow, source_code: str) -> IntakeRecord:
        try:
            rec = json.loads(row.raw)
            ext, ver, title, parts = rec["external_id"], str(rec.get("version", "")), rec["title"], rec["parts"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise AdapterError("parse", "PARSE_FAILED", f"bad demo record: {e}") from e
        if not parts:
            raise AdapterError("normalize", "NORMALIZE_FAILED", "record has no parts")
        stem = rec.get("stem_latex")
        doc = {
            "schema_version": "1.0.0",
            "problem": {"grade_band": rec.get("grade_band", "senior_high"), "subject": "mathematics"},
            "revision": {
                "locale": rec.get("locale", "zh-CN"),
                "title": title,
                "shared_statement": {"blocks": [{"type": "display_math", "latex": stem}]} if stem else {"blocks": []},
                "content_metadata": {"region_hints": rec.get("region_hints", ["CN-SH"]), "import_placeholder_scores": True},
                "parts": [
                    {
                        "part_key": str(p["key"]), "display_order": i, "response_type": "short_text",
                        "max_score": "1.00", "prompt": text_to_richtext(p["question"]),
                        "answer_spec": {"spec_version": 1, "grading_mode": "practice_only", "checker_type": "rubric_manual"},
                    }
                    for i, p in enumerate(parts, start=1)
                ],
            },
            "source_record_refs": [{"source_code": source_code, "external_id": ext, "external_revision": ver or _pseudo_revision(row.raw)}],
            "rights_policy_ref": "",
        }
        return IntakeRecord(ext, ver or _pseudo_revision(row.raw), doc,
                            ["answers missing: parts imported as practice_only with placeholder max_score 1.00"])


class CsvSimpleAdapter:
    """Partner CSV: one line per part; lines sharing external_id form one problem.

    Columns: external_id, version, title, grade_band, region, statement, part_key, prompt, response_type,
    max_score, checker_type, expected, assumptions(JSON), options(JSON {"A":"…"}), knowledge_code,
    difficulty, solution. Inline math uses $…$.
    """

    adapter_version = "csv-simple-v1"
    REQUIRED = {"external_id", "title", "part_key", "prompt", "response_type", "max_score"}

    def rows(self, data: bytes) -> Iterator[RawRow]:
        text = data.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        missing = self.REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise AdapterError("parse", "IMPORT_SCHEMA_MISMATCH", f"missing CSV columns: {sorted(missing)}")
        groups: dict[str, list[tuple[int, dict]]] = {}
        order: list[str] = []
        for line_no, rec in enumerate(reader, start=2):
            if None in rec:  # more fields than header columns → reject this record, not the batch
                rec["__extra_fields__"] = str(len(rec.pop(None)))
            rec = {k: (v if v is not None else "") for k, v in rec.items()}
            ext = (rec.get("external_id") or "").strip() or f"__line{line_no}"
            if ext not in groups:
                order.append(ext)
            groups.setdefault(ext, []).append((line_no, rec))
        for ext in order:
            lines = groups[ext]
            yield RawRow(lines[0][0], json.dumps([r for _, r in lines], ensure_ascii=False, sort_keys=True).encode("utf-8"), ext)

    def parse(self, row: RawRow, source_code: str) -> IntakeRecord:
        recs = json.loads(row.raw)
        first = recs[0]
        bad = [r for r in recs if r.get("__extra_fields__")]
        if bad:
            raise AdapterError("parse", "PARSE_FAILED", f"line has {bad[0]['__extra_fields__']} more field(s) than the header (check quoting)")
        ext = (first.get("external_id") or "").strip()
        if not ext:
            raise AdapterError("parse", "PARSE_FAILED", "external_id is empty")
        parts = []
        try:
            for i, r in enumerate(recs, start=1):
                rtype = r["response_type"].strip()
                ctype = (r.get("checker_type") or "").strip()
                spec: dict = {"spec_version": 1, "grading_mode": "automatic" if ctype and ctype != "rubric_manual" else "manual",
                              "checker_type": ctype or "rubric_manual"}
                if r.get("expected"):
                    exp = r["expected"].strip()
                    spec["expected"] = [x.strip() for x in exp.split("|")] if rtype == "multiple_choice" else exp
                if r.get("assumptions"):
                    spec["assumptions"] = json.loads(r["assumptions"])
                part = {"part_key": r["part_key"].strip(), "display_order": i, "response_type": rtype,
                        "max_score": r["max_score"].strip(), "prompt": text_to_richtext(r["prompt"]), "answer_spec": spec}
                if r.get("options"):
                    opts = json.loads(r["options"])
                    part["options"] = [{"id": k, "content": text_to_richtext(v)} for k, v in opts.items()]
                if r.get("knowledge_code"):
                    part["knowledge_codes"] = [r["knowledge_code"].strip()]
                if r.get("solution"):
                    part["solutions"] = [{"type": "worked", "review_state": "unreviewed", "steps": [r["solution"]]}]
                if spec["grading_mode"] == "manual":
                    part["rubric"] = {"version": 1, "criteria": [{"id": f"P{i}-C1", "description": "按参考解答整体评分", "max_points": part["max_score"]}]}
                parts.append(part)
        except (KeyError, ValueError, AttributeError) as e:
            raise AdapterError("normalize", "NORMALIZE_FAILED", f"bad CSV value: {e}") from e
        md: dict = {"region_hints": [first["region"]] if first.get("region") else []}
        if (first.get("difficulty") or "").strip().isdigit():
            md["platform_difficulty"] = {"value": int(first["difficulty"]), "origin": f"source:{source_code}"}
        codes = sorted({c for p in parts for c in p.get("knowledge_codes", [])})
        if codes and first.get("curriculum_code") and first.get("release_code"):
            md["curriculum_mappings"] = [{"curriculum_code": first["curriculum_code"], "release_code": first["release_code"],
                                          "knowledge_code": c, "relation_type": "tested"} for c in codes]
        doc = {
            "schema_version": "1.0.0",
            "problem": {"grade_band": (first.get("grade_band") or "senior_high").strip(), "subject": "mathematics"},
            "revision": {"locale": "zh-CN", "title": first["title"].strip(),
                         "shared_statement": text_to_richtext(first.get("statement") or ""),
                         "content_metadata": md, "parts": parts},
            "source_record_refs": [{"source_code": source_code, "external_id": ext,
                                    "external_revision": (first.get("version") or "").strip() or _pseudo_revision(row.raw)}],
            "rights_policy_ref": "",
        }
        return IntakeRecord(ext, doc["source_record_refs"][0]["external_revision"], doc)


ADAPTERS = {a.adapter_version: a for a in (ContractJsonlAdapter(), DemoJsonlAdapter(), CsvSimpleAdapter())}
SUPPORTED_NORMALIZERS = {NORMALIZER_VERSION}
