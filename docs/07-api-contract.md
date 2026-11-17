# 07｜LeetMath REST API v1 规范草案

Base path：/api/v1。统一 JSON，UTF-8。草案需以 OpenAPI 3.1 文件和契约测试落地（examples/openapi.yaml 提供初始骨架）。

## 1. 通用约定

- Auth：浏览器使用 HttpOnly session cookie；非浏览器集成可使用显式 Bearer token。Cookie 写请求必须通过 CSRF 与 Origin 校验。
- IDs：内部使用 UUID；display_id 仅用于用户界面；路径使用 slug 可变，返回 canonical URL。
- Pagination：cursor + limit（1..100），分页响应含 next_cursor/has_more；排序追加稳定 ID。
- Time：UTC RFC3339；locale BCP47；金额/小数精度用字符串以避免浮点歧义。
- Error body：{"error":{"code":"...","message":"...","request_id":"...","details":{}}}；必须区分 400/401/403/404/409/422/429/500/503。
- Idempotency-Key：POST submissions/imports/publish/jobs 必须支持；同 key 不同请求体返回 409 IDEMPOTENCY_CONFLICT。
- ETag / If-Match：用于草稿编辑乐观锁；409 或 412 返回当前版本/冲突字段。
- 公开 API 严格过滤许可和可见性；管理员只读私有内容也必须按角色与 scope 授权。


## 1.1 认证与 CSRF

~~~text
GET  /auth/csrf       # 建立 HMAC 签名的 CSRF cookie，返回 csrf_token
POST /auth/register   # 创建账号并设置 HttpOnly session cookie，响应只返回 user
POST /auth/login      # 登录并轮换旧 session cookie，响应只返回 user
POST /auth/logout     # 撤销当前 session，删除 session 与 CSRF cookie
POST /auth/token      # 非浏览器 API 兼容入口，显式返回 Bearer token
~~~

浏览器 SPA 使用 fetch credentials=same-origin，并在所有 unsafe methods 携带 X-CSRF-Token。Session Cookie：HttpOnly、SameSite=Lax、Path=/；生产 Secure，启用 Secure 时使用 __Host- 前缀且不设置 Domain。CSRF Cookie：JS 可读、SameSite=Strict、Path=/；生产 Secure。服务端比较 CSRF cookie/header、验证 HMAC，并在 Origin 存在时要求与请求源一致。显式 Authorization: Bearer 请求保留兼容性，SPA 不保存或发送 Bearer token。

生产必须设置 LEETMATH_ENV=production、LEETMATH_COOKIE_SECURE=1、共享 LEETMATH_REDIS_URL，以及唯一且至少 32 字符的 LEETMATH_CSRF_SECRET。

## 2. 公开题库与筛选

~~~text
GET /problems?query=导数&grade_band=senior_high&region=CN-SH&knowledge_id=...&difficulty_min=5&difficulty_max=8&response_type=expression&sort=updated_desc&limit=20&cursor=...
GET /problems/{slug}
GET /problems/{slug}/revisions/{revision_id}    # 有范围权限、历史公开策略
GET /knowledge?curriculum_release_id=...
GET /collections
GET /collections/{id}
~~~

列表返回：id、display_id、slug、title、difficulty、grade_band、region_hints、knowledge_summaries、part_count、attempted_state（仅登录用户）、current_public_revision_id。详情返回 revision_id、title、shared_statement、parts[]（id/logical_part_id/response_type/score）、allowed_assets、source_attribution、visible_solutions_policy。严禁向未满足显示策略的用户发送答案 spec/隐藏判题配置。

## 3. 提交、评测和个人学习

~~~text
POST /attempts
POST /attempts/{attempt_id}/submissions
GET  /submissions/{id}
GET  /submissions/{id}/evaluations
GET  /me/submissions?cursor=...
PUT  /me/bookmarks/{problem_id}
DELETE /me/bookmarks/{problem_id}
GET  /me/bookmarks
GET  /me/mistakes
GET  /me/progress?knowledge_id=...
POST /content-reports
GET  /content-reports/{id}  # 仅创建人/有授权管理员
~~~

