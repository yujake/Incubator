# -*- coding: utf-8 -*-
"""连续票与打回（同一份正文才算数）。

2026-11-20（VERSPLIT2）：`v_streak.py` 是从 `verifications.py` 搬出的 6 块 / 270 行（块
逐字未动，逐名 AST 全等在 `temp/versplit2/` 可复算）。对 32 个被测试打桩的名字，读
一律写成 `verifications.<name>` —— 门面字典在调用那一刻才查，所以
`monkeypatch.setattr(verifications, ...)` 仍然到得了这里（`from .x import X` 是快照，
补丁到不了）。跨模块 import 放在文件末尾：模块之间有互相引用，定义全跑完再 import
才解得开环。
"""

from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from . import jsonlfile as JF
from . import schema as S  # 编号形态的唯一来源（六位 / 旧四位读侧兼容）


def _hold_runs(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[int], list[bool]]:
    """逐行给出 `(到这一行为止连续几次成立, 这一行是否作废)`（行序 = 台账追加序）。

    这是台账历史读数的唯一计数实现：:func:`consecutive_holds`（从尾部取一格）、
    :func:`review_standing`（它已经读过同一批行，不重复读盘）、:func:`signed_rows`
    （一批台账里哪几行签住了）三处都调它；:func:`_hold_run_lengths` 是它的只取计数那一半。

    ## 2026-11-06（业主裁定 3 的准确含义）：打回站住，同一份正文不重复判

    业主逐字：「一次判有毛病时应该立即打回，不再起转，等下一次提交时重新从 0 转计数」。
    于是「打回」不只是一次清零，而是这份正文的下一次送审不再攒票：

    - 带 `review_call` 的行（2026-11-02 起的新形态 = 一次 `verify_proof` 的一转）：
      这一份正文上第一次出现 `axis=fault` 之后，后续那些新送审的 clean 行一律作废
      （`void=True`，计数停在 0）—— 它们不再算"另一次送审的三转"（真机
      `R-mk-infinite-94` 的 000034：v1 clean / v2 fault / v3–v5 clean 曾经凑成 3/3 签）;
    - 不带 `review_call` 的老行（2026-11-02 之前"一次调用只判一轮、靠台账尾部凑次数"
      的形态）：按旧口径读（fault 清零之后还能再攒）—— 这是历史兼容，不是新签的路
      （`tests/test_v_sign_gate_streak.py::test_a2` 钉着它）。

    为什么用 `review_call` 当判据而不是"一律作废"：老行没法归到某一次送审上，把旧读数
    按新规矩重算会把历史工作区的读数整体翻掉（那不是这次修正要动的东西）。
    """
    runs: list[int] = []
    void: list[bool] = []
    sha = ""
    run = 0
    #: 这一份证明里被判过打回的那些正文 sha（带 `review_call` 的那一行判了 fault）。
    #:
    #: 按 sha 记、不随"换了一份正文"清掉：台账里两份正文的行可以交错出现（改稿 → 回退 →
    #: 再改稿），而"这一份 sha 打回过"是这份正文的性质，不是相邻两行的性质。
    #: 改前它是单值、遇到 sha 变化就重置 ⇒ 交错出现时后一次的同 sha 行会漏掉作废。
    rejected: set[str] = set()
    for row in rows:
        one = str(row.get("proof_sha256") or "")
        if not runs or one != sha:
            run = 0
            sha = one
        axis = verifications.ledger_axis(row)
        call = str(row.get("review_call") or "").strip()
        is_void = bool(one and one in rejected and call)
        if axis == "fault":
            run = 0
            if call:
                rejected.add(one)
        elif not axis:
            # 没有轴：老行 / 没判成 / 轴名读不出来。那不是一种判定 ⇒ 既不攒票也不作废。
            pass
        elif is_void:
            # 打回之后又起转的那一趟：不算"同一次送审内的票"，也不给自己清零的理由。
            run = 0
        elif not row_signable(row):
            run = 0
        else:
            run += 1
        runs.append(run)
        void.append(is_void)
    return runs, void


