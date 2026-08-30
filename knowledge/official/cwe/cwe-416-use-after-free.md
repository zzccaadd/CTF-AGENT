---
source_url: https://cwe.mitre.org/data/definitions/416.html
source_title: "CWE-416: Use After Free"
source_version: "4.20"
publisher: MITRE
license: MITRE CWE terms
retrieved_at: 2026-08-31
topic: use-after-free
cwe_id: CWE-416
---
# CWE-416：释放后使用

## 核心概念

指针指向的内存被 free 后仍被程序引用。读取已释放内存可能泄露堆中的残留数据，写入已释放内存可能破坏堆分配器元数据或被重新分配对象的内容，是堆利用的重要原语。与 CWE-415（双重释放）成因不同：UAF 是"释放后又用"，double free 是"同一内存释放两次"。

## 关键细节

- 成因：free 后未置空指针、对象生命周期管理混乱、C++ 容器/迭代器/共享指针引用计数错误、并发下释放与使用的竞态。
- 示例代码：

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(void) {
    char *p = malloc(32);
    strcpy(p, "hello");
    free(p);        /* 释放 */
    puts(p);        /* 使用已释放指针 → UAF */
    return 0;
}
```

- 编译并启用 ASan：

```bash
gcc -fsanitize=address -g uaf.c -o uaf && ./uaf
```

- 预期输出要点：`ERROR: AddressSanitizer: heap-use-after-free`，报告同时给出 `READ of size ... at`（使用点）、`freed by thread`（释放点）与 `previously allocated by`（分配点）三段调用栈。
- 工程防御：free 后置 NULL；明确所有权；RAII/智能指针；进程隔离降低利用稳定性。

## 常见坑

- `p = NULL` 只解决"同一个指针"再被使用，代码中残留的其他别名指针仍会 UAF。
- 释放对象与使用对象之间隔着函数调用/回调，调用栈不直观。
- 多线程场景下检查与释放之间存在窗口（TOCTOU）。
- 与 double free 混用：先 UAF 后 double free 形成更复杂的堆状态。

## 验证方式

- ASan 的三段调用栈（alloc / free / use）是定位 UAF 的最快路径；valgrind 会报 `Invalid read/write ... after free`。
- 用 gdb 在 use 点观察指针指向的堆块是否已被回收/复用（如相邻 chunk 元数据变化）。
- 静态工具（clang `--analyze`、CodeQL UAF 查询）辅助发现跨函数 UAF。
