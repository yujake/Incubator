# agentflow —— 产品根目录（Python 包 + 它的判据、文档与工具链）

> 这是 `Incubator` 仓库里的**产品目录**，也是 `agentflow` 这个 Python 包的检出根
> （`pyproject.toml` 在这里）。git 根在**上一级**：`D:\Incubator`。
> 一句话：**代码在这里，门与工具在这里，规矩也在这里**；判据（`tests/`）只在本地开发机上，
> **不随仓库交付**（业主 2026-11-21 裁定：`agentflow/tests` 不该被提交 git，它只是测试工具）。
> 仓库根读 [`../README.md`](../README.md)。
>
> **为什么这份不叫 `README.md`**：`tests/test_user_quickstart.py`、`test_release_all.py`、
> `test_r8_retired_entries.py`、`test_doc_code_consistency.py`、`test_readme_lint_rule_range.py`
> 解析 `README.md` 的口径都是 **`agentflow/` 优先、仓库根兜底**。一旦这里出现
> `agentflow/README.md`，这几条判据会**静默改读这一份**（它们钉的却是仓库根那一份的
> 子命令数、lint 区间、`cli demo` 标注…）⇒ 判据会红，而红的原因不是文档错了。
> 所以产品根这份叫 `README-PRODUCT.md`：名字让路，判据不动。

## 谁读这份

- **人（运维 / 开发者）** —— 要装它、跑它、改它、发布它。
- **模型（编码 agent）** —— 进门先读 [`AGENTS.md`](AGENTS.md)（FC-27 禁改区），
  再读 [`DEVELOPMENT.md`](DEVELOPMENT.md)（改代码前先读哪几节）。
  角色模型的提示词**不来自本文件**：那是 `src/agentflow/specs/*.py` 的声明与工作区里的
  `skills/`，本文件不重复它们。

## 这个目录里有什么

| 路径 | 是什么 | 谁生成 |
|---|---|---|
| `src/agentflow/` | 产品代码（包本体）。见 [`src/agentflow/README.md`](src/agentflow/README.md) | 人 |
| `tests/` | 判据（pytest）。**本机开发门，不随仓库交付**：干净 clone 里没有这个目录；逐文件说明见本机的 `tests/README.md`（不入库） | 人 |
| `docs/` | 规格、设计理由、历史、验收剧本。**哪份算数看 [`docs/INDEX.md`](docs/INDEX.md)**（本目录刻意不放 README：`docs/*.md` 每一份都必须在 INDEX 里登记，多一份 README 就会让那条判据红） | 人 + 生成物（`ROLE-GUIDE.md` / `SYSTEM-COMPONENTS.md` 由 `tools/write_system_docs.py` 现算） |
| `scripts/` | 长期工具（门、审计、重冻、种子）。见 [`scripts/README.md`](scripts/README.md) | 人 |
| `tools/` | 发布门的编排与一次性探针。见 [`tools/README.md`](tools/README.md) | 人 |
| `data/` | 默认工作区（`--root` 缺省就指这里）的**空台账**，入库。见 [`data/README.md`](data/README.md) | `agentflow.cli init` |
| `seed/` | 文献种子包（历史真机下载成功、抽读无乱码的 PDF）。见 [`seed/README.md`](seed/README.md) | `scripts/seed_corpus.py` |
| `specs/` | 角色声明（duty/policy/boundary/动作表）。**预设机制已于 2026-11-22 退役**：A 的检索式教法住在 `specs/a.py::SEARCH_STYLE`，来龙去脉见 [`docs/PRESET-RETIREMENT.md`](docs/PRESET-RETIREMENT.md) | 人（FC-27 禁改区） |
| `ui/` | 用户端前端工程（Preact + Vite）。见 [`ui/README-DEV.md`](ui/README-DEV.md) | 人 + 生成物（`src/types.ts` / `src/theme/generated/theme.css`） |
| `src/agentflow/web/` | 用户端的样式令牌、两份生成器，以及**入库的构建产物** `static/`（clone 下来不装 node 也能起网页）。见 [`src/agentflow/web/README.md`](src/agentflow/web/README.md) | 人 + `pnpm -C ui build` |
| `src/agentflow.egg-info/` | `pip install -e .` 的元数据。**不要手改**：重装即覆盖 | `pip` |
| `temp/` | 一次性探针与读数（AGENTS.md R2）。**整目录不入库**（`.gitignore` 覆盖；留档证据已全部退役） | 各路人 |
| — | `example/` 已退役（2026-11-21 仓库清洁：取消跟踪，原件在 `draft/archive-example/`） | — |
| `AGENTS.md` | FC-27 禁 AI 区（唯一主题），与 `.noai-paths` 逐条一致 | 人 |
| `DEVELOPMENT.md` | 改代码先读哪几节（入口指针） | 人 |
| `DESIGN*.md`（五份） | **当初为什么这么设计**，不是行为规格 | 人 |
| `NOAI-REVIEW-REGISTER.md` | FC-27 逐条审计台账（历史证据） | 人 |
| `pyproject.toml` / `requirements.txt` | 打包与依赖（Python ≥ 3.11） | 人 |
| `config.yaml` / `settings.example.json` | 配置样例；真 `settings.json` 被忽略（可含 key） | 人 |
| `.noai-paths` / `.noai-approvals.json` | 禁改区清单 / 批准台账（两份都是禁改区，见 AGENTS.md） | 门与签字流程 |