def _hold_run_lengths(rows: Sequence[Mapping[str, Any]]) -> list[int]:
    """逐行给出「到这一行为止，连续几次成立」（行序就是台账的追加序）。

    计数规则（含 2026-11-06「打回站住」那一档）见 :func:`_hold_runs`：本函数只取它的
    计数那一半，读数对外的形状逐字未变。

    它不再充当"新签发不发"的判据（2026-11-02 业主定稿：「不允许跨两次送审累计
    成功数」）。一次 `verify_proof` 的签发只看同一次调用内的轮数
    （`sign_issuance.within_call`）；这个函数数的是跨全部历史行的连续数，只用来回答
    "台账上以前发生过什么"，旧工作区的读数（`holding` / `signed` 等）仍照它读。
    三个调用点都是读侧；写侧 `sign_statement` 在拿到 `within_call` 时不调它。

    三处各写一遍合计，只会让三处对同一批行给出三个数 —— 而"位上说签了、台账只签一次"
    正是这种分家的形态。

    ## 什么会清零、什么被读成"这一票算上了"（2026-10-29 的 A 段 + 2026-10-30 第三次裁定
    ## + 2026-11-01 的两态结论 + 2026-11-02 的追加裁定）
    - `proof_sha256` 变了 ⇒ 清零（F 改稿之后，之前那几次审的不是这一份）；
    - 行局部签不住（`有毛病` / 未解决 error / 引用挡签）⇒ 清零；
    - 轴是 `clean` ⇒ 投一票；
    - 轴是 `fault`（有缺陷要指出）⇒ 清零；
    - 没有轴（老行没有 `secretary_judge` / 问过没判成 / 轴名读不出来）⇒ 不清零、也不计入。
      这是 p247 的核心：轴只由秘书的语义分析给，`verdict` 的字面不是证据。
      "这一行的轴读不出来"与"这一趟判过了 clean"必须分得开，否则一次读侧故障就会把一条
      未判的行静默算成一票（`tests/test_v_sign_gate_streak.py` 的 z2(c) 钉着这件事）。
    - 轴是 `clean` 但行局部机械闸没过（未解决 error / 引用挡签 / 依赖台账读不成）⇒ 清零；
    - 同一份正文已经被打回过（带 `review_call` 的那一次送审里判了 fault）⇒ 之后的
      新送审行一律作废、不攒票（2026-11-06 业主裁定 3；判据在 :func:`_hold_runs`）。

    调用方负责先把行分组（同一命题 + 同一证明号）：一条命题的两份证明各自数各自的，
    `#p1` 的三票不许替 `#p2` 数（不许借光）。
    """
    return _hold_runs(rows)[0]


def void_after_rejection(rows: Sequence[Mapping[str, Any]]) -> list[bool]:
    """逐行给出「这一行属于『同一份正文被打回之后又起转』的那一趟」（读侧共用的一把尺）。

    判据只有一处实现（:func:`_hold_runs`），本函数是它对外的那一半：读侧有两处必须
    同尺 —— 台账的连续计数（:func:`_hold_run_lengths`）与"重送义务清没清"
    （:func:`obligations.resubmit_cleared`）。两处各判一套的后果很具体：作废行一边不算
    票、一边却还能把"要你重送"的义务清掉 —— 于是一份被打回、没改稿、重掷签上的正文，
    既不欠票、也不再有人要求它重送（"打回即站住"只站住了一半）。

    调用方负责先把行分组（同一命题 + 同一证明号），与 :func:`_hold_run_lengths` 同一条。
    """
    return _hold_runs(rows)[1]


def _rows_of_proof(rows: Sequence[Mapping[str, Any]], proof_no: int) -> list[Mapping[str, Any]]:
    """这一批台账行里属于 `#proof_no` 的那些（按台账行序，别的证明的行一条都不带）。"""
    return [r for r in rows if proof_no_of(r) == int(proof_no)]


