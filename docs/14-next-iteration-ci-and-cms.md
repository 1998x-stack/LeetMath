# 14｜Phase 1 下一阶段实施计划：CI 质量门禁与结构化 CMS

> 2026-11-17 · 迭代 N1 候选交付 · **不是生产上线；CI 与浏览器验收以真实执行为准**。

## 一、基线、证据和优先级

查阅 README、HANDOFF、docs/00–13 及 reasoning-practice 后，当前 main 是可运行的本地/试点 MVP：13 道原创演示题、内容契约 v1、多源导入、不可变修订、双门禁审校、题库搜索与判题、学生端、固定 1/3/7 天推理训练。HANDOFF 记录曾在 SQLite 与 PostgreSQL 16 上各完成 245 项 Python 测试，却指出 GitHub Actions 文件缺失；教师编辑页面依赖手写 JSON。

本批集中处理 **P0 CI + P0/P1 教师结构化编审**。暂不并行实施高风险的生产认证、FSRS、AI 教师、几何 3D 与 Manim。

## 二、本批变更与验收契约

| 工作包 | 实现 | 自动化验收 | 已知不足 |
|---|---|---|---|
| 质量门禁 | .github/workflows/ci.yml | Python 3.12 + Node 22；compileall；Ruff 关键错误规则；13 个合同正例/黄金判题；PostgreSQL DDL 精确 diff、OpenAPI 结构 diff、JS 语法/Node 测试 | Ruff 全规则治理、依赖锁 |
| 数据库 | SQLite/PostgreSQL 16 矩阵 | Alembic upgrade/check/downgrade，全量 pytest | 真实生产备份恢复/SLO |
| 结构化编辑 | frontend/cms-editor.js | Node 测试验证无损拷贝、稳定 part_key、历史身份、diff | 富媒体编辑、全量表单 Schema、批量编辑 |
| 教师端整合 | frontend/app.js、index.html、style.css | 原有后端 RBAC/乐观锁不变；新增浏览器人工清单 | 浏览器截图 E2E 尚未自动化 |

### 编辑器约束

支持标题、难度、MathRichText 段落/行内公式/独立公式、题目预览、小问排序与增删、分值、参考答案和解答步骤。复杂图片/表格/链接/特种区块只读但**保留原字段与原结构**；高级判题器参数、rubric、reasoning_steps、来源及授权仍可用原始 JSON 模式编辑，不隐式丢弃数据。

排序仅改变 display_order，保留 logical_part_id、part_key；编辑器新增小问是含占位答案与待审解答的草稿，必须完成审校才能送审。已发布版本只读；更改需要创建新 revision。前端展示「未保存差异」和「相对上一修订差异」；If-Match 乐观锁与双人审校门禁仍由后端执行。

## 三、必须手动验证的 UI 细节（未验收前不得宣称已完成）

- [ ] editor 创建题目并修改 LaTeX（含中文、反斜杠、花括号），公式预览准确；375px 与桌面无溢出
- [ ] 表单修改图片/表格/链接混合题后切回高级 JSON，未知块、版权与评分字段零丢失
- [ ] 增删/排序小问，稳定 part_key / logical_part_id 不变；修改分值后出现 rubric/推理卡守恒提醒
- [ ] 同题新草稿相对上一版本差异正确；reviewer 查看只读；未保存变更不允许直接送审
- [ ] JSON 语法错误不能离开 JSON 模式且用户输入不丢；乐观锁 409 后草稿不被静默覆盖
- [ ] 两位独立审核者、版权有效性、公开 visibility 和权限回归通过
- [ ] GitHub PR 的 quality、sqlite、postgres16 三个 job 通过

## 四、下一阶段路线与完成条件

| 顺序 | 级别 | 工作包 | Done 口径 |
|---|---|---|---|
| N1 本批 | P0 | CI 双数据库与生成物门禁 | PR checks 真绿；可复现失败 |
| N1 本批 | P0/P1 | CMS 基础表单 + 预览 + diff | 常用字段可视化编辑，未知字段无损 |
| N2 | P0 | Playwright 桌面+375px E2E，公式审阅与可访问性 | 截图、交互断言、失败记录入 CI |
| N2 | P0 | httpOnly Cookie / CSRF / 跨实例 Redis 限流 | JS 不可读凭证、IDOR/CSRF 测试、双实例压测 |
| N3 | P0/P1 | 教师批量编审、差异局部批注、媒体上传/隔离扫描/签名 URL | 逐条权限+版权校验、失败报告、资产访问闭环 |
| N4 | P1 | 标注判题集 300+、中文/公式检索基线、去重阈值标定 | 标注指标和检索/SLO 报告可复现 |
| N4 | P0 | 备份/恢复演练、未成年人数据与权利合规审查 | RPO/RTO 演练记录、法律与教研签核 |
| N5 | P2 | FSRS、知识画像、2D/3D 与 Manim | 审核内容与事件语义稳定，按独立 ADR 上线 |

## 五、ADR

**N1-01：先维护原生 SPA**，与现有自有 KaTeX、自有 CSP 一致，避免本批引入框架迁移风险；复杂度达到阈值再讨论 Next.js。

**N1-02：不可变发布**，编辑范围仅 draft；旧 revision、submission、evaluation 均保持原关联。审批与版权仍由服务端强制执行。

**N1-03：无损表单**，高级内容只读及 JSON 后备通道，禁止将不认识的媒体或评分元数据扁平化重写。

**N1-04：复用已有 revision API 获取上一版本**，不增加冗余的后端 diff 接口；教师与审核者需要拥有原有 STAFF 权限。

**N1-05：先上有意义的静态错误基线**，后续再逐步扩展 Ruff 范围，不将其误称为全量 lint 已清零。

## 六、验证命令

Python 3.12：

~~~bash
pip install -r requirements-dev.txt
PYTHONPATH=backend python -m leetmath.cli validate fixtures/positive
PYTHONPATH=backend python -m leetmath.cli ddl --dialect postgresql > /tmp/leetmath-schema.sql
diff -u docs/generated/schema.postgresql.sql /tmp/leetmath-schema.sql
cd backend && python -m pytest -q
~~~

Node 22：

~~~bash
node --check frontend/app.js
node --check frontend/cms-editor.js
node --test frontend/tests/*.test.cjs
~~~

**验证状态**：该迭代已通过 GitHub 连接器写入候选分支，离线环境无法克隆 GitHub 仓库运行整套 Python/PostgreSQL 与浏览器测试；需要以 PR check 的实际结果更新本节。未完成上述验收不声称生产就绪。
