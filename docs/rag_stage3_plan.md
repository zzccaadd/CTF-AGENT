# RAG Stage 3 计划：RAG Agent 应用、协作闭环与效果验收

> 本阶段把 Stage 2 的本地 lexical 检索能力变成可控、可审计、可评估的 Agent 应用闭环。Stage 3 不改变 Stage 1 的任务领取、黑板、evidence、flag 提交和结束状态机，也不在本阶段引入向量检索。

## 1. 阶段定位

### 1.1 已完成的 Stage 2 能力

当前工作区的 Stage 2 已具备以下底座：

- `backend/knowledge/` 提供 SQLite FTS5/BM25 和 metadata 过滤；
- `KnowledgeService` 统一 query 清洗、`top_k`、字符上限、超时诊断、来源白名单和存储失败隔离；
- `scripts/bootstrap_knowledge.py` 扫描 `knowledge/official`、`reference`、`internal_notes`，执行幂等建库、过期文档清理并写建库报告；
- Markdown front matter 的 `source_url`、标题、版本、发布者、许可证、抓取日期等 provenance 会进入文档、chunk 和搜索结果；
- Codex solver 已注册动态 `search_knowledge` 工具；工具结果会进入当前 turn、trace、`knowledge_searched` evidence 事件和 benchmark 知识指标；
- `knowledge_enabled`、数据库路径、`top_k`、字符上限和查询超时可配置；关闭开关时不暴露知识工具；
- `scripts/search_knowledge.py` 有稳定的搜索、删除、非法参数和数据库不存在返回码；
- `scripts/run_rag_eval.py` 和 `knowledge_probe.json` 已具备基础的 off/on 对照输入、知识查询计数、命中数、字符数和检索耗时字段。

这些能力定义的是 Stage 2 的底座和最小 Codex 接入，不等于 RAG 已经证明能提升解题效果。

### 1.2 Stage 3 目标

Stage 3 的完成定义是：

1. solver 只在有理由时调用受限的 `search_knowledge`，并遵守可观测的查询预算；
2. 知识结果、引用、事实/假设、PoC 和 intent 之间存在可回放的 provenance 链；
3. 多 solver 可以复用已有检索结果，不把同一片段重复写入黑板或反复检索；
4. Codex 是必选运行路径；其他当前保留的 solver 路径只做统一 service/result contract 的薄适配；
5. RAG off/on 在固定题目、模型和资源约束下可重复运行，并能区分 solve rate、成本、延迟、召回和无效调用；
6. 语料有来源审核、版本、许可证、更新、删除、回滚和回归查询流程；
7. RAG 可以通过 feature flag 关闭并回到 Stage 1 行为，进入 Stage 4 需要满足明确的数据门槛。

### 1.3 本阶段明确不做

以下内容不属于 Stage 3，不得以“接入 RAG”为由提前实现：

- Embedding Provider；
- Vector Index 或向量数据库；
- BM25 + Vector 混合召回；
- RRF、score fusion 或 reranker；
- query rewrite、自动多轮语义检索；
- 将整库、整篇文档或未筛选的语料注入 system prompt；
- 为了形式一致而重写 Stage 1 solver 调度、ChallengeSwarm 或 evidence 状态机。

## 2. Stage 2 验收前置条件

Stage 3 的任何效果结论都必须建立在一次可记录的 Stage 2 gate 之上。进入 gate 前保存工作区状态、Python 版本、依赖锁定信息、知识库路径、corpus manifest 和 commit/diff 标识。

### 2.1 必跑命令

```bash
.venv/bin/pytest -q
.venv/bin/ruff check backend tests scripts
.venv/bin/python -m compileall -q backend scripts
```

验收记录至少包含：测试通过数、Ruff/compileall 结果、Python/依赖版本、测试数据库是否为临时库，以及是否存在未提交改动。当前工作区基线为 `65 passed`，Ruff 和 compileall 已通过；后续改动后必须重新执行，不能沿用历史数字。

### 2.2 Stage 2 功能 smoke

在独立临时数据库中执行：

