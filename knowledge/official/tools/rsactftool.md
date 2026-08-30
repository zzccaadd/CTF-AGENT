---
source_url: https://github.com/RsaCtfTool/RsaCtfTool
source_title: RsaCtfTool repository
source_version: current
publisher: RsaCtfTool contributors
license: MIT
retrieved_at: 2026-08-31
topic: cryptography
tool_name: rsactftool
---
# RsaCtfTool 常见攻击模式

## 核心概念

RsaCtfTool 是聚合型 RSA 攻击工具：给定公钥（PEM/DER/公钥文件/裸 n,e）与密文，自动尝试多种攻击（Wiener、Fermat、低指数、共同模数、Factordb 查询等）。CTF 用法核心是正确喂入 `--publickey`/`-n -e` 与 `--uncipherfile`/`--uncipher`，并读懂输出的恢复结果。

## 关键细节

### 基本调用

```bash
# 公钥文件 + 密文文件
python3 RsaCtfTool.py --publickey key.pub --uncipherfile cipher.enc

# 直接给 n, e 与密文（十六进制）
python3 RsaCtfTool.py -n 0x9c1f... -e 0x10001 --uncipher 0x1234...

# 只恢复私钥
python3 RsaCtfTool.py --publickey key.pub --private

# 查看公钥解析结果（n、e、位数）
python3 RsaCtfTool.py --publickey key.pub --dumpkey
```

成功恢复时输出形如：

```
[+] Clear text : b'...'
[+] Private key :
-----BEGIN RSA PRIVATE KEY-----
...
-----END RSA PRIVATE KEY-----
```

### 指定攻击

```bash
python3 RsaCtfTool.py --publickey key.pub --uncipherfile c.bin --attack wiener
python3 RsaCtfTool.py --publickey key.pub --uncipherfile c.bin --attack fermat
python3 RsaCtfTool.py --publickey key.pub --attack factordb
```

- `wiener`：d 较小（约 n^0.25 量级）时用连分数恢复 d。
- `fermat`：p、q 很接近时，从 sqrt(n) 附近枚举差平方。
- `factordb`：n 已在 FactorDB 收录时直接查分解（需联网，且默认攻击列表包含它）。
- 低指数广播攻击：多组 (n, c) 同 e 时用 `--attack hastad` 或组合 CRT，工具自带相关攻击项。

`--verbose` 打印每步尝试的攻击与中间量，排查"全失败"时必开。

### 工具自带公钥/密文格式

```bash
# 直接给裸整数
-n 12345 -e 65537 --uncipher 6789
# 十六进制前缀 0x
-n 0x00c1... -e 0x010001
```

大数建议用 `--dumpkey` 先确认工具读到的 n/e 与题目一致（常见错误：e 写反、密文贴错、大端小端反）。

## 常见坑

- 公钥文件必须是合法 PEM/DER；直接拿 `n,e` 时十六进制带 `0x` 前缀，且 e 通常为 0x10001（65537），不要漏高位 0x01。
- 密文文件是二进制还是 hex 文本要分清：hex 文本用 `--uncipher` 传十六进制串（可带 0x），二进制文件用 `--uncipherfile`。
- 攻击全失败不一定是"无解"：可能是密文用了 RSA 变体（如 Rabin、多素数、共模），需要换工具或手写，先看 `--verbose` 输出再下结论。
- 结果明文的头尾 `b'...'` 可能含不可打印字节或填充，打印不全时用 `-o out` 落盘再看。

## 验证方式

用 `openssl genrsa -out k.pem 512 && openssl rsa -in k.pem -pubout -out pub.pem` 生成测试密钥，`python3 RsaCtfTool.py --publickey pub.pem --dumpkey` 应输出与 `openssl rsa -in k.pem -text -noout` 一致的 n/e 与位数；再加密一条短消息跑 `--uncipher` 应还原原文。
