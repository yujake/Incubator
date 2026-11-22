# -*- coding: utf-8 -*-
"""SYSRESIDUE：系统自动产物剩下四个写点的校验与读数。

## 这一层补的是什么

`SYSGUARD` 那份普查列了 20 项系统自动产物，封了 5 处写点，剩下四处只报不改
（`temp/sysguard/REPORT.md` 的 ③ 表）。本模块就是那四处：

| # | 产物 / 格 | 写点 | 本模块给的判据 |
|---|---|---|---|
| ① | `literature.processed` | `agent_b/run_once.py` 的三处（跳过两档 + 抽完那档） | `settle_processed`：`processed=True` 必须带一条可回读的理由（跳过档是 `last_mine_error`，抽完档是 `mine_attempts` + `download.fulltext`） |
| ② | `bits.evidence.optimized_by_proof` | `evidencebits.with_optimized_flag` / `with_optimized_defaults` 造表，`schema.Statement.validate` 把关 | `optimized_cells_problems`：表必须是"证明号 ⇒ 布尔"，且 `true` 必须带同号的签凭据 |
| ③ | `runs` 的 `spend` 自报 | `agent_loop.run()` 收工前那一处 | `spend_reconcile`：自报 vs 账本 vs 会话事件三个数并排（只读数，不改自报） |
| ④ | `literature.dedup_key` | `agent_a/run_once.py` / `locallib.py` / `tools/search_tools.py` | `literature_dedup_cells`：三处都走同一处算；`dedup_cells_problems`：主键必须在本行键集里 |

## 它守的是 SYSGUARD 同一条纪律

SIGNMAL 的形态不是"某一格写错了"，而是"写口漏写之后没有人拦"：行照样落盘、
读侧照样放行、下游读数照旧自洽。这四处是同一个形态在另一批写口上的残留 ——
所以每一处的处置都必须是写点自己判（受控拒或同处补值），不靠读侧宽容。

## 读数形状不另造（复用 `sysguard`）

拒绝 / 补值的读数一律走 `sysguard.refused` / `sysguard.derived` /
`sysguard.unchecked`，台账是 `out/sysguard/write-readings.jsonl`，
`errorstats` 把它们数进过程读数类目 `write_point_guarded`（不进错误合计、
不当门 —— 业主口径是"畸形要看得见"，不是再拦一道）。

三态：读不到 ⇒ `unchecked`，绝不折成"没问题"。

## 两处刻意的"不补"

- `spend` 的自报值一个字节都不改：那是模型/框架的账，写点只给第二个读数；
- `optimized_by_proof` 的 `{}` 与缺键不判：`OPTIMIZED_STATES` 把"这一行还没有
  这一格"定成合法初态（`not_recorded`），拒它就是让存量行全部拒写。这里只拒
  "形状不对"与"空口说 true" —— 前者读不出来，后者读侧必须替它拆弹。
"""

from __future__ import annotations

from typing import Any, Mapping

from . import sysguard as SG

__all__ = [
    "CODE_DEDUP_KEY_MISSING",
    "CODE_OPTIMIZED_BAD_TABLE",
    "CODE_PROCESSED_REASON_DERIVED",
    "CODE_PROCESSED_WITHOUT_EVIDENCE",
    "CODE_SPEND_MISSING",
    "CODE_SPEND_UNCHECKED",
    "CODE_SPEND_UNRECONCILED",
    "DEDUP_POINT",
    "OPTIMIZED_POINT",
    "PROCESSED_POINT",
    "SKIP_PROCESSED_REASONS",
    "SPEND_POINT",
    "dedup_cells_problems",
    "literature_dedup_cells",
    "note_dedup_refusal",
    "note_reading",
    "optimized_cells_problems",
    "processed_evidence_problems",
    "processed_reason",
    "record_spend_reading",
    "settle_processed",
    "skip_reason",
    "spend_reconcile",
]

#: 四个写点在读数里的名字（`sysguard` 台账的 `point` 列）。
PROCESSED_POINT = "agent_b.run_once.literature.processed"
OPTIMIZED_POINT = "evidencebits.bits_shape_problems.optimized_by_proof"
SPEND_POINT = "agent_loop.run.spend"
DEDUP_POINT = "literature.dedup_key"

