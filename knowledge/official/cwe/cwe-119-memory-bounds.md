---
source_url: https://cwe.mitre.org/data/definitions/119
source_title: CWE-119 Improper Restriction of Operations within the Bounds of a Memory Buffer
source_version: "4.20"
publisher: MITRE
license: MITRE CWE terms
retrieved_at: 2026-08-31
topic: memory-safety
cwe_id: CWE-119
---
# CWE-119：内存缓冲区边界

## 核心概念

当程序读写内存时没有限制在目标缓冲区边界内，就会产生越界访问。越界读可能泄露相邻对象或地址，越界写可能破坏数据、控制流，甚至导致代码执行。

## 分析要点

分析二进制时，先确认缓冲区的实际容量、输入长度计算方式和复制循环的终止条件，再判断越界读写能影响哪些对象。不要只依据函数名判断漏洞，必须结合长度来源、整数转换和终止符处理。

## 防御与验证

对所有复制和拼接操作显式检查目标容量；循环访问数组时验证索引；对外部输入设置合理上限；结合 ASLR、PIE 等环境加固降低地址利用的稳定性。漏洞结论需要由调试器观测或可重复的最小 PoC 支持。
