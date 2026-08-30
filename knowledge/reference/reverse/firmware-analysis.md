---
source_url: knowledge/reference/reverse/firmware-analysis.md
source_title: Firmware analysis and filesystem extraction — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: reverse
tool_name: binwalk
---

# 固件分析：binwalk 扫描与文件系统提取（通用模式）

> 从多份已审核 writeup 提炼的通用解法模式，不含具体题目内容。

## 核心概念

固件镜像通常是多段拼接：引导程序 + 内核 + rootfs（文件系统），其中 rootfs 多被压缩（gzip/zlib）或打包为特定格式（Squashfs/Cramfs/JFFS2/ext4/cpio），还可能带自定义头部或被整体加密。主流程：`file`/熵判断 → `binwalk` 扫描签名与偏移 → 按偏移切分/提取 → 解开文件系统 → 在文件系统内排查敏感文件。

## 关键细节

### 1. 扫描与提取

```console
$ file firmware.bin
$ binwalk firmware.bin               # 列出签名命中：偏移量 + 类型（Squashfs/gzip/...）
$ binwalk -Me firmware.bin           # 递归提取全部内容
```

- `-e` 按签名自动提取；`-M` 递归处理嵌套内容；签名不可靠时用 `-D '类型:脚本'` 自定义提取。
- 内部工具需要 root 权限时报错，就加 `--run-as=root`。
- 大偏移跳过：`dd if=firmware.bin of=rootfs.bin bs=1 skip=$((0x12345))`（`bs=1` 慢但偏移精确；大文件换算成 `bs=1024` 的块数）。

### 2. 解开文件系统

```console
$ unsquashfs rootfs.squashfs        # Squashfs（最常见）；失败换 sasquatch 解非标准版
$ jefferson rootfs.jffs2 -d out/    # JFFS2
$ 7z x rootfs.cpio                  # cpio；也可 cpio -idmv < rootfs.cpio
$ mount -o loop,ro rootfs.ext4 /mnt # ext4（需要权限；只读浏览可用 debugfs）
```

### 3. 熵与加密判断

```console
$ binwalk -E firmware.bin           # 按块打印熵，直观看到高熵区域
$ binwalk -A firmware.bin           # 文件类型指纹扫描
```

- 签名几乎无命中、熵图大面积接近 1.0 → 固件被整体压缩或加密；先找题目是否给出密钥/源码，不要凭空暴力。
- 自定义头：前 N 字节非标准 magic，`dd` 跳过头后再 `binwalk`/`file` 重新识别。

### 4. 提取后的排查

```console
$ strings -n 8 firmware.bin | grep -iE "pass|key|http|/etc/"
$ find extracted/ -type f | grep -iE "config|passwd|init|\.sh$"
```

启动脚本（`/etc/init.d/*`）、`passwd`/`shadow`、服务配置与内嵌证书/私钥是常见关注点；注意 busybox 环境里很多命令是符号链接。

## 常见坑

- **忘记 `--run-as=root` 或 `-M`**：提取失败或嵌套压缩未解开，先补这两个参数。
- **`unsquashfs` 报版本不支持**：非标准 Squashfs 换 `sasquatch`；Squashfs 4.0 需新版 squashfs-tools。
- **`dd` 偏移单位错**：实际跳过字节数 = `skip × bs`；只有 `bs=1` 时 skip 才是纯字节偏移。
- **只解了一层**：文件系统里可能还有第二层镜像（rootfs 内又打包了压缩包），递归解完再搜。
- **在未解压的整份固件上搜字符串**：明文在压缩层里，先解压再 `strings`。
- **熵全高不代表没救**：可能只是 zlib 流占大部分，签名被自定义头遮住，`dd` 跳过头再看。

## 验证方式

- 提取目录出现 `/bin /etc /usr /var` 等根目录结构，且 `unsquashfs`/`mount` 无报错。
- 在文件系统内找到的配置/密钥与固件实际运行行为能对上（如程序访问的地址/凭据）。
- `binwalk` 输出的偏移能精确重现切分点：`dd` 出的片段 `file` 类型与扫描结果一致。
