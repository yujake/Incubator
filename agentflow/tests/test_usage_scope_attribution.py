"""G-20 / G-6：成本归因（每一次 modelgw 调用都带一个显式 `scope`）。

## 这一条要修的缺陷

`USAGE_SCOPES` 有七档（`summon` / `experiment` / `search` / `extract` / `review` /
`reason` / `other`），而账本答不出"搜索/抽取/审校各花了多少" —— 因为唯一的记账入口
`modelcost.charge_reply` 的 `scope` 缺省是 `"reason"`，任何忘记传的调用点都静默落进
那一档。账本的总额与条目数完全自洽，问题只是永远答不出来。

## 这个文件守的三件事

1. 正控：一次多角色流程跑完，账本里 `scope` 分布至少 4 档非零，
   且总额不变（`usage_task_total_mismatch` 不响：分档只改归属，不改数字）。
2. 负控：某一处 `scope` 缺掉/写错 ⇒ 那一档归零或落"未分类"，而且看得见
   （不是静默落进别的档）。
3. `G-6`：每一档归口要么有真实的产出点、要么被显式标注为"没有产出点" ——
   两者在 `by_scope` 的固定零值键里完全同形，所以不能靠读零值来区分。

多角色流程用 `ModelGateway` 的真实现 + 假传输（`transport=` 接缝），
全程离线、秒级、可重复。刻意不自己拼 `Charge` 对象：那样测的就不是
"modelgw → 账本"这条真路径了。

## `G-6` 的处置（为什么 `other` 从词表里消失了）

`modelgw.complete` 的 docstring 自己写着"缺省也不许是「其它」：一个「其他」档会把
「有人忘了写」伪装成一个正常的分类"，而 `"other"` 恰恰在词表里 ——
`Charge(scope="other")` 不拒、`by_scope["other"]` 与正常档同形，那句承诺在数据上
不成立。本仓没有任何地方产出 `other`，所以按"要么有真实产出点、要么不在词表里"
取后者。同一个判据也适用于每一档：`schema.USAGE_SCOPE_PRODUCERS` 逐档登记
（`None` = 本版本没有产出点），并且由 `schema` 在导入期对账。
"""

from __future__ import annotations

import json

import pytest

from agentflow import modelcost as MC
from agentflow import modelgw as G
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tokenmeter import Charge as MeterCharge
from agentflow.tokenmeter import TokenMeter
from agentflow.verify import verify_all

TS = "2026-01-01T00:00:00+00:00"

#: 一次多角色流程：每个角色调一次模型，各自声明自己的用途归口。
#: 顺序与名称照 `USAGE_SCOPES` 里的语义写（不是随便挑四个词）：
#: A 检索 ⇒ search；B 抽取 ⇒ extract；H 审校 ⇒ review；主控整合作答 ⇒ reason。
#: 角色名用 `schema.ROLES` 里的字母（`tasks.role` 只认 A–H 与 M）——
#: 这一步是为了让下面的 tasks 行能真的过 `Task.validate`。
ROLE_FLOW: tuple[tuple[str, str], ...] = (
    ("A", "search"),
    ("B", "extract"),
    ("H", "review"),
    ("M", "reason"),
)


@pytest.fixture
def meter(store: Store) -> TokenMeter:
    return TokenMeter(store, budget_usd=10.0)


def _ok_body(tokens_in: int, tokens_out: int) -> str:
    return json.dumps({
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out},
    }, ensure_ascii=False)


def _gateway(tokens_in: int = 100, tokens_out: int = 20) -> G.ModelGateway:
    """真 `ModelGateway` + 假传输：这正是 `runflow` 生产路径用的那对组合。"""
    def _t(url, headers, data, timeout_sec):  # noqa: ARG001
        return 200, _ok_body(tokens_in, tokens_out)

    return G.ModelGateway(G.ModelSpec(api_key="test-key"), transport=_t,
                          sleep=lambda _s: None, clock=lambda: 0.0)


