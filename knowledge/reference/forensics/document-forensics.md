---
source_url: knowledge/reference/forensics/document-forensics.md
source_title: Office/PDF document forensics — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: forensics
tool_name: olevba
---

# 文档取证（通用模式）

> 从多份已审核 writeup 提炼的通用解法模式，不含任何具体题目的 flag、附件路径或 payload 字节。

## 核心概念

文档类题目有三个藏点：**元数据**（作者/公司/时间/打印信息）、**隐藏内容**（注释、修订、隐藏文字、白字、PDF 内嵌文件）、**宏代码**（VBA，可能附带解码/下载逻辑）。先确定容器格式再选工具：docx/xlsx/pptx 是 OOXML 打包（本质 zip），doc/xls 是 OLE2 复合文档，PDF 是对象+流结构。

## 关键细节

1. **docx 元数据与隐藏内容**：
   - `unzip -l doc.docx` 列出包内文件；`unzip -p doc.docx docProps/core.xml` 看作者/公司/时间。
   - `word/document.xml` 中找 `w:vanish`（隐藏文字属性）与 `w:color w:val="FFFFFF"`（白字）；注释在 `word/comments.xml`，修订记录含作者与改前/改后内容。
   - 直接查 XML：`unzip -p doc.docx word/document.xml | grep -o '<w:t[^>]*>[^<]*</w:t>'`。
2. **宏分析**（.docm/.xlsm/.pptm）：
   - `olevba -c doc.docm` 提取 VBA 源码；`olevba --reveal` 还原 `Chr()`/`Asc()` 拼接的混淆字符串。
   - 宏被密码保护时源码只存编译后 p-code：`pcodedmp file.docm` 反编译。
   - 也可 `unzip -p doc.docm word/vbaProject.bin > v.bin` 后对二进制做 `strings` 粗扫。
3. **PDF**：
   - `pdfinfo f.pdf` 看元数据；`pdfdetach -saveall f.pdf` 导出内嵌附件；`pdftotext -layout f.pdf` 抽文本（含隐藏/不可见文本层）。
   - 展开对象流：`qpdf --qdf --object-streams=disable f.pdf out.qdf`，再在 out.qdf 里找注释（`/Annots`）、额外流与可疑内容。
   - `mutool extract f.pdf` 抽出全部内嵌资源与附件。
4. **老式 .doc（OLE2）**：`oleid` 判断类型，`olemeta` 读元数据，`strings`/`oletimes` 辅助。

## 常见坑

- 对 docx 整体 `strings`/grep 基本无效：先 `unzip` 拆包再逐文件分析。
- PDF 文本在 FlateDecode 压缩流里，直接 `strings` 看不到：必须 `pdftotext` 或 qpdf 展开。
- 宏只存在于启用宏的容器（.docm/.xlsm/.pptm 的 `vbaProject.bin`）；普通 .docx 里通常没有可执行宏。
- VBA 混淆串静态看是乱码：先 `olevba --reveal`，仍不行再考虑本地复刻解码逻辑运行。
- 隐藏文字在 XML 里始终存在（只是渲染不可见），不要因为界面上看不到就跳过 XML 检查。

## 验证方式

- 元数据/隐藏文本以 `unzip -p` 原始 XML 为准，与渲染视图对照确认"不可见但存在"。
- 宏逻辑用本地 Python 复刻一遍，确认解码/还原结果与文档内其他线索自洽。
- PDF 附件导出后逐一 `file` + 解压/打开验证，`qpdf --check` 确认文档未被破坏。
