---
source_url: https://www.rfc-editor.org/rfc/rfc793
source_title: RFC 793 — Transmission Control Protocol
source_version: RFC 793 (with RFC 1122 errata)
publisher: IETF
license: IETF Trust License
retrieved_at: 2026-08-31
topic: tcp-ip
tool_name: tcp
---
# TCP/IP 基础

## 核心概念

TCP 提供面向连接、可靠、字节流的传输服务，运行于 IP 之上。可靠性与有序性由序号（seq）和确认号（ack）保证：seq 是本段首字节序号，ack 是期望收到的下一个字节序号（即对端 seq+1）。TCP 段头部最小 20 字节，段内无长度字段，边界由 IP 层总长度推导。

## 关键细节

- 三次握手：客户端 `SYN(seq=x)` → 服务端 `SYN+ACK(seq=y, ack=x+1)` → 客户端 `ACK(ack=y+1)`。确认号恒为对端 seq+1，即使该段无数据。
- 四次挥手：FIN → ACK → FIN → ACK；FIN 也占一个序号，所以最后一次 ACK 后还要等待 TIME_WAIT。
- 标志位（9 位）：NS、CWR、ECE、URG、ACK、PSH、RST、SYN、FIN。RST 异常中断连接，PSH 提示立即交付，URG 配合紧急指针使用。
- TCP 头字段：源端口(16)、目的端口(16)、seq(32)、ack(32)、数据偏移(4bit，单位 4 字节)、保留(3bit)、Flags(9bit)、窗口(16)、校验和(16)、紧急指针(16)；选项区常见 MSS、SACK、时间戳。
- 端口分类：0-1023 知名端口（22 SSH、53 DNS、80 HTTP、443 HTTPS、3306 MySQL、5432 PostgreSQL、6379 Redis），1024-49151 注册端口，49152-65535 动态端口。
- 校验和：对伪头部（源 IP、目的 IP、协议号 6、TCP 总长度）+ TCP 头 + 数据按 16 位字累加取反；伪头部需要 IP 层信息，因此校验和验证必须结合 IP 头。

## 常见坑

- 抓包中绝对 seq/ack 与预期不符多因丢包重传或 SACK 选项，分析时用相对序号（relative sequence number）而非绝对序号。
- SYN 扫描只发 SYN，收到 SYN+ACK 即开放、RST 即关闭；全连接扫描会留下完整握手记录，隐蔽性差。
- 单独解出 TCP 段无法验证校验和，因为伪头部依赖源/目的 IP；工具报 checksum 错误常见于采集卡 offload，不代表数据真被改。
- seq 预测、Tiny fragment、RST 注入等攻击都建立在标志位与序号语义上，读 pcap 先确认握手是否完整、有没有异常重传。

## 验证方式

`tshark -r cap.pcap -Y "tcp.flags.syn==1" -T fields -e tcp.seq -e tcp.ack -e tcp.srcport -e tcp.dstport` 提取握手序列；`tcpdump -nn -i lo port 4444 -c 10` 实抓验证；`nc -lvnp 4444` 监听 + `nc -nv 127.0.0.1 4444` 连接观察三次握手；scapy：`sr1(IP(dst="host")/TCP(dport=80,flags="S"))` 构造 SYN 探测，看响应标志位。
