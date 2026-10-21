# -*- coding: utf-8 -*-
"""业主 2026-10-12 的 Lean 开关（`toolchain.lean_enabled`）：一条轴上的六处判据。

「由于某些用户没有 Lean 环境，再设计一个模式，在全程不做 Lean 形式化的情况下尽可能用
审阅自然语言证明的方式推进论文审阅或课题研究。至于有没有 Lean 环境，这做一个 bool 值
让用户设置。全流程涉及 Lean 的都要跟进这个开关的状态。」

六处落点（每处一条判据，正控 + 负控）：

| # | 落点 | 这一档的行为 |
|---|---|---|
| 1 | `settings.lean_enabled` | 环境变量 `AGENTFLOW_LEAN_ENABLED` > 设置文件 `toolchain.lean_enabled` > 缺省 `True`；
读不懂当场报错 |
| 2 | `toolchain`（读数层） | `toolchain_report()` 给 `lean_enabled` / `formal_mode`；关掉时 `can_do_formal=False` |
| 3 | `formalgw.check_lean`（桥接层） | 关掉 ⇒ `status="lean_disabled"`、`checked=False`、连探测/进程都不起 |
| 4 | `agent_e`（实现层） | 关掉 ⇒ `run_experiment(method="formal")` 前置拒绝（`lean_disabled`），`check_formal` 如实回没查成 |
| 5 | 提示词（`TOOLCHAIN_FACTS` / `TOOLCHAIN_FORMAL`） | 关掉 ⇒ 先报"已关闭"并给出替代路线（`proof_text` + V 的 `verify_proof`） |
| 6 | 收工门（`closing` 的 `load_bearing`） | 关掉 ⇒ 记 `na` + 理由（不是 pass、也不是 fail），并给替代读数 |

负控的方向一律是"开关开着时逐字不变"：没设这个键 = 与 2026-10-12 之前行为相同。"""
from __future__ import annotations

import json
import os
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
def _lean_on_by_suite_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """套件契约：`tests/conftest.py` 把整趟套件钉成"Lean 开着"（产品缺省是关的）。

    本文件里的用例各自显式声明自己要哪一档（`monkeypatch.setenv(..., "0"/"1")`），
    所以这里只核那条钉还在 —— 它不见了就说明这一批判据跑在了一个不该有的档上，
    而那种错会让"关掉时的行为"这件事被误判成"实现了"。
    """
    assert os.environ.get(SET.ENV_LEAN_ENABLED) == "1", (
        "套件的 Lean 开关钉不见了（见 tests/conftest.py）⇒ 这一批会跑错档")


def _settings(tmp_path: pathlib.Path, text: str) -> pathlib.Path:
    p = tmp_path / "settings.json"
    p.write_text(text, encoding="utf-8")
    return p


# ============================================================ 1. 开关本体
def test_the_product_default_is_lean_off() -> None:
    """产品缺省是关（业主 2026-10-12：「默认设置中 Lean 关闭帮用户在无严苛要求时省钱」）。

    这条判据与 `tests/conftest.py` 里"套件跑在开着那一档"的那一行是一对：
    套件跑开着（守形式化那条路的接线），而产品缺省由这一条单独钉住 ——
    两者分家的形态是"套件全绿、用户装出来却是关的"，而那种错没有任何读数会报。
    """
    assert SET.DEFAULT_LEAN_ENABLED is False, SET.DEFAULT_LEAN_ENABLED
    assert SET.lean_enabled(env={}) == (False, ""), "没设任何一档时就是关"
    # 示例文件也必须写 false（用户照抄一份就得到缺省行为 —— 那句注释与它必须一致）
    example = pathlib.Path(__file__).resolve().parents[1] / "settings.example.json"
    data = json.loads(example.read_text(encoding="utf-8"))
    assert data["toolchain"]["lean_enabled"] is False, data["toolchain"]


