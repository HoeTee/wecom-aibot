# AGENTS

这个仓库是一个面向企业微信文档工作流的 agent。核心闭环是：

1. 读取用户输入
2. 检索或总结来源材料
3. 创建或编辑企业微信文档
4. 通过 `doc_id`、`doc_url`、`doc_name` 维持文档连续性

## Source Of Record

以下文件是这个仓库的知识基线：

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
- [evals/gates/global.yaml](/C:/Users/18014/wecom-aibot/evals/gates/global.yaml)

`AGENTS.md` 只做索引，不做长篇手册。

## 可修改文件

正常迭代可以修改：

- `prompts/system/*`
- `backend/app.py`
- `backend/agent.py`
- `backend/memory.py`
- `backend/mcp_client/host.py`
- `backend/mcp_client/connection.py`
- `docs/*.md`
- `evals/gates/*`
- `evals/scenarios/*`

## 非必要不要修改的文件

- `knowledge_base/papers/*`
- `config/mcp_servers.json`
- `gateway/long_connection.ts`
- `data/`、`evals/runs/`、`evals/reports/` 下的运行产物

## 迭代规则

一次只改一个层面：

- prompt
- tool 暴露方式或 tool 使用约束
- memory 读写或注入逻辑
- orchestration flow

改完后，必须重跑同一批固定 eval 场景。

当前 workflow：

1. coding agent 做一轮收敛修改
2. 跑固定 scenarios
3. 先看 shared hard gates 是否通过
4. 再由 human reviewer 给出最终结论
5. 只有在结论明确后，才进入下一轮修改
