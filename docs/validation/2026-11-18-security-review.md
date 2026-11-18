# 安全复核报告（Cookie / CSRF / RBAC / 限流）｜2026-11-18

环境：Compose 栈（`http://127.0.0.1:18000`，`LEETMATH_ENV=development`、`LEETMATH_COOKIE_SECURE=0`、
共享 Redis）。探针脚本：`/tmp/lm-security-probe.py`（输出 `artifacts/local-validation/2026-11-18/security-probe.json`）。
**本报告与脚本均不打印任何 Cookie、令牌或密钥值**，只记录标志位、状态码、错误码与摘要结论。

## 1. 探针结果（17/17 通过，真实 HTTP）

| # | 检查 | 结果 |
|---|---|---|
| 1 | 同源带 `X-CSRF-Token` 登录 | 200 |
| 2 | 登录响应体不含会话令牌 | 仅 `{"user": …}`，无 `token` 字段 |
| 3 | 会话 Cookie 属性 | `HttpOnly; Max-Age=259200; Path=/; SameSite=lax`，本地 HTTP 无 `Secure`（符合 `COOKIE_SECURE=0`） |
| 4 | CSRF Cookie 属性 | JS 可读、`SameSite=strict`、`Path=/`（由 `/auth/csrf` 下发，登录只下发会话 Cookie） |
| 5 | Cookie 会话写操作缺 CSRF 头 | 403 `CSRF_TOKEN_MISSING` |
| 6 | 跨源 `Origin: https://evil.example`（非安全方法） | 403 |
| 7 | 跨源写操作（即使带有效 token） | 403 `CSRF_ORIGIN_MISMATCH` |
| 8 | Cookie 会话访问 `GET /me` | 200 |
| 9 | 登出 | 204 |
| 10 | 登出后 `GET /me` | 401（会话即时失效） |
| 11 | `POST /auth/token`（非浏览器集成路径，免 CSRF） | 200 且返回 bearer |
| 12 | Bearer 访问 `GET /me` | 200 |
| 13 | bearer 值与会话 Cookie 值不同 | 是 |
| 14 | 数据库只存摘要 | `auth_sessions.token_hash` 全为 64 位十六进制 SHA-256，且等于 `sha256(bearer)`；未出现原始令牌 |
| 15 | 热点桶触发限流 | 连续注册请求：403×10 → **429** |
| 16 | 429 带 `Retry-After` | `Retry-After: 60` |
| 17 | 无效 CSRF 请求也计入限流 | 前 10 次 403 仍消耗注册窗口（符合"先限流后拒绝 CSRF"的既有修复） |

## 2. 自动化安全测试（pytest，真实 TestClient + Redis）

`backend/tests/test_auth_security.py`（5 例）与 `backend/tests/test_rate_limit.py`（5 例）在最终提交树上全部通过，
CI parity 命令整体 `13 passed`：

- `test_browser_login_sets_httponly_cookie_and_never_returns_session_token`
- `test_logout_revokes_session_immediately_and_clears_cookies`
- `test_cookie_writes_require_valid_csrf_and_same_origin`
- `test_explicit_bearer_compatibility_endpoint_remains_available`
- `test_reauthentication_rotates_cookie_and_revokes_previous_session`
- `test_two_independent_limiter_instances_share_atomic_redis_window`
- `test_production_rate_limit_fails_closed_without_shared_backend`
- `test_local_fallback_is_windowed_and_does_not_leak_raw_keys`
- `test_two_independent_api_processes_share_ip_rate_limit`
- `test_configured_but_unreachable_redis_fails_closed`

要点：
- 两个**独立 Uvicorn 进程**共享同一 Redis 限流窗口（分布式一致性由真实进程验证，而非同进程两个对象）；
- `production` 且无共享后端 → 503 `RATE_LIMIT_BACKEND_UNAVAILABLE`（fail closed），**不会**静默降级为进程内计数；
- Redis 已配置但不可达 → 503（不降级）；
- 本地开发未配置 Redis 时才使用进程内 fallback，并且 key 以 SHA-256 存桶（不泄露原始用户/IP 键）。

## 3. 权限与业务流程（回归覆盖，255 例中）

- IDOR：`test_idor_other_students_data` 等 —— 学生无法读取他人提交/错题/进度。
- RBAC：`test_students_and_editors_cannot_publish`；学生/编辑不能发布，越权写接口被拒。
- 自审阻断：`test_reviewer_cannot_approve_own_content`（数学与版权审核需不同人）。
- 版权门禁：`test_cannot_publish_before_rights_review`、`test_rights_expiry_*`、`test_rights_hold_and_release`、`test_ac005_retracted_content_unreachable`。
- 不可变历史：`test_ac002_new_revision_keeps_history`（发布后原位修改被 ORM 守卫/触发器阻止）。
- 内容导入：`test_sample_a…f`（不自动发布、不自动合并、逐行状态）。
- 判题沙箱：`test_engine_timeout_is_not_a_math_error`（超时/资源限制不误判为数学错误）。
- 推理训练：`test_reasoning.py`（自评不进入 `evaluations`，XP 幂等）。

## 4. 未执行 / 未证明

| 项 | 原因 | 需要的后续动作 |
|---|---|---|
| `Secure` + `__Host-` 前缀（生产 Cookie） | 本机无 HTTPS 终止，`LEETMATH_COOKIE_SECURE=0` | 在具备 TLS 的环境用 `LEETMATH_ENV=production` + 真实域验证 |
| 生产启动自检（强制 Secure/Redis/CSRF secret） | 同上 | 冒烟：缺任一配置应拒绝启动 |
| `FORWARDED_ALLOW_IPS` 反代行为 | 无反向代理 | 部署阶段用真实代理 IP/CIDR 验证，禁止 `*` |
| 渗透测试 / 依赖漏洞扫描 / 备份恢复演练 | 超出本机验收范围 | 上线前安全评审（docs/11） |
| 限流阈值校准与压测（SLO） | 需要真实流量分布 | 正式开放前按学校 NAT/代理重新标定 |
| 真实用户旧会话一次性撤销 | 属运维操作（`UPDATE auth_sessions SET revoked = TRUE`） | 发布窗口执行，**未在本机执行** |
