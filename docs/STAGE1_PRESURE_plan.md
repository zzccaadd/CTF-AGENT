# Stage 1 压力测试计划

> 文件名按当前任务约定保留为 `STAGE1_PRESURE_plan.md`。本文面向 Stage 1 本地 benchmark/smoke 主链路，不把 CTFd 在线服务作为默认压测依赖。

## 1. 目标与范围

### 1.1 目标

验证以下链路在负载增加、worker 竞争、租约过期、超时和进程清理场景下仍然正确、可恢复、可观测：

```text
benchmark runner -> ChallengeSwarm -> Codex worker pool
                  -> SQLite evidence board -> LocalFlagVerifier
                  -> SolverResult / trace / benchmark result
```

重点不是让模型在压测中解更多题，而是确认 Stage 1 的调度和状态契约不会因为并发而失效：

- 一个 intent 同时只被一个有效 worker 持有；
- lease 过期后任务可以安全重领，旧 worker 不能越权写入；
- append-only events、intents 投影和 replay 结果一致；
- flag 确认后其他 worker 能退出，不留下半写入状态或 Docker 容器；
- timeout/error 结果仍保留步数、成本、finding 和 trace 路径；
- benchmark 本地运行不访问 CTFd 或公共网络。

### 1.2 本阶段不测

- CTFd 服务端吞吐和在线 API 压测；
- Codex 模型质量排名或跨模型公平比较；
- 向量 RAG、reranker、routes/branches 等 Stage 2 以后功能；
- Stage 2 knowledge corpus/index/search 的吞吐和召回；这些内容单独在 Stage 2 评测，不计入本压测门槛；
- 生产环境多机 SQLite、分布式锁或跨主机容灾。

在线 coordinator/poller 保留兼容性检查，但不放入本地 Stage 1 压测的通过门槛。

## 2. 前置条件与安全边界

### 2.1 环境

- Python 3.14 virtualenv：`.venv/bin/python`、`.venv/bin/pytest`、`.venv/bin/ctf-bench`；
- Docker daemon 正常运行；
- `ctf-sandbox` 镜像已经构建；
- 真实 Codex 压测需要本机已登录 Codex，并明确本轮 token/cost 预算；
- 首轮使用 Cybench 中已经通过过的 Dynastic smoke 题，避免把题目准备失败误判为 Stage 1 调度失败。

### 2.2 隔离和限流

每次运行都使用独立临时目录，不要直接覆盖开发中的 `logs/evidence.sqlite3`：

```bash
RUN_ID="$(date +%Y%m%d-%H%M%S)"
PRESSURE_ROOT="/tmp/ctf-agent-stage1-pressure/${RUN_ID}"
mkdir -p "${PRESSURE_ROOT}"
export EVIDENCE_DB_PATH="${PRESSURE_ROOT}/evidence.sqlite3"
```

默认关闭互联网。机制说明：`--allow-internet` / `BenchmarkLimits.allow_internet` 只是 solver 工具层开关（是否下发 web 工具、`codex_solver` 是否拦截）；真正的出口隔离来自 provider 创建的 docker `--internal` 网络 `shared_net`（有 start_script/compose 的题）和 `network_mode=none`（无 start_script 的题）：

- benchmark CLI 不带 `--allow-internet`，`BenchmarkLimits.allow_internet=False`；
- 不使用在线 CTFd 提交，统一由 `LocalFlagVerifier` 校验；
- 每轮开始先校验隔离生效：有 start_script/compose 的题，`docker network inspect shared_net --format '{{.Internal}}'` 应为 `true`（该网络仅在跑 service 题时才创建）；无 start_script 的题验证 `network_mode=none`；
- 每轮开始校验 `EVIDENCE_DB_PATH` 确实生效（在项目根目录执行）：`Settings().evidence_db_path` 必须等于 `${PRESSURE_ROOT}/evidence.sqlite3`，避免静默写进开发库 `logs/evidence.sqlite3`；
- 若观测到 `http://localhost:8000` 以外的网络请求、宿主机文件访问或未预期容器，立即停止该轮。

操作约束：**同一时间只能运行一个 `ctf-bench` 进程**——`BenchmarkRunner.run()` 启动时会调用 `cleanup_orphan_containers()` 杀掉所有 `label=ctf-agent` 的容器，两个进程并发会互相清理对方的压测容器。

### 2.3 资源预算建议

第一轮不要超过以下上限：

