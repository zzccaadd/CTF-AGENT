---
source_url: https://refspecs.linuxbase.org/elf/x86_64-abi-0.99.pdf
source_title: System V Application Binary Interface AMD64 Architecture Processor Supplement
source_version: "0.99"
publisher: Linux Foundation / System V ABI
license: upstream specification terms
retrieved_at: 2026-08-31
topic: binary-format
tool_name: readelf
---
# ELF：静态分析基础

## 关键对象

ELF 文件由文件头、程序头表和节区组成。文件头给出入口地址、目标架构和相关表的位置；程序头描述装载器需要的 segment；节区通常服务于链接、符号和调试。分析时先区分“装载视角”的 segment 与“链接视角”的 section。

## 入口和装载

入口地址是程序开始执行的位置，但不一定等于用户定义的 `main`。应结合解释器、可执行 segment 的权限、基址和重定位信息判断真实运行布局。PIE 可执行文件的静态地址需要与运行时加载基址区分。

## 建议检查顺序

先确认架构和端序，再查看入口、segment 权限、动态依赖、重定位和符号。用 `readelf`、`objdump` 或分析器输出互相核对；任何地址结论都要标明是文件偏移、虚拟地址还是运行时地址。
