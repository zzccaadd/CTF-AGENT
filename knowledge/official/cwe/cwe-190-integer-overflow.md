---
source_url: https://cwe.mitre.org/data/definitions/190.html
source_title: "CWE-190: Integer Overflow or Wraparound"
source_version: "4.20"
publisher: MITRE
license: MITRE CWE terms
retrieved_at: 2026-08-31
topic: integer-overflow
cwe_id: CWE-190
---
# CWE-190：整数溢出

## 核心概念

算术运算结果超出类型表示范围后发生回绕/溢出。C 语言中无符号整数溢出是定义行为（模 2^N 回绕），有符号溢出是未定义行为。利用方式通常是：让"长度 = 大数相乘"回绕成小值，绕过分配检查导致分配过小，随后按原始大长度写入，连锁触发越界写（CWE-787）。

## 关键细节

- 典型成因：`malloc(count * elem_size)` 中 `count` 来自不可信输入，乘法溢出。
- 示例代码：

```c
#include <stdint.h>
#include <stdlib.h>
int main(void) {
    uint32_t n = 0x10000, sz = 0x10000;
    size_t total = n * sz;       /* 0x100000000 回绕为 0 */
    char *p = malloc(total);     /* 实际分配 0 字节 */
    /* 后续按 n*sz 的逻辑写入 p → 堆越界写 */
    return 0;
}
```

- 编译并启用 UBSan：

```bash
gcc -fsanitize=undefined -g iov.c -o iov && ./iov
```

- 预期输出要点：`runtime error: signed integer overflow: 2147483647 + 1 cannot be represented in type 'int'`（有符号场景）；无符号回绕 UBSan 默认不报，需配合 `-fsanitize=unsigned-integer-overflow` 或人工审计。
- 安全写法：

```c
if (n > SIZE_MAX / sz) { /* 拒绝 */ }
size_t total = n * sz;
```

- 亦可使用 `__builtin_mul_overflow(a, b, &out)` 做带溢出检测的乘法；Rust 在 debug 构建下溢出即 panic，release 默认回绕。

## 常见坑

- 先乘法后检查：回绕已经发生，检查的是错误值。
- 隐式类型提升：`int` 与 `size_t` 混算，负值转成超大无符号数。
- 只防上限不防下限；把 `int` 负数直接当作长度。
- 32 位与 64 位下 `size_t` 宽度不同，同一表达式行为可能不同。

## 验证方式

- 用 UBSan 定位溢出表达式与行号；对无符号回绕用边界值（如 0xFFFFFFFF、0x10000×0x10000）做针对性测试。
- 代码审计聚焦所有"外部长度 × 单位大小"的分配与索引点，确认乘法是否发生在任何溢出检查之前。
