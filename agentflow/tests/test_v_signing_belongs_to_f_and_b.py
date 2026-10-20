# -*- coding: utf-8 -*-
"""判据：V 的签字只有两个入口 —— **F 产出时签**、**B 入库文献侧内容时签**（2026-10-20 业主裁定）。

## 裁定逐字（业主）

> "F 产出的证明带 V 签字后不该反复要求签字，所以**最早版本只有 F 能派 V**；B 负责定理及证明
> 入库时可让 V 审核签字，这是对**文献侧引入的内容**需要看的，因为我们自己经 F 产出的证明
> **天生带 V 签字**。"

所以四件事要同时成立，缺一件模型就会照着错的那一句派活：

- **边表**（①）：`D.edges` 与 `capabilities.ALLOWED_EDGES["D"]` 都**不含 V**，而且 V 只有
  **两个入口**：`F`（自产证明时签）与 `B`（文献侧内容入库时签）。**`M→V` 已撤**（2026-10-20
  业主裁定「派 V 只有 F 与 B 两个入口；M 不再直连 V」），边总数 **33 → 32**。
  `M→B→V` 与 `M→D→F→V` 两条间接路都还在 ⇒ 撤这条边不会让 V 变成孤儿（判据里有反真空）。
  此前"树根可派任何人"那一句（2026-10-18 的裁定）已被本裁定取代 —— 派 V 走查证明这件事
  由 F 在交出证明时办好，M 不再直连 V；见 ②。- **M 的文字面**（②）：`specs/m.py` 的 policy 里不再有"派 V / `verify_proof`"这一类**义务句**。
  原来那两条（`reviewed_proof_rows` 记 0；`history` 里出现 `statement_id`）都改成"派 D 去办"。
- **D 的文字面**（③）：D 的义务是"确认 F 交回的证明带 V 的签字；没有就让 F 去补签"，
  并明说"你不要自己派 V"。
- **B 的文字面**（④）：B 只对**文献侧引入**的定理/证明要求 V 签字；F 产的证明不要重复要求签。
- **不许反复签**（⑤）：`verifications` 里最近一签「成立」且 `proof_sha256` 与现行正文相符的
  命题，D 与 M 的清单都**不再要求它**。这一条落在盘上那两个读数上，不落在措辞上：
  D 那一侧是 `verifications.proof_review_gap`（"带没带签"），M 那一侧是
  `verifications.unverified_statement_refs`（收工门「攻」那一格读它）。两边各配负控 ——
  改一个字（sha 不再相符）、换一个没有台账的根，清单都必须重新要求它。

## 为什么这些判据值得存在

`specs/*.py` 的 policy 是**逐字进提示词**的东西：模型按它派活。改错一句不会报错、不会崩、
五条既有判据（spec↔prompt 对账、两层一致、清单登记）全都照样绿 —— 它只会在真机上多派一次 V，
或者少派一次。所以这里既判"边表那种读得出来的东西"（①），也判"那两句话在不在 + 哪一格不对"
（②③④，报错时逐条打印读到的原文），还判"已签的还会不会被再要一签"（⑤，用真读数）。

## 负控为什么必须逐条注入

**每一条正控都配一条"把它改回去 ⇒ 必须红"**：① 把 `V` 塞回 D 的出边；② 把那两条义务句
各自加回 M；③ 把 D 那句里的"让 F 去补签"换成"让 V 去补签"、或整句删掉；④ 把 B 那一条删掉；
⑤ 改一个字 / 换一个根。没有这些负控，本文件就只是把裁定抄了一遍 —— 而抄一遍不会咬人。
"""
from __future__ import annotations

import dataclasses
import re

from agentflow import capabilities as C
from agentflow import schema as S
from agentflow.specs import builtin_specs
from agentflow.verifications import (
    parse_verdict,
    proof_review_gap,
    record_verification,
    unverified_statement_refs,
)

