# Evals

## 目的

eval 层的作用，是通过固定场景和重复重跑来持续改进 agent。

## 结构

- 共享 hard gates：`evals/gates/global.yaml`
- 场景定义：`evals/scenarios/*`
- 来源材料：`knowledge_base/papers/*`
- 运行产物：`evals/runs/`，已加入 `.gitignore`
- 对比报告：`evals/reports/`，已加入 `.gitignore`

## 迭代方法

1. 保持 scenario 集合稳定
2. 一次只修改一个层面
3. 重跑同一批场景
4. 比较 hard gate 结果和 reviewer 结论
5. 只有在质量提升且没有引入回归时，才保留改动
