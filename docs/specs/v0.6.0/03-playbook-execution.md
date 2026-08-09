# Playbook Execution

Status: Confirmed

## 1. Purpose

保留低心智成本的 Python `run()` 编程模型，同时增加可选的 UI 可见运行消息、明确时间、崩溃恢复和只读运行历史。

该设计不是工作流引擎，也不要求开发者拆分或声明执行阶段。

## 2. Authoring model

Playbook 继续由 Python 代码定义：

```python
class Playbook(BasePlaybook):
    NAME = "Contain Endpoint"
    DESC = "Contain the endpoint associated with the case."
    TAGS = ["EDR", "Response"]
    RISK_LEVEL = "High"

    def run(self):
        self.add_run_message("Collecting endpoint context.")
        endpoints = collect_endpoints(self.case)
        self.add_run_message(f"Collected {len(endpoints)} endpoint(s).")

        for endpoint in endpoints:
            contain(endpoint)

        self.add_run_message("Containment requests submitted.")
        return f"Contained {len(endpoints)} endpoint(s)."
```

规则：

- `run()` 仍是唯一执行入口。
- `add_run_message(message)` 完全可选；现有 v0.5.2 Playbook 无需修改即可运行。
- Run Message 只是当前 Run 的 UI 可见文本，不保存 Python 返回值或执行上下文。
- 平台不捕获 `print()` 或 Python `logging` 输出；服务器日志与 UI 可见消息保持分离。
- `run()` 未捕获异常导致整个 Run Failed。
- 开发者可以捕获可容忍错误，并通过 `add_run_message()` 写入安全说明。
- Playbook 可直接使用 `httpx` 或厂商 SDK；平台不提供通用 Connector。

## 3. Explicit exclusions

- 可视化/表单式编排器。
- DAG、分支、并行 Step。
- 中途人工审批；点击 Run 即授权整个 Playbook。
- Pending 或 Running 取消。
- 专用 Retry、retry lineage 或单步 resume。
- 结构化 Stage 或执行步骤。
- 自动捕获 `print()` 或 Python `logging`。
- 源码、hash 或定义版本锁定。
- 结构化 input schema。
- HTTP/Webhook Connection profile。
- 自动轮询或 WebSocket 进度。

## 4. Definition metadata

定义扫描继续读取：

- `NAME`
- `DESC`
- `TAGS`
- 新增 `RISK_LEVEL`

风险枚举：

- Low
- Medium
- High
- Critical

默认 Low。风险只用于 UI 展示，不改变权限、确认或执行流程。

Definition 选择界面展示当前扫描到的 metadata。Run 不保存 metadata 快照，历史列表和详情只展示 Run 已保存的 name，不解析当前定义。

Pending 执行时始终加载当前最新 Python 代码。

## 5. Run model

现有 `Playbook` 记录继续作为 Run，可考虑重命名 Python 类但不要求修改 db_table。

新增/调整字段：

| Field | Type | Semantics |
| --- | --- | --- |
| job_status | enum | Pending/Running/Success/Failed |
| job_id | string/UUID | 当前执行标识 |
| started_at | nullable datetime | claim 成功时间 |
| finished_at | nullable datetime | terminal 时间 |
| remark | text | 终态安全摘要 |

保留：

- case
- name
- user
- user_input
- created_at/updated_at

### Status transitions

| Current | Allowed next |
| --- | --- |
| Pending | Running |
| Running | Success, Failed |
| Success | none |
| Failed | none |

不允许直接修改 job_status。所有状态变化通过 domain service。

### Timing

- Pending 创建时 started_at/finished_at 为空。
- Pending→Running 设置 started_at。
- Running→Success/Failed 设置 finished_at。
- duration_seconds 由 started_at 和 finished_at 计算；Running 使用 now-started_at。

## 6. Run Message model

建议模型 `PlaybookRunMessage`：

| Field | Type | Notes |
| --- | --- | --- |
| id | UUID | primary key |
| playbook_run | FK | CASCADE at DB level, though Run API cannot delete |
| sequence | positive bigint | per Run append order |
| message | text | UI-visible safe message |
| created_at | datetime | append time |

Constraints/indexes:

- unique `(playbook_run, sequence)`.
- index `(playbook_run, sequence)`.
- message 经过长度限制。

### `add_run_message()` behavior

调用 `self.add_run_message(message)`：

1. 只接受非空字符串。
2. 对 message 执行敏感字段过滤和长度限制。
3. 原子分配当前 Run 的下一个 sequence。
4. 持久化消息，供 Run 详情 UI 按 sequence 展示。

该方法返回 `None`，不提供 level、结构化字段、进度百分比或消息更新能力。开发者应记录少量有意义的执行信息，而不是逐条输出循环数据。

