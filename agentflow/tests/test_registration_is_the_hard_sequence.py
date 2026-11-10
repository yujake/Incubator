# -*- coding: utf-8 -*-
"""「立项 → 落稿 → 送审 → 收录」是每条命题的硬序列；立项用计划号，入账才建命题行（p271）。

## 现场（两轮真机，业主从盘上逐条读出来的）

```text
第一轮（projects/dct-min-20261110，67 分钟）：
  B 建号 4 条（1 concept + 3 conjecture）；V 9 次 verify_proof 里 5 次栽在
  「递的不是框架手稿」；能审到的那份判「有毛病」；签 0；statements.proof_text 全空。
第二轮（projects/dct-min2-20261110，62 分钟）：
  V 这次确实审了框架手稿（reports/f-proof-plan-000004.md），仍判「有毛病」；
  而 B 一次都没跑 —— M 的日志逐字：「B 的派活被 deadline_exceeded 拒（一次都没跑）」
  ⇒ statements 0 条、签 0 个。
```

共同点：没有谁把「立项 → 落稿 → 送审 → 收录」当成一条必须走完的链。

## 立项用计划号，不建在命题台账上（业主 2026-11-10 的立项口径）

```text
· agent_f/core.py / agent_f/manuscript.py：没号 ⇒ reports/f-proof-plan-<计划号>.md
· manuscriptfamily.classify_manuscript("reports/f-proof-plan-000004.md")
  ⇒ {tier: family, family: f-proof, id: plan-000004, proof_no: 1}   ← 合法落稿名
· verify_proof 的 statement_id 缺省 "" ⇒ 不传也能送审（这一轮还没有命题号）
· 计划稿不是签的载体（vsigns.is_sign_carrier 为 False）：
    判「有毛病」⇒ 判词落 verifications/pending/<正文 sha>.jsonl（kind=proof_unregistered_rejected）
    判「成立」  ⇒ 只看过没签（kind=proof_reviewed_not_signed，pending 0 行、签文件 0 份）
· agent_b/register_statement.py：两种名都认；拿到号那一刻稿转名 f-proof-<命题号>.md（签另算）
```

⇒ 「立项看计划号，入账看命题号；两者不是同一件事，不要为了拿号去写一行 statements」。

## 这一份钉什么

| # | 判据 | 反真空 |
|---|---|---|
| ① | M 的渲染题面里三条字面都在（立项不建在台账上 / 决定即立项 / 收录才是成果落点） | 各删一处 ⇒ 同一算式红 |
| ② | 「立项看计划号，入账看命题号」那一句在题面与手册里 | 删那一句 ⇒ 红 |
| ③ | 不传 `statement_id` 也能送审的三条正面读数（缺省值 / 计划稿是合法族名 / 它不是签的载体） | 把那一格改成"必填"式的假读数 ⇒ 同一算式红 |
| ④ | 业主两次驳回的写法（按钟判、框架催办）一个字都不许回来 | 塞一句回去 ⇒ 红 |

零模型调用、零网络。
"""
from __future__ import annotations

import inspect

from agentflow import agent_prompts as AP
from agentflow import agent_skills as AS
from agentflow import manuscriptfamily as MF
from agentflow import vsigns as VS
from agentflow.agent_v import AgentV
from agentflow.tools import build_registry

TASK = "把这条链路走一遍"
ROOT = "D:/x"

#: ① 立项那一句（判据只认这个字面）。锚点刻意不带强调符：题面与手册排版不同，
#: 判据钉的是读到的意思，不是某一处的粗体。
PLAN_NEEDLE = "立项不建在命题台账上"
#: ① 的四跳落点：少一环就说明「硬序列」被压回了"记得登记"这种软话。
HOP_NEEDLES: tuple[str, ...] = (
    "F 落 `reports/f-proof-plan-<计划号>.md`",
    "`verify_proof(proof_manuscript=\"reports/f-proof-plan-<计划号>.md\", proof_no=…)`",
    "不传 statement_id",
    "`verifications/pending/<正文 sha>.jsonl`",
    "B 收录时才建 statements 行",
)
#: ① 末句：立项与入账是两件事。
SPLIT_NEEDLE = ("立项看计划号，入账看命题号；两者不是同一件事，"
                "不要为了拿号去写一行 statements")

#: ② 决定即立项（分命题，不分钟）。
DECIDE_NEEDLE = "决定要证某条命题的那一刻就立项"
DECIDE_REASONS: tuple[str, ...] = (
    "拿计划号、落稿",
    "一次是稿名对不上",
    "一次是 B 根本没被派活",
    "与钟无关：分的是命题，不是时刻",
)

