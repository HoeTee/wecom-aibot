# 流程

## 目的

这份文档记录当前仓库里真实存在的端到端流程。

## 流程 1：用户上传 PDF

入口：

- 企业微信文件消息
- `gateway/long_connection.ts`
- `/knowledge-base/upload`

实际顺序：

1. 网关下载文件
2. 后端校验文件名、扩展名和 PDF 文件头
3. 把 PDF 写入 `knowledge_base/`
4. 计算上传结果
5. 保存最近上传记录
6. 返回简短确认

当前 `upload_action` 可能是：

- `added`
- `replaced`
- `unchanged`
- `duplicate_content`

## 流程 2：上传后用户马上问“这份文档是不是已经加入知识库了”

实际顺序：

1. `/chat` 收到文本消息
2. 先检查最近 30 分钟内是否有上传记录
3. 如果命中 follow-up 模式，直接根据最近上传状态回复
4. 不进入完整的 agent tool loop

这是当前唯一明确存在的 upload follow-up 短路流程。

## 流程 3：普通文本消息

入口：

- 企业微信文本消息
- `gateway/long_connection.ts`
- `/chat`

实际顺序：

1. 生成 `request_id`
2. 计算 `session_id`
3. 连接外部 MCP server
4. 注册本地 KB/doc/RAG 工具
5. 加载 memory context 和 recent chat history
6. 生成 `intent packet`
7. 进入 agent tool loop
8. 保存 tool call、flow event 和最终回复

## 流程 4：继续编辑当前文档

这是当前默认路径，不需要额外 Python 规则确认。

实际依赖：

- `session_docs` 里已经有当前绑定文档
- 本轮请求不是明确的新建文档请求

当前效果：

- 绑定文档会被注入 memory
- agent 更容易继续操作这份文档，而不是新建一份

## 流程 5：明确要求“重新生成一份文档”

当前触发条件来自 `backend/policy/document.py`，例如：

- “重新生成文档”
- “新建一份文档”

实际顺序：

1. `/chat` 识别为 fresh document request
2. 不把当前绑定文档注入 memory
3. agent 按新文档语义选工具

注意：

- 这里不是直接新建文档
- 只是避免旧文档上下文强行干扰本轮决策

## 流程 6：知识库文件管理

当前真实能力包括：

- 列表
- 相关匹配
- 导出原 PDF
- 重命名
- 删除

实际执行路径：

1. agent 识别成知识库 family
2. 调本地 `kb__*` 工具
3. 本地工具进入 `backend/tools/kb_cli.py`
4. 在 `knowledge_base/` 上执行真实文件操作

其中：

- 导出会附带文件附件
- 重命名和删除要求 `confirmed=true`

## 流程 7：文档正文追加 / 覆盖 / 改写

当前流程已经简化：

1. agent 根据当前绑定文档（或本轮新建的文档）选目标 `docid`
2. 直接调用外部 MCP 的 `edit_doc_content`
3. `content_type` 统一走纯文本写入（`1`），运行时硬拦截其它取值

说明：

- 本地旧版的 `doc__append_section` / `doc__preview_replace` / `doc__replace_section` / `doc__expand_section` 已从 agent 工具面下线，运行时同时加了硬拦截。所有“追加 / 覆盖 / 改写”都映射到一次 `edit_doc_content`
- 如果需要“基于已有正文续写”，当前实现不会回读文档；模型根据对话上下文与来源材料生成完整的新正文，整体写回

## 流程 8：智能表格请求

当前真实情况是：

1. LLM 可以把请求识别成 `smartsheet` family
2. 当前绑定对象也可以是智能表格 URL
3. 具体创建字段、追加记录等动作仍依赖外部 MCP server

已经硬编码拦截的只有一类：

- 修改或删除已有行

命中后会直接回复不支持。

## 流程 9：本轮操作后自动补链接

如果本轮成功创建或修改了企微文档/智能表格：

1. tool 结果会更新 `session_docs`
2. 最终回复如果没带链接
3. `backend/flow/chat.py` 会自动把当前绑定链接补上

## 流程 10：错误与超时

### agent 超时

当前 `Agent.chat(...)` 有总超时限制。  
超时后会返回一条安全失败回复，不会继续假装完成。

### 工具参数连续生成失败

如果 LLM 连续两轮生成非法 JSON tool arguments：

1. agent 会先要求模型重试
2. 第二次仍失败则停止并返回失败回复

### MCP 连接失败

如果外部 MCP server 连接失败：

- optional server 会被跳过
- required server 会直接抛错
- stdio server 的关键排查入口是 `data/logs/mcp/<server_name>_stderr.log`