### Output safety

- 不自动 `str()` 或 JSON serialize 任意函数输出。
- 不自动保存 HTTP response、LLM output、SIEM records 或变量值。
- message 由自定义代码显式提供，并视为最终用户可见内容。
- message 使用统一 sanitizer，至少屏蔽 password/token/api_key/secret/authorization 等值。
- API 不返回 traceback。

## 7. Queue and Worker behavior

### Supported topology

- 正式支持一个 Playbook Worker。
- 全局 FIFO，按 created_at/id claim。
- 不按 Case Severity 或用户优先级排序。

### Duplicate launch

Run endpoint 不提供 idempotency。重复请求可以创建多条 Pending Run，这是已接受行为。

### Worker loss

Playbook Worker 使用 Worker Health 心跳。检测到前一实例丢失后：

- 遗留 Running Run 标记 Failed。
- remark 使用固定安全文本，说明 Worker stopped before completion。
- 不自动重置 Pending 或重跑。
- 用户检查后可重新发起 Run。

实现可在 Worker 成功获取 singleton lease 后执行 orphan recovery。不得仅按运行时长把合法长任务判失败。

## 8. Launch

`POST /api/playbooks/run/`

- Admin/User 可运行，Viewer 403。
- 任何 Case 均可运行，包括 Closed。
- Case Relationship 不影响运行 eligibility。
- name 必须能在当前定义扫描中找到。
- user_input 是可选自由文本。
- 点击 Run 直接创建 Pending，不增加确认。
- risk level 只展示。

## 9. API shape

Playbook Run 资源改为 read-only：

- GET list。
- GET retrieve。
- GET definitions。
- POST run。
- GET messages（detail action 或独立 nested endpoint）。

禁止：

- 普通 POST create。
- PUT/PATCH。
- DELETE。

Run Message API：

- 只读。
- 必须按 sequence 分页。
- 不得一次返回无限消息。

### Run response additions

```json
{
  "id": "...",
  "playbook_id": "playbook_000123",
  "job_status": "Running",
  "started_at": "2026-07-30T08:00:00Z",
  "finished_at": null,
  "duration_seconds": 42
}
```

## 10. Remark semantics

| Terminal state | Remark |
| --- | --- |
| Success | `str(run() return value)`，经长度限制和安全处理 |
| Failed | 固定安全摘要 |

Run Message 不得拼接到 remark。原始异常只进服务器日志。

## 11. Notifications

遵循发起用户现有 `notify_on_playbook_completion` 偏好：

- Success 通知。
- Failed 通知。
- Run Message 不通知。

## 12. Audit

只记录用户动作：

- launch

Worker 自动状态变化不写全局 AuditLog，因为 Run 和 Run Message 已是状态事实。

Audit metadata 不包含 user_input 全文、Run Message 或任何 Secret。

## 13. Frontend

### Definition selection

- 显示 name、description、tags、risk level。
- 点击 Run 直接排队。
- 保留自由文本 user_input。

### Run list/detail

- 状态、Case、发起人、时间和 duration。
- Run/Run Message 无 Delete/Edit。
- Run Message 在详情中按 sequence 分页展示。
- 页面不自动轮询、不使用 WebSocket；提供 Refresh。

## 14. Migration

- 现有四状态数据直接保留。
- 已有 Success/Failed Run 的 started_at 可为空，不伪造历史时间。
- 旧 Running Run 在升级后由首次 Worker recovery 处理。
- started_at、finished_at 均 nullable。

## 15. Acceptance criteria

1. v0.5.2 旧 Playbook 不修改即可运行。
2. 可选 `add_run_message()` 按 sequence 保存并可在 UI 查询。
3. Run 异常导致 Run Failed，API 不泄露 traceback。
4. Run/Run Message 所有普通 mutation/delete 被拒绝。
5. FIFO claim 可预测。
6. Worker 崩溃后遗留 Running 标记 Failed且不自动重跑。
7. Closed Case 可运行，Case Relationship 不影响运行。
8. Success/Failed 通知符合用户偏好。
9. Run Message 数量大时 API 正确分页。

## 16. Known tradeoffs

- 最新代码执行使 Pending Run 语义可能在排队期间变化。
- 历史 Run 不展示 description、tags 或 risk level。
- 重复 launch 可产生重复外部副作用。
- Pending 和 Running 均不可取消。
- Failed Run 没有专用 Retry；用户需要重新发起。
- 频繁调用 `add_run_message()` 可能产生大量数据，开发者需自律；平台只通过分页保护读取。
- 直接 httpx 调用的重试、幂等和 Secret 安全由自定义代码负责。
