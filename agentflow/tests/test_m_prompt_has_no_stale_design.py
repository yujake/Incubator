# -*- coding: utf-8 -*-
"""M 侧提示词与工具说明里的过时设计残留（业主裁定：「M 侧过时全清」）。

审查清单 27 条，逐条一个断言；每条的失败信息都点名条目号与文件:行。文件后半段是五条护栏：

| 判据 | 守的是 | 反真空 |
|---|---|---|
| a) 27 条逐条 | 文案说的与实现不是一件事 —— 这类分家在跑起来之后不会报错 | 每条都带一句"改前那个写法"的负控（`_OLD_SNIPPETS`） |
| b) 工具名必须在面上 | 提示词点名了一件不存在的工具（模型照着调只会拿 `unknown_action`） | 塞一个 `conductor.nosuchtool` 进同一份文本 ⇒ 必红 |
| c) 收件人指称 | 拿角色代号当收件人（名册上有几个同角色实例时指不清） | 负控：把两条指称说明删掉 ⇒ 必红 |
| d) 渲染无损坏 | 源码里用反斜杠当强调符 ⇒ 渲染后是控制字符 + 半截单词 | 负控：把旧写法喂进同一个读法 ⇒ 必红 |
| e) 写死数字 / 转义 | 口径必须现算，不许手抄 | 把件数写回、把反斜杠写法写回 ⇒ 必红 |

为什么这些值得一条专门的判据：这 27 条全都是"提示词说的与代码做的不是一件事"，
而这类分家在真机上不会亮任何红灯 —— 模型照着旧口径写，拿到的是
`unknown_action` / `forbidden_edge`，或者读起来对、做起来做不到；更贵的是每一句旧口径
都会被每一次模型调用重新付一次钱。

不在本批的三处（只记录、不改，避免与别的 lane 抢）：
- `agent_loop.py::JSON_TAIL` 仍是 `{"handoff": {"to": "<伙伴/M/ALL>", …}}`（同形，归另一条 lane）；
- `llmseam.py` 里 `framework_message` 的 `to` 说明仍写「伙伴角色名 / `#public` / `ALL`」（原生
  function-calling 那一面，不在提示词里）；
- `notes/<你的角色号>.md`（#22 的同形写法）：它是文件名、不是收件人 —— 盘上真的叫
  `notes/M.md`，改成名册名会指向一个不存在的路径（判据 c 只收件人语境，见下）。
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib
import re

import pytest

from agentflow import agent_prompts as AP
from agentflow import agent_skills as AS
from agentflow import promptstability as PS
from agentflow import schema as S
from agentflow.tools import build_registry

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
PKG = REPO / "src" / "agentflow"

#: 本批读的四份源码。
M_SPEC = PKG / "specs" / "m.py"
PROMPTS = PKG / "agent_prompts.py"
CTOOLS = PKG / "tools" / "conductor_tools.py"
SKILLS = PKG / "agent_skills.py"
STABILITY = PKG / "promptstability.py"

#: 这些用例给的任务与工作区（固定值：判据必须确定性）。
TASK = "把这条链路走一遍"
ROOT = "D:/x"

#: 收工门那八格（`conductor.closing` 的读数；真身在 `closing.py`）。
CLOSING_GATES: tuple[str, ...] = (
    "paper", "contradictions", "load_bearing", "report_shape",
    "user_pending", "substance", "acceptance", "artifact_ledger",
)

#: 判据 b 只看这三组（M 的工具面上只有它们）。
_TOOL_TOKEN = re.compile(r"\b((?:conductor|clock|fs)\.[a-z][a-z0-9_]*)")


# ====================================================================== 夹具
@pytest.fixture(scope="module")
def registry():
    """真渲染用的注册表：带 workspace_root，所以 `fs.*` 在面上（M 的提示词点名了它们）。"""
    return build_registry(workspace_root=ROOT).registry


@pytest.fixture(scope="module")
def m_surface(registry) -> set[str]:
    return {spec.name for spec in registry.for_role(S.CONDUCTOR_ROLE)}


@pytest.fixture(scope="module")
def m_prompt(registry) -> str:
    """M 这一趟的提示词（纯函数，零模型调用）。"""
    return AP.system_prompt(S.CONDUCTOR_ROLE, registry=registry, task=TASK,
                            workspace_root=ROOT)


# ====================================================================== 小工具
def _src(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _cite(path: pathlib.Path, needle: str) -> str:
    """`文件:行`；源码里找不到这个串时如实说明（那说明它来自另一处真身）。"""
    for i, line in enumerate(_src(path).splitlines(), 1):
        if needle in line:
            return f"{path.name}:{i}"
    return f"{path.name}（这一串已不在源码里，真身在别处）"


def _fmt(item: int, problems: list[str], where: str) -> str:
    return f"#{item}（{where}）：\n" + "\n".join(f"  - {p}" for p in problems)


# ====================================================================== a) 逐条判据
#: 渲染后的 M 提示词里不许再出现的写法：`(条目号, 旧写法, 出处文件, 为什么)`。
_STALE_IN_PROMPT: tuple[tuple[int, str, pathlib.Path, str], ...] = (
    (1, "action='review'", M_SPEC, "`action` 2026-10-16 起不存在；派活只写 `task`"),
    (3, "叫停只有两条路", M_SPEC, "其实有三个入口：stop / stop(force=True) / cancel"),
    (4, "打断不了", M_SPEC, "那是工具内部的一步，不该出现在 M 侧政策里"),
    (5, "open_items_of", M_SPEC, "它不是工具；读板只有 `conductor.board`"),
    (6, "收工看 `closure_reminders`", M_SPEC,
     '要写成 `conductor.ledger(view="stats")` 的 `stats.closure_reminders`'),
    (7, "`manuscript_edited``source/`", M_SPEC, "句子断了（渲染出来就是这几个字）"),
    (8, "C 没有出边", M_SPEC,
     "理由不成立（M 的出边含 C）；真正的理由是 C 不做结论、只给确定性读数"),
    (9, "（每推进一段就看一次）", M_SPEC, "没点任何 clock 工具"),
    (10, "取自律上面列出的伙伴表", PROMPTS, "错字，且伙伴表已不列动作名"),
    (11, "十四件", PROMPTS, "现读 18 件；写死的数字会过期"),
    (12, "V 已于 2026-10-18 由业主加回 M 的出边", PROMPTS, "2026-10-20 已撤"),
    (14, '改前那句"五条"是手抄的陈旧计数', PROMPTS, "这句话读不通，而且计数仍然手抄"),
    (19, "`to` 取 A–H 或 M", PROMPTS, "收件人面是名册名 / 绝对编号 / 角色名 / ALL"),
    (20, '"to": "A–H 或 ALL"', PROMPTS, "同上"),
    (21, "`to` 必须是角色名或 `ALL`", PROMPTS, "同上"),
    (22, "`to` 写它的角色号", PROMPTS, "改成写名册名或绝对编号"),
    (23, "<伙伴角色名>", PROMPTS, "形状骨架里的收件人占位符已换成名册名/编号"),
    (24, "派活仍按角色走 `summon`", PROMPTS, "造新子代理给它名册名；复用写 `reuse`"),
    (26, "`conductor.retire_child(task_id=…, reason=…)`", M_SPEC,
     "销号只有一条正路：`conductor.retire_child(child_name=…)`"),
    (27, "给所有人写 `to=#public`", M_SPEC, '手稿的公共频道写法是 `to="ALL"`'),
)

#: 渲染后的 M 提示词里必须出现的写法：`(条目号, 该出现的一串, 出处文件, 为什么)`。
_REQUIRED_IN_PROMPT: tuple[tuple[int, str, pathlib.Path, str], ...] = (
    (1, "不要填 `action`", M_SPEC, "要明确禁止填 `action`"),
    (2, "调 `conductor.stop`", M_SPEC, "把叫停写成一次工具调用，不是四步手工"),
    (2, "它内部依次做掉", M_SPEC, "写明那几步是 stop 的内部步骤，不是 M 要拆开做的"),
    (2, "开关 → 广播", M_SPEC, "stop 内部依次做那几步"),
    (3, "conductor.cancel", M_SPEC, "第三个入口"),
    (3, "三个入口", M_SPEC, "数得出三个"),
    (5, "`conductor.board` 读得到", M_SPEC, "只用真工具点名"),
    (6, "stats.closure_reminders", M_SPEC, "点出读数在哪一格"),
    (7, "`source/main.tex`", M_SPEC, "把断掉的那半句补回来"),
    (8, "C 不做结论", M_SPEC, "理由换成成立的那一半"),
    (9, "clock.timer_start", M_SPEC, "「定期」要落到一个 clock 工具上"),
    (9, "clock.timer_list", M_SPEC, "同上（查还有哪些在计时）"),
    (10, "角色名取自伙伴表", PROMPTS, "角色名从伙伴表取"),
    (10, "动作名不要填", PROMPTS, "动作名不许填也不许猜"),
    (14, "论文交付", PROMPTS, "说清这五条是论文交付那五条"),
    (19, "名册名", PROMPTS, "收件人面写成名册名"),
    (19, "绝对编号", PROMPTS, "同一个收件人面还有绝对编号"),
    (23, "名册名或绝对编号", PROMPTS, "形状骨架里点名册名/编号"),
    (24, "造新子代理给它名册名", PROMPTS, "派活口径换成名册名"),
    (26, "conductor.retire_child(child_name=", M_SPEC, "政策里明写走这一件、且收 child_name"),
    (27, '`to="ALL"`', M_SPEC, "公共频道写法统一到 ALL"),
)


def _item_problems(text: str) -> dict[int, list[str]]:
    """按条目号收集这份 M 提示词里的问题（`{条目号: [问题]}`）。"""
    out: dict[int, list[str]] = {}
    for item, needle, where, why in _STALE_IN_PROMPT:
        if needle in text:
            out.setdefault(item, []).append(
                f"仍然出现 {needle!r}（{why}）—— 出处 {_cite(where, needle)}")
    for item, needle, where, why in _REQUIRED_IN_PROMPT:
        if needle not in text:
            out.setdefault(item, []).append(
                f"读不到 {needle!r}（{why}）—— 出处 {_cite(where, needle)}")
    return out


def _assert_items(numbers: list[int], text: str) -> None:
    problems = _item_problems(text)
    for n in numbers:
        assert not problems.get(n), _fmt(n, problems[n], "M 提示词")


def test_items_01_to_04_summon_and_stop(m_prompt: str) -> None:
    """#1–#4：派活不填 `action`；叫停是 `conductor.stop` 的一次调用（三个入口），不写工具内部。"""
    _assert_items([1, 2, 3, 4], m_prompt)


