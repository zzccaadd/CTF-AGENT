---
source_title: Sandbox execution rules — project internal notes
source_version: "1.0"
publisher: CTF-Agent project
license: project internal
retrieved_at: 2026-08-31
topic: internal-operations
---

# 沙箱运行规则（项目内部说明）

## 目录约定

- 所有题目文件在 `/challenge/` 下：`/challenge/distfiles/`（原始附件，只读）、`/challenge/workspace/`（工作目录，可写）。
- 禁止使用 `/challenge/` 之外的任何主机路径；sandbox 与宿主机文件系统隔离。

## 网络

- `allow_internet=false` 时（benchmark 默认）：通用互联网与外部 webhook 被禁用；只能连接题目服务（如 `127.0.0.1:1337` 或题目提供的连接信息）。
- 不要假设题目服务一定在本机；连接信息以题目描述为准。

## 执行语义

- **每次 `bash` 调用都是新进程**：变量、cwd 不跨调用保留；需要状态时写文件或用 heredoc 一次发多条命令。
- 连接 TCP 服务建议：`nc 127.0.0.1 <port> <<'EOF' ... EOF`，或用 Python `socket`/pwntools 写有状态脚本。
- 命令有超时（默认 60s）和输出上限；长输出先写文件再按需查看。

## 已安装工具（常用）

- Python3、pwntools、gdb、radare2（`r2`）、angr、capstone、pyghidra（反编译，见提示词示例）、steghide、exiftool、zsteg、strings/xxd/objdump/readelf（binutils）。
- Crypto：RsaCtfTool、sage（ECM）、cado-nfs（大数分解）按提示词说明使用。
- 不确定某工具是否可用时，先 `which <tool>` 再使用，不要假设。

## 通用规则

- 先用最小命令确认环境（`pwd`、`ls`、`file`、`checksec` 相关），再展开分析。
- 容器内存有上限（benchmark 默认 4g/题）：避免一次性读取超大文件或无限循环。
- 本题的观测结果只属于本题 run；不要把栈地址、payload、flag 写回通用知识库。
