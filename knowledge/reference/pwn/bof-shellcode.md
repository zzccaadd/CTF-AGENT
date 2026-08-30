---
source_title: Stack buffer overflow to shellcode — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: pwn
tool_name: pwntools
---

# 栈缓冲区溢出 → 控制流劫持 → shellcode（通用模式）

> 本文是从多份已审核 writeup 提炼的通用解法模式，不含任何具体题目的 flag、附件、地址或 payload 内容。

## 识别阶段

1. `checksec`（pwntools）确认保护状态：`NX`（栈不可执行）、`PIE`、`canary`、`RELRO`、`ASLR`（由内核决定）。
2. `file` + `readelf -hW` 确认架构（32/64 位）与端序；32 位无 canary 的栈溢出最直接。
3. 定位溢出点：寻找 `gets`、`strcpy`、`read` 到栈缓冲区的调用；用 `cyclic(200)` 生成模式串，崩溃后用 `cyclic_find(offset)` 求精确偏移。
4. 确认控制流：崩溃时 RIP/EIP 是否被模式串覆盖；`info registers` 确认可控寄存器。

## 攻击面选择（按保护状态分支）

- **无 NX（栈可执行）**：`shellcraft` 生成 shellcode + 跳板（`jmp esp`/`call esp` 或 NOP sled + 栈地址）。栈地址不稳定时优先找 `jmp esp` gadget。
- **有 NX（经典 ROP 的前置）**：先用 `ROP` 类找 `pop rdi; ret` 等 gadget 完成 `execve("/bin/sh")`，或 `mprotect` 开可执行页再跳 shellcode。
- **有 canary**：先泄露 canary（格式化字符串或逐字节爆破），payload 布局为 `padding | canary | padding | ret`。
- **PIE**：先泄露基址（泄漏 GOT 或返回地址再计算），gadget 地址 = 基址 + 偏移。

## 标准解题步骤

1. 本地用同样的保护参数复现崩溃（`gdb` + `set disable-randomization on`）。
2. 写 pwntools 脚本：`sendlineafter` 同步交互 → 构造 payload → `recv` 解析泄露值。
3. 无交互条件时用 `process`/`remote` 参数化，先本地后远端。
4. 拿到 shell 后 `cat flag*`；注意远端路径可能与本地不同。

## 常见坑

- 溢出点后还有数据校验（如长度检查）时，先满足校验再触发。
- 32 位传参走栈、64 位走寄存器（rdi/rsi/rdx…），ROP 链构造不同。
- 单次 `recv` 可能截断输出：循环 `recvuntil` 到稳定标记。
- 远端 ASLR 开启时，任何栈/堆地址都必须以泄露值为准，不能写死本地地址。

## 验证方式

- 本地脚本重复执行 3 次以上无随机失败；远端执行成功拿到 `flag` 才算完成。
- 每步（偏移、泄露、劫持）单独验证后再拼整链，避免一次性的"碰运气" payload。
