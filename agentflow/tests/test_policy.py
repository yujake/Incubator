"""策略层测试（`policy.py` + `capabilities.py` 的装配期自检）。

这一层是纯函数，所以它的测试不需要 store、不需要线程、不需要时间 ——
"策略对不对"必须能在没有编排器的情况下被单独回答。
"""

from __future__ import annotations

import pytest

from agentflow import capabilities as C
from agentflow import policy as P
from agentflow import schema as S


# ---------------------------------------------------------------- ActionSpec / 装配期自检


def test_assert_capabilities_passes_on_real_code():
    """装配期自检本身必须过 —— 它断言的是"能力表与真实代码一致"。

    它不返回布尔值而是抛（fail-closed）。这里显式调一次，
    让"能力表漂移"在测试里也有一条具名用例，而不是只在 import 时体现。
    """
    C.assert_capabilities()


def test_capabilities_keys_equal_schema_roles_plus_conductor():
    """判据只有一处：`schema.ROLES`（+ 主控）。"""
    assert set(C.CAPABILITIES) == set(S.ROLES) | {S.CONDUCTOR_ROLE}
    assert set(C.WRITE_SETS) == set(S.ROLES) | {S.CONDUCTOR_ROLE}


def test_conductor_has_no_agent_actions():
    """主控没有 Agent 动作 —— 它的动作是 `summon` 本身。

    这条断言把"主控不产出领域对象"从一句设计口号变成可判定的事实。
    """
    assert C.CAPABILITIES[S.CONDUCTOR_ROLE] == ()


def test_every_action_handler_really_exists():
    """负控：编造一个不存在的动作名必须让自检当场炸。

    正控（真表过）见上；这里改一个 handler_name 再断言它炸，
    否则"装配期自检"可能只是碰巧通过（例如它实际上什么都没核）。
    """
    spec = C.CAPABILITIES["C"][0]
    forged = C.ActionSpec(
        "C", "hottest", spec.summary, spec.params, spec.returns,
        side_effect=spec.side_effect, handler_name="this_method_does_not_exist",
    )
    original = C.CAPABILITIES["C"]
    C.CAPABILITIES["C"] = (forged, *original[1:])
    try:
        with pytest.raises(AssertionError, match="this_method_does_not_exist"):
            C.assert_capabilities()
    finally:
        C.CAPABILITIES["C"] = original


def test_readonly_role_write_sets_are_declared_exceptions():
    """只读角色的写集必须为空，或显式登记为产出表。

    这不是形式主义：C 写 `analysis_reports`、H 写 `review_findings`，
    都是真的。把它们藏起来（写成空集）会让"只读"从一个事实变成一个谎言，
    而谎言不会报错 —— 它只会让下一次有人给 C 加一个写动作时不触发任何检查。
    """
    from agentflow.tools import READ_ONLY_ROLES

    for role in READ_ONLY_ROLES:
        ws = C.WRITE_SETS[role]
        allowed = C.READ_ONLY_WRITE_EXCEPTIONS.get(role, frozenset())
        assert ws <= allowed, f"{role} 的写集 {sorted(ws)} 超出已登记的例外 {sorted(allowed)}"


def test_readonly_exception_is_not_a_blank_cheque():
    """负控：给 C 加一张未登记的写表 ⇒ 自检必须炸。

    没有这条负控，`READ_ONLY_WRITE_EXCEPTIONS` 就可能宽到"什么都允许"。
    """
    original = C.WRITE_SETS["C"]
    C.WRITE_SETS["C"] = frozenset({"relations"})
    try:
        with pytest.raises(AssertionError, match="未登记"):
            C.assert_capabilities()
    finally:
        C.WRITE_SETS["C"] = original


def test_conditional_write_cannot_silently_disappear():
    """裁决 3 的判据：C 的条件性写必须留在写集里，且不许静默消失。

    这条断言的作用是：有人把 `agent_c._submit_gap_requests` 删掉（或把
    `gaps(submit_requests=True)` 的写入面挪走）时，这条测试会红 ——
    而不是让"只读角色的写面"悄悄变窄，然后某天有人以为 C 从不写。

    背景（两句话，说的是两件事）：
    - 工具层的 `ToolSpec.side_effect` 描述默认调用的副作用
      （`submit_requests` 默认 False ⇒ 默认纯读，所以 `graph.gaps` 的
      `side_effect="read"` 是对的，不该改成写工具 —— 改了会被
      `for_role` 从 C 的工具面里过滤掉，反而砍掉 C 的核心能力）；
    - 能力层的 `WRITE_SETS` 描述可能写的表 —— 条件性写也算可能写。
    """
    assert "search_requests" in C.WRITE_SETS["C"], (
        "C 的 I3 缺口直连（agent_c._submit_gap_requests，默认关闭）会写 "
        "search_requests —— 这是受控例外，必须留在写集里。删掉它 = 只读角色的"
        "写面静默变窄，而那正是这条测试要防的事"
    )
    assert C.READ_ONLY_WRITE_EXCEPTIONS["C"] >= C.WRITE_SETS["C"], (
        "写集里的每一项都必须在受控例外表里登记（否则 assert_capabilities 会抛）"
    )
    # 三张知识表零写入点 —— 这条比"search_requests 在里面"更重要：
    # 它才是"C 只读"这句话的实际内容。
    assert not (C.WRITE_SETS["C"] & {"literature", "concepts", "relations"}), (
        "C 的写集里出现了知识表 —— 那才是真正的越界（工具面只读 + 三张知识表零写入）"
    )


