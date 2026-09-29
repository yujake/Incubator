"""前置提示词的判据：每个角色的事实部分必须由注册表与边表现算，不许手抄。

这一组守的是"提示词与事实不许分家"。`agent_prompts` 里手写的只有判断
（职责一句、边界、政策、招牌错误），而工具面取自 `tools.build_registry()`、
伙伴取自 `capabilities.ALLOWED_EDGES`、动作取自 `capabilities.actions_for`、
三态词表取自 `judge.JUDGE_PROBLEMS`。任何一份被手抄进文本，就会多出一份会漂移的副本，
而"提示词与事实不一致"这件事不会有任何读数报出来（指令里记过：cli 写死四个角色，
新增 E-H 时没有任何地方报错）。

所以这里既有逐条覆盖的正控，也有两条"改了事实、提示词必须跟着变"的负控 ——
后者是这一组里最重要的两条：只断言"提示词里有工具名"无法区分现算与手抄。

注册表一律用 `build_registry()`（不带 workspace_root）：它没有 fs 工具，
这是这些用例里如实的工具面（其余模块的 register 需要 store，会被如实记进 skipped）。
用例不碰文件系统、不联网、不依赖执行顺序。
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

import pytest

from agentflow import agent_prompts as AP
from agentflow import capabilities as C
from agentflow import judge as J
from agentflow import schema as S
from agentflow.tools import ToolRegistry, build_registry

#: 需要一份提示词的全部角色：可被召唤的 A-H 加主控。
ALL_ROLES: tuple[str, ...] = tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)

#: 这些用例给的任务与工作区（固定值：判据必须是确定性的）。
TASK = "把这条链路走一遍"
ROOT = "D:/x"

#: 伙伴条目：以角色字母开头、后接全角冒号的行。
_PARTNER_BULLET = re.compile(r"^- ([A-HM])：")
#: 参数提示里"必填"那一栏（到分号或右括号为止）。
_REQUIRED_GROUP = re.compile(r"必填 ([^；）]*)")


@pytest.fixture()
def registry() -> ToolRegistry:
    """一张不带工作区的注册表：它没有 fs 工具，这是这些用例里如实的工具面。"""
    return build_registry().registry


def _prompt(role: str, registry: ToolRegistry, **kw: Any) -> str:
    """按统一的默认值渲染某个角色这一次的提示词。"""
    kw.setdefault("task", TASK)
    kw.setdefault("workspace_root", ROOT)
    return AP.system_prompt(role, registry=registry, **kw)


def _line_of(lines: list[str], prefix: str) -> str:
    """取唯一一条以 `prefix` 开头的行；没有或多于一条都当场失败。"""
    hits = [line for line in lines if line.startswith(prefix)]
    assert len(hits) == 1, f"以 {prefix!r} 开头的行应当恰好一条，实际 {len(hits)} 条"
    return hits[0]


def _required_in_hint(line: str) -> set[str]:
    """参数提示里"必填"一栏列出的键（`无` 表示没有必填项）。"""
    match = _REQUIRED_GROUP.search(line)
    assert match is not None, f"这一行没有参数提示：{line}"
    return {key for key in match.group(1).split("、") if key and key != "无"}


def _partner_bullets(text: str) -> set[str]:
    """文本里全部伙伴条目提到的角色字母。"""
    found = (_PARTNER_BULLET.match(line) for line in text.splitlines())
    return {match.group(1) for match in found if match}


def _partner_bullet_line(lines: list[str], role: str) -> str:
    """某个伙伴的条目行（带可调用动作那一行），不是接线态那一栏。"""
    hits = [
        line for line in lines
        if line.startswith(f"- {role}：") and "可调用动作" in line
    ]
    assert len(hits) == 1, f"伙伴 {role} 的条目应当恰好一条，实际 {len(hits)} 条"
    return hits[0]


def test_every_role_in_schema_has_a_registered_brief():
    """schema.ROLES 与主控都必须在 agent_prompts 里登记职责（missing_roles 为空）。
    若这条破了：新增角色时没人补写职责与边界，该角色的提示词会退化成通用文本，
    而"哪个角色没有提示词"没有任何读数会报出来。"""
    assert AP.missing_roles() == ()
    expected = set(S.ROLES) | {S.CONDUCTOR_ROLE}
    assert set(AP.roles_covered()) >= expected, sorted(expected - set(AP.roles_covered()))


def test_every_role_prompt_is_rendered_without_template_leftovers(registry: ToolRegistry):
    """每个角色的提示词非空、没有没被插值的模板组，并且写着它自己的职责。
    若这条破了：角色会拿到一份通用或半插值的提示词（比如任务框里留着 `{{task}}`），
    "这一次是谁在做什么"就无从判断，而模板组是坏提示词最隐蔽的形态。"""
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        assert text.strip(), f"{role} 的提示词是空的"
        assert "{{" not in text, f"{role} 的提示词里还有没被插值的模板组"
        assert AP.ROLE_BRIEFS[role].duty in text, f"{role} 的职责没有进提示词"


def test_every_tool_on_the_face_is_listed_with_its_parameter_keys(registry: ToolRegistry):
    """工具面上的每件工具都必须在提示词里，且参数提示列出 schema 里的键、必填项标成必填。
    若这条破了：模型会照提示词去调一个不存在的工具名（unknown_tool），
    或者按只列了必填的提示词多传一个键（invalid_params）——
    真机第一次跑就是这么栽的，而那一次提示词并没有说谎，只是少说了一半。"""
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        lines = text.splitlines()
        for spec in sorted(registry.for_role(role), key=lambda s: s.name):
            line = _line_of(lines, f"- {spec.name}：")
            properties = sorted(str(key) for key in (spec.params.get("properties") or {}))
            required = {str(key) for key in (spec.params.get("required") or [])}
            for key in properties:
                assert key in line, f"{role} 的工具 {spec.name} 漏了参数 {key}：{line}"
            assert _required_in_hint(line) == required, line
            if not properties:
                assert "不许传任何参数" in line, line


def test_partner_bullets_follow_the_edge_table(registry: ToolRegistry):
    """每个角色的伙伴条目必须与 ALLOWED_EDGES 的出边一致：一个不少、一个不多。
    若这条破了：模型会去唤起一个边表不允许的伙伴（换回 forbidden_edge），
    或者根本不知道某条已经放开的边存在；不可召唤的角色还会误以为自己能被召唤。"""
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        expected = set(AP.partners_out(role))
        assert _partner_bullets(text) == expected, (
            f"{role} 的伙伴条目与边表不一致：多出 {_partner_bullets(text) - expected}，"
            f"少了 {expected - _partner_bullets(text)}"
        )
        for partner in expected:
            assert f"- {partner}：" in text, f"{role} 缺伙伴条目 {partner}"
        if role in C.NON_SUMMONABLE:
            assert "不可以被任何人唤起" in text, f"{role} 不可召唤，但提示词没写"


def test_every_declared_action_is_listed_with_its_required_params(registry: ToolRegistry):
    """角色对外可被调用的动作（capabilities.actions_for）连同必填参数必须逐条写进提示词。
    若这条破了：伙伴按一个错的动作名或漏参去召唤它，拿回 unknown_action / invalid_params，
    而提示词本来该把动作名与参数表说清楚（没有动作的角色要明说没有）。"""
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        lines = text.splitlines()
        declared = C.actions_for(role)
        for spec in declared:
            line = _line_of(lines, f"- {spec.action}：")
            required = {str(key) for key in (spec.params.get("required") or ())}
            assert _required_in_hint(line) == required, line
        if not declared:
            assert "你没有对外可被调用的动作" in text, f"{role} 没有动作，提示词却没说"


def test_availability_section_lists_states_and_marks_unwired_partners(registry: ToolRegistry):
    """给 availability 时要多出一栏接线态、在伙伴条目里标出没接线的那个；不给时不许有这一栏。
    若这条破了：主控会派活给一个当场没接线的伙伴（真机第一次跑就是这样），
    或者反过来，把"没有读数"与"全都接线了"折叠成同一句话。"""
    availability = {
        "A": "no_provider",
        "B": "wired",
        "C": "no_key",
        "D": "wired",
        "E": "wired",
        "F": "wired",
        "G": "wired",
        "H": "wired",
    }
    for role in ALL_ROLES:
        text = _prompt(role, registry, availability=availability)
        lines = text.splitlines()
        audit = AP.prompt_audit(role, registry=registry, task=TASK, workspace_root=ROOT,
                                availability=availability)
        assert "PARTNER_AVAILABILITY" in audit["sections"], audit["sections"]
        for other, state in availability.items():
            assert f"- {other}：{state}" in text, f"{role} 的接线态栏里没有 {other}：{state}"
        for partner in AP.partners_out(role):
            bullet = _partner_bullet_line(lines, partner)
            if availability[partner] == "wired":
                assert "现在没接线" not in bullet, bullet
            else:
                assert f"（现在没接线：{availability[partner]}）" in bullet, bullet

        plain = _prompt(role, registry)
        plain_audit = AP.prompt_audit(role, registry=registry, task=TASK, workspace_root=ROOT)
        assert "PARTNER_AVAILABILITY" not in plain_audit["sections"], plain_audit["sections"]
        assert "现在的接线态" not in plain, f"{role} 没有接线态读数却渲染了那一栏"


def test_prompt_audit_records_version_sections_variables_and_task_hash(registry: ToolRegistry):
    """审计读数要有版本、逐字哈希、段名与排好序的变量表，且任务变了哈希必须变。
    若这条破了：事后无法回答"这次结论是哪一版提示词加哪个任务的产物"，
    两次不同任务的调用还会共用同一个哈希 —— 审计记录从此不再指向具体那一份提示词。"""
    first = AP.prompt_audit("D", registry=registry, task="任务甲", workspace_root=ROOT)
    assert first["prompt_sha256"], first
    assert len(first["prompt_sha256"]) == 64, first["prompt_sha256"]
    assert first["prompt_version"] == AP.PROMPT_VERSION
    for name in ("AGENT_IDENTITY", "ROLE_BOUNDARY", "PARTNERS", "AGENT_TOOLS_SDK"):
        assert name in first["sections"], (name, first["sections"])
    assert first["variables"] == sorted(first["variables"]), first["variables"]
    assert first["variables"] and "task" in first["variables"], first["variables"]

    second = AP.prompt_audit("D", registry=registry, task="任务乙", workspace_root=ROOT)
    assert second["prompt_sha256"] != first["prompt_sha256"], (
        "任务不同而提示词哈希相同：任务没有进提示词"
    )
    assert second["prompt_chars"] == len(_prompt("D", registry, task="任务乙"))


def test_a_renamed_tool_follows_into_the_prompt(registry: ToolRegistry, monkeypatch):
    """负控（漂移）：把注册表里的一件工具改名，渲染出来的提示词必须跟着改。
    若这条破了：工具名是手抄进提示词的 —— 注册表改了而提示词还报旧名字，
    模型照着调一次就拿到 unknown_tool，而两边都没有任何读数指出它们已经分家。"""
    role = "A"
    original_for_role = registry.for_role
    target = sorted(original_for_role(role), key=lambda spec: spec.name)[0]
    renamed = "drift.checked"

    before = _prompt(role, registry)
    assert f"- {target.name}：" in before
    assert renamed not in before

    def for_role_with_one_renamed(each_role: str) -> list[Any]:
        return [
            replace(spec, name=renamed) if spec.name == target.name else spec
            for spec in original_for_role(each_role)
        ]

    monkeypatch.setattr(registry, "for_role", for_role_with_one_renamed)
    after = _prompt(role, registry)
    assert f"- {renamed}：" in after, "改名后的工具没有出现在提示词里"
    assert f"- {target.name}：" not in after, "改名后提示词里还留着旧工具名"
    assert renamed in AP.system_prompt("A", registry=registry, task=TASK)


def test_a_changed_edge_follows_into_the_prompt(registry: ToolRegistry, monkeypatch):
    """负控（漂移）：临时改一条 ALLOWED_EDGES 的边，伙伴条目必须跟着增删。
    若这条破了：边表放开了而提示词还写着"不能找他"，模型永远不知道该走这条新路；
    反过来，边被收回而提示词还留着那条，它会一直撞 forbidden_edge。"""
    role = "D"
    before = _prompt(role, registry)
    assert _partner_bullets(before) == set(AP.partners_out(role))
    assert "F" in _partner_bullets(before) and "G" not in _partner_bullets(before)

    edges = {each: frozenset(partners) for each, partners in C.ALLOWED_EDGES.items()}
    edges[role] = frozenset((C.ALLOWED_EDGES[role] - {"F"}) | {"G"})
    monkeypatch.setattr(C, "ALLOWED_EDGES", edges)

    after = _prompt(role, registry)
    assert _partner_bullets(after) == {"A", "B", "C", "E", "G"}, _partner_bullets(after)
    assert f"- G：" in after, "新边带来的伙伴没有进提示词"
    assert f"- F：" not in after, "被收回的边对应的伙伴还留在提示词里"


def test_prompts_are_anti_vacuous(registry: ToolRegistry):
    """提示词必须长到不像占位符，且四种循环形状、三态词表、逐字引文契约都在里面。
    若这条破了：一份被截断或退回模板的提示词照样"非空"，
    而模型从未被告知循环协议、三态纪律与引文契约 —— 它会输出散文，或者把被拒折成没问题。"""
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        assert len(text) > 800, f"{role} 的提示词只有 {len(text)} 字符"
        for shape in ('"tool"', '"summon"', '"message"', '"final"'):
            assert shape in text, f"{role} 的提示词里没有循环形状 {shape}"
        assert any(code in text for code in J.JUDGE_PROBLEMS), f"{role} 的提示词里没有三态词表"
        assert "引文一律逐字" in text, f"{role} 的提示词里没有逐字引文契约"


def test_unregistered_role_and_missing_registry_fail_closed(registry: ToolRegistry):
    """未登记的角色与没给注册表都必须当场抛 ValueError（不许静默退回一份默认提示词）。
    若这条破了：拼错的角色名会拿到一份通用提示词、不给注册表会拿到一份少了几件工具的
    提示词（实测不带 workspace_root 的注册表里 D 只有 25 件工具），两者都不会有任何读数。"""
    assert "A" in AP.ROLE_BRIEFS and "Q" not in AP.ROLE_BRIEFS
    with pytest.raises(ValueError):
        AP.system_prompt("Q", registry=registry)
    with pytest.raises(ValueError):
        AP.system_prompt("A")
