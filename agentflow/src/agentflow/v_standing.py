# -*- coding: utf-8 -*-
"""第 3 位读数（签的是哪一份）。

2026-11-20（VERSPLIT2）：`v_standing.py` 是从 `verifications.py` 搬出的 6 块 / 641 行（块
逐字未动，逐名 AST 全等在 `temp/versplit2/` 可复算）。对 32 个被测试打桩的名字，读
一律写成 `verifications.<name>` —— 门面字典在调用那一刻才查，所以
`monkeypatch.setattr(verifications, ...)` 仍然到得了这里（`from .x import X` 是快照，
补丁到不了）。跨模块 import 放在文件末尾：模块之间有互相引用，定义全跑完再 import
才解得开环。
"""

from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from . import depsection as _DS  # 可引门槛的唯一定义（`CITATION_MIN_LEVEL`）
from . import jsonlfile as JF


def _superseded_reading(row: Mapping[str, Any], *, streak: Any = None) -> dict[str, Any]:
    """一条被更近的签盖过去的旧签（`review_standing` 的 `superseded` 元素）。

    它回答"这一份正文以前还被谁签过、签的是哪一版、结论是什么"：旧签仍然可见，
    但判定只看最近那一签（:func:`review_standing`）。字段刻意只留定位用的几格，
    正文与 findings 不回放 —— 那些在台账文件里逐字可查，读数层不复制历史。

    `verdict` 按两态读（:func:`read_verdict`）：老行上的 `看不出来` 在这里报 `成立`
    （2026-11-02：那一档连历史兼容读也不留）；逐字原话仍去台账文件里读。

    `signed_bit3` 是那一签当年的读数：`streak` 由调用方按"到这一行为止的连续次数"
    递进来（:func:`_hold_run_lengths` 的分组读数）——旧签也要过同一道连续闸，
    否则"当年签住了"会把一条只有 1 票的旧签说成签过。
    """
    return {
        "verification_id": str(row.get("verification_id") or ""),
        "verdict": read_verdict(row),
        "round": row.get("round"),
        "at": str(row.get("at") or ""),
        "proof_no": proof_no_of(row),
        "proof_sha256": str(row.get("proof_sha256") or ""),
        "signed_bit3": signs_bit3(row, streak=streak),
        "unresolved_errors": int(row.get("unresolved_errors") or 0),
        "why": str(row.get("why") or "")[:200],
    }


