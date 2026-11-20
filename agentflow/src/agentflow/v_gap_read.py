# -*- coding: utf-8 -*-
"""凭据缺口读数（pending/短回路）。

2026-11-20（VERSPLIT2）：`v_gap_read.py` 是从 `verifications.py` 搬出的 7 块 / 784 行（块
逐字未动，逐名 AST 全等在 `temp/versplit2/` 可复算）。对 32 个被测试打桩的名字，读
一律写成 `verifications.<name>` —— 门面字典在调用那一刻才查，所以
`monkeypatch.setattr(verifications, ...)` 仍然到得了这里（`from .x import X` 是快照，
补丁到不了）。跨模块 import 放在文件末尾：模块之间有互相引用，定义全跑完再 import
才解得开环。
"""

from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from . import evidencebits as EB  # 等级的唯一派生口（`derive_grade` / 反算表）
from . import jsonlfile as JF
from . import schema as S  # 编号形态的唯一来源（六位 / 旧四位读侧兼容）
from .proofloc import DEFAULT_PROOF_NO  # canonical 证明号只有一个出处（`proofloc`）


def _gap_from_pending(out: dict[str, Any], checks: list[dict[str, Any]],
                      got: Mapping[str, Any], *, statement_id: str,
                      manuscript_id: str = "",
                      root: str | Path = "") -> dict[str, Any]:
    """:func:`_pending_signed` 认到那一签之后，把 `proof_review_gap` 的读数摊开。

    判据与"台账那一路"同一条（`signs_bit3`）：`成立` 且没有未解决 error、且引用核实
    没有挡住的那一条，才算签住（2026-10-27 收口）。

    改前这一行是 `row_ok = (verdict == "成立")` —— 与它上面这句话相反：`pending_sign`
    只回四格，`unresolved_errors` / `citation_checks` / `citation_gate` 全被丢掉，
    于是"成立 + 有未解决 error"与"成立 + 引用核实判不了"在这一路上都读成签住了，
    而同一行内容放进 `verifications/<命题号>.jsonl` 会被 `signs_bit3` 拒。同一份证据、
    两个落点、两套判定 —— 这就是要收掉的那条缝。

    ## 2026-11-11（p283）：认领完成之后，这一签不再是"待登记的那一签"

    2026-11-10 的裁量是「pending 只够过准入闸、不够升 kind」—— 它说的是“命题还没在册
    时” V 审的那一签（`pending` 行上还没有号，升档留痕指不出"这条命题的哪一签"）。
    认领（`vsigns.bind_pending_claim`）把 `statement_id` 回写之后，这一签已经绑在这条
    命题上了：来路仍是 pending 台账（文件不搬），但它就是“本条命题自己的签”。
    所以 `pending` 这一格按三态写：

    - `pending=True`：还没认领（行上没有 `statement_id`），或者认给的是“别的”号；
    - `pending=False` + `claimed=True`：认给的就是本条命题，且载体稿号与行上的
      `manuscript_id` 对得上（两边都有号时；老行没记稿号 ⇒ 认领本身就够）；
    - 载体稿号与行上稿号不一致 ⇒ 仍算 `pending`：那一签签的是另一份稿，
      不是这一条命题的稿上的签（判据 `vsigns.manuscript_id_of`，与签块第 9 格同源）。

    ## 2026-11-11（p284）：认领只解除「来路」那一层，不解除「票数与 sha」那一层

    p283 之后 `ok` 不再只由 `row_signable` 说了算 —— 认领过的 pending 行会真的被当作
    升档依据（`evidencebits.kind_following_grade(allow_pending=False)`）。所以它必须过
    台账那一路的同一道闸（:func:`_pending_claim_streak`）：尾部连续
    `SIGN_STREAK_NEED` 票「成立」、这几票签的是同一份正文、且与行上正文的 sha 一致
    ⇒ 才 `ok=True`。一票 / 两票 / 票数够但最新一票签的是别的正文 ⇒ `state="holding"`、
    `ok=False`，`why` 里写清还差几票（或哪一份 sha 对不上）。

    未认领的 pending（`pending=True`）仍是旧口径：`ok` 只走行局部（D-34 的准入闸面），
    抬档那一格由 `pending=True` 自己挡住 —— 那条路一个字没动。
    """
    row = dict(got.get("row") or {})
    row.setdefault("verdict", str(got.get("verdict") or ""))
    # pending 那一签按对象 sha 认领，它审的时候命题还没登记 —— 命题台账那一路的
    # "连续 3 票"在盘上没有等价物，但同一叠 pending 台账里就有（同一份正文的
    # 那几行）：票数与"是不是同一份正文"由 `_pending_claim_streak` 数。
    # `row_ok` 仍只判行局部那一半（成立 + 无未解决 error + 引用不挡）。
    row_ok = row_signable(row)
    verdict_word = str(got.get("verdict") or "")
    out["ledger"] = str(got.get("ledger") or "")
    out["verification_id"] = str(out["ledger"]).split("#")[-1]
    #: 这一签挂的是第几条证明（多证明模型，业主 2026-10-22）：pending 行自己记着号
    #: （`record_pending_sign` 写 `proof_no`），与台账那一支取 `chosen_no` 同一个口径
    #: （见 `proof_review_gap` 末尾 `chosen_no` 那一行）。
    #:
    #: 改前这一格没有任何一支写：`proof_review_gap` 走 pending 支时返回的 `proof_no`
    #: 恒是初始值 `None`。为什么这不是"少一格装饰"：`_grade_recomputed_from_signature`
    #: 把 gap 的这一格原样抄进 `_grade_recomputed.proof_no`（那条读数的形状写死在它的
    #: docstring 里，含 `proof_no`），而 `register_statement` 自 2026-11-05 起在"正文落行
    #: 之后、tx.upsert 之前"就调回填 —— 那一笔的签通常还只在 pending 台账里 ⇒ 改前
    #: 行上的 `_grade_recomputed.proof_no` 写成 `None`。`_read_proof_no` 对"没写号"的
    #: 约定仍是 canonical（缺省 ⇒ 1；给了坏值 ⇒ 0），所以那条读数丢的不是"号怎么读"，
    #: 而是"这一签挂的是哪一份"：读的人只能按 canonical 猜，分不出"真的是 #p1"与
    #: "写的人没填"（3640a508 起由本函数末尾那一行 `proof_no_of(row)` 补上）。
    out["proof_no"] = proof_no_of(row)
    out["verdict"] = verdict_word
    out["rows"] = 1
    out["sha_matches"] = True
    out["checked"] = True
    #: 来路那一格：这一份凭据是"命题还没在册时审的那一签"（纯读数；`ok` 的判据不变）。
    #: 升 `kind` 的那一格在 B 的登记 / 收录路上靠它把这一档分出来（`allow_pending=False`）。
    #:
    #: 2026-11-11（p283）：已认领给本条命题的那一签不是"待登记的一签" —— 认领回写的
    #: `statement_id` 与载体稿号都对得上时 `pending=False`、`claimed=True`（见 docstring）。
    claimed = str(row.get("stmt_id") or row.get("statement_id") or "").strip()
    claimed_here = bool(claimed) and claimed == str(statement_id or "").strip()
    carrier_mid = ""
    if claimed_here:
        try:
            from . import vsigns as _VS

            carrier_mid = _VS.manuscript_id_of(str(row.get("object_path") or ""))
        except Exception:  # noqa: BLE001 —— 认不出载体号 ⇒ 不做第二道比较（认领本身仍算）
            carrier_mid = ""
    row_mid = str(manuscript_id or "").strip()
    own = bool(claimed_here) and (not row_mid or not carrier_mid or row_mid == carrier_mid)
    out["claimed"] = bool(own)
    out["carried_manuscript_id"] = carrier_mid
    out["pending"] = not bool(own)
    # 票数与"三票同一份正文"（p284）：认领之后这一签会被当作升档依据，所以它必须过
    # 台账那一路的同一道闸。未认领那一档只作读数（抬档由 `pending=True` 挡住）。
    streak_read = verifications._pending_claim_streak(
        got.get("passes") or (), row.get("proof_sha256"),
        review_call=str(row.get("review_call") or ""))
    out["streak"] = int(streak_read.get("votes") or 0)
    out["need"] = int(streak_read.get("need") or verifications.SIGN_STREAK_NEED)
    out["streak_ok"] = bool(streak_read.get("ok"))
    # 签不住有两种来路，拒信必须分开说：结论压根不是「成立」，还是判了「成立」却
    # 被 `signs_bit3` 的三条（未解决 error / 引用核实 / 没查成）之一挡住。
    if verdict_word != "成立":
        blocked = f"结论是 {verdict_word!r}（要「成立」）"
    else:
        blocked = ("结论写了「成立」但签不住（" + _bit3_blockers(row) + "）")
    checks[1].update(ok=bool(row_ok),
                     detail=(f"{out['ledger']}（命题还没在册时审的那一签）"
                             if row_ok else f"{out['ledger']}：{blocked}"))
    checks[2].update(ok=bool(row_ok),
                     detail=("按这一份正文的 sha 认领到（待登记的那一签）"
                             if row_ok else "签的不是这一份"))
    if not row_ok:
        out["state"] = "rejected"
        out["why"] = (f"命题 {statement_id} 的证明在 pending 台账里那一签：{blocked}"
                      "⇒ 复核过、签不住")
        return out
    if own and not bool(streak_read.get("ok")):
        # 认领完成 = 这一签会被当成"本条命题自己的签" ⇒ 它必须与台账那一路同门槛：
        # 满 `SIGN_STREAK_NEED` 票、同一份正文。一票 / 两票 / 票数够但 sha 不一 ⇒ 不抬。
        votes = int(streak_read.get("votes") or 0)
        need = int(streak_read.get("need") or verifications.SIGN_STREAK_NEED)
        if not bool(streak_read.get("same_sha")):
            blocked = (f"认给本命题的这一叠 pending 签里，最新一票签的不是本条正文"
                       f"（签的是 sha {str(streak_read.get('tail_sha') or '')[:12] or '（空）'}…，"
                       f"本条正文是 sha "
                       f"{str(row.get('proof_sha256') or '')[:12] or '（空）'}…）"
                       f"⇒ 不抬 kind：抬档要挂在满 {need} 票、同一份正文 sha 的真签上")
        else:
            blocked = (f"认给本命题的连续「成立」只有 {votes}/{need} 票"
                       f"（还差 {max(0, need - votes)} 票）⇒ 不抬 kind："
                       f"抬档要挂在满 {need} 票、同一份正文 sha 的真签上"
                       f"（这一签只落台账、不发签）")
        out["state"] = "holding"
        out["why"] = (f"命题 {statement_id} 的凭据在 `{out['ledger']}`：V 判过「成立」，"
                      + blocked)
        checks[1].update(ok=False, detail=(f"{out['ledger']}：{blocked}"))
        checks[2].update(ok=False, detail=("票数与正文 sha 还没同时到门槛："
                                           "这一签不算本条命题的定理凭据"))
        return out
    out["state"] = "signed"
    out["ok"] = True
    # 2026-11-14 RL1：指针以「正式颁发的那一签」为准（见 `_issued_verification_pointer`）。
    # 这一档（pending 台账）尤其要紧：同一份正文并发审两趟时，台账最后一条可能属于
    # 没发签的那一趟。`state` / `ok` / 票数一个字不动，只改凭据指回哪一行。
    if root:
        issued = verifications._issued_verification_pointer(
            root, str(row.get("proof_sha256") or ""))
        if issued.get("found"):
            out["verification_id"] = (str(issued.get("verification_id") or "")
                                      or out["verification_id"])
            out["ledger"] = str(issued.get("ledger") or out["ledger"])
    out["why"] = (f"命题 {statement_id} 的凭据在 `{out['ledger']}`：V 在命题还没在册时"
                  f"审过这一份并判「成立」（连续 {int(streak_read.get('votes') or 0)} 票、"
                  f"门槛 {int(streak_read.get('need') or verifications.SIGN_STREAK_NEED)} 票），"
                  "按这一份正文的 sha 认领到"
                  + ("（这一签已经认给本命题、载体稿号与行上一致 ⇒ 算本条命题自己的签，"
                     "不再是「待登记的那一签」）" if own else
                     "（「先签后登记」与「先登记后签」是同一件事）"))
    return out


