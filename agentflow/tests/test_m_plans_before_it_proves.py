# -*- coding: utf-8 -*-
"""判据：M 的规划口径 —— 先了解全貌，再定方向、多位分别派遣，定期看产出调计划，全部落定才成文。

## 为什么这道判据存在

业主裁定逐字：「我认为现在M侧提示词并不能使M成为一个好的planner」。
他给出的做法逐字：「M的做法应该是先了解任务所涉及领域的全貌，然后制定切实可行的研究方向
（如有多种方向，分别派遣），定期查看各方向的研究产出，调整计划。全部研究落定，可以写论文时，
进入成文阶段」。

那四步是口径，不是某一次任务的脚本。业主当场拦下过照抄样例（「你这是为了这个专项任务定制
提示词！！」）⇒ 政策与手册写的都是同一条一般化的规划习惯：判据只核「这四步与那句理由读得到」，
既不核条数（不许出现「必须派三个」这种写死的数目），也不核任何任务名。

## 第一步为什么不核「必须先派 A」

「先了解全貌」是政策，取全貌的手段是手段：检索、读文献、问下属都算。把手段写进政策，等于
规定它只能走一条路 —— 所以这里既核「了解全貌」这层意思在，也核「必须先派某个角色」这类
写死手段的写法不在（05 那一组）。

## 四处落点，缺一处就会只改一半

- 01 渲染出来的提示词：`specs/m.py` 的 `brief.policy` 逐字进 `ROLE_POLICY` 段，
  所以「读得到」= 真的渲染一次再读（不读源码文本，历史裁定注释里可以写任何字样）。
- 02 落盘的手册：`agent_skills.materialize` 写成 `skills/M/<slug>.md` 之后，用真的
  `fs.read` 读回来 —— 那才是模型手上那一份。
- 03 反真空：把那几条 policy 摘掉之后再渲染一次，01 必须红。否则「没有这四步」
  可以靠「什么都没写」满足，而这两件事在报告里长得一样。
- 04 结构护栏：M 的可召唤面含 A / D / G、不含 F（F 仍只走 `M → D → F`）；
  文字承诺与边表必须同时成立，少了任何一半都是在教它派一条不存在的边。

## 为什么核「意思」而不核「条数」

业主的口径是「如有多种方向，分别派遣」，不是「永远凑三条」。所以每一层都用一个短的、唯一的
短语去认（去掉强调符号与空白之后比对），短语只认「这一层说过没有」，与条数、与具体任务无关。
短语选长的理由：短到像 `D` 或 `路` 那样的词，在一份两万字的提示词里到处都是，那种判据永远
不会红，也永远不会说真话。
"""
from __future__ import annotations

import re

import pytest

from agentflow import agent_prompts as AP
from agentflow import agent_skills as AS
from agentflow import capabilities as C
from agentflow.tools import ToolRegistry, build_registry

#: 渲染一次用的固定事实（与 `test_agent_prompts.py` 同一套默认值）。
TASK = "把这条链路走一遍"
ROOT = "D:/x"


@pytest.fixture()
def registry() -> ToolRegistry:
    """一张不带工作区的注册表（这些用例只读提示词，不调工具）。"""
    return build_registry().registry


def _prompt(registry: ToolRegistry, **kw) -> str:
    """渲染 M 这一次的提示词。"""
    kw.setdefault("task", TASK)
    kw.setdefault("workspace_root", ROOT)
    return AP.system_prompt("M", registry=registry, **kw)


#: 强调符号与空白：`派 **A** 去` 与 `派 A 去` 是同一句话（判「读到的意思」，不判排版）。
_EMPHASIS = re.compile(r"[\s*`]+")


def _flat(text: str) -> str:
    """去掉强调符号与所有空白 —— 判据按「读出来的意思」比对。"""
    return _EMPHASIS.sub("", text)