```bash
.venv/bin/python scripts/bootstrap_knowledge.py \
  --root knowledge \
  --db logs/knowledge.sqlite3
.venv/bin/python scripts/search_knowledge.py "buffer overflow" --top-k 5
.venv/bin/python scripts/search_knowledge.py "缓冲区越界" --source-type official
```

检查以下事实：

- bootstrap 报告能解释文件、chunk、失败和删除项；
- 搜索结果包含 `document_id`、`chunk_id`、section、行号、source URL/path、trust level；
- front matter provenance 在索引和搜索输出中保持一致；
- 空 query、非法 `top_k`、缺失 DB、删除文档有稳定语义；
- 关闭 `knowledge_enabled` 后动态工具不可用，但 solver 仍能继续 sandbox、黑板和提交流程；
- 知识查询故障只生成可读的空结果/失败状态，不终止主链路。

### 2.3 当前 Stage 2 状态表

| 项目 | 状态 | 是否阻塞 Stage 3 |
| --- | --- | --- |
| SQLite FTS5/BM25、metadata filter、来源白名单 | 已完成 | 否 |
| bootstrap、幂等重建、过期清理、front matter provenance | 已完成基础闭环 | 否 |
| Codex `search_knowledge`、trace/evidence provenance | 已完成基础闭环 | 否 |
| RAG 开关、数据库路径、top-k/字符/超时配置 | 已完成 | 否 |
| 固定语料的持续审核、扩充和版本清单 | 待完成 | 是，阻塞正式效果结论 |
| 真实 Codex off/on 联调和重复运行 | 待完成 | 是，阻塞收益结论 |
| Recall@5、MRR、引用正确率、无效检索率 | 待完成 | 是，阻塞 Stage 4 决策 |
| Pydantic/Claude 适配 | 待 S3.0 按发布矩阵决定 | 若路径纳入发布或 fallback，则阻塞该路径验收 |

“不阻塞”只表示可以先开发和测试 Stage 3 代码，不表示可以跳过对应验收项。

### 2.4 Stage 3 gate 产物和发布矩阵

每次进入 Stage 3 gate 都要生成一个不可变的 gate 记录，至少包含：

- Git commit/diff 标识、Python/依赖版本和运行主机信息；
- `knowledge/manifest.json`、bootstrap 报告、数据库文件 hash 和 corpus version；
- 启用的 solver/provider 列表、模型规格、sandbox image、网络策略和全部 benchmark limits；
- pytest/Ruff/compileall 输出、离线搜索 smoke 输出和未提交改动说明；
- 当前 gate 是开发、评估还是发布 gate，以及失败项和豁免理由。

Stage 3 默认发布矩阵必须在 gate 中明确冻结：

| 路径 | 当前仓库状态 | Stage 3 策略 |
| --- | --- | --- |
| Codex | 已有 `search_knowledge`，必选 | 必须完成全部策略、provenance 和评估验收 |
| Pydantic AI | 现有 solver 和 quota fallback 路径仍存在 | 只要该路径可被 benchmark 或 fallback 触发，就必须完成 parity；否则需显式关闭并记录不纳入发布 |
| Claude SDK | swarm 支持独立运行路径 | 若进入默认配置、CI 或发布 benchmark，必须完成 parity；否则不作为 Stage 3 发布能力 |

不能用“后续可能适配”作为验收状态。未纳入矩阵的 solver 必须在配置和报告中显示为 disabled，而不是静默缺少知识工具。

## 3. Agent 检索策略

### 3.1 何时调用

solver 可以在以下场景按需调用知识工具：

- 题目涉及 solver 当前无法确认的通用概念、ABI、文件格式、协议或漏洞类别；
- 需要查工具的稳定语法、参数语义或安全使用方式，例如 gdb、pwntools、z3、Volatility；
- 已有 sandbox 观测提示某个通用机制，但需要参考资料形成可检验的下一步假设；
- 协作者明确提出可由受控语料回答的问题。

以下场景不应调用：

- 查询本题 flag、附件内容、challenge-specific writeup 或模型刚刚可以直接观察到的命令输出；
- 只是为了增加上下文而搜索宽泛词；
- 已有同一 query、过滤条件和 corpus 版本的结果，且黑板/本地 turn context 已可用；
- 需要实时外部信息。知识工具只读本地审核语料，不替代 sandbox 或网络工具。

