# -*- coding: utf-8 -*-
"""业主 2026-10-22 第四批：所有受 Lean 开关控制的提示词 / 工具 / 动作一律指向 L。

业主口径逐字：「要保证 L 侧完全被 Lean 开关隔离，并改写所有智能体被 Lean 开关控制的
提示词、工具、动作等全部指向 L」。

## 这一份判什么（六条）

| # | 档 | 判据 |
|---|---|---|
| ① | 开 | 每一条"在讲 Lean 形式化"的指引都点着 L，且不再把 E 当形式化入口 |
| ② | 开 | L 自己那份提示词里有实质内容：`statement_full` / `proof_text` / 逐步 / 三态 / `code/formal` |
| ③ | 关 | 所有可见角色的渲染文本里，角色名 `L` 出现 0 次、`formal.` 出现 0 次 |
| ④ | 同进程 关→开→关 | ①②③ 都跟着开关变（不许停在缓存里的旧值） |
| ⑤ | 反真空 | 把 `leanscope.is_hidden` 钉成恒 False ⇒ ③ 必红 |
| ⑥ | 回归 | E 的动作面与工具面原样（`test_lean_switch.py` 作子进程跑，退出码 0） |

## ① 的射程（为什么不是"凡含'形式化'三个字"）

"形式化"在中文里有两个用法：Lean 形式化（本判据的对象）与"把问题精确地形式化"
（数学写作里的措辞，与 Lean 无关，例如 `specs/g.py` 的体例那一条）。把后者也算进来
只会逼着每一句数学写作去提 L —— 那不是业主的意思，也会把判据变成噪音。所以一条句子
只有同时满足下面三条才进 ① 的射程：

1. 含「形式化」；
2. 还带 Lean 那一族的记号（`Lean` / `检查器` / `源码` / `formal.` / `机器核` / `formalize`）——
   或者它点名了某个角色（那就是"这件事归谁"的句子）；
3. 不是在讲"开关关掉之后这一档不存在"（`已关闭` / `关掉时` 那一类描述句）。

另外两类刻意不在射程里，各自都有理由：

- 「不许写『已形式化验证』」这一族措辞禁令：它管的是用词，不是"谁做形式化"；
  判据先把这个受控短语摘掉再看还剩不剩「形式化」；
- 工具面/动作面那一行本身（`- <工具名>：<摘要>`）由工具面现算，措辞的真身在
  `tools/*.py` 的 `ToolSpec.summary` —— 它们的形状是"能力清单"，不是"这件事归谁"的指引。

## 零模型

全部用例只读代码与本地开关：不起子进程跑模型、不写工作区。唯一一条子进程是
第 ⑥ 条的 `pytest tests/test_lean_switch.py`（它自己也是零模型的）。
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

from agentflow import agent_prompts as AP
from agentflow import leanscope as LS
from agentflow import schema as S
from agentflow import settings as SET
from agentflow.tools import build_registry

#: 那个只在开关打开时存在的角色。
ROLE_L = "L"

#: 角色名 `L` 的记号。口径与 `tests/test_l_is_isolated_when_lean_is_off.py` 同一条：
#: 边界按 ASCII 词字符算，所以 `Lean` / `Mathlib` 里的 L 不算，`L 的` / `（L）` 算。
#: 为什么不能按裸字母 `L` 数：渲染文本里 `ALL`（公共频道）/ `LLM` / `L1`（溯源档）都带 L，
#: 那些与角色无关 —— 真读数见下面 `_counts()` 报的两列（role_L 与 raw_L）。
ROLE_NAME = re.compile(r"(?<![A-Za-z0-9_])L(?![A-Za-z0-9_])")

#: "把 E 当形式化入口"的两种形状：`E.xxx` 这种动作/工具名，以及"形式化…E"这种挨着写的。
E_TOKEN = re.compile(r"`E\.[a-z_]")
E_AFTER_FORMAL = re.compile(r"形式化[^。\nL]{0,8}E(?![A-Za-z0-9_])")

#: "把 E 当形式化入口"的那几种形状（逐条给一句人话：红的时候读者要知道改哪一句）。
E_POINTERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"`E\.check_formal`"), "仍把 `E.check_formal` 当形式化入口"),
    (re.compile(r"`E\.run_experiment\(\s*method"), "仍把 E 的 formal 实验当落库入口"),
    (re.compile(r"`E\.formalize`"), "仍把 `E.formalize` 当形式化入口"),
    (re.compile(r"形式化[（(]E[）)]"), "形式化后面写着 E"),
    (re.compile(r"形式化找\s*E(?![A-Za-z0-9_])"), "「形式化找 E」"),
    (re.compile(r"形式化.{0,6}交给\s*E(?![A-Za-z0-9_])"), "「形式化交给 E」"),
)

#: 句子切法：中文句末与换行（`；` 不算 —— 它常把"这件事归谁"与"怎么做"连在一句里）。
SENT_SPLIT = re.compile(r"[。\n]")

#: Lean 形式化那一族的记号（见模块 docstring 的"① 的射程"）。
LEANISH = ("Lean", "检查器", "源码", "formal.", "机器核", "formalize")

#: 受控的措辞禁令（摘掉之后再看还剩不剩「形式化」）。
WORDING_BAN = "已形式化验证"

#: "开关关掉之后这一档不存在"那一类描述句的记号。
OFF_BRANCH = ("已关闭", "关掉时")

#: L 自己那份提示词里必须有的实质（判据 ②）。
L_MUST_HAVE = ("statement_full", "proof_text", "逐步", "三态", "code/formal")


def _roles() -> tuple[str, ...]:
    return tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)


#: 这个文件开跑前的开关原值（`None` = 原来没设）。文件跑完由 `_restore` 放回去。
_ORIGINAL_SWITCH: str | None = None


def _set(on: bool) -> None:
    """改开关并清掉提示词层那个 `lru_cache`（`leanscope` 自己不缓存）。"""
    import os

    global _ORIGINAL_SWITCH
    if _ORIGINAL_SWITCH is None and SET.ENV_LEAN_ENABLED in os.environ:
        _ORIGINAL_SWITCH = os.environ[SET.ENV_LEAN_ENABLED]
    os.environ[SET.ENV_LEAN_ENABLED] = "1" if on else "0"
    AP.reset_toolchain_readings()


def _restore() -> None:
    """按原值放回开关（原来没设就删掉）并清缓存。

    为什么要这一步：`_set` 直接写 `os.environ`，不还原的话这个文件跑完会留下
    `AGENTFLOW_LEAN_ENABLED=0`，于是同一 pytest 进程里紧跟其后的
    `test_agent_prompts.py` 会看到「Lean 关」那一档并连带 38 条红
    （2026-10-22 实测复现过；单文件跑不会暴露，只有同一进程串跑才会）。
    写环境变量的判据文件都该自己收尾，不许把状态漏给下一个文件。
    """
    import os

    if _ORIGINAL_SWITCH is None:
        os.environ.pop(SET.ENV_LEAN_ENABLED, None)
    else:
        os.environ[SET.ENV_LEAN_ENABLED] = _ORIGINAL_SWITCH
    AP.reset_toolchain_readings()


def _prompt(role: str, registry) -> str:
    return AP.system_prompt(role, registry=registry)


def _registry():
    return build_registry().registry


def _counts() -> dict[str, dict[str, int]]:
    """这一档下每个可见角色的三格计数（`role_L` / `raw_L` / `formal.`）。"""
    registry = _registry()
    return {
        role: {
            "role_L": len(ROLE_NAME.findall(_prompt(role, registry))),
            "raw_L": _prompt(role, registry).count("L"),
            "formal_dot": _prompt(role, registry).count("formal."),
        }
        for role in LS.visible_roles(_roles())
    }


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]


def _formal_pointing_problems(role: str, text: str) -> list[str]:
    """这一份渲染文本里"讲 Lean 形式化但没点着 L"的行（判据 ① 的单角色尺子）。

    单位是渲染行（不是句子）：提示词的行就是它的排版单位，而伙伴表那一行
    `- L：…` 把"这一岗的职责"与"它自己的边界（原话）"放在同一行里 —— 按句子切会把后半截
    当成一句没有主语的孤立话（它其实在讲 L）。

    "在射程里"的判据是就近的：每处「形式化」前后 60 字里要有 Lean 那一族的记号，
    或者要有角色名 —— 这样"问题在这一节被精确形式化"（数学写作，前后 60 字里没有 Lean
    也没有角色名）不会被误判成"该指向 L 的指引"。
    """
    out: list[str] = []
    for line in text.split("\n"):
        if "形式化" not in line:
            continue
        probe = line.replace(WORDING_BAN, "")
        if "形式化" not in probe:
            continue
        if any(mark in probe for mark in OFF_BRANCH):
            continue
        in_scope = False
        for match in re.finditer("形式化", probe):
            near = probe[max(0, match.start() - 60):match.end() + 60]
            if any(mark in near for mark in LEANISH) or ROLE_NAME.search(near):
                in_scope = True
                break
        if not in_scope:
            continue
        if not ROLE_NAME.search(probe):
            out.append(f"{role}: 讲了 Lean 形式化却没点着 L：{probe[:120]}")
            continue
        for pattern, why in E_POINTERS:
            if pattern.search(probe):
                out.append(f"{role}: {why}：{probe[:120]}")
    return out


# --------------------------------------------------------------------------- ①
def test_on_every_formal_pointer_names_l(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关开：讲 Lean 形式化的指引只指向 L（逐角色逐句）。

    改前红（2026-10-22 实测）：E 的职责句「数值实验与形式化验证…」出现在每一份
    提示词的伙伴表里；M 的决策表写着「要一条硬的数或形式化裁决 → E」；G 写「形式化找 E」；
    H 写「断言能否形式化就找 E」；D 的立场句写「最终背书在形式化（E）或人」；
    `TOOLCHAIN_FORMAL` 那一段发给 E/F/G 三家，正文全是"你怎么写 Lean"。
    """
    _set(True)
    registry = _registry()
    problems: list[str] = []
    for role in LS.visible_roles(_roles()):
        if role == ROLE_L:
            continue          # L 自己那一段不讲"交给谁"，判据 ② 单独判它
        problems += _formal_pointing_problems(role, _prompt(role, registry))
    assert problems == [], (
        "开关开着时，这些句子仍在把形式化算在别人头上（或根本没说是谁）：\n  "
        + "\n  ".join(problems))
    # 反真空：这一档真的有点着 L 的句子（否则上面那条"没红"可能只是因为一句都没有）
    pointing = sum(len(ROLE_NAME.findall(_prompt(r, registry)))
                   for r in LS.visible_roles(_roles()) if r != ROLE_L)
    assert pointing >= 10, f"除 L 以外只有 {pointing} 处提到 L ⇒ 上一条可能是真空的"


