"""R1-A1 现状读数（只读）：三个入口上，D 的 `self.llm` 到底是什么对象。

口径：照生产装配路径造 D（`host.build_role_registry` 的工厂），不自己 new 一个假的装配层。
工作区建在系统临时目录，不碰仓库数据面。
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

sys.path.insert(0, r"D:\Incubator\agentflow\src")
from agentflow import host as H  # noqa: E402
from agentflow.agent_d import AgentD  # noqa: E402
from agentflow.llmseam import LlmSeam  # noqa: E402
from agentflow.store import Store  # noqa: E402


class _Reply:
    ok = True
    text = '{"analysis": "a", "conclusion": "c", "suggestions": [], "confidence": "low"}'
    tokens_in = 1
    tokens_out = 1
    error_detail = ""
    tool_calls: tuple = ()


class _FakeGateway:
    """真 `LlmSeam` 的替身后端（缝自己那层逻辑照跑：`ask` → `_land` → 记事件）。"""

    class spec:
        model = "fake-model"

    def complete(self, prompt, *, scope="", system=None, max_tokens=None, tools=None):
        return _Reply()


class _FakeClient:
    """裸 client（有 `.complete`）—— 测试夹具与老路径用的形态。"""

    def complete(self, prompt):
        return _Reply.text


def _describe(tag: str, llm) -> None:
    print(f"  {tag:22s} type={type(llm).__name__:12s} is_none={llm is None!s:5s} "
          f"has_complete={hasattr(llm, 'complete')!s:5s} callable={callable(llm)!s:5s} "
          f"has_ask={hasattr(llm, 'ask')!s:5s} wired={getattr(llm, 'wired', '—')}")


EV = {"question": "q", "claims": []}
VERDICT = {"confidence": "low", "criteria": [], "hits": {}, "degree": 0,
           "verified_count": 0, "contradictions": []}


def _compose_reading(tag: str, d) -> None:
    d.last_tool_errors = []
    analysis, conclusion, suggestions, llm_used = d._compose(dict(EV), dict(VERDICT))
    print(f"    {tag:22s} llm_used={llm_used!s:5s} last_tool_errors={d.last_tool_errors}")


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="r1a1_status_"))
    st = Store(tmp / "ws")
    st.init()
    root = pathlib.Path(st.root)

    print("== (a) run-agent 那条路（`host.wired_llm_conductor`，默认 semantic_review/attack_reasoning 都关）==")
    wiring = H.wired_llm_conductor(st, loops={}, session_root=root, sid="t", providers=[object()])
    cond = wiring["conductor"]
    inner = getattr(getattr(cond, "backend", None), "inner", None)
    print(f"    conductor.backend={type(getattr(cond, 'backend', None)).__name__} "
          f"inner={type(inner).__name__} 角色表={sorted(getattr(inner, 'registry', {}) or {})}")
    d_a = inner.resolve("D") if inner is not None else None
    _describe("D.llm", getattr(d_a, "llm", None))
    _compose_reading("_compose", d_a)

    print("\n== (b) `wired_conductor(store, llm=<标准缝>)`：把公共缝交给装配层那条入口 ==")
    seam = LlmSeam(role="D", session_root=root, gateway=_FakeGateway(), sid="t")
    reg_b = H.build_role_registry(st, llm=seam, providers=[object()])
    d_b = reg_b["D"][1](store=st)
    _describe("D.llm", d_b.llm)
    _compose_reading("_compose", d_b)

    print("\n== (b2) 装配层给的是『没接线的缝』（无 key）时同上 ==")
    seam_off = LlmSeam.for_role("D", session_root=root, from_env=False)
    reg_b2 = H.build_role_registry(st, llm=seam_off, providers=[object()])
    d_b2 = reg_b2["D"][1](store=st)
    _describe("D.llm", d_b2.llm)
    _compose_reading("_compose", d_b2)

    print("\n== (c) 测试夹具（`AgentD(..., llm=<裸 client>)` / `llm=None`）==")
    d_c = AgentD(st, config={}, llm=_FakeClient())
    _describe("D.llm", d_c.llm)
    _compose_reading("_compose", d_c)
    d_c2 = AgentD(st, config={}, llm=None)
    _describe("D.llm", d_c2.llm)
    _compose_reading("_compose", d_c2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