def _bit3_blockers(row: Mapping[str, Any], *, streak: Any = None) -> str:
    """`signs_bit3` 为假时，逐条说清是哪一条挡住（拒信与读数的唯一措辞处）。

    `streak` 与 :func:`signs_bit3` 同义：行局部都过了、只有门槛还没到时，这一格
    必须把那句话写出来 —— 否则拒信会落进 `"判据判不了（读数不全）"` 那条兜底，
    读的人以为"有一格没读出来"，而实际只是"门槛还没到"。
    """
    why: list[str] = []
    if int(row.get("unresolved_errors") or 0) != 0:
        why.append(f"未解决的 error {int(row.get('unresolved_errors') or 0)} 条")
    problem = signing_gate_problem(row)
    if problem:
        why.append(f"引用核实没查成（{problem}）")
    blocked = citation_blocks(row)
    if blocked:
        why.append("引用核实挡住：" + "、".join(
            f"{e['stmt_id'] or '（没有号）'} 判 {e['verdict']}" for e in blocked))
    if row_signable(row) and not verifications.streak_ok(streak):
        got = _streak_number(streak)
        why.append(("门槛没读出来（这一格没查成 ⇒ 不发签）"
                    if got is None else
                    "门槛还没到（门槛由框架按这一趟送审自己数；跨趟不累计）"))
    return "；".join(why) or "判据判不了（读数不全）"


