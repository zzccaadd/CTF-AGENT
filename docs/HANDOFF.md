# CTF-Agent RAG 项目交接文档（HANDOFF）

> 生成时间：2026-08-31 10:30（会话切换交接）
> 分支：`rag_branch`（与 origin/rag_branch 同步，工作树干净）
> 测试基线：`pytest 100 passed`、`ruff` 全绿
> 开发记录：log.md 1-72（本文件是浓缩版，细节以 log.md 与 git log 为准）

---

## 1. 快速开始

```bash
# 测试与静态检查（改代码后必跑）
.venv/bin/pytest -q
.venv/bin/ruff check backend tests scripts
.venv/bin/python -m compileall -q backend scripts

# 重建知识库（knowledge/ 73 篇 md → logs/knowledge.sqlite3）
.venv/bin/python scripts/bootstrap_knowledge.py --root knowledge --db logs/knowledge.sqlite3 --report logs/knowledge.manifest.json

# 搜索验证
.venv/bin/python scripts/search_knowledge.py "padding oracle" --top-k 3

# 跑评估（默认配置：timeout 300s / max_tokens 1M / solvers-per-swarm 3）
.venv/bin/python scripts/run_rag_eval.py --compare-rag \
  --manifest benchmarks/rag_eval/knowledge_probe_v4.json \
  --concurrency 4 --results-dir results/rag_eval_v5

# 分析结果
.venv/bin/python scripts/analyze_rag_compare.py \
  --results-dir results/rag_eval_v5 --manifest benchmarks/rag_eval/knowledge_probe_v4.json

# 离线检索质量评估（不花模型额度）
.venv/bin/python scripts/eval_knowledge_recall.py --db logs/knowledge.sqlite3

# S3.0 gate 档案
.venv/bin/python scripts/generate_stage3_gate.py
```

## 2. 总体架构（对齐 muteki-main 语义）

```
challenge started
  └─ ChallengeSwarm（协调层）
       ├─ 1 个 seed intent（recon）→ worker claim
       ├─ LLM Coordinator（gpt-5.5，muteki reason 语义）
       │    ├─ 触发：黑板 (facts, dead_ends, hypotheses) 计数变化 + 45s 冷却
       │    ├─ 证据审计：关键 intent 只基于 verified facts；无 verified 时
       │    │   可提 RECON/验证类 intent（标注 based_on_hypotheses）
       │    ├─ 知识路由：可提出"必须调用 search_knowledge"的 intent
       │    ├─ 输出：verdict(explore/course_correct/complete) + intents
       │    └─ trace：logs/trace-coordinator-*.jsonl（assistant_message+plan）
       └─ 3 个 Codex worker（gpt-5.5）
            ├─ 工具：bash/sandbox、黑板、submit_flag、search_knowledge（query+top_k 双参数）
            ├─ 预算：turn 1 次 / solver 8 次 / challenge 24 次 / 32k 字符上下文
            ├─ 去重缓存：同 query+top_k 命中 cache_hit 不计 queries
            └─ trace：logs/trace-*.jsonl（tool_call/tool_result/assistant_message/
                 knowledge_searched(含 query_outcome)/turn_failed）
```

- **Stage 1**：evidence 黑板（SQLite WAL 事件源、intent claim/lease/complete 状态机、fact/hypothesis/dead_end 区分、flag 确认兜底）——对齐 `muteki-main/muteki/swarm/shared_graph.py` 语义
- **Stage 2**：SQLite FTS5 lexical RAG（v2 中文单字分词、schema 迁移、service 边界、CLI 返回码、72 篇受控语料）
- **Stage 3（进行中）**：预算/query_outcome、S3.0 gate、评估基建（repeats/seed/随机化顺序）、LLM coordinator、细粒度验证体系

## 3. 模块地图

| 路径 | 职责 |
|---|---|
| `backend/agents/coordinator.py` | muteki 式规划器：单轮 Codex JSON-RPC、证据审计 prompt、容错 plan 解析、独立 trace、propose 去重 |
| `backend/agents/swarm.py` | ChallengeSwarm：solver 调度、coordinator 触发循环（`_evidence_signature`+`_coordinator_loop`）、知识预算对象、flag 兜底 |
| `backend/agents/codex_solver.py` | Codex worker：JSON-RPC 协议、工具执行（含 search_knowledge 预算/缓存/outcome）、assistant_message 记录、QUOTA_ERROR 分类 |
| `backend/knowledge/` | store（FTS5/迁移）、service（边界+白名单+0 命中 fallback）、budget（共享预算）、indexer、models |
| `backend/evidence/` | 黑板事件源与 intent 状态机 |
| `backend/benchmarks/` | runner（swarm 级指标聚合）、models、cli、providers |
| `scripts/` | bootstrap/index/search_knowledge/run_rag_eval/analyze_rag_compare/generate_stage3_gate/eval_knowledge_recall/rag_tool_probe |
| `knowledge/` | 73 篇语料：official 35（CWE/ELF-PE/协议/工具）、reference 33（解法模式卡片）、internal_notes 4 |
| `benchmarks/rag_eval/` | 测试集：knowledge_probe(v1)/v2/v3_fast/v4 + qrels 标注字段 |

