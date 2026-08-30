---
source_title: Shared blackboard usage — project internal notes
source_version: "1.0"
publisher: CTF-Agent project
license: project internal
retrieved_at: 2026-08-31
topic: internal-operations
---

# 共享黑板（Blackboard）使用规则

## 概念

黑板是同一道题内多个 solver 协作的共享状态：intent（任务）、fact（已验证事实）、hypothesis（未验证假设）、dead end（已排除路线）。所有事件写入 evidence 库并带 provenance。

## 工具与用法

- `blackboard_intents`：列出开放 intent；`blackboard_claim <intent_id>` 认领一个任务。**一个 worker 同时只能认领一个 intent**，完成后再认领下一个。
- `blackboard_fact <fact>`：只记录**真实工具输出中观察到的事实**，不带猜测。
- `blackboard_hypothesis <hypothesis>`：未经验证的推测，供他人验证。
- `blackboard_dead_end <reason>`：被真实测试排除的路线，防止其他 worker 重试。
- `blackboard_complete <intent_id> <result>`：完成任务并写结果；`blackboard_summary`：查看全局进展。

## 纪律

- fact 必须可追溯到工具输出；knowledge 检索结果只是参考资料，未经验证不能写成 fact。
- 同一事实不要重复写：先看 `blackboard_summary` 再写；重复写入会增加噪声。
- 认领后要持续推进自己的 intent；发现别的 intent 已被认领时不要抢。
- 每题完成后，本题黑板内容只属于本题，不进入通用知识库。
