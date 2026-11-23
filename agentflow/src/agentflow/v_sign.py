# -*- coding: utf-8 -*-
"""签落位（台账与 statements 同一次写）。

2026-11-20（VERSPLIT2）：`v_sign.py` 是从 `verifications.py` 搬出的 3 块 / 572 行（块
逐字未动，逐名 AST 全等在 `temp/versplit2/` 可复算）。对 32 个被测试打桩的名字，读
一律写成 `verifications.<name>` —— 门面字典在调用那一刻才查，所以
`monkeypatch.setattr(verifications, ...)` 仍然到得了这里（`from .x import X` 是快照，
补丁到不了）。跨模块 import 放在文件末尾：模块之间有互相引用，定义全跑完再 import
才解得开环。
"""

from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from . import statementledger as SL  # 命题台账的查口（按号 / 按关键词，只读、零模型）
from .proofloc import DEFAULT_PROOF_NO  # canonical 证明号只有一个出处（`proofloc`）


def _framework_holds(root: str | Path, row: Mapping[str, Any], *, need: Any,
                     review_call: str = "", proof_no: Any = None) -> dict[str, Any]:
    """这一签的「连续几次过审」读数：框架从台账现数（`sign_counting`），不吃调用方的数。

    业主 2026-11-17 逐字：「…（是系统计数落签）」。改前这一格由调用方递进来的
    `within_call`（V 那一趟的 `pass_no`）或台账尾部连续数（`consecutive_holds`）决定；
    现在只有一个来源：:func:`sign_counting.count_registered` —— 同一份正文、同一个
    `review_call` 内 `review_pass=1..need` 连续 clean 的轮数。老行（没有 `review_call`）
    走 legacy 复算，读数里带 `legacy=True` + `counted_by="legacy:ledger_tail"`。

    2026-11-22（BASELINEFIX）：这条口径此前只覆盖生产落地那一步
    （:func:`land_sign_without_ledger`）；同文件的 :func:`sign_statement` 里还留着一条
    按 `sign_issuance.within_call` 自报数判定的活门。那条已退役（见
    :func:`_holds_for_the_issuance`），两个落地口现在同一个实现。

    `proof_no=None` = 按这一行自己记的那一格（`proof_no_of`）；给了就用它 ——
    调用方手里那个数才是"这一签签的是哪一份证明"（`sign_statement` 的 `proof_no`
    与行上那一格可能不同：显式传号时行上往往没有那一格）。

    返回 `holds` 的键与 `consecutive_holds` 同形（`checked` / `streak` / `need` /
    `streak_ok` / `sha` / `legacy_rows`），另加 `counted_by` / `legacy` / `why`。
    """
    from . import sign_counting as _SC

    sid = str(row.get("stmt_id") or row.get("statement_id") or "")
    if proof_no is None:
        try:
            no = proof_no_of(row)
        except VerificationError:
            no = DEFAULT_PROOF_NO
    else:
        no = proof_no
    counted = _SC.count_registered(
        root, statement_id=sid, proof_no=no,
        proof_sha256=row.get("proof_sha256"),
        review_call=str(review_call or row.get("review_call") or ""), need=need)
    return {
        "checked": bool(counted.get("checked")),
        "streak": int(counted.get("count") or 0),
        "need": int(counted.get("need") or int(need or verifications.SIGN_STREAK_NEED)),
        "streak_ok": bool(counted.get("ok")),
        "sha": str(row.get("proof_sha256") or ""),
        #: legacy 那两档（没有 `review_call` 的历史行 / 登记在册的单轮会审）不给
        #: `review_call`：签的 `passes` 那一格要按台账尾部回捞（`_vsign_payload` 的
        #: 历史支），而不是按"这一趟"取——单轮会审的每一行本来就各属于一个
        #: `review_call`，按趟取只会取到 1 条，签就会 `passes_incomplete`。
        "review_call": ("" if counted.get("legacy")
                        else str(counted.get("review_call") or "")),
        "legacy_rows": int(counted.get("legacy_rows") or 0),
        #: 这个数是哪一档数出来的（`sign_counting` / `legacy:*`）：签文件与读数都写它，
        #: 老数据不许静默等价成新签。
        "counted_by": str(counted.get("counted_by") or ""),
        "legacy": bool(counted.get("legacy")),
        "why": str(counted.get("why") or ""),
    }