#: 边总数的现读：D 不派 V 那一批之后是 33；2026-10-20 同一裁定把 `M→V` 也撤了
#: （"派 V 只有 F 与 B 两个入口"）⇒ **32**。
EXPECTED_EDGE_TOTAL = 32

#: V 的两个入口（2026-10-20 业主裁定逐字：「派 V 只有 F（自产证明）与 B（文献侧内容）
#: 两个入口；M 不再直连 V」）。**F 与 B 两条一条都不许少**，而 `M` 必须**不在**里面。
V_ENTRANCES = frozenset({"F", "B"})

#: M 的出边（反真空：撤 V 之后这七条一条都不许少）。
M_EDGES = frozenset({"A", "B", "C", "D", "E", "G", "H"})

#: D 的出边（反真空：这五条一条都不许少 —— 那条裁定只否掉了 `V`，没否掉别的）。
D_EDGES = frozenset({"A", "B", "C", "E", "F"})


# ============================================================ ① 边表：D 不派 V、M 也不直连 V

def _edge_problems(d_edges, table, m_edges=None) -> list[str]:
    """两边（D 与 M）的出边与边总数的全部问题（空列表 = 全对）。

    五个分量分开报，因为它们坏起来是五种不同的事：声明层被人补了 `V`、派生表与声明
    不同步、总数变了（有边被顺手加/删）、某一边的**反真空**没成立（"不含 V"可以用
    "干脆一条边都没有"来满足）。`m_edges` 给了就一并核 M 的声明层（不给 ⇒ 只核
    派生层的 `table["M"]`）。
    """
    out: list[str] = []
    declared = tuple(d_edges)
    if "V" in set(declared):
        out.append(f"D 的声明层出边含 V：{declared} —— 2026-10-20 业主裁定：D 不派 V"
                   "（V 的签字由 F 在交出证明时办好，文献侧由 B 在入库时办好）")
    derived = set(table.get("D", frozenset()))
    if "V" in derived:
        out.append(f"派生层 ALLOWED_EDGES['D'] 含 V：{sorted(derived)}")
    total = sum(len(v) for v in table.values())
    if total != EXPECTED_EDGE_TOTAL:
        out.append(f"边总数是 {total}，不是 {EXPECTED_EDGE_TOTAL} —— "
                   "2026-10-20 的裁定：D→V 没有加，`M→V` 撤掉一条（33 → 32）")
    lost = sorted(D_EDGES - derived)
    if lost:
        out.append(f"D 少了这些边 {lost} —— 反真空：其余五条（A/B/C/E/F）一条都不许少")
    # ---- M 那一侧（同一条裁定把 `M→V` 也撤了：派 V 只有 F 与 B 两个入口）----
    if m_edges is not None and "V" in set(m_edges):
        out.append(f"M 的声明层出边含 V：{tuple(m_edges)} —— "
                   "2026-10-20 业主裁定：M 不再直连 V（派 V 只有 F 与 B 两个入口）")
    m_derived = set(table.get("M", frozenset()))
    if "V" in m_derived:
        out.append(f"派生层 ALLOWED_EDGES['M'] 含 V：{sorted(m_derived)}")
    m_lost = sorted(M_EDGES - m_derived)
    if m_lost:
        out.append(f"M 少了这些边 {m_lost} —— 反真空：其余七条（A/B/C/D/E/G/H）一条都不许少")
    return out