def test_the_switch_ladder_is_env_then_settings_then_default(tmp_path: pathlib.Path) -> None:
    """正控：三档梯子各走一遍，且来源位如实报出来。"""
    assert SET.lean_enabled(env={}) == (False, ""), "缺省是关（见上一条）"
    p = _settings(tmp_path, json.dumps({"toolchain": {"lean_enabled": False}}))
    assert SET.lean_enabled(p, env={}) == (False, "settings"), "JSON 布尔 false 必须被读到"
    assert SET.lean_enabled(p, env={SET.ENV_LEAN_ENABLED: "1"}) == (True, "env"), \
        "环境变量压在最上面（与其余键同一条梯子）"
    assert SET.lean_enabled(p, env={SET.ENV_LEAN_ENABLED: " "}) == (False, "settings"), \
        "空串 = 未设置，不遮住下一档"
    # 字符串写法也认（写设置文件的人手写 "false" 是常见的）
    p3 = tmp_path / "s3.json"
    p3.write_text(json.dumps({"toolchain": {"lean_enabled": "on"}}), encoding="utf-8")
    assert SET.lean_enabled(p3, env={}) == (True, "settings")
    # 显式写 true 就等于老套路（产品缺省的翻转只影响"不写这一格"的人）
    p4 = tmp_path / "s4.json"
    p4.write_text(json.dumps({"toolchain": {"lean_enabled": True}}), encoding="utf-8")
    assert SET.lean_enabled(p4, env={}) == (True, "settings")


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


def test_the_settings_example_carries_the_key_with_false() -> None:
    """示例文件里必须有这一格，且写的是 false（用户照抄一份就得到今天的缺省行为）。"""
    example = pathlib.Path(__file__).resolve().parents[1] / "settings.example.json"
    data = json.loads(example.read_text(encoding="utf-8"))
    assert data["toolchain"]["lean_enabled"] is False, data["toolchain"]
    assert any("lean_enabled" in str(k) or "lean_enabled" in str(v)
               for k, v in data.items()), "示例里要有这一格的说明行"


# ============================================================ 2. 读数层
def test_the_toolchain_reading_carries_the_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """读数层：开关与"机器上装没装"是两条独立的事实，都要能读出来。"""
    off = TC.toolchain_report(env={})
    assert off["lean_enabled"] is False and off["formal_mode"] == "prose_review"
    assert off["lean_enabled_source"] == "", "没设任何一档 ⇒ 来源是空串（缺省关）"
    on = TC.toolchain_report(env={SET.ENV_LEAN_ENABLED: "1"})
    assert on["lean_enabled"] is True and on["formal_mode"] == "formal"
    assert on["lean_enabled_source"] == "env"
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
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
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

    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    AP.reset_toolchain_readings()
    on_facts, on_formal = AP.toolchain_facts_text(), AP.toolchain_formal_text()
    assert "已关闭" not in on_facts and "已关闭" not in on_formal

    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    AP.reset_toolchain_readings()
    off_facts, off_formal = AP.toolchain_facts_text(), AP.toolchain_formal_text()
    assert "已关闭" in off_facts, off_facts
    assert "verify.verify_proof" in off_formal and "proof_text" in off_formal, off_formal
    assert "lean_disabled" in off_formal, "要告诉模型见到这个状态别再重试"
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    AP.reset_toolchain_readings()
    assert AP.toolchain_facts_text() == on_facts, "复位之后必须回到开着那一版（缓存要清干净）"


# ============================================================ 5b. 关掉时的「面」
def _unapplied_entries(table: tuple[tuple[str, str], ...],
                       text: str) -> list[tuple[int, str]]:
    """逐条判"这一条改写真的被应用了吗"：原句还在、或改写后的文本没出现 ⇒ 没应用。

    为什么两条都要判（`T-L3`，2026-10-20 修的那一处静默失效）：只判"原句不在"会被
    `old` 自己写错骗过去 —— 写错的原句当然不在任何文本里，于是"关掉时没有形式化字样"
    成了假绿。`new` 必须出现才是"这一条真的替换过"。
    """
    return [(i, old) for i, (old, new) in enumerate(table)
            if old in text or new not in text]


