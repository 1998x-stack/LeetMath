/* LeetMath SPA — vanilla JS, no build step.
 * Security: every piece of content is inserted with textContent / KaTeX (trust:false). No innerHTML with data. */
"use strict";

// ───────────────────────── utilities ─────────────────────────
const $app = document.getElementById("app");
const state = { token: sessionStorage.getItem("lm_token"), user: null, attempts: {}, knowledge: null };

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36));
function toast(msg) { const t = document.getElementById("toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 2600); }
function mount(...nodes) { $app.replaceChildren(...nodes); $app.focus({ preventScroll: true }); }

async function api(method, path, body, extraHeaders = {}) {
  const headers = { ...extraHeaders };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  let res;
  try { res = await fetch("/api/v1" + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) }); }
  catch (e) { throw { status: 0, code: "NETWORK", message: "网络连接失败，请重试" }; }
  if (res.status === 204) return null;
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) {
    const err = (data && data.error) || { code: "HTTP_" + res.status, message: String(data) };
    if (res.status === 401 && state.token && err.code === "AUTH_REQUIRED") { logout(true); }
    throw { status: res.status, ...err, etag: res.headers.get("ETag") };
  }
  if (data && typeof data === "object") Object.defineProperty(data, "_etag", { value: res.headers.get("ETag"), enumerable: false });
  return data;
}
const ERR_TEXT = {
  AUTH_REQUIRED: "请先登录", FORBIDDEN: "没有权限", NOT_FOUND: "不存在或暂不可访问", CONTENT_RETRACTED: "题目已下架",
  REVISION_SUPERSEDED: "题目已更新为新版本，请刷新后作答", RIGHTS_HOLD: "该内容因版权原因暂不可用", RATE_LIMITED: "操作太频繁，请稍后再试",
  EDIT_CONFLICT: "草稿已被他人修改，请刷新后合并", IDEMPOTENCY_CONFLICT: "重复请求冲突", SELF_APPROVAL_FORBIDDEN: "不能审批自己创建的内容",
};
const errText = (e) => (ERR_TEXT[e.code] ? ERR_TEXT[e.code] + "" : "") + (e.message && !ERR_TEXT[e.code] ? e.message : "") || "出错了";

