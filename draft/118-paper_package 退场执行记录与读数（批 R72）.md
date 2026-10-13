# 118 —— `paper_package` 整条退场：执行记录与读数（批 R72）

> 计划在 `draft/117`；这一份是**执行完之后的记录**：做了什么、读数是多少、过程中发现了
> 什么坑、哪些口径变了、哪些判据被删了而它的教训挪去了哪、还剩什么没做。
> 业主 2026-10-13 的裁定逐字：「paper_package 里那些东西都是古早废案了，我们要智能体写文章」；
> 经 `ask_user_question` 定下**范围 A**（整条路退场：一个动作 + 五件工具 + 收工门一格 + 三个模块）
> 与**作者 A**（G 自己把正文写进 `out/paper/main.tex`，框架在框架内编译出 PDF）。

---

## 1. 退场面（删了什么、加了什么）

| 面 | 退场前 | 现在 |
|---|---|---|
| 角色动作 | `G.paper_package`（重渲染 → 重编译 → 核锚） | 无（动作总数 60 → **59**） |
| G 的工具 | `doc.paper_render` / `doc.paper_build` / `doc.paper_compile` / `doc.paper_anchor` | 只剩 `doc.paper_compile` |
| H 的工具 | `doc.paper_state`（只读核锚） | **无**（H 不再有核包工具，见 §4） |
| 模块 | `renderanchor.py`（渲染锚 + 回执 + 构建历史）、`paperbuild.py`（项目脚本通道）、`agent_g/paper_package.py` | `papercompile.py`（只做一件事：编 PDF + 写回执） |
| 落点 | `out/paper/` 里有 `RENDER-ANCHOR.json` / `BUILD-HISTORY.jsonl` / 项目自带的 `code/make_paper.py` / `code/compile_paper.py` | 只有正文 `main.tex`（**智能体写**）、`main.pdf`（框架编）、`COMPILE-RECEIPT.json`（**框架写**） |
| 收工门那一格 | `anchor`（渲染锚 0 漂移） | `paper`（**这份 PDF 是不是盘上这份正文编的**） |
| 辅助读数 | `reviewaccept` 的 `anchor_verdict` | `receipt_matches_tex`（`consistent` / `drifted` / `unknown`） |
| 提示词 | 纸包段（派 `G.paper_package`、锚回 `consistent`） | 论文段（正文自己写 → `doc.paper_compile` → 核回执 `tex_sha256`），`PROMPT_VERSION` p101 → **p102** |
| 演示 | `demo/paper_from_results/`（那对脚本的样板） | 删（它演示的正是退场的那条路，且 import 已断） |

工具面读数（现算，不是记忆）：

```powershell
$env:PYTHONPATH="D:\Incubator\agentflow\src"; python -B -c "import sys; from agentflow.tools import build_registry; from agentflow import schema as S; from agentflow.store import Store; import tempfile,pathlib; d=pathlib.Path(tempfile.mkdtemp()); r=build_registry(store=Store(d), workspace_root=str(d), roles=tuple(S.ROLES)).registry; print(len(r.names()))"
# 79（退场前 83：四条 paper 工具下线、编译那一件留下）
```

动作面读数：`capabilities` 导入期自报 **59 个动作**（退场前 60）。

---

## 2. 新那一层的四条刻意口径（`agentflow/papercompile.py`）

1. **不跑项目脚本**：LaTeX 引擎由框架直接起（`pdflatex` / `xelatex` / `lualatex`，
   可用 `AGENTFLOW_LATEX_ENGINE` 指定）——项目里有没有 `code/*.py` 与本层无关；
2. **回执由框架写**：`tex_sha256` / `pdf_sha256` / `engine` / `runs` / `exit_codes` /
   `pages` / `pdf_bytes` / `pdf_fresh` / `compiled_at` / `written_by` / `stderr_tail`；
3. **产物与退出码分两栏**：本机 MiKTeX 会写完 PDF 却以 `0xC0000409` 退出
   （第二次 T2 实测 `exit_codes=[3221226505, 3221226505]`、`pages=3`）⇒ 判据是回执里的产物读数，
   退出码照实带回，谁也不冒充谁；
4. **三态 + 一条新读数 `pdf_fresh`**：`not_applicable`（还没有 `main.tex`）/
   `unknown`（没引擎、超时、**这一次没编出 PDF**）/ `computed`（**这一趟**拿到 PDF）。

