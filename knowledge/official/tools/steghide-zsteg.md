---
source_url: https://github.com/zed-0xff/zsteg
source_title: zsteg repository
source_version: current
publisher: zed-0xff
license: MIT
retrieved_at: 2026-08-31
topic: steganography
tool_name: zsteg
---
# steghide / zsteg 隐写提取用法

## 核心概念

两类图片隐写提取工具：`steghide` 用于其自有格式的隐写（JPEG/BMP/WAV/AU 载体，需要口令，无口令时回车跳过）；`zsteg` 面向 PNG/BMP 的 LSB 类隐写，自动检测各种位平面与通道组合，一条命令往往直接出结果。

## 关键细节

### steghide

```bash
steghide info carrier.jpg          # 探测：是否嵌入了数据，能否解密
steghide extract -sf carrier.jpg   # 交互式输入口令后提取（无口令直接回车）
steghide extract -sf carrier.jpg -p ""    # 非交互：空口令
steghide extract -sf carrier.jpg -p mypass -xf out.txt   # 指定口令与输出文件
```

`info` 成功时显示 `embedded file "data.txt": size: 123 bytes` 之类信息；提取成功打印 `wrote extracted data to "data.txt"`。口令错误或未嵌入数据时报 `could not extract any data`。注意 `-p ""` 表示空口令，与"回车无口令"等价，是脚本化时必须的写法。

### zsteg

```bash
zsteg image.png              # 全自动：列出所有候选通道与检测到的数据
zsteg -a image.png           # 穷举更多位平面组合（慢）
zsteg -E "b1,rgb,lsb,xy" image.png   # 提取指定平面的裸数据（E = extract）
zsteg -b 1 image.png         # 指定位深（默认尝试多个）
zsteg -o xy image.png        # 指定顺序：xy（行优先）或 yx
zsteg -v image.png           # 冗余输出，观察每个通道的熵/结果
```

典型输出格式：`b1,rgb,lsb,xy` 一行对应一个候选，附检测到的字符串预览；`-E "b1,rgb,lsb,xy"` 把该平面原始位流写到 stdout，配合重定向 `> extracted.bin` 落盘。

平面语法解释：`b1` 指第 1 个最低有效位（LSB），`rgb` 指对 R/G/B 三通道都取，`lsb` 指低位平面，`xy` 指扫描顺序。常用组合按题目隐写位平面调整。

## 常见坑

- steghide 无口令场景脚本化必须显式 `-p ""`，否则卡在交互提示；交互终端里直接回车等价。
- zsteg 只支持 PNG/BMP（依赖 Ruby 图像库），JPEG 的 LSB 隐写它读不了，换 stegsolve/自定义脚本。
- `-E` 的平面参数必须与 `zsteg` 默认检测到的那一行完全一致，`-a` 出来的平面列表里复制粘贴最稳。
- 提取出的原始位流常带噪声或需要二次处理（如按字节反转、按行重排），先 `xxd` 看前 64 字节确认格式再解析。
- zsteg 输出里的"预览"可能被截断，疑似有数据但看不到完整内容时用 `-E` 取全量。

## 验证方式

自建测试：生成纯色 PNG 后把一段 ASCII 文本写入 R 通道最低位（Python PIL 即可），`zsteg` 应在其候选列表出现含该文本的行；`zsteg -E "b1,r,lsb,xy"` 提取后与写入位流一致。steghide 用 `steghide embed -cf c.jpg -ef s.txt -p pass` 嵌入后，`steghide extract -sf c.jpg -p pass` 应还原文件。
