# RAG Stage 2 实施计划：Lexical MVP 收口与 Agent 接入

> 本文用于说明当前 Stage 2 的真实实现状态、缺口和后续落地路径。Stage 2 以本地、离线、可回滚的 lexical RAG 为目标，不在本阶段引入向量数据库、reranker 或复杂知识图谱。

> 架构对齐说明：你提供的 Vector Search + BM25 + Merge + Reranker 属于后续 Advanced RAG 目标形态；本文只落地其中的 BM25/metadata/Agent Tool 最小闭环，向量检索和 reranker 保留到独立后续阶段。

> 结构对齐说明：帖子中的 `CWE`、`Writeup`、`Tool Docs` 是知识来源分类，不要求当前实现拆成三个数据库或三个工具。当前统一使用 `source_type + metadata` 管理来源；challenge-specific writeup 默认不进入通用 corpus，避免 flag 泄露和评测污染。

> 阶段边界说明：本文中的 P3 仅覆盖 Stage 3 所需的评估字段、脚本和最小对照集前置准备；真实 Agent 检索策略、协作闭环、off/on 多次运行、引用正确率和 Stage 4 决策由 [`docs/rag_stage3_plan.md`](rag_stage3_plan.md) 负责。本文中的 P4 Advanced RAG 仅是后续阶段提示，不属于 Stage 2 或 Stage 3 的实现范围。

## 1. 结论先行

当前 Stage 2 已完成了“知识库底座”和受控语料目录框架，但尚未完成“真实语料驱动的 RAG 效果验收”闭环。

已经具备：

- `backend/knowledge/` 本地 SQLite FTS5 知识库；
- `knowledge/` 三类受控语料目录和 corpus policy manifest；
- 第一批 6 份带 front matter provenance 的官方/可信种子笔记；
- Markdown/文本按标题、代码块和长度切分；
- `KnowledgeDocument`、`KnowledgeChunk`、`SearchRequest`、`SearchResult` 数据模型；
- source type、metadata、trust level、document/chunk provenance；
- 文档幂等重建、同 URL 更新、删除和 benchmark corpus 隔离；
- `scripts/index_knowledge.py` 离线建库；
- `scripts/bootstrap_knowledge.py` 统一扫描三类目录、清理过期文档并生成建库报告；
- `scripts/search_knowledge.py` 命令行查询；
- `backend/knowledge/service.py` 统一查询边界、字符上限、诊断和失败隔离；
- Codex solver 的 `search_knowledge` 动态工具、知识查询 trace/evidence provenance 和 RAG 指标字段；
- `tests/test_knowledge.py` 基础回归测试。

尚未具备：

- Pydantic solver 的统一检索兼容工具（非 MVP 必选）；
- 完整固定 RAG corpus、来源清单和版本管理；
- 引用正确率和 Recall@K/MRR 等效果指标；

因此当前完成度可定义为：**Stage 2 lexical MVP、Codex 最小接入、知识库目录框架和第一批 provenance 种子语料已完成，完整语料治理和效果验收尚未完成。**

## 2. 范围与原则

### 2.1 本阶段目标

把知识检索接入 Stage 1 主链路，但不改变 solver 的任务领取、黑板、flag 提交和结束逻辑。当前已完成 Codex 最小接入，下面的数据流中 Pydantic 兼容和效果评估仍是后续项：

```text
challenge started
  -> Codex worker 按需调用 search_knowledge（Pydantic 仅保留兼容适配，不作为 MVP 门槛）
  -> SQLite FTS5 返回带 provenance 的知识片段
  -> worker 根据知识继续使用 sandbox/tools
  -> 检索调用和引用写入 trace/evidence
  -> 原有黑板、提交和 SolverResult 链路继续工作
```

### 2.1.1 与 Advanced RAG 的对应关系

