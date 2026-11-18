# 缺陷报告与修复记录｜2026-11-18（Pi Agent 本机验收）

基线 `08caab892daded21139a91b05fa461460d7ff0e1` → 修复分支 `fix/pi-local-n2-validation-20261118`。
每个缺陷都先复现、再定位根因、再最小修复 + 回归测试，最后在同一提交树重跑全量。

| ID | 优先级 | 模块 | 摘要 | 提交 |
|---|---|---|---|---|
| LM-LOCAL-001 | P0 | 前端 CMS + 浏览器 E2E | RichText 字段名跨区域重复导致 Playwright strict mode 失败 | `bce9ac2`（测试）+ `27a5485`（产品） |
| LM-LOCAL-002 | P1 | 前端 CMS diff | 「相对上一版本的差异」把 revision 行身份当内容变更 | `e40e9c8` |
| LM-LOCAL-003 | P0 | 前端布局 | 375px 下长不可断行文本撑开整页横向滚动 | `9031b6c` |
| LM-LOCAL-004 | P0 | 前端认证 | SPA 登出后重新登录 403（CSRF 缓存竞态） | `0401d97` |
| 环境修复 | P2 | 交付 | `.gitignore` 忽略 `artifacts/` 本地证据目录 | `8a15ffc` |

---

## LM-LOCAL-001｜RichText 字段名跨区域重复（阻断 CI 与全部浏览器验收）

- **优先级**：P0（阻塞 N2 完成判据中的浏览器 E2E 全部条目）
- **影响模块**：`frontend/cms-editor.js`、`backend/tests/test_browser_e2e.py`、CI quality job
- **运行环境**：本机 Chromium 159 / 前端源码直接由 Uvicorn 服务；CI ubuntu-latest 同样复现
- **复现步骤**：
  1. `LEETMATH_RUN_BROWSER_TESTS=1 LEETMATH_REQUIRE_BROWSER=1 PYTHONPATH=backend pytest -q backend/tests/test_browser_e2e.py`
  2. 进入 `test_teacher_full_review_publish_revision_and_cookie_flow`，在结构化表单中定位「行内公式 LaTeX #2」
- **预期**：定位到公共题干区块中的行内公式输入并填入 LaTeX
- **实际**：`playwright._impl._errors.Error: Locator.fill: Error: strict mode violation: get_by_label("行内公式 LaTeX #2") resolved to 2 elements`（公共题干区块 + 小问 1 题干），测试中止；CI 同步失败（Run 44095520961，`1 failed, 12 passed`）
- **证据**：
  - `artifacts/local-validation/2026-11-18/pytest-browser-before-fix.txt`
  - 真实 DOM 快照 `artifacts/local-validation/2026-11-18/cms-dom-before-fix.json`：两个 `section.cms-rich` 的字段名为
    `['正文 #1','行内公式 LaTeX #2','正文 #3']` 与 `['正文 #1','行内公式 LaTeX #2']`，重复项 `[['正文 #1',2],['行内公式 LaTeX #2',2]]`，且区域无 `data-cms-scope`、无 `aria-label`
  - 截图 `cms-dom-before-fix.png`
- **根因**：`richEditor(label, rt)` 用「片段类型 + 块内下标」生成可访问名（`行内公式 LaTeX #2`），而每个 RichText 区域（公共题干、每个小问题干）都会重新从 `#1` 开始编号；同一 accessible name 在同一文档中出现多次，Playwright strict mode 拒绝歧义定位。测试此前改用 `.first` 掩盖部分歧义（`正文 #1`），但 `行内公式 LaTeX #2` 无 `.first`，因此失败。同一问题也是可访问性缺陷：两个区域含同名控件却无区域名称。
- **涉及文件与函数**：`frontend/cms-editor.js::createForm/richEditor`、`frontend/app.js`（状态/预检/错误钩子）、`backend/tests/test_browser_e2e.py::test_teacher_full_review_publish_revision_and_cookie_flow`
- **修复方案**（产品 + 测试，不使用位置下标）：
  - `section.cms-rich` 增加稳定的机器名 `data-cms-scope`（`revision.shared_statement` / `revision.parts.<part_key>.prompt`）与 `aria-label`；
  - `section.cms-part` 增加 `data-cms-part-key` 与 `aria-label`；
  - 编辑页状态徽章加 `data-revision-status`，预检反馈加 `data-preflight-state`，动作错误加 `data-action-error`（避免用子串文本同时命中审计列表与 toast）；
  - 测试改为「先限定区域，再按字段名定位」，并断言两个区域的 scope 顺序；删除对 `.first` 的依赖。
