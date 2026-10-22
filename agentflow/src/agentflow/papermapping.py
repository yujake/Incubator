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
| `env_no` | 是 | 正文里第几个该环境，1 起，按正文出现顺序按类计数（theorem 单独数、lemma 单独数） |
| `ledger_id` | 是 | `stmt:NNNNNN` / `exp:NNNNNN` / `rel:NNNNNN`；多证明带 `#pN`（`stmt:000004#p2`） |
| `proof_no` | 是 | 这条定理名下第几号证明：1 = canonical（台账行上的 `proof_text`）；2 及以上 = 该行 `proofs` 清单里那一份 |
| `file` | 是 | 该条完整证明或实验所在的真实文件，论文包内的相对路径（`proofs/000004-p1.md`） |
| `page_or_section` | 否 | 给人看的定位（`3` / `p.7`） |
| `citation_loc` | 视来源 | 引文的本地位置：`{"file": 包内相对路径, "page_range"|"line_range"|"char_range": [起点, 终点]}` |
| `citation_loc_reason` | 视来源 | 不给 `citation_loc` 时那句理由 |
| `lean_file` | 有 Lean 产出时 | Lean 程序的真实位置：论文包内相对路径（`formal/000004.lean`）。绝对路径与包外路径都红 |
| `lean_target` | 有 Lean 产出时 | 它验的是哪一条：Lean 里那个声明的名字（`FreeGroupFactor.isII1`），必须真的出现在 `lean_file` 里 |

`file` 与 `citation_loc.file` 都是包内相对路径：绝对路径在别人的机器上等于不存在，
而指向包外的相对路径同样过不了"换一台机器也能复核"这一关（两者都判红）。

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
- 开关开、且盘上有 Lean 产物（论文包内任意 `*.lean`，或 `<项目根>/out/formal/` 下的产物）
  => 每条 theorem / lemma / proposition / corollary 行必须给这两格，缺就是
  `mapping_lean_missing`；
- `lean_file` 不是 `.lean`、或不在论文包里 => `mapping_lean_file_missing`；
- `lean_target` 在那一份 `.lean` 里找不到（做词边界匹配，`foo` 不算命中 `foobar`）
  => `mapping_lean_target_missing`；
- 同一个 `lean_target` 出现在两行 => `mapping_lean_target_ambiguous`。一条命题有多条证明时，
  允许两行共用一个 `lean_file`，但那两行的 `lean_target` 必须各自不同（各自那份 `.lean`
  里验它的声明名）。

开关开、却一个 Lean 产物都没有 => 读数里有一档 `lean_on_but_no_artifact`（`warnings`，
不拦门；见 `LEAN_WARN_KINDS`）：两格无从填起这件事必须看得见，但它说的不是
"表与正文对不上"。两格里只要填了一格（哪怕开关关着），就要当真核 —— 只填一半同样是
`mapping_lean_missing`：填了就是声称，声称就得能复核。

## 双向都不许有孤儿

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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import papercompile as PC
from . import proofloc as PL
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
APPENDIX_BEGIN = ("% ==== MAPPING-APPENDIX BEGIN"
                  "（由 out/paper/MAPPING.json 渲染，不许手改）====")
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

#: Lean 那两格（`lean_file` / `lean_target`）：有 Lean 产出时必填，其余时候允许为空。
LEAN_ROW_FIELDS: tuple[str, ...] = ("lean_file", "lean_target")

#: Lean 产物的后缀（`lean_file` 必须是它结尾）。
LEAN_SUFFIX = ".lean"

#: 除论文包之外，Lean 产物还落在哪（项目根相对；业主口径里有 `out/formal/` 这一处）。
LEAN_ARTIFACT_DIRS: tuple[str, ...] = ("out/formal",)

#: 扫 Lean 产物时不进的目录（`.lake` 里是整份 Mathlib 的源码与编译产物）。
LEAN_SKIP_DIRS: tuple[str, ...] = (".lake", ".git", ".hg", "node_modules", "__pycache__")

#: Lean 那两格的三种占位写法（空着时按开关状态印出来，不印空白）。
LEAN_OFF_CELL = "（未开 Lean）"
LEAN_UNFILLED_CELL = "（没填）"

#: 每一行的必填字段（其余见 `OPTIONAL_ROW_FIELDS` 与 `CONDITIONAL_ROW_FIELDS`）。
ROW_FIELDS: tuple[str, ...] = (
    "kind", "label", "env_no", "ledger_id", "proof_no", "file",
)

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

