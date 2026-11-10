# -*- coding: utf-8 -*-
"""把三处「有实现、提示词 0 命中」教进去，并删掉两处「教了做不到」（审计 171 + 172）。

三处是同一种形态：实现早已在盘上，而模型的可见面一个字都没提 ——
它不会做错什么，它只是永远不会去做。

| # | 实现（真身） | 提示词面改前 |
|---|---|---|
| u1 | `closing.statements_unsigned_reading` + `closing` 的 blocker（`machine_pass` 还要 `not blockers`）；`statementabandon` 的 `abandoned@<ISO>@<理由>`；`vreceipts.close_resubmits_for` | M/D/F 提示词里 `statements_unsigned` / `abandoned` 各 0 次；M 那一格还写着已作废的「0 不是失败，静默的 0 才是」 |
| u2 | `vreceipts` 的重送义务板项：幂等键 `v-resubmit@<命题号>@<proof_sha256>`、`expects="work"`、关闭条件是更新的干净「成立」行（`settle_resubmitted`），不是 ack | `specs/f.py` 与 `_f_skills()` 全文 `resubmit` 0 次 |
| u3 | `verify.verify_proof` 交出去的是 `proof_manuscript` / `proof_no` / `readonly_facts` 三格（2026-11-10 第二刀之后没有 `statement_id`：命题号由 B 收录时现取） | F 只说"唤起 V 的 verify_proof，把 proof_text 与只读读数交过去" —— 一个真键名都没写 |
| u4 | 手稿由 `agent_f/manuscript.py::proof_manuscript` 写、`## 依赖` 由 `dependency_rows` 按 `steps[].cites` 渲染；`fs` 保留表拒 F 写 `f-proof-*` | F 教「手稿里必须有一节 `## 依赖` ……引用一条就写进这一节」 |
| u5 | 项目级 `reports/RESEARCH.md` 是 D 的研究手稿（七节、先读后改；2026-11-04 的补充裁定把它从"保留面"翻回既有交付物）；自己写的 `## 证明` 节才被 `fs` 拒 | D 教「`RESEARCH.md` 是保留面、别手写」 |

每条判据都同时核渲染后的提示词与该角色的手册：前者是每一趟真正读到的，后者是它按需翻的
那一本；只补一处等于换个地方继续不教。

反真空：每条都先断言这一份提示词/手册真的非空、且带着同段的旧内容或旧数量
（不是"文件里没这个词"就能变绿）。
"""
from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import agent_prompts as AP   # noqa: E402
from agentflow import agent_skills as AL    # noqa: E402
from agentflow.tools import build_registry  # noqa: E402

#: 与 `tests/test_f_reads_vs_two_states.py` 同一口径的注册表（离线、不建工作区）。
_REG = build_registry().registry


def _prompt(role: str) -> str:
    return AP.system_prompt(role, registry=_REG)


def _manual(role: str) -> str:
    """该角色手册的全部文本（slug / 标题 / 索引两格 / 正文）。"""
    parts: list[str] = []
    for skill in AL.CATALOG[role]:
        parts.append(f"### {skill.slug}")
        for field in ("title", "summary", "when", "body"):
            parts.append(str(getattr(skill, field)))
    return "\n".join(parts)


#: 收工门那一格的名字（`closing` 的 blocker 码前缀）。
UNSIGNED = "statements_unsigned"
#: 放弃标记的前缀（`statementabandon.ABANDON_MARKER`）。
ABANDON = "abandoned@"
#: 重送义务板项的幂等键前缀（`vreceipts.RESUBMIT_PREFIX`）。
RESUBMIT = "v-resubmit@"
#: `expects` 的取值（`schema.ITEM_EXPECTS`）：work 项只能 `completed` / `expired` 收口。
WORK = "expects=work"


