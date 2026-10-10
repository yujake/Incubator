# -*- coding: utf-8 -*-
"""`agentflow.presets`：发现优先级、坏预设不跳过、挂一次、生成换代、复制式创作。

## 为什么这些用例必须存在

`draft/101` §2 记下了 DSH 那七条机制，其中四条是"错了也不会有任何读数报出来"的类型：

1. 根优先级（随包根前置并赢同 id）——顺序反了只表现为"某个预设的行为悄悄变了";
2. 坏预设列出来带理由——跳过它只会表现成"这个预设不见了"，而它仍占着那个 id；
3. 一个预设挂一次 + 戳换了才换代——每会话重挂不会报错，只会让"这次跑的是哪一套"
   变得没法回答，并且把前缀稳定（复用）的前提拆掉；
4. 创作面只有复制——覆盖已有的那个目录不会报错，只会安静地毁掉别人的预设。

每条用例的 docstring 都写"退化会坏成什么"，而不是"这段代码能跑"。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import presets as P


def _make_preset(base: pathlib.Path, preset_id: str, *, name: str = "",
                 rows: object = None, raw: str | None = None,
                 description: str = "来源的描述") -> pathlib.Path:
    """在 `base/<id>/` 落一个预设（写 `preset.json` + 组装文件）。"""
    path = base / preset_id
    path.mkdir(parents=True, exist_ok=True)
    (path / P.PRESET_MANIFEST_NAME).write_text(
        json.dumps({"name": name or preset_id, "description": description, "order": 7},
                   ensure_ascii=False), encoding="utf-8")
    body = raw if raw is not None else json.dumps(
        rows if rows is not None else [{"id": "r1", "name": "mod.a"}])
    (path / P.COMPOSITION_NAME).write_text(body, encoding="utf-8")
    return path


def test_roots_are_scanned_shipped_first_then_configured_then_user(tmp_path):
    """根的顺序 = 优先级：随包 → 配置的 → 用户的（前一个赢同名 id）。

    退化会坏成什么：随包根若不在最前，一个用户目录里的同 id 预设会安静地换掉内置那份
    的全部行为，而列表面上看不出哪一份在跑；用户根若不在最后，它连"覆盖自己上一次的复制"
    都做不到（复制落在用户根，下一次扫却先扫到别处）。
    """
    shipped = tmp_path / "shipped"
    configured = tmp_path / "configured"
    home = tmp_path / "home"
    for base in (shipped, configured):
        base.mkdir()
    _make_preset(shipped, "standard", name="内置")
    _make_preset(configured, "standard", name="配置的")
    _make_preset(configured, "extra", name="额外的")
    _make_preset(home / P.USER_ROOT_SUBDIR, "mine", name="我的")

    roots = P.scan_roots(roots=[P.PresetRoot(configured)], shipped_root=shipped, home=home)
    assert [r.trust for r in roots] == [P.TRUST_SYSTEM, P.TRUST_CONFIGURED, P.TRUST_USER]

    got = {p.id: p for p in P.discover(roots=[P.PresetRoot(configured)],
                                       shipped_root=shipped, home=home)}
    assert set(got) == {"standard", "extra", "mine"}, sorted(got)
    assert got["standard"].display == "内置", "同 id 时不是随包根赢"
    assert got["standard"].trust == P.TRUST_SYSTEM


def test_broken_presets_stay_in_the_list_with_a_reason_naming_the_fault(tmp_path):
    """读不成的预设仍然列出来、带理由（缺组装文件 / 不是具名行列表 / 解析不了 / 非法 id）。

    退化会坏成什么：跳过坏目录，用户在列表上看到的是"这个预设没了"，而它的 id 仍被占着 ——
    于是正确的动作（去修它、或者去删它）在界面上没有入口。DSH 逐字：
    "a skipped directory would still occupy its id while no surface shows anything to delete"。
    """
    configured = tmp_path / "cfg"
    configured.mkdir()
    _make_preset(configured, "ok")
    (configured / "no-composition").mkdir()
    (configured / "no-composition" / P.PRESET_MANIFEST_NAME).write_text("{}", encoding="utf-8")
    _make_preset(configured, "unparsable", raw="{ 不是 JSON")
    _make_preset(configured, "not-a-list", rows={"id": "r1", "name": "mod.a"})
    _make_preset(configured, "nameless-row", rows=[{"id": "r1"}])
    _make_preset(configured, "dup-row", rows=[{"id": "r1", "name": "a"},
                                              {"id": "r1", "name": "b"}])
    (configured / "Bad_Id").mkdir()

    got = {p.id: p for p in P.discover(roots=[P.PresetRoot(configured)],
                                       include_user=False)}
    assert got["ok"].broken == "" and not got["ok"].rows[0].disabled
    assert "缺组装文件" in got["no-composition"].broken
    assert "读不了" in got["unparsable"].broken
    assert "具名行的列表" in got["not-a-list"].broken
    assert "缺 id 或 name" in got["nameless-row"].broken
    assert "id 重复" in got["dup-row"].broken
    assert "不是合法 id" in got["Bad_Id"].broken
    assert all(p.id in got for p in got.values())


def test_a_row_naming_an_unresolvable_module_makes_the_preset_broken(tmp_path):
    """给了 `resolve` 时，组装行里解析不了的名字 ⇒ 整个预设坏（带行号与名字）。

    退化会坏成什么：不检查的话，坏行会在挂载到一半时炸 —— 而 DSH 的口径是"绝不允许
    半组装"（"a session never starts half-composed"），所以要在挂载之前就判。
    `disabled` 的行不解析：它这次不挂，要求它可解析等于把"先关掉一行"这个动作堵死。
    """
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    _make_preset(cfg, "good", rows=[{"id": "r1", "name": "known.mod"}])
    _make_preset(cfg, "bad", rows=[{"id": "r1", "name": "known.mod"},
                                   {"id": "r2", "name": "missing.mod"}])
    _make_preset(cfg, "off", rows=[{"id": "r1", "name": "missing.mod", "disabled": True}])

    def resolve(name: str) -> str:
        if name != "known.mod":
            raise KeyError(name)
        return name

    got = {p.id: p for p in P.discover(roots=[P.PresetRoot(cfg)], include_user=False,
                                       resolve=resolve)}
    assert got["good"].broken == ""
    assert "missing.mod" in got["bad"].broken and "解析不了" in got["bad"].broken
    assert got["off"].broken == "", "被 disabled 的行不该参与解析检查"


def test_a_preset_is_composed_once_per_stamp_and_a_new_stamp_starts_a_generation(tmp_path):
    """戳不变 ⇒ 不重挂（同一份返回值）；组装文件变了 ⇒ 新的一代。

    退化会坏成什么：每会话重挂会把"前缀稳定"这件事拆掉 —— 前缀一变，复用失效，
    而"这次跑的是哪一套组装"变成每会话都可能不同、事后无法回答（DSH 的生成戳就是为了
    这一点：`README:100/:164`）。
    """
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    _make_preset(cfg, "standard")
    preset = P.discover(roots=[P.PresetRoot(cfg)], include_user=False)[0]

    mount = P.PresetMount()
    calls: list[int] = []
    first = mount.mount(preset, lambda p: calls.append(1) or {"gen": 1})
    second = mount.mount(preset, lambda p: calls.append(2) or {"gen": 2})
    assert first is second and calls == [1], "戳没变却重新组装了"
    assert mount.generation("standard") == 1 and mount.mounted_ids() == ("standard",)
    assert not mount.is_stale(preset)

    # 组装文件改一个字节（size 变）⇒ 过期 ⇒ 换代
    preset.composition_path.write_text(json.dumps(
        [{"id": "r1", "name": "mod.a"}, {"id": "r2", "name": "mod.b"}]), encoding="utf-8")
    reloaded = P.read_preset(preset.path, root=preset.root, trust=preset.trust)
    assert mount.is_stale(reloaded)
    third = mount.mount(reloaded, lambda p: {"gen": 3})
    assert third == {"gen": 3} and mount.generation("standard") == 2


def test_a_broken_preset_is_refused_at_mount_and_a_missing_file_too(tmp_path):
    """坏预设挂不上（抛，不是"挂个空壳"）；组装文件消失后也挂不上。

    退化会坏成什么：让坏预设挂上去等于让一个会话以半组装的状态跑起来，
    而"半组装"的症状是"少了一段政策"这种看不见的形态。
    """
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    _make_preset(cfg, "ok")
    (cfg / "no-comp").mkdir()
    (cfg / "no-comp" / P.PRESET_MANIFEST_NAME).write_text("{}", encoding="utf-8")
    got = {p.id: p for p in P.discover(roots=[P.PresetRoot(cfg)], include_user=False)}
    mount = P.PresetMount()
    with pytest.raises(P.PresetError) as exc:
        mount.mount(got["no-comp"], lambda p: None)
    assert "不能挂" in str(exc.value) and "缺组装文件" in str(exc.value)

    got["ok"].composition_path.unlink()
    with pytest.raises(P.PresetError):
        mount.mount(got["ok"], lambda p: None)


def test_authoring_is_copy_only_and_refuses_the_four_bad_calls(tmp_path):
    """创作面只有复制：落在第一个用户根、`preset.json` 被改写；四种调用被拒。

    退化会坏成什么：允许直接覆盖已有目录，等于让"新建一个预设"这个动作可以毁掉别人的
    预设，而且没有任何读数会报出来；允许复制一个坏来源，等于把坏处复制一份
    （DSH 逐字："a copy is byte-identical to its source, so a source broken on disk yields
    a copy exactly as broken as the source"）。
    """
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    home = tmp_path / "home"
    _make_preset(cfg, "standard", name="内置", description="来源的描述")
    (cfg / "broken").mkdir()
    (cfg / "broken" / P.PRESET_MANIFEST_NAME).write_text("{}", encoding="utf-8")
    got = {p.id: p for p in P.discover(roots=[P.PresetRoot(cfg)], include_user=False)}

    target = P.copy_preset(got["standard"], "my-copy", home=home)
    assert target.parent == P.writable_root(home=home)
    meta = json.loads((target / P.PRESET_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert meta["description"] == "来源的描述", "复制没有保留来源的描述（作者要改的就是它）"
    assert "order" not in meta, "复制没有丢掉 order ⇒ 名册分不清副本与来源"
    assert (target / P.COMPOSITION_NAME).is_file(), "复制没有带上组装文件"

    with pytest.raises(P.PresetError):
        P.copy_preset(got["standard"], "my-copy", home=home)        # 永不覆盖
    with pytest.raises(P.PresetError):
        P.copy_preset(got["standard"], "Bad Name", home=home)       # id 不合法
    with pytest.raises(P.PresetError):
        P.copy_preset(got["broken"], "x", home=home)                # 坏来源
    with pytest.raises(P.PresetError):
        P.copy_preset(got["standard"], "y", include_user=False)     # 没有可写根


def test_remove_only_touches_presets_under_the_writable_root(tmp_path):
    """删只允许删可写根底下的那些；随包/配置根下的 ⇒ 抛。

    退化会坏成什么：能删随部署发的预设，等于"一个用户动作毁掉了所有人的内置集合"，
    而它是不可恢复的（没有版本控制兜底）。
    """
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    home = tmp_path / "home"
    _make_preset(cfg, "standard")
    configured = {p.id: p for p in P.discover(roots=[P.PresetRoot(cfg)], include_user=False)}
    with pytest.raises(P.PresetError) as exc:
        P.remove_preset(configured["standard"], home=home)
    assert "不在可写根" in str(exc.value)

    target = P.copy_preset(configured["standard"], "mine", home=home)
    mine = P.read_preset(target, root=target.parent, trust=P.TRUST_USER)
    P.remove_preset(mine, home=home)
    assert not target.exists()


def test_the_id_regex_is_the_path_safety_judge():
    """id 是目录名，所以那条正则同时是路径安全判据（不许 `..`、不许大小写、不许斜杠）。

    退化会坏成什么：放宽成"非空字符串"之后，`../x` 这种 id 会让复制写到用户根之外 ——
    而它照样是一条"复制成功"的读数。
    """
    for good in ("a", "standard", "ptc", "my-copy-2", "9lives"):
        assert P.id_is_valid(good), good
    for bad in ("", "Standard", "a_b", "a/b", "../x", "-a", ".hidden", "with space"):
        assert not P.id_is_valid(bad), bad
    assert P.PRESET_ID.pattern == r"^[a-z0-9][a-z0-9-]*$"
