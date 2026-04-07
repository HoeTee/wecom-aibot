# Evals

## 目的

eval 层的作用，是通过固定场景和重复重跑来持续改进 agent。

## 结构

- 共享 hard gates：`evals/gates/global.yaml`
- 场景定义：`evals/scenarios/*`
- 来源材料：`knowledge_base/papers/*`
- 运行产物：`evals/runs/`，已加入 `.gitignore`
- 对比报告：`evals/reports/`，已加入 `.gitignore`
- human review 模板：`evals/review_template.md`

## 当前 workflow

1. 保持 scenario 集合稳定
2. 一次只修改一个层面
3. 重跑同一批场景
4. 先检查 hard gates
5. 由 human reviewer 给出最终结论
6. 根据最终结论决定下一轮是否继续修改

## 当前 review 方式

当前阶段不要求复杂打分，也不要求自动 evaluator。

human reviewer 只需要给出：

- `pass` 或 `fail`
- 最大问题属于内容、格式、回复、连续性中的哪一类
- 一句简短说明

如果后面稳定了，再逐步引入更细的 rubric 或 LLM evaluator。
