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
import pathlib
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


def test_the_toolchain_reading_is_in_every_prompt_and_is_not_hardcoded(
        registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch):
    """判据（`draft/37` §89）：这台机器的证明工具链读数要进提示词，且它必须现算。

    真机读数（T1 第 3 趟）：`E.check_formal` 被派 8 次，6 次撞在 `import Mathlib`
    报 `unknown package 'Mathlib'` 上 —— 框架早就知道本机没装 Mathlib
    （`toolchain.mathlib_state()` 是 §82 为这一轴做的读数），却从没写进模型看得见的地方；
    而 E 的提示词里那句"要 Mathlib 就显式传 imports"在这台机器上是一句误导。

    判据分两半，缺一不可：
      ① 每个角色的提示词里都有这一段，且没传读数时它说"没有读到读数"
         （不许静默缺席 —— 那会让"我不知道"看起来像"本来就没有"）；
      ② 传了读数时它逐字出现 —— 且把探针换成两个不同的替身，正文跟着变
         （证明这一行是投影，不是写死的一句话）。
    """
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        assert "证明工具链" in text, f"{role} 的提示词里没有工具链那一段"
        assert "没有读到读数" in text, (
            f"{role} 的提示词在没拿到读数时没有如实写「没读到」：{text[:200]}")

    sentinel = "这台机器上的证明工具链（现算读数，不是记忆）：\n- 检查器：lean 4.7.0"
    assert sentinel in _prompt("E", registry, toolchain_facts=sentinel)

    from agentflow import agent_prompts as AP2
    from agentflow import toolchain as TC

    def _probe(**kw: Any) -> dict[str, Any]:
        return {"checked": True, "available": [{"name": "lean", "version": "4.7.0"}],
                "available_names": ["lean"], "probe_errors": [], "reason": "探测到 1 个",
                "looked_in": [], "sources": {"lean": "explicit_dir"}}

    monkeypatch.setattr(TC, "probe_checkers", _probe)
    monkeypatch.setattr(TC, "mathlib_state",
                        lambda *a, **k: {"checked": True, "root": "",
                                         "reason": "没找到 Mathlib 工程根"})
    AP2.toolchain_facts_text.cache_clear()
    with_lean = AP2.toolchain_facts_text()
    assert "lean 4.7.0" in with_lean and "没找到工程根" in with_lean, with_lean

    monkeypatch.setattr(TC, "probe_checkers",
                        lambda **kw: {"checked": True, "available": [],
                                      "available_names": [], "probe_errors": [],
                                      "reason": "探测完成：环境里没有任何受支持的证明检查器",
                                      "looked_in": [], "sources": {}})
    AP2.toolchain_facts_text.cache_clear()
    without = AP2.toolchain_facts_text()
    assert "没有任何受支持的检查器" in without, without
    assert without != with_lean, "换了探针读数、这一行却没变 ⇒ 它是写死的"
    AP2.toolchain_facts_text.cache_clear()


def test_the_toolchain_line_says_to_pass_mathlib_when_the_probe_says_it_works(
    monkeypatch: pytest.MonkeyPatch,
):
    """判据：Mathlib 可用时，那一行必须说"显式传 `['Mathlib']`"，而不是叫你去写自足文件。

    真机读数（2026-10-05 T1 第 16 趟）：这一行在 Mathlib 可用时仍然写死
    "`check_formal` 可达的写法是不 import Mathlib 的自足文件" —— 它与上面一行的现算读数
    直接打架，而模型信了它：`experiments` 里 8 次 formal 全是
    `imports=（默认：不注入任何库）`、全部 `compile_error`（检查器原话
    `failed to synthesize instance`），一条 proof 行都没落成。
    负控：读数说没装时，"自足文件"那句必须还在 —— 那一支的处置本来就该是它。
    """
    from agentflow import agent_prompts as AP2
    from agentflow import toolchain as TC

    probe = {"checked": True, "available": [{"name": "lean", "version": "4.7.0"}],
             "available_names": ["lean"], "probe_errors": [], "reason": "探测到 1 个",
             "looked_in": [], "sources": {"lean": "explicit_dir"}}
    monkeypatch.setattr(TC, "probe_checkers", lambda **kw: probe)
    monkeypatch.setattr(TC, "mathlib_state",
                        lambda *a, **k: {"checked": True, "root": "R",
                                         "umbrella_olean": "R/Mathlib.olean",
                                         "import_mathlib": "可用"})
    AP2.toolchain_facts_text.cache_clear()
    text = AP2.toolchain_facts_text()
    assert "'Mathlib'" in text and "imports" in text and "failed to synthesize instance" in text, text
    assert "不 import Mathlib 的自足文件" not in text, text

    monkeypatch.setattr(TC, "mathlib_state",
                        lambda *a, **k: {"checked": True, "root": "",
                                         "reason": "没找到 Mathlib 工程根"})
    AP2.toolchain_facts_text.cache_clear()
    text = AP2.toolchain_facts_text()
    assert "不 import Mathlib 的自足文件" in text, text
    AP2.toolchain_facts_text.cache_clear()


