# SLA Management

Status: Confirmed

## 1. Purpose

为升级后新建的 Case 建立按 Severity 配置的 TTD、TTA、TTR 时限，向负责人提示即将超时和已经超时的工作，并在 Case 和 Dashboard 中提供与现有平均时间指标完全一致的达标统计。

## 2. Terminology and formulas

单个 Case 使用不带 Mean 前缀的名称：

| Per-Case | Formula | Dashboard aggregate |
| --- | --- | --- |
| TTD, Time to Detect | earliest valid Alert.first_seen_time → Case.created_at | MTTD |
| TTA, Time to Acknowledge | Case.created_at → Case.acknowledged_time | MTTA |
| TTR, Time to Resolve | Case.acknowledged_time → Case.closed_time | MTTR |

规则：

- `M` 仅表示多个样本的 Mean。
- Dashboard 现有 MTTD/MTTA/MTTR 公式必须与上表一致。
- created_at→closed_time 可以作为总耗时展示，但没有独立 SLA target。
- 全部使用 24×7 elapsed seconds，不使用工作时间、节假日或暂停时钟。

## 3. Policy

每个 CaseSeverity 一行全局策略：

| Severity | TTD | TTA | TTR |
| --- | ---: | ---: | ---: |
| Critical | 300s | 900s | 14,400s |
| High | 900s | 1,800s | 28,800s |
| Medium | 1,800s | 7,200s | 86,400s |
| Low | 7,200s | 28,800s | 259,200s |
| Informational | 28,800s | 86,400s | 604,800s |
| Unknown | 3,600s | 14,400s | 172,800s |

- v0.6.0 中 SLA 始终启用。
- 六行和三项目标都必填。
- 每个目标为整数 seconds，范围 60 秒到 365 天。
- 不要求 TTD ≤ TTA ≤ TTR，因为三者覆盖不同阶段。
- 不按 Category、Tag、Assignee 或业务组配置。

### Policy model

建议 `SlaPolicy`：

- severity，unique。
- ttd_target_seconds。
- tta_target_seconds。
- ttr_target_seconds。
- created_at/updated_at。

Settings API 一次提交全部六行，并在一个事务中全部保存。任一值非法则全部拒绝。

## 4. Snapshot semantics

每个阶段开始时快照当时 Severity 和 target：

- TTD：Case 创建时。
- TTA：Case 创建时。
- TTR：首次 acknowledged_time 设置时。

之后修改 Case Severity 不改变已经开始或完成的阶段。

策略修改只影响未来创建的阶段快照：

- 新 Case 的 TTD/TTA 使用新策略。
- 旧但尚未 acknowledge 的 Case，其 TTR 在未来开始时使用新策略。
- 不批量重算已有快照。

## 5. CaseSla model

每个参与 SLA 的 Case 一条 OneToOne `CaseSla`，不用 JSON 或通用 metric child table。

每项指标明确保存：

- severity_snapshot。
- target_seconds。
- started_at。
- ended_at。
- deadline_at。
- elapsed_seconds。

补充字段：

- case OneToOne。
- created_at/updated_at。

建议索引：

- tta_deadline_at，配合 acknowledged_time/null 或等价 active marker。
- ttr_deadline_at，配合 closed_time/null。
- CaseSla.case unique。

状态不周期写入数据库，按快照、当前时间和完成时间动态计算。

## 6. Metric states

通用状态：

- Pending。
- Warning。
- Met。
- Breached。
- Not applicable。

未完成指标：

- elapsed < 80% target：Pending。
- 80% ≤ elapsed < 100%：Warning。
- elapsed ≥ target：Breached。

已完成指标：

- elapsed ≤ target：Met。
- elapsed > target：Breached。
- 完成后超时仍保持 Breached，不增加 Completed late。

### TTD subset

TTD 在被观察时已经完成，因此只可能：

- Met。
- Breached。
- Not applicable。

TTD 不进入 Pending 或 Warning。

### TTR before acknowledgement

尚未 acknowledge：

- UI state 显示 Pending。
- started/deadline/elapsed 为空。
- 标注 `Starts after acknowledgement`。
- SLA Worker 不扫描 Warning/Breach。