def test_the_no_lean_variant_rewrites_every_role_face(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """业主 2026-10-12（逐字）：「负责 Lean 的智能体 E 在开关关掉时可不载入有关形式化验证的
    提示词，全体成员关于 E 的印象也可以没有『负责形式化验证』这个说法，一旦提到形式化验证
    所有人的第一反应是系统做不了」。

    四个方向都判：① 反真空（改写表/删除表的左边必须在开着时的提示词里逐字出现，
    否则它们会在某次重写之后悄悄失效，而"关掉时没有形式化字样"就成了假绿）；
    ② 关掉时十个角色里一个形式化广告面都不许剩（职责句 / 工具描述 / 伙伴表都算），
    且每格都必须出现「系统做不了」；③ 关掉时逐条核这张表的每一条都真的被应用了
    （原句不剩 ＋ 改写后的文本在位 ＋ 改写文本自己不提 Lean）；④ 开着时收口逐字返回原文。
    """
    from agentflow import agent_prompts as AP
    from agentflow import schema as S
    from agentflow.specs import e as E
    from agentflow.tools import build_registry

    roles = tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)
    reg = build_registry().registry
    # 反真空那一半必须在显式打开的那一档取：产品缺省是关的（见本文件第一条判据）
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    AP.reset_toolchain_readings()
    on_text = "\n".join(AP.system_prompt(r, registry=reg) for r in roles)
    # ④ 开着 ⇒ 原样：收口在开着那一档必须逐字返回原文（一次替换都不做）
    assert AP._apply_no_lean_variant(on_text) == on_text, \
        "开着时收口改了提示词的一个字（负控：这一档必须与没这张表时逐字相同）"
    for old, _new in E.NO_LEAN_REPLACEMENTS:
        assert old in on_text, f"改写表的左边在开着时的提示词里找不到（表失效了）：{old!r}"
    for mark in E.NO_LEAN_DROP_LINE_MARKERS:
        assert mark in on_text, f"删除表的标记在开着时的提示词里找不到（表失效了）：{mark!r}"
    for start, keep in E.NO_LEAN_DROP_BLOCKS:
        assert start in on_text and keep in on_text, (start, keep)

    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    AP.reset_toolchain_readings()
    try:
        facts = AP.toolchain_facts_text()
        off_text = "\n".join(
            AP.system_prompt(role, registry=reg, toolchain_facts=facts) for role in roles)
        for role in roles:
            text = AP.system_prompt(role, registry=reg, toolchain_facts=facts)
            for face in ("数值实验与形式化验证", "转发到形式化检查器",
                         "你这一岗怎么写形式化", "默认不注入任何库",
                         "`E.check_formal` 逐条核"):
                assert face not in text, f"{role} 的提示词里还留着形式化广告面：{face!r}"
            assert "系统做不了" in text, (
                f"{role} 的提示词里必须说清「本会话不做形式化验证：系统做不了」")
        # ③ 逐条：关掉之后每一条原句都必须被改写掉、且改写后的那一段必须真的在位。
        #    只判"原句不在"是不够的（写错的原句当然不在）—— 两条一起才是"逐条断言"，
        #    负控见 `test_a_corrupted_entry_in_the_rewrite_table_is_reported_by_name`。
        unapplied = _unapplied_entries(E.NO_LEAN_REPLACEMENTS, off_text)
        assert unapplied == [], (
            "关掉形式化之后这些改写没有生效（原句还在 / 改写文本没出现）："
            + "；".join(f"第 {i} 条 {old[:40]!r}…" for i, old in unapplied))
        for i, (old, new) in enumerate(E.NO_LEAN_REPLACEMENTS):
            assert "Lean" not in new, (
                f"改写表第 {i} 条（{old[:40]!r}…）的改写文本自己还提着 Lean：{new!r}")
    finally:
        monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")   # 还原成套件钉的那一档
        AP.reset_toolchain_readings()


def test_a_corrupted_entry_in_the_rewrite_table_is_reported_by_name(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """负控（③ 那把尺子）：把表里一条原句改坏 ⇒ 必须红，并点名是哪一条。

    为什么这条负控必须有：工具面/动作面那两条的左边现在是从真身读的
    （`specs/e.py` 里那两个读工具描述的辅助函数），所以"表与工具面抄漂"这种失效
    结构上不会再发生 —— 但"这张表根本没跑"仍然可能（例如收口换了匹配方式、或那一行
    被别处先删掉了）。`specs/e.py` 那一批的原始故障正是"左边对不上 ⇒ 静默不替换"，
    它当时唯一的读数就是判据报"表失效了"，而"面还在广告"这件事没有任何断言。
    这条负控钉住的就是后者。

    取的是工具面那一条（`old` 以 `verify.check_formal：` 开头）：它正是当年漂掉的那一条，
    改坏它 ⇒ 关掉时那一行照旧读作"把 Lean 源码交给检查器真跑一次"。
    """
    from agentflow import agent_prompts as AP
    from agentflow import schema as S
    from agentflow.specs import e as E
    from agentflow.tools import build_registry

    roles = tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)
    reg = build_registry().registry
    victim = next(i for i, (old, _n) in enumerate(E.NO_LEAN_REPLACEMENTS)
                  if old.startswith("verify.check_formal："))

    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    AP.reset_toolchain_readings()
    try:
        facts = AP.toolchain_facts_text()

        def _off_text() -> str:
            return "\n".join(
                AP.system_prompt(r, registry=reg, toolchain_facts=facts) for r in roles)

        # 正控：原表条条都应用得上（否则负控的"改坏"就分不清是谁的问题）
        assert _unapplied_entries(E.NO_LEAN_REPLACEMENTS, _off_text()) == []

        old, new = E.NO_LEAN_REPLACEMENTS[victim]
        broken = list(E.NO_LEAN_REPLACEMENTS)
        broken[victim] = (old + "（故意改坏）", new)
        monkeypatch.setattr(E, "NO_LEAN_REPLACEMENTS", tuple(broken))
        AP.reset_toolchain_readings()
        hit = _unapplied_entries(tuple(broken), _off_text())
        assert [i for i, _old in hit] == [victim], (
            f"改坏第 {victim} 条之后尺子没有点名它（点到了 {hit!r}）")
        assert hit[0][1].endswith("（故意改坏）"), hit
        # 反真空的另一半：被改坏的那一条在开着的那一档也找不到了 —— 这就是
        # "表失效"的形态本身（不是"面没被改写"）。
        monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
        AP.reset_toolchain_readings()
        on_text = "\n".join(AP.system_prompt(r, registry=reg) for r in roles)
        assert hit[0][1] not in on_text, "改坏的原句居然还在提示词里（那它没改坏）"
    finally:
        monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
        AP.reset_toolchain_readings()