| 资源 | 建议上限 |
| --- | ---: |
| 同时运行的 challenge | 4 |
| 每个 challenge 的 solver | 3 |
| 同时运行的 sandbox 容器 | 12 |
| 单个 sandbox 容器内存上限 | 2–4 GB |
| 单个 challenge timeout | 300 秒（P4 soak 例外，见 P4） |
| 单个 solver max tokens | 200,000 |
| 连续真实 Codex 压测时间 | 30 分钟 |
| 本轮模型费用 | 由操作者预先设置硬预算 |

`max_containers = concurrency * solvers_per_swarm`，超过宿主机内存或 Docker 配额时优先降低 `concurrency`，不要关闭黑板或租约保护。

每容器内存上限没有 CLI 旋钮，来自 `Settings.container_memory_limit`（默认 `16g`，环境变量 `CONTAINER_MEMORY_LIMIT` 可覆盖，pydantic-settings 大小写不敏感读取）。压测轮次务必先 `export CONTAINER_MEMORY_LIMIT=4g`（或 2g），否则 P2-D 12 个容器理论封顶 192 GB，极易触发宿主机 OOM；压测期间以 `docker stats` 实际内存为准判断是否降档。

`max_tokens` 是传给每个 solver 的预算，不是整个 challenge 的总预算。3 个 solver 同时运行时，单题最坏 token 消耗约为该值的 3 倍；若需要严格控制单题成本，应先降低每个 solver 的预算或减少 replicas。

## 3. 测试层级

### P0：回归基线

目的：确认压测前代码和环境没有基本回归。

参数：

- 1 个 Dynastic challenge；
- `concurrency=1`；
- `solvers_per_swarm=3`；
- `timeout=120`；
- `max_tokens=80_000`；
- `allow_internet=false`。

命令：

```bash
.venv/bin/pytest -q
.venv/bin/ruff check backend tests scripts

.venv/bin/ctf-bench \
  --provider cybench \
  --root benchmarks/cybench \
  --split benchmark \
  --challenge 'hackthebox/cyber-apocalypse-2024/crypto/[Very Easy] Dynastic' \
  --model codex/gpt-5.5 \
  --timeout 120 \
  --max-tokens 80000 \
  --concurrency 1 \
  --solvers-per-swarm 3 \
  --image ctf-sandbox \
  --results "${PRESSURE_ROOT}/p0-results.json"
```

通过条件：测试全通过；Dynastic 至少成功 1 次；结果包含非空 `trace_path`、`tool_calls` 和 `cost_usd`；黑板可以 replay（校验片段见 §4.2）。

基线参考：历史单 solver 运行 Dynastic 约 44–61 秒、~43k–56k tokens、~$0.10–0.17（`results/rag_eval/probe_gpt55_dynastic.json`、`results/rag_eval/smoke_20.cybench.json`）。80k×3 预算与 120s timeout 可行但偏紧；若未解出，先区分模型/题目准备与调度原因（见 §5.3），可先提 `--max-tokens 120000`、`--timeout 180` 复跑。

### P1：黑板存储与竞争压测

目的：不消耗模型额度，单独验证 SQLite 事件和 intent 并发语义。建议固化为可重复脚本 `scripts/pressure_board.py`（参数化 intent/worker/claim 数量与轮次）或独立测试文件；不要用一次性临时 harness，否则无法按 §7 用实际数据反推下一轮参数。为测到真实 SQLite 锁争用，每个 worker 用独立 `threading.Thread` + 独立 `SQLiteEvidenceStore` connection；所有 worker 共用一个 connection 只能验证 Python 层锁，不能代表多进程/多连接负载。

两点与真实拓扑的关系：

- 生产路径是"每 challenge 一个 connection（store 内 RLock 串行化），challenge 内 3 个 solver 共享"，多连接争用只发生在跨 challenge（P2-D 最多 4 连接）。P1 的"每 worker 一连接"是比生产更严苛的负载，结论应限定为"多连接/SQLite 锁争用"而非"worker 竞争"；如要贴近生产，另加"每 challenge 单连接 × 并发 challenge"的小轮对照。
- store 修复记录（2026-08-31）：`__init__` 的 schema 迁移已包在 `BEGIN IMMEDIATE` 事务内（多连接并发建库不再有 `ALTER TABLE` 竞态）；`intents` 投影表主键已从 `intent_id` 单列改为 `(challenge_name, run_id, intent_id)` 复合主键（含旧库自动重建迁移），跨 run 相同 intent_id 不再静默冲突；`store.heartbeat` 已增加 run 作用域与 `lease_until >= now` 守卫。P1 脚本仍保持先单连接初始化 schema 再起 worker 的做法。

