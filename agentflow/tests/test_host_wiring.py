"""T3-H 的判据：主控真的派得出去（依据 `draft/30` §T3-H，落点 `agentflow.host`）。

这一组回答四个问题，每个都有正控 + 注入负控：
  ① 角色登记表该覆盖谁、不该覆盖谁（三态：`no_provider` ≠ `wired`）；
  ② 接了线之后，一次 `summon` 是不是真的跑到了角色实现（`outcome="ok"`）；
  ③ 台账能不能重建 M 的派活序列（`called_by="M"`、`verify_tasks()` 为空）；
  ④ 默认仍然零 LLM 调用，且工厂用的是传进来的那个 store。
"""

from __future__ import annotations

from pathlib import Path

from agentflow import schema as S
from agentflow import host
from agentflow.agent_c import AgentC
from agentflow.conductor import Conductor
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
    """接了线的工具层：M 的面仍然是那 10 件编排面工具，一件领域工具都没有。"""
    st = _store(tmp_path)
    built = host.wired_tool_registry(st, providers=[object()])
    reg = built.registry
    m_tools = sorted(t.name for t in reg.for_role("M"))
    assert len(m_tools) == 10, m_tools
    assert "conductor.summon_many" in m_tools, m_tools
    assert all(n.startswith("conductor.") for n in m_tools), m_tools
    # 领域工具不许出现在 M 的面上（P10 的红线在接线之后仍然成立）
    assert not [n for n in m_tools if n.startswith(("table.", "fs.", "prov."))], m_tools
