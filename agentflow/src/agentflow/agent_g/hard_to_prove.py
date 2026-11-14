# -*- coding: utf-8 -*-
"""难以自证的命题在论文里的形态（业主 2026-11-13 裁定）。

## 业主原话（逐字）

「G 侧写论文时要读得懂：已优化 + 引文占位 V 签代表着难以自证，对这类命题需在论文中持保守态度。
若该命题承重，需报告要仔细研究，不敢落成文。」

## 这条纪律读的是哪一个标记

不读"已优化 + 引文占位签"这个组合 —— 业主 2026-11-13 更正：那个组合是刚被否决的形态，
拿它反推"难以自证"会把两条独立的读数折成一条推断。只读命题行上那个显式的第四档标记：

- `bits.evidence.hard_to_prove_by_proof[<证明号>]`（`evidencebits.HARD_TO_PROVE_KEY`）；
- 读侧的折档口 `evidencebits.optimized_state(row, 证明号) == "hard_to_prove"`。

唯一读口是 :func:`hard_to_prove_paths`。判据把 `evidencebits.hard_to_prove_by_proof`
打桩成空表，这一整组语义必须消失（反真空①）—— 打桩得到的绿说明它读的是标记本身，
而不是"看起来像优化过又没真签"的组合推断。

## 两种处置

- 辅助断言（不是本文承重的那一条）⇒ 改写为保守形态（:func:`conservative_claim`）：
  证据档位降到 `heuristic`、`status` 那一格摘掉（不再声称"证"）、正文前面加
  「引文所述，未经独立复核」、`our_check` 写成「只读了陈述」、`source_kind` 写成「文献」。
  于是 `doc_tools.wording_ceiling()` 不再允许「定理 / 证明」这类措辞
  （`claimanatomy.validate_claim` 的过度声称那条闸）—— 保守不是靠自觉写的，是靠结构卡住的。
- 承重断言（本文靠它站着的那一条）⇒ 不进正文（从 `claims` 里摘掉，原因写进
  `open_problems`），并发一条 message 给召唤者：「这条承重、需仔细研究，因此不落成文」
  （:func:`report_held_back`）。不走 `conductor.escalate`：那条通道会以
  `stop_reason=escalated` 收工，而业主要的是同一趟里把话带到（`message` 通道，
  落在同一个收件箱里、不停这一趟）。

## 承重不设阈值

:func:`is_load_bearing` 判的是"这条断言在这篇论文里是什么角色"，不是数一数、比一比：
辅助件（定义 / 例 / 注 / 反例）不是承重；被降级成 `Remark only` / `移入 open` 的不是本文的结论；
作废的不在正文。其余按结果型断言读（定理 / 命题 / 引理 / 推论 —— 包括没登记 `kind` 的行：
"没写类型"不等于"辅助"，三态纪律）。这条判据可被单独打桩（反真空②）。

## 这一组落在哪两个入口

`build_document` 与 `revise` 都调 :func:`settle_claims`（同一个实现）：写稿与改稿是同一条
纪律的两个入口，只接一个等于给另一个留后门（本仓反复踩过的那一形态）。
"""
from __future__ import annotations

from ._support import Any, DT, DocumentError, Mapping, Path, Sequence
from .. import claimanatomy as CA
from .. import evidencebits as EB

#: 保守形态正文前那一句。与 `doc_tools.CROSS_CHECK_DISCLAIMER` /
#: `PROOF_REVIEW_DISCLAIMER` 同族、同体裁：读者在正文旁边就看到"这一条凭什么"。
#: 业主原话是「引文所述、未经独立复核」，这里按现有标点体裁写成一句。
HARD_TO_PROVE_CLAUSE = "引文所述，未经独立复核"

#: 保守形态落到的证据档位。为什么是 `heuristic`：`evidencebits.bits_of` 对"引用来的命题"
#: 给的等级上限就是猜想（反算档位 = `heuristic`），而"引文没给完整严密的证明"正是同一件事。
#: 它同时是 `wording_ceiling()` 之外的那一档 —— 于是「已证明 / 定理成立」这类措辞
#: 在这条断言上结构性地写不进去。
HARD_TO_PROVE_EVIDENCE_KIND = "heuristic"

