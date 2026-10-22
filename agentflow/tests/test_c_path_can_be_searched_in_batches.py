# -*- coding: utf-8 -*-
"""C 的长链可以一批一批往回搜：前沿读数 + 技能里的那个动作循环（业主 2026-10-22）。

业主原话（这一批的需求真身）：

> 「这里 max 的意思是一批分析能搜到多深，不妨碍如果有个证明有几十个大步骤，
>  可以一批一批往回搜，再拼起来。」

拆开是四件事，本文件的判据就钉这四件（判的是"读数够不够 C 做这件事"与
"技能有没有教这件事"，不是"框架自动替 C 拼链"）：

1. `max_depth` 是一批的深度上限（默认 6，没动它）：一批到不了根时，
   `frontier` 必须非空、点名停在哪几个节点、`why="depth_limit"`，
   并给出"下一批从哪开始"（`next_hint`）；
2. 以前沿节点为起点再搜一批能到根 —— 由这条判据自己驱动两次调用，
   框架里没有"接着搜"的循环（那会把搜多深的决定权从模型手里拿走）；
3. `join_segments` 能把"拼的是哪几段、接缝在哪"摆出来（`segments` / `seams`），
   合并后的 `hops` / `steps` 与整条链一次搜到底的读数相同（按拼后的边重算，
   不是两批数字相加）；接缝节点必须同时出现在前一批的 `frontier` 与后一批的路径上；
4. 技能文本里那一节必须含那个动作循环的六条实质（允许措辞不同），
   并且"看 `frontier`、以前沿为下一批起点"那一句删掉之后必须红。

另加两条：三态（一批就到根 ⇒ `frontier == []` 且 `checked=True`，不等于"没查成"）、
反真空（把 `frontier` 恒置空 ⇒ 判据 1 必红）。

零模型、零网络：夹具全在 `tmp_path` 下自建，`proof_chain` 与 `join_segments`
都是确定性代码。

命名上的约定（读数里那几格的口径，复核时照这几条）：`frontier` 的 `node` 是这一批
没走进去的那个节点（下一批的起点），`from` 是走通的最后一站，`depth_reached` 是
从本批起点到 `from` 的跳数（= 本批的深度上限）；`seams[].at_node` 就是接缝那个节点。
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from agentflow import agent_skills as AS           # noqa: E402
from agentflow import schema as S                  # noqa: E402
from agentflow.agent_c import AgentC               # noqa: E402
from agentflow.agent_c import path_shape as PS     # noqa: E402
from agentflow.agent_c import proof_chain as PC    # noqa: E402
from agentflow.store import Store                  # noqa: E402

#: 夹具时间戳写死（不依赖当前时间）。
TS = "2026-10-22T00:00:00+08:00"

#: 这一批的深度上限（业主口径：默认 6，判据照这一档跑）。
BATCH_DEPTH = 6

#: 12 步链在 `max_depth=6` 下应该停在哪：起点 0001 走通到 0007，没走进去的是 0008。
EXPECTED_FRONTIER = "stmt:0008"
EXPECTED_LAST_WALKED = "stmt:0007"
ROOT = "lit:0009"
#: 第一批的 target 给裸号：这样"改前红"是因为前沿没交出来，而不是因为别的。
#: 第二批判据照 `frontier` 里那个带前缀的 `node` 调（那是模型照读数会写的那一种写法）。
TARGET = "0001"
TARGET_NODE = "stmt:0001"


# --------------------------------------------------------------------- 夹具


def _store(root: pathlib.Path) -> Store:
    st = Store(root / "ws")
    st.init()
    return st


def _stmt(st: Store, sid: str) -> None:
    row = S.Statement(stmt_id=sid, origin="own_result", kind="theorem",
                      label=f"命题 {sid}", statement_text="短版",
                      statement_full="若假设 A 成立，则结论 B 成立",
                      proof_text="", source_lit_id=None,
                      quote_verified=None, quote_reason="夹具（还没核）",
                      evidence_kind="cross_check", aliases=[], status="active",
                      created_at=TS)
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict(), note="stmt")


def _lit(st: Store, lid: str) -> None:
    row = S.Literature(lit_id=lid, title=f"文献 {lid}", type="J", summary="s",
                       path=None, added_at=TS)
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", row.to_dict(), note="lit")


def _dep(st: Store, did: str, used_by: str, *, stmt_id: str = "", lit_id: str = "",
         group: int = 1) -> None:
    row = S.Dependency(dep_id=did, used_by=used_by, kind="theorem", label="前提",
                       status="closed", status_reason="",
                       source_stmt_id=stmt_id or None, source_experiment_id=None,
                       source_lit_id=lit_id or None, path_group=group, created_at=TS)
    row.validate()
    with st.tx("dependencies", actor="test") as tx:
        tx.upsert("dependencies", row.to_dict(), note="dep")


def _twelve_steps(root: pathlib.Path) -> Store:
    """12 步的链：0001 → 0002 → … → 0012 → 文献 0009（一次搜到底 = 12 跳 / 12 步）。

    为什么钉 12：它正好是两个 `max_depth=6` 的批次接得上（6 段 + 1 处接缝 + 5 段），
    而"两批数字相加"会得到 7 + 5 = 12 或 6 + 5 = 11 —— 前者巧合成 12、后者差一跳。
    所以合并后的读数是按拼后的边重算出来的，不是相加来的（判据 3 会把这一条钉住）。
    """
    st = _store(root)
    _lit(st, "0009")
    for i in range(1, 13):
        _stmt(st, f"{i:04d}")
    for i in range(1, 12):
        _dep(st, f"9{i:05d}", f"stmt:{i:04d}", stmt_id=f"{i + 1:04d}")
    _dep(st, "900012", "stmt:0012", lit_id="0009")
    return st


def _short_chain(root: pathlib.Path) -> Store:
    """3 步的链：0010 → 0011 → 0012 → 文献 0009（一批就走到根）。"""
    st = _store(root)
    _lit(st, "0009")
    for i in range(10, 13):
        _stmt(st, f"{i:04d}")
    _dep(st, "900010", "stmt:0010", stmt_id="0011")
    _dep(st, "900011", "stmt:0011", stmt_id="0012")
    _dep(st, "900012", "stmt:0012", lit_id="0009")
    return st


# ------------------------------------------- 判据 1：这一批停在哪儿（纯函数）


def _rows_by_id(payload: dict) -> dict[str, dict]:
    return {str(r.get("path_id") or ""): r for r in (payload.get("path_shapes") or [])}


def frontier_problems(payload: dict) -> list[str]:
    """判据 1 的判据体（空列表 = 过）。

    三态的第一面：`frontier_checked` 为假是"没算成"，那时不许把空列表读成
    "没有前沿"。所以先判三态位，再看条目本身。
    """
    out: list[str] = []
    if payload.get("frontier_checked") is not True:
        out.append("`frontier_checked` 不是真 ⇒ 前沿这一趟没算成"
                   "（没算不等于没有前沿；也不等于这一批就到根了）")
        return out
    if payload.get("closed"):
        out.append("这一批的 `closed` 是真 ⇒ 夹具前提就错了（12 步链在 6 跳内到不了根）")
    frontier = list(payload.get("frontier") or [])
    if not frontier:
        out.append("一批 `max_depth=6` 搜不到根，`frontier` 却是空列表 ⇒ "
                   "把『还没搜完』读成了『没有前沿』")
        return out
    rows = _rows_by_id(payload)
    for i, item in enumerate(frontier):
        where = f"frontier[{i}]={item!r}"
        if item.get("why") != PS.FRONTIER_DEPTH_LIMIT:
            out.append(f"{where}：`why` 不是 {PS.FRONTIER_DEPTH_LIMIT!r} ⇒ "
                       "停下原因那一格没说清（别的停法不叫前沿）")
        if int(item.get("depth_reached") or 0) != BATCH_DEPTH:
            out.append(f"{where}：`depth_reached` 应当是 {BATCH_DEPTH}"
                       f"（这一批走通的深度上限）：{item.get('depth_reached')!r}")
        if not str(item.get("node") or "").startswith("stmt:"):
            out.append(f"{where}：`node` 不是节点号 ⇒ 下一批没法照它当起点")
        if not str(item.get("from") or ""):
            out.append(f"{where}：`from` 是空的 ⇒ 接缝的上一站没交代，拼起来接不上")
        if not str(item.get("via_dep_id") or ""):
            out.append(f"{where}：`via_dep_id` 是空的 ⇒ 接缝那条边没法回台账核")
        hint = str(item.get("next_hint") or "")
        if str(item.get("node") or "") not in hint:
            out.append(f"{where}：`next_hint` 没点名下一批的起点 ⇒ 模型得自己猜")
        row = rows.get(f"p{item.get('proof_no')}g{item.get('path_group')}")
        if row is None:
            out.append(f"{where}：读数里没有它说的那条候选路径"
                       f"（p{item.get('proof_no')}g{item.get('path_group')}）")
            continue
        walked = [str(n) for n in (row.get("walked_nodes") or [])]
        if not walked:
            out.append(f"{where}：那一行没有交出『走通的那一段』⇒ 拼的时候没有起点")
        elif walked[-1] != str(item.get("from") or ""):
            out.append(f"{where}：前沿的上一站是 {item.get('from')!r}，"
                       f"而那一行走通的最后一个是 {walked[-1]!r} ⇒ 两处对不上")
        if row.get("frontier") is None:
            out.append(f"{where}：那一行自己没有 `frontier` 格（省略了这一格）")
    nodes = [str(f.get("node") or "") for f in frontier]
    if EXPECTED_FRONTIER not in nodes:
        out.append(f"前沿里没有点名 {EXPECTED_FRONTIER}（实得 {nodes}）⇒ "
                   "停在哪几个节点没说清")
    return out


# ----------------------------------- 判据 3：段落与接缝（纯函数，另判 2 的前提）


def joined_problems(batch1: dict, batch2: dict, joined: dict, full: dict) -> list[str]:
    """判据 3 的判据体（空列表 = 过）。同时钉住判据 2 的结果（第二批到根）。"""
    out: list[str] = []
    rows2 = list(batch2.get("path_shapes") or [])
    if not batch2.get("closed"):
        out.append("第二批（以前沿节点为起点）没到根 ⇒ 判据 2 不成立"
                   f"（closed={batch2.get('closed')!r}）")
    if not rows2 or not rows2[0].get("reached"):
        out.append(f"第二批的那一行没报 reached=True：{rows2[:1]!r}")
    if joined.get("checked") is not True:
        out.append(f"两批读数拼不起来：{joined.get('note')!r}")
        return out
    if joined.get("complete") is not True:
        out.append(f"拼起来了但没到根：{joined.get('note')!r}")
    rows = list(joined.get("rows") or [])
    if len(rows) != 1:
        out.append(f"合并后的形状应当恰好一行，实得 {len(rows)} 行")
        return out
    row = rows[0]
    full_rows = list(full.get("path_shapes") or [])
    if not full_rows:
        out.append("整条链一次搜到底的读数不见了 ⇒ 没有可比的基准")
        return out
    base = full_rows[0]
    for key in ("hops", "steps"):
        if int(row.get(key) or 0) != int(base.get(key) or 0):
            out.append(f"合并后的 `{key}` 是 {row.get(key)!r}，而整条链一次搜到底是 "
                       f"{base.get(key)!r} ⇒ 没按拼后的边重算")
    segments = list(joined.get("segments") or [])
    if [int(s.get("batch") or 0) for s in segments] != [1, 2]:
        out.append(f"`segments` 没按批次给出两段：{segments!r}")
    if len(segments) == 2:
        first, second = segments
        if first.get("start") != TARGET_NODE:
            out.append(f"第 1 段的起点应当是 {TARGET_NODE}：{first.get('start')!r}")
        if first.get("end") != EXPECTED_LAST_WALKED:
            out.append(f"第 1 段的终点应当是 {EXPECTED_LAST_WALKED}：{first.get('end')!r}")
        if second.get("start") != EXPECTED_FRONTIER:
            out.append(f"第 2 段的起点应当是前沿节点 {EXPECTED_FRONTIER}："
                       f"{second.get('start')!r}")
        if second.get("end") != ROOT:
            out.append(f"第 2 段的终点应当是根 {ROOT}：{second.get('end')!r}")
        got_hops = [int(s.get("hops") or 0) for s in segments]
        if got_hops != [6, 5]:
            out.append(f"两段的跳数应当是 [6, 5]（接缝那一跳不算在任何一段里）：{got_hops}")
        # 反真空：合并后的跳数不许等于各段跳数直接相加（那样接缝那一跳就丢了）。
        if int(row.get("hops") or 0) == sum(got_hops):
            out.append(f"合并后的 hops={row.get('hops')!r} 正好等于各段跳数之和 "
                       f"{sum(got_hops)} ⇒ 接缝那一跳没算进去（不是按拼后的边重算）")
    seams = list(joined.get("seams") or [])
    if len(seams) != 1:
        out.append(f"两批之间应当恰好一处接缝，实得 {len(seams)} 处：{seams!r}")
        return out
    seam = seams[0]
    at = str(seam.get("at_node") or "")
    if at != EXPECTED_FRONTIER:
        out.append(f"接缝节点应当是 {EXPECTED_FRONTIER}：{at!r}")
    if (int(seam.get("from_batch") or 0), int(seam.get("to_batch") or 0)) != (1, 2):
        out.append(f"接缝没说清是从第几批到第几批：{seam!r}")
    fronts1 = [str(f.get("node") or "") for f in (batch1.get("frontier") or [])]
    if at not in fronts1:
        out.append(f"接缝节点 {at!r} 不在前一批的 `frontier` 里（{fronts1}）⇒ 这不是一处接缝")
    if at not in [str(n) for n in (row.get("spine_nodes") or [])]:
        out.append(f"接缝节点 {at!r} 不在拼起来的那条路径上 ⇒ 接缝摆错了地方")
    path2 = [str(n) for n in ((rows2[0].get("walked_nodes") or []) if rows2 else [])]
    if at not in path2:
        out.append(f"接缝节点 {at!r} 不在第二批的路径上（{path2}）⇒ 接缝摆错了地方")
    if not str(seam.get("via_dep_id") or ""):
        out.append("接缝没给 `via_dep_id` ⇒ 那一条边回不了台账核")
    return out


def seam_refused_problems(batch1: dict, joined: dict, bad_start: str) -> list[str]:
    """拼接失败那一面（判据 3 的负控）：接缝对不上时不许交出"看起来完整"的链。"""
    out: list[str] = []
    if joined.get("checked") is not False:
        out.append("第二批的起点不在前沿里，`checked` 却是真 ⇒ 接缝没被核就拼了")
    if list(joined.get("rows") or []):
        out.append("拼不起来却给出了合并后的链 ⇒ 不许静默交一条"
                   "『看起来完整』的链")
    note = str(joined.get("note") or "")
    if "接缝对不上" not in note:
        out.append(f"`note` 没点名『接缝对不上』：{note!r}")
    if bad_start not in note:
        out.append(f"`note` 没点名断在哪儿（起点 {bad_start}）：{note!r}")
    fronts = [str(f.get("node") or "") for f in (batch1.get("frontier") or [])]
    if fronts and not any(node in note for node in fronts):
        out.append(f"`note` 没点名真正的前沿节点（{fronts}）⇒ 读的人不知道"
                   "该从哪儿接")
    return out


# ---------------------------------------------- 判据 4：技能里的那个动作循环

#: C 那一节的名字（`agent_skills.CATALOG["C"]` 里的 slug）。
NATURAL_SLUG = "自然路径-循序渐进优先且绕弯不选"

#: 动作循环的六条实质：键 = 人的叫法，值 = 同一段里必须同时出现的几串
#: （按"段"比：整条链的实质被拆到别的段里，读者就串不起来）。
LOOP_NEEDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("① 先搜一批，到根就直接判自然性", ("先搜一批", "closed")),
    ("① 点出那个调用形式与一批的深度", ("C.proof_chain(", "max_depth=6")),
    ("② 没到根看 frontier：哪几个节点把深度用光", ("frontier", "depth_limit")),
    ("② 那些节点是下一批的起点", ("frontier", "target")),
    ("③ 先想清楚要补全还是确认走不通", ("补全", "走不通")),
    ("④ 拼的时候交代拼的是哪几段", ("哪几段",)),
    ("④ 接缝在哪", ("接缝",)),
    ("④ 每段各几跳", ("几跳",)),
    ("④ 有没有一段是无依赖直达", ("无依赖",)),
    ("④ 核对材料（不是自动拼链）", ("join_segments", "核对")),
    ("⑤ 拼不起来就如实报哪一段缺", ("哪一段",)),
    ("⑤ 不把没搜完说成没有这条路", ("没搜完",)),
    ("⑥ 补全之后仍绕弯/全是跳变就上报", ("上报",)),
)

#: 阈值式硬规定：出现这些就是"把判断写成了死判据"（与「自然路径」那一节同一口径）。
THRESHOLD_PATTERNS: tuple[str, ...] = (
    r"hops\s*(?:<=|>=|<|>|≤|≥|==?)\s*\d+",
    r"(?:跳数|hops|步数|steps)\s*(?:不超过|不少于|少于|大于|小于|等于|至多|至少)\s*\d+",
    r"\d+\s*跳\s*(?:以内|以上|以下|才算)",
    r"才算自然",
    r"才叫自然",
)

#: 强调符号与空白：正文里加不加星号是同一句话（按读到的意思判）。
_EMPHASIS = re.compile(r"[\s*`]+")


def _flat(text: str) -> str:
    return _EMPHASIS.sub("", text)


def _paragraphs(body: str) -> list[str]:
    """按空行切段（一段里同时出现才算"把这件事说在一起"）。"""
    return [p for p in re.split(r"\n\s*\n", body) if p.strip()]


def skill_loop_problems(body: str) -> list[str]:
    """判据 4 的判据体（空列表 = 过）。"""
    out: list[str] = []
    paras = [_flat(p) for p in _paragraphs(body)]
    for name, needles in LOOP_NEEDS:
        if not any(all(_flat(n) in para for n in needles) for para in paras):
            shown = "、".join(needles)
            out.append(f"技能正文里读不到「{name}」（同一段里应当出现「{shown}」）")
    for pat in THRESHOLD_PATTERNS:
        hit = re.search(pat, body)
        if hit:
            out.append(f"技能正文里出现了阈值式硬规定 `{hit.group(0)}` —— "
                       "搜几批、要不要拼该由模型判")
    return out


# ---------------------------------------------------------------- 判据 5：三态


def tri_state_problems(payload: dict) -> list[str]:
    """判据 5 的判据体：一批就到根 ⇒ `frontier == []` 且 `checked=True`。"""
    out: list[str] = []
    if payload.get("closed") is not True:
        out.append(f"这条链一批就到根，`closed` 却不是真：{payload.get('closed')!r}")
    if payload.get("frontier"):
        out.append(f"一批就到根却报了前沿：{payload.get('frontier')!r}")
    if payload.get("frontier_checked") is not True:
        out.append("`frontier_checked` 不是真 ⇒ 『没有前沿』被读成了『没查成』")
    if str(payload.get("frontier_note") or "").strip():
        out.append(f"没有前沿、全都到根了，`frontier_note` 却留了一句话："
                   f"{payload.get('frontier_note')!r}")
    if "frontier" not in payload:
        out.append("`frontier` 这一格被省略了（没有前沿时也要给空列表）")
    return out


# ------------------------------------------------------------------ 判据 1 / 2 / 3


def test_one_batch_stops_at_the_depth_limit_and_says_where(tmp_path: pathlib.Path):
    """判据 1：12 步链、一批 `max_depth=6` ⇒ 到不了根，但前沿点名停在哪、为什么。"""
    agent = AgentC(_twelve_steps(tmp_path))
    rep = agent.proof_chain(TARGET, max_depth=BATCH_DEPTH)
    assert rep.ok, rep.error
    problems = frontier_problems(rep.payload)
    assert problems == [], "\n  - " + "\n  - ".join(problems)
    # 正控：这一批真的没到根，而且"没到根"的原因就在前沿上（不是别的原因）。
    assert rep.payload["closed"] is False
    assert [f["node"] for f in rep.payload["frontier"]] == [EXPECTED_FRONTIER]
    assert [f["why"] for f in rep.payload["frontier"]] == [PS.FRONTIER_DEPTH_LIMIT]
    # 那一条前沿说的路径号，指的正是读数里那一行（拼的时候要照它走同一条）。
    item = rep.payload["frontier"][0]
    assert f"p{item['proof_no']}g{item['path_group']}" in _rows_by_id(rep.payload)


def test_the_next_batch_starts_from_the_frontier_and_reaches_the_root(
        tmp_path: pathlib.Path):
    """判据 2 + 3：以前沿为起点再搜一批 ⇒ 到根；两批拼起来与一次搜到底同读数。

    "两批"是这条判据自己驱动的两次调用 —— 框架里没有自动接着搜的循环。
    """
    agent = AgentC(_twelve_steps(tmp_path))
    batch1 = agent.proof_chain(TARGET, max_depth=BATCH_DEPTH)
    assert batch1.ok, batch1.error
    frontier = list(batch1.payload.get("frontier") or [])
    assert frontier, "夹具前提：第一批必须停在某个前沿上"
    start = frontier[0]["node"]
    batch2 = agent.proof_chain(start, max_depth=BATCH_DEPTH)
    assert batch2.ok, batch2.error
    # 这一行是"照着读数做"的判据：`frontier` 给的 `node` 是 `stmt:0008` 这种写法，
    # 下一批的 target 必须认它 —— 不认的时候模型会得到"目标找不到"，而链本来是接得上的。
    assert batch2.payload["node"]["stmt_id"] == "0008", batch2.payload.get("node")
    full = agent.proof_chain(TARGET, max_depth=20)
    assert full.ok, full.error
    joined = PS.join_segments([batch1.payload, batch2.payload])
    problems = joined_problems(batch1.payload, batch2.payload, joined, full.payload)
    assert problems == [], "\n  - " + "\n  - ".join(problems)
    # 正控：合并后确实是一条到根的链，且两段之间存在一处接缝。
    assert joined["complete"] is True and len(joined["seams"]) == 1
    assert joined["seams"][0]["at_node"] == start


def test_a_wrong_next_start_is_refused_not_silently_glued(tmp_path: pathlib.Path):
    """判据 3 的负控：第二批的起点不在前沿里 ⇒ `checked=False` + 点名，不许给完整链。"""
    agent = AgentC(_twelve_steps(tmp_path))
    batch1 = agent.proof_chain(TARGET, max_depth=BATCH_DEPTH)
    bad_start = "stmt:0011"
    assert bad_start not in [f["node"] for f in batch1.payload["frontier"]]
    wrong = agent.proof_chain(bad_start, max_depth=BATCH_DEPTH)
    assert wrong.ok, wrong.error
    joined = PS.join_segments([batch1.payload, wrong.payload])
    problems = seam_refused_problems(batch1.payload, joined, bad_start)
    assert problems == [], "\n  - " + "\n  - ".join(problems)


# ------------------------------------------------------------------- 判据 5


def test_a_short_chain_has_no_frontier_but_that_is_not_a_failure(
        tmp_path: pathlib.Path):
    """判据 5：一批就到根 ⇒ `frontier == []` 且 `checked=True`（三态不许折平）。"""
    agent = AgentC(_short_chain(tmp_path))
    rep = agent.proof_chain("0010", max_depth=BATCH_DEPTH)
    assert rep.ok, rep.error
    problems = tri_state_problems(rep.payload)
    assert problems == [], "\n  - " + "\n  - ".join(problems)
    # 同一份读数再拼一批（只有一段）：没有接缝，但仍然是一条到根的链。
    joined = PS.join_segments([rep.payload])
    assert joined["checked"] is True and joined["complete"] is True, joined
    assert joined["seams"] == [] and len(joined["segments"]) == 1, joined


# ------------------------------------------------------------------- 判据 4


def test_the_skill_teaches_the_batch_loop(tmp_path: pathlib.Path):
    """判据 4：技能那一节必须含动作循环的六条实质，而且没有阈值式硬规定。"""
    rows = {s.slug: s for s in AS.CATALOG["C"]}
    assert NATURAL_SLUG in rows, f"C 那一岗没有这一节：{sorted(rows)}"
    skill = rows[NATURAL_SLUG]
    problems = skill_loop_problems(skill.body)
    assert problems == [], "\n  - " + "\n  - ".join(problems)
    # 它必须指向那一列真的读数与那个真的调用（不是一句泛泛的"再看一眼"）。
    assert "C.proof_chain" in skill.actions, skill.actions
    assert "frontier" in skill.body and "path_shapes" in skill.body
    # 反真空：正文得真的在讲这件事（不是一段能凑出关键词的空话）。
    assert len(skill.body) > 2000, len(skill.body)


def test_the_negative_control_catches_a_missing_frontier_step():
    """判据 4 的负控：删掉"看 frontier、以前沿为下一批起点"那些行 ⇒ 必红。

    没有这一条，"看 frontier 再接着搜"就只是一句注释：正文里其余五条的词一个不少，
    判据照样绿。
    """
    rows = {s.slug: s for s in AS.CATALOG["C"]}
    body = rows[NATURAL_SLUG].body
    assert skill_loop_problems(body) == [], "夹具前提：真身是干净的"
    dropped = "\n".join(
        line for line in body.splitlines()
        if "frontier" not in line
        and not ("前沿" in line and ("target" in line or "起点" in line)))
    assert dropped != body, "夹具前提：正文里真有写着 frontier 的行"
    got = skill_loop_problems(dropped)
    assert any("frontier" in p for p in got), got


# ------------------------------------------------------------------- 判据 6


def test_the_frontier_readout_is_not_vacuous_an_always_empty_one_must_go_red(
        tmp_path: pathlib.Path, monkeypatch):
    """判据 6：把 `frontier` 恒置空 ⇒ 判据 1 必须红（判据 1 不是"永远绿"）。"""
    good = AgentC(_twelve_steps(tmp_path / "base")).proof_chain(TARGET, max_depth=BATCH_DEPTH)
    assert frontier_problems(good.payload) == [], "夹具前提：基线上判据 1 是绿的"

    real = PC.path_shapes

    def _no_frontier(graph, target, groups, *, max_depth=4):
        got = real(graph, target, groups, max_depth=max_depth)
        # 改前那一层能给的读数长这样：深处停下的行照旧"没到根"，但没有一处说得出
        # 停在哪个节点 —— 于是"还没搜完"和"这条路不存在"在读的人眼里一样。
        return {**got, "frontier": [], "frontier_note": ""}

    monkeypatch.setattr(PC, "path_shapes", _no_frontier, raising=False)
    bad = AgentC(_twelve_steps(tmp_path / "stub")).proof_chain(TARGET, max_depth=BATCH_DEPTH)
    problems = frontier_problems(bad.payload)
    assert problems, "反真空失效：前沿恒空时，判据 1 居然还是绿的"
    assert any("空列表" in p for p in problems), problems