// ───────────────────────── math rendering ─────────────────────────
function mathEl(latex, display = false) {
  const span = h(display ? "div" : "span", { class: display ? "display-math" : "inline-math" });
  if (window.katex) {
    try { window.katex.render(latex, span, { displayMode: display, throwOnError: false, trust: false, strict: "ignore", maxExpand: 500 }); }
    catch { span.textContent = latex; }
  } else span.append(h("code", {}, latex));
  span.setAttribute("title", latex);
  return span;
}
function spans(list) {
  return (list || []).map((s) => {
    if (s.type === "inline_math") return mathEl(s.latex);
    if (s.type === "emphasis") return h("em", {}, s.text);
    if (s.type === "link") return /^(https:\/\/|\/)/.test(s.href) ? h("a", { href: s.href, rel: "noopener noreferrer", target: "_blank" }, s.text) : s.text;
    return s.text;
  });
}
function rich(rt) {
  const frag = document.createDocumentFragment();
  for (const b of (rt && rt.blocks) || []) {
    if (b.type === "paragraph") frag.append(h("p", {}, spans(b.spans)));
    else if (b.type === "display_math") frag.append(mathEl(b.latex, true));
    else if (b.type === "list") frag.append(h(b.ordered ? "ol" : "ul", {}, b.items.map((it) => h("li", {}, spans(it)))));
    else if (b.type === "table") frag.append(h("table", { class: "list" }, b.rows.map((r) => h("tr", {}, r.map((c) => h("td", {}, spans(c)))))));
    else if (b.type === "image" || b.type === "diagram") frag.append(h("figure", { class: "muted small" }, "[图] ", b.alt || ""));
  }
  return frag;
}
/** text that mixes CJK prose and LaTeX (solution steps, references) → render as math where it looks like math */
const LOOKS_LATEX = /[\\^_{}=<>]|\d\s*[a-z]|[a-z]\(/;
function mixed(text) {
  // Only runs that actually look like LaTeX become math; plain prose (e.g. "x·ln x") stays text.
  if (/[一-鿿]/.test(text)) {
    const parts = text.split(/([一-鿿，。；：、（）“”？！]+)/).filter(Boolean);
    return parts.map((p) => (/^[一-鿿，。；：、（）“”？！]+$/.test(p) || !LOOKS_LATEX.test(p) ? p : p.trim() ? mathEl(p.trim()) : p));
  }
  return LOOKS_LATEX.test(text) ? mathEl(text) : text;
}
/** plain-text answer → LaTeX for the live preview only (never changes what is submitted) */
function toPreviewLatex(v) {
  return v.replace(/(^|[^\\a-zA-Z])(sqrt|ln|log|sin|cos|tan|pi|exp)\b/g, (m, pre, w) => pre + "\\" + w + (w === "sqrt" ? "" : " "))
    .replace(/\\sqrt\s*\(([^()]*)\)/g, "\\sqrt{$1}").replace(/\boo\b|∞/g, "\\infty ").replace(/\*/g, "\\cdot ");
}
function diffChip(d) { if (!d) return h("span", { class: "muted" }, "—"); const c = d <= 3 ? "e" : d <= 6 ? "m" : "h"; return h("span", { class: "diff " + c, title: "平台难度 1–10" }, d); }
const RT_LABEL = { single_choice: "单选", multiple_choice: "多选", integer: "整数", rational: "分数", decimal: "小数", expression: "表达式", interval: "区间", set: "集合", equation_set: "解集", proof: "证明", derivation: "推导", short_text: "简答", matrix: "矩阵", vector: "向量", drawing: "作图" };
const STATUS_TEXT = { accepted: "✓ 正确", rejected: "✗ 不正确", partial: "◐ 部分得分", pending_review: "⏳ 待复核", invalid_response: "⚠ 格式无法解析", engine_error: "⚠ 判题服务异常", queued: "排队中" };

// ───────────────────────── auth ─────────────────────────
async function loadMe() {
  if (!state.token) { state.user = null; return renderAccount(); }
  try { state.user = await api("GET", "/me"); } catch { state.user = null; }
  renderAccount();
}
function isStaff() { return !!state.user && state.user.roles.some((r) => r !== "student"); }
function hasRole(...rs) { return !!state.user && state.user.roles.some((r) => rs.includes(r) || r === "admin"); }
function renderAccount() {
  const box = document.getElementById("account");
  document.querySelectorAll(".staff-only").forEach((el) => (el.hidden = !isStaff()));
  if (state.user) box.replaceChildren(h("span", {}, state.user.display_name), h("span", { class: "chip" }, state.user.roles.join(" · ")), h("button", { class: "btn sm", onclick: () => logout() }, "退出"));
  else box.replaceChildren(h("a", { href: "/login", "data-link": true, class: "btn sm primary" }, "登录 / 注册"));
}
function logout(silent) {
  if (state.token && !silent) api("POST", "/auth/logout").catch(() => {});
  state.token = null; state.user = null; sessionStorage.removeItem("lm_token"); renderAccount();
  if (!silent) navigate("/");
}
function viewLogin() {
  const u = h("input", { type: "text", autocomplete: "username", placeholder: "用户名", required: true });
  const p = h("input", { type: "password", autocomplete: "current-password", placeholder: "密码（≥8位）", required: true });
  const msg = h("p", { class: "muted small" });
  async function go(kind) {
    try {
      const r = await api("POST", "/auth/" + kind, { username: u.value.trim(), password: p.value });
      state.token = r.token; sessionStorage.setItem("lm_token", r.token); state.user = r.user; renderAccount();
      toast("欢迎，" + r.user.display_name); navigate(new URLSearchParams(location.search).get("next") || "/");
    } catch (e) { msg.textContent = errText(e); }
  }
  mount(h("div", { class: "panel", style: "max-width:420px;margin:40px auto" },
    h("h1", {}, "登录 LeetMath"),
    h("form", { class: "answer", onsubmit: (e) => { e.preventDefault(); go("login"); } }, u, p,
      h("div", { class: "row" }, h("button", { class: "btn primary", type: "submit" }, "登录"), h("button", { class: "btn", type: "button", onclick: () => go("register") }, "注册新账号"))),
    msg,
    h("details", { class: "small muted" }, h("summary", {}, "演示账号"),
      h("p", {}, "student / student-pass-123 · editor / editor-pass-123 · reviewer / reviewer-pass-123 · rights / rights-pass-123 · ops / ops-pass-123 · admin / admin-pass-123"))));
}

// ───────────────────────── problem list ─────────────────────────
async function knowledgeNodes() {
  if (!state.knowledge) state.knowledge = (await api("GET", "/knowledge")).releases;
  return state.knowledge;
}
async function viewProblems() {
  const q = new URLSearchParams(location.search);
  const f = {
    query: h("input", { type: "search", placeholder: "关键词 / 题号 / 知识点", value: q.get("query") || "", style: "min-width:220px" }),
    knowledge_id: h("select", {}, h("option", { value: "" }, "全部知识点")),
    difficulty_min: h("input", { type: "number", min: 1, max: 10, value: q.get("difficulty_min") || "", style: "width:70px" }),
    difficulty_max: h("input", { type: "number", min: 1, max: 10, value: q.get("difficulty_max") || "", style: "width:70px" }),
    response_type: h("select", {}, h("option", { value: "" }, "全部题型"), Object.entries(RT_LABEL).slice(0, 8).map(([k, v]) => h("option", { value: k }, v))),
    sort: h("select", {}, [["", "默认"], ["relevance", "相关度"], ["updated_desc", "最近更新"], ["difficulty_asc", "难度↑"], ["difficulty_desc", "难度↓"], ["display_id", "题号"]].map(([k, v]) => h("option", { value: k }, v))),
  };
  try {
    for (const rel of await knowledgeNodes()) for (const n of rel.nodes) f.knowledge_id.append(h("option", { value: n.id }, (n.parent_id ? "　" : "") + n.title));
  } catch {}
  for (const [k, el] of Object.entries(f)) if (el.tagName === "SELECT") el.value = q.get(k) || "";
  const apply = () => {
    const p = new URLSearchParams();
    for (const [k, el] of Object.entries(f)) if (el.value) p.set(k, el.value);
    navigate("/?" + p.toString());
  };
  const tbody = h("tbody");
  const more = h("button", { class: "btn", hidden: true }, "加载更多");
  const count = h("span", { class: "muted small" });
  let cursor = null, total = 0;
  async function load() {
    const p = new URLSearchParams(q); p.set("limit", "20"); if (cursor) p.set("cursor", cursor);
    try {
      const r = await api("GET", "/problems?" + p.toString());
      for (const it of r.items) {
        const st = it.attempted_state === "completed" ? h("span", { class: "chip green" }, "✓ 完成") : it.attempted_state === "attempted" ? h("span", { class: "chip amber" }, "做过") : "";
        tbody.append(h("tr", {},
          h("td", { class: "hide-sm muted small" }, it.display_id),
          h("td", {}, h("a", { href: "/problems/" + it.slug, "data-link": true }, it.title), " ", st,
            h("div", { class: "row small", style: "gap:6px;margin-top:2px" }, it.response_types.map((t) => h("span", { class: "chip" }, RT_LABEL[t] || t)))),
          h("td", {}, diffChip(it.difficulty)), h("td", { class: "hide-sm" }, it.part_count + " 问"),
          h("td", { class: "hide-sm small muted" }, (it.region_hints || []).join(" "))));
      }
      total += r.items.length;
      count.textContent = `已显示 ${total} 题`;
      cursor = r.next_cursor; more.hidden = !r.has_more;
      if (!total) tbody.append(h("tr", {}, h("td", { colspan: 5, class: "muted" }, "没有找到题目。试试移除部分筛选条件。", h("button", { class: "btn sm", onclick: () => navigate("/") }, "重置筛选"))));
    } catch (e) { tbody.append(h("tr", {}, h("td", { colspan: 5 }, errText(e), " ", h("button", { class: "btn sm", onclick: () => route() }, "重试")))); }
  }
  more.onclick = load;
  mount(
    h("div", { class: "row spread" }, h("h1", {}, "题库"), count),
    h("form", { class: "panel filters", onsubmit: (e) => { e.preventDefault(); apply(); } },
      h("label", {}, "搜索", f.query), h("label", {}, "知识点", f.knowledge_id), h("label", {}, "难度从", f.difficulty_min), h("label", {}, "到", f.difficulty_max),
      h("label", {}, "题型", f.response_type), h("label", {}, "排序", f.sort),
      h("button", { class: "btn primary", type: "submit" }, "筛选"), h("button", { class: "btn", type: "button", onclick: () => navigate("/") }, "重置")),
    h("table", { class: "list" }, h("thead", {}, h("tr", {}, h("th", { class: "hide-sm" }, "题号"), h("th", {}, "题目"), h("th", {}, "难度"), h("th", { class: "hide-sm" }, "小问"), h("th", { class: "hide-sm" }, "地区"))), tbody),
    h("div", { class: "row", style: "justify-content:center;margin-top:12px" }, more));
  await load();
}

// ───────────────────────── problem detail ─────────────────────────
async function viewProblem(slug) {
  let d;
  try { d = await api("GET", "/problems/" + encodeURIComponent(slug)); }
  catch (e) { return mount(h("div", { class: "panel" }, h("h1", {}, e.status === 404 ? "题目不存在或已下架" : "加载失败"), h("p", { class: "muted" }, errText(e)), h("a", { href: "/", "data-link": true }, "返回题库"))); }
  if (d.slug !== slug) history.replaceState(null, "", "/problems/" + d.slug);
  const rev = d.current_revision;
  const bm = h("button", { class: "btn sm" }, d.bookmarked ? "★ 已收藏" : "☆ 收藏");
  bm.onclick = async () => {
    if (!state.user) return navigate("/login?next=" + encodeURIComponent(location.pathname));
    try { await api(d.bookmarked ? "DELETE" : "PUT", "/me/bookmarks/" + d.id); d.bookmarked = !d.bookmarked; bm.textContent = d.bookmarked ? "★ 已收藏" : "☆ 收藏"; } catch (e) { toast(errText(e)); }
  };
  const partsBox = h("div");
  const nav = h("div", { class: "partnav", role: "tablist" });
  rev.parts.forEach((p, i) => {
    const prog = d.progress && d.progress.parts[p.id];
    const mark = prog ? (prog.accepted_count ? " ✓" : prog.latest_state === "pending_review" ? " ⏳" : " ·") : "";
    nav.append(h("button", { class: "btn sm" + (i === 0 ? " cur" : ""), role: "tab", onclick: (e) => {
      nav.querySelectorAll("button").forEach((b) => b.classList.remove("cur")); e.currentTarget.classList.add("cur");
      document.getElementById("part-" + p.id).scrollIntoView({ behavior: "smooth", block: "start" });
    } }, `第 ${p.part_key} 问${mark}`));
    partsBox.append(partView(d, rev, p));
  });
  const side = h("aside", { class: "side" }, h("div", { class: "panel" },
    h("h3", {}, "题目信息"),
    h("dl", { class: "kv" },
      h("dt", {}, "题号"), h("dd", {}, d.display_id), h("dt", {}, "版本"), h("dd", {}, "v" + rev.revision_no),
      h("dt", {}, "难度"), h("dd", {}, diffChip(rev.difficulty)), h("dt", {}, "总分"), h("dd", {}, rev.total_score),
      h("dt", {}, "知识点"), h("dd", {}, rev.knowledge.filter((k) => k.relation === "tested").map((k) => h("span", { class: "chip blue", style: "margin:0 4px 4px 0" }, k.title))),
      h("dt", {}, "来源"), h("dd", { class: "small" }, rev.source_attribution.map((s) => h("div", {}, s.attribution || `${s.source}${s.relation && s.relation !== "origin" ? "（" + s.relation + "）" : ""}`))),
      h("dt", {}, "更新"), h("dd", { class: "small muted" }, (rev.published_at || "").slice(0, 10))),
    d.progress ? h("p", { class: "small" }, `进度：${d.progress.parts_accepted}/${d.progress.part_count} 问已正确`) : h("p", { class: "small muted" }, "登录后可作答并记录进度"),
    rev.verified_exam ? null : h("p", { class: "small muted" }, "原创示例题，非官方真题")));
  mount(h("div", { class: "layout-detail" },
    h("div", {},
      h("div", { class: "panel" },
        h("div", { class: "row spread" }, h("div", { class: "muted small" }, d.display_id, " · ", rev.parts.length, " 个小问"), bm),
        h("h1", {}, rev.title),
        h("div", { class: "statement" }, rich(rev.shared_statement)), nav),
      partsBox),
    side));
}

function partView(d, rev, p) {
  const box = h("section", { class: "panel part", id: "part-" + p.id, "aria-label": "第" + p.part_key + "问" });
  const fb = h("div", { "aria-live": "polite" });
  const solBox = h("div");
  let input, getValue;
  const hint = p.input || {};
  if (p.options) {
    const name = "opt-" + p.id, multi = p.response_type === "multiple_choice";
    const wrap = h("div", { class: "options" }, p.options.map((o) => h("label", {}, h("input", { type: multi ? "checkbox" : "radio", name, value: o.id }), h("b", {}, o.id + "."), h("span", {}, rich(o.content)))));
    input = wrap;
    getValue = () => [...wrap.querySelectorAll("input:checked")].map((x) => x.value).join(",");
  } else if (["proof", "derivation", "short_text"].includes(p.response_type)) {
    input = h("textarea", { rows: 6, placeholder: "写出推导/证明过程（提交后由教师按评分点批改，不会自动判对错）", style: "font-family:inherit;font-size:15px" });
    getValue = () => input.value;
  } else {
    const ph = { expression: "例如 ln(x)+1-a 或 \\ln x+1-a", interval: "例如 (1,2] 或 (-∞,-2)∪[1,+∞)", set: "例如 {2,3}", equation_set: "例如 {2,3}", integer: "整数", rational: "例如 3/10", decimal: "数值" }[p.response_type] || "";
    const field = h("input", { type: "text", placeholder: ph, autocomplete: "off", spellcheck: "false", "aria-label": "答案" });
    const preview = h("div", { class: "preview", "aria-hidden": "true" });
    field.addEventListener("input", () => preview.replaceChildren(field.value ? mathEl(toPreviewLatex(field.value)) : ""));
    field.addEventListener("keydown", (e) => { if (e.key === "Enter") submit.click(); });
    input = h("div", { class: "answer" }, field, preview);
    getValue = () => field.value;
  }
  let pendingKey = null;  // reused when retrying after a network failure → server dedupes
  const submit = h("button", { class: "btn primary" }, "提交");
  submit.onclick = async () => {
    if (!state.user) return navigate("/login?next=" + encodeURIComponent(location.pathname));
    const val = getValue();
    if (!val || !val.trim()) { fb.replaceChildren(h("div", { class: "feedback invalid_response" }, "请先填写答案")); return; }
    submit.disabled = true; submit.textContent = "判题中…";
    try {
      let att = state.attempts[rev.id];
      if (!att) { att = (await api("POST", "/attempts", { problem_revision_id: rev.id, mode: "practice" }, { "Idempotency-Key": uuid() })).attempt_id; state.attempts[rev.id] = att; }
      pendingKey = pendingKey || uuid();
      const r = await api("POST", `/attempts/${att}/submissions`, { revision_part_id: p.id, response: { type: p.response_type, input: val } }, { "Idempotency-Key": pendingKey });
      pendingKey = null;
      const ev = r.evaluation;
      fb.replaceChildren(h("div", { class: "feedback " + ev.status },
        STATUS_TEXT[ev.status] || ev.status, ev.score !== null ? `　得分 ${ev.score} / ${ev.max_score}` : "", h("div", { class: "small", style: "font-weight:400" }, ev.message || ""),
        ev.regrade_eligible ? h("button", { class: "btn sm", style: "margin-top:6px", onclick: () => report(rev, p, ev.evaluation_id, "misjudged") }, "认为判错？申诉") : null));
      if (["accepted", "rejected", "partial", "pending_review"].includes(ev.status)) refreshSolutions(d, rev, p, solBox);
    } catch (e) {
      if (e.code !== "NETWORK") pendingKey = null;
      fb.replaceChildren(h("div", { class: "feedback rejected" }, errText(e), e.code === "NETWORK" ? "（内容已保留，可直接重试）" : ""));
    } finally { submit.disabled = false; submit.textContent = "提交"; }
  };
  const meta = [h("span", { class: "chip" }, RT_LABEL[p.response_type] || p.response_type), h("span", { class: "chip" }, p.max_score + " 分")];
  if (hint.variables && Object.keys(hint.variables).length) meta.push(h("span", { class: "chip blue", title: "变量与取值范围" }, "变量：" + Object.entries(hint.variables).map(([k, v]) => `${k}(${v})`).join(", ")));
  if (hint.grading_mode === "manual") meta.push(h("span", { class: "chip amber" }, "人工批改"));
  if (p.grading_suspended) meta.push(h("span", { class: "chip red" }, "自动判题已暂停"));
  box.append(h("h3", {}, `第 ${p.part_key} 问`, meta), h("div", { class: "statement" }, rich(p.prompt)), input,
    h("div", { class: "row" }, submit, h("button", { class: "btn sm", onclick: () => report(rev, p) }, "报告问题")), fb, solBox);
  showSolutions(p, solBox);
  return box;
}
function showSolutions(p, solBox) {
  if (p.solutions && p.solutions.length) solBox.replaceChildren(...p.solutions.map((s) => h("div", { class: "solution", style: "margin-top:12px" }, h("b", {}, s.type === "proof" ? "参考证明" : "参考解析"), h("ol", {}, s.steps.map((st) => h("li", {}, mixed(st)))))));
  else if (p.solutions_locked) solBox.replaceChildren(h("p", { class: "small muted" }, "提交后可查看解析"));
}
async function refreshSolutions(d, rev, p, solBox) {
  try { const nd = await api("GET", "/problems/" + d.slug); const np = nd.current_revision.parts.find((x) => x.id === p.id); if (np) showSolutions(np, solBox); } catch {}
}
async function report(rev, p, evaluationId, kind) {
  if (!state.user) return navigate("/login");
  const k = kind || prompt("问题类型：wrong_answer 答案错误 / ambiguous 题干歧义 / missing_image 图片缺失 / misjudged 判题误判 / typo 排版 / other", "ambiguous");
  if (!k) return;
  const desc = prompt("请简要描述问题：", "") ?? "";
  try { const r = await api("POST", "/content-reports", { problem_revision_id: rev.id, revision_part_id: p.id, evaluation_id: evaluationId || null, kind: k.trim(), description: desc }); toast(`已提交报告（${r.severity}），可在「我的 → 报告」查看处理状态`); }
  catch (e) { toast(errText(e)); }
}

// ───────────────────────── lists ─────────────────────────
async function viewLists(id) {
  if (id) {
    const c = await api("GET", "/collections/" + id).catch((e) => ({ error: e }));
    if (c.error) return mount(h("div", { class: "panel" }, errText(c.error)));
    return mount(h("h1", {}, c.title), h("p", { class: "muted" }, c.description),
      h("table", { class: "list" }, h("tbody", {}, c.items.map((it) => h("tr", {}, h("td", { class: "muted small" }, it.ordinal), h("td", { class: "muted small" }, it.display_id), h("td", {}, h("a", { href: "/problems/" + it.slug, "data-link": true }, it.title)), h("td", {}, diffChip(it.difficulty)))))));
  }
  const r = await api("GET", "/collections");
  mount(h("h1", {}, "题单"), h("div", { class: "cards" }, r.items.map((c) => h("a", { class: "card", href: "/lists/" + c.id, "data-link": true }, h("b", {}, c.title), h("span", { class: "muted small" }, c.description), h("span", { class: "chip" }, c.kind)))));
}

// ───────────────────────── me ─────────────────────────
async function viewMe(tab = "progress") {
  if (!state.user) return navigate("/login?next=/me");
  const tabs = [["progress", "进度"], ["submissions", "提交记录"], ["mistakes", "错题"], ["bookmarks", "收藏"], ["reports", "报告"]];
  const body = h("div");
  mount(h("h1", {}, "我的学习"), h("div", { class: "tabs" }, tabs.map(([k, v]) => h("a", { href: "/me/" + k, "data-link": true, class: k === tab ? "cur" : "" }, v))), body);
  try {
    if (tab === "progress") {
      const r = await api("GET", "/me/progress");
      body.append(h("div", { class: "panel" }, h("h2", {}, "按知识点"), h("p", { class: "small muted" }, r.note),
        r.knowledge.length ? r.knowledge.map((k) => h("div", { class: "meter" }, h("span", {}, k.title), h("div", { class: "bar" }, h("i", { style: `width:${Math.round((k.accuracy || 0) * 100)}%` })), h("span", { class: "small" }, `${k.parts_accepted}/${k.parts_attempted}${k.low_sample ? " · 样本少" : ""}`))) : h("p", { class: "muted" }, "还没有练习记录")),
        h("div", { class: "panel" }, h("h2", {}, "最近练习"), r.recent_attempts.map((a) => h("div", {}, a.available ? h("a", { href: "/problems/" + a.slug, "data-link": true }, a.title) : h("span", { class: "muted" }, a.display_id + "（题目已下架）"), h("span", { class: "muted small" }, "  " + a.started_at.slice(0, 16).replace("T", " "))))));
    } else if (tab === "submissions") {
      const r = await api("GET", "/me/submissions?limit=50");
      body.append(h("table", { class: "list" }, h("thead", {}, h("tr", {}, h("th", {}, "时间"), h("th", {}, "题目"), h("th", {}, "答案"), h("th", {}, "结果"))),
        h("tbody", {}, r.items.map((s) => h("tr", {}, h("td", { class: "small muted" }, s.created_at.slice(0, 16).replace("T", " ")),
          h("td", {}, s.problem.available ? h("a", { href: "/problems/" + s.problem.slug, "data-link": true }, s.problem.title) : h("span", { class: "muted" }, "题目已下架"), ` · 第${s.part_key}问 · v${s.revision_no}`, s.problem.superseded ? h("span", { class: "chip amber" }, "已有新版本") : ""),
          h("td", { class: "small" }, h("code", {}, s.response.input.slice(0, 60))),
          h("td", {}, h("span", { class: "feedback " + s.status, style: "padding:2px 8px" }, STATUS_TEXT[s.status] || s.status), s.score ? ` ${s.score}/${s.max_score}` : ""))))));
    } else if (tab === "mistakes") {
      const r = await api("GET", "/me/mistakes");
      body.append(r.items.length ? h("table", { class: "list" }, h("tbody", {}, r.items.map((m) => h("tr", {}, h("td", {}, m.available ? h("a", { href: "/problems/" + m.slug, "data-link": true }, m.title) : h("span", { class: "muted" }, "题目已下架"), ` · 第${m.part_key}问`, m.changed_since ? h("span", { class: "chip amber" }, `题目已从 v${m.revision_no} 更新到 v${m.current_revision_no}`) : ""), h("td", {}, h("button", { class: "btn sm", onclick: async () => { await api("DELETE", "/me/mistakes/" + m.revision_part_id); route(); } }, "移出错题")))))) : h("p", { class: "muted" }, "没有错题 🎉"));
    } else if (tab === "bookmarks") {
      const r = await api("GET", "/me/bookmarks");
      body.append(r.items.length ? h("ul", {}, r.items.map((b) => h("li", {}, b.available ? h("a", { href: "/problems/" + b.slug, "data-link": true }, b.title) : h("span", { class: "muted" }, b.display_id + "（题目已下架）")))) : h("p", { class: "muted" }, "还没有收藏"));
    } else if (tab === "reports") {
      const r = await api("GET", "/me/content-reports");
      body.append(h("table", { class: "list" }, h("tbody", {}, r.items.map((x) => h("tr", {}, h("td", {}, x.kind), h("td", {}, h("span", { class: "chip" }, x.severity)), h("td", {}, x.state), h("td", { class: "small" }, x.public_note || ""))))));
    }
  } catch (e) { body.append(h("p", {}, errText(e))); }
}

// ───────────────────────── reasoning practice ─────────────────────────
async function viewPractice() {
  const r = await api("GET", "/learning/catalog");
  const prof = state.user ? await api("GET", "/learning/profile").catch(() => null) : null;
  mount(h("div", { class: "row spread" }, h("h1", {}, "推理步骤训练"), state.user ? h("a", { href: "/profile", "data-link": true, class: "btn sm" }, "成长档案") : null),
    h("p", { class: "muted" }, "先在纸上想出下一步，再诚实地选「我知道 / 有些模糊 / 没想到」。这是主观自评，用来安排复习，不是考试分数；XP 与选项无关，诚实不会少拿。"),
    prof && prof.due_now ? h("div", { class: "panel row spread" }, h("span", {}, `有 ${prof.due_now} 张推理卡到期`), h("button", { class: "btn primary", onclick: () => startPractice(null, "due") }, "开始复习")) : null,
    h("div", { class: "cards" }, r.items.map((it) => h("div", { class: "card" }, h("span", { class: "muted small" }, it.display_id), h("b", {}, it.title),
      h("span", { class: "small" }, `${it.part_count} 问 · ${it.step_count} 个推理步骤 · 满分 ${it.max_score}`),
      h("button", { class: "btn primary", onclick: () => startPractice(it.revision_id, "full") }, "开始训练")))));
}
async function startPractice(revId, mode) {
  if (!state.user) return navigate("/login?next=/practice");
  try { const v = await api("POST", "/learning/attempts", { problem_revision_id: revId, mode }); navigate("/practice/" + v.attempt_id); }
  catch (e) { toast(errText(e)); }
}
async function viewAttempt(id) {
  if (!state.user) return navigate("/login?next=/practice");
  let v = await api("GET", "/learning/attempts/" + id);
  let xp = 0;
  const top = h("div", { class: "panel rp-top" });
  const left = h("ul", { class: "history" });
  const center = h("div", { class: "panel" });
  const statement = v.problem ? h("details", { class: "panel", open: true }, h("summary", {}, h("b", {}, v.problem.title)), h("div", { class: "statement" }, rich(v.problem.shared_statement)), v.problem.parts.map((p) => h("div", {}, h("b", {}, `(${p.part_key}) `), rich(p.prompt)))) : null;
  function paint(revealed) {
    const done = v.cards.filter((c) => c.reviewed).length;
    top.replaceChildren(h("b", {}, `步骤 ${Math.min(done + 1, v.cards.length)}/${v.cards.length}`), h("div", { class: "bar" }, h("i", { style: `width:${(100 * done) / v.cards.length}%` })),
      h("span", { title: v.score_label }, `自评 ${v.self_recall_score}/${v.self_recall_max}`), h("span", { class: "chip blue" }, `+${xp} XP`));
    left.replaceChildren(...v.cards.map((c, i) => h("li", { class: i === v.current_index ? "cur" : "" }, c.reviewed ? { know: "✓", fuzzy: "~", unsure: "?" }[c.rating] : "○", `(${c.part_key}) 步骤 ${c.order}`, c.criticality === "key" ? h("span", { class: "chip amber" }, "关键") : "")));
    if (revealed) return;
    const card = v.cards[v.current_index];
    if (!card) return paintEnd();
    const rate = (rating) => async () => {
      center.querySelectorAll(".rate button").forEach((b) => (b.disabled = true));
      try {
        const r = await api("POST", `/learning/attempts/${v.attempt_id}/step-reviews`, { event_id: uuid(), step_id: card.step_id, rating });
        xp += r.xp_awarded;
        v = await api("GET", "/learning/attempts/" + id);
        paint(true);
        center.append(h("div", { class: "reveal solution" }, h("b", {}, "参考推导"), mathEl(r.reference_latex, true), r.explanation ? h("p", { class: "small" }, r.explanation) : null,
          h("p", { class: "small muted" }, `自评得分 ${r.self_score}/${r.max_points} · 下次复习 ${r.next_due_at.slice(0, 10)}`),
          h("button", { class: "btn primary", onclick: () => paint(false) }, v.current_index === null ? "完成" : "下一步 →")));
      } catch (e) { toast(errText(e)); center.querySelectorAll(".rate button").forEach((b) => (b.disabled = false)); }
    };
    center.replaceChildren(h("div", { class: "muted small" }, `第 ${card.part_key} 问 · 步骤 ${card.order} · ${card.max_points} 分`, card.criticality === "key" ? " · 关键步骤" : ""),
      h("div", { class: "cue" }, mixed(card.recall_cue)), h("p", { class: "small muted" }, "先自己想（可以在纸上写），想好后再选择："),
      h("div", { class: "rate" }, h("button", { class: "btn", onclick: rate("know") }, "✓ 我知道"), h("button", { class: "btn", onclick: rate("fuzzy") }, "~ 有些模糊"), h("button", { class: "btn", onclick: rate("unsure") }, "? 没想到")));
  }
  function paintEnd() {
    if (v.mode !== "full" || v.state === "completed") {
      center.replaceChildren(h("h2", {}, "本轮完成"), h("p", {}, `自评 ${v.self_recall_score}/${v.self_recall_max}（主观参考，非正式成绩）`), h("a", { href: "/profile", "data-link": true, class: "btn primary" }, "查看成长档案"));
      return;
    }
    const sels = {};
    center.replaceChildren(h("h2", {}, "最后：知识点自评"), h("p", { class: "small muted" }, "1 = 完全不会，4 = 能独立讲清楚"),
      ...v.knowledge_codes.map((code) => { const s = h("select", {}, [1, 2, 3, 4].map((n) => h("option", { value: n }, n))); s.value = "3"; sels[code] = s; return h("div", { class: "row" }, h("span", { style: "width:180px" }, code), s); }),
      h("button", { class: "btn primary", onclick: async () => { const levels = {}; for (const [k, s] of Object.entries(sels)) levels[k] = Number(s.value); try { v = await api("POST", `/learning/attempts/${v.attempt_id}/knowledge-feedback`, { levels }); paintEnd(); } catch (e) { toast(errText(e)); } } }, "提交并完成"));
  }
  mount(top, statement, h("div", { class: "rp-grid" }, h("div", { class: "panel" }, h("h3", {}, "已完成步骤"), left), center));
  paint(false);
}
async function viewProfile() {
  if (!state.user) return navigate("/login?next=/profile");
  const p = await api("GET", "/learning/profile");
  mount(h("h1", {}, "成长档案"), h("p", { class: "muted small" }, p.label),
    h("div", { class: "grid2" },
      h("div", { class: "panel" }, h("h2", {}, "知识点证据指数"), p.knowledge.length ? p.knowledge.map((k) => h("div", { class: "meter" }, h("span", {}, k.title), h("div", { class: "bar" }, h("i", { style: `width:${k.evidence_index}%` })), h("span", { class: "small" }, `${k.evidence_index}${k.low_sample ? "*" : ""}`))) : h("p", { class: "muted" }, "暂无数据"), h("p", { class: "small muted" }, "* 观察次数少于 5，仅供参考")),
      h("div", {},
        h("div", { class: "panel" }, h("h2", {}, "复习"), h("p", {}, `到期 ${p.due_now} 张 · 已排程 ${p.scheduled} 张 · 累计 ${p.reviews_total} 次 · ${p.xp_total} XP`), p.due_now ? h("button", { class: "btn primary", onclick: () => startPractice(null, "due") }, "开始复习") : null),
        h("div", { class: "panel" }, h("h2", {}, "需要加强的关键步骤"), p.weak_key_steps.length ? h("ul", {}, p.weak_key_steps.map((w) => h("li", {}, mixed(w.recall_cue), " ", h("span", { class: "chip amber" }, w.rating)))) : h("p", { class: "muted" }, "暂无")))));
}

// ───────────────────────── admin ─────────────────────────
function adminTabs(cur) {
  const t = [["", "概览"], ["problems", "题目"], ["reviews", "审核"], ["grading", "人工批改"], ["imports", "导入"], ["duplicates", "疑似重复"], ["sources", "来源与授权"], ["reports", "举报"]];
  return h("div", { class: "tabs" }, t.map(([k, v]) => h("a", { href: "/admin" + (k ? "/" + k : ""), "data-link": true, class: k === cur ? "cur" : "" }, v)));
}
const issuesList = (issues) => h("ul", { class: "issues" }, issues.map((i) => h("li", { class: i.severity }, `[${i.severity === "blocking" ? "阻断" : "警告"}] ${i.code} ${i.path} — ${i.message}`)));

async function viewAdmin(sub, arg) {
  if (!isStaff()) return mount(h("div", { class: "panel" }, "需要后台权限。", h("a", { href: "/login?next=/admin", "data-link": true }, "登录")));
  const body = h("div");
  mount(h("h1", {}, "内容后台"), adminTabs(sub || ""), body);
  try {
    if (!sub) {
      const d = await api("GET", "/admin/dashboard");
      const stat = (label, v) => h("div", { class: "card" }, h("span", { class: "muted small" }, label), h("b", { style: "font-size:24px" }, v ?? 0));
      body.append(h("div", { class: "cards" }, stat("已发布", d.revisions_by_status.published), stat("草稿", d.revisions_by_status.draft), stat("待数学审核", d.pending_math_review), stat("待版权审核", d.pending_rights_review),
        stat("疑似重复积压", d.duplicate_backlog), stat("待人工批改", d.pending_manual_grading), stat("版权冻结题目", d.held_problems), stat("30 天内到期授权", d.rights_expiring_30d.length)),
        h("div", { class: "panel", style: "margin-top:16px" }, h("h3", {}, "导入行状态"), h("pre", { class: "code" }, JSON.stringify(d.import_rows_by_state, null, 2))));
    } else if (sub === "problems") await adminProblems(body);
    else if (sub === "edit") await adminEdit(body, arg);
    else if (sub === "reviews") await adminReviews(body);
    else if (sub === "grading") await adminGrading(body);
    else if (sub === "imports") await adminImports(body, arg);
    else if (sub === "duplicates") await adminDuplicates(body);
    else if (sub === "sources") await adminSources(body);
    else if (sub === "reports") await adminReports(body);
  } catch (e) { body.append(h("p", { class: "feedback rejected" }, errText(e))); }
}
async function adminProblems(body) {
  const q = new URLSearchParams(location.search);
  const r = await api("GET", "/admin/problems?" + (q.get("status") ? "status=" + q.get("status") : ""));
  const statusSel = h("select", { onchange: (e) => navigate("/admin/problems" + (e.target.value ? "?status=" + e.target.value : "")) }, ["", "draft", "in_math_review", "in_rights_review", "approved", "published", "archived", "retracted"].map((s) => h("option", { value: s }, s || "全部状态")));
  statusSel.value = q.get("status") || "";
  body.append(h("div", { class: "row spread", style: "margin-bottom:10px" }, statusSel, hasRole("editor") ? h("button", { class: "btn primary", onclick: newProblem }, "新建题目") : null),
    h("table", { class: "list" }, h("thead", {}, h("tr", {}, ["题号", "标题", "版本", "状态", ""].map((x) => h("th", {}, x)))),
      h("tbody", {}, r.items.map((x) => h("tr", {}, h("td", { class: "small" }, x.display_id), h("td", {}, x.title, x.is_current_public ? h("span", { class: "chip green" }, "线上") : "", x.takedown_hold ? h("span", { class: "chip red" }, "版权冻结") : "", x.visibility === "private" ? h("span", { class: "chip" }, "私有") : ""),
        h("td", {}, "v" + x.revision_no), h("td", {}, h("span", { class: "chip" }, x.status)), h("td", {}, h("a", { href: "/admin/edit/" + x.revision_id, "data-link": true }, "打开")))))));
}
async function newProblem() {
  const tpl = { schema_version: "1.0.0", problem: { grade_band: "senior_high", subject: "mathematics" },
    revision: { locale: "zh-CN", title: "新题目", shared_statement: { blocks: [{ type: "paragraph", spans: [{ type: "text", text: "已知函数 " }, { type: "inline_math", latex: "f(x)=x^2-2x" }, { type: "text", text: "。" }] }] },
      content_metadata: { region_hints: ["CN-SH"], platform_difficulty: { value: 2, origin: "editor" }, curriculum_mappings: [{ curriculum_code: "CN-SH-SENIOR-HIGH", release_code: "DEMO-2026", knowledge_code: "DERIV-RULES", relation_type: "tested" }] },
      parts: [{ part_key: "1", display_order: 1, response_type: "expression", max_score: "4.00", prompt: { blocks: [{ type: "paragraph", spans: [{ type: "text", text: "求 " }, { type: "inline_math", latex: "f'(x)" }] }] },
        answer_spec: { spec_version: 1, grading_mode: "automatic", checker_type: "symbolic_equivalence", expected: "2x-2", assumptions: { x: "real" } },
        solutions: [{ type: "worked", review_state: "unreviewed", steps: ["f'(x)=2x-2"] }] }] },
    source_record_refs: [{ source_code: "leetmath-original-demo", external_id: "cms-" + Date.now() }], rights_policy_ref: "sample-original-internal-review-required" };
  try { const r = await api("POST", "/admin/problems", { document: tpl }); navigate("/admin/edit/" + r.revision_id); } catch (e) { toast(errText(e)); }
}
async function adminEdit(body, rid) {
  const r = await api("GET", "/admin/problem-revisions/" + rid);
  let lock = r.lock_version;
  const ta = h("textarea", { rows: 28, spellcheck: "false" }); ta.value = JSON.stringify(r.document, null, 2);
  const out = h("div");
  const parse = () => { try { return JSON.parse(ta.value); } catch (e) { out.replaceChildren(h("p", { class: "feedback rejected" }, "JSON 语法错误：" + e.message)); return null; } };
  const act = (label, fn, cls = "btn") => h("button", { class: cls, onclick: async () => { try { await fn(); } catch (e) { out.replaceChildren(h("div", { class: "feedback rejected" }, errText(e)), e.details && e.details.issues ? issuesList(e.details.issues) : ""); } } }, label);
  const flow = (path, extra) => async () => { const res = await api("POST", `/admin/problem-revisions/${rid}/${path}`, extra || {}); toast("状态：" + res.status); route(); };
  const editable = r.status === "draft";
  const actions = [];
  actions.push(act("预检", async () => { const d = parse(); if (!d) return; const res = await api("POST", "/admin/preflight", { document: d }); out.replaceChildren(h("div", { class: "feedback " + (res.ok ? "accepted" : "rejected") }, res.ok ? "无阻断项" : "存在阻断项"), issuesList(res.issues)); }));
  if (editable && hasRole("editor")) {
    actions.push(act("保存草稿", async () => { const d = parse(); if (!d) return; const res = await api("PATCH", "/admin/problem-revisions/" + rid, { document: d }, { "If-Match": `"${lock}"` }); lock = res.lock_version; toast("已保存（版本锁 " + lock + "）"); }, "btn primary"));
    actions.push(act("送审", flow("submit-review")));
  }
  if (["in_math_review", "in_rights_review"].includes(r.status) && hasRole("reviewer", "rights_reviewer")) {
    actions.push(act(r.status === "in_math_review" ? "数学审核通过" : "版权审核通过", flow("approve"), "btn primary"));
    actions.push(act("驳回", async () => { const reason = prompt("驳回原因（必填）："); if (reason) await flow("reject", { reason })(); }, "btn danger"));
  }
  if (r.status === "approved" && hasRole("reviewer")) actions.push(act("发布", flow("publish"), "btn primary"));
  if (r.status === "published" && hasRole("reviewer", "rights_reviewer")) actions.push(act("撤稿", async () => { const reason = prompt("撤稿原因（必填）："); if (reason) await flow("retract", { reason })(); }, "btn danger"));
  if (["published", "archived", "retracted"].includes(r.status) && hasRole("editor")) actions.push(act("基于此创建新修订", async () => { const res = await api("POST", `/admin/problems/${r.problem_id}/revisions`); navigate("/admin/edit/" + res.revision_id); }));
  if (r.status === "published" && hasRole("rights_reviewer")) actions.push(act(r.takedown_hold ? "解除版权冻结" : "版权冻结", async () => { const reason = prompt("原因："); if (reason) { await api("POST", `/admin/problems/${r.problem_id}/rights-hold`, { hold: !r.takedown_hold, reason }); route(); } }, "btn danger"));
  body.append(h("div", { class: "panel" },
    h("div", { class: "row spread" }, h("h2", {}, `${r.display_id} · v${r.revision_no} · ${r.title}`), h("span", { class: "chip" }, r.status)),
    r.review_note ? h("p", { class: "feedback partial" }, "审核意见：" + r.review_note) : null,
    !editable ? h("p", { class: "small muted" }, "非草稿状态：内容只读（已发布版本不可原地修改，请创建新修订）。") : null,
    h("div", { class: "row", style: "margin:10px 0" }, actions), out, ta),
    h("div", { class: "panel" }, h("h3", {}, "工作流记录"), h("ul", { class: "small" }, r.workflow.map((w) => h("li", {}, `${w.at.slice(0, 19).replace("T", " ")}  ${w.from} → ${w.to}  ${w.reason || ""}`)))));
}
async function adminReviews(body) {
  for (const [stage, label] of [["math", "待数学审核"], ["rights", "待版权审核"], ["publish", "待发布"]]) {
    const r = await api("GET", "/admin/reviews?stage=" + stage).catch(() => ({ items: [] }));
    body.append(h("div", { class: "panel" }, h("h3", {}, `${label}（${r.items.length}）`), r.items.length ? h("table", { class: "list" }, h("tbody", {}, r.items.map((x) => h("tr", {}, h("td", {}, x.display_id), h("td", {}, h("a", { href: "/admin/edit/" + x.revision_id, "data-link": true }, x.title)), h("td", { class: "small muted" }, `${x.age_hours} 小时`), h("td", {}, x.is_own ? h("span", { class: "chip amber" }, "本人创建，不可审批") : ""))))) : h("p", { class: "muted small" }, "队列为空")));
  }
}
async function adminGrading(body) {
  const r = await api("GET", "/admin/grading-queue");
  if (!r.items.length) return body.append(h("p", { class: "muted" }, "没有待批改的提交"));
  for (const it of r.items) {
    const score = h("input", { type: "text", value: "", placeholder: "分数", style: "width:80px" });
    const reason = h("input", { type: "text", placeholder: "评语/理由（必填）", style: "flex:1" });
    const crit = (it.problem.rubric && it.problem.rubric.criteria) || [];
    const boxes = crit.map((c) => h("label", { class: "small", style: "display:block" }, h("input", { type: "checkbox", value: c.id, onchange: () => { score.value = boxes.filter((b) => b.querySelector("input").checked).reduce((a, b) => a + Number(crit.find((c2) => c2.id === b.querySelector("input").value).max_points), 0).toFixed(2); } }), ` ${c.id}（${c.max_points}）${c.description}`));
    const send = async () => {
      const s = Number(score.value), max = Number(it.problem.max_score);
      const st = s >= max ? "accepted" : s > 0 ? "partial" : "rejected";
      try { await api("POST", `/admin/submissions/${it.submission_id}/evaluations`, { state: st, score: s.toFixed(2), reason: reason.value, matched_criteria: boxes.filter((b) => b.querySelector("input").checked).map((b) => b.querySelector("input").value) }); toast("已批改"); route(); } catch (e) { toast(errText(e)); }
    };
    body.append(h("div", { class: "panel" }, h("div", { class: "muted small" }, `${it.problem.title} · v${it.problem.revision_no} · 第${it.problem.part_key}问 · 满分 ${it.problem.max_score} · ${it.result_code}`),
      h("div", { class: "statement" }, rich(it.problem.prompt)), h("h3", {}, "学生作答"), h("pre", { class: "code", style: "white-space:pre-wrap" }, it.response.input),
      it.problem.expected ? h("p", { class: "small" }, "参考答案：", mathEl(String(it.problem.expected))) : null, h("h3", {}, "评分点"), boxes,
      it.own_submission ? h("p", { class: "chip amber" }, "本人提交，不可批改") : h("div", { class: "row" }, score, reason, h("button", { class: "btn primary", onclick: send }, "提交评分"))));
  }
}
async function sha256Hex(text) { const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)); return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join(""); }
async function adminImports(body, bid) {
  if (bid) {
    const b = await api("GET", "/admin/imports/" + bid); const rows = await api("GET", `/admin/imports/${bid}/rows`);
    const dl = async () => { const res = await fetch(`/api/v1/admin/imports/${bid}/rows?format=csv`, { headers: { Authorization: "Bearer " + state.token } }); const blob = await res.blob(); const a = h("a", { href: URL.createObjectURL(blob), download: `import-${bid}.csv` }); a.click(); };
    return body.append(h("div", { class: "panel" }, h("h2", {}, `批次 ${b.dataset}`), h("p", { class: "small" }, `${b.status} · ${b.dry_run ? "预检（不落库）" : "正式导入"} · adapter ${b.adapter_version}`), h("pre", { class: "code" }, JSON.stringify(b.counts, null, 2)),
      h("div", { class: "row" }, h("button", { class: "btn", onclick: dl }, "导出逐行报告 CSV"), h("button", { class: "btn", onclick: async () => { await api("POST", `/admin/imports/${bid}/retry-failed`); route(); } }, "重试失败行"))),
      h("table", { class: "list" }, h("thead", {}, h("tr", {}, ["行", "外部键", "状态", "阶段", "错误", "详情"].map((x) => h("th", {}, x)))), h("tbody", {}, rows.items.map((r) => h("tr", {}, h("td", {}, r.row_no), h("td", { class: "small" }, r.source_record_key || ""), h("td", {}, h("span", { class: "chip " + ({ new_record: "green", retained: "", duplicate_candidate: "amber", rejected: "red", failed: "red", quarantined: "red" }[r.state] || "") }, r.state)), h("td", {}, r.stage), h("td", { class: "small" }, r.error_code || ""), h("td", { class: "small" }, h("code", {}, JSON.stringify(r.error_detail || {}).slice(0, 160))))))));
  }
  const man = h("textarea", { rows: 12 });
  man.value = JSON.stringify({ manifest_schema_version: "1.0", source_code: "demo-partner-csv", dataset_id: "partner-demo", dataset_version: "2026-11-v1", locale: "zh-CN", rights_grant_ref: "demo-partner-2026", input_format: "csv", adapter_version: "csv-simple-v1", normalizer_version: "math-normalizer-v1", dry_run: true, files: [{ path: "partner.csv", sha256: "" }] }, null, 2);
  const fname = h("input", { type: "text", value: "partner.csv" });
  const content = h("textarea", { rows: 8 });
  content.value = "external_id,version,title,region,statement,part_key,prompt,response_type,max_score,checker_type,expected,assumptions,knowledge_code,difficulty,curriculum_code,release_code\nP-100,1,二次函数求导（合作方示例）,CN-SH,已知 $g(x)=x^2+2x$,1,求 $g'(x)$,expression,4,symbolic_equivalence,2x+2,\"{\"\"x\"\":\"\"real\"\"}\",DERIV-RULES,2,CN-SH-SENIOR-HIGH,DEMO-2026\nP-100,1,二次函数求导（合作方示例）,CN-SH,,2,求 $g(x)$ 的最小值,integer,2,integer_exact,-1,,,,,\n";
  const out = h("div");
  const send = async (dry) => {
    try {
      const m = JSON.parse(man.value); m.dry_run = dry;
      m.files = [{ path: fname.value, sha256: await sha256Hex(content.value) }]; man.value = JSON.stringify(m, null, 2);
      const r = await api("POST", dry ? "/admin/imports/dry-run" : "/admin/imports", { manifest: m, files: { [fname.value]: content.value } });
      navigate("/admin/imports/" + r.batch_id);
    } catch (e) { out.replaceChildren(h("div", { class: "feedback rejected" }, errText(e)), h("pre", { class: "code" }, JSON.stringify(e.details || {}, null, 2))); }
  };
  const list = await api("GET", "/admin/imports").catch(() => ({ items: [] }));
  body.append(h("div", { class: "grid2" },
    h("div", { class: "panel" }, h("h2", {}, "新建导入批次"), h("p", { class: "small muted" }, "sha256 自动计算并写回 manifest；同一 manifest 重复提交会返回原批次（幂等）。"), h("label", { class: "small" }, "Manifest"), man, h("label", { class: "small" }, "文件名"), fname, h("label", { class: "small" }, "文件内容（CSV / JSONL）"), content,
      h("div", { class: "row", style: "margin-top:8px" }, h("button", { class: "btn", onclick: () => send(true) }, "预检 dry-run"), h("button", { class: "btn primary", onclick: () => send(false) }, "正式导入")), out),
    h("div", { class: "panel" }, h("h2", {}, "最近批次"), h("ul", {}, list.items.map((b) => h("li", {}, h("a", { href: "/admin/imports/" + b.batch_id, "data-link": true }, b.dataset), ` · ${b.status}${b.dry_run ? " · dry-run" : ""} · ${JSON.stringify(b.counts)}`))))));
}
async function adminDuplicates(body) {
  const r = await api("GET", "/admin/duplicates");
  if (!r.items.length) return body.append(h("p", { class: "muted" }, "没有待处理的疑似重复"));
  for (const c of r.items) {
    const decide = (decision) => async () => { const reason = prompt("决定理由（必填）："); if (!reason) return; try { await api("POST", `/admin/duplicates/${c.id}/resolve`, { decision, reason }); toast("已处理"); route(); } catch (e) { toast(errText(e)); } };
    const stmt = (doc) => doc ? h("div", { class: "statement small" }, rich(doc.revision.shared_statement), doc.revision.parts.map((p) => h("div", {}, `(${p.part_key}) `, rich(p.prompt)))) : "";
    body.append(h("div", { class: "panel" }, h("div", { class: "row spread" }, h("b", {}, `${c.level} · 相似度 ${c.score}`), h("span", { class: "small muted" }, JSON.stringify(c.signals))),
      h("div", { class: "grid2" }, h("div", {}, h("h3", {}, `新记录：${c.left.source} / ${c.left.external_id}@${c.left.external_revision}`), stmt(c.left.document)), h("div", {}, h("h3", {}, `已有题目：${c.right.display_id}`), stmt(c.right.document))),
      h("div", { class: "row" }, h("button", { class: "btn", onclick: decide("exact_duplicate") }, "确认完全重复（映射，保留来源）"), h("button", { class: "btn", onclick: decide("isomorphic_to") }, "同构/换参"), h("button", { class: "btn", onclick: decide("adapted_from") }, "改编"), h("button", { class: "btn", onclick: decide("independent") }, "独立题目"), h("button", { class: "btn", onclick: decide("defer") }, "延后"))));
  }
}
async function adminSources(body) {
  const r = await api("GET", "/admin/sources");
  body.append(h("table", { class: "list" }, h("thead", {}, h("tr", {}, ["来源", "类型", "记录数", "授权"].map((x) => h("th", {}, x)))),
    h("tbody", {}, r.items.map((s) => h("tr", {}, h("td", {}, h("b", {}, s.code), h("div", { class: "small muted" }, s.name)), h("td", {}, s.kind, s.status !== "active" ? h("span", { class: "chip red" }, s.status) : ""), h("td", {}, s.record_count),
      h("td", {}, s.grants.map((g) => h("div", { class: "small" }, h("span", { class: "chip " + (g.display_ok ? "green" : "red") }, g.display_ok ? "可展示" : g.display_reason), ` ${g.code} · ${g.permitted_actions.join("/")} · ${g.valid_to ? "至 " + g.valid_to.slice(0, 10) : "长期"}`))))))));
}
async function adminReports(body) {
  const r = await api("GET", "/admin/content-reports");
  if (!r.items.length) return body.append(h("p", { class: "muted" }, "没有未处理的举报"));
  body.append(h("table", { class: "list" }, h("tbody", {}, r.items.map((x) => h("tr", {}, h("td", {}, h("span", { class: "chip " + (x.severity === "P0" ? "red" : "amber") }, x.severity)), h("td", {}, x.kind), h("td", { class: "small" }, x.description),
    h("td", {}, h("button", { class: "btn sm", onclick: async () => { const note = prompt("公开处理说明："); if (note === null) return; await api("POST", `/admin/content-reports/${x.id}/resolve`, { state: "resolved", resolution: "handled", public_note: note }); route(); } }, "标记已处理")))))));
}

