---
source_url: knowledge/reference/pwn/rop-chains.md
source_title: ROP chain construction — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: pwn
tool_name: pwntools
---

# ROP 链构造（gadget 搜索与传参）

> 从多份已审核 writeup 提炼的通用解法模式，不含任何具体题目的 flag、附件、地址或 payload 内容。

## 核心概念

ROP（Return-Oriented Programming）在 NX 开启、无法直接执行注入代码时，复用程序与共享库中已有的指令片段（gadget，以 `ret` 结尾）。核心思想是把控制流劫持变成"数据驱动"：把各 gadget 的地址依次压栈，`ret` 不断把栈顶地址弹入 RIP，链式完成任意调用（如 `system`、`mprotect`、`syscall`）。

## 关键细节

1. **gadget 搜索**：
   - `ROPgadget --binary ./vuln --only "pop|ret"` 按类别过滤；`--depth 20` 增大搜索深度（深 gadget 常藏在指令流中间的非对齐字节处）。
   - ropper：`ropper --file ./vuln --search "pop rdi"`。
   - pwntools：`ROP(elf)` 自动搜程序内 gadget 并可直接构建链。
2. **64 位传参**：前 6 个参数走寄存器 rdi/rsi/rdx/rcx/r8/r9；系统调用用 rax + rdi/rsi/rdx。最少需要 `pop rdi; ret`、`pop rsi; ret`、`pop rdx; ret`、`pop rax; ret` 等 gadget；32 位参数直接取自栈，无需此类 gadget。
3. **链的基本形式**（64 位调函数）：
   ```python
   rop = ROP(elf)
   rop.call("system", [next(elf.search(b"/bin/sh"))])
   payload = flat({offset: rop.chain()})
   ```
   手写时：`padding + pop_rdi + arg1 + pop_rsi + arg2 + func_addr`，注意 gadget 与参数交错入栈的顺序不能乱。
4. **栈对齐**：System V ABI 要求调用函数前 rsp 16 字节对齐，`system` 内 `movaps` 未对齐会直接 SIGSEGV。修复：目标函数前多放一个裸 `ret` gadget（栈上已压入奇数个地址时尤其必要）。
5. **缺 gadget 的替代**：
   - 用 `pop rsi; pop r15; ret` 这类多弹一个垃圾值的 gadget 凑寄存器。
   - ret2csu：`__libc_csu_init` 的通用序列（`pop rbx; pop rbp; pop r12; pop r13; pop r14; pop r15; ret` + `mov rdx, r15; mov rsi, r14; mov edi, r13d; call [r12+rbx*8]`）可任意传 3 参。
   - 先 `mprotect` 开 RWX 再跳 shellcode（见 shellcode 卡）。

## 常见坑

- PIE 开启时 gadget 地址 = 基址 + 偏移，必须先泄露基址再计算。
- ASLR 下 libc 内 gadget 每次运行都变，须先泄露 libc 基址。
- `flat()` 自动按位数打包，勿手写 `p64` 造成位数/大小端错误。
- 搜索深度不足会漏 gadget，报 "no gadgets" 时先加 `--depth`。
- 每个参数都要配对应 pop gadget，多一个少一个都会让整条链错位。

## 验证方式

- gdb 中 `x/10gx $rsp` 确认链按预期入栈，单步验证各 gadget 的 pop 效果。
- ROPgadget 与 pwntools `ROP` 交叉验证关键 gadget 地址。
- 本地脚本重复运行 3 次以上无随机失败，再打远端。