def test_the_role_that_writes_the_acceptance_table_knows_every_controlled_kind():
    """广告面判据（D35）：写表的人必须拿到受控词表的逐字清单。

    真机读数（T2 第 7 趟 `projects/p6i-research-from-zero`）：M 的验收表 P1 用了
    `manuscript_edited`，而那个从零工作区没有只读基线 `source/` ⇒ 那一行的读数算不出来
    ⇒ 整张表判没查成、`can_close=false`（七格里唯一红的那格其实是 `anchor`，而
    `acceptance` 连读数都没留下）。词表不在 brief 里时，写表就是猜；猜错一个名字废掉的是
    整张表，不是那一行 —— 所以这一条按"词表里每一档都要在 brief 里出现"来守。
    """
    from agentflow import agent_prompts as AP
    from agentflow import closing as CL

    brief = AP.ROLE_BRIEFS["M"]
    text = "\n".join([brief.duty, brief.deliverable, *brief.policy])
    missing = [k for k in CL.LEG_CHECK_KINDS if k not in text]
    assert not missing, f"这些受控档没进写表那个角色的 brief：{missing}"


def test_the_research_brief_sends_conjectures_to_the_attack_role():
    """广告面判据（D33）：研究型任务里"猜想交给 F 攻坚"必须明说。

    真机读数（T2 第 7 趟）：7 条可检验猜想、5 条实验、1 份稿件，而 `attack_plans` 0 行
    —— M 的 brief 此前一个字都没提 F / 攻坚 / attack，于是"提了猜想没人攻"；
    而 F 那一侧 §138 加的纪律全在，问题只在没人派它。
    """
    from agentflow import agent_prompts as AP

    brief = AP.ROLE_BRIEFS["M"]
    text = "\n".join([brief.duty, brief.deliverable, *brief.policy])
    assert "F.create_plan" in text and "attack_plans" in text, text
    assert "plan_progress_rows" in text, text
    assert "不是论文包" in text, "研究型任务的交付物口径也要写清（D34）"


def test_the_research_brief_asks_for_literature_citations_and_three_search_readings():
    """广告面判据（D37 / D38 的作者侧）：这三句话必须写在 brief 里。

    真机读数（T2 第 9 趟 `p6k`）：手稿 7 条引用全是 `exp:`、`lit:` 引用 0
    （库里有 16 条文献、8 条全对口），14 条数值实验 `search_bound` 有值的 0 条
    —— 两件事都不是"能力缺失"，是没人要求：验收表没写文献那一行、
    也没人告诉主控"你自己写的核验脚本要留下界/策略/成本曲线"。
    """
    from agentflow import agent_prompts as AP

    def _brief_text(role: str) -> str:
        brief = AP.ROLE_BRIEFS[role]
        return "\n".join([brief.duty, brief.deliverable, *brief.policy])

    m_text = _brief_text("M")
    assert "document_literature_citations" in m_text and "文献进稿" in m_text, m_text
    assert "bound" in m_text and "strategy" in m_text and "scaling" in m_text, m_text
    g_text = _brief_text("G")
    assert "lit:" in g_text and "研究型手稿" in g_text, g_text


