# -*- coding: utf-8 -*-
"""论文对应表：G 写正文之前先有这张表，H 依据它逐行核。

G 产出论文时需附上对应表，说明每条定理、引理、命题、例子、实验对应产出物的
真实文件和序号是什么，H 依据此核查，G 也依据此写作。

## 三个落点、一份内容（都在论文包里）

论文包就是 `main.tex` / `main.pdf` 所在那一个目录（`papercompile.package_dir`，通常是
`out/package/`）。下面三份都住在包里，包外那一份不算数：

- `<论文包>/MAPPING.json`：机器读，唯一真身。本模块是它唯一的读侧（解析 + 校验）；
- `<论文包>/MAPPING.md`：人读，由 json 生成（`render_mapping_markdown`）。不许手写第二份；
- `<论文包>/mapping-appendix.tex`：正文附录（`附录：产出对应表`），由 json 生成
  （`render_appendix`），`main.tex` 用 `\\input{mapping-appendix}` 把它印进 PDF。

生成顺序是死的：先写 json -> 由 json 渲染 md 与附录 -> 再编 PDF。改完正文必须重编一次
（`doc.paper_compile`），否则 `closing` 的 `paper` 那一格会报"PDF 是旧正文编的"。

## 每一行的字段与口径

| 字段 | 必填 | 口径 |
|---|---|---|
| `kind` | 是 | 受控词表 `ENV_KINDS`（theorem / lemma / proposition / corollary / example / experiment / definition） |
| `label` | 是 | 正文里那个 `\\label{...}` 的值（不带花括号） |
| `env_no` | 是 | 正文里第几个该环境，1 起，按正文出现顺序按类计数（theorem 单独数、lemma 单独数；分节 `\\input` 进来的按内联顺序算） |
| `ledger_id` | 是 | `stmt:NNNNNN` / `exp:NNNNNN` / `rel:NNNNNN`；老行可能带 `#pN` 尾巴（`stmt:000004#p2`） |
| `proof_no` | 是 | 这条定理名下的稿号（一个稿号 = 一份文件 = 一份证明）：1 = canonical（台账行上的 `proof_text`）；2 及以上 = 该行 `proofs` 清单里那一份 |
| `file` | 除定义行外是 | 该条完整证明或实验所在的真实文件，论文包内的相对路径（`proofs/000004-p1.md`）。定义行（`kind="definition"`）没有证明稿，这一格允许省略（见 `NO_MANUSCRIPT_KINDS`） |
| `page_or_section` | 否 | 给人看的定位（`3` / `p.7`） |
| `citation_loc` | 视来源 | 引文的本地位置：`{"file": 包内相对路径, "page_range"|"line_range"|"char_range": [起点, 终点]}` |
| `citation_loc_reason` | 视来源 | 不给 `citation_loc` 时那句理由 |
| `lean_file` | 有机器核验凭据时 | 机器核验凭据（Lean 程序 / 数值证明程序）：这一格说的是「这条命题有机器核验过的凭据（百分百为真）」，填什么由这条命题的证明通道决定。形式化通道 ⇒ Lean 程序的真实位置（项目根相对路径 `code/formal/000004.lean` —— L 把源码落在这里；论文包内那种写法 `formal/000004.lean` 也认）；数值证明通道 ⇒ 证明栏第 ① 段那份数值程序（`code/r34_check.py`，必须是同一份，`norm_rel` 比）；没有通道 ⇒ 这一格允许为空（不适用）。绝对路径与两个根之外的路径都红 |
| `lean_target` | 有形式化凭据时 | 它验的是哪一条：Lean 里那个声明的名字（`FreeGroupFactor.isII1`），必须真的出现在 `lean_file` 里。数值证明通道没有声明名可填（那一格填的是程序地址）—— 那两半不是一回事，填错一格就是拿 Lean 的名字给一份数值程序背书 |

`file` 与 `citation_loc.file` 都是包内相对路径：绝对路径在别人的机器上等于不存在，
而指向包外的相对路径同样过不了"换一台机器也能复核"这一关（两者都判红）。

`lean_file` 是唯一收「项目根相对路径」的那一格：
L 的产物落在 `code/formal/`（`agent_l._support.FORMAL_DIR`），而论文包是 `out/package/`，
全仓没有任何一步把前者拷进后者 —— 只认包内相对路径时，那条真实存在的源码永远填不进
这一格（三个落点各说各话）。所以这一格两个根都解析：先按包内找，找不到再按项目根找。
字段名保持 `lean_file`（不改名：表头、解析与两份渲染产物都不动），但它的语义是
「机器核验凭据」那一格，不再只是 Lean 源码的位置。

### `proof_no` 的口径

老行的 `#pN` 尾巴与 `proof_no` 说的是同一件事：`stmt:000004#p2` 的 `proof_no` 必须是 2。
`proof_no` 不许省：默认成 1 会让"没写"与"稿号 1"分不开，而逐份认签要挡的正是这个。
它解析到哪一份证明只走 `verifications.proof_list`，不在这里
重写那份清单的读法。`file` 的指向随之分档：`proof_no` = 1 指台账行本身或附录里那一段正文，
2 及以上指那一份证明自己的文件。

### `citation_loc` 的三态

- 台账行 `origin="external_lit"`（从文献摘的）=> 必填，缺就是 `mapping_citation_loc_missing`；
- `origin="own_result"`（我们自己得的）=> 允许为空，但必须给 `citation_loc_reason`；
  两样都没有 => 同样是 `mapping_citation_loc_missing`；
- 给了 `citation_loc` 而它那个 `file` 不在包里 => `mapping_citation_file_missing`。

区间三种任选其一（至少一种），值写成 `[起点, 终点]` 或 `{"start": ..., "end": ...}`，
两者都必须是正整数且起点不大于终点。

### 机器核验凭据那一格的三态（Lean 程序与数值证明程序同用一格）

lean 和数值证明程序同用一格不会打架，这一格的功能就是说这个命题是百分百真的。
所以 `lean_file` 那一格的语义是「这条命题有机器核验过的凭据（百分百为真）」，而不是
「Lean 开关开着时必填的一格」。填的类别必须与这条命题的证明通道一致 —— 通道只有一处判据
（`numericproof.formal_slot`，本模块只接线，不另写一套）：

- 通道 `numeric`（数值证明：证明栏第 ① 段是程序、台账里有 E 签的那条穷举）⇒ 必填，且必须
  是证明栏第 ① 段那份程序（`norm_rel` 比）—— 一份 `.py`。填 `.lean`、或填另一份程序都是
  `mapping_lean_file_missing`：两类凭据不许互相冒充。这一档只要求 `lean_file` 一格
  （程序没有声明名那一半，`lean_target` 不填；填了同样是受控拒绝）；
- 通道 `formal`（形式化）⇒ 必有 `lean_file` 与 `lean_target` 两格：`.lean` 结尾、在论文包与
  项目根两处之一里读得到、`lean_target` 真的出现在那份源码里（词边界匹配，`foo` 不算命中
  `foobar`）；
- 通道空（没有 `proof_text`、台账里也没有穷举或形式化实验）⇒ 这一格允许为空 —— 那是
  「不适用」，不是「没填」。盘上有没有 Lean 产物都不改变这一条：有产物是一个读数，
  不是这一条命题的凭据（"有产物 ⇒ 定理行必须给两格"正是把不适用读成没填的形态）；

`lean_target` 在那一份 `.lean` 里找不到 => `mapping_lean_target_missing`；同一个
`lean_target` 出现在两行 => `mapping_lean_target_ambiguous`。一条命题有多条证明时，
允许两行共用一个 `lean_file`，但那两行的 `lean_target` 必须各自不同（各自那份 `.lean`
里验它的声明名）。

开关开、却一个 Lean 产物都没有 => 读数里有一档 `lean_on_but_no_artifact`（`warnings`，
不拦门；见 `LEAN_WARN_KINDS`）：这一趟一个形式化文件都没落这件事必须看得见，但它说的不是
"表与正文对不上"。两格里只要填了一格（哪怕通道是空的），就要当真核 —— 只填一半同样是
`mapping_lean_missing`：填了就是声称，声称就得能复核。空着也绝不等于「验过了」：
它说的是「这一条命题没有机器核验凭据」，读数里说得出来。

### 数值实验定理那两格

纯数值实验把整个命题穷尽验证掉（覆盖全域）时也能到 `proof` 这一档，理由写「穷举」，
签名是那份程序；入定理证明库时证明栏写程序地址（相对仓库）。于是这类定理在对应表里
多两格，且证明栏换了一种指向：

- `file`：这一行是数值实验定理时，它写的是那份程序（相对仓库根，如 `code/r34_check.py`），
  不再是论文包内的那份 tex —— 判据差一档叫 `mapping_proof_program_missing`；
- `numeric_evidence`：E 的那条穷举读数（`exp:NNNNNN`）。台账里必须有它、必须是
  `numericproof.is_signed_exhaustion` 那一档、且它的程序就是 `file` 那一份；差一档叫
  `mapping_numeric_evidence_missing`；
- `exhaustion_note`：E 写的那两块（程序设计思路 / 穷举论证）与运行环境落在哪一份读数里
  （相对仓库根）。里面缺块、缺署名（`作者：E`）或缺读数编号 => `mapping_exhaustion_note_missing`。

三块合起来就是这条定理在论文里的证明栏：正文那一段还要指回 E 的读数（程序路径或
`exp:` 编号都算），指不回去 => `mapping_numeric_citation_missing`。词汇与判定只有一份，
在 `numerictheorem`（本模块只接线，不另写一套口径）。

哪一行算"数值实验定理"：它登记的那条命题的证明栏是程序（`numericproof.proof_column_script`；
真正的数值通道还要台账里有一条 E 签的穷举，见 `numericproof.proof_channel`），而且正文里
把它排成 theorem / lemma / proposition / corollary（`STATEMENT_ENV_KINDS`）。例子与实验不是
被证明的命题：它们照旧按通道填「机器核验凭据」那一格（`lean_file` = 证明栏第 ① 段那份程序；
E 还没签成穷举时那份 `.py` 也认 —— 例子 / 实验的凭据就是它），
但没有「这条定理压在哪条 E 的读数上」那几格（`numeric_evidence` / `exhaustion_note` / 索引四格）
—— `kind` 只决定要不要这几格附加义务，凭据格始终按通道判
（:func:`is_numeric_theorem_row` 是这条边界的唯一落点）。
其余行（自然语言证明的定理）一格都不要动 —— 防误伤那一条判据就在
`tests/test_numeric_theorem_writing_spec.py` 第 4b 条。

### 索引四格（D 的报告是目录）

D 的报告是目录（新成果＋索引），F 的证明 / E 的报告是
正文，V 的签是盖章，B 是读者 ——「B 基本都是从 D 的报告看到定理（命题），经索引看 F 侧
证明或 E 侧报告，并核实 V 签」。于是数值实验定理那一行（以及任何"正文在别处"的行）还要
带四格，缺一件 B 就取不到正文：

| 格 | 键 | 口径 |
|---|---|---|
| 正文是哪一档 | `evidence_kind` | `report`（E 的报告）/ `proof`（F 的证明） |
| 正文在哪 | `evidence_path` | 相对仓库根（`out/experiments/000000/exhaustion.md`） |
| 正文的指纹 | `evidence_sha256` | 那份对象正文的 sha256：E 的报告是文件字节；F/B 的证明取 `## 证明` 那一节（与 V 签的 `正文sha` 同一把尺，稿头与签块不算正文） |
| V 的签 | `v_signature` | `{"verdict": "成立", "sha256": <被签那一份的 sha256>}` |

这四格的列义只有一份（`numericproof.INDEX_*`），判据也只有一份
（`numericproof.resolve_index`：四格齐 => 读盘 => 算 sha256 => 与 `evidence_sha256` 和
`v_signature.sha256` 各比一次）。本模块那一档拦门（`mapping_numeric_evidence_missing`，
判据本体 `numerictheorem.evidence_index_problems`）与 B 的入库闸读的是同一个函数 ——
不许出现第二份口径，否则会出现"B 认、G/H 不认"的分家。
四格只进 `MAPPING.json`（机器读那一份）：md 与附录的列已经排满，加列会让旧附录整份对不上，
而那两份的用途是给人看"哪一行对应哪一份文件"，不是给 B 取对象。

自有证明那几行由写侧现填（2026-11-22 真机 sylow-4：四行「已签」的
`evidence_path` 全是空串 ⇒ 表在盘上指不到正文）。`fill_evidence_cells` 在落盘之前按台账
现读：`evidence_kind=proof`、`evidence_path` = `statements.manuscripts[证明号]`、
`evidence_sha256` = `bits.evidence.reviewed_sha_by_proof[证明号]`（V 签住的那一份正文；
现读那份稿的 `## 证明` 再核一遍才填）、`v_signature` = 同一份 sha + 「成立」。G 手填的
这四格会被这一次现读盖掉。`citation` 行不填：它没有 V 签，`v_signature` 无从取 —— 空着
绝不被读成「已签」。

### 台账那两格（让「论文说定理 / 台账说猜想 / V 签没签」自己暴露）

「论文对应表要能自己暴露『论文说定理 / 台账说猜想 / V 签没签』」。
于是每一行多两格，与既有的九列同源渲染（json / md / 附录三份都由 `Row` 渲染，
手写第二份照样过不了逐字比对）：

| 格 | 键 | 口径 |
|---|---|---|
| 台账里这一行叫什么 | `ledger_kind` | 台账那一行自己的 `kind`（theorem / lemma / conjecture / concept …） |
| V 签没签 | `reviewed` | 该证明号的 `bits.evidence.reviewed_by_proof` + `bits.evidence.reviewed_by.verdict` |

这两格不是 G 写的，是「填」出来的（`fill_ledger_cells`）：`write_mapping` 落盘之前
按 `ledger_id` 去台账里取那一行，现读现填，于是「表里说 theorem、台账说 conjecture」
这件事在表上自己就是可见的 —— 不需要读者去翻两个文件对。G 手填的值会被这一次现读
盖掉：填了就是声称，而这两格的声称必须来自台账。

`reviewed` 的取值是四档（「应该分：已签/未通过/未审/未读到」），
空着不许折成任何一边：

- `已签（判决：成立）`：逐份那张表里这一份为真（`reviewed_by_proof[证明号] is True`），
  且 `reviewed_by` 记着判决原话；原话读不到就印 `已签（判决：未读到）`（签过这件事读得出来，
  判决对不对得上这一份读不出来，两件事分开写）；
- `未通过`：审过、但没拿到签 —— `verifications/<命题号>.jsonl` 在，而这一份的键不存在或为假；
- `未审`：从没送审 —— `verifications/<命题号>.jsonl` 不在；
- `未读到`：台账文件在但读不出（坏行 / 权限 / 读异常），或 statements 行读不到。
  这一格没查成，不是「未通过」也不是「未审」。

判「审过没审过」认的是台账在不在，不是 `reviewed_by_proof` 有没有键：写侧
`verifications._reviewed_statement_row` 只在真签的时候才建那个键，于是"审过、判过有毛病、
从没签"的命题在逐份表里也没有键 —— 按"没键 = 未审"会把它读成"从没审过"。

`ledger_kind` 同样是三态：台账行在就写它的 `kind`；台账行读不到（或那一行的 `kind`
是空的）就写 `未读到`。渲染器最后这一道（`_ledger_kind_cell` / `_reviewed_print_cell`）保证
这两格永远不会印成空白 —— 空白会被读成"没问题"，而这几档里没有一档是"没问题"。

### 落差读数（D-69 ②：先让它看得见，不拦门）

`mapping_reading` 多两格读数，两格都只说、不判：

- `kind_gap`：论文里以 theorem / lemma 环境出现、而台账 `kind` 仍是 `conjecture`
  的行，逐条 `label → stmt:NNNNNN`（业主原话）；
- `theorem_unsigned`：论文里排成定理而 V 没签的行（`未通过` 与 `未审` 都算"没签"，
  逐条 `reviewed` 那一格自己说是哪一档）；签没签读不到的那几行单列进
  `unreadable`，不算进"没签"（没查成不是结论）。

两格都不进 `problems`、不进 `ALL_PROBLEM_KINDS`，所以它们不改 `state`、不改收工门的
八格、不给 `Finding`；它们进 `reason`（成文与收工那句话读得到）与 `readings`
（`closing.mapping_gaps` 转发）。为什么不拦：这一档量的是"论文与台账现在的关系"，
而拦门的判据是"表与正文对不对得上" —— 把前者做成门，每一份"论文先写、账后改"的稿子
都会红；但看不见更不行，sylow3 那三行正是这样一路静默到收工。

加了两格之后，旧论文包（json 里没有这两键）必须重跑一次 `doc.write_mapping`：
md 与附录都是按列逐字比对的，列变了就是 `md_drifted` / `mapping_paper_mismatch`。
读侧把这件事写进 `reason`（"另有 N 行没有台账那两格（旧表）"），不静默。

## 顺序：编号由 C 的路径驱动，正文先后必须是依赖 DAG 的拓扑序

业主 2026-11-26 的设计：G 按 C 给的路径行文（`agent_c.proof_path.plan_path` 的 `order`），
进入正文后重新标号（`概念1.1` / `引理3.1` / `定理3.3`），并维护对应表。G 仍可自由分章
（章号可跳、章序可重排），但章内顺序必须与路径一致。

这一轴分两问，都只看结构、不设任何阈值：

1. 依赖 DAG 的拓扑序（`order.dag`）：读 `<工作区>/data/dependencies.json`，每条依赖
   是「前提 → 使用它的人」（`label` / `source_stmt_id` 指前提，`used_by` 指使用者）。
   两边都在对应表里有行、且都有正文位置时，前提必须排在前面。谁被依赖就排在依赖者
   之前 —— 这一问不需要 C 的报告，材料在盘上，所以它总能判（读不到台账 ⇒ `checked=False`）。
2. 编号按路径（`order.path`）：G 在 `doc.write_mapping(path_order=[…])` 里声明它用了
   哪一条路径（按 C 报告 `payload.order` 原样抄）。读侧拿声明去 `<工作区>/data/
   analysis_reports.json` 里找 `kind="proof_chain"` 且 `order` 逐字相同的那一份报告：
   - 找不到 ⇒ 不是通过：`checked=False`，`why` 说清是"没有报告"还是"声明与任何一份
     都对不上"；对不上（台账读得到、声明是假的）落 `mapping_order_off_path`；
   - 找得到 ⇒ 逐条核：声明里的每个节点都要有一行（`mapping_order_missing_node` ——
     C 说这条路径自足，少一条就是证明链断在那儿）；每一行都要在声明的那条路径上
     （`mapping_order_off_path` —— 表里写了 C 没规划的条目）；
   - 按正文的 `\section` / `\chapter` 分章（结构事实，不看 label 长什么样），章内按
     正文出现顺序读路径位次，必须严格递增（`mapping_order_off_path`）；
   - label 写成 `…:<章>.<序>` 的行：同一章里章号必须一致、序号必须随正文顺序递增，
     两个不同的章不许共用同一个章号（`mapping_order_off_path`）。没有按这个形态编号
     的行不进这一问（`order.path.numbering.missing` 如实报几行没编号），但上面那条
     "章内顺序 == 路径"照样压着它。

`env_no` 这一格本来就由正文位置定（`_orphan_problems` 按 `(kind, label)` 与正文环境
逐一对上，序号对不上就是孤儿）—— 所以"文中条目依次"这一列是位置驱动的，不靠 G 报数。

三态：`order.checked` = 两问都真的判了；任一问缺材料 ⇒ `checked=False` 并把缺什么写进
`why`（没查成不是"顺序没问题"），`state` 不会被这一档单独翻成 pass/fail 之外的
东西 —— 但 `doc.write_mapping` 会把 `order` 整格交回去，读者一眼看见 `checked=False`。

## 双向都不许有孤儿

正文是"`main.tex` ＋ 它递归 `\\input` / `\\include` 进来的那些文件"（相对路径按被包含
文件所在目录解析；环与深度上限见 `MAX_TEX_INPUT_DEPTH`），不是 `main.tex` 一个文件：
分节写正文的论文与一次写完的论文必须由同一套读法读，否则前者要么全红、要么全绿。
扫描之前先做词法剥离（`strip_tex_comments`）：行尾 `%` 注释、`\\iffalse … \\fi`、
`comment` 环境、`\\verb` 里的字节都不算正文 —— 否则"注释掉一条定理"会让正文侧凭空
多一条，或者让 `env_no` 被一个幽灵环境顶位（报出来的孤儿指向根本没写错的那一行）。
`\\begin {theorem}`（控制词后带空格）是合法 TeX，按同一个环境读；嵌套环境用栈式
扫描，内外层各占一条、各自的 `env_no` 互不挪位。

正文里每个定理类环境都必须在表里有一行，表里每一行也必须在正文里有一个环境。
两个方向的成因不同：前者是"写了正文没登记"，后者是"登记了但正文里没有它"，
两件事分开报（合成一句就分不出该改哪一边）。一条定理有多条证明时，每一条证明各占一行。

## 附录必须是从 json 渲染出来的

`render_appendix` 是唯一的渲染函数，产物带一对界标
（`MAPPING-APPENDIX BEGIN` / `END`）与每行一条机器可读的 `MAPPING-ROW` 注释。
判据就是"正文里那一段与 `render_appendix(盘上 json)` 逐字相等"：
手抄一遍等于把渲染器再抄一遍，而抄错一个字符就是 `mapping_paper_mismatch`。

## 三态

- 有正文、但包里没有 `MAPPING.json` => `state="fail"` + `mapping_package_missing`
  （G 产出论文却没交表：这是没产出，不是没查成）；
- 没有正文、也没有表 => `state="unknown"`（不适用，不是通过）；
- 表在、但有 `ALL_PROBLEM_KINDS` 里的问题 => `state="fail"`，逐条列；
- 表在且干净 => `state="pass"`（`warnings` 非空也还是 `pass`：`warnings` 说的是读数，
  不是表与正文对不上 —— 但那一档必须打印、并在 `reason` 里点名，不许静默；
  目前 `warnings` 里只有 `lean_on_but_no_artifact` 一档，见 `LEAN_WARN_KINDS`）。

"路径不存在"与"内容为空"必须分得开（`file_state` 的 `missing` 与 `empty`）：
前者是这一行指错了地方，后者是那个文件真的还没写内容。

## 与 H 的关系（这条边界的由来）

`schema.FINDING_KINDS` 是禁改区里的受控词表，这些 `mapping_*` 不在里面，所以这一类
暂时落不进 `review_findings`，只能落收工读数（`closing` 的 `mapping` 格）。
词表与分档在 `agent_h/mapping_judge.py`；本模块只负责"表与正文对不对得上"这个事实。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import evidencebits as EB
from . import jsonlfile as JF
from . import papercompile as PC
from . import proofloc as PL
from . import numericproof as NP
from . import numerictheorem as NT
from . import schema as S
from . import textutil as T
from . import verifications as V


#: 机器读那一份的文件名。
MAPPING_JSON_NAME = "MAPPING.json"

#: 人读那一份的文件名（由 `MAPPING_JSON_NAME` 生成）。
MAPPING_MD_NAME = "MAPPING.md"

#: 正文附录那一份的文件名（由 `MAPPING_JSON_NAME` 生成）。
APPENDIX_FILE_NAME = "mapping-appendix.tex"

#: `main.tex` 里引用附录的那一行（`write_appendix` 负责插进去）。
APPENDIX_INPUT = "\\input{mapping-appendix}"

#: 附录那一节的标题（业主点名：中文标题就用「附录：产出对应表」）。
APPENDIX_TITLE = "附录：产出对应表"

#: 附录块的界标（判据靠这一对定位；手抄的那一段没有它就对不上）。
#:
#: 界标本身不许带 CJK（D-45）：它是渲染产物的一部分，英文论文的附录里连注释也扫不到
#: 一个中文字；所以这句说明用英文写死，两种语言共用同一个界标 —— 界标一旦按语言分叉，
#: 读侧（`_appendix_block`）就得知道该找哪一种，而它只拿得到正文文本。
APPENDIX_BEGIN = ("% ==== MAPPING-APPENDIX BEGIN"
                  " (rendered from out/package/MAPPING.json; do not edit by hand) ====")
APPENDIX_END = "% ==== MAPPING-APPENDIX END ===="

#: 附录里每一行的机器可读注释
#: （`% MAPPING-ROW kind|env_no|label|ledger_id|proof_no|file|lean_file|lean_target`）。
APPENDIX_ROW_PREFIX = "% MAPPING-ROW "

#: 正文里要进对应表的七类环境（顺序就是 md 与附录里 kind 的推荐顺序）。
#:
#: `definition` 是 2026-11-26（GMAP）补的第七类：正文里的定义条目（"Definition 1.1 ↔
#: 概念1"）此前根本写不进对应表 —— `kind` 词表里没有它、`parse_rows` 一律拒。
#: 它与定理类的两个区别：
#:
#: 1. 它不是被证明的命题：不进 `STATEMENT_ENV_KINDS`，不参与"一条命题对一个环境"、
#:    不算承重行（`is_load_bearing_row` 返回假）；
#: 2. 它没有证明稿：`file` 不是必填格（见 `NO_MANUSCRIPT_KINDS`），但 `ledger_id`
#:    必须有（定义正文在台账那一行的 `statement_full` 里，指得到才追得回来源）。
ENV_KINDS: tuple[str, ...] = (
    "theorem", "lemma", "proposition", "corollary", "example", "experiment",
    "definition",
)

#: 六类环境在正文里"印出来的抬头"（环境识别面的唯一一张表）。
#:
#: `kind=example` 的行（玩具例子）：正文用 `Example` 环境，不用 Lemma/Theorem；
#: 其余按既有映射。example 只是给人看的标签，处理与普通命题一致。
#:
#: 为什么单列一张表：对应表的 `kind` 是机器面（`\begin{example}` 的环境名），读者
#: 看到的是抬头（"Example 1.2"）。两者可以不一致 —— `\newtheorem{example}{Lemma}`
#: 会让一条 `kind=example` 的行在 PDF 上印成 Lemma，而扫描器只认环境名、看不出这件事
#: （`_printed_env_title` 只对上 theorem / lemma / proposition / corollary 那一组）。
#: 这一张表把"这一类 kind 该印什么"写成数据，`environment_titles()` 逐行对照导言区
#: 真有的 `\newtheorem` 声明 —— 于是"kind=example 的行真的进了 Example 环境"是一格
#: 可读的读数，而不是一句人话。
ENV_TITLES: dict[str, str] = {
    "theorem": "Theorem",
    "lemma": "Lemma",
    "proposition": "Proposition",
    "corollary": "Corollary",
    "example": "Example",
    "experiment": "Experiment",
    "definition": "Definition",
}

#: 数值实验定理那一支管哪几类环境（正文"一条命题一个环境"用；`is_numeric_row` 不按它判）。
#:
#: 为什么不是全部六类：例子与实验不是"被证明的命题"，它们没有证明栏可指。
#: 凭据那一格（`lean_file`）不按这一组裁：它按这一条命题的证明通道判
#: （见 `_lean_problems`）—— 通道非空就要填，与正文里排成哪类环境无关。
#: 数值定理那一支同理：`is_numeric_row` 只按通道判（2026-11-04 缝隙一），
#: 这一组只留给"一条命题对一个环境"、读数里的 `target_kinds`，以及
#: `is_numeric_theorem_row` 那一道「附加义务」的边界（2026-11-05 缺陷 1）。
LEAN_TARGETED_KINDS: tuple[str, ...] = ("theorem", "lemma", "proposition", "corollary")

#: "一条命题对一个环境"这条口径管哪几类环境（业主 2026-10-24，D-40）。
#:
#: 就是定理类四件套。例子与实验不是被证明的命题 —— 它们照样各占对应表一行，
#: 但不参与"正文环境数 = 台账命题数"这条一一对应。
STATEMENT_ENV_KINDS: tuple[str, ...] = LEAN_TARGETED_KINDS

#: 自定义环境（`\newtheorem{名字}{标题}`）印出来是这四个词之一 ⇒ 它就是一个定理类环境。
#:
#: D-40 的现场（cube2，2026-10-24）：G 把 Lean 的六段分解照搬进正文，再用
#: `\newtheorem{claim}[theorem]{Lemma}` 把 5 个中间步骤印成 Lemma。那 5 个环境名
#: 不在 `ENV_KINDS` 里，所以扫描器看不见它们 —— 正文侧只剩 1 个 theorem 环境，
#: "1 个环境对 1 条命题"当场成立，一条判据都拦不住（它既伪装成 Lemma，又绕开判据）。
#: 印成 Lemma 的宏与 `\begin{lemma}` 在读者眼里没有任何区别，所以这一格按"印出来的
#: 标题"认，而不是按环境名认。
STATEMENT_ENV_TITLES: tuple[str, ...] = ("theorem", "lemma", "proposition", "corollary")

#: 台账里不算"命题"的那几类 `kind`（概念并表后的 `kind="concept"`，以及定义/记号这类）。
#:
#: 为什么缺 `kind` 的旧行算命题：`schema.Statement` 只要求 `kind` 非空（它是自由文本），
#: 早期工作区与判据夹具里没有这一格。把"没说"读成"不是命题"会让那些正文全部变成
#: "多出来的定理类环境" —— 那是最贵的一种假阳性。
NON_PROPOSITION_KINDS: tuple[str, ...] = (
    "concept", "definition", "notation", "dataset", "experiment", "remark",
    "example", "open_problem", "openproblem",
)

#: `\newtheorem{名字}[计数器]{标题}` / `\newtheorem{名字}{标题}[节]`（标题那一支必取）。
_NEWTHEOREM_RE = re.compile(
    r"\\newtheorem\*?\s*\{(?P<name>[^{}]+)\}\s*(?:\[[^{}]*\]\s*)?\{(?P<title>[^{}]*)\}")

#: 机器核验凭据那一格（字段名仍是 `lean_file`）在文档与人读产物里的叫法（业主 2026-11-04）。
#:
#: 为什么字段名不改：表头、`MAPPING.json` 的解析、md 与附录两份渲染产物都按 `lean_file`
#: 走；改名要同时动这四处，而这一改的语义（两类凭据同用一格）不需要动它们。
#: 名字进 docstring、`MAPPING.md` 的说明段与正文附录的说明段；列头照旧。
CREDENTIAL_CELL_NAME = "机器核验凭据（Lean 程序 / 数值证明程序）"

#: 凭据那两格（`lean_file` / `lean_target`）：通道非空时必填，通道为空时允许为空。
#:
#: 两格是一对（`lean_target` 是 Lean 声明名那一半），但数值证明通道只要 `lean_file`：
#: 一份数值程序没有 Lean 声明名可填（见 `numericproof.formal_slot` 的两类填法）。
LEAN_ROW_FIELDS: tuple[str, ...] = ("lean_file", "lean_target")

#: 凭据是 Lean 程序时，`lean_file` 必须以它结尾（数值证明通道那一类不查这一条）。
LEAN_SUFFIX = ".lean"

#: 除论文包之外，Lean 产物还落在哪（项目根相对）。
#:
#: 2026-10-25（审计 G/H/V/L 第 4 条）：`code/formal` 是 L 的真实落点
#: （`agent_l._support.FORMAL_DIR`），而它此前不在扫描面上 —— 于是"盘上有 Lean 产出"
#: 这个读数看不见 L 写下的任何一份源码，`lean_file` 也就没有一处能指的落点。
#: `out/formal` 是业主 2026-10-22 口径里点名的另一处，两条并存。
LEAN_ARTIFACT_DIRS: tuple[str, ...] = ("out/formal", "code/formal")

#: 扫 Lean 产物时不进的目录（`.lake` 里是整份 Mathlib 的源码与编译产物）。
LEAN_SKIP_DIRS: tuple[str, ...] = (".lake", ".git", ".hg", "node_modules", "__pycache__")

#: 凭据那两格的三种占位写法（空着时按开关状态印出来，不印空白）。
#:
#: 渲染器不知道每条命题的证明通道（那要读台账），所以空着只有"开关关"与"没填"两档：
#: "不适用"那一档由 `mapping_lean_*` 在 `problems` 里说清，渲染只负责不印空白。
LEAN_OFF_CELL = "（未开 Lean）"
LEAN_UNFILLED_CELL = "（没填）"

#: 数值实验定理那两格的占位写法（空着时印它，不印空白）。
#:
#: 与 Lean 那两格的区别：那两格分"未开 Lean"与"没填"两档，这两格没有开关可分 ——
#: 空着就是"这一行不是数值实验定理，或者该填没填"，读者要能看见它。
NUMERIC_EMPTY_CELL = "（非数值证明）"

#: ---- 台账那两格（D-69）：这一行在台账里叫什么、V 签没签 ---------------------------
#:
#: 为什么这两格必须进表：业主 2026-10-24 的原话是"论文对应表要能自己暴露
#: 『论文说定理 / 台账说猜想 / V 签没签』"。改前表里只有 `kind`（论文里排成什么环境），
#: 于是真机 sylow3 那种"论文排成 lemma、台账 kind 还是 conjecture"的形态在表上
#: 一个字符都看不到 —— 表没说谎，但落差不可见。
LEDGER_KIND_FIELD = "ledger_kind"

#: V 那一签那一格（逐份证明的读数 + 判决原话）。
REVIEWED_FIELD = "reviewed"


#: 四档里"读不到"那一档的写法（台账文件在但读不出 / statements 行读不到）。
#:
#: 它不许折成「未审」、也不许折成「未通过」：读不到是"这一格没查成"，而「未审」
#: 是一个关于 V 有没有收到过这一份的结论 —— 两者在报告里长得一样是本项目最忌的形态。
LEDGER_CELL_UNREADABLE = "未读到"

#: 「审过、但没拿到签」：`verifications/<命题号>.jsonl` 在，而这一份的键不存在或为假。
#:
#: 为什么不能落在"没键 = 没签"上：写侧 `verifications._reviewed_statement_row`
#: 只在真签的时候才建 `reviewed_by_proof` 那个键，于是"审过五次、三次判有毛病、
#: 从没签"这种命题在逐份表里也没有键 —— 按"没键"读就会把它读成"从没审过"。
#: 「审过没审过」认的是台账在不在，不是键在不在。
REVIEWED_NOT_PASSED = "未通过"

#: 「从没送审」：`verifications/<命题号>.jsonl` 不在（合法初态，不是读不到）。
REVIEWED_UNREVIEWED = "未审"

#: 签了之后的写法（`已签（判决：<判决原话>）`）。
REVIEWED_SIGNED = "已签"
REVIEWED_SIGNED_TEMPLATE = REVIEWED_SIGNED + "（判决：{verdict}）"

#: ---- 优化态与来源那两格（业主 2026-11-02 两阶段录入；draft/179 二之一） --------
#:
#: 优化态三档，词与 `evidencebits.OPTIMIZED_STATES` 一一对应：
#: 这一份证明是"洗过的那一版"、还是"机械录入那一版、还等着洗"、还是"这一行根本没有
#: 那一格"（存量行）。三档不许折平：折成两档会把存量行读成"等洗"（3000+ 行）
#: 或读成"洗过"（更坏）。
OPTIMIZED_FIELD = "optimized"
OPTIMIZED_YES = "已优化"
OPTIMIZED_NO = "未优化"
OPTIMIZED_UNKNOWN = "未记录"
#: 优化栏第四档（2026-11-13 业主裁定）：优化阶段试过了、证不出来。
#: 它既不是「已优化」（没有真 V 签），也不是「未优化」（那会一直等洗、派活派不完）。
OPTIMIZED_HARD_TO_PROVE = "难以自证"

#: 来源那一格（收工门按来源分档的同一口径，与 `evidencebits.bits_of` 的 proof_source 同词）：
#: own = 我们自己的证明（F 的自动工具那一笔）；citation = 文献侧录入
#: （V 签位填的是文献编号 = 占位签）；空 = 读不出来。
PROOF_SOURCE_FIELD = "proof_source"
PROOF_SOURCE_OWN = "own"
PROOF_SOURCE_CITATION = "citation"

#: ---- 被引实验行（2026-11-25，MAPPING-COMPLETE） ------------------------------------
#:
#: 论文里写到的 `exp:NNNNNN` 也必须能在表里指到它自己的程序与读数。它没有对应的
#: 正文环境（论文往往在附录段落里引它），所以这一行的 `env_no` 记 :data:`EXPERIMENT_ENV_NO`
#: —— 0 = 被引、未印成环境。正文里真印成 `experiment` 环境的行仍按环境号 ≥ 1 走
#: 原来的双向孤儿判据；两种行不会互相顶替（同一实验只能有一行）。
EXPERIMENT_ID_PREFIX = "exp:"
EXPERIMENT_ENV_NO = 0
#: 文献行的前缀（2026-11-26，GMAP）：`lit:NNNNNN` 指 `literature` 表。
#:
#: 为什么它也要能进对应表：业主的对应表三列是「文中条目 → 库中编号 → 具体文件的相对
#: 路径」，而"这一条引自某篇文献"的第三列就是那份文献文件（`literature[].path`）。这类
#: 条目通常不印成环境（写成一句带出处的散文），所以它走「被引、未印成环境」那一档
#: （`env_no=0`），与 `exp:` 行同一套判法。
LITERATURE_ID_PREFIX = "lit:"
#: 实验行多出来的那几格（只进 `MAPPING.json`；由 `fill_experiment_cells` 从台账现读现填，
#: G 不写 —— 与索引四格同一条纪律：写侧填，读侧核）。
EXPERIMENT_LOGS_FIELD = "experiment_logs"
EXPERIMENT_CODE_HASH_FIELD = "experiment_code_hash"
EXPERIMENT_RESULT_FIELD = "experiment_result"
EXPERIMENT_NEGATION_FIELD = "experiment_negation_kind"
EXPERIMENT_PARAMS_FIELD = "experiment_params"
EXPERIMENT_EXIT_FIELD = "experiment_exit_code"
EXPERIMENT_ROW_FIELDS: tuple[str, ...] = (
    EXPERIMENT_LOGS_FIELD, EXPERIMENT_CODE_HASH_FIELD, EXPERIMENT_RESULT_FIELD,
    EXPERIMENT_NEGATION_FIELD, EXPERIMENT_PARAMS_FIELD, EXPERIMENT_EXIT_FIELD,
)
#: 台账那一格在实验行上的写法（实验表没有 `kind`、也不走 V 的审校链）。
EXPERIMENT_LEDGER_CELL = "不适用（实验行）"
#: 参数摘要为空时怎么写（`experiments.params` 这一列在历史行上常见是 `{}`）。
EXPERIMENT_PARAMS_EMPTY = "未记录（台账 params 为空）"


def optimized_cell(ledger_row: Mapping[str, Any] | None, proof_no: Any) -> str:
    """这一份证明洗过没有（优化态那一格的三档 + 读不到那一档）。

    - 已优化：`bits.evidence.optimized_by_proof[证明号] is True`；
    - 未优化：那一格在、值为假；
    - 未记录：这一行还没有那一格（存量行）—— 不许读成"未优化"，也不许读成"已优化"；
    - 难以自证：优化栏记着"试过了、证不出来"（第四档，2026-11-13）；
    - 未读到：行读不到 / 证明号认不出（这一格没查成，三态里的"没查成"）。

    判据只走 `evidencebits.optimized_state`（唯一读口）：这里再判一次就等于第二份口径。
    """
    if not isinstance(ledger_row, Mapping):
        return LEDGER_CELL_UNREADABLE
    no = _int_or_none(proof_no)
    if no is None:
        return LEDGER_CELL_UNREADABLE
    state = EB.optimized_state(ledger_row, int(no))
    if state == "true":
        return OPTIMIZED_YES
    if state == "false":
        return OPTIMIZED_NO
    if state == "hard_to_prove":
        return OPTIMIZED_HARD_TO_PROVE
    return OPTIMIZED_UNKNOWN

#: 审校台账 `verifications/<命题号>.jsonl` 的三态：在、不在、读不出。
#:
#: 这三档只用来判「未通过 / 未审 / 未读到」；「已签」只认
#: `bits.evidence.reviewed_by_proof[证明号] is True`（那一格是签字的正本）。
REVIEW_LEDGER_PRESENT = "present"
REVIEW_LEDGER_ABSENT = "absent"
REVIEW_LEDGER_UNREADABLE = "unreadable"
REVIEW_LEDGER_STATES: tuple[str, ...] = (
    REVIEW_LEDGER_PRESENT, REVIEW_LEDGER_ABSENT, REVIEW_LEDGER_UNREADABLE,
)

#: 论文里"排成定理"的那几类环境（D-69 的落差读数按它判）。
#:
#: 只收 theorem / lemma：业主点名的是"论文里以 theorem/lemma 环境出现"。
#: proposition / corollary 不在这一组里 —— 它们也是被证明的命题，但"说成定理"这句话
#: 指的是这两个环境名，把四件套全收进来会让读数与业主那句话对不上。

#: 台账里"还只是猜想"的那一档（落差读数的一半）。
CONJECTURE_KIND = "conjecture"

#: 每一行无条件必填的字段（与 kind 无关的那几格）。
#:
#: `file` 不在这里：它是"证明稿在哪"，而定义行没有证明稿（见 `NO_MANUSCRIPT_KINDS`）。
#: 一行到底要哪几格由 :func:`required_fields_for_kind` 一处算，`parse_rows` 与
#: 工具层 `_MAPPING_ROW_PARAMS["required"]` 都读它（工具层写的是字面量：`capabilities`
#: 的 AST 解析只认字面量，两者逐字一致由 `tests/test_g_mapping_rows_declare_the_papermapping_cells.py`
#: 的 ③ 守着）。
ROW_FIELDS: tuple[str, ...] = (
    "kind", "label", "env_no", "ledger_id", "proof_no",
)

#: 证明稿那一格（除 `NO_MANUSCRIPT_KINDS` 之外每行必填）。
MANUSCRIPT_FIELDS: tuple[str, ...] = ("file",)

#: 没有证明稿的那几类环境（2026-11-26，GMAP）：定义不是被证明的命题，它没有"稿"。
#:
#: 这一档只免 `file` 一格 —— `ledger_id` 照样必填（定义正文在台账那一行的
#: `statement_full` 里）；`proof_no` 也照样必填（`#p1` 恒在，它指的是那一行的正文，
#: 不是"有一份证明稿"）。
NO_MANUSCRIPT_KINDS: tuple[str, ...] = ("definition",)


def manuscript_required(row: Any) -> bool:
    """这一行是不是必须给 `file`（证明稿 / 实验程序在哪）。

    参数可以是 :class:`Row`、Mapping 或一个 kind 字符串。三态只有两档：真 / 假 ——
    "读不出 kind"按要处理（未知 kind 本来就会被 `parse_rows` 拒收，这里不替它猜）。
    """
    if isinstance(row, str):
        kind = row.strip()
    elif isinstance(row, Mapping):
        kind = str(row.get("kind") or "").strip()
    else:
        kind = str(getattr(row, "kind", "") or "").strip()
    return kind not in NO_MANUSCRIPT_KINDS


def required_fields_for_kind(kind: Any) -> tuple[str, ...]:
    """这一种 `kind` 的行必须给哪几格（唯一口径；`parse_rows` 与声明面读同一份）。"""
    if manuscript_required(str(kind or "")):
        return ROW_FIELDS + MANUSCRIPT_FIELDS
    return ROW_FIELDS

#: 数值实验定理那两格（业主 2026-10-23，E-1）：口径与判定在 `numerictheorem`，这里只转发。
NUMERIC_ROW_FIELDS: tuple[str, ...] = NT.NUMERIC_ROW_FIELDS

#: `citation_loc` 里三种区间（至少给一种）。
RANGE_KEYS: tuple[str, ...] = ("page_range", "line_range", "char_range")

#: 能解析的台账前缀（表名从 `schema.citation_prefix_table` 取，不在这里抄第二份）。
#:
#: `lit` 是 2026-11-26（GMAP）加进来的第四档：引文行的第三列要指得到那份文献文件，
#: 而"那份文件在哪"只有 `literature` 表知道（`literature[].path`，相对工作区根）。
LEDGER_PREFIXES: tuple[str, ...] = ("stmt", "exp", "rel", "lit")

#: 能承载 `ledger_id` 的四张台账表。
#:
#: 它同时是 `read_ledger_tables` 读哪几张表的口径 —— `lit` 进来之后文献行解析得到，
#: 代价是 `read_ledger_tables` 多读一份 `literature.json`（同一份按 mtime 缓存）。
LEDGER_TABLES: tuple[str, ...] = ("statements", "experiments", "relations", "literature")

#: 表 / 正文 / 文件三条轴上的问题类别（业主点名的客观四类，见 `agent_h/mapping_judge.py`）。
#:
#: `mapping_missing`：表写好了、但放错了落点（包外那一份不算数）；
#: `mapping_orphan`：孤儿 —— 正文里的环境表里没有，或表里的行正文里没有（`detail` 写方向）；
#: `mapping_unresolvable`：这一行读不懂，或 `ledger_id` / `proof_no` 在台账里解析不到；
#: `mapping_file_missing`：`file` 指的路径在论文包里不存在。
MAPPING_KINDS: tuple[str, ...] = (
    "mapping_missing", "mapping_orphan", "mapping_unresolvable", "mapping_file_missing",
)

#: 引文那一格的两个类别（`citation_loc`）。
CITATION_KINDS: tuple[str, ...] = (
    "mapping_citation_loc_missing", "mapping_citation_file_missing",
)

#: 证据对象那两条（2026-11-25，MAPPING-COMPLETE）：这一行在表上声称的「证明稿 / 实验文件」
#: 与台账那一行对不上、或盘上取不到。
#:
#: 它们与 `MAPPING_KINDS` 分开一组，是因为那四类是业主点名的「表与正文对不对得上」，
#: 而这两条问的是「表与台账/盘上那份对象对不对得上」—— 后者此前只被
#: `doc.mapping_cells`（工具面）与 B 的入库闸调过，`mapping_reading` 这一道门没调。
#: 结果就是真机 sylow-4 那种形态：四行「已签」的 `evidence_path` 全空、或者删掉盘上那份稿，
#: 表照样 `pass`。这一组就是那个缺口的落点。
PROOF_FILE_MISSING = "mapping_proof_file_missing"
EXPERIMENT_FILE_MISSING = "mapping_experiment_file_missing"
#: 第三、四条（2026-11-26 BEARINGDEF）：论文里的承重命题必须有它自己的证明稿与签。
#:
#: 现场（真机 sunflower-digest-2，2026-11-25/26）：MAPPING 5 行，`prop:block` /
#: `thm:erdos-rado` 两行是正文里带完整证明的命题 / 定理，而它们的索引四格一个都没有；
#: 这两条命题在台账里 `origin=external_lit` + `proof_source=citation`（只因为"这行引了
#: 文献"），于是旧的闸（`proof_source == own` 且 `reviewed == 已签`）把它们整行 `continue`
#: 掉 —— 收工门 8/8、`mapping_reading` 判 pass。两条命题的签是 `未审`。
#:
#: 判据只有两问（业主 2026-11-26 更正）：
#:
#: 1. 台账里这条命题有没有指向一份证明稿、那份稿在不在盘上
#:    （`statements.manuscripts[证明号]` → 盘上文件）；
#: 2. 那一份有没有 V 的签（`reviewed` / `verifications` 的签读数）。
#:
#: 不把"稿的正文 sha 变了"判成红：稿号与命题号设计上就不同轴（`b-proof-000000.md`
#: 是 B 自己的稿号，与命题号无关），而 B 的二阶段会洗证明正文并重拿 V 签 —— 正文变化
#: 是合法的。sha 只作信息读数（`sha_drift` / `manuscript_sha256`），不拦门。
#:
#: - `mapping_load_bearing_evidence_missing`：承重命题没有它自己的证明稿
#:   （台账没记稿，或记的那份稿在盘上取不到）；
#: - `mapping_load_bearing_unsigned`：稿在，而这一个承重命题没有 V 的签
#:   （业主 2026-11-26：「论文里的承重命题必须有它自己的证明稿与签」—— 这也是拦门，
#:   不是 warning；"还在写、还没送审"由 `reviewed` 那一格逐行说明，不由门装看不见）。
LOAD_BEARING_EVIDENCE_MISSING = "mapping_load_bearing_evidence_missing"
LOAD_BEARING_UNSIGNED = "mapping_load_bearing_unsigned"
EVIDENCE_KINDS: tuple[str, ...] = (
    PROOF_FILE_MISSING, EXPERIMENT_FILE_MISSING,
    LOAD_BEARING_EVIDENCE_MISSING, LOAD_BEARING_UNSIGNED,
)

#: 稿的字节 sha 那一格（与 `evidence_sha256` 的"正文 sha"分家；见 `Row` 的注释）。
#:
#: 为什么必须另立一格：`numericproof.INDEX_SHA_FIELD`（`evidence_sha256`）对 proof 档
#: 存的是那份稿 `## 证明` 正文的 sha（与 V 签同一把尺）—— `numericproof.py:1098` 与
#: `:1104-1108` 逐字写着"手稿的签块是签后写回稿里的，字节每签一次就变一次"，所以
#: 字节 sha 回答不了"签的是不是这份正文"。两件事塞进一格，就会出现"看起来对得上、
#: 其实比的是另一把尺"的静默错。
#:
#: 语义：信息读数，不是身份、不拦门（业主 2026-11-26 更正：洗稿合法）。
#: 它只回答"写表那一刻盘上这一份是谁"，由 `proof_evidence_reading` 的 `file_sha256` /
#: `sha_drift` 那一档读；判"承重命题有没有稿与签"只看台账映射与签读数。
PROOF_FILE_SHA_FIELD = "evidence_file_sha256"


#: 人读那一份的问题类别（同一张表的第二个落点）。
#:
#: `md_missing`：`MAPPING.md` 不在包里；
#: `md_drifted`：它与 json 生成出来的内容不一致（手写了一份，或者改了没重生成）。
MD_KINDS: tuple[str, ...] = ("md_missing", "md_drifted")

#: 论文侧的三条（落地在包里 / 印在正文里 / 印出来的与 json 一致）。
#:
#: `mapping_package_missing`：论文包里没有 `MAPPING.json`（没产出，不是没查成）；
#: `mapping_not_in_paper`：json 在、但正文里读不到「附录：产出对应表」那一节；
#: `mapping_paper_mismatch`：印出来的那一段与 json 渲染出来的不一致
#: （行数不等、或某个 label 只在一边出现）。
PAPER_KINDS: tuple[str, ...] = (
    "mapping_package_missing", "mapping_not_in_paper", "mapping_paper_mismatch",
)

#: 凭据那一组四条（业主 2026-10-22 追加；口径见模块 docstring 的凭据三态）。
#:
#: `mapping_lean_missing`：这一条命题有证明通道（数值 / 形式化），而两格没填
#: （或只填了一格 —— 填了就是声称，声称就得能复核）；
#: `mapping_lean_file_missing`：凭据的类别与证明通道不一致（数值通道填 `.lean`、
#: 形式化通道填 `.py`、空通道填程序），或那份 `.lean` 不在论文包 / 项目根里；
#: `mapping_lean_target_missing`：`lean_target` 在那一份 `.lean` 里找不到（词边界匹配）；
#: `mapping_lean_target_ambiguous`：同一个 `lean_target` 被两行共用（谁验的哪一条就说不清了）。
LEAN_KINDS: tuple[str, ...] = (
    "mapping_lean_missing", "mapping_lean_file_missing",
    "mapping_lean_target_missing", "mapping_lean_target_ambiguous",
)

#: 只进读数、不拦门的一档：Lean 开关开着，而盘上一个 Lean 产物都没有。
#:
#: 为什么是 warning 而不是 blocker：这一档说的是"形式化一个文件都没落"，不是
#: "表与正文对不上"。把它拦成 blocker 会让每一份不使用形式化的论文都交不了表，
#: 而承重结论没有形式化背书那件事已经由收工门的 `load_bearing` 与形式化门在管；
#: 但"这一趟一个形式化文件都没落"必须看得见（空着与"验过了"要分得开），所以它在
#: `warnings` 里。它不再是"两格必填"的触发器（2026-11-04：那一档按证明通道判）。
LEAN_WARN_KINDS: tuple[str, ...] = ("lean_on_but_no_artifact",)

#: 数值实验定理那一组（业主 2026-10-23，E-1）：证明栏是程序、三块与署名由 E 给。
#:
#: 真身在 `numerictheorem.NUMERIC_KINDS`（这里只是别名，别处不另抄一份）：缺程序路径、
#: 程序没有 E 签的穷举证明、缺 E 的读数编号、缺块 / 缺署名 / 缺出处、正文那段指不回读数。
NUMERIC_KINDS: tuple[str, ...] = NT.NUMERIC_KINDS

#: 顺序那一组三条（2026-11-26，GMAP）：编号由 C 的路径驱动、正文先后必须是依赖 DAG 的
#: 拓扑序（口径见模块 docstring「顺序」那一节）。
#:
#: - `mapping_order_not_topological`：一条依赖的前提排在用它的人之后
#:   （"依赖在前、使用在后"被颠倒 —— 定义挪到定理后面就是这一条）；
#: - `mapping_order_off_path`：这一行不在 C 声明的那条路径上 / 章内顺序与路径不一致 /
#:   声明的那条路径在台账里对不上任何一份报告 / 编号与章内顺序打架；
#: - `mapping_order_missing_node`：C 的路径上有这个节点，而表里没有它那一行
#:   （C 说这条路径自足，少一条就是证明链断在那儿）。
ORDER_NOT_TOPOLOGICAL = "mapping_order_not_topological"
ORDER_OFF_PATH = "mapping_order_off_path"
ORDER_MISSING_NODE = "mapping_order_missing_node"
ORDER_KINDS: tuple[str, ...] = (
    ORDER_NOT_TOPOLOGICAL, ORDER_OFF_PATH, ORDER_MISSING_NODE,
)

#: `MAPPING.json` 顶层的那个声明格：G 用的是 C 的哪一条路径（C 报告 `payload.order` 的原样）。
#:
#: 为什么把它写进表里而不是只留在工具层：读侧（H / 收工门 / 复核者）只有那份 json，
#: 而"这一篇按哪条路径写的"必须能从交付物本身读出来 —— 否则"编号按路径"这句话就只剩
#: 一句人话，复核时无从复算。声明与台账报告的比对由 :func:`order_reading` 一处做。
PATH_ORDER_FIELD = "path_order"

#: 本模块会产出的全部问题类别（判据要逐类覆盖它，见 `tests/test_paper_mapping_table.py`）。
#:
#: 只收拦门的那几组：`LEAN_WARN_KINDS` 不进这里（它在 `warnings` 里，不改 `state`）。
ALL_PROBLEM_KINDS: tuple[str, ...] = (
    MAPPING_KINDS + CITATION_KINDS + MD_KINDS + PAPER_KINDS + LEAN_KINDS + NUMERIC_KINDS
    + EVIDENCE_KINDS + ORDER_KINDS
)

#: 三态取值。
STATES: tuple[str, ...] = ("pass", "fail", "unknown")

#: 正文里定理类环境的开 / 闭标记（允许带星号，`end` 必须同名同星号）。
#:
#: 控制词与花括号之间的空格是合法 TeX（控制词后面的空格会被吞掉，
#: `\\begin {theorem}` 与 `\\begin{theorem}` 是同一件事），所以这里写 `\\s*`。
#: 硬要求 `\\begin\\{` 的后果不是"少读一个环境"而是"整条环境静默消失"（缺陷 1）。
_ENV_TOKEN_RE = re.compile(
    r"\\(?P<which>begin|end)\s*\{(?P<kind>" + "|".join(ENV_KINDS) + r")(?P<star>\*?)\}"
)

#: 只找"再开一个环境"：算外层的 label 时要在第一个内层环境处截断，
#: 否则外层会把内层的 `\\label` 认成自己的。
_ENV_OPEN_RE = re.compile(
    r"\\begin\s*\{(?:" + "|".join(ENV_KINDS) + r")(?:\*?)\}"
)

#: 环境里的标签（取第一个）。
_LABEL_RE = re.compile(r"\\label\{([^{}]*)\}")

#: `\\input{...}` / `\\include{...}`（附录与分节写法的正文都靠它接进来）。
_INPUT_RE = re.compile(r"\\(?:input|include)\s*\{\s*([^{}]+?)\s*\}")

#: 正文里引用附录那一行（注释剥离之后精确匹配；`\\input {mapping-appendix.tex}` 也算）。
_APPENDIX_INPUT_RE = re.compile(r"\\input\s*\{\s*mapping-appendix(?:\.tex)?\s*\}")

#: 台账代号必须是纯数字（宽度由 `schema.ID_DIGITS` 定，这里只判"是数字"）。
_DIGITS_RE = re.compile(r"^[0-9]+$")

#: LaTeX 特殊字符的替换表（逐字符映射：替换出来的反斜杠不会被二次转义）。
_TEX_SPECIALS: dict[str, str] = {
    "\\": "\\textbackslash{}", "&": "\\&", "%": "\\%", "$": "\\$", "#": "\\#",
    "_": "\\_", "{": "\\{", "}": "\\}", "~": "\\textasciitilde{}",
    "^": "\\textasciicircum{}",
}

#: `\input` / `\include` 的递归深度上限（TeX 自己不设上限，环会一路展开到内存耗尽）。
#:
#: 8 是"比任何真实论文的分节嵌套都深、又足够小到不会挂死"的取值：到 8 层还没到底就
#: 不再展开，并在 `problems` 里报一条 `mapping_unresolvable` —— 没跟完的正文不能
#: 读成"这里没有环境"（那会让正文侧全空，或者反过来把登记过的行全判成孤儿）。
MAX_TEX_INPUT_DEPTH = 8

#: `\begin{comment}` … `\end{comment}`（`comment` 宏包）整段不参与扫描。
_COMMENT_ENV_BEGIN_RE = re.compile(r"\\begin\s*\{comment\}")
_COMMENT_ENV_END_RE = re.compile(r"\\end\s*\{comment\}")

#: `\iffalse` 那一支的开头（TeX 会一直跳到配对的 `\fi`）。
_IFFALSE_RE = re.compile(r"\\iffalse(?![A-Za-z])")

#: `\if…` / `\fi` 的配对（找 `\iffalse` 的收尾用；`\else` 不影响层级）。
_COND_TOKEN_RE = re.compile(r"\\(?:if[A-Za-z]*|fi(?![A-Za-z]))")

#: `\verb<d>…<d>`：`\verb` 后面那个字符是分隔符，里面的 `%` / `\begin` 都不是正文。
_VERB_RE = re.compile(r"\\verb\*?(?P<delim>[^A-Za-z\s])")


def _is_escaped_percent(text: str, at: int) -> bool:
    """`text[at]` 是 `%`：前面有奇数个反斜杠就是被转义的 `\\%`（不是注释）。

    偶数个（`\\\\%`）是"换行命令 + 一条注释"，仍然是注释 —— 这一格按 TeX 的
    "反斜杠成对读"判，而不是看"前面有没有反斜杠"。
    """
    count = 0
    i = at - 1
    while i >= 0 and text[i] == "\\":
        count += 1
        i -= 1
    return count % 2 == 1


def _cond_skip_end(text: str, at: int) -> int:
    """从 `\\iffalse` 之后找到与它配对的 `\\fi` 的末尾（找不到 => 文本末尾）。"""
    depth = 1
    for m in _COND_TOKEN_RE.finditer(text, at):
        if m.group(0).startswith("\\fi"):
            depth -= 1
            if depth <= 0:
                return m.end()
            continue
        depth += 1
    return len(text)


def _blank_but_keep_lines(chunk: str) -> str:
    """把被剥掉的一段换成空格、换行保留（行号与列号因此仍然对得上原文件）。"""
    return "".join(ch if ch in "\r\n" else " " for ch in chunk)


def strip_tex_comments(tex: str) -> str:
    """剥掉 TeX 里不参与排版的字节，只留真正会被排出来的那部分。

    处理规则（与 TeX 自己一致的那几条）：

    - `%` 到行尾是注释；`\\%` 是转义出来的百分号，不是注释；`\\\\%` 是换行命令
      后面跟一条注释（反斜杠按成对读，所以它仍然是注释）；
    - `\\iffalse … \\fi` 整段（含套在里面的 `\\if…`）不参与；
    - `\\begin{comment} … \\end{comment}` 整段不参与；
    - `\\verb<d> … <d>` 里的内容不参与（分隔符之后的 `%` 不是注释）。

    剥掉的字节用空格顶替、换行保留：行号与列号与原文一致，报出来的"第 N 行"
    仍然指得回原文件。只有正文扫描（`body_envs`）与附录定位（`_appendix_block`）
    用得到它 —— 两处必须是同一套剥离规则，否则"什么算正文"就有了两份口径。
    """
    text = str(tex or "")
    out: list[str] = []
    i = 0
    end = len(text)
    while i < end:
        ch = text[i]
        if ch == "%" and not _is_escaped_percent(text, i):
            stop = text.find("\n", i)
            stop = end if stop < 0 else stop
            out.append(_blank_but_keep_lines(text[i:stop]))
            i = stop
            continue
        if ch == "\\":
            m = _COMMENT_ENV_BEGIN_RE.match(text, i)
            if m is not None:
                close = _COMMENT_ENV_END_RE.search(text, m.end())
                stop = end if close is None else close.end()
                out.append(_blank_but_keep_lines(text[i:stop]))
                i = stop
                continue
            m = _IFFALSE_RE.match(text, i)
            if m is not None:
                stop = _cond_skip_end(text, m.end())
                out.append(_blank_but_keep_lines(text[i:stop]))
                i = stop
                continue
            m = _VERB_RE.match(text, i)
            if m is not None:
                delim = str(m.group("delim"))
                stop = text.find(delim, m.end())
                stop = end if stop < 0 else stop + 1
                out.append(_blank_but_keep_lines(text[i:stop]))
                i = stop
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _problem(kind: str, detail: str, *, label: str = "", where: str = "") -> dict[str, Any]:
    """一条问题（四个字段都要有：kind 是 H 的分档把手，其余是给人看的定位）。"""
    return {"kind": kind, "detail": detail, "label": label, "where": where}


def _int_or_none(value: Any) -> int | None:
    """把一个正整数写成的东西读成 int（`2` / `"2"`）；读不成或小于 1 => None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, str):
        text = value.strip()
        if _DIGITS_RE.match(text):
            got = int(text)
            return got if got >= 1 else None
    return None


def _tex_escape(text: Any) -> str:
    """把一段文字转成能放进 `tabular` 的 LaTeX（逐字符替换，顺序无关）。"""
    return "".join(_TEX_SPECIALS.get(ch, ch) for ch in str(text or ""))


@dataclass(frozen=True)
class Row:
    """对应表里的一行。"""

    kind: str
    label: str
    env_no: int
    ledger_id: str
    proof_no: int
    #: 这一行的证明稿 / 实验程序在哪（包内相对路径）。定义行没有证明稿，这一格
    #: 允许空（`NO_MANUSCRIPT_KINDS` / `manuscript_required`）；其余行必填。
    file: str = ""
    #: ---- 机器核验凭据那一格（字段名不变，语义见 `CREDENTIAL_CELL_NAME`） ----------
    #:
    #: `lean_file`：这一条命题的机器核验凭据（百分百为真）—— 形式化通道是那份 `.lean`
    #: 的位置，数值证明通道是证明栏第 ① 段那份 `.py` 程序；没有证明通道时允许为空。
    #: 字段名保持 `lean_file`（不改名：表头、解析、两份渲染产物都不动）。
    #: `lean_target`：形式化通道那一半（那份 `.lean` 里字面出现的声明名）；数值证明
    #: 通道不填它（一份数值程序没有 Lean 声明名）。
    lean_file: str = ""
    lean_target: str = ""
    page_or_section: str = ""
    citation_loc: Mapping[str, Any] | None = None
    citation_loc_reason: str = ""
    #: E 的那条穷举读数（`exp:NNNNNN`）：数值实验定理那一行必须给（业主 2026-10-23）。
    numeric_evidence: str = ""
    #: E 写的那两块（程序设计思路 / 穷举论证）与运行环境落在哪份读数里（相对仓库根）。
    exhaustion_note: str = ""
    #: ---- 索引四格（D-34；列义只有一份，在 `numericproof.INDEX_*`） --------------
    #:
    #: D 的报告是目录：每一行必须指得到正文那一份（F 的证明 / E 的报告）、
    #: 说得出它的字节指纹、并带上 V 签的那一格的 sha。四格缺一件，"读目录去取正文"
    #: 这件事就断在那儿 —— 而 B 的入库正是顺着它走的。
    evidence_kind: str = ""
    evidence_path: str = ""
    evidence_sha256: str = ""
    #: 那份稿的字节 sha256（`PROOF_FILE_SHA_FIELD`；写表那一刻盘上那一份字节）。
    #: 与 `evidence_sha256` 是两件事：后者是 `## 证明` 正文的 sha（V 签同一把尺），
    #: 前者是文件字节（签块写回会合法地改它）。两态：稿在就填，与签没签无关。
    evidence_file_sha256: str = ""
    #: `{"verdict": "成立", "sha256": <被签那一份的 sha256>}`。
    v_signature: Mapping[str, Any] | None = None
    #: ---- 台账那两格（D-69）：不手填，由 `fill_ledger_cells` 现读现填 ------------
    #:
    #: `ledger_kind` 是台账那一行自己的 `kind`；`reviewed` 是 V 拿这一份怎么办（四档）。
    #: 空串 = 这一格没填（旧表 / 还没填过）—— 渲染时印 `未读到`，不印空白。
    ledger_kind: str = ""
    reviewed: str = ""
    #: 优化态那一格（业主 2026-11-02 两阶段录入）：已优化 / 未优化 / 未记录。
    #: 与 `reviewed` 同一个落法：不手填，由 `fill_ledger_cells` 按台账现读现填。
    optimized: str = ""
    #: 这一份证明的来源（own / citation / 空）：收工门按来源分档的同一格口径。
    proof_source: str = ""
    #: ---- 被引实验行的那几格（2026-11-25，MAPPING-COMPLETE） ----------------------
    #:
    #: 只在 `ledger_id` 是 `exp:NNNNNN` 的行上有值（`env_no=0` 表示"被引、未印成环境"）。
    #: 全部由 `fill_experiment_cells` 从 `experiments` 那一行现读现填：G 不写，写侧也不猜。
    #: `file` 就是 `experiments.code_path`（一格一源，不再另立 `experiment_code`）；
    #: 日志逐份列在 `experiment_logs`（`artifact_paths` 原样，不许只取第一份）。
    experiment_logs: tuple[str, ...] = ()
    experiment_code_hash: str = ""
    experiment_result: str = ""
    experiment_negation_kind: str = ""
    experiment_params: str = ""
    experiment_exit_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """写回 json 的形状（字段顺序固定，diff 才读得懂）。"""
        out: dict[str, Any] = {"kind": self.kind, "label": self.label,
                               "env_no": int(self.env_no), "ledger_id": self.ledger_id,
                               "proof_no": int(self.proof_no), "file": self.file,
                               # 台账那两格（D-69）：三份同源的第一份。旧表没有这两键，
                               # 那一档由读侧读成 `未读到`（不许读成「已签」，也不许折成
                               # 「未通过」或「未审」）。
                               LEDGER_KIND_FIELD: self.ledger_kind,
                               REVIEWED_FIELD: self.reviewed,
                               # 优化态与来源（业主 2026-11-02）：与上面两格同一个落法 ——
                               # 写侧按台账现读现填（`fill_ledger_cells`），旧表没有这两键
                               # 时读成空串 ⇒ 渲染印「未记录」，不印空白。
                               OPTIMIZED_FIELD: self.optimized,
                               PROOF_SOURCE_FIELD: self.proof_source}
        if self.lean_file:
            out["lean_file"] = self.lean_file
        if self.lean_target:
            out["lean_target"] = self.lean_target
        if self.page_or_section:
            out["page_or_section"] = self.page_or_section
        if self.citation_loc is not None:
            out["citation_loc"] = dict(self.citation_loc)
        if self.citation_loc_reason:
            out["citation_loc_reason"] = self.citation_loc_reason
        if self.numeric_evidence:
            out["numeric_evidence"] = self.numeric_evidence
        if self.exhaustion_note:
            out["exhaustion_note"] = self.exhaustion_note
        if self.evidence_kind:
            out[NP.INDEX_KIND_FIELD] = self.evidence_kind
        if self.evidence_path:
            out[NP.INDEX_PATH_FIELD] = self.evidence_path
        if self.evidence_sha256:
            out[NP.INDEX_SHA_FIELD] = self.evidence_sha256
        if self.evidence_file_sha256:
            out[PROOF_FILE_SHA_FIELD] = self.evidence_file_sha256
        if self.v_signature is not None:
            out[NP.INDEX_SIGN_FIELD] = dict(self.v_signature)
        # 被引实验行那几格（2026-11-25）：只在该行有值时写出来 —— 旧表 / 定理行不受影响，
        # 追加在末尾保证既有键的位置一个都不动（读侧按位置读的那几处不会错位）。
        if self.experiment_logs:
            out[EXPERIMENT_LOGS_FIELD] = [str(p) for p in self.experiment_logs]
        if self.experiment_code_hash:
            out[EXPERIMENT_CODE_HASH_FIELD] = self.experiment_code_hash
        if self.experiment_result:
            out[EXPERIMENT_RESULT_FIELD] = self.experiment_result
        if self.experiment_negation_kind:
            out[EXPERIMENT_NEGATION_FIELD] = self.experiment_negation_kind
        if self.experiment_params:
            out[EXPERIMENT_PARAMS_FIELD] = self.experiment_params
        if self.experiment_exit_code is not None:
            out[EXPERIMENT_EXIT_FIELD] = int(self.experiment_exit_code)
        return out


@dataclass(frozen=True)
class BodyEnv:
    """正文里的一个定理类环境（`line` 是 1 起的行号）。

    `file` 是它所在那一份 tex 相对论文包的名字（`main.tex` 或 `sections/body.tex`）：
    跟了 `\\input` 之后，"第 12 行"必须说得清是哪个文件的第 12 行，否则报出来的
    位置指不回原文件。

    `start` / `end` 是它在（已经剥离注释的）那段正文里的字节区间：数值实验定理那一条
    要读"定理那一段"里有没有指回 E 的读数（`theorem_segments`），而"那一段"正是从
    这个区间的末尾往后接一个 `proof` 环境。默认 0/0 表示"没记位置"（别的调用方不关心它）。
    """

    kind: str
    label: str
    env_no: int
    line: int
    file: str = ""
    start: int = 0
    end: int = 0


@dataclass
class _RowCheck:
    """一行的校验结果（问题清单 + 解析到的台账行，供第二个方向复用）。"""

    problems: list[dict[str, Any]] = field(default_factory=list)
    ledger_row: Mapping[str, Any] | None = None
    proof_no: int = 0

    def add(self, kind: str, detail: str, *, label: str = "", where: str = "") -> None:
        self.problems.append(_problem(kind, detail, label=label, where=where))


def is_experiment_row(row: Row) -> bool:
    """这一行是不是「被引实验行」（`ledger_id` 指 `experiments` 表）。

    只按 `ledger_id` 的前缀判，与 `resolve_ledger_id` 认的台账表同一条口径
    （`schema.CITATION_PREFIXES["exp"] == "experiments"`）；不另立一份"实验行"词表。
    """
    return str(getattr(row, "ledger_id", "") or "").strip().startswith(EXPERIMENT_ID_PREFIX)


def experiment_id_of_row(row: Row) -> str:
    """这一行的实验号（`exp:000003` ⇒ `"000003"`）；不是实验行 ⇒ 空串。"""
    if not is_experiment_row(row):
        return ""
    return str(row.ledger_id).strip()[len(EXPERIMENT_ID_PREFIX):].split("#", 1)[0].strip()


def is_literature_row(row: Row) -> bool:
    """这一行是不是「被引文献行」（`ledger_id` 指 `literature` 表）。

    2026-11-26（GMAP）：正文里引来的成果（"这一条引自 Erdős–Rado 1960"）也是对应表里
    的一行 —— 第三列要指得到那份具体的文献文件。只按 `ledger_id` 的前缀判，与
    `resolve_ledger_id` 认的台账表同一条口径（`schema.CITATION_PREFIXES["lit"] ==
    "literature"`），不另立词表。
    """
    return str(getattr(row, "ledger_id", "") or "").strip().startswith(LITERATURE_ID_PREFIX)


def literature_id_of_row(row: Row) -> str:
    """这一行的文献号（`lit:000003` ⇒ `"000003"`）；不是文献行 ⇒ 空串。"""
    if not is_literature_row(row):
        return ""
    return str(row.ledger_id).strip()[len(LITERATURE_ID_PREFIX):].split("#", 1)[0].strip()


def is_cited_only_row(row: Row) -> bool:
    """这一行是不是「被引、未印成环境」（`env_no == EXPERIMENT_ENV_NO`）。

    只有实验行与文献行允许 `env_no=0`（由 `parse_rows` 保证）：定理类环境必须真的印在
    正文里，「被引未印」这件事对它们不成立。文献行是 2026-11-26（GMAP）补的：引来的
    成果往往写成一句带出处的散文（`\\paragraph{Source …}`），不占一个定理环境，而它
    照样要在表里有一行、指得到那份文件。
    """
    if int(row.env_no) != EXPERIMENT_ENV_NO:
        return False
    return is_experiment_row(row) or is_literature_row(row)


def is_load_bearing_row(row: Row | Mapping[str, Any]) -> bool:
    """承重命题的唯一判据：论文里以 `STATEMENT_ENV_KINDS`（定理类四件套）之一印出来的行。

    2026-11-26 BEARINGDEF 的根因（真机 sunflower-digest-2）：同一个概念"论文里的承重
    命题"被四处各定义了一次，四个集合互不相同 —— `proof_source == own`（本模块旧
    `evidence_cells_for_row`, `_proof_index_problems`）、`STATEMENT_ENV_KINDS`
    （`kind_gap_reading` 的 `theorem_unsigned`，只有 theorem/lemma）、
    `STATEMENT_ENV_KINDS`（正文环境侧）、`documents.claims` 的 `evidence_kind=="proof"`
    （`closing` 的 load_bearing 那格）。`prop:block`（proposition）与 `thm:erdos-rado`
    （`origin=external_lit`）恰好落在并集之外：正文里它们带完整证明，而填充 / 门 /
    落差读数三处都不算它们承重 ⇒ 一条读数都看不见。

    判据只问一件事：这一行在正文里是不是印成了定理类环境（`kind` 就是那个环境名，
    由 `parse_rows` 从表里读、由 `_orphan_problems` 与正文逐一对上）。所以：

    - 与 `origin` 无关（外部文献来的命题也是论文里的承重命题）；
    - 与 `proof_source` 无关（"这行引了文献"不是"它没有自己的证明"）；
    - 与 V 签没签无关（没签是"承重但没签"，不是"不承重" —— 这两件事今天必须分开）；
    - 与论文里排成 theorem / lemma / proposition / corollary 哪一件无关（四件套同档）；
    - 例子 / 实验不是"被证明的命题"，不进这一档（`EXPERIMENT_ENV_NO` 的被引实验行同理）。

    四个消费点都读它，不许各写一份：`evidence_cells_for_row`（写侧填充）、
    `_proof_index_problems`（门）、`kind_gap_reading`（`theorem_unsigned` 读数）、
    `closing._mapping_row_missing_cells`（收工门 CH8 的"该有格"）。
    判据的单一性由 `tests/test_bearingdef_load_bearing_evidence.py` 的反真空钉着：
    把它打桩成恒假 ⇒ 四处同时退回旧形态。
    """
    if isinstance(row, Mapping):
        kind = str(row.get("kind") or "").strip()
        ledger_id = str(row.get("ledger_id") or "")
        env_no: Any = row.get("env_no", 1)
    else:
        kind = str(getattr(row, "kind", "") or "").strip()
        ledger_id = str(getattr(row, "ledger_id", "") or "")
        env_no = getattr(row, "env_no", 1)
    if ledger_id.strip().startswith(EXPERIMENT_ID_PREFIX):
        return False
    try:
        if int(env_no) == EXPERIMENT_ENV_NO:
            return False
    except (TypeError, ValueError):
        # `env_no` 读不成整数时不当"被引未印"：只按 kind 判（非实验行的正常形态）。
        pass
    return kind in STATEMENT_ENV_KINDS



def package_dir(project_root: str | Path) -> Path:
    """论文包目录（`<项目根>/out/package`，与 `papercompile` 同一处——不另写一份路径）。"""
    return PC.package_dir(project_root)


def mapping_paths(project_root: str | Path) -> tuple[Path, Path]:
    """对应表两个落点的绝对路径（`(json, md)`），都在论文包里。"""
    pkg = package_dir(project_root)
    return pkg / MAPPING_JSON_NAME, pkg / MAPPING_MD_NAME


def appendix_path(project_root: str | Path) -> Path:
    """正文附录那一份（由 json 渲染）的绝对路径。"""
    return package_dir(project_root) / APPENDIX_FILE_NAME


def index_rows(project_root: str | Path) -> list[dict[str, Any]]:
    """盘上那张表的原始行（D 报告里那些目录行；读不到 ⇒ 空清单）。

    为什么要这个入口（D-34）：B 的入库是"读 D 的报告 → 顺着索引去取 F 的证明 / E 的报告 →
    核 V 签"。B 手上只有工作区根，而表的落点、文件名的口径都在本模块（`mapping_paths`），
    所以它从这里取，不自己拼路径。三态：读不到 / 坏 json ⇒ 空清单 —— 调用方（`numericproof`
    的入库闸）把它读成"目录里没有这一条"，折的方向是拒，不是放行。
    """
    path, _md = mapping_paths(project_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    raw = payload.get("rows") if isinstance(payload, Mapping) else payload
    if not isinstance(raw, (list, tuple)):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _env_token_re(kinds: Sequence[str]) -> re.Pattern[str]:
    """某一组环境名对应的 begin / end 标记（`_ENV_TOKEN_RE` 是 `ENV_KINDS` 那一档）。"""
    return re.compile(
        r"\\(?P<which>begin|end)\s*\{(?P<kind>"
        + "|".join(re.escape(k) for k in kinds) + r")(?P<star>\*?)\}")


def _env_open_re(kinds: Sequence[str]) -> re.Pattern[str]:
    """某一组环境名对应的"再开一个环境"标记（算外层 label 时在这截断）。"""
    return re.compile(
        r"\\begin\s*\{(?:" + "|".join(re.escape(k) for k in kinds) + r")(?:\*?)\}")


def _scan_envs(text: str, counts: dict[str, int], *, where_file: str = "",
               line_offset: int = 0,
               kinds: Sequence[str] | None = None) -> list[BodyEnv]:
    """在已经剥离注释的正文里栈式扫环境（嵌套时内外层各自产出一条）。

    为什么用栈而不是一条非贪婪正则：非贪婪会一路匹配到最内层那个 `end` 之后，
    `finditer` 再从外层末尾往下扫，夹在中间的内层环境就整条消失（缺陷 5）。
    这里遇到 `\\begin{X}` 压栈、遇到配对的 `\\end{X}` 弹栈，栈里每个环境各自一条；
    `env_no` 在压栈时按同类计数，所以外层的序号不因内层而偏移。

    `counts` 由调用方跨文件 / 跨片段传进来：`env_no` 是"读完所有 `\\input` 之后的
    整体出现顺序"，每份文件各自从头数会让序号与正文对不上。

    `kinds` 是这次要认的环境名（缺省 = `ENV_KINDS`，即对应表那六类）；"一条命题对一个
    环境"那一条会把它换成 `statement_env_names()` 的读数（多认印成 Lemma 的自定义宏）。
    """
    found: list[tuple[int, BodyEnv]] = []
    opens: list[dict[str, Any]] = []
    token_re = _ENV_TOKEN_RE if kinds is None else _env_token_re(kinds)
    open_re = _ENV_OPEN_RE if kinds is None else _env_open_re(kinds)
    for m in token_re.finditer(text):
        kind = str(m.group("kind"))
        star = str(m.group("star"))
        if m.group("which") == "begin":
            counts[kind] = counts.get(kind, 0) + 1
            opens.append({"kind": kind, "star": star, "start": m.start(),
                          "body": m.end(), "env_no": counts[kind]})
            continue
        if not opens:
            continue
        top = opens[-1]
        if (top["kind"], top["star"]) != (kind, star):
            # 不配对的 `\\end`：TeX 自己也会报错，这里不弹栈（弹了会把外层错配掉）。
            continue
        opens.pop()
        body = text[int(top["body"]):m.start()]
        inner = open_re.search(body)
        if inner is not None:
            body = body[:inner.start()]
        label = _LABEL_RE.search(body)
        found.append((int(top["start"]), BodyEnv(
            kind=kind, label=(label.group(1).strip() if label else ""),
            env_no=int(top["env_no"]),
            line=line_offset + text.count("\n", 0, int(top["start"])) + 1,
            file=where_file, start=int(top["start"]), end=m.end())))
    found.sort(key=lambda item: item[0])
    return [env for _pos, env in found]


def body_envs(tex: str) -> list[BodyEnv]:
    """单份正文里的全部定理类环境（按出现顺序，`env_no` 按同类计数、1 起）。

    先剥离注释再扫（`strip_tex_comments`）：注释掉 / `\\iffalse` 包住 / `\\verb`
    里的 `\\begin{...}` 不是正文环境。跨 `\\input` 的读法见 `_body_envs_of_package`。
    """
    counts: dict[str, int] = {}
    return _scan_envs(strip_tex_comments(str(tex or "")), counts)


def _printed_env_title(title: str) -> str:
    """`\\newtheorem` 标题那一段"印出来的第一个词"（小写；去掉命令与花括号）。"""
    plain = re.sub(r"\\[A-Za-z]+\*?", " ", str(title or ""))
    words = re.findall(r"[A-Za-z]+", plain.lower())
    return words[0] if words else ""


def statement_env_names(tex: str) -> tuple[str, ...]:
    """正文里算"定理类环境"的全部环境名。

    = `STATEMENT_ENV_KINDS` + 导言区里那些"印出来是 Theorem / Lemma / Proposition /
    Corollary"的自定义环境。只认标题、不认环境名：`\\newtheorem{claim}{Claim}` 印的是
    Claim，不算定理类环境；`\\newtheorem{claim}[theorem]{Lemma}` 印的是 Lemma，算 ——
    读者看到的是一行 "Lemma 3.4"，它与 `\\begin{lemma}` 在正文里没有任何区别。

    只读主文件（`main.tex`）的导言区：自定义环境通常只在那里声明，而 `\\input` 进来的
    分节文件用的是同一份导言区。
    """
    names = list(STATEMENT_ENV_KINDS)
    for m in _NEWTHEOREM_RE.finditer(strip_tex_comments(str(tex or ""))):
        name = m.group("name").strip()
        if not name or name in names:
            continue
        if _printed_env_title(m.group("title")) in STATEMENT_ENV_TITLES:
            names.append(name)
    return tuple(names)


def statement_envs_of_text(tex: str) -> list[BodyEnv]:
    """单份正文里全部定理类环境（`body_envs` 再加上印成 Lemma 的自定义环境）。

    只用于"一条命题对一个环境"那一条（`_statement_surplus_problems`）：对应表本身
    仍然按 `ENV_KINDS` 六类登记 —— 自定义环境在表里没有 `kind` 可写，那正是这一条
    要报的形态（它不是"另一类合法的环境"，而是"绕开对应表的那条路"）。
    """
    clean = strip_tex_comments(str(tex or ""))
    return _scan_envs(clean, {}, kinds=statement_env_names(clean))


def env_title_of(kind: Any) -> str:
    """某一类映射行在正文里该印哪个抬头（`ENV_TITLES` 的唯一读口；认不出 ⇒ 空串）。

    空串是"认不出这一档"，不是"哪一档都行"：调用方（`environment_titles`）把它
    读成"这一行没有可对照的抬头"，于是"摘掉 example 那一格"会当场变成一格红读数。
    """
    return ENV_TITLES.get(str(kind or "").strip().lower(), "")


def _newtheorem_titles(tex: str) -> dict[str, str]:
    """导言区 `\\newtheorem{名字}{标题}` ⇒ `{名字: 标题第一个词（小写）}`。

    只读印出来的第一个词（与 `statement_env_names` 同一把尺）：`{Example}` 与
    `{Example (toy)}` 都读成 `example`。读不到的（没有声明、或标题是纯命令）不进表。
    """
    out: dict[str, str] = {}
    for m in _NEWTHEOREM_RE.finditer(strip_tex_comments(str(tex or ""))):
        name = m.group("name").strip()
        title = _printed_env_title(m.group("title"))
        if name and title:
            out[name] = title
    return out


def environment_titles(rows: Iterable[Row], *, tex: str = "") -> dict[str, Any]:
    """对应表逐行「该用哪个环境抬头」的读数，以及正文导言区实际印的是什么。

    `kind=example` 的行（玩具例子）：正文用
    `Example` 环境，不用 Lemma/Theorem；其余按既有映射。这一格就是这条口径的机器读数。

    逐行给：

    | 键 | 意思 |
    |---|---|
    | `kind` / `label` | 这一行说的是哪一类环境的哪一个（对应表原样） |
    | `env_title` | 这一行该印的抬头（`ENV_TITLES`；认不出 ⇒ 空串） |
    | `declared` | 导言区 `\\newtheorem{<kind>}{…}` 实际印出来的抬头；读不到 ⇒ 空串 |
    | `ok` | `env_title` 非空，且（没有声明 或 声明与它同名，不分大小写） |

    `declared` 为空是"没查成"（没有 `\\newtheorem` 可对 —— 夹具与大部分手稿的
    环境由文档类直接给），不是"印错了"：三态纪律在这里就是"读不到 ⇒ 不据此判红"。

    返回 `{"checked": True, "titles": {kind: title}, "rows": [...], "unknown": [...],
    "mismatched": [...]}`。它是「读数」（与 `kind_gap` / `theorem_unsigned` 同族），
    不进 `problems`、不改 `state`；判它红不红是调用方的事（判据见
    `tests/test_example_g_mapping_is_the_example_environment.py` 的 d/e）。

    为什么按 `row.kind` 找 `declared`：对应表与正文的对齐口径是"环境名 = kind"
    （`_orphan_problems` 按 `(kind, label)` 配），所以 `kind=example` 那一行对的就是
    `\\begin{example}` 与 `\\newtheorem{example}{…}`。
    """
    declared_titles = _newtheorem_titles(tex)
    items: list[dict[str, Any]] = []
    unknown: list[str] = []
    mismatched: list[dict[str, str]] = []
    for row in rows:
        kind = str(row.kind or "").strip().lower()
        title = env_title_of(kind)
        declared = str(declared_titles.get(kind) or "")
        ok = bool(title) and (not declared or declared == title.lower())
        items.append({"kind": kind, "label": str(row.label or ""),
                      "env_title": title, "declared": declared, "ok": ok})
        if not title:
            unknown.append(kind)
        elif not ok:
            mismatched.append({"kind": kind, "label": str(row.label or ""),
                               "env_title": title, "declared": declared})
    return {"checked": True, "titles": {k: v for k, v in ENV_TITLES.items()},
            "rows": items, "unknown": unknown, "mismatched": mismatched}


def _env_where(env: BodyEnv) -> str:
    """一个环境该被点名的位置（`文件:行`；`main.tex` 之外的按读入时的相对路径写）。"""
    return f"{env.file or PC.TEX_NAME}:{env.line}"


def _tex_input_names(tex: str) -> list[str]:
    """剥离注释后，按出现顺序给出 `\\input` / `\\include` 的文件名。"""
    return [m.group(1).strip() for m in _INPUT_RE.finditer(strip_tex_comments(str(tex or "")))]


def _input_target(base: Path, name: str) -> Path | None:
    """`\\input{name}`（相对 `base`）指向的文件；没有后缀时也试 `.tex`；读不到 => None。"""
    raw = Path(str(name or "").strip())
    if not str(raw) or not raw.name:
        return None
    candidates = [base / raw]
    if not raw.suffix:
        candidates.append((base / raw).with_suffix(".tex"))
    for cand in candidates:
        try:
            if cand.is_file():
                return cand.resolve()
        except OSError:
            continue
    return None


def _rel_to(package: Path, path: Path) -> str:
    """一个 tex 相对论文包的名字（包外给文件名本身，便于人读）。"""
    try:
        return path.resolve().relative_to(package.resolve()).as_posix()
    except (OSError, ValueError):
        return path.name


def _collect_tex_segments(package: Path, main_path: Path, main_text: str
                          ) -> tuple[list[tuple[str, str, int]], list[str],
                                     list[dict[str, Any]]]:
    """按 TeX 的内联顺序把正文切成"片段"，跟完 `\\input` / `\\include`。

    返回 `([(相对名, 片段, 起始行偏移), …], [读过的文件（读入顺序）, …], 问题)`。
    为什么要切片段而不是"每个文件整段扫"：`main.tex` 里 `\\input` 之后的定理，
    在 TeX 眼里排在分节文件之后；整份文件先扫会让 `env_no` 整体错位（表里写的
    序号与正文对不上，报出来的是 `mapping_orphan`，而正文侧其实没错）。

    环用"当前这一支已经展开过的绝对路径"判；长度用 `MAX_TEX_INPUT_DEPTH` 兜底。
    两条都报 `mapping_unresolvable` 并停止展开（不报就等于把"没读到"读成"没有"）。
    一个环境不能横跨 `\\input` 边界（片段是分开扫的）—— 真实论文里没有这种写法。
    """
    segments: list[tuple[str, str, int]] = []
    files: list[str] = []
    problems: list[dict[str, Any]] = []
    stack: list[Path] = []
    chain: list[str] = []

    def visit(path: Path, text: str, depth: int) -> None:
        rel = _rel_to(package, path)
        if rel not in files:
            files.append(rel)
        # 环判据比的是解析后的绝对路径：相对路径写法不同（`main.tex` / `./main.tex`）
        # 不能让同一个文件被当成两个。
        stack.append(path.resolve())
        chain.append(rel)
        try:
            clean = strip_tex_comments(text)
            names = _tex_input_names(text)
            if names and depth >= MAX_TEX_INPUT_DEPTH:
                problems.append(_problem(
                    "mapping_unresolvable",
                    f"正文 \\input 递归到第 {depth} 层（上限 {MAX_TEX_INPUT_DEPTH}）还没到底："
                    f"{' -> '.join(chain + [names[0]])} —— 这一支不再展开；"
                    "没跟完的正文不能读成「这里没有环境」",
                    where=rel))
                segments.append((rel, clean, 0))
                return
            pos = 0
            for m in _INPUT_RE.finditer(clean):
                if m.start() > pos:
                    segments.append((rel, clean[pos:m.start()],
                                     text.count("\n", 0, pos)))
                name = m.group(1).strip()
                target = _input_target(path.parent, name)
                if target is None:
                    problems.append(_problem(
                        "mapping_unresolvable",
                        f"正文 {rel} 里的 \\input{{{name}}} 指的文件读不到"
                        f"（按 {path.parent} 解析，原名与 .tex 都试过）—— "
                        "这一支的定理类环境没有进表，别把「没读到」读成「没有」",
                        where=rel))
                elif target in stack:
                    problems.append(_problem(
                        "mapping_unresolvable",
                        f"正文 \\input 成环：{' -> '.join(chain + [name])} —— "
                        "这一支不再展开（不是「这里没有环境」）",
                        where=rel))
                else:
                    try:
                        sub = target.read_text(encoding="utf-8")
                    except OSError as exc:
                        problems.append(_problem(
                            "mapping_unresolvable",
                            f"正文 {rel} 里的 \\input{{{name}}} 读不出来"
                            f"（{type(exc).__name__}: {exc}）—— 这一支没有进表",
                            where=rel))
                    else:
                        visit(target, sub, depth + 1)
                pos = m.end()
            if pos < len(clean):
                segments.append((rel, clean[pos:], text.count("\n", 0, pos)))
        finally:
            stack.pop()
            chain.pop()

    visit(main_path, main_text, 0)
    return segments, files, problems


#: 分章的标记（`\section` / `\chapter`，带星号也认）。它只用来回答"这个环境落在第几章"，
#: 不参与"正文里有哪些环境"—— 章是叙述结构，环境才是条目。
_SECTION_RE = re.compile(r"\\(?:chapter|section)\*?\s*\{")


def _body_envs_with_sections(package: Path, main_path: Path, main_text: str
                             ) -> tuple[list[BodyEnv], list[BodyEnv], list[int],
                                        list[str], list[dict[str, Any]]]:
    """正文那一侧的完整读数 + 每个环境落在第几章（0 = 第一个 `\\section` 之前）。

    章号从正文结构读（`\\section` / `\\chapter` 的先后），不看 label 长什么样 ——
    所以"章内顺序"这一问与"G 怎么编号"是两件事，可以分开核。

    其余口径与 :func:`_body_envs_of_package` 完全一致（后者只是这里的薄包装）：
    环境片段按 TeX 的内联顺序切（`_collect_tex_segments`），`env_no` 跨文件连续计数。
    """
    segments, files, problems = _collect_tex_segments(package, main_path, main_text)
    counts: dict[str, int] = {}
    envs: list[BodyEnv] = []
    sections: list[int] = []
    names = statement_env_names(main_text)
    statement_counts: dict[str, int] = {}
    statement_envs: list[BodyEnv] = []
    section = 0
    for rel, segment, line_offset in segments:
        # 章标记与"再开一个环境"的标记按位置合并扫一遍：环境按它前面最近的那个章算。
        marks = sorted([(m.start(), "section") for m in _SECTION_RE.finditer(segment)]
                       + [(m.start(), "env") for m in _ENV_OPEN_RE.finditer(segment)])
        section_at: dict[int, int] = {}
        for at, what in marks:
            if what == "section":
                section += 1
            else:
                section_at[at] = section
        for env in _scan_envs(segment, counts, where_file=rel, line_offset=line_offset):
            envs.append(env)
            sections.append(section_at.get(int(env.start), section))
        statement_envs.extend(_scan_envs(segment, statement_counts, where_file=rel,
                                         line_offset=line_offset, kinds=names))
    return envs, statement_envs, sections, files, problems


def _body_envs_of_package(package: Path, main_path: Path, main_text: str
                          ) -> tuple[list[BodyEnv], list[BodyEnv], list[str],
                                     list[dict[str, Any]]]:
    """正文那一侧的完整读数：环境、定理类环境（含印成 Lemma 的自定义宏）、这次读了
    哪几个文件（读入顺序）、读不完的问题。

    为什么两列分开返回：`envs` 是对应表那几类（表行按它登记），`statement_envs` 多认
    那些"印出来是 Lemma"的自定义宏 —— 只有"一条命题对一个环境"那一条读第二列。
    把两列合成一列会让每一份用了 `claim` 宏的正文都要求表里多出几行没有 `kind` 可写的行。
    """
    envs, statement_envs, _sections, files, problems = _body_envs_with_sections(
        package, main_path, main_text)
    return envs, statement_envs, files, problems


#: `proof` 环境的开 / 闭标记。它与 `ENV_KINDS` 分开：`proof` 不进对应表（一条定理占一行），
#: 但数值实验定理那三块的引用就写在它里面，所以"那一段"要把它接进来。
_PROOF_OPEN_RE = re.compile(r"\\begin\s*\{proof\*?\}")
_PROOF_CLOSE_RE = re.compile(r"\\end\s*\{proof\*?\}")


def _segment_of(text: str, env: BodyEnv) -> str:
    """一个定理环境那一段：它自己 + 紧随其后的第一个 `proof` 环境。

    中间夹着别的定理类环境的那一档不接（那个 `proof` 不是这条定理的）：
    否则"某一条定理的证明里写了出处"会让整份正文里每一条数值实验定理都算指得回。
    """
    body = text[int(env.start):int(env.end)]
    tail = text[int(env.end):]
    opened = _PROOF_OPEN_RE.search(tail)
    if opened is None:
        return body
    if _ENV_OPEN_RE.search(tail[:opened.start()]) is not None:
        return body
    closed = _PROOF_CLOSE_RE.search(tail, opened.end())
    end = closed.end() if closed is not None else opened.end()
    return body + "\n" + tail[opened.start():end]


def theorem_segments(project_root: str | Path, *,
                     tex: str | None = None) -> dict[str, str]:
    """`label` -> 那条定理"那一段"的正文（环境自身 + 紧跟其后第一个 `proof` 环境）。

    为什么不整份正文搜一遍：整份搜等于"任何一句顺带提到那份程序的话"都能让判据变绿，
    而判据要问的是"这条数值实验定理那一段有没有指回 E 的读数"。纯读，不写盘。
    `tex` 直接给了就只扫这一份（调用方已经读过盘、或没有盘的情形）。
    """
    package = package_dir(project_root)
    if tex is None:
        main_path = package / PC.TEX_NAME
        if not main_path.is_file():
            # 空输入理应得空输出：没有正文就没有"那一段"。调用方那边不会把它读成
            # "指得回"——`mapping_reading` 会先按 `has_paper` 判过"有没有正文"，
            # 真到了这里还没正文的分支落的是 `mapping_numeric_citation_missing`。
            return {}
        try:
            main_text = main_path.read_text(encoding="utf-8")
        except OSError:
            # 读不出来的那一档同样是"没有那一段"，由调用方落 `mapping_numeric_citation_missing`
            # （"没读到"不许读成"没有要求"）。
            return {}
        segments = _collect_tex_segments(package, main_path, main_text)[0]
    else:
        segments = [(PC.TEX_NAME, strip_tex_comments(str(tex)), 0)]
    out: dict[str, str] = {}
    for _rel, segment, _offset in segments:
        for env in _scan_envs(segment, {}):
            if not env.label or env.label in out:
                continue
            out[env.label] = _segment_of(segment, env)
    return out


#: 台账文件解析缓存：`路径 -> ((mtime_ns, size), 行)`。
#:
#: 为什么要有这一格：`read_ledger_tables` 一次解析三张台账文件，而它在一趟收工门里
#: 会被调两次以上（`fill_ledger_cells` 一次、`mapping_reading` 一次；两者都接受
#: 调用方传 `ledger=` 来省掉第二遍，但那条路要调用方记得传）。键是
#: `(mtime_ns, size)`：别的进程（`store` 的 `os.replace`）一写就变 ⇒ 下一次重解析。
#: 交回的每一行都是新 dict，所以"调用方改顶层字段"污染不到缓存；行里嵌套的
#: list/dict 仍与缓存共享（要改请整格赋新对象）。
_LEDGER_CACHE: dict[str, tuple[tuple[int, int], list[Mapping[str, Any]]]] = {}
#: 缓存最多留几份文件（多工作区并行时无上限就是无界增长）。
_LEDGER_CACHE_MAX: int = 64


def _ledger_file_rows(path: Path) -> list[Mapping[str, Any]]:
    """一份台账文件的行（按 `(mtime_ns, size)` 缓存；不在盘上 / 坏 JSON ⇒ 空表）。"""
    try:
        st = path.stat()
    except OSError:
        _LEDGER_CACHE.pop(str(path), None)
        return []
    stamp = (int(st.st_mtime_ns), int(st.st_size))
    hit = _LEDGER_CACHE.get(str(path))
    if hit is not None and hit[0] == stamp:
        return [dict(r) for r in hit[1]]
    rows: list[Any] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, Mapping):
        rows = list(payload.get("rows") or [])
    elif isinstance(payload, list):
        rows = list(payload)
    kept = [r for r in rows if isinstance(r, Mapping)]
    if len(_LEDGER_CACHE) >= _LEDGER_CACHE_MAX:
        _LEDGER_CACHE.clear()
    _LEDGER_CACHE[str(path)] = (stamp, kept)
    return [dict(r) for r in kept]


def read_ledger_tables(workspace_root: str | Path) -> dict[str, list[Mapping[str, Any]]]:
    """从盘上读三张台账表（`<工作区>/data/<表文件>`）。

    为什么读盘而不是读 store：这一格要在收工门里跑，而收工门有"运行外"的出口
    （`agentflow closing`）—— 那里没有 store，只有工作区目录。
    读不出来（不在盘上 / 坏 JSON）就返回空表，由"代号在表里找不到"报出来。
    同一趟里被调多次时，文件没变就不重解析（见 `_LEDGER_CACHE`）。
    """
    root = Path(workspace_root)
    out: dict[str, list[Mapping[str, Any]]] = {}
    for table in LEDGER_TABLES:
        name = str((S.TABLES.get(table) or {}).get("file") or "")
        out[table] = _ledger_file_rows(root / "data" / name) if name else []
    return out


#: 论文注记里认的引用前缀（`stmt:` / `exp:` / `lit:` / `rel:`）—— 认不认仍由
#: `schema.CITATION_PREFIXES` 说了算，这里只是"我们要看的这几个"的显式收窄。
PAPER_CITATION_PREFIXES: tuple[str, ...] = ("stmt", "exp", "lit", "rel")

#: LaTeX 里「标签名 / 交叉引用名」的那几个命令：`\label{exp:scan}` 里的 `exp:scan` 是
#: 标签名，不是"论文引了 exp:scan 这条实验"。扫引用之前先把这些命令的花括号参数抹掉；
#: `\texttt{exp:000003}` 不抹 —— 那才是正文里写出来的引用。`%` 注释不抹：
#: `% evidence: stmt:000034` 这一行是论文源里真实存在的注记（demo 就是靠它登记命题）。
_TEX_LABEL_COMMAND_RE = re.compile(
    r"\\(?:label|ref|eqref|autoref|cref|Cref|pageref|nameref)\*?\s*\{[^{}]*\}")

#: 内联进正文的那一段附录（`APPENDIX_BEGIN … APPENDIX_END`）：它不是论文正文，
#: 是 `MAPPING.json` 的渲染产物 —— 扫引用时整段抹掉（见 `citation_text_of_tex`）。
_APPENDIX_BLOCK_RE = re.compile(
    re.escape(APPENDIX_BEGIN) + r".*?" + re.escape(APPENDIX_END), re.S)


def citation_text_of_tex(tex: Any) -> str:
    """正文源里该当引用读的那一段。

    抹掉两样东西，理由各一条：

    - 附录块（`APPENDIX_BEGIN … APPENDIX_END`）：它是 `MAPPING.json` 的渲染产物，里面
      既有每行的 `MAPPING-ROW` 注释（`exp:scan` 是 label，不是引用），也有那句
      `exp:NNNNNN` 占位（它说的是"格式"，不是"这一篇引了 NNNNNN"）。不抹掉，
      一张内联附录的表会把自己表里的 label 读成论文引用；
    - `\\label{}` / `\\ref{}` 一类命令的参数：标签名不是引用记号。
    """
    text = _APPENDIX_BLOCK_RE.sub(" ", str(tex or ""))
    return _TEX_LABEL_COMMAND_RE.sub(" ", text)


def read_document_rows(workspace_root: str | Path) -> list[Mapping[str, Any]]:
    """`<工作区>/data/documents.json` 的行（按 `(mtime_ns, size)` 缓存，与三张台账同一处）。

    为什么单开一条：`LEDGER_TABLES` 那三张是 `ledger_id` 能指的表（`stmt` / `exp` / `rel`），
    `documents` 不在其中；但「论文里写了哪些 `stmt:` / `exp:`」只在那张表的 `claims[].citations`
    里。读不出来的处置与 `read_ledger_tables` 相同：返回空表，由"引用的东西表里没有"报出来
    （空表不等于"这篇论文没引任何东西"，那由 `mapping_reading` 的 citations 读数说）。
    """
    name = str((S.TABLES.get("documents") or {}).get("file") or "")
    return _ledger_file_rows(Path(workspace_root) / "data" / name) if name else []


def paper_documents(rows: Iterable[Mapping[str, Any]] | None) -> list[Mapping[str, Any]]:
    """`documents` 里 kind=paper 的那几行（多份修订 / 多篇时全部返回，由调用方并集读）。"""
    return [row for row in (rows or ()) if isinstance(row, Mapping)
            and str(row.get("kind") or "").strip() == "paper"]


def read_literature_rows(workspace_root: str | Path) -> list[Mapping[str, Any]]:
    """`<工作区>/data/literature.json` 的行（`lit:` 引用能不能解析到一条文献行的唯一来源）。"""
    name = str((S.TABLES.get("literature") or {}).get("file") or "")
    return _ledger_file_rows(Path(workspace_root) / "data" / name) if name else []


def read_dependency_rows(workspace_root: str | Path) -> list[Mapping[str, Any]]:
    """`<工作区>/data/dependencies.json` 的行（顺序那一轴的材料：前提 → 使用者）。

    与三张台账同一处读法（`_ledger_file_rows`，按 mtime 缓存）；读不到 ⇒ 空表，由
    `order_reading` 把它读成"这一轴没查成"（`checked=False`），不是"没有依赖"。
    """
    name = str((S.TABLES.get("dependencies") or {}).get("file") or "")
    return _ledger_file_rows(Path(workspace_root) / "data" / name) if name else []


def read_analysis_reports(workspace_root: str | Path) -> list[Mapping[str, Any]]:
    """`<工作区>/data/analysis_reports.json` 的行（C 报告登记的落点）。

    顺序那一轴只认 `kind="proof_chain"` 且 `payload.order` 非空的那几份（C 的
    `proof_path.plan_path` ⇒ `plan_report` ⇒ `analysis_reports`）；读不到 ⇒ 空表，
    由 `order_reading` 读成"没查成"。
    """
    name = str((S.TABLES.get("analysis_reports") or {}).get("file") or "")
    return _ledger_file_rows(Path(workspace_root) / "data" / name) if name else []


def citations_of_documents(rows: Iterable[Mapping[str, Any]] | None) -> list[dict[str, str]]:
    """论文注记里声明的全部引用（`[{"raw", "prefix", "code", "source"}]`，按出现次序去重）。

    只读 `claims[].citations`，不读别的键：`doc.build_document` 要求每条 claim 至少一条
    引用，于是这一格就是"论文自己声明它写了哪些号"的正本。解析走
    `textutil.citation_ref_parts`（`#锚点` 与 `stmt:000034#p2` 都按同一个号算一次）。
    """
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        doc_id = str(row.get("doc_id") or "")
        for claim in row.get("claims") or ():
            if not isinstance(claim, Mapping):
                continue
            for raw in claim.get("citations") or ():
                prefix, code = T.citation_ref_parts(raw)
                if prefix not in PAPER_CITATION_PREFIXES or not code:
                    continue
                if (prefix, code) in seen:
                    continue
                seen.add((prefix, code))
                out.append({"raw": str(raw), "prefix": prefix, "code": code,
                            "source": f"documents#{doc_id}" if doc_id else "documents"})
    return out


def paper_citations(project_root: str | Path, *,
                    workspace_root: str | Path | None = None,
                    tex: str | None = None) -> list[dict[str, str]]:
    """论文写到的全部 `stmt:` / `exp:` / `lit:` / `rel:`（两处取并集，按出现次序去重）。

    两处来源，缺一不可：

    - 正文源：`main.tex`（以及它 `\\input` 进来的分节）的原文，用
      `textutil.find_citations` 扫 —— 论文在正文/注释里真写了什么，这是唯一能回答的地方；
    - 注记：`documents.claims[].citations` —— `doc.build_document` 要求每条 claim
      至少一条引用，于是它记的是"论文自己声明写了哪些号"。

    为什么取并集而不是二选一：只读注记，会漏掉"正文写了、claim 没记"的号（那正是要抓的
    "表里不全"）；只读正文，会漏掉注释掉的/结构化注记里的号（那同样是论文侧的事实）。
    并集只多不少，而"多"的那一侧由 `_paper_citation_problems` 的双向判据管
    （表里没有 ⇒ 红；表里有而两处都没写 ⇒ 红）。
    """
    workspace = Path(workspace_root) if workspace_root is not None else Path(project_root)
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def take(prefix: str, code: str, raw: str, source: str) -> None:
        if prefix not in PAPER_CITATION_PREFIXES or not code:
            return
        if (prefix, code) in seen:
            return
        seen.add((prefix, code))
        out.append({"raw": raw, "prefix": prefix, "code": code, "source": source})

    for item in citations_of_documents(paper_documents(read_document_rows(workspace))):
        take(item["prefix"], item["code"], item["raw"], item["source"])
    text = tex
    if text is None:
        tex_path = package_dir(project_root) / PC.TEX_NAME
        try:
            text = tex_path.read_text(encoding="utf-8") if tex_path.is_file() else ""
        except OSError:
            text = ""
    for got in T.find_citations(citation_text_of_tex(text), prefixes=PAPER_CITATION_PREFIXES):
        take(got["prefix"], got["code"], got["raw"], "paper source")
    return out


def ledger_ids(ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None,
               table: str) -> set[str]:
    """某张台账表里已有的全部代号（按 `schema.TABLES` 的 `id_field` 取列）。"""
    field_name = str((S.TABLES.get(table) or {}).get("id_field") or "")
    ids: set[str] = set()
    if not field_name:
        return ids
    for row in ((ledger or {}).get(table) or ()):
        if isinstance(row, Mapping):
            got = str(row.get(field_name) or "")
            if got:
                ids.add(got)
    return ids


def ledger_row(ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None,
               table: str, row_id: str) -> Mapping[str, Any] | None:
    """按代号在台账里找那一行（找不到 => None）。"""
    field_name = str((S.TABLES.get(table) or {}).get("id_field") or "")
    if not field_name:
        return None
    for row in ((ledger or {}).get(table) or ()):
        if isinstance(row, Mapping) and str(row.get(field_name) or "") == str(row_id):
            return row
    return None


def proof_nos_for_statement(row: Mapping[str, Any] | None) -> list[int]:
    """一条命题名下到底有哪几号证明（`#p1` 恒在；其余来自 `verifications.proof_list`）。"""
    if not isinstance(row, Mapping):
        return []
    return [int(no) for no, _text in V.proof_list(row)]


def resolve_ledger_id(ledger_id: Any,
                      ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None) -> dict[str, Any]:
    """把一行的 `ledger_id` 解析到台账上。

    返回 `{"ledger_id", "ok", "prefix", "table", "row_id", "proof_no", "reason"}`。

    多证明的尾巴由 `proofloc.parse_used_by_checked` 解析（全仓唯一解析点），
    坏尾巴必须红、不许折成 `#p1`：折平之后"这一行指的是第 2 条证明"就静默
    变成了"第 1 条"，而两条证明各自指向不同的文件。
    """
    raw = str(ledger_id or "").strip()
    out: dict[str, Any] = {"ledger_id": raw, "ok": False, "prefix": "", "table": "",
                           "row_id": "", "proof_no": PL.DEFAULT_PROOF_NO, "reason": ""}
    if not raw:
        out["reason"] = "`ledger_id` 是空的（它必须指到台账上的某一行）"
        return out
    prefix, sep, rest = raw.partition(":")
    if not sep or not prefix or not rest:
        out["reason"] = (f"`ledger_id` 的写法不对：{raw!r} —— 要 `stmt:000004` 这种"
                         f"（前缀 {list(LEDGER_PREFIXES)} 之一 + 冒号 + 代号）")
        return out
    table = S.citation_prefix_table(prefix)
    if table not in LEDGER_TABLES:
        out["reason"] = (f"`ledger_id` 的前缀 {prefix!r} 不认：只认 "
                         f"{[p + ':' for p in LEDGER_PREFIXES]}")
        return out
    out["prefix"], out["table"] = prefix, table
    row_id, proof_no = rest, PL.DEFAULT_PROOF_NO
    if "#" in rest:
        if table != "statements":
            out["reason"] = (f"`ledger_id` 带了证明号尾巴（{raw!r}），但证明号只对 "
                             "`stmt:` 有意义 —— `exp:` / `rel:` 没有多证明这一说")
            return out
        row_id, proof_no, problem = PL.parse_used_by_checked(rest)
        if problem:
            out["reason"] = (f"`ledger_id` 的证明号尾巴读不懂：{problem!r} "
                             "（坏尾巴不折成 #p1，也不猜它是第几条）")
            return out
    if not _DIGITS_RE.match(str(row_id)):
        out["reason"] = f"`ledger_id` 的代号不是纯数字：{str(row_id)!r}（收到 {raw!r}）"
        return out
    known = ledger_ids(ledger, table)
    if str(row_id) not in known:
        out["reason"] = (f"`{prefix}:{row_id}` 在 `{table}` 表里没有这一行"
                         f"（该表盘上共 {len(known)} 行）")
        return out
    out["row_id"], out["proof_no"], out["ok"] = str(row_id), int(proof_no), True
    return out


def ledger_kind_cell(ledger_row: Mapping[str, Any] | None) -> str:
    """这一行在台账里叫什么（`ledger_kind` 那一格）。

    三态：台账行在、且它写着 `kind` ⇒ 写那个词；台账行不在、或者那一行的 `kind`
    是空的 ⇒ `未读到`。空着的 `kind` 是"台账没回答"，不是"不是定理"。
    """
    if not isinstance(ledger_row, Mapping):
        return LEDGER_CELL_UNREADABLE
    kind = str(ledger_row.get("kind") or "").strip()
    return kind or LEDGER_CELL_UNREADABLE


def _reviewed_by_of(ledger_row: Mapping[str, Any] | None) -> dict[str, Any]:
    """`bits.evidence.reviewed_by` 那一格（V 最近那一签的凭据：含判决原话）。

    只认 `evidencebits` 与写侧共用的那一格口袋；读不到就返回空表（调用方据此写
    `未读到`，不许折成"没签"）。
    """
    if not isinstance(ledger_row, Mapping):
        return {}
    bits = ledger_row.get("bits") if isinstance(ledger_row.get("bits"), Mapping) else ledger_row
    ev = bits.get("evidence") if isinstance(bits.get("evidence"), Mapping) else {}
    by = ev.get("reviewed_by")
    return dict(by) if isinstance(by, Mapping) else {}


def _proof_body_sha_of(ledger_row: Mapping[str, Any], proof_no: int) -> str:
    """这一号证明现在的正文 sha（与签、`reviewed_sha_by_proof` 同一把尺）。

    三态：这一号没有正文（清单里没有它 / 正文为空）⇒ 空串 = 判不了（不拿空串去比，
    否则"取不到正文"会被读成"签的是旧版"）。尺只有一处：`verifications._sign_sha`
    ⇒ `proofregistry.proof_sha`，与写侧 `_apply_review_to_bits` 落 `reviewed_sha_by_proof`
    用的是同一把。
    """
    try:
        text = str(V.proof_text_of(dict(ledger_row), int(proof_no)) or "")
    except Exception:  # noqa: BLE001 —— 正文取不到 = 判不了，不编一个 sha
        return ""
    if not text.strip():
        return ""
    return str(V._sign_sha(text) or "")


def reviewed_ledger_state(workspace_root: str | Path, statement_id: Any) -> str:
    """这份命题的审校台账（`verifications/<命题号>.jsonl`）在不在、读不读得出。

    返回 `REVIEW_LEDGER_STATES` 之一。判据只有一处：`jsonlfile.read_jsonl_state`
    的四态 —— `absent` ⇒ 不在（`absent`）；`unreadable`（读异常 / 权限 / 不是 UTF-8）
    或有任何坏行（`problems` 非空）⇒ 读不出（`unreadable`）；其余（`ok` / `empty`，
    即文件在、行都读得出来）⇒ 在（`present`）。

    为什么"文件在、只是空"算「在」：空文件是"送审过、还没落下结论"的一种（写侧先建
    文件再追加），它不是"从没送审"，也不是"读不出"。三件事三种处置。

    为什么在这里读、而不是在 `reviewed_cell` 里读：渲染函数是纯函数（拿行出字），
    一次渲染里每一行都要问这一格，写盘的东西只该在调用点读一遍（见
    `_review_ledger_states`）。
    """
    sid = str(statement_id or "").strip()
    if not sid:
        return REVIEW_LEDGER_UNREADABLE
    try:
        path = V.verification_ledger_path(workspace_root, sid)
    except Exception:  # noqa: BLE001 - 命题号坏到连路径都拼不出 ⇒ 这一格没查成
        return REVIEW_LEDGER_UNREADABLE
    _rows, problems, state = JF.read_jsonl_state(path)
    if state == "absent":
        return REVIEW_LEDGER_ABSENT
    if state == "unreadable" or problems:
        return REVIEW_LEDGER_UNREADABLE
    return REVIEW_LEDGER_PRESENT


def _review_ledger_states(workspace_root: str | Path, rows: Iterable[Row],
                          ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None
                          ) -> dict[str, str]:
    """一次读出这批论文行各自那份审校台账的三态（按命题号归并，同一份只读一遍）。

    只有 `stmt:` 开头的行有这份台账：`exp:` / `rel:` 不在 V 的审校链上，查询时
    由 `_review_ledger_of` 落 `unreadable`（那一格没查成，不是"从没送审"）。
    """
    out: dict[str, str] = {}
    for row in rows:
        resolved = resolve_ledger_id(row.ledger_id, ledger)
        if not resolved["ok"] or str(resolved["table"]) != "statements":
            continue
        sid = str(resolved["row_id"])
        if sid not in out:
            out[sid] = reviewed_ledger_state(workspace_root, sid)
    return out


def _review_ledger_of(resolved: Mapping[str, Any], states: Mapping[str, str]) -> str:
    """一条论文行对应哪一档台账读数（非 statements 表 ⇒ `unreadable`，不冒充「未审」）。"""
    if not resolved.get("ok") or str(resolved.get("table")) != "statements":
        return REVIEW_LEDGER_UNREADABLE
    return str(states.get(str(resolved.get("row_id")), REVIEW_LEDGER_UNREADABLE))


def reviewed_cell(ledger_row: Mapping[str, Any] | None, proof_no: Any, *,
                  review_ledger: str) -> str:
    """V 签没签 + 判决原话（`reviewed` 那一格的四档）。

    `review_ledger` 是这条命题那份审校台账 `verifications/<命题号>.jsonl` 的三态
    （`REVIEW_LEDGER_STATES`），由调用点现读一遍传进来 —— 渲染函数不自己读盘。

    四档（「应该分：已签/未通过/未审/未读到」）：

    - `已签（判决：<原话>）`：逐份表里这一份为真（`reviewed_by_proof[证明号] is True`），
      而且那一签盖的就是这一份正文（`reviewed_sha_by_proof[证明号]` 与正文现算的
      sha 相同；老行没有那张表 ⇒ 判不了，不拿它否决）。原话那一格读不到、或者它
      记的是另一份证明的签 ⇒ `已签（判决：未读到）`；
    - `未通过`：台账在，而这一份的键不存在或为假（审过，没拿到签 —— 含"判过有毛病"）；
    - `未审`：台账不在（从没送审）；
    - `未读到`：台账在但读不出 / 这一格没查成 / statements 行读不到 / 证明号读不出，
      以及两种"表上没有这一号、可是那一签明显记在别的号上"的形态：
      ① 这一份正文的 sha 记在 `reviewed_sha_by_proof` 的别的号上（B 收录时按
      canonical 号落的老账 / 号错位）；② 这一号键为真而它记的 sha 不是现在这一份
      （签的是旧版，这一版没被读过）。

    判「审过没审过」只认台账在不在：写侧只在真签时建 `reviewed_by_proof` 的键，
    按"没键"读会把"审过、从没签"读成"从没审过"（这一个反向形态本轮一并治掉）。

    ## 为什么"没这一号"有时是「未读到」而不是「未通过」

    现场形态：同一命题的两份证明都已签，而 `reviewed_by_proof` 只有 `{1: True}`
    （B 收录第 2 份时用了 canonical 号，见 `register_statement._ingest_apply_evidence`）。
    这时表上给第 2 条路径写「未通过」= 替 V 下了一个假结论（V 根本没判过它）。
    判据要能分辨"读不到"与"判过没通过"：只有这一份确实被判过才落「未通过」。
    所以：这一份正文的 sha 在 sha 表里记在别的号上 ⇒ 那一签盖的就是这份正文、
    只是号记错了 ⇒ 落「未读到」；否则（正文 sha 哪里都没记）⇒ 「未通过」。
    """
    if not isinstance(ledger_row, Mapping):
        return LEDGER_CELL_UNREADABLE
    no = _int_or_none(proof_no)
    if no is None or str(review_ledger) not in REVIEW_LEDGER_STATES:
        return LEDGER_CELL_UNREADABLE
    per = EB.reviewed_by_proof(ledger_row)
    sha_by = EB.reviewed_sha_by_proof(ledger_row)
    body_sha = _proof_body_sha_of(ledger_row, int(no))
    if per.get(int(no)) is True:
        by = _reviewed_by_of(ledger_row)
        told = str(by.get("verdict") or "").strip()
        # `reviewed_by` 只有一格（最近那一签）。它记的是哪一份，就只给那一份背书：
        # 多证明时拿 #p1 的判决原话替 #p2 说话，等于让一份签替另一份签作证。
        said = _int_or_none(by.get("proof_no"))
        if said is not None and int(said) != int(no):
            told = ""
        # 这一号签过的"是不是现在这一份正文"：sha 表记了而记的不是它 ⇒ 签的是旧版
        # ⇒ 这一版没有被判过 ⇒ 未读到（不折成「已签」，也不折成「未通过」）。
        pinned = str(sha_by.get(int(no)) or "").strip().lower()
        if body_sha and pinned and pinned != body_sha:
            return LEDGER_CELL_UNREADABLE
        return REVIEWED_SIGNED_TEMPLATE.format(verdict=told or LEDGER_CELL_UNREADABLE)
    if str(review_ledger) == REVIEW_LEDGER_UNREADABLE:
        return LEDGER_CELL_UNREADABLE
    if str(review_ledger) == REVIEW_LEDGER_ABSENT:
        return REVIEWED_UNREVIEWED
    # ---- 「表上没有这一号」的两种读法（不许一律折成「未通过」） ----------------
    if body_sha:
        # ① 正文 sha 记在别的号上（B 收录时按 canonical 号落的老账）⇒ 那一签盖的
        #    就是这一份正文 ⇒ 号错位，不是 V 判过它 ⇒ 未读到。
        if any(str(v or "").strip().lower() == body_sha
               for k, v in sha_by.items() if int(k) != int(no)):
            return LEDGER_CELL_UNREADABLE
        # ② 汇总那一格（`reviewed_by`）记的 sha 是这一份正文、而号是别的号 ⇒ 同上。
        by = _reviewed_by_of(ledger_row)
        said = _int_or_none(by.get("proof_no"))
        said_sha = str(by.get("proof_sha256") or "").strip().lower()
        if (said is not None and int(said) != int(no)
                and said_sha and said_sha == body_sha):
            return LEDGER_CELL_UNREADABLE
    return REVIEWED_NOT_PASSED


def ledger_cells(ledger_row: Mapping[str, Any] | None, proof_no: Any, *,
                 review_ledger: str, table: str = "statements") -> dict[str, str]:
    """一行的台账格（ledger_kind / reviewed / optimized / proof_source）。

    `table` 是这一行的 `ledger_id` 解析到哪张台账表：`experiments` 那几行没有 `kind`、
    也不走 V 的审校链 ⇒ 四格统一记 :data:`EXPERIMENT_LEDGER_CELL`（"不适用"），
    不折成「未读到」（那说的是"这一格没查成"，而实验行这一格本来就没有）。
    """
    if str(table or "") == "experiments":
        return {LEDGER_KIND_FIELD: EXPERIMENT_LEDGER_CELL,
                REVIEWED_FIELD: EXPERIMENT_LEDGER_CELL,
                OPTIMIZED_FIELD: EXPERIMENT_LEDGER_CELL,
                PROOF_SOURCE_FIELD: EXPERIMENT_LEDGER_CELL}
    return {LEDGER_KIND_FIELD: ledger_kind_cell(ledger_row),
            REVIEWED_FIELD: reviewed_cell(ledger_row, proof_no,
                                          review_ledger=review_ledger),
            OPTIMIZED_FIELD: optimized_cell(ledger_row, proof_no),
            PROOF_SOURCE_FIELD: ledger_source_cell(ledger_row)}


def ledger_source_cell(ledger_row: Mapping[str, Any] | None) -> str:
    """这一份证明的来源那一格：own / citation（读不到 ⇒ 空串，渲染印「未记录」）。

    只读 `bits.evidence.proof_source`（`evidencebits.bits_of` 写的唯一一处）：
    不拿 `origin` 猜 —— origin="own_result" 里还混着 E 的穷举证明与 B 自写的正文，
    "来源"这一格回答的是"这份证明是谁那条路交上来的"，不是"命题是谁的"。
    """
    if not isinstance(ledger_row, Mapping):
        return ""
    bits = ledger_row.get("bits")
    if not isinstance(bits, Mapping):
        return ""
    return str(dict(bits.get("evidence") or {}).get("proof_source") or "")


def fill_ledger_cells(ledger_root: str | Path,
                      rows: Iterable[Row], *,
                      ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None = None
                      ) -> list[Row]:
    """按台账把每一行的两格现读现填（D-69 的唯一填充口；纯读、不改盘）。

    为什么要填而不是让 G 写：这两格说的是台账那一行的事实（`kind`）与 V 的读数，
    G 只能抄。抄错一位就是"表与台账对不上"而没有东西会报错 —— 所以写侧现读现填，
    G 手填的值会被这一次现读盖掉。

    `ledger_root` 是"`data/` 那一层在谁下面"，也就是工作区根（与
    `mapping_reading(workspace_root=…)` 同一处口径：台账在 `<工作区>/data/<表文件>`，
    审校台账在 `<工作区>/verifications/<命题号>.jsonl`）。论文包可能挂在项目子目录下，
    所以它不一定是项目根 —— 调用方给哪个就按哪个读。

    三态：`ledger_id` 解析不到、或台账里没有那一行 ⇒ 两格都写 `未读到`（这一格
    没查成，不是"未审"、也不是"不是定理"）。`ledger=None` 时按 `ledger_root` 读盘。

    凭据那一格（`lean_file`，语义是「机器核验凭据（Lean 程序 / 数值证明程序）」）不在
    这里填：它填的是提交方声称的凭据（类别与通道一致与否由 `_lean_problems` 判），而这里
    只填台账自己的事实（`ledger_kind` / `reviewed` / `optimized` / `proof_source`）——
    凭证是"声称"，签与审是"事实"，两件事不混在一个填充口里。

    审校台账那份三态在开头按命题号归并读一遍（`_review_ledger_states`），同一份
    只读一次：一行一次 `open` 会让一张长表的填充退化成 N 次读盘。
    """
    known = ledger if ledger is not None else read_ledger_tables(ledger_root)
    items = list(rows)
    states = _review_ledger_states(ledger_root, items, known)
    out: list[Row] = []
    for row in items:
        resolved = resolve_ledger_id(row.ledger_id, known)
        target = (ledger_row(known, str(resolved["table"]), str(resolved["row_id"]))
                  if resolved["ok"] else None)
        cells = ledger_cells(target, row.proof_no,
                             review_ledger=_review_ledger_of(resolved, states),
                             table=str(resolved["table"]) if resolved["ok"] else "statements")
        out.append(replace(row, ledger_kind=cells[LEDGER_KIND_FIELD],
                           reviewed=cells[REVIEWED_FIELD],
                           optimized=cells[OPTIMIZED_FIELD],
                           proof_source=cells[PROOF_SOURCE_FIELD]))
    return out


#: 自有证明行的索引四格由谁填：写侧（`fill_evidence_cells`）现读现填，G 手填的值会被盖掉。
#:
#: 为什么填在写侧而不是让 G 抄：这四格说的是"台账那一行指到哪一份稿 / V 签的是哪一份正文"，
#: 是台账自己的事实（`statements.manuscripts[证明号]` 与 `bits.evidence.reviewed_sha_by_proof`），
#: G 只能抄。抄错一位（例如把稿的文件字节 sha 当成正文 sha）没有任何东西会报错 —— 而
#: `temp/realrun-sylow/read_package.py` 第 ⑦ 项真读到的正是这个形态：四行"已签"的自有证明
#: 全是空 `evidence_path`，表在盘上"指不到"任何一份正文。
#:
#: 这句话同时是教法（`doc.mapping_cells` 的工具面摘要与逐格 `sources` 都引这一份）：
#: 修前工具面对非数值定理行说"索引四格只对数值实验定理那一行判 ⇒ 这一行不适用"，
#: 写侧却已经现读现填 —— 弟子面与契约差一句，G 会以为自己该手填。
OWN_PROOF_CELLS_NOTE = "自有证明行的索引四格由框架现读现填，你别手填；填了也会被盖"

#: 拿不到自有已签证明的那一档（citation / 未签 / 例子 / 实验）怎么读空串：不是"框架会填"，
#: 是这一档没有"正文在哪"这一问；空着绝不冒充「已签」。带"不适用"三个字是刻意的 ——
#: `doc.mapping_cells` 的 `returns` 口径与判据按这三个字认「这一档没有这一格」。
NOT_OWN_PROOF_CELLS_NOTE = ("这一行不是「自有 + 已签 + 定理类」的证明 ⇒ 索引四格不适用"
                            "（空着不冒充已签）")
def proof_evidence_reading(ledger_row: Mapping[str, Any] | None, proof_no: Any,
                           workspace_root: str | Path, *, reviewed: str = "") -> dict[str, Any]:
    """这一号证明的「稿 / 签」两态读数（纯读、不猜；填充、G 表、门共用这一份）。

    业主 2026-11-26 的口径（本函数只回答这两问）：

    1. 稿：台账里这条命题有没有指向一份证明稿（`statements.manuscripts[证明号]`），
       那份稿在不在盘上；
    2. 签：这一份有没有 V 的签（按台账的 `reviewed` 四档判）。

    稿号与命题号不同轴：`b-proof-000000.md` 这类名字是 B 自己的稿号，与命题号
    各自独立编号 —— "这份稿装的是谁那条命题的证明"只能从台账的
    `statements.manuscripts` 映射回答，不从文件名 / 正文内容 / 字节 sha 推。
    B 的二阶段还会洗证明正文并重拿 V 签（业主既定流程）⇒ 正文变化是合法的，
    所以 `file_body_sha256` / `proof_body_sha256` / `file_sha256` 在这里只是信息读数
    （`sha_drift` 说明"盘上这一版的正文与台账这一版不同"，不是判据）。

    签的判法复用既有那一处：传了 `reviewed`（`fill_ledger_cells` 已经读过的那一格）就用它；
    没传时按 `bits.evidence.reviewed_by_proof[证明号] is True` 且 V 记的正文 sha 与台账
    这一号正文相同（与 `reviewed_cell` 同一档，不是第二套口径）。

    三态：`checked=False`（台账行 / 稿记录读不出来）不是"没有稿"，调用方按"没查成"处置。
    返回 `{checked, recorded, rel, recorded_sha, recorded_sha_known, path_state,
    file_sha256, file_body_sha256, proof_body_sha256, sha_drift, reviewed, signed,
    signed_sha, why}`。
    """
    out: dict[str, Any] = {
        "checked": False, "recorded": False, "rel": "", "recorded_sha": "",
        "recorded_sha_known": False, "path_state": "outside", "file_sha256": "",
        "file_body_sha256": "", "proof_body_sha256": "", "sha_drift": False,
        "reviewed": str(reviewed or ""), "signed": False, "signed_sha": "", "why": "",
    }
    if not isinstance(ledger_row, Mapping):
        out["why"] = "台账里没有这一行 ⇒ 稿与签两态都判不了"
        return out
    no = _int_or_none(proof_no)
    if no is None:
        out["why"] = f"证明号读不出（收到 {proof_no!r}）⇒ 稿与签两态都判不了"
        return out
    from . import manuscriptpaths as MPP   # 惰性：只在这一格用到

    root = Path(workspace_root)
    rec = MPP.recorded_manuscript(ledger_row, int(no), root)
    out["checked"] = bool(rec.get("checked"))
    out.update(recorded=bool(rec.get("recorded")), rel=str(rec.get("path") or ""),
               recorded_sha=str(rec.get("sha256") or ""),
               recorded_sha_known=bool(rec.get("sha_known")),
               path_state=str(rec.get("path_state") or "outside"),
               file_sha256=str(rec.get("file_sha256") or ""),
               proof_body_sha256=str(_proof_body_sha_of(ledger_row, int(no)) or "").lower(),
               why=str(rec.get("why") or ""))
    body = out["proof_body_sha256"]
    signed_sha = str(EB.reviewed_sha_by_proof(ledger_row).get(int(no)) or "").strip().lower()
    out["signed_sha"] = signed_sha
    if str(reviewed or "").strip():
        out["signed"] = _split_reviewed(reviewed)[0] == "signed"
    else:
        out["signed"] = bool(EB.reviewed_by_proof(ledger_row).get(int(no)) is True
                             and signed_sha and body and signed_sha == body)
    if out["rel"] and out["path_state"] == "present":
        try:
            text = (root / out["rel"]).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            out.update(path_state="unreadable",
                       why=f"{out['rel']} 读不出来（{type(exc).__name__}: {exc}）")
        else:
            out["file_body_sha256"] = str(V._sign_sha(text) or "").strip().lower()
            out["sha_drift"] = bool(body and out["file_body_sha256"]
                                    and body != out["file_body_sha256"])
    return out


def evidence_cells_for_row(row: Row,
                           ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None,
                           workspace_root: str | Path) -> dict[str, Any]:
    """这一行该填的证据格（空表 = 不填 / 不适用；纯读，不猜）。

    填哪一档（2026-11-26 BEARINGDEF：两态、按承重判、与来源无关）：

    - 只填承重行：`is_load_bearing_row(row)`（正文里印成定理类环境的行）；
      `origin=external_lit` / `proof_source=citation` / 没 V 签 都不再让它空掉
      —— 这两个字段回答的是"这行是不是自己的证明"，不是"它有没有一份稿"；
    - `evidence_kind` = `proof`；`evidence_path` = 台账记的那一份稿
      （`statements.manuscripts[证明号]`，读口 `manuscriptpaths.recorded_manuscript`）；
    - `evidence_sha256` = 这一号证明正文的 sha（`_proof_body_sha_of`；与 V 签同一
      把尺）。稿还没签也填 —— 它说的是"这份稿该装哪一段正文"，不是"签过了"；
    - `evidence_file_sha256` = 写表那一刻盘上那份稿的字节 sha（信息读数：
      洗稿合法，这一格不承担判据；见 `PROOF_FILE_SHA_FIELD`）；
    - `v_signature` = `{"verdict": "成立", "sha256": <正文 sha>}` 只在真签上时填。

    不填的档（各有理由，空着不等于"已签"）：
    - 非承重行（例子 / 实验 / 被引实验行）：不是"被证明的命题"，没有"正文在哪"这一问；
    - 数值 / 形式化通道的行：正文是 E 的报告或 `.lean`，索引四格另有口径
      （`mapping_cells` 与 `_lean_problems` 那一支），这里不替它改指一份稿；
    - 台账读不到 / 台账没记这一号稿：`{}`（由门报 `mapping_load_bearing_evidence_missing`，
      不在这里编一个路径）。
    """
    if not is_load_bearing_row(row):
        return {}
    resolved = resolve_ledger_id(row.ledger_id, ledger)
    if not resolved["ok"] or str(resolved.get("table") or "") != "statements":
        return {}
    target = ledger_row(ledger, "statements", str(resolved["row_id"]))
    if not isinstance(target, Mapping):
        return {}
    no = _int_or_none(row.proof_no)
    if no is None or int(no) < 1:
        return {}
    try:
        if is_numeric_row(row, ledger):
            return {}
    except Exception:  # noqa: BLE001 —— 通道读不出来 ⇒ 不填（不编一个"像是"的值）
        return {}
    reading = proof_evidence_reading(target, int(no), workspace_root,
                                     reviewed=row.reviewed)
    if not reading.get("checked"):
        return {}
    rel = str(reading.get("rel") or "")
    if not rel:
        return {}
    cells: dict[str, Any] = {NP.INDEX_KIND_FIELD: NP.INDEX_KIND_PROOF,
                             NP.INDEX_PATH_FIELD: rel}
    body = str(reading.get("proof_body_sha256") or "")
    if body:
        cells[NP.INDEX_SHA_FIELD] = body
    if reading.get("file_sha256"):
        cells[PROOF_FILE_SHA_FIELD] = str(reading["file_sha256"])
    if reading.get("signed"):
        cells[NP.INDEX_SIGN_FIELD] = {
            "verdict": NP.THIRD_PARTY_VERDICT_OK,
            "sha256": str(reading.get("signed_sha") or body),
        }
    return cells


def fill_evidence_cells(ledger_root: str | Path,
                        rows: Iterable[Row], *,
                        ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None = None
                        ) -> list[Row]:
    """把承重行的证据格现读现填（纯读、不改盘；`write_mapping` 的唯一填充口）。

    与 `fill_ledger_cells` 同一条纪律：这些格说的是台账的事实，不是提交方的声称，
    所以 G 手填的值会被这一次现读盖掉。三态：拿不到就保持原样（不填一个像样的空值）。

    2026-11-26 起"稿"与"签"拆成两态：台账记了稿就填 `evidence_path` /
    `evidence_sha256` / `evidence_file_sha256`，没签也填；`v_signature` 只在真签上
    时出现。旧行为是"没签 ⇒ 整行空掉"，于是真机 `thm:erdos-rado` / `prop:block`
    连"稿在哪"都看不见（见 `is_load_bearing_row` 的注释）。

    反真空：判据 `tests/test_mapping_evidence_cells.py` 把本函数打桩成恒等 ⇒ 自有证明行
    的四格必须回到空串（"绿"真的靠这一处填充，而不是靠构造里恰好带着值）。
    """
    known = ledger if ledger is not None else read_ledger_tables(ledger_root)
    root = Path(ledger_root)
    out: list[Row] = []
    for row in rows:
        try:
            cells = evidence_cells_for_row(row, known, root)
        except Exception:  # noqa: BLE001 —— 填不出来就空着；写表不许被这一格拦崩
            cells = {}
        if not cells:
            out.append(row)
            continue
        out.append(replace(row,
                           evidence_kind=str(cells[NP.INDEX_KIND_FIELD]),
                           evidence_path=str(cells[NP.INDEX_PATH_FIELD]),
                           evidence_sha256=str(cells.get(NP.INDEX_SHA_FIELD) or ""),
                           evidence_file_sha256=str(cells.get(PROOF_FILE_SHA_FIELD) or ""),
                           v_signature=(dict(cells[NP.INDEX_SIGN_FIELD])
                                        if isinstance(cells.get(NP.INDEX_SIGN_FIELD), Mapping)
                                        else None)))
    return out


def _params_summary(params: Any, observations: Any) -> str:
    """实验行的参数摘要（三态，不编造）。

    - `params` 非空 ⇒ 它的规范化 JSON（键排序，重跑两次逐字相同）；
    - `params` 空 ⇒ `未记录（台账 params 为空）`，并把 `observations.strategy` 那一句
      附在后面：那是台账里真实存在的"这一条按什么策略跑的"，不是替 `params` 编一个值；
    - 连 strategy 都没有 ⇒ 只剩"未记录"。
    """
    if isinstance(params, Mapping) and params:
        return json.dumps(dict(params), ensure_ascii=False, sort_keys=True, default=str)
    strategy = ""
    if isinstance(observations, Mapping):
        strategy = " ".join(str(observations.get("strategy") or "").split())
    if strategy:
        return f"{EXPERIMENT_PARAMS_EMPTY}；strategy：{strategy}"
    return EXPERIMENT_PARAMS_EMPTY


def _repo_rel_state(workspace_root: str | Path, rel: Any) -> dict[str, Any]:
    """仓库根相对的一条路径在盘上的状态（`present` / `missing` / `empty` / `outside`）。

    解析器只有一处：`numericproof._resolve_under`（索引四格解析用的同一把尺），这里
    只补"存在 / 非空"两档，不另写一套路径规则（绝对路径、`..`、越界都按它拒）。
    """
    raw = NP.norm_rel(rel)
    out: dict[str, Any] = {"state": "outside", "file": raw, "abs": "", "size": 0, "reason": ""}
    target, why = NP._resolve_under(workspace_root, raw)
    if target is None:
        out["reason"] = why
        return out
    out["abs"] = str(target)
    if not target.is_file():
        out["state"] = "missing"
        out["reason"] = f"盘上没有这份文件：{raw}"
        return out
    try:
        size = int(target.stat().st_size)
    except OSError as exc:
        out["state"] = "missing"
        out["reason"] = f"{raw} 读不出来（{type(exc).__name__}: {exc}）"
        return out
    out["size"] = size
    if size <= 0:
        out["state"] = "empty"
        out["reason"] = f"这份文件是空的：{raw}（空文件不等于「这一条跑过」）"
        return out
    out["state"] = "present"
    return out


def experiment_cells_for_row(experiment: Mapping[str, Any] | None) -> dict[str, Any]:
    """一条被引实验行该填的格（空表 = 台账里取不到行；纯读、不猜）。

    每一格的来源都只有一处，全部是 `experiments` 那一行的原值（不拼字符串、不改写）：

    | 格 | 台账列 |
    |---|---|
    | `file` | `code_path`（程序，仓库根相对；与数值定理行 `file` 同一坐标系） |
    | `experiment_logs` | `artifact_paths`（原样逐份列，不取第一份了事） |
    | `experiment_code_hash` | `code_hash`（`verify_tools.code_hash` = sha256 前 16 位） |
    | `experiment_result` | `result`（supports / refutes / inconclusive） |
    | `experiment_negation_kind` | `negation_kind` |
    | `experiment_params` | `params`（空则"未记录 + strategy"，见 `_params_summary`） |
    | `experiment_exit_code` | `exit_code` |
    """
    if not isinstance(experiment, Mapping):
        return {}
    code = NP.norm_rel(experiment.get("code_path"))
    if not code:
        return {}
    logs: list[str] = []
    for raw in experiment.get("artifact_paths") or ():
        rel = NP.norm_rel(raw)
        if rel and rel not in logs:
            logs.append(rel)
    exit_code = experiment.get("exit_code")
    return {
        "file": code,
        EXPERIMENT_LOGS_FIELD: tuple(logs),
        EXPERIMENT_CODE_HASH_FIELD: str(experiment.get("code_hash") or "").strip(),
        EXPERIMENT_RESULT_FIELD: str(experiment.get("result") or "").strip(),
        EXPERIMENT_NEGATION_FIELD: str(experiment.get("negation_kind") or "").strip(),
        EXPERIMENT_PARAMS_FIELD: _params_summary(experiment.get("params"),
                                                 experiment.get("observations")),
        EXPERIMENT_EXIT_FIELD: (int(exit_code) if isinstance(exit_code, int)
                                and not isinstance(exit_code, bool) else None),
    }


def fill_experiment_cells(ledger_root: str | Path,
                          rows: Iterable[Row], *,
                          ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None = None
                          ) -> list[Row]:
    """把被引实验行的那几格按台账现读现填（纯读、不改盘；`write_mapping` 的第二填充口）。

    只填「被引、未印成环境」的行（`env_no == EXPERIMENT_ENV_NO`）：真印成 `experiment`
    环境的行，`file` 是论文包内那一份正文（由 G 给、由 `_row_checks` 按包内判），
    这里不替它改指程序。三态：台账里没有这一行 / 它没有 `code_path` ⇒ 保持空，
    由读侧当缺口报（空着绝不被读成「这一条有程序」）。
    """
    known = ledger if ledger is not None else read_ledger_tables(ledger_root)
    out: list[Row] = []
    for row in rows:
        if not is_cited_only_row(row):
            out.append(row)
            continue
        resolved = resolve_ledger_id(row.ledger_id, known)
        if not resolved["ok"] or str(resolved.get("table") or "") != "experiments":
            out.append(row)
            continue
        cells = experiment_cells_for_row(ledger_row(known, "experiments",
                                                    str(resolved["row_id"])))
        if not cells:
            out.append(row)
            continue
        out.append(replace(row,
                           file=str(cells["file"]),
                           experiment_logs=tuple(cells[EXPERIMENT_LOGS_FIELD]),
                           experiment_code_hash=str(cells[EXPERIMENT_CODE_HASH_FIELD]),
                           experiment_result=str(cells[EXPERIMENT_RESULT_FIELD]),
                           experiment_negation_kind=str(cells[EXPERIMENT_NEGATION_FIELD]),
                           experiment_params=str(cells[EXPERIMENT_PARAMS_FIELD]),
                           experiment_exit_code=cells[EXPERIMENT_EXIT_FIELD]))
    return out


def synthesize_experiment_rows(project_root: str | Path, rows: Iterable[Row], *,
                               workspace_root: str | Path | None = None,
                               tex: str | None = None) -> list[Row]:
    """把论文写到、而表里还没有的 `exp:NNNNNN` 补成行（幂等；只有 `write_package` 调它）。

    业主 2026-11-25：「论文包里的 MAPPING 信息还是不全，需要从命题台账读到论文中写的
    stmt 的证明稿的具体文件名、experiment 的具体文件名。」这条决定实验行由框架从
    论文注记 + 台账现读现造，G 不写、也不许手抄：`exp:` 号只可能来自论文自己写的引用，
    文件只可能来自 `experiments` 那一行。

    幂等：`present` 按实验号去重，同一批 `rows` 连跑两次得到的行集合与字段逐字相同；
    已经由 G（或上一次输出）带进来的实验行不重复造，也不改它的 `env_no`。
    台账里没有那条实验的引用不造行（没有文件可指的"行"只会是空壳）；那一档由
    `_paper_citation_problems` 报"论文引了、台账里没有这条实验"。
    """
    workspace = Path(workspace_root) if workspace_root is not None else Path(project_root)
    items = list(rows)
    # 先问一句"这一趟有论文登记行吗"：`doc.build_document` 是成文四步的第 ⓪ 步，
    # 所以真论文一定有 `documents(kind="paper")` 那一行。没有它时（判据夹具 / 半成品）
    # 不合成：此时"论文引了哪些 exp"只有正文源一处可读，合成出来的行会把夹具的
    # 行数悄悄改掉（`test_mapping_three_known_gaps` 的 `gate["rows"] == 1` 就是这一档）。
    # 有登记行时按并集造（注记 ∪ 正文），两处都是论文自己写的。
    if not paper_documents(read_document_rows(workspace)):
        return items
    present = {experiment_id_of_row(row) for row in items if is_experiment_row(row)}
    known = read_ledger_tables(workspace)
    known_ids = {str(row.get("experiment_id") or "").strip()
                 for row in known.get("experiments") or () if isinstance(row, Mapping)}
    extra: list[Row] = []
    for item in paper_citations(project_root, workspace_root=workspace, tex=tex):
        if item["prefix"] != "exp":
            continue
        eid = str(item["code"]).strip()
        if not eid or eid in present or eid not in known_ids:
            continue
        target = ledger_row(known, "experiments", eid)
        cells = experiment_cells_for_row(target)
        if not cells:
            # 台账那一行没有 `code_path` ⇒ 这一行即使造出来也没有 `file` 可填，
            # 而 `file` 是每行必填 —— 造出来只会让自己的表读不回来（parse 阶段
            # 报"缺必填字段"并把 md 一起拖成 drift）。这一档留给读侧报
            # "论文引了 exp:X、表里没有行"，并点明台账没有程序。
            continue
        present.add(eid)
        extra.append(Row(kind="experiment", label=f"{EXPERIMENT_ID_PREFIX}{eid}",
                         env_no=EXPERIMENT_ENV_NO,
                         ledger_id=f"{EXPERIMENT_ID_PREFIX}{eid}", proof_no=1, file=""))
    return items + extra


def file_state(package_root: str | Path, rel: Any) -> dict[str, Any]:
    """`file` 那一栏在论文包里是什么状态。

    五态：`present`（在、非空）· `empty`（在、0 字节）·
    `missing`（路径不存在）· `directory`（路径在、但它是个目录）·
    `outside`（不是包内相对路径，或指到了论文包之外）。

    `empty` 与 `missing` 必须分开：前者是"文件还没写内容"，后者是"根本没有这个文件"。
    折成一个读数，就会把"指错地方"读成"写得短"。
    """
    raw = str(rel or "").strip()
    out: dict[str, Any] = {"file": raw, "state": "missing", "abs": "", "reason": ""}
    if not raw:
        out["reason"] = "`file` 是空的"
        return out
    path = Path(raw)
    root = Path(package_root)
    if path.is_absolute():
        out["state"] = "outside"
        out["abs"] = str(path)
        out["reason"] = ("`file` 必须写论文包内的相对路径（收到的是绝对路径 "
                         f"{raw!r}）—— 绝对路径在别人的机器上等于不存在")
        return out
    absolute = (root / path).resolve()
    out["abs"] = str(absolute)
    try:
        absolute.relative_to(root.resolve())
    except ValueError:
        out["state"] = "outside"
        out["reason"] = f"`file` 指到了论文包之外：{raw!r}"
        return out
    if absolute.is_dir():
        out["state"] = "directory"
        out["reason"] = f"`file` 指到的是一个目录：{raw!r}"
        return out
    if not absolute.is_file():
        out["state"] = "missing"
        out["reason"] = f"`file` 在论文包里不存在：{raw!r}（解析成 {absolute}）"
        return out
    try:
        size = absolute.stat().st_size
    except OSError as exc:
        out["state"] = "missing"
        out["reason"] = f"`file` 读不到大小：{raw!r}（{type(exc).__name__}: {exc}）"
        return out
    out["state"] = "empty" if size == 0 else "present"
    return out


def lean_switch() -> tuple[bool, str]:
    """这一趟走不走 Lean 形式化（业主 2026-10-12 的开关）。返回 `(值, 来源)`。

    口径只有一处：`settings.lean_enabled`（环境变量 `AGENTFLOW_LEAN_ENABLED` >
    设置文件 `toolchain` 段的 `LEAN_ENABLED_KEY` > `DEFAULT_LEAN_ENABLED`）。这里照抄
    `closing._check_load_bearing` 那一处调用（`_SET.lean_enabled()[0]`）—— 不另写第三份判定，
    也不把结果缓存在模块常量里：环境变量可以在 import 之后才设，缓存就会让"我关掉了"
    与"这一格以为还开着"分家。

    为什么惰性 import：本模块要在收工门的"运行外"出口里被读（没有 store、只有工作区目录），
    不想在 import 期就把设置层与它牵连的东西全拉起来。
    """
    from . import settings as SET

    return SET.lean_enabled()


def _lean_sources(base: Path) -> list[Path]:
    """`base` 下所有 `.lean` 文件（不跟符号链接；`LEAN_SKIP_DIRS` 与点目录不进）。"""
    if not base.is_dir():
        return []
    out: list[Path] = []
    stack: list[Path] = [base]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                is_dir = entry.is_dir()
            except OSError:
                continue
            if is_dir:
                name = entry.name
                if name.startswith(".") or name in LEAN_SKIP_DIRS:
                    continue
                stack.append(entry)
            elif entry.name.lower().endswith(LEAN_SUFFIX):
                out.append(entry)
    return out


def lean_artifacts(project_root: str | Path) -> list[str]:
    """盘上已有的 Lean 产物（排序、去重；包内的记成包内相对路径）。

    三处都扫：论文包内任意 `*.lean`（包内写法，`formal/000004.lean`）、
    `<项目根>/out/formal/` 与 `<项目根>/code/formal/`（后两处记成项目根相对路径，
    如 `code/formal/000004.lean`）。三处都是 `lean_file` 能填的写法
    （2026-10-25：`code/formal` 是 L 的真实落点，见 `LEAN_ARTIFACT_DIRS`）。

    返回值是"盘上到底有没有 Lean 产出、以及它在哪"这个事实的读数。它不再是
    "两格必填"的触发器（2026-11-04 业主口径：那一格是「这条命题有机器核验过的凭据」，
    按每条命题的证明通道判）；它仍然进读数（`lean` 那一格）与
    `lean_on_but_no_artifact` 那一档警告 —— "一个形式化文件都没落"必须看得见。
    """
    project = Path(project_root)
    package = package_dir(project)
    found: list[str] = []
    for path in _lean_sources(package):
        try:
            found.append(path.relative_to(package).as_posix())
        except ValueError:
            continue
    for rel_dir in LEAN_ARTIFACT_DIRS:
        for path in _lean_sources(project / rel_dir):
            try:
                found.append(path.relative_to(project).as_posix())
            except ValueError:
                continue
    out: list[str] = []
    for rel in sorted(found):
        if rel not in out:
            out.append(rel)
    return out


def _lean_source_state(package_root: Path, project_root: Path | None,
                       rel: Any) -> dict[str, Any]:
    """`lean_file` 那一格在盘上的状态：先按论文包内解析，找不到再按项目根解析。

    为什么两个根都认（2026-10-25，审计 G/H/V/L 第 4 条）：三个落点此前各说各话 ——
    G 的提示词说"论文包内相对路径"、L 把源码落在 `code/formal/`、扫描面是"包内 +
    `out/formal`"，而全仓没有任何一步把 `code/formal` 拷进包 ⇒ 那条真实存在的源码
    永远填不进这一格。现在 `lean_file` 收「项目根相对路径」，同时保留包内写法
    （老项目与包内的 `formal/000004.lean` 逐字照旧）。

    绝对路径与两个根之外的路径仍然是 `outside`（`file_state` 的原判据不动）：
    换一台机器也要能复核。
    """
    raw = str(rel or "").strip()
    state = file_state(package_root, raw)
    if project_root is None or state["state"] != "missing":
        return state
    elsewhere = file_state(project_root, raw)
    if elsewhere["state"] in ("present", "empty", "directory"):
        return elsewhere
    return state


def _declaration_re(name: Any) -> re.Pattern[str]:
    """声明名的词边界正则：`foo` 不许命中 `foobar`、`foo'`、`Foo.foo`。

    为什么边界里带 `.`：Lean 的名字是点分的，`FreeGroupFactor.isII1` 与
    `My.FreeGroupFactor.isII1` 是两条不同的声明 —— 左边允许 `.` 就会把后者读成前者。
    """
    return re.compile(r"(?<![\w.'])" + re.escape(str(name or "")) + r"(?![\w.'])")


def lean_declares(text: str, name: Any) -> bool:
    """`name` 是不是真的出现在这段 Lean 源码里（词边界匹配，不是子串）。"""
    raw = str(name or "")
    if not raw:
        return False
    return bool(_declaration_re(raw).search(str(text or "")))


#: Lean 顶层声明那一行的写法（`@[…]` 属性、修饰词、声明关键字、名字）。
#:
#: 只认行首：`have h : …` / `rw [foo]` 里的名字不是声明。`namespace` / `section` 不改名
#: （`lean_target` 既允许写短名、也允许与源码逐字一致的全名）。
_DECLARATION_LINE_RE = re.compile(
    r"^[ \t]*(?:@\[[^\]]*\][ \t]*)*"
    r"(?:(?:private|protected|noncomputable|partial|unsafe|scoped)[ \t]+)*"
    r"(?:theorem|lemma|def|abbrev|instance|structure|class|inductive)[ \t]+"
    r"(?P<name>[^\s:{([]+)",
    re.MULTILINE,
)


def lean_declarations(text: Any) -> list[dict[str, Any]]:
    """一段 Lean 源码里顶层写了哪些声明（`[{"name", "line"}]`，按出现顺序）。

    为什么放在这里：`lean_target` 那一格的来源就是"那份 `.lean` 里的声明名"，而
    "声明名长什么样"与 :func:`lean_declares` 是同一件事的两面 —— 一处认名字、一处列名字，
    分开写就会漂（认的是全名、列的却是短名，等于两套口径）。

    刻意只认行首的声明关键字（理由见 `_DECLARATION_LINE_RE`）：注释里的 `theorem foo`
    与 tactic 块里的名字都不是声明。列不出来时返回空清单，由调用方报"读不出声明名"，
    绝不拿文件的路径去凑一个名字。
    """
    out: list[dict[str, Any]] = []
    for lineno, line in enumerate(str(text or "").splitlines(), start=1):
        hit = _DECLARATION_LINE_RE.match(line)
        if hit is None:
            continue
        out.append({"name": str(hit.group("name")), "line": lineno})
    return out


def _range_problem(value: Any) -> str:
    """一个区间的形态问题（空串 = 合法：两个正整数、起点不大于终点）。"""
    if isinstance(value, Mapping):
        start, end = value.get("start"), value.get("end")
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        start, end = value[0], value[1]
    else:
        return (f"区间要写成 [起点, 终点] 或 {{\"start\": ..., \"end\": ...}}，"
                f"收到 {value!r}")
    for name, got in (("起点", start), ("终点", end)):
        if isinstance(got, bool) or not isinstance(got, int) or got < 1:
            return f"{name}必须是正整数，收到 {got!r}"
    if int(start) > int(end):
        return f"起点 {start} 大于终点 {end}"
    return ""


def _citation_problems(row: Row, package_root: Path,
                       origin: str) -> list[dict[str, Any]]:
    """`citation_loc` 那一格的三态判据（口径见模块 docstring）。"""
    problems: list[dict[str, Any]] = []
    loc = row.citation_loc
    if loc is None:
        if origin == "external_lit":
            problems.append(_problem(
                "mapping_citation_loc_missing",
                f"表里 label={row.label!r} 指着外部文献的命题（origin=external_lit），"
                "`citation_loc` 必填 —— 引文在包里哪一份文件、哪一段，H 要靠它逐字核",
                label=row.label, where=MAPPING_JSON_NAME))
        elif origin == "own_result" and not row.citation_loc_reason:
            problems.append(_problem(
                "mapping_citation_loc_missing",
                f"表里 label={row.label!r} 没有 `citation_loc`，也没有 `citation_loc_reason` —— "
                "我们自己得的命题允许无引文位置，但那句理由必须写出来",
                label=row.label, where=MAPPING_JSON_NAME))
        return problems
    if not isinstance(loc, Mapping):
        problems.append(_problem(
            "mapping_citation_loc_missing",
            f"表里 label={row.label!r} 的 `citation_loc` 必须是对象 "
            f"{{file, page_range|line_range|char_range}}，收到 {type(loc).__name__}",
            label=row.label, where=MAPPING_JSON_NAME))
        return problems
    file_raw = str(loc.get("file") or "").strip()
    if not file_raw:
        problems.append(_problem(
            "mapping_citation_loc_missing",
            f"表里 label={row.label!r} 的 `citation_loc` 缺 `file`（包内那份文件的相对路径）",
            label=row.label, where=MAPPING_JSON_NAME))
        return problems
    given = [(k, v) for k in RANGE_KEYS if (v := loc.get(k)) is not None]
    if not given:
        problems.append(_problem(
            "mapping_citation_loc_missing",
            f"表里 label={row.label!r} 的 `citation_loc` 三种区间一个都没给"
            f"（{list(RANGE_KEYS)} 至少给一种）",
            label=row.label, where=MAPPING_JSON_NAME))
    for key, value in given:
        bad = _range_problem(value)
        if bad:
            problems.append(_problem(
                "mapping_citation_loc_missing",
                f"表里 label={row.label!r} 的 `citation_loc.{key}` 读不懂：{bad}",
                label=row.label, where=MAPPING_JSON_NAME))
    if file_raw.lower().startswith(("http://", "https://")):
        problems.append(_problem(
            "mapping_citation_file_missing",
            f"表里 label={row.label!r} 的 `citation_loc.file` 是外网 URL（{file_raw!r}）—— "
            "要的是论文包里那份抽取文本 / PDF / 占位文件的相对路径",
            label=row.label, where=MAPPING_JSON_NAME))
        return problems
    state = file_state(package_root, file_raw)
    if state["state"] in ("missing", "directory", "outside"):
        problems.append(_problem(
            "mapping_citation_file_missing",
            f"表里 label={row.label!r} 的 `citation_loc.file` 读不到：{state['reason']}",
            label=row.label, where=MAPPING_JSON_NAME))
    return problems


def _credential_statement(row: Row,
                          ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None
                          ) -> Mapping[str, Any] | None:
    """这一行压在台账里的那条命题（带上这一号证明的正文）；读不到 ⇒ `None`。

    证明正文按 `proof_no` 取（`verifications.proof_text_of`：`#p1` 是行上的
    `proof_text`，`#p2` 及以上在 `proofs` 清单里）—— 一条命题有多条证明时，
    "这一行走哪条通道"问的是这一份证明，不是 canonical 那一份。
    """
    resolved = resolve_ledger_id(row.ledger_id, ledger)
    if not resolved["ok"] or str(resolved.get("table") or "") != "statements":
        return None
    target = ledger_row(ledger, "statements", str(resolved["row_id"]))
    if not isinstance(target, Mapping):
        return None
    return {**dict(target), "proof_text": V.proof_text_of(target, row.proof_no)}


def _proof_column_program(statement: Mapping[str, Any] | None, *,
                          experiments: Sequence[Mapping[str, Any]] = (),
                          evidence: Any = "", file: Any = "") -> str:
    """证明栏那份程序的相对路径（读不到 ⇒ 空串）。

    2026-11-08 起程序路径住在 `experiments.code_path`（证明栏只剩 ③），所以认法：
    ① 先按这一行的 `numeric_evidence`（`exp:NNNNNN`）钉到那条实验、读它的 `code_path`；
    ② 读不到才退回旧形态的证明栏文本（历史数据里 `程序：` 那一段）；
    ③ 再退到对应表那一行的 `file`（它本来就是"证明栏"那一格；例子 / 实验的数值凭据
       正是填在这里）。
    通道判据仍只问 `numericproof.proof_channel`，本函数不另判通道。
    """
    if not isinstance(statement, Mapping):
        return ""
    legacy = NP.norm_rel(NP.proof_column_script(statement.get("proof_text")))
    if legacy:
        return legacy
    eid = str(evidence or "").strip().split(":")[-1]
    if eid:
        for row in (experiments or ()):
            if not isinstance(row, Mapping):
                continue
            if str(row.get("experiment_id") or row.get("id") or "") != eid:
                continue
            got = NP.norm_rel(row.get("code_path"))
            if got:
                return got
    fallback = NP.norm_rel(file)
    return fallback if NP.is_script_path(fallback) else ""


def _credential_slot(row: Row,
                     ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None,
                     experiments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """这一行的凭据格该填哪一类（真身在 `numericproof.formal_slot`，本模块只接线）。

    通道判据只有那一处（`proof_channel` + `formal_slot`）：数值证明 / 形式化 / 空。
    这里不另写一套，否则"这一条命题该填什么"会长出第二个答案。
    """
    statement = _credential_statement(row, ledger)
    if statement is None:
        return {"channel": "", "kind": "", "path": "", "problems": [],
                "why": "台账里读不到这一行压着哪条命题 ⇒ 通道读不出来"}
    return NP.formal_slot(statement, experiments, filled=str(row.lean_file or "").strip())


def _experiment_rows(ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None
                     ) -> list[dict[str, Any]]:
    """台账里 `experiments` 那几行（判通道要读它；读不到就是空表，不是"随便一条"）。"""
    return [dict(item) for item in ((ledger or {}).get("experiments") or ())
            if isinstance(item, Mapping)]


def _numeric_row_reading(row: Row,
                         ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None,
                         experiments: Sequence[Mapping[str, Any]] | None = None
                         ) -> dict[str, Any]:
    """这一行的「证明通道 / 是否按数值定理判 / 证明栏是不是程序」——三件事的唯一读法。

    判据本体只有一处：通道由 `numericproof.proof_channel` 判（经 `_credential_slot` 读，
    而 `_credential_slot` 只接线 `numericproof.formal_slot`）。`kind` 不参与 ——
    `kind="example"` 的行只要证明栏是程序，它照样是数值定理那一支要管的行。

    通道判不出来（空串）时用 E-1 的入口 `numerictheorem.is_program_proof`
    （它再转发 `numericproof.proof_column_script`）兜底：证明栏第 ① 段就是一份程序 ⇒
    这一行按数值定理那一支判。为什么必须有这条兜底：程序还没被 E 签成穷举时
    `proof_channel` 也返回空串，而那一档要报的是 `mapping_proof_program_unbacked`
    （"只能记成有数值实验支持"）—— 兜底去掉，那条红会静默消失。

    兜底只决定"按哪一支判"，不决定通道：凭据格该不该填仍按 `channel`（空通道两格必须空）。
    本模块里没有第二处判断"这一行算不算数值定理"：`is_numeric_row` 读的就是这里。
    """
    if experiments is None:
        experiments = _experiment_rows(ledger)
    slot = _credential_slot(row, ledger, experiments)
    channel = str(slot.get("channel") or "")
    statement = _credential_statement(row, ledger)
    program = bool(statement) and NT.is_program_proof(statement.get("proof_text"))
    return {
        "channel": channel,
        "program": program,
        "slot": slot,
        "numeric": channel == NP.PROOF_CHANNEL_NUMERIC or (not channel and program),
    }


def credential_fields(channel: Any) -> tuple[str, ...]:
    """这一条证明通道"该填"哪几个凭据格（`_lean_problems` 与 `mapping_cells` 共用这一处）。

    数值通道只要 `lean_file` 一格（一份数值程序没有 Lean 声明名那一半）；形式化与空通道
    都是 :data:`LEAN_ROW_FIELDS` 那两格。空通道返回两格是刻意的：`_lean_problems` 要判
    「只填了一半」（那时缺的那一格才是它报的格），而「通道为空 ⇒ 这一格不适用」由
    调用方按 `bool(channel)` 决定 —— 通道的判据只有 `numericproof.proof_channel` 一处。
    """
    if str(channel or "") == NP.PROOF_CHANNEL_NUMERIC:
        return ("lean_file",)
    return LEAN_ROW_FIELDS


def _empty_channel_problems(row: Row) -> list[dict[str, Any]]:
    """没有证明通道那一行的凭据格读数（`_lean_problems` 的第 5 / 6 条）。

    "没有通道"= 证明栏里既没有程序也没有 Lean 源码、台账里也没有 E 签的穷举。此时
    这一行的凭据格必须两格都空：填了 `lean_file` / `lean_target` 是无依据的声称，
    填了 `numeric_evidence` / `exhaustion_note` 是自称有数值证据而没有数值证明通道
    （2026-11-04 缝隙二；`mapping_reading` 与收工门读数都读这一条）。

    从 `_lean_problems` 拆出来只为让那个函数回到 200 行以下（2026-11-05：缺陷 1
    那一支加进来之后 189 → 215）。判据一个字没改，拆的只是落点。
    """
    problems: list[dict[str, Any]] = []
    claimed = [name for name in (NT.EVIDENCE_FIELD, NT.NOTE_FIELD)
               if str(getattr(row, name, "") or "").strip()]
    if claimed:
        problems.append(_problem(
            NT.NUMERIC_EVIDENCE_MISSING,
            f"表里 label={row.label!r}（{row.kind} 第 {row.env_no} 个）填了 {claimed}，"
            "而这一行没有数值证明通道（证明栏里既没有程序也没有 Lean 源码、台账里"
            "也没有 E 签的穷举）⇒ 这一行自称有数值证据，但没有数值证明通道 —— 两边"
            "不一致：要么把证明栏第 ① 段写成那份程序并让 E 签下穷举，要么把这两格清空",
            label=row.label, where=MAPPING_JSON_NAME))
    filled = [name for name in LEAN_ROW_FIELDS
              if str(getattr(row, name, "") or "").strip()]
    if filled:
        problems.append(_problem(
            "mapping_lean_file_missing",
            f"表里 label={row.label!r}（{row.kind} 第 {row.env_no} 个）的凭据格填了 "
            f"{filled}，而这一行没有证明通道（证明栏里既没有程序也没有 Lean 源码）"
            "⇒ 凭据格不许填，填了就是无依据的声称 —— 类别与通道不一致："
            f"`lean_file` 是「{CREDENTIAL_CELL_NAME}」那一格，它说的是「这条命题"
            "百分百为真」；没有通道就没有凭据，两格都必须留空",
            label=row.label, where=MAPPING_JSON_NAME))
    return problems


def _lean_problems(rows: Sequence[Row], package_root: Path,
                   project_root: Path | None = None,
                   ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None = None
                   ) -> list[dict[str, Any]]:
    """凭据那一格（`lean_file`，字段名照旧）：什么时候必填、填的类别要与通道一致。

    六件事分开报，一条坏不遮蔽另一条：
    1. 通道非空而缺（或两格只填了一格）=> `mapping_lean_missing`；
    2. 凭据的类别与证明通道不一致（数值通道填 `.lean`、形式化通道填 `.py`、空通道填程序）
       => `mapping_lean_file_missing`（判据本体是 `numericproof.formal_slot`，这里只加一句
       「类别与通道不一致」的定位，不另判一次）；
    3. 形式化通道的 `.lean` 两个根里都找不到 => `mapping_lean_file_missing`；
       `lean_target` 在那一份 `.lean` 里找不到 => `mapping_lean_target_missing`；
    4. 同一个 `lean_target` 被两行共用 => `mapping_lean_target_ambiguous`；
    5. 空通道（证明栏里既没有程序也没有 Lean 源码、台账里也没有 E 签的穷举）而凭据格填了
       任一格 => `mapping_lean_file_missing`：没有通道就没有凭据，两格必须都空
       （2026-11-04 缝隙三，业主口径「这一格的功能是这条命题百分百为真」）；
    6. 空通道而 `numeric_evidence` / `exhaustion_note` 有值 => `mapping_numeric_evidence_missing`：
       "这一行自称有数值证据，但没有数值证明通道"（2026-11-04 缝隙二；`mapping_reading` 与
       收工门读数都读这一条，两边同时报，不再一边报一边不报）；
    7. 例子 / 实验（`STATEMENT_ENV_KINDS` 之外）的证明栏第 ① 段是程序、而 E 还没把它签成
       穷举（`proof_channel` 为空）时，凭据格填的就是那份 `.py`：这一支认它，不要求
       `lean_target`、也不按「类别与通道不一致」拒（2026-11-05 缺陷 1）。命题类环境不认这一支
       —— 定理的「百分百为真」必须由 E 签下的穷举背书，没签的那份程序仍受控拒。

    "必填"按这一条命题的证明通道判（`numericproof.formal_slot` 的 numeric / formal /
    空），不再按"盘上有没有 Lean 产物"判：后者是一个全局读数，不是某一条命题的凭据
    （2026-11-04 业主口径：这一格说的是「这个命题是百分百真的」）。通道为空 ⇒ 这一格
    不许填（不是"允许为空"而是"必须为空"，见第 5 条）。这一条只在 `LEAN_KINDS` 非空时
    才被调用（见 `mapping_reading`）：清空那一组就是关掉这一档，反真空用例靠它证明这些红
    真的靠那组 kind。

    通道与"证明栏是不是程序"的唯一读法是 :func:`_numeric_row_reading`（它只接线
    `numericproof.proof_channel` 与 `numerictheorem.is_program_proof`）：这里不另判一次
    "这一行算不算数值定理"。

    `lean_file` 的解析走 :func:`_lean_source_state`（包内优先、项目根兜底）：
    L 的源码在 `code/formal/`，它填不进"只认包内"的那一版（2026-10-25 第 4 条）。
    """
    problems: list[dict[str, Any]] = []
    experiments = _experiment_rows(ledger)
    seen_targets: dict[str, Row] = {}
    for row in rows:
        lean_file = str(row.lean_file or "").strip()
        lean_target = str(row.lean_target or "").strip()
        reading = _numeric_row_reading(row, ledger, experiments)
        slot = reading["slot"]
        channel = str(reading["channel"] or "")
        # 通道的两个取值在 `numericproof.PROOF_CHANNEL_*`（`channel` 与 `kind` 是两件事：
        # 前者是"证明走哪条路"，后者是"这一格该填哪一类"）。
        numeric = channel == NP.PROOF_CHANNEL_NUMERIC
        formal = channel == NP.PROOF_CHANNEL_FORMAL
        # 证明栏第 ① 段是程序、而 E 还没把它签成穷举时，`proof_channel` 返回空串。
        # 例子 / 实验不是被证明的命题：那份程序本身就是它们的「数值凭据」，
        # 凭据格填它就齐 —— 不因 kind 不是命题类环境而挡（2026-11-05 缺陷 1）。
        program_path = ""
        if reading["program"] and not channel:
            program_path = _proof_column_program(
                _credential_statement(row, ledger), experiments=experiments,
                evidence=str(getattr(row, NT.EVIDENCE_FIELD, "") or ""),
                file=str(row.file or ""))
        program_credential = bool(program_path) and row.kind not in STATEMENT_ENV_KINDS
        values = {"lean_file": lean_file, "lean_target": lean_target}
        if not channel and not reading["program"]:
            # 空通道：凭据格必须两格都空（第 5 条）；填了就是无依据的声称。
            problems.extend(_empty_channel_problems(row))
            continue
        # 数值通道那两格里只有一格（程序地址）：程序没有 Lean 声明名那一半。
        # 这份清单只有一处（`credential_fields`）：`doc.mapping_cells` 读的是同一个函数。
        # 例子 / 实验按「证明栏第 ① 段是程序」这一支同样只要那两格里的第一格。
        wants = ("lean_file",) if program_credential else credential_fields(channel)
        missing = [name for name in wants if not values[name]]
        half = (any(values[name] for name in LEAN_ROW_FIELDS)
                and not all(values[name] for name in LEAN_ROW_FIELDS))
        need = numeric or formal
        if missing and (need or half):
            if numeric:
                why = ("这条命题的证明通道是数值证明（证明栏第 ① 段是程序 "
                       f"{str(slot.get('path') or '')!r}）⇒ 这一格必须填那份程序"
                       "（相对仓库根，.py）—— 这一格的功能就是「这条命题有机器核验过的"
                       "凭据」")
                tail = ("数值证明通道：`lean_file` 填证明栏第 ① 段那份程序（如 "
                        "code/r34_check.py）；`lean_target` 不用填（数值程序没有 Lean 声明名）")
            elif formal:
                why = ("这条命题的证明通道是 Lean（形式化）⇒ 这一格必须填那份 `.lean` 与它"
                       "验的声明名（`lean_target`）")
                tail = ("形式化通道：`lean_file` 写那份源码的真实位置（项目根相对路径，如 "
                        "code/formal/000004.lean；论文包内的写法 formal/000004.lean 也认），"
                        "`lean_target` 写 Lean 里那个声明的名字（如 FreeGroupFactor.isII1）")
            else:
                why = "两格是一对：只填一格时，另一格没有任何东西可以复核它"
                tail = ("这一条命题没有数值/形式化证明通道 ⇒ 这一格本可以留空；现在是只填了"
                        "一半，才要求补齐（`lean_file` 与 `lean_target` 是一对）")
            problems.append(_problem(
                "mapping_lean_missing",
                f"表里 label={row.label!r}（{row.kind} 第 {row.env_no} 个）缺 {missing} —— "
                f"{why}。`lean_file` 是「{CREDENTIAL_CELL_NAME}」那一格。{tail}",
                label=row.label, where=MAPPING_JSON_NAME))
        file_ok = False
        if lean_file:
            if numeric:
                # 类别与通道要一致、地址还要是证明栏第 ① 段那一份（`norm_rel` 比）：
                # 两条判据都在 `formal_slot` 里，这里只把它的理由与定位转发出来。
                for detail in slot.get("problems") or ():
                    problems.append(_problem(
                        "mapping_lean_file_missing",
                        f"表里 label={row.label!r} 的 `lean_file` = {lean_file!r} 类别与通道不一致"
                        "（通道 = 数值证明程序，这一格要填的是证明栏第 ① 段"
                        f"那份程序 {str(slot.get('path') or '')!r}）：{detail}",
                        label=row.label, where=MAPPING_JSON_NAME))
                file_ok = not (slot.get("problems") or ())
            elif program_credential:
                # 例子 / 实验的凭据就是证明栏第 ① 段那份程序（不必等 E 签成穷举）：
                # 填同一份 `.py` 就齐；换成 `.lean` 或另一份程序都是类别与通道不一致。
                if NP.is_script_path(lean_file) and NP.norm_rel(lean_file) == program_path:
                    file_ok = True
                else:
                    problems.append(_problem(
                        "mapping_lean_file_missing",
                        f"表里 label={row.label!r}（{row.kind} 第 {row.env_no} 个）的 "
                        f"`lean_file` = {lean_file!r} 与证明栏第 ① 段那份程序 "
                        f"{program_path!r} 不一致：这一行按数值凭据通道判（例子 / 实验不是"
                        "被证明的命题，证明栏第 ① 段就是它们的凭据）⇒ 这一格必须是那一份 "
                        "`.py`（相对仓库根；换成 Lean 源码或另一份程序都是两类凭据互相冒充）",
                        label=row.label, where=MAPPING_JSON_NAME))
            elif not lean_file.lower().endswith(LEAN_SUFFIX):
                if formal:
                    got_channel = "Lean 程序（形式化）⇒ 这一格只收 `.lean` 路径"
                elif reading["program"]:
                    got_channel = ("空（这一行有程序但还没有 E 签的穷举 ⇒ 证明通道判不出来）"
                                   "⇒ 不能把一份数值程序填进这一格")
                else:
                    got_channel = ("空（这一条没有证明通道：`proof_text` 不是程序、台账里"
                                   "也没有 E 签的穷举）⇒ 不能把一份数值程序填进这一格")
                if formal or NP.is_script_path(lean_file):
                    problems.append(_problem(
                        "mapping_lean_file_missing",
                        f"表里 label={row.label!r} 的 `lean_file` = {lean_file!r} 类别与通道不一致："
                        f"通道 = {got_channel} —— 凭据的类别必须与通道一致（两类不许互相冒充）",
                        label=row.label, where=MAPPING_JSON_NAME))
                else:
                    problems.append(_problem(
                        "mapping_lean_file_missing",
                        f"表里 label={row.label!r} 的 `lean_file` = {lean_file!r} 不是 Lean 源码"
                        f"（要以 {LEAN_SUFFIX} 结尾）—— 它指的是那份真的被检查器读过的文件",
                        label=row.label, where=MAPPING_JSON_NAME))
            else:
                state = _lean_source_state(package_root, project_root, lean_file)
                if state["state"] in ("missing", "directory", "outside"):
                    problems.append(_problem(
                        "mapping_lean_file_missing",
                        f"表里 label={row.label!r} 的 `lean_file` 读不到：{state['reason']} —— "
                        "它必须是项目根相对路径（如 code/formal/000004.lean，L 的落点）或论文包内"
                        "相对路径（如 formal/000004.lean）；绝对路径在别人的机器上等于不存在",
                        label=row.label, where=MAPPING_JSON_NAME))
                else:
                    file_ok = True
        if numeric and lean_target:
            # 数值证明通道那一格填的是程序地址：`lean_target` 是 Lean 声明名，两者不是一回事。
            problems.append(_problem(
                "mapping_lean_missing",
                f"表里 label={row.label!r} 的 `lean_target` = {lean_target!r} 在数值证明通道上"
                "没有落点：这一格是 Lean 声明名，而这一条命题的凭据是那份数值程序"
                "（`lean_file`）—— 填了就是拿 Lean 的名字给一份数值程序背书",
                label=row.label, where=MAPPING_JSON_NAME))
        elif lean_target and lean_file and file_ok:
            absolute = Path(state["abs"])
            try:
                text = absolute.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                problems.append(_problem(
                    "mapping_lean_target_missing",
                    f"表里 label={row.label!r} 的 `lean_file` = {lean_file!r} 读不出文本"
                    f"（{type(exc).__name__}: {exc}）—— 名字没核过，不算命中",
                    label=row.label, where=MAPPING_JSON_NAME))
                text = None
            if text is not None and not lean_declares(text, lean_target):
                problems.append(_problem(
                    "mapping_lean_target_missing",
                    f"表里 label={row.label!r} 的 `lean_target` = {lean_target!r} 在 "
                    f"{lean_file!r} 里找不到这个名字（做的是词边界匹配：`foo` 不算命中 "
                    "`foobar`）—— 要写那份源码里字面出现的声明名：源码是 "
                    "`namespace X` 里写短名，就写短名；写全名，就与源码逐字一致。"
                    "正文里的 LaTeX label 不是它",
                    label=row.label, where=MAPPING_JSON_NAME))
        if not numeric and lean_target:
            prev = seen_targets.get(lean_target)
            if prev is not None:
                problems.append(_problem(
                    "mapping_lean_target_ambiguous",
                    f"`lean_target` = {lean_target!r} 被两行共用"
                    f"（label={prev.label!r} 与 label={row.label!r}）—— 同一个声明只验得了一条；"
                    "一条命题有多条证明时，两行可以共用一个 `lean_file`，"
                    "但 `lean_target` 必须是各自那份证明里的声明名",
                    label=row.label, where=MAPPING_JSON_NAME))
            else:
                seen_targets[lean_target] = row
    return problems


def parse_rows(payload: Any) -> tuple[list[Row], list[dict[str, Any]]]:
    """把 json 的载荷读成行（读不懂的行落一条 `mapping_unresolvable`，不静默丢）。

    载荷同时接受 `{"rows": [...]}` 与裸列表：前者是写侧（`write_mapping`）的形状，
    后者是人手写的常见形状 —— 两种都读，而每一行的字段判据只有这一份。
    """
    raw_rows = payload.get("rows") if isinstance(payload, Mapping) else payload
    problems: list[dict[str, Any]] = []
    if not isinstance(raw_rows, (list, tuple)):
        problems.append(_problem(
            "mapping_unresolvable",
            "表的形状不对：顶层应当是 {\"rows\": [...]} 或一个列表，收到 "
            f"{type(payload).__name__}"))
        return [], problems
    rows: list[Row] = []
    for i, item in enumerate(raw_rows, start=1):
        if not isinstance(item, Mapping):
            problems.append(_problem(
                "mapping_unresolvable", f"第 {i} 行不是对象（收到 {type(item).__name__}）"))
            continue
        kind = str(item.get("kind") or "").strip()
        if kind not in ENV_KINDS:
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行的 `kind` = {kind!r} 不在受控词表 {list(ENV_KINDS)} 里",
                label=str(item.get("label") or "")))
            continue
        # 必填格按 kind 分档（2026-11-26 GMAP）：定义行没有证明稿，`file` 不是必填格；
        # 其余每一行都要它。清单只有一处真身（`required_fields_for_kind`）。
        required = required_fields_for_kind(kind)
        missing = [f for f in required
                   if not str(v if (v := item.get(f)) is not None else "").strip()]
        if missing:
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行缺必填字段 {missing}（{kind} 行必须有 {list(required)}）"
                + ("—— 定义行没有证明稿，`file` 可以省略；其余行不行"
                   if not manuscript_required(kind) else ""),
                label=str(item.get("label") or "")))
            continue
        label = str(item.get("label") or "").strip()
        raw_env_no = item.get("env_no")
        env_no = _int_or_none(raw_env_no)
        # `env_no = 0` 只对 `exp:` / `lit:` 行合法：0 说的是「被引、未印成环境」
        # （`EXPERIMENT_ENV_NO`）。定理类环境必须真的印在正文里，0 对它们是"没写环境号"。
        ledger_text = str(item.get("ledger_id") or "").strip()
        is_exp_row = ledger_text.startswith(EXPERIMENT_ID_PREFIX)
        cited_kind = is_exp_row or ledger_text.startswith(LITERATURE_ID_PREFIX)
        if env_no is None and cited_kind and str(raw_env_no).strip() in ("0", "0.0"):
            env_no = EXPERIMENT_ENV_NO
        if env_no is None:
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行的 `env_no` 必须是 1 起的整数"
                "（`exp:` / `lit:` 行允许 0 = 被引未印成环境），"
                f"收到 {item.get('env_no')!r}",
                label=label))
            continue
        if env_no == EXPERIMENT_ENV_NO and not cited_kind:
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行的 `env_no` = 0，而它的 `ledger_id` 不是 `exp:` / `lit:` 行 —— "
                "0 只表示「被引、未印成环境」，定理/引理/命题/推论必须真的印在正文里",
                label=label))
            continue
        proof_no = _int_or_none(item.get("proof_no"))
        if proof_no is None:
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行的 `proof_no` 必须是 1 起的整数（1 = canonical），"
                f"收到 {item.get('proof_no')!r}",
                label=label))
            continue
        loc = item.get("citation_loc")
        if loc is not None and not isinstance(loc, Mapping):
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行的 `citation_loc` 必须是对象，收到 {type(loc).__name__}",
                label=label))
            continue
        bad_lean = [f for f in LEAN_ROW_FIELDS
                    if (v := item.get(f)) is not None and not isinstance(v, str)]
        if bad_lean:
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行的 {bad_lean} 必须是字符串（`lean_file` 是「"
                + CREDENTIAL_CELL_NAME + "」那一格的路径 —— Lean 程序或数值证明程序；"
                "`lean_target` 是 Lean 里那个声明的名字）",
                label=label))
            continue
        bad_numeric = [f for f in NUMERIC_ROW_FIELDS
                       if (v := item.get(f)) is not None and not isinstance(v, str)]
        if bad_numeric:
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行的 {bad_numeric} 必须是字符串（`numeric_evidence` 是 E 那条读数的"
                "编号 exp:NNNNNN、`exhaustion_note` 是那块读数在仓库里的相对路径）",
                label=label))
            continue
        bad_index = [f for f in (NP.INDEX_KIND_FIELD, NP.INDEX_PATH_FIELD, NP.INDEX_SHA_FIELD,
                                 PROOF_FILE_SHA_FIELD)
                     if (v := item.get(f)) is not None and not isinstance(v, str)]
        bad_sign = item.get(NP.INDEX_SIGN_FIELD)
        if bad_index or (bad_sign is not None and not isinstance(bad_sign, Mapping)):
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行的索引格形状不对（{bad_index or [NP.INDEX_SIGN_FIELD]}）："
                f"`{NP.INDEX_KIND_FIELD}` / `{NP.INDEX_PATH_FIELD}` / `{NP.INDEX_SHA_FIELD}` / "
                f"`{PROOF_FILE_SHA_FIELD}` 是字符串、"
                "`v_signature` 是对象（{\"verdict\": …, \"sha256\": …}）",
                label=label))
            continue
        # 被引实验行那几格（框架填，但读侧也要认形状：坏形状不许静默丢）。
        raw_logs = item.get(EXPERIMENT_LOGS_FIELD)
        if raw_logs is not None and (not isinstance(raw_logs, (list, tuple))
                                     or not all(isinstance(x, str) for x in raw_logs)):
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行的 `{EXPERIMENT_LOGS_FIELD}` 必须是字符串列表（台账 `artifact_paths`"
                f" 的原样），收到 {raw_logs!r}",
                label=label))
            continue
        bad_experiment = [f for f in (EXPERIMENT_CODE_HASH_FIELD, EXPERIMENT_RESULT_FIELD,
                                      EXPERIMENT_NEGATION_FIELD, EXPERIMENT_PARAMS_FIELD)
                          if (v := item.get(f)) is not None and not isinstance(v, str)]
        raw_exit = item.get(EXPERIMENT_EXIT_FIELD)
        if bad_experiment or (raw_exit is not None
                              and (isinstance(raw_exit, bool) or not isinstance(raw_exit, int))):
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行的实验格形状不对（{bad_experiment or [EXPERIMENT_EXIT_FIELD]}）："
                "`experiment_code_hash` / `experiment_result` / `experiment_negation_kind` / "
                "`experiment_params` 是字符串，`experiment_exit_code` 是整数",
                label=label))
            continue
        rows.append(Row(kind=kind, label=label, env_no=env_no,
                        ledger_id=str(item.get("ledger_id") or "").strip(),
                        proof_no=proof_no,
                        file=str(item.get("file") or "").strip(),
                        lean_file=str(item.get("lean_file") or "").strip(),
                        lean_target=str(item.get("lean_target") or "").strip(),
                        page_or_section=str(item.get("page_or_section") or "").strip(),
                        citation_loc=dict(loc) if isinstance(loc, Mapping) else None,
                        citation_loc_reason=str(item.get("citation_loc_reason") or "").strip(),
                        numeric_evidence=str(item.get(NT.EVIDENCE_FIELD) or "").strip(),
                        exhaustion_note=str(item.get(NT.NOTE_FIELD) or "").strip(),
                        # 索引四格（D-34）：形状在这里归一，"齐不齐 / 指不指得到对象"
                        # 由 `numerictheorem.evidence_index_problems` 一处判（判据不在这里）。
                        evidence_kind=str(item.get(NP.INDEX_KIND_FIELD) or "").strip(),
                        evidence_path=str(item.get(NP.INDEX_PATH_FIELD) or "").strip(),
                        evidence_sha256=str(item.get(NP.INDEX_SHA_FIELD) or "").strip(),
                        evidence_file_sha256=str(
                            item.get(PROOF_FILE_SHA_FIELD) or "").strip(),
                        v_signature=(dict(bad_sign)
                                     if isinstance(bad_sign, Mapping) else None),
                        # 台账那两格（D-69）：旧表没有这两键 ⇒ 读成空串 ⇒ 渲染印
                        # `未读到`（"这一格没填"不许印成空白，也不许折成「未通过」/「未审」）。
                        ledger_kind=str(item.get(LEDGER_KIND_FIELD) or "").strip(),
                        reviewed=str(item.get(REVIEWED_FIELD) or "").strip(),
                        # 优化态与来源（2026-11-02）：与前两格同一条读法 —— 缺键读空串，
                        # 渲染印「未记录」（不许折成「未优化」：那是"记过了、是假的"）。
                        optimized=str(item.get(OPTIMIZED_FIELD) or "").strip(),
                        proof_source=str(item.get(PROOF_SOURCE_FIELD) or "").strip(),
                        experiment_logs=tuple(str(x) for x in (raw_logs or ())),
                        experiment_code_hash=str(item.get(EXPERIMENT_CODE_HASH_FIELD) or "").strip(),
                        experiment_result=str(item.get(EXPERIMENT_RESULT_FIELD) or "").strip(),
                        experiment_negation_kind=str(
                            item.get(EXPERIMENT_NEGATION_FIELD) or "").strip(),
                        experiment_params=str(item.get(EXPERIMENT_PARAMS_FIELD) or "").strip(),
                        experiment_exit_code=(int(raw_exit) if isinstance(raw_exit, int)
                                              and not isinstance(raw_exit, bool) else None)))
    return rows, problems


def _loc_text(row: Row) -> str:
    """`citation_loc` 在 md 里的一格写法（空串 = 没给）。"""
    loc = row.citation_loc
    if not isinstance(loc, Mapping):
        return ""
    parts = [str(loc.get("file") or "")]
    for key in RANGE_KEYS:
        value = loc.get(key)
        if isinstance(value, Mapping):
            parts.append(f"{key} {value.get('start')}-{value.get('end')}")
        elif isinstance(value, (list, tuple)) and len(value) == 2:
            parts.append(f"{key} {value[0]}-{value[1]}")
        elif value is not None:
            parts.append(f"{key} {value!r}")
    return " · ".join(p for p in parts if p)


# ---------------------------------------------------------------- 论文语言（D-45）
#
# 附录是论文的一部分：标题、说明段、表头、占位格都得跟正文同一种语言。语言只在一处判
# （`paper_language`：正文的 CJK 密度），渲染函数按它出文 —— 于是"英文论文的附录里印着
# 中文"这件事在结构上不会发生，而不是靠谁记得手改。

#: 论文语言的两种取值。
PAPER_LANGUAGE_EN = "en"
PAPER_LANGUAGE_ZH = "zh"

#: 全部取值（`render_appendix` 的 `language=` 只收这两个）。
PAPER_LANGUAGES: tuple[str, ...] = (PAPER_LANGUAGE_EN, PAPER_LANGUAGE_ZH)

#: 没有正文可读时的默认语言：本仓的论文是英文，默认跟着它走。
DEFAULT_PAPER_LANGUAGE = PAPER_LANGUAGE_EN

#: 判"这是中文论文"的密度门（CJK 字符数 / 非空白字符数）。
#:
#: 实测读数（2026-10-24）：cube2 那份英文正文 0.000；判据夹具里那几份"英文导言区 +
#: 三行中文定理"的稿子 0.10 上下；一份中文散文为主的稿子在 0.40 以上。0.30 把后两类
#: 分开，于是夹具里那几个中文定理不会被读成"中文论文"。`PAPER_LANGUAGE_MIN_CJK` 是
#: 第二道闸：正文里零星几个中文字不许把整篇判成中文。
PAPER_LANGUAGE_CJK_RATIO = 0.30
PAPER_LANGUAGE_MIN_CJK = 20

#: CJK 字符（汉字常用区 + 扩展 A + 兼容区）。
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

#: 论文抬头那四个宏：中文方案（ctex 的 chinese scheme、或手写重定义）改的就是它们。
#:
#: 为什么盯这四个：它们是"每印一次就混一次语言"的那一类 —— `\proofname` 改一次，
#: 正文里每一条证明的开头都从 "Proof." 变成「证明」（cube2 的现场）。
HEADING_MACROS: tuple[str, ...] = ("proofname", "abstractname", "refname", "appendixname")

#: `\renewcommand{\proofname}{…}` / `\renewcommand\proofname{…}` / `\def\proofname{…}`
#: （带星号与参数个数的写法都收）。取值那一支不含花括号：抬头名里没有嵌套命令。
_HEADING_REDEFINE_RE = re.compile(
    r"\\(?:renewcommand|providecommand|newcommand|def)\*?\s*\{?\s*\\"
    r"(?P<macro>" + "|".join(HEADING_MACROS) + r")\s*\}?\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}")

#: `\documentclass[选项]{类名}`（类名那一支必取）。
_CLASS_RE = re.compile(r"\\documentclass\s*(?P<options>\[[^\]]*\])?\s*\{(?P<cls>[^{}]*)\}")

#: ctex 那一族文档类：默认 scheme 是 chinese，源码里一个中文都没有，印出来却是
#: 「摘要」「参考文献」「证明。」。
_CJK_CLASSES: tuple[str, ...] = ("ctexart", "ctexrep", "ctexbook", "ctexbeamer")

#: 附录里由渲染器产出的那几段文字，按语言分两个版本（两版的键集必须一致）。
#:
#: 为什么整段都按语言写死在这里、而不是只换标题：缺一个占位格（「（未开 Lean）」这种）
#: 就够让英文附录里冒出中文 —— D-45 的现场里正是一行里同时出现了英文散文与中文占位。
_APPENDIX_TEXT: dict[str, Any] = {
    PAPER_LANGUAGE_EN: {
        "title": "Appendix: Output Mapping",
        "note": (
            "This table is rendered from \\texttt{" + MAPPING_JSON_NAME + "} by "
            "\\texttt{agentflow.papermapping.render\\_appendix}, so there is no second copy to keep "
            "by hand. The \\texttt{file} column is a path relative to the paper package and therefore "
            "names the same file on another machine; for a theorem proved by an exhaustive numerical "
            "experiment, \\texttt{file} is the path of that program relative to the repository root. "
            "The column headed ``Lean (file / declaration)'' is the machine-checked credential slot: "
            "it holds the program by which this statement is known to be true. For a statement whose "
            "proof goes through formalization it holds the Lean source and the declaration that source "
            "checks; for a statement proved by an exhaustive numerical experiment it holds that "
            "numerical proof program (a ``.py`` path, the same one named as the proof program) and the "
            "declaration half stays empty. What belongs in that slot follows the proof channel of that "
            "statement -- an entry of the other kind is refused -- and an empty cell means that "
            "statement has no machine-checked credential: an empty cell never means checked, and with "
            "the switch off the cell reads ``(Lean off)''. "
            "The last two columns belong to theorems proved by numerical experiment: the reading of "
            "E's exhaustive run (\\texttt{" + NT.EVIDENCE_PREFIX + "NNNNNN}) and where E's two written "
            "blocks (design note and exhaustion argument) live; when absent they read "
            "``(not a numeric proof)''. The two columns after the ledger row are the ledger's own "
            "kind for that row and what V did with it; the V column is one of four: "
            "``signed (verdict: ...)'' (the per-proof signature table says this very proof is "
            "signed), ``not passed'' (the review ledger exists, but this proof has no signature), "
            "``unreviewed'' (the review ledger does not exist at all: never sent), or "
            "``(unread)'' (the cell could not be read: no statement row, a broken ledger file). "
            "``(unread)'' is never folded into ``not passed'' or ``unreviewed''. "
            "The last column belongs to the experiments the paper cites: it holds the reading "
            "log(s) recorded for that experiment, each path as it stands in the experiment "
            "ledger, followed by the experiment's result; a dash means the row is not an "
            "experiment. An experiment row whose environment number reads a dash is cited by "
            "the paper without being printed as an environment. This paragraph "
            "itself is written by the renderer in the language of the paper: do not hand-copy it "
            "and do not mix languages."
        ),
        "columns": (
            "Env", "Label", "Ledger row", "Ledger kind", "V sign-off", "Proof", "File",
            "Lean (file / declaration)", "Citation location", "E reading", "Exhaustion note",
            "Experiment log / result",
        ),
        "lean_off": "(Lean off)",
        "lean_unfilled": "(not filled)",
        "numeric_empty": "(not a numeric proof)",
    },
    PAPER_LANGUAGE_ZH: {
        "title": APPENDIX_TITLE,
        "note": (
            "本表由 \\texttt{" + MAPPING_JSON_NAME + "} 渲染（\\texttt{agentflow.papermapping.render\\_appendix}），"
            "不许手抄第二份；这一段说明由渲染函数按论文语言生成，不许手抄、不许混语言。"
            "\\texttt{file} 一列是论文包内的相对路径 —— 换一台机器也指向同一份文件；"
            "数值实验定理那一行的 \\texttt{file} 是那份穷举程序的相对路径（相对仓库根）。"
            "Lean 那一列（\\texttt{lean\\_file} / \\texttt{lean\\_target}）是「" + CREDENTIAL_CELL_NAME
            + "」：形式化通道填验它的那份源码在哪（\\texttt{.lean}）与验的是哪个声明；"
            "数值证明通道填证明栏第 ① 段那份数值程序（\\texttt{.py}，与证明栏同一份），"
            "声明那一半留空。填什么由这一条命题的证明通道决定（填错类别就是受控拒绝）；"
            "空着是「这一条没有机器核验凭据」，绝不等于验过；开关关时印「" + LEAN_OFF_CELL + "」。"
            "最后两列是数值实验定理的：E 的那条穷举读数（\\texttt{" + NT.EVIDENCE_PREFIX
            + "NNNNNN}）与 E 写的那两块（" + NT.BLOCK_DESIGN + " / " + NT.BLOCK_EXHAUSTION
            + "）落在哪一份读数里；不填印「" + NUMERIC_EMPTY_CELL + "」。"
            "台账序号后面那两列是「台账里这一行叫什么」（`" + LEDGER_KIND_FIELD + "`）与"
            "「V 拿这一份怎么办」（`" + REVIEWED_FIELD + "`）：两格都由写侧按台账现读现填。"
            "后一格是四档：「已签（判决：…）」（逐份表说这一份签过）、「" + REVIEWED_NOT_PASSED
            + "」（审校台账在、而这一份没拿到签）、「" + REVIEWED_UNREVIEWED
            + "」（审校台账不在：从没送审）、「" + LEDGER_CELL_UNREADABLE
            + "」（这一格没查成：statements 行读不到 / 台账读不出）——"
            "「" + LEDGER_CELL_UNREADABLE + "」绝不折成「" + REVIEWED_NOT_PASSED
            + "」或「" + REVIEWED_UNREVIEWED + "」。"
            "最后一列属于论文里写到的实验：它给出那条实验在台账里登记的读数日志（逐份原样）"
            "与结果；印「—」的行不是实验行。环境号印「—」的实验行表示：论文引了它、但没把它"
            "印成 `experiment` 环境。"
        ),
        "columns": (
            "环境", "label", "台账序号", "台账 kind", "V 是否签过", "证明号", "真实文件",
            "Lean（文件 / 声明）", "引文位置", "E 读数", "两块读数",
        ),
        "lean_off": LEAN_OFF_CELL,
        "lean_unfilled": LEAN_UNFILLED_CELL,
        "numeric_empty": NUMERIC_EMPTY_CELL,
    },
}

#: 附录表的十二列定宽（`\\textwidth` 的比例；十二列合计 0.90，剩下的留给列间距与 `\\tabcolsep`）。
#:
#: 业主 2026-10-24（D-46）：原先是四列 `l`（自然宽）加六列定宽，引文位置那一格是一整句
#: 英文，于是整张表宽出 `\\textwidth`、右侧被切到页外，Lean 那两列还互相压字。现在全列
#: 定宽、Lean 的文件与声明并成一列、整表 `\\small` 且 `\\tabcolsep` 收到 2pt。
#:
#: D-69 加了台账那两格（`ledger_kind` / `reviewed`）之后是十一列：新增的两列各 0.07 / 0.09，
#: 其余九列按同一比例压一点，合计仍然是 0.90 —— 列数变了而总宽不变，否则整张表又会宽出
#: `\\textwidth`（D-46 的那条判据按"列格式与表头逐格对上"判，不看具体数值）。
#:
#: 2026-11-25（MAPPING-COMPLETE）：加最后一列「实验读数 / 结果」占 0.10，其余十一列从
#: 0.80 总量里各收一点 —— 合计仍是 0.90。理由同上：原来 0.90 已经把 `\tabcolsep` 的
#: 余量吃满，把新列直接加到 0.90 之上必然宽出 `\\textwidth`。
APPENDIX_COLUMN_WIDTHS: tuple[float, ...] = (
    0.06, 0.08, 0.08, 0.06, 0.08, 0.05, 0.07, 0.09, 0.10, 0.05, 0.08, 0.10,
)

#: 定宽列里"字母数字连写的长串"隔几个字给一个可选断点（`_tex_breakable` 用它）。
#:
#: 取 7：比任何一列的最小可用宽度都短（`theorem` / `experiment` / `nicomachus` 这类整词
#: 因此断得开），又长到不会把普通词断得七零八落。
PAPER_CELL_BREAK_RUN = 7


def _cjk_count(text: Any) -> int:
    """这段文本里有多少个 CJK 字符（判据扫附录 CJK 与判论文语言共用这一个读法）。"""
    return len(_CJK_RE.findall(str(text or "")))


def paper_language_of_text(tex: str) -> str:
    """一段 tex 正文的语言读数（`en` / `zh`）：只有一条判据 —— 正文的 CJK 密度。

    先剥注释：注释不是印出来的正文，里面的中文不该把整篇判成中文论文。
    """
    body = strip_tex_comments(str(tex or ""))
    total = len(re.sub(r"\s+", "", body))
    if not total or _cjk_count(body) < PAPER_LANGUAGE_MIN_CJK:
        return PAPER_LANGUAGE_EN
    return (PAPER_LANGUAGE_ZH
            if _cjk_count(body) / total >= PAPER_LANGUAGE_CJK_RATIO
            else PAPER_LANGUAGE_EN)


def paper_language(project_root: str | Path | None = None) -> str:
    """论文语言 = 正文语言（D-45）：读论文包里的 `main.tex` 定，读不到就按默认英文。

    这是本模块唯一的语言判定口：附录的标题、说明段、表头、占位格全由它决定。
    判据把它打桩成恒中文时附录必须跟着变中文（反真空）—— 这也是为什么
    `render_appendix` 自己调它，而不是让每个调用方各传一个字符串。
    """
    if project_root is None:
        return DEFAULT_PAPER_LANGUAGE
    try:
        text = (package_dir(project_root) / PC.TEX_NAME).read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_PAPER_LANGUAGE
    return paper_language_of_text(text)


def appendix_title(language: str = PAPER_LANGUAGE_ZH) -> str:
    """附录那一节的标题（按论文语言；中文那一版就是业主点名的「附录：产出对应表」）。"""
    return str(_APPENDIX_TEXT[language]["title"])


def paper_heading_problems(tex: str) -> list[str]:
    """英文论文里"抬头被换成中文"的静态判定（D-45 ⑥）：返回问题清单，空 = 没命中。

    判三件，都能在 tex 源码上一眼看定：

    - 四个抬头宏（`\\proofname` 那一族）被重定义成含 CJK 的值 —— 改一次，每一条证明、
      每一页页眉都跟着换语言；
    - 文档类是 ctex 那一族且没有 `scheme=plain`：它的默认方案把同样的四个抬头印成
      中文，而源码里一个中文字都看不见（cube2 的现场：`\\documentclass[11pt]{ctexart}`）；
    - 正文本身是中文（`paper_language_of_text` 读到 `zh`）时上面两条都不算缺陷 ——
      中文论文里中文抬头是对的。

    这是纯判定：只读 tex 文本，不碰盘、不改状态。
    """
    body = strip_tex_comments(str(tex or ""))
    if paper_language_of_text(body) != PAPER_LANGUAGE_EN:
        return []
    problems: list[str] = []
    for match in _HEADING_REDEFINE_RE.finditer(body):
        if _CJK_RE.search(match.group(0)):
            problems.append(
                f"导言区把 \\{match.group('macro')} 重定义成了含中文的值（{match.group(0)}）"
                "—— 英文论文里这个抬头每印一次就混一次语言")
    for match in _CLASS_RE.finditer(body):
        cls = match.group("cls").strip()
        options = (match.group("options") or "").replace(" ", "")
        if cls in _CJK_CLASSES and "scheme=plain" not in options:
            problems.append(
                f"文档类是 {cls}（选项 {options or '无'}）—— ctex 的默认方案会把 "
                "abstract / references / appendix / proof 四个抬头印成中文"
                "（源码里一个中文字都没有）；英文论文用 article，或显式写 scheme=plain")
    return problems


def _tex_breakable(escaped: str) -> str:
    """给路径/编号/长词加可断点（定宽列里的一串字必须断得开）。

    为什么需要：`p{}` 列里 `\\texttt{formal/000000.lean}` 这种整串在 TeX 眼里是一个词，
    列宽 45pt 而串宽 100pt 时它不换行 —— 直接压到邻列上（D-46 的现场）。两档断点：

    - `/` `:` `.` `_` 后面插 `\\allowbreak{}`（路径与编号的自然断点，不带连字符）；
    - 字母数字连写的长串每 `PAPER_CELL_BREAK_RUN` 个字插一个 `\\-`（可断连字符）：
      `experiment` 这种整词比整列还宽时，它是唯一能断的地方，断出来带连字符不难看。

    两档都只是"可选断点"：不断的时候一个字符都不多印。
    """
    out: list[str] = []
    run = 0
    for char in escaped:
        out.append(char)
        if char in "/:._":
            out.append("\\allowbreak{}")
            run = 0
        elif char.isascii() and char.isalnum():
            run += 1
            if run >= PAPER_CELL_BREAK_RUN:
                out.append("\\-")
                run = 0
        else:
            run = 0
    return "".join(out)


def _cell(text: Any, *, mono: bool = False) -> str:
    """表格里的一格：先转义、再加可断点；`mono=True` 的那几格套 `\\texttt{}`。

    整格用 `\\raggedright` 排版（不用 `array` 宏包，`>{}` 那种列格式要它，而论文的导言区
    只保证 amsmath / booktabs）：长路径与整句英文挤在定宽列里时，两端对齐会撑出巨大的
    词间距（D-46 现场那一列的文字看着像"竖排折行"，一半原因就是它）。
    """
    body = _tex_breakable(_tex_escape(text))
    if mono:
        body = "\\texttt{" + body + "}"
    return "{\\raggedright " + body + "\\par}"


def _lean_cell(value: str, lean_on: bool, language: str = PAPER_LANGUAGE_ZH) -> str:
    """凭据那一格在表格里的一格：空着时按开关状态写占位，不印空白。

    "空"与"验过了"必须分得开：开关关时印「未开 Lean」（这一趟没走形式化，不是没写），
    开关开而没填就印「没填」——它是不是红的由 `mapping_lean_*` 那几档判，
    这一格只负责不让读者把空白读成"没问题"。

    为什么渲染器不按证明通道印第三档（「不适用」）：通道要读台账（这一号证明的正文 +
    E 签的穷举），而渲染函数是纯函数、只拿得到行；把读盘塞进来会让 md / 附录的
    "逐字相同"判据变成第二份通道口径。空着这一格在不适用与漏填之间两种可能都由
    `mapping_lean_*` 那一档在 `problems` 里说清，渲染只负责"不印空白"。

    `language` 只决定占位那句怎么写：英文论文的附录里不许出现中文（D-45）。
    默认值是中文（人读的 `MAPPING.md` 恒中文，走的就是默认值）。
    """
    if value:
        return value
    text = _APPENDIX_TEXT[language]
    return str(text["lean_unfilled"] if lean_on else text["lean_off"])


def _numeric_cell(value: str, language: str = PAPER_LANGUAGE_ZH) -> str:
    """数值实验定理那两格在表格里的一格：空着时印占位（不让空白被读成"没问题"）。

    与 Lean 那两格的 `_lean_cell` 同一个理由，但默认值不同：Lean 有开关状态可分，
    这两格没有开关 —— 空着就是"这一行不是数值实验定理，或者该填没填"，
    两种情况都得由读者看得见，所以印同一句占位。`language` 的口径同 `_lean_cell`。
    """
    return value or str(_APPENDIX_TEXT[language]["numeric_empty"])


def _ledger_kind_cell(row: Row) -> str:
    """`ledger_kind` 那一格在 md 里怎么印（空着就印 `未读到`，不印空白）。"""
    return str(row.ledger_kind or "").strip() or LEDGER_CELL_UNREADABLE


def _reviewed_print_cell(row: Row) -> str:
    """`reviewed` 那一格在 md 里怎么印（空着就印 `未读到`，不印空白）。

    与 `_ledger_kind_cell` 同一条纪律：这一格的几档里没有一档叫"空白"。
    """
    return str(row.reviewed or "").strip() or LEDGER_CELL_UNREADABLE


def _optimized_print_cell(row: Row) -> str:
    """优化态那一格在 md 里怎么印（空着就印「未记录」，不印空白）。

    为什么不印「未优化」：空串的意思是"这一格没填过"（旧表 / 存量行），而「未优化」
    是一个关于这一份证明的结论（记过了、是假的）。两者在表上长得一样是本项目最忌的
    形态（与 reviewed 的四档同一条理由）。
    """
    return str(row.optimized or "").strip() or OPTIMIZED_UNKNOWN


def _source_print_cell(row: Row) -> str:
    """来源那一格在 md 里怎么印（空着就印「未记录」）。"""
    raw = str(row.proof_source or "").strip()
    if raw == PROOF_SOURCE_OWN:
        return "我方证明"
    if raw == PROOF_SOURCE_CITATION:
        return "文献侧录入"
    return raw or OPTIMIZED_UNKNOWN


#: 台账那两格在附录里按论文语言怎么说（D-45）。
#:
#: 为什么附录要翻一遍、而 json / md 只存中文那一版：json 与 md 是给人读的中文两份
#: （`MAPPING.md` 恒中文），附录是论文的一部分 —— 英文论文里一个中文字都不许有。
#: 三份仍然同源（同一批 `Row`、同一个渲染器），差别只是附录这一道按语言出词；
#: 这与 Lean 那两格的"（未开 Lean）/ (Lean off)"是同一条既有口径。
#:
#: `reviewed` 那四档：`signed (verdict: …)` / `not passed` / `unreviewed` / `(unread)`。
#: 判决原话那一格：中文版逐字用原话；英文版按 `schema.REVIEW_VERDICTS` 这张受控词表
#: 翻成英文词。词表外的词（坏数据）英文附录印 `(unread)` 而不是把中文原话印进去：
#: 印进去就破了 D-45 那条"英文论文的附录里没有 CJK"，而不印只是"这一格翻不出来"。
_LEDGER_CELL_TEXT: dict[str, Any] = {
    PAPER_LANGUAGE_EN: {
        "unread": "(unread)",
        "not_passed": "not passed",
        "unreviewed": "unreviewed",
        "signed": "signed (verdict: {verdict})",
        #: 实验行：`experiments` 表没有 `kind`、也不走 V 的审校链 ⇒ 这一格是"不适用"，
        #: 不是"读不到"（后者说的是"没查成"）。
        "not_applicable": "n/a (experiment row)",
        #: 2026-11-16 裁定 ④：「看不出来」那一档已从判定词表里删除 ⇒ 英文附录也不再
        #: 替它留一个译名。老数据里若真出现那四个字，按"这一格翻不出来"印 `(unread)`
        #: （不是把它印成通过，也不是给它一个 inconclusive 的第三态）。
        "verdicts": {"成立": "holds", "有毛病": "defective"},
    },
    PAPER_LANGUAGE_ZH: {
        "unread": LEDGER_CELL_UNREADABLE,
        "not_passed": REVIEWED_NOT_PASSED,
        "unreviewed": REVIEWED_UNREVIEWED,
        "signed": REVIEWED_SIGNED_TEMPLATE,
        #: 实验行：台账那一行没有 `kind`、也不在 V 的审校链上（`EXPERIMENT_LEDGER_CELL`）。
        "not_applicable": EXPERIMENT_LEDGER_CELL,
        "verdicts": {},
    },
}


def _split_reviewed(cell: Any) -> tuple[str, str]:
    """把 `reviewed` 那一格的规范写法拆成 `(状态, 判决原话)`。

    状态只有四档：`signed` / `not_passed` / `unreviewed` / `unread`。拆不出来的写法
    一律落 `unread`：这一格认不出时，它说的既不是"签了"也不是"没签"，那是
    "这一格没查成"。
    """
    text = str(cell or "").strip()
    if not text or text == LEDGER_CELL_UNREADABLE:
        return "unread", ""
    if text == REVIEWED_NOT_PASSED:
        return "not_passed", ""
    if text == REVIEWED_UNREVIEWED:
        return "unreviewed", ""
    head, _, tail = REVIEWED_SIGNED_TEMPLATE.partition("{verdict}")
    if (tail and text.startswith(head) and text.endswith(tail)
            and len(text) > len(head) + len(tail)):
        return "signed", text[len(head):len(text) - len(tail)]
    return "unread", ""


def _appendix_reviewed(cell: Any, language: str) -> str:
    """附录里那一格（按论文语言出词；四档原样保留）。

    实验行那一格是"不适用"（`EXPERIMENT_LEDGER_CELL`），按语言出词，不折进 `(unread)`。
    """
    text = _LEDGER_CELL_TEXT[language]
    if str(cell or "").strip() == EXPERIMENT_LEDGER_CELL:
        return str(text["not_applicable"])
    state, verdict = _split_reviewed(cell)
    if state in ("not_passed", "unreviewed"):
        return str(text[state])
    if state != "signed":
        return str(text["unread"])
    word = verdict if language == PAPER_LANGUAGE_ZH else str(
        text["verdicts"].get(verdict) or "")
    return str(text["signed"]).format(verdict=word or text["unread"])


def _appendix_ledger_kind(cell: Any, language: str) -> str:
    """附录里 `ledger_kind` 那一格（台账那个词原样印；读不到按语言印占位）。

    台账的 `kind` 是台账自己的词（theorem / lemma / conjecture …），不翻 —— 翻一个
    受控词表的取值等于造第二个词表。只有"读不到"那一档按语言出词。
    """
    raw = str(cell or "").strip()
    if raw == EXPERIMENT_LEDGER_CELL:
        return str(_LEDGER_CELL_TEXT[language]["not_applicable"])
    if not raw or raw == LEDGER_CELL_UNREADABLE:
        return str(_LEDGER_CELL_TEXT[language]["unread"])
    return raw


def _lean_pair(row: Row, lean_on: bool, language: str) -> str:
    """凭据那一格（D-46 把文件与声明并成一列）：`文件 / 声明`。

    形式化通道那两半都在（Lean 程序 + 声明名）；数值证明通道只填前半（程序地址），
    声明那一半空着 —— 空着时按开关印占位。两格都空（按开关印出同一句占位）时只印一次：
    `（未开 Lean）/（未开 Lean）` 会让读者以为漏填了一格。
    """
    left = _lean_cell(row.lean_file, lean_on, language)
    right = _lean_cell(row.lean_target, lean_on, language)
    if not row.lean_file and not row.lean_target:
        return left
    return f"{left} / {right}"


def _row_key_text(row: Row, language: str = PAPER_LANGUAGE_ZH) -> str:
    """附录里那条机器可读注释的内容（`|` 分隔，判据靠它数行与比 label）。

    末尾两格是数值实验定理的（E 的读数编号与两块读数的落点）：追加在末尾而不是插在中间，
    因为 `appendix_row_keys` 按位置读前几格 —— 插在中间会让旧附录整份对不上。

    D-69 的两格（`ledger_kind` / `reviewed`）同样追加在末尾（排在数值实验那两格之后）：
    理由与上面那一句相同 —— 位置一旦挪动，读侧按位置读的那几格会静默错位。它们按
    `language` 出词（注释也是附录的一部分，英文论文里同样不许出现 CJK）。

    2026-11-25（MAPPING-COMPLETE）：被引实验行那几格插在 `exhaustion_note` 之后、
    `ledger_kind` / `reviewed` 之前 —— 那两格必须留在最后两格（读侧按 `parts[-2:]`
    读它们，`appendix_row_keys` 按前 3 格读 label），插到它们后面会把两格的读法挤错位。
    日志多份用 `,` 连（注释只占一行），空值写空串 —— 它只是同一份 Row 的渲染，
    不是第二份数据源（真身仍是 json 里的 `experiment_logs` 列表）。
    """
    return "|".join([row.kind, str(int(row.env_no)), row.label, row.ledger_id,
                     str(int(row.proof_no)), row.file, row.lean_file, row.lean_target,
                     row.numeric_evidence, row.exhaustion_note]
                    + _experiment_key_cells(row)
                    + [_appendix_ledger_kind(row.ledger_kind, language),
                       _appendix_reviewed(row.reviewed, language)])


def _experiment_key_cells(row: Row) -> list[str]:
    """被引实验行那几格在注释里的写法（非实验行一律空串，保持列数稳定）。

    `experiment_params` 在注释里留空：它的取值可能是中文（"未记录（台账 params 为空）…"），
    而附录是论文的一部分 —— 英文论文的附录里连注释也不许出现 CJK（D-45）。参数摘要仍在
    `MAPPING.json` / `MAPPING.md` 里（那两份是中文面），附录不重复它。
    """
    if not is_experiment_row(row):
        return ["" for _ in EXPERIMENT_ROW_FIELDS]
    return [",".join(str(p) for p in row.experiment_logs),
            str(row.experiment_code_hash or ""),
            str(row.experiment_result or ""),
            str(row.experiment_negation_kind or ""),
            "",
            ("" if row.experiment_exit_code is None else str(int(row.experiment_exit_code)))]


def _appendix_env_cell(row: Row) -> str:
    """附录第一格：`experiment 1` / `theorem 2`；被引未印的行写 `experiment —`。

    0 不是"第 0 个环境"：它说的是"这一行没有正文环境"（`EXPERIMENT_ENV_NO`）。
    印成 `experiment 0` 会让读者以为正文里真有一个编号 0 的环境。
    """
    return f"{row.kind} {'—' if is_cited_only_row(row) else int(row.env_no)}"


def _appendix_experiment_reading(row: Row, language: str = PAPER_LANGUAGE_ZH) -> str:
    """附录最后一格：实验行的读数日志（逐份）与结果；非实验行印 `—`。

    日志是 `experiments.artifact_paths` 的原样（`experiment_logs`），多份用 `; ` 连；
    结果后括注 `negation_kind`（若有）。这一格只是渲染，不改写台账里的任何路径。
    """
    if not is_experiment_row(row):
        return "—"
    logs = "; ".join(str(p) for p in row.experiment_logs or ()) or "—"
    result = str(row.experiment_result or "").strip()
    negation = str(row.experiment_negation_kind or "").strip()
    tail = result + (f" ({negation})" if negation else "")
    return f"{logs} — {tail}" if tail else logs


def appendix_row_keys(block: str) -> list[tuple[str, str]]:
    """从附录块里读出 `(kind, label)` 清单（只认 `MAPPING-ROW` 那条注释）。"""
    out: list[tuple[str, str]] = []
    for line in str(block or "").split("\n"):
        text = line.strip()
        if not text.startswith(APPENDIX_ROW_PREFIX.strip()):
            continue
        parts = text[len(APPENDIX_ROW_PREFIX.strip()):].strip().split("|")
        if len(parts) >= 3:
            out.append((parts[0], parts[2]))
    return out


def render_appendix(rows: Iterable[Row], *, lean_enabled: bool | None = None,
                    language: str | None = None,
                    project_root: str | Path | None = None) -> str:
    """把行渲染成正文附录（唯一渲染函数；手抄的那一段过不了逐字比对）。

    `lean_enabled` 不给时按 `lean_switch()` 的当次读数（读盘那一侧也走同一个默认）：
    Lean 那一列因此印的是这一趟的真实状态，而不是一段永远一样的空白。

    `language` 不给时按 `paper_language(project_root)` 的读数：附录是论文的一部分，
    标题、说明段、表头、占位格全部跟正文同语言（D-45）。给了 `language` 就照给的写
    （判据里反真空那一条把这一支打桩成恒中文）。

    表格不再宽出 `\\textwidth`（D-46）：九列全定宽、整表 `\\small`、`\\tabcolsep` 收到
    2pt，Lean 的文件与声明并成一列；路径类的格子带 `\\allowbreak{}` 断点，免得一串
    类型宽字把定宽列撑破。
    """
    items = list(rows)
    lean_on = lean_switch()[0] if lean_enabled is None else bool(lean_enabled)
    lang = paper_language(project_root) if language is None else str(language)
    if lang not in PAPER_LANGUAGES:
        raise ValueError(f"language 只能是 {PAPER_LANGUAGES} 之一，收到的是 {lang!r}")
    text = _APPENDIX_TEXT[lang]
    columns = tuple(text["columns"])
    spec = ("@{}" + "".join(f"p{{{width:.2f}\\textwidth}}"
                            for width in APPENDIX_COLUMN_WIDTHS) + "@{}")
    lines = [
        APPENDIX_BEGIN,
        "\\section*{" + str(text["title"]) + "}",
        "",
        str(text["note"]),
        "",
        # 字号与列间距只在组内生效：`\\small` 要是漏到别的小节，读者会以为整篇都是小字。
        "\\begingroup",
        "\\small",
        "\\setlength{\\tabcolsep}{2pt}",
        "\\begin{tabular}{" + spec + "}",
        "\\hline",
        " & ".join(columns) + " \\\\",
        "\\hline",
    ]
    for row in items:
        lines.append(APPENDIX_ROW_PREFIX + _row_key_text(row, lang))
        lines.append(" & ".join([
            _cell(_appendix_env_cell(row)),
            _cell(row.label, mono=True),
            _cell(row.ledger_id, mono=True),
            _cell(_appendix_ledger_kind(row.ledger_kind, lang), mono=True),
            _cell(_appendix_reviewed(row.reviewed, lang)),
            str(int(row.proof_no)),
            _cell(row.file, mono=True),
            _cell(_lean_pair(row, lean_on, lang)),
            _cell(_loc_text(row) or row.citation_loc_reason or ""),
            _cell("—" if is_experiment_row(row) else _numeric_cell(row.numeric_evidence, lang)),
            _cell("—" if is_experiment_row(row)
                  else _numeric_cell(row.exhaustion_note, lang), mono=True),
            _cell(_appendix_experiment_reading(row, lang), mono=True),
        ]) + " \\\\")
    lines += ["\\hline", "\\end{tabular}", "\\endgroup", "", APPENDIX_END, ""]
    return "\n".join(lines)


def render_mapping_markdown(rows: Iterable[Row], *, lean_enabled: bool | None = None) -> str:
    """把行渲染成人读的那一份（表格列顺序固定，任何人都能用同一段代码重生成）。

    `lean_enabled` 的口径与 `render_appendix` 相同（不给就按当次开关读数）。
    """
    items = list(rows)
    lean_on = lean_switch()[0] if lean_enabled is None else bool(lean_enabled)
    lines = [
        "# 论文对应表（`" + MAPPING_JSON_NAME + "` 的人读版）",
        "",
        "这一份由 `" + MAPPING_JSON_NAME + "` 生成，不许手写第二份 —— 两份不一致时，"
        "读 md 的人与读 json 的机器会得出两个结论，而没有东西会报错。",
        "",
        "重生成：`sync_markdown(项目根)`（`agentflow.papermapping`）。",
        "正文附录里印的就是这张表（「" + APPENDIX_TITLE + "」，由 `render_appendix` 渲染）。",
        "`env_no` 的口径：正文里第几个该环境，1 起，按正文出现顺序按类计数"
        "（theorem 单独数、lemma 单独数）。",
        "`proof_no` 的口径：1 = canonical（台账行上的 `proof_text`）；2 及以上 = 该行 "
        "`proofs` 清单里那一份。多证明时每一条证明各占一行。",
        "`file` 与 `citation_loc.file` 都是论文包内的相对路径：绝对路径在别人的机器上"
        "等于不存在，指到包外的相对路径同样过不了复核。",
        "`file` 的指向：`proof_no` = 1 指台账行本身或附录里那一段正文；2 及以上指那一份"
        "证明自己的文件。",
        "`lean_file` 那一格是「" + CREDENTIAL_CELL_NAME + "」：它说的是「这条命题有机器核验过"
        "的凭据（百分百为真）」，填的类别要与这条命题的证明通道一致 —— 形式化通道填 `.lean`"
        "（另带 `lean_target`：那份源码里字面出现的声明名）；数值证明通道填证明栏第 ① 段"
        "那份数值程序（`.py`，与证明栏指同一份）；没有通道时这一格允许为空（不适用）。"
        "开关关或没填时这两列印「" + LEAN_OFF_CELL + "」/「" + LEAN_UNFILLED_CELL
        + "」—— 空不等于验过。",
        "`numeric_evidence` 与 `exhaustion_note`：数值实验定理那一行（证明栏是程序）多这两格 ——"
        "E 的那条穷举读数编号（`" + NT.EVIDENCE_PREFIX + "NNNNNN`）与 E 写的那两块"
        "（" + NT.BLOCK_DESIGN + " / " + NT.BLOCK_EXHAUSTION + "）落在哪一份读数里；"
        "那一行的 `file` 写的是那份程序的相对路径（相对仓库根），不是论文包内的 tex。",
        "被引实验行（`kind=experiment`、`ledger_id=exp:NNNNNN`、`env_no=0`）：论文写到、"
        "但没印成 `experiment` 环境的那些实验由框架从 `experiments` 台账现读现造 —— `file` 是"
        "`experiments.code_path`（程序，相对仓库根），`" + EXPERIMENT_LOGS_FIELD + "` 是同一行"
        "`artifact_paths` 的原样（读数日志，多份逐份列），`" + EXPERIMENT_CODE_HASH_FIELD
        + "` / `" + EXPERIMENT_RESULT_FIELD + "` / `" + EXPERIMENT_NEGATION_FIELD + "` / `"
        + EXPERIMENT_PARAMS_FIELD + "` / `" + EXPERIMENT_EXIT_FIELD + "` 同样是台账原值；"
        "这几格 G 不写、写侧会按台账盖掉，读侧逐格核。`env_no=0` 只表示「被引、未印成环境」，"
        "不是「第 0 个环境」。",
        "`" + LEDGER_KIND_FIELD + "` 与 `" + REVIEWED_FIELD + "`（D-69）：台账那一行自己的 "
        "`kind`，以及 V 拿这一份怎么办（四档：「" + REVIEWED_SIGNED + "（判决：…）」/「"
        + REVIEWED_NOT_PASSED + "」/「" + REVIEWED_UNREVIEWED + "」/「"
        + LEDGER_CELL_UNREADABLE + "」）。两格由写侧按台账现读现填（`fill_ledger_cells`），"
        "读不到就写 `" + LEDGER_CELL_UNREADABLE + "` —— 那一档既不折成「" + REVIEWED_NOT_PASSED
        + "」也不折成「" + REVIEWED_UNREVIEWED + "」。"
        "它们让「论文里排成定理、台账里还是猜想」与「论文里排成定理、V 没签」这两件事在表上"
        "自己可见。",
        "`" + OPTIMIZED_FIELD + "` 与 `" + PROOF_SOURCE_FIELD + "`（业主 2026-11-02 的两阶段"
        "录入）：这一份证明洗过没有、以及它是哪条路交上来的。前者三档 ——「"
        + OPTIMIZED_YES + "」（换过正文且拿到覆盖新正文的 V 签）/「" + OPTIMIZED_NO
        + "」（机械录入那一版，还等着洗）/「" + OPTIMIZED_UNKNOWN + "」（这一行还没有那一格，"
        "存量行）—— 第二阶段只读这一格（「洗过的肯定能保证V签」）。后者两档："
        + PROOF_SOURCE_OWN + "（我们自己的证明）/ " + PROOF_SOURCE_CITATION
        + "（文献侧录入：V 签位填的是文献编号 = 占位签，它不算已签）；读不出来就是空。",
        "",
        "| # | kind | label | env_no | ledger_id | " + LEDGER_KIND_FIELD + " | " + REVIEWED_FIELD
        + " | " + OPTIMIZED_FIELD + " | " + PROOF_SOURCE_FIELD
        + " | proof_no | file | lean_file | lean_target "
        "| citation_loc | citation_loc_reason | page_or_section | numeric_evidence "
        "| exhaustion_note | " + EXPERIMENT_LOGS_FIELD + " | " + EXPERIMENT_CODE_HASH_FIELD
        + " | " + EXPERIMENT_RESULT_FIELD + " | " + EXPERIMENT_NEGATION_FIELD
        + " | " + EXPERIMENT_PARAMS_FIELD + " | " + EXPERIMENT_EXIT_FIELD + " |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, row in enumerate(items, start=1):
        lines.append(
            "| {i} | {kind} | {label} | {no} | {ledger} | {lkind} | {reviewed} | {optimized} "
            "| {source} | {proof} "
            "| {file} | {lean_file} "
            "| {lean_target} | {loc} | {reason} | {where} | {evidence} | {note} "
            "| {logs} | {code_hash} | {result} | {negation} | {params} | {exit_code} |".format(
                i=i, kind=row.kind, label=row.label or "（没有 label）",
                no=("—" if is_cited_only_row(row) else int(row.env_no)),
                ledger=row.ledger_id, proof=int(row.proof_no),
                lkind=_ledger_kind_cell(row), reviewed=_reviewed_print_cell(row),
                optimized=_optimized_print_cell(row),
                source=_source_print_cell(row),
                file=row.file or "（空）",
                lean_file=_lean_cell(row.lean_file, lean_on),
                lean_target=_lean_cell(row.lean_target, lean_on),
                loc=_loc_text(row) or "",
                reason=row.citation_loc_reason or "",
                where=row.page_or_section or "",
                evidence=_numeric_cell(row.numeric_evidence),
                note=_numeric_cell(row.exhaustion_note),
                logs="; ".join(row.experiment_logs or ()) or "",
                code_hash=row.experiment_code_hash or "",
                result=row.experiment_result or "",
                negation=row.experiment_negation_kind or "",
                params=row.experiment_params or "",
                exit_code=("" if row.experiment_exit_code is None
                           else int(row.experiment_exit_code))))
    lines.append("")
    counts: dict[str, int] = {}
    for row in items:
        counts[row.kind] = counts.get(row.kind, 0) + 1
    summary = "、".join(f"{k} {counts[k]}" for k in ENV_KINDS if k in counts) or "一行都没有"
    lines.append(f"合计 {len(items)} 行：{summary}。")
    lines.append("")
    return "\n".join(lines)


def _norm_text(text: str) -> str:
    """比对两份渲染产物时的归一化：只压掉行尾空白与首尾空行（内容一个字符都不放过）。"""
    body = str(text or "").replace("\r\n", "\n")
    return "\n".join(line.rstrip() for line in body.split("\n")).strip("\n")


def write_mapping(project_root: str | Path, rows: Iterable[Row], *,
                  workspace_root: str | Path | None = None,
                  path_order: Sequence[Any] | None = None) -> tuple[Path, Path]:
    """写 json 与 md 两份，返回它们的路径（都在论文包里）。

    只走这一个写口：两份由同一次 `rows` 生成，于是"手写第二份"在结构上不可能发生。

    `path_order` 是 G 用的那条 C 的路径（`payload.order` 原样）：给了就写进
    `MAPPING.json` 顶层（`PATH_ORDER_FIELD`），读侧拿它去台账里比对
    （`order_reading`）。不给 ⇒ 表里没有这一格 ⇒ 顺序那一问 `checked=False`
    （没查成，不是"顺序没问题"）。

    D-69：落盘之前先按台账把两格现读现填（`fill_ledger_cells`）。所以 G 手填的
    `ledger_kind` / `reviewed` 会被这一次现读盖掉 —— 这两格是"台账说是什么"，
    不是"提交方声称是什么"；填错了没有东西会报错，现读才有。

    D-34 的索引四格也有同一档缺口：自有证明（`proof_source="own"`）的那几行，G 交来的
    表里 `evidence_path` 常常是空的（真机 sylow-4：四行"已签"全指不到盘上任何一份稿）。
    于是落盘之前再走一次 `fill_evidence_cells`：`evidence_kind=proof`、`evidence_path` =
    台账那一行上这一号证明的稿、`evidence_sha256` = 那份稿 `## 证明` 的 sha（与 V 签的
    `正文sha` 同一把尺 —— 稿头/签块不算正文）、`v_signature` = 同一份 sha + 判决。
    G 手填的那四格同样会被这一次现读盖掉。

    `workspace_root` 是台账（`data/`）与审校台账（`verifications/`）所在的那一层；
    不给就按 `project_root` 读（单项目工作区里两者是同一个目录）。
    """
    ledger_root = workspace_root if workspace_root is not None else project_root
    items = fill_ledger_cells(ledger_root, list(rows))
    items = fill_evidence_cells(ledger_root, items)
    items = fill_experiment_cells(ledger_root, items)
    json_path, md_path = mapping_paths(project_root)
    payload: dict[str, Any] = {"rows": [row.to_dict() for row in items]}
    declared = [str(node).strip() for node in (path_order or ()) if str(node or "").strip()]
    if declared:
        # 写在 `rows` 之后（顶层多一格，不影响 `parse_rows` 读行）：这一格是"这一篇按哪条
        # 路径写的"的声明，读侧（`order_reading`）拿它去台账比对。
        payload[PATH_ORDER_FIELD] = declared
    json_path.parent.mkdir(parents=True, exist_ok=True)
    # `default=str`：载荷里一旦有非 JSON 值（Path / 时间戳 / dataclass 之外的壳对象），
    # 这一行会抛 `TypeError: Object of type … is not JSON serializable` —— 它崩在"写对应表"
    # 这一步，而对应表是收工门 paper 那一格的输入，错误信息也不指向这里。
    # 对纯 JSON 载荷这个参数不改变任何字节（判据 `tests/test_json_dumps_has_a_default.py`）。
    json_path.write_bytes(
        (json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8"))
    md_path.write_bytes(render_mapping_markdown(items).encode("utf-8"))
    return json_path, md_path


def sync_markdown(project_root: str | Path) -> Path:
    """按盘上的 json 重生成 md（改了 json 之后唯一合法的修法）。"""
    json_path, md_path = mapping_paths(project_root)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    rows, _problems = parse_rows(payload)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_bytes(render_mapping_markdown(rows).encode("utf-8"))
    return md_path


def _appendix_input_present(tex: str) -> bool:
    """正文里有没有一条真的会被排版的 `\\input{mapping-appendix}`（注释里不算）。

    写侧与读侧共用这一条判据。只做字面子串搜索的话，`% \\input{mapping-appendix}`
    会让写侧以为"已经有了"而永不补插，于是附录永久挡在 PDF 外（缺陷 3）——
    注释里出现过不算数，必须真的补一行进去。
    """
    return bool(_APPENDIX_INPUT_RE.search(strip_tex_comments(str(tex or ""))))


def write_appendix(project_root: str | Path) -> Path:
    """按盘上的 json 渲染附录，并保证 `main.tex` 里有那一行 `\\input`。

    写的是两份东西：`<论文包>/mapping-appendix.tex`（附录正文）与 `main.tex` 里
    那一行 `\\input{mapping-appendix}`（已存在就不重复插）。"存在"按
    `_appendix_input_present` 判：被注释掉的那一行不算 —— 那时要补插真正的一行，
    否则读侧永远读不到、写侧也永远不自愈。

    `\\input{mapping-appendix.tex}`（带后缀）算同一行，不再插第二行：附录在 PDF 里
    印两遍是另一种静默错。正文变长 => 必须重编一次（`doc.paper_compile`），
    否则 `closing` 的 `paper` 那一格会报"PDF 是旧正文编的"——那是既有判据，
    不因本模块而放宽。
    """
    root = Path(project_root)
    json_path, _md_path = mapping_paths(root)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    rows, _problems = parse_rows(payload)
    frag = appendix_path(root)
    frag.parent.mkdir(parents=True, exist_ok=True)
    body = render_appendix(rows, project_root=root) + "\n"
    # 生产者侧的硬不变量（2026-11-22，PAPER-PKG-FIX）：附录只写「片段」。渲染器若哪天
    # 退回"整篇 ctexart 文档"，这里在落盘前就拒 —— 真机两份 `appendix.tex` 都是整篇
    # 独立文档、都没被 `\input`（`temp/paperpkg/REPORT.md` M11）。不许写出去再靠读侧点名。
    if "\\documentclass" in body:
        raise ValueError(
            "附录渲染结果里有 `\\documentclass` ⇒ 它不是片段，拒绝落盘："
            "附录必须是能被 `main.tex` `\\input` 的一段（写侧只产出片段，"
            "整篇独立文档这条路径已删除）")
    frag.write_bytes(body.encode("utf-8"))
    tex = package_dir(root) / PC.TEX_NAME
    if tex.is_file():
        text = tex.read_text(encoding="utf-8")
        if not _appendix_input_present(text):
            end = text.rfind("\\end{document}")
            if end < 0:
                # 正文还没有 `\end{document}`（半成品稿）：追加到末尾，不猜它该在哪结束。
                # 这样"先写正文、再补附录"与"一次写完"两条路都能走通。
                text = text.rstrip("\n") + "\n" + APPENDIX_INPUT + "\n"
            else:
                text = text[:end] + APPENDIX_INPUT + "\n" + text[end:]
            tex.write_bytes(text.encode("utf-8"))
    return frag


def write_package(project_root: str | Path, rows: Iterable[Row], *,
                  workspace_root: str | Path | None = None,
                  tex: str | None = None,
                  path_order: Sequence[Any] | None = None) -> tuple[Path, Path, Path]:
    """G 的唯一写口：json + md + 附录（三份都由同一批 `rows` 生成）。

    `workspace_root` 只影响台账那两格的现读现填（台账在 `<工作区>/data/` 下）；
    不给就按项目根读（单项目工作区里是同一个目录）。

    `path_order` 原样交给 :func:`write_mapping`（写进 `MAPPING.json` 顶层）：
    G 声明它按 C 的哪一条路径行文，读侧据此核"编号按路径"。不写这一格不影响三份
    产物的字节形状之外的任何东西 —— 它只是一个声明格，缺了就是 `checked=False`。

    2026-11-25（MAPPING-COMPLETE）：落盘之前先把「论文写到、而表里还没有」的
    `exp:NNNNNN` 补成行（`synthesize_experiment_rows`）。这一步只能在这里做：
    `write_mapping` 是「给什么写什么」的纯写口（判据夹具直接调它），而"论文引了哪些实验"
    要读论文注记与正文 —— 那是 `write_package` 这一层的事。幂等：同一批 rows 连跑两次，
    行集合与字段逐字相同（第二次看到实验行已在，不再补）。
    """
    items = synthesize_experiment_rows(project_root, list(rows),
                                       workspace_root=workspace_root, tex=tex)
    json_path, md_path = write_mapping(project_root, items, workspace_root=workspace_root,
                                       path_order=path_order)
    frag = write_appendix(project_root)
    return json_path, md_path, frag


def _md_reading(project_root: Path, rows: Sequence[Row]) -> tuple[str, list[dict[str, Any]]]:
    """人读那一份的状态（`present` / `missing` / `drifted` / `unreadable`）与它的问题。"""
    _json_path, md_path = mapping_paths(project_root)
    problems: list[dict[str, Any]] = []
    if not md_path.is_file():
        problems.append(_problem(
            "md_missing",
            f"人读那一份不在包里：{md_path} —— 它由 json 生成（`sync_markdown`）；"
            "只交机器读那一份，H 与业主手上就没有可读的那一份"))
        return "missing", problems
    try:
        got = md_path.read_text(encoding="utf-8")
    except OSError as exc:
        problems.append(_problem(
            "md_drifted", f"人读那一份读不出来：{md_path}（{type(exc).__name__}: {exc}）"))
        return "unreadable", problems
    if _norm_text(got) != _norm_text(render_mapping_markdown(rows)):
        problems.append(_problem(
            "md_drifted",
            f"{md_path.name} 与 {MAPPING_JSON_NAME} 生成出来的内容不一致 —— "
            "它被手写过、或者 json 改了没重生成（`sync_markdown` 重生成一次）"))
        return "drifted", problems
    return "present", problems


def _appendix_block(project_root: Path, tex: str) -> str:
    """正文里那一段附录的字节（找不到 => 空串）。

    两种形态都认：界标直接写在正文里，或由一条真的会被排版的 `\\input` 接进来。
    `\\input{...}` 必须先剥离注释再找 —— 否则"被注释掉的那一行"会被当成
    "附录已经印进正文"，读侧从此永不报 `mapping_not_in_paper`（缺陷 3）。

    界标本身是一行注释（渲染器写的 `% ==== MAPPING-APPENDIX BEGIN …`），所以那一步
    只能在原文里找：不能先剥离注释再找界标，否则合法的附录也一起消失。
    """
    text = str(tex or "")
    start = text.find(APPENDIX_BEGIN)
    if start >= 0:
        end = text.find(APPENDIX_END, start)
        return text[start:end + len(APPENDIX_END)] if end >= 0 else text[start:]
    for name in _tex_input_names(text):
        candidate = package_dir(project_root) / str(name).strip()
        paths = [candidate] if candidate.suffix else [candidate, candidate.with_suffix(".tex")]
        for path in paths:
            if path.is_file():
                try:
                    got = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                at = got.find(APPENDIX_BEGIN)
                if at >= 0:
                    end = got.find(APPENDIX_END, at)
                    return got[at:end + len(APPENDIX_END)] if end >= 0 else got[at:]
    return ""


def _appendix_reading(project_root: Path, tex: str,
                      rows: Sequence[Row]) -> tuple[str, list[dict[str, Any]]]:
    """附录那一节的状态（`present` / `missing` / `mismatch`）与它的问题。"""
    block = _appendix_block(project_root, tex)
    # 语言从正文读（与写侧同一个判定口）：英文论文的附录标题是 Appendix: Output Mapping，
    # 照中文标题去找会把它判成"没印出来"（D-45）。
    lang = paper_language(project_root)
    if not block.strip():
        return "missing", [_problem(
            "mapping_not_in_paper",
            f"正文里读不到「{appendix_title(lang)}」那一节 —— 由 json 渲染（`write_appendix`），"
            f"再把 `{APPENDIX_INPUT}` 放进正文；表只在盘上、没印进正文，H 读稿时看不到它",
            where=PC.TEX_NAME)]
    want = render_appendix(rows, language=lang)
    if _norm_text(block) == _norm_text(want):
        return "present", []
    in_paper = appendix_row_keys(block)
    in_json = [(row.kind, row.label) for row in rows]
    only_paper = [k for k in in_paper if k not in in_json]
    only_json = [k for k in in_json if k not in in_paper]
    detail = (f"正文附录与 {MAPPING_JSON_NAME} 渲染出来的不一致："
              f"附录里 {len(in_paper)} 行、json 里 {len(in_json)} 行")
    if only_paper:
        detail += f"；只在附录里出现的：{[f'{k[0]} {k[1]}' for k in only_paper][:6]}"
    if only_json:
        detail += f"；只在 json 里出现的：{[f'{k[0]} {k[1]}' for k in only_json][:6]}"
    detail += "（附录由 `write_appendix` 从 json 重渲染一次，别手改）"
    return "mismatch", [_problem("mapping_paper_mismatch", detail, where=PC.TEX_NAME)]


def _orphan_problems(envs: Sequence[BodyEnv], rows: Sequence[Row]) -> list[dict[str, Any]]:
    """双向孤儿（正文有环境表里没有 / 表里有行正文没有 / 序号对不上 / 行重复）。"""
    problems: list[dict[str, Any]] = []
    body_by_key: dict[tuple[str, str], list[BodyEnv]] = {}
    for env in envs:
        body_by_key.setdefault((env.kind, env.label), []).append(env)
    env_by_key: dict[tuple[str, str], BodyEnv] = {}
    for key, got in body_by_key.items():
        kind, label = key
        if not label:
            for env in got:
                problems.append(_problem(
                    "mapping_orphan",
                    f"正文第 {env.line} 行的 {kind} 环境没有 \\label —— 没有 label 就无法在表里"
                    "指到它（先给它一个 label，再在表里登记一行）",
                    where=_env_where(env)))
            continue
        if len(got) > 1:
            problems.append(_problem(
                "mapping_orphan",
                f"正文里 label={label!r} 的 {kind} 出现了 {len(got)} 次"
                f"（第 {[e.line for e in got]} 行）—— 重复的 label 无法与表行一一对应",
                label=label, where=_env_where(got[0])))
            continue
        env_by_key[key] = got[0]

    rows_by_key: dict[tuple[str, str], list[Row]] = {}
    for row in rows:
        rows_by_key.setdefault((row.kind, row.label), []).append(row)
    for key, env in env_by_key.items():
        if key in rows_by_key:
            continue
        kind, label = key
        problems.append(_problem(
            "mapping_orphan",
            f"正文第 {env.line} 行的 {kind}（label={label!r}，第 {env.env_no} 个 {kind}）"
            "在表里没有对应行 —— 正文有、表里没有，就是一个孤儿环境",
            label=label, where=_env_where(env)))
    for key, got in rows_by_key.items():
        kind, label = key
        # 「被引、未印成环境」的行（`env_no=0`）不参加"环境↔行"这一轴：它们没有环境，
        # 由 `_citation_problems` 按「论文引了没有 / 表里有没有」双向判（criterion c）。
        kept = [row for row in got if not is_cited_only_row(row)]
        if not kept:
            continue
        got = kept
        env = env_by_key.get(key)
        if env is None:
            if not label:
                problems.append(_problem(
                    "mapping_orphan",
                    f"表里有 {len(got)} 行 {kind} 的 label 是空的 —— 空 label 在正文里指不到环境",
                    where=MAPPING_JSON_NAME))
            elif len(body_by_key.get(key) or ()) > 1:
                continue          # 正文那一侧已经报过"重复 label"，不再报一次
            else:
                problems.append(_problem(
                    "mapping_orphan",
                    f"表里的行 label={label!r}（{kind} 第 {got[0].env_no} 个）在正文里找不到"
                    f"对应环境（正文里共有 {len(envs)} 个环境）—— 表有、正文没有，就是孤儿行",
                    label=label, where=MAPPING_JSON_NAME))
            continue
        seen: dict[str, Row] = {}
        for row in got:
            if int(row.env_no) != int(env.env_no):
                problems.append(_problem(
                    "mapping_orphan",
                    f"表里 label={label!r} 那行写的是第 {row.env_no} 个 {kind}，"
                    f"而正文里它是第 {env.env_no} 个（正文第 {env.line} 行）—— "
                    "同一行对不上同一个环境",
                    label=label, where=_env_where(env)))
            prev = seen.get(row.ledger_id)
            if prev is not None:
                problems.append(_problem(
                    "mapping_orphan",
                    f"表里 label={label!r} 有两行的 `ledger_id` 都是 {row.ledger_id!r}"
                    "（第 {a} 个与第 {b} 个）—— 多证明那几行必须各指自己那一条"
                    "（`#p1` / `#p2` 不许互相顶替）".format(a=prev.env_no, b=row.env_no),
                    label=label, where=MAPPING_JSON_NAME))
            seen[row.ledger_id] = row
    return problems


def proposition_statement_ids(ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None
                              ) -> list[str]:
    """台账里算"命题"的那几条的 `stmt_id`（按台账里的顺序）。

    口径（业主 2026-10-24，D-40）：`kind` 不在 `NON_PROPOSITION_KINDS` 里就算命题 ——
    概念并进 `statements` 之后那一批 `kind="concept"` 的行是定义/记号，不是正文要
    对着写环境的命题；反过来，缺 `kind` 的旧行算命题（"没说"不许读成"不是"）。
    """
    out: list[str] = []
    for row in (ledger or {}).get("statements") or ():
        if not isinstance(row, Mapping):
            continue
        stmt_id = str(row.get("stmt_id") or "").strip()
        if not stmt_id:
            continue
        if str(row.get("kind") or "").strip().lower() in NON_PROPOSITION_KINDS:
            continue
        out.append(stmt_id)
    return out


def _statement_env_label(env: BodyEnv) -> str:
    """一个定理类环境在报信里的名字（没有 label 时退到位置）。"""
    return env.label or f"（无 label 的那个 {env.kind}，第 {env.line} 行）"


def _statement_surplus_problems(
        statement_envs: Sequence[BodyEnv], rows: Sequence[Row],
        ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """正文的定理类环境 vs 台账登记的命题：一条命题对一个环境（业主 2026-10-24，D-40）。

    逐环境按正文顺序认领一条还没被认领过的命题：那一行要按 `kind` + `label` 对上
    环境，`ledger_id` 要解析到 `statements`，而那一行还要算命题。认领不到的环境就是
    "正文多出来的" —— 三种来源报同一句话并逐个点名 label：

      - 对应表里没有这一行（正文有、表里没有）；
      - 那一行指的是台账里的概念/定义行（不是命题）；
      - 那一行压着的命题已经被前面某个环境用掉了（一条命题不许对两个环境）。

    返回 `(problems, 多出来的 label 清单)`。台账里一条 `statements` 行都没有时返回
    `([], [])`：那一档是"无从判起"（没读到台账，不是"正文多出来了"），把两者折平会让
    每一份夹具工作区都红；而"台账读得到、里面只有概念行"照判 —— 那种稿子确实一个
    命题都没登记，正文里的定理类环境全是多出来的。问题类别落在既有的
    `mapping_orphan` 上：它就是"孤儿"的另一半，只是这次判据从"表里有没有那一行"
    升级到"台账里有没有那一条命题"。
    """
    statements = [row for row in ((ledger or {}).get("statements") or ())
                  if isinstance(row, Mapping)]
    if not statements:
        return [], []
    propositions = proposition_statement_ids(ledger)
    prop_set = set(propositions)
    by_key: dict[tuple[str, str], list[str]] = {}
    mapped: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        resolved = resolve_ledger_id(row.ledger_id, ledger)
        if not resolved["ok"] or str(resolved.get("table") or "") != "statements":
            continue
        stmt_id = str(resolved.get("row_id") or "")
        key = (str(row.kind), str(row.label))
        mapped.setdefault(key, [])
        if stmt_id not in mapped[key]:
            mapped[key].append(stmt_id)
        if stmt_id in prop_set:
            by_key.setdefault(key, []).append(stmt_id)
    used: dict[str, BodyEnv] = {}
    extra: list[tuple[BodyEnv, str]] = []
    for env in statement_envs:
        key = (str(env.kind), str(env.label))
        candidates = by_key.get(key, ())
        take = next((sid for sid in candidates if sid not in used), "")
        if take:
            used[take] = env
            continue
        taken = [sid for sid in candidates if sid in used]
        if not mapped.get(key):
            why = "（对应表里没有这一行）"
        elif taken:
            why = ("（与 " + _statement_env_label(used[taken[0]])
                   + " 压在同一条命题 stmt:" + taken[0] + " 上）")
        else:
            why = ("（表里那一行指 stmt:" + mapped[key][0]
                   + "，而台账里那不是命题）")
        extra.append((env, why))
    if not extra:
        return [], []
    labels: list[str] = []
    named: list[str] = []
    for env, why in extra:
        label = _statement_env_label(env)
        labels.append(label)
        named.append(label + why)
    detail = (
        f"正文多出 {len(extra)} 个定理类环境，台账里没有对应命题："
        + "、".join(named)
        + f"（台账里算命题的是 {len(propositions)} 条："
        + "、".join(f"stmt:{sid}" for sid in propositions[:8])
        + ("等" if len(propositions) > 8 else "")
        + "）—— 正文的定理/引理/命题结构以 B 台账登记的命题为准：一条命题对一个环境，"
        "证明用那一行的 `proof_text`；L 的形式化产物只作「这一条命题的形式化已验证」的"
        "凭据，它内部的 lemma / step 不进正文目录、不拆成多个定理类环境（业主口径："
        "参照 L 会切割太细）。印成 Lemma 的自定义宏（例如 "
        "`\\newtheorem{claim}[theorem]{Lemma}`）同样算定理类环境，不能用它绕开这一条")
    return [_problem("mapping_orphan", detail, label=labels[0] if labels else "",
                     where=_env_where(extra[0][0]))], labels


def _row_checks(row: Row, ledger: Mapping[str, Sequence[Mapping[str, Any]]],
                package_root: Path, workspace: Path) -> _RowCheck:
    """一行的三条轴：台账代号码 / 证明号 / 文件（三条互不遮蔽：一条坏不影响别条被报）。

    `workspace` 是数值实验定理那一支要用的：它的证明栏是仓库内那份程序，
    不是论文包内的文件（口径见 `is_numeric_row`）。
    """
    got = _RowCheck()
    resolved = resolve_ledger_id(row.ledger_id, ledger)
    if not resolved["ok"]:
        got.add("mapping_unresolvable",
                f"表里 label={row.label!r}（{row.kind} 第 {row.env_no} 个）的 "
                f"`ledger_id` = {row.ledger_id!r} 在台账里解析不到：{resolved['reason']}",
                label=row.label, where=MAPPING_JSON_NAME)
    else:
        table, row_id = str(resolved["table"]), str(resolved["row_id"])
        target = ledger_row(ledger, table, row_id)
        got.ledger_row, got.proof_no = target, int(row.proof_no)
        tail_no = int(resolved["proof_no"])
        if row.proof_no != tail_no:
            got.add("mapping_unresolvable",
                    f"表里 label={row.label!r} 的 `ledger_id` 写的是第 {tail_no} 条证明"
                    f"（{row.ledger_id!r}），而 `proof_no` 写的是 {row.proof_no} —— "
                    "同一件事两处不一致",
                    label=row.label, where=MAPPING_JSON_NAME)
        if table != "statements":
            if row.proof_no != PL.DEFAULT_PROOF_NO:
                got.add("mapping_unresolvable",
                        f"表里 label={row.label!r} 的 `ledger_id` = {row.ledger_id!r} 指的不是 "
                        f"`statements`，却写了 `proof_no` = {row.proof_no} —— "
                        "证明号只对 `stmt:` 有意义",
                        label=row.label, where=MAPPING_JSON_NAME)
        else:
            known = proof_nos_for_statement(target)
            if int(row.proof_no) not in known:
                got.add("mapping_unresolvable",
                        f"表里 label={row.label!r} 的 `proof_no` = {row.proof_no}，"
                        f"而 `stmt:{row_id}` 的证明清单里只有 {known}（`proofs` 那一条）"
                        "—— 证明号必须能被台账解析到",
                        label=row.label, where=MAPPING_JSON_NAME)
    if is_cited_only_row(row):
        # 「被引、未印成环境」的行（`exp:` / `lit:`，`env_no=0`）：它们的 `file` 是仓库根
        # 相对的那个对象（程序 / 文献文件），不走论文包内文件那一支。
        if is_literature_row(row):
            got.problems.extend(_cited_literature_problems(row, ledger, workspace))
        else:
            got.problems.extend(_cited_experiment_problems(row, ledger, workspace))
        return got
    numeric = is_numeric_row(row, ledger)
    if numeric:
        # 数值实验定理那一行的证明栏是程序（相对仓库根），与论文包内那份 tex 是两回事：
        # 走同一张 `file_state` 会把 `code/…` 判成"指到包外"，于是每一条真的穷举证明都红。
        state = NT.program_state(workspace, row.file)
        if state["state"] != "present":
            got.add(NT.PROOF_PROGRAM_MISSING,
                    f"表里 label={row.label!r}（{row.kind} 第 {row.env_no} 个，数值实验定理）"
                    f"的证明栏（`file`）不过关：{state['reason']}",
                    label=row.label, where=MAPPING_JSON_NAME)
    elif not manuscript_required(row):
        # 定义行没有证明稿（2026-11-26 GMAP）：`file` 允许空。给了就照样核 ——
        # "不必填"不等于"填什么都行"，指到包外/读不到的文件仍是红的。
        if str(row.file or "").strip():
            state = file_state(package_root, row.file)
            if state["state"] in ("missing", "directory"):
                got.add("mapping_file_missing",
                        f"表里 label={row.label!r}（{row.kind} 第 {row.env_no} 个）的 `file` "
                        f"读不到：{state['reason']}（定义行不要求填它，填了就要指得到）",
                        label=row.label, where=MAPPING_JSON_NAME)
            elif state["state"] == "outside":
                got.add("mapping_unresolvable",
                        f"表里 label={row.label!r} 的 `file` 不合口径：{state['reason']}",
                        label=row.label, where=MAPPING_JSON_NAME)
    else:
        state = file_state(package_root, row.file)
        if state["state"] in ("missing", "directory"):
            got.add("mapping_file_missing",
                    f"表里 label={row.label!r}（{row.kind} 第 {row.env_no} 个）的 `file` "
                    f"读不到：{state['reason']}", label=row.label, where=MAPPING_JSON_NAME)
        elif state["state"] == "outside":
            got.add("mapping_unresolvable",
                    f"表里 label={row.label!r} 的 `file` 不合口径：{state['reason']}",
                    label=row.label, where=MAPPING_JSON_NAME)
    return got


def _cited_experiment_problems(row: Row,
                               ledger: Mapping[str, Sequence[Mapping[str, Any]]],
                               workspace: Path) -> list[dict[str, Any]]:
    """「被引、未印成环境」那一行的格：程序 / 读数 / 摘要必须与台账同一行一致且在盘上。

    三态：
    - `ledger_id` 在 `experiments` 里解析不到 ⇒ `mapping_unresolvable`（这一行指不到实验）；
    - 台账那一行没有 `code_path` ⇒ `mapping_file_missing`（没程序可指，不许拿别的顶）；
    - 程序不在 / `code_hash` / `result` / `params` / `artifact_paths` 与台账不一致 ⇒
      `mapping_file_missing`（表里那几格是 `fill_experiment_cells` 从台账抄的，抄错或被人
      手改都会在这里露出来）；
    - 每一份日志不在盘上 ⇒ `mapping_file_missing`（"多份逐份列"之后逐份都要在）。
    """
    out: list[dict[str, Any]] = []
    resolved = resolve_ledger_id(row.ledger_id, ledger)
    if not resolved["ok"] or str(resolved.get("table") or "") != "experiments":
        out.append(_problem(
            "mapping_unresolvable",
            f"表里实验行 label={row.label!r} 的 `ledger_id` = {row.ledger_id!r} 在台账里"
            f"解析不到：{resolved.get('reason')}",
            label=row.label, where=MAPPING_JSON_NAME))
        return out
    target = ledger_row(ledger, "experiments", str(resolved["row_id"]))
    want = experiment_cells_for_row(target)
    if not want:
        out.append(_problem(
            EXPERIMENT_FILE_MISSING,
            f"表里实验行 label={row.label!r} 指到 experiments#{resolved['row_id']}，"
            "而台账那一行没有 `code_path` ⇒ 没有程序文件可指（这一行的 `file` 拿不到）",
            label=row.label, where=MAPPING_JSON_NAME))
        return out
    state = NT.program_state(workspace, row.file)
    if state["state"] != "present":
        out.append(_problem(
            EXPERIMENT_FILE_MISSING,
            f"表里实验行 label={row.label!r} 的 `file`（= `experiments.code_path`）不过关："
            f"{state['reason']}",
            label=row.label, where=MAPPING_JSON_NAME))
    got = {
        EXPERIMENT_CODE_HASH_FIELD: str(row.experiment_code_hash or "").strip(),
        EXPERIMENT_RESULT_FIELD: str(row.experiment_result or "").strip(),
        EXPERIMENT_NEGATION_FIELD: str(row.experiment_negation_kind or "").strip(),
        EXPERIMENT_PARAMS_FIELD: str(row.experiment_params or "").strip(),
        EXPERIMENT_EXIT_FIELD: row.experiment_exit_code,
        EXPERIMENT_LOGS_FIELD: tuple(row.experiment_logs or ()),
    }
    for name in (EXPERIMENT_CODE_HASH_FIELD, EXPERIMENT_RESULT_FIELD,
                 EXPERIMENT_NEGATION_FIELD, EXPERIMENT_PARAMS_FIELD, EXPERIMENT_EXIT_FIELD):
        if got[name] != want[name]:
            out.append(_problem(
                EXPERIMENT_FILE_MISSING,
                f"表里实验行 label={row.label!r} 的 `{name}` = {got[name]!r}，而台账 "
                f"experiments#{resolved['row_id']} 那一格是 {want[name]!r} —— "
                "这几格由 `fill_experiment_cells` 从台账现读现填，对不上就是被手改过；"
                "重跑 `doc.write_mapping` 会按台账盖回去",
                label=row.label, where=MAPPING_JSON_NAME))
    if got[EXPERIMENT_LOGS_FIELD] != want[EXPERIMENT_LOGS_FIELD]:
        out.append(_problem(
            EXPERIMENT_FILE_MISSING,
            f"表里实验行 label={row.label!r} 的 `{EXPERIMENT_LOGS_FIELD}` = "
            f"{list(got[EXPERIMENT_LOGS_FIELD])!r}，而台账那一行是 "
            f"{list(want[EXPERIMENT_LOGS_FIELD])!r} —— 读数日志必须逐份照台账原样列",
            label=row.label, where=MAPPING_JSON_NAME))
    for rel in row.experiment_logs or ():
        log_state = _repo_rel_state(workspace, rel)
        if log_state["state"] != "present":
            out.append(_problem(
                EXPERIMENT_FILE_MISSING,
                f"表里实验行 label={row.label!r} 的读数日志读不到：{log_state['reason']}",
                label=row.label, where=MAPPING_JSON_NAME))
    return out


def _cited_literature_problems(row: Row,
                               ledger: Mapping[str, Sequence[Mapping[str, Any]]],
                               workspace: Path) -> list[dict[str, Any]]:
    """「被引、未印成环境」的文献行：`file` 必须就是台账那一行指的那份文献文件。

    判据只有两条（都是可复算的客观事实，不读模型）：

    - `ledger_id` 在 `literature` 里解析不到 ⇒ `mapping_unresolvable`（这一行指不到文献）；
    - 台账那一行没有 `path` ⇒ `mapping_file_missing`（没文件可指，不许拿别的顶）；
    - 表里的 `file` 与台账 `path` 不是同一份（`norm_rel` 比），或那份文件不在盘上
      ⇒ `mapping_file_missing`。

    文献文件相对 `library/`（`literature[].path` 的唯一读侧口径是
    `litread.resolve_literature_path`，与 `store.library_path` 同一套形状判据）：本函数
    只借它解析，不另拼一次 `library/` 前缀 —— 两处各拼一次就会在"带不带前缀 / 旧两位号"
    上漂开，而漂开的那天同一份文献一条读得通、一条判红。
    """
    from . import litread as LR

    out: list[dict[str, Any]] = []
    resolved = resolve_ledger_id(row.ledger_id, ledger)
    if not resolved["ok"] or str(resolved.get("table") or "") != "literature":
        out.append(_problem(
            "mapping_unresolvable",
            f"表里文献行 label={row.label!r} 的 `ledger_id` = {row.ledger_id!r} 在台账里"
            f"解析不到：{resolved.get('reason')}",
            label=row.label, where=MAPPING_JSON_NAME))
        return out
    target = ledger_row(ledger, "literature", str(resolved["row_id"]))
    want = NP.norm_rel((target or {}).get("path"))
    if not want:
        out.append(_problem(
            "mapping_file_missing",
            f"表里文献行 label={row.label!r} 指到 literature#{resolved['row_id']}，"
            "而台账那一行没有 `path` ⇒ 没有文献文件可指（这一行的 `file` 拿不到）",
            label=row.label, where=MAPPING_JSON_NAME))
        return out
    given = NP.norm_rel(row.file)
    if given != want:
        out.append(_problem(
            "mapping_file_missing",
            f"表里文献行 label={row.label!r} 的 `file` = {row.file!r}，而台账 "
            f"literature#{resolved['row_id']} 那一行指的是 {want!r} —— "
            "这两处说的必须是同一份文件（第三列要指得到真实的来源）",
            label=row.label, where=MAPPING_JSON_NAME))
        return out
    got = LR.resolve_literature_path(workspace, workspace / "library", given)
    if got.path is None or not Path(str(got.path)).is_file():
        out.append(_problem(
            "mapping_file_missing",
            f"表里文献行 label={row.label!r} 的 `file`（= 台账 `path`）在 `library/` 下"
            f"读不到：{got.reason or '没有这个文件'}",
            label=row.label, where=MAPPING_JSON_NAME))
    return out


def _experiment_coverage(rows: Sequence[Row],
                         ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None
                         ) -> set[str]:
    """表里已经"带上了"哪些实验号（两种带上法，二者都算）。

    - 有一条 `exp:` 行（`experiment_id_of_row`）；
    - 或者某行的 `numeric_evidence` 就是 `exp:<号>`（数值实验定理那一行，它的程序与读数
      已经在 `file` / `exhaustion_note` / 索引四格里）。

    第二种是刻意的：`test_numeric_theorem_writing_spec` 那一类论文在正文里写 `exp:000000`
    压的是数值定理的穷举读数，它不该再被补成一条独立的实验行（那一行本来就有文件）。
    """
    out: set[str] = set()
    experiments = [row for row in ((ledger or {}).get("experiments") or ())
                   if isinstance(row, Mapping)]
    by_code: dict[str, str] = {}
    for experiment in experiments:
        code = NP.norm_rel(experiment.get("code_path"))
        eid = str(experiment.get("experiment_id") or "").strip()
        if code and eid:
            by_code.setdefault(code, eid)
    for row in rows:
        if is_experiment_row(row):
            out.add(experiment_id_of_row(row))
        evidence = str(getattr(row, NT.EVIDENCE_FIELD, "") or "").strip()
        if evidence.startswith(EXPERIMENT_ID_PREFIX):
            out.add(evidence[len(EXPERIMENT_ID_PREFIX):].split("#", 1)[0].strip())
        # 第三种带上法：这一行的 `file` 就是那条实验的程序（数值定理行 / 例子行的
        # 既有约定：证明栏第 ① 段是程序）。此时"实验的文件名"已经在表里了，不再补一行。
        covered = by_code.get(NP.norm_rel(getattr(row, "file", "")))
        if covered:
            out.add(covered)
    return {eid for eid in out if eid}


def _paper_citation_problems(rows: Sequence[Row],
                       citations: Sequence[Mapping[str, str]],
                       ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None,
                       workspace: Path,
                       envs: Sequence[BodyEnv]) -> list[dict[str, Any]]:
    """论文写到的 `stmt:` / `exp:` 与表里那几行双向对账（2026-11-25，MAPPING-COMPLETE）。

    这一轴此前完全没有判据：原有的一条只问「正文环境 ↔ 表行」（`_orphan_problems`），
    于是"论文在附录段落里引了 `exp:000003`、表里一行都没有"这种事一路静默。

    三个方向（与业主 2026-11-25 的口径逐条对应）：

    a. 论文引的每个 `stmt:` 都要有一行（行指到那条命题）；
    b. 论文引的每个 `exp:` 都要在表里带上（`exp:` 行，或数值定理行的 `numeric_evidence`）；
    c. 表里的实验行都要被论文写过（或本来就是印在正文里的 `experiment` 环境）。

    三态：`stmt:` 引了而台账里没有这条命题 ⇒ `mapping_unresolvable`（引用的东西不存在，
    不是"表漏了一行"）；`exp:` 引了而台账里没有这条实验 ⇒ 同样是 `mapping_unresolvable`。
    """
    out: list[dict[str, Any]] = []
    exp_ids = {str(item["code"]).strip() for item in citations if item["prefix"] == "exp"}
    stmt_ids = {str(item["code"]).strip() for item in citations if item["prefix"] == "stmt"}
    known_statements = ledger_ids(ledger, "statements")
    known_experiments = ledger_ids(ledger, "experiments")
    row_statements: dict[str, Row] = {}
    for row in rows:
        resolved = resolve_ledger_id(row.ledger_id, ledger)
        if resolved["ok"] and str(resolved.get("table") or "") == "statements":
            row_statements.setdefault(str(resolved["row_id"]), row)
    covered_experiments = _experiment_coverage(rows, ledger)
    env_keys = {(str(env.kind), str(env.label)) for env in envs}
    for sid in sorted(stmt_ids):
        if sid in row_statements:
            continue
        if sid not in known_statements:
            out.append(_problem(
                "mapping_unresolvable",
                f"论文引了 `stmt:{sid}`，而台账 `statements` 里没有这条命题（引用悬空）—— "
                "表里当然也就没有行可指；先让 B 登记这条命题或改掉正文那个号",
                label=f"stmt:{sid}", where=MAPPING_JSON_NAME))
            continue
        out.append(_problem(
            "mapping_orphan",
            f"论文引了 `stmt:{sid}`（`documents.claims[].citations` 或正文源里写着），"
            "而表里没有一行指到它 —— 论文里写了的命题，表里必须有一行给出它的证明稿文件名",
            label=f"stmt:{sid}", where=MAPPING_JSON_NAME))
    for eid in sorted(exp_ids):
        if eid in covered_experiments:
            continue
        if eid not in known_experiments:
            out.append(_problem(
                "mapping_unresolvable",
                f"论文引了 `exp:{eid}`，而台账 `experiments` 里没有这条实验（引用悬空）—— "
                "表里也就没有文件可指",
                label=f"exp:{eid}", where=MAPPING_JSON_NAME))
            continue
        out.append(_problem(
            "mapping_orphan",
            f"论文引了 `exp:{eid}`，而表里没有带上它（既没有 `exp:{eid}` 行，也没有哪一行"
            "的 `numeric_evidence` 等于它）—— 论文里写了的实验，表里必须给出它的程序与读数"
            "文件名",
            label=f"exp:{eid}", where=MAPPING_JSON_NAME))
    for row in rows:
        if not is_experiment_row(row):
            continue
        eid = experiment_id_of_row(row)
        if eid in exp_ids or (str(row.kind), str(row.label)) in env_keys:
            continue
        out.append(_problem(
            "mapping_orphan",
            f"表里实验行 label={row.label!r} 在论文两处（`documents.claims[].citations`、"
            "正文源）都找不到 `exp:` 引用，也不是正文里印出来的 `experiment` 环境 —— "
            "表有、论文没写，就是孤儿行",
            label=row.label, where=MAPPING_JSON_NAME))
    return out


def _literature_problems(citations: Sequence[Mapping[str, str]],
                         workspace: Path) -> list[dict[str, Any]]:
    """论文引的每个 `lit:` 都要解析到一条 `literature` 行（并在盘上取得到那份文件）。

    只做"能解析到 lit_id"这一件事：文献号 ↔ `library/<6位号>/<名>` 的对应仍归 A 的文献表
    （`literature.path`），解析走 `litread.resolve_literature_path` —— 它同时认现行
    `<6位号>/<名>` 与历史形态，于是 LIB-LAYOUT 迁移中间态不会把这条判据变成假红。
    """
    out: list[dict[str, Any]] = []
    wanted = [item for item in citations if item["prefix"] == "lit"]
    if not wanted:
        return out
    rows = {str(row.get("lit_id") or "").strip(): row
            for row in read_literature_rows(workspace) if isinstance(row, Mapping)}
    from . import litread as LR   # 惰性：文献落点解析只在有 lit: 引用时需要
    library = Path(workspace) / "library"
    for item in wanted:
        lid = str(item["code"]).strip()
        row = rows.get(lid)
        if row is None:
            out.append(_problem(
                "mapping_citation_file_missing",
                f"论文引了 `lit:{lid}`，而台账 `literature` 里没有这个文献号（引用悬空）",
                label=f"lit:{lid}", where=MAPPING_JSON_NAME))
            continue
        rel = str(row.get("path") or "").strip()
        if not rel:
            out.append(_problem(
                "mapping_citation_file_missing",
                f"论文引了 `lit:{lid}`，而文献表那一行的 `path` 是空的 ⇒ 落不到 "
                "`library/<6位号>/<名>` 上（这条文献还没有可读的文件）",
                label=f"lit:{lid}", where=MAPPING_JSON_NAME))
            continue
        resolved = LR.resolve_literature_path(workspace, library, rel)
        target = getattr(resolved, "path", None)
        if not target or not Path(target).is_file():
            out.append(_problem(
                "mapping_citation_file_missing",
                f"论文引了 `lit:{lid}`，文献表的 `path` = {rel!r} 解析不到盘上的文件："
                f"{getattr(resolved, 'reason', '') or '盘上没有这份文件'}",
                label=f"lit:{lid}", where=MAPPING_JSON_NAME))
    return out


def statement_by_id(ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None,
                    statement_id: Any) -> Mapping[str, Any] | None:
    """按编号取一条 `statements` 行 —— 唯一读口 `statementledger.by_id`。

    G 侧那张表的第一跳必须走这一处（业主 2026-11-26：「需要告知 G 侧那条 lane 要从
    哪里读命题证明稿的路径」）：编号是确定性事实，命中就是那一行，0 命中就是"没有这一行"；
    三态（`checked` / `found`）由 `by_id` 给，不在这里折平。`rows` 由调用方现读的台账给，
    免得每一跳再读一次盘。
    """
    from . import statementledger as SL   # 惰性：只在这一跳用到

    rows = [row for row in ((ledger or {}).get("statements") or ())
            if isinstance(row, Mapping)]
    got = SL.by_id(rows=rows, stmt_id=statement_id)
    if not got.get("checked") or not got.get("found"):
        return None
    row = got.get("row")
    return dict(row) if isinstance(row, Mapping) else None




def load_bearing_evidence_required(
        row: Row,
        ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None,
        experiments: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """这一条承重行有没有「它自己的证明稿与签」这项义务（三态读数）。

    判"要不要"只问一件事：`is_load_bearing_row(row)`。这条义务与 `origin` /
    `proof_source` / V 签没签都无关（业主 2026-11-26：论文里的承重命题必须有它自己的
    证明稿与签，与来源无关）。

    四道边界（都不是"来源"轴，且每一道都写进读数）：

    1. 非承重行 ⇒ 不适用（例子 / 实验 / 被引未印的实验行）；
    2. 台账那一行解析不到 ⇒ `checked=False`（"没查成"，由 `mapping_unresolvable` 另一条
       报红；这里不重复判，也不静默当"不用"）；
    3. 证明通道非空（数值证明 / 形式化）⇒ 不适用这一档：它的"证明稿"是 E 的报告 /
       `.lean` 程序，证据义务由凭据格那一族（`_lean_problems` / `_numeric_problems` /
       收工门的 `_numeric_row_index_problems`）判 —— 两处不许对同一条命题各要一份稿；
    4. 台账那一行连 `kind` 都没写（`未读到`）⇒ `checked=False`：这一行是不是命题台账
       自己都没回答，"承重"这一问缺一个前提（读数进 `mapping_reading` 的
       `load_bearing.unreadable`，不许折成"不用"）。
    """
    out: dict[str, Any] = {"required": False, "checked": True, "channel": "", "reason": ""}
    if not is_load_bearing_row(row):
        out["reason"] = "这一行不是承重命题（正文里不是定理类环境）⇒ 没有这项义务"
        return out
    resolved = resolve_ledger_id(row.ledger_id, ledger)
    if not resolved["ok"] or str(resolved.get("table") or "") != "statements":
        out.update(checked=False,
                   reason=(f"台账那一行解析不到（{resolved.get('reason') or '不是 statements 行'}）"
                           "⇒ 承重证据这项义务判不了（不是「不用」）"))
        return out
    target = statement_by_id(ledger, str(resolved["row_id"]))
    if not isinstance(target, Mapping):
        out.update(checked=False, reason="台账里没有这一行 ⇒ 承重证据判不了（不是「不用」）")
        return out
    try:
        if experiments is None:
            experiments = [dict(item) for item in (ledger or {}).get("experiments") or ()
                            if isinstance(item, Mapping)]
        slot = _credential_slot(row, ledger, experiments)
        channel = str(slot.get("channel") or "")
    except Exception:  # noqa: BLE001 —— 通道读不出来 ⇒ 按"有没有这些格"的旧口径走
        channel = ""
    out["channel"] = channel
    if channel:
        out["reason"] = (f"这一行的证明通道是 {channel!r} ⇒ 证据在 E 的报告 / `.lean` 程序上，"
                         "由凭据格那一族判，不在「手稿稿与签」这一档")
        return out
    kind = ledger_kind_cell(target)
    if not kind or kind == LEDGER_CELL_UNREADABLE:
        out.update(checked=False,
                   reason=("台账那一行没有可读的 `kind` ⇒ 这一行算不算命题台账没回答，"
                           "承重证据这项义务判不了（不是「不用」）"))
        return out
    out.update(required=True,
               reason=(f"论文里印成 {row.kind!r}、台账 `{row.ledger_id}` 的 kind = {kind!r}"
                       " ⇒ 这一条承重命题必须有属于它自己的证明稿与 V 签"))
    return out


def _proof_index_problems(rows: Sequence[Row],
                          gaps: Mapping[str, Any],
                          ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None,
                          workspace: Path) -> list[dict[str, Any]]:
    """承重行的「稿 / 签」两态必须真的对得上（门那一支）。

    这一支不另判一次：它消费的是 G 侧那张表 `load_bearing_gaps`（同一份读数），
    把每一行的 `missing`（`稿` / `签`）折成拦门的问题。2026-11-25 / 26 的缺口正是
    "门与 G 各写一份承重定义"：旧闸只对 `proof_source == own` 且 `reviewed == 已签` 的行
    核四格，于是真机 sunflower-digest-2 的 `prop:block` / `thm:erdos-rado`
    （`proof_source=citation`、`reviewed=未审`）被整行跳过 —— `mapping_reading` 判 pass、
    收工门 8/8。

    判据只有两问（业主 2026-11-26 更正）：
    ① 台账里这条命题有没有指向一份证明稿、那份稿在不在盘上；② 那一份有没有 V 的签。
    不把稿的正文 sha 变了判成红（稿号与命题号不同轴；B 二阶段会洗正文并重签）。

    问题类别（都在 `EVIDENCE_KINDS` 里，`agent_h.mapping_judge` 一律按 blocker）：

    - `mapping_proof_file_missing`：台账记了稿而表里没填 / 指到另一份稿（修法不同）；
    - `mapping_load_bearing_evidence_missing`：连稿都没有（台账没记，或记的那份取不到）；
    - `mapping_load_bearing_unsigned`：稿在而没有 V 签。

    三态：`gaps["unreadable"]` 的行不在这里折成红（"没查成"不是"缺"），它们在
    `mapping_reading` 的 `load_bearing.unreadable` 里可见；台账解析不到的行由
    `_row_checks` 的 `mapping_unresolvable` 报红，不在这一支重复。
    """
    out: list[dict[str, Any]] = []
    by_sid: dict[str, Mapping[str, Any]] = {}
    for one in gaps.get("gaps") or ():
        by_sid[str(one.get("stmt_id") or "")] = one
    for row in rows:
        if not is_load_bearing_row(row):
            continue
        resolved = resolve_ledger_id(row.ledger_id, ledger)
        if not resolved["ok"] or str(resolved.get("table") or "") != "statements":
            continue
        sid = str(resolved["row_id"])
        one = by_sid.get(sid)
        if one is not None:
            missing = [str(x) for x in (one.get("missing") or [])]
            label = str(row.label)
            if "稿" in missing:
                table_path = str(one.get("table_path") or "").strip()
                rels = {NP.norm_rel(p.get("manuscript")) for p in (one.get("paths") or ())
                        if str(p.get("manuscript") or "").strip()}
                if table_path and rels and NP.norm_rel(table_path) not in rels:
                    out.append(_problem(
                        PROOF_FILE_MISSING,
                        f"表里 label={label!r} 的 `{NP.INDEX_PATH_FIELD}` = {table_path!r}，"
                        "而台账那一行这一条命题的稿是 "
                        + "、".join(repr(x) for x in sorted(rels))
                        + " —— 表指到了另一份稿",
                        label=label, where=MAPPING_JSON_NAME))
                else:
                    out.append(_problem(
                        LOAD_BEARING_EVIDENCE_MISSING,
                        f"论文里 label={label!r} 是承重命题（正文里印成定理类环境），而它"
                        f"没有可用的证明稿：{one.get('why') or '台账没有这一条命题的稿记录'}"
                        " —— 承重命题必须有至少一条路径的证明稿在盘上",
                        label=label, where=MAPPING_JSON_NAME))
            if "签" in missing:
                out.append(_problem(
                    LOAD_BEARING_UNSIGNED,
                    f"论文里 label={label!r} 是承重命题，稿在，而这一条没有 V 的签"
                    f"（`reviewed` = {str(one.get('reviewed') or row.reviewed or '未读到')!r}）"
                    " —— 承重命题必须有它自己的证明稿与签；签还没下来之前它不许被当成"
                    "已成立的结论",
                    label=label, where=MAPPING_JSON_NAME))
            continue
        # gaps 里没有这一行：稿与签都齐（或通道非空）。
        want = load_bearing_evidence_required(row, ledger)
        if not want.get("checked") or not want.get("required"):
            # 通道非空的行：数值档沿用 B 入库闸同一个判据（E 的报告 + 程序 + 签）。
            try:
                numeric = (str(want.get("channel") or "") == NP.PROOF_CHANNEL_NUMERIC
                           and is_numeric_theorem_row(row, ledger))
            except Exception:  # noqa: BLE001 —— 通道读不出来 ⇒ 不重复判
                numeric = False
            if numeric:
                why = NT.evidence_index_problems(row=row.to_dict(), workspace_root=workspace)
                if why:
                    out.append(_problem(
                        PROOF_FILE_MISSING,
                        f"表里 label={row.label!r}（数值实验定理）的证据索引不过关："
                        + "；".join(why),
                        label=row.label, where=MAPPING_JSON_NAME))
            continue
        # 稿与签都齐：只剩"表里填的是不是台账那一份"这一格（记了没填 / 指到另一份）。
        table_path = str(row.evidence_path or "").strip()
        target = statement_by_id(ledger, sid)
        if not isinstance(target, Mapping):
            continue
        reading = manuscript_paths_reading(
            target, workspace,
            review_ledger=reviewed_ledger_state(workspace, sid))
        if not reading.get("checked"):
            continue
        rels = {NP.norm_rel(p.get("manuscript")) for p in (reading.get("paths") or ())
                if str(p.get("manuscript") or "").strip()}
        if not rels:
            continue
        if not table_path or NP.norm_rel(table_path) not in rels:
            out.append(_problem(
                PROOF_FILE_MISSING,
                f"表里 label={row.label!r} 的 `{NP.INDEX_PATH_FIELD}` = {table_path!r}，"
                "而台账那一行这一条命题的稿是 "
                + "、".join(repr(x) for x in sorted(rels)) + " —— "
                + ("记了稿却没填（重跑一次 `doc.write_mapping`）" if not table_path
                   else "表指到了另一份稿"),
                label=row.label, where=MAPPING_JSON_NAME))
    return out


def is_numeric_row(row: Row,
                   ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None,
                   experiments: Sequence[Mapping[str, Any]] | None = None) -> bool:
    """这一行算不算数值实验定理 —— 只按证明通道判，`kind` 不参与。

    判法只有一处：:func:`_numeric_row_reading`（通道的真身是
    `numericproof.proof_channel`；通道判不出来时用 E-1 的"证明栏是不是程序"兜底）。
    为什么两条旧口径不能留：

    - 旧口径有"`kind` 必须在 `LEAN_TARGETED_KINDS` 里"这一道门。于是 `kind="example"`
      而台账里那条命题的证明栏是程序（`proof_channel == numeric`）时，收工门读数按通道
      要 `numeric_evidence` / `exhaustion_note` / 索引四格（`complete=0`），而这里被
      kind 门挡住 ⇒ `mapping_reading` 报 `pass`：同一张表两个答案（缝隙一）。
      现在 `kind` 一格都不参与 —— 一条命题的证明走哪条通道，与它在正文里排成哪类环境无关。
    - 旧口径有"这一行自己填了 `numeric_evidence` / `exhaustion_note` 就算数值定理"。
      那会把空通道的自称读成判据：现在空通道而填了那两格是"两边不一致"，由
      `_lean_problems` 第 6 条报 `mapping_numeric_evidence_missing`（缝隙二）。

    `ledger` 是整张台账（要读 `experiments` 判 E 签的穷举）；`experiments` 不给就从
    `ledger` 现取。

    它只管「凭据那一格与 `file` 走哪一类」：数值那一档要再带 `numeric_evidence` /
    `exhaustion_note` / 索引四格的那几行由 :func:`is_numeric_theorem_row` 判（`kind` 决定
    档位）—— 本函数对六类环境一视同仁，不因 `kind` 是 example /
    experiment 就把按通道填好的 `.py` 判成「凭据不够」。凭据格对这一档的认法（例子 / 实验
    的证明栏第 ① 段是程序时，那份 `.py` 就是凭据）在 `_lean_problems` 第 7 条。
    """
    return bool(_numeric_row_reading(row, ledger, experiments)["numeric"])


def is_numeric_theorem_row(row: Row,
                           ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None,
                           experiments: Sequence[Mapping[str, Any]] | None = None) -> bool:
    """这一行要不要「数值实验定理」那几格附加义务 —— 通道优先，`kind` 只决定档位。

    误拦的形态：`kind="example"` / `"experiment"` 的行按数值通道填了
    `lean_file`（= 证明栏第 ① 段那份 `.py`），读数却还要 `numeric_evidence` /
    `exhaustion_note` / 索引四格，于是被判成「凭据不够」。修法是把两件事拆开：

    - 凭据格按通道判（`:func:`is_numeric_row` + `_lean_problems` + `credential_fields`
      那一支，六类环境一视同仁）：证明栏是程序 ⇒ `lean_file` 填那份程序就齐，与正文里
      排成哪类环境无关；
    - 附加义务按档位判（本函数）：`numeric_evidence` / `exhaustion_note` / 索引四格 /
      正文指回 E 这几格问的是「这条定理压在哪条 E 的穷举读数上」—— 只有
      `STATEMENT_ENV_KINDS`（theorem / lemma / proposition / corollary）那几行才有这一问；
      例子与实验不是被证明的命题（`STATEMENT_ENV_KINDS` 的 docstring 已经这么说），
      它们没有这一档。

    这不退回那道 kind 门：那道门问的是「这一行算不算数值行」，
    `file` 与凭据格都跟着 `kind` 走（例子行按通道填的 `.py` 反而被判凭据不够）；
    这里的门只问「要不要再要那四格附加义务」，凭据格仍按通道 —— 例子 / 实验的证明栏
    第 ① 段是程序时，那份 `.py` 在 `_lean_problems` 第 7 条里认（连 E 还没签成穷举时也认）。
    """
    if str(row.kind or "").strip() not in STATEMENT_ENV_KINDS:
        return False
    return is_numeric_row(row, ledger, experiments)


def _numeric_problems(row: Row, ledger_row: Mapping[str, Any] | None,
                      ledger: Mapping[str, Sequence[Mapping[str, Any]]],
                      workspace: Path, segments: Mapping[str, str]) -> list[dict[str, Any]]:
    """数值实验定理那一条的逐格判据（空清单 = 三块齐全、指得回 E、正文也指得回）。

    五档一一对应业主那三块与"作者是 E"：证明栏是程序（`mapping_proof_program_missing`）、
    那条读数确实是 E 签的穷举（`mapping_proof_program_unbacked`）、E 的读数编号在
    （`mapping_numeric_evidence_missing`）、两块读数与署名在（`mapping_exhaustion_note_missing`）、
    正文那一段指得回（`mapping_numeric_citation_missing`）。
    """
    out: list[dict[str, Any]] = []
    label, where = row.label, MAPPING_JSON_NAME

    def add(kind: str, detail: str) -> None:
        out.append(_problem(kind, detail, label=label, where=where))

    # ① 程序相对地址：证明栏就是那份程序，且盘上真的有它。
    state = NT.program_state(workspace, row.file)
    if state["state"] != "present":
        add(NT.PROOF_PROGRAM_MISSING,
            f"表里 label={label!r}（数值实验定理）的证明栏（`file`）不过关：{state['reason']}"
            f" —— 这一行的证明栏要写程序的相对路径（相对仓库根），像 `code/r34_check.py`")
        return out

    # 那条 E 的读数：编号必须给、必须在台账里、必须与这份程序是同一件事。
    want = str(row.numeric_evidence or "").strip()
    if not want:
        add(NT.NUMERIC_EVIDENCE_MISSING,
            f"表里 label={label!r} 缺 `{NT.EVIDENCE_FIELD}`：这条定理压在哪一条 E 的穷举读数上"
            f"（`{NT.EVIDENCE_PREFIX}NNNNNN`）必须写出来 —— 业主口径里正文要标出它来自 E 的那条读数")
        return out
    experiments = [dict(r) for r in (ledger.get("experiments") or ())
                   if isinstance(r, Mapping)]
    found = next((dict(r) for r in experiments
                  if NT.evidence_id_of(r) == want), None)
    if found is None:
        add(NT.NUMERIC_EVIDENCE_MISSING,
            f"表里 label={label!r} 的 `{NT.EVIDENCE_FIELD}` = {want!r} 在台账里没有这一行实验")
        return out
    if not NP.is_signed_exhaustion(found):
        reasons = NP.exhaustion_problems(
            method=found.get("method"),
            observations=found.get("observations"),
            certificate=found.get("certificate"),
            search_bound=found.get("search_bound"),
            code_path=found.get("code_path"),
            result=found.get("result"))
        add(NT.PROOF_PROGRAM_UNBACKED,
            f"表里 label={label!r} 的读数 {want} 不是 E 签的穷举证明"
            f"（method={found.get('method')!r}，evidence_kind={found.get('evidence_kind')!r}，"
            f"签名的证明理由={NP.signature_of(found).get('proof_reason')!r}）："
            f"{'；'.join(reasons) if reasons else '签名或证明理由不齐'}"
            f" ⇒ 这一条只能记成「{NT.SUPPORTED_ONLY_WORD}」，不许写成定理 / 已证明")
        return out
    # 程序路径住在实验行的 `code_path`（2026-11-08：证明栏只剩 ③ 穷举论证）。
    script = NP.norm_rel(found.get("code_path"))
    if NP.norm_rel(script) != NP.norm_rel(row.file):
        add(NT.NUMERIC_EVIDENCE_MISSING,
            f"表里 label={label!r} 的 `{NT.EVIDENCE_FIELD}` = {want} 那一段的程序是 "
            f"{script!r}（`exp:{NT.evidence_id_of(found)}` 的 `code_path`），而证明栏写的是 "
            f"{row.file!r} —— 同一条定理的证明栏只能指一份程序")
        return out

    # 落库那一份证明栏（`statements.proof_text`）就是这条定理的证明栏：它必须与 E 的
    # ③ 逐字相同（缺了 / 改写了 ⇒ 它还不算证明 —— 只能记成"有数值实验支持"）。
    if isinstance(ledger_row, Mapping):
        column_problems = NT.proof_column_problems(
            ledger_row.get("proof_text"), code_path=found.get("code_path"))
        for detail in column_problems:
            add(NT.EXHAUSTION_NOTE_MISSING,
                f"表里 label={label!r} 落库那份证明栏（`{row.ledger_id}`）{detail}"
                f" —— ③ 齐、程序在 `code_path`，才叫证明栏；③ 由 E 写，G 原样引用")
        registered = NP.norm_text(ledger_row.get("proof_text"))
        if registered and registered != NP.norm_text(NP.proof_column(found)):
            add(NT.EXHAUSTION_NOTE_MISSING,
                f"表里 label={label!r} 落库那份证明栏与 E 的 ③ 不是同一份"
                f"（`{row.ledger_id}` 与 `exp:{NT.evidence_id_of(found)}` 的签名）——"
                "B 只负责原样登记 E 的读数，改写成自己的话就不算同一份")

    # ②③ 两块读数 + 署名 + 读数编号：E 写的那一份落点必须读得到、且三块齐。
    expected = NT.note_relpath(found)
    if expected and NP.norm_rel(row.exhaustion_note) != expected:
        add(NT.EXHAUSTION_NOTE_MISSING,
            f"表里 label={label!r} 的 `{NT.NOTE_FIELD}` 写的是 "
            f"{str(row.exhaustion_note or '').strip()!r}，而 E 那条读数（{want}）的落点是 "
            f"{expected!r} —— 两块读数的落点只有一处（`exhaustionreport.report_relpath`），"
            "G 不许另挑一个地方说「E 写在那」")
    note_problems = NT.corpus_problems(note=row.exhaustion_note, workspace_root=workspace,
                                       evidence_id=want)
    for detail in note_problems:
        add(NT.EXHAUSTION_NOTE_MISSING, f"表里 label={label!r}：{detail}")

    # ---- 索引四格（D-34）：这一行还要当"目录"用 —— 指得到正文（E 的报告）、
    # 说得出它的字节指纹、并带上 V 签那一格的 sha。判据本体在
    # `numerictheorem.evidence_index_problems`（它再转发 `numericproof.resolve_index`），
    # 于是"顺索引取对象"这条口径与 B 的入库闸是同一个实现：不会出现
    # "B 认、G/H 不认"的分家。问题落进既有五档里最贴的那一档（缺 E 的读数那一格）。
    for detail in NT.evidence_index_problems(row=row.to_dict(), workspace_root=workspace):
        add(NT.NUMERIC_EVIDENCE_MISSING, f"表里 label={label!r}：{detail}")

    # 正文那一段要指回 E 的读数（整份正文搜一遍不算：那段话必须是这一条的）。
    segment = segments.get(label)
    if segment is None:
        add(NT.NUMERIC_CITATION_MISSING,
            f"表里 label={label!r} 在正文里找不到那个环境（这一行的正文那一段无从核对）—— "
            "先把正文里那一条定理写出来，再回头核这一格")
    elif not NT.citation_present(segment, program=row.file, evidence_id=want):
        add(NT.NUMERIC_CITATION_MISSING,
            f"表里 label={label!r} 的正文那一段里指不回 E 的读数：要写出那份程序"
            f"（{row.file}）或 E 的读数编号（{want}）—— 业主口径是「在正文里标出它们来自 E 的"
            "那条读数」；把 E 的两块改写成没有出处的叙述，等于把 E 的读数换成我们自己的说法")
    return out


# ---------------------------------------------------------------- 逐格取数（`doc.mapping_cells`）

#: `mapping_cells` 的 `problems[].cell` 里"不是某一格"的那一档（整表 / 整行）。
WHOLE_ROW_CELL = "*"

#: `mapping_cells` 交出去的那九格（顺序固定：读的人按它看，diff 才读得懂）。
MAPPING_CELL_FIELDS: tuple[str, ...] = (
    "file", "lean_file", "lean_target",
    NT.EVIDENCE_FIELD, NT.NOTE_FIELD,
    NP.INDEX_KIND_FIELD, NP.INDEX_PATH_FIELD, NP.INDEX_SHA_FIELD, NP.INDEX_SIGN_FIELD,
)


def _body_env_for_label(project_root: str | Path, label: Any) -> tuple[BodyEnv | None, str]:
    """正文里 `label` 那个定理类环境（`None` + 理由 = 读不到 / 没有这个环境）。

    只做"定位"：环境数、顺序、`env_no` 那些判据在 `_orphan_problems` /
    `_statement_surplus_problems` 里，这里不另判一次。
    """
    package = package_dir(project_root)
    main_path = package / PC.TEX_NAME
    if not main_path.is_file():
        return None, f"没有正文（{main_path} 不在盘上）"
    try:
        main_text = main_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"正文读不出来（{type(exc).__name__}: {exc}）"
    envs, _statement_envs, _files, problems = _body_envs_of_package(
        package, main_path, main_text)
    want = str(label or "")
    for env in envs:
        if env.label == want:
            return env, ""
    if problems:
        return None, f"正文没读完（{problems[0].get('detail')}）"
    return None, f"正文里没有 label={want!r} 的环境"


def _cell_of_problem(problem: Mapping[str, Any], row: Row, channel: Any) -> str:
    """一条既有判据的问题落到哪一「格」（只做显示归位；判据本身不在这里重写）。

    归位的依据是问题类别（`_problem` 的 `kind`）—— 每一类本来就是围着某一格说的
    （见 `_lean_problems` / `_numeric_problems` 的 docstring）。`mapping_numeric_evidence_missing`
    那一类还兼任索引四格的载体，所以先看它在原话里点了哪个 `INDEX_*` 字段名。
    """
    kind = str(problem.get("kind") or "")
    detail = str(problem.get("detail") or "")
    if kind == "mapping_lean_missing":
        empty = [name for name in credential_fields(channel)
                 if not str(getattr(row, name, "") or "").strip()]
        return empty[0] if empty else "lean_file"
    if kind == "mapping_lean_file_missing":
        if not str(channel or ""):
            # 空通道那一族（第 5 条：两格必须都空）：问题落在"填了的那一格"，
            # 只填 `lean_target` 时不能读成 `lean_file`。
            filled = [name for name in LEAN_ROW_FIELDS
                      if str(getattr(row, name, "") or "").strip()]
            if filled:
                return filled[0]
        return "lean_file"
    if kind in ("mapping_lean_target_missing", "mapping_lean_target_ambiguous"):
        return "lean_target"
    if kind in ("mapping_proof_program_missing", "mapping_file_missing"):
        return "file"
    if kind == NT.PROOF_PROGRAM_UNBACKED:
        return NT.EVIDENCE_FIELD
    if kind == NT.EXHAUSTION_NOTE_MISSING:
        return NT.NOTE_FIELD
    if kind == NT.NUMERIC_EVIDENCE_MISSING:
        for name in (NP.INDEX_KIND_FIELD, NP.INDEX_PATH_FIELD, NP.INDEX_SHA_FIELD,
                     NP.INDEX_SIGN_FIELD):
            if name in detail:
                return name
        if "索引" in detail:
            return NP.INDEX_PATH_FIELD
        return NT.EVIDENCE_FIELD
    if kind == NT.NUMERIC_CITATION_MISSING:
        # 正文那一段指不回 E：它不是某一格的值，是"这一行在正文里那一段"。
        return WHOLE_ROW_CELL
    return WHOLE_ROW_CELL


def mapping_cells(project_root: str | Path, *,
                  workspace_root: str | Path | None = None,
                  statement_id: Any = "",
                  claim_key: Any = "",
                  proof_no: Any = None) -> dict[str, Any]:
    """给 G 直接取「对应表那一行该填的每一格」：值 + 每格来源 + 逐格问题（纯读，不写盘）。

    业主 2026-11-04 的裁定：「如果数据位置都知道，要给 G 开发辅助工具直接拿到」。

    ## 这个函数只做"取数 + 归位"，判据一条都不重写

    - 通道与「该填哪几格」：`_credential_slot` → `numericproof.formal_slot` →
      `numericproof.proof_channel`；凭据格的清单是 :func:`credential_fields`（`_lean_problems`
      读的是同一个函数）；
    - 这一行算不算数值凭据那一档：`is_numeric_row`（`_row_checks` 的 `file` 与凭据格
      走它）；要不要再带数值实验定理那几格附加义务：`is_numeric_theorem_row`
      （`kind` 决定档位；`_numeric_problems` 只对命题类环境跑，2026-11-05 缺陷 1）；
    - 逐格问题：`_row_checks` / `_lean_problems` / `_numeric_problems` 的原话，
      按问题类别归位到格（:func:`_cell_of_problem`）—— 于是"工具说齐、判据说拒"在结构上
      不可能：同一份 `problems` 一半来自这些判据本身；
    - 索引四格：`NT.evidence_index_problems`（它再转发 `numericproof.resolve_index`；
      报告那一档只对数值实验定理那一行判）；自有 + 已签 + 定理类的行由写侧现读现填
      （`fill_evidence_cells`），这里把同一份值交回去，`sources` 写明"框架现读现填、
      你别手填"；其余行四格空着并说清为什么（空 != 已签）。

    ## 三态与"不许猜"

    - `checked=False` ⇒ 没查成（比如连表都读不出来），绝不是"这行齐了"；
    - 拿得到的格进 `cells`，且 `sources[格]` 指回"哪张表哪一行哪一格"或"现算"；
    - 拿不到的格不进 `cells`（不留一个像样的空值），在 `problems` 里点名缺哪格、为什么；
    - 通道为空的那两格是"不适用"：进 `cells` 的是空串，`sources` 写明"不适用（可留空）"——
      空串在这里是判据说过的取值，不是"缺失"的冒充；
    - `evidence_sha256` / `v_signature.sha256` 一律现算（报告那一档是
      `numericproof.index_object_sha256` 的字节尺；自有证明那一档是同一份 `## 证明`
      正文 sha，与 V 签同一把尺），与表里抄的值不符时由 `NT.evidence_index_problems`
      报"抄来的数与盘上不符"。

    ## 认行的三种写法

    `statement_id` 收裸号（`000004`）、`stmt:000004`、以及带证明号的 `stmt:000004#p2`；
    也可以只给 `claim_key`（台账 `experiments.claim_key`，它指到唯一一条命题号时用它）。
    `proof_no` 显式给了就压过 `statement_id` 里的尾巴。表里对不上那一行 / 对上不止一行
    都落 `problems`（`cell="*"`），不挑一行"看着像"的。
    """
    project = Path(project_root)
    workspace = Path(workspace_root) if workspace_root is not None else project
    package = package_dir(project)
    out: dict[str, Any] = {"ok": False, "cells": {}, "sources": {}, "problems": [],
                           "channel": "", "checked": False,
                           #: G 侧那张「承重命题的稿与签」表（`load_bearing_gaps` 的同一份
                           #: 读数）：不给 `statement_id` 时这就是全部返回值，G 成文前先读它。
                           "load_bearing_gaps": {"checked": False, "rows": 0, "gaps": [],
                                                 "complete": 0, "unreadable": [],
                                                 "why": ""},
                           "note": ""}
    problems: list[dict[str, Any]] = out["problems"]

    def whole(why: Any) -> None:
        problems.append({"cell": WHOLE_ROW_CELL, "why": str(why)})

    json_path = package / MAPPING_JSON_NAME
    if not json_path.is_file():
        out["checked"] = True
        whole(f"论文包里没有对应表：{json_path} —— 这一行还没有可取的格"
              "（先 `doc.write_mapping` 落表）")
        return out
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        out["checked"] = True
        whole(f"对应表在包里但读不出来：{json_path}（{type(exc).__name__}: {exc}）")
        return out
    rows, row_problems = parse_rows(payload)
    out["checked"] = True
    for item in row_problems:
        whole(item.get("detail") or item)

    ledger = read_ledger_tables(workspace)
    experiments = [dict(r) for r in (ledger.get("experiments") or ())
                   if isinstance(r, Mapping)]
    # G 侧那张表（业主 2026-11-26）：「这篇论文里哪些承重命题没有自己的证明稿 / 签」。
    # 它是 `load_bearing_gaps` 的唯一读数的转发 —— 不给 statement_id 时，本工具只交这张表。
    out["load_bearing_gaps"] = load_bearing_gaps(
        project, workspace_root=workspace, ledger=ledger, rows=rows)

    # ---- 认这一条命题（裸号 / stmt: / claim_key 三种写法）
    raw = str(statement_id or "").strip()
    key = str(claim_key or "").strip()
    if raw and ":" not in raw:
        raw = f"stmt:{raw}"
    if not raw and key:
        hits = [r for r in experiments if str(r.get("claim_key") or "") == key]
        sids = sorted({str(r.get("statement_id") or "") for r in hits} - {""})
        if len(sids) > 1:
            whole(f"claim_key={key!r} 在 `experiments` 台账里指到不止一条命题"
                  f"（{sids}）⇒ 不知道要取哪一行")
            return out
        if not sids:
            whole(f"claim_key={key!r} 在 `experiments` 台账里没有对应的命题号 ⇒ 取不到这一行")
            return out
        raw = f"stmt:{sids[0]}"
    if not raw:
        # 没给命题号：这一次只取「承重命题的稿与签」那张表（G 成文前的第一读数）。
        # 它不是"这一行齐了"，也不是"没查成"——`load_bearing_gaps.checked` 自己说查没查成。
        out.update(checked=True, ok=True,
                   note=("没给 `statement_id` / `claim_key` ⇒ 只取了本项目的承重缺口表"
                         "（`load_bearing_gaps`）；要取某一行的格再带命题号"))
        return out
    resolved = resolve_ledger_id(raw, ledger)
    if not resolved["ok"] or str(resolved.get("table") or "") != "statements":
        whole(f"`statement_id` = {raw!r} 在台账里解析不到：{resolved.get('reason')}")
        return out
    sid = str(resolved["row_id"])
    try:
        want_no = int(proof_no) if proof_no is not None else int(resolved["proof_no"])
    except (TypeError, ValueError):
        whole(f"`proof_no` 读不成正整数：{proof_no!r}")
        return out
    if want_no < 1:
        whole(f"`proof_no` 必须是 1 起的整数（1 = canonical），收到 {proof_no!r}")
        return out
    statement_raw = ledger_row(ledger, "statements", sid)
    if not isinstance(statement_raw, Mapping):
        whole(f"台账 `statements` 里没有 stmt:{sid} ⇒ 这一条命题没在册")
        return out

    hits: list[Row] = []
    for row in rows:
        got = resolve_ledger_id(row.ledger_id, ledger)
        if not got["ok"] or str(got.get("table") or "") != "statements":
            continue
        if str(got["row_id"]) != sid or int(row.proof_no) != want_no:
            continue
        hits.append(row)
    if not hits:
        others = [f"{one.label}#p{int(one.proof_no)}" for one in rows
                  if str(one.ledger_id).startswith(f"stmt:{sid}")]
        whole(f"对应表里没有一行指到 stmt:{sid} 的第 {want_no} 条证明"
              + (f"（表里同一条命题登记的是 {'、'.join(others)}）" if others else "")
              + " —— 先给这一条登记一行")
        return out
    if len(hits) > 1:
        whole(f"对应表里有 {len(hits)} 行都指到 stmt:{sid} 的第 {want_no} 条证明"
              f"（labels={'、'.join(repr(one.label) for one in hits)}）⇒ 不知道取哪一行")
        return out
    row = hits[0]

    # ---- 通道：只调既有判据（`_credential_slot` → `formal_slot` → `proof_channel`）
    statement = {**dict(statement_raw), "proof_text": V.proof_text_of(statement_raw, want_no)}
    slot = _credential_slot(row, ledger, experiments)
    channel = str(slot.get("channel") or "")
    out["channel"] = channel
    numeric = is_numeric_row(row, ledger, experiments)
    theorem_numeric = is_numeric_theorem_row(row, ledger, experiments)
    # 证明栏第 ① 段是程序、E 还没签成穷举时，那份 `.py` 就是例子 / 实验的数值凭据
    # （2026-11-05 缺陷 1：凭据格按通道判，`kind` 只决定要不要那几格附加义务）。
    program_path = "" if channel else _proof_column_program(
        statement, experiments=experiments,
        evidence=str(getattr(row, NT.EVIDENCE_FIELD, "") or ""),
        file=str(row.file or ""))
    program_credential = bool(program_path) and row.kind not in STATEMENT_ENV_KINDS
    cells: dict[str, Any] = {}
    sources: dict[str, str] = {}

    def put(cell: str, value: Any, source: str) -> None:
        cells[cell] = value
        sources[cell] = str(source)

    def miss(cell: str, why: Any) -> None:
        problems.append({"cell": str(cell), "why": str(why)})

    # ---- `file`：数值行 = 仓库根相对的那份程序；理论行 = 论文包内那份 tex
    exp_row: dict[str, Any] | None = None
    if numeric:
        exp_row = (NP.find_signed_exhaustion_for_column(experiments,
                                                        statement.get("proof_text"))
                   or NP.find_signed_exhaustion(experiments, slot.get("path") or row.file))
        script = NP.norm_rel((exp_row or {}).get("code_path"))
        if not script:
            script = NP.norm_rel(slot.get("path") or "") or program_path
        if script:
            src = (f"experiments#{NT.evidence_id_of(exp_row) or '?'} 的 `code_path`"
                   "（2026-11-08：程序路径住实验行，不在证明栏里）"
                   if exp_row is not None else
                   f"statements#stmt:{sid}#p{want_no} 的 proof_text（旧形态 `程序：` 段）"
                   "（`numericproof.proof_column_script`）")
            put("file", script, f"{src} —— 数值实验定理这一行的 `file` 是「仓库根相对」的那份程序")
        else:
            miss("file", "这一行按 `papermapping.is_numeric_row` 是数值凭据那一档，"
                         "而那条实验的 `code_path` 与证明栏的旧 `程序：` 段都读不出程序路径"
                         " ⇒ 这一格拿不到")
    else:
        env, why = _body_env_for_label(project, row.label)
        if not manuscript_required(row):
            # 定义行没有证明稿（2026-11-26 GMAP）：`file` 不是必填格，这一格给"不适用"。
            # 表里自己填了的话，仍把它原样交回（并明说没独立复核）。
            given = str(row.file or "").strip()
            if given:
                put("file", given,
                    "表里这一格现有的值（定义行不要求填它；填了就要指得到包内那份文件 —— "
                    "`_row_checks` 会核）")
            else:
                put("file", "",
                    "定义行没有证明稿 ⇒ 这一格不适用（可留空）；定义正文在台账那一行的 "
                    "`statement_full` 里，来源由 `ledger_id` 追")
        elif env is not None:
            put("file", env.file,
                f"正文 {env.file}:{int(env.line)} 的定理环境（label={row.label!r}）—— "
                "理论定理这一行的 `file` 是「论文包内相对」的路径")
        elif str(row.file or "").strip():
            put("file", str(row.file).strip(),
                "表里这一格现有的值（正文里读不到那个环境 ⇒ 没独立复核）")
            miss("file", f"正文里读不到 label={row.label!r} 那个环境（{why or '没有正文'}）"
                         " ⇒ 这一格的值没法独立复核（只把表里现值原样交回）")
        else:
            miss("file", f"正文里读不到 label={row.label!r} 那个环境（{why or '没有正文'}），"
                         "表里这一格也是空的 ⇒ 这一格拿不到")

    # ---- `lean_file`：numeric ⇒ 证明栏第 ① 段那份 .py；formal ⇒ .lean；空通道 ⇒ 不适用
    if channel == NP.PROOF_CHANNEL_NUMERIC:
        lean = NP.norm_rel(slot.get("path") or "") or str(cells.get("file") or "")
        if lean:
            put("lean_file", lean,
                f"证明栏第 ① 段那份程序（statements#stmt:{sid}#p{want_no}；"
                "通道=numeric，`numericproof.formal_slot`）—— 数值通道只有这一格，"
                "`lean_target` 不填")
        else:
            miss("lean_file", "通道是数值证明（`numericproof.proof_channel`），而证明栏第 ① 段"
                              "读不出那份 `.py` 的路径 ⇒ 这一格拿不到")
    elif program_credential:
        put("lean_file", program_path,
            f"证明栏第 ① 段那份程序（statements#stmt:{sid}#p{want_no}；"
            f"这一行排成 {str(row.kind or '')!r}，不是被证明的命题 ⇒ 这份 `.py` 就是它的"
            "数值凭据；`lean_target` 不填）")
    elif channel == NP.PROOF_CHANNEL_FORMAL:
        lean = NP.norm_rel(slot.get("path") or "")
        if lean:
            put("lean_file", lean,
                f"形式化通道的那份 `.lean`（statements#stmt:{sid}#p{want_no} 的证明栏第 ① 段 / "
                "`experiments` 里那条 formal 行；通道=formal）")
        else:
            miss("lean_file", "通道是形式化（`numericproof.proof_channel`），而证明栏第 ① 段与"
                              "台账的 formal 行都读不到一份 `.lean` 路径 ⇒ 这一格拿不到")
    else:
        put("lean_file", "",
            "通道为空 ⇒ 这一格不适用（`numericproof.formal_slot` 的 why：可留空，空≠已验）")

    # ---- `lean_target`：只有 formal 通道有它；来源是那份 `.lean` 里的声明名
    if channel == NP.PROOF_CHANNEL_FORMAL:
        lean_file = str(cells.get("lean_file") or "")
        state = (_lean_source_state(package, project, lean_file) if lean_file
                 else {"state": "missing", "abs": "", "reason": "`lean_file` 没取到"})
        text = ""
        if state.get("state") in ("present", "empty"):
            try:
                text = Path(str(state.get("abs") or "")).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                miss("lean_target", f"{lean_file!r} 读不出文本（{type(exc).__name__}: {exc}）"
                                    " ⇒ 声明名没核过，这一格不算命中")
        elif lean_file:
            miss("lean_target", f"`lean_file` 那份源码读不到：{state.get('reason')}"
                                " ⇒ 声明名没处核")
        if text:
            names = lean_declarations(text)
            given = str(row.lean_target or "").strip()
            if given and lean_declares(text, given):
                put("lean_target", given,
                    f"{lean_file} 里字面出现的声明名（`papermapping.lean_declares` 词边界命中）")
            elif len(names) == 1:
                put("lean_target", names[0]["name"],
                    f"{lean_file}:{names[0]['line']} 的顶层声明名（那份源码只有这一个声明）")
            elif not names:
                miss("lean_target", f"{lean_file} 里读不出任何顶层声明名"
                                    "（`theorem` / `lemma` / `def` …）⇒ 这一格拿不到")
            else:
                shown = "、".join(f"{one['name']}（:{one['line']}）" for one in names[:8])
                miss("lean_target", f"{lean_file} 里有 {len(names)} 个顶层声明（{shown}）"
                                    "—— 没有一处说明哪一个是这一条命题的 ⇒ 不许猜："
                                    "写源码里字面出现的那个声明名")
    else:
        put("lean_target", "",
            "只有 formal 通道填这一格（数值程序没有 Lean 声明名；通道为空更不适用）")

    # ---- 数值那两格：E 的那条读数与两块读数的落点（判据在 `numerictheorem`）
    #
    # 只有「数值实验定理」那一档（命题类环境）才要这两格：例子 / 实验按数值通道填凭据格
    # 就够了，它们没有「这条定理压在哪条 E 的穷举读数上」这一问（2026-11-05 缺陷 1）。
    if theorem_numeric:
        if exp_row is not None:
            eid = NT.evidence_id_of(exp_row)
            if eid:
                put(NT.EVIDENCE_FIELD, eid,
                    f"experiments#{eid}（`numericproof.find_signed_exhaustion_for_column`："
                    "E 签的穷举行，它与证明栏第 ① 段是同一份程序）")
            else:
                miss(NT.EVIDENCE_FIELD, "找到的那条 E 签穷举行没有 `experiment_id` ⇒ 读数编号拿不到")
            put(NT.NOTE_FIELD, NT.note_relpath(exp_row),
                "`exhaustionreport.report_relpath(experiments#"
                f"{eid or '?'})`（E 的 ②③ 的唯一落点）")
        else:
            miss(NT.EVIDENCE_FIELD, "台账里没有一条 E 签的穷举证明与证明栏第 ① 段对得上"
                                    "（`numericproof.find_signed_exhaustion_for_column` 返回 None）"
                                    " ⇒ 这一格拿不到")
            miss(NT.NOTE_FIELD, "没有那条 E 的读数 ⇒ 两块读数的落点也无从取")
    elif numeric:
        put(NT.EVIDENCE_FIELD, "",
            "这一行是数值凭据那一档（证明栏第 ① 段是程序），而正文里排成 "
            f"{str(row.kind or '')!r}（不是被证明的命题）⇒ 数值实验定理那两格不适用；"
            "凭据那一格仍按数值通道填（`lean_file` = 证明栏第 ① 段那份程序）")
        put(NT.NOTE_FIELD, "", "同上：两块读数的落点只对定理类环境那一行（不适用）")
    else:
        put(NT.EVIDENCE_FIELD, "",
            "这一行不是数值实验定理（`papermapping.is_numeric_row` 为假）⇒ 这一格不适用")
        put(NT.NOTE_FIELD, "", "同上：两块读数只对数值实验定理那一行（不适用）")

    # ---- 索引四格：正文是哪一档 / 在哪 / 现算的指纹 / V 的签
    # 与上面两格同一个边界：只对定理类环境判（例子 / 实验没有「正文是哪一份 E 报告」这一问）。
    note = str(cells.get(NT.NOTE_FIELD) or "")
    fresh_sha = ""
    if theorem_numeric and exp_row is not None:
        put(NP.INDEX_KIND_FIELD, NP.INDEX_KIND_REPORT,
            "这一行的正文是 E 的报告（`exhaustionreport.report_relpath` 指的那份读数）⇒ "
            f"{NP.INDEX_KIND_REPORT}（受控词表 `numericproof.INDEX_KINDS`）")
        put(NP.INDEX_PATH_FIELD, note,
            "与 `exhaustion_note` 同一处（`numerictheorem.evidence_index_problems` 要求两格"
            "指同一份）")
        note_abs, why = NT._resolve(workspace, note) if note else (None, "落点没取到")
        if note_abs is None or not note_abs.is_file():
            miss(NP.INDEX_SHA_FIELD, f"`{NT.NOTE_FIELD}` 指的那份读数读不到"
                                     f"（{why if note_abs is None else note + ' 不在盘上'}）"
                                     " ⇒ sha 现算不了（不抄别人写的数）")
        else:
            try:
                fresh_sha = NP.object_sha256(note_abs)
            except OSError as exc:
                miss(NP.INDEX_SHA_FIELD, f"{note} 读不出来（{type(exc).__name__}: {exc}）"
                                         " ⇒ sha 现算不了（不抄别人写的数）")
            else:
                put(NP.INDEX_SHA_FIELD, fresh_sha,
                    f"现算（`numericproof.object_sha256`）：{note} 的字节 sha256")
    elif theorem_numeric:
        for field_name in (NP.INDEX_KIND_FIELD, NP.INDEX_PATH_FIELD, NP.INDEX_SHA_FIELD,
                           NP.INDEX_SIGN_FIELD):
            miss(field_name, "找不到那条 E 的读数（见 `numeric_evidence` 那一格）"
                             " ⇒ 索引四格都无从取")
    else:
        # 自有 + 已签 + 定理类的行：索引四格由写侧现读现填（`fill_evidence_cells`）——
        # 这里把框架落盘时会写下去的那四格直接交回去（G 不用抄，抄了也会在落盘前被盖）。
        # 其余行（citation / 未签 / 例子 / 实验）四格空着：空 != 已签，`sources` 说清为什么。
        own: dict[str, Any] = {}
        try:
            own = evidence_cells_for_row(row, ledger, workspace)
        except Exception:  # noqa: BLE001 —— 读不出来 ⇒ 当"这一档没有"，走下面那一档
            own = {}
        if own:
            where = {
                NP.INDEX_KIND_FIELD:
                    "受控词表 `numericproof.INDEX_KINDS`（这一号证明的正文是 proof）",
                NP.INDEX_PATH_FIELD:
                    "台账 `statements.manuscripts[证明号]` 指的那一份稿",
                NP.INDEX_SHA_FIELD:
                    "台账 `bits.evidence.reviewed_sha_by_proof[证明号]`（V 签住的那一份 "
                    "`## 证明` 正文，与写侧同一把尺）",
                NP.INDEX_SIGN_FIELD:
                    "同一份正文的 sha + V 的判决（`fill_evidence_cells` 落盘时也写这一份）",
            }
            for field_name, source in where.items():
                put(field_name, own[field_name],
                    f"{OWN_PROOF_CELLS_NOTE}；来源：{source}")
        else:
            for field_name in (NP.INDEX_KIND_FIELD, NP.INDEX_PATH_FIELD, NP.INDEX_SHA_FIELD,
                               NP.INDEX_SIGN_FIELD):
                put(field_name, "", NOT_OWN_PROOF_CELLS_NOTE)

    if fresh_sha and NP.INDEX_SIGN_FIELD not in cells:
        signed = NP.latest_third_party_sign(workspace, statement_id=sid,
                                            object_sha256=fresh_sha, object_path=note)
        verdict, sign_src = "", ""
        if signed.get("checked") and signed.get("found"):
            verdict = str(signed.get("verdict") or "")
            sign_src = (f"{signed.get('ledger') or f'verifications/{sid}.jsonl'}"
                        "（`numericproof.latest_third_party_sign`：V 的最近一签，"
                        "盖的是这一份对象的字节）")
        else:
            from . import vsigns as _VS   # 惰性：`vsigns` 只在 v_signature 这一格用到
            got_sign = _VS.sign_of(workspace, fresh_sha)
            if got_sign.get("checked") and got_sign.get("found"):
                verdict = str(dict(got_sign.get("sign") or {}).get("verdict") or "")
                sign_src = f"{got_sign.get('path')}（`vsigns` 台账里签这一份对象的那一签）"
        if not sign_src:
            if not signed.get("checked"):
                miss(NP.INDEX_SIGN_FIELD, f"V 的签没查成（{signed.get('why')}）"
                                          " —— 不许当成签过，也不许拿空串冒充")
            elif signed.get("stale"):
                miss(NP.INDEX_SIGN_FIELD, f"V 的签盖的是旧版：{signed.get('why')}"
                                          " ⇒ 这一版没有被签住")
            else:
                miss(NP.INDEX_SIGN_FIELD,
                     "没有 V 的签：`verifications/<命题号>.jsonl` 与 `out/vsigns/<sha>.json` "
                     "里都没有盖住这一份对象的签 ⇒ 这一格拿不到（空串不许冒充「签过」）")
        else:
            put(NP.INDEX_SIGN_FIELD, {"verdict": verdict, "sha256": fresh_sha}, sign_src)
            if verdict != NP.THIRD_PARTY_VERDICT_OK:
                miss(NP.INDEX_SIGN_FIELD,
                     f"V 的结论是 {verdict!r}（要 {NP.THIRD_PARTY_VERDICT_OK!r}）"
                     " ⇒ 这一行不许当 proof")

    # ---- 既有判据的原话（与 `mapping_reading` 同一批调用），按问题类别归位到格
    judged: list[Mapping[str, Any]] = list(
        _row_checks(row, ledger, package, workspace).problems)
    if LEAN_KINDS:
        judged.extend(item for item in _lean_problems(rows, package, project, ledger)
                      if str(item.get("label") or "") == str(row.label))
    if NT.NUMERIC_KINDS and theorem_numeric:
        judged.extend(_numeric_problems(row, statement_raw, ledger, workspace,
                                        theorem_segments(project)))
    seen = {(str(item.get("cell")), str(item.get("why"))) for item in problems}
    for item in judged:
        cell = _cell_of_problem(item, row, channel)
        why = str(item.get("detail") or "")
        if (cell, why) in seen:
            continue
        seen.add((cell, why))
        problems.append({"cell": cell, "why": why})

    out["cells"] = {name: cells[name] for name in MAPPING_CELL_FIELDS if name in cells}
    out["sources"] = {name: sources[name] for name in out["cells"]}
    out["ok"] = bool(out["checked"] and not problems)
    return out


def _stray_mapping_copies(project: Path, workspace: Path) -> list[Path]:
    """包外那些"放错落点"的 `MAPPING.json`（它们不算数，但要被点名）。"""
    found: list[Path] = []
    for base in (project, workspace, project / "papers"):
        path = base / MAPPING_JSON_NAME
        if path.is_file() and path not in found:
            found.append(path)
    return found


def ledger_cells_reading(rows: Iterable[Row],
                         ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None, *,
                         review_states: Mapping[str, str]) -> dict[str, Any]:
    """盘上那张表的两格与台账现在的读数逐行比一遍（纯读，不写盘、也不拦门）。

    三种结局分开记（三态纪律）：

    - `filled`：这一行两格都填了；
    - `missing`：这一行两格是空的（旧表：写侧还没填过这两格）—— 它不是"没签"，
      是"这张表还没这两格"；
    - `stale`：填了，但与台账现在的读数不一致（表写完之后台账又动过）。

    `review_states` 是命题号 → 审校台账三态（`_review_ledger_states` 的产物）：
    `reviewed` 那一格的四档要用它判「未通过 / 未审 / 未读到」，这里不自己读盘。

    它是读数不是判据：D-69 的边界是"先让它看得见" —— 表被手改过、或者台账在表写完之后
    又签了一笔，这两件事都要在读数里点名，但不把论文卡在收工门上（`md_drifted` 与
    `mapping_paper_mismatch` 已经在管"三份同源"那一档）。
    """
    items = list(rows)
    out: dict[str, Any] = {"checked": True, "rows": len(items), "filled": 0,
                           "missing": [], "stale": []}
    for row in items:
        resolved = resolve_ledger_id(row.ledger_id, ledger)
        target = (ledger_row(ledger, str(resolved["table"]), str(resolved["row_id"]))
                  if resolved["ok"] else None)
        want_all = ledger_cells(target, row.proof_no,
                                review_ledger=_review_ledger_of(resolved, review_states),
                                table=(str(resolved["table"]) if resolved["ok"]
                                       else "statements"))
        # 这一档数的是「那两格」（`ledger_kind` / `reviewed`）：`want_all` 还带
        # `optimized` / `proof_source`，拿四格去比两格会恒不相等 ⇒ 每张填过这两格的表
        # 都被报成 `stale`（2026-11-25 修）。比之前先收窄到同两格。
        want = {LEDGER_KIND_FIELD: want_all[LEDGER_KIND_FIELD],
                REVIEWED_FIELD: want_all[REVIEWED_FIELD]}
        got = {LEDGER_KIND_FIELD: str(row.ledger_kind or "").strip(),
               REVIEWED_FIELD: str(row.reviewed or "").strip()}
        if not got[LEDGER_KIND_FIELD] and not got[REVIEWED_FIELD]:
            out["missing"].append({"label": row.label, "ledger_id": row.ledger_id,
                                   "ledger": want})
            continue
        out["filled"] += 1
        if got != want:
            out["stale"].append({"label": row.label, "ledger_id": row.ledger_id,
                                 "json": got, "ledger": want})
    return out


def kind_gap_reading(rows: Iterable[Row],
                     ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None, *,
                     review_states: Mapping[str, str]
                     ) -> tuple[dict[str, Any], dict[str, Any]]:
    """落差读数：论文说定理 / 台账说猜想，以及论文排成定理 / V 没签。

    论文里以承重环境（`is_load_bearing_row`：theorem / lemma / proposition /
    corollary）出现、而台账 kind 仍是 conjecture 的行：N 条（逐条 label → stmt）；
    同理一条「论文里排成定理类环境但 V 没签的行」。

    2026-11-26 BEARINGDEF：改前只认 theorem / lemma 两种环境，于是真机
    `prop:block`（proposition）连"没签"这条读数都不进（`count=1` 而不是 2）。承重判据
    只有 `is_load_bearing_row` 一处；这一格与 `_proof_index_problems` / 填充 / CH8 同源。

    读数取自台账现读（不读表上那两格：表可能还没填、也可能写完之后台账又动过 ——
    落差说的是"论文与台账现在的关系"）。

    `review_states` 的口径同 `ledger_cells_reading`（命题号 → 审校台账三态）。

    三态：`未通过` 与 `未审` 都算"V 没签"（两者是"没签"的两条不同来路，逐条 `reviewed`
    那一格自己说是哪一档）；`未读到` 的行单列进 `unreadable`，不算进 `count`
    （"没签"是一个关于 V 做过什么的结论；"读不到"是没查成，两者折平就等于把没查成
    报成没签）。

    返回 `(kind_gap, theorem_unsigned)` 两份读数，形状都是
    `{"count", "items", "unreadable"?, "why"}`。这两条本身不改 `state`：业主的边界是
    "先让它看得见"；"稿在未签"拦不拦由 `_proof_index_problems` 的
    `mapping_load_bearing_unsigned` 判（那是另一格，判的是"承重命题有没有签"）。
    """
    gap: list[dict[str, Any]] = []
    unsigned: list[dict[str, Any]] = []
    unreadable: list[dict[str, Any]] = []
    for row in rows:
        if not is_load_bearing_row(row):
            continue
        resolved = resolve_ledger_id(row.ledger_id, ledger)
        target = (ledger_row(ledger, str(resolved["table"]), str(resolved["row_id"]))
                  if resolved["ok"] else None)
        cells = ledger_cells(target, row.proof_no,
                             review_ledger=_review_ledger_of(resolved, review_states))
        item = {"label": row.label, "env_kind": row.kind, "ledger_id": row.ledger_id,
                "proof_no": int(row.proof_no),
                "ledger_kind": cells[LEDGER_KIND_FIELD], "reviewed": cells[REVIEWED_FIELD]}
        if cells[LEDGER_KIND_FIELD] == CONJECTURE_KIND:
            gap.append(item)
        state, _verdict = _split_reviewed(cells[REVIEWED_FIELD])
        if state in ("not_passed", "unreviewed"):
            unsigned.append(item)
        elif state == "unread":
            unreadable.append(item)
    gap_why = ""
    if gap:
        gap_why = ("论文里印成定理类环境、而台账 kind 仍是 conjecture 的行："
                   + str(len(gap)) + " 条（"
                   + "、".join(f"{it['label']} → {it['ledger_id']}" for it in gap)
                   + "）")
    unsigned_why = ""
    if unsigned:
        unsigned_why = ("论文里排成定理类环境但 V 没签的行：" + str(len(unsigned)) + " 条（"
                        + "、".join(f"{it['label']} → {it['ledger_id']}" for it in unsigned)
                        + "）")
    if unreadable:
        head = ("论文里排成定理类环境、而 V 签没签读不到的行：" if not unsigned
                else "；论文里排成定理类环境、而 V 签没签读不到的行：")
        unsigned_why += head + str(len(unreadable)) + " 条（" + "、".join(
            f"{it['label']} → {it['ledger_id']}" for it in unreadable) + "）"
    return ({"count": len(gap), "items": gap, "why": gap_why},
            {"count": len(unsigned), "items": unsigned,
             "unreadable": unreadable, "why": unsigned_why})


def manuscript_paths_reading(ledger_row: Mapping[str, Any] | None,
                             workspace_root: str | Path, *,
                             review_ledger: str = "") -> dict[str, Any]:
    """一条命题的逐路径稿读数（业主 2026-11-26 的"有证明"判据的唯一实现）。

    取数链（不许别的走法）：

    1. `statements` 行（`statementledger.by_id` 那一层读出来的行）→
    2. 这一行的 `manuscripts`（`{路径号: 稿的相对路径}`，可能有任何条数）；
    3. 盘上存在性：`<工作区根>/<manuscripts[p]>`（相对工作区根，不是 library）；
    4. 签：按那一份稿判（`verifications` / `reviewed_by_proof` 的同一档；
       不按稿号与命题号的对应关系判 —— 两套编号不同轴）。

    返回 `{checked, paths: [{path_group, manuscript, on_disk, signed}], has_proof,
    signed, body_present, why}`：

    - `has_proof = any(path.manuscript 非空且 on_disk)` —— 业主口径：
      「按照命题任一证明路径有证明稿就判有证明」；
    - `signed = any(path.signed for 在盘上且有路径的 path)`；
    - `body_present` 是另一件事（这一行有没有证明正文，`bits.proof` 那条轴）——
      它只用来报两种不一致（稿在但正文空 / 正文在但稿缺），不参与 `has_proof`；
    - 三态：`checked=False`（`manuscripts` 坏形状）⇒ 调用方按"没查成"处置。
    """
    out: dict[str, Any] = {"checked": False, "paths": [], "has_proof": False,
                           "signed": False, "body_present": False, "why": ""}
    if not isinstance(ledger_row, Mapping):
        out["why"] = "台账里没有这一行 ⇒ 稿读数判不了"
        return out
    from . import manuscriptpaths as MPP   # 惰性：稿记录的读口只有那一处

    records, problems = MPP._per_path_records(ledger_row)
    if problems:
        out["why"] = "；".join(problems[:3])
        return out
    root = Path(workspace_root)
    paths: list[dict[str, Any]] = []
    for group in sorted(records):
        one = records[group]
        rel = str(one.get("path") or "")
        state = "outside"
        if rel:
            try:
                target = (root / rel)
                on_disk = target.is_file()
                state = "present" if on_disk else "missing"
            except OSError:
                on_disk, state = False, "unreadable"
        else:
            on_disk = False
        signed = False
        if rel and on_disk:
            cell = reviewed_cell(
                ledger_row, group,
                review_ledger=(review_ledger or reviewed_ledger_state(root, str(
                    ledger_row.get("stmt_id") or ""))))
            signed = _split_reviewed(cell)[0] == "signed"
        paths.append({"path_group": int(group), "manuscript": rel,
                      "on_disk": bool(on_disk), "signed": bool(signed)})
    body = str(_proof_body_sha_of(ledger_row, 1) or "")
    if not body:
        # 多证明时 canonical 可能不是 #p1：只要有任一条非空正文就算"正文在"。
        body = next((str(_proof_body_sha_of(ledger_row, int(no)) or "")
                     for no, text in V.proof_list(ledger_row)
                     if str(text or "").strip()), "")
    out.update(checked=True, paths=paths,
               has_proof=any(p["manuscript"] and p["on_disk"] for p in paths),
               signed=any(p["signed"] for p in paths if p["manuscript"] and p["on_disk"]),
               body_present=bool(body),
               why=(f"这条命题有 {len(paths)} 条路径的稿记录，"
                    + (f"盘上在 {sum(1 for p in paths if p['on_disk'])} 条"
                       if paths else "一条都没有")))
    return out




def _judge_load_bearing(cand: Mapping[str, dict[str, Any]],
                        known: Mapping[str, Sequence[Mapping[str, Any]]] | None,
                        workspace: Path) -> dict[str, Any]:
    """逐条判「缺什么」：`manuscripts` 的每一条路径 → 盘上 → 签（`load_bearing_gaps` 的后半）。

    只用台账 + 盘面：不读 `bits.proof` 当"有证明"，不按稿号与命题号对齐。
    """
    from . import manuscriptpaths as _MPP_GAPS

    result: dict[str, Any] = {"rows": 0, "gaps": [], "items": [], "complete": 0,
                             "unreadable": [], "mismatches": [], "checked_rows": 0}
    # ---- 「同一份稿被几条命题指着」：信息读数（1:1 的核实另有 `statement_of_manuscript`）。
    from . import manuscriptpaths as _MPP_GAPS

    claims_by_path: dict[str, list[str]] = {}
    for stmt_row in (known.get("statements") or ()):
        if not isinstance(stmt_row, Mapping):
            continue
        stmt_id = str(stmt_row.get("stmt_id") or "")
        per, _bad = _MPP_GAPS._per_path_manuscripts(stmt_row)
        for rel in per.values():
            normalized = str(rel or "").strip().replace("\\", "/")
            if normalized and stmt_id:
                claims_by_path.setdefault(normalized, []).append(stmt_id)
    # ---- 逐条判「缺什么」（判据：台账里的逐路径稿 + 那一份的签；不看正文 sha）
    for sid in sorted(cand):
        one = cand[sid]
        row = one.get("row")
        proof_no = int(one.get("proof_no") or 1)
        resolved = resolve_ledger_id(f"stmt:{sid}", known)
        target = (statement_by_id(known, sid) if resolved["ok"] else None)
        base: dict[str, Any] = {
            "stmt_id": sid, "ledger_id": f"stmt:{sid}",
            "kind": str(one.get("kind") or ""),
            "ledger_kind": ledger_kind_cell(target),
            "label": str(one.get("label") or ""),
            "proof_no": proof_no, "missing": [], "has_proof": False,
            "paths": [], "path_count": 0,
            "mismatch": "",
            "reviewed": "", "signed": False, "body_present": False,
            "manuscript": "", "manuscript_exists": False,
            "shared_with": [],
            "manuscript_sha256": "", "file_sha256": "", "sha_drift": False,
            "channel": "", "cited_at": list(one.get("cited_at") or []),
            "table_row": row is not None,
            "table_path": str(getattr(row, "evidence_path", "") or ""),
            "why": "",
        }
        if not isinstance(target, Mapping):
            base["why"] = (f"台账 `statements` 里没有 stmt:{sid} 这一行 ⇒ 它有没有稿与签"
                           "判不了（没查成，不是「没有缺口」）")
            result["unreadable"].append(base)
            continue
        if not base["label"]:
            # 论文里没印成环境、只在 claims / 正文里被引的那一条：label 用台账那一行的
            # 陈述截一段（G 派人时要有东西可指；它不是编号对齐，只是展示用）。
            base["label"] = str(target.get("statement_text") or "")[:40]
        # 通道非空（数值 / 形式化）：证据在 E 的报告 / `.lean` 程序上，不在"手稿稿与签"这一档。
        probe = Row(kind=str(one.get("kind") or "theorem"),
                    label=str(one.get("label") or f"stmt:{sid}"),
                    env_no=int((one.get("envs") or [{}])[0].get("env_no") or 1),
                    ledger_id=f"stmt:{sid}", proof_no=proof_no, file="")
        want = load_bearing_evidence_required(probe, known)
        channel = str(want.get("channel") or "")
        base["channel"] = channel
        if channel:
            base["why"] = (f"这一条命题的证明通道是 {channel!r} ⇒ 证据在 E 的报告 / `.lean` "
                           "程序上，由凭据格那一族判（不在「证明稿与签」这一栏）")
            result["checked_rows"] += 1
            result["items"].append(base)
            continue
        if not want.get("checked"):
            # 三态：台账没回答"这一行算不算命题" ⇒ 这一格没查成（不是"没有缺口"）。
            base["why"] = str(want.get("reason") or "承重证据这一项判不了")
            result["unreadable"].append(base)
            result["items"].append(base)
            continue
        reviewed = reviewed_cell(
            target, proof_no,
            review_ledger=reviewed_ledger_state(workspace, sid))
        paths = manuscript_paths_reading(target, workspace, review_ledger=(
            reviewed_ledger_state(workspace, sid)))
        base["reviewed"] = reviewed
        if not paths.get("checked"):
            base["why"] = (f"这一条命题的稿记录读不出来（{paths.get('why') or '坏形状'}）"
                           "⇒ 缺什么判不了（没查成，不是「没有缺口」）")
            result["unreadable"].append(base)
            result["items"].append(base)
            continue
        per_path = list(paths.get("paths") or ())
        on_disk_rels = [str(p.get("manuscript")) for p in per_path
                        if p.get("manuscript") and p.get("on_disk")]
        base.update(has_proof=bool(paths.get("has_proof")), paths=per_path,
                    path_count=len(per_path), signed=bool(paths.get("signed")),
                    body_present=bool(paths.get("body_present")),
                    manuscript=(on_disk_rels[0] if on_disk_rels else
                                (str(per_path[0].get("manuscript")) if per_path else "")),
                    manuscript_exists=bool(paths.get("has_proof")),
                    shared_with=sorted({s for rel in
                                        {str(p.get("manuscript") or "") for p in per_path}
                                        for s in claims_by_path.get(rel, []) if s != sid}))
        info = proof_evidence_reading(target, proof_no, workspace, reviewed=reviewed)
        base.update(manuscript_sha256=str(info.get("recorded_sha") or ""),
                    file_sha256=str(info.get("file_sha256") or ""),
                    sha_drift=bool(info.get("sha_drift")))
        missing: list[str] = []
        if not paths.get("has_proof"):
            missing.append("稿")
        if not paths.get("signed"):
            # 签那一问独立：连稿都没有时也是"两者都缺"（不是只缺稿）。
            missing.append("签")
        base["missing"] = missing
        # 两种不一致单独报（业主 2026-11-26）：不许折成一个"有 / 没有"。
        if paths.get("has_proof") and not paths.get("body_present"):
            base["mismatch"] = "manuscript_without_body"
            result["mismatches"].append({
                "stmt_id": sid, "label": base["label"],
                "kind": "manuscript_without_body",
                "why": "稿在盘上，而台账这一行没有证明正文（稿在但正文空）"})
        elif paths.get("body_present") and not paths.get("has_proof"):
            base["mismatch"] = "body_without_manuscript"
            result["mismatches"].append({
                "stmt_id": sid, "label": base["label"],
                "kind": "body_without_manuscript",
                "why": "台账这一行有证明正文，而没有任何一条路径的稿在盘上（正文在但稿缺）"})
        result["rows"] += 1
        result["checked_rows"] += 1
        result["items"].append(base)
        if not missing:
            result["complete"] += 1
            continue
        reasons: list[str] = []
        if "稿" in missing:
            if not per_path:
                reasons.append("台账没有这一条命题的任何稿记录（它没有属于自己的证明稿）")
            else:
                reasons.append("台账记了稿，而盘上一条都取不到（"
                               + "、".join(f"第 {p['path_group']} 条 `{p['manuscript']}`"
                                          for p in per_path if p.get("manuscript"))
                               + "）")
        if "签" in missing:
            reasons.append(f"稿在盘上，而没有 V 的签（`reviewed` = {reviewed!r}）")
        if base["mismatch"]:
            reasons.append("稿与正文两态不一致：" + str(base["mismatch"]))
        if base["shared_with"]:
            reasons.append("同一份稿还被 " + "、".join(f"stmt:{x}" for x in base["shared_with"])
                           + " 指着（一份稿只能是一条命题的证明；见台账这一格）")
        base["why"] = "；".join(reasons)
        result["gaps"].append(base)
    return result


def load_bearing_gaps(project_root: str | Path, *,
                      workspace_root: str | Path | None = None,
                      ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
                      tex: str | None = None,
                      rows: Sequence[Row] | None = None) -> dict[str, Any]:
    """G 侧的第一张表：这篇论文里哪些承重命题没有它自己的证明稿 / 签（只读、不拦门）。

    业主 2026-11-26 的裁定（逐字）：

    > 「承重命题必须有证明稿应该是 G 侧应该看的，如果没有则要派 D 补材料。」

    所以这张表的主战场在「成文之前」：G 先读它；`gaps` 非空 ⇒ 先派 D 补材料，D 回来再
    成文。收工门（`mapping_reading` 的 `mapping_load_bearing_*`）读的是「同一份读数」
    （`mapping_reading` 直接把本函数的返回值放进 `load_bearing`，再由
    :func:`_proof_index_problems` 折成问题）—— 同一件事只有一个定义、一份读数，
    门只是最后一道，不在门里另写一套。

    ## 输入（两处取并集，业主口径逐字）

    - 论文正文里出现的承重环境：`STATEMENT_ENV_KINDS`（theorem / lemma / proposition /
      corollary）—— 判据是 `is_load_bearing_row`（与 MAPPING 那一行的 `kind` 同源）；
    - `documents.claims[].citations` 里的 `stmt:`（以及正文里写到的 `stmt:`）：论文自己
      声明它压在这些命题上，哪怕它们没有印成环境（附录段落 / 被 `\ref` 引用）。

    两处都读不到时 `checked=False`（"没查成"绝不折成"没缺口"）。

    ## 每一行给什么（业主 2026-11-26 定死的形状）

    `[{stmt_id, kind, label, paths: [{path_group, manuscript, on_disk, signed}], has_proof,
    missing, reviewed, shared_with, citation 位置, ...}]`：

    - `paths` 是该命题 `statements.manuscripts` 里的「每一条」路径（`{1: …, 2: …}` 有几条
      就给几条），`on_disk` 按 `<工作区根>/<路径>` 现查，`signed` 按「那一份稿」的签读数判；
    - `has_proof = any(path.manuscript 非空且 on_disk)`（业主：「按照命题任一证明路径有
      证明稿就判有证明」）；「不」读 `bits.proof`（那是"有没有证明正文"，另一件事）；
    - `missing`（`["稿"]` / `["签"]` / `["稿","签"]`）由 `has_proof` 与"在盘上的那条路径
      有没有签"两问得出；
    - `mismatches`（另一份读数，逐条）：`manuscript_without_body`（稿在但正文空）与
      `body_without_manuscript`（正文在但稿缺）——两种不一致分开报，不折成"有 / 没有"；
    - `manuscript` / `manuscript_exists` / `reviewed` / `shared_with` / `cited_at` /
      `manuscript_sha256` / `file_sha256` / `sha_drift` 是展示与信息读数（「sha 不当判据」：
      洗稿合法）。

    ## 取数链（必须写成台账读法，不许按编号对齐）

    `stmt_id` → `statements` 行（唯一读口 `statementledger.by_id`）→
    那一行的 `manuscripts`（`{path_group: 稿的相对路径}`，「不要拿 `proof_no` 当身份」）
    → `<工作区根>/<manuscripts[p]>` 的存在性 → `verifications` / `reviewed` 里「那一份稿」的签。
    稿号（`b-proof-NNNNNN`）与命题号是两套独立编号：文件名与它服务哪条命题无关，
    所以只能查台账这一格，不能拿编号拼、不能拿正文内容 / label 字面 / 字节 sha 反推。

    三态：`checked`（整张表查没查成）、`gaps`（缺东西的行）、`unreadable`（这一行查不成：
    台账解析不到 / 正文有环境而表里没有行 / 稿记录读不出来）—— `unreadable` 不是
    "没有缺口"，G 与门都必须看得见它。

    这条读数的判据只有一处：`is_load_bearing_row`（承重）+ `proof_evidence_reading`
    （稿 / 签两态）。四个消费点（G 的 `doc.mapping_cells`、`mapping_reading`、收工门 CH8、
    `theorem_unsigned`）都读这一处或它的同一份定义，不许各写一份。
    """
    project = Path(project_root)
    workspace = Path(workspace_root) if workspace_root is not None else project
    known = ledger if ledger is not None else read_ledger_tables(workspace)
    out: dict[str, Any] = {"checked": False, "project_root": str(project),
                           "workspace_root": str(workspace), "rows": 0,
                           "gaps": [], "items": [], "complete": 0, "unreadable": [],
                           "mismatches": [], "checked_rows": 0, "why": ""}
    # ---- 正文：定理类环境（第 1 处输入）
    _statement_envs: list[BodyEnv] = []
    tex_problems: list[dict[str, Any]] = []
    text = tex
    if text is None:
        package = package_dir(project)
        tex_path = package / PC.TEX_NAME
        try:
            text = tex_path.read_text(encoding="utf-8") if tex_path.is_file() else ""
        except OSError as exc:
            out["unreadable"].append({"label": "", "stmt_id": "",
                                      "why": f"正文读不出来（{type(exc).__name__}: {exc}）"})
            text = ""
        if text:
            _envs, _statement_envs, _files, tex_problems = _body_envs_of_package(
                package, tex_path, text)
    if text:
        if not _statement_envs:
            # 调用方直接给了正文（`tex=`）：没有文件可跟，但环境与行号仍要读出来
            # （G 那张表的 `cited_at` 要指到"第几行、哪个环境"）。
            _statement_envs = [
                BodyEnv(kind=env.kind, label=env.label, env_no=env.env_no,
                        line=env.line, file=PC.TEX_NAME)
                for env in body_envs(text) if env.kind in STATEMENT_ENV_KINDS]
        else:
            _statement_envs = [env for env in _statement_envs if env.kind in STATEMENT_ENV_KINDS]
    # ---- 表那一层（第 1 处输入的另一半：MAPPING 的承重行）
    table_rows: list[Row] = []
    if rows is not None:
        table_rows = [row for row in rows if is_load_bearing_row(row)]
    else:
        json_path = package_dir(project) / MAPPING_JSON_NAME
        if json_path.is_file():
            try:
                payload = json.loads(json_path.read_text(encoding="utf-8"))
                parsed, _problems = parse_rows(payload)
                table_rows = [row for row in parsed if is_load_bearing_row(row)]
            except (OSError, json.JSONDecodeError) as exc:
                out["unreadable"].append({
                    "label": "", "stmt_id": "",
                    "why": f"对应表读不出来（{type(exc).__name__}: {exc}）"})
    for item in tex_problems:
        out["unreadable"].append({"label": str(item.get("label") or ""), "stmt_id": "",
                                  "why": str(item.get("detail") or "")})
    # ---- 候选：stmt_id ⇒ 收集到的线索（表的行 / 正文环境 / 文内引用）
    cand: dict[str, dict[str, Any]] = {}

    def _one(sid: str) -> dict[str, Any]:
        return cand.setdefault(sid, {"stmt_id": sid, "row": None, "envs": [],
                                     "cited_at": [], "proof_no": 1})

    for row in table_rows:
        resolved = resolve_ledger_id(row.ledger_id, known)
        if not resolved["ok"] or str(resolved.get("table") or "") != "statements":
            out["unreadable"].append({
                "label": str(row.label), "stmt_id": "",
                "why": (f"对应表里 label={row.label!r} 的 `ledger_id` 解析不到"
                        f"（{resolved.get('reason') or '不是 statements 行'}）⇒ 查不到它的台账命题")})
            continue
        sid = str(resolved["row_id"])
        one = _one(sid)
        one["row"] = row
        one["proof_no"] = int(row.proof_no or 1)
        one["kind"] = str(row.kind)
        one["label"] = str(row.label)
    # 正文环境按 `label` 对回表的行：表里有这一行 ⇒ 记它被引在哪；没有 ⇒ unreadable。
    row_by_label = {str(row.label): row for row in table_rows}
    for env in _statement_envs:
        row = row_by_label.get(str(env.label))
        if row is None:
            out["unreadable"].append({
                "label": str(env.label), "stmt_id": "",
                "why": (f"正文里 {env.kind} 环境 {env.label!r}（{env.file}:{env.line}）"
                        "在对应表里没有行 ⇒ 连它是哪条命题都不知道，承重缺口判不了")})
            continue
        resolved = resolve_ledger_id(row.ledger_id, known)
        if not resolved["ok"] or str(resolved.get("table") or "") != "statements":
            continue
        one = _one(str(resolved["row_id"]))
        one["envs"].append({"kind": env.kind, "label": env.label, "env_no": int(env.env_no),
                            "file": env.file, "line": int(env.line)})
        one["cited_at"].append({"where": "paper", "file": env.file, "line": int(env.line),
                                "env": env.kind, "env_no": int(env.env_no)})
    # 第 2 处输入：论文自己声明的 `stmt:`（claims）与正文里写到的 `stmt:`。
    for item in paper_citations(project, workspace_root=workspace, tex=text):
        if item["prefix"] != "stmt":
            continue
        sid = str(item["code"]).split("#", 1)[0]
        one = _one(sid)
        where = str(item.get("source") or "")
        if where == "paper source":
            one["cited_at"].append({"where": "paper", "raw": str(item.get("raw") or "")})
        else:
            one["cited_at"].append({"where": "claims", "source": where,
                                    "raw": str(item.get("raw") or "")})
    out["checked"] = True
    judged = _judge_load_bearing(cand, known, workspace)
    # 前半段（表行解析不到 / 正文有环境而表里没有行）收的 unreadable 不能被后半段盖掉：
    # 两段都是"这一项没查成"，只是发现的阶段不同。
    out["unreadable"] = (list(out.get("unreadable") or ())
                         + list(judged.pop("unreadable", []) or ()))
    out.update(judged)
    # ---- 末尾 why（一句话读数）
    out["why"] = (f"这篇论文的承重命题 {out['rows']} 条：{len(out['gaps'])} 条缺稿或签"
                  f"（{out['complete']} 条齐）"
                  + (f"；另有 {len(out['unreadable'])} 条这一项没查成"
                     "（没查成不是「没有缺口」）" if out["unreadable"] else "")
                  + (f"；稿与正文两态不一致 {len(out['mismatches'])} 条"
                     if out["mismatches"] else ""))
    return out


#: 编号形态：`…:<章>.<序>`（设计里的 `概念1.1` / `定理3.3`；对应表 label 里写成
#: `definition:1.1` / `theorem:3.1`）。没按这个形态编号的行不进"编号忠实"那一问。
_NUMBERED_LABEL_RE = re.compile(r"^(?P<head>[^:]+):(?P<chap>\d+)\.(?P<idx>\d+)$")


def path_order_of(payload: Any) -> list[str]:
    """`MAPPING.json` 顶层声明的路径顺序（`path_order`）—— 缺 / 形状不对 ⇒ 空清单。

    空清单是"G 没声明它用了哪条路径"这一档，由 :func:`order_reading` 读成
    `checked=False`（没查成，不是"顺序没问题"）。
    """
    raw = payload.get(PATH_ORDER_FIELD) if isinstance(payload, Mapping) else None
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(item).strip() for item in raw if str(item or "").strip()]


def _node_of_id(raw: Any) -> str:
    """把一个号归一成路径节点（`stmt:000004#p2` ⇒ `stmt:000004`；`used_by` 的尾巴剥掉）。"""
    text = str(raw or "").strip()
    if "#" in text:
        text = text.split("#", 1)[0].strip()
    return text


def _report_path_orders(reports: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """台账里那几份带路径的 C 报告（`kind="proof_chain"` 且 `payload.order` 非空）。

    倒序（新登记的优先）：同一篇论文可能问过 C 好几次，最近的这一次才是这一趟的规划。
    """
    out: list[dict[str, Any]] = []
    for row in reports or ():
        if not isinstance(row, Mapping):
            continue
        if str(row.get("kind") or "").strip() != "proof_chain":
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
        order = [_node_of_id(item.get("node") if isinstance(item, Mapping) else item)
                 for item in (payload.get("order") or ())]
        order = [node for node in order if node]
        if not order:
            continue
        out.append({"report_id": str(row.get("report_id") or ""),
                    "created_at": str(row.get("created_at") or ""),
                    "checked": bool(payload.get("checked")),
                    "targets": [str(t.get("label") or t.get("stmt_id") or "")
                                for t in (payload.get("targets") or ())
                                if isinstance(t, Mapping)],
                    "order": order})
    out.sort(key=lambda item: (item["created_at"], item["report_id"]), reverse=True)
    return out


def order_reading(rows: Sequence[Row],
                  env_index: Mapping[tuple[str, str], tuple[int, int]],
                  ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None,
                  workspace: Path,
                  *, payload: Any = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """顺序那一轴：依赖 DAG 的拓扑序 + 编号按 C 的路径（口径见模块 docstring）。

    `env_index` 是「`(kind, label)` ⇒ `(正文位次, 章号)`」——由 `mapping_reading` 从
    `envs` 现读（正文位次 = 环境在全文里的出现次序，0 起；章号 = 它落在第几个
    `\\section` / `\\chapter` 之下）。两个数都是结构事实，不看 label 长什么样。

    返回 `(reading, problems)`；`problems` 的 `kind` 都在 `ORDER_KINDS` 里。
    三态：`reading["checked"]` = 两问都真的判了；缺材料的那一问 `checked=False`，并在
    `why` 里说清缺什么 —— 没查成不是"顺序没问题"。
    """
    problems: list[dict[str, Any]] = []
    reports = _report_path_orders(read_analysis_reports(workspace))
    declared = path_order_of(payload)
    deps_present = bool(read_dependency_rows(workspace))
    # 节点 → 行（`stmt:` / `exp:` / `lit:` / `rel:` 都归一成 `表:号`）
    by_node: dict[str, Row] = {}
    for row in rows:
        resolved = resolve_ledger_id(row.ledger_id, ledger)
        if not resolved["ok"]:
            continue
        node = f"{resolved['prefix']}:{resolved['row_id']}"
        by_node.setdefault(node, row)

    def pos_of(row: Row) -> tuple[int, int] | None:
        return env_index.get((str(row.kind), str(row.label)))

    # ---- ① 依赖 DAG 的拓扑序（材料 = 台账 dependencies；不依赖 C 的报告）
    dag: dict[str, Any] = {"checked": deps_present, "edges": 0, "checked_edges": 0,
                           "unpositioned": [], "why": ""}
    # 一条依赖的"被依赖端"有四种来源（source_stmt_id / experiment / lit / doc）：这份
    # 台账形状的全仓唯一读法是 `agent_c.proof_path._target_of`（C 的规划器就按它建边）。
    # 这里借它一把，不另写第二份 `if source_stmt_id … elif source_lit_id …` —— 两份迟早
    # 会在"哪一行算前提"上漂开，而漂开的那天 C 的路径与这一条判据说的不是同一张图。
    from .agent_c.proof_path import _target_of as _dep_target_of

    def premise_of(dep: Mapping[str, Any]) -> str:
        node, _kind = _dep_target_of(dep)
        return _node_of_id(node or dep.get("label"))

    if not deps_present:
        dag["why"] = ("依赖表读不到（`data/dependencies.json` 不在盘上或是空的）⇒ "
                      "正文先后是不是依赖的拓扑序**没查成**")
    else:
        deps = read_dependency_rows(workspace)
        dag["edges"] = len(deps)
        for dep in deps:
            if not isinstance(dep, Mapping):
                continue
            premise = premise_of(dep)
            user = _node_of_id(dep.get("used_by"))
            if not premise or not user:
                continue
            row_p, row_u = by_node.get(premise), by_node.get(user)
            if row_p is None or row_u is None:
                continue
            at_p, at_u = pos_of(row_p), pos_of(row_u)
            if at_p is None or at_u is None:
                for row in (row_p, row_u):
                    label = str(row.label)
                    if pos_of(row) is None and label not in dag["unpositioned"]:
                        dag["unpositioned"].append(label)
                continue
            dag["checked_edges"] += 1
            if at_p[0] > at_u[0]:
                problems.append(_problem(
                    ORDER_NOT_TOPOLOGICAL,
                    f"依赖被颠倒：`{premise}`（label={row_p.label!r}，正文第 {at_p[0] + 1} 条）"
                    f"是 `{user}`（label={row_u.label!r}，正文第 {at_u[0] + 1} 条）的前提，"
                    "而它排在使用它的那一条**之后** —— 正文里条目的先后必须是依赖 DAG 的"
                    "拓扑序：依赖在前、使用在后",
                    label=row_p.label, where=MAPPING_JSON_NAME))
        if dag["unpositioned"]:
            dag["why"] = (f"{len(dag['unpositioned'])} 行没有正文环境（被引未印 / 表里有行正文"
                          "没有），它们的先后没进这一问")

    # ---- ② 编号按 C 的路径
    path: dict[str, Any] = {"checked": False, "source_report": "", "declared": len(declared),
                            "reports": len(reports), "nodes": 0, "rows": 0,
                            "chapters": 0, "numbering": {"checked": False, "numbered": 0,
                                                         "missing": []},
                            "why": ""}
    if not reports:
        path["why"] = ("台账里没有带路径的 C 报告（`analysis_reports` 里没有 `kind=\"proof_chain\"`"
                       " 且 `payload.order` 非空的登记）⇒ 编号是否按 C 的路径**没查成**")
    elif not declared:
        path["why"] = ("`MAPPING.json` 没有 `path_order`（G 没声明它用的是 C 的哪一条路径）⇒ "
                       "编号是否按路径**没查成**（不是「顺序没问题」）")
    else:
        hit = next((item for item in reports if item["order"] == declared), None)
        if hit is None:
            nearest = reports[0]
            problems.append(_problem(
                ORDER_OFF_PATH,
                "表里声明的 `path_order`（" + str(len(declared)) + " 个节点）在台账里对不上任何"
                "一份 C 的路径报告 —— 最近的一份是 "
                f"report:{nearest['report_id']}（{len(nearest['order'])} 个节点："
                + "、".join(nearest["order"][:6]) + ("…" if len(nearest["order"]) > 6 else "")
                + "）。声明的顺序必须与 C 报告 `payload.order` 逐字相同（原样抄，不许自己重排）",
                where=MAPPING_JSON_NAME))
        else:
            path["checked"] = True
            path["source_report"] = hit["report_id"]
            path["nodes"] = len(hit["order"])
            index = {node: i for i, node in enumerate(hit["order"])}
            for node in hit["order"]:
                if node not in by_node:
                    problems.append(_problem(
                        ORDER_MISSING_NODE,
                        f"C 的路径第 {index[node] + 1} 位是 `{node}`，而对应表里没有它那一行 —— "
                        "C 说这条路径自足：少一条，正文里就有一个前提没有落点（证明链断在那儿）",
                        where=MAPPING_JSON_NAME))
            placed: list[tuple[int, int, Row, int]] = []
            for node, row in by_node.items():
                idx = index.get(node)
                if idx is None:
                    problems.append(_problem(
                        ORDER_OFF_PATH,
                        f"表里 label={row.label!r}（`{node}`）不在声明的这条路径上 —— "
                        "正文写 C 没规划过的条目，编号就不再是由路径驱动的",
                        label=row.label, where=MAPPING_JSON_NAME))
                    continue
                at = env_index.get((str(row.kind), str(row.label)))
                if at is None:
                    continue
                placed.append((at[1], at[0], row, idx))
            path["rows"] = len(placed)
            # 章内顺序：同一节里，正文出现顺序对应的路径位次必须严格递增
            by_section: dict[int, list[tuple[int, int, Row, int]]] = {}
            for item in placed:
                by_section.setdefault(item[0], []).append(item)
            path["chapters"] = len(by_section)
            for section, items in sorted(by_section.items()):
                items.sort(key=lambda x: x[1])
                for prev, cur in zip(items, items[1:]):
                    if cur[3] <= prev[3]:
                        problems.append(_problem(
                            ORDER_OFF_PATH,
                            f"第 {section} 节里章内顺序与 C 的路径不一致：正文先出现 "
                            f"label={prev[2].label!r}（路径第 {prev[3] + 1} 位），再出现 "
                            f"label={cur[2].label!r}（路径第 {cur[3] + 1} 位）—— "
                            "章可以自己分、章序可以重排，但**同一章里的先后必须与路径一致**",
                            label=cur[2].label, where=MAPPING_JSON_NAME))
                        break
            # 编号忠实：`…:<章>.<序>` 的行，同章里章号一致、序号随正文递增；两章不共章号。
            numbering = path["numbering"]
            numbered: list[tuple[int, int, Row, int, int]] = []
            for section, at, row, idx in placed:
                match = _NUMBERED_LABEL_RE.match(str(row.label or ""))
                if not match:
                    if str(row.label) not in numbering["missing"]:
                        numbering["missing"].append(str(row.label))
                    continue
                numbered.append((section, at, row, int(match.group("chap")),
                                 int(match.group("idx"))))
            numbering["checked"] = bool(numbered)
            numbering["numbered"] = len(numbered)
            for section, items in _group_by(numbered, key=lambda x: x[0]).items():
                items.sort(key=lambda x: x[1])
                chaps = {item[3] for item in items}
                if len(chaps) > 1:
                    problems.append(_problem(
                        ORDER_OFF_PATH,
                        f"第 {section} 节里的编号章号不唯一（{sorted(chaps)}）—— 同一章的行必须"
                        "用同一个章号，否则读者按编号找不到那一段",
                        where=MAPPING_JSON_NAME))
                for prev, cur in zip(items, items[1:]):
                    if cur[4] <= prev[4]:
                        problems.append(_problem(
                            ORDER_OFF_PATH,
                            f"编号与章内顺序打架：label={prev[2].label!r}（第 {prev[4]} 个）"
                            f"排在 label={cur[2].label!r}（第 {cur[4]} 个）之前 —— "
                            "同一章里的序号必须随正文递增（编号由路径驱动，不是随手填）",
                            label=cur[2].label, where=MAPPING_JSON_NAME))
                        break
            chaps: list[int] = []
            for section in sorted({item[0] for item in numbered}):
                chapter = next(item[3] for item in numbered if item[0] == section)
                chaps.append(chapter)
            if len(chaps) != len(set(chaps)):
                problems.append(_problem(
                    ORDER_OFF_PATH,
                    f"两个不同的章共用了同一个章号（{sorted(chaps)}）—— 章号可以在整篇里跳号、"
                    "也可以重排章序，但两章不能撞号",
                    where=MAPPING_JSON_NAME))
    reading = {"checked": bool(dag["checked"] and path["checked"]),
               "dag": dag, "path": path, "problems": problems,
               "why": "；".join(text for text in (dag["why"], path["why"]) if text)}
    return reading, problems


def _group_by(items: Iterable[Any], *, key: Any) -> dict[Any, list[Any]]:
    """按 `key(item)` 分组（保序；小工具，别为一行 `itertools.groupby` 付排序代价）。"""
    out: dict[Any, list[Any]] = {}
    for item in items:
        out.setdefault(key(item), []).append(item)
    return out


def mapping_reading(project_root: str | Path, *,
                    workspace_root: str | Path | None = None,
                    ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
                    tex: str | None = None) -> dict[str, Any]:
    """读一个项目的对应表并校验（纯读，不写盘）。

    三态：`pass` / `fail` / `unknown`（`unknown` 是"没查成 / 不适用"，绝不是通过）。
    `problems` 里每条都带 `kind`（取值在 `ALL_PROBLEM_KINDS` 里），拦不拦门由
    `agent_h.mapping_judge.level_of` 决定；`warnings` 里是只进读数、不改 `state` 的那一档
    （`LEAN_WARN_KINDS`），`lean` 那一格给出这一趟的 Lean 开关与盘上的产物。

    正文按"`main.tex` ＋ 它递归 `\\input` 进来的文件"读（见 `_body_envs_of_package`）：
    `tex_files` 是这次真的读到的文件（读入顺序），读不完（成环 / 超深 / 指的文件
    读不到）会落一条 `mapping_unresolvable` —— 没读完不许判 pass。
    """
    project = Path(project_root)
    workspace = Path(workspace_root) if workspace_root is not None else project
    package = package_dir(project)
    json_path, md_path = mapping_paths(project)
    body_problems: list[dict[str, Any]] = []
    tex_files: list[str] = []
    if tex is None:
        tex_path = package / PC.TEX_NAME
        tex_text = tex_path.read_text(encoding="utf-8") if tex_path.is_file() else ""
    else:
        tex_text = str(tex)
    has_paper = bool(str(tex_text or "").strip())
    # 定理类环境（含印成 Lemma 的自定义宏）：只有"一条命题对一个环境"那一条读它。
    statement_envs: list[BodyEnv] = []
    sections: list[int] = []
    if tex is None and has_paper:
        envs, statement_envs, sections, tex_files, body_problems = (
            _body_envs_with_sections(package, tex_path, tex_text))
    else:
        # 调用方直接给了正文文本（没有文件可跟）：只扫这一份，`tex_files` 是空的，
        # 章号也读不出来（整份当一段：`sections` 全 0 —— 章内顺序这一问退化成全文顺序）。
        envs = body_envs(tex_text)
        sections = [0] * len(envs)
        statement_envs = statement_envs_of_text(tex_text)
    lean_on, lean_source = lean_switch()
    artifacts = lean_artifacts(project)
    if not lean_on:
        lean_state = "off"
        lean_reason = ("未开 Lean（`toolchain.lean_enabled` 为假，来源："
                       + (lean_source or "缺省") + "）⇒ 没有证明通道的行，`lean_file` / "
                       "`lean_target` 允许为空；空不等于验过 —— 这一趟的证明走 `proof_text` "
                       "与 V 的逐行审校。凭据那一格按每条命题的证明通道判（形式化通道仍要 "
                       "`.lean`，数值证明通道仍要那份程序）")
    elif artifacts:
        lean_state = "on"
        lean_reason = (f"Lean 开关开着、盘上有 {len(artifacts)} 份 Lean 产物（{list(artifacts[:3])}）"
                       "—— 这是读数，不是「必须填」的理由：`lean_file` 是「"
                       + CREDENTIAL_CELL_NAME + "」那一格，按每条命题的证明通道判"
                       "（形式化通道 ⇒ 必填 `.lean` 与 `lean_target`；数值证明通道 ⇒ 必填"
                       "证明栏第 ① 段那份程序；没有通道 ⇒ 允许为空）")
    else:
        lean_state = "on_no_artifact"
        lean_reason = ("Lean 开关开着，但盘上一个 Lean 产物都没有（找过论文包内的 `"
                       + LEAN_SUFFIX + "` 与 `<项目根>/" + "`, `<项目根>/".join(LEAN_ARTIFACT_DIRS)
                       + "`）⇒ 这一趟一个形式化文件都没落：说它是「没开 Lean」不真，说它是"
                       "「验过了」更不真")
    reading: dict[str, Any] = {
        "checked": False,
        "state": "unknown",
        "project_root": str(project),
        "workspace_root": str(workspace),
        "package": str(package),
        "mapping_json": str(json_path),
        "mapping_md": str(md_path),
        "rows": 0,
        "envs": len(envs),
        "statement_envs": len(statement_envs),
        "statement_surplus": [],
        # 六类环境"该印什么抬头"的读数（业主 2026-11-07：example 用 Example 环境）。
        # 与 `kind_gap` / `theorem_unsigned` 同族：纯读、不拦门；判它红不红是调用方的事。
        "environments": {"checked": False, "titles": {}, "rows": [],
                         "unknown": [], "mismatched": []},
        "tex_files": list(tex_files),
        "md_state": "",
        "appendix_state": "",
        "lean_state": lean_state,
        "lean": {"enabled": bool(lean_on), "source": lean_source, "state": lean_state,
                 "artifacts": list(artifacts[:20]), "artifact_count": len(artifacts),
                 "target_kinds": list(LEAN_TARGETED_KINDS), "reason": lean_reason},
        "empty_files": [],
        # ---- 台账那两格与两条落差读数（D-69）：先给空形状，填不到就是"没读到"。
        # 它们都不进 `problems`：业主的边界是"先让它看得见"，不拦门。
        "ledger_cells": {"checked": False, "rows": 0, "filled": 0,
                         "missing": [], "stale": []},
        # 论文侧写了哪些 stmt/exp/lit（两处来源取并集；§`paper_citations`）。
        "paper_citations": {"checked": False, "items": [], "counts": {}},
        "kind_gap": {"count": 0, "items": [], "why": ""},
        "theorem_unsigned": {"count": 0, "items": [], "unreadable": [], "why": ""},
        #: 承重行与「它自己的稿与签」的读数（2026-11-26 BEARINGDEF）：这是 G 侧那张
        #: 表的同一份读数（`load_bearing_gaps`）；其中缺稿 / 缺签的行另由
        #: `_proof_index_problems` 折成 `mapping_load_bearing_*` 进 `problems`。
        "load_bearing": {"checked": False, "rows": 0, "gaps": [], "complete": 0,
                         "unreadable": [], "checked_rows": 0, "why": ""},
        #: 顺序那一轴（2026-11-26 GMAP）：依赖 DAG 的拓扑序 + 编号按 C 的路径。
        #: `checked` = 两问都真的判了；缺材料的那一问 `checked=False`（没查成，不是通过）。
        "order": {"checked": False,
                  "dag": {"checked": False, "edges": 0, "checked_edges": 0,
                          "unpositioned": [], "why": ""},
                  "path": {"checked": False, "source_report": "", "declared": 0,
                           "reports": 0, "nodes": 0, "rows": 0, "chapters": 0,
                           "numbering": {"checked": False, "numbered": 0, "missing": []},
                           "why": ""},
                  "problems": [], "why": ""},
        "problems": [],
        "warnings": [],
        "reason": "",
    }
    if lean_state == "on_no_artifact":
        reading["warnings"].append(_problem(
            "lean_on_but_no_artifact",
            "Lean 开关开着（来源：" + (lean_source or "缺省") + "），而盘上一个 Lean 产物都没有"
            "（找过论文包内的 `" + LEAN_SUFFIX + "` 与 `<项目根>/"
            + "`, `<项目根>/".join(LEAN_ARTIFACT_DIRS) + "`）—— 这一档不拦门（它说的不是"
            "「表与正文对不上」，而是「这一趟的形式化一个文件都没落」），但它必须看得见："
            "否则两格空白会被读成「验过了」"))

    if not json_path.is_file():
        if not has_paper:
            reading["reason"] = (
                f"这个项目没有论文正文（{package / PC.TEX_NAME} 不在盘上），论文包里也没有对应表"
                " —— 这一格不适用（不是通过）")
            return reading
        reading["checked"] = True
        reading["state"] = "fail"
        problems = [_problem(
            "mapping_package_missing",
            f"论文包里没有对应表：{json_path} —— 有正文却没有表，是没产出（不是没查成）；"
            f"G 要先写 `out/package/{MAPPING_JSON_NAME}`，再渲染 md 与附录，最后才编 PDF")]
        for stray in _stray_mapping_copies(project, workspace):
            problems.append(_problem(
                "mapping_missing",
                f"表放在了论文包之外：{stray} —— 包外那一份不算数（它不随论文一起交付，"
                f"H 与业主读不到）；把它移到 {json_path}"))
        reading["problems"] = problems
        reading["reason"] = ("论文包里没有对应表 ⇒ 这一格是红的（有正文、没交表）；"
                             "见 problems 里那两条")
        return reading

    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        reading["checked"] = True
        reading["state"] = "fail"
        reading["problems"] = [_problem(
            "mapping_unresolvable",
            f"对应表在包里但读不出来：{json_path}（{type(exc).__name__}: {exc}）")]
        reading["reason"] = "表在包里、但没有一行是能读的（先修 json 语法）"
        return reading

    rows, problems = parse_rows(payload)
    reading["rows"] = len(rows)
    reading["checked"] = True
    # 六类环境"该印什么抬头"的读数（纯读，不进 problems）：`kind=example` 的行要在
    # 正文里印成 Example —— 这一格把"该印什么"与"导言区真声明成什么"逐行摆在一起。
    reading["environments"] = environment_titles(rows, tex=tex_text)
    # 正文读不完（成环 / 超深 / \\input 指的文件读不到）与表无关，但它决定了
    # "正文里有没有这个环境"这一格能不能信 —— 所以它与表的问题一起进 problems。
    problems += body_problems

    md_state, md_problems = _md_reading(project, rows)
    reading["md_state"] = md_state
    problems += md_problems

    if not has_paper:
        reading["problems"] = problems
        reading["state"] = "unknown"
        reading["reason"] = (f"这个项目没有论文正文（{package / PC.TEX_NAME} 不在盘上），"
                             "对应表没有可对的东西（不适用，不是通过）")
        return reading

    appendix_state, appendix_problems = _appendix_reading(project, tex_text, rows)
    reading["appendix_state"] = appendix_state
    problems += appendix_problems

    problems += _orphan_problems(envs, rows)
    known = ledger if ledger is not None else read_ledger_tables(workspace)
    # 凭据那一档（`mapping_lean_*`）只在 `LEAN_KINDS` 非空时才判（见 `_lean_problems`
    # 的 docstring：清空那一组就是关掉这一档，反真空用例靠它）。它要台账：那一条命题
    # 的证明通道（数值 / 形式化 / 空）的真身在 `numericproof.formal_slot`，而通道要
    # 读这一号证明的正文与 E 签的穷举实验行 —— 所以这里先读台账，再判凭据格。
    if LEAN_KINDS:
        problems += _lean_problems(rows, package, project, known)
    # 审校台账那份三态按命题号归并读一遍（`reviewed` 那一格的四档要用它，
    # 渲染函数自己不读盘 —— 见 `reviewed_cell`）。
    review_states = _review_ledger_states(workspace, rows, known)
    # ---- 台账那两格与两条落差读数（D-69）：都是纯读、都不拦门。
    #
    # 位置在 `known` 之后、逐行校验之前：这三项问的是"论文与台账现在的关系"，
    # 与"表与正文对不对得上"是两件事 —— 混进 `problems` 就等于把它们当门，
    # 而业主的口径是先让它看得见（`kind_gap` / `theorem_unsigned` 都不在
    # `ALL_PROBLEM_KINDS` 里）。
    reading["ledger_cells"] = ledger_cells_reading(rows, known,
                                                   review_states=review_states)
    # 论文侧引用 ↔ 表行（2026-11-25，MAPPING-COMPLETE）：只有这一趟真的登记过论文行
    # （`documents(kind="paper")`，`doc.build_document` 是成文四步的第 ⓪ 步）且表里有行
    # 才查。两个条件缺一不可：
    #   - 没有论文行 ⇒ 这一轴"没查成"（三态 `checked=False`）；
    #   - 表是 0 行 ⇒ 这篇论文没有定理类环境 / 被引实验行可对（`write_package(root, [])`
    #     的合法形态），引用轴没有对照物 —— 报"论文引了 X 而表里没有"会把"这张表本来
    #     只登记环境"读成"漏登记"（收工门 / 空工作区夹具正是这一档：它们只造论文注记，
    #     不造任何定理环境）。空表本身由 `_orphan_problems` 的正文侧管：正文里有定理类
    #     环境而表是 0 行，那一条照样红。
    paper_rows = paper_documents(read_document_rows(workspace))
    active = bool(paper_rows) and bool(rows)
    citations = paper_citations(project, workspace_root=workspace, tex=tex_text)
    counts: dict[str, int] = {}
    for item in citations:
        counts[item["prefix"]] = counts.get(item["prefix"], 0) + 1
    why = ""
    if not paper_rows:
        why = ("台账里没有 `documents(kind=\"paper\")` 那一行 ⇒ 论文侧引用没查成"
               "（不是「没引」：没登记论文的包不参与这一轴）")
    elif not rows:
        why = ("对应表是 0 行 ⇒ 这篇论文没有定理类环境 / 被引实验行可对"
               "（引用轴没有对照物，不是「引用都齐了」）")
    reading["paper_citations"] = {"checked": active, "items": citations,
                                  "counts": counts, "why": why}
    if active:
        problems += _paper_citation_problems(rows, citations, known, workspace, envs)
        problems += _literature_problems(citations, workspace)
    reading["kind_gap"], reading["theorem_unsigned"] = kind_gap_reading(
        rows, known, review_states=review_states)
    # 承重行「自己的稿与签」：G 侧那张表（`load_bearing_gaps`）是唯一读数，
    # 收工门读同一份（`_proof_index_problems` 只把它折成问题，不另判一次）。
    reading["load_bearing"] = load_bearing_gaps(
        project, workspace_root=workspace, ledger=known, tex=tex_text, rows=rows)
    if EVIDENCE_KINDS:
        problems += _proof_index_problems(rows, reading["load_bearing"],
                                          known, workspace)
    gap_notes = [str(reading["kind_gap"].get("why") or ""),
                 str(reading["theorem_unsigned"].get("why") or "")]
    gap_notes = [text for text in gap_notes if text]
    load_note = str(reading["load_bearing"].get("why") or "")
    # 数值实验定理那一支要读"定理那一段"：真遇上这种行时才去扫（扫一遍要把 `\input`
    # 跟完，不该为一份全是自然语言证明的稿子付这份成本）。`None` = 还没扫过。
    segments: dict[str, str] | None = None
    seen_targets: dict[tuple[str, int], Row] = {}
    for row in rows:
        got = _row_checks(row, known, package, workspace)
        problems += got.problems
        if got.ledger_row is not None:
            key = (str(row.ledger_id).split("#")[0], int(row.proof_no))
            prev = seen_targets.get(key)
            if prev is not None:
                problems.append(_problem(
                    "mapping_orphan",
                    f"表里 {row.ledger_id} 的第 {row.proof_no} 条证明被登记了两次"
                    f"（label={prev.label!r} 与 label={row.label!r}）—— 同一条证明只能占一行，"
                    "两行指同一个 (命题, 证明号) 就是互相顶替",
                    label=row.label, where=MAPPING_JSON_NAME))
            seen_targets[key] = row
        origin = ""
        if isinstance(got.ledger_row, Mapping) and str(row.ledger_id).startswith("stmt:"):
            origin = str(got.ledger_row.get("origin") or "")
        problems += _citation_problems(row, package, origin)
        if NUMERIC_KINDS and is_numeric_theorem_row(row, known):
            if segments is None:
                segments = theorem_segments(project, tex=tex_text if tex is not None else None)
            problems += _numeric_problems(row, got.ledger_row, known, workspace, segments)

    for row in rows:
        state = (NT.program_state(workspace, row.file) if is_numeric_row(row, known)
                 else file_state(package, row.file))
        if state["state"] == "empty":
            reading["empty_files"].append(state["file"])

    # 一条命题对一个环境（业主 2026-10-24，D-40）：正文的定理类环境里，凡认领不到
    # 一条台账命题的那些（表里没行 / 指的是概念行 / 命题被别人用了）都要被点名。
    surplus_problems, surplus_labels = _statement_surplus_problems(
        statement_envs, rows, known)
    problems += surplus_problems
    reading["statement_surplus"] = list(surplus_labels)

    # 顺序那一轴（2026-11-26 GMAP）：材料都在盘上（依赖表 + C 的报告），判据只有一份。
    env_index: dict[tuple[str, str], tuple[int, int]] = {}
    for i, env in enumerate(envs):
        env_index.setdefault((str(env.kind), str(env.label)),
                             (i, sections[i] if i < len(sections) else 0))
    reading["order"], order_problems = order_reading(
        rows, env_index, known, workspace, payload=payload)
    problems += order_problems

    reading["problems"] = problems
    if problems:
        reading["state"] = "fail"
        counts: dict[str, int] = {}
        for item in problems:
            counts[item["kind"]] = counts.get(item["kind"], 0) + 1
        reading["reason"] = ("表在包里、但有 {n} 处问题（{by}）—— 逐条见 problems".format(
            n=len(problems), by="、".join(f"{k} {v}" for k, v in counts.items())))
        if surplus_labels:
            # 拒信本身就要点名（只给一个计数等于让读者自己去翻 problems）。
            reading["reason"] += (
                "；正文多出 " + str(len(surplus_labels)) + " 个定理类环境，"
                "台账里没有对应命题：" + "、".join(surplus_labels[:8])
                + ("等" if len(surplus_labels) > 8 else ""))
    else:
        reading["state"] = "pass"
        reading["reason"] = (f"{len(rows)} 行与正文 {len(envs)} 个环境逐一对上，附录逐字一致，"
                             "`ledger_id` 与 `proof_no` 都能在台账里解析到，`file` 都在包里；"
                             f"正文 {len(statement_envs)} 个定理类环境对着 "
                             f"{len(proposition_statement_ids(known))} 条台账命题，一条命题对一个环境")
    # 两档都写进 reason：`pass` 不等于"什么都没剩"，`warnings` 与 Lean 那一格必须被看见
    # （三态纪律：把"没开 Lean / 没有 Lean 产出"与"验过了"折成同一个沉默是本项目最忌的形态）。
    reading["reason"] += "；Lean：" + lean_reason
    if reading["warnings"]:
        reading["reason"] += "；另有警告 " + "、".join(
            sorted({str(w.get("kind") or "") for w in reading["warnings"]}))
    # 落差读数（D-69 ②）：两条都在 `reason` 里点名，且都写明"读数，不拦门"——
    # 它们是"看得见"的那一半，拦不拦由 H 与收工门另外判（都不进 `problems`）。
    if gap_notes:
        reading["reason"] += "；落差读数（不拦门）：" + "；".join(gap_notes)
    if load_note:
        reading["reason"] += "；承重缺口读数：" + load_note
    # 顺序那一轴：checked=False 必须在这句话里显形 —— `pass` 那句话不能说成"顺序没问题"。
    order = reading["order"]
    if order.get("checked"):
        reading["reason"] += (
            "；顺序轴（已判）：依赖 DAG 拓扑序看过 "
            f"{order['dag'].get('checked_edges', 0)} 条边，编号按 C 的路径报告 "
            f"report:{order['path'].get('source_report') or '?'}"
            f"（{order['path'].get('nodes', 0)} 个节点 / {order['path'].get('chapters', 0)} 章）")
    else:
        reading["reason"] += (
            "；顺序轴**没查成**（checked=False，不是「顺序没问题」）："
            + (order.get("why") or "缺材料"))
    cells = reading["ledger_cells"]
    if cells.get("missing"):
        reading["reason"] += (
            "；另有 " + str(len(cells["missing"])) + " 行没有台账那两格"
            "（旧表）—— 重跑一次 `doc.write_mapping` 就会按台账填上")
    if cells.get("stale"):
        reading["reason"] += (
            "；另有 " + str(len(cells["stale"])) + " 行的台账那两格与台账现在的读数不一致"
            "（表写完之后台账又动过，或者表被手改过）—— 重跑一次 `doc.write_mapping`")
    return reading