def _run_multi_role_flow(store: Store, *, flow=ROLE_FLOW) -> dict:
    """跑一次多角色流程：每次调用都带显式 scope，逐笔经 `charge_reply` 入账。

    `task_id` 给 `None`（账本允许的形态）—— 这里要证的是"归口"这一件事，而
    `task_id` 非空却不在 `tasks` 表里会触发 `dangling_usage_task`，所以正控那一组
    刻意不建 tasks 行；带 tasks 行的版本另有一条用例。
    """
    m = TokenMeter(store)
    gw = _gateway()
    charges = []
    for i, (role, scope) in enumerate(flow):
        reply = gw.complete(f"{role} 的 prompt", scope=scope)
        charges.append(MC.charge_reply(m, reply, role=role, scope=scope,
                                       task_id=None, call_index=i, now=TS))
    return {"charges": charges, "spent": m.spent(), "by_scope": m.by_scope(), "meter": m}


def _nonzero(by_scope: dict) -> list[str]:
    return sorted(k for k, v in by_scope.items() if int(v["entries"]) > 0)


# ----------------------------------------------------------------- 正控


def test_a_multi_role_flow_fills_at_least_four_scope_buckets(store: Store):
    """正控：多角色流程跑完 ⇒ 至少 4 档非零，且分档之和等于总额。"""
    out = _run_multi_role_flow(store)
    by_scope = out["by_scope"]

    hit = _nonzero(by_scope)
    assert len(hit) >= 4, f"归口不成立：非零档只有 {hit}（要求 ≥4），全档={by_scope}"
    assert set(hit) == {"search", "extract", "review", "reason"}

    # 每一档的数字必须与它那一笔的来源一致（不是随便塞了个数）
    for _, scope in ROLE_FLOW:
        assert by_scope[scope]["entries"] == 1, by_scope[scope]
        assert by_scope[scope]["tokens"] == 120, by_scope[scope]

    # 总额不变：分档只改归属，不改数字。
    summed = sum(int(v["tokens"]) for v in by_scope.values())
    assert summed == int(out["spent"]["tokens"]) == 4 * 120
    assert sum(int(v["entries"]) for v in by_scope.values()) == 4


def test_every_scope_bucket_is_present_even_when_zero(store: Store):
    """零值档必须在场：`{"search": ...}` 与"没有 search 这一档"不是一回事。"""
    by_scope = _run_multi_role_flow(store)["by_scope"]
    assert set(by_scope) == set(S.USAGE_SCOPES) | {S.SCOPE_UNCLASSIFIED}
    assert by_scope["summon"]["entries"] == 0
    assert by_scope["experiment"]["entries"] == 0
    assert by_scope[S.SCOPE_UNCLASSIFIED]["entries"] == 0
    assert by_scope[S.SCOPE_UNCLASSIFIED]["raw_values"] == []
    # `G-6`：`other` 已从词表里删掉，所以 `by_scope` 里不该有这一档。
    # 留着它会让"有人忘了写归口"有一个长得像正常分类的落位（见模块 docstring）。
    assert "other" not in by_scope, by_scope.keys()
    assert "other" not in S.USAGE_SCOPES


