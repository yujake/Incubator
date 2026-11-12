# -*- coding: utf-8 -*-
"""手稿的逐格提取（「提取」侧）。

## 这一层做什么、不做什么

输入是（稿正文文本 + 族 + 要填的格），输出是每一格的提取读数：
`{格: {outcome, source: {section, lines, sha}, value, why}}`。它只做纯函数切节与
解析：不读写盘、不读 store、不读台账；切节复用 `depsection`，不另写一份。
「把取到的那几格写进哪一行」不在这里 —— 那是接线后的写口。

## 三态（与手稿录入同一口径，不许折平）

- `present`：稿里有这一节。`value` 是那一节的正文或解析结果；空节也算 present
  （空表 / 空正文是事实，不是"没有这一节"）。
- `absent`：稿里没有这一节。`value=None`、`source.sha=""`、`source.lines=[]`；
  调用方必须自己判，不许拿别的节或整份全文顶替（`e-num-*` 本来就没有 `## 证明`）。
- `unreadable`：传进来的根本不是文本（`None` / bytes / 别的类型）。这一态不是
  `absent`：没读到与"稿里没有这一节"是两件事。

## 切节的唯一实现

`_section` 只是 `depsection.section_lines` 的转发：判据（`## 证明` 到下一个同级或
更高级的标题为止，`### ` 及更深的小标题算节内）只有 `depsection.heading_level` /
`section_lines` 一处。抄一份镜像的代价是同一份稿在 V 稿闸里读得到正文、在逐格提取
里被截成空串，两处读数对不上。

## 冲突矩阵

`plan_cells(row, got, conflict)` 逐格给出 `filled / unchanged / kept / refused /
not_applicable`，并返回 `diff`（`requested_not_filled` / `filled_not_requested`）与
`derived_write`。它不读写盘、不认签：`proof_without_v_sign` 那条闸要读
`verifications` / `vsigns`，属于接线那一步。
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from . import depsection as _DS  # 切节的唯一实现（`section_lines` / `heading_level`）

#: 收录格的闭集（与 `manuscriptfamily.INGEST_CELLS` 同一份口径；判据钉住两处相等）。
INGEST_CELLS: tuple[str, ...] = (
    "statement_full", "proof_text", "dependencies", "kind", "numeric_evidence")

#: 族的名单（与 `manuscriptfamily.FAMILIES` 的键同一份口径；判据钉住两处相等）。
FAMILY_NAMES: tuple[str, ...] = ("f-proof", "b-proof", "e-proof", "e-num", "legacy")

#: 提取三态。
EXTRACT_PRESENT = "present"
EXTRACT_ABSENT = "absent"
EXTRACT_UNREADABLE = "unreadable"

#: 冲突策略（默认 fail-closed：`refuse`）。
CONFLICTS: tuple[str, ...] = ("refuse", "overwrite", "append", "keep")

#: 收录的三种模式：预览 / 按格回填 / 登记新命题。
#: 与 `agent_b.ingest_manuscript` 的 `mode` 枚举同一份口径（判据钉住两处相等）。
INGEST_MODES: tuple[str, ...] = ("apply", "preview", "register")

#: 计划结果的五种 outcome。
PLAN_FILLED = "filled"
PLAN_UNCHANGED = "unchanged"
PLAN_KEPT = "kept"
PLAN_REFUSED = "refused"
PLAN_NOT_APPLICABLE = "not_applicable"

#: 每一格从稿的哪儿取。`kind` 取稿头的元信息行，不是一个小节。
SECTION_BY_CELL: Mapping[str, str] = {
    "statement_full": "## 命题",
    "proof_text": "## 证明",
    "dependencies": "## 依赖",
    "kind": "head: - 证据种类：",
    "numeric_evidence": "## 数值结果",
}

#: 依赖表的列（与 `depsection.COLUMN_KEYS` 同一套关键词；顺序不限）。
#: 前三列缺一不可；最后一列 `path_group` 可省 —— 产出侧不写路径号，号由收录时的
#: 秘书在事务里分配（省了它 ⇒ 这一格按默认第 1 条落，由秘书覆盖）。
DEPENDENCY_COLUMNS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("quote", ("引用",), "引用（F 的原话）"),
    ("stmt_id", ("命题号", "stmt"), "命题号（stmt:NNNNNN）"),
    ("step", ("步",), "用在哪一步"),
    ("path_group", ("路径",), "路径号（第几条证明）"),
)

#: `DEPENDENCY_COLUMNS` 里可以省掉的那一列（唯一一列）。
DEPENDENCY_OPTIONAL_FIELDS: tuple[str, ...] = ("path_group",)

#: `kind` 的受控词表（`secretary.PROPOSITION_KINDS` 的镜像）。
#: 顺序按档位从弱到强：`kind` 只升不降，升要签。
KIND_RANK: Mapping[str, int] = {
    "conjecture": 0, "example": 1, "proposition": 2,
    "lemma": 3, "corollary": 4, "theorem": 5,
}

#: 与族表对齐的两张镜像（真身是 `manuscriptfamily` 的那张表）。
_ALLOWED_BY_FAMILY: Mapping[str, tuple[str, ...]] = {
    "f-proof": ("statement_full", "proof_text", "dependencies", "kind"),
    "b-proof": ("proof_text", "dependencies", "kind"),
    "e-proof": ("statement_full", "proof_text", "dependencies", "kind"),
    "e-num": ("statement_full", "numeric_evidence"),
    "legacy": (),
}
_DERIVED_BY_FAMILY: Mapping[str, tuple[str, ...]] = {
    "f-proof": ("bits", "proof_no", "proof_sha256", "kind", "proofs"),
    "b-proof": ("bits", "proof_no", "proof_sha256", "kind", "proofs"),
    "e-proof": ("bits", "proof_no", "proof_sha256", "kind", "proofs"),
    "e-num": ("bits", "grade"),
    "legacy": (),
}

#: 受控码（只在这一层用，不进工具面）。
CODE_LEGACY = "legacy_manuscript_name"
CODE_UNREADABLE = "manuscript_unreadable"
CODE_STATEMENT_ABSENT = "manuscript_statement_absent"
CODE_STATEMENT_EMPTY = "manuscript_statement_empty"
CODE_PROOF_ABSENT = "manuscript_proof_absent"
CODE_PROOF_EMPTY = "manuscript_proof_empty"
CODE_PROOF_EXISTS = "proof_text_exists_different"
CODE_PROOF_TAKEN = "proof_no_taken"
CODE_PROOF_GAP = "proof_no_gap"
CODE_DEP_MISSING = "dependency_section_missing"
CODE_DEP_UNREADABLE = "dependency_section_unreadable"
CODE_KIND_BAD = "bad_manuscript_kind"
CODE_KIND_DOWNGRADE = "kind_downgrade"
CODE_KIND_UPGRADE_UNSIGNED = "kind_not_upgraded_without_sign"
CODE_KIND_ROW_UNREADABLE = "kind_unreadable_on_row"
CODE_NUMERIC_ABSENT = "numeric_evidence_absent"
CODE_CELL_NOT_APPLICABLE = "cell_not_applicable_for_family"
CODE_STATEMENT_LOCKED = "proposition_locked"

#: 正文里点名的 `stmt:` 引用（只用来判"缺 `## 依赖` 时该不该拒"，不判在册）。
_STMT_REF_RE = re.compile(r"stmt:\s*(\d{4,6})")
#: 稿头元信息行（`- 证据种类：lemma` / `- 实验号：exp:000000`）。
_HEAD_FIELD_RE = re.compile(r"^\s*-\s*(?P<key>[^：:]+?)\s*[：:]\s*(?P<value>.*?)\s*$")
_EXPERIMENT_ID_RE = re.compile(r"^exp:(\d{4,6})$")


# ---------------------------------------------------------------- 切节（纯函数）


def _normalise(text: Any) -> tuple[str | None, str]:
    """入参 ⇒ `(规范化后的文本 或 None, 为什么读不出)`。

    三态纪律：`None` / bytes / 非字符串不是"空文本"，是 unreadable。空串是合法的
    "稿里什么都没有"，会走 `absent` 那一支（每一节都不在）。
    """
    if text is None:
        return None, "没有稿正文（None）⇒ 这一格没读到，不是「稿里没有这一节」"
    if isinstance(text, (bytes, bytearray)):
        return None, "稿正文是字节串而不是文本 ⇒ 这一格没读到（不猜编码）"
    if not isinstance(text, str):
        return None, (f"稿正文是 {type(text).__name__} 而不是文本 ⇒ "
                      "这一格没读到（不把它读成空稿）")
    return text.replace("\r\n", "\n").replace("\r", "\n"), ""


def _section(text: str, heading: str) -> tuple[list[tuple[int, str]], int]:
    """取某一节的正文行 ⇒ `([(行号, 原文)], 标题所在行号)`；没有这一节 ⇒ `([], 0)`。

    唯一实现是 :func:`depsection.section_lines`。
    标题行必须逐字以 `heading` 开头（后面可以跟括号说明或空白）；节从标题下一行开始、
    到下一个同级或更高级的标题或文末为止，`### ` 及更深的小标题算节内内容。
    入参已由 :func:`_normalise` 规范过换行，所以这里直接交给它。
    """
    body, start = _DS.section_lines(text, heading)
    return list(body), start


def _head_lines(text: str) -> list[tuple[int, str]]:
    """第一个二级标题（`## 小节`）之前的行（稿头元信息只在那一小段里认）。

    为什么不是"第一个 `#`"：e-num 稿以一级标题 `# E 的数值实验手稿：…` 开头，稿头
    元信息在它下面、`## 命题` 上面；按"任何 `#`"停会把标题下面那一段整段漏掉。
    """
    out: list[tuple[int, str]] = []
    for index, line in enumerate(text.split("\n"), 1):
        if line.strip().startswith("##"):
            break
        out.append((index, line))
    return out


def _span(heading_line: int, body: Sequence[tuple[int, str]]) -> list[int]:
    """一节在稿里的行号区间（闭区间）；空节 ⇒ 只有标题那一行。"""
    return [int(heading_line), int(body[-1][0]) if body else int(heading_line)]


def _sha(text: Any) -> str:
    """文本的 sha256（与 `verifications.text_sha` 同一把尺：不 strip、不加换行）。"""
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _reading(cell: str, outcome: str, *, lines: Sequence[int] = (), sha: str = "",
             value: Any = None, why: str = "", **extra: Any) -> dict[str, Any]:
    """一格的提取读数（键固定：`outcome` / `source` / `value` / `why` + 该格的附加读法）。"""
    out: dict[str, Any] = {
        "outcome": outcome,
        "source": {"section": SECTION_BY_CELL[cell], "lines": list(lines), "sha": sha},
        "value": value,
        "why": why,
    }
    out.update(extra)
    return out


def _absent(cell: str, why: str, **extra: Any) -> dict[str, Any]:
    """`absent` 的读数：value 是 None（不是空串）、source 没有行号与 sha。"""
    return _reading(cell, EXTRACT_ABSENT, value=None, why=why, **extra)


def _unreadable(cell: str, why: str) -> dict[str, Any]:
    """`unreadable` 的读数：没读到与"稿里没有这一节"分得开。"""
    return _reading(cell, EXTRACT_UNREADABLE, value=None, why=why)


# ---------------------------------------------------------------- 逐格解析


def _cells_of(line: str) -> list[str]:
    """一行 Markdown 表格 ⇒ 逐格（首尾的 `|` 不算格子）。"""
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]


def _is_separator(cells: Sequence[str]) -> bool:
    """Markdown 表的分隔行（`|---|:--:|`）。"""
    return bool(cells) and all(
        cell and set(cell) <= set("-: ") and "-" in cell for cell in cells)


def _parse_dependency_table(body: Sequence[tuple[int, str]]) -> tuple[list[dict[str, Any]],
                                                                      list[dict[str, Any]]]:
    """`## 依赖` 的四列表 ⇒ `(rows, problems)`（缺列 / 列数不对 / 号形不对都进 problems）。

    为什么按表头取列而不是按位置：表头换个顺序时位置读法会把 `step` 与 `path_group`
    静默互换，而那种错误不会让任何判据红（`depsection` 记过同一课）。
    """
    table = [(line_no, raw) for line_no, raw in body if raw.strip().startswith("|")]
    problems: list[dict[str, Any]] = []
    if not table:
        problems.append({"line": int(body[0][0]) if body else 0,
                         "why": "这一节下面没有表格：要给一张四列的表"})
        return [], problems
    header_line, header_raw = table[0]
    header_cells = _cells_of(header_raw)
    found: dict[str, int] = {}
    for index, cell in enumerate(header_cells):
        low = cell.lower()
        for field, keys, _name in DEPENDENCY_COLUMNS:
            if field in found:
                continue
            if any(key.lower() in low for key in keys):
                found[field] = index
                break
    missing = [name for field, _keys, name in DEPENDENCY_COLUMNS
               if field not in DEPENDENCY_OPTIONAL_FIELDS and field not in found]
    present = [field for field, _k, _n in DEPENDENCY_COLUMNS if field in found]
    if missing:
        problems.append({"line": header_line,
                         "why": (f"表头缺列：{missing}（这一节要 "
                                 f"{len(DEPENDENCY_COLUMNS) - len(DEPENDENCY_OPTIONAL_FIELDS)} 列，"
                                 "逐列固定；路径号那一列可省）")})
        return [], problems
    if len(header_cells) != len(present):
        problems.append({"line": header_line,
                         "why": (f"表头有 {len(header_cells)} 列，只有 {len(present)} 列认得出"
                                 f"（{' / '.join(n for _f, _k, n in DEPENDENCY_COLUMNS)}）")})
        return [], problems
    rows: list[dict[str, Any]] = []
    for line_no, raw in table[1:]:
        cells = _cells_of(raw)
        if _is_separator(cells):
            continue
        if len(cells) != len(present):
            problems.append({"line": line_no,
                             "why": f"这一行读出来 {len(cells)} 列，应有 "
                                    f"{len(present)} 列：{cells!r}"})
            continue
        row: dict[str, Any] = {"line": line_no}
        bad: list[str] = []
        for field in present:
            _keys, name = next((k, n) for f, k, n in DEPENDENCY_COLUMNS if f == field)
            value = cells[found[field]].strip().strip("`").strip()
            if not value:
                bad.append(f"缺 {name}")
                continue
            if field == "stmt_id":
                if not value.startswith("stmt:"):
                    bad.append(f"{name} 要是 stmt:NNNNNN（收到 {value!r}）")
                    continue
                row["stmt_id"] = value[len("stmt:"):].strip()
                continue
            if field == "path_group":
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    bad.append(f"{name} 要是正整数（收到 {value!r}）")
                    continue
                if number < 1:
                    bad.append(f"{name} 要是正整数（收到 {value!r}）")
                    continue
                row["path_group"] = number
                continue
            row[field] = value
        if bad:
            problems.append({"line": line_no, "why": "；".join(bad)})
            continue
        if "path_group" not in row:
            # 产出侧不写路径号 ⇒ 这一列不是"缺"，是"还没分配"（收录时由秘书给）。
            row["path_group"] = 1
        rows.append(row)
    return rows, problems


def _stmt_refs(text: str) -> list[str]:
    """一段正文里点名的 `stmt:` 引用（按出现顺序去重；只判"有没有引"，不判在册）。"""
    out: list[str] = []
    for code in _STMT_REF_RE.findall(text or ""):
        if code not in out:
            out.append(code)
    return out


def _extract_statement(text: str) -> dict[str, Any]:
    """`## 命题` ⇒ 命题正文（首尾空行与空白去掉，与 `depsection.statement_body` 同归一）。"""
    body, heading = _section(text, SECTION_BY_CELL["statement_full"])
    if not heading:
        return _absent("statement_full", "稿里没有 `## 命题` 那一节")
    value = "\n".join(raw for _line, raw in body).strip("\n").strip()
    return _reading("statement_full", EXTRACT_PRESENT, lines=_span(heading, body),
                    sha=_sha(value), value=value,
                    why=f"`## 命题` 第 {heading} 行起，正文 {len(value)} 字")


def _extract_proof(text: str) -> dict[str, Any]:
    """`## 证明` ⇒ 证明正文（只按行 join 后去掉首尾换行，与签的 sha 同一份归一）。"""
    body, heading = _section(text, SECTION_BY_CELL["proof_text"])
    if not heading:
        return _absent("proof_text",
                       "稿里没有 `## 证明` 那一节 ⇒ 没有可读的证明正文"
                       "（不拿 `## 依赖` 或整份全文顶替）")
    value = "\n".join(raw for _line, raw in body).strip("\n")
    return _reading("proof_text", EXTRACT_PRESENT, lines=_span(heading, body),
                    sha=_sha(value), value=value,
                    why=f"`## 证明` 第 {heading} 行起，正文 {len(value.strip())} 字")


def _extract_dependencies(text: str) -> dict[str, Any]:
    """`## 依赖` ⇒ 四列表的行；缺节时把证明正文里的 `stmt:` 引用一并带出（判缺节要不要拒）。"""
    body, heading = _section(text, SECTION_BY_CELL["dependencies"])
    proof = _extract_proof(text)
    refs = _stmt_refs(proof["value"]) if proof["outcome"] == EXTRACT_PRESENT else []
    if not heading:
        return _absent("dependencies",
                       "稿里没有 `## 依赖` 那一节（缺节本身不是拒，要看证明正文有没有引用）",
                       refs=refs, rows=0, problems=[])
    rows, problems = _parse_dependency_table(body)
    raw_table = "\n".join(raw for _line, raw in body if raw.strip().startswith("|"))
    return _reading("dependencies", EXTRACT_PRESENT, lines=_span(heading, body),
                    sha=_sha(raw_table), value=rows,
                    why=(f"`## 依赖` 第 {heading} 行起：{len(rows)} 行"
                         + (f"，{len(problems)} 处读不懂" if problems else "")),
                    rows=len(rows), problems=problems, refs=refs)


def _extract_kind(text: str) -> dict[str, Any]:
    """稿头 `- 证据种类：<kind>` ⇒ kind（小写；不在稿头里猜，也不从正文里猜）。"""
    for line_no, raw in _head_lines(text):
        matched = _HEAD_FIELD_RE.match(raw)
        if not matched:
            continue
        if matched.group("key").strip() != "证据种类":
            continue
        value = matched.group("value").strip().strip("`").strip().lower()
        if not value:
            return _absent("kind", f"稿头第 {line_no} 行声明了证据种类但是空的")
        return _reading("kind", EXTRACT_PRESENT, lines=[line_no, line_no],
                        sha=_sha(value), value=value,
                        why=f"稿头第 {line_no} 行声明的证据种类")
    return _absent("kind", "稿头没有 `- 证据种类：` 那一行 ⇒ 没有可填的档")


def _extract_numeric(text: str) -> dict[str, Any]:
    """`## 数值结果` ⇒ 数值凭据（方法 / 结果 / 逐项字段 + 稿头的实验号）。"""
    body, heading = _section(text, SECTION_BY_CELL["numeric_evidence"])
    if not heading:
        return _absent("numeric_evidence",
                       "稿里没有 `## 数值结果` 那一节 ⇒ 普通数值档没有可填的凭据")
    fields: dict[str, str] = {}
    for _line_no, raw in body:
        matched = _HEAD_FIELD_RE.match(raw)
        if matched:
            fields[matched.group("key").strip()] = matched.group("value").strip()
    experiment_id = ""
    for _line_no, raw in _head_lines(text):
        matched = _HEAD_FIELD_RE.match(raw)
        if not matched or matched.group("key").strip() != "实验号":
            continue
        exp = _EXPERIMENT_ID_RE.match(matched.group("value").strip().strip("`"))
        experiment_id = exp.group(1) if exp else ""
        break
    raw_section = "\n".join(raw for _line_no, raw in body)
    value = {"experiment_id": experiment_id,
             "method": fields.get("方法", ""),
             "result": fields.get("结果", ""),
             "fields": fields}
    return _reading("numeric_evidence", EXTRACT_PRESENT, lines=_span(heading, body),
                    sha=_sha(raw_section), value=value,
                    why=(f"`## 数值结果` 第 {heading} 行起：{len(fields)} 个字段；"
                         f"实验号 {experiment_id or '（稿头没写）'}"))


_EXTRACTORS = {
    "statement_full": _extract_statement,
    "proof_text": _extract_proof,
    "dependencies": _extract_dependencies,
    "kind": _extract_kind,
    "numeric_evidence": _extract_numeric,
}


def _normalise_cells(cells: Iterable[str]) -> tuple[str, ...]:
    """请求格 ⇒ 去重后的元组；空集 / 未知格 / 传了字符串都抛 `ValueError`（fail-closed）。"""
    if cells is None or isinstance(cells, (str, bytes)):
        raise ValueError("cells 要是格的序列（例如 [\"proof_text\"]），不是单个字符串")
    if not isinstance(cells, Iterable):
        raise ValueError(f"cells 要是格的序列，收到 {type(cells).__name__}")
    got: list[str] = []
    for cell in cells:
        name = str(cell).strip()
        if name not in INGEST_CELLS:
            raise ValueError(f"未知的收录格 {cell!r}：只有 {INGEST_CELLS}")
        if name not in got:
            got.append(name)
    if not got:
        raise ValueError("cells 不能是空的（至少请求一格）")
    return tuple(got)


def extract_cells(text: Any, family: str, cells: Iterable[str]) -> dict[str, dict[str, Any]]:
    """从稿正文里逐格提取 ⇒ `{格: {outcome, source, value, why}}`。

    参数：稿正文文本、族名（校验闭集；提取本身对族一视同仁 —— 族的合法性由
    `manuscriptfamily.allowed_cells` 判，不在这里判）、要填的格。

    对族一视同仁是有意的：`mode=apply` 里 `statement_full` 只校验不写，`preview` 还要
    能看 `legacy` 稿里有什么；若这里按族把格砍掉，"校验"与"预览"都会缺格。真正
    "这一族不许填这一格"的拒在 `plan_cells` 与接线后的工具层（码
    `cell_not_applicable_for_family`）。

    三态：`present` / `absent` / `unreadable`；`absent` 的 `value` 是 `None`、`source`
    没有行号与 sha —— 不许把别的节或整份全文填进来顶替（与手稿录入同一口径）。
    """
    family_name = str(family or "").strip()
    if family_name not in FAMILY_NAMES:
        raise ValueError(f"未知手稿族 {family!r}：只有 {FAMILY_NAMES}")
    requested = _normalise_cells(cells)
    normalised, why = _normalise(text)
    if normalised is None:
        return {cell: _unreadable(cell, why) for cell in requested}
    return {cell: _EXTRACTORS[cell](normalised) for cell in requested}


# ---------------------------------------------------------------- 冲突矩阵（纯函数）


def _row_dict(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """既有台账行 ⇒ 普通字典（None 表示"新行"，不是"读不到"）。

    三态纪律的落点：`None` 是 `mode=register` 的新行；一个读不出来的行必须由调用方
    显式传空字典并自己报 unreadable，这里不把"没给"与"读坏了"折成同一件事。
    """
    return dict(row) if row else {}


def _is_register(row: Mapping[str, Any]) -> bool:
    """这一笔是不是新行（`mode=register`：没有既有号，statement_full 可写）。"""
    return not str(row.get("stmt_id") or "").strip() and not row.get("statement_full")


def _proofs(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """行上的 `proofs` 那一列（多份证明；只认 dict 条目，坏条目跳过并保留原样读法）。"""
    got = row.get("proofs")
    if not isinstance(got, list):
        return []
    return [one for one in got if isinstance(one, dict)]


def _proof_no_of(item: Mapping[str, Any]) -> int:
    """一份证明的号（读不出 ⇒ 0，不猜）。"""
    try:
        return int(item.get("proof_no") or 0)
    except (TypeError, ValueError):
        return 0


def _has_p1(row: Mapping[str, Any]) -> bool:
    """这一行有没有第一份证明（canonical 正文或 proofs 里的 #p1）。"""
    if str(row.get("proof_text") or "").strip():
        return True
    return any(_proof_no_of(one) == 1 for one in _proofs(row))