def review_standing(root: str | Path, *, statement_id: str, proof_text: str,
                    proof_no: int = 1) -> dict[str, Any]:
    """一条证明的第 3 位相对「它现在这一份正文」的读数（唯一判定口，纯读）。

    ## 判据（业主 2026-10-22 多证明模型）
    只看 `proof_no` 这一份证明的现行正文的 sha：同一份正文上按台账行序取最近那一签，
    它签住了 ⇒ `signed`；最近那一签的结论不是「成立」⇒ `rejected`；签的是旧版 ⇒
    `stale`（R10 不计，单列 `proofs_stale`）；这一份一次都没签 ⇒ `unsigned`（哪怕同一条
    命题的别的证明签过 —— 不许借光）；台账读不出来 ⇒ `unreadable`（没查成，不是通过）。
    更早的签不改判定，只进 `superseded`（仍可见：id / verdict / 那一签盖住的 sha）。

    ## 最近一签为什么必须能否决（2026-10-22 审计的第 3 条）
    改前先挑出有「成立」的那几签再取最后一条，于是"先成立、后改判有毛病"永远读回
    `signed`：后一次否决投不出去，旧的那一签被当成了免死金牌。改后同一份正文的覆盖集里
    只有最后那一签说了算；更早的签降为历史读数。
    "旧签名是历史，不是否决票"仍然成立，但它的方向被限定为：旧版上的结论（包括
    「有毛病」）不否决现行这一份上的「成立」那一签（哈希只回答"这份稿在你签完之后有没有
    被改过"）；反过来，同一份正文上更新的否决必须盖过更早的成立。

    ## 哈希在这里的角色：读数，不是授权
    `stale` 与 `rejected` 都不拦任何写入（见 :func:`proof_review_gaps`），它们只让第 3 位
    不计入、并各自有一个可读的理由。返回键：`checked` / `state` / `ok` / `in_sync` /
    `ledger_present` / `statement_id` / `proof_no` / `sha` / `verification_id` / `verdict` /
    `round` / `unresolved_errors` / `rows`（这条命题的台账总行数）/ `proof_rows`（本份
    证明的行数）/ `superseded` / `superseded_total` / `problems` / `ledger` / `why` /
    `streak` / `need` / `streak_ok`（业主 2026-10-29 的连续读数）/ `legacy_rows`
    （历史形态的行数，2026-11-02：只作历史台账读数，不参与新签判断）。

    ## 「连续 3 次」在这一格怎么读（业主 2026-10-29 的 A 段）
    `state="signed"` 的条件从"最近一签是成立"改成"尾部连续 `SIGN_STREAK_NEED` 签成立
    且同一份正文"：`streak` / `need` / `streak_ok` 三格把这件事逐字报出来。签过、判成立、
    但次数还没到 ⇒ `state="holding"`（不是 `signed`，也不是"一次都没签"）。计数只调
    :func:`_hold_run_lengths`（不重复读盘：这里的 `mine` 就是它要的那批行），
    行长与"哪一签算第几票"因此与 :func:`consecutive_holds` 逐字一致。

    ## 历史形态与"新签"分开（2026-11-02，业主定稿）
    上面这段说的是台账历史读数：它回答"以前发生过什么"，旧工作区的 `state` 仍照它读。
    但"新签发不发"不再看它 —— 新签只看同一趟 `verify_proof` 内 `review_pass=1..need`
    的那几行（`sign_issuance.within_call`）。没有 `review_call` / `review_pass` 的行
    由 `legacy_rows` 显式数出来，不参与新签判断，也不按新规则重算成签。

    ## 历史行 `verdict="看不出来"` 怎么读（2026-11-02：这一档连历史兼容读也不留）
    按 :func:`read_verdict` 读成 `成立` ⇒ 它走上面同一条路（同一份正文 ⇒ `signed` /
    `holding`，并投"连续成立"那一票），没有"历史行"那一条支了。改前它读成 `rejected`
    并附一句"只作兼容读：既不算票、也不清零"（宽容方向：老行既不算通过、也不算失败），
    那条历史支已整段删掉（连函数一起）。

    ## 证明号认不出 ⇒ `unreadable`，不折成 `#p1`（2026-10-22 收尾）
    `proof_no` 问的是"要看哪一份证明"，所以没给（`None` / 空串）才是 canonical；给了但
    :func:`as_proof_no` 认不出（`0` / `'abc'` / `2.0`）⇒ 返回 `checked=False`、
    `state="unreadable"`、`proof_no=0`，`why` 逐字点名"证明号认不出"。改前是
    `as_proof_no(proof_no) or 1`：一个坏号拿到的是 `#p1` 的读数，而读的人看不出号给错了
    （同样的折平还在 :func:`proof_text_of` / :func:`proof_label` 里，三处一起改的）。
    这一档是"没查成"（问的是哪一份都没有答案），不是"查过了、没签过"。

    ## 在册台账缺席 / 为空 ⇒ 回退到 `verifications/pending/`（FIX186-D1，2026-11-19）
    「先签后收录」是主路：V 在命题还没在册时审、B 收录时才拿到号 ⇒ 那一签住在
    `verifications/pending/<载体 sha>.jsonl`，在册台账可能根本不存在。改前这里只读
    在册台账 ⇒ 同一件事两个读口两个答案（`proof_review_gap` 早就有 pending 回退）。
    现在只在"在册台账读不出行"时回退（有行以正本为准），回退之后 `ledger` /
    `rows` / `review_source` 都指回真的那一份文件；判定仍走本函数同一套
    （`_hold_runs` / `row_signable` / `signs_bit3`），票数按尾行那一趟送审数
    （`_pending_claim_streak`，与签发那一侧同一把尺）。
    """
    sid = str(statement_id or "").strip()
    no = _read_proof_no(proof_no)
    sha = _sign_sha(proof_text)
    out: dict[str, Any] = {
        "checked": False, "state": "unsigned", "ok": False, "in_sync": None,
        "ledger_present": False, "statement_id": sid, "proof_no": no, "sha": sha,
        "verification_id": "", "verdict": "", "round": None,
        "unresolved_errors": 0, "rows": 0, "proof_rows": 0, "problems": [],
        "superseded": [], "superseded_total": 0,
        #: 连续读数（业主 2026-10-29）：三个键无条件存在（"这一格是 0"与"没有这一格"
        #: 必须靠键的存在分开）。读不成 / 没有那一行时它们是 0 / 3 / False。
        "streak": 0, "need": int(verifications.SIGN_STREAK_NEED), "streak_ok": False,
        #: 历史形态的行数（2026-11-02）：没有 `review_call` / `review_pass` 的行。
        #: 它们只作历史台账读数，不参与新签判断；见 :func:`_is_legacy_row`。
        "legacy_rows": 0,
        #: 这个连续数是哪一档数出来的（2026-11-17）：本格数的是台账尾部连续数
        #: ⇒ 显式 legacy（新签的组内计数在 `sign_counting`，不是这里）。
        "counted_by": "legacy:ledger_tail",
        "ledger": "", "why": "",
    }
    if no < 1:
        # 证明号认不出 ⇒ "问的是哪一份"没有答案。这是"没查成"，不是"没签过"（三态纪律），
        # 也不许悄悄按 canonical 读：改前 `as_proof_no(proof_no) or 1` 会把它读成 `#p1`，
        # 于是"号给错了"的读数与"我要 #p1"逐字相同。
        out.update(
            checked=False, state="unreadable",
            why=(f"证明号认不出：收到 {proof_no!r}（合法写法是 1、2、3 … 或 "
                 "'2' / 'p2' / '#p2'）⇒ 不知道问的是哪一份证明，这一格没查成"
                 "（不是「没签过」，也不是「签过过期」）；读侧不把它折成 canonical（#p1）"))
        return out
    if not sid:
        out.update(checked=True, why="没有命题号 ⇒ 查不到台账（不是没签过）")
        return out
    try:
        path = verification_ledger_path(root, sid)
    except VerificationError as exc:
        out.update(checked=True, why=f"命题号 {sid!r} 不是编号形态（{exc}）⇒ 查不到台账")
        return out
    out["ledger"] = f"{VERIFICATIONS_DIR}/{sid}.jsonl"
    out["ledger_present"] = path.is_file()
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    if out["ledger_present"]:
        rows, problems = JF.read_jsonl(path)
        out["rows"] = len(rows)
        out["problems"] = list(problems)
        if problems:
            out.update(state="unreadable",
                       why=(f"`{out['ledger']}` 有读不出来的行（{problems[:3]}）⇒ "
                            "第 3 位没查成（不是「没签过」，也不是「签过过期」）"))
            return out
    # ---- FIX186-D1：在册台账缺席 / 为空 ⇒ 回退到「先签后收录」那一叠 ------------
    #
    # 只在"在册台账读不出行"时才回退：有行就以在册台账为准（两处都有时不让 pending
    # 盖过正本）。回退之后 `ledger` / `rows` / `review_source` 都指回真的那一份文件。
    pending_mode = False
    if not rows:
        pending = verifications._pending_standing_rows(root, statement_id=sid, sha=sha,
                                         proof_no=no, proof_text=proof_text)
        if pending is not None:
            rows = list(pending.get("rows") or [])
            pending_mode = True
            out.update(ledger=str(pending.get("ledger") or ""),
                       ledger_present=True, rows=int(pending.get("rows_total") or 0),
                       review_source="pending", counted_by="pending:issued_call")
    if not pending_mode:
        if not out["ledger_present"]:
            out.update(checked=True,
                       why=f"`{out['ledger']}` 不在盘上 ⇒ 一次审校都没有（不是签过过期）")
            return out
        if not rows:
            out.update(checked=True, why=(
                f"`{out['ledger']}` 是空文件 ⇒ 一次审校都没落过"
                "（「有这个文件」不等于「审过」）"))
            return out
    out["checked"] = True
    if not str(proof_text or "").strip():
        # 空正文不是"签过过期"：没有被审的对象，「签没签过」这件事无从谈起。
        out.update(why=(f"{proof_label(sid, no)} 的正文是空的 ⇒ 没有被审的那一份，"
                        "这一格既不是「签过」也不是「签过过期」"))
        return out
    mine = [r for r in rows if proof_no_of(r) == no]
    out["proof_rows"] = len(mine)
    out["legacy_rows"] = sum(1 for r in mine if _is_legacy_row(r))
    if not mine:
        out.update(why=(f"`{out['ledger']}` 里没有 #{no} 这一份证明的签"
                        "（别的证明签过也不算 —— 不许借光）"))
        return out
    covering = [r for r in mine if str(r.get("proof_sha256") or "") == sha]
    # ---- 最近一签的判据（2026-10-22 审计后）：同一份正文上按台账行序取最后那一签。
    #
    # 改前这里先挑 `signed`（有「成立」的签）再取它的最后一条，于是"先成立、后改判有毛病"
    # 永远读成 signed —— 后一次否决投不出去，旧的那一签被当成了免死金牌。改后：在同一份
    # 正文的覆盖集里，最后那一签说了算；更早的签只留在 `superseded` 里可见，不参与判定。
    # 签名行本身是追加式的（台账不改历史），所以"最近"就是读出来的行序（`at` / `round`
    # 只做展示；时钟回拨不会把判定翻回去）。
    chosen = covering[-1] if covering else mine[-1]
    cut = next((i for i, r in enumerate(mine) if r is chosen), len(mine) - 1)
    superseded = mine[:cut]
    # ---- 连续读数（业主 2026-10-29）：逐行的"到这一行为止连续几次成立"。
    #
    # `runs[-1]` 是本份证明现在的连续次数（尾部那一签数到几），`runs[cut]` 是
    # "被选中那一签当年算第几票"—— 判定用的是后者：`chosen` 未必是尾行
    # （F 改了正文、而更早的几签盖着现行 sha 时就是那种情形），拿尾行的票数去判
    # 一个更早的签会把它说成它没达到过的次数。
    runs, runs_void = _hold_runs(mine)
    chosen_run = runs[cut] if 0 <= cut < len(runs) else 0
    out.update({
        "streak": int(runs[-1] if runs else 0),
        "need": int(verifications.SIGN_STREAK_NEED),
        "streak_ok": bool(runs and runs[-1] >= verifications.SIGN_STREAK_NEED),
        "verification_id": str(chosen.get("verification_id") or ""),
        #: 结论按两态读（:func:`read_verdict`）：老行上的 `看不出来` 在这里就是 `成立`。
        "verdict": read_verdict(chosen),
        "round": chosen.get("round"),
        "unresolved_errors": int(chosen.get("unresolved_errors") or 0),
        #: 被这一签盖过去的旧签（仍可见、不参与判定）：按台账行序，逐条给 id / verdict /
        #: 那一签盖住的 sha。它是"旧签降为历史"的唯一读数格。
        "superseded": [_superseded_reading(r, streak=runs[i])
                       for i, r in enumerate(superseded)],
        "superseded_total": len(superseded),
        #: I10 硬禁令在这一签上的机械命中（2026-10-27，只报不判）：这一格不参与
        #: `state` / `ok` / `in_sync` 中的任何一个 —— 它只是让"这一签盖过的正文里有
        #: 「易证/显然」"这件事可见。老行没有这一格 ⇒ 空列表。
        "hard_ban_markers": [str(m) for m in (chosen.get("hard_ban_markers") or [])],
        #: 秘书对这段回复的语义判定（业主 2026-10-29 第 5 轮）：`fault` 是"V 的结论词写
        #: 成立、但秘书读出来它其实指出了缺陷"那一档。它不改六态词表（`state` 仍 `holding`，
        #: 因为 R10 与收工门共读那个词表），只让这件事在读数里说得出来 ——
        #: 否则读的人会把 `holding` 的"还差 3 次"当成"还没评够"，而实际是"被读出了缺陷"。
        #: 2026-11-02 起这里是 :func:`secretary_axis` 的读法（只有 clean / fault 两格）：
        #: 老行上那个已取消的轴名读出来是空串（"这一行没有轴"），不再在读数里冒充一格。
        "secretary_axis": verifications.ledger_axis(chosen),
        "secretary_fault": (verifications.ledger_axis(chosen) == "fault"),
        #: 这一转的秘书判定是"判过了"还是"没判成"（业主 2026-10-30）：读侧要拿它把
        #: "没查成"与"判过了"分开（见 :func:`secretary_judged` / :func:`secretary_unjudged`）。
        "secretary_judged": secretary_judged(chosen),
        "secretary_unjudged": secretary_unjudged(chosen),
    })
    if pending_mode:
        # FIX186-D1：pending 那一支的票数要按「这一份正文在尾行那一趟送审里签了几转」数
        # （与签发那一侧 `sign_counting.count_rows` 同一把尺，见 `_pending_claim_streak`）。
        # 不用 `_hold_runs` 的跨送审累计数：那会把"上一趟 2 转 + 这一趟 3 转"读成 5/3，
        # 而签发那一侧只认这一趟的 3 转 —— 判定与读数不许各说一个数。
        _counted = verifications._pending_claim_streak(mine, sha)
        chosen_run = int(_counted.get("votes") or 0)
        out.update(streak=chosen_run, streak_ok=bool(_counted.get("ok")),
                   counted_by=f"pending:{_counted.get('counted_by') or 'issued_call'}")
    if covering and 0 <= cut < len(runs_void) and runs_void[cut]:
        # ---- 2026-11-06（业主裁定 3 的准确含义）：这一签落在"打回之后又起转"的那一趟上 --
        #
        # 真机 `R-mk-infinite-94` 的 000034：v2 判 fault（打回），同一次送审本该到此为止；
        # 而 v3–v5 是同一份正文（同一个 sha）重开的一趟，三转 clean 之后签了、签块写
        # "连续=3/3"。业主逐字：「第 2 转判 fault 时就该打回，根本不该有第 3、4、5 转」。
        # 所以读侧按新口径把那些行判成作废（:func:`_hold_runs` 的 `void`），这一份正文
        # 仍是打回状态、连续数 0：不许把"打回之后又起转"读成"另一次送审攒够了"。
        objection = ""
        obj_i = -1
        for i in range(min(cut, len(mine)) - 1, -1, -1):
            if (str(mine[i].get("proof_sha256") or "") == sha
                    and verifications.ledger_axis(mine[i]) == "fault"):
                objection = str(mine[i].get("verification_id") or "")
                obj_i = i
                break
        out.update(
            state="rejected", in_sync=False,
            #: 定位那几格指回打回那一行（不是指回那一条作废的 clean 行）：
            #: 读 `verification_id` 的人要能找到"凭什么打回"，而不是一条不作数的签。
            verification_id=(objection or str(chosen.get("verification_id") or "")),
            round=(mine[obj_i].get("round") if obj_i >= 0 else chosen.get("round")),
            verdict=(read_verdict(mine[obj_i]) if obj_i >= 0 else read_verdict(chosen)),
            unresolved_errors=int((mine[obj_i].get("unresolved_errors") or 0)
                                  if obj_i >= 0 else 0),
            secretary_axis="fault" if obj_i >= 0 else verifications.ledger_axis(chosen),
            secretary_fault=True if obj_i >= 0 else bool(out.get("secretary_fault")),
            why=(f"{proof_label(sid, no)} 的现行正文（sha {sha[:12]}…）最近一签是 "
                 f"{str(chosen.get('verification_id') or '（没有号）')}，它落在「被打回之后"
                 f"又起转」的那一趟送审上 ⇒ 这一签不作数（同一份正文不重复判、跨送审不累计）；"
                 f"这一份仍是打回状态"
                 + (f"（打回在 {objection}）" if objection else "")
                 + "：按缺陷改稿之后再送，下一次送审从 0 起数"))
        return out
    if covering and signs_bit3(chosen, streak=chosen_run):
        out.update(state="signed", ok=True, in_sync=True,
                   why=(f"{proof_label(sid, no)} 的现行正文（sha {sha[:12]}…）连续 "
                        f"{chosen_run}/{verifications.SIGN_STREAK_NEED} 签「成立」，最近一签是"
                        f"{out['verification_id']}（{out['ledger']}）"
                        + (f"；更早的 {len(superseded)} 签已降为历史"
                           "（见 superseded，不参与判定）" if superseded else "")))
        return out
    if covering and row_signable(chosen) and not signs_bit3(chosen, streak=chosen_run):
        # 签过、判成立、签的也是现行这一份 —— 就是次数没到（业主 2026-10-29）。
        out.update(state="holding", in_sync=True,
                   why=(f"{proof_label(sid, no)} 的现行正文（sha {sha[:12]}…）已连续 "
                        f"{chosen_run}/{verifications.SIGN_STREAK_NEED} 签「成立」（最近一签 "
                        f"{out['verification_id']}，{out['ledger']}）⇒ 还差 "
                        f"{verifications.SIGN_STREAK_NEED - chosen_run} 次才发签：台账有行、第 3 位没翻"
                        + ("；但秘书读出了缺陷（它判 fault：V 的结论词虽写「成立」，"
                           "回复里其实指出了问题）—— 这一份要按缺陷处理，"
                           "别把「还差几次」当成「还没评够」"
                           if out.get("secretary_fault") else "")
                        + ("；而这一转秘书没判成（checked=False：没查成，不是有毛病）"
                           "—— 这一签不发，等判定接上之后重签"
                           if out.get("secretary_unjudged") else "")))
        return out
    if covering and verifications.ledger_axis(chosen) == "fault":
        out.update(state="rejected", in_sync=True,
                   why=(f"{proof_label(sid, no)} 的现行正文（sha {sha[:12]}…）最近一签是 "
                        f"{out['verification_id']}：秘书语义判定轴=fault ⇒ 这一份要打回，"
                        f"按缺陷处理（V 写下的陈述：{out['verdict']!r}；"
                        f"unresolved_errors={out['unresolved_errors']}；"
                        f"why：{str(chosen.get('why') or '')[:120]}）"
                        + (f"；更早的 {len(superseded)} 签已降为历史（见 superseded），"
                           "不能把它翻回「成立」" if superseded else "")))
        return out
    if covering:
        # 轴不是 fault、但这一行也没签成：clean 但次数没到 / 机械闸挡签 / 这一问没判成
        # （checked=False）/ 没有轴（老行）。p247 起这里不再按 `verdict` 的字面判"打回"：
        # 只有秘书判 fault 才是打回（上一支），其余一律是"这一签不发"。
        out.update(state="holding", in_sync=True,
                   why=(f"{proof_label(sid, no)} 的现行正文（sha {sha[:12]}…）最近一签是 "
                        f"{out['verification_id']}（V 写下的陈述：{out['verdict']!r} —— "
                        "复核过、这一签不发）"
                        + ("；秘书没判成（checked=False：没查成，不是有毛病）"
                           if out.get("secretary_unjudged") else "")
                        + ("；这一行没有秘书轴（老行 / 没判过）⇒ 不算票、不签发"
                           if not out.get("secretary_axis") else "")))
        return out
    out.update(state="stale", in_sync=False,
               why=(f"`{out['ledger']}` 里 {proof_label(sid, no)} 有 {len(mine)} 签，"
                    f"但没有一签盖住它现在这一份：最近一签 {out['verification_id']} 签的是"
                    f"另一版（台账 sha256={str(chosen.get('proof_sha256') or '')[:12]}…，"
                    f"现行这一份={sha[:12]}…）⇒ 待复核（stale）：第 3 位不计，"
                    "等 V 对现在这一份重签"))
    return out


