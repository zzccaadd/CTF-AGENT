---
source_url: https://cwe.mitre.org/data/definitions/125.html
source_title: "CWE-125: Out-of-bounds Read"
source_version: "4.20"
publisher: MITRE
license: MITRE CWE terms
retrieved_at: 2026-08-31
topic: out-of-bounds-read
cwe_id: CWE-125
---
# CWE-125：越界读

## 核心概念

程序读取了超出缓冲区合法边界的地址，访问到相邻对象、未初始化内存或守卫页。相比越界写（CWE-787），越界读主要造成信息泄露（相邻堆对象、栈残留、堆元数据），严重时可泄露指针、口令等敏感数据；少数场景配合其他原语可演化为任意读。

## 关键细节

- 高危入口：数组下标、指针算术、`memcpy`/`strncpy`/`fread`/`recv` 等按长度读取的 API，以及 `strlen`/`strcpy` 这类依赖终止符的函数。
- 示例代码：

```c
#include <stdio.h>
#include <string.h>
int main(void) {
    char buf[8] = "abcdefg";
    int idx = 10;              /* 越界下标 */
    printf("%c\n", buf[idx]);  /* 读取 buf[10]，越界 */
    return 0;
}
```

- 编译并启用 AddressSanitizer：

```bash
gcc -fsanitize=address -g oobr.c -o oobr && ./oobr
```

- 预期输出要点：`ERROR: AddressSanitizer: stack-buffer-overflow`（或 heap/global-buffer-overflow），包含 `READ of size 1` 以及 `#0` 指向的越界行号。
- 替代验证：`valgrind --tool=memcheck ./oobr` 会报 `Invalid read of size 1`。

## 常见坑

- 循环边界 off-by-one：`for (i = 0; i <= n; i++)` 在最后一次迭代访问 `arr[n]` 越界。
- 有符号/无符号混算：空字符串时 `strlen(s) - 1` 无符号下溢成超大值，作为读取长度即越界。
- `strncpy` 不保证 NUL 结尾，随后 `strlen` 会越过缓冲区继续读。
- 直接信任报文/文件中的长度字段而不校验上限。

## 验证方式

- ASan 报错方向为 READ（区别于 CWE-787 的 WRITE），先确认越界方向再定位成因。
- 用调试器（gdb）在报错行观察越界索引与缓冲区容量的差值，判断是 off-by-one 还是完全越界。
- 静态检查 `-D_FORTIFY_SOURCE=2` 开启情况，并审计所有"长度来源"是否经过边界校验。
