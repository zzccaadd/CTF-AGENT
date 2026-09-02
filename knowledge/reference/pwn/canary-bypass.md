---
source_url: knowledge/reference/pwn/canary-bypass.md
source_title: Stack canary bypass — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: pwn
keywords_en: stack canary, canary bypass, 金丝雀
tool_name: pwntools
---

# Canary 绕过（泄露与爆破）

> 从多份已审核 writeup 提炼的通用解法模式，不含任何具体题目的 flag、附件、地址或 payload 内容。

## 核心概念

canary 是函数序言写入栈的随机值，返回前经 `__stack_chk_fail` 校验，防止覆盖返回地址。canary 每进程生成一次（来自内核 AT_RANDOM），绕过思路两条：**泄露**（读出来后原样回填）或**爆破**（fork 型服务子进程 canary 不变，逐字节试探）。

## 关键细节

1. **位置与布局**：canary 位于缓冲区与 saved rbp 之间（高地址侧）；64 位 canary 低字节固定为 `\x00`（防泄露），payload 布局为 `padding + canary + padding + ret_addr`。
2. **泄露路径**：
   - 存在格式化字符串：`%<n>$p` 定位并读出 canary（先用 gdb 对比确认位置）。
   - 越界读：如 `gets` 后直接 `printf(buf)`，把缓冲区后面紧跟的 canary 一并打印。
   - 泄露值要**完整回填**，包括低字节 `\x00`（否则 strcpy/gets 类输入会被截断，payload 直接残废）。
3. **爆破**：fork 型服务每个连接 fork 的子进程 canary 相同，逐字节从低到高试：
   ```python
   for i in range(1, 8):
       for b in range(256):
           payload = b"A" * off + known + bytes([b])
           # 发送 payload；服务仍存活则当前字节正确
   ```
   每字节最多 255 次尝试，连接崩溃即当前字节错误。
4. **触发特征**：canary 被破坏时 stderr 输出 `*** stack smashing detected ***`，可据此判断字节对错。

## 常见坑

- canary 与 ASLR 相互独立：gdb `set disable-randomization on` **不能**固定 canary。
- 32 位 canary 4 字节、64 位 8 字节，爆破轮数与字节数不同。
- 别把 saved rbp 当成 canary 覆盖：顺序是 buf → canary → rbp → ret。
- 爆破只适用于父进程常驻、子进程处理请求的 fork 服务；多线程程序共享进程级 canary 但新 fork 会重新生成。
- 泄露的 canary 记得带低字节 `\x00` 一起回填。

## 验证方式

- gdb 在函数返回处比对 `__stack_chk_fail` 前的 canary 内存与泄露值是否一致。
- 爆破脚本先在本地起同构服务验证成功率，再打远端。
