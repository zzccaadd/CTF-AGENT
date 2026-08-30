---
source_url: https://www.rfc-editor.org/rfc/rfc6455
source_title: RFC 6455 — The WebSocket Protocol
source_version: RFC 6455
publisher: IETF
license: IETF Trust License
retrieved_at: 2026-08-31
topic: websocket
tool_name: websocket
---
# WebSocket 握手与帧格式

## 核心概念

WebSocket 借助 HTTP Upgrade 机制在 TCP 上建立全双工消息通道。连接始于一个普通 HTTP GET，服务端返回 101 后协议切换为二进制帧流。所有多字节字段按网络字节序；关键约束：客户端发往服务端的帧必须置 MASK 位，服务端到客户端的帧禁止置 MASK 位。

## 关键细节

- 握手请求：

```
GET /chat HTTP/1.1
Host: example.com
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==
Sec-WebSocket-Version: 13
```

- 服务端计算 `Sec-WebSocket-Accept = base64(SHA1(Sec-WebSocket-Key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"))`，在 `101 Switching Protocols` 响应中返回。RFC 示例 key `dGhlIHNhbXBsZSBub25jZQ==` 对应 accept `s3pPLMBiTxaQ9kYGzzhZRbK+xOo=`。
- 帧头：FIN(1bit)、RSV1-3(3bit)、opcode(4bit)、MASK(1bit)、payload length(7bit)。长度 <126 直接使用；=126 表示后随 2 字节 16 位长度；=127 表示后随 8 字节 64 位长度。MASK=1 时随后跟 4 字节掩码密钥，再是负载。
- opcode：0x0 延续帧、0x1 文本、0x2 二进制、0x8 关闭、0x9 ping、0xA pong。分片消息除最后一片 FIN=1 外其余 FIN=0，分片之间不得插入其他类型帧。
- 掩码规则：`payload[i] ^= mask[i % 4]`。关闭帧负载为 2 字节状态码：1000 正常、1001 离开、1002 协议错误、1003 不可接受数据、1008 策略违规。

## 常见坑

- 手工构造客户端帧最易漏掉掩码：客户端未掩码的帧会被服务端判定非法并关闭连接；反向服务端帧带 MASK 同样非法。
- `Sec-WebSocket-Key` 是 16 字节随机数的 base64，服务端校验的是 SHA1 摘要而非 key 本身，只改 key 不重算 accept 握手必然失败。
- 浏览器自动处理 ping/pong 与掩码，脚本客户端需自行实现；长时间无消息时服务端可能主动 ping 保活，脚本需响应 pong。
- Wireshark 对已识别的 WebSocket 流自动解码（过滤 `websocket`），但 TLS 包裹或缺少握手上下文的抓包中看不到明文帧。

## 验证方式

`tshark -r cap.pcap -Y "websocket" -T fields -e websocket.opcode -e websocket.payload` 查看帧；交互测试用 `websocat ws://host/path`；复核 accept：

```
python3 -c "import base64,hashlib; k=base64.b64decode(b'dGhlIHNhbXBsZSBub25jZQ=='); print(base64.b64encode(hashlib.sha1(k+b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest()).decode())"
```

输出应为 `s3pPLMBiTxaQ9kYGzzhZRbK+xOo=`；python `websockets` 库（asyncio）适合写自动化客户端。
