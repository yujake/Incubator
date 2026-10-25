"""F 手稿里的依赖段：唯一解析点 ＋ 引用档位的唯一判据（业主 2026-10-24 最终形态）。

## 业主原话（唯一权威）

    「依赖面登记是否是F在其手稿中写好，D的研究手稿引用F的证明手稿给B入库时，B侧读到
      F手稿处的依赖面，按此入库的？（即和V签一个逻辑）」
    「改」

⇒ 作者只写内容，登记由收方读稿产生（与 V 读 F 的手稿再签字同构）。所以：

- F 在证明手稿里写一节固定格式的依赖段（表格四列，见 :data:`COLUMN_KEYS`）；
- B 在入库时读那一节，落 `dependencies`（`used_by="stmt:<命题号>#pN"` ＋ `path_group`
  ＋ `source_stmt_id`）；F 自己不写依赖台账，也没有写台账的工具。

## 为什么格式必须固定

四趟真机的 `dependencies` 全 0 行，根因之一就是"证明正文是中文散文"：秘书那条扫描只认
`stmt:` / `lit:` / `exp:` / `doc:` 四种前缀，散文里一条都扫不出来，而"扫不到"与"没有"
在读数上长得一样。固定表格把"作者心里的依赖"变成"机器读得动的一行"，缺列、坏号、
第几行读不懂都能逐行点名。

## 三条判据（本文件是它们的唯一实现，B 与 F 的只读预览都读它）

1. 解析：段标题 `## 依赖`，下面一张四列表；缺表头 / 缺列 / 列数不对 / 命题号形状不对 /
   路径号不是正整数 ⇒ 逐条进 `problems`（带行号与列名），调用方整笔受控拒绝；
2. 引用档位（业主加码裁定，逐字：「proof_review级及以上才可引用」）：来源那一行的
   `evidence_kind` 必须站到 `proof_review` 及以上；允许集合从等级序现算
   （:func:`citation_levels`），不写死字面量；档位读不到 ⇒ fail-closed；
3. 三态读数（`present` / `missing` / `not_applicable`）：读数实现仍是秘书那一份
   （`secretary._deps_missing_reading`），本文件只负责把"手稿里有没有依赖段"这件事
   如实叠上去 —— 手稿没有段而证明正文里出现了 `stmt:` 引用，是 `missing`，不是 0。

## 边界

本文件不写任何表：B 落库那一步仍走 `Secretary.record_statement`（它有 `statements` 与
`dependencies` 两张表的写权），F 那一侧只有"写自己的手稿"和"只读预览"。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from . import schema as S


#: 依赖段的段标题（固定，逐字）。
SECTION_HEADING = "## 依赖"

#: 证明正文那一节的段标题（预览时"引用了哪些 `stmt:`"只在这一节里数 —— 手稿开头的
#: 元信息（"命题号：stmt:000002"）不是引用，把它数进来会让读数虚高）。
SECTION_PROOF = "## 证明"

#: 表格的四列：`(字段名, 认得出的关键词, 人读的列名)`。
#:
#: 识别按关键词（表头写"命题号（stmt:NNNNNN）"也认），但四列缺一不可、顺序不限 ——
#: 顺序不限不是放宽：缺哪一列会被点名，而"列数不对"同样进 `problems`。
COLUMN_KEYS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("quote", ("引用",), "引用（F 的原话）"),
    ("stmt_id", ("命题号", "stmt"), "命题号（stmt:NNNNNN）"),
    ("step", ("步",), "用在哪一步"),
    ("path_group", ("路径",), "路径号（第几条证明）"),
)

#: 引用门槛的那一档（业主 2026-10-24，逐字：「proof_review级及以上才可引用」）。
CITATION_MIN_LEVEL = "proof_review"

#: 解析失败的受控码（B 那一侧据此整笔拒绝）。
REFUSED_SECTION = "dependency_section_unreadable"
#: 手稿没有 `## 依赖` 那一节、而证明正文引用了在册命题（整笔拒绝）。
REFUSED_SECTION_MISSING = "dependency_section_missing"
#: 来源不在册 / 不可用 / 档位读不到 / 档位不够，各一档受控码。
REFUSED_UNKNOWN_SOURCE = "dependency_source_not_registered"
REFUSED_SOURCE_STATUS = "dependency_source_not_usable"
REFUSED_LEVEL_UNREADABLE = "citation_level_unreadable"
REFUSED_LEVEL_TOO_LOW = "citation_below_proof_review"


def citation_levels() -> frozenset[str]:
    """`CITATION_MIN_LEVEL` 及以上那几档 —— 从等级序现算，不写死一个字面量列表。

    两处声明的交叉核对（缺一条就是"读错顺序也能过"）：

    - `schema.EVIDENCE_KINDS` 的声明序（由强到弱：`proof` · `proof_review` ·
      `cross_check` · `heuristic`，见那一格的注释）；
    - `tools/verify_tools.py::_EVIDENCE_ORDER` 的证据力序（由弱到强），它在导入期
      已经断言自己是 `EVIDENCE_KINDS` 的一个排列 —— 这里再核一次"它恰好是逆序"，
      于是"顺序口径"只有一份，漂开就在导入期炸。

    返回的集合从 `CITATION_MIN_LEVEL` 那一位切到最强端：今天是
    `{proof_review, proof}`，但它是算出来的（换一档门槛或调等级序会跟着变）。
    """
    # 私名 import：`_EVIDENCE_ORDER` 是本仓唯一的"证据力排序"声明（弱 → 强），
    # 它在自己的模块里已经与 `schema.EVIDENCE_KINDS` 对过账。这里不另写一份排序。
    from .tools.verify_tools import _EVIDENCE_ORDER as weak_to_strong

    declared = tuple(S.EVIDENCE_KINDS)
    ordered = tuple(weak_to_strong)
    assert set(ordered) == set(declared), (
        f"`verify_tools._EVIDENCE_ORDER`={ordered} 与 `schema.EVIDENCE_KINDS`={declared} "
        "不是同一批取值 ⇒ 引用档位算不出来（等级序必须只有一份定义）")
    assert ordered == tuple(reversed(declared)), (
        f"`schema.EVIDENCE_KINDS` 的声明序 {declared} 与证据力序 {ordered} 不是互逆关系 "
        "⇒ 「proof_review 级及以上」会算错，而错的那一侧放行的是弱档"
        "（两份顺序声明必须互为逆序，改一处就得改另一处）")
    assert CITATION_MIN_LEVEL in ordered, (
        f"引用门槛 {CITATION_MIN_LEVEL!r} 不在证据力序 {ordered} 里 ⇒ 门槛切不出来")
    return frozenset(ordered[ordered.index(CITATION_MIN_LEVEL):])


#: 允许被引用的档位集合（导入期算一次；值来自 `citation_levels()`，不是手抄的列表）。
CITATION_LEVELS: frozenset[str] = citation_levels()


def citation_level_allowed(level: str) -> bool:
    """这一档够不够「proof_review 级及以上」（判据只有这一处，三条路径都读它）。

    空串 / 词表外的取值一律返回假：排不出等级的档位不许当成"合格"
    （三态纪律：读不到不是"查过了、够格"）。
    """
    return str(level or "").strip() in CITATION_LEVELS


def dep_kind_of(statement_kind: str) -> str:
    """来源那一行的 `statements.kind` 该记成哪一档 `schema.DEP_KINDS`。

    `Dependency.validate` 只认 `DEP_KINDS`，而 `Statement.kind` 是自由文本。
    落在表外的 kind 一律按 `theorem` 记 —— 保守方向：不把一条命题说成比它更弱或更强。
    """
    got = str(statement_kind or "").strip().lower()
    return {
        "theorem": "theorem",
        "lemma": "lemma",
        "proposition": "proposition",
        "corollary": "proposition",
        "definition": "definition",
        "concept": "definition",
        "conjecture": "proposition",
        "prior_art": "prior_art",
        "dataset": "dataset",
        "experiment": "experiment",
    }.get(got, "theorem")


# ------------------------------------------------------------------ 解析


def _cells(line: str) -> list[str]:
    """一行 Markdown 表格 ⇒ 逐格（去首尾空白；首尾的 `|` 不算格子）。"""
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


def section_lines(text: str, heading: str = SECTION_HEADING) -> tuple[list[tuple[int, str]], int]:
    """取出某一节的正文行 ⇒ `([(行号, 原文)], 段标题所在行号)`；没有这一节 ⇒ `([], 0)`。

    段从标题行下一行开始，到下一个 Markdown 标题（`#` 开头）或文末为止。
    """
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    start = 0
    for i, line in enumerate(lines, 1):
        norm = line.strip()
        if not norm.startswith(heading):
            continue
        rest = norm[len(heading):]
        if rest and not rest.startswith(("（", "(", " ", "\t")):
            continue
        start = i
        break
    if not start:
        return [], 0
    body: list[tuple[int, str]] = []
    for i, line in enumerate(lines[start:], start + 1):
        if line.strip().startswith("#"):
            break
        body.append((i, line))
    return body, start


def proof_body(text: str) -> str:
    """手稿里"证明正文"那一节的正文（没有那一节 ⇒ 去掉依赖段之后的全文）。

    为什么单独取这一节：预览要回答的是"证明正文里引了哪些在册命题"，而手稿开头的
    元信息（"命题号：stmt:000002"）不是引用 —— 把它数进来会让 `refs` 与
    `derived_from` 都虚高，而那种虚高不会让任何判据红，只会让读数难看。
    """
    body, _start = section_lines(text, SECTION_PROOF)
    if not body:
        body, _start = section_lines(text, SECTION_HEADING)
        if not body:
            return str(text or "")
        first = body[0][0]
        lines = str(text or "").replace("\r\n", "\n").split("\n")
        return "\n".join(lines[: max(0, first - 1)])
    return "\n".join(raw for _ln, raw in body)


def parse_dependency_section(text: str) -> dict[str, Any]:
    """把一份手稿里的依赖段解析成行 ⇒ 三态读数（`checked` / `present` / `problems`）。

    返回键：
    - `checked`：解析跑了没有（本函数恒为 True —— 它没有"没查成"的路径；
      "段不存在"是 `present=False`，不是没查成）；
    - `present`：手稿里有没有 `## 依赖` 这一节；
    - `heading_line`：段标题在第几行（1 起；没有段 ⇒ 0）；
    - `rows`：`[{quote, stmt_id, step, path_group, line}]`（按文件顺序）；
    - `problems`：`[{line, why}]` —— 缺表头 / 缺列 / 列数不对 / 命题号形状 / 路径号；
    - `refused`：`REFUSED_SECTION` 或空串（调用方据此整笔拒绝）；
    - `reason`：一句话（拒信的第一句，带行号与列名）。
    """
    body, heading_line = section_lines(text)
    out: dict[str, Any] = {
        "checked": True, "present": bool(heading_line), "heading_line": heading_line,
        "rows": [], "problems": [], "refused": "", "reason": "",
    }
    if not heading_line:
        return out
    table = [(ln, raw) for ln, raw in body if raw.strip().startswith("|")]
    if not table:
        out["problems"].append({
            "line": heading_line,
            "why": (f"`{SECTION_HEADING}` 下面没有表格：要给一张四列的表"
                    f"（{' / '.join(name for _f, _k, name in COLUMN_KEYS)}）")})
    header_cells: list[str] = []
    if table:
        header_line, header_raw = table[0]
        header_cells = _cells(header_raw)
        found: dict[str, int] = {}
        for idx, cell in enumerate(header_cells):
            low = cell.lower()
            for field, keys, _name in COLUMN_KEYS:
                if field in found:
                    continue
                if any(key.lower() in low for key in keys):
                    found[field] = idx
                    break
        missing = [name for field, _keys, name in COLUMN_KEYS if field not in found]
        if missing:
            out["problems"].append({
                "line": header_line,
                "why": (f"表头缺列：{missing}（这一节要四列，逐列固定："
                        f"{' / '.join(name for _f, _k, name in COLUMN_KEYS)}）")})
        elif len(header_cells) != len(COLUMN_KEYS):
            out["problems"].append({
                "line": header_line,
                "why": (f"表头有 {len(header_cells)} 列，这一节要恰好 {len(COLUMN_KEYS)} 列"
                        f"（{' / '.join(name for _f, _k, name in COLUMN_KEYS)}）")})
        out["columns"] = [field for field, _k, _n in COLUMN_KEYS if field in found]
        out["column_index"] = dict(found)
    # ---- 逐行读表格（表头之后：分隔行跳过，其余每一行都要是完整的一条）
    for line_no, raw in table[1:]:
        cells = _cells(raw)
        if _is_separator(cells):
            continue
        if len(cells) != len(COLUMN_KEYS):
            out["problems"].append({
                "line": line_no,
                "why": (f"这一行读出来 {len(cells)} 列，应有 {len(COLUMN_KEYS)} 列："
                        f"{cells!r}（{SECTION_HEADING} 那张表一行一条依赖）")})
            continue
        row: dict[str, Any] = {"line": line_no}
        bad: list[str] = []
        for idx, (field, _keys, name) in enumerate(COLUMN_KEYS):
            value = cells[idx].strip().strip("`").strip()
            if not value:
                bad.append(f"缺 `{name}`")
                continue
            if field == "stmt_id":
                if not value.startswith("stmt:"):
                    bad.append(f"`{name}` 要是 `stmt:NNNNNN`（收到 {value!r}）")
                    continue
                sid = value[len("stmt:"):].strip()
                if not S.is_valid_id(sid):
                    bad.append(f"`{name}` 的号不是 {S.ID_DIGITS} 位十进制（收到 {sid!r}）")
                    continue
                row["stmt_id"] = sid
                continue
            if field == "path_group":
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    bad.append(f"`{name}` 要是正整数（收到 {value!r}）")
                    continue
                if number < 1:
                    bad.append(f"`{name}` 要是正整数（收到 {value!r}）")
                    continue
                row["path_group"] = number
                continue
            row[field] = value
        if bad:
            out["problems"].append({"line": line_no, "why": "；".join(bad)})
            continue
        out["rows"].append(row)
    if out["problems"]:
        out["refused"] = REFUSED_SECTION
        first = out["problems"][0]
        out["reason"] = (f"手稿的依赖段读不懂（`{SECTION_HEADING}`，第 {first['line']} 行起）："
                         + "；".join(f"第 {p['line']} 行——{p['why']}" for p in out["problems"]))
    return out


def stmt_refs(text: str) -> list[str]:
    """一段正文里点名的 `stmt:` 引用（裸号，按出现顺序去重）。

    扫描实现不在这里：`textutil.find_citations` 是全仓唯一那一条（秘书的
    `_scan_proof_deps` 也读它）—— 两份扫描会漂，漂的形态是"B 读到的引用数"
    与"秘书扫到的引用数"不一致，而那份不一致没有任何地方会报。
    """
    from . import textutil as T

    out: list[str] = []
    for ref in T.find_citations(str(text or "")):
        if str(ref.get("prefix")) != "stmt":
            continue
        code = str(ref.get("code") or "").strip()
        # 只要真号：手稿里那张表的表头写着 `stmt:NNNNNN`（占位符），它不是一条引用。
        if code and S.is_valid_id(code) and code not in out:
            out.append(code)
    return out


# ------------------------------------------------------------------ 档位门


def gate_rows(rows: Iterable[Mapping[str, Any]],
              statement_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """逐条核"来源在册 / 可用 / 档位够不够" ⇒ 一份可整笔拒绝的读数。

    返回 `{"checked", "ok", "refused", "reason", "levels": {号: 档}, "rows": [...]}`。
    判据顺序：在册 → 状态可用 → 档位读得到 → 档位够。先报最具体的那一条
    （"这条号不在册"比"档位不够"更能让人立刻改对）。
    """
    index = {str(r.get("stmt_id") or ""): dict(r) for r in statement_rows}
    levels: dict[str, str] = {}
    for row in rows:
        sid = str(row.get("stmt_id") or "")
        anchor = index.get(sid)
        if anchor is None:
            return {"checked": True, "ok": False, "refused": REFUSED_UNKNOWN_SOURCE,
                    "levels": levels,
                    "reason": (f"依赖段第 {row.get('line')} 行点名的 `stmt:{sid}` 不在册"
                               f"（台账里现有 {len(index)} 条命题）⇒ 整笔不写：一条依赖挂在一个"
                               "不存在的号上，读侧会以为这条路通了")}
        status = str(anchor.get("status") or "").strip()
        if status != "active":
            return {"checked": True, "ok": False, "refused": REFUSED_SOURCE_STATUS,
                    "levels": levels,
                    "reason": (f"依赖段第 {row.get('line')} 行点名的 `stmt:{sid}` 不可用："
                               f"statements.status={status or '（空）'!r}，只有 active 才算已收录"
                               f"（这几档都不是依据：{S.STATEMENT_UNUSABLE_STATUSES}）⇒ 整笔不写")}
        level = str(anchor.get("evidence_kind") or "").strip()
        levels[sid] = level
        if not level or level not in S.EVIDENCE_KINDS:
            return {"checked": True, "ok": False, "refused": REFUSED_LEVEL_UNREADABLE,
                    "levels": levels,
                    "reason": (f"依赖段第 {row.get('line')} 行点名的 `stmt:{sid}` 档位读不到"
                               f"（`evidence_kind`={level!r}，不在词表 {S.EVIDENCE_KINDS} 里）"
                               "⇒ 整笔不写：读不到它的档位就不许放行，先确认它现在是哪一档")}
        if not citation_level_allowed(level):
            return {"checked": True, "ok": False, "refused": REFUSED_LEVEL_TOO_LOW,
                    "levels": levels,
                    "reason": (f"被引命题 stmt:{sid} 现在是 {level}，引用要求 "
                               f"{CITATION_MIN_LEVEL} 级及以上 —— 先让它过 V 的逐行走审"
                               "（或等它形式化/穷举到 proof 档），再来引"
                               f"（依赖段第 {row.get('line')} 行）")}
    return {"checked": True, "ok": True, "refused": "", "reason": "", "levels": levels}


def deps_groups(rows: Iterable[Mapping[str, Any]],
                kinds: Mapping[str, str]) -> list[list[dict[str, Any]]]:
    """解析出来的行 ⇒ 秘书那一侧要的二维列表（外层 = 路径组，内层 = 组内每一步）。

    组号 = 路径号（"第几条证明"）：一份证明就是一条可选路径，于是 `used_by` 会落成
    `stmt:<命题号>#pN`，`path_group` 也是 N —— 与多证明模型的两维口径同一个意思
    （组内 AND／组间 OR）。第 1 组不带 `#pN` 尾巴（`proofloc` 的既有口径）。
    """
    groups: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        sid = str(row.get("stmt_id") or "")
        group = int(row.get("path_group") or 1)
        groups.setdefault(group, []).append({
            "stmt_id": sid,
            "kind": str(kinds.get(sid) or "theorem"),
            "label": f"手稿依赖段（第 {row.get('line')} 行）：{row.get('quote')}",
            "quote": str(row.get("quote") or ""),
            "path_group": group,
            # 多证明那一维：`_write_dep_steps` 据此落 `used_by="stmt:<号>#pN"`。
            "proof_no": group,
            # 手稿里点名的步骤（读数用，不参与落库）
            "manuscript_step": str(row.get("step") or ""),
        })
    return [groups[no] for no in sorted(groups)]


# ------------------------------------------------------------------ 三态读数


def deps_missing_reading(*, proof_text: Any, deps_written: int,
                         derived_from: Sequence[str] = (), stmt_id: str = "",
                         proof_no: int = 0, refs: int = 0,
                         section: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """"这一条命题的依赖面建起来没有" ⇒ 三态读数（实现仍是秘书那一份）。

    秘书那份读数的三个状态（`present` / `missing` / `not_applicable`）一个字都不改；
    这里只把"手稿里有没有依赖段 ＋ 正文引了几条"叠上去（`manuscript` 那一格），
    并按业主 2026-10-24 的口径定三档的边界：

    - 正文一条 `stmt:` 引用都没有（不管手稿有没有那一节）⇒ `not_applicable`：
      自足的证明合法，既不拒收、也不记成"缺依赖"（`missing` 只留给"该有而没有"）；
    - 有引用、手稿也有那一节 ⇒ 用秘书那份读数（段里落了边就是 `present`）；
    - 有引用、手稿没有那一节 ⇒ `missing`，`why` 写清"作者没写依赖段"。
      （B 那一侧对这种手稿是整笔受控拒绝 `dependency_section_missing`；这一档读数
      留给只读预览与别的调用方，它说的是同一件事。）
    """
    from .secretary import _deps_missing_reading

    base = dict(_deps_missing_reading(
        proof_text=proof_text, deps_written=deps_written, derived_from=list(derived_from),
        stmt_id=str(stmt_id or ""), proof_no=int(proof_no or 0), scan={"refs": int(refs)}))
    sec = dict(section or {})
    if not sec:
        return base
    base["manuscript"] = {
        "present": bool(sec.get("present")),
        "heading_line": int(sec.get("heading_line") or 0),
        "rows": len(sec.get("rows") or []),
        "problems": len(sec.get("problems") or []),
        "refs_in_proof": int(refs),
    }
    if int(refs) <= 0:
        # 一条在册引用都没有 ⇒ 依赖面这一格不适用（自足证明合法）。
        # 这一档刻意与 `missing` 分开：`missing` 说的是"引了却没记"，不是"没引"。
        base["state"] = "not_applicable"
        base["why"] = ("这一份证明没有引用任何在册命题 ⇒ 依赖面这一格不适用"
                       "（自足的证明合法：既不拒收，也不记成「缺依赖」）；"
                       "一旦正文引用了在册命题，手稿就必须有那一节")
        base["next_step"] = ""
        return base
    if not sec.get("present"):
        base["state"] = "missing"
        base["why"] = (f"手稿里没有 `{SECTION_HEADING}` 这一节，而证明正文里出现了 "
                       f"{refs} 条 `stmt:` 引用 ⇒ 依赖面没有按格式登记（这不是「依赖为零」，"
                       "是「作者没写依赖段」）；B 入库时会整笔拒收 `dependency_section_missing`")
        base["next_step"] = (f"让 F 在证明手稿里补一节 `{SECTION_HEADING}`（四列表，见 "
                             "`agentflow.depsection.COLUMN_KEYS`），再由 B 重新入库")
    return base
