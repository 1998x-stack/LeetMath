"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const CMS = require("../cms-editor.js");

function fixture() {
  return {
    schema_version: "1.0.0",
    source_record_refs: [{ external_id: "abc", source_code: "local" }],
    rights_policy_ref: "grant-original",
    revision: {
      title: "题目", shared_statement: { blocks: [{ type: "paragraph", spans: [
        { type: "text", text: "已知 " }, { type: "inline_math", latex: "x^2" },
        { type: "link", text: "来源", href: "https://example.org" }
      ] }] },
      content_metadata: { platform_difficulty: { value: 3, origin: "editorial" },
        curriculum_mappings: [{ knowledge_code: "DERIV-RULES" }] },
      parts: [{
        part_key: "a", display_order: 1, logical_part_id: "stable-a",
        response_type: "proof", max_score: "3.00",
        answer_spec: { checker_type: "rubric_manual", grading_mode: "manual" },
        rubric: { criteria: [{ id: "c1", max_points: "3.00" }] },
        prompt: { blocks: [{ type: "image", asset_id: "unchanged-image", alt: "图" }] }
      }, {
        part_key: "b", display_order: 2, logical_part_id: "stable-b",
        response_type: "integer", max_score: "2.00",
        prompt: { blocks: [{ type: "paragraph", spans: [{ type: "text", text: "求值" }] }] },
        answer_spec: { checker_type: "integer_exact", expected: "42" }
      }]
    }
  };
}

test("copy and field changes never mutate the source contract", () => {
  const original = fixture();
  const edited = CMS.copy(original);
  edited.revision.title = "修改后的题目";
  edited.revision.parts[1].answer_spec.expected = "43";
  assert.equal(original.revision.title, "题目");
  const paths = CMS.changes(original, edited).map((x) => x.path);
  assert.deepEqual(paths, ["$.revision.title", "$.revision.parts[1].answer_spec.expected"]);
});

test("reordering parts preserves stable keys, identities, rubric, media, and rights", () => {
  const doc = fixture();
  assert.equal(CMS.movePart(doc, 1, -1), true);
  assert.deepEqual(doc.revision.parts.map((p) => p.part_key), ["b", "a"]);
  assert.deepEqual(doc.revision.parts.map((p) => p.logical_part_id), ["stable-b", "stable-a"]);
  assert.deepEqual(doc.revision.parts.map((p) => p.display_order), [1, 2]);
  assert.equal(doc.revision.parts[1].prompt.blocks[0].asset_id, "unchanged-image");
  assert.equal(doc.revision.parts[1].rubric.criteria[0].max_points, "3.00");
  assert.equal(doc.rights_policy_ref, "grant-original");
  assert.equal(CMS.movePart(doc, 0, -1), false);
});

test("adding a part creates a unique stable part_key and keeps existing identities", () => {
  const doc = fixture();
  const p = CMS.addPart(doc);
  assert.equal(p.part_key, "1");
  assert.equal(p.display_order, 3);
  assert.equal(p.knowledge_codes[0], "DERIV-RULES");
  assert.equal(p.answer_spec.checker_type, "symbolic_equivalence");
  assert.equal(p.solutions[0].review_state, "unreviewed");
  assert.equal(doc.revision.parts[0].logical_part_id, "stable-a");
  assert.equal(doc.source_record_refs[0].external_id, "abc");
  assert.equal(CMS.addPart(doc).part_key, "2");
});

test("RichText span append preserves links and other existing rich blocks", () => {
  const doc = fixture();
  const rt = doc.revision.shared_statement;
  CMS.appendSpan(rt, "inline_math");
  assert.equal(rt.blocks[0].spans[2].href, "https://example.org");
  assert.equal(rt.blocks[0].spans[3].latex, "x");
  CMS.appendSpan(rt, "text");
  assert.equal(rt.blocks[0].spans[4].text, "新文字");
});

test("nested changes preserve reference values and distinguish deleted fields", () => {
  const a = fixture();
  const b = CMS.copy(a);
  delete b.revision.parts[0].rubric;
  const diff = CMS.changes(a, b);
  assert.equal(diff.length, 1);
  assert.equal(diff[0].path, "$.revision.parts[0].rubric");
  assert.equal(diff[0].after, undefined);
  assert.equal(diff[0].before.criteria[0].id, "c1");
});

test("new-revision row identity and workflow state are not reported as content changes", () => {
  const published = fixture();
  published.revision.id = "row-v1";
  published.revision.revision_no = 1;
  published.revision.status = "published";
  published.revision.parts[0].id = "part-row-v1";
  published.revision.parts[1].id = "part-row-v1b";

  // What the server returns for a revision created from the published one: identical
  // editorial content, fresh row ids, new revision number, draft state.
  const draft = CMS.copy(published);
  draft.revision.id = "row-v2";
  draft.revision.revision_no = 2;
  draft.revision.status = "draft";
  draft.revision.parts[0].id = "part-row-v2";
  draft.revision.parts[1].id = "part-row-v2b";

  assert.deepEqual(CMS.changes(published, draft), []);
});

test("one editorial edit on a new revision is reported exactly once", () => {
  const published = fixture();
  published.revision.id = "row-v1";
  published.revision.revision_no = 1;
  published.revision.status = "published";
  const draft = CMS.copy(published);
  draft.revision.id = "row-v2";
  draft.revision.revision_no = 2;
  draft.revision.status = "draft";
  draft.revision.title = "修订后的标题";
  const diff = CMS.changes(published, draft);
  assert.equal(diff.length, 1);
  assert.equal(diff[0].path, "$.revision.title");
  assert.equal(diff[0].before, "题目");
  assert.equal(diff[0].after, "修订后的标题");
});
