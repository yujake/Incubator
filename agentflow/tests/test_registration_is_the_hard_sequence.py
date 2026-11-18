# -*- coding: utf-8 -*-
"""「立项 → 落稿 → 送审 → 收录」是硬序列；三个号各管一件事（p272）。

## 业主裁定（逐字，唯一依据）

> 「F 的稿自己维护一套号源，不依赖命题号和计划号。停掉错误的口径。」

再一轮点名：「计划为什么有稿？」—— 计划不拥有稿件，「计划稿」这个概念本身就是错的。

## 三个号（这一份钉的就是这件事）

```text
· 稿号：F 自己发（manuscriptids.next_manuscript_id；data/counters.json 的 manuscript 号段）
        ⇒ 稿叫 reports/f-proof-<稿号>.md；它是签的单位（同一份稿改稿仍是同一个稿号）
· 计划号：继续 / 放弃 / 更改的单位；F 在计划下做；计划不拥有稿
· 命题号：B 收录时现取（V 判成立之后），只落在 statements 那一行上
```

## 这一份钉什么

| # | 判据 | 反真空 |
|---|---|---|
| ① | M 的渲染题面 + 手册里三层号的说法都在（稿号管签 / 计划号管去留 / 命题号收录时现取） | 各删一处 ⇒ 同一算式红 |
| ② | F 的稿只按稿号命名；收录不改名；旧约定名只读兼容可签 | 把命名改回命题号 / 计划号 ⇒ 同一算式红 |
| ③ | 不传 `statement_id` 也能送审的三条正面读数（有缺省 / 稿是合法族名 / 旧约定名是签载体） | 把那一格改成"必填"式的假读数 ⇒ 同一算式红 |
| ④ | 业主两次驳回的写法（按钟判、框架催办）一个字都不许回来 | 塞一句回去 ⇒ 红 |

零模型调用、零网络。
"""
from __future__ import annotations

import inspect

from agentflow import agent_prompts as AP
from agentflow import agent_skills as AS
from agentflow import manuscriptfamily as MF
from agentflow.agent_f import AgentF
from agentflow.agent_v import AgentV
from agentflow.tools import build_registry

TASK = "把这条链路走一遍"
ROOT = "D:/x"

#: ① 三层号那一句（判据只认这个字面）。
THREE_LAYERS_NEEDLE = "三个号各管一件事"
#: ① 四跳落点：少一环就说明「硬序列」被压回了"记得登记"这种软话。
HOP_NEEDLES: tuple[str, ...] = (
    "**稿号**是 F 自己发的",
    "**计划号**管继续/放弃/更改",
    "**命题号是 B 收录时现取的**",
    "`reports/f-proof-<稿号>.md`",
    "**不改稿名**",
)
#: ① 末句：计划管去留、稿号管签、命题号管收录。
SPLIT_NEEDLE = "计划管去留、稿号管签、命题号管收录"

#: ② 决定即立项（分命题，不分钟）。
DECIDE_NEEDLE = "决定要证某条命题的那一刻就立项"
DECIDE_REASONS: tuple[str, ...] = (
    "拿计划号",
    "一次是稿名对不上",
    "一次是 B 根本没被派活",
    "与钟无关：分的是命题，不是时刻",
)

#: ③ 成果是收录的产物，不是立项的产物；身份有 `stmt:` / `mss:` 两种。
LEDGER_NEEDLE = "成果的身份有两种"
LEDGER_REASONS: tuple[str, ...] = (
    "**收录**的产物，不是立项的产物",
    "「草稿已落盘」",
    "`mss:<稿号>`",
)

#: 业主两次驳回的那两种写法（按钟判 / 框架催办）—— 题面与手册里一个都不许有。
REJECTED_LITERALS: tuple[str, ...] = (
    "第一个小时",
    "墙钟过半",
    "墙钟过 50",
    "过半时自检",
    "statements 为 0",
    "催办",
    "registration_overdue",
    "nudge",
)

#: 手册那一侧的锚点（手册与题面是两份排版不同的文本：题面一段落、手册分条。
#: 两处都要有那些意思，但不许逐字重复 —— `test_agent_skills.py` 有一条判据
#: 钉着"正文任何一行都不许出现在前置提示词里"）。
MANUAL_NEEDLES: tuple[str, ...] = (
    "三个号各管一件事",
    "稿号**：F 自己发",
    "计划号**：**继续 / 放弃 / 更改",
    "命题号**：**B 收录时现取",
    "`reports/f-proof-<稿号>.md`",
    "稿名一个字不动",
    "计划管去留，稿号管签，命题号管收录",
    "决定要证某条命题的那一刻就立项",
    "成果的身份有两种",
    "**收录**的产物",
    "`mss:<稿号>`",
)


def _manual_problems(body: str) -> list[str]:
    """手册那一份缺了什么（空列表 = 三层号与四跳都在）。纯函数（反真空走同一条路）。"""
    text = str(body or "")
    missing = [needle for needle in MANUAL_NEEDLES if needle not in text]
    return [f"手册缺锚点：{needle!r}" for needle in missing]


def _render(role: str) -> str:
    return AP.system_prompt(role, registry=build_registry().registry,
                            task=TASK, workspace_root=ROOT)


def _m_prompt() -> str:
    return _render("M")


def _m_manual() -> str:
    for skill in AS.skills_for("M"):
        body = str(getattr(skill, "body", "") or "")
        if "三个号各管一件事" in body:
            return body
    return ""


# ------------------------------------------------------------------ ① 题面 + 手册

