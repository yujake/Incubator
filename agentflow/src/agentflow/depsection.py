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

from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import schema as S


#: 依赖段的段标题（固定，逐字）。
SECTION_HEADING = "## 依赖"

#: F 的证明手稿落点（工作区相对目录，与 `agent_f/manuscript.py` 的 `MANUSCRIPT_DIR` 同一处）。
MANUSCRIPT_DIR = "reports"
#: 按命题号命名的那一种（登记取到号之后的名字）。
MANUSCRIPT_STMT_PREFIX = "f-proof-"
#: 按计划号命名的那一种（立项那一轮还没有命题号时用的是它，也是兜底读盘认的第二个名）。
MANUSCRIPT_PLAN_PREFIX = "f-proof-plan-"

#: 手稿从哪来（四态，进返回值与读数，不许折平）：
#:
#: - `param`：调用方把正文递进来了（这一笔不必读盘）；
#: - `carried_by_D`：D 交研究手稿给 B 入库时把它一并带过来了（`## 携带的证明手稿` 那一节
#:   点名的落点，见 :func:`read_carried_manuscript`）—— 业主 2026-10-26 的原话是
#:   「是通过D传吗」，所以这条链上 D 是携带者、B 是收方，B 自己去盘上撞是兜底而不是主路；
#: - `disk`：前两处都没有，按约定路径在盘上真读到了 F 的稿（历史调用 / 直调的那一档）；
#: - `none`：三处都查过、一处都没有。
SOURCE_PARAM = "param"
SOURCE_CARRIED = "carried_by_D"
SOURCE_DISK = "disk"
SOURCE_NONE = "none"

#: D 的研究报告里那一节的段标题（携带单；逐字固定，渲染与解析共用一个常量）。
CARRIED_HEADING = "## 携带的证明手稿"
#: 携带单的三列（命题号 / 手稿路径 / sha256）。
CARRIED_COLUMNS: tuple[str, ...] = ("命题号（stmt:NNNNNN）", "手稿路径", "sha256")

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


# ------------------------------------------------------------------ 手稿的约定路径与兜底读盘

#: 兜底读盘这一格为什么要存在（真机读数，写在这里而不是写在调用方）：
#:
#: `B.register_statement` 的 `proof_manuscript` 在真机上从来没有人传过值 —— 它是可选参数，
#: 而 B 的提示词只印必填参数（实测 `proof_manuscript` 在 B 的段里出现 0 次），于是
#: "B 读 F 的手稿登记依赖面"这条正路一次都没走过（sylow5/sylow6：`reports/f-proof-*.md`
#: 0 份、会话里 `## 依赖` 0 次、依赖表 0 行）。只改装配（让调用方记得传）不够：那条装配
#: 一旦漏一次，形态是"静默地没有依赖边"，而它长得和"这条证明确实自足"一模一样。
#: 所以这里把"按约定路径去盘上找"做成唯一一个实现，参数空的时候必须走它。


def manuscript_relpath(*, statement_id: str = "", plan_id: str = "") -> str:
    """手稿的约定路径（工作区相对）—— 有命题号按命题号，只有计划号按计划号，都没有返回空串。

    两种名是同一件事的两个时刻：立项那一轮还没有命题号（`f-proof-plan-<plan>.md`），
    登记取到号之后叫 `f-proof-<号>.md`。兜底读盘两种都认（:func:`manuscript_relpaths`），
    于是"登记之前写的稿"与"登记之后写的稿"都能被收方找到。
    """
    sid = str(statement_id or "").strip()
    pid = str(plan_id or "").strip()
    if sid:
        return f"{MANUSCRIPT_DIR}/{MANUSCRIPT_STMT_PREFIX}{sid}.md"
    if pid:
        return f"{MANUSCRIPT_DIR}/{MANUSCRIPT_PLAN_PREFIX}{pid}.md"
    return ""


def manuscript_relpaths(*, statement_ids: Iterable[str] = (), plan_id: str = "") -> list[str]:
    """兜底读盘的候选路径（按优先次序，去重后返回）。

    优先次序就是这个函数存在的理由：按命题号命名的那些排在前（它精确指向"这一条命题的
    证明手稿"），计划号那一个排在最后（它说的是"这个计划的稿"，比命题号宽）。
    一条候选都没有时返回空列表 —— 调用方据此落 `none`，而不是拿空串去拼一个目录名。
    """
    out: list[str] = []
    for sid in statement_ids or ():
        rel = manuscript_relpath(statement_id=str(sid))
        if rel and rel not in out:
            out.append(rel)
    rel = manuscript_relpath(plan_id=str(plan_id or ""))
    if rel and rel not in out:
        out.append(rel)
    return out


