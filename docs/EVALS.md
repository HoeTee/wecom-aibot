# Evals

## 目的

当前 HE 层服务的是固定场景回归，而不是自由发挥式测试。

重点是：

- 场景固定
- 证据导出
- 自动检查
- 收敛后再做人类最终裁决

## HE 目录

HE 已独立到 `he/`：

- `he/contracts/*`
- `he/flows/*`
- 共享 hard gates：`he/gates/global.yaml`
- 场景定义：`he/scenarios/*`
- 人工 review 模板：`he/review_template.md`
- 运行产物：`he/runs/*`
- 总报告：`he/reports/*`

执行入口保持在根目录：

- `scripts/run_eval_case.py`
- `scripts/check_layers.py`

## preflight

每次业务场景评测前，先做一层基础设施 preflight：

- 检查所有 `required: true` 的 stdio MCP server 是否能完成 initialize
- 如果失败，业务场景应先判为基础设施失败
- 对应 gate 是 `required_stdio_mcp_must_initialize`

## 当前场景

当前已落地的代表性场景包括：

### 1. `pdf_3papers_create_summary_doc`

抓这类问题：

- “重新生成”时误复用旧文档
- 写回 `...` 占位内容
- 缺少 1/2/3/4 结构
- 未请求表格时提前出现第 5 节

### 2. `upload_pdf_add_to_knowledge_base`

抓这类问题：

- 上传后没有留下结构化上传状态
- 用户补一句“把这份文档添加到知识库”时再次索要文件
- 没有明确确认刚上传文件已入库

### 3. `upload_duplicate_pdf_notice`

抓：

- 内容完全一致的重复上传是否被明确提示

### 4. `upload_same_name_pdf_update_notice`

抓：

- 同名但内容不同的上传是否被明确提示为更新

### 5. `kb_list_files`

抓：

- 知识库列表回复是否包含数量和文件列表

### 6. `kb_related_candidates`

抓：

- 相关性查询是否先给候选，而不是直接替用户决定具体文件

### 7. `kb_export_action_clarify`

抓：

- 选择具体文件后，系统是否继续澄清“原文件还是摘要”

### 8. `kb_export_original_pdf`

抓：

- 用户明确要原文件时，是否真的准备了 attachment

### 9. `kb_delete_file_confirmation`

抓：

- 删除流程是否先确认，再执行

### 10. `kb_list_all_files_followup`

抓：

- 用户强调“把所有文件都列出来”后，系统是否真的返回完整列表

### 11. `kb_uploaded_files_scope`

抓：

- 用户问自己上传过哪些文件时，系统是否只返回上传文件集合

### 12. `kb_rename_request_scope`

抓：

- 知识库改名请求是否保持在知识库文件管理语义内，而不是误转成企微文档标题语义

### 13. `kb_rename_confirmation`

抓：

- 用户明确给出原文件名和新名称后，系统是否先进入确认步骤

### 14. `kb_rename_by_ordinal_reference`

抓：

- 用户按最近候选列表中的“第 N 份文件”发起改名时，系统是否正确解析序号引用
- 是否进入知识库改名确认
- 是否避免掉入 `rag.*`
- 是否避免无回复结束

### 15. `doc_merge_kb_into_current`

抓：

- 并入当前文档前，是否确认目标文档、来源文档和动作

### 16. `doc_replace_kb_section`

抓：

- 替换前，是否先展示将被替换的章节预览

### 17. `doc_expand_kb_section`

抓：

- 自动生成新章节标题后，是否先确认标题

## 运行方式

用户在企微里完成真实测试后，执行：

```powershell
python scripts/run_eval_case.py --scenario-id pdf_3papers_create_summary_doc --session-id dm:14292
python scripts/run_eval_case.py --scenario-id upload_pdf_add_to_knowledge_base --session-id dm:14292
python scripts/run_eval_case.py --scenario-id upload_duplicate_pdf_notice --session-id dm:14292
python scripts/run_eval_case.py --scenario-id upload_same_name_pdf_update_notice --session-id dm:14292
python scripts/run_eval_case.py --scenario-id kb_list_all_files_followup --session-id dm:14292
python scripts/run_eval_case.py --scenario-id kb_uploaded_files_scope --session-id dm:14292
python scripts/run_eval_case.py --scenario-id kb_rename_request_scope --session-id dm:14292
python scripts/run_eval_case.py --scenario-id kb_rename_confirmation --session-id dm:14292
python scripts/run_eval_case.py --scenario-id kb_rename_by_ordinal_reference --session-id dm:14292
```

其中：

- `scenario-id` 是场景标识
- `session-id` 是本地 memory 里的会话标识

## 导出产物

脚本会在 `he/runs/<run_id>/<scenario_id>/` 下导出：

- `metadata.json`
- `user_request.txt`
- `assistant_reply.txt`
- `contract_results.json`
- `flow_results.json`
- `flow_trace.json`
- `tool_trace.json`
- `rag_query.json`
- `doc_binding.json`
- `uploaded_file.json`
- `attachment.json`
- `written_doc_content.md`
- `gate_results.json`
- `evaluator.json`

如果启用了层级检查，还会额外导出：

- `he/runs/<run_id>/layer_checks.json`
- `he/runs/<run_id>/required_stdio_boot.json`

总 summary 默认输出到：

- `he/reports/<run_id>.md`
- `he/reports/<run_id>.json`

## flow_trace

`flow_trace.json` 是单次运行的核心证据之一。

推荐位置：

- `he/runs/<run_id>/<scenario_id>/flow_trace.json`

当前也会导出：

- `he/runs/<run_id>/<scenario_id>/contract_results.json`
- `he/runs/<run_id>/<scenario_id>/flow_results.json`

默认结构：

- `metadata`
- `events`

其中：

- `metadata` 记录运行上下文
- `events` 保留真实发生顺序

### metadata

默认至少包含：

- `scenario_id`
- `run_id`
- `session_id`
- `git_commit`
- `prompt_version`

### events

每条事件默认至少包含：

- `timestamp`
- `layer_at_event`
- `event`

关键字段默认覆盖：

- `route_selected`
- `route_reason`
- `selected_target`
- `guard_hit`
- `tool_called`
- `clarify_needed`
- `stop_reason`
- `agent_plan_created`
- `agent_self_check`

## evaluator

evaluator 默认自动执行。

每个场景结果默认输出：

- `pass` / `fail`
- `failed_checks`
- 每个失败项的简短原因
- `suggested_fix_layer`

其中：

- `failed_checks` 用 `code + detail`
- `suggested_fix_layer` 默认包含主层和次层

## 当前 workflow

1. coding agent 先修改代码
2. 用户在企微里跑真实场景
3. 运行 `scripts/run_eval_case.py`
4. 先看：
   - `gate_results.json`
   - `flow_trace.json`
   - `layer_checks.json`
5. 自动检查收敛后，再做最终 human review

## maintenance

maintenance 不假设后台自动运行。

当前默认方式：

- 每次主链路发生重要修改后，由 coding agent 主动建议执行一次
- 由用户决定是否生成 maintenance summary

输出位置：

- `he/reports/maintenance/*.md`
- `he/reports/maintenance/*.json`

输出结构保持短而结构化，默认包括：

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

清理测试产物统一使用：

```powershell
python scripts/cleanup_artifacts.py
```

## 当前边界

这套 gates 目前只针对已明确建模的场景生效，不自动推广到所有问题。