def test_scope_distribution_does_not_raise_usage_task_total_mismatch(store: Store):
    """总额口径不变：记账带 `task_id` 时 `verify_all` 不许报 `usage_task_total_mismatch`。

    这条是"归口改造没有动数字"的全库版证据：给每一次调用配一行 `tasks`
    （`tokens` 取自账本汇总，与 `conductor._set_usage` 同一条口径），
    再看不变量是否安静。
    """
    m = TokenMeter(store)
    gw = _gateway()
    # `task_id` 必须是合法的过程记录号：`schema.PROCESS_ID_PREFIXES["task"] = "t"`
    # 且 `schema._PROCESS_ID_RE` 要求 `t-` + 4 位数字。原先写的是 `t-<角色>`（如 `t-A`），
    # 那从来不是合法号 —— 旧校验只查"非空"所以静默通过，`c-1`/`c-2` 把契约接上之后
    # `Task.validate` 当场拒绝（这是"注释把不存在的形态说成契约"的又一例，已改注释）。
    def _tid(i: int) -> str:
        return f"t-{i + 1:04d}"

    for i, (role, scope) in enumerate(ROLE_FLOW):
        reply = gw.complete(f"{role} 的 prompt", scope=scope)
        MC.charge_reply(m, reply, role=role, scope=scope,
                        task_id=_tid(i), call_index=i, now=TS)
    with store.tx("tasks", actor="test", note="declare") as tx:
        for i, (role, _scope) in enumerate(ROLE_FLOW):
            tid = _tid(i)
            tx.upsert("tasks", {
                "task_id": tid, "role": role, "action": "run_experiment",
                "status": "done", "outcome": "ok", "detail": "归口正控",
                "started_at": TS, "ended_at": TS,
                "tokens": m.tokens_for(tid), "usd": m.usd_for(tid),
            }, note="declare")
    codes = [i.code for i in verify_all(store).issues]
    assert "usage_task_total_mismatch" not in codes, codes
    assert "dangling_usage_task" not in codes, codes


def test_runflow_costs_are_readable_by_scope(store: Store):
    """下游可读：`cost.json` 的形状里 `by_scope` 在场，且逐笔带 scope。"""
    from agentflow import runflow

    out = runflow.run_topic(
        store, topic="归口可读性", budget_usd=1.0, out_dir=store.root / "out",
        transport=lambda url, headers, data, timeout_sec: (200, _ok_body(50, 10)),
        spec=G.ModelSpec(api_key="test-key"), max_calls=2,
        search_fn=lambda topic, *, limit, timeout_sec: [
            {"source": "s", "title": "t", "year": 2000, "doi": "10.1/x", "abstract": "a"}],
        now=TS,
    )
    assert out["exit_code"] == 0, out
    cost = json.loads((store.root / "out" / "cost.json").read_text(encoding="utf-8"))
    by_scope = cost["usage_ledger"]["by_scope"]
    assert set(by_scope) == set(S.USAGE_SCOPES) | {S.SCOPE_UNCLASSIFIED}
    assert by_scope["reason"]["entries"] == 2, by_scope["reason"]
    assert [c["scope"] for c in cost["per_call"]] == ["reason", "reason"]


# ----------------------------------------------------------------- 负控


def test_a_forgotten_scope_is_refused_not_silently_bucketed(store: Store):
    """负控①：某一处 `scope` 注掉 ⇒ 当场报错，该档不会被别的档顶上。

    这是 G-20 要的形态：缺省不许静默落档。`charge_reply` 的 `scope` 是必填的，
    所以"注掉一处 scope"在运行时就是一个 `TypeError`，而不是一个数字悄悄变了。
    同时证明：注掉之后没有任何行落进 `reason` 或 `other`。
    """
    m = TokenMeter(store)
    reply = _gateway().complete("x", scope="search")
    with pytest.raises(TypeError):
        MC.charge_reply(m, reply, task_id=None, call_index=0)  # type: ignore[call-arg]
    assert store.rows("usage_ledger") == [], "被拒的调用不许留下任何一行"
    assert _nonzero(m.by_scope()) == [], "也不许有任何一档被顶上"
    assert m.by_scope()["search"]["entries"] == 0
    # `other` 已不在词表里（`G-6`），所以这里断言的是更强的一件事：
    # 连"落进 other 那一档"这个可能性都不存在了。
    assert "other" not in m.by_scope()


