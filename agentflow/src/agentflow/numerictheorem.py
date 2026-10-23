# -*- coding: utf-8 -*-
"""数值实验定理怎么写、怎么登记（业主 2026-10-23 的裁定，E-1）。

业主原话（逐字）：

> 「请给 G 立规范如何在正文写纯数值实验跑出的定理，且搞好对应表。G 在落数值实验证出的
> 定理时应该写明程序设计思路以及确实穷举的论证」；「这个可以当数值实验定理的证明栏」。

随后补的那条硬口径（作者归属）逐字：

> 「数值实验定理的证明栏三部分：① 程序相对地址 ② 程序设计 ③ 穷举论证。作者：② 与 ③
> 都由 E 写；G 在正文里必须原样引用 E 的那两块（可压缩措辞，但不许改写实质、不许把 E 的
> 读数变成『我们认为』），并在正文里标出它们来自 E 的那条读数（引用编号/路径）。E 没给
> 就把这写成『定理/已证明』是不许的，只能写『有数值实验支持』，并点名缺哪一块。」

## 三块、它们的作者、它们的落点

| 块 | 本模块的记号 | 谁写 | 落点 |
|---|---|---|---|
| ① 程序相对地址 | `Row.file`（数值实验定理那一行） | E 跑出来的那份脚本 | 工作区内的相对路径（`code/r34_check.py`） |
| ② 程序设计思路 | `BLOCK_DESIGN` | E | `Row.exhaustion_note` 指的那份读数里 |
| ③ 穷举论证 | `BLOCK_EXHAUSTION` | E | 同上；可核的那一份在 `experiments` 的 `search_bound` / `observations` |
| 运行环境 | `BLOCK_ENVIRONMENT` | E | 同上（版本、种子若有） |

三块合起来就是这条定理在论文里的证明栏：不是脚注，不是附录摘要。G 的正文照它写，
对应表那两格（`numeric_evidence` / `exhaustion_note`）指回 E 的读数。

## 为什么判据落在这些键上

- 证明栏是程序：`numericproof.is_script_path` 判"这是不是一段脚本的相对路径"，
  与 E-1 里「入定理证明库时证明栏写程序地址（相对仓库）」是同一份口径；
- 那块读数是不是"确实穷举"：不另立口径，直接用 `numericproof.is_signed_exhaustion`
  （方法属于计算类、`evidence_kind="proof"`、签名者 E、证明理由 exhaustion）与
  `numericproof.exhaustion_problems`（搜索空间 + 布尔 exhaustive + 覆盖说明）。
  于是"不完全的数值实验"在数据面上根本拿不到 proof，也就在对应表这一格上过不去；
- 三块的"齐"：`blocks_missing` 只认字面记号（两个论证的标题、运行环境、署名 `作者：E`、
  以及至少一条 `exp:NNNNNN` 的读数编号）。这是刻意粗糙的一条：它判的是"有没有那一块、
  那块是谁的、出处写没写"，不判实质有没有被改写 —— 那是 H 的读法，写在
  `agent_h/mapping_judge.py` 的主观档里，不在这里冒充机器判据。

## 三块里少一块算什么

少一块就是"这条定理的证明栏写不完"：`papermapping` 那一侧落成拦门的一类问题
（`NUMERIC_KINDS` 那一组），`doc.write_mapping` 随之受控拒绝（`mapping_not_clean`），
一行都不许当成"已经写完了"。降档那一条（记成"有数值实验支持"）用的是
`numericproof.SUPPORTED_ONLY_KIND`，两个方向都有判据，见
`tests/test_numeric_theorem_writing_spec.py`。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from . import exhaustionreport as ER
from . import numericproof as NP

#: ② 这一块的标题（E 写的"程序设计思路"，G 原样引用）。
#:
#: 字面取自 `exhaustionreport` 与 `numericproof.PART_NAMES`：证明栏那三段（程序 / 程序设计 /
#: 穷举论证）与那份读数的三块标题都只有一个真身，这里是它的读侧别名 —— 两边各写一份，
#: 迟早会漂成两种说法（`exhaustionreport` 的 docstring 也点名要按 `blocks_missing` 核）。
BLOCK_DESIGN = ER.BLOCK_DESIGN

#: ③ 这一块的标题（E 写的"确实穷举的论证"）。
BLOCK_EXHAUSTION = ER.BLOCK_EXHAUSTION

#: ① 那一块的标题（程序相对地址）。
BLOCK_PROGRAM = NP.PART_NAMES["script"]

#: 第三件：运行环境（版本、随机种子若有）。它与程序地址合成业主口径里的第三块。
BLOCK_ENVIRONMENT = ER.BLOCK_ENVIRONMENT

#: 作者记号（业主：「② 与 ③ 都由 E 写」）。G 不许署自己，也不许改成"我们认为"。
AUTHOR_MARKER = ER.AUTHOR_MARKER

#: E 的那条读数编号在文里怎么写（`exp:000000`，与 `schema` 的引用前缀同一套）。
EVIDENCE_PREFIX = ER.EVIDENCE_PREFIX
#: 缺读数编号时 `blocks_missing` 报的那一格名字（它不是字面记号，单独给一个标签）。
EVIDENCE_LABEL = "E 的读数编号（" + EVIDENCE_PREFIX + "NNNNNN）"

#: 那三块与署名在读数里必须逐字出现的记号（顺序即业主口径的顺序）。
NOTE_MARKERS: tuple[str, ...] = tuple(ER.NOTE_MARKERS) + (AUTHOR_MARKER,)

#: 不完全的数值实验唯一允许的说法（业主：「只能说有数值实验支持」）。
SUPPORTED_ONLY_WORD = "有数值实验支持"

#: 对应表里数值实验定理多出来的两格（与 Lean 那两格同一套"条件必填"写法）。
EVIDENCE_FIELD = "numeric_evidence"
NOTE_FIELD = "exhaustion_note"
NUMERIC_ROW_FIELDS: tuple[str, ...] = (EVIDENCE_FIELD, NOTE_FIELD)

#: 本模块那一组问题类别（拦门的那一档，接线在 `papermapping.ALL_PROBLEM_KINDS`）。
#:
#: `mapping_proof_program_missing`：证明栏（`file`）不是相对仓库的程序路径，或盘上没有那份程序；
#: `mapping_proof_program_unbacked`：程序在台账里没有 E 签的穷举证明（那就只是"有数值实验支持"）；
#: `mapping_numeric_evidence_missing`：缺 E 的读数编号，或它指的那条与证明栏不是同一份程序；
#: `mapping_exhaustion_note_missing`：两块读数的落点不在、或里面缺块 / 缺署名 / 缺出处；
#: `mapping_numeric_citation_missing`：正文那一段里指不回 E 的读数（无出处的叙述）。
PROOF_PROGRAM_MISSING = "mapping_proof_program_missing"
PROOF_PROGRAM_UNBACKED = "mapping_proof_program_unbacked"
NUMERIC_EVIDENCE_MISSING = "mapping_numeric_evidence_missing"
EXHAUSTION_NOTE_MISSING = "mapping_exhaustion_note_missing"
NUMERIC_CITATION_MISSING = "mapping_numeric_citation_missing"

#: 这一组的全部取值（`papermapping.ALL_PROBLEM_KINDS` 会 import 它，别处不另抄）。
NUMERIC_KINDS: tuple[str, ...] = (
    PROOF_PROGRAM_MISSING, PROOF_PROGRAM_UNBACKED, NUMERIC_EVIDENCE_MISSING,
    EXHAUSTION_NOTE_MISSING, NUMERIC_CITATION_MISSING,
)

#: 读数编号的形状（`exp:` 后面是纯数字；宽度由 `schema.ID_DIGITS` 定，这里只判"是数字"）。
_EVIDENCE_ID_RE = re.compile(r"exp:[0-9]+")


def is_program_proof(proof_text: Any) -> bool:
    """这一格是不是"证明栏写的是程序"（数值实验定理的判据入口）。

    口径只有一份：`numericproof.proof_column_script` —— 它同时认三段式证明栏
    （`程序：… / 程序设计：… / 穷举论证：…`）与"只写了一行程序路径"的历史形态。
    不在这里重写一遍，否则"什么样的写法算程序"会长出第二个答案。
    """
    return bool(NP.proof_column_script(proof_text))


def proof_column_problems(proof_text: Any) -> list[str]:
    """这条定理落库时那份证明栏缺哪一段（空清单 = ① ② ③ 三段齐）。

    转给 `numericproof.parse_proof_column`：三段标签的解析与判据只有那一处。
    """
    return list(NP.parse_proof_column(proof_text).get("problems") or [])


def evidence_id_of(experiment: Mapping[str, Any] | None) -> str:
    """一条实验行的引用编号（`exp:000000`）；读不到编号就给空串（不猜）。"""
    row = dict(experiment or {})
    raw = str(row.get("experiment_id") or "").strip()
    return (EVIDENCE_PREFIX + raw) if raw else ""


def blocks_missing(note_text: Any) -> list[str]:
    """两块论证那一份读数里缺什么（空清单 = 三块齐全、署名 E、且写了读数编号）。

    这是"三块齐全"的唯一判定。判据里有一条反真空用例把它打桩成恒真，用来证明
    "缺块被拒"这件事真的压在这个函数上（`tests/test_numeric_theorem_writing_spec.py` 第 5 条）。
    """
    text = str(note_text or "")
    missing = [marker for marker in NOTE_MARKERS if marker not in text]
    if not _EVIDENCE_ID_RE.search(text):
        missing.append(EVIDENCE_LABEL)
    return missing


def note_relpath(experiment: Mapping[str, Any] | None) -> str:
    """这条 E 的读数该落在哪（`out/experiments/<实验号>/exhaustion.md`，相对仓库根）。

    口径只有一份：转给 `exhaustionreport.report_relpath`（本函数只是这个模块里那个
    名字的读侧入口，不另起一套口径；换个名字是为了不让两条公开 def 同名）。
    对应表那两格里的 `exhaustion_note` 必须是这一条（不许 G 自己另挑一个地方说"E 写在那"）。
    """
    row = dict(experiment or {})
    return ER.report_relpath(row.get("experiment_id"))


def corpus_problems(*, note: Any, workspace_root: str | Path | None,
                    evidence_id: Any = "") -> list[str]:
    """两块论证那一份读数的读数（空清单 = 读得到、三块齐、署名与出处都在）。

    `note` 是 `Row.exhaustion_note`（相对仓库根的路径），`evidence_id` 是这条定理压着的
    那条 E 的读数编号（`exp:NNNNNN`）。四种读不到的情形各自说清：没填 / 路径不合口径
    （绝对路径、含 `..`）/ 盘上没有 / 文件是空的；再加上"缺块 / 缺署名 / 缺读数编号"。
    三种都不许折成"没问题"：折了就等于把"E 没给"读成"给过了"。
    """
    raw = str(note or "").strip()
    if not raw:
        return [
            f"没填 `{NOTE_FIELD}`：E 写的那两块（{BLOCK_DESIGN} / {BLOCK_EXHAUSTION}）"
            "落在哪一份读数里必须写出来（相对仓库根的路径）"
        ]
    path, problem = _resolve(workspace_root, raw)
    if path is None:
        return [f"`{NOTE_FIELD}` 不合口径：{problem}"]
    if not path.is_file():
        return [f"`{NOTE_FIELD}` 指的读数读不到：{raw}（盘上没有这份文件）"]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"`{NOTE_FIELD}` 指的读数读不出来：{raw}（{type(exc).__name__}: {exc}）"]
    if not text.strip():
        return [f"`{NOTE_FIELD}` 指的读数是空的：{raw}（空文件不等于「这两块写过了」）"]
    missing = blocks_missing(text)
    out: list[str] = []
    want_id = str(evidence_id or "").strip()
    if want_id and want_id not in text:
        missing.append(want_id)
    if missing:
        out.append(
            f"`{NOTE_FIELD}` 缺 {missing}（{raw}）：那两块由 E 写，G 在正文里原样引用；"
            f"缺任何一块，这条定理的证明栏就没写完 —— 只能记成「{SUPPORTED_ONLY_WORD}」")
    return out


def program_state(workspace_root: str | Path | None, program: Any) -> dict[str, Any]:
    """证明栏那份程序的读数（形状与 `papermapping.file_state` 同：`state` + 理由）。

    `state` 五档里的四档在这里：`present` / `missing` / `empty` / `outside`。
    与论文包内相对路径那一路分开判，因为程序不在论文包里（它住 `code/`）。
    """
    raw = str(program or "").strip().replace("\\", "/")
    out: dict[str, Any] = {"state": "outside", "file": raw, "path": None, "reason": ""}
    if not raw:
        out["reason"] = "没填证明栏（数值实验定理的 `file` 就是那份程序的相对路径）"
        return out
    if not NP.is_script_path(raw):
        out["reason"] = (
            f"`file` = {raw!r} 不是「相对仓库根的程序脚本路径」：穷举证明的签名就是那份程序，"
            f"要写它的相对路径（后缀在 {list(NP.SCRIPT_SUFFIXES)} 里，不含盘符与 `..`）"
        )
        return out
    path, problem = _resolve(workspace_root, raw)
    if path is None:
        out["reason"] = f"`file` = {raw!r} 不合口径：{problem}"
        return out
    out["path"] = str(path)
    if not path.is_file():
        out["state"] = "missing"
        out["reason"] = f"`file` 指的 {raw} 在仓库里读不到（盘上没有这份程序）"
        return out
    try:
        size = path.stat().st_size
    except OSError as exc:
        out["state"] = "missing"
        out["reason"] = f"`file` 指的 {raw} 读不出来（{type(exc).__name__}: {exc}）"
        return out
    if size <= 0:
        out["state"] = "empty"
        out["reason"] = f"`file` 指的 {raw} 是空文件（空程序不可能穷举过任何东西）"
        return out
    out["state"] = "present"
    return out


def citation_present(segment: Any, *, program: Any, evidence_id: Any) -> bool:
    """正文那一段里有没有指回 E 的读数（程序路径或 `exp:NNNNNN` 两种写法都算）。

    为什么两种都算：正文是英文的，而内部编号按体例只许进附录 A；程序路径不是内部编号，
    它可以出现在正文里。两种写法都指向同一份读数（`program` 那一行实验就是它的签名）。
    """
    text = str(segment or "")
    if not text:
        return False
    want = NP.norm_rel(program)
    if want:
        variants = {want, want.replace("_", "\\_"), want.replace("_", r"\_")}
        if any(v and v in text for v in variants):
            return True
    eid = str(evidence_id or "").strip()
    return bool(eid) and eid in text


def evidence_index_problems(*, row: Mapping[str, Any] | None,
                            workspace_root: str | Path | None) -> list[str]:
    """数值实验定理那一行的索引四格（D-34）：空清单 = 目录行指得到盘上那一份正文。

    业主 2026-10-23 夜的模型：「D 侧报告的多半是新成果，B 基本都是从 D 的报告看到定理
    （命题），经索引看 F 侧证明或 E 侧报告，并核实 V 签」。于是这一行除了"三块证明栏"
    （程序 / ②③ / 落点）之外，还要能当目录用：

    | 格 | 键 | 这一行该填什么 |
    |---|---|---|
    | 证据是哪一档 | `evidence_kind` | 数值实验定理这一行是 `report`（E 的报告） |
    | 正文在哪 | `evidence_path` | E 那份读数的相对仓库路径（`out/experiments/<号>/exhaustion.md`） |
    | 正文的指纹 | `evidence_sha256` | 那份文件的字节 sha256 |
    | V 的签 | `v_signature` | `{"verdict": "成立", "sha256": <被签那一份的 sha256>}` |

    判据本体只有一份：`numericproof.resolve_index`（四格齐不齐、路径取不取到对象、
    两份 sha 对不对得上）。这里只多做两件本模块特有的事：

    1. `evidence_path` 必须就是 `exhaustion_note` 那一处（一块读数只有一个落点 ——
       两处各写一个地址，读的人不知道该信哪个）；
    2. 把问题翻成"这一组的那几档"（调用方按现有五档拦门接线，不新造词）。

    三态：没给工作区根 ⇒ `numericproof.resolve_index` 报"没查成" ⇒ 这里返回非空
    （没查成不许折成通过）。
    """
    row_map = dict(row or {}) if isinstance(row, Mapping) else {}
    entry = {
        NP.INDEX_KIND_FIELD: row_map.get(NP.INDEX_KIND_FIELD),
        NP.INDEX_PATH_FIELD: row_map.get(NP.INDEX_PATH_FIELD),
        NP.INDEX_SHA_FIELD: row_map.get(NP.INDEX_SHA_FIELD),
        NP.INDEX_SIGN_FIELD: row_map.get(NP.INDEX_SIGN_FIELD),
    }
    missing = NP.index_problems(entry)
    if missing:
        return [f"`{EVIDENCE_FIELD}` / `{NOTE_FIELD}` 那一行还缺索引 —— " + "；".join(missing) +
                "。业主 2026-10-23 夜：D 的报告是目录（新成果＋索引），B 顺着索引看 F 侧证明"
                "或 E 侧报告、并核实 V 签 —— 目录里没有这一条，B 就取不到正文，"
                "这一条也就登记不进定理证明库"]
    resolved = NP.resolve_index(workspace_root, entry)
    out: list[str] = []
    if resolved["problems"]:
        out.extend(str(p) for p in resolved["problems"])
        return out
    note = str(row_map.get(NOTE_FIELD) or "").strip()
    if note and NP.norm_rel(note) != NP.norm_rel(entry[NP.INDEX_PATH_FIELD]):
        out.append(
            f"`{NP.INDEX_PATH_FIELD}` 与 `{NOTE_FIELD}` 指的不是同一处："
            f"索引写 {entry[NP.INDEX_PATH_FIELD]!r}，两块读数的落点写 {note!r} —— "
            "一份读数只有一处落点，两个地址等于把「该信哪一份」留给读的人猜")
    return out


def _resolve(workspace_root: str | Path | None, raw: str) -> tuple[Path | None, str]:
    """把一条相对仓库根的路径解析成绝对路径（越界一律 None + 理由）。

    三态纪律：`workspace_root` 没给时返回 (None, 理由)，不是"路径没问题"。
    """
    if workspace_root is None:
        return None, "这一趟没给工作区根 ⇒ 这条相对路径无从解析（不是「合规」）"
    text = str(raw or "").strip().replace("\\", "/")
    if not text:
        return None, "路径是空的"
    candidate = Path(text)
    if candidate.is_absolute() or ":" in text:
        return None, "必须是相对仓库根的路径（收到绝对路径）"
    if ".." in text.split("/"):
        return None, "不许用 `..` 跳出仓库根"
    root = Path(workspace_root).resolve()
    target = (root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None, "解析之后跑到仓库根外面去了"
    return target, ""