def _issued_verification_pointer(root: str | Path, artifact_sha: Any) -> dict[str, Any]:
    """这一份正文正式颁发的那一签指回台账的哪一行（纯读；`_kind_upgrade` 的指针源）。

    ## 为什么不能取"台账里最后一条 pending"（2026-11-14 真机 000041）

    `f-proof-000001` 上并发跑了两个 V 任务：20:55:26 的那一趟满 3 票发签（签文件的
    `ledger` 记 `...#u-000003`），20:57:25 的另一趟又落 3 条「成立」但没有发签
    （`landed=pending`、`charged=false`）。台账按行序取"最后一条"会拿到 `u-000006`，
    于是 `_kind_upgrade.basis` 里签文件被写成 `out/vsigns/<sha>.json#u-000006`、台账被
    写成 `...#u-000006`，而真正算数的那一签是 `u-000003` —— 同一行两个指针打架。

    这一格回答的就是"哪一签算数"：以 `out/vsigns/<正文 sha>.json` 的 `ledger` 为准
    （那个 sha 就是被签的正文；签文件是逐份证据，`issued.json` 是它的派生归档）。
    没有签文件、签文件没记台账、或读不出来 ⇒ `found=False`，调用方保留自己的指针
    （不编一条凭据，也不把"没查成"折成"没有签"）。

    返回 `{checked, found, ledger, verification_id, why}`。
    """
    out: dict[str, Any] = {"checked": False, "found": False, "ledger": "",
                           "verification_id": "", "why": ""}
    sha = str(artifact_sha or "").strip()
    if not sha:
        out["why"] = "没有正文 sha ⇒ 不知道问哪一签（不是「没有签」）"
        return out
    try:
        from . import vsigns as _VS   # 惰性：签文件目录只有一处口径
        got = _VS.sign_of(root, sha)
    except Exception as exc:  # noqa: BLE001 —— 读不出来 = 没查成
        out["why"] = f"签文件读不出来（{type(exc).__name__}: {exc}）⇒ 这一格没查成"
        return out
    out["checked"] = bool(got.get("checked"))
    doc = dict(got.get("sign") or {})
    if not got.get("found"):
        out["why"] = f"`{got.get('path') or sha}` 不在盘上 ⇒ 这一份正文没有颁过签"
        return out
    ledger = str(doc.get("ledger") or "").strip()
    if not ledger:
        out["why"] = ("签文件没记台账行（`ledger` 是空的）⇒ 指不出那一签是哪一行")
        return out
    vid = ledger.rsplit("#", 1)[-1] if "#" in ledger else ""
    out.update(found=True, ledger=ledger, verification_id=vid, why="")
    return out


def issued_sign_short_circuit(root: str | Path, *, proof_text: str = "",
                              manuscript_rel: str = "", sha: str = "") -> dict[str, Any]:
    """这一份正文是不是已经有正式颁发的签（D，2026-11-15：同一 sha 不重复买判定）。

    ## 为什么要有这一格

    真机同一份 `f-proof-000001.md`（正文 sha `0ac4b14c…`）被两条送审路径各判了一遍：
    2 趟 V × 每趟连判 3 转 = 6 条「成立」，签只有 1 个，第二趟 $0.030761 白花
    （`temp/analysis/10-concurrency-budget.md` §3/§4）。原因是"这个 sha 已有签"没有在
    送审判定入口被读到 —— 只有稿上的签块会在旧路里被认（`manuscript_sign_standing`），
    而签文件 `out/vsigns/<sha>.json` 这一份正式颁发的证据此前只有 RL1 的指针读它。

    唯一读口就是那份签文件的 `ledger`（内部走 :func:`_issued_verification_pointer`，
    与 RL1 同源）—— 不是台账里"最后一条成立"（并发两趟时它可能属于没发签的那一趟），
    也不是命题行的第 3 位（V 只对手稿负责之后它已不是 V 的输入）。

    ## 三态（fail-open 的方向写在这里）

    - `found=True` ⇒ 有正式颁发的签；`block_covers` 说"稿上那块签也读得到"
      （读到 ⇒ 旧路本来就会短接，调用方让它照旧走；读不到 ⇒ 这才是这一格要补的洞）。
    - `found=False` ⇒ 签文件缺失 / 没记台账 / 读不出来 ⇒ 照常判，不许当已签
      （旧盘与坏盘都走这一档；"没查成"留在这一个 `checked` 位上）。
    - `checked=False` ⇒ 连"问哪一份签"都没有答案（没给正文、手稿也读不出来）；
      `why` 里说清，调用方照常判。

    返回 `{checked, found, sha, ledger, verification_id, sign, block_covers, reason, why}`。
    """
    out: dict[str, Any] = {"checked": False, "found": False, "sha": "", "ledger": "",
                           "verification_id": "", "sign": {}, "block_covers": False,
                           "reason": "", "why": ""}
    key = str(sha or "").strip().lower()
    rel = str(manuscript_rel or "").strip().replace("\\", "/")
    raw = ""
    if not key:
        given = str(proof_text or "")
        if given.strip():
            key = _sign_sha(given)
        elif rel:
            try:
                raw = (Path(root) / rel).read_text(encoding="utf-8")
            except OSError as exc:
                out["why"] = (f"手稿 `{rel}` 读不出来（{type(exc).__name__}: {exc}）⇒ "
                              "不知道问哪一份签（不是「没有签」，照常判）")
                return out
            key = _sign_sha(raw)
    if not key:
        out["why"] = ("没给正文、也没有可读的手稿 ⇒ 不知道问哪一份签"
                      "（不是「没有签」，照常判）")
        return out
    out["sha"] = key
    # 稿上那块签读不读得到：读到则旧路自己会短接，这一格只补"读不到"的洞。
    if not raw and rel:
        try:
            raw = (Path(root) / rel).read_text(encoding="utf-8")
        except OSError:
            raw = ""
    if raw:
        try:
            from . import vsigns as _VS

            block = dict(_VS.manuscript_sign_reading(raw, manuscript_path=rel) or {})
            out["block_covers"] = bool(
                block.get("signed")
                and str(block.get("proof_sha256") or "") == key)
        except Exception:  # noqa: BLE001 —— 判不了块不等于没有签，继续问签文件
            out["block_covers"] = False
    pointer = verifications._issued_verification_pointer(root, key)
    out["checked"] = bool(pointer.get("checked"))
    if not pointer.get("found"):
        out["why"] = (f"这一份正文没有已颁发的签（{pointer.get('why') or '签文件不在盘上'}）"
                      "⇒ 照常判（不许当已签）")
        return out
    try:
        from . import vsigns as _VS

        sign = dict(_VS.sign_of(root, key).get("sign") or {})
    except Exception:  # noqa: BLE001 —— 指针已经读到了，签全文取不到就少给这一格
        sign = {}
    out.update(found=True, reason="already_signed", sign=sign,
               ledger=str(pointer.get("ledger") or ""),
               verification_id=str(pointer.get("verification_id") or ""))
    out["why"] = (f"这一份正文（sha {key[:12]}…）已经有正式颁发的签："
                  f"`{out['ledger'] or '（签文件没记台账）'}`；"
                  f"连续 {sign.get('streak', '?')}/{sign.get('need', verifications.SIGN_STREAK_NEED)} "
                  "次「成立」⇒ 同一份正文不再重复判")
    return out