def test_the_formal_verification_path_says_verdict_then_ledger_row(registry: ToolRegistry):
    """判据（`draft/37` §92）：提示词必须说清"形式化核验分两步"，且第二步是落库。

    真机读数（第 6 趟）：主控照提示词派了 6 次 `E.check_formal`，其中两条真的
    `verified=true`（`exactness_core` / `fekete_core`），而 `experiments` 表是 0 行 ——
    因为 `check_formal` 只给裁决、不落台账。于是它随后的 10 条 proof 级断言一条都建不进
    `documents`（FC-22 要 `exp:` 引用），`documents` 与 H 那两跳全落空；
    而旧提示词写的是「`check_formal` 给出的 `verified=True` 是证据升级（台账里那条断言的
    证据跟着变）」——那句话与实现不符。

    判据的形状：①提示词里必须有 `run_experiment` 与 `method='formal'` 这条落库路径；
    ②必须写明 `check_formal` 不落台账；③负控（事实那一侧）：`check_formal` 跑完之后
    `experiments` 行数不变 —— 万一有人把它改成会写行，这条判据会红，提醒改提示词。
    """
    paper_pack_roles = [r for r in ALL_ROLES if r in AP.PAPER_PACK_ROLES]
    assert paper_pack_roles, "没有角色拿到论文包那一段 ⇒ 这条判据失去对象"
    for role in paper_pack_roles:
        text = _prompt(role, registry)
        assert "run_experiment(method='formal'" in text, f"{role} 的提示词没给落库那一步"
        assert "只给裁决、不落台账" in text, f"{role} 的提示词没说清 check_formal 不落台账"

    # ---- 事实那一侧（负控）：`check_formal` 真的不写 `experiments`
    import tempfile
    from pathlib import Path as _P

    from agentflow.agent_e import AgentE
    from agentflow.store import Store

    ws = _P(tempfile.mkdtemp(prefix="formal-path-judge-"))
    st = Store(ws)
    st.init()
    e = AgentE(st)
    before = len(st.rows("experiments"))
    (ws / "t.lean").write_text("theorem judge_trivial : (1 : Nat) + 1 = 2 := rfl\n",
                               encoding="utf-8")
    e.check_formal(claim="判据：1+1=2", script_path="t.lean")
    assert len(st.rows("experiments")) == before, (
        "`check_formal` 现在会写 experiments 了？那提示词里那两句（裁决/落库分开）必须跟着改")


def test_e_is_told_to_write_the_lean_source_into_the_workspace(registry: ToolRegistry):
    """判据（`draft/37` §98 的真机读数）：E 必须被明确告知"内联源码同时落进工作区"。

    第 10 趟真机：两次 `check_formal` 真的 `verified` 了（`exactness_forward`），
    而内联源码只落在临时目录里 ⇒ 它既不是 `proof_location`、也没法交给
    `run_experiment(method='formal', script_path=…)`；随后 4 次 `run_experiment`
    指着 `code/exactness_forward.lean` 报"脚本不存在"，`experiments` 里一条 proof 行都没有。
    裁决与落库之间只差"把源码写进工作区"这一步 —— 而这一步此前没人告诉过它。
    """
    text = _prompt("E", registry)
    for needle in ("fs.write", "code/lean/", "script_path", "proof_location"):
        assert needle in text, f"E 的提示词里没有提到 {needle!r}"
    # 无 Mathlib 时的三条写法口径（第 11 趟的真机失败形态，逐条写进去）
    for needle in ("decide", "不归约", "sorry", "改一处再试", "checker_name"):
        assert needle in text, f"E 的提示词里没有提到 {needle!r}"


def test_the_partner_table_says_what_each_partner_delivers_and_must_not_do(
        registry: ToolRegistry):
    """判据（`draft/37` §108，用户口径"先加强描述"）：伙伴行要带"它交付什么 + 它不许什么"。

    此前那一行只有"它有哪些动作" —— 真机代价：主控把 `ingest_local` 派给了 B
    （那是 A 的动作，`refused/unknown_action`），也拿越权请求去撞拒绝。
    这两件事在事前本来就能避免。数据来自声明层（`agentspec.AgentBrief`），现算。
    """
    for role in ALL_ROLES:
        brief = AP.ROLE_BRIEFS[role]
        for other in AP.partners_out(role):
            line = next((ln for ln in AP.partners_lines(role) if ln.startswith(f"- {other}：")), "")
            assert line, f"{role} 的伙伴表里没有 {other} 那一行"
            ob = AP.ROLE_BRIEFS[other]
            assert str(ob.deliverable) in line, f"{role} 看到的 {other} 没写交付物：{line[:200]}"
            first = next((str(x) for x in ob.boundary if str(x).strip()), "")
            if first:
                assert first in line, f"{role} 看到的 {other} 没写边界：{line[:200]}"
        del brief


