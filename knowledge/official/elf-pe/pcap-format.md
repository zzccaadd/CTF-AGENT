---
source_url: https://wiki.wireshark.org/Development/LibpcapFileFormat
source_title: Libpcap File Format（Wireshark Wiki）
source_version: 当前版本（对应 libpcap 1.x）
publisher: Wireshark Foundation
license: Wireshark Wiki 内容许可
retrieved_at: 2026-08-31
topic: pcap-format
tool_name: tshark, tcpdump, capinfos, scapy
---

# pcap / pcapng 文件格式技术卡片

## 核心概念

- pcap：24 字节全局头 + 若干记录（每条 16 字节包头 + 包数据）。
- pcapng：块结构，每块以（Block Type + 块总长）开头、以同样的块总长结尾，便于跳过未知块。常用块：SHB 节头块（`0x0A0D0D0A`）、IDB 接口描述块（`0x00000001`）、EPB 增强包块（`0x00000006`）、SPB 简单包块（`0x00000003`）、ISB 接口统计块（`0x00000005`）、NRB 名字解析块（`0x00000004`）。

## 关键细节

- pcap 全局头：magic(4)、version_major=2、version_minor=4、thiszone(4, 通常 0)、sigfigs(4)、snaplen(4)、network/linktype(4)。
  - magic `0xa1b2c3d4` = 微秒时间戳，`0xa1b23c4d` = 纳秒时间戳。
  - 字节序判定：把前 4 字节按小端读出，若得 `0xa1b2c3d4`/`0xa1b23c4d` 则全文件为小端；若得 `0xd4c3b2a1`/`0x4d3cb2a1` 则文件为大端，所有字段按大端解析。
- 记录头：ts_sec(4)、ts_usec(4)、incl_len(4, 实际存储长度)、orig_len(4, 原始长度)；`incl_len < orig_len` 表示被 snaplen 截断。
- linktype 常见值：1 = Ethernet、101 = 裸 IP（RAW）、105 = IEEE 802.11、119 = Linux cooked。
- pcapng SHB：Byte-Order Magic `0x1A2B3C4D`（判端序）、Major(1)/Minor(0)、Section Length；IDB 含 linktype 与 snaplen；EPB 记录头：Interface ID(4)、Timestamp High(4)/Low(4)（单位默认 10⁻⁶ 秒，可由 if_tsresol 选项修改）、CapLen(4)、PacketLen(4)、数据、选项。
- 常用命令：`capinfos a.pcap`（端序/版本/接口/时长/链路类型）；`tshark -r a.pcap -Y 'tcp'` 过滤显示；`tcpdump -r a.pcap -nn -vvv` 详细输出；scapy：`pkts = rdpcap('a.pcap')` 返回包列表，`wrpcap('b.pcap', pkts)` 写回。

## 常见坑

- 端序必须先按 magic 判定：pcap 各字段端序跟随写入机而非当前主机，端序读错会导致时间戳、长度全乱。
- pcap 记录之间没有分隔签名，解析完全依赖 incl_len；一条记录损坏后后续全部错位，逐条按 incl_len 前进可恢复。
- pcapng 一个文件可有多个 IDB（多接口），EPB 的 Interface ID 对应第几个 IDB，不能假定单接口。
- 截断包（incl_len < orig_len）缺少完整负载，做流重组或解密前先 `capinfos` 看 snaplen。
- 时间戳单位：pcap 固定为微秒/纳秒（由 magic 决定）；pcapng 由 if_tsresol 选项决定（默认 10⁻⁶ 秒），换算差值时不要混用。

## 验证方式

- `capinfos a.pcap` 输出端序、链路类型与时间戳分辨率；`tshark -r a.pcap -c 1 -V` 查看首包逐层解析结果；scapy 读取后比较 `len(pkt)` 与记录头中的 orig_len 是否一致。
