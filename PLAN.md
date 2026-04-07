# PLAN

## 1. 目标

本计划的目标不是把当前仓库改造成“零人工写代码”的系统，而是吸收 OpenAI 在 harness engineering 中真正可迁移的部分，把当前项目从：

- 有完整工作流的多智能体应用

推进为：

- 评测驱动、可验证、可回归、可持续纠偏的可靠代理系统

本仓库的 north star 定义为：

`让合同审查结果可验证、可回溯、可覆盖全部审查项，并且任何改动都可以通过评测证明是否变好。`


## 2. 对齐的 OpenAI 实践

本计划对齐的是 OpenAI 文章中以下几条核心思想，而不是照搬它们的组织方式：

- Repository knowledge is the system of record
- Agent legibility is the goal
- Mechanical enforcement beats informal guidance
- Testing, validation, review, and recovery are part of the harness
- Entropy must be controlled continuously

本计划不会照搬的部分：

- 不追求零人工代码
- 不允许自动合并生产级变更
- 不采用低阻塞 merge gate 哲学
- 不把 coding-agent 工作流直接等同于合同审查工作流


## 3. 当前状态

当前仓库已经具备良好的骨架：

- 6 阶段工作流
- Planner / Orchestrator / Reflector / Summarizer 角色分工
- `pageindex` / `llamaindex` / `evidence` 三种检索模式
- Web + CLI 双入口
- 工作流日志、导出链路、结构化 API

但距离 OpenAI 风格的 harness 还有明显差距：

### 3.1 验证层仍然偏软

- 结果可以生成，但没有硬性 verifier 阻断错误结果进入汇总与导出
- 覆盖率只是报告附录，不是 release gate
- 反思机制仍然主要依赖 LLM 审核，而非机械校验

### 3.2 Repo 还不是 agent 的系统记录

- 缺少根目录 `AGENTS.md`
- 缺少围绕质量、可靠性、执行计划的稳定知识入口
- 现有文档可读，但还未形成 progressive disclosure 的知识地图

### 3.3 日志是事后记录，不是可评测 trace

- 现在的 workflow log 适合人工复盘
- 但还不足以支持 trace grading、failure mode 分析、回归对比

### 3.4 缺少系统级 eval 基线

- 目前没有 benchmark 数据集
- 没有固定指标
- 没有“改完以后是否真的更好”的可重复运行机制

### 3.5 缺少机械化边界约束

- 架构边界主要写在文档中
- 还没有将依赖方向、输出结构、质量要求写成 hard checks

### 3.6 缺少持续垃圾回收

- 没有周期性清理 drift、无效规则、失效文档、劣化模式的机制


## 4. 总体策略

整体路线定义为：

`Eval-Driven Reliability Harness`

核心思想：

1. 先定义质量目标，再改 agent
2. 先建立 benchmark，再调 prompt / tool / loop
3. 先让输出可验证，再让结果更“聪明”
4. 先把规则编码成 grader / verifier / checks，再写进 prompt
5. 让 repo 内文档、规则、计划、评测成为 agent 可直接读取的系统记录


## 5. 成功标准

完成本计划的最低成功标准如下：

- 所有审查项都有结论，`coverage = 100%`
- 每个问题都有可回溯证据
- 不允许无证据问题进入最终报告
- 关键回归指标可重复运行
- 任意一次改动都可以回答“有没有变好”
- 质量规则不再只靠 prompt 维持，而是由机械检查保证

建议追踪的核心指标：

- `coverage`
- `issue_recall`
- `evidence_precision`
- `unsupported_claim_rate`
- `location_accuracy`
- `latency_p95`
- `tokens_per_criterion`
- `artifact_success_rate`


## 6. 分阶段改造计划

### Phase 0 - 建立评测基线

目标：

- 让后续所有改造都能被量化评估

工作内容：