推荐工作负载：

| 项目 | 轻量轮 | 目标轮 | 上限轮 |
| --- | ---: | ---: | ---: |
| intent 数量 | 100 | 1,000 | 10,000 |
| worker 数量 | 3 | 9 | 30 |
| 每个 intent 的 tool 事件 | 10 | 20 | 20 |
| 竞争 claim 次数 | 300 | 3,000 | 30,000 |
| 数据库 | 临时 SQLite WAL | 临时 SQLite WAL | 临时 SQLite WAL |

实测数据（`scripts/pressure_board.py`，2026-08-31）：轻量轮约 2 秒、目标轮约 5.9 秒（append/claim/complete p95 ≈ 2.7 / 11.1 / 4.5 ms）全部 PASS；**上限轮（30 个独立连接）暴露 WAL 自动 checkpoint 饿死**——WAL 增长超过 1 GB、写入吞吐崩塌（约 1 claim/s），26 分钟仅完成约 15% 负载。上限轮需预留 30 分钟以上时间与足够磁盘，或先评估 WAL checkpoint 策略（周期 `PRAGMA wal_checkpoint(TRUNCATE)`、调小 `wal_autocheckpoint`、降低连接数）再决定是否作为必须轮；生产路径最多 4 个连接，不触发该问题。

每轮需要检查：

1. 每个 intent 的有效 `intent_claimed` 不超过一个同时有效 worker；
2. 自定义 dedupe key 不跨 challenge/run 串数据；
3. 按 (challenge_name, run_id) 分组后 `seq` 严格递增；允许 `INSERT OR IGNORE` 去重造成的 seq 空洞（`seq` 是全库 AUTOINCREMENT，多 challenge 共享一个 DB 时本来就是全局交错、单 challenge 内不连续），"没有事件丢失"用事件计数 + `snapshot()==replay()` 校验，不用 seq 连续性；
4. `snapshot()` 与 `replay()` 完全相等；
5. 不出现 `database is locked`、未捕获异常或线程泄漏；
6. 达到 `max_attempts=3` 后 intent 进入 `blocked`，不会无限重试；
7. 并发写入相同 `dedupe_key` 只产生一个事件（幂等），不产生重复 `intent_claimed`/`intent_completed`。

建议观测指标：

- `append_event`、`claim_intent`、`complete_intent` 的成功/失败数；
- claim 成功率和 p50/p95 延迟；
- 事件总数、SQLite 文件大小、WAL 文件大小；
- blocked intent 数、重复 claim 数、replay mismatch 数。

首轮门槛：目标轮完成后 `replay mismatch=0`、重复有效 claim=0、未处理异常=0；本地单次 append/claim p95 不超过 500 ms（本地 SQLite WAL 预期 1–5 ms，500 ms 只是上限门槛）。建议同时记录 p50/max 与 claim 冲突数，用首轮实际值下探后续轮目标。

### P2：worker pool 并发阶梯

目的：确认 ChallengeSwarm 的 solver 生命周期、取消和提交锁在并发增加时稳定。

使用 2 到 4 个轻量、预先可运行的本地 challenge，优先选择非 service/compose 题（如 Dynastic、Makeshift 这类 crypto，`network_mode=none`、无镜像构建成本），避免并发 `docker compose up --build` 把题目准备时间混进压测变量；避免重复使用同一个 challenge/run 数据库状态。每个阶梯至少运行 2 次，两次结果都写入 summary.md：

| 阶梯 | challenge 并发 | solver/challenge | 容器上限 | timeout | max tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| A | 1 | 1 | 1 | 120 s | 80k |
| B | 1 | 3 | 3 | 120 s | 80k |
| C | 2 | 3 | 6 | 180 s | 120k |
| D | 4 | 3 | 12 | 300 s | 200k |

阶梯 D 最坏 token 消耗 ≈ `concurrency × solvers × max_tokens` = 4×3×200k = 2.4M tokens，启动前用实际单价估算本轮预算；若预算吃紧，先降 max_tokens 或降到阶梯 C。

运行示例：

```bash
# scripts/run_rag_eval.py 为了可复现性固定使用 1 个 solver；worker pool 压测使用 ctf-bench。
.venv/bin/ctf-bench \
  --provider cybench \
  --root benchmarks/cybench \
  --split benchmark \
  --challenge '<challenge-id-1>' \
  --challenge '<challenge-id-2>' \
  --model codex/gpt-5.5 \
  --timeout 180 \
  --max-tokens 120000 \
  --concurrency 2 \
  --solvers-per-swarm 3 \
  --image ctf-sandbox \
  --results "${PRESSURE_ROOT}/p2-results.json"
```

