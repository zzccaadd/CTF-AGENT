---
source_url: knowledge/reference/forensics/zip-archive-tricks.md
source_title: ZIP archive tricks — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: forensics
keywords_en: zip, archive, zip slip, 压缩包
tool_name: python
---

# ZIP 档案技巧（通用模式）

> 从多份已审核 writeup 提炼的通用解法模式，不含任何具体题目的 flag、附件路径或 payload 字节。

## 核心概念

ZIP 相关题目集中在三类手法：**伪加密**（文件头声明加密、数据实际未加密）、**CRC32 爆破**（stored 条目内容极短时按校验和反推原文）、**zip-slip**（解压路径穿越写出目录外）。它们的共同前提是先弄懂 ZIP 布局：每个条目有 local file header（`PK\x03\x04`，偏移 6 处 2 字节 general purpose flag），末尾有 central directory（`PK\x01\x02`）。

## 关键细节

1. **伪加密**：GP flag 的 bit 0（值 0x01）置位表示加密。若只是置位而没有真实 ZipCrypto 加密头，数据并未加密——快速判断：7-Zip 用任意密码也能解开。修复：清除 local header（必要时连同 central directory）的 bit 0：

```python
import struct
data = bytearray(open("x.zip", "rb").read())
i = 0
while data[i:i+4] == b"PK\x03\x04":
    data[i+6] &= ~0x01          # 清加密位，注意保留 bit 3（数据描述符）
    n = struct.unpack("<H", data[i+26:i+28])[0]   # 文件名长
    m = struct.unpack("<H", data[i+28:i+30])[0]   # 扩展字段长
    i += 30 + n + m
open("fixed.zip", "wb").write(data)
```

   改的是元数据标志位，不动数据本身，因此 CRC 校验不受影响。改完用 `unzip -P '' fixed.zip` 应直接解出。

2. **CRC32 爆破**：条目用 stored（method 0，不压缩）且内容只有 3-5 字节时，已知 CRC 可穷举原文：

```python
import zipfile, binascii
z = zipfile.ZipFile("x.zip")
info = z.infolist()[0]                      # 先确认 info.compress_type == 0
target = info.CRC
size = info.file_size                       # 以条目大小为穷举长度
for v in range(256 ** size):
    b = v.to_bytes(size, "big")
    if binascii.crc32(b) & 0xFFFFFFFF == target:
        print(b); break
```

   长度取 central directory 的 `file_size`；超过 4 字节穷举量过大，改走已知明文攻击。
3. **ZipCrypto 已知明文攻击**：掌握 ≥12 字节连续明文（如已知文件头）时，用 `bkcrack` 恢复 ZipCrypto 内部密钥：`bkcrack -C x.zip -c 密文条目名 -p 明文文件`，再 `-k` 密钥直接解密全部条目，无需密码。
4. **zip-slip**：条目名可含 `../` 或绝对路径，未防护的解压会把文件写到目标目录外。检查：`unzip -l x.zip` 看条目名是否含 `..`。安全解压：用 Python `zipfile` 逐条 `os.path.realpath` 校验落在目标目录内再写；新版 `unzip` 对 `../` 会告警拒绝，但 7-Zip 旧版与 `zipfile.extractall` 默认不防护。若题目提供一个"解压用户上传 zip"的服务，zip-slip 本身就是可利用点（写出覆盖可读文件）。

## 常见坑

- 只清 local header 不够：部分工具读 central directory 的 flag，两处都清。
- 别试图改数据字节"绕过加密"——那样 CRC 必挂；伪加密只动标志位。
- CRC 爆破仅对极短 stored 内容可行；内容稍长或压缩过的条目改用 bkcrack/找密码（`zip2john` + john、`fcrackzip`）。
- 解压工具差异：新版 unzip 拒收 `../` 条目不等于系统安全，其他解压器仍可能写出。

## 验证方式

- `zipinfo -v x.zip` 看 flag 值确认加密位；修复后用 `unzip -P ''` 免密解出全部条目。
- 爆破结果以「CRC 匹配 + 结果可读/命中已知格式」双重确认，避免撞到 CRC 碰撞。
- zip-slip 验证：先 `unzip -l` 列名，再在隔离目录里实际解压并检查文件是否越界。
