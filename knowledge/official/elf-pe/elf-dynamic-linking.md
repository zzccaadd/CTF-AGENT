---
source_url: https://refspecs.linuxfoundation.org/elf/gabi4+/ch4.reloc.html
source_title: ELF gABI 第 4 章 Relocations（System V ABI 官方规范）
source_version: gABI 4.1（含 ELF64 补充说明）
publisher: Linux Foundation（原 Tool Interface Standards）
license: 公开规范文档（Linux Foundation 版权，可自由阅读引用）
retrieved_at: 2026-08-31
topic: elf-dynamic-linking
tool_name: readelf, objdump, patchelf
---

# ELF 动态链接与重定位技术卡片：GOT/PLT

## 核心概念

- 重定位（relocation）表记录装载期需要修正的位置：`.rela.dyn`（数据与函数地址修正）与 `.rela.plt`（lazy binding 用）。动态链接器 `ld.so` 在装载时按这些条目改写 GOT。
- GOT（全局偏移表）存放函数与变量的最终地址；PLT（过程链接表）是跳板代码，首次调用某函数时经 `_dl_runtime_resolve` 解析真实地址并回填 GOT，后续调用直接命中。
- 目标文件类型影响装载基址：ET_EXEC 固定基址（x86-64 通常 0x400000），ET_DYN（PIE）基址随机，重定位计算使用装载基址 B。

## 关键细节

- 64 位重定位项 `Elf64_Rela` 共 24 字节：`r_offset`(8) + `r_info`(8) + `r_addend`(8)；`r_info = (符号表索引 << 32) | 类型`。32 位下 `Elf32_Rel` 为 8 字节、`Elf32_Rela` 为 12 字节（REL 无 r_addend，修正值直接写入目标位置）。
- 常用 x86-64 类型：`R_X86_64_RELATIVE`(8) = B+A，用于 `.data` 中含指针的数据；`R_X86_64_GLOB_DAT`(6) = S，全局变量地址；`R_X86_64_JUMP_SLOT`(7) = S，函数地址；`R_X86_64_64`(1) = S+A，绝对地址。
- RELRO：部分 RELRO 下 `.got` 只读、`.got.plt` 可写；full RELRO（编译加 `-z now`）下 `.got.plt` 也只读，lazy binding 关闭，DT_FLAGS 含 `BIND_NOW`。
- 查看命令：`readelf -r bin` 列重定位；`readelf -d bin | grep -i bind_now` 判断是否 full RELRO；`readelf -s bin` 看符号；`objdump -d -j .plt bin` 看 PLT 桩。`readelf -r` 输出形如：

  ```
  Relocation section '.rela.plt' at offset 0x3d8 contains 2 entries:
    Offset          Info           Type           Sym. Value    Sym. Name
  000000003f18  000200000007 R_X86_64_JUMP_SLOT 000000000000  puts@GLIBC_2.2.5
  ```

## 常见坑

- 32 位与 64 位重定位结构体大小不同，手写解析器不要混用字段偏移。
- PIE 程序静态文件中的地址是相对偏移（RVA），调试时需加上装载基址才能对应实际内存。
- full RELRO 时 GOT 只读，函数地址启动时已全部解析，不存在"首次调用才填充"的时间窗口。
- 静态链接程序没有 GOT/PLT，不要对静态二进制套用动态链接分析思路。

## 验证方式

- `readelf -r ./bin | head` 查看重定位条目与类型；`readelf -d ./bin | grep -E 'BIND_NOW|FLAGS'` 判断 RELRO 级别；gdb 中 `start` 后用 `x/gx &puts@got`，观察该 GOT 槽位在调用前后从解析桩地址变为 libc 真实地址。
