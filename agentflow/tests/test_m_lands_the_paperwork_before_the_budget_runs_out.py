# -*- coding: utf-8 -*-
"""判据：预算见底之前先把收工必需物落盘（业主 2026-11-17，真机 `projects/lp-ball-5`）。

## 现场

那一趟花满 $5（F 77 趟 / V 18 次），到上限时 `out/paper/ACCEPTANCE-CHECKS.json`
还没写 ⇒ 收工门 `acceptance` 只能报 `acceptance_missing_for_research`（研究型项目
没有可复算的验收口径），而预算已经花光、再也补不回来。

这不是"证明没证出来"，是预算花在证明上、交付物排在它后面。所以这一条把三件事
钉住（a/b/c 与交付单上的三项一一对应）：

| # | 钉什么 | 怎么判 |
|---|---|---|
| a | 那条硬口径逐字进了 M 的 policy（`specs/m.py`）与 M 的手册（`agent_skills.py`） | 两处渲染出来的文本都含那五段字面量 |
| b | 反真空：把那段话从任一处删掉 ⇒ a 必红 | 删过的副本喂同一个检查函数 ⇒ 点名缺的是哪一侧 |
| c | 收工门 `acceptance` 的「验收表缺失」那一档拒信里带着预算余量读数 | 拒信里有"已花 / 上限 / 还剩"；`readings["acceptance"]["budget"]` 三格齐；写得不对那一档不带 |

## 为什么 b 要在"删掉的那一份"上判，而不是再写一条 `assert False`

反真空要证明的是"a 的绿来自那一段文本"，不是"a 恰好绿"。所以检查函数必须能被喂进
一份去掉那段话的渲染结果，并在那一份上真的报出来；同时原样那一份必须报空 ——
两端都判，才排除"这个函数永远红"（那与永远绿是同一种失明）。

## 为什么 c 是读数不是硬闸

预算是用户随时可追加的寄存器（`budget.add_usd`）。拿它去挡交付物，会让"钱不够"长成
"活没干"；这一档要的恰恰相反 —— 钱不够时更要交出交付物。所以 `acceptance` 那一格
的 `status` / `machine_pass` 一个字都不因预算变（见 `test_c_...` 里那三档的 `status`
都是 `fail`），变的是读的人能不能分清"没写"与"写得不对"。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import agent_prompts as AP
from agentflow import agent_skills as AS
from agentflow import budget as BUD
from agentflow import closing as C
from agentflow.store import Store
from agentflow.tools import build_registry

#: 业主 2026-11-17 那条硬口径的逐字段（判据按段钉，不按整句钉：
#: 整句钉会把"标点换一个"判成红，而段钉抓的正是"口径有没有被弱化" ——
#: 五段里任何一段被删掉、被改写成"尽量""建议"，这一条都会红）。
_ANCHOR_FRAGMENTS: tuple[str, ...] = (
    "预算余量低于阈值时，先把收工必需物落盘",
    "`out/paper/ACCEPTANCE-CHECKS.json`",
    "`out/review/REPORT.md`",
    "再回去继续攻证明",
    "宁可少证一条，不许交不出验收表",
)

#: 渲染 M 的提示词用的固定值（与 `tests/test_agent_prompts.py` 同一套：判据必须确定性）。
_TASK = "把这条链路走一遍"
_ROOT = "D:/x"


def _m_policy_text() -> str:
    """M 这一刻真正会读到的提示词（policy 就在里面）。

    为什么不直接读 `specs/m.py` 的 `SPEC.policy` 元组：元组是"声明"，提示词是"模型
    实际读到的那一段"。两者之间还有一层渲染（policy 逐条拼进 brief）—— 拿元组判
    会漏掉"渲染时被截断 / 被别处覆盖"这一档，而那正是模型看到的东西。
    """
    return AP.system_prompt("M", registry=build_registry().registry,
                            task=_TASK, workspace_root=_ROOT)


def _m_handbook_text() -> str:
    """M 的手册正文（`agent_skills` 落成 `skills/M/<slug>.md` 的那些，模型按需读）。"""
    return "\n".join(str(s.body) for s in AS.skills_for("M"))


def _anchor_problems(policy_text: str, handbook_text: str) -> list[str]:
    """两处渲染里缺了哪几段硬口径（空列表 = 两处都齐）。

    纯函数（两段文本都由调用方给）：反真空就是拿"删掉那段话的副本"再喂它一次。
    """
    out: list[str] = []
    for label, text in (("M 的 policy（提示词里那一段）", policy_text),
                        ("M 的手册（agent_skills）", handbook_text)):
        missing = [frag for frag in _ANCHOR_FRAGMENTS if frag not in text]
        if missing:
            out.append(f"{label} 缺这条硬口径的这几段：{missing}")
    return out


# ================================================================ a 逐字锚点
def test_a_the_hard_rule_is_verbatim_in_m_policy_and_handbook() -> None:
    """a：M 的 policy 与 M 的手册都含那条硬口径（五段逐字都在）。"""
    policy = _m_policy_text()
    handbook = _m_handbook_text()
    assert _anchor_problems(policy, handbook) == [], (
        "M 的两处落点没有同时含那条硬口径："
        + "；".join(_anchor_problems(policy, handbook)))

    # 反真空的一半（不是"读了一遍自己"）：两处真的是两份不同的文本。
    assert policy != handbook, "两处读到的是同一段文本 ⇒ 这条判据只判了一个落点"
    # 手册里那一段要落在"收工"那条 skill 上：散在别处的正文模型不会在收工那一刻读到。
    hit = [str(s.slug) for s in AS.skills_for("M")
           if BUD.PAPERWORK_FIRST_RULE in str(s.body)]
    assert hit, ("M 的手册里没有任何一条 skill 的正文含那条硬口径 ⇒ 模型收工时读不到它")
    assert any("收工" in slug for slug in hit), (
        f"含这条硬口径的 skill 不是收工那一条（{hit}）⇒ 模型在收工那一刻不会翻到它")


# ================================================================ b 反真空
def test_b_deleting_the_rule_turns_the_anchor_red() -> None:
    """b：把那段话从任一处删掉 ⇒ 同一个检查函数必红，并点名缺的是哪一侧。

    两端都判：原样那一份必须报空（否则"删了就红"什么也证明不了 —— 一个永远红的
    判据与永远绿的是同一种失明）。
    """
    policy = _m_policy_text()
    handbook = _m_handbook_text()
    assert _anchor_problems(policy, handbook) == [], (
        "正控不成立：原样两份文本上这个检查函数就报红 ⇒ 下面的反真空没有意义")

    stripped_policy = policy.replace(BUD.PAPERWORK_FIRST_RULE, "")
    assert stripped_policy != policy, "删掉那段话没改变文本 ⇒ 反真空没打到东西"
    problems_policy = _anchor_problems(stripped_policy, handbook)
    assert problems_policy, "删掉 policy 里那段话之后这个检查函数仍然报空 ⇒ 它没在量这一格"
    assert len(problems_policy) == 1 and "policy" in problems_policy[0], (
        "删 policy 那一侧时只该点名 policy 那一侧：", problems_policy)

    stripped_handbook = handbook.replace(BUD.PAPERWORK_FIRST_RULE, "")
    assert stripped_handbook != handbook, "删掉那段话没改变文本 ⇒ 反真空没打到东西"
    problems_handbook = _anchor_problems(policy, stripped_handbook)
    assert problems_handbook, "删掉手册里那段话之后这个检查函数仍然报空 ⇒ 它没在量这一格"
    assert len(problems_handbook) == 1 and "手册" in problems_handbook[0], (
        "删手册那一侧时只该点名手册那一侧：", problems_handbook)


# ================================================================ c 拒信带预算读数
def _research_store(tmp_path: pathlib.Path, *, spent_usd: float | None,
                    total_usd: float | None) -> Store:
    """一个研究型工作区：有 `research_questions` 行、没有验收表；按需给账与预算。"""
    st = Store(tmp_path / "ws")
    st.init()
    with st.tx("research_questions", actor="test") as tx:
        tx.upsert("research_questions",
                  {"question_id": "000001", "question": "为什么？", "status": "open"})
    if spent_usd is not None:
        with st.tx("usage_ledger", actor="test") as tx:
            tx.upsert("usage_ledger", {
                "usage_id": "000001", "scope": "summon", "role": "F",
                "task_id": "t-f-000001", "tokens_in": 10, "tokens_out": 20,
                "tokens_total": 100, "usd": float(spent_usd), "attempts": 1,
                "at": "2026-11-17T00:00:00+08:00"})
    if total_usd is not None:
        pathlib.Path(st.root, BUD.REGISTER_NAME).write_text(
            json.dumps({"total_usd": float(total_usd), "added": []}, ensure_ascii=False),
            encoding="utf-8")
    return st


def _acceptance_blocker(rep: C.ClosingReport) -> C.Finding:
    hits = [f for f in rep.blockers if f.code == "acceptance_missing_for_research"]
    assert len(hits) == 1, [f.code for f in rep.blockers]
    return hits[0]


def test_c_the_missing_acceptance_refusal_carries_the_budget_remaining(
        tmp_path: pathlib.Path) -> None:
    """c：验收表缺失那一档的拒信里，把"还剩多少预算"与"缺的是哪一格"写在一起。

    三档一起判（对应真机 / 正常 / 读不成）：

    1. 真机 `lp-ball-5` 的形状：上限 $5、已花 $5.0012 ⇒ 还剩负数，拒信里要看得见
       "已花 / 上限 / 还剩"三个数，并说明余量被扣穿；
    2. 余量充足：这一格照样 `fail`（没写就是没写），而拒信说的是"缺的是没写，不是
       写不起" —— 钱多不改变判定，只改变读法；
    3. 没设预算：剩余算不出来（不是 0、也不是"还剩很多"）。
    """
    # ---- ① 真机形状：花满 / 扣穿
    st = _research_store(tmp_path / "a", spent_usd=5.0012, total_usd=5.0)
    rep = C.ClosingReport()
    C._check_acceptance(rep, st, ".")
    assert rep.status["acceptance"] == "fail", rep.status
    detail = _acceptance_blocker(rep).detail
    assert "已花 $5.001200" in detail, detail
    assert "上限 $5.000000" in detail, detail
    assert "还剩 $-0.001200" in detail, detail
    assert "透支" in detail, detail
    got = rep.readings["acceptance"]["budget"]
    assert got["remaining_usd"] < 0, got
    assert got["below_reserve"] is True, got
    assert got["reserve_usd"] == BUD.PAPERWORK_RESERVE_USD, got
    # 读数不是硬闸：这一格的 fail 来自"没有验收表"，不来自预算。
    assert "没有可复算的验收口径" in detail, detail
    assert "缺的是那一行，不是那个数" in detail, detail

    # ---- ② 余量充足：判定一个字不变，只是读法变了
    rich = _research_store(tmp_path / "b", spent_usd=1.0, total_usd=100.0)
    rep_rich = C.ClosingReport()
    C._check_acceptance(rep_rich, rich, ".")
    assert rep_rich.status["acceptance"] == "fail", rep_rich.status
    rich_detail = _acceptance_blocker(rep_rich).detail
    assert "还剩 $99.000000" in rich_detail, rich_detail
    assert "余量还在收工储备线" in rich_detail, rich_detail
    assert "「没写」" in rich_detail, rich_detail

    # ---- ③ 没设预算：剩余算不出来（不是 0，也不是"还剩很多"）
    bare = _research_store(tmp_path / "c", spent_usd=2.0, total_usd=None)
    rep_bare = C.ClosingReport()
    C._check_acceptance(rep_bare, bare, ".")
    assert rep_bare.status["acceptance"] == "fail", rep_bare.status
    bare_detail = _acceptance_blocker(rep_bare).detail
    assert "算不出来" in bare_detail, bare_detail
    assert rep_bare.readings["acceptance"]["budget"]["remaining_usd"] is None, \
        rep_bare.readings["acceptance"]["budget"]


def test_c2_the_other_acceptance_tier_does_not_carry_the_budget_note(
        tmp_path: pathlib.Path) -> None:
    """c 的另一半（档位纪律）：「写得不对」那一档不带预算读数。

    为什么必须分开：那一档缺的是"行里的读数不够"（改行），不是"文件没写"（补文件）。
    把预算那句贴到它身上，会把人往"是不是钱不够"上带 —— 而那一刻钱够不够与这一格
    红不红无关。三态纪律的反面：不是所有红都长得一样。
    """
    st = _research_store(tmp_path, spent_usd=5.0012, total_usd=5.0)
    checks = pathlib.Path(st.root, C.ACCEPTANCE_CHECKS_NAME)
    checks.parent.mkdir(parents=True, exist_ok=True)
    checks.write_text(json.dumps({"checks": [
        {"id": "R1", "name": "立起研究问题", "kind": "research_question_rows", "min": 0},
        {"id": "R4", "name": "想", "kind": "conjecture_rows", "min": 5,
         "note": "这一轮想不出五条可检验的猜想"},
    ]}, ensure_ascii=False), encoding="utf-8")
    rep = C.ClosingReport()
    C._check_acceptance(rep, st, ".")
    assert rep.status["acceptance"] == "fail", rep.status
    codes = [f.code for f in rep.blockers]
    assert "acceptance_missing_for_research" not in codes, codes
    detail = "；".join(f.detail for f in rep.blockers)
    assert "预算读数" not in detail, (
        "「写得不对」那一档不该带预算读数（那一档的问题不是钱）：", detail)
    assert "预算" not in json.dumps(rep.readings.get("acceptance") or {},
                                   ensure_ascii=False), rep.readings.get("acceptance")