def test_side_effect_read_describes_default_call_only():
    """裁决 3 的另一半：`gaps` 的 `side_effect` 必须是 `read`，不许改成写。

    为什么这条也要有测试：最"直白"的修法就是把 `gaps` 标成 `write_local`，
    而那会让 `ToolRegistry.for_role("C")` 把它从只读角色的工具面里过滤掉
    （`tools/base.py:335`）—— 一个措辞修正变成能力删除。这条测试钉住那个决定。
    """
    spec = C.find_action("C", "gaps")
    assert spec is not None
    assert spec.side_effect == "read", (
        "gaps 的默认调用是纯读（submit_requests 默认 False）；"
        "标成写会让 for_role 把它从 C 的工具面里去掉 —— 照字面修反而更坏"
    )
    assert "search_requests" in C.WRITE_SETS["C"], "而可能写的口径必须留在写集里"


def test_allowed_edges_match_design_table():
    """§3.1 的表逐条实现 —— 尤其 C 的边是空的。

    2026-09-30（`draft/28` §199，人批准）：给 `G` 加 `A`、给 `H` 加 `A`/`E`。
    理由逐字写在 `capabilities.ALLOWED_EDGES` 那两行上：G 原状能要形式化（E）
    却叫不动 A 去查一份原文；H 是"发现者"却只能请 G 修订 —— 发现问题的人
    不能去要证据。H 是只读角色这件事没变：新加的两条边只让它"请求"，
    `READ_ONLY_ROLES` 与它的写面一个字未动（下面那条断言仍然成立）。
    """
    assert C.ALLOWED_EDGES["C"] == frozenset(), "C 一旦能发起动作就成了绕过 B 引文回验的写入路径"
    assert C.ALLOWED_EDGES["H"] == frozenset({"A", "E", "G"}), \
        "审校者可以向 A/E 要证据、请 G 修订，但**不许自己改数据**（它的只读面在 tools 层）"
    assert C.ALLOWED_EDGES["A"] == frozenset({"B"})
    assert C.ALLOWED_EDGES["B"] == frozenset({"C"})
    assert C.ALLOWED_EDGES["D"] == frozenset({"A", "B", "C", "E", "F"})
    assert C.ALLOWED_EDGES["E"] == frozenset({"B", "D"})
    assert C.ALLOWED_EDGES["F"] == frozenset({"A", "B", "C", "D", "E", "V"})
    assert C.ALLOWED_EDGES["G"] == frozenset({"A", "D", "E", "F"})
    # `V`（验证者）只与 F 交互：出边只有 F（用户 2026-10-05 第七轮裁定）。
    assert C.ALLOWED_EDGES["V"] == frozenset({"F"})
    # 主控的出边（业主 2026-10-10 第 146 轮第 4 条裁定：「不许直接控制 B、F、V，
    # 只可间接由父代理转达」）。改前它是 `frozenset(S.ROLES)` 九条；
    # 改后少这三个，而三条间接路径各自有判据（见本文件下面那两条负控）。
    assert C.ALLOWED_EDGES["M"] == frozenset({"A", "C", "D", "E", "G", "H"}), \
        "主控的直接出边：B / F / V 按裁定必须走父代理（B 走 A、F 走 D、V 走 F）"
    # 负控（这条改动最该守住的边界）：H 与 V 仍然是只读角色 —— 新加的两条边只让它
    # "请求"，权限面（工具层）没有跟着动。
    from agentflow.tools import READ_ONLY_ROLES as _RO

    assert tuple(_RO) == ("C", "H", "V"), _RO


def test_unknown_edge_target_is_rejected():
    """负控：边表里塞一个拼错的角色名 ⇒ 自检必须炸。

    拼法不一致（`"agent-A"` vs `"A"`）在本项目里已经出现过一次
    （`research_tools` 的 roles），症状是静默少几个工具。边表同理：
    拼错 ⇒ 每一次 `M → A` 都被判 forbidden_edge，而"策略拒绝了"看起来像正常工作。
    """
    original = frozenset(C.ALLOWED_EDGES["M"])
    C.ALLOWED_EDGES["M"] = frozenset({"agent-A"})
    try:
        with pytest.raises(AssertionError, match="非角色目标"):
            C.assert_capabilities()
    finally:
        C.ALLOWED_EDGES["M"] = original


