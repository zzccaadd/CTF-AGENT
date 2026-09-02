---
source_url: knowledge/reference/pwn/format-string.md
source_title: Format string exploitation — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: pwn
keywords_en: format string, printf, %n, 格式化字符串
cwe_id: CWE-134
---

# 格式化字符串利用（泄露与任意写）

> 从多份已审核 writeup 提炼的通用解法模式，不含任何具体题目的 flag、附件、地址或 payload 内容。

## 核心概念

`printf` 系列函数把用户可控内容当作格式串。格式串按参数位置依次消费栈上数据：`%p`/`%s` 泄露，`%n` 系列写内存。利用只需两步——确定输入内容在参数列表中的**偏移**，然后按偏移读写。

## 关键细节

1. **定位偏移**：输入 `%p.%p.%p...`（或 `%1$p|%2$p|...`）观察输出序列，找到自己输入内容出现的位置，即该输入在栈上对应的参数序号。
2. **泄露**：`%<n>$p` 打印第 n 个参数；`%<n>$s` 把第 n 个参数当作指针解引用打印字符串，可泄 GOT 表或任意可读地址内容。64 位下前 6 个参数在寄存器（rdi/rsi/rdx/rcx/r8/r9），栈上参数从第 7 位起编号。
3. **任意写**：`%hhn` 写 1 字节、`%hn` 写 2 字节、`%n` 写 4 字节，写入值 = 当前已输出字符数：
   ```python
   payload = fmtstr_payload(offset, {target_addr: value}, write_size="short")
   ```
   pwntools 自动生成"填充到目标值再写"的序列；手写时为 `%<count>c%<n>$hhn`。
4. **64 位地址含 `\x00`**：目标地址必须放在格式串**开头**或分多次写，否则被 `\x00` 截断；地址按小端序从低字节地址开始排布。
5. **多字节拆分**：一次写 4/8 字节通常拆成多次 `%hhn`（每次只影响 1 字节），避免填充数亿字符导致超时。

## 常见坑

- `%s` 解引用不可读地址会崩溃：先确认目标地址可读。
- 大填充（`%100000c`）易超时/打爆输出缓冲，优先拆分多次写。
- offset 估算错误（64 位常见）：一律用 `%p` 实测，不要凭寄存器规则硬推。
- full RELRO 下 GOT 不可写：改用 `__free_hook` 等可写函数指针、返回地址或 setcontext 链。
- 程序限制格式串长度时，优先短写法（单字节写 + 最小填充）。

## 验证方式

- 本地确认 offset 与目标地址可读性；gdb 对比写入前后内存值。
- 先单独验证泄露步（打印值与 gdb 一致），再上写链。
- 远端执行成功拿到 flag 才算完成。
