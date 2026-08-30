# RAG 计划

## 目标

在不改变主链路的前提下，把 RAG 作为一个可插拔模块接入当前 CTF Agent，并先完成一个低成本、可复现、可评估的最小版本。

默认 solver 模型：`codex/gpt-5.5`

## RAG 架构分层

当前项目采用“先 lexical、再 Agent 闭环、最后 hybrid”的渐进路线。你提供的 Vector Search + BM25 + Merge + Reranker 是完整 Advanced RAG 形态，其中向量库、融合和 reranker 不属于当前 Stage 2/Stage 3 的范围。

```text
Stage 1
Evidence/blackboard/solver 主链路

Stage 2 MVP
文档 -> 清洗/切分 -> metadata -> SQLite FTS5(BM25) -> KnowledgeService -> Codex search_knowledge

Stage 3
按需检索策略 -> 查询预算/去重 -> trace/evidence/blackboard provenance -> off/on 评估与语料运营

Stage 4 Advanced RAG（Stage 3 数据门槛之后）
Query -> BM25 + Vector Search -> Merge/RRF -> Reranker -> Top-K Context -> Agent
```

当前知识库语料目录为 `knowledge/`，按 `official`、`reference`、`internal_notes` 三类来源分开管理。将审核后的 Markdown 文件放入对应目录后，使用 `scripts/bootstrap_knowledge.py` 统一完成扫描、索引、过期文档清理和建库报告生成；目录中的 `README.md`、以下划线开头的文件和目录外文件不会被索引。

知识库的统一概念不是只存 CWE，而是 `CTF Domain Knowledge Base`，至少包含三类受控来源：

- `official`：CWE、ELF/PE、协议、文件格式和官方工具文档；
- `reference`：经过审核的 pwn、reverse、crypto、web、forensics、misc 通用技术资料；
- `internal_notes`：sandbox、黑板和 solver 协作规则。

每个 chunk 都需要保留 `source_type`、`category`、`topic`、`tool_name`、`cwe_id`、`version`、`document_id`、`section`、`trust_level` 和来源路径/URL。当前实现中部分字段由通用 metadata 字典承载，`document_id`、`section`、行号和来源由索引流程补齐。

网络资料整理为 Markdown 时，使用 YAML front matter 保存 `source_url`、`source_title`、`source_version`、`publisher`、`license` 和 `retrieved_at`；bootstrap 会把这些字段写入 document/chunk metadata 和搜索 provenance，并保留正文原始行号。

benchmark 题目、flag、原始附件和未审核的 challenge-specific writeup 只属于评测或临时资料，不能进入通用 RAG corpus。

## 总体原则

- 不重写主 solver 调度
- 先做结构化证据，再做检索
- 先做 lexical MVP，再考虑向量检索
- RAG 按需调用，不默认塞进系统提示词
- 每一步都要能独立评估和回滚

## 阶段 0：建立基线和契约

### 目标

先把“不加 RAG 时”的表现记录清楚，作为后续对比基线。

### 要做的事

- 记录现有 Solver 的 solve rate
- 记录平均步数、成本、耗时、失败类型
- 明确 `KnowledgeDocument`、`KnowledgeChunk`、`SearchRequest`、`SearchResult` 四个核心模型
- 定义 Benchmark corpus 与 RAG corpus 的隔离规则

### SearchResult 最少字段

- `text`
- `source_type`
- `metadata`
- `score`
- `provenance`

### 验收标准

- 有 baseline 指标
- 数据模型可落地
- benchmark corpus 和 RAG corpus 不混用

## 阶段 1：补 Evidence Graph

### 目标

把现有 MessageBus 里的字符串 findings，逐步升级成结构化证据事件。

### 建议事件类型

- `fact_added`
- `hypothesis_added`
- `dead_end_added`
- `poc_added`
- `intent_proposed`
- `intent_claimed`
- `intent_completed`
- `review_submitted`
- `flag_verified`

### 实现思路

- 新增独立的 `backend/evidence/` 模块
- 现有 `ChallengeSwarm` 竞争模式先保留
- 结构化事件先作为旁路记录，不强制改调度逻辑
- 事件需要能关联原始 trace 和 tool result