`pdf_fresh` 是写这一层时**探针逼出来的**：只判"文件在不在"会把上一次编的 PDF 当成本次读数
（引擎什么都没产、旧 PDF 还躺在那里 ⇒ 读成"编成功了"）。判据是**编译前后的快照变了**
（mtime 变新或内容换了），而**不删**旧 PDF —— 一次失败的编译不该顺手毁掉上一份能看的稿子。

---

## 3. 几处读数（逐条可复算）

| 读数 | 值 | 怎么算的 |
|---|---|---|
| 工具总数 | 83 → **79** | 上面那条 `build_registry(store=…, roles=ALL)`；`tests/test_release_all.py` 的清单 91 = 79 个包根 `.py` + 12 个包目录 |
| 动作总数 | 60 → **59** | `capabilities` 导入期自报 |
| G 的工具面 | 41 → 37 | `tests/test_role_specs_complete.py` + 发布门 role-specs 步 |
| H 的工具面 | 27 → 26 | 同上（少的正是 `doc.paper_state`） |
| 提示词版本 | p101 → **p102** | 只有 M / G / H 三格的**段**换值；A–F 与 V 的段逐字未动（十格摘要里它们只差版本号那一行） |
| 冻结快照 | 两份都重冻 | `agent_surface`：G 的 actions/handler_signatures/tools/write_tools/prompt，H 的 tools/prompt，M 的 prompt；`tool_surface`：`declarations`/`signatures` 各 83→79（删四条、`doc.paper_compile` 改一格）、`roles`/`roles_with_m` 的 G/H、`summary`、11 条 CLI 输出（它们内嵌工具清单） |

逐格对拍是**算出来**的，不是看 diff 看出来的（`temp/_diff_snapshots.py` / `temp/_diff_agent_snapshot.py`）：
按 `git show HEAD:<快照>` 与工作区那份逐键比，报"删了哪些键 / 加了哪些键 / 改了哪些格"。
`agent_surface` 那一份十个角色**都**变了，但 A–F 与 V **只差 `- 提示词版本：p101` 那一行**（长度逐字相同）——
这句话必须说清，否则"十个角色都变了"会被读成"改了十格提示词"。

---

## 4. 口径变了的三件事（请业主过目）

1. **完成定义第 1 条换对象**：旧的是"渲染锚 0 漂移"（锚三维把 `store` 的行也算在内 ⇒
   写完台账就得重新封锚）；现在是"回执里的 `tex_sha256` == 盘上这份 `main.tex` 的摘要"。
   因此**写台账不再让 PDF 过期**，只有改正文才会。
2. **独立复核少了一条腿**：旧路里 H（只读）能自己调 `doc.paper_state` 核一遍；
   现在 `doc.paper_compile` 只发给 G（它写盘 + 起子进程），H 手上没有核包工具。
   仍有的两条：M 跑 `conductor.closing` 读 `paper` 那一格（判据在框架里现算）、
   H 用 `fs.read` 读回执与正文（提示词里写明"要写清这是 G 的读数还是自己核的"），
   以及 `reviewaccept` 的辅助读数 `receipt_matches_tex`。**若业主要求"H 也能独立核"**，
   合理的加法是一件只读的 `doc.paper_status`（进程内比摘要）—— 本次**没有**加，因为范围 A 定的是退场。
3. **一条顺序纪律随机制消失**（不是被删）：旧提示词要求"会写台账的动作（`H.verify_fixes`）
   排在最后一次重渲染之前" —— 那是因为旧锚把台账行算进维度。现在回执只认 `main.tex`，
   那句话既不对也没用了；`tests/test_paper_pack.py` 的 docstring 如实记了这一条。

---

## 5. 这一批删掉的判据，以及它们的教训挪去了哪（不粉饰）

删掉的四个测试文件（连同它们守的机制）：