#: 为什么这一篇算处理完了（受控理由码；读数与拒信都用它）。
CODE_PROCESSED_WITHOUT_EVIDENCE = "literature_processed_without_evidence"
CODE_PROCESSED_REASON_DERIVED = "literature_processed_reason_derived"
CODE_OPTIMIZED_BAD_TABLE = "optimized_by_proof_bad_table"
CODE_SPEND_UNRECONCILED = "spend_usd_unreconciled"
CODE_SPEND_MISSING = "spend_usd_missing"
CODE_SPEND_UNCHECKED = "spend_usd_unchecked"
CODE_DEDUP_KEY_MISSING = "literature_dedup_key_missing"

#: 跳过档的必填理由：分支名 ⇒ 那一句人话。
#:
#: 为什么按分支写死而不是让调用方自由拼：这三档的 `last_mine_error` 此前是各写
#: 一句（同一件事三种措辞），于是"这一篇为什么算处理完"在读侧只能靠猜。
#: 分支名是写点自己知道的事实，理由由它给出，调用方只说细节。
SKIP_PROCESSED_REASONS: dict[str, str] = {
    "extract_failed": ("availability=extract_failed: 抽过但失败（乱码/无文本层）"
                       "⇒ 不再自动重抽；要重试请先用 `text.extract` 重判这一条的可读性"),
    "content_mismatch": ("content_type_mismatch: 盘上那一份按内容类型不是论文"
                         "（例如落地页 HTML 被存成 PDF）⇒ 这一趟不抽"),
    "metadata_only": ("availability=metadata_only; no_local_file: "
                      "这一行只登记了题录、没有本地字节（要按 `download.url` 重取）"),
    "file_missing": ("availability=file_missing: 两个基准下都没有这一份文件"
                     "（先 `library/`、再工作区；两个候选绝对路径见这一行的 `path`）"),
}

#: 分支名都不认识时的兜底句（非空：宁可说"按分支补了一句"，也不留空串）。
FALLBACK_PROCESSED_REASON = ("processed: 这一篇在本趟被标为已处理，"
                             "而写点没有拿到具体理由（按分支名补的一句，分支见 `stage` 读数）")

#: 差额判据的容差（美元）。账上的数一律四舍五入到 6 位，所以 1e-6 是"同一个数"。
_SPEND_EPS = 1e-6


def note_reading(root: Any, one: SG.WriteReading) -> str:
    """记一条写点读数；返回没记成的问题（空 = 记成了）。

    与 `sysguard.record_reading` 的分工：那一处只管写文件，这一处管"没有根时
    不抛"——写点是判据，留痕失败不许把判据的结论换掉（与 `artifacts` 同一纪律）。
    """
    if root is None or str(root).strip() == "":
        return "写点读数没记成：没有工作区根（这一条只留在返回值里）"
    _row, problem = SG.record_reading(root, one)
    return problem


# ===================================================== ① literature.processed

def skip_reason(branch: str) -> str:
    """跳过档的标准理由（按分支查表；分支名不认识也给一句非空的话）。

    写点在正常路径上用这个函数取得"这一篇为什么算处理完"，写点的兜底也用它 ——
    于是理由的措辞只有一张表。`processed_reason` 是它加上"调用方给了细节就用细节"。
    """
    known = SKIP_PROCESSED_REASONS.get(str(branch or ""))
    return known or FALLBACK_PROCESSED_REASON


def processed_reason(branch: str, detail: str = "") -> str:
    """跳过档的必填理由：调用方给了细节就逐字用，没给就按分支补一句。

    补值只在这里发生（写点唯一的一处）。"逐字用"这一档保证正常路径一个字节都不变：
    三处写点原来写的那几句话由调用方作为 `detail` 传进来。
    """
    text = str(detail or "").strip()
    if text:
        return text
    return skip_reason(branch)