### 验收标准

- 能按 challenge 查询全部证据
- 能区分验证事实和模型猜测
- 能关联原始 trace/tool result
- 重启后事件不丢失

## 阶段 2：实现 RAG Lexical MVP 与最小 Codex 接入

### 目标

先做一个不依赖外部向量服务的知识库和受限检索工具，作为 Stage 3 Agent 应用和效果评估的底座。

### 范围

- CWE 和基础漏洞知识
- 协议、文件格式、二进制基础
- GDB、radare2、pwntools、z3、Volatility 等工具文档

### 推荐实现

- 新增 `backend/knowledge/`
- 离线流程：
  - 文档采集
  - 清洗
  - 按标题/代码块切分
  - 生成 metadata
  - 去重
  - 建索引
- 先用本地 SQLite FTS5 做 BM25/关键词检索

目录初始化命令：

```bash
.venv/bin/python scripts/bootstrap_knowledge.py --root knowledge --db logs/knowledge.sqlite3
```

本阶段已完成 lexical 知识库、provenance、bootstrap、CLI 和 Codex `search_knowledge` 最小接入。完整的 solver 使用策略、协作闭环、效果验收和语料运营移至 Stage 3。Vector Search、Embedding、Merge/RRF 和 Reranker 只有在 Stage 3 的真实评测数据证明 lexical 召回不足后，才作为独立 Stage 4 增强接入，不能替换当前 lexical fallback。

### metadata 建议

- `source_type`
- `category`
- `topic`
- `tool_name`
- `cwe_id`
- `version`
- `document_id`
- `section`
- `trust_level`
- `split`

### 验收标准

- 能按 query 检索知识
- 能按 metadata 过滤
- 检索结果可追溯
- 不需要向量库也能跑通

## 阶段 3：RAG Agent 应用、协作闭环与效果验收

> 正式计划见 [`docs/rag_stage3_plan.md`](rag_stage3_plan.md)。本阶段不是重复接入 `search_knowledge` 工具，而是把 Stage 2 的最小工具接入变成可控、可审计、可评估的 Agent 应用。

### 目标

在不改变 Stage 1 主链路的前提下，定义 solver 何时检索、检索多少、如何复用和引用知识，并完成多 agent evidence/blackboard 闭环、solver contract 对齐、RAG off/on 效果评估和语料运营。

### Stage 2 前置验收

- 重新执行 pytest、Ruff 和 compileall；
- 验证 bootstrap、search、delete、缺失 DB、provenance 和 `knowledge_enabled` 开关；
- 明确固定语料、来源清单、版本和尚未完成的不阻塞项；
- 真实 off/on 联调前保存 corpus manifest、trace/evidence 和环境参数。

### Agent 与协作闭环

- Codex 是必选路径，按需调用 Stage 2 的 `search_knowledge`；
- 单 turn、单 solver、单题查询预算、top-k、字符上限、超时、无结果和失败语义必须由统一 service/adapter 强制；
- query/result 去重、冲突来源处理和禁止整库注入 system prompt；
- 检索结果通过 trace、`knowledge_searched` evidence、fact/hypothesis/PoC 和 intent 关联到共享黑板；
- Pydantic/Claude 仅在当前确实保留的运行路径中做薄适配，不重写 Stage 1 调度。

### 效果与运营

- 固定知识型/非知识型 smoke 子集，使用相同模型、题目、solver 数、token、timeout 和网络策略运行 RAG off/on；
- 统计 solve rate、timeout/error、tool calls、token/cost、elapsed、knowledge queries/hits/chars、检索耗时、provenance 数量、无效检索率、Recall@5 和 MRR；
- 正式评估前冻结 solver 发布矩阵、qrels/eval version、至少 3 个 replicate、off/on 随机化顺序和量化阈值；`knowledge_probe` 只做开发 smoke，正式集知识型/非知识型各不少于 10 道；
- CI 分为 PR 离线检查、定期 corpus/query smoke 和高成本模型评估，完整结果必须保存 trace/evidence、corpus manifest 和环境配置；
- 通过 manifest、来源审核、版本、许可证、抓取日期、重建、回滚和回归 query 管理语料；
- 不把题目 flag、附件、临时 PoC 或未审核 writeup 写入通用 corpus。