def read_manuscript(root: Any, *, statement_ids: Iterable[str] = (),
                    plan_id: str = "") -> dict[str, Any]:
    """按约定路径在盘上找 F 的证明手稿 ⇒ `{checked, source, text, path, tried, why}`。

    三态（与全仓同一条纪律，不许折平）：

    - `checked=False`：压根没查成（没有工作区根）⇒ `source=none` 只是如实说"没读到"，
      `why` 点名缺的是哪一个上下文；
    - `checked=True` + `source=disk`：真读到了一处，`path` 是那一处、`text` 是全文；
    - `checked=True` + `source=none`：约定路径逐条查过，一处都不在盘上，
      `tried` 逐条列出查过哪些路径 —— 于是"我没找"与"找了没有"在读数上分得开。

    读文件本身失败（权限 / 编码）不吞：那一条进 `tried` 的 `why`，继续找下一处；
    全部失败时 `why` 会带上它们，调用方据此知道该修什么。
    """
    root_text = str(root or "").strip()
    if not root_text:
        return {"checked": False, "source": SOURCE_NONE, "text": "", "path": "",
                "tried": [], "why": "没有工作区根（`root` 是空的）⇒ 按约定路径找手稿这一趟没查成"}
    base = Path(root_text)
    tried: list[dict[str, Any]] = []
    for rel in manuscript_relpaths(statement_ids=statement_ids, plan_id=plan_id):
        path = base / rel
        try:
            exists = path.is_file()
        except OSError as exc:  # noqa: BLE001 - 探一次盘都会失败时要说出来，不许当成"不在"
            tried.append({"path": rel, "exists": False,
                          "why": f"探不到（{type(exc).__name__}: {exc}）"})
            continue
        if not exists:
            tried.append({"path": rel, "exists": False, "why": ""})
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:  # noqa: BLE001 - 读失败与"不在盘上"是两件事
            tried.append({"path": rel, "exists": True,
                          "why": f"读不出来（{type(exc).__name__}: {exc}）"})
            continue
        if not text.strip():
            tried.append({"path": rel, "exists": True, "why": "文件在，但正文是空的"})
            continue
        tried.append({"path": rel, "exists": True, "why": ""})
        return {"checked": True, "source": SOURCE_DISK, "text": text, "path": rel,
                "tried": tried, "why": ""}
    checked_paths = [str(t.get("path") or "") for t in tried]
    why = ("按约定路径找过 " + (f"{len(checked_paths)} 处：" + "、".join(checked_paths)
                                if checked_paths else "0 处（没有命题号也没有计划号可定位）")
           + " —— 这几种名一处都不在盘上（或者读不出来，原因逐条见 `tried`）")
    return {"checked": True, "source": SOURCE_NONE, "text": "", "path": "",
            "tried": tried, "why": why}


# ------------------------------------------------------------------ D 携带（走的正是这条主路）

#: D 的研究报告候选名：跨趟那一份手稿，以及 `write_report` 渲染的每问题工作稿。
D_REPORT_NAMES: tuple[str, ...] = ("RESEARCH.md",)
D_WORKING_SUFFIX = "-research.md"
#: 携带单最多列几条（超出只报条数，不静默截断）。
CARRIED_LIMIT = 50


def d_report_paths(root: Any) -> list[str]:
    """D 的研究报告相对路径（跨趟手稿排在前，其余按名字排序）。"""
    base = Path(str(root or ""))
    out: list[str] = []
    d = base / MANUSCRIPT_DIR
    for name in D_REPORT_NAMES:
        if (d / name).is_file():
            out.append(f"{MANUSCRIPT_DIR}/{name}")
    if d.is_dir():
        for p in sorted(d.glob(f"*{D_WORKING_SUFFIX}")):
            rel = f"{MANUSCRIPT_DIR}/{p.name}"
            if rel not in out:
                out.append(rel)
    return out


