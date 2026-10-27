# -*- coding: utf-8 -*-
"""业主 2026-10-22 的施工单：Lean 开关没开时，角色 L 完全隔绝。

原话逐字：「在Lean开关没开时隔绝L，也是保证待会那次跑的测试不受干扰」。

## 这一份判的是什么

开关关着时，L 不许出现在任何面向模型/用户的地方 —— 不是"它跑不动"，而是
"它不存在"：

| 面 | 关着时的读数 |
|---|---|
| 角色注册面 | `registry.roles()` / `TOOL_ROLES` 里没有 L；按名取 L 的入口给受控拒绝，理由 `lean_off` |
| 工具面 | `formal.*` 两件不装配（谁的工具面里都没有） |
| 提示词 | 任一角色（A–H / M / V）的渲染提示词里没有 L 这个角色名；L 自己那份不生成 |
| 名册/召唤 | 没有以 L 为端点的边、它不在可召唤名单里（既有机制），主控的伙伴表里也不出现它 |
| 读数 | 画像文件与接线态读数里没有"L 存在但没用到"这一格 |

开关开着时四项全部反过来（L 在角色表、`role_spec` 可读、`formal.*` 在 L 的工具面、
L 的提示词在）—— 负控的方向一律是"开着时与改前逐字相同"。

## 为什么每一条都要有一条反真空

"L 不在角色表里"在一个空表上恒真，"L 的提示词里没有形式化字样"在一份空提示词上
恒真。所以每条断言都先证"这个读数在这个档位上本来应该是什么"，并单独有一个用例把
唯一那个判定入口（`leanscope.is_hidden`）改成恒 False / 恒 True，证上面的判据会红
（改变前红的那把尺子本身也要有尺子）。

## 零模型

全部用例只读代码与本地开关：不起子进程、不调模型、不写工作区（`tmp_path` 只在
需要工作区的那一格用）。
"""
from __future__ import annotations

import re

import pytest

from agentflow import agent_prompts as AP
from agentflow import agentspec as AS
from agentflow import schema as S
from agentflow import settings as SET
from agentflow.tools import TOOL_ROLES, build_registry
from agentflow.tools import conductor_tools as CT

#: L 这个角色名。
ROLE_L = "L"

#: L 的两件工具（开关开着时它们在 L 的工具面上，关着时一件都不许装配）。
FORMAL_TOOLS = ("formal.formalize", "formal.check_formal")

#: 面向模型/用户的"其余角色"：由 `schema.ROLES` 现算（A–H、V，再加主控 M），
#: L 不在这一串里 —— 它只有在开关开着时才是一个角色。
#:
#: 2026-10-22 晚（L 协作面接线）：这一格此前是手写的 `("A", …, "V")`，于是"新加一个
#: 角色"不会自动进这条判据。改成现算之后，任何未来的角色都自动被"关着时提示词里
#: 0 处 L"守住 —— C 这一档正是因为 `L → C` 接上而第一次需要它（`partners_in`
#: 当时漏了可见性过滤，就是这条判据抓到的）。
OTHER_ROLES = tuple(role for role in (*S.ROLES, S.CONDUCTOR_ROLE) if role != ROLE_L)

#: "L 这个角色名"的判据：一个独立的 `L` 记号。
#:
#: 为什么不用 `\bL\b`：Python 的 `re` 在 str 上把中日韩字符算作 `\w`，
#: 于是 `角色 L` 里那个 `L` 与它左边的汉字之间没有词边界，`\bL\b` 一条都匹配不到
#: （实测：改前 L 的提示词里那两处全被漏掉）。这里的边界是"ASCII 词字符"，
#: 所以 `Lean` / `Mathlib` 里的 L 不算（它后面还跟着字母），`L 的` / `（L）` 算。
ROLE_NAME = re.compile(r"(?<![A-Za-z0-9_])L(?![A-Za-z0-9_])")


