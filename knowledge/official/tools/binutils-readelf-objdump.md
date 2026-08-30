---
source_url: https://sourceware.org/binutils/docs/
source_title: GNU Binutils documentation
source_version: current
publisher: Free Software Foundation / Binutils project
license: GFDL
retrieved_at: 2026-08-31
topic: binary-analysis
tool_name: readelf
---
# readelf / objdump / strings 关键用法

## 核心概念

三件套覆盖 ELF 静态分析的三个层次：`readelf` 读节表、符号表、重定位等结构化元数据；`objdump` 做反汇编与段内容 dump；`strings` 快速抽可打印字符串。CTF 中先 `file` 判类型、`checksec` 类信息由 `readelf -h/-l` 补全、动态链接依赖看 `-d`，反汇编首选 `objdump -M intel`。

## 关键细节

### readelf

```bash
readelf -h ./bin           # ELF 头：类型、机器、入口点 Entry point 0x...
readelf -S ./bin           # 节表：.text/.plt/.got/.bss 地址与大小
readelf -s ./bin           # 符号表：函数名与地址（strip 后消失）
readelf -r ./bin           # 重定位表：GOT 项对应符号
readelf -d ./bin           # 动态段：NEEDED 依赖库、BIND_NOW 等
readelf -l ./bin           # 程序头：段权限（判断 NX：GNU_STACK 是否 RW）
```

预期输出样例（`-h`）：`ELF Header: Magic: 7f 45 4c 46 02 01 01 00 ...  Class: ELF64 ... Entry point address: 0x401000`。判断保护：`-l` 里 `GNU_STACK` 无 E 即 NX；`-d` 有 `BIND_NOW` 或 `FLAGS` 含 `NOW` 即 Full RELRO；`-s` 有 `__gmon_start__` 等符号说明未 strip。

### objdump

```bash
objdump -d ./bin                    # 反汇编 .text（AT&T 语法）
objdump -d -M intel ./bin           # Intel 语法，CTF 首选
objdump -d -M intel --start-address=0x4011a0 --stop-address=0x4011f0 ./bin
objdump -t ./bin                    # 符号表（同 readelf -s）
objdump -R ./bin                    # 动态重定位（.got 条目）
objdump -s -j .rodata ./bin         # hexdump 指定节
objdump -h ./bin                    # 节头表
```

`objdump -d -M intel` 输出格式为 `地址 <函数名+偏移>: 机器码  助记符`；配合 `--start/--stop-address` 精确看某函数。注意 `-M intel` 与架构参数不冲突，交叉架构用 `-b elf64-x86-64 -m i386:x86-64` 之类（少用，r2/ghidra 更省事）。

### strings

```bash
strings ./bin                    # 默认打印 ≥4 个可打印字符序列
strings -n 8 ./bin               # 只打长度 ≥8
strings -t x ./bin               # 每行前缀文件偏移（十六进制）
strings -t d ./bin               # 十进制偏移
strings -e l ./bin               # UTF-16LE 编码字符串（宽字符/Unicode 常见）
strings -a ./bin                 # 扫描整个文件（含数据段）
```

`-e l` 处理宽字符串程序；`-t x` 拿偏移后配合 `dd skip=... count=...` 或十六进制编辑器定位。静态链接大文件用 `strings -n 8 | grep -i` 过滤噪声。

## 常见坑

- strip 后 `readelf -s`/`objdump -t` 符号表为空，改看 `.dynsym`（`readelf -s` 默认含 dynsym 的动态符号仍在）或直接看反汇编入口。
- `objdump -d` 默认 AT&T 语法，`lea rax, [rip+...]` 与 Intel 顺序相反，判读前先确认 `-M intel`。
- `strings` 默认跳过不可读段；被加密或压缩的载荷要 `-a` 或先解包再跑。
- 判断 NX/RELRO 别只信 `checksec`，以 `readelf -l/-d` 原始输出为准（工具版本差异）。

## 验证方式

对任意 ELF 依次运行 `readelf -h`（应见 `ELF Header` 与 `Entry point`）、`objdump -d -M intel`（应见 `<main>:` 与 Intel 助记符）、`strings -n 8`（应输出可读字符串），三者输出可互相印证地址与函数名。