def test_every_research_side_prompt_says_how_an_unsigned_statement_ends() -> None:
    """u1：M / D / F 的提示词与手册都要说清「未签＝blocker」与那两条出路。"""
    bad: list[str] = []
    for role in ("M", "D", "F"):
        for label, text in (("prompt", _prompt(role)), ("manual", _manual(role))):
            if len(text) < 500:
                bad.append(f"{role}/{label} 只有 {len(text)} 字 —— 这份面是空的，判据失去对象")
                continue
            for needle in (UNSIGNED, ABANDON, RESUBMIT):
                if needle not in text:
                    bad.append(f"{role}/{label} 没提 {needle!r}")
            # 两条出路都要点到（只写"未签是 blocker"不给路，等于把模型逼去乱试）。
            if "重新送" not in text and "重送" not in text:
                bad.append(f"{role}/{label} 没说「重送 V」这条出路")
            if "放弃" not in text:
                bad.append(f"{role}/{label} 没说「明确放弃」这条出路")
    assert not bad, "未签闭环没被教全：\n  " + "\n  ".join(bad)


def test_m_no_longer_teaches_that_a_silent_zero_is_not_a_failure() -> None:
    """u1 的反面：M 那一句已作废的口径必须删掉（业主 2026-11-01 的裁定把它翻了）。"""
    text = _prompt("M")
    # 反真空：这一份提示词确实带着同段的那一条政策（否则"没有那句"可能只是没这一段）。
    assert "要有人走查就派 D 去办" in text, "M 的提示词里没有走查那一段 ⇒ 这条判据没有对象"
    assert "0 不是失败" not in text, (
        "M 的提示词里还留着「0 不是失败」—— 收工门现在把「既无 V 签也未放弃」判成 blocker，"
        "这句话会把模型推向「静默地 0 也合法」")
    assert "静默的 0" not in text, "M 的提示词里还留着「静默的 0 才是」那句"


def test_f_knows_the_resubmit_item_is_not_an_ack() -> None:
    """u2：`v-resubmit@` 是 work 项，ack 关不掉；不关它会挡销号与收工。"""
    bad: list[str] = []
    for label, text in (("prompt", _prompt("F")), ("manual", _manual("F"))):
        if len(text) < 500:
            bad.append(f"F/{label} 只有 {len(text)} 字 —— 这份面是空的")
            continue
        if "v-resubmit@" not in text:
            bad.append(f"F/{label} 没提 v-resubmit@ 这条板项")
        if WORK not in text:
            bad.append(f"F/{label} 没说它是 {WORK}（ack 关不掉）")
        if "ack" not in text:
            bad.append(f"F/{label} 没把「ack 关不掉」与「什么才关得掉」对照着写")
        if "销号" not in text and "收工" not in text:
            bad.append(f"F/{label} 没说它会挡销号/收工（不说后果，模型不会去收口）")
    assert not bad, "重送义务没被教全：\n  " + "\n  ".join(bad)


def test_f_knows_verify_proof_requires_statement_id() -> None:
    """u3（2026-11-10 第二刀改写）：F 交出去的那三个真键名写全，`statement_id` 不再是要交的。

    ## 为什么口径翻了（强度只升不降）

    改前这一条钉的是「`statement_id` 是必填」——那是 2026-11-10 业主裁定要撤掉的东西：
    「撤去所有有关对某个给定命题号进行攻坚或写证明的逻辑」。现在钉三件事：
    ① 三个真键名（`proof_manuscript` / `proof_no` / `readonly_facts`）一个不许少；
    ② 不许把"在册后给号"教成 F 的义务（两句改前的原话逐字禁掉）；
    ③ 反真空：把改前那句原话喂进同一个读法 ⇒ 必须报红。
    """
    old = ("`statement_id`（在册后给这条命题的号；还没在册就不给，"
           "空号 = 还没在册 —— **没号也能签**")
    for label, text in (("prompt", _prompt("F")), ("manual", _manual("F"))):
        bad = _verify_key_problems(text, old=old)
        assert not bad, f"F/{label} 的送审口径不对：\n  " + "\n  ".join(bad)
    # 反真空：旧口径喂进同一个读法必须红（判据不是橡皮图章）
    assert _verify_key_problems(old, old=old), "旧口径居然全绿 ⇒ 这条判据是空的"