def test_d_has_no_edge_to_v_and_the_total_is_unchanged() -> None:
    """① 正控：D 的出边里没有 `V`、M 的出边里也没有 `V`，边总数 32，两边的其余边一条没少。"""
    specs = builtin_specs()
    problems = _edge_problems(specs["D"].edges, C.ALLOWED_EDGES, specs["M"].edges)
    assert problems == [], ("D/M 的出边与 2026-10-20 的裁定不一致：\n  - "
                            + "\n  - ".join(problems))
    # 反真空（正控的另一半）：V 的**两个入口**（F 与 B）都还在，否则上面那条"不含 V"
    # 可能只是"整个 V 都没人够得着"。
    assert set(V_ENTRANCES) == {r for r, tos in C.ALLOWED_EDGES.items() if "V" in tos}, (
        "V 的入口集合变了（2026-10-20 裁定：只有 F 与 B 两个入口）",
        sorted(r for r, t in C.ALLOWED_EDGES.items() if "V" in t))
    for holder in sorted(V_ENTRANCES):
        assert "V" in C.ALLOWED_EDGES[holder], f"{holder}→V 不见了（V 少了一个入口）"


def test_negative_control_putting_v_back_on_d_is_caught() -> None:
    """① 负控：把 `V` 塞回 D 的出边（声明层 / 派生层各注入一次）⇒ 判据必须红。"""
    spec = builtin_specs()["D"]
    m_spec = builtin_specs()["M"]
    # (a) 声明层：有人又在 `specs/d.py` 里补了 'V'
    drifted = dataclasses.replace(spec, edges=(*spec.edges, "V"))
    got = _edge_problems(drifted.edges, C.ALLOWED_EDGES, m_spec.edges)
    assert any("声明层" in p for p in got), got
    # (b) 派生层：有人在运行期改了那张表（不碰源码也能造出"D 能派 V"）
    tampered = {role: frozenset(tos) for role, tos in C.ALLOWED_EDGES.items()}
    tampered["D"] = frozenset(D_EDGES | {"V"})
    got = _edge_problems(spec.edges, tampered, m_spec.edges)
    assert any("派生层" in p for p in got), got
    # (c) 总数也得咬人：多一条边（D→V 那种形态）必须被这一格点名
    assert any("边总数" in p for p in got), got
    # 收尾（负控的负控）：真身没被动过 ⇒ 同一条判据在原始输入上仍然成立
    assert _edge_problems(spec.edges, C.ALLOWED_EDGES, m_spec.edges) == []


def test_negative_control_putting_v_back_on_m_is_caught() -> None:
    """① 负控（2026-10-20 那一半）：把 `V` 加回 M（声明层 / 派生层各一次）⇒ 判据必须红。

    没有这一条，"M 不含 V"就只能靠人记得 —— 而它是这一天业主裁定的**核心那一格**：
    把 V 加回去等于让 M 又能直连 V，而 V 的两个入口（F / B）不再独占。
    """
    m_spec = builtin_specs()["M"]
    d_spec = builtin_specs()["D"]
    # (a) 声明层：有人在 `specs/m.py` 里又把 'V' 补回 `edges`
    drifted = dataclasses.replace(m_spec, edges=(*m_spec.edges, "V"))
    got = _edge_problems(d_spec.edges, C.ALLOWED_EDGES, drifted.edges)
    assert any("M 的声明层" in p for p in got), got
    # (b) 派生层：运行期改表（不碰源码也能造出"M 能派 V"）
    tampered = {role: frozenset(tos) for role, tos in C.ALLOWED_EDGES.items()}
    tampered["M"] = frozenset(M_EDGES | {"V"})
    got = _edge_problems(d_spec.edges, tampered, m_spec.edges)
    assert any("派生层 ALLOWED_EDGES['M']" in p for p in got), got
    # (c) 总数那一格：把 V 加回 M ⇒ 33，判据必须点出"不是 32"
    assert any("边总数" in p for p in got), got
    # 收尾（负控的负控）：真身没被动过 ⇒ 仍然全对
    assert _edge_problems(d_spec.edges, C.ALLOWED_EDGES, m_spec.edges) == []


#: 端到端那一条用的替身缝：这一组判据不碰模型（只碰边表闸门与台账）。
class _NoModel:
    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def complete(self, prompt, *, scope="", system=None, **kw):  # pragma: no cover
        raise AssertionError("这一条判据不许调到模型")


