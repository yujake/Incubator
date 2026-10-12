# -*- coding: utf-8 -*-
"""业主 2026-10-12 的 Lean 开关（`toolchain.lean_enabled`）：一条轴上的六处判据。

## 逐字口径

「由于某些用户没有 Lean 环境，再设计一个模式，在全程不做 Lean 形式化的情况下尽可能用
审阅自然语言证明的方式推进论文审阅或课题研究。至于有没有 Lean 环境，这做一个 bool 值
让用户设置。全流程涉及 Lean 的都要跟进这个开关的状态。」

## 这条轴上的六处落点（每处一条判据，正控 + 负控）

| # | 落点 | 这一档的行为 |
|---|---|---|
| 1 | `settings.lean_enabled` | 环境变量 `AGENTFLOW_LEAN_ENABLED` > 设置文件 `toolchain.lean_enabled` > 缺省 `True`；读不懂当场报错 |
| 2 | `toolchain`（读数层） | `toolchain_report()` 给 `lean_enabled` / `formal_mode`；关掉时 `can_do_formal=False` |
| 3 | `formalgw.check_lean`（桥接层） | 关掉 ⇒ `status="lean_disabled"`、`checked=False`、连探测/进程都不起 |
| 4 | `agent_e`（实现层） | 关掉 ⇒ `run_experiment(method="formal")` 前置拒绝（`lean_disabled`），`check_formal` 如实回没查成 |
| 5 | 提示词（`TOOLCHAIN_FACTS` / `TOOLCHAIN_FORMAL`） | 关掉 ⇒ 先报"已关闭"并给出替代路线（`proof_text` + V 的 `verify_proof`） |
| 6 | 收工门（`closing` 的 `load_bearing`） | 关掉 ⇒ 记 `na` + 理由（不是 pass、也不是 fail），并给替代读数 |

负控的方向一律是"开关开着时逐字不变"：没设这个键 = 与 2026-10-12 之前行为相同。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import closing as CL
from agentflow import formalgw as FG
from agentflow import settings as SET
from agentflow import toolchain as TC
from agentflow import verifications as VR
from agentflow.agent_e import AgentE, ExperimentError
from agentflow.store import Store


@pytest.fixture(autouse=True)
def _no_ambient_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """判据跑在确定环境里：本机就算设了那个环境变量，也不许渗进来。"""
    monkeypatch.delenv(SET.ENV_LEAN_ENABLED, raising=False)


def _settings(tmp_path: pathlib.Path, text: str) -> pathlib.Path:
    p = tmp_path / "settings.json"
    p.write_text(text, encoding="utf-8")
    return p


# ============================================================ 1. 开关本体
def test_the_switch_ladder_is_env_then_settings_then_default(tmp_path: pathlib.Path) -> None:
    """正控：三档梯子各走一遍，且来源位如实报出来。"""
    assert SET.lean_enabled(env={}) == (True, ""), "缺省必须是 true（不设它 = 行为不变）"
    p = _settings(tmp_path, json.dumps({"toolchain": {"lean_enabled": False}}))
    assert SET.lean_enabled(p, env={}) == (False, "settings"), "JSON 布尔 false 必须被读到"
    assert SET.lean_enabled(p, env={SET.ENV_LEAN_ENABLED: "1"}) == (True, "env"), \
        "环境变量压在最上面（与其余键同一条梯子）"
    assert SET.lean_enabled(p, env={SET.ENV_LEAN_ENABLED: " "}) == (False, "settings"), \
        "空串 = 未设置，不遮住下一档"
    # 字符串写法也认（写设置文件的人手写 "false" 是常见的）
    p3 = tmp_path / "s3.json"
    p3.write_text(json.dumps({"toolchain": {"lean_enabled": "off"}}), encoding="utf-8")
    assert SET.lean_enabled(p3, env={}) == (False, "settings")


def test_a_value_that_cannot_be_understood_is_refused_not_defaulted(
        tmp_path: pathlib.Path) -> None:
    """负控：读不懂的值不许静默按缺省跑（那会让"我关掉了"与"我以为我关掉了"分不开）。"""
    p = _settings(tmp_path, json.dumps({"toolchain": {"lean_enabled": "maybe"}}))
    with pytest.raises(ValueError) as exc:
        SET.lean_enabled(p, env={})
    assert "读不懂" in str(exc.value)
    with pytest.raises(ValueError):
        SET.lean_enabled(env={SET.ENV_LEAN_ENABLED: "flase"})


def test_the_writer_accepts_a_real_bool_and_refuses_garbage(tmp_path: pathlib.Path) -> None:
    """写入口：真布尔（或 'true'/'false'）收，其余写法当场拒（不许落一条读不懂的配置）。"""
    p = tmp_path / "written.json"
    got = SET.write_settings({"toolchain": {"lean_enabled": False}}, p, env={})
    assert got["tri"] == "written", got
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["toolchain"]["lean_enabled"] == "false", on_disk
    assert SET.lean_enabled(p, env={}) == (False, "settings")
    bad = SET.write_settings({"toolchain": {"lean_enabled": "nope"}}, p, env={})
    assert bad["tri"] == "refused" and "lean_enabled" in bad["reason"], bad


def test_the_settings_example_carries_the_key_with_true(tmp_path: pathlib.Path) -> None:
    """示例文件里必须有这一格，且缺省是 true（用户照抄一份就得到今天的行为）。"""
    example = pathlib.Path(__file__).resolve().parents[1] / "settings.example.json"
    data = json.loads(example.read_text(encoding="utf-8"))
    assert data["toolchain"]["lean_enabled"] is True, data["toolchain"]
    assert any("lean_enabled" in str(k) or "lean_enabled" in str(v)
               for k, v in data.items()), "示例里要有这一格的说明行"


# ============================================================ 2. 读数层
def test_the_toolchain_reading_carries_the_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """读数层：开关与"机器上装没装"是两条独立的事实，都要能读出来。"""
    on = TC.toolchain_report(env={})
    assert on["lean_enabled"] is True and on["formal_mode"] == "formal"
    assert on["lean_enabled_source"] == ""
    off = TC.toolchain_report(env={SET.ENV_LEAN_ENABLED: "0"})
    assert off["lean_enabled"] is False and off["formal_mode"] == "prose_review"
    assert off["lean_enabled_source"] == "env"
    assert off["can_do_formal"] is False, "关掉时这一格必须是 False（不许报成能做）"


# ============================================================ 3. 桥接层
def test_check_lean_starts_no_process_when_the_switch_is_off(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """桥接层：关掉 ⇒ 受控状态 `lean_disabled`，且一次进程都不起。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    calls: list[tuple] = []

    def _spy(*a, **k):     # 任何"真跑一次"的路都不许走到这里
        calls.append(a)
        raise AssertionError("开关关着时不该起检查器")

    res = FG.check_lean("theorem t : 1 = 1 := rfl", name="t", run_fn=_spy)
    assert res["status"] == "lean_disabled", res["status"]
    assert res["ran"] is False and res["exit_code"] is None
    assert res["evidence"]["checked"] is False
    assert res["evidence"]["evidence_kind"] is None, "关掉时产不出任何等级的证据"
    assert "已关闭" in res["reason"], res["reason"]
    assert calls == [], calls


