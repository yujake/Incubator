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


def b_extractor(store: Any, *, config: Mapping[str, Any] | None = None,
                notes: list[str] | None = None) -> Any:
    """B 的抽取器 —— 「唯一装配点」（`run-agent` / `run-b` / `pipeline` 三条路共用）。

    ## 为什么它必须存在（2026-10-03 的根因，见 `draft/37` §83）

    `LLMExtractor` 要一个 `complete(prompt) -> str` 的 client，而「模型缝不是它」
    （`LlmSeam` 只有 `ask`）。此前三条路各写各的，结果都一样坏：

    - `run-agent` 从不给 B 任何 client ⇒ 退到 `RuleExtractor` ⇒ `B.run_once`
      「当场拒抽」（`R-56`：规则抽取器会把碎片当概念/关系）⇒ `relations` 一行都没有
      ⇒ 引文逐字回验这条腿在真机上「结构性不可达」（实测 `p5-run15`：`relations` 0 行、
      `literature.processed=False`）；
    - `run-b` / `pipeline` 把 `RuleExtractor()` 写死 ⇒ 同样永远拒抽；
    - 而唯一正确的配方写在 `projects.py` 里：`client_from_env(scope="extract",
      meter=TokenMeter(store), role="B", max_tokens=8192)`。`max_tokens` 必须给大
      （实测 2026-09-28：缺省 4096 会把整份 JSON 截在半句上 ⇒ 解析失败、整篇作废）。

    这里把那个配方收成一处：「有 key ⇒ 计量过的模型 client；没有 key ⇒ 规则档」
    （后者让 `run_once` 如实报 `no_llm_extractor`，而不是"每篇文献发一次注定失败的请求"）。
    两种情况都往 `notes` 里记一句，于是"为什么 B 在用规则抽取器"在读数里看得见。
    """
    from .extract import extract_text  # noqa: F401  （保留语义：调用方仍需自查）
    from .llm import LLMExtractor, RuleExtractor

    if not _model_key_present():
        if notes is not None:
            notes.append(f"B：没有配置模型 key ⇒ 抽取器退回规则档"
                         f"（`B.run_once` 会如实拒抽：no_llm_extractor）")
        return RuleExtractor()
    from .modelclient import SCOPE_EXTRACT, client_from_env
    from .tokenmeter import TokenMeter

    client = client_from_env(scope=SCOPE_EXTRACT, meter=TokenMeter(store),
                             task_id="host-wiring", role="B", max_tokens=8192)
    if notes is not None:
        notes.append("B：抽取器 = LLMExtractor（client 走 modelclient，作用域 extract、"
                     "max_tokens=8192、已挂 TokenMeter ⇒ 花销进 usage_ledger）")
    return LLMExtractor(client)


def _model_key_present(env: Mapping[str, str] | None = None) -> bool:
    """环境里配了模型 key 吗（只看有没有，绝不读值去做别的事）。"""
    try:
        from .modelgw import spec_from_env

        return bool((spec_from_env(env).api_key or "").strip())
    except Exception:  # noqa: BLE001 - 配置读不出来 ⇒ 当作"没有"，让上层如实退规则档
        return False