### 验收标准

- RAG 关闭时 Stage 1 行为不能回退；
- RAG 开启时所有引用均可追溯到 chunk、来源、版本和行号；
- 查询预算、失败隔离、去重和 provenance 在所有已启用 solver 路径一致；
- off/on 评估可重复、可配对、可解释，且不把单次随机成功视为收益；
- 语料更新和回滚至少完整演练一次。

## 阶段 4：Advanced RAG（向量、混合召回与重排）

### 进入条件

只有 Stage 3 产生真实且稳定的评测数据后才能立项：在不少于 20 道带 qrels 的固定样本、至少 3 个 replicate 中，lexical Recall@5/MRR 仍达到预先冻结的不足阈值，且已排除语料缺失、query 策略和 solver 使用问题；off/on、成本、延迟、provenance 和 citation correctness 基线完整；语料版本和回滚流程稳定。

### 组件

- Embedding Provider
- Vector Index
- RRF / Score Fusion
- Optional Reranker

### 建议

- 新增 embedding provider 和 vector index 时保持 `KnowledgeService` 统一入口；
- 以 BM25 fallback 为底座，经过独立实验后再采用 RRF/score fusion；
- reranker、query rewrite 和多轮语义检索必须独立 feature flag、独立评测和可回滚；
- 不得用一次向量实验替换 Stage 2 lexical 结果，也不得绕过 Stage 3 provenance。

### 评估指标

- Recall@K
- MRR 或 nDCG
- 检索延迟
- 额外 token 成本
- Solver solve rate 变化
- 错误知识引用率

## 当前评估集

### 主测试集

- `benchmarks/rag_eval/main_100.json`

### 快速 smoke 集

- `benchmarks/rag_eval/smoke_20.json`

### RAG-sensitive 集

- `benchmarks/rag_eval/rag_sensitive_100.json`

### Stage 3 最小对照集

- `benchmarks/rag_eval/knowledge_probe.json`

该子集从 `smoke_20.json` 固定抽取知识型与非知识型样本，用于先验证召回、无效调用和 off/on 对照；它不是完整效果结论。

### 临时调试子集

- `benchmarks/rag_eval/smoke_20_no_character.json`
- `benchmarks/rag_eval/smoke_20_after_delulu.json`

## 当前待完成项

### Stage 2 已知缺口

- 受控语料仍需持续扩充和审核，当前首批内容不能代表完整领域覆盖；
- 真实 Codex off/on 联调和多次重复评估尚未完成；
- 引用正确率、Recall@5、MRR 和无效检索率尚未形成稳定报告；
- Pydantic/Claude 适配只在实际保留运行路径需要时进行。

这些缺口由 Stage 3 处理；它们不授权提前实现 Stage 4 向量组件。

## 建议下一步

当前 Stage 1 evidence graph 和 Stage 2 knowledge base 是两条不同链路：前者记录本次解题产生的事实/假设/工具证据，后者提供可复用的外部技术资料。Stage 3 通过 trace/evidence provenance 将两者关联，但不能把题目运行结果反向当作通用知识直接入库。

当前不拆分成 `search_cwe`、`search_writeup`、`search_docs` 三套 solver 工具，而是统一为 `search_knowledge`，通过 `source_type` 和 metadata filter 区分语料。这样可以避免不同工具的参数、错误处理和审计格式分叉；未来有必要时再增加面向用户的语义别名。

先用受控语料完成 Stage 2 lexical MVP，再按 [`docs/rag_stage3_plan.md`](rag_stage3_plan.md) 完成 Agent 使用、协作闭环和 off/on 验收；只有真实召回、成本和延迟数据证明 lexical 不足时，才进入 Stage 4 向量/混合检索。

这样做的好处是：
- baseline 清楚
- 证据可追溯
- 后面检索效果能量化比较
- 不会一上来就把系统改得太散
