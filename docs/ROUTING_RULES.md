# 路由规则

## 目的

这份文档只写当前代码里真正存在的路由规则，不写理想状态下的复杂对话树。

## 入口级分流

当前只有两条后端入口：

- `POST /chat`
- `POST /knowledge-base/upload`

它们的分流依据不是语义，而是消息载体：

- 文本消息走 `/chat`
- 文件消息走 `/knowledge-base/upload`

## `/knowledge-base/upload` 的硬规则

这条链路是确定性的，不走 LLM：

1. 必须有文件
2. 必须有文件名
3. 扩展名必须是 `.pdf`
4. 文件头必须以 `%PDF-` 开头
5. 校验通过后写入本地知识库

上传完成后会记录：

- `file_name`
- `stored_path`
- `file_sha256`
- `upload_action`
- `matched_file_name`
- `matched_stored_path`

若 `upload_action` 是 `added` / `replaced`，后端会再调 `schedule_index_rebuild(file_name)` 触发后台索引重建，并写入 `index_rebuild_scheduled` flow 事件。`unchanged` / `duplicate_content` 不动 `knowledge_base/*.pdf`，不触发重建。

上传能力是产品固有能力而非 agent 工具——prompt 要求 agent 在用户说"我要上传 / 帮我把 PDF 加进知识库"时直接指引用户在个人聊天窗口发送文件，而不是回"不支持"。

## `/chat` 的主路由

`backend/flow/chat.py` 的主顺序是：

1. 生成 `request_id`
2. 计算 `session_id`
3. 记录 `request_received`
4. 检查是否命中短路规则
5. 如果没有短路，则进入 agent flow

## 当前真正存在的短路规则

### 最近上传 PDF 的 follow-up 确认

如果同时满足：

- 用户文本看起来是在说“把这份文档 / 这个 PDF 加入知识库”
- 最近 30 分钟内有上传记录

那么当前实现不会再进入完整的 agent tool loop，而是直接返回确认结果。

这里的回复会根据最近上传状态生成，例如：

- 已加入知识库
- 已是同名同内容
- 与知识库中某文件内容重复
- 同名文件已更新

## 非短路请求如何进入 agent flow

### 1. 是否注入当前绑定文档

当前只有一个确定性的规则：

- 如果命中“重新生成一份文档 / 新建一份文档”这类 fresh request，就不把当前绑定文档注入 memory
- 其它情况默认注入当前绑定文档

这条逻辑来自：

- `backend/policy/document.py`

### 2. 连接 tool runtime

当前 runtime 会：

- 加载外部 MCP server 配置
- 连接所有可用的外部 server
- 补充本地 KB/doc/RAG 工具

### 3. 加载会话状态

当前会注入三类状态：

- 当前绑定文档
- 最近若干轮对话与 tool 摘要
- 最近上传文件

### 4. 生成 `intent packet`

由 LLM 把请求分类成这些 family 之一：

- `knowledge_base`
- `document`
- `smartsheet`
- `upload_followup`
- `general`

这是当前主路由的核心依据。  
Python 代码没有实现一棵完整的关键词规则树。

## 当前 Python 侧的额外防线

### 智能表格已有行修改/删除直接拦截

如果同时满足：

- `intent_family == smartsheet`
- 文本里像是在要求修改或删除某一行

当前直接回复不支持，不再继续调用工具。

这个拦截来自：

- `backend/policy/smartsheet.py`
- `backend/flow/chat.py`

### 文档/表格写入后补链接

如果本轮有工具真正修改了企微文档或智能表格：

- 回复里没有链接
- 但当前 session 已经绑定到了文档 URL

系统会自动把链接补到最终回复里。

## 知识库请求当前如何理解

当前知识库相关路由主要依赖 `intent packet + prompt`，但底层工具边界是明确的：

- 文件列举和相关匹配走 `kb__list_files` / `kb__match_related_files`
- 导出原 PDF 走 `kb__export_file`
- 重命名和删除走 `kb__rename_file` / `kb__delete_file`

当前代码没有实现这些内容：

- 复杂的多轮编号确认状态机
- 一个独立的 Python 知识库关键词路由器
- “查看 PDF 内部正文”的单独能力

## 文档请求当前如何理解

当前文档请求也主要依赖 `intent packet + prompt`。

但当前实现有两个稳定前提：

1. 默认优先复用当前绑定文档
2. 用户明确说“重新生成 / 新建一份”时，才不注入旧文档

后续是否创建新文档、是否追加章节、是否替换章节，由 agent 在工具选择时决定。

## 智能表格请求当前如何理解

当前可识别的 intent 仍包括：

- `smartsheet.create`
- `smartsheet.update_schema`
- `smartsheet.add_records`

但请按当前真实实现理解边界：

- 路由可以识别成 `smartsheet`
- 当前绑定对象可以保存智能表格 URL
- 具体能否成功执行，取决于外部 MCP server 是否真的有对应工具
- 已有行读取、修改、删除仍然不支持

## 当前没有实现的东西

以下内容不要再当成“已硬编码规则”写进其它文档：

- 每个模糊意图都有固定澄清模板
- 每个知识库动作都有严格的 Python 确认状态机
- 每个文档动作都有固定的多步确认顺序
- 所有 follow-up 都由规则引擎决定

当前真实情况是：

- 少量高风险情况由 Python 规则硬拦
- 大部分意图分流仍然依赖 `intent packet`、memory 和系统 prompt
