"""`A.search_literature` 的 `providers`（一次问多源）：声明面缺口补齐后的判据族。

所有者 2026-10-07 批准的功能改动：工具面 `search.literature` 早就有 `providers`，
动作面没有 —— 而主控派活读的是动作参数表，于是这个入口在编排层看不见。
这一族钉五件事，每件都带能红的负控：

1. 声明面：动作面真的声明了 `providers`，形状是 array<string>，且没有把
   可用源名单（工具面那格的 enum）抄过来 —— 抄一份就是第二个要改的地方。
2. 声明与实现不分家：只加声明、不改实现时，导入期的参数交叉断言必须报出来
   （这正是这次改动不能只改声明面的理由，负控复现的就是那条报文）。
3. 三态分得开，各带读数：没点名源（按角色接线、今天的行为不变）/ 点名了合法源
   （逐源成败 + 成本可读，形状与工具面同名读数一致）/ 点名了不认识的源
   （如实拒绝 + 给可用名单 + 零写入，绝不静默忽略）。
4. 领取侧真的按请求行点名的源检索，不是只看角色级接线。
5. 收尾面：动作声明里 `returns` 那一格的逐键清单与实现真正返回的键逐键相同
   （题 20 选 A，2026-10-07 所有者裁定）—— 题 11 补完"完整透传"之后实现多返回了
   `sources` / `cost`，而声明面没跟上，主控派的活读的就是那一格。

全部离线、确定性：检索源是注入的替身，不联网。
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import tempfile
from pathlib import Path

import pytest
from conftest import TS, add_request, sync_counters

from agentflow import capabilities as C
from agentflow import providers as P
from agentflow import schema as S
from agentflow.agent_a import AgentA
from agentflow.store import Store
from agentflow.tools import search_tools
from agentflow.tools.base import ToolRegistry
from agentflow.verify import verify_all


# --------------------------------------------------------------------------- 替身与夹具


class _StubProvider:
    """确定性检索源替身：不联网，记下自己被问过几次。可配置成抛异常。"""

    def __init__(self, name: str, candidates=(), error: BaseException | None = None) -> None:
        self.name = name
        self.candidates = list(candidates)
        self.error = error
        self.calls: list[tuple] = []

    def search(self, topic, mode, description="", limit=10):
        self.calls.append((topic, mode, description, limit))
        if self.error is not None:
            raise self.error
        return list(self.candidates)


def _cand(title: str, doi: str, provider: str) -> P.Candidate:
    """一条候选（带 DOI ⇒ 跨源合并键可判定，不会落进"无法判定"那一档）。"""
    return P.Candidate(
        title=title, year=1930, doi=doi, authors=["A. Author"], venue="V",
        type_code="J", summary="摘要", pdf_url=None, landing_url=None,
        language="en", provider=provider, raw={"provider": provider},
    )


def _agent(store: Store, *provs, **cfg) -> AgentA:
    """A 实例：默认关下载（这一族判的是"问了谁"，不是落盘字节）。"""
    config = {"download": False, "lease_seconds": 900, "max_attempts": 3}
    config.update(cfg)
    return AgentA(store, providers=list(provs), downloader=None, config=config)


def _spec():
    """动作面上的 `A.search_literature` 那一条声明。"""
    return next(s for s in C.CAPABILITIES["A"] if s.action == "search_literature")


# --------------------------------------------------------------------------- 1. 声明面


def _declaration_problems(declared) -> list[str]:
    """动作面 `providers` 那一格的形状问题清单（空 = 成立）。

    纯函数，正控与负控走同一段逻辑 —— 否则负控红了也说不清是判据坏了还是输入错了。
    """
    out: list[str] = []
    if not isinstance(declared, dict):
        return ["providers 那一格不是对象"]
    if declared.get("type") != "array":
        out.append("providers 的 type 必须是 array")
    items = declared.get("items")
    if not isinstance(items, dict) or items.get("type") != "string":
        out.append("providers 的 items.type 必须是 string")
    for copied in ("enum", "minItems", "maxItems"):
        if copied in declared:
            out.append(f"providers 抄了工具面的 {copied}（可用源名单的真身是检索后端注册表）")
    return out


def test_the_action_declares_array_of_string_without_copying_the_source_list():
    """正控：动作面声明了 `providers`，形状是 array<string>，且没抄 enum/上下限。"""
    props = (_spec().params or {}).get("properties") or {}
    assert "providers" in props, "动作面又没了 providers（编排层看不见这个入口）"
    assert _declaration_problems(props["providers"]) == [], props["providers"]
    # 反真空：这一格不是凭空冒出来的 —— 同一张表里原有的三格还在（判据真的读到了表）。
    assert {"topic", "mode", "description"} <= set(props), sorted(props)
    assert list((_spec().params or {}).get("required") or []) == ["topic"], \
        "providers 是可选的，不该进 required"


def test_the_declaration_shape_checker_catches_a_copied_or_wrong_shape():
    """负控：形状错、或把可用源名单抄进来 ⇒ 同一个检查函数必须各报一次。

    没有这一条，"形状是 array<string>"这句话可能只是恒真（检查器没牙）。
    """
    assert _declaration_problems({"type": "object"}), "形状错没被抓住"
    assert _declaration_problems({"type": "array", "items": {"type": "integer"}}), \
        "items 类型错没被抓住"
    assert _declaration_problems(
        {"type": "array", "items": {"type": "string"}, "enum": ["openalex"]}
    ), "抄了 enum 没被抓住"
    assert _declaration_problems(
        {"type": "array", "items": {"type": "string"}, "minItems": 1}
    ), "抄了 minItems 没被抓住"


# --------------------------------------------------------------------------- 2. 两层不分家


def test_declaring_it_without_teaching_the_implementation_is_import_time_red(monkeypatch):
    """负控（这次改动的由头）：只加声明、实现不收 ⇒ 参数交叉断言必须报出来。

    这是逐字复现那条报文的那一格：`param_seam_violations` 读的是
    `inspect.signature`，而参数门（主控派活）读的是声明表。两者分家时，
    主控会放行、写一行 running、执行期才报"不认这些参数"。
    负控手法：把实现侧"收得下哪些参数"换成加这一格之前的那一份 ——
    判据必须恰好报出 `providers` 这一个，而不是整表报错。
    """
    spec = _spec()
    real = C.handler_accepted

    # 正控：真实实现收得下 providers（这才是"改完了"的样子）。
    named, accepts_kw = real("A", "search_literature")
    assert "providers" in named and not accepts_kw, (sorted(named), accepts_kw)
    assert C.param_seam_violations({"A": (spec,)}) == []

    # 负控：把实现面换回"没有 providers"的旧样子。
    monkeypatch.setattr(C, "handler_accepted",
                        lambda role, action: (frozenset({"topic", "mode", "description"}), False))
    bad = C.param_seam_violations({"A": (spec,)})
    assert bad == [("A", "search_literature", ["providers"])], bad


def test_the_handler_signature_really_takes_providers():
    """实现面：`AgentA.search_literature` 的签名里真的有这个具名形参。"""
    params = inspect.signature(AgentA.search_literature).parameters
    assert "providers" in params, sorted(params)
    assert params["providers"].default is None, "不给这一格 = 第一态（按角色接线查）"
    # 反真空：签名里原来那三个还在（判据读的不是一个空签名）。
    assert {"topic", "mode", "description"} <= set(params), sorted(params)


# --------------------------------------------------------------------------- 3. 三态


def test_state_one_no_providers_uses_the_role_wiring_and_says_so(store):
    """第一态：不给 `providers` ⇒ 按角色级接线查，今天的行为不变，读数如实说"没点名"。"""
    alpha = _StubProvider("alpha", [_cand("Alpha paper", "10.1/alpha", "alpha")])
    beta = _StubProvider("beta", [_cand("Beta paper", "10.2/beta", "beta")])
    a = _agent(store, alpha, beta)

    out = a.search_literature(topic="abelian group", mode="topical")

    assert out["outcome"] == "ok" and out["registered"] == 2, out
    # 判据：`providers_requested=None` 才是"没点名"。若有人把它折成"默认等于角色接线"，
    # 这一格会变成 ["alpha","beta"]，这条立即红（折平三态的那条路被钉住）。
    assert out["providers_requested"] is None, out["providers_requested"]
    assert out["role_providers"] == ["alpha", "beta"], out["role_providers"]
    # 第一态也逐源报状态（2026-10-20 审计 A 的缺陷 6）：不报的话，"被限流"与
    # "0 命中"在读数上同形。这里两个源都交货了一条，逐源读数必须如实说这件事；
    # "没点名"这件事仍由 `providers_requested=None` 回答，不许混进这一格。
    assert [s["name"] for s in out["sources"]] == ["alpha", "beta"], out["sources"]
    assert all(s["status"] == "ok" and s["count"] == 1 for s in out["sources"]), out["sources"]
    # 反真空：真的问了接线上的每一个源（不是"读数全 0"混过去）。
    assert len(alpha.calls) == 1 and len(beta.calls) == 1, (alpha.calls, beta.calls)
    assert out["cost"]["provider_calls"] == 2, out["cost"]
    # 请求行上没点名：老行为在盘上也看得出来。
    assert store.rows("search_requests")[0]["providers"] == []


def test_state_two_named_sources_are_all_asked_and_each_reading_is_there(store):
    """第二态：点名合法源 ⇒ 只问它们、逐源三态与成本可读、请求行留住名字与次序。"""
    alpha = _StubProvider("alpha", [_cand("Alpha paper", "10.1/alpha", "alpha")])
    beta = _StubProvider("beta", [_cand("Beta paper", "10.2/beta", "beta")])
    a = _agent(store, alpha, beta)

    # 故意按"非升序"点名：次序是合并口径的一部分（先到的源先填字段）。
    out = a.search_literature(topic="abelian group", mode="topical",
                              providers=["beta", "alpha"])

    assert out["outcome"] == "ok" and out["registered"] == 2, out
    assert out["providers_requested"] == ["beta", "alpha"], out["providers_requested"]
    # 反折叠：点名了就不该再报"没点名"。
    assert out["providers_requested"] is not None
    rows = out["sources"]
    assert [r["name"] for r in rows] == ["beta", "alpha"], rows
    for row in rows:
        assert row["status"] == "ok" and row["delivered"] is True, row
        assert row["refused"] is False and row["error"] == "", row
    # 反真空：读数不是一排 0 —— 每个源真的各交了 1 条。
    assert [r["count"] for r in rows] == [1, 1], rows
    assert out["cost"]["provider_calls"] == 2, out["cost"]
    assert len(alpha.calls) == 1 and len(beta.calls) == 1, (alpha.calls, beta.calls)
    # 请求行上留住名字与次序（seq，不许被静默排序去重）。
    assert store.rows("search_requests")[0]["providers"] == ["beta", "alpha"]


def test_state_two_reports_a_failed_source_without_swallowing_the_other(store):
    """第二态的分档：一个源炸了不许吞掉别的源的结果，也不许折成"检索失败"。"""
    good = _StubProvider("good", [_cand("Good paper", "10.3/good", "good")])
    bad = _StubProvider("bad", error=RuntimeError("upstream 503"))
    a = _agent(store, good, bad)

    out = a.search_literature(topic="abelian group", mode="topical",
                              providers=["good", "bad"])

    assert out["outcome"] == "ok", "有源交了货就不该整条落失败"
    assert out["registered"] == 1, out
    rows = {r["name"]: r for r in out["sources"]}
    assert set(rows) == {"good", "bad"}, rows
    assert rows["good"]["delivered"] is True and rows["good"]["count"] == 1, rows["good"]
    assert rows["bad"]["status"] == "failed", rows["bad"]
    assert rows["bad"]["count"] == 0 and rows["bad"]["error_kind"], rows["bad"]
    assert "503" in rows["bad"]["error"], rows["bad"]
    # 坏源与"这一问没发出去"（第三态）必须分开：它不是 refused。
    assert rows["bad"]["refused"] is False, rows["bad"]


def test_state_three_an_unknown_source_name_is_refused_with_the_available_list(store):
    """第三态：不认识的源名 ⇒ 如实拒绝 + 可用名单 + 零写入（绝不静默忽略）。"""
    alpha = _StubProvider("alpha", [_cand("Alpha paper", "10.1/alpha", "alpha")])
    a = _agent(store, alpha)

    out = a.search_literature(topic="abelian group", mode="topical",
                              providers=["crossref"])

    assert out["ok"] is False and out["kind"] == "unknown_provider", out
    assert out["refusal_reason"] == "invalid_params", out
    assert out["available"] == ["alpha"], out["available"]
    assert out["providers_requested"] == ["crossref"] and out["unknown"] == ["crossref"], out
    assert alpha.calls == [], "被拒就不该有任何出网"
    assert store.rows("search_requests") == [], "零写入：不许留一条注定查不动的请求"
    assert store.rows("literature") == []


def test_state_three_a_partly_unknown_list_is_refused_whole(store):
    """第三态不许"部分生效"：名单里混了一个不认识的 ⇒ 整条拒（不是悄悄只问认识的）。"""
    alpha = _StubProvider("alpha", [_cand("Alpha paper", "10.1/alpha", "alpha")])
    a = _agent(store, alpha)

    out = a.search_literature(topic="abelian group", mode="topical",
                              providers=["alpha", "nope"])

    assert out["ok"] is False and out["kind"] == "unknown_provider", out
    assert out["unknown"] == ["nope"], out["unknown"]
    assert alpha.calls == [], "整条被拒时一个源都不该问"
    assert store.rows("search_requests") == []


def test_state_three_an_explicit_empty_list_is_not_read_as_role_config(store):
    """第三态的另一半：显式空列表既不是"点名"也不是"按角色配置" ⇒ 如实拒。"""
    alpha = _StubProvider("alpha", [_cand("Alpha paper", "10.1/alpha", "alpha")])
    a = _agent(store, alpha)

    out = a.search_literature(topic="abelian group", mode="topical", providers=[])

    assert out["ok"] is False and out["kind"] == "bad_providers", out
    assert out["available"] == ["alpha"], out
    assert alpha.calls == [] and store.rows("search_requests") == []


def test_the_three_states_have_three_different_readings(store):
    """三态纪律的元判据：同一次动作在三种输入下的读数两两不同形。

    没有这一条，"三态分得开"就只能靠人读三处断言去比 —— 而"折平了某一态"
    恰恰是那种单看一处断言看不出来的改动。
    """
    alpha = _StubProvider("alpha", [_cand("Alpha paper", "10.1/alpha", "alpha")])
    a = _agent(store, alpha)

    one = a.search_literature(topic="abelian group", mode="topical")
    assert one["admitted"] is True
    two = a.search_literature(topic="abelian group", mode="topical", providers=["alpha"])
    assert two["admitted"] is True
    three = a.search_literature(topic="abelian group", mode="topical", providers=["nope"])

    def key(d: dict) -> tuple:
        """一条读数的可比较摘要：做成了没有 / 点名了谁 / 逐源是谁。"""
        return (d.get("ok"), d.get("kind"), d.get("providers_requested"),
                tuple(r["name"] for r in d.get("sources") or []))
    readings = [json.dumps(key(one), ensure_ascii=False),
                json.dumps(key(two), ensure_ascii=False),
                json.dumps(key(three), ensure_ascii=False)]
    assert len(set(readings)) == 3, readings
    assert one["providers_requested"] is None, one
    assert two["providers_requested"] == ["alpha"], two
    assert three["ok"] is False, three


# --------------------------------------------------------------------------- 4. 领取侧


def _row_blind_problems(*, asked: list[str], named: list[str],
                        wired: list[str], sources: list[dict]) -> list[str]:
    """"只看角色级配置、不看请求行"这个缺陷的问题清单（空 = 没这个缺陷）。

    纯函数：正控与负控喂同一段逻辑。判据三条 —— 行上点名的源每个都问了、
    行上没点名的源一个都没问、逐源读数与点名单一致。
    """
    out: list[str] = []
    for name in named:
        if name not in asked:
            out.append(f"行上点名的源 {name!r} 没被问")
    for name in wired:
        if name not in named and name in asked:
            out.append(f"行上没点名的源 {name!r} 被问了（实现又按角色级接线遍历了）")
    rows = [r["name"] for r in sources]
    if sorted(rows) != sorted(named):
        out.append(f"逐源读数是 {rows}，与行上点名的 {named} 对不上")
    return out


def test_the_claim_side_asks_the_sources_named_on_the_row(store):
    """领取侧按请求行点名的源检索：没点名的源一次都不该被问。

    这条是"真的收下并生效"的牙：若实现只把参数收进签名、而检索仍按角色级配置
    遍历，`alpha` 会被问一次 —— 这条立即红。
    """
    add_request(store, "r-0001", topic="hand written", providers=["beta"])
    alpha = _StubProvider("alpha", [_cand("Alpha paper", "10.1/alpha", "alpha")])
    beta = _StubProvider("beta", [_cand("Beta paper", "10.2/beta", "beta")])
    a = _agent(store, alpha, beta)

    res = a.run_once()

    assert res.processed == 1 and res.registered == 1, res.to_dict()
    assert _row_blind_problems(asked=[p.name for p in (alpha, beta) if p.calls],
                               named=["beta"], wired=["alpha", "beta"],
                               sources=res.sources) == [], res.to_dict()
    assert len(beta.calls) == 1, beta.calls
    assert res.providers_requested == ["beta"], res.providers_requested
    assert res.cost["provider_calls"] == 1, res.cost


def test_the_row_blind_check_catches_an_implementation_that_ignores_the_row(monkeypatch, store):
    """负控（改前红的那种）：把选源换成"整个角色接线" ⇒ 同一个检查必须报出来。

    注入点选在领取侧的选源那一处（把"按名字挑"换成"全都挑"），跑完由
    `monkeypatch` 自动还原 —— 盘上的代码一个字节都不动。没有这一条，
    上面那条判据可能只是"实现了恰好只问一个源"。
    """
    add_request(store, "r-0001", topic="hand written", providers=["beta"])
    alpha = _StubProvider("alpha", [_cand("Alpha paper", "10.1/alpha", "alpha")])
    beta = _StubProvider("beta", [_cand("Beta paper", "10.2/beta", "beta")])
    a = _agent(store, alpha, beta)

    real = AgentA._pick_named_providers
    monkeypatch.setattr(AgentA, "_pick_named_providers",
                        lambda self, named: (list(self.providers), []))
    try:
        res = a.run_once()
    finally:
        monkeypatch.setattr(AgentA, "_pick_named_providers", real)

    bad = _row_blind_problems(asked=[p.name for p in (alpha, beta) if p.calls],
                              named=["beta"], wired=["alpha", "beta"],
                              sources=res.sources)
    assert bad, "忽略请求行的实现没被报出来 —— 上面那条判据在这个形态上没有牙"
    assert alpha.calls, "负控注入没生效（alpha 仍然没被问）⇒ 前面的红不构成证据"
    assert AgentA._pick_named_providers is real, "负控必须把选源那一处还原成原样"


def test_the_claim_side_still_walks_the_whole_wiring_when_the_row_names_nothing(store):
    """反真空（同一段逻辑的另一侧）：行上没点名 ⇒ 接线上的源都会被问。

    两条合起来才证明"差别来自请求行"，而不是"实现恰好只问了一个源"。
    """
    add_request(store, "r-0001", topic="hand written")
    alpha = _StubProvider("alpha", [_cand("Alpha paper", "10.1/alpha", "alpha")])
    beta = _StubProvider("beta", [_cand("Beta paper", "10.2/beta", "beta")])
    a = _agent(store, alpha, beta)

    res = a.run_once()

    assert len(alpha.calls) == 1 and len(beta.calls) == 1, (alpha.calls, beta.calls)
    assert res.providers_requested == [], res.providers_requested
    assert res.role_providers == ["alpha", "beta"], res.role_providers
    # 第一态也逐源报状态（2026-10-20 审计 A 的缺陷 6）：改前这里是空数组，
    # 于是"两个源被限流"与"两个源都 0 命中"在读数上同形。现在两个源都在，
    # 且各自带状态 —— 这一条断言的正是"接线上的每一个源都被问过、都有读数"。
    assert [s["name"] for s in res.sources] == ["alpha", "beta"], res.sources
    assert all(s["status"] == "ok" and s["count"] == 1 for s in res.sources), res.sources
    assert res.cost["provider_calls"] == 2, res.cost


# --------------------------------------------------------------------------- 5. 形状与 schema


def test_the_action_readings_have_the_same_shape_as_the_tool_readings(store):
    """两种入口的 `sources[]` / `cost` 逐键同形（工具面是这份口径的真身）。"""
    def _tool_reg(s: Store, *provs) -> ToolRegistry:
        reg = ToolRegistry(name="search")
        reg.bound_role = "A"
        search_tools.register(reg, store=s, providers=list(provs), workspace=s.root)
        return reg

    tool = _tool_reg(store, _StubProvider("s1", [_cand("Paper A", "10.1/a", "s1")]),
                     _StubProvider("s2", [_cand("Paper B", "10.1/b", "s2")]))
    # 题面用英文：动作侧在入队之前有一道"这一问发得出去吗"的判据（纯中文题面会被
    # 判成第三态、根本不进检索），而这一族判的是读数形状，不是那道判据。
    res = tool.call("search.literature", topic="abelian group", mode="topical",
                    providers=["s1", "s2"])
    assert res.ok, res.error
    tool_rows = res.data["sources"]

    # 换一个 store 跑动作面（工具面那一次已经往第一个 store 里登记过文献）。
    with tempfile.TemporaryDirectory(prefix="provider-shape-") as td:
        s2 = Store(Path(td) / "ws")
        s2.init()
        a = _agent(s2, _StubProvider("s1", [_cand("Paper A", "10.1/a", "s1")]),
                   _StubProvider("s2", [_cand("Paper B", "10.1/b", "s2")]))
        out = a.search_literature(topic="abelian group", mode="topical",
                                  providers=["s1", "s2"])

    assert tool_rows and out["sources"], (tool_rows, out["sources"])
    assert set(tool_rows[0]) == set(out["sources"][0]), (sorted(tool_rows[0]), sorted(out["sources"][0]))
    assert set(res.data["cost"]) == set(out["cost"]), (res.data["cost"], out["cost"])
    assert sorted(tool_rows[0]) == sorted(out["sources"][0])


def test_the_schema_field_is_appended_with_a_default_so_old_rows_still_load(store):
    """向后兼容：老行（盘上没有这个键）照样读得进来；新字段有默认值。"""
    row = S.SearchRequest(request_id="r-0001", timestamp=TS, topic="t", mode="broad")
    assert row.providers == []
    row.validate()
    # 盘上那种"没有 providers 键"的 dict ⇒ 默认值接手。
    back = S.row_from_dict("search_requests", {
        "request_id": "r-0002", "timestamp": TS, "topic": "t", "mode": "broad",
        "content_description": "", "done": False,
    })
    assert back.providers == []
    back.validate()
    # seq 的 round-trip：写→读→逐元素相等且顺序不变（`ARRAY_FIELD_KINDS` 的要求）。
    assert S.array_kinds("search_requests")["providers"] == "seq"
    keeper = S.SearchRequest(request_id="r-0003", timestamp=TS, topic="t", mode="broad",
                             providers=["beta", "alpha"])
    keeper.validate()
    with store.tx("search_requests", actor="test") as tx:
        tx.upsert("search_requests", keeper.to_dict())
    sync_counters(store)
    got = next(r for r in store.rows("search_requests") if r["request_id"] == "r-0003")
    assert got["providers"] == ["beta", "alpha"], "序列字段被静默排序了"


def test_a_row_written_before_this_field_existed_still_loads_from_disk(store):
    """盘上已有的行（快照里没有 providers 键）照样读得进来，且被当成第一态。

    这条是向后兼容的端到端证据：不是"dataclass 有默认值"这句话，而是
    "把盘上那一行的键删掉之后，`store` 读得动、`verify` 干净、领取侧按角色接线查"。
    """
    add_request(store, "r-0001", topic="hand written")
    snapshot = store.data / "search_requests.json"
    doc = json.loads(snapshot.read_text(encoding="utf-8"))
    assert "providers" in doc["rows"][0], "夹具前提变了：新写下的行本该带这个键"
    doc["rows"][0].pop("providers")
    snapshot.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    assert store.rows("search_requests")[0].get("providers") is None, \
        "夹具没改到：盘上那一行还带着这个键"
    assert verify_all(store).to_dict()["errors"] == [], "老行读不进来（或是被当成了坏数据）"

    alpha = _StubProvider("alpha", [])
    beta = _StubProvider("beta", [])
    res = _agent(store, alpha, beta).run_once()

    assert res.providers_requested == [], res.to_dict()
    assert res.role_providers == ["alpha", "beta"], res.role_providers
    # 反真空：老行真的走了"按角色接线查"那条路（两个源都被问过）。
    assert len(alpha.calls) == 1 and len(beta.calls) == 1, (alpha.calls, beta.calls)


def test_the_schema_field_rejects_shapes_that_cannot_be_read_back(store):
    """负控（喂坏输入必红）：形状坏的值必须在写盘之前被拒。"""
    base = dict(request_id="r-0001", timestamp=TS, topic="t", mode="broad")
    for bad in ("alpha", ["alpha", ""], ["alpha", 7], [None]):
        with pytest.raises(ValueError, match="providers"):
            S.SearchRequest(**base, providers=bad).validate()


def test_verify_reports_the_field_as_undeclared_when_the_registry_entry_is_gone(store, monkeypatch):
    """负控（改前红）：没有在数组字段登记表里声明 ⇒ `verify` 当场报。

    改前这一格不存在，而 `providers` 是数组 —— 这一条就是"必须同时登记
    set/seq"那条纪律的负控；把它从登记表里摘掉，`verify` 必须报出来。
    """
    store.init()
    with store.tx("search_requests", actor="test") as tx:
        tx.upsert("search_requests", S.SearchRequest(
            request_id="r-0001", timestamp=TS, topic="t", mode="broad",
            providers=["alpha"], done=True, outcome="no_results",
        ).to_dict())
    sync_counters(store)
    clean = verify_all(store).to_dict()
    assert [i for i in clean["errors"] + clean["warnings"]
            if i["code"] == "undeclared_array_field"] == []

    patched = {k: dict(v) for k, v in S.ARRAY_FIELD_KINDS.items()}
    patched["search_requests"].pop("providers")
    monkeypatch.setattr(S, "ARRAY_FIELD_KINDS", patched)
    got = [i for i in verify_all(store).to_dict()["errors"]
           if i["code"] == "undeclared_array_field"]
    assert len(got) == 1 and "providers" in got[0]["message"], got


def test_the_request_row_records_the_sources_without_touching_other_rows(store):
    """请求行上的点名单只属于这一行：同一批里的另一条请求仍按角色接线走。"""
    alpha = _StubProvider("alpha", [_cand("Alpha paper", "10.1/alpha", "alpha")])
    beta = _StubProvider("beta", [_cand("Beta paper", "10.2/beta", "beta")])
    a = _agent(store, alpha, beta)

    first = a.search_literature(topic="abelian group", mode="topical", providers=["beta"])
    second = a.search_literature(topic="abelian group", mode="topical")

    assert first["providers_requested"] == ["beta"]
    assert second["providers_requested"] is None
    rows = {r["request_id"]: r for r in store.rows("search_requests")}
    assert rows[first["request_id"]]["providers"] == ["beta"]
    assert rows[second["request_id"]]["providers"] == [], "点名单不许串到别的请求上"
    # 反真空：两条请求都真的跑完了（不是"没跑所以没有读数"）。
    assert {rows[first["request_id"]]["done"], rows[second["request_id"]]["done"]} == {True}


def test_the_readings_survive_a_round_trip_through_the_run_result(store):
    """`run_once` 的返回值里也带着这份读数（动作层之外的人要靠它复盘）。"""
    add_request(store, "r-0001", topic="hand written", providers=["beta"])
    a = _agent(store, _StubProvider("alpha", []), _StubProvider("beta", [_cand("B", "10.2/b", "beta")]))

    payload = a.run_once().to_dict()

    assert payload["providers_requested"] == ["beta"], payload
    assert [r["name"] for r in payload["sources"]] == ["beta"], payload
    assert payload["cost"]["provider_calls"] == 1, payload
    # 反真空：这几个键不是"永远在、永远是空"—— 上面三条各自绑了一个非空读数。
    assert payload["sources"][0]["count"] == 1, payload


def test_the_run_result_is_a_plain_dict_of_json_safe_values(store):
    """读数必须是能落进事件日志的形状（不是 dataclass 对象、不是 set）。"""
    add_request(store, "r-0001", topic="hand written", providers=["beta"])
    a = _agent(store, _StubProvider("beta", [_cand("B", "10.2/b", "beta")]))
    payload = a.run_once().to_dict()
    text = json.dumps(payload, ensure_ascii=False)
    assert "beta" in text and json.loads(text)["providers_requested"] == ["beta"]


def test_the_dataclass_fields_are_appended_so_positional_construction_still_works():
    """追加字段而不是插队：老的位置参数顺序一个字没动（`asdict` 的键序只会多一个尾巴）。

    这条不是形式主义：`SearchRequest` 的字段顺序是磁盘快照里键的次序，
    也是 `to_dict()` 的输出次序 —— 插队会让"同一行前后两次序列化不同形"。
    """
    names = [f.name for f in dataclasses.fields(S.SearchRequest)]
    assert names[-1] == "providers", names[-5:]
    assert names[:14] == [
        "request_id", "timestamp", "topic", "mode", "content_description", "done",
        "submitted_by", "claimed_by", "lease_until", "attempts", "result_lit_ids",
        "last_error", "outcome", "priority",
    ], names[:14]


# --------------------------------------------------------------------------- 6. returns 收尾面


def _declared_return_keys(spec) -> list[str]:
    """动作声明里 `returns` 那一格"逐键：…"列出的键名（空 = 那一格没有逐键清单）。

    为什么要机器读这一格：主控派活读的是动作声明表，不是实现源码 ——
    声明写着返回某个键而实现不返回（或反过来），调用方就会照一个不存在的读数
    做判断，而没有任何地方会响。题 20 选 A（2026-10-07 所有者裁定）的由头就是这个：
    实现已经多返回了 `sources` / `cost`，声明面还停在四个键上。
    """
    text = str(getattr(spec, "returns", "") or "")
    if "逐键：" not in text:
        return []
    body = text.split("逐键：", 1)[1].split("）", 1)[0]
    return [k.strip() for k in body.split("/") if k.strip()]


def _returns_mismatch(declared: list[str], actual: list[str]) -> list[str]:
    """声明清单与实现键序的差异清单（空 = 逐键一致）。纯函数，正控与负控共用。"""
    out: list[str] = []
    missing = [k for k in actual if k not in declared]
    extra = [k for k in declared if k not in actual]
    if missing:
        out.append(f"实现返回了但声明没写：{missing}")
    if extra:
        out.append(f"声明写了但实现不返回：{extra}")
    if not missing and not extra and declared != actual:
        out.append(f"键集相同而次序不同：声明 {declared} ≠ 实现 {actual}")
    return out


def test_the_declared_returns_are_the_keys_the_implementation_really_returns(store):
    """正控：`A.search_literature` 的 `returns` 清单与实现那个 return 字典逐键相同。

    走真实的成功路径取键（注入替身源，不联网），所以断言的不是"源码里出现过
    这些字符串"，而是"这一次真的返回了这些键、且一个不多一个不少"。
    """
    spec = _spec()
    a = _agent(store, _StubProvider("alpha", [_cand("Alpha paper", "10.1/alpha", "alpha")]))
    out = a.search_literature(topic="abelian group", mode="topical")
    assert out["outcome"] == "ok", out

    declared = _declared_return_keys(spec)
    assert declared, f"returns 那一格不再有逐键清单，机器读不到声明：{spec.returns!r}"
    assert _returns_mismatch(declared, list(out)) == [], (
        f"声明 {declared} 与实现 {list(out)} 分家"
        f"（差异：{_returns_mismatch(declared, list(out))}）")
    # 题 11 的那两个新读数必须在声明里（这一格就是题 20 的落点）
    assert "sources" in declared and "cost" in declared, declared
    # 反真空：清单不是"什么都有" —— 逐源读数与成本之外，老键也在
    assert {"outcome", "result_lit_ids", "providers_requested"} <= set(declared), declared


def test_the_returns_checker_catches_a_missing_or_extra_key():
    """负控：声明漏一个键、多一个实现没有的键、或次序不同 ⇒ 同一个比较必须报出来。

    没有这一条，"逐键相同"这句话可能只是恒真（比较器没牙）。三档各来一次 ——
    漏键正是题 20 改前的形态（`sources` / `cost` 没写进声明）。
    """
    actual = ["ok", "sources", "cost"]
    assert _returns_mismatch(actual, actual) == []
    assert _returns_mismatch(["ok", "cost"], actual), "漏键没被抓住"
    assert _returns_mismatch(["ok", "sources", "cost", "note"], actual), "多键没被抓住"
    assert _returns_mismatch(["cost", "sources", "ok"], actual), "次序不同没被抓住"
    # 改前那种声明（只有四个键）必须被报出来 —— 这就是这一件要修的那一格
    old = ["request_id", "outcome", "result_lit_ids", "literature"]
    assert _returns_mismatch(old, actual), "改前那一格没被报出来 ⇒ 判据在这形态上没牙"
