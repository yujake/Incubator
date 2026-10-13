# 117 —— `paper_package` 整条退场、正文改由智能体直接写（批 R72 计划）

> 业主 2026-10-13（逐字）：「paper_package 里那些东西都是古早废案了，我们要智能体写文章」，
> 并在两个选择题上选了 **A / A**：
>
> - 范围 A：**整条退场** —— 动作 + 5 个工具 + 收工门那一维 + 三个模块都下线；
> - 交付 A：**G 直接写 `out/paper/main.tex`**（散文体、自己排章节），框架**内置**编译出 PDF；
>   `documents/NNNN.md` 仍是台账侧正本（不要求两者一致 —— 那一档是 C 方案，业主没选）。

---

## §0 为什么退场（第二趟 T2 的读数）

第二趟 T2 的论文包是**M 在会话里现写了一个 Python 生成器**（`code/make_paper.py` 步 30/34、
`code/compile_paper.py` 步 35/43/46/48/52 重写 5 次）再生成 `main.tex` 的：
一节 = 一个标题 + 一整段 body（台账 6 段 body 的换行数全是 0）、`\paragraph{Claim N of 5}`
手写编号、**摘要硬编码在脚本里**（台账没有 `abstract` 字段）、非 ASCII 静默变空格、
没有 `fontenc`（`>=` 印成 `¿=`）、没有参考文献、`exp:0002` 是 `refutes` 还被当支撑引用。
根因不是模型写得差，而是**这条路要求"项目里得有一对渲染/编译脚本"**，而从零研究工作区没有
⇒ `t-0025/0026/0036/0037` 四次 `package_build_failed`（"脚本不在盘上"）⇒ 每个角色都得
现造一个，排版就固化进 Python。这条路要退场。

---

## §1 退场面（改之前逐个确认过）

| # | 落点 | 现内容 | 处置 | 禁改区 |
|---|---|---|---|---|
| 1 | `specs/g.py:104-126` | `ActionSpec("G","paper_package",…)` | **删** | **是** |
| 2 | `specs/g.py:149` | G 的政策"改完稿要让包跟上…锚 0 漂移" | **换成**"正文你自己写：`out/paper/main.tex` 用 fs.write 逐节写（散文体、章节自排）；写完调 `doc.paper_compile` 出 PDF" | **是** |
| 3 | `specs/m.py:82` | M 的政策"整理成论文 ⇒ 必须建论文包…锚 0 漂移，要判成 consistent" | **换成**"整理成论文 ⇒ 让 G 直接写 `out/paper/main.tex` 并编译出 PDF；不建包、不核锚" | **是** |
| 4 | `capabilities.py:2493-2506` | `paper_package` 的"非工具名动作"登记 + 计数注释 | **删**（动作数 60 → 59） | **是** |
| 5 | `agent_g/core.py` | `_PaperPackage` 混入 | **删**引用 | 否 |
| 6 | `agent_g/paper_package.py` | 整个模块 | **删文件** | 否 |
| 7 | `paperbuild.py` | 项目脚本通道（render/anchor/build） | **删文件**（编译能力搬进新模块，见 §2） | 否 |
| 8 | `renderanchor.py` | 锚的全部实现 | **删文件** | 否 |
| 9 | `tools/doc_tools.py` | 5 个工具（`doc.paper_render/compile/anchor/build/state`） | **删 4 个**（render/anchor/build/state），**新增 1 个** `doc.paper_compile`（框架内置编译，见 §2） | 否 |
| 10 | `tool_timeout.py:154-161` | 上面那几个的声明 | 同步 | 否 |
| 11 | `closing.py:53 / 2561 / 2584-2640` | 八格里的 `anchor` 那一格 + `_has_paper_package` + `_check_anchor` | 改成 `paper` 一格：有 `main.tex` ⇒ 必须**本次**编出 `main.pdf`（回执的 `tex_sha256` == 盘上那一份）；没有正文 ⇒ `not_applicable`；有正文没编 ⇒ fail | 否（评测口径） |
| 12 | `agent_prompts.py`（纸包三/四 + 327/1102/1150 三处工具摘要） | 「工作循环：改 main.tex → paper_render → paper_compile → paper_state，锚回 consistent」+ 完成定义第 1 条（锚 0 漂移） | **重写**成"正文由 G 写、编译由框架做、那一格看本次 PDF" | 否（但要升版本 + 重冻快照 + 人审签字） |
| 13 | 判据 | `test_paperbuild.py` / `test_renderanchor.py` / `test_paper_package_action.py` + 其它引用点 | 删/改（换成"G 写 .tex → 框架编译 → 收工门那一格"的正负控） | 否 |
| 14 | `tests/golden/agent_surface_snapshot.json` / 提示词冻结摘要表 | 动作面 60 → 59、提示词换了文字 | **重冻 + 逐格核** | **是** |

