---
source_title: search_knowledge tool usage — project internal notes
source_version: "1.0"
publisher: CTF-Agent project
license: project internal
retrieved_at: 2026-08-31
topic: internal-operations
---

# search_knowledge 使用约定

## 工具说明

`search_knowledge(query, source_type?, metadata?, top_k?)` 检索本地受控知识库，返回带 provenance 的片段（document_id、chunk_id、source URL、标题、section、行号、trust level）。纯本地检索，不产生网络请求。

## 何时调用

适合：遇到不熟悉的 ABI/文件格式/协议/漏洞类别；需要工具（gdb/pwntools/z3/Volatility…）的准确语法或参数语义；已有观测但需要通用机制资料形成下一步假设。

不适合：查询本题 flag、附件内容、challenge-specific 解法；宽泛无目的搜索；模型刚在工具输出里直接看到的内容；需要实时外部信息（应走 sandbox/网络工具）。

## 参数边界

- `query`：必填，≤512 字符；空或超长会返回 invalid 诊断。
- `source_type`：`official` / `reference` / `internal_notes`（白名单）；其他来源不会返回。
- `metadata`：扁平键值 ≤8 个，键值各 ≤256 字符。
- `top_k`：默认 5，最大 10；单次返回累计 ≤8000 字符。
- 单 turn 最多 1 次知识查询；单题累计不要超过预算（默认单 solver 8 次 / 单题 32,000 字符上下文）。

## 结果使用

- 检索结果是参考资料，不是自动事实：关键结论必须用 sandbox 真实工具输出验证。
- 无命中返回 "no usable results"，属正常情况，继续 sandbox 分析即可。
- 同 query 已查过且语料未变时不要重复查询；先看黑板/当前上下文是否有可用结果。
- 引用时注意来源冲突：不同资料不一致时保留各自的 source/版本/trust level，先作为 hypothesis，再用可重复观测解决。
