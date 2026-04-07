# PLAN

## 目标

这个计划的目标，不是把当前仓库改造成“完全无人值守写代码”的系统，而是吸收 OpenAI 在 harness engineering 中真正可迁移的部分，把当前项目逐步收敛成一个：

- 评测驱动
- 可验证
- 可回归
- 可持续改进

的企业微信文档 agent。

当前项目的 north star 是：

`让文档生成、文档修改、回复质量和文档连续性都能被固定场景稳定验证。`

## 核心原则

- Repository knowledge is the system of record
- Agent legibility is the goal
- Mechanical enforcement beats informal guidance
- Testing、validation、review、recovery 都属于 harness 的组成部分
- Entropy 需要持续控制

不追求的方向：

- 零人工写代码
- 自动合并生产级变更
- 只有 prompt、没有验证层的“玄学调参”

## 当前差距

当前仓库已经具备基础运行骨架，但距离一个稳定的 harness 还有差距：

- 缺少固定 eval 场景基线
- 缺少共享 hard gates
- 缺少稳定的 reviewer 规则
- 缺少 run artifacts 和版本比较层
- prompt、tool、memory、flow 的迭代没有统一证据链

## 总体策略

项目按 `Eval-Driven Reliability Harness` 推进。

执行顺序：

1. 先固定场景，再改 agent
2. 先建立 benchmark，再调 prompt / tool / loop
3. 先让输出可验证，再追求“更聪明”
4. 先把规则写成 gates / checks / docs，再写进 prompt
5. 把 repo 文档、规则、计划、评测变成 agent 可读的 system of record

## 成功标准

- 固定场景能够重复重跑
- 关键 hard gates 可以稳定通过
- 每次改动都能回答“是否真的变好”
- 文档连续性可以通过 `doc_id`、`doc_url`、`doc_name` 验证
- 回归问题能被及时发现，而不是事后凭感觉复盘

## 分阶段计划

### Phase 0

建立最小 eval 基线：

- 固定场景
- 固定 hard gates
- 固定 reviewer rubric
- 固定 run artifacts

### Phase 1

把 repo 改成 agent 可读的 knowledge base：

- `AGENTS.md`
- `docs/*.md`
- `prompts/system/*.md`
- `evals/gates/*`
- `evals/scenarios/*`

### Phase 2

把运行产物变成可比较对象：

- reply
- tool trace
- doc binding
- gate result
- reviewer result

### Phase 3

让迭代遵守“单层改动、整套回归”的规则：

- 一次只改 prompt / tool / memory / flow 的一个层面
- 每次都用同一批场景回归
- 只有在变好且无明显回归时才保留改动

## 当前最小可执行版本

第一轮不做全套自动 grader，只做：

- 共享 hard gates
- 固定 scenarios
- 中文 system prompt
- 中文业务知识文档
- 可重复的回归方式

做到这一步后，项目就会从“能跑”变成“能证明自己有没有变好”。