检索结果是参考资料，不是自动事实。solver 必须用真实工具输出验证关键结论；未验证的引用只能支持 hypothesis，不能直接标成 verified fact。

### 3.2 查询预算和返回边界

Stage 3 采用以下初始策略，所有路径由统一 service/adapter 执行并记录拒绝原因：

| 预算/边界 | 初始值 | 说明 |
| --- | ---: | --- |
| 单个 turn 最大查询数 | 1 | 一次模型响应最多发起一次知识查询；需要继续时进入下一 turn |
| 单个 solver/单题最大查询数 | 8 | 超过后返回预算耗尽的可读状态，不中断解题 |
| 一个 challenge 的 swarm 建议上限 | 24 | 作为聚合成本保护；按 solver 计数并记录超限 |
| 单个 solver/单题累计知识上下文 | 32,000 字符 | 防止 8 次查询各返回 8,000 字符造成隐性上下文膨胀 |
| 默认 `top_k` | 5 | 请求最大 10；调用方不能绕过 service 上限 |
| 单次返回字符上限 | 8,000 | 按结果顺序截断，保留 `truncated` provenance |
| query 最大长度 | 512 字符 | 超长 query 记 invalid，不执行搜索 |
| metadata | 最多 8 个扁平键 | 键和值各最多 256 字符；不支持嵌套、范围或列表过滤 |
| 查询硬超时 | 200 ms 默认 | SQLite 查询内硬中断；完成但超时的结果可以返回并记录 overshoot |

查询预算需要在 solver/turn 边界强制，而不能只在提示词中声明。预算字段应进入 trace、benchmark result 和比较报告。Stage 3 可以将上限做成 settings，但默认值和语义必须稳定。每次工具调用必须先经过预算检查，再决定 cache hit、实际查询或拒绝。

预算计数采用以下统一字段：

- `knowledge_tool_calls`：模型发起的工具调用总数，包含非法、无命中、cache hit 和预算拒绝；
- `knowledge_queries`：真正访问 `KnowledgeService`/SQLite 的次数；
- `knowledge_cache_hits`：命中本地或共享缓存的次数，不计入实际查询次数；
- `knowledge_budget_rejections`：因 turn/solver/challenge/上下文预算拒绝的次数；
- `knowledge_chars`：实际注入当前 turn 的字符数；
- `knowledge_context_chars`：单 solver/单题累计字符数，不能只依赖 `knowledge_chars` 聚合推算。

单个 turn 的边界必须与 trace 中的 model response/request ID 对齐；并发工具调用按调用数计入同一 turn。缓存键固定为 `corpus_version + normalized_query + metadata_filter + source_policy`，缓存只在同一 challenge run 或明确允许的受控范围内共享，并记录命中来源和失效原因。

### 3.3 无结果、失败和重复

- 空 query、超长 query、非法参数：返回结构化 invalid 诊断；工具向模型给出简短可读信息；不把异常栈暴露给 solver；
- 无命中：返回 `no usable results`，solver 继续 sandbox 分析；无命中不是失败，也不能计为知识 hit；
- 数据库不可用或查询硬超时：返回 isolated error/timeout 状态，记录诊断，主链路继续；
- 完成但超过软 deadline：保留结果并记录 `elapsed_ms` 与 overshoot，不能静默丢弃冷缓存结果；
- 同一 solver 在相同 corpus 版本、query 规范化结果和 metadata filter 下重复查询：命中本地 turn cache 或共享检索缓存，计为一次实际 query；
- query、filter 或 corpus 版本变化：允许重新检索，并在 trace 中说明 cache miss 原因；
- 结果按 `chunk_id` 去重；同一文档相邻 chunk 只在确有不同 section/provenance 时保留。

查询终态统一使用 `query_outcome` 字段区分：`ok`、`no_hit`、`invalid_query`、`invalid_params`、`timeout`、`store_error`、`budget_exhausted`、`cache_hit`。其中 `no_hit` 不是 error，`cache_hit` 不是一次新的 backend query；同一调用只能有一个终态。

### 3.4 来源冲突

不同来源对同一事实不一致时：

