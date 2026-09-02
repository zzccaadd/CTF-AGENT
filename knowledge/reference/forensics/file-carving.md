---
source_url: knowledge/reference/forensics/file-carving.md
source_title: file carving — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: forensics
keywords_en: file carving, forensics, binwalk, 文件雕刻
tool_name: binwalk
---

# 文件雕刻（通用模式）

> 从多份已审核 writeup 提炼的通用解法模式，不含任何具体题目的附件路径或内容。

## 核心概念

雕刻（carving）不依赖文件系统元数据，而是按**文件签名（magic bytes）**从磁盘镜像或拼接文件里恢复/切出数据。典型场景：删除的文件、隐藏分区、PNG 之后追加的 ZIP、可执行文件里内嵌的其他文件。

## 关键细节

1. **常见魔数**：
   - PNG：`\x89PNG\r\n\x1a\n`，结束于 IEND chunk（`IEND` + CRC 后即止）。
   - JPEG：`\xff\xd8\xff` … `\xff\xd9`。
   - ZIP：`PK\x03\x04`（本地头）… `PK\x05\x06`（EOCD）；RAR：`Rar!\x1a\x07`。
   - PDF：`%PDF-` … `%%EOF`；GIF：`GIF87a`/`GIF89a`；ELF：`\x7fELF`。
2. **工具链**：
   - `binwalk img`：列出偏移处的签名；`binwalk -e img` 按签名自动抽取；`binwalk --dd='png:png'` 自定义抽取类型。
   - `foremost -i img -o out/ -t png,jpg,zip`：按类型批量雕刻。
   - `scalpel`：编辑 `/etc/scalpel/scalpel.conf` 增删签名规则后执行。
   - `photorec`：按文件内容恢复大量删除文件。
3. **手动切取**（自动工具失败时）：

```bash
# 先定位魔数偏移（16 进制输出，grep 出偏移列）
grep -abo $'\x89PNG\r\n\x1a\n' img.bin
# 从偏移 0x1234 起切 4096 字节
dd if=img.bin of=out.png bs=1 skip=$((0x1234)) count=4096
```

   长度不确定时：PNG 顺 IEND 结束；ZIP 用 EOCD 里的中央目录偏移计算；JPEG 找 `\xff\xd9`，**其后追加的数据（常见是另一个文件）要单独再雕**。
4. **先探明文**：`strings -n 8 img` 先看有没有残留的可读内容，再决定是否雕刻。

## 常见坑

- 起点偏移错 1-2 字节会导致 `file` 识别失败：确认魔数完整（PNG 是 8 字节）。
- 一个镜像里有多个同类文件：`binwalk` 只报首个偏移，`foremost -t` 全量恢复后逐个检查。
- JPEG 内嵌 JPEG：第一个 `\xff\xd9` 未必是外层的结尾，内嵌图会提前出现；从每个 `\xff\xd8` 都试一次切取。
- 删过的文件块可能被部分覆盖：先验证 `file` 与可打开性，覆盖严重的考虑 slack space / strings。
- 尾部多余数据别漏：PNG 后追加 ZIP、ZIP 后追加图片都很常见，`binwalk` 默认能看到但需手动确认切点。

## 验证方式

- 每个产物先 `file` 确认类型，再按类型验证完整性：`unzip -t`、`qpdf --check`、图片打开、`xxd` 核对首尾魔数。
- 若已知原始文件哈希（题目附带校验和），`sha256sum` 比对作为最严格判据。
