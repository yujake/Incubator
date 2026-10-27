# -*- coding: utf-8 -*-
"""论文对应表（业主 2026-10-22）：G 写正文之前先有这张表，H 依据它逐行核。

业主原话：「G 产出论文时需附上对应表，说明每条定理、引理、命题、例子、实验对应产出物的
真实文件和序号是什么，H 依据此核查，G 也依据此写作」。

## 三个落点、一份内容（都在论文包里）

论文包就是 `main.tex` / `main.pdf` 所在那一个目录（`papercompile.package_dir`，通常是
`out/paper/`）。下面三份都住在包里，包外那一份不算数：

- `<论文包>/MAPPING.json`：机器读，唯一真身。本模块是它唯一的读侧（解析 + 校验）；
- `<论文包>/MAPPING.md`：人读，由 json 生成（`render_mapping_markdown`）。不许手写第二份；
- `<论文包>/mapping-appendix.tex`：正文附录（`附录：产出对应表`），由 json 生成
  （`render_appendix`），`main.tex` 用 `\\input{mapping-appendix}` 把它印进 PDF。

生成顺序是死的：先写 json -> 由 json 渲染 md 与附录 -> 再编 PDF。改完正文必须重编一次
（`doc.paper_compile`），否则 `closing` 的 `paper` 那一格会报"PDF 是旧正文编的"。

## 每一行的字段与口径

| 字段 | 必填 | 口径 |
|---|---|---|
| `kind` | 是 | 受控词表 `ENV_KINDS`（theorem / lemma / proposition / corollary / example / experiment） |
| `label` | 是 | 正文里那个 `\\label{...}` 的值（不带花括号） |
| `env_no` | 是 | 正文里第几个该环境，1 起，按正文出现顺序按类计数（theorem 单独数、lemma 单独数；分节 `\\input` 进来的按内联顺序算） |
| `ledger_id` | 是 | `stmt:NNNNNN` / `exp:NNNNNN` / `rel:NNNNNN`；多证明带 `#pN`（`stmt:000004#p2`） |
| `proof_no` | 是 | 这条定理名下第几号证明：1 = canonical（台账行上的 `proof_text`）；2 及以上 = 该行 `proofs` 清单里那一份 |
| `file` | 是 | 该条完整证明或实验所在的真实文件，论文包内的相对路径（`proofs/000004-p1.md`） |
| `page_or_section` | 否 | 给人看的定位（`3` / `p.7`） |
| `citation_loc` | 视来源 | 引文的本地位置：`{"file": 包内相对路径, "page_range"|"line_range"|"char_range": [起点, 终点]}` |
| `citation_loc_reason` | 视来源 | 不给 `citation_loc` 时那句理由 |
| `lean_file` | 有 Lean 产出时 | Lean 程序的真实位置：项目根相对路径（`code/formal/000004.lean` —— L 把源码落在这里）；论文包内那种写法（`formal/000004.lean`）也认。绝对路径与两个根之外的路径都红 |
| `lean_target` | 有 Lean 产出时 | 它验的是哪一条：Lean 里那个声明的名字（`FreeGroupFactor.isII1`），必须真的出现在 `lean_file` 里 |

`file` 与 `citation_loc.file` 都是包内相对路径：绝对路径在别人的机器上等于不存在，
而指向包外的相对路径同样过不了"换一台机器也能复核"这一关（两者都判红）。

`lean_file` 是唯一收「项目根相对路径」的那一格（2026-10-25，审计 G/H/V/L 第 4 条）：
L 的产物落在 `code/formal/`（`agent_l._support.FORMAL_DIR`），而论文包是 `out/paper/`，
全仓没有任何一步把前者拷进后者 —— 只认包内相对路径时，那条真实存在的源码永远填不进
这一格（三个落点各说各话）。所以这一格两个根都解析：先按包内找，找不到再按项目根找。

### `proof_no` 的口径

多证明时 `ledger_id` 与 `proof_no` 说的是同一件事：`stmt:000004#p2` 的 `proof_no` 必须是 2。
`proof_no` 不许省：默认成 1 会让"没写"与"第 1 条"分不开，而多证明模型要挡的正是这个。
它解析到哪一份证明只走 `verifications.proof_list`（`#p1` 恒在且排第一），不在这里
重写那份清单的读法。`file` 的指向随之分档：`proof_no` = 1 指台账行本身或附录里那一段正文，
2 及以上指那一份证明自己的文件。

### `citation_loc` 的三态

- 台账行 `origin="external_lit"`（从文献摘的）=> 必填，缺就是 `mapping_citation_loc_missing`；
- `origin="own_result"`（我们自己得的）=> 允许为空，但必须给 `citation_loc_reason`；
  两样都没有 => 同样是 `mapping_citation_loc_missing`；
- 给了 `citation_loc` 而它那个 `file` 不在包里 => `mapping_citation_file_missing`。

区间三种任选其一（至少一种），值写成 `[起点, 终点]` 或 `{"start": ..., "end": ...}`，
两者都必须是正整数且起点不大于终点。

### Lean 那两格的三态（业主 2026-10-22 追加）

业主原话：「有 Lean 产出时，还要写明 Lean 程序的位置与它验的是哪条定理/哪条证明」。五档：

- Lean 开关关（读 `settings.lean_enabled`，与 `closing` 那一处是同一个口径）=> 两格允许为空，
  读数里写「未开 Lean」；空绝不等于验过 —— 这一趟的证明走 `proof_text` 与 V 的逐行审校；
- 开关开、且盘上有 Lean 产物（论文包内任意 `*.lean`，或 `<项目根>/out/formal/` / `<项目根>/code/formal/`
  下的产物）=> 每条 theorem / lemma / proposition / corollary 行必须给这两格，缺就是
  `mapping_lean_missing`；
- `lean_file` 不是 `.lean`、或在论文包与项目根两处都找不到 => `mapping_lean_file_missing`；
- `lean_target` 在那一份 `.lean` 里找不到（做词边界匹配，`foo` 不算命中 `foobar`）
  => `mapping_lean_target_missing`；
- 同一个 `lean_target` 出现在两行 => `mapping_lean_target_ambiguous`。一条命题有多条证明时，
  允许两行共用一个 `lean_file`，但那两行的 `lean_target` 必须各自不同（各自那份 `.lean`
  里验它的声明名）。

开关开、却一个 Lean 产物都没有 => 读数里有一档 `lean_on_but_no_artifact`（`warnings`，
不拦门；见 `LEAN_WARN_KINDS`）：两格无从填起这件事必须看得见，但它说的不是
"表与正文对不上"。两格里只要填了一格（哪怕开关关着），就要当真核 —— 只填一半同样是
`mapping_lean_missing`：填了就是声称，声称就得能复核。

### 数值实验定理那两格（业主 2026-10-23 的裁定 E-1）

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

哪一行算"数值实验定理"：它是 theorem / lemma / proposition / corollary，且它登记的那条
命题的 `proof_text` 本身就是程序（`numericproof.is_script_path`），或者它自己填了那两格。
其余行（例子、实验、自然语言证明的定理）一格都不要动 —— 防误伤那一条判据就在
`tests/test_numeric_theorem_writing_spec.py` 第 4b 条。

### 索引四格（D-34，业主 2026-10-23 夜：D 的报告是目录）

业主那三句话把这条链的模型说死了：D 的报告是目录（新成果＋索引），F 的证明 / E 的报告是
正文，V 的签是盖章，B 是读者 ——「B 基本都是从 D 的报告看到定理（命题），经索引看 F 侧
证明或 E 侧报告，并核实 V 签」。于是数值实验定理那一行（以及任何"正文在别处"的行）还要
带四格，缺一件 B 就取不到正文：

| 格 | 键 | 口径 |
|---|---|---|
| 正文是哪一档 | `evidence_kind` | `report`（E 的报告）/ `proof`（F 的证明） |
| 正文在哪 | `evidence_path` | 相对仓库根（`out/experiments/000000/exhaustion.md`） |
| 正文的指纹 | `evidence_sha256` | 那份文件字节的 sha256 |
| V 的签 | `v_signature` | `{"verdict": "成立", "sha256": <被签那一份的 sha256>}` |

这四格的列义只有一份（`numericproof.INDEX_*`），判据也只有一份
（`numericproof.resolve_index`：四格齐 => 读盘 => 算 sha256 => 与 `evidence_sha256` 和
`v_signature.sha256` 各比一次）。本模块那一档拦门（`mapping_numeric_evidence_missing`，
判据本体 `numerictheorem.evidence_index_problems`）与 B 的入库闸读的是同一个函数 ——
不许出现第二份口径，否则会出现"B 认、G/H 不认"的分家。
四格只进 `MAPPING.json`（机器读那一份）：md 与附录的列已经排满，加列会让旧附录整份对不上，
而那两份的用途是给人看"哪一行对应哪一份文件"，不是给 B 取对象。

### 台账那两格（D-69，2026-10-24：让「论文说定理 / 台账说猜想 / V 签没签」自己暴露）

业主原话（D-69）：「论文对应表要能自己暴露『论文说定理 / 台账说猜想 / V 签没签』」。
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

`reviewed` 的取值是三态，空着不许折成任何一边：

- `已签（判决：成立）`：逐份那张表里这一份为真，且 `reviewed_by` 记着判决原话；
- `没签`：逐份那张表里这一份为假（签过别的证明不算 —— 不许借光）；
- `未读到`：台账里没有这一行 / 这一份在逐份表里没有键 / 判决原话那一格读不到。
  三种都是「读不到」，不是「没签」。

`ledger_kind` 同样是三态：台账行在就写它的 `kind`；台账行读不到（或那一行的 `kind`
是空的）就写 `未读到`。渲染器最后这一道（`_ledger_kind_cell` / `_reviewed_print_cell`）保证
这三格永远不会印成空白 —— 空白会被读成"没问题"，而这三态里没有一档是"没问题"。

### 落差读数（D-69 ②：先让它看得见，不拦门）

`mapping_reading` 多两格读数，两格都只说、不判：

- `kind_gap`：论文里以 theorem / lemma 环境出现、而台账 `kind` 仍是 `conjecture`
  的行，逐条 `label → stmt:NNNNNN`（业主原话）；
- `theorem_unsigned`：论文里排成定理而 V 没签的行；签没签读不到的那几行单列进
  `unreadable`，不算进"没签"（三态：没查成不是结论）。

两格都不进 `problems`、不进 `ALL_PROBLEM_KINDS`，所以它们不改 `state`、不改收工门的
八格、不给 `Finding`；它们进 `reason`（成文与收工那句话读得到）与 `readings`
（`closing.mapping_gaps` 转发）。为什么不拦：这一档量的是"论文与台账现在的关系"，
而拦门的判据是"表与正文对不对得上" —— 把前者做成门，每一份"论文先写、账后改"的稿子
都会红；但看不见更不行，sylow3 那三行正是这样一路静默到收工。

加了两格之后，旧论文包（json 里没有这两键）必须重跑一次 `doc.write_mapping`：
md 与附录都是按列逐字比对的，列变了就是 `md_drifted` / `mapping_paper_mismatch`。
读侧把这件事写进 `reason`（"另有 N 行没有台账那两格（旧表）"），不静默。

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
from . import papercompile as PC
from . import proofloc as PL
from . import numericproof as NP
from . import numerictheorem as NT
from . import schema as S
from . import verifications as V

#: 论文包相对项目根的落点（与 `papercompile.package_dir` 同一个目录）。
PACKAGE_SUBDIR: tuple[str, ...] = ("out", "paper")

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
                  " (rendered from out/paper/MAPPING.json; do not edit by hand) ====")
APPENDIX_END = "% ==== MAPPING-APPENDIX END ===="

#: 附录里每一行的机器可读注释
#: （`% MAPPING-ROW kind|env_no|label|ledger_id|proof_no|file|lean_file|lean_target`）。
APPENDIX_ROW_PREFIX = "% MAPPING-ROW "

#: 正文里要进对应表的六类环境（顺序就是 md 与附录里 kind 的推荐顺序）。
ENV_KINDS: tuple[str, ...] = (
    "theorem", "lemma", "proposition", "corollary", "example", "experiment",
)

#: 有 Lean 产出时必须给 `lean_file` + `lean_target` 的那几类环境（业主 2026-10-22 追加）。
#:
#: 为什么不是全部六类：例子与实验不是"被 Lean 验的命题"，它们没有声明名可写。
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

#: Lean 那两格（`lean_file` / `lean_target`）：有 Lean 产出时必填，其余时候允许为空。
LEAN_ROW_FIELDS: tuple[str, ...] = ("lean_file", "lean_target")

#: Lean 产物的后缀（`lean_file` 必须是它结尾）。
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

#: Lean 那两格的三种占位写法（空着时按开关状态印出来，不印空白）。
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

#: 这两格的键（写进 json、进 md、进附录，三处同源）。
LEDGER_CELL_FIELDS: tuple[str, str] = (LEDGER_KIND_FIELD, REVIEWED_FIELD)

#: 三态里"读不到"那一档的写法（台账行不在 / 逐份签名表没有这一份 / 判决原话空）。
#:
#: 它不许折成 `没签`，也不许折成"已签"：读不到是"这一格没查成"，而"没签"是一个
#: 关于 V 做过什么的结论 —— 两者在报告里长得一样是本项目最忌的形态。
LEDGER_CELL_UNREADABLE = "未读到"

#: 逐份签名表里这一份为假时的写法（签过别的证明不算，不许借光）。
REVIEWED_UNSIGNED_CELL = "没签"

#: 签了之后的写法（`已签（判决：<判决原话>）`）。
REVIEWED_SIGNED_TEMPLATE = "已签（判决：{verdict}）"

#: 论文里"排成定理"的那几类环境（D-69 的落差读数按它判）。
#:
#: 只收 theorem / lemma：业主点名的是"论文里以 theorem/lemma 环境出现"。
#: proposition / corollary 不在这一组里 —— 它们也是被证明的命题，但"说成定理"这句话
#: 指的是这两个环境名，把四件套全收进来会让读数与业主那句话对不上。
THEOREM_ENV_KINDS: tuple[str, ...] = ("theorem", "lemma")

#: 台账里"还只是猜想"的那一档（落差读数的一半）。
CONJECTURE_KIND = "conjecture"

#: 每一行的必填字段（其余见 `OPTIONAL_ROW_FIELDS` 与 `CONDITIONAL_ROW_FIELDS`）。
ROW_FIELDS: tuple[str, ...] = (
    "kind", "label", "env_no", "ledger_id", "proof_no", "file",
)

#: 数值实验定理那两格（业主 2026-10-23，E-1）：口径与判定在 `numerictheorem`，这里只转发。
NUMERIC_ROW_FIELDS: tuple[str, ...] = NT.NUMERIC_ROW_FIELDS

#: 可以不给的字段。
OPTIONAL_ROW_FIELDS: tuple[str, ...] = ("page_or_section",)

#: 按来源决定要不要给的字段（口径见模块 docstring 的 `citation_loc` 三态）。
CONDITIONAL_ROW_FIELDS: tuple[str, ...] = ("citation_loc", "citation_loc_reason")

#: `citation_loc` 里三种区间（至少给一种）。
RANGE_KEYS: tuple[str, ...] = ("page_range", "line_range", "char_range")

#: 能解析的台账前缀（表名从 `schema.citation_prefix_table` 取，不在这里抄第二份）。
LEDGER_PREFIXES: tuple[str, ...] = ("stmt", "exp", "rel")

#: 能承载 `ledger_id` 的三张台账表。
LEDGER_TABLES: tuple[str, ...] = ("statements", "experiments", "relations")

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

#: Lean 那两格的四条（业主 2026-10-22 追加；口径见模块 docstring 的 Lean 三态）。
#:
#: `mapping_lean_missing`：开关开、有 Lean 产出，而某条定理/引理/命题/推论行没给两格
#: （或只给了一格 —— 填了就是声称，声称就得能复核）；
#: `mapping_lean_file_missing`：`lean_file` 不是 `.lean`，或不在论文包里；
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
#: 但"两格无从填起"这件事必须看得见（空着与"验过了"要分得开），所以它在 `warnings` 里。
LEAN_WARN_KINDS: tuple[str, ...] = ("lean_on_but_no_artifact",)

#: 数值实验定理那一组（业主 2026-10-23，E-1）：证明栏是程序、三块与署名由 E 给。
#:
#: 真身在 `numerictheorem.NUMERIC_KINDS`（这里只是别名，别处不另抄一份）：缺程序路径、
#: 程序没有 E 签的穷举证明、缺 E 的读数编号、缺块 / 缺署名 / 缺出处、正文那段指不回读数。
NUMERIC_KINDS: tuple[str, ...] = NT.NUMERIC_KINDS

#: 本模块会产出的全部问题类别（判据要逐类覆盖它，见 `tests/test_paper_mapping_table.py`）。
#:
#: 只收拦门的那几组：`LEAN_WARN_KINDS` 不进这里（它在 `warnings` 里，不改 `state`）。
ALL_PROBLEM_KINDS: tuple[str, ...] = (
    MAPPING_KINDS + CITATION_KINDS + MD_KINDS + PAPER_KINDS + LEAN_KINDS + NUMERIC_KINDS
)

#: 三态取值。
STATES: tuple[str, ...] = ("pass", "fail", "unknown")

#: `file` 的五个状态（`present` 之外的四个各自有判据）。
FILE_STATES: tuple[str, ...] = ("present", "empty", "missing", "directory", "outside")

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
    file: str
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
    #: `{"verdict": "成立", "sha256": <被签那一份的 sha256>}`。
    v_signature: Mapping[str, Any] | None = None
    #: ---- 台账那两格（D-69）：不手填，由 `fill_ledger_cells` 现读现填 ------------
    #:
    #: `ledger_kind` 是台账那一行自己的 `kind`；`reviewed` 是 V 签没签 + 判决原话。
    #: 空串 = 这一格没填（旧表 / 还没填过）—— 渲染时印 `未读到`，不印空白。
    ledger_kind: str = ""
    reviewed: str = ""

    def to_dict(self) -> dict[str, Any]:
        """写回 json 的形状（字段顺序固定，diff 才读得懂）。"""
        out: dict[str, Any] = {"kind": self.kind, "label": self.label,
                               "env_no": int(self.env_no), "ledger_id": self.ledger_id,
                               "proof_no": int(self.proof_no), "file": self.file,
                               # 台账那两格（D-69）：三份同源的第一份。旧表没有这两键，
                               # 那一档由读侧读成 `未读到`（不许读成"已签"或"没签"）。
                               LEDGER_KIND_FIELD: self.ledger_kind,
                               REVIEWED_FIELD: self.reviewed}
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
        if self.v_signature is not None:
            out[NP.INDEX_SIGN_FIELD] = dict(self.v_signature)
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


def package_dir(project_root: str | Path) -> Path:
    """论文包目录（`<项目根>/out/paper`，与 `papercompile` 同一处——不另写一份路径）。"""
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


def _body_envs_of_package(package: Path, main_path: Path, main_text: str
                          ) -> tuple[list[BodyEnv], list[BodyEnv], list[str],
                                     list[dict[str, Any]]]:
    """正文那一侧的完整读数：环境、定理类环境（含印成 Lemma 的自定义宏）、这次读了
    哪几个文件（读入顺序）、读不完的问题。

    为什么两列分开返回：`envs` 是对应表那六类（表行按它登记），`statement_envs` 多认
    那些"印出来是 Lemma"的自定义宏 —— 只有"一条命题对一个环境"那一条读第二列。
    把两列合成一列会让每一份用了 `claim` 宏的正文都要求表里多出几行没有 `kind` 可写的行。
    """
    segments, files, problems = _collect_tex_segments(package, main_path, main_text)
    counts: dict[str, int] = {}
    envs: list[BodyEnv] = []
    names = statement_env_names(main_text)
    statement_counts: dict[str, int] = {}
    statement_envs: list[BodyEnv] = []
    for rel, segment, line_offset in segments:
        envs.extend(_scan_envs(segment, counts, where_file=rel, line_offset=line_offset))
        statement_envs.extend(_scan_envs(segment, statement_counts, where_file=rel,
                                         line_offset=line_offset, kinds=names))
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


def read_ledger_tables(workspace_root: str | Path) -> dict[str, list[Mapping[str, Any]]]:
    """从盘上读三张台账表（`<工作区>/data/<表文件>`）。

    为什么读盘而不是读 store：这一格要在收工门里跑，而收工门有"运行外"的出口
    （`agentflow closing`）—— 那里没有 store，只有工作区目录。
    读不出来（不在盘上 / 坏 JSON）就返回空表，由"代号在表里找不到"报出来。
    """
    root = Path(workspace_root)
    out: dict[str, list[Mapping[str, Any]]] = {}
    for table in LEDGER_TABLES:
        name = str((S.TABLES.get(table) or {}).get("file") or "")
        rows: list[Any] = []
        if name:
            path = root / "data" / name
            if path.is_file():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    payload = None
                if isinstance(payload, Mapping):
                    rows = list(payload.get("rows") or [])
                elif isinstance(payload, list):
                    rows = list(payload)
        out[table] = [r for r in rows if isinstance(r, Mapping)]
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


def reviewed_cell(ledger_row: Mapping[str, Any] | None, proof_no: Any) -> str:
    """V 签没签 + 判决原话（`reviewed` 那一格）。

    判据只有一处：逐份那张表走 `evidencebits.reviewed_by_proof`（写侧
    `verifications._reviewed_statement_row` 落的同一张表）；判决原话走
    `bits.evidence.reviewed_by.verdict`。

    三态（业主 D-69 口径：读不到不许折成任何一边）：

    - 台账行读不到 / 逐份表里没有这一份 ⇒ `未读到`（这一格没查成）；
    - 这一份为假 ⇒ `没签`（签过别的证明不算 —— 不许借光）；
    - 这一份为真 ⇒ `已签（判决：<原话>）`；原话那一格读不到、或者它记的是另一份
      证明的签 ⇒ `已签（判决：未读到）`：签过这件事读得出来，判决对不对得上这一份
      读不出来，两件事分开写。
    """
    if not isinstance(ledger_row, Mapping):
        return LEDGER_CELL_UNREADABLE
    no = _int_or_none(proof_no)
    if no is None:
        return LEDGER_CELL_UNREADABLE
    per = EB.reviewed_by_proof(ledger_row)
    if int(no) not in per:
        return LEDGER_CELL_UNREADABLE
    if not per[int(no)]:
        return REVIEWED_UNSIGNED_CELL
    by = _reviewed_by_of(ledger_row)
    told = str(by.get("verdict") or "").strip()
    # `reviewed_by` 只有一格（最近那一签）。它记的是哪一份，就只给那一份背书：
    # 多证明时拿 #p1 的判决原话替 #p2 说话，等于让一份签替另一份签作证。
    said = _int_or_none(by.get("proof_no"))
    if said is not None and int(said) != int(no):
        told = ""
    return REVIEWED_SIGNED_TEMPLATE.format(verdict=told or LEDGER_CELL_UNREADABLE)


def ledger_cells(ledger_row: Mapping[str, Any] | None, proof_no: Any) -> dict[str, str]:
    """一行的台账两格（`{ledger_kind, reviewed}`；三态口径见上面两个函数）。"""
    return dict(zip(LEDGER_CELL_FIELDS,
                    (ledger_kind_cell(ledger_row), reviewed_cell(ledger_row, proof_no))))


def fill_ledger_cells(ledger_root: str | Path,
                      rows: Iterable[Row], *,
                      ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None = None
                      ) -> list[Row]:
    """按台账把每一行的两格现读现填（D-69 的唯一填充口；纯读、不改盘）。

    为什么要填而不是让 G 写：这两格说的是台账那一行的事实（`kind`）与 V 的读数，
    G 只能抄。抄错一位就是"表与台账对不上"而没有东西会报错 —— 所以写侧现读现填，
    G 手填的值会被这一次现读盖掉。

    `ledger_root` 是"`data/` 那一层在谁下面"，也就是工作区根（与
    `mapping_reading(workspace_root=…)` 同一处口径：台账在 `<工作区>/data/<表文件>`）。
    论文包可能挂在项目子目录下，所以它不一定是项目根 —— 调用方给哪个就按哪个读。

    三态：`ledger_id` 解析不到、或台账里没有那一行 ⇒ 两格都写 `未读到`（这一格
    没查成，不是"没签"、也不是"不是定理"）。`ledger=None` 时按 `ledger_root` 读盘。
    """
    known = ledger if ledger is not None else read_ledger_tables(ledger_root)
    out: list[Row] = []
    for row in rows:
        resolved = resolve_ledger_id(row.ledger_id, known)
        target = (ledger_row(known, str(resolved["table"]), str(resolved["row_id"]))
                  if resolved["ok"] else None)
        cells = ledger_cells(target, row.proof_no)
        out.append(replace(row, ledger_kind=cells[LEDGER_KIND_FIELD],
                           reviewed=cells[REVIEWED_FIELD]))
    return out


def file_state(package_root: str | Path, rel: Any) -> dict[str, Any]:
    """`file` 那一栏在论文包里是什么状态。

    五态（`FILE_STATES`）：`present`（在、非空）· `empty`（在、0 字节）·
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

    返回值是"盘上到底有没有 Lean 产出、以及它在哪"这个事实的读数；它同时是
    `mapping_reading` 里"两格必填"那一档的判据（有产物 ⇒ 定理类那四类行必须给两格）。
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
    given = [(k, loc.get(k)) for k in RANGE_KEYS if loc.get(k) is not None]
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


