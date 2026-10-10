# -*- coding: utf-8 -*-
"""预设接线的判据（`draft/103` §4.1b）：组装文件真的改变了"哪段文件给这一段"。

这一层最危险的失败形态不是"预设不生效"，而是它看起来生效了：
`role_preset` 找不到目录时静默回落内置注册，提示词照渲染、工具照跑、
没有任何一条别的判据会红 —— A 的预设接目录名 `A`（大写）时实测就是这条路
（`presetkit` 的 id 字符集是小写 kebab ⇒ 那一行判"目录名不是合法 id"）。
所以这里每一条都要两头钉：生效的那一头要看得见新段，回落的那一头要看得见
"与没有预设时逐字节相同"。

判据名单：
  1. 随包预设真的在盘上、读得动、不是坏预设（十个角色的 id 映射逐格对账）；
  2. 生效：预设给的段真的进了提示词（段名 + 正文）；
  3. 回落：其余九个角色在"有随包预设"与"没有预设"两种装配下逐字节相同；
  4. 坏预设三态：行名不认识 / 文件缺 / `file` 与 `text` 同时给 ⇒ 都不许半组装；
  5. 覆盖：预设声明接管的段，代码那一份必须跳过（不跳过就是同名两次注册 ⇒ 抛）。
"""
from __future__ import annotations

import pathlib
import shutil

import pytest

from agentflow import agent_prompts as AP
from agentflow import composition as CB
from agentflow import presets as PR
from agentflow import schema as S
from agentflow.promptkit import Scope
from agentflow.tools import ToolRegistry, build_registry

ROLES = (*S.ROLES, S.CONDUCTOR_ROLE)

#: 渲染一份提示词用的固定事实（这些用例关心的是"哪段文件给这一段"，不是当次事实）。
FACTS = {"task": "（判据：一件占位任务）", "workspace_root": "D:/x"}


@pytest.fixture()
def registry() -> ToolRegistry:
    return build_registry().registry


def _prompt(role: str, registry: ToolRegistry, **kw: object) -> str:
    kw.setdefault("task", FACTS["task"])
    kw.setdefault("workspace_root", FACTS["workspace_root"])
    return AP.system_prompt(role, registry=registry, **kw)


def _sections(role: str, registry: ToolRegistry, **kw: object) -> dict[str, str]:
    """这一次装配的 段名 → 段正文（空段也在里面，与 `Assembly.names` 同一口径）。

    用段层而不是渲染文本做比对：段是"哪段文件给这一段"这件事的落点，
    而渲染文本还要过一遍丢空段与插值（插值会把当次事实混进来，比对就不干净了）。
    """
    kw.setdefault("task", FACTS["task"])
    kw.setdefault("workspace_root", FACTS["workspace_root"])
    reg = AP.role_prompt_registry(role, registry=registry, **kw)
    assembly = reg.assemble(Scope(role=role))
    return {s.name: s.render(assembly.scope) for s in assembly.sections}


@pytest.fixture()
def empty_root(tmp_path: pathlib.Path) -> pathlib.Path:
    """一个空的预设根：拿它渲染 = "这个角色没有预设"那一档。"""
    root = tmp_path / "no-presets"
    root.mkdir()
    return root