def _same_numeric_program(left: Any, right: Any) -> bool:
    """两份数值凭据是不是同一程序（按 `code_path` / `method` / `result` 三格比）。"""
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        return False
    keys = ("code_path", "method", "result")
    if not any(str(left.get(key) or "").strip() for key in keys):
        return False
    return all(str(left.get(key) or "").strip() == str(right.get(key) or "").strip()
               for key in keys)


def _refused(reading: Mapping[str, Any], writable: bool, code: str,
             reason: str, **extra: Any) -> dict[str, Any]:
    """一格的计划读数（`refused`）：把提取读数原样带上，调用方仍能看见来源。"""
    out: dict[str, Any] = {
        "requested": True, "writable": bool(writable), "outcome": PLAN_REFUSED,
        "source": reading.get("source") or {}, "value": reading.get("value"),
        "code": code, "reason": reason,
    }
    out.update(extra)
    return out


def _planned(reading: Mapping[str, Any], outcome: str, writable: bool = True,
             reason: str = "", code: str = "", **extra: Any) -> dict[str, Any]:
    """一格的计划读数（非拒档）：`filled` / `unchanged` / `kept` / `not_applicable`。"""
    out: dict[str, Any] = {
        "requested": True, "writable": bool(writable), "outcome": outcome,
        "source": reading.get("source") or {}, "value": reading.get("value"),
        "code": code, "reason": reason,
    }
    out.update(extra)
    return out