def consecutive_holds(root: str | Path, statement_id: str, proof_no: Any = 1,
                      need: int | None = None) -> dict[str, Any]:
    """台账尾部连续几次「成立」且是同一份正文（纯读；业主 2026-10-29 的 A 段）。

    `need=None` = 门槛现读 `SIGN_STREAK_NEED`（2026-10-30 改，理由与 :func:`streak_ok`
    同一句：默认参数是导入期的快照，不是门槛本身 —— 而 `sign_statement` 的签字闸读的
    就是这个函数的返回值，两处门槛漂了之后"够不够"会给出两个数）。

    这就是「连续 3 次没问题」那个计数：从 `verifications/<命题号>.jsonl` 的尾部按台账
    行序往回数，同一 `proof_sha256`、连续判「成立」的行数；任何一行判「有毛病」、或者
    sha 换了、或者秘书判了 `fault` ⇒ 从那里断开（尾行自己就断 ⇒ 0 次）。
    秘书没查成的那一行不清零也不计入；老行上的 `看不出来`
    没有秘书轴 ⇒ 同样不计票（2026-11-16 裁定 ④：那一档不是一个结论）。

    ## 三态（"没查成"不是"0 次"）
    | 结局 | `checked` | `streak` |
    |---|---|---|
    | 数出来了（含"一次都没签"） | True | 数出来的次数（可以是 0） |
    | 台账在盘上但读不出坏行 / 证明号认不出 / 命题号不是编号形态 | False | 0 |

    `checked=False` 时 `streak=0` 只是占位（返回值必须有一个整数），调用方要读的是
    `checked`：`signs_bit3(row, streak=<这一份>)` 会因为它 `checked` 为假而不签
    （见 :func:`_streak_number`），所以"没查成"在签字那一端是 fail-closed 的。

    ## `legacy_rows`：历史形态的显式读数（2026-11-02）

    `legacy_rows` = 这一份证明的台账行里没有 `review_call` / `review_pass` 的行数。
    这些行是旧版跨送审累计形态留下的（当时一次调用只判一轮、靠台账尾部凑次数），
    读得出、也仍参与 `streak` 这个历史读数；但它们不参与新签判断 ——
    新签只看同一趟 `verify_proof` 内 `review_pass=1..need` 的那几行
    （`sign_issuance.within_call`）。"多少行是历史形态"必须能一眼读出来，否则
    "旧台账的 2 行 clean 被当成这一次的 2 轮"会静静地发生。

    返回键：`checked` / `statement_id` / `proof_no` / `need` / `streak` / `streak_ok` /
    `sha`（尾部那一签盖住的正文 sha256）/ `rows`（这一个证明号的行数）/
    `legacy_rows` / `ledger` / `reason`。
    """
    out: dict[str, Any] = {
        "checked": False, "statement_id": str(statement_id or "").strip(),
        "proof_no": 0, "need": int(verifications.SIGN_STREAK_NEED) if need is None else int(need),
        "streak": 0, "streak_ok": False,
        "sha": "", "rows": 0, "legacy_rows": 0, "ledger": "", "reason": "",
        #: 这个连续数是哪一档数出来的（2026-11-17，业主「系统计数落签」）：本函数
        #: 数的是台账尾部连续数，也就是历史形态那一路 —— 显式标 legacy，不许
        #: 让读的人把它当成新签的 `review_call` 组内计数（那个在 `sign_counting`）。
        "counted_by": "legacy:ledger_tail",
    }
    no = _read_proof_no(proof_no)
    if no < 1:
        out["reason"] = (f"证明号认不出：收到 {proof_no!r} ⇒ 不知道数的是哪一份证明，"
                         "这一格没查成（不是「一次都没签」）")
        return out
    out["proof_no"] = no
    sid = out["statement_id"]
    if not S.is_valid_id(sid):
        out["reason"] = (f"命题号 {sid!r} 不是编号形态 ⇒ 查不到台账，这一格没查成"
                         "（不是「一次都没签」）")
        return out
    try:
        path = verification_ledger_path(root, sid)
    except VerificationError as exc:
        out["reason"] = f"命题号 {sid!r} 查不到台账（{exc}）⇒ 这一格没查成"
        return out
    out["ledger"] = f"{VERIFICATIONS_DIR}/{sid}.jsonl"
    if not path.is_file():
        out.update(checked=True,
                   reason=(f"`{out['ledger']}` 不在盘上 ⇒ 一次审校都没有"
                           "（查过了：连续次数是 0，不是「没查成」）"))
        return out
    rows, problems = JF.read_jsonl(path)
    if problems:
        out["reason"] = (f"`{out['ledger']}` 有读不出来的行（{problems[:3]}）⇒ "
                         "连续次数没查成（不是「0 次」）")
        return out
    mine = _rows_of_proof(rows, no)
    out["rows"] = len(mine)
    out["legacy_rows"] = sum(1 for r in mine if _is_legacy_row(r))
    out["checked"] = True
    if not mine:
        out["reason"] = (f"`{out['ledger']}` 里没有 #{no} 这一份证明的签 ⇒ 连续次数 0"
                         "（别的证明签过也不借光）")
        return out
    runs = _hold_run_lengths(mine)
    tail = mine[-1]
    run = runs[-1]
    out.update(streak=int(run), streak_ok=bool(run >= out["need"]),
               sha=str(tail.get("proof_sha256") or ""))
    if out["streak_ok"]:
        out["reason"] = (f"#{no} 的尾部连续 {run} 次「成立」且盖着同一份正文"
                         f"（sha {out['sha'][:12]}…，门槛 {out['need']} 次）⇒ 够发签")
    else:
        out["reason"] = (f"#{no} 的尾部连续 {run} 次「成立」（门槛 {out['need']} 次，"
                         f"最新一签 {str(tail.get('verification_id') or '') or '（没有编号）'}、"
                         f"verdict={tail.get('verdict')!r}）⇒ 不发签：连续次数没到门槛"
                         "（这一签只落台账、不翻位）")
    return out


