# -*- coding: utf-8 -*-
"""签落位（翻位/降级/义务）。

2026-11-20（VERSPLIT2）：`v_sign_flip.py` 是从 `verifications.py` 搬出的 9 块 / 757 行（块
逐字未动，逐名 AST 全等在 `temp/versplit2/` 可复算）。对 32 个被测试打桩的名字，读
一律写成 `verifications.<name>` —— 门面字典在调用那一刻才查，所以
`monkeypatch.setattr(verifications, ...)` 仍然到得了这里（`from .x import X` 是快照，
补丁到不了）。跨模块 import 放在文件末尾：模块之间有互相引用，定义全跑完再 import
才解得开环。
"""

from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from . import depsection as _DS  # 可引门槛的唯一定义（`CITATION_MIN_LEVEL`）
from . import evidencebits as EB  # 等级的唯一派生口（`derive_grade` / 反算表）
from . import jsonlfile as JF
from . import schema as S  # 编号形态的唯一来源（六位 / 旧四位读侧兼容）


def _reviewed_statement_row(found: Mapping[str, Any], verification_row: Mapping[str, Any],
                           *, proof_text: str, proof_no: int = 1,
                           streak: Any = None) -> dict[str, Any]:
    """命题那一行改成"那一份证明的第 3 位已签"的样子。

    只动四处：那一份证明的 `reviewed`（#p1 = `bits.reviewed` 的汇总位；#p2+ 另外把
    `proofs` 清单里对应项标上）、逐条证明的那张表
    （`bits.evidence.reviewed_by_proof = {"1": true, "2": false, ...}`）、逐条证明的
    "那一签盖住哪一份正文"那张表（`bits.evidence.reviewed_sha_by_proof`）与凭据
    `reviewed_by`；别的一格不碰。等级必须现算
    （`evidencebits.normalize_raw` 的唯一入口）：盘上那份 `grade` 只是缓存，写下去的
    必须与现算逐字相同，否则提交期 `bits_shape_problems` 会拒收这一笔。

    ## 逐条表为什么必须整表写，而不是只写被签的那一格
    业主的负控是"签了 #p1、#p2 读成 False"。只写 `{"1": true}` 的话，`#p2` 是"表里
    没有这一格"——而"没有"与"有、值为 False"在读侧长得不一样：前者要靠调用方记得
    缺省是 False，后者是直接读出来的结论。所以这里把 `proof_list` 里每一份都列出来，
    被签的那一份为 True，其余按原来的值（没有再按 False）。汇总位
    `bits.reviewed` 的语义不变：任一份为 True 即 True。

    ## 第二张表为什么也整表写（sha 那一格）
    汇总位要回答"还有没有一份证明仍盖着现在这一份正文"。`reviewed_by` 只留最近那一签，
    只核它会让"签过 #p1、之后改了 #p2"读成没审过。所以逐条记下每一签的 sha：被签的
    那一份换成这一签的 `proof_sha256`，其余保留原值（没有就写空串 = 这一份判不了）。
    """
    from . import evidencebits as _EB   # 惰性：只在真写这一行时需要（不新增模块级依赖边）

    new = dict(found)
    # 证明号已经在 `sign_statement` 判过（`proof_no_strict`：没给 ⇒ canonical，给了坏值 ⇒
    # 拒）；这里再走一遍同一个函数是防"将来有人直接调本函数"时把 0 静默折成 #p1。
    no = proof_no_strict(proof_no)
    payload = bit3_payload(verification_row, streak=streak)
    reviewed_by = dict(payload.get("reviewed_by") or {})
    bits = dict(new.get("bits") or {})
    ev = dict(bits.get("evidence") or {})
    # 逐条表整表写（含未签的那几份为 False）：`#p2` 不许借 `#p1` 的光。
    per = {str(n): bool(v) for n, v in
           (_EB.reviewed_by_proof(new) or {}).items()}
    per = {str(n): bool(per.get(str(n), False)) for n, _ in proof_list(new)}
    per[str(no)] = True
    ev[_EB.REVIEWED_BY_PROOF_KEY] = per
    # 逐条证明的"那一签盖住的是哪一份正文"：`{证明号: sha256}`（没签过 / 判不了的写空串）。
    # 汇总位按"任一条仍 in-sync ⇒ True"读，靠的就是这一格（见 `_stale_review_cleared`）。
    sha_by_proof = {str(n): str(v) for n, v in
                    (_EB.reviewed_sha_by_proof(new) or {}).items()}
    sha_by_proof = {str(n): str(sha_by_proof.get(str(n), "")) for n, _ in proof_list(new)}
    sha_by_proof[str(no)] = str(verification_row.get("proof_sha256") or "")
    ev[_EB.REVIEWED_SHA_BY_PROOF_KEY] = sha_by_proof
    # 命题那一行的 `bits.reviewed` 是"这条命题至少有一份证明被审过"的汇总位（老读者
    # 只认它）；真正的凭据按证明记：`reviewed_by` 里带 `proof_no` 与 `proof_sha256`，
    # 于是"这一位说的是哪一份"不再靠猜。
    ev["reviewed_by"] = reviewed_by
    bits["reviewed"] = any(per.values())
    bits["evidence"] = ev
    new["bits"] = _EB.normalize_raw(bits, origin=str(new.get("origin") or "own_result"),
                                    kind=str(new.get("kind") or ""))
    if no > 1:
        entries = [dict(p) if isinstance(p, Mapping) else p
                   for p in (new.get(PROOFS_KEY) or [])]
        for p in entries:
            if isinstance(p, dict) and proof_no_of(p) == no:
                p["reviewed"] = True
                p["reviewed_by"] = dict(reviewed_by)
        new[PROOFS_KEY] = entries
    return new


