---
source_url: knowledge/reference/crypto/padding-oracle.md
source_title: Padding oracle attack — CBC PKCS#7 pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: crypto
tool_name: python
---

# Padding Oracle 攻击模式

> 从已审核 writeup 提炼的通用解法模式，不含具体题目数据。

## 核心概念

CBC 解密时 `P_i = D(C_i) XOR C_{i-1}`，密文被解出后按 PKCS#7 校验填充：最后一字节为 `0x01`，或 `0x02 0x02`，以此类推，最大 `0x10`。若服务端对**填充不合法**与**其它错误**返回可区分的响应（状态码、报错文案、时序），即构成 padding oracle：攻击者可以逐字节篡改前一块密文，反向探测 `D(C_i)` 的中间值，最终恢复整块明文。

## 关键细节

- **逐字节探测**：攻击第 `i` 块的中间值 `I_i = D(C_i)`。置 `C_{i-1}[15] = g`，从 `0x00` 试到 `0xff`，当填充校验通过（服务端返回非填充错误）时，`I_i[15] = g XOR 0x01`。
- **固定已解字节**：已知 `I_i[j+1..15]` 后，把 `C_{i-1}[j+1..15]` 设为 `I_i[k] XOR pad`（`pad = 16 - j`），再暴力 `C_{i-1}[j]`，通过时 `I_i[j] = g XOR pad`。
- **还原明文**：整块中间值解出后 `P_i = I_i XOR C_{i-1}`（用原始密文块）。
- **第一块**：`P_1 = I_1 XOR IV`，即把 IV 当作第 0 块密文处理。
- **解密任意密文**：oracle 只要求能构造合法填充，因此可把任意目标块当作 `C_i` 输入，用自己构造的 `C_{i-1}` 解出 `D(C_i)`。

```python
# 伪代码骨架（单块、只解第 16 字节）
inter = bytearray(16)
for pos in range(15, -1, -1):
    pad = 16 - pos
    for g in range(256):
        c_prev = bytearray(16)
        for k in range(pos+1, 16):
            c_prev[k] = inter[k] ^ pad
        c_prev[pos] = g
        if oracle(c_prev + c_target):   # 服务端判定填充合法
            inter[pos] = g ^ pad
            break
plain = bytes(x ^ y for x, y in zip(inter, c_prev_orig))
```

## 常见坑

- oracle 判定必须是**填充错误与其它错误分离**；若服务端统一返回同一错误（或无区分），攻击不成立。
- 探测最后一个字节时，若中间值恰好使某高字节合法（如 `...02 02`），会提前命中干扰结果——用下一字节的探测结果回校，或从已知 `pad` 反推修正。
- 每次请求数在 256 量级/字节，交互必须复用同一连接或处理连接重置；网络抖动导致的假阳性要重试。
- 密文块数多于 1 时逐块解，块间独立；不要把 `C_{i-1}` 和 `C_i` 的索引搞混。
- PKCS#7 填充值只到 `0x10`；若解出的 `pad` 大于块长说明中间值有误。

## 验证方式

- 本地搭一个最小 CBC 解密服务复现 oracle，用同一脚本跑通再打远程。
- 每解完一块用已知明文位置自检（如已知前缀）验证中间值正确。
- 对已解明文重新加密一轮，确认构造的密文能被服务端正常解密（端到端闭环）。
