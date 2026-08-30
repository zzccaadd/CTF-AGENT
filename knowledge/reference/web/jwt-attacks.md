---
source_url: knowledge/reference/web/jwt-attacks.md
source_title: JWT 攻击模式（算法混淆/弱密钥/伪造）— reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: web
cwe_id: CWE-347
---

# JWT 攻击模式（算法混淆 / 弱密钥 / 伪造）

> 本文为通用技术模式卡片，不含任何具体题目的 flag、附件路径、端点地址或原始 payload。

## 核心概念

JWT 由三段 base64url 拼接：`header.payload.signature`。签名算法由 header 中 `alg` 声明，**服务端常直接信任 header 的算法声明**——这是多数攻击的根因。常见攻击面：`alg:none`、HS256/RS256 算法混淆、弱 HMAC 密钥爆破、`kid`/`jku`/`x5u` 注入、`exp` 过期校验缺失、payload 权限字段篡改。

## 关键细节

**结构解析**（base64url 无 padding，`-`/`_` 替代 `+`/`/`）：
```
header:  {"alg":"HS256","typ":"JWT"}
payload: {"sub":"alice","role":"user","exp":1735689600}
signature: HMAC-SHA256(secret, base64url(header)+"."+base64url(payload))
```
本地用 python 验签：`jwt.decode(token, key, algorithms=['HS256'])`（pyjwt）；或 `python -c` 用 `base64.urlsafe_b64decode` 逐段解码先看内容。

**alg:none**（旧库接受）：
```json
{"alg":"none","typ":"JWT"}
```
第三段签名为空即可；变体大小写 `None`/`NONE`/`nOnE` 也常被接受。pyjwt 需显式 `jwt.encode(payload, key='', algorithm='none')` 生成。

**算法混淆（HS256/RS256）**：
- 服务端用 RSA 公钥验 RS256，攻击者把 header 改为 `{"alg":"HS256"}`，并用**服务端公钥本身**作为 HMAC 密钥签名——若库未区分密钥类型即通过。
- 前提：拿到公钥（常见于 JWKS 端点、`.well-known/jwks.json`、或随题目给出的 PEM 文件）。
- 注意密钥长度：HMAC 对任意长度密钥可用，直接 `jwt.encode(payload, public_key_pem, algorithm='HS256')`。

**弱密钥爆破**（HS256）：
```bash
hashcat -m 16500 token.txt wordlist.txt
john token.txt --format=HMAC-SHA256 --wordlist=wordlist.txt
```
常见弱密钥：`secret`、`password`、`123456`、`admin`、项目名/题目名；也可在源码、注释、配置文件里找。

**kid / jku / x5u 注入**：
- `kid`（Key ID）被当作文件名/查表键：`{"kid":"../../../../etc/passwd"}` 路径穿越读文件；若库把文件内容当密钥，指向攻击者可控制内容的路径即等于自定义 HMAC 密钥。
- `jku`（JWK Set URL）：服务端拉取攻击者提供的 JWKS → 用攻击者私钥签的 token 被信任（前提：服务端未固定可信源）。
- 篡改 `exp`：把过期时间改成未来或直接删除，若服务端不校验即绕过。

**payload 篡改**：解码改 `role`/`admin`/`user_id`/`sub` 后用已知/爆破出的密钥重新签名；无密钥时配合 none 或混淆。

## 常见坑

- base64url 不是标准 base64：先替换 `-`→`+`、`_`→`/` 并补 `=`，直接用标准 base64 解码会出错。
- alg:none 在 pyjwt 新版本默认拒绝；服务端语言/版本未知时 none 与混淆都要试。
- 算法混淆只在服务端**不校验 key 类型**时生效；部分库（如 Java jjwt 0.9.x）`alg` 取 header 的才可混淆。
- RSA 私钥泄露 ≠ 公钥混淆：混淆用的是公钥内容做 HMAC 密钥，不是私钥。
- 弱密钥爆破前确认算法是 HS256；RS256 爆破无意义。
- 有些服务把 JWT 放 Cookie 而非 Authorization 头，Cookie 的 `HttpOnly`/`Secure` 属性不影响验证逻辑但影响窃取方式。

## 验证方式

1. 用 jwt.io 或本地解码确认三段内容与当前 `alg`。
2. 依序尝试：`alg:none` → payload 篡改 + 弱密钥爆破 → 算法混淆（需先拿到公钥）→ kid/jku 注入。
3. 每次修改后用目标接口验证 401/200 变化，确认服务端确实校验签名而非只解析 payload。
4. 爆破命令先在本地生成已知密钥的 token 验证 hashcat/john 格式无误，再对目标执行。
