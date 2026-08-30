---
source_url: https://cwe.mitre.org/data/definitions/476.html
source_title: "CWE-476: NULL Pointer Dereference"
source_version: "4.20"
publisher: MITRE
license: MITRE CWE terms
retrieved_at: 2026-08-31
topic: null-pointer-dereference
cwe_id: CWE-476
---
# CWE-476：空指针解引用

## 核心概念

对值为 NULL（地址 0 附近）的指针进行解引用。多数情况下导致进程崩溃（SIGSEGV）形成拒绝服务；在内核态或某些错误处理路径中，空指针附近的可映射页可能被读取，造成有限的信息泄露。

## 关键细节

- 成因：分配/获取资源的函数失败后未检查返回值；逻辑分支遗漏空指针；检查与使用之间存在竞态。
- 示例代码：

```c
#include <string.h>
int main(void) {
    char *p = NULL;
    strcpy(p, "boom");   /* 空指针写入 → SIGSEGV */
    return 0;
}
```

- 运行预期：`Segmentation fault (core dumped)`；Linux 下 `dmesg` 可见 `BUG: kernel NULL pointer dereference` 或用户态 `segfault at 0000000000000000`。
- gdb 定位：

```bash
gdb -batch -ex run -ex bt ./prog
```

- 调试注意：`-fno-delete-null-pointer-checks` 可防止编译器优化掉显式的空指针检查（默认优化可能把 `if (!p)` 删除）。
- 平台差异：当 `mmap_min_addr` 被设为 0（部分旧内核/嵌入式配置）时，地址 0 附近可被映射，空指针解引用可能变成受控读写而非单纯崩溃；现代系统默认该值非零以缓解此类利用。

## 常见坑

- 假定 `malloc`/`calloc` 必然成功——内存耗尽时返回 NULL。
- TOCTOU：先判空、后使用，两处之间对象被并发修改为 NULL。
- 只检查外层对象，未检查其内部成员指针。
- 把"崩在空指针上"当成普通崩溃忽略，可能掩盖上游未检查返回值的问题。

## 验证方式

- 看信号：SIGSEGV（11）；gdb `bt` 给出解引用行号。
- 用 ASan 编译可得到更明确的 `SEGV on unknown address` 报告并附调用栈。
- 审计所有资源获取调用的返回值处理（对应 CWE-690 未检查返回值）。