#: `source_kind` 的取值（词表在 `schema.CLAIM_SOURCE_KINDS`）：这条断言来自文献。
HARD_TO_PROVE_SOURCE_KIND = "文献"

#: `our_check` 的取值（词表在 `schema.CLAIM_CHECK_KINDS`）：我方只读了陈述。
#: 中间那一档刻意不叫"验证"：这一格回答"我们做了什么"，不是"结论有多可信"。
HARD_TO_PROVE_OUR_CHECK = "只读了陈述"

#: 辅助件的类型（`schema.CLAIM_KINDS` 里那四类）：它们不是本文的结论，是引子 / 例子 / 旁注。
AUXILIARY_CLAIM_KINDS: tuple[str, ...] = ("定义", "例", "注", "反例")

#: 被降级的可用范围：这两档东西明确不是本文的结论（`schema.ALLOWED_USE_KINDS`）。
DOWNGRADED_ALLOWED_USE: tuple[str, ...] = ("Remark only", "移入 open")

#: 作者显式声明的主结果（`schema.ALLOWED_USE_KINDS` 的第一档）：这一格写着它，
#: 就不看 `kind` 了 —— 作者已经自己说了"这是本文的结论"，机器不该替他降回辅助。
MAIN_RESULT_ALLOWED_USE = "主结果"

#: 撤销那一档（`claimanatomy.is_retracted` 的同一格）。
RETRACTED_CLAIM_STATUS = "作废"

#: 上报留言的标题前缀（机器可识别：测试与审计按它捞，与 D 的交付汇报同一种做法）。
REPORT_SUBJECT = "G 写作报告：承重命题难以自证，未落成文"

#: 上报正文必须出现的那句人话（业主原话「需仔细研究」）。
RESEARCH_NEEDED = "需仔细研究"


def hard_to_prove_paths(row: Mapping[str, Any]) -> dict[int, dict[str, str]]:
    """这一行命题上「难以自证」的逐路径标记：`{证明号: {basis, at}}`（唯一读口）。

    两处都读、以标记为准：先读显式标记 `bits.evidence.hard_to_prove_by_proof`，
    再拿 `evidencebits.optimized_state` 的第四档对一遍 —— 后者是优化栏的读侧折档口，
    它把这一格折成 `state="hard_to_prove"`（并且盖住手写行里与 `optimized=true` 并存的那一档）。
    两处都不认的条目不当结论：那说明写口被手改坏了，读侧不该替它下判断。

    号认不出 / 没记过 ⇒ 空字典（三态：不记过不是"记成没有"，只是这一份没有结论）。
    """
    marked = EB.hard_to_prove_by_proof(row)
    if not marked:
        return {}
    out: dict[int, dict[str, str]] = {}
    for raw_no, entry in marked.items():
        if EB.optimized_state(row, raw_no) != "hard_to_prove":
            continue
        out[int(raw_no)] = dict(entry)
    return out


def cited_statement_ids(claim: Mapping[str, Any]) -> list[str]:
    """一条断言引到的命题号（只认 `stmt:` 前缀；`#` 之后的锚点不参与）。"""
    out: list[str] = []
    for raw in (claim.get("citations") or []):
        prefix, ident = DT.citation_ref_parts(raw)
        if prefix == "stmt" and ident and ident not in out:
            out.append(ident)
    return out


