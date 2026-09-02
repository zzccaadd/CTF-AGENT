---
source_url: knowledge/reference/reverse/pyc-reversing.md
source_title: Python pyc decompilation and bytecode analysis — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: reverse
keywords_en: pyc, python bytecode, decompile, uncompyle6, pycdc, marshal, 反编译
tool_name: pycdc
---

# Python pyc 反编译与字节码分析（通用模式）

> 从多份已审核 writeup 提炼的通用解法模式，不含具体题目内容。

## 核心概念

`.pyc` 是 Python 源码编译后的字节码文件：文件头（magic number + 时间戳/大小）后接一个用 `marshal` 序列化的 code object。反编译目标二选一：恢复近似源码（uncompyle6/pycdc），或直接读字节码（`dis`）。**版本匹配是成败关键**：magic number 对应 Python 小版本，工具与运行环境必须与之匹配。

## 关键细节

### 1. 先确定 Python 版本

```console
$ file challenge.pyc
$ xxd challenge.pyc | head -1      # 前 4 字节是 magic number
$ python3 -c "import importlib.util; print(importlib.util.MAGIC_NUMBER.hex())"
```

比对 magic 后选定工具与解释器：3.9+ 推荐 `pycdc`（C++ 实现，对新版字节码支持最好）；2.7–3.8 可用 `uncompyle6`/`decompyle3`。

### 2. 反编译

```console
$ uncompyle6 -o out.py challenge.pyc
$ pycdc challenge.pyc > out.py
```

反编译失败或输出残缺时降级到字节码层：

```python
import dis, marshal
f = open("challenge.pyc", "rb")
f.read(16)                 # 3.7+ 头 16 字节；旧版 8 字节，按 file 输出调整
code = marshal.load(f)
dis.dis(code)              # 顶层指令
for c in code.co_consts:   # code object 本身也是常量（嵌套函数）
    if isinstance(c, type(code)):
        print(c.co_name)
        dis.dis(c)
```

`dir(code)` 可查全部属性：`co_consts`（常量/嵌套代码对象）、`co_names`（全局名）、`co_varnames`、`co_code`（原始字节码）、`co_freevars`/`co_cellvars`（闭包）。加密逻辑常表现为 `LOAD_CONST` 直接加载字符串常量或调用某个函数。

### 3. 打包产物（PyInstaller 等）

先提取再反编译：

```console
$ pyinstxtractor.py challenge.exe    # 输出 challenge.exe_extracted/
$ file challenge.exe_extracted/*     # 主脚本 pyc 常无 magic 头，需手工补上再反编译
```

## 常见坑

- **magic 不匹配**：`marshal.load` 直接报错或反编译器崩溃；先 `file`/magic 定版本，再选同版本工具与解释器。
- **uncompyle6 报 "Python version not supported"**：对 3.8+ 字节码支持差，换 `pycdc`/`decompyle3`。
- **头部长度算错**：读 code object 前多/少读字节都会让 `marshal.load` 失败；用 `file` 确认头结构后再定偏移。
- **字符串分片/拼接**：反编译显示为常量拼接是正常现象，别误判为混淆；真混淆时直接看 `co_consts` 里的明文常量。
- **反编译输出带 `# uncompyle6 version ...` 注释**：正常产物，不是错误信息。

## 验证方式

- 反编译源码在同版本 Python 下可运行，行为与原文件一致（对比关键输出）。
- 字节码反汇编中指令序列与逻辑吻合：`LOAD_CONST`/`CALL_FUNCTION` 序列对应源码中的函数调用。
- 用同版本 `python3 -m py_compile` 生成参考 pyc，`dis` 对比指令差异，判断字节码是否被改造。
