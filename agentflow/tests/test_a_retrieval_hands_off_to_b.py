"""判据：A 把文献收进 literature 之后的下一步是无条件的 —— 派 B 的 run_once 整理。

业主指令（2026-11-20，逐字）：A拿好文献，只有接着派B才能转化成资产。这在A的协作里应该有写。

## 这一条守的是哪一处

真机现场（projects/lp-ball-13）：A 把 14 篇文献全 admit 进 literature（processed=false 的
待整理行留在盘上），B 0 趟、A 4 趟；上一趟 lp-ball-11 是同一形态（60 条 pending 收工）。
根因在 A 的协作面那句条件句：改前 specs/a.py 的 policy 写着「取回的这批如果要被引用成断言
（报告里「这条结论凭什么」要追到出处），派 B 整理」—— 条件句把派 B 变成了"看情况"，
于是 A 判断"还没到引用那一步"就继续往下走，而 literature 里的行不会自己变成概念与关系。

改法（这一条判据守的就是它）：把 A 的协作面改成一条无条件的下一步 ——
收进 literature（admitted > 0）之后，下一步就是派 B 的 run_once 整理；不派 B 等于这批
文献没转化成资产。引用闸那半句保留，但它只说明"引用要追出处"，不再是派 B 的前提。

## 判据（三条，全部对渲染产物断言，不读 specs/a.py 的源码串）

a. 渲染后的 A 提示词里，那条指令是无条件的：同一个条目里按顺序读得到
   收进 literature、admitted > 0、下一步就是派 B、run_once、没转化成资产；
   且任何一处派 B 的前置子句里没有如果 / 若 / 假如 / 才这类条件词；
b. 反真空：把条件句塞回去（boundary 与 policy 换回改前那两句）再渲染一遍 ⇒ a 必红，
   而且红的原因里点名那个条件句；
c. 正控：引用闸那半句仍在（不是删掉），语义仍是引用要追出处；
   负控：把引用闸那一条从真身上摘掉再渲染 ⇒ c 必红（删掉不许冒充改对）。

源码里有这句话不等于模型看得到它（段有没有注册、渲染口径、Lean 档位都会影响），
所以 a 与 c 都只读 agent_prompts.system_prompt 渲染出来的那一份文本。
"""
from __future__ import annotations

import dataclasses

import pytest

from agentflow import agent_prompts as AP
from agentflow.specs import a as spec_a
from agentflow.tools import build_registry

#: a 的指令骨架：按这个顺序出现在同一个条目里（顺序也是判据的一部分 ——
#: 先"收进 literature"、再"下一步派 B"，把它读成因果；顺序颠倒了就不是这一步）。
_PIPELINE: tuple[str, ...] = (
    "收进 `literature`",
    "`admitted > 0`",
    "下一步就是派 B",
    "`run_once`",
    "没转化成资产",
)

#: 条件词：出现在"派 B"之前（同一句里）⇒ 这条派 B 的指令是"看情况"的。
#: 才 也算：改前那一类写法不止「如果…」，还有「…才派 B」。
_GATE_MARKERS: tuple[str, ...] = ("如果", "若", "假如", "才")

#: 改前那两句（反真空用：逐字抄改前的 specs/a.py，用来证明判据抓得住它）。
_OLD_BOUNDARY = "检索完请 B 整理：抽概念、建关系是他的活。"
_OLD_POLICY = (
    "继续搜还是收手由预算与命中率决定：预算耗尽时必须收手并在结论里写明预算读数。"
    "检索的价值不在跑了几次，而在找到能改变判断的那几篇：命中后要写清它**支撑 / 推翻**了"
    "台账里的哪一条（`stmt:` / `rel:` 号，写进结论与 `note`）；只登记元数据不说影响的，"
    "不算有价值。取回的这批如果**要被引用成断言**（报告里「这条结论凭什么」要追到出处），"
    "**派 B 整理**：概念行与关系行（`relations` 的 `kind`/`quote`）；"
    "你自己不建概念网，也别把一批文献直接扔给下一环。"
)


def _render_a() -> str:
    """真的渲染一遍 A 的提示词（与生产同一条入口，零模型调用）。"""
    return AP.system_prompt("A", registry=build_registry().registry,
                            task="把这条链路走一遍", workspace_root="D:/x")


def _bullets(text: str) -> list[str]:
    """提示词里的条目行（边界与政策都渲染成 `- ` 开头的行）。"""
    return [line for line in text.splitlines() if line.startswith("- ")]


def _gate_prefixes(line: str, token: str = "派 B") -> list[str]:
    """每一处 token 所在那一句里、token 之前的那一段（用来找前置条件词）。

    句子切分用句号：同一句里出现条件词 + 派 B 就是"看情况"，而分号 / 逗号切不开
    「如果…，派 B」这种同一句里的前后件。用 find 而不是正则找 token：
    token 里的 `派 B` 没有正则元字符，但 find 更直白地说明我们是在数出现位置。
    """
    out: list[str] = []
    pos = 0
    while True:
        found = line.find(token, pos)
        if found < 0:
            return out
        start = line.rfind("。", 0, found) + 1
        out.append(line[start:found])
        pos = found + len(token)