def test_a_scope_outside_the_vocabulary_lands_in_unclassified_visibly(store: Store):
    """负控②：账本里存在编外/空的 scope ⇒ 落显式的"未分类"档，且原值被记下来。

    ## 为什么这一条用假账本行，而不是往真账本里写一行编外值

    写入侧是 fail-closed 的：`UsageEntry.validate` 与 `Charge.validate` 都会当场拒绝
    编外的 scope（`schema.py` 的受控词表断言）。也就是说"编外值出现在账本里"
    这件事在本版本不可能由正常写入产生 —— 它只能来自另一个写入方：
    旧版本进程、或直接改 `data/usage_ledger.json` 的人。

    那么读账那一侧就必须对它有确定的、可见的处置，而不是丢掉或塞进 `other`：
    丢掉会让分档之和小于总额（一个静默的假不一致），塞进 `other` 会把
    "有人写了编外归口"这件事藏起来。这里用一份构造的账本行来验那条读侧判据，
    并同时断言写入侧确实拒绝同一个值 —— 两侧的判据都要有。

    ## 为什么假账本只需要 `rows()`

    `TokenMeter.by_scope` 是纯读侧：它只调 `self.store.rows("usage_ledger")`。
    所以这里注入一个最小替身（而不是真 `Store`），正是为了构造出真 `Store`
    这一版写不出来的那种行。
    """
    bad_rows = [
        {"usage_id": "0000", "scope": "", "role": "legacy", "task_id": None,
         "tokens_in": 7, "tokens_out": 0, "tokens_total": 7, "usd": 0.0,
         "attempts": 1, "at": TS, "note": "历史行：没有归口", "idem_key": ""},
        {"usage_id": "0001", "scope": "shopping", "role": "legacy", "task_id": None,
         "tokens_in": 3, "tokens_out": 0, "tokens_total": 3, "usd": 0.0,
         "attempts": 1, "at": TS, "note": "编外归口", "idem_key": ""},
        {"usage_id": "0002", "scope": "search", "role": "A", "task_id": None,
         "tokens_in": 100, "tokens_out": 20, "tokens_total": 120, "usd": 0.0,
         "attempts": 1, "at": TS, "note": "正常一笔", "idem_key": ""},
    ]

    class _FakeStore:
        """只提供 `rows()` 的最小替身（`by_scope` 只用这一个方法）。"""

        def rows(self, table: str) -> list[dict]:
            assert table == "usage_ledger"
            return [dict(r) for r in bad_rows]

    meter = TokenMeter(_FakeStore())  # type: ignore[arg-type]
    by_scope = meter.by_scope()
    assert by_scope[S.SCOPE_UNCLASSIFIED]["entries"] == 2
    assert by_scope[S.SCOPE_UNCLASSIFIED]["tokens"] == 10
    assert by_scope[S.SCOPE_UNCLASSIFIED]["raw_values"] == ["", "shopping"]
    assert "other" not in by_scope, "编外值不许被塞进一个『其它』档"
    assert by_scope["search"]["entries"] == 1 and by_scope["search"]["tokens"] == 120
    assert _nonzero(by_scope) == sorted(["search", S.SCOPE_UNCLASSIFIED])
    # 分档之和必须仍然等于总额（未分类那一档没把钱弄丢）
    assert sum(int(v["tokens"]) for v in by_scope.values()) == int(meter.spent()["tokens"])

    # 写入侧 counter-check：同一个值写不进去（所以上面那种行只能来自别处）
    with pytest.raises(ValueError, match="scope"):
        S.UsageEntry(usage_id="0003", scope="", at=TS, note="x").validate()
    with pytest.raises(ValueError, match="scope"):
        S.UsageEntry(usage_id="0004", scope="shopping", at=TS, note="x").validate()


def test_reply_and_ledger_scopes_must_agree(store: Store):
    """负控③：网关说 `extract`、入账说 `review` ⇒ 当场报错（两处都自洽而互相矛盾）。"""
    m = TokenMeter(store)
    reply = _gateway().complete("x", scope="extract")
    with pytest.raises(ValueError, match="scope"):
        MC.charge_reply(m, reply, task_id=None, call_index=0, scope="review")
    assert store.rows("usage_ledger") == []


