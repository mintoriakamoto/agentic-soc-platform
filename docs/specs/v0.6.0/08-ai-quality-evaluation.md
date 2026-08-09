# AI Quality Evaluation

Status: Confirmed

## 1. Purpose

比较 Closed Case 的最终人工结构化判断与关闭前最后一次有效 AI 分析结果，形成可解释的 AI–Human Agreement 指标。

该功能不宣称人工标签是绝对真相，因此产品文案不用 Accuracy/Correctness。它不评价报告文字质量，也不自动优化 Prompt。

## 2. Evaluated fields

逐项比较：

- Verdict ↔ verdict_ai。
- Severity ↔ severity_ai。
- Impact ↔ impact_ai。
- Priority ↔ priority_ai。
- Confidence ↔ confidence_ai。

不合成总质量分。

## 3. Reference prediction

每个 Case 的主质量样本最多一个，使用：

1. status=Success 的 CaseAnalysisJob。
2. completed_at 不晚于当前 closed_time。
3. Job 原本针对该目标 Case 运行。
4. 满足以上条件的最后一次 Job。

复用 `CaseAnalysisJob.result_json`，不创建独立 Prediction 表。

## 4. Metadata exclusion

AI Quality 不新增、使用或展示：

- Provider。
- Model。
- Prompt ID/content/hash/language。
- Profile version。
- Trigger。
- base URL。
- Input payload。

即使 CaseAnalysisJob/AnalysisRecord 当前已有部分字段，全局质量页面也不按这些维度过滤。已接受的限制是无法比较模型或 Prompt 版本质量。

## 5. Evaluation trigger and lifecycle

### Create

Case 进入 Closed 时创建当前 Evaluation，快照：

- 参考 Job。
- 五个 AI 值。
- 五个人工值。
- Case category。
- Assignee。
- closed_time。
- evaluated_at。

### Closed field correction

Case 保持 Closed 时修改任一人工比较字段，提交 Case 后重建同一 Evaluation。Category/Assignee snapshot 也随重建刷新。

### Reopen

Case Reopen 时删除当前 Evaluation。开放 Case 不进入质量统计。再次 Closed 后重新创建，不保留第一次关闭的质量版本。

### Delete

Evaluation 不提供独立 mutation API，随 Case 删除级联。Reference CaseAnalysisJob 不允许独立删除。

### Failure isolation

Evaluation 构建失败不得阻止 Case Close、Reopen 或人工字段修改：

- Case transaction 先成功。
- commit 后执行重建。
- 失败写安全日志。
- 提供 `rebuild_ai_quality_evaluations` 管理命令用于回填和修复。
- 不新增专用 Worker。

实现不得返回“失败形状的成功”。Case API 可成功，但日志和后续 reconciliation 必须发现缺失 Evaluation。

## 6. Coverage states

每个 Closed Case Evaluation 状态：

- Evaluated：有 eligible Job 且 result_json 可解析。
- No prediction：没有 eligible Job。
- Invalid prediction：eligible 成功 Job 的 result_json 无法解析所需结构。

Prediction Coverage：

```text
Evaluated Cases / all filtered Closed Cases
```

No prediction 和 Invalid prediction 都在分母、不在分子。页面单独显示 Invalid count。

存在 Job 即使某个 AI 字段为空，Case 仍可为 Evaluated；该字段单独 Not evaluable。

## 7. Missing values

每个字段只有 AI 和人工值都存在时才进入该字段 agreement 分母。

- AI 空：Not evaluable。
- 人工空：Not evaluable。
- 双方空：Not evaluable。
- Unknown 是显式有效值，不等于空。

Close 不强制五个人工字段全部填写；现有 Verdict 关闭约束保持。

## 8. Comparison semantics

### Verdict

- 使用完整 CaseVerdict 枚举。
- exact agreement。
- 完整 confusion matrix。
- 不归并二分类或三分类。

### Ordinal fields

Severity、Impact、Priority、Confidence：

- exact agreement。
- absolute ordinal distance。
- AI overestimate。
- AI underestimate。

等级顺序使用现有枚举的业务顺序。Unknown：

- 参与 exact agreement。
- 进入 confusion counts。
- 任一方 Unknown 时不计算 distance/direction。

### Naming

所有 UI/API 文案使用：

- AI–Human Agreement。
- Agreement rate。
- Mismatch。
- Overestimate/Underestimate。

不使用 AI Accuracy、Correctness 或 analyst accuracy。

## 9. Data model

每 Case 一条 OneToOne `AiQualityEvaluation`，显式字段而非 JSON。

建议字段：

- case OneToOne。
- reference_job nullable FK。
- coverage_state。
- ai_verdict / human_verdict / verdict_agrees。
- ai_severity / human_severity / severity_agrees / severity_distance / severity_direction。
- ai_impact / human_impact / impact_agrees / impact_distance / impact_direction。
- ai_priority / human_priority / priority_agrees / priority_distance / priority_direction。
- ai_confidence / human_confidence / confidence_agrees / confidence_distance / confidence_direction。
- category_snapshot。
- assignee_snapshot nullable FK。
- closed_at。
- evaluated_at。

派生字段保存为显式 nullable 列，方便 PostgreSQL 聚合与筛选；重建时一次计算。

建议索引：

