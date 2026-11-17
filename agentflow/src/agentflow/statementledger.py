# -*- coding: utf-8 -*-
"""命题台账的查口：两种口径，各自独立、各自带读数（只读、零模型调用、不写盘）。

## 先读这一节：这个模块管什么、不管什么

本模块是 B 秘书「增 / 改 / 查」三族里查那一族的实现，也是全仓唯一一处
「怎么在 `statements` 里找行」的实现。它只回答一个问题：台账里有哪些行。
它不回答「这两条是不是同一条命题」——那是判定，仍归 `secretary.Secretary.judge`
（唯一判定口）与 `secretary.Secretary.adjudicate_proposition`（检索 + 判定的唯一组合点）。

| 归本模块 | 不归本模块 |
|---|---|
| 按编号取一行（`by_id`） | 判同一性 / 判形态 / 判档位（`judge` 那一族） |
| 按内容关键字检索（`by_keywords`） | 挑关键词（`pick_statement_keywords`，一次模型调用） |
| 取数口、可检索池、全表索引、正文全等（底座） | 写台账（`record_statement` / `amend_statement_meta` / `land_statement`） |

三条硬边界：不写盘、不开事务、不发模型调用。前端要事务内的快照时，把 `tx`
传进来即可（`Store.rows` 与 `Tx.rows` 同一个 `rows(table)` 协议）；要自己给一批行时
传 `rows=`。三种来源走同一份实现，读数里 `source` 记的是哪一种。

## 两种口径为什么必须分开（不是两个函数名，是两件不同的事）

- 口径一（`by_id`）回答的是确定性事实：编号就是主键，逐字相等就命中。
  所以它不做任何过滤 —— 不按 `kind` 筛、不按 `status` 筛。理由有三条，
  每条都对着一个既有调用方：放弃命题那一支必须找得到 `abandoned` 的行
  （`statementabandon.apply_abandonment`）；V 的签档要读得到已签的行
  （`vsigns.sign_filing_reading`）；判「点名的那一条还可不可并」时，
  「读不到」与「读到了但状态不可并」必须是两句话（`Secretary._proposition_owner`
  把它们合在一条 fail-closed 原因里，但前提是它先读到了那一行）。
  0 命中 = 这一行不在台账里（确定性）。

- 口径二（`by_keywords`）回答的是「有哪些行提到了这件事」：匹配规则是
  `label` / `statement_full` 经 `textutil.normalize` 后包含任一关键词
  （全半角 / 大小写 / 标点归一，多词任一命中）。它永远不能把 0 命中当成
  「不在册」—— 同义词（「质数」/「素数」）、记号差异（`p^a` / `pᵃ`）、换了行文
  都会漏。唯一的正式用法就是这样读它的：0 命中 ⇒ 判 different，
  但读数里 `why` 明写「命中 0 条」，好让读的人知道那是「这批词没命中」而不是
  「台账里没有」（业主：「检索只是取候选，不参与判定」）。

正因为这两条口径认识论上不同，它们互不调用：`by_id` 不用关键词、`by_keywords`
不用编号。判据 `tests/test_the_statement_ledger_has_two_ways_to_be_asked.py`
用静态 AST 检查钉住这一点（不是靠运行时打桩），另外各有一条「把这一条口径降级
⇒ 依赖它的判据红」的反真空。

## 与工具层 `table.search` 的关系（statements 上同一把尺）

通用表工具（`tools/table_tools.py` 的 `table.get` / `table.search`）对别的表仍是列文本：
`casefold` 子串、对该表全部标量字符串字段。本模块是命题语义面的查：只比 `label` /
`statement_full`，用 `textutil.normalize`（与判重、查重同一把尺）。

在 `statements` 表上，两边是一把尺：`table.search` 的 statements 分支
不再用 `casefold`，而是调同一份判据（`textutil.normalized_keywords` /
`textutil.matched_keywords`），搜索面也收敛到 `label` / `statement_full`；点名别的列
（`proof_text` / `status` / `stmt_id` …）会受控拒绝，不静默忽略。
所以「同一个查询在两处给出不同命中」这个形态在命题台账上已被消掉（判据：
`tests/test_the_two_rulers_agree_on_the_ledger.py`，反真空是把那一路换回 `casefold` ⇒ 红）。

`table_tools.py` 在 `.noai-paths` 的 FC-27 禁改区（`auth-audit` 类）：改它要按
`scripts/noai_gate.py --baseline` 登记，登记 ≠ 批准，仍需 2 名 reviewer 逐行走查。

## 池（查哪一批）归调用方，不归本模块

「查哪一批」是语义决定，不是实现细节：判命题同一性要active 命题（跳概念行、
跳被否证/被取代的行），判概念同一性要概念行，收工读数是全部行。
把池焊死在查里，就是把这三种折平。所以：

- `by_id` / `by_keywords` 查的是你给的那批行（不给就用台账全表，`scanned` 如实记）；
- 要池就 `rows=pool(rows, kinds=…)` —— `pool` 是唯一一份池过滤实现；
- 那条 kind 名单（`secretary.PROPOSITION_KINDS`）与候选正文的截断长度
  （`secretary.PROPOSITION_VERDICT_TEXT_CHARS`）都由调用方传进来：本模块不复制
  这两份常量，也不给自己定新的阈值。

## 第三种问法？不是 —— 「被引面」是依赖账的反向投影

业主逐字：「在命题台账加被引面读数，是手稿录入时获取依赖面和将注册的命题号，
把命题号打进各依赖面的被引面，是自动维护，暂不研究消费者」。

所以 `cited_by` 不是第三种「在 `statements` 里找行」的口径（那种口径仍然只有
两条），而是 `dependencies` 这本账的反向读法：「谁引了我」= `source_stmt_id == 我`
的那些行的 `used_by`。

写侧一个字都不用改，这条读数是派生的：B 登记时先拿到号
（`secretary.Secretary._record_statement_tx` 里的 `tx.alloc_id`），再在同一笔事务里
按那个号写依赖行 —— `used_by="stmt:<刚拿到的号>"`、`source_stmt_id=<被引命题>`
（`Secretary._write_dep_steps`，`proofloc.used_by_of` 是那个号的唯一拼法）。所以
「录入完成后，被引的那些命题的读数里立刻能看到这一条引了它」是结构性的，不需要
第二次维护、也没有可漏抄的一步。判据 `tests/test_the_cited_face_is_read_from_the_dependency_ledger.py`
用正控（登记前后 0 条 → 1 条）、多引用、三态与两条反真空钉住它。

## 读数（三种结局必须分得开）

两个口径的返回值都是「三态 + 读数」，不是布尔：

| 键 | 意思 |
|---|---|
| `checked` | 这一问查成了没有。`False` 不是「没有」，是「没查成」—— 调用方 fail-closed |
| `mode` | 走的是哪一条口径：`"id"` / `"keywords"`（读数里必须看得见「查了什么口径」） |
| `found` | 口径一：`True` / `False` / `None`（`None` = 没查成，不许读成「没有这一行」） |
| `hits` / `hits_total` | 命中几条（口径二每条带 `hit_words`：为什么这条进来） |
| `scanned` | 在多少行里找的（0 命中与没读到必须在这个数上分得开） |
| `matched_by` | 这一问的匹配规则（人话），让「两把尺」在读数上认得出来 |
| `why` / `reason` | 一句话说清「凭什么」/「为什么没查成」 |

被引面那一格（`cited_by`，读的是另一张表）另有四个键：

| 键 | 意思 |
|---|---|
| `found` | 被引条数（int）；`None` = 没查成。0 不是「没人引」，`None` 也不是。它数的是引用条数（依赖行），引用方个数另看 `citers_total`（详见 `cited_by` 的 docstring 那个「3 条引用 / 2 个引用方」的例子） |
| `citations` | 每条一条：`dep_id` / `used_by` / `citer_stmt_id` / `proof_no` / `kind` / `label` / `status` / `created_at` / `path_group` / `used_by_problem` |
| `by_status` | 按 `dependencies.status` 计数（`closed` / `dangling` / `refuted` / `disputed` …）；「那一行后来作废了」在这里看得见，但不被折成「没人引」 |
| `citers` | `used_by` 的去重集合（逐字，含 `#pN` 尾巴；同一个命题的另一条路径是另一个 `used_by`） |
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from . import schema as S
from . import proofloc as PL
from . import textutil as T

#: 口径一：按编号查（读数的 `mode`）。
MODE_ID = "id"
#: 口径二：按内容关键字查（读数的 `mode`）。
MODE_KEYWORDS = "keywords"
#: 被引面（反向读 `dependencies`；读数的 `mode`）。它不是第三种查口径，见模块 docstring。
MODE_CITED_BY = "cited_by"

#: 口径一的匹配规则（一句话；进读数 `matched_by`）。
MATCHED_BY_ID = "stmt_id 逐字相等（不过滤 kind / status）"
#: 口径二的匹配规则（一句话；进读数 `matched_by`）。
MATCHED_BY_KEYWORDS = "label / statement_full 经 textutil.normalize 后包含任一关键词"
#: 被引面的匹配规则（一句话；进读数 `matched_by`）。
MATCHED_BY_CITED_BY = "source_stmt_id 逐字相等（被引方 = 这一条；引用方 = 该行的 used_by）"

#: 命题台账那本账（取数口的默认表）。
TABLE_STATEMENTS = "statements"
#: 依赖账：`source_stmt_id` 是被引方、`used_by` 是引用方 —— 被引面就住在这里
#: （`schema.Dependency` 的 `used_by` / `source_stmt_id`）。
TABLE_DEPENDENCIES = "dependencies"

#: 取数口的三种来源（进读数 `source`，让「查的是哪一份快照」可复核）。
SOURCE_ROWS = "rows"
SOURCE_STORE = "store"
SOURCE_TX = "tx"

#: 「我方自己得的那一条」必须写清的那两格来路 —— 两格至少一个非空（业主 2026-11-17 真机缺陷 ②）。
#:
#: 为什么是这两格：`origin="own_result"` 的命题是我们提出并证明的，它不欠外部出处
#: （那是 `external_lit` 的事），但它欠「它由什么推出来」：要么是承重链
#: （`derived_from`：它用了哪几条已登记的命题），要么是一篇文献
#: （`source_lit_id`：这一条是从哪篇论文的结论推出来的）。两格都空 ⇒ 读的人无法复核
#: 「这条命题是天上掉下来的，还是我们真的推出来的」—— 而 2026-11-17 `projects/lp-ball-3`
#: 现场正是这个形态：33 行命题里 3 行 `origin=own_result`，`derived_from` 与
#: `source_lit_id` 全空，收工门的 `acceptance` 因此红（`blocker=acceptance_unmet`）。
#:
#: 判据只有这一处（:func:`own_result_basis_missing`）：写入口（B 的登记）与读口
#: （收工门的「造」那一环）读同一份，两处不再各写一遍"有没有来路"。
OWN_RESULT_BASIS_FIELDS: tuple[str, ...] = ("derived_from", "source_lit_id")

#: 不用来路的那几档 `kind`：概念行的"来路"就是它自己的定义（`conceptrows` 的口径），
#: 给它要承重链 / 文献出处等于让 B 编一个。C 与 D 的判据都不读概念行的这一格。
OWN_RESULT_BASIS_EXEMPT_KINDS: tuple[str, ...] = ("concept",)


def own_result_basis_missing(*, origin: Any, derived_from: Any = (),
                             source_lit_id: Any = "",
                             kind: Any = "") -> list[str]:
    """`origin="own_result"` 那一笔缺哪一格来路 ⇒ 缺的字段名（空列表 = 齐了、放行）。

    判据（业主 2026-11-17 逐字）：「`origin=own_result` ⇒ `derived_from` 与
    `source_lit_id` 至少一个非空，否则受控拒（给出可执行的下一步：写清它由哪几条
    已登记命题 / 哪篇文献推出）」。所以：

    - `origin` 不是 `own_result` ⇒ 这一问不适用（`[]`，其他来源的判据各自管各自）；
    - `kind` 在 :data:`OWN_RESULT_BASIS_EXEMPT_KINDS` 里（概念行）⇒ `[]`；
    - 两格都空 ⇒ `["derived_from", "source_lit_id"]`（逐条点名，不只说"缺凭据"）；
    - 任一非空 ⇒ `[]`（照旧放行）。

    纯函数、不读盘：写入口拿它拦在写库之前，收工门拿它判"这一行有没有来路"，
    两处说同一句话（`closing._check_acceptance` 的「造」那一环）。
    """
    if str(origin or "") != "own_result":
        return []
    if str(kind or "").strip().lower() in OWN_RESULT_BASIS_EXEMPT_KINDS:
        return []
    chain = [str(x) for x in (derived_from or ()) if str(x).strip()] \
        if isinstance(derived_from, (list, tuple, set)) else []
    if chain:
        return []
    if str(source_lit_id or "").strip():
        return []
    return list(OWN_RESULT_BASIS_FIELDS)


def own_result_basis_refusal(missing: Sequence[str]) -> str:
    """把 :func:`own_result_basis_missing` 的结论翻成一条可执行的拒信（只有这一处措辞）。

    为什么单独成函数：模型可见的那句话与写入口的判据必须逐字同源 —— 判据说"缺哪一格"，
    拒信就得点名同一格；分成两处写，改一处就会让"拒信指的路"与"闸真正要的"漂开。

    三件事缺一不可（照 `policy.REFUSAL_SLOTS` 的四样口径写）：判定（缺哪几格、现算）、
    正路（补哪一格、填什么）、前提（自产不等于无源）。窗口按 400 字（模型真正看到的是
    `_clip(detail, 400)`）—— 这一句连插值在内 300 出头，整条在窗口内。
    """
    cells = "、".join(f"`{one}`" for one in (missing or OWN_RESULT_BASIS_FIELDS))
    return (
        "origin='own_result' 的命题必须写清来路，而这一笔 "
        + cells + " 都是空的 ⇒ 整笔不写（不进 statements）。"
        "正路：补齐只要给一格 —— ① `derived_from`：它由哪几条已登记命题推出，"
        "填 `stmt_id` 列表（例如 [\"000000\", \"000003\"]）；"
        "② `source_lit_id`：它从哪篇文献的结论推出，填 `lit_id`。"
        "前提：自产不等于无源 —— 说不出它派生于什么，读的人就无法复核这一条。")


def _source_label(source: Any, rows: Any) -> str:
    """这一问读的是哪一种来源（读数用；不参与判据）。"""
    if rows is not None:
        return SOURCE_ROWS
    if source is None:
        return ""
    name = type(source).__name__
    if name == "Tx":
        return SOURCE_TX
    if name == "Store":
        return SOURCE_STORE
    return name


def rows_of(source: Any = None, *, rows: Iterable[Mapping[str, Any]] | None = None,
            table: str = TABLE_STATEMENTS
            ) -> tuple[list[dict[str, Any]] | None, str, dict[str, str]]:
    """唯一取数口：`store` / `tx` / 显式 `rows` ⇒ 一批台账行。

    三态：`(行, "", {})` = 读成了（可能是空表：那是「查过、0 行」）；
    `(None, 理由, {"type": …, "message": …})` = 读不成（不是「0 行」）。

    第三格是那一趟异常的原文（`{}` = 没有异常）：调用方要保留自己的那句
    「读不出来（X: msg）⇒ 这一格没查成」时靠它拼，不必各写一份 try/except。

    `rows=` 优先：调用方已经有一份快照（例如事务里 `tx.rows("statements")`）时，
    这一层不再读第二次 —— 一次登记里读两遍整表会拿到两个瞬间的行。

    `table` 只有两个落点：`statements`（两种查口径与被引面判「在册」时读）与
    `dependencies`（被引面自己读的那本账）。默认 `statements` ⇒ 既有调用点的
    行为与那句话逐字不变；加这一格是因为「同一份 try/except 写两遍」正是本模块
    要消灭的第二种实现（被引面不许自己再扫一遍依赖表）。
    """
    if rows is not None:
        return [dict(r) for r in rows if isinstance(r, Mapping)], "", {}
    if source is None:
        return None, ("没给台账（`store` / `tx` / `rows=` 三样都没有）⇒ 这一问没查成"
                      "（不是「台账里没有这一行」，也不是「0 行」）"), {}
    reader = getattr(source, "rows", None)
    if not callable(reader):
        return None, (f"给的来源没有 `rows(table)` 读法（{type(source).__name__}）"
                      "⇒ 这一问没查成（不是「台账里没有这一行」）"), {}
    try:
        got = reader(str(table))
    except Exception as exc:  # noqa: BLE001 —— 读不到 ⇒ 没查成（不是「没有」）
        return (None,
                (f"`{table}` 台账读不出来（{type(exc).__name__}: {exc}）"
                 "⇒ 这一问没查成（不是「台账里没有这一行」，也不是「0 行」）"),
                {"type": type(exc).__name__, "message": str(exc)})
    return [dict(r) for r in (got or ()) if isinstance(r, Mapping)], "", {}


# ---------------------------------------------------------------- 口径一：按编号


def by_id(source: Any = None, *, stmt_id: Any, rows: Iterable[Mapping[str, Any]] | None = None
          ) -> dict[str, Any]:
    """口径一：按编号查一行（主键逐字相等；不过滤 kind / status）。

    业主：「查必须明确有两种口径」。这一条是「按编号」那一条：

    - 它是确定性事实：命中就是那一行，0 命中就是「台账里没有这一行」；
    - 它不做任何过滤：编号指的是那一行本身，不是「active 的那一行」。
      放弃、被取代、概念行、待补定义的行，只要能按号指到，就返回它 ——
      要不要排除由调用方按自己的判据决定（`found` 与「可不可用」是两根轴）；
    - 「读不到台账」不等于「没有这一行」：此时 `checked=False`、`found=None`、
      `reason` 写明没查成。把这两档折平，上游就会把一次 I/O 故障读成「这条命题
      不存在」，然后照常新建一条重复的。

    返回（键无条件存在；没查成由 `checked` 说，不靠少给键）：

    | 结局 | 返回 |
    |---|---|
    | 命中 | `checked=True` + `found=True` + `hits_total=1` + `row=<整行副本>` |
    | 查过、没有 | `checked=True` + `found=False` + `hits_total=0` + `row={}` + `why` 写明扫了几行 |
    | 没查成 | `checked=False` + `found=None` + `hits_total=0` + `reason`（台账读不出来 / 没给号） |
    """
    sid = str(stmt_id or "").strip()
    out: dict[str, Any] = {
        "checked": False, "mode": MODE_ID, "stmt_id": sid, "found": None,
        "hits_total": 0, "row": {}, "scanned": 0,
        "source": _source_label(source, rows), "matched_by": MATCHED_BY_ID,
        "why": "", "reason": "", "error": {},
    }
    if not sid:
        why = ("没给编号（或给的是空白）⇒ 按编号查这一问不成立"
               "（不是「台账里没有这一行」）")
        out.update(why=why, reason=why)
        return out
    got, problem, error = rows_of(source, rows=rows)
    if problem:
        out.update(why=problem, reason=problem, error=dict(error))
        return out
    out["scanned"] = len(got)
    out["checked"] = True
    for row in got:
        if str(row.get("stmt_id") or "") == sid:
            out.update(found=True, hits_total=1, row=dict(row),
                       why=f"按主键逐字相等命中 stmt:{sid}（在 {len(got)} 行里找的）")
            return out
    out.update(found=False,
               why=(f"查过：台账里没有编号 {sid} 这一行"
                    f"（在 {len(got)} 行里逐字比过；这是确定性事实，不是「可能漏了」）"))
    return out


# ---------------------------------------------------------------- 口径二：按内容关键字


def by_keywords(source: Any = None, *,
                keywords: str | Sequence[str],
                rows: Iterable[Mapping[str, Any]] | None = None,
                text_chars: int | None = None) -> dict[str, Any]:
    """口径二：按内容关键字查（`label` / `statement_full` 归一后包含；多词任一命中）。

    ## 匹配规则（业主口径，逐字搬自 `_statements_matching_keywords`）

    `label` 或 `statement_full` 里「包含」该关键词；大小写 / 全半角 / 标点按
    `textutil.normalize` 归一。多关键词任一命中即进候选，并记下命中的词
    （每条 `hit_words` —— 这就是「为什么这条命中」）。排序按命中词数降序、
    同分按号升序 —— 只是展示顺序，不参与判定；词面相似度也不进这一格
    （业主：「检索只是取候选，不参与判定」）。

    ## 它查的是「你给的那批行」

    不给 `rows=` 就用台账全表（`scanned` 如实记有多少行）。要只查 active 命题
    （判同一性那一档），调用方自己 `rows=pool(rows, kinds=PROPOSITION_KINDS)`：
    「查哪一批」是语义决定，本模块不替你选（见模块 docstring 的「池归调用方」）。

    ## 0 命中不等于「不在册」

    这是它与口径一最要紧的差别（模块 docstring 第二节已展开）：同义词、记号差异、
    换了行文都会漏。所以 0 命中时 `checked=True` + `hits_total=0` + `why` 明写
    「命中 0 条」，不许任何调用方把它读成「台账里没有这一条」。

    `text_chars` 给了就按它截断每条命中的 `statement_full`（判定那一趟的篇幅约束
    由调用方传：1200 字住在 `secretary.PROPOSITION_VERDICT_TEXT_CHARS`，本模块
    不复制这个数）；不给则原样返回（`hits[i]["row"]` 里本来就是整行）。
    """
    out: dict[str, Any] = {
        "checked": False, "mode": MODE_KEYWORDS, "keywords": [], "hits": [],
        "hits_total": 0, "scanned": 0, "checked_rows": 0,
        "source": _source_label(source, rows), "matched_by": MATCHED_BY_KEYWORDS,
        "why": "", "reason": "", "error": {},
    }
    wanted = T.normalized_keywords(keywords)
    out["keywords"] = [raw for raw, _norm in wanted]
    if not wanted:
        why = ("没给可用的关键词（一个都没有，或归一化后全是空）⇒ 按关键字查这一问"
               "不成立（不是「台账里没有」）")
        out.update(why=why, reason=why)
        return out
    got, problem, error = rows_of(source, rows=rows)
    if problem:
        out.update(why=problem, reason=problem, error=dict(error))
        return out
    out["scanned"] = len(got)
    out["checked_rows"] = len(got)
    out["checked"] = True
    # 惰性：证明清单的唯一读口径（`verifications.proof_list`），与既有实现同一处。
    from . import verifications as VR

    limit = None if text_chars is None else max(0, int(text_chars))
    hits: list[dict[str, Any]] = []
    for row in got:
        sid = str(row.get("stmt_id") or "")
        if not sid:
            continue
        label = str(row.get("label") or "")
        full = str(row.get("statement_full") or "")
        hit_words = T.matched_keywords([label, full], wanted)
        if not hit_words:
            continue
        hits.append({"stmt_id": sid, "label": label,
                     "kind": str(row.get("kind") or ""),
                     "statement_full": full if limit is None else full[:limit],
                     "hit_words": hit_words,
                     "proof_nos": [int(no) for no, _t in VR.proof_list(row)],
                     "row": dict(row)})
    hits.sort(key=lambda item: (-len(item["hit_words"]), item["stmt_id"]))
    out["hits"] = hits
    out["hits_total"] = len(hits)
    if hits:
        out["why"] = (f"查过：{len(got)} 行里命中 {len(hits)} 条"
                      f"（关键词 {'、'.join(out['keywords'])}；按命中词数降序、同分按号升序）")
    else:
        out["why"] = (f"查过：关键词 {'、'.join(out['keywords'])} 在 {len(got)} 行里"
                      "命中 0 条（那是「这批词没命中」，不是「台账里没有」）")
    return out


# ---------------------------------------------------------------- 被引面（反向读依赖账）


def _cited_by_one(row: Mapping[str, Any]) -> dict[str, Any]:
    """一条依赖行 ⇒ 被引面的一条引用读数（键恒定，缺的格给空值）。

    `status` 刻意是依赖行的 `dependencies.status`（`closed` / `dangling` /
    `external_unavailable` / `refuted` / `disputed`），不是被引命题自己的
    `statements.status`：这一面读的是「某一条引用边」，不是「那一条命题现在还成不成立」。
    将来要看「作废的引用」的人，据此按 `status` 分流即可（`by_status` 已先数好）。

    `used_by` 的 `#pN` 尾巴走 `proofloc.parse_used_by_checked`（全仓唯一解析点）：
    坏尾巴不折成 canonical，原文进 `used_by_problem` —— 留痕比"读成一个看起来
    像的号"更重要（那也是 `proofloc` 对全仓的承诺）。坏尾巴那一档不给
    `citer_stmt_id`：`#pabc` 不是路径号，硬折成 1 就等于替它编一个号。
    """
    used = str(row.get("used_by") or "")
    head, proof_no, problem = PL.parse_used_by_checked(used)
    kind_of_citer = head.split(":", 1)[0].strip() if ":" in head else ""
    #: 引用方的命题号：只有干净尾巴的 `stmt:` 那一类引用方才有（`doc:` / `experiment:`
    #: 没有命题号，留空串 —— 不许把 `doc:0001` 的 `0001` 冒充成一条命题；尾巴读不懂
    #: 时留空串 + 原文进 `used_by_problem`，不猜）。
    citer_stmt_id = (head.split(":", 1)[-1].strip()
                     if (kind_of_citer == "stmt" and not problem) else "")
    return {
        "dep_id": str(row.get("dep_id") or ""),
        "used_by": used,
        "used_by_head": head,
        "used_by_problem": problem,
        "citer_kind": kind_of_citer,
        "citer_stmt_id": citer_stmt_id,
        "proof_no": int(proof_no),
        "kind": str(row.get("kind") or ""),
        "label": str(row.get("label") or ""),
        "status": str(row.get("status") or ""),
        "created_at": str(row.get("created_at") or ""),
        "path_group": int(row.get("path_group") or 1),
    }


def cited_by(source: Any = None, *, stmt_id: Any,
             rows: Iterable[Mapping[str, Any]] | None = None
             ) -> dict[str, Any]:
    """被引面：谁引用了 `stmt_id` 这一条（反向读 `dependencies`，只读、零模型）。

    ## 它是怎么派生的

    一条依赖行里：`source_stmt_id` 是被引方、`used_by` 是引用方。所以

        cited_by(A) = [行 for 行 in dependencies if 行.source_stmt_id == A]

    这条读数没有自己的写侧：B 登记时先拿号、再按那个号写 `used_by="stmt:<号>"`
    与 `source_stmt_id`，两个格子同时落表 ⇒ 一录完就能在这里读到。反过来，任何
    "手工把号补进被引面"的做法都会造出第二份真相，本模块不做。

    ## 三态（`found` 的三档，绝不许折平）

    | 结局 | 返回 |
    |---|---|
    | 查成了、有人引 | `checked=True` + `found=N`（N≥1）+ `citations` 逐条 + `by_status` |
    | 查成了、没人引 | `checked=True` + `found=0` + `citations=[]`（这是「查过、0 条」） |
    | 没查成 | `checked=False` + `found=None` + `reason`（`dependencies` 读不出来 / 没给号） |

    `found=None` 与 `found=0` 必须是两句话：把它们折平，上游就会把一次 I/O 故障读成
    「这条命题没人引」，然后据此判它不承重（或干脆不再给它登记引用）。

    ## 带哪些格

    每条引用带 `used_by`（逐字，含 `#pN`）、`citer_stmt_id`（引用方命题号）、
    `proof_no`（路径号）、`kind` / `label` / `status` / `created_at`
    （依赖行的四格，与业主原话逐字对应）、`path_group`、`dep_id`；
    另有 `citers`（`used_by` 去重集合）与 `by_status`（按依赖行状态计数）——
    前者回答"谁引了我"，后者回答"这些引用里有没有后来作废/悬空的"。

    ## `found` 与 `citers_total` 是两个数（不是同一个数的两种写法）

    `found` / `hits_total` 数的是引用条数（依赖行）；`citers` / `citers_total`
    数的是引用方（`used_by` 去重）。“同一方引两次”与“两方各引一次”在依赖账里
    是两件事，读数必须分得开：

        某命题 A 的被引面，盘上有 3 条依赖行：
            used_by="stmt:000001"     （B 的第一条路径）
            used_by="stmt:000001#p2"  （B 的第二条路径）
            used_by="stmt:000007"     （C 的第一条路径）
        ⇒ found = 3（3 条引用），citers_total = 3（`stmt:000001` / `stmt:000001#p2` /
          `stmt:000007` 三个 used_by 逐字不同），而引用方命题只有 2 个（000001 / 000007）。
        要把"2 个引用方"读出来：`sorted({one["citer_stmt_id"] for one in citations})`
        —— 本模块不把 `#pN` 折掉（拆尾巴是 `proofloc` 的唯一职责，折平会让
        "另一条路径引了它"这件事实消失）。

    `rows=` 可以直接给一批依赖行快照（事务里 `tx.rows("dependencies")`）；
    不给就经唯一取数口读 `store` / `tx`。不读 `statements`：这一面不判在册、
    也不判等级（那是引用门的活），0 条只说"这本账里没有指向它的边"。
    """
    sid = str(stmt_id or "").strip()
    out: dict[str, Any] = {
        "checked": False, "mode": MODE_CITED_BY, "stmt_id": sid,
        "found": None, "hits_total": 0, "citations": [], "citers": [],
        "citers_total": 0, "by_status": {}, "scanned": 0,
        "source": _source_label(source, rows), "matched_by": MATCHED_BY_CITED_BY,
        "why": "", "reason": "", "error": {},
    }
    if not sid:
        why = ("没给编号（或给的是空白）⇒ 被引面这一问不成立"
               "（不是「没人引它」）")
        out.update(why=why, reason=why)
        return out
    got, problem, error = rows_of(source, rows=rows, table=TABLE_DEPENDENCIES)
    if problem:
        # 三态：表读不出来 ≠ 没人引。这句一定要带上，否则读数会被读成 0 条。
        why = problem + "（被引面这一格没查成：这不是「没人引它」）"
        out.update(why=why, reason=why, error=dict(error))
        return out
    out["scanned"] = len(got)
    out["checked"] = True
    citations = [_cited_by_one(row) for row in got
                 if str(row.get("source_stmt_id") or "") == sid]
    citations.sort(key=lambda one: (one["created_at"], one["used_by"], one["dep_id"]))
    out["citations"] = citations
    out["hits_total"] = len(citations)
    out["found"] = len(citations)
    out["citers"] = sorted({one["used_by"] for one in citations})
    out["citers_total"] = len(out["citers"])
    by_status: dict[str, int] = {}
    for one in citations:
        by_status[one["status"]] = by_status.get(one["status"], 0) + 1
    out["by_status"] = by_status
    if citations:
        out["why"] = (f"查过：{len(got)} 条依赖边里 {len(citations)} 条指向 stmt:{sid}"
                      f"（来自 {out['citers_total']} 个 used_by；"
                      "按 created_at 升序，同刻按 used_by / dep_id）")
    else:
        out["why"] = (f"查过：{len(got)} 条依赖边里没有一条的 source_stmt_id 是 {sid}"
                      "（0 条被引 —— 这是「查过、没人引」，不是「没查成」）")
    return out


# ---------------------------------------------------------------- 底座（不是口径）


def pool(rows: Iterable[Mapping[str, Any]], *,
         kinds: Iterable[str]) -> list[dict[str, Any]]:
    """可检索 / 可并池：active（跳过 `STATEMENT_UNUSABLE_STATUSES`）、命给定的 kind、
    有号、有正文。

    这是唯一一份池过滤实现（原样搬自 `Secretary._searchable_statement_rows`；
    它旁边那句注释自己写着「与 `_same_proposition_candidate` 逐字同源」）。
    `kinds` 由调用方给（命题那几档是 `secretary.PROPOSITION_KINDS`）—— 本模块
    不复制名单：名单加一个取值时，这里一个字都不用改。

    返回行副本（调用方拿去构造判定上下文，改它不污染台账缓存）。
    """
    want = {str(k or "").strip().lower() for k in (kinds or ())}
    keep: list[dict[str, Any]] = []
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        if not str(row.get("stmt_id") or "").strip():
            continue
        if str(row.get("kind") or "").strip().lower() not in want:
            continue
        if str(row.get("status") or "") in S.STATEMENT_UNUSABLE_STATUSES:
            continue
        if not str(row.get("statement_full") or "").strip():
            continue
        keep.append(dict(row))
    return keep


def index_by_id(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """全表 → `{号: 行}`（唯一一份；没有号的行跳过 —— 台账行没有号就没有身份）。

    调用方要号集合 / 号元组就自己套一层：`set(index)` / `tuple(index)`。
    """
    out: dict[str, dict[str, Any]] = {}
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        sid = str(row.get("stmt_id") or "")
        if not sid:
            continue
        out[sid] = dict(row)
    return out


def duplicate_hits(rows: Iterable[Mapping[str, Any]], *, text: Any) -> dict[str, Any]:
    """写入路径的查重判据：按 `statement_full` 的规范化值找在册行（不是查口径）。

    业主的口径「同一条正文已在册」就是这一句：`textutil.normalize`
    后逐字相等。它住在查口这一层只因为它也是「在台账里找行」，但它回答的
    不是「有哪些行提到了这件事」，而是「这一条正文是不是已经在册」——
    所以它不进两种口径，只给写入路径当判据用（`record_statement` 的老查重、
    B 的 `_existing_statement_for`、L 的 `claim_match`）。

    命中按台账物理顺序返回（不排序）：调用方自己判「0 条 = 不在册」「1 条 = 就是它」
    「N 条 = 认不出是哪一条」（`term` 那一档的三种处置各不相同，本模块不替它选）。
    """
    out: dict[str, Any] = {
        "checked": True, "mode": "text", "hits": [], "hits_total": 0, "scanned": 0,
        "matched_by": "statement_full 经 textutil.normalize 后逐字相等",
        "why": "", "reason": "",
    }
    key = T.normalize(str(text or ""))
    if not key:
        out.update(checked=False,
                   reason=("没给正文（或归一化后为空）⇒ 这一问不成立"
                           "（不是「不在册」）"),
                   why="没给可比的正文 ⇒ 没查成")
        return out
    got = [dict(r) for r in rows or () if isinstance(r, Mapping)]
    out["scanned"] = len(got)
    for row in got:
        if T.normalize(str(row.get("statement_full") or "")) == key:
            out["hits"].append(row)
    out["hits_total"] = len(out["hits"])
    out["why"] = (f"查过：{len(got)} 行里正文规范化后逐字相同的 {out['hits_total']} 条")
    return out
