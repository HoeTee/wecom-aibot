# 检查

## 目的

这份文档定义：

- 哪些项必须自动检查
- 哪些项应做成事中 guard
- 哪些项由 human reviewer 在最后裁决

当前原则：

- HE 过程本身尽量自动化完成
- human review 不参与每一轮迭代
- human review 只在一轮代码收敛后，检查最终产品效果

## flow_trace

`flow_trace` 属于自动检查的基础输入。

当前要求：

- 每次关键请求都应导出独立的 `flow_trace.json`
- 单次运行先落 JSON
- 后续由 maintenance 汇总和清理，不做永久无限堆积

默认必须包含这些字段：

- `route_selected`
- `route_reason`
- `selected_target`
- `guard_hit`
- `tool_called`
- `clarify_needed`
- `stop_reason`

### 字段粒度

#### `route_selected`

必须明确写出这次请求最终走了哪条路。

#### `route_reason`

必须记录为什么选了这条路。

#### `selected_target`

默认记录对象摘要，而不是只记单个主标识。

建议至少包含：

- `target_type`
- 主标识
- 简短显示名

#### `guard_hit`

默认记录命中的 guard 名称列表。

#### `tool_called`

默认记录：

- tool 名
- 参数摘要
- 结果摘要

这里用摘要，不记录全量原文。

#### `clarify_needed`

必须明确标记这次是否进入澄清分支。

#### `stop_reason`

必须写明这次流程为什么在这里结束。

## 自动检查优先

以下项默认属于自动检查：

### 1. 是否走错路由

例如：

- 上传 PDF 后却走到了普通聊天理解
- 问知识库列表却走到了 RAG 总结
- 文档链接意图不明却直接进入编辑

这类边界清晰，默认自动检查。

### 2. 是否重复索要已上传文件

例如：

- 用户刚上传 PDF
- 系统已入库成功
- 后面却又回复“请上传文件”或“请提供文件”

这类项不仅应自动检查，还应优先做成：

- 事中 guard
- 事后 evaluator

### 3. 是否误复用旧文档

例如：

- 用户说“重新生成一份文档”
- 系统却继续编辑旧 `doc_id`

这类项也应同时具备：

- 事中 guard
- 事后 evaluator

### 4. 是否缺少要求的章节

如果用户明确要求了结构化章节，例如：

- 背景
- 每篇论文摘要
- 横向对比
- 结论与建议

则系统必须自动检查最终内容是否缺项。

### 5. 是否提前生成未请求的内容

例如：

- 用户未要求 comparison table
- 系统却提前生成第 5 节表格

这类项默认自动检查。

### 6. 是否多调 / 漏调 / 错调 tool

这类项默认自动检查。

判断依据不是让 evaluator 每次重新自由猜用户意图，而是：

1. 先根据路由规则和流程规则确定预期路径
2. 再确定允许的 tool 集合
3. 检查实际 tool 调用是否偏离

## evaluator

evaluator 默认自动执行。

输出结果默认包括：

- `pass` / `fail`
- `failed_checks`
- 每个失败项的简短原因

### 输出层次

#### 1. 每个 scenario 单独输出

每个场景都要有自己的检查结果。

#### 2. 额外总 summary

除单场景结果外，还应输出一份总 summary。

推荐位置：

- `evals/reports/<run_id>.md`
- `evals/reports/<run_id>.json`

## layer checks

layer checks 也属于自动检查。

当前优先级：

1. 下层反向 import 上层
2. production 代码 import `evals/*`
3. orchestration 直接依赖 tool implementation

第一阶段策略：

- 直接 hard fail
- 同时产出结构化报告

推荐位置：

- `evals/runs/<run_id>/layer_checks.json`

报告默认包含：

- 违反了哪条规则
- 哪个文件依赖了哪个文件

## 软质量项

以下项默认也应尽量自动检查，但最终产品裁决仍由 human reviewer 完成：

### 1. 文档内容质量

自动检查负责抓：

- 结构性问题
- 明显缺失
- 占位符
- 重复段落

human reviewer 最后判断：

- 是否能交付
- 是否满足真实需求

### 2. 回复是否自然

默认自动检查为主。

用户反馈和最终 human review 用于持续校正标准。

### 3. 总结是否有洞见

默认自动检查为主。

最终由 human reviewer 判断：

- 是否真的有价值
- 是否值得保留当前改动

## human review 的位置

human review 不是每轮 HE 的常规步骤。

当前默认流程是：

1. coding agent 自动修改
2. 自动跑固定 scenarios
3. 自动跑 gates / evaluator
4. 代码和规则收敛后
5. 再由 human reviewer 看最终文档和最终体验

## 当前方向

后续检查体系分三层：

1. hook
   - 自动记录 route / state / tool / output
2. guard
   - 在运行时尽量阻止明显错误
3. evaluator
   - 在运行后自动判断是否通过
