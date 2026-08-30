---
source_url: https://docs.pwntools.com/en/stable/
source_title: pwntools documentation
source_version: "4.15.0"
publisher: Gallopsled / pwntools contributors
license: upstream project terms
retrieved_at: 2026-08-31
topic: exploit-development
tool_name: pwntools
---
# pwntools 进阶：ELF、ROP、assembly 与 shellcraft

## 核心概念

基础篇解决"连接与收发"，本篇覆盖 exploit 的核心构造层：`ELF` 对象解析符号与 GOT/PLT、`ROP` 对象自动化搜索 gadget 并组装链、`asm`/`disasm` 做架构级指令编解码、`shellcraft` 生成免手写 shellcode，以及 `fmtstr`、`cyclic`、`gdb.debug` 等配套模块。

## 关键细节

### ELF 对象

```python
from pwn import *
e = ELF("./bin")
e.symbols['main']          # 函数地址
e.got['puts']              # GOT 表项地址
e.plt['puts']              # PLT 桩地址（调用即跳 GOT）
e.address                 # PIE 基址（checksec 后可用）
e.bss()                   # bss 段可写地址
e.checksec()              # 打印保护（NX/PIE/RELRO/Fortify）
e.read(e.address, 4)      # 从进程映射读字节
e.search(b"/bin/sh")      # 返回字节序列迭代器
```

RELRO 关闭时 `e.got['puts']` 可直接覆写；`e.plt['puts']` 用于构造调用。`e.symbols` 对 strip 的程序为空，此时靠 `ROP` 对象按 `.got` 泄漏地址。

### ROP 链

```python
rop = ROP(e)
rop.puts(e.got['puts'])    # 调用 puts@plt 打印 GOT 中真实地址
rop.call('system', [next(e.search(b"/bin/sh"))])
rop.raw(0xdeadbeef)        # 手动塞字节/地址
print(rop.dump())          # 可视化链
payload = b"A"*offset + rop.chain()
```

`ROP(e)` 自动扫描 `__libc_csu_init` 的 pop 序列；`rop.find_gadget(['pop rdi','ret'])` 精确查找单 gadget，找不到时用 `csu` 传参。链上地址必须都是运行时真实地址，泄漏 libc 基址后要 `libc.address = leak - libc.symbols['puts']` 再重算。

### 汇编与反汇编

```python
context.arch = 'amd64'     # 或 'i386'/'arm'/'aarch64'，全局影响一切
asm('mov rax, 59; syscall')
asm('mov rax, 59; syscall', vma=0x1000)   # 指定基址（跳转相对寻址必需）
disasm(b'\x48\x31\xc0')    # 反汇编字节
```

`context` 还含 `context.os`、`context.endian`、`context.bits`。注意 `asm` 默认输出字节串，shellcode 里 `jmp` 类指令的偏移依赖 `vma`，不传会错。

### shellcraft

```python
shellcraft.sh()                              # 当前 arch 的 /bin/sh
shellcraft.i386.linux.sh()                   # 显式 arch/os
shellcraft.amd64.linux.execve('/bin/sh', 0)  # 自定义 execve
shellcraft.amd64.linux.cat('/etc/passwd')  # open+read+write 直读文件
asm(shellcraft.sh())                         # 得到字节串
```

`shellcraft` 是 `asm` 的模板库，常与 `asm()` 组合：`asm(shellcraft.sh())` 即完整 shellcode。seccomp 环境改选 `cat` 或 `open/read/write` 组合，避免直接 `sh`。

### 其他高频模块

```python
cyclic(200)                 # 生成 200 字节循环序列
cyclic_find(0x61616162)     # 由崩溃值反查偏移
fmtstr_payload(offset, {e.got['puts']: e.symbols['system']})  # 自动构造格式化串写
gdb.debug('./bin', 'b main')   # 拉起 gdb 调试当前进程
```

`cyclic_find` 参数是被覆盖的返回地址的值（小端序），不是偏移；`fmtstr_payload` 返回的 payload 直接送入 `%n` 类漏洞点。

## 常见坑

- `ROP` 对象默认按 `context.arch` 工作，忘记设 `context` 会按 x86_64 之外的默认值扫描，链地址全错。
- `e.address` 只有 PIE 二进制且 `checksec` 识别后才有意义，非 PIE 程序基址固定为加载地址。
- shellcode 中用到绝对地址（如 `movabs` 立即数）时与 `vma` 无关，但相对跳转依赖 `vma`，两者要分别对待。
- `shellcraft.cat()` 与直接 `shellcraft.sh()` 在禁 execve 的沙箱里行为不同，先确认 seccomp 再选。

## 验证方式

写最小脚本：`e = ELF('你的二进制'); print(hex(e.plt['puts']))` 应输出 PLT 地址；`asm('nop')` 应得到 `\x90`；`len(asm(shellcraft.sh()))` 应返回几十字节非零长度。