#: 四步 + 理由，逐层给几个短语，全部出现才算这一层读得到（提示词那一侧的措辞）。
#:
#: 顺序就是业主给的那四步（全貌 → 定方向、分别派遣 → 定期看产出调计划 → 落定才成文），
#: 外加「各方向不许换皮」这一条判据与最后那句理由。短语都是口径的原话，不是任务名。
_PROMPT_LAYERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("第一步：先了解领域的全貌",
     ("了解任务所涉及领域的全貌", "别人怎么做的", "常见路线有哪几类")),
    ("第二步：制定方向、有多种就分别派遣",
     ("制定切实可行的研究方向", "如有多种方向，分别派遣", "各交一个下属并行推进",
      "只有一个方向就只派一路")),
    ("第二步的判据：各方向不许互相换皮",
     ("不能互相换皮", "证明结构或引理清单不同")),
    ("第三步：监控全树、盯三类信号",
     ("定期监控全树", "整棵树上的各智能体行为", "handoff", "真的落盘",
      "工作阻碍", "行为异常", "特殊需求", "异常即触发")),
    ("第三步的处置：指导下发＋只到链尾、改计划、补派",
     ("沿绝对编号链逐级由秘书转发", "只有链尾", "调整研究方向", "配合补派", "为什么改")),
    ("第四步：全部落定、可以写论文时才进入成文阶段",
     ("可以写论文时", "进入成文阶段", "每落实一条就写一稿")),
    ("理由：发散早、收敛晚",
     ("发散得早", "收敛得晚")),
)

#: 同一件事在手册那一侧的措辞（层次一一对应，短语不同）。
#:
#: 为什么手册不能逐字抄政策：`tests/test_agent_skills.py::test_the_prompt_carries_the_index_and_
#: not_the_manual` 判的是「skill 正文一个字都不在提示词里」—— 手册与政策逐字同文，那条判据会
#: 当场红（实测：这一条第一次写就是这么红的）。而两处写得一字不差本来也没有信息量：政策给口径，
#: 手册给步骤与反面形态。所以这里按「同一层意思、手册自己的话」核。
_MANUAL_LAYERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("第一步：先了解领域的全貌",
     ("摸全貌", "这个领域有什么", "常见路线分几类")),
    ("第二步：制定方向、有多种就分别派遣",
     ("方向就是工作包", "一个方向一个下属", "只有一个方向就只派一路")),
    ("第二步的判据：各方向不许互相换皮",
     ("不许换皮", "证明结构或引理清单不同")),
    ("第三步：监控全树、盯三类信号",
     ("盯全树", "整棵树上每个智能体的行为", "空转", "工作阻碍", "行为异常", "特殊需求",
      "异常即触发")),
    ("第三步的处置：指导下发＋只到链尾、改计划、补派",
     ("沿绝对编号链逐级由秘书转发到它手上", "只有链尾", "改计划", "补派人")),
    ("第四步：全部落定、可以写论文时才进入成文阶段",
     ("全部方向都落定", "一次成文", "每落定一条就写一稿")),
    ("理由：发散早、收敛晚",
     ("早发散", "晚收敛")),
)


def _layer_problems(text: str, table=_PROMPT_LAYERS) -> list[str]:
    """这段文字里缺哪几层（空列表 = 四步与那句理由都读得到）。"""
    flat = _flat(text)
    out: list[str] = []
    for name, needles in table:
        missing = [n for n in needles if _flat(n) not in flat]
        if missing:
            out.append(f"读不到「{name}」这一层（缺 {missing}）")
    return out


def test_both_tables_cover_the_same_layers() -> None:
    """反真空（判据自己）：两张表覆盖同一批层次名，且手册那一侧的措辞确实不是逐字照抄。

    少了这一条，02 可以用一张只有一两层的表把「手册同口径」这一格测成一句空话；
    而「措辞不同」这条前提一旦被抄回成逐字同文，`test_agent_skills.py` 那条判据会红，
    但这里读不出来 —— 所以两边都在这里说一遍。
    """
    assert [n for n, _ in _PROMPT_LAYERS] == [n for n, _ in _MANUAL_LAYERS], (
        _PROMPT_LAYERS, _MANUAL_LAYERS)
    for (name, prompt_needles), (_, manual_needles) in zip(_PROMPT_LAYERS, _MANUAL_LAYERS):
        assert prompt_needles != manual_needles, (
            f"「{name}」这一层两侧的短语一模一样 ⇒ 手册成了政策的逐字副本"
            "（`test_agent_skills.py` 那条会红，且两处写得一字不差没有信息量）")