class _Builder:
    """一次装配的上下文：按需建角色、同 (角色, store 根) 单例。

    单例不是优化：`D` 与 `F` 在构造期就被绑定了它们的邻居（`c=` / `e=`），
    如果每次召唤都新建一个 C，那么 D 手里的 C 与 M 直接召唤的 C 就是两个对象 ——
    两个对象各自持有会话状态，"谁能叫谁"这条结构就名存实亡了。
    """

    def __init__(self, *, llm: Any = None, providers: Any = None, extractor: Any = None,
                 config: Mapping[str, Any] | None = None,
                 workspace_root: str | Path | None = None,
                 llm_by_role: Mapping[str, Any] | None = None) -> None:
        self.llm = llm
        #: 逐角色的模型缝（2026-09-30）：`llm=` 是"所有角色共用这一个"，
        #: 而 H 的语义判据要的是只给 H 一个缝 —— 把它塞进 `llm=` 会让
        #: `agent_b` 拿它去造 `LLMExtractor`，而缝不是抽取器 client
        #: （实测：`TypeError: client 必须提供 complete(prompt: str) -> str 方法`，
        #: 且当时被 `resolve` 的 `except TypeError` 兜成了一句误导性的"需要一个 store"）。
        self.llms: dict[str, Any] = dict(llm_by_role or {})
        self.providers = list(providers or [])
        self.extractor = extractor
        self.cfg: dict[str, Any] = dict(config or {})
        self.workspace_root = Path(workspace_root) if workspace_root else None
        self._made: dict[tuple[str, str], Any] = {}
        #: "为什么 B 在用规则抽取器"这类装配读数（`b_extractor` 往里写，`wired_llm_conductor` 转出来）
        self.extractor_notes: list[str] = []
        #: 角色声明的注册表（懒取一次；`goal-7f5116c1` M4）
        self._specs: Any = None

    # ------------------------------------------------------------ 逐个角色

    def _llm_for(self, role: str) -> Any:
        """该角色用的模型缝：逐角色优先，否则用共用的那个。"""
        return self.llms.get(role, self.llm) if role in self.llms else self.llm

    def _cfg_for(self, role: str) -> dict[str, Any]:
        """该角色的配置段（`config["agent_c"]` 这类；没有就给空 dict）。"""
        seg = self.cfg.get(f"agent_{role.lower()}") or {}
        return dict(seg) if isinstance(seg, Mapping) else {}

    #: 角色 → 它的构造签名收不收 `actor=`（2026-09-30 为实例轴查的实测结论）。
    #: A/D/E/F 有显式 `actor=` 形参；G/H 从 config 的 `actor` 键取；
    #: B/C 没有 actor 概念（B 的写入走 `claimed_by` 领取，C 只读）。
    _ACTOR_KWARG: frozenset[str] = frozenset({"A", "D", "E", "F"})
    _ACTOR_IN_CONFIG: frozenset[str] = frozenset({"G", "H"})

    def _actor_for(self, role: str, instance: str) -> str:
        """实例标签 → actor 名（空标签就是默认的那个 actor）。"""
        return f"agent-{role}-{instance}" if instance else f"agent-{role}"

    def agent_a(self, store: Any, instance: str = "") -> Any:
        """A（构造在 `specs/a.py::build`：要 providers 与下载器）。"""
        return self._build("A", store, instance)


    def agent_b(self, store: Any, instance: str = "") -> Any:
        """B（构造在 `specs/b.py::build`：要抽取器；B 的签名里没有 `llm`、没有 `actor`）。"""
        return self._build("B", store, instance)


    def agent_c(self, store: Any, instance: str = "") -> Any:
        """C（构造在 `specs/c.py::build`：只要 store / config / llm）。"""
        return self._build("C", store, instance)


    def agent_d(self, store: Any, instance: str = "") -> Any:
        """D（构造在 `specs/d.py::build`：构造期拿到同一个 C 实例，`peers=("C",)`）。"""
        return self._build("D", store, instance)


    def agent_e(self, store: Any, instance: str = "") -> Any:
        """E（构造在 `specs/e.py::build`：要工作区根）。"""
        return self._build("E", store, instance)


    def agent_f(self, store: Any, instance: str = "") -> Any:
        """F（构造在 `specs/f.py::build`：构造期拿到同一个 E 实例，`peers=("E",)`）。"""
        return self._build("F", store, instance)


    def agent_g(self, store: Any, instance: str = "") -> Any:
        """G（构造在 `specs/g.py::build`：要工作区根；actor 在 config 里）。"""
        return self._build("G", store, instance)


    def agent_h(self, store: Any, instance: str = "") -> Any:
        """H（构造在 `specs/h.py::build`：只要 store / config / llm）。"""
        return self._build("H", store, instance)


    def _cfg_with_actor(self, role: str, instance: str) -> dict[str, Any]:
        """G/H 从 config 读 `actor`：实例标签就写在这里（它们没有 `actor=` 形参）。"""
        cfg = self._cfg_for(role)
        cfg["actor"] = self._actor_for(role, instance)
        return cfg

    # ------------------------------------------------------------ 依赖怎么造
    #
    # `goal-7f5116c1` M4：角色的构造搬进了它自己的声明（`specs/<角色>.py::build`），
    # 这里只剩"装配知识"——两个角色专属的默认值，它们不是声明，放这儿才对：
    # 一个是"没给抽取器时按有没有模型缝选哪一种"，一个是"A 的下载器由配置开关决定"。

    def _extractor_for(self, role: str, store: Any = None) -> Any:
        """B 的抽取器：显式给的最优先；否则按"这一路的模型 client 能不能造"选。

        三条分支（顺序就是优先级）：

        1. 调用方显式给了 `extractor=` ⇒ 用它（判据与替身走这条）；
        2. 该角色拿到的 `llm` 本身就是抽取器 client（有 `.complete`）⇒ 包成 `LLMExtractor`
          （`tests/test_host_wiring.py` 的假 LLM 走这条）；
        3. 其余情况 ⇒ :func:`b_extractor`（有 key 用模型 client，没有 key 退规则档）。

        不再把模型缝塞给 `LLMExtractor`。此前那句 `LLMExtractor(role_llm)` 是个陷阱：
        真实缝没有 `.complete` ⇒ 构造期 `TypeError`，而那个错曾被 `LocalBackend.resolve`
        的 `except TypeError` 兜成一句误导性的"factory(B) 需要一个 store"（`__init__` 的
        注释逐字记着这次事故）。现在缝被认出来就记一条 note、走第 3 条，不再硬塞。
        """
        if self.extractor is not None:
            return self.extractor
        role_llm = self._llm_for(role)
        if role_llm is not None:
            if hasattr(role_llm, "complete"):
                from .llm import LLMExtractor

                return LLMExtractor(role_llm)
            self.extractor_notes.append(
                f"{role}：给的模型缝没有 complete()（缝不是抽取器 client）⇒ 不拿它造 "
                f"LLMExtractor（那会在构造期抛 TypeError）；改走 b_extractor()")
        return b_extractor(store, config=self.cfg, notes=self.extractor_notes)

    def _downloader_for(self, role: str) -> Any:
        """A 的下载器：`agent_<role>` 配置段的 `download` 关掉时明确不给（None = 没接）。

        为什么默认给：只给 providers 时 A 能检索、却一条全文都下不下来，
        台账里逐条写 `error="no_downloader"` —— 而 `no_pdf_url` 是另一回事
        （那篇本来就没有开放获取 PDF）。两种"没下来"必须分得开。
        """
        cfg = self._cfg_for(role)
        if not cfg.get("download", True):
            return None
        from . import fetch as F

        return F.default_downloader(self.cfg.get("download") or {})

    # ------------------------------------------------------------ 通用构造（读注册表）

    def _registry(self):
        """角色声明的注册表（每个 `_Builder` 取一次；`agentspec` 是叶子，代价很小）。"""
        if self._specs is None:
            from .agentspec import builtin_registry

            self._specs = builtin_registry()
        return self._specs

    def _build(self, role: str, store: Any, instance: str = "") -> Any:
        """按声明构造一个角色实例（`goal-7f5116c1` M4）。

        这里只做三件通用的事：① 算该角色的 llm / config / actor（G/H 的 config 带 actor）；
        ② 按声明里的 `needs` / `peers` 备齐依赖；③ 把 `BuildDeps` 交给 `spec.build`。
        角色之间的差别（用哪个类、传哪些关键字、要谁的实例）全在声明里 —— 所以
        "新建一个 agent" 不需要改这个文件。
        """
        from .agentspec import BuilderDeps

        spec = self._registry().get(role)
        if spec.build is None:
            raise ValueError(f"角色 {role} 的声明里没有 build 工厂（M4 起装配只认它）")
        cfg = (self._cfg_with_actor(role, instance) if role in self._ACTOR_IN_CONFIG
               else self._cfg_for(role))
        deps = BuilderDeps(
            role=role,
            store=store,
            instance=instance,
            llm=self._llm_for(role),
            config=cfg,
            providers=tuple(self.providers) if "providers" in spec.needs else (),
            extractor=(self._extractor_for(role, store) if "extractor" in spec.needs else None),
            workspace_root=((self.workspace_root or _root_of(store))
                            if "workspace_root" in spec.needs else None),
            actor=self._actor_for(role, instance),
            downloader=self._downloader_for(role) if "downloader" in spec.needs else None,
            peers={r: self.get(r, store) for r in spec.peers},
        )
        return spec.build(deps)

    # ------------------------------------------------------------ 取实例

    def get(self, role: str, store: Any, instance: str = "") -> Any:
        """取（或建）该角色的实例；键含 store 根 ⇒ 换库必换实例。

        `instance` 是 2026-09-30 加的实例轴：空串 = 那个单例（默认行为逐字不变）；
        显式标签 ⇒ 键里多一维，于是"N 个 B 一起干活"拿到的是 N 个对象。
        为什么单例路径必须留着：`D` 与 `F` 在构造期就绑定了邻居（`c=` / `e=`），
        每召唤一次新建一个 C，就会让 `D.c is C` 这条结构不变式断掉
        （`tests/test_host_wiring.py` 钉着它）。所以只有显式要实例时才分家。
        """
        key = (role, str(instance or ""), str(_root_of(store)))
        if key not in self._made:
            maker = getattr(self, f"agent_{role.lower()}")
            self._made[key] = maker(store) if not instance else maker(store, instance=instance)
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
                        workspace_root: str | Path | None = None,
                        llm_by_role: Mapping[str, Any] | None = None,
                        notes: list[str] | None = None) -> dict[str, Factory]:
    """给 `LocalBackend` 的角色登记表（`role -> ("factory", fn)`）。

    没接线的角色不进这张表 —— 于是 `summon` 会如实落 `refused/not_wired`，
    而不是拿一个空壳对象假装跑过。要看"谁没接线、为什么"，用 :func:`wiring_status`。
    """
    b = _Builder(llm=llm, providers=providers, extractor=extractor,
                 config=config, workspace_root=workspace_root, llm_by_role=llm_by_role)
    if notes is not None:
        # 同一个列表对象：装配读数（B 的抽取器是什么、为什么）在装配期就写进去，
        # 调用方跑完能把它当「这一趟的接线读数」读出来，而不是靠猜。
        b.extractor_notes = notes
    reg: dict[str, Factory] = {}
    for role, state in b.status().items():
        if state != "wired":
            continue

        # 工厂必须用传进来的 store（不许捕获外层那个）：否则把同一张登记表
        # 交给第二个工作区时，角色会静默写进第一个库。
        def factory(*, store: Any = None, instance: str = "",
                    _role: str = role, _b: _Builder = b) -> Any:
            """backend 的工厂契约：`fn(*, store=..., instance="")` ⇒ 该角色的实例。

            不给 `instance` 时按 `(角色, 库)` 单例（`tests/test_host_wiring.py` 钉着）；
            给了实例标签 ⇒ 每标签一个对象（"N 个 B 一起干活"要的是 N 个对象）。
            """
            if store is None:
                raise TypeError(f"factory({_role}) 需要一个 store（backend 的契约是 fn(*, store=...)）")
            return _b.get(_role, store, instance)

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
                        session_root: str | Path | None = None, sid: str | None = None,
                        **build_kw: Any) -> Any:
    """组装接了线的工具层（主控与角色接线都注入进去）。

    返回 `tools.build_registry` 的原返回值（`RegistryBuild`，含 `.registry`）。

    `session_root` / `sid` 显式往后传（`draft/37` §63）：会话身份是装配期输入，
    不给 ⇒ `conductor.closing` 的 `user_pending` 记 `unknown`（不是 pass）。
    这里显式列出而不是靠 `build_kw` 顺手带过去：靠 `build_kw` 时，
    一个拼错的键会被静默吞进 `deps` 之外、工具照旧按缺省会话读 —— 那正是假绿的形态。
    """
    from .tools import build_registry

    reg = build_role_registry(store, llm=llm, providers=providers, extractor=extractor,
                              config=config, workspace_root=workspace_root)
    conductor = wired_conductor(store, policy=policy, llm=llm, providers=providers,
                                extractor=extractor, config=config,
                                workspace_root=workspace_root)
    return build_registry(store=store, conductor=conductor, role_registry=reg,
                          workspace_root=workspace_root, config=config,
                          session_root=session_root, sid=sid, **build_kw)


