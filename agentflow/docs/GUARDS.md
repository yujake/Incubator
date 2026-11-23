# 三件只读护栏：产物畸形 / 系统写点 / 种子投放（2026-11-21 新增，最小说明）

> 这三件同一天落地，此前没有任何文档面说它们是什么。本文只做**入口说明**：
> 每件给一句话、代码落点、读数入口与判据。**不铺开写**设计与取舍 —— 设计在各自
> 模块 docstring 里，改行为读那里。

## 1. `wellformed/` —— 产物畸形的统一判据（MALFORM 路）

- **是什么**：把"这个工作区里的产物有没有畸形"收成一处判据 —— 15 类产物
  （`KINDS`：vsigns / literature / relations / statements / lit_candidates / tasks /
  usage_ledger / sessions / manuscripts / proof_reports / acceptance / artifacts /
  roster_retired / layout / paper_package），每类一根轴：形状 / 词表 / 内部一致性 / 跨表指向 / 落点布局。
- **三态**：`ok` / `malformed`（带 Finding：文件、位置、逐字读数、怎么改）/
  `unchecked`（没查成）。`unchecked` 不折成 `ok`。
- **落点**：`src/agentflow/wellformed/`（`__init__.py` 收口，规则按类别各一个模块；
  `RULES[kind][name]` 是登记表）；只读读数面接在 `statusreport.collect` 的
  `wellformed` 一格；**不进收工门、不加 blocker**（业主 2026-11-21：畸形要看得见，
  不是再拦一道）。
- **读数入口**：`python scripts/check_wellformed.py --root projects/<ws> [--kind ...] [--json]`
  （0 = 全 ok / 1 = 有畸形 / 2 = 没查成）。
- **判据**：`tests/test_wellformed_tool.py`、`tests/test_reading_map.py`。

## 2. `sysguard.py` + `sysresidue.py` —— 系统自动产物的写点读数（SYSGUARD / SYSRESIDUE 路）

- **是什么**：系统自己写的字段与文件，必须由**写点**保证每一格（不让模型补、不靠读侧宽容）。
  `sysguard` 给这一族写口一个统一读数形状（`ok` / `refused` / `derived` / `unchecked`），
  `sysresidue` 是剩下四处写点的校验：`literature.processed`、`bits.evidence.optimized_by_proof`、
  `runs.spend` 自报对账、`literature.dedup_key`。
- **落点**：`src/agentflow/sysguard.py`（`WriteReading` / `write_reading` / `record_reading` /
  `read_readings` / `summarize`）、`src/agentflow/sysresidue.py`（四处：`settle_processed` /
  `optimized_cells_problems` / `spend_reconcile` / `literature_dedup_cells`）。
- **台账**：`<工作区>/out/sysguard/write-readings.jsonl`（只读读数，不是表、不进重建、
  不进 `ARTIFACTS.jsonl`）。`refused` / `derived` 计数进 `errorstats` 过程类目
  `write_point_guarded`（看得见、不计错、不当门）。
- **判据**：`tests/test_sysguard_write_points.py`、`tests/test_sysresidue_write_points.py`。

## 3. `seedinject.py` —— 文献种子投进新工作区的输入区（SEEDINJECT 路）

- **是什么**：把 `agentflow/seed/literature/` 这份种子包原样复制进**新建**工作区的
  **输入区 `reference/`**，并在同一目录落一份 `SEED-README.md`。**只放文件、不写台账**：
  不打开也不创建 `data/literature.json`（业主 2026-11-21：不直接入库 —— 判收是 A 的动作）。
- **为什么不落 `library/`**（业主 2026-11-22）：「为什么你直接往library里塞文献？这会导致
  A 侧维护的文献库结构异常」。`library/` 是**已登记书架**（`literature.path` 指向它），
  只放被登记行引用到的文件；未登记的种子占住书架位置就是结构异常。
- **开关**：`agentflow start --seed-literature` / `agentflow init --seed-literature`，
  默认**关**；只对"真的是新建"生效（`data/` 已在 ⇒ 不投）；`reference/SEED-README.md`
  在 ⇒ 幂等返回读数；根上还有改前形态的 `SEED-README.md` ⇒ 拒投（不许两种形态混住）。