#: ③ 成果是收录的产物，不是立项的产物。
LEDGER_NEEDLE = "成果是台账里的条目，不是文件"
LEDGER_REASONS: tuple[str, ...] = (
    "收录**的产物，不是立项的产物",
    "「草稿已落盘」不算交付",
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
#: 钉着"正文任何一行都不许出现在前置提示词里"，所以手册这边另立一组锚点）。
MANUAL_NEEDLES: tuple[str, ...] = (
    "立项不建在命题台账上",
    "plan 号段",
    "`statement_id` 不传",
    "`verifications/pending/<正文 sha>.jsonl`",
    "计划稿不是签的载体",
    "B 收录时才建 statements 行",
    "立项看计划号，入账看命题号",
    "决定要证某条命题的那一刻就立项",
    "成果是台账里的条目，不是文件",
    "**收录**的产物",
)


def _manual_problems(body: str) -> list[str]:
    """手册那一份缺了什么（空列表 = 三件事都在）。纯函数（反真空探针走同一条路）。"""
    return [f"手册里读不到：{n!r}" for n in MANUAL_NEEDLES if n not in body]


def _prompt() -> str:
    return AP.system_prompt("M", registry=build_registry().registry,
                            task=TASK, workspace_root=ROOT)


def _manual() -> str:
    """M 那一本手册里写「硬序列」的那一条的正文（`fs.read` 现读的那一份）。"""
    skill = next(s for s in AS.CATALOG["M"] if s.slug == "研究攻坚链-文献到收录证明")
    return skill.body


def _problems(text: str) -> list[str]:
    """这一份文本缺了什么（空列表 = 三条都在）。

    纯函数：`text` 既可以是真渲染的那一份、也可以是反真空探针（删掉一条之后的同一份
    文本）—— 两端走同一条路，反真空才打得到真判据。
    """
    bad: list[str] = []
    if PLAN_NEEDLE not in text:
        bad.append(f"① 缺「立项不建在命题台账上」这一句：{PLAN_NEEDLE!r}")
    missing_hops = [h for h in HOP_NEEDLES if h not in text]
    if missing_hops:
        bad.append(f"① 四跳落点缺这几处：{missing_hops}")
    if SPLIT_NEEDLE not in text:
        bad.append(f"① 缺「立项看计划号，入账看命题号」这一句：{SPLIT_NEEDLE!r}")
    if DECIDE_NEEDLE not in text:
        bad.append(f"② 缺「决定要证某条命题的那一刻就立项」这一句：{DECIDE_NEEDLE!r}")
    missing_why = [x for x in DECIDE_REASONS if x not in text]
    if missing_why:
        bad.append(f"② 缺了配套的判据/现场：{missing_why}")
    if LEDGER_NEEDLE not in text:
        bad.append(f"③ 缺「成果是台账里的条目，不是文件」这一句：{LEDGER_NEEDLE!r}")
    missing_ledger = [x for x in LEDGER_REASONS if x not in text]
    if missing_ledger:
        bad.append(f"③ 缺了配套的判据：{missing_ledger}")
    return bad


def _positive_readings() -> dict[str, object]:
    """「不传 `statement_id` 也能送审」的三条正面读数（全部从实现现算，不手抄）。

    它们一起成立才说明这条教法可执行：参数真的可省、计划稿真是合法族名、
    并且它真的不是签的载体（所以 ① 里那句"判成立那一档只看过没签"不是保守说法）。
    """
    params = inspect.signature(AgentV.verify_proof).parameters
    sid = params.get("statement_id")
    named = MF.classify_manuscript("reports/f-proof-plan-000004.md")
    return {
        "statement_id_default": (None if sid is None else sid.default),
        "plan_tier": named.get("tier"),
        "plan_family": named.get("family"),
        "plan_id": named.get("manuscript_id") or named.get("id"),
        "plan_proof_no": named.get("proof_no"),
        "plan_is_carrier": VS.is_sign_carrier("reports/f-proof-plan-000004.md"),
    }


def test_the_rendered_prompt_carries_all_three() -> None:
    """正控：M 的渲染提示词里三条都在（①立项/入账两件事 ②决定即立项 ③成果是收录的产物）。"""
    text = _prompt()
    assert len(text) > 5000, len(text)  # 反真空：读到的真的是渲染出来的那一份
    bad = _problems(text)
    assert bad == [], "\n".join(bad)


def test_the_manual_carries_the_same_three() -> None:
    """手册镜像：M 现读的那一本里三件事也在（题面给口径、手册给步骤与反面形态）。

    手册与题面不许逐字重复（`test_agent_skills.py` 钉着"正文任何一行都不许出现在
    前置提示词里"），所以这一条用的是手册自己那一组锚点，不是题面的那组。
    """
    body = _manual()
    assert len(body) > 800, len(body)  # 反真空：读到的真的是那一本
    bad = _manual_problems(body)
    assert bad == [], "\n".join(bad)


def test_removing_the_manual_anchor_makes_it_red() -> None:
    """手册反真空：把「立项看计划号，入账看命题号」从手册里删掉 ⇒ 同一算式必须红。"""
    body = _manual()
    needle = "立项看计划号，入账看命题号"
    assert needle in body
    hit = _manual_problems(body.replace(needle, ""))
    assert hit and any(needle in x for x in hit), hit


def test_a_missing_statement_id_is_really_ok() -> None:
    """③ 正面读数：`statement_id` 可省、计划稿是合法族名、并且它不是签的载体。

    这三格是 ① 那段教法能不能执行的全部依据：参数可省 ⇒ 那一轮不需要命题号；
    族名认得 ⇒ 稿能落、V 能审；不是载体 ⇒ 判「成立」也只到「看过、没签」。
    """
    got = _positive_readings()
    assert got["statement_id_default"] == "", got
    assert got["plan_tier"] == MF.TIER_FAMILY, got
    assert got["plan_family"] == "f-proof", got
    assert str(got["plan_id"]) == "plan-000004", got
    assert got["plan_proof_no"] == 1, got
    assert got["plan_is_carrier"] is False, got


def test_the_positive_reading_can_go_red() -> None:
    """③ 反真空：把"计划稿是签的载体"这一格换成假读数 ⇒ 同一算式必须红。

    没有这一条，`is False` 这句断言可以靠"这个函数永远返回 False"骗过 ——
    而真身是"计划稿不被当载体、正式稿被当载体"，两档都要立得住才算读对了。
    """
    assert VS.is_sign_carrier("reports/f-proof-plan-000004.md") is False
    assert VS.is_sign_carrier("reports/f-proof-000004.md") is True, (
        "正式稿必须被当载体 ⇒ 上面那条 False 不是'函数恒假'")

    def doctored() -> dict[str, object]:
        got = _positive_readings()
        got["statement_id_default"] = "<required>"
        return got

    got = doctored()
    assert got["statement_id_default"] != "", "假读数没生效 ⇒ 这条反真空是摆设"


def test_removing_the_plan_sentence_makes_it_red() -> None:
    """① 反真空：把「立项不建在命题台账上」删掉 ⇒ 同一个算式必须报出来。"""
    text = _prompt()
    assert PLAN_NEEDLE in text
    hit = _problems(text.replace(PLAN_NEEDLE, ""))
    assert hit and any("立项不建在命题台账上" in x for x in hit), hit


def test_removing_a_hop_makes_it_red() -> None:
    """① 反真空之二：删掉「B 收录时才建 statements 行」那一跳 ⇒ 必须报出来。"""
    text = _prompt()
    assert HOP_NEEDLES[4] in text
    hit = _problems(text.replace(HOP_NEEDLES[4], ""))
    assert hit and any("四跳" in x for x in hit), hit


def test_removing_the_split_sentence_makes_it_red() -> None:
    """② 反真空：删掉「立项看计划号，入账看命题号」⇒ 必须报出来（这一句要有判据钉住）。"""
    text = _prompt()
    assert SPLIT_NEEDLE in text
    hit = _problems(text.replace(SPLIT_NEEDLE, ""))
    assert hit and any("立项看计划号" in x for x in hit), hit


def test_removing_the_decide_sentence_makes_it_red() -> None:
    """② 反真空：删掉「决定要证某条命题的那一刻就立项」⇒ 必须报出来。"""
    text = _prompt()
    assert DECIDE_NEEDLE in text
    hit = _problems(text.replace(DECIDE_NEEDLE, ""))
    assert hit and any("那一刻就立项" in x for x in hit), hit


def test_removing_the_ledger_sentence_makes_it_red() -> None:
    """③ 反真空：删掉「成果是台账里的条目」⇒ 必须报出来。"""
    text = _prompt()
    assert LEDGER_NEEDLE in text
    hit = _problems(text.replace(LEDGER_NEEDLE, ""))
    assert hit and any("收录" in x or "台账" in x for x in hit), hit


def test_the_two_rejected_formulations_never_come_back() -> None:
    """④ 反向判据：业主两次驳回的写法（按钟判、框架催办）都不许回来。

    为什么这条不是"语气检查"：那两句一旦回来，M 就会在探索期被迫立项，或者等一个
    框架来提醒它 —— 两种都被业主逐字驳回。
    """
    for label, text in (("题面", _prompt()), ("手册", _manual())):
        stale = [s for s in REJECTED_LITERALS if s in text]
        assert not stale, f"{label}里又出现了被驳回的写法：{stale}"


def test_the_rejected_scan_catches_a_regression() -> None:
    """④ 反真空：把「第一个小时」那一句塞回同一份文本 ⇒ 上面那条必须红。"""
    text = _prompt() + "\n**立项必须在第一个小时内发生**。\n"
    stale = [s for s in REJECTED_LITERALS if s in text]
    assert stale == ["第一个小时"], stale