不计算 Case overall SLA 状态。TTD、TTA、TTR 始终独立展示和筛选。

## 7. TTD behavior

### Valid source

使用当前 Case 下最早的有效 Alert.first_seen_time，要求：

- 非空。
- `first_seen_time <= Case.created_at`。

没有有效时间时：

- TTD=Not applicable。
- 不进入达标率分母。
- 不使用 Alert.created_at、Case.created_at 或 0 秒兜底。

### Recalculation

以下情况重算 TTD start、elapsed 和 result：

- Alert 创建并关联 Case。
- Alert.first_seen_time 修改。
- Alert 移动到其他 Case。

TTD target 和 Severity snapshot 不变。更早 Alert 可能使 Met 变为 Breached。

## 8. TTA behavior

- Case 创建时立即启动。
- deadline=created_at + snapshotted target。
- Case 第一次离开 New 时设置 acknowledged_time 并结束。
- acknowledged_time 永久保留，Reopen 不重置。
- On Hold 不暂停。

## 9. TTR behavior

- 首次 acknowledged_time 设置时启动并快照当时 Severity/target。
- deadline=acknowledged_time + target。
- closed_time 设置时结束。
- On Hold 不暂停。
- Closed→In Progress Reopen 清空 closed_time 后，从原 acknowledged_time 恢复同一时钟。
- 再次 Closed 后使用新的 closed_time 作为当前最终结果。
- 原关闭历史只通过 AuditLog 保留。

### Direct New→Closed

状态机同时设置 acknowledged_time 和 closed_time：

- TTA=created_at→transition timestamp。
- TTR=0 秒，Met。

## 10. Upgrade boundary

- 只有 SLA migration/feature 启用后新建的 Case 创建 CaseSla。
- v0.5.2 已存在 Case 不回填，不展示 SLA 状态、不筛选、不通知、不进入达标率。
- 旧 Case 继续进入现有 MTTD/MTTA/MTTR mean，只要满足原查询条件。
- Dashboard 必须显示 mean 和 compliance 各自 sample count，因为样本集合不同。

## 11. Case relationships

- Case Relationship 不改变任何 Case SLA。
- 关联 Case 之间不共享 target、Severity snapshot、时钟、状态或通知。
- Artifact suggestion 和正式关系均不进入 SLA 查询条件。

## 12. Notifications

### Recipient

- 只通知当前 Assignee。
- 未分配 Case 不通知。
- Admin 不作为 fallback recipient。
- 用户不能关闭 SLA 通知。

### Events

- TTA Warning。
- TTA Breached。
- TTR Warning。
- TTR Breached。
- TTD Breached。
- 不发送 TTD Warning。
- 不发送 Met、恢复或完成通知。

Warning 和 Breached 分别通知。同一 recipient 最多各一次。Worker 首次看到已 Breached 时只发 Breached，不补发 Warning。

### Reassignment

按 CaseSla + metric + state + recipient 去重。当前状态已经 Warning/Breached 后重新分配，新 Assignee 在下一次扫描收到一次当前状态通知；原 Assignee不收到撤销消息。

### Notification storage

`CaseSlaNotification`：

- case_sla FK。
- metric enum TTD/TTA/TTR。
- state enum Warning/Breached。
- recipient nullable FK User，删除用户后 SET_NULL。
- sent_at。
- unique(case_sla, metric, state, recipient)；nullable recipient 的历史处理需保证不会影响实际去重。

通知记录不保存消息 Secret 或完整 Case 内容。

## 13. SLA Worker

新增单实例 `run_sla_worker`：

- 每 60 秒扫描。
- 接入 Worker Health，成为第 6 个 Worker。
- 只负责发现需通知状态并去重发送。
- API 状态仍动态计算，不依赖 Worker 更新状态。
- 对适用且未完成的 TTA/TTR 使用 deadline 索引扫描。
- 对 TTD Breached 和 reassignment 使用未通知查询。
- 一个通知失败不得吞掉；按 WorkerIterationResult.failure_count 进入 Degraded。
- 不发送外部 Webhook 或邮件。