def _plan_statement(reading: Mapping[str, Any], row: Mapping[str, Any],
                    conflict: str) -> dict[str, Any]:
    """`statement_full`：新行可写；在册行只校验（相同 unchanged、不同 proposition_locked）。"""
    if reading.get("outcome") != EXTRACT_PRESENT:
        return _refused(reading, False, CODE_STATEMENT_ABSENT,
                        "稿里没有可读的 `## 命题` ⇒ 这一格填不了")
    value = str(reading.get("value") or "")
    if not value:
        return _refused(reading, False, CODE_STATEMENT_EMPTY, "`## 命题` 那一节是空的")
    if _is_register(row):
        return _planned(reading, PLAN_FILLED, writable=True, reason="新行：命题正文可写")
    existing = str(row.get("statement_full") or "")
    if existing == value:
        return _planned(reading, PLAN_UNCHANGED, writable=False,
                        reason="与台账逐字相同（幂等）")
    return _refused(reading, False, CODE_STATEMENT_LOCKED,
                    "在册行的命题正文只读：稿里的命题与台账不同 ⇒ 改命题只能重新登记"
                    f"（台账 {len(existing)} 字 / 稿 {len(value)} 字；conflict={conflict} 也不放行）")


def _plan_proof(reading: Mapping[str, Any], row: Mapping[str, Any],
                conflict: str, proof_no: int,
                *, append_new_path: bool = False) -> dict[str, Any]:
    """`proof_text`：空 ⇒ 填；同 sha ⇒ unchanged；不同 ⇒ 逐档按冲突矩阵。"""
    if reading.get("outcome") != EXTRACT_PRESENT:
        return _refused(reading, True, CODE_PROOF_ABSENT,
                        "稿里没有 `## 证明` ⇒ 没有要写的证明正文（缺节不等于空证明）")
    value = str(reading.get("value") or "")
    if not value.strip():
        return _refused(reading, True, CODE_PROOF_EMPTY,
                        "`## 证明` 那一节是空的 ⇒ 空正文不是一份证明")
    value_sha = str((reading.get("source") or {}).get("sha") or "")
    current = str(row.get("proof_text") or "")
    current_sha = str(row.get("proof_sha256") or "")
    if current and not current_sha:
        current_sha = _sha(current)
    if current and current_sha == value_sha:
        return _planned(reading, PLAN_UNCHANGED, writable=True,
                        reason="台账正文与稿同一 sha（幂等）")
    if not current and not _proofs(row):
        if int(proof_no) >= 2:
            return _refused(reading, True, CODE_PROOF_GAP,
                            f"稿是 #p{proof_no}，但这一行还没有 #p1 ⇒ 先录 #p1")
        return _planned(reading, PLAN_FILLED, writable=True,
                        reason="这一行的证明正文是空的 ⇒ 填 canonical 正文")
    if int(proof_no) >= 2:
        hit = [one for one in _proofs(row) if _proof_no_of(one) == int(proof_no)]
        if hit:
            hit_sha = str(hit[0].get("proof_sha256") or "")
            if hit_sha and hit_sha == value_sha:
                return _planned(reading, PLAN_UNCHANGED, writable=True,
                                reason=f"#p{proof_no} 已是这一份正文（幂等）")
            return _refused(reading, True, CODE_PROOF_TAKEN,
                            f"#p{proof_no} 已被另一份正文占用 ⇒ 换一个证明号")
        if not _has_p1(row):
            return _refused(reading, True, CODE_PROOF_GAP,
                            f"稿是 #p{proof_no}，但这一行还没有 #p1 ⇒ 先录 #p1")
        return _planned(reading, PLAN_FILLED, writable=True,
                        reason=f"追加第 {proof_no} 份证明（append）")
    if append_new_path and conflict == "refuse":
        # 换了稿 / 换了正文 ⇒ 同一命题的另一条证明路径（不是覆盖在册那一份）。
        # 号由收录时的秘书在事务里分配，这一层只判"可写"。
        return _planned(reading, PLAN_FILLED, writable=True,
                        reason=("追加一条新的证明路径（路径号由收录时的秘书分配）"))
    if conflict == "keep":
        return _planned(reading, PLAN_KEPT, writable=True,
                        reason="conflict=keep：保留台账现值，跳过这一格")
    if conflict == "refuse":
        return _refused(reading, True, CODE_PROOF_EXISTS,
                        "台账已有另一份正文；要覆盖给 overwrite、要追加给 append、"
                        "要跳过给 keep（默认拒）")
    return _planned(reading, PLAN_FILLED, writable=True,
                    reason=("conflict=overwrite：覆盖这一格（旧正文进 proof_history、"
                            "旧签现算成 stale；签闸仍由接线后的写口判）"))