1. 不在检索层静默合并或选择一个“看起来正确”的文本；
2. 保留每个候选的 source、版本、trust level、section 和行号；
3. solver 在 evidence 中记录冲突，先作为 hypothesis；
4. 以题目 sandbox 的可重复观测、较新且可核验的官方资料或人工 review 解决冲突；
5. 任何最终 fact/PoC 都引用实际支持它的片段，不能只引用一次搜索的 query。

## 4. 多 agent 协作闭环

### 4.1 统一事件流

```text
solver intent
  -> search_knowledge(query, filters)
  -> SearchResult(text + provenance)
  -> current turn context
  -> trace knowledge_searched
  -> evidence knowledge/tool_result provenance
  -> verified observation or hypothesis
  -> blackboard fact/dead_end/PoC/intent link
```

`knowledge_searched` 是“查到了资料”的事件，不是事实确认事件。只有真实工具输出或人工确认才能把结论升级为 verified fact。

### 4.2 provenance 链要求

每次检索至少保存：

- `run_id`、challenge、solver/actor、turn/step、intent_id（如有）；
- query hash、规范化 query、source_type 和 metadata filter；
- query 状态、命中数、返回字符、耗时、预算消耗；
- 每个结果的 `document_id`、`chunk_id`、source URL/path、title、section、line_start/line_end、版本、许可证和 trust level；
- 当前 corpus manifest/version 标识。

隐私规则：默认只持久化规范化 query 的 hash、长度和必要的脱敏摘要；不得把可能包含 flag、凭据、附件内容或秘密的完整 query 写入公开 trace/evidence。完整 query 只有在受控 debug 开关、短 retention 和访问审计同时开启时才允许保存。source version/license 可以存于 result metadata，但 evidence 必须至少能通过 `document_id/chunk_id + corpus_version` 解析到它们。

事实、假设、PoC 和 intent 的 provenance 应通过 evidence event/link 关联上述结果，而不是复制一份没有出处的文本。`knowledge_searched` 永远不是 verified fact；引用摘录只保留满足审计所需的短片段，避免把整篇资料写入黑板。所有终态（包括 timeout/store_error）都必须有可计算的 elapsed 或明确的未测量原因。

### 4.3 黑板复用与去重

- agent 发布知识辅助的 finding 时，写入引用的 chunk/document ID、query hash 和对应 intent；
- 后续 agent 先读取 blackboard summary/evidence，再决定是否需要检索；
- 同一 chunk 已被当前 challenge 的一个 solver 使用时，其他 solver 可以复用 provenance，但仍需记录自己的引用关系和验证结果；
- 共享缓存只按 corpus version、规范化 query、filter 和 source policy 隔离，不能跨题共享 challenge-specific 内容；
- 去重不能抹掉不同 solver 的验证结果、冲突或 dead end。

### 4.4 严格隔离题目运行产物

下列内容只能留在本题 run 的 trace/evidence/benchmark 结果中，禁止反向写入通用 RAG corpus：

- flag、题目附件、容器路径、临时凭据和环境秘密；
- challenge-specific 解法、未审核 writeup、模型猜测和一次性 PoC；
- 只对本题成立的 endpoint、地址、栈布局、payload 或运行日志。

通用语料只能通过人工审核的新增/更新流程进入 `knowledge/`，并必须补齐来源和许可证信息。

## 5. Solver 一致性

### 5.1 发布门槛

- Codex 是 Stage 3 必选路径，必须复用 `KnowledgeService` 和统一的 `SearchResult`/诊断格式；
- Pydantic 或 Claude 只有在仓库当前实际保留并计划发布的运行路径中才做薄适配；未启用的路径不构成阻塞项；
- 适配器只负责参数映射、工具注册和错误转译，不在 solver 内拼 SQL、重复实现排序、预算或 provenance；
- 不为满足“所有 solver 一样”而重写 Stage 1 主链路；
- 各路径的查询预算、来源白名单、无结果/失败语义和 trace 字段必须一致。

### 5.2 一致性测试

使用同一个临时 DB 和固定 query fixture，验证所有已启用路径：

