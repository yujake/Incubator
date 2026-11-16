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

import hashlib
import pathlib
import re
from dataclasses import replace
from typing import Any, Mapping

import pytest

from agentflow import agent_loop as AL
from agentflow import agent_prompts as AP
from agentflow import capabilities as C
from agentflow import judge as J
from agentflow import schema as S
from agentflow import userio as U
from agentflow.promptkit import Scope
from agentflow.tools import ToolRegistry, build_registry

#: 需要一份提示词的全部角色：可被召唤的 A-H 加主控。
ALL_ROLES: tuple[str, ...] = tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)

#: 这些用例给的任务与工作区（固定值：判据必须是确定性的）。
TASK = "把这条链路走一遍"
ROOT = "D:/x"

#: 伙伴条目：以角色字母开头、后接全角冒号的行。
#: 2026-10-22（新设 L）：字符集加上 `L` —— 它此前是 `[A-HMV]`，于是伙伴表里
#: `- L：…` 那一行被这条正则整行漏掉（读数看起来"主表里没有这一行"，而它确实在）。
_PARTNER_BULLET = re.compile(r"^- ([A-HLMV])：")
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
    """某个伙伴的条目行（描述那一行），不是接线态那一栏。

    2026-10-16：原先靠行里含 `可调用动作` 辨认 —— 那条口径撤掉之后，伙伴行只剩
    `- <角色>：<职责>；它交付：…`。而接线态那一栏也是 `- <角色>：<状态>`（同样以
    `- 角色：` 开头）⇒ 用"；它交付"这个只在描述行里出现的分段来区分。
    """
    hits = [
        line for line in lines
        if line.startswith(f"- {role}：") and "；它交付" in line
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

    真机读数（T1 第 3 趟）：`E.check_formal` 被派 8 次，6 次撞在 `import Mathlib` 报
    `unknown package 'Mathlib'` 上 —— 框架早就知道本机没装（`toolchain.mathlib_state()` 是 §82
    为这一轴做的读数），却从没写进模型看得见的地方；而 E 的提示词里那句"要 Mathlib 就显式传
    imports"在这台机器上是一句误导。

    判据分两半：① 每个角色的提示词里都有这一段，且没传读数时说"没有读到读数"（不许静默缺席 ——
    否则"我不知道"看起来像"本来就没有"）；② 传了读数时它逐字出现，且把探针换成两个替身正文跟着变
    （证明这一行是投影，不是写死的一句话）。"""
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
    AP2.reset_toolchain_readings()
    with_lean = AP2.toolchain_facts_text()
    assert "lean 4.7.0" in with_lean and "没找到工程根" in with_lean, with_lean

    monkeypatch.setattr(TC, "probe_checkers",
                        lambda **kw: {"checked": True, "available": [],
                                      "available_names": [], "probe_errors": [],
                                      "reason": "探测完成：环境里没有任何受支持的证明检查器",
                                      "looked_in": [], "sources": {}})
    AP2.reset_toolchain_readings()
    without = AP2.toolchain_facts_text()
    assert "没有任何受支持的检查器" in without, without
    assert without != with_lean, "换了探针读数、这一行却没变 ⇒ 它是写死的"
    AP2.reset_toolchain_readings()


def test_the_formal_writing_block_goes_to_whoever_holds_the_tool(registry: ToolRegistry):
    """`TOOLCHAIN_FORMAL` 只发给手上真有 `formal.*` 的角色（2026-10-22 起只有 L）。

    旧期望把这一段算在 E 头上（2026-10-22 改指向 L）：那时受众判据是
    `verify.check_formal`（E / F / G 三家都挂在工具面上），于是三家都被教"你怎么写 Lean
    源码"。业主 2026-10-22 第四批的口径是「所有受 Lean 开关控制的提示词 / 工具 / 动作
    一律指向 L」⇒ 受众判据收成 `formal.*`（`_writes_lean` 读的那一族），今天只有 L 占得上。
    桥接层真身 `verify.check_formal` 仍在 E/F/G 的工具面上（那是权限面，不动），
    但它不再决定"谁拿这一段"。

    两头都钉，因为两头的错法不一样：
      - 漏发（这一岗真做形式化的人没拿到口径）⇒ 重演 `draft/37` §89：8 次
        `check_formal` 里 6 次白撞 `import Mathlib`，而框架手里有读数；
      - 滥发（不做形式化的人也收到一段"怎么写 Lean 源码"）⇒ 提示词变噪音，
        而噪音的代价是"该看的那几句被淹掉"。
    """
    holders: list[str] = []
    for role in ALL_ROLES:
        sections = AP.prompt_audit(role, registry=registry, task=TASK,
                                   workspace_root=ROOT)["sections"]
        holds = any(s.name.startswith("formal.") for s in registry.for_role(role))
        assert ("TOOLCHAIN_FORMAL" in sections) is holds, (
            f"{role}：工具面上{'有' if holds else '没有'} `formal.*`，"
            f"而段表里{'有' if 'TOOLCHAIN_FORMAL' in sections else '没有'}那一段")
        if holds:
            holders.append(role)
    assert holders == ["L"], (
        f"持有 `formal.*` 的角色集合变了（现算：{holders}）⇒ 这一段的受众跟着变 —— "
        "不是判据坏了，是读数变了：改这一行之前先看那一岗的提示词是不是真的该拿到它")
    # 负控：E / F / G 不再拿这一段（这一条是这一批的正题）。
    # 为什么不在这里钉"它们手上还有 `verify.check_formal`"：2026-10-22 另一路把 E 的 Lean 侧
    # 写死停用（理由码 `formal_moved_to_l`）并把那一件从 E 的工具面上摘掉 —— 那是权限面的事，
    # 由 `tests/test_l_formalizes_what_b_says.py` 与冻结快照看，本判据只管"谁读怎么写"。
    for role in ("E", "F", "G"):
        sections = AP.prompt_audit(role, registry=registry, task=TASK,
                                   workspace_root=ROOT)["sections"]
        assert "TOOLCHAIN_FORMAL" not in sections, (
            f"{role} 又在读「怎么写 Lean 源码」那一段了 ⇒ 形式化又被算回它头上了")


def test_the_toolchain_line_says_to_pass_mathlib_when_the_probe_says_it_works(
    monkeypatch: pytest.MonkeyPatch,
):
    """判据：Mathlib 可用时，那一段必须说"显式传 `['Mathlib']`"，而不是叫你去写自足文件。

    真机读数（2026-10-05 T1 第 16 趟）：这一段在 Mathlib 可用时仍写死"`check_formal` 可达的写法是
    不 import Mathlib 的自足文件"，与现算读数直接打架，而模型信了它：`experiments` 里 8 次 formal
    全是 `imports=（默认：不注入任何库）`、全部 `compile_error`（检查器原话
    `failed to synthesize instance`），一条 proof 行都没落成。负控：读数说没装时，"自足文件"那句
    必须还在 —— 那一支的处置本来就该是它。

    2026-10-11（E 的迁移批）这一轴拆成两段：事实（`toolchain_facts_text`，全角色）与怎么写
    （`toolchain_formal_text`，持有 `verify.check_formal` 的角色）。这条判据因此同时钉住"拆干净了"：
    事实段里不再出现写法口径（否则九个不写 Lean 的角色照样读到它 ⇒ 拆了个寂寞），口径段里按读数给路。"""
    from agentflow import agent_prompts as AP2
    from agentflow import toolchain as TC

    probe = {"checked": True, "available": [{"name": "lean", "version": "4.7.0"}],
             "available_names": ["lean"], "probe_errors": [], "reason": "探测到 1 个",
             "looked_in": [], "sources": {"lean": "explicit_dir"}}
    monkeypatch.setattr(TC, "probe_checkers", lambda **kw: probe)
    monkeypatch.setattr(TC, "mathlib_state",
                        lambda *a, **k: {"checked": True, "root": "R",
                                         "umbrella_olean": "R/Mathlib.olean",
                                         "import_mathlib": "可用",
                                         "import_mathlib_probe": {"checked": True,
                                                                  "verified": True}})
    AP2.reset_toolchain_readings()
    facts = AP2.toolchain_facts_text()
    text = AP2.toolchain_formal_text()
    assert "'Mathlib'" in text and "imports" in text, text
    assert "不 import Mathlib 的自足文件" not in text, text
    # 事实段只报读数：它不该再夹一句"所以你该怎么写"（那是另一段的事）
    assert "显式传" not in facts and "自足文件" not in facts, facts

    # 负控：读数说没装 ⇒ 口径段改说自足文件（那一支本来就该是它）
    monkeypatch.setattr(TC, "mathlib_state",
                        lambda *a, **k: {"checked": True, "root": "",
                                         "reason": "没找到 Mathlib 工程根"})
    AP2.reset_toolchain_readings()
    text = AP2.toolchain_formal_text()
    assert "自足文件" in text, text
    assert "显式传 `imports: ['Mathlib']`" not in text, text

    # 负控：实测编译失败（根在、umbrella 在、但真编译过不去）⇒ 也说自足，
    # 且必须说清"这是环境问题，不是命题问题"（否则模型会据它改结论）
    monkeypatch.setattr(TC, "mathlib_state",
                        lambda *a, **k: {"checked": True, "root": "R",
                                         "umbrella_olean": "R/Mathlib.olean",
                                         "import_mathlib": "可用",
                                         "import_mathlib_probe": {
                                             "checked": True, "verified": False,
                                             "missing_imports": ["Std"],
                                             "status": "import_unavailable"}})
    AP2.reset_toolchain_readings()
    text = AP2.toolchain_formal_text()
    assert "自足文件" in text and "环境问题" in text and "Std" in text, text

    # 负控：探测没做成 ⇒ 不许猜（"没读到"与"没有"必须分得开）
    monkeypatch.setattr(TC, "probe_checkers",
                        lambda **kw: {"checked": False, "available": [],
                                      "available_names": [], "probe_errors": [],
                                      "reason": "没查成", "looked_in": [], "sources": {}})
    AP2.reset_toolchain_readings()
    text = AP2.toolchain_formal_text()
    assert "没做成" in text and "别猜" in text, text
    AP2.reset_toolchain_readings()


def test_the_parent_limits_block_goes_to_whoever_can_summon(registry: ToolRegistry):
    """`PARENT_LIMITS` 只发给派得出活的角色（`partners_out` 非空），两头都钉。

    为什么要有这一段（业主 2026-10-11 裁定 A：上限数字写、且现算）：
    `draft/104` §2.1 的真机读数 —— 四类上限在提示词里一个数字都没有，模型知道自己的
    `depth` 却不知道上限是 5、也不知道同时在飞最多 5 个（主控 20 个）；
    §2.8 接着说这四类上限在真机上从未触发，而第一失败形态是 `invalid_params`。
    把数字给它，它才会去规划。

    两头都钉的理由与 `TOOLCHAIN_FORMAL` 那条一样：漏发（真会派活的人没有数字）
    与滥发（出边为 0、连 `summon` 都发不出的角色读到"你能派几个"）都是错的。
    判据按 `partners_out` 现算，所以它钉的是"角色与能力表对得上"这件事。
    """
    holders: list[str] = []
    for role in ALL_ROLES:
        sections = AP.prompt_audit(role, registry=registry, task=TASK,
                                   workspace_root=ROOT)["sections"]
        can = bool(AP.partners_out(role))
        assert ("PARENT_LIMITS" in sections) is can, (
            f"{role}：出边{'非空' if can else '为空'}，"
            f"而段表里{'有' if 'PARENT_LIMITS' in sections else '没有'}派活上限那一段")
        if can:
            holders.append(role)
    # 2026-10-22：L 接上协作面（有出边）之后它也会读派活上限那一段 ⇒ 名单里多一个 L。
    # 2026-11-05（业主裁定「V 不应该有出边」）：V 也成了发不出 `summon` 的那一档 ⇒ 少一个 V。
    assert holders == ["A", "B", "D", "E", "F", "G", "H", "L", "M"], (
        f"能派活（出边非空）的角色集合变了（现算：{holders}）⇒ 这一段的受众跟着变 —— "
        "不是判据坏了，是能力表变了（发不出 `summon` 的实测是 C 与 V）")
    # 2026-10-20 业主裁定：改回 C 无出边、由 D 唤起 C ⇒ 这张表按原句恢复（又少了 `"C"`）。


def test_the_parent_limits_are_computed_from_the_policy():
    """数字必须从 `Policy` 现算，一个都不许写死（业主口径 C：从代码现算）。

    正控：换一个把四类上限都改掉的 `Policy` ⇒ 渲染出来的那一句跟着换；负控：缺省值一个字都不该
    出现在改过的那一段里 —— 写死的数字在"被覆盖过的 run"里就是谎话（`cli.py` 就传过 `wall_clock_sec`）。
    另钉两处口径：主控那一档来自 `DIRECT_CHILDREN_LIMIT_BY_ROLE`（100，同时把工人档 25 写出来做对照），而
    `wall_clock_sec=None` 那一支必须写成"这一次不限"（不是"限 0"，也不是不写 —— 业主裁定 B 的另一面：
    墙钟不缩短，但"没设"与"设为 0"必须分得开）。

    2026-10-15 改（承 `draft/123` 裁定 C4/C5）：缺省值整体抬高（`max_direct_children` 5→25、
    `max_concurrency` 4→16、`max_tasks_per_run` 200→5000、`wall_clock_sec` 900→14400、M 档 20→100），
    而这条判据里的字面量没有跟着改 ⇒ 它红了。改法刻意把新旧两套缺省值都放进负控：职责是"默认值
    不许被写死在渲染里"，所以凡是当期缺省值都不许出现在被覆盖过的那一段里 —— 只列旧值会在下一次抬阈值时再变成谎言。（同族教训：`test_refusal_family_numbers` 那份手写 code
    清单做"反真空"自相矛盾。）

    2026-10-24 补：链长那一格不再跟 C5 一起抬，业主原话「深度5的意思是假如M-W-X-Y-Z，
    Z就不能再派子代理」⇒ `max_chain_depth` 回到"链上 5 个代理"（台账口径 4 跳；
    更名与两种数法见 `policy.Policy` 的注释与 `policy.max_agents_on_chain`）；
    本判据不看那个数字（它要求数字一律现算），所以这一格改回来不影响它。
    2026-11-05 再补：业主把这一格抬到 6（逐字「将深度锁调到6，不然 M->D->F->A->B->V
    是做不到的」）⇒ 链上 7 个代理、台账 6 跳。判据仍然不看那个数字（渲染里一律现算），
    所以这一条不随它动 —— 动了反而说明有人又把缺省值写死回渲染里。
    """
    from agentflow import policy as POL

    odd = POL.Policy(max_chain_depth=9, max_direct_children=7, max_concurrency=3,
                     max_tasks_per_run=11, wall_clock_sec=None)
    text = AP.parent_limits_text(odd, "E")
    for want in ("7 个", "9", "3 个", "11 个", "这一次**不限**"):
        assert want in text, f"改过 Policy 之后这一段里没有 {want!r}：{text}"
    # 负控：旧缺省值（2026-10-15 之前）与当期缺省值都不许出现。
    stale_defaults = ("最多 5 个", "全局同时运行 4 个", "总数 200 个", "墙钟：900 秒",
                      "最多 25 个", "全局同时运行 16 个", "总数 5000 个", "墙钟：14400 秒")
    for stale in stale_defaults:
        assert stale not in text, f"这一段里还留着写死的缺省值数字 {stale!r}：{text}"

    # 主控那一档来自 DIRECT_CHILDREN_LIMIT_BY_ROLE；工人档来自 Policy.max_direct_children（两处都现算）
    m_text = AP.parent_limits_text(odd, "M")
    assert "最多 100 个" in m_text and "工人档是 7 个" in m_text, m_text
    assert "最多 7 个（" not in m_text, m_text

    # 默认 Policy 的那一支：工人档等于 Policy.max_direct_children ⇒ 不再补"工人档是…"那半句
    plain = AP.parent_limits_text(POL.Policy(), "E")
    assert "最多 25 个。" in plain and "工人档" not in plain, plain


def test_the_role_that_writes_the_acceptance_table_knows_every_controlled_kind():
    """广告面判据（D35）：写表的人必须拿到受控词表的逐字清单。

    真机读数（T2 第 7 趟 `projects/p6i-research-from-zero`）：M 的验收表 P1 用了 `manuscript_edited`，
    而那个从零工作区没有只读基线 `source/` ⇒ 那一行读数算不出来 ⇒ 整张表判没查成、`can_close=false`
    （七格里唯一红的那格其实是 `anchor`，而 `acceptance` 连读数都没留下）。词表不在 brief 里时写表
    就是猜；猜错一个名字废掉的是整张表，不是那一行 —— 所以按"词表里每一档都要在 brief 里出现"守。

    CC-09（list 半，2026-10-06）：从"名字出现过"升级为"清单 == 词表"。旧判据看不穿两件事：
    ① 平铺清单漏了某一档（而那档恰好在别处被提到 ⇒ 名字查得到 ⇒ 照样绿）；② 清单混进词表外的名字
    （提示词教人照清单挑 ⇒ 挑出框架不认识的档）。实测清单 30 项而词表 31 档（漏 `c_analysis_runs`）。
    现在解析那份清单与词表双向对拍（漏一档、多一档都红），并带两条反真空（解析不出 20 项以上 ⇒ 红；
    清单里有重复项 ⇒ 红）。"""
    from agentflow import agent_prompts as AP
    from agentflow import closing as CL

    brief = AP.ROLE_BRIEFS["M"]
    text = "\n".join([brief.duty, brief.deliverable, *brief.policy])
    missing = [k for k in CL.LEG_CHECK_KINDS if k not in text]
    assert not missing, f"这些受控档没进写表那个角色的 brief：{missing}"

    item = next((i for i in brief.policy if "受控档位逐字列在这里" in i), "")
    assert item, "找不到那份「受控档位逐字列在这里」的清单（判据不许因为找不到就通过）"
    seg = item.partition("逐字列在这里")[2].split("。")[0].replace("`", "")
    seg = seg.rsplit("：", 1)[-1]          # 去掉列表前那段括注
    listed = [p.strip() for p in seg.split("/") if p.strip()]
    assert len(listed) >= 20, f"清单只解析出 {len(listed)} 项 ⇒ 解析口径变了，先修判据：{listed}"
    assert len(set(listed)) == len(listed), f"清单里有重复项：{listed}"
    assert not sorted(set(CL.LEG_CHECK_KINDS) - set(listed)), (
        f"清单漏了这些受控档：{sorted(set(CL.LEG_CHECK_KINDS) - set(listed))}")
    assert not sorted(set(listed) - set(CL.LEG_CHECK_KINDS)), (
        f"清单里混进了词表外的名字（写表的人会照着它挑）：{sorted(set(listed) - set(CL.LEG_CHECK_KINDS))}")


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
    # 2026-10-13 业主口径：M 的第一步是"看工作区、认输入、据此排工作流"
    # 2026-10-13 业主当场更正：提示词里不要写业主的话，这一条就一句"先扫一眼工作区"
    assert "开工先扫一眼工作区" in text, text
    # 这一条只钉"别把业主那几句话抄进提示词"（别的条目里的历史括注不动）
    for quoted in ("不要刻意认为丢进来的都是论文", "其他内容不会是结构化的",
                   "做断点续跑就不担心了"):
        assert quoted not in text, f"提示词正文里抄了业主原话：{quoted!r}"

    # 2026-10-13 业主更正：审校链的中心是 B / H / V —— 三个角色各自的框都要写着它
    # 三格各自的那句"我在链上干什么"（业主 2026-10-13 更正后：不再抄原话，只留做法）
    chain_phrases = {"B": "你是审校这条链的第一环", "H": "你站在这条审校链的中间",
                     "V": "你是这条链的审阅环"}
    for role, phrase in chain_phrases.items():
        rb = AP.ROLE_BRIEFS[role]
        mine = "\n".join([rb.duty, rb.deliverable, *rb.boundary, *rb.policy])
        assert phrase in mine, f"{role}：提示词里没有「{phrase}」"
        assert "不是一种模式" not in mine, f"{role}：提示词里还抄着业主原话"

    # 2026-10-13 业主口径：两阶段分工（研究阶段不写论文）+ review 是一类任务且要落产物
    assert "两阶段的分工" in text and "所有角色都可能有任务" in text, text
    # 业主 2026-10-13 更正：审校不是一种模式，而是一条以 B / H / V 为中心的协作链 ——
    # 这一条钉的正是"M 有没有按这条链排期"，不是"表里有没有一行 review"。
    assert "以 B / H / V 为中心的协作链" in text, text
    assert "不是一种模式" not in text, "提示词里还抄着业主原话"
    assert "review_files" in text, text
    # D47：交付物按任务那句话说 —— "整理成论文"那一类要交出论文（T3 第 1 趟就是漏了这一句）。
    # 2026-10-13（`draft/117`）：口径从"必须建论文包"改成"让 G 自己写正文再编" ——
    # 业主裁定「paper_package 里那些东西都是古早废案了，我们要智能体写文章」。
    assert "交付物按任务那句话说" in text and "自己写正文" in text, text
    assert "doc.paper_compile" in text, text
    # D44：只立项不算推进 —— 这一句不写，M 就会像 T2 第 13 趟那样只 create_plan、不 step
    assert "F.step" in text and "只立项不算推进" in text, text
    # D45：子目标要带可检验形式 —— 不写，M 派的子目标就会被 I9 闸门挡在门外（F 一次都不调）
    assert "每条子目标都要带可检验形式" in text and "testable" in text, text
    # D48/D49：「交付清单」类任务的清单本体要落 documents；天然不适用的那一档写 na + 理由
    assert "清单本体是 `documents` 里的行" in text, text
    assert '"na": true' in text and "α" not in text, text
    # D52：调查/探索类任务要把 C 用起来，并把 c_analysis_runs 写进验收表
    assert "要把 C 用起来" in text and "c_analysis_runs" in text, text
    # D53：「看（关系分析）」是覆盖面的一环
    assert "研究链的五个环节" not in text, text
    assert "研究链的六个环节" not in text, text
    assert "研究链的八个环节" in text and "看（关系分析）" in text, text
    # D56：「闭（请求闭环）」是覆盖面的最后一环，且消费队列的那个动作要被点名
    # （它是个无参动作，名字本身说不出它是干什么的 —— T5 第 5 趟 M 从头到尾没派过它）
    assert "闭（请求闭环）" in text and "unfinished_request_rows" in text, text
    assert "`run_once`" in text and "`unfinished_request_rows`" in text, text
    assert "请求闭环" in text, text
    # D59：「交」那一环不许被 F 的计划推进顶掉，交付物本身要有一档读数
    assert "攻（攻坚推进）" in text and "交（手稿落盘）" in text, text
    assert "document_rows" in text and "顶掉它" in text, text
    # D60：检索那一腿要写"真的取回了什么"，且一条 no_results 要用规范术语重查
    assert "检索（真的取回）" in text and "retrieval_ok_rows" in text, text
    assert "规范术语" in text, text
    # D54：方法 → 档位的映射（做对了活、写错了档是 T5 第 3 趟的失败形态）
    assert "挑哪一档要看你实际做的是什么" in text, text
    assert "search_frontier_rows" in text and "exhaustive_search" in text, text


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
    """判据（`draft/37` §92）：提示词必须说清"核验的裁决与落库是两件事"。

    历次改指向：旧期望把这两步算在 E 头上 ⇒ 2026-10-22 改指向 L（`L.check_formal` 裁决 →
    `formal.record` 落库）⇒ 2026-10-24（业主：是否形式化由用户指定，指定之后 M 派 B、
    B 派 L）改成"读回执"：G / H / M 与 L 之间没有边，它们读的是 B 带回来的回执，
    所以这一段现在钉的是「回执的那几样」与「那两件事的分界」，而不是"去调哪个动作"。

    真机读数（第 6 趟）仍然成立：照着提示词派了 6 次裁决，其中两条真的 `verified=true`，
    而 `experiments` 表是 0 行 —— 因为裁决那一步只给结论、不落台账。于是随后 10 条
    proof 级断言一条都建不进 `documents`（FC-22 要 `exp:` 引用）。

    判据的形状：① 回执那四样（三态 / 原始输出 / 退出码 / `exp:<id>`）在提示词里；
    ② 必须写明"查过了"不等于"台账里多了一条证据"；③ 负控（事实那一侧）：
    `check_formal` 跑完之后 `experiments` 行数不变 —— 万一有人把它改成会写行，
    这条判据会红，提醒改提示词。"""
    paper_pack_roles = [r for r in ALL_ROLES if r in AP.PAPER_PACK_ROLES]
    assert paper_pack_roles, "没有角色拿到论文包那一段 ⇒ 这条判据失去对象"
    for role in paper_pack_roles:
        text = _prompt(role, registry)
        assert "`exp:<id>`" in text, f"{role} 的提示词没写回执里那个台账编号（FC-22）"
        assert "`verified=true` 只说明「这一次查过了」" in text, (
            f"{role} 的提示词没把「查过了」与「台账里多了一条证据」分开")
        assert "三态结论" in text, f"{role} 的提示词没写回执里的三态结论"
        assert "`unknown` 时那是**没查成**" in text, (
            f"{role} 的提示词没写 unknown 那一档怎么读（没查成 ≠ 两档结论之一）")

    # ---- 事实那一侧（负控）：`check_formal` 真的不写 `experiments`
    #
    # 2026-10-23 晚：这一格改量 L 的那条路（`formal.check_formal`；E 的动作整条摘掉了）。
    # 判据不变：裁决那一步只给结论、不落台账 —— 落库是 `formal.record` 的事。
    import tempfile
    from pathlib import Path as _P

    from agentflow.agent_l import AgentL
    from agentflow.store import Store

    ws = _P(tempfile.mkdtemp(prefix="formal-path-judge-"))
    st = Store(ws)
    st.init()
    l = AgentL(st)
    before = len(st.rows("experiments"))
    (ws / "t.lean").write_text("theorem judge_trivial : (1 : Nat) + 1 = 2 := rfl\n",
                               encoding="utf-8")
    l.check_formal(claim="判据：1+1=2", script_path="t.lean")
    assert len(st.rows("experiments")) == before, (
        "`check_formal` 现在会写 experiments 了？那提示词里那两句（裁决/落库分开）必须跟着改")


def test_l_is_told_to_read_the_ledger_then_write_the_lean_source(registry: ToolRegistry):
    """判据（`draft/37` §98 的真机读数，2026-10-22 改指向 L）：写 Lean 源码那一边的口径归 L。

    旧期望把这一条算在 E 头上（2026-10-22 改指向 L）：原名是
    `test_e_is_told_to_write_the_lean_source_into_the_workspace`，它要求 E 的提示词里
    出现 `fs.write` / `code/lean/` / `decide` / `不归约` / `sorry` / `改一处再试` /
    `checker_name` —— 也就是"E 被教怎么写 Lean 源码"。业主 2026-10-22 第四批之后 E 不再教
    这件事（它那一岗是实验与反例），这一段口径整条搬到 L 那一岗，于是判据的主语换成 L。

    真机读数（第 10 趟）仍然成立、而且正好是 L 的设计理由：两次裁决真的 `verified` 了，
    而源码只落在临时目录里 ⇒ 它既不是 `proof_location`、也没法交给下一步。裁决与落库之间
    只差"把源码写进工作区"这一步 —— 现在 L 的 `formalize` 一次成型（写盘 + 检查 + 三态），
    所以判据钉的是"它的提示词里要读到这条链"：

      - 输入是 B 登记的那一条（`statement_full` + `proof_text`，逐步对上）；
      - 落点是 `code/formal/<声明名>.lean`，检查器原话与真实退出码是唯一凭据；
      - 结论三态，`sorry` 堵不住（它编译得过，但框架逐字判"这不是证明"）。
    """
    text = _prompt("L", registry)
    for needle in ("statement_full", "proof_text", "逐步", "code/formal", "三态", "sorry"):
        assert needle in text, f"L 的提示词里没有提到 {needle!r}"
    # 负控：E 那一侧不再有"怎么写 Lean 源码"的落点口径（这一批的正题）
    e_text = _prompt("E", registry)
    for needle in ("code/lean/", "decide", "不归约", "checker_name"):
        assert needle not in e_text, (
            f"E 的提示词里还留着「怎么写 Lean 源码」的口径 {needle!r} ⇒ 形式化又被算回它头上了")


def test_every_action_in_the_partner_table_says_what_it_does(
        registry: ToolRegistry):
    """判据（2026-10-16 翻面，业主口径）：伙伴表里不许出现动作名与参数提示。

    原话逐字：「M 只是个派活的，对所有角色都一样，只根据它们的能力范围派活，不指定能力。
    M 能看到的只是各角色描述，看不到具体的工具箱与动作，但可在角色描述中暗示它各角色能干什么。」

    它取代了什么（`draft/39` §6.45 的 D56，2026-10-16 退场）：D56 当年加的是"每个动作带一句摘要"，
    理由是"无参动作只有一个名字 ⇒ M 从没派过 `A.run_once`，F 的请求 `r-0004` 整趟没人做"。那条判据
    的前提是"M 要点名动作"；2026-10-16 的口径把那个前提整个撤掉（M 只派活、动作由被派者自己选）
    ⇒ "让 M 看懂每个动作"不再需要，需要的是让 M 别去碰动作 ⇒ 判据方向翻转：动作名、参数提示、
    `可调用动作` 字样，一条都不许有。"""
    import re

    from agentflow import agent_prompts as AP

    ACTIONISH = re.compile(r"可调用动作|（必填")
    for role in ALL_ROLES:
        for other in AP.visible_partners(role):
            line = next((ln for ln in AP.partners_lines(role) if ln.startswith(f"- {other}：")), "")
            assert line, f"{role} 的伙伴表里没有 {other} 的条目"
            assert not ACTIONISH.search(line), (
                f"{role} 看到的 {other} 那一行又印了动作与参数：{line[:200]}"
            )


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
    """判据（`draft/37` §110 + `draft/104` §4.1）：非 M 角色要说清"做不了怎么上报"，
    而且收件人必须与代码一致（2026-10-11 改到直接父）。

    为什么单列一条：原来的文本只把 M 说成"找不在名单里的人时的中转站"
    （`subject` 固定「请代唤」）—— 那是"替别人办事"的口径；而"我自己办不了"是另一种情形，
    不明说就会出现"静默少做"或"把没做成的写成做成了"（第 7/8 趟都有过）。

    收件人那一半是 2026-10-11 的修正（`draft/104` §4.1 甲案，业主 2026-10-09 逐字
    「和父代理 A 交流即可」）：代码 `agent_loop._relay_recipient` 一直发给直接父
    （只有顶层 / 父那一行读不成才落回 M），而提示词还写着"发给主控 M" ⇒
    模型会照着自己那一版手动越级（中间那一层看不见，M 被当路由器）。
    """
    for role in [r for r in ALL_ROLES if r != "M"]:
        text = _prompt(role, registry)
        assert "做不了就上报" in text, f"{role} 的提示词里没有上报规则"
        assert "报告你的直接父" in text, (
            f"{role} 的上报规则没写收件人（要与 `_relay_recipient` 一致）："
            f"{text[-600:]}")
        assert "M" in text and "主控" in text, f"{role} 的提示词里没有主控 M"
    assert "做不了就上报" not in _prompt("M", registry), "主控不需要向自己上报"


def test_the_three_kinds_of_reference_are_told_apart(registry: ToolRegistry):
    """三种指称的总判据（`draft/104` §4.4）：台账号对账 / 名册名指称 / 实例标签分实例。

    为什么需要它：今天两处各说一半 —— 身份段渲染台账号并说"编号用来对账与回报"，
    而 `retire` / `interrupt` 只认名册名，那条纪律只写在受控拒绝的文案里
    （`agent_loop._do_retire` 逐字「绝对编码不是父子之间的指称」）⇒ 模型要犯一次错
    才读得到它。真机代价：拿台账号去 `retire` 白费一步；反过来对账时用名册名也对不上。

    受众与 `PARENT_LIMITS` 同一条判据（`partners_out` 非空）：能派活才有"我名下的子代理"，
    而 C 的出边是 0、一辈子没有子代理 ⇒ 名册名对它没有意义（`draft/104` §5.1 原写"全部"，
    这一处按业主口径 C「从代码现算」收窄，读数记在 `draft/103` §4.1b-8）。
    """
    holders: list[str] = []
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        sections = AP.prompt_audit(role, registry=registry, task=TASK,
                                   workspace_root=ROOT)["sections"]
        can = bool(AP.partners_out(role))
        assert ("COLLAB_NAMES" in sections) is can, (
            f"{role}：出边{'非空' if can else '为空'}，"
            f"而段表里{'有' if 'COLLAB_NAMES' in sections else '没有'}指称那一段")
        if not can:
            continue
        holders.append(role)
        for want in ("台账号", "名册名", "实例标签", "对账", "绝对编码"):
            assert want in text, f"{role} 的指称判据里缺 {want!r}"
    # 2026-11-05（业主裁定「V 不应该有出边」）：V 不再派得出活 ⇒ 名单里没有 V。
    assert holders == ["A", "B", "D", "E", "F", "G", "H", "L", "M"], holders
    # 2026-10-20 业主裁定：改回 C 无出边、由 D 唤起 C ⇒ 这张表按原句恢复（与上一条同口径）。


def test_blocked_is_not_a_substitute_for_reporting(registry: ToolRegistry):
    """`blocked` 与上报是两件事，都要做（`draft/104` §4.10 的文案修正）。

    原文只写"并且照旧上报一次"，容易被读成"二选一"（`blocked` 就替代了上报）——
    而代码侧两条路各管一半：`blocked` 让父知道这一支卡住（`conductor.note_blocked`
    ⇒ `subtree_blocked`），上报让有人知道缺口存在（会话/板项/问题落盘）。
    只做前者，缺口在系统里消失（三态纪律不允许）。
    """
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        assert "`blocked` 只管「我停下了」" in text, (
            f"{role} 的循环协议里没有那一句：{text[-500:]}")
        assert "两件事都要做" in text, f"{role} 的提示词里没写清 blocked 不是上报的替代"


def test_the_relay_instruction_names_the_same_recipient_as_the_code(registry: ToolRegistry):
    """代唤的收件人：提示词与代码必须说同一个人（直接父；顶层才是 M）。

    这条判据钉的是两侧一致，两侧各自的实现都在别处：
      - 代码侧：`agent_loop._relay_recipient`（`tests/test_the_relay_goes_to_the_parent.py`
        守着"发给直接父"这件事本身）；
      - 文本侧：本判据守"提示词不再教模型发给 M"。

    为什么值得一条：`draft/104` §4.1 记着这一处的历史 —— 提示词那两句是立项时的措辞
    （用户原话"至少要能向主控申请唤起别的智能体"），2026-10-09 的裁定改了收件人却漏了提示词。
    两侧不一致的代价不是报错，而是模型自己把越级做回来：M 被当路由器，
    真正的父那一层看不见这次申请。
    """
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        assert "直接父" in text, f"{role} 的提示词里没有「直接父」这个收件人口径"
        for stale in ("给主控（M）的代唤申请", "换目标为 M", "直接把 message 发给主控 M"):
            assert stale not in text, f"{role} 的提示词里还留着旧收件人的写法：{stale!r}"


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


#: 提示词里允许出现的"点号 token"但不是工具名的那些，逐条登记理由。
#: 判据：`test_the_prompt_never_names_a_tool_that_does_not_exist`。
#: 登记表的用途与 `test_secretary_prompt_alignment` 里那张表同形：豁免必须留下理由，
#: 而"表里某条已经不在提示词里"本身也要红（腐烂的豁免表＝看起来还在挡着什么）。
_NON_TOOL_DOTTED_TOKENS: dict[str, str] = {
    # 2026-10-24：L 的图论那一句点的不是工具，是模块里的函数（读自检第 ⑤ 步那条读数）。
    # 它不是 agentflow 工具表里的件，模型照着写不会得到 unknown_action（那是 Python 侧的读数口）。
    "leantoolchain.mathlib_reading": "模块函数不是工具：L 用来读第 ⑤ 步那条 Mathlib 读数的口",
    "fs.read": "真工具，但只在带 workspace_root 的注册表里 —— 本文件的夹具刻意不带（见文件头）",
    "fs.write": "同 fs.read",
    "fs.edit": "同 fs.read",
    "fs.list": "同 fs.read（M 的「看工作区、认输入」那一条口径里点名了它）",
    "fs.stat": "同 fs.read（同上）",
    "research.set_status": "真工具，但只在带 store 的注册表里（`research_tools.ALL_TOOLS`，"
                           "`roles=('D',)`）—— 本文件的夹具不带 store，`research_tools` 按契约"
                           "跳过（`tools/__init__.py:390`，原因记在 `build_registry().skipped`）。"
                           "口径的两个读数见 `draft/108` §四 CS-9：无 store 70/28 件、"
                           "带 store 83/41 件",
    "main.pdf": "文件名（编译产物），不是工具",
    "appendix.tex": "文件名（附录落点），不是工具 —— 它只用来把一件事说清：正文与附录都写在 `out/paper/main.tex` 这一份里",
    "documents.claims": "台账字段（documents 表的 claims 列），不是工具",
    # 2026-10-26（M 侧过时清理 #6）：`closure_reminders` 的读数路径。它是
    # `conductor.ledger(view="stats")` 返回的 `stats` 里那一格 —— 读数字段路径，
    # 不是工具（旧写法点过 `conductor.stats`，那件工具不存在）。
    "stats.closure_reminders": "读数字段路径（`conductor.ledger(view=\"stats\")` 的 `stats` "
                               "里那一格），不是工具",
    "documents.status": "台账字段（documents 表的 status 列），不是工具 —— H 的裁决正落在它上面"
                        "（`accepted` / `in_review` / `unresolved_review`，见 `draft/103` §4.1b-25）",
    "experiments.search_bound": "台账字段（experiments 表的 search_bound 列），不是工具",
    # 2026-11-04（p235 收口）：今晚三处新写的说明面点名了台账 / 读数里的字段名，不是工具 ——
    # 三条都是「表.列」或「行.键」形态，模型照着念读数不会拿到 `unknown_action`。
    # `observations.e_signature`：experiments 行的 observations 里那一格（E 的结构标记，不是签）；
    # `v_signature.sha256`：对应表那一行 v_signature 里的 sha256 键（G 的 `doc.mapping_cells` 读数）。
    # 2026-11-10（p273）：`statements.derived_from` 那一条退场 —— 它能被豁免是因为旧 C 题面的
    # 污染面说明拿它做对照，而 p273 把那一段换成了 `ledger.resolve` / `ledger.expand`
    # （局部树的依赖面由代码侧给，不再教 C 去比 `derived_from`）。豁免表腐烂会红，所以删掉。
    "observations.e_signature": "台账字段（experiments 行的 observations 里那一格：结构标记），不是工具",
    "v_signature.sha256": "对应表那一行的 v_signature 里的 sha256 键，不是工具",
    # 2026-11-16（p286，FC-27 的 H 补丁）：H 不再判 G8 回执那一句写的是
    # 「收工门从台账现算（`conductor.closing` 的 `readings.run_evidence`）」——
    # `readings.run_evidence` 是 `conductor.closing` 返回 dict 里的字段路径，
    # 不是工具（模型照着念读数不会拿到 `unknown_action`）。
    "readings.run_evidence": "读数字段路径（`conductor.closing` 返回的 `readings` 里那一格），不是工具",
    # 2026-11-01（审计 171 D-08 的修法）：D 的跨趟记忆落点。它与 `research.set_status` 同型 ——
    # 真工具，但只在带 store 的注册表里（`research_tools.ALL_TOOLS`、`roles=('D',)`），
    # 本文件的夹具不带 store ⇒ 那一组按契约跳过。它替换掉的是被 fs 保留表拒的
    # `reports/RESEARCH.md`（手写那一份只会撞 `reserved_framework_artifact`）。
    "research.write_note": "真工具，但只在带 store 的注册表里（`research_tools.ALL_TOOLS`，"
                           "`roles=('D',)`）—— 与 `research.set_status` 同一条契约，"
                           "本文件的夹具不带 store ⇒ 跳过",
    # 2026-11-01（审计 174 §1.3 那一族）：B 的说明面要指认「推断 proof_authors 的是哪个模块」，
    # 而那一句写的是模块文件（`proofauthors.py`）。它不是工具，也不该被读成工具名 ——
    # 判据 `tests/test_b_param_face_explains_proof_authors_and_kind.py` 逐字要求带 `.py`。
    "proofauthors.py": "文件名（模块文件），不是工具 —— B 的说明面用它指认推断那一格的是哪个模块",
    # 2026-11-06（p250，审计 2 的 1b 条）退役：这条登记的是 `retire_integrity.open_items`，
    # 而顶层根本没有这一格（根自己那一格叫 `root_open_items`，逐节点那一格才叫 `open_items`）。
    # 提示词已经改成「`retire_integrity` 的 `dirty` 非空 ⇒ `complete=false`」，那句话不再点
    # 任何「不是工具」的点号路径 ⇒ 本条登记随旧口径一起退役（本判据自己有反真空断言：
    # 登记表里每一条都必须仍在某一份提示词里 ⇒ 退役就是删掉，不是留着不报）。
    # 2026-11-01（审计 174 §1.3 的修法）：`autonomy.run_autonomous` / `policy.check` /
    # `policy.waves_of` / `quoteverify.check_quote` / `userio.ask_user` 五条已从提示词里删掉
    # （它们是模块函数，不是工具；照字面调只会拿 `unknown_tool`）⇒ 这五条登记也一起摘掉。
    # 判据 `test_the_prompt_never_names_a_tool_that_does_not_exist` 的"登记表里的 token 必须
    # 还出现在某一格"那一半就是这条清理的驱动。
    "verifications.cold_start_prompt": "同 autonomy.run_autonomous（V 那一格的入口说明："
                                       "它说清 V 走的是冷启动入口，不是工具）",
    "own.register_statement": "动作被包成的那一件工具（`AgentLoop._registry_with_own_action`：名字是 "
                              "`own.<动作名>`，只活在**被派那一趟的循环注册表**里 —— 按角色/按派活现装）。"
                              "基座 `build_registry()` 里没有它，本文件的夹具按基座渲染，所以扫不到；"
                              "它是真工具名（B 手册里的短名 `register_statement` 由 `_do_tool` 的别名格映到它，"
                              "判据见 `tests/test_own_action_tool.py` 那一组）",
    # 2026-11-10（T1）：B 的两个新动作，与 `own.register_statement` 同一条登记理由
    # （`own.*` 由 `_registry_with_own_action` 现装，基座注册表里本来就没有）。
    "own.land_manuscript": "B 的动作被包成的那件 `own.*` 工具（同 `own.register_statement`："
                           "基座 `build_registry()` 里没有，只在被派那一趟的循环注册表里现装）",
    "own.ingest_manuscript": "B 的动作被包成的那件 `own.*` 工具（同 `own.register_statement`："
                             "基座 `build_registry()` 里没有，只在被派那一趟的循环注册表里现装）",
}

#: "像工具名"的点号 token：反引号包着、两段都是小写标识符。
_DOTTED_TOKEN = re.compile(r"`([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)`")


def test_the_prompt_never_names_a_tool_that_does_not_exist(registry: ToolRegistry):
    """广告面不说谎：提示词里每个"像工具名"的 token 要么是真工具，要么登记过理由。

    真机代价（`draft/105` 的 B1/B2 + `draft/41`）：`unknown_action` 52 次，其中一部分就是提示词指名
    了一个不存在的工具 —— 从前写着"要发给某一个同伴看就用 `manuscripts.write`"（全仓没有这件工具：
    `manuscript_tools.py` 的表格逐字写着"它不是工具：走循环形状 handoff"）与"传话走留言
    （`message.send`）"（也没有这个名字，`message` 是形状）。批 Q1 把两处改成形状名，并加了这一条
    判据 —— 它是那两条的通用形式：与其为每个名字写一条短语探针，不如扫一遍十格提示词。

    两侧都钉：正控：十格提示词里抽得到 token（抽不到 = 扫描面坏了，不是"没有问题"）；对拍：每个
    token 要么在这一岗的工具面里，要么在 `_NON_TOOL_DOTTED_TOKENS` 里逐条登记过理由；反真空：
    登记表里每一条都真的还在提示词里（豁免表腐烂时红）。"""
    seen: dict[str, list[str]] = {}
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        for tok in _DOTTED_TOKEN.findall(text):
            seen.setdefault(tok, []).append(role)
    assert seen, "十格提示词里一个点号 token 都没抽到 ⇒ 扫描面坏了（不是'没有问题'）"
    tools = {str(s.name) for role in ALL_ROLES for s in registry.for_role(role)}
    unknown = {tok: roles for tok, roles in seen.items()
               if tok not in tools and tok not in _NON_TOOL_DOTTED_TOKENS}
    assert not unknown, (
        "这些 token 长得像工具名，却既不在工具面上、也没在 `_NON_TOOL_DOTTED_TOKENS` 里"
        f"登记理由（模型照着写会拿到 `unknown_action`）：{ {k: ''.join(v) for k, v in unknown.items()} }")
    stale = sorted(k for k in _NON_TOOL_DOTTED_TOKENS if k not in seen)
    assert not stale, f"登记表里这些 token 已经不在任何一格的提示词里了 ⇒ 摘掉它们：{stale}"


def test_the_tool_name_scan_can_actually_go_red(registry: ToolRegistry,
                                                monkeypatch: pytest.MonkeyPatch):
    """反负控：往提示词里塞一个不存在的工具名 ⇒ 上面那条判据必红。

    为什么单列一条：那一条判据的实现是"扫 + 对拍"，两侧都容易退化成恒真
    （抽不到 token 时 `unknown` 恒空；登记表写全时也恒空）。这里用注入证明它有分辨率 ——
    它正是批 Q1 抓到 `manuscripts.write` / `message.send` 的那种形态。
    """
    real = AP.system_prompt

    def patched(role: str, **kw: Any) -> str:
        return real(role, **kw) + "\n- 顺手写一句 `fake.tool_name` 看看\n"

    monkeypatch.setattr(AP, "system_prompt", patched)
    with pytest.raises(AssertionError, match="fake.tool_name"):
        test_the_prompt_never_names_a_tool_that_does_not_exist(registry)


def test_the_notebook_is_told_as_a_file_on_disk_not_as_session_local(registry: ToolRegistry):
    """草稿本（`note`）的存活期与可见性：提示词说的必须与代码一致（`draft/105` A14）。

    代码真身（`agent_loop.write_note` / `note_path`）：追加写 `<项目根>/notes/<角色>.md`
    —— 盘上的文件，收工后仍在；同一批还在会话记录里留一份（`agent_note` 带 `path`）。
    提示词从前写"`note` 只活在这一次会话里（别人看不到、收工后查不到）" ⇒ 两句都错：
    模型据此会以为"写了也没人看得到、过后也没了"，于是该用 `note` 记的东西不记
    （或者反过来，把要交接的事写进 `note` 当一个"私下留痕"用）。

    判据两侧一起钉：① 提示词里写的是代码里那个路径（目录名取自 `AL.NOTES_DIR_NAME`，
    不是抄一个字符串）；② 旧的两句"会话本地/过后查不到"不许再出现。
    """
    root = pathlib.Path("R")
    assert AL.note_path(root, "D") == root / AL.NOTES_DIR_NAME / "D.md", \
        "代码里草稿本的路径变了 ⇒ 这条判据的锚要跟着改（它引的就是这个函数）"
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        assert f"{AL.NOTES_DIR_NAME}/<你的角色号>.md" in text, (
            f"{role} 的提示词没说清草稿本落在哪（代码是 {AL.NOTES_DIR_NAME}/<角色>.md）："
            f"{text[-500:]}")
        for stale in ("只活在这一次会话里", "收工后查不到"):
            assert stale not in text, f"{role} 的提示词还在说 {stale!r} ⇒ 与盘上的事实相反"


def test_the_three_shapes_that_carry_more_fields_teach_all_of_them(registry: ToolRegistry):
    """`draft/105` 的 A3/A4/A5：三个形状各有"代码收了、提示词一个字没说"的字段。

    两侧一起钉（提示词说了 + 代码真的收）：只钉一侧时，两种错法都抓不到 ——
    教了一个不存在的字段（模型写了被拒），或者收了一个没教的字段（模型不知道该写）。

      - `summon_many` 的每一项：`brief` / `name` / `reuse`（与 `summon` 同三格）——
        一批里派三件不同的活时，各自的简介写在各自那一项里（`_decode_shape` 的 `extra` 字段）；
      - `message`：`reply_to` —— 回一条已经存在的对话 ⇒ 不再要求协作边
        （`message_admission` 的准入判据里它是第三个放行项）。这一条是"旁的角色先开口、
        你再回"这条路在提示词里唯一的落点，不写它模型就只能干看着；
      - `handoff`：`revises`（订正某一号，旧行保留）/ `why`。
    """
    # 代码侧①：解析器真的把这几个字段收进 payload
    shape, pay, problem = AL._decode_shape({"summon_many": {"targets": [
        {"role": "B", "action": "run", "params": {}, "brief": "甲", "name": "B1"}], "why": "w"}})
    assert shape == "summon_many" and problem == "", (shape, problem)
    assert pay["targets"][0].get("brief") == "甲", pay
    assert pay["targets"][0].get("name") == "B1", pay
    shape, pay, problem = AL._decode_shape({"message": {"to": "B", "subject": "s", "body": "b",
                                                        "reply_to": "m-0001"}})
    assert shape == "message" and problem == "" and pay.get("reply_to") == "m-0001", pay
    shape, pay, problem = AL._decode_shape({"handoff": {"to": "F", "summary": "s", "body": "b",
                                                        "revises": "0003", "why": "w"}})
    assert shape == "handoff" and problem == "", (shape, problem)
    assert pay.get("revises") == "0003" and pay.get("why") == "w", pay

    # 代码侧②：`reply_to` 的准入效果（提示词教的正是它）
    assert AL.message_admission("A", "C") != "", "A→C 没有协作边 ⇒ 应当被拒（这是前置事实）"
    assert AL.message_admission("A", "C", "m-0001") == "", "带 reply_to 应当放行"

    # 提示词侧：十格都要写到这两格；派得出活的角色还要写到 2b 的名册三格
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        for want in ("reply_to", "revises"):
            assert want in text, f"{role} 的提示词里没有 {want!r}"
        if AP.partners_out(role):
            assert "名册三格" in text, f"{role} 的 2b 段没写清每一项还能带哪三格"


def test_the_user_channel_is_told_as_conductors_only(registry: ToolRegistry):
    """`ask_user` 只有主控能用（`draft/105` A7）：提示词必须写清"谁可以问"与"别人怎么办"。

    代码真身（`agent_loop._do_ask_user` 第一句）：`if self.role != S.CONDUCTOR_ROLE:` ⇒
    返回受控拒绝，`problem = userio.ASK_NOT_CONDUCTOR`，并在 `note` 里给出替代路
    （"把未决问题写进你的最终结果交回召唤者，由主控汇总给人"）。
    提示词从前对所有角色讲 `ask_user` 怎么写，一个字没提"只有 M 能问" ⇒
    九个角色照着写、然后被拒（浪费一步，而且"该问的没问出去"在读数上看起来像"它没问"）。

    两侧一起钉：① 判据的锚是 `userio.ASK_NOT_CONDUCTOR` 这个常量（改名/删除时这条先红）；
    ② 十格都要写到"只有主控能直接用这个形状"与非主控的替代路（写进最终结果 / 交给 M 代问）。
    """
    assert U.ASK_NOT_CONDUCTOR, "userio 里那个'不是主控'的问题码不见了 ⇒ 这条判据的锚没了"
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        assert U.ASK_NOT_CONDUCTOR in text, (
            f"{role} 的提示词没说清'当面问用户'会被拒（码 {U.ASK_NOT_CONDUCTOR!r}）")
        assert "只有主控 M 能直接用这个形状" in text, (
            f"{role} 的提示词没说清谁可以问用户")
        assert "请它代问" in text, f"{role} 的提示词没给非主控的替代路"


def test_the_cold_start_role_is_told_it_has_two_entries(registry: ToolRegistry):
    """V 的真实入口是冷启动提示词（`draft/105` A26）：提示词要把两个入口的关系说清。

    代码真身：`agent_v/core.py::verify_proof` 用 `verifications.cold_start_prompt(...)`
    拼好问题直接问一次（`self._ask(prompt)`），读完结论就落台账；而 `system_prompt("V")`
    这一套循环只在有人 `--drive V.<动作>` 把它当循环角色驱动时才用得上
    （全仓没有生产路径渲染 `system_prompt("V")`，只有审计与判据面渲染十格）。

    受众从声明现算（`agent_prompts._is_cold_start_role`：实现类是 `agentflow.agent_v`），
    不写死 "V"；并断言 `verifications.cold_start_prompt` 真的存在（这条判据的锚）。
    两头都钉：走冷启动那一格必须写、别格不许写 —— 否则这句话会变成所有角色的噪音。
    """
    from agentflow import verifications as VR

    assert callable(getattr(VR, "cold_start_prompt", None)), (
        "锚点没了：`verifications.cold_start_prompt` 不在了 ⇒ 这条判据要先跟着改")
    holders: list[str] = []
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        cold = AP._is_cold_start_role(role)
        assert ("cold_start_prompt" in text) is cold, (
            f"{role}：实现类{'是' if cold else '不是'} `agentflow.agent_v`，"
            f"而提示词里{'有' if 'cold_start_prompt' in text else '没有'}那句入口说明")
        if cold:
            holders.append(role)
    assert holders == ["V"], f"走冷启动入口的角色集合变了（现算：{holders}）⇒ 受众跟着变"


def test_the_stop_rules_moved_out_of_the_loop_protocol_verbatim(registry: ToolRegistry):
    """「什么时候停」三条从循环协议里搬到 `PARENT_STOP`：搬走 + 逐字都在（两头钉）。

    `draft/104` §4.9 的口径：那三条（预算耗尽 / 原地打转 / 上报两档）与"预算耗尽才收工"是
    同一根轴上的话，原先分散在 16 条规则的三处；协作块族要求合成一块讲"什么时候停"。

    这条判据在段层判（不是抽出来在整篇文本里找短语）：
      ① `LOOP_RULES` 那一段里不再有这三条（搬走了）；
      ② `PARENT_STOP` 那一段里逐行都有（逐字搬的，不是重写的）；
      ③ 整个提示词里这三条各只出现一次（没搬重）。
    这样"搬"与"抄"分得开：抄的话 ① 会红；重写的话 ② 会红；两者都做的话 ③ 会红。
    """
    moved = [ln for ln in AP.PARENT_STOP_TEXT.splitlines() if ln.strip()]
    assert len(moved) > 10, f"搬出来那一段看着不像那三条规则：{moved[:3]}"
    keys = ("花销预算耗尽时你必须收工", "别原地打转", "干不了 / 干不着就上报")
    for role in ALL_ROLES:
        assembly = AP.role_prompt_registry(role, registry=registry, task=TASK,
                                           workspace_root=ROOT).assemble(Scope(role=role))
        texts = {s.name: s.render(assembly.scope) for s in assembly.sections}
        assert "PARENT_STOP" in texts and "LOOP_RULES" in texts, sorted(texts)
        stop, rules = texts["PARENT_STOP"], texts["LOOP_RULES"]
        for head in keys:
            assert head in stop, f"{role} 的 PARENT_STOP 里没有 {head!r}"
            assert head not in rules, f"{role} 的循环协议里还留着 {head!r}（那是抄不是搬）"
            whole = assembly.render()
            assert whole.count(head) == 1, (
                f"{role} 的提示词里 {head!r} 出现了 {whole.count(head)} 次 ⇒ 搬重了")
        for line in moved:
            assert line in stop, f"{role} 的 PARENT_STOP 少了一行：{line[:60]!r}"


def test_the_roster_usage_block_is_told_only_where_there_is_a_roster(registry: ToolRegistry):
    """名册的用法（`draft/104` §5.1 的 `PARENT_ROSTER`）：受众 + 四条用法都与代码一致。

    形状（协议第 8/9/10 条）讲"怎么写"，这一块讲"什么时候用哪个"。四条里两条有代码锚：
      - `_decode_shape`：`summon` 形状里写 `instance` 会被丢掉，而 `summon_many` 的每个 target
        留着它 ⇒ "真并发只有 `summon_many` + `instance` 一条路"这句话有依据；
      - `secretary.roster_add` 的 `reuse` 那一支是往对照表写一条 `bind`（把既有名字绑到新的
        task_id 上），而 `_do_summon` 每次都调 `conductor.summon(...)` 建新任务行
        ⇒ "`reuse` 复用名字、不复用名额"有依据。
    受众与 `PARENT_LIMITS` / `COLLAB_NAMES` 同一条判据（`partners_out` 非空）；C 的出边是 0
    ⇒ 它一辈子没有子代理，也没有名册可看。
    """
    _shape, pay, _problem = AL._decode_shape({"summon": {"role": "B", "action": "run",
                                                         "params": {}, "instance": "B#2"}})
    assert "instance" not in pay, f"`summon` 形状开始收 `instance` 了 ⇒ 这段话要重写：{pay}"
    _shape, pay, _problem = AL._decode_shape({"summon_many": {"targets": [
        {"role": "B", "action": "run", "params": {}, "instance": "B#2"}], "why": "w"}})
    assert pay["targets"][0].get("instance") == "B#2", pay

    for role in ALL_ROLES:
        text = _prompt(role, registry)
        sections = AP.prompt_audit(role, registry=registry, task=TASK,
                                   workspace_root=ROOT)["sections"]
        can = bool(AP.partners_out(role))
        assert ("PARENT_ROSTER" in sections) is can, (
            f"{role}：出边{'非空' if can else '为空'}，"
            f"而段表里{'有' if 'PARENT_ROSTER' in sections else '没有'}名册用法那一段")
        if not can:
            continue
        for want in ("快照不是现状", "复用名字，不复用名额", "真并发只有一条路", "停与退是两件事"):
            assert want in text, f"{role} 的名册用法那一块缺 {want!r}"


def test_the_five_bits_block_is_computed_from_evidencebits(registry: ToolRegistry,
                                                           monkeypatch: pytest.MonkeyPatch):
    """五元位那一段是现算的（业主口径 C）：真身在 `evidencebits`，提示词里不许抄一份。

    为什么这条判据的形态是"改真身、看渲染"而不是"对字符串"：抄一份进提示词的坏处不是
    当场红，而是以后漂（`verify.py` 第 13 段按 `BIT_LEDGERS` 派判据 ⇒ 判据与提示词各说
    一套时，模型按一套写、门按另一套判）。所以这里 monkeypatch 真身（加一位假位、改 owner）
    来证明渲染确实跟着走 —— 写死的话这一段不会变。
    """
    from agentflow import evidencebits as EB

    text = AP.collab_fivebits_text()
    for bit in EB.BIT_NAMES:
        meta = EB.BIT_LEDGERS[bit]
        for want in (bit, str(meta["owner"]), str(meta["ledger"])):
            assert want in text, f"这一段里没有 {want!r}（位 {bit} 那一行）：{text}"
    for state in EB.BIT_STATES:
        assert state in text, f"四态里没有 {state!r}"
    for grade in EB.GRADES:
        assert grade in text, f"等级里没有 {grade!r}"

    # 现算的正控：改真身 ⇒ 渲染跟着变（写死的话这一跳会红）
    monkeypatch.setitem(EB.BIT_LEDGERS, "fakebit",
                        {"owner": "ZZ", "ledger": "某张表（判据夹具）"})
    monkeypatch.setattr(EB, "BIT_NAMES", EB.BIT_NAMES + ("fakebit",))
    grown = AP.collab_fivebits_text()
    assert "fakebit" in grown and "ZZ" in grown and "某张表（判据夹具）" in grown, grown

    # 受众：十个角色都有这一段（证据语法对所有人都要用）
    for role in ALL_ROLES:
        sections = AP.prompt_audit(role, registry=registry, task=TASK,
                                   workspace_root=ROOT)["sections"]
        assert "COLLAB_FIVEBITS" in sections, f"{role} 的段表里没有五元位那一段"


def test_the_board_block_teaches_the_boards_own_vocabulary(registry: ToolRegistry,
                                                           monkeypatch: pytest.MonkeyPatch):
    """工作项板那一段的四个词表是现算的（`draft/104` §5.1 的 `COLLAB_BOARD`）。

    真机口径（`draft/104` §2.8）：`tasks` 2276 行里板项 0 行 —— 机制在用
    （`open_items_of` / `mark_item_seen` 都接上了），而提示词从没讲过 `kind` / `expects` /
    `item_state` / `item_close` 这几个词的语义 ⇒ 模型拿着板项不知道怎么消它。

    判据的形态与五元位那条同源（改真身、看渲染）：词表抄错一个词，模型就会拿一个
    不存在的 kind 去收口 —— 那正是 `invalid_params` 那一族。所以这里也 monkeypatch 真身
    证明渲染跟着走，而不是对着字符串比。
    """
    from agentflow import schema as S

    text = AP.collab_board_text()
    for group in (S.ITEM_KINDS, S.ITEM_EXPECTS, S.ITEM_STATES, S.ITEM_CLOSES):
        for word in group:
            assert f"`{word}`" in text, f"这一段里没有 {word!r}（词表 {group}）"
    assert "ack_unbacked" in text, "没写「没读就 ack」那一条读数"
    assert "板项不是子代理" in text, "没写两条轴的分工（板项 ≠ 名册里的子代理）"

    monkeypatch.setattr(S, "ITEM_KINDS", S.ITEM_KINDS + ("judgefake",))
    grown = AP.collab_board_text()
    assert "`judgefake`" in grown, f"词表变了而这一段没变 ⇒ 它是抄的：{grown}"

    for role in ALL_ROLES:
        sections = AP.prompt_audit(role, registry=registry, task=TASK,
                                   workspace_root=ROOT)["sections"]
        assert "COLLAB_BOARD" in sections, f"{role} 的段表里没有工作项板那一段"


def test_every_shape_has_a_name_in_the_prompt_and_a_line_in_the_chooser(
        registry: ToolRegistry):
    """十一种形状：每一种都要在提示词里有名字，`COLLAB_SHAPES` 那张决策表要在（现算）。

    两侧都由代码说话：形状集合取自 `agent_loop.SHAPES`（加一个形状时这一条会告诉你
    "提示词里还没有它的名字"）；受众那条按 `partners_out` 现算 —— 出边为空的角色（实测 C）
    拿到的是 `2b)` 的残桩，里面按设计不出现 `summon_many` 这个键
    （那一档一个伙伴都唤不动），所以它的期望集合少一个。
    """
    shapes = tuple(AL.SHAPES)
    assert len(shapes) == 11, f"形状数变了（现算 {len(shapes)} 个）⇒ 这条判据的期望要跟着改"
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        sections = AP.prompt_audit(role, registry=registry, task=TASK,
                                   workspace_root=ROOT)["sections"]
        assert "COLLAB_SHAPES" in sections, f"{role} 的段表里没有那张决策表"
        expect = set(shapes) if AP.partners_out(role) else set(shapes) - {"summon_many"}
        missing = sorted(s for s in expect if f'"{s}"' not in text and f"`{s}`" not in text)
        assert not missing, (
            f"{role} 的提示词里没有这些形状的名字：{missing}（形状集合现算自 `SHAPES`）")
        if not AP.partners_out(role):
            assert '"summon_many"' not in text, (
                f"{role} 出边为空却读到了 `summon_many` 的键 ⇒ 残桩机制坏了")


def test_no_prompt_claims_a_step_limit_and_the_actionless_role_is_told_why(
        registry: ToolRegistry):
    """两件同族的"读起来像另一个人写的"（`draft/106` §4 第 3 块 + `draft/105` A21 的第三处）。

    ① 没有哪一格说"步数有限"：框架不设步数闸（`max_steps` 只是报告阈值，12-K 裁定与 `agent_loop` 的
    注释都这么写），协议里那句"步数不是收工理由"才是真的。`specs/m.py` 曾有两条政策拿"步数有限"当前提
    （"步数有限：现状侦察最多做一次…"与"步数预算有限，留出最后几步…"）—— 而同一份提示词的协议里写着
    "框架不设步数闸" ⇒ 一格里两句互相矛盾（批 R1 改掉）。这条判据钉两头：旧前提不许留（含"步数预算
    有限"这种换词写法 —— 只判那四个字会漏掉它）、真话必须在。

    ② 0 个对外动作的角色（现算：`actions_lines(role)` 空 ⇒ 实测只有 M）要读到"这是设计，不是缺口"
    与它的三张面（对用户 / 对同伴 / 对框架）—— 原来那句"你没有对外可被调用的动作（你的产出由框架
    直接读）"读起来像缺省值、像在说"我什么都做不了"（`draft/103` §5.2 第 2 条点过；`draft/106` §4 的
    `M_DELIVERABLE`）。"""
    #: "步数…有限"的几种写法都算命中：中间那几格是"预算"这类修饰语。
    claims = re.compile(r"步数[^。；，、\n]{0,4}有限")
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        hit = claims.search(text)
        assert hit is None, (
            f"{role} 的提示词里还写着「{hit.group(0) if hit else ''}」"
            "⇒ 与同一格里的「框架不设步数闸」矛盾")
        assert "步数不是收工理由" in text, f"{role} 的提示词里没说清步数不是收工理由"
    actionless = [r for r in ALL_ROLES if not AP.actions_lines(r)]
    assert actionless == ["M"], f"没有对外动作的角色集合变了（现算：{actionless}）"
    m_text = _prompt("M", registry)
    assert "这是设计，不是缺口" in m_text, (
        "M 那格还是那句像缺省值的「你没有对外可被调用的动作」")
    for face in ("对用户", "对同伴", "对框架"):
        assert face in m_text, f"M 的三张面里缺 {face!r}"


def _hint_text(line: str) -> str:
    """参数提示那一段（从"（必填"到它配对的"）"）。

    为什么要单独取这一段而不是直接在整行里找键名：工具摘要的散文里可能出现与键同名的词
    （`project` / `limit` / `to` 这类），在整行里判"可选键没出现"会误红。
    """
    start = line.find("（必填")
    assert start >= 0, f"这一行没有参数提示：{line}"
    end = line.find("）", start)
    assert end > start, f"参数提示没有收尾括号：{line}"
    return line[start:end + 1]


def test_every_tool_on_the_face_is_listed_with_its_required_parameter_keys(registry: ToolRegistry):
    """工具面上的每件工具都必须在提示词里，且参数提示列出必填键、且只列必填。

    口径变更（2026-10-07，R6 `draft/63 §2-①②`）：参数提示从"必填 + 可选枚举"改成只列必填。改前那条
    断言的依据是一次真机事故 —— 模型按只列必填的提示词多传了一个键、拿到 `invalid_params`（本文件
    这条判据的 docstring 原来逐字记着它）。那次事故现在的接住方是：可用键是封闭集合、写错时框架把
    完整参数表回给你（LOOP 规则①里各写一次）；兜底本体 `agent_loop._param_table`（`tool` / `summon` /
    `summon_many` 三条形状全覆盖），判据在 `tests/test_param_table_on_refusal.py`；本族口径的守卫在
    `tests/test_prompt_param_hints.py`（可选枚举回到提示词里必红）。

    为什么要换：那串枚举是十角色合计 10,458 字符，而每一次运行的每一步都要重付这笔钱；兜底那张表
    只在写错时付一次。若这条破了：模型会去调一个不存在的工具名，或者连必填键都不知道 —— 后者连
    兜底都救不了（被拒之前它根本凑不出一次合法调用）。"""
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        lines = text.splitlines()
        for spec in sorted(registry.for_role(role), key=lambda s: s.name):
            line = _line_of(lines, f"- {spec.name}：")
            properties = sorted(str(key) for key in (spec.params.get("properties") or {}))
            required = {str(key) for key in (spec.params.get("required") or [])}
            hint = _hint_text(line)
            for key in sorted(required):
                assert key in hint, f"{role} 的工具 {spec.name} 漏了必填参数 {key}：{line}"
            assert _required_in_hint(line) == required, line
            # 参数提示的精确形状（改了形状就必须改这条判据 —— 顺带把"可选键又回来了"堵死）。
            #
            # 为什么用精确相等而不是"可选键名不许出现"：那是子串判断，会被包含关系骗到 ——
            # 实测（本判据第一次跑）`doc.compose_claim` 的必填里有 `evidence_kind`、可选里有
            # `kind`，于是"kind 没出现在提示里"当场为假，报了一条假红。
            req_list = [str(key) for key in (spec.params.get("required") or [])]
            expected = "（必填 " + ("、".join(req_list) if req_list else "无")
            if not properties:
                expected += "；不许传任何参数"
            else:
                # 2026-11-01（业主裁定 + 审计 174 §1.2）：可选键用 `?key` 紧凑列在必填之后。
                # 形状仍是精确相等（改形状就必须改这条判据），只是多了一段可选的尾巴 ——
                # 于是「可选键静默消失」也会在这里红，而不是只靠 test_prompt_param_hints。
                opt_list = [k for k in properties if k not in required]
                if opt_list:
                    expected += "；可选 " + "、".join("?" + k for k in opt_list)
            expected += "）"
            assert hint == expected, (
                f"{role} 的工具 {spec.name} 的参数提示形状变了：\n  现场 {hint}\n  应为 {expected}"
            )


def test_partner_bullets_follow_the_edge_table(registry: ToolRegistry):
    """伙伴条目 = "看得见的那些"；"唤不起的"必须逐条标出来。

    若这条破了：模型会去唤起一个边表不允许的伙伴（换回 forbidden_edge），或者根本不知道某条已经
    放开的边存在；不可召唤的角色还会误以为自己能被召唤。

    2026-10-10 口径更新（看两层，不再是一层）：改前是"伙伴条目恰等于出边"（一层）。裁定第 4 条之后
    主控的出边只剩六个，而 2026-10-09 的裁定又要求「M 要看到所有人的简介」—— 两句话同时成立 ⇒
    主控的条目是全体，其中唤不起的三个带「你唤不起它」标记。所以这条判据改成：① 条目恰等于
    `visible_partners`（不多不少）；② 看得见但唤不起的那些必须有标记（否则"看得见"会被读成"派得动"）；
    ③ 反真空：真的存在这样的角色（否则 ② 是空转）。"""
    gaps: dict[str, set[str]] = {}
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        expected = set(AP.visible_partners(role))
        got = _partner_bullets(text)
        assert got == expected, (
            f"{role} 的伙伴条目与「看得见的那些」不一致：多出 {got - expected}，"
            f"少了 {expected - got}"
        )
        unreachable = expected - set(AP.partners_out(role))
        gaps[role] = unreachable
        for partner in expected:
            assert f"- {partner}：" in text, f"{role} 缺伙伴条目 {partner}"
            line = next(ln for ln in text.splitlines() if ln.startswith(f"- {partner}："))
            assert ("你唤不起它" in line) == (partner in unreachable), (
                f"{role} 看到的 {partner}：标记与出边不一致（在出边里={partner not in unreachable}）"
                f"：{line[:160]}")
        if unreachable:
            assert "只能间接由父代理转达" in text, f"{role} 有唤不起的伙伴，却没写那句话"
        if role in C.NON_SUMMONABLE:
            assert "不可以被任何人唤起" in text, f"{role} 不可召唤，但提示词没写"
    # 反真空：这一批就是因为主控有"看得见、唤不起"的角色才加的。
    # 2026-10-13：业主「补 M 到 B」之后，主控唤不起的从 {B,F,V} 收成 {F,V}；
    # 2026-10-18：业主「给 M 开 V 出边」之后只剩 {F}；
    # 2026-10-20：业主撤掉 `M→V`（「派 V 只有 F 与 B 两个入口」）⇒ 回到 {F, V} ——
    # 而这一条必须非空，否则下面那句"看得见但唤不起"的判据整体空转
    # （`gaps[M]` 为空时它一句都不验）。期望值跟着裁定走，判据强度不变。
    # 2026-10-22（新设 L + 只有 F→L 一条边）：M 看得见 L（伙伴表印全体简介），但唤不起它 ——
    # 与 F / V 同一档，都必须在条目上带「你唤不起它」标记。
    # 2026-10-24（业主：是否形式化由用户指定 ⇒ M 派 B ⇒ B 派 L）：L 那一行从主控的伙伴表里
    # 撤掉了 —— 它与主控没有边，而"经父代理转达"那条间接路对形式化不成立（许可在用户手上，
    # 执行人是 B）。所以"唤不起"那一档回到 {F, V}，判据强度不变（仍然非空）。
    assert gaps["M"] == {"F", "V"}, gaps["M"]
    assert gaps["M"], "主控的『唤不起』集合空了 ⇒ 这一整条判据退化成空转"
    assert not any(gaps[r] for r in gaps if r != "M"), \
        f"只有主控该有这一档（其余角色的条目就是出边）：{ {r: g for r, g in gaps.items() if g} }"


def test_roles_that_can_summon_a_are_told_its_index_is_english(registry: ToolRegistry):
    """能唤起 A 的角色必须被明确告知：A 的检索面是英文文献库。

    为什么值得一条判据：`providers.query_applicability` 对抽不出英文关键词的题面是 fail-closed
    （`query_not_applicable_cjk`）。模型不知道就会拿中文题面去唤起，拿回一个"这一问没发出去"的结果、
    却当成"没有这篇文献"（真机实测：`draft/28` §203 的中文 description 把 `precise` 的查询清零，
    而两层闸门都不拦它）。这条判据同时钉住两半：有 A 这条边的角色要读到、没有这条边的角色不要读到
    （无差别地贴一句放之四海皆准的提示词，就是把提示词当噪音）。

    探针钉的是"对唤起者说的那句"（`唤起 A 时注意`），不是"英文关键词"这个词：2026-10-11 接线批 C1
    之前它钉的是词，而 A 自己的第一段写死的正文（`presets/roles/a/blocks/search_style.md`，段名
    `A_SEARCH_STYLE`）里合法地写着"`topic` 里要带英文关键词" —— 那是对 A 自己说的，与这句对唤起者
    说的不是同一句，钉词会变成假红（实测：`p68` 时 A 的 `partners_out` 里没有 A，而提示词里有这个词 ⇒ 判据红）。要守的性质是"谁读到了这句提醒"，主体是收件人（`draft/105`
    已登记这一形态）。"""
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        can_summon_a = "A" in AP.partners_out(role)
        told = "唤起 A 时注意" in text
        assert told is can_summon_a, (
            f"{role}：partners_out 里{'有' if can_summon_a else '没有'} A，"
            f"而提示词里{'有' if told else '没有'}那句对唤起者说的英文索引提醒")
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
    """接线态换了落点（2026-10-21 第二批）：从 system 的 `PARTNER_AVAILABILITY`
    挪进开场那条 user 消息；system 里只剩一句静态指路语。

    为什么挪：这一段逐字节跟着伙伴配置变 ⇒ 它是 system 里第 63% 处的断点（M 岗实测 32,568 / 51,935），
    换个配置就砍掉 37% 的前缀。判据
    `tests/test_cross_run_prefix_is_reused.py::test_two_partner_configs_render_the_same_system`
    是它的端到端版本（十角色、两次渲染逐字节比对）；这一条守的是同一个落点上的三件事：

    ① system 里永远有那一句指路语（不管给没给读数 —— 段的有无不许随配置变）；② 给了读数时，逐个
    伙伴的 `- X：状态` 与"没接线的那个会被拒"那句都在开场那条 user 消息里
    （`agent_loop._opening_transcript`）；③ 伙伴行里不再夹带"（现在没接线：X）"这个逐配置动的标记。
    三态照旧：`availability=None` 时 user 消息里必须写"（没有读数…）"，不许把"没读到"与"全都接线了"折叠成同一句话。"""
    availability = {
        "A": "no_provider",
        "B": "wired",
        "C": "no_key",
        "D": "wired",
        "E": "wired",
        "F": "wired",
        "G": "wired",
        "H": "wired",
        # V（F-02 起）：`host.wiring_status` 是按 `schema.ROLES` 逐角色给的，
        # 所以这份夹具也必须含 V —— 少了它，F 的伙伴条目（`F → V` 那条边）
        # 会在这里 KeyError，而那不是"V 没接线"，是夹具没跟上角色表。
        "V": "wired",
    }
    from agentflow.agent_loop import _opening_transcript

    for role in ALL_ROLES:
        text = _prompt(role, registry, availability=availability)
        audit = AP.prompt_audit(role, registry=registry, task=TASK, workspace_root=ROOT,
                                availability=availability)
        # ① system 里那一段在，但只是一句指路语（逐字节静态，见下一条判据）。
        assert "PARTNER_AVAILABILITY" in audit["sections"], audit["sections"]
        assert "见本次对话第一条消息的「现在的接线态」那一栏" in text, role
        # ③ 伙伴行里不再夹带逐配置动的标记。
        for partner in AP.partners_out(role):
            bullet = _partner_bullet_line(text.splitlines(), partner)
            assert "现在没接线" not in bullet, bullet
        assert "（现在没接线：" not in text, f"{role} 的 system 里还有逐配置动的接线态标记"

        # ② 真值在开场那条 user 消息里：逐伙伴一行，且"没接线的会被拒"那句跟着出现。
        opening = _opening_transcript(
            task=TASK, inbox="", summoned_by="user", task_id="t-a", depth=1,
            parent_task_id="", children="", board="", user_replies="",
            workspace_root=str(ROOT), availability=availability,
            parent_limits="（判据夹具）")
        for other, state in availability.items():
            assert f"- {other}：{state}" in opening, f"{role} 的开场消息里没有 {other}：{state}"
        assert "没接线的伙伴派了也会被拒" in opening, role

        # 三态：没给读数 ⇒ 一句"没有读数"，不是"全都 wired"。
        silent = _opening_transcript(
            task=TASK, inbox="", summoned_by="user", task_id="t-a", depth=1,
            workspace_root=str(ROOT), availability="", parent_limits="（判据夹具）")
        assert "没有读数" in silent and "wired" not in silent, silent
        # 而 system 那一句指路语两种情况下一字不差 ⇒ 给不给读数，system 逐字节相同
        # （比"段名在不在"更强：段的有无、内容都不许随配置变）。
        plain_audit = AP.prompt_audit(role, registry=registry, task=TASK, workspace_root=ROOT)
        assert "PARTNER_AVAILABILITY" in plain_audit["sections"], plain_audit["sections"]
        assert _prompt(role, registry) == text, (
            f"{role}：给不给 availability 读数，system 竟然不同 ⇒ 前缀仍随伙伴配置变")


# ------------------------------------------------ 角色减负的反真空（2026-10-21 事务二）
#
# 这一批从 A / B / C / E / G / H 的 `policy` / `local_notes` 里删掉了几条已有判据在守
# 的义务（逐条出处写在 `specs/*.py` 原处的 `判据：` 旁注里）。减负有一个射程：
# 身份 / 边界 / 上报路径 / 交接规则 / 不硬凑 / 必填字段一律不许碰 ——
# 那几类是安全与正确性，判据替不了它们（判据只能事后抓，抓不到"它根本不知道该向谁上报"
# 这种形态：那时模型会把没做成的写成做成了，而没有任何门会响）。
#
# 所以减负必须配一条反真空：删完之后，每个角色的提示词里仍然读得到这四类锚点，
# 逐角色断言。只断言"某几个角色还在"就会给"顺手删过头"留一条缝。

#: 四类锚点各自的读法（都是逐字锚，不是关键词模糊匹配）。
_ANCHOR_KINDS: dict[str, tuple[str, ...]] = {
    "身份": ("号角色，职责是：",),                      # `AGENT_IDENTITY`
    "上报": ("干不了 / 干不着就上报",),                 # `PARENT_STOP`（十个角色都有）
    "交接": ("交接手稿（handoff；交接工作前的标准动作",),  # `HANDOFF_PROTOCOL`
}
#: 「边界」不能只认抬头那一行：`brief_sections` 在 `boundary=()` 时只印抬头
#: （实测：`'边界（这些是硬约束，越过它们做的事一律不算数）：\n'`）—— 只认抬头的话，
#: 有人把边界条目整批删掉也判绿，那正是这条反真空要抓的形态。
_BOUNDARY_HEADER = "边界（这些是硬约束"


def _boundary_still_lists_a_clause(text: str) -> bool:
    """边界那一段还在、且真的列了条目（抬头后面紧跟着 `- ` 那几行）。"""
    lines = text.splitlines()
    head = next((i for i, line in enumerate(lines) if line.startswith(_BOUNDARY_HEADER)), None)
    if head is None:
        return False
    return any(line.startswith("- ") for line in lines[head + 1:head + 4])


def _missing_anchors(text: str) -> list[str]:
    """这段提示词里缺哪几类锚点（空 = 四类都在）。判据本体只这一处。"""
    missing = [kind for kind, needles in _ANCHOR_KINDS.items()
               if not all(needle in text for needle in needles)]
    if not _boundary_still_lists_a_clause(text):
        missing.insert(0, "边界")
    return missing


def test_every_role_still_carries_the_four_anchor_kinds(registry: ToolRegistry):
    """判据（减负的反真空）：十角色逐个都还读得到身份 / 边界 / 上报 / 交接。

    四类各取一句逐字锚（见 `_ANCHOR_KINDS`）：身份与边界回答"我是谁、不许做什么"，
    上报回答"做不了时找谁"，交接回答"怎么把活交出去"。减负删的是"已有判据在守"的
    行为义务，这四类没有判据能替代 —— 删掉它们，模型不会报错，只会静默地少做。
    """
    # 反真空（判据自己）：四类名一个不少（"边界"由 `_boundary_still_lists_a_clause` 单独判）。
    assert sorted(_ANCHOR_KINDS) == sorted(("上报", "交接", "身份")), sorted(_ANCHOR_KINDS)
    checked: list[str] = []
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        missing = _missing_anchors(text)
        assert not missing, (
            f"{role} 的提示词里缺了 {missing} 这几类锚点 ⇒ 减负删过头了"
            "（身份/边界/上报/交接一律不许删）")
        checked.append(role)
    # 2026-10-22（新设 L）：角色数从 10 变 11 —— 这一条守的是「每个角色都还读得到四类锚」，
    # 所以对着 `ALL_ROLES` 的数判，不写死一个会随角色表漂的字面量。
    assert len(checked) == len(ALL_ROLES), checked


def test_deleting_a_safety_clause_makes_the_anchor_criterion_red(
        registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch):
    """负控（减负的反真空）：把删除范围扩大到安全条款 ⇒ 必红。

    两刀，各打在一条"判据替不了"的条款上：
    ① 把某个角色的 `boundary` 清空（那是它的边界，`AgentBrief` 的六格之一）；
    ② 把 `HANDOFF_PROTOCOL` 换成空串（那是交接规则，十格共享）。
    两刀都必须让 `_missing_anchors` 点名对应的那一类 —— 只报"少了点什么"不够，
    报不出是哪一类的话，读的人还得自己去比对三十万字的提示词。
    """
    from agentflow.agentspec import AgentBrief

    victim = "E"
    brief = AP.ROLE_BRIEFS[victim]
    assert isinstance(brief, AgentBrief), brief
    assert _missing_anchors(_prompt(victim, registry)) == []
    monkeypatch.setitem(AP.ROLE_BRIEFS, victim,
                        replace(brief, boundary=()))
    assert _missing_anchors(_prompt(victim, registry)) == ["边界"], (
        "清空 boundary 之后判据没点名「边界」⇒ 这条反真空抓不住扩大的删除范围")
    monkeypatch.undo()

    assert _missing_anchors(_prompt(victim, registry)) == []
    # ② 交接：把那份协议换成一份块数相同（2 块，`_block_sections` 按空行切、
    # 块数与 `_HANDOFF_BLOCK_NAMES` 不等会当场抛）但没有那句锚的正文 —— 于是
    # "交接手稿（handoff；交接工作前的标准动作" 不再出现，而提示词其余部分照常渲染。
    monkeypatch.setattr(AP, "HANDOFF_PROTOCOL",
                        "交接（探针）：锚点那一句被删掉了。\n\n规则（探针）：照旧。\n\n")
    assert _missing_anchors(_prompt(victim, registry)) == ["交接"], (
        "删掉交接协议里那句锚之后判据没点名「交接」")
    monkeypatch.undo()


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
    """提示词必须长到不像占位符，且循环形状、三态词表、逐字引文契约都在里面。

    若这条破了：一份被截断或退回模板的提示词照样"非空"，
    而模型从未被告知循环协议、三态纪律与引文契约 —— 它会输出散文，或者把被拒折成没问题。

    2026-11-05 改期望（p242）：`"summon"` 那一形只在有出边的角色上存在 —— 50c4a1d2
    把 V 的出边清空、C 本来就没有协作边，两份提示词于是改成「这一档你用不到 —— 你没有任何
    协作边」。旧期望要求十一格都有 `"summon"`，那会把一个用不上的形状硬塞回没有出边的
    角色（模型读到的是一份它做不到的教法）。这里改成从 `ALLOWED_EDGES` 现算：有出边的角色
    必须有那一形，没有出边的必须有那句「用不到」的残桩 —— 两个方向都判，不是删检查。"""
    from agentflow import capabilities as C

    for role in ALL_ROLES:
        text = _prompt(role, registry)
        assert len(text) > 800, f"{role} 的提示词只有 {len(text)} 字符"
        shapes = ['"tool"', '"message"', '"final"']
        if C.ALLOWED_EDGES.get(role):
            shapes.append('"summon"')
        else:
            assert "你没有任何协作边" in text, (
                f"{role} 没有出边（`ALLOWED_EDGES` 为空），提示词里却没有「你没有任何协作边」"
                f"这一句残桩 —— 模型要么读不到派活那一形、要么被教了一件它做不到的事")
        for shape in shapes:
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


# ---------------------------------------------------------------- L-05e：notify 的义务广告


#: L-05e 退场的那几句（代码侧先接住：收工侧不再打回、`no_notify` 不可达；
#: 派活侧形状不对就退回框架派生那一份、派活照常发生）。留着它们就是
#: "提示词在要求一件代码已经不要求的事"—— 模型会为一道不存在的闸门耗步数。
FORCED_NOTIFY_ADVERTISEMENT = ("no_notify", "打回重填", "强制留痕", "强制项", "框架不代填")


def test_the_forced_notify_advertisement_is_gone_from_the_prompt():
    """L-05e 的提示词半（`45 §2`：代码先接住、提示词后撤）：广告退场，只留事实口径。

    撤的是"强制 / 打回 / 会因此停"那层义务广告；留的是与代码一致的事实：
    填了且形状对 ⇒ 由这一趟的秘书执笔写成一行手稿并发给 `to`；
    没填或填错 ⇒ 不打回、照常收工，只是没有手稿，理由如实进读数（`notify_problem`）。

    反负控：把旧话术喂进同一个判据必须被认出来 —— 否则"没命中"与"判据坏了"分不开。
    """
    brief = AP.ROLE_BRIEFS["M"]
    prompt_side = "\n".join([AP.LOOP_PROTOCOL, brief.duty, *brief.boundary,
                             *brief.policy, *brief.stance])
    for word in FORCED_NOTIFY_ADVERTISEMENT:
        assert word not in prompt_side, f"L-05e 之后这句义务广告还在：{word!r}"
    # 事实口径留下（与 `agent_loop._do_handoff` / `notify_reading` 的现状一致）
    assert "秘书执笔" in AP.LOOP_PROTOCOL, AP.LOOP_PROTOCOL
    assert "不打回" in AP.LOOP_PROTOCOL, AP.LOOP_PROTOCOL
    assert "notify_problem" in AP.LOOP_PROTOCOL, AP.LOOP_PROTOCOL
    # 反负控：同一组词喂旧话术 ⇒ 必须逐个认出来
    old = ("主控（M）派活时**强制留痕**：带了 `notify` 但填错字段会被**打回重填**；"
           "收工不带 `notify` 的趟会以 `no_notify` 收场（`notify` 是**强制项**，"
           "**框架不代填**）。")
    assert [w for w in FORCED_NOTIFY_ADVERTISEMENT if w in old] == \
        ["no_notify", "打回重填", "强制留痕", "强制项", "框架不代填"], old
    # 代码侧的读数确实存在（提示词撤了，读数还在 —— 撤的是广告不是留痕）。
    # 代码侧"`no_notify` 已退场"的判据在 A 线的 `tests/test_forced_notify.py`（那里按源码行扫，
    # 不算注释）；本题只在提示词这一侧钉"广告已退场"，不重复钉代码侧。
    import inspect

    from agentflow import agent_loop as AL

    assert "notify_problem" in inspect.getsource(AL), "读数没接上：广告撤了、留痕也没了"


# ------------------------------------------------- 循环协议的形状表（必须与 agent_loop.SHAPES 同源）
#
# 这一组守的是一条量出来的缺陷：形状表的正典（`LOOP_PROTOCOL`）写"七种形状"、逐字列了 7 个，
# 而 `agent_loop.SHAPES` 是 8 个 —— 漏掉的正是 `handoff`。它不是"文字不齐"：
# `handoff` 是手稿落行的唯一形状入口（`_do_handoff`），而"没人写手稿"正是量过的形态
# （真机 1542 行里 967 行是框架派生、模型自写 0 行）。
#
# 为什么此前不会红：`test_prompts_are_anti_vacuous` 只按 `"tool"`/`"summon"`/`"message"`/`"final"`
# 四个带引号的键名在整份提示词里出现过，既不覆盖 `handoff`，也不看形状表那一段，
# 更不核数目 —— 于是"正典少一种形状"这件事在任何测试里都没有读数。
# 所以判据钉在两处现算上：名字逐个取自 `AL.SHAPES`，数目由 `len(AL.SHAPES)` 推出来。

#: 形状表那一段的锚点：起句取「每次只取其一」再往前退到行首（必须把「N种形状」那句整个包进来，
#: 否则数目对拍读不到东西 —— 那是"没查成"，不许当成"查过了没问题"）；
#: 收束句是「规则：」。两个锚点读不到就抛，不返回空串。
_SHAPE_TABLE_ANCHOR = "每次只取其一"
_SHAPE_TABLE_END = "\n规则："

#: 中文数词（`len(SHAPES)` → 文本里该出现的那个字）。
_CN_NUM = {1: "一", 2: "两", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九",
           10: "十", 11: "十一"}


def _shape_table(protocol: str = "") -> str:
    """切出一版循环协议里的形状表那一段（含表头那一行）。锚点读不到就断言失败。

    `protocol` 留空 = `LOOP_PROTOCOL`（主控那一版）。`R6` §2-⑥ 之后协议按角色渲染
    （`agent_prompts.loop_protocol_for`），所以"哪个角色的形状表"由调用方给 ——
    默认值只服务于"协议常量本身"那一条判据。
    """
    text = protocol or AP.LOOP_PROTOCOL
    anchor = text.find(_SHAPE_TABLE_ANCHOR)
    assert anchor >= 0, f"形状表的起句读不到（`{_SHAPE_TABLE_ANCHOR}`）"
    start = text.rfind("\n", 0, anchor) + 1
    end = text.find(_SHAPE_TABLE_END, anchor)
    assert end > start, f"形状表的收束句读不到（`{_SHAPE_TABLE_END}`）"
    return text[start:end]


def _shape_names_in(text: str) -> list[str]:
    """文本里逐字出现的形状名。带左右边界：`summon_many` 不许把 `summon` 冒充出来。"""
    return [n for n in AL.SHAPES
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", text)]


def test_loop_protocol_shape_table_lists_every_shape_the_loop_accepts():
    """形状表里十个形状名一个不缺，且数目与 `agent_loop.SHAPES` 现算一致。

    若这条破了：正典表少列一种形状，模型可能永远不写它，而框架照旧全绿 ——
    这一次少的是 `handoff`（手稿落行的唯一形状入口）。

    `== 11` 是本判据的提醒线（S1k-2 从 8 抬到 10：新增 `retire` / `roster`；
    S-H 从 10 抬到 11：新增 `interrupt`）：
    形状表被动过就得把它与提示词一起过一遍，别让下面的数目对拍变成对着旧数目对。
    """
    seg = _shape_table()
    assert len(AL.SHAPES) == 11, (
        f"形状表本身被动过了（`agent_loop.SHAPES` 现在有 {len(AL.SHAPES)} 个）⇒ "
        "先把这条判据与提示词一起过一遍，别让下面的数目对拍变成对着旧数目对")
    missing = [n for n in AL.SHAPES if n not in _shape_names_in(seg)]
    assert not missing, (
        f"循环协议的形状表里少了 {missing}（`agent_loop.SHAPES`={tuple(AL.SHAPES)}）—— "
        "形状表是模型看到的正典，少一种就等于那种形状在协议里不存在")
    want = _CN_NUM[len(AL.SHAPES)]
    # 数词那一格要连着读（`[一二三四五六七八九十]+`）：抬到 11 之后表头写的是「十一」，
    # 单字符的正则会读到"一" ⇒ 判据会把对的表判错（改这一处是因为形状数越过了十）。
    counts = set(re.findall(r"([一二三四五六七八九十]+)种形状", seg))
    assert counts == {want}, (
        f"形状表里的数目是 {sorted(counts) or '（读不到中文数目）'}，而 `agent_loop.SHAPES` "
        f"有 {len(AL.SHAPES)} 个 ⇒ 应当写「{want}种形状」")


def test_every_served_prompt_carries_the_whole_shape_table(registry: ToolRegistry):
    """那段形状表要真的进到每个角色的提示词里（常量里写对、却没接进提示词＝没改）。

    负控在下面那条：把"少一种形状"的旧表喂进同一个读法，必须被认出来。`R6` §2-⑥ 之后这一条按角色切：
    改前协议是一个常量发给所有角色，"每个角色都有同一段形状表（八种一个不缺）"成立；改后按角色渲染
    （`agent_prompts.loop_protocol_for`）—— 主控那一版仍是 `LOOP_PROTOCOL` 本身，其余九个少掉三块只有
    M 用得到的文本，其中 [c] 就是 `2b) summon_many` 那一段。
    于是成立的替换命题：每个角色的提示词里都有它那一版协议的整张形状表（逐字节等于
    `loop_protocol_for(role)` 里那一段）；`agent_loop.SHAPES` 里被它漏掉的形状恰好是 `summon` 与
    `summon_many`，且只有出边为空的角色会漏。这个缺口不是静默放过：下面那半句逐字钉住（多缺一个/
    少缺一个都红），而这两个形状的骨架仍由 `agent_loop.JSON_TAIL` 在每一步发给所有人（撤的只是
    "对没有协作边的角色说的那段用法说明"）。`R6` §2-⑥ 的作用域更正（2026-10-07，主控裁定）：会缺它的
    不是"所有非 M"，而是出边为空、一个伙伴都唤不动的角色（`_summon_capable_roles` 从
    `capabilities.ALLOWED_EDGES` 现算；今天 C / V）。"""
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        seg = _shape_table(AP.loop_protocol_for(role))
        assert seg in text, f"{role} 的提示词里没有它那一版协议里的形状表那一段"
        missing = [n for n in AL.SHAPES if not re.search(rf'"{re.escape(n)}"', text)]
        want_missing = [] if role in _summon_capable_roles() else ["summon", "summon_many"]
        assert missing == want_missing, (
            f"{role} 的形状表缺的形状是 {missing}，而它那一版协议该缺的是 {want_missing} —— "
            "这一版协议与 `agent_loop.SHAPES` 分家了（多缺一个形状等于那种形状在这一版里"
            "不存在；少缺一个等于那段 M 专用文本又漏给了非 M）")
        if role == S.CONDUCTOR_ROLE:
            assert AP.LOOP_PROTOCOL in text, "主控那一版不再是 `LOOP_PROTOCOL` 常量本身"
    # 反负控：缺 `handoff`、且写着"九种"的那一版必须被同一组读法判红。
    # 这一段逐字另写（不从当前文本拼）—— 从当前文本拼出来的"旧版"会随修好一起变好，
    # 于是判据坏掉也照样绿（反负控的全部价值就在于它与被测文本无关）。
    # `S1k-2` 抬到十种形状之后，这一段跟着补上 `retire` / `roster`（仍然缺 `handoff`：
    # 反负控要守的正是"少一种就被抓出来"）。
    old_seg = ("九种形状，互斥，每次只取其一：\n"
               '1) {"tool": "<工具名>", "args": {}}\n'
               '2) {"summon": {"role": "A-H", "action": "<动作名>"}}\n'
               '2b) {"summon_many": {"targets": []}}\n'
               '3) {"message": {"to": "#public", "subject": "x", "body": "y"}}\n'
               '4) {"note": "一句话"}\n'
               '5) {"ask_user": {"question": "?"}}\n'
               '6) {"retire": {"name": "D1"}}\n'
               '7) {"roster": {"of": "self"}}\n'
               '7b) {"interrupt": {"name": "D1"}}\n'
               '8) {"final": "<结论>", "evidence": []}')
    assert _shape_names_in(old_seg) == [n for n in AL.SHAPES if n != "handoff"], \
        f"反负控失效：旧表被读成 {_shape_names_in(old_seg)}"
    assert set(re.findall(r"([一二三四五六七八九十]+)种形状", old_seg)) != {_CN_NUM[len(AL.SHAPES)]}, \
        "反负控失效：写着「九种」的旧表居然通过了数目对拍"


# ------------------------------------------------- 循环协议里两组与该角色无关的文本
# `R6` §2-⑥（`draft/63`）的结构性搬移：`LOOP_PROTOCOL` 里两组死文本作用域不同 ⇒ 判据分开断
# （混成一条会把「搬错了范围」读成「搬干净了」）。M 专段（[a] 留痕块 / [b] 例外句）对非 M 角色都无关；
# [c] `2b)` 整段只对「一个伙伴都唤不动」的角色无关（今天只有 C：`capabilities.ALLOWED_EDGES["C"]` 空，
# 其余八个各有出边、`Conductor.summon` 按 `frm=by` 过边表 ⇒ 它们发的 `summon_many` 真的会执行）。
# 两端都要钉：只钉「无关的角色里没有」⇒ 整块删掉也绿（删规矩，不是搬移）；只钉「M 里有」⇒
# 别的角色背着别人的收件人也绿 —— 所以每条都先断言该有的地方逐字在（反真空）。三份副本
# 刻意不读 `agent_prompts._LOOP_BLOCK_*`：读被测常量的话，「常量与提示词一起改错」时会一起变好。
_BLOCK_A = '''\
   主控（M）派活时**留痕**：这一句里可以带一张 `notify` 表
   （`{"summary": "<一句话：派了什么活>", "body": "<markdown>", "refs": [...]}`，`to` 可省略，
   缺省就是被派的那个角色），框架会把它交给秘书写成一份交接手稿并发给对方；
   不带或填错也**照样派活** —— 留痕退回框架据派活本身派生的那一行
   （"谁派了谁做什么、参数、为什么"，注明"框架据派活派生"：那一行是日志，不算交接），
   格式问题如实记进这一次运行。别的角色派活不必带。'''

_BLOCK_B = '''\
   主控（M）例外：它的 final 是**给用户的回复**，不必带 `notify`。'''

_BLOCK_C = '''\
2b) **一次唤起一批**（并发，用于"一批活分给几个人/几个实例同时干"）：
   {"summon_many": {"targets": [
       {"role": "<伙伴>", "task": "<要它干什么>", "params": {…}, "instance": "<可选，同一角色要多开几个实例时各给一个不同标签>"},
       {"role": "<伙伴>", "task": "<要它干什么>", "params": {…}}],
     "why": "<一句话说明为什么一次派这一批>",
     "notify": {"summary": "<一句话：这一批派了什么>", "body": "<markdown>"}}}
   （主控派这一批时同样走上面 2) 那段留痕：一波算一次派活、写一行。）
   每一项还能带与 2) 一样的**名册三格**（`brief` / `name` / `reuse`）—— 一批里派三件不同的活时，
   每个子代理各自的简介就写在**它自己那一项**里（别只写一个总的：退役时读的人靠那一句认人）。
   框架按写集分波、同波并发跑；结果按输入顺序回来，每条各自带 status/outcome。
   **先读 `outcome` 再决定下一步**（它是六档词表，别当成布尔）：`ok` 才是"这一趟真做出了
   东西"；**`no_result` 是"跑完了、确实没有产出"**（例如派人去消化文献，而那一批全都没有
   本地全文 —— 它会如实报"真消化 0 篇"）；`refused` 是框架说不（照 `detail` 改参数）；
   `failed` 才是执行没成功；`cancelled` 是这一条被叫停、没轮到跑（**不是它做不成** ——
   原样再派之前先问清是谁停的）；`not_applicable` 是"这件活对那个目标不适用"（换目标，别
   重试同一个）。**见到 `no_result` 不许原样再派一遍**：要么换做法（换动作 / 换目标 /
   换参数），要么如实记下"这一条路这一趟没有产出"。**把 `no_result` 当 `ok` 读，正是
   "以为干了、其实没干"的根源。**
   同一角色在一批里出现多次、又没给 `instance` 时，框架会自动补 `<角色>#N` ——
   所以"并发三个 B"这件事可以就这么写。返回里的 `waves` 与 `concurrent_peak` 是
   "到底并发了没有"的读数；一次一个地派会把本该并行的活排成串行。'''

#: 出边为空的角色用不到的两块（`2)` 派活骨架 / `2b)` 一次唤起一批）。
#:
#: 与 `_BLOCK_A`/`_BLOCK_B`/`_BLOCK_C` 同一条纪律：逐字副本，不读被测常量。
_BLOCK_2 = '''\
2) 唤起一个伙伴去做一件事（`role` 写**伙伴表里那个角色名**，不是角色级通配）：
   {"summon": {"role": "<伙伴表里的角色名>", "task": "<要它干什么：一件可判定的活；可捎上你的起手建议>",
               "params": {<交给它的结构化数据：材料路径、编号、口径这类；不点动作 ⇒ 没有参数表可核>}, "why": "<一句话说明为什么找他>",
               "brief": "<一句任务简介，单行、不超过 60 字>",
               "name": "<可选：名册标签，不是职责编码；写成 probe-a-1 这种一眼看得出是标签的样子>",
               "reuse": "<可选：复用已有子代理时写它的名册标签（上一次 name 给的那一个）>"}}
   这一形**没有 `action` 那一格**（业主口径 S2：一致改成 `task` 必填、动作不填）：派活只写
   "做什么"，由接活的人按自己的工具面自己选动作。所以 `params` 不是"动作参数表"里那一套 ——
   它是你顺手交给它的结构化数据（材料路径、编号、口径），核不了对错也不会因为写了它被拒。
   名册（业主口径）：**造一个新子代理就给一句 `brief`** —— 它进名册，退役时读的人靠它认人；
   **复用已有的子代理也要给一句 `brief`**（名册登记先看简介、再看 `reuse`：只给 `reuse`
   那一笔名册绑定不落，读数 `roster_problem` 里会写明，**而这次派活照样进行**）；
   要给**已有的**子代理再派一件活就写 `reuse:"D1"`（复用**不新增名册项**，只多一次调用）；
   父可以自己提名（`name`），也可以只给角色由秘书分配 —— 名字一经分配**不再改**
   （名字被占用或已销号 ⇒ 被受控拒绝的是**那一笔名册登记**：这次派活照跑、名字不落、
   读数里写明理由；别自己换一个名字硬发）。但**它不会因此永久无名**：这一次**真跑完**
   之后，收口时的兜底会给它补一个**从未用过的新名字**（名册行里留着 `requested_name`
   与 `refusal_code`：你当初点的那个名字、为什么没落），下次看名册就知道它叫什么；
   没跑过的号（被并发 / 深度 / 扇出这类闸拒掉的）永远不会拿到名字。
   要点名时先 `{"roster": {"of": "self"}}` 看一眼活跃名册（名字 · 简介 · 状态 ·
   在飞几件）；要某一个子代理**停下当前那一轮**就用 `{"interrupt": {"name": "D1"}}`
   （只停它那一轮：排队消息还在、它自己的子代理继续跑），**不要用全局叫停**。
   主控（M）派活时**留痕**：这一句里可以带一张 `notify` 表
   （`{"summary": "<一句话：派了什么活>", "body": "<markdown>", "refs": [...]}`，`to` 可省略，
   缺省就是被派的那个角色），框架会把它交给秘书写成一份交接手稿并发给对方；
   不带或填错也**照样派活** —— 留痕退回框架据派活本身派生的那一行
   （"谁派了谁做什么、参数、为什么"，注明"框架据派活派生"：那一行是日志，不算交接），
   格式问题如实记进这一次运行。别的角色派活不必带。'''

#: `_BLOCK_2` 里 A 之前的那一段（非 M 的派活骨架：A 会被单独摘掉，所以只切前半）。
_BLOCK_2_HEAD = _BLOCK_2.split(_BLOCK_A)[0]

#: 出边为空的角色那一版里 `2b)` 的残桩（判据自己那份逐字副本）。
#:
#: 为什么是残桩而不是整块删：表头「八种形状，互斥，每次只取其一：」是常量自己的正文
#: （不在任何一块里），而它是真的（`agent_loop.SHAPES` 是 8 个）。整块删掉之后，
#: 这一档会读到"八种"却只数得出 7 项 —— 描述与自身矛盾。残桩保住表头与 8 项枚举的自洽。
_STUB = ("2) 唤起一个伙伴：**这一档你用不到** —— 你没有任何协作边，派不出活"
         "（骨架仍见每步的 JSON 尾巴）。\n\n"
         "2b) 一次唤起一批：同上 —— 你没有任何协作边，一个伙伴都唤不动。")


def _summon_capable_roles() -> list[str]:
    """出边非空的角色（含主控）—— [c] 那一段对它们有用。

    真身取自 `capabilities.ALLOWED_EDGES`（刻意不写死角色名）：边表一变，
    该拿到 [c] 的角色集就跟着变，判据跟着真身走。
    """
    return [r for r in ALL_ROLES if C.ALLOWED_EDGES.get(r, ())]


def _edgeless_roles() -> list[str]:
    """一个伙伴都唤不动的角色（出边为空）—— [c] 对它们无从填起（今天只有 C）。

    2026-10-20 业主裁定：改回 C 无出边、由 D 唤起 C ⇒ 这一档在真实树上又有对象了
    （2026-10-19 那一版曾为 C→D 改用一个无出边的合成角色顶上，现按原形态恢复）。
    """
    return [r for r in ALL_ROLES if not C.ALLOWED_EDGES.get(r, ())]


def _excise(protocol: str, units: tuple[str, ...]) -> str:
    """用判据自己那份逐字副本把 `units` 删掉（换行口径与 `loop_protocol_for` 一致）。

    [a]/[b] 只吃它们自己那一行的换行（它们嵌在 `2)` 与 `7)` 两块内部，
    删掉不影响块数）。[c] 是整块，它的删法见 `_blank_block`。
    """
    out = protocol
    for unit in units:
        assert out.count(unit) == 1, (
            "判据自己那份逐字副本与它要删的那一版协议对不上（块被改过 / 换行口径变了 / "
            "块出现了不止一次）—— 这一条不许因为找不到就通过")
        out = out.replace(unit, "", 1)
    return out


def _blank_block(protocol: str, block: str) -> str:
    """把整块 `block` 清空（保留它两侧的空行 ⇒ 块数不变）。

    为什么不是"连它后面那个空行一起删"：`draft/103` §2.1 的 A 轴把循环协议按空行
    切成了 15 段（`_LOOP_BLOCK_NAMES`）—— 空行就是段边界。删掉一个空行会把两块并成一块
    （15 → 14），于是 `_block_sections` 的"块数与名字数不等即抛"当场触发。
    而分段之后，"这一块不在提示词里"本来就应该表达成"这一段是空串"
    （`Assembly.render` 丢掉空段，`promptkit.py` 的 `render`）—— 这与整块删掉的渲染结果
    逐字相同，且不破坏结构。这是 A 轴带来的一处判据口径更新，不是放宽：
    `_roles_with_block()` 仍然逐字在渲染后的提示词里找那一块。
    """
    assert protocol.count(block) == 1, (
        "要清空的那一块在协议里找不到或不止一处 —— 判据自己那份逐字副本与它对不上")
    return protocol.replace(block, "", 1)


#: 判据自己算出来的三版协议（不读被测函数的返回值）。
#: 一版给"出边非空"的非 M 角色（减 [a]/[b]），一版给"出边为空"的角色（再把 [c] 换残桩），
#: 外加"整块清空、不留残桩"的那一版 —— 它只用来做反负控（那是作用域更正前那一版的形状）。
_WITHOUT_CONDUCTOR_BLOCKS = _excise(AP.LOOP_PROTOCOL, (_BLOCK_A + "\n", _BLOCK_B + "\n"))
_WITHOUT_ALL_THREE = _blank_block(_WITHOUT_CONDUCTOR_BLOCKS, _BLOCK_C)
_WITH_STUB = _excise(
    AP.LOOP_PROTOCOL.replace(_BLOCK_2 + "\n\n" + _BLOCK_C + "\n\n",
                             _STUB + "\n\n", 1),
    (_BLOCK_B + "\n",))


def _roles_with_block(block: str, registry: ToolRegistry) -> list[str]:
    """提示词里逐字含这一块的全部角色（含主控）。空列表 = 谁都没有（那是最坏的一种绿）。"""
    return [r for r in ALL_ROLES if block in _prompt(r, registry)]


def test_the_conductor_blocks_reach_only_the_conductor(
        registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch):
    """[a] 留痕块 + [b] 主控例外句：主控逐字有，其余九个角色一个都没有。

    这两块为什么对任何非 M 都无关：`notify` 是派活那一刻的留痕，而框架只在
    `role == S.CONDUCTOR_ROLE` 那一支上把它写进交接手稿（`agent_loop._do_handoff`）；
    [a] 的末句自己就写着"别的角色派活不必带"；[b] 说的是"主控的 final 是给用户的回复"
    —— 对非 M 角色，那句话的主语不是它。

    反真空：先断言主控那一版里这两块逐字在，否则"九个角色都没有"可以被"谁都没有"骗过。
    反负控（两端，都走真的渲染路径）：
      ① `loop_protocol_for` 恒真（照旧给所有人）⇒ "只有主控有"那半必须红；
      ② 恒假（删后版给所有人，主控也不例外）⇒ "主控含该段"那半必须红。
    """
    m = _prompt(S.CONDUCTOR_ROLE, registry)
    for label, block in (("[a] 主控留痕块", _BLOCK_A), ("[b] 主控例外句", _BLOCK_B)):
        assert block in m, (
            f"反真空：主控那一版里没有 {label} ⇒ 下面那句「其余九个角色都没有」证明不了任何事")
        assert _roles_with_block(block, registry) == [S.CONDUCTOR_ROLE], (
            f"{label} 本该只给主控，实际还有这些角色的提示词里有它："
            f"{[r for r in _roles_with_block(block, registry) if r != S.CONDUCTOR_ROLE]}")

    # ① 恒真：照旧发给所有人 ⇒ "只有主控有"那半必须红
    monkeypatch.setattr(AP, "loop_protocol_for", lambda role: AP.LOOP_PROTOCOL)
    for label, block in (("[a] 主控留痕块", _BLOCK_A), ("[b] 主控例外句", _BLOCK_B)):
        assert _roles_with_block(block, registry) == list(ALL_ROLES), (
            f"反负控失效：`loop_protocol_for` 恒真（谁拿的都是全量协议）时，"
            f"这一条没认出 {label} 还在九个角色的提示词里")
    # ② 恒假：删后版给所有人 ⇒ 主控那一版里这两块也没了（"主控含该段"那半会红）
    monkeypatch.setattr(AP, "loop_protocol_for", lambda role: _WITHOUT_ALL_THREE)
    m_after = _prompt(S.CONDUCTOR_ROLE, registry)
    for label, block in (("[a] 主控留痕块", _BLOCK_A), ("[b] 主控例外句", _BLOCK_B)):
        assert block not in m_after, (
            f"反负控失效：把删后版给所有人时，主控那一版里居然还留着 {label} —— "
            "那说明「主控含该段」那半不是因为这段文本真的在场才绿的")


def test_the_summon_many_block_reaches_every_role_that_can_summon(
        registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch):
    """2) 与 2b) 那两段：出边非空的角色拿到整段说明，出边为空的角色拿到两行残桩。

    作用域是主控 2026-10-07 更正过的那一条：不是"所有非 M"，而是"一个伙伴都唤不动的角色"——今天 C / V
    （`ALLOWED_EDGES["C"]` 是空的）。判据按真身现算（`capabilities.ALLOWED_EDGES`），不写死角色名。
    2026-10-20 业主裁定：改回 C 无出边、由 D 唤起 C ⇒ 这一条按原形态恢复（2026-10-19 那一版为 C→D
    临时改用过合成角色；"出边为空"那一档又回到真实角色 C）。

    留残桩而不是整块删：表头「十一种形状，互斥，每次只取其一：」是常量自己的正文（不在任何一块里），而它是真的（`agent_loop.SHAPES` 是 11 个）；整块删掉后这一档读到"十一种"却只数得出 9 项 ——
    描述与自身矛盾。残桩保住表头为真、枚举仍是 11 项，而 2) 与 2b) 的用法说明不再进这一档的提示词。
    反真空：至少一个角色拿到整段（八个非 M），且出边为空的那个拿到的是残桩；反负控四端都走真渲染：
    ① 恒真（谁拿的都是全量协议）⇒"该没有的没有"红；② 恒假（[c] 换残桩那版发给所有人）⇒"主控含整段"
    红；③ 旧作用域（把 [c] 当成 M 专段）⇒"该有的有"红；④ 整块删、不留残桩 ⇒"出边为空的有残桩"红。"""
    m = _prompt(S.CONDUCTOR_ROLE, registry)
    assert _BLOCK_C in m, "反真空：主控那一版里没有 2b 整段 ⇒ 下面的断言证明不了任何事"
    assert _BLOCK_2 in m, "反真空：主控那一版里没有 2) 整段 ⇒ 下面的断言证明不了任何事"
    capable, edgeless = _summon_capable_roles(), _edgeless_roles()
    assert capable, "反真空：没有任何角色有出边 ⇒ 这一条判据失去对象"
    assert edgeless, "反真空：没有出边为空的角色 ⇒ 这一条判据失去对象"
    assert set(capable) | set(edgeless) == set(ALL_ROLES), (capable, edgeless)
    assert _roles_with_block(_BLOCK_C, registry) == capable, (
        f"2b 整段该给这些角色：{capable}；实际给的是：{_roles_with_block(_BLOCK_C, registry)}；"
        f"出边为空的角色（{edgeless}）不该有它")
    assert _roles_with_block(_BLOCK_2_HEAD, registry) == capable, (
        f"2) 整段该给这些角色：{capable}；实际给的是：{_roles_with_block(_BLOCK_2_HEAD, registry)}；"
        f"出边为空的角色（{edgeless}）不该有它")
    assert _roles_with_block(_STUB, registry) == edgeless, (
        f"2) / 2b) 残桩该给这些角色：{edgeless}；实际给的是：{_roles_with_block(_STUB, registry)}")
    for role in edgeless:
        assert _STUB in _prompt(role, registry), f"{role} 那一版里没有 2b 残桩"

    # ① 恒真
    monkeypatch.setattr(AP, "loop_protocol_for", lambda role: AP.LOOP_PROTOCOL)
    assert _roles_with_block(_BLOCK_C, registry) == list(ALL_ROLES), (
        "反负控失效：`loop_protocol_for` 恒真时，这一条没认出 2b 整段还发给了出边为空的角色")
    # ② 恒假（[c] 换残桩那一版发给所有人）
    monkeypatch.setattr(AP, "loop_protocol_for", lambda role: _WITH_STUB)
    assert _BLOCK_C not in _prompt(S.CONDUCTOR_ROLE, registry), (
        "反负控失效：把含残桩的那一版给所有人时，主控那一版里居然还留着 2b 整段 —— "
        "那说明「主控含整段」那半不是因为这段文本真的在场才绿的")
    # ③ 旧作用域（这一条判据抓的就是这个错法）
    monkeypatch.setattr(AP, "loop_protocol_for",
                        lambda role: (AP.LOOP_PROTOCOL if role == S.CONDUCTOR_ROLE
                                      else _WITHOUT_ALL_THREE))
    got = _roles_with_block(_BLOCK_C, registry)
    assert got == [S.CONDUCTOR_ROLE], (
        "反负控失效：把 [c] 当成 M 专段（只有主控有它）时，这一条没认出"
        f"出边非空的那八个角色少了它（实际拿到的是 {got}）")
    # ④ 整块删、不留残桩（更正前那一版）：出边为空的角色会既没有整段、也没有残桩
    monkeypatch.setattr(AP, "loop_protocol_for",
                        lambda role: (AP.LOOP_PROTOCOL if role == S.CONDUCTOR_ROLE
                                      else (_WITHOUT_CONDUCTOR_BLOCKS
                                            if role in _summon_capable_roles()
                                            else _WITHOUT_ALL_THREE)))
    assert _roles_with_block(_STUB, registry) == [], (
        "反负控失效：把 [c] 整块删掉（不留残桩）时，这一条没认出"
        "出边为空的角色手里既没有整段、也没有残桩")


def test_each_rendered_protocol_is_exactly_the_constant_minus_its_own_blocks(
        registry: ToolRegistry):
    """每一版协议逐字节等于"常量减掉它自己那一组"（少删半块、多删一段都红）。

    为什么值得单列一条：`roles.<X>.prompt` 的真身是渲染出来的文本，而这一刀的风险
    恰恰在边界上 —— 多删一个换行会把形状 2) 与 2b)/3) 粘在一起，少删一行会留下半句
    （而主控那一版照样逐字节不变、没有任何读数会红）。这条判据把"只搬这几块"
    这句话变成可判的：判据用它自己那三份副本算三版，两边必须逐字节相同。

    三版（作用域不同）：出边非空的那八个少 319 字符（[a]+[b]）；出边为空的 C / V 少 2578
    （再把 2) 与 2b) 两块换成两行残桩，账见下面那条断言）。
    """
    with_conductor = _WITHOUT_CONDUCTOR_BLOCKS
    with_stub = _WITH_STUB
    assert with_conductor != AP.LOOP_PROTOCOL and with_stub != with_conductor, \
        "夹具前提：处理完还等于原样 ⇒ 这一条什么也没判"
    for name, version, dropped in (("减 [a]/[b]", with_conductor, (_BLOCK_A, _BLOCK_B)),
                                   ("减 [a]/[b]+[c] 换残桩", with_stub, (_BLOCK_A, _BLOCK_B, _BLOCK_C))):
        assert "\n\n\n" not in version, f"{name}：处理完出现了多余的连续空行（换行口径错了）"
        for block in dropped:
            assert block not in version, f"{name}：{block[:12]}… 没删干净"
        assert version.splitlines()[-1] == AP.LOOP_PROTOCOL.splitlines()[-1], \
            f"{name}：这一版协议的末行变了 ⇒ 动的不只是那几块"
    assert _STUB in with_stub and _STUB not in with_conductor, \
        "残桩只该出现在「出边为空」那一版里"
    assert len(AP.LOOP_PROTOCOL) - len(with_conductor) == \
        len(_BLOCK_A) + len(_BLOCK_B) + 2, "减 [a]/[b] 的字符账不对（边界上多删或少删了）"
    assert len(AP.LOOP_PROTOCOL) - len(with_stub) == \
        len(_BLOCK_2) + len(_BLOCK_C) + 2 - len(_STUB) + len(_BLOCK_B) + 1, \
        "「2) / 2b) 换残桩」的字符账不对（边界上多删或少删了）"
    for role in ALL_ROLES:
        if role == S.CONDUCTOR_ROLE:
            want = AP.LOOP_PROTOCOL
        elif role in _summon_capable_roles():
            want = with_conductor
        else:
            want = with_stub
        assert AP.loop_protocol_for(role) == want, (
            f"{role} 那一版协议与「常量 / 减 [a][b] / 再减 [c] 换残桩」这三档对不上"
            f"（它是出边{'非空' if role in _summon_capable_roles() else '为空'}的角色）")
        assert want in _prompt(role, registry), f"{role} 的提示词里不是这一版协议"
    assert AP.loop_protocol_for(S.CONDUCTOR_ROLE) is AP.LOOP_PROTOCOL, \
        "主控那一版必须是常量对象本身（设计上不可能失败的那一条）"


# ------------------------------------------------- 版本随段前进（`R6` 结构性搬移那一刀新增）
# `test_review_line_prompts.py` 那条只钉下界（`int(PROMPT_VERSION[1:]) >= 24`）：它声称守
# 「段变了、版本要跟着动」，机器判据看不见 —— 改段不改版本照样绿。这里补真判据：逐角色渲染
# 一次取摘要，与本文件冻结的十格表比对，段与版本必须一起动（两个方向都判）。
# 维护：谁改段谁在同一个 commit 里改这张表与 `PROMPT_VERSION`；它是版本相关性的读数，不是
# 「面」的基线 ⇒ 不随 `tests/golden/*` 重冻而变、也不许从那儿读。
# 摘要口径：`hashlib.sha256`（同 `llmseam.prompt_sha256`）取渲染后的提示词、把「提示词版本」
# 归一成 `<PROMPT_VERSION>`（不归一，「只改版本号」会改掉全部十格）；夹具另钉工具链读数与派活上限。
_SURFACE_FIXTURE_TOOLCHAIN = ("这台机器上的证明工具链（现算读数，不是记忆）：\n"
                              "- 检查器：（判据夹具，与机器无关）")
#: 会写 Lean 源码的角色那一段（`TOOLCHAIN_FORMAL`）也钉成固定串，理由同上。
#: 它与上面那个夹具是同一批读数的两种用法：上面报事实、这一条说怎么写。
_SURFACE_FIXTURE_FORMAL = ("你这一岗怎么写形式化（由上面那份读数现算）：\n"
                           "- （判据夹具：这一次按自足文件写）")
#: 派活上限那一段（`PARENT_LIMITS`）同理：真数字来自这一次 run 的 `Policy`
#: （`cli.py` 的 `wall_clock_sec` 就能覆盖它）⇒ 不钉住它，冻结摘要会随 run 的配置变。
_SURFACE_FIXTURE_LIMITS = ("这一次 run 的派活上限（现算读数，不是记忆）：\n"
                           "- （判据夹具：同时在飞 5 个、深度 5、墙钟 900 秒）")
_VERSION_LINE = re.compile(r"(?m)^- 提示词版本：.*$")

#: 冻结的版本号与十格摘要：这张表是「这一版是哪些段」的指纹（摘要口径见上）。
#: 更新规则：谁改段谁在同一个 commit 里改这张表与 `PROMPT_VERSION`（两个方向都判）。
#: 版本史压成一行（2026-10-07 → 2026-10-20，`p40` → `p169`）：逐批的理由与「换了几格」的读数
#: 见 `draft/103` §4.1b / `draft/104` §2–§6 / `draft/105` / `draft/106` §4 / `draft/108` §二 /
#: `draft/117` / `draft/120` §五；逐批的旧叙述不在这里保留 —— 现行实现以树为准。
#: 「换几格」本身是改动作用域的读数：改共用段 ⇒ 十格全换；只动某岗 `policy` / `document`
#: ⇒ 只那一格换（伙伴表印的是 `duty` / `boundary`）。重算用
#: `agentflow/temp/recompute_prompt_digests.py`（它钉上 `conftest.py` 的 `AGENTFLOW_LEAN_ENABLED=1`）。
# 2026-10-30（p220 → p221，业主批准动禁改区 · FC-27）：`specs/f.py` 的 policy 那一条
# 把「V 报看不出来 时把它当成这一格还没被签」换成两态（成立 / 有毛病 + 各自该怎么办）
# ⇒ 这一条只落在 F 自己的段上，十一格里只有 F 换值。逐格旧值 → 新值：
#   F f6e60280 → 6d606f06；其余十格（A/B/C/D/E/G/H/L/M/V）逐字同值。
# 十一格是 `D:\Incubator\temp\recompute_f_digest.py`（导入本文件的 `_surface_digest`，
# 环境变量与 `conftest.py` 逐条对齐：Lean 开、设置文件钉到不存在的路径、机器事实类变量清空）
# 的现算值，不是手抄。
# 2026-10-30（p222 → p223，业主批准动禁改区 · FC-27）：`specs/d.py` 与 `specs/m.py` 的
# policy 把「顺延发号」改成「按序号发下一个未用名」—— 事实没变（不点名就按
# 用过的最大序号发一个新名），换的只是词面："顺延"与已废的「撞名 ⇒ 改用顺延名继续登记」
# 共用词面（`draft/151` §6.4 第 1 条点名了这一处）。这一条只落在 D / M 两格。
# 逐格旧值 → 新值：D 5c33db06 → e890bd3a；M d3d81018 → 65646855；其余九格逐字同值。
# 十一格是 `temp/recompute_digests.py`（导入本文件的 `_surface_digest`，环境变量与
# `conftest.py` 逐条对齐）的现算值，不是手抄。
# 2026-11-03（p232 → p233，业主放权动禁改区 · FC-27）：F 那一格换值 ——
# `specs/f.py` 的 `attack.step` / `attack.status` 的 ActionSpec `returns=` 补齐实现的真返回，
# 且 policy 改成 179 §二之三的逐条交差口径；其余十格逐字未动
# （`agent_skills` 正文只落盘、工具层 `returns` 只进声明快照，不进 function-calling 的 description）。
# 逐格旧值 → 新值：F 00b76d27→61be3f62。
# 十一格是 `temp/_p233_recompute.py` 的现算值，不是手抄。
# 2026-11-04（p234 → p235，收口批）：十一格全换 —— p234 冻结（2026-11-03 13:27）之后，
# 提示词 / 工具面一侧落了 42 笔。其中进段的有：八份 spec 的「子任务被拒」格从
# `refusals` 改成真名 `subtask_refusals`（每份 spec 都有「监控直接下级」那一条 ⇒
# 十一条全部换值）；新只读工具 `doc.mapping_cells`（`roles=("G",)`，只进 G 的
# `tools_lines`）；A / B / E / F / G / H / L / M / V 各自的 policy / returns 收口；
# `PAPER_PACK` 的 blocker 两类读法（只进 G / H / M）。逐格旧值 → 新值：
#   A 5123ace4→e8be2e68 / B 3c47404b→07a9cfcf / C 90c19871→395a6def /
#   D e5e43b8e→d72edfac / E 7c174604→ce0984eb / F 61be3f62→76657779 /
#   G bd3ea65a→2aca56d9 / H 15cc471d→4715fc66 / L 40152fe3→8cb3e956 /
#   M 9c423a10→8807868b / V 1703a9c5→2403f0f1。
# 十一格是 `temp/_p235_recompute.py`（导入本文件的 `_surface_digest`，环境变量与
# `conftest.py` 逐条对齐）的现算值，不是手抄；逐笔出处写在
# `agent_prompts.PROMPT_VERSION` 上方 p235 那一格。
# 2026-11-04（p235 → p236，`6fb014f5` 三条已知缝隙那一批）：只有 G / H 两格换值 ——
# 凭据格在「通道为空」时从「可留空」改成「必须留空」（填了受控拒绝），
# `doc.write_mapping` 的 `lean_state` 不再把「关档 / 有产物」当凭据格判据；
# 工具说明面同步（进 G 的 `tools_lines`）。其余九格逐字同值。逐格旧值 → 新值：
#   G 2aca56d9→fc79c5df / H 4715fc66→ba7efe69。
# 十一格是 `temp/_p235_recompute.py` 的现算值（Lean 开档，与 conftest 同一条），不是手抄。
# 2026-11-07（p250 → p251，「修 9 条红」）：八格换值 —— A/B/D/E/F/G/L/M。
# 其中 A/E/F/G/L 的上游不在本批：72dffab1 把共享的 `conductor.void_items` summary 里
# `open_items_of` 改成「读板用 `conductor.board`：board_open_items / board_open_count /
# patrol 的 child_open_count / tree().items」四个真读数，而该工具在 A/B/D/E/F/G/L/M
# 八格面上 ⇒ p250 冻结之后这八格一直漂（文本变了没抬版本）。本批自己动的是 B / D / M：
# ① 甲：`specs/d.py` 恢复「研究侧由你主导」89 字原条并挪回第一条（b3f0b8fb 把撤销说明
#    插到最前，顶掉了 2026-10-20 的"第一条"裁定）；`secretary.py` 的「两个『判不了』别混」
#    整段恢复（它只进秘书的判断面，不进这十一格）；「作废后的板项」在 B/D/M 与两份手册里
#    统一成 `done` + `expired`。② 乙：V/E/作废口径三组判据按 f507b528 已改准的现状更新
#    （判据文本不进提示词；同步到五处的那一句进 B/D/M 三格）。③ M 另带 b7a1c721 的读数名
#    改动。C/H/V 逐字未动。逐格旧值 → 新值：
#      A 0ae47c4f→e3919091 / B 2e2a0f35→8eb5c3c7 / D 15969bb8→0c08f935 /
#      E acf48e01→7a6079a2 / F 2b76518f→af0fa9f9 / G 99a3a6ac→c8d898a7 /
#      L 34b0473c→f1d6fe1d / M 1b6876d9→523229a7（C/H/V 与 p250 同值）。
# 十一格是 `temp/_p251_freeze_digests.py` 的现算值（导入本文件的 `_surface_digest`，
# 先 `import conftest` 钉住 Lean 开档 / 设置文件 / 机器事实），不是手抄。
# 2026-11-07（p252 → p253，「让提示词与工具面第二次对齐 + 版本冻结」）：九格换值 ——
# D/F/M 是本笔（四处旧放弃格式改成两档 ＋ F 的 policy 正文补命题形态闸 ＋ M 的完成定义那一句），
# A/B/E/G/L 的上游是 4e5e85ae 的 `table.update` summary（p252 起就漂着，本批只把冻结表跟上），
# H 的上游是本笔改的 PAPER_PACK 段（H 与 M 共用「五、完成定义」），C/V 逐字未动。
# 逐格旧值 → 新值：
#   A 6d0b66f1→aa1ca53c / B 86c2b728→08cdc16d / D ec440bd4→48fb9628 /
#   E 66cf60d0→bfea0b31 / F 0be857db→46140ef9 / G 8d38e0fe→142885bc /
#   H f1fa916c→82aded01 / L 1d86d5e6→1ecacc15 / M 523229a7→b43664a8。
# 十一格是 `temp/_p253_freeze_digests.py` 的现算值（口径同上），不是手抄。
# 2026-11-07（p253 → p254，A4 裁边 + 解耦落地的连带重冻）：四格换值 ——
# B/D/F/M；上游两笔都不在本笔改段（本笔只把版本与冻结表跟上）：
#   ① 74e243df「A4 裁边：删 F→B、加 F→D」：`specs/f.py` 的 edges 换一格（伙伴表里 B 换成 D）、
#      `specs/f.py` / `specs/d.py` / `specs/m.py` 的放弃理由落盘形状改成
#      `quote_reason=abandoned@<ISO8601>@<结构化理由>`、`agent_skills._b_skills()` 新增
#      「F 不会直接派你；交稿来自 D 的携带单」与「来自 A 的收录请求照常办」两句；
#   ② 本批 B 类收口（`tools/fs_tools.py`）：`fs.write` 的 summary 补一句「A/B 写 `reports/`
#      下这三族证明了也拒；`notes/` 下不算框架产物」—— 那一行进面快照、不进十一格摘要。
# 逐格旧值 → 新值：
#   B 08cdc16d→30720620 / D 48fb9628→2b0e40ab / F 46140ef9→390ca21e / M b43664a8→0449b009。
# C/H/V 与 A/E/G/L 逐字未动。十一格是 `temp/_p254_freeze_digests.py` 的现算值（口径同上），
# 不是手抄。
# 2026-11-07（p256 → p257，玩具例子 `kind=example` 只是标签）：三格换值 —— E / F / G。
# 上游 c86e7a2a 给 `verify.run_experiment` 的工具面多一格 `kind`（它的 roles 是 E / F / G
# ⇒ 只这三格的 `tools_lines` 换值）+ adf3402c 给 `specs/g.py` 的 `WRITING_SCOPE` /
# `WRITING_SCOPE_NO_LEAN` 补「玩具例子用 Example 环境」⇒ G 再换一次（E / F 的 policy 未动）。
# 其余八格（A/B/C/D/H/L/M/V）逐字未动（只差版本行）。逐格旧值 → 新值：
#   E c5cefdfc→e60b9c92 / F f6f65ec0→3029f47a / G 55d1a1c1→e94de814。
# 十一格是 `temp/_p257_freeze_digests.py` 的现算值（导入判据文件自己的 `_surface_digest`，
# 先 `import conftest` 钉住 Lean 开档 / 设置文件 / 机器事实），不是手抄。
# 2026-11-08（p257 → p258，业主三条裁定：E 普通数值手稿 + B 绿色通道 + 穷举档证明栏）：
# 四格换值 —— B / D / E / G；上游是本笔改的四份 spec（E 的穷举 ② 改写 + ⑤ 新增、
# B 的「两族手稿」policy 与 `origin` 描述、D 的「提交强猜想引用 e-num」、G 的
# WRITING_SCOPE 落库口径）。A / C / F / H / L / M / V 逐字未动（只差版本行）。
# 逐格旧值 → 新值：
#   B 667bf57a→465a645b / D 527711b8→da51f676 / E e60b9c92→dd9d4185 /
#   G e94de814→27d436f7。
# 十一格是 `temp/_p258_freeze_digests.py` 的现算值（导入判据文件自己的 `_surface_digest`，
# 先 `import conftest` 钉住 Lean 开档 / 设置文件 / 机器事实），不是手抄。
# 2026-11-08（p258 → p259，业主三条裁定 · 第 4 笔）：两格换值 —— B / D。上游是本批改的
# 两份 spec：B 的 `register_statement.required` 放开 + `proof_manuscript` 描述广告「按手稿
# 路径收录」；D 的 policy 三处（只递指针 / 只给研究方向不点 conjecture_id / 命题台账由 B 写、
# D 只读）。A / C / E / F / G / H / L / M / V 逐字未动（只差版本行）。
# 逐格旧值 → 新值：B 465a645b→4441ddd1 / D da51f676→4d840d5b。
# 十一格不是手抄：口径只取判据文件自己的 `_surface_digest`
# （先 `import conftest` 钉住 Lean 开档 / 设置文件 / 机器事实）现算。
# 2026-11-08（p259 → p260，业主：收录按语义查一圈 + 普通数值一律 conjecture +
# 数值证据流水）：一格换值 —— B。上游是 `specs/b.py` 的 policy 新增
# 「收录先查『是不是在册的同一条』」（普通数值手稿永远是 conjecture；秘书按关键词检索后
# 认定，查到就不新注册：数值手稿更新数值证据流水 / 证明手稿按既有多证明分支追加）。
# A / C / D / E / F / G / H / L / M / V 逐字未动（只差版本行）。
# 逐格旧值 → 新值：B 4441ddd1→af7b11fd。
# 十一格是 `temp/_p258_freeze_digests.py` 的现算值（口径同上），不是手抄。
# 2026-11-08（p260 → p261，缺陷①）：零格换值 —— 十一格逐字未动（只差版本行）。
# 上游 `specs/b.py` 只去掉 `register_statement.statement_full` 的 `minLength: 1`
# 并改了那一格的 description；`_surface_digest` 不含参数 description，动作 summary /
# policy / 工具面都未变 ⇒ 十一格 SAME。
# 2026-11-08（p261 → p262，提示词-工具面一致性审计 ①–⑦ 的题面补齐）：四格换值。
# 上游两笔：① `specs/b.py` 的 policy 新增四条（从手稿读命题 / 两格读数与六档 /
# 判不了受控拒与改法 / 短证明照样判）；② `verify.run_experiment` 的 summary 换成两类
# E 手稿（e-proof 穷举要 V 签 / e-num 普通数值不需 V 签）—— 它的 roles 是 E/F/G，
# `tools_lines` 只渲染本角色工具面 ⇒ 这三格换值。`verifications.cold_start_prompt`
# （V 的真实入口）与 `verify.verify_proof.readonly_facts` 的说明都不进 system prompt
# ⇒ V 那一格逐字同 p261。A / C / D / H / L / M / V 逐字未动（只差版本行）。
# 逐格旧值 → 新值：
#   B af7b11fd→a424c53f / E dd9d4185→4c7ab9c9 / F 3029f47a→fa1e8c8c /
#   G 27d436f7→1994799a。
# 十一格不是手抄：口径只取判据文件自己的 `_surface_digest`
# （`temp/_p258_freeze_digests.py` 导入它并先 `import conftest` 钉住环境）现算。
# 2026-11-10（T1 收口，设计 `_design_T123.md` §2）：一格换值 —— B。上游是 `specs/b.py`
# 的 policy（「改写之后先拿签」从 `own.register_statement` 改成显式两动作
# `own.land_manuscript` → 派 V → `own.ingest_manuscript`，并新增「位置与格由你指定、
# 工具按块回填」整条教法）；两个新 ActionSpec 只在被派那一趟包成 `own.*`、不进
# `tools_lines` ⇒ 其余十格逐字未动（只差版本行）。逐格旧值 → 新值：
#   B d091cd6f366dad092f1b6831066e896b292670845d38638d89d18150f16eb239
#     → 0a45243ea4adbe6a285d495147c685ddd9eadf98cb61b1987c89088bfc36a254。
# 2026-11-10（概念的良定义证明有落点，业主裁定 甲）：一格换值 —— B。上游是
# `specs/b.py` 的 policy 新增一条「概念的良定义证明也走这条链（稿由你产出）」：
# 概念行不是"没有证明可写"，B 用 `own.land_manuscript` 落 `reports/b-proof-<号>.md`、
# 派 V 签、签回来用 `own.ingest_manuscript(apply, cells=["proof_text"])` 收录；
# 概念没有等级轴（`derive_grade` 对 concept 短路成 `not_applicable`）。其余十格逐字未动
# （只差版本行）。逐格旧值 → 新值：
#   B 0a45243ea4adbe6a285d495147c685ddd9eadf98cb61b1987c89088bfc36a254
#     → 65b7ff4627cc779541606cc68e89c7b15e7aa4a6ba45e55aa93424428583207b。
# 十一格不是手抄：`temp/_p267_recompute.py`（导入本文件的 `_surface_digest`，先钉
# `AGENTFLOW_LEAN_ENABLED=1`）现算。
# 2026-11-10（自产概念在 B 的动作面有入口）：一格换值 —— B。上游两笔：
# ① `agent_b/register_statement.py` 的 `register_statement` / `_register_statement_impl`
#    新增参数 `self_authored`（默认 False = 不声明）：`kind="concept"` + `origin="own_result"`
#    时显式 True 才放行并把 True 透传给秘书，不传仍 `concept_origin_refused`，
#    True 又给 `source_lit_id` ⇒ 受控拒；② `specs/b.py` 的参数面加这一格 + policy 补
#    「自己定义的新概念要显式声明 `self_authored=True`」（题面此前只教了文献那一档）。
#    参数说明与动作 summary 不进 `tools_lines`（`B.register_statement` 没有同名工具）⇒
#    其余十格逐字未动（只差版本行）。逐格旧值 → 新值：
#   B 65b7ff4627cc779541606cc68e89c7b15e7aa4a6ba45e55aa93424428583207b
#     → 767b69942cd90c0a3a121afbd1a18bab32c6b3da813917d97985a2fd3c310618。
# 十一格不是手抄：`temp/_p268_recompute.py`（导入本文件的 `_surface_digest`，先钉
# `AGENTFLOW_LEAN_ENABLED=1`）现算。
# 2026-11-10（B 不该知道 V 内部审几次；业主 2026-11-04 裁定）：一格换值 —— B。上游一笔：
# `specs/b.py` 概念良定义证明那一条的「派 V 照常三转签」→「派 V 照常签」（同一字面位置、
# 同一行 ⇒ 行数 773 不变；禁令判据 `test_b_proof_review_threshold_is_signed.py` 的 s1
# 禁用词表一个字没动）。其余十格逐字未动（只差版本行）。逐格旧值 → 新值：
#   B 767b69942cd90c0a3a121afbd1a18bab32c6b3da813917d97985a2fd3c310618
#     → 7705b3b4baf55b06ec488ce2205b73b682a4918e5cfa333978f09a1ab0eb4297。
# 十一格不是手抄：`temp/_p269_recompute.py`（导入本文件的 `_surface_digest`，先钉
# `AGENTFLOW_LEAN_ENABLED=1`）现算。
# 2026-11-10（递审只递框架手稿：真机 9 次全拒、签一发未发）：三格换值 —— D / F / V。
# 上游三笔都是教法（入口闸一个字没改）：`specs/f.py` 的 policy 说清「递审只能点
# `F.step` 返回的 `manuscript_path`；自己写的论文章节稿不是手稿」；`specs/v.py` 的
# policy 说清「被审必须是 `reports/f-proof*.md`；递来别的东西先退回、不重试同一路径」；
# `specs/d.py` 的 policy 说清「携带只转 `manuscript_path`、不转章节稿」。其余八格
# 逐字未动（只差版本行）。逐格旧值 → 新值：
#   D 25b054a3cc08dfc4fd2cb087d91065fd61a9ac66848da6c16a716ae48cb249e8
#     → a45d95a863ed2cf586c7dc813590137bba02fddf0b460e826851ec3a8b3ec272。
#   F af4916cc7319d8de8f382d6257a356d847dd837a52905be76118cb4fecb07e9e
#     → e66809ec1f6488e063a3a9942c4030db8b569cf305531f1aa64f3c54ec24fdd7。
#   V 9dce764f2770a1606efb82c0cdfbaa3df923d5fcdd4fb65aefa11d0fc6e870c5
#     → cc875eaad0c7bfa2ae425729d0a774ac867afdc33e4d940b32d362bd78afad88。
# 十一格不是手抄：`temp/_p270_recompute.py`（导入判据文件自己的 `_surface_digest`，先钉
# `AGENTFLOW_LEAN_ENABLED=1`）现算。
# 2026-11-10（立项用计划号、入账才建命题行：两轮真机都没有谁把「立项 → 落稿 → 送审 →
# 收录」当成一条必须走完的链）：一格换值 —— M。上游一笔（教法；入口闸 / B 的收录闸 /
# closing 一个字没改）：`specs/m.py` 的 policy 新增三句 ——
# ①「立项不建在命题台账上」：立项拿计划号、F 落 `reports/f-proof-plan-<计划号>.md`、
#    V 送审不传 statement_id、判词有落点（有毛病落 pending 行；计划稿不是签的载体 ⇒
#    成立那一档只看过没签）、B 收录时才建 statements 行；
# ②「决定要证某条命题的那一刻就立项」：分的是命题不是时刻；
# ③「成果是台账里的条目，不是文件 —— 但那是收录的产物，不是立项的产物」。
# 其余十格逐字未动（只差版本行）。逐格旧值 → 新值：
#   M d6b1b82f6456816b78577c9f3daf05b02643b4119f67cfcf9cbeecacde7148d4
#     → 6996deb9a3cd5a64ca96e4c2e563b49116fa65acf41536f42c46182592ef401c。
# 十一格不是手抄：`temp/_p271_recompute.py`（导入判据文件自己的 `_surface_digest`，先钉
# `AGENTFLOW_LEAN_ENABLED=1`）现算。
# 2026-11-10 晚（业主裁定：「F 的稿自己维护一套号源，不依赖命题号和计划号。停掉错误的口径。」）：
# 四格换值 —— M / F / V / B（三个号各管一件事：稿号是签的单位、计划号管去留、命题号 B 收录
# 时现取；稿名只按稿号、收录不改名、旧约定名只读兼容可签）。其余七格逐字未动（只差版本行）。
# 逐格旧值 → 新值：
#   B 7705b3b4… → bff2b0ec09bda00105237caaac176a9c05e261fec25d983a55da2146698e11b1。
#   F e66809ec… → 0a2de44fe28529c48c7c73c21ea555f87456bf1e7e9b79e0e7a7b45e25d3ce31。
#   M 6996deb9… → 4d85c06c1f3dd2d4b625ab29fc7c426bba8b614a88d4912ef4eccf816addff94。
#   V cc875eaa… → 12872e74dc49673b71d7d1eac497507e4cfb34d903fca34e6402b1b73160cdda。
# 十一格不是手抄：`temp/_p272_recompute.py`（导入判据文件自己的 `_surface_digest`，先钉
# `AGENTFLOW_LEAN_ENABLED=1`）现算。
# 2026-11-10 晚（`draft/181` 的 A + B 批 + 题面并入）：一格换值 —— C。上游是
# `specs/c.py` 的 policy 把"污染面手算多跳（`table.list(table="dependencies", …)`）"
# 换成"`ledger.resolve` 选根 → `ledger.expand(node=…, depth=…)`（层数由你决定、必填）
# → 对 `frontier` 拼接"，并把污染面写成一种查询模式（不是工具）。其余十格逐字未动
# （只差版本行）。逐格旧值 → 新值：
#   C 987c39476674f2a4… → de99ae26130ec76a7ada77f230a6e7e7e1f0687b2822e5427191f261ebe7a560。
# 十一格不是手抄：`temp/_p273_recompute.py`（导入判据文件自己的 `_surface_digest`，先钉
# `AGENTFLOW_LEAN_ENABLED=1`）现算。
# 2026-11-11（p274 → p275，真机第三轮的通道断）：一格换值 —— F。
# 上游三笔都是 F 自己的段：`attack.step` 的摘要与参数面（新增可选 `product`）、
# `specs/f.py` 的动作表同一格 + policy 新增一条教法（"写好的证明可以直接交进来"）。
# 其余十格逐字未动（只差版本行）。
# 逐格旧值 → 新值：
#   F a62be58c… → 27d85b473d4560894e8a2c2a0a6444c3f3f21ed732da46a3588391b4d6a20f47。
# 十一格不是手抄：`temp/_p276_recompute.py`（导入本文件的 `_surface_digest`，先钉
# `AGENTFLOW_LEAN_ENABLED=1`）现算。p276（2026-11-11，一个稿号 = 一份文件 = 一份证明）：
# 只换 F 一格 27d85b47… → 4306d8ed…；其余十格与 p275 逐字同值（版本行已归一）。
# p277 → p278（2026-11-11，业主真机三裁定 · 甲 + 丙）：三格换值 —— B / E / F
# （送审之后必须挂计时器等 V 的反馈；签成立即提交；B 另有交稿义务）。
# 其余八格逐字未动（版本行已归一）。逐格旧值 → 新值：
#   B b68b60f8… → 5ea2affa… / E bb895e8d… → 0dc0d45d… / F ee6e60db… → 163dde59…。
# 十一格不是手抄：`temp/_p278_recompute.py` 的现算值（口径同上一支）。
# p278 → p279（2026-11-12，G 的 revise 教法按新轮次口径改）：只有 G 那一格换值
# （e6bcda81… → 4f8dc27e…），其余十格逐字未动（版本行已归一）。上游一处语义：
# `specs/g.py` 的 `revise` 动作说明从「review_rounds+1、status=revised」改成
# 「改稿开启/推进这一轮；「复审收过几次」看 review_rounds」（239e23a7 起轮次账跟着复审走）。
# 十一格不是手抄：`temp/_p279_recompute.py` 的现算值（口径同上一支）。
# p279 → p280（2026-11-13，教法对齐）：四格换值 —— B / E / F / M；其余七格逐字未动
# （版本行已归一）。十一格不是手抄：`temp/_p280_recompute.py`（导入本文件的
# `_surface_digest`，先钉 `AGENTFLOW_LEAN_ENABLED=1`）现算。逐格旧值 → 新值：
#   B 5ea2affa… → 4a58462d…：`b_sign_policy` 的「送审之后必须挂计时器等 V 的反馈」改成
#     「送审之后这一趟还不能收工 —— 收工门按签拦（`b-proof` 没有现行的 V 签、且那条命题
#     没被放弃 ⇒ 受控拒）」，计时器只当"要等才挂"。
#   E 0dc0d45d… → 063d2d72…：`specs/e.py` 同一句改成按签拦（`e-proof` 没签、且这一条没被
#     撤销 ⇒ 拒；`e-num` 只拦无稿）。
#   F 163dde59… → b9b8482b…：`specs/f.py` 的同一句改成按签拦（计划号没有现行的 V 签、且
#     没被放弃 ⇒ 拒），并把「老盘 `-p2` 只读兼容（仍能分类 / 读 / 认签）」改成「不再被
#     认成手稿」。
#   M bbcad379… → 2c197af4…：`specs/m.py` 的「另一份证明用 `-p2`」改成「另一份证明就是
#     另一个稿号 —— 一个稿号 = 一份文件 = 一份证明」。
# A / C / D / G / H / L / V 七格与 p279 逐字同值（这几句只落在 B/E/F/M 各自的 policy 上；
# `agent_skills` 的手册正文与 `specs/l.py` 的注释不进提示词）。
# p280 第二批（同源教法补齐，版本仍 p280）：只有 F 一格再换一次 —— `specs/f.py` 的依赖段
# 教法从「四列表 / 示例画 `| 1 |`」改成「三列表（引用 / 命题号 / 用在哪一步）；路径号是
# 第四列，由 B 收录时分配、不进稿」，示例表按三列画；`dependency_section_missing` 那句
# 不再逐字引「（四列表，列固定）」。其余十格与第一批同值（`agent_skills` 的手册正文与
# `specs/b.py` 的参数说明不进提示词）。逐格：F b9b8482b… → 8fce808f…
# p281（2026-11-13，业主批准的四方合批）：三格换值 —— B / D / F；其余八格逐字未动
# （版本行已归一）。十一格不是手抄：`temp/_p280_recompute.py`（导入本文件的
# `_surface_digest`，先钉 `AGENTFLOW_LEAN_ENABLED=1`）现算。逐格旧值 → 新值：
#   p281：B 由 4a58462d… → 0236ed0c…，因为 `specs/b_ingest_policy.py` 的 `INGEST_POLICY`
#     补第十条「`## 命题` 不是定理陈述 ⇒ 让动作出受控拒，不要把这件「怎么办」写成给 D 的
#     handoff」（受控拒 `proposition_form_refused` 带 `fix` / `next_step`）。
#   p281：D 由 bc209de7… → eff9aa3f…，因为 `specs/d.py` 的派活段新增「plan 由 F 自己定、
#     一个方向一个 F、D 可查 plan 并发建议、`attack.abandon_plan` 的放弃理由三档
#     （`math_error` / `difficulty` / 不再需要；「需要调整」是操作不是理由）、
#     `dispatch_fit` 只提醒不拦」。
#   p281：F 由 8fce808f… → 3de77cc8…，因为 `specs/f.py` 的形态闸三句（`## 命题` 只从
#     `product.proposition` 渲染）＋ `attackround.PRODUCT_SPECS["proof"]` 要求
#     `proposition`，`attack.step` 参数面那两个 description（proposition / label），以及
#     X1 更正后 `attack.abandon_plan` 的说明 / 参数改成三档（`math_error` / `difficulty` /
#     不再需要；另加 `basis` / `difficulty` / `salvaged` 证据格）。
# A / C / E / G / H / L / M / V 八格与 p280 逐字同值。
# p282（2026-11-14，业主裁定「是否出 paper 退出收工判定」）：`conductor.closing` 的说明
# 由「八格」改成「七格」，`status` 的键名单去掉 `paper`（它落
# `readings.paper`，由 M 判断）。段变 D / G / H / M 四格；其余七格逐字未动。
# 现算（`temp/k1_recompute_digests.py`，先钉 `AGENTFLOW_LEAN_ENABLED=1`）。
# p283（2026-11-15，FC-27 人审批；三批改动合并后的唯一一次抬版）：段变 A / B / D / E /
# F / G / H / L / M 九格（不是某一批自己声称的四格 —— 三批合并后按合并树现算才看得全）：
#   D / F / M 是 `specs/d.py` / `f.py` / `m.py` 的 policy 正文（D 的教法收口 R-06/R-07 ＋
#   三份 spec 的「`salvaged` 可不指」）；G / H 读得到 `PAPER_PACK` 第五 / 六节的「七格全过 /
#   `paper` 落 `readings.paper`」；H 另读自己的 `verify_fixes` policy（轮数上限撤除、改由
#   `close_as` 收尾）；A / B / E / L 自己的段一个字没改，变的是它们伙伴表 / 工具面里
#   `table.update` 那一行的说明（`salvaged` 可空）。C / V 两格逐字未动。
# 逐格旧值 → 新值（p282 冻结值 → p283 合并树现算值）：
#   A 32b293f6… → 4d174ff3… / B 0236ed0c… → 2068491d… / D 209d873d… → 77a8ae8b… /
#   E 063d2d72… → 26c4de78… / F 3de77cc8… → f25ab207… / G d39af13d… → b31a79a1… /
#   H 782e5430… → bdf02c4d… / L cc1068bc… → da33b9cd… / M c3ee7e36… → a5f870d5…；
#   C 5edce177… / V 983eefc0… 与 p282 同值（逐字未动）。
# 现算（`temp/_p283_recompute.py`，先钉 `AGENTFLOW_LEAN_ENABLED=1`，一次算全十一格、不跳段）。
# 另补：`99f6a08f` 之后 `agent_skills.py` 的 H 段改动没抬版本、十一格也没重算（两条判据一直
# 红），本版一次补齐 —— 那一版的 H 段文字与 `close_as` 收尾口径是同一件事。
# p284（2026-11-16，业主逐字「改」授权的唯一一处；FC-27 区 `specs/d.py`）：D 的 policy 把
# F 的工具名降成动作名 —— 「写入口是 F 自己的 `attack.abandon_plan`（…）」改成「写入口是
# F 的 `abandon_plan` 动作（…）」。根因：`test_policy_never_names_a_tool_the_role_lacks`
# 是纯词法扫描，注册工具名出现在 D 的 policy 里而 D 的工具面上没有它 ⇒ 红；降成裸动作名
# （同段已有 `F.create_plan` / `F.step` 同形）语义未变。这一版只改了这一处。
# 段变 D 一格；其余十格与 p283 逐字相同（版本行已归一）。逐格旧值 → 新值：
#   D 77a8ae8b… → ce9d76c23513bdb05f7cc67fb805f8e002839c3fa8f013373501bb285fc5aa74
# 现算（`temp/_p284_recompute.py`，先钉 `AGENTFLOW_LEAN_ENABLED=1`，一次算全十一格、不跳段）。
# p285（2026-11-16，CL2 / 12A，审计 AU1 表一 A1）：`conductor.void_items` 的摘要里两处
# 别家工具名写明施事（「主控用 `conductor.board` 看它们」/「仍是主控的
# `conductor.wake_blocked`」）—— `conductor.board` 的 roles 只有 M，而 void_items 发给
# 6 个父角色 ⇒ 原句在教 6 个拿不到它的角色去调。判据的施事豁免同时从整行收紧到分句
# （`tests/test_tool_summaries_only_name_tools_the_role_has.py`）。
# 段变 A / B / D / E / F / G / L / M 八格（这八格读得到 void_items 那一行）；
# C / H / V 是只读角色、面上没有它，逐字未动。逐格旧值 → 新值：
#   A 4d174ff3… → 56c62604… / B 2068491d… → f6a59960… / D ce9d76c2… → bf9576d7… /
#   E 26c4de78… → 7d678aaf… / F f25ab207… → f44810a5… / G b31a79a1… → f8ffecd5… /
#   L da33b9cd… → 5bcfa1cf… / M a5f870d5… → e0cb961a…；C 5edce177… / H bdf02c4d… /
#   V 983eefc0… 与 p284 同值（逐字未动）。
# 现算（`temp/cl2/recompute_digests.py`，先钉 `AGENTFLOW_LEAN_ENABLED=1`，一次算全十一格）。
# p286（2026-11-16，业主逐字「其余按建议」授权；本版含两笔，合并后一次抬版）：
#   ① FC-27 三份补丁（CL1 / CL2）：M 的 G8 改成「证据只有 `experiments` 台账、不交回执」、
#     H 不再判回执、B 三处口径收口（`verify.verify_proof` → 动作名 `V.verify_proof`；
#     `table.update` 的列名写明在 `patch` 里）。只改教法与口径，语义未变 ⇒ 只换 B / H / M。
#     现算：B f6a59960… → 1a2ae03c… / H bdf02c4d… → 36979cac… / M e0cb961a… → 32e1a93f…；
#     其余八格逐字相同（版本行已归一）。
#   ② `conductor.broadcast` 全面退场（业主同批逐字「广播工具…全面退场」）：工具从
#     `conductor_tools._TOOL_FUNCTIONS` 移除，不再进任何角色面 ⇒ A / B / D / E / F / G / L / M
#     这八格的工具清单少一行（C / H / V 是只读角色，本来就没有它）。最终变化格 =
#     A / B / D / E / F / G / H / L / M 九格；C / V 两格与 p285 逐字相同。
#   ③ 连带（压缩批次比例）：退场后压缩批次 84 件、现量 75.11% > 75% ⇒
#     `review.report` 说明删掉「（markdown）」（-10 字符，只 H 那一格）压回 74.97%；
#     `MAX_RATIO` 未动。逐格：H 36979cac… → 25aff142…（① 的 H 段 + ③ 的摘要）。
# 十一格不是手抄：`temp/FC1/recompute_digests.py`（导入本文件的 `_surface_digest`，先钉
# `AGENTFLOW_LEAN_ENABLED=1`，一次算全十一格、不跳段）现算。
# p287（2026-11-17，业主 2026-11-17 逐字「先apply」授权）：Q1 的 `6176a035` 改了
# `conductor.closing` 的摘要 —— 收工门从「七格」写成「八格」，并加一句
# 「`literature_pending` 要待入库表清空」（第八格就是 Q1 新增的 `literature_pending`）。
# 那条摘要会进 M 的提示词（`tools_lines` 渲染每个角色自己面上的工具名 + 摘要 + 必填参数
# + 副作用），而 `conductor.closing` 只发给 M ⇒ M 段变了。只此一格；其余十格与 p286
# 逐字相同（版本行已归一）。
# 逐格旧值 → 新值：
#   M 2b7f8eac9d4b9686ed755bb88a84f2e8376b21d5c7dfe649db0412ee056f5e18 →
#     fefd7f961fac595aa8f9bc2cbc33d360b20a0d130f29bb46c6ac09a912e61084；
#   A 63c38fa6… / B d21f8265… / C 5edce177… / D 721eea57… / E 36668798… / F 99a9972c… /
#   G 931406c4… / H 25aff142… / L f1bca10c… / V 983eefc0… 与 p286 同值。
# 十一格不是手抄：`temp/p287/recompute_digests.py`（导入本文件的 `_surface_digest`，先钉
# `AGENTFLOW_LEAN_ENABLED=1`，一次算全十一格、不跳段）现算。
_FROZEN_PROMPT_VERSION = "p287"
# 2026-10-24（D-66）：D 与 M 的 policy 各加了一条「收口 ≠ 销号，再派同类子代理要新建」
# （业主裁：收口可再接活、销号不可用；用过的名字顺延成 G2/G3，绝不回收）。这一段
# 改的是段文本，而当时那一轮的边界把 `PROMPT_VERSION` 钉在 p200（不许抬）⇒ 只重算了
# D / M 两格，其余九格逐字未动。2026-10-25 抬到 p201 时已把这两格与版本一起确认。
# 判据：`tests/test_roster_ownership_survives_the_reuse_path.py`。
# 2026-10-25（p201 收口批）：十一格全换 —— 今晚十几条 lane 的段变更（M 的 27 条过时清理、
# D/E/F 与 G/H/V/L 两批审计、S1 摘掉 system 的 inbox/board 两格、S2 的出口按角色现算、
# 以及共用段那几处）改了既有角色段也改了共用段，逐组理由写在 `agent_prompts.PROMPT_VERSION`
# 上方那一段。十一格是那支重算脚本（当时写在 temp 下，已随 scratch 清理）的现算值，不是手抄。
# 2026-10-26（p202 收口批）：十一格全换。根因只有一条 —— `judge.JUDGE_PROBLEMS` 多了一个
# 失败码 `judge_unknown_tool`，而那份词表被逐项拼进每个角色的 `THREE_STATE` 段
# （`"、".join(J.JUDGE_PROBLEMS)`）⇒ 加一个码等于改十一个角色的提示词。另两笔在段上的落点：
# `verify.verify_proof.required` 去掉 `proof_text`（V 的工具目录那一行换值）、F 的写集不去
# 影响段、但 policy 三处「你自己落成 statements 一行」改成「交给 B 登记」；还有 `specs/d.py`
# 一处文案（不再教 `force_new`）。逐格的旧值 → 新值：
#   A 1022e25d→d8819279 / B f7d38a5c→407bf1ee / C 630ad84f→72ace081 / D 07409c4a→110f7eb7 /
#   E 3121e244→f46e5f64 / F 835fa4ca→46bd35c5 / G e59dbbf8→a1d7077d / H ad1e532a→e9bdf211 /
#   L dac10e41→b60b8d3f / M 38b381b9→16bf19ba / V 0afe4946→33b5d66b。
# 十一格是那支重算脚本（当时写在 temp 下，已随 scratch 清理）的现算值，不是手抄。
# 2026-10-26（p203 收口批）：只有 F 那一格换值 —— 业主裁定「依赖面写在自己那份证明手稿里、
# 由 B 读稿登记」⇒ `specs/f.py` 的 policy 多一条（`## 依赖` 四列表；缺段而正文有引用则整笔
# 拒收 `dependency_section_missing`）。同批的另两笔（B 的 `register_statement` 多一格可选参数
# `proof_manuscript`、`verify.verify_proof.returns` 多三格）都不进提示词正文 ⇒ 另十格逐字未动。
# 逐格的旧值 → 新值：
#   A d8819279→d8819279 / B 407bf1ee→407bf1ee / C 72ace081→72ace081 / D 110f7eb7→110f7eb7 /
#   E f46e5f64→f46e5f64 / F 46bd35c5→91335ce5 / G a1d7077d→a1d7077d / H e9bdf211→e9bdf211 /
#   L b60b8d3f→b60b8d3f / M 16bf19ba→16bf19ba / V 33b5d66b→33b5d66b。
# 十一格是那支重算脚本（当时写在 temp 下，已随 scratch 清理）的现算值，不是手抄。
# 2026-10-27（p204 收口批）：十一格全换，两笔一起动。
# ① 时钟八件的形写进各角色的政策（十格各加一条；M 那一格把申请形状、wait_for 三种指称、
#    补目的、到点消息的例子、旧计时工具退役并进它已有的挂机那一条）；
# ② 把「各级父也会收到通知」改成「按绝对编号链逐级由秘书转发，内容只有链尾看得到、
#    中间各跳不读内容」—— 十一份 specs 都动了这一句；
# ③（同批进段的那一笔）`_names` 的手那一档改成全列 ⇒ 每一格的「次要官能：手」那一行
#    都变长，所以十一格无一幸免，不是只换改了 policy 的那十格。
# 逐格的旧值 → 新值：
#   A 1022e25d→d8819279→0ff3434f / B 407bf1ee→61153920 / C 72ace081→ed603919 /
#   D 110f7eb7→7126df90 / E f46e5f64→e44a6a90 / F 91335ce5→7cd0c83a /
#   G a1d7077d→689286fc / H e9bdf211→f8bf823d / L b60b8d3f→75204093 /
#   M 16bf19ba→08567b14 / V 33b5d66b→19ba4aa7。
# 十一格是那支重算脚本（当时写在 temp 下，已随 scratch 清理）的现算值，不是手抄。
# 2026-10-27（p205 收口批）：十一格全换，两笔一起动。
# ① 新工具 `clock.wait_any` 进 `tools_lines` 那一行（名 + 摘要 + 必填参数 + 副作用），
#    而 `tools_lines` 对每个角色都渲染 ⇒ 十一格无一幸免；
# ② `conductor.retire_child` 的 summary 文案换了（补「待机」那一档与 refusal_code 的三态
#    读数）⇒ M 那一格再换一次。`returns=` 不进段（只进声明快照，不进 function-calling 的 description）。
# 逐格的旧值 → 新值：
#   A 0ff3434f→a5e29d79 / B 61153920→8cc47b71 / C ed603919→fc1387da /
#   D 7126df90→446f2a2d / E e44a6a90→1ea126e2 / F 7cd0c83a→7005c3d7 /
#   G 689286fc→b7255c30 / H f8bf823d→c82d132c / L 75204093→1f73dd53 /
#   M 08567b14→96bc2568 / V 19ba4aa7→01ef0b27。
# 十一格是那支重算脚本（当时写在 temp 下，已随 scratch 清理）的现算值，不是手抄。
# 2026-10-27（p206 收口批）：十一格全换，三笔一起动。
# ① 工具面 summary 十一处进 `tools_lines` 那一行（attack.create_plan /
#    clock.alarm_start / clock.timer_cancel / clock.timer_list / clock.wait_any /
#    conductor.guide / fs.edit / fs.write / table.get / table.list / verify.verify_proof），
#    而 `tools_lines` 对每个角色都渲染 ⇒ 十一格无一幸免（同批的 `returns` 只进声明快照）；
# ② 十一份 specs 的时钟段补 `clock.wait_any` 的行为口径（requested=true / waiting=false
#    那一档不是「没在等」；无计时而手头也没活就按交差处理）⇒ 同样十一格；
# ③ `specs/m.py` 的 `delivered_to` 改成「列表，只有一个元素」⇒ M 那一格再换一次。
# 逐格的旧值 → 新值：
#   A a5e29d79→5e51994a / B 8cc47b71→baeae677 / C fc1387da→61bd5d08 /
#   D 446f2a2d→8885d099 / E 1ea126e2→ee9f1962 / F 7005c3d7→8303429f /
#   G b7255c30→71b47d56 / H c82d132c→2db09be8 / L 1f73dd53→1e3825c7 /
#   M 96bc2568→03495fae / V 01ef0b27→6ec461ac。
# 十一格是那支重算脚本（当时写在 temp 下，已随 scratch 清理）的现算值，不是手抄。
# 2026-10-27（p207 收口批）：十一格全换，十四段一起动（逐段理由写在
# `agent_prompts.PROMPT_VERSION` 上方 p207 那一格）：
# ① 形状 2 的 `params` 改成"结构化数据、不是动作参数表"，并写明这一形没有 `action`（S2）；
# ② 形状 2B 的 `outcome` 补成六档受控词表（`cancelled` / `not_applicable` 各有读法），
#    `_LOOP_BLOCK_C` 同步；③ 形状 3 补公聊硬拒 `public_is_not_a_conversation`；
# ④ 形状 8 的名册三格与 `agent_state` / `active` / `waiting_only` 等读数分写；
# ⑤/⑥ 形状 9 / 10 删掉「静默 no-op / 旧路 / 未消板项」旧口径，改成 `not_mine` /
#    `no_op` 两档与静默闸（`target_not_silent` ＋ `target_state` / `blocking`）；
# ⑦ 规则那一条从"每一步只能做一件事"改成"每一步只发一条调用"；
# ⑧ PARENT_STOP 的原地打转两档措辞与 `blocked` 的形（`final` 里带一格）；
# ⑨ PARENT_ROSTER 补名册读数与退役前置；⑩ COLLAB_SHAPES 补两形只认名册名与静默闸；
# ⑪ COLLAB_NAMES 把台账号拒收收窄成四个入口、`message` / `handoff` 两种写法都收；
# ⑫ EVIDENCE_RULES 的引文归一补全五类（标点不归一）；⑬ PAPER_07_BODY 的 `.tex` 读数改
#    成 `unreadable` ＋ `UnsupportedFormat`（`unsupported_format` 从未产生过）；
# ⑭ FACULTIES 头的"层"从两档改成三档。另新增只读判据 `prompt_text_problems()`。
# 十一格全换的原因：上面这些段里 LOOP_PROTOCOL / COLLAB_SHAPES / EVIDENCE_RULES /
# FACULTIES 头是十一格共用，PARENT_STOP 十一格都渲染；PAPER_07_BODY 只进 G / H / M。
# 逐格的旧值 → 新值：
#   A 5e51994a→2b104beb / B baeae677→97ea29af / C 61bd5d08→81215a32 /
#   D 8885d099→c5788d65 / E ee9f1962→87f0a6ca / F 8303429f→70d94543 /
#   G 71b47d56→6d9c53cf / H 2db09be8→304b9028 / L 1e3825c7→30ba4ea1 /
#   M 03495fae→8dbe22d6 / V 6ec461ac→ef388571。
# 十一格是那支重算脚本（当时写在 temp 下，已随 scratch 清理）的现算值，不是手抄。
# 2026-10-27（p208 收口批）：只有五格换值（D / F / G / M / V），另六格逐字未动
# （逐格理由写在 `agent_prompts.PROMPT_VERSION` 上方 p208 那一格）：
# ① F：`specs/f.py` 的 `boundary` 新增第 8 条（形式化不是 F 的活、不许由 F 发起，
#    不排流水线、不立形式化子目标、不传 `method="formal"`）⇒ F 那一格换值；
# ② 伙伴表连带：D / G / V 自己的段一个字没改，但它们伙伴表里 F 那一行印着
#    「（它的边界共 N 条）」，N 从 7 变成 8 ⇒ 这三格各换一次。A / B / C / E / H / L
#    的伙伴表里没有 F，所以那六格逐字未动；
# ③ M：伙伴表那一行同上（7 → 8），另加 `specs/m.py` 的 policy 四段改写
#    （回执三样 / proof 双来源 (a) E 的穷举 (b) 形式化那一岗 / 「形式化关闭」那一档
#    只说明 (b) 不适用 / 「挑哪一档」按两来源写且不许只认 Lean）与审校链那一句
#    （「与 Lean 开没开无关」）。
# 同批不进提示词的几笔：`agent_skills.py` 的手册正文（指派表收件人 L → B 等）只落盘、
# 提示词里只有索引行，索引行没动；`agent_f/*` 的形式化判定也不进段。
# 逐格的旧值 → 新值：
#   A 2b104beb→2b104beb / B 97ea29af→97ea29af / C 81215a32→81215a32 /
#   D c5788d65→71c77599 / E 87f0a6ca→87f0a6ca / F 70d94543→ce2a0e5a /
#   G 6d9c53cf→def9b6b2 / H 304b9028→304b9028 / L 30ba4ea1→30ba4ea1 /
#   M 8dbe22d6→7b886073 / V ef388571→eec84b9d。
# 十一格是那支重算脚本（当时写在 temp 下，已随 scratch 清理）的现算值，不是手抄。
# 2026-10-26（p210 收口批）：十一格全换，九笔一起动（逐笔出处写在
# `agent_prompts.PROMPT_VERSION` 上方 p210 那一格）：
# ① 公共频道只剩一种写法（`#public` → `ALL`），落点是十一格共用的段；
# ② 模板里的具体台账号换成占位 `t-NNNNNN`，同样落在共用段上（含 `specs/m.py` 的 policy）；
# ③ 两件新工具 `program.list` / `program.stop`，`tools_lines` 对每个角色都渲染 ⇒ 每格各多行；
# ④ `conductor.post_task`（Q15 裁定之后进了 `UNIVERSAL_TOOLS`）⇒ 连只读的 C / H / V 也各多一行；
# ⑤ `conductor.ack` 的 `close` 与 `conductor.retire_child` / `conductor.state` 的声明与摘要；
# ⑥ `lit.*` 六格按三态口径重写（摘要进 `tools_lines`）；
# ⑦ `clock.periodic_start` 的 `returns=` 补 `patrol_checklist` —— `returns=` 不进段，
#    所以这一笔单独不换摘要，它只表现在 golden 的 `declarations` 上；
# ⑧ G9 的 lit 两处 summary（`stage_add` 的"同一篇只占一个槽"、`stage_withdraw` 的
#    "撤掉是终态判断"）⇒ A 那一格再变一次；
# ⑨ `specs/b.py` 的 policy 新增两条（`draft/161` 的 C1：入库前逐条判 relevance、
#    定理与证明要改写成自然语言）⇒ B 那一格再变一次。
# ③ ④ 两笔对十一个角色各多一行，这是"十一格无一幸免"的直接读数（与"只动某岗段落"对照）。
# 逐格的旧值 → 新值（新值 = 三条 lane 全部收工之后、冻结这一次的现算值）：
#   A 7a8ddf0d→a02e9b5d / B 4fd7572d→12c1ccac / C 81215a32→0934cade /
#   D d46dcc3a→682d422d / E f1036188→1b8b2e4f / F 9684cb81→bf10c061 /
#   G 96e718db→b30cc02b / H 304b9028→8bb8629d / L 03858b46→fed4e587 /
#   M 7b886073→61204a21 / V eec84b9d→55e0a1ae。
# 十一格是 `agentflow/temp/_p210_digests.py` 的现算值（它导入本文件的 `_surface_digest`，
# 摘要口径只有一处），不是手抄。
# 2026-10-26（p211 收口批 / K1）：十一格全换。本批只做两件事 —— 补齐四处提示词正文的
# 缺句/多句（D 面上还印着 `conductor.summon`、M 丢了「只做数值实验不算完成」、论文段丢了
# 「收工门八格全过」与「可改、该改」，另补一处 `.tex` 的 `unsupported_format` 读数）＋
# 把工具说明的压缩批次重压回 ≤75%（30 件，六件回涨最大的按「同一句解释出现两次」合并）。
# 逐笔出处写在 `agent_prompts.PROMPT_VERSION` 上方 p211 那一格。
# 十一格全换的原因：① 的落点是 `conductor.post_task` 的 summary，而它是 `UNIVERSAL_TOOLS`
# ⇒ 十一格各少一个 `conductor.summon`；② `specs/m.py` 的 policy 只进 M 那一格；
# ③ ④ 只在 PAPER_PACK（只进 M / G / H）；⑤ 的 30 件 summary 全在 `tools_lines` 那一行，
# 而 `tools_lines` 对每个角色都渲染 ⇒ 剩下的格子也跟着变。
# 逐格的旧值 → 新值：
#   A a02e9b5d→b905f740 / B 12c1ccac→bde265b3 / C 0934cade→ec81ba2d /
#   D 682d422d→2a3dc40a / E 1b8b2e4f→f2d86a4b / F bf10c061→9917ca15 /
#   G b30cc02b→7a56ebf7 / H 8bb8629d→44cfc11e / L fed4e587→5bfea9b0 /
#   M 61204a21→0b46a39a / V 55e0a1ae→f36bb01a。
# 十一格是那一支重算探针（当时写在 temp 下，口径只取本文件的 `_surface_digest` 一处）
# 的现算值，不是手抄。
# 2026-10-27（p213 收尾 / L1 巡查）：只有 M 那一格换值，其余十格逐字未动。
# 三笔都落在 M 自己的段上：① `specs/m.py` 的 policy 多了轮查的规范动作（99 字）——
# 「轮查是规范动作：到点跑 `conductor.patrol` 拿全，逐个给 `conductor.patrol_verdict`
# （过/指导）；结完再干别的；挂机等时才挂下一个 20 分钟轮查计时器。」；② 同处再一条
# 点名 `conductor.review_child`（要细看某一个时给它绝对编码，返回那一项与整棵名册树）；
# ③ M 的工具面多三件（`conductor.patrol` / `conductor.review_child` /
# `conductor.patrol_verdict`，`roles` 都是 `("M",)`），三件的 summary 进 `tools_lines`
# 那一行 ⇒ 只有 M 那一格跟着变。逐笔出处写在 `agent_prompts.PROMPT_VERSION` 上方 p213
# 那一格。逐格的旧值 → 新值：
#   M 663cba16→35b2542a（A–L / V 十格与 p212 同值）。
# 十一格是 `temp/l1_digests.py`（不入库，导入本文件的 `_surface_digest`，摘要口径只有
# 一处）的现算值，不是手抄。
# 2026-10-27（p214，`R-BE4` 的 D1 Phase A，业主批准）：只有 D 那一格换值 ——
# `conjecture_tools` 进了 `tools._MODULES` ⇒ D 的 `tools_lines` 多一行
# `conjecture.register_conjecture(...)`（`roles=("D",)` ⇒ 其余十格逐字未动）。
# 逐格的旧值 → 新值：D 2a3dc40a→8cf1fb51（A–C / E–H / L / M / V 十格与 p213 同值）。
# 十一格是 `temp/rbe4_prompt_digests.py`（不入库，导入本文件的 `_surface_digest`）
# 的现算值，不是手抄；连"只有 D 变"这件事也是它打出来的读数。
# 2026-10-28（p216，阶段 ③ 2B）：只有 A 那一格换值 —— A 的工具面多一件
# `search.retry_pending`（`roles=("A",)`），它的 summary 进 `tools_lines` 那一行，
# 而那一行只渲染本角色的工具面 ⇒ 其余十格逐字节未动（重算读数：变化的格 = ['A']）。
# 这一笔没有改任何手写段文：变的是派生态（工具面从注册表现算）。版本照样要抬 ——
# 判据问的是"渲染出来的整份提示词变了没有"，它不区分手写段与派生态。
# 逐格：A d05af496→e77c832a（B–H / L / M / V 十格与 p215 同值）。
# 十一格是 `temp/_recompute_digests.py`（导入本文件的 `_surface_digest`、用
# `build_registry().registry`，不带 store/workspace）的现算值，不是手抄。
# 2026-10-28（p217，阶段 ③ 2C）：只有 A 那一格换值 —— `specs/a.py` 的 policy 追了两段
# （「取不到全文不等于这篇不存在」＋ 429/404/400 三种处置 ＋ broad 的 topic_selfcheck
# 口径），那是 A 自己的段 ⇒ 其余十格逐字节未动（重算读数：变化的格 = ['A']）。
# 逐格：A e77c832a→0fce9436（B–H / L / M / V 十格与 p216 同值）。
# 2026-10-29（p218，V 签门槛 S5）：十一格全换，两件事一起落。
# ① V 那一格是本笔改的：`agent_skills._v_skills()` 多一份手册（`skills/V/产出-只产意见-签在秘书.md`），
#    它的索引行进 `system_prompt("V")`（V 的冷启动提示词里那一套口径的压缩版不进 system prompt，
#    由 `tests/test_v_sign_gate_streak.py` 的 c4/c8 钉着）。
# ② 另外十格不是本笔改的：p217 之后有两笔改动动了共用段（`LLM_LOOP` / `HANDOFF_PROTOCOL` /
#    `PARENT_STOP` 那一类）而没有抬版本（2026-10-29 的 bd124e5 / dc6c2d5）。读数：把
#    `git archive HEAD` 导到 temp、用同一支探针现算，在我这一笔之前十一格就已经全部与
#    p217 的冻结表不同（V 当时是 1cc92a8c）⇒ 这一笔把版本抬到 p218、十一格一次重算到位。
# 逐格旧值 → 新值（p217 → p218）：
#   A 0fce9436→822362d2 / B 336e6a60→24dc2329 / C 0e83598d→03661adc /
#   D 84f42417→44b6f5f2 / E 1522d170→79ea5bac / F 24add73c→90fd138a /
#   G c8e8bbbc→d2ddd830 / H 28da3b64→ac8a5bde / L 43b14761→172c9cf0 /
#   M f3e029d5→5c4848b6 / V de15442a→6b8ebdb4。
# 十一格是 `D:\Incubator\temp\recompute_digests.py`（导入本文件的 `_surface_digest`，
# 环境变量与 `conftest.py` 逐条对齐）的现算值，不是手抄。
# 2026-10-30（p222）：只有 H 那一格换值 —— H 的工具面多一件只读工具
# `review.scan_text_integrity`（`roles=("H",)`），它的 summary 进 `tools_lines` 那一行，
# 而那一行只渲染本角色的工具面 ⇒ 其余十格逐字同值（重算读数：变化的格 = ['H']）。
# 这一笔没有改任何手写段文：变的是派生态（工具面从注册表现算）。版本照样要抬 ——
# 判据问的是"渲染出来的整份提示词变了没有"，它不区分手写段与派生态。
# 逐格：H ac8a5bde→425e071a（A–G / L / M / V 十格与 p221 同值）。
# 逐笔出处写在 `agent_prompts.PROMPT_VERSION` 上方 p222 那一格（p219 起不再逐版往这里重抄：
# 同一件事两处说法，两处就会漂）。
#: p226 → p227（2026-11-01，业主批准动禁改区 · FC-27；`draft/160` 三-4 的丁案）：
#: 循环协议（summon 那一形）补三句名册口径 —— 撞名被拒但真跑过的号，收口兜底会补一个
#: 从未用过的新名字；没跑过的号永远不会拿到名字。它是共用段 ⇒ 十一格全换。
#: 逐格旧值 → 新值（p226 → p227）：
#:   A faa859c1→8d24e8eb / B 627f8e2a→232f3c47 / C a1d8cfc1→7c4339d8 /
#:   D 55e43491→a6df3a6a / E 3d8b7d39→337cd50e / F 507ba201→58295b4d /
#:   G 8ec81e89→dddd5baf / H e23e2f50→3b686b76 / L bf25c613→2462bba4 /
#:   M 2d018a30→e416b8a2 / V f291a4b9→7bb595da。
#: 十一格是 `temp/_recompute_160.py`（导入本文件的 `_surface_digest`，环境变量与
#: `conftest.py` 逐条对齐）的现算值，不是手抄。
#: p227 → p228（2026-11-01，业主批准动禁改区 · FC-27；「将 H 的所有机械扫描工具统一成
#: 一个方便 H 使用」）：H 的工具面多一件只读工具 `review.scan`（`roles=("H",)`，统一入口，
#: 七类 kinds），它的 summary 进 `tools_lines` 那一行，而那一行只渲染本角色的工具面
#: ⇒ 只有 H 那一格换值（重算读数：变化的格 = ['H']）。这一笔没有改任何手写段文，
#: 变的是派生态（工具面从注册表现算）。逐格：H 3b686b76→acc9ec94
#: （A–G / L / M / V 十格与 p227 同值，逐格现算见 `temp/_recompute_p228.py`）。
#: 块 3 还要再抬一次（`specs/h.py` 的审稿清单改成用 `review.scan` 拿读数 + H 手册）。
#: p228 → p229（2026-11-01，业主批准动禁改区 · FC-27）：块 3 改的是手写段文 ——
#: `specs/h.py` 的审稿清单四条（改成"机器读数走 review.scan"，并写清哪两条没有机器
#: 读数）+ 同一份声明里新增的一条「机械读数走一个入口」（含"这些读数不进 finding 台账"）
#: + `agent_skills._h_skills()` 新增一份 H 手册（它的索引行进 H 的前置提示词）。
#: 三笔都只落在 H 自己那一格 ⇒ 只有 H 换值（重算读数：变化的格 = ['H']）。
#: 逐格：H acc9ec94→27716e46（其余十格与 p228 同值，现算见 `temp/_recompute_p228.py`）。
#: 为什么块 3 不继续叫 p228：p228 已经落进 `tests/fixtures/prompt_cache_warm.json`
#: （那份读数记录的是"p228 的提示词"）⇒ 复用同一个版本号会让读数声称一份它没量过的
#: 提示词。抬 p229 并重跑一轮 warm（花费见提交信息）。
#: p248 → p249（2026-11-06，「签 / 秘书」这一类口径的最后一次收拾）：五个格换值 ——
#: V（`duty` / `boundary` / policy 里「才轮得到发签这一步」那一句 + 技能索引那一行）与
#: B / E / F / M（它们的伙伴表里印着 V 的 `duty`，同一处上游）。其余六格逐字未动
#: （只差版本行 p248→p249）。逐格旧值 → 新值：
#:   B b1cbc93f→754e663c / E bdd995ca→514ddf63 / F af7ec19a→660af579 /
#:   M 283c0ca9→080c336b / V 5a071356→c4a83154。
#: 十一格是 `temp/_p249_freeze_digests.py` 的现算值（导入本文件的 `_surface_digest`，
#: 先 `import conftest` 钉住 Lean 开档 / 设置文件 / 机器事实），不是手抄。
#: p262 → p263（2026-11-09，两把尺统一后的声明面收口）：十格换值 ——
#: A / B / C / D / E / F / G / H / V / L；M 那一格逐字未动（只差版本行）。
#: 上游一笔：`tools/table_tools.py::table_search` 的 summary 改成真口径
#: （statements 走内容面 label/statement_full，其余表走全部标量字符串字段），
#: 这件工具的 roles 是 A–H + V + L ⇒ `tools_lines` 那十格各换一行。
#: 逐格旧值 → 新值：A 7dfe78d3→0471e545 / B a424c53f→9215e02b / C 922a4275→a0c27ad3 /
#: D 4d840d5b→daaa8bdf / E 4c7ab9c9→d3d10bf5 / F fa1e8c8c→df80126b / G 1994799a→31cc8d96 /
#: H b2eda81b→a1302b26 / V a3d391fc→5a5b6c01 / L 9461d747→b54e3b2b；M 63abea4f 不变。
#: 十一格不是手抄：`temp/_p274_recompute.py`（导入本文件的 `_surface_digest`，
#: 先钉 `AGENTFLOW_LEAN_ENABLED=1`）现算。
#:
#: p274（2026-11-10，F 侧撤"按命题号写证明"）：四格换值、七格逐字不动 ——
#:   F 0a2de44f→a62be58c / G e851e09f→6730aa37 / H 18f91c2e→4e36b38d /
#:   M 4d85c06c→47d3b555；A/B/C/D/E/L/V 不变（G/H/M 动的是共用段 `PAPER_PACK`
#:   那一道"F 的稿叫什么"的字面，B 的收录面一个字没改）。
_FROZEN_PROMPT_DIGESTS: dict[str, str] = {
    "A": "63c38fa6967475d2da8fcab4078404aa1c14d00d7edeb41c59477373be157d71",
    "B": "d21f8265e9303630d23ee7b81b56ccc20c9f261113eadbc508d2e38002cd9b50",
    "C": "5edce17709665a2cedd49f8f15c3dc3e40b61d79803bf6fa2be164d383fca7b8",
    "D": "721eea576054098fbcb21ede3b30c6421cf05fea6b6b15acccd14a49b652c82a",
    "E": "36668798000e529b8c10ad7f506f88e6c7c3773554746b7d8e3b5234a59662a1",
    "F": "99a9972c639865261faf680d96f9768f1fcfbcb96d500cbaa2677a1606ef6150",
    "G": "931406c43e586cf7651851d2a1ed8732ec50756ed8fbd3379cab1d1cc9170bf7",
    "H": "25aff142c3e0aba2efdc4ffdc366d6e4f130e398f2a85f8785b3ecf220a263f8",
    "L": "f1bca10c393724aeee2e5df956b14d839723b37a10a7dfa34da9b87d472ad388",
    "M": "fefd7f961fac595aa8f9bc2cbc33d360b20a0d130f29bb46c6ac09a912e61084",
    "V": "983eefc06c583904e4d2a10d864b0fb7f382cde30503610f6f4e7c9d9dc42384",
}


def _surface_digest(role: str, registry: ToolRegistry) -> str:
    """某个角色这一次渲染出来的提示词的摘要（版本那一行归一掉，见上面的口径）。"""
    text = _prompt(role, registry, toolchain_facts=_SURFACE_FIXTURE_TOOLCHAIN,
                   toolchain_formal=_SURFACE_FIXTURE_FORMAL,
                   parent_limits=_SURFACE_FIXTURE_LIMITS)
    normalized, hits = _VERSION_LINE.subn("- 提示词版本：<PROMPT_VERSION>", text)
    assert hits == 1, (
        f"{role} 的提示词里「提示词版本」那一行有 {hits} 条（应当恰好 1 条）⇒ "
        "归一化没生效，这条判据会退化成对着版本号本身比（那它就抓不住"
        "「只改版本不改段」了）")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _version_drift(digests: Mapping[str, str], version: str,
                   frozen: Mapping[str, str], frozen_version: str) -> list[str]:
    """段与版本有没有一起动（空列表 = 一致）。

    纯函数（喂替身进来就能给两端做反负控）：
      - 段变了而版本没动 ⇒ 报（事后分不清这句话是哪个版本的提示词说的）；
      - 版本动了而段没动 ⇒ 报（版本号是"段"的名字，段没动就不该动它）。
    """
    changed = sorted(r for r in set(digests) | set(frozen)
                     if digests.get(r) != frozen.get(r))
    bad: list[str] = []
    if changed and version == frozen_version:
        bad.append(f"段变了（{changed}）而 PROMPT_VERSION 还是 {version!r} ⇒ "
                   "这一次改动在审计里查不到版本，事后分不清哪句话是哪一版说的")
    if not changed and version != frozen_version:
        bad.append(f"PROMPT_VERSION 动了（{frozen_version!r} → {version!r}）而十格摘要一格没变 ⇒ "
                   "这一版号在说什么：版本号是段的短名字，段没动就不该动它")
    return bad


def test_the_prompt_version_moves_with_the_sections(registry: ToolRegistry,
                                                    monkeypatch: pytest.MonkeyPatch):
    """真判据：段与版本必须一起动（两个方向都判，两端反负控都走真的渲染路径）。

    为什么必须有这一条：这一轴此前只有下界那一半（`>= 24`），于是"改了段、忘了动版本"
    在本仓没有任何读数会红 —— 而 `draft/63` 这一整批施工（含 `R6` §2-⑥ 那一刀与
    2026-10-07 的 §2-①②"参数提示只列必填"那一刀）做的恰恰就是"改段"。
    名字与 docstring 声称守这件事的那条判据（在
    `test_review_line_prompts.py`）守的是下界，不是这件事。

    维护规则逐字写在上面那段注释里：谁改段谁在同一个 commit 里更新这张表与
    `PROMPT_VERSION`；这张表不随 `tests/golden/*` 重冻而变，也不许读 golden。
    """
    live = {role: _surface_digest(role, registry) for role in ALL_ROLES}

    # 反真空：这张表真的覆盖十个角色，且十格摘要互不相同（否则"摘要没变"证明不了什么）
    assert sorted(_FROZEN_PROMPT_DIGESTS) == sorted(ALL_ROLES), (
        f"冻结表覆盖的角色与 ALL_ROLES 对不上：{sorted(_FROZEN_PROMPT_DIGESTS)}")
    assert len(set(_FROZEN_PROMPT_DIGESTS.values())) == len(ALL_ROLES), \
        "十格摘要有重复 ⇒ 摘要没有把角色区分开，这一条会退化成只比一格"
    assert len({v for v in live.values()}) == len(ALL_ROLES), "现场十格摘要也应当互不相同"

    # 正控：段与版本一起动过（改后仍一致）
    drift = _version_drift(live, AP.PROMPT_VERSION,
                           _FROZEN_PROMPT_DIGESTS, _FROZEN_PROMPT_VERSION)
    assert drift == [], "段与版本没有一起动：\n" + "\n".join(drift)

    # ---- 反负控 ①：只改段、不改版本 ⇒ 必须红（端到端：临时改一段真文本，再渲染一次）
    #
    # 探针必须在最后一块内部改，不能往末尾追加一句：`HANDOFF_PROTOCOL` 以两个换行收尾，
    # 直接 `+ "…"` 会多出一个空行块（2 → 3），而 A 轴（`draft/103` §2.1）把空行当段边界
    # —— `_block_sections` 的"块数与名字数不等即抛"会当场触发，探针就变成了"改结构"而不是"改文本"。
    # `rstrip("\n")` 之后再拼既改了文本（摘要必然动），又不动块数。
    monkeypatch.setattr(AP, "HANDOFF_PROTOCOL",
                        AP.HANDOFF_PROTOCOL.rstrip("\n") + "（判据探针：这一句是反负控）")
    moved = {role: _surface_digest(role, registry) for role in ALL_ROLES}
    assert moved != live, "反负控失效：改了一段真文本，摘要却没变（那这条判据什么也抓不住）"
    assert _version_drift(moved, AP.PROMPT_VERSION,
                          _FROZEN_PROMPT_DIGESTS, _FROZEN_PROMPT_VERSION), \
        "反负控失效：真的改了一段而版本没动，判据却放过了"
    monkeypatch.undo()

    # ---- 反负控 ②：只改版本、不改段 ⇒ 必须红（端到端：只把版本号抬一格）
    #
    # 抬一格的那个值是当场算出来的（`_FROZEN_PROMPT_VERSION` 的下一个），不写死字面量：
    # 写死的话，每抬一次真实版本号这一端就会变成空转 —— 实测踩过两次（p39 时代写死
    # "p40"，而 p40 落地那天它成了 no-op；两条并行线又都各自抬过一次 p40），
    # 所以这里只要求"是另一格"，与它具体是不是下一个号无关。
    _next_version = f"p{int(_FROZEN_PROMPT_VERSION[1:]) + 1}"
    monkeypatch.setattr(AP, "PROMPT_VERSION", _next_version)
    bumped = {role: _surface_digest(role, registry) for role in ALL_ROLES}
    assert bumped == live, (
        "反负控失效：只动版本号，归一化摘要却变了 ⇒ 归一化没生效，这一端不可达"
        "（而不可达的反负控就是摆设）")
    assert _next_version != _FROZEN_PROMPT_VERSION, "抬一格必须真的是另一格"
    assert _version_drift(bumped, _next_version,
                          _FROZEN_PROMPT_DIGESTS, _FROZEN_PROMPT_VERSION), \
        "反负控失效：只动了版本号，判据却放过了"
    monkeypatch.undo()


#: 在提到 `handoff` 的行里教给模型的收件人字面量：`to=…` 与 `"to": "…"` 两种写法。
_TAUGHT_TO_LITERAL = re.compile(r'to\s*=\s*"?([A-Za-z#][A-Za-z#]*)"?|"to"\s*:\s*"([A-Za-z#]+)"')


def _taught_handoff_targets(text: str) -> list[tuple[str, str]]:
    """取「同时提到 `handoff` 的行」里教给模型的 `to` 字面量，返回 `[(字面量, 出处行)]`。

    只跟 `handoff` 的行：`notify` 那一栏的 `to` 确实收 `ALL`（`notify_reading` 认），
    拿它一起判会把一处正确的写法判红 —— 两处的受控词表本来就不同。
    """
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        if "handoff" not in line:
            continue
        for m in _TAUGHT_TO_LITERAL.finditer(line):
            out.append((m.group(1) or m.group(2), line.strip()))
    return out


def test_prompt_never_teaches_a_handoff_target_the_decoder_rejects(registry: ToolRegistry):
    """提到 `handoff` 的地方教给模型的 `to` 字面量，解码器必须真的收。

    若这条破了：模型照提示词写 `to=ALL`，而 `_decode_shape` 只认 `#public` ——
    手稿写不出来，回给模型的拒信自己也在教 `ALL`（那半边在 A 线的 `agent_loop.py`，已报主控）。
    这正是"提示词教了一个框架不收的字面量"这一形态：改前 `HANDOFF_PROTOCOL` 与 M 的政策
    各教了一遍 `to="ALL"`，而没有任何读数会因此变红。
    """
    for role in ALL_ROLES:
        for lit, line in _taught_handoff_targets(_prompt(role, registry)):
            _, _, problem = AL._decode_shape(
                {"handoff": {"to": lit, "summary": "s", "body": "b"}})
            assert not problem, (
                f"{role} 的提示词教了 `handoff` 的 `to={lit}`，而解码器判它非法：{problem}\n"
                f"出处：{line}")
    # 反负控：改前那两句逐字喂进同一个读法，必须被认出来（与当前文本无关）。
    old = ('**交接工作前先写一份手稿**（`handoff` 形状）：给一个人写 `to=A–H`、'
           '给所有人写 `to=ALL`；编号由脚本分配（从 0000 起，你不编号）')
    assert "ALL" in [lit for lit, _ in _taught_handoff_targets(old)], \
        f"反负控失效：旧句里的 `to=ALL` 没被读出来（读到 {_taught_handoff_targets(old)}）"
    # 判据的前提变了（这条反负控本来就是为"前提变了"设的，实测它响了）：
    # 主控裁 (a)「教什么就得收什么」⇒ A 线把 `handoff` 的 `to` 与 `message`/`notify` 对齐，
    # `ALL` 与 `#public` 现在都收。所以"这条判据还能红"不再能用 `ALL` 来证明 ——
    # 改用一个仍然被拒的字面量（`Z`）来证明判据本身没坏。
    # 权威判据在 A 线那一侧（`_decode_shape` 接受 `ALL`、仍拒 `Z`）；这里钉的是
    # "提示词教的字面量必须被解码器收下"所依赖的那两个端点，前提一破就先在这里响。
    assert AL._decode_shape({"handoff": {"to": "Z", "summary": "s", "body": "b"}})[2], \
        "反负控失效：解码器居然收了 `to=Z` —— 那这条判据抓不住任何东西了"
    assert not AL._decode_shape({"handoff": {"to": "ALL", "summary": "s", "body": "b"}})[2], \
        "A 线裁定 (a) 的对齐没生效：`handoff` 的 `to` 应当与 message/notify 一样收 `ALL`"


# ------------------------------------------------- 只读角色必须说出"我不许写"
#
# 这一组守的是一处真实发生过的删改事故（批④ 的提示词减负里）：C 与 H 的
# 「你是只读角色：不许写/改任何数据…」整句被当成冗余删掉了。
# 为什么没有任何读数变红：H 的 `duty` 里写着「审校（只读）」，于是
# "提示词里出现过『只读』"这种松判据照样满足 —— 而"H 不许写数据、不许改稿"这件事
# 在提示词里已经没有了。换句话说：判据松一格，删掉的正好是那一格。
# 所以这里必须要求「只读 与 一个禁令词」同时出现在同一句里（标签不算数）。

#: 禁令词：中文里"你不许做某事"的那几种写法。
_PROHIBITION = ("不许", "不得", "不能", "不准", "不写", "不改", "不碰")


def _readonly_prohibition(brief: Any) -> list[str]:
    """这份 brief 里"你是只读角色 + 一句禁令"的那些格子（空列表 = 没说清）。"""
    cells = (brief.duty, *brief.boundary, *brief.policy, *brief.stance)
    return [str(s) for s in cells
            if "只读" in str(s) and any(w in str(s) for w in _PROHIBITION)]


def test_every_read_only_role_says_it_must_not_write():
    """`tools.READ_ONLY_ROLES` 里的每个角色的提示词都要有一句"只读 + 禁令"。

    事实真身是 `tools.READ_ONLY_ROLES`（只读面由它在结构上保证）——
    所以判据从它现算：新加一个只读角色，它的提示词必须跟着说清"你不许写"。
    若这条破了：只读角色读到的提示词里没有那句禁令，而"只读"这个标签还在
    （`duty` 里的括号），于是人以为说了、机器以为查了。
    """
    from agentflow.tools import READ_ONLY_ROLES

    assert set(READ_ONLY_ROLES) <= set(S.ROLES), \
        f"READ_ONLY_ROLES={READ_ONLY_ROLES} 里有不在 S.ROLES 里的角色"
    for role in READ_ONLY_ROLES:
        assert _readonly_prohibition(AP.ROLE_BRIEFS[role]), (
            f"{role} 是只读角色，而它的提示词里没有一句「只读 + 禁令」"
            f"（只有『只读』这个标签不算：批④ 删掉 C/H 那句禁令时，"
            f"duty 里的『审校（只读）』让所有松判据照样绿）")
    # 反负控：把 H 那句禁令删掉（就是实际发生过的删法）⇒ 同一读法必须判红。
    h = AP.ROLE_BRIEFS["H"]
    broken = replace(h, boundary=tuple(s for s in h.boundary if "只读角色" not in s))
    assert not _readonly_prohibition(broken), (
        f"反负控失效：删掉 H 的禁令之后判据还是绿的（读到 {_readonly_prohibition(broken)}）"
        "—— 那这条判据抓不住它本该抓的那种删改")
    assert _readonly_prohibition(h), "正控失效：H 的禁令现在读不出来"

def test_empty_brief_sections_are_never_registered(registry: ToolRegistry):
    """空段一律不注册（业主 2026-10-12 裁定 CS-16 ②）—— 两条注册路径同一条口径。

    改前不对称：`STANCE` 无条件返回（M 的 `stance=()` ⇒ 它以空段出现在段清单里），
    而 `ROLE_POLICY` / `SIGNATURE_ERROR` / `DELIVERABLE` 只在非空时返回；
    预设那条路（`composition._register_brief_blocks`）本来就跳空。裁定 ② = 统一"都不注册"。

    两条一起钉：① `brief_sections` 逐角色返回的每一段正文都非空（从真身现算）；
    ② 活的那一格 —— M 的段清单里没有 `STANCE`，G 有（它的 `stance` 非空）。
    渲染出来的正文不变（空段本来就不渲染）⇒ 这条只动段清单读数，不动提示词版本。
    """
    for role in ALL_ROLES:
        for name, _order, text in AP.brief_sections(role):
            assert text.strip(), f"{role} 的 {name} 是空段 —— 空的不该注册（CS-16 ②）"
    m_audit = AP.prompt_audit("M", registry=registry, task=TASK, workspace_root=ROOT)
    g_audit = AP.prompt_audit("G", registry=registry, task=TASK, workspace_root=ROOT)
    assert "STANCE" not in m_audit["sections"], m_audit["sections"]
    assert "STANCE" in g_audit["sections"], g_audit["sections"]