def _kind_upgrade_from_signature(row: Mapping[str, Any], *, root: str | Path,
                                 verifier: str) -> dict[str, Any]:
    """V 判「成立」之后，按证据位把这一行的 `kind` 现算一遍（D-69）。

    ## 为什么它在签名这一笔里（断链在哪）
    D-37 已经有"kind 该不该跟着证据升"的唯一判据（`evidencebits.kind_following_grade`，
    纯读），但它的写侧落点都不在"V 签字"这条路上：
    `agent_b.register_statement` 的那一格只在第 4 位（形式化）同步出变化时才跑。
    于是真机 sylow3 那种形态 —— V 的台账里判「成立」、`bits.evidence.reviewed_by_proof`
    是 `{"1": true}`，而 `statements` 那一行的 `kind` 仍是 `conjecture` —— 没有任何一步会
    去改它：读的人（G 写稿 / H 审校 / 收工门）读 `kind`，于是"这是定理"这句话在盘上
    不存在，论文却已经把它排成 lemma / theorem。

    这一格就是那条断链的补口：台账那一行刚追加进 `verifications/<命题号>.jsonl`
    （同一个事务里），`kind_following_grade` 现在读得到那一签，于是把它放在
    `_reviewed_statement_row` 之后、`tx.upsert` 之前 —— 位与档位同一笔事务落盘。

    ## 只抬 `kind`，不碰 `evidence_kind`
    `evidence_kind` 的抬档已经有一条正路（秘书那一支，凭据是同一个
    `verifications.proof_review_gap`），而 `kind` 那一格没有任何一条正路会在签字之后
    到达。两件事各修一处，不再造第二份 `evidence_kind` 口径。

    ## 三态（判不了就不抬）
    只有 `kind_following_grade` 说 `state="upgraded"` 时才改那一格：`held`（凭据不够）
    与 `unreadable`（五元位算不出来）都原样返回 —— "没判成"绝不折成"已经升了"。
    这一笔也绝不降档：起点只认 `conjecture`（`KIND_UPGRADABLE_FROM`），别的 kind 一个字不动。

    返回 `{"row", "kind_upgrade", "note"}`：`row` 是（可能）改过 `kind` 的那一行，
    `kind_upgrade` 是与秘书那一支同形的留痕（`from` / `to` / `basis` / `grade` /
    `by` / `at`），`note` 是给返回读数看的那一句「因 V 判成立而抬档：…（依据 …）」。
    """
    from . import evidencebits as _EB   # 惰性：与 `_reviewed_statement_row` 同一条纪律

    out: dict[str, Any] = {"row": dict(row), "kind_upgrade": {}, "note": ""}
    read = _EB.kind_following_grade(out["row"], root=root)
    if str(read.get("state") or "") != "upgraded":
        return out
    target = str(read.get("kind") or "")
    before = str(out["row"].get("kind") or "")
    if target not in _EB.KIND_UPGRADE_TARGETS or target == before:
        return out
    basis = str(read.get("basis") or "")
    out["row"]["kind"] = target
    out["row"]["_kind_upgrade"] = {
        "from": before, "to": target, "basis": basis,
        "grade": str(read.get("grade") or ""),
        "by": str(verifier or "verifier-V"), "at": S.now_iso(),
    }
    out["kind_upgrade"] = dict(out["row"]["_kind_upgrade"])
    out["note"] = (f"因 V 判成立而抬档：{before or '（空）'}→{target}"
                   f"（依据 {basis or '台账里那一签'}）")
    return out


def _exhaustion_proof_channel(row: Mapping[str, Any], *,
                              root: str | Path) -> dict[str, Any]:
    """这一行的证明走的是不是「E 的穷举程序 + V 签」那条通道 —— 纯读，不写任何东西。

    ## 为什么回填必须分通道（业主 2026-11-04 的裁定，写死在 `schema.EVIDENCE_KINDS`）
    穷举数值证明 + 针对该穷举的 V 签 ⇒ 直接 `proof`；`proof_review` 的定义是
    "V 逐行审过文字证明"，而 V 不能逐行走查一份程序 ⇒ 穷举题停在 `proof_review`
    本身就是错的终态。所以"V 落签之后按签重算档位"这一格不能一律给 `proof_review`：
    它得先问一句"这一份证明是哪条通道的"。

    ## 判据只有一处（不另立第二套穷举口径）
    这一格只问 `numericproof.find_signed_exhaustion_for_column` —— 它内部读
    `is_signed_exhaustion`（方法属于计算类、`evidence_kind="proof"`、签名主体 V、
    ②③ 作者含 E、`proof_reason="exhaustion"`），正是 `verify` 审计
    （`proof_stmt_without_formal_backing` 的第二条合法背书）与 B 的入库闸用的那一个函数。
    于是"回填给的档"与"审计认的背书"结构上是同一件事，不会分家。

    ## 三态（判不了就不按穷举给档）
    - `checked=False`：实验台账读不出来（没给根 / 表坏了）⇒ "没查成"，调用方按文字
      证明通道处理（`proof_review`）—— 不许把"没查成"读成"是穷举"；
    - `checked=True, found=False`：查过了，台账里没有这份证明栏对应的穷举证明
      ⇒ 文字证明通道；
    - `found=True`：`experiment_id` / `script` 指向那一条 E 签的穷举证明。

    返回 `{checked, found, experiment_id, script, why}`。
    """
    out: dict[str, Any] = {"checked": False, "found": False, "experiment_id": "",
                           "script": "", "why": ""}
    text = str(row.get("proof_text") or "")
    if not text.strip():
        out["checked"] = True
        out["why"] = "这一行没有证明正文 ⇒ 通道判不了（也就没有任何一档可升）"
        return out
    if not str(root or "").strip():
        out["why"] = "没给工作区根 ⇒ 实验台账读不出来（这一格没查成）"
        return out
    try:
        from . import numericproof as _NP   # 惰性：穷举判据的单一口径
        from .store import Store           # 惰性：只读一份表，不参与本模块的写事务

        experiments = Store(root).rows("experiments")
    except Exception as exc:  # noqa: BLE001 —— 读不出来要如实说，不许猜成"是穷举"
        out["why"] = (f"实验台账读不出来（{type(exc).__name__}: {exc}）⇒ 这一格没查成"
                      "（按文字证明通道处理，不按穷举给 proof）")
        return out
    out["checked"] = True
    hit = _NP.find_signed_exhaustion_for_column(experiments, text)
    if hit is None:
        out["why"] = ("台账里没有与这份证明栏对应的、V 签下的穷举证明 "
                      "⇒ 这一行走文字证明通道（`proof_review`）")
        return out
    out["found"] = True
    out["experiment_id"] = str(hit.get("experiment_id") or hit.get("id") or "")
    out["script"] = _NP.proof_column_script(text)
    out["why"] = (f"证明栏是穷举证明的三段式（① 程序 {out['script'] or '（空）'} + ②③），"
                  f"台账里 exp:{out['experiment_id'] or '?'} 是 V 签下的穷举证明")
    return out