- **声明**：用户说"这个文件夹里的都是可靠参考文献"时，把
  `{"paths": ["reference/"]}` 落到工作区根的 `RELIABLE-REFERENCES.json`（`verbatim` 用用户
  原话）；投放**不替用户写声明**（那是用户的点名，不是投放的副作用）。
- **书架卫生判据**：`unregistered_library_files` —— `library/` 里出现没有 `literature` 行
  引用的文件即结构异常（判据 `tests/test_seed_lands_in_reference_not_library.py`，含反真空）。
- **落点**：`src/agentflow/seedinject.py`（`seed_workspace` / `read_seed_reading` /
  `unregistered_library_files` / `candidate_chain_lines`）；种子包口径与判收链见
  [`../seed/literature/README.md`](../seed/literature/README.md)。
- **复算**：`python scripts/seed_corpus.py --verify`；判据 `tests/test_seed_corpus.py`、
  `tests/test_seed_readme_says_the_chain.py`、`tests/test_seed_lands_in_reference_not_library.py`、
  `tests/test_a_workspace_literature_is_not_already_registered.py`。

## 4. `eguard.py` + `_experiment_guard/` —— 实验脚本不许写 `data/`（B2f 路）

> 这一件与上面三件不同族：上面三件是**只读读数**（标题里的「三件只读护栏」仍指 §1–§3），
> 这一件是一道**写闸**，2026-11-22 追加。

- **是什么**：E 的实验脚本由 `agent_e/core.py::_run_script` 在子进程里跑，而
  `fs.write` 的保留路径闸跑在**父进程**，管不到子进程的 `open("data/…", "w")`
  —— 真机 `projects/lp-ball-15` 的 4 个野表就是这么长出来的
  （取证读数在 `agentflow/temp/datahygiene/REPORT.md` §3.1；`temp/` 不入库，故不写成链接）。
  这一件把闸装进子进程：`sys.addaudithook` 拦 `open`（mode 含 `w` / `a` / `x` / `+`，
  或 `os.open` 的 flags 带写位）、`os.rename` / `os.replace`、`os.remove` / `os.unlink`；
  命中且路径在 `<工作区>/data` 下 ⇒ `PermissionError`，消息里带一句话出路：
  「实验读数落 `out/exp-logs/<实验号>.log`（原始输出）；穷举三件套（搜索空间 / 穷尽的判据 / 边界处理）
  仍落 `out/experiments/<实验号>/exhaustion.md`；`data/` 只由表工具写」。
- **读放行**：脚本读 `data/*.json` 的历史读数是允许的（真机里 E 会读自己上一轮的读数），
  只有写才拦。路径解析失败也放行 —— 这是卫生闸，不是把跑得通的实验拦死的闸。
- **落点**：`src/agentflow/eguard.py`（`install` / `guarded_roots` / `WAY_OUT`）、
  `src/agentflow/_experiment_guard/sitecustomize.py`（子进程启动期入口，只在
  `AGENTFLOW_EXPERIMENT_GUARD` 非空时装钩子）；接线只有 `agent_e/core.py::_run_script`
  一处：把 `_experiment_guard/` prepend 进**子进程**的 `PYTHONPATH`（保留原有值），
  并把 `AGENTFLOW_EXPERIMENT_GUARD=<工作区>/data` 写进**子进程**环境。
  **只在跑脚本这一支设，本进程一行不碰**：表工具写 `data/` 是它的正常工作，
  不能被自己的守卫拦住。
- **装不上怎么办**：`sitecustomize.py` 整个装配包在 try/except 里，失败时退化成不设防、
  在 stderr 留一行，退出码照旧 —— 绝不让子进程因守卫失败而起不来。