def test_items_05_to_09_readings_point_at_real_tools(m_prompt: str) -> None:
    """#5–#9：`open_items_of` 不是工具；closure 读数在 ledger 里；断句补回；C 的理由；clock。"""
    _assert_items([5, 6, 7, 8, 9], m_prompt)


def test_items_10_to_12_partner_table_and_no_hardcoded_counts(m_prompt: str) -> None:
    """#10–#12：伙伴表只给角色名；`conductor.*` 的件数现算；撤掉的边不再提。"""
    _assert_items([10, 11, 12], m_prompt)


def test_item_14_closing_gate_lists_all_eight_cells(m_prompt: str) -> None:
    """#14：收工门写「八格」就必须列得出八格（论文交付五条 + 其余以 closing 读数为准）。"""
    _assert_items([14], m_prompt)
    start = m_prompt.find("五、完成定义")
    end = m_prompt.find("六、收工前的最后一条")
    assert start >= 0 and end > start, "M 提示词里切不出「五、完成定义」那一段"
    section = m_prompt[start:end]
    missing = [g for g in CLOSING_GATES if f"`{g}`" not in section]
    assert not missing, _fmt(14, [f"八格里这几格没点名：{missing}"], _cite(PROMPTS, "五、完成定义"))


def test_items_15_to_17_tool_descriptions_match_what_the_tools_return(registry) -> None:
    """#15–#17：`role_spec` 只给描述；角色名含 V/L；出边看伙伴表（A–H 会让 M 以为 F/V 能派）。"""
    spec = registry.get("conductor.role_spec")
    summary = spec.summary
    stale = [s for s in ("允许的动作", "它今天有哪些工具") if s in summary]
    assert not stale, _fmt(15, [f"role_spec 的说明仍写 {s!r}（实现只给 role/summonable + brief 六格）"
                                for s in stale], _cite(CTOOLS, "某角色的描述"))
    for want in ("职责", "不给"):
        assert want in summary, _fmt(
            15, [f"role_spec 的说明里读不到 {want!r}：{summary!r}"], _cite(CTOOLS, "某角色的描述"))

    role_name = spec.params["properties"]["role_name"]["description"]
    assert "V" in role_name and "L" in role_name, _fmt(
        16, [f"role_name 的说明是 {role_name!r}（要写 A–H / V / L）"], _cite(CTOOLS, "角色名（A–H"))

    target = registry.get("conductor.summon").params["properties"]["target_role"]["description"]
    assert "A–H" not in target, _fmt(
        17, [f"target_role 仍写 {target!r}（A–H 会让 M 以为 F/V 也派得动）"], _cite(CTOOLS, "被召唤的角色代号"))
    assert "伙伴表" in target, _fmt(
        17, [f"target_role 没有指向伙伴表：{target!r}"], _cite(CTOOLS, "被召唤的角色代号"))
    many = registry.get("conductor.summon_many")
    target_many = many.params["properties"]["targets"]["items"]["properties"]["target_role"]["description"]
    assert "A–H" not in target_many, _fmt(
        17, [f"summon_many 的 target_role 仍写 {target_many!r}（同一条口径）"],
        _cite(CTOOLS, "被召唤的角色代号"))


