---
source_url: https://docs.pwntools.com/en/stable/index.html
source_title: pwntools documentation
source_version: "4.15.0"
publisher: Gallopsled / pwntools contributors
license: upstream project terms
retrieved_at: 2026-08-31
topic: exploit-development
tool_name: pwntools
---
# pwntools：CTF 自动化基础

## 适用场景

pwntools 是面向 CTF 和 exploit 原型的 Python 工具库，常用能力包括进程或远程连接、整数打包、汇编/反汇编、ELF 符号访问、循环序列生成和 shellcode 辅助生成。

## 脚本基本结构

脚本应先设置目标架构和端序，再创建本地进程或远程连接；发送数据后明确读取边界，避免把一次 `recv` 当作完整响应。调试阶段可以把日志级别和本地/远程模式做成配置，而不是散落在 payload 中。

## 使用注意

`p64`、`p32` 等打包操作必须匹配目标位数和端序；`cyclic` 生成的偏移需要用崩溃时实际覆盖值反查；ELF 地址、libc 地址和 PIE 基址不能混为一谈。任何 exploit 结论都应保留输入、响应和目标环境记录。
