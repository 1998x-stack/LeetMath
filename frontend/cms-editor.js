/* LeetMath structured CMS: a lossless editor for common Contract v1 fields.
 * Unsupported rich blocks and grading settings are preserved, not flattened.
 * Raw JSON mode remains available for advanced content. No untrusted HTML. */
(function (root) {
  "use strict";

  function copy(value) { return JSON.parse(JSON.stringify(value)); }

  // Row identity and workflow state are per-revision storage details, not editorial content:
  // a freshly created revision always differs from its parent in these fields, so counting
  // them would report "4 处" before the author changed anything and drown the real diff.
  const IGNORED_DIFF_PATHS = /^\$\.revision\.(id|revision_no|status)$|^\$\.revision\.parts\[\d+\]\.id$/;

  function changes(before, after, path, out) {
    path = path || "$";
    out = out || [];
    if (out.length >= 100 || JSON.stringify(before) === JSON.stringify(after)) return out;
    const aObject = before !== null && typeof before === "object";
    const bObject = after !== null && typeof after === "object";
    if (aObject && bObject && Array.isArray(before) === Array.isArray(after)) {
      const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
      for (const key of keys) {
        if (out.length >= 100) break;
        const suffix = Array.isArray(before) ? "[" + key + "]" : "." + key;
        changes(before[key], after[key], path + suffix, out);
      }
    } else if (!IGNORED_DIFF_PATHS.test(path)) {
      out.push({ path: path, before: before, after: after });
    }
    return out;
  }

  function addPart(doc) {
    const parts = doc.revision.parts;
    const used = new Set(parts.map((p) => String(p.part_key)));
    let n = 1;
    while (used.has(String(n))) n += 1;
    const mapping = (doc.revision.content_metadata || {}).curriculum_mappings || [];
    const p = {
      part_key: String(n), display_order: parts.length + 1,
      response_type: "expression", max_score: "1.00",
      prompt: { blocks: [{ type: "paragraph", spans: [{ type: "text", text: "新小问（请修改）" }] }] },
      answer_spec: { spec_version: 1, grading_mode: "automatic", checker_type: "symbolic_equivalence", expected: "x", assumptions: { x: "real" } },
      solutions: [{ type: "worked", review_state: "unreviewed", steps: ["请补充解题步骤"] }]
    };
    if (mapping.length) p.knowledge_codes = [mapping[0].knowledge_code];
    parts.push(p);
    return p;
  }

  function movePart(doc, index, delta) {
    const parts = doc.revision.parts;
    const target = index + delta;
    if (target < 0 || target >= parts.length) return false;
    const temp = parts[index];
    parts[index] = parts[target];
    parts[target] = temp;
    parts.forEach((p, i) => { p.display_order = i + 1; });
    return true;
  }

  function appendSpan(rt, kind) {
    if (!rt.blocks) rt.blocks = [];
    let block = rt.blocks.find((b) => b.type === "paragraph");
    if (!block) {
      block = { type: "paragraph", spans: [] };
      rt.blocks.push(block);
    }
    if (!Array.isArray(block.spans)) block.spans = [];
    block.spans.push(kind === "inline_math" ? { type: "inline_math", latex: "x" } : { type: "text", text: "新文字" });
  }

  function createForm(doc, opts) {
    const h = opts.h;
    const editable = opts.editable;
    const signal = () => opts.onChange();
    const rootNode = h("div", { class: "cms-form" });

    function textField(label, value, setter, multiline, note) {
      const input = h(multiline ? "textarea" : "input",
        multiline ? { rows: 2, disabled: !editable } : { type: "text", disabled: !editable });
      input.value = value === undefined || value === null ? "" : String(value);
      input.addEventListener("input", () => { setter(input.value); signal(); });
      return h("label", { class: "cms-field" }, h("span", {}, label), input, note ? h("small", { class: "muted" }, note) : null);
    }

    function button(label, cb, cls) {
      return h("button", { type: "button", class: "btn sm " + (cls || ""), disabled: !editable, onclick: cb }, label);
    }

    // `scope` is a stable machine name for the edited region (data-cms-scope) so field
    // names that repeat across regions (~"行内公式 LaTeX #2" in every RichText block)
    // stay unambiguous for tests and assistive technology.
    function richEditor(label, rt, scope) {
      const container = h("section", { class: "cms-rich", "data-cms-scope": scope, "aria-label": label + " 编辑区" },
        h("h3", {}, label));
      if (!rt || !Array.isArray(rt.blocks)) return container;
      const preview = h("div", { class: "cms-preview statement", "aria-label": label + " 预览" }, opts.rich(rt));
      const changed = () => { preview.replaceChildren(opts.rich(rt)); signal(); };
      rt.blocks.forEach((block, bi) => {
        const header = h("div", { class: "cms-block-title" }, "区块 " + (bi + 1) + " · " + block.type);
        container.append(header);
        if (block.type === "paragraph") {
          (block.spans || []).forEach((span, si) => {
            if (["text", "emphasis", "inline_math"].includes(span.type)) {
              const key = span.type === "inline_math" ? "latex" : "text";
              const input = textField(
                (span.type === "inline_math" ? "行内公式 LaTeX" : span.type === "emphasis" ? "强调文本" : "正文") + " #" + (si + 1),
                span[key], (v) => { span[key] = v; preview.replaceChildren(opts.rich(rt)); }, false);
              container.append(h("div", { class: "cms-inline-row" }, input,
                button("删除片段", () => { block.spans.splice(si, 1); opts.refresh(); })));
            } else {
              container.append(h("p", { class: "muted small" }, "暂不支持可视化编辑的片段 " + span.type + "（已原样保留，可在 JSON 模式编辑）"));
            }
          });
          container.append(h("div", { class: "row" },
            button("添加文字", () => { block.spans.push({ type: "text", text: "新文字" }); opts.refresh(); }),
            button("添加行内公式", () => { block.spans.push({ type: "inline_math", latex: "x" }); opts.refresh(); })));
        } else if (block.type === "display_math") {
          container.append(textField("独立公式 LaTeX", block.latex,
            (v) => { block.latex = v; preview.replaceChildren(opts.rich(rt)); }));
        } else {
          container.append(h("p", { class: "muted small" },
            "该区块仅预览，数据保持不变；图片、表格、列表等高级内容请使用 JSON 模式。"));
        }
      });
      container.append(h("div", { class: "row" },
        button("添加段落", () => { rt.blocks.push({ type: "paragraph", spans: [{ type: "text", text: "新段落" }] }); opts.refresh(); }),
        button("添加独立公式", () => { rt.blocks.push({ type: "display_math", latex: "x=1" }); opts.refresh(); })));
      container.append(preview);
      return container;
    }

    rootNode.append(h("p", { class: "muted small" }, "编辑内容会原位更新数据模型；高级元数据、答案规则、知识点映射、评分细则和复杂媒体区块保留原值。变更前请预检并保存。"));
    rootNode.append(textField("题目标题", doc.revision.title, (v) => { doc.revision.title = v; }));
    const metadata = doc.revision.content_metadata || {};
    const difficulty = metadata.platform_difficulty;
    if (difficulty) {
      const level = h("input", { type: "number", min: 1, max: 10, step: 1, disabled: !editable });
      level.value = difficulty.value ?? "";
      level.addEventListener("input", () => { difficulty.value = Number(level.value); signal(); });
      rootNode.append(h("label", { class: "cms-field" }, h("span", {}, "难度 (1–10)"), level));
    }
    rootNode.append(richEditor("公共题干", doc.revision.shared_statement, "revision.shared_statement"));

    const parts = doc.revision.parts || [];
    parts.forEach((part, index) => {
      const section = h("section", { class: "cms-part", "data-cms-part-key": part.part_key,
          "aria-label": "小问 " + (index + 1) + " · part_key=" + part.part_key },
        h("div", { class: "row spread" }, h("h3", {}, "小问 " + (index + 1) + " · part_key=" + part.part_key),
          h("div", { class: "row" },
            button("上移", () => { movePart(doc, index, -1); opts.refresh(); }),
            button("下移", () => { movePart(doc, index, +1); opts.refresh(); }),
            button("删除小问", () => {
              if (parts.length === 1) return;
              if (root.confirm("删除小问 " + part.part_key + "？此操作只影响当前草稿。")) {
                parts.splice(index, 1);
                parts.forEach((p, i) => { p.display_order = i + 1; });
                opts.refresh();
              }
            }, "danger"))),
        h("p", { class: "muted small" }, "题型：" + part.response_type + " · 判题器：" + (part.answer_spec || {}).checker_type +
          "（变更题型/判题模式、rubric、推理卡请使用 JSON 模式）"),
        textField("分值", part.max_score, (v) => { part.max_score = v; }, false,
          part.rubric || part.reasoning_steps ? "注意：本问包含评分细则/推理卡，分值修改可能需要同时调整权重。" : ""),
        richEditor("小问题干 · 小问 " + (index + 1), part.prompt, "revision.parts." + part.part_key + ".prompt"));
      const spec = part.answer_spec || {};
      const keys = ["expected", "canonical_expr", "expected_latex"];
      for (const key of keys) {
        if (typeof spec[key] === "string") section.append(textField(
          "参考答案 · " + key, spec[key], (v) => { spec[key] = v; }, true));
      }
      (part.solutions || []).forEach((solution, solutionIndex) => {
        section.append(h("h3", {}, "解答方案 " + (solutionIndex + 1)));
        (solution.steps || []).forEach((step, si) => {
          section.append(textField("解答步骤 " + (si + 1), step,
            (v) => { solution.steps[si] = v; }, true));
        });
        section.append(button("添加解答步骤", () => {
          if (!Array.isArray(solution.steps)) solution.steps = [];
          solution.steps.push("新步骤");
          opts.refresh();
        }));
      });
      rootNode.append(section);
    });
    rootNode.append(button("新增小问", () => { addPart(doc); opts.refresh(); }, "primary"));
    if (!editable) rootNode.querySelectorAll("input,textarea,button").forEach((el) => { el.disabled = true; });
    return rootNode;
  }

  const API = { copy, changes, addPart, movePart, appendSpan, createForm };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  root.LeetMathCms = API;
})(typeof window !== "undefined" ? window : globalThis);