def is_load_bearing(claim: Mapping[str, Any]) -> bool:
    """这条断言是不是本文的承重结论（主结果），还是辅助 —— 语义判定，不设阈值。

    ## 判什么

    "承重"在这里是它在论证里的角色：读者读完要记住、正文靠它站着的那一条。所以：

    - 辅助件不是承重：`kind` 是定义 / 例 / 注 / 反例（`AUXILIARY_CLAIM_KINDS`）——
      它们是引子、例子、旁注，删掉它们论文的结论不塌；
    - 被降级的不是本文的结论：`allowed_use` 是 `Remark only` / `移入 open`
      （`DOWNGRADED_ALLOWED_USE`）—— 前者是按证据档位自动降下来的（`cross_check` 的
      断言由 `compose_claim` 自动标成 `Remark only`），后者是"这属于开放问题"；
    - 作者显式标了 `allowed_use="主结果"` 的按承重读（他自己说了这是本文的结论，
      就不看 `kind` 了 —— 机器不替他降回辅助）；
    - 作废的不在正文（`status="作废"`），也就谈不上承重。

    其余一律按结果型断言读（定理 / 命题 / 引理 / 推论）。`kind` 没登记的行也按结果型读：
    "没写类型"与"辅助"是两件事，把前者折成后者等于用"没登记"给承重结论开一条降级路。

    ## 为什么这不是阈值

    它读的是断言自己声明的角色（类型 + 可用范围 + 生命周期），不是任何计数或长度。
    数一数、比一比（"主结果区超过 N 条"之类）会把"哪一条是本文的结论"变成规模问题，
    而那是作者写下的判断，不是能靠数字估出来的东西。
    """
    if not isinstance(claim, Mapping):
        return False
    if str(claim.get("status") or "").strip() == RETRACTED_CLAIM_STATUS:
        return False
    use = str(claim.get("allowed_use") or "").strip()
    if use in DOWNGRADED_ALLOWED_USE:
        return False
    if use == MAIN_RESULT_ALLOWED_USE:
        return True
    kind = str(claim.get("kind") or "").strip()
    return kind not in AUXILIARY_CLAIM_KINDS


def conservative_text(text: str, *, statement_text: str = "") -> str:
    """保守形态的正文：`引文所述，未经独立复核：<那句话>`。

    ## 为什么要换掉带过度声称措辞的那一句

    证据档位降到 `heuristic` 之后，`claimanatomy` 会把「已证明 / 定理成立 / 由此得证」
    这类措辞判成 `overclaim`（error）—— 那是这条断言落库时会被拒的形态。所以：

    - 原话里没有这些措辞 ⇒ 原样保留，只在前面加上那一句归属（保住作者的叙述）；
    - 原话有这些措辞 ⇒ 用命题台账里那一句原文代替（`statement_text`）。
      作者那句"已证明"的力度是假的（引文没给完整证明），换成"命题原文"是唯一
      既不撒谎、也不替作者改数学内容的形态。

    两句都带过度声称措辞 ⇒ 受控拒（`DocumentError`）：这一条命题没有可写的保守形态，
    不拿一个假的正文去凑。
    """
    said = str(text or "").strip()
    if _has_overclaim(said):
        said = str(statement_text or "").strip()
    if _has_overclaim(said):
        raise DocumentError(
            "难以自证的命题在台账里的原文本身就带着过度声称措辞（"
            f"「{_overclaim_hit(said)}」）⇒ 写不出保守形态："
            "请先让那条命题的登记文字带上「引文所述、未经独立复核」的归属，再回来写论文"
        )
    if not said:
        return HARD_TO_PROVE_CLAUSE
    if said.startswith(HARD_TO_PROVE_CLAUSE):
        return said
    return f"{HARD_TO_PROVE_CLAUSE}：{said}"


def conservative_claim(
    claim: Mapping[str, Any],
    *,
    statement_text: str = "",
    basis: str = "",
    statement_id: str = "",
) -> dict:
    """把一条辅助断言改写成保守形态（返回新的 dict，不改入参）。

    改写面（逐格）：

    - `evidence_kind` ⇒ `heuristic`（`wording_ceiling` 之外那一档，定理措辞写不进去）；
    - `status` ⇒ 摘掉（"证 / 验"是生命周期声明；这一条不声称"证"。摘掉不是写"待精化"——
      三态：没提这件事与明确说了没有必须分得开）；
    - `proof_location` ⇒ 摘掉（那个位置是我方证明的落点，这一条没有我方证明）；
    - `text` ⇒ `引文所述，未经独立复核：…`（见 :func:`conservative_text`）；
    - `scope_caveat` ⇒ 并入那一句归属 + 依据（原文已有的话保留）；
    - `source_kind` ⇒ `文献`、`our_check` ⇒ `只读了陈述`、`our_check_note` ⇒ 依据；
    - `disclaimer` ⇒ 保留（它说的是一句真话），但不再由这一档强制。

    不动的格：`claim_id` / `section` / `citations` / `kind` / `allowed_use` / 数字证据 /
    反例 / 勘误。`kind` 刻意不降：引文里的一条定理仍然可以按定理引用，被去掉的是
    "已证"这个力度，不是它的数学身份。
    """
    out = dict(claim)
    before = CA.claim_statement(out)
    out["evidence_kind"] = HARD_TO_PROVE_EVIDENCE_KIND
    out.pop("status", None)
    out.pop("proof_location", None)
    out["source_kind"] = HARD_TO_PROVE_SOURCE_KIND
    out["our_check"] = HARD_TO_PROVE_OUR_CHECK
    note = HARD_TO_PROVE_CLAUSE
    if statement_id:
        note += f"（命题 stmt:{statement_id}"
        note += f"；依据：{_one_line(basis)}）" if str(basis or "").strip() else "）"
    out["our_check_note"] = note
    caveat = str(out.get("scope_caveat") or "").strip()
    out["scope_caveat"] = note if not caveat else f"{note}；{caveat}"
    out["text"] = conservative_text(before, statement_text=statement_text)
    return out


