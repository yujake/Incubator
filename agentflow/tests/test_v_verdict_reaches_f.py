# -*- coding: utf-8 -*-
"""业主 2026-10-22 晚裁定 B-3 的判据：V 的判决必须递到 F；B 杜撰的定理必须先过 V。

裁定原文（逐字照抄）：

```text
B-3 V 的判决必须递到 F（让 F 去修），否则瞎写的证明不能用；
    另外 B 侧自己杜撰定理与证明时，也必须给 V 看才能落库，否则按瞎编处理。
```

## 改前的现场（这一批要治的东西，逐条都是真机读数）

- V 的签字只在 `agent_v/core.py` 的 `review_write` 里回写；"判有毛病"只落
  `verifications/<命题号>.jsonl`；
- `agent_loop.py` 全文 0 处读 `verifications` ⇒ 运行期 D/F 看不到"V 判过、判的是有毛病"；
- 真机 `t-000026`：F 派了 V，V 逐条走查 `000000-000003`，四条全判"有毛病"
  （`unresolved_errors` 1/1/2/3），而 `statements` 仍 `status=active`、`bits.reviewed=false`、
  `grade=conjecture` —— 数据诚实，但没人看得见、没人去修；
- 收工门 R10 才把它记成 rejected，运行期零后果。

## 五条判据（每条都要求"改前红"）

| 判据 | 守什么 | 反真空 |
|---|---|---|
| 1 | F 的开场事实里读到"被 V 判有毛病的 N 条"，N=3 且逐条点名 | — |
| 2 | V 判完有毛病 ⇒ F 的收件板里出现一项判决（含命题号与步号） | 把递送 monkeypatch 掉 ⇒ 1 仍绿、2 红 |
| 3 | B 登记自产定理级（升档那一步）⇒ 拒 `self_authored_needs_v`；有成立签 ⇒ 通过 | — |
| 4 | B 登记自产猜想 ⇒ 不被这条拒（别把猜想堵死） | — |
| 5 | 把"要不要 V 签"的判定 monkeypatch 成恒通过 ⇒ 3 必红 | — |

判据 1/2 真的跑一趟 F 的循环（`run_role("F", ...)`），读的是模型真的收到的那条开场
消息与主控真的开出来的板项 —— 不靠"读源码觉得它在那儿"。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from conftest import seed_statement_row, sign_before_registration, ensure_basis_stmt

from _proof_manuscript_fixture import write_proof_manuscript

from agentflow import agent_loop as AL
from agentflow import evidencebits as EB
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.agent_b.register_statement import _RegisterStatement
from agentflow.agent_loop import run_role
from agentflow.llmseam import LlmSeam
from agentflow.store import Store

from test_agent_loop import _wired
from conftest import ensure_basis_lit
from conftest import BASIS_LIT_ID

pytestmark = pytest.mark.usefixtures("every_store_has_basis_lit")

TS = "2026-10-22T00:00:00+08:00"

#: 三条被 V 判"有毛病"的证明：每条的步号都不同（判决项里要带得出来）。
REJECTED: tuple[tuple[str, int], ...] = (("000000", 2), ("000001", 1), ("000002", 3))


# ------------------------------------------------------------------ 夹具

def _statement_row(st: Store, sid: str, *, proof: str) -> None:
    """落一条"有证明、还没被签"的命题行（`statements` 是真表，走真事务）。"""
    basis_lit = ensure_basis_lit(st)     # 先落来路行：放进下面的事务里会撞锁
    with st.tx("statements", actor="test", note="b3 fixture") as tx:
        tx.upsert("statements", {
            "stmt_id": sid, "origin": "own_result", "source_lit_id": basis_lit, "kind": "lemma",
            "label": f"探针命题 {sid}", "statement_text": f"探针 {sid}",
            "statement_full": f"探针命题 {sid}：若 n≥3 则无解。",
            "proof_text": proof, "evidence_kind": "heuristic", "status": "active",
            "quote_verified": None, "quote_reason": "夹具：还没查",
            "created_at": TS, "created_by": "test", "bits": {},
        })


def _reject(root: pathlib.Path, sid: str, *, step: int) -> str:
    """给这一条写一签"有毛病"（走 V 的那条真写入路：`verifications.record_verification`）。"""
    row = VR.record_verification(
        root, statement_id=sid, proof_text=f"1. 由定义直接得到。\n2. 易证。\n3. 显然。",
        verdict={"verdict": "有毛病", "defect_step": step,
                 "findings": [{"level": "error", "step": step, "kind": "无依据的步骤",
                               "detail": f"第 {step} 步直接用了结论"}]},
        verifier="agent-V",
        #: p247：打回只看秘书轴；夹具给 fault（不是由 V 的 verdict 字面推）。
        secretary_judge={"checked": True, "axis": "fault",
                         "decision": "有缺陷要指出", "reason": "夹具：fault",
                         "defect_step": step},
        #: fault 那一档的转达必须带洗过的文本（C 段）；否则交付侧拒绝投递。
        washed_relay={"washed": True,
                      "text": f"第 {step} 步直接用了结论：补齐之后重新送 V 重签。",
                      "findings": [{"quote": "第 2 步", "why": "没有依据"}]})
    return str(row["verification_id"])


def _rejected_workspace(tmp_path: pathlib.Path) -> tuple[Store, dict, pathlib.Path]:
    """造三条"被 V 判有毛病"的夹具（判据 1/2 共用）。"""
    st, cond, reg, gateways, root = _wired(
        tmp_path, {"F": [json.dumps({"final": "收工", "evidence": []}, ensure_ascii=False)]},
        max_steps=2)
    for sid, step in REJECTED:
        _statement_row(st, sid, proof="1. 由定义直接得到。\n2. 易证。\n3. 显然。")
        _reject(root, sid, step=step)
    return st, {"cond": cond, "reg": reg, "gateways": gateways, "root": root,
                "sid": "t-b3-verdicts"}, tmp_path


def _run_f(tmp_path: pathlib.Path, *, deliver: bool = True) -> dict:
    """跑一趟 F 的循环，返回开场消息与板项读数（判据 1/2 的唯一取数口）。

    `deliver=False` 只把"递送"那一条路换成空转（读侧一个字不动）—— 反真空就靠它：
    两条路是分开实现的，摘掉一条不该让另一条也消失。
    """
    st, ctx, _ = _rejected_workspace(tmp_path)
    original = AL.deliver_v_verdicts
    if not deliver:
        AL.deliver_v_verdicts = lambda *a, **k: {
            "checked": True, "opened": [], "existing": [], "problems": [],
            "reason": "（探针：递送被摘掉）"}
    try:
        gateway = ctx["gateways"]["F"]
        seam = LlmSeam(role="F", session_root=ctx["root"], gateway=gateway,
                       sid=ctx["sid"])
        run = run_role("F", "把 V 判过的证明补完", store=st, registry=ctx["reg"],
                       conductor=ctx["cond"], seam=seam,
                       workspace_root=str(ctx["root"]), sid=ctx["sid"], from_env=False)
    finally:
        AL.deliver_v_verdicts = original
    board = [dict(r) for r in ctx["cond"]._board_rows()
             if str(r.get("role") or "") == "F"]
    return {"prompt": gateway.prompts[0] if gateway.prompts else "",
            "systems": gateway.systems, "board": board, "run": run}


# ------------------------------------------------------------------ 判据 1

def test_1_fs_opening_facts_name_every_proof_v_rejected(tmp_path: pathlib.Path) -> None:
    """判据 1：F 的开场事实里读到"被 V 判有毛病的 N 条"，N=3 且逐条点名。

    改前红：`agent_loop` 全文 0 处读 `verifications` ⇒ 那条开场消息里一个命题号都没有。
    """
    got = _run_f(tmp_path)
    prompt = got["prompt"]
    assert prompt, "这一趟没有真的问过模型 ⇒ 开场消息读不到"
    assert "被 V 判「有毛病」的证明共 3 条" in prompt, prompt[:1200]
    for sid, step in REJECTED:
        assert f"{sid}#p1" in prompt, f"{sid} 没有被点名：{prompt[:1500]}"
        assert f"错在第 {step} 步" in prompt, f"{sid} 的步号（{step}）没读出来"
    # 反真空（另一半）：三条各自的签都点名了（不是三行同一句话）。
    for sid, _step in REJECTED:
        assert f"verifications/{sid}.jsonl" in prompt, prompt[:1500]
    # 而且它不在 system 里（跨 run 会变的事实不许进前缀）。
    assert "被 V 判「有毛病」的证明共 3 条" not in (got["systems"][0] if got["systems"] else "")


# ------------------------------------------------------------------ 判据 2

def test_2_vs_verdict_lands_on_fs_board_with_the_step_number(tmp_path: pathlib.Path) -> None:
    """判据 2：V 判完有毛病 ⇒ F 的收件板里出现一项判决（含命题号与步号）。

    反真空在同一条用例里做：把递送 monkeypatch 掉（新工作区）⇒ 判据 1 仍绿、判据 2 红
    —— 两条路是分开实现的，不是同一段读数的两种说法。
    """
    got = _run_f(tmp_path)
    items = [r for r in got["board"]
             if str(r.get("input_key") or "").startswith(AL.V_VERDICT_ITEM_PREFIX)]
    assert len(items) == 3, [(r.get("input_key"), r.get("detail")) for r in got["board"]]
    for sid, step in REJECTED:
        # 按"判决项的第一行"精确点名（不按子串：`v-000001` 里也有 `000001`）。
        wanted = f"V 判「有毛病」：{sid}#p1"
        hit = [r for r in items if wanted in str(r.get("detail") or "")]
        assert len(hit) == 1, (sid, [r.get("detail") for r in items])
        detail = str(hit[0].get("detail") or "")
        assert f"第 {step} 步" in detail, detail
        assert str(hit[0].get("kind")) == "notice", hit[0]
        assert str(hit[0].get("called_by")) == "V", hit[0]

    # ---- 反真空：把递送摘掉 ⇒ 判据 1 仍绿、判据 2 红
    fresh = tmp_path / "no_delivery"
    fresh.mkdir()
    off = _run_f(fresh, deliver=False)
    assert "被 V 判「有毛病」的证明共 3 条" in off["prompt"], (
        "把递送摘掉之后读侧也没读数了 ⇒ 两条路其实是同一条，判据 1 不独立："
        + off["prompt"][:800])
    assert not [r for r in off["board"]
                if str(r.get("input_key") or "").startswith(AL.V_VERDICT_ITEM_PREFIX)], (
        "递送被摘掉了，板上却仍然冒出判决项 ⇒ 这一条反真空没打中")


# ------------------------------------------------------------------ 判据 3/4/5（B 侧）

def _b(st: Store) -> AgentB:
    return AgentB(st, extractor=None, extract_text=None, config={})


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


#: 一条自产命题的两件式（定理内容 + 证明过程）：`doc_id` 与 `quote_reason` 是预检的硬要求。
FULL = "探针：若 n>=3 则 n^2+n 是偶数。"
PROOF = "1. n^2+n = n(n+1)。\n2. 相邻整数必有一偶，故积为偶。"


def _own(**kw) -> dict:
    base = {"statement_full": FULL, "origin": "own_result", "source_lit_id": BASIS_LIT_ID, "doc_id": "000000",
            "proof_text": PROOF, "quote_verified": False,
            "quote_reason": "自产命题：没有第二份文本可比对"}
    base.update(kw)
    return base


def _ok(out) -> dict:
    return out if isinstance(out, dict) else out.to_dict()


def _ms(st: Store, *, sid: str = "000000", proof: str = PROOF) -> str:
    """2026-11-04（业主裁定 甲 / ⑥-1-b）：要写证明正文的登记必须带手稿。

    给这一笔要写的正文落一份按号命名的稿（`## 证明` 与 `proof_text` 逐字一致、
    `## 依赖` 空表），返回工作区相对路径 —— 与 V 侧送审用的是同一份载体。
    """
    return write_proof_manuscript(st.root, sid, proof, statement_full=FULL)


def test_3_a_fabricated_theorem_needs_vs_signature(tmp_path: pathlib.Path) -> None:
    """判据 3：B 登记自产定理级 ⇒ 拒 `self_authored_needs_v`；先造成立签 ⇒ 通过。

    为什么"升档那一步"才是这一条的对象：猜想本来就要先落库才审得动（V 只审在册的命题），
    所以第一次登记的自产定理级由 B-2 的 `must_start_as_conjecture` 接管；等它按猜想立住
    之后再来声明定理级 —— 那一步欠的就是 V 的一签。
    """
    st = _ws(tmp_path)
    b = _b(st)

    # (a) 先按猜想在册（直接铺行造历史形态）
    #
    # 2026-11-02 准入闸 strict 之后，"一条在册、有证明、还没签"的猜想不能再经
    # `register_statement` 造出来（无签正文整笔拒）—— 而这一条判据测的正是
    # "在册猜想升级到定理级时要不要 V 签"。所以现场改成直接铺行（真机历史形态：
    # bits={}、没有台账、没有签）；期望值一个字没改。
    seeded = seed_statement_row(
        st, proof_text=PROOF, statement_full=FULL, statement_text=FULL,
        kind="conjecture", label="探针命题 000000", quote_verified=False,
        quote_reason="自产命题：没有第二份文本可比对",
        bits=EB.bits_of(origin="own_result", proof=True, proof_process=PROOF,
                        kind="conjecture"))
    sid = str(seeded["stmt_id"])
    assert sid

    # (b) 升档那一步、还没有 V 的签 ⇒ 拒 self_authored_needs_v
    bad = _ok(b.register_statement(**_own(kind="theorem"),
                                   proof_manuscript=_ms(st, sid=sid)))
    assert bad.get("ok") is False, bad
    assert bad.get("kind") == "self_authored_needs_v", bad
    err = str(bad.get("error") or "")
    # 2026-11-10（D1，`4273a273`）：B-3 这一句拒信的口径换了 —— 登记不再顺手落稿，
    # 所以改法不是"换个 kind 按 conjecture 再交一次"（那一版正文根本没在盘上），
    # 而是「显式落稿 → 派 V 审 → 签块由收方秘书落回稿 → 带这份稿重交」。
    # 两个方向一起钉：新话在（显式落稿 / verify_proof / 重交）+ 旧话不在（conjecture）。
    assert "显式落稿" in err and "verify_proof" in err, err
    assert "再带这份稿重交" in err, err
    assert "conjecture" not in err, (
        "B-3 的拒信又回到「换个 kind 按 conjecture 再交一次」的旧口径 "
        "⇒ 那一句在 D1 之后是错的（正文没落盘，换 kind 交不上去）：" + err)
    rows = [dict(r) for r in st.rows("statements")]
    assert len(rows) == 1 and str(rows[0].get("kind")) == "conjecture", rows

    # (c) 造一份"成立"签（走 V 的真写入路）⇒ 同一笔再交一次、kind 改回定理级 ⇒ 通过
    #
    # 业主 2026-10-29 定稿：同一份证明、同一版正文（同 `proof_sha256`）要连续 3 次给出
    # 「成立」且秘书判定通过，才轮到 V 的秘书落签（`verifications.sign_statement`）；
    # 第 1、2 次只落台账、第 3 位不翻。所以这里先断"1 次不签"（新规矩的正控），
    # 再把次数凑够 —— `signs_bit3` 只认"够次数"的那一签，所以连续读数要一起递进去。
    sign = VR.record_verification(
        st.root, statement_id=sid, proof_text=PROOF,
        verdict={"verdict": "成立", "findings": []}, verifier="agent-V",
        secretary_judge={"checked": True, "axis": "clean",
                         "decision": "没问题", "reason": "夹具：clean"})
    holds1 = VR.consecutive_holds(st.root, sid)
    assert holds1["checked"] is True and int(holds1["streak"]) == 1, holds1
    assert VR.signs_bit3(sign, streak=holds1) is False, (
        "签 1 次就签住了第 3 位 ⇒ 2026-10-29 的连续 3 次口径没生效", holds1)
    sign = VR.record_verification(
        st.root, statement_id=sid, proof_text=PROOF,
        verdict={"verdict": "成立", "findings": []}, verifier="agent-V",
        secretary_judge={"checked": True, "axis": "clean",
                         "decision": "没问题", "reason": "夹具：clean"})
    sign = VR.record_verification(
        st.root, statement_id=sid, proof_text=PROOF,
        verdict={"verdict": "成立", "findings": []}, verifier="agent-V",
        secretary_judge={"checked": True, "axis": "clean",
                         "decision": "没问题", "reason": "夹具：clean"})
    holds3 = VR.consecutive_holds(st.root, sid)
    assert int(holds3["streak"]) == VR.SIGN_STREAK_NEED and holds3["streak_ok"] is True, holds3
    assert sign["verdict"] == "成立" and VR.signs_bit3(sign, streak=holds3), sign
    good = _ok(b.register_statement(**_own(kind="theorem", evidence_kind="proof_review"),
                                    proof_manuscript=_ms(st, sid=sid)))
    assert good.get("ok") is True, good
    reading = dict(good.get("self_authored_review") or {})
    assert reading.get("needs_v") is True and reading.get("signed") is True, reading
    assert reading.get("verification_id") == sign["verification_id"], reading


def test_4_a_conjecture_is_still_registrable_without_v(tmp_path: pathlib.Path) -> None:
    """判据 4（正控）：B 登记自产猜想 ⇒ 不被这条拒（别把猜想堵死）。"""
    st = _ws(tmp_path)
    # 准入闸（2026-11-02 默认 strict）：正文先要有签（先签后登记）。这条正控问的是
    # "猜想不被 `self_authored_needs_v` 拒"，不是"可以无签入册"。
    sign_before_registration(st.root, proof_text=PROOF)
    got = _ok(_b(st).register_statement(**_own(kind="conjecture"),
                                        proof_manuscript=_ms(st)))
    assert got.get("ok") is True, got
    assert got.get("kind") != "self_authored_needs_v", got
    reading = dict(got.get("self_authored_review") or {})
    assert reading.get("needs_v") is False, reading
    assert "conjecture" in str(reading.get("why") or ""), reading
    rows = st.rows("statements")
    assert len(rows) == 1 and str(rows[0].get("kind")) == "conjecture", rows


def test_5_forcing_the_signature_lookup_open_makes_criterion_3_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 5（反真空）：把"要不要 V 签"的判定 monkeypatch 成恒通过 ⇒ 判据 3 必红。

    "要不要 V 签的判定"的唯一实现是 `_v_signature_for`（它读 V 的台账）。把它换成一个
    恒回"签过了"的替身之后，判据 3 的那一笔（没有签）就会落到更后面那一档 —— 于是判据 3
    的"拒 self_authored_needs_v"必红。这条反真空证明判据 3 读的是那一份判定，不是
    "反正拒了"。

    2026-11-08（缺陷③，`c94a8e8f`）之后"更后面那一档"的形状变了：收录回执
    （`proof_no` / `proof_sha256`）是"只要这一行真有正文就写"的一格，它进了写盘判据
    ⇒ 这一笔 `ok=true` + `new_row=false`，不再落到 `duplicate_statement` 那一档。
    真正挡住升档的是写入期闸读到的那一份盘上台账（放开的只是一份判定，不是那一行）：
    盘上 `kind` 停在 `conjecture`、没有 `_kind_upgrade`，回执自己写着"还差 V 的一签"。
    所以判据钉这三格，不钉那个拒码 —— 拒码只证明"有人拒了"，这三格证明
    "拒了之后那一行仍然不是定理"。
    """
    st = _ws(tmp_path)
    b = _b(st)
    # 在册那一行直接铺（历史形态：没有签）—— 见判据 3 那一段的理由。
    seeded = seed_statement_row(
        st, proof_text=PROOF, statement_full=FULL, statement_text=FULL,
        kind="conjecture", label="探针命题 000000", quote_verified=False,
        quote_reason="自产命题：没有第二份文本可比对",
        bits=EB.bits_of(origin="own_result", proof=True, proof_process=PROOF,
                        kind="conjecture"))
    first = {"ok": True, "stmt_id": str(seeded["stmt_id"])}
    assert first.get("ok") is True, first

    # 正控（没打补丁）：判据 3 的那一笔就在这一格被拒。
    plain = _ok(b.register_statement(**_own(kind="theorem", evidence_kind="proof_review"),
                                     proof_manuscript=_ms(st, sid=str(first.get("stmt_id")))))
    assert plain.get("kind") == "self_authored_needs_v", plain

    def _always_signed(self, *, statement_full: str, proof_text: str,
                       manuscript_text: str = "", manuscript_path: str = "") -> dict:
        # 2026-11-04（甲）：真判定多了 `manuscript_path` 一格（签要认载体）；
        # 打桩只回答"签过了没有"，那一格照收不用。
        return {"checked": True, "signed": True, "in_ledger": True,
                "stmt_id": str(first.get("stmt_id") or ""),
                "verification_id": "v-999999", "proof_sha256": "",
                "why": "（探针：恒回签过了）"}

    monkeypatch.setattr(_RegisterStatement, "_v_signature_for", _always_signed)
    forced = _ok(b.register_statement(**_own(kind="theorem", evidence_kind="proof_review"),
                                      proof_manuscript=_ms(st, sid=str(first.get("stmt_id")))))
    # 判据 3 的断言是"拒收 `self_authored_needs_v`"。把那一份判定换成恒通过之后，
    # 这一格不再由它来拒（改由更后面的一级说话）⇒ 判据 3 必红。
    assert forced.get("kind") != "self_authored_needs_v", (
        "'要不要 V 签'的判定已经换成恒通过，这一笔却仍然报 self_authored_needs_v ⇒ "
        "判据 3 的牙不在那一份判定上（它可能是被别的东西顺手拦下的）：" + str(forced))
    # 闸放开之后这一笔落成什么（见 docstring 末段）：没有新建行，盘上名字没升，
    # 回执逐字说还差什么 —— 挡它的是写入期闸读到的那一份盘上台账。
    assert forced.get("new_row") is False, (
        "闸放开之后这一笔既没有落成「在册那一档」、也没有给出读数 ⇒ 这个反真空没打中："
        + str(forced))
    landed = next((dict(r) for r in st.rows("statements")
                   if str(r.get("stmt_id") or "") == str(first.get("stmt_id"))), {})
    assert str(landed.get("kind") or "") == "conjecture", (
        "闸放开之后盘上的名字跟着升成定理了 ⇒ 判据 3 的牙不在那一份判定上：" + str(landed))
    assert not landed.get("_kind_upgrade"), landed
    assert "V 的一签" in str(forced.get("note") or ""), forced