def _lean_problems(rows: Sequence[Row], package_root: Path, lean_on: bool,
                   artifacts: Sequence[str],
                   project_root: Path | None = None) -> list[dict[str, Any]]:
    """Lean 那两格（业主 2026-10-22 追加）：什么时候必填、填了要真。

    三件事分开报，一条坏不遮蔽另一条：
    1. 必填而缺（或只填了一半）=> `mapping_lean_missing`；
    2. `lean_file` 不是 `.lean` / 两个根里都找不到 => `mapping_lean_file_missing`；
    3. `lean_target` 在那一份 `.lean` 里找不到 => `mapping_lean_target_missing`；
    外加一条横向的：同一个 `lean_target` 被两行共用 => `mapping_lean_target_ambiguous`。

    "必填"的口径见模块 docstring：开关开、且盘上真有 Lean 产物，才要求定理类那四行给两格。
    这一条只在 `LEAN_KINDS` 非空时才被调用（见 `mapping_reading`）：清空那一组就是关掉这一档，
    反真空用例靠它证明"这些红真的靠那组 kind"。

    `lean_file` 的解析走 :func:`_lean_source_state`（包内优先、项目根兜底）：
    L 的源码在 `code/formal/`，它填不进"只认包内"的那一版（2026-10-25 第 4 条）。
    """
    problems: list[dict[str, Any]] = []
    required = bool(lean_on) and bool(artifacts)
    seen_targets: dict[str, Row] = {}
    for row in rows:
        lean_file = str(row.lean_file or "").strip()
        lean_target = str(row.lean_target or "").strip()
        missing = [name for name, value in (("lean_file", lean_file),
                                            ("lean_target", lean_target)) if not value]
        need = required and row.kind in LEAN_TARGETED_KINDS
        half = bool(lean_file) != bool(lean_target)
        if missing and (need or half):
            why = (f"盘上已经有 {len(artifacts)} 份 Lean 产物（{list(artifacts[:3])}），"
                   "这一行必须说清验它的是哪一份 `.lean` 里的哪一个声明名"
                   if need else
                   "两格是一对：只填一格时，另一格没有任何东西可以复核它")
            problems.append(_problem(
                "mapping_lean_missing",
                f"表里 label={row.label!r}（{row.kind} 第 {row.env_no} 个）缺 {missing} —— "
                f"{why}。`lean_file` 写那份源码的真实位置（项目根相对路径，如 "
                "code/formal/000004.lean；论文包内的写法 formal/000004.lean 也认），"
                "`lean_target` 写 Lean 里那个声明的名字（如 FreeGroupFactor.isII1）",
                label=row.label, where=MAPPING_JSON_NAME))
        file_ok = False
        if lean_file:
            state = _lean_source_state(package_root, project_root, lean_file)
            if not lean_file.lower().endswith(LEAN_SUFFIX):
                problems.append(_problem(
                    "mapping_lean_file_missing",
                    f"表里 label={row.label!r} 的 `lean_file` = {lean_file!r} 不是 Lean 源码"
                    f"（要以 {LEAN_SUFFIX} 结尾）—— 它指的是那份真的被检查器读过的文件",
                    label=row.label, where=MAPPING_JSON_NAME))
            elif state["state"] in ("missing", "directory", "outside"):
                problems.append(_problem(
                    "mapping_lean_file_missing",
                    f"表里 label={row.label!r} 的 `lean_file` 读不到：{state['reason']} —— "
                    "它必须是项目根相对路径（如 code/formal/000004.lean，L 的落点）或论文包内"
                    "相对路径（如 formal/000004.lean）；绝对路径在别人的机器上等于不存在",
                    label=row.label, where=MAPPING_JSON_NAME))
            else:
                file_ok = True
        if lean_target and lean_file and file_ok:
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
        if lean_target:
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
        missing = [f for f in ROW_FIELDS
                   if not str(item.get(f) if item.get(f) is not None else "").strip()]
        if missing:
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行缺必填字段 {missing}（每行必须有 {list(ROW_FIELDS)}）",
                label=str(item.get("label") or "")))
            continue
        kind = str(item.get("kind") or "").strip()
        if kind not in ENV_KINDS:
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行的 `kind` = {kind!r} 不在受控词表 {list(ENV_KINDS)} 里",
                label=str(item.get("label") or "")))
            continue
        label = str(item.get("label") or "").strip()
        env_no = _int_or_none(item.get("env_no"))
        if env_no is None:
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行的 `env_no` 必须是 1 起的整数，收到 {item.get('env_no')!r}",
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
                    if item.get(f) is not None and not isinstance(item.get(f), str)]
        if bad_lean:
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行的 {bad_lean} 必须是字符串（`lean_file` 是包内相对路径、"
                "`lean_target` 是 Lean 里那个声明的名字）",
                label=label))
            continue
        bad_numeric = [f for f in NUMERIC_ROW_FIELDS
                       if item.get(f) is not None and not isinstance(item.get(f), str)]
        if bad_numeric:
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行的 {bad_numeric} 必须是字符串（`numeric_evidence` 是 E 那条读数的"
                "编号 exp:NNNNNN、`exhaustion_note` 是那块读数在仓库里的相对路径）",
                label=label))
            continue
        bad_index = [f for f in (NP.INDEX_KIND_FIELD, NP.INDEX_PATH_FIELD, NP.INDEX_SHA_FIELD)
                     if item.get(f) is not None and not isinstance(item.get(f), str)]
        bad_sign = item.get(NP.INDEX_SIGN_FIELD)
        if bad_index or (bad_sign is not None and not isinstance(bad_sign, Mapping)):
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行的索引格形状不对（{bad_index or [NP.INDEX_SIGN_FIELD]}）："
                "`evidence_kind` / `evidence_path` / `evidence_sha256` 是字符串、"
                "`v_signature` 是对象（{\"verdict\": …, \"sha256\": …}）",
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
                        v_signature=(dict(item.get(NP.INDEX_SIGN_FIELD))
                                     if isinstance(item.get(NP.INDEX_SIGN_FIELD), Mapping)
                                     else None),
                        # 台账那两格（D-69）：旧表没有这两键 ⇒ 读成空串 ⇒ 渲染印
                        # `未读到`（"这一格没填"不许印成空白，也不许折成"没签"）。
                        ledger_kind=str(item.get(LEDGER_KIND_FIELD) or "").strip(),
                        reviewed=str(item.get(REVIEWED_FIELD) or "").strip()))
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
            "The Lean column says where the source that checks the statement lives and which "
            "declaration it checks; both are mandatory whenever Lean output exists, and with the "
            "switch off the cell reads ``(Lean off)'' (an empty cell never means checked). "
            "The last two columns belong to theorems proved by numerical experiment: the reading of "
            "E's exhaustive run (\\texttt{" + NT.EVIDENCE_PREFIX + "NNNNNN}) and where E's two written "
            "blocks (design note and exhaustion argument) live; when absent they read "
            "``(not a numeric proof)''. The two columns after the ledger row are the ledger's own "
            "kind for that row and what V signed; ``(unread)'' in either of them means the cell could "
            "not be read at all, which is neither ``signed'' nor ``unsigned''. This paragraph "
            "itself is written by the renderer in the language of the paper: do not hand-copy it "
            "and do not mix languages."
        ),
        "columns": (
            "Env", "Label", "Ledger row", "Ledger kind", "V sign-off", "Proof", "File",
            "Lean (file / declaration)", "Citation location", "E reading", "Exhaustion note",
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
            "Lean 那一列是「验它的那份源码在哪」与「验的是哪个声明」两部分：有 Lean 产出时这两部分必填，"
            "开关关时印「" + LEAN_OFF_CELL + "」（空不等于验过）。"
            "最后两列是数值实验定理的：E 的那条穷举读数（\\texttt{" + NT.EVIDENCE_PREFIX
            + "NNNNNN}）与 E 写的那两块（" + NT.BLOCK_DESIGN + " / " + NT.BLOCK_EXHAUSTION
            + "）落在哪一份读数里；不填印「" + NUMERIC_EMPTY_CELL + "」。"
            "台账序号后面那两列是「台账里这一行叫什么」（`" + LEDGER_KIND_FIELD + "`）与"
            "「V 签没签、判决原话是什么」（`" + REVIEWED_FIELD + "`）：两格都由写侧按台账现读现填，"
            "读不到就印「" + LEDGER_CELL_UNREADABLE + "」—— 那一档既不是「已签」也不是「没签」。"
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

#: 附录表的十一列定宽（`\\textwidth` 的比例；十一列合计 0.90，剩下的留给列间距与 `\\tabcolsep`）。
#:
#: 业主 2026-10-24（D-46）：原先是四列 `l`（自然宽）加六列定宽，引文位置那一格是一整句
#: 英文，于是整张表宽出 `\\textwidth`、右侧被切到页外，Lean 那两列还互相压字。现在全列
#: 定宽、Lean 的文件与声明并成一列、整表 `\\small` 且 `\\tabcolsep` 收到 2pt。
#:
#: D-69 加了台账那两格（`ledger_kind` / `reviewed`）之后是十一列：新增的两列各 0.07 / 0.09，
#: 其余九列按同一比例压一点，合计仍然是 0.90 —— 列数变了而总宽不变，否则整张表又会宽出
#: `\\textwidth`（D-46 的那条判据按"列格式与表头逐格对上"判，不看具体数值）。
APPENDIX_COLUMN_WIDTHS: tuple[float, ...] = (
    0.07, 0.09, 0.09, 0.07, 0.09, 0.05, 0.08, 0.10, 0.11, 0.06, 0.09,
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
    """Lean 那两格在表格里的一格：空着时按开关状态写占位，不印空白。

    "空"与"验过了"必须分得开：开关关时印「未开 Lean」（这一趟没走形式化，不是没写），
    开关开而没填就印「没填」——它是不是红的由 `mapping_lean_*` 那几档判，
    这一格只负责不让读者把空白读成"没问题"。

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

    与 `_ledger_kind_cell` 同一条纪律：这一格的三态里没有一档叫"空白"。
    """
    return str(row.reviewed or "").strip() or LEDGER_CELL_UNREADABLE


#: 台账那两格在附录里按论文语言怎么说（D-45）。
#:
#: 为什么附录要翻一遍、而 json / md 只存中文那一版：json 与 md 是给人读的中文两份
#: （`MAPPING.md` 恒中文），附录是论文的一部分 —— 英文论文里一个中文字都不许有。
#: 三份仍然同源（同一批 `Row`、同一个渲染器），差别只是附录这一道按语言出词；
#: 这与 Lean 那两格的"（未开 Lean）/ (Lean off)"是同一条既有口径。
#:
#: 判决原话那一格：中文版逐字用原话；英文版按 `schema.REVIEW_VERDICTS` 这张受控词表
#: 翻成英文词。词表外的词（坏数据）英文附录印 `(unread)` 而不是把中文原话印进去：
#: 印进去就破了 D-45 那条"英文论文的附录里没有 CJK"，而不印只是"这一格翻不出来"。
_LEDGER_CELL_TEXT: dict[str, Any] = {
    PAPER_LANGUAGE_EN: {
        "unread": "(unread)",
        "unsigned": "unsigned",
        "signed": "signed (verdict: {verdict})",
        "verdicts": {"成立": "holds", "有毛病": "defective", "看不出来": "inconclusive"},
    },
    PAPER_LANGUAGE_ZH: {
        "unread": LEDGER_CELL_UNREADABLE,
        "unsigned": REVIEWED_UNSIGNED_CELL,
        "signed": REVIEWED_SIGNED_TEMPLATE,
        "verdicts": {},
    },
}


def _split_reviewed(cell: Any) -> tuple[str, str]:
    """把 `reviewed` 那一格的规范写法拆成 `(状态, 判决原话)`。

    状态只有三档：`signed` / `unsigned` / `unread`。拆不出来的写法一律落 `unread`：
    这一格认不出时，它说的既不是"签了"也不是"没签"，那是"这一格没查成"。
    """
    text = str(cell or "").strip()
    if not text or text == LEDGER_CELL_UNREADABLE:
        return "unread", ""
    if text == REVIEWED_UNSIGNED_CELL:
        return "unsigned", ""
    head, _, tail = REVIEWED_SIGNED_TEMPLATE.partition("{verdict}")
    if (tail and text.startswith(head) and text.endswith(tail)
            and len(text) > len(head) + len(tail)):
        return "signed", text[len(head):len(text) - len(tail)]
    return "unread", ""


def _appendix_reviewed(cell: Any, language: str) -> str:
    """附录里那一格（按论文语言出词；三态原样保留）。"""
    text = _LEDGER_CELL_TEXT[language]
    state, verdict = _split_reviewed(cell)
    if state == "unsigned":
        return str(text["unsigned"])
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
    if not raw or raw == LEDGER_CELL_UNREADABLE:
        return str(_LEDGER_CELL_TEXT[language]["unread"])
    return raw


def _lean_pair(row: Row, lean_on: bool, language: str) -> str:
    """Lean 那一格（D-46 把文件与声明并成一列）：`文件 / 声明`。

    两格都空（按开关印出同一句占位）时只印一次：`（未开 Lean）/（未开 Lean）`
    会让读者以为漏填了一格。
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
    """
    return "|".join([row.kind, str(int(row.env_no)), row.label, row.ledger_id,
                     str(int(row.proof_no)), row.file, row.lean_file, row.lean_target,
                     row.numeric_evidence, row.exhaustion_note,
                     _appendix_ledger_kind(row.ledger_kind, language),
                     _appendix_reviewed(row.reviewed, language)])


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
            _cell(f"{row.kind} {int(row.env_no)}"),
            _cell(row.label, mono=True),
            _cell(row.ledger_id, mono=True),
            _cell(_appendix_ledger_kind(row.ledger_kind, lang), mono=True),
            _cell(_appendix_reviewed(row.reviewed, lang)),
            str(int(row.proof_no)),
            _cell(row.file, mono=True),
            _cell(_lean_pair(row, lean_on, lang)),
            _cell(_loc_text(row) or row.citation_loc_reason or ""),
            _cell(_numeric_cell(row.numeric_evidence, lang)),
            _cell(_numeric_cell(row.exhaustion_note, lang), mono=True),
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
        "`lean_file` 与 `lean_target`：有 Lean 产出时，每条定理/引理/命题/推论还要说清"
        "验它的是论文包内哪一份 `.lean`、以及那份源码里的哪个声明名。开关关时这两列印"
        "「" + LEAN_OFF_CELL + "」—— 空不等于验过。",
        "`numeric_evidence` 与 `exhaustion_note`：数值实验定理那一行（证明栏是程序）多这两格 ——"
        "E 的那条穷举读数编号（`" + NT.EVIDENCE_PREFIX + "NNNNNN`）与 E 写的那两块"
        "（" + NT.BLOCK_DESIGN + " / " + NT.BLOCK_EXHAUSTION + "）落在哪一份读数里；"
        "那一行的 `file` 写的是那份程序的相对路径（相对仓库根），不是论文包内的 tex。",
        "`" + LEDGER_KIND_FIELD + "` 与 `" + REVIEWED_FIELD + "`（D-69）：台账那一行自己的 "
        "`kind`，以及 V 签没签 + 判决原话。两格由写侧按台账现读现填（`fill_ledger_cells`），"
        "读不到就写 `" + LEDGER_CELL_UNREADABLE + "` —— 那一档既不是「已签」也不是「没签」。"
        "它们让「论文里排成定理、台账里还是猜想」与「论文里排成定理、V 没签」这两件事在表上"
        "自己可见。",
        "",
        "| # | kind | label | env_no | ledger_id | " + LEDGER_KIND_FIELD + " | " + REVIEWED_FIELD
        + " | proof_no | file | lean_file | lean_target "
        "| citation_loc | citation_loc_reason | page_or_section | numeric_evidence "
        "| exhaustion_note |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, row in enumerate(items, start=1):
        lines.append(
            "| {i} | {kind} | {label} | {no} | {ledger} | {lkind} | {reviewed} | {proof} "
            "| {file} | {lean_file} "
            "| {lean_target} | {loc} | {reason} | {where} | {evidence} | {note} |".format(
                i=i, kind=row.kind, label=row.label or "（没有 label）", no=int(row.env_no),
                ledger=row.ledger_id, proof=int(row.proof_no),
                lkind=_ledger_kind_cell(row), reviewed=_reviewed_print_cell(row),
                file=row.file or "（空）",
                lean_file=_lean_cell(row.lean_file, lean_on),
                lean_target=_lean_cell(row.lean_target, lean_on),
                loc=_loc_text(row) or "",
                reason=row.citation_loc_reason or "",
                where=row.page_or_section or "",
                evidence=_numeric_cell(row.numeric_evidence),
                note=_numeric_cell(row.exhaustion_note)))
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
                  workspace_root: str | Path | None = None) -> tuple[Path, Path]:
    """写 json 与 md 两份，返回它们的路径（都在论文包里）。

    只走这一个写口：两份由同一次 `rows` 生成，于是"手写第二份"在结构上不可能发生。

    D-69：落盘之前先按台账把两格现读现填（`fill_ledger_cells`）。所以 G 手填的
    `ledger_kind` / `reviewed` 会被这一次现读盖掉 —— 这两格是"台账说是什么"，
    不是"提交方声称是什么"；填错了没有东西会报错，现读才有。

    `workspace_root` 是台账（`data/`）所在的那一层；不给就按 `project_root` 读
    （单项目工作区里两者是同一个目录）。
    """
    items = fill_ledger_cells(workspace_root if workspace_root is not None else project_root,
                              list(rows))
    json_path, md_path = mapping_paths(project_root)
    payload = {"rows": [row.to_dict() for row in items]}
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
    frag.write_bytes((render_appendix(rows, project_root=root) + "\n").encode("utf-8"))
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
                  workspace_root: str | Path | None = None) -> tuple[Path, Path, Path]:
    """G 的唯一写口：json + md + 附录（三份都由同一批 `rows` 生成）。

    `workspace_root` 只影响台账那两格的现读现填（台账在 `<工作区>/data/` 下）；
    不给就按项目根读（单项目工作区里是同一个目录）。
    """
    items = list(rows)
    json_path, md_path = write_mapping(project_root, items, workspace_root=workspace_root)
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
        take = next((sid for sid in by_key.get(key, ()) if sid not in used), "")
        if take:
            used[take] = env
            continue
        taken = [sid for sid in by_key.get(key, ()) if sid in used]
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
    numeric = is_numeric_row(row, got.ledger_row)
    if numeric:
        # 数值实验定理那一行的证明栏是程序（相对仓库根），与论文包内那份 tex 是两回事：
        # 走同一张 `file_state` 会把 `code/…` 判成"指到包外"，于是每一条真的穷举证明都红。
        state = NT.program_state(workspace, row.file)
        if state["state"] != "present":
            got.add(NT.PROOF_PROGRAM_MISSING,
                    f"表里 label={row.label!r}（{row.kind} 第 {row.env_no} 个，数值实验定理）"
                    f"的证明栏（`file`）不过关：{state['reason']}",
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


def is_numeric_row(row: Row, ledger_row: Mapping[str, Any] | None) -> bool:
    """这一行是不是数值实验定理（证明栏是程序，或它自己填了那两格）。

    两个来源都要认：
      - 台账说它的证明就是一份程序（`stmt` 行的 `proof_text` 过了
        `numerictheorem.is_program_proof`）—— 这是 E-1 的权威判据；
      - 或者这一行自己填了 `numeric_evidence` / `exhaustion_note` —— 填了就是声称，
        声称就得能复核（与 Lean 那两格同一条纪律）。

    只对命题类环境算（`LEAN_TARGETED_KINDS`）：例子与实验不是"被证明的命题"，
    它们的 `file` 仍然是论文包内那份材料。
    """
    if row.kind not in LEAN_TARGETED_KINDS:
        return False
    if row.numeric_evidence or row.exhaustion_note:
        return True
    if isinstance(ledger_row, Mapping) and NT.is_program_proof(ledger_row.get("proof_text")):
        return True
    return False


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
    script = NP.proof_column_script(NP.proof_column(found))
    if NP.norm_rel(script) != NP.norm_rel(row.file):
        add(NT.NUMERIC_EVIDENCE_MISSING,
            f"表里 label={label!r} 的 `{NT.EVIDENCE_FIELD}` = {want} 那一段的程序是 "
            f"{script!r}，而证明栏写的是 {row.file!r} —— 同一条定理的证明栏只能指一份程序")
        return out

    # 落库那一份证明栏（`statements.proof_text`）就是这条定理的证明栏：三段（① 程序、
    # ② 程序设计、③ 穷举论证）缺任何一段，它都还不算证明 —— 只能记成"有数值实验支持"。
    if isinstance(ledger_row, Mapping):
        column_problems = NT.proof_column_problems(ledger_row.get("proof_text"))
        for detail in column_problems:
            add(NT.EXHAUSTION_NOTE_MISSING,
                f"表里 label={label!r} 落库那份证明栏（`{row.ledger_id}`）{detail}"
                f" —— 三段齐了才叫证明栏；缺的那一段由 E 写，G 原样引用")
        registered = NP.proof_column_script(ledger_row.get("proof_text"))
        if registered and NP.norm_rel(registered) != NP.norm_rel(row.file):
            add(NT.PROOF_PROGRAM_MISSING,
                f"表里 label={label!r} 的证明栏写的是 {row.file!r}，而落库那份证明栏第 ① 段"
                f"写的是 {registered!r} —— 同一条定理的证明栏只能指一份程序")

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


def _stray_mapping_copies(project: Path, workspace: Path) -> list[Path]:
    """包外那些"放错落点"的 `MAPPING.json`（它们不算数，但要被点名）。"""
    found: list[Path] = []
    for base in (project, workspace, project / "papers"):
        path = base / MAPPING_JSON_NAME
        if path.is_file() and path not in found:
            found.append(path)
    return found


def ledger_cells_reading(rows: Iterable[Row],
                         ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None) -> dict[str, Any]:
    """盘上那张表的两格与台账现在的读数逐行比一遍（纯读，不写盘、也不拦门）。

    三种结局分开记（三态纪律）：

    - `filled`：这一行两格都填了；
    - `missing`：这一行两格是空的（旧表：写侧还没填过这两格）—— 它不是"没签"，
      是"这张表还没这两格"；
    - `stale`：填了，但与台账现在的读数不一致（表写完之后台账又动过）。

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
        want = ledger_cells(target, row.proof_no)
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
                     ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None
                     ) -> tuple[dict[str, Any], dict[str, Any]]:
    """落差读数（D-69 ②）：论文说定理 / 台账说猜想，以及论文排成定理 / V 没签。

    业主原话：「论文里以 theorem/lemma 环境出现、而台账 kind 仍是 conjecture 的行：
    N 条（逐条 label → stmt）」；同理一条「论文里排成定理但 V 没签的行」。

    两条都只看 `THEOREM_ENV_KINDS`（theorem / lemma）那几行，读数取自台账现读
    （不读表上那两格：表可能还没填、也可能写完之后台账又动过 —— 落差说的是
    "论文与台账现在的关系"）。

    三态：`reviewed` 读不到的行单列进 `unreadable`，不算进 `count`（"没签"是一个
    关于 V 做过什么的结论；"读不到"是没查成，两者折平就等于把没查成报成没签）。

    返回 `(kind_gap, theorem_unsigned)` 两份读数，形状都是
    `{"count", "items", "unreadable"?, "why"}`。这两条不拦门：业主的边界是
    "先让它看得见"（拦不拦由 H 与收工门另外判）。
    """
    gap: list[dict[str, Any]] = []
    unsigned: list[dict[str, Any]] = []
    unreadable: list[dict[str, Any]] = []
    for row in rows:
        if row.kind not in THEOREM_ENV_KINDS:
            continue
        resolved = resolve_ledger_id(row.ledger_id, ledger)
        target = (ledger_row(ledger, str(resolved["table"]), str(resolved["row_id"]))
                  if resolved["ok"] else None)
        cells = ledger_cells(target, row.proof_no)
        item = {"label": row.label, "env_kind": row.kind, "ledger_id": row.ledger_id,
                "proof_no": int(row.proof_no),
                "ledger_kind": cells[LEDGER_KIND_FIELD], "reviewed": cells[REVIEWED_FIELD]}
        if cells[LEDGER_KIND_FIELD] == CONJECTURE_KIND:
            gap.append(item)
        state, _verdict = _split_reviewed(cells[REVIEWED_FIELD])
        if state == "unsigned":
            unsigned.append(item)
        elif state == "unread":
            unreadable.append(item)
    gap_why = ""
    if gap:
        gap_why = ("论文里以 theorem/lemma 环境出现、而台账 kind 仍是 conjecture 的行："
                   + str(len(gap)) + " 条（"
                   + "、".join(f"{it['label']} → {it['ledger_id']}" for it in gap)
                   + "）")
    unsigned_why = ""
    if unsigned:
        unsigned_why = ("论文里排成定理但 V 没签的行：" + str(len(unsigned)) + " 条（"
                        + "、".join(f"{it['label']} → {it['ledger_id']}" for it in unsigned)
                        + "）")
    if unreadable:
        head = ("论文里排成定理、而 V 签没签读不到的行：" if not unsigned
                else "；论文里排成定理、而 V 签没签读不到的行：")
        unsigned_why += head + str(len(unreadable)) + " 条（" + "、".join(
            f"{it['label']} → {it['ledger_id']}" for it in unreadable) + "）"
    return ({"count": len(gap), "items": gap, "why": gap_why},
            {"count": len(unsigned), "items": unsigned,
             "unreadable": unreadable, "why": unsigned_why})


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
    if tex is None and has_paper:
        envs, statement_envs, tex_files, body_problems = _body_envs_of_package(
            package, tex_path, tex_text)
    else:
        # 调用方直接给了正文文本（没有文件可跟）：只扫这一份，`tex_files` 是空的。
        envs = body_envs(tex_text)
        statement_envs = statement_envs_of_text(tex_text)
    lean_on, lean_source = lean_switch()
    artifacts = lean_artifacts(project)
    if not lean_on:
        lean_state = "off"
        lean_reason = ("未开 Lean（`toolchain.lean_enabled` 为假，来源："
                       + (lean_source or "缺省") + "）⇒ `lean_file` / `lean_target` 允许为空；"
                       "空不等于验过 —— 这一趟的证明走 `proof_text` 与 V 的逐行审校")
    elif artifacts:
        lean_state = "on"
        lean_reason = (f"Lean 开关开着、盘上有 {len(artifacts)} 份 Lean 产物（{list(artifacts[:3])}）"
                       "⇒ 定理/引理/命题/推论那几行必须写 `lean_file` 与 `lean_target`")
    else:
        lean_state = "on_no_artifact"
        lean_reason = ("Lean 开关开着，但盘上一个 Lean 产物都没有（找过论文包内的 `"
                       + LEAN_SUFFIX + "` 与 `<项目根>/" + "`, `<项目根>/".join(LEAN_ARTIFACT_DIRS)
                       + "`）⇒ 这两格无从填起：说它是「没开 Lean」不真，说它是「验过了」更不真")
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
        "kind_gap": {"count": 0, "items": [], "why": ""},
        "theorem_unsigned": {"count": 0, "items": [], "unreadable": [], "why": ""},
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
            f"G 要先写 `out/paper/{MAPPING_JSON_NAME}`，再渲染 md 与附录，最后才编 PDF")]
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
    # Lean 那四类只在 `LEAN_KINDS` 非空时才判（见 `_lean_problems` 的 docstring：
    # 清空那一组就是关掉这一档，反真空用例靠它）。
    if LEAN_KINDS:
        problems += _lean_problems(rows, package, lean_on, artifacts, project)
    known = ledger if ledger is not None else read_ledger_tables(workspace)
    # ---- 台账那两格与两条落差读数（D-69）：都是纯读、都不拦门。
    #
    # 位置在 `known` 之后、逐行校验之前：这三项问的是"论文与台账现在的关系"，
    # 与"表与正文对不对得上"是两件事 —— 混进 `problems` 就等于把它们当门，
    # 而业主的口径是先让它看得见（`kind_gap` / `theorem_unsigned` 都不在
    # `ALL_PROBLEM_KINDS` 里）。
    reading["ledger_cells"] = ledger_cells_reading(rows, known)
    reading["kind_gap"], reading["theorem_unsigned"] = kind_gap_reading(rows, known)
    gap_notes = [str(reading["kind_gap"].get("why") or ""),
                 str(reading["theorem_unsigned"].get("why") or "")]
    gap_notes = [text for text in gap_notes if text]
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
        if NUMERIC_KINDS and is_numeric_row(row, got.ledger_row):
            if segments is None:
                segments = theorem_segments(project, tex=tex_text if tex is not None else None)
            problems += _numeric_problems(row, got.ledger_row, known, workspace, segments)

    for row in rows:
        resolved = resolve_ledger_id(row.ledger_id, known)
        target = (ledger_row(known, str(resolved["table"]), str(resolved["row_id"]))
                  if resolved["ok"] else None)
        state = (NT.program_state(workspace, row.file) if is_numeric_row(row, target)
                 else file_state(package, row.file))
        if state["state"] == "empty":
            reading["empty_files"].append(state["file"])

    # 一条命题对一个环境（业主 2026-10-24，D-40）：正文的定理类环境里，凡认领不到
    # 一条台账命题的那些（表里没行 / 指的是概念行 / 命题被别人用了）都要被点名。
    surplus_problems, surplus_labels = _statement_surplus_problems(
        statement_envs, rows, known)
    problems += surplus_problems
    reading["statement_surplus"] = list(surplus_labels)

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
