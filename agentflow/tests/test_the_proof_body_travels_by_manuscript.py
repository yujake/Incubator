# -*- coding: utf-8 -*-
"""判据：证明正文的载体只有手稿（业主 2026-11-04 裁定 甲）。

## 为什么要有这一条

今晚业主把四件事判定为「老路」，其中第一件是「内联正文」：

> `verify_proof(proof_text=…)` / `register_statement(proofs=[…])` 能换到签、能进台账
> ⇒ 甲：在册命题也要给 `proof_manuscript`。

代码面的闸由另一条 lane 落在 `agent_v/core.py` / `tools/verify_tools.py` / `specs/v.py` /
`agent_b/register_statement.py`；这一条只钉「提示词教了什么」 —— 因为老路在提示词里
留下的形态不是一句错话，而是四种「可以不给稿」的教法：

1. F 的 policy 说 `proof_text` 可以不给、`proof_manuscript` 是「还没在册」时那条入口；
2. F 的送审表只有四行（`statement_id` / `proof_no` / `proof_text` / `readonly_facts`），
   没有 `proof_manuscript`；
3. B 的 policy 教「`proofs=[{proof_no: 1..N, text: …}]` 一次交清」——那条路没有稿，
   `## 依赖` 段读不出来（依赖面恒 0）；B 的手册在「改写后重签」处也只给 `statement_id`；
4. 共用段（`PAPER_PACK` / `TOOLCHAIN_FACTS` / L 的关档文案）把「写进 statements 的
   `proof_text`，再请 V 用 `verify_proof` 走查」当成交付形状。

## 判据（每条都两向）

- 正控：改后的渲染结果 / 手册正文里读得到「在册也给稿」与「正文的唯一载体是手稿」；
- 反真空：把「改前那句原话」喂给同一个读法 ⇒ 必须报缺（判据不是橡皮图章）。

零模型钱：只读 `system_prompt` / `CATALOG` 里的字符串，不起任何进程。
"""
from __future__ import annotations

from agentflow import agent_prompts as AP
from agentflow import agent_skills as AS
from agentflow.specs import b as SB
from agentflow.tools import build_registry

#: 强调符号与空白：``在册也给 `proof_manuscript``` 与 ``在册也给`proof_manuscript``` 同义。
import re
_EMPHASIS = re.compile(r"[\s*`]+")


def _flat(text: str) -> str:
    return _EMPHASIS.sub("", str(text))


def _missing(text: str, needles: tuple[str, ...]) -> list[str]:
    flat = _flat(text)
    return [needle for needle in needles if _flat(needle) not in flat]


def _prompt(role: str) -> str:
    return AP.system_prompt(role, registry=build_registry().registry,
                            task="把这条链路走一遍", workspace_root="D:/x")


def _skill(role: str, slug: str) -> str:
    return next(s for s in AS.CATALOG[role] if s.slug == slug).body


#: F 的 policy 必须读到的新口径（「在册也给稿」的三种说法都在这里）。
#:
#: 2026-11-10 第二刀（业主裁定「撤去所有有关对某个给定命题号进行攻坚或写证明的逻辑」）
#: 改写了三条针，强度只升不降：
#:   · `在册了也点同一份稿` → `收录前后都点同一份稿`（同一件事，e78a3c44 已按"收录"重写）；
#:   · `每份各自落成一份手稿` → `每份落在同一份稿的第 N 个证明上`（多证明改成 `-pN`）；
#:   · `F.step 把这一份证明落成 reports/f-proof-<命题号>.md`
#:     → `…落成 reports/f-proof-<你的稿号>.md`（稿份按稿号命名，p272 之后命题号不进稿名）；
#:     并新增两条正向针：`你这一趟不交命题号`（F 的交接口上不再有号）、
#:     `命题号由 B 收录时现取`（号的归属只有一处）。
F_NEW: tuple[str, ...] = (
    "`proof_manuscript` **一律给**",
    "收录前后都点同一份稿",
    "每份落在同一份稿的第 N 个证明上",
    "不要用内联的 `proofs=[...]` 交正文",
    "把这一份证明落成 `reports/f-proof-<你的稿号>.md`",
    "你这一趟不交命题号",
    "命题号由 **B 收录时现取**",
)

#: F 的 policy 里不许再出现的旧口径。
F_OLD: tuple[str, ...] = (
    "`proof_manuscript` 是**还没在册**时的那条入口",
    "`proof_text` 可以不给",
    "各条证明用 `proofs=[{proof_no: 1..N, text: …}]` 一次交清",
    # 2026-11-10 第二刀：F 的送审参数表里不许再有"在册后给号"这一格
    "`statement_id`（在册后给这条命题的号",
    "在册后再加 `statement_id`",
    "`reports/f-proof-<命题号>.md`",
)

