---
source_url: https://www.rfc-editor.org/rfc/rfc9110
source_title: RFC 9110 — HTTP Semantics
source_version: RFC 9110 (obsoletes RFC 7230-7235)
publisher: IETF
license: IETF Trust License
retrieved_at: 2026-08-31
topic: http
tool_name: http
---
# HTTP 协议要点

## 核心概念

HTTP/1.1 是无状态、基于请求-响应的文本协议，默认 80 端口明文。一次请求由请求行、请求头、空行、消息体四部分组成，请求行格式为 `METHOD SP request-target SP HTTP-version CRLF`。RFC 9110 定义的请求方法：GET、HEAD、POST、PUT、DELETE、CONNECT、OPTIONS、TRACE，另有 PATCH（RFC 5789）。请求方法决定语义：GET 无副作用，POST 提交数据，HEAD 只取响应头，OPTIONS 查询能力。

## 关键细节

- 状态码：1xx 信息、2xx 成功（200 OK）、3xx 重定向（301/302/307/308）、4xx 客户端错误（400/401/403/404/405/413）、5xx 服务端错误（500/502/504）。
- 必备头：HTTP/1.1 的 `Host` 必须存在；消息体长度由 `Content-Length` 或 `Transfer-Encoding` 描述，两者同时出现时以 `Transfer-Encoding: chunked` 为准。
- 分块编码（chunked）：每块为 `十六进制长度 CRLF 数据 CRLF`，以 `0\r\n\r\n` 结束，例如：

```
4\r\nWiki\r\n5\r\npedia\r\n0\r\n\r\n
```

- URL 编码：非 ASCII 与保留字符以 `%HH` 百分号编码，空格为 `%20`（查询串中亦可为 `+`），`%2e`、`%00` 等解码差异是绕过测试重点。
- Content-Type 常见值：`application/x-www-form-urlencoded`（`a=1&b=2`）、`application/json`、`multipart/form-data; boundary=...`（每段以 `--boundary` 分隔，文件以 `filename=` 标注）。
- 认证头：`Authorization: Basic base64(user:pass)`；Cookie 以 `Cookie: name=value; name2=value2` 传递，`Set-Cookie` 可带 `HttpOnly`、`SameSite`、`Secure` 属性。

## 常见坑

- 代理与后端对长度解析不一致会造成请求走私：先发一个 `Content-Length` 与 `Transfer-Encoding` 冲突的请求，观察后续请求是否被拼接进同一逻辑请求（CL.TE / TE.CL）。
- 路径归一化差异：`/../`、`//`、`/%2e%2e/`、`/.;/` 在不同中间件下处理结果不同，常用于绕过路由鉴权。
- `X-Forwarded-For`、`X-Real-IP`、`X-Forwarded-Host` 可被客户端伪造，服务端若仅信任这些头做 IP 判定即存在绕过。
- 响应头注入：未过滤的 CRLF（`%0d%0a`）可注入任意响应头，衍生缓存投毒；同样注意 `Content-Type` 反射导致的 XSS。

## 验证方式

`curl -v http://host/` 观察原始请求/响应头；`curl --path-as-is http://host/../` 禁止 curl 归一化路径；用 `nc host 80` 手工拼原始请求验证走私与注入；`curl -H "Content-Type: application/x-www-form-urlencoded" -d "a=1"` 对比不同编码方式的 body 差异。
