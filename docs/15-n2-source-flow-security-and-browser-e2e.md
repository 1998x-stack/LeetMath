# 15｜N2 源码因果分析与实现：浏览器编审 E2E、Cookie/CSRF 与共享限流

> 日期：2026-11-17 · 对应 GitHub Issues：[#3 Playwright 编审闭环 + 375px 数学公式 E2E](https://github.com/1998x-stack/LeetMath/issues/3)、[#4 Cookie/CSRF + 共享限流](https://github.com/1998x-stack/LeetMath/issues/4)。
>
> 状态说明：本文件描述 N2 候选实现分支。只有 PR 的 GitHub Actions、浏览器 trace 与双进程 Redis 测试实际通过后，才可将状态更新为“已验收”；本文件不构成生产上线许可。

## 1. 调查方法与结论

本次不是按 Issue 文字直接补依赖，而是沿着“入口 → 状态/数据 → 组件 → 副作用 → 失败表现 → 测试缺口”追踪源码：

- 先阅读 HANDOFF.md、docs/07、docs/08、docs/11、docs/14 和 Issues #3/#4；
- 再定位 backend/leetmath/app.py、api/public.py、api/common.py、services/learning.py、services/audit.py、models.py；
- 前端追踪 frontend/index.html → app.js → cms-editor.js → style.css → 本地 KaTeX；
- 对照 backend/tests/conftest.py、test_api_flow.py、test_workflow_rights.py，识别原测试真正覆盖的边界；
- 最后把浏览器与多进程测试接入 CI，而不是把 TestClient 的 API 测试误当作 UI/部署验收。

**根因归纳：**

1. Issue #3 的问题不是“缺少一个 Playwright 包”，而是旧 CI 的测试入口没有启动真实 HTTP 服务和浏览器。245 个 TestClient 测试不执行 CSS 布局、真实 cookie jar、KaTeX 脚本加载、浏览器交互或视口测量，因此它们全绿也无法证明 375px 页面可用。
2. Issue #4 的问题是两个彼此独立的单进程假设：浏览器认证凭证放在 sessionStorage，服务端限流桶放在 Python 进程内。前者使同源 XSS 能读取 bearer token；后者让每个 worker/container 拥有不同计数，重启后计数清空。
3. 数据库已经有 AuthSession.token_hash / expires_at / revoked。因此会话安全升级不需要新造一套明文 session 表；应复用现有 token hash、过期和撤销语义，把浏览器凭证的传递方式改为 HttpOnly Cookie。

## 2. Issue #3：浏览器编审闭环与移动端公式

### 2.1 原始问题的逐步源码流程

旧测试路径：

~~~text
.github/workflows/ci.yml
  └─ pytest
      └─ backend/tests/conftest.py::client
          └─ fastapi.testclient.TestClient(app)
              └─ FastAPI API 路由 / SQLAlchemy
~~~

这条链路能验证 API 状态码、权限、版本与数据库事务，但不会加载浏览器入口：

~~~text
frontend/index.html
  ├─ /static/vendor/katex/katex.min.js
  ├─ /static/cms-editor.js
  ├─ /static/app.js
  └─ /static/style.css
~~~

浏览器实际的数学显示链路是：

1. app.js::viewProblem() 获取公开题目 DTO；
2. rich() 遍历 MathRichText blocks；
3. mathEl() 调用 window.katex.render(..., trust:false)；
4. style.css 的 .statement、.display-math、.layout-detail 和移动端 media query 决定实际布局；
5. 教师端 adminEdit() 获取 revision，调用 LeetMathCms.createForm()；
6. cms-editor.js 以原位修改的方式更新 Contract JSON，预览由 opts.rich() 生成；
7. 保存时 PATCH /admin/problem-revisions/{rid} 携带 If-Match，送审/审批/发布由服务端状态机决定。

因此，原来只有 API 测试时，以下故障都可能逃过 CI：本地 KaTeX 资源没有加载、公式节点没有被渲染、长公式/表格导致页面横向溢出、结构化表单切换时丢失未知 block、按钮绑定错误、Cookie 没有被浏览器带上、审核角色看到错误动作、乐观锁冲突后草稿输入被覆盖。

### 2.2 修复方案

- 新增 backend/tests/test_browser_e2e.py：通过独立 Uvicorn HTTP 服务启动同一个 seeded FastAPI app，使用真实 Chromium 访问 /、/problems/...、/admin/...。
- CI quality job 安装 Playwright Chromium，并上传 artifacts/e2e/ 中的截图与 trace。
- 覆盖桌面与 375px 视口；断言 document.documentElement.scrollWidth 和 document.body.scrollWidth 不超过 window.innerWidth。
- 通过 UI 创建草稿、修改标题、MathRichText、标准答案、预检、保存、送审；使用不同账号完成数学审核和版权审核，再由 reviewer 发布。
- 在高级 JSON 中加入合法 table block，切换结构化表单再切回 JSON，验证不支持可视化编辑的复杂 block 没有被扁平化或丢弃。
- 发布后验证旧 revision 只读；基于旧版本创建新 revision，验证差异视图反映字段变更。
- 使用两个独立浏览器上下文（editor 与 admin）编辑同一草稿，先后保存，第二个请求得到 412 EDIT_CONFLICT，原始输入仍留在编辑框中。
- 用包含 HTML 标签的普通文本检查 CMS 预览和公开页面是否把内容作为文本节点处理；KaTeX 继续使用 trust:false。
- 对浏览器截图、trace 和失败截图统一归档。

### 2.3 为什么移动端 CSS 要这样改

原 CSS 已有 max-width:860px 的单列布局，但“切换为单列”并不等于“内容不会撑开 viewport”。表格、长行内公式、网格子项和 flex 子项可能保留 min-content 宽度。

本批为主要内容容器设置 min-width:0 / max-width:100%；表格在自身区域内横向滚动；行内公式成为可滚动 inline block；.statement 与 .kv dd 允许长内容折行。目标是把不可避免的宽内容限制在局部容器内，而不是用 overflow-x:hidden 隐藏整个页面的布局错误。

### 2.4 验收边界

自动化浏览器覆盖的关键路径不等于完整人工教研验收。以下内容仍需要后续补齐：

- 上传真实图片/附件、对象存储隔离、恶意文件扫描和短效签名 URL；
- 真实多租户 scope 和不同组织的编辑隔离；
- 所有题型、所有复杂 MathRichText block 的视觉回归；
- Safari/WebKit、Firefox、Android/iOS 真机差异；
- 真实教师对公式排版、可访问性和教学内容的人工确认。

## 3. Issue #4：Cookie 会话、CSRF 与共享限流

### 3.1 旧认证调用链与问题如何发生

~~~text
POST /api/v1/auth/login
  └─ api/public.py::login()
      └─ issue_token()
          └─ response {"token": "..."}
              └─ frontend/app.js
                  ├─ state.token
                  ├─ sessionStorage.setItem("lm_token", token)
                  └─ api() 添加 Authorization: Bearer ...
                      └─ api/common.py::current_user()
                          └─ _user_from_token(Authorization)
~~~

旧链路把可直接访问账户权限的 bearer token 放在 JavaScript 可读存储中。任何同源 XSS 一旦执行，就能读取 token 并在有效期内重放。AuthSession 虽然已经只存 token hash，但这只保护数据库静态数据，不解决浏览器端凭证暴露。

旧限流链路：

~~~text
API request
  └─ services/learning.py::rate_limit()
      └─ module-level defaultdict(deque)
          ├─ worker A 自己的内存桶
          ├─ worker B 自己的内存桶
          └─ container restart → 所有桶清空
~~~

例如登录限制为每用户名 20 次/分钟：攻击者将请求均匀发往 4 个 worker 时，每个 worker 看到的计数都低于本地阈值；单实例测试不会暴露这个问题。

### 3.2 新浏览器认证链路

~~~text
GET /api/v1/auth/csrf
  ├─ 创建/复用 HMAC 签名的随机 CSRF token
  ├─ 设置 SameSite=Strict、JS 可读的 CSRF cookie
  └─ 返回 csrf_token 给 SPA 内存态

POST /api/v1/auth/login + X-CSRF-Token
  ├─ 校验 Origin 与 CSRF cookie/header
  ├─ 验证用户名密码
  ├─ 撤销旧 session（如存在）
  ├─ 新 token 只以 HttpOnly session cookie 下发
  └─ JSON 只返回 user，不返回 session token

后续同源 API
  ├─ fetch(..., credentials="same-origin")
  ├─ unsafe methods 添加 X-CSRF-Token
  └─ api/common.py 从 Cookie 读取 token hash 并校验 AuthSession
~~~

Cookie 约定：

| Cookie | 属性 | 用途 |
|---|---|---|
| Session | HttpOnly、SameSite=Lax、Path=/；生产 Secure | 身份凭证，JavaScript 不可读 |
| CSRF | JS 可读、SameSite=Strict、Path=/；生产 Secure | 供 SPA 回传 X-CSRF-Token，本身不是登录凭证 |

生产环境启用 Secure 时使用 __Host- 前缀，且不设置 Domain。所有 cookie-auth 写请求都校验 CSRF；若 Origin 存在则必须与请求源一致。显式 Authorization: Bearer 仍作为非浏览器 API 兼容方式，避免破坏现有集成；SPA 不再使用它。

POST /auth/login 与 /auth/register 现在返回用户信息并设置 cookie；需要显式 bearer token 的脚本/集成调用 POST /auth/token。旧 SPA 曾写入的 lm_token 会在新版本启动时从 sessionStorage/localStorage 清除。

登出会撤销数据库 session、删除 session/CSRF 两个 cookie。再次登录会获取新的 CSRF bootstrap，并签发新的 session；测试覆盖旧 token 不能继续使用。数据库仍只存 SHA-256 token digest，不保存原始 token。

### 3.3 新共享限流链路

~~~text
FastAPI middleware / learning service
  └─ services/rate_limit.py::RateLimiter.check()
      ├─ SHA-256(key) → 不暴露原始用户/IP key
      ├─ Redis Lua script
      │   ├─ Redis TIME 取统一时钟
      │   ├─ ZREMRANGEBYSCORE 清理窗口外请求
      │   ├─ ZCARD 判断阈值
      │   ├─ ZADD 写入本次请求
      │   └─ PEXPIRE 清理空闲 key
      └─ 同一 Redis key 对所有 API 进程原子可见
~~~

Lua 脚本把“清理旧请求 → 读取计数 → 判断 → 写入新请求”放在 Redis 单次原子执行中。每个事件使用 UUID member，避免同毫秒请求覆盖。Redis 使用自己的 TIME，避免不同 API 主机时钟偏差造成窗口不一致。

当前按 IP 与操作分类设置边界：登录/API token 60 次/分钟、注册 10 次/分钟、提交 240 次/分钟、举报 30 次/分钟、CMS 读写 180 次/分钟、普通读取 600 次/分钟、普通写入 180 次/分钟；登录/注册/提交服务还按用户维度限流。阈值是初始防护值，不是压测后 SLO，正式开放前要根据学校 NAT、代理与流量分布校准。

Redis 不可用时：
- 生产环境必须 fail closed，返回 503 RATE_LIMIT_BACKEND_UNAVAILABLE；
- Redis 已配置但命令失败时，不允许偷偷降级为每进程内存桶；
- 非生产开发环境未配置 Redis 时允许本地 fallback，明确不具备多实例一致性。

### 3.4 测试设计

- test_auth_security.py：HttpOnly/SameSite 标志、登录响应不返回 token、CSRF 缺失/伪造/跨 Origin 拒绝、正常同源登录、登出即时撤销、重登录轮换、数据库只存 hash、Bearer API 兼容。
- test_rate_limit.py：两个独立 limiter 共享同一 Redis 窗口；生产无 Redis fail closed；Redis 配置但不可达返回 503；两个独立 Uvicorn 进程共享同一 IP 限流桶。
- test_workflow_rights.py 与 test_api_flow.py：继续回归自审阻断、双人数学/版权 gate、发布前权利检查、历史 revision、IDOR、学生提交归属和判题路径。
- test_browser_e2e.py：验证浏览器拿不到 session token、旧 sessionStorage token 被清除、cookie 写请求带 CSRF、SPA 登出后可无整页刷新重新登录。

## 4. 环境变量与部署约束

| 环境变量 | 开发/本地 | 生产 |
|---|---|---|
| LEETMATH_ENV | development | production |
| LEETMATH_COOKIE_SECURE | 本地 HTTP 可设 0 | 必须 1 |
| LEETMATH_REDIS_URL | Compose 使用 redis://redis:6379/0；脚本直跑可不配 | 必须配置共享 Redis，使用 ACL/TLS/密钥管理 |
| LEETMATH_CSRF_SECRET | 仓库默认值仅限本地 | 唯一随机密钥，至少 32 字符，不可复用或入库 |
| LEETMATH_AUTO_CREATE | 本地可自动创建 | 必须 0，由 Alembic 管理 |
| LEETMATH_DATABASE_URL | SQLite 或 Compose PostgreSQL | PostgreSQL，凭据来自 secrets |
| FORWARDED_ALLOW_IPS | 本地可使用默认值 | 只填写实际反向代理 IP/CIDR，不要无条件设 * |

create_app() 在 production 启动时检查 Secure Cookie、Redis URL 和 CSRF secret。Docker Compose 已增加 Redis 7 服务；scripts/run-local.sh 显式设置开发环境与 HTTP cookie 选项。演示账号、Compose 数据库口令、开发 CSRF secret 都是本地值，生产必须替换；生产环境不得执行 demo seed 来创建可预测账号。

限流按 request.client.host 识别来源 IP。若服务位于反向代理之后，必须通过 Uvicorn FORWARDED_ALLOW_IPS 只信任真实代理地址；否则所有用户可能被识别为代理 IP。测试代码使用 forwarded_allow_ips="*" 只为本地双进程验证，不得复制到生产。

## 5. 文件级改动索引

| 文件 | 改动职责 |
|---|---|
| backend/leetmath/services/security.py | Cookie 名称、HMAC CSRF token、Origin/CSRF 校验 |
| backend/leetmath/services/rate_limit.py | Redis Lua sliding-window、开发 fallback、生产 fail-closed |
| backend/leetmath/api/public.py | cookie login/register/logout、token compatibility endpoint |
| backend/leetmath/api/common.py | Cookie/Bearer 双认证入口，复用 AuthSession hash/expiry/revoked |
| backend/leetmath/app.py | CSRF middleware、按 IP/操作分类限流、429 Retry-After |
| backend/leetmath/services/learning.py | 用户级限流转到共享 limiter |
| frontend/app.js | 移除 Bearer/sessionStorage，same-origin credentials，CSRF header |
| frontend/style.css | 小屏内容宽度约束与局部横向滚动 |
| backend/tests/test_browser_e2e.py | Chromium 真浏览器回归、截图、trace |
| backend/tests/test_auth_security.py | Cookie/CSRF/撤销/轮换测试 |
| backend/tests/test_rate_limit.py | Redis 单元/双进程共享测试 |
| .github/workflows/ci.yml | Redis service、Playwright Chromium、浏览器 artifact |
| docker-compose.yml、requirements*.txt | Redis 服务、Python Redis 与 Playwright 依赖 |
| docs/generated/openapi.json | 同步新增 CSRF bootstrap 与 API token endpoint |

## 6. 回滚与兼容

- 现有 AuthSession 表结构不变，不需要迁移；新旧认证共用 token hash、过期与撤销字段。
- 新版本第一次对真实用户开放前，应安排一次旧会话失效：在维护窗口执行 `UPDATE auth_sessions SET revoked = TRUE WHERE revoked = FALSE;`，所有用户需要重新登录。该操作不可逆地撤销现有会话，不要在日常启动时自动执行。
- 非浏览器 Bearer API 仍可使用；浏览器 SPA 只走 Cookie。
- 若需回滚前端，应同时回滚认证 API 与 CSRF middleware，不能只回滚 app.js，否则浏览器写请求会被拒绝。
- 若 Redis 故障，生产保持 503 并恢复 Redis；禁止通过关闭限流或开启本地 fallback 规避故障。
- 若浏览器 E2E 失败，保留 trace/screenshot，修复后再合并；不得把测试改为 skip 或删除溢出断言来制造绿灯。

## 7. N2 完成判据

- [ ] GitHub Actions quality / SQLite / PostgreSQL 16 全部通过；
- [ ] Chromium desktop 与 375px 浏览器 E2E 全部通过，artifact 可下载；
- [ ] editor → reviewer → rights reviewer → publish 完整闭环通过；
- [ ] 复杂 table block 表单切换无损、published revision 只读、新 revision diff 正确；
- [ ] 两个独立编辑会话触发 412 EDIT_CONFLICT，第二份输入保留；
- [ ] Cookie/CSRF/登出撤销/会话轮换与 legacy token 清理测试通过；
- [ ] 两个独立 API 进程通过 Redis 共享同一限流桶；Redis 故障生产 fail closed；
- [ ] 原有 IDOR、版权 gate、RBAC、判题 sandbox 回归通过；
- [ ] 部署文档、OpenAPI 与代码保持一致。

N2 完成不代表媒体上传、恶意文件扫描、异步判题、生产压测、备份恢复、未成年人数据合规或生产上线审批完成。