def test_m_dispatching_v_end_to_end_is_forbidden(tmp_path) -> None:
    """① 判据②（端到端）：M 真的去派 V ⇒ `conductor.summon` 判 `forbidden_edge`，一行活都没跑。

    为什么不能只断言 `policy.check`：那是"策略函数怎么判"，而这一条要守的是
    "**M 的派活这条路**走不通" —— 中间还隔着 `AgentLoop._do_summon` 的形状解码、
    `Conductor.summon` 的边闸门、以及台账那一行。改前（2026-10-18 ~ 2026-10-20）
    这整条路是通的；撤边之后必须在**最后那一层**也拒，而不只是在边表里看不见。
    顺带把"被拒的那一行也带父的绝对编号"钉住（拒绝 ≠ 孤儿）。
    """
    import pathlib

    from agentflow.agent_loop import AgentLoop
    from agentflow.conductor import Conductor, LocalBackend
    from agentflow.llmseam import LlmSeam
    from agentflow.store import Store
    from agentflow.tools import build_registry

    ws = pathlib.Path(tmp_path) / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    top = cond.open_top_level_run("M", "顶层这一趟")
    loop = AgentLoop(role="M", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="M", session_root=ws, gateway=_NoModel(),
                                  price=(0.0, 0.0), sid="s-v-entrance"),
                     store=st, sid="s-v-entrance", max_steps=2)
    loop.my_task_id = top
    out = loop._do_summon({"role": "V", "task": "走查 stmt:000000 那一条证明"})
    assert out.get("ok") is False, out
    assert str(out.get("refusal_reason") or "") == "forbidden_edge", (
        "M 真的把 V 派出去了（或拒成了别的理由）—— 2026-10-20 的裁定要求 forbidden_edge", out)
    assert "V" in str(out.get("detail") or "") or "只能召唤" in str(out.get("detail") or ""), out
    # 台账那一行：被拒的尝试也落行，且父是顶趟的绝对编号（不是 None）
    rows = [r for r in st.rows("tasks") if str(r.get("role")) == "V"]
    assert len(rows) == 1, rows
    assert str(rows[0].get("outcome")) == "refused", rows[0]
    assert str(rows[0].get("refusal_reason")) == "forbidden_edge", rows[0]
    assert str(rows[0].get("parent_task_id") or "") == top, (
        "被拒的那一行没有父（孤儿形态）—— 拒绝也是派活，父必须是顶趟的绝对编号", rows[0])
    assert str(rows[0].get("called_by")) == "M", rows[0]


# ============================================================ ② M 不再有"派 V"的义务句

#: 义务词：一句话里出现这些词，才算它"在要求谁去做"（史实说明与注释不在此列）。
_OBLIGATION = re.compile(r"(必须|应当|需要|要|不许|不要|派)")

#: "派 V" / "派 `V`"（含反引号那种写法）。
_DISPATCH_V = re.compile(r"派\s*`?V`?")


def _prove_walk_obligations(policy) -> list[str]:
    """M 的 policy 里"派 V 走查证明"这一类**义务句**（空列表 = 一句都没有）。

    两个分量合成一条判据（业主给的口径："用'必须/要/派'这类义务词 + `verify_proof`
    同时命中才算义务"）：

    - 点名 `verify_proof` —— 那是 V 的主动作，写在 M 的义务句里就等于教它去派 V；
    - 义务词 + "派 V" —— 同一个意思的另一种写法（不必提动作名）。

    两者都不看注释：传进来的只有 `policy` 这个元组（注释在源码里，不在声明里），
    所以"注释里提到过这件事"不会被误判成义务句 —— 这也是这条判据用**声明**而不是
    用文件文本的原因（`specs/m.py` 里那些 2026-10-20 的裁定注释必须可以写）。
    """
    out: list[str] = []
    for i, item in enumerate(policy):
        text = str(item)
        reasons: list[str] = []
        if "verify_proof" in text:
            reasons.append("点名了 `verify_proof`（V 的主动作）")
        if _OBLIGATION.search(text) and _DISPATCH_V.search(text):
            reasons.append("有义务词、且写着「派 V」")
        if reasons:
            out.append(f"policy[{i}]：" + "；".join(reasons) + f"\n      原文：{text[:160]}")
    return out


