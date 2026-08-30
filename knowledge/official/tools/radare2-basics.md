---
source_url: https://book.rada.re/
source_title: radare2 book
source_version: current
publisher: radare org
license: CC BY-NC 3.0 (book), LGPL (radare2)
retrieved_at: 2026-08-31
topic: binary-analysis
tool_name: radare2
---
# radare2 基础：分析、反汇编与调试

## 核心概念

radare2（r2）是命令行逆向框架。核心心智模型是"当前偏移（seek）"：所有打印、反汇编都以当前 seek 位置为基准，配合分析产生的函数、交叉引用等元数据，用极短命令完成从打开文件到反汇编、动态调试的全流程。

## 关键细节

### 打开与分析

```bash
r2 ./bin            # 只读打开
r2 -w ./bin         # 可写打开（可 patch）
r2 -A ./bin         # 打开并自动分析
r2 -d ./bin         # 以调试模式启动（类似 gdb）
```

分析建议：进入后先 `aaa`（a、aa、aaa 三档，aaa 为深度分析），再 `afl` 列函数、`iI` 看 ELF 头信息、`ii` 看导入符号。

### seek 与反汇编

```bash
s main              # seek 到 main
s 0x401200          # seek 到绝对地址
pdf                 # 反汇编当前函数（Print Disassembly Function）
pdr                 # 带引用的反汇编
afl                 # 函数列表
axt @ sym.imp.strcmp   # 谁引用了 strcmp（xref to）
axf main            # main 调用了谁（xref from）
s-                  # 回到上一个位置
```

`pdf` 是最常用命令，输出含地址、指令、注释，比 `objdump -d` 更易读。用 `pd 20` 反汇编 20 条指令。

### 打印与搜索

```bash
px 64 @ 0x404000    # hexdump 64 字节
ps @ 0x404020       # 按字符串打印
iz                  # 文件中字符串（.rodata 等）
izz                 # 全文件字符串（含可执行段）
iS                  # 节表
/i str              # 在文件中搜字符串
/x 7f454c46         # 搜字节序列
/r 0x401100         # 搜引用该地址的指令
```

`izz` 对静态链接或加密壳后的提取比 `strings` 更可控，可按 `~` 过滤：`izz~key` 只显示含 key 的行（避免把完整字符串写进脚本，只用于交互检索）。

### 调试

```bash
r2 -d ./bin
db main             # 在 main 下断点
dc                  # continue
ds                  # step 一条指令
dr                  # 显示寄存器
dr rax=0x41414141   # 修改寄存器
dbt                 # 回溯（backtrace）
dm                  # 内存映射（看 PIE 基址）
```

调试模式下 seek 是"逻辑地址"，`dm` 显示的实际映射基址与文件偏移的换算方式和 GDB 相同。

### 可视化

`V` 进入可视化面板：`p` 切换视图（反汇编/十六进制/图形），`V` 再按 `V` 进图形视图（函数调用关系），方向键移动，`q` 逐层退出。

## 常见坑

- 忘了 `aaa` 就 `afl`/`pdf`，结果为空或只有入口函数——分析必须先于函数查询。
- seek 是全局状态：`pdf` 停在别的地址时输出的是那个函数，先 `s main` 再反汇编。
- 写模式 `-w` 与调试模式 `-d` 互斥选择，需要 patch 时用 `-w`，需要单步时用 `-d`。
- 对 PIE 程序，分析得到的是文件偏移；调试运行时按 `dm` 的映射加基址。

## 验证方式

对任意 ELF 执行 `r2 -q -c "aaa; afl; s main; pdf" ./bin`（`-q` 静默退出），应看到函数列表与 main 的反汇编；`r2 -q -c "izz~main" ./bin` 应列出含 main 的字符串行。