def _grade_recomputed_from_signature(row: Mapping[str, Any], *, root: str | Path,
                                     proof_no: Any = None) -> dict[str, Any]:
    """V 的签刚落位 ⇒ 按现行签现算等级（只算等级，不再写档位）。

    ## 业主 2026-11-05 的裁定（为什么这一格从"写档"改成"只算等级"）
    「档位不再是一套词表：`evidence_kind` 只作历史列保留，判定面一律读等级」。
    于是这一格不再回答"该把 `evidence_kind` 写成哪一档"，只回答"按五元位现算，
    这一行现在是哪一级"。签落位之后 `bits.reviewed` 已被 `_reviewed_statement_row`
    翻真 ⇒ 等级自然升到 `pre_theorem`（或第 1/4 位本就 verified 时到 `theorem`）；
    这一格不复制那份真值，它只是把"凭什么"（哪一份台账的哪一签）与档位的历史反算名
    （`kind_from_grade`）写进读数，供回执与审计用。

    ## 三态（不折平）
    - 凭据读不出来 ⇒ `checked=False`（"没查成"既不是"不够格"也不是"没变"）；
    - 凭据不够（没签 / 签的是旧版 / 判的不是成立）⇒ `reading={}`（negative：
      没签的命题不许被这一格说成"升了"）；
    - 算出来了 ⇒ `to` 是等级、`to_kind` 是它的历史反算名。

    ## 只读
    本函数一个字节都不写：`out["row"]` 是入参的副本、`evidence_kind` 不动。
    写档位的地方（若还有）必须走 `EB.kind_from_grade` 反算，不许拿这一格的
    `to` 直接当档位（那是把等级又译回第二套真值）。`_apply_grade_backfill`
    是那唯一一处写者，写的是反算名，不是"这一格给的目标档"。

    返回 `{"row", "reading"}`：`reading` 是
    `{checked, from, to, from_kind, to_kind, why, basis, proof_no, at}`；
    没动过就是 `{}` —— 键的存在本身说明"这一签改变了等级读数"。
    """
    out: dict[str, Any] = {"row": dict(row), "reading": {}}
    if str(out["row"].get("kind") or "") == "concept":
        # 概念不参与等级链：既不是"升了"也不是"不够格"，这一格没有它的事。
        return out
    try:
        gap = verifications.proof_review_gap(root, out["row"], proof_no=proof_no)
    except Exception as exc:  # noqa: BLE001 —— 读不出来要如实说，不许当成"不够格"
        out["reading"] = {
            "checked": False, "from": "", "to": "",
            "why": (f"凭据读不出来（{type(exc).__name__}: {exc}）⇒ 这一格没查成，"
                    "等级与档位一个字节不动")}
        return out
    if not gap.get("ok"):
        return out
    ledger = str(gap.get("ledger") or "")
    vid = str(gap.get("verification_id") or "")
    # 两支的 `ledger` 形状不同：台账支是路径（`verifications/<号>.jsonl`），pending 支
    # 已经带着号（`verifications/pending/<sha>.jsonl#u-000001`，见 `pending_sign` 的
    # `ledger`）。这里只在"还没带号"时补一次 —— 否则 pending 支会拼成
    # `…jsonl#u-000001#u-000001`：同一个锚点写两遍，读的人会以为那是两层定位。
    basis = (f"{ledger}#{vid}" if ledger and vid and not ledger.endswith(f"#{vid}")
             else (ledger or vid))
    try:
        bits = EB.bits_from_row(out["row"])
    except Exception as exc:  # noqa: BLE001 —— 同上：算不出来就是没查成
        out["reading"] = {
            "checked": False, "from": "", "to": "",
            "why": (f"五元位算不出来（{type(exc).__name__}: {exc}）⇒ 这一格没查成，"
                    "等级与档位一个字节不动")}
        return out
    # ---- 穷举通道：签住的是 E 的穷举程序 ⇒ 第 1 位落 verified ---------------
    #
    # 2026-11-05 业主裁定「穷举证书相当于 Lean 形式化，表示绝对正确」，于是
    # `derive_grade` 的 `theorem` 有两条同级入口：第 2 位 + 第 4 位（formal verified）
    # 或第 2 位 + 第 1 位（numeric verified）。但"V 签住这一份穷举证明"这件事此前
    # 没有任何写者把它落到第 1 位：`_exhaustion_proof_channel` 还在，却没人调用
    # ⇒ 穷举题签完停在 `pre_theorem`，永远到不了 `theorem`。
    #
    # 位置与 `_reviewed_statement_row` 的 reviewed 同一步：签已经落位（gap.ok），
    # 这一格只把"签住的那份证明是哪条通道"翻译成第 1 位。通道判据只有一处
    # （`numericproof.find_signed_exhaustion_for_column`），这里不另写一份。
    channel = "text"
    try:
        _exhaustion = _exhaustion_proof_channel(out["row"], root=root)
    except Exception:  # noqa: BLE001 —— 通道判不了就按文字证明（不猜成穷举）
        _exhaustion = {"checked": False, "found": False, "why": ""}
    if _exhaustion.get("found"):
        evidence = dict(bits.get("evidence") or {})
        evidence["numeric"] = {
            "experiment_id": str(_exhaustion.get("experiment_id") or ""),
            "script": str(_exhaustion.get("script") or ""),
            "why": str(_exhaustion.get("why") or ""),
        }
        bits = dict(bits, numeric="verified", evidence=evidence)
        kind_now = str(out["row"].get("kind") or "")
        out["row"]["bits"] = EB.normalize_raw(
            bits, origin=str(out["row"].get("origin") or "own_result"),
            voided_by=dict(bits.get("voided_by") or {}), kind=kind_now)
        bits = out["row"]["bits"]
        channel = "exhaustion"
    target = EB.derive_grade(bits, kind=str(out["row"].get("kind") or ""))
    from_kind = str(out["row"].get("evidence_kind") or "").strip()
    from_grade = EB.KIND_TO_GRADE.get(from_kind, "")
    # ---- 幂等（不写第二个时间戳）：两件都算"这一签没有新消息" ----------------
    # ① 历史列反算出来的等级与现算等级相同（例如位没翻 ⇒ 两边都是 conjecture）；
    # ② 行上已经有一条 `to` 相同的回执（同一份签再签一次）。
    # 只读行上的回执，不读 `evidence_kind` 当第二套真值 —— 后者只是 `from` 的读数。
    prior = out["row"].get(GRADE_RECOMPUTED_KEY)
    if from_grade and from_grade == target:
        return out
    if isinstance(prior, Mapping) and str(prior.get("to") or "") == target:
        return out
    out["reading"] = {
        "checked": True,
        "from": from_grade, "to": target,
        "from_kind": from_kind, "to_kind": EB.kind_from_grade(target),
        "channel": channel,
        "why": ("V 的签刚落位：这一行有证明正文，且台账里那一签盖住的就是现行这一版 "
                "⇒ 按五元位现算等级（只算等级，不写档位）；"
                f"历史列 `evidence_kind`={from_kind or '（空）'} 只是读数，判定面读 `{target}`"),
        "basis": basis, "proof_no": int(gap.get("proof_no") or 0) or None,
        "at": verifications._now_iso(),
    }
    return out