- 工具 schema 的参数名、默认值和上限一致；
- 成功、无命中、非法参数、数据库失败的结果格式一致；
- provenance 字段集合和 query hash 规则一致；
- RAG off 时工具不可用且 Stage 1 smoke 不回退；
- RAG on 时调用计数、字符、耗时和引用均进入统一 benchmark result。

### 5.3 明确的发布判定

S3.0 必须在第一次正式评估前冻结下列判定，不允许看到结果后再改阈值：

- Codex 路径为必过；任何纳入发布矩阵的 Pydantic/Claude/fallback 路径也为必过；
- RAG off 的 Stage 1 smoke 不允许新增失败、预算违规或主链路状态变化；
- RAG on 的非空结果 provenance 完整率为 100%，`knowledge_searched` 事件完整率为 100%；
- 查询预算违规数为 0，检索 P95 目标沿用 Stage 2 的 200 ms，并单独报告 timeout/overshoot；
- 评估报告、原始 trace/evidence、corpus manifest 和 run 配置缺一项即为不完整，不得发布。

上述是发布完整性门槛，不等价于必须提升 solve rate；收益结论仍由第 6 节的统计规则决定。

## 6. 效果评估方案

### 6.1 固定评估集

评估集分层使用，不混淆用途：

- `benchmarks/rag_eval/knowledge_probe.json`：当前 6 题最小对照集，3 道标注知识型、3 道标注非知识型；用于首先验证策略、召回和无效调用；
- `benchmarks/rag_eval/smoke_20.json`：Stage 1/RAG 回归 smoke，不把单次成功当作收益证明；
- `main_100.json`、`rag_sensitive_100.json`：Stage 3 稳定后作为扩大样本和 holdout，不能因为调参反复污染；
- 每道知识型样本必须人工标注 `knowledge_needed`、`expected_knowledge`、支持该结论的语料主题和相关 chunk；非知识型样本的预期知识集合为空或明确说明原因。标注应落在独立的 qrels 文件中，例如 `benchmarks/rag_eval/knowledge_probe_qrels.json`，并记录 `qrels_version`、annotator、判定理由、相关 document/chunk ID 和语料版本。

`knowledge_probe.json` 只作为开发 smoke。Stage 3 发布评估至少需要 20 道固定标注题目，其中知识型和非知识型各不少于 10 道；`main_100` 或 `rag_sensitive_100` 作为冻结 holdout，不得用于调参后再回填标注。样本不足时只能报告“链路验证完成”，不能报告 RAG 收益。

### 6.2 对照运行

RAG off/on 必须使用完全相同的：

- challenge manifest 和题目版本；
- model/provider/model 参数；
- solver 数、并发、attempts、timeout、max tokens、sandbox image 和网络策略；
- 结果目录格式和失败重试策略。

每个 replicate 随机化 off/on 的执行顺序，避免固定先 off 后 on 的时间、缓存和服务状态偏差；同一 replicate 仍使用完全相同的题目、模型和资源。每组至少 3 个独立 seed/run（资源允许时增加到 5），按 `(provider, challenge_id, eval_version, run_seed, rag_enabled)` 配对，缺任一侧都标记为 incomplete 而不是当作 unsolved。`scripts/run_rag_eval.py` 需要补充 repeat/seed 编排和跨 run 聚合，不能只依赖手工重复命令。保存原始结果、trace、evidence、corpus manifest 和比较 JSON。改变模型、题目、solver 数或 token 预算后，必须视为新实验，不能与旧结果直接比较。

### 6.3 必须输出的指标

至少输出以下聚合和每题明细：

