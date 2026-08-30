---
source_url: http://www.libpng.org/pub/png/spec/1.2/PNG-Contents.html
source_title: "PNG (Portable Network Graphics) Specification Version 1.2 — Chapter 4: Structure of a PNG file"
source_version: 1.2
publisher: PNG Working Group / libpng.org
license: PNG 规范许可（可自由分发，需保留版权声明）
retrieved_at: 2026-08-31
topic: png-format
tool_name: pngcheck, python zlib, xxd
---

# PNG 文件结构技术卡片：chunk / IHDR / IDAT

## 核心概念

- 8 字节签名：`89 50 4E 47 0D 0A 1A 0A`（即 "PNG\r\n\x1a\n"），任何合法 PNG 都以它开头。
- chunk 通用结构：`Length`(4, 大端) + `Type`(4, ASCII) + `Data`(Length 字节) + `CRC32`(4, 覆盖 Type+Data，不含 Length)。
- 关键块：`IHDR`（必须为第一块）、`PLTE`（调色板）、`IDAT`（图像数据，至少一个）、`IEND`（结束）；辅助块如 `tEXt`、`gAMA`、`pHYs`、`tIME` 可选。

## 关键细节

- IHDR 数据固定 13 字节：宽(4) 高(4) 位深(1) 颜色类型(1) 压缩方法(1, 必须 0) 滤波方法(1, 必须 0) 隔行方式(1: 0 无 / 1 Adam7)。
- 颜色类型：0 灰度、2 真彩 RGB、3 调色板索引、4 灰度+alpha、6 真彩+alpha；位深与颜色类型的组合受规范约束（如真彩只允许 8/16 位）。
- 每个扫描行前有 1 字节滤波类型：0 None / 1 Sub / 2 Up / 3 Average / 4 Paeth；全部 IDAT 拼接后是一个 zlib 流。
- 解析示例（python）：

  ```python
  import struct, zlib
  data = open('a.png','rb').read()
  assert data[:8] == b'\x89PNG\r\n\x1a\n'
  pos, idat = 8, b''
  while pos < len(data):
      ln, typ = struct.unpack('>I4s', data[pos:pos+8])
      body = data[pos+8:pos+8+ln]
      if typ == b'IHDR':
          w, h = struct.unpack('>II', body[:8])
          print('size', w, h, 'bit/color', body[8], body[9])
      elif typ == b'IDAT':
          idat += body
      pos += 12 + ln
  raw = zlib.decompress(idat)
  ```

- `pngcheck -v a.png` 逐块校验并输出宽高、色深、滤波与 CRC 状态。

## 常见坑

- 多个 IDAT 必须按序拼接后再 `zlib.decompress`，只解其中一块会报错或得到残缺数据。
- 宽高字段被篡改会导致解码异常（花屏/错位）；先用 `pngcheck` 定位异常块，按 IHDR 布局恢复后需重算 IHDR 的 CRC（CRC 只覆盖 13 字节数据），否则解码器会拒绝。
- 位深 16 时每像素分量占 2 字节；颜色类型 3 的调色板图数据是索引值而非直接 RGB。
- Adam7 隔行数据按 7 遍扫描顺序排布，直接按行拼接顺序会错乱。

## 验证方式

- `pngcheck -v a.png` 输出每块类型/长度/CRC 结果；python 脚本打印 IHDR 字段并解压 IDAT，比较解压长度与 `(height * (1 + width * channels * bytes_per_channel))` 是否吻合；修改宽高后同步重算 IHDR CRC 再验证解码。
