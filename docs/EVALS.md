# Evals

## 目的

当前 HE 层主要服务一个特定场景：

- 基于 `knowledge_base/papers/` 中的三篇固定论文生成一份新的企业微信文档
- 文档必须包含：背景、每篇论文摘要、横向对比、结论与建议
- 当前场景首轮不应提前出现 comparison table

## 结构

- 共享 hard gates：`evals/gates/global.yaml`
- 场景定义：`evals/scenarios/*`
- 人工 review 模板：`evals/review_template.md`
- 运行产物：`evals/runs/`，已加入 `.gitignore`

## 当前落地

当前已经为 `pdf_3papers_create_summary_doc` 加入场景级 gates，用于发现这次真实踩过的问题：

- “重新生成”时误复用旧文档
- 写回 `...` 占位内容
- 缺少 1/2/3/4 四个部分
- 未要求表格时提前出现第 5 节

## 运行方式

用户在企微里完成一次真实测试后，执行：

```powershell
python scripts/run_eval_case.py --scenario-id pdf_3papers_create_summary_doc --session-id dm:14292
```

其中：

- `scenario-id` 指评测场景
- `session-id` 指当前企微会话在本地 memory 中的会话标识

## 导出产物

脚本会在 `evals/runs/<run_id>/<scenario_id>/` 下导出：

- `metadata.json`
- `user_request.txt`
- `assistant_reply.txt`
- `tool_trace.json`
- `rag_query.json`
- `doc_binding.json`
- `written_doc_content.md`
- `gate_results.json`

## 当前 workflow

1. 我先修改代码
2. 你在企微里跑真实场景
3. 运行 `scripts/run_eval_case.py`
4. 先看 `gate_results.json`
5. gates 全过后，再做最终 human review

## 当前边界

这套 gates 目前只针对 `pdf_3papers_create_summary_doc` 这个场景，不自动推广到其他场景。
