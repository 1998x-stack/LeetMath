# 浏览器复核报告（功能 + 数学排版 + 响应式）｜2026-11-18

环境：Chromium 159.0.8154.6（headless，Playwright Python），目标 `http://127.0.0.1:18000`
（Compose：PostgreSQL 16 + Redis 7 + Uvicorn + 本地 KaTeX，无外部 CDN）。

## 1. 学生端主流程（P0-A）

| 步骤 | 操作方法 | 观测结果 |
|---|---|---|
| 打开首页 | `GET /` | 200，SPA 外壳加载，题库表格 15 行 |
| 关键词搜索 | 搜索框输入 `对数` + Enter | URL 带 `query=`，表格 2 行（`对数函数的定义域（单选）`、`方程的解集（注意增根）`） |
| 知识点筛选 | `select` 全部知识点 → `对数与对数函数` | 选项由 `/api/v1/knowledge` 渲染（含父子缩进） |
| 打开多小问题目 | `/problems/function-x-log-x-minus-a-x` | 3 个 `section.part`，题干 `.statement` 内 KaTeX 节点 5 个，来源/更新/知识点侧栏齐全 |
| 逐问作答 | 每题「提交」按钮 | `POST /attempts` → `POST /attempts/{id}/submissions`，反馈区显示状态 + 得分，`submissions` 返回 201 |
| 正确/等价 | `ln(x)+1-a`、`1-a+ln(x)` | `✓ 正确　得分 3.00 / 3.00`（「在题设条件下符号等价」） |
| 错误 | `ln(x)-1-a` | `✗ 不正确　得分 0.00 / 3.00` +「认为判错？申诉」入口 |
| 格式异常 | `ln(x` | `⚠ 格式无法解析`（`expected ')'`），不产生错题 |
| 定义域差异 | `x/x+2x-3`（题目假设 x 为实数） | `⏳ 待复核`「表达式定义域与标准答案不同，已转人工复核」 |
| 人工题 | 第 2 问（derivation） | `⏳ 待复核`，提示由教师按评分点批改 |
| 错题/收藏/进度/历史 | `/me/{mistakes,bookmarks,progress,submissions}` | 均渲染数据：错题含「第1问」、收藏含题目、进度含 0/1 与最近练习、提交历史含 5 条记录 |
| 登出 | 顶栏「退出」 | `POST /auth/logout` 204；随后 `GET /me` → 401；访问 `/me` 跳转 `/login?next=/me` |

## 2. 教师 CMS 全流程（P0-B，由 `test_browser_e2e.py` 覆盖并本轮通过）

1. 高级 JSON 注入合法 `table` block → 切结构化表单 → 切回 JSON：`e2e-table-preserved` 仍存在（复杂区块未被扁平化，表单显示「该区块仅预览，数据保持不变」）。
2. 标题与 MathRichText 正文写入含 `<img src=x onerror=...>` 的**纯文本**：CMS 预览与公开页均无 `img[src=x]`、`window.__leetmathXss` 保持 `null`，文本按文本节点显示。
3. 预检：故意构造 `RUBRIC_SUM_MISMATCH` → 出现阻断项（`data-preflight-state="blocking"`），修好后 → `ok`；保存草稿出现「已保存（版本锁 …）」。
4. 送审 → `in_math_review` →（reviewer）数学审核通过 → `in_rights_review` →（rights，另一位审核人）版权审核通过 → `approved` →（reviewer）发布 → `published`；每一步都由 `data-revision-status` 断言，而非子串文本。
5. 发布后编辑页只读（标题输入框 disabled）；「基于此创建新修订」→ 差异面板先显示 `相对上一版本的差异 · 0 处`（修复后），改标题后 `· 1 处`。
6. 两个独立上下文（editor 与 admin）竞争保存：第二个保存得到 HTTP 412 → 显示「草稿已被他人修改」且本地输入保留。
7. 移动端 375px：CMS 编辑页与公开页均无横向溢出。

## 3. 数学排版（P0-C）

程序化断言（本轮模型无 vision，未做像素级人工判读；截图已留档待人工/视觉模型复核）：

| 内容 | 断言 |
|---|---|
| 行内公式 / 上下标 / 分式 `\frac{x^2+1}{x-1}` | `.statement .katex` 节点渲染成功，`katex.render(..., {trust:false, throwOnError:false})` |
| 独立公式 | `.display-math` 容器存在，`overflow-x:auto` 局部滚动 |
| 对数 `\ln x`、三角 `2\sin(x+\pi/3)`、根式 `\sqrt{6}/3` 等种子题 | 13 道种子题在题库/详情页均渲染无报错（`test_contract` 与浏览器用例覆盖） |
| 长分式与表格混排 | 注入 table block 的题目在 375px 无整页溢出（修复 LM-003 后 437px → 375px） |
| 公式截断 | 未发现公式被裁剪：KaTeX MathML 影子节点（`katex-mathml`）为 1px 且 `overflow:hidden` 属于 KaTeX 正常结构，不构成溢出 |

## 4. 视口与溢出度量（P0-C）

度量方式：`document.documentElement.scrollWidth` 与 `document.body.scrollWidth` 必须 ≤ `window.innerWidth`；
失败时打印超宽元素清单（标签/类名/宽度/scrollWidth）。页面：题库、题目详情、登录、题单、推理训练、
后台列表、CMS 编辑、我的学习。

| 视口 | 结果 |
|---|---|
| 1280px | 8/8 无溢出 |
| 768px | 8/8 无溢出 |
| 375px | 8/8 无溢出 |

截图（本地，未上传）：`artifacts/local-validation/2026-11-18/responsive-375-*.png`、
`student-*.png`，E2E 产物 `artifacts/e2e/*.png` 与 `*.trace.zip`。

## 5. 体验问题记录（区分类型）

| 类型 | 问题 | 严重度 | 处理 |
|---|---|---|---|
| 功能阻断（已修） | 移动端题目标题含不可断行长串时整页横向滚动 | P0 | 本轮修复 LM-003 |
| 功能阻断（已修） | CMS「相对上一版本的差异」把 revision 行身份算作内容变更（0 改动显示 4 处） | P1 | 本轮修复 LM-002 |
| 权限/状态（已修） | SPA 登出后重新登录 403（CSRF 缓存竞态） | P0 | 本轮修复 LM-004 |
| 可访问性（已修） | 多个编辑区域含同名控件且区域无名称 | P2 | 本轮修复 LM-001（区域加 aria-label + scope） |
| 表单易用性 | CMS 仍以 JSON + 结构化表单混用，缺少批量编辑/差异视图增强 | P1 | 未开发（docs/13 §6 已登记） |
| 性能 | 单进程同步判题，无队列/SSE；本地未测压 | P1 | 未开发 |
| 缺失功能 | 解析几何/立体几何交互可视化、Manim 视频 | 规划项 | 不列为当前缺陷（docs/12 规划） |

## 6. 未执行的复核

- 真实移动设备（iOS/Android）、Safari/WebKit、Firefox。
- 像素级视觉审美与教研可读性人工确认（需人工或具备 vision 的模型）。
- 深色模式、打印布局、无障碍读屏实测（仅有语义标签与 `aria-live` 的静态检查）。
