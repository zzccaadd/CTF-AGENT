---
source_url: knowledge/reference/pwn/ret2libc.md
source_title: ret2libc — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: pwn
tool_name: pwntools
---

# ret2libc（泄露 libc 基址与 one_gadget）

> 从多份已审核 writeup 提炼的通用解法模式，不含任何具体题目的 flag、附件、地址或 payload 内容。

## 核心概念

NX 开启且无可执行注入空间时，复用 libc 中现成的 `system`/`execve`。libc 地址随 ASLR 每次变化，关键是先**泄露** libc 中某个已解析函数的真实地址，算出 libc 基址，再推算目标函数与字符串的实际地址。

## 关键细节

1. **泄露基址**：用 `puts`/`printf`/`write` 打印 GOT 中某函数（如 puts）的真实地址，打印完回到 main 以便二次输入：
   ```python
   payload = flat({offset: [pop_rdi, elf.got["puts"], elf.plt["puts"], elf.symbols["main"]]})
   leak = u64(io.recvuntil(b"\n", drop=True).ljust(8, b"\x00"))
   libc.address = leak - libc.symbols["puts"]
   system = libc.symbols["system"]
   binsh = next(libc.search(b"/bin/sh"))
   ```
2. **libc 版本匹配**：泄露 2–3 个符号（如 puts/printf/read）后用 `LibcSearcher` 匹配，或 libc-database（libc.rip）`find puts <addr> printf <addr>` 查版本；本地与远端 libc 必须一致，否则所有偏移全错。
3. **one_gadget**：`one_gadget ./libc.so.6` 输出可行地址及**约束条件**（如 rsp 某偏移处必须为 0、某寄存器必须为 0）。约束不满足会崩溃，需用栈迁移、堆喷或调整环境来凑约束。
4. **32 位**：参数全在栈上，链为 `padding + system + fake_ret + binsh_addr`，无需 pop gadget。64 位 execve 需 rdi/rsi/rdx 三参，一般 `pop rdi; ret` + binsh + `pop rsi; ret` + 0 + `pop rdx; ret` + 0 + execve 地址。

## 常见坑

- 泄露输出可能含 `\n` 或被截断：用 `recvuntil(b"\n", drop=True)` 精确截取再 ljust 补足 8 字节。
- 解包时统一 `ljust(8, b"\x00")`，地址高字节天然为 0，别补 `\xff`。
- 本地 libc 与远端不同 → 全部地址错：先确认远端 libc 版本。
- one_gadget 多条候选约束不同，要逐一测试，别只试第一条。
- 第二次进入 main 后栈深度与第一次可能不同，偏移需重新确认或保持相同调用路径。

## 验证方式

- 本地 gdb `p puts` 与泄露值对照，确认基址计算正确。
- one_gadget 候选逐个本地验证稳定性。
- 远端执行成功拿到 flag 才算完成；失败先核对 libc 版本。