- **没有逃生口（刻意，不要加）**：不提供 `AGENTFLOW_OK_DATA_WRITES` 一类"本地调试放行"
  变量。要让脚本能写 `data/`，改的是脚本的落点，不是环境变量：实验读数写
  `out/exp-logs/<实验号>.log`（原始输出）、穷举三件套 `out/experiments/<实验号>/`，临时报表写 `work/E/adhoc/`（2026-11-22 B2b-1：`reports/`
  已退役，见 §5 —— 原文此处写的 `reports/adhoc/` 现在会被落点闸拒）。加一个放行变量等于给这条闸
  开一扇"设个环境变量就绕过"的门，而真机上没人会记得自己设过它。
- **判据**：`tests/test_experiment_data_guard.py`（a 写 `data/` 被拒且不落盘 /
  b 正控写 `out/exp-logs/000000/` 与 `out/experiments/000000/` 都成功、读 `data/tasks.json` 放行 /
  c 反真空清掉那个变量同一脚本又能写 / d 零副作用 + `os.replace` 等四路 /
  e 重复 `install` 幂等）。

## 5. 落点闸（写侧）与落点读法（`wellformed.layout`）—— `reports/` 退役、按角色分目录（B2b-1 路）

> 这一节与 §4 同族（也是一道**写闸**），2026-11-22 追加。业主裁定见 `draft/194` §二/§三：
> 「草稿区不能叫 report 这个名字，换名且按角色整理」。闸与规则先落（B2b-1，2026-11-22）；目录搬迁随后（B2b-2）
> —— 本文按**搬完之后**的布局写。

- **是什么**：工作区里每一份正文 / 草稿只有两个合法去处 —— 正文 `manuscripts/<角色>/…`、
  草稿 `work/<角色>/…`（第二段**必须是调用者自己的**角色目录，角色名 A–H / L / M / V，
  大小写不敏感）；`reports/` **退役**，写进去受控拒。记录型内容不进文件，进表
  （`search_requests` / `experiments` / `attack_plans` / `review_findings`）。
- **两个受控码**：`reports_is_retired`（写退役目录）与 `not_your_role_directory`
  （第二段不是你的角色目录 / 不是角色名 / 这一笔没有角色上下文）。两条拒信都带
  `how_to_fix`：草稿 `work/<你的角色>/`、正文 `manuscripts/<你的角色>/`、记录型进表。
- **缺省是开 = 拒（`AGENTFLOW_STRICT_LANDING`，2026-11-22 裁定；B4/p317 起翻转）**：闸与教法
  必须同一批窗口翻转。B2b-1 立闸时，教 `reports/` 的字还在（`specs/` 94 处 + `agent_skills.py`
  60 处 + `agent_prompts.py` 17 处），所以那一个窗口的产品缺省只能是"只记读数"，否则 A/M
  照旧写 `reports/` ⇒ 被拒 ⇒ 每一趟在同一个格子上空转。**B4 已把教法改完（p317）**：现盘渲染面
  里教 `reports/` 的字为 0（`apply_b4.py --verify-target`）⇒ 产品缺省**受控拒**。退档只为
  取证 / 老盘过渡：显式 `AGENTFLOW_STRICT_LANDING=0`（`0`/`false`/`no`/`off`）才是"只记读数"档，
  空串按缺省 = 拒。退档时"本该拒"的那几条进 `fs_tools.landing_readings()`
  （`by_kind` 是写侧受控码、`by_code` 是读侧判词码、`recent` 是最近十条原文），`strict`
  那一位分辨当前档位。判据侧（`tests/conftest.py`）钉的是"开"档 —— 要验的是闸开着时的判据
  本身；"缺省是拒"与"`=0` 只记读数"由
  `tests/test_b2b1_landing_gate.py::test_the_gate_ships_open_and_zero_is_the_readings_tier`
  自己验。**读侧（`layout` 一类）不受这个开关管**：它只报读数，任何时候都能跑。
