"""主控接线：把 A–H 接到 `LocalBackend`（依据 `draft/30` §T3-H）。

## 这一层解决什么

`conductor.summon` 是 M 唯一的派活动作，它把活交给"后端"。进程内那个后端
（`LocalBackend`）明确拒绝自动创建角色实例（构造依赖靠猜就等于静默少做事），
所以调用方必须给一张登记表。默认没人给 ⇒ 每次召唤都如实落
`refused/not_wired`（这是设计，不是缺陷：没接线就说没接线）。

这一层就是那张登记表的唯一装配点：按各角色实测的构造签名造工厂。
实测（2026-09-29，`temp/_probe_agent_construction.py`）：八个角色只给 `store`
就能自组装工具面（D 9 / E 6 / F 6 / G 63 / H 22 件，A/B/C 为 `None`），
所以这里不重复装配工具，只补两类真实依赖：

- `A` 需要 `providers`（检索的后端）—— 没给就不进登记表（不编造 provider 列表）；
- `B` 需要 `extractor` + `extract_text`；且 B 的签名里没有 `llm`：
  它的 LLM 走 extractor 协议（`LLMExtractor`），有 `llm` 时用它、没有时用 `RuleExtractor`。

## 它不是计划器（`draft/31` P10 的形式约束）

本模块不含计划 JSON schema、prompt 模板库、plan 解析器、重计划状态机，
也不决定"该派谁"。它只回答一件事：每个角色的实例怎么造出来。
"派谁、派什么"是 M 的工具调用序列。

## 三态纪律

`wiring_status()` 逐角色给 `"wired"` 或 `"no_provider"`。没有第三种"看起来能跑"：
没接线的角色在台账里落 `refused/not_wired`，而其余角色照常工作 ——
拒绝是逐角色的，不是整表失效。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from . import schema as S

#: 角色的接线态。刻意只有两格：`wired` 与"需要一个我没拿到的东西"。
WIRING_STATES: tuple[str, ...] = ("wired", "no_provider")

#: 登记项的形态（与 `conductor.LocalBackend.resolve` 的契约逐字对应）：
#: `("factory", fn)` 且 `fn(*, store=...)`。类是不允许的（backend 会明确拒绝）。
Factory = tuple[str, Callable[..., Any]]


def _root_of(store: Any) -> Path:
    """工作区根（与 `conductor_tools.conductor_for` 同一口径，好让两处缓存对齐）。"""
    return Path(getattr(store, "root", ".")).resolve()


class _Builder:
    """一次装配的上下文：按需建角色、同 (角色, store 根) 单例。

    单例不是优化：`D` 与 `F` 在构造期就被绑定了它们的邻居（`c=` / `e=`），
    如果每次召唤都新建一个 C，那么 D 手里的 C 与 M 直接召唤的 C 就是两个对象 ——
    两个对象各自持有会话状态，"谁能叫谁"这条结构就名存实亡了。
    """

    def __init__(self, *, llm: Any = None, providers: Any = None, extractor: Any = None,
                 config: Mapping[str, Any] | None = None,
                 workspace_root: str | Path | None = None) -> None:
        self.llm = llm
        self.providers = list(providers or [])
        self.extractor = extractor
        self.cfg: dict[str, Any] = dict(config or {})
        self.workspace_root = Path(workspace_root) if workspace_root else None
        self._made: dict[tuple[str, str], Any] = {}

    # ------------------------------------------------------------ 逐个角色

    def _cfg_for(self, role: str) -> dict[str, Any]:
        """该角色的配置段（`config["agent_c"]` 这类；没有就给空 dict）。"""
        seg = self.cfg.get(f"agent_{role.lower()}") or {}
        return dict(seg) if isinstance(seg, Mapping) else {}

    def agent_a(self, store: Any) -> Any:
        """A：需要 providers（没给就根本不会走到这里）。

        downloader 也要给（2026-09-29 验收 P1 实测的缺口）：只给 providers 时
        A 能检索、却一条全文都下不下来，台账里逐条写 `error="no_downloader"` ——
        而 `no_pdf_url` 是另一回事（那篇本来就没有开放获取 PDF）。两种"没下来"
        必须分得开；`pipeline._build_agent_a` 一直是给的，这一层漏了。
        """
        from . import fetch as F
        from .agent_a import AgentA

        acfg = self._cfg_for("A")
        downloader = None
        if acfg.get("download", True):
            downloader = F.default_downloader(self.cfg.get("download") or {})
        return AgentA(store, providers=list(self.providers), llm=self.llm,
                      config=acfg, downloader=downloader)

    def agent_b(self, store: Any) -> Any:
        """B：extractor 决定它有没有 LLM（B 的签名里没有 `llm`）。"""
        from .agent_b import AgentB
        from .extract import extract_text

        extractor = self.extractor
        if extractor is None:
            if self.llm is not None:
                from .llm import LLMExtractor

                extractor = LLMExtractor(self.llm)
            else:
                from .llm import RuleExtractor

                extractor = RuleExtractor()
        return AgentB(store, extractor=extractor, extract_text=extract_text,
                      config=self._cfg_for("B"))

    def agent_c(self, store: Any) -> Any:
        """C：只要 store。"""
        from .agent_c import AgentC

        return AgentC(store, config=self._cfg_for("C"), llm=self.llm)

    def agent_d(self, store: Any) -> Any:
        """D：构造期拿到 同一个 C 实例（`D` 的签名里 `c` 是可选关键字）。"""
        from .agent_d import AgentD

        return AgentD(store, config=self._cfg_for("D"), llm=self.llm,
                      c=self.get("C", store))

    def agent_e(self, store: Any) -> Any:
        """E：需要工作区根（它跑实验脚本、写产物）。"""
        from .agent_e import AgentE

        return AgentE(store, config=self._cfg_for("E"), llm=self.llm,
                      workspace_root=self.workspace_root or _root_of(store))

    def agent_f(self, store: Any) -> Any:
        """F：构造期拿到 同一个 E 实例。"""
        from .agent_f import AgentF

        return AgentF(store, config=self._cfg_for("F"), llm=self.llm,
                      e=self.get("E", store))

    def agent_g(self, store: Any) -> Any:
        """G：需要工作区根（它写稿件）。"""
        from .agent_g import AgentG

        return AgentG(store, config=self._cfg_for("G"), llm=self.llm,
                      workspace_root=self.workspace_root or _root_of(store))

    def agent_h(self, store: Any) -> Any:
        """H：只要 store（它的落库代理 `writers` 自己会注册）。"""
        from .agent_h import AgentH

        return AgentH(store, config=self._cfg_for("H"), llm=self.llm)

    # ------------------------------------------------------------ 取实例

    def get(self, role: str, store: Any) -> Any:
        """取（或建）该角色的实例；键含 store 根 ⇒ 换库必换实例。"""
        key = (role, str(_root_of(store)))
        if key not in self._made:
            maker = getattr(self, f"agent_{role.lower()}")
            self._made[key] = maker(store)
        return self._made[key]

    def status(self) -> dict[str, str]:
        """逐角色的接线态（`WIRING_STATES` 之一）。"""
        out: dict[str, str] = {}
        for role in S.ROLES:
            if role == "A" and not self.providers:
                out[role] = "no_provider"      # A 的检索后端没给 ⇒ 不假装它接了线
            else:
                out[role] = "wired"
        return out


def build_role_registry(store: Any, *, llm: Any = None,
                        providers: Any = None, extractor: Any = None,
                        config: Mapping[str, Any] | None = None,
                        workspace_root: str | Path | None = None) -> dict[str, Factory]:
    """给 `LocalBackend` 的角色登记表（`role -> ("factory", fn)`）。

    没接线的角色不进这张表 —— 于是 `summon` 会如实落 `refused/not_wired`，
    而不是拿一个空壳对象假装跑过。要看"谁没接线、为什么"，用 :func:`wiring_status`。
    """
    b = _Builder(llm=llm, providers=providers, extractor=extractor,
                 config=config, workspace_root=workspace_root)
    reg: dict[str, Factory] = {}
    for role, state in b.status().items():
        if state != "wired":
            continue

        # 工厂必须用传进来的 store（不许捕获外层那个）：否则把同一张登记表
        # 交给第二个工作区时，角色会静默写进第一个库。
        def factory(*, store: Any = None, _role: str = role, _b: _Builder = b) -> Any:
            """backend 的工厂契约：`fn(*, store=...)` ⇒ 该角色的实例（按角色+库单例）。"""
            if store is None:
                raise TypeError(f"factory({_role}) 需要一个 store（backend 的契约是 fn(*, store=...)）")
            return _b.get(_role, store)

        reg[role] = ("factory", factory)
    return reg


def wiring_status(store: Any, *, providers: Any = None,
                  extractor: Any = None, config: Mapping[str, Any] | None = None,
                  workspace_root: str | Path | None = None) -> dict[str, str]:
    """逐角色的接线态（与 :func:`build_role_registry` 用同一份判定）。"""
    b = _Builder(providers=providers, extractor=extractor, config=config,
                 workspace_root=workspace_root)
    return b.status()


def wired_conductor(store: Any, *, policy: Any = None, llm: Any = None,
                    providers: Any = None, extractor: Any = None,
                    config: Mapping[str, Any] | None = None,
                    workspace_root: str | Path | None = None,
                    backend: str = "local") -> Any:
    """建一个接了线的主控（复用 `conductor_tools` 的按工作区缓存）。

    复用缓存是必要的：M 的每次工具调用都走 `conductor_for(store)`，
    若这里另建一个实例，工具调用看到的台账/预算/取消信号就与这里的不是同一个。
    """
    from .tools.conductor_tools import conductor_for

    reg = build_role_registry(store, llm=llm, providers=providers, extractor=extractor,
                              config=config, workspace_root=workspace_root)
    return conductor_for(store, policy=policy, role_registry=reg, backend=backend)


def wired_tool_registry(store: Any, *, policy: Any = None, llm: Any = None,
                        providers: Any = None, extractor: Any = None,
                        config: Mapping[str, Any] | None = None,
                        workspace_root: str | Path | None = None,
                        **build_kw: Any) -> Any:
    """组装接了线的工具层（主控与角色接线都注入进去）。

    返回 `tools.build_registry` 的原返回值（`RegistryBuild`，含 `.registry`）。
    """
    from .tools import build_registry

    reg = build_role_registry(store, llm=llm, providers=providers, extractor=extractor,
                              config=config, workspace_root=workspace_root)
    conductor = wired_conductor(store, policy=policy, llm=llm, providers=providers,
                                extractor=extractor, config=config,
                                workspace_root=workspace_root)
    return build_registry(store=store, conductor=conductor, role_registry=reg,
                          workspace_root=workspace_root, config=config, **build_kw)


#: 默认的"模型驱动"接线表。刻意是空的：装配期不许因为"环境里有 key"就改变行为。
#: 要驱动哪些 `(角色, 动作)`，由调用方显式给（CLI 的 `--drive` 或代码里传 `loops=`）。
DEFAULT_LLM_LOOPS: dict[tuple[str, str], dict[str, Any]] = {}


def wired_llm_conductor(store: Any, *, policy: Any = None,
                        loops: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
                        session_root: str | Path | None = None, sid: str | None = None,
                        max_steps: int = 6, usd_budget: float | None = None,
                        providers: Any = None, extractor: Any = None,
                        config: Mapping[str, Any] | None = None,
                        workspace_root: str | Path | None = None,
                        seam_factory: Any = None) -> dict[str, Any]:
    """建一个"模型驱动"的主控，返回 `{conductor, backend, registry, loops}`。

    ## 语义（与 `LlmBackend` 的 docstring 逐字一致）

    登记在 `loops` 里的 `(角色, 动作)` 由 LLM 循环执行，其余动作仍走 Python 实现 ——
    角色的确定性动作（算图、分配号、落一行表）不该被模型取代。
    默认 `loops` 为空 ⇒ 这个函数建出来的主控与 `wired_conductor` 行为完全一致，
    差别只是"随时可以接线"。

    ## 为什么要挑明 `conductor_for` 的缓存

    `tools.conductor_tools.conductor_for` 按 `store.root` 缓存实例，而忽略后传的 `backend`：
    先建过确定性主控、再要一个模型驱动的主控，会静默拿到旧的那个 ——
    "我要的是模型驱动"与"实际跑的是确定性实现"在读数上长得一模一样。
    这里显式把 `backend` 换上去并记一条 note（不静默）。
    """
    from .agent_loop import LlmBackend
    from .conductor import LocalBackend
    from .llmseam import LlmSeam
    from .tools import build_registry
    from .tools.conductor_tools import conductor_for

    root = Path(session_root or getattr(store, "root", ".")).resolve()
    ws = str(workspace_root or getattr(store, "root", "") or "")
    role_reg = build_role_registry(store, llm=None, providers=providers, extractor=extractor,
                                   config=config, workspace_root=workspace_root)
    table = dict(loops or {})
    conductor = conductor_for(store, policy=policy, role_registry=role_reg, backend="local")

    # 内层 backend 必须带着 store：`LocalBackend.store` 由 `Conductor` 注入，
    # 而 `factory(role, store=None)` 会被角色工厂当场拒（"需要一个 store"）——
    # 实测 2026-09-29：`run-agent M` 派 H 做 review，两次都以
    # `TypeError: factory(H) 需要一个 store（backend 的契约是 fn(*, store=...)）` 失败，
    # 而 §185 那批测试没看见它：那个用例把子角色也登记进 `loops`（走 LLM 循环），
    # `LocalBackend` 那条路一次都没走。
    inner = getattr(conductor, "backend", None)
    if not isinstance(inner, LocalBackend):
        inner = LocalBackend(role_reg)
        inner.store = store

    def _default_seam(role: str) -> LlmSeam:
        return LlmSeam.for_role(role, session_root=root, sid=sid, usd_budget=usd_budget)

    backend = LlmBackend(inner=inner, loops=table, session_root=root,
                         seam_factory=seam_factory or _default_seam, store=store,
                         max_steps=max_steps, workspace_root=ws, sid=sid)
    if not isinstance(conductor.backend, LlmBackend):
        conductor.backend = backend
        conductor.backend_note = ("backend 被换成 LlmBackend（conductor_for 的缓存忽略后传的 "
                                  "backend，不换就会静默跑确定性实现）")
    built = build_registry(store=store, conductor=conductor, role_registry=role_reg,
                           workspace_root=workspace_root, config=config)
    backend.registry = built.registry
    backend.conductor = conductor
    backend.store = store
    return {"conductor": conductor, "backend": backend, "registry": built.registry,
            "loops": table, "session_root": root}


def selftest() -> int:
    """自检：登记表形态、逐角色接线态、以及"没给 providers 就不进表"。

    这也是本模块的正控/负控最小集（完整判据见 `tests/test_host_wiring.py`）：
    正控 = 给了 providers 时 A–H 齐；负控 = 不给 providers 时 A 必须缺席且状态是 `no_provider`。
    """
    import shutil
    import tempfile

    from .store import Store

    root = Path(tempfile.mkdtemp(prefix="host-selftest-"))
    try:
        st = Store(root)
        st.init()
        fake_providers = [object()]
        full = build_role_registry(st, providers=fake_providers)
        if set(full) != set(S.ROLES):
            print(f"[fail] 给了 providers 时登记表应覆盖 {S.ROLES}，实得 {sorted(full)}")
            return 1
        if any(kind != "factory" for kind, _fn in full.values()):
            print("[fail] 登记项必须全是 ('factory', fn)（类会被 LocalBackend 拒绝）")
            return 1
        part = build_role_registry(st, providers=None)
        if "A" in part:
            print("[fail] 没给 providers 时 A 不许进登记表")
            return 1
        st_map = wiring_status(st, providers=None)
        if st_map.get("A") != "no_provider" or set(st_map) != set(S.ROLES):
            print(f"[fail] wiring_status 应逐角色给态，实得 {st_map}")
            return 1
        # 工厂真的能建（用假 provider 只验构造路径，不出网）
        obj = full["C"][1](store=st)
        if type(obj).__name__ != "AgentC" or getattr(obj, "llm", "missing") is not None:
            print("[fail] C 的工厂应给出 llm=None 的 AgentC")
            return 1
        same = full["D"][1](store=st).c is full["C"][1](store=st)
        if not same:
            print("[fail] D 手里的 C 与登记表里的 C 必须是同一个实例")
            return 1
        print("SELF-CHECK DONE")
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(selftest())
