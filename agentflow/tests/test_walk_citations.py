# -*- coding: utf-8 -*-
"""`search.walk_citations` 与它底下的 `OpenAlexProvider.walk_citations` 的判据。

业主 2026-10-15 裁定：引文图用新动作的方式落。这一份守的是那件动作的工具面。

三层各守一段：
  ① 工具面：它在 A 的面上、不在别人的面上；
  ② provider：两个方向各发什么请求（离线，把 `http_get_json` 换掉）；
  ③ 工具：失败必须 `ok=False` 且说得清是哪一种失败（不是返回空列表）。

全部离线（不联网），复跑：`python -m pytest -q tests/test_walk_citations.py`
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from agentflow import providers as P
from agentflow.store import Store
from agentflow.tools import build_registry


def _seed_literature(root: pathlib.Path, **overrides) -> None:
    """往一份临时工作区的 `literature` 表里放一行（引文走查从盘上这一篇出发）。"""
    row = {
        "lit_id": "000001",
        "title": "A theory and methodology to quantify knowledge",
        "doi": "10.1098/rsos.181055",
        "year": 2019,
        "type_code": "J",
        "type": "J",
        "path": "",
        "authors": ["X"],
        "venue": "R Soc Open Sci",
        "summary": "",
        "dedup_key": "doi:10.1098/rsos.181055",
        "status": "registered",
        "source_keys": ["doi:10.1098/rsos.181055"],
    }
    row.update(overrides)
    row = {k: v for k, v in row.items() if v is not _DROP}
    store = Store(root)
    with store.tx("literature", actor="test", note="seed") as tx:
        tx.upsert("literature", row, note="seed")


class _DROP:  # noqa: N801 - 哨兵：让 overrides 能删掉一个字段
    """哨兵类型：`_seed_literature(..., doi=_DROP)` 表示"这一行没有 doi"。"""


# ============================================================ ① 工具面


def test_the_tool_is_on_as_surface_and_only_as() -> None:
    """它在 A 的工具面上 —— 而且只在 A 的面上（`roles=("A",)` 不是装饰）。"""
    tmp = pathlib.Path(tempfile.mkdtemp())
    reg = build_registry(store=Store(tmp), workspace_root=tmp).registry

    def surface(role: str) -> set[str]:
        # `for_role` 给的是这一角色看得到的 spec 列表（`scoped_to(role).names()`
        # 不按角色过滤 —— 实测两者不是一回事，别混用）
        return {s.name for s in reg.for_role(role)}

    assert "search.walk_citations" in surface("A")
    for other in ("B", "C", "D", "E", "F", "G", "H", "V"):
        assert "search.walk_citations" not in surface(other), other


# ============================================================ ② provider 侧


def _stub_http(monkeypatch, *, source: dict, batch: dict, seen: list) -> None:
    """把 provider 的 HTTP 换掉：按请求形态分流，不按 URL 猜。

    分流判据是"这一问带没带 `openalex_id:` / `cites:` 过滤"：
    带过滤的是批量那一问（回 `batch`），不带的是取源记录那一问（回 `source`）。
    早先按 `"/works/W" in url` 分流是错的 —— 走 DOI 时 URL 是 `/works/doi:…`，
    会被误分到批量那一支，于是"源记录没有 referenced_works" ⇒ 回溯空。
    """
    def fake(url, params=None, **kwargs):  # noqa: ANN001, ANN003
        seen.append((url, dict(params or {})))
        flt = str((params or {}).get("filter") or "")
        if flt.startswith("openalex_id:") or flt.startswith("cites:"):
            return batch
        return source
    monkeypatch.setattr(P, "http_get_json", fake)


def test_backward_still_reads_the_source_record_when_given_only_an_openalex_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """反真空：只给 `openalex_id` 时也必须去读源记录。

    为什么这一条必须钉住：`referenced_works` 只在源记录上，批量解析那一问拿不到它。
    改前若"给了 id 就跳过取源记录"，回溯会静默返回空 —— 而"这一篇谁都没引"
    与"我没去读它的参考文献"在产物上长得一模一样（那是假阴性，本项目最贵的一类错）。
    """
    seen: list = []
    _stub_http(
        monkeypatch,
        source={"id": "https://openalex.org/W123", "title": "src",
                "referenced_works": ["https://openalex.org/W9"]},
        batch={"results": [{"id": "https://openalex.org/W9", "title": "cited work",
                            "publication_year": 2001, "doi": "https://doi.org/10.1/x",
                            "type": "article"}]},
        seen=seen,
    )
    prov = P.OpenAlexProvider(mailto="x@example.invalid")
    out = prov.walk_citations(openalex_id="W123", direction="backward", limit=5)
    assert [c.title for c in out] == ["cited work"], out
    assert any(url.endswith("/W123") for url, _ in seen), \
        f"没有去读源记录 ⇒ 回溯会静默返回空。实际请求：{[u for u, _ in seen]}"
    # 批量解析那一问必须带 openalex_id 过滤（不是拿内部 id 当 DOI 用）
    assert any("openalex_id:" in str(p.get("filter")) for _, p in seen), seen


def test_forward_uses_the_cites_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """前推走 `cites:<W…>` —— 两个方向是两条不同的查询，不是同一条换个参数。"""
    seen: list = []
    _stub_http(
        monkeypatch,
        source={"id": "https://openalex.org/W123", "title": "src"},
        batch={"results": [{"id": "https://openalex.org/W9", "title": "citer",
                            "publication_year": 2021, "type": "article"}]},
        seen=seen,
    )
    prov = P.OpenAlexProvider(mailto="x@example.invalid")
    out = prov.walk_citations(openalex_id="W123", direction="forward", limit=5)
    assert [c.title for c in out] == ["citer"], out
    assert any(str(p.get("filter", "")).startswith("cites:W123") for _, p in seen), seen


def test_the_two_ident_forms_build_different_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_fetch_one_work` 认两种形态：`W…` 走 `/works/W…`，别的当 DOI 走 `/works/doi:…`。"""
    seen: list = []
    _stub_http(monkeypatch, source={"id": "https://openalex.org/W1", "title": "t"},
               batch={"results": []}, seen=seen)
    prov = P.OpenAlexProvider(mailto="x@example.invalid")
    prov._fetch_one_work("W123")
    prov._fetch_one_work("10.1098/rsos.181055")
    urls = [u for u, _ in seen]
    assert any(u.endswith("/works/W123") for u in urls), urls
    assert any("/works/doi:10.1098" in u for u in urls), urls