def _skill_text() -> str:
    """全部手册正文（`CATALOG` 里那些会被模型 `fs.read` 的东西）。"""
    return "\n".join(f"{s.slug}\n{s.summary}\n{s.when}\n{s.body}"
                     for rows in AS.CATALOG.values() for s in rows)


def test_item_18_handbook_never_names_a_tool_that_does_not_exist() -> None:
    """#18：手册点名的工具必须真存在 —— 新判据让"点不存在的工具"必红。

    `validate()` 原来只查"已在工具面上的名字"，一个不存在的名字（`conductor.stats` 的真身是
    `conductor.ledger(view="stats")`）在那边静默放过。这条守两半：正控（今天一条都不许有）
    + 规则本身在跑（反真空见下一条）。
    """
    handbook = _skill_text()
    assert "conductor.stats" not in handbook, _fmt(
        18, ['手册里还点着 `conductor.stats`（真身是 `conductor.ledger(view="stats")`）'],
        _cite(SKILLS, "收工那一步（`conductor.closing`）"))
    surface = AS._role_tool_surface([])
    assert surface, "读不出工具面 ⇒ 这一格没查成（不是没问题）"
    unknown = AS._unknown_tool_problems(surface)
    assert unknown == [], _fmt(18, unknown, "agent_skills.py")
    problems = AS.validate()
    assert problems == [], _fmt(18, problems, "agent_skills.validate()")