def test_negative_control_missing_a_role_in_the_conductor_edges_is_rejected():
    """负控（`FINAL-R4-01`）：主控够不到某个角色（值少一个）⇒ 能力层自家判据必须炸。

    这一条钉的是"键集判据看不见的那一半"：`set(ALLOWED_EDGES) >= set(S.ROLES)`
    只问"每个角色有没有出边条目"，不问"主控能不能够到每一个角色"。
    实测（R4 批）：把 `ALLOWED_EDGES["M"]` 写成 7 元字面量后，
    按权限相关的 7 个测试文件跑子集全绿（守点在别处）。

    ## 2026-10-10 口径更新（裁定第 4 条之后）

    改前这里删的是最后一条直接边（因为当时"够得到"等价于"直接边里有它"）。
    裁定之后"直接边里有它"不再是必要条件 ⇒ 删直接边不再必然让判据炸
    （删 B / F / V 正是裁定要的形态）。所以负控改成删一条会被别人间接补回来也不算够
    的边：这里删 `H`（H 的进路只有主控这一条，删掉它以后整个图里到不了 H）——
    `test_the_three_indirect_roles_still_have_a_path` 从另一面钉住"间接那三条还在"。
    """
    original = frozenset(C.ALLOWED_EDGES["M"])
    assert original == frozenset({"A", "C", "D", "E", "G", "H"}), \
        "前提：真表上主控的直接出边就是这六个（裁定第 4 条之后）"
    C.ALLOWED_EDGES["M"] = frozenset(sorted(original)[:-1])   # 去掉 'H'
    try:
        with pytest.raises(AssertionError, match="到不了这些角色"):
            C.assert_capabilities()
    finally:
        C.ALLOWED_EDGES["M"] = original


def test_write_set_of_unknown_role_is_conservative():
    """未知角色的写集不是空集 —— 空集等于"它可以和任何人并发"。

    三态纪律在这里的形态是"不知道 ⇒ 保守"。这条断言防止有人把
    `write_set_of` 的未知分支"简化"成返回 frozenset()。
    """
    assert C.write_set_of("不存在的角色") == C.write_set_of("Z")
    assert len(C.write_set_of("Z")) > 0, "未知角色必须被当成写者"


# ---------------------------------------------------------------- 两根轴（effect × external）

def test_axis_vocabularies_have_exactly_one_source():
    """两根轴的词表各只有一份：`capabilities` 与 `tools.base` 必须逐字一致。

    形态照抄既有的 `set(SIDE_EFFECTS) == set(TOOL_SIDE_EFFECTS)`（第 5 条）。
    两处字面量分叉的症状不是崩溃，而是"两套说法都自洽"（FC-03）。
    """
    from agentflow.tools.base import EFFECT as TOOL_EFFECT
    from agentflow.tools.base import EXTERNAL as TOOL_EXTERNAL

    assert set(C.EFFECT) == set(TOOL_EFFECT)
    assert set(C.EXTERNAL) == set(TOOL_EXTERNAL)
    assert set(C.EFFECT) == {"none", "read", "write_local"}
    assert set(C.EXTERNAL) == {"none", "egress", "exec"}


def test_write_sets_non_empty_implies_a_write_like_axis():
    """交叉断言一：写集非空（减掉已登记的只读例外）⇒ 该角色有 `_WRITE_LIKE` 的动作。

    正控是真表（`assert_capabilities()` 已经跑过）；这里是负控：
    把某个写角色的全部动作改成 `read`，这条断言必须炸 ——
    否则"写集与效果轴一致"就只是一句注释。
    """
    original = C.CAPABILITIES["A"]
    forged = tuple(
        C.ActionSpec(s.role, s.action, s.summary, s.params, s.returns,
                     side_effect="read", handler_name=s.handler_name)
        for s in original
    )
    C.CAPABILITIES["A"] = forged
    try:
        with pytest.raises(AssertionError, match="WRITE_SETS"):
            C.assert_capabilities()
    finally:
        C.CAPABILITIES["A"] = original