## 4. 关键机制备忘（踩过的坑）

1. **source_type 过滤曾清零结果**：模型传 `ctf_pattern/all` 等自创标签被当精确过滤 → 已修：白名单外忽略 + **0 命中时自动 fallback 全库**（service 层，status=fallback）；工具面已收缩为 `query+top_k` 双参数（杜绝误传）
2. **中文检索**：unicode61 把连续 CJK 当一个 token → v2 索引侧单字分词（schema migration 已就绪，v1 库自动迁移）
3. **swarm 无 winner 丢诊断**：`_no_result_result`/`_timeout_result` 保留真实 trace/step/cost/知识指标（否则出现 calls=0 假象）
4. **tool_calls 统计**：全 swarm 求和（`_swarm_tool_calls`），与知识指标口径一致
5. **coordinator 触发**：签名含 hypothesis（solver 每轮自动写入）才可触发；45s 冷却限频；连续空计划退避（记录 65）
6. **turn_failed 闭包坑**：coordinator 的 turn_failed 分支曾因 nonlocal 缺失成为死代码（记录 70 已修，有脚本化协议回归测试）
7. **API 余额 403**：归类 QUOTA_ERROR fail-fast，不进入重试循环（记录 68）
8. **环境不可用题**：`just-another-pickle-jail`/`noisier-crc`（Debian buster 源 404，构建失败）、`frog-waf`（registry 403）→ manifest 标 `environment_unavailable`，run_rag_eval 自动跳过
9. **RAG 调用率突破 0 的路径**（记录 64/65/66）：coordinator 提出"必须检索知识"的 intent + worker 自主检索 → kq=3/hits=7、kq=4/hits=20，并出现 on 2/2 solve 翻转（RAG 收益可复现信号）

## 5. 实验数据摘要（log 记录 42-72）

| 轮次 | 测试集 | 结果 | 结论 |
|---|---|---|---|
| v1 | 6 题（旧语料/旧提示词） | off 3/6, on 4/6, **kq=0** | 模型不使用工具；pilot 触发安全拦截 |
| v2 | 11 题（72 篇语料+提示词段） | off 2/11, on 3/11, **kq=0**（假象：旧 runner 丢指标+source_type 清零） | 大量 token 耗尽（500k 预算偏紧）；8 题 calls=0 是诊断丢失 |
| v3 | 4 快题（修复后，3-solver） | off 4/4, on 4/4, **kq=0** | easy 题无"缺知识时刻"，RAG on 反而贵 $1.10 |
| v4 | 7 题（+3 medium） | off 4/7, on 5/7, **kq=0**；coordinator 零触发（签名不含 hypothesis） | 修复触发后重测 |
| v5 | v4 测试集 repeats=2 | 进行中（记录 71 启动；余额曾耗尽恢复后重跑） | 待汇总；前导单题验证 kq>0、RAG solve 翻转 2/2 |

## 6. 当前状态与运行中任务

- **v5 compare（repeats=2）**：记录 71 启动，当前是否运行以 `docker ps` / `results/rag_eval_v5*` 为准；跑完用 `analyze_rag_compare.py` 汇总
- 知识库：`logs/knowledge.sqlite3` 72 文档/403 chunks/schema v2（若语料有改动需重新 bootstrap）
- git：本地=origin/rag_branch，工作树干净（仅 cybench 子模块内部差异）

## 7. 待办 / 下一步（按优先级）

1. **v5 结果汇总**：off/on × 2 replicates 的 solve rate、成本、kq 对比；确认 coordinator 触发数、proposed intents、trace 可观测
2. **RAG 收益判定**：用"调用过知识的 run vs 未调用的 run"分组对比耗时/成本/solve（"调用 RAG 效率更高"的证明路径）
3. **qrels 正式化**：knowledge_probe_v4 的 chunk 级 qrels 文件（主审+复核），Recall@5/MRR 计算
4. **3-replicate 正式评估**（Stage 3 §6.2 门槛）：`--repeats 3`，随机化 off/on 顺序（已支持）
5. **coordinator 调优**：intent 质量抽查、冷却/退避参数、是否引入 verdict=complete 联动停机
6. **Stage 4 决策**：仅在 ≥20 题 qrels 上 Recall@5<0.80 或 MRR<0.50（≥3 replicates、排除语料/query/solver 因素）后立项向量检索
7. **语料运营**：manifest 版本化、回归查询集固化、删除/回滚演练（S3.5）

## 8. 已知风险

- 模型额度：API 余额 403 会 fail-fast（QUOTA_ERROR）；v5 曾因余额中断，重跑前检查余额
- 模型安全策略：shellcode/恶意软件类题（pilot 等）会触发 provider 拦截，测试集已规避
- 服务端交互题 token 消耗大：`--max-tokens 1M` 已缓解，但 medium 题（matrix-lab-2）仍可能超时
- 并行会话写入冲突：log.md 编号唯一性需在追加前检查；.codex-diffs 已 gitignore
