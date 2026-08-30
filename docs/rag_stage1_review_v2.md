# RAG Stage 1 Review v2：最小可运行黑板主链路

> 本文是 `docs/rag_stage1_review.md` 的执行版更新稿。目标是先把当前 CTF 求解场景完整跑通，不追求一次实现 Muteki 的全部高级能力。

## 1. 先说结论

Stage 1 只做一件事：把现在“每个 solver 自己从头解完整道题”的流程，改成“一个持久化黑板协调多个 Codex worker”的流程。

必须具备的闭环只有：

```text
开始题目 -> 黑板记录 -> coordinator 拆任务 -> Codex worker 认领任务
-> 使用现有 sandbox/tools -> 把结果写回黑板 -> coordinator 继续拆任务
-> CTFd 确认 flag -> 结束题目
```

本阶段不实现：向量 RAG、routes/branches、PoC 生命周期、事实审核/合并、资源锁、人工介入、复杂 trust level、UI 和自动知识总结。

## 2. 当前问题（大白话）

1. 现在的 `ChallengeSwarm` 会让每个 solver 各自解整道题，大家不是在分工，而是在重复比赛。
2. `findings` 和 `ChallengeMessageBus` 只是进程内字符串消息，程序重启后就没了，也不能可靠区分“事实”和“猜测”。
3. JSONL trace 只能回答“做过什么”，不能回答“下一步任务是什么、谁负责、任务是否完成”。
4. 当前 solver 的输出协议主要只有 `flag_found`，没有“我领取了哪个任务”“我发现了什么”“这条路走不通”等正式回写入口。
5. 当前 coordinator 能读 trace 和发消息，但没有一个持久化的共享状态可供它持续规划。

所以，单纯新增一个 evidence 目录或把日志写进 SQLite 不够；必须同时补上最小的任务认领和 worker 循环。

## 3. 已确定的范围

- “state 1”统一称为 **Stage 1**，不是额外的运行状态编号。
- 只支持当前 CTF 解题业务，不扩展其他业务场景。
- 只保留 Codex solver 实现；Pydantic/Claude 不属于本阶段交付。
- Muteki 只做语义参考，必要时复制少量实现；以简单、稳定、最小侵入为准。
- Muteki 参考源码目录：`/home/mengshancha/muteki-main`，主要参考 `muteki/swarm/shared_graph.py` 的事件追加、SQLite WAL 和原子 Intent claim 语义。
- 黑板从当前版本开始是唯一主状态。
- 继续保留 sandbox、动态工具、trace、flag 提交确认、成本/步数统计和必要的 quota fallback。
- 旧 findings/message bus 不再作为事实来源；最多在开发测试阶段做短期对比。

## 4. MVP 黑板定义

### 4.1 事件

所有状态都由 append-only `events` 事件产生。MVP 只实现这些事件：

| 事件 | 含义 |
| --- | --- |
| `challenge_started` / `challenge_finished` | 题目生命周期 |
| `intent_proposed` | coordinator 提出一个具体任务 |
| `intent_claimed` | 一个 worker 原子领取任务 |
| `intent_completed` | worker 完成、失败或阻塞任务 |
| `tool_call` / `tool_result` | 工具调用及结果索引 |
| `fact_added` | 有真实输出支撑的事实 |
| `hypothesis_added` | 尚未证实的猜测 |
| `dead_end_added` | 已确认不可行的方向 |
| `submission_result` / `flag_verified` | 提交结果及正确 flag 确认 |

事件统一字段：`event_id`、`schema_version`、`ts`、`challenge_name`、`run_id`、`actor_id`、`actor_type`、`kind`、`payload`、`provenance`、`dedupe_key`。

### 4.2 `verified` 的简单规则

MVP 只有二值标记：

- `verified=true`：命令真实输出、文件内容、服务响应或 CTFd 返回值直接证明；
- `verified=false`：solver 的推测、未复现实验、自然语言判断。

未经证明的内容只能写入 `hypothesis_added`，不能被 board summary 当作事实提供给后续规划。无需引入 Muteki 之外的多级信任系统。

### 4.3 Intent

Intent 是一条可执行的小任务，而不是“解决整道题”。最小字段：

`intent_id`、`challenge_name`、`goal`、`acceptance`、`status`、`worker_id`、`lease_until`、`attempt`、`created_event_id`、`result_event_id`。

状态只保留：

```text
open -> claimed -> completed
                 -> failed
                 -> blocked
claimed -> open   (lease 过期回收)
```

同一时刻只能有一个有效 worker。完成、失败、回收都必须幂等。

## 5. 最小实现架构

### 5.1 `backend/evidence/`

只需要以下模块：

- `models.py`：事件、provenance、intent、board snapshot 类型；
- `store.py`：SQLite schema、事务、幂等、原子 claim；
- `board.py`：面向 coordinator/worker 的读写 API；
- `state.py`：从事件折叠出 facts、hypotheses、dead ends、intents、flag；
- `query.py`：按 challenge 查询和导出；
- `replay.py`：按顺序重放事件并重建 snapshot。

不单独实现复杂的 routes/branches/pocs/reviews/locks 投影。

### 5.2 SQLite

MVP 使用一个全局 SQLite 文件，按 `challenge_name` 和 `run_id` 隔离数据：

- `events`：唯一事实来源；
- `intents`：当前可快速 claim 的投影；
- `event_links`：事件之间的 `supports`、`derived_from`、`for_intent` 关系。

启用 WAL、外键、busy timeout 和 schema migration。所有写入都在事务中完成；事件和 intent 投影必须同事务提交。原始工具大输出保存在 trace/artifact 路径，事件只保留 excerpt、路径和 hash。