| 删掉的判据 | 守的机制 | 教训挪去哪 |
|---|---|---|
| `tests/test_paperbuild.py` | 项目脚本通道（渲染/编译/查锚三态） | 机制没了 ⇒ 判据没了；**三态**那一半由 `tests/test_papercompile.py` 接手（`not_applicable` / `unknown` / `computed` 各自单列） |
| `tests/test_renderanchor.py` | 渲染锚三维 + 只读核对 | 同上；"手写的锚 / 格式不对 ⇒ 没查成，不是漂了"这一条改成"回执读不到 ⇒ `None`（判不了）" |
| `tests/test_paper_package_action.py` | 动作与工具面的接线（`R2b-⑬`） | 动作没了；"工具面只有一件、且只给 G"由 `test_papercompile.py` 的权限面判据接手 |
| `tests/test_the_package_failure_carries_the_script_stderr.py` | **失败要把外部工具自己的话带回来**（`t3e` 的读数） | **完整接手**：`test_papercompile.py` 的两条（引擎 stdout/stderr 尾巴随读数回来 + 回执里也留一份）。laTeX 的错误印在 **stdout**（`.log` 转录）上，所以两栏都留 |
| `tests/test_refusals.py` 里三条 `agent_g/paper_package.py` 的失败码 | 那三条失败码 | 登记逐条删掉，docstring 写明退场理由 + 接手判据 —— **没有**给不存在的机制编新判据 |
| "洁净室渲染器不许改正文"（旧 polish 回路里的负控） | 生成器整份重写正文的真机血案 | 变成**结构性保证**（框架的编译本来就不碰正文），并在 `test_review_polish_loop.py` 里以"改动还在、其余正文逐字未动"这一对断言继续钉 |

---

## 6. 过程中发现并修掉的五个坑（都不是"模型笨"，是工程读数）

1. **`closing.py` 里还留着一处 `RA.file_digest`**（`manuscript_edited` 那一腿）——`renderanchor`
   删掉之后它是一个 `NameError`。**是判据自己抓出来的**：那一腿落 `acceptance_leg_unreadable`
   ⇒ 整格 `unknown`（不是 pass、也不是 fail），三态纪律在这里救了一次。改完那一格恢复
   `fail`/`pass` 两种正常读数（`tests/test_closing_gate.py::test_the_manuscript_edited_leg_…`）。
2. **`agent_prompts.py` 被脚本整体写回时从 CRLF 变成 LF**：`read_text()` 把 `\r\n` 归一成 `\n`，
   再 `write_text(newline="")` 写回去 ⇒ 整份文件换行符变了，`git diff` 显示"改了 5282 行"，
   而实际只改了七处。已按字节修回 CRLF（`git diff` 现在 76 插入 / 58 删除）。
   本仓的 EOL 纪律：`agent_prompts.py` = CRLF，多数文件 = LF。
3. **冻结提示词摘要表的环境坑**：`tests/conftest.py` 在导入期钉 `AGENTFLOW_LEAN_ENABLED=1`，
   而 D/E/F 三格的摘要对 Lean 开关敏感。不带这个变量跑
   `temp/recompute_prompt_digests.py` 会算出**另一组** D/E/F（`da82…` 对 `814e…`），
   抄进表里判据当场红、而红的位置看着像"段动了"。已让那个计算器自己钉上开关，并在
   `tests/test_agent_prompts.py` 的冻结表上方写明这个坑。
4. **快照重生成是同一个坑的第二处**：直接跑
   `python -B tests/test_agent_surface_snapshot.py --write`（不带开关）会写出 Lean **关闭**口径的
   提示词文本（D 的"背书在形式化（E）或人"变成"逐行审阅（E / V）或人"、E 的"数值实验与形式化验证"
   变成"数值实验与证明审阅"……），而判据（在 conftest 下）比的是 Lean **开启**那一套 ⇒
   写出来的基线自己就不认。已让两个 `--write` 入口在导入 agentflow **之前**自己钉上开关。
5. **`pdf_fresh`**（见 §2 第 4 条）：探针发现"文件在不在"会把旧 PDF 读成本次产物。
6. **三处陈旧读数 / 坏引用 / 看不清的返回，被本仓自己的判据在全量套件里抓出来**（第一跑
   `3 failed, 5074 passed`）—— 这三条都不是本次退场引入的"新错"，而是退场把旧数字变成陈旧：
   - `capabilities.py` 里那句实测读数还是 `60 个动作 = 21 compared + 39 unmatched + 0 ambiguous`，
     而现在是 `59 = 21 + 38 + 0`（`tests/test_r4_roles_surface.py` 按现算读数逐字比对源码注释）；
   - `doc_tools.py` 的成功支写成 `ok(body)`（变量）⇒ "看不清返回了哪些键"的处数从 2 涨到 3
     （`tests/test_tools_branch_key_sets.py`）；改成字面量键表即可，判据自己也这么建议；
   - `tests/test_agent_prompts.py` 的注释里两处引用 `temp/recompute_prompt_digests.py`：
     这条判据按**工作区根**（仓库根）解析 `temp/...`，而那份脚本在 `agentflow/temp/` 下
     ⇒ 引用是坏的（`tests/test_r5_orchestration_cost.py`）。改成 `agentflow/temp/…` 全路径。
   三条都在改后单独跑到绿（56 passed / 98 passed），并重跑了全量套件（读数见 §9）。