# --------------------------------------------------------------------------- ②
def test_on_l_prompt_carries_the_formal_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关开：L 的提示词里要有那五样实质（输入 / 过程 / 落点 / 三态）。

    改前红：`TOOLCHAIN_FORMAL` 那一段是发给 E/F/G 的，L 拿到的是一份只讲"自检 + 检查器"
    的文本，`statement_full` / `逐步` / `三态` / `code/formal` 一个都没有。
    """
    _set(True)
    text = _prompt(ROLE_L, _registry())
    missing = [needle for needle in L_MUST_HAVE if needle not in text]
    assert not missing, f"L 的提示词里缺这些实质：{missing}"
    # 反真空：这五样不是在别的角色的文本里凑出来的 —— 它们必须同时出现在 L 那一份里
    assert len(text) > 5000, f"L 的提示词只有 {len(text)} 字符 ⇒ 这一条是真空的"


# --------------------------------------------------------------------------- ③
def test_off_leaves_no_trace_of_l(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关关：所有可见角色的渲染文本里，角色名 L 与 `formal.` 都是 0 次。

    "零痕迹"不许只做到"不渲染 L 的 prompt"：L 这个角色名、它的工具族名都不许留在
    别人的提示词里 —— 否则模型会去问一个这一档根本不存在的角色。

    改前红（2026-10-22 实测）：关着时每一份提示词末尾都有一行
    「本会话 Lean 形式化关闭：上面若有一条讲形式化的技能，它读来也做不了」，
    而 M 的伙伴表里还印着 `L：…` 那一行。
    """
    _set(False)
    registry = _registry()
    counts = _counts()
    assert ROLE_L not in counts, f"关着时 L 仍被算作可见角色：{sorted(counts)}"
    bad = {role: row for role, row in counts.items()
           if row["role_L"] or row["formal_dot"]}
    assert not bad, f"关着时仍有角色的提示词里留着 L 的痕迹：{bad}"
    for role in counts:
        text = _prompt(role, registry)
        assert "L：" not in text, f"{role} 的伙伴表里还有 `L：` 那一行"
        assert "形式化那一岗是 L" not in text, f"{role} 的提示词里还点着 L 那一岗"
    # 反真空：这一档的文本不是空的（十个角色加起来远大于 0，且 L 那一岗确实不在）
    assert sum(len(_prompt(r, registry)) for r in counts) > 20000, "关着时提示词被清空了"