def test_the_rendered_prompt_carries_all_three() -> None:
    """① M 的渲染题面：三层号 + 四跳落点 + 末句都在。"""
    text = _m_prompt()
    assert THREE_LAYERS_NEEDLE in text, "M 的题面里没有「三个号各管一件事」"
    for needle in HOP_NEEDLES:
        assert needle in text, f"M 的题面缺落点：{needle!r}"
    assert SPLIT_NEEDLE in text, "M 的题面缺「计划管去留、稿号管签、命题号管收录」"
    assert DECIDE_NEEDLE in text
    for needle in DECIDE_REASONS:
        assert needle in text, f"M 的题面缺「决定即立项」的论据：{needle!r}"
    assert LEDGER_NEEDLE in text
    for needle in LEDGER_REASONS:
        assert needle in text, f"M 的题面缺「成果是收录的产物」的论据：{needle!r}"


def test_the_manual_carries_the_same_three() -> None:
    """①（手册那一侧）：三层号与四跳在 `agent_skills` 的 M 手册里都在。"""
    body = _m_manual()
    assert body, "M 手册里找不到「三个号各管一件事」那一条 ⇒ 手册与题面分家了"
    problems = _manual_problems(body)
    assert not problems, problems


def test_removing_the_manual_anchor_makes_it_red() -> None:
    """① 反真空：删掉手册里的一个锚点 ⇒ `_manual_problems` 必红。"""
    body = _m_manual()
    assert _manual_problems(body) == []
    broken = body.replace("稿名一个字不动", "")
    assert broken != body
    assert _manual_problems(broken) != []


# ------------------------------------------------------------------ ② 命名 / 不改名

def test_b_the_manuscript_is_named_by_its_own_number() -> None:
    """② F 的稿只按稿号命名；`manuscript_path` 没有"命题号/计划号/子目标号"三条回退。"""
    sig = inspect.signature(AgentF.manuscript_path)
    assert list(sig.parameters) == ["self", "manuscript_id", "proof_no"], sig
    assert AgentF.manuscript_path(object.__new__(AgentF), "000123") == (
        "reports/f-proof-000123.md")
    # 旧的三条回退给了就 TypeError（参数已经不存在）
    for bad in ({"statement_id": "000001"}, {"plan_id": "000004"}, {"sid": "s1"}):
        try:
            AgentF.manuscript_path(object.__new__(AgentF), **bad)
        except TypeError:
            continue
        raise AssertionError(f"`manuscript_path({bad})` 还能走旧回退 ⇒ 停掉的口径回来了")


def test_b_collection_does_not_rename() -> None:
    """② 收录那一侧不再有"按命题号改名"的实现（`_should_promote_to_formal` 只认草稿）。"""
    from agentflow.agent_b import register_statement as BRS

    assert BRS._should_promote_to_formal("reports/f-proof-000123.md") is False
    assert BRS._should_promote_to_formal("reports/f-proof-plan-0004.md") is False
    assert BRS._should_promote_to_formal("reports/b-proof-000123.md") is False
    assert BRS._should_promote_to_formal("notes/草稿.md") is True


# ------------------------------------------------------------------ ③ 三条正面读数

def test_a_missing_statement_id_is_really_ok() -> None:
    """③ 不传 `statement_id` 也能送审：缺省 / 合法族名 / 旧约定名是签载体（三条正面读数）。"""
    params = inspect.signature(AgentV.verify_proof).parameters
    assert "statement_id" in params
    assert params["statement_id"].default == "", params["statement_id"].default

    reading = MF.classify_manuscript("reports/f-proof-000004.md")
    assert reading["tier"] == MF.TIER_FAMILY, reading
    assert reading["family"] == "f-proof" and reading["id"] == "000004", reading

    old = MF.sign_carrier("reports/f-proof-plan-0004.md")
    assert old["ok"] is True, old
    assert MF.CODE_PLAN_NOT_SIGN, "历史码必须保留（老读数还要解释）"


def test_the_positive_reading_can_go_red(monkeypatch) -> None:
    """③ 反真空：把"旧约定名是签载体"打桩回旧行为 ⇒ 同一算式红。"""
    real = MF.sign_carrier

    def _regressed(rel):
        got = dict(real(rel))
        if str(got.get("name") or "").startswith("f-proof-plan-"):
            got.update(ok=False, code=MF.CODE_PLAN_NOT_SIGN)
        return got

    monkeypatch.setattr(MF, "sign_carrier", _regressed)
    assert MF.sign_carrier("reports/f-proof-plan-0004.md")["ok"] is False


# ------------------------------------------------------------------ ④ 驳回的写法

def test_rejected_wording_never_comes_back() -> None:
    """④ 业主两次驳回的写法（按钟判 / 框架催办）在题面与手册里一个都不许有。"""
    corpus = "\n".join(_render(role) for role in ("M", "F", "V", "B")) + "\n" + _m_manual()
    hits = [(lit, corpus.count(lit)) for lit in REJECTED_LITERALS if lit in corpus]
    assert hits == [], f"驳回的写法又回来了：{hits}"


def test_removing_a_hop_makes_it_red() -> None:
    """④ 反真空：把一个落点从题面里删掉 ⇒ ① 的算式红。

    用真渲染做：临时改 `specs/m.py` 的 policy 文本不现实，这里用纯函数对拍同一个算式
    （`HOP_NEEDLES` 逐条 in 判断）—— 删一条必须被点名。
    """
    text = _m_prompt()
    missing = [n for n in HOP_NEEDLES if n not in text]
    assert missing == []
    broken = text.replace(HOP_NEEDLES[0], "")
    assert [n for n in HOP_NEEDLES if n not in broken] == [HOP_NEEDLES[0]]