def _vsign_payload(*, root: Any, ledger: Path, statement_id: str, proof_no: int,
                   sha: str, need: int, holds: Mapping[str, Any],
                   manuscript: str = "") -> dict[str, Any]:
    """组一份签的内容（纯读：台账 + 手稿路径；不写任何东西）。

    业主 2026-11-01（逐字）：「V 签不直接进台账，进手稿，随 B 侧将手稿中的定理或命题
    收录时读到。」于是签要落成「按被签正文 sha 命名」的一份侧文件（`out/vsigns/<sha>.json`），
    它的内容全部从台账现读，不复制全文：

    - `passes`：这一份正文尾部连续 `need` 转的 `{verification_id, at, proof_sha256, why}`
      （`why` 是 V 那一转自己写的理由，逐字；「全文在台账」，见 `vsigns.PASSES_SOURCE_NOTE`）；
    - `objections`：「同一份 sha」 上的「有毛病」记录（两档都算：V 自己判的、秘书判 fault 的）。
      为什么要它：同一段正文可能先被判有毛病、后来连续三次成立拿到签（V 改判 / 秘书在
      「V 写成立」的回复上读出缺陷那一档）—— 那段痕迹必须留在签上，否则"先有毛病、后有签"
      这件事在签这一份文件里看不见（跨 sha 的改版链不在这里，那是台账 `superseded` 的事）；
    - `artifact_path`：这一签的载体。给了 `manuscript` 就用它（在册那一支从台账行带来，
      2026-11-04 甲：手稿是签的唯一载体）；没给才退回 `depsection.manuscript_relpaths`
      扫"按号命名的 f-proof 稿"（旧行为）。两者都找不到就留空 —— `ledger` 那一格永远有，
      所以定位不会丢。

    `written_by` 不在这里定（本函数只组内容）：它由调用方那一格
    :func:`_vsigns_write_after_flip` 按 `append_ledger` 分两档 —— 秘书落地那条路
    （V 先落台账、秘书只翻位）是 `secretary`，直调写入口（夹具 /
    `record_verification(flip=True)`）是 `sign_statement(direct)`。两者都真实发生过，
    把后者也写成 secretary 会让"这张签是谁发的"变成假话。
    """
    from . import vsigns as _VS

    out: dict[str, Any] = {"passes": [], "objections": [], "artifact_path": "",
                           "ledger": f"{VERIFICATIONS_DIR}/{statement_id}.jsonl#"
                                     f"{str(holds.get('verification_id') or '')}",
                           "at": S.now_iso()}
    try:
        rows, _problems = JF.read_jsonl(ledger)
    except OSError:
        rows = []
    mine = _rows_of_proof([dict(r) for r in rows], proof_no)
    runs = _hold_run_lengths(mine)
    want = max(1, int(need or 1))
    passes: list[dict[str, Any]] = []
    # ---- 2026-11-02：签的 `passes` 只许来自同一趟送审（业主：「不允许跨两次送审
    # 累计成功数」）。持有 `review_call` 时按它取行，绝不按台账尾部的连续票数回捞 ——
    # 后者会把旧台账里的 clean 行拼进本次的签（实测：2 行历史 + 本次第 1 轮，tail=3
    # 会捞到 runs=3/2/1 的三行，其中两行是历史行）。
    call_id = str(holds.get("review_call") or "")
    if call_id:
        picked = [r for r in mine
                  if str(r.get("review_call") or "") == call_id
                  and int(r.get("review_pass") or 0) >= 1]
        picked.sort(key=lambda r: int(r.get("review_pass") or 0))
        picked = picked[:want]
        for r in picked:
            passes.append({
                "verification_id": str(r.get("verification_id") or ""),
                "at": str(r.get("at") or ""),
                "proof_sha256": str(r.get("proof_sha256") or ""),
                "why": str(r.get("why") or ""),
                # 这两格让"三票同源"在签文件里可直接读（vsigns.write_sign 原样复制）。
                "review_call": call_id,
                "review_pass": int(r.get("review_pass") or 0),
            })
    else:
        # 历史 / 直调路径：按台账尾部连续票数回捞（旧行为，逐字不变）。
        # 尾部那一串连续成立的票：`runs[i]` 就是"到这一行为止连续几次"，
        # 所以从尾部往回收 `streak, streak-1, …` 恰好收齐那一串。
        # 为什么不用 `signs_bit3(row, streak=runs[i])` 过滤：那个谓词问的是"这一行能不能翻位"
        # （要够门槛），而这里要的是"哪几行是这一签的票"—— 前两票本来就不够门槛，
        # 用翻位谓词会把它们全滤掉（实测：passes 只剩 1 条）。
        tail = int(holds.get("streak") or (runs[-1] if runs else 0))
        for i in range(len(mine) - 1, -1, -1):
            if len(passes) >= want:
                break
            if str(mine[i].get("proof_sha256") or "") != sha:
                continue
            if runs[i] != tail - len(passes):
                continue
            one = {"verification_id": str(mine[i].get("verification_id") or ""),
                   "at": str(mine[i].get("at") or ""),
                   "proof_sha256": str(mine[i].get("proof_sha256") or ""),
                   "why": str(mine[i].get("why") or "")}
            if (str(mine[i].get("review_call") or "")
                    or mine[i].get("review_pass") is not None):
                one["review_call"] = str(mine[i].get("review_call") or "")
                one["review_pass"] = mine[i].get("review_pass")
            passes.append(one)
        passes.reverse()
    if passes:
        # 最后的那一签就是这一份签的落点（台账行序 = 追加序，不存在第二种"最近"）。
        out["ledger"] = f"{VERIFICATIONS_DIR}/{statement_id}.jsonl#" \
                        f"{passes[-1]['verification_id']}"
    out["passes"] = passes
    objections: list[dict[str, Any]] = []
    for row in mine:
        if str(row.get("proof_sha256") or "") != sha:
            continue
        axis = _VS.verdict_axis(row)
        if not axis:
            continue
        objections.append({"verification_id": str(row.get("verification_id") or ""),
                           "at": str(row.get("at") or ""),
                           "axis": axis,
                           "defect_steps": _VS.defect_steps(row)})
    out["objections"] = objections
    # ---- 载体：点名的那一份优先（2026-11-04 甲）---------------------------------
    #
    # 改前只按 `depsection.manuscript_relpaths` 扫"按号命名的 f-proof 稿"：真机里稿
    # 叫 `notes/...` 或 B 的 `b-proof-<号>.md` 时就扫不到，签只落进台账、稿上没有签块。
    # 现在在册那一支把 `proof_manuscript` 随台账行带进来（`record_verification` 的
    # `manuscript` 参数）⇒ 就盖回送审方点名的那一份；没点名时才退回扫盘（旧行为）。
    named = str(manuscript or "").strip().replace("\\", "/")
    try:
        if named:
            if (Path(str(root)) / named).is_file():
                out["artifact_path"] = named
            # 点名了而盘上没有 ⇒ 不退回扫盘：签会盖到另一份稿上，那比"没有落点"更坏。
            # 这一档由 `_registered_manuscript_body` 在更早处拒掉，到这里只作兜底。
        else:
            from . import depsection as _DS

            for rel in _DS.manuscript_relpaths(statement_ids=[statement_id]):
                if (Path(str(root)) / rel).is_file():
                    out["artifact_path"] = str(rel)
                    break
    except Exception:  # noqa: BLE001 —— 定位那一格读不成不算失败（它不参与判据）
        out["artifact_path"] = ""
    return out