def land_sign_without_ledger(store: Any, *, row: Mapping[str, Any],
                             within_call: int | None = None,
                             need: Any = None, review_call: str = "",
                             by: str = "", manuscript: str = "") -> dict[str, Any]:
    """颁签 + 落块，不碰 `statements`（2026-11-08，业主「V 只对手稿负责」）。

    这是 V 的在册送审在"三转 clean + 秘书判发"之后的落地那一步：
    - 写签的侧文件（`out/vsigns/<正文 sha>.json`，`vsigns.issue`）；
    - 让收方秘书把 `- V 签：` 九格块落回手稿（`vsigns.land`，`ledger_bit=False`）；
    - 给 B 开一条「必须收录」义务（`_registration_after_vsign`，签块落成才开）。

    不开 `store.tx("statements")`：不翻第 3 位、不写 `kind` / `grade` /
    `reviewed_by_proof`。那些是 B 收录时的活（业主：「第几份证明、什么等级都是 B 秘书
    录入时关心且需负责的」）。于是 `writeback["written"]` 恒为 False —— 它回答的是
    "命题位有没有被这一趟翻"，答案是没有；签有没有落地由 `sign_issued` /
    `manuscript_write` 两格回答（三态不许折平）。

    返回键：`written`（恒 False，命题位）/ `deferred_to="filing:B"` /
    `sign_issued` / `vsign` / `land` / `manuscript_write` / `registration` / `reason`。
    `written=False` 与 `sign_issued=False` 同时出现才是"这一签没落地"。
    """
    out: dict[str, Any] = {
        "written": False, "rolled_back": False, "deferred_to": "filing:B",
        "sign_issued": False, "append_state": "appended_by_caller",
        "vsign": {}, "land": {}, "manuscript_write": {}, "registration": {},
        "statement_id": str(row.get("stmt_id") or row.get("statement_id") or ""),
        "proof_no": 0, "proof_sha256": str(row.get("proof_sha256") or ""),
        "grade": "", "kind_upgrade": {}, "upgrade_note": "",
        "grade_recomputed": {}, "streak": 0, "need": int(verifications.SIGN_STREAK_NEED),
        "streak_ok": False, "reason": "",
    }
    row = dict(row or {})
    sid = str(out["statement_id"])
    if not sid:
        out["reason"] = ("没有命题号 ⇒ 这一签没有可写的台账锚点（不是「签上了」）")
        return out
    if not row_signable(row):
        out["reason"] = ("这一签签不住（verdict 不是「成立」，或有未解决的 error）"
                         "⇒ 不颁发、不落块")
        return out
    root = getattr(store, "root", "")
    if isinstance(store, (str, Path)):
        root = str(store)
    try:
        no = proof_no_of(row)
    except VerificationError:
        no = DEFAULT_PROOF_NO
    out["proof_no"] = int(no)
    n = int(need or verifications.SIGN_STREAK_NEED)
    # ---- 2026-11-17（业主：「是系统计数落签」）：门槛由框架从台账现数 --------------
    #
    # 改前这里吃 `within_call`（V 那一趟的 `pass_no`）：给了它，`streak` 就是调用方
    # 说的那个整数，框架一个字都不核（现盘对应逻辑见 `secretary_sign.py::decide_sign_issuance`）。
    # 现在数只有一个来源：`sign_counting.count_registered` —— 同一份正文、同一个
    # `review_call` 内 `review_pass=1..need` 连续 clean。`within_call` 只作读数
    # （`within_call_claim`），它多了/少了一轮都不改变这里数出来的数。
    holds: dict[str, Any] = _framework_holds(
        root, row, need=n, review_call=review_call)
    if within_call is not None:
        holds["within_call_claim"] = max(0, int(within_call))
    out["streak"] = int(holds.get("streak") or 0)
    out["need"] = int(holds.get("need") or n)
    out["streak_ok"] = bool(holds.get("streak_ok"))
    try:
        ledger = verification_ledger_path(root, sid)
    except VerificationError as exc:
        out["reason"] = f"{exc}；这一签没有可写的台账锚点"
        return out
    vsign = _vsigns_write_after_flip(
        root, row=row, ledger=ledger, statement_id=sid, proof_no=int(no),
        sha=str(row.get("proof_sha256") or ""), holds=holds,
        append_ledger=False, by=str(by or ""),
        manuscript=str(manuscript or row.get("manuscript") or ""))
    out["vsign"] = dict(vsign)
    out["sign_issued"] = bool(vsign.get("written") or vsign.get("idempotent"))
    out["manuscript_write"] = dict(vsign.get("manuscript_write") or {})
    out["land"] = dict(vsign.get("land") or {})
    if out["sign_issued"] and out["manuscript_write"].get("written"):
        out["reason"] = ("签已颁发并落回手稿；命题行的第 3 位与等级由 B 收录时"
                         "按正文 sha 认领/现算（V 不写 statements）")
    elif out["sign_issued"]:
        out["reason"] = (f"签已颁发（`{vsign.get('path') or '签文件'}`），但块没落："
                         f"{str(out['land'].get('reason') or vsign.get('reason') or '没有理由')}")
    else:
        out["reason"] = (f"颁发没成（`{vsign.get('path') or '签文件'}`）："
                         f"{str(vsign.get('reason') or '没有理由')}")
    out["registration"] = _registration_after_vsign(
        store=store, root=root, vsign=dict(vsign), statement_id=sid,
        proof_no=int(no), sha=str(row.get("proof_sha256") or ""), skip_gap=True,
        # SGN1：签落地 = 必须真把 B 叫醒的那一刻（不是"板上多一条无主项"）。
        wake=True)
    return out


