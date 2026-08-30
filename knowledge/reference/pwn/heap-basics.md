---
source_url: knowledge/reference/pwn/heap-basics.md
source_title: Heap exploitation basics — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: pwn
tool_name: pwntools
---

# 堆利用基础（chunk 结构与 bin 机制）

> 从多份已审核 writeup 提炼的通用解法模式，不含任何具体题目的 flag、附件、地址或 payload 内容。

## 核心概念

glibc ptmalloc2 用 chunk 管理堆内存，利用点集中在**元数据伪造**与**分配器状态篡改**：double free、UAF、堆溢出覆盖相邻 chunk 头部、篡改 fd/bk 指针控制后续分配返回地址。

## 关键细节

1. **chunk 头部（64 位）**：`prev_size`（8 字节，仅前一块被释放时有效）+ `size`（8 字节，低 3 位标志：P/PREV_INUSE=0x1、M/IS_MMAPPED=0x2、N/NON_MAIN_ARENA=0x4）；`size` 16 字节对齐，用户可用区 = size - 0x10。malloc 返回的用户指针 = chunk 头 + 0x10。
2. **释放后**：chunk 进入对应 bin，fd/bk 指针写入用户区前 8/16 字节；fastbin 是 LIFO 单链表，smallbin 是双向链表。
3. **unsorted bin 泄露 libc**：非 fastbin 的 chunk 释放后先进 unsorted bin，其 fd/bk 指向 main_arena 附近；UAF/越界读打印该指针后减去版本相关偏移即得 libc 基址。
4. **常见利用**：
   - **tcache poisoning（2.26+ 默认开启）**：篡改 tcache 中 chunk 的 fd 指向任意地址，随后两次 malloc 即返回该地址；注意 2.32+ 的 safe-linking（fd 被 `fd ^ (addr >> 12)` 异或加密，需先泄露堆地址）。
   - **double free**：同一 chunk 释放两次，使 fastbin/tcache 中出现重复项，分配时拿到同一地址从而覆盖其元数据。
   - **堆溢出**：覆盖相邻 chunk 的 size 与 PREV_INUSE，伪造大小触发 unlink 或扩大可写范围。
5. **调试**：pwndbg 的 `heap bins`、`heap chunks`、`vmmap heap` 观察 bin 状态与 chunk 布局。

## 常见坑

- glibc 版本决定一切：2.23 / 2.27 / 2.31 / 2.35 的 tcache 数量、double-free 检查、safe-linking 均不同，先确认目标版本再选手法。
- unsorted bin 泄露的地址偏移随版本与符号（main_arena 位置）不同，不要套用其他版本的固定偏移。
- 伪造 fd 时注意指向 chunk 头还是用户区，两者差 0x10 字节。
- tcache 每类大小只有 7 个槽位（2.31+ 有 count 字段），填满后 chunk 才进 fastbin/smallbin，流程别算错。

## 验证方式

- 本地 gdb + pwndbg 逐步观察 bin 变化与分配返回地址。
- 每步（泄露、伪造、分配）单独验证后再拼最终利用。
- 与目标 libc 版本匹配后远端复测。