# ============================================================ 01 渲染出来的提示词

def test_m_prompt_reads_the_four_steps_and_the_reason(registry: ToolRegistry) -> None:
    """01 正控：M 的渲染提示词里那四步与那句理由都读得到。"""
    problems = _layer_problems(_prompt(registry))
    assert problems == [], (
        "M 的提示词里读不到规划口径的这几层（业主：现在M侧提示词并不能使M成为一个好的planner）：\n  - "
        + "\n  - ".join(problems))


def test_the_layers_are_read_from_the_rendered_prompt_not_a_source_file() -> None:
    """01 落点核对：这四步是从 `ROLE_BRIEFS['M'].policy` 出来的，且真的进了 `ROLE_POLICY` 段。

    为什么单查这一条：`specs/m.py` 里同时有 2026-10-18 / 2026-10-20 / 2026-10-24 那几段裁定
    注释，它们必须可以写任何字样（注释不进提示词）。所以判据只认声明，而声明有没有真的
    渲染进提示词，要另看一眼段名 —— 否则「policy 里有」与「模型读得到」是两件事。
    """
    brief = AP.ROLE_BRIEFS["M"]
    problems = _layer_problems("\n".join(str(x) for x in brief.policy))
    assert problems == [], ("`ROLE_BRIEFS['M'].policy` 里就不是四步齐的：\n  - "
                            + "\n  - ".join(problems))
    text = _prompt(build_registry().registry)
    assert "这次运行的政策：" in text, "提示词里没有 ROLE_POLICY 那一段（政策的落点变了）"
    for needle in ("了解任务所涉及领域的全貌", "进入成文阶段", "发散得早"):
        assert _flat(needle) in _flat(text), (
            f"policy 里写着「{needle}」，渲染出来的提示词里却没有 ⇒ 这一条没进 ROLE_POLICY 段")


# ============================================================ 02 落盘的手册

#: 手册那一份的 slug（落成 `skills/M/<slug>.md`）。
_SKILL_SLUG = "规划-先了解全貌再定方向"


def _m_skill():
    """M 名下的那一条规划手册（读不到就当场失败 —— 不许把「没有」读成「没问题」）。"""
    hits = [s for s in AS.CATALOG["M"] if s.slug == _SKILL_SLUG]
    assert len(hits) == 1, (
        f"M 的名下没有恰好一条 slug 为 {_SKILL_SLUG!r} 的手册："
        f"{sorted(s.slug for s in AS.CATALOG['M'])}")
    return hits[0]


def test_the_same_layers_land_in_the_manual_on_disk(tmp_path) -> None:
    """02 正控：手册真的落盘，且用真的 `fs.read` 读回来的正文里同样四步齐、理由也在。"""
    AS.materialize(tmp_path)
    path = tmp_path / AS.SKILLS_DIR / "M" / f"{_SKILL_SLUG}.md"
    assert path.is_file(), f"手册没落盘：{path}"
    reg = build_registry(workspace_root=tmp_path).registry
    got = reg.call("fs.read", path=f"{AS.SKILLS_DIR}/M/{_SKILL_SLUG}.md", role="M")
    assert got.ok, f"照索引里的路径读不到手册：{got.error}"
    problems = _layer_problems(str(got.data), _MANUAL_LAYERS)
    assert problems == [], ("落盘的手册里读不到这几层（模型 fs.read 读到的就是这一份）：\n  - "
                            + "\n  - ".join(problems))


def test_the_manual_body_is_not_the_index_and_is_what_carries_the_layers() -> None:
    """02 反真空：这几层是手册正文带来的，不是索引那三格（标题 / 一句话 / 何时读）。

    这条守的是「现做现读」那一整套设计：如果四步全写进 `summary`，它们会跟着索引进每一次
    调用的前置提示词，于是 02 这一条退化成「索引里有」—— 而索引只有三格的位置。
    """
    _m_skill()
    problems = _layer_problems(AS.index_block("M"), _MANUAL_LAYERS)
    assert problems, ("索引块里就四步齐了 ⇒ 02 这一条分不出「正文」与「索引」，"
                      "而且前置提示词会为这件事每趟多付一次钱")
    body_problems = _layer_problems(_m_skill().body, _MANUAL_LAYERS)
    assert body_problems == [], ("手册正文里读不到这几层：\n  - " + "\n  - ".join(body_problems))