| Advanced RAG 组件 | 当前 Stage 2 | 后续阶段 |
| --- | --- | --- |
| 结构化清洗/切分 | 已实现 | 持续优化 |
| Metadata Filter | 已实现扁平精确匹配 | 可扩展范围/列表过滤 |
| BM25 Search | SQLite FTS5 已实现 | 保留 lexical fallback |
| Vector Search | 暂不实现 | 独立 embedding/vector index |
| Merge/RRF | 暂不实现 | Vector + BM25 融合阶段 |
| Reranker | 暂不实现 | Hybrid 稳定后再加 |
| Agent Tool | Codex `search_knowledge` 已实现 | 统一其他 solver 适配 |

因此当前 knowledge 库不是“向量数据库缺失的半成品”，而是有明确边界的 lexical MVP；未来增加向量检索时，应复用同一个 `KnowledgeService`，由 service 内部完成候选合并，不能让 solver 各自实现检索逻辑。

### 2.2 明确不做

- 不引入向量数据库或外部 embedding 服务；
- 不引入 reranker、RRF、多路 query rewrite；
- 不把整库自动注入 system prompt；
- 不把 benchmark challenge 文件、flag、writeup 解答直接混入通用知识库；
- 不在 Stage 2 重写 `ChallengeSwarm` 或 Stage 1 evidence 状态机；
- 不要求 CTFd 在线服务参与 RAG 测试；
- 不同时维护多套不一致的 solver 检索接口；Codex 是 Stage 2 的必选接入方，Pydantic 仅在现有兼容场景需要时复用同一适配器。

## 3. 当前代码审查

### 3.1 已实现模块

| 模块 | 当前能力 | 判断 |
| --- | --- | --- |
| `backend/knowledge/models.py` | 四类核心数据模型 | 已具备 MVP 契约 |
| `backend/knowledge/indexer.py` | 标题/空行/代码块感知切分，保存行号 | 已可用 |
| `backend/knowledge/store.py` | SQLite WAL、FTS5、BM25、metadata 过滤、trust 加权、CRUD | 底座可用，需加固 |
| `scripts/index_knowledge.py` | 本地 glob 文档导入、白名单、manifest/report、过期文档清理 | P0 基础项已完成 |
| `scripts/bootstrap_knowledge.py` | 扫描 `knowledge/{official,reference,internal_notes}`、解析 front matter provenance、建库、删除过期文档、输出报告 | 目录框架与 provenance 已完成 |
| `knowledge/` | 受控语料目录、来源策略、provenance front matter 和首批笔记 | 框架与首批语料已完成，待持续审核扩充 |
| `scripts/search_knowledge.py` | JSON 查询输出、稳定参数错误码 | P1 基础项已完成 |
| `backend/knowledge/service.py` | 查询清洗、top-k/字符上限、诊断和存储失败隔离 | P1 基础项已完成 |
| `tests/test_knowledge.py` | 切分、检索、过滤、来源、更新、删除、隔离、trust 测试 | 基础覆盖已存在 |
| `backend/config.py` | `knowledge_db_path` 配置 | 已有配置入口 |
| `backend/agents/codex_solver.py` | sandbox、黑板和 `search_knowledge` 动态工具 | Codex 最小接入已完成 |
| `backend/agents/solver.py` | Pydantic FunctionToolset | 尚未注册知识检索工具 |
| `backend/benchmarks/runner.py` | benchmark 运行、RAG 开关和知识调用指标 | 基础字段已完成，效果统计待补 |

### 3.2 需要修正或补充的底层问题

1. knowledge DB 已有 schema version 和本地文件初始化锁；后续字段变更仍需增加显式 migration step。
2. 当前初始化锁覆盖本地文件场景，跨主机共享文件系统不属于支持范围。
3. FTS query 当前使用 token `OR` 拼接，召回宽但噪声可能较大；需要明确空 query、特殊字符、中文和超长 query 的测试口径。
4. `score` 是经过 trust weight 调整的相对分数，不应直接当作跨 query 的概率或质量百分比；评测必须使用排序指标和阈值前的原始结果。
5. metadata 过滤是扁平字典精确匹配，暂不支持范围、列表、嵌套字段；应在 Stage 2 文档中明确该限制。
6. 索引脚本没有记录输入文件清单、删除的过期文档、失败文件和最终 chunk 数，无法稳定复现一次建库结果。
7. 当前知识查询已有统一 `KnowledgeService` 基础层和 Codex 工具；Pydantic 仍是兼容项。
8. 检索调用已写入 trace/evidence，但引用正确率和 Recall@K/MRR 仍未统计。
9. 索引脚本已有 source type 白名单和 manifest；固定语料目录和审核流程仍需确定。
10. benchmark 已有 RAG 开关和调用计数，尚未完成 off/on 自动对照汇总。

