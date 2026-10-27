# -*- coding: utf-8 -*-
"""模板里不许出现具体台账号（Q25）—— 2026-10-26。

台账号（`t-` 加六位数字）是运行期事实：它由 `tasks` 表分配，属于某一次运行。静态模板里
写一个具体号（改前有 5 处 `t-000003`）有两个后果：

| 后果 | 读数 |
|---|---|
| 读到的人会以为那个号在这一趟也成立（它不在：号跟着每一次调用走） | 没有读数会报 |
| 它会与判据自己的素材撞车 | `test_children_and_parent_are_visible.py` 的 `test_the_two_cells_are_the_only_source_of_those_ids` 变红，而它守的那件事（父/子两格是那些编号的唯一来源）一个字都没坏 |

改法（只动文案）：具体号一律换成本文件自己早就在用的占位形 `t-NNNNNN`
（`_COLLAB_NAMES_TEXT` 里逐字写着「台账号（`t-NNNNNN`）：框架分配的，一生不变」）——
既说清"它长什么样"，又不冒充任何一次运行。

范围（判据照这条边界写）：本单只钉 `agent_prompts.py` 自己写的那几段。M 那一格还有
9 处具体号来自两个禁改区（`specs/m.py` 的 policy 与 `conductor_tools.py` 的
`conductor.guide` 摘要），本单一个字都不动它们 —— 所以：

1. 模板段命中 0（改前红：十一格各 4–5 处 `t-000003`）；
2. 残留逐条钉住：每一条都要说清"哪一段、哪个文件:行、逐字是什么"，并且能区分
   "已知那几处"与"新冒出来的一处"—— 后者必红，残留不是免死金牌；
3. 运行期真注入的地方（`task_id` / `parent_task_id`）不受影响（正控）；
4. 把具体号塞回模板 ⇒ 第 1 条必红（反真空）。

2026-10-26（本单的收尾）：那 9 处已经由业主许可后落地（`specs/m.py` 三处与
`conductor.guide` 摘要一处，具体号一律换成占位形 `t-NNNNNN`）⇒ `_RESIDUAL` 归零。
归零之后第 2 条仍然守着：新写进 `specs/*` 或工具摘要的具体号照样会被它逮住
（那时 `want` 是空的，任何一处都是"新冒出来的"）。第 5 条钉住"归零不是靠删话"。

顺带钉一句"不许为了绿而删话"：十一格渲染里「绝对编号链」那句必须还在（它由
`specs/*.py` 的 boundary 供给，本单不动），且本单改过的那句仍写着「名册名（如 `D1`）、
绝对编号」—— 编号这件事没有被删成空话。
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

import pytest

from agentflow import agent_prompts as AP
from agentflow import schema as S
from agentflow.promptkit import Scope
from agentflow.tools import ToolRegistry, build_registry

#: 十一格：可被召唤的 A–H / V / L 加主控。
ALL_ROLES: tuple[str, ...] = tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)

#: 判据里那一次 run 的固定输入（确定性）。
TASK = "把这条链路走一遍"
ROOT = "D:/x"

#: 具体台账号的形。占位形 `t-NNNNNN` 不是它（N 不是数字）—— 这条正则是本单的判据本身。
_ID = re.compile(r"t-\d{6}")

#: 不是模板写的那两族段：文本由禁改区的模块供给。
#:   - `ROLE_POLICY`：`specs/*.py` 的 `policy`（本单只有 M 那一格有具体号）；
#:   - `TOOL_nn`：工具面的摘要行（只有 M 的工具面有 `conductor.guide`）。
#: 这两处都在禁改区（`specs/*` 与 `tools/*`），所以判据把它们排除在"模板"之外，
#: 并把它们贡献的残留逐条钉在 `_RESIDUAL` 里。
_FOREIGN_SECTIONS: tuple[str, ...] = ("ROLE_POLICY",)
_FOREIGN_PREFIX = "TOOL_"

#: 禁改区残留的逐条清单（本单一个字都不动它们；判据只把"已知"钉住）。
#:
#: 形状：`{角色: ((段名, 文件:行, 逐字样, 这段逐字样在这一段里出现几次), ...)}`。
#: 号不另抄一份 —— 每个逐字样里的具体号由 `_ID` 现扫，于是"换了个号"与"改了这句话"
#: 都会红（前者让实际集合多一项，后者让逐字样对不上）。
#:
#: 2026-10-26 归零：那 9 处（`src/agentflow/specs/m.py` 的 policy 三处 +
#: `src/agentflow/tools/conductor_tools.py` 的 `conductor.guide` 摘要一处）已在业主
#: 许可后换成占位形 `t-NNNNNN`，所以这张表是空的。空表不是把这条判据关掉：
#: `want` 为空 ⇒ 任何一处具体号都是"新冒出来的"（第 ② 条照旧红），而第 ⑤ 条钉住
#: "归零不是靠删话"（那四句仍逐字在，只是号成了占位形）。
_RESIDUAL: dict[str, tuple[tuple[str, str, str, int], ...]] = {}


@pytest.fixture()
def registry() -> ToolRegistry:
    """不带工作区的注册表（与本目录其余提示词判据同一档：没有 fs 工具）。"""
    return build_registry().registry


def _kw(registry: ToolRegistry, **kw: Any) -> dict[str, Any]:
    kw.setdefault("registry", registry)
    kw.setdefault("task", TASK)
    kw.setdefault("workspace_root", ROOT)
    return kw


def _rendered_sections(role: str, registry: ToolRegistry) -> list[tuple[str, str]]:
    """这一次装配里每一段的（段名, 渲染后的文本）。

    用 `assemble()` 而不是读私有字典：段的合并与遮蔽（全局层 + 角色作用域）只有
    装配那一处口径，判据不该自带第二份。注意这里刻意不做变量插值 —— 这正是
    "静态模板"的定义：`{{task_id}}` 那一类运行期事实还没进到文本里来。
    """
    pr = AP.role_prompt_registry(role, **_kw(registry))
    asm = pr.assemble(Scope(role=role))
    return [(sec.name, sec.render(asm.scope)) for sec in asm.sections]


def _is_foreign(name: str) -> bool:
    """这一段是不是禁改区供给的（`ROLE_POLICY` 与 `TOOL_nn`）。"""
    return name in _FOREIGN_SECTIONS or name.startswith(_FOREIGN_PREFIX)


def _template_hits(role: str, registry: ToolRegistry) -> list[tuple[str, str]]:
    """模板段里出现具体台账号的地方：`[(段名, 号)]`（空列表 = 模板干净）。"""
    out: list[tuple[str, str]] = []
    for name, text in _rendered_sections(role, registry):
        if _is_foreign(name):
            continue
        out.extend((name, m.group(0)) for m in _ID.finditer(text))
    return out


def _foreign_hits(role: str, registry: ToolRegistry) -> list[tuple[str, str]]:
    """禁改区供给的那几段里的具体台账号：`[(段名, 号)]`。"""
    out: list[tuple[str, str]] = []
    for name, text in _rendered_sections(role, registry):
        if not _is_foreign(name):
            continue
        out.extend((name, m.group(0)) for m in _ID.finditer(text))
    return out


def _expected_residual(role: str) -> list[tuple[str, str]]:
    """从 `_RESIDUAL` 的逐字样现推出"该有哪些 (段, 号)"。"""
    out: list[tuple[str, str]] = []
    for section, _where, snippet, times in _RESIDUAL.get(role, ()):
        ids = _ID.findall(snippet)
        for _ in range(times):
            out.extend((section, task_id) for task_id in ids)
    return out


def _residual_drift(got: Counter, want: Counter) -> tuple[list[tuple[str, str]],
                                                          list[tuple[str, str]]]:
    """残留的实际读数与已知清单的差：`(新冒出来的一处, 清单里少了一处)`。

    分成两栏的理由：这两件事的处置方向相反 —— 多出来一处要么是本单该改的文案
    （落在模板段），要么是禁改区换了号（该同步 `_RESIDUAL`）；少了一处说明那处被清掉，
    这张表该跟着归零。折成一个"有没有残留"的布尔，两件事就都读不出来了。
    """
    return (sorted((got - want).elements()), sorted((want - got).elements()))


# --------------------------------------------------------------- ① 模板侧零命中

def test_no_concrete_task_id_is_written_into_the_template(registry: ToolRegistry):
    """判据 a′（改前红）：十一格的模板段里不许有具体台账号。

    改前逐格读数（`system_prompt` 现算）：A/B/D/E/F/G/H/V/L 各 5 处、C 4 处，
    全部是 `t-000003`（`HANDOFF_RULES` 1 + `LOOP_SHAPE_03` 2 + `LOOP_RULES` 1，
    有 `COLLAB_NAMES` 的角色再多 1）。它也是下面那条既有判据变红的直接原因：
    `test_children_and_parent_are_visible.py::test_the_two_cells_are_the_only_source_of_those_ids`
    造出来的子编号正好是 `t-000003`。
    """
    bad: list[str] = []
    for role in ALL_ROLES:
        for name, task_id in _template_hits(role, registry):
            bad.append(f"{role} / {name}: {task_id}")
    assert not bad, (
        "模板里写了具体台账号（它是运行期事实，不该进静态模板）：\n  "
        + "\n  ".join(bad)
        + "\n改法：换成本文件自己的占位形 `t-NNNNNN`（见 `_COLLAB_NAMES_TEXT` 里"
          "「台账号（`t-NNNNNN`）」那一句），或改成\"从读数里取\"的说法。"
    )


# --------------------------------------------------- ② 残留逐条钉住（不是免死金牌）

def test_the_residual_ids_are_pinned_one_by_one(registry: ToolRegistry):
    """判据 a″：十一格渲染里剩下的具体号，逐条对得上"已知那几处"（今天是零处）。

    两个方向都判：
      - 多出来的一处（哪个段、哪个号）⇒ 红：可能是新写进模板的（那就该改文案），
        也可能是 `specs/*` 或工具摘要里又写了一个具体号（那就该换成占位形）；
      - 少了一处（清单里该有却没有）⇒ 红：说明那处被清掉了，
        这张表该跟着归零，不然它就成了"反正有残留"的免死金牌。

    `_RESIDUAL` 在 2026-10-26 归零（那 9 处已换成占位形），所以今天 `want` 是空的 ——
    这一条因此变成"禁改区供给的那几段里一个具体号都不许有"。反真空在下面：
    先断言那几段真的被扫到了（否则"零命中"可能只是没东西可扫）。
    """
    bodies = {role: dict(_rendered_sections(role, registry)) for role in ALL_ROLES}
    # 反真空：禁改区供给的段必须真的在渲染里。少了它们，"零残留"是真空通过。
    foreign_sections = {role: sorted(n for n, _t in _rendered_sections(role, registry)
                                     if _is_foreign(n)) for role in ALL_ROLES}
    assert foreign_sections[S.CONDUCTOR_ROLE], (
        "M 那一格一个禁改区供给的段都没有（`ROLE_POLICY` / `TOOL_*`）⇒ "
        "这条判据今天没有可扫的东西，绿是假的")
    for role in ALL_ROLES:
        got = Counter(_foreign_hits(role, registry))
        want = Counter(_expected_residual(role))
        appeared, vanished = _residual_drift(got, want)
        assert not appeared and not vanished, (
            f"{role} 那一格的禁改区残留与清单不符：\n"
            f"  新冒出来的一处 = {appeared}\n"
            f"  清单里少了一处 = {vanished}\n"
            "改动点在 `specs/m.py` 或 `tools/conductor_tools.py` 时，"
            "请在同一批里同步 `_RESIDUAL` 与上面那条测试的 docstring；"
            "若多出来的落在模板段，那是本单要改的文案，不是这张表。"
            "（2026-10-26 之后这里该是零处：具体号一律写占位形 `t-NNNNNN`。）")
        for section, where, snippet, times in _RESIDUAL.get(role, ()):
            body = bodies[role].get(section, "")
            assert body.count(snippet) == times, (
                f"{role} / {section} 的那处逐字样对不上了（{where}）：期望出现 "
                f"{times} 次且逐字为 {snippet!r}，实际 {body.count(snippet)} 次。"
                "句子被改写过 ⇒ 请同步 `_RESIDUAL`；这一格是禁改区，改它要人审。")


def test_the_residual_reading_tells_a_new_id_from_a_known_one():
    """反负控：上面那条的读数能把"新冒出来的一处"与"已知那几处"分开。

    没有这一条，② 只要"清单非空"就绿（或者，清单归零之后，两条都只会报"少了一处"）。
    所以这里用一张自带的替身清单喂同一个读数函数（不从 `_RESIDUAL` 现取 ——
    那张表今天已经是空的，拿它当夹具会让这条判据跟着一起真空）：
    多一处必须只报"多出来"，少一处必须只报"少了一处"。
    """
    want = Counter({("ROLE_POLICY", "t-000012"): 2, ("TOOL_17", "t-000005"): 1})

    extra = Counter(want)
    extra[("ROLE_POLICY", "t-000009")] += 1
    appeared, vanished = _residual_drift(extra, want)
    assert appeared == [("ROLE_POLICY", "t-000009")], appeared
    assert vanished == [], vanished

    missing = Counter(want)
    missing[("TOOL_17", "t-000005")] -= 1
    appeared, vanished = _residual_drift(missing, want)
    assert appeared == [], appeared
    assert vanished == [("TOOL_17", "t-000005")], vanished


# --------------------------- ⑤ 归零不是靠删话：那四句还在，只是号成了占位形

#: 那四处（两处 policy 段落 + 一处 policy 段落里的链 + 工具摘要）换成占位形之后的逐字样。
PLACEHOLDER_SNIPPETS: tuple[tuple[str, str], ...] = (
    ("ROLE_POLICY", "`wait_for` 认三种写法（名册名如 `D1` / 绝对编号如 `t-NNNNNN` / `task:<号>`）"),
    ("ROLE_POLICY", "绝对编号链（`t-NNNNNN->t-NNNNNN->t-NNNNNN`）"),
    ("ROLE_POLICY", "只写链尾（`D1` 或 `t-NNNNNN`，由秘书按台账现算从你到它的那一条链）"),
    ("ROLE_POLICY", "绝对编号（形如 `t-NNNNNN`）"),
    ("TOOL_17", "写整条链（绝对编号 `t-NNNNNN->t-NNNNNN->t-NNNNNN`，或名册名"),
)


def test_the_cleaned_sentences_survive_with_the_placeholder(registry: ToolRegistry):
    """判据 e（反真空的另一半）：残留归零靠的是换号，不是把那几句删掉。

    没有这一条，"零命中"可以靠删话达成 —— 而"编号 / 链"这件事恰恰是模型必须知道的
    （`conductor.guide` 的 `to` 怎么写法、`wait_for` 认哪三种、手稿的收件人怎么写）。
    四句里每一句都必须逐字还在，且号已经是占位形（不是又换了一个具体号）。
    """
    body = dict(_rendered_sections(S.CONDUCTOR_ROLE, registry))
    for section, snippet in PLACEHOLDER_SNIPPETS:
        text = body.get(section, "")
        assert snippet in text, (
            f"M 那一格的 {section} 里读不到这句了：{snippet!r} —— "
            "归零不许靠删话（换号可以，话要留着）")
        assert not _ID.search(snippet), f"这一条逐字样里还带着具体号：{snippet!r}"


# ------------------------------------------- ③ 不许为了绿而删话（编号链还在）

def test_the_chain_sentence_survives_the_cleanup(registry: ToolRegistry):
    """判据 b：改完之后"编号 / 链"这件事仍说清 —— 淘汰的只能是那个具体号。

    两头都要：
      - 「绝对编号链」那句还在（它来自 `specs/*.py` 的 boundary，十一格各一条；
        本单一个字都不动它，谁为了绿把它删了，这一条红）；
      - 本单改过的那句仍写着「名册名（如 `D1`）、绝对编号」（`LOOP_RULES`，
        十一格共用）—— 换掉的只是"如 `t-000003`"里的那个号，不是这句话本身。
    """
    for role in ALL_ROLES:
        text = AP.system_prompt(role, **_kw(registry))
        assert "绝对编号链" in text, (
            f"{role} 的提示词里没有「绝对编号链」那句了 —— 编号链这件事被删掉了：",
            text[-600:])
        assert "名册名（如 `D1`）、绝对编号" in text, (
            f"{role} 的提示词里那句『名册名（如 D1）、绝对编号』没了："
            "换号可以，别把这句话删成空话", text[-600:])
        assert "编号" in text and "链" in text, (role, "编号/链 至少要出现")


# ------------------------------------- ④ 正控：运行期真注入的编号不受本单影响

def test_runtime_task_ids_still_reach_the_prompt(registry: ToolRegistry):
    """判据 c（正控）：`task_id` / `parent_task_id` 这两个运行期事实照样进提示词。

    没有这一条，上面那条"零命中"可以靠"渲染器把编号全滤掉"变绿 —— 那才是真坏了
    （模型读不到自己的号，回报就挂错名字）。所以这里喂两个真号，断言它们在里面。
    """
    text = AP.system_prompt(
        "D", **_kw(registry, summoned_by="M", task_id="t-000777",
                   parent_task_id="t-000001", depth=2, inbox="（没有收到留言）"))
    assert "t-000777" in text, ("我自己的台账号没进提示词（运行期注入坏了）：", text[-800:])
    assert "t-000001" in text, ("父的台账号没进提示词（运行期注入坏了）：", text[-800:])


# ------------------------------------- ⑤ 反真空：把具体号塞回模板 ⇒ 判据必红

def test_a_concrete_id_put_back_into_the_template_goes_red(
        registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch):
    """判据 d（反真空）：往模板里塞一个具体号，① 必须红。

    塞的是 `t-000042`：它不在任何禁改区那几段的残留集合里（见 ②），
    所以"红"只可能来自模板 —— 这条同时证明 ① 不是永远绿的摆设。
    """
    assert not _template_hits("A", registry), "反真空的前提坏了：A 那一格本已是绿的"
    original = AP._COLLAB_NAMES_TEXT
    monkeypatch.setattr(AP, "_COLLAB_NAMES_TEXT",
                        original + "\n再写一遍：`t-000042`。\n")
    hits = _template_hits("A", registry)
    assert hits, "往模板里塞了具体号，① 居然还是绿的 —— 那条判据抓不住任何东西"
    assert [task_id for _n, task_id in hits] == ["t-000042"], hits
    # 反负控的另一半：把号换回占位形就不再命中（占位形不是具体号）。
    monkeypatch.setattr(AP, "_COLLAB_NAMES_TEXT",
                        original + "\n再写一遍：`t-NNNNNN`。\n")
    assert not _template_hits("A", registry), (
        "占位形 `t-NNNNNN` 被误判成具体号 —— 正则写宽了", )
