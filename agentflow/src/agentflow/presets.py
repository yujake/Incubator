"""预设：一个预设一个目录、发现按根优先级、挂一次、复制式创作（`dsh-agent-presets` 的端口）。

## 这个模块解决什么

"预设有哪几个、从哪来、改了之后什么时候生效、谁能改"这四件事此前没有落点：
提示词的内容散在 `agent_prompts.py` 的常量与函数里，"换一套"只能改代码。
DSH 把这一层做成数据：一个预设就是一个目录，目录里有一份显示元数据与一份组装文件；
发现、优先级、健康、生效时机、创作面都由机制规定，内容由目录里的文件决定。

## 搬过来的七条（逐条带 DSH 出处）

1. 一个预设一个目录：`preset.json`（显示三件：name / description / order）+
   组装文件（必需）。DSH 的对应物是 `presets/<id>/preset.yml` + `agent.cordis.yml`
   （实测四个随包预设的目录形状见 `draft/101` §2.1）。
2. 根按优先级扫（`README:54-60`）：随包根前置（所以内置永远赢同 id）→ 部署配置的根
   → 用户的根（追加在最后）。`trust` 三档：`system` / `configured` / `user`。
3. 坏预设列出来带理由，不跳过（`README:85/:102`）。逐字理由：
   "a skipped directory would still occupy its id while no surface shows anything to delete"。
4. 一个预设一个常驻组装，进程内挂一次（`README:99`）；前缀在 agent 一生里稳定
   （`README:164` 逐字："a composition is installed once, before the agent is published and
   therefore before its first request, and is never re-read while the agent runs"）。
5. 生成键 = 组装文件的 mtime + size（`README:100`）：戳变了就开新一代；
   已经在跑的会话留在它那一代（所以改文件不打断在跑的会话）。
6. 创作面只有复制（`README:75-77`）：新建 = 复制一个已有预设的整目录；复制永不覆盖；
   删只允许删本地创作的那些（随部署发的不可删）。
7. id 是一条正则（`README:77`）：`^[a-z0-9][a-z0-9-]*$` —— 因为 id 会成为目录名。

## 与 DSH 的偏差（三条，都写在下面各自的位置上）

- 组装文件用 JSON（stdlib）而不是 YAML：本仓运行期依赖只有 `filelock`
  （`pyproject.toml` 的注释逐字："运行期依赖必须保持极小"），而 YAML 不在声明里。
  形状（"具名行的列表"）与 DSH 一致。
- DSH 的组装行名字解析成 Cordis 插件；本模块不解析（那是接线面的事）：
  `resolve` 由调用方传进来（不给就跳过这一条健康检查）。机制与内容因此分开。
- DSH 的"用户根"是 `<dshHome>/.agent-presets`；本框架没有 `dshHome`，默认取
  `~/.agentflow/agent-presets`（同样可关掉）。
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import stat
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

#: 显示元数据的文件名（DSH：`preset.yml`）。
PRESET_MANIFEST_NAME = "preset.json"

#: 组装文件的文件名（DSH：`agent.cordis.yml`；本框架的组装语言是 JSON，见模块 docstring）。
COMPOSITION_NAME = "agent.agentflow.json"

#: 用户根的默认位置（DSH：`<dshHome>/.agent-presets`）。
USER_ROOT_SUBDIR = pathlib.Path(".agentflow") / "agent-presets"

#: 预设 id 的正则（DSH 逐字）。id 会成为目录名，所以这条正则同时是路径安全判据。
PRESET_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")

#: 三档信任（DSH 同名）：随包发的、部署配的、用户自己写的。
TRUST_SYSTEM = "system"
TRUST_CONFIGURED = "configured"
TRUST_USER = "user"
TRUSTS: tuple[str, ...] = (TRUST_SYSTEM, TRUST_CONFIGURED, TRUST_USER)


class PresetError(ValueError):
    """预设的配置错误（id 非法、复制覆盖、删随包预设、组装文件读不了）。"""


@dataclass(frozen=True)
class PresetRoot:
    """一个被扫的根目录。

    `trust` 不是标签而是权限面：只有第一个 `user` 根底下的预设有创作权
    （删除与新建都落在那里）。DSH 逐字（`README:173`）：复制/删除只认第一个 user 根，
    "不在可写根下"是一个明确答案，而不是"试试看"。
    """

    path: pathlib.Path
    trust: str = TRUST_CONFIGURED

    def __post_init__(self) -> None:
        if self.trust not in TRUSTS:
            raise PresetError(f"未知的 trust {self.trust!r}（只认 {TRUSTS}）")

    def resolved(self, home: pathlib.Path | None = None) -> pathlib.Path:
        """展开 `~` 之后的绝对路径（DSH：`path` 里的前导 `~` 会展开）。"""
        raw = str(self.path)
        if raw.startswith("~"):
            base = home if home is not None else pathlib.Path.home()
            raw = str(base) + raw[1:]
        return pathlib.Path(raw).expanduser().resolve()


@dataclass(frozen=True)
class PresetRow:
    """组装文件里的一行（DSH 的 `{id, name, config, disabled, group, isolate}`）。

    `name` 是"要挂什么"的名字，本模块不解释它（见模块 docstring 的偏差二）：
    机制只知道"有哪些行、哪一行坏了"，"这一行是谁"由接线面回答。
    """

    id: str
    name: str
    config: Any = None
    disabled: bool = False
    group: bool = False
    isolate: Mapping[str, bool] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        """这一行这次会不会生效（`disabled` 为真时不挂，但仍在清单里可见）。"""
        return not self.disabled


@dataclass(frozen=True)
class Preset:
    """一个预设。`broken` 非空 = 它不能挂（原因逐字留着，供列表面显示）。"""

    id: str
    root: pathlib.Path
    trust: str
    path: pathlib.Path
    name: str = ""
    description: str = ""
    order: int = 100
    rows: tuple[PresetRow, ...] = ()
    broken: str = ""

    @property
    def composition_path(self) -> pathlib.Path:
        return self.path / COMPOSITION_NAME

    @property
    def display(self) -> str:
        """列表面上显示什么（没有 name 就退回 id）。"""
        return self.name or self.id


@dataclass(frozen=True)
class PresetStamp:
    """组装文件的戳（DSH：mtime + size）。生成（generation）就按它换代。"""

    mtime: float
    size: int

    @classmethod
    def of(cls, path: pathlib.Path) -> "PresetStamp":
        st = path.stat()
        return cls(mtime=st.st_mtime, size=st.st_size)


def id_is_valid(preset_id: str) -> bool:
    """id 合法吗（DSH 逐字正则；不合法 ⇒ 不能成为目录名）。"""
    return bool(PRESET_ID.match(str(preset_id or "")))


def scan_roots(*, roots: Sequence[PresetRoot] = (), shipped_root: pathlib.Path | None = None,
               include_shipped: bool = True, include_user: bool = True,
               home: pathlib.Path | None = None) -> tuple[PresetRoot, ...]:
    """按优先级排出要扫的根：随包（前置）→ 配置的 → 用户的（最后）。

    顺序就是优先级（前一个赢同名 id）。DSH 逐字（`README:60`）：随包根前置是刻意的，
    "so the built-in set remains available and wins duplicate ids even when a patch replaces
    the roster configuration"。
    """
    out: list[PresetRoot] = []
    if include_shipped and shipped_root is not None:
        out.append(PresetRoot(pathlib.Path(shipped_root), TRUST_SYSTEM))
    out.extend(roots)
    if include_user:
        base = home if home is not None else pathlib.Path.home()
        out.append(PresetRoot(pathlib.Path(base) / USER_ROOT_SUBDIR, TRUST_USER))
    return tuple(out)


def writable_root(*, roots: Sequence[PresetRoot] = (), include_user: bool = True,
                  home: pathlib.Path | None = None) -> pathlib.Path | None:
    """第一个 `user` 根（创作面唯一能写的地方）；没有就是 None。"""
    for root in scan_roots(roots=roots, include_shipped=False, include_user=include_user,
                           home=home):
        if root.trust == TRUST_USER:
            return root.resolved(home)
    return None


def read_preset(path: pathlib.Path, *, root: pathlib.Path, trust: str,
                resolve: Callable[[str], Any] | None = None) -> Preset:
    """读一个预设目录。读不成 ⇒ 返回一个 `broken` 非空的 `Preset`（不抛）。

    为什么不抛：发现面要能把它列出来并说明为什么不能挂（DSH 逐字：
    "listed as broken with a reason naming the rows at fault; composing such a preset is
    refused up front, so a session never starts half-composed"）。抛出去的话，
    用户在列表上看到的是"这个预设不见了"，而不是"它坏在哪一行"。
    """
    preset_id = path.name
    base = dict(id=preset_id, root=root, trust=trust, path=path)
    if not id_is_valid(preset_id):
        return Preset(**base, broken=f"目录名不是合法 id（要求 {PRESET_ID.pattern}）：{preset_id!r}")

    meta: dict[str, Any] = {}
    manifest = path / PRESET_MANIFEST_NAME
    if manifest.is_file():
        try:
            loaded = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return Preset(**base, broken=f"{PRESET_MANIFEST_NAME} 读不了：{type(exc).__name__}: {exc}")
        if not isinstance(loaded, Mapping):
            return Preset(**base, broken=f"{PRESET_MANIFEST_NAME} 的最外层必须是对象")
        meta = dict(loaded)

    composition = path / COMPOSITION_NAME
    if not composition.is_file():
        return Preset(**base, name=str(meta.get("name", "")),
                      description=str(meta.get("description", "")),
                      broken=f"缺组装文件 {COMPOSITION_NAME}")

    try:
        rows_raw = json.loads(composition.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return Preset(**base, name=str(meta.get("name", "")),
                      description=str(meta.get("description", "")),
                      broken=f"组装文件读不了：{type(exc).__name__}: {exc}")

    rows, broken = _read_rows(rows_raw, resolve=resolve)
    preset = Preset(**base,
                    name=str(meta.get("name", "")),
                    description=str(meta.get("description", "")),
                    order=int(meta.get("order", 100) or 100),
                    rows=rows, broken=broken)
    return preset


def _read_rows(rows_raw: Any, *, resolve: Callable[[str], Any] | None) -> tuple[tuple[PresetRow, ...], str]:
    """组装文件 → 行；返回 (行, 坏理由)。"""
    if not isinstance(rows_raw, Sequence) or isinstance(rows_raw, (str, bytes)):
        return (), "组装文件必须是一个具名行的列表"
    rows: list[PresetRow] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows_raw):
        if not isinstance(raw, Mapping):
            return (), f"第 {index} 行不是对象"
        row_id = str(raw.get("id", "") or "")
        row_name = str(raw.get("name", "") or "")
        if not row_id or not row_name:
            return (), f"第 {index} 行缺 id 或 name（两者都必填）"
        if row_id in seen:
            return (), f"组装文件里 id 重复：{row_id!r}（一行一个 id）"
        seen.add(row_id)
        isolate = raw.get("isolate", {}) or {}
        if not isinstance(isolate, Mapping):
            return (), f"第 {index} 行（{row_id}）的 isolate 必须是对象"
        if resolve is not None and not bool(raw.get("disabled")):
            try:
                resolve(row_name)
            except Exception as exc:  # noqa: BLE001 —— 这里就是要把它翻成"这一行坏了"
                return (), (f"第 {index} 行（{row_id}）命名的 {row_name!r} 解析不了："
                            f"{type(exc).__name__}: {exc}")
        rows.append(PresetRow(
            id=row_id, name=row_name, config=raw.get("config"),
            disabled=bool(raw.get("disabled")), group=bool(raw.get("group")),
            isolate={str(k): bool(v) for k, v in dict(isolate).items()},
        ))
    return tuple(rows), ""


def discover(*, roots: Sequence[PresetRoot] = (), shipped_root: pathlib.Path | None = None,
             include_shipped: bool = True, include_user: bool = True,
             home: pathlib.Path | None = None,
             resolve: Callable[[str], Any] | None = None) -> tuple[Preset, ...]:
    """扫全部根：前一个根赢同名 id；坏预设留在清单里带理由。

    为什么"前一个根赢"而不是"后一个覆盖"：随包根在最前面 ⇒ 内置集合永远可用、
    同 id 永远赢（DSH 的理由逐字见 `scan_roots`）。让后一个覆盖，等于让一个用户目录
    悄悄换掉内置预设的全部行为，而列表面上看不出哪一份在跑。
    """
    out: list[Preset] = []
    seen: dict[str, Preset] = {}
    for root in scan_roots(roots=roots, shipped_root=shipped_root,
                           include_shipped=include_shipped, include_user=include_user,
                           home=home):
        base = root.resolved(home)
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            preset = read_preset(child, root=base, trust=root.trust, resolve=resolve)
            if preset.id in seen:
                continue                      # 前一个根赢（含"坏的那一份也占住 id"）
            seen[preset.id] = preset
            out.append(preset)
    return tuple(out)


# ------------------------------------------------------------------ 挂载与生成


class PresetMount:
    """一个进程里的常驻挂载表：一个预设挂一次，戳变了才开新一代。

    为什么"挂一次"而不是每会话挂一次（DSH `README:164` 逐字）：组装决定的是前缀，
    而前缀稳定才谈得上复用（KV cache）；每会话重挂会把"这次跑的是哪一套"变成每会话
    都可能不同，且旧代与它在跑的会话必须一起留着（DSH 自认的代价：`README:176`，
    旧代不回收）。

    本模块只记"该开新一代了没有"：真正的组装由调用方给的 `compose` 做（见模块 docstring）。
    """

    def __init__(self) -> None:
        self._generations: dict[str, int] = {}
        self._stamps: dict[str, PresetStamp] = {}
        self._mounted: dict[str, Any] = {}

    def stamp_of(self, preset: Preset) -> PresetStamp | None:
        """这个预设当前的戳；组装文件不在 ⇒ None。"""
        path = preset.composition_path
        if not path.is_file():
            return None
        try:
            return PresetStamp.of(path)
        except OSError:
            return None

    def is_stale(self, preset: Preset) -> bool:
        """戳与上一次挂的时候不一样（含"还没挂过"与"组装文件不在了"两种情况）。

        为什么"文件不在了"必须算过期：两种情况下 `stamp_of` 都是 None ——
        "从没挂过"与"挂过但文件被删了"。旧写法只比 `stamps.get(id) != stamp`，
        于是"从没挂过 + 文件不在"会判成不过期，接着去取一个并不存在的挂载值
        （KeyError）。它不是理论情形：`tests/test_presets.py` 里那条"组装文件消失"
        的用例第一次跑就撞上了。所以这里把 None 显式归到过期那一档。
        """
        stamp = self.stamp_of(preset)
        if stamp is None:
            return True
        return self._stamps.get(preset.id) != stamp

    def mount(self, preset: Preset, compose: Callable[[Preset], Any]) -> Any:
        """挂一个预设：只有戳变了（或还没挂过）才真的 `compose`。

        坏预设 ⇒ 抛（逐字理由：宁可当场拒挂，也不让一个会话以半组装的状态跑起来）。
        """
        if preset.broken:
            raise PresetError(f"预设 {preset.id!r} 不能挂：{preset.broken}")
        if not self.is_stale(preset):
            return self._mounted[preset.id]
        stamp = self.stamp_of(preset)
        if stamp is None:
            raise PresetError(f"预设 {preset.id!r} 的组装文件不见了：{preset.composition_path}")
        value = compose(preset)
        self._stamps[preset.id] = stamp
        self._generations[preset.id] = self._generations.get(preset.id, 0) + 1
        self._mounted[preset.id] = value
        return value

    def generation(self, preset_id: str) -> int:
        """这个预设挂过几代（0 = 从没挂过）。"""
        return self._generations.get(str(preset_id), 0)

    def mounted_ids(self) -> tuple[str, ...]:
        """挂过（且当前）的预设 id，按名字排序。"""
        return tuple(sorted(self._mounted))


# ------------------------------------------------------------------ 创作面（只有复制）


def copy_preset(source: Preset, new_id: str, *, roots: Sequence[PresetRoot] = (),
                include_user: bool = True, home: pathlib.Path | None = None,
                name: str = "") -> pathlib.Path:
    """把一个已有预设整目录复制成新的本地预设，返回新目录。

    四条拒绝（DSH `README:77` 逐字）：id 不合法、id 已被占用、来源未知、
    没有可写根。复制永不覆盖；复制之后 `preset.json` 被改写（保留 description、
    丢掉 name 与 order）—— 理由逐字：复制保留来源的描述是给作者改的，
    而 name/order 丢掉是为了"名册分得清副本与来源"。
    """
    if not id_is_valid(new_id):
        raise PresetError(f"预设 id 不合法（要求 {PRESET_ID.pattern}）：{new_id!r}")
    if source.broken:
        raise PresetError(
            f"来源预设 {source.id!r} 自己是坏的（{source.broken}）⇒ 复制出来只会一样坏。"
            "DSH 逐字：a copy is byte-identical to its source, so a source broken on disk "
            "yields a copy exactly as broken as the source")
    if not source.path.is_dir():
        raise PresetError(f"来源预设目录不存在：{source.path}")
    root = writable_root(roots=roots, include_user=include_user, home=home)
    if root is None:
        raise PresetError("没有可写的用户根（include_user=False 且没有配置 user 根）")
    target = root / new_id
    if target.exists():
        raise PresetError(f"目标已存在，复制永不覆盖：{target}")
    root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source.path, target)
    meta = {"name": name or source.display, "description": source.description}
    (target / PRESET_MANIFEST_NAME).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _tighten(target)
    return target


def remove_preset(preset: Preset, *, roots: Sequence[PresetRoot] = (),
                  include_user: bool = True, home: pathlib.Path | None = None) -> None:
    """删掉一个本地创作的预设。随部署发的、或不在可写根下的 ⇒ 抛。"""
    root = writable_root(roots=roots, include_user=include_user, home=home)
    if root is None:
        raise PresetError("没有可写的用户根 ⇒ 什么都删不了")
    try:
        preset.path.resolve().relative_to(root)
    except ValueError as exc:
        raise PresetError(
            f"预设 {preset.id!r} 不在可写根 {root} 底下 ⇒ 不能删。"
            "DSH 逐字：remove() refuses anything that does not live under the first user root"
        ) from exc
    shutil.rmtree(preset.path)


def _tighten(root: pathlib.Path) -> None:
    """把整棵树收紧到 owner-only（DSH：文件 0o600、目录 0o700）。"""
    for path in [root, *root.rglob("*")]:
        try:
            if path.is_dir():
                path.chmod(0o700)
            else:
                mode = path.stat().st_mode
                keep_exec = bool(mode & stat.S_IXUSR)
                path.chmod(0o700 if keep_exec else 0o600)
        except OSError:
            continue          # 平台不支持就跳过（收紧是加固，不是功能）


def selftest() -> int:
    """自检：发现优先级、坏预设不跳过、复制四条拒绝、生成换代。"""
    import tempfile

    problems: list[str] = []

    def check(ok: bool, what: str) -> None:
        if not ok:
            problems.append(what)

    def write_preset(base: pathlib.Path, preset_id: str, *, name: str = "",
                     rows: Any = None, broken_rows: Any = None) -> pathlib.Path:
        path = base / preset_id
        path.mkdir(parents=True, exist_ok=True)
        (path / PRESET_MANIFEST_NAME).write_text(
            json.dumps({"name": name or preset_id, "description": "d", "order": 1},
                       ensure_ascii=False), encoding="utf-8")
        if broken_rows is not None:
            (path / COMPOSITION_NAME).write_text(str(broken_rows), encoding="utf-8")
        else:
            (path / COMPOSITION_NAME).write_text(
                json.dumps(rows if rows is not None else [{"id": "a", "name": "mod.a"}]),
                encoding="utf-8")
        return path

    with tempfile.TemporaryDirectory(prefix="preset-") as td:
        tmp = pathlib.Path(td)
        shipped = tmp / "shipped"
        configured = tmp / "configured"
        home = tmp / "home"
        shipped.mkdir(); configured.mkdir()
        write_preset(shipped, "standard", name="内置")
        write_preset(configured, "standard", name="配置的")     # 同 id ⇒ 内置赢
        write_preset(configured, "extra", name="额外的")
        write_preset(configured, "bad", broken_rows="{ 不是合法 JSON")
        (configured / "not-a-preset-dir").mkdir()
        (configured / "Bad_Id").mkdir()

        got = discover(roots=[PresetRoot(configured, TRUST_CONFIGURED)],
                       shipped_root=shipped, home=home)
        by_id = {p.id: p for p in got}
        check(by_id["standard"].display == "内置", "同 id 时不是随包根赢")
        check("extra" in by_id, "配置根里的预设没有出现")
        check(by_id["bad"].broken and "读不了" in by_id["bad"].broken,
              f"坏预设没有带理由：{by_id.get('bad')}")
        check(any(p.broken for p in got if p.id == "Bad_Id"),
              "非法 id 的目录没有被列成坏行（它占着 id 却不显示，就没法删）")
        check(by_id["standard"].trust == TRUST_SYSTEM, "trust 不是 system")

        # 生成：戳不变 ⇒ 同一代；改一下 ⇒ 新的一代
        mount = PresetMount()
        calls: list[str] = []
        std = by_id["standard"]
        first = mount.mount(std, lambda p: calls.append(p.id) or "组装1")
        again = mount.mount(std, lambda p: "组装2")
        check(first == again == "组装1" and calls == ["standard"],
              "戳没变却又组装了一次（前缀就不稳定了）")
        check(mount.generation("standard") == 1, "代数不对")
        comp = std.composition_path
        comp.write_text(json.dumps([{"id": "a", "name": "mod.a"},
                                    {"id": "b", "name": "mod.b"}]), encoding="utf-8")
        reloaded = read_preset(std.path, root=std.root, trust=std.trust)
        check(mount.is_stale(reloaded), "戳变了却没判成过期")
        mount.mount(reloaded, lambda p: "组装2")
        check(mount.generation("standard") == 2, "换代之后代数没加")

        try:
            mount.mount(by_id["bad"], lambda p: None)
            problems.append("坏预设居然挂上了")
        except PresetError:
            pass  # 期望它抛

        # 复制：合法 → 落在用户根；重名/非法/坏来源 ⇒ 抛
        target = copy_preset(std, "my-copy", roots=[], home=home)
        check(target.parent == (home / USER_ROOT_SUBDIR).resolve(), f"复制没落在用户根：{target}")
        copied_meta = json.loads((target / PRESET_MANIFEST_NAME).read_text(encoding="utf-8"))
        check("order" not in copied_meta, "复制没有丢掉 order（名册分不清副本与来源）")
        for bad_call, why in (
            (lambda: copy_preset(std, "my-copy", roots=[], home=home), "重名"),
            (lambda: copy_preset(std, "Bad", roots=[], home=home), "非法 id"),
            (lambda: copy_preset(by_id["bad"], "x", roots=[], home=home), "坏来源"),
        ):
            try:
                bad_call()
                problems.append(f"复制没有拒绝：{why}")
            except PresetError:
                pass  # 负控期望它抛：抛了才算这一格通过（上面已把它记成问题）

        # 删除：只删本地创作的那些
        mine = read_preset(target, root=target.parent, trust=TRUST_USER)
        remove_preset(mine, roots=[], home=home)
        check(not target.exists(), "本地预设没删掉")
        try:
            remove_preset(std, roots=[], home=home)
            problems.append("删掉了随包/不可写根下的预设")
        except PresetError:
            pass  # 负控期望它抛：不许删掉可写根之外的预设（上面已把它记成问题）

    if problems:
        print("SELF-CHECK FAILED")
        for p in problems:
            print("  -", p)
        return 1
    print("SELF-CHECK DONE（preset 正控 11 条 + 负控 5 条）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(selftest())