def test_item_18_a_handbook_naming_a_missing_tool_goes_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """#18 反真空：往一条手册正文里塞一个不存在的工具名 ⇒ `validate()` 必红。

    没有这一条，"手册里没有点错名"可能只是"没有任何判据在看它"（改前正是如此）。
    """
    rows = AS.CATALOG["M"]
    victim = dataclasses.replace(rows[0], body=rows[0].body + "\n收口用 `conductor.nosuchtool`。\n")
    monkeypatch.setitem(AS.CATALOG, "M", (victim, *rows[1:]))
    problems = AS.validate()
    assert any("conductor.nosuchtool" in p for p in problems), (
        f"往手册里塞一个不存在的工具名，validate() 却一声不吭：{problems}")


def test_items_19_to_24_handoff_and_message_addressing_is_roster_names(m_prompt: str) -> None:
    """#19–#24：收件人面写成名册名 / 绝对编号 / 角色名 / ALL（不再教角色代号）。"""
    _assert_items([19, 20, 21, 22, 23, 24], m_prompt)


def test_item_25_the_board_and_inbox_point_at_the_step_message() -> None:
    """#25：`board` / `inbox` 的指路语指向每一步之前那条【信箱】增量消息（D-52 删了开场那两格）。"""
    for key in ("board", "inbox"):
        text = PS.SYSTEM_PLACEHOLDERS[key]
        where = _cite(STABILITY, f'"{key}": (')
        assert "【信箱】" in text, _fmt(
            25, [f"{key} 的指路语没有指向【信箱】增量消息：{text!r}"], where)
        assert "本次对话第一条消息" not in text, _fmt(
            25, [f"{key} 仍指向已删掉的开场快照：{text!r}"], where)