def _pipeline_problems(text: str) -> list[str]:
    """a 的判据本体：返回问题清单（空 = 绿）。纯函数，喂任何一份渲染文本都能判。"""
    problems: list[str] = []
    bullets = _bullets(text)
    # a-1：必须有一条把整条流水线写全（顺序也要对）。
    complete = []
    for line in bullets:
        spots = [line.find(needle) for needle in _PIPELINE]
        if all(spot >= 0 for spot in spots) and spots == sorted(spots):
            complete.append(line)
    if not complete:
        problems.append(
            "渲染后的 A 提示词里没有一条把「收进 literature（admitted > 0）→ 下一步派 B 的 "
            "run_once 整理 → 不派 B = 这批文献没转化成资产」写全的条目 ⇒ 派 B 仍然不是"
            "无条件的下一步（缺的那几段：" + " / ".join(_PIPELINE) + "）")
    # a-2：任何一处派 B 都不许被条件词前置（这就是改前那句的形态）。
    for line in bullets:
        for prefix in _gate_prefixes(line):
            bad = [marker for marker in _GATE_MARKERS if marker in prefix]
            if bad:
                problems.append(
                    f"这条派 B 的指令被条件句前置（{bad}）⇒ 模型会读成「看情况」而不是"
                    f"下一步：{line}")
    return problems


def _citation_gate_problems(text: str) -> list[str]:
    """c 的判据本体：引用闸那半句还在不在、语义还是不是引用要追出处。"""
    gate = [line for line in _bullets(text) if "引用闸" in line]
    if not gate:
        return ["渲染后的 A 提示词里没有「引用闸」那一条 —— 引用要追出处那半句被删了"
                "（那不是改成无条件，是把闸拆了）"]
    problems: list[str] = []
    for needle in ("这条结论凭什么", "追到出处", "`kind`", "`quote`",
                   "不是派 B 的前提"):
        if not any(needle in line for line in gate):
            problems.append(f"引用闸那一条里读不到「{needle}」⇒ 语义不再是"
                            "「引用要追出处」，或它又被写成了派 B 的前提")
    return problems


# ============================================================ a 正控：无条件的下一步
def test_a_admits_then_summoning_b_is_the_next_step_not_a_conditional() -> None:
    """a：渲染后的 A 提示词里，这条指令是无条件的（不含以引用为前提的条件句）。"""
    # 判据读的是真身：渲染用的那份 brief 就是 specs/a.py 的 SPEC.brief（不是一份拷贝）。
    assert AP.ROLE_BRIEFS["A"] is spec_a.SPEC.brief, (
        "渲染用的 A 的 brief 不是 specs/a.py::SPEC.brief —— 这条判据读的与声明的不是同一个对象")

    text = _render_a()
    problems = _pipeline_problems(text)
    assert problems == [], "\n".join(problems)
    # 正控的反面：改前那句条件句一个字也不许留在渲染产物里。
    assert "如果**要被引用成断言**" not in text, (
        "渲染后的 A 提示词里还留着改前那句条件句 ⇒ 派 B 仍然不是无条件的一步")


# ============================================================ b 反真空：塞回条件句 ⇒ 必红
def test_b_putting_the_conditional_back_turns_the_criterion_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """b：把条件句塞回去（改前那两句）⇒ a 必红，且点名那个条件句。"""
    brief = AP.ROLE_BRIEFS["A"]
    idx = next(i for i, entry in enumerate(brief.policy) if "继续搜还是收手" in entry)
    reverted = dataclasses.replace(
        brief,
        boundary=(_OLD_BOUNDARY,) + tuple(brief.boundary[1:]),
        policy=tuple(entry if j != idx else _OLD_POLICY
                     for j, entry in enumerate(brief.policy)),
    )
    # 同时改渲染源与声明：ROLE_BRIEFS 是渲染那一刻读的那一份（brief_sections），
    # SPEC 是权限面的真身；只改一处会留下"判据读的与声明的不是同一个"的假象。
    monkeypatch.setitem(AP.ROLE_BRIEFS, "A", reverted)
    monkeypatch.setattr(spec_a, "SPEC", dataclasses.replace(spec_a.SPEC, brief=reverted))

    problems = _pipeline_problems(_render_a())
    assert problems, ("反真空失效：把改前那句条件句塞回去之后 a 仍然绿 ⇒ "
                      "它判的不是提示词里那条指令")
    assert any("如果" in one for one in problems), problems
    # 条件句本身要在问题里点出来（否则"必红"可能红在别的原因上）。
    assert any("要被引用成断言" in one or "派 B 整理" in one for one in problems), problems

    # 负控的负控：换回去 ⇒ 判据重新成立。
    monkeypatch.setitem(AP.ROLE_BRIEFS, "A", brief)
    monkeypatch.setattr(spec_a, "SPEC", dataclasses.replace(spec_a.SPEC, brief=brief))
    assert _pipeline_problems(_render_a()) == [], "换回去之后 a 仍然红"


# ============================================================ c 正控 + 负控：引用闸
def test_c_the_citation_gate_survives_and_is_not_a_precondition() -> None:
    """c：引用闸那半句仍在，语义仍是引用要追出处，且写明它不是派 B 的前提。"""
    text = _render_a()
    problems = _citation_gate_problems(text)
    assert problems == [], "\n".join(problems)


def test_c_deleting_the_citation_gate_turns_it_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """c 的负控：把引用闸整条摘掉 ⇒ c 必红（删掉不许冒充改对）。"""
    brief = AP.ROLE_BRIEFS["A"]
    kept = tuple(entry for entry in brief.policy if "引用闸" not in entry)
    assert len(kept) == len(brief.policy) - 1, (
        "夹具前提：引用闸真的装着在一条 policy 里（否则下面摘的是空）")
    monkeypatch.setitem(AP.ROLE_BRIEFS, "A", dataclasses.replace(brief, policy=kept))
    problems = _citation_gate_problems(_render_a())
    assert problems, "把引用闸那条摘掉之后 c 仍然绿 ⇒ 它没有守住那半句还在"


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
