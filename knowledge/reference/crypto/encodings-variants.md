---
source_url: knowledge/reference/crypto/encodings-variants.md
source_title: Common encoding variant identification — base64 / hex / ROT / custom
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: crypto
tool_name: python
---

# 常见编码变体识别

> 从已审核 writeup 提炼的通用解法模式，不含具体题目数据。

## 核心概念

编码不是加密：无密钥或密钥公开，重点在**识别变体**。先看输出字符集、长度特征、是否有填充字符，据此锁定编码族，再按变体规则解码。常见的"多轮编码"题目需按逆序逐层解。

## 关键细节

- **Base64**：字符集 `A-Za-z0-9+/`，长度必为 4 的倍数，末尾 `=` 填充（最多两个）。变体：URL-safe（`-` `_` 替代 `+/`）、缺填充（长度 `%4 == 2/3` 时补 `=`）。`base64.b64decode(s, validate=True)` 可校验非法字符。
- **Base32**：字符集 `A-Z2-7`，长度 8 的倍数，填充 `=` 最多 6 个；常见于被大写化的密文。`base64.b32decode`。
- **Base58 / Base62 / Base85**：Base58 无 `0 O I l` 四字符（比特币地址风格）；Base62 为 `0-9A-Za-z`；Base85（ASCII85/Ascii85 或 Z85）输出几乎全是可打印 ASCII，`base64.a85decode/b85decode`。见到"数字+大小写字母混合"且无填充符优先怀疑这三者。
- **Hex**：仅 `0-9a-f` 且长度为偶数；`bytes.fromhex(s)` / `s.hex()`。注意大小写混合的 hex（`0-9A-F`）仍属 hex。
- **ROT/凯撒**：字母表内循环移位。ROT13 自逆（两次还原）；ROT47 作用于可打印 ASCII（`33–126`）。暴力尝试 26 次移位，按词频/英文单词命中判断。

```python
def rot(s, k):                       # 只移字母
    return ''.join(chr(65 + (ord(c)-65+k) % 26) if c.isupper() else
                   chr(97 + (ord(c)-97+k) % 26) if c.islower() else c for c in s)
```

- **自写编码（换表）**：题目常给"自定义 base64 表"或"逐字符映射"。若给定表与标准表，按表索引重映射回标准字符集再解码；若只给编码后文本与样例，用已知明文片段（常见前缀）反推映射关系。
- **数字编码**：一串十进制/十六进制数每项恰在 ASCII 范围（32–126）→ 逐项 `chr` 拼接；也可能按 `0x...` 或 `\xNN` 转义书写。

## 常见坑

- **顺序**：多轮编码按生成逆序解（后编码的先解）；先判断每层特征再动手，别在错误层硬解。
- Base64 变体用错字符集（`+` `/` 变 `-` `_`）会报 padding/字符错误——先看输出里是否有 `-` `_`。
- 大写化后的 base32 容易误判为 base64 前 32 字符子集：注意长度 `%8==0` 且出现 `2-7` 时优先 base32。
- ROT 仅移字母：含数字/符号时逐字符判断，直接 `ord(c)±k` 会破坏非字母字符。
- 换表编码中 `=` 填充位仍在，解码后先看可打印率再判断是否还有下一层。

## 验证方式

- 解码结果的可打印率 > 95% 且成词（可跑 `isprintable` 检查）。
- 用 `cyberchef`（本地/在线）多层 recipe 交叉验证每层选择；或写脚本逐层打印中间状态核对。
- 对换表编码，用已知明文前缀反推 3–5 个字符确认映射规律后再全量解码。
