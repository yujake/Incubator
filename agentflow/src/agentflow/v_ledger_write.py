# -*- coding: utf-8 -*-
"""台账写口（追加 + 可撤回）。

2026-11-20（VERSPLIT2）：`v_ledger_write.py` 是从 `verifications.py` 搬出的 8 块 / 511 行（块
逐字未动，逐名 AST 全等在 `temp/versplit2/` 可复算）。对 32 个被测试打桩的名字，读
一律写成 `verifications.<name>` —— 门面字典在调用那一刻才查，所以
`monkeypatch.setattr(verifications, ...)` 仍然到得了这里（`from .x import X` 是快照，
补丁到不了）。跨模块 import 放在文件末尾：模块之间有互相引用，定义全跑完再 import
才解得开环。
"""

import json
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from . import jsonlfile as JF
from . import schema as S  # 编号形态的唯一来源（六位 / 旧四位读侧兼容）
from .proofloc import DEFAULT_PROOF_NO  # canonical 证明号只有一个出处（`proofloc`）


def next_verification_id(root: str | Path, statement_id: str) -> str:
    """这个命题的验证台账里的下一个编号（`v-` + 当前宽度；宽度见 `schema.format_id`）。

    为什么从 `record_verification` 里抽出来一处具名函数（2026-10-14 改宽度那一笔）：
    它是发号点，而"每个发号点都发当前宽度"这条判据要能逐个真发一次 ——
    发号逻辑埋在写函数中间时，判据只能靠"读一遍代码"来假装检查过。
    """
    path = verification_ledger_path(root, statement_id)
    rows, _problems = JF.read_jsonl(path) if path.is_file() else ([], [])
    return f"v-{S.format_id(len(rows) + 1)}"


def _note_conjecture_refutation(root: str | Path, row: dict[str, Any]) -> dict[str, Any]:
    """V 判「有毛病」⇒ 把猜想台账那一行落成 `refuted`（唯一写点：`conjectureledger`）。

    ## 为什么挂在 V 这一侧

    业主 2026-11-13 裁定 ②：被拒那一档要落 `refuted`，而"被拒"有两条真实的来路 ——
    E 跑出了反例（`result=refutes`，由 E 自己的记账那一笔落），或有人把它判死了
    （V 判「有毛病」/ B 拒收）。B 那一侧接在 `register_statement` 的拒收路上；V 这一侧
    就是这里：`record_verification` 是"V 的判词落台账"的唯一入口。

    ## 三态

    - 这一签不是「有毛病」⇒ 一个字节都不动，返回行上也不加键（老读数逐字不变）；
    - 是「有毛病」但命题正文读不到（`statements` 里没有这一条）⇒ 返回行上
      `checked=False` + 理由 —— 那是"对不上猜想行"，不是"没被拒"；
    - 是「有毛病」且对上了 ⇒ `refuted` + `refusal_ref=verifications/<号>.jsonl#v-…`，
      返回行上多一格读数（`checked` / `refuted` / `conjecture_id` / `refusal_ref`）。
      台账里没有那条猜想 ⇒ `refuted=False` 且不新建一行（被拒的必须是被登记过的那一条）。

    记账失败不许把一次审校变成失败：读数进返回行（`checked=False` + 异常名），
    台账那一行已经落了，它是正本。
    """
    if str(row.get("verdict") or "") != _FAULT_VERDICT:
        return row
    sid = str(row.get("statement_id") or "")
    vid = str(row.get("verification_id") or "")
    reading: dict[str, Any] = {
        "checked": False, "refuted": False, "conjecture_id": "",
        "refusal_ref": f"verifications/{sid}.jsonl#{vid}", "reason": "",
    }
    try:
        from . import conjectureledger as CL
        from . import statementledger as SL
        from .store import Store

        store = Store(str(root))
        # 「取数走查口」：按编号取一行走 `statementledger.by_id`，不再自己扫全表
        # （`tests/test_the_statement_ledger_has_two_ways_to_be_asked.py` 的 n）。
        # 三态：`found=False` ⇒ 真的没有这一行；`checked=False` ⇒ 台账没查成 ——
        # 两档都不给正文，下面那一句把两种情形都写成"对不上猜想行"，与改前同形。
        hit = SL.by_id(store, stmt_id=sid)
        text = str((hit.get("row") or {}).get("statement_full") or "") if hit.get("found") else ""
        if not text.strip():
            reading["reason"] = ("这一签的命题在 `statements` 里读不到正文 ⇒ 对不上猜想行"
                                 "（不是「没被拒」）")
        else:
            got = CL.mark_refuted(store=store, statement=text,
                                  refusal_ref=reading["refusal_ref"], actor="agent-V")
            reading["conjecture_id"] = str(got.get("conjecture_id") or "")
            reading["refuted"] = bool(got.get("refuted"))
            reading["checked"] = reading["refuted"] or bool(reading["conjecture_id"])
            reading["reason"] = (str(got.get("reason") or "")
                                 or "猜想台账那一行已落 refuted")
    except Exception as exc:  # noqa: BLE001 —— 记账失败不许把一次审校变成失败
        reading["reason"] = f"{type(exc).__name__}: {exc}"
    row["conjecture_refutation"] = reading
    return row


