# -*- coding: utf-8 -*-
"""未审命题（在册 / pending 两路）。

2026-11-20（VERSPLIT2）：`v_unverified.py` 是从 `verifications.py` 搬出的 2 块 / 226 行（块
逐字未动，逐名 AST 全等在 `temp/versplit2/` 可复算）。对 32 个被测试打桩的名字，读
一律写成 `verifications.<name>` —— 门面字典在调用那一刻才查，所以
`monkeypatch.setattr(verifications, ...)` 仍然到得了这里（`from .x import X` 是快照，
补丁到不了）。跨模块 import 放在文件末尾：模块之间有互相引用，定义全跑完再 import
才解得开环。
"""

from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from . import jsonlfile as JF


def _claimed_pending_by_statement(
        root: str | Path) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """已认领的 pending 行按命题号分组（"哪些行算已认领"仍只由 :func:`_claimed_pending_rows` 定）。

    为什么要这一层：:func:`unverified_statement_refs` 按号逐条问"这一条有没有签"，而
    `_claimed_pending_rows` 一次就把整个 `verifications/pending/` 读完 ⇒ 一份 plan 的
    `history` 点名几十条时，逐条调用会把同一个目录读几十遍。判据口径一个字不在这里：
    未认领的行（两个号都空）上面那一口自己就不会交出来。
    """
    rows, problems = verifications._claimed_pending_rows(root)
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        sid = str(row.get("stmt_id") or row.get("statement_id") or "").strip()
        if sid:
            out.setdefault(sid, []).append(row)
    return out, problems


