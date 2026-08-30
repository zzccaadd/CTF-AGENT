---
source_url: https://sourceware.org/gdb/current/onlinedocs/gdb.html/
source_title: GDB User Manual (Current)
source_version: current
publisher: Free Software Foundation / GDB project
license: GFDL
retrieved_at: 2026-08-31
topic: binary-analysis
tool_name: gdb
---
# GDB 进阶：断点、watchpoint、脚本与多线程

## 核心概念

GDB 是 GNU 源码级调试器，CTF 中用于动态分析 ELF 二进制：下断点观察关键函数、用 watchpoint 追踪内存被谁改写、用命令脚本和 Python 扩展实现半自动化分析，并处理 fork/线程下的执行流切换。

## 关键细节

### 断点（breakpoint）

```gdb
break main                 # 按符号下断点
break *0x40123c            # 按绝对地址（PIE 下需先算基址）
tbreak main                # 一次性断点，命中即删
rbreak puts                # 对所有名字含 puts 的函数下断点
break main if argc == 3    # 条件断点，满足条件才停
```

断点命中后的常用子命令：`continue`(c) 继续、`nexti`(ni) 单步指令、`stepi`(si) 单步并进入调用、`finish` 执行到当前函数返回、`info break` 列出断点、`disable`/`enable`/`delete` 管理断点。

在断点处批量执行命令用 `commands` 块，`silent` 抑制默认打印：

```gdb
break strcmp
commands
  silent
  printf "a=%s b=%s\n", $rdi, $rsi
  continue
end
```

### watchpoint

```gdb
watch *(long long*)0x404000   # 写入即停
rwatch  *(int*)0x404000       # 读取即停
awatch  buf                   # 读或写都停
```

watchpoint 依赖硬件寄存器，数量有限；对栈变量失效（栈帧销毁后地址无效）是常见问题，CTF 里优先 watch 全局变量或堆地址。

### 寄存器与内存

```gdb
info registers               # 全部寄存器
p $rdi                       # 打印单个寄存器
x/20gx $rsp                  # 从 rsp 起打印 20 个 8 字节十六进制
x/16wx $rsp                  # 4 字节一组
x/s 0x404020                 # 按字符串打印
```

格式字母：`x`(hex) `d`(signed dec) `u`(unsigned dec) `o`(oct) `t`(bin) `i`(指令) `s`(string) `f`(float)。

### 多线程与多进程

```gdb
info threads                 # 列出线程
thread 2                     # 切换到 2 号线程
thread apply all bt          # 对所有线程回溯
set scheduler-locking on     # 单步时只跑当前线程（默认 off 会让其他线程乱跑）
set follow-fork-mode child   # fork 后跟随子进程
set detach-on-fork off       # 父、子都可调试
info inferiors               # 进程列表
```

多线程程序单步时其他线程仍在执行，是"步过却看不到效果"的主因，先 `set scheduler-locking on`。

### 脚本化

批处理模式：`gdb -batch -x script.gdb ./bin`（不进入交互，配合 `info registers`、`printf` 可批量 dump 状态）。

Python 扩展（GDB 7.7+）：

```python
import gdb
gdb.execute("break main")
gdb.execute("run")
regs = gdb.execute("info registers", to_string=True)
val = int(gdb.parse_and_eval("*(long*)0x404000"))
```

`to_string=True` 把输出收进字符串而非打印，便于解析寄存器值。

## 常见坑

- PIE 程序里断点地址必须等于 `加载基址 + 文件内偏移`，基址在 `start` 或 `_start` 断点处用 `info files` 的 Entry point 与 `0x400000` 之差推算。
- 对栈地址下 watchpoint 会随帧销毁失效；对寄存器值下 watch 只对内存有效。
- `set disable-randomization on` 默认开启才能复现固定地址（Linux 上需 ptrace 权限）。
- ASLR 下 `gdb` 内 `run` 与 `start` 的加载基址可能不同，用 `start` 而非 `run` 统一入口。

## 验证方式

对自带 `main` 的二进制执行 `gdb -batch -ex "break main" -ex "run" -ex "info registers rdi" ./bin`，应输出 `Breakpoint 1, main (...) at ...` 及 `rdi` 的值；`info threads` 在线程程序上应列出 `LWP` 条目。