POST /attempts body：{"problem_revision_id":"uuid","mode":"practice"}。POST submissions body：{"revision_part_id":"uuid","response":{"type":"expression","input":"ln(x)+1-a"}}，返回 202 evaluation queued 或 200 计算完成，含 submission_id、evaluation_id、poll_url。错误示例：409 REVISION_SUPERSEDED / CONTENT_RETRACTED；422 INVALID_MATH_INPUT；429 RATE_LIMITED。

同一 attempt 的 revision_part_id 必须属于该 attempt.problem_revision_id。匿名用户可尝试本地演练但不能伪造拥有服务端进度。

## 4. CMS / 题源 / 导入

~~~text
GET  /admin/problems?status=draft
POST /admin/problems
GET  /admin/problems/{id}
POST /admin/problems/{id}/revisions
PATCH /admin/problem-revisions/{id}            # If-Match
POST /admin/problem-revisions/{id}/submit-review
POST /admin/problem-revisions/{id}/approve
POST /admin/problem-revisions/{id}/reject
POST /admin/problem-revisions/{id}/publish
POST /admin/problem-revisions/{id}/retract
GET  /admin/sources
POST /admin/sources
POST /admin/rights-grants
POST /admin/imports/dry-run
POST /admin/imports
GET  /admin/imports/{batch_id}
GET  /admin/imports/{batch_id}/rows
POST /admin/imports/{batch_id}/retry-failed
GET  /admin/duplicates?status=pending
POST /admin/duplicates/{candidate_id}/resolve
GET  /admin/audit-events?entity_type=...
~~~

发布必须通过审核和 rights gate，不允许管理员跳过阻断校验直接 force publish。批量后台操作返回 job_id，并提供 job 状态可查。

## 5. API 示例

~~~json
{
  "id": "f5e5a151-24bc-473b-b0c2-8afca51b1001",
  "display_id": "LM-SH-000001",
  "slug": "function-x-log-x-minus-a-x",
  "current_revision": {
    "id": "7bf963cf-d872-4c26-8a9c-72cbeaa71001",
    "revision_no": 1,
    "locale": "zh-CN",
    "title": "含参数函数的导数、单调性与不等式",
    "parts": [
      {"id": "3d0108d3-dc46-4c44-a38f-cdc183e51001", "display_order": 1, "response_type": "expression", "max_score": "3.00"},
      {"id": "3d0108d3-dc46-4c44-a38f-cdc183e51002", "display_order": 2, "response_type": "derivation", "max_score": "5.00"},
      {"id": "3d0108d3-dc46-4c44-a38f-cdc183e51003", "display_order": 3, "response_type": "proof", "max_score": "6.00"}
    ]
  }
}
~~~

## 6. 接口权限矩阵

| 角色 | 公开阅读 | 作答/自己历史 | CMS 编辑 | 审核/发布 | 数据源/授权管理 |
|---|---|---|---|---|---|
| guest | ✓ | — | — | — | — |
| student | ✓ | ✓ | — | — | — |
| editor | ✓ | ✓ | ✓（指定 scope） | — | — |
| reviewer | ✓ | ✓ | 审阅范围读 | ✓（不能审批本人内容） | 只读授权 |
| rights_reviewer | ✓ | ✓ | — | 仅权利审核 gate（不能审数学内容） | 授权文件审核 |
| source_manager | ✓ | — | 导入草稿 | 不能单独发布 | ✓ |
| admin | ✓ | 按必要权限 | ✓ | ✓（双人门禁仍适用） | ✓ |
| auditor | — | — | — | — | 只读审计与访问报表 |

## 7. 错误码注册表

AUTH_REQUIRED、FORBIDDEN、NOT_FOUND、VALIDATION_FAILED、INVALID_MATH_INPUT、MATH_PARSER_TIMEOUT、GRADER_UNAVAILABLE、CONTENT_RETRACTED、REVISION_SUPERSEDED、RIGHTS_HOLD、SOURCE_VERSION_CONFLICT、IDEMPOTENCY_CONFLICT、EDIT_CONFLICT、IMPORT_SCHEMA_MISMATCH、IMPORT_FILE_HASH_MISMATCH、RATE_LIMITED。

客户端必须显示可理解文案；服务端将 request_id 贯穿追踪，不在错误响应中返回敏感堆栈和数据库 SQL。
