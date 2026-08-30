---
source_url: knowledge/reference/forensics/lsb-stego.md
source_title: LSB steganography extraction — reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: forensics
tool_name: zsteg
---

# LSB 隐写提取（通用模式）

> 从多份已审核 writeup 提炼的通用解法模式，不含任何具体题目的 flag 或附件内容。

## 核心概念

LSB（最低有效位）隐写把数据按位写入载体字节的最低位：图像把每个像素的 R/G/B 分量最低 1 位拼起来存字节，音频（WAV）把每个采样值的最低位存数据。因为改 1 位对颜色/音量几乎无感，肉眼与直方图都难以察觉。要点是载体必须是无损格式（PNG/BMP/WAV），JPEG 的有损压缩会破坏嵌入位，LSB 提取不适用。

## 关键细节

1. **识别**：`file` 确认格式；比较图片尺寸与文件大小是否异常偏大；用 `zsteg -a img.png` 全模式扫描，或 stegsolve 的 Bit Planes / Data Extract 面板逐平面看是否出现规律图案或文本。
2. **常见工具**：
   - `zsteg -a img.png`（扫描全部组合）；`zsteg -E 'b1,rgb,lsb,xy' img.png > out` 按指定模式提取（b1=每通道 1 位，rgb=通道序，lsb=位序，xy=扫描顺序）。
   - `steghide extract -sf img.jpg -p 密码`（若有密码提示才用，先试空密码）。
   - stegsolve：Analyse → Data Extract，勾选 R/G/B 与 LSB 位，Preview 观察是否出现可读数据。
3. **手动提取脚本**（组合参数化，便于换通道序/位序/扫描序）：

```python
from PIL import Image
img = Image.open("c.png").convert("RGB")
px = img.load()
bits = []
for y in range(img.height):              # xy：先列后行；yx 则交换循环
    for x in range(img.width):
        r, g, b = px[x, y]
        for v in (r, g, b):              # 通道序 rgb / bgr / 只取某通道
            bits.append(v & 1)           # 取最低位
data = bytearray()
for i in range(0, len(bits) - 7, 8):
    byte = 0
    for j in range(8):
        byte |= bits[i + j] << j         # 位序：j=0 为最低位（LSB-first）
    data.append(byte)
print(data[:64])                         # 先看头部是否命中魔数/明文
```

4. **音频 LSB**（WAV）：`python -c` 逐采样 `sample & 1` 收集位，或 `stegolsb wavsteg -r -i s.wav -o out.txt`。

## 常见坑

- **通道序**：BMP/某些工具按 BGR 存，或含 alpha 通道，顺序错了全乱码；用 `zsteg -a` 覆盖所有组合快速定位。
- **位序**：提取时 `<< j` 与 `<< (7-j)` 结果不同，两种都试。
- **扫描顺序**：数据可能按列优先（yx）写入而非行优先（xy）。
- **数据起点**：嵌入数据可能以 PNG/ZIP 魔数或可读文本开头；解出字节先 `xxd` 看头，若是压缩包再解压。
- JPEG 图像上的"LSB"多数是误导（有损压缩），先确认无损格式。

## 验证方式

- 提取结果头部命中已知魔数（`\x89PNG`、`PK\x03\x04`、`%PDF-`）或整段可读文本才算成功。
- 对提取文件执行 `file` 与解压/打开双重确认；多组合提取时按可打印比例评分挑选。
