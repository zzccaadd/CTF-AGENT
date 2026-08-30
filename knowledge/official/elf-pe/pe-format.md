---
source_url: https://learn.microsoft.com/en-us/windows/win32/debug/pe-format
source_title: PE Format（Microsoft Windows 可移植可执行文件格式规范）
source_version: 官方文档当前版本
publisher: Microsoft
license: Microsoft Learn 文档许可（CC BY 4.0）
retrieved_at: 2026-08-31
topic: pe-format
tool_name: pefile, llvm-objdump, dumpbin
---

# PE 文件结构技术卡片：DOS 头 / 节区 / 导入表

## 核心概念

- DOS 头 `IMAGE_DOS_HEADER`（64 字节）：`e_magic = 0x5A4D`（即 "MZ"），`e_lfanew` 指向 NT 头在文件中的偏移（常见 0x40 或 0x80）。
- NT 头 = 4 字节签名 "PE\0\0" + `IMAGE_FILE_HEADER` + `IMAGE_OPTIONAL_HEADER`；Optional Header 的 `Magic` 为 0x10B 表示 PE32（32 位），0x20B 表示 PE32+（64 位）。
- 节表：每个 `IMAGE_SECTION_HEADER`（40 字节）含 Name(8)、VirtualSize、VirtualAddress、SizeOfRawData、PointerToRawData、Characteristics。
- 导入表：`IMAGE_IMPORT_DESCRIPTOR` 数组，关键字段 `OriginalFirstThunk`（INT）、`Name`（DLL 名 RVA）、`FirstThunk`（IAT）；运行时加载器把 IAT 槽位改写为函数真实地址。

## 关键细节

- RVA 与文件偏移换算：先确定 RVA 落在哪个节的 `[VirtualAddress, VirtualAddress+VirtualSize)` 区间，再 `FileOffset = RVA - VirtualAddress + PointerToRawData`。
- DataDirectory 共 16 项：第 0 项导出表、第 1 项导入表；`AddressOfEntryPoint` 是 RVA，不是文件偏移。
- Machine 字段：0x14C 为 i386、0x8664 为 x64；Characteristics 置位 0x2000 表示 DLL。
- pefile 示例：

  ```python
  import pefile
  pe = pefile.PE('sample.exe')
  print(hex(pe.OPTIONAL_HEADER.AddressOfEntryPoint))
  for entry in pe.DIRECTORY_ENTRY_IMPORT:
      names = [i.name.decode() for i in entry.imports if i.name]
      print(entry.dll.decode(), names)
  ```

  预期输出形如：`KERNEL32.dll ['LoadLibraryA', 'GetProcAddress', ...]`。

- 命令行替代：`dumpbin /headers /imports x.exe`、`llvm-objdump -x -d x.exe`、`file x.exe`。

## 常见坑

- RVA 不等于文件偏移，把入口地址直接当文件偏移读取会解析到错误字节。
- `VirtualSize` 常大于 `SizeOfRawData`（含 BSS 类未初始化数据），节尾有填充，两节之间可能有缝隙，换算偏移时按节区间匹配。
- PE32 与 PE32+ 的 Optional Header 布局不同（DataDirectory 起始偏移分别为 0x78 与 0x88），自写解析器要注意位数。
- 静态文件中 IAT 存的是导入名 RVA 或序号（高位 `IMAGE_ORDINAL_FLAG` 0x80000000 表示按序号导入），真实函数地址是运行时才写入的。

## 验证方式

- `file x.exe` 确认位数与子系统；pefile 脚本打印节表、入口 RVA、导入表；把入口 RVA 按节表换算为文件偏移，用 `llvm-objdump -d` 对照该偏移处指令与程序入口是否一致。