# --------------------------------------------------------------------------- ④
def test_the_same_process_follows_the_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """同一进程内 关 → 开 → 再关：①②③ 的读数都跟着走（不许缓存）。

    改前红：③ 那一行（技能索引末尾的"Lean 形式化关闭"）在任何档位下都出现，
    所以"关"与"开"两档在它上面完全相同 —— 它证明不了开关接上了。
    """
    _set(False)
    off_first = _counts()
    _set(True)
    on_counts = _counts()
    on_l_text = _prompt(ROLE_L, _registry())
    _set(False)
    off_again = _counts()

    print("\n[同进程切换] 关着 role_L 合计 =", sum(r["role_L"] for r in off_first.values()))
    print("[同进程切换] 开着 role_L 合计 =", sum(r["role_L"] for r in on_counts.values()))
    print("[同进程切换] 再关 role_L 合计 =", sum(r["role_L"] for r in off_again.values()))

    assert off_first == off_again, "关 → 开 → 关 之后读数没回到第一次那一档（缓存停在中间态）"
    assert on_counts != off_first, "换到开着那一档之后一个读数都没变（判定没接上）"
    assert sum(r["role_L"] for r in off_first.values()) == 0
    assert sum(r["role_L"] for r in on_counts.values()) >= 10
    assert sum(r["formal_dot"] for r in off_first.values()) == 0
    assert sum(r["formal_dot"] for r in on_counts.values()) > 0
    assert all(needle in on_l_text for needle in L_MUST_HAVE)