def proof_review_gap(root: str | Path, row: Mapping[str, Any],
                     proof_no: Any = None) -> dict[str, Any]:
    """一条 `evidence_kind="proof_review"` 的命题有没有凭据 —— 纯读，不写任何东西。

    判据逐字来自 `schema.EVIDENCE_KINDS` 上面那段定义（2026-10-19 之前它只是注释，没有代码
    强制）：`proof_review` —— 证明经逐行审阅（`statements` 表的 `proof_text` 非空 + V 的
    `verifications` 里那一条签「成立」）。三条都要成立（缺哪条就报哪条，`why` 里说清）：
    1. `proof_text` 非空 —— 没有被审的那份证明，"审过"无从谈起；
    2. `verifications/<命题号>.jsonl` 里有一条盖住现行这一份正文的签（判定只走
       `review_standing`：那一份证明现在的 sha 有 `signs_bit3` 的签）；
    3. 那一签带着这一份正文的 `proof_sha256` —— 哈希回答"这份稿在你签完之后有没有被改过"。
    2026-10-22 口径（业主）：第 3 条是读数，不是授权凭证。所以 `ok=False` 有两种完全
    不同的来路，`state` 把它们分开：`stale`（签的是旧版 ⇒ 待复核）与 `rejected`
    （签的就是这一份、结论不是「成立」）。写入期闸只拒后者与"一次都没签"，见
    :func:`proof_review_gaps` —— "正文改过了"不许成为拒收理由。
    三态：读不到台账 / 坏行 ⇒ `ok=False` 且 `checked=False`（没查成，不是"通过"）；台账
    读得出、只是`一次都没签` ⇒ `checked=True`（查过了，结论是没凭据）。

    ## 任一份证明签住即放行（2026-10-22 审计最危险的一批，第 1 条）
    `evidence_kind` 是命题级的声明，而多证明模型里每一条证明各自有第 3 位
    （见 :func:`statement_review_reading`）⇒ 命题级凭据的判据是"至少一份证明 signed"。
    改前这里写死 `review_standing(..., proof_no=1)`：只认 canonical 那一份，于是
    `#p1` 未签、`#p2` 已成立的存量 `proof_review` 行既写不进去（闸整笔拒收），
    拒收之后撤回又抹掉台账那一行（同一批审计的两半）。
    逐条那一侧仍然分开：`state` / `proof_no` / `verification_id` / `sha_matches` / `why`
    说的是"当前这一份"（`proof_no` 参数；没给就按这一行自己记的号、没有就 canonical），
    于是拒信仍指得出是哪一份证明缺凭据，而不是一句"这一行不行"。

    返回键：`ok` / `checked` / `why` / `state` / `proof_no` / `statement_id` /
    `verification_id` / `verdict` / `round` / `unresolved_errors` / `sha_matches` /
    `ledger` / `rows` / `problems` / `checklist` / `pending` / `streak` / `need` /
    `streak_ok`；`checklist` 是逐项过关读数
    （`[{"item", "ok", "detail"}]`，三条与上面一一对应），只为拒信存在（业主 2026-10-19 的口径：
    "拒收消息要让人/模型一眼看出该补哪一项"），不参与判据 —— 写错只改可读性。
    `pending` 是"来路"那一格：True = 这一份凭据取自
    `verifications/pending/<正文 sha>.jsonl` 且“还没有认领”（命题还没在册时审的那一签，
    行上没有 `statement_id`），False = 取自 `verifications/<命题号>.jsonl` 那一行“或”
    取自一条已经认领给本条命题的 pending 行（2026-11-11 p283：认领之后它就是本条命题
    自己的签；`claimed` 那一格把这两种来路分开）。两者都算"签过"，但升 `kind` 的那一格
    在 B 的登记 / 收录路上不认“未认领”的 pending
    （`evidencebits.kind_following_grade(allow_pending=False)`）。
    `streak` / `need` / `streak_ok`（2026-11-11 p284）是 pending 那一支的票数读数：
    认领之后 `ok` 还要求 `streak >= SIGN_STREAK_NEED` 且那几票是同一份正文
    （`_pending_claim_streak`）；未认领那一支这三个数只作读数（`ok` 仍只走行局部）。
    """
    sid = str(row.get("stmt_id") or row.get("statement_id") or "").strip()
    out: dict[str, Any] = {
        "ok": False, "checked": False, "why": "", "statement_id": sid,
        "verification_id": "", "verdict": "", "round": None,
        "sha_matches": None, "ledger": "", "rows": 0, "problems": [],
        #: 现行这一份的读数（`REVIEW_STATES`）与证明号：`ok` 只在 `signed` 时为真。
        #: `state="stale"` 是"签过、但签的是旧版"—— 它是待复核这个读数，不是"没签过"；
        #: `state="holding"` 是"签过、判成立、连续次数还没到"（业主 2026-10-29）。
        "state": "", "proof_no": None,
        #: 这一份凭据是不是"命题还没在册时审的那一签"（`verifications/pending/`）。
        #: 它与台账那一行同等算"签过"（D-34：「先签后登记」与「先登记后签」是同一件事），
        #: 但来路不同必须读得出来：升 `kind` 的那一格（`kind_following_grade`）
        #: 在 B 的登记 / 收录路上不认未认领的 pending（`allow_pending=False`），
        #: 否则新行会在同一笔里变成 theorem 而它连台账行都还没有。
        #: 2026-11-11（p283）：认领回写了 `statement_id`（且载体稿号与行上一致）之后
        #: 这一格是 False、`claimed=True` —— 那时它已经是本条命题自己的签。
        "pending": False, "claimed": False, "carried_manuscript_id": "",
        #: pending 那一支的票数读数（2026-11-11 p284）：认领之后 `ok` 要求
        #: `streak_ok`（满 `SIGN_STREAK_NEED` 票且同一份正文 sha），见 `_gap_from_pending`。
        "streak": 0, "need": int(verifications.SIGN_STREAK_NEED), "streak_ok": False,
    }
    checks: list[dict[str, Any]] = [
        {"item": "proof_text 非空（有被审的那份证明）", "ok": False, "detail": "还没判到"},
        {"item": f"`verifications/<命题号>.jsonl` 里有签「成立」的那一行"
                 f"（verdict=成立 且 unresolved_errors=0）", "ok": False, "detail": "还没判到"},
        {"item": "那一行的 `proof_sha256` 等于现在这一版 `proof_text` 的 sha256",
         "ok": False, "detail": "还没判到"},
    ]
    out["checklist"] = checks
    # ---- 概念行：不算"等级链上的证明"，但良定义证明可以有签（2026-11-10 业主裁定 甲）----
    #
    # 真机读数（`projects/mp3/data/statements.json`）：1143 条概念行每一条
    # 都带 `proof_text`（值是一个哨兵 `concept:primitive`）。于是"这一行有没有证明"
    # 的读数被顶高：`prose_reviewed_statements` 数的是"`proof_text` 非空且 V 签了
    # 成立"，一条概念行只要撞上一次签名就能进那一格；而 `proof_review_gap` 也只问
    # `proof_text` 非空 —— 它会把概念行当成"有一条被审过的证明"的候选。
    #
    # 2026-11-10 业主裁定（甲）：概念的良定义证明与一般手稿同一条链 —— B 落 b-稿、
    # V 三转签、B 收录进 `proof_text`。所以这一档要按"有没有那一个签"分：
    # 有签 ⇒ 这一格是良定义证明（不是污染，也不是等级链上的证明）；
    # 没签 ⇒ 写入侧/存量行的污染（要点名，让存量看得见）；
    # 不带 ⇒ 正常（这一格对它不适用 —— 不是"缺证明"）。
    if str(row.get("kind") or "") == "concept":
        out["checked"] = True
        text_concept = str(row.get("proof_text") or "")
        if text_concept.strip():
            from . import vsigns as _VS

            try:
                sign = dict(_VS.sign_reading(
                    root, statement_id=sid, proof_text=text_concept,
                    proof_no=1, store=None))
            except Exception as exc:  # noqa: BLE001 —— 读不出来 = 没查成，不是"已签"
                sign = {"checked": False, "state": "",
                        "why": f"签的读数没查成（{type(exc).__name__}: {exc}）"}
            out["sign"] = dict(sign)
            if str(sign.get("state") or "") == "signed":
                checks[0].update(ok=True,
                                 detail=f"{len(text_concept)} 字（良定义证明，已签）")
                checks[1]["detail"] = "概念不参与等级链；这一份是良定义证明，V 已签"
                checks[2]["detail"] = "同上"
                out.update(ok=True, state="signed", verdict="成立",
                           verification_id=str(
                               (sign.get("credential") or {}).get("verification_id") or ""),
                           ledger=str((sign.get("credential") or {}).get("path") or ""),
                           sha_matches=True,
                           why=(f"命题 {sid or '（没有编号）'} 是概念行（kind='concept'），"
                                "它的 `proof_text` 是良定义证明，且 V 已签在 b-稿上"
                                "（`vsigns.sign_reading.state == 'signed'`）⇒ 不是污染；"
                                "概念仍不参与等级链（`derive_grade` 短路成 "
                                "`not_applicable`），这一格不改变任何等级读数"))
            else:
                checks[0].update(ok=False, detail=f"{len(text_concept)} 字（概念行不该有）")
                checks[1]["detail"] = "概念行没有'证明'这一档，不适用"
                checks[2]["detail"] = "同上"
                out["why"] = (f"概念行不该带证明文本：命题 {sid or '（没有编号）'} 是 "
                              f"kind='concept'，而它的 `proof_text` 非空"
                              f"（{text_concept[:40]!r}）⇒ 概念不参与等级链，"
                              "`proof_text` 对它不是证明，而是一个哨兵；"
                              "任何'有没有证明'的读数都会被它顶高。"
                              "写入侧已经堵住（`conceptrows.concept_statement` 只保留有 V 签的正文），"
                              "这一条是存量行的点名：把这一格清空（定义/待补标记都在别的字段里），"
                              "或先落 b-稿、让 V 签回来、再按位置与格收录")
        else:
            checks[0]["detail"] = "概念行没有 proof_text（正常：概念不参与等级链）"
            checks[1]["detail"] = "概念行没有'证明'这一档，不适用"
            checks[2]["detail"] = "同上"
            out["why"] = (f"命题 {sid or '（没有编号）'} 是概念行（kind='concept'）："
                          "概念没有'证明'这一档（不参与等级链）⇒ 这一格对它不适用，"
                          "不许读成'有证明'，也不许读成'缺证明'")
        return out
    text = str(row.get("proof_text") or "")
    if not text.strip():
        out["checked"] = True
        checks[0]["detail"] = "空"
        checks[1]["detail"] = "没有被审的对象，不适用"
        checks[2]["detail"] = "没有被审的对象，不适用"
        out["why"] = (f"命题 {sid or '（没有编号）'} 的 evidence_kind="
                      f"{PROOF_REVIEW_KIND!r}，而 `proof_text` 是空的 ⇒ "
                      "没有被审的那份证明，「逐行审阅过」这句话就没有对象。"
                      "要么把证明过程写进 proof_text，要么把这一档降成 heuristic")
        return out
    checks[0].update(ok=True, detail=f"{len(text)} 字")
    if not S.is_valid_id(sid):
        checks[1]["detail"] = "命题号不是编号形态，查不到台账"
        checks[2]["detail"] = "同上"
        out["why"] = (f"命题号 {sid!r} 不是编号形态（{S.ID_DIGITS} 位，旧四位仍可读）⇒ "
                      f"`verifications/` 里查不到它，凭据无从核起")
        return out
    path = verification_ledger_path(root, sid)
    out["ledger"] = f"{VERIFICATIONS_DIR}/{sid}.jsonl"
    if not path.is_file():
        pending = _pending_signed(root, text)
        if pending is not None:
            return verifications._gap_from_pending(
                out, checks, pending, statement_id=sid,
                manuscript_id=str(row.get("manuscript_id") or ""), root=root)
        out["checked"] = True
        checks[1]["detail"] = f"`{out['ledger']}` 不在盘上（一次审校都没有）"
        checks[2]["detail"] = "没有那一行，无从比"
        out["why"] = (f"命题 {sid} 声称 evidence_kind={PROOF_REVIEW_KIND!r}，而 "
                      f"`{out['ledger']}` 不在盘上 ⇒ 一次审校都没有。"
                      "这一档要求 V 的 `verifications` 里那一条签「成立」（且审的是现在"
                      "这一版）—— 没有它，这一行就只是「自称被审过」。"
                      f"建议：① 派 V 去 `verify_proof(statement_id=\"{sid}\")`（不传 "
                      "proof_text，签的就是现行正文）；② 把 evidence_kind 降成 heuristic")
        return out
    rows, problems = JF.read_jsonl(path)
    out["rows"] = len(rows)
    out["problems"] = list(problems)
    if problems:
        checks[1]["detail"] = f"台账有读不出来的行：{problems[:3]}（没查成）"
        checks[2]["detail"] = "同上"
        out["why"] = (f"`{out['ledger']}` 有读不出来的行（{problems[:3]}）⇒ "
                      "凭据没查成（不是「查过、没问题」）")
        return out
    if not rows:
        pending = _pending_signed(root, text)
        if pending is not None:
            return verifications._gap_from_pending(
                out, checks, pending, statement_id=sid,
                manuscript_id=str(row.get("manuscript_id") or ""), root=root)
        out["checked"] = True
        checks[1]["detail"] = "台账是空文件"
        checks[2]["detail"] = "同上"
        out["why"] = (f"`{out['ledger']}` 是空文件 ⇒ 一次审校都没落过"
                      "（「有这个文件」不等于「审过」）")
        return out

    # ---- 判定分两个口（2026-10-22 审计第 1 条 + 多证明模型收口）
    #
    # 命题级（`ok`）：`evidence_kind` 是命题级的声明，而每一条证明各自有第 3 位 ⇒
    # "任一份证明 signed 即放行"（`statement_review_reading` 的 `reviewed`）。
    # 逐条级（`state` / `proof_no` / `verification_id` / `sha_matches` / `why`）：
    # 说的是"当前这一份"（`proof_no`，缺省按这一行自己记的号，再缺省 canonical）。
    #
    # 为什么不能只留一个口：只留命题级，拒信就说不清是哪一份缺凭据（读的人只能猜）；
    # 只留逐条级（改前就是 `review_standing(..., proof_no=1)`），"#p1 未签、#p2 已签"
    # 的存量行会被写入期闸整笔拒收，而拒收之后撤回把台账那一行也抹掉 —— 同一批审计
    # 的第 1 条正是这个形态：`checked=True verdict='成立' signed_bit3=True` 而台账 0 字节。
    reading = statement_review_reading(root, row)
    no = proof_no_of(row) if proof_no is None else as_proof_no(proof_no)
    if no < 1:
        no = DEFAULT_PROOF_NO
    entries = [p for p in (reading.get("proofs") or []) if isinstance(p, Mapping)]
    by_no = {as_proof_no(p.get("proof_no")): p for p in entries}
    current = by_no.get(no) or by_no.get(DEFAULT_PROOF_NO) or {}
    signed_entry = next((p for p in entries if p.get("ok")), {})
    stale_entry = next((p for p in entries if str(p.get("state") or "") == "stale"), {})
    checked = bool(reading.get("checked"))
    if checked and signed_entry:
        chosen, state = signed_entry, "signed"
    elif checked and stale_entry:
        chosen, state = stale_entry, "stale"
    else:
        chosen, state = current, str(current.get("state") or "unsigned")
    chosen_no = as_proof_no(chosen.get("proof_no")) or no
    # 台账那一签的细节（verdict / round / unresolved_errors）只有 `review_standing` 的
    # 返回里有，逐条读数只带定位用的几格 ⇒ 对"被选中的那一份"再读一次（纯读，不写）。
    span = (review_standing(root, statement_id=sid,
                            proof_text=proof_text_of(row, chosen_no), proof_no=chosen_no)
            if checked else {})
    out.update({
        "checked": checked,
        "state": state,
        "proof_no": chosen_no,
        "sha_matches": chosen.get("in_sync"),
        "verification_id": str(chosen.get("verification_id") or ""),
        "verdict": str(span.get("verdict") or ""),
        "round": span.get("round"),
        # 给拒收消息用（"这一签是 verdict=X、unresolved_errors=N"）：读数，
        # 不参与判据 —— 判据只看 `signs_bit3`（一处口径）。
        "unresolved_errors": int(span.get("unresolved_errors") or 0),
        # I10 硬禁令的机械命中（只报不判，见 `review_standing` 的同一格）。
        "hard_ban_markers": [str(m) for m in (span.get("hard_ban_markers") or [])],
    })
    if state == "signed" and checked:
        # 2026-11-14 RL1（真机 000041）：指针取值以「正式颁发的那一签」为准，不取
        # 台账里最后一条 pending —— 同一份正文可能被并发审过两趟（20:55 发签 u-000003、
        # 20:57 又落 3 条成立但没发签 u-000006），"最后一条"会把没发签的那一趟写成凭据。
        # `state` / `ok` / 连续票数一个字不动（那是"这一份正文算不算签住"的判定）；
        # 这一格只改"凭据指回哪一行"，所以后一次否决仍按 `review_standing` 的原判据生效。
        issued = verifications._issued_verification_pointer(root, str(chosen.get("proof_sha256") or ""))
        if issued.get("found"):
            out["verification_id"] = (str(issued.get("verification_id") or "")
                                      or out["verification_id"])
            out["ledger"] = str(issued.get("ledger") or out["ledger"])
        checks[1].update(ok=True, detail=f"{out['verification_id']}：{out['verdict'] or '成立'}")
        checks[2].update(ok=True, detail=(
            f"{proof_label(sid, chosen_no)} 的现行正文 sha "
            f"{str(chosen.get('proof_sha256') or '')[:12]}… 与台账那一行相符"))
        out["ok"] = True
        out["why"] = (
            f"命题 {sid} 的 evidence_kind={PROOF_REVIEW_KIND!r} 有凭据（每份证明各自有第 3 位，"
            f"任一份 signed 即算）：{str(chosen.get('why') or '')}")
        return out
    if state == "rejected":
        checks[1]["detail"] = (f"现行这一版被签过：{out['verification_id']} "
                               f"verdict={out['verdict']!r}、"
                               f"unresolved_errors={out['unresolved_errors']}")
        checks[2]["detail"] = "签的就是现行这一版，但结论不是「成立」"
        out["why"] = (
            f"命题 {sid} 的 evidence_kind={PROOF_REVIEW_KIND!r}，而 `{out['ledger']}` 里"
            f"{proof_label(sid, chosen_no)} 现在这一份上那一签是 {out['verification_id']}："
            f"verdict={out['verdict']!r}、unresolved_errors={out['unresolved_errors']}"
            f"（why：{str(chosen.get('why') or '')[:120]}）⇒ 复核过、结论不是「成立」。"
            "建议：按 findings 改好证明再派 V 走一遍，或者如实降档 —— "
            "改完再把同一份内容交一次（改稿是正常动作，不是越权）。")
        return out
    if state == "stale":
        checks[1]["detail"] = (f"{proof_label(sid, chosen_no)} 签过，但没有一签盖住现在这一份"
                               f"（最近一签 {out['verification_id']}）")
        checks[2]["detail"] = "签的是另一版，无从比"
        out["why"] = (str(chosen.get("why") or "")
                      + "；改稿是正确动作，建议：请重新拿 V 签 —— 派 V 用 "
                      f"`verify_proof(statement_id=\"{sid}\", proof_no={chosen_no})` "
                      "审现行正文（签还没到位：这一版正文上还没有签块）")
        return out
    if state == "holding":
        # 签过、判成立、签的也是现行这一版 —— 就是门槛还没到（业主 2026-10-29）。
        # 它与 `unsigned`（一次都没签）必须分开说：前者的下一步是"再送 V 走这一趟送审"，
        # 后者是"送 V 一次"。折成同一个读数会让"已经在路上"看起来像"还没出发"。
        entry = next((p for p in entries
                      if as_proof_no(p.get("proof_no")) == chosen_no), {})
        got = int(entry.get("streak") or 0)
        need = int(entry.get("need") or verifications.SIGN_STREAK_NEED)
        checks[1]["detail"] = (f"{proof_label(sid, chosen_no)} 的「成立」读数 {got}/{need}"
                               f"（最近一签 {out['verification_id']}）")
        checks[2]["detail"] = "签的就是现行这一版（不是过期），只是门槛还没到"
        out["checked"] = checked
        out["why"] = (f"命题 {sid} 的证明签过、也判了「成立」，但门槛还没到"
                      "⇒ 签还没到位（V 判过「成立」，但这一版正文上还没有签块），"
                      "不能当「审过」。建议：再送 V 走这一趟送审（门槛由框架按这一趟"
                      "送审自己数；跨趟不累计），直到签到位；"
                      "不许把这几票当成一次签")
        return out
    if state == "unsigned":
        # 台账读得出、只是这一份（以及别的证明）一次都没签 ⇒ 查过了，结论是"没凭据"。
        # 改前这一支掉进最后那段，被报成 checked=False「台账读不出来（没查成）」——
        # 把"查过了、没签过"与"没查成"折成同一个读数（审计第 4 条）。
        checks[1]["detail"] = (f"`{out['ledger']}` 里没有 {proof_label(sid, chosen_no)} 这一份"
                               "证明的签（一次都没签）")
        checks[2]["detail"] = "没有那一行，无从比"
        out["checked"] = checked
        out["why"] = str(chosen.get("why") or
                         f"`{out['ledger']}` 里没有这一份证明的签 ⇒ 一次都没签")
        out["why"] += ("；建议：请拿 V 签 —— 派 V 用 "
                       f"`verify_proof(statement_id=\"{sid}\", proof_no={chosen_no})` 审这一份"
                       "（签还没到位：这一版正文上还没有签块）")
        return out
    checks[1]["detail"] = "台账读不出来（没查成）"
    checks[2]["detail"] = "同上"
    out["checked"] = False
    out["why"] = str(chosen.get("why") or "台账没查成（不是「没签过」）")
    return out


