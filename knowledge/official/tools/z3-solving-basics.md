---
source_url: https://z3prover.github.io/api/html/index.html
source_title: Z3 API documentation
source_version: "1.9.8"
publisher: Microsoft Research / Z3 contributors
license: Z3 project terms
retrieved_at: 2026-08-31
topic: constraint-solving
tool_name: z3
---
# Z3：约束求解基础

## 建模流程

先创建与目标位宽匹配的整数、位向量或数组变量，再用约束表达输入关系、边界和校验逻辑，最后调用 solver 检查 `sat`、`unsat` 或 `unknown`。模型中的类型必须与程序实际运算一致，尤其要区分无符号位向量和数学整数。

## 结果使用

只有 `sat` 结果才可以读取 model。读取模型后应把候选值带回原始校验逻辑重新验证；`unsat` 说明当前约束集合没有解，不等同于题目没有解，可能是建模遗漏或类型错误。

## 调试策略

复杂约束应分组加入并逐步检查，优先固定常量、位宽和边界。对 `unknown` 保留原因和超时信息，不要把未知结果当成错误答案或成功答案。
