---
source_url: https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT
source_title: APPNOTE.TXT — .ZIP File Format Specification
source_version: 6.3.x
publisher: PKWARE
license: PKWARE ZIP 规范许可（可复制分发，需保留版权声明）
retrieved_at: 2026-08-31
topic: zip-format
tool_name: zipinfo, binwalk, python zipfile
---

# ZIP 格式技术卡片：Local Header / Central Directory / EOCD

## 核心概念

- ZIP 由"本地文件头 + 文件数据"序列、中央目录（Central Directory）和末尾 EOCD（End of Central Directory）三部分组成。
- 解压流程：先读文件末尾的 EOCD（签名 `50 4B 05 06`）拿到中央目录偏移与条目数，再按中央目录记录的"本地头相对偏移"定位每个条目并读取数据。

## 关键细节

- 本地文件头（签名 `50 4B 03 04`）关键字段：通用标志(2B)、压缩方式(2B)、CRC32(4B)、压缩大小(4B)、未压缩大小(4B)、文件名长度(2B)、额外字段长度(2B)、文件名。
- 通用标志位：bit0 = 加密，bit3 = 文件数据后跟 Data Descriptor（此时本地头中的大小/CRC 为 0）；压缩方式：0 = 存储（不压缩）、8 = deflate。
- 中央目录头（签名 `50 4B 01 02`）在本地头字段基础上增加"本地头相对偏移"(4B)，文件名后可带注释。
- EOCD（`50 4B 05 06`）：磁盘号、中央目录条目数、中央目录大小、中央目录偏移、注释长度（最长 65535 字节）；ZIP64 扩展使用 EOCD64（`50 4B 06 06`）与定位器（`50 4B 06 07`），条目 extra 字段 id 0x0001。
- 常用命令：`unzip -l a.zip` 列条目；`zipinfo -v a.zip` 显示 flags/压缩方式/大小/偏移；`binwalk a.zip` 识别文件中的嵌入 ZIP；python：`zipfile.ZipFile('a.zip').infolist()` 查看 `flag_bits`、`compress_type`、`header_offset`。

## 常见坑

- 伪加密：条目通用标志 bit0 被置位但数据实际未加密，常规解压会提示输密码；修复方法是把该条目在本地头与中央目录两处的 flags bit0 同时清零（按结构定位改写或用脚本处理），之后可直接解出。
- 加密 ZIP 的本地头与中央目录 flags 不一致时各解压器行为不同，先 `zipinfo -v` 核对。
- 使用 Data Descriptor（bit3）的条目，本地头里大小/CRC 为 0，真实值在数据之后，手动处理流时要按描述符结构读取。
- EOCD 可能被附加数据（自解压壳、注释）推离文件末，搜索 `50 4B 05 06` 应从文件末尾向前扫。

## 验证方式

- `zipinfo -v a.zip` 核对 flags、压缩方式与偏移；python 遍历 `infolist()` 打印 `header_offset` 并 seek 到该偏移验证本地头签名；修复伪加密 flags 后执行 `unzip a.zip` 能直接解出内容。
