---
source_url: https://ericpony.github.io/z3py-tutorial/guide-examples.htm
source_title: Z3Py Guide (Z3 API in Python)
source_version: current
publisher: Z3 project / Microsoft Research
license: MIT
retrieved_at: 2026-08-31
topic: constraint-solving
tool_name: z3
---
# Z3 约束求解常用模式：BitVec、Int 与求解循环

## 核心概念

Z3 是 SMT 求解器，Python 绑定称 Z3Py。CTF 用途集中在两类：一是密码/数学类直接把未知数建模为 `Int` 或 `BitVec` 求解；二是逆向类把程序中对字节的运算翻译成位向量约束，让求解器反推满足条件的输入（通常再交给 z3 输出字节串）。

## 关键细节

### 基本流程

```python
from z3 import *
x = Int('x')
s = Solver()
s.add(x > 10, x < 20, x % 7 == 0)
print(s.check())      # sat / unsat / unknown
m = s.model()
print(m[x])           # 取解
```

`check()` 返回 `sat` 才可取 `model()`；`unsat` 说明约束矛盾；`unknown` 常见于非线性或超大规模约束。

### BitVec 位操作

```python
a = BitVec('a', 32)            # 32 位位向量，无符号语义
b = BitVecVal(0xdeadbeef, 32)  # 常量
c = (a ^ b) & 0xff             # 位运算
d = LShR(a, 8)                 # 逻辑右移（无符号）
e = a >> 8                     # 算术右移（有符号）
ext = ZeroExt(24, a)           # 零扩展（8→32）
sgn = SignExt(24, a)           # 符号扩展
lo = Extract(7, 0, a)          # 取低 8 位
hi = Extract(31, 24, a)        # 取高 8 位
concat = Concat(a, b)          # 拼接
```

逆向中最易错的是移位：Python 的 `>>` 对 `BitVec` 是算术右移，无符号场景必须用 `LShR`；`Extract` 的参数是 `(high, low, expr)` 而非 `(low, high)`。

### 多字节输入建模

```python
secret = [BitVec(f'f{i}', 8) for i in range(32)]  # 32 字节输入
s = Solver()
for i, c in enumerate(secret):
    s.add(And(c >= 0x20, c <= 0x7e))   # 可打印字符约束
s.add(secret[0] == ord('f'))
# ... 逐字节加程序约束 ...
m = s.model()
out = bytes([m[secret[i]].as_long() for i in range(32)])
```

取解用 `as_long()` 转成 Python 整数，再 `bytes()` 组装，避免 `m[expr]` 直接拼接出错。

### 求解循环（枚举多个解）

```python
while s.check() == sat:
    m = s.model()
    sol = [m[secret[i]].as_long() for i in range(32)]
    print(bytes(sol))
    s.add(Or([secret[i] != sol[i] for i in range(32)]))  # 排除当前解
```

每轮把当前解以"至少一个字节不同"的形式加回去，即可迭代出全部解（用于多解程序或验证唯一性）。

### 常用手法

- 乘加混合：`Int` 解模逆、同余式；`BitVec` 解溢出回绕（自动按 2^32 取模）。
- 与常量表比较：把变换写成表达式后 `s.add(y == const)`。
- 非线性（乘两个未知数）优先尝试 `BitVec` 而非 `Int`，有时 `unknown` 但 `sat` 可得；再不行拆位约束。

## 常见坑

- 忘记 `LShR`：对无符号字节用 `>>` 会把高位当符号位，结果偏差。
- `Extract` 参数顺序写反；`ZeroExt/SignExt` 的第一个参数是"扩展的位数"不是目标总位宽。
- `model()` 里未约束变量返回 `None`，用 `m[x]` 前先 `s.check() == sat` 并给足约束。
- 位宽不匹配（8 位与 32 位混加）直接 `z3.z3types.Z3Exception`，先 `ZeroExt` 对齐。

## 验证方式

运行 `x = BitVec('x', 8); s = Solver(); s.add(x * 2 == 0x1fe); print(s.check(), hex(s.model()[x].as_long()))` 应输出 `sat 0xff`，验证溢出回绕语义正确。
