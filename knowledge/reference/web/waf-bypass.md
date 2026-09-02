---
source_url: knowledge/reference/web/waf-bypass.md
source_title: WAF bypass 与请求走私 — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-09-02
topic: web
keywords_en: WAF bypass, web application firewall, request smuggling, encoding bypass, case bypass, comment injection, 防火墙绕过
---

# WAF 绕过（通用模式）

> 从多份已审核 writeup 提炼的通用解法模式，不含具体题目内容。

## 核心概念

WAF（Web 应用防火墙）用规则集匹配请求特征（关键字、正则、签名、频率）来拦截攻击流量。
绕过的本质：**让 WAF 看到与后端不一致的请求**——WAF 与后端在解析、解码、归一化上的差异
就是绕过面。先判断 WAF 类型（规则引擎 vs 语义引擎）与部署位置（反向代理 / 云防护），再选绕过面。

## 关键细节

### 1. 编码差异（最常用）

后端解码链比 WAF 多一步或多一层，WAF 匹配原始字节而后端解码后执行：

```text
URL 编码:      /admin -> /%61dmin          (后端先 URL-decode)
双重编码:      %2527 -> %27 -> '          (双层解码链)
Unicode:      /admin -> /%u0061dmin       (IIS 风格)
HTML 实体:    &#x27;  (在反射型场景)
```

测试方法：对 payload 逐字符尝试 URL/Unicode/双重编码，观察后端行为差异。

### 2. 大小写与关键字混淆

- 大小写混合：`SeLeCt`、`<ScRiPt>`（WAF 大小写敏感时）。
- 关键字内插注释/空白：`SEL/**/ECT`、`UNION%0aSELECT`、`/**/OR/**/1=1`。
- 等价关键字替换：`information_schema.tables` → `sys.tables`（MSSQL）、
  `concat()` → `concat_ws()`，布尔盲注用 `a=b` vs `a<>b` 绕 `=` 过滤。
- 空字节截断（老式）：`%00`。

### 3. 协议层绕过

- **参数污染 (HPP)**：`?id=1&id=2'`——后端取最后一个（或第一个）参数，WAF 只检查第一个。
- **Content-Type 混淆**：`application/x-www-form-urlencoded` ↔ `multipart/form-data` 切换
  （WAF 只解析一种）；JSON body（`application/json`）绕过只解析表单的 WAF。
- **方法切换**：`GET`/`POST`/`PUT`/`HEAD` 规则集覆盖不同；`HEAD` 常被漏检。
- **请求走私**：`Content-Length` vs `Transfer-Encoding: chunked` 不一致，前端 WAF 按一个
  解析、后端按另一个——构造走私请求把 payload 藏进 WAF 看不到的分块。

### 4. 应用层语义绕过

- 用合法功能构造攻击：`ORDER BY` 后的表达式、JSONPath/GraphQL 变量、XML 外部实体替代 SQL 注释。
- 分段拼接：payload 拆成多个参数/请求，后端拼接后生效。
- 触发点错位：攻击面在 WAF 不监控的端点（静态文件、API 版本前缀、大小写路径）。

## 验证方式

1. 先发无害探测请求确认 WAF 存在与拦截特征（403/HTML 页/特定 header）。
2. 对每种绕过面构造变体，逐个对比响应差异（拦截 vs 放行 vs 后端报错）。
3. 确认放行后再验证后端**确实执行**了 payload（响应差异/时间差/报错信息）。
4. 记录哪种变体放行且生效——后续利用全用该变体。

## 常见坑

- 绕过 WAF ≠ 利用成功：放行后还要保证后端语义正确。
- 双重编码要确认后端解码层数，多试一层可能破坏 payload。
- HPP 的后端取值顺序因框架而异（PHP 取最后、ASP.NET 取第一个），先探测。