def test_two_layer_declarations_agree_on_the_real_tree():
    """交叉断言二：两层声明在真实树上必须说同一句话（P-13 §10 第 3 条已收敛）。

    实测的那一处是 `verify.check_formal`：工具层声明 `read`、能力层声明
    `network`（遗留取值），而"没有任何机器判据看见过"它（R006 只看工具层且是
    文件级共现；R006 现已退休，判据面移入 R010 的逐工具判定）。
    B3 收官把两层同批改成 `read` + `exec` ⇒ 这条不一致消失。

    这条用例因此从"断言不一致存在"翻成"断言不一致不存在"：
    它仍然是一条可红的判据（下面两条用例把两层各自改错，验证判据真的会报）。
    """
    got = C.declaration_divergences()
    codes = {d.code for d in got}
    assert "two_layer_name_unmatched" in codes, "找不到对应工具的动作必须被报出来（不是'一致'）"
    # 遗留取值带来的两类码随那个取值一起消失：它们现在是死码。
    assert "two_layer_legacy_overclaims" not in codes, sorted(codes)
    assert "two_layer_legacy_imprecise" not in codes, sorted(codes)
    # 真实树上两层零分歧（除"没有比对"这一类 info 之外）。
    hard = [d for d in got if d.code.startswith("two_layer_") and d.code != "two_layer_name_unmatched"]
    assert hard == [], [d.to_dict() for d in hard]


def test_two_layer_legacy_overclaim_is_still_detectable(monkeypatch):
    """正控：内部轴估值函数对同一份声明给出一致结果（判据没有变成恒真）。

    为什么要保留这条正控：真实树现在"两层一致"，于是 `declaration_divergences`
    很容易退化成一条恒真的断言（`G-19`：门接上了，但什么都没比）。
    这里把工具层的声明改成"没写 external"（第三分量为假）并把能力层也清成
    未迁移形态，验证：

    1. `_tool_axes` 原样读出 `(side_effect, external, explicit)` —— 它不再查
       任何翻译表，第三个分量就是"人写没写这个字段"；
    2. 两边都未迁移时，判据不报任何 external 分歧（默认 `none` 对 `none`）。
    """
    base = C._tool_side_effects()
    assert base["verify.check_formal"] == ("read", "exec", True), base["verify.check_formal"]
    assert C._tool_axes(("read", "none", False)) == ("none", "read", False)
    assert C._tool_axes(base["verify.check_formal"]) == ("exec", "read", True)

    monkeypatch.setattr(C, "_tool_side_effects",
                        lambda: {**base, "verify.check_formal": ("read", "none", False)})
    original = C.CAPABILITIES["E"]
    C.CAPABILITIES["E"] = tuple(
        C.ActionSpec(s.role, s.action, s.summary, s.params, s.returns,
                     side_effect=s.side_effect,
                     handler_name=s.handler_name,
                     external=None if s.action == "check_formal" else s.external)
        for s in original
    )
    try:
        got = [d for d in C.declaration_divergences()
               if "E.check_formal" in d.where and d.code in
               ("two_layer_external_divergence", "two_layer_external_imprecise")]
        assert got == [], [d.to_dict() for d in got]
    finally:
        C.CAPABILITIES["E"] = original


def test_two_layer_divergence_is_real_when_the_capability_understates(monkeypatch):
    """负控：能力层低估风险轴时必须报 error（而不是被"保守"吞掉）。

    正控是真树：`E.check_formal` 两层都说 `read` + `exec`，没有 error。
    负控把能力层的 `external` 抹掉（回到"没迁移"的默认值），
    而工具层仍然声明 `exec` ⇒ 能力层低估了风险轴，必须报 error。
    """
    base = C._tool_side_effects()
    assert base["verify.check_formal"] == ("read", "exec", True), base["verify.check_formal"]
    original = C.CAPABILITIES["E"]
    C.CAPABILITIES["E"] = tuple(
        C.ActionSpec(s.role, s.action, s.summary, s.params, s.returns,
                     side_effect=s.side_effect,
                     handler_name=s.handler_name,
                     external=None if s.action == "check_formal" else s.external)
        for s in original
    )
    try:
        got = [d for d in C.declaration_divergences() if d.code == "two_layer_external_divergence"]
        assert any("E.check_formal" in d.where for d in got), got
        assert all(d.level == "error" for d in got)
    finally:
        C.CAPABILITIES["E"] = original


def test_two_layer_external_imprecise_is_a_warning_not_an_error():
    """新增判据：两层都非 `none` 但精度不同 ⇒ warning（`two_layer_external_imprecise`）。

    为什么它不能是 error：两层都承认"这个动作会触到我们不拥有的事"，
    风险面没有被低估，只是精度不同（出网与起进程的承接方式不同）。
    为什么它也不能不报：静默会让"精度不同"变成一件没人看得见的事 ——
    而报告里看不见的分歧等于不存在（P15 的反面用法：可见但不升级）。
    """
    spec = C.ActionSpec("E", "probe", "样本动作", {"type": "object", "properties": {}},
                        handler_name="run_experiment", side_effect="read", external="egress")
    base = C._tool_side_effects()
    # `verify.run_experiment` 工具层声明 exec，这个替身让能力层说 egress。
    got = C.declaration_divergences_for({"E": (spec,)}, base)
    hits = [d for d in got if d.code == "two_layer_external_imprecise"]
    assert hits, [d.to_dict() for d in got]
    assert all(d.level == "warning" for d in hits)
    # 负控：两边一致时不许报（否则它会变成一条常驻噪音）
    same = C.ActionSpec("E", "probe", "样本动作", {"type": "object", "properties": {}},
                        handler_name="run_experiment", side_effect="read", external="exec")
    assert [d for d in C.declaration_divergences_for({"E": (same,)}, base)
            if d.code == "two_layer_external_imprecise"] == []


