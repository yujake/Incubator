"""T3-H 的判据：主控真的派得出去（依据 `draft/30` §T3-H，落点 `agentflow.host`）。

这一组回答四个问题，每个都有正控 + 注入负控：
  ① 角色登记表该覆盖谁、不该覆盖谁（三态：`no_provider` ≠ `wired`）；
  ② 接了线之后，一次 `summon` 是不是真的跑到了角色实现（`outcome="ok"`）；
  ③ 台账能不能重建 M 的派活序列（`called_by="M"`、`verify_tasks()` 为空）；
  ④ 默认仍然零 LLM 调用，且工厂用的是传进来的那个 store。
"""

from __future__ import annotations

import pathlib

from pathlib import Path

import pytest

from agentflow import schema as S
from agentflow import host
from agentflow.agent_c import AgentC
from agentflow.conductor import Conductor
from agentflow.providers import Candidate
from agentflow.store import Store


class _FakeLLM:
    """被调用就抛的假 LLM：用来证明“构建期一次都不许调用它”。"""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *a, **kw):  # pragma: no cover - 只在被误用时走到
        self.calls += 1
        raise AssertionError("构建期不许调用 LLM")

    def complete(self, *a, **kw):  # pragma: no cover
        self.calls += 1
        raise AssertionError("构建期不许调用 LLM")