def test_M_sees_everyone_and_others_see_only_their_partners(registry: ToolRegistry):
    """判据（`draft/37` §109，用户口径）：M 看全体，其它角色只看可协作的同伴。

    用户逐字：「M 要看到所有人的简介，其它智能体只要看到可协作的同伴的简介，
    这些应该落成智能体可查阅的描述文件，毕竟怕只是开头注入提示词它们后面忘了」。
    两半都要钉：①范围（M 的伙伴表覆盖 A–H 全体；非 M 角色只覆盖自己的出边）；
    ②可查阅（提示词里要指到那份落盘的画像文件）。
    """
    m_line = _prompt("M", registry)
    for role in ("A", "B", "C", "D", "E", "F", "G", "H"):
        assert f"- {role}：" in m_line, f"M 的伙伴表里没有 {role}"
    assert AP.PROFILES_FILE in m_line, "M 的提示词里没有指到画像文件"

    for role in ("A", "B", "C", "D", "E", "F", "G", "H"):
        text = _prompt(role, registry)
        allowed = set(AP.partners_out(role))
        for other in ("A", "B", "C", "D", "E", "F", "G", "H"):
            bullet = f"- {other}：" in text
            assert bullet == (other in allowed), (
                f"{role} 的伙伴表与它的出边不一致：{other} 在表里={bullet}，"
                f"在出边里={other in allowed}")
        assert AP.PROFILES_FILE in text, f"{role} 的提示词里没有指到画像文件"


def test_the_profiles_file_lists_every_role_with_its_full_picture(tmp_path: pathlib.Path):
    """判据（`draft/37` §109）：画像文件必须逐角色给全（职责 / 交付物 / 边界 / 动作）。"""
    root = tmp_path / "ws"
    root.mkdir()
    path = AP.write_profiles(root, availability={"A": "wired"})
    assert path, "画像文件没写成"
    text = pathlib.Path(path).read_text(encoding="utf-8")
    for role in ("A", "B", "C", "D", "E", "F", "G", "H", "M"):
        brief = AP.ROLE_BRIEFS[role]
        assert f"## {role}：" in text, f"画像文件里没有 {role} 这一节"
        assert brief.deliverable in text, f"{role} 的交付物没进画像文件"
        for item in brief.boundary:
            assert item in text, f"{role} 的一条边界没进画像文件：{item[:40]}"
    assert "A" in text and "现在的接线态：wired" in text, "接线态那半没写进去"


def test_every_role_knows_M_and_the_escalation_rule(registry: ToolRegistry):
    """判据（`draft/37` §110，用户逐字）：非 M 角色要知道 M 的存在，
    并且明说「自己做不了、同伴也做不了 ⇒ 报告主控」。

    为什么单列一条：原来的文本只把 M 说成"找不在名单里的人时的中转站"
    （`subject` 固定「请代唤」）—— 那是"替别人办事"的口径；而"我自己办不了"是另一种情形，
    不明说就会出现"静默少做"或"把没做成的写成做成了"（第 7/8 趟都有过）。
    """
    for role in [r for r in ALL_ROLES if r != "M"]:
        text = _prompt(role, registry)
        assert "做不了就上报" in text, f"{role} 的提示词里没有上报规则"
        assert "M" in text and "主控" in text, f"{role} 的提示词里没有主控 M"
    assert "做不了就上报" not in _prompt("M", registry), "主控不需要向自己上报"


def test_the_profiles_file_header_carries_the_escalation_rule(tmp_path: pathlib.Path):
    """判据（`draft/37` §110）：画像文件（可查阅的那份）里也要写这条规则。"""
    root = tmp_path / "ws"
    root.mkdir()
    path = AP.write_profiles(root)
    text = pathlib.Path(path).read_text(encoding="utf-8")
    assert "做不了就上报" in text and "主控 M" in text, text[:200]


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