def test_unmapped_actions_are_reported_not_silently_treated_as_consistent():
    """三态：没比对 ≠ 一致。找不到对应工具的动作必须出现在清单里。

    这条断言是 P16（判据真空通过）的形态：一条规则若把"没查到"当成"没问题"，
    它的"全绿"就没有任何信息量。
    """
    unmapped = C.unmapped_actions()
    assert unmapped, "真实树上不可能每个动作都有唯一对应的工具 —— 若为空，说明映射判据被放宽了"
    assert ("C", "hottest") in unmapped, unmapped
    assert C.STRICT_DECLARATIONS is False, (
        "STRICT_DECLARATIONS 只在 B3 把两层声明同批改完之后才翻 True；"
        "在还有不一致时翻它会让 import agentflow.capabilities 永久失败"
    )


# ---------------------------------------------------------------- Policy.validate


def test_policy_validate_rejects_each_missing_limit():
    """FC-18：四类上限缺任一类都可以被绕过，所以每个都必须为正数。"""
    for field_name in ("max_depth", "max_fanout", "max_concurrency", "max_tasks_per_run"):
        for bad in (0, -1):
            with pytest.raises(ValueError, match=field_name):
                P.Policy(**{field_name: bad})


def test_policy_validate_rejects_non_int_limits():
    """负控：`None` 不能通过 —— 那会让"我忘了设"与"我决定不限"长得一模一样。"""
    with pytest.raises(ValueError, match="max_concurrency"):
        P.Policy(max_concurrency=None)  # type: ignore[arg-type]


def test_policy_defaults_have_all_four_limits():
    p = P.Policy()
    assert P.assert_policy_complete(p) is None
    # 资源类上限允许 None（不限），且保持 None，不许折叠成 0
    d = p.to_dict()
    assert d["token_budget"] is None and d["usd_budget"] is None
    assert d["wall_clock_sec"] == 900


def test_policy_is_frozen_value_object():
    """策略是值对象：出生时合法，之后不可变（改了它等于改了判据的依据）。"""
    p = P.Policy()
    with pytest.raises(Exception):
        p.max_depth = 9  # type: ignore[misc]


def test_negative_budget_is_rejected():
    with pytest.raises(ValueError, match="token_budget"):
        P.Policy(token_budget=-1)
    with pytest.raises(ValueError, match="usd_budget"):
        P.Policy(usd_budget=-0.5)


# ---------------------------------------------------------------- check_edge：每一条判据


def _d(**kw) -> P.Decision:
    base = dict(frm="M", to="C", action="hottest")
    base.update(kw)
    return P.Decision(**base)


def test_check_edge_allows_legal_edge():
    assert P.check(P.Policy(), _d()) is None


def test_unknown_role_and_unknown_action_are_different_refusals():
    """两种失败必须分开：人不存在 vs 人存在但没这个本事。"""
    r1 = P.check(P.Policy(), _d(to="Z"))
    assert r1 is not None and r1.reason == "unknown_role"
    r2 = P.check(P.Policy(), _d(action="没有这个动作"))
    assert r2 is not None and r2.reason == "unknown_action"


def test_summoning_the_conductor_is_a_forbidden_edge_not_an_unknown_action():
    """`G-11`：召唤主控必须报 `forbidden_edge`，而不是 `unknown_action`。

    ## 为什么这条断言换过 reason（这是断言错，不是实现错）

    改前这里断言的是 `unknown_action`（附一句"主控没有 Agent 动作"）。
    那条断言之所以能一直是绿的，是因为 `check` 把整件事交给了
    `check_action`：它在第一步就把 `to == S.CONDUCTOR_ROLE` 判成
    `unknown_action` 并返回，于是 `NON_SUMMONABLE` 那条显式判据
    （连同它 docstring 里"不靠 `ALLOWED_EDGES` 里没人写 M 这个偶然事实"的理由）
    从来执行不到 —— 登记册 `G-11` 的实测就是"两条判据不可达"。

    代价是读者拿到 `unknown_action` 会以为"角色名拼错了 / 动作不存在"，
    而事实上发生的是"召唤主控这件事本身不允许"。两者处置相反：
    前者去查名字，后者去改设计。所以按 `G-11` 的验收判据改成 `forbidden_edge`，
    并把"主控没有 Agent 动作"这半句留给 `check_action` 自己的用例
    （`tests/test_coverage_policy.py::test_check_action_accepts_the_conductor_role_presence_but_never_an_action`
    —— 那一层一个字符没动）。
    """
    r3 = P.check(P.Policy(), _d(to=S.CONDUCTOR_ROLE, action="summon"))
    assert r3 is not None and r3.reason == "forbidden_edge", (
        "召唤主控必须报 forbidden_edge（`G-11`）；拿到 unknown_action 说明 "
        "NON_SUMMONABLE 判据又不可达了"
    )
    assert r3.limit == "edge", r3
    assert S.CONDUCTOR_ROLE in r3.detail, r3.detail