#: 「伙伴表里那一行」的判据：`L：` 的左边不许再贴着字母。
#:
#: 为什么不能写成 `"L：" in text`：公共频道那条说明逐字写着 ``to 也可以写 ALL：…``
#: （`ALL` 那套写法合并之后才有的句子），而 `"ALL："` 里就含一个 `"L："`
#: —— 子串匹配于是把「广播关键字后面跟一个全角冒号」判成「主控的伙伴表里还留着 L」。
#: 实测（`agentflow/temp/_g3_probe_lean_l.py`，Lean 关那一档）：M 的提示词 64209 字里
#: `ROLE_NAME` 的命中数是 0，`"L："` 却是 True，`"ALL："` 在盘上。
#: 这个边界把 `ALL：` 排除、把真的伙伴表行（`- L：…` / `L：…`）留全 —— 判据没有放松。
ROW_L = re.compile(r"(?<![A-Za-z0-9_])L：")


def _reload_switch() -> None:
    """配置重载：清掉 `agent_prompts` 那个 `lru_cache` 的开关读数。

    为什么必须调用它：`leanscope.reading()` 每次都现读（没有缓存，见那个模块的
    docstring），而提示词那一层为了"同一趟里前缀稳定"把开关读数记在
    `agent_prompts._lean_switch` 的 `lru_cache` 里 —— 那个缓存由
    `reset_toolchain_readings()` 清（它就是这个模块文档化的配置重载口）。
    不调用它，改环境变量的那一刻提示词会停在旧值：那不是"隔绝没生效"，
    而是"提示词是别的档位渲的"，两件事必须分得开。
    """
    AP.reset_toolchain_readings()


def _ls():
    """唯一判定入口（延迟 import：这个模块是本次改动新加的）。"""
    from agentflow import leanscope

    return leanscope


# --------------------------------------------------------------------------- 读数


def _tool_faces(build: object = None) -> dict[str, set[str]]:
    """每个角色的工具面（`for_role` 是工具面的唯一读法）。"""
    build = build_registry() if build is None else build
    return {role: {spec.name for spec in build.registry.for_role(role)}
            for role in (*OTHER_ROLES, ROLE_L)}


def _role_spec_l():
    """按名取 L 的那个入口（`conductor.role_spec` 是模型唯一能按名查角色的工具）。"""
    return CT.conductor_role_spec(None, ROLE_L)


def _prompt(role: str, registry: object = None) -> str:
    """既有渲染入口：`system_prompt`（生产路径与审计都走它）。

    `registry` 必须给（`system_prompt` 自己会拒一个空的）：提示词要描述的那份
    工具面必须与真正执行调用的那一份是同一个。不给时这里现装一份，于是"现读现算"
    这件事不会因为某个缓存而停在别的档位。
    """
    if registry is None:
        registry = build_registry().registry
    return AP.system_prompt(role, registry=registry)


def _l_prompt_problem(registry: object = None) -> str:
    """L 自己那份提示词在关着时是不是被拒了；返回空串 = 被拒得对。

    合法的拒绝只有 `leanscope.RoleHidden`，而且理由串里必须带上这一档的理由码
    （关着是 `lean_off`，读不出是 `lean_unreadable`）—— 拒绝那一刻不点名理由，
    读者就分不清"用户关了它"与"配置写坏了"。
    抛别的异常与"照旧渲染出来"都不是隔绝：前者是崩溃，后者是没隔绝。
    """
    want = _ls().lean_reading().reason
    try:
        text = _prompt(ROLE_L, registry)
    except _ls().RoleHidden as e:
        if want not in str(e):
            return f"L 的提示词被拒了，但理由里没有 {want}：{e}"
        return ""
    except Exception as e:  # noqa: BLE001
        return f"L 的提示词抛的不是受控拒绝（{type(e).__name__}: {e}）"
    return f"L 的提示词还能渲染出来（{len(text)} 字）"