def statement_review_reading(root: str | Path, row: Mapping[str, Any]) -> dict[str, Any]:
    """一条命题在「多证明」模型下的第 3 位读数（纯读，逐条证明分开）。

    ## 为什么命题级读数不能只有一个布尔
    多证明模型（业主 2026-10-22）里，每条证明各自有第 3 位：`#p1` 签过不等于 `#p2`
    签过（不许借光），`#p2` 签过也不等于 `#p1` 签过。命题级要回答的是"这条定理有没有
    一份被审过的证明"，所以它是逐条读数的汇总，而逐条读数各自独立。

    返回键：
    - `proofs`: `[{proof_no, state, ok, in_sync, reviewed, grade, formal,
      proof_sha256, verification_id, streak, need, streak_ok, why}]`
      （每条证明一条，按 `proof_no` 升序）；
      其中 `formal` 是这一条证明自己的第 4 位（`{证明号: 状态}` 里的那一格，
      四态 + 读侧产生的 `stale`）：`#p1` 形式化通过不等于 `#p2` 形式化通过，
      所以它必须逐条给，并且与 `grade` 成对读；
      `streak` / `need` / `streak_ok` 是这一份证明自己的连续读数（业主 2026-10-29，
      `#p1` 的票数不替 `#p2` 数）；
    - `reviewed`: 命题级 —— 至少一条证明 `signed`（定理档取"最高"就落在这一格）；
    - `grade`: 逐条证明各自的档里最高的那一档（`_highest_grade`）：一条 in-sync 都没有
      ⇒ `conjecture`；两条各缺一半（一条有形式化、另一条有签名）⇒ 不许凑出定理
      （借光由逐条派生挡掉，见 `proofs[*]["grade"]`）；
    - `state`: 命题级六态（有 signed 就 `signed`；否则有 stale 就 `stale`；否则有
      rejected 就 `rejected`；否则有 holding 就 `holding`；否则有 unreadable 且没别的
      ⇒ `unreadable`；否则 `unsigned`）；
    - `proofs_unreviewed` / `proofs_stale` / `proofs_rejected` / `proofs_holding`:
      逐条证明的编号写法
      （`000004#p2`），不许折进"没有证明"：它们是两条独立读数；
    - `proofs_superseded`: 被更近的签盖过去的旧签（写法 `000004#p1:v-000001`）；
      它们仍可见，但不参与判定（最近一签说了算）；
    - 概念行：`reviewed=False` / `grade=not_applicable` 短路，不产出上面那些计数项；
    - `checked` / `ledger_present` / `problems` / `why`。
    """
    from . import evidencebits as _EB   # 惰性：等级的唯一入口
    from . import lifecycle as _LC      # FIX186-A：三态的唯一入口
    sid = str(row.get("stmt_id") or row.get("statement_id") or "")
    kind = str(row.get("kind") or "")
    bits = _EB.bits_from_row(row)
    #: 这条命题现在占不占活跃集（三态；原始 `status` 仍在行上，判据只读这一格）。
    lifecycle_state = str(_LC.state_of_statement(row).get("state") or "")
    if kind == "concept":
        # ---- 概念行短路（2026-10-22 审计的第 5 条） -----------------------------
        #
        # 改前这里照样去读台账，然后把每条的 state 写成 unsigned、grade 写成
        # not_applicable，却没有把 `ok` 一起压掉：只要概念行的 proof_text 撞上一次
        # 「成立」的签，`reviewed = any(e["ok"])` 就把它抬成 `reviewed=True`、
        # `state='signed'`，而同一条读数的 `proofs[0]` 写着 `unsigned`、
        # `grade='not_applicable'` —— 一条读数自己跟自己矛盾，R10 也跟着把它算进去。
        # 概念不参与等级链（`derive_grade` 对 concept 短路），所以这一格整份是
        # "不适用"：reviewed 恒 False、grade 恒 not_applicable，也不产出
        # `proofs_unreviewed` / `proofs_stale` / `proofs_rejected` 这些计数项
        # （它们会让"概念"被当成"没签过的证明"灌进读数）。
        entries = [{
            "proof_no": no, "label": proof_label(sid, no),
            "state": "unsigned", "ok": False, "in_sync": None,
            "reviewed": False, "grade": _EB.GRADE_NOT_APPLICABLE,
            "proof_sha256": _sign_sha(text), "verification_id": "",
            "superseded": [],
            "why": ("概念行不参与等级链（`evidencebits.derive_grade` 对 "
                    "kind='concept' 短路成 not_applicable）⇒ 这一格对它不适用，"
                    "既不算审过，也不算没审过"),
        } for no, text in proof_list(row)]
        return {
            "checked": True,
            "ledger_present": False,
            "statement_id": sid,
            "proofs": entries,
            "state": "unsigned",
            "reviewed": False,
            "grade": _EB.GRADE_NOT_APPLICABLE,
            "proofs_unreviewed": [],
            "proofs_stale": [],
            "proofs_rejected": [],
            "proofs_holding": [],
            "proofs_superseded": [],
            "superseded_total": 0,
            "problems": [],
            "lifecycle_state": lifecycle_state,
            "why": (f"{sid or '（没有编号）'} 是概念行（kind='concept'）：概念不参与"
                    "等级链，没有「审过的证明」这一档 ⇒ reviewed=False、"
                    "grade=not_applicable，也不计入 R10"),
        }
    entries: list[dict[str, Any]] = []
    unreviewed: list[str] = []
    stale: list[str] = []
    rejected: list[str] = []
    holding: list[str] = []
    superseded_labels: list[str] = []
    problems: list[str] = []
    ledger_present = False
    #: 第 4 位（形式化）在逐条证明上的读数：`{证明号: 状态}`。汇总那一层是 OR
    #: （业主 2026-10-22：「但凡任意一个路径通过核验，它就是对的」），而逐条这一层是
    #: "哪一条路径验过" —— 两条都要：只读汇总会让 `#p2` 借 `#p1` 的光。
    formal_states = _EB.formal_by_proof(bits)
    for no, text in proof_list(row):
        st = review_standing(root, statement_id=sid, proof_text=text, proof_no=no)
        ledger_present = ledger_present or bool(st.get("ledger_present"))
        problems.extend(str(p) for p in (st.get("problems") or []))
        per = dict(bits)
        per["reviewed"] = bool(st.get("ok"))
        # 逐条证明的第 4 位：只有这一条自己被验过才算（不许拿别条的顶）。
        per[_EB.FORMAL_BIT] = formal_states.get(no, "pending")
        grade = _EB.derive_grade(per, kind=kind)
        state = str(st.get("state") or "unsigned")
        old = [dict(x) for x in (st.get("superseded") or [])]
        for item in old:
            superseded_labels.append(
                f"{proof_label(sid, no)}:{str(item.get('verification_id') or '?')}")
        entries.append({
            "proof_no": no, "label": proof_label(sid, no), "state": state,
            "ok": bool(st.get("ok")), "in_sync": st.get("in_sync"),
            "reviewed": bool(st.get("ok")), "grade": grade,
            #: 这一条证明自己的第 4 位（`evidencebits.FORMAL_PATH_STATES` 的取值：
            #: 四态 + 读侧产生的 `stale`）。它与 `grade` 成对："这条证明到什么档"
            #: 只有这两格合起来才说得清（#p1 形式化通过、#p2 没验 ⇒ 两条各自的档不同）。
            "formal": per[_EB.FORMAL_BIT],
            "proof_sha256": str(st.get("sha") or ""),
            "verification_id": str(st.get("verification_id") or ""),
            #: 被最近那一签盖过去的旧签（仍可见、不参与判定）。`review_standing`
            #: 的同一格原样下传，逐条证明分开。
            "superseded": old,
            #: 连续读数（业主 2026-10-29）：这一份证明自己的 `streak` / `need` /
            #: `streak_ok`，逐条证明分开（#p1 的票数不替 #p2 数）。
            "streak": int(st.get("streak") or 0),
            "need": int(st.get("need") or verifications.SIGN_STREAK_NEED),
            "streak_ok": bool(st.get("streak_ok")),
            #: 秘书对最近那一签的判定（业主 2026-10-30）：轴只有 clean / fault 两档，
            #: `judged` 区分"判过了"与"没判成"，`unjudged` 是"问过、没查成"那一格。
            "secretary_axis": str(st.get("secretary_axis") or ""),
            "secretary_judged": bool(st.get("secretary_judged")),
            "secretary_unjudged": bool(st.get("secretary_unjudged")),
            "why": str(st.get("why") or ""),
        })
        if state == "unsigned":
            unreviewed.append(proof_label(sid, no))
        elif state == "stale":
            stale.append(proof_label(sid, no))
        elif state == "rejected":
            rejected.append(proof_label(sid, no))
        elif state == "holding":
            holding.append(proof_label(sid, no))
    reviewed = any(e["ok"] for e in entries)
    states = [e["state"] for e in entries]
    if reviewed:
        state = "signed"
    elif "stale" in states:
        state = "stale"
    elif "rejected" in states:
        state = "rejected"
    elif "holding" in states:
        # 签过、判成立、只是次数没到（业主 2026-10-29）。它必须排在 `unsigned` 之前：
        # "有行、还差两次"与"一次都没签"是两种处置（前者再派两次，后者派一次）。
        state = "holding"
    elif "unreadable" in states:
        state = "unreadable"
    else:
        state = "unsigned"
    out_bits = dict(bits)
    out_bits["reviewed"] = reviewed
    #: 命题级的档 = 逐条证明里最高的那一档（`draft/39` §3.14 的"在 in-sync 的证明里取最高"）。
    #:
    #: 改前这里先把第 3 位取 OR、第 4 位取 OR，再派生一次：多证明模型下那会让
    #: `#p1` 的形式化通过 + `#p2` 的 V 签名凑出一档 —— 两条各缺一半，凑出来的档
    #: 谁也没有（借光）。现在每一档都由一条证明自己撑起来，命题级只是取最高的那条。
    grade = _highest_grade([str(e.get("grade") or "") for e in entries])
    if not grade:
        grade = _EB.derive_grade(out_bits, kind=kind)
    why = _statement_reading_why(sid=sid, state=state, reviewed=reviewed, entries=entries,
                                 unreviewed=unreviewed, stale=stale, rejected=rejected,
                                 holding=holding)
    return {
        "checked": not problems,
        "ledger_present": ledger_present,
        "statement_id": sid,
        "proofs": entries,
        "state": state,
        "reviewed": reviewed,
        "grade": grade,
        "proofs_unreviewed": unreviewed,
        "proofs_stale": stale,
        "proofs_rejected": rejected,
        #: 签过、判成立、但连续次数还没到的那些（写法与上面三格同形）。
        #: 单列的理由：它们是"再派两次审阅"的待办，不是"派一次"，也不是"改证明"。
        "proofs_holding": holding,
        #: 被更近的签盖过去的旧签（写法 `000004#p1:v-000001`）：它们仍在台账里、
        #: 仍读得出来，但不参与命题级判定（最近一签说了算，见 `review_standing`）。
        "proofs_superseded": superseded_labels,
        "superseded_total": len(superseded_labels),
        "problems": problems,
        #: 三态（FIX186-A）：这条命题现在占不占活跃集（原始 `status` 在行上作审计）。
        "lifecycle_state": lifecycle_state,
        "why": why,
    }