def carried_manuscripts(report_text: Any) -> dict[str, Any]:
    """读 D 研究报告里"携带给 B 的证明手稿"那一节 ⇒ 三态读数。

    返回 `{checked, present, heading_line, rows, problems, refused, reason}`：
    `rows` 是 `[{statement_id, path, sha256, line}]`（按文件顺序，同号先到先得）；
    `problems` 逐行点名（缺列 / 命题号形状不对 / 路径为空），`refused` 非空时调用方
    不许把这一节读成"携带单是空的"—— 读不懂与没有是两件事。
    """
    body, heading_line = section_lines(report_text, CARRIED_HEADING)
    out: dict[str, Any] = {"checked": True, "present": bool(heading_line),
                           "heading_line": heading_line, "rows": [], "problems": [],
                           "refused": "", "reason": ""}
    if not heading_line:
        return out
    table = [(ln, raw) for ln, raw in body if raw.strip().startswith("|")]
    seen: set[str] = set()
    for line_no, raw in table:
        cells = _cells(raw)
        if _is_separator(cells):
            continue
        if cells and cells[0].lower().startswith("---"):
            continue
        if len(cells) != len(CARRIED_COLUMNS):
            # 表头那一行（三列的名字）在三列表里也是三格 ⇒ 用"第一格是不是命题号"区分
            if all(not c.startswith("stmt:") and not S.is_valid_id(c) for c in cells):
                continue
            out["problems"].append({
                "line": line_no,
                "why": (f"这一行读出来 {len(cells)} 列，应有 {len(CARRIED_COLUMNS)} 列"
                        f"（{' / '.join(CARRIED_COLUMNS)}）")})
            continue
        raw_id, raw_path, raw_sha = (c.strip().strip("`").strip() for c in cells)
        if not raw_id.startswith("stmt:"):
            # 表头那一行（"命题号（stmt:NNNNNN）"）不算坏行：它第一格不以上面的前缀开头
            if raw_id.startswith("命题号") or not raw_id:
                continue
            out["problems"].append({"line": line_no,
                                    "why": f"命题号那一格要是 `stmt:NNNNNN`（收到 {raw_id!r}）"})
            continue
        sid = raw_id[len("stmt:"):].strip()
        if not S.is_valid_id(sid):
            out["problems"].append({"line": line_no,
                                    "why": f"命题号的号不是 {S.ID_DIGITS} 位十进制（收到 {sid!r}）"})
            continue
        if not raw_path:
            out["problems"].append({"line": line_no, "why": "手稿路径那一格是空的"})
            continue
        if sid in seen:
            continue
        seen.add(sid)
        out["rows"].append({"statement_id": sid, "path": raw_path,
                            "sha256": raw_sha.lower(), "line": line_no})
    if out["problems"]:
        first = out["problems"][0]
        out["refused"] = REFUSED_SECTION
        out["reason"] = (f"D 报告的携带单读不懂（`{CARRIED_HEADING}`，第 {first['line']} 行起）："
                         + "；".join(f"第 {p['line']} 行——{p['why']}" for p in out["problems"]))
    return out


def render_carried_section(rows: Iterable[Mapping[str, Any]],
                           *, note: str = "") -> str:
    """把携带行渲染成那一节（D 侧写、B 侧读；渲染与解析共用 `CARRIED_HEADING` 与列名）。"""
    lines = [CARRIED_HEADING, "",
             "D 交研究手稿给 B 入库时把 F 的证明手稿一并带过来（「是通过D传吗」）：",
             "下表每一行是 `命题号 → 手稿路径 → 那份文件字节的 sha256`，B 读稿登记依赖面。",
             ""]
    lines.append("| " + " | ".join(CARRIED_COLUMNS) + " |")
    lines.append("|" + "|".join("---" for _ in CARRIED_COLUMNS) + "|")
    count = 0
    for row in rows:
        sid = str(row.get("statement_id") or "")
        lines.append(f"| stmt:{sid} | {row.get('path')} | {row.get('sha256') or ''} |")
        count += 1
    if not count:
        lines.append("")
        lines.append("（这一趟没有可携带的 F 证明手稿：不是省略，是确实没有 —— 盘上没有"
                     "任何一条按命号命名的 `reports/f-proof-<命题号>.md`。）")
    if str(note or "").strip():
        lines.append("")
        lines.append(str(note).strip())
    return "\n".join(lines) + "\n"


