# -*- coding: utf-8 -*-
"""命题台账的查口：两种口径，各自独立、各自带读数（只读、零模型调用、不写盘）。

## 先读这一节：这个模块管什么、不管什么

本模块是 B 秘书「增 / 改 / 查」三族里**查**那一族的实现，也是全仓**唯一**一处
「怎么在 `statements` 里找行」的实现。它只回答一个问题：**台账里有哪些行**。
它不回答「这两条是不是同一条命题」——那是判定，仍归 `secretary.Secretary.judge`
（唯一判定口）与 `secretary.Secretary.adjudicate_proposition`（检索 + 判定的唯一组合点）。

| 归本模块 | 不归本模块 |
|---|---|
| 按编号取一行（`by_id`） | 判同一性 / 判形态 / 判档位（`judge` 那一族） |
| 按内容关键字检索（`by_keywords`） | 挑关键词（`pick_statement_keywords`，一次模型调用） |
| 取数口、可检索池、全表索引、正文全等（底座） | 写台账（`record_statement` / `amend_statement_meta` / `land_statement`） |

三条硬边界：**不写盘、不开事务、不发模型调用**。前端要事务内的快照时，把 `tx`
传进来即可（`Store.rows` 与 `Tx.rows` 同一个 `rows(table)` 协议）；要自己给一批行时
传 `rows=`。三种来源走同一份实现，读数里 `source` 记的是哪一种。

## 两种口径为什么必须分开（不是两个函数名，是两件不同的事）

- **口径一（`by_id`）回答的是确定性事实**：编号就是主键，逐字相等就命中。
  所以它**不做任何过滤** —— 不按 `kind` 筛、不按 `status` 筛。理由有三条，
  每条都对着一个既有调用方：放弃命题那一支必须找得到 `abandoned` 的行
  （`statementabandon.apply_abandonment`）；V 的签档要读得到已签的行
  （`vsigns.sign_filing_reading`）；判「点名的那一条还可不可并」时，
  「读不到」与「读到了但状态不可并」必须是两句话（`Secretary._proposition_owner`
  把它们合在一条 fail-closed 原因里，但前提是它先读到了那一行）。
  0 命中 = **这一行不在台账里**（确定性）。

- **口径二（`by_keywords`）回答的是「有哪些行提到了这件事」**：匹配规则是
  `label` / `statement_full` 经 `textutil.normalize` 后**包含**任一关键词
  （全半角 / 大小写 / 标点归一，多词任一命中）。它**永远不能**把 0 命中当成
  「不在册」—— 同义词（「质数」/「素数」）、记号差异（`p^a` / `pᵃ`）、换了行文
  都会漏。今天唯一的正式用法就是这样读它的：0 命中 ⇒ 判 different，
  但读数里 `why` 明写「命中 0 条」，好让读的人知道那是「这批词没命中」而不是
  「台账里没有」（业主 2026-11-08：「检索只是取候选，不参与判定」）。

正因为这两条口径认识论上不同，**它们互不调用**：`by_id` 不用关键词、`by_keywords`
不用编号。判据 `tests/test_the_statement_ledger_has_two_ways_to_be_asked.py`
用**静态** AST 检查钉住这一点（不是靠运行时打桩），另外各有一条「把这一条口径降级
⇒ 依赖它的判据红」的反真空。

## 与工具层 `table.search` 的关系（两件事，别混）

通用表工具（`tools/table_tools.py` 的 `table.get` / `table.search`）搜的是**列文本**：
`casefold` 子串、对表里全部标量字符串字段（`statements` 实测 18 个，连 `status`、
`stmt_id` 都在扫描面里）。本模块是**命题语义面的查**：只比 `label` / `statement_full`，
用 `textutil.normalize`（与判重、查重同一把尺）。两者不是同一件事，也不许互相顶替：
同一个关键词在两处会给出不同命中。工具层那两条不在本模块的迁移范围（`table_tools.py`
在 `.noai-paths` 的 FC-27 禁改区，`auth-audit` 类，要 2 名 reviewer）；
**将来若拿到 FC-27 批准，`table.search` 在 `table="statements"` 上应委托 `by_keywords`**
—— 那是待办，不是已做（见 `temp/_todo_b_box_step4.md`）。

## 池（查哪一批）归调用方，不归本模块

「查哪一批」是语义决定，不是实现细节：判命题同一性要**active 命题**（跳概念行、
跳被否证/被取代的行），判概念同一性要**概念行**，收工读数是**全部行**。
把池焊死在查里，就是把这三种折平。所以：

- `by_id` / `by_keywords` 查的是**你给的那批行**（不给就用台账全表，`scanned` 如实记）；
- 要池就 `rows=pool(rows, kinds=…)` —— `pool` 是**唯一**一份池过滤实现；
- 那条 kind 名单（`secretary.PROPOSITION_KINDS`）与候选正文的截断长度
  （`secretary.PROPOSITION_VERDICT_TEXT_CHARS`）都由调用方传进来：本模块**不复制**
  这两份常量，也不给自己定新的阈值。

## 读数（三种结局必须分得开）

两个口径的返回值都是「三态 + 读数」，不是布尔：

| 键 | 意思 |
|---|---|
| `checked` | 这一问**查成了没有**。`False` 不是「没有」，是「没查成」—— 调用方 fail-closed |
| `mode` | 走的是哪一条口径：`"id"` / `"keywords"`（读数里必须看得见「查了什么口径」） |
| `found` | 口径一：`True` / `False` / `None`（`None` = 没查成，不许读成「没有这一行」） |
| `hits` / `hits_total` | 命中几条（口径二每条带 `hit_words`：**为什么**这条进来） |
| `scanned` | 在多少行里找的（0 命中与没读到必须在这个数上分得开） |
| `matched_by` | 这一问的匹配规则（人话），让「两把尺」在读数上认得出来 |
| `why` / `reason` | 一句话说清「凭什么」/「为什么没查成」 |
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from . import schema as S
from . import textutil as T

#: 口径一：按编号查（读数的 `mode`）。
MODE_ID = "id"
#: 口径二：按内容关键字查（读数的 `mode`）。
MODE_KEYWORDS = "keywords"

#: 口径一的匹配规则（一句话；进读数 `matched_by`）。
MATCHED_BY_ID = "stmt_id 逐字相等（不过滤 kind / status）"
#: 口径二的匹配规则（一句话；进读数 `matched_by`）。
MATCHED_BY_KEYWORDS = "label / statement_full 经 textutil.normalize 后包含任一关键词"

#: 取数口的三种来源（进读数 `source`，让「查的是哪一份快照」可复核）。
SOURCE_ROWS = "rows"
SOURCE_STORE = "store"
SOURCE_TX = "tx"


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


def rows_of(source: Any = None, *, rows: Iterable[Mapping[str, Any]] | None = None
            ) -> tuple[list[dict[str, Any]] | None, str]:
    """唯一取数口：`store` / `tx` / 显式 `rows` ⇒ 一批台账行。

    三态：`(行, "")` = 读成了（可能是空表：那是「查过、0 行」）；
    `(None, 理由)` = **读不成**（不是「0 行」）。

    `rows=` 优先：调用方已经有一份快照（例如事务里 `tx.rows("statements")`）时，
    这一层不再读第二次 —— 一次登记里读两遍整表会拿到两个瞬间的行。
    """
    if rows is not None:
        return [dict(r) for r in rows if isinstance(r, Mapping)], ""
    if source is None:
        return None, ("没给台账（`store` / `tx` / `rows=` 三样都没有）⇒ 这一问没查成"
                      "（不是「台账里没有这一行」，也不是「0 行」）")
    reader = getattr(source, "rows", None)
    if not callable(reader):
        return None, (f"给的来源没有 `rows(table)` 读法（{type(source).__name__}）"
                      "⇒ 这一问没查成（不是「台账里没有这一行」）")
    try:
        got = reader("statements")
    except Exception as exc:  # noqa: BLE001 —— 读不到 ⇒ 没查成（不是「没有」）
        return None, (f"`statements` 台账读不出来（{type(exc).__name__}: {exc}）"
                      "⇒ 这一问没查成（不是「台账里没有这一行」，也不是「0 行」）")
    return [dict(r) for r in (got or ()) if isinstance(r, Mapping)], ""


# ---------------------------------------------------------------- 口径一：按编号


def by_id(source: Any = None, *, stmt_id: Any, rows: Iterable[Mapping[str, Any]] | None = None
          ) -> dict[str, Any]:
    """口径一：按编号查一行（主键逐字相等；**不过滤** kind / status）。

    业主 2026-11-08：「查必须明确有两种口径」。这一条是「按编号」那一条：

    - 它是**确定性事实**：命中就是那一行，0 命中就是「台账里没有这一行」；
    - 它**不做任何过滤**：编号指的是那一行本身，不是「active 的那一行」。
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
        "why": "", "reason": "",
    }
    if not sid:
        why = ("没给编号（或给的是空白）⇒ 按编号查这一问不成立"
               "（不是「台账里没有这一行」）")
        out.update(why=why, reason=why)
        return out
    got, problem = rows_of(source, rows=rows)
    if problem:
        out.update(why=problem, reason=problem)
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

    ## 匹配规则（业主 2026-11-08 的口径，逐字搬自原 `_statements_matching_keywords`）

    `label` 或 `statement_full` 里「包含」该关键词；大小写 / 全半角 / 标点按
    `textutil.normalize` 归一。多关键词**任一**命中即进候选，并记下命中的词
    （每条 `hit_words` —— 这就是「为什么这条命中」）。排序按命中词数降序、
    同分按号升序 —— 只是展示顺序，**不参与判定**；词面相似度也不进这一格
    （业主：「检索只是取候选，不参与判定」）。

    ## 它查的是「你给的那批行」

    不给 `rows=` 就用台账**全表**（`scanned` 如实记有多少行）。要只查 active 命题
    （判同一性那一档），调用方自己 `rows=pool(rows, kinds=PROPOSITION_KINDS)`：
    「查哪一批」是语义决定，本模块不替你选（见模块 docstring 的「池归调用方」）。

    ## 0 命中不等于「不在册」

    这是它与口径一最要紧的差别（模块 docstring 第二节已展开）：同义词、记号差异、
    换了行文都会漏。所以 0 命中时 `checked=True` + `hits_total=0` + `why` 明写
    「命中 0 条」，**不许**任何调用方把它读成「台账里没有这一条」。

    `text_chars` 给了就按它截断每条命中的 `statement_full`（判定那一趟的篇幅约束
    由调用方传：1200 字住在 `secretary.PROPOSITION_VERDICT_TEXT_CHARS`，本模块
    不复制这个数）；不给则原样返回（`hits[i]["row"]` 里本来就是整行）。
    """
    out: dict[str, Any] = {
        "checked": False, "mode": MODE_KEYWORDS, "keywords": [], "hits": [],
        "hits_total": 0, "scanned": 0, "checked_rows": 0,
        "source": _source_label(source, rows), "matched_by": MATCHED_BY_KEYWORDS,
        "why": "", "reason": "",
    }
    raw_words = [keywords] if isinstance(keywords, str) else list(keywords or ())
    wanted = [(str(raw), T.normalize(str(raw))) for raw in raw_words]
    wanted = [(raw, norm) for raw, norm in wanted if norm]
    out["keywords"] = [raw for raw, _norm in wanted]
    if not wanted:
        why = ("没给可用的关键词（一个都没有，或归一化后全是空）⇒ 按关键字查这一问"
               "不成立（不是「台账里没有」）")
        out.update(why=why, reason=why)
        return out
    got, problem = rows_of(source, rows=rows)
    if problem:
        out.update(why=problem, reason=problem)
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
        label_n = T.normalize(str(row.get("label") or ""))
        full_n = T.normalize(str(row.get("statement_full") or ""))
        hit_words = [raw for raw, norm in wanted if norm in label_n or norm in full_n]
        if not hit_words:
            continue
        full = str(row.get("statement_full") or "")
        hits.append({"stmt_id": sid, "label": str(row.get("label") or ""),
                     "kind": str(row.get("kind") or ""),
                     "statement_full": full if limit is None else full[:limit],
                     "hit_words": hit_words,
                     "proof_nos": [int(no) for no, _t in VR.proof_list(dict(row))],
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


# ---------------------------------------------------------------- 底座（不是口径）


def pool(rows: Iterable[Mapping[str, Any]], *,
         kinds: Iterable[str]) -> list[dict[str, Any]]:
    """可检索 / 可并池：active（跳过 `STATEMENT_UNUSABLE_STATUSES`）、命给定的 kind、
    有号、有正文。

    这是**唯一**一份池过滤实现（原样搬自 `Secretary._searchable_statement_rows`；
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
    """写入路径的查重判据：按 `statement_full` 的规范化值找在册行（**不是查口径**）。

    业主 2026-10-24 的老口径「同一条正文已在册」就是这一句：`textutil.normalize`
    后逐字相等。它住在查口这一层只因为它也是「在台账里找行」，但它回答的
    **不是**「有哪些行提到了这件事」，而是「这一条正文是不是已经在册」——
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