def _fake_preset(tmp_path: pathlib.Path, rows: list[dict[str, object]], *,
                 blocks: dict[str, str] | None = None) -> pathlib.Path:
    """在临时根下造一个预设目录（目录名 `a` = 角色 A 的预设 id），返回那个根。

    目录名必须是 `a`：预设 id 就是目录名，而角色 id → 预设 id 的映射是小写化
    （`composition.preset_id_of`）。造一个叫 `fake` 的目录时 `role_preset("A")` 找不到它，
    于是所有"坏预设"用例都会静默走回落那条路、并因此恒真通过 —— 这个坑在写这一批
    判据时踩过一次（7 条用例一起红，红的原因是"假预设没被发现"）。
    """
    pdir = tmp_path / CB.preset_id_of("A")
    pdir.mkdir(exist_ok=True)
    (pdir / PR.PRESET_MANIFEST_NAME).write_text("name: 判据用\n", encoding="utf-8")
    for name, text in (blocks or {}).items():
        target = pdir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    import yaml

    (pdir / PR.COMPOSITION_NAME).write_text(
        yaml.safe_dump(rows, allow_unicode=True), encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------- 1. 盘上的那一份


def test_the_shipped_root_holds_one_readable_preset_per_shipped_role():
    """随包根下真的有 A 的预设，且它读得动、不是坏预设。

    反真空：这条判据同时要求"根存在"与"至少有一个预设" —— 否则"没有坏预设"会因为
    "一个预设都没有"而假装通过（那正是静默回落的样子）。
    """
    root = CB.shipped_root()
    assert root.is_dir(), f"随包预设根不在盘上：{root}"
    found = PR.discover(shipped_root=root, include_user=False, resolve=CB._resolvable)
    assert found, f"随包根 {root} 下一个预设都没有 ⇒ 整条接线是空的"
    ids = sorted(p.id for p in found)
    assert ids == ["a"], f"随包预设今天只有 A 那一份（`draft/109`）：{ids}"
    a = CB.role_preset("A")
    assert a is not None and not a.broken, f"A 的预设读不成：{a.broken if a else '没找到'}"
    assert a.composition_path.is_file(), a.composition_path


def test_the_role_id_mapping_is_exactly_one_preset_id_per_role():
    """十个角色 → 十个预设 id，逐个合法且互不相同。

    为什么值得一条：预设 id 的字符集是 `presetkit` 定的（`^[a-z0-9][a-z0-9-]*$`），
    而角色 id 是大写单字母。映射写错了不会报错 —— 只会"这个角色的预设找不着"，
    于是它静静地用内置那份（实测过：目录叫 `A` 时 `prompt_audit["preset"]["problem"]`
    写着"目录名不是合法 id"，而提示词本身一切正常）。
    """
    ids = {role: CB.preset_id_of(role) for role in ROLES}
    assert len(set(ids.values())) == len(ROLES), f"映射撞了：{ids}"
    bad = {r: i for r, i in ids.items() if not PR.id_is_valid(i)}
    assert not bad, f"这些角色的预设 id 不是合法 id（预设会判坏）：{bad}"


# ---------------------------------------------------------------- 2. 生效


def test_a_preset_block_lands_in_the_prompt(registry: ToolRegistry):
    """生效的那一头：A 的检索式那一段真的进了提示词（段名 + 正文都要看得见）。

    两个都要钉：只有段名 = 段是空的（渲染时被丢掉），只有正文 = 它不在段表里
    （那就分不清"预设给的"与"代码里本来就有的"）。
    """
    text = _prompt("A", registry)
    block = (CB.shipped_root() / "a" / "blocks" / "search_style.md").read_text(encoding="utf-8")
    assert block.strip(), "预设块是空的 ⇒ 这条判据会退化成恒真"
    assert block.strip() in text, "预设块的正文没进 A 的提示词"
    audit = AP.prompt_audit("A", registry=registry, **FACTS)  # type: ignore[arg-type]
    assert "A_SEARCH_STYLE" in audit["sections"], audit["sections"]
    fact = audit["preset"]
    assert fact["id"] == "a" and fact["problem"] == "", fact


def test_the_preset_reading_names_the_file_it_came_from(registry: ToolRegistry):
    """读数要能指回盘上那一段：`path` 是预设目录，`rows` 是组装文件的行数。

    为什么不是"能跑就行"：这一层出问题时唯一的读数就是这个字典，
    它若只报 `id` 而不报路径，读的人无法判断"跑的是哪一份文件"。
    """
    fact = AP.prompt_audit("A", registry=registry, **FACTS)["preset"]  # type: ignore[arg-type]
    assert pathlib.Path(fact["path"]) == CB.shipped_root() / "a", fact
    assert fact["rows"] == 1, fact


# ---------------------------------------------------------------- 3. 回落逐字节


def test_roles_without_a_preset_are_byte_identical(registry: ToolRegistry,
                                                   empty_root: pathlib.Path):
    """没有预设的角色：给不给预设根，渲染出来的提示词逐字节相同。

    这是接线批最要紧的一条：预设机制不许顺手改别的角色的提示词
    （实测：接线前后九个角色的段数/字数/摘要三样全同）。
    """
    for role in ROLES:
        if role == "A":
            continue
        with_shipped = _prompt(role, registry)
        without = _prompt(role, registry, preset_root=str(empty_root))
        assert with_shipped == without, (
            f"{role} 没有预设，但给了随包根之后提示词变了 —— 预设机制动了不该动的东西")


def test_a_role_with_a_preset_is_exactly_the_fallback_plus_that_block(
        registry: ToolRegistry, empty_root: pathlib.Path):
    """有预设的角色：多出来的东西恰好是那一段（别的段一个字都没动）。

    判据放在注册表的段层，不放在渲染出来的长文本上：文本层的"去掉这一段"要靠
    字符串替换，而段自己的正文里也有空行（`search_style.md` 第 2 行就是）⇒ 替换点会错位
    （写这一条时实测：替换之后差一个空行，于是判据假红）。段层的比对是精确的：
    多出来的段名恰好一个、它的正文与文件逐字节相同、其余每个段名对应的正文完全相同。
    """
    block = (CB.shipped_root() / "a" / "blocks" / "search_style.md").read_text(
        encoding="utf-8").strip("\n")
    with_preset = _sections("A", registry)
    fallback = _sections("A", registry, preset_root=str(empty_root))
    assert with_preset != fallback, "A 的预设没生效 ⇒ 这条判据在空跑"
    added = {name: text for name, text in with_preset.items() if name not in fallback}
    assert set(added) == {"A_SEARCH_STYLE"}, f"多出来的段不止那一个：{sorted(added)}"
    assert added["A_SEARCH_STYLE"] == block, "预设段的正文与文件不一致"
    for name, text in fallback.items():
        assert with_preset[name] == text, f"段 {name} 被预设顺手改了"


# ---------------------------------------------------------------- 4. 坏预设三态


def test_an_unknown_row_name_makes_the_preset_broken_and_falls_back(
        registry: ToolRegistry, tmp_path: pathlib.Path):
    """行名不认识 ⇒ 那一行坏（带名字）⇒ 整个预设坏 ⇒ 回落，且读数里写明。

    三态纪律：不许把"没挂成"折叠成"挂上了但没有段"。
    """
    root = _fake_preset(tmp_path, [{"id": "x", "name": "agentflow.没有这一行",
                                    "config": {"blocks": []}}])
    preset = CB.role_preset("A", root=root)
    assert preset is not None, "假预设没被发现 ⇒ 这条判据打的是空气"
    assert preset.broken, "行名不认识居然没判坏"
    assert "agentflow.没有这一行" in preset.broken, preset.broken
    # 回落：坏预设 ⇒ 与"没有预设"逐字节相同
    assert _prompt("A", registry, preset_root=str(root)) == _prompt(
        "A", registry, preset_root=str(tmp_path / "empty")), \
        "坏预设没有回落（半组装的提示词）"


def test_a_missing_block_file_falls_back_and_says_which_file(
        registry: ToolRegistry, tmp_path: pathlib.Path):
    """`file:` 指的文件不在 ⇒ 组装期抛 ⇒ 回落，读数里带上那个路径。"""
    root = _fake_preset(tmp_path, [{
        "id": "x", "name": CB.TEXT_BLOCKS,
        "config": {"blocks": [{"section": "A_SEARCH_STYLE", "file": "blocks/没有这个文件.md"}]},
    }])
    fact = AP.prompt_audit("A", registry=registry, preset_root=str(root), **FACTS)  # type: ignore[arg-type]
    assert fact["preset"]["problem"], "文件缺了却报成没问题"
    assert "没有这个文件" in fact["preset"]["problem"], fact["preset"]
    assert "A_SEARCH_STYLE" not in fact["sections"], "坏预设留下了半份提示词"


def test_a_block_with_both_file_and_text_is_a_broken_row(tmp_path: pathlib.Path):
    """`file` 与 `text` 同时给 ⇒ 那一行坏（"这一段是谁写的"没有答案）。"""
    root = _fake_preset(tmp_path, [{
        "id": "x", "name": CB.TEXT_BLOCKS,
        "config": {"blocks": [{"section": "S", "file": "blocks/one.md", "text": "两处都给"}]},
    }], blocks={"blocks/one.md": "文件里那一份"})
    preset = CB.role_preset("A", root=root)
    assert preset is not None and not preset.broken, "行本身是好的，坏在组装期"
    with pytest.raises(PR.PresetError):
        CB.apply_preset(AP.PromptRegistry(), preset, role="A")


# ---------------------------------------------------------------- 5. 覆盖与空段


def test_a_preset_can_take_over_a_brief_section(tmp_path: pathlib.Path):
    """`agentflow.brief_blocks` 声明接管 ⇒ 代码那一份跳过（同名两次注册会抛）。

    这条判据的形态：不抛就是跳过了 —— `promptkit` 对同名两次注册是注册期即抛
    （两份文本抢一个段名时"哪一份是真的"必须有答案）。
    """
    root = _fake_preset(tmp_path, [{
        "id": "x", "name": CB.BRIEF_BLOCKS,
        "config": {"sections": ["ROLE_BOUNDARY"]},
    }])
    preset = CB.role_preset("A", root=root)
    assert preset is not None and not preset.broken, preset.broken if preset else "没找到"
    reg = AP.PromptRegistry()
    provided = CB.apply_preset(reg, preset, role="A")
    assert provided == {"ROLE_BOUNDARY"}, provided
    # 真的接管了：再跑一遍完整装配不抛（代码那一份跳过了）
    text = _prompt("A", registry=build_registry().registry, preset_root=str(root))
    assert "边界（这些是硬约束" in text


def test_the_brief_row_does_not_get_a_second_copy_of_the_identity_text(
        tmp_path: pathlib.Path):
    """`brief_blocks` 只声明"这五格由我列出"，正文仍从真身渲染 —— 不许抄第二份。

    判据：接管之后那一段的正文与真身（`ROLE_BRIEFS`）渲染的逐字节相同。
    业主裁定 I-1 逐字：`specs/<role>.py::SPEC.brief` 是唯一真身。
    """
    root = _fake_preset(tmp_path, [{
        "id": "x", "name": CB.BRIEF_BLOCKS, "config": {"sections": ["DELIVERABLE"]},
    }])
    preset = CB.role_preset("A", root=root)
    assert preset is not None
    reg = AP.PromptRegistry()
    CB.apply_preset(reg, preset, role="A")
    mounted = {s.name: s.render(Scope(role="A")) for s in reg.assemble(Scope(role="A")).sections}
    by_truth = {name: text for name, _order, text in AP.brief_sections("A")}
    assert mounted["DELIVERABLE"] == by_truth["DELIVERABLE"], \
        "预设里的身份文本与真身不一致（第二份副本）"


def test_only_enabled_rows_are_mounted(tmp_path: pathlib.Path):
    """`!!js` 门（`conditional`）不挂 —— "没求值"不许读成"生效"。

    写法照 `presets.py` 的真身：门在 `disabled:` 那一格（`if:` 不是它认的键，
    写了等于没写、那一行照挂 —— 这条判据的第一版就这么错过一次）。
    """
    pdir = tmp_path / CB.preset_id_of("A")
    pdir.mkdir()
    (pdir / PR.PRESET_MANIFEST_NAME).write_text("name: 判据用\n", encoding="utf-8")
    (pdir / PR.COMPOSITION_NAME).write_text(
        "- id: gated\n"
        "  name: agentflow.text_blocks\n"
        "  disabled: !!js \"process.platform === 'win32'\"\n"
        "  config:\n"
        "    blocks:\n"
        "      - section: A_SEARCH_STYLE\n"
        "        order: 2000\n"
        "        text: 这一段不该出现\n",
        encoding="utf-8")
    preset = CB.role_preset("A", root=tmp_path)
    assert preset is not None, "假预设没被发现"
    assert [{r.id: r.state} for r in preset.rows] == [{"gated": PR.GATE_CONDITIONAL}], \
        [(r.id, r.state) for r in preset.rows]
    reg = AP.PromptRegistry()
    provided = CB.apply_preset(reg, preset, role="A")
    assert provided == set(), f"conditional 那一行被挂上了：{provided}"


# ---------------------------------------------------------------- 6. 与机制的缝


def test_apply_preset_is_the_only_wiring_point():
    """接线层只落两行解析表，且每一行都能被 `_resolvable` 认出来。

    为什么钉"两行"：其余十行（现算块）写出来就是死表
    （`CONTEXT_ORDERS` / `RESERVED_VALUES` 那两课：没人用的表会腐烂成"看起来还在挡着什么"）。
    这条判据不禁止以后加行 —— 它禁止的是"加了行却没有解析函数"与"表里塞了没人认的名字"。
    """
    assert set(CB.RESOLVERS) == {CB.TEXT_BLOCKS, CB.BRIEF_BLOCKS}, tuple(CB.RESOLVERS)
    for name in CB.RESOLVERS:
        assert CB._resolvable(name) is CB.RESOLVERS[name]
    with pytest.raises(PR.PresetError):
        CB._resolvable("agentflow.没有这一行")


def test_no_preset_is_read_from_outside_the_shipped_root(tmp_path: pathlib.Path):
    """用户目录里的预设今天不生效（`include_user=False`）：部署面决策，不是接线的事。

    这条判据守的是"接线该多宽"：配置根一律要有一条裁定才接
    （`draft/103` §4.5 的不做清单），而在那之前它必须真的读不到 ——
    "以为读了其实没读"与"以为没读其实读了"都会让"跑的是哪一套提示词"没有答案。
    """
    assert CB.role_preset("A", root=tmp_path) is None, \
        "临时根下没有预设，却找到了一个 ⇒ 有人在随包根之外读预设"


def test_the_selftest_passes():
    """`python -m agentflow.composition` 的自检必须是绿的（它是这一层的唯一自带正控）。"""
    assert CB.selftest() == 0


# ---------------------------------------------------------------- 7. 反负控


def test_the_byte_identity_criterion_can_fail(registry: ToolRegistry,
                                              empty_root: pathlib.Path):
    """反负控：把"逐字节相同"这条判据喂一个真的不同的东西，它必须红。

    为什么值得：上面那条判据的实现是一句 `==`，而 `==` 两侧若都是空串、
    或两侧都渲染失败拿到了同一个异常串，它会恒真。这里用 A（有预设）去撞
    "九个角色逐字节相同"那条判据的形状 ⇒ 必须不等。
    """
    assert _prompt("A", registry) != _prompt("A", registry, preset_root=str(empty_root))


def test_the_block_landing_criterion_can_fail(registry: ToolRegistry):
    """反负控：换一个不存在的段名，段表里就不该有它（判据不是恒真）。"""
    audit = AP.prompt_audit("A", registry=registry, **FACTS)  # type: ignore[arg-type]
    assert "A_SEARCH_STYLE" in audit["sections"]
    assert "A_SEARCH_STYLE_没有这一段" not in audit["sections"]


def test_cleanup_guard_for_tmp_roots(tmp_path: pathlib.Path):
    """`_fake_preset` 造的目录必须能被彻底删掉（免得临时根污染下一次发现）。

    这条看着像废话，但它守着一个真踩过的坑：`PR.discover` 的根优先级是"目录名即 id"，
    临时根里若留下上一个用例的残留目录，下一个用例会在另一个根上发现它
    （发现集是并集），于是失败的用例会指向一处它从没碰过的路径。
    """
    root = _fake_preset(tmp_path, [{"id": "x", "name": CB.TEXT_BLOCKS, "config": {"blocks": []}}])
    assert (root / CB.preset_id_of("A")).is_dir()
    shutil.rmtree(root)
    assert not root.exists()
