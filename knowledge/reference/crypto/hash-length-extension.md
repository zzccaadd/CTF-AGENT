---
source_url: knowledge/reference/crypto/hash-length-extension.md
source_title: Hash length extension attack — pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: crypto
tool_name: python
---

# 哈希长度扩展攻击模式

> 从已审核 writeup 提炼的通用解法模式，不含具体题目数据。

## 核心概念

MD5、SHA-1、SHA-256 等基于 Merkle–Damgård 结构的哈希，内部状态就是"截至当前的消息摘要"。已知 `H(secret || message)`（secret 长度可猜）时，无需知道 secret 内容，即可继续从该状态往后压缩任意追加数据，伪造 `H(secret || message || padding || extra)` 的合法摘要。典型场景：服务端用 `MAC = H(secret || msg)` 校验消息，且校验逻辑只比对摘要。

## 关键细节

- **填充规则（MD 结构通用）**：消息末尾补 `0x80`、若干 `0x00`、最后 8 字节为**原始消息长度（bit 计，大端）**；总长对齐到块长（SHA-256 块 64 字节，SHA-1/MD5 同；长度字段为 64 位，即 `len << 3` 对 `2^64` 取模）。
- **攻击流程**：
  1. 已知 `H(secret || msg)` 与 `len(secret)`（长度未知时按常见取值枚举，如 8/16/32 字节）。
  2. 计算 `pad1`：使 `len(secret || msg) + len(pad1)` 对齐块长。
  3. 用 `H(secret || msg)` 作为**初始状态**继续压缩 `extra`（需先补 `pad2` 使 `secret || msg || pad1 || extra` 对齐）。
  4. 提交 `msg || pad1 || extra` 与新摘要；服务端算出 `H(secret || msg || pad1 || extra)` 与之相等。
- **工具**：`hashpumpy`（C 扩展）、`hlextend`（纯 Python），直接调用省去手写压缩细节。

```python
import hlextend
s = hlextend.new()
append = s.extend(b'extra', b'msg', len(secret), digest_hex)
# append 即 msg || pad1 || extra；s.hexdigest() 为伪造摘要
```

- **不适用**：SHA-3/Keccak（海绵结构）、BLAKE2（有内部去填充防御）、截断输出（如 SHA-224/384 丢弃部分状态位，无法重建完整状态）。

## 常见坑

- **长度必须精确**：`len(secret)` 猜错 1 字节，整个伪造摘要即失效——先枚举常见长度（题目给出 token/随机串长度时直接采用），再逐个试。
- 追加数据在 `pad1` **之后**，不是紧接原消息；服务端收到的是带注入填充的合法消息，不是原始消息 + extra。
- 长度字段是 **bit** 且大端：64 位写 `(total_len << 3) & 0xffffffffffffffff`，忘加 `<< 3` 是最常见错误。
- 摘要字节序：多数库输出小端内部状态（尤其 MD5/SHA-1 工具类），对接时确认字符串 hex 顺序。
- 校验若包含"消息必须与摘要同步更新"（如密钥在新消息后更换）则攻击不成立，先读清服务端逻辑。

## 验证方式

- 本地构造 `secret`（随机字节）+ 消息，先算合法 MAC；再用脚本生成 `msg || pad1 || extra` 的伪造摘要，与"用完整 secret 前缀直接算 `H(secret || msg || pad1 || extra)`"逐字节比对。
- 长度枚举：对每个候选 `len(secret)` 重算并提交，命中即服务端放行。
- 用标准库 `hashlib` 对照验证 padding 字节的二进制布局。
