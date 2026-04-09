# 检查

## 目的

这份文档定义：

- 哪些项必须自动检查
- 哪些项应做成事中 guard
- 哪些项由 human reviewer 在最后裁决

当前原则：

- HE 过程本身尽量自动化完成
- human review 不参与每一轮迭代
- human review 只在一轮代码和规则收敛后，检查最终产品效果

## 自动检查的三层

当前检查体系分三层：

1. `hook`
   - 自动记录 route、state、tool、output
2. `guard`
   - 在运行时尽量阻止明显错误
3. `evaluator`
   - 在运行后自动判断是否通过

## flow_trace

`flow_trace` 属于自动检查的基础输入。

当前要求：

- 每次关键请求都导出独立的 `flow_trace.json`
- 单次运行先落 JSON
- 后续由 maintenance 汇总和清理，不做永久无限堆积

### 顶层结构

`flow_trace.json` 默认采用：

- `metadata`
- `events`

## contract_results

动作层开始 CLI 化后，每次关键评测也应导出独立的 `contract_results.json`。

当前第一阶段先覆盖 `kb.*`：

- `kb.list`
- `kb.list_uploads`
- `kb.match_related`
- `kb.export`

### metadata

默认至少包含：

- `scenario_id`
- `run_id`
- `session_id`
- `git_commit`
- `prompt_version`

### events

事件必须保留真实发生顺序。

每条事件默认至少包含：

- `timestamp`
- `layer_at_event`
- `event`

此外，默认必须覆盖这些关键字段：

- `route_selected`
- `route_reason`
- `selected_target`
- `guard_hit`
- `tool_called`
- `clarify_needed`
- `stop_reason`

### 字段要求

#### `route_selected`

必须明确写出这次请求最终走了哪条路。  
命名采用两层：

- `code`
- `detail`

#### `route_reason`

必须记录为什么选了这条路。  
默认是原因列表，而不是单条字符串。

#### `selected_target`

默认记录对象摘要，而不是只记单个主标识。  
建议至少包含：

- `target_type`
- 主标识
- 简短显示名

如果没有选中任何对象，也不直接写 `null`；应保留空对象并写明原因。

#### `guard_hit`

默认记录命中的 guard 列表。  
命名采用两层：

- `code`
- `detail`

#### `tool_called`

每次调用 tool 时都应作为一条独立事件记录，而不是最后合并成一个总列表字段。

默认记录：

- `tool_name`
- 参数摘要
- 结果摘要
- `result_status`

`result_status` 至少区分：

- `success`
- `failure`
- `partial`

这里只记录摘要，不记录全量原文。

#### `clarify_needed`

必须明确标记这次是否进入澄清分支。  
默认包含：

- 是否需要澄清
- `clarify_reason`

#### `stop_reason`

必须写明这次流程为什么在这里结束。  
默认包含：

- 两层命名：`code` / `detail`
- 最后停在哪一层

## 自动检查优先项

以下项默认属于自动检查：

### 0. required stdio MCP 是否先成功启动

如果某个 `required: true` 的 stdio MCP server 不能完成 initialize：

- 该轮业务场景不应继续视为有效
- 应优先判为基础设施失败
- 应输出对应的 child stderr 日志路径

### 1. 是否走错路由

例如：

- 上传 PDF 后却走到了普通聊天理解
- 问知识库列表却走到了 RAG 总结
- 文档链接意图不明却直接进入编辑

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

### 6. 是否多调 / 漏调 / 错调 tool

判断依据不是让 evaluator 每次重新自由猜用户意图，而是：

1. 先根据路由规则和流程规则确定预期路径
2. 再确定允许的 tool 集合
3. 检查实际 tool 调用是否偏离

### 7. 是否把知识库作用域理解错

以下情况默认自动检查：

- 用户明确要求“把所有文件都列出来”，系统仍继续只列前几项
- 用户问“我上传过哪些文件”，系统却混入固定知识库材料
- 用户问知识库文件能否改名，系统却误转成企微文档标题语义

## evaluator

evaluator 默认自动执行。

### 输出结构

默认输出：

- `pass` / `fail`
- `failed_checks`
- 每个失败项的简短原因
- `suggested_fix_layer`

其中：

- `failed_checks` 用 `code + detail`
- `suggested_fix_layer` 默认包含主层和次层

### 场景结果与总结果

evaluator 默认既输出：

1. 每个 scenario 的单独结果
2. 一份总 summary

推荐位置：

- `he/reports/<run_id>.md`
- `he/reports/<run_id>.json`

## layer checks

layer checks 也属于自动检查。

### 当前优先级

以下三类都重要，但当前第一优先级是：

1. 下层反向 import 上层
2. production 代码 import `he/*`
3. `flow` 直接依赖 `tools`
4. stdio MCP wrapper 缺少 `__main__ -> run(...)` 入口

### 第一阶段策略

- 直接 hard fail
- 同时产出结构化报告

推荐位置：

- `he/runs/<run_id>/layer_checks.json`

### 报告内容

默认包含：

- 违反了哪条规则
- 哪个文件依赖了哪个文件
- `suggested_refactor_target`

其中 `suggested_refactor_target` 默认包含：

- 主目标
- 备选目标

每个目标都写：

- 层名
- 建议目录

## 软质量项

以下项也应尽量自动检查，但最终产品裁决仍由 human reviewer 完成：

### 1. 文档内容质量

自动检查负责抓：

- 结构性问题
- 明显缺失
- 占位符
- 重复段落

最终 human reviewer 判断：

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
2. 自动跑固定 `scenarios`
3. 自动跑 guards / evaluator
4. 代码和规则收敛后
5. 再由 human reviewer 看最终文档和最终体验

## 当前新增覆盖面

除原有的上传、综述和文档连续性外，当前自动检查已扩展到：

- 知识库列表是否返回数量和文件名
- 用户强调“所有文件”后是否真的返回全量列表
- 上传文件列表是否只返回上传文件
- 导出流程是否先澄清原文件还是摘要
- 原 PDF 导出时是否准备 attachment
- 删除流程是否先确认
- 知识库改名请求是否保持在知识库文件语义内
- 明确文件名和新名称后是否先进入改名确认
- 并入当前文档前是否确认目标/来源/动作
- 替换流程是否先展示章节预览
- 扩写流程是否先确认自动生成的标题