def test_m_has_no_obligation_to_dispatch_v() -> None:
    """② 正控：M 的 policy 里没有"派 V / `verify_proof`"的义务句，且那两条义务已转交 D。"""
    policy = builtin_specs()["M"].brief.policy
    bad = _prove_walk_obligations(policy)
    assert bad == [], ("M 的 policy 里还有『派 V 走查』的义务句（模型会照着派，而 V 的签字只由 "
                       "F / B 发起）：\n  - " + "\n  - ".join(bad))
    # 反真空：两句**转交**必须真的写在那里 —— 否则"没有义务句"可以用"整条删掉、什么也不说"
    # 来满足，而那等于把这条义务从台账上抹掉（业主说的是"挪到 D"，不是"取消"）。
    text = "\n".join(str(s) for s in policy)
    for marker in ("要有人走查就派 D 去办", "就当场交给 D 去核签"):
        assert marker in text, (
            f"M 的 policy 里读不到转交后的那句「{marker}」⇒ 这条义务没有落点"
            "（删掉≠转交：D 那边接不到，就没有人办）")


def test_negative_control_the_removed_obligations_are_caught() -> None:
    """② 负控：把撤掉的两句各自加回 M ⇒ 判据必须红（每条都要单独咬得住）。"""
    policy = builtin_specs()["M"].brief.policy
    removed = (
        # 改前 `specs/m.py` 里的第 21 条（`reviewed_proof_rows` 记 0 那一格）
        "**要 V 走查就直接派 V**：正文或 `statements` 里存在**证明级断言**（`proof_review` / "
        "`proof`）而 `reviewed_proof_rows` 记 0 时，要么派 `V` 走查（`verify.verify_proof`，"
        "逐条签名落 `verifications`），要么在验收表那一行写清为什么没有 V 的签名。",
        # 改前 `specs/m.py` 里的第 22 条（`history` 里的 `statement_id` 那一格）
        "**「攻」里出现 `statement_id` 就当场派 V 去走查那一条**：看到它就在同一轮里派 "
        "`V.verify_proof(statement_id=<那个命题号>)`，不要等收工再想起来。",
        # 只有"派 V"、没有动作名的形态（判据不能只认 `verify_proof` 一个词）
        "缺签的活必须派 V 去做。",
    )
    for extra in removed:
        got = _prove_walk_obligations((*policy, extra))
        assert got, f"这句加回 M 之后判据居然绿了：{extra!r}"
    # 收尾（负控的负控）：原样的 policy 必须重新成立
    assert _prove_walk_obligations(policy) == []


# ============================================================ ③ D 的义务：核签 + 让 F 补签

def _d_signing_problems(policy) -> list[str]:
    """D 的 policy 里"确认带签 / 让 F 补签 / 不自己派 V"这三件的问题（空列表 = 全对）。"""
    text = "\n".join(str(s) for s in policy)
    out: list[str] = []
    for needle, why in (
        ("带 V 的签字", "D 的义务是**确认 F 交回的证明带 V 的签字** —— 这句话不在了，D 就不知道要核什么"),
        ("让 F 去补签", "缺签的处置必须是**让 F 去补签**（F 才派得动 V；D 自己没有到 V 的边）"),
        ("不要自己派 V", "必须明说**你不要自己派 V** —— 不说，D 会照着'补签'两个字自己去派"),
    ):
        if needle not in text:
            out.append(f"缺「{needle}」：{why}")
    if "派 V 去走查" in text or "V 由 F 派去走查" in text:
        out.append("D 的 policy 还把「派 V 去走查」写成自己的动作（2026-10-20 之前的口径）")
    return out


