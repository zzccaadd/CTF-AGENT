---
source_url: https://volatility3.readthedocs.io/en/latest/basics.html
source_title: Volatility 3 documentation：Basics
source_version: "2.28.2"
publisher: Volatility Foundation
license: upstream project terms
retrieved_at: 2026-08-31
topic: memory-forensics
tool_name: volatility3
---
# Volatility 3：内存取证基础

## 核心模型

Volatility 3 将内存分析拆成 memory layers、templates/objects 和 symbol tables，并把它们放在 `Context` 中。虚拟地址到物理数据的访问通过 layer 图完成，不能把原始文件偏移直接当作进程虚拟地址。

## 插件使用

命令行通常采用 `python3 vol.py -f <memory-image> <plugin>`。插件名称可能带操作系统前缀，例如 `linux.pslist`；插件参数应通过对应的 `--help` 确认。分析报告应记录镜像来源、符号表版本、插件名称和参数。

## 解释结果

插件输出是观测结果，不是自动结论。进程、模块、命令历史等发现需要结合时间线、内存层配置和其他插件交叉验证；符号表不匹配时应先修复环境，不要根据异常地址直接下结论。