- closed_at。
- coverage_state。
- category_snapshot。
- assignee_snapshot。
- human_severity。
- 各 agrees 字段按实际查询计划决定组合索引。

## 10. Case relationships

- Case Relationship 不改变 Evaluation 创建、选择或聚合。
- 每个 Case 只使用自身 eligible Job 和人工字段。
- 正式关系与 Artifact suggestion 均不进入 AI Quality 查询条件。

## 11. Historical backfill

升级时/升级后管理命令回填：

- 当前 Closed。
- 使用当前人工字段。
- 选择 closed_time 前最后 eligible 成功 Job。
- 没有 Job 创建 No prediction。
- 解析失败创建 Invalid prediction。
- 不调用 LLM。
- 不产生通知或 Evaluation AuditLog。

## 12. Permissions

| Surface | Admin | User | Viewer |
| --- | --- | --- | --- |
| Current Case comparison | Yes | Yes | Yes |
| Global summary | Yes | No | No |
| Global samples | Yes | No | No |
| Mutation | No | No | No |

Assignee 可用于 Admin 筛选，但不提供分析师排行榜、最好/最差排名或绩效分。

## 13. Global analytics

位置：`System Settings → AI Quality`。

默认最近 30 天，时间维度为 Case closed_time。

筛选：

- closed time range。
- category snapshot。
- human severity。
- assignee snapshot。
- coverage state。

不按 model/provider/prompt/profile/trigger 过滤。

### Required metrics

- Prediction Coverage 和 total count。
- Evaluated/No prediction/Invalid counts。
- 五字段 exact agreement rate + sample count。
- Verdict confusion matrix。
- 四个 ordinal 字段 mean absolute distance。
- 四个 ordinal 字段 over/under/match counts。
- 五字段 agreement trend。

不提供：

- composite score。
- pass/fail threshold。
- 红黄绿目标。
- severity weighted score。
- analyst leaderboard。

### Trends

- ≤31 天：daily。
- 32–180 天：weekly。
- >180 天：monthly。
- 每点包含 sample count。
- 空桶不返回，不显示为 0%。

## 14. Sample drilldown

Admin-only 分页表：

- Case ID/title link。
- closed_at。
- assignee snapshot。
- category/human severity。
- coverage state。
- 五组 AI/human values。
- agreement/direction/distance。

筛选：

- mismatch field。
- only mismatches。
- global filters。

不在表中返回完整 Investigation Report、Analysis input、知识上下文或原始 Job JSON。

## 15. Case UI

现有 Investigation Tab 顶部增加五行对比表：

- Field。
- AI value。
- Human value。
- Agreement。
- Direction/distance（适用时）。

显示：

- No prediction。
- Invalid prediction。
- Not evaluable。

不新增独立 Case Quality Tab。完整报告继续使用现有 Investigation view。

## 16. API

### Global summary

`GET /api/ai-quality/summary/`

- Admin-only。
- 接收已确认筛选。
- 返回 coverage、agreement、matrix、ordinal stats、trend。
- PostgreSQL 实时聚合。

### Samples

`GET /api/ai-quality/evaluations/`

- Admin-only。
- cursor/page pagination。
- 返回安全结构化快照。

### Case surface

Case Investigation 或 Case detail 的只读字段返回当前 Evaluation。User/Viewer 可读。

无 create/update/delete API，无 CSV/JSON export。

## 17. Aggregation

- 实时 PostgreSQL 查询。
- 默认 30 天。
- medium 基线最多约 10,000 Evaluation，不新增缓存/Worker/materialized daily table。
- closed_at 和筛选维度必须有适当索引。
- API 必须返回 sample counts，避免小样本误解。

## 18. Audit

- Evaluation create/rebuild/delete 不写 AuditLog。
- Admin 查看 summary/sample 不写 AuditLog。
- Case Close/Reopen/人工字段修改沿用现有 Case audit。
- reference_job 和 evaluated_at 用于技术追溯。

## 19. Acceptance criteria

1. 五个字段比较正确且不合成总分。
2. 最新 eligible pre-close Job 选择正确。
3. Case Relationship 不改变 reference Job 选择。
4. Unknown 和 empty 语义正确。
5. Verdict matrix 和 ordinal direction/distance 正确。
6. Close 创建，Closed edit 重建，Reopen 删除，Reclose 重建。
7. Evaluation 故障不阻止 Case 业务操作，并可管理命令修复。
8. 历史 Closed Case 正确回填，不调用 LLM。
9. 关联 Case 仍分别进入各自符合条件的统计样本。
10. Coverage denominator/numerator 和 Invalid count 正确。
11. Admin-only 全局页面，所有角色单案可见。
12. 筛选使用 Evaluation snapshot 和 closed_time。
13. 自适应趋势和 sample count 正确。
14. API 不暴露 report/input/provider/model/prompt metadata。
15. medium 数据实时聚合满足最终验收阈值。

## 20. Known tradeoffs

- 无模型/Prompt 元数据，无法解释版本变化导致的趋势。
- 人工字段只是参考标签，不是绝对 ground truth。
- Closed 后重建覆盖旧质量结果，不保留 closure version。
- Evaluation 失败与 Case 关闭隔离，短时间内统计可能缺少样本，依赖 reconciliation。
- 无报告正文质量反馈、导出、阈值和自动学习。