# ============================================================ ③ 工具侧


def _call(reg, **kwargs):
    return reg.call("search.walk_citations", role="A", **kwargs)


def test_an_unknown_lit_id_fails_instead_of_returning_an_empty_list() -> None:
    """找不到那一行 ⇒ `ok=False` ＋ `kind=unknown_lit_id`。

    为什么不许返回空列表：空列表在下游是一个有效结论（"这一篇没有引文邻居"），
    而"我没找到你指的那一篇"是另一件事。三态纪律。
    """
    tmp = pathlib.Path(tempfile.mkdtemp())
    _seed_literature(tmp)
    reg = build_registry(store=Store(tmp), workspace_root=tmp).registry
    res = _call(reg, lit_id="999999")
    assert res.ok is False, res
    assert (res.meta or {}).get("kind") == "unknown_lit_id", res.meta
    assert "999999" in str(res.error)


def test_a_row_with_no_source_key_says_so_instead_of_failing_silently() -> None:
    """这一行既没有 doi 也没有 openalex_id ⇒ 说清是这一格缺，不是"没查到引文"。"""
    tmp = pathlib.Path(tempfile.mkdtemp())
    _seed_literature(tmp, doi=None, openalex_id=None)
    # `doi=None` 会被 schema 收成空串；两种形态都不该走到联网那一步
    reg = build_registry(store=Store(tmp), workspace_root=tmp).registry
    res = _call(reg, lit_id="000001")
    assert res.ok is False, res
    assert (res.meta or {}).get("kind") == "no_source_key", res.meta


def test_no_store_says_it_never_looked(monkeypatch: pytest.MonkeyPatch) -> None:
    """没配 store ⇒ 明说"根本没查"，不是"这一篇不在表里"。"""
    reg = build_registry(store=None, workspace_root=tempfile.mkdtemp()).registry
    res = _call(reg, lit_id="000001")
    assert res.ok is False, res
    assert (res.meta or {}).get("kind") == "no_store", res.meta


