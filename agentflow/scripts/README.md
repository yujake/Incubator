# scripts/ —— 长期工具（不是某趟真机的取证）

`AGENTS.md` R2 把一次性探针、读数导出放在 `temp/`（不入库、允许被清）。
反过来说：**凡是会被重跑第二次的东西，就不许只活在 `temp/`** —— 它必须在这里，
带 `--help`、带退出码、带一句用法。下面这几个是 2026-11-20 TEMPTIDY 从 `temp/`
提升上来的（原稿见各自 docstring）。

| 脚本 | 干什么 | 用法（在 `agentflow/` 下） |
|---|---|---|
| `safe_comment_fix.py` | tokenize + AST 双闸清理注释/文档串里的成对强调标记（lint R009 口径；FC-27 禁改区默认跳过） | `python scripts/safe_comment_fix.py --check`（只报）/ `--apply`（改并复核） |
| `recompute_prompt_digests.py` | 现算十一格提示词摘要，与 `tests/test_agent_prompts.py` 的冻结表对账 | `python scripts/recompute_prompt_digests.py`（只报）/ `--write`（写回） |
| `refreeze_goldens.py` | 按现值重冻 `tests/golden/` 的 agent 面 / tool 面快照（禁改区动作） | `python scripts/refreeze_goldens.py`（只报）/ `--write`（重冻） |
| `recompute_map_headline.py` | 重算 `docs/READING-MAP.md` 开头那句三格读数 | `python scripts/recompute_map_headline.py`（只报）/ `--write`（写回） |
| `check_wellformed.py` | 查一个工作区的产物有没有畸形（13 类：表 / 侧文件 / 稿头 / 销号名单 / 产物登记），逐条给出文件、位置、逐字读数 | `python scripts/check_wellformed.py --root projects/<ws> [--kind ...] [--json]`（0=全 ok / 1=有畸形 / 2=没查成） |
| `recon_b.py` | RECON-B：真机一趟之后的七项只读对账（账目 / unattributed / 八格 / 签 / 非平凡度 / 销号义务 / 会话归口），人读表 + JSON；口径文档见 [`RECON-B.md`](RECON-B.md) | `python scripts/recon_b.py --root projects/<ws> [--outdir ...] [--no-product] [--print-json]`（0=七项都读到 / 2=至少一项 unknown） |

共同约定（与仓库三态纪律同一条）：`0` = 查过、一致；`1` = 查过、不一致；
`2` = 没查成（读不到 / import 不了）。**没查成不是一致。**

判据面：`tests/test_temp_is_not_a_workshop.py` 的 `test_scripts_tools_answer_help`
会逐个跑上表的 `--help` —— 新增长期工具时把它加进那张表，否则它会从判据面上消失。
