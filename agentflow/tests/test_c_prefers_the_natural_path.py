# -*- coding: utf-8 -*-
"""C 的「最自然路径」：候选路径的形状读数 + 技能文本（业主 2026-10-22）。

业主原话（需求真身）：

> 「分析最自然，最直接的关系路径（不只是看最短依赖链）。比如一个 T4 级的东西无依赖地
>  生生证出来了，还有一条路线是循序渐进花五六个大步骤自然推出，我们肯定不希望用前者。
>  但是如果在那一顿绕弯子，有许多不直接支撑证明的引理或定理在依赖链上，C 应该不选它。
>  如果曲折的路径是已收录的唯一路径，则应该上报让父代理找 D 组织研究，并提出自己的构想。
>  总之这是 LLM 驱动。」

分工是这一组判据的前提：机械侧只摆形状（`agent_c/path_shape.py`，读数进
`C.proof_chain` 的 payload），判断侧在技能文本里（`agent_skills.py` 的 C 那一岗）。
所以这里既不判"哪条更自然"（那是模型的事），也不给"自然度分数"式的伪判据 ——
只判"形状摆出来了没有、摆得对不对、文本有没有把三条判据与上报口径说清"。

五条判据（前三条各配一个纯函数判据体，第五条靠它做反真空）：

1. 读数存在且不止一行：两条到根路径（一条无依赖直达 = 一跳落到一个自己没有任何
   依赖的自证定理上；一条 5 步循序渐进）⇒ 两条都在，各自带全
   `hops` / `steps` / `gaps` / `detour_nodes` / `alternatives` 等格；
   另有一面是业主原话里最刺眼的那种：目标自己无依赖却已到根 ⇒ 那一行读出
   `hops=0` / `steps=0` / `gaps=1`，而"依赖没写"的同一形态必须 `reached=False`；
2. 绕弯可识别：中间挂一条只被中间节点引用、目标并不直接用到它的引理 ⇒ 它出现在
   `detour_nodes` 里，而它那条边不在 `support_edges` 里；
3. 唯一路径可识别：同一目标只有一条路径、而它带着 `gaps` 与 `detour_nodes` ⇒
   `alternatives == 0` 且形状如实（"唯一且有跳变"在读数上分得开）；
4. 技能文本：C 的那一节必须含三条判据的实质（循序渐进优先 / 绕弯不选 /
   唯一曲折要上报并给构想），且不许出现阈值式硬规定；
5. 反真空：把读数换成"只给最短那条、且只有跳数一格"的替身（也就是改前那一层
   能给的读数）⇒ 判据 1 与判据 3 必须各自报出问题。

零模型、零网络：夹具全在 `tmp_path` 下自建，`proof_chain` 是确定性代码。
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from agentflow import agent_skills as AS          # noqa: E402
from agentflow import schema as S                 # noqa: E402
from agentflow.agent_c import AgentC               # noqa: E402
from agentflow.agent_c import proof_chain as PC    # noqa: E402
from agentflow.store import Store                  # noqa: E402

#: 夹具时间戳写死（不依赖当前时间）。
TS = "2026-10-22T00:00:00+08:00"

#: 每条候选路径一行必须带的格（业主 2026-10-22 点名的那一列）。
SHAPE_KEYS: tuple[str, ...] = (
    "path_id", "proof_no", "path_group", "hops", "steps", "gaps",
    "detour_nodes", "off_path_ratio", "support_edges", "alternatives",
)


# --------------------------------------------------------------------- 夹具


def _store(root: pathlib.Path) -> Store:
    st = Store(root / "ws")
    st.init()
    return st


def _stmt(st: Store, sid: str, *, kind: str = "theorem",
          evidence: str = "cross_check", proof_text: str = "") -> None:
    row = S.Statement(stmt_id=sid, origin="own_result", kind=kind,
                      label=f"{kind} {sid}", statement_text="短版",
                      statement_full="若假设 A 成立，则结论 B 成立",
                      proof_text=proof_text, source_lit_id=None,
                      quote_verified=None, quote_reason="夹具（还没核）",
                      evidence_kind=evidence, aliases=[], status="active",
                      created_at=TS)
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict(), note="stmt")


def _lit(st: Store, lid: str) -> None:
    row = S.Literature(lit_id=lid, title=f"文献 {lid}", type="J", summary="s",
                       path=None, added_at=TS)
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", row.to_dict(), note="lit")


def _dep(st: Store, did: str, used_by: str, *, stmt: str = "", lit: str = "",
         kind: str = "theorem", group: int = 1, status: str = "closed") -> None:
    row = S.Dependency(dep_id=did, used_by=used_by, kind=kind, label="前提",
                       status=status, status_reason="",
                       source_stmt_id=stmt or None, source_experiment_id=None,
                       source_lit_id=lit or None, path_group=group, created_at=TS)
    row.validate()
    with st.tx("dependencies", actor="test") as tx:
        tx.upsert("dependencies", row.to_dict(), note="dep")


def _two_paths(root: pathlib.Path) -> Store:
    """两条都走到根的候选路径：组 2 = 无依赖直达（一跳）；组 1 = 5 步循序渐进。

    组 2 那一跳落在 0002 上：它自己一条依赖都没有，却带着 `evidence_kind=proof`
    被当成根 —— 这正是业主说的"T4 级的东西无依赖地生生证出来"。组 1 则是一步
    接着一步、最后落到一篇文献上。
    """
    st = _store(root)
    _lit(st, "0009")
    for sid in ("0001", "0010", "0011", "0012", "0013"):
        _stmt(st, sid)
    _stmt(st, "0002", evidence="proof", proof_text="Proof. 检查器核过。")
    _dep(st, "900002", "stmt:0001", stmt="0002", group=2)
    _dep(st, "900010", "stmt:0001", stmt="0010", group=1)
    _dep(st, "900011", "stmt:0010", stmt="0011", group=1)
    _dep(st, "900012", "stmt:0011", stmt="0012", group=1)
    _dep(st, "900013", "stmt:0012", stmt="0013", group=1)
    _dep(st, "900014", "stmt:0013", lit="0009", kind="prior_art", group=1)
    return st


def _with_detour(root: pathlib.Path) -> Store:
    """一条链，中间那个节点（0002）挂着一条只被它引用、结论并不用到的引理（0004）。

    0002 有两条分支：组 1 走到文献（承重），组 2 指向 0004（一条依赖没写的引理）。
    0004 只被中间节点 0002 引用，目标 0001 与它的直接前提都碰不到它。
    """
    st = _store(root)
    _lit(st, "0009")
    for sid in ("0001", "0002", "0003", "0004"):
        _stmt(st, sid)
    _dep(st, "900001", "stmt:0001", stmt="0002")
    _dep(st, "900002", "stmt:0002", stmt="0003", group=1)
    _dep(st, "900003", "stmt:0002", stmt="0004", group=2)
    _dep(st, "900004", "stmt:0003", lit="0009", kind="prior_art")
    return st


def _unique_crooked(root: pathlib.Path) -> Store:
    """唯一一条路径，而它同时带着跳变（0003 无依赖却是根）与旁挂引理（0004）。"""
    st = _store(root)
    _lit(st, "0009")
    for sid in ("0001", "0002", "0005"):
        _stmt(st, sid)
    _stmt(st, "0003", evidence="proof", proof_text="Proof. 无依赖自证。")
    _stmt(st, "0004")
    _dep(st, "900001", "stmt:0001", stmt="0002")
    _dep(st, "900002", "stmt:0001", stmt="0003")
    _dep(st, "900003", "stmt:0002", stmt="0005")
    _dep(st, "900004", "stmt:0005", lit="0009", kind="prior_art")
    _dep(st, "900005", "stmt:0002", stmt="0004", group=2)
    return st


# --------------------------------------------------- 判据体（纯函数，供反真空复用）


def _rows_by_id(payload: dict) -> dict[str, dict]:
    return {str(r.get("path_id") or ""): r for r in (payload.get("path_shapes") or [])}


def _key_problems(rows: list[dict]) -> list[str]:
    """每一行都要带全那几格（少一格就等于那一格没算）。"""
    out: list[str] = []
    for i, row in enumerate(rows):
        missing = [k for k in SHAPE_KEYS if k not in row]
        if missing:
            out.append(f"第 {i} 行少了这些格：{missing}（这一行实有的键：{sorted(row)}）")
    return out


def two_paths_problems(payload: dict) -> list[str]:
    """判据 1 的判据体（空列表 = 过）。"""
    out: list[str] = []
    if not payload.get("path_shapes_checked"):
        out.append("`path_shapes_checked` 不是真 ⇒ 形状没算成（没算不等于没有候选路径）")
    rows = list(payload.get("path_shapes") or [])
    if len(rows) < 2:
        out.append(f"读数里只有 {len(rows)} 条候选路径 ⇒ 只剩『最短那条』一行"
                   "（两条都到根的路必须都摆出来，否则模型只能比较一条）")
    out.extend(_key_problems(rows))
    by_id = _rows_by_id(payload)
    direct = by_id.get("p1g2")
    gradual = by_id.get("p1g1")
    if direct is None:
        out.append(f"无依赖直达那条（p1g2）不在读数里：{sorted(by_id)}")
    else:
        if int(direct.get("hops") or 0) != 1:
            out.append(f"无依赖直达那条应当是一跳：hops={direct.get('hops')!r}")
        if int(direct.get("gaps") or 0) < 1:
            out.append(f"无依赖直达那条没有报出跳变：gaps={direct.get('gaps')!r}"
                       f" gap_nodes={direct.get('gap_nodes')!r}")
        if not direct.get("gap_nodes"):
            out.append("跳变那一处没有点名是哪个节点（gap_nodes 是空的）")
        if int(direct.get("alternatives") or 0) != 1:
            out.append(f"同目标还有一条别的路径，alternatives 应当是 1："
                       f"{direct.get('alternatives')!r}")
    if gradual is None:
        out.append(f"5 步循序渐进那条（p1g1）不在读数里：{sorted(by_id)}")
    else:
        if int(gradual.get("hops") or 0) != 5:
            out.append(f"循序渐进那条应当是 5 跳：hops={gradual.get('hops')!r}")
        if int(gradual.get("steps") or 0) != 5:
            out.append(f"循序渐进那条应当是 5 个大步骤：steps={gradual.get('steps')!r}")
        if int(gradual.get("gaps") or 0) != 0:
            out.append(f"循序渐进那条不该有跳变：gaps={gradual.get('gaps')!r}"
                       f" gap_nodes={gradual.get('gap_nodes')!r}")
        if len(gradual.get("support_edges") or []) != 5:
            out.append("循序渐进那条的承重边应当是 5 条："
                       f"{gradual.get('support_edges')!r}")
        if int(gradual.get("alternatives") or 0) != 1:
            out.append(f"同目标还有一条别的路径，alternatives 应当是 1："
                       f"{gradual.get('alternatives')!r}")
    # 最短那条仍然是"最短"（proof_chain 的读数没被这一层改写），
    # 而循序渐进那条照样在读数里 —— 这两件事同时成立才叫"不只是看最短依赖链"。
    if payload.get("best_group") != 2:
        out.append(f"最短那组变了：best_group={payload.get('best_group')!r}"
                   "（形状读数不许改 shortest 的口径）")
    return out


def detour_problems(payload: dict) -> list[str]:
    """判据 2 的判据体（空列表 = 过）。"""
    out: list[str] = []
    rows = list(payload.get("path_shapes") or [])
    if len(rows) != 1:
        out.append(f"这个夹具只有一条候选路径，实得 {len(rows)} 行")
    out.extend(_key_problems(rows))
    row = rows[0] if rows else {}
    detour = [str(n) for n in (row.get("detour_nodes") or [])]
    if detour != ["stmt:0004"]:
        out.append(f"旁挂的那条引理没被点出来：detour_nodes={detour!r}")
    if "stmt:0004" in (row.get("spine_nodes") or []):
        out.append("旁挂节点同时出现在承重脊上（两处口径互相打架）")
    if "stmt:0004" in [str(e.get("to") or "") for e in (row.get("support_edges") or [])]:
        out.append("旁挂那条边被算进了 support_edges（它不支撑结论）")
    if float(row.get("off_path_ratio") or 0.0) <= 0.0:
        out.append(f"有旁挂节点，off_path_ratio 却不大于 0：{row.get('off_path_ratio')!r}")
    # 反真空：承重的那三个节点不许被误报成旁挂（否则"旁挂"就等于"所有节点"）
    for node in ("stmt:0002", "stmt:0003", "lit:0009"):
        if node in detour:
            out.append(f"承重节点 {node} 被报成了旁挂 ⇒ 这条判据只是噪音")
    return out


def unique_crooked_problems(payload: dict) -> list[str]:
    """判据 3 的判据体（空列表 = 过）。"""
    out: list[str] = []
    rows = list(payload.get("path_shapes") or [])
    if len(rows) != 1:
        out.append(f"这个夹具只有一条候选路径，实得 {len(rows)} 行")
    out.extend(_key_problems(rows))
    row = rows[0] if rows else {}
    if int(row.get("alternatives") or 0) != 0:
        out.append(f"唯一一条路径的 alternatives 应当是 0：{row.get('alternatives')!r}")
    if int(row.get("gaps") or 0) < 1 or not (row.get("gap_nodes") or []):
        out.append("这条唯一路径带着无依赖跳变，gaps / gap_nodes 却没报出来："
                   f"gaps={row.get('gaps')!r} gap_nodes={row.get('gap_nodes')!r}")
    if not (row.get("detour_nodes") or []):
        out.append("这条唯一路径挂着旁挂引理，detour_nodes 却是空的："
                   f"{row.get('detour_nodes')!r}")
    if not row.get("reached"):
        out.append("这条唯一路径走得到根，reached 却不是真")
    return out


# --------------------------------------------------------------- 判据 1 / 2 / 3


def test_the_readout_keeps_more_than_the_shortest_path(tmp_path: pathlib.Path):
    """判据 1：两条到根路径都在读数里，各自带全那几格（不许只剩最短那条）。"""
    rep = AgentC(_two_paths(tmp_path)).proof_chain("0001", max_depth=8)
    assert rep.ok, rep.error
    problems = two_paths_problems(rep.payload)
    assert problems == [], "、".join(problems)
    # 正控：那一列真的是一行一条路径，而不是把一条路径拆成几行
    assert len(rep.payload["path_shapes"]) == rep.payload["groups_total"] == 2


def test_the_target_itself_being_a_bare_root_is_a_jump_not_a_good_path(
        tmp_path: pathlib.Path):
    """判据 1 的第二面（业主原话里最刺眼的那种形状）：目标自己无依赖却已到根。

    这一行必须把"它是一处跳变"读出来：`hops=0`、`steps=0`、`gaps=1`、
    `gap_nodes` 点名目标自己、`alternatives=0`。同一形态若"不是根"（依赖没写），
    那一行必须是 `reached=False` —— 三态不许折平（"没写依赖"不是"无依赖地证出来了"）。
    """
    st = _store(tmp_path / "bare")
    _stmt(st, "0001", evidence="proof", proof_text="Proof. 检查器核过。")
    rep = AgentC(st).proof_chain("0001")
    assert rep.payload["closed"] is True, rep.payload
    rows = list(rep.payload.get("path_shapes") or [])
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["path_id"] == "target-is-root", row
    assert (row["hops"], row["steps"], row["gaps"]) == (0, 0, 1), row
    assert row["gap_nodes"] == ["stmt:0001"], row
    assert row["alternatives"] == 0 and row["support_edges"] == [], row
    # 反真空的另一半：同一条命题去掉证明证据 ⇒ 那一行不许再说它"到根了"
    st2 = _store(tmp_path / "unwritten")
    _stmt(st2, "0001", evidence="heuristic")
    rep2 = AgentC(st2).proof_chain("0001")
    rows2 = list(rep2.payload.get("path_shapes") or [])
    assert len(rows2) == 1 and rows2[0]["reached"] is False, rows2
    assert rows2[0]["gaps"] == 0 and rows2[0]["why"], rows2


def test_a_detour_lemma_is_named_not_swallowed(tmp_path: pathlib.Path):
    """判据 2：只被中间节点引用、结论并不用到的引理 ⇒ 进 detour_nodes。"""
    rep = AgentC(_with_detour(tmp_path)).proof_chain("0001")
    assert rep.ok, rep.error
    problems = detour_problems(rep.payload)
    assert problems == [], "、".join(problems)


def test_a_unique_crooked_path_is_visible_as_such(tmp_path: pathlib.Path):
    """判据 3：唯一一条路径带着跳变与旁挂 ⇒ `alternatives == 0` 且形状如实。"""
    rep = AgentC(_unique_crooked(tmp_path)).proof_chain("0001", max_depth=8)
    assert rep.ok, rep.error
    problems = unique_crooked_problems(rep.payload)
    assert problems == [], "、".join(problems)


# ------------------------------------------------------------------- 判据 4

#: C 那一节的名字（写进 `agent_skills.CATALOG["C"]` 的那一条 slug）。
NATURAL_SLUG = "自然路径-循序渐进优先且绕弯不选"

#: "必须说到的实质"：键 = 人的叫法，值 = 正文里必须找得到的那串（去强调与空白后比）。
NATURAL_NEED: dict[str, str] = {
    "① 循序渐进优先": "循序渐进",
    "① 不是无依赖跳变": "无依赖",
    "② 绕弯不选": "绕弯",
    "② 不直接支撑结论的引理": "不直接支撑",
    "③ 唯一且曲折": "唯一",
    "③ 上报而不是默认接受": "上报",
    "③ 提出构想": "构想",
    "上报口径（真的通道）": "conductor.escalate",
    "构想至少一条可执行建议": "造工具",
}

#: 阈值式硬规定：一段文本里出现这些就是"把判断写成了死判据"。
THRESHOLD_PATTERNS: tuple[str, ...] = (
    r"hops\s*(?:<=|>=|<|>|≤|≥|==?)\s*\d+",
    r"(?:跳数|hops|步数|steps)\s*(?:不超过|不少于|少于|大于|小于|等于|至多|至少)\s*\d+",
    r"\d+\s*跳\s*(?:以内|以上|以下|才算)",
    r"才算自然",
    r"才叫自然",
)

#: 强调符号与空白：`派 D 去核` 与 `派 **D** 去核` 是同一句话（按读到意思判）。
_EMPHASIS = re.compile(r"[\s*`]+")


def _flat(text: str) -> str:
    return _EMPHASIS.sub("", text)


def natural_text_problems(body: str) -> list[str]:
    """C 那一节的正文：三条判据的实质齐不齐、有没有阈值式硬规定（纯函数）。"""
    flat = _flat(body)
    out = [f"正文里读不到「{name}」（应当出现「{needle}」）"
           for name, needle in NATURAL_NEED.items() if needle not in flat]
    for pat in THRESHOLD_PATTERNS:
        hit = re.search(pat, body)
        if hit:
            out.append(f"正文里出现了阈值式硬规定 `{hit.group(0)}` —— 自然与否该由模型判，"
                       "不该由一条数字门槛替它判")
    return out


def test_the_skill_says_what_natural_means_and_what_to_do_when_it_is_the_only_path():
    """判据 4：技能文本含三条判据的实质 + 上报口径 + 构想的形状，且没有阈值。"""
    rows = {s.slug: s for s in AS.CATALOG["C"]}
    assert NATURAL_SLUG in rows, f"C 那一岗没有这一节：{sorted(rows)}"
    skill = rows[NATURAL_SLUG]
    problems = natural_text_problems(skill.body)
    assert problems == [], "\n  - " + "\n  - ".join(problems)
    # 它必须指向那个真的读数与那两条真的通道（不是一句泛泛的"去上报"）
    assert "C.proof_chain" in skill.actions, skill.actions
    assert "path_shapes" in skill.body, "正文没有指向形状读数那一列"
    assert "conductor.escalate" in skill.tools, skill.tools
    # 反真空：正文得真的在讲这件事（不是一段能凑出关键词的空话）
    assert len(skill.body) > 800, len(skill.body)
    assert "hop" in skill.body or "跳" in skill.body, "正文没提跳数那一格"


def test_the_negative_control_catches_a_threshold_rule(monkeypatch):
    """判据 4 的负控：往正文里塞一条数字门槛 ⇒ 判据必须当场红。

    没有这一条，"不许出现阈值"就只是一句注释：阈值加回去，三条判据的关键词
    一个不少，判据照样绿。"""
    rows = {s.slug: s for s in AS.CATALOG["C"]}
    body = rows[NATURAL_SLUG].body
    assert natural_text_problems(body) == [], "夹具前提：真身是干净的"
    for bad in ("hops<=3 才算自然。", "步数 不超过 4 才算自然。", "3 跳以内才算自然。"):
        got = natural_text_problems(body + "\n\n" + bad)
        assert got, f"负控失效：把 `{bad}` 加进去，判据却放过了"


def test_the_negative_control_catches_a_missing_report_line(monkeypatch):
    """判据 4 的反真空之二：把"上报 + 构想"整段删掉 ⇒ 必须红（删掉不等于改对）。"""
    rows = {s.slug: s for s in AS.CATALOG["C"]}
    body = rows[NATURAL_SLUG].body
    dropped = "\n".join(line for line in body.splitlines()
                        if "上报" not in line and "构想" not in line)
    assert dropped != body, "夹具前提：正文里真有写着上报与构想的行"
    got = natural_text_problems(dropped)
    assert any("上报" in p for p in got), got
    assert any("构想" in p for p in got), got


# ------------------------------------------------------------------- 判据 5


def test_the_readout_is_not_vacuous_a_shortest_only_stub_must_go_red(tmp_path,
                                                                   monkeypatch):
    """判据 5：把读数换成"只给最短那条、且只有跳数一格"（改前那一层能给的读数）
    ⇒ 判据 1 与判据 3 必须各自报出问题。

    "判据 1 过"与"读数真的摆了两条路"必须分得开：没有这一条，一个只返回最短那条的
    替身会让判据 1 与 3 一起变绿，而它们看起来像在守着"两条路径都摆出来"。"""
    real = PC.path_shapes

    def _stub_only_the_shortest(graph, target, groups, *, max_depth=4):
        got = real(graph, target, groups, max_depth=max_depth)
        rows = [r for r in got["rows"] if r.get("reached")]
        rows.sort(key=lambda r: (int(r.get("hops") or 0), r.get("proof_no") or 1,
                                 r.get("path_group") or 1))
        keep = rows[0] if rows else (got["rows"][0] if got["rows"] else {})
        # 改前那一层能给的：一条路径，只有跳数一格。
        slim = {"path_id": "best", "proof_no": keep.get("proof_no"),
                "path_group": keep.get("path_group"), "hops": keep.get("hops")}
        return {"checked": True, "total": got["total"], "note": "", "rows": [slim]}

    # 先证明基线上这两条判据是绿的（否则下面的红分不清是谁的功劳）
    good_two = AgentC(_two_paths(tmp_path / "base")).proof_chain("0001", max_depth=8)
    good_one = AgentC(_unique_crooked(tmp_path / "base2")).proof_chain("0001", max_depth=8)
    assert two_paths_problems(good_two.payload) == []
    assert unique_crooked_problems(good_one.payload) == []

    monkeypatch.setattr(PC, "path_shapes", _stub_only_the_shortest, raising=False)
    bad_two = AgentC(_two_paths(tmp_path / "stub")).proof_chain("0001", max_depth=8)
    bad_one = AgentC(_unique_crooked(tmp_path / "stub2")).proof_chain("0001", max_depth=8)
    p1 = two_paths_problems(bad_two.payload)
    p3 = unique_crooked_problems(bad_one.payload)
    assert p1, "反真空失效：只剩最短那条时，判据 1 居然还是绿的"
    assert p3, "反真空失效：只剩最短那条时，判据 3 居然还是绿的"
    # 两处报的必须是"缺了形状"，而不是别的原因（否则那两条判据在测别的）
    assert any(("少了这些格" in p) or ("只有 1 条" in p) for p in p1), p1
    assert any("少了这些格" in p for p in p3), p3