def settle_claims(
    rows_of: Any,
    claims: Sequence[Mapping[str, Any]],
) -> dict:
    """按「难以自证」把候选断言过一遍（`build_document` 与 `revise` 共用的唯一实现）。

    `rows_of(table)` 是读表口（`store.rows` / 事务内的 `tx.rows`）：两处看到的是同一份快照。

    返回四组：

    - `claims`：可以落正文的断言（辅助条目已改写成保守形态、承重条目已摘掉）；
    - `held_back`：承重的那几条（逐条带 `index` / `claim_id` / `statement_ids` / 依据）；
    - `attributed`：被改写成保守形态的那几条（逐条带 `text_before` —— 改前的原话，
      不许因为改了就丢掉"作者原来写了什么"）；
    - `readings`：这一趟的读数（`checked` 三态、逐条点名、两个计数）；
    - `open_problems`：要补进稿件开放问题区的那几句（"为什么这条没写进来"）。

    读数里的 `index` 是「候选清单里」的 1 起序号：`build_document` 那条路会把
    `claim_id` 重排成 `claim-1…claim-N`（`doc_tools.normalize_claims` 的口径），
    所以拿进来时那个代号在落库之后对不上；`index` 与 `statement_ids` 是对得上的那两个。

    读不到 `statements` 时「不做任何改写」、`readings["checked"]=False` 并写明为什么：
    这时"这一条是不是难以自证"没有答案，按"所有命题都保守"处理正是业主否决过的泛化。
    （实际路径上读不到台账也过不了 `check_citations` 那一关，所以这里不是一条静默放行。）
    """
    rows = [dict(c) if isinstance(c, Mapping) else c for c in (claims or [])]
    readings: dict[str, Any] = {
        "checked": False, "why": "", "rows": [], "held_back": [], "attributed": [],
    }
    try:
        statements = {str(r.get("stmt_id") or ""): r for r in rows_of("statements")}
    except Exception as exc:  # noqa: BLE001 —— 读不到要说出来，但不据此改写（见 docstring）
        readings["why"] = f"statements 读不出来（{type(exc).__name__}: {exc}）"
        return {"claims": rows, "held_back": [], "attributed": [],
                "readings": readings, "open_problems": []}
    readings["checked"] = True

    kept: list[dict] = []
    held_back: list[dict] = []
    attributed: list[dict] = []
    open_problems: list[str] = []
    for index, claim in enumerate(rows, 1):
        if not isinstance(claim, Mapping):
            kept.append(claim)
            continue
        claim = dict(claim)
        if str(claim.get("status") or "").strip() == RETRACTED_CLAIM_STATUS:
            kept.append(claim)          # 撤销的条目归渲染层附录管，这里一个字都不动
            continue
        found: dict[str, dict[int, dict[str, str]]] = {}
        for sid in cited_statement_ids(claim):
            row = statements.get(sid)
            if row is None:
                continue
            paths = hard_to_prove_paths(row)
            if paths:
                found[sid] = paths
        if not found:
            kept.append(claim)
            continue
        cid = str(claim.get("claim_id") or "")
        reading = _reading_row(claim, found, cid=cid, index=index)
        if is_load_bearing(claim):
            reading["action"] = "held_back"
            readings["rows"].append(reading)
            readings["held_back"].append(cid or reading["index"])
            held_back.append(reading)
            open_problems.append(_held_back_line(reading))
            continue
        primary = sorted(found)[0]
        # 依据取第一份证明的那一条（`basis` 是台账上那句可复核的话；多路径时逐条都在读数里）
        basis = next(iter(sorted(found[primary].items())))[1].get("basis", "")
        fixed = conservative_claim(
            claim,
            statement_text=str(statements[primary].get("statement_text")
                               or statements[primary].get("statement_full") or ""),
            basis=str(basis or ""), statement_id=primary,
        )
        reading.update(action="attributed", text_before=CA.claim_statement(claim),
                       text_after=CA.claim_statement(fixed))
        readings["rows"].append(reading)
        readings["attributed"].append(cid or reading["index"])
        attributed.append(reading)
        kept.append(fixed)
    return {"claims": kept, "held_back": held_back, "attributed": attributed,
            "readings": readings, "open_problems": open_problems}