# ============================================================ 6. 用词上限（论文那一档）
def test_the_wording_ceiling_follows_the_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """业主 2026-10-12：「写论文那一档原先卡每个定理都要到 proof 水平，但没 Lean 显然做不到，
    但也要能写」—— 关掉时用词上限多一档 `proof_review`（逐行审阅过的证明），开着时不多。

    ① 关掉时 `proof_review` + 声明 ⇒ 干净（可以写「定理/证明」）；
    ② 关掉时缺声明 ⇒ `missing_disclaimer`；③ 开着时同一份断言 ⇒ `overclaim`（老套路不变）；
    ④ `cross_check` 不是上限（写了照旧报）；⑤ 实验表不许声称这一档（凭据在 `verifications`）。
    """
    from agentflow import claimanatomy as CA
    from agentflow import schema as S
    from agentflow.tools import doc_tools as DT

    def _claim(ek: str, disc: str | None) -> dict:
        c = {"claim_id": "c1", "section": "1", "text": "定理 3.1 成立：我们证明了它",
             "evidence_kind": ek, "citations": ["stmt:0001"], "is_negative": False}
        if disc is not None:
            c["disclaimer"] = disc
        return c

    def _codes(c: dict) -> set[str]:
        res = CA.validate_claim(c)
        issues = getattr(res, "issues", None)
        if issues is None:
            issues = res if isinstance(res, (list, tuple)) else []
        return {i.code for i in issues}

    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    assert set(DT.wording_ceiling()) == {"proof", "proof_review"}
    assert "overclaim" not in _codes(_claim("proof_review", DT.PROOF_REVIEW_DISCLAIMER))
    assert "missing_disclaimer" in _codes(_claim("proof_review", None))
    assert "overclaim" in _codes(_claim("cross_check", DT.CROSS_CHECK_DISCLAIMER)), \
        "cross_check 不是用词上限：写「定理/证明」照旧要报"

    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    assert set(DT.wording_ceiling()) == {"proof"}, "开着时上限回到只有 proof（老套路）"
    assert "overclaim" in _codes(_claim("proof_review", DT.PROOF_REVIEW_DISCLAIMER))

    got = DT.compose_claim("定理 3.1 成立", citations=["stmt:0001"],
                           evidence_kind="proof_review", section="1")
    assert got["disclaimer"] == DT.PROOF_REVIEW_DISCLAIMER, got
    assert "proof_review" not in S.EXPERIMENT_EVIDENCE_KINDS
    assert "proof_review" in S.EVIDENCE_KINDS