def test_item_26_retiring_has_exactly_one_entry_and_it_takes_a_roster_name(
        registry, m_prompt: str) -> None:
    """#26：销号只有一个入口 `conductor.retire_child(child_name=…)`；`task_id` 只是兼容并留读数。

    为什么正路那一格叫 `child_name` 而不是 `name`：`ToolRegistry.call(name, ...)` 的首个形参
    就叫 `name`，而 `agent_loop._do_tool` 把模型给的 args 摊成关键字传进去 ⇒ 形参叫 `name`
    时，「名字写对了、工具本身没问题」却会拿到 `TypeError`（2026-10-26 实测）。所以这条
    还钉两件事：schema 里不许出现 `name`；按名册名调用的那条路真的走得通（见下一条）。
    """
    spec = registry.get("conductor.retire_child")
    props = spec.params["properties"]
    assert "child_name" in props, _fmt(
        26, ["retire_child 的 params 里没有 child_name（名册名才是正路）"],
        _cite(CTOOLS, '"conductor.retire_child"'))
    assert "name" not in props, _fmt(
        26, ["schema 里还留着 `name` ⇒ 模型照它写 args:{name:…} 会撞 "
             "`ToolRegistry.call` 的首个形参（TypeError）"],
        _cite(CTOOLS, '"child_name": {'))
    assert "task_id" in props, _fmt(26, ["retire_child 不再收 task_id（兼容口径被删了）"],
                                    _cite(CTOOLS, '"conductor.retire_child"'))
    assert spec.params["required"] == [], _fmt(
        26, [f"required 是 {spec.params['required']!r} ⇒ 只写 child_name 的调用会被 schema 挡下"],
        _cite(CTOOLS, '"required": []'))
    for key in ("task_id_compat", "addressed_by"):
        assert key in spec.returns, _fmt(
            26, [f"returns 里没有 {key} ⇒ 谁按哪一格指称、谁还在用旧写法，都读不出来"],
            _cite(CTOOLS, key))
    assert "名册名" in props["child_name"]["description"], _fmt(
        26, [f"child_name 的说明没写名册名：{props['child_name']['description']!r}"],
        _cite(CTOOLS, '"child_name": {'))
    assert "旧路" in m_prompt, _fmt(
        26, ["M 提示词里没有把 /shape 的 `retire` 标成旧路"], _cite(PROMPTS, "这一形是"))
    _assert_items([26], m_prompt)


def test_item_26_a_roster_name_can_reach_the_tool_through_the_loop_path(registry) -> None:
    """#26 副判据：模型那条路（把 args 摊成关键字传给 registry.call）必须走得通，不撞名。

    改前形参叫 `name`，于是 call 把 args 摊成关键字时，args 里的 `name` 与
    `call` 自己的首个形参撞车 ⇒ `TypeError`，而工具本身完全没问题：这正是"名字写对了
    却拿到工具层抛错"的形态，模型从读数里分不出它和"工具坏了"。
    """
    try:
        registry.call("conductor.retire_child", role="M", child_name="D1", reason="夹具")
    except TypeError as exc:      # pragma: no cover - 只有撞名时才会走到
        raise AssertionError(f"按名册名调销号撞了 TypeError（形参又改回 name 了？）：{exc}") from exc
    # 负控：`name` 当关键字传进来时确实会撞 —— 所以它不许出现在 schema 里（见上一条）。
    with pytest.raises(TypeError):
        registry.call("conductor.retire_child", role="M", name="D1")


