"""反向那一格：工具面声明了、动作面没声明（残项 ㉓；所有者 2026-10-07 授权 5b"补反向 + 新计数并入读数"）。

为什么这一格值得一条判据：正反两处既有判据都管不到它 ——
`param_type_divergences_for` 由动作面驱动（动作没声明的 property 它根本看不见），
`param_seam_violations` 管的是"动作声明了、实现不收" ⇒ "工具面加了参数、忘了加动作面"
这条裂缝全树没有读数会报。活样本就是 ⑱ 的 `providers`（工具面有、`specs/a.py` 没有）。
它为什么有代价：编排层按动作参数表派活 ⇒ 工具面新加的入口在派活侧看不见。

实测（2026-10-07）：21 个动作唯一匹配到工具，其中 7 个存在这个方向的缺口（共 22 个
property），逐条登记在 `capabilities._KNOWN_TOOL_ONLY_PARAMS` 里（登记 = 让它可见，
不是认可；改哪一层由人定）。牙在这条测试里，不在导入期 —— 所有者授权的是
"补反向 + 新计数并入读数"，把导入期改成硬失败会超出那次授权。
"""

from __future__ import annotations

from agentflow import capabilities as C


def test_no_unregistered_tool_only_params() -> None:
    """正控：反向缺口必须逐条登记过（新的一对、或已登记那对又多缺一个，都红）。"""
    bad = C.unregistered_missing_in_actions()
    assert not bad, (
        "有没登记的工具面独有参数（编排层看不见这些入口）：\n  " + "\n  ".join(bad)
        + "\n处置二选一：把这几个 property 补进动作面声明（`specs/*.py`，禁改区、要人审），"
        "或登记进 `capabilities._KNOWN_TOOL_ONLY_PARAMS` 并写清为什么不改。"
    )


def test_the_registration_has_no_stale_entries() -> None:
    """登记不许过期：某个 property 不再缺了 ⇒ 必须删掉那几条登记。

    与 `stale_param_seams` 同一条道理：只增不减的登记表会烂成噪音，
    而噪音里的真缺口就没人看了。
    """
    stale = C.stale_missing_in_action_entries()
    assert not stale, "登记过期：\n  " + "\n  ".join(stale)


def test_the_reverse_scan_is_not_vacuous() -> None:
    """反真空：真的比过动作、登记表非空、每条都写了理由且不是空集合。

    空集永远是子集 —— "没有反向缺口"这句话必须配上"比过多少对"才作数（P16）。
    """
    coverage = C.param_missing_in_action_coverage()
    assert coverage["pairs"] > 0, f"一个动作都没比过 ⇒ 上面两条正控是真空的：{coverage}"
    assert coverage["gaps"] > 0, (
        f"反向缺口读到 0 处 ⇒ 要么真被补齐了（那就把登记表也清空并改这条断言），"
        f"要么判据失效了：{coverage}"
    )
    assert C._KNOWN_TOOL_ONLY_PARAMS, "登记表是空的 ⇒ 正控失去对象"
    for key, (props, why) in C._KNOWN_TOOL_ONLY_PARAMS.items():
        assert props, f"{key} 登记了空集合 —— 空登记等于没登记"
        assert why.strip(), f"{key} 没写理由 ⇒ 复核者无从判断这个缺口该不该留"


def test_the_reverse_checker_catches_an_extra_gap_on_a_registered_pair(monkeypatch) -> None:
    """负控①：已登记那对又多缺一个 property ⇒ 必须红（否则登记表就成了万能豁免）。"""
    spec = next(s for s in C.CAPABILITIES["C"] if s.action == "neighbors")
    cap_props = set((spec.params or {}).get("properties") or {})
    assert cap_props, "`C.neighbors` 一个 property 都没声明 ⇒ 这条负控失去对象"
    # 工具面 = 动作面已声明的 + 登记里那个（仍然缺）+ 一个新的（多缺）
    tools = {"graph.neighbors": {**{p: (None, None) for p in cap_props},
                                "max_neighbors": ("integer", None),
                                "brand_new": ("string", None)}}
    monkeypatch.setattr(C, "_candidates", lambda s, t: ["graph.neighbors"])
    bad = C.unregistered_missing_in_actions({"C": (spec,)}, tools)
    assert bad and "brand_new" in bad[0], bad
    # 同一个输入下"过期检测"不许把这一对报成过期：登记的属性仍然在缺。
    # （注意作用域：这里喂的是只含 C 的替身表 ⇒ 别的登记条目当然会被报成过期，
    #  所以断言只针对 C.neighbors 这一条，不是"整张表为空"。）
    stale = C.stale_missing_in_action_entries({"C": (spec,)}, tools)
    assert not any("C.neighbors" in s for s in stale), stale


def test_the_reverse_checker_catches_an_unregistered_pair(monkeypatch) -> None:
    """负控②：一对没登记过的动作出现缺口 ⇒ 必须红。"""
    spec = next(s for s in C.CAPABILITIES["A"] if s.action == "search_literature")
    cap_props = set((spec.params or {}).get("properties") or {})
    tools = {"search.literature": {**{p: (None, None) for p in cap_props}, "brand_new": ("string", None)}}
    monkeypatch.setattr(C, "_candidates", lambda s, t: ["search.literature"])
    bad = C.unregistered_missing_in_actions({"A": (spec,)}, tools)
    assert bad and "A.search_literature" in bad[0], bad


def test_the_reverse_checker_catches_a_stale_entry(monkeypatch) -> None:
    """负控③：登记过的那一对不再缺 ⇒ 必须报"登记过期"（否则表只增不减）。"""
    spec = next(s for s in C.CAPABILITIES["C"] if s.action == "neighbors")
    cap_props = set((spec.params or {}).get("properties") or {})
    tools = {"graph.neighbors": {p: (None, None) for p in cap_props}}   # 工具面只剩动作面已声明的
    monkeypatch.setattr(C, "_candidates", lambda s, t: ["graph.neighbors"])
    stale = C.stale_missing_in_action_entries({"C": (spec,)}, tools)
    assert any("C.neighbors" in s for s in stale), stale
    assert C.unregistered_missing_in_actions({"C": (spec,)}, tools) == []