- 新增 `evals/` 目录
- 建立小规模 benchmark 数据集
- 定义统一指标和评分规则
- 提供一键运行评测脚本
- 对三种检索模式建立初始基线

建议新增：

- `evals/README.md`
- `evals/datasets/`
- `evals/graders/`
- `scripts/run_evals.py`
- `docs/QUALITY_SCORE.md`

验收标准：

- 可以对同一批样本重复跑评测
- 可以输出模式级比较结果
- 可以记录每次运行的分数、时延、token 和错误


### Phase 1 - 把 repo 改成 agent 可读的 system of record

目标：

- 让 agent 从 repo 内就能找到规则、计划和质量标准

工作内容：

- 在仓库根目录新增 `AGENTS.md`
- 只把 `AGENTS.md` 作为目录，不作为大而全说明书
- 重组文档，形成 progressive disclosure
- 把执行计划、质量规则、可靠性规则纳入 repo

建议新增或调整：

- `AGENTS.md`
- `docs/PLANS.md`
- `docs/RELIABILITY.md`
- `docs/SECURITY.md`
- `docs/exec-plans/active/`
- `docs/exec-plans/completed/`

验收标准：

- 新 agent 进入仓库后，能从 `AGENTS.md` 找到主要知识入口
- 架构、计划、质量、可靠性均有稳定落点
- 文档不再只是面向人，而是同时面向 agent


### Phase 2 - 把输出改成可机械验证对象

目标：

- 让每条审查结论都能被 verifier 检查

工作内容：

- 将每个 criterion 的输出从自由文本改为严格 JSON
- 补齐结构化字段
- 新增 verifier，对证据、位置、结论完整性进行硬校验
- verifier 不通过时，禁止进入汇总与导出

建议修改：

- `agents/orchestrator.py`
- `agents/prompts/cn_prompts.py`
- `main_workflow/main_workflow.py`
- `api/models/schemas.py`

建议新增：

- `tools/verification/criterion_verifier.py`
- `tools/verification/report_gate.py`
- `tools/verification/schemas.py`

结构化字段建议至少包括：

- `criterion_id`
- `verdict`
- `reason`
- `evidence_quote`
- `evidence_span`
- `location`
- `confidence`

验收标准：

- 每条结论都能通过 schema 校验
- 每个问题都具备证据字段
- 无证据问题无法进入报告
- 失败结果会进入修复循环，而不是静默通过


### Phase 3 - 升级 review / reflection 为真正的质量 gate

目标：

- 让 Reflector 从“建议者”变成“守门员”

工作内容：

- 修复 JSON 解析失败即 `PASS` 的逻辑
- 引入显式 grader rubric
- 将 review 输出标准化
- 允许 judge 使用独立配置，降低同源偏差
- 将 verifier 失败与 reflector 反馈统一进入 repair loop

建议修改：

- `agents/reflector.py`
- `agents/base_agent.py`
- `agents/prompts/cn_prompts.py`

建议新增：

- `agents/grader.py`
- `docs/review_rubrics/criterion_review.md`

验收标准：

- Reflector 失效不会被视为通过
- review 结果可结构化记录
- repair loop 有明确退出条件
- 同一错误模式能被稳定复现和修复


### Phase 4 - 把日志升级成 trace，并接入 trace grading

目标：

- 从“任务日志”升级到“可评分轨迹”

工作内容：

- 将 workflow logger 升级为结构化 trace logger
- 每个阶段都记录 span 级信息
- 建立 trace grader
- 让一次运行可以被整体评分，而不是只能看最终报告

建议修改：

- `main_workflow/workflow_logger.py`
- `main_workflow/main_workflow.py`
- `mcp_service/mcp_client/mcp_minimal.py`

建议新增：

- `logs/traces/`
- `evals/trace_graders/`
- `scripts/grade_traces.py`

trace 级信息建议包括：

- criterion id
- retrieval mode
- tool calls
- sub-agent output
- reflector output
- verifier output
- retries / repair rounds
- final verdict