## 14. API

Case list/detail 增加嵌套 SLA：

```json
{
  "sla": {
    "applicable": true,
    "ttd": {
      "state": "Met",
      "severity": "High",
      "target_seconds": 900,
      "elapsed_seconds": 420,
      "started_at": "...",
      "ended_at": "...",
      "deadline_at": "..."
    },
    "tta": {},
    "ttr": {
      "state": "Pending",
      "started": false
    }
  }
}
```

旧 Case：

```json
{"sla": {"applicable": false}}
```

Case list 支持每项 state filter 和 deadline ordering。不得用 Python 全量计算后分页；查询必须可在数据库层筛选。

Settings SLA API：

- Admin GET。
- Admin 原子 PUT/PATCH 全部六行。
- User/Viewer 403。
- seconds 为唯一 API 单位。

## 15. Frontend

### Case list

- TTA state 默认显示。
- TTR state 默认显示。
- TTD state 默认隐藏但可选。
- 三项分别筛选。
- TTA/TTR 支持 deadline 排序。
- 不显示 overall Tag。

### Case detail

SLA 区块分别显示：

- TTD/TTA/TTR。
- state。
- target。
- elapsed。
- start/end/deadline。
- Severity snapshot。
- TTR 未开始提示。

### Settings

`System Settings → SLA`：

- 六个 Severity 行。
- 三个目标列。
- UI 使用分钟/小时可读输入，提交转换为精确 seconds。
- 一次 Save 全部原子提交。
- 仅 Admin。

## 16. Dashboard

保留现有：

- MTTD mean/sample。
- MTTA mean/sample。
- MTTR mean/sample。

新增：

- TTD compliance rate/sample。
- TTA compliance rate/sample。
- TTR compliance rate/sample。
- 当前 TTA Warning count。
- 当前 TTA Breached count。
- 当前 TTR Warning count。
- 当前 TTR Breached count。

取样：

- TTD compliance：Case.created_at 在窗口。
- TTA compliance：acknowledged_time 在窗口。
- TTR compliance：closed_time 在窗口。
- 当前 Warning/Breached：所有活动且有 CaseSla 的 Case，不受创建时间窗口限制。

TTD 没有当前 Warning/Breach count。

## 17. Audit

- SLA policy 修改写 AuditLog，记录六行三项目标的 before/after seconds。
- 时间推移导致的 Pending/Warning/Breached/Met 不写 Case AuditLog。
- SLA Worker 扫描不写 AuditLog。
- CaseSlaNotification 提供发送历史。

## 18. Acceptance criteria

1. 单案 TTD/TTA/TTR 与 Dashboard MTTD/MTTA/MTTR公式一致。
2. 六个 Severity 默认值与范围正确，Admin 原子保存。
3. 每阶段按当时 Severity 快照，后续修改不追溯。
4. TTD 缺失时间为 NA，Alert 变化可重算。
5. TTA first-exit-New 结束，TTR acknowledge 开始。
6. On Hold 不暂停，Reopen 从原 acknowledge 继续。
7. Direct close 的 TTR=0 Met。
8. 80% Warning、100% Breached，完成后 late 仍 Breached。
9. 旧 Case 无 SLA，新 Case有 SLA。
10. Case Relationship 不改变任何 Case SLA 或达标率。
11. SLA Worker 每分钟运行并作为第 6 个 Worker 进入 Worker Health。
12. 仅当前 Assignee 强制接收去重 Warning/Breach。
13. 新 Assignee 可收到当前状态，未分配不通知。
14. Case list/detail、Dashboard 和 Settings 行为符合 Spec。
15. medium 数据规模下 active deadline 扫描使用索引，不全表 Python 计算。

## 19. Known tradeoffs

- 旧 Case 不进入达标率，升级初期样本较少。
- On Hold 持续计时，不反映净工作时间。
- 重开 Case 会持续拉长同一 TTR。
- Severity 变化不追溯，单 Case 不同阶段可能使用不同策略版本。
- TTD 可因迟到 Alert 从 Met 变为 Breached。
- 未分配 Case 不产生 SLA 通知。