def _reading_row(claim: Mapping[str, Any], found: Mapping[str, Mapping[int, Mapping[str, str]]],
                 *, cid: str, index: int) -> dict:
    """一条「难以自证」读数的逐条形状（位置 / 断言 / 命题 / 路径 / 依据）。"""
    paths: list[dict[str, Any]] = []
    for sid in sorted(found):
        for no in sorted(found[sid]):
            entry = found[sid][no]
            paths.append({"statement_id": sid, "proof_no": int(no),
                          "basis": str(entry.get("basis") or ""),
                          "at": str(entry.get("at") or "")})
    return {
        "index": int(index),
        "claim_id": cid,
        "statement_ids": sorted(found),
        "paths": paths,
        "kind": str(claim.get("kind") or ""),
        "evidence_kind": str(claim.get("evidence_kind") or ""),
        "load_bearing": bool(is_load_bearing(claim)),
    }


def _held_back_line(reading: Mapping[str, Any]) -> str:
    """承重条目在「开放问题」区里那一条（读者看得见"它为什么不在正文"）。

    刻意不写"已报告召唤者"：上报成没成只有 `report_held_back` 的返回值知道，
    而这段文字会落在稿件正文里 —— 把没发出去的留言写成"已报告"是第二种谎。
    """
    sids = "、".join(f"stmt:{x}" for x in (reading.get("statement_ids") or []))
    return (f"承重断言（第 {reading.get('index')} 条，引 {sids}）所依据的命题被记为"
            f"「难以自证」：{RESEARCH_NEEDED}，因此不落成文。")


def report_held_back(store: Any, settled: Mapping[str, Any], *, kind: str = "") -> dict:
    """把承重的那几条写进召唤者的收件箱（`message` 通道；不停这一趟）。

    三态：没查成（`readings.checked=False`）⇒ `checked=False` 且说清为什么；
    没有承重条目 ⇒ `checked=True`、`sent=False` 且 `why` 说清"没有要报的"（不是"报失败了"）；
    判不出召唤者 / 消息通道不可用 / 写盘失败 ⇒ `sent=False` 且 `why` 带原因。
    "没报成"绝不许被写成"报过了"（与 D 的交付汇报同一条纪律）。
    """
    checked = bool((settled.get("readings") or {}).get("checked"))
    if not checked:
        return {"checked": False, "sent": False, "to": "", "msg_id": "",
                "why": "命题台账没读成 ⇒ 这一趟有没有承重要报，没有结论（不是「没有」）"}
    rows = [r for r in (settled.get("held_back") or []) if isinstance(r, Mapping)]
    if not rows:
        return {"checked": True, "sent": False, "to": "", "msg_id": "",
                "why": "这一趟没有承重条目需要上报"}
    to_role, session_root, sid, why = _parent_inbox(store)
    if not to_role:
        return {"checked": False, "sent": False, "to": "", "msg_id": "", "why": why}
    body = _report_body(rows, kind=kind)
    try:
        from ..agent_loop import send_message
    except Exception as exc:  # noqa: BLE001 —— 通道不可用要如实记，不许静默
        return {"checked": True, "sent": False, "to": to_role, "msg_id": "",
                "why": f"消息通道不可用（{type(exc).__name__}: {exc}）⇒ 这一条没发出"}
    msg_id, problem = send_message(
        session_root, sender="G", to=to_role, subject=REPORT_SUBJECT, body=body,
        sid=str(sid or "") or None, by_framework=True,
    )
    return {"checked": True, "sent": bool(msg_id) and not problem, "to": to_role,
            "msg_id": str(msg_id or ""), "session_root": str(session_root),
            "sid": str(sid or ""), "why": str(problem or "")}


