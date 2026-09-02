---
source_url: knowledge/reference/crypto/cbc-bit-flipping.md
source_title: CBC bit flipping attack — pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: crypto
keywords_en: CBC bit flipping, bit flip, block cipher, 翻转攻击
tool_name: python
---

# CBC 位翻转攻击模式

> 从已审核 writeup 提炼的通用解法模式，不含具体题目数据。

## 核心概念

CBC 解密公式 `P_i = D(C_i) XOR C_{i-1}`：修改密文块 `C_{i-1}` 的第 `k` 字节，只会确定性翻转 `P_i` 的同位置字节（异或属性），而 `P_{i-1}` 被完全破坏（随机）。攻击者若能控制密文且已知目标块明文（或能猜出），即可按需修改解密结果——常用于篡改 Cookie/会话字段、把 `admin=0` 改成 `admin=1`。

## 关键细节

- **翻转公式**：设原明文 `P_old[k]`、目标明文 `P_new[k]`，则令 `C_{i-1}[k] ^= P_old[k] ^ P_new[k]`，解密后 `P_i[k]` 即变为 `P_new[k]`。
- **已知明文来源**：题目常给出可读取的密文对应明文（如可解密/可打印的 cookie 内容），据此计算差分。
- **目标块位置**：被篡改的是**前一块**密文；要改第 `i` 块的字节就改第 `i-1` 块，第一块改 IV（`P_1 = D(C_1) XOR IV`）。
- **只改字节不改块**：`^=` 操作保持块长不变，服务端按块解密不报错；前提是整块解密后填充仍合法——因此目标字节通常是明文中间的 ASCII，不要落在填充区。

```python
def flip(block, k, p_old, p_new):
    b = bytearray(block)
    b[k] ^= p_old ^ p_new   # 原位异或，不改变块长
    return bytes(b)

# 修改第 i 块明文 → 改第 i-1 块密文；修改第 1 块明文 → 改 IV
```

## 常见坑

- **连带破坏**：改 `C_{i-1}` 会同时破坏 `P_{i-1}`。若服务端校验整段明文（如用户名+权限字段连读），需保证被破坏块内容无关紧要，或一并修正（翻转被破坏块对应的更前一块）。
- 目标明文必须**逐字节精确**：把 `admin=0` 改成 `admin=1` 只翻一字节，但写成整块替换会破坏填充。
- 修改落在 PKCS#7 填充字节上会触发填充错误，攻击失败；优先改块中部可打印字符。
- IV 参与第一块解密，改 IV 不影响其它块，但服务端可能丢弃 IV 变更（如 IV 固定/校验），需先确认 IV 是否可控。
- 只凭密文没有已知明文时无法直接翻转，需配合其它信息（明文格式可猜）再动手。

## 验证方式

- 本地用 `Crypto.Cipher.AES.new(key, MODE_CBC, iv)` 正反两遍验证：翻转后解密结果中目标字节等于 `P_new`，且除目标块外的块不受影响。
- 逐字节回放：每翻一个字节，服务端行为应只对应那一处差异。
- 若题目返回解密后的内容（错误回显），用它核对 `P_old` 的取值是否与猜测一致。