每轮结束后检查：

- 实际容器数不超过 `concurrency * solvers_per_swarm`（用 `docker ps --filter label=ctf-agent` 计数）；
- solved challenge 的其他 worker 被取消，且没有新的 flag 提交；
- 每个结果都有 `status`、`elapsed_seconds`、`tool_calls`、`trace_path`；
- timeout challenge 的诊断字段不为空；
- `docker ps --filter label=ctf-agent` 不留下孤儿容器（比 `ancestor=ctf-sandbox` 精确——compose 服务容器也可能基于该镜像）；
- evidence DB 中本轮各 run 的 `challenge_finished` 数量与输入 challenge 数量一致（按 run_id 分组核对，不是全表计数——多个阶梯共享一个 DB 时历史轮次会累计）；
- 本轮各 challenge 的 run_id 为新值（若上次运行被中断，`latest_run_id()` 会静默 resume 旧 run；校验片段见 §4.2）。

### P3：故障、租约和恢复压测

目的：验证 worker 崩溃、租约到期、超时取消和重启恢复不会破坏黑板。

#### 3.1 租约过期与旧 worker fencing

- 使用测试专用 lease `5` 秒、heartbeat 约 `1` 秒；
- worker A claim intent 后停止 heartbeat；
- 等待 lease 过期，由 worker B 重新 claim；
- worker A 尝试 `complete`，必须返回失败且不能产生 `intent_completed`；
- worker B 完成后 replay 状态必须为 `completed`；
- 已知边界（已修复，2026-08-31）：`store.heartbeat` 原无 `lease_until >= now` 守卫，租约过期后旧 worker 仍可续租；现已增加守卫与 run 作用域，过期后旧 worker 必须重新 claim 才能续租。本测试按"A 停止 heartbeat、B 抢回"验证 fencing。

#### 3.2 达到最大尝试次数

- 设置 `max_attempts=3`；
- 让三个 worker 依次 claim 后过期；
- 第四次 claim 必须返回不可用；
- intent 必须为 `blocked`，结果为 `maximum attempts reached`；
- 注意 `attempt` 按"claim 次数"计数（每次成功 claim 都 +1，同一 worker 重复 claim 也消耗），因此"三个 worker 依次 claim 后过期"= 3 次 claim 后 blocked。

#### 3.3 benchmark timeout

- 使用一个会运行超过 timeout 的 challenge 或 synthetic solver；
- 调用 `swarm.kill()` 并取消 benchmark task；
- 结果必须是 `status=timeout`，同时保留已有 `step_count`、`cost_usd`、`findings_summary` 和 `log_path`；
- provider cleanup 完成后不能有运行中的 sandbox；
- 预期行为：超时取消会写 `challenge_finished("cancelled")`（`backend/agents/swarm.py` CancelledError 分支），该 run 被视为已结束、后续运行不会 resume 它；`_timeout_result` 只保留第一个非空 solver 的 `log_path`，其余 solver 的 trace 仍在 `logs/` 下按文件名可查。

#### 3.4 进程重启恢复

- 第一次运行在 intent 处于 `open` 或过期 `claimed` 时**进程级硬杀（SIGKILL）**：`swarm.kill()` + task cancel 会写 `challenge_finished("cancelled")`，写完后 `latest_run_id()` 找不到未完成 run，就验证不到"恢复"；
- 使用专用 DB（如 `${PRESSURE_ROOT}/restart.sqlite3`）且只在本测试使用：被硬杀留下的未完成 run，后续若用同一 DB 跑同一 challenge 会静默 resume 旧 run_id；
- 重新打开同一个 DB 和 challenge；
- 未完成 intent 可以被新 worker 领取；
- 已完成 intent 不得重复执行；
- `snapshot == replay`，且 follow-up intent 编号不重复。

故障注入只允许使用临时 DB、临时 trace 和本地 challenge，不对 CTFd 或其他外部服务发送请求。

### P4：短时 soak（可选）

目的：发现长时间运行中的内存、SQLite WAL、trace 文件和取消任务泄漏。

时间账：benchmark runner 会等所有 challenge 结束才返回，单题 timeout=300 秒时整轮最多 ~5–6 分钟，达不到"连续 20–30 分钟"。要让 soak 真正持续 20–30 分钟，二选一：

