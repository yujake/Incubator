"""工具摘要里的读数必须等于真身（R6 `draft/63 §3-2` 的判据化）。

靶心是实测出来的一个真缺陷：模型看到的 `table.schema` 摘要写着"返回 6 张表"，
而 `schema.TABLES` / `ALL_TABLES` 的真身是 17。这类假读数有一个共同特征 ——
不会让任何判据变红（改前全仓扫描：没有任何判据提到过那句字面量），
于是它可以一直是假的，而报告照样亮绿。

这一族判据把"摘要里的数字"钉到现算上：凡在摘要里写"N 张表"，N 必须等于
`len(ALL_TABLES)`。反真空那一条同样要紧 —— 若哪天摘要里一处张数都不写了，
判据不是"通过"，而是失去对象，必须有人显式决定。
"""

from __future__ import annotations

import pathlib
import re
import tempfile

from agentflow.store import Store
from agentflow.tools import ROLES, build_registry
from agentflow.tools.table_tools import ALL_TABLES

REPO = pathlib.Path(__file__).resolve().parents[1]

#: 摘要里"N 张表"的写法。本仓实测只有 `table.schema` 用它（"四张表"那族说的是
#: 论文包里的四张表，是另一个对象，刻意不匹配）。
_TABLE_COUNT_RE = re.compile(r"(\d+)\s*张表")


def _summaries_by_name() -> dict[str, str]:
    """全角色工具面上的 name → summary（就是模型在提示词里看到的那一份）。"""
    ws = pathlib.Path(tempfile.mkdtemp(prefix="tool-summary-")) / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    reg = build_registry(store=st, workspace_root=ws, roles=tuple(ROLES), strict=True).registry
    out: dict[str, str] = {}
    for role in ROLES:
        for spec in reg.for_role(role):
            out.setdefault(str(spec.name), str(spec.summary))
    return out


def stale_table_count_claims(summaries: dict[str, str], live: int) -> list[str]:
    """返回"说了张数、但说的不是真身"的条目。纯函数：正控与负控都调它。

    为什么把判断抽成纯函数：负控若自己另写一套判断，它证明的只是"另写的那套会红"。
    """
    bad: list[str] = []
    for name, text in summaries.items():
        for n in _TABLE_COUNT_RE.findall(text):
            if int(n) != live:
                bad.append(f"{name}：摘要说 {n} 张表，真身 {live}")
    return bad


def test_no_tool_summary_states_a_stale_table_count() -> None:
    """正控：模型看到的工具摘要里，"N 张表"必须就是现算的那个数。"""
    summaries = _summaries_by_name()
    claims = {n: _TABLE_COUNT_RE.findall(t) for n, t in summaries.items()}
    claims = {n: v for n, v in claims.items() if v}
    # 反真空：这一族必须真的有人在说张数。全没了不等于"没问题"，是判据没了对象。
    assert claims, (
        "工具摘要里一处「N 张表」都没有了 ⇒ 这条判据失去对象。要么把 `table.schema` "
        "的摘要改回现算，要么确认这是有意删除并同步改掉本判据（不许静默失去对象）。"
    )
    bad = stale_table_count_claims(summaries, len(ALL_TABLES))
    assert not bad, (
        "工具摘要里的表数是假的（模型会按错的表数办事）：\n  "
        + "\n  ".join(bad)
        + f"\n真身：len(ALL_TABLES) = {len(ALL_TABLES)}"
    )


def test_the_table_count_checker_actually_catches_a_stale_number() -> None:
    """负控（改前红）：喂一个写死 6 的摘要，检查器必须报出来；换真数字也必须报。"""
    fake = {"table.schema": "返回 6 张表的字段名/类型/是否必填/默认值。"}
    assert stale_table_count_claims(fake, len(ALL_TABLES)), (
        "写死 6 的摘要没有被报出来 ⇒ 上面那条正控是真空的"
    )
    # 反负控：数字是相对的 —— 表真涨到 18 时，写 17 的摘要同样必须红
    assert stale_table_count_claims({"x": "返回 17 张表"}, 18), (
        "换了真身数字之后检查器不认账 ⇒ 它钉的是字面量而不是「等于真身」这件事"
    )
    ok = {"table.schema": f"返回 {len(ALL_TABLES)} 张表的字段名。"}
    assert not stale_table_count_claims(ok, len(ALL_TABLES)), "现算写法被误报"
