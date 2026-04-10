# AGENTS

这个仓库是一个面向企业微信文档工作流的 agent。

核心闭环：

1. 读取用户输入
2. 检索或总结来源材料
3. 创建或编辑企业微信文档
4. 通过 `doc_id`、`doc_url`、`doc_name` 维持文档连续性
5. 通过独立的 `he/` 层做回归和检查

`AGENTS.md` 只做索引，不做长手册。

## Source Of Record

- [docs/PRODUCT.md](/C:/Users/18014/wecom-aibot/docs/PRODUCT.md)
- [docs/DOC_WRITING.md](/C:/Users/18014/wecom-aibot/docs/DOC_WRITING.md)
- [docs/REPLY_STYLE.md](/C:/Users/18014/wecom-aibot/docs/REPLY_STYLE.md)
- [docs/MCP_TOOLS.md](/C:/Users/18014/wecom-aibot/docs/MCP_TOOLS.md)
- [docs/MEMORY.md](/C:/Users/18014/wecom-aibot/docs/MEMORY.md)
- [docs/ARCHITECTURE.md](/C:/Users/18014/wecom-aibot/docs/ARCHITECTURE.md)
- [docs/ROUTING_RULES.md](/C:/Users/18014/wecom-aibot/docs/ROUTING_RULES.md)
- [docs/FLOWS.md](/C:/Users/18014/wecom-aibot/docs/FLOWS.md)
- [docs/CHECKS.md](/C:/Users/18014/wecom-aibot/docs/CHECKS.md)
- [docs/EVALS.md](/C:/Users/18014/wecom-aibot/docs/EVALS.md)
- [he/gates/global.yaml](/C:/Users/18014/wecom-aibot/he/gates/global.yaml)

## 目录约定

运行时层级：

- `backend/entry`
- `backend/flow`
- `backend/policy`
- `backend/state`
- `backend/caps`
- `backend/runtime`
- `backend/tools`

独立 HE 层：

- `he/`

稳定入口文件名不改：

- `backend/app.py`
- `backend/agent.py`
- `backend/memory.py`
- `scripts/run_eval_case.py`
- `scripts/check_layers.py`
- `scripts/mcp_test.py`
- `gateway/long_connection.ts`

## 可修改文件

正常迭代可以修改：

- `prompts/system/*`
- `backend/app.py`
- `backend/agent.py`
- `backend/memory.py`
- `backend/entry/*`
- `backend/flow/*`
- `backend/policy/*`
- `backend/state/*`
- `backend/caps/*`
- `backend/runtime/*`
- `backend/tools/*`
- `docs/*.md`
- `he/gates/*`
- `he/scenarios/*`
- `he/review_template.md`
- `README.md`
- `.gitignore`

## 非必要不要修改的文件

- `knowledge_base/*.pdf`
- `config/mcp_servers.json`
- `gateway/long_connection.ts`
- `data/`
- `he/runs/`
- `he/reports/`

## 迭代规则

一次只改一个主要层面：

- prompt
- flow
- policy / state
- runtime / tools
- HE checks

改完后必须重跑固定场景，再比较结果。