## §2 编译这一件事放哪（退场之后唯一保留的机械步骤）

业主选的是"框架**内置**编译"，所以新的 `doc.paper_compile` 不再跑项目脚本：

- 输入：`project`（项目根，默认 `.`）、`timeout_sec`；
- 动作：在项目根下找 `out/paper/main.tex`，用 `pdflatex -interaction=nonstopmode` 跑两遍
  （cwd = `out/paper`），**带上本机需要的 `MIKTEX_USERDATA` / `MIKTEX_USERCONFIG`**
  （指向项目内可写目录 —— 第二次 T2 的 `exit_codes=[3221226505,3221226505]` 就是这个坑），
  从引擎日志里读页数；
- 产出：`main.pdf` + **框架写的** `COMPILE-RECEIPT.json`（`tex_sha256`/`pdf_sha256`/`engine`/
  `runs`/`exit_codes`/`pages`/`pdf_bytes`/`compiled_at`）—— 回执这一件留着（它是"这份 PDF
  是从盘上这一份 tex 编的"的唯一读数），但**由框架写**，不再由项目脚本写；
- 三态：没有 `main.tex` ⇒ `not_applicable`（还没写，不是失败）；引擎缺席/超时 ⇒ `unknown`；
  引擎退出码非 0 **而 PDF 在** ⇒ 如实两栏都报（不当成功、也不当"没有 PDF"）；
  回执与盘上 `main.tex` 对不上 ⇒ `drifted`（"这份 PDF 是旧 tex 编的"）。
- `RENDER-ANCHOR.json` / `BUILD-HISTORY.jsonl` 不再产生；收工门不再有"锚 0 漂移"这一格。

## §3 执行顺序（一个批内做完，避免中间态）

1. 新模块 `papercompile.py`（§2 的编译 + 回执 + 三态）+ 判据；
2. `doc_tools`：删 4 个工具、加 `doc.paper_compile`、改工具表；
3. 删三个模块（`renderanchor.py` / `paperbuild.py` / `agent_g/paper_package.py`）+ `agent_g/core.py` 引用；
4. `closing.py`：`anchor` 格 → `paper` 格（含 `_has_paper_package` 删除、读数改口径）；
5. 禁改区三处（`specs/g.py` / `specs/m.py` / `capabilities.py`）；
6. 提示词（纸包三/四 + 三处工具摘要）→ `PROMPT_VERSION` p101 → p102；
7. 判据：删/改旧的三组，加"G 写 .tex → 编译 → 收工门纸那一格"的正负控；
8. 重冻：提示词摘要表 + `agent_surface_snapshot.json`（动作 60→59、提示词文字）；
9. 全量套件（冻结树上）→ FC-27 门 → 两人签字 → `draft/117` 补读数 → 提交推送。

## §4 已知代价（写在前面，别事后才发现）

- 这一批**命中禁改区三处**（`specs/g.py`、`specs/m.py`、`capabilities.py`）+ 两份冻结快照，
  按规矩要人审 + 2 名 reviewer 签字；
- `agent_surface_snapshot.json` 里 G 的动作减一 ⇒ 逐格核 diff（这是"声明与行为没变"
  唯一的机器读数，退场正是它该显示的那一格）；
- 收工门那一格换词（`anchor` → `paper`），历史读数里的 `anchor=pass/drifted` 变成旧词 ——
  报告里要保留"旧读数怎么读"的一句（历史不回填）。