def _registration_after_vsign(*, store: Any, root: Any, vsign: Mapping[str, Any],
                              statement_id: str, proof_no: int,
                              sha: str, skip_gap: bool = False,
                              wake: bool = True) -> dict[str, Any]:
    """`sign_statement` 那一笔事务之外：签块落成了就给 B 开一条「必须收录」义务。

    为什么必须在事务之外（2026-11-05 实测）：`_vsigns_write_after_flip` 跑在
    `store.tx("statements")` 里面，而开板项要拿 `tasks` / `counters` 的锁 ⇒ 在里面开项
    直接撞 `StoreError: 获取 counters 的锁超时（30.0s）`（同一进程已经持有那把锁）。
    所以这一格落在事务落定之后（`sign_statement` 的返回之前）。

    为什么以"块真的落成"为闸：义务的凭据是稿上那一块成立的签。没落成（未在册 / 秘书
    不在场 / 正文不符那几档）不是"签了没人收录"，那一档由收工对账
    （`obligations.sweep_registrations`）按盘上的事实兜底 —— 这里不编一条。

    `wake=True`（SGN1，2026-11-17）：签落地就是"必须真把 B 叫醒"的那一刻 —— 义务项
    只在"没有 B 台账号"时开成无主的，无主的项不进任何人的收件箱（真机 lp-ball-5：
    3 枚签、0 条义务、B 一次没被召唤）。呼唤的读数落在返回值的 `wake` 格里。
    """
    land = dict(vsign.get("land") or {}) if isinstance(vsign, Mapping) else {}
    if not land.get("landed"):
        return {"checked": True, "state": "skipped", "code": "sign_not_landed",
                "reason": ("签块没落成 ⇒ 这一档不是「签了没人收录」（收工扫盘按盘上的"
                           "事实兜底），不在这里开义务")}
    sign = dict(vsign.get("sign") or {}) if isinstance(vsign, Mapping) else {}
    mw = dict(land.get("manuscript_write") or {})
    rel = str(mw.get("path") or sign.get("artifact_path") or "")
    return _registration_after_sign(store=store, root=root,
                                    statement_id=str(statement_id or ""),
                                    proof_no=int(proof_no or 1), sha=str(sha or ""),
                                    manuscript=rel, at=str(sign.get("at") or ""),
                                    skip_gap=skip_gap, wake=wake)