def _isolation_violations() -> list[str]:
    """关着时"完全隔绝"的判据。返回违反项（空 = 隔绝成立）。"""
    bad: list[str] = []
    reg = AS.builtin_registry()

    # ---- 1. 角色注册面
    if ROLE_L in reg.roles():
        bad.append(f"registry.roles() 里还有 L：{reg.roles()}")
    if ROLE_L in reg.summonable_roles():
        bad.append(f"L 出现在可召唤名单里：{reg.summonable_roles()}")
    if ROLE_L in _ls().visible_roles(TOOL_ROLES):
        bad.append(f"TOOL_ROLES 的读数里还有 L：{_ls().visible_roles(TOOL_ROLES)}")

    # ---- 2. 按名取 L：受控拒绝 + 理由
    res = _role_spec_l()
    if res.ok is not False:
        bad.append(f"role_spec('L') 没有被拒（ok={res.ok}，data={res.data}）")
    elif str((res.meta or {}).get("reason") or "") != "lean_off":
        bad.append(f"role_spec('L') 被拒了，但理由是 {(res.meta or {}).get('reason')!r}")

    # ---- 3. 工具面：formal.* 一件都不装配
    build = build_registry()
    faces = _tool_faces(build)
    assembled = set(build.registry.names())
    leaked = sorted(assembled & set(FORMAL_TOOLS))
    if leaked:
        bad.append(f"形式化工具仍然装配了：{leaked}")
    if "formal_tools" in build.loaded:
        bad.append(f"工具模块清单里还有 formal_tools：{build.loaded}")
    if any(str(x).startswith("formal.") for x in build.summary().get("tools") or []):
        bad.append("RegistryBuild.summary() 的工具清单里还有 formal.*")
    for role, face in faces.items():
        hit = sorted(face & set(FORMAL_TOOLS))
        if hit:
            bad.append(f"{role} 的工具面里还有 {hit}")
    if faces[ROLE_L]:
        bad.append(f"L 的工具面不是空的：{sorted(faces[ROLE_L])}")

    # ---- 4. 提示词：其余角色一个字都不许提 L
    for role in OTHER_ROLES:
        hits = ROLE_NAME.findall(_prompt(role, build.registry))
        if hits:
            bad.append(f"{role} 的提示词里出现了 {len(hits)} 处 L 这个角色名")
    problem = _l_prompt_problem(build.registry)
    if problem:
        bad.append(problem)

    # ---- 5. 名册/召唤：L 没有活的入边，伙伴表里也不出现它
    #
    # 2026-10-22 第三班改口径：边表是声明（`specs/f.py` 的 `edges` 里有 'L'，
    # 那是"开关开着时谁可以派它"），而开关关着时 L 不是这一档的角色 ——
    # 于是同一条边必须当场不通。判据因此从"静态表里没有 L"（那会让
    # `specs/f.py` 的声明随开关变动，而声明是静态的）换成"每一条静态边都被拒"：
    # `policy.check` 对它们一律 `forbidden_edge`，理由串点名 `lean_off`。
    # 这一条比原来那条强：原来只断言"没人写了这条边"，现在断言"写了也不通"。
    from agentflow import policy as _POL

    pol = _POL.Policy()
    for frm in sorted(role for role, targets in _edges().items() if ROLE_L in targets):
        got = _POL.check(pol, _POL.Decision(frm=frm, to=ROLE_L, action="", depth=2))
        if got is None:
            bad.append(f"{frm} → L 在开关关着时仍然通（边表声明了、闸门没拦）")
        elif got.reason != "forbidden_edge":
            bad.append(f"{frm} → L 被拒了，但理由是 {got.reason!r}（不是 forbidden_edge）")
        elif "lean" not in got.detail:
            bad.append(f"{frm} → L 的拒绝理由里没点名 Lean 开关：{got.detail!r}")
    m_text = _prompt("M", build.registry)
    if ROW_L.search(m_text) or ROLE_NAME.search(m_text):
        bad.append("主控的伙伴表里还留着 L 这一行")

    # ---- 6. 读数：画像文件与接线态
    if ROLE_NAME.search(AP.profiles_markdown(registry=build.registry)):
        bad.append("画像文件（AGENT-PROFILES.md 的内容）里还有 L")

    from agentflow.host import _Builder

    wiring = sorted(_Builder().status())
    if ROLE_L in wiring:
        bad.append(f"接线态读数里还有 L：{wiring}")
    return bad


