---
source_url: knowledge/reference/reverse/pyinstaller-unpacking.md
source_title: PyInstaller 打包产物提取与逆向 — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-09-02
topic: reverse
keywords_en: pyinstaller, pyinstxtractor, MEI, CArchive, PYZ, 打包
tool_name: pyinstxtractor
---

# PyInstaller 打包产物提取与逆向（通用模式）

> 从多份已审核 writeup 提炼的通用解法模式，不含具体题目内容。

## 核心概念

PyInstaller 把 Python 应用连同解释器打包成单个可执行文件（Windows `.exe` / Linux ELF）。
识别特征：体积大（数 MB 起）、`strings` 中出现 Python 相关路径（`python3x.dll`、
`base_library.zip`、`PyInstaller`、`_MEIPASS`、`pyi-` 前缀函数）或压缩库名（`zlib`/`lzma`）。
打包结构：文件尾是 `MEI`/`CArchive` 目录（overlay），内含压缩的 TOC（table of contents）
指向各模块（`.pyc`、`.dll`、数据文件）。

## 关键细节

### 1. 识别与提取

```console
$ file challenge.exe                    # PE32+ console，但体积异常
$ strings -el challenge.exe | grep -iE "pyinstaller|_MEIPASS|python3" | head
$ python3 pyinstxtractor.py challenge.exe   # 输出 challenge.exe_extracted/
```

`pyinstxtractor.py`（开源脚本，单文件）是标准工具：解析 CArchive 覆盖层，把 TOC 中的
条目解压到 `<exe>_extracted/` 目录。常见变体：`pyinstxtractor-ng`（支持新版 PyInstaller
6.x / zstd 压缩）。

### 2. 提取后定位主模块

提取目录中 `PYZ-00.pyz` 是打包的纯 Python 模块集合，`struct`（或 `main`/`run`）是入口 stub。
真正的题目逻辑通常在 `PYZ-00.pyz` 内或作为单独 `.pyc` 存放：

```console
$ ls challenge.exe_extracted/          # struct, PYZ-00.pyz, base_library.zip, ...
$ python3 -c "import pyz; pyz.show('challenge.exe_extracted/PYZ-00.pyz')"  # 或 pyinstxtractor 自带工具
```

主 `.pyc` 的 magic number 与 Python 版本对应；PyInstaller 打包时可能用与系统不同的
Python 版本，需按 magic 匹配反编译工具。

### 3. 反编译提取出的 pyc

```console
$ pycdc challenge.exe_extracted/struct  # 或对应主模块 pyc
$ uncompyle6 -o out.py challenge.exe_extracted/struct
```

注意：PyInstaller 的 stub（`struct`/`main`）反编译结果通常无意义（只是引导代码），
真正逻辑在 `PYZ-00.pyz` 里的模块中——用 `pyinstxtractor` 的 `pyz` 工具列出并解出目标
模块再反编译。压缩（zstd/lzma）的 PyInstaller 6.x 需要 `pyinstxtractor-ng`。

### 4. 无工具时的手工路径

- `binwalk challenge.exe` 或搜 `MEI` 魔数定位 overlay 偏移；
- 手工读 TOC：条目格式 `(offset, length, compr_flag, type, name)`，按 flag 决定
  zlib/lzma 解压；
- 解出 `.pyc` 后按 magic 定版本（`importlib.util.MAGIC_NUMBER` 对照），再走
  pyc-reversing 流程（`marshal.load` + `dis` 或 pycdc）。

## 常见陷阱

- **版本不匹配**：pycdc 对高版本字节码（3.11+）支持有限，必要时 `dis` 手工分析；
- **加密/混淆**：PyInstaller 6.x 支持 `--key` 加密 pyc，提取后还需先解密
  （key 硬编码在 stub 中，可动态调试或搜常量）；
- **二次打包**：题目可能把 pyc 再压进自定义容器，先识别容器再提 pyc。