def test_the_ledger_row_records_the_scope_it_was_given(store: Store):
    """落账的那一列必须等于调用点声明的那个值（不是"接近"、不是默认值）。"""
    m = TokenMeter(store)
    reply = _gateway().complete("x", scope="review")
    MC.charge_reply(m, reply, role="H", task_id=None, call_index=0, scope="review", now=TS)
    row = store.rows("usage_ledger")[0]
    assert row["scope"] == "review"
    assert row["role"] == "H"


# ------------------------------------------------------- G-6：产出点登记（三态）

#: 与 :data:`schema.USAGE_SCOPE_PRODUCERS` 逐档对账的固定期望。
#:
#: 为什么把它抄成一份字面量而不是直接读 `schema`：那样会变成同义反复 ——
#: 改 `schema` 里的登记，测试跟着一起改，判据一声不响。抄一份之后，
#: 两边都得改才会绿，而"改了产出点却没改测试"会红。
#:
#: 今天有产出点的只有两档（2026-09-26 全面体检实测，登记册 `G-6`）：
#: `summon` ← `conductor._charge_and_settle` 的 `Charge(scope="summon")`；
#: `reason` ← `runflow` 的作答调用点（`scope=SCOPE_ANSWER`，值是 `"reason"`）。
#: 另外四档今天没有任何生产调用点（A–H 的 `self.llm.complete(prompt)` 走的
#: 是 `llm.LLMExtractor` 的 `.complete(prompt) -> str` 协议，不带 scope）。
#: 这一条不是"接受缺陷"，而是把它变成可判定的：谁哪天把 search 接上了，
#: 就得同时改这里与 `schema`，而不是让读者继续从 `by_scope` 的全零里猜。
#:
#: 2026-09-28：`extract` 从"没有产出点"变成"有产出点"—— 模型读本地文献那条通路
#: （`projects.extract_with_model` → `modelclient.ModelClient`，归口 scope='extract'）
#: 上线，`schema.USAGE_SCOPE_PRODUCERS` 同批改。按上面那句约定，两处都改才允许这张
#: 冻结期望变；只改一处会被 `schema` 的导入期断言或这条断言抓住。
EXPECTED_PRODUCED = {"summon", "reason", "extract"}
EXPECTED_NOT_PRODUCED = {"experiment", "search", "review"}


def test_usage_scope_vocabulary_has_no_other_bucket():
    """`G-6`：词表里不许有"什么都不是"的档。

    `modelgw.complete` 的 docstring 逐字写着"缺省也不许是「其它」：
    一个「其他」档会把「有人忘了写」伪装成一个正常的分类"，而改前 `"other"`
    就在词表里。要么给它一个真实产出点、要么从词表里去掉 —— 本仓没有产出点，
    所以取后者（见模块 docstring 的说明）。
    """
    assert "other" not in S.USAGE_SCOPES, S.USAGE_SCOPES
    assert S.SCOPE_UNCLASSIFIED not in S.USAGE_SCOPES
    # 写入侧（`UsageEntry.validate`，与 `tokenmeter.Charge.__post_init__` 共用同一张词表）
    with pytest.raises(ValueError, match="scope"):
        S.UsageEntry(usage_id="0007", scope="other", at=TS, note="忘了写归口").validate()
    with pytest.raises(ValueError, match="scope"):
        MeterCharge(role="M", scope="other")
    # 网关侧也拒 —— 这是 `modelgw.complete` 的第一道闸。
    with pytest.raises(ValueError, match="scope"):
        _gateway().complete("x", scope="other")


