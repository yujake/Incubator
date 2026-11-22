# tools/ —— 发布门与一次性探针（与 `scripts/` 的分工）

> 同是"脚本"，两个目录的定位不同：
> **`scripts/` = 长期工具**（会被重跑第二次、带 `--help` 与退出码、有判据盯着）；
> **`tools/` = 发布门的编排层 + 一批一次性探针**（探针保留是因为它们复算过历史读数）。

## 谁读

要跑发布门、要复核某个历史读数、或要改门本身的人。
注意：本目录里有 **FC-27 禁改区**文件（`release_all.py`、`run_each_test_file.py`、
`coverage_zero_test.py`、`vocab_census.py`），改它们要 2 名 reviewer（见 `../AGENTS.md`）。

## 文件

| 文件 | 是什么 |
|---|---|
| `release_all.py` | **一键发布检查的编排层**：把全部门串成一条命令并做三态汇总（0 pass / 1 fail / 2 unknown）。`--skip` 的步骤记 `unknown`，不记 `pass` |
| `run_each_test_file.py` | 发布门的 `per-file` 步：逐文件跑测试，把"顺序依赖 / 跨文件状态泄漏"变成可判定的门。**需本机有 `tests/`**：tests 不随仓库交付（业主 2026-11-21 裁定），缺目录 ⇒ `unknown` |
| `coverage_zero_test.py` | 发布门的 `coverage` 步：按 AST 分档找出"零直接测试"的公开函数 |
| `frontend_gate.py` | 发布门的 `frontend` 步：类型检查 + 构建 + 产物新鲜度 |
| `verify_role_specs.py` | 核对 `docs/ROLE-SPECS.md` 的结构完整性（逐节子节、引用是否存在） |
| `write_system_docs.py` | 生成 `docs/ROLE-GUIDE.md` 与 `docs/SYSTEM-COMPONENTS.md`（两份生成物） |
| `vocab_census.py` | 受控词表普查（lint R011 的实现本体） |
| `repo_survey.py` | 仓库体量巡检（只读）：多大、哪里在长、注释够不够 |
| `make_demo_dataset.py` | 造一个"够丰富"的演示数据集，用于端到端验证 C/D/pipeline |
| `inspect_pipeline.py` | 流水线结果速查（问题表、报告表、D 报告里的证据片段） |
| `smoke_real_provider.py` | 真实网络冒烟：只做搜索，不下载 |
| `probe_*.py` | 历史探针：AMS/arXiv 下载行为、OCR 链路、缺口台账与提交、rebuild 丢字段… 每个都写明它当时量的是什么 |

## 怎么用

```powershell
# 全部门（很慢；CI 用 --since 给禁改区门一个基线）
python tools/release_all.py --since HEAD~1

# 只跑几步 / 跳过几步（跳过的记 unknown）
python tools/release_all.py --only role-specs,coverage
python tools/release_all.py --skip coverage

# 单跑某一道门
python tools/verify_role_specs.py --root . --json
python tools/frontend_gate.py

# 生成两份给人读的文档（改了角色声明之后）
python tools/write_system_docs.py
```

> **本机开发门**：`release-check` 的第 1 项（全量测试）与 `per-file` 步要求本机有
> `tests/`。tests 不随仓库交付（业主 2026-11-21 裁定：不入 git），干净 clone 里缺这个目录
> ⇒ 这两处记 `unknown` 并写明原因，**不是 pass**。

步骤 key 与顺序以 `release_all.build_steps()` 现算为准：
```powershell
python -c "import sys,pathlib;sys.path.insert(0,'.');from tools.release_all import build_steps;print([s.key for s in build_steps(pathlib.Path('.').resolve())])"
```

## 邻居

上游：`../scripts/`（门禁、linter、重冻等长期工具，`release_all` 调用它们）。
下游：CI 与人读的发布报告。`inspect_pipeline.py` / `make_demo_dataset.py` 的默认落点在
`../test/`（不入库），跑它们之前先看各自的默认目录。
