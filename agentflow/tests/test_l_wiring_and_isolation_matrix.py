# -*- coding: utf-8 -*-
"""L 的协作面与 Lean 开关的接线矩阵：七条判据（A1/A2/A3 与 E12–E15）。

## 这一份判什么

业主 2026-10-22 晚的裁定把 L 的协作面压成很短的一句：只有 B 可以派 L，L 只派 C；
Lean 开关没开时 L 整条不存在。本文件把它拆成两层各判一遍：先判声明的边表，再判
Conductor 闸门上的实测判决，最后判那道开关在四个面（角色表 / 工具面 / 名册 / 提示词）
上的两种取值。

| 编号 | 判据 | 改前红（本文件加进来之前的那棵树） |
|---|---|---|
| A1 | 遍历每一个角色：指向 L 的入边只有 B；L 在可召唤名单里、不在不可召唤名单里 | 改前 `S.ROLES` 是九个角色（A–H、V），树里没有 `agent_l` / `specs/l.py` / `leanscope`：没有 L 这个角色，`inbound == ["B"]` 读到的是空清单，当场红 |
| A2 | L 的出边恰好一条 C；L 派任何别的角色（含自己与主控）一律 forbidden_edge | 改前 `ALLOWED_EDGES` 里没有 "L" 这个键（`edges["L"]` 不存在）⇒ KeyError 当场红 |
| A3 | 边表不算数：M 与其余每个角色在 `Conductor.summon` 上实测拿 refused / forbidden_edge，而 B 那一条通 | 改前 L 不是角色 ⇒ 正控那一半（B → L 被受理）红；负控在"没有这个角色"上恒真，是真空的 |
| E12 | 开关关：角色表 / 可召唤名单 / 工具面 / 名册 / 画像 / 十个角色的提示词里 L = 0、formal. = 0 | 改前没有开关这一层，也没有 L：纯"关"的那一半在空集上是真空绿。本用例把同一个读数在开着那一档先验成正控，改前那一半当场红 |
| E13 | 开关开：以上每一项都看得见，且 `formal.*` 真能调到 | 改前开与关是同一档（`leanscope` 不存在）⇒ 红 |
| E14 | 同一进程里 关 → 开 → 再关：四个面的读数跟着走，且判定入口不缓存 | 改前没有判定入口，三档读数完全相同 ⇒ 红 |
| E15 | 反真空：把唯一判定入口 `is_hidden` 钉成恒 False ⇒ E12 的判据函数必红 | 若 E12 读的不是那个入口，钉死之后它照样绿；改前连这个入口都没有 ⇒ 红 |

## 零模型、零 Lean

A1/A2 与 E12–E15 只读代码与本地开关（不起子进程、不调模型）。A3 走一次真实的
`Conductor.summon`，但送进去的源码刻意没有具名定理 / 引理 ⇒ 在写盘与起检查器之前
就被受控拒绝，所以整份文件一次 Lean 都不起、一次模型请求都没有。

## 临时文件

需要工作区的两条（A3 与 E13）都在 `tmp_path` 下自建；本文件不写任何固定路径。
"""
from __future__ import annotations

import pathlib
import re

import pytest

from agentflow import agent_prompts as AP
from agentflow import agentspec as AS
from agentflow import capabilities as C
from agentflow import leanscope as LS
from agentflow import policy as P
from agentflow import schema as S
from agentflow import settings as SET
from agentflow.store import Store
from agentflow.tools import TOOL_ROLES, build_registry
from agentflow.tools import conductor_tools as CT

#: 被形式化的那条命题（与 A3 送进去的"没有定理的源码"无关：那一条不写盘）。
CLAIM = "forall n : Nat, n + 0 = n"
#: 命题台账里那一行的标题。
LABEL = "加零不改变自然数"

#: 一个不是角色名的 L 记号。为什么不用 `\bL\b`：Python 的 `re` 把中日韩字符算作
#: `\w`，于是"角色 L"里那个 L 与左边的汉字之间没有词边界（`tests/test_l_is_isolated_when_lean_is_off.py`
#: 逐字登记过这一跤）。边界按 ASCII 词字符算，所以 `Lean` / `Mathlib` 里的 L 不算。
ROLE_NAME = re.compile(r"(?<![A-Za-z0-9_])L(?![A-Za-z0-9_])")