# --------------------------------------------------------------------------- ⑧
#: "把形式化写成流水线一环"的那些说法（业主 B-5 口径逐字：「L 的形式化验证由于成本极高，
#: 口径改为：在全部研究和论文落定之后，用户指定有形式化验证需求时，要一条才做一条」）。
#: 这些词一旦出现在开档的提示词里，模型就会把形式化排进每一轮的工作流 —— 而那正是
#: 成本失控的形态。
#:
#: 口径：只收把"形式化"本身写成必过的短语。为什么不用"每个 / 都要"这种宽词：
#: 它们在论文体例那几条里正当出现（「每个 theorem / lemma / proposition 各带一个
#: `\begin{proof}`」—— 那讲的是证明的粒度，与形式化无关），宽词会让这条判据把正确的
#: 句子判红，于是它很快变成噪音（本仓对假阳性的一贯判词）。
PIPELINE_PHRASES = (
    "每个证明都要", "每个定理都要形式化", "都要过一遍", "都要形式化",
    "都必须形式化", "必须形式化", "必派两步", "一律形式化", "每条形式化",
    "两步都要走，两步都要走",
)

#: "用户指定之后才对单条执行"这件事必须在提示词里说清（否则 ⑧ 只是"删干净了"）。
USER_SPECIFIED = ("用户指定", "成本极高")


def test_on_formal_is_not_written_as_a_pipeline_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关开：形式化不许被写成"流水线上的一环"（业主 B-5，2026-10-22 口径变更）。

    业主原话：「L 的形式化验证由于成本极高，口径改为：在全部研究和论文落定之后，用户指定
    有形式化验证需求时，要一条才做一条。」

    ⇒ 开档下允许出现 L（它不是被隔绝的那一档），但不许出现"每个证明都要过一遍"
    那一类叙述；同时"用户指定之后才对单条执行"这条顺序必须写清 —— 只删干净不算做到
    （那样模型既不知道有这条路，也不知道它什么时候开）。

    改前红：`specs/m.py` 的政策原文是「开关开着、而任务原文要求形式化时，你必派两步」，
    而 `agent_prompts.py` 的论文包那一段写「"核验证明"分两步，两步都要走」后面紧跟
    「必须派 `E.run_experiment(method='formal')`」—— 两处都把形式化写成了每一趟都要走的流水线。
    """
    _set(True)
    registry = _registry()
    problems: list[str] = []
    hit_user_specified = 0
    for role in LS.visible_roles(_roles()):
        text = _prompt(role, registry)
        for phrase in PIPELINE_PHRASES:
            if phrase in text:
                problems.append(f"{role}: 把形式化写成了流水线一站（出现 {phrase!r}）")
        hit_user_specified += sum(text.count(word) for word in USER_SPECIFIED)
    assert problems == [], (
        "开档下仍有把形式化写成人人必经的句子：\n  " + "\n  ".join(problems))
    assert hit_user_specified >= 5, (
        f"「用户指定 / 成本极高」这一族只出现了 {hit_user_specified} 次 ⇒ 换掉流水线口径之后"
        "没有写清它什么时候才该开（只删不写，读者不知道这条路什么时候用）")


# --------------------------------------------------------------------------- ⑤
def test_never_hiding_turns_the_zero_trace_criterion_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把 `is_hidden` 钉成恒 False（永不隔绝）⇒ ③ 必红。

    这一条守的是 ③ 有没有分辨力：它读的是同一个判定入口（`leanscope.is_hidden`），
    所以钉成找不到之后，L 那一份提示词必须被当成"可见角色"算进来，③ 当场红。
    """
    _set(False)
    registry = _registry()
    live = {role: _prompt(role, registry) for role in LS.visible_roles(_roles())}
    assert all(len(ROLE_NAME.findall(t)) == 0 for t in live.values()), \
        "正控没成立（关着时本来就有 L 的痕迹？）"
    monkeypatch.setattr(LS, "is_hidden", lambda role: False)
    widened = {role: _prompt(role, registry) for role in LS.visible_roles(_roles())}
    assert ROLE_L in widened, "把判定改成恒 False 之后 L 仍不在可见角色里"
    dirty = {role: len(ROLE_NAME.findall(t)) + t.count("formal.")
             for role, t in widened.items()}
    assert dirty[ROLE_L] > 0, (
        "恒 False 之后 L 那份提示词里一个 L 记号都没有 ⇒ ③ 在这种改动下不会红，它是真空的")