def _verify_key_problems(text: str, *, old: tuple[str, ...] | str = "") -> list[str]:
    """F 的送审口径：三个真键名都在、且改前那两句"要交号"的原话都不在。"""
    bad: list[str] = []
    if "verify_proof" not in text:
        bad.append("连 verify_proof 都没提 ⇒ 判据没有对象")
        return bad
    for needle in ("proof_manuscript", "proof_no", "readonly_facts"):
        if needle not in text:
            bad.append(f"没写 {needle!r}（这三个键名是实现里的真名）")
    olds = (old,) if isinstance(old, str) else tuple(old or ())
    for stale in (*olds, "`statement_id`（在册后给这条命题的号", "在册后再加 `statement_id`"):
        if stale and stale in text:
            bad.append(f"还在教「{stale}」—— 命题号不是 F 这一趟要交的东西")
    return bad


def test_f_is_taught_to_hand_cites_not_the_dependency_section() -> None:
    """u4：`## 依赖` 那一节由框架按 `cites` 渲染，F 手写会被保留表拒。"""
    bad: list[str] = []
    for label, text in (("prompt", _prompt("F")), ("manual", _manual("F"))):
        for stale in ("手稿里必须有一节标题逐字为", "引用一条就写进这一节"):
            if stale in text:
                bad.append(f"F/{label} 还在教「{stale}」—— 那一节是框架渲染的")
        if "cites" not in text:
            bad.append(f"F/{label} 没说「引用写进 cites」")
        if "reserved_framework_artifact" not in text:
            bad.append(f"F/{label} 没说手写 `reports/f-proof-*` 会被 `reserved_framework_artifact` 拒")
    assert not bad, "F 的依赖面仍教了做不到的写法：\n  " + "\n  ".join(bad)


def test_d_is_taught_the_research_manuscript_and_that_proofs_belong_to_f() -> None:
    """u5：`reports/RESEARCH.md` 是 D 的研究手稿（先读后改、收录 F/E 成果）；禁区是自写证明。

    2026-11-04 的补充裁定把 u5 的口径翻了过来：改前（2026-11-01 审计 D-08）D 被教
    「`reports/RESEARCH.md` 是框架保留面、别手写」；现在它是 D 的既有交付物
    （收录 F 的证明手稿与 E 的实验成果，交 B 时随稿带携带单），所以：
      ① 要教"七节 / 先读后改"，不许再把"保留面 / 别手写"教回去；
      ② 禁区改成"自己新写 `## 证明` 节"（`reserved_framework_artifact` 拒的那一档）；
      ③ 记忆的另一处落点 `research.write_note` 仍在。
    """
    bad: list[str] = []
    for label, text in (("prompt", _prompt("D")), ("manual", _manual("D"))):
        if "先读后改" not in text:
            bad.append(f"D/{label} 没教「`reports/RESEARCH.md` 先读后改」")
        if "research.write_note" not in text:
            bad.append(f"D/{label} 没点名另一处记忆落点 `research.write_note`")
        if "## 证明" not in text:
            bad.append(f"D/{label} 没说清禁区是「自己新写 `## 证明` 节」")
        if "reserved_framework_artifact" not in text:
            bad.append(f"D/{label} 没说那一档会被 `reserved_framework_artifact` 拒")
        for stale in ("RESEARCH.md 是框架保留面", "别去手写它"):
            if stale in text:
                bad.append(f"D/{label} 把 2026-11-04 已翻转的旧口径教回来了：{stale!r}")
    assert not bad, "D 的研究手稿落点与证明禁区没教对：\n  " + "\n  ".join(bad)