def test_d_must_confirm_the_signature_and_send_f_back() -> None:
    """③ 正控：D 的 policy 写明"核签 → 让 F 补签 → 不自己派 V"，且"签不了让 B 降档"。"""
    policy = builtin_specs()["D"].brief.policy
    bad = _d_signing_problems(policy)
    assert bad == [], "D 的那句话与 2026-10-20 的裁定不一致：\n  - " + "\n  - ".join(bad)
    text = "\n".join(str(s) for s in policy)
    assert "让 B 如实降档" in text, (
        "签不了时的出口必须写出来（降档是安全方向；不写，D 会自己去补签或把档位写高）："
        + text[:200])


def test_negative_control_d_sentence_is_caught_when_it_regresses() -> None:
    """③ 负控：把"让 F 去补签"换成"让 V 去补签"、或把那一句删掉 ⇒ 判据必须红。"""
    policy = builtin_specs()["D"].brief.policy
    # (a) 改回旧口径：D 自己去派 V
    regressed = tuple(str(s).replace("让 F 去补签", "让 V 去补签") for s in policy)
    problems = _d_signing_problems(regressed)
    assert any("让 F 去补签" in p for p in problems), problems
    # (b) 整句删掉：义务消失（"没有义务"不等于"义务还在"）
    dropped = tuple(s for s in policy if "带 V 的签字" not in str(s))
    assert dropped != tuple(policy), "夹具前提：那一句里含「带 V 的签字」"
    assert _d_signing_problems(dropped) != []
    # 收尾（负控的负控）
    assert _d_signing_problems(policy) == []


# ============================================================ ④ B：只对文献侧要求签字

def _b_literature_problems(policy) -> list[str]:
    """B 的 policy 里"文献侧引入才要签 / F 产的不重复要求"这条的问题（空 = 全对）。"""
    text = "\n".join(str(s) for s in policy)
    out: list[str] = []
    for needle, why in (
        ("文献侧引入", "B 只在**文献侧引入**的定理/证明上要求签字 —— 条件不写清，B 会对我们自己的证明也要求签"),
        ("派 V 审核签字", "动作要写出来（B 的 `edges` 里有 V，这是它唯一该用那条边的地方）"),
        ("不要重复要求签", "F 产的证明天生带 V 签字 ⇒ 必须明说不要重复要求，否则同一条证明会被反复送审"),
    ):
        if needle not in text:
            out.append(f"缺「{needle}」：{why}")
    return out


def test_b_asks_v_only_for_the_literature_side() -> None:
    """④ 正控：B 的 policy 有"文献侧引入 ⇒ 派 V 审核签字；F 产的不要重复要求签"。"""
    policy = builtin_specs()["B"].brief.policy
    bad = _b_literature_problems(policy)
    assert bad == [], "B 的那一条与 2026-10-20 的裁定不一致：\n  - " + "\n  - ".join(bad)


def test_negative_control_b_item_is_caught_when_dropped() -> None:
    """④ 负控：把 B 那一条删掉 ⇒ 判据必须红（删掉不等于"这条规则不需要写"）。"""
    policy = builtin_specs()["B"].brief.policy
    dropped = tuple(s for s in policy if "文献侧引入" not in str(s))
    assert dropped != tuple(policy), "夹具前提：B 的 policy 里真有一条写着「文献侧引入」"
    assert _b_literature_problems(dropped) != []
    assert _b_literature_problems(policy) == []


# ============================================================ ⑤ 已签过的不许再要求签

#: 这一趟要签的那份证明（逐行写，方便"改一个字"造负控）。
PROOF_TEXT = ("1. 由定义直接得到 c(G) ≤ 1。\n"
              "2. 代入化简即得。\n")