| 指标 | 定义 |
| --- | --- |
| solve rate | `solved / total`，同时报告每次 run 和跨 run 均值/区间 |
| timeout/error | 按结果 status 统计，不能把 timeout 当普通 unsolved 混合解释 |
| tool calls | 平均、P50/P95 和每题明细 |
| token/cost | input/output/total tokens、USD 成本及 off/on delta |
| elapsed | challenge 总耗时和检索耗时，至少报告均值与 P95 |
| knowledge queries | 采用 `knowledge_tool_calls`、`knowledge_queries`、`knowledge_cache_hits` 分开统计 |
| knowledge hits | 采用 `knowledge_hit_queries`（至少一个结果的查询数）和 `knowledge_result_count`（结果条数）分开统计 |
| knowledge_chars | 返回到 solver context 的字符数 |
| retrieval latency | 每次终态的 `elapsed_ms`，含 timeout、overshoot、未测量原因和 P50/P95 |
| provenance count | search result、knowledge evidence、被引用 fact/PoC 的数量，不能只统计 query 次数 |
| invalid retrieval rate | 只统计 `invalid_query + invalid_params + budget_exhausted`；`no_hit`、timeout、store_error 另列比例 |
| Recall@5 | 对人工标注知识型样本，top 5 是否包含期望主题/人工标注相关 chunk |
| MRR | 第一个相关 chunk 的倒数排名；无相关结果记 0 |
| citation correctness | 引用是否真实支持对应 fact/PoC，抽样或全量人工审核并报告样本数 |

`knowledge_est_extra_tokens = knowledge_chars / 4` 只能作为粗略估算字段，不能替代 provider 的精确 token 结算。评估执行器必须保留每次调用的原始事件或等价样本，才能计算检索 P50/P95 和各终态比例；仅保存总耗时无法回溯分布。Recall/MRR 和 solve rate 必须按题目与 run 展开，避免聚合平均掩盖某一类题目的回退。

Recall/MRR 使用 qrels 中的相关 chunk/document，而不是模糊的“主题看起来相关”：top-k 中命中任一 relevant item 记 Recall 命中，第一个 relevant item 的排名用于 MRR。标注至少由一名主审和一名复核完成；冲突记录 adjudication，不得静默覆盖。正式报告至少给出知识型样本数、qrels 版本和未标注/不可判定数量。

### 6.4 解释规则

- 单次模型随机成功、单次 timeout 消失或单个 query 命中都不能视为 RAG 收益；
- solve rate 提升但引用错误率、成本或延迟显著上升时，不得直接发布为成功；
- 知识型样本无召回：优先区分语料缺失、词法召回失败和 solver 未使用结果；
- 非知识型样本频繁调用：记录为无效检索或策略问题，而不是“更多上下文”；
- off/on 结果不完整、题目未配对、corpus 版本不同或资源约束变化时，实验结论标记为不可比较。

### 6.5 CI、smoke 和高成本评估分层

| 层级 | 触发 | 内容 | 是否消耗模型额度 |
| --- | --- | --- | --- |
| PR 必跑 | 每次代码/计划相关实现变更 | pytest、Ruff、compileall、知识工具 contract、临时 DB bootstrap/search/delete、RAG off 主链路 smoke | 否 |
| 定期离线 | corpus 或索引变更、每日/每周 | bootstrap 报告、固定 query 回归、provenance 完整性、语料隔离和删除/回滚演练 | 否 |
| 评估任务 | Stage 3 gate/release candidate | 至少 3 组 off/on replicate、qrels、完整指标和人工引用审核 | 是 |

PR 和定期离线层失败时不得启动高成本评估；高成本评估失败要保留 artifact，并区分代码、语料、模型和环境原因。

## 7. 语料运营

### 7.1 manifest 和审核字段

每份受控语料必须有：

- 稳定文件路径和 `document_id`；
- `source_type`、category/topic/tool/CWE 等适用 metadata；
- source URL 或明确本地来源；
- source title、source version、publisher、license、retrieved_at；
- 内容 hash、chunk 数、索引时间和审核人/审核状态；
- 不含 flag、附件、凭据、个人数据和未审核 challenge-specific 解法的声明。

`knowledge/manifest.json` 是 corpus policy/来源清单；bootstrap 生成的建库报告是一次构建产物。两者都要随评估产物保存，不能用临时 DB 状态替代来源清单。

### 7.2 新增和更新流程

1. 在 `official`、`reference` 或 `internal_notes` 放入聚焦主题的 Markdown 摘要；
2. 补齐 front matter 和 metadata，做人工来源/许可证/敏感信息审核；
3. 运行 bootstrap 到临时 DB，检查新增、更新、删除、chunk 数和失败项；
4. 执行固定回归 query，确认新旧结果、来源和行号合理；
5. 更新 manifest/version，保留 diff 和构建报告；
6. 通过测试、Ruff、compileall 和最小搜索 smoke 后，才替换发布 DB。

