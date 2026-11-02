"""D11：「谁是 V 的入口」只有一个真身（`capabilities.ALLOWED_EDGES`）。

## 改前的现场

同一件事实（V 的签名拓扑）在三处各写一遍：`specs/m.py` 的 policy、`agent_skills.py` 的
手册、以及由这份 brief 渲染出来的 `AGENT-PROFILES.md`。三份都写成绝对口吻
（要 V 签字只走经 B 的 `M→B→V`），于是：

- 读的人分不清哪一份是「这一角色的口径」、哪一份是「全局路线图」；
- 改一处，另外两处不会变，也不会有任何判据变红（这正是「同一事实多副本」的病）。

## 2026-11-02 的收口（业主）

```text
既然B侧不收录F侧产出的异常无签证明，自然不会有无签证明被M看到，
所以M根本上没有V签的编辑权也没有获取V签的义务，无需唤起V
```

⇒ 手册与政策里那条「经 B 的两跳路」整条退场：M 这一侧只剩两条事实（V 不在出边里、
V 签不经你的手），路线细节只交回伙伴表。

## 这一组钉住什么

1. 手册与政策都写「V 签不经你的手 / 没有编辑权 / 没有获取义务」，且都不再抄那条两跳路；
2. 手册与政策都明写「F 与 B 各有直连 V 的边」，并把「谁直连谁」交回伙伴表；
3. 改前那句不带主语的第二份路线（要 V 签字只走…）不再出现；
4. 数据面：伙伴表（`ALLOWED_EDGES`）里 M 没有到 V 的边、F 与 B 各有。

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


#: 手册与政策都必须写着的那两句（2026-11-02 的收口）。
_MUST = ("V 签不经你的手", "没有 V 签的编辑权", "没有获取 V 签的义务",
         "F 与 B 各有直连 V 的边", "伙伴表")


def test_the_manual_says_the_v_sign_does_not_go_through_m() -> None:
    """手册那一侧：V 签不经 M 的手（没有编辑权、没有获取义务），路线交回伙伴表。"""
    body = _manual_body()
    for needle in _MUST:
        assert needle in body, f"手册里读不到「{needle}」"
    assert "M→B→V" not in body, "手册里还抄着那条两跳路（2026-11-02 已退场）"
    assert "不是你直连 V" not in body, "手册里还留着上一版两跳路的说明"


def test_the_manual_no_longer_writes_a_second_route() -> None:
    """判据 4 的下半：改前那句不带主语的第二份路线不再出现。"""
    body = _manual_body()
    for old in ("要 V 签字只走", "替代链是"):
        assert old not in body, f"手册里还留着改前那句第二份路线：{old}"


def test_the_m_policy_says_the_v_sign_does_not_go_through_m() -> None:
    """`specs/m.py` 那一侧：同一条口径，且不再出现两跳路。"""
    policy = _m_policy()
    for needle in _MUST:
        assert needle in policy, f"政策里读不到「{needle}」：{policy[:400]}"
    assert "M→B→V" not in policy, "M 到 V 的两跳路还在（2026-11-02 已退场，不该再抄）"
    assert "要 V 签字只走" not in policy, "改前那句第二份路线还在"
    assert "的那条两跳路" not in policy, "改前那句的路数还在（这一句是路线图的副本）"


def test_the_partner_table_is_the_single_truth_and_matches_those_sentences() -> None:
    """反真空：那两句话必须与伙伴表（`ALLOWED_EDGES`）一致，且 M 确实没有到 V 的边。"""
    assert "V" not in C.ALLOWED_EDGES["M"], (
        "M 有了到 V 的直连边 ⇒ 手册/政策里那句「V 不在你的出边里」变成假话")
    assert "V" in C.ALLOWED_EDGES["F"], "F 没有到 V 的边 ⇒「F 与 B 各有直连 V 的边」是假话"
    assert "V" in C.ALLOWED_EDGES["B"], "B 没有到 V 的边 ⇒「各有直连 V 的边」是假话"
    assert "B" in C.ALLOWED_EDGES["M"], "M 没有到 B 的边 ⇒ 手册里「B 你可以直接派」是假话"