- **落点**：写侧在 `src/agentflow/tools/fs_tools.py` 的 `_landing_refusal`（常量
  `REPORTS_RETIRED_KIND` / `LANDING_ROLE_KIND` / `REPORTS_RETIRED_MESSAGE` /
  `LANDING_ROLE_MESSAGE` / `LANDING_LEDGER_MESSAGE`），接在 `_reserved_refusal` 的**末端**
  —— 既有的保留表与 D 的正文闸排在它前面，拒信与受控码一个字不变；四个写口
  （`fs.write` / `fs.edit` / `fs.delete` / `fs.move`）仍然只有 `_reserved_refusal` 一个结论点。
  读侧在 `src/agentflow/wellformed/layout.py`（分类器 `layout_of` / 角色表 `is_role` /
  `canonical_role`），`wellformed` 的新类别 `layout`（`reader._SPECS` 的 `path-tree` →
  `driver._check_tree` → `RULES["layout"]["landing"]`）。
- **为什么判落点、不按扩展名拦**：同一份 `x.md` 在 `reports/` 下是旧落点、在 `work/A/` 下是
  草稿、在 `manuscripts/A/` 下是正文 —— 扩展名三者完全相同；反过来 `.md` 在 `out/` /
  `notes/` / `code/` 下是合法产出面，按扩展名拦会一起误伤。退役面里也不止 `.md`
  （`reports/x.json` 一样拒），而 `m-review.md` / `summary.md` 这类"普通报告名"按扩展名认不出来。
- **读侧三态**：`ok` / `malformed` / `unchecked`，与 §1 同一个三态。
  - 新布局（`manuscripts/<角色>/`、`work/<角色>/`、`work/handoffs.jsonl`）⇒ 无一档；
  - **旧布局（不再支持）**（`reports/` 下的一切、`documents/` 下的一切、
    `manuscripts/handoffs.jsonl`）⇒ `error` + 一条点名的 code（`layout_reports_retired` /
    `layout_documents_body` / `layout_handoffs_ledger_in_manuscripts`），整份读数退出码 1。
    业主 2026-11-22 裁定「旧工作区不必兼容」：早一版那一档 `legacy`（进读数、不改三态）
    已取消 —— **不许静默当 ok、不许折成空**。真机 55 个工作区全是旧布局
    （`reports/` 690 份、`manuscripts/handoffs.jsonl` 26 个、`documents/` 22 份、`work/` 0 个），
    所以它们在新口径下都是 `malformed`：那不是回归，是"还没搬"的读数；
  - `manuscripts/x.md`、`work/notes/y.md` 这类**新目录下不合规** ⇒ 畸形（`error`）；
  - 受管目录读不到 ⇒ `unchecked` + 退出码 2（不折成 `ok`）。豁免与截断都写在 `notes` 里
    （一个目录最多逐条列 `SCAN_LIMIT=200` 份）。
- **读数入口**：`python scripts/check_wellformed.py --root projects/<ws> --kind layout [--json]`；
  `wellformed.layout_reading(root)` 给每种判词的份数，`wellformed.layout.iter_unsupported(root)`
  逐个吐出"不再支持"的路径（B2b-2 搬目录用的清单）。
- **判据**：`tests/test_b2b1_landing_gate.py`（a 写别人的角色目录 ⇒ 拒 / 写自己的 ⇒ 通；
  b `reports/x.md` 与 `reports/x.json` ⇒ 拒 + 三条出路，`code/` / `out/` / `notes/` / `out/data/`
  照旧通；b2 四个写口同一处结论；c 没有角色上下文时角色目录拒、`out/` 通；
  d 反真空把 `_landing_refusal` 打桩成放行 ⇒ a / b 翻转；e 开关缺省拒、显式 `=0` 才是
  只记读数档），
  `tests/test_wellformed_layout.py`（c1 旧布局树 ⇒ malformed 且三条 code 点名 /
  c2 新布局树 ⇒ 无一档 / c3 新目录下不合规 ⇒ 畸形 / c3b 账本两个位置分开判 /
  c4 读不到 ⇒ unchecked / d1 把 `UNSUPPORTED_SEVERITY` 降成 `info` ⇒ 旧树变 ok /
  d2 把分类器打桩成 `UNRELATED` ⇒ 两条读数全空）。
- **与 §4 的一句话冲突（已就地改正）**：§4 原文把"临时报表"指到 `reports/adhoc/` —— 那一格
  现在也拒（`reports/` 退役）。出路改成 `work/<角色>/adhoc/`。

