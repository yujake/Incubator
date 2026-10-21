"""`draft/37` §64 的判据：「模型调用的钱必须进账本」，而判据不许据假账本给 pass。

撞出来的那一处（第 11 趟真机）：`usage_ledger` 对一次真花了 0.289069 美元的运行报 `0.000000`
（9 行全是零）。病因是结构性的：`LlmSeam` 根本没有 meter 字段，`run-agent` 这条路上没有任何
一行代码把花销写进账本 —— 钱只活在 `SeamSpend`（内存，随进程消失）与会话事件的 `llm_call.usd` /
`spend_after`（盘上，但只有 `reviewaccept` 的成本判据不看它）。

于是 `reviewaccept.within_cost_cap`（cap=0.10 实测）拿一份"花了 0"的账本判"没超上限"—— 而真实
花销是上限的三倍。假绿，且「七趟运行全部同形」。

判据两条腿（缺一条就退回假绿）：1. 写入侧：缝接了 `meter` 就必须落一行真账，且「账本上的数 ==
会话事件里的数」（两处逐位相等才算同一笔钱；这是 `_charge_ledger` 直接造 `Charge` 而不是借
`charge_reply` 重算的理由 —— `SeamCall` 没有 `attempts`，重算会漏掉重试）；2. 读取侧：
`within_cost_cap` 必须两头看 —— 账本 + 会话事件，取大的那个判上限；账本比会话少 ⇒「fail」
（"账本没跟上这一趟"），会话里有算不出价钱的调用 ⇒「unknown」（说不清花了多少）。

负控都在：没接 meter 时「不入账」（不是记一笔零）、失败调用也留痕、别的会话/别的角色不互相
污染、旧账本为零的历史工作区必须被判成 fail 而不是 pass。"""
from __future__ import annotations

import pathlib
from typing import Any

from agentflow import closing as CL          # noqa: F401  (与 reviewaccept 同一套三态口径)
from agentflow import reviewaccept as RX
from agentflow import schema as S
from agentflow import sessions as SS
from agentflow import store as Store_
from agentflow.llmseam import LlmSeam
from agentflow.tokenmeter import TokenMeter

WS = "real64"


class FakeGw:
    """一个只回 usage 的假网关（离线：不碰网络、不读 key）。"""

    def __init__(self, *, tokens_in: int = 10000, tokens_out: int = 1000, ok: bool = True):
        self.tokens_in, self.tokens_out, self.ok = tokens_in, tokens_out, ok

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 max_tokens: Any = None, tools: Any = None) -> Any:
        return type("Reply", (), {
            "ok": self.ok, "text": "{}", "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out, "scope": scope, "attempts": 1,
            "error_detail": "", "error_kind": "",
        })()


class BoomGw:
    """发请求时炸掉的网关（超时那条路的代表）。"""

    def complete(self, prompt: str, **kw: Any) -> Any:
        raise TimeoutError("上游超时")


def _ws(tmp_path: pathlib.Path) -> tuple[Store_.Store, pathlib.Path]:
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    st = Store_.Store(tmp_path)
    st.init()
    return st, tmp_path


def _seam(st: Store_.Store, ws: pathlib.Path, *, meter: Any, gw: Any | None = None,
          price: Any = (1.0, 2.0)) -> LlmSeam:
    return LlmSeam(role="M", session_root=ws, gateway=gw or FakeGw(), price=price,
                   sid=WS, meter=meter)


def _events(ws: pathlib.Path, sid: str = WS) -> list[dict]:
    events, _ = SS.read_session(ws, sid=sid)
    return events


def _calls(ws: pathlib.Path, sid: str = WS) -> list[dict]:
    return [e for e in _events(ws, sid) if e.get("kind") == "llm_call"]


# ============================================================ 写入侧：落真账

def test_a_seam_call_with_a_meter_lands_one_true_row(tmp_path: pathlib.Path):
    """正控：接了账本的缝，一次调用落一行 —— 且「账本的数 == 事件里的数」。

    这两个数相等是本判据的核心（不是"反正记了一行"）：
    账本记 0.012 而事件记 0.024（重试被漏算）同样是假账。
    """
    st, ws = _ws(tmp_path)
    seam = _seam(st, ws, meter=TokenMeter(st))
    call = seam.ask("hi")

    assert call.ok, call.detail
    assert call.usd is not None and call.usd > 0, call.to_dict()
    rows = st.rows("usage_ledger")
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["usd"] == round(call.usd, 6), (row["usd"], call.usd)
    assert int(row["tokens_in"]) == call.tokens_in and int(row["tokens_out"]) == call.tokens_out
    assert int(row["attempts"]) == 1 and row["task_id"] is None, row
    assert row["scope"] == "reason" and row["role"] == "M", row
    assert "llmseam" in str(row["note"]) and str(row["idem_key"]).startswith("idem-"), row
    # 汇总口径也要对得上：`meter.spent()` 是预算判据读的那个数
    assert TokenMeter(st).spent()["usd"] == round(call.usd, 6), TokenMeter(st).spent()

    # 会话事件自己说得出"这次的钱记成哪一行"（两处用同一个 usage_id 交叉可查）
    ev = _calls(ws)[0]
    assert ev["ledger"]["charged"] is True, ev["ledger"]
    assert ev["ledger"]["usage_id"] == row["usage_id"], (ev["ledger"], row)