def _registration_after_sign(*, store: Any, root: Any, statement_id: str, proof_no: int,
                             sha: str, manuscript: str, at: str = "",
                             skip_gap: bool = False,
                             wake: bool = False) -> dict[str, Any]:
    """签发（签块落成）之后：给 B 开一条「必须收录」义务（缺陷 B；永不抛）。

    为什么在这里（业主 2026-11-05）：87 的现场是"签了但没人收录"——
    `reports/f-proof-000000.md` 上有 `secretary:F` 的成立签，而 `statements:000000`
    仍是 `正文=0 / reviewed=false`；盘上的根因是 D 从头没派 B 收录（B 在 87 里只被派过
    1 次，还是文献侧的 `t-000027`）。教学里那句话（`specs/d.py`「那一行写进你的报告之后
    派 B 入库」）在，但"教"不是"义务"：签发之后必须有东西把"这一份还没入库"摆到 B 面前。

    判据一个字都不在这里（唯一实现是 `obligations.registration_gap` /
    `obligations.ensure_registration` 与它们的幂等键 `b-register@<命题号>@<sha>`）。
    这一格只做两件事：认出"这一签的载体是不是 `reports/{f,b}-proof-…`"（不是就不开：
    那一档不在这一条义务的射程内），然后把读数带进返回值。失败不许带走这一签。

    三态：`checked` / `state`（`opened` / `existing` / `closed` / `cleared` / `expired` /
    `skipped` / `error`）/ `reason`；`skipped` 里 `code=not_a_proof_carrier` 说的是
    "这一签的稿不在这一条义务的射程内"，不是"已经收录了"。

    `skip_gap=True`（2026-11-08，V 的签后义务）：不读 `statements` 去判断"是不是已经收录了"。
    义务的存在与它是否已满足是两件事 —— V 只对手稿负责，签落成后就无条件开义务；
    "满足了没有"由 B 收录时消账、收工时 `sweep_registrations` 按盘上事实收口。

    默认 `False` 只服务历史直调（`sign_statement` 末尾那一支：兼容门，仍按 `statements`
    判"已收录"）；生产签后义务在 `land_sign_without_ledger` 里显式传 `skip_gap=True`。
    判据 `test_production_landing_does_not_rely_on_write_defaults` 逐条核这一格。

    `wake`（SGN1，2026-11-17）：签落地那一刻必须真把 B 叫醒（见
    :func:`_registration_after_vsign`）；生产两处（`land_sign_without_ledger` /
    `sign_statement`）与未在册那一支（:func:`registration_after_unregistered_sign`）
    都传 `True`。
    """
    from . import obligations as _OBL

    out: dict[str, Any] = {"checked": False, "state": "skipped", "key": "", "item_id": "",
                           "owner": "", "owner_known": False, "code": "", "reason": "",
                           "wake": {}}
    rel = str(manuscript or "").strip().replace("\\", "/")
    if not rel:
        out.update(code="no_manuscript",
                   reason="这一签没有手稿载体 ⇒ 这一条义务不知道要收录哪一份（不是「已收录」）")
        return out
    if not any(rel.startswith(prefix) for prefix in _OBL.REGISTRATION_CARRIERS):
        out.update(code="not_a_proof_carrier",
                   reason=(f"`{rel}` 不是 `reports/{{f,b}}-proof-…` 那一类载体 "
                           f"{list(_OBL.REGISTRATION_CARRIERS)} ⇒ 不在这一条义务的射程内"))
        return out
    label = f"{str(statement_id or '')}#p{int(proof_no or 1)}"
    try:
        got = _OBL.ensure_registration(store=store, root=root, label=label,
                                       proof_sha=str(sha or ""), manuscript=rel,
                                       called_by="V", at=str(at or ""),
                                       skip_gap=bool(skip_gap), wake=bool(wake))
    except Exception as exc:  # noqa: BLE001 —— 开义务失败不许带走这一签
        out.update(code="registration_raised",
                   reason=(f"开「必须收录」义务那一笔抛了（{type(exc).__name__}: {exc}）"
                           "⇒ 这一格没查成（收工扫盘会再试一次）"))
        return out
    out.update(dict(got))
    return out