def _holds_for_the_issuance(root: str | Path, row: Mapping[str, Any], *,
                            proof_no: Any,
                            sign_issuance: Mapping[str, Any] | None) -> dict[str, Any]:
    """这一签的连续读数：门槛只由台账定，`sign_issuance.within_call` 只进读数（退役门）。

    ## 改前那一条活门（2026-11-02 → 2026-11-22）

    `sign_issuance["within_call"]` 一旦给出，`sign_statement` 就只看那个整数：

        within_call = int(sign_issuance.get("within_call"))
        streak_ok = bool(within_call >= need)

    台账一个字都不核。而 `within_call` 是秘书从 V 那一趟连判循环里拿到的调用方自报
    轮数（`agent_v/core.py` 的 `pass_no`）—— 业主 2026-11-17 的裁定「是系统计数落签」
    正是针对它：数只能从台账现数。

    ## 为什么退役而不是删函数

    `sign_statement` 现在只服务历史直调 / 夹具：生产在册落地那一步是
    :func:`land_sign_without_ledger`（`secretary_sign.py:527-531` 逐字写明生产不再调
    `sign_statement`），唯一剩下的框架侧调用者是 `record_verification(flip=True)`
    这条兼容门。所以函数保留（夹具与 `record_verification` 的登记形态要它），
    但那条"自报数当门槛"的语义退役：

    - 给了 `sign_issuance.within_call` ⇒ 门槛与 `streak` / `need` / `streak_ok` 全部由
      :func:`_framework_holds` → :func:`sign_counting.count_registered` 从台账现数；
      `within_call` 原样留在 `holds["within_call_claim"]`（读数），它多了 / 少了一轮
      都不改变判定；
    - 没给 `sign_issuance`（历史直调 / 夹具 / `record_verification(flip=True)`）⇒
      :func:`consecutive_holds` 的历史兼容门，一个字没动（它数台账尾部发生过什么，
      与这条退役门无关；改它会把"打回之后又起转"那一档读宽）。

    判定口径因此与生产落地那一步同一个实现；这条函数的门只剩"台账现数"一种。
    """
    issuance = dict(sign_issuance or {})
    claim = issuance.get("within_call")
    if claim is None:
        return consecutive_holds(
            root, str(row.get("stmt_id") or row.get("statement_id") or ""), proof_no=proof_no)
    holds = _framework_holds(
        root, row, need=int(issuance.get("need") or verifications.SIGN_STREAK_NEED),
        review_call=str(issuance.get("review_call") or ""), proof_no=proof_no)
    try:
        holds["within_call_claim"] = max(0, int(claim))
    except (TypeError, ValueError):
        #: 报的不是一个整数 ⇒ 读数记成"读不出来"（None），判定照旧只由台账定。
        holds["within_call_claim"] = None
    return holds