def processed_evidence_problems(row: Mapping[str, Any], *, mined: bool) -> list[str]:
    """这一行要以 `processed=True` 落盘时，它的"为什么"够不够。

    两条证据取其一，与写点自己的分支一一对应：

    - 跳过档（`mined=False`）：`last_mine_error` 非空 —— 那一格就是"这一篇为什么
      没抽 / 抽败"的唯一落点；
    - 抽完档（`mined=True`）：`mine_attempts >= 1` 且 `download.fulltext` 在四档
      词表里 —— 前者是"真抽过"的计数，后者是这一趟对盘上字节的机器读数。
      抽完档刻意不看 `last_mine_error`：那一格在成功行上必须是 None（语义是
      "为什么没抽成"），拿它当"处理完了"的证据等于把两个相反的意思塞进一格。
    """
    if not row.get("processed"):
        return []
    problems: list[str] = []
    if mined:
        try:
            attempts = int(row.get("mine_attempts") or 0)
        except (TypeError, ValueError):
            attempts = 0
        if attempts < 1:
            problems.append(
                "抽完档没有 `mine_attempts >= 1`（这一格是'真的调过抽取器'的计数）"
                "⇒ 这一行说不出它凭什么叫处理完")
        download = row.get("download")
        tier = dict(download).get("fulltext") if isinstance(download, Mapping) else None
        from . import litread as _LR   # 惰性：词表只有一个真身

        if tier not in _LR.FULLTEXT_TIERS:
            problems.append(
                f"`download.fulltext` 读到 {tier!r}，不在四档 {list(_LR.FULLTEXT_TIERS)} 里"
                "⇒ 这一趟对盘上字节的机器读数没有落下来")
        return problems
    if not str(row.get("last_mine_error") or "").strip():
        problems.append("跳过档的 `last_mine_error` 是空的：这一行没有说它为什么算处理完")
    return problems


def settle_processed(row: dict, *, branch: str, mined: bool, detail: str = "",
                     where: str = "", root: Any = None) -> list[str]:
    """把 `processed` 那一格落定：先补理由，再判证据，坏的记读数。

    返回问题列表：空 = 可以按 `processed=True` 写下去；非空 = 受控拒
    （调用方必须把 `row["processed"]` 留在 False —— 这一行会留在队列里等下一轮，
    而不是像真机 `lp-ball-15` 的 `lit:000018` 那样永远 false 又永远不会被重领）。

    受控拒只拒"这一篇算处理完"这一格，不拒整行：领取与租约仍然照原样清掉，
    否则这一行会卡在别人手里，而卡住比漏一格更难查。
    """
    if not mined:
        before = str(row.get("last_mine_error") or "")
        given = str(detail or before).strip()
        reason = processed_reason(branch, given)
        if reason:
            row["last_mine_error"] = reason
        if reason and reason != given:
            note_reading(root, SG.derived(
                PROCESSED_POINT, code=CODE_PROCESSED_REASON_DERIVED, where=where,
                detail=f"跳过档 {branch}: 理由为空 ⇒ 写点按分支补了一句",
                how_to_fix=("调用方写这一行时把'为什么算处理完'写进 `last_mine_error`；"
                            "写点只兜底，不替它编细节")))
    problems = processed_evidence_problems(row, mined=mined)
    if problems:
        note_reading(root, SG.refused(
            PROCESSED_POINT, code=CODE_PROCESSED_WITHOUT_EVIDENCE, where=where,
            detail="；".join(problems),
            how_to_fix=("跳过档把理由写进 `last_mine_error`；抽完档在同一个事务里把"
                        " `mine_attempts` 加一、并用 `litread.with_fulltext` 落档位。"
                        "两样都缺时这一行不许翻 `processed`（下一轮会重领它）")))
    return problems


# ========================================== ② bits.evidence.optimized_by_proof

def _proof_table(bits: Mapping[str, Any]) -> Any:
    """`optimized_by_proof` 那一格的原值（正位是 `bits.evidence`，兼容顶层旧写）。"""
    from . import evidencebits as _EB

    evidence = bits.get("evidence")
    if isinstance(evidence, Mapping) and _EB.OPTIMIZED_BY_PROOF_KEY in evidence:
        return evidence.get(_EB.OPTIMIZED_BY_PROOF_KEY)
    return bits.get(_EB.OPTIMIZED_BY_PROOF_KEY)


