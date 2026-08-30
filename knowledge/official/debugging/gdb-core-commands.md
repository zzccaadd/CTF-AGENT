---
source_url: https://www.sourceware.org/gdb/current/onlinedocs/gdb.html/gdb-man.html
source_title: Debugging with GDB
source_version: "19.0.50.20260827-git"
publisher: GNU Project / Free Software Foundation
license: GNU Free Documentation License 1.3
retrieved_at: 2026-08-31
topic: debugging
tool_name: gdb
---
# GDB：基础定位命令

## 最小工作流

使用 `gdb <program>` 启动调试。用 `break function` 或 `break file:line` 设置断点，`run [args]` 启动程序，程序暂停后用 `bt` 查看调用栈、`print expr` 查看表达式、`info registers` 查看寄存器，最后用 `continue` 继续执行。

## 崩溃分析

崩溃后先保存信号、程序计数器和调用栈，再确认当前线程和栈帧。`bt` 默认显示当前线程的栈；多线程场景可以使用 `thread apply all backtrace` 查看全部线程。调用栈中的函数、文件行号和参数应与寄存器及内存观测交叉验证。

## 自动化边界

断点命令列表可以在命中断点时自动执行检查，但恢复执行的命令之后的内容不会继续执行。solver 应先用少量命令确认状态，再继续或退出，避免无限自动化循环。
