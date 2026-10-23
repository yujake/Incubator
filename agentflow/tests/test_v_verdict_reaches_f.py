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

from agentflow import agent_loop as AL
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.agent_b.register_statement import _RegisterStatement
from agentflow.agent_loop import run_role
from agentflow.llmseam import LlmSeam
from agentflow.store import Store

from test_agent_loop import _wired

TS = "2026-10-22T00:00:00+08:00"

#: 三条被 V 判"有毛病"的证明：每条的步号都不同（判决项里要带得出来）。
REJECTED: tuple[tuple[str, int], ...] = (("000000", 2), ("000001", 1), ("000002", 3))


# ------------------------------------------------------------------ 夹具

def _statement_row(st: Store, sid: str, *, proof: str) -> None:
    """落一条"有证明、还没被签"的命题行（`statements` 是真表，走真事务）。"""
    with st.tx("statements", actor="test", note="b3 fixture") as tx:
        tx.upsert("statements", {
            "stmt_id": sid, "origin": "own_result", "kind": "lemma",
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
        verifier="agent-V")
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
    base = {"statement_full": FULL, "origin": "own_result", "doc_id": "000000",
            "proof_text": PROOF, "quote_verified": False,
            "quote_reason": "自产命题：没有第二份文本可比对"}
    base.update(kw)
    return base


def _ok(out) -> dict:
    return out if isinstance(out, dict) else out.to_dict()


def test_3_a_fabricated_theorem_needs_vs_signature(tmp_path: pathlib.Path) -> None:
    """判据 3：B 登记自产定理级 ⇒ 拒 `self_authored_needs_v`；先造成立签 ⇒ 通过。

    为什么"升档那一步"才是这一条的对象：猜想本来就要先落库才审得动（V 只审在册的命题），
    所以第一次登记的自产定理级由 B-2 的 `must_start_as_conjecture` 接管；等它按猜想立住
    之后再来声明定理级 —— 那一步欠的就是 V 的一签。
    """
    st = _ws(tmp_path)
    b = _b(st)

    # (a) 先按猜想登记：不被这条闸拦（它是猜想，本来就要先落库才审得动）
    first = _ok(b.register_statement(**_own(kind="conjecture")))
    assert first.get("ok") is True, first
    sid = str(first.get("stmt_id") or "")
    assert sid

    # (b) 升档那一步、还没有 V 的签 ⇒ 拒 self_authored_needs_v
    bad = _ok(b.register_statement(**_own(kind="theorem")))
    assert bad.get("ok") is False, bad
    assert bad.get("kind") == "self_authored_needs_v", bad
    err = str(bad.get("error") or "")
    assert "conjecture" in err and "verify_proof" in err, err
    rows = [dict(r) for r in st.rows("statements")]
    assert len(rows) == 1 and str(rows[0].get("kind")) == "conjecture", rows

    # (c) 造一份"成立"签（走 V 的真写入路）⇒ 同一笔再交一次、kind 改回定理级 ⇒ 通过
    sign = VR.record_verification(
        st.root, statement_id=sid, proof_text=PROOF,
        verdict={"verdict": "成立", "findings": []}, verifier="agent-V")
    assert sign["verdict"] == "成立" and VR.signs_bit3(sign), sign
    good = _ok(b.register_statement(**_own(kind="theorem", evidence_kind="proof_review")))
    assert good.get("ok") is True, good
    reading = dict(good.get("self_authored_review") or {})
    assert reading.get("needs_v") is True and reading.get("signed") is True, reading
    assert reading.get("verification_id") == sign["verification_id"], reading


def test_4_a_conjecture_is_still_registrable_without_v(tmp_path: pathlib.Path) -> None:
    """判据 4（正控）：B 登记自产猜想 ⇒ 不被这条拒（别把猜想堵死）。"""
    st = _ws(tmp_path)
    got = _ok(_b(st).register_statement(**_own(kind="conjecture")))
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
    恒回"签过了"的替身之后，判据 3 的那一笔（没有签）就会落库 —— 于是判据 3 的
    "拒 self_authored_needs_v" 必红。这条反真空证明判据 3 读的是那一份判定，不是
    "反正拒了"。
    """
    st = _ws(tmp_path)
    b = _b(st)
    first = _ok(b.register_statement(**_own(kind="conjecture")))
    assert first.get("ok") is True, first

    # 正控（没打补丁）：判据 3 的那一笔就在这一格被拒。
    plain = _ok(b.register_statement(**_own(kind="theorem", evidence_kind="proof_review")))
    assert plain.get("kind") == "self_authored_needs_v", plain

    def _always_signed(self, *, statement_full: str, proof_text: str) -> dict:
        return {"checked": True, "signed": True, "in_ledger": True,
                "stmt_id": str(first.get("stmt_id") or ""),
                "verification_id": "v-999999", "proof_sha256": "",
                "why": "（探针：恒回签过了）"}

    monkeypatch.setattr(_RegisterStatement, "_v_signature_for", _always_signed)
    forced = _ok(b.register_statement(**_own(kind="theorem", evidence_kind="proof_review")))
    # 判据 3 的断言是"拒收 `self_authored_needs_v`"。把那一份判定换成恒通过之后，
    # 这一格不再由它来拒（改由更后面的一级说话）⇒ 判据 3 必红。
    assert forced.get("kind") != "self_authored_needs_v", (
        "'要不要 V 签'的判定已经换成恒通过，这一笔却仍然报 self_authored_needs_v ⇒ "
        "判据 3 的牙不在那一份判定上（它可能是被别的东西顺手拦下的）：" + str(forced))
    assert str(forced.get("kind") or "") in ("duplicate_statement",
                                            "must_start_as_conjecture"), (
        "闸放开之后这一笔既没有落库、也没有落到更后面那一级 ⇒ 这个反真空没打中：" + str(forced))