def _edges():
    """边表（`capabilities.ALLOWED_EDGES` 是权威定义）。"""
    from agentflow import capabilities as C

    return C.ALLOWED_EDGES


def _visibility_violations() -> list[str]:
    """开着时"与改前逐字相同"的判据。返回违反项（空 = 一致）。"""
    bad: list[str] = []
    reg = AS.builtin_registry()
    build = build_registry()
    if ROLE_L not in reg.roles():
        bad.append(f"开着时 L 不在角色表里：{reg.roles()}")
    if ROLE_L not in _ls().visible_roles(TOOL_ROLES):
        bad.append(f"开着时 TOOL_ROLES 的读数里没有 L：{_ls().visible_roles(TOOL_ROLES)}")

    res = _role_spec_l()
    if res.ok is not True:
        bad.append(f"开着时 role_spec('L') 读不出来（ok={res.ok}，error={res.error}）")
    elif str((res.data or {}).get("duty") or "") == "":
        bad.append(f"开着时 role_spec('L') 没有职责那一格：{res.data}")

    face = _tool_faces(build)[ROLE_L]
    missing = sorted(set(FORMAL_TOOLS) - face)
    if missing:
        bad.append(f"开着时 L 的工具面里没有 {missing}（拿到的是 {sorted(face)}）")

    try:
        text = _prompt(ROLE_L, build.registry)
    except Exception as e:  # noqa: BLE001
        bad.append(f"开着时 L 的提示词渲不出来（{type(e).__name__}: {e}）")
    else:
        if not text.strip():
            bad.append("开着时 L 的提示词是空的")

    # 主控的渲染在开着时必须有 L 的读数（这条是"隔绝"的负控：不许把开着也一起灭了）。
    # 2026-10-24 起那一处读数不再是伙伴表里的一行（L 与主控没有边），而是五元位第 4 位的
    # owner 读数（`formal`：L 签）—— 判"开档没被灭"这件事本身不变。
    if not ROLE_NAME.search(_prompt("M", build.registry)):
        bad.append("开着时主控的读数里没有 L 了（这个角色在模型眼里消失了）")
    return bad


# --------------------------------------------------------------------------- 判据 1
def test_off_the_role_is_not_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关关：`registry.roles()` 里没有 L，可召唤名单里也没有，`TOOL_ROLES` 读数里没有。

    改前红：三处都还列着 L（实测改前 `registry.roles()` 是 A–H、V、L、M）。

    为什么第三处写的是"按可见性读出来的 TOOL_ROLES"而不是"TOOL_ROLES 本身"：
    那张表是 `ToolSpec.roles` 的「声明词表」（`P-1` 的拼写闸门），它刻意保持完整 ——
    把 L 从声明词表里删掉会让 `roles=tuple(S.ROLES)` 这种"全体角色"的写法变成拼写
    错误，于是 `table_tools` / `conductor_tools` / `manuscript_tools` 整模块装不上
    （实测，与业主的要求毫无关系）。所以"看不见 L"落在两个地方：读它的人全部过
    `leanscope.visible_roles`（`cli tools` 的逐角色计数、skills 的工具面普查），
    以及 `for_role` 对不存在的角色返回空面（下面那条断言）。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    _reload_switch()
    reg = AS.builtin_registry()
    assert ROLE_L not in reg.roles(), f"registry.roles() 里还有 L：{reg.roles()}"
    assert ROLE_L not in _ls().visible_roles(TOOL_ROLES), (
        f"TOOL_ROLES 的读数里还有 L：{_ls().visible_roles(TOOL_ROLES)}")
    assert ROLE_L not in reg.summonable_roles(), reg.summonable_roles()
    assert build_registry().registry.for_role(ROLE_L) == [], "L 的工具面不是空的"
    # 反真空：其余角色一个都没少（隔绝只针对 L，不是"把角色表清空"）
    assert set(OTHER_ROLES) - {"M"} <= set(reg.roles()), reg.roles()