#: L 的三件工具（工具面那三件的名字；开关关着时一件都不许装配）。
FORMAL_TOOLS = ("formal.check_formal", "formal.formalize", "formal.record")

#: 全部角色（含主控）。由 `schema` 现算：手抄一份名单会让"新加的角色"自动漏过这条判据。
ALL_ROLES = tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)

#: 一段没有具名定理 / 引理的"源码"：A3 用它让动作在写盘之前被受控拒绝，
#: 于是那条判据一次 Lean 都不起。
NO_THEOREM = "def not_a_theorem : Nat := 0\n"


# ============================================================ 开关与工作区


def _reset_readings() -> None:
    """清掉两层读数缓存（`leantoolchain` 的自检缓存与提示词那个 lru_cache）。

    不调用它，"改了环境变量但提示词停在旧值"会被误读成"隔绝没生效"：那是两件事，
    必须分得开（这一句与 `tests/test_l_is_isolated_when_lean_is_off.py` 同口径）。
    """
    from agentflow import leantoolchain as LT

    LT.reset_reading_cache()
    AP.reset_toolchain_readings()


def _lean_env(monkeypatch: pytest.MonkeyPatch, on: bool) -> None:
    """把 Lean 开关钉到某一档，并清掉读数缓存（零子进程）。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1" if on else "0")
    _reset_readings()


def _workspace(tmp_path: pathlib.Path) -> tuple[Store, pathlib.Path]:
    """建一个空的临时工作区（A3 与 E13 用）。"""
    root = tmp_path / "ws"
    st = Store(root)
    st.init()
    return st, root


def _agent_l(st: Store, ws: pathlib.Path):
    """L 的真实现（零模型；会话落点显式给，递送判据才可复现）。"""
    from agentflow.agent_l import AgentL

    return AgentL(st, workspace_root=ws, config={"session_root": str(ws), "sid": "t"})


# ============================================================ 面的读数


def _faces(*, store: Store | None = None,
           workspace_root: pathlib.Path | None = None) -> dict:
    """四个面（角色表 / 工具面 / 名册 / 提示词）这一档的读数。

    为什么把四类读数收进一个 dict：E12 与 E15 判的是同一组读数，两处各拼一遍会让
    "改了开关之后哪一格跟着走"这件事有两个答案。提示词那一格逐角色记，于是
    "某一个角色的提示词漏了隔绝"可以被单独点名，而不是只剩一个总数。
    """
    from agentflow.host import _Builder

    build = build_registry(store=store, workspace_root=workspace_root)
    reg = AS.builtin_registry()
    prompts: dict[str, str] = {}
    hidden: dict[str, str] = {}
    for role in ALL_ROLES:
        try:
            prompts[role] = AP.system_prompt(role, registry=build.registry)
        except LS.RoleHidden as exc:
            hidden[role] = str(exc)
    return {
        "roles": sorted(reg.roles()),
        "summonable": sorted(reg.summonable_roles()),
        "tool_roles": sorted(LS.visible_roles(TOOL_ROLES)),
        "formal_assembled": sorted(str(n) for n in build.registry.names()
                                   if str(n).startswith("formal.")),
        "l_tool_face": sorted(spec.name for spec in build.registry.for_role("L")),
        "roster": sorted(_Builder().status()),
        "hidden": hidden,
        "prompts": prompts,
        "profiles": AP.profiles_markdown(registry=build.registry),
    }


def _off_violations(faces: dict) -> list[str]:
    """关着时"完全看不见"的判据。返回违反项（空清单 = 隔绝成立）。

    刻意做成纯函数：E15 要把它读的那唯一一个判定入口钉成恒 False，再看它会不会红
    （判据本体替换成"恒过"之后仍然绿，说明它读的不是那个入口）。
    """
    bad: list[str] = []
    if "L" in faces["roles"]:
        bad.append(f"角色表里还有 L：{faces['roles']}")
    if "L" in faces["summonable"]:
        bad.append(f"可召唤名单里还有 L：{faces['summonable']}")
    if "L" in faces["tool_roles"]:
        bad.append(f"能持有工具的角色读数里还有 L：{faces['tool_roles']}")
    if faces["formal_assembled"]:
        bad.append(f"工具面还装配着 formal.*：{faces['formal_assembled']}")
    if faces["l_tool_face"]:
        bad.append(f"L 的工具面不是空的：{faces['l_tool_face']}")
    if "L" in faces["roster"]:
        bad.append(f"名册（接线态读数）里还有 L：{faces['roster']}")
    if "L" not in faces["hidden"]:
        bad.append("关着时 L 自己的提示词仍然渲染得出来（应受控拒绝，理由 lean_off）")
    for role, text in faces["prompts"].items():
        if role == "L":
            continue
        hits = len(ROLE_NAME.findall(text))
        if hits:
            bad.append(f"{role} 的提示词里出现了 {hits} 处 L 这个角色名")
        formal = text.count("formal.")
        if formal:
            bad.append(f"{role} 的提示词里出现了 {formal} 处 formal.")
    if ROLE_NAME.search(faces["profiles"]) or "L：" in faces["profiles"]:
        bad.append("画像文件（AGENT-PROFILES.md 的内容）里还有 L")
    return bad


def _on_violations(faces: dict) -> list[str]:
    """开着时"看得见、调得到"的判据。返回违反项（空清单 = 可见面完整）。"""
    bad: list[str] = []
    if "L" not in faces["roles"]:
        bad.append(f"角色表里没有 L：{faces['roles']}")
    if "L" not in faces["summonable"]:
        bad.append(f"可召唤名单里没有 L：{faces['summonable']}")
    if "L" not in faces["roster"]:
        bad.append(f"名册（接线态读数）里没有 L：{faces['roster']}")
    if "L" in faces["hidden"]:
        bad.append(f"开着时 L 自己的提示词被拒了：{faces['hidden'].get('L', '')[:120]}")
    missing = sorted(set(FORMAL_TOOLS) - set(faces["formal_assembled"]))
    if missing:
        bad.append(f"工具面没有装配 {missing}（装出来的：{faces['formal_assembled']}）")
    lacking = sorted(set(FORMAL_TOOLS) - set(faces["l_tool_face"]))
    if lacking:
        bad.append(f"L 的工具面上没有 {lacking}（拿到的是 {faces['l_tool_face']}）")
    text = faces["prompts"].get("L") or ""
    if not text.strip():
        bad.append("开着时 L 的提示词是空的")
    elif "formal." not in text:
        bad.append("开着时 L 的提示词里一行 formal.* 都没有（工具面没进提示词）")
    if not ROLE_NAME.search(faces["profiles"]):
        bad.append("开着时画像文件里没有 L")
    if not ROLE_NAME.search(faces["prompts"].get(S.CONDUCTOR_ROLE) or ""):
        bad.append("开着时主控的伙伴表里没有 L")
    return bad


def _snapshot(faces: dict) -> dict:
    """四个面的六格布尔读数（E14 三档逐格对比用它）。"""
    return {
        "registry_has_l": "L" in faces["roles"],
        "summonable_has_l": "L" in faces["summonable"],
        "formal_assembled": bool(faces["formal_assembled"]),
        "l_face_size": len(faces["l_tool_face"]),
        "roster_has_l": "L" in faces["roster"],
        "l_prompt_hidden": "L" in faces["hidden"],
        "prompt_l_total": sum(len(ROLE_NAME.findall(t)) for t in faces["prompts"].values()),
        "prompt_formal_total": sum(t.count("formal.") for t in faces["prompts"].values()),
        "profiles_has_l": "L：" in faces["profiles"],
    }


# ============================================================ A1 入边


def _edge_violations(edges: dict) -> list[str]:
    """B → L 是唯一入边的判据本体（纯函数，A1 与它的反真空共用）。"""
    bad: list[str] = []
    inbound = sorted(role for role, targets in edges.items() if "L" in (targets or ()))
    if inbound != ["B"]:
        bad.append(f"指向 L 的入边不是只有 B：{inbound}")
    for role in ALL_ROLES:
        if role == "B":
            continue
        if role not in edges:
            bad.append(f"{role} 不在边表里 ⇒ 上面那一轮遍历漏了一个角色")
            continue
        if "L" in (edges[role] or ()):
            bad.append(f"{role} 的出边里出现了 L（裁定：只有 B 可以派 L）")
    return bad


def _bad_inbound_edges() -> dict:
    """反真空用的坏表：多开一条 A → L。"""
    bad = {role: frozenset(targets) for role, targets in C.ALLOWED_EDGES.items()}
    bad["A"] = frozenset(set(bad.get("A") or ()) | {"L"})
    return bad


def test_a1_b_to_l_is_the_only_inbound_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    """A1：遍历边表，指向 L 的入边只有 B；L 可被召唤。

    改前红：改前的 `schema.ROLES` 是九个角色（A–H、V），`specs/` 里没有 `l.py`，
    也没有 `agent_l` / `leanscope` —— L 这个角色整条不存在。于是
    `_edge_violations()` 读到的 inbound 是空清单，`inbound != ["B"]` 当场红；
    下面那句 `assert "L" in edges["B"]` 也是红的（改前 `specs/b.py` 的
    `edges=('C', 'H', 'V')`）。

    反真空：判据函数在一张多开 A → L 的坏表上必须报出违反项，否则它在读一句恒真的话。
    """
    _lean_env(monkeypatch, True)
    edges = C.ALLOWED_EDGES
    total = sum(len(targets) for targets in edges.values())
    assert total >= 30, f"边表几乎是空的（{total} 条）⇒ 下面的断言会变成真空"

    assert _edge_violations(edges) == [], "\n".join(_edge_violations(edges))

    # 逐条写出来（读者不看判据函数也知道裁定说了什么）
    assert "L" in edges["B"], f"B 的出边里没有 L：{sorted(edges['B'])}"
    for role in ALL_ROLES:
        if role == "B":
            continue
        assert role in edges, f"{role} 不在边表里 ⇒ 上面那一轮遍历漏了它"
        assert "L" not in edges[role], f"{role} 的出边里出现了 L：{sorted(edges[role])}"
    assert "L" not in C.NON_SUMMONABLE, f"L 还在不可召唤名单里：{sorted(C.NON_SUMMONABLE)}"
    assert "L" in AS.builtin_registry().summonable_roles(), (
        f"L 不在可召唤名单里：{AS.builtin_registry().summonable_roles()}")

    # 反真空：坏表上判据必须报出 A → L
    bad = _edge_violations(_bad_inbound_edges())
    assert bad, "A → L 的坏表上判据函数也全绿 ⇒ A1 是真空的"
    assert any("A" in item for item in bad), bad


# ============================================================ A2 出边


def _out_violations(edges: dict) -> list[str]:
    """L → C 是唯一出边的判据本体（纯函数）。"""
    bad: list[str] = []
    allowed = frozenset(edges.get("L") or ())
    if allowed != frozenset({"C"}):
        bad.append(f"L 的出边不是恰好一条 C：{sorted(allowed)}")
    return bad


def test_a2_l_to_c_is_the_only_outbound_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    """A2：L 的出边恰好一条 C；派任何别的角色一律 forbidden_edge。

    改前红：改前的 `ALLOWED_EDGES` 里没有 "L" 这个键（L 不是角色），
    `edges["L"]` 当场 KeyError。今天这一格是 `frozenset({'C'})`。

    反真空：把 B 加进 L 的出边（编一张坏表）⇒ 判据本体必须报出来。
    """
    _lean_env(monkeypatch, True)
    edges = C.ALLOWED_EDGES
    assert "L" in edges, f"边表里没有 L：{sorted(edges)}"
    assert edges["L"] == frozenset({"C"}), f"L 的出边：{sorted(edges['L'])}"
    assert _out_violations(edges) == []

    pol = P.Policy()
    assert P.check(pol, P.Decision(frm="L", to="C", action="", depth=2)) is None, (
        "L → C 这条唯一出边在闸门上不通")
    for target in ALL_ROLES:
        if target == "C":
            continue
        got = P.check(pol, P.Decision(frm="L", to=target, action="", depth=2))
        assert got is not None, f"L → {target} 居然通了（裁定：L 只派 C）"
        assert got.reason == "forbidden_edge", (target, got.reason, got.detail)

    # 反真空：坏表（L 还能派 B）上判据本体必须报出来
    bad_table = {role: frozenset(targets) for role, targets in edges.items()}
    bad_table["L"] = frozenset({"C", "B"})
    assert _out_violations(bad_table), "L 能派 B 的坏表上判据也全绿 ⇒ A2 是真空的"


# ============================================================ A3 闸门实测


def test_a3_the_conductor_refuses_everyone_but_b(tmp_path: pathlib.Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """A3：Conductor 层实测 —— M 与其余每个角色派 L 都是 refused / forbidden_edge。

    这一条判的是行为面，不是边表：只改边表而闸门照样放行，是"声明改对了、执行没改"
    的形态（`tests/test_the_conductor_does_not_directly_control_bfv.py` 逐字论证过
    这两层为什么必须各判一次）。

    改前红：改前 L 不是角色，正控那一半（B → L 被受理）拿到的是 unknown_role；
    而负控在"根本没有这个角色"上恒真 —— 真空的绿不算绿。

    零 Lean：送进去的源码没有具名定理 / 引理，动作在写盘与起检查器之前就受控拒绝
    （`param_error`），所以这一条一次子进程都不起。
    """
    _lean_env(monkeypatch, True)
    st, ws = _workspace(tmp_path)
    import agentflow.conductor as CO

    agent = _agent_l(st, ws)
    cond = CO.Conductor(st, registry={"L": ("object", agent)})
    params = {"claim": CLAIM, "source": NO_THEOREM}

    refusals = []
    for frm in ALL_ROLES:
        if frm == "B":
            continue
        res = cond.summon("L", "formalize", params, by=frm, input_key=f"a3-{frm}")
        assert res.status == "done", (frm, res.status, res.detail)
        assert res.outcome == "refused", (frm, res.outcome, res.detail)
        assert res.refusal_reason == "forbidden_edge", (frm, res.refusal_reason, res.detail)
        refusals.append(frm)

    # 正控：B 这一条入口在闸门上是通的（同一张表、同一份参数）
    ok = cond.summon("L", "formalize", params, by="B", input_key="a3-B")
    assert ok.refusal_reason is None, (ok.outcome, ok.refusal_reason, ok.detail)
    assert ok.outcome != "refused", (ok.outcome, ok.detail)

    # 拒绝也是一个结果：每一行都进了台账（不是"静默不派"）
    rows = [dict(row) for row in st.rows("tasks")]
    l_rows = [row for row in rows if str(row.get("role")) == "L"]
    assert len(l_rows) == len(ALL_ROLES), len(l_rows)
    called_by = {str(row.get("called_by")) for row in l_rows}
    assert called_by == set(ALL_ROLES), called_by
    refused_by = {str(row.get("called_by")) for row in l_rows
                  if str(row.get("outcome")) == "refused"}
    assert refused_by == set(refusals), refused_by
    assert all(str(row.get("refusal_reason")) == "forbidden_edge"
               for row in l_rows if str(row.get("outcome")) == "refused")

    # 拒绝要可行动：主控的拒信必须点名"改派 B"（否则它只会重试同一条边）
    m_row = next(row for row in l_rows if str(row.get("called_by")) == S.CONDUCTOR_ROLE)
    assert "B" in str(m_row.get("detail") or ""), m_row.get("detail")


# ============================================================ E12 关


def test_e12_when_off_every_face_has_zero_l_and_zero_formal(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """E12：开关关 ⇒ 角色表 / 工具面 / 名册 / 提示词里 L = 0、formal. = 0。

    改前红：改前树里没有 L，也没有开关这一层，所以纯"关"的那一半在空集上是真空绿。
    本用例因此先把同一个读数在开着那一档验成正控（`L` 与 `formal.*` 都必须看得见），
    再把开关关掉 —— 改前那一半当场红。

    反真空还有第二层：十个角色的提示词加起来必须远大于 0 字（否则"0 处 L"可能只是
    "提示词是空的"）。
    """
    _lean_env(monkeypatch, True)
    on = _faces()
    assert "L" in on["roles"], on["roles"]
    assert on["formal_assembled"], on["formal_assembled"]
    assert ROLE_NAME.search(on["prompts"].get(S.CONDUCTOR_ROLE) or ""), (
        "开着时主控的伙伴表里没有 L ⇒ 下面那个计数器的分辨力没被证明")

    _lean_env(monkeypatch, False)
    off = _faces()
    bad = _off_violations(off)
    assert bad == [], "关着时仍然没有完全隔绝：\n  - " + "\n  - ".join(bad)

    # 逐条读出来（读者不看判据函数也知道关着时是什么样）
    assert "L" not in off["roles"], off["roles"]
    assert "L" not in off["summonable"], off["summonable"]
    assert "L" not in off["tool_roles"], off["tool_roles"]
    assert off["formal_assembled"] == [], off["formal_assembled"]
    assert off["l_tool_face"] == [], off["l_tool_face"]
    assert "L" not in off["roster"], off["roster"]
    assert "L" in off["hidden"], sorted(off["hidden"])
    assert "lean_off" in off["hidden"]["L"], off["hidden"]["L"]

    counts = {role: len(ROLE_NAME.findall(text))
              for role, text in off["prompts"].items() if role != "L"}
    assert set(counts.values()) == {0}, counts
    formal_counts = {role: text.count("formal.")
                     for role, text in off["prompts"].items() if role != "L"}
    assert set(formal_counts.values()) == {0}, formal_counts
    assert sum(len(text) for text in off["prompts"].values()) > 20000, (
        "十个角色的提示词加起来太短 ⇒ 「0 处 L」可能是真空的")
    assert "L：" not in off["profiles"], "画像文件里还有 L 那一行"


# ============================================================ E13 开


def test_e13_when_on_all_four_faces_show_l_and_the_tools_are_callable(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """E13：开关开 ⇒ 四个面都看得见 L，且 `formal.*` 真的调得到（不是只在清单里）。

    改前红：改前没有开关这一层，开与关是同一档、且 L 根本不存在 ⇒ 红。

    反真空：工具那一格不只是"名字在工具面上"，还真的经 `ToolRegistry.call` 走了一次
    handler（送空源码 ⇒ 受控 `param_error`）。只在清单里、调不动的工具也叫"可见"的话，
    这条判据就只是在读一个字符串。
    """
    _lean_env(monkeypatch, True)
    st, ws = _workspace(tmp_path)
    faces = _faces(store=st, workspace_root=ws)
    bad = _on_violations(faces)
    assert bad == [], "开着时可见面不完整：\n  - " + "\n  - ".join(bad)

    assert set(FORMAL_TOOLS) <= set(faces["l_tool_face"]), faces["l_tool_face"]
    assert "Lean 形式化" in (faces["prompts"].get("L") or ""), "L 的提示词里没有它的职责句"

    # 可用：三件工具都调得到（handler 真跑到了，结论是受控三态）。
    #
    # 这一格刻意不要求检查器真的跑起来：本文件的 `_lean_env` 只动开关、不给
    # `AGENTFLOW_LEAN_BIN`（那是"真跑检查器"那一档的事，见
    # `tests/test_l_faithfulness_and_report_matrix.py`）。所以这里的读数是
    # "工具在面上、经 ToolRegistry.call 走得到 handler、返回受控理由" ——
    # 它要和"工具不在这个角色的可调用面里"（一句话就被拒，见文件三的 F16）分得开。
    reg = build_registry(store=st, workspace_root=ws).registry
    formalize = reg.call("formal.formalize", role="L", claim=CLAIM, source="")
    assert formalize.ok is True, formalize.error
    assert dict(formalize.data or {}).get("reason") == "param_error", formalize.data
    record = reg.call("formal.record", role="L", statement_id="999999",
                      code_path="code/formal/probe.lean")
    assert record.ok is True, record.error
    assert dict(record.data or {}).get("reason") == "statement_not_found", record.data
    check = reg.call("formal.check_formal", role="L", claim=CLAIM, source="")
    assert check.ok is True, check.error
    check_data = dict(check.data or {})
    assert check_data.get("status") == "unknown", check_data
    assert str(check_data.get("reason") or "").strip(), check_data
    assert str(check_data.get("detail") or "").strip(), check_data

    # 按名取 L 的入口读得出职责（受控拒绝那一档反过来看：开着时不该被拒）
    res = CT.conductor_role_spec(None, "L")
    assert res.ok is True, (res.ok, res.error)
    assert str((res.data or {}).get("duty") or "").startswith("Lean 形式化"), res.data


# ============================================================ E14 同进程三档


def test_e14_the_same_process_follows_off_on_off(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """E14：同一进程里 关 → 开 → 再关，四个面的读数跟着走，且不缓存旧值。

    改前红：改前没有判定入口（`leanscope`），三档读数完全相同 ⇒ 第一条"第二次关回来
    必须与第一次逐格相同、而开着那一档必须不同"红。

    为什么先断一次"没有 reload 也必须立刻说开"：判定入口自己缓存旧值这件事，症状是
    "改了开关不生效"，而它在读数上与"这一档本来就这样"完全一样。提示词那一层有
    lru_cache（同一趟里前缀稳定），它的刷新口是 `reset_toolchain_readings()` —— 那一步
    单独调用，不算进"判定入口有没有缓存"这一条。
    """
    _lean_env(monkeypatch, True)

    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    assert LS.lean_on() is False, "改 env 之后判定入口还停在旧值（缓存了）"
    _reset_readings()
    off_first = _snapshot(_faces())

    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    assert LS.lean_on() is True, "改 env 之后判定入口还停在旧值（缓存了）"
    _reset_readings()
    on = _snapshot(_faces())

    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    assert LS.lean_on() is False, "改 env 之后判定入口还停在旧值（缓存了）"
    _reset_readings()
    off_again = _snapshot(_faces())

    print("\n[同进程切换] 关着 =", off_first)
    print("[同进程切换] 开着 =", on)
    print("[同进程切换] 再关 =", off_again)

    assert off_first == off_again, (
        "关 → 开 → 关 之后读数没有回到第一次那一档（缓存停在中间态）："
        f"{off_first} vs {off_again}")
    assert on != off_first, "换到开着那一档之后读数一个都没变（开关没接上）"
    # 逐项：关着那两档是"不存在"，开着那一档是"存在且可用"
    assert off_first["registry_has_l"] is False and on["registry_has_l"] is True
    assert off_first["summonable_has_l"] is False and on["summonable_has_l"] is True
    assert off_first["formal_assembled"] is False and on["formal_assembled"] is True
    assert off_first["l_face_size"] == 0 and on["l_face_size"] >= len(FORMAL_TOOLS)
    assert off_first["roster_has_l"] is False and on["roster_has_l"] is True
    assert off_first["l_prompt_hidden"] is True and on["l_prompt_hidden"] is False
    assert off_first["prompt_l_total"] == 0 and on["prompt_l_total"] > 0
    assert off_first["prompt_formal_total"] == 0 and on["prompt_formal_total"] > 0
    assert off_first["profiles_has_l"] is False and on["profiles_has_l"] is True


# ============================================================ E15 反真空


def test_e15_never_hiding_turns_e12_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """E15：把唯一判定入口 `is_hidden` 钉成恒 False ⇒ E12 的判据函数必红。

    这一条守的是 E12 到底在判什么：它读的是同一个判定入口（`leanscope.is_hidden`），
    所以把入口钉成"永不隔绝"之后，角色表 / 名册 / 提示词那几格必须当场把话说出来。
    红的方式也有要求：违反项要分别点到角色表、名册、提示词 —— 只红一条说明判据函数
    只读了其中一格。

    改前红：改前没有 `leanscope`（连钉的对象都不存在）⇒ ImportError / AttributeError 红。
    """
    _lean_env(monkeypatch, False)
    faces = _faces()
    assert _off_violations(faces) == [], "正控没成立：关着时本来就没隔绝？"

    monkeypatch.setattr(LS, "is_hidden", lambda role: False)
    patched = _faces()
    bad = _off_violations(patched)
    assert bad, ("把 is_hidden 钉成恒 False 之后 E12 的判据仍然全绿 ⇒ 它读的不是那个入口")
    blob = "\n".join(bad)
    print("\n[反真空] 恒 False 时报出来的违反项共", len(bad), "条：", bad[:8])
    for word in ("角色表", "名册", "提示词"):
        assert word in blob, f"违反项里没有点到{word}（判据只读了其中一格）：{bad}"