def test_without_a_meter_nothing_is_charged_and_it_says_so(tmp_path: pathlib.Path):
    """负控：没接账本 ⇒ 「不入账」，且如实说（不是"记了一笔零"，更不是"免费"）。

    这一条同时也是"不许悄悄退化成零"的判据：`meter=None` 时账本必须「没有行」，
    而事件里必须有一句 `no_meter` 的可读理由。
    """
    st, ws = _ws(tmp_path)
    seam = _seam(st, ws, meter=None)
    call = seam.ask("hi")
    assert call.ok, call.detail
    assert st.rows("usage_ledger") == [], st.rows("usage_ledger")
    assert _calls(ws)[0]["ledger"]["reason"] == "no_meter", _calls(ws)[0]["ledger"]


def test_two_calls_land_two_rows_with_distinct_keys(tmp_path: pathlib.Path):
    """反真空：两次调用是两行、两个幂等键 —— 键撞了后到的那笔会被静默判重放。"""
    st, ws = _ws(tmp_path)
    seam = _seam(st, ws, meter=TokenMeter(st))
    first, second = seam.ask("one"), seam.ask("two")
    rows = st.rows("usage_ledger")
    assert len(rows) == 2, rows
    assert len({r["idem_key"] for r in rows}) == 2, rows
    assert round(TokenMeter(st).spent()["usd"], 6) == round((first.usd or 0) + (second.usd or 0), 6)


def test_a_failed_call_is_recorded_not_dropped(tmp_path: pathlib.Path):
    """负控：发过请求但失败 ⇒ 照样留一行（钱可能已经花了；"这次尝试"本身是事实）。"""
    st, ws = _ws(tmp_path)
    seam = _seam(st, ws, meter=TokenMeter(st), gw=BoomGw())
    call = seam.ask("hi")
    assert not call.ok and call.problem == "judge_timeout", call.to_dict()
    rows = st.rows("usage_ledger")
    assert len(rows) == 1, rows
    assert "judge_timeout" in str(rows[0]["note"]), rows[0]
    assert float(rows[0]["usd"]) == 0.0, rows[0]


def test_a_preflight_refusal_is_not_charged(tmp_path: pathlib.Path):
    """负控：「没发请求」的两次早退（没接线 / 预算已尽）不入账 —— 没有钱要记。"""
    st, ws = _ws(tmp_path)
    seam = _seam(st, ws, meter=TokenMeter(st), gw=None)
    seam.gateway = None                                    # 没接线
    seam.ask("hi")
    over = _seam(st, ws, meter=TokenMeter(st))
    over.usd_budget = 0.0                                  # 预算已尽（0 = 什么都不准做）
    over.ask("hi")
    assert st.rows("usage_ledger") == [], st.rows("usage_ledger")
    reasons = {e["ledger"]["reason"] for e in _calls(ws)}
    assert reasons == {"no_request"}, reasons


# ============================================================ 读取侧：判据两头看

def test_the_judge_catches_a_ledger_that_did_not_keep_up(tmp_path: pathlib.Path):
    """核心负控：「重现第 11 趟的形态」 —— 会话里花了钱、账本里没有 ⇒ 不许 pass。

    这一条是 §64 的判据本体：它不依赖任何模型调用，直接把"第 11 趟"搬到测试里
    （会话一条 `llm_call` 合计 0.289069，账本零行），然后要求
    `within_cost_cap` 报 fail。修完写入侧之后真机不会再出现这个形态，
    但"下一次又有人加一条忘了记账的路"必须当场红。
    """
    st, ws = _ws(tmp_path)
    SS.append(ws, {"kind": "llm_call", "role": "M", "usd": 0.289069, "tokens_in": 1020869,
                   "tokens_out": 12212, "spend_after": {"usd": 0.289069}}, sid=WS)
    acc = RX.check_review(st, project_dir="", report_path="", cost_cap_usd=2.0,
                          session_root=ws, sid=WS)
    assert acc.criteria["within_cost_cap"] == "fail", acc.to_dict()
    assert "没跟上" in acc.details["within_cost_cap"], acc.details
    assert acc.readings["cost"]["session_usd"] == 0.289069, acc.readings["cost"]

    # 上限比真花销还小 ⇒ 也要红（而且是"超过"那条理由，不是"账本没跟上"）
    acc2 = RX.check_review(st, project_dir="", report_path="", cost_cap_usd=0.10,
                           session_root=ws, sid=WS)
    assert acc2.criteria["within_cost_cap"] == "fail", acc2.to_dict()
    assert "上限" in acc2.details["within_cost_cap"], acc2.details

    # 负控的负控：把账本补齐（模拟修好之后的运行）⇒ 同一份会话必须变成 pass，
    # 否则上面那两条红的证明力只到"这个判据恒红"。
    meter = TokenMeter(st)
    from agentflow.tokenmeter import Charge

    meter.charge(Charge(role="M", scope="reason", tokens_in=1020869, tokens_out=12212,
                        usd=0.289069, task_id=None, note="补齐：模拟已修好的运行"))
    acc3 = RX.check_review(st, project_dir="", report_path="", cost_cap_usd=2.0,
                           session_root=ws, sid=WS)
    assert acc3.criteria["within_cost_cap"] == "pass", acc3.to_dict()


