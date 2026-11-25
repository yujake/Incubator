# -*- coding: utf-8 -*-
"""落点布局：`manuscripts/<角色>/` · `work/<角色>/` · `reports/` 退役（一份分类，读写两侧共用）。

## 这一层回答什么问题

2026-11-22 业主裁定（`draft/194` §二/§三）：「草稿区不能叫 report 这个名字，换名且按角色整理」。
于是工作区里每一份正文 / 草稿只有两个合法去处，记录型内容不进文件：

| 东西 | 落点 |
|---|---|
| 正文（F/B/D 的证明稿、G 的论文） | `manuscripts/<角色>/<kind>-<编号>.md` |
| 草稿（A/E/F/H/G 的过程稿） | `work/<角色>/<kind>-<编号>.md` |
| 记录型（检索 / 实验 / 攻坚 / 审读） | 进表（`search_requests` / `experiments` / `attack_plans` / `review_findings`） |
| 交接账本（不是手稿） | `work/handoffs.jsonl`（从 `manuscripts/` 挪出） |

`reports/` 退役。真机读数（2026-11-22，`projects/` 55 个工作区）：它下面共 690 份平铺
文件，四种东西混放 —— `e-num-*` 235 · `lit-r-*` 184 · `attack-*` 83 · `f-proof-*` 70 ·
`*research*` 52 · `b-proof-*` 31 · `*-review.md` 5 · 其余 30。

## 旧布局：不再兼容（业主 2026-11-22 裁定）

早一版这里有一档 `legacy`（旧布局"读得通、不判畸形"）。业主后来裁定「旧工作区不必兼容」，
于是那一档取消：旧布局（`reports/` 下的一切、`documents/` 下的一切、
`manuscripts/handoffs.jsonl`）现在报明确的"旧布局（不再支持）"，按 `error` 落成畸形、
整份读数退出码 1。不许静默当 ok、不许折成空：一个人打开读数必须一眼看出"这里是旧的"，
而不是"什么都没报"。同一档严重度（:data:`UNSUPPORTED_SEVERITY`）也管 `library/` 的两种旧
落点（`library/<lit_id>/<名>` 与裸扁平 `<名>`，见 `literature._landing_verdict`）——
"旧布局算不算畸形"只能有一个口径，否则两处会慢慢给同一种形态两个答案。

真机读数（2026-11-22，`projects/` 55 个工作区）说明这个选择意味着什么：旧布局占全部
（`reports/` 690 份 / 29 个工作区、`manuscripts/handoffs.jsonl` 26 个、`documents/` 22 份 /
18 个、`work/` 0 个、`manuscripts/<角色>/` 0 个）。所以这 55 个工作区在新口径下都是
`malformed` —— 那不是回归，那是"还没搬"的读数；B2b-2 搬完之后它们才会变绿。

## 一份分类，两处读

:func:`layout_of` 是落点规范的唯一真身：

- 写侧（`tools/fs_tools.py` 的落点闸）延迟 import 它，问"这个路径是不是落在退役目录 /
  别人的角色目录里"；
- 读侧（本模块末尾 `RULES["layout"]["landing"]`）问"这一份文件合不合规范"。

两侧共用一份分类，是因为第二份分类早晚会与第一份给同一个路径两个答案，而那两个答案之间
没有任何东西会报错。依赖方向是 `tools → wellformed`（工具层依赖只读层），与 `fs_tools`
延迟 import `manuscriptfamily` / `depsection` 同一条。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .. import manuscriptfamily as MFAM
from .. import manuscripts as MS
from .. import schema as S
from .predicates import _Unchecked, _rel
from .registry import _Ctx, _rule
from .states import Finding

# ---------------------------------------------------------------- 词表（唯一真身）

#: 退役目录的字面量（`reports/` 已退役；2026-11-22 B2b-2 起一族的落点目录是
#: `manuscripts/<角色>/`，所以这里不再从 `manuscriptfamily.MANUSCRIPT_DIR` 派生 ——
#: 那个常量现在是"正文根"，派生出来会把 `manuscripts/` 自己判成退役目录）。
REPORTS_DIR: str = "reports"

#: 正文目录（`manuscripts.py` 是它的权威：交接账本与手稿曾共用这一个名字）。
MANUSCRIPTS_DIR: str = MS.MANUSCRIPTS_DIR

#: 草稿目录（本规范新立的名字；除本模块外没有第二个定义点）。
WORK_DIR = "work"

#: 正文曾住过的地方（`documents/<N>.md` 是 `documents` 表 `markdown_path` 指向的那一份）。
DOCUMENTS_DIR = "documents"

#: 交接账本的文件名（`manuscripts.py` 是它的权威）。
HANDOFFS_NAME: str = MS.HANDOFFS_NAME

#: 多项目根布局：根工作区是仓库根时，真正的工作区在 `projects/<p>/`。与
#: `fs_tools.RESERVED_ARTIFACT_TABLE` 里 `wsdata:projects` 那一行同一处假设。
PROJECTS_DIR = "projects"

#: 本规范管的四个一级目录（写侧只拒前三个；`documents/` 的封口随 B2b-2 搬目录）。
MANAGED_DIRS: tuple[str, ...] = (REPORTS_DIR, MANUSCRIPTS_DIR, WORK_DIR, DOCUMENTS_DIR)

#: 写侧管的那三个一级目录。
WRITE_GATED_DIRS: tuple[str, ...] = (REPORTS_DIR, MANUSCRIPTS_DIR, WORK_DIR)

#: 角色名录：`schema.ROLES` 是唯一来源，主控不在里面（它另有一个常量）。
ROLE_NAMES: tuple[str, ...] = tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)

# ---------------------------------------------------------------- 三档判词


#: 合规范（新布局）。
CANONICAL = "canonical"
#: 旧布局（不再支持）：`reports/` 下的一切、`documents/` 下的一切、`manuscripts/handoffs.jsonl`。
UNSUPPORTED = "unsupported"
#: 历史形态（读得通、新写不产出）：2026-11-25 起只用于 `library/` 的两档历史落点
#: （`<4位号>/<名>` 与扁平一段）。它与 `UNSUPPORTED` 的区别是处置：前者不许再写但
#: 不翻畸形（真实盘上有 lp-ball-15/22 这类历史数据，报 error 会让旧工作区整片变红），
#: 后者是"这个目录已经退役、必须搬"。严重度只有 `LEGACY_SEVERITY` 一格说了算。
LEGACY = "legacy"
#: 落在受管的目录里而不合规范（新布局才能有的形态）。
MALFORMED_FORM = "malformed"
#: 不在本规范管的目录里（`code/` / `out/` / `notes/` / 根上的文件）—— 本层一个字都不判。
UNRELATED = "unrelated"

FORM_VERDICTS: tuple[str, ...] = (CANONICAL, UNSUPPORTED, LEGACY, MALFORMED_FORM, UNRELATED)

#: finding code：`reports/` 下的旧落点（退役目录）。
CODE_REPORTS_RETIRED = "layout_reports_retired"
#: finding code：交接账本还在 `manuscripts/`（它不是手稿，新家是 `work/handoffs.jsonl`）。
CODE_HANDOFFS_LEDGER = "layout_handoffs_ledger_in_manuscripts"
#: finding code：正文还在 `documents/`（新落点是 `manuscripts/<角色>/`）。
CODE_DOCUMENTS_BODY = "layout_documents_body"
#: finding code：`manuscripts/` 或 `work/` 下第一段不是角色目录。
CODE_ROLE_DIR_MISSING = "layout_role_dir_missing"
#: finding code：第一段有个目录名，但它不是角色（`manuscripts/notes/x.md`）。
CODE_ROLE_DIR_NOT_A_ROLE = "layout_role_dir_not_a_role"


def is_role(segment: Any) -> bool:
    """这一段是不是一个角色名（大小写不敏感：Windows 上 `a` 与 `A` 是同一个目录）。"""
    return bool(canonical_role(segment))


def canonical_role(segment: Any) -> str:
    """段落的规范写法（`b` ⇒ `B`）；不是角色名 ⇒ 空串。

    为什么返回规范写法而不是 bool：拒信与 finding 都要逐字点名"你写的是 `B`、你是 `A`"，
    而"角色名照原样回显"会让 `manuscripts/b/x.md` 的读数看不出规范名是 `B`。
    """
    low = str(segment or "").strip().casefold()
    if not low:
        return ""
    for name in ROLE_NAMES:
        if low == name.casefold():
            return name
    return ""


@dataclass(frozen=True)
class Landing:
    """一条路径的落点判词（`:func:`layout_of` 的返回值）。"""

    #: :data:`FORM_VERDICTS` 之一。
    verdict: str
    #: 命中的一级目录（`reports` / `manuscripts` / `work` / `documents`；`UNRELATED` 时为空）。
    top: str = ""
    #: 第二段的原样读数（`manuscripts` / `work` 才有）。
    role_seen: str = ""
    #: 第二段解析出的规范角色名（不是角色 ⇒ 空串）。
    role: str = ""
    #: finding code（`CANONICAL` / `UNRELATED` 时为空）。
    code: str = ""
    #: 逐字读数：为什么这一份是这个判词（要能被人复核）。
    why: str = ""

    @property
    def managed(self) -> bool:
        """这一段路径是不是本规范管的（`UNRELATED` ⇒ False）。"""
        return self.verdict != UNRELATED


# ---------------------------------------------------------------- 分类


def _parts(rel: Any) -> list[str]:
    """相对路径 ⇒ 段列表（`/` 分隔、抹掉空段与 `.`、抹掉 `projects/<p>/` 前缀）。

    抹前缀与 `fs_tools` 的 `wsdata:projects` 同一条假设：多项目根布局下真正的工作区在
    `projects/<p>/`，于是 `projects/lp-ball-15/reports/x.md` 与 `reports/x.md` 是同一件事。
    """
    parts = [p for p in str(rel or "").replace("\\", "/").split("/") if p not in ("", ".")]
    if len(parts) >= 3 and parts[0].casefold() == PROJECTS_DIR.casefold():
        return parts[2:]
    return parts


def _top_is(parts: list[str], name: str) -> bool:
    """第一段是不是 `name`（大小写不敏感）。"""
    return bool(parts) and parts[0].casefold() == name.casefold()


def _role_dir_landing(parts: list[str], top: str) -> Landing:
    """`manuscripts/` 与 `work/` 的判词：第一段必须是角色目录。"""
    if len(parts) >= 2:
        role = canonical_role(parts[1])
        if role:
            return Landing(CANONICAL, top=top, role_seen=parts[1], role=role)
    if (len(parts) == 2 and parts[1].casefold() == HANDOFFS_NAME.casefold()):
        # 交接账本不是手稿。它还在 `manuscripts/` 里 ⇒ 旧落点（新家是 `work/handoffs.jsonl`）；
        # 它已经在 `work/` 里 ⇒ 新落点（上面 `layout_of` 的分支先返回 CANONICAL）。
        return Landing(UNSUPPORTED, top=top, role_seen=parts[1], code=CODE_HANDOFFS_LEDGER,
                       why=(f"旧布局（不再支持）：`{top}/{parts[1]}` 是交接账本"
                            f"（一行一份、收件人是角色），不是手稿 ⇒ 新落点是 "
                            f"`{WORK_DIR}/{HANDOFFS_NAME}`"))
    if len(parts) == 1:
        return Landing(MALFORMED_FORM, top=top, code=CODE_ROLE_DIR_MISSING,
                       why=(f"`{top}/` 下面必须先有 `<角色>/` 这一段（读到的就是目录本身）；"
                            f"正文写 `{top}/<你的角色>/…`"))
    if len(parts) == 2:
        return Landing(MALFORMED_FORM, top=top, role_seen=parts[1], code=CODE_ROLE_DIR_MISSING,
                       why=(f"第二段读到 `{parts[1]}`，它不是角色名 ⇒ 这一份不落进任何角色的面"
                            f"（`{top}/<你的角色>/…`，角色是 {'/'.join(ROLE_NAMES)}）"))
    return Landing(MALFORMED_FORM, top=top, role_seen=parts[1], code=CODE_ROLE_DIR_NOT_A_ROLE,
                   why=(f"第二段是 `{parts[1]}` 而不是角色名 ⇒ `{top}/` 下面只认 "
                        f"`<角色>/…`（角色是 {'/'.join(ROLE_NAMES)}）"))


def layout_of(rel: Any) -> Landing:
    """一份工作区相对路径的落点判词（写侧与读侧共用的唯一分类）。

    四个一级目录各一档，其余一律 :data:`UNRELATED`（不在本层判）：

    - `reports/` 下的每一份 ⇒ :data:`UNSUPPORTED`（退役目录：旧布局不再支持；写侧也拒）；
    - `documents/` 下的每一份 ⇒ :data:`UNSUPPORTED`（正文曾住在这里；新落点是 `manuscripts/<角色>/`）；
    - `manuscripts/<角色>/` 下的每一份 / `work/<角色>/` 下的每一份 ⇒ :data:`CANONICAL`；
    - `work/handoffs.jsonl` ⇒ :data:`CANONICAL`（交接账本的新家）；
    - `manuscripts/handoffs.jsonl` ⇒ :data:`UNSUPPORTED`（账本还留在手稿目录里）；
    - `manuscripts/<非角色>/` 下的每一份、`work/<非角色>/` 下的每一份、以及两个目录本身 ⇒ :data:`MALFORMED_FORM`。

    `code/` / `out/` / `notes/` / 根上的文件不在本规范里 —— 它们不是"不合规"，
    是"不归这一层管"（写侧照旧走既有逻辑，不折平）。
    """
    parts = _parts(rel)
    if not parts:
        return Landing(UNRELATED)
    if _top_is(parts, REPORTS_DIR):
        return Landing(
            UNSUPPORTED, top=REPORTS_DIR, code=CODE_REPORTS_RETIRED,
            why=(f"旧布局（不再支持）：`{REPORTS_DIR}/` 已退役（2026-11-22 业主裁定："
                 f"草稿区不能叫 report，按角色整理）⇒ 草稿进 `{WORK_DIR}/<角色>/`、正文进 "
                 f"`{MANUSCRIPTS_DIR}/<角色>/`、记录型进表"))
    if _top_is(parts, DOCUMENTS_DIR):
        return Landing(
            UNSUPPORTED, top=DOCUMENTS_DIR, code=CODE_DOCUMENTS_BODY,
            why=(f"旧布局（不再支持）：`{DOCUMENTS_DIR}/` 名说「文档」实为手稿正文 ⇒ "
                 f"正文的新落点是 `{MANUSCRIPTS_DIR}/<角色>/`，`documents` 表只留登记"))
    if _top_is(parts, MANUSCRIPTS_DIR):
        return _role_dir_landing(parts, MANUSCRIPTS_DIR)
    if _top_is(parts, WORK_DIR):
        if len(parts) == 2 and parts[1].casefold() == HANDOFFS_NAME.casefold():
            return Landing(CANONICAL, top=WORK_DIR, role_seen=parts[1],
                           why=f"交接账本的新家（`{WORK_DIR}/{HANDOFFS_NAME}`）")
        return _role_dir_landing(parts, WORK_DIR)
    return Landing(UNRELATED)


# ---------------------------------------------------------------- 读侧规则

#: 旧布局那一档的严重度（`error` ⇒ 畸形、退出码 1、读数里看得见）。
#:
#: 这一格是反真空的打桩点：把它降成 `"info"`（或任何不翻三态的值），旧布局立刻读成 ok ——
#: 于是"旧布局必红"这件事的来源精确地是这一格，而不是"碰巧有规则"。
#:
#: 它管两个落点：这一层的四个受管目录（`layout` 一类）与 `library/` 的两种旧落点
#: （`literature` 一类的 `_landing_verdict` 读的是同一格）—— 业主裁定的"旧工作区不必
#: 兼容"是一条，宽严不在第二个地方另定。
UNSUPPORTED_SEVERITY = "error"

#: 历史形态那一档的严重度（`legacy` ⇒ 进读数、不翻三态、退出码不变）。
#:
#: 这是与 `UNSUPPORTED_SEVERITY` 成对的反真空打桩点：把它改成 `"error"`，旧工作区
#: （lp-ball-15/22 与 p9 那批 4 位号老盘）立刻整片变红；改成 `"info"` 则"历史形态"
#: 混进"有解释的读数"里，看不出它"新写不产出"。它只用于 `library/` 的历史落点
#: （`literature.py` 的 `_landing_verdict` 读的是这一格）。
LEGACY_SEVERITY = "legacy"

#: 一个受管目录最多逐条列出多少份（`reports/` 真机 690 份；其余按目录分开算）。
#:
#: 为什么要有上限而不是全列：读数面（`statusreport.collect`）把 findings 逐条带走，
#: 一份 690 条的数组会让"看一眼状态"变成翻页。截断本身要写在 `notes` 里 ——
#: "只列了前 N 份"与"只有 N 份"必须是两件看得出来的事。
SCAN_LIMIT = 200


def _managed_dirs(root: Path) -> list[Path]:
    """根下那四个受管目录（按实际大小写找，`Reports` 也算）。"""
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        raise _Unchecked(f"读不到工作区根 {root}（{type(exc).__name__}: {exc}）") from exc
    wanted = {name.casefold() for name in MANAGED_DIRS}
    return sorted(p for p in entries
                  if p.name.casefold() in wanted and p.is_dir())


def _walk(base: Path) -> list[Path]:
    """一个受管目录下的全部文件（读不到 ⇒ `_Unchecked`，不许折成"零份"）。"""
    try:
        return sorted(p for p in base.rglob("*") if p.is_file())
    except OSError as exc:
        raise _Unchecked(f"读不到 {base.name}/ 下面的文件"
                         f"（{type(exc).__name__}: {exc}）") from exc


def _finding(ctx: _Ctx, where: str, landing: Landing) -> Finding:
    """一份文件的 finding（严重度由判词决定：旧布局那一档由 :data:`UNSUPPORTED_SEVERITY` 定）。"""
    if landing.verdict == UNSUPPORTED:
        return Finding(kind=ctx.kind, where=where, detail=landing.why,
                       severity=UNSUPPORTED_SEVERITY, code=landing.code)
    return Finding(kind=ctx.kind, where=where, detail=landing.why,
                   severity="error", code=landing.code)


@_rule("layout", "landing")
def _rule_layout(ctx: _Ctx) -> list[Finding]:
    """整棵树上每一份受管文件：新布局合规范 / 旧布局（不再支持）/ 新目录下不合规。

    规则自己摊开文件清单（`driver._check_tree`），不是"每份文件跑一遍"：布局是整棵树的
    属性，一份文件单独看判不出"它旁边的目录叫什么"。

    `unsupported` 与 `malformed` 的分界就是 :func:`layout_of` 的判词：
    `reports/` 下的每一份、`documents/` 下的每一份、`manuscripts/handoffs.jsonl` 是旧布局
    （业主 2026-11-22 裁定：旧工作区不必兼容 ⇒ 报 error、读数看得见）；
    `manuscripts/x.md`、`manuscripts/notes/x.md` 这类是新目录下的不合规（也是 error）——
    两者都只有一个来路：前者是「还没搬」（B2b-2 之前），后者是「写的时候就没按规范落」。
    """
    root = ctx.root
    if root is None:
        raise _Unchecked("没有工作区根 ⇒ 读不到 reports/ manuscripts/ work/ documents/")
    findings: list[Finding] = []
    for base in _managed_dirs(root):
        files = _walk(base)
        for path in files[:SCAN_LIMIT]:
            landing = layout_of(_rel(root, path))
            if landing.verdict in (UNSUPPORTED, MALFORMED_FORM):
                findings.append(_finding(ctx, _rel(root, path), landing))
        if len(files) > SCAN_LIMIT:
            ctx.notes.append(
                f"{base.name}/ 下共 {len(files)} 份，这里只逐条列出前 {SCAN_LIMIT} 份"
                f"（余下的判词与列出的这些同档；上限见 layout.SCAN_LIMIT）")
    return findings


def layout_reading(root: str | Path) -> dict[str, int]:
    """只读读数：受管目录里每种判词各多少份（`UNRELATED` 不计）。

    它是给读数面与搬目录用的计数（不算三态）：`unsupported` 多少、`malformed` 多少、
    `canonical` 多少。读不到目录 ⇒ 抛 `_Unchecked`，由调用方决定怎么记。
    """
    counts = {verdict: 0 for verdict in FORM_VERDICTS}
    root_p = Path(root)
    for base in _managed_dirs(root_p):
        for path in _walk(base):
            counts[layout_of(_rel(root_p, path)).verdict] += 1
    return counts


def iter_unsupported(root: str | Path) -> Iterator[str]:
    """逐个吐出不再支持的旧布局路径（B2b-2 搬目录时的清单；读不到目录 ⇒ `_Unchecked`）。"""
    root_p = Path(root)
    for base in _managed_dirs(root_p):
        for path in _walk(base):
            rel = _rel(root_p, path)
            if layout_of(rel).verdict == UNSUPPORTED:
                yield rel