- **新增/修改的测试**：浏览器用例内部断言 `[...section.cms-rich].map(data-cms-scope) == ["revision.shared_statement","revision.parts.1.prompt"]`；4 处基于子串文本的等待改为基于 `data-revision-status` / `data-preflight-state` 的确定性等待（**更严格**，未删除任何断言）。
- **修复前验证**：`1 failed, 2 passed`（本机，见 pytest-browser-before-fix.txt）
- **修复后验证**：`3 passed`；与 auth/rate-limit 合并的 CI parity 命令 `13 passed`
- **遗留风险**：区域 scope 以 `part_key` 命名，若未来允许同一 revision 内重复 `part_key`，scope 会冲突（当前 `part_key` 在 revision 内唯一，且 `addPart` 保证唯一）。

## LM-LOCAL-002｜新修订的「相对上一版本的差异」把行身份算作内容变更

- **优先级**：P1（教学编辑可用性 + N2 判据「新 revision diff 正确」）
- **影响模块**：`frontend/cms-editor.js::changes`、`frontend/app.js::updateDiff/showDiff`
- **运行环境**：本机 Chromium（Compose 栈与 E2E 内嵌 Uvicorn 均可复现）
- **复现步骤**：发布一个修订 → 「基于此创建新修订」→ 观察「差异审阅」面板
- **预期**：未做任何编辑时显示 0 处变更；改标题后显示 1 处
- **实际**：立即显示 `相对上一版本的差异 · 4 处`，改标题后 `· 5 处`
- **证据**：Playwright trace DOM 快照中 4 条差异路径为
  `$.revision.id`、`$.revision.revision_no`(1→2)、`$.revision.status`("published"→"draft")、`$.revision.parts[0].id`（`artifacts/e2e/teacher-review-publish.trace.zip`，本轮已解析为文本证据）
- **根因**：`changes(before, after)` 对整份 Contract 文档做叶子级比较，未排除**每行存储身份/状态**字段；新建修订必然在这些字段上与父版本不同，且 `revision.parts[i].id` 是版本化小问的行 ID。
- **涉及文件与函数**：`frontend/cms-editor.js::changes`（新增 `IGNORED_DIFF_PATHS`）
- **修复方案**：`changes()` 忽略 `$.revision.id`、`$.revision.revision_no`、`$.revision.status`、`$.revision.parts[i].id`，其余（含新增/删除区块、删除字段）照旧上报。该函数同时被「送审前有未保存变更」守卫使用，守卫比较的是同一文档的两个快照，行为不变。
- **新增/修改的测试**：`frontend/tests/cms-editor.test.cjs` 新增 2 例——(a) 新修订（新行 ID/新编号/draft 状态）产出 0 处变更；(b) 在新修订上改标题恰好产出 1 条且路径为 `$.revision.title`；浏览器用例新增 `· 0 处` → `· 1 处` 断言。
- **修复前验证**：trace 显示 `· 4 处`；Node 用例在修复前不存在（新增即为回归）
- **修复后验证**：`node --test` → `pass 7 / fail 0`；浏览器用例通过并断言 0 处/1 处
- **遗留风险**：若后端未来把更多「非内容」字段放进文档（如 `lock_version`、时间戳），需要同步扩充忽略列表；建议后端标注哪些字段属于身份/状态。

## LM-LOCAL-003｜375px 下长不可断行文本撑开整页

- **优先级**：P0（docs/15 §7「375px 页面渲染正常，无重大整体溢出」）
- **影响模块**：`frontend/style.css`
- **运行环境**：Compose 栈 + Chromium 375×812
- **复现步骤**：发布标题包含长不可断行片段（如 `<img src=x onerror=window.__leetmathXss=1>` 作为纯文本）的题目，
  在 375px 打开 `/problems/lm-sh-000016`
- **预期**：`document.documentElement.scrollWidth <= 375`
- **实际**：`{'width': 375, 'document': 437, 'body': 437}`（Playwright 断言失败）
- **证据**：`artifacts/local-validation/2026-11-18/overflow-lm-sh-000016-375.png`；度量脚本输出显示最宽元素为
  `h1 clientWidth=305 / scrollWidth=402`，其父 `.panel`/`main`/`body`/`html` 依次继承 437
- **根因**：`body` 及内容容器允许在 CJK 文本中折行，但无法在长 ASCII 串（粘贴的标签、外部键、URL）内部断行；
  标题 `h1` 没有 `overflow-wrap`，单个 token 直接决定容器的 min-content 宽度 → 整页横向滚动。
  既有 N2 CSS 已覆盖 `.statement`、`.kv dd`、表格与 `.cms-preview`，遗漏了标题。
- **涉及文件与函数**：`frontend/style.css`（`body { overflow-wrap: anywhere; }`）
- **修复方案**：在 `body` 允许「最后手段」在不可断行串内断行，使文本在本地折行而不是撑开页面；保持 docs/15 §2.3
  「把宽内容限制在局部容器内，而不是用 `overflow-x: hidden` 隐藏整页布局错误」的原则（未使用 `hidden` 掩盖）。