def test_the_tool_does_not_annotate_dedup_on_purpose(monkeypatch: pytest.MonkeyPatch) -> None:
    """刻意的差别：本工具不替判重（与 `search.literature` 不同）。

    判重在本模块只有 `_h_literature` 那一处内联实现；在这里再写一份就是"同一件事两处实现",
    而"同一篇文献只留一个键"正是划进禁改区的那条纪律。所以候选只带书目字段，
    并留一句"登记前先 dedup_check"。
    """
    tmp = pathlib.Path(tempfile.mkdtemp())
    _seed_literature(tmp)
    _stub_http(
        monkeypatch,
        source={"id": "https://openalex.org/W1", "title": "src",
                "referenced_works": ["https://openalex.org/W9"]},
        batch={"results": [{"id": "https://openalex.org/W9", "title": "cited work",
                            "publication_year": 2001, "type": "article"}]},
        seen=[],
    )
    reg = build_registry(store=Store(tmp), workspace_root=tmp).registry
    res = _call(reg, lit_id="000001", direction="backward", limit=5)
    assert res.ok is True, res
    cands = res.data["candidates"]
    assert cands and cands[0]["title"] == "cited work", cands
    for absent in ("is_new", "dedup_key", "existing", "dedup_hit_key"):
        assert absent not in cands[0], f"{absent} 出现在候选里 ⇒ 判重被复制了第二份"
    assert "dedup_check" in res.data["note"]


# ============================================================ ④ 动作层（`AgentA.walk_citations`）


def _agent(root: pathlib.Path):
    from agentflow.agent_a import AgentA

    return AgentA(Store(root), providers=[])


def test_the_action_exists_and_is_callable() -> None:
    """能力表里的动作必须在 `AgentA` 上有真实的公开方法。

    `capabilities.assert_capabilities()` 在导入期就断言这一条（逐字："能力表里的动作
    必须是真实代码里存在的公开方法，不许编造"）—— 那条断言是权威，这里只是把
    "这一格确实在"再钉一次，免得将来有人把动作表和方法拆开搬走。
    """
    from agentflow import capabilities as C

    assert "walk_citations" in {a.action for a in C.actions_for("A")}
    assert callable(getattr(_agent(pathlib.Path(tempfile.mkdtemp())), "walk_citations"))


def test_the_action_refuses_when_the_call_itself_does_not_hold() -> None:
    """这次调用本身不成立 ⇒ `refuse(...)`（带受控理由码），不是走查结果。

    为什么必须分开：`ok=False` 说的是"走查没做成"（工具层那三档），
    而这里压根没开始走。折平了，"我参数给错了"与"引文图上没邻居/没做成"就分不开 ——
    本仓反复踩的就是这一类。判据：拒绝那一档带 `refusal_reason`，工具失败那一档不带。
    """
    a = _agent(pathlib.Path(tempfile.mkdtemp()))
    cases = (
        ({"lit_id": ""}, "bad_lit_id"),
        ({"lit_id": "000001", "direction": "sideways"}, "bad_direction"),
        ({"lit_id": "000001", "limit": 0}, "bad_limit"),
    )
    for kwargs, code in cases:
        out = a.walk_citations(**kwargs)
        assert out["ok"] is False, out
        assert out["kind"] == code, (kwargs, out)
        assert out.get("refusal_reason"), out


def test_the_action_passes_the_tools_failure_kind_through() -> None:
    """工具报"没做成" ⇒ 原样透传 `kind`，且不带 `refusal_reason`（两档不许混）。"""
    tmp = pathlib.Path(tempfile.mkdtemp())
    _seed_literature(tmp)
    out = _agent(tmp).walk_citations(lit_id="999999")
    assert out["ok"] is False, out
    assert out["kind"] == "unknown_lit_id", out
    assert "refusal_reason" not in out, "工具层的「没做成」被折成了「拒绝」"


def test_the_action_clamps_the_limit_and_does_not_register_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两件事一起钉：① `limit` 超工具面上限要截到 50 并说明；
    ② 动作只读 —— 一次成功的走查不许往台账里落任何一行。

    为什么 ② 重要：登记是判断（判重），而判重在本仓只有一处实现。
    动作层擅自登记 = 在第二处做"这两条是不是同一篇"的判断，而它漂了不会报错。
    """
    tmp = pathlib.Path(tempfile.mkdtemp())
    _seed_literature(tmp)
    _stub_http(
        monkeypatch,
        source={"id": "https://openalex.org/W1", "title": "src"},
        batch={"results": [{"id": "https://openalex.org/W9", "title": "citer",
                            "publication_year": 2021, "type": "article"}]},
        seen=[],
    )
    before = len(Store(tmp).rows("literature"))
    out = _agent(tmp).walk_citations(lit_id="000001", direction="forward", limit=9999)
    assert out["ok"] is True, out
    assert out["truncated_to_tool_max"] is True, out
    assert "截到 50" in out["note"], out["note"]
    assert len(Store(tmp).rows("literature")) == before, "动作往台账里落了行 ⇒ 它不再是只读的"
