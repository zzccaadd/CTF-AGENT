---
source_url: https://cwe.mitre.org/data/definitions/89.html
source_title: "CWE-89: Improper Neutralization of Special Elements used in an SQL Command ('SQL Injection')"
source_version: "4.20"
publisher: MITRE
license: MITRE CWE terms
retrieved_at: 2026-08-31
topic: sql-injection
cwe_id: CWE-89
---
# CWE-89：SQL 注入

## 核心概念

不可信输入未经处理直接拼入 SQL 语句，改变了语句的语义结构。攻击者可绕过认证、读取/篡改任意表数据，在部分数据库上还能实现文件读写或命令执行（如 MySQL 的 LOAD_FILE/INTO OUTFILE、SQL Server 的 xp_cmdshell）。注入面由"字符串拼接位置"决定：WHERE 子句、ORDER BY、LIMIT、表名/列名等。

## 关键细节

- 典型错误拼接（反面教材）：

```python
cur.execute("SELECT * FROM users WHERE name='" + user + "' AND pass='" + pwd + "'")
```

  输入 `admin' -- `（MySQL 的 `--` 注释需尾随空格，或使用 `#`）可截断后续条件绕过认证。
- 联合查询探测：`' UNION SELECT 1,2,3-- `，逐步对齐列数后读取其他表。
- 盲注判定：布尔盲注比较 `' AND 1=1--` 与 `' AND 1=2--` 的响应差异；时间盲注在 MySQL 下用 `' OR SLEEP(5)--` 观察延迟。
- 修复：参数化查询/预编译语句：

```python
cur.execute("SELECT * FROM users WHERE name=?", (user,))
```

- 注释符差异：MySQL `-- `（需空格）与 `#`；Oracle/PostgreSQL 用 `--`。
- 自动化工具：`sqlmap -u "https://host/item?id=1" --batch`（仅限授权目标）。

## 常见坑

- 依赖字符串转义/魔术引号：历史上 PHP magic_quotes 已移除，转义方案常被编码绕过。
- ORM 的"原生 SQL / raw 查询"接口依旧可注入。
- 存储过程内部动态拼 SQL；先存储后拼接的二次注入。
- 只测引号报错，忽略不报错的盲注场景（数据库错误被吞掉时）。

## 验证方式

- 输入单引号 `'` 引发 SQL 语法错误为初步证据。
- 布尔/时间盲注与基准请求对比响应差异（可用 `curl` 计时观察 SLEEP 延迟）。
- 代码审计定位所有拼接 SQL 的点位，逐一改为参数绑定并复测。