def record_verification(root: str | Path, *, statement_id: str, proof_text: str, verdict: Mapping[str, Any],
           verifier: str = "V", round_no: int | None = None,
           used_faces: Iterable[str] = (), submission_id: str = "",
           store: Any = None, proof_no: Any = None,
           object_sha256: Any = "", object_path: Any = "",
           manuscript: str = "",
           producer_path: Any = "", producer_code: Any = "",
           roster_role: Any = "",
           citation_gate: Mapping[str, Any] | None = None,
           secretary_judge: Mapping[str, Any] | None = None,
           sign_issuance: Mapping[str, Any] | None = None,
           washed_relay: Mapping[str, Any] | None = None,
           review_pass: int | None = None, review_call: str = "",
           review_scope: str = "",
           flip: bool = True) -> dict[str, Any]:
    """把一次审校写进这个命题的台账（追加一行），返回那一行。

    编号 `v-NNNN` 由脚本按文件内顺序发（`draft/39` §3.21 五：与手稿编号、台账 id 同一套）。
    写之前把结论再规范化一遍（`parse_verdict` 的同一套校验）—— 调用方绕开解析直接
    构造一个 dict 时，坏结论会在写入期被挡住，而不是等到下游读它的时候。

    ## 这一行记什么（2026-10-22 补上右边的三格）
    `(stmt_id, proof_no, proof_sha256)`：`stmt_id` 是被审的那条命题（与 `statement_id`
    同值，两个键都写是为了不让读的人去猜哪个才是号）；`proof_no` 是被审的那一份证明
    （缺省 1 = canonical，见 :data:`PROOFS_KEY`）；`proof_sha256` 是这一份正文的指纹。
    三者合起来回答"复核过的是哪一份"。

    ## 证明号的两种来路必须分开（2026-10-22 审计第 3 条）
    `proof_no=None` = 没给参数 ⇒ canonical（`#p1`）；给了但 :func:`as_proof_no` 认不出
    （`0` / `'abc'` / `2.0` / `'#p0'` …）⇒ :func:`proof_no_strict` 抛
    `VerificationError`，一个字节都不写。改前这里写 `as_proof_no(proof_no) or 1`：
    调用方说"签 #p2"、号给成了 0，台账上记成 `proof_no=1` 且 `verdict=成立` —— 签错
    一份证明，而盘上没有任何一格会报。

    ## `store` 给了就顺手把那条证明的第 3 位翻上去（业主 2026-10-22：同一次写）
    给了 `store` 且这一签签得住第 3 位（`signs_bit3`）⇒ 追加台账之后立刻调
    :func:`sign_statement`，在同一个 `statements` 事务里把那条证明的 `reviewed` 置真并把
    `reviewed_by` 换成这一签的凭据（含 `proof_no` 与 `proof_sha256`）。返回值里多一格
    `statement_writeback`（写没写成、为什么、回滚了没有、追加落在哪一态）—— 台账那一行
    是权威记录，位是它的缓存；写位失败不回滚签名（签名确实发生过），但必须如实报出来。
    不给 `store` ⇒ 只追加台账（老行为，夹具与自检走这条）。

    ## `manuscript`：这一签的载体（2026-11-04，业主裁定 甲）

    工作区相对路径。给了它就把这一格写进台账行（条件写入 ⇒ 老行逐字节不变）；
    :func:`sign_statement` 翻位时从行上读它、交给 :func:`_vsigns_write_after_flip`，
    于是 `vsigns.land` 把签块盖回送审方点名的那一份稿，而不是按约定路径扫盘猜一份。
    未在册那一支不走这里（它落 `verifications/pending/<sha>.jsonl`，手稿由
    `Secretary.land_unregistered_sign` 落）。

    ## 返回行上的三格：这一签到底有没有落地（2026-10-22 审计第 1 条）
    `checked` / `re_sign_required` / `reason`：撤回（`_rollback_append`）发生在
    :func:`sign_statement` 内部，调用方只看返回值。改前撤回之后返回行仍然是那一份
    `verdict=成立` 的记录 ⇒ V 的 `verify_proof` 照报"签住了第 3 位"，而台账是 0 字节。
    现在撤回或追加失败 ⇒ `checked=False`、`re_sign_required=True`、`reason` 逐字写明
    "台账那一行被撤回 / 没写成"。

    ## `citation_gate`：只在"这一档没查成"时写（2026-10-27）
    `problem` 非空（依赖台账读不出来）⇒ 行上多一格 `citation_gate`
    （`ok` / `problem` / `why` 三个读数）。为什么必须落盘：那时 `citation_checks` 常常
    是空数组，而空数组什么都不挡 —— 读侧的硬闸（:func:`signs_bit3`）要能分开
    "没查成"与"核过、没有引用"。查成了的行不写这一格（老行因此逐字节不变）。

    ## `secretary_judge` / `sign_issuance`：业主 2026-10-29 的 B 段与 A 段
    `secretary_judge` 是秘书对这段回复的两档语义判定（`clean` / `fault`），原样落到台账
    那一行的 `SECRETARY_JUDGE_KEY` 那一格 —— 连续计数读它（`fault` 清零、`clean` 计入；
    没查成的那一行两样都不做）。写侧只收这两格（`:data:`SECRETARY_JUDGE_AXES``）：词表外的
    轴（包括 2026-10-30 之前那个已取消的轴名）一律落成空轴，写不进来。
    不给就一个字节都不写（历史行与"没问过秘书"的那一批因此逐字节不变，
    读侧按"没判过"处理，也就是计入）。
    `sign_issuance` 是秘书"发不发这一签"的决定，原样交给 :func:`sign_statement` 当闸：
    `checked=False`（没缝 / 超时 / 台账读不成 / 没装配）⇒ 不翻位。
    两个参数都只影响"位翻不翻"，不改台账那一行的 `verdict`（那是 `parse_verdict` 的正本）。

    ## `flip=False`：这一签只落台账，翻位交给秘书（业主 2026-10-29 追加口径）
    原话：「V 不再自己发签。V 只产出审稿意见；由 V 的秘书判定并落盘」。所以 V 的写入口
    取 `flip=False`：台账那一行照落（正本），`statement_writeback.deferred_to="secretary"`，
    第 3 位由 `Secretary.decide_sign_issuance` 判完再调
    :func:`sign_statement`（`append_ledger=False`）翻。默认 `True` 是兼容门（夹具 / 直调本函数
    的那一批），生产 V 那两条路都传 `False`。

    ## `review_pass` / `review_call`：这一行是"哪一趟送审的第几轮"（2026-11-02 定稿）
    一次 `verify_proof` = V 连判 `SIGN_STREAK_NEED` 轮；`review_call` 是那一趟调用的 id
    （每趟一个，同一趟的三行逐字相同），`review_pass` 是这趟里的第几轮（1..need）。
    新签只认同一 `review_call` 内 `review_pass=1..need` 的那几行；跨调用绝不累计。
    `round` 保持原样（全局台账行号，老读数仍在用），不要拿它当趟内轮次。
    不给这两个参数（老调用点 / 夹具 / 直调本函数）⇒ `review_call=""`、
    `review_pass=None` ⇒ 读侧按历史形态计（`legacy_rows`），不参与新签判断。

    ## `object_sha256` / `object_path`：被审的是盘上哪一份文件（2026-11-21，SIGNMAL）

    两格回答的是"V 审的是哪一份文件"，与 `proof_sha256`（哪一版正文）不是同一把尺：

    - `object_sha256` 是那份文件（`reports/f-proof-<号>.md` / `e-proof-*` / E 的报告）
      的字节 sha256，64 位小写；`object_path` 是它的工作区相对路径；
    - 给了才写（条件写入 ⇒ 老行逐字节不变），但生产 V 的两个写入口都必须给：
      未在册那一支由 `record_pending_sign` 收，在册那一支（本函数）由
      `agent_v/core.py` 的 `verify_proof` 现算传进来（`_manuscript_bytes_sha`）；
    - 为什么必须给：签文件的 `passes` 逐票抄这一格（`sign_counting.ticket`），空串
      会让那一份签说不清"审的是哪一份文件"——真机 `projects/lp-ball-15` 的
      `2f77e321….json` 就是这么落出一份格式不合格的签（写侧格式闸见
      `vsigns.sign_file_problems`：空串在点名了载体时由 `vsigns.issue` 用
      `artifact_path` 的字节 sha 补上，非空而形状坏才受控拒）。
    """
    # 证明号先判：坏号在写任何东西之前就拒（不落台账、不改位）。
    no = proof_no_strict(proof_no)
    checked = parse_verdict(json.dumps({"verdict": verdict.get("verdict"),
                                        # 折过档的那一行要把模型原话带下去（审计用）：
                                        # 不带的话，`parse_verdict` 只能看到已折好的
                                        # 「成立」，盘上就再也查不到"它其实没判"。
                                        "verdict_raw": verdict.get("verdict_raw", ""),
                                        "defect_step": verdict.get("defect_step"),
                                        "quote": verdict.get("quote", ""),
                                        "why": verdict.get("why", ""),
                                        "findings": list(verdict.get("findings") or []),
                                        # 引用核实那一格也要过同一套校验：调用方绕开
                                        # `parse_verdict` 直接构造 dict 时，坏档位同样被挡在
                                        # 写入期（否则它会以"没有这一格"的样子落盘）。
                                        "citation_checks": list(verdict.get("citation_checks") or [])},
                                       ensure_ascii=False, default=str))
    path = verification_ledger_path(root, statement_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows, problems = JF.read_jsonl(path)
    if problems:
        raise VerificationError(f"这个命题的验证台账有读不出来的行：{problems[:3]}")
    vid = next_verification_id(root, statement_id)
    sha = _sign_sha(proof_text)
    row = {
        "verification_id": vid,
        # 两个键同值：`statement_id` 是历史名（老行只有它），`stmt_id` 是"被审的命题"的
        # 那一个名字（业主 2026-10-22 点名要它）。只写一个会让按另一个键读的人读到 None，
        # 而"读到 None"与"这一签不属于任何命题"在读数上长得一样。
        "statement_id": str(statement_id), "stmt_id": str(statement_id),
        # 2026-11-11 业主裁定：`proof_no` 在 V 签侧退役 —— canonical 新行不写这一格
        # （一稿一份之后身份由 `proof_sha256` + `stmt_id` 回答）。老行里已有的
        # `proof_no` 读侧照旧（`proof_no_of` 缺省按 1，`PROOF_NO_KEYS` 兼容 `rev` / `no`）；
        # 显式 `proof_no>1`（旧多证明调用点）的兼容写在行构造之后（见下面那一支）。
        "verifier": str(verifier or "V"), "verdict": checked["verdict"],
        "defect_step": checked["defect_step"], "quote": checked["quote"],
        "why": checked["why"], "findings": checked["findings"],
        "unresolved_errors": checked["unresolved_errors"],
        #: 引用核实（业主 2026-10-26）：`[{stmt_id, verdict, quote_verbatim, note}]`。
        #: 每一行都写这一个键（空列表 = "这一签核过、没有被引命题要核"，与历史行
        #: "没有这一格"在读侧分得开：老行没有它，新行有它、可以是空的）。
        "citation_checks": list(checked.get("citation_checks") or []),
        "proof_sha256": sha,
        "proof_chars": len(str(proof_text or "")),
        "round": int(round_no) if round_no is not None else len(rows) + 1,
        #: 这一行是"哪一趟送审的第几轮"（2026-11-02 定稿）：`review_call` 同一趟相同，
        #: `review_pass` 是 1..need。老行没有这两个键 ⇒ 读侧按历史形态（`legacy_rows`）计，
        #: 不参与新签判断。`round` 仍是全局台账行号，不是趟内轮次。
        "review_pass": int(review_pass) if review_pass is not None else None,
        "review_call": str(review_call or ""),
        "used_faces": [str(x) for x in used_faces],
        "submission_id": str(submission_id or ""),
        "at": verifications._now_iso(),
    }
    # ---- 产出方格（甲）：新行无条件写；老行读侧记 unknown（`producer_reading`）----
    row.update(_producer_cells(
        str(manuscript or producer_path or object_path or ""),
        producer_code=producer_code, roster_role=roster_role))
    if str(review_scope or "").strip():
        #: 2026-11-17（系统计数）：这一趟的「审了几轮」是不是只有一轮。只在一处写
        #: （在册穷举型证据那一档：机械七项会审一次落一行，不是三轮）；条件写入 ⇒
        #: 所有别的行逐字节不变。读侧（`sign_counting.count_registered`）见到它就把
        #: 这一签标成 `legacy:single_round_review` —— 那是登记在册的例外，不是静默
        #: 等价（签文件里也写 `legacy=true` + 同一个 `counted_by`）。
        row["review_scope"] = str(review_scope).strip()
    if no != DEFAULT_PROOF_NO:
        # 2026-11-11 业主裁定：`proof_no` 在 V 签侧退役 —— canonical（#p1）新行不再写。
        # 显式 `proof_no>1` 是旧多证明写口（一稿一份之后生产路径不再产生它）：旧读侧
        # （`consecutive_holds(proof_no=N)` / `_rows_of_proof`）按号分组，必须还能把这
        # 一行认成第 N 份，所以这一支照写；它不是新口径，是旧文件的写侧兼容。
        row["proof_no"] = int(no)
    if str(checked.get("verdict_raw") or "").strip():
        #: 折档那一行留住的模型原话（"它其实没判、只是没找到缺陷"这件事的唯一读数）。
        #: 只在真折过时写 ⇒ "模型自己就答了两态"的行与历史行逐字节不变。
        row["verdict_raw"] = str(checked["verdict_raw"]).strip()
    #: I10 硬禁令的机械命中（2026-10-27，业主裁定：先接成读数、不许直接挡签）。
    #: 命中就写一格 `hard_ban_markers`（"易证/显然/trivial/…"逐条），落盘可见；
    #: 只在命中时写（条件写入，老行与"没命中"的行逐字节不变）。它不参与任何判定：
    #: `signs_bit3` 不读它、`parse_verdict` 不因它改结论 —— 理由是"存量里有多少条
    #: 会被挡"还没量过，一次接上挡签会把一批历史证明打掉（业主 2026-10-27 的裁定）。
    _banned = banned_markers_in(proof_text)
    if _banned:
        row["hard_ban_markers"] = list(_banned)
    #: D-34：这一签审的对象（盘上那份报告 / 证明文件）的字节 sha256 与相对路径。
    #: 只在调用方真的知道时写（条件写入，老行因此逐字节不变），读侧按它认领
    #: "命题登记之前审的那一签"（`numericproof.latest_third_party_sign` 的第二路）。
    if str(object_sha256 or "").strip():
        row["object_sha256"] = str(object_sha256).strip().lower()
        row["object_path"] = str(object_path or "").strip().replace("\\", "/")
    #: 2026-11-04（业主裁定 甲）：这一签的载体（工作区相对路径）。在册命题也必须
    #: 有一份手稿：签块要盖回它，`sign_statement` 翻位时从这一格读到它、交给
    #: `vsigns.land`（`_vsign_payload` 不再靠"按约定路径扫盘"猜一份）。只在给了稿时
    #: 写（条件写入 ⇒ 老行逐字节不变；未在册那一支走的是 pending 台账，不经这里）。
    if str(manuscript or "").strip():
        row["manuscript"] = str(manuscript).strip().replace("\\", "/")
    #: 引用核实那一档的判据本行（`citation_gate` 的五格）。只在"这一档没查成"
    #: （`problem` 非空）时写：那时 `citation_checks` 往往是空数组（没有条目可核），
    #: 而空数组什么都不挡 —— 没有这一格，读侧（`signs_bit3`）就分不开"没查成"与
    #: "核过、没有引用"。查成了的行一个字都不多写（老行因此逐字节不变）。
    gate_problem = ""
    if isinstance(citation_gate, Mapping):
        gate_problem = str(citation_gate.get("problem") or "").strip()
    if gate_problem:
        row["citation_gate"] = {"ok": False, "problem": gate_problem,
                                "why": str(citation_gate.get("why") or "")}
    #: 秘书语义判定的两档轴（业主 2026-10-29 的 B 段；2026-10-30 第三次裁定收成两档）：
    #: `{axis, checked, decision, reason}`。
    #: 无条件写（业主裁定 2）：调用方给了判定就写它，没给就写"未判成"那一格
    #: （:data:`NO_SECRETARY_JUDGE`）。改前是条件写入 —— 不给就一个字节都不写，于是
    #: 那一行落进 `historical_axis` 的历史兼容支、按 `verdict` 字面拿到 clean。
    #: 为什么落在这一行而不是 `statements` 的新列：连续计数从台账派生（`draft/125` §二 A），
    #: 而"这一签当年算不算一票"是这一行的性质（`_hold_run_lengths` 读它）。
    _judge = secretary_judge_cell(secretary_judge)
    row[SECRETARY_JUDGE_KEY] = {
        "axis": _judge["axis"],
        "checked": bool(_judge["checked"]),
        "decision": str(_judge.get("decision") or ""),
        "reason": str(_judge.get("reason") or "")[:300],
    }
    # ---- D3 批 2：类别三格随判定一起落盘（不新增磁盘字段，仍在这一格里） --------
    #
    # 为什么只挑这三格白名单、不做整格透传：调用方给的判定里还有 `material` / `cost` /
    # `basis` 这些运行期大块（透传会把整份材料抄进台账行）。D3 要落的是分类结果：
    # `fault_kind`（可空）/ `fault_cause`（可空）/ `report_gap`（可空）。写侧（V 的
    # 写行处）每一行都给，于是新行的键一定在 —— 键在不在是 `fault_kind_of` 分
    # "新行 / 老行"的唯一依据。调用方没给时（老测试夹具 / 非 V 的写口）不写，
    # 那一行的读法回到 `legacy_*` 的保守推定（不会静默解锁）。
    for _key in ("fault_kind", "fault_cause", "report_gap", "defect_scope"):
        if _key in _judge:
            row[SECRETARY_JUDGE_KEY][_key] = str(_judge.get(_key) or "")[:500]
    #: CLAIM-INTEGRITY ②（2026-11-24）：`defect_scope` 写侧只认三档 + 空
    #: （词表只有一处：`v_vocab.DEFECT_SCOPE_VALUES`）。词表外的写法落成空 = 没分类 ——
    #: 不许让一个读侧读不出的值在重送闸那里"因为不是 statement 所以放行"。
    if str(row[SECRETARY_JUDGE_KEY].get("defect_scope") or "") not in DEFECT_SCOPE_VALUES:
        row[SECRETARY_JUDGE_KEY]["defect_scope"] = ""
    #: 洗过的那一份转达文本（业主 2026-10-29 的 C 段）：`{text, findings, dropped, refused}`。
    #: 只在秘书真的洗出来时写（`washed=True`）—— 洗不出来的那一档不写这一格：
    #: 台账上"没有这一格"必须是"没洗过/洗不出来"，而不许写一份空文本冒充洗过。
    #: 它是 C 段交付面的唯一来源（`agent_loop.v_rejections_digest` 读这一格），
    #: 于是"递给 F 的那段话"与"台账上留痕的那段话"是同一份字节。
    if isinstance(washed_relay, Mapping) and washed_relay.get("washed"):
        row["washed_relay"] = {
            "text": str(washed_relay.get("text") or ""),
            "findings": [dict(f) for f in (washed_relay.get("findings") or [])
                         if isinstance(f, Mapping)],
            "dropped": [dict(f) for f in (washed_relay.get("dropped") or [])
                        if isinstance(f, Mapping)],
        }
    if store is None:
        _append_verification(path, row)
        # 缺陷 A（2026-11-05）：重判之后把签块那两格刷到台账最新那一行。
        row["sign_block_refresh"] = _retrack_sign_block(root, row=row,
                                                       manuscript=manuscript)
        return _note_conjecture_refutation(root, row)
    if flip is False:
        # ---- 业主 2026-10-29 追加口径：V 不再自己发签 ----
        #
        # V 只产审稿意见；"翻不翻第 3 位"由 V 的秘书判（`Secretary.decide_sign_issuance`），
        # 落地那一步也由它调 `sign_statement(append_ledger=False)`。所以这一支只落台账
        # （正本先落，签这个事实不依赖任何人的决定），把翻位留给秘书：
        # `statement_writeback.deferred_to == "secretary"` 是"这一支没翻位"的可读读数，
        # 它不是失败（`checked` 仍为真：台账那一行确实落了）。
        append_state = "not_attempted"
        append_problem = ""
        try:
            _append_verification(path, row)
            append_state = "appended"
        except OSError as exc:
            append_state = "failed"
            append_problem = f"{type(exc).__name__}: {exc}"
        writeback: dict[str, Any] = {
            "written": False, "rolled_back": False, "append_state": append_state,
            "re_sign_required": append_state != "appended", "grade": "",
            "statement_id": str(statement_id), "proof_no": no,
            "proof_sha256": sha, "kind_upgrade": {}, "upgrade_note": "",
            "grade_recomputed": {},
            "streak": 0, "need": verifications.SIGN_STREAK_NEED, "streak_ok": False,
            "deferred_to": "secretary",
            "reason": (f"发签这一步不在这一支：在册档由 V 的秘书判定并发（业主 2026-10-29），"
                       f"未在册档由 V 自己颁发签信封。台账那一行已落（{vid}）"
                       + (f"；但签名那一行没写成（{append_problem}）" if append_problem else "")),
        }
        row["statement_writeback"] = writeback
        _mark_landed(row, writeback)
        # 缺陷 A（2026-11-05）：台账那一行落下之后刷签块（`vsigns.refresh_manuscript_sign`）。
        row["sign_block_refresh"] = _retrack_sign_block(root, row=row,
                                                       manuscript=manuscript)
        return _note_conjecture_refutation(root, row)
    if not row_signable(row):
        # 签不住的结论也要落台账（它是"看过、结论是没过"的证据），但它不翻任何位。
        # 追加由本函数做（`sign_statement` 在这一支只回一句理由、不碰台账）⇒ 由本函数
        # 把追加落在哪一态写回 `statement_writeback`（2026-10-22 审计第 5 条：那一格
        # 此前只有"-written 前的 -1"一个哨兵兼任两义，"签名确实发生过"可能是在说谎）。
        #
        # 判据是行局部那一半（`row_signable`），不是 `signs_bit3`：后者还要连续次数，
        # 而"连续次数不够"与"这一签签不住"是两件事 —— 前者仍要走 `sign_statement`
        # （它负责把台账追加在事务里、并在次数够了的时候翻位），后者连事务都不该开。
        # 改前这里写的是 `signs_bit3(row)`（那时它只有行局部那一半）；业主 2026-10-29
        # 给 `signs_bit3` 加了连续闸之后，若不同步改这一行，"成立但还差次数"那一支会
        # 被当成本支处理 ⇒ 台账会被追加两次（一次在这里、一次在 `sign_statement` 里）。
        append_state = "not_attempted"
        append_problem = ""
        try:
            _append_verification(path, row)
            append_state = "appended"
        except OSError as exc:
            append_state = "failed"
            append_problem = f"{type(exc).__name__}: {exc}"
        writeback = verifications.sign_statement(store, row=row, proof_text=proof_text,
                                   path=path, proof_no=no)
        writeback["append_state"] = append_state
        if append_state == "failed":
            writeback.update(
                written=False, re_sign_required=True,
                reason=(f"签名那一行没写成（{append_problem}）⇒ 这一签没有落地（必须重签）；"
                        + str(writeback.get("reason") or "")))
        row["statement_writeback"] = writeback
        _mark_landed(row, writeback)
        row["sign_block_refresh"] = _retrack_sign_block(root, row=row,
                                                       manuscript=manuscript)
        return _note_conjecture_refutation(root, row)
    writeback = verifications.sign_statement(store, row=row, proof_text=proof_text,
                               path=path, proof_no=no, sign_issuance=sign_issuance)
    row["statement_writeback"] = writeback
    _mark_landed(row, writeback)
    row["sign_block_refresh"] = _retrack_sign_block(root, row=row,
                                                   manuscript=manuscript)
    return _note_conjecture_refutation(root, row)


def _retrack_sign_block(root: str | Path, *, row: Mapping[str, Any],
                        manuscript: str = "") -> dict[str, Any]:
    """台账那一行落下之后：把这一份正文的签块刷到台账最新那一行（缺陷 A；永不抛）。

    为什么挂在这里（2026-11-05，真机 87 的读数）：签块上 `台账=` / `时间=` 两格此前
    只有 :func:`sign_statement` -> `vsigns.land` 一个写者，而它只在发签那一刻跑。
    同一份正文之后的每一次重判（同 sha 的新台账行）只追加台账、没人碰块 ⇒ 块永远停在
    第一次发签那一行（87：块说 v-000008，账上最新 v-000011；而且 v-000009 判了「有毛病」
    之后块还挂着旧签）。

    判据一个字都不在这里（唯一实现是 :func:`vsigns.refresh_manuscript_sign`）：这一格只
    负责"行落了就叫它一声"，并把它那一笔的三态读数带进返回值 —— 刷块失败不许带走这一签
    （台账那一行已经落了，它是正本）。读数的键是 `sign_block_refresh`（不落盘：
    它在追加之后才写进返回行，与 `statement_writeback` 同一条纪律）。
    """
    from . import vsigns as _VS

    try:
        return dict(_VS.refresh_manuscript_sign(
            root, artifact_sha=str(row.get("proof_sha256") or ""),
            statement_id=str(row.get("stmt_id") or row.get("statement_id") or ""),
            proof_no=row.get("proof_no"), manuscript=str(manuscript or "")))
    except Exception as exc:  # noqa: BLE001 —— 刷块失败不许带走这一签（台账已落）
        return {"checked": False, "state": "error",
                "why": (f"签块刷新没跑成（{type(exc).__name__}: {exc}）"
                        "⇒ 块可能停在旧那一签上（这一格没查成）")}


def _mark_landed(row: dict[str, Any], writeback: Mapping[str, Any]) -> None:
    """把"这一签有没有真的落地"写进返回行（`checked` / `re_sign_required` / `reason`）。

    判据只认 `writeback` 自己报的两格：`append_state == "appended"`（台账那一行真追加了）
    且没有 `rolled_back`（它没被撤回）。只看 `verdict` 会把"被撤回的那一签"读成"签住了"，
    而台账盘上是 0 字节 —— 这正是本批审计第 1 条的读数（`checked=True verdict='成立'
    signed_bit3=True` 而台账字节数 0）。
    """
    landed = (str(writeback.get("append_state") or "") == "appended"
              and not writeback.get("rolled_back"))
    row["checked"] = bool(landed)
    row["re_sign_required"] = bool(writeback.get("re_sign_required"))
    if landed:
        row["reason"] = ""
        return
    head = "台账那一行被撤回" if writeback.get("rolled_back") else "台账那一行没写成"
    row["reason"] = (f"{head}：这一签没有落地（必须重签）；位没有改成 reviewed="
                     f"{bool(writeback.get('written'))}；写回原话："
                     f"{str(writeback.get('reason') or '')}")


def _verification_line(row: Mapping[str, Any]) -> str:
    """台账的一行怎么落盘（唯一实现：追加与撤回都拿它算字节）。"""
    return json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str) + "\n"


