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

#: `proof_text` 的来源（与上面那一组分开的一格读数，2026-11-02）。
#:
#: 上面那四个说的是"这份稿从哪来"，这一个说的是"落进 `proof_text` 的正文是不是
#: 那份稿"。业主 2026-11-02 的口径是「F 侧实际上是 D 侧，F 的东西都在 D 的手稿上记了一笔」：
#: 主路是 B 按 D 的携带单寻址 → 取到稿正文 → 落成 `proof_text`（:data:`SOURCE_MANUSCRIPT`）。
#: `param` = 调用方直递的正文（它优先）；空串 = 这一笔没有正文要写。
SOURCE_MANUSCRIPT = "manuscript"

#: 二次寻址的三种形态（2026-11-02 业主：二次寻址必须是确定性工具，不许消耗 LLM 的 token）。
#:
#: | 值 | 什么时候 |
#: |---|---|
#: | `auto` | 由本模块的纯函数寻址（`read_carried_manuscript` / `read_manuscript`），零模型调用 |
#: | `model` | 寻址这一步被模型参与过（本仓的结构里不该出现；出现了要能读出来） |
#: | `unknown` | 这一趟没有寻址 / 没查成（不许折成「auto」） |
ADDRESS_MODES: tuple[str, ...] = ("auto", "model", "unknown")

#: 携带单点了名、而那个地址读不到 ⇒ 受控拒绝（2026-11-02 业主）。
#:
#: 为什么它必须是拒绝而不是"降级去盘上自己找"：D 的清单是 B 的唯一寻址依据
#: （业主：「B侧需寻址获得F侧证明及V签」）。清单点名却读不到，说明清单与盘不一致
#: —— 那时换一条自己找的路，就是把"照单收录"换成了"猜一份稿"。
REFUSED_ADDRESS = "manuscript_address_unreadable"

#: D 的研究报告里那一节的段标题（携带单；逐字固定，渲染与解析共用一个常量）。
CARRIED_HEADING = "## 携带的证明手稿"
#: 携带单的列（命题号 / 手稿路径 / sha256 / 证明号）。
#: 携带单第一格认两种键（2026-11-04，业主：「E 的穷举论证和 V 签也是委托入库」）:
#: `stmt:<命题号>`（F 的证明手稿，命题已在册）与 `exp:<实验号>`（E 的穷举证明手稿，
#: 命题可能还没进台账 —— 那条链里 E 从来没有命题号可用）。
#:
#: 为什么不是另开一张单：携带机制本来就只做三件事（键 → 地址 → 文件 sha256），
#: E 那一份与 F 那一份在这三件事上完全同形；差别只在"键是什么"。
#: 第二格是地址，读侧按它到盘上取文件并核 sha（`read_carried_manuscript`）。
#:
#: 第四格 `proof_no`（2026-11-04，缺口 ①）：这一份是这条命题的第几份证明。
#: 改前交付里没有这一格，于是"一命题多证明"时只能靠 B 猜（canonical 空则 #p1 /
#: 否则最大号 + 1）。老行只有三格 ⇒ 读成 `#p1`（老数据的读数与改前逐字不变）；
#: 第四格留空同样读成 `#p1` —— "没写"与"写了 1"在证明号上是同一件事。
CARRIED_COLUMNS: tuple[str, ...] = ("命题号（stmt:NNNNNN / exp:NNNNNN）", "手稿路径",
                                    "sha256", "证明号（#pN，可空）")

#: 携带单的最少列数（第四列 `proof_no` 是新增的可省略列：老行三列照读）。
CARRIED_MIN_COLUMNS = 3

#: 携带单第一格的前缀（`stmt:` 是命题号、`exp:` 是 E 的实验号）。
CARRIED_KEYS: tuple[str, ...] = ("stmt:", "exp:")

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
#: 兜底审计（2026-10-27）：盘上那份 `reports/f-proof-*.md` 缺洗稿元信息 ⇒
#: 它不是框架渲染的产物（手写 / 换名绕过），整笔拒绝，请 F 用 `proof` 动作重写。
REFUSED_NOT_WASHED = "manuscript_not_washed"