#: B 的 policy 必须读到的新口径。
B_NEW: tuple[str, ...] = (
    "`proof_manuscript` 是证明正文的载体",
    "在册也给稿",
    "不要用内联的 `proofs=",
    "依赖面恒 0",
    "自产命题由手稿 `proof_manuscript` 带进来",
)

#: B 的 policy（与动作摘要）里不许再出现的旧口径。
B_OLD: tuple[str, ...] = (
    "`proof_text` 可缺（缺则落最低等级并进待办）",
    "**同一条定理的多种证明只占一条 stmt**：用户要「几种证明语言 / 几条独立路径」时，"
    "目标是同一条命题的 `proof_no` 1..N，不是 N 条独立命题。登记时一次交清："
    "`own.register_statement` 的 `proofs=[{proof_no: 1..N, text: …}]`",
)

#: B 的动作/参数说明里必须读到的新口径（它们不进渲染提示词，进参数表与工具说明）。
B_SOURCE_NEW: tuple[str, ...] = (
    "`proof_manuscript` 是证明正文的载体",
    "自产命题（origin='own_result'）的正文不走这一格",
    "交一份证明手稿",
)

#: B 的参数说明里不许再出现的旧口径。
B_SOURCE_OLD: tuple[str, ...] = (
    "origin='own_result' 的逐字证明摘录。**可以不给**（P-06）",
    "**并且**给 proof_text",
)


def _b_all_text() -> str:
    """B 的动作摘要 + 每个参数的 description（渲染面 + 参数面两处）。"""
    parts: list[str] = []
    for action in SB.ACTIONS:
        parts.append(str(action.summary))
        props = dict((action.params or {}).get("properties") or {})
        for spec in props.values():
            if isinstance(spec, dict):
                parts.append(str(spec.get("description") or ""))
    return "\n".join(parts)


# ------------------------------------------------------------------ 一、F 的 policy

def test_f_policy_sends_the_manuscript_even_when_the_statement_is_registered() -> None:
    """正控：F 的 policy 读得到「在册也给稿」，旧的三句都不在。"""
    text = _prompt("F")
    assert _missing(text, F_NEW) == [], (
        "F 的 policy 还没有「在册也给 proof_manuscript」这一条（老路仍在）："
        f"{_missing(text, F_NEW)}")
    still = [old for old in F_OLD if _flat(old) in _flat(text)]
    assert still == [], f"F 的 policy 还留着教「可以不给稿」的旧句：{still}"


# ------------------------------------------------------------------ 二、B 的 policy

def test_b_policy_carries_the_body_by_manuscript_and_not_inline_proofs() -> None:
    """正控：B 的 policy 读得到「正文的载体是稿」，内联 `proofs=[…]` 不再被教成正路。"""
    text = _prompt("B")
    assert _missing(text, B_NEW) == [], (
        "B 的 policy 还没有「正文的载体是手稿」这一条（老路仍在）："
        f"{_missing(text, B_NEW)}")
    still = [old for old in B_OLD if _flat(old) in _flat(text)]
    assert still == [], f"B 的 policy 还留着教内联正文的旧句：{still}"


def test_b_action_and_param_text_no_longer_offers_inline_text() -> None:
    """正控：B 的动作摘要/参数说明把「可以不给」换成「稿是载体」。"""
    text = _b_all_text()
    assert _missing(text, B_SOURCE_NEW) == [], (
        "B 的动作/参数说明里还没有「稿是载体」："
        f"{_missing(text, B_SOURCE_NEW)}")
    still = [old for old in B_SOURCE_OLD if _flat(old) in _flat(text)]
    assert still == [], f"B 的动作/参数说明还留着旧口径：{still}"


# ------------------------------------------------------------------ 三、手册正文

def test_f_manual_submission_table_has_the_manuscript_as_required() -> None:
    """正控：F 手册的送审表把 `proof_manuscript` 写成必填、不再列 `proof_text`。"""
    body = _skill("F", "交付-证明要能被别人复核")
    assert _missing(body, ("| `proof_manuscript` | **是** |", "在册也给 `proof_manuscript`",
                           "一律点手稿路径")) == [], (
        "F 手册的送审表仍把稿当「未在册时那条入口」")
    assert _flat("| `proof_text` | 否") not in _flat(body), (
        "F 手册的送审表还列着 `proof_text` 这一行（它会把正文重新教成参数）")


def test_b_manual_resign_goes_through_the_b_manuscript() -> None:
    """正控：B 手册在「改写后重签」处点名 b-proof 稿，而不是只给 statement_id。"""
    body = _skill("B", "登记-三件式与证据三态")
    assert _missing(body, ("reports/b-proof-<命题号>.md", "`proof_manuscript` 给这份稿的路径",
                           "在册也给稿", "`proof_text` 只是它收进台账后的那一列")) == [], (
        "B 手册的「三件式 / 改写后重签」还没有把稿写成载体")
    old = "`V.verify_proof`：`statement_id` 必填，要审第几条证明就带 `proof_no`"
    assert _flat(old) not in _flat(body), "B 手册还教「只给 statement_id 就能重签」"


