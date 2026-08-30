# CTF Agent

CTF Agent 是一个自动化 CTF 解题系统，采用 coordinator + solver swarm 的架构。它会把题目放进隔离的 Docker sandbox 中运行，支持多种 solver 后端，并提供可复现的 benchmark 框架来比较不同题集上的 solver 表现。

## 这个项目做什么

- 在 Docker 中端到端运行 CTF 题目
- 由 coordinator 分配给一个或多个 solver
- 将题目执行与宿主机隔离
- 收集 trace、成本和解题结果
- 提供可重复的 benchmark manifest，用于 baseline 和 RAG 风格评估

## 仓库结构

- `backend/` - 核心 agent、benchmark 和 sandbox 逻辑
- `scripts/` - benchmark 构建与运行脚本
- `benchmarks/` - benchmark 语料和整理好的评估清单
- `results/` - 生成的 benchmark 结果
- `logs/` - solver trace 和运行日志

## 默认模型

当前 benchmark 默认模型是 `codex/gpt-5.6-luna`。

## RAG 评估

整理好的 RAG 评估在 `benchmarks/rag_eval/`：

- `main_100.json` - 全量 benchmark 集
- `smoke_20.json` - 快速 smoke 集
- `rag_sensitive_100.json` - 对 RAG 更敏感的题集
- `smoke_20_no_character.json` 和 `smoke_20_after_delulu.json` - smoke 调试时生成的临时局部子集

生成这些 manifest：

```bash
uv run python scripts/build_rag_eval_sets.py
```

运行评估：

```bash
uv run python scripts/run_rag_eval.py
```

默认 runner 配置：

- model: `codex/gpt-5.6-luna`
- timeout: `1800`
- max tokens: `500000`
- concurrency: `1`
- solvers per swarm: `1`
- max solvers per swarm: `1`

结果会写入 `results/rag_eval/`，包含按 provider 拆分的结果文件，以及合并后的总结果文件。

### 评估流程

1. 从两个上游语料中选题。
2. 把选题写成 JSON manifest。
3. runner 读取 manifest，按 provider 分组，并在本地发现对应题目定义。
4. 每道题在隔离的临时工作区中准备。
5. solver 在固定 token 限额和单次尝试下运行。
6. 用本地 verifier 校验提交的 flag。
7. 最终 JSON 结果记录 solve rate、token 使用量、成本、耗时和 trace 路径。

### 数据集来源

这些评估 manifest 基于以下上游数据集：

- NYU CTF Bench: https://github.com/NYU-LLM-CTF/NYU_CTF_Bench
- Cybench: https://github.com/andyzorigin/cybench

本地常见克隆路径：

- `~/benchmarks/NYU_CTF_Bench`
- `~/benchmarks/cybench`

这些上游语料保留在本地即可，不需要提交进本仓库。
`.gitignore` 已经把这类本地语料路径排除了，仓库里只保留 benchmark 定义、脚本和结果摘要。

## Benchmark 清单

- `main_100.json`: 57 道 NYU test 题 + 43 道 Cybench 题
- `smoke_20.json`: 10 道 NYU test 题 + 10 道 Cybench 题
- `rag_sensitive_100.json`: 偏向 RAG 敏感题的关键词筛选集合

## 注意事项

- API key 和本地运行文件不要提交到 Git。
- 改代码走 feature branch 和 PR。
- 保持 benchmark manifest 和生成脚本版本化，确保结果可复现。

## English Version

- [README.md](README.md)
