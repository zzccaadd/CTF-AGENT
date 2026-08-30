---
source_url: https://cwe.mitre.org/data/definitions/798.html
source_title: "CWE-798: Use of Hard-coded Credentials"
source_version: "4.20"
publisher: MITRE
license: MITRE CWE terms
retrieved_at: 2026-08-31
topic: hardcoded-credentials
cwe_id: CWE-798
---
# CWE-798：硬编码凭据

## 核心概念

源码、配置文件、二进制中直接内嵌口令、密钥、令牌等凭据。任何能读取代码/文件/二进制的人都能提取并使用这些凭据；在逆向场景中，这是最常被直接利用的一类弱点——字符串提取往往一步到位。

## 关键细节

- 典型形态：`const char *pwd = "s3cr3t";`、`.env`/`config` 中 `API_KEY=xxx`、数据库连接串内嵌口令、与用户输入直接 `strcmp` 比较的"口令校验"。
- 反面教材示例：

```c
#include <string.h>
int check(const char *input) {
    return strcmp(input, "s3cr3t") == 0; /* 口令随二进制分发 */
}
```

- 提取手段：

```bash
strings ./prog | grep -iE 'pass|key|token|secret'
```

- 仓库扫描：`gitleaks detect --source .`、`trufflehog filesystem .`。
- 正确做法：环境变量（如 `getenv("DB_PASS")`）、密钥管理服务、`.env` 加入 `.gitignore` 不入库、凭据定期轮换。
- 关联条目：CWE-259（硬编码口令）、CWE-321（硬编码加密密钥）。

## 常见坑

- Base64/简单混淆不算保护：`echo xxx | base64 -d` 即可还原。
- 凭据留在 git 历史里：删除当前提交不等于清除历史提交（`git log -p` 可翻出）。
- Docker 镜像层与运行环境变量中残留凭据。
- 客户端程序硬编码"校验口令"并直接与输入比较——提取即得可用凭据。
- 凭据复用：同一口令/密钥被多个服务或账号共用，泄露一处即波及全部。

## 验证方式

- 静态提取：strings/grep 全文件搜索常见关键词及其变形（大小写、拼接片段）。
- gitleaks/trufflehog 扫描仓库及历史提交。
- 对二进制逐段检查可疑字符串常量，确认是否被校验逻辑直接引用。
