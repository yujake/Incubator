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
_PARTNER_BULLET = re.compile(r"^- ([A-HMV])：")
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
    """`TOOLCHAIN_FORMAL` 只发给手上真有 `verify.check_formal` 的角色（业主裁定 G）。

    两头都钉，因为两头的错法不一样：
      - 漏发（会用它的角色没拿到）⇒ 重演 `draft/37` §89：8 次 `check_formal` 里
        6 次白撞 `import Mathlib`，而框架手里有读数；
      - 滥发（不写 Lean 的角色也收到一段"怎么写 Lean 源码"）⇒ 提示词变噪音，
        而噪音的代价是"该看的那几句被淹掉"（本文件的伙伴表判据同一句话）。

    判据按工具面现算（`_writes_lean`），不写死角色名 —— 所以它同时钉住
    "角色与工具面对得上"这件事：注册表里谁有这件工具，谁就该有这一段。
    """
    holders: list[str] = []
    for role in ALL_ROLES:
        sections = AP.prompt_audit(role, registry=registry, task=TASK,
                                   workspace_root=ROOT)["sections"]
        holds = any(s.name == "verify.check_formal" for s in registry.for_role(role))
        assert ("TOOLCHAIN_FORMAL" in sections) is holds, (
            f"{role}：工具面上{'有' if holds else '没有'} `verify.check_formal`，"
            f"而段表里{'有' if 'TOOLCHAIN_FORMAL' in sections else '没有'}那一段")
        if holds:
            holders.append(role)
    assert holders == ["E", "F", "G"], (
        f"持有这件工具的角色集合变了（现算：{holders}）⇒ 这一段的受众跟着变 —— "
        "不是判据坏了，是读数变了：改这一行之前先看那三个角色的提示词是不是真的都该拿到它")