验收标准：

- 每次运行都可导出结构化 trace
- trace 可用于 failure mode 分类
- trace grader 能支持回归检测


### Phase 5 - 将架构边界和质量要求写成机械约束

目标：

- 让“规则”成为自动执行的系统组成部分

工作内容：

- 将关键依赖方向变成 structural checks
- 对输出结构、文档完整性、关键字段、上传安全做 hard checks
- 将质量规则从 prompt 提升为脚本 / lint / test

建议新增：

- `checks/architecture_check.py`
- `checks/report_schema_check.py`
- `checks/docs_freshness_check.py`
- `tests/`

验收标准：

- 违反关键架构边界会被直接发现
- 缺字段、错字段、脏文档有明确失败信号
- 规则具备可维护、可扩展的实现方式


### Phase 6 - 建立持续垃圾回收和质量盘点机制

目标：

- 控制 entropy，持续修正 drift

工作内容：

- 周期性扫描失败模式
- 发现和标注失效文档
- 自动更新质量盘点文档
- 持续找出 unsupported claims 的高发模式
- 形成例行的质量回顾与修正流程

建议新增：

- `scripts/doc_gardening.py`
- `scripts/failure_mode_report.py`
- `docs/QUALITY_SCORE.md`
- `docs/tech-debt-tracker.md`

验收标准：

- 可以周期性输出质量状态
- 质量下降有可见信号
- 常见坏模式能被持续清理，而不是堆积


## 7. 建议实施顺序

建议按以下顺序实施，而不是并行乱改：

1. Phase 0
2. Phase 2
3. Phase 3
4. Phase 4
5. Phase 1
6. Phase 5
7. Phase 6

原因：

- 没有 benchmark，就无法判断优化是否真实有效
- 没有结构化输出和 verifier，就无法建立硬质量门槛
- 没有 trace，就无法定位失败模式
- 没有 repo knowledge map，就无法把经验沉淀成长期杠杆


## 8. 第一个迭代的最小范围

第一轮不求“大而全”，只完成一个最小可用版本：

- 建 benchmark
- 改 criterion 输出为结构化 JSON
- 引入 verifier
- 修复 reflector 的软失败通过问题
- 让最终报告必须通过质量 gate

如果第一轮完成，项目就会从：

- 可以运行

变成：

- 可以证明自己有没有变好


## 9. 风险与注意事项

### 9.1 不要过早复杂化 agent 拓扑

问题：

- 过早引入太多角色，会让系统更难评测

策略：

- 优先提升输出可验证性和回归能力

### 9.2 不要把 prompt 当主控制面

问题：

- prompt 是必要的，但不是最稳定的约束层

策略：

- 规则优先落成 grader、verifier、lint、test

### 9.3 不要只做报告美化

问题：

- 报告更漂亮不等于结果更可靠

策略：

- 所有工作优先服务于质量指标

### 9.4 不要先追求完全通用

问题：

- 完全通用通常会牺牲首个场景的可落地性

策略：

- 先在合同审查上建立“评测驱动可靠性 harness”
- 再抽象出可复用模式


## 10. 对外可复用的总结方式

本项目完成上述改造后，对外分享不建议描述为：

- “我们做了一个合同审查 agent”

更建议描述为：

- “我们把领域规则转成 grader 和 verifier，用评测驱动 agent 的生成、验证、修复和回归。”

一句话版本：

`我们不是在堆 agent 角色，而是在构建一个评测驱动的可靠性 harness。`


## 11. 立即下一步

本计划落地后的第一个具体执行动作应为：

1. 建立 `evals/` 基线
2. 选出 20-30 份合同样本
3. 为每份样本标注 5-10 个高风险 criterion
4. 固定评分指标
5. 用当前系统跑出第一版 baseline

在完成这一步之前，不建议进行大规模 prompt 改写或 agent 角色扩张。