#: 命题号从 `schema` 取（宽度一改，夹具跟着改 —— 不写死四位/六位）。
SID = S.format_id(7)
#: `statements` 那一行的形态（`proof_review` 档要的正是 `proof_text` + 那一签）。
STATEMENT_ROW = {"statement_id": SID, "proof_text": PROOF_TEXT, "evidence_kind": "proof_review"}


def _sign(root, proof_text: str = PROOF_TEXT) -> None:
    """按 V 的口径落一签（`成立` + 无未解决 error ⇒ `signs_bit3` 成立）。"""
    record_verification(root, statement_id=SID, proof_text=proof_text,
                        verdict=parse_verdict('{"verdict": "成立", "findings": []}'))


def _d_side_ok(root, row) -> bool:
    """D 那一侧的读数：这一条**带没带 V 的签字**（`proof_review_gap` 判三件事）。"""
    return bool(proof_review_gap(root, row)["ok"])


def _m_side_missing(root) -> list[str]:
    """M 那一侧的读数：收工门「攻」那一格还要求哪些命题补签（`unverified_statement_refs`）。"""
    plans = [{"plan_id": "p-1", "history": [{"statement_id": SID, "round": 1}]}]
    refs = unverified_statement_refs(root, plans)
    assert refs["checked"] is True, f"这一格没查成（不是『没缺签』）：{refs['problems']}"
    assert refs["total"] == 1, f"夹具前提：plan 的 history 里应当恰好点名一条命题，读到 {refs['total']}"
    return [str(r["statement_id"]) for r in refs["missing"]]


def test_a_signed_statement_is_not_asked_for_another_signature(tmp_path) -> None:
    """⑤ 正控：已签（最近一签「成立」且 sha 相符）⇒ D 与 M 的清单都不再要求它。"""
    root = tmp_path / "ws"
    root.mkdir()
    _sign(root)
    assert _d_side_ok(root, STATEMENT_ROW) is True, (
        "已经签过的命题在 D 那一侧仍被判『没带签』⇒ D 会让 F 补签，而它已经签过了"
        "（业主裁定：签一次即定，不该反复要求签字）")
    assert _m_side_missing(root) == [], (
        "已经签过的命题仍留在 M 的收工清单里 ⇒ 主控会反复要求补签；"
        f"读到 {_m_side_missing(root)}")


def test_negative_control_a_changed_proof_needs_a_new_signature(tmp_path) -> None:
    """⑤ 负控①：证明改过一个字（sha 不再相符）⇒ D 那一侧必须重新要求签。

    这一条守住的是"不许反复签"的**边界**：它不是"凡签过就永远算数"。签的是那一版，
    正文一改，那一签就不覆盖现在这一版 —— 只有这一种情形才该再送审。
    """
    root = tmp_path / "ws"
    root.mkdir()
    _sign(root)
    changed = {**STATEMENT_ROW, "proof_text": PROOF_TEXT + "3. 再补一步。\n"}
    assert _d_side_ok(root, changed) is False, (
        "改过正文之后 D 那一侧仍然判『带签』⇒ 签名覆盖了它没审过的那一版"
        "（`proof_sha256` 那一格形同虚设）")


def test_negative_control_the_m_checklist_really_reads_the_ledger(tmp_path) -> None:
    """⑤ 负控②：换一个没有台账的根 ⇒ M 的清单必须重新点名它（证明它读的是盘）。

    没有这一条，"已签的不再要求"可能只是那句清单恒返回空 —— 而恒空与"都签过了"
    在读数上分不开（P16 的真空通过）。
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _m_side_missing(empty) == [SID], (
        "一条都没有台账的命题居然不在 M 的清单里 ⇒ 那条清单不读盘")

    signed = tmp_path / "signed"
    signed.mkdir()
    _sign(signed)
    assert _m_side_missing(signed) == [], "同一份夹具在签过之后仍然被点名 ⇒ 上面那条负控没有对照组"
