---
source_url: https://www.rfc-editor.org/rfc/rfc8446
source_title: RFC 8446 — The Transport Layer Security (TLS) Protocol Version 1.3
source_version: RFC 8446
publisher: IETF
license: IETF Trust License
retrieved_at: 2026-08-31
topic: tls
tool_name: tls
---
# TLS 握手与证书验证要点

## 核心概念

TLS 在 TCP 之上提供机密性、完整性与身份认证。记录层每个记录为 `内容类型(1) 版本(2) 长度(2) 数据`；内容类型 20=change_cipher_spec、21=alert、22=handshake、23=application_data。握手消息类型：1=ClientHello、2=ServerHello、11=Certificate、12=ServerKeyExchange、14=ServerHelloDone、16=ClientKeyExchange、20=Finished。

## 关键细节

- TLS 1.2 握手（RFC 5246）：ClientHello → ServerHello → Certificate → ServerKeyExchange → ServerHelloDone → ClientKeyExchange → ChangeCipherSpec → Finished（双方各一次）。
- TLS 1.3 握手：ClientHello → ServerHello → EncryptedExtensions → Certificate → CertificateVerify → Finished（服务端批量发送），客户端随后发自己的 Finished；此后的握手与应用数据全部加密，pcap 中只剩密文记录。
- ClientHello 字段：legacy_version、random(32 字节，含 4 字节时间戳可选)、session_id、cipher_suites 列表、compression_methods、extensions（SNI、ALPN、supported_groups、key_share 等）。
- 证书链验证四要素：① 链顶锚定到本地受信任根 CA；② 每级证书由上一级私钥签名且签名算法匹配；③ 有效期（notBefore/notAfter）覆盖当前时间；④ 主机名匹配 SubjectAltName 的 DNS 条目（RFC 6125，现代实现不再匹配 CN）。
- 吊销检查：CRL（证书吊销列表）或 OCSP；OCSP stapling 由服务端握手时附带吊销状态。
- 常见弱配置：自签名证书、SHA-1 签名、1024 位 RSA、可导出密钥套件、会话复用且无前向保密。

## 常见坑

- TLS 1.3 在 ServerHello 后即加密，解密必须提供 keylog：tshark 加 `-o tls.keylog_file:keys.log`，客户端侧设 `SSLKEYLOGFILE` 环境变量（curl、Chrome、Firefox 均支持）。
- 证书报错要区分类别：`unable to get local issuer certificate` 是链不完整，`certificate has expired` 是有效期，`IP address mismatch` 是主机名问题，排查方向完全不同。
- 同一 IP 多站点靠 SNI 区分；ClientHello 扩展区 SNI 是明文，抓包可提取，但 TLS 1.3 的加密握手消息本身不可读。
- 只验有效期不验信任链的自研校验逻辑会被自签名证书直接绕过；只比 CN 不比 SAN 的校验会被 SAN 证书绕过。

## 验证方式

`openssl s_client -connect host:443 -servername host -showcerts` 查看完整链路与证书；`openssl s_client -brief` 输出概要；`tshark -r cap.pcap -Y "tls.handshake.type==1" -T fields -e tls.handshake.extensions_server_name` 提取 SNI；解密后 `-Y "tls.record.content_type==23"` 筛应用数据。降级测试用 `curl --tls-max 1.2 -v https://host/` 观察 TLS 1.2 握手细节。