- 方案 A（推荐）：单题 `--timeout 1500–1800`，2 个 challenge、`concurrency=2`、每题 3 个 solver，让 solver 持续工作到模型预算耗尽；成本按 6 个 solver 的 max_tokens 估算并计入本轮预算；
- 方案 B：小规模题目集循环多轮（每轮结束立即开始下一轮），把准备/清理成本计入总时长，按累计运行时长计 soak。

每 60 秒记录：

- Python 进程 RSS；
- Docker 容器数和总内存；
- evidence DB/WAL/trace 文件大小；
- active/open/claimed intent 数；
- cost、token、tool_call 累计值。

soak 不以模型最终 solve rate 作为唯一结论；即使题目未解出，也必须满足无崩溃、无任务泄漏、无孤儿容器和状态可 replay。

## 4. 指标与结果记录

每轮结果目录建议如下：

```text
${PRESSURE_ROOT}/
├── p0-results.json
├── p2-results.json
├── evidence.sqlite3
├── evidence.sqlite3-wal
├── traces/          # 需手动收集，见下方说明
├── docker-stats.log
└── summary.md
```

> 当前实现里 solver trace 硬编码写入项目 `logs/trace-*.jsonl`（`backend/tracing.py` 的 `SolverTracer(log_dir="logs")`，尚无 `trace_dir` 配置），不会自动进入 `${PRESSURE_ROOT}/traces/`。每轮结束后执行 `mkdir -p "${PRESSURE_ROOT}/traces" && cp logs/trace-*.jsonl "${PRESSURE_ROOT}/traces/"` 收集，并在 summary.md 记录来源目录；或后续给 `Settings` 增加 `trace_dir` 后由 runner 直写。

### 4.1 必记指标

| 类别 | 指标 |
| --- | --- |
| 正确性 | solved、status、flag_verified、错误提交数 |
| 调度 | intent proposed/claimed/completed、claim 冲突、lease lost、blocked |
| 一致性 | event 数、per-run seq 连续性（允许去重空洞）、snapshot/replay 是否相等、dedupe 重复数 |
| 性能 | challenge elapsed、claim/append/complete p50/p95、timeout 数 |
| 模型成本 | input/output/cached tokens、cost_usd、cost per solved |
| 资源 | Python RSS、CPU、Docker 容器数/内存、DB/WAL/trace 大小 |
| 关联性 | results.json 条目 ↔ evidence DB run_id 映射（challenge → run_id） |
| 清理 | 孤儿容器（`label=ctf-agent`）、残留 `shared_net` docker 网络、未结束 task、未关闭 DB、未关闭 trace |

### 4.2 建议采样命令

压测期间另开终端执行（`du`/`ps` 依赖项目根目录作为 cwd）：

```bash
while true; do
  date -Is
  free -m | head -2                                   # 宿主机内存，对照 §6 停止条件
  docker ps --filter label=ctf-agent --format '{{.ID}} {{.Image}} {{.Status}}'
  docker stats --no-stream --filter label=ctf-agent --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}'
  ps -eo pid,rss,comm --sort=-rss | head -5           # Python 进程 RSS（P4 关注）
  du -sh "${PRESSURE_ROOT}" logs 2>/dev/null   # logs/ 存放 solver trace
  sleep 10
done | tee "${PRESSURE_ROOT}/docker-stats.log"
```

SQLite 事件汇总可用项目虚拟环境中的 Python 查询，避免依赖系统是否安装 `sqlite3` CLI：

```bash
.venv/bin/python - "${PRESSURE_ROOT}/evidence.sqlite3" <<'PY'
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1])
print(conn.execute(
    "select kind, count(*) from events group by kind order by kind"
).fetchall())
print(conn.execute(
    "select count(*), max(seq) from events"
).fetchone())
PY
```

黑板可重放与 run_id 校验（每轮结束后执行，复用项目虚拟环境）：

```bash
.venv/bin/python - "${PRESSURE_ROOT}/evidence.sqlite3" <<'PY'
import sqlite3
import sys

from backend.evidence import EvidenceBoard

path = sys.argv[1]
conn = sqlite3.connect(path)
runs = conn.execute(
    "select challenge_name, run_id, "
    "sum(case when kind='challenge_started' then 1 else 0 end) started, "
    "sum(case when kind='challenge_finished' then 1 else 0 end) finished "
    "from events group by challenge_name, run_id order by 1, 2"
).fetchall()
for name, run_id, started, finished in runs:
    board = EvidenceBoard.open(path, name, run_id)
    snap = board.snapshot()
    print(name, run_id[:8], "started", started, "finished", finished,
          "replay_ok", snap == board.replay(), "last_seq", snap.last_seq)
    board.close()
print("runs:", len(runs))
PY
```

