---
source_url: https://www.rfc-editor.org/rfc/rfc5280
source_title: RFC 5280 — Internet X.509 Public Key Infrastructure Certificate and CRL Profile
source_version: RFC 5280
publisher: IETF
license: IETF Trust License
retrieved_at: 2026-08-31
topic: x509
tool_name: openssl
---
# X.509 证书结构与解析

## 核心概念

X.509 证书是 CA 对「公钥 + 身份信息」的签名绑定，用 ASN.1 编码。DER 是二进制形式；PEM 是 DER 的 base64 加 `-----BEGIN CERTIFICATE-----` 壳。证书由三部分组成：tbsCertificate（被签名的主体）、signatureAlgorithm、signatureValue。自签名证书的 issuer 与 subject 相同，且用自己的私钥签名。

## 关键细节

- tbsCertificate 字段：version（v1/v2/v3 编码为 0/1/2）、serialNumber、signature（签名算法 OID）、issuer、validity（notBefore/notAfter）、subject、subjectPublicKeyInfo（算法 + 公钥）、可选 extensions。
- 时间编码：UTCTime（`YYMMDDHHMMSSZ`，仅 1950-2049）或 GeneralizedTime（`YYYYMMDDHHMMSSZ`）。
- 常用 OID：CN=2.5.4.3、O=2.5.4.10、rsaEncryption=1.2.840.113549.1.1.1、sha256WithRSAEncryption=1.2.840.113549.1.1.11、BasicConstraints=2.5.29.19、KeyUsage=2.5.29.15、SubjectAltName=2.5.29.17、CRLDistributionPoints=2.5.29.31。
- RSA 公钥信息：SEQUENCE 内的 modulus（2048 位约 256 字节）与 publicExponent；若同时持有私钥指数 d，可验证或直接重建签名。
- 关键扩展：BasicConstraints（`CA:TRUE` 标识 CA）、KeyUsage、ExtendedKeyUsage、SubjectAltName（SAN 中的 DNS/IP 条目）、AuthorityInfoAccess（OCSP 地址）。

## 常见坑

- PEM/DER 混用：openssl 可自动识别，但部分库严格区分格式，如 python `cryptography` 的 `load_der_x509_certificate` 读 PEM 会报错，需先 `serialization.load_pem_x509_certificate`。
- 序列号必须是正整数：DER 整数最高位为 1 时会带 0x00 前缀，手工解析时去掉前导零，否则按负数处理。
- SAN 优先于 CN（RFC 6125）：存在 SAN 时现代校验忽略 CN，只看 CN 判断域名会误判；反之校验实现只比 CN 会被 SAN 证书绕过。
- UTCTime 无世纪信息且上限 2049，跨世纪必须 GeneralizedTime；旧解析库可能把 GeneralizedTime 当 UTCTime 失败。
- 链不完整时报 `unable to get local issuer certificate`：把中间证书与叶子证书拼接成一个 bundle（`cat leaf.pem inter.pem > bundle.pem`）再验证。
- 有效期检查要同时看 notBefore/notAfter，只查过期时间会漏掉"尚未生效"的证书。

## 验证方式

`openssl x509 -in cert.pem -text -noout` 输出全部字段；`openssl asn1parse -in cert.der -inform DER -i` 逐层查看 ASN.1 结构；`openssl x509 -pubkey -noout -in cert.pem` 提取公钥；`openssl verify -CAfile ca.pem cert.pem` 验证信任链。python：`from cryptography import x509; cert=x509.load_pem_x509_certificate(open('cert.pem','rb').read())`，读取 `cert.serial_number`、`cert.not_valid_after_utc`、`cert.public_key()`、`cert.extensions.get_extension_for_oid(x509.SubjectAlternativeNameOID())`。