def optimized_cells_problems(bits: Mapping[str, Any] | None) -> list[str]:
    """`optimized_by_proof` 这一格的写点判据（只判形状，正反两种谎都拒）。

    三件事，全部在写侧判：

    1. 给了这一格就必须是对象（`False` / `None` / 字符串都拒 —— 读侧会把它们
       静默读成 `not_recorded`，与"存量行没有这一格"长得一模一样）；
    2. 键必须是证明号（`as_proof_no >= 1`；`"abc"` / `"0"` 读侧会悄悄跳过）；
    3. 值必须是布尔（`"true"` / `1` / `"yes"` 都拒：读侧按 `bool(value)` 归一，
       而 `"false"` 会被读成 True —— "没洗"变"洗过"）。

    刻意不判的两件：

    - `{}` 与缺键：`OPTIMIZED_STATES` 把"这一行还没有这一格"定成合法初态
      （`not_recorded`），拒它就是让存量行全部拒写；
    - `true` 有没有同号的签：那是 `_optimized_gate`（写侧）与
      `optimized_standing`（读侧）的判据，本函数不抢它的结论 —— 抢了会让那条
      判据的反真空判据（打桩掉 gate 之后应当复现旧的静默形态）无法复现。
    """
    if not bits or not isinstance(bits, Mapping):
        return []
    from . import evidencebits as _EB
    from . import verifications as _VR

    problems: list[str] = []
    table = _proof_table(bits)
    if table is None:
        return []
    if not isinstance(table, Mapping):
        return [f"`bits.evidence.{_EB.OPTIMIZED_BY_PROOF_KEY}` 必须是对象"
                f"（证明号 ⇒ 布尔），收到 {type(table).__name__} {table!r}"
                f"（码 {CODE_OPTIMIZED_BAD_TABLE}）：读侧会把它静默读成"
                f" `not_recorded`，与'存量行没有这一格'同形"]
    bad_keys = sorted(str(k) for k in table if _VR.as_proof_no(k) < 1)
    if bad_keys:
        problems.append(f"`{_EB.OPTIMIZED_BY_PROOF_KEY}` 的键必须是证明号（1、2、3 …），"
                        f"这几个认不出：{bad_keys}（码 {CODE_OPTIMIZED_BAD_TABLE}）")
    bad_values = sorted(str(k) for k, v in table.items()
                        if not isinstance(v, bool))
    if bad_values:
        problems.append(f"`{_EB.OPTIMIZED_BY_PROOF_KEY}` 的值必须是布尔，"
                        f"这几格是别的类型：{bad_values}（码 {CODE_OPTIMIZED_BAD_TABLE}）"
                        "（`\"false\"` 被 `bool()` 读成 True ⇒ 没洗会变洗过）")
    return problems


# ============================================ ③ runs 的 spend 自报（只读数）