def weaker_than_evidence_gaps(root: str | Path,
                              rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """一组 `statements` 行里够格 `pre_theorem` 却现算成更弱等级的那些 —— 纯读。

    ## 2026-11-05：这条读数改读等级
    改前它读 `evidence_kind` 在 :data:`WEAKER_THAN_PROOF_REVIEW` 里（`heuristic` /
    `cross_check`）；业主动裁「判定面一律读等级」之后，判据换成"现算等级低于
    `pre_theorem`、而凭据已经够 `pre_theorem`"。这两件事在旧口径下几乎等价
    （档位弱 ⇔ 等级弱），但新口径能看见旧口径看不见的那一类：档位写着 `proof`、
    现算等级却只有 `strong_conjecture` 的行（真机 169 条不一致里有一批正是它）。

    ## 这条读数在说什么（2026-10-19，接 `proof_review_gap` 的反方向）
    `proof_review_gap` 管"自称审过、其实没签"（虚报）；这里是它的镜像：凭据齐全、
    等级却现算得低。真机形态（`projects/mp2` 的 `stmt:000003`）：`proof_text` 1909 字、
    `verifications/000003.jsonl` 里 `v-000001` 签「成立」、`proof_sha256` 与现行正文
    相符 ⇒ 按五元位现算就是 `pre_theorem`，而盘上落的是 `heuristic`。
    它不是虚报，所以不是 error：降档是安全方向，可以是有意的选择；但它必须是看得见的
    选择，不是默认值 —— 长期把强结果写成弱档，论文的强度声明会系统性偏低。

    判据只三条：
    1. 现算等级在 :data:`WEAKER_THAN_PRE_THEOREM_GRADES` 里；
    2. `proof_text` 非空（没有证明就谈不上"这份证明被审过"）；
    3. `proof_review_gap(...)` 判 `ok=True`（V 最近一签是「成立」且 `proof_sha256`
       等于现行正文）。
    概念行（`kind="concept"`）跳过：概念不参与等级链（`evidencebits.derive_grade` 的
    `not_applicable`）。
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("kind") or "") == "concept":
            continue
        try:
            bits = EB.bits_from_row(dict(row))
            grade = EB.derive_grade(bits, kind=str(row.get("kind") or ""))
        except Exception:  # noqa: BLE001 —— 算不出来不是"档位写低了"（三态：判不了就不判）
            continue
        if grade not in WEAKER_THAN_PRE_THEOREM_GRADES:
            continue
        if not str(row.get("proof_text") or "").strip():
            continue
        gap = verifications.proof_review_gap(root, row)
        if not gap.get("ok"):
            continue
        sid = str(row.get("stmt_id") or row.get("statement_id") or "")
        out.append({
            "statement_id": sid,
            "grade": grade,
            "evidence_kind": str(row.get("evidence_kind") or ""),
            "verification_id": gap.get("verification_id") or "",
            "ledger": gap.get("ledger") or "",
            "why": (f"命题 {sid} 现算等级是 `{grade}`（低于 `pre_theorem`），而它的凭据"
                    f"已经够 `pre_theorem`：`proof_text` 非空、`{gap.get('ledger') or ''}` 里 "
                    f"{gap.get('verification_id')} 签「成立」、`proof_sha256` 与现行正文相符"
                    "（判据与 `proof_review` 写入期那道闸同一处）。"
                    "降档是安全方向，所以这是 warning、不是 error；但它必须是有意的："
                    "要么让这一行的五元位如实反映那一签，要么在报告里写清为什么故意留弱档。"),
        })
    return out


def proof_review_gaps(root: str | Path, rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """一组 `statements` 行里凭据不够的那些 `proof_review`（空列表 = 都够）。

    只挑 `evidence_kind == "proof_review"` 的行去核（其它档不归这条判据管：
    `proof` 由 `evidencebits.bit_evidence_gaps` 核，`cross_check`/`heuristic` 只需声明）。

    ## 哪些算"凭据不够"（业主 2026-10-22 口径改了半边）
    这一份的调用者是写入期闸（`store._refuse_fake_proof_review`）与审计期档
    （`verify._check_13`），所以"不够"的判据就是"该不该拒收/点名"：
    - `unsigned`（一次「成立」都没有）/ `unreadable`（台账读不出来）⇒ 不够，照旧；
    - `rejected`（现行这一版被签过、结论不是「成立」）⇒ 不够，照旧；
    - `stale`（签过、但签的是旧版）⇒ 不再算"没有凭据"。哈希是读数不是授权凭证：
      "正文改过了"是正常动作，任何写入路径都不许因为它被拒收。这一档现在是待复核
      这个读数（收工门 R10 的 `stale_ids`），不是"没签过"。
    - 任一证明 `signed` ⇒ 够（`proof_review_gap` 的命题级判据）：多证明模型里每份证明
      各自有第 3 位，"#p1 未签、#p2 已成立"这一形态不许整笔拒收 —— 它是本批审计
      第 1 条的存量形态（真机 mp1 的 10 条 `proof_review`）。逐条的不合格仍由
      `proof_review_gap` 的 `state` / `why` 读出来，只是不升级成"整笔不写"。
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("evidence_kind") or "") != PROOF_REVIEW_KIND:
            continue
        gap = verifications.proof_review_gap(root, row)
        if gap["ok"] or gap.get("state") == "stale":
            continue
        out.append(gap)
    return out