def _statement_reading_why(*, sid: str, state: str, reviewed: bool,
                           entries: Sequence[Mapping[str, Any]],
                           unreviewed: Sequence[str], stale: Sequence[str],
                           rejected: Sequence[str], holding: Sequence[str]) -> str:
    """命题级那句 `why`（六态各一句；`holding` 里再把两种处置分开）。

    为什么要单独一个函数：这条`why`有六个分支、每支都是一句人话，而它住在
    :func:`statement_review_reading` 里会把那个函数压过 200 行（`scripts/repo_survey.py`
    的长函数基线是逐条登记的，长大要人裁）。判据不变，只是换了个落点。
    """
    if reviewed:
        return ""
    if state == "stale":
        return (f"{sid} 的证明都签过旧版（或签过但没盖住现在这一份）"
                f"（stale：{'、'.join(stale)}）⇒ 一条 in-sync 的签名都没有")
    if state == "rejected":
        return (f"{sid} 的证明现在这一份被签过、结论不是「成立」"
                f"（rejected：{'、'.join(rejected)}）")
    if state == "holding":
        # 2026-10-30（第三次裁定）：holding 里混着两种来路 —— "次数没到"（再送 V 判几转）
        # 与"这一转秘书没判成"（框架失败：没查成）。读数必须把它们分开，否则后者会被
        # 读成前者（"再判几次就好"）。
        #
        # 2026-11-02 删掉了第三种来路：改前这里还单列"历史行里的 unsure（只作历史兼容读：
        # 既不算票、也不清零）"。那一档连历史兼容读也不留之后，老行上那个轴名读出来是
        # 空轴（:func:`secretary_axis`），它在连续计数里落进"轴读不出来"那条通用纪律
        # （不计票、也不清零）—— 与"这一转秘书没判成"同一条处置，于是不再需要第三句。
        unjudged = [str(e.get("label") or "") for e in entries
                    if str(e.get("state") or "") == "holding"
                    and e.get("secretary_unjudged")]
        return (f"{sid} 的证明签过、也判了「成立」，但门槛还没到"
                f"（holding：{'、'.join(holding)}）"
                "⇒ 第 3 位不发签：再送 V 走这一趟送审（门槛由框架按这一趟送审自己数；"
                "跨趟不累计）"
                + (f"；其中 {'、'.join(unjudged)} 是这一转秘书没判成（checked=False："
                   "没查成，不是有毛病）—— 那一档不发签，等判定接上之后重签"
                   if unjudged else ""))
    if state == "unreadable":
        return f"{sid} 的验证台账读不出来 ⇒ 第 3 位没查成（不是「没签过」）"
    return (f"{sid} 的证明一次都没签（{'、'.join(unreviewed) or '没有证明'}）"
            "⇒ 第 3 位是没签过，不是签过过期")