def test_item_26_a_dirty_board_refuses_with_the_hard_wording() -> None:
    """#26 附（业主 2026-10-26）：「task_board 没清，发提醒，不准直接销号」。

    拒信要同时给三样：点出还差几条、给处置路径（`conductor.ack`）、并把硬话写出来
    （逐字「否则不许销号」）—— 只写"先把项收口"是提醒，不是禁令。
    """
    src = _src(CTOOLS)
    needle = "否则不许销号"
    assert needle in src, _fmt(
        26, [f"销号前置的拒信里没有逐字 {needle!r}（业主原话：task_board 没清，不准直接销号）"],
        _cite(CTOOLS, "未消的板项"))
    at = src.find(needle)
    window = src[max(0, at - 420):at]
    assert "conductor.ack" in window, _fmt(
        26, ["拒信里没给处置路径（同一句里要提 `conductor.ack`）"], _cite(CTOOLS, "未消的板项"))
    assert "未消的板项" in window, _fmt(
        26, ["拒信里没点出还差几条（`未消的板项`）"], _cite(CTOOLS, "未消的板项"))


def test_item_27_handoff_target_is_aligned_with_the_message_shapes(m_prompt: str) -> None:
    """#27：`specs/m.py` 的交接收件人那一格与 #19–#24 同一套指称（名册名/编号/ALL）。"""
    _assert_items([27], m_prompt)
    assert "名册名（例如 `D1`）" in m_prompt, _fmt(
        27, ["m.py 的交接那一条不再点名册名"], _cite(M_SPEC, "收件人写名册名"))


# ====================================================================== b) 工具名护栏
def _unknown_tool_problems(text: str, surface: set[str]) -> list[str]:
    """文本里点名的 `conductor.*` / `clock.*` / `fs.*` 必须都在这个角色的工具面上。"""
    return [f"点名了工具 {tok}，而它不在 M 的工具面上（{len(surface)} 件里没有它）"
            for tok in sorted(set(_TOOL_TOKEN.findall(text))) if tok not in surface]


def test_b_every_tool_named_in_the_m_prompt_is_on_the_m_surface(m_prompt: str,
                                                               m_surface: set[str]) -> None:
    """b) 整份 M 提示词点名的工具，一个都不许落在面外（专抓 #18 那类"点了不存在的工具"）。"""
    assert len(m_surface) >= 20, f"M 的工具面只有 {len(m_surface)} 件 ⇒ 这条判据是真空的"
    problems = _unknown_tool_problems(m_prompt, m_surface)
    assert problems == [], _fmt(18, problems, "M 提示词 vs 工具面")
    poisoned = m_prompt + "\n收口用 `conductor.nosuchtool`。\n"
    assert _unknown_tool_problems(poisoned, m_surface), (
        "塞进 `conductor.nosuchtool` 之后判据仍然绿 ⇒ 它证明不了任何事")


# ====================================================================== c) 指称护栏
#: "拿角色代号当收件人"的那几种写法：命中即红。
_ROLE_AS_RECIPIENT = (
    re.compile(r"to\s*=\s*\"?A[–-]H"),
    re.compile(r"\"to\"\s*:\s*\"A[–-]H"),
    re.compile(r"`to`?\s*[^。\n]{0,6}写[^。\n]{0,6}角色号"),
    re.compile(r"<伙伴角色名>"),
)


def _recipient_problems(text: str) -> list[str]:
    out: list[str] = []
    for pat in _ROLE_AS_RECIPIENT:
        hit = pat.search(text)
        if hit is not None:
            out.append(f"仍在教角色代号当收件人：{hit.group(0)!r}")
    for want in ("名册名", "绝对编号"):
        if want not in text:
            out.append(f"指称说明里读不到 {want!r}（别把指称说明一起删了）")
    return out


