---
source_url: knowledge/reference/crypto/rsa-attacks.md
source_title: RSA common attack patterns — wiener / fermat / low exponent / common modulus
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: crypto
tool_name: python
---

# RSA 常见攻击模式

> 从已审核 writeup 提炼的通用解法模式，不含具体题目数据。

## 核心概念

RSA 安全性依赖大整数分解困难。攻击入口几乎总是**参数的极端取值**：私钥指数过小、素数相近、公钥指数过小、多组密文共用参数。解题先看 `(n, e, c)` 的数字特征再选攻击面。

## 关键细节

- **Wiener（小私钥指数）**：`d < N^0.25` 时可用连分数攻击。对 `e/N` 展开连分数，逐项取渐近分数 `k/d'`，检查 `(e*d' - 1)` 能否被 `k` 整除，若能则令 `phi = (e*d' - 1)//k`，解一元二次方程 `x^2 - (n - phi + 1)x + n = 0` 判判别式是否完全平方。

```python
# 用 sage 或 python 连分数实现；核心检查：
# phi = (e*d - 1) // k; 判 4*n 是否为 (n-phi+1)^2 的完全平方
```

- **Fermat（素数相近）**：设 `a = isqrt(n) + 1`，循环 `b^2 = a^2 - n` 直到为完全平方数，得 `p = a - b`，`q = a + b`。`p`、`q` 接近时收敛极快。

```python
from math import isqrt
a = isqrt(n) + 1
while True:
    b2 = a*a - n
    b = isqrt(b2)
    if b*b == b2: break
    a += 1
p, q = a - b, a + b
```

- **低公钥指数（e 很小）**：`e=3` 且 `m < N^(1/3)` 时 `c = m^3`（无模），直接 `iroot(c, 3)`。同一明文发给 `e` 份不同模数的接收者时用 CRT 合并后开 `e` 次方（Håstad 广播）。

```python
from sympy import integer_nthroot
m = integer_nthroot(c, 3)[0]          # 无模情形
m = integer_nthroot(crt(Ns, cs), 3)[0] # 广播情形，Ns 为各模数
```

- **共模攻击**：同一 `n`、两组 `(e1, c1)`、`(e2, c2)` 且 `gcd(e1, e2) = 1`。扩展欧几里得求 `u*e1 + v*e2 = 1`（注意 `v` 为负时对 `c2` 求模逆），`m = c1^u * c2^v mod n`。
- **模数不互素**：多组 `(n_i, e, c_i)` 两两求 `gcd`，若 `gcd(n_i, n_j) > 1` 即共享素数，直接分解并解密。
- **恢复私钥**：得 `p, q` 后 `d = pow(e, -1, (p-1)*(q-1))`，`m = pow(c, d, n)`。

## 常见坑

- Wiener 里 `k=0` 的项直接跳过；`e` 给的是小值（如 65537 固定）时优先排查其它攻击面，勿盲目套 Wiener。
- Fermat 的起点 `isqrt(n)+1` 必须正确；用 `isqrt` 而非 `int(sqrt(n))` 避免浮点误差。
- 广播攻击要求各组 `c_i` 对应**同一明文**且密文未做随机填充；题目若对每个接收者加了不同填充则失效。
- 共模攻击中 `u`、`v` 一正一负，负指数要对相应密文先求模逆再乘方。

## 验证方式

- 自检：`p * q == n`；`(d * e) % ((p-1)*(q-1)) == 1`。
- 解密结果先转字节再判可读性（`bytes.fromhex(hex(m)[2:])`），避免只看整数。
- 用 `sage` 的 `RSA.construct((n, e, d))` 或自写解密复算一遍交叉验证。