def _plan_dependencies(reading: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    """`dependencies`：永远是追加 + 去重（依赖是集合，不是版本）；缺节看有没有引用。"""
    if reading.get("outcome") == EXTRACT_UNREADABLE:
        return _refused(reading, True, CODE_UNREADABLE,
                        str(reading.get("why") or "依赖段没读到"))
    if reading.get("outcome") == EXTRACT_ABSENT:
        refs = list(reading.get("refs") or [])
        if refs:
            return _refused(reading, True, CODE_DEP_MISSING,
                            "证明正文引了在册命题，而稿里没有 `## 依赖` 那一节 ⇒ 整笔拒"
                            f"（引用：{', '.join('stmt:' + one for one in refs)}）")
        return _planned(reading, PLAN_NOT_APPLICABLE, writable=True,
                        reason="稿里没有 `## 依赖`，证明正文也没有引用 ⇒ 这一格不适用")
    problems = list(reading.get("problems") or [])
    if problems:
        return _refused(reading, True, CODE_DEP_UNREADABLE,
                        "依赖段读不懂：" + "；".join(str(one.get("why") or one)
                                                  for one in problems))
    rows = list(reading.get("value") or [])
    if not rows:
        return _planned(reading, PLAN_UNCHANGED, writable=True,
                        reason="稿里的依赖表是空表 ⇒ 没有要写的行")
    existing = row.get("dependencies")
    seen = set()
    if isinstance(existing, list):
        for one in existing:
            if isinstance(one, Mapping):
                seen.add((str(one.get("stmt_id") or ""),
                          str(one.get("path_group") or ""),
                          str(one.get("step") or "")))
    duplicates = sum(1 for one in rows
                     if (str(one.get("stmt_id") or ""),
                         str(one.get("path_group") or ""),
                         str(one.get("step") or "")) in seen)
    return _planned(reading, PLAN_FILLED, writable=True,
                    reason=f"追加 {len(rows)} 行（去重 {duplicates} 行；依赖永不删）",
                    rows_written=len(rows), duplicates=duplicates)


def _plan_kind(reading: Mapping[str, Any], row: Mapping[str, Any],
               conflict: str) -> dict[str, Any]:
    """`kind`：只升不降；升档要签（无签 ⇒ kept + 读数，不写）；降 ⇒ 拒。"""
    if reading.get("outcome") == EXTRACT_UNREADABLE:
        return _refused(reading, True, CODE_UNREADABLE,
                        str(reading.get("why") or "稿头没读到"))
    if reading.get("outcome") == EXTRACT_ABSENT:
        return _planned(reading, PLAN_NOT_APPLICABLE, writable=True,
                        reason="稿头没有声明证据种类 ⇒ 这一格不适用（不拿台账现值冒充稿头）")
    value = str(reading.get("value") or "")
    if value not in KIND_RANK:
        return _refused(reading, True, CODE_KIND_BAD,
                        f"稿头声明的证据种类 {value!r} 不在受控词表 {tuple(KIND_RANK)} 里")
    if str(row.get("kind") or "") in ("concept", "definition"):
        return _refused(reading, True, CODE_CELL_NOT_APPLICABLE,
                        "概念 / 定义行没有证明档 ⇒ 不收 kind")
    current = str(row.get("kind") or "")
    if _is_register(row) or not current:
        return _planned(reading, PLAN_FILLED, writable=True,
                        reason="新行：按稿头声明落 kind")
    if value == current:
        return _planned(reading, PLAN_UNCHANGED, writable=True, reason="与台账相同")
    if current not in KIND_RANK:
        return _refused(reading, True, CODE_KIND_ROW_UNREADABLE,
                        f"台账上的 kind {current!r} 不在受控词表里 ⇒ 不比较强弱")
    if KIND_RANK[value] > KIND_RANK[current]:
        return _planned(reading, PLAN_KEPT, writable=True,
                        reason=(f"台账更弱（{current}）、稿头更强（{value}）⇒ 签后才升；"
                                "这一格先 kept"),
                        code=CODE_KIND_UPGRADE_UNSIGNED)
    if conflict == "keep":
        return _planned(reading, PLAN_KEPT, writable=True,
                        reason=f"conflict=keep：保留台账的 {current}（稿头 {value} 更弱）")
    return _refused(reading, True, CODE_KIND_DOWNGRADE,
                    f"只升不降：台账 {current} 强于稿头 {value} ⇒ 拒")


def _plan_numeric(reading: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    """`numeric_evidence`：同一程序 ⇒ unchanged；否则填（只 e-num 适用）。"""
    if reading.get("outcome") == EXTRACT_UNREADABLE:
        return _refused(reading, True, CODE_UNREADABLE,
                        str(reading.get("why") or "数值结果没读到"))
    if reading.get("outcome") == EXTRACT_ABSENT:
        return _refused(reading, True, CODE_NUMERIC_ABSENT,
                        "稿里没有 `## 数值结果` ⇒ 普通数值档没有可填的凭据")
    value = reading.get("value") or {}
    existing = row.get("numeric_evidence")
    if _same_numeric_program(value, existing):
        return _planned(reading, PLAN_UNCHANGED, writable=True,
                        reason="与台账已有凭据同一程序（幂等）")
    return _planned(reading, PLAN_FILLED, writable=True,
                    reason="填入这一份数值凭据（code_path / method / result 与台账不同）")


def _derived(family: str, got: Mapping[str, Any]) -> list[str]:
    """这一笔会顺带写的派生列（有族名按表；没有就按请求格推，仍只给派生列）。"""
    if family in _DERIVED_BY_FAMILY:
        return list(_DERIVED_BY_FAMILY[family])
    if "numeric_evidence" in got:
        return list(_DERIVED_BY_FAMILY["e-num"])
    if "proof_text" in got:
        return list(_DERIVED_BY_FAMILY["e-proof"])
    return []


def plan_cells(row: Mapping[str, Any] | None, got: Mapping[str, Mapping[str, Any]],
               conflict: str = "refuse", *, family: str = "",
               proof_no: int = 1, append_new_path: bool = False) -> dict[str, Any]:
    """把提取读数对到既有行上 ⇒ 逐格计划。

    `row` 是既有台账行（`None` / 空字典 = `mode=register` 的新行），`got` 是
    `extract_cells` 的返回，`conflict` 是逐格策略。`family` 与 `proof_no` 是接线时由
    工具层从稿名读出的坐标（本函数不读稿名）。

    `append_new_path`：这一份稿是同一命题的另一条证明路径（换了稿 / 换了正文）。
    产出侧不再写 `-pN` 之后，"这是第几份"在计划这一步还不知道（号由收录时的秘书分）
    ⇒ 这一格只说"追加"，不比对某个具体号；真正的号与写入由秘书那一笔事务判。

    返回键：`ok` / `cells` / `diff` / `derived_write` / `refused` / `reason` / `written`。
    两条硬不变量：

    - I1：`diff.filled_not_requested == []` —— 实际改动只可能落在请求格与派生列里；
    - I2：`diff.requested_not_filled` 的每一条都带 `outcome ∈ {refused, kept,
      not_applicable}` 与非空的 `reason`。

    这一层不认签：`proof_without_v_sign` 要读 `verifications` / `vsigns`，属于接线后
    的写口；也不写盘（`mode=preview` 与 `apply` 共用这一份计划）。
    """
    policy = str(conflict or "refuse").strip()
    if policy not in CONFLICTS:
        raise ValueError(f"未知冲突策略 {conflict!r}：只有 {CONFLICTS}")
    family_name = str(family or "").strip()
    if family_name and family_name not in FAMILY_NAMES:
        raise ValueError(f"未知手稿族 {family!r}：只有 {FAMILY_NAMES}")
    unknown = [cell for cell in got if cell not in INGEST_CELLS]
    if unknown:
        raise ValueError(f"未知的收录格 {unknown!r}：只有 {INGEST_CELLS}")
    try:
        proof_no_now = int(proof_no)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"证明号要是 >=1 的整数，收到 {proof_no!r}") from exc
    if proof_no_now < 1:
        raise ValueError(f"证明号要是 >=1 的整数，收到 {proof_no!r}")
    row_now = _row_dict(row)
    register = _is_register(row_now)
    allowed = _ALLOWED_BY_FAMILY.get(family_name) if family_name else None
    cells: dict[str, dict[str, Any]] = {}
    for cell in INGEST_CELLS:
        if cell not in got:
            continue
        reading = got[cell]
        if family_name == "legacy":
            cells[cell] = _refused(reading, False, CODE_LEGACY,
                                   "历史档：可列出、可 preview、不可签、不可收录；"
                                   "要收录先落成规范名")
            continue
        if allowed is not None and cell not in allowed:
            cells[cell] = _refused(
                reading, False, CODE_CELL_NOT_APPLICABLE,
                f"{family_name} 只能填 {allowed}；这一格不在里面")
            continue
        if cell == "statement_full":
            cells[cell] = _plan_statement(reading, row_now, policy)
        elif cell == "proof_text":
            cells[cell] = _plan_proof(reading, row_now, policy, proof_no_now,
                                      append_new_path=bool(append_new_path))
        elif cell == "dependencies":
            cells[cell] = _plan_dependencies(reading, row_now)
        elif cell == "kind":
            cells[cell] = _plan_kind(reading, row_now, policy)
        else:
            cells[cell] = _plan_numeric(reading, row_now)
    requested_not_filled = [
        cell for cell in INGEST_CELLS
        if cell in cells and cells[cell]["outcome"] not in (PLAN_FILLED, PLAN_UNCHANGED)]
    refusals = [cells[cell] for cell in INGEST_CELLS
                if cell in cells and cells[cell]["outcome"] == PLAN_REFUSED]
    return {
        "ok": not refusals,
        "cells": cells,
        "diff": {"requested_not_filled": requested_not_filled,
                 "filled_not_requested": []},
        "derived_write": _derived(family_name, got),
        "refused": str(refusals[0]["code"]) if refusals else "",
        "reason": str(refusals[0]["reason"]) if refusals else "",
        "written": any(one["outcome"] == PLAN_FILLED for one in cells.values()),
        "target_is_register": register,
    }