def spend_reconcile(self_report: Mapping[str, Any] | None, *,
                    ledger_usd: float | None = None,
                    ledger_calls: int | None = None,
                    events_usd: float | None = None,
                    events_calls: int | None = None,
                    problems: Any = ()) -> dict[str, Any]:
    """自报花销 vs 两本实际账：差多少、哪一本读不到。

    三个数并排，谁也不顶替谁（与 `sessions.runs_in_session` 的两格同一纪律）：

    - `self`：这一趟的缝自报的 `spend`（一个字节都不改 —— 那是模型/框架的账）；
    - `ledger`：`usage_ledger` 里同号的那些行（"我们真的记了多少钱"）；
    - `events`：会话里 `llm_call.usd` 归到这一趟的求和（"上游说花了多少"）。

    返回 `{checked, state, code, detail, self_usd, self_calls, ledger_usd,
    events_usd, delta_ledger, delta_events, unpriced_calls, problems}`。
    `state`：`ok`（对得上，不写读数）/ `derived`（对不上 —— 写点在同一处补了
    实际值这一格读数）/ `unchecked`（有一本读不到 ⇒ 没查成，绝不折成"对上了"）。
    """
    self_usd: float | None = None
    self_calls: int | None = None
    unpriced = 0
    if isinstance(self_report, Mapping):
        raw_usd = self_report.get("usd")
        if isinstance(raw_usd, (int, float)) and not isinstance(raw_usd, bool):
            self_usd = round(float(raw_usd), 6)
        raw_calls = self_report.get("calls")
        if isinstance(raw_calls, int) and not isinstance(raw_calls, bool):
            self_calls = int(raw_calls)
        raw_unpriced = self_report.get("unknown_usd_calls")
        if isinstance(raw_unpriced, int) and not isinstance(raw_unpriced, bool):
            unpriced = int(raw_unpriced)
    out: dict[str, Any] = {
        "checked": False, "state": "unchecked", "code": CODE_SPEND_UNCHECKED,
        "detail": "", "self_usd": self_usd, "self_calls": self_calls,
        "ledger_usd": (None if ledger_usd is None else round(float(ledger_usd), 6)),
        "ledger_calls": ledger_calls, "events_usd": (None if events_usd is None
                                                     else round(float(events_usd), 6)),
        "events_calls": events_calls, "unpriced_calls": unpriced,
        "delta_ledger": None, "delta_events": None,
        "problems": [str(p) for p in (problems or ()) if str(p)],
    }
    read_problems = list(out["problems"])
    if events_usd is None or ledger_usd is None:
        out["detail"] = "；".join(read_problems) or "两本实际账里有一本没读到（没查成）"
        return out
    out["checked"] = True
    out["delta_ledger"] = round(float(self_usd or 0.0) - float(ledger_usd), 6)
    out["delta_events"] = round(float(self_usd or 0.0) - float(events_usd), 6)
    out["state"] = "ok"
    out["code"] = ""
    if self_usd is None:
        out["state"] = "derived"
        out["code"] = CODE_SPEND_MISSING
        out["detail"] = (f"这一趟没有自报 `spend.usd`（账本 {float(ledger_usd):.6f} 美元 / "
                         f"{ledger_calls} 行、会话事件 {float(events_usd):.6f} 美元 / "
                         f"{events_calls} 次）⇒ 自报值原样不动，这里补的是实际值这一格读数")
        return out
    differs = (abs(float(out["delta_ledger"] or 0.0)) > _SPEND_EPS
               or abs(float(out["delta_events"] or 0.0)) > _SPEND_EPS
               or (self_calls is not None and ledger_calls is not None
                   and int(self_calls) != int(ledger_calls)))
    if differs or unpriced:
        out["state"] = "derived"
        out["code"] = CODE_SPEND_UNRECONCILED
        out["detail"] = (
            f"自报 {float(self_usd):.6f} 美元 / {self_calls} 次；"
            f"账本 {float(ledger_usd):.6f} 美元 / {ledger_calls} 行"
            f"（Δ {float(out['delta_ledger'] or 0.0):+.6f}）；"
            f"会话事件 {float(events_usd):.6f} 美元 / {events_calls} 次"
            f"（Δ {float(out['delta_events'] or 0.0):+.6f}）"
            + (f"；算不出价钱的调用 {unpriced} 次（自报的结构性缺口）" if unpriced else ""))
    return out


def record_spend_reading(root: Any, one: Mapping[str, Any], *, where: str = "") -> str:
    """把一次核对写进读数台账；对得上 / 读不到两档也各有落点。

    `ok` 不写（正常路径不灌台账）；`derived` / `unchecked` 各写一条。
    返回没记成的问题（空 = 记成了或本来就不该记）。
    """
    state = str(one.get("state") or "")
    code = str(one.get("code") or "")
    if state == "ok" or not code:
        return ""
    detail = str(one.get("detail") or "")
    fix = ("核对只在读数里做：自报值一个字都不改（那是模型/框架的账）。"
           "差额的处置是修记账那条路（`modelcost.charge_reply` 的幂等键 / 缝的 meter），"
           "不是改这一格")
    if state == "unchecked":
        return note_reading(root, SG.unchecked(
            SPEND_POINT, code=code, where=where, detail=detail,
            how_to_fix=("两本实际账里至少一本没读到（`usage_ledger` / 会话事件）："
                        "这一趟的'自报对不对'没查成，不是对上了")))
    return note_reading(root, SG.derived(
        SPEND_POINT, code=code, where=where, detail=detail, how_to_fix=fix))