若某 challenge 最近一次 run 的 `finished=0`，说明存在未完成 run：后续同题运行会静默 resume 它（P2 各阶梯应避免，P3.4 重启测试则刻意利用它）。

## 5. 通过门槛

### 5.1 必须满足

- P0 全部通过，Dynastic smoke 至少成功 1 次（若未解出，须能归因于模型 quota/题目准备并保留完整 status/error 与调度契约证据，见 §5.3）；
- P1 目标轮完成，重复有效 claim=0，replay mismatch=0；
- P2 阶梯 C 至少完成 2 次，不能出现未捕获异常或孤儿容器；
- 所有 timeout/error 结果保留可诊断字段；
- flag 确认后其他 worker 被取消，黑板没有半写入 intent；
- 本地压测过程没有 CTFd 或公共网络依赖；
- 代码测试、ruff、脚本语法和 `git diff --check` 通过。

### 5.2 建议满足

- P2 阶梯 D 完成 2 次；
- P3 租约、最大尝试和重启恢复各完成 1 次；
- P4 soak 完成 20 分钟；
- append/claim/complete p95 小于 500 ms；
- 运行结束后 Python task、trace、DB connection 和 Docker 容器均清理干净。

### 5.3 暂不作为失败

- 真实 Codex 因模型服务临时 quota/rate limit 失败，但已正确记录 `quota_error` 并释放资源；
- 单道题在有限 token 下未解出，但调度、清理、事件一致性全部通过；
- 宿主机资源不足导致主动降档，只要记录实际参数并重新完成对应阶梯。

## 6. 停止条件与回滚

满足以下任一条件立即停止当前轮：

- Docker 内存连续 ≥3 个采样点（10s 间隔）超过宿主机可用内存的 80%，或出现 swap/OOM；
- 容器数超过计算上限，或发现孤儿容器快速增长；
- SQLite 出现持续 `database is locked`（非瞬时重试成功）、per-run seq 跳变或 replay mismatch；
- 未知网络访问、宿主机路径访问或 CTFd 请求出现；
- 单轮成本达到预设预算；
- 同一阶梯连续 2 次运行失败率 >5%，且不是已知模型 quota/rate limit。

停止后保留结果目录和日志，禁止用 `git reset`、`git checkout` 或删除工作区来清理。只清理明确属于本轮的临时容器和临时目录，并在 `summary.md` 记录原因。

## 7. 推荐执行顺序

1. P0 回归基线（先确认 `EVIDENCE_DB_PATH`、`CONTAINER_MEMORY_LIMIT` 生效）；
2. P1 黑板目标轮（`scripts/pressure_board.py`，先单连接初始化 schema 再起 worker）；
3. P3 租约、最大尝试和 timeout 故障注入（P3.4 用 SIGKILL + 专用 DB）；
4. P2 阶梯 A 到 C（每轮校验 run_id 为新值）；
5. 资源充足且预算允许时执行 P2 阶梯 D；
6. 最后执行 P4 soak（timeout 提到 1500–1800s，或循环题目集）。

首轮推荐配置是 P0 + P1 目标轮 + P2 阶梯 C，不建议一开始直接执行 P2 阶梯 D 或 P4。完成首轮后，使用实际的 p95、最大 RSS、容器峰值、token 和 cost 数据反推下一轮参数，而不是只按理论上限继续加压。

## 8. 结果摘要模板

每轮压测结束后在 `${PRESSURE_ROOT}/summary.md` 写入：

```markdown
# Stage 1 Pressure Run

- run_id:
- commit/worktree:
- model:
- challenge set:
- concurrency:
- solvers_per_swarm:
- timeout/max_tokens:
- evidence_db_path:
- challenge → run_id 映射:
- duration:
- solved/total:
- timeout/error/quota_error:
- total tool calls:
- total tokens/cost:
- peak containers/RSS/DB size:
- replay mismatch:
- orphan containers/tasks:
- leftover docker networks (shared_net):
- network access observed:
- verdict: pass / pass-with-limitations / fail
- notes:
```

采用 `pass-with-limitations` 时必须列出降档原因、未完成阶梯和下一轮建议参数。
