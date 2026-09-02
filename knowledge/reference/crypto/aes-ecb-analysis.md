---
source_url: knowledge/reference/crypto/aes-ecb-analysis.md
source_title: AES-ECB mode analysis — block reorder / repeated block
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: crypto
keywords_en: AES, ECB, block cipher, electronic codebook, 分组密码
tool_name: python
---

# AES-ECB 模式分析

> 从已审核 writeup 提炼的通用解法模式，不含具体题目数据。

## 核心概念

ECB 模式对每个 16 字节明文块独立加密：**相同明文块 → 相同密文块**，块间无链接。两个直接后果：① 密文块频率泄漏明文结构（可检测出重复块）；② 块的顺序不影响解密合法性（cut-and-paste：密文块可任意重排/增删而不破坏解密）。题目常利用这两点构造"选择明文 → 逐字节恢复未知串"的 oracle 型攻击。

## 关键细节

- **块大小**：AES 固定 16 字节；检测重复块时按 16 字节切分后统计。

```python
def chunks(data, size=16):
    return [data[i:i+size] for i in range(0, len(data) - len(data) % size, size)]

repeated = [c for c in chunks(ct) if chunks(ct).count(c) > 1]  # 有重复块 → 疑似 ECB
```

- **检测 ECB vs CBC**：向加密 oracle 提交可控长输入（如 64 字节 `A*64`），若输出中出现重复 16 字节块即为 ECB（CBC 下相同明文块也因链式异或而不同）。
- **逐字节恢复未知串（经典构造）**：设未知串为 `s`、可控前缀 `p`、可控后缀 `q`（服务端输出 `E(p || s || q)`）。
  1. 令 `p` 长度为 `15 - len(s) mod 16` 使 `s` 的第一字节落在某块末位，记录该块密文。
  2. 用 `p'`（长度同上）拼接猜测字符 `c1`，得到 `E(p' || c1)` 的对应块，与上一步比对——相等即猜中 `s[0]`。
  3. 逐字节推进，每次把已知部分移入猜测块。
- **块重排（cut-and-paste）**：若服务端按固定字段布局解密（如 `username||role||...`），把含目标字段的块换到解密结果中被读取的位置；块间独立，无需重加密。

## 常见坑

- 服务端可能在 `s` 前后拼接额外前缀/后缀（如固定字符串），块边界计算必须**先实测**：用不同长度输入观察块边界偏移，而不是假设 `p` 为空。
- 密文长度若非 16 的倍数，末尾不足一块的填充字节不可参与重排，否则解密报填充错误。
- 重复块检测要排除完全由可控输入产生的块，确认差异仅来自未知串。
- 猜测逐字节恢复时，每步的已知前缀长度随 `s` 增长而变化，公式 `15 - (len(s) + len(known)) % 16` 要算准。

## 验证方式

- 本地模拟 oracle：`E(p||s||q)` 用固定 key 的 AES-ECB 加密，跑恢复脚本与真实 `s` 逐字节比对。
- 对 cut-and-paste，本地把重排后的密文解密，确认服务端读取字段值符合预期且填充合法。
- 先做 ECB/CBC 判别实验（重复块特征）再决定是否进入逐字节恢复流程。
