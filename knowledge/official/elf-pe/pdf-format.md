---
source_url: https://opensource.adobe.com/dc-acrobat-sdk-docs/pdfstandards/PDF32000_2008.pdf
source_title: PDF 32000-1:2008 Document management — Portable document format（ISO 32000-1）
source_version: PDF 1.7 / ISO 32000-1:2008
publisher: Adobe Systems（作为 ISO 32000-1:2008 发布）
license: Adobe 版权，公开可读
retrieved_at: 2026-08-31
topic: pdf-format
tool_name: qpdf, mutool, pdfinfo
---

# PDF 结构技术卡片：对象 / 交叉引用表 / 流

## 核心概念

- PDF = 文件头（`%PDF-1.x`）+ 对象体 + 交叉引用表（xref）+ 尾部（trailer + `startxref`）。间接对象形如 `N G obj ... endobj`，其他地方用 `N G R` 引用。
- xref 记录每个对象的字节偏移，trailer 的 `/Root` 指向目录对象、`/Size` 为对象总数；`startxref` 给出 xref 在文件中的偏移。
- 流对象：字典中声明 `/Length` 与可选的 `/Filter`（如 `/FlateDecode`），正文夹在 `stream` 与 `endstream` 之间，用于存页面内容、字体、图像等。

## 关键细节

- 常用字典：`/Catalog`（含 `/Pages`）、`/Pages`（含 `/Kids` `/Count`）、`/Page`（含 `/Contents` `/MediaBox` `/Font`）、`/Annots`（注释）、`/OpenAction`（打开时动作）。
- 对象语法：字典 `<< /Key Value >>`、数组 `[a b]`、名字 `/Name`、文本串 `(…)`（`\n` `\t` `\ddd` 转义）、十六进制串 `<4142>`。
- 增量更新：文件可追加新的 xref 段与 trailer，旧对象仍然有效；分析最新状态时以文件末尾的 trailer 为准。
- PDF 1.5+ 的交叉引用流（对象流，`/Type /XRef`）把对象压缩进流，普通按字节偏移扫描的解析器看不到正文对象。
- 常用命令：`qpdf --check f.pdf` 检查完整性；`qpdf --qdf --object-streams=disable f.pdf out.pdf` 展开对象流；`mutool show f.pdf xref`；`pdfinfo f.pdf`；`strings -n 8 f.pdf` 快速搜索明文文本。
- 读取 xref 偏移的示例（python）：

  ```python
  data = open('f.pdf','rb').read()
  off = int(data[data.rfind(b'startxref')+9:].split()[0])
  print(data[off:off+80].decode('latin1'))
  # 预期形如：'xref\n0000000000 65535 f\n0000000015 00000 n\n...'
  ```

## 常见坑

- xref 中的字节偏移是相对文件首的绝对偏移；手工增删对象后必须同步更新 xref，否则解析器找不到对象。
- 对象流压缩后 `grep -a "obj"` 找不到正文对象，先禁用对象流再分析。
- 损坏的 xref 可用 `qpdf --repair` 或 `mutool clean` 重建（工具会扫描全文件重新索引）。
- `/OpenAction` 或 `/AA` 中的 JavaScript 是常见恶意入口，审阅 PDF 时优先检查。
- 多次增量更新产生多个 xref 段与 trailer，分析"最新改动"要读文件末尾的 trailer，而不是开头第一段。

## 验证方式

- `qpdf --check f.pdf` 输出 xref 与对象完整性；`qpdf --qdf --object-streams=disable` 展开后用 `grep -a` 检索 `/OpenAction` 或目标字典；`mutool show f.pdf N` 按对象号查看内容。