#: 本模块会产出的全部问题类别（判据要逐类覆盖它，见 `tests/test_paper_mapping_table.py`）。
#:
#: 只收拦门的那几组：`LEAN_WARN_KINDS` 不进这里（它在 `warnings` 里，不改 `state`）。
ALL_PROBLEM_KINDS: tuple[str, ...] = (
    MAPPING_KINDS + CITATION_KINDS + MD_KINDS + PAPER_KINDS + LEAN_KINDS
)

#: 三态取值。
STATES: tuple[str, ...] = ("pass", "fail", "unknown")

#: `file` 的五个状态（`present` 之外的四个各自有判据）。
FILE_STATES: tuple[str, ...] = ("present", "empty", "missing", "directory", "outside")

#: 正文里的一类环境：`\\begin{theorem}`（允许带星号，`end` 必须同名同星号）。
_ENV_RE = re.compile(
    r"\\begin\{(?P<kind>" + "|".join(ENV_KINDS) + r")(?P<star>\*?)\}"
    r"(?P<body>.*?)"
    r"\\end\{(?P=kind)(?P=star)\}",
    re.S,
)

#: 环境里的标签（取第一个）。
_LABEL_RE = re.compile(r"\\label\{([^{}]*)\}")

#: `main.tex` 里的 `\\input{...}`（附录可以被 `\\input` 进来）。
_INPUT_RE = re.compile(r"\\input\{([^{}]+)\}")

#: 台账代号必须是纯数字（宽度由 `schema.ID_DIGITS` 定，这里只判"是数字"）。
_DIGITS_RE = re.compile(r"^[0-9]+$")

#: LaTeX 特殊字符的替换表（逐字符映射：替换出来的反斜杠不会被二次转义）。
_TEX_SPECIALS: dict[str, str] = {
    "\\": "\\textbackslash{}", "&": "\\&", "%": "\\%", "$": "\\$", "#": "\\#",
    "_": "\\_", "{": "\\{", "}": "\\}", "~": "\\textasciitilde{}",
    "^": "\\textasciicircum{}",
}


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

    def to_dict(self) -> dict[str, Any]:
        """写回 json 的形状（字段顺序固定，diff 才读得懂）。"""
        out: dict[str, Any] = {"kind": self.kind, "label": self.label,
                               "env_no": int(self.env_no), "ledger_id": self.ledger_id,
                               "proof_no": int(self.proof_no), "file": self.file}
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
        return out


@dataclass(frozen=True)
class BodyEnv:
    """正文里的一个定理类环境（`line` 是 1 起的行号）。"""

    kind: str
    label: str
    env_no: int
    line: int


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


