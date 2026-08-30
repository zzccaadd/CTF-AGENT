# RAG 计划

## 目标

在不改变主链路的前提下，把 RAG 作为一个可插拔模块接入当前 CTF Agent，并先完成一个低成本、可复现、可评估的最小版本。

默认 solver 模型：`codex/gpt-5.5`

## RAG 架构分层

当前项目采用“先 lexical、后 hybrid”的渐进路线。你提供的 Vector Search + BM25 + Merge + Reranker 是完整 Advanced RAG 形态，其中向量库、融合和 reranker 不属于当前 Stage 2 的已实现范围。

```text
当前 Stage 2 MVP
文档 -> 清洗/切分 -> metadata -> SQLite FTS5(BM25) -> KnowledgeService -> Codex search_knowledge

后续 Stage 4
Query -> BM25 + Vector Search -> Merge/RRF -> Reranker -> Top-K Context -> Agent
```

知识库的统一概念不是只存 CWE，而是 `CTF Domain Knowledge Base`，至少包含三类受控来源：

- `official`：CWE、ELF/PE、协议、文件格式和官方工具文档；
- `reference`：经过审核的 pwn、reverse、crypto、web、forensics、misc 通用技术资料；
- `internal_notes`：sandbox、黑板和 solver 协作规则。

每个 chunk 都需要保留 `source_type`、`category`、`topic`、`tool_name`、`cwe_id`、`version`、`document_id`、`section`、`trust_level` 和来源路径/URL。当前实现中部分字段由通用 metadata 字典承载，`document_id`、`section`、行号和来源由索引流程补齐。

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

## 阶段 2：实现 RAG Lexical MVP

### 目标

先做一个不依赖外部向量服务的检索版本，验证 RAG 是否能带来收益。

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

本阶段明确不做 Vector Search、Embedding、Merge/RRF 和 Reranker；这些能力只有在 lexical 召回数据证明不足后，作为独立 Stage 4 增强接入，不能替换当前 lexical fallback。

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

## 阶段 3：接入 Agent 工具层

### 目标

把知识检索变成一个可由各个 solver 调用的标准工具。

### 核心接口

```python
search_knowledge(query, source_type, metadata, top_k)
```

### 接入位置

- Pydantic Solver：`backend/agents/solver.py`
- Codex Solver：`backend/agents/codex_solver.py`
- Claude Coordinator/Solver：暂不作为当前 MVP 门槛，后续按统一 service 适配

### 原则

- 按需调用
- 不自动灌进 system prompt
- 各 solver 的 RAG 能力尽量一致

### 验收标准

- 各 solver 都能调用同一套检索入口
- 检索不破坏原有主链路
- 调用日志可观察

## 阶段 4：加入向量检索和 Reranker

### 目标

在 lexical recall 不够时，再增加向量检索和结果融合。

### 组件

- Embedding Provider
- Vector Index
- RRF / Score Fusion
- Optional Reranker

### 建议

- 用 RRF 合并 BM25 和向量结果
- 设置多轮检索上限，避免 token 循环
- 默认最多重写 1 到 2 次

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

### 临时调试子集

- `benchmarks/rag_eval/smoke_20_no_character.json`
- `benchmarks/rag_eval/smoke_20_after_delulu.json`

## 目前我认为还需要确认的点

### 1. 数据边界

要明确哪些内容属于 RAG corpus，哪些只是 benchmark corpus。

建议先定成：
- benchmark corpus：只用于评估，不参与检索索引
- RAG corpus：知识库内容，只在检索阶段使用

### 2. 证据图存储方式

还需要确定：
- 事件落地是 SQLite、Postgres，还是文件
- 是否要支持增量恢复
- 是否要支持按 challenge 回放

### 3. 检索接口的返回策略

还需要确定：
- `top_k` 默认是多少
- metadata 过滤是否必须
- provenance 要不要包括段落位置和来源 URL

### 4. 文档来源范围

还需要确定：
- 只收官方文档和基础知识，还是也纳入 writeup
- 是否允许把 challenge-specific 解法写入知识库
- 是否需要给每条知识打 trust level

### 5. 评估口径

还需要确定：
- RAG 是否只看 solve rate
- 还是要同时看 token、耗时、错误引用率
- smoke 集是否作为 CI 必跑

### 6. solver 侧一致性

还需要确认：
- Claude Solver 现在要不要先补 MCP
- 还是先做受控命令桥接
- 是否要求所有 solver 先达到同一套 RAG 能力

## 建议下一步

当前 Stage 1 evidence graph 和 Stage 2 knowledge base 是两条不同链路：前者记录本次解题产生的事实/假设/工具证据，后者提供可复用的外部技术资料。两者通过 trace/evidence provenance 关联，但不能把题目运行结果反向当作通用知识直接入库。

当前不拆分成 `search_cwe`、`search_writeup`、`search_docs` 三套 solver 工具，而是统一为 `search_knowledge`，通过 `source_type` 和 metadata filter 区分语料。这样可以避免不同工具的参数、错误处理和审计格式分叉；未来有必要时再增加面向用户的语义别名。

先用受控语料完成 Stage 2 lexical MVP 和 Codex 工具闭环，再根据真实召回和 solve rate 数据决定是否进入向量/混合检索阶段。

这样做的好处是：
- baseline 清楚
- 证据可追溯
- 后面检索效果能量化比较
- 不会一上来就把系统改得太散