def read_carried_manuscript(root: Any, *, statement_ids: Iterable[Any] = ()) -> dict[str, Any]:
    """在 D 的报告里找"这一条命题的证明手稿"，找到就把正文读回来。

    返回 `{checked, source, text, path, sha256, carried_by, tried, why}`：
    `source=carried_by_D` 只在"携带单里有这个号、文件读得到、sha256 相符（给了就核）"时成立；
    任何一处不成立都落到 `none` 并把原因写进 `tried` / `why` —— 静默用一份对不上的稿
    比读不到更坏（依赖边会挂到别人的论证上）。

    为什么这是主路而不是兜底：业主 2026-10-26 的原话是「是通过D传吗」——
    携带者 D、收方 B；B 自己按约定路径撞见一份稿（`disk`）只算历史调用 / 直调那一档。
    """
    import hashlib

    root_text = str(root or "").strip()
    out: dict[str, Any] = {"checked": False, "source": SOURCE_NONE, "text": "", "path": "",
                           "sha256": "", "carried_by": "", "tried": [], "why": ""}
    if not root_text:
        out["why"] = "没有工作区根（`root` 是空的）⇒ 读 D 报告里那张携带单这一趟没查成"
        return out
    base = Path(root_text)
    tried: list[dict[str, Any]] = out["tried"]
    index: dict[str, dict[str, Any]] = {}
    for rel in d_report_paths(root_text):
        try:
            text = (base / rel).read_text(encoding="utf-8")
        except OSError as exc:  # noqa: BLE001 - 读不出报告要说出来（它可能就是带稿的那一份）
            tried.append({"report": rel, "why": f"读不出来（{type(exc).__name__}: {exc}）"})
            continue
        got = carried_manuscripts(text)
        tried.append({"report": rel, "present": bool(got.get("present")),
                      "rows": len(got.get("rows") or []),
                      "problems": len(got.get("problems") or [])})
        for row in got.get("rows") or []:
            index.setdefault(str(row["statement_id"]), {**row, "report": rel})
    out["checked"] = True
    for raw in statement_ids or ():
        sid = str(raw or "").strip().split("#", 1)[0].split(":", 1)[-1].strip()
        if not sid:
            continue
        hit = index.get(sid)
        if hit is None:
            continue
        rel = str(hit.get("path") or "")
        raw_target = Path(rel)
        if raw_target.is_absolute() or ".." in raw_target.parts:
            tried.append({"statement_id": sid, "path": rel,
                          "why": "携带单里的路径越出工作区（绝对路径或含 ..）⇒ 不读"})
            continue
        target = base / raw_target
        if not target.is_file():
            tried.append({"statement_id": sid, "path": rel, "why": "携带单点名的文件不在盘上"})
            continue
        try:
            blob = target.read_bytes()
        except OSError as exc:  # noqa: BLE001 - 读失败与"不在"分得开
            tried.append({"statement_id": sid, "path": rel,
                          "why": f"读不出来（{type(exc).__name__}: {exc}）"})
            continue
        sha = hashlib.sha256(blob).hexdigest()
        want = str(hit.get("sha256") or "")
        if want and want != sha:
            tried.append({"statement_id": sid, "path": rel,
                          "why": (f"sha256 对不上（携带单写 {want[:12]}…，盘上是 {sha[:12]}…）"
                                  "⇒ 这份稿不是 D 交的那一版，不拿它登记")})
            continue
        text = blob.decode("utf-8", errors="replace")
        if not text.strip():
            tried.append({"statement_id": sid, "path": rel, "why": "文件在，但正文是空的"})
            continue
        return {"checked": True, "source": SOURCE_CARRIED, "text": text, "path": rel,
                "sha256": sha, "carried_by": str(hit.get("report") or ""),
                "tried": tried, "why": ""}
    if not index:
        out["why"] = ("D 的报告里没有「携带的证明手稿」那一节（或那一节是空的）"
                      + ("；查过：" + "、".join(str(t.get("report") or "") for t in tried)
                         if tried else "；工作区里连一份 D 报告都没有"))
    else:
        out["why"] = (f"D 的携带单里有 {len(index)} 条手稿，没有一条对得上这一笔的命题号"
                      f"{[str(x) for x in statement_ids][:4]}")
    return out


def candidate_statement_ids(*, derived_from: Iterable[Any] = (), proof_text: Any = "",
                            extra: Iterable[Any] = ()) -> list[str]:
    """收方"这一份手稿可能挂在哪些命题号下"⇒ 候选号（裸号，按出现次序去重）。

    - `derived_from`：B 交上来的承重链（自己的或外部的上下文命题）；
    - 证明正文里的 `stmt:` 引用（`stmt_refs` 是全仓唯一那条扫描，这里不另写一份）；
    - `extra`：调用方手上多出来的号（例如 D 的手稿点名了 F 的那一条）。

    只要形状是合法号（`schema.is_valid_id`）就收：这一层判的是"去盘上找哪几个名字"，
    "那个号在不在册"不是它的判据（盘上找得到稿、而号不在册，是另一件事，
    由引用档位门与 `derived_from` 那几处各自点名）。
    """
    out: list[str] = []

    def _take(raw: Any) -> None:
        sid = str(raw or "").strip().split("#", 1)[0].split(":", 1)[-1].strip()
        if sid and S.is_valid_id(sid) and sid not in out:
            out.append(sid)

    for raw in derived_from or ():
        _take(raw)
    for raw in stmt_refs(proof_text):
        _take(raw)
    for raw in extra or ():
        _take(raw)
    return out



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
