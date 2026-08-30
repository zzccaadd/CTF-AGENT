---
source_url: https://cwe.mitre.org/data/definitions/787.html
source_title: "CWE-787: Out-of-bounds Write"
source_version: "4.20"
publisher: MITRE
license: MITRE CWE terms
retrieved_at: 2026-08-31
topic: out-of-bounds-write
cwe_id: CWE-787
---
# CWE-787：越界写

## 核心概念

程序写入超出缓冲区合法边界的地址，覆盖相邻变量、返回地址、堆对象或堆分配器元数据。越界写是最直接的内存破坏原语：栈上可改写返回地址/保存的帧指针，堆上可改写相邻对象或 chunk 元数据，是代码执行类利用的主要起点。

## 关键细节

- 高危 API：`strcpy`/`strcat`/`gets`/`sprintf`/`memcpy`（长度参数错误）。
- 示例代码：

```c
#include <string.h>
int main(void) {
    char buf[16];
    strcpy(buf, "this string is way too long!!"); /* 栈越界写 */
    return 0;
}
```

- 编译并启用 ASan：

```bash
gcc -fsanitize=address -g oobw.c -o oobw && ./oobw
```

- 预期输出要点：`ERROR: AddressSanitizer: stack-buffer-overflow`，含 `WRITE of size 33` 与写入位置调用栈（方向为 WRITE，区别于 CWE-125 的 READ）。
- 加固编译：`gcc -O2 -fstack-protector-all -D_FORTIFY_SOURCE=2`，溢出触发时输出 `*** stack smashing detected ***: terminated`。
- 关联条目：CWE-120（缓冲区复制）、CWE-121（栈缓冲）、CWE-122（堆缓冲）、CWE-125（越界读）。

## 常见坑

- 函数传参后数组退化为指针，`sizeof(ptr)` 得到 8（64 位）而不是数组容量。
- `strncpy` 未写满时无 NUL 结尾；`snprintf` 截断后长度与内容不一致。
- 下标 off-by-one：`i == len` 时写 `arr[i]` 恰好越界一个元素。
- 长度来自不可信输入且未与目标容量比较（常与 CWE-190 整数溢出连锁）。

## 验证方式

- ASan 报错先确认 WRITE 方向与目标区域（stack / heap / global），再定位复制/写入点。
- 开启 FORTIFY 的二进制运行期 abort 可快速验证越界写被检测到。
- 代码审计检查每个写操作的"写入长度 ≤ 目标容量"不变式。