## 4. Stage 2 目标架构

### 4.1 数据流

```text
官方文档/本地知识文件
        |
        v
  ingest + normalize + chunk + dedupe
        |
        v
  SQLiteKnowledgeBase (FTS5)
        |
        v
  KnowledgeService.search(SearchRequest)
        |
        +--> Codex dynamic tool: search_knowledge
        +--> Pydantic compatibility tool: search_knowledge (optional)
        |
        v
  SearchResult(text + metadata + provenance)
        |
        +--> solver context
        +--> trace
        +--> evidence tool_call/tool_result provenance
```

### 4.2 统一服务接口

新增一个很薄的 service/adapter 层，禁止 solver 直接拼 SQL。下面是当前已落地的 service 契约；Agent tool 接入仍在 P2：

```python
search_knowledge(
    query: str,
    source_type: str | None = None,
    metadata: dict[str, str] | None = None,
    top_k: int = 5,
) -> list[SearchResult]
```

统一约束：

- `query` 去空白后不能为空；
- `top_k` 默认 5，最大 10；
- 单次返回总字符数限制为 8,000；
- 每条结果必须带 document/chunk、section、行号、source URL/path、trust level；
- service 层返回空列表并记录结构化诊断；agent tool 层再把“没有命中”或“暂时不可用”转换成模型可读文本，不向模型暴露 SQLite 异常；
- 检索失败只影响本次知识调用，不得终止 Stage 1 解题主链路。

### 4.3 corpus 边界

Stage 2 的 corpus policy 默认只允许以下 source type。该白名单属于索引脚本/service policy 层；底层 `SQLiteKnowledgeBase` 仍可保留通用 CRUD 能力，以免破坏现有单元测试和离线维护工具：

- `official`：官方工具、协议、文件格式和 CWE 文档；
- `reference`：经过审核的基础知识；
- `internal_notes`：项目内部运行说明。

以下内容默认禁止进入通用 RAG corpus（测试用的 `writeup`/`notes` fixture 不代表批准的生产语料）：

- `benchmark`、`benchmark_corpus`；
- 题目原始附件和 flag；
- 未审核的 challenge-specific writeup；
- 带有外部秘密、凭据或个人数据的文件。

初始语料应优先覆盖：CWE、ELF/PE、常见协议和文件格式、gdb/radare2/pwntools/z3/Volatility 基础用法，并按 `category/topic/tool_name/cwe_id/version` 补齐 metadata。每份进入受控 corpus 的文档必须有 source URL 或明确本地来源路径；当前低层模型允许 `source_url=None`，这属于兼容能力，不等于 corpus policy 放宽。

## 5. 分阶段实施计划

### P0：冻结契约与建立语料基线

目标：让一次建库可以复现、检查和回滚。

任务：

1. [已完成] 固定 `KnowledgeDocument`、`KnowledgeChunk`、`SearchRequest`、`SearchResult` 字段及 JSON 输出格式。
2. [已完成] 增加 `knowledge_schema_version` 和本地初始化锁；后续字段变更仍需增加显式 migration step。
3. [已完成] 新增 corpus manifest：记录文件路径、source type、trust level、content hash、chunk 数和失败项。
4. [已完成] 增加 source type 白名单和路径/扩展名校验。
5. 明确 benchmark corpus 与 RAG corpus 的物理目录不能相互索引。
6. [已完成基础覆盖] 补充空 query、超长文档、重复导入和并发初始化保护测试；特殊 FTS query 仍需扩展。