# ============================================================ 03 反真空：摘掉 ⇒ 01 必红

#: 那几条 policy 的认领词（是「这一条在说规划」的锚，不是判据本身）。
_PLANNING_ANCHORS = ("了解任务所涉及领域的全貌", "制定切实可行的研究方向",
                     "各方向不能互相换皮", "定期查看各方向的研究产出",
                     "进入成文阶段", "发散得早")


def _drop_planning_policy(policy):
    """把讲规划的那几条整体摘掉（其余一字不动）。"""
    keep = tuple(s for s in policy
                 if not any(_flat(a) in _flat(str(s)) for a in _PLANNING_ANCHORS))
    assert len(keep) < len(policy), (
        "夹具前提不成立：policy 里没有一条能被这几只锚认出来 ⇒ 反真空打空了")
    return keep


def test_negative_control_dropping_the_policy_makes_01_red(
        registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    """03 反真空：把那几条 policy 摘掉再渲染一次 ⇒ 01 必红。"""
    import dataclasses

    brief = AP.ROLE_BRIEFS["M"]
    assert _layer_problems(_prompt(registry)) == [], "夹具前提：真身上四步是齐的"
    monkeypatch.setitem(AP.ROLE_BRIEFS, "M",
                        dataclasses.replace(brief, policy=_drop_planning_policy(brief.policy)))
    got = _layer_problems(_prompt(registry))
    assert got, ("把那几条 policy 摘掉之后判据仍然绿 ⇒ 它没有咬合力："
                 "「没有这一层」可以靠「什么都没写」满足")
    # 摘掉的是规划那几条，不是整段 policy：其余条目必须还在（否则反真空打的是「删干净」）
    assert "先窄后宽" in "\n".join(str(x) for x in AP.ROLE_BRIEFS["M"].policy), (
        "夹具把整段 policy 都摘掉了 ⇒ 这条反真空证不了「摘掉这一层就红」")
    monkeypatch.undo()
    assert _layer_problems(_prompt(registry)) == []


def test_negative_control_one_missing_layer_is_named(
        registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    """03 反真空（逐层）：只摘掉第四步那一条 ⇒ 报出来的必须点名这一层。"""
    import dataclasses

    brief = AP.ROLE_BRIEFS["M"]
    keep = tuple(s for s in brief.policy
                 if "进入成文阶段" not in str(s))
    assert len(keep) == len(brief.policy) - 1, "夹具前提：这一层恰好只在那一条里"
    monkeypatch.setitem(AP.ROLE_BRIEFS, "M", dataclasses.replace(brief, policy=keep))
    got = _layer_problems(_prompt(registry))
    assert got and any("进入成文阶段" in item or "可以写论文时" in item for item in got), (
        "只摘掉一层时判据没有点名那一层（报「少了点什么」读的人还得自己去找）：" + repr(got))
    monkeypatch.undo()


# ============================================================ 04 结构护栏：可召唤面

def _edge_problems(m_edges, d_edges) -> list[str]:
    """M 的可召唤面对不对（空列表 = 含 A / D / G、不含 F，且 F 仍经 D 可达）。"""
    got = set(m_edges)
    out = [f"M 的可召唤面里没有 {role} ⇒ 这一步规划写成了一句话术"
           for role in ("A", "D", "G") if role not in got]
    if "F" in got:
        out.append("M 的可召唤面里有 F ⇒ 2026-10-10 业主裁定的「不许直接控制 F」被推翻，"
                   "而政策里还写着 F 只能经 D")
    if "F" not in set(d_edges):
        out.append("D 的出边里没有 F ⇒ 「F 仍只走 M→D→F」这条两跳路断了，"
                   "政策里「各交一个下属并行推进」就落不到 F")
    return out


def test_m_can_summon_a_d_and_g_but_not_f() -> None:
    """04 正控：`ALLOWED_EDGES['M']` 含 A / D / G、不含 F；F 仍经 D 可达。"""
    problems = _edge_problems(C.ALLOWED_EDGES["M"], C.ALLOWED_EDGES["D"])
    assert problems == [], "M 的可召唤面与规划口径对不上：\n  - " + "\n  - ".join(problems)


def test_negative_control_the_edge_guard_catches_both_directions() -> None:
    """04 负控：给 M 加一条到 F 的边、或摘掉到 A/D/G 的边 ⇒ 判据都必须红。"""
    assert _edge_problems(C.ALLOWED_EDGES["M"], C.ALLOWED_EDGES["D"]) == []
    with_f = tuple(C.ALLOWED_EDGES["M"]) + ("F",)
    got = _edge_problems(with_f, C.ALLOWED_EDGES["D"])
    assert got and any("有 F" in item for item in got), got
    no_a = tuple(r for r in C.ALLOWED_EDGES["M"] if r != "A")
    got = _edge_problems(no_a, C.ALLOWED_EDGES["D"])
    assert got and any("A" in item for item in got), got
    no_f_from_d = tuple(r for r in C.ALLOWED_EDGES["D"] if r != "F")
    got = _edge_problems(C.ALLOWED_EDGES["M"], no_f_from_d)
    assert got and any("D 的出边" in item for item in got), got


# ============================================================ 05 一般化：不许定制

#: 四类任务名（业主当场拦下的那一版就是照抄这些的人名与任务名）。
_TASK_PROPER_NOUNS = ("sylow", "西罗", "galois", "伽罗瓦")

#: 写死的手段：第一步只写「了解全貌」，不写「必须先派某个角色」。
_HARDCODED_MEANS = ("起手先派A做", "必须先派A", "第一步派A", "先派A检索")

#: 写死的条数：口径是「如有多种方向，分别派遣」，不是「永远凑三条」。
_HARDCODED_COUNTS = ("三条路", "三个D", "三条不同的路", "三条方向", "三个方向")


def _customization_problems(policy) -> list[str]:
    """政策里出现了任务名、写死的手段、或写死的条数（空列表 = 一般化写法）。"""
    flat = _flat("\n".join(str(x) for x in policy))
    low = flat.lower()
    out = [f"政策里出现了这一次专项任务的名字：{word!r} —— 业主当场拦过："
           "「你这是为了这个专项任务定制提示词！！」"
           for word in _TASK_PROPER_NOUNS if word in low]
    out += [f"政策里把手段写死了：{word!r} —— 第一步只写「了解全貌」，取全貌的手段由 M 按"
            "工具面自己决定（检索、读文献、问下属都算）"
            for word in _HARDCODED_MEANS if _flat(word) in flat]
    out += [f"政策里写死了条数：{word!r} —— 口径是「如有多种方向，分别派遣」，"
            "写死一个数目会让只有一个方向的问题变成凑数"
            for word in _HARDCODED_COUNTS if _flat(word) in flat]
    return out


def test_the_policy_is_a_general_habit_not_a_task_script() -> None:
    """05 正控：政策里没有任务名、没有写死的手段、没有写死的条数（一般化的规划习惯）。"""
    problems = _customization_problems(AP.ROLE_BRIEFS["M"].policy)
    assert problems == [], "M 的规划政策被写成了这一次任务的脚本：\n  - " + "\n  - ".join(problems)
    # 反真空：第一步那一层真的写在那儿（否则「没写手段」可以靠「什么都没写」满足）
    assert _flat("了解任务所涉及领域的全貌") in _flat(
        "\n".join(str(x) for x in AP.ROLE_BRIEFS["M"].policy))


def test_negative_control_a_task_name_a_means_and_a_fixed_count_are_caught() -> None:
    """05 负控：把任务名、写死的手段、写死的条数各自塞回去 ⇒ 判据必须红。"""
    base = AP.ROLE_BRIEFS["M"].policy
    assert _customization_problems(base) == [], "夹具前提：真身是一般化的写法"
    assert _customization_problems((*base, "先派 A 查 Sylow 定理有哪几条常用证明。")), (
        "塞回任务名之后判据仍然绿")
    assert _customization_problems((*base, "**第一步必须先派 A 检索。**")), (
        "塞回写死的手段之后判据仍然绿")
    assert _customization_problems((*base, "把这条命题拆成三条路，让三个 D 各走一条。")), (
        "塞回写死的条数之后判据仍然绿")