@pytest.fixture(autouse=True)
def _no_model_key(monkeypatch):
    """默认把模型 key 清掉：这一组判据要的是「确定」的接线态。

    为什么必须这么做（2026-10-03，`draft/37` §83）：B 的抽取器现在按「有没有 key」在
    `LLMExtractor` / `RuleExtractor` 之间选 —— 开发机上恰好配了 key 时，「没 key ⇒ 规则档」
    这类断言就会随机变红。要 key 的用例自己 `monkeypatch.setenv` 即可。
    """
    monkeypatch.delenv("AGENTFLOW_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("AGENTFLOW_MODEL_BASE_URL", raising=False)


def _store(tmp_path: Path, name: str = "ws") -> Store:
    st = Store(tmp_path / name)
    st.init()
    return st


def _pick_action(role: str) -> str:
    """该角色第一个没有必填参数的动作（判据里不写死动作名，免得随设计漂移）。"""
    from agentflow import capabilities as CAP

    for spec in CAP.actions_for(role):
        if not (spec.params or {}).get("required"):
            return spec.action
    raise AssertionError(f"{role} 没有无必填参数的动作 —— 本判据需要换一个用法")


# ---------------------------------------------------------------- ① 登记表与三态

def test_wiring_writes_the_profiles_file_into_the_workspace(tmp_path: pathlib.Path):
    """判据（`draft/37` §109）：每次接线都把画像文件落到工作区根（可查阅）。"""
    from agentflow import agent_prompts as AP
    from agentflow import host as host_mod

    ws = tmp_path / "ws"
    ws.mkdir()
    st = Store(ws)
    st.init()
    out = host_mod.wired_llm_conductor(st, session_root=ws, sid="t", max_steps=1,
                                       usd_budget=1.0, workspace_root=str(ws))
    path = ws / AP.PROFILES_FILE
    assert path.is_file(), "画像文件没写进工作区根"
    text = path.read_text(encoding="utf-8")
    assert "## M：" in text and "## A：" in text, "画像文件里没有角色小节"
    assert any("画像文件" in str(n) for n in out.get("notes", [])), out.get("notes")


def test_registry_covers_all_roles_and_only_factories(tmp_path: Path):
    """正控：给了 providers ⇒ 恰好 A–H，且每项是 `("factory", fn)`。"""
    st = _store(tmp_path)
    reg = host.build_role_registry(st, providers=[object()])
    assert set(reg) == set(S.ROLES), sorted(reg)
    for role, entry in reg.items():
        kind, fn = entry
        assert kind == "factory", f"{role} 的登记项必须是工厂（类会被 backend 明确拒绝）"
        assert callable(fn)


def test_registry_omits_a_without_providers_and_says_why(tmp_path: Path):
    """负控：没给 providers ⇒ A 不进表，且状态如实是 `no_provider`（不许假装接了线）。"""
    st = _store(tmp_path)
    reg = host.build_role_registry(st, providers=None)
    assert "A" not in reg, "没给检索后端时 A 不许进登记表"
    assert set(reg) == set(S.ROLES) - {"A"}
    st_map = host.wiring_status(st, providers=None)
    assert st_map["A"] == "no_provider"
    assert all(st_map[r] == "wired" for r in S.ROLES if r != "A")
    assert set(st_map) == set(S.ROLES), "接线态必须逐角色给，不许只给接线的那些"


# ---------------------------------------------------------------- ② 真的派得出去

def test_wired_conductor_really_dispatches_a_task(tmp_path: Path):
    """正控：接一根线，`summon` 真的跑到角色实现（`outcome="ok"`），且台账干净。"""
    st = _store(tmp_path)
    c = host.wired_conductor(st, providers=[object()])
    action = _pick_action("C")
    res = c.summon(role="C", action=action, params={}, input_key=f"judge:{action}")
    assert res.status == "done", (res.status, res.outcome, res.refusal_reason)
    assert res.outcome == "ok", (res.outcome, res.error, res.detail)
    assert res.refusal_reason is None
    rows = st.rows("tasks")
    assert [r.get("called_by") for r in rows] == ["M"], rows
    assert c.verify_tasks() == [], c.verify_tasks()


def test_multi_step_ledger_rebuilds_the_sequence(tmp_path: Path):
    """P10 第 ③ 条：连续多轮派活，台账能按 `task_id` 重建成 M 的决策序列。

    选 C/D/E/H 四个角色：它们是实测里有无必填参数动作的那几个
    （G 没有 ⇒ 它的派活要带参数，本合同不需要牵扯那一层）。
    """
    st = _store(tmp_path)
    c = host.wired_conductor(st, providers=[object()])
    roles = ("C", "D", "E", "H")
    for role in roles:
        action = _pick_action(role)
        res = c.summon(role=role, action=action, params={},
                       input_key=f"judge:{role}:{action}")
        # 实测（2026-09-29，空工作区）：这四个动作都落 outcome="ok"，
        # 所以这里钉的是"真的跑完了"，不是"没被拒就行"。
        assert res.outcome == "ok", (role, action, res.outcome, res.error, res.detail)
    rows = [r for r in st.rows("tasks") if r.get("role") in roles]
    assert len(rows) == len(roles), rows
    assert [r.get("called_by") for r in rows] == ["M"] * len(roles)
    ids = [str(r.get("task_id")) for r in rows]
    assert ids == sorted(ids) and len(set(ids)) == len(ids), f"台账序列不单调或重复：{ids}"
    assert [r.get("role") for r in rows] == list(roles), "台账顺序应与派活顺序一致"
    assert c.verify_tasks() == [], c.verify_tasks()


def test_unwired_conductor_refuses_honestly(tmp_path: Path):
    """负控：不接线 ⇒ `done/refused/not_wired`（不是异常、也不是"成功"）。"""
    st = _store(tmp_path)
    c = Conductor(st, backend="local")
    res = c.summon(role="C", action=_pick_action("C"), params={}, input_key="judge:unwired")
    assert (res.status, res.outcome, res.refusal_reason) == ("done", "refused", "not_wired")
    assert "C" in str(res.detail), res.detail


def test_refusal_is_per_role_not_whole_table(tmp_path: Path):
    """负控：只缺 A 的后端时，A 被拒而其余角色照常工作（拒绝是逐角色的）。"""
    st = _store(tmp_path)
    c = host.wired_conductor(st, providers=None)
    bad = c.summon(role="A", action=_pick_action("A"), params={}, input_key="judge:A")
    good = c.summon(role="C", action=_pick_action("C"), params={}, input_key="judge:C")
    assert bad.refusal_reason == "not_wired", (bad.outcome, bad.detail)
    assert good.outcome == "ok", (good.outcome, good.error)


def test_class_entry_is_refused_by_the_backend(tmp_path: Path):
    """负控（注入）：把登记项改成 `("class", AgentC)` ⇒ 必须被 backend 拒（不许猜依赖）。"""
    st = _store(tmp_path)
    c = Conductor(st, registry={"C": ("class", AgentC)}, backend="local")
    res = c.summon(role="C", action=_pick_action("C"), params={}, input_key="judge:class")
    assert (res.status, res.outcome, res.refusal_reason) == ("done", "refused", "not_wired")
    assert "类" in str(res.detail), res.detail


# ---------------------------------------------------------------- ③ 默认零调用与工厂纪律

def test_default_llm_is_none_and_build_time_never_calls_it(tmp_path: Path):
    """正控 + 自检：`llm=None` ⇒ 角色拿到的 llm 是 None；传假 LLM ⇒ 构建期零调用。"""
    st = _store(tmp_path)
    reg = host.build_role_registry(st, providers=[object()], llm=None)
    for role in ("A", "C", "D", "E", "F", "G", "H"):
        obj = reg[role][1](store=st)
        assert getattr(obj, "llm", None) is None, f"{role} 的 llm 应为 None"

    fake = _FakeLLM()
    reg2 = host.build_role_registry(st, providers=[object()], llm=fake)
    for role in ("A", "C", "D", "E", "F", "G", "H"):
        reg2[role][1](store=st)
    assert fake.calls == 0, "构建角色时调用了 LLM（默认关闭不许被破坏）"
    # B 的 LLM 走 extractor 协议：给了 llm 就换成 LLMExtractor
    b = reg2["B"][1](store=st)
    assert type(b.extractor).__name__ == "LLMExtractor", type(b.extractor).__name__
    b_none = reg["B"][1](store=st)
    assert type(b_none.extractor).__name__ == "RuleExtractor"


def test_d_gets_a_seam_by_availability_not_by_a_role_switch(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """`R1-B-x`（裁定 3）：D 的缝由"这次运行有没有模型"决定，不由角色开关决定。

    裁决 6 的口径是"接全部在用动作"，不是"可选接" ⇒ D 不该像 F 那样等一个
    `--attack-reasoning` 才拿得到缝。三态与 fail-open 由 `model_json_call` 的
    `reading.state`（`used`/`failed`/`not_wired`/`unknown_object`）负责。

    两半都要钉：
    - 有模型 ⇒ 建缝（否则 D 的精修永远 `not_wired`，"有模型却不接线"读不出来）；
    - 没有模型 ⇒ 不建缝（无条件建会把"没接线"写成"接上了但没答"——那正是
      本项目反复防的那种假话）。
    """
    st = _store(tmp_path)
    seen: list[str] = []
    captured: dict = {}
    real = host.build_role_registry

    def _spy(store_, **kw):
        captured.clear()
        captured.update(kw)
        return real(store_, **kw)

    def _factory(role: str):
        seen.append(role)
        return _FakeLLM()

    monkeypatch.setattr(host, "build_role_registry", _spy)
    monkeypatch.setattr(host, "_model_key_present", lambda *_a, **_k: True)
    host.wired_llm_conductor(st, providers=[object()], seam_factory=_factory, loops={})
    assert "D" in (captured.get("llm_by_role") or {}), (
        f"有模型时 D 没被登记进逐角色缝表（裁定 3）：{sorted((captured.get('llm_by_role') or {}))}")
    assert "D" in seen, f"缝工厂没被要求造 D 的缝：{seen}"

    seen.clear()
    monkeypatch.setattr(host, "_model_key_present", lambda *_a, **_k: False)
    host.wired_llm_conductor(st, providers=[object()], seam_factory=_factory, loops={})
    assert "D" not in (captured.get("llm_by_role") or {}), "没有模型时不许把 D 登记成接线"
    assert "D" not in seen, f"没有模型却造了 D 的缝：{seen}"


def test_attack_reasoning_is_opt_in_and_the_default_stays_deterministic(tmp_path: Path):
    """判据（`draft/39` §6.32 的 D42b）：F 的攻坚推理是显式接线，默认仍确定性。

    真机读数（T2 第 12 趟 `projects/p6n-research-from-zero`）：D42 把"有缝就推理"那一支
    修好了，可 `attack_plans.history` 那一条依旧逐字写着"本框架尚未接线自动推理" ——
    因为这条路径上 `llm_by_role` 只登记了 H，`specs/f.py::_build` 拿到的 `d.llm` 是 None。
    缝从来没到过 F 手上，那才是真机那一句的根因。

    两半都要钉：打开时 F 拿得到缝（否则能力还是够不着）；关着时 F 仍是 None 且装配读数
    如实说"未接线"（不能为了让它能跑，就把"默认确定性"这条纪律悄悄改掉）。
    """
    st = _store(tmp_path)
    seam = _FakeLLM()

    off = host.wired_llm_conductor(st, session_root=tmp_path, sid="t-off", max_steps=1,
                                   workspace_root=tmp_path, attack_reasoning=False)
    notes_off = " ".join(str(x) for x in off["notes"])
    assert "F 的攻坚推理：未接线" in notes_off, notes_off
    reg_off = host.build_role_registry(st, providers=[object()])
    assert reg_off["F"][1](store=st).llm is None, "默认档下 F 不该拿到缝"

    on = host.wired_llm_conductor(st, session_root=tmp_path, sid="t-on", max_steps=1,
                                  workspace_root=tmp_path, attack_reasoning=True,
                                  seam_factory=lambda role: seam)
    notes_on = " ".join(str(x) for x in on["notes"])
    assert "F 的攻坚推理：接线" in notes_on, notes_on
    reg_on = host.build_role_registry(st, providers=[object()], llm_by_role={"F": seam})
    f = reg_on["F"][1](store=st)
    assert f.llm is seam, "打开 --attack-reasoning 之后 F 必须真的拿到那个缝"


def test_factory_uses_the_store_it_is_given(tmp_path: Path):
    """负控（注入）：工厂必须用传进来的 store —— 捕获外层 store 会静默写错库。"""
    st1 = _store(tmp_path, "one")
    st2 = _store(tmp_path, "two")
    reg = host.build_role_registry(st1, providers=[object()])
    obj = reg["C"][1](store=st2)
    assert Path(obj.store.root).resolve() == Path(st2.root).resolve(), obj.store.root
    # 单例按 store 分：同一个库里两次取到同一个对象，不同库取到不同对象
    assert reg["C"][1](store=st2) is obj
    assert reg["C"][1](store=st1) is not obj


def test_cross_links_are_bound_at_construction_time(tmp_path: Path):
    """结构不变式：D 手里的 C、F 手里的 E 就是登记表里那两个实例（不是各建各的）。"""
    st = _store(tmp_path)
    reg = host.build_role_registry(st, providers=[object()])
    c = reg["C"][1](store=st)
    e = reg["E"][1](store=st)
    assert reg["D"][1](store=st).c is c
    assert reg["F"][1](store=st).e is e


def test_instance_axis_gives_one_object_per_instance(tmp_path: Path):
    """实例轴（2026-09-30）：显式实例标签 ⇒ 每标签一个对象；不给 ⇒ 仍是单例。

    "并发几个 B 一起读一批文献"要的是 N 个对象：同一个对象被 N 个线程共用，
    实例状态（actor、recorder、抽取器上的会话）会互相串味 —— 那样"并发"只是
    把串行改成了更危险的形态。所以实例轴必须一路走到"对象分家"这一层。

    三条一起断言，缺一条都不算：
    ① 同一标签两次取到同一个对象（幂等，不然每次 summon 都新建一个）；
    ② 不同标签取到不同对象；
    ③ 不给标签仍然是单例（既有的 `test_factory_uses_the_store_it_is_given` 语义）。
    """
    st = _store(tmp_path)
    reg = host.build_role_registry(st, providers=[object()])
    b1 = reg["B"][1](store=st, instance="1")
    assert reg["B"][1](store=st, instance="1") is b1
    b2 = reg["B"][1](store=st, instance="2")
    assert b2 is not b1
    assert reg["B"][1](store=st) is reg["B"][1](store=st)
    assert reg["B"][1](store=st) is not b1
    # actor 带上实例标签（A/D/E/F 有 actor= 形参）：数据行才分得清是谁写的
    e1 = reg["E"][1](store=st, instance="7")
    assert getattr(e1, "actor", "") == "agent-E-7", getattr(e1, "actor", "")


# ---------------------------------------------------------------- ④ 工具层接线

def test_semantic_review_seam_goes_only_to_h(tmp_path: Path):
    """负控（真机抓到的）：给 H 的语义判据缝不许被塞给别的角色。

    实测（`temp/live-collab-fanout-20260930-144422.txt`）：`wired_llm_conductor(..., semantic_review=True)`
    把 H 的 `LlmSeam` 当成了所有角色共用的 `llm=` ⇒ `agent_b` 拿它去造
    `LLMExtractor`，而缝不是抽取器 client ⇒ `TypeError: client 必须提供 complete(prompt: str) -> str 方法`。
    更糟的是那句错被 `LocalBackend.resolve` 的 `except TypeError` 兜住，
    最后报出来的是误导性的"factory(B) 需要一个 store" —— 于是 3 个 B 实例
    全部 `failed`，而错误信息指着完全不相干的地方。

    判据两条：① 开了 `semantic_review` 之后 B/E 仍然能正常构造并被召唤；
    ② B 的抽取器仍是 `RuleExtractor`（说明它拿到的 llm 是 None，不是那个缝）。
    """
    from agentflow.llmseam import LlmSeam
    from agentflow.tools.conductor_tools import reset_cache

    st = _store(tmp_path)

    class _G:
        spec = type("S", (), {"model": "m", "api_key": "k"})()

        def complete(self, prompt: str, **kw):
            return type("R", (), {"ok": False, "text": "", "tokens_in": 0, "tokens_out": 0,
                                  "error_detail": "no", "error_kind": "x"})()

    def seam(role: str) -> LlmSeam:
        return LlmSeam(role=role, session_root=st.root, gateway=_G(), price=(0.0, 0.0), sid="t")

    reset_cache()
    wiring = host.wired_llm_conductor(st, session_root=st.root, sid="t", max_steps=3,
                                      workspace_root=str(st.root), seam_factory=seam,
                                      semantic_review=True)
    reg = host.build_role_registry(st, providers=[object()], llm_by_role={"H": seam("H")})
    b = reg["B"][1](store=st)
    assert type(b.extractor).__name__ == "RuleExtractor", type(b.extractor).__name__
    c = wiring["conductor"]
    for role, action in (("B", "run_once"), ("E", "list_experiments")):
        res = c.summon(role, action, {}, by="M", instance="probe-1")
        assert res.outcome == "ok", (role, res.status, res.outcome, res.error)


def test_a_factory_that_raises_typeerror_is_not_masked(tmp_path: Path):
    """负控（`resolve` 的调用方式）：工厂内部抛的 `TypeError` 不许被吞掉换成别的调用。

    旧写法是 `try: value(store=…, instance=…) except TypeError: …` —— 它把
    "工厂不接受这个参数"与"工厂自己炸了"混成一件事。真机里正是这个吞法
    把 `client 必须提供 complete(...)` 变成了一句"需要一个 store"。
    现在按签名决定怎么调：工厂炸了就是它炸了，错误原文要原样出来。
    """
    from agentflow.conductor import LocalBackend

    def boom(*, store=None, instance=""):
        raise TypeError("工厂内部的真错：client 必须提供 complete(prompt: str) -> str 方法")

    be = LocalBackend({"B": ("factory", boom)})
    be.store = _store(tmp_path)
    with pytest.raises(TypeError) as err:
        be.resolve("B", "b1")
    assert "工厂内部的真错" in str(err.value), err.value


def test_selftest_passes():
    """`host.selftest()` 自己必须绿（它是这一层的门，不能被判据绕过）。"""
    assert host.selftest() == 0


def test_a_factory_wires_a_downloader_only_when_the_config_says_so(tmp_path: Path):
    """A 的工厂要按 `agent_a.download` 给 downloader（验收 P1 撞出来的缺口）。

    第一版只给了 providers ⇒ A 能检索却一条全文都下不下来，文献行的
    `download.error` 逐条写 `no_downloader`；而 `no_pdf_url` 是另一回事
    （"这篇本来没有开放获取 PDF"）。两种"没下来"必须分得开 ——
    所以这里正控（配了 download ⇒ 有下载器）与负控（显式关掉 ⇒ None）都要测。
    """
    st = _store(tmp_path)
    on = host.build_role_registry(st, providers=[object()],
                                  config={"agent_a": {"download": True},
                                          "download": {"retries": 1}})
    off = host.build_role_registry(st, providers=[object()],
                                   config={"agent_a": {"download": False}})
    assert getattr(on["A"][1](store=st), "downloader", None) is not None, \
        "配了 download 就必须有下载器"
    assert getattr(off["A"][1](store=st), "downloader", None) is None, \
        "显式关掉时必须是 None（不是'忘了传'）"


def test_a_factory_is_omitted_entirely_without_providers(tmp_path: Path):
    """负控（反真空）：没有 providers 时 A 根本不进登记表 —— 没有"半接线的 A"。"""
    st = _store(tmp_path)
    reg = host.build_role_registry(st, providers=None, config={"agent_a": {"download": True}})
    assert "A" not in reg


def test_wired_tool_registry_keeps_m_surface_orchestration_only(tmp_path: Path):
    """接了线的工具层：M 的面 = 编排面 11 件 + 文件面白名单 6 件，一件领域工具都没有。

    ## 这条判据改过两次，每次都是真机读数逼出来的

 2026-10-02（`draft/37` §38，用户裁定）：给 M 只读四件 + `fs.write`。
    §37 那一趟 23 步里 15 步在猜"盘上到底有没有论文"，最后交不出报告 ——
    M 缺的不是判断力，是眼睛与笔（它当时一件 `fs.*` 都没有）。

 2026-10-03（`draft/37` §57，用户追加）：再给一件 `fs.edit`。
    §56 第八趟真机：主控知道该改哪三处、也找准了逐字文本，然后试图用 `fs.write`
    把整份 26 KB 的 `main.tex` 重写一遍 —— 回复被输出额度（8192 token）截断在字符串中间
    （步 27/30 的 `text_len` 是 26110 / 26134），连续三次坏 JSON ⇒ `bad_json_limit`。
    也就是说：`fs.write` 单独不足以改大文件，而"整文件覆盖"本来也是更危险的那条路。
    `fs.edit`（锚定替换，一次一处、不命中就拒）输出量与改动量成正比，
    因此比 `fs.write` 更安全 —— "不可逆"那条理由对它不适用。

    红线仍然在，只是又换了口径：从"M 不碰盘"→「M 有眼睛和笔」→
    「M 有眼睛、有笔、能改该改的那一处，但不碰知识表、不做检索、不删东西、不挪东西」。
    所以这条判据现在守三件事：

    1. 白名单六件必须在（`fs.list` / `fs.read` / `fs.search` / `fs.stat` / `fs.write` / `fs.edit`）；
    2. `fs.delete` / `fs.move` 两件都不许有（一个真删、一个换位置，都是不可逆的）；
    3. `table.*` / `prov.*` / `search.*` 一件都不许有（知识表与检索仍然是 M 的禁区）。
    """
    st = _store(tmp_path)
    built = host.wired_tool_registry(st, providers=[object()])
    reg = built.registry
    m_tools = sorted(t.name for t in reg.for_role("M"))
    # 计数随工具面一起动：18 → 19 是 `conductor.board`（工作项板，业主 A1=甲 之后 S1b 加的；
    # 它的 `roles=("M",)` 落在 M 的编排面上）。这一条当时漏改 —— 2026-10-08 深夜 S1d 审计时
    # 实测 HEAD 上就有一条红（`assert 19 == 18`），补在这里并把出处写清楚。
    assert len(m_tools) == 19, m_tools
    assert "conductor.board" in m_tools, m_tools
    assert "conductor.summon_many" in m_tools, m_tools
    assert "conductor.closing" in m_tools, m_tools
    # ① 文件面白名单六件（§38 + §57 两次裁定）
    for name in ("fs.list", "fs.read", "fs.search", "fs.stat", "fs.write", "fs.edit"):
        assert name in m_tools, (name, m_tools)
    # ② 不可逆的两件一件都不许有
    for name in ("fs.delete", "fs.move"):
        assert name not in m_tools, (name, m_tools)
    # ③ 知识表与检索仍是禁区
    assert not [n for n in m_tools if n.startswith(("table.", "prov.", "search."))], m_tools
    # 编排面那 12 件照旧 + `conductor.board`（同上，S1b 加的）⇒ 13
    assert len([n for n in m_tools if n.startswith("conductor.")]) == 13, m_tools


# ---------------------------------------------------------------- ⑥ A 的文献检索真的通


class _OneCandidateProvider:
    """确定性检索替身：固定一篇候选，记下被问了什么（不联网、无随机）。"""

    name = "stub-one"

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def search(self, topic, mode, description, limit):
        self.calls.append((topic, mode, description, limit))
        return [Candidate(
            title="The extremal process of branching Brownian motion",
            year=2012,
            doi="10.1007/s00440-012-0464-x",
            authors=["L.-P. Arguin", "A. Bovier", "N. Kistler"],
            venue="Probability Theory and Related Fields",
            type_code="J",
            summary="分支布朗运动的极值过程。",
            pdf_url=None,          # 没有开放获取 PDF：这件事本身要如实落进 download
            landing_url=None,
            language="en",
            provider="stub-one",
            raw={"provider": "stub-one"},
        )]


def test_the_sources_a_returns_can_be_registered_as_a_closed_dependency(tmp_path: Path):
    """`A 通关`的第三条腿：A 交回的来源必须能直接写进依赖表（goal 原话：台账与依赖表都留痕）。

    真机（`temp/live-a-roles-*.txt` 场景 II）里 G 就是这么做的：
    `dependencies/0000 used_by=main.tex:introduction kind=prior_art status=closed
    source_lit_id=0000`，而 `0000` 正是 A 那一次交回的 `lit_id`。
    这条离线判据把那条链钉住：`A.search_literature` → 取 `result_lit_ids[0]` →
    `G.register_dependency(source_lit_id=…)` ⇒ 依赖行是 `closed` 且指向那一行文献。
    没有它，"来源回来了"与"来源被引用了"这两件事可能各自为真、却接不上。
    """
    st = _store(tmp_path)
    provider = _OneCandidateProvider()
    c = host.wired_conductor(st, providers=[provider])

    res = c.summon(role="A", action="search_literature",
                   params={"topic": "branching Brownian motion extremal process"},
                   input_key="lit:bbm-extremal")
    assert res.outcome == "ok", (res.status, res.outcome, res.detail)
    lit_id = (res.payload or {}).get("result_lit_ids", [None])[0]
    assert lit_id, res.payload

    dep = c.summon(role="G", action="register_dependency",
                   params={"used_by": "main.tex:introduction", "kind": "prior_art",
                           "label": "The extremal process of branching Brownian motion",
                           "source_lit_id": lit_id, "status": "closed"},
                   input_key=f"dep:{lit_id}")
    assert dep.outcome == "ok", (dep.status, dep.outcome, dep.detail, dep.error)
    rows = st.rows("dependencies")
    assert len(rows) == 1, rows
    assert rows[0]["status"] == "closed", rows[0]
    assert rows[0]["source_lit_id"] == lit_id, rows[0]
    # 台账两处齐：A 那次召唤 + G 那次召唤
    roles = sorted(str(r.get("role")) for r in st.rows("tasks"))
    assert roles == ["A", "G"], roles
    assert c.verify_tasks() == [], c.verify_tasks()

    # 负控（实测撞到的真实形态）：`kind` 不在受控词表里时，工具层会拒 ——
    # 这条负控是"我第一版写了 kind=literature 就红了"留下来的：能力层的
    # `G.register_dependency.params.kind` 只是个 string（没有 enum），所以参数门放行、
    # 由工具层拒。拒得对（它如实写了词表），但两层口径不同这件事登记在 `draft/28` §203。
    bad = c.summon(role="G", action="register_dependency",
                   params={"used_by": "main.tex:introduction", "kind": "literature",
                           "label": "x"},
                   input_key=f"dep-bad:{lit_id}")
    assert bad.outcome == "refused", (bad.status, bad.outcome, bad.detail)
    assert "prior_art" in str(bad.detail), bad.detail
    assert len(st.rows("dependencies")) == 1, "被拒的那次一条都不许写"


def test_a_summoned_literature_search_really_lands_in_the_library(tmp_path: Path):
    """`A 通关`的集成判据：接上检索后端之后，一次带主题的召唤真的把文献查回库里。

    为什么单钉这一条：`wired_llm_conductor(providers=...)` 这个参数一直存在，
    但`run-agent` 从来没传过它 ⇒ `_Builder.status()` 把 A 判成 `no_provider`、
    A 不进登记表 ⇒ 任何角色唤起 A 都落 `refused/not_wired`。真机实测
    （`draft/28` §201）：G 按协议唤起了 A，拿回来的是"A 没有接线"。
    也就是说 —— "缺文献证据就去找 A"这条最重要的协同边，在协同运行里从来没接上过。

    这条判据钉两件互相独立的事：
    ① 接了后端时，`A.search_literature(topic=…)` 可召唤、真的问到了 provider、
       文献进了 `literature`，请求行上留着是谁提的；
    ② 没接后端时同一句话落 `refused/not_wired` 且零写入（三态：没查成 ≠ 没有文献）。
    """
    st = _store(tmp_path)
    provider = _OneCandidateProvider()
    c = host.wired_conductor(st, providers=[provider])

    res = c.summon(role="A", action="search_literature",
                   params={"topic": "branching Brownian motion extremal process"},
                   input_key="lit:bbm-extremal")

    assert (res.status, res.outcome) == ("done", "ok"), (res.status, res.outcome, res.detail)
    assert provider.calls, "provider 一次都没被问到 ⇒ 没有真的检索"
    assert provider.calls[0][0] == "branching Brownian motion extremal process"
    rows = st.rows("literature")
    assert len(rows) == 1, rows
    assert rows[0]["title"] == "The extremal process of branching Brownian motion"
    assert rows[0]["doi"] == "10.1007/s00440-012-0464-x"
    assert rows[0]["path"] is None, "没有 PDF URL ⇒ path 为空（不是编一个路径）"
    req = st.rows("search_requests")
    assert len(req) == 1 and req[0]["submitted_by"] == "agent-A"
    assert req[0]["result_lit_ids"] == [rows[0]["lit_id"]], "来源必须挂在这条请求上"
    # 召唤方拿到的是可读的来源，而不只是一句"跑完了"
    payload = res.payload if isinstance(res.payload, dict) else {}
    lit_back = payload.get("literature") or []
    assert lit_back and lit_back[0]["lit_id"] == rows[0]["lit_id"], payload
    assert c.verify_tasks() == [], c.verify_tasks()

    # ---- 负控：同一句话，只是没有检索后端
    st2 = _store(tmp_path, "ws2")
    c2 = host.wired_conductor(st2, providers=[])
    res2 = c2.summon(role="A", action="search_literature",
                     params={"topic": "branching Brownian motion extremal process"},
                     input_key="lit:bbm-extremal")
    assert (res2.status, res2.outcome, res2.refusal_reason) == ("done", "refused", "not_wired")
    assert st2.rows("literature") == [], "没接线时不许留下任何文献行"
    assert st2.rows("search_requests") == [], "没接线时一条请求都不该入队"


# ------------------------------------------------- ⑤ B 的抽取器接线（`draft/37` §83）

class _SeamLike:
    """像 `LlmSeam`：有 `ask`、「没有」 `complete` —— 它不是抽取器 client。"""

    def __init__(self) -> None:
        self.calls = 0

    def ask(self, *a, **kw):  # pragma: no cover - 只在被误用时走到
        self.calls += 1
        raise AssertionError("构建期不许调用模型")


def test_b_extractor_uses_a_metered_model_client_when_a_key_is_configured(
        tmp_path: Path, monkeypatch):
    """正控（§83 的根因修复）：配了 key ⇒ B 拿到 `LLMExtractor`，且 client 是 modelclient 造的。

    为什么这条是「引文那条腿能不能通」的判据：`B.run_once` 在规则抽取器下「当场拒抽」
    （`R-56`：规则抽取器会把碎片当概念/关系），于是 `relations` 一行都不会有、逐字回验
    无处发生 —— 实测 `p5-run15` 就是 `relations` 0 行、`literature.processed=False`。
    """
    monkeypatch.setenv("AGENTFLOW_MODEL_API_KEY", "fixture-key-not-a-secret")
    st = _store(tmp_path)
    notes: list[str] = []
    reg = host.build_role_registry(st, providers=[object()], notes=notes)
    b = reg["B"][1](store=st)
    assert type(b.extractor).__name__ == "LLMExtractor", type(b.extractor).__name__
    assert b.extractor_is_fallback is False
    assert type(b.extractor.client).__name__ == "ModelClient", type(b.extractor.client).__name__
    assert any("max_tokens=8192" in n for n in notes), notes


def test_a_seam_is_not_mistaken_for_an_extractor_client(tmp_path: Path, monkeypatch):
    """负控（真机抓到的形态）：塞一个「缝」给 B 不许抛 `TypeError`。

    旧写法 `LLMExtractor(role_llm)` 对真实缝会当场抛（缝没有 `.complete`），而那句错曾被
    `LocalBackend.resolve` 的 `except TypeError` 兜成一句误导性的「需要一个 store」。
    现在的口径：认出来就记一条 note、改走正确的 client；构造期一次模型都不调。
    """
    monkeypatch.setenv("AGENTFLOW_MODEL_API_KEY", "fixture-key-not-a-secret")
    seam = _SeamLike()
    st = _store(tmp_path)
    notes: list[str] = []
    reg = host.build_role_registry(st, providers=[object()], llm_by_role={"B": seam},
                                   notes=notes)
    b = reg["B"][1](store=st)
    assert type(b.extractor).__name__ == "LLMExtractor", type(b.extractor).__name__
    assert any("缝不是抽取器 client" in n for n in notes), notes
    assert seam.calls == 0, "构建期调用了那个缝"


def test_without_a_key_b_refuses_to_extract_and_says_so(tmp_path: Path):
    """负控（三态）：没有 key ⇒ 规则档 + 一条说清的 note（不是静默地什么都不做）。"""
    st = _store(tmp_path)
    notes: list[str] = []
    reg = host.build_role_registry(st, providers=[object()], notes=notes)
    b = reg["B"][1](store=st)
    assert type(b.extractor).__name__ == "RuleExtractor", type(b.extractor).__name__
    assert b.extractor_is_fallback is True
    assert any("没有配置模型 key" in n for n in notes), notes


def test_run_agent_wiring_exposes_the_extractor_notes(tmp_path: Path):
    """正控（读数可见）：`wired_llm_conductor`（`run-agent` 那条路）把装配读数转出来。

    口径：读数是「B 实例被造出来」那一刻写的（惰性装配），所以判据先让主控真的召唤一次 B，
    再读 `wiring["notes"]` —— 这也正是运维会看到它的时机（召唤发生在跑的过程中）。
    """
    from agentflow.tools.conductor_tools import reset_cache

    st = _store(tmp_path)
    reset_cache()
    wiring = host.wired_llm_conductor(st, session_root=st.root, sid="t", max_steps=3,
                                      workspace_root=str(st.root))
    assert "notes" in wiring, wiring.keys()
    assert not any("B：" in n for n in wiring["notes"]), (
        "还没造过 B 就写了它的抽取器读数？那是装配期的谎话（画像文件那条 note 不算）")
    res = wiring["conductor"].summon("B", "run_once", {}, by="M")
    assert res.status == "done", (res.status, res.outcome, res.error)
    assert any("B：" in n for n in wiring["notes"]), wiring["notes"]
    # 负控（同一条读数的另一面）：没有 key 时它必须说清"会拒抽"，而不是沉默
    assert any("拒抽" in n or "LLMExtractor" in n for n in wiring["notes"]), wiring["notes"]