---

## 7. 没做 / 留给后面的（如实列）

1. **两件要业主裁的**（从 `draft/116` 带过来，本次没动）：
   ① 稿件**作废/取代**（`supersedes`）的语义与落点；② **`blocker` 是否阻断收工**
   （现在 `blocker` 只进 `findings`，`can_close` 归 M 的判据）。
2. **`literature.unprocessed` 没有队列项**：已经登记但没被处理的文献不会进任何队列，
   `A.run_once` 只能回 `no_pending_request`（第二次 T2 的 t2b 步 9 真机读数）。
   两条路：改 `agent_a`（**不是**禁改区）或在 B 那一侧加一个 intake 动作（那是 FC-27）。
   本次没动 —— 它属于"研究链"，不属于这次退场。
3. **已知遗留的陈旧提及**（没改，留记录，都不是判据对象）：
   - `tools/coverage_zero_test.py` 里 `gauge` 的说明文字拿 `paper_package.py` 当
     "生产路径直调工具体"的例子（那个文件是禁改区 `release-deploy`，改它要另走一次人审）；
   - `tests/test_tools_returns_declaration.py` 头部 docstring 里几处"55 个工具"（**既有**陈旧，
     本次退场之前就与 83 不符）；
   - `src/agentflow/agent_e/author_script.py` 的一处注释拿 `paper_package` 举例（同族说法）。
4. **第三次 T2 没有启动**（业主 2026-10-13：「不急着做第三回 T2，着重记录并修复已知问题」）。
   `draft/116` 里那些"读数不一致 / 交付面缺陷"的条目，本次只处理了与退场直接相关的那几条。

---

## 8. 禁改区（FC-27）命中清单 —— 本批必须 2 名人审

| 文件 | 类别 | 这一批改了什么 |
|---|---|---|
| `src/agentflow/specs/g.py` | `auth-audit`（角色 G 的声明真身） | 删 `ActionSpec("G","paper_package",…)`；政策那一条改写成"正文你自己写 + `doc.paper_compile`" |
| `src/agentflow/specs/m.py` | `auth-audit`（角色 M 的声明真身） | 交付形式口径：论文那一档改成"G 自己写正文 + 编 PDF"；两处"论文包"措辞 |
| `src/agentflow/capabilities.py` | `auth-audit`（A–H 调用矩阵的权威定义） | 拿掉 `G.paper_package` 的登记 |
| `tests/golden/agent_surface_snapshot.json` | `eval-criteria`（冻结快照） | 重冻（逐格读数见 §3） |
| `tests/golden/tool_surface_snapshot.json` | `eval-criteria`（冻结快照） | 重冻（逐格读数见 §3） |

（`scripts/noai_gate.py --git --since <基线>` 的读数与两名人审的登记见提交信息与
`.noai-approvals.json`。）

---

## 9. 全量套件的两次读数（同一棵树上的"改前 / 改后"）

| 跑 | 命令 | 读数 |
|---|---|---|
| 第一跑 | `python -B -m pytest -q -p no:cacheprovider` | **3 failed, 5074 passed**, 5 skipped, 10 deselected, 1 xfailed（1738 s；日志 `temp/r72-full-suite.txt`） |
| 改掉那三条之后 | 同上 | 见 `temp/r72b-full-suite.txt`（同一命令，日志在盘上） |

第一跑那三条红**不是**"改动坏了东西"，而是退场把三处**旧数字/坏引用/看不清的返回**
变成了陈旧读数（逐条见 §6 第 6 项）—— 这正是"全量套件在冻结的树上跑"的价值：
它们单跑一个个文件时不一定碰得到。

