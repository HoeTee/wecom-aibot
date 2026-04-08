# Evals

## 目的

当前 HE 层主要服务已经明确的场景回归。

当前重点场景包括：

- 基于 `knowledge_base/papers/` 中的固定论文生成新的企业微信文档
- 用户先上传 PDF，再发“把这份文档添加到知识库”
- 用户重复上传内容完全一致的 PDF
- 用户上传同名但内容不同的 PDF

## 结构

- 共享 hard gates：`evals/gates/global.yaml`
- 场景定义：`evals/scenarios/*`
- 人工 review 模板：`evals/review_template.md`
- 运行产物：`evals/runs/`
- 总报告：`evals/reports/*`

## 当前落地场景

### 1. `pdf_3papers_create_summary_doc`

用于发现这类问题：

- “重新生成”时误复用旧文档
- 写回 `...` 占位内容
- 缺少 1/2/3/4 四个部分
- 未要求表格时提前出现第 5 节

### 2. `upload_pdf_add_to_knowledge_base`

用于发现这类问题：

- 上传 PDF 后没有留下结构化上传状态
- 用户补一句“把这份文档添加到知识库”时，assistant 再次索要文件
- assistant 没有明确确认刚上传文件已经入库

### 3. `upload_duplicate_pdf_notice`

用于检查：

- 内容完全一致的重复上传是否被明确提示

### 4. `upload_same_name_pdf_update_notice`

用于检查：

- 同名但内容不同的上传是否被明确提示为更新

## 运行方式

用户在企微里完成一次真实测试后，执行：

```powershell
python scripts/run_eval_case.py --scenario-id pdf_3papers_create_summary_doc --session-id dm:14292
python scripts/run_eval_case.py --scenario-id upload_pdf_add_to_knowledge_base --session-id dm:14292
python scripts/run_eval_case.py --scenario-id upload_duplicate_pdf_notice --session-id dm:14292
python scripts/run_eval_case.py --scenario-id upload_same_name_pdf_update_notice --session-id dm:14292
```

其中：

- `scenario-id` 指评测场景
- `session-id` 指当前企微会话在本地 memory 中的会话标识

## 导出产物

脚本会在 `evals/runs/<run_id>/<scenario_id>/` 下导出：

- `metadata.json`
- `user_request.txt`
- `assistant_reply.txt`
- `flow_trace.json`
- `tool_trace.json`
- `rag_query.json`
- `doc_binding.json`
- `uploaded_file.json`
- `written_doc_content.md`
- `gate_results.json`

如果启用了 layer checks，还应额外导出：

- `evals/runs/<run_id>/layer_checks.json`

## flow_trace

`flow_trace.json` 属于单次运行证据包的一部分。

### 位置

推荐位置：

- `evals/runs/<run_id>/<scenario_id>/flow_trace.json`

### 结构

默认采用：

- `metadata`
- `events`

其中：

- `metadata` 记录单次运行上下文
- `events` 保留真实发生顺序

### metadata

默认至少包含：

- `scenario_id`
- `run_id`
- `session_id`
- `git_commit`
- `prompt_version`

### events

每条 event 默认至少包含：

- `timestamp`
- `layer_at_event`
- `event`

关键字段默认应覆盖：

- `route_selected`
- `route_reason`
- `selected_target`
- `guard_hit`
- `tool_called`
- `clarify_needed`
- `stop_reason`

## evaluator 输出

evaluator 默认自动执行。

### 每个场景的结果

默认输出：

- `pass` / `fail`
- `failed_checks`
- 每个失败项的简短原因
- `suggested_fix_layer`

其中：

- `failed_checks` 使用两层命名：`code` + `detail`
- `suggested_fix_layer` 默认包含主层和次层

### 总 summary

除每个 scenario 的结果外，还应额外输出一份总 summary：

- `evals/reports/<run_id>.md`
- `evals/reports/<run_id>.json`

## 当前 workflow

1. coding agent 先修改代码
2. 用户在企微里跑真实场景
3. 运行 `scripts/run_eval_case.py`
4. 先看 `gate_results.json`、`flow_trace.json`、`layer_checks.json`
5. 自动检查全部收敛后，再做最终 human review

## maintenance

maintenance 不假设后台自动运行。

当前默认方式是：

- 每次主链路发生重要修改后，由 coding agent 主动建议执行一次
- 由用户决定是否生成 maintenance summary

### 输出位置

maintenance summary 建议按主题命名，位置在：

- `evals/reports/maintenance/*.md`
- `evals/reports/maintenance/*.json`

### 输出结构

给人看的 summary 保持结构化但不过分详细，推荐包含：

1. 问题
2. 影响层
3. 建议修改点
4. 相关场景

### 生命周期

单次运行的 JSON 证据先落盘。

后续由 maintenance 负责：

- 汇总
- 提炼
- 清理不再需要的旧 traces

## 当前边界

这套 gates 目前只针对已经明确定义的场景生效：

- `pdf_3papers_create_summary_doc`
- `upload_pdf_add_to_knowledge_base`
- `upload_duplicate_pdf_notice`
- `upload_same_name_pdf_update_notice`

不会自动推广到其他场景。