### 5.3 Codex worker

在 `CodexSolver` 上增加 board context 和以下最小操作：

1. `read_board_summary()`；
2. `list_open_intents()`；
3. `claim_intent(intent_id)`；
4. 使用现有 sandbox/tools 执行；
5. `add_fact` / `add_hypothesis` / `add_dead_end`；
6. `complete_intent(result)`；
7. 通过现有 submit 逻辑提交 flag，确认后写 `flag_verified`。

worker 不能执行未领取的 intent。tool wrapper 自动记录 `tool_call/tool_result` 并关联现有 trace index；结论由 worker 显式提交，不能靠字符串 findings 猜测生成。

### 5.4 Coordinator / reason

不新增一套复杂 agent。直接把现有 Codex coordinator 的“读消息、看 trace、决定下一步”改成：

1. 读取 board summary；
2. 生成一个或多个 `intent_proposed`；
3. 根据 `intent_completed`、新事实和死路继续规划；
4. 看到 `flag_verified` 后结束 challenge。

这里的 reason 只是 coordinator 的规划职责，不是另一个必须单独部署的组件。

### 5.5 Swarm 与兼容层

`ChallengeSwarm` 仍负责 sandbox、solver 生命周期、取消、提交锁和成本汇总，但调度改为 worker pool：每个 Codex 实例循环领取 intent，而不是启动后直接独立解完整题。

`message_bus` 暂时保留类型和兼容调用，内部改为读取 board summary；切换完成后删除 `findings` 字典的主状态职责。`do_read_solver_trace` 保留为调试和 provenance 查询。

## 6. 默认参数（实现侧直接决定）

| 参数 | 默认值 |
| --- | --- |
| `evidence_db_path` | `logs/evidence.sqlite3` |
| worker lease | 300 秒 |
| lease heartbeat | 60 秒 |
| intent 最大尝试 | 3 次 |
| 单次 board summary | 只返回当前 facts、hypotheses、dead ends、active intents，限制长度 |
| 事件幂等 | 调用方 key；缺省使用稳定 payload 指纹 |
| SQLite | WAL + foreign keys + busy timeout 5 秒 |
| Codex solver replicas | 默认 3，硬上限 3（可用配置降到 1 或 2） |

这些参数不需要业务侧逐项确认；实现后可通过 `Settings` 覆盖。

## 7. 实施顺序

1. 定义 models 和事件 JSON schema；
2. 完成 SQLite store、migration、幂等写入和原子 claim；
3. 完成 state fold、board summary、query/replay；
4. 在 Codex tool wrapper、trace、submission 处接 recorder；
5. 改造 `CodexSolver` 为 intent worker；
6. 改造 `ChallengeSwarm` 和现有 Codex coordinator 调度；
7. 将 message bus 降级为兼容适配层；
8. 开发阶段跑少量旧 findings 对比，验收后只保留黑板主链路；
9. 补齐重启恢复、stale lease 回收和 benchmark 回归。

## 8. 验收标准

最小成功案例必须能产生并回放：

```text
challenge_started
intent_proposed
intent_claimed
tool_call / tool_result
fact_added 或 hypothesis_added 或 dead_end_added
intent_completed
submission_result
flag_verified
challenge_finished
```

同时满足：

- 两个 Codex worker 并发 claim 同一 intent 时只有一个成功；
- worker 崩溃后 lease 到期，任务可被重新领取；
- 重启后 board snapshot 与重放结果一致；
- verified fact、hypothesis、dead end 能分别查询；
- 任一 board 事件能定位到 trace/tool artifact；
- flag 确认后其他 worker 能被取消且状态不产生半写入；
- benchmark 仍能得到原有 `SolverResult` 字段；
- 不依赖 `ChallengeSwarm.findings` 才能继续求解。

## 9. 仍需对齐的内容（仅保留真正必要项）

目前没有阻塞实现的参数问题。只需在开始编码前确认两件事：

1. Muteki 参考代码的实际仓库/目录是否可以提供；若没有，直接按本文语义实现，不等待源码。
2. 是否临时将 replicas 降到 1 或 2；默认按 3 个 Codex worker 实现，硬上限为 3。

除此之外，事件字段、lease、重试、SQLite schema、兼容窗口和测试门槛由实现侧按本文确定，不再增加业务对接负担。

## 10. 本版与旧版的主要变化

- 把“state 1”纠正为 Stage 1；
- 将三类 solver 缩减为 Codex；
- 将 Muteki 高级对象从 MVP 移除；
- 用一个简单二值 `verified` 替代复杂信任等级；
- 明确 coordinator/reason 是同一规划职责；
- 明确必须改造 swarm/solver 调度，不能只增加日志；
- 将双写限定为开发测试手段，不作为生产架构；
- 将验收重点收敛到“能分工、能回写、能恢复、能确认 flag”。

## 11. 实现状态

截至当前版本，本文约定的 Stage 1 非端到端部分已经落地：

- SQLite 事件黑板、事务、幂等、schema migration、Intent 原子认领和 lease heartbeat；
- Codex worker 的黑板读取、Intent 列表/认领/完成、事实/假设/死路回写和未认领工具拦截；
- coordinator 的黑板读取、Intent 列表和动态 Intent 提出工具；
- 基于事实、假设、死路和完成结果的动态 follow-up 规划；
- message bus 兼容适配、事件 provenance、verified gate、最大尝试次数和自动 blocked；
- state fold、query、replay 模块及回归测试。

当前未执行的只有真实 Codex 进程、Docker sandbox 和 CTFd 的端到端联调；这不影响本地单元测试和静态校验结果。