def test_a_self_written_disclaimer_does_not_pass() -> None:
    """判据（2026-10-13，无 Lean T2 的真机）：写了的声明也必须是受控那一句。

    真机现场（`projects/p6t2-research-20261012b/documents/0002.md`，无 Lean 那一趟）：claim-1 的
    `disclaimer` 是『文献交叉比对，不构成证明』—— 这句在全仓代码里不存在（受控的只有「数值交叉验证，
    不构成证明」与「逐行审阅过的证明，未经机器检查」）。此前这条判据只查"非空"，于是自造声明一路
    写库、一路渲染进 PDF。

    为什么"近义就行"不成立：那句声明是受控字符串，下游按它逐字对口径（H 的采信规则、报告里的分档
    统计、读者看到的"这一档凭什么"）—— 换一句作者自己愿意承担的话，等于把受控承诺换掉了，而没有
    任何读数会响（FC-03）。
    两件事一起钉：受控那句必须干净；近义那句必须报 `uncontrolled_disclaimer`。反负控：判据必须用
    `doc_tools` 里那两个常量（唯一来源），不是在本判据里手打一份。"""
    from agentflow import claimanatomy as CA
    from agentflow.tools import doc_tools as DT

    def _codes(ek: str, disc: str) -> set[str]:
        c = {"claim_id": "c1", "section": "1", "text": "数值上支持 P。",
             "evidence_kind": ek, "citations": ["exp:0000"],
             "disclaimer": disc, "is_negative": False}
        res = CA.validate_claim(c)
        issues = getattr(res, "issues", None)
        if issues is None:
            issues = res if isinstance(res, list | tuple) else []
        return {i.code for i in issues}

    assert "uncontrolled_disclaimer" not in _codes("cross_check", DT.CROSS_CHECK_DISCLAIMER)
    assert "uncontrolled_disclaimer" not in _codes("proof_review", DT.PROOF_REVIEW_DISCLAIMER)
    # 档与声明必须配对：拿错那一档的声明也要报（否则"受控"只是一句话）
    assert "uncontrolled_disclaimer" in _codes("cross_check", DT.PROOF_REVIEW_DISCLAIMER)
    for variant in ("文献交叉比对，不构成证明", "数值交叉验证，仅供参考",
                    DT.CROSS_CHECK_DISCLAIMER + "。"):
        assert "uncontrolled_disclaimer" in _codes("cross_check", variant), variant
        assert "missing_disclaimer" not in _codes("cross_check", variant), variant


# ============================================================ 7. 稿子的「阅读须知」
def _levels_named_in(text: str) -> set[str]:
    """一段说明文字里以 `` `等级` `` 形态点到的证据等级集合（只看词表里那些名字）。"""
    from agentflow import schema as _S

    return {k for k in _S.EVIDENCE_KINDS if f"`{k}`" in text}


def test_the_rendered_paper_lists_every_evidence_level() -> None:
    """判据（2026-10-13，无 Lean T2 的真机）：稿子的「阅读须知」必须列全证据等级。

    真机现场（`projects/p6t2-research-20261012b/documents/0002.md`，无 Lean 那一趟）：第 11 行逐字写着
    "证据等级只有三档"，只列了 `proof` / `cross_check` / `heuristic`；而同一份稿子第 19–24 行的统计表
    里 `proof_review` 一行赫然在目 —— 自相矛盾，而且方向恰好是最坏的那个：没有 Lean 的用户读到它，
    会以为"逐行审阅过的证明"这一档不存在，而那一档正是他这个模式下唯一能承载「定理 / 证明」的凭据。

    根因是渲染函数手写了"三档"与那三个名字，而统计表按 `schema.EVIDENCE_KINDS` 出行。现在第 0 节
    也从词表现算，所以判据钉的是"两处同源"：第 0 节点名的等级集合必须等于 `S.EVIDENCE_KINDS`，且
    `proof_review` 那句声明必须在读者能看到的地方（读者要读得到"这一档凭什么"）。"""
    from agentflow import schema as S
    from agentflow.tools import doc_tools as DT

    text = DT.render_markdown({"doc_id": "0001", "kind": "paper", "title": "t",
                               "status": "draft", "claims": []})
    head = text.split("## 1.", 1)[0]
    assert _levels_named_in(head) == set(S.EVIDENCE_KINDS), (
        "第 0 节没列全证据等级：", sorted(set(S.EVIDENCE_KINDS) - _levels_named_in(head)))
    assert DT.PROOF_REVIEW_DISCLAIMER in head, (
        "第 0 节没有 `proof_review` 那句声明 ⇒ 读者看不出这一档凭什么（无 Lean 模式的正题）")
    # 统计表那一半照旧按词表出行（两处同源 ⇒ 自相矛盾这种形态不会再出现）
    table = text.split("## 1.", 1)[1].split("## 2.", 1)[0]
    assert _levels_named_in(table) == set(S.EVIDENCE_KINDS), sorted(_levels_named_in(table))

    # 反负控：把某一档从说明里拿掉 ⇒ 同一把尺子必须报出来（否则这条判据恒真）
    crippled = head.replace("`proof_review`", "`某档`")
    assert _levels_named_in(crippled) != set(S.EVIDENCE_KINDS), "反负控失效：拿掉一档却没报"


# ============================================================ 8. 收工门
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
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    rep = _Rep()
    CL._check_load_bearing(rep, st)
    assert rep.status["load_bearing"] == "pass", rep.status
    assert "disabled" not in rep.readings["load_bearing"]
