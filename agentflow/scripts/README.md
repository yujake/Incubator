# scripts/ —— 长期工具（不是某趟真机的取证）

`AGENTS.md` R2 把一次性探针、读数导出放在 `temp/`（不入库、允许被清）。
反过来说：**凡是会被重跑第二次的东西，就不许只活在 `temp/`** —— 它必须在这里，
带 `--help`、带退出码、带一句用法。

共同约定（与仓库三态纪律同一条）：`0` = 查过、一致；`1` = 查过、不一致；
`2` = 没查成（读不到 / import 不了）。**没查成不是一致。**

## 按用途分组

| 用途 | 脚本 |
|---|---|
| **门禁** | `noai_gate.py`（FC-27 禁改区门）、`lint_rules.py`（R001–R012 机械规则）、`release_check.py`（发布前一键检查） |
| **发布 / 重冻** | `refreeze_goldens.py`（重冻两份"面"快照，**禁改区动作**）、`golden_diff.py`（逐格 diff，重冻前必须看过）、`recompute_prompt_digests.py`、`recompute_map_headline.py` |
| **审计 / 读数** | `recon_b.py`（真机一趟之后七项对账，口径见 [`RECON-B.md`](RECON-B.md)）、`check_wellformed.py`（产物畸形，逐类给出文件/位置/逐字读数）、`sign_audit.py`、`verify_audit.py`、`usage_ledger_audit.py` |
| **真机 / 证据** | `seed_corpus.py`（种子包清点与按 manifest 复算）、`manuscripts_query.py`、`pytest_all.py`（分 N 路并行全量，**需本机有 `tests/`**：tests 不随仓库交付）、`warm_prompt_cache.py` |
| **签字 / 登记** | `noai_batch_sign.py`（批量签字前端）、`render_registration_skeletons.py`（只打印缺口与账骨架） |
| **代码整理** | `safe_comment_fix.py`（清理成对强调标记，FC-27 默认跳过）、`docstring_patch.py` |

## 高频几条的用法（在 `agentflow/` 下）

```powershell
python scripts/noai_gate.py --git --since HEAD~1      # 0 clean / 1 命中需人审 / 2 没查成
python scripts/lint_rules.py                          # 机械规则；--strict 把 warning 也算失败
python scripts/refreeze_goldens.py                    # 只报差异；--write 才重冻（禁改区，需人审）
python scripts/golden_diff.py                         # 两份快照逐格 diff（人读）
python scripts/recon_b.py --root projects/<ws>        # 真机一趟之后的七项对账
python scripts/check_wellformed.py --root projects/<ws> [--kind ...] [--json]
python scripts/seed_corpus.py --verify                # 按 MANIFEST.json 重算 sha256/字节/抽读
```

## 判据面（新增脚本时要一起改的地方）

`tests/test_temp_is_not_a_workshop.py::test_scripts_tools_answer_help` 会逐个跑
`SCRIPTS_TOOLS` 那张表里的 `--help` —— 新增长期工具时把它加进那张表，否则它会从判据面上消失。
