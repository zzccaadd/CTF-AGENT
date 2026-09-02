---
source_url: knowledge/reference/pwn/shellcode-constraints.md
source_title: Shellcode constraints and generation — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: pwn
keywords_en: shellcode, constraints, alphanumeric, 约束
tool_name: pwntools
---

# Shellcode 编写约束与生成（长度 / 坏字符）

> 从多份已审核 writeup 提炼的通用解法模式，不含任何具体题目的 flag、附件、地址或 payload 内容。

## 核心概念

把可执行指令注入可写可执行内存并跳转。约束维度：可执行空间**长度**、输入过滤的**坏字符**（如 `\x00`、`\x0a`、`\x20`）、可用字符集（如仅字母数字）、以及 NX 是否开启。

## 关键细节

1. **生成**：pwntools `asm(shellcraft.sh(), arch="amd64")` 生成 `execve("/bin/sh")`；`shellcraft.i386.linux.sh()` 对应 32 位。短场景用 `shellcraft.amd64.linux.cat(...)` 之类直接读文件的小型 shellcode。
2. **坏字符校验**：`asm(code, arch="amd64", badbytes=b"\x00\x0a")` 汇编后自动校验，含坏字节即抛错；规避手段：
   - 立即数拆分：把含 0 的 `mov rax, <大数>` 改写成先 `xor rax, rax` 再分步赋值，或 `push` 到栈上再 `pop`。
   - 字符串入栈：`push <字符串片段>` + `mov rdi, rsp` 替代含 0 的 mov 指令。
3. **长度受限**：先 `asm()` 看长度，超限时手写精简版（如 20~30 字节的 execve：`xor` 清寄存器 + `push` 路径 + `syscall`）；或分两次注入（第一次读入、第二次跳转执行）。
4. **字符集受限（字母数字）**：`shellcraft.amd64.alphanumeric_encoder` 或 msfvenom `-e x86/alpha_mixed` 编码；注意编码后长度膨胀数倍，先算好空间。
5. **跳转稳定性**：栈地址随 ASLR 波动，优先 `jmp rsp`/`call rsp`/`push rsp; ret` 或已知寄存器（如 `jmp rbx`）；NOP sled（`\x90`）提高命中率。
6. **NX 开启**：先 `mprotect` 把内存页改为 RWX 再跳 shellcode，或直接 ret2libc，不要硬塞 shellcode。

## 常见坑

- `shellcraft.sh()` 产物含 `\x00`（如 `mov rax, 59` 的编码），直接注入常被截断，先检查字节。
- 32 位与 64 位 syscall 号不同（execve 分别为 11 与 59），混用必崩。
- 可执行段空间不够时先 `readelf -l` / `vmmap` 找大块 RWX 段，别在不足的缓冲区里硬塞。
- 坏字符过滤可能同时含 `\x0a`（换行）与 `\x20`（空格），按提示逐一排除。
- alphanumeric 编码后超长是常态，先估长度再决定是否换方案。

## 验证方式

- `asm()` 后 `print(hexdump(code))` 确认无坏字符、长度达标。
- 本地注入后执行成功（gdb `x/20i` 反汇编确认指令符合预期）。
- 远端执行拿到 flag 才算完成。
