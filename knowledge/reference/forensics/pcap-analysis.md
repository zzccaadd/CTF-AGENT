---
source_url: knowledge/reference/forensics/pcap-analysis.md
source_title: pcap traffic analysis — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: forensics
tool_name: tshark
---

# pcap 流量分析（通用模式）

> 从多份已审核 writeup 提炼的通用解法模式，不含任何具体题目的端点地址或附件内容。

## 核心概念

抓包分析围绕三件事：**过滤**（用显示过滤器定位可疑协议与流）、**重组**（把分片的 TCP 会话拼回完整请求/响应）、**导出**（从 HTTP/FTP/SMB 等会话中取出传输的文件）。多数题目的 flag 藏在某次上传/下载的文件、表单密码、或 DNS/ICMP 外带通道里。

## 关键细节

1. **概览与过滤**：
   - `capinfos file.pcap`：包数、时长、文件类型（pcap/pcapng）。
   - `tshark -r file.pcap -Y "http.request" -T fields -e http.request.uri`：只看 HTTP 请求行。
   - 常用过滤器：`dns`、`ftp`、`ftp-data`、`tcp.stream eq 0`、`dns.qr==0`、`icmp`、`tls.handshake`。
2. **会话重组**：
   - `tshark -z follow,tcp,ascii,0 -r file.pcap`：以 ASCII 跟随 0 号 TCP 流（改 `hex` 看二进制）。
   - `tcpflow -r file.pcap -o out/`：把每条 TCP 流按方向拆成独立文件，便于 `file`/`strings` 检查。
3. **导出对象**（传输的文件）：
   - `tshark -r file.pcap --export-objects http,out/`，同理可导出 `ftp`、`smb` 对象。
   - 导出后逐一 `file` 与 `sha256sum`，找压缩包/图片/脚本。
4. **DNS 外带**：`tshark -r file.pcap -Y "dns.qr==0" -T fields -e dns.qry.name | sort -u` 收集查询域名，去掉固定后缀后按 base32/base64/hex 解码。
5. **USB HID 键盘**：`tshark -r file.pcap -Y "usb.capdata" -T fields -e usb.capdata` 取出按键字节流，用 USB HID usage 表把第二字节映射为字符（注意大写/Shift 修饰键）。
6. **TLS 解密**：拿到 `(pre)-master-secret` 日志时 `tshark -r file.pcap -o tls.keylog_file:keys.txt`，再配合 `-Y "http"` 查看解密后的明文 HTTP。

## 常见坑

- 忘记区分 pcap/pcapng：先 `file file.pcap`，工具大多两者兼容，但偏移类手工操作要按实际格式来。
- TCP 数据分片/乱序时直接 grep 会漏内容：必须经 `follow`/`tcpflow` 重组后再分析。
- `--export-objects` 只对 HTTP/FTP/SMB 等有会话对象语义的协议生效，裸 TCP 传文件要用 follow/tcpflow。
- DNS 外带的域名常被工具截断或小写化，解码前先恢复原始大小写。
- 多个同名文件（多次下载）时按 `tcp.stream` 号区分，避免取错版本。

## 验证方式

- 导出的文件通过 `file` 识别且可正常解压/打开；关键请求与响应能一一对应到同一 `tcp.stream`。
- 解码结果（密码、文件名、外带数据）整段可读，并与包内其他线索（如用户代理、时间戳）自洽。
