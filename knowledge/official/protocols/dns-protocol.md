---
source_url: https://www.rfc-editor.org/rfc/rfc1035
source_title: RFC 1035 — Domain Names - Implementation and Specification
source_version: RFC 1035
publisher: IETF
license: IETF Trust License
retrieved_at: 2026-08-31
topic: dns
tool_name: dns
---
# DNS 报文结构

## 核心概念

DNS 是域名与资源记录间的分布式映射协议，默认 UDP/53；报文超过 512 字节或进行区域传送时走 TCP/53。报文分五段：Header（固定 12 字节）、Question、Answer、Authority、Additional。所有多字节整数按网络字节序（大端）编码，解析时必须逐位拆字段。

## 关键细节

- Header 12 字节布局：ID(16bit)、Flags(16bit)、QDCOUNT、ANCOUNT、NSCOUNT、ARCOUNT（各 16bit）。
- Flags 位：QR(1bit，0=查询 1=响应)、Opcode(4bit，0=QUERY)、AA(权威应答)、TC(截断)、RD(递归期望)、RA(递归可用)、Z(3bit 保留)、RCODE(4bit：0=NOERROR、1=FORMERR、2=SERVFAIL、3=NXDOMAIN、4=NOTIMP、5=REFUSED)。
- Question 段：QNAME 是长度前缀标签序列，如 `03www05baidu03com00`；随后 QTYPE(16bit)、QCLASS(16bit，1=IN)。
- 记录类型：A=1、NS=2、CNAME=5、SOA=6、PTR=12、MX=15、TXT=16、AAAA=28、SRV=33、AXFR=252（区域传送）。
- 资源记录 RDATA 因类型而异：A 为 4 字节 IPv4，AAAA 为 16 字节 IPv6，TXT 为 1 字节长度前缀 + 字符串，MX 为 2 字节优先级 + 域名。
- 名称压缩指针：标签首两比特为 `11` 时低 14 位是相对报文起始处的偏移，`c00c` 表示跳到偏移 12 处继续读域名。

## 常见坑

- 解析 QNAME 遇压缩指针要跳转并在原位置继续（指针后常紧跟 QTYPE），循环跳转超过两次即应终止，防止自引用死循环。
- TXT 记录可存放任意文本，是 DNS 外带数据（exfiltration）的常见载体，读每条 TXT 时注意前面 1 字节长度，多段字符串要拼接。
- 区域传送 AXFR 若未限制来源即配置漏洞，`dig @ns.example.com example.com axfr` 可一次拉取全部记录，泄露内部主机名。
- RCODE=3（NXDOMAIN）只表示该名字不存在；通配符 `*.example.com` 会让任意子域名都返回记录，枚举时注意区分。
- 请求 ID 只有 16 位，且固定源端口时易被伪造响应投毒；抓包时按 ID 对应查询与响应。

## 验证方式

`dig @8.8.8.8 example.com A +noall +answer` 只看答案；`dig example.com TXT` 看 TXT 记录；`dig +trace` 跟踪解析链；`tshark -r cap.pcap -Y "dns.flags.response==1"` 筛响应。python 用 dnspython：`import dns.resolver; dns.resolver.resolve("example.com","TXT")`；scapy 构造：`sr1(IP(dst="8.8.8.8")/UDP(dport=53)/DNS(rd=1,qd=DNSQR(qname="example.com")))`。