# 跨模块引用放在文件末尾：这些名字的实现在别的模块里，而两个模块可能互相
# 引用（顶层 `from .x import y` 在环里会在对方还没定义完时执行）。引用点
# 全部在函数体里，所以只要定义都跑完了，谁先被导入都拿得到。
from . import verifications  # 门面字典：被打桩的名字经它取
from .v_vocab import (  # noqa: F401 — 实现在 v_vocab.py
    PROOF_REVIEW_KIND,
    VERIFICATIONS_DIR,
    WEAKER_THAN_PRE_THEOREM_GRADES,
)
from .v_citation import (  # noqa: F401 — 实现在 v_citation.py
    citation_blocks,
)
from .v_paths import (  # noqa: F401 — 实现在 v_paths.py
    _sign_sha,
    as_proof_no,
    proof_label,
    proof_no_of,
    proof_text_of,
    verification_ledger_path,
)
from .v_pending_read import (  # noqa: F401 — 实现在 v_pending_read.py
    _pending_signed,
)
from .v_rowread import (  # noqa: F401 — 实现在 v_rowread.py
    _streak_number,
    row_signable,
    signing_gate_problem,
)
from .v_standing import (  # noqa: F401 — 实现在 v_standing.py
    review_standing,
    statement_review_reading,
)