def sign_statement(store: Any, *, row: Mapping[str, Any], proof_text: str,
                   path: Path | None = None, proof_no: Any = None,
                   sign_issuance: Mapping[str, Any] | None = None,
                   append_ledger: bool = True, by: str = "") -> dict[str, Any]:
    """把一签写回 `statements` 那一行里那一条证明的第 3 位（与台账同一次写）。

    ## 2026-11-22（BASELINEFIX）：这是迁就历史直调 / 夹具的写口，生产不走它

    生产在册落地那一步是 :func:`land_sign_without_ledger`（只颁签 + 只落块，不碰
    `statements`）：`secretary_sign.py:527-531` 逐字写着「`sign_statement` 保留给历史
    直调 / 夹具（`flip=True` 那条兼容门）」，而业主 2026-11-08 的口径是「V 现在只对手稿
    负责」。本函数今天的全部调用者只有两个：`record_verification(flip=True)`
    （`v_ledger_write.py:398/411` 的兼容门）与测试夹具。

    判据 `tests/test_sign_statement_does_not_read_the_callers_number.py::test_e_*` 按 AST
    钉住这条调用面：src 里除 `record_verification` 之外再长出一个调用点就会红 ——
    新增生产调用点必须同时回答"为什么不走生产落地那一步"，而不是悄悄多一个写
    `statements` 的口。

    ## 这一格为什么原来永远是 False
    第 3 位的唯一写者是 B 的 `register_statement`，而它按设计不替 V 签字（`BIT_OWNERS`：
    第 3 位的 owner 是 V）；V 自己的写口（本模块的 `record_verification`）当时只写台账
    那个文件，从来不碰 `statements`。于是"V 真的签了、台账上写着成立"与"命题那一行
    的 `reviewed` 位"之间没有连接：收工门的 R10 读位 ⇒ 恒 0。这一格就是那条断链的补口。

    ## 不借光（多证明模型）
    签名只翻被签的那一份（`proof_no`）的 `reviewed`；别的证明一个字不动。
    `proof_no > 1` 而命题行的证明清单里没有那一份 ⇒ 只落台账、不翻位（没有可翻的
    那一条证明），理由串写清 —— 不许把凭据记到 #p1 头上。

    ## 证明号：没给与给了坏值必须分开（2026-10-22 审计第 3 条）
    `proof_no=None` = 没给 ⇒ 按这一行自己记的那一格（老行只有 `rev` 时由
    :func:`proof_no_of` 按正名读，兼容、不迁移）；给了但 :func:`proof_no_strict` 认不出
    ⇒ 不追加台账、不改位，`reason` 点名"证明号认不出"。改前写的是
    `as_proof_no(proof_no) or proof_no_of(row)`：0 被折成这一行自己的号，
    于是"号给错了"与"号没给"在台账上长得一模一样。

    ## 顺序与回滚（为什么不是纯原子事务）
    台账是追加式文件、`statements` 是快照 JSON，两者不可能进同一个事务。所以取这个顺序：
    ① 在 `statements` 的事务里（事务已持有该表锁 ⇒ 并发签同一行时"读-改-写"是原子的）
       先追加台账那一行；② 改内存里那一行（那条证明的 `reviewed=True` + 凭据换成本签）；
    ③ 提交。提交失败 ⇒ 把刚追加的那一行撤回（只撤我们自己的那一行），整笔"没发生"；
    撤回不了 ⇒ 留着台账行并如实报"位没写成"—— 签名确实发生过，抹掉它比留一条
    "位没跟上"更坏；而读侧（`review_standing`）按台账现算，所以断链不会因此复现。

    ## `before = -1` 不再兼任两义（2026-10-22 审计第 5 条）
    改前 `before` 既是"追加前的字节数"又是"到底试没试过追加"：追加本身失败时它还是 -1，
    于是理由串照样写"台账那一行留着（签名确实发生过）"—— 而盘上一个字节都没有。
    现在追加落在哪一态由 `append_state` 单独记（`not_attempted` / `appended` / `failed`），
    理由串据此分三句；`re_sign_required` 说清调用方是不是必须重签（只有"没落地"才要）。

    返回键：`written` / `reason` / `rolled_back` / `grade` / `statement_id` / `proof_no` /
    `proof_sha256` / `append_state` / `re_sign_required` / `kind_upgrade` / `upgrade_note` /
    `grade_recomputed` /
    `streak` / `need` / `streak_ok`（业主 2026-10-29 的连续读数；键集合固定 ——
    "这一格没有读数"与"这一格是 0"必须由键的存在区分开）。
    `written=False` 的四种来路各有
    理由串：签不住第 3 位（不改位）、连续次数不够（不改位）、秘书没发签（不改位）、
    命题不在册或那一份证明不在（没有可写的行）、
    追加失败（连台账那一行都没写）、事务失败（附回滚结果）。

    ## D-69：同一笔事务里把 `kind` 跟着这一签抬上去
    见 :func:`_kind_upgrade_from_signature`。它只改 `kind` 那一格（起点只认 `conjecture`），
    判不了就一个字节都不动；抬了的时候 `kind_upgrade` / `upgrade_note` 两格把依据
    （`verifications/<命题号>.jsonl#v-…`）写出来，读的人不用去翻台账才知道凭什么。

    ## 第 1、2 次只落台账、不翻位（业主 2026-10-29 的 A 段）
    这一签先追加进台账（那是正本），然后从台账现数尾部连续成立次数
    （:func:`consecutive_holds`，含刚追加的这一行）：数到 `SIGN_STREAK_NEED` 次才翻位，
    否则 `written=False` + 理由串点名"还差几次" —— 台账那一行照样在，
    `append_state="appended"`、`re_sign_required=False`（"次数不够"不是"没落地"）。
    计数放在追加之后、且只有这一处：`draft/124` §一② 点名的那种第二份账
    （"位上说签了、台账只签一次"）就是"行局部谓词自己数次数"长出来的。

    ## `sign_issuance`：秘书持有"发不发签"的决定（业主 2026-10-29）
    调用方问过秘书 ⇒ 把那份三态读数递进来（:meth:`Secretary.decide_sign_issuance` 的返回）。
    `checked` 为假（没缝 / 超时 / 台账读不成 / 没装配）或 `issue` 为假 ⇒ 不翻位，
    理由串逐字写出秘书那一句：`checked=False` 绝不被读成"没问题"
    （`draft/125` §三：装配没接上时秘书判定必须报 `checked=False`，且不放签）。
    `None` = 调用方没有问过秘书（老调用点 / 夹具 / 直接调本函数那一档）⇒ 只按连续闸判，
    这一档是兼容门，不是第二套判据。

    ## `sign_issuance.within_call`：调用方自报的轮数 —— 2026-11-22 起只是读数

    这个键的来路是 `AgentV` 的连判循环（每一轮报"这一趟的第几轮"），它是自报读数，
    不是台账数。2026-11-02 到 2026-11-22 之间它曾是本函数唯一的门槛（`>= need` 就翻位，
    台账一个字都不核）；业主 2026-11-17 的裁定「是系统计数落签」把它撤了。现在
    `streak` / `need` / `streak_ok` 三格由 :func:`sign_counting.count_registered` 从台账
    现数（同一份正文、同一 `review_call` 内 `review_pass=1..need` 连续 clean；签的
    `passes` 按同一 `review_call` 取，绝不跨趟拼接），`within_call` 只原样留在读数里
    （`holds["within_call_claim"]`）—— 它多了 / 少了一轮都不改变判定。
    不给这个键时走 `consecutive_holds`（台账尾部连续数，历史兼容门，不是送审路径）。
    判定口径见 :func:`_holds_for_the_issuance`。

    ## `append_ledger=False`：台账那一行已经由调用方落了（业主 2026-10-29 追加口径）
    V 不再自己发签：`AgentV.verify_proof` 只落台账（`record_verification(flip=False)`），
    然后由 V 的秘书判定并调本函数翻位（`Secretary.decide_sign_issuance` 的落地那一步）。
    那时台账那一行已经在盘上（它是正本、先落），本函数只做"翻位"这一半 ⇒ `append_ledger=False`：
    不再追加（否则同一签在台账上出现两次），`append_state="appended_by_caller"`，
    异常分支也不撤回（不是我们追加的，没有可撤的）。
    """
    sid = str(row.get("stmt_id") or row.get("statement_id") or "")
    # 证明号：调用方给的那个（`proof_no`）；没给就按这一行自己记的那一格 —— 老行只有
    # `rev` 时由 `proof_no_of` 按正名读（兼容，不迁移）。
    out: dict[str, Any] = {
        "written": False, "reason": "", "rolled_back": False, "grade": "",
        "statement_id": sid, "proof_no": None,
        "proof_sha256": str(row.get("proof_sha256") or ""),
        #: 台账那一行落在哪一态（三态，不许折平）：
        #: `not_attempted` = 这一支根本不追加（签不住第 3 位 / 号认不出）；
        #: `appended` = 真追加了一行（撤回与否另看 `rolled_back`）；`failed` = 追加本身失败；
        #: `appended_by_caller` = 调用方先落了那一行（`append_ledger=False`：V 的秘书那条路），
        #: 本函数只翻位、不撤回。
        "append_state": "not_attempted",
        #: 调用方是不是必须重签：只有"这一签没有落在台账上"（追加失败 / 已撤回）才为真。
        "re_sign_required": False,
        #: D-69：这一签有没有把 `kind` 抬上去（形状与秘书那一支的升档痕迹相同）：
        #: `{}` = 没抬（起点不是 conjecture / 凭据不够 / 位算不出来），那三档都不改盘。
        "kind_upgrade": {},
        #: 抬档的读数原话（「因 V 判成立而抬档：conjecture→theorem（依据 …）」）；
        #: 没抬时是空串。它不写进 `reason`：`reason` 只留"这一签没落成"的那几档。
        "upgrade_note": "",
        #: 档位回填（业主 2026-11-04）：这一签有没有把 `evidence_kind` 按现行签重算上去。
        #: `{}` = 没动（已经是那一档 / 凭据不够 / 那一刻不适用），那几档都不改盘；
        #: 非空时形状见 `_grade_recomputed_from_signature` 的 `reading`。
        "grade_recomputed": {},
        #: 连续读数（门槛的唯一来源是台账）：给了 `sign_issuance.within_call` 时由
        #: :func:`sign_counting.count_registered` 现数这一趟（`within_call` 只作
        #: `within_call_claim` 读数，不参与判定 —— 2026-11-22 退役那条自报门槛）；
        #: 不给时是台账尾部连续成立次数（`consecutive_holds`，历史兼容门）。
        #: 三个键无条件存在。
        "streak": 0, "need": verifications.SIGN_STREAK_NEED, "streak_ok": False,
        #: 业主 2026-11-01：这一签的侧文件（`out/vsigns/<artifact_sha>.json`）落成了没有。
        #: 三态与 `vsigns.write_sign` 同形：`written` / `idempotent` / `conflict` /
        #: `archive_error`（归档失败不回滚）/ `reason` / `path`。签文件写不成时本函数
        #: 整笔失败（位也不会翻），所以"`written=True` 而 `vsign.written=False`"只可能
        #: 是"这一份签早就在盘上、逐字相同"（`idempotent`）这一档。
        "vsign": {},
        #: 2026-11-03（件二）：翻位前那道正文闸的读数 —— `matched` / `missing_body` /
        #: `sha_mismatch`。空串 = 还没走到那道闸（前面的分支已经返回）。
        "body_gate": "",
    }
    try:
        no = proof_no_of(row) if proof_no is None else proof_no_strict(proof_no)
    except VerificationError as exc:
        out.update(re_sign_required=True,
                   reason=(f"{exc}；第 3 位一个字没动，台账里也没有这一签"))
        return out
    out["proof_no"] = no
    if not row_signable(row):
        out["reason"] = ("这一签签不住第 3 位（verdict 不是「成立」，或有未解决的 error）"
                         "⇒ 位不动：没签住的字不该改任何读数")
        return out
    ledger = path or verification_ledger_path(store.root, sid)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    append_state = "not_attempted"
    #: 追加前的字节数（只有 `append_state == "appended"` 时才有意义，撤回按它截断）。
    before = -1
    try:
        with store.tx("statements", actor=f"verifier-{row.get('verifier') or 'V'}",
                      note=f"verify.sign:{sid}#p{no}") as tx:
            # 按号定位走查口（口径一）；快照传 `tx`（同一个 `rows(table)` 协议）。
            # 锁内读失败仍照旧抛出（查口把异常收成 checked=False → 这里翻回一次抛出，
            # 否则「读不到」会被下面读成「没有这一行」）。
            by_id = SL.by_id(tx, stmt_id=sid)
            if not by_id["checked"]:
                err = by_id.get("error") or {}
                raise RuntimeError(f"`statements` 读不出来（{err.get('type') or '?'}: "
                                   f"{err.get('message') or by_id.get('reason') or '?'}）")
            found = by_id["row"] if by_id["found"] else None
            if not append_ledger:
                # 台账那一行是调用方先落的（V 的秘书那条路）：这里一个字都不追加。
                append_state = "appended_by_caller"
                out["append_state"] = append_state
            else:
                try:
                    before = _append_verification(ledger, row)
                except OSError:
                    # 追加本身失败：记下这一态再往外抛（理由串要据此说"整笔没发生"，
                    # 不许说"签名确实发生过"）。
                    append_state = "failed"
                    raise
                append_state = "appended"
                out["append_state"] = append_state
            if found is None:
                out["reason"] = (f"`statements` 里没有命题 {sid} ⇒ 只落了台账（签名）那一行，"
                                 "第 3 位没有可写的行")
                return out
            if no > 1 and no not in {n for n, _ in proof_list(found)}:
                out["reason"] = (f"命题 {sid} 的证明清单里没有 #{no}（`{PROOFS_KEY}` 那一条）"
                                 "⇒ 只落了台账那一行；第 3 位不翻（不许把这一签记到 #p1 头上）")
                return out
            # ---- 业主 2026-10-29：连续 N 次成立才翻位（第 1、2 次只落台账）----
            #
            # 2026-11-22（BASELINEFIX）：这一格的门槛只有一个来源 —— 台账现数。
            # 改前 `sign_issuance.within_call` 一旦给出就只看调用方报的那个数
            # （`streak_ok = bool(within_call >= need)`），框架一个字都不核；而它是
            # 秘书从 V 那一趟循环里拿到的自报轮数（业主 2026-11-17：「是系统计数
            # 落签」）。现在与生产落地那一步（`land_sign_without_ledger`）同一个实现：
            # `_framework_holds` → `sign_counting.count_registered`；`within_call` 只作
            # 读数（`within_call_claim`），它多了 / 少了一轮都不改变数出来的数。
            # 不给 `sign_issuance`（旧直调 / 夹具 / `record_verification(flip=True)`）
            # 时走 `consecutive_holds` 的历史兼容门，那一档一个字没动。
            holds = _holds_for_the_issuance(
                getattr(store, "root", ""), row, proof_no=no, sign_issuance=sign_issuance)
            out["streak"] = int(holds.get("streak") or 0)
            out["need"] = int(holds.get("need") or verifications.SIGN_STREAK_NEED)
            out["streak_ok"] = bool(holds.get("streak_ok"))
            if sign_issuance is not None and not (
                    bool(sign_issuance.get("checked")) and bool(sign_issuance.get("issue"))):
                # 秘书没有发签（没缝 / 超时 / 台账读不成 / 它自己判了不发）。
                # 这一档与"次数不够"必须分开说：前者是"没有人发这一签"，后者是"还差几次"。
                out["reason"] = ("秘书没有发这一签（"
                                 + ("checked=False："
                                    if not bool(sign_issuance.get("checked")) else "")
                                 + f"{str(sign_issuance.get('reason') or '没有给理由')}）"
                                 "⇒ 只落了台账那一行，第 3 位不翻")
                return out
            if not signs_bit3(row, streak=holds):
                out["reason"] = (f"「成立」{out['streak']}/{out['need']}"
                                 f"（同一份正文 sha {str(row.get('proof_sha256') or '')[:12]}…）"
                                 "⇒ 门槛还没到：只落了台账那一行，第 3 位不翻"
                                 "（门槛由框架按这一趟送审自己数；跨趟不累计）")
                return out
            # ---- 2026-11-03（件二）：翻位前必须核"这一份正文存在，且就是签覆盖的那一份" ----
            #
            # 86 的现场：`stmt:000013` 的 `proof_text` 是空串（B 先按"不带正文"拿号，
            # 正文等 V 签完再登记），而 V 的秘书按 `row.proof_sha256=ed35…` 调本函数 ⇒
            # 改前这里不看命题行有没有正文，直接把 `reviewed_by_proof["1"]` 写成 true。
            # 于是"没有正文（也就没有正文 sha）"被读成"第 1 份已签"。
            #
            # 判据（业主 2026-11-03）：第 3 位翻真要求"该份正文存在，且它的 sha 与这一签
            # 覆盖的 sha 相同"。两条缺一 ⇒ 位不翻，理由串点名缺哪一条 —— 不静默跳过，
            # 也不拿"签过了"冒充"命题行里有这一份"。
            #
            # 但"位不翻"不等于"签不颁"：两阶段录入是 B 先拿号、V 先签、B 再把正文写进
            # 命题行（2026-11-02 口径），B 靠 `out/vsigns/<正文 sha>.json` 按 sha 认领。
            # 所以下面仍调 `_vsigns_write_after_flip`（写签文件 + 落手稿块），只是跳过
            # `_reviewed_statement_row`/`tx.upsert` 那一半。
            body_in_row = proof_text_of(found, no)
            signed_sha = str(row.get("proof_sha256") or "")
            body_gate = "matched"
            if not str(body_in_row or "").strip():
                body_gate = "missing_body"
                out["reason"] = (
                    f"命题 {sid} 的第 {no} 份证明没有正文（`proof_text` / `{PROOFS_KEY}` 都读不到）"
                    " ⇒ 这一签没有可盖的正文：第 3 位不翻（`reviewed_by_proof` 不写这一份），"
                    "签照旧颁发，等 B 把正文写进命题行之后按正文 sha 认领")
            else:
                body_sha = _sign_sha(str(body_in_row))
                if not signed_sha or body_sha != signed_sha:
                    body_gate = "sha_mismatch"
                    out["reason"] = (
                        f"命题 {sid} 的第 {no} 份证明正文 sha {body_sha[:12]}… 与这一签覆盖的 "
                        f"sha {signed_sha[:12] or '（空）'}… 不符 ⇒ 第 3 位不翻"
                        "（签的不是现在这一份正文）；签照旧颁发，等正文换过来之后按 sha 认领")
            out["body_gate"] = body_gate
            # ---- 业主 2026-11-01：签落成一份按正文 sha 命名的侧文件 -------------------
            #
            # 位置（2026-11-10 调整）：「翻位判据 → 签发侧文件 → 按签判 kind / 重算等级
            # → upsert」，全在同一个事务里。改前这一步在 upsert 之后、判 kind 之后；
            # 于是 `_kind_upgrade_from_signature` 写留痕时签文件还不存在，那一句
            # `basis` 缺 witness（只有台账行）。之后 B 任何一次写都会把它"刷新"成
            # 另一句 ⇒ "再交一次不改盘"的幂等被打破（D-37 criterion2 的现场）。
            # 先落签文件之后，签名那一笔的 basis 与 B 那一支逐字同源（裁量 ②），
            # 刷新的判据自然变成空操作。三条不变的理由照旧：
            # ① 位与签同生共死：`<sha>.json` 写不成 ⇒ 抛出去让整个事务回滚（连同台账那
            #    一行一起撤回）——"签没落地"与"签落了但没档"是两件事，前者要能重试；
            # ② 归档（`issued.json`）失败「不许」回滚：签文件已经写在盘上，
            #    删掉刚写好的签文件是抹掉发生过的事（`vsigns` 的模块 docstring 那一节）；
            # ③ 内容全部从台账现读（`_vsign_payload`），不复制全文、不吃调用方状态。
            sign_out = _vsigns_write_after_flip(
                store, row=dict(row), ledger=ledger, statement_id=sid, proof_no=no,
                sha=str(row.get("proof_sha256") or ""), holds=holds,
                append_ledger=bool(append_ledger), by=str(by or ""),
                # 2026-11-04（甲）：载体随台账行来（`record_verification(manuscript=…)`）。
                manuscript=str(row.get("manuscript") or ""),
                # 提交记号写 `tasks`，不能在 `store.tx("statements")` 里开第二笔
                # （会撞同一把 `counters` 锁）；这一笔由下面事务外的收口补上。
                submit=False)
            out["vsign"] = dict(sign_out)
            if not (sign_out.get("written") or sign_out.get("idempotent")):
                if sign_out.get("refused_below_need"):
                    # 两道守卫不一致（`signs_bit3` 说够、`write_sign` 说不够）：位照它自己的
                    # 判据翻，「不写签」，并把这件事留在 `vsign.reason` 里。
                    #
                    # 为什么这一档不许把整笔弄失败：`signs_bit3` 是第 3 位的「唯一」硬闸
                    # （`tests/test_v_sign_gate_streak.py::test_z1_removing_the_streak_gate_makes_the_first_hold_flip` 用"把 `streak_ok` 打成恒真"
                    # 做反真空负控）。若这里改成抛异常回滚，那道闸就再也量不出来了 ——
                    # 一条"签没写"的读数是可见的，而一条"闸拆了也看不出来"的判据是不可修的。
                    out["vsign"]["reason"] = str(sign_out.get("reason") or "")
                else:
                    # 签文件没落地（写不成 / 冲突）⇒ 整笔失败（位不许在"没有任何档"的情况下翻上去）。
                    raise VerificationError(
                        "签文件没写成：" + str(sign_out.get("reason") or "没有理由"))
            if body_gate == "matched":
                new = verifications._reviewed_statement_row(found, row, proof_text=proof_text, proof_no=no,
                                              streak=holds)
                # ---- D-69：V 判「成立」⇒ 同一笔事务里按证据位把 `kind` 现算一遍。
                #
                # 位置在"位已经翻上去"之后、`tx.upsert` 之前：台账那一行刚追加进
                # `verifications/<号>.jsonl`，`kind_following_grade` 现在读得到那一签；
                # 判不了（`held` / `unreadable`）就原样不动（三态：不抬，也不降）。
                upgraded = verifications._kind_upgrade_from_signature(
                    new, root=getattr(store, "root", ""), verifier=f"verifier-{no}")
                new = upgraded["row"]
                # ---- 等级现算（2026-11-05 改口径）：只算等级、不再写档位 --------------
                #
                # 位置与 D-69 那一格并列、`tx.upsert` 之前：台账那一行刚追加进
                # `verifications/<号>.jsonl`，`proof_review_gap` 现在读得到它。
                # 这一格只把"按现行签现算的等级 + 凭什么"写进回执（`GRADE_RECOMPUTED_KEY`）；
                # `evidence_kind` 一个字不动 —— 它只是历史列，判定面读等级。
                recomputed = verifications._grade_recomputed_from_signature(
                    new, root=getattr(store, "root", ""), proof_no=no)
                if recomputed["reading"]:
                    # 2026-11-06：这一格不只算等级，还会按穷举通道落第 1 位
                    # （`numeric=verified`）—— 那一份 `row` 必须一起落盘，否则
                    # "算过 theorem"只活在返回值里，盘上仍是 pre_theorem。
                    new = dict(recomputed.get("row") or new)
                    new[GRADE_RECOMPUTED_KEY] = dict(recomputed["reading"])
                tx.upsert("statements", new, note=f"verify.sign:{sid}#p{no}")
                out.update(written=True, grade=str((new.get("bits") or {}).get("grade") or ""),
                           kind_upgrade=dict(upgraded["kind_upgrade"]),
                           upgrade_note=str(upgraded["note"]),
                           grade_recomputed=dict(recomputed["reading"]))
    except Exception as exc:  # noqa: BLE001 - 写位失败要如实报（签名那一行可能已经在盘上了）
        rolled = (_rollback_append(ledger, before, row)
                  if append_state == "appended" and before >= 0 else False)
        if append_state == "failed":
            reason = (f"台账那一行也没写成（{type(exc).__name__}: {exc}）⇒ 第 3 位没写成，"
                      "整笔没发生（可以重试；必须重签）")
        elif rolled:
            reason = (f"第 3 位没写成（{type(exc).__name__}: {exc}）；"
                      "台账那一行已撤回（整笔没发生，可以重试）⇒ 必须重签")
        elif append_state in ("appended", "appended_by_caller"):
            reason = (f"第 3 位没写成（{type(exc).__name__}: {exc}）；"
                      "台账那一行留着（签名确实发生过）；读侧按台账现算，不按这一位")
        else:
            # 连追加都没走到（例如事务加锁失败）：台账里没有这一签，整笔没发生。
            reason = (f"第 3 位没写成（{type(exc).__name__}: {exc}）；"
                      "台账那一行没有追加（整笔没发生）⇒ 必须重签")
        out.update(
            written=False, rolled_back=bool(rolled), append_state=append_state,
            re_sign_required=(not rolled
                              and append_state not in ("appended", "appended_by_caller")),
            reason=reason)
    # ---- 甲（2026-11-11）：签触发提交在事务外补（事务里写 `tasks` 会撞同一把锁）----
    #
    # 只在这一签真的颁发了（written / idempotent）时做；写不成只落读数，
    # 不许把"签了"这件事带走（「签了但没提交」与「没签」必须分得开）。
    _vsign_done = dict(out.get("vsign") or {})
    if _vsign_done.get("written") or _vsign_done.get("idempotent"):
        try:
            from . import manuscriptsubmission as _MS

            _sign_doc = dict(_vsign_done.get("sign") or {})
            _sub = _MS.mark_sign_submitted(
                store=store, root=getattr(store, "root", "") or ".",
                artifact_sha=str(_sign_doc.get("artifact_sha")
                                 or row.get("proof_sha256") or ""),
                artifact_path=str(_sign_doc.get("artifact_path")
                                  or row.get("manuscript") or ""))
            if isinstance(out.get("vsign"), dict):
                out["vsign"]["submission"] = dict(_sub)
        except Exception as exc:  # noqa: BLE001 —— 提交读数坏了不许把签带走
            if isinstance(out.get("vsign"), dict):
                out["vsign"]["submission"] = {
                    "checked": False, "written": False, "already": False,
                    "via": "", "why": (f"签触发提交没跑成（{type(exc).__name__}: "
                                       f"{exc}）⇒ 这一份这次没置为已提交（不是「没签」）")}
    # ---- 缺陷 B（2026-11-05）：签发落成之后，给 B 开一条「必须收录」义务 ----
    #
    # 位置在事务之外（理由见 `_registration_after_vsign`：事务里开板项会撞锁）。
    # 87 的现场：`reports/f-proof-000000.md` 上有成立的签，而 `statements:000000` 仍是
    # 「正文=0 / reviewed=false」—— 签发之后没有任何东西把"这一份还没入库"摆到 B 面前
    # （D 从头没派 B 收录；B 在 87 里只被派过 1 次，还是文献侧的 `t-000027`）。
    out["registration"] = _registration_after_vsign(
        store=store, root=getattr(store, "root", ""), vsign=dict(out.get("vsign") or {}),
        statement_id=sid, proof_no=int(no),
        sha=str(row.get("proof_sha256") or ""), wake=True)
    return out


# 跨模块引用放在文件末尾：这些名字的实现在别的模块里，而两个模块可能互相
# 引用（顶层 `from .x import y` 在环里会在对方还没定义完时执行）。引用点
# 全部在函数体里，所以只要定义都跑完了，谁先被导入都拿得到。
from . import verifications  # 门面字典：被打桩的名字经它取
from .v_vocab import (  # noqa: F401 — 实现在 v_vocab.py
    GRADE_RECOMPUTED_KEY,
    PROOFS_KEY,
)
from .v_paths import (  # noqa: F401 — 实现在 v_paths.py
    VerificationError,
    _sign_sha,
    proof_list,
    proof_no_of,
    proof_no_strict,
    proof_text_of,
    verification_ledger_path,
)
from .v_ledger_write import (  # noqa: F401 — 实现在 v_ledger_write.py
    _append_verification,
    _rollback_append,
)
from .v_rowread import (  # noqa: F401 — 实现在 v_rowread.py
    row_signable,
    signs_bit3,
)
from .v_streak import (  # noqa: F401 — 实现在 v_streak.py
    consecutive_holds,
)
from .v_sign_flip import (  # noqa: F401 — 实现在 v_sign_flip.py
    _registration_after_vsign,
    _vsigns_write_after_flip,
)