def _report_body(rows: Sequence[Mapping[str, Any]], *, kind: str = "") -> str:
    """上报正文：逐条写清断言 / 命题 / 依据，并给出那句"需仔细研究"的处置。"""
    lines = [
        f"G 在写稿（{kind or '稿件'}）时把 {len(rows)} 条承重断言留在了正文之外。",
        "",
        "原因：这些断言所依据的命题在命题台账上被记为「难以自证」"
        f"（`bits.evidence.hard_to_prove_by_proof`，优化栏第四档）。"
        f"{RESEARCH_NEEDED}：把那条命题的证明补齐或改写、拿到真 V 签，再回来写。"
        "在此之前它们不落成文 —— 一条承重结论写成『已证定理』而它证不出来，"
        "整篇论文的结论就都靠不住了。",
        "",
    ]
    for r in rows:
        lines.append(f"- 第 {r.get('index')} 条断言（类型 {r.get('kind') or '未登记'}）")
        for p in (r.get("paths") or []):
            lines.append(
                f"  - 引文命题 stmt:{p.get('statement_id')} 的证明 #{p.get('proof_no')}："
                f"{str(p.get('basis') or '（没写依据）')[:200]}"
                + (f"（记于 {p.get('at')}）" if p.get("at") else ""))
    lines.append("")
    lines.append("处置：这 {n} 条已从这份稿的正文里摘掉，原因写进稿件的开放问题区。"
                 .format(n=len(rows)))
    return "\n".join(lines)


def _parent_inbox(store: Any) -> tuple[str, Path, str, str]:
    """这一趟的召唤者与该落的会话：`(角色, 会话根, sid, 判不出的原因)`。

    先读运行期挂点（`conductor.current_parent` / `current_session`）：那是循环解析出来的
    那一个父，比台账更接近现场。没有挂点时退回 `tasks` 台账的 `called_by`
    （与 `agent_d.write_report._parent_of_this_summon` 同一条读法）。
    """
    try:
        from ..conductor import current_parent, current_session, current_task_id
    except Exception as exc:  # noqa: BLE001 —— 没有挂点 ⇒ 判不出父是谁（不猜收件人）
        return "", Path(str(store.root)), "", f"读不到召唤者挂点（{type(exc).__name__}: {exc}）"
    _tid, parent_role = current_parent()
    session_root, sid = current_session()
    role = str(parent_role or "")
    if not role:
        task_id = str(current_task_id() or "")
        row = next((r for r in store.rows("tasks")
                    if str(r.get("task_id")) == task_id), None) if task_id else None
        called_by = str((row or {}).get("called_by") or "")
        if called_by and called_by not in ("user", "用户"):
            role = called_by
    if not role:
        return "", Path(str(store.root)), "", (
            "判不出召唤者是谁（这一趟不在 summon 上下文里、tasks 台账也没有这一行的 called_by）"
            "⇒ 这条上报没发（不发进一个没人读的收件箱）")
    root = Path(session_root) if str(session_root or "") else Path(str(store.root))
    return role, root, str(sid or ""), ""


def _has_overclaim(text: str) -> bool:
    """这句话里有没有「已证明 / 定理成立」这类措辞（词表在 `doc_tools.OVERCLAIM_MARKERS`）。"""
    return bool(_overclaim_hit(text))


def _overclaim_hit(text: str) -> str:
    """命中的那一个过度声称措辞（空串 = 没命中）。"""
    return next((m for m in DT.OVERCLAIM_MARKERS if m in str(text or "")), "")


def _one_line(text: Any, width: int = 160) -> str:
    """单行化 + 截断（与 `doc_tools._one_line` 同一体裁，读数是给人看的）。"""
    s = " ".join(str(text or "").split())
    return s if len(s) <= width else s[: width - 1] + "…"