验收：同一输入目录重复构建得到相同 document/chunk ID；非法 source 和 benchmark 文件被拒绝；构建报告可解释新增、更新、删除和失败文件。

### P1：收口 lexical 检索服务（基础项已完成）

目标：稳定提供受限、可观测的本地检索能力。

任务：

1. [已完成] 实现 `KnowledgeService`，封装 `SQLiteKnowledgeBase`。
2. [已完成] 统一 `top_k`、字符上限、query 清洗和异常处理。
3. [已完成] 保留 BM25 排序和 trust level 加权，并输出原始 lexical score 与最终 score，避免误解。
4. [已完成] metadata 只支持扁平精确匹配；增加 source type、topic、tool_name、cwe_id 测试。
5. [已完成] 增加检索耗时、命中数和 query hash 统计；不记录完整敏感 query 到公开日志。
6. [已完成] 为删除、重建和 DB 不存在场景定义稳定 CLI 返回码。

验收：本地离线环境可完成 ingest/search/delete；在预先声明的目标库规模、硬件和冷/热缓存条件下，单次检索 P95 不超过 200 ms；该数值是性能目标，不是脱离语料规模的绝对保证；所有结果可追溯到源文件和行号；异常不会让 solver 崩溃。

### P2：接入 Codex solver（Pydantic 兼容适配可选）

目标：在不改变 Stage 1 调度的前提下，让 solver 能按需查知识。

任务：

1. [已完成] Codex dynamic tool 增加 `search_knowledge` schema，这是 Stage 2 MVP 必须完成的 solver 接入。
2. 如需维持现有 Pydantic 兼容运行，再在其 `FunctionToolset` 增加同名薄适配；它不是 Stage 2 MVP 的阻塞项。
3. 所有已接入的路径都调用同一个 service，使用相同参数和返回格式。
4. [已完成基础项] 每次调用写入现有 trace/tool_call/tool_result 和 `knowledge_searched`；结果 provenance 包含 query hash、document_id、chunk_id、source_type、trust_level。
5. 将检索结果作为当前 turn 的上下文返回，不默认追加到全局 system prompt。
6. [已完成] 检索工具失败时返回可读错误并允许 solver 继续使用 sandbox。
7. [已完成] 增加 settings 开关：`knowledge_enabled`、`knowledge_db_path`、`knowledge_top_k`、`knowledge_max_chars`。
8. [已完成] 默认启用工具但不主动调用；可通过配置关闭以进行 A/B 对照。

验收：Codex solver 能在离线 DB 上调用统一接口；若启用 Pydantic 兼容适配，则其参数和结果与 Codex 一致；关闭 RAG 时原有 Stage 1 smoke 行为不变；开启 RAG 时可以在 trace/evidence 中定位检索和引用来源。

### P3：RAG 评估前置与 Stage 3 交接

目标：补齐 Stage 3 评估所需的指标字段、固定子集和比较脚本；本阶段不使用模型额度下最终收益结论。

任务：

1. [已完成基础准备] 固定 `smoke_20.json` 中的最小对照子集 `knowledge_probe.json`，附知识型/非知识型标注。
2. [已完成基础字段] 结果增加 `knowledge_queries`、`knowledge_hits`、`knowledge_chars`、检索耗时和估算额外 token。
3. [已完成基础脚本] `scripts/run_rag_eval.py --compare-rag` 输出 off/on 聚合、delta 和按 challenge 配对明细。
4. 将真实相同 challenge/model/timeout/max_tokens/solver 数量的 off/on 运行、Recall@K/MRR、引用正确率和无效检索率移交 Stage 3。
5. smoke 只作为回归门槛，不把一次模型随机成功当成 RAG 效果结论。

建议通过门槛：