#: 默认的"模型驱动"接线表。刻意是空的：装配期不许因为"环境里有 key"就改变行为。
#: 要驱动哪些 `(角色, 动作)`，由调用方显式给（CLI 的 `--drive` 或代码里传 `loops=`）。
DEFAULT_LLM_LOOPS: dict[tuple[str, str], dict[str, Any]] = {}


def wired_llm_conductor(store: Any, *, policy: Any = None,
                        loops: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
                        session_root: str | Path | None = None, sid: str | None = None,
                        max_steps: int = 30, usd_budget: float | None = None,
                        providers: Any = None, extractor: Any = None,
                        config: Mapping[str, Any] | None = None,
                        workspace_root: str | Path | None = None,
                        seam_factory: Any = None,
                        semantic_review: bool = False) -> dict[str, Any]:
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
    from .tokenmeter import TokenMeter
    from .tools import build_registry
    from .tools.conductor_tools import conductor_for
    from . import sessions as SS

    root = Path(session_root or getattr(store, "root", ".")).resolve()
    ws = str(workspace_root or getattr(store, "root", "") or "")
    # ---- 会话身份在装配期定下（`draft/37` §63，修法 B）
    #
    # `sid=None` 的缺省值是"写入那一刻"的 `sessions.session_id()`（当天日期）。
    # 运行内 `conductor.closing` 拿到的必须是「这一趟」的会话号，而不是"今天那段" ——
    # 实测第 11 趟运行内报 `can_close: true`、外部带 sid 报 `failed: ['user_pending']`。
    # 所以这里解析一次，把它同时交给：模型缝（写 `llm_call` 事件）、
    # `LlmBackend`（写 `agent_*` 事件）、以及工具层（读会话文件）——
    # 三处读写的必须是同一个文件。
    eff_sid = sid or SS.session_id()
    # H 的语义判据（`draft/28` §196）：默认 False —— 环境里有 key 也不改变确定性行为
    # （与 `DEFAULT_LLM_LOOPS` 同一条纪律）。打开时 H 拿一个按角色造的模型缝，
    # `claims_semantically_judged` 才会从 0 变成真读数。
    h_llm = None
    if semantic_review:
        from .llmseam import LlmSeam as _Seam

        h_llm = (seam_factory or (lambda role: _Seam.for_role(role, session_root=root, sid=eff_sid,
                                                             usd_budget=usd_budget,
                                                             meter=TokenMeter(
                                                                 store, budget_usd=usd_budget))))("H")
    notes: list[str] = []
    role_reg = build_role_registry(store, providers=providers, extractor=extractor,
                                   notes=notes,
                                   config=config, workspace_root=workspace_root,
                                   llm_by_role=({"H": h_llm} if h_llm is not None else None))
    table = dict(loops or {})
    conductor = conductor_for(store, policy=policy, role_registry=role_reg, backend="local")
    # 画像文件（`draft/37` §109，用户口径）：M 要看到所有人的简介，其它角色看可协作的
    # 同伴 —— 而"只在开头注入提示词"会被跑到后面忘掉，所以每次运行落一份可查的文件
    # 到工作区根（不进 `out/`：那里是论文包的地盘，锚在看着它）。
    try:
        from . import agent_prompts as _AP

        _prof = _AP.write_profiles(store.root if store is not None else ".",
                                   registry=table or None,
                                   availability=wiring_status(store) if store is not None else None)
        notes.append(f"画像文件：{_prof}" if _prof else
                     "画像文件没写成（工作区不可写？）—— 提示词里的那份仍然有效")
    except Exception as exc:  # noqa: BLE001 —— 写不成不影响这次运行，但必须留痕
        notes.append(f"画像文件没写成：{type(exc).__name__}: {exc}")

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
        # `meter=` 见 `draft/37` §64：缝是模型调用的唯一入口，记账挂在它身上 ——
        # 不挂的话，`run-agent` 这条路一次调用都不会进 `usage_ledger`。
        return LlmSeam.for_role(role, session_root=root, sid=eff_sid, usd_budget=usd_budget,
                                meter=TokenMeter(store, budget_usd=usd_budget))

    backend = LlmBackend(inner=inner, loops=table, session_root=root,
                         seam_factory=seam_factory or _default_seam, store=store,
                         max_steps=max_steps, workspace_root=ws, sid=eff_sid)
    if not isinstance(conductor.backend, LlmBackend):
        conductor.backend = backend
        conductor.backend_note = ("backend 被换成 LlmBackend（conductor_for 的缓存忽略后传的 "
                                  "backend，不换就会静默跑确定性实现）")
    built = build_registry(store=store, conductor=conductor, role_registry=role_reg,
                           workspace_root=workspace_root, config=config,
                           session_root=root, sid=eff_sid)
    backend.registry = built.registry
    backend.conductor = conductor
    backend.store = store
    return {"conductor": conductor, "backend": backend, "registry": built.registry,
            "loops": table, "session_root": root,
            # 这一趟定下的会话号（§63）：调用方与运维据此核对"工具面读的是哪一段"。
            "sid": eff_sid,
            # 装配读数（B 的抽取器是什么、为什么；2026-10-03 §83 的根因修复）：
            # 空 = 一切按预期；非空 = 有人该看一眼（例如没 key ⇒ B 会拒抽）。
            "notes": notes}


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
