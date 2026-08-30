---
source_url: knowledge/reference/reverse/obfuscation-deobfuscation.md
source_title: Obfuscation identification and deobfuscation — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: reverse
tool_name: angr
---

# 混淆与去混淆：字符串加密与控制流平坦化（通用模式）

> 从多份已审核 writeup 提炼的通用解法模式，不含具体题目内容。

## 核心概念

混淆只增加静态分析的难度，运行逻辑必须等价于原始逻辑，因此"让它跑起来再观察"（动态）或"把等价逻辑化简"（符号执行/补丁）通常可行。CTF 常见两类：

- **字符串加密**：明文不出现在文件里，运行时解密后再使用。
- **控制流平坦化**（OLLVM `-mllvm -fla` 等）：把顺序基本块改写为"状态变量 + 巨型 switch 分派器"，反编译输出成百上千个 case，正常循环/分支结构消失。

## 关键细节

### 1. 字符串加密

识别：`strings` 几乎看不到有意义的明文；反编译中字符串以"被加密的字节数组"形式出现，作为参数传给解密函数，返回值再赋给局部缓冲区。

解法优先级：**能动态绝不静态**。

```text
(gdb) break *0x401100        # 设在解密函数返回之后的地址
(gdb) run
(gdb) x/s 0x406000           # 查看解密结果
(gdb) dump memory . 0x406000 0x406800   # 或直接导出解密区
```

- 定位解密函数：在反汇编中搜对固定字节数组的 `lea`/`mov` 引用，入口参数通常指向 `.rodata`。
- 也可主动调用：`(gdb) call (char*)decrypt((unsigned char*)0x404000)`，一次解一个。
- 若解密在程序入口前完成，`start` 后直接断点查看即可，无需逆向算法本身。

### 2. 控制流平坦化

识别：Ghidra/反编译器输出一个巨型 `switch`，各 case 间通过状态变量跳转，一个分派器（dispatcher）基本块反复出现。

三个方向，按成本排序：

- **动态跟踪**：记录运行时经过的基本块顺序，按该顺序重建实际控制流；平坦化只影响静态视图，运行时顺序就是原始逻辑顺序。
- **补丁去平坦化**：识别状态变量与分派器，把分派跳转替换为直接跳转到下一个实际基本块（deflat 类脚本的核心：按 state 值排序各 case 的前驱/后继，重建边后 patch）。
- **符号执行**（不关心结构，直接求输入）：

```python
import angr
p = angr.Project("./challenge", auto_load_libs=False)
state = p.factory.entry_state()
sm = p.factory.simulation_manager(state)
sm.explore(find=0x401234)          # 目标分支地址
s = sm.found[0]
print(s.posix.dumps(0))            # 求出的输入
```

### 3. 其他常见混淆

虚假控制流（恒真条件包裹死代码，如 `if (x * 2 == x + x)`）：符号执行或常量折叠后自动消除；指令替换/常量展开：动态跟踪或对比运行前后内存，通常比手搓还原快。

## 常见坑

- **在反编译里逐行读被平坦化的函数**：几千个 case 纯浪费时间，优先动态/符号执行。
- **断点下在解密完成之前**：应设在调用返回之后，否则看到的还是密文。
- **混淆层叠**（加密字符串 + 平坦化 + 反调试）：先处理反调试（见 anti-debug 卡片），再动态取字符串，最后才考虑 patch。
- **angr 找不到路径**：未设 `auto_load_libs=False`，或状态在任意地址继续执行（unconstrained）导致状态爆炸；改用 `veritesting=True` 或限定 `avoid` 地址。

## 验证方式

- 去混淆后的反编译可通读：if/for 结构清晰、调用关系符合直觉。
- `strings` 重新扫描能看到明文常量。
- 符号执行求出的输入能让程序走到预期分支；用真实输入对比两种分析结果一致。