### 7.3 删除、回滚和回归

- 删除文件后重新 bootstrap，确认对应 source URL 的旧文档被清理；
- 任何失败的 ingest 保留上一份可用索引，直到新版本通过验证；
- 发布前保留上一版 DB、manifest、报告和 corpus hash；
- 出现错误来源、召回回退、敏感内容或性能异常时，将 feature flag 关闭并恢复上一版 DB；
- 回滚后重新跑 Stage 2 gate 和固定 query，确认结果可追溯且 Stage 1 不受影响。

## 8. 分阶段执行清单

### 8.0 责任角色与交付物

| 责任角色 | 主要交付物 | 交接条件 |
| --- | --- | --- |
| Knowledge maintainer | corpus manifest、qrels 关联的 document/chunk、bootstrap 报告、回归 query | 来源、版本、许可证和敏感信息审核通过 |
| Solver maintainer | 预算/cache/query outcome、Codex 及纳入矩阵的 adapter、contract tests | 离线工具 contract 和 Stage 1 off smoke 通过 |
| Evaluation maintainer | repeat/seed runner、配对比较、聚合指标、原始 artifact 清单 | off/on replicate 完整且配置可复现 |
| Evidence reviewer | provenance 链、冲突处理、citation correctness 抽样和 adjudication | 引用可回放，事实/假设边界清楚 |

同一人可以承担多个角色，但每个 gate artifact 必须记录实际负责人和审阅人。模型额度实验不能替代代码、语料和 evidence 审核。

### S3.0：Stage 2 gate

- [ ] 重新执行 pytest、Ruff、compileall；
- [ ] 在临时 DB 完成 bootstrap/search/delete/缺失 DB smoke；
- [ ] 记录当前实现、CLI、RAG 开关、provenance 和 corpus manifest；
- [ ] 冻结 solver/provider 发布矩阵、qrels/eval version、重复 run 数和所有量化阈值；
- [ ] 生成不可变 gate artifact，记录环境、配置、commit/diff、失败项和豁免理由；
- [ ] 标记语料缺口和不阻塞项，不把缺语料误判成代码失败。

### S3.1：检索策略和预算

- [ ] 在 solver/turn 边界实现单 turn、单 solver、单题预算；
- [ ] 明确并测试 `knowledge_tool_calls`、实际 queries、cache hits、budget rejections 和累计 context chars；
- [ ] 实现规范化 query/filter/corpus-version 的重复查询去重或缓存；
- [ ] 统一无结果、失败、硬超时和完成但慢的返回语义；
- [ ] 补齐 `query_outcome` 终态和 invalid/no-hit/timeout/store_error 统计，所有终态可计算耗时。

### S3.2：协作和 provenance

- [ ] 把 query、结果 provenance、intent、fact/hypothesis/PoC 链接写入 trace/evidence；
- [ ] 支持其他 solver 复用已有 chunk 而不重复检索；
- [ ] 增加冲突来源和引用正确性的审计样例；
- [ ] 加入题目运行产物不得进入通用 corpus 的检查。

### S3.3：solver contract

- [ ] Codex 离线协议级回归保持必过；
- [ ] 在 S3.0 冻结 Codex/Pydantic/Claude/fallback 发布矩阵；纳入矩阵的路径补统一薄适配；
- [ ] 用同一个 service、参数边界、结果格式和错误语义完成 parity test；
- [ ] 不改 Stage 1 调度和 evidence 状态机。

### S3.4：评估和验收

- [ ] 固化 `knowledge_probe_6` 标注和相关 chunk；
- [ ] 建立 qrels 文件、标注复核和 holdout 冻结规则；
- [ ] 为 `scripts/run_rag_eval.py` 增加 repeat/seed、随机化 off/on 顺序、缺失配对和跨 run 聚合；
- [ ] 在相同资源约束下运行至少 3 个 replicate 的 RAG off/on；
- [ ] 输出全部指标、per-challenge 配对、trace/evidence/provenance 和 corpus 版本；
- [ ] 人工审核知识型样本的 Recall@5、MRR 和 citation correctness；
- [ ] 对非知识型样本报告 invalid retrieval rate，并分析无效调用原因。