def test_forbidden_edge_c_to_b():
    """越权边（C → B）⇒ forbidden_edge，且理由在受控词表里。"""
    r = P.check(P.Policy(), _d(frm="C", to="B", action="run_once"))
    assert r is not None
    assert r.reason == "forbidden_edge"
    assert r.reason in S.REFUSAL_REASONS
    assert "C" in r.detail and "B" in r.detail


def test_forbidden_edge_takes_priority_over_depth():
    """顺序是判据的一部分：越权优先于深度。

    `C → B` 无论在什么深度都是越权；报 depth_exceeded 会让人以为"再浅一点就行"。
    """
    r = P.check(P.Policy(max_depth=1), _d(frm="C", to="B", action="run_once", depth=99))
    assert r is not None and r.reason == "forbidden_edge"


def test_depth_exceeded():
    r = P.check(P.Policy(max_depth=3), _d(depth=4))
    assert r is not None and r.reason == "depth_exceeded"


def test_depth_boundary_is_allowed():
    """边界正控：`depth == max_depth` 必须放行 —— 否则"默认值"会变成"默认值减一"。"""
    assert P.check(P.Policy(max_depth=3), _d(depth=3)) is None


def test_the_default_depth_is_five_after_the_2026_10_08_ruling():
    """默认深度 3 → 5（所有者 2026-10-08：「我们限制递归调用深度为5，毕竟
    20*(5*5*5*5) 也非常可观了」）。

    两件事：①默认值就是 5（链 `M(1) → A(2) → B(3) → C(4) → D(5)` 到底）；
    ②边界精确 —— 第 5 层放行、第 6 层拒。为什么把默认值也钉住：它是"并行规模的
    上界"里那一根轴（名额逐实例 ⇒ 沿链相乘 20×5⁴），改它要跟着改所有者那句话。
    """
    p = P.Policy()
    assert p.max_depth == 5, p.to_dict()
    assert P.check(p, _d(depth=5)) is None, "第 5 层必须放行"
    r = P.check(p, _d(depth=6))
    assert r is not None and r.reason == "depth_exceeded", r


def test_cycle_detected():
    anc = (("A", "run_once", "k"), ("B", "run_once", "k2"))
    r = P.check(P.Policy(), _d(frm="B", to="C", action="hottest", key=("A", "run_once", "k"),
                               ancestry=anc))
    assert r is not None and r.reason == "cycle_detected"


def test_cycle_uses_input_key_not_all_params():
    """判重键是 `(role, action, input_key)`。

    同样的 (role, action) 但不同的 input_key 是进展，不是活锁。
    这条负控防止有人"简化"成只看 (role, action) —— 那会让
    "对第二个问题问同一个角色"被误判成循环。
    """
    anc = (("A", "run_once", "k1"),)
    assert P.check(P.Policy(), _d(frm="M", to="A", action="run_once",
                                  key=("A", "run_once", "k2"), ancestry=anc)) is None
    r = P.check(P.Policy(), _d(frm="M", to="A", action="run_once",
                               key=("A", "run_once", "k1"), ancestry=anc))
    assert r is not None and r.reason == "cycle_detected"


def test_fanout_exceeded():
    """默认档（工人）的扇出上限 = `Policy.max_fanout`，在 `>=` 处拒。

    为什么这里显式写 `frm="A"`（而 `_d` 的默认 frm 是 M）：上限按发起方角色取
    （题15 选B，2026-10-07），主控那一档是 20，不写 frm 就会测到主控档上。
    主控档自己的判据见 `test_fanout_limit_is_per_initiator_role`。
    """
    r = P.check(P.Policy(max_fanout=2), _d(frm="A", to="B", action="run_once", fanout=2))
    assert r is not None and r.reason == "fanout_exceeded"
    assert P.check(P.Policy(max_fanout=2),
                   _d(frm="A", to="B", action="run_once", fanout=1)) is None