# ================================================ ④ literature.dedup_key

def literature_dedup_cells(title: str, year: int | None,
                           doi: str | None) -> tuple[list[str], str]:
    """一行 `literature` 的两个去重格（`_keys` 与 `dedup_key`）的唯一算法。

    三个写点（`agent_a/run_once.py` 新建行、`locallib.py` 本地藏书、
    `tools/search_tools.py::search.register`）此前各算一份：两处写
    `keys[0] if keys else f"title:{norm}|*"`、一处写 `keys[0] if keys else ""`。
    同一个主键两处口径，漂的形式是"同一篇文献两个键"（而读侧 `_row_keys` 两处都收，
    于是永远不报错）。

    现在只有这一处：键集仍由 `dedup.literature_keys` 给（FC-27 的那一份归一化，
    本模块只调用、不重写），主键永远是键集的第一个；键集为空时主键就是空串
    （不编一个匹配不到任何东西的假键 —— 判定由 `dedup_cells_problems` 做）。
    """
    from . import dedup as _D   # 惰性：判重键的归一化只有 FC-27 那一份真身

    keys = list(_D.literature_keys(title, year, doi))
    return keys, (keys[0] if keys else "")


def note_dedup_refusal(root: Any, *, where: str, problems: Any) -> str:
    """`dedup_key` 那三处写点的受控拒读数（一处算，三处共用）。"""
    return note_reading(root, SG.refused(
        DEDUP_POINT, code=CODE_DEDUP_KEY_MISSING, where=where,
        detail="；".join(str(p) for p in (problems or ())),
        how_to_fix=("给这一行一个能归一化的题名（或 DOI）：`dedup_key` 由 "
                    "`sysresidue.literature_dedup_cells` 一处算，键集来自 "
                    "`dedup.literature_keys`；没有主键的文献不许落库")))


def dedup_cells_problems(row: Mapping[str, Any], *, keys: list[str] | None = None) -> list[str]:
    """写点判据：这一行的主键必须存在、且必须在本行自己的键集里。

    三件：键集非空、`dedup_key` 非空、`dedup_key` 是键集里的那一个（`_keys` 与
    键集逐字相同）。`keys` 不传就按行上的 `title` / `year` / `doi` 现算 —— 于是
    "读侧现算"与"写点判"是同一个函数（不会出现两处各算一次）。
    """
    from . import textutil as _T

    if keys is None:
        cells, _primary = literature_dedup_cells(
            str(row.get("title") or ""), row.get("year"), row.get("doi"))
        keys = cells
    problems: list[str] = []
    if not keys:
        problems.append(
            "键集是空的（题名规范化之后是空串、也没有 DOI）⇒ 这一行没有任何可判重的"
            f"主键（码 {CODE_DEDUP_KEY_MISSING}）。同一篇再登记一次读侧认不出它，"
            "而盘上看起来完全正常")
    key = str(row.get("dedup_key") or "")
    if not key.strip():
        problems.append(
            f"`dedup_key` 是空串（码 {CODE_DEDUP_KEY_MISSING}）："
            f"题名 {str(row.get('title') or '')!r} 规范化之后是 "
            f"{_T.normalize(str(row.get('title') or ''))!r}")
    elif keys and key not in keys:
        problems.append(
            f"`dedup_key` 是 {key!r}，而本行的键集是 {keys}（码 {CODE_DEDUP_KEY_MISSING}）"
            "—— 主键必须由同一处算出来，另拼一个形态等于让同一篇文献有两个键")
    have = sorted({str(k) for k in (row.get("_keys") or [])})
    if sorted(set(keys)) != have:
        problems.append(
            f"`_keys` 与键集不同源：行上是 {have}，键集是 {sorted(set(keys))}"
            f"（码 {CODE_DEDUP_KEY_MISSING}）")
    return problems
