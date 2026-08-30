---
source_url: knowledge/reference/pwn/seccomp-bypass.md
source_title: Seccomp sandbox bypass (orw) — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: pwn
tool_name: seccomp-tools
---

# Seccomp 沙箱绕过（ORW：open/read/write）

> 从多份已审核 writeup 提炼的通用解法模式，不含任何具体题目的 flag、附件、地址或 payload 内容。

## 核心概念

seccomp 用 BPF 规则限制系统调用：常见配置是禁止 `execve`（拿不到 shell）但保留 `open`/`read`/`write`。此时目标从"get shell"变成"**直接读 flag 文件**"：open → read → write 三段链，简称 ORW。

## 关键细节

1. **读规则**：`seccomp-tools dump ./bin` 输出 BPF 规则；先确认禁了哪些 syscall、白名单有哪些，再决定手法。
2. **ORW 链（64 位）**：ROP 依次调用：
   ```python
   payload = flat({off: [
       pop_rdi, path_addr,      # open(path, O_RDONLY)
       pop_rsi, 0,
       open_plt,
       pop_rdi, fd,             # read(fd, buf, size)
       pop_rsi, bss_addr,
       pop_rdx, 0x50,
       read_plt,
       pop_rdi, 1,              # write(1, buf, size)
       pop_rsi, bss_addr,
       pop_rdx, 0x50,
       write_plt,
   ]})
   ```
   无对应 PLT 符号时用 `syscall` gadget + 各寄存器 pop（常用调用号：open=2、read=0、write=1、openat=257）。
3. **openat 的坑**：第 4 参 mode 在 r10 寄存器，常规 `pop r10` gadget 极少见——需要 ret2csu 或 SROP。SROP 用 `rt_sigreturn` 伪造 sigframe 一次性设置全部寄存器（pwntools `SigreturnFrame()`），适合参数多的系统调用。
4. **路径与 fd**：flag 文件路径优先用题目线索或常见默认路径；`open` 返回当前最小可用 fd（通常 3），多次打开后 fd 递增，链中要写实际值。
5. **绕过变体**：禁 `open` 但允许 `openat` 时换 openat；禁 `write` 时考虑侧信道（时间/退出码）或换输出通道。

## 常见坑

- read 的 buf 必须指向可写内存（bss 段），写只读段直接崩溃。
- fd 号写死导致读错文件：先本地确认 open 返回的 fd。
- 64 位 openat 缺 r10 pop：别硬拼 ROP，直接上 SROP/csu。
- 老内核不支持部分新 syscall 号（如 openat2），选目标内核支持的调用。
- ORW 后输出可能滞留缓冲区，链尾可加 `exit` 或确认 stdout 已刷新。

## 验证方式

- `seccomp-tools dump` 与本地 `strace -f` 对照确认实际拦截行为。
- 本地放一个测试文件，用完整链读出来，验证三段调用逐字节正确。
- 远端执行成功拿到 flag 才算完成。
