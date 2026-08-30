---
source_url: https://cwe.mitre.org/data/definitions/502.html
source_title: "CWE-502: Deserialization of Untrusted Data"
source_version: "4.20"
publisher: MITRE
license: MITRE CWE terms
retrieved_at: 2026-08-31
topic: deserialization
cwe_id: CWE-502
---
# CWE-502：不可信反序列化

## 核心概念

程序对来自不可信来源的序列化数据执行反序列化，攻击者构造的序列化对象在反序列化过程中触发"魔术方法/回调"，进而执行任意代码或造成拒绝服务。涉及典型机制：Python `pickle` 的 `__reduce__`、Java `ObjectInputStream.readObject` 的 gadget 链、PHP `unserialize` 的 `__wakeup`/`__destruct`、Ruby `Marshal`、.NET `BinaryFormatter`、Node.js 的 eval 型反序列化。

## 关键细节

- 风险判定：序列化格式是否自带"对象重建 + 回调执行"能力；数据来源是否可控；入口是否可达。
- Python 演示（仅教学，勿用于生产）：

```python
import pickle, os
class RCE:
    def __reduce__(self):
        return (os.system, ("id",))
open("p.bin", "wb").write(pickle.dumps(RCE()))
pickle.load(open("p.bin", "rb"))   # 反序列化即执行 os.system("id")
```

- 预期输出：`uid=...` 一行的命令执行结果。
- YAML 注意：`yaml.safe_load(data)` 安全；`yaml.load(data)`（旧默认 Loader）或 `yaml.unsafe_load(data)` 可构造对象、存在同类风险。
- Java 缓解：Java 9+ 使用 `ObjectInputFilter` 对类名做白/黑名单过滤；对不可信输入应整体拒绝 `readObject`。
- 工程防御：不使用原生反序列化解析不可信数据；改用 JSON + 结构校验；序列化数据加 HMAC 签名并校验来源；类名白名单。

## 常见坑

- 只防显式的 `loads`，漏掉隐式入口：Session/缓存/消息队列/ORM 的序列化存储。
- 用 `yaml.load` 处理不可信 YAML 且不自知 Loader 行为差异。
- 反序列化后不校验对象类型/字段范围。
- 误以为"本地文件"可信——本地文件内容也可能被用户控制（上传、缓存、临时文件）。

## 验证方式

- 数据流审计：不可信输入是否可达反序列化入口。
- 用无害探测对象（仅打印）验证"反序列化会执行回调"，不执行破坏性命令。
- 审计依赖中已知 gadget 组件（如 ysoserial 涉及的库）版本，确认是否存在公开利用链。
