---
source_url: https://github.com/NationalSecurityAgency/pyghidra
source_title: pyghidra repository
source_version: current
publisher: National Security Agency (NSA)
license: Apache-2.0
retrieved_at: 2026-08-31
topic: reverse-engineering
tool_name: pyghidra
---
# pyghidra 反编译脚本用法

## 核心概念

pyghidra 是 NSA 提供的 Python 绑定，把 Ghidra 的 Sleigh 反编译与程序分析能力暴露给外部 Python 进程，无需打开 Ghidra GUI 就能对二进制做反编译、符号表查询、交叉引用分析，适合批量逆向与把 Ghidra 能力接进自动化流水线。

## 关键细节

### 安装与启动

```bash
pip install pyghidra
# 需先有 Ghidra 安装目录，未检测到时：
pyghidra --install-ghidra /path/to/ghidra_11.x_2024xx
```

首次运行会定位 `GHIDRA_INSTALL_DIR` 环境变量或已安装的 Ghidra；`pyghidra --help` 可看子命令。

### 一次性脚本模式（最常用）

```bash
pyghidra script.py ./bin
```

`script.py` 内通过 `pyghidra.open_program` 上下文拿到程序对象：

```python
import pyghidra

with pyghidra.open_program("./bin") as flat:
    api = flat  # FlatProgramAPI 实例
    listing = api.getCurrentProgram().getListing()
    fm = api.getCurrentProgram().getFunctionManager()
    for fn in fm.getFunctions(True):
        print(fn.getName(), hex(fn.getEntryPoint().getOffset()))
```

`flat`（FlatProgramAPI）提供 `getBytes`、`getSymbol`、`getFunctionAt` 等高层方法；底层对象通过 `api.getCurrentProgram()` 访问。

### 交互模式

```bash
pyghidra -i ./bin        # 启动交互式会话（逐行执行，便于探索）
```

### 反编译指定函数

```python
import pyghidra
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

with pyghidra.open_program("./bin") as flat:
    program = flat.getCurrentProgram()
    fn = program.getFunctionManager().getFunctionAt(
        program.getSymbolTable().getSymbol("main").getAddress())
    ifc = DecompInterface()
    ifc.openProgram(program)
    res = ifc.decompileFunction(fn, 30, ConsoleTaskMonitor())
    if res.decompileCompleted():
        print(res.getDecompiledFunction().getC())
```

`DecompInterface` 每次 `openProgram` 后复用；`decompileFunction(fn, timeout, monitor)` 的第二个参数是超时秒数，监控器一般用 `ConsoleTaskMonitor()`。

### 地址与字节

```python
addr = api.toAddr(0x4011a0)          # 数值 → Address
data = api.getBytes(addr, 16)        # 读 16 字节
api.setBytes(addr, bytes(...))       # patch（内存态）
sym = api.getSymbol("main")          # 符号 → Symbol，.getAddress()
```

## 常见坑

- 必须先 `pyghidra --install-ghidra` 或设 `GHIDRA_INSTALL_DIR`，否则 `ModuleNotFoundError`；每次升级 Ghidra 后要重装对应版本。
- `open_program` 默认只读分析；需要写回需在 `open_program(..., restore=False)` 之类参数下配合 `program.setWriteEnabled(True)` 显式处理。
- `DecompInterface` 的 `openProgram` 必须在同一程序实例上先于 `decompileFunction` 调用，且每轮 `decompile` 之间别重复 open。
- 函数名不存在（strip）时 `getSymbol("main")` 返回 `None`，先用 `getFunctions(True)` 遍历拿入口或按地址取。
- 脚本里的 `flat` 与 Ghidra 脚本环境不同：没有自动注入的 `currentProgram` 全局变量，必须从 `open_program` 上下文取。

## 验证方式

对任意 ELF 运行 `pyghidra script.py ./bin`（脚本只打印 `main` 反编译结果），应输出 C 风格反编译代码且无异常；再打印 `main` 入口地址，与 `readelf -h` 的 Entry point 或 `objdump -t` 对照应一致。