def registration_after_unregistered_sign(*, store: Any, root: Any, manuscript: str,
                                         sha: str, at: str = "") -> dict[str, Any]:
    """未在册的签落地之后：把「这一份必须收录」摆到 B 面前（SGN1，永不抛）。

    ## 真机现场（`projects/lp-ball-5`，2026-11-17 17:11 只读读数）

    `statements` 0 行、`role="B"` 的台账号 0 趟、`b-register@` 板项 0 条，而
    `reports/f-proof-000002/3.md` 上各有一块成立的 V 签（签文件都在 `out/vsigns/`）。
    为什么一条义务都没有：V 签 `reports/*-proof-*.md` 时命题还没在册（业主
    2026-11-05「V 不假定有号，全签在稿上」）⇒ 走 `_issue_and_land_unregistered`
    那一支 ⇒ 那一支从来没有接过 `_registration_after_*`（改前只有"在册"那两条支路
    有），于是签落了、义务没人开、B 没人叫。

    ## 为什么号从稿名读

    未在册那一支的 `vsign.statement_id` 是空串（没有行可写），但载体名里带着裸稿号
    （`reports/f-proof-000002.md` ⇒ `000002`）—— 这与收工扫盘
    （`obligations.sweep_registrations`）同一把尺、同一组守卫（载体族 / 裸稿号 /
    `tier=family`）。这里不另立一套判据，只把"签发那一刻"接上同一条义务。
    """
    from . import manuscriptfamily as _MF
    from . import obligations as _OBL
    from . import vsigns as _VS

    out: dict[str, Any] = {"checked": False, "state": "skipped", "key": "", "item_id": "",
                           "owner": "", "owner_known": False, "code": "", "reason": "",
                           "wake": {}}
    rel = str(manuscript or "").strip().replace("\\", "/")
    if not rel:
        out.update(code="no_manuscript",
                   reason=("这一签没有手稿载体 ⇒ 这一条义务不知道要收录哪一份"
                           "（不是「已收录」）"))
        return out
    if not any(rel.startswith(prefix) for prefix in _OBL.REGISTRATION_CARRIERS):
        out.update(code="not_a_proof_carrier",
                   reason=(f"`{rel}` 不是 `reports/{{f,b}}-proof-…` 那一类载体 "
                           f"{list(_OBL.REGISTRATION_CARRIERS)} ⇒ 不在这一条义务的射程内"))
        return out
    sid = _VS.manuscript_id_of(rel)
    if not sid:
        out.update(code="no_statement_id",
                   reason=f"稿名认不出裸稿号（`{rel}`）⇒ 不猜命题号，也不开义务")
        return out
    if _MF.classify_manuscript(rel).get("tier") != _MF.TIER_FAMILY:
        out.update(code="not_a_family_carrier",
                   reason=f"`{rel}` 是历史档（tier≠family）⇒ 不可收录")
        return out
    no = as_proof_no(_VS.manuscript_proof_no_of(rel)) or 1
    return _registration_after_sign(store=store, root=root, statement_id=sid,
                                    proof_no=int(no), sha=str(sha or ""),
                                    manuscript=rel, at=str(at or ""),
                                    skip_gap=True, wake=True)


