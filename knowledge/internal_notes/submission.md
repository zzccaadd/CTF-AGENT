---
source_title: Flag submission and verification — project internal notes
source_version: "1.0"
publisher: CTF-Agent project
license: project internal
retrieved_at: 2026-08-31
topic: internal-operations
---

# Flag 提交与验证流程

## 提交流程

- 用 `submit_flag <candidate>` 工具提交候选 flag；不要只在报告里写 "FLAG: xxx" 而不提交。
- 提交结果由本地 verifier（benchmark 环境）或 CTFd（在线环境）判定：`CORRECT` / `ALREADY SOLVED` 表示通过。
- 通过后立即输出 `FLAG: <value>` 并结束；确认后同 turn 即使撞到 token 上限或错误，也要以已确认 flag 为准返回结果。

## 候选 flag 规则

- 忽略占位 flag：`CTF{flag}`、`CTF{placeholder}`、示例格式都不是真实答案。
- 每个候选都要验证，不要凭格式猜测直接结束。
- flag 可能藏在：文件末尾/隐藏文件、环境变量、服务输出、图片/文档隐写、程序运行结果中；以实际观测为准。

## 错误处理

- 提交失败（网络/服务不可用）只影响本次提交，不终止解题：继续分析并重试。
- 同一个候选重复提交会浪费调用：先确认新信息再提交。
- 若 flag 已确认但结果未返回（预算耗尽等边界），系统有兜底逻辑保留已确认 flag，无需重复提交。
