# -*- coding: utf-8 -*-
"""系统计数落签：发签之前那一个「连续几次过审」的计数（2026-11-17 业主裁定）。

## 业主逐字（本模块存在的唯一理由）

    「三次连续过审才能签…不存在 V 秘书判一次审过后直接落签，不存在 V 秘书
      自己拿着工具落签（是系统计数落签）」

## 这一层是谁数、数什么、不数什么

数：只数台账行。同一份正文（`proof_sha256`）、同一次送审（`review_call`）里
`review_pass = 1..need` 连续 clean 的行。跨送审不累计 —— 另一个 `review_call`
的行只算「另一组」，不进这一组的数。同一 `review_pass` 多了几行（同号重放）不增加
计数：轮号是这一趟的身份，不是"再投一票"的机会。

不数：不数任何调用方递进来的整数。`within_call` / `len(judged)` / 台账尾部
那三个数（`agent_v/core.py` 的 `pass_no`、`3437`/`3791` 的 `len(judged)`、
`sign_counting.py::legacy_tail` 读的旧盘台账尾数）在改前各自决定过发不发签；改后它们只是读数。
决定只有一个来源：本模块从盘上那本台账现数出来的 `count`。

不落：本模块一个字节都不写（纯读）。写签是 :func:`vsigns.issue`，落签是收方
秘书的 :meth:`Secretary.land_unregistered_sign` / `vsigns.land`。三件事分三层：
谁数（这里）／谁决定（`vsigns.issue` 只认这里的 `ok`）／谁落（收方秘书）。

## 老数据：显式 legacy，不许静默等价

没有 `review_call` 的行是 2026-11-02 之前的形态（当时一次调用只判一轮、靠台账尾部
凑次数）。它们仍读得出（`legacy_tail`），但：

- 返回值带 `legacy=True` 与 `counted_by="legacy:ledger_tail"`；
- 这样数出来的签，签文件里也写 `legacy=true` + 同一个 `counted_by`（不是"看起来
  和新签一样"）；
- 它们不进新组的计数：新组只看同一个 `review_call` 的那些行（`legacy_rows`
  是它们的条数，只作读数）。

## 一处刻意登记的例外（不是静默等价）

在册穷举型证据（`agent_v/core.py` 的 `_numeric` 支）一次送审只落一行
（`review_pass=1`，机械七项会审）。那一档的行带 `review_scope="single_round"`，
读侧按 `legacy:single_round_review` 显式标出来 —— 它仍然是"一次会审"，不是三轮；
把它读成"三轮"才是本模块要挡的那种谎。

## 机械会审整组只算 1 轮（2026-11-17 业主裁定）

业主逐字：「因为实验侧报告不承重（承重的是程序），E 这条路的过审门槛从三次降成一次
（need=1）」；同一份确定性判词（`exhaustionreport.review`：同一份输入跑几遍都是同一份
判词）复制成多行不构成多轮。所以本模块收一道判据 :func:`real_judgment`：

- 同一组里出现机械会审的行（`review_scope="single_round"` / 判词来路
  `exhaustion_report`）⇒ 整组只算 1 轮（`terminated="not_real_judgment"` 作读数）；
- 那一轮算不算够，仍由 `need` 决定：E 这一档 `need=1` ⇒ 一次机械过审即达门槛；
  F / B 的 `need` 仍是 3 ⇒ 机械行永远不够（负控）；
- legacy 尾部复算同样只给机械行 1 轮 —— 「一次机械审 × 三次送审」凑不出三轮。

那一格是显式的、可打桩的：反真空判据把它打桩成恒真，"同一份判词复制三份"立刻
被数成 3 轮（`tests/test_no_mechanical_review_counts_as_three.py` 的 d）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

#: 这一格读数的来源（签文件 / 返回值都写它）：框架现数，不是调用方递进来的数。
COUNTED_BY = "sign_counting"
#: 老形态（没有 `review_call` 的行）：按台账尾部连续数，显式标注。
LEGACY_TAIL = "legacy:ledger_tail"
#: 登记在册的单轮会审（穷举型证据那一档）：一次送审只有一行，显式标注。
LEGACY_SINGLE_ROUND = "legacy:single_round_review"
#: 单轮会审的写侧标记（`verifications.record_verification(review_scope=...)`）。
SINGLE_ROUND = "single_round"
#: 机械会审的判词来路（`secretary_judge.source`）：七项确定性核对，不是模型判定。
MECHANICAL_SOURCE = "exhaustion_report"
#: 这一组停在"只有机械会审"（读数用；E 档 need=1 时它照样够）。
NOT_REAL_JUDGMENT = "not_real_judgment"


def _text(row: Mapping[str, Any], key: str) -> str:
    return str(row.get(key) or "").strip()


def row_call(row: Mapping[str, Any]) -> str:
    """这一行的送审 id（`review_call`；老行 ⇒ 空串）。"""
    return _text(row, "review_call")


def row_pass(row: Mapping[str, Any]) -> int:
    """这一行是这一趟的第几轮（`review_pass`；读不出 ⇒ 0 = 不是新形态的轮号）。"""
    got = row.get("review_pass")
    if isinstance(got, bool) or got is None:
        return 0
    try:
        return int(got)
    except (TypeError, ValueError):
        return 0


def row_sha(row: Mapping[str, Any]) -> str:
    return _text(row, "proof_sha256").lower()


def _axis(row: Mapping[str, Any]) -> str:
    """秘书给的轴（唯一来源：`verifications.ledger_axis`，不在这里另立一套）。"""
    from . import verifications as _VR

    return str(_VR.ledger_axis(row) or "")


def _signable(row: Mapping[str, Any]) -> bool:
    from . import verifications as _VR

    return bool(_VR.row_signable(row))


def mechanical_judgment(row: Mapping[str, Any]) -> bool:
    """这一行的判词是不是「确定性机械会审」（不是模型判定）。

    两个标记都是写侧本来就落的读数，不新增字段：

    - `review_scope == "single_round"`：登记在册的机械会审（一次送审只判一轮）；
    - `secretary_judge.source == "exhaustion_report"`：七项机械会审给的轴。

    两格都读不出（老行 / 散文支 / 夹具）⇒ `False`：那些行不是机械会审。
    """
    judge = row.get("secretary_judge")
    source = ""
    if isinstance(judge, Mapping):
        source = str(judge.get("source") or "")
    return (source == MECHANICAL_SOURCE
            or _text(row, "review_scope") == SINGLE_ROUND)


def real_judgment(row: Mapping[str, Any]) -> bool:
    """这一行是不是一次「真实判定」（模型真判过的那一轮）。

    「机械会审整组只算 1 轮」的唯一判据：同一份确定性判词复制成多行不构成多轮。
    注意它不是"机械行永远不算"—— E 这一档的 `need=1` 是业主 2026-11-17 的裁定
    （实验侧报告不承重、承重的是程序），一次机械过审就够；F / B 的 `need=3` 不受影响。

    反真空判据把它打桩成恒真，"同一份判词复制三份"必须立刻被数成 3 轮。
    """
    return not mechanical_judgment(row)


def ticket(row: Mapping[str, Any]) -> dict[str, Any]:
    """把一行台账翻成签文件 `passes` 里的一张票（`verification_id` / `at` / sha 三格必填）。

    2026-11-17 起多带三格身份：`review_call`（哪一次送审）、`review_pass`（第几轮）、
    `object_sha256`（稿的字节 sha）—— 于是签文件自己就能回答"这三票是不是同一趟"，
    不用回台账旁证。
    """
    return {
        "verification_id": _text(row, "verification_id"),
        "at": _text(row, "at"),
        "proof_sha256": _text(row, "proof_sha256"),
        "review_call": row_call(row),
        "review_pass": row.get("review_pass"),
        "object_sha256": _text(row, "object_sha256"),
        "object_path": _text(row, "object_path"),
        "round": row.get("round"),
        "verdict": _text(row, "verdict"),
        "axis": _axis(row),
    }


def _out(*, review_call: str, proof_sha256: str, need: int) -> dict[str, Any]:
    """读数的空壳（键无条件存在：读的人不必按分支猜这一格在不在）。"""
    return {
        #: 这一格查成没有（台账读不出来 ⇒ False，不是"0 次"）。
        "checked": False,
        #: 数出来的连续 clean 轮数够不够（`count >= need` 且 1..need 不重不漏）。
        "ok": False, "count": 0, "need": max(1, int(need or 1)),
        "review_call": str(review_call or ""), "proof_sha256": str(proof_sha256 or ""),
        "passes": [], "legacy": False, "counted_by": "", "legacy_rows": 0,
        #: 同一份正文里「机械会审」的行数（整组只算 1 轮，多出来的只作读数）。
        "mechanical_rows": 0,
        #: 同号重放的条数（不增加计数，只作读数）。
        "replayed": 0,
        #: 这一组停在哪（空串 = 没停，1..need 齐了）：`fault` / `not_signable` /
        #: `missing_pass` / `no_call` / `single_round` / `not_real_judgment`。
        "terminated": "",
        "why": "",
    }


def count_rows(rows: Sequence[Mapping[str, Any]], *, review_call: Any,
               proof_sha256: Any, need: Any) -> dict[str, Any]:
    """同一趟送审（一个 `review_call`）里连续 clean 的轮数（唯一计数实现）。

    ## 计数规则（每条都能单独钉住）

    - 只取同一份正文（`proof_sha256` 逐字相同）且 `review_call` 相同的行；
    - 轮号必须恰好是 `1..need`：缺号 ⇒ 这一组不成立（`terminated=missing_pass`）；
    - 同号重放（同一个 `review_pass` 有多行）不增加计数（`replayed` 记条数）；
    - 轴是 `fault` ⇒ 这一组当场终止（`count` 停在 fault 之前那几轮）；
    - 轴不是 clean（没查成 / 读不出来）或那一行自己签不住 ⇒ 同样终止；
    - 机械会审的行（:func:`real_judgment` 为假）⇒ 整组只算 1 轮（`:func:`real_judgment`
      的同一份判词复制成多行不算多轮）；够不够仍看 `need`（E 档 need=1 ⇒ 够；
      F / B 的 need=3 ⇒ 永远不够）；
    - 只有 `count >= need` 且 1..need 全齐才 `ok=True`。

    `legacy_rows` 是同一份正文里没有 `review_call` 的行数（只作读数：它们不进这里
    的计数，也不改变 `ok`）。
    """
    call = str(review_call or "").strip()
    sha = str(proof_sha256 or "").strip().lower()
    out = _out(review_call=call, proof_sha256=sha, need=need)
    out["checked"] = True
    same_sha = [dict(r) for r in rows if row_sha(r) == sha]
    out["legacy_rows"] = sum(1 for r in same_sha if not row_call(r))
    if not call:
        out.update(terminated="no_call",
                   why=("这一组没有 `review_call` ⇒ 不是新形态：老行只能按台账尾部数"
                        "（legacy），不许静默当成这一趟的轮号"))
        return out
    group: dict[int, list[dict[str, Any]]] = {}
    for row in same_sha:
        if row_call(row) != call:
            continue
        n = row_pass(row)
        if n >= 1:
            group.setdefault(n, []).append(row)
    out["replayed"] = sum(len(v) - 1 for v in group.values())
    count = 0
    for n in range(1, out["need"] + 1):
        got = group.get(n)
        if not got:
            out["terminated"] = "missing_pass"
            break
        #: 同号重放取第一行：轮号是这一趟的身份，重放不构成新的一轮。
        row = got[0]
        axis = _axis(row)
        if axis == "fault":
            out["terminated"] = "fault"
            break
        if axis != "clean" or not _signable(row):
            out["terminated"] = "not_signable"
            break
        #: 机械会审整组只算 1 轮：同一份确定性判词复制成多行不构成多轮。够不够仍看
        #: `need` —— E 这一档 need=1（业主 2026-11-17：实验侧报告不承重，承重的是程序），
        #: F / B 的 need=3 因此永远数不满（负控）。
        if not real_judgment(row):
            out["count"] = max(count, 1)
            out["passes"] = [ticket(row)]
            out["counted_by"] = COUNTED_BY
            out["terminated"] = NOT_REAL_JUDGMENT
            out["mechanical_rows"] = len(got)
            out["ok"] = bool(out["count"] >= out["need"])
            out["why"] = (
                f"系统计数：`{call}` 这一趟的判词来自机械会审（确定性核对，同一份输入"
                f"跑几遍都是同一份判词）⇒ 整组只算 1 轮；{out['count']}/{out['need']}"
                + ("，已达门槛" if out["ok"] else "，不够发签"))
            return out
        count += 1
        out["passes"].append(ticket(row))
    out["count"] = count
    out["ok"] = bool(count >= out["need"])
    out["counted_by"] = COUNTED_BY
    out["why"] = (
        f"系统计数：`{call}` 这一趟连续 clean {count}/{out['need']} 轮"
        f"（同号重放 {out['replayed']} 条不计；老行 {out['legacy_rows']} 条不进这一组）"
        if out["ok"] else
        f"系统计数：`{call}` 这一趟连续 clean {count}/{out['need']} 轮"
        f"（停在 {out['terminated'] or '没齐'}）⇒ 不够发签")
    return out


def legacy_tail(rows: Sequence[Mapping[str, Any]], *, proof_sha256: Any,
                need: Any, why: str = "", include_calls: bool = False) -> dict[str, Any]:
    """老形态（没有 `review_call` 的行）按台账尾部连续数 —— 显式 legacy。

    规则与 `verifications.consecutive_holds` 的历史读法同一条：同一份正文，fault /
    签不住 ⇒ 清零；没有轴的行不清零也不计入；clean 且签得住 ⇒ +1。区别只有一个：
    默认只数 `review_call` 为空的行（新形态的行不进这一条复算），并且返回值把
    "这是 legacy"写在 `legacy` / `counted_by` 上。

    `include_calls=True` 是给登记在册的单轮会审那一档用的（`review_scope=
    single_round`）：那几行本来就带 `review_call`（每一趟一个），而那一档的门槛一直是
    "同一份正文尾部连续几行 clean"—— 它按定义不是"同一趟内的 1..need 轮"。

    2026-11-17（业主：E 的过审门槛从三次降成一次）：机械会审的行在尾部复算里
    整组只算 1 轮（多出来的只进 `mechanical_rows` 读数），所以「一次机械审 ×
    三次送审」不会凑成 3 行；那一档的 `need=1` 由单轮会审的两个入口传进来。
    """
    sha = str(proof_sha256 or "").strip().lower()
    out = _out(review_call="", proof_sha256=sha, need=need)
    out.update(checked=True, legacy=True, counted_by=LEGACY_TAIL)
    same_sha = [dict(r) for r in rows
                if row_sha(r) == sha and (include_calls or not row_call(r))]
    out["legacy_rows"] = sum(1 for r in same_sha if not row_call(r))
    run = 0
    counted: list[dict[str, Any]] = []
    mech_counted = False
    for row in same_sha:
        #: 机械会审的行整组只算 1 轮（放在轴分支之前：机械行的轴往往是 clean）。
        if not real_judgment(row):
            out["mechanical_rows"] = int(out.get("mechanical_rows") or 0) + 1
            if not mech_counted:
                run += 1
                counted.append(row)
                mech_counted = True
            continue
        axis = _axis(row)
        if axis == "fault":
            run, counted = 0, []
        elif not axis:
            #: 没查成 / 老行轴读不出来：不清零、也不计入（与 `_hold_runs` 同一条）。
            continue
        elif not _signable(row):
            run, counted = 0, []
        else:
            run += 1
            counted.append(row)
    out["count"] = run
    out["passes"] = [ticket(r) for r in counted[-out["need"]:]]
    out["ok"] = bool(run >= out["need"])
    out["why"] = (why or (
        f"legacy 复算（台账尾部）：同一份正文连续 {run}/{out['need']} 行 clean，"
        f"老行 {out['legacy_rows']} 条没有 `review_call`"
        + (f"、机械会审 {out['mechanical_rows']} 条只算 1 轮"
           if out["mechanical_rows"] else "")
        + " ⇒ 这是历史形态，不是这一趟的轮号"))
    return out


def read_rows(path: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """读一本 jsonl 台账（坏行照实报出，不静默跳过）。"""
    target = Path(str(path))
    if not target.is_file():
        return [], [f"`{target}` 不在盘上"]
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    #: 行界只有 `\n`（与 `jsonlfile` 同一口径，R10FIX-D1）：台账里的判词文本可能带
    #: U+0085 一类 Unicode 行界，`splitlines()` 会把一行切碎、票数当场数成 0。
    for n, line in enumerate(target.read_text(encoding="utf-8").split("\n"), 1):
        if not line.strip():
            continue
        try:
            one = json.loads(line)
        except (ValueError, TypeError) as exc:
            problems.append(f"第 {n} 行读不出来（{exc}）")
            continue
        if not isinstance(one, dict):
            problems.append(f"第 {n} 行不是一个对象")
            continue
        rows.append(dict(one))
    return rows, problems


def _find_anchor(rows: Sequence[Mapping[str, Any]], vid: str) -> dict[str, Any] | None:
    for row in rows:
        if _text(row, "verification_id") == vid:
            return dict(row)
    return None


def _is_single_round(row: Mapping[str, Any]) -> bool:
    """这一行是不是"登记在册的单轮会审"（穷举型证据那一档，显式登记过）。"""
    return _text(row, "review_scope") == SINGLE_ROUND


def count_ledger_file(path: Any, *, anchor_vid: Any, proof_sha256: Any,
                      need: Any) -> dict[str, Any]:
    """从一本台账现数这一签够不够（`vsigns.issue` 的唯一门槛来源）。

    三种形态各走各的路，但都在返回值上写清是哪一种：

    | 锚点那一行 | 走哪条 | `counted_by` |
    |---|---|---|
    | 带 `review_call` | :func:`count_rows`（严格按这一趟数 1..need） | `sign_counting` |
    | 带 `review_scope="single_round"` | :func:`legacy_tail`（登记在册的单轮会审） | `legacy:single_round_review` |
    | 没有 `review_call` | :func:`legacy_tail`（历史形态） | `legacy:ledger_tail` |

    台账读不出来 / 锚点行不在 ⇒ `checked=False`（"没查成"不是"0 次"，也不是"够"）。
    """
    sha = str(proof_sha256 or "").strip().lower()
    vid = str(anchor_vid or "").strip()
    out = _out(review_call="", proof_sha256=sha, need=need)
    rows, problems = read_rows(path)
    if problems:
        out["why"] = ("台账读不出来 ⇒ 这一签的计数没查成（不是「0 次」，也不是「够」）："
                      + "；".join(problems[:3]))
        return out
    anchor = _find_anchor(rows, vid)
    if anchor is None:
        out["why"] = f"台账里没有锚点那一行 `{vid}` ⇒ 这一签的计数没查成"
        return out
    out["review_call"] = row_call(anchor)
    #: 锚点那一行自己的身份（`review_pass` / `review_call`）：写签前核它是这一组的
    #: 第 need 轮（同号重放不改变这一点 —— 重放的那一行也是第 need 轮）。
    out["anchor_pass"] = row_pass(anchor)
    out["anchor_call"] = row_call(anchor)
    if _is_single_round(anchor):
        #: 2026-11-17（业主）：E 这一档的过审门槛是 1（实验侧报告不承重，承重的是
        #: 程序）—— 单轮会审按 `EXHAUSTION_SIGN_STREAK_NEED` 数，不拿 F/B 的 3 去卡它。
        from . import verifications as _VR

        got = legacy_tail(rows, proof_sha256=sha,
                          need=int(_VR.EXHAUSTION_SIGN_STREAK_NEED),
                          include_calls=True, why=(
            f"legacy 复算（登记在册的单轮会审）：`{vid}` 那一趟只有一行"
            f"（`review_scope={SINGLE_ROUND}`）⇒ 这是「一次会审」；E 的过审门槛是 1"
            "（业主 2026-11-17：实验侧报告不承重，承重的是程序）"))
        got["counted_by"] = LEGACY_SINGLE_ROUND
        got["terminated"] = "single_round"
        got["review_call"] = out["review_call"]
        return got
    if not out["review_call"]:
        return legacy_tail(rows, proof_sha256=sha, need=need)
    got = count_rows(rows, review_call=out["review_call"],
                     proof_sha256=sha, need=need)
    #: 锚点自己的身份跟着数出来的那一格一起交出去（`vsigns.issue` 用它核"锚在第几轮"）。
    got["anchor_pass"] = out["anchor_pass"]
    got["anchor_call"] = out["anchor_call"]
    return got


def count_registered(root: Any, *, statement_id: Any, proof_no: Any,
                     proof_sha256: Any, review_call: Any = "",
                     need: Any) -> dict[str, Any]:
    """在册台账（`verifications/<命题号>.jsonl`）里这一趟的计数（`#proof_no` 分组）。

    `review_call` 没给 ⇒ 从"这一份证明的最后一行"读（调用方手里通常就是刚落的
    那一行）。没有 `review_call` 的老行 ⇒ :func:`legacy_tail`（显式 legacy）。
    """
    from . import verifications as _VR

    sid = str(statement_id or "").strip()
    sha = str(proof_sha256 or "").strip().lower()
    out = _out(review_call=str(review_call or ""), proof_sha256=sha, need=need)
    try:
        no = int(proof_no or 1)
        path = _VR.verification_ledger_path(root, sid)
    except (TypeError, ValueError, _VR.VerificationError) as exc:
        out["why"] = f"台账读不出来（{type(exc).__name__}: {exc}）⇒ 这一签的计数没查成"
        return out
    rows, problems = read_rows(path)
    if problems:
        out["why"] = ("台账读不出来 ⇒ 这一签的计数没查成（不是「0 次」）："
                      + "；".join(problems[:3]))
        return out
    mine = [r for r in rows if _VR.proof_no_of(r) == no]
    out["legacy_rows"] = sum(1 for r in mine if not row_call(r))
    call = str(review_call or "").strip()
    if not call and mine:
        call = row_call(mine[-1])
    if not call:
        if mine and _is_single_round(mine[-1]):
            got = legacy_tail(mine, proof_sha256=sha,
                              need=int(_VR.EXHAUSTION_SIGN_STREAK_NEED),
                              include_calls=True, why=(
                f"legacy 复算（登记在册的单轮会审）：`{sid}#p{no}` 只有一行"
                f"（`review_scope={SINGLE_ROUND}`）⇒ 一次会审；E 的过审门槛是 1"
                "（业主 2026-11-17：实验侧报告不承重，承重的是程序）"))
            got["counted_by"] = LEGACY_SINGLE_ROUND
            got["terminated"] = "single_round"
            return got
        return legacy_tail(mine, proof_sha256=sha, need=need)
    if mine and _is_single_round(mine[-1]):
        got = legacy_tail(mine, proof_sha256=sha,
                          need=int(_VR.EXHAUSTION_SIGN_STREAK_NEED),
                          include_calls=True, why=(
            f"legacy 复算（登记在册的单轮会审）：`{sid}#p{no}` 那一趟只有一行"
            f"（`review_scope={SINGLE_ROUND}`）⇒ 一次会审；E 的过审门槛是 1"
            "（业主 2026-11-17：实验侧报告不承重，承重的是程序）"))
        got["counted_by"] = LEGACY_SINGLE_ROUND
        got["terminated"] = "single_round"
        got["review_call"] = call
        return got
    return count_rows(mine, review_call=call, proof_sha256=sha, need=need)