## 怎么用（在本目录下跑）

```powershell
# 装（只跑一次）
python -m pip install -e .    # 运行期依赖由 pyproject.toml 拉取；依赖清单在仓库根 requirements.txt

# 建一个工作区（任何目录都能当工作区；台账落在 <ws>/data/）
python -m agentflow.cli --root D:\Incubator\temp\ws init

# 先看它打算做什么（零写入、零模型调用）
python -m agentflow.cli --root D:\Incubator\temp\ws start --task "研究这个问题：…" --dry-run

# 真跑一趟（有 key 才会调模型；没有 key 会以退出码 2 明说）
python -m agentflow.cli --root D:\Incubator\temp\ws start --task "研究这个问题：…" --budget-usd 5

# 读记录
python -m agentflow.cli --root D:\Incubator\temp\ws status
python -m agentflow.cli --root D:\Incubator\temp\ws verify      # 有 error 级发现 ⇒ 退出码 1
python -m agentflow.cli --root D:\Incubator\temp\ws closing     # 收工门：0 / 1 / 2

# 测（**本机开发门**；tests/ 不随仓库交付，干净 clone 里没有这个目录 ⇒ 发布门第 1 项记 unknown）
python -m pytest -q tests/test_user_quickstart.py
python -m pytest -q

# 门
python scripts/noai_gate.py --git --since HEAD~1
python scripts/lint_rules.py
```

三态纪律贯穿所有命令与脚本：`0` = 查过且一致，`1` = 查过且不一致，
`2` = **没查成**。`2` 不是 `0`。

## 与谁相邻

- **上游（本仓库内）**：仓库根的 [`../AGENTS.md`](../AGENTS.md)（agent 的工作方式规矩 R1–R4）；
  离线演示 `demo/` 已整条退场（2026-11-22 DEMORETIRE，见下"边界"一节），
  要看产物长什么样请读一个真机工作区的 `out/` / `reports/`（本地、不入库）。
- **下游（运行时）**：每个工作区 `<ws>/` 自己是一套：`data/` 台账、`reports/`、`out/`、`sessions/`。
  产品代码**不写工作区以外的地方**。
- **不入库的邻居**：`../draft/`（业主裁定与施工单，本地草稿）、`../projects/`（真机运行数据）、
  `../test/`、`../temp/`、`../_env/`（Lean 工具链）。它们都在 `.gitignore` 里，
  所以**引用它们时必须写明"本地、不入库"**，否则新 clone 的读者找不到。

## 边界（别在这里找的东西）

- **没有 `docs/README.md`**：见上表那一行的理由；文档地图是 `docs/INDEX.md`。
- **`example/`、`temp/` 被 `.gitignore` 覆盖**
  （2026-10-18 业主清理），但因为早已跟踪，`git ls-files` 仍会列出它们。
  ⇒ **往这些目录里新增文件（包括 README）不会进版本库**，除非显式 `git add -f`。
- **`demo/` 已整条退场**（2026-11-22 业主裁定 DEMORETIRE）：`src/agentflow/demo.py`、
  `demo/run/`（旧产物）、`demo/sources/` + `demo/fixtures/`（夹具）、`demo/selftest/`
  （自检素材）全部删除；`agentflow demo` 仍能解析，但只做受控退场（exit 2 + 说明）。
  离线检索（`--provider fixture`）保留，候选清单改由调用方放在
  `<工作区>/fixtures/candidates.json`。
- **`src/agentflow/specs/` 与 `src/agentflow/webui/` 是禁改区族**（FC-27 的 auth-audit 一组）：
  改它们要 2 名 reviewer，见 `AGENTS.md`。