def signed_rows(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """这一批台账行里签住了第 3 位的那些（按 (命题号, 证明号) 分组各自数连续次数）。

    `ledger_reading` / `unverified_statement_refs` 要从一批跨命题的行里数"有几行签住了"，
    而连续次数只能在同一份证明的同一批行里数 ⇒ 分组这一步必须只有一处实现
    （否则两个读数会对同一批行给出不同的行数）。
    """
    groups: dict[tuple[str, int], list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault((_statement_id_of(row), proof_no_of(row)), []).append(row)
    out: list[Mapping[str, Any]] = []
    for key in sorted(groups):
        one = groups[key]
        for row, run in zip(one, _hold_run_lengths(one)):
            if signs_bit3(row, streak=run):
                out.append(row)
    return out


# 跨模块引用放在文件末尾：这些名字的实现在别的模块里，而两个模块可能互相
# 引用（顶层 `from .x import y` 在环里会在对方还没定义完时执行）。引用点
# 全部在函数体里，所以只要定义都跑完了，谁先被导入都拿得到。
from . import verifications  # 门面字典：被打桩的名字经它取
from .v_vocab import (  # noqa: F401 — 实现在 v_vocab.py
    VERIFICATIONS_DIR,
)
from .v_paths import (  # noqa: F401 — 实现在 v_paths.py
    VerificationError,
    _read_proof_no,
    proof_no_of,
    verification_ledger_path,
)
from .v_rowread import (  # noqa: F401 — 实现在 v_rowread.py
    _is_legacy_row,
    _statement_id_of,
    row_signable,
    signs_bit3,
)
