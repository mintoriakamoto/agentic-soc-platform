# Bulk Case Triage

Status: Confirmed

## 1. Purpose

允许分析师在 Case 列表中明确勾选一组 Case，一次修改相同的分诊字段。该功能优化重复人工操作，不替代 Case Relationships、抑制规则、AI 分析或 Playbook。

## 2. Scope

### Included

- 仅 Case 支持批量分诊。
- 一次可组合修改 Assignee、Status、Severity、Verdict。
- 最多 100 个显式 Case ID。
- 支持跨分页选择。
- 同步执行并返回逐 Case 成功或失败结果。
- 允许部分成功。

### Excluded

- Alert 批量分诊。
- Priority 和 Tags 批量修改。
- 对当前筛选结果全部执行。
- 后台批量任务。
- 服务端幂等键。
- updated_at 乐观锁。
- 批次级 AuditLog 实体。

## 3. Permission matrix

| Action | Admin | User | Viewer |
| --- | --- | --- | --- |
| Select cases | Yes | Yes | No |
| Bulk update any case | Yes | Yes | No |
| Bulk assign to any valid user | Yes | Yes | No |
| Bulk close | Yes | Yes | No |

权限必须在服务端检查。User 不受 assignee 所有权限制。

## 4. Shared Case state machine

单条 PATCH 与 bulk triage 必须调用同一个 domain service，不得分别维护状态逻辑。

### Allowed transitions

| Current | Allowed next |
| --- | --- |
| New | In Progress, Closed |
| In Progress | On Hold, Resolved, Closed |
| On Hold | In Progress, Resolved, Closed |
| Resolved | In Progress, Closed |
| Closed | In Progress |

相同状态写入可以作为无变化字段跳过，不应产生状态错误。

### Transition side effects

- Case 第一次离开 `New` 时设置 `acknowledged_time=now()`。
- `acknowledged_time` 设置后永久保留，Reopen 不重置。
- 进入 `Closed` 时设置 `closed_time=now()`。
- 进入 `Closed` 必须在最终状态上存在非空 Verdict，并要求本次请求提供 disposition note。
- `Closed → In Progress` 是 Reopen：
  - 清空 `closed_time`。
  - 清空 `verdict`。
  - 保留 Summary、acknowledged_time 和历史审计。
- 其他离开 Closed 的路径不存在。

状态机应作为可复用服务，例如 `apps.cases.services.transition_case()`；Serializer 和 bulk endpoint 都调用它。

## 5. Editable field semantics

### Assignee

- 字段未包含：保持不变。
- 提供有效用户 ID：设置新 assignee。
- 显式 `null`：取消分配。
- 不允许设置不存在或不可用的用户。

### Status

- 字段未包含：保持不变。
- 必须是 CaseStatus 枚举。
- 必须满足共享状态机。
- Status 不允许清空或设为 null。

### Severity

- 字段未包含：保持不变。
- 必须是 CaseSeverity 枚举。
- 不使用空字符串表达清空；使用 `Unknown`。

### Verdict

- 字段未包含：保持不变。
- 必须是 CaseVerdict 枚举。
- 非 Closed Case 可以显式设为 null/空值以清空 Verdict。
- 请求结束后的 Case 若为 Closed，Verdict 必须非空。
- 不允许只清空 Closed Case 的 Verdict。

### Multi-field evaluation

校验应基于本次请求全部字段应用后的最终 Case 状态，而不是按 JSON 字段顺序执行。例如同一次请求可以把 New Case 设为 Closed 并提供 Verdict。

## 6. Bulk close note

进入 Closed 时 `reason` 必填。该文本同时用于审计和 Summary 追加。

Summary 追加格式：

```markdown

### Bulk disposition · 2026-07-28 10:44 UTC · alice

Confirmed as false positive after campaign review.
```

规则：

- 保留现有 Summary。
- 现有 Summary 与新段落之间插入空行。
- 标题时间使用 UTC 的稳定格式。
- actor 使用当前用户名。
- 对每个成功关闭的 Case 追加相同说明。
- 普通分配、Severity、Status 或 Verdict 修改的 reason 可选；如果提供，只写审计，不追加 Summary。

## 7. API

### Endpoint

`POST /api/cases/bulk-triage/`

这是 Case 专用 collection action，不实现通用 bulk PATCH。

### Request

```json
{
  "case_ids": [
    "6387d62e-4ed6-45b4-b83a-522cd7b5e845",
    "b109ce5c-956a-42d5-b53c-bc883d19dbfc"
  ],
  "changes": {
    "assignee": "e0602519-1cd0-4750-80af-aac269a98722",
    "status": "In Progress",
    "severity": "High",
    "verdict": "Suspicious"
  },
  "reason": "Campaign triage"
}
```

Validation:

- `case_ids` 必须是非空数组。
- 去重后最多 100 个。
- ID 必须是合法 UUID；请求结构中的非法 UUID 是请求级 400，而不存在的合法 UUID 是逐项失败。
- `changes` 至少包含一个允许字段。
- 不接受 Priority、Tags 或其他字段。
- `reason` 去除首尾空白后校验。
- 如果请求的最终目标状态是 Closed，reason 必填。

### Success and partial success response

只要请求结构有效，返回 HTTP 200：

