---
source_url: knowledge/reference/reverse/packers-unpacking.md
source_title: Packer identification and unpacking — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: reverse
keywords_en: packer, unpacking, UPX, 加壳
tool_name: upx
---

# 加壳与脱壳：从识别到内存转储（通用模式）

> 从多份已审核 writeup 提炼的通用解法模式，不含具体题目内容。

## 核心概念

加壳（packing）把原始代码与数据压缩或加密，额外包一层"壳代码"，运行时由壳在内存中逐段还原原始指令，再跳到真正的程序入口（OEP，Original Entry Point）。CTF 常见两类：

- **压缩壳**：如 UPX，只做压缩 + 解压，`upx -d` 常可直接还原。
- **加密/自解密壳**：壳代码先解密代码段，还原后的逻辑只存在于运行态，必须动态脱壳（内存转储）。

目标只有一个：拿到运行态中还原后的原始代码，再做静态分析。

## 关键细节

### 1. 识别是否加壳

```console
$ file challenge
challenge: ELF 32-bit LSB executable, ... , UPX packed
$ strings challenge | grep -iE "upx|packed|protect"
$ readelf -S challenge        # 壳常见特征段：UPX0/UPX1；.text 权限异常（WX）
$ readelf -h challenge        # 入口地址若落在壳段而非 .text，基本确认加壳
```

### 2. UPX 直接脱壳

```console
$ upx -d challenge                 # 就地还原
$ upx -d -o unpacked challenge     # 还原到新文件，保留原件做对比
```

脱壳失败（报错、magic 被改）时走手动流程：壳的末尾通常是一条跳转到 OEP 的指令，跟踪到那里即可。

### 3. 动态脱壳（自解密壳）与内存转储

用 gdb 运行程序，在 OEP 处暂停后把还原区导出：

```text
(gdb) set disable-randomization on   # 先关 ASLR，保证地址可复现
(gdb) start
(gdb) info proc mappings             # 查看各段地址范围
(gdb) si                             # 反复单步，盯第一条跳出当前段的跳转
(gdb) dump memory unpacked.bin 0x08048000 0x0804a000
```

- 找 OEP 的实用信号：单步到 `jmp <段外地址>` 或 `push <地址>; ret` 组合指令，目标就是 OEP。
- 导出的内存映像通常不能直接当 ELF 分析：先 `file unpacked.bin`，必要时手工补 section 头，或用 `r2 -m 0x08048000 unpacked.bin` 按加载地址载入分析。

### 4. 工具清单

`file` / `strings` / `readelf`（识别）；`upx`（压缩壳还原）；`gdb` `dump memory`（加密壳转储）；`rabin2 -I` / `r2 -d`（导入与分析）；`pyghidra`/Ghidra（转储后的静态反编译）。

## 常见坑

- **不关 ASLR 就 dump**：两次运行地址不同，导出内容不可复现。先 `set disable-randomization on`。
- **dump 范围不对**：只导 `.text` 漏了数据段，字符串/常量缺失。先 `info proc mappings` 再按段导出。
- **`upx -d` 报错不代表不是 UPX**：很多样本改动 UPX magic/版本号，应手动找 OEP，不要硬试。
- **转储文件 `file` 显示 "data"**：正常，内存映像缺 ELF 头，按加载地址分析或修复头部。
- **壳代码自带反调试**：先按 anti-debug 卡片处理 `ptrace`/时间差检测，否则单步会失败。

## 验证方式

- 脱壳后 `strings unpacked` 能搜到原本看不见的明文字符串。
- OEP（或转储的跳转目标）落在标准函数序言（`push ebp; mov ebp, esp`）或 CRT 入口风格，而不是壳代码。
- 用转储结果做静态分析能还原关键逻辑，且与程序实际运行行为一致。