def unverified_statement_refs(root: str | Path,
                              plans: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """攻坚计划的 `history` 里点名了哪些 `statement_id`、而 `verifications` 两路都没有对应的行。

    ## 为什么这一条落在「攻」那一格（2026-10-19，接 V 的回路的收工侧）
    F 的论证由 B 登记成 `statements` 一行、拿到 `statement_id` 之后，那一号进 `attack_plans.history`（`agent_f/step.py`
    的 P3-6 落点），M 在 `attack.status` 里看得见；但看得见不等于有人审 —— 那一栏可以一直是
    "F 交了、没人签"而收工门照样绿（「攻」只问计划推进了没有）。这一条把两件事接上：history 里
    有 `statement_id` ⇒ `verifications` 里必须有它的一行（`verify_proof` 的产物）；没有 ⇒
    `closing._check_acceptance` 记 `unknown`（不是 `pass`）——"没签"与"签了"必须分得开。
    三态：`checked=False` ⇒ 没查成（读不到 `verifications/` 目录或坏行），不是"一条都没缺"；
    `missing` 逐条给 `plan_id` / `round` / `statement_id` / `why`。`signed` 是"那一行签住了第 3 位"
    （`signs_bit3`），不决定红绿（由 `missing` 定），留着是因为"有行但没签"与"有行且签了"是两种不同状态（`有毛病` 也是一条"有对应行"）。

    ## 第二路：命题还没在册时签的那一签（2026-11-20，V2FIX）

    本仓的主路是「先签后收录」：V 在命题还没号时审、签落
    `verifications/pending/<载体 sha>.jsonl`（:func:`record_pending_sign`）；B 收录拿到号之后
    只在那一行上回写 `statement_id`（:func:`_claimed_pending_rows` 的口径：不搬文件）。
    改前这一格只问 `verification_ledger_path(...).is_file()` ⇒ 只要某计划 `history` 带
    `statement_id`、而签住在 pending，`missing` 就有它 ⇒ 收工门「攻」那一格掉 `unknown`
    （lp-ball-10 / lp-ball-12 的现场，理由逐字「`verifications` 里没有它们对应的行」）。
    现在两路并读：在册台账或已认领给这一条命题的 pending 行，任一路有一行就算
    "有人审过它"。在册台账那一档的口径与改前逐字相同（pending 只作 `pending_rows` 读数）。

    不放宽的两档（三态不折平）：

    - 未认领的 pending 行（`statement_id` / `stmt_id` 两个都空）不属于任何命题 ——
      它只说明"V 审过某一份还没号的载体"，不能替任意一条命题背书；
    - 已认领、但尾行签不住（:func:`row_signable` 为假：`有毛病` / 未解决 error /
      引用核实挡签 / 没判成）的那一叠也不算：认领只回写号、不改判词。判据与
      `numericproof.exhaustion_backing` 的第二路同一条 —— 不是只看 `verdict` 那个词。

    在册台账读不动（坏行）⇒ `checked=False`；第二路读不动、且真有一条命题是「第二路
    判成 missing」的 ⇒ 同样 `checked=False`（不许折成 pass）。反过来，一本不承重的
    pending 台账读不动（每条点名的命题都在在册台账里 / 已认领的 pending 就签得住）
    不该把整格「攻」记成 `unknown`。
    """
    refs: list[dict[str, Any]] = []
    problems: list[str] = []
    #: 第二路的索引（按命题号分组）。惰性读：一份 plan 的 history 里一条 `statement_id`
    #: 都没有时，这一格不该因为"pending 目录里有坏行"就记 `unknown`。
    claimed_by: dict[str, list[dict[str, Any]]] = {}
    claimed_read = False
    #: 第二路要看的「叠」：`_claimed_pending_rows` 只交已认领的行，而"这一签之后又有
    #: 哪几转"要看整份 pending 台账（2026-11-20 READUNIFY）。与认领索引同一次惰性读。
    stacks: list[tuple[Path, list[dict[str, Any]]]] = []
    #: 第二路的坏行先单独收着：只有真有一条命题是「第二路判成 missing」的（在册台账
    #: 没有它的行、已认领的 pending 又签不住）时它才是承重的 —— 否则一本与本次提问
    #: 无关的 pending 台账读不动，不该把整格「攻」记成 `unknown`。
    pending_bad: list[str] = []
    fallback_missing = False
    for plan in plans:
        if not isinstance(plan, Mapping):
            continue
        for entry in (plan.get("history") or []):
            if not isinstance(entry, Mapping):
                continue
            sid = str(entry.get("statement_id") or "").strip()
            if not sid:
                continue
            ref: dict[str, Any] = {
                "plan_id": str(plan.get("plan_id") or ""),
                "round": entry.get("round"),
                "statement_id": sid, "rows": None, "signed": None, "why": "",
            }
            try:
                path = verification_ledger_path(root, sid)
            except VerificationError as exc:
                ref["why"] = f"命题号 {sid!r} 不是编号形态（{exc}）⇒ 查不到它那一份台账"
                refs.append(ref)
                continue
            ledger_rows: list[Mapping[str, Any]] = []
            if path.is_file():
                ledger_rows, bad = JF.read_jsonl(path)
                if bad:
                    problems.extend(f"{VERIFICATIONS_DIR}/{sid}.jsonl: {b}" for b in bad)
                    ref["why"] = f"`{VERIFICATIONS_DIR}/{sid}.jsonl` 有读不出来的行：{bad[:3]}"
                    refs.append(ref)
                    continue
            # ---- 第二路：已认领给这一条命题的 pending 行（先签后收录的正常形态）。
            if not claimed_read:
                got_claimed, got_bad = _claimed_pending_by_statement(root)
                claimed_by.update(got_claimed)
                pending_bad.extend(got_bad)
                stacks, _stack_bad = _pending_ledgers(root)
                claimed_read = True
            claimed_rows = claimed_by.get(sid) or []
            # ---- 取哪一行：与读口① `pending_sign` 同一个实现（2026-11-20 READUNIFY）----
            #
            # 改前这里取 `claimed_rows[-1]`（已认领行的尾行）。两个读口于是各取各的：
            # ① 认已发签锚在的那一行、② 取尾行 ⇒ 同一份盘一个说"有签"、一个说"没签"
            # （lp-ball-10 的 stmt:000015：锚 u-000024 / 尾行 u-000025 没轴）。
            # 现在两处都交 :func:`_pending_sign_row` 定「锚行 / 尾行」，V2FIX 的两路
            # 并读结构（在册台账 或 已认领的 pending）一个字没动。
            #
            # 取整叠而不是只取已认领的行：同一份正文后来那一转即使还没认领，它也仍是
            # 这一签之后的那一转（lp-ball-12 000071 的 u-000045 判 fault，未认领）。
            # 叠里认给别的命题的行不进来（不许借光），未认领的行算这一叠的。
            tail: dict[str, Any] = {}
            pending_row = ""
            pending_state = ""
            if claimed_rows:
                last_claimed = claimed_rows[-1]
                want_sha = str(last_claimed.get("proof_sha256") or "")
                pile = [r for r in _pending_stack_of_row(last_claimed, stacks=stacks)
                        if str(r.get("proof_sha256") or "") == want_sha
                        and _pending_claim_of(r) in ("", sid)]
                picked = verifications._pending_sign_row(root, rows=pile, sha=want_sha)
                tail = dict(picked.get("row") or {})
                pending_row = str(tail.get("verification_id") or "")
                pending_state = str(picked.get("state") or "")
                pending_ok = bool(picked.get("signable"))
            else:
                pending_ok = False
            counted = list(ledger_rows) if ledger_rows else (list(claimed_rows) if pending_ok else [])
            ref["rows"] = len(counted)
            ref["signed"] = bool(signed_rows(counted)) if counted else False
            #: 读数（不决定红绿）：认领给这一条命题的 pending 行有几条、那一处取的
            #: 「那一签」是哪一行（`pending_row`）、它签不签得住、三态是哪一档。
            ref["pending_rows"] = len(claimed_rows)
            ref["pending_signable"] = pending_ok
            ref["pending_row"] = pending_row
            ref["pending_state"] = pending_state
            if not counted:
                if claimed_rows:
                    # 轴是行局部谓词的第一条（`row_signable` 先问秘书轴）：轴不是 clean 时
                    # 挡住它的就是轴本身；`_bit3_blockers` 只列机械闸，这时它会落到兜底句。
                    blocked = (_bit3_blockers(tail) if verifications.ledger_axis(tail) == "clean"
                               else str(axis_reading(tail).get("why") or ""))
                    ref["why"] = (
                        f"`{VERIFICATIONS_DIR}/{PENDING_DIR_NAME}/` 里有 "
                        f"{len(claimed_rows)} 行认领给 stmt:{sid}，但"
                        f"{pending_row or '那一行'} 签不住"
                        f"（verdict={read_verdict(tail)!r}；{blocked}）⇒ 仍算 missing："
                        "认领只回写号、不改判词，「有行」不等于「签住了」")
                elif path.is_file():
                    ref["why"] = f"`{VERIFICATIONS_DIR}/{sid}.jsonl` 是空文件 ⇒ 一次审校都没落过"
                else:
                    ref["why"] = (f"`{VERIFICATIONS_DIR}/{sid}.jsonl` 不在盘上，"
                                  f"`{VERIFICATIONS_DIR}/{PENDING_DIR_NAME}/` 里也没有认领给它的行 "
                                  "⇒ 这一条命题一次审校都没落过")
            refs.append(ref)
            if not counted and not ledger_rows:
                # 这一条答案是由第二路给的（而且是"没有"）⇒ 第二路的坏行可能藏着
                # 一份签得住的那一叠，必须记"没查成"而不是"确实没有"。
                fallback_missing = True
    if fallback_missing:
        problems.extend(pending_bad)
    missing = [r for r in refs if not r.get("rows")]
    return {
        "checked": not problems,
        "problems": problems,
        "refs": refs,
        "missing": missing,
        "total": len(refs),
        "note": ("plan 的 `history` 里有 `statement_id` ⇒ `verifications/<命题号>.jsonl` 里"
                 "必须有它的一行，或 `verifications/pending/` 里有一行认领给它且**签得住**"
                 "（先签后收录的正常形态；派 V 的 `verify.verify_proof` 就会落）。`missing` 非空 ⇒ "
                 "「攻（攻坚推进）」那一格记 `unknown`（不是 `pass`）；`signed` 只是读数："
                 "「有行但没签」由审计期那一档（`proof_review_without_verification`）点名"),
    }


# 跨模块引用放在文件末尾：这些名字的实现在别的模块里，而两个模块可能互相
# 引用（顶层 `from .x import y` 在环里会在对方还没定义完时执行）。引用点
# 全部在函数体里，所以只要定义都跑完了，谁先被导入都拿得到。
from . import verifications  # 门面字典：被打桩的名字经它取
from .v_vocab import (  # noqa: F401 — 实现在 v_vocab.py
    PENDING_DIR_NAME,
    VERIFICATIONS_DIR,
)
from .v_paths import (  # noqa: F401 — 实现在 v_paths.py
    VerificationError,
    verification_ledger_path,
)
from .v_pending_read import (  # noqa: F401 — 实现在 v_pending_read.py
    _pending_claim_of,
    _pending_ledgers,
    _pending_stack_of_row,
)
from .v_rowread import (  # noqa: F401 — 实现在 v_rowread.py
    axis_reading,
    read_verdict,
)
from .v_streak import (  # noqa: F401 — 实现在 v_streak.py
    signed_rows,
)
from .v_gap_read import (  # noqa: F401 — 实现在 v_gap_read.py
    _bit3_blockers,
)
