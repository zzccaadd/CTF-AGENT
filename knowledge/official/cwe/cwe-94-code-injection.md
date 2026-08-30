---
source_url: https://cwe.mitre.org/data/definitions/94.html
source_title: "CWE-94: Improper Control of Generation of Code ('Code Injection')"
source_version: "4.20"
publisher: MITRE
license: MITRE CWE terms
retrieved_at: 2026-08-31
topic: code-injection
cwe_id: CWE-94
---
# CWE-94：代码注入

## 核心概念

不可信输入被拼接到代码片段或表达式中，由解释器（eval/exec、shell、模板引擎等）执行。攻击者注入自己的代码改变程序行为，典型后果是任意命令执行。与 CWE-78（OS 命令注入）的区别：CWE-94 注入的是被解释的"代码"，CWE-78 注入的是 shell 命令；两者常相伴出现。

## 关键细节

- 高危入口：`eval`/`exec`（Python/JavaScript/PHP）、`system`/`os.system`（shell 拼接）、模板引擎渲染不可信模板（SSTI）。
- 反面教材（Python）：

```python
expr = input("expression: ")
print(eval("2 + " + expr))   # eval 拼接用户输入 → 代码执行
```

- 变体：`os.system("ls " + user_path)` 属 shell 注入路径。
- SSTI 探测：模板渲染 `{{7*7}}` 输出 `49`，说明模板表达式被求值。
- 安全替代（Python）：

```python
import subprocess
subprocess.run(["ls", user_path])   # 列表参数传递，不使用 shell=True
```

- 规则：不 eval 用户数据；用白名单/解析器处理输入；模板引擎只渲染受信模板；避免字符串拼接命令行。

## 常见坑

- `subprocess` 加 `shell=True` 再拼字符串（Python 经典错误）。
- 黑名单过滤危险关键字可被编码、大小写、拼接绕过。
- 把模板/配置文件内容当普通字符串 eval。
- 只防护"直接入口"，忽略间接来源（请求头、文件名、Cookie 等进入 eval 的路径）。

## 验证方式

- 无害探测：SSTI 用 `{{7*7}}`、`${7*7}`；shell 场景用引号/分号/回显类指令观察差异。
- 代码审计 grep：`eval(`、`exec(`、`shell=True`、`system(`、`render_template_string`。
- 数据流确认：不可信输入是否可达任何执行点（eval/exec/模板渲染）。