def test_roles_that_can_summon_a_are_told_its_index_is_english(registry: ToolRegistry):
    """能唤起 A 的角色必须被明确告知：A 的检索面是英文文献库。

    为什么值得一条判据：`providers.query_applicability` 对抽不出英文关键词的题面是
    fail-closed（`query_not_applicable_cjk`）。模型不知道这件事就会拿中文题面去唤起，
    拿回一个"这一问没发出去"的结果、却当成"没有这篇文献"（真机实测：`draft/28` §203
    的中文 description 把 `precise` 的查询清零，而两层闸门都不拦它）。
    这条判据同时钉住两半：有 A 这条边的角色要读到、没有这条边的角色不要读到
    （无差别地贴一句放之四海皆准的提示词，就是把提示词当噪音）。
    """
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        can_summon_a = "A" in AP.partners_out(role)
        assert ("英文关键词" in text) is can_summon_a, (
            f"{role}：partners_out 里{'有' if can_summon_a else '没有'} A，"
            f"而提示词里{'有' if '英文关键词' in text else '没有'}那句英文索引提醒")
        if can_summon_a:
            assert "query_not_applicable" in text, (
                f"{role} 的提示词没写清「这一问没发出去」的返回码，"
                "模型会把缺证据读成没有文献")


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


#: 官能分组测试用的注册表（与文件里其它用例同一份口径：不带 workspace_root，没有 fs 工具）。
REGISTRY = build_registry().registry

# ---------------------------------------------------------------- 官能的分量（v2）
#
# 这一组守的是"分清哪个要求描述哪个角色、哪些是共有的"：
# 把十项官能做成所有角色都一样的检查表，读起来是能力清单，实际抹平了分工。

def test_every_role_declares_an_emphasis_for_all_ten_faculties():
    """正控（分量表要完整）：每个角色对十项官能都有明确分量，且三档取值合法。"""
    names = [f for f, _w, _b in AP.FACULTIES]
    assert len(names) == 10, names
    for role in AP.roles_covered():
        table = AP.FACULTY_EMPHASIS.get(role)
        assert table is not None, f"{role} 没有分量表"
        assert sorted(table) == sorted(names), f"{role} 的分量表与十项官能对不上：{sorted(table)}"
        bad = {k: v for k, v in table.items() if v not in ("core", "minor", "denied")}
        assert not bad, f"{role} 的分量取值非法：{bad}"


def test_core_faculties_are_written_locally_and_denied_ones_are_written_as_forbidden():
    """正控（分量要落到文字上）：主战官能必须有这一岗的本地说明；不许的必须在禁列里。"""
    for role in AP.roles_covered():
        missing = [f for f, level in AP.FACULTY_EMPHASIS[role].items()
                   if level == "core" and (role, f) not in AP.FACULTY_LOCAL]
        assert not missing, f"{role} 的主战官能没有本地说明：{missing}"
        denied_missing = [f for f, level in AP.FACULTY_EMPHASIS[role].items()
                          if level == "denied" and (role, f) not in AP.FACULTY_LOCAL]
        assert not denied_missing, f"{role} 的禁止项没有写明理由：{denied_missing}"

        text = AP.faculties_text(role, REGISTRY)
        assert "主战官能" in text and "结构上不许" in text or "结构上不许" not in text
        for f, level in AP.FACULTY_EMPHASIS[role].items():
            if level == "core":
                # 主战官能那一行带层标签（`- 眼睛［代码保证］：`）：标签是"这一条靠什么保证"，
                # 所以这里按 `- 名字［` 判，而不是按 `- 名字：`。
                assert f"- {f}［" in text, f"{role} 的主战官能 {f} 没有出现在正文里"
            if level == "denied":
                head = text[text.index("结构上不许"):] if "结构上不许" in text else ""
                assert f"- {f}：" in head, f"{role} 的禁止项 {f} 没有落在禁列里"