def test_v_manual_names_the_manuscript_param() -> None:
    """正控：V 手册列的是 `proof_manuscript`，不再把 `proof_text` 当可选参数。"""
    body = _skill("V", "复核-两态并指到那一步")
    assert "proof_manuscript" in _flat(body), "V 手册没点名 proof_manuscript"
    old = "可选 `proof_no` / `proof_text` / `readonly_facts`"
    assert _flat(old) not in _flat(body), "V 手册还把 proof_text 当可选参数（老路）"


# ------------------------------------------------------------------ 四、共用段

def test_paper_pack_and_lean_off_route_go_through_the_manuscript() -> None:
    """正控：共用段不再教「写进 statements 的 proof_text，再请 V 走查」。"""
    paper = AP.PAPER_PACK
    assert _missing(paper, ("证明过程逐字由框架落成一份手稿",
                            "`proof_manuscript` 给那一份稿 —— 在册也给")) == [], (
        "PAPER_PACK 的关档替代路线还没改走手稿")
    old = "证明过程逐字进 `statements` 的 `proof_text`"
    assert _flat(old) not in _flat(paper), (
        "PAPER_PACK 还在教把正文内联进 statements.proof_text")


def test_toolchain_text_lean_off_route_goes_through_the_manuscript(
        monkeypatch) -> None:
    """正控：`TOOLCHAIN_FACTS` 与 L 的关档文案都改走手稿。"""
    monkeypatch.setattr(AP, "_lean_switch", lambda: (False, "判据夹具"))
    monkeypatch.setattr(AP, "_toolchain_readings", lambda: None)
    AP.toolchain_facts_text.cache_clear()
    AP.toolchain_formal_text.cache_clear()
    try:
        facts = AP.toolchain_facts_text()
        formal = AP.toolchain_formal_text()
    finally:
        AP.toolchain_facts_text.cache_clear()
        AP.toolchain_formal_text.cache_clear()
    assert "证明正文先落成一份手稿" in _flat(facts), (
        "TOOLCHAIN_FACTS 的关档路线还在教内联正文")
    old = "把证明过程写进 `statements` 的 `proof_text`"
    assert _flat(old) not in _flat(facts), (
        "TOOLCHAIN_FACTS 还留着「写进 statements 的 proof_text」")
    assert "把证明过程逐字交给框架落成一份手稿" in _flat(formal), (
        "L 的关档文案还在教内联正文")
    old = "把证明过程逐字写进 `statements` 的 `proof_text`"
    assert _flat(old) not in _flat(formal), (
        "L 的关档文案还留着「写进 statements 的 proof_text」")


# ------------------------------------------------------------------ 五、反真空

def test_the_needles_reject_the_old_road_text() -> None:
    """反真空：把改前那几句原话喂给同一个读法 ⇒ 每一组都必须报缺。

    没有这一条，上面几条可能只是"某段文本恰好含有某个词"；这一条证明它读的正是
    「在册也给稿」这个判断，而不是任何一段带 `proof_manuscript` 的字。
    """
    old_f = (
        "`statement_id`（在册后必填，这条命题的号）；`proof_no` 是第几条证明（缺省 1）；"
        "`proof_text` 可以不给（不给或给空串时 V 从 `statements` 取 `proof_no` 指的那一份）；"
        "`proof_manuscript` 是**还没在册**时的那条入口")
    assert _missing(old_f, F_NEW) == list(F_NEW), (
        "F 的新针在旧文本上居然全中 ⇒ 这条判据读的不是那个判断")
    old_b = (
        "`proof_text` 可缺（缺则落最低等级并进待办）"
        "**同一条定理的多种证明只占一条 stmt**：用户要「几种证明语言 / 几条独立路径」时，"
        "目标是同一条命题的 `proof_no` 1..N，不是 N 条独立命题。登记时一次交清："
        "`own.register_statement` 的 `proofs=[{proof_no: 1..N, text: …}]`")
    assert _missing(old_b, B_OLD) == [], "反真空的旧文本自己都不含旧句，判据写错了"
    assert _missing(old_b, B_NEW) == list(B_NEW), (
        "B 的新针在旧文本上居然全中 ⇒ 这条判据读的不是那个判断")
    old_shared = "把证明过程逐字写进 `statements` 的 `proof_text`，再请 V 用 `verify.verify_proof` 逐行走查"
    assert _missing(old_shared, ("把证明过程逐字交给框架落成一份手稿",)) != [], (
        "共用段的新针在旧文本上命中了 ⇒ 判据不是橡皮图章")