def _vsigns_write_after_flip(store: Any, *, row: Mapping[str, Any], ledger: Path,
                             statement_id: str, proof_no: int, sha: str,
                             holds: Mapping[str, Any],
                             append_ledger: bool, by: str = "",
                             manuscript: str = "",
                             submit: bool = True) -> dict[str, Any]:
    """翻位之后把签落成侧文件（「永不抛」：这一格的三态由调用方读）。

    为什么与落签拆成两步（2026-11-02 业主口径）：V 只颁发（`vsigns.issue`），
    手稿块与台账位由收方秘书落（`vsigns.land`，`by=` 只认 `secretary:F|B`）。
    本函数是 V 侧那一半的接线：颁发成功之后按 `by` 去落签；`by` 为空（直调 / 夹具 /
    V 的父角色读不到）⇒ 颁发照做（`written_by=sign_statement(direct)`），但落签会被
    受控拒绝 `not_a_secretary`，块不盖 —— 读数留在 `land` 那一格，不冒充"落成了"。

    返回 `issue` 的三态（`written` / `idempotent` / `conflict` / `archive_error` /
    `reason` / `path` / `sign` / `envelope`），外加 `land`（落签那一笔的读数）与
    `payload_problem`（组内容那一步的问题，空串 = 组得成）。
    """
    out: dict[str, Any] = {"written": False, "idempotent": False, "conflict": False,
                           "path": "", "archive_error": "", "reason": "",
                           "sign": {}, "payload_problem": "", "envelope": {},
                           "land": {}, "manuscript_write": {},
                           "submission": {},
                           "refused_below_need": False}
    from . import vsigns as _VS

    root = getattr(store, "root", "")
    if isinstance(store, (str, Path)):
        root = str(store)
    # ---- K6①：签发之前核「我读到的还是不是盘上那一版」 ---------------------------
    #
    # `sha` 是这一签的判词挂的那一版（台账行 / V 稿的 `proof_sha256`）。若盘上那份
    # 稿在 V 读完之后被改过，签 v2 就等于把 v1 的判词盖到 v2 上（lp-ball-8 的
    # 「判 c023、记 a1741」）。受控拒，一个字节都不签。
    _mc = str(manuscript or "").strip().replace("\\", "/")
    if _mc and str(sha or "").strip():
        try:
            _raw_now = (Path(root) / _mc).read_text(encoding="utf-8")
            _cur_sha = _sign_sha(str(_DS.proof_body(_raw_now)).strip("\n"))
        except (OSError, UnicodeDecodeError):
            _cur_sha = ""
        if _cur_sha and _cur_sha != str(sha or "").strip().lower():
            _reason = (f"`{_mc}` 在 V 读到的那一版之后又改过"
                       f"（读到 {str(sha)[:12]}…，盘上 {_cur_sha[:12]}…）⇒ "
                       "不签发：判词 / V 稿 / 台账行只挂读到的那一版；"
                       "请把这一份重新送审")
            out.update(checked=True, code=verifications.PROOF_CHANGED_SINCE_DISPATCH,
                       reason=_reason)
            # R9FIX 追补：门槛够了而签没发 ⇒ 盘上要有这一条（真机 lp-ball-9
            # 08:30:09 的第 4 个 3/3 clean 组就是这样：签文件不在、失败记录也没有）。
            if holds.get("streak_ok"):
                _VS.note_missed_issue(
                    root, artifact_sha=sha, manuscript=_mc,
                    streak=holds.get("streak"), need=holds.get("need") or need,
                    code=verifications.PROOF_CHANGED_SINCE_DISPATCH, reason=_reason)
            return out
    need = int(holds.get("need") or verifications.SIGN_STREAK_NEED)
    # ---- 收方秘书是谁：调用方给了就用；没给就按这一趟的父角色现读（权威来源）----
    #
    # 为什么是 `current_parent()` 而不是"猜一个 F / B"：V 的 parent 就是"谁送审"，
    # 而收方秘书只能是那一位的秘书（业主 2026-11-02：父代理 = V 的 parent）。
    # 读不到（直调 / 夹具 / 没有挂点）⇒ 空串 = 没有收方秘书 ⇒ 能颁发、不能落块。
    who = str(by or "").strip()
    if not who:
        try:
            from . import conductor as _CND

            _pid, prole = _CND.current_parent()
            who = _VS.secretary_id(prole)
        except Exception:  # noqa: BLE001 —— 读不到父角色不是失败：就是"没有收方秘书"
            who = ""
    try:
        payload = _vsign_payload(root=root, ledger=ledger, statement_id=statement_id,
                                 proof_no=proof_no, sha=sha, need=need, holds=holds,
                                 manuscript=manuscript)
    except Exception as exc:  # noqa: BLE001 —— 组内容失败要留读数，但不许带走翻位
        out["payload_problem"] = f"{type(exc).__name__}: {exc}"
        payload = {"passes": [], "objections": [], "artifact_path": "", "ledger": "",
                   "at": S.now_iso()}
    try:
        got = _VS.issue(
            root, artifact_sha=sha,
            streak=int(holds.get("streak") or 0), need=need,
            artifact_path=str(payload.get("artifact_path") or ""),
            ledger=str(payload.get("ledger") or ""),
            statement_id=str(statement_id or ""), proof_no=int(proof_no),
            passes=list(payload.get("passes") or []),
            objections=list(payload.get("objections") or []),
            at=str(payload.get("at") or ""),
            by=who,
            # VJ-07：签发者取这一签的判词行自己记的 `verifier`（实例级 actor，
            # `AgentV` 写行时就带上了）—— 不在签发处另猜一个。
            issuer=str(row.get("verifier") or ""),
            # 签成功那一刻顺手把稿置为已提交（2026-11-11 甲，复用 `mss:` 那条路）：
            # 只在真的有 store 时接线；直调 / 夹具传的是根路径 ⇒ 这一格如实报没查。
            # `submit=False` 是"调用方自己在事务外补这一笔"那一档（见 `sign_statement`）：
            # 本函数会在 `store.tx("statements")` 里被调，而提交记号要写 `tasks` ——
            # 事务里再开一笔会撞同一把 `counters` 锁（实测挂死）。
            store=(store if (submit and hasattr(store, "rows")
                             and hasattr(store, "tx")) else None))
    except Exception as exc:  # noqa: BLE001 —— 写文件那一笔抛了也要如实报
        out["reason"] = f"颁发那一笔抛了（{type(exc).__name__}: {exc}）"
        return out
    out.update({k: got.get(k) for k in ("written", "idempotent", "conflict", "path",
                                        "archive_error", "reason", "sign", "envelope",
                                        "code", "refused_below_need", "submission")})
    # R9FIX 追补：门槛够了而这一签没落地 ⇒ 落一条「该发签却没发」的记录。
    # 三档「没写成」各自会带 code/reason；`idempotent`（签早在盘上）与 `conflict`
    # （盘上那份不是这一版的签，交人看）不是"该发没发"，不记。
    if (holds.get("streak_ok")
            and not (out.get("written") or out.get("idempotent") or out.get("conflict"))):
        _VS.note_missed_issue(
            root, artifact_sha=sha, manuscript=_mc,
            streak=holds.get("streak"), need=holds.get("need") or need,
            code=str(out.get("code") or "not_written"),
            reason=str(out.get("reason") or "这一签没有落盘"))
    if got.get("written") or got.get("idempotent"):
        try:
            landed = _VS.land(
                root, artifact_sha=sha, by=who,
                manuscript_path=str(payload.get("artifact_path") or ""),
                store=None, statement_id=str(statement_id or ""),
                proof_no=int(proof_no),
                # 台账位由外层事务（`sign_statement` 的 `store.tx`）落 —— 这里再落一次
                # 就是同一格两个写者（而且会重入同一把表锁）。
                ledger_bit=False)
        except Exception as exc:  # noqa: BLE001 —— 落签抛了也要如实报（签已经颁发了）
            landed = {"landed": False, "state": "refused", "reason": (
                f"落签那一笔抛了（{type(exc).__name__}: {exc}）"), "code": "land_raised"}
        out["land"] = dict(landed or {})
        out["manuscript_write"] = dict((landed or {}).get("manuscript_write") or {})
        if not (landed or {}).get("landed"):
            out["reason"] = (f"{out['reason']}；落签没成："
                             f"{str((landed or {}).get('reason') or '没有理由')}")
    if out["payload_problem"]:
        out["reason"] = (f"{out['reason']}；组签内容时有一格没读成"
                         f"（{out['payload_problem']}）")
    return out


# 跨模块引用放在文件末尾：这些名字的实现在别的模块里，而两个模块可能互相
# 引用（顶层 `from .x import y` 在环里会在对方还没定义完时执行）。引用点
# 全部在函数体里，所以只要定义都跑完了，谁先被导入都拿得到。
from . import verifications  # 门面字典：被打桩的名字经它取
from .v_vocab import (  # noqa: F401 — 实现在 v_vocab.py
    GRADE_RECOMPUTED_KEY,
    PROOFS_KEY,
    VERIFICATIONS_DIR,
)
from .v_paths import (  # noqa: F401 — 实现在 v_paths.py
    _sign_sha,
    as_proof_no,
    proof_list,
    proof_no_of,
    proof_no_strict,
)
from .v_rowread import (  # noqa: F401 — 实现在 v_rowread.py
    bit3_payload,
)
from .v_streak import (  # noqa: F401 — 实现在 v_streak.py
    _hold_run_lengths,
    _rows_of_proof,
)
