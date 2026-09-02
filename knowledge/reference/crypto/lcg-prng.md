---
source_url: knowledge/reference/crypto/lcg-prng.md
source_title: LCG linear congruential generator — break pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: crypto
keywords_en: LCG, linear congruential generator, PRNG, random prediction, 随机数
tool_name: python
---

# LCG 线性同余生成器破解模式

> 从已审核 writeup 提炼的通用解法模式，不含具体题目数据。

## 核心概念

LCG（线性同余生成器）递推关系：`X_{n+1} = (a * X_n + c) mod m`，其中 `a` 为乘数、`c` 为增量、`m` 为模数、`X_0` 为种子。破解目标：由若干连续输出恢复参数 `(m, a, c)`，从而预测后续任意输出。

## 关键细节

- **求模数 m**：设相邻输出差 `t1 = X1 - X0`，`t2 = X2 - X1`，则 `m | gcd(t2, t1)`。多取几组差求 `gcd` 后约掉小因子即得真实 `m`（gcd 结果若大于 1 且为合数，需用 `sympy.factorint` 或逐一除以小素因子）。
- **求乘数 a**：`a = (X2 - X1) * pow(X1 - X0, -1, m) % m`（Python 3.8+ 支持 `pow(x, -1, m)` 求模逆）。
- **求增量 c**：`c = (X1 - a * X0) % m`。
- **已知 m、未知 a/c**：只需两组输出：`a = (X2 - X1) * pow(X1 - X0, -1, m) % m`。
- **输出被截断**（如只给高位若干比特）：用格子/联立同余恢复完整状态，或直接交给 Z3 约束求解。

示例还原脚本骨架：

```python
from math import gcd

xs = [...]  # 连续输出
diffs = [xs[i+1] - xs[i] for i in range(len(xs) - 1)]
m = 0
for t in diffs:
    m = gcd(m, t)
# 必要时去掉小因子：while m % p == 0 且 (m//p) 仍满足同余
a = (xs[2] - xs[1]) * pow(xs[1] - xs[0], -1, m) % m
c = (xs[1] - a * xs[0]) % m
```

## 常见坑

- 输出顺序必须**严格连续**；中间混入其它调用（如题目同时用生成器做别的随机）会导致差分解法失效。
- `m` 未必等于 gcd 结果本身：gcd 常带多余因子，需验证 `a, c` 恢复后能否复现整条序列。
- 若题目给出的是 `getrandbits` 截断输出，差分法直接套用会失败，先按位拼接重建完整状态。
- 忘记取模导致负值：`c = (X1 - a * X0) % m` 用 `%` 而非直接减。

## 验证方式

- 用恢复的 `(m, a, c)` 从 `X0` 起复算至少 10 项，与题目输出完全一致。
- 预测下一项 `X_next = (a * X_last + c) % m`，与题目后续给出的值比对。
- 若题目附生成脚本，本地用同一参数正跑一遍逐项对照。