### S3.5：语料运营和发布

- [ ] 建立来源审核、版本、许可证、更新和删除流程；
- [ ] 发布前执行 bootstrap、回归 query、完整测试和 smoke；
- [ ] 保留上一版 DB/manifest/report，验证 feature flag 和回滚；
- [ ] 按 PR/定期离线/高成本评估三层执行 CI 和 smoke；
- [ ] 形成 Stage 3 评估报告，明确是否满足 Stage 4 数据门槛。

## 9. 验收标准、风险与回滚

### 9.1 Stage 3 验收标准

Stage 3 只有同时满足以下条件才可标记完成：

- `knowledge_enabled=false` 时 Stage 1 测试、smoke 和主链路行为无回退；
- `knowledge_enabled=true` 时所有知识引用可从 fact/PoC 回溯到 evidence、trace、chunk、来源 URL/path、版本和行号；
- 查询预算、去重、失败隔离、字符/超时边界在 Codex 及所有纳入发布矩阵的适配路径一致；
- 固定评估集可重复执行，off/on 变量一致，原始 artifact 和比较报告齐全；
- 报告包含 solve rate、timeout/error、tool calls、token/cost、elapsed、knowledge 指标、检索耗时、provenance、invalid retrieval rate、Recall@5、MRR 和 citation correctness；
- 语料新增/更新/删除/回滚流程至少完整演练一次；
- 没有把 benchmark、flag、附件或未审核题解写入通用 corpus。

额外的最低发布门槛为：查询预算违规为 0；非空检索结果 provenance 完整率 100%；评估题目配对完整率 100%；知识型正式评估集不少于 10 道、非知识型不少于 10 道；至少 3 个完整 replicate。solve rate 没有提升时可以结束 Stage 3，但必须能区分语料缺失、召回失败、solver 未使用和随机波动。

### 9.2 风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| lexical 召回噪声或语料覆盖不足 | solver 被误导或知识型题目无命中 | 固定 query/标注、来源 trust、冲突审计、Recall/MRR 分析 |
| solver 反复查询造成成本/延迟上升 | 解题预算被知识调用消耗 | turn/solver/challenge 预算、去重、P95 监控 |
| 引用被当成事实 | 错误 PoC 或错误协作方向 | provenance gate，未经工具验证只能是 hypothesis |
| 多 agent 重复检索/重复写黑板 | 噪声和成本增加 | corpus-version cache、chunk 去重、intent 链接 |
| 语料污染或许可证不明 | flag 泄露、合规和评测污染 | 物理目录隔离、manifest 审核、发布前检查 |
| RAG 失败影响主链路 | Stage 1 回退 | service 隔离、工具可关闭、离线 fallback |

### 9.3 回滚路径

1. 将 `knowledge_enabled`/RAG benchmark flag 设为 `false`；
2. 停止使用当前知识 DB，恢复上一个已审核 DB、manifest 和报告；
3. 保留失败 run 的 trace/evidence 供审计，不把其内容写回 corpus；
4. 重新执行 Stage 2 gate、Stage 1 smoke 和固定 query；
5. 只有定位并修复语料、策略或适配问题后，才重新开启 RAG。

### 9.4 进入 Stage 4 的数据门槛

Stage 4 只能在 Stage 3 产生真实、稳定、可解释的评测数据后立项。以下是首次正式评估前冻结的初始建议门槛，项目负责人可以在运行前调整，但运行后不得追改：

- lexical 召回在不少于 20 道带 qrels 的固定样本上，经过语料/query/solver 排查后仍出现 Recall@5 < 0.80 或 MRR < 0.50，且该结果在至少 3 个 replicate 中方向一致；
- off/on 评测至少完成 3 个可配对 replicate，模型、题目、solver 数、token、timeout 和网络策略一致；
- solve rate、成本、延迟、provenance 和 citation correctness 基线完整；
- 语料版本、人工标注、回归 query 和回滚流程稳定；
- 已明确向量/混合检索将如何保持 lexical fallback、feature flag 和数据隔离。

在这些条件不满足前，继续扩充审核语料和改进 lexical Agent 使用策略，不启动 embedding、vector index、RRF 或 reranker。