def test_read_only_roles_do_not_advertise_hands_on_the_data_plane():
    """负控（不许把禁止写成能力）：C 与 H 的手是结构禁止的，正文不许给它们列可写工具。

    2026-10-02 用户裁定之后（`draft/37` §41），M 从这条判据里移出：
    它现在真拿到 6 件写工具（编排面 5 件 + `fs.write`），
    再把它印在"结构上不许：手"那一档里就与实情相反了 ——
    而"提示词与事实不一致"正是这一整个文件存在的理由。
    M 的那一半改由两条判据守：
    - 这里下面的 `test_the_conductor_hand_is_minor_not_a_forbidden_line`（档位与列位）；
    - `tests/test_conductor_tools.py::test_conductor_hand_line_lists_its_real_write_tools`
      （用带 workspace_root 的注册表，逐名核它列出的写工具与"不许出现在里面"的领域写工具）。
    """
    for role in ("C", "H"):
        assert AP.FACULTY_EMPHASIS[role]["手"] == "denied", role
        core_line = AP.faculties_text(role, REGISTRY)
        core_part = core_line[:core_line.index("结构上不许")] if "结构上不许" in core_line else core_line
        assert "- 手：" not in core_part, f"{role} 把'手'列进了主战官能：{core_part[-200:]}"
        assert "数据面上没有写工具" in core_line or "结构禁止" in core_line or "不产出领域对象" in core_line


def test_the_conductor_hand_is_minor_not_a_forbidden_line():
    """正控（`draft/37` §41 的用户裁定）：M 的「手」是次要官能，不许再印成"结构上不许"。

    为什么值得一条判据：这一档决定那句本地说明渲染到哪一段
    （主战 / 次要 / 结构上不许），而三段在提示词里的语气完全不同 ——
    档位写错时提示词会一边说"你有笔"、一边说"做了也不算数"。
    """
    assert AP.FACULTY_EMPHASIS["M"]["手"] == "minor"
    text = AP.faculties_text("M", REGISTRY)
    head = text[text.index("结构上不许"):] if "结构上不许" in text else ""
    assert "- 手：" not in head, f"M 的'手'仍然落在'结构上不许'那一段里：{head[:200]}"
    minor_line = next(ln for ln in text.splitlines() if "次要官能" in ln)
    assert "手＝" in minor_line, minor_line
    # 这一份注册表不带 `workspace_root` ⇒ 没有 fs 工具，那 5 件编排面写工具必须在列。
    for name in ("conductor.summon", "conductor.summon_many", "conductor.stop"):
        assert name in minor_line, minor_line
    assert "可改" in minor_line, minor_line


def test_the_shared_layer_is_named_once_and_identical_for_every_role():
    """正控（共有项只有一份）：共享层在每个角色里都点名，且文字逐字相同。"""
    note = AP.SHARED_FACULTIES_NOTE
    assert "证据契约" in note and "三态纪律" in note and "循环协议" in note
    assert "期刊体例" in note and "不是共享项" in note
    for role in AP.roles_covered():
        text = AP.faculties_text(role, REGISTRY)
        assert note in text, f"{role} 的官能段里没有共享层说明"


def test_roles_differ_in_emphasis_not_only_in_wording():
    """正控（真的分开了）：不同角色的分量表不许雷同，核心项集合也要不一样。"""
    cores = {role: {f for f, lv in AP.FACULTY_EMPHASIS[role].items() if lv == "core"}
             for role in AP.roles_covered()}
    assert len({frozenset(v) for v in cores.values()}) >= 4, f"核心官能集合太像：{cores}"
    assert "手" in cores["A"] and "手" not in cores["C"], "只读角色与写角色必须在这一项上分开"
    assert cores["E"] >= {"手", "能思辨", "有品味"}, cores["E"]
    assert cores["G"] >= {"手", "有品味", "高观点"}, cores["G"]
    assert cores["M"] >= {"耳朵", "能讨论", "能互动"}, cores["M"]


# ---------------------------------------------------------------- 层：提示词 vs 代码

def _resolve_anchor(anchor: str) -> Any:
    """把 `模块:属性` 解析成真实对象（取不到就抛，由用例报红）。"""
    import importlib

    mod_name, _, attr_path = anchor.partition(":")
    obj: Any = importlib.import_module(mod_name)
    for part in attr_path.split("."):
        obj = getattr(obj, part)
    return obj