def test_the_switch_on_does_not_change_the_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    """负控：开关开着时逐字不变 —— 那条路照旧走检查器（这里用注入的 run_fn 证明）。"""
    monkeypatch.delenv(SET.ENV_LEAN_ENABLED, raising=False)
    seen: list[tuple] = []

    def _fake(cmd, *, cwd, timeout_sec):
        seen.append(tuple(cmd))
        return {"exit_code": 0, "stdout": "", "stderr": "", "elapsed_sec": 0.1}

    res = FG.check_lean("theorem t : 1 = 1 := rfl", name="t", run_fn=_fake)
    assert res["status"] != "lean_disabled"
    assert seen, "开关开着时必须真的走一次检查器调用"


# ============================================================ 4. 实现层（E）
def test_e_refuses_a_formal_experiment_before_running_anything(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """实现层：关掉 ⇒ `method='formal'` 在跑脚本之前就被拒，理由里带上替代路线。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    script = ws / "code" / "x.lean"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("theorem t : 1 = 1 := rfl\n", encoding="utf-8")
    e = AgentE(st, workspace_root=ws)
    with pytest.raises(ExperimentError) as exc:
        e.run_experiment("命题", "k1", str(script), method="formal")
    msg = str(exc.value)
    assert "已关闭" in msg and "verify_proof" in msg, msg
    # 负控：非形式化那条路照常（关掉 Lean 不该把数值实验也关掉）
    num = ws / "code" / "y.py"
    num.write_text('print("REPRO_RESULT: {\\"result\\": \\"supports\\"}")\n', encoding="utf-8")
    got = e.run_experiment("命题", "k1", str(num), method="numeric")
    assert got["evidence_kind"] in ("cross_check", "heuristic"), got


def test_e_check_formal_reports_lean_disabled_not_no_backend(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """实现层：`check_formal` 的受控理由要把"用户关掉了"与"机器上没有"分开。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    out = AgentE(st, workspace_root=ws).check_formal("命题", source="theorem t : True := trivial",
                                                     name="t")
    assert out["checked"] is False, out
    assert out["reason"] == "lean_disabled", out
    assert out["reason"] != "no_backend", "两件事不许折叠成一档"


# ============================================================ 5. 提示词
def test_the_prompt_blocks_follow_the_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """提示词：关掉时先报"已关闭"并给出替代路线；开着时逐字不提关闭那件事。"""
    from agentflow import agent_prompts as AP

    monkeypatch.delenv(SET.ENV_LEAN_ENABLED, raising=False)
    AP.reset_toolchain_readings()
    on_facts, on_formal = AP.toolchain_facts_text(), AP.toolchain_formal_text()
    assert "已关闭" not in on_facts and "已关闭" not in on_formal

    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    AP.reset_toolchain_readings()
    off_facts, off_formal = AP.toolchain_facts_text(), AP.toolchain_formal_text()
    assert "已关闭" in off_facts, off_facts
    assert "verify.verify_proof" in off_formal and "proof_text" in off_formal, off_formal
    assert "lean_disabled" in off_formal, "要告诉模型见到这个状态别再重试"
    monkeypatch.delenv(SET.ENV_LEAN_ENABLED, raising=False)
    AP.reset_toolchain_readings()
    assert AP.toolchain_facts_text() == on_facts, "复位之后必须回到开着那一版（缓存要清干净）"


# ============================================================ 6. 收工门
class _Rep:
    """收工门那一格的最小替身（`_check_load_bearing` 只碰这三个属性）。"""

    def __init__(self) -> None:
        self.status: dict[str, str] = {}
        self.findings: list = []
        self.readings: dict[str, object] = {}


def test_the_closing_cell_says_not_applicable_instead_of_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """收工门：关掉 ⇒ `na` + 理由 + 替代读数（V 审过的证明行），不是 fail。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", {"stmt_id": "0000", "status": "active",
                                 "evidence_kind": "cross_check",
                                 "statement_full": "命题", "proof_text": "证明：一行",
                                 "quote_reason": "这一行只为这一格的读数而造，不涉及外部原文",
                                 "origin": "own_result"})
    # V 的审校是工作区里的文件（`verifications/<命题号>.jsonl`），不是台账表：
    # 这里就用它自己的写入口落一行「成立」，再核收工门那一格读不读得到。
    VR.record_verification(ws, statement_id="0000", proof_text="证明：一行",
                           verdict={"verdict": "成立", "findings": []}, verifier="V")
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    rep = _Rep()
    CL._check_load_bearing(rep, st)
    assert rep.status["load_bearing"] == "na", rep.status
    assert rep.readings["load_bearing"]["disabled"] is True
    assert rep.readings["load_bearing"]["prose_reviewed_statements"] == 1, \
        rep.readings["load_bearing"]
    assert all(f.level != "blocker" for f in rep.findings), rep.findings


def test_the_closing_cell_is_unchanged_when_the_switch_is_on(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控：开着 ⇒ 老判据照旧（没有 proof 断言时 pass，读数里没有 disabled 那一格）。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    monkeypatch.delenv(SET.ENV_LEAN_ENABLED, raising=False)
    rep = _Rep()
    CL._check_load_bearing(rep, st)
    assert rep.status["load_bearing"] == "pass", rep.status
    assert "disabled" not in rep.readings["load_bearing"]