// ───────────────────────── router ─────────────────────────
function navigate(url) { history.pushState(null, "", url); route(); }
async function route() {
  const path = location.pathname.replace(/\/+$/, "") || "/";
  document.querySelectorAll(".mainnav a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "/" ? path === "/" || path.startsWith("/problems") : path.startsWith(a.getAttribute("href"))));
  const m = (re) => path.match(re);
  let r;
  try {
    if (path === "/") await viewProblems();
    else if ((r = m(/^\/problems\/([^/]+)$/))) await viewProblem(decodeURIComponent(r[1]));
    else if (path === "/login") viewLogin();
    else if ((r = m(/^\/lists(?:\/([^/]+))?$/))) await viewLists(r[1]);
    else if ((r = m(/^\/me(?:\/(\w+))?$/))) await viewMe(r[1]);
    else if (path === "/practice") await viewPractice();
    else if ((r = m(/^\/practice\/([\w-]+)$/))) await viewAttempt(r[1]);
    else if (path === "/profile") await viewProfile();
    else if ((r = m(/^\/admin(?:\/(\w+))?(?:\/([\w-]+))?$/))) await viewAdmin(r[1], r[2]);
    else mount(h("div", { class: "panel" }, h("h1", {}, "页面不存在"), h("a", { href: "/", "data-link": true }, "返回题库")));
  } catch (e) { mount(h("div", { class: "panel" }, h("h1", {}, "出错了"), h("p", {}, errText(e)))); }
}
document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-link]");
  if (a && !e.metaKey && !e.ctrlKey && a.origin === location.origin) { e.preventDefault(); navigate(a.getAttribute("href")); }
});
window.addEventListener("popstate", route);
(async () => { await loadMe(); route(); })();
