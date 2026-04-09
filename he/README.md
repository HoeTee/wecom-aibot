# HE

`he/` 是这个仓库的 Harness Engineering 独立层。

它不属于运行时层级，也不应被生产代码依赖。

## 目录

```text
he/
  README.md
  review_template.md
  gates/
  scenarios/
  runs/
  reports/
```

## 职责

- `gates/`：共享 hard gates
- `scenarios/`：固定回归场景
- `runs/`：单次运行证据包
- `reports/`：总报告和 maintenance 输出
- `review_template.md`：最终 human review 模板
- 业务场景前还应先做 required stdio MCP boot preflight

## 执行入口

HE 的执行脚本仍保留在根目录 `scripts/`：

- `scripts/run_eval_case.py`
- `scripts/check_layers.py`

这是为了保持脚本文件名和调用方式稳定。