def test_c_no_role_code_is_taught_as_a_recipient(m_prompt: str) -> None:
    """c) M 提示词里没有"角色代号当收件人"的写法，且两条指称说明还在。

    豁免（明写出来、不是漏查）：`notes/<你的角色号>.md` 是文件名、不是收件人 ——
    盘上真的叫 `notes/M.md`，改成名册名会指向一个不存在的路径。
    负控：只把那两条指称说明删掉、别的不动 ⇒ 这条必须红（业主点名要防"顺手一起删"）。
    """
    problems = _recipient_problems(m_prompt)
    assert problems == [], _fmt(19, problems, _cite(PROMPTS, "写信给"))
    assert "notes/<你的角色号>.md" in m_prompt, (
        "note 的落盘路径不见了（它是文件名、不是收件人：改它会让笔记写到别处）")
    stripped = m_prompt.replace("名册名", "").replace("绝对编号", "")
    assert _recipient_problems(stripped), (
        "把两条指称说明删掉之后判据仍然绿 ⇒ 这条判据证明不了「说明还在」")


# ====================================================================== d) 渲染无损坏
#: 渲染后不许出现的控制字符（`\n` / `\t` 是正常换行与缩进，不算）。
_BAD_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def test_d_the_rendered_prompt_has_no_escape_damage(m_prompt: str) -> None:
    """d) 渲染后的 M 提示词里没有控制字符、没有 `⏎` 这类残字（反斜杠当强调符的后果）。"""
    bad = _BAD_CONTROL.findall(m_prompt)
    assert not bad, _fmt(13, [f"渲染后有 {len(bad)} 个控制字符：{[hex(ord(c)) for c in bad[:6]]}"],
                         _cite(PROMPTS, "名册三格"))
    assert "\u23ce" not in m_prompt, _fmt(13, ["渲染后出现 ⏎（换行被画成了符号）"],
                                          _cite(PROMPTS, "名册三格"))


# ====================================================================== e) 反真空
#: "反斜杠当强调符"那种写法：`\b` / `\n` / `\r` 紧跟字母（渲染后是控制字符 + 半截单词）。
_BACKSLASH_WORD = re.compile(r"(?<!\\)\\[abfnrtv](?=[A-Za-z])")

#: 改前那半句（逐字；用来证明判据本身会红）。
_OLD_NAMES_LINE = r"（\brief\ / \name\ / \reuse\）"