- RAG 开关关闭时，Stage 1 既有测试和 smoke 结果不回退；
- 检索调用不会产生 CTFd 或公共网络请求；
- 所有命中结果有 provenance；
- RAG-enabled 运行的额外成本和耗时可量化；脚本至少输出 solve 数、知识查询数和命中数差异。
- 在预先标注的知识型子集上 Recall@5 有可解释结果；
- 若 solve rate 没有提升，也必须能明确判断是语料、召回还是 solver 使用问题。

### P4：Advanced RAG 预留（移交 Stage 4）

只有 Stage 3 评估稳定且满足数据门槛后，才由独立 Stage 4 计划考虑：

- 向量 embedding 和本地向量索引；
- BM25 + vector 的 RRF 融合；
- reranker；
- query rewrite 和多轮检索；
- 自动知识摘要、知识审核和 UI。

这些能力必须以独立 feature flag 接入，不能替换 lexical fallback，也不应在 Stage 3 提前实现。

## 6. 默认配置建议

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `knowledge_enabled` | `true` | 只控制工具是否可用，不代表自动检索 |
| `knowledge_db_path` | `logs/knowledge.sqlite3` | 与 evidence DB 分离 |
| `knowledge_top_k` | `5` | 单次最多返回 5 条 |
| `knowledge_max_chars` | `8000` | 限制返回上下文大小 |
| `knowledge_query_timeout_ms` | `200` | SQLite 查询内超时并记录诊断；验收按 P95 目标执行 |
| `knowledge_allowed_sources` | `official,reference,internal_notes`（目标值） | 由索引/service policy 层防止任意文件入库 |
| `knowledge_trust_default` | `medium`（目标值） | 未显式标记时使用 |
| `knowledge_vector_enabled` | `false` | Stage 2 不启用向量检索 |

参数由实现侧直接确定，优先保证本地可运行和可关闭，不增加不必要的业务对接。

## 7. 文件级实施清单

第一批建议修改：

- `backend/knowledge/service.py`：统一检索服务和结果限制；
- `backend/knowledge/store.py`：schema version、初始化保护、原始 rank 和查询边界；
- `backend/knowledge/models.py`：补充请求/结果限制字段（如确有必要）；
- `scripts/index_knowledge.py`：manifest、白名单、构建报告；
- `scripts/search_knowledge.py`：统一 service、返回码和 JSON 格式；
- `backend/config.py`：知识检索 feature flags 和上限配置；
- `backend/agents/codex_solver.py`：动态 `search_knowledge` 工具；
- `backend/agents/solver.py`：Pydantic 同名兼容工具（如保留该运行路径）；
- `backend/benchmarks/models.py`、`backend/benchmarks/runner.py`：RAG 指标字段和 A/B 配置；
- `tests/test_knowledge.py`、新增 `tests/test_knowledge_tool.py`：单测、工具契约和失败隔离测试；
- `docs/rag_plan.md`：把阶段 2 状态更新为本文定义，避免旧计划继续把 Stage 2 写成未开始。

## 8. 下一步执行顺序

1. 从官方/可信来源整理带 `source_url`、版本、许可证和抓取日期的 Markdown 种子语料，放入 `knowledge/official`、`knowledge/reference`、`knowledge/internal_notes`，再运行 `scripts/bootstrap_knowledge.py`；
2. 补齐 P0/P1 剩余的 migration step、特殊 query 测试和固定语料审核流程；
3. 增加 Codex 工具的离线协议级回归测试；
4. 仅在现有兼容运行需要时接入 Pydantic 薄适配，并确认其参数/结果与 Codex 一致；
5. 增加 trace/evidence provenance；
6. 将固定 smoke 子集、评估字段和比较脚本交接给 Stage 3，按其计划跑多次 RAG off/on；
7. 只有 Stage 3 评估报告满足数据门槛后，才另立 Stage 4 计划。

Stage 2 的最小完成定义不是“有一个 SQLite FTS5 文件”，而是：**solver 能按需调用统一 lexical 检索接口，结果可追溯、可关闭、可评估，并且不破坏 Stage 1 主链路。** 向量检索、Merge/RRF 和 Reranker 不属于本阶段完成条件。