def _append_verification(path: Path, row: Mapping[str, Any]) -> int:
    """追加一行，返回追加前的文件字节数（撤回时按它截断）。"""
    line = _verification_line(row).encode("utf-8")
    before = path.stat().st_size if path.exists() else 0
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line.decode("utf-8"))
    return before


def _rollback_append(path: Path, before: int, row: Mapping[str, Any]) -> bool:
    """把刚追加的那一行撤掉（只撤我们自己的那一行）；撤不动 ⇒ False。

    判据是"文件尾逐字等于我们写的那一行"：文件尾若已经变成别人的行，截断会
    删掉别人的记录 —— 那种情况下宁可留着我们这一行（它确实发生过），也不动别人的。
    """
    want = _verification_line(row).encode("utf-8")
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if data[before:] != want:
        return False
    try:
        with path.open("r+b") as fh:
            fh.truncate(before)
        return True
    except OSError:
        return False


# 跨模块引用放在文件末尾：这些名字的实现在别的模块里，而两个模块可能互相
# 引用（顶层 `from .x import y` 在环里会在对方还没定义完时执行）。引用点
# 全部在函数体里，所以只要定义都跑完了，谁先被导入都拿得到。
from . import verifications  # 门面字典：被打桩的名字经它取
from .v_vocab import (  # noqa: F401 — 实现在 v_vocab.py
    DEFECT_SCOPE_VALUES,
    SECRETARY_JUDGE_KEY,
    _FAULT_VERDICT,
)
from .v_paths import (  # noqa: F401 — 实现在 v_paths.py
    VerificationError,
    _producer_cells,
    _sign_sha,
    parse_verdict,
    proof_no_strict,
    verification_ledger_path,
)
from .v_rowread import (  # noqa: F401 — 实现在 v_rowread.py
    row_signable,
    secretary_judge_cell,
)
from .v_defect import (  # noqa: F401 — 实现在 v_defect.py
    banned_markers_in,
)