def test_every_scope_is_marked_produced_or_not_produced():
    """`G-6` 的正控：每一档归口都有确定的产出状态，且登记与固定期望一致。

    判据的形状（为什么不是"至少有几个非零"）：`by_scope` 对每一档都给固定键，
    零值档也在场 —— 于是"没有任何产出点"与"查过、没花钱"在产物里同形。
    这里把"哪几档有产出点"钉死，`schema` 那侧再由导入期断言保证词表与登记不脱节。
    """
    production = S.usage_scope_production()
    assert set(production) == set(S.USAGE_SCOPES), production
    assert {s for s, st in production.items() if st == "produced"} == EXPECTED_PRODUCED
    assert set(S.scopes_without_producer()) == EXPECTED_NOT_PRODUCED
    assert S.SCOPE_UNCLASSIFIED not in production, "未分类档不是归口，不进这张表"


def test_producer_registry_and_vocabulary_cannot_drift():
    """`G-6` 的负控：改了词表却漏改登记 ⇒ 导入期对账断言必须红。

    注入是真的改 `schema` 的两张表（随后恢复），所以这条负控证明的是
    "判据真的读那两张表"，而不是"判据恰好对某个字面量成立"。
    `_assert_usage_scope_production_contract` 的恢复调用同时证明
    "这条负控没把模块状态改坏"。
    """
    scopes_snapshot = tuple(S.USAGE_SCOPES)
    producers_snapshot = dict(S.USAGE_SCOPE_PRODUCERS)
    try:
        # ① 词表多一档、登记里没有它 ⇒ 红
        S.USAGE_SCOPES = scopes_snapshot + ("brand_new_scope",)  # type: ignore[assignment]
        with pytest.raises(AssertionError) as ei:
            S._assert_usage_scope_production_contract()
        assert "brand_new_scope" in str(ei.value), str(ei.value)
        # ② 登记里多一档、词表里没有它 ⇒ 也红（另一侧的不对称）
        S.USAGE_SCOPES = scopes_snapshot  # type: ignore[assignment]
        S.USAGE_SCOPE_PRODUCERS["ghost_scope"] = None
        with pytest.raises(AssertionError) as ei2:
            S._assert_usage_scope_production_contract()
        assert "ghost_scope" in str(ei2.value), str(ei2.value)
    finally:
        S.USAGE_SCOPES = scopes_snapshot  # type: ignore[assignment]
        S.USAGE_SCOPE_PRODUCERS.clear()
        S.USAGE_SCOPE_PRODUCERS.update(producers_snapshot)
    # 恢复之后必须重新变绿。
    S._assert_usage_scope_production_contract()


def test_runflow_only_produces_scopes_that_are_registered_as_produced(store: Store):
    """`G-6` 的端到端一侧：真实 `run_topic` 的 `cost.json` 里，非零档必须都是
    登记为 `produced` 的那些；登记为 `not_produced` 的档必须仍然是 0。

    这条把"登记"与"真实产物"接上：登记说 `search` 没有产出点，那么跑完整条
    runflow 之后 `by_scope["search"]` 就必须还是 0（而不是某个数字悄悄非零）。
    """
    from agentflow import runflow

    out = runflow.run_topic(
        store, topic="产出点对账", budget_usd=1.0, out_dir=store.root / "out",
        transport=lambda url, headers, data, timeout_sec: (200, _ok_body(50, 10)),
        spec=G.ModelSpec(api_key="test-key"), max_calls=2,
        search_fn=lambda topic, *, limit, timeout_sec: [
            {"source": "s", "title": "t", "year": 2000, "doi": "10.1/x", "abstract": "a"}],
        now=TS,
    )
    assert out["exit_code"] == 0, out
    cost = json.loads((store.root / "out" / "cost.json").read_text(encoding="utf-8"))
    by_scope = cost["usage_ledger"]["by_scope"]
    production = S.usage_scope_production()
    for scope in S.USAGE_SCOPES:
        entries = int(by_scope[scope]["entries"])
        if production[scope] == "not_produced":
            assert entries == 0, (
                f"{scope} 登记为 not_produced，但真实 run 产出 {entries} 笔 ⇒ "
                "要么登记过期、要么有别的调用点悄悄写了这一档（G-6）"
            )
    assert int(by_scope["reason"]["entries"]) >= 1, by_scope["reason"]