def test_every_faculty_declares_its_layer_and_code_anchors_exist():
    """正控（分层的锚点必须真实）：声明了代码那一半的官能，锚点要能 import 到。

    这条判据防的是"口头声明"：写一句"由框架结构性保证"很容易，
    而锚点漂了（改过名字、搬过模块）就说明那句话已经不再对应任何代码。
    """
    names = [f for f, _w, _b in AP.FACULTIES]
    assert sorted(AP.FACULTY_LAYERS) == sorted(names), (
        f"分层表与十项官能对不上：{sorted(AP.FACULTY_LAYERS)} vs {sorted(names)}")
    for faculty, (layer, anchor) in AP.FACULTY_LAYERS.items():
        assert layer in ("prompt", "code", "both"), f"{faculty} 的层非法：{layer}"
        if layer == "prompt":
            assert anchor == "", f"{faculty} 声明为纯提示词，却给了锚点 {anchor!r}"
            continue
        assert anchor, f"{faculty} 含代码那一半，却没有锚点"
        assert _resolve_anchor(anchor) is not None, f"{faculty} 的锚点解析为空：{anchor}"


def test_structure_not_prompt_items_all_have_a_named_mechanism():
    """正控（不许把结构约束写成请求）：每一条"框架用结构保证"的事都要说清靠什么。"""
    assert len(AP.STRUCTURE_NOT_PROMPT) >= 6, AP.STRUCTURE_NOT_PROMPT
    for what, how in AP.STRUCTURE_NOT_PROMPT:
        assert what and how, (what, how)
        assert len(how) >= 8, f"{what} 的机制说明太短，读的人无法复核：{how!r}"
    text = AP.faculties_text("D", REGISTRY)
    for what, _how in AP.STRUCTURE_NOT_PROMPT:
        assert what in text, f"官能段里没有把结构保证的那条讲清楚：{what}"


def test_prompt_only_items_are_named_and_not_dressed_up_as_enforcement():
    """正控（也不许反过来）：纯提示词负责的事要点名，且不许写成"会被拒"。"""
    assert len(AP.PROMPT_ONLY) >= 4, AP.PROMPT_ONLY
    text = AP.faculties_text("A", REGISTRY)
    assert "只由你自己把握的事" in text
    for item in AP.PROMPT_ONLY:
        head = item[:6]
        assert head in text, f"提示词层的那一条没有点名：{item}"
    tail = text[text.index("只由你自己把握的事"):]
    for banned in ("会被拒", "一律拒绝", "结构性禁止你"):
        assert banned not in tail, f"纯提示词那一栏里出现了强制口吻：{banned}"


def test_the_two_layers_are_not_the_same_set():
    """负控（不许全都塞进一层）：两层都要有实质内容，且不是同一批条目。"""
    codeish = {f for f, (lv, _a) in AP.FACULTY_LAYERS.items() if lv in ("code", "both")}
    prompted = {f for f, (lv, _a) in AP.FACULTY_LAYERS.items() if lv in ("prompt", "both")}
    assert codeish and prompted, (codeish, prompted)
    assert codeish != prompted, "每一项都既代码又提示词，等于没有分层"
    assert "眼睛" in codeish and "高观点" in prompted
    assert "手" not in {f for f, (lv, _a) in AP.FACULTY_LAYERS.items() if lv == "prompt"}


def test_the_file_the_closing_gate_judges_is_named_in_the_prompt_that_writes_it():
    """判据与提示词同源（`draft/37` §137 补的那个洞）：门判的那份文件必须有人被告知过。

    实测（2026-10-04）：`closing` 按 `out/paper/ACCEPTANCE-CHECKS.json` 逐行算验收，
    而全仓此前没有一处（提示词、文档都没有）提到过这个文件名 ——
    于是"没写那份表"与"写了且全过"在收工门上长得一样，而写表的人根本不知道要写它。
    这条判据把"门与提示词同源"钉住：文件名换一处、另一处没跟，这里就红。
    """
    from agentflow import closing as CL

    name = CL.ACCEPTANCE_CHECKS_NAME.split("/")[-1]          # ACCEPTANCE-CHECKS.json
    brief = AP.ROLE_BRIEFS["M"]
    text = "\n".join([brief.duty, brief.deliverable, *brief.policy])
    assert name in text, f"M 的提示词里没有点名 {name}（而收工门按它判验收）"
    # 反面：这份文件不是给所有人的（G/H 的那条线由 PAPER_PACK 管），别顺手撒到每个角色
    others = [r for r, b in AP.ROLE_BRIEFS.items()
              if r != "M" and name in "\n".join([b.duty, b.deliverable, *b.policy])]
    assert others == [], f"这份文件只该在主控的brief里点名，却出现在：{others}"
