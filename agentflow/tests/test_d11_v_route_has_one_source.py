"""D11：「谁是 V 的入口」只有一个真身（`capabilities.ALLOWED_EDGES`）。

## 改前的现场

同一件事实（V 的签名拓扑）在三处各写一遍：`specs/m.py` 的 policy、`agent_skills.py` 的
手册、以及由这份 brief 渲染出来的 `AGENT-PROFILES.md`。三份都写成绝对口吻
（要 V 签字只走经 B 的 `M→B→V`），于是：

- 读的人分不清哪一份是「这一角色的口径」、哪一份是「全局路线图」；
- 改一处，另外两处不会变，也不会有任何判据变红（这正是「同一事实多副本」的病）。

现在：路线图只有一份，就是伙伴表（`capabilities.ALLOWED_EDGES` 现算渲染出来的）；
手册与政策只留「你（M）这一侧」的口径，并指明「见伙伴表」。

## 这一组钉住什么

1. 手册里那条路线只出现一次，而且带主语「你（M）」；
2. 手册里明写「F 与 B 各有直连 V 的边」，并把「谁直连谁」交回伙伴表；
3. 改前那句不带主语的第二份路线（要 V 签字只走…）不再出现；
4. 数据面：伙伴表本身（`ALLOWED_EDGES`）与那两句话一致 —— M 没有到 V 的边、
   F 与 B 各有；不一致时这几句话就变成了假话。

第 4 条是反真空：只断言字符串消失，可以靠「整段删掉」满足；断言它与边表一致，
才能挡住「照抄一份已经过期的路线」。
"""
from __future__ import annotations

from agentflow import agent_skills as AS
from agentflow import capabilities as C
from agentflow import specs as SP

#: 手册里「派给谁」那一条（唯一一条写着派活路线的条目）。
_MANUAL_SLUG_NEEDLE = "按任务类型"


def _manual_body() -> str:
    """M 的手册正文（「按任务类型选收件人」那一条）。"""
    route = next(s for s in AS.CATALOG["M"] if _MANUAL_SLUG_NEEDLE in s.slug)
    return route.body


def _m_policy() -> str:
    """M 的政策全文（`specs/m.py` 是唯一真身，`agent_prompts.ROLE_BRIEFS` 由它派生）。"""
    return "\n".join(str(s) for s in SP.builtin_specs()["M"].brief.policy)


def test_the_manual_has_one_route_copy_with_the_subject() -> None:
    """判据 4 的上半：手册里的 V 路线只出现一次，且那一次带主语「你（M）」。"""
    body = _manual_body()
    assert body.count("M→B→V") == 1, (
        f"手册里 V 的那条路线写了 {body.count('M→B→V')} 遍 —— 同一件事多副本正是要治的病")
    assert "你（M）" in body, "手册里那一句没有主语（读的人不知道这句是对谁说的）"
    assert "F 与 B 各有直连 V 的边" in body, (
        "手册里没有写清「谁直连 V」（那件事只该在伙伴表里出现一次）")
    assert "不是你直连 V" in body, "两跳路必须写明「不是你直连 V」"
    assert "伙伴表" in body, "手册没有指向唯一真身（伙伴表）"


def test_the_manual_no_longer_writes_a_second_route() -> None:
    """判据 4 的下半：改前那句不带主语的第二份路线不再出现。"""
    body = _manual_body()
    for old in ("要 V 签字只走", "替代链是"):
        assert old not in body, f"手册里还留着改前那句第二份路线：{old}"


def test_the_m_policy_keeps_one_route_with_the_subject() -> None:
    """`specs/m.py` 那一侧：同一句改成「你（M）…只能走」，并交回伙伴表。"""
    policy = _m_policy()
    assert "你（M）" in policy, f"政策里那一句还没有主语：{policy[:400]}"
    assert "M→B→V" in policy, "M 到 V 的两跳路不见了（那条路今天仍然通，不该顺手删掉）"
    assert "经 B" in policy, "两跳路没有写明「经 B」"
    assert "不是你直连 V" in policy, "两跳路没有写明「不是你直连 V」"
    assert "F 与 B 各有直连 V 的边" in policy, "政策里没有写清 F 与 B 的直连 V 的边"
    assert "伙伴表" in policy, "政策没有指向唯一真身（伙伴表）"
    # 改前那句：不带主语、把路线图当成这一角色的话说死
    assert "要 V 签字只走" not in policy, "改前那句第二份路线还在"
    assert "的那条两跳路" not in policy, "改前那句的路数还在（这一句是路线图的副本）"


def test_the_partner_table_is_the_single_truth_and_matches_those_sentences() -> None:
    """反真空：那两句话必须与伙伴表（`ALLOWED_EDGES`）一致，且 M 确实没有到 V 的边。"""
    assert "V" not in C.ALLOWED_EDGES["M"], (
        "M 有了到 V 的直连边 ⇒ 手册/政策里那句「V 不在你的出边里」变成假话")
    assert "V" in C.ALLOWED_EDGES["F"], "F 没有到 V 的边 ⇒「F 与 B 各有直连 V 的边」是假话"
    assert "V" in C.ALLOWED_EDGES["B"], "B 没有到 V 的边 ⇒ 两跳路 M→B→V 不成立"
    assert "B" in C.ALLOWED_EDGES["M"], "M 没有到 B 的边 ⇒ 两跳路 M→B→V 第一步就走不动"
