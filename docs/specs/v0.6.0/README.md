# ASP v0.6.0 specification index

本目录是 v0.6.0 的跨会话实施依据。已完成讨论的功能使用实施级 Spec 固化；尚未完成讨论的功能只记录 TODO 和待决策问题，不得把 TODO 中的推荐项当作已经确认的需求。

## 已确认 Spec

| 文档 | 状态 | 内容 |
| --- | --- | --- |
| [00-release-scope.md](00-release-scope.md) | Confirmed | 版本目标、部署边界、兼容矩阵、容量、权限与排除项 |
| [01-bulk-case-triage.md](01-bulk-case-triage.md) | Confirmed | Case 批量分诊、共享状态机、通知与审计 |
| [02-case-relationships.md](02-case-relationships.md) | Confirmed | Case 弱关联、关系约束、Artifact 候选与 Agent 读取 |
| [03-playbook-execution.md](03-playbook-execution.md) | Confirmed | Playbook Run、结构化 Stage、取消、重试与 Worker 语义 |
| [05-worker-health.md](05-worker-health.md) | Confirmed | Redis 心跳、Worker 状态与 Admin API |
| [07-sla-management.md](07-sla-management.md) | Confirmed | TTD/TTA/TTR 时限、Severity 策略、通知和 Dashboard 达标率 |
| [08-ai-quality-evaluation.md](08-ai-quality-evaluation.md) | Confirmed | AI–Human Agreement、Coverage、混淆矩阵和样本下钻 |

## 待讨论

[TODO-remaining-domains.md](TODO-remaining-domains.md) 仅记录版本验收。所有 v0.6.0 功能域均已确认或明确排除。

## 实施顺序

1. 先完成 Case 状态机，再实现批量分诊和 Case Relationships。
2. 完成 Playbook Run/Stage。
3. 完成通用 Worker Health 基础设施并接入五类 Worker。
4. 完成 SLA 和 AI Quality。
5. 最后统一补齐 v0.6.0 验收规范。

## Spec 使用规则

- `Confirmed` 表示产品决策已确认，实施不得自行改变行为。
- Spec 中的模型名和 URL 是目标设计；若代码库已有命名约束冲突，可以做等价调整，但外部行为必须一致。
- 每项功能必须同时覆盖后端、前端、权限、审计、迁移和失败行为。
- v0.6.0 允许破坏性 API 调整，不需要兼容旧 CLI 或插件。
- 不得把本目录复制到 `asp-doc` 作为用户文档；用户文档应在功能实现定型后另行编写。