def _docstring_ids(tree: ast.AST) -> set[int]:
    """模块 / 函数 / 类的 docstring 节点 —— 它们不进提示词，不参与这条判据。"""
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = list(getattr(node, "body", None) or [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.add(id(body[0].value))
    return out


def _raw_escape_hits(text: str) -> list[str]:
    return [m.group(0) for m in _BACKSLASH_WORD.finditer(text)]


def _escape_damage(src: str) -> list[str]:
    """源码里那些会渲染成控制字符的字符串字面量（注释与 docstring 不算）。"""
    tree = ast.parse(src)
    skip = _docstring_ids(tree)
    out: list[str] = []
    for node in ast.walk(tree):
        if (not isinstance(node, ast.Constant) or not isinstance(node.value, str)
                or id(node) in skip):
            continue
        seg = ast.get_source_segment(src, node) or ""
        hits = _raw_escape_hits(seg)
        if hits:
            out.append(f"第 {node.lineno} 行的字符串里有 {hits}（渲染后是控制字符 + 半截单词）")
    return out


def test_e_item_13_the_source_has_no_backslash_as_emphasis() -> None:
    """e) #13 反真空：把反斜杠写法塞回源码 ⇒ 必红（改前那一版正是这个样子）。"""
    damage = _escape_damage(_src(PROMPTS))
    assert damage == [], _fmt(13, damage, _cite(PROMPTS, "名册三格"))
    assert _raw_escape_hits(_OLD_NAMES_LINE), (
        "改前那半句喂进同一个读法却一声不吭 ⇒ 这条判据抓不住 #13")


def test_e_item_11_the_conductor_count_is_computed_not_written(
        registry, monkeypatch: pytest.MonkeyPatch) -> None:
    """e) #11 反真空：把件数写死 ⇒ 必红。判据是"改了工具面，提示词跟着变"。"""
    live = AP.conductor_tool_count(S.CONDUCTOR_ROLE, registry)
    assert live >= 10, f"M 的 `conductor.*` 只有 {live} 件 ⇒ 这条判据是真空的"
    text = AP.system_prompt(S.CONDUCTOR_ROLE, registry=registry, task=TASK, workspace_root=ROOT)
    assert f"{live} 件读数与操作" in text, _fmt(
        11, [f"提示词里读不到现算的件数（应为 {live} 件）"], _cite(PROMPTS, "件读数与操作"))
    monkeypatch.setattr(AP, "conductor_tool_count", lambda role, reg: live + 7)
    shifted = AP.system_prompt(S.CONDUCTOR_ROLE, registry=registry, task=TASK, workspace_root=ROOT)
    assert f"{live + 7} 件读数与操作" in shifted, (
        "把件数换成一个错数字，提示词却没跟着变 ⇒ 那个数字是写死的")
    assert f"{live} 件读数与操作" not in shifted


# ====================================================================== 改前红（负控总表）
#: 改前那几句逐字（不从当前文本拼：拼出来的"旧版"会随修好一起变好）。
_OLD_SNIPPETS: tuple[tuple[int, str], ...] = (
    (1, "`conductor.summon` 里给 `action='review'` 并写明 `doc_id`"),
    (3, "叫停只有两条路，都在你手上"),
    (4, "广播每个同伴都收得到，但它**打断不了**正在跑的循环"),
    (5, "各级父用 `open_items_of` / `conductor.board` 读得到"),
    (6, "收工看 `closure_reminders`：谁提交了没人接手"),
    (7, "其中 `manuscript_edited``source/`**（审阅型工作区才有）"),
    (8, "D 自己唤起 C 拿报告、立猜想、再派 F——C 没有出边"),
    (9, "**定期**（每推进一段就看一次）"),
    (10, "角色名与动作名取自律上面列出的伙伴表"),
    (11, "`conductor.*` 那十四件读数与操作"),
    (12, "V 已于 2026-10-18 由业主加回 M 的出边"),
    (14, '五、完成定义（收工门八格全过才算交付，任何一格没过就不许说"完成"；\n'
         '格数与逐格判据以 `conductor.closing` 的当次读数为准 —— 这里写的是真身条数，'
         '改前那句"五条"是手抄的陈旧计数）'),
    (19, "- 写给谁：`to` 取 A–H 或 M"),
    (20, '"to": "A–H 或 ALL"'),
    (21, "所以 `to` 必须是角色名或 `ALL`"),
    (22, '**私下指名**（`to` 写它的角色号）'),
    (23, '{"summon": {"role": "<伙伴角色名>"'),
    (24, "派活仍按角色走 `summon`"),
    (26, "`conductor.retire_child(task_id=…, reason=…)`"),
    (27, "给所有人写 `to=#public`"),
)


@pytest.mark.parametrize(("item", "old"), _OLD_SNIPPETS,
                         ids=[f"item{n:02d}" for n, _ in _OLD_SNIPPETS])
def test_a_each_item_goes_red_on_the_old_wording(item: int, old: str, m_prompt: str) -> None:
    """a) 改前红：把那一句旧写法塞回 M 提示词 ⇒ 同一个读法必须点出那一个条目号。

    这是"判据不是橡皮图章"的唯一证明方式：只断言"今天的文本里没有某个串"，无法区分
    "改好了"与"这句话本来就不在这份文本里"。
    """
    problems = _item_problems(m_prompt + "\n" + old + "\n")
    assert problems.get(item), (
        f"#{item}：把 {old!r} 塞回 M 提示词，判据却一声不吭（读到的问题：{sorted(problems)}）")


def test_a_the_old_wording_is_gone_from_the_sources() -> None:
    """a) 附带：这 20 句旧写法在源码里一句都不许留（否则它们随时会被渲染回来）。"""
    stale: list[str] = []
    for item, old in _OLD_SNIPPETS:
        for path in (M_SPEC, PROMPTS):
            if old in _src(path):
                stale.append(f"#{item} {old!r} 仍在 {path.name}")
    assert not stale, "旧写法还在源码里：\n" + "\n".join(f"  - {s}" for s in stale)