# --------------------------------------------------------------------------- ⑥
def test_e_is_not_weakened() -> None:
    """E 没有被顺手削弱：裁定范围之外的动作面与工具面原样，且 `test_lean_switch.py` 仍全绿。

    为什么这一条必须在这里：这一批改的全是文本，而"改文本"最容易顺手把 E 的能力面
    也收掉。2026-10-23 晚的裁定确实收掉了两格（`check_formal` 动作与
    `verify.detect_verifier` 在 E 面上的那一格），所以这一条分成两半：
    裁定内的三件必须真的没了（收掉了才算执行了裁定），裁定外的必须一件不少
    （实验、查询、算哈希、脚本封装都还在）。两半缺一条都会让"清理"变成"顺手削掉"。
    """
    from agentflow import capabilities as C

    actions = {spec.action for spec in C.CAPABILITIES["E"]}
    for want in ("run_experiment", "run_script_experiment",
                 "evidence_for", "list_experiments"):
        assert want in actions, f"E 的动作面少了 {want}（裁定只让删 check_formal）"
    assert "check_formal" not in actions, "裁定要删的 check_formal 还在 E 的动作表里"
    face = {spec.name for spec in _registry().for_role("E")}
    assert "verify.run_experiment" in face, f"E 的工具面少了实验那一路：{sorted(face)}"
    assert "verify.code_hash" in face, f"E 的工具面少了可复现性那一格：{sorted(face)}"
    assert len(face) >= 14, f"E 的工具面只剩 {sorted(face)} ⇒ 这不是清理 Lean 侧，是把能力面收掉了"
    assert "verify.detect_verifier" not in face, "裁定要求把探测从 E 的面上拿掉"
    # 桥接层真身必须仍然装配在某处（它是 `formal.*` 共同的下游）：删的是"E 的工具面那一件"，
    # 不是这份实现。它今天挂在 L 的那三件工具下面（`formal.check_formal`）。
    assert "formal.check_formal" in _registry().names(), (
        "L 的形式化入口不见了 ⇒ 桥接层真身被删了，而不只是收掉了 E 那一面")
    assert "verify.check_formal" not in _registry().names(), (
        "`verify.check_formal` 还在注册表里 ⇒ 裁定要的是整条删掉，不是收成空 roles")

    here = pathlib.Path(__file__).resolve().parent
    proc = subprocess.run([sys.executable, "-m", "pytest", str(here / "test_lean_switch.py"),
                           "-q", "--no-header", "-p", "no:cacheprovider"],
                          cwd=str(here.parent), capture_output=True, text=True,
                          env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8",
                               "PYTHONUTF8": "1"})
    tail = "\n".join((proc.stdout or proc.stderr or "").splitlines()[-12:])
    assert proc.returncode == 0, f"test_lean_switch.py 红了（退出码 {proc.returncode}）：\n{tail}"


@pytest.fixture(autouse=True)
def _keep_the_switch() -> "object":
    """每条用例跑完把开关按原值放回（见 `_restore` 的 docstring）。

    必须逐条还原，不能只在本文件末尾还原：pytest 的 session 级收尾要等整场结束，
    那时同一进程里后面的 `test_agent_prompts.py` 已经看过「Lean 关」那一档了。
    """
    yield
    _restore()