- **新增/修改的测试**：浏览器用例在溢出断言失败时输出超宽元素清单（`_overflow_report`）；375/768/1280 三组页面继续断言 `scrollWidth <= innerWidth`。
- **修复前验证**：437 > 375（失败）
- **修复后验证**：同一页面 375px → 375；768/1280 无变化；响应式扫描 24/24 通过
- **遗留风险**：`overflow-wrap: anywhere` 影响全站文本的 min-content 计算，极端情况下会让长英文单词在窄容器内断开（可接受的取舍，已在报告登记）。

## LM-LOCAL-004｜SPA 登出后重新登录返回 403（CSRF 缓存竞态）

- **优先级**：P0（docs/15 §3.4「SPA 登出后可无整页刷新重新登录」；真实用户一旦登出必须能重新登录）
- **影响模块**：`frontend/app.js`（`logout`、`csrfToken`、`api`）
- **运行环境**：本机 Chromium + Uvicorn + Redis（真实 HTTP）
- **复现步骤**：登录 → 在 SPA 内点「退出」→ 点「登录 / 注册」→ 填写同一账号 → 提交（不刷新页面）
- **预期**：登录成功，出现「后台」入口，`GET /me` → 200
- **实际**：`POST /api/v1/auth/login` → **403**，页面停留在登录页
- **证据**：Playwright `trace.network`（`artifacts/e2e/teacher-review-publish.trace.zip`）：
  - 登出请求 204，响应删除两个 Cookie（含 `leetmath_csrf`）；
  - 随后的登录请求带 `X-CSRF-Token: <旧值>` 且**没有 Cookie 头** → 403；
  - 登出与登录之间没有任何新的 `/api/v1/auth/csrf` 请求。
  截图 `artifacts/e2e/teacher-review-publish-failure.png`
- **根因**：`logout()` 以「不 await」的方式发起 `POST /auth/logout`，同时同步把 `state.csrfToken` 置空；
  但该登出请求自身会先 bootstrap 一个 CSRF token（`/auth/csrf` 会复用现有 Cookie 返回同一 token），
  它在 `state.csrfToken = null` **之后**才 resolve，于是又把已被登出响应删除 Cookie 的 token 写回缓存；
  下一次登录复用该 token，服务端因 Cookie 缺失返回 `CSRF_TOKEN_MISSING`（403）。
- **涉及文件与函数**：`frontend/app.js::logout`、`csrfToken`、新增 `invalidateCsrf`
- **修复方案**：
  1. `logout()` 先 `await` 撤销请求再清理本地状态（保证 Cookie 删除已生效）；
  2. CSRF bootstrap 加入**代际保护**：取号 → 请求 → resolve 时若代际已变（登出或被判定 token 失效）则**不缓存**并重取（最多 3 次，超限则只用于本次请求、不缓存）。
- **新增/修改的测试**：既有 `test_browser_e2e.py` 覆盖该路径（登出 → 不刷新重新登录 → `GET /me` 期望 200），修复前失败、修复后通过；`test_auth_security.py` 覆盖登出撤销与 Cookie 清理。
- **修复前验证**：该用例在 LM-001 修复后才执行到此步骤 —— 首次执行即失败（登录 403 → 等待「后台」超时）
- **修复后验证**：`13 passed`（含该用例）；安全探针中「登出后 `GET /me` → 401」仍成立
- **遗留风险**：断网时 `logout()` 现在会先等待请求（最多 fetch 超时），期间 UI 不切换；已用 try/catch 保证最终仍清理本地状态并跳转。

---

## 本轮排查后判定为"非产品缺陷"的现象（避免误报）

| 现象 | 结论 | 依据 |
|---|---|---|
| 首页搜索 `对数` 返回 0 行 | 探针脚本时序问题（未等待 SPA 渲染/未等 URL 变化） | `GET /api/v1/problems?query=对数` → 2 条；修正等待后 2/15 |
| 详情页 KaTeX 节点只有 5 个（脚本阈值 >5） | 阈值过严 | `.statement .katex` = 5，公式均渲染，无报错 |
| `ln(x^2)/2+1-a` 判为 accepted（原以为应 pending_review） | 引擎行为正确：该小问题设 `x>0`，此域下两式恒等 | 直接调用 checker：`x>0` → accepted；`x: real` → pending_review |
| 收藏检查第二次运行失败 | 探针脚本非幂等（第一次运行已收藏，第二次点击变成取消收藏） | 改为读取按钮状态后再决定是否点击，随后 46/46 |

## 上一轮（`de32528` 之前）已修复、本轮回归确认的缺陷

- `docker compose up --build` 因命名卷属主为 root 导致 seed `PermissionError`（Dockerfile 预建 `/app/var/objects`）。
- `cli ddl` 输出不可复现（索引顺序未排序）→ 已排序并重新生成 `docs/generated/schema.postgresql.sql`。