def is_framework_manuscript(rel: Any) -> bool:
    """`rel` 是不是 `depsection` 这套约定下的 F 证明手稿路径（`reports/f-proof-*.md`）。

    判据只用一处定义（前缀与目录名都从本模块的常量读）：调用方拿它区分
    "这是我约定的那份稿"与"别的文件" —— 兜底审计只在它是的那一档上生效。
    空串 / 非 `.md` / 不在 `reports/` 下 / 名字不带前缀 ⇒ False（宁可不动手）。
    """
    parts = [p for p in str(rel or "").replace("\\", "/").split("/") if p not in ("", ".")]
    if len(parts) < 2 or parts[0].casefold() != MANUSCRIPT_DIR.casefold():
        return False
    name = parts[-1]
    return (name.casefold().endswith(".md")
            and name.casefold().startswith(MANUSCRIPT_STMT_PREFIX.casefold()))


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
    #: 逐行解析用的列序。表头认得全就照表头取列（上面 `COLUMN_KEYS` 说的
    #: 「顺序不限」只有在这里真的按表头解析时才是事实；此前 `found` 只进了
    #: 出参 `column_index`，正文一律按位置读 —— 表头换个顺序，`step` 与
    #: `path_group` 就静默互换，`problems` 一条都不报，读出两个依赖面）。
    #: 表头认不全时退回位置序：缺列/列数不对已经在上面报过，那一档照旧整笔拒。
    parse_order: list[int] = list(range(len(COLUMN_KEYS)))
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
        if len(found) == len(COLUMN_KEYS):
            parse_order = [found[field] for field, _k, _n in COLUMN_KEYS]
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
            src = parse_order[idx]
            value = (cells[src] if src < len(cells) else "").strip().strip("`").strip()
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

    2026-11-04（业主裁定，F/B 两族形式统一）：拼接与解析本体收在
    `manuscriptform.name_reading`（内部只走 `vsigns.parse_manuscript_name`）。这里
    只留一个薄转发 —— 低层常量仍由本模块持有，命名规则不许有两个落点。
    """
    from . import manuscriptform as _MF

    got = _MF.name_reading(_MF.FAMILY_F, statement_id=statement_id, plan_id=plan_id)
    return str(got.get("path") or "") if got.get("ok") else ""


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


#: 兜底读盘两种认法（进 `read_manuscript` 的读数 `matched_by`，三态里的"怎么命中的"）。
MATCH_BY_PATH = "path"
MATCH_BY_PROOF_BODY = "proof_body"


def _proof_body_key(text: Any) -> str:
    """一份稿 / 一段正文的"证明正文指纹"：`## 证明` 那一节逐行去首尾空白、丢空行。

    为什么是逐行归一而不是逐字：手稿是渲染出来的（`agent_f/manuscript.py` 按步拼行），
    而 B 收下来的 `proof_text` 可能多/少一个尾随空行 —— 那是排版，不是另一份证明。
    反过来，改一个字指纹就变（判据里有负控）⇒ 它比"文件名"精确、比"正文包含"严格。

    洗稿元信息那一行（`WASH_MARK`）不算证明内容，指纹里剔掉：`mark_washed` 在
    "没有 `- 计划：` 那一行"的稿子上会把它插到第 2 行之后 —— 那种形状下它会落进
    `## 证明` 那一节，留着就会让"同一份证明"读成"不同"（真机手稿有页头，不会撞到；
    但判据夹具与手写稿会）。
    """
    body = str(proof_body(text) or "").replace("\r\n", "\n")
    return "\n".join(line.strip() for line in body.split("\n")
                     if line.strip() and not line.strip().startswith(WASH_MARK))


def _plan_named_manuscripts(base: Path) -> list[str]:
    """`reports/f-proof-plan-*.md` 的候选（工作区相对、按名字排序）。

    为什么按名字排序而不是按 mtime：这个兜底要用"内容"认，不用"新旧"认 ——
    计划号那一份稿每一轮都会被覆盖（87 的 plan-000001 改写 3 次），按 mtime 取最新
    会把上一轮的证明当成这一轮的。排序只为了让同一批候选的顺序可复现。
    """
    directory = base / MANUSCRIPT_DIR
    try:
        if not directory.is_dir():
            return []
        names = sorted(p.name for p in directory.glob(f"{MANUSCRIPT_PLAN_PREFIX}*.md"))
    except OSError:  # noqa: BLE001 —— 探不到目录要能如实说，不许当成"没有候选"
        return []
    return [f"{MANUSCRIPT_DIR}/{name}" for name in names]


def read_manuscript(root: Any, *, statement_ids: Iterable[str] = (),
                    plan_id: str = "", proof_text: Any = "") -> dict[str, Any]:
    """按约定路径（必要时按证明正文）在盘上找 F 的证明手稿。

    返回 `{checked, source, text, path, tried, why, matched_by}`。

    ## 两段认法（第二段 2026-11-04 补：业主批的那一条）

    ① 按名字（`manuscript_relpaths`）：`reports/f-proof-<命题号>.md` 优先，
       其次 `reports/f-proof-plan-<计划号>.md`；命中 ⇒ `matched_by="path"`。
    ② 按内容（`proof_text` 非空、且第 ① 段一个都没命中时）：扫
       `reports/f-proof-plan-*.md`，把每一份的 `## 证明` 那一节与这一笔的 `proof_text`
       逐行归一后比 —— 相同才认，命中 ⇒ `matched_by="proof_body"`。

    ## 为什么必须补第 ② 段（真机读数，ramsey-4-4-87）
    F 的稿在拿到命题号之前叫 `f-proof-plan-<计划号>.md`，而"登记成功之后改名成
    `f-proof-<命题号>.md`"只发生在 F 自己的 outlet 登记成功那一笔（`publish_manuscript`）。
    87 里六份稿全叫 plan 名、按号命名的 0 份（outlet 因"没有覆盖正文的 V 签"整笔拒），
    于是 B 的兜底读盘永远只查 `f-proof-<号>.md` ⇒ 读到 0 份 ⇒ 依赖面 0 行。第 ② 段补的
    就是"盘上那份稿还在、只是叫计划名"这一档。

    ## 为什么它只补一半（这一条必须写在读数旁边，不许被读成"补了就好"）
    内容认法的前提是"盘上那一份还是登记时那一份"。计划号那份稿会被后续轮次覆盖
    （87 实测：六份里三份的正文与登记进台账的 `proof_text` 已经不是同一份）——
    那一档必须继续受控拒绝（`source=none` ⇒ 有在册引用时 B 整笔拒
    `dependency_section_missing`），不许按 glob 取最新去猜一份。真机读数：
    87 的六份稿里第 ② 段认得出 3 份（000000→stmt:000001、000002→stmt:000003、
    000003→stmt:000007），另外 3 份正是"被后续轮次覆盖"的那一半。

    ## 本函数不产出证明号（别与携带单第四列混成一个）
    `#pN` 只有两个来路：调用方给的 `proof_no`、D 携带单第四列（`CARRIED_COLUMNS`）。
    内容命中的是一份正文，不是"第几条证明" —— 这里不猜号、也不回填号；读数只用
    `matched_by` 说"是靠名字还是靠正文命中的"（`tried` 逐条也带这一格）。

    三态（与全仓同一条纪律，不许折平）：

    - `checked=False`：压根没查成（没有工作区根）⇒ `source=none` 只是如实说"没读到"，
      `why` 点名缺的是哪一个上下文；
    - `checked=True` + `source=disk`：真读到了一处，`path` 是那一处、`text` 是全文；
    - `checked=True` + `source=none`：约定路径逐条查过、内容也认过，一处都不对，
      `tried` 逐条列出查过哪些路径 / 比过哪些正文 —— 于是"我没找"与"找了没有"分得开。

    读文件本身失败（权限 / 编码）不吞：那一条进 `tried` 的 `why`，继续找下一处；
    全部失败时 `why` 会带上它们，调用方据此知道该修什么。
    """
    root_text = str(root or "").strip()
    if not root_text:
        return {"checked": False, "source": SOURCE_NONE, "text": "", "path": "",
                "tried": [], "matched_by": "",
                "why": "没有工作区根（`root` 是空的）⇒ 按约定路径找手稿这一趟没查成"}
    base = Path(root_text)
    tried: list[dict[str, Any]] = []
    for rel in manuscript_relpaths(statement_ids=statement_ids, plan_id=plan_id):
        path = base / rel
        try:
            exists = path.is_file()
        except OSError as exc:  # noqa: BLE001 - 探一次盘都会失败时要说出来，不许当成"不在"
            tried.append({"path": rel, "exists": False, "matched_by": MATCH_BY_PATH,
                          "why": f"探不到（{type(exc).__name__}: {exc}）"})
            continue
        if not exists:
            tried.append({"path": rel, "exists": False, "matched_by": MATCH_BY_PATH, "why": ""})
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:  # noqa: BLE001 - 读失败与"不在盘上"是两件事
            tried.append({"path": rel, "exists": True, "matched_by": MATCH_BY_PATH,
                          "why": f"读不出来（{type(exc).__name__}: {exc}）"})
            continue
        if not text.strip():
            tried.append({"path": rel, "exists": True, "matched_by": MATCH_BY_PATH,
                          "why": "文件在，但正文是空的"})
            continue
        tried.append({"path": rel, "exists": True, "matched_by": MATCH_BY_PATH, "why": ""})
        return {"checked": True, "source": SOURCE_DISK, "text": text, "path": rel,
                "tried": tried, "matched_by": MATCH_BY_PATH, "why": ""}
    # ---- 第 ② 段：按证明正文认（只在第 ① 段全 miss、且调用方给了正文时） -------------
    want = _proof_body_key(proof_text) if str(proof_text or "").strip() else ""
    compared = 0
    if want:
        for rel in _plan_named_manuscripts(base):
            path = base / rel
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:  # noqa: BLE001 —— 读不出来要如实说，继续比下一份
                tried.append({"path": rel, "exists": True, "matched_by": MATCH_BY_PROOF_BODY,
                              "why": f"读不出来（{type(exc).__name__}: {exc}）"})
                continue
            compared += 1
            if _proof_body_key(text) == want:
                tried.append({"path": rel, "exists": True, "matched_by": MATCH_BY_PROOF_BODY,
                              "why": "`## 证明` 与这一笔的 proof_text 逐行相同"})
                return {
                    "checked": True, "source": SOURCE_DISK, "text": text, "path": rel,
                    "tried": tried, "matched_by": MATCH_BY_PROOF_BODY,
                    "why": (f"按名字没找到；按证明正文认出了 {rel}"
                            f"（比过 {compared} 份计划名手稿）")}
            tried.append({"path": rel, "exists": True, "matched_by": MATCH_BY_PROOF_BODY,
                          "why": "`## 证明` 与这一笔的 proof_text 不同（不是这一份）"})
    checked_paths = [str(t.get("path") or "") for t in tried]
    why = ("按约定路径找过 " + (f"{len(checked_paths)} 处：" + "、".join(checked_paths)
                                if checked_paths else "0 处（没有命题号也没有计划号可定位）")
           + " —— 这几种名一处都不在盘上（或者读不出来，原因逐条见 `tried`）")
    if want:
        why += (f"；又按证明正文比过 {compared} 份 `{MANUSCRIPT_DIR}/{MANUSCRIPT_PLAN_PREFIX}"
                "*.md`，没有一份与这一笔的 proof_text 相同"
                "（那一半只能等 F 在登记成功后把稿改名成按命题号的那一份）")
    return {"checked": True, "source": SOURCE_NONE, "text": "", "path": "",
            "tried": tried, "matched_by": "", "why": why}


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
        if len(cells) not in (CARRIED_MIN_COLUMNS, len(CARRIED_COLUMNS)):
            # 表头那一行（列名的名字）在两种列数里也对不上 ⇒ 用"第一格是不是命题号"区分
            if all(not c.startswith("stmt:") and not S.is_valid_id(c) for c in cells):
                continue
            out["problems"].append({
                "line": line_no,
                "why": (f"这一行读出来 {len(cells)} 列，应有 {CARRIED_MIN_COLUMNS} 或 "
                        f"{len(CARRIED_COLUMNS)} 列（{' / '.join(CARRIED_COLUMNS)}；"
                        "老行没有第四列 ⇒ 证明号读成 #p1）")})
            continue
        raw_id, raw_path, raw_sha = (c.strip().strip("`").strip() for c in cells[:3])
        raw_no = cells[3].strip().strip("`").strip() if len(cells) > 3 else ""
        if not any(raw_id.startswith(p) for p in CARRIED_KEYS):
            # 表头那一行（"命题号（stmt:NNNNNN ...）"）不算坏行：它第一格不以上面的前缀开头
            if raw_id.startswith("命题号") or not raw_id:
                continue
            out["problems"].append({"line": line_no,
                                    "why": ("命题号那一格要是 `stmt:NNNNNN` 或 "
                                            f"`exp:NNNNNN`（收到 {raw_id!r}）")})
            continue
        proof_no = 1
        if raw_no:
            # 第四格写了但认不出 ⇒ 整节读不懂（不许静默折成 #p1：那正是"号给错了"的形态）
            try:
                proof_no = int(raw_no) if not raw_no.startswith("#") else int(raw_no[2:])
            except (TypeError, ValueError):
                proof_no = 0
            if proof_no < 1:
                out["problems"].append({
                    "line": line_no,
                    "why": (f"证明号那一格要是 >= 1 的整数（可写 `2` / `#p2`；收到 "
                            f"{raw_no!r}）—— 留空才是 #p1")})
                continue
        key = next(p for p in CARRIED_KEYS if raw_id.startswith(p))
        sid = raw_id[len(key):].strip()
        if not S.is_valid_id(sid):
            out["problems"].append({"line": line_no,
                                    "why": f"命题号的号不是 {S.ID_DIGITS} 位十进制（收到 {sid!r}）"})
            continue
        if not raw_path:
            out["problems"].append({"line": line_no, "why": "手稿路径那一格是空的"})
            continue
        # 键的身份决定这一行是谁的稿：`stmt:` ⇒ 命题行（F 的稿）；`exp:` ⇒ E 的实验
        # （那条链里命题可能还没进台账，没有命题号可写）。两档落同一个 `rows` 结构，
        # 只是 `statement_id` 与 `experiment_id` 各有一格是空的。
        row_key = f"{key}{sid}"
        if row_key in seen:
            continue
        seen.add(row_key)
        out["rows"].append({"statement_id": sid if key == "stmt:" else "",
                            "experiment_id": sid if key == "exp:" else "",
                            "key": row_key,
                            "path": raw_path,
                            "sha256": raw_sha.lower(),
                            #: 这一份是第几份证明（第四格；老行 / 空格 ⇒ #p1）。
                            "proof_no": int(proof_no),
                            "line": line_no})
    if out["problems"]:
        first = out["problems"][0]
        out["refused"] = REFUSED_SECTION
        out["reason"] = (f"D 报告的携带单读不懂（`{CARRIED_HEADING}`，第 {first['line']} 行起）："
                         + "；".join(f"第 {p['line']} 行——{p['why']}" for p in out["problems"]))
    return out


def render_carried_section(rows: Iterable[Mapping[str, Any]],
                           *, note: str = "") -> str:
    """把携带行渲染成那一节（D 侧写、B 侧读；渲染与解析共用 `CARRIED_HEADING` 与列名）。

    `rows` 的每一行用 `statement_id`（F 的稿，`stmt:`）或 `experiment_id`（E 的稿，
    `exp:`）其中之一做键；两者都给时以命题号为准（命题已在册时它更精确）。
    """
    lines = [CARRIED_HEADING, "",
             "D 交研究手稿给 B 入库时把证明手稿一并带过来（「是通过D传吗」）：",
             "下表每一行是 `命题号 → 手稿路径 → 那份文件字节的 sha256 → 第几份证明`，",
             "B 读稿登记依赖面。第四列留空 ⇒ 第 1 份（老行没有这一列，读数相同）。",
             "E 的穷举证明手稿用 `exp:<实验号>` 做键：那条链里命题可能还没进台账。",
             ""]
    lines.append("| " + " | ".join(CARRIED_COLUMNS) + " |")
    lines.append("|" + "|".join("---" for _ in CARRIED_COLUMNS) + "|")
    count = 0
    for row in rows:
        sid = str(row.get("statement_id") or "")
        eid = str(row.get("experiment_id") or "")
        if sid:
            key = f"stmt:{sid}"
        elif eid:
            key = f"exp:{eid}"
        else:
            continue
        no = str(row.get("proof_no") or "").strip()
        lines.append(f"| {key} | {row.get('path')} | {row.get('sha256') or ''} | {no} |")
        count += 1
    if not count:
        lines.append("")
        lines.append("（这一趟没有可携带的证明手稿：不是省略，是确实没有 —— 盘上没有"
                     "任何一条按命号命名的 `reports/f-proof-<命题号>.md`，也没有一份"
                     "已签的 `reports/e-proof-<实验号>.md`。）")
    if str(note or "").strip():
        lines.append("")
        lines.append(str(note).strip())
    return "\n".join(lines) + "\n"


def _carried_target(base: Path, hit: Mapping[str, Any],
                    tried: list[dict[str, Any]]) -> tuple[str, str]:
    """按携带单的一行到盘上去读那份 F 稿 ⇒ `(text, 文件 sha256)`。

    读不到就回 `("", "")`，并把原因追加进 `tried`（不在这一层抛、也不静默）。
    判据三条：路径不许越出工作区 / 文件要在盘上 / 携带单给了 sha256 就必须相符。
    """
    import hashlib

    rel = str(hit.get("path") or "")
    raw_target = Path(rel)
    if raw_target.is_absolute() or ".." in raw_target.parts:
        tried.append({"statement_id": hit.get("statement_id"), "path": rel,
                      "why": "携带单里的路径越出工作区（绝对路径或含 ..）⇒ 不读"})
        return "", ""
    target = base / raw_target
    if not target.is_file():
        tried.append({"statement_id": hit.get("statement_id"), "path": rel,
                      "why": "携带单点名的文件不在盘上"})
        return "", ""
    try:
        blob = target.read_bytes()
    except OSError as exc:  # noqa: BLE001 - 读失败与"不在"分得开
        tried.append({"statement_id": hit.get("statement_id"), "path": rel,
                      "why": f"读不出来（{type(exc).__name__}: {exc}）"})
        return "", ""
    sha = hashlib.sha256(blob).hexdigest()
    want = str(hit.get("sha256") or "")
    if want and want != sha:
        tried.append({"statement_id": hit.get("statement_id"), "path": rel,
                      "why": (f"sha256 对不上（携带单写 {want[:12]}…，盘上是 {sha[:12]}…）"
                              "⇒ 这份稿不是 D 交的那一版，不拿它登记")})
        return "", ""
    text = blob.decode("utf-8", errors="replace")
    if not text.strip():
        tried.append({"statement_id": hit.get("statement_id"), "path": rel,
                      "why": "文件在，但正文是空的"})
        return "", ""
    return text, sha


def read_carried_manuscript(root: Any, *, statement_ids: Iterable[Any] = (),
                            proof_text: Any = "") -> dict[str, Any]:
    """在 D 的报告里找"这一条命题的证明手稿"，找到就把正文读回来（纯读，零模型调用）。

    返回 `{checked, source, text, path, sha256, carried_by, tried, why, named, address,
    item, list_report, list_line, list_sha256, matched_by}`。

    ## 怎么认这一笔（两条路，都在清单里找，绝不自己到盘上猜）
    1. 按候选命题号（`statement_ids`）命中清单里的那一行；
    2. 号对不上时（首次登记还没有号、`proof_manuscript` 也没给），按正文命中：
       逐行按地址去读那份 F 稿，谁的「## 证明」正文 sha 等于 `proof_text` 的 sha 就是它。
       2026-11-02 业主：「B侧需寻址获得F侧证明及V签」—— 号还不知道时，正文是清单里
       唯一能对上的东西；这一步仍是清单内寻址，不是"按约定路径撞见一份稿"。

    `source=carried_by_D` 只在"清单里有这一条、文件读得到、sha256 相符（给了就核）"时成立；
    任何一处不成立都落到 `none` 并把原因写进 `tried` / `why` —— 静默用一份对不上的稿
    比读不到更坏（依赖边会挂到别人的论证上）。

    ## `named`（2026-11-02）
    `named=True` 表示"清单点了这一笔的名"（按号或按正文命中了那一行）：即便地址读不到，
    调用方也必须受控拒绝而不是降级去盘上自己找（`depsection.REFUSED_ADDRESS`）。
    `address` / `item` / `list_report` / `list_line` / `list_sha256` 五格是"按哪条清单、
    第几项、什么地址"的读数。
    """
    import hashlib

    root_text = str(root or "").strip()
    out: dict[str, Any] = {"checked": False, "source": SOURCE_NONE, "text": "", "path": "",
                           "sha256": "", "carried_by": "", "tried": [], "why": "",
                           "named": False, "address": "", "item": 0,
                           "list_report": "", "list_line": 0, "list_sha256": "",
                           "proof_no": 0, "matched_by": ""}
    if not root_text:
        out["why"] = "没有工作区根（`root` 是空的）⇒ 读 D 报告里那张携带单这一趟没查成"
        return out
    base = Path(root_text)
    tried: list[dict[str, Any]] = out["tried"]
    index: dict[str, dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []
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
        for i, row in enumerate(got.get("rows") or [], 1):
            one = {**row, "report": rel, "item": i}
            candidates.append(one)
            index.setdefault(str(row["statement_id"]), one)
    out["checked"] = True

    def _hit(one: Mapping[str, Any], *, matched_by: str) -> dict[str, Any]:
        """把清单里的这一行写进读数（按号命中 / 按正文命中共用一处）。"""
        out.update(named=True, address=str(one.get("path") or ""),
                   item=int(one.get("item") or 0),
                   list_report=str(one.get("report") or ""),
                   list_line=int(one.get("line") or 0),
                   list_sha256=str(one.get("sha256") or ""),
                   #: 携带单第四列（这一份是第几份证明；老行 / 空格 ⇒ #p1）。
                   proof_no=int(one.get("proof_no") or 1),
                   matched_by=matched_by)
        return out

    for raw in statement_ids or ():
        sid = str(raw or "").strip().split("#", 1)[0].split(":", 1)[-1].strip()
        if not sid:
            continue
        hit = index.get(sid)
        if hit is None:
            continue
        text, sha = _carried_target(base, hit, tried)
        _hit(hit, matched_by="statement_id")
        if not text:
            continue
        return {**out, "source": SOURCE_CARRIED, "text": text,
                "path": str(hit.get("path") or ""), "sha256": sha,
                "carried_by": str(hit.get("report") or ""), "why": ""}
    # ---- 2026-11-02：号还不知道时按正文命中（仍在清单内寻址）----
    want = (hashlib.sha256(str(proof_text or "").encode("utf-8")).hexdigest()
            if str(proof_text or "").strip() else "")
    unreadable: list[dict[str, Any]] = []
    if want and candidates:
        for hit in candidates:
            text, sha = _carried_target(base, hit, tried)
            if not text:
                unreadable.append(dict(hit))
                continue
            body = proof_body(text).strip("\n")
            got = hashlib.sha256(body.encode("utf-8")).hexdigest()
            if got != want:
                tried.append({"statement_id": hit.get("statement_id"),
                              "path": hit.get("path"),
                              "why": ("清单里这一份的「## 证明」正文 sha 与这一笔登记的不是"
                                      "同一份 ⇒ 不是它")})
                continue
            _hit(hit, matched_by="proof_sha")
            return {**out, "source": SOURCE_CARRIED, "text": text,
                    "path": str(hit.get("path") or ""), "sha256": sha,
                    "carried_by": str(hit.get("report") or ""), "why": ""}
        if len(unreadable) == len(candidates):
            # 清单里的每一条地址都读不到 ⇒ 这不是"清单里没有这一笔"，是"按清单寻址失败"。
            # 调用方必须受控拒绝（`REFUSED_ADDRESS`），不许降级去盘上自己找一份。
            first = unreadable[0]
            _hit(first, matched_by="")
            out["why"] = ("D 的携带单点了名，而清单里的地址一条都读不到："
                          + "；".join(str(t.get("why") or "") for t in tried[-len(unreadable):]))
            return out
    if not candidates:
        out["why"] = ("D 的报告里没有「携带的证明手稿」那一节（或那一节是空的）"
                      + ("；查过：" + "、".join(str(t.get("report") or "") for t in tried)
                         if tried else "；工作区里连一份 D 报告都没有"))
    elif statement_ids:
        out["why"] = (f"D 的携带单里有 {len(index)} 条手稿，没有一条对得上这一笔的命题号"
                      f"{[str(x) for x in statement_ids][:4]}")
    else:
        out["why"] = (f"D 的携带单里有 {len(index)} 条手稿，按正文 sha 一条都没对上这一笔")
    return out

def manuscript_proof_no(text: str) -> int:
    """手稿稿头那一行"证明号：<N>"⇒ 这一份是第几份证明（没写 ⇒ 0）。

    为什么是 0 而不是 1：这一格要区分"交付里写了号"与"交付里没写"——
    后者要回退（`proof_no_source=fallback`），前者要用它（`crafted`）。
    缺省 `#p1` 的读法由调用方在"没写"那一档自己落（`or 1`），不在这里折平。

    认的写法与 `verifications.as_proof_no` 同源（`2` / `#p2` / `p2`），但只认稿头前
    12 行里以 `- 证明号` 开头的那一行 —— 正文里出现"证明号"三个字不是元信息。
    """
    head = str(text or "").replace("\r\n", "\n").split("\n")[:12]
    import re as _re

    for raw in head:
        line = raw.strip()
        if not line.startswith("- 证明号"):
            continue
        hit = _re.search(r"[:：]\s*(?:#?\s*[pP]?\s*)?([0-9]+)", line)
        if not hit:
            continue
        no = int(hit.group(1))
        if no >= 1:
            return no
    return 0


def manuscript_statement_id(text: str) -> str:
    """手稿开头元信息里那个"命题号：stmt:<号>"⇒ 裸号（没有 ⇒ 空串）。

    为什么需要它：D 把一份稿递给 B 时，B 要判"这份稿是不是 D 携带单里点名的那一条"。
    携带单是按命题号索引的，而调用方递进来的 `derived_from` 是那条命题的承重链
    （被它引用的别的东西）—— 两处都不是"这份稿自己的号"。手稿头那一行就是它。
    """
    head = str(text or "").replace("\r\n", "\n").split("\n")[:12]
    import re as _re

    for raw in head:
        line = raw.strip()
        if not line.startswith("- 命题号"):
            continue
        hit = _re.search(r"stmt:\s*([0-9]{4,})", line)
        if hit and S.is_valid_id(hit.group(1)):
            return hit.group(1)
    return ""


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


# ------------------------------------------------------------------ 渲染（唯一实现）

def render_dependency_section(rows: Iterable[Mapping[str, Any]]) -> str:
    """把依赖行渲染成那一节固定格式的表格（表头四列，逐字与解析器对齐）。

    唯一实现放在这里（解析与渲染必须同一个人写，否则"渲染出来的格式解析器读不懂"
    这种形态没有任何地方会报）：F 的手稿渲染与秘书洗稿后的重渲染都读它。
    一条引用都没有时也把表头留着，并写一行"空表就是声明" —— 于是"这份证明是自足的"
    与"作者忘写了这一节"在收方那侧读得不一样（三态不是靠猜的）。
    """
    head = "| " + " | ".join(name for _f, _k, name in COLUMN_KEYS) + " |"
    rule = "|" + "|".join("---" for _ in COLUMN_KEYS) + "|"
    lines = [SECTION_HEADING, "", head, rule]
    count = 0
    for row in rows:
        lines.append("| {quote} | stmt:{sid} | {step} | {group} |".format(
            quote=str(row.get("quote") or "").replace("|", "／"),
            sid=str(row.get("stmt_id") or ""),
            step=str(row.get("step") or ""),
            group=int(row.get("path_group") or 1)))
        count += 1
    if not count:
        lines.append("")
        lines.append("（这一份证明没有引用任何在册命题 —— 空表就是声明。）")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ 作者侧洗稿（F 的秘书）
#
# 业主 2026-10-26 晚的原话（逐字）：「F写证明时务必加依赖面命题号，且由F的秘书对无引用
# 证明忘加空依赖面的补空，对有引用证明的命题号核实（即秘书帮它洗一遍）」
# 「F的秘书工作的时候是F写好了，提交证明给V前」。
#
# 所以这一段是"提交给 V 之前"的那一遍：它只动依赖面（命题号 / 那一段的格式），
# 绝不改证明正文（正文是 F 的署名作品）。洗出来的那一份才是交给 V、交给 D 携带的稿。

#: 无引用而缺节 ⇒ 秘书补一个空节的读数。
WASH_FILLED_EMPTY = "empty_by_secretary"
#: 有引用而缺节 / 那一段读不懂 ⇒ 秘书按证明正文的 `cites` 重渲染那一节的读数
#: （依赖面永远由代码生成，不由模型自由发挥）。
WASH_RENDERED = "rendered_from_proof"
#: 洗不动而退回 F 的受控码（"这一份先别交给 V"）。
WASH_REFUSED_ROW = "dependency_row_unverified"
#: 依赖段里的号不在册（退回 F）—— 与 B 那一侧同一个受控码。
WASH_REFUSED_UNKNOWN = REFUSED_UNKNOWN_SOURCE


def proof_steps(text: str) -> dict[int, dict[str, Any]]:
    """`## 证明` 那一节里"第几步说了什么、引了哪些 `stmt:`"⇒ `{步号: {text, cites}}`。

    步号取行首的 `N.`（F 的渲染器与真机手稿都是这个形状）。认不出步号的行不进
    这张表：它是"没有编号的散文"，不是第几步。
    """
    import re as _re

    body, _start = section_lines(text, SECTION_PROOF)
    if not body:
        return {}
    out: dict[int, dict[str, Any]] = {}
    for _ln, raw in body:
        line = str(raw or "").strip()
        if not line:
            continue
        hit = _re.match(r"^(\d+)\s*[.、)]\s*(.*)$", line)
        if not hit:
            continue
        no = int(hit.group(1))
        out[no] = {"text": hit.group(2).strip(), "cites": stmt_refs(hit.group(2))}
    return out


def _step_numbers(step_text: Any) -> list[int]:
    """依赖段那一格"第 1、3 步"⇒ `[1, 3]`（认不出就是个空列表，不猜）。"""
    import re as _re

    return [int(x) for x in _re.findall(r"\d+", str(step_text or ""))]


def _rows_from_proof(text: str) -> list[dict[str, Any]]:
    """按证明正文的 `cites` 现渲染依赖行（洗稿重建那一节的唯一口径）。

    与 `agent_f/manuscript.py::dependency_rows` 同一件事（一处渲染、一处解析；
    这里用的是同一份 `proof_steps`），所以"F 渲染出来的"与"秘书重建出来的"同形。
    """
    steps = proof_steps(text)
    rows: list[dict[str, Any]] = []
    index: dict[str, int] = {}
    for no in sorted(steps):
        for cite in steps[no]["cites"]:
            if cite in index:
                rows[index[cite]]["steps"].append(no)
                continue
            index[cite] = len(rows)
            rows.append({"stmt_id": cite, "quote": str(steps[no]["text"])[:80],
                         "steps": [no], "path_group": 1})
    for row in rows:
        row["step"] = "第 " + "、".join(str(n) for n in row.pop("steps")) + " 步"
    return rows


def _replace_section(text: str, section_text: str) -> str:
    """把 `## 依赖` 那一节整段换成 `section_text`（没有那一节就接在文末）。"""
    raw = str(text or "").replace("\r\n", "\n")
    lines = raw.split("\n")
    _body, start = section_lines(raw)
    if not start:
        return raw.rstrip("\n") + "\n\n" + section_text
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].strip().startswith("#"):
            end = i
            break
    head = lines[: start - 1]
    tail = lines[end:]
    while head and not head[-1].strip():
        head.pop()
    out = "\n".join(head + [""] + section_text.rstrip("\n").split("\n"))
    rest = "\n".join(tail).strip("\n")
    return out + ("\n\n" + rest if rest else "") + "\n"


#: 洗过的那一份手稿里那一行元信息的固定前缀（B 侧据此读 `manuscript_washed=true`）。
WASH_MARK = "- 依赖面洗稿："
#: 洗稿元信息的行内键（渲染与解析共用，避免两处各写一个拼法）。
WASH_MARK_ACTOR = "执行者"
WASH_MARK_FILLED = "补节"
WASH_MARK_TAG = "已洗"


def mark_washed(text: str, *, actor: str = "", filled: str = "") -> str:
    """在洗过的手稿里盖一行元信息（幂等：先删旧的同一行，再插到 `- 计划：` 之后）。

    为什么要把"这一份被秘书洗过"写进正文而不是只存在调用方内存里：D 携带、B 读的
    都是盘上那一份文件；读数必须跟着文件走，否则"B 读到的是不是洗过的那一版"
    在收方那侧无从判断（而那正是这条链要回答的问题）。
    """
    raw = str(text or "").replace("\r\n", "\n")
    lines = [ln for ln in raw.split("\n") if not ln.strip().startswith(WASH_MARK)]
    parts = [f"{WASH_MARK_TAG}=true"]
    if str(actor or "").strip():
        parts.append(f"{WASH_MARK_ACTOR}={str(actor).strip()}")
    if str(filled or "").strip():
        parts.append(f"{WASH_MARK_FILLED}={str(filled).strip()}")
    # 形如：`- 依赖面洗稿：已洗=true；执行者=secretary-F；补节=empty_by_secretary`
    mark = WASH_MARK + "；".join(parts)
    at = 0
    for i, ln in enumerate(lines):
        if ln.strip().startswith("- 计划："):
            at = i + 1
            break
    else:
        at = min(2, len(lines))
    lines.insert(at, mark)
    return "\n".join(lines)


def manuscript_wash_reading(text: str) -> dict[str, Any]:
    """读手稿里那一行洗稿元信息 ⇒ `{washed, actor, filled, mark}`（没有就 `washed=False`）。

    三态纪律：没有那一行 = "这一份没被洗过"（`washed=False`），不是"洗过、没变化"。
    """
    for raw in str(text or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line.startswith(WASH_MARK):
            continue
        body = line[len(WASH_MARK):]
        cells = dict(
            tuple(cell.split("=", 1)) for cell in body.split("；") if "=" in cell)
        return {"washed": str(cells.get(WASH_MARK_TAG) or "").lower() == "true",
                "actor": str(cells.get(WASH_MARK_ACTOR) or ""),
                "filled": str(cells.get(WASH_MARK_FILLED) or ""),
                "mark": line}
    return {"washed": False, "actor": "", "filled": "", "mark": ""}


def wash_dependency_section(text: str, *,
                            statement_rows: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """秘书那一遍洗稿：只洗依赖面，不改证明正文（业主 2026-10-26 晚的裁定）。

    三件事，按顺序：

    1. `## 依赖` 那一节缺了、或者读不懂 ⇒ 由代码重渲染（有 `cites` 就按正文现算行，
       一条都没有就落一个空节 + 一行"空表就是声明"）。读数 `deps_section_filled`：
       `empty_by_secretary`（无引用补空）/ `rendered_from_proof`（按正文重渲染）；
    2. 每一条依赖行的命题号逐条核：
       - 不在册 ⇒ 洗不动，整份退回 F（`deps_refused=dependency_source_not_registered`，
         点名第几行、哪个号）—— 这一份不许交给 V；
       - 在册、而且它说"用在哪一步"与那一步 `cites` 对不上 ⇒ 能确定正确号时洗成那个号
         （`deps_washing=[{line, from, to, why}]`），不能确定（那一步引了不止一条，
         或一条都没引）⇒ 退回；
       - 对得上 ⇒ 原样留下。
    3. 洗过才重渲染那一节（没动过就逐字原样返回，`washed=False` —— 这一步是幂等的）。

    ## 为什么用"那一步的 cites"当核实依据，而不是拿 label 与 F 的原话比
    `quote` 那一格是 F 说"我在这一步怎么用它"，不是那条命题的正文 —— 拿它去和
    label 比相似度，得到的是措辞的巧合，而不是判断（本仓最忌的"看起来像判据"）。
    真正可判的是同一份手稿里两处对同一个号的说法：正文那一步引了谁、依赖表说引了谁。
    它们对不上时，错的只能是依赖表那一格（正文是 F 的署名作品，秘书不改它）。

    返回 `{checked, washed, text, deps_section_filled, deps_washing, deps_refused,
    reason, section, rows, columns_ok}`：`text` 是洗过的那一份（退回时是原文）。
    """
    raw = str(text or "")
    index = {str(r.get("stmt_id") or ""): dict(r) for r in statement_rows}
    section = parse_dependency_section(raw)
    out: dict[str, Any] = {
        "checked": True, "washed": False, "text": raw,
        "deps_section_filled": "", "deps_washing": [], "deps_refused": "",
        "reason": "", "section": section, "rows": [],
        # 认不出的行 / 列问题由 `section` 自己带（`problems`），这里只回放它的结论。
        "columns_ok": not bool(section.get("problems")),
    }
    refs = stmt_refs(proof_body(raw))
    filled = ""
    rows: list[dict[str, Any]]
    if not section.get("present"):
        rows = _rows_from_proof(raw)
        filled = WASH_RENDERED if rows else WASH_FILLED_EMPTY
    elif section.get("problems"):
        rows = _rows_from_proof(raw)
        filled = WASH_RENDERED
    else:
        rows = [dict(r) for r in section.get("rows") or []]
        # 那一节读得懂但是空的、而正文里确实有 `stmt:` 引用 ⇒ 表是漏写的：
        # 按正文的 `cites` 重建（这是"能确定"的那一档，不猜）。
        if not rows and refs:
            rows = _rows_from_proof(raw)
            if rows:
                filled = WASH_RENDERED
    steps = proof_steps(raw)
    kept: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    def _finding(*, line: int, quote: str, got: str, expected: str, why: str,
                 how_to_fix: str) -> dict[str, Any]:
        """一条"打回"的逐条说明（业主：哪一行 / 写的什么 / 该是什么 / 为什么 / 怎么改）。"""
        return {"line": int(line), "quote": str(quote or ""), "got": str(got or ""),
                "expected": str(expected or ""), "why": str(why or ""),
                "how_to_fix": str(how_to_fix or "")}

    # 结构都读不懂、而正文里又没有 `cites` 可以据以重建 ⇒ 打回（不许猜一行出来）。
    # 注意"缺节 + 一条引用都没有"不是这一档：那是自足证明，秘书补一个空节即可。
    if not rows and (refs or section.get("problems")):
        reason = str(section.get("reason") or "").strip()
        findings.append(_finding(
            line=int(section.get("heading_line") or 0),
            quote="（依赖段缺失或读不懂）",
            got=f"present={bool(section.get('present'))}，problems={len(section.get('problems') or [])}",
            expected="一张四列的表（引用 / 命题号 / 用在哪一步 / 路径号）",
            why=(reason or f"手稿里没有 `{SECTION_HEADING}` 这一节，而证明正文里也没有可据以重建的 `stmt:` 引用"),
            how_to_fix=(f"在证明手稿里补一节 `{SECTION_HEADING}`（四列表，列固定），"
                        "或者在证明正文的每一步写明依据（`stmt:NNNNNN`）—— 依赖面由代码按它渲染")))
    for row in rows:
        sid = str(row.get("stmt_id") or "")
        line = int(row.get("line") or 0)
        quote = str(row.get("quote") or "")
        anchor = index.get(sid)
        if anchor is None:
            findings.append(_finding(
                line=line, quote=quote, got=f"stmt:{sid}",
                expected="（无法确定 —— 请自己指认台账里真实的那一条）",
                why=(f"第 {line} 行点名的 `stmt:{sid}` 不在册"
                     f"（台账里现有 {len(index)} 条命题）"),
                how_to_fix=(f"把 `stmt:{sid}` 改成台账里真实的一条在册命题号"
                            "（`attack.step` 的返回值里有本轮可引 id 清单），并让正文那一步写明依据")))
            continue
        level = str(anchor.get("evidence_kind") or "").strip()
        if not level or level not in S.EVIDENCE_KINDS:
            findings.append(_finding(
                line=line, quote=quote, got=f"stmt:{sid}（evidence_kind={level!r}）",
                expected=f"{CITATION_MIN_LEVEL} 级及以上",
                why=(f"第 {line} 行点名的 `stmt:{sid}` 档位读不到"
                     f"（不在词表 {S.EVIDENCE_KINDS} 里）⇒ 读不到就不许引"),
                how_to_fix=("先让 V 走查签「成立」（或形式化 / 穷举核过）把它升到 "
                            f"{CITATION_MIN_LEVEL} 级，再引它")))
            continue
        if not citation_level_allowed(level):
            findings.append(_finding(
                line=line, quote=quote, got=f"stmt:{sid}（{level}）",
                expected=f"{CITATION_MIN_LEVEL} 级及以上",
                why=(f"第 {line} 行点名的 `stmt:{sid}` 现在是 {level}，"
                     f"引用要求 {CITATION_MIN_LEVEL} 级及以上"),
                how_to_fix=(f"先让它过 V 的逐行走审站到 {CITATION_MIN_LEVEL} 级"
                            "（或换一条已经够格的命题），再来引它")))
            continue
        cited: list[str] = []
        for no in _step_numbers(row.get("step")):
            cited.extend((steps.get(no) or {}).get("cites") or [])
        cited = list(dict.fromkeys(cited))
        if not cited:
            # 那一步没有 `cites`（前提步 / 没有编号）⇒ 这一层核不了号，
            # 在读数的 `rows` 里如实标 unverified，不把它说成"核过了"。
            kept.append({**row, "verified": "unverified"})
            continue
        if sid in cited:
            kept.append({**row, "verified": "cited"})
            continue
        fixable = [x for x in cited if x in index]
        if len(fixable) == 1:
            # 能确定（那一步只点名了一条在册命题）⇒ 直接洗成它，留逐行记录。
            out["deps_washing"].append({
                "line": line, "from": sid, "to": fixable[0],
                "why": (f"第 {row.get('step')} 的 `cites` 只点名了 `stmt:{fixable[0]}`，"
                        f"而依赖表写的是 `stmt:{sid}` ⇒ 按正文洗成 `stmt:{fixable[0]}`")})
            kept.append({**row, "stmt_id": fixable[0], "verified": "washed"})
            continue
        findings.append(_finding(
            line=line, quote=quote, got=f"stmt:{sid}",
            expected="（无法唯一确定 —— 请自己指认）",
            why=(f"第 {line} 行写的是 `stmt:{sid}`，而第 {row.get('step')} 的 `cites` 是 "
                 f"{['stmt:' + x for x in cited]} ⇒ 号与正文对不上"),
            how_to_fix=("在依赖表里写清真正的那一条在册命题号，并让正文那一步的 `cites` 同步它")))
    if findings:
        out.update(
            deps_refused=WASH_REFUSED_ROW,
            deps_refused_findings=findings,
            reason=("依赖面的命题号核实不过（这一份不许提交给 V，退回 F 重写）："
                    + "；".join(str(f["why"]) for f in findings)),
            rows=[dict(r) for r in rows])
        return out
    out["rows"] = kept
    changed = bool(filled) or bool(out["deps_washing"])
    if not changed:
        # 已经洗过（幂等）：逐字返回，`washed=False` —— 读的人据此知道"这一遍没动它"。
        return out
    out.update(washed=True, deps_section_filled=filled,
               text=_replace_section(raw, render_dependency_section(kept)))
    out["section"] = parse_dependency_section(str(out["text"]))
    return out



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