def _highest_grade(grades: Sequence[str]) -> str:
    """几条证明各自的档 ⇒ 命题级那一档（`GRADES` 里最靠后的那个）。

    空清单 / 只有认不出的取值 ⇒ 空串（调用方退回"按汇总位现算"那一条路，不猜）。
    `not_applicable`（概念行）不在 `GRADES` 里，所以它到不了这里：概念行在
    `statement_review_reading` 里是短路的一支。
    """
    from . import evidencebits as _EB   # 惰性：与 `statement_review_reading` 同一处依赖

    known = [str(g) for g in grades if str(g) in _EB.GRADES]
    if not known:
        return ""
    return max(known, key=_EB.GRADES.index)


def statement_grade(root: str | Path, row: Mapping[str, Any]) -> str:
    """一条命题的等级 —— 转发（唯一实现在 `depsection.statement_grade`）。

    这一格原先自带一份实现（`statement_review_reading(root, row)["grade"]`：逐条证明
    现读台账、在 in-sync 的证明里取最高），与 `depsection.statement_grade`（`bits` 现算）
    是两个落点 —— `R003` 报的正是"同一判据两份实现"。2026-11-05 收成一处：等级由
    `evidencebits.derive_grade` 从五元位现算（`depsection` 那一份），这里只转发。

    `root` 保留在签名里只为老调用方（`test_multi_proof_end_to_end` 等）不必改；
    等级不从台账现读 —— 台账的签只写第 3 位（`bits.reviewed`），读侧按同一条
    `bits_from_row` 现算。逐条证明各自的读数仍归
    :func:`statement_review_reading`（那是另一个函数、回答另一个问题：每条证明自己
    到什么档），不要从这一格取。
    """
    return _DS.statement_grade(row)


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
    _sign_sha,
    proof_label,
    proof_list,
    proof_no_of,
    verification_ledger_path,
)
from .v_rowread import (  # noqa: F401 — 实现在 v_rowread.py
    _is_legacy_row,
    read_verdict,
    row_signable,
    secretary_judged,
    secretary_unjudged,
    signs_bit3,
)
from .v_streak import (  # noqa: F401 — 实现在 v_streak.py
    _hold_runs,
)
