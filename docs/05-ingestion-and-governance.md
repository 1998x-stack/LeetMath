# 05｜多题库接入、ETL、去重与内容治理

**本项目可持续规模化的最关键规格。** 第一批上海高中数学只是 Source Registry 的一个实例；不能为每个题源写一套独立的业务表。

## 1. 题源类型与接入决策

| 来源类型 | 输入 | 适配器 | 要求 |
|---|---|---|---|
| 自有原创 | CMS / JSONL | internal | 创作者与贡献记录、原创建档 |
| 授权合作方 | API / CSV / JSON / ZIP | partner | 合同/范围/截止日期与源标识 |
| 开放许可题集 | Git 仓库/公开数据包 | open_license | 许可证兼容、作者署名、原始链接 |
| 教材/试卷（合法获取） | PDF / 图片 / 结构化 | document | 权利核验 + 逐题人工审查 |
| 教师个人私有题库 | Excel / JSON | teacher_private | 私有访问域、不可默认公开 |
| 题库编辑迁移 | 数据库导出/JSONL | legacy | 字段映射、历史 ID/授权证据迁移 |

禁止未授权批量抓取商业平台或将未核对的 OCR / AI 识别结果自动公开。

## 2. Connector 标准接口

~~~python
class SourceAdapter:
    source_code: str
    adapter_version: str
    async def discover(self, cursor): ...
    async def fetch(self, key): ...
    async def parse(self, raw_bytes): ...
    async def normalize(self, source_record): ...
    async def asset_refs(self, source_record): ...
    async def provenance(self, source_record): ...
~~~

所有适配器必须返回 Contract v1，并保留 raw bytes + source metadata + 解析/规范化版本。Adapter 不得直接发布 canonical Problem；只能提交 IntakeResult 到治理队列。新来源接入不更改业务主表。

## 3. 导入清单 Manifest 与契约

每批有：source_code、dataset_id、dataset_version、manifest_schema_version、input_format、source_license_ref、locale、curriculum_hints、files[{path,sha256,count?}]、adapter_version、normalizer_version、dry_run、creator。批次幂等键 = sha256(source_code + dataset_id + dataset_version + 规范化文件列表/哈希 + adapter_version)，其中参数变更必须产生新批次；单记录幂等由 source_id + external_id + source_revision 控制。示例见 examples/import-manifest.json。

## 4. 标准流水线（每阶段可重试/观测）

1. **Source registration**：登记来源所有者、许可证与展示范围；拒绝未知或失效授权，私有数据默认 quarantine。
2. **Upload + immutable raw archive**：校验 sha256、大小和 MIME、恶意文件扫描，保存原始包与每行 raw payload。
3. **Parse**：按适配器读取题号、年级、题干、图、子问、答案等；保留字段级抽取置信度；失败标记 PARSE_FAILED。
4. **Normalize**：转换 MathRichText、LaTeX、结构化 Part、选项/答案类型、知识点候选；附 normalizer_version；失败 NORMALIZE_FAILED。
5. **Schema / math checks**：JSON Schema、数学公式渲染、必填项、图片有效性、数值域、答案解析一致性；不满足条件进入 NEEDS_FIX。
6. **Exact identity matching**：先按 source_id+external_id 判定源记录是否已有；对相同内容 hash 仅创建候选映射，严禁根据 hash 直接合并版权和来源对象。
7. **Near-duplicate candidates**：中文/LaTeX/结构哈希、题干相似度、图像感知 hash、知识点/答案匹配，多信号聚合；打分仅供候选排序。
8. **Rights gate**：按动作 display/reproduce/adapt/redistribute/export、地域、用途、到期日评估；无法证明则隔离。
9. **Human review**：原题对照、数学答案审校、来源、版权、知识点、疑似重复；通过才允许发布。
10. **Publish + index**：发布不可变 Revision，出 outbox 事件，异步搜索索引/缓存刷新。
11. **Report**：逐行 retained/new_revision/duplicate_candidate/rejected/quarantined/published 结果可导出并可恢复。

## 5. 去重分级

L0 source identity：同一 source_id + external_id 即同一来源实体；原版本变化是 SourceRecordRevision 更新。

L1 exact normalized content：完全相同题目内容（含题干/条件/子问，必要时图片 hash），向运营提出“完全重复”候选。

L2 expression-aware：公式等价、空格/排版差异；注意数学假设、量词、定义域、上下标、向量符号和图像条件可能改变题目意义。

L3 semantic/isomorphic：解法结构相似或数值换参，标为 isomorphic/adapted，不合并内容身份。

相似度阈值必须由已标注样本标定，不能任意设 0.85 即自动合并。人工合并操作需要记录决策、来源映射、可逆关系与保留 redirect；如一个来源不许可公开，不能靠另一个来源“洗”出其受限内容。

## 6. 冲突策略

- 原来源内容更新：新增 source_record_revision，触发人工差异审阅；不得直接改写 published revision。
- 同 source_id+external_id 但重复版本标识内容 hash 变了：SOURCE_VERSION_CONFLICT，要求来源更正版本。
- 相同试卷编号不同文本：SOURCE_CONFLICT，校核官方原件与 OCR。
- 答案冲突：ANSWER_CONFLICT，阻断自动评分、人工定稿。
- 知识点名称冲突：建立 mapping，不擅自重命名对方源术语。
- 相同题干不同参数/小问：标记 variant 或 related，不盲目合并。
- 版权冲突：RIGHTS_HOLD，停止公开与导出，保留封存审计并处理申诉。

## 7. 版本、回滚与同步

外部记录版本单调跟踪，但不假定所有伙伴都有 revision；可以用原始 hash 生成 content_revision_key。支持 initial/full/incremental/delta/deletion 标记；伙伴删除记录时进入 tombstone review，不将用户历史提交级联删除。支持 dry-run 预检、指定失败行重放、同一批次幂等重放、撤销本批“未发布草稿”；已发布内容回滚走撤稿/新修订而非物理删除。

## 8. 导入运营数据

批次指标：读取数、解析成功数、规范化成功数、候选重复数、待审核数、审核通过数、发布数、版权隔离数、失败数；发布通过率按来源/版本追踪。重点监控 SLO：批次任务心跳、单行失败可见性、原始数据可恢复、导入幂等。P0 验证样本：重跑五次零重复、断点恢复、不可信 OCR 拦截、超期授权禁发、双源同题合并不丢归属。

## 9. 多题库规模化原则

1. 新接一个题库，只新增 source/rights/adapter/config，不修改核心 Problem/Submission 表。
2. 每个来源拥有自己的 source namespace、知识点 mapping、难度映射、许可证。
3. 大批量数据先导入 landing/staging，经过质量门禁再进入 published。
4. 搜索索引可重建；主库 + 原始资产是 source of truth。
5. 权利授权是可撤销、可到期和按使用场景约束的；不是简单布尔值 copyrighted=false。
6. 每个导入结果可解释：哪一行、用什么 adapter、何时、生成了何种身份/版本、为何接受/拒绝。

## 10. 实施验收样本

A：原创函数题重复上传 5 次仅产生 1 SourceRecord。B：另一授权来源上传同题生成 duplicate_candidate，不会删除第二来源归属。C：同题“x>0”被误改为“x≥0”触发语义差异，必须人工审核。D：来源授权过期，所有公共访问在不修改学生历史下被拒绝。E：一批 1000 条有 20 条坏记录，其余 980 条仍可入待审区并导出失败明细。F：同源 external_version 冲突直接中止该记录。