def body_envs(tex: str) -> list[BodyEnv]:
    """正文里全部定理类环境（按出现顺序，`env_no` 按同类计数、1 起）。"""
    text = str(tex or "")
    counts: dict[str, int] = {}
    out: list[BodyEnv] = []
    for m in _ENV_RE.finditer(text):
        kind = str(m.group("kind"))
        counts[kind] = counts.get(kind, 0) + 1
        label = _LABEL_RE.search(m.group("body"))
        out.append(BodyEnv(kind=kind, label=(label.group(1).strip() if label else ""),
                           env_no=counts[kind], line=text.count("\n", 0, m.start()) + 1))
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

    两处都扫：论文包内任意 `*.lean`（`lean_file` 只认包内相对路径，所以这是能填的那一处），
    以及 `<项目根>/out/formal/` 下的产物（业主 2026-10-22 口径里点名的另一处）。
    返回的是给人看的写法：包内的是 `formal/000004.lean`，`out/formal/` 的是
    `out/formal/000004.lean` —— 后者填不进 `lean_file`（那会指到包外），
    它的用处是"盘上到底有没有 Lean 产出"这个事实。
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
                   artifacts: Sequence[str]) -> list[dict[str, Any]]:
    """Lean 那两格（业主 2026-10-22 追加）：什么时候必填、填了要真。

    三件事分开报，一条坏不遮蔽另一条：
    1. 必填而缺（或只填了一半）=> `mapping_lean_missing`；
    2. `lean_file` 不是 `.lean` / 不在包里 => `mapping_lean_file_missing`；
    3. `lean_target` 在那一份 `.lean` 里找不到 => `mapping_lean_target_missing`；
    外加一条横向的：同一个 `lean_target` 被两行共用 => `mapping_lean_target_ambiguous`。

    "必填"的口径见模块 docstring：开关开、且盘上真有 Lean 产物，才要求定理类那四行给两格。
    这一条只在 `LEAN_KINDS` 非空时才被调用（见 `mapping_reading`）：清空那一组就是关掉这一档，
    反真空用例靠它证明"这些红真的靠那组 kind"。
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
                f"{why}。`lean_file` 写论文包内的相对路径（如 formal/000004.lean），"
                "`lean_target` 写 Lean 里那个声明的名字（如 FreeGroupFactor.isII1）",
                label=row.label, where=MAPPING_JSON_NAME))
        file_ok = False
        if lean_file:
            state = file_state(package_root, lean_file)
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
                    "它必须是论文包内的相对路径（绝对路径在别人的机器上等于不存在），"
                    "`out/formal/` 下的产物要先放进包里（如 formal/000004.lean）",
                    label=row.label, where=MAPPING_JSON_NAME))
            else:
                file_ok = True
        if lean_target and lean_file and file_ok:
            absolute = Path(package_root) / lean_file
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
        rows.append(Row(kind=kind, label=label, env_no=env_no,
                        ledger_id=str(item.get("ledger_id") or "").strip(),
                        proof_no=proof_no,
                        file=str(item.get("file") or "").strip(),
                        lean_file=str(item.get("lean_file") or "").strip(),
                        lean_target=str(item.get("lean_target") or "").strip(),
                        page_or_section=str(item.get("page_or_section") or "").strip(),
                        citation_loc=dict(loc) if isinstance(loc, Mapping) else None,
                        citation_loc_reason=str(item.get("citation_loc_reason") or "").strip()))
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


def _lean_cell(value: str, lean_on: bool) -> str:
    """Lean 那两格在表格里的一格：空着时按开关状态写占位，不印空白。

    "空"与"验过了"必须分得开：开关关时印「未开 Lean」（这一趟没走形式化，不是没写），
    开关开而没填就印「没填」——它是不是红的由 `mapping_lean_*` 那几档判，
    这一格只负责不让读者把空白读成"没问题"。
    """
    if value:
        return value
    return LEAN_UNFILLED_CELL if lean_on else LEAN_OFF_CELL


def _row_key_text(row: Row) -> str:
    """附录里那条机器可读注释的内容（`|` 分隔，判据靠它数行与比 label）。"""
    return "|".join([row.kind, str(int(row.env_no)), row.label, row.ledger_id,
                     str(int(row.proof_no)), row.file, row.lean_file, row.lean_target])


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


def render_appendix(rows: Iterable[Row], *, lean_enabled: bool | None = None) -> str:
    """把行渲染成正文附录（唯一渲染函数；手抄的那一段过不了逐字比对）。

    `lean_enabled` 不给时按 `lean_switch()` 的当次读数（读盘那一侧也走同一个默认）：
    Lean 那两列因此印的是这一趟的真实状态，而不是一段永远一样的空白。
    """
    items = list(rows)
    lean_on = lean_switch()[0] if lean_enabled is None else bool(lean_enabled)
    lines = [
        APPENDIX_BEGIN,
        "\\section*{" + APPENDIX_TITLE + "}",
        "",
        "本表由 \\texttt{" + MAPPING_JSON_NAME + "} 渲染（\\texttt{agentflow.papermapping.render\\_appendix}），"
        "不许手抄第二份。\\texttt{file} 一列是论文包内的相对路径 —— 换一台机器也指向同一份文件。"
        "Lean 那两列是「验它的那份源码在哪」与「验的是哪个声明」：有 Lean 产出时这两列必填，"
        "开关关时它们印「" + LEAN_OFF_CELL + "」（空不等于验过）。",
        "",
        "\\begin{tabular}{llllp{0.15\\textwidth}p{0.15\\textwidth}p{0.15\\textwidth}"
        "p{0.15\\textwidth}}",
        "环境 & label & 台账序号 & 证明号 & 真实文件 & Lean 文件 & Lean 声明 & 引文位置 \\\\",
        "\\hline",
    ]
    for row in items:
        lines.append(APPENDIX_ROW_PREFIX + _row_key_text(row))
        lines.append(" & ".join([
            _tex_escape(f"{row.kind} {int(row.env_no)}"),
            "\\texttt{" + _tex_escape(row.label) + "}",
            "\\texttt{" + _tex_escape(row.ledger_id) + "}",
            str(int(row.proof_no)),
            "\\texttt{" + _tex_escape(row.file) + "}",
            _tex_escape(_lean_cell(row.lean_file, lean_on)),
            _tex_escape(_lean_cell(row.lean_target, lean_on)),
            _tex_escape(_loc_text(row) or row.citation_loc_reason or ""),
        ]) + " \\\\")
    lines += ["\\hline", "\\end{tabular}", "", APPENDIX_END, ""]
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
        "",
        "| # | kind | label | env_no | ledger_id | proof_no | file | lean_file | lean_target "
        "| citation_loc | citation_loc_reason | page_or_section |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, row in enumerate(items, start=1):
        lines.append(
            "| {i} | {kind} | {label} | {no} | {ledger} | {proof} | {file} | {lean_file} "
            "| {lean_target} | {loc} | {reason} | {where} |".format(
                i=i, kind=row.kind, label=row.label or "（没有 label）", no=int(row.env_no),
                ledger=row.ledger_id, proof=int(row.proof_no),
                file=row.file or "（空）",
                lean_file=_lean_cell(row.lean_file, lean_on),
                lean_target=_lean_cell(row.lean_target, lean_on),
                loc=_loc_text(row) or "",
                reason=row.citation_loc_reason or "",
                where=row.page_or_section or ""))
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


def write_mapping(project_root: str | Path, rows: Iterable[Row]) -> tuple[Path, Path]:
    """写 json 与 md 两份，返回它们的路径（都在论文包里）。

    只走这一个写口：两份由同一次 `rows` 生成，于是"手写第二份"在结构上不可能发生。
    """
    items = list(rows)
    json_path, md_path = mapping_paths(project_root)
    payload = {"rows": [row.to_dict() for row in items]}
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
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


def write_appendix(project_root: str | Path) -> Path:
    """按盘上的 json 渲染附录，并保证 `main.tex` 里有那一行 `\\input`。

    写的是两份东西：`<论文包>/mapping-appendix.tex`（附录正文）与 `main.tex` 里
    那一行 `\\input{mapping-appendix}`（已存在就不重复插）。正文因此变长 =>
    必须重编一次（`doc.paper_compile`），否则 `closing` 的 `paper` 那一格会报
    "PDF 是旧正文编的"——那是既有判据，不因本模块而放宽。
    """
    root = Path(project_root)
    json_path, _md_path = mapping_paths(root)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    rows, _problems = parse_rows(payload)
    frag = appendix_path(root)
    frag.parent.mkdir(parents=True, exist_ok=True)
    frag.write_bytes((render_appendix(rows) + "\n").encode("utf-8"))
    tex = package_dir(root) / PC.TEX_NAME
    if tex.is_file():
        text = tex.read_text(encoding="utf-8")
        if APPENDIX_INPUT not in text:
            end = text.rfind("\\end{document}")
            if end < 0:
                # 正文还没有 `\end{document}`（半成品稿）：追加到末尾，不猜它该在哪结束。
                # 这样"先写正文、再补附录"与"一次写完"两条路都能走通。
                text = text.rstrip("\n") + "\n" + APPENDIX_INPUT + "\n"
            else:
                text = text[:end] + APPENDIX_INPUT + "\n" + text[end:]
            tex.write_bytes(text.encode("utf-8"))
    return frag


def write_package(project_root: str | Path, rows: Iterable[Row]) -> tuple[Path, Path, Path]:
    """G 的唯一写口：json + md + 附录（三份都由同一批 `rows` 生成）。"""
    items = list(rows)
    json_path, md_path = write_mapping(project_root, items)
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
    """正文里那一段附录的字节（找不到 => 空串）。"""
    if APPENDIX_BEGIN in tex:
        start = tex.find(APPENDIX_BEGIN)
        end = tex.find(APPENDIX_END, start)
        if end >= 0:
            return tex[start:end + len(APPENDIX_END)]
        return tex[start:]
    for name in _INPUT_RE.findall(tex or ""):
        candidate = package_dir(project_root) / str(name).strip()
        paths = [candidate] if candidate.suffix else [candidate, candidate.with_suffix(".tex")]
        for path in paths:
            if path.is_file():
                try:
                    got = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                if APPENDIX_BEGIN in got:
                    start = got.find(APPENDIX_BEGIN)
                    end = got.find(APPENDIX_END, start)
                    return got[start:end + len(APPENDIX_END)] if end >= 0 else got[start:]
    return ""


def _appendix_reading(project_root: Path, tex: str,
                      rows: Sequence[Row]) -> tuple[str, list[dict[str, Any]]]:
    """附录那一节的状态（`present` / `missing` / `mismatch`）与它的问题。"""
    block = _appendix_block(project_root, tex)
    if not block.strip():
        return "missing", [_problem(
            "mapping_not_in_paper",
            f"正文里读不到「{APPENDIX_TITLE}」那一节 —— 由 json 渲染（`write_appendix`），"
            f"再把 `{APPENDIX_INPUT}` 放进正文；表只在盘上、没印进正文，H 读稿时看不到它",
            where=PC.TEX_NAME)]
    want = render_appendix(rows)
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
                    where=f"{PC.TEX_NAME}:{env.line}"))
            continue
        if len(got) > 1:
            problems.append(_problem(
                "mapping_orphan",
                f"正文里 label={label!r} 的 {kind} 出现了 {len(got)} 次"
                f"（第 {[e.line for e in got]} 行）—— 重复的 label 无法与表行一一对应",
                label=label, where=f"{PC.TEX_NAME}:{got[0].line}"))
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
            label=label, where=f"{PC.TEX_NAME}:{env.line}"))
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
                    label=label, where=f"{PC.TEX_NAME}:{env.line}"))
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


def _row_checks(row: Row, ledger: Mapping[str, Sequence[Mapping[str, Any]]],
                package_root: Path) -> _RowCheck:
    """一行的三条轴：台账代号码 / 证明号 / 文件（三条互不遮蔽：一条坏不影响别条被报）。"""
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


def _stray_mapping_copies(project: Path, workspace: Path) -> list[Path]:
    """包外那些"放错落点"的 `MAPPING.json`（它们不算数，但要被点名）。"""
    found: list[Path] = []
    for base in (project, workspace, project / "papers"):
        path = base / MAPPING_JSON_NAME
        if path.is_file() and path not in found:
            found.append(path)
    return found


def mapping_reading(project_root: str | Path, *,
                    workspace_root: str | Path | None = None,
                    ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
                    tex: str | None = None) -> dict[str, Any]:
    """读一个项目的对应表并校验（纯读，不写盘）。

    三态：`pass` / `fail` / `unknown`（`unknown` 是"没查成 / 不适用"，绝不是通过）。
    `problems` 里每条都带 `kind`（取值在 `ALL_PROBLEM_KINDS` 里），拦不拦门由
    `agent_h.mapping_judge.level_of` 决定；`warnings` 里是只进读数、不改 `state` 的那一档
    （`LEAN_WARN_KINDS`），`lean` 那一格给出这一趟的 Lean 开关与盘上的产物。
    """
    project = Path(project_root)
    workspace = Path(workspace_root) if workspace_root is not None else project
    package = package_dir(project)
    json_path, md_path = mapping_paths(project)
    if tex is None:
        tex_path = package / PC.TEX_NAME
        tex_text = tex_path.read_text(encoding="utf-8") if tex_path.is_file() else ""
    else:
        tex_text = str(tex)
    has_paper = bool(str(tex_text or "").strip())
    envs = body_envs(tex_text)
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
        "md_state": "",
        "appendix_state": "",
        "lean_state": lean_state,
        "lean": {"enabled": bool(lean_on), "source": lean_source, "state": lean_state,
                 "artifacts": list(artifacts[:20]), "artifact_count": len(artifacts),
                 "target_kinds": list(LEAN_TARGETED_KINDS), "reason": lean_reason},
        "empty_files": [],
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
        problems += _lean_problems(rows, package, lean_on, artifacts)
    known = ledger if ledger is not None else read_ledger_tables(workspace)
    seen_targets: dict[tuple[str, int], Row] = {}
    for row in rows:
        got = _row_checks(row, known, package)
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

    for row in rows:
        state = file_state(package, row.file)
        if state["state"] == "empty":
            reading["empty_files"].append(state["file"])

    reading["problems"] = problems
    if problems:
        reading["state"] = "fail"
        counts: dict[str, int] = {}
        for item in problems:
            counts[item["kind"]] = counts.get(item["kind"], 0) + 1
        reading["reason"] = ("表在包里、但有 {n} 处问题（{by}）—— 逐条见 problems".format(
            n=len(problems), by="、".join(f"{k} {v}" for k, v in counts.items())))
    else:
        reading["state"] = "pass"
        reading["reason"] = (f"{len(rows)} 行与正文 {len(envs)} 个环境逐一对上，附录逐字一致，"
                             "`ledger_id` 与 `proof_no` 都能在台账里解析到，`file` 都在包里")
    # 两档都写进 reason：`pass` 不等于"什么都没剩"，`warnings` 与 Lean 那一格必须被看见
    # （三态纪律：把"没开 Lean / 没有 Lean 产出"与"验过了"折成同一个沉默是本项目最忌的形态）。
    reading["reason"] += "；Lean：" + lean_reason
    if reading["warnings"]:
        reading["reason"] += "；另有警告 " + "、".join(
            sorted({str(w.get("kind") or "") for w in reading["warnings"]}))
    return reading