def test_fanout_limit_is_per_initiator_role():
    """扇出上限按发起方角色取：主控一档 = 20，默认档 = `Policy.max_fanout`。

    20 这个数钉在判据里是刻意的：它是一条人裁的编排余量（题15 选B，2026-10-07），
    改它应当先改那一处裁定，而不是顺手调一个常量。口径在 2026-10-08 被所有者
    改成"单时刻在飞"（`fanout` = 此刻还没返回的子代理数；见 `policy` 的模块 docstring），
    这里的 `_d(fanout=…)` 直接给的就是那个数。
    """
    p = P.Policy()
    assert P.fanout_limit_for(p, S.CONDUCTOR_ROLE) == 20
    assert P.fanout_limit_for(p, "A") == p.max_fanout == 5
    # 反真空：两档都真的会拒，报文里能读出"此刻在飞几个"与"上限是多少"。
    worker = P.check(p, _d(frm="A", to="B", action="run_once", fanout=5))
    assert worker is not None and worker.reason == "fanout_exceeded"
    assert "在飞 5" in worker.detail and "上限 5" in worker.detail, worker.detail
    assert P.check(p, _d(frm="M", to="A", action="run_once", fanout=6)) is None
    boss = P.check(p, _d(frm="M", to="A", action="run_once", fanout=20))
    assert boss is not None and boss.reason == "fanout_exceeded"
    assert "在飞 20" in boss.detail and "上限 20" in boss.detail, boss.detail
    # 报文要说清那个 20 是从哪来的（否则读的人会以为上限就是 policy.max_fanout）
    assert "FANOUT_LIMIT_BY_ROLE" in boss.detail and "policy.max_fanout=5" in boss.detail


def test_concurrency_exceeded():
    r = P.check(P.Policy(max_concurrency=4), _d(running=4))
    assert r is not None and r.reason == "concurrency_exceeded"
    assert P.check(P.Policy(max_concurrency=4), _d(running=3)) is None


def test_total_tasks_budget_exceeded():
    r = P.check(P.Policy(max_tasks_per_run=10), _d(total=10))
    assert r is not None and r.reason == "budget_exceeded"
    assert r.limit == "max_tasks_per_run"


def test_token_budget_exhausted_and_estimate():
    """预算判定有两档：已耗尽（确定性）与这一单就已超（预计值）。"""
    r1 = P.check(P.Policy(token_budget=100), _d(tokens_left=0))
    assert r1 is not None and r1.reason == "budget_exceeded"
    r2 = P.check(P.Policy(token_budget=100), _d(tokens_left=10, tokens_wanted=50))
    assert r2 is not None and r2.reason == "budget_exceeded"
    # 预计值放得下 ⇒ 放行（预算不是"一有消耗就拒绝"）
    assert P.check(P.Policy(token_budget=100), _d(tokens_left=10, tokens_wanted=5)) is None
    # 不限预算 ⇒ 永远不因此被拒
    assert P.check(P.Policy(), _d(tokens_left=None, tokens_wanted=10**9)) is None


def test_usd_budget():
    r = P.check(P.Policy(usd_budget=1.0), _d(usd_left=0.0))
    assert r is not None and r.reason == "budget_exceeded"
    assert r.limit == "usd_budget"


def test_deadline_exceeded_is_last_check():
    """墙钟是最后判的一条：前面每一条都是"策略"，它是"环境"。"""
    r = P.check(P.Policy(), _d(deadline_hit=True))
    assert r is not None and r.reason == "deadline_exceeded"
    # 越权 + 到点 ⇒ 报越权（更具体、更可处置）
    r2 = P.check(P.Policy(), _d(frm="C", to="B", action="run_once", deadline_hit=True))
    assert r2 is not None and r2.reason == "forbidden_edge"


def test_refusal_reason_must_be_in_controlled_vocabulary():
    """负控：自由文本的拒绝理由必须被拒。

    自由文本的理由无法被统计，也无法被 `verify` 检查 ——
    而"我拒绝过"恰恰是事后最需要能回答的问题。
    """
    with pytest.raises(ValueError, match="受控词表"):
        P.Refusal("因为我今天不想跑")
    assert P.Refusal("forbidden_edge").to_dict()["reason"] in S.REFUSAL_REASONS


def test_check_edge_does_not_raise_on_any_reason():
    """负控：策略判定永远不抛（除了构造非法 Refusal 这种编程错误）。

    把它变成异常会逼调用方用 try/except 包住它，而 try/except 会连真正的
    编程错误一起吞掉。
    """
    for kw in (
        dict(to="Z"), dict(action="?"), dict(frm="C", to="B", action="run_once"),
        dict(depth=99), dict(fanout=99), dict(running=99), dict(total=999),
        dict(deadline_hit=True), dict(tokens_left=0),
    ):
        out = P.check_edge(P.Policy(), kw.pop("frm", "M"), kw.pop("to", "C"),
                           action=kw.pop("action", "hottest"), **kw)
        assert out is None or isinstance(out, P.Refusal)


# ---------------------------------------------------------------- 写集冲突