def test_off_role_spec_refuses_l_with_lean_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关关：按名取 L 的入口给受控拒绝，理由 `lean_off`。

    改前红：`ok=True` 且连 brief 的六格一起给出去（实测改前 `duty` 是 L 的职责句）。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    _reload_switch()
    res = _role_spec_l()
    assert res.ok is False, f"role_spec('L') 没有被拒：ok={res.ok}，data={res.data}"
    assert str((res.meta or {}).get("reason")) == "lean_off", res.meta
    assert "L" in str(res.error), f"受控拒绝的理由串里没有点名 L：{res.error!r}"
    # 反真空：其余角色照旧读得出来（拒绝只针对 L）
    other = CT.conductor_role_spec(None, "E")
    assert other.ok is True and str((other.data or {}).get("duty") or ""), other


def test_off_no_formal_tool_is_assembled(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关关：`formal.*` 两件不装配，谁的工具面里都没有，模块清单里也不出现。

    改前红：改前 `build.registry.names()` 里有这两件，L 的工具面 14 件里有它们。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    _reload_switch()
    build = build_registry()
    names = set(build.registry.names())
    assert not (names & set(FORMAL_TOOLS)), f"还装着：{sorted(names & set(FORMAL_TOOLS))}"
    assert "formal_tools" not in build.loaded, build.loaded
    summary_tools = [str(x) for x in (build.summary().get("tools") or [])]
    assert not [x for x in summary_tools if x.startswith("formal.")], summary_tools
    for role, face in _tool_faces().items():
        assert not (face & set(FORMAL_TOOLS)), f"{role} 的工具面里还有 formal.*：{sorted(face & set(FORMAL_TOOLS))}"
    # 反真空：别的工具照旧装着（不是"整个工具层都空了"）
    assert len(names) >= 40, f"工具面只剩 {len(names)} 件 ⇒ 这不是「关掉 L」，是把工具层关了"


def test_off_no_role_prompt_mentions_l(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关关：任一角色（A–H / M / V）的渲染提示词里没有 L 这个角色名。

    改前红：改前主控的伙伴表里有 `L：…` 一行（实测关着时全树 3 处，其中主控 1 处）。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    _reload_switch()
    registry = build_registry().registry
    counts = {role: len(ROLE_NAME.findall(_prompt(role, registry))) for role in OTHER_ROLES}
    assert all(n == 0 for n in counts.values()), (
        f"关着时仍有角色在提示词里提到 L：{ {k: v for k, v in counts.items() if v} }")
    # 反真空：提示词本身不是空的（十个角色的提示词加起来必须远大于 0 字）
    assert sum(len(_prompt(r, registry)) for r in OTHER_ROLES) > 20000, \
        "提示词被清空了 ⇒ 上一条是真空的"


def test_off_l_has_no_prompt_of_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关关：L 自己那份提示词不生成（受控拒绝，理由 `lean_off`）。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    _reload_switch()
    problem = _l_prompt_problem()
    assert problem == "", problem


def test_off_the_readouts_do_not_list_l(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关关：画像文件与接线态读数里没有 L（不是"它存在但没用到"）。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    _reload_switch()
    profiles = AP.profiles_markdown(registry=build_registry().registry)
    assert not ROLE_NAME.search(profiles), "画像文件里还有 L"
    assert not ROW_L.search(profiles), "画像文件里还有 `L：` 这一行"
    from agentflow.host import _Builder

    wiring = sorted(_Builder().status())
    assert ROLE_L not in wiring, f"接线态读数里还有 L：{wiring}"
    # 反真空：画像文件里其余角色照旧（不是整份文件被清空）
    for role in ("E", "V"):
        assert f"{role}：" in profiles, f"画像文件里没有 {role} 了"


def test_off_the_whole_isolation_holds(monkeypatch: pytest.MonkeyPatch) -> None:
    """关着时上面六条合起来（判据 1 的整体形态，供反真空那两条复用）。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    _reload_switch()
    bad = _isolation_violations()
    assert bad == [], "关着时仍然没有完全隔绝：\n  - " + "\n  - ".join(bad)


# --------------------------------------------------------------------------- 判据 2
def test_on_the_l_surface_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关开：L 与改前逐字一致（角色表 / role_spec / 工具面 / 自己的提示词）。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    _reload_switch()
    reg = AS.builtin_registry()
    assert ROLE_L in reg.roles(), reg.roles()
    assert ROLE_L in TOOL_ROLES, TOOL_ROLES
    res = _role_spec_l()
    assert res.ok is True, f"开着时 role_spec('L') 被拒了：{res.error}"
    assert str((res.data or {}).get("duty") or "").startswith("Lean 形式化"), res.data
    face = _tool_faces()[ROLE_L]
    assert set(FORMAL_TOOLS) <= face, sorted(face)
    text = _prompt(ROLE_L)
    assert text.strip(), "开着时 L 的提示词是空的"
    assert "你这一岗怎么写形式化" in text or "Lean" in text, (
        "开着时 L 的提示词里一句形式化都没有（那不是改前的样子）")
    bad = _visibility_violations()
    assert bad == [], "开着时 L 的可见面被削弱了：\n  - " + "\n  - ".join(bad)


def test_on_no_isolation_leaks_into_the_other_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关开：L 仍然在别的角色的渲染里（读数的负控：不许把开着那一档也灭了）。

    2026-10-24 口径（业主：是否形式化由用户指定 ⇒ M 派 B ⇒ B 派 L）：主控的伙伴表里
    不再给 L 留一行（L 与主控没有边，那条间接路要用户先给许可），所以这一条的
    正控换成两处今天仍然承重的读数：
      ① 主控的提示词里仍然读得到 L（五元位第 4 位的 owner 读数：「`formal`：L 签」）——
         这一格证明"开着那一档还在"，不证明"主控能找 L"；
      ② B 的伙伴表里仍然有 L 那一行（`B → L` 是唯一入边）。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    _reload_switch()
    m_text = _prompt("M")
    assert ROLE_NAME.search(m_text), "开着时主控的提示词里一处 L 都没有了（开档被灭了）"
    assert "`formal`：**L** 签" in m_text, (
        "开着时主控读不到五元位第 4 位的 owner 读数了")
    assert not ROW_L.search(m_text), "主控的伙伴表里又给 L 留了一行（L 与主控没有边）"
    b_text = _prompt("B")
    assert f"- {ROLE_L}：" in b_text, "开着时 B 的伙伴表里没有 L 那一行（唯一入边消失了）"


# --------------------------------------------------------------------------- 判据 3
def _face_snapshot() -> dict[str, object]:
    """四类读数的快照（同一进程内切换判定用它逐档对比）。"""
    build = build_registry()
    reg = AS.builtin_registry()
    res = _role_spec_l()
    problem = _l_prompt_problem(build.registry)
    return {
        "in_registry": ROLE_L in reg.roles(),
        "in_tool_roles": ROLE_L in _ls().visible_roles(TOOL_ROLES),
        "role_spec_ok": bool(res.ok),
        "role_spec_reason": (res.meta or {}).get("reason"),
        "formal_in_l_face": sorted(_tool_faces(build)[ROLE_L] & set(FORMAL_TOOLS)),
        "l_prompt_chars": (0 if problem == "" else len(_prompt(ROLE_L, build.registry))),
        "m_mentions_l": bool(ROLE_NAME.search(_prompt("M", build.registry))),
    }


def test_the_same_process_follows_the_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """同一进程内改 env：关 / 开 / 再关，读数必须跟着走（不许停在缓存里的旧值）。

    三档各判一次，并逐档给出实跑读数（下面那句总结就是它）。

    改前红：改前没有这个判定入口（`leanscope` 不存在），而三处注册面本身在任何
    档位下都不变 —— 于是"关着"那一档与"开着"那一档完全相同。
    """
    from agentflow import leanscope as LS

    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    _reload_switch()
    off_first = _face_snapshot()

    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    # 判定入口本身不许缓存：一次 reload 都不调，它也必须立刻说"开"
    assert LS.lean_on() is True, "改 env 之后判定入口还停在旧值（缓存了）"
    _reload_switch()
    on = _face_snapshot()

    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    assert LS.lean_on() is False, "改 env 之后判定入口还停在旧值（缓存了）"
    _reload_switch()
    off_again = _face_snapshot()

    print("\n[同进程切换] 关着 =", off_first)
    print("[同进程切换] 开着 =", on)
    print("[同进程切换] 再关 =", off_again)

    assert off_first == off_again, "关 → 开 → 关 之后读数没有回到第一次那一档（缓存停在中间态）"
    assert on != off_first, "换到开着那一档之后读数一个都没变（判定没接上）"
    # 逐项：关着那两档是"不存在"，开着那一档是"存在"
    assert off_first["in_registry"] is False and on["in_registry"] is True
    assert off_first["in_tool_roles"] is False and on["in_tool_roles"] is True
    assert off_first["role_spec_ok"] is False and on["role_spec_ok"] is True
    assert off_first["role_spec_reason"] == "lean_off" and on["role_spec_reason"] is None
    assert off_first["formal_in_l_face"] == [] and on["formal_in_l_face"] == sorted(FORMAL_TOOLS)
    assert off_first["l_prompt_chars"] == 0 and on["l_prompt_chars"] > 0
    assert off_first["m_mentions_l"] is False and on["m_mentions_l"] is True


def test_an_unreadable_value_is_treated_as_off_and_says_so(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """第三档：开关读不出（`"maybe"` 这类写法）⇒ 按"关"处理，并在读数里说明。

    为什么要这一档：把"我没设"与"我设了一个读不懂的值"折成同一档，读者就分不出
    "Lean 关着"与"配置写坏了" —— 而后者要改的是配置文件。
    """
    from agentflow import leanscope as LS

    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "maybe")
    rd = LS.lean_reading()
    assert rd.verdict == "unknown", rd
    assert rd.enabled is False, rd
    assert rd.reason == "lean_unreadable", rd
    assert rd.detail, "读不出时读数里没有说明"
    assert "maybe" in rd.detail or "读不懂" in rd.detail, rd.detail
    # 按"关"处理：L 一样被隔绝，且拒绝理由如实说"读不出"
    _reload_switch()
    assert ROLE_L not in AS.builtin_registry().roles()
    assert ROLE_L not in LS.visible_roles(TOOL_ROLES)
    res = _role_spec_l()
    assert res.ok is False and str((res.meta or {}).get("reason")) == "lean_unreadable", res.meta
    bad = [b for b in _isolation_violations() if "role_spec('L') 被拒了，但理由是" not in b]
    assert bad == [], "读不出那一档没有按「关」隔绝：\n  - " + "\n  - ".join(bad)

# --------------------------------------------------------------------------- 判据 4
def test_never_isolating_turns_criterion_one_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把隔绝判定改成恒 False（永不隔绝）⇒ 判据 1 必红。

    这一条守的是判据 1 本身有没有分辨力：它读的是同一个判定入口
    （`leanscope.is_hidden`），所以把它钉成 False 之后，上面那些断言必须全部说出来。
    """
    from agentflow import leanscope as LS

    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    _reload_switch()
    assert _isolation_violations() == [], "正控没成立（关着时本来就没隔绝？）"
    monkeypatch.setattr(LS, "is_hidden", lambda role: False)
    bad = _isolation_violations()
    assert bad, (
        "把隔绝判定改成恒 False 之后判据 1 仍然全绿 ⇒ 判据 1 是真空的"
        "（它没有读那个判定入口）")
    print("\n[反真空] 恒 False 时报出来的违反项共", len(bad), "条：", bad[:6])


def test_always_isolating_turns_criterion_two_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把隔绝判定改成恒 True（永远隔绝）⇒ 判据 2 必红。"""
    from agentflow import leanscope as LS

    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1")
    _reload_switch()
    assert _visibility_violations() == [], "正控没成立（开着时本来就不一致？）"
    monkeypatch.setattr(LS, "is_hidden", lambda role: role in LS.LEAN_ONLY_ROLES)
    bad = _visibility_violations()
    assert bad, (
        "把隔绝判定改成恒 True 之后判据 2 仍然全绿 ⇒ 判据 2 是真空的")
    print("\n[反真空] 恒 True 时报出来的违反项共", len(bad), "条：", bad[:6])