```json
{
  "operation_id": "a143bc8b-df7b-40d8-b0ee-e5df4e7efdc4",
  "requested": 2,
  "succeeded_count": 1,
  "failed_count": 1,
  "succeeded": [
    {
      "id": "6387d62e-4ed6-45b4-b83a-522cd7b5e845",
      "case_id": "case_000123",
      "updated_at": "2026-07-28T02:44:00Z"
    }
  ],
  "failed": [
    {
      "id": "b109ce5c-956a-42d5-b53c-bc883d19dbfc",
      "case_id": "case_000124",
      "code": "invalid_transition",
      "detail": "Case cannot transition from New to Resolved."
    }
  ]
}
```

允许的安全失败码至少包括：

- `not_found`
- `permission_denied`
- `invalid_transition`
- `invalid_final_state`
- `invalid_assignee`
- `update_failed`

不得在 `detail` 返回 traceback 或数据库错误。

### Request-level errors

以下返回 400，不处理任何 Case：

- 空 case_ids。
- 超过 100 个 ID。
- 非法 UUID。
- changes 为空。
- 未知字段。
- 非法枚举值。
- 目标 Closed 但 reason 缺失。

401/403 使用现有认证和权限响应。

## 8. Transaction and failure behavior

- 整批不使用一个全局原子事务。
- 每个 Case 在自己的短事务中读取、应用状态机、保存并写 AuditLog。
- 一个 Case 失败不得回滚已成功 Case。
- 使用 last-write-wins，不比较客户端看到的 updated_at。
- 在事务中读取最新 Case；只覆盖请求明确包含的字段。
- 前端请求进行中禁用提交按钮，平台不提供服务端 idempotency key。

## 9. Notifications

只有 assignee 实际变化时产生 assignment notification。

- 按最终 assignee 分组。
- 每位接收人一次批量请求最多收到一条 Inbox 消息。
- 消息包含成功分配给该用户的 Case 数量和可打开的 Case ID 列表。
- 失败 Case 不进入通知。
- 取消分配不发送通知。
- 如果 assignee 未改变，不发送通知。
- 通知在对应 Case 事务成功后统一生成；通知失败不得把已完成业务更新伪装为失败，应按现有通知错误策略显式记录。

## 10. Audit

每个成功 Case 写一条现有 `updated` AuditLog：

```json
{
  "action": "updated",
  "changes": {
    "status": {"from": "New", "to": "In Progress"},
    "severity": {"from": "Medium", "to": "High"}
  },
  "metadata": {
    "source": "bulk_triage",
    "operation_id": "a143bc8b-df7b-40d8-b0ee-e5df4e7efdc4",
    "reason": "Campaign triage"
  }
}
```

- 后端为每次请求生成一个 UUID operation_id。
- 同一请求的所有成功 Case 共享 operation_id。
- 不创建单独的批次 AuditLog。
- 无实际字段变化的 Case 可以视为成功，但不得写空 changes 审计；响应应包含 `unchanged: true`。
- 失败 Case 不写业务更新审计。

## 11. Frontend

### Selection

- 仅 Case 主列表启用批量分诊。
- 翻页保留选择。
- Search、普通 Filter 或 Advanced Filter 发生变化时清空选择。
- 不支持“Select all filtered results”。
- 最多选择 100 条；达到上限后其他 checkbox disabled，并显示上限提示。
- Toolbar 始终显示选中数量和 Clear selection。

### Bulk triage modal

- 用户点击 Bulk Triage 打开 Modal，不立即执行。
- 每个字段有独立“修改此字段”开关；未启用字段不进入 changes。
- Assignee 支持选择用户和 Unassigned。
- Status、Severity、Verdict 使用现有选项与 Tag 表现。
- reason 默认可选；Status 选择 Closed 后立即变为必填并解释会追加到 Summary。
- 显示选中数量、字段变更预览和关闭副作用。
- 提交期间禁用所有操作。

### Result handling

- 成功项从 selection 移除。
- 失败项保持选中。
- 显示成功/失败汇总。
- 失败列表显示 Case ID、失败码对应的用户可读说明。
- 不自动重试。
- 刷新当前列表数据，但不得因刷新清除失败 selection。

## 12. Backend implementation surfaces

预期涉及：

- `backend/apps/cases/services.py`：共享状态机和字段应用。
- `backend/apps/cases/serializers.py`：bulk request/response serializer。
- `backend/apps/cases/views.py`：collection action。
- `backend/apps/inbox/notifications.py`：汇总 assignment notification。
- `frontend/src/components/DataTable.tsx`：受控跨页 selection 和自定义 bulk action context。
- Case resource 页面：Bulk Triage modal 和结果展示。

不得把 Case 业务状态机写进通用 DataTable。

## 13. Acceptance criteria

1. Admin/User 可对 1–100 个 Case 组合修改四个允许字段。
2. Viewer 看不到操作并且 API 返回 403。
3. 跨页选择保留，筛选变化清空。
4. 非法状态转换只失败对应 Case，其他 Case 成功。
5. Closed 必须有最终 Verdict 和 reason。
6. Bulk close 正确追加带时间和 actor 的 Markdown Summary。
7. Reopen 清空 closed_time/verdict，保留 acknowledged_time/Summary。
8. assignment notification 按用户汇总。
9. 每个成功 Case 有 source、operation_id 和 changes 审计。
10. 请求级错误不产生任何 Case 更新。
11. medium 数据集下 100 条同步请求可在正式验收设定的超时内完成。

## 14. Known tradeoffs

- last-write-wins 可能覆盖并发编辑，这是已接受行为。
- 没有服务端 idempotency，客户端网络重试可能重复追加 close note；前端必须避免自动重试 POST。
- 部分成功使一次 operation_id 不代表全量成功；响应和逐 Case 审计是事实来源。