def test_the_toolchain_line_says_to_pass_mathlib_when_the_probe_says_it_works(
    monkeypatch: pytest.MonkeyPatch,
):
    """判据：Mathlib 可用时，那一段必须说"显式传 `['Mathlib']`"，而不是叫你去写自足文件。

    真机读数（2026-10-05 T1 第 16 趟）：这一段在 Mathlib 可用时仍然写死
    "`check_formal` 可达的写法是不 import Mathlib 的自足文件" —— 它与上面一行的现算读数
    直接打架，而模型信了它：`experiments` 里 8 次 formal 全是
    `imports=（默认：不注入任何库）`、全部 `compile_error`（检查器原话
    `failed to synthesize instance`），一条 proof 行都没落成。
    负控：读数说没装时，"自足文件"那句必须还在 —— 那一支的处置本来就该是它。

    2026-10-11（E 的迁移批）这一轴拆成两段：事实（`toolchain_facts_text`，
    全角色）与怎么写（`toolchain_formal_text`，持有 `verify.check_formal` 的角色）。
    这条判据因此同时钉住"拆干净了"：事实段里不再出现写法口径
    （否则九个不写 Lean 的角色照样读到它 ⇒ 拆了个寂寞），
    而口径段里按读数给路（三档都测）。
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
    assert holders == ["A", "B", "D", "E", "F", "G", "H", "V", "M"], (
        f"能派活（出边非空）的角色集合变了（现算：{holders}）⇒ 这一段的受众跟着变 —— "
        "不是判据坏了，是能力表变了（唯一发不出 `summon` 的实测是 C）")


def test_the_parent_limits_are_computed_from_the_policy():
    """数字必须从 `Policy` 现算，一个都不许写死（业主口径 C：从代码现算）。

    正控：换一个把四类上限都改掉的 `Policy` ⇒ 渲染出来的那一句跟着换；
    负控：默认值（5 / 4 / 200 / 900）一个字都不该出现在改过的那一段里 ——
    写死的数字在"被覆盖过的 run"里就是一句谎话（`cli.py` 就传过 `wall_clock_sec`）。
    另外钉住两处口径：主控那一档来自 `FANOUT_LIMIT_BY_ROLE`（20，同时把工人档
    5 写出来做对照），而 `wall_clock_sec=None` 那一支必须写成"这一次不限"
    （不是"限 0"，也不是不写 —— 业主裁定 B 的另一面：墙钟不缩短，
    但"没设"与"设为 0"必须分得开）。
    """
    from agentflow import policy as POL

    odd = POL.Policy(max_depth=9, max_fanout=7, max_concurrency=3,
                     max_tasks_per_run=11, wall_clock_sec=None)
    text = AP.parent_limits_text(odd, "E")
    for want in ("7 个", "9", "3 个", "11 个", "这一次**不限**"):
        assert want in text, f"改过 Policy 之后这一段里没有 {want!r}：{text}"
    for stale in ("最多 5 个", "全局同时运行 4 个", "总数 200 个", "墙钟：900 秒"):
        assert stale not in text, f"这一段里还留着写死的旧数字 {stale!r}：{text}"

    # 主控那一档来自 FANOUT_LIMIT_BY_ROLE；工人档来自 Policy.max_fanout（两处都现算）
    m_text = AP.parent_limits_text(odd, "M")
    assert "最多 20 个" in m_text and "工人档是 7 个" in m_text, m_text
    assert "最多 7 个（" not in m_text, m_text

    # 默认 Policy 的那一支：工人档等于 Policy.max_fanout ⇒ 不再补"工人档是…"那半句
    plain = AP.parent_limits_text(POL.Policy(), "E")
    assert "最多 5 个。" in plain and "工人档" not in plain, plain


def test_the_role_that_writes_the_acceptance_table_knows_every_controlled_kind():
    """广告面判据（D35）：写表的人必须拿到受控词表的逐字清单。

    真机读数（T2 第 7 趟 `projects/p6i-research-from-zero`）：M 的验收表 P1 用了
    `manuscript_edited`，而那个从零工作区没有只读基线 `source/` ⇒ 那一行的读数算不出来
    ⇒ 整张表判没查成、`can_close=false`（七格里唯一红的那格其实是 `anchor`，而
    `acceptance` 连读数都没留下）。词表不在 brief 里时，写表就是猜；猜错一个名字废掉的是
    整张表，不是那一行 —— 所以这一条按"词表里每一档都要在 brief 里出现"来守。

    ## CC-09（list 半，2026-10-06）：从"名字出现过"升级为"清单 == 词表"

    旧的判据只查"每一档的名字在 brief 里出现过"——它看不穿两件事：① 那一串平铺清单
    漏了某一档（而那一档恰好在别处被提到 ⇒ 名字查得到 ⇒ 判据照样绿）；
    ② 清单里混进了词表外的名字（提示词教人照清单挑 ⇒ 挑出一个框架不认识的档）。
    实测：清单 30 项而词表 31 档（漏 `c_analysis_runs`）。
    现在这一条把那份清单解析出来，与词表双向对拍（漏一档、多一档都红），
    并带两条反真空（清单解析不出 20 项以上 ⇒ 红；清单里有重复项 ⇒ 红）。
    """
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
    # D47：交付物按任务那句话说 —— "整理成论文"那一类必须建包（T3 第 1 趟就是漏了这一句）
    assert "交付物按任务那句话说" in text and "必须建论文包" in text, text
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


def test_every_action_in_the_partner_table_says_what_it_does(
        registry: ToolRegistry):
    """判据（`draft/39` §6.45 的 D56）：伙伴表里每个动作都要带一句"它是干什么的"。

    改前那一行只有 `动作名（参数提示）` —— 无参动作于是等于只有一个名字。
    真机代价（T5 第 5 趟 `p8e-fermat-shorter-proof`）：F 的攻坚子目标用
    `submit_search_request` 把请求 `r-0004` 放进检索队列，而队列的消费者是 A 的
    `run_once`（无参）—— M 从头到尾没派过它，请求整趟没人做、计划停在
    「等 A 完成检索请求」，七格全绿。摘要来自 `capabilities` 的动作表（唯一来源）。
    """
    from agentflow import agent_prompts as AP
    from agentflow import capabilities as C

    for role in ALL_ROLES:
        for other in AP.partners_out(role):
            line = next((ln for ln in AP.partners_lines(role) if ln.startswith(f"- {other}：")), "")
            for a in C.actions_for(other):
                assert str(a.summary) in line, \
                    f"{role} 看到的 {other}.{a.action} 没有摘要（无参动作只有一个名字）：{line[:300]}"


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
    assert holders == ["A", "B", "D", "E", "F", "G", "H", "V", "M"], holders


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
    "fs.read": "真工具，但只在带 workspace_root 的注册表里 —— 本文件的夹具刻意不带（见文件头）",
    "fs.write": "同 fs.read",
    "fs.edit": "同 fs.read",
    "research.set_status": "真工具，但只在带 store 的注册表里（`research_tools.ALL_TOOLS`，"
                           "`roles=('D',)`）—— 本文件的夹具不带 store，`research_tools` 按契约"
                           "跳过（`tools/__init__.py:390`，原因记在 `build_registry().skipped`）。"
                           "口径的两个读数见 `draft/108` §四 CS-9：无 store 70/28 件、"
                           "带 store 83/41 件",
    "main.tex": "文件名（稿件落点），不是工具",
    "main.pdf": "文件名（渲染产物），不是工具",
    "appendix.tex": "文件名（附录落点），不是工具",
    "documents.claims": "台账字段（documents 表的 claims 列），不是工具",
    "documents.status": "台账字段（documents 表的 status 列），不是工具 —— H 的裁决正落在它上面"
                        "（`accepted` / `in_review` / `unresolved_review`，见 `draft/103` §4.1b-25）",
    "experiments.search_bound": "台账字段（experiments 表的 search_bound 列），不是工具",
    "autonomy.run_autonomous": "模块.函数引用（说明这条纪律由哪段代码保证），不是工具",
    "policy.check": "同 autonomy.run_autonomous",
    "policy.waves_of": "同 autonomy.run_autonomous",
    "quoteverify.check_quote": "同 autonomy.run_autonomous",
    "userio.ask_user": "同 autonomy.run_autonomous",
    "verifications.cold_start_prompt": "同 autonomy.run_autonomous（V 那一格的入口说明："
                                       "它说清 V 走的是冷启动入口，不是工具）",
}

#: "像工具名"的点号 token：反引号包着、两段都是小写标识符。
_DOTTED_TOKEN = re.compile(r"`([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)`")


def test_the_prompt_never_names_a_tool_that_does_not_exist(registry: ToolRegistry):
    """广告面不说谎：提示词里每个"像工具名"的 token 要么是真工具，要么登记过理由。

    真机代价（`draft/105` 的 B1/B2 + `draft/41`）：`unknown_action` 52 次，
    其中一部分就是提示词指名了一个不存在的工具 —— 从前写着"要发给某一个同伴看
    就用 `manuscripts.write`"（全仓没有这件工具：`manuscript_tools.py` 的表格逐字写着
    "它不是工具：走循环形状 handoff"）与"传话走留言（`message.send`）"（也没有这个名字，
    `message` 是形状）。批 Q1 把两处改成形状名，并加了这一条判据 ——
    它是那两条的通用形式：与其为每个名字写一条短语探针，不如扫一遍十格提示词。

    两侧都钉：
      - 正控：十格提示词里抽得到 token（抽不到 = 扫描面坏了，不是"没有问题"）；
      - 对拍：每个 token 要么在这一岗的工具面里，要么在 `_NON_TOOL_DOTTED_TOKENS`
        里逐条登记过理由；
      - 反真空：登记表里每一条都真的还在提示词里（豁免表腐烂时红）。
    """
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
        一批里派三件不同的活时，各自的简介写在各自那一项里（`_decode_shape` 的 `**extra`）；
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

    ① 没有哪一格说"步数有限"：框架不设步数闸（`max_steps` 只是报告阈值，
    12-K 裁定与 `agent_loop` 的注释都这么写），协议里那句"步数不是收工理由"才是真的。
    `specs/m.py` 曾有两条政策拿"步数有限"当前提（"步数有限：现状侦察最多做一次…"与
    "步数预算有限，留出最后几步…"）—— 而同一份提示词的协议里写着"框架不设步数闸"
    ⇒ 一格里两句互相矛盾（批 R1 改掉；这是 A21 的第三处与它的同族，前两处由 p65 修）。
    这条判据钉两头：旧前提不许留（含"步数预算有限"这种同一个意思的换词写法 ——
    只判那四个字会漏掉它）、真话必须在。

    ② 0 个对外动作的角色（现算：`actions_lines(role)` 空 ⇒ 实测只有 M）要读到
    "这是设计，不是缺口"与它的三张面（对用户 / 对同伴 / 对框架）——
    原来那一句"你没有对外可被调用的动作（你的产出由框架直接读）"读起来像缺省值，
    像在说"我什么都做不了"（`draft/103` §5.2 第 2 条点过；`draft/106` §4 的 `M_DELIVERABLE`）。
    """
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

    口径变更（2026-10-07，R6 `draft/63 §2-①②`）：参数提示从"必填 + 可选枚举"改成只列必填。
    改前那条断言的依据是一次真机事故 —— 模型按只列必填的提示词多传了一个键、拿到
    `invalid_params`（本文件这条判据的 docstring 原来逐字记着它）。那次事故现在的接住方是：

    * 可用键是封闭集合、写错时框架把完整参数表回给你 —— LOOP 规则①里各写一次；
    * 兜底本体 `agent_loop._param_table`（`tool` / `summon` / `summon_many` 三条形状全覆盖），
      判据在 `tests/test_param_table_on_refusal.py`；
    * 本族口径的守卫在 `tests/test_prompt_param_hints.py`（可选枚举回到提示词里必红）。

    为什么要换：那串枚举是十角色合计 10,458 字符，而每一次运行的每一步都要重付这笔钱；
    兜底那张表只在写错时付一次。

    若这条破了：模型会去调一个不存在的工具名（unknown_tool），或者连必填键都不知道 ——
    后者连兜底都救不了（被拒之前它根本凑不出一次合法调用）。
    """
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
            expected += "）"
            assert hint == expected, (
                f"{role} 的工具 {spec.name} 的参数提示形状变了：\n  现场 {hint}\n  应为 {expected}"
            )


def test_partner_bullets_follow_the_edge_table(registry: ToolRegistry):
    """伙伴条目 = "看得见的那些"；"唤不起的"必须逐条标出来。

    若这条破了：模型会去唤起一个边表不允许的伙伴（换回 forbidden_edge），
    或者根本不知道某条已经放开的边存在；不可召唤的角色还会误以为自己能被召唤。

    ## 2026-10-10 口径更新（看两层，不再是一层）

    改前这里是"伙伴条目恰等于出边"（一层）。裁定第 4 条之后主控的出边只剩六个，
    而 2026-10-09 的裁定又要求「M 要看到所有人的简介」—— 两句话同时成立 ⇒
    主控的条目是全体，其中唤不起的三个带「你唤不起它」标记。
    所以这条判据改成：① 条目恰等于 `visible_partners`（不多不少）；
    ② 看得见但唤不起的那些必须有标记（否则"看得见"会被读成"派得动"）；
    ③ 反真空：真的存在这样的角色（否则 ② 是空转）。
    """
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
    # 反真空：这一批就是因为主控有 B / F / V 三个"看得见、唤不起"的角色才加的。
    assert gaps["M"] == {"B", "F", "V"}, gaps["M"]
    assert not any(gaps[r] for r in gaps if r != "M"), \
        f"只有主控该有这一档（其余角色的条目就是出边）：{ {r: g for r, g in gaps.items() if g} }"


def test_roles_that_can_summon_a_are_told_its_index_is_english(registry: ToolRegistry):
    """能唤起 A 的角色必须被明确告知：A 的检索面是英文文献库。

    为什么值得一条判据：`providers.query_applicability` 对抽不出英文关键词的题面是
    fail-closed（`query_not_applicable_cjk`）。模型不知道这件事就会拿中文题面去唤起，
    拿回一个"这一问没发出去"的结果、却当成"没有这篇文献"（真机实测：`draft/28` §203
    的中文 description 把 `precise` 的查询清零，而两层闸门都不拦它）。
    这条判据同时钉住两半：有 A 这条边的角色要读到、没有这条边的角色不要读到
    （无差别地贴一句放之四海皆准的提示词，就是把提示词当噪音）。

    探针钉的是"对唤起者说的那句"（`唤起 A 时注意`），不是"英文关键词"这个词：
    2026-10-11 接线批 C1 之前它钉的是词，而 A 自己的第一段写死的正文
    （`presets/roles/a/blocks/search_style.md`，段名 `A_SEARCH_STYLE`）里合法地
    写着"`topic` 里要带英文关键词" —— 那是对 A 自己说的，与这句对唤起者说的不是同一句。
    钉词的判据在那一刻变成假红（实测：`p68` 时 A 的 `partners_out` 里没有 A，
    而提示词里有这个词 ⇒ 判据红）—— 而这条判据要守的性质是
    "谁读到了这句提醒"，主体是收件人。（`draft/105` 已登记这一条形态：
    探针钉词而不钉收件人时，任何一个角色自己谈到同一个概念都会把它钉红。）
    """
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
        # V（F-02 起）：`host.wiring_status` 是按 `schema.ROLES` 逐角色给的，
        # 所以这份夹具也必须含 V —— 少了它，F 的伙伴条目（`F → V` 那条边）
        # 会在这里 KeyError，而那不是"V 没接线"，是夹具没跟上角色表。
        "V": "wired",
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

    负控在下面那条：把"少一种形状"的那种旧表喂进同一个读法，必须被认出来。

    ## `R6` §2-⑥ 之后这一条按角色切（改过一次，逐字留痕）

    改动前：循环协议是一个常量发给所有角色，所以"每个角色的提示词里都有同一段
    形状表（八种一个不缺）"这句话成立。改动后：协议按角色渲染
    （`agent_prompts.loop_protocol_for`）—— 主控那一版仍是 `LOOP_PROTOCOL` 本身，
    其余九个角色那一版少掉三块只有 M 用得到的文本，其中 [c] 就是 `2b) summon_many`
    那一段。于是成立的替换命题是：

    - 每个角色的提示词里都有它那一版协议的整张形状表（逐字节等于
      `loop_protocol_for(role)` 里那一段，切法与本文件其它地方同一套锚点）；
    - `agent_loop.SHAPES` 里被它漏掉的形状恰好是 `summon_many`，且只有非 M 会漏。

    这一个缺口不是静默放过：下面那半句把它逐字钉住（多缺一个/少缺一个都红），
    而 `summon_many` 的形状骨架仍由 `agent_loop.JSON_TAIL` 在每一步发给所有人
    （每一步的提示词都无条件追加它）—— 撤的只是"对 M 说的那一段说明"。

    `R6` §2-⑥ 的作用域更正（2026-10-07，主控裁定）：会缺 `summon_many` 的不是
    "所有非 M"，而是出边为空、一个伙伴都唤不动的角色（`_summon_capable_roles`
    从 `capabilities.ALLOWED_EDGES` 现算；今天只有 C）。判据因此按那个集合算。
    """
    for role in ALL_ROLES:
        text = _prompt(role, registry)
        seg = _shape_table(AP.loop_protocol_for(role))
        assert seg in text, f"{role} 的提示词里没有它那一版协议里的形状表那一段"
        missing = [n for n in AL.SHAPES if not re.search(rf'"{re.escape(n)}"', text)]
        want_missing = [] if role in _summon_capable_roles() else ["summon_many"]
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
#
# `R6` §2-⑥（施工清单 `draft/63`）的结构性搬移：`LOOP_PROTOCOL` 里有两组死文本，
# 它们的作用域不一样，所以判据必须分开断（混成一条会把"搬错了范围"读成"搬干净了"）：
#
#   - M 专段（[a] 主控留痕块 / [b] 主控例外句）：对任何非 M 角色都无关；
#   - [c] `2b)` 整段：只对一个伙伴都唤不动的角色无关 —— 今天只有 C
#     （`capabilities.ALLOWED_EDGES["C"]` 是空的）。其余八个非 M 角色各有 1–6 条出边，
#     而 `Conductor.summon` 按 `frm=by` 过边表 ⇒ 它们发出的 `summon_many` 真的会执行，
#     那一段对它们是能用的。（"是不是主控"曾被拿来当判据，那是错的：主控的动作表是空的，
#     `summon_many` 走的是 conductor 工具面，按动作表算十角色全是 False。）
#
# 两端都要钉：只钉"无关的角色里没有"时，把这几块从常量里整个删掉也照样绿（那是"删规矩"，
# 不是搬移，而且主控那份也跟着没了）；只钉"M 里有"时，别的角色照旧背着别人的收件人
# 也照样绿。所以每条判据里都有"反真空"（先断言该有的地方逐字在）。
#
# 下面三份是判据自己的逐字副本，刻意不读 `agent_prompts._LOOP_BLOCK_*`：
# 读被测常量的话，"常量与提示词一起改错"时判据会跟着一起变好 —— 那正是本仓反复
# 记过的假绿形态（反负控的全部价值就在于它与被测文本无关）。
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
       {"role": "<伙伴>", "action": "<动作>", "params": {…}, "instance": "<可选，同一角色要多开几个实例时各给一个不同标签>"},
       {"role": "<伙伴>", "action": "<动作>", "params": {…}}],
     "why": "<一句话说明为什么一次派这一批>",
     "notify": {"summary": "<一句话：这一批派了什么>", "body": "<markdown>"}}}
   （主控派这一批时同样走上面 2) 那段留痕：一波算一次派活、写一行。）
   每一项还能带与 2) 一样的**名册三格**（\rief\ / ame\ / euse\）—— 一批里派三件不同的活时，
   每个子代理各自的简介就写在**它自己那一项**里（别只写一个总的：退役时读的人靠那一句认人）。
   框架按写集分波、同波并发跑；结果按输入顺序回来，每条各自带 status/outcome。
   同一角色在一批里出现多次、又没给 `instance` 时，框架会自动补 `<角色>#N` ——
   所以"并发三个 B"这件事可以就这么写。返回里的 `waves` 与 `concurrent_peak` 是
   "到底并发了没有"的读数；一次一个地派会把本该并行的活排成串行。'''

#: 出边为空的角色那一版里 `2b)` 的残桩（判据自己那份逐字副本）。
#:
#: 为什么是残桩而不是整块删：表头「八种形状，互斥，每次只取其一：」是常量自己的正文
#: （不在任何一块里），而它是真的（`agent_loop.SHAPES` 是 8 个）。整块删掉之后，
#: 这一档会读到"八种"却只数得出 7 项 —— 描述与自身矛盾。残桩保住表头与 8 项枚举的自洽。
_STUB = ("2b) 一次唤起一批（这一档你用不到：你没有任何协作边，派不出活 —— "
         "骨架见每步的 JSON 尾巴）。")


def _summon_capable_roles() -> list[str]:
    """出边非空的角色（含主控）—— [c] 那一段对它们有用。

    真身取自 `capabilities.ALLOWED_EDGES`（刻意不写死角色名）：边表一变，
    该拿到 [c] 的角色集就跟着变，判据跟着真身走。
    """
    return [r for r in ALL_ROLES if C.ALLOWED_EDGES.get(r, ())]


def _edgeless_roles() -> list[str]:
    """一个伙伴都唤不动的角色（出边为空）—— [c] 对它们无从填起（今天只有 C）。"""
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
_WITH_STUB = _WITHOUT_CONDUCTOR_BLOCKS.replace(_BLOCK_C, _STUB, 1)


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
    """[c] `2b)` 那一段：出边非空的角色拿到整段说明，出边为空的角色拿到残桩。

    作用域是主控 2026-10-07 更正过的那一条（见上面那段注释）：不是"所有非 M"，
    而是"一个伙伴都唤不动的角色"——今天只有 C（`ALLOWED_EDGES["C"]` 是空的）。
    判据按真身现算（`capabilities.ALLOWED_EDGES`），不写死角色名。

    这一档为什么留残桩而不是整块删：表头「八种形状，互斥，每次只取其一：」是常量
    自己的正文（不在任何一块里），而它是真的（`agent_loop.SHAPES` 是 8 个）。
    整块删掉之后，这一档读到"八种"却只数得出 7 项 —— 描述与自身矛盾。残桩保住
    表头为真、枚举仍是 8 项，而 565 字的用法说明不再进这一档的提示词。

    反真空：至少有一个角色拿到整段（今天八个非 M 都有），且出边为空的那个角色
    确实拿到的是残桩（不是整段、也不是什么都没有）。
    反负控（四端，都走真的渲染路径）：
      ① 恒真（谁拿的都是全量协议）⇒ "该没有的没有"那半必须红；
      ② 恒假（[c] 换残桩那版发给所有人）⇒ "主控含整段"那半必须红；
      ③ 旧作用域（把 [c] 当成 M 专段 —— 只有主控有）⇒ "该有的有"那半必须红；
      ④ 整块删、不留残桩（作用域更正前那一版的形状）⇒ "出边为空的有残桩"那半必须红。
    """
    m = _prompt(S.CONDUCTOR_ROLE, registry)
    assert _BLOCK_C in m, "反真空：主控那一版里没有 2b 整段 ⇒ 下面的断言证明不了任何事"
    capable, edgeless = _summon_capable_roles(), _edgeless_roles()
    assert capable, "反真空：没有任何角色有出边 ⇒ 这一条判据失去对象"
    assert edgeless, "反真空：没有出边为空的角色 ⇒ 这一条判据失去对象"
    assert set(capable) | set(edgeless) == set(ALL_ROLES), (capable, edgeless)
    assert _roles_with_block(_BLOCK_C, registry) == capable, (
        f"2b 整段该给这些角色：{capable}；实际给的是：{_roles_with_block(_BLOCK_C, registry)}；"
        f"出边为空的角色（{edgeless}）不该有它")
    assert _roles_with_block(_STUB, registry) == edgeless, (
        f"2b 残桩该给这些角色：{edgeless}；实际给的是：{_roles_with_block(_STUB, registry)}")
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

    三版（作用域不同）：出边非空的那八个少 319 字符（[a]+[b]）；出边为空的 C 少 832
    （再把 567 字符的 [c] 换成 54 字符的残桩：−567+54 = −513，319+513 = 832）。
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
        len(_BLOCK_A) + len(_BLOCK_B) + len(_BLOCK_C) + 4 - len(_STUB) - 2, \
        "「[c] 换残桩」的字符账不对（边界上多删或少删了）"
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


# ------------------------------------------------- 版本随段前进（`R6` 结构性搬移这一刀新增）
#
# 本仓此前在这一轴上只有下界那一半：`test_review_line_prompts.py` 的
# `test_the_prompt_version_moved_with_the_sections` 只断言 `int(PROMPT_VERSION[1:]) >= 24`。
# 它的名字与 docstring 声称守的是"段变了、版本要跟着动"，而机器判据看不见这件事 ——
# 改段不改版本照样绿。这里补上真判据：对每个角色渲染一次提示词取摘要，与一张冻结在
# 本文件里的"每角色 prompt 摘要"表比对，段与版本必须一起动（两个方向都判）。
#
# ## 维护规则（谁改段谁照它做）
#
# 谁改段谁在同一个 commit 里更新这张表与 `PROMPT_VERSION`。
# 这张表是版本相关性的读数（"这一版是哪些段"的指纹），不是面的基线 ——
# 所以它不随 `tests/golden/*` 重冻而变，也不许从 `tests/golden/*` 读
# （golden 那份是"面"的基线，重冻它不改变"段与版本"的关系）。
#
# ## 摘要口径
#
# `hashlib.sha256`（与 `llmseam` 的 `prompt_sha256` / `agent_prompts.prompt_audit`
# 同一个算法），取的是渲染出来的提示词，但把「提示词版本」那一行归一成
# `<PROMPT_VERSION>`：不归一的话，"只改版本号"本身就会改掉全部十格摘要，于是
# "版本动了而段没动"这一支永远不可达 —— 那半条反负控就成了摆设。
# 夹具另外把「证明工具链读数」钉成一个固定串：真读数随机器变（探针扫的是本机装了什么），
# 而这张表要守的是"段与版本一起前进"，不是"这台机器上装了什么"。
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

#: 冻结的版本号与十格摘要（口径见上）。更新规则：改段 ⇒ 同一个 commit 里改这张表 + 版本。
#:
#: `p40`（2026-10-07，题 9/B，所有者授权、主控代改）：`specs/b.py` 的 `register_statement`
#: 与 `specs/d.py` 的 `propose_question` / `write_report` / `register_conjecture` 四条
#: 动作摘要缩短（只删参数语义的复述与设计缘由，不删动作本身），八个角色的伙伴表或动作
#: 清单因此换了字。
#:
#: `p41`（同一次合并，主控统一）：上面那一刀与 `draft/68` 题 1（`citations` 加 `stmt:` 前缀）
#: 那一刀在两条并行线上各自抬过一次版本号（都写成了 `p40`）⇒ 合并时由主控统一成 `p41`，
#: 十格摘要在合并后的树上按同一口径与算法重算（生成器 `temp/_gen_digests.py`）。
#: 题 1 的提示词那一半：G 的 brief 新增"引我们自己的命题要用 `stmt:<命题号>`"，
#: 论文包那段（H 与 M 共享）的 `lit:` / `exp:` 补上 `stmt:`。
#:
#: `p42`（同日，`draft/68` 题 17 选 B，所有者授权）：`conductor.closing` 的工具摘要里广告了
#: `review_acceptance` 那一栏与可选参数 `cap_usd` —— 摘要只进 M 的工具面 ⇒ 只有 M 那一格换值
#: （实测：其余九格逐字不变，这本身是"摘要只落 M"的佐证）。同时它把题 16 的那一段
#: 补进了 `specs/g.py` 的镜像（那是声明面镜像、不是段，所以不进这张表）。
#:
#: `p43`（同日，`draft/68` 题 19 与题 20，所有者授权）：题 20 同步 A 的 `search_literature`
#: 声明（`returns` 按实现如实改写）与 A 提示词里的两格；题 19 让工具面 `citations` 的描述
#: 教出 `stmt:` 前缀，那件工具在 A 的工具面上。两刀合起来实测只有 A 那一格换值。
#:
#: `p44`（2026-10-08 晚，所有者 T18）：插话通道收窄成"只有用户能发、只有主控 M 会收到"
#: ⇒ 改的是共享段那段【插话】⇒ 十格全部换值（与 p42/p43"只动一格"正好对照：
#: 换几格本身就是这次改动作用域的读数）。
#: `p45`（2026-10-08 深夜，S1d）：`AGENT_IDENTITY`（共享段）补两格事实 ——
#: `{{parent_task_id}}`（我父的台账号）与 `{{children}}`（此刻我名下的子代理台账号）。
#: 业主 T21 的追问「不就应该是知道我的父代理是谁，子代理有谁，然后往它们按编号沟通吗」
#: ⇒ 数据本来就在台账里，缺的是渲染。落在共享段 ⇒ 十格全部换值（同 p44 的读数形态）。
#: `p46`（2026-10-08 深夜，S1i）：`TASK_FRAME`（共享段）补一格 `{{board}}` —— 挂在我名下的
#: 工作项进上下文（业主 A3=甲 "渲染即 seen" 的渲染那一半）。同 p44/p45：共享段 ⇒ 十格全换。
#: `p47`（2026-10-08 深夜，S1k-2）：循环协议八种形状 → 十种（新增 `retire` / `roster`），
#: 且 `summon` 里补 `brief` / `name` / `reuse` 三格（名册口径）⇒ 十格全换。
#: `p48`（2026-10-09，S6-a）：公共频道的可见面收窄成"发信人的直接子代理"（业主 T20/T21）——
#: 循环协议里"所有角色都会在自己的收件箱里看到它"、手稿 `ALL`、叫停那句、角色定位
#: "能互动"那一句同批改（留旧句子就是教模型按错的语义广播）⇒ 十格全换。
#: `p49`（2026-10-09，S6-b）：新增 `conductor.broadcast` ⇒ 七个角色 + M 的工具体清单
#: 那一格变了；C/H/V 只读、不在它的 `roles` 里 ⇒ 那三格逐字不动。
#: `p50`（2026-10-09，业主三句裁定）：收工由自己判（被派的活做完没有；M 自列任务列表、
#: 收工时交 `task_list`/`goal_met`）、干不了就上报父 / M 上报用户、机器八格是读数不是判决
#: ⇒ 共享的循环协议 ⇒ 十格全换。
#: `p51`（2026-10-09，同一批的补）：`conductor.closing` 的工具说明那一句还写着旧口径
#: （"`can_close` 只在八格全过时为真"）—— 模型读的就是那一句，与 p50 的新语义当场相反 ⇒
#: 改那一句 + 同一张表里那一行。只有 M 有这件工具 ⇒ 只 M 那一格变（其余九格逐字不动，
#: 这正是这条判据该有的分辨率：改一处、只动该动的那一格）。
#: `p52`（2026-10-09，S1g-2）：共享的循环协议新增一句"派活那一刻秘书还会替你看一遍
#: 『这件活在被派人的读写面里做不做得成』"（业主 2026-10-09：「"超越职责"的一个主要可能
#: 是无法在被分配的读写面内完成任务，这个秘书也要帮忙看」）⇒ 共享段 ⇒ 十格全换。
#: `p53`（2026-10-09，交付格式词表 + 引用两阶段）：M 的 `brief.policy` 新增两条 ——
#: 真身在 `src/agentflow/specs/m.py`（`agent_prompts.ROLE_BRIEFS["M"]` 是镜像，
#: 两处逐字相同，`test_agent_spec_reconciliation` 按位比）⇒ 只有 M 那一格变。
#: 业主授权（2026-10-09）：「禁改区允许你在仔细考虑后先进行改动和测试，后面我再审」
#: —— 这一处禁改区改动待人审，`noai_gate` 会报 requires_human(1)。
#: `p54`（2026-10-09，S1p）：M 的受控档位清单加 `reviewed_then_digested_rows`
#: （实现在 `closing.py`；业主：「D 的手稿过审后是否被 B 消化或研究成果逐条入库。
#: 前置条件具备了，C 才能在里面找依赖链」）⇒ 只有 M 那一格变。
#: `p55`（2026-10-09，S1o 前半的补 `ec70789`）：`specs/c.py` 新增动作 `C.proof_chain`
#: —— 那一轮只加了动作，没有同轮更新这张表与 `PROMPT_VERSION`（判据当场抓出来：
#: "段变了（['B','C','D','F','M']）而 PROMPT_VERSION 还是 'p54'"）。这一段补上：
#: 伙伴表里逐条列着"这个伙伴能调用的动作" ⇒ 能召唤 C 的角色那一行换字。
#: `ALLOWED_EDGES` 里能召唤 C 的是 B / D / F / M（A→[B]、E→[B,D]、G→[A,D,E,F]、
#: H→[A,E,G]、V→[F] 都不含 C）⇒ 实测换值五格 = C 自己 + 那四个，
#: 其余五格（A/E/G/H/V）逐字不动 —— 换几格本身就是"谁看得见 C"的读数。
#: `p57`（2026-10-10，S1r 并表落刀）：`specs/b.py` 的写集去掉 `concepts`（表退役）⇒
#: 十格全换 —— 伙伴表在每个角色的提示词里都逐条列着"这个伙伴写哪些表"，B 的写集
#: 一动，看得到 B 的那些行全换；实测十格摘要无一相同（现算脚本 `temp/_s1r_prompt_digests.py`
#: 逐格对照过）。与 `p55`（只换那五格）对照着看，"换几格"本身就是这次改动的读数。
#: `p58`（2026-10-10，T1 第 18 趟的门槛）：`specs/m.py` 加了一句"收工前也落一份状态报告"
#: （`draft/38` §7 第三组判据里"M 的状态报告落盘"一直没满足，因为提示词只在用户问时才要求）
#: ⇒ 只换 M 那一格（现算脚本 `temp/_s1r_prompt_digests.py` 逐格对照过）。
#: `p59`（2026-10-10，T2 第 24 趟的交付面读数）：`doc.build_document` 的 `returns=` 里加了
#: `meta.citation_coverage` 那一句 —— 工具返回值的声明是 M 提示词的一部分 ⇒ 只换 M 那一格。
#: `p60`（2026-10-10，D 的交付物声明更正）：D 的 `deliverable` 原先点名 `analysis_reports`
#: （那是 C 的报告通道，D 的写集里没有它）⇒ 改成指向 `write_report` 写出的报告文件。
#: 看得见 D 那一行的角色全换 ⇒ 实测五格（D/E/F/G/M），现算脚本逐格对照过。
#: `p61`（2026-10-10，T4 第 8 趟的漂移）：M 的「清单本体」那一句补了半句 ——
#: 清单的每一条要写「题目问的那个领域」里的事，C 的关系读数是"依据"、不代替清单本体
#: ⇒ 只换 M 那一格。
#: `p62`（2026-10-10，T4 第 9 趟的反面）：`p61` 那半句只说"C 是依据" ⇒ M 把它降成叙述、
#: 交付面连一条 `rel:` 都不引 ⇒ 补全为"C 的读数也要真的被引到"（至少引一条 `rel:`）。
#: 仍只换 M 那一格。
#: `p64`（2026-10-10，裁定 10丙「提醒3次、判停5次」+ 12-F 计数按委托记账）：那一句散文在
#: 十格里都有（"别原地打转"是共用段）⇒ 十格全换；这正是"改一个数字、十格都动"的读数。
#: `p65`（2026-10-10，S-F 裁定 12-K「步数上限不作硬标准」）：把"步数或预算耗尽时你必须收工 /
#: 框架会在最后一步要求你收工"改成"预算耗尽才收工 + 每满阈值向父代理报一次账"，另两处
#: "步数有限"的说辞同样改掉 ⇒ 换的是共用段（循环协议），所以十格全换。
#: `p66`（2026-10-10，S-H 裁定 14）：协议补第 9 条 `interrupt`（停某一个子代理当前那一轮，
#: 不是全局叫停）+ 名册那一句补 `scope=descendants` 与三格新读数（status / in_flight /
#: last_reading）⇒ 又是共用段，十格全换。
#: `p67`（2026-10-11，业主口径「一切以代码为参考」；`draft/105` 的 A22/A24 两条）：
#: 两处在共享段里指了一件收件人没有的工具 ——
#:   ① 纸包第二节原写"用 `conductor.acceptance` 读它"，而那一件只发给 M
#:      （`conductor_tools.py` 的 `roles=("M",)`）⇒ G/H 读不到；改成"主控用它读、G/H 直接
#:      `fs.read` 那个文件"；
#:   ② 手稿协议原写"对方用 `manuscripts.read(...)` 读全文"，而 `_READ_ROLES` 不含 M
#:      （`manuscript_tools.py` 逐字记着"M 的读面是 `fs.*` 白名单，扩它要裁定"）⇒
#:      改成把两条读法都写明（含"主控直接读那个追加式账本"）。
#: 两处都在共享段（`PAPER_PACK` 与 `HANDOFF_PROTOCOL`，后者十格都有）⇒ 十格全换
#: （下面的读数：`temp/_s1r_prompt_digests.py` 逐格对照，十格无一相同）。
#: `p69`（2026-10-11，E 的迁移批：业主裁定 G「E 的工具链专属段要」+ 拆段）：
#: 证明工具链那一轴拆成两段 —— 事实（`TOOLCHAIN_FACTS`，全角色）与
#: 怎么写（新段 `TOOLCHAIN_FORMAL`，order 9010，只发给手上真有 `verify.check_formal`
#: 的角色，现算 = E / F / G）。原来那句"由上一条推得：要用 Mathlib 就显式传…"是写在
#: 事实段末尾的（十格都有），现在按读数现算成三档、只发给会写 Lean 源码的角色。
#: 读数（夹具固定值下逐格对照）：只有 E / F / G 换（段各 +1：E 61→62 / F 72→73 /
#: G 87→88），其余七格一个字节都没动 —— 夹具把事实段钉成了固定串，那句"由上一条推得"
#: 本来就不在夹具里。真机上它还会从另外七个角色的文本里消失（那七个不写 Lean 源码），
#: 两份读数都在 `draft/103` §4.1b-4。
#: `p70`（2026-10-11，协作块族第一块：派活上限；业主裁定 A「上限数字写、且现算」）：
#: 新段 `PARENT_LIMITS`（order 5210，`draft/104` §6-1 合并后的协作块号段）——
#: 四类上限（同时在飞 / 深度 / 全局并发 / 总量）+ 墙钟，数字全部从这一次 run 的
#: `Policy` 现算（`policy.Policy` + `fanout_limit_for`）。受众从能力表现算：
#: 出边非空的九个角色（实测只有 C 出边为 0 ⇒ 它连 `summon` 都发不出）。
#: 读数：A/B/D/E/F/G/H/V/M 九格换，只有 C 那一格逐字不动（段数 +1：A 65→66、
#: B 58→59、D 71→72、E 62→63、F 73→74、G 88→89、H 76→77、V 55→56、M 68→69）。
#: 这一批的理由是真机读数（`draft/104` §2.1）：四类上限在提示词里一个数字都没有，
#: 而模型知道自己的 `depth` 却不知道上限是 5（主控同时在飞 20）⇒ 只能撞上去再回头。
#: `p71`（2026-10-11，协作块族第二块：收件人与名册口径；`draft/104` §4.1 甲案 / §4.2）：
#: 两处纯文案改到以代码为准 ——
#:   ① 代唤与上报的收件人：`agent_loop._relay_recipient` 一直发给直接父
#:      （只有顶层 / 父那一行读不成才落回 M），而提示词三处还写着"发给主控 M"
#:      （立项时的措辞，2026-10-09 的裁定漏改了文本）⇒ 改成"直接父"；
#:   ② 名册是快照：`AGENT_IDENTITY` 原写"此刻你名下的子代理"，而
#:      `agent_loop._children_text` 逐字写着"这一趟开始那一刻的名单，不假装实时"
#:      ⇒ 改成"这一趟开始那一刻…要看活的用 `{"roster": {"of": "self"}}`"。
#: 两处都在共享段（循环协议与身份段）⇒ 十格全换（这是"改一处、十格都动"的读数）。
#: `p72`（2026-10-11，协作块族第三块：指称与 blocked 口径；`draft/104` §4.4 / §4.10）：
#:   ① 新段 `COLLAB_NAMES`（order 5220）：三种指称的总判据（台账号对账 / 名册名指称 /
#:      实例标签分实例 / 产出用台账引用）—— 原文只在受控拒绝的文案里说"绝对编码不是
#:      父子之间的指称"，模型要犯一次错才读得到。受众与 `PARENT_LIMITS` 同一条判据
#:      （出边非空 ⇒ 实测九个；C 出边 0、一辈子没有子代理）⇒ 那九格 +1 段；
#:   ② 循环协议第 ② 档补一句：`blocked` 只管「我停下了」、上报只管「有人知道了」——
#:      两件事都要做（原文只写"照旧上报一次"，容易被读成二选一）⇒ 共享段 ⇒ 十格全变。
#: 合起来：十格全换（九格是"加段 + 换字"、C 那一格只是"换字"）。
#: 尾注：名册名那一句的措辞刻意沿用探针表里的锚（"父可以自己提名 / 由秘书分配 / 名字一经分配"）——
#: `tests/test_secretary_prompt_alignment.py` 按这些短语把"提示词承诺的秘书职责"与代码里的接住方
#: 对上；换一套同义词会让它判成"承诺了没人接住"（第一版正是那么红的）。
#: `p73`（2026-10-11，批 Q1：`draft/105` 的五条"提示词写错/写旧了" + 一条通用判据）：
#:   ① B1：`manuscripts.write` 不是工具（从前写着"要发给某一个同伴看就用它"）⇒ 改成"手稿是 `handoff` 形状"；
#:   ② B2：`message.send` 不存在（`message` 是形状）⇒ 改成"走 `message` 形状（留言）"；
#:   ③ A25：公共频道两种拼法（`#public` / `ALL`）说清一次 —— 两个名字同一个频道、框架两个都收；
#:   ④ A19：打转提醒的口径改成"同一个调用连着第 3 次"（代码只认 `same_call`，不要求读数相同）；
#:   ⑤ A20：`ask_user` 的语义改成"这一趟停在原地等（`stop_reason="waiting_for_user"`）"，
#:      `user_no_answer` 只是"还没答"那一个读数；
#:   ⑥ A15：`#public` 那条补上例外（框架自己发的通报对所有角色可见）。
#: 全在共享段 ⇒ 十格全换；段数不变（换字，不加段）。
#: `p74`（2026-10-11，批 Q2：`draft/105` 的 A12/A13/A14 三条 —— 名册复用、被拒的是哪一件事、
#: 草稿本的存活期）：
#:   ① A12：复用也要给 `brief`（`secretary.roster_add` 先查简介、再看 `reuse`；
#:      只给 `reuse` 时那一笔名册绑定不落、`roster_problem` 里写明，而派活照样进行）；
#:   ② A13："被占用或已销号 ⇒ 这一句会被受控拒绝"改成"被拒的是那一笔名册登记"；
#:   ③ A14：`note` 从"只活在这一次会话里（收工后查不到）"改成"盘上的文件
#:      `notes/<你的角色号>.md`"（同批也修了 `specs/m.py` 里同一处错误说法 —— 禁改区，
#:      记 FC-27 人审）。
#: 全在共享段 ⇒ 十格全换；段数不变（换字）。
#: `p75`（2026-10-11，批 Q3：`draft/105` 的 A3/A4/A5 —— 三个形状各有"代码收了、提示词没说"的字段）：
#:   ① `summon_many` 的每一项还能带名册三格（`brief` / `name` / `reuse`）；
#:   ② `message` 补 `reply_to`（回一条已存在的对话 ⇒ 不再要求协作边）；
#:   ③ `handoff` 补 `revises`（订正某一号，旧行保留）与 `why`，`to` 的例子统一成 `ALL`。
#: 全在共享段 ⇒ 十格全换；段数不变（换字）。
#: 注：2b 那一段正文在仓库里有三份（`LOOP_PROTOCOL` 内联、`agent_prompts._LOOP_BLOCK_C`、
#: 本文件 `_BLOCK_C` 那份判据自己的逐字副本）—— 改一处会先后撞两个 assert（模块级那个 +
#: 本文件模块级那个）。这是刻意的（副本被改过就当场炸），但也意味着改 2b 要改三处。
#: `p76`（2026-10-11，批 Q4：`draft/105` 的 A7 —— `ask_user` 只有主控能用）：
#: 形状 6) 的抬头补"只有主控 M 能直接用这个形状（你不是主控 ⇒ `problem` 是
#: `not_conductor`，把未决问题写进最终结果交回召唤者或请 M 代问）"，规则里那条
#: "只有用户能定的取舍"同步改（原来对所有角色说"要用 ask_user 问"，且"等不到就按
#: 最保守的做法继续"与代码相反：有人值守时它是停在原地等、无人值守那一档才 fail-closed），
#: D 的"能互动"那一格也改成"交回召唤者或请 M 代问"。全在共享段 ⇒ 十格全换；段数不变。
#: `p77`（2026-10-11，批 Q5：`draft/105` 的 A26 —— V 的真实入口；A23 经核对为"已满足"）：
#: V 的伙伴表那句"你可以唤起这些伙伴：F"旁边补一句入口说明（"你的真实入口不是这套循环：
#: V 是一次性问答，框架用 `verifications.cold_start_prompt` 直接问你一次；下面这套循环只在
#: 有人 `--drive V.<动作>` 时用得上"）。受众从声明现算（实现类是 `agentflow.agent_v`）。
#: 读数：只有 V 那一格变（A/B/C/D/E/F/G/H/M 九格逐字节不动）—— 这正是这条判据
#: 该有的分辨率。`PROMPT_VERSION` 仍要动（段与版本必须一起前进）。
#: `p78`（2026-10-11，批 Q6：`draft/104` §4.9 —— 「什么时候停」合成一块 `PARENT_STOP`）：
#: 把循环协议 16 条规则里的三条（预算耗尽 / 原地打转 / 上报两档）逐字搬到新段
#: `PARENT_STOP`（order 5230），协议里相应删掉；顺手把留在协议里的那句交叉引用
#:（"如实记成上面那一档「职责之外」"）改成"见下面「什么时候停」那一段"（它现在在下面了）。
#: 读数：十格全换 + 段数各 +1（A 67→68、B 60→61、C 62→63、D 73→74、E 64→65、F 75→76、
#: G 90→91、H 78→79、V 57→58、M 70→71）—— 三条对十个角色都有意义（谁都可能预算耗尽、
#: 原地打转、或做不了某件活），所以这一次不分受众。
#: 判据 `test_the_stop_rules_moved_out_of_the_loop_protocol_verbatim` 在段层两头钉：
#: ① `LOOP_RULES` 里不再有、② `PARENT_STOP` 里逐行都有、③ 整篇各只出现一次
#: （抄 ⇒ ①红；重写 ⇒ ②红；两样都做 ⇒ ③红）。
#: `p79`（2026-10-11，批 Q7：`draft/104` §5.1 的 `PARENT_ROSTER` —— 名册的用法）：
#: 新段（order 5240）四条：快照不是现状 / `reuse` 复用名字不复用名额 / 真并发只有
#: `summon_many`+`instance` / 停与退是两件事。受众与 `PARENT_LIMITS`/`COLLAB_NAMES` 同一条判据
#: （出边非空）⇒ 九格换（各 +1 段）、C 那一格逐字节不动（它一辈子没有子代理）。
#: 两条有代码锚：`_decode_shape` 对 `summon` 会丢掉 `instance`（`summon_many` 留着它）、
#: `roster_add` 的 `reuse` 支是往对照表写 `bind` 绑到新 task_id（⇒ 名额照占）。
#: `p80`（2026-10-11，批 Q8：`draft/104` §5.1 的 `COLLAB_FIVEBITS` —— 五元位）：
#: 新段（order 5250）现算自 `evidencebits`：五位（`BIT_NAMES`）各自谁签（`BIT_LEDGERS`
#: 的 `owner`）与凭据去哪张表（`ledger`）+ 四态 + 等级也是现算的。
#: 受众 = 全部十个角色（§5.1 原写"M/G/H/V"，落地时按"证据语法对所有人"给全；
#: 段很短，不会淹掉别的）。
#: 读数：十格全换 + 段数各 +1（A 70、B 63、C 64、D 76、E 67、F 78、G 93、H 81、V 60、M 73）。
#: `p81`（2026-10-11，批 Q9：`draft/104` §5.1 的 `COLLAB_BOARD` —— 工作项板的语义）：
#: 新段（order 5260）现算自 `schema` 的四张词表（`ITEM_KINDS` / `ITEM_EXPECTS` /
#: `ITEM_STATES` / `ITEM_CLOSES`）+ 状态机那三条不变量（`done` 前必须 `seen`、
#: 渲染即 seen、没读就 ack ⇒ `ack_unbacked` 读数）+ "板项不是子代理"。
#: 受众 = 全部十个角色（板项可以开在任何一个角色名下）。
#: 读数：十格全换 + 段数各 +1（A 71、B 64、C 65、D 77、E 68、F 79、G 94、H 82、V 61、M 74）。
#: `p82`（2026-10-11，批 Q10：`draft/104` §5.1 的 `COLLAB_SHAPES` —— 十一种形状"用哪个"）：
#: 新段（order 5270）是一张决策表（"要做什么 ⇒ 用哪个形状"），形状的写法仍只在
#: 循环协议那张表里（不写第二遍）。同批登记：`COLLAB_ADDRESS` / `COLLAB_RELAY` 不单独落
#: —— 它们的正文逐句核过，已经写在 `message`/`handoff` 那两个形状与代唤那条规则里。
#: 读数：十格全换 + 段数各 +1（A 72、B 65、C 66、D 78、E 69、F 80、G 95、H 83、V 62、M 75）。
#: `p83`（2026-10-11，批 R1：M 的迁移第一小批 —— `M_DELIVERABLE` + 两处"步数有限"的说辞）：
#:   ① `OUTPUT_CONTRACT` 那句"你没有对外可被调用的动作"对"对外动作数为 0"的角色
#:      （受众由 `actions_lines` 现算 ⇒ 只有 M）读起来像缺省值 ⇒ 改成"这是设计，不是缺口"
#:      + 三张面（对用户 = 收工那句 `final`；对同伴 = 任务行与手稿；对框架 = `conductor.*`）
#:      + 交付说明落 `out/review/REPORT.md`（`draft/106` §4 的 `M_DELIVERABLE`）；
#:   ② `specs/m.py` 两条政策都拿"步数有限"当前提：一条写"步数有限：现状侦察最多做一次…"、
#:      一条写"步数预算有限，留出最后几步…"，而同一份提示词的协议里写着"框架不设步数闸"
#:      （`agent_loop` 的步号计数器是无限的，`max_steps` 只当报告阈值）
#:      ⇒ 一格里两句互相打脸（`draft/105` A21 的第三处与它的同族；前两处由 p65 修）。
#:      两处都按代码改：去掉错前提、留下规则（别拿只读调用把这一趟填满 / 收工门看的是盘上那份）。
#: 三处都只动 M ⇒ 只有 M 那一格换（其余九格逐字节不动），段数不变：M 47,110 → 47,347 字。
#: 逐格读数用 `temp/read_prompt_grid.py`（口径从本文件导入，不另抄一份）。
#: `p84`（2026-10-11，批 R2：`draft/106` §4 的 `M_FIVEBITS` 的另一半 —— "够不够交"怎么判）：
#: M 那条验收表政策里对 `reviewed_proof_rows` 只写着"（有证明过程 + 审过的我方命题）"，
#: 于是它读不出三件事（三件都现算自 `closing.py` 的 `reviewed_proof_rows` 读侧）：
#: ① 等级是五位现算的（不读盘上存的那份），引用命题（`origin=external_lit`）到高档也不算；
#: ② "0 条"有两种，靠 `statements_without_bits` 与 `statements` 是否相等分开
#: （相等 ⇒ 产出方根本没走过位记录；小于 ⇒ 算了、只是不够档）；
#: ③ 要抬档只能去派签位的人（数值 / 形式化 E、证明 F、审过 V、正式审查 H；
#: 写位的是 B 的 `register_statement`）。
#: 只动 M ⇒ 只有 M 那一格换（其余九格逐字节不动），段数不变：M 47,347 → 47,682 字（+335）。
#: 本批刻意不新增判据：这是文本搬运，两头已有判据（spec↔prompt 逐字对账 + 冻结摘要）；
#: 按业主口径"尽可能避免做机器判据"，也按 `draft/105` D3 的教训（钉词的判据会被
#: 别的角色谈到同一个概念钉红）—— 不为这一句话新钉一个词。
#: `p85`（2026-10-11，批 R4：F 的迁移第一批 —— `draft/108` §二·F 的靶子 1–4）：
#: `specs/f.py` 补三条硬边界 + 一条政策，四件全部是代码里已经硬的、而提示词一个字没说的
#: （词频实测各 0 次）：① 预算四类键缺一不可（`max_rounds` / `max_parallel_subgoals` /
#: `max_persist_attempts` / `max_depth`；`create_plan` 判 `budget_incomplete` 拒绝创建，FC-18）；
#: ② 停下必须交 `best_partial`（`status='stalled'` 的 schema 硬条件 + `verify` 的
#: `stalled_without_partial` 判据）；③ 子目标 `closed` 必须有 proof 级证据，数值/穷举支持
#: 只能 `supported_not_proved`（FC-22）；④ 子目标 `blocked` 时 `blocked_reason` 必填
#: （"不许静默卡住"是 schema 的硬条件）。
#: 作用域读数（一处改动、五格换值）：F 自己那格换（25,453 → 26,079 字，段数 80 不变），
#: 另外四格是伙伴表把它带过去的 —— 出边指向 F 的 D/G/V 与"唤不起它"的 M，
#: 它们的 `PARTNERS` 里逐条渲染 F 的边界条数（「它的边界共 4 条」→「7 条」，
#: 字数一个不变、只有摘要变）。这本身是"改动作用域"的读数。
#: `p86`（2026-10-11，批 R6：D 的迁移第一批 —— `draft/108` §二·D 的靶子 D1–D5）：
#: `specs/d.py` 补三条硬边界 + 一条政策、改写一条政策，五件全部对着代码：
#: ① 回答完要自己推状态（`research` 只推 `researching`；`answered` 只有 `research.set_status`
#: 与矛盾裁决两个写入点 —— 真机 118 行 `research_questions` 里 `answered` 0 行，CS-5）；
#: ② `needs_evidence` 必须带非空 `waiting_request_ids`（`research_tools.py:260-262`）；
#: ③ 猜想九个状态各自必须带什么（`schema.Conjecture.validate`，`schema.py:756-820`）；
#: ④ 证据就绪的三条可核实判据（`agent_d/_support.py:241-330` 的 `analyze_gaps`）；
#: ⑤ 猜想登记的判重与更新（`tools/conjecture_tools.py:107-136`）。
#: 作用域读数：D / E / F / G / M 五格换值，A / B / C / H / V 逐字节不动。
#: D 自己那格 25,896 → 26,954 字（段数 78 不变）；另外四格是伙伴表把 D 的边界条数
#: 带过去的（「它的边界共 4 条」→「7 条」，字数一个不变、只有摘要变）。
#: `p87`（2026-10-11，批 R8：C 的迁移第一批 —— `draft/108` §二·C 的靶子 C1–C3）：
#: `specs/c.py` 改三处，都对着代码：① "产出登记口是 `handle`" 写进它的动作摘要与返回说明
#: （`agent_c/handle.py:26-43`；真机 100 个工作区 `analysis_reports` 全 0 行、唯一一次
#: `handle` 召唤因缺 `request_text` 被拒）；② 五个分析动作的返回说明里那句"要落库需显式
#: persist"改成"落库走 `handle`"（`persist` 是调用不了的动词，属 B1/B2 同族）；
#: ③ "只读"说准（工具面全量只读；能落库的只有两处登记过的例外）并消解
#: `local_notes['敢创新']` 与政策第 2 条的表面矛盾。
#: 作用域读数：B / C / D / F / M 五格换值（C 自己那格 17,901 → 18,383 字、段数 66
#: 不变；另外四格恰好是能唤 C 的四个角色，各 +304 字 —— 伙伴表里逐条渲染它的动作摘要）。
_FROZEN_PROMPT_VERSION = "p98"
_FROZEN_PROMPT_DIGESTS: dict[str, str] = {
    "A": "1136cd1c3cc3b44186447cdecd9c4cb93a865c41b724765a41b17d7e7b18c3db",
    "B": "181e81bd0acebc0f7bd24d09b3495d95405fbdeed8ee97f9986bdb898f940a5c",
    "C": "0db1c148033a1e57a00cd6c51e4f74bfe5a2171a2cd67397ea5a7a8a86e2b5fe",
    "D": "6f1788f41dcd54c60dd00ca229ad61cc4dfc9e2cbd69f1e22703b0ad04f18c95",
    "E": "65c6e6a047df3af559d09a37b4df78f1b7b968e571bc8b80425d0d75bf6a69b5",
    "F": "c68a82f083e6e7e464b0340a44e2bc1432538cec95710c6a930f735bbdcc01e4",
    "G": "bae081d6343510e3cb10dc17b8c253606f150bf309d408bc8cdcc7eeda43f06f",
    "H": "70453c1278a7eb0b73621b6894c7fda79afa6f4ef8f87444c51bec407d32a619",
    "V": "02f14a2aed20f4bfc32b035f78928d4c46fb8a0195b4bcf510e406b56d7782f7",
    "M": "caca552c89b56589c857d971f828244a7b24b1e2c54561afc17da5337949635f",
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