def test_estimate_write_conflict_shares_a_table():
    """写集相交 = 不该并发。判据是表级（本轮的粒度，见设计 §8 待决问题 3）。"""
    assert P.estimate_write_conflict("A", "B") is True, "都写 literature"
    assert P.estimate_write_conflict("D", "F") is True, "都写 search_requests"
    assert P.estimate_write_conflict("B", "F") is True, "都写 reprocess_requests"
    assert P.estimate_write_conflict("E", "E") is True, "两个 E 都写 experiments"


def test_estimate_write_conflict_disjoint_is_false():
    """负控（反方向）：写集不相交 ⇒ 允许并发，不许一律判 True。

    如果判据退化成"永远 True"，整个调度会串行 —— 那不会报错，
    只会表现为"框架很慢"。所以必须有一条断言钉住"确实存在可并发的一对"。

    注意 `C` 与 `A` 现在相交（都写 `search_requests`，I3 的受控例外）——
    这条断言里刻意用不与 C 相交的角色来证明"确实存在可并发的一对"，
    否则这些 `is False` 会退化成"因为全都相交所以全都 False"。
    """
    assert P.estimate_write_conflict("C", "E") is False
    assert P.estimate_write_conflict("A", "E") is False
    assert P.estimate_write_conflict("C", "H") is False
    assert P.estimate_write_conflict("G", "E") is False
    # 正方向：C 与 A/D 因为 search_requests 而相交（受控例外的可观测后果）
    assert P.estimate_write_conflict("C", "A") is True
    assert P.estimate_write_conflict("C", "D") is True


def test_estimate_write_conflict_accepts_action_spec():
    """判据要能吃 `ActionSpec`（调用方手上常常只有它，没有角色名）。"""
    e = C.find_action("E", "run_experiment")
    c = C.find_action("C", "hottest")
    assert e is not None and c is not None
    assert P.estimate_write_conflict(e, c) is False
    assert P.estimate_write_conflict(e, C.find_action("E", "evidence_for")) is True


def test_waves_of_keeps_input_order_and_mutual_exclusion():
    """分波：波内写集互不相交，波内下标升序，且划分是确定性的。

    这里刻意不断言"摊平后的顺序 == 输入顺序"：贪婪装箱会把后面的
    调用塞进前面未满的波（输入 `(E,C,H,E,A)` ⇒ `[[0,1,2],[3,4]]`，
    摊平是 `0,1,2,3,4` 只是碰巧；换一组输入就会变，例如把 A 换成第二个 C
    会得到 `[[0,1,2,4],[3]]`）。跨波的顺序不重要 —— 结果合并顺序是由
    `scheduler.run_waves` 按下标写回 `out[i]` 保证的（见 I-10），
    不是靠分波顺序。把它当成"顺序保证"是两件事被混为一谈的典型形态。

    这一组的分波是 `[[0,1,2],[3,4]]`：第 4 个（E）与波 0 里的 E 相交 ⇒ 新开一波；
    A（4）写 `search_requests`，而C 现在也写 `search_requests`（I3 受控例外，
    见 `WRITE_SETS["C"]`），所以 A 与 C 相交 ⇒ 也只能进第 1 波。
    """
    calls = [P.Decision(role=r) for r in ("E", "C", "H", "E", "A")]
    waves = P.waves_of(calls, limit=4)
    assert waves == [[0, 1, 2], [3, 4]], f"实际 {waves}"
    for w in waves:
        assert w == sorted(w), "同一波内的下标必须升序（否则波内执行顺序不稳定）"
        for i in w:
            for j in w:
                if i < j:
                    assert not P.estimate_write_conflict(calls[i].role, calls[j].role)
    assert sorted(i for w in waves for i in w) == list(range(len(calls))), "每个调用恰好出现一次"


def test_waves_of_respects_limit():
    """单波容量就是 `max_concurrency` —— 划分本身保证"波内并发 ≤ 上限"。"""
    calls = [P.Decision(role=r) for r in ("C", "E", "H", "C", "E")]
    for w in P.waves_of(calls, limit=2):
        assert len(w) <= 2


def test_budget_state_keeps_none_semantics():
    """`None`（不限）与 `0`（已耗尽）不许折叠。"""
    p = P.Policy(token_budget=None)
    st = P.budget_state(p, spent_tokens=10, spent_usd=1.0)
    assert st["tokens_left"] is None and st["usd_left"] is None
    p2 = P.Policy(token_budget=5)
    st2 = P.budget_state(p2, spent_tokens=10, spent_usd=0.0)
    assert st2["tokens_left"] == 0, "花超了也不能是负数（负数会被读成'还能再花'）"


def test_iter_edges_is_flat_and_complete():
    """边表能被摊平，且C 不发起任何召唤（它是只读角色）。"""
    edges = set(P.iter_edges())
    assert ("M", "A") in edges and ("H", "G") in edges
    assert not any(a == "C" for a, _ in edges), "C 不发起任何召唤（§3.1：C 的边刻意是空的）"