def test_an_unpriced_call_is_unknown_not_pass(tmp_path: pathlib.Path):
    """三态：会话里有「算不出价钱」的调用 ⇒ `unknown`（说不清花了多少，不是通过）。

    账本那一行照样留下（token 数是真的），`note` 必须写明"0 是算不出来"。
    """
    st, ws = _ws(tmp_path)
    seam = _seam(st, ws, meter=TokenMeter(st), price=(None, None))   # 价表不可用
    call = seam.ask("hi")
    assert call.usd is None and "花销未能折算" in call.detail, call.to_dict()
    rows = st.rows("usage_ledger")
    assert len(rows) == 1 and int(rows[0]["tokens_in"]) == call.tokens_in, rows
    assert float(rows[0]["usd"]) == 0.0 and "算不出来" in str(rows[0]["note"]), rows[0]

    acc = RX.check_review(st, project_dir="", report_path="", cost_cap_usd=1.0,
                          session_root=ws, sid=WS)
    assert acc.criteria["within_cost_cap"] == "unknown", acc.to_dict()
    assert "算不出价钱" in acc.details["within_cost_cap"], acc.details


def test_a_real_seam_run_reconciles_ledger_and_session(tmp_path: pathlib.Path):
    """端到端（离线）：缝跑两次之后，账本合计 == 会话事件合计（不允许差一分钱）。"""
    st, ws = _ws(tmp_path)
    seam = _seam(st, ws, meter=TokenMeter(st))
    seam.ask("one")
    seam.ask("two")
    ledger = TokenMeter(st).spent()["usd"]
    session = round(sum(float(e["usd"] or 0.0) for e in _calls(ws)), 6)
    assert ledger == session, (ledger, session)
    acc = RX.check_review(st, project_dir="", report_path="", cost_cap_usd=1.0,
                          session_root=ws, sid=WS)
    assert acc.criteria["within_cost_cap"] == "pass", acc.to_dict()


# ============================================================ 接线（产品路径）

def test_the_cli_seam_factory_wires_the_meter_to_the_same_store(tmp_path, monkeypatch):
    """正控：`cli._agent_seam_factory` 必须把 meter 接到「同一个 store 实例」上。

    另建一个 `Store(root)` 也能"看起来记了账"，但两个实例各自持一份内存副本，
    后写的那个会把先写的行覆盖掉 —— 账本静默丢账。所以这里钉的是「同一个对象」。
    """
    from agentflow import cli
    from agentflow import llmseam as LS

    st, ws = _ws(tmp_path)
    seen: dict[str, Any] = {}

    def fake_for_role(cls, role: str, **kw: Any) -> Any:      # noqa: ANN001
        seen.update(kw, role=role)
        return "SEAM"

    monkeypatch.setattr(LS.LlmSeam, "for_role", classmethod(fake_for_role))
    out = cli._agent_seam_factory("M", root=ws, sid="t", usd_budget=2.0, store=st)
    assert out == "SEAM"
    assert isinstance(seen["meter"], TokenMeter), seen
    assert seen["meter"].store is st, "meter 必须挂在同一个 store 上（另建实例会互相覆盖）"
    assert seen["meter"].budget_usd == 2.0, seen

    seen.clear()
    cli._agent_seam_factory("M", root=ws, sid="t", usd_budget=2.0, store=None)
    assert seen["meter"] is None, "没有 store ⇒ meter=None（如实报『没有入账』）"


def test_the_host_default_seam_carries_a_meter(tmp_path):
    """正控：`host.wired_llm_conductor` 默认造出来的缝必须带 meter。

    真机走的就是这条路；装配层漏接一个参数，前面全绿而账本照旧全零。
    """
    from agentflow import host

    st, ws = _ws(tmp_path)
    wiring = host.wired_llm_conductor(st, session_root=ws, sid="t", workspace_root=str(ws))
    seam = wiring["backend"].seam_factory("M")
    assert seam.meter is not None, "默认缝没有 meter ⇒ run-agent 一次调用都不会进账本"
    assert seam.meter.store is st, "meter 必须挂在同一个 store 上"
    assert pathlib.Path(seam.session_root) == pathlib.Path(ws), seam.session_root


def test_the_reason_scope_declaration_names_both_producers():
    """归口 `reason` 现在有两个产出点 ⇒ 那张人写的声明必须两个都写（`G-6`）。

    声明写着"只有 runflow 产出它"而实际还有 `llmseam`，就是一句假话 ——
    `schema.USAGE_SCOPE_PRODUCERS` 自己那段注释逐字反对这件事。
    """
    producers = S.USAGE_SCOPE_PRODUCERS["reason"]
    assert producers is not None, "归口 reason 被登记成『没有产出点』了？"
    assert any("llmseam" in str(part) for part in producers), producers
