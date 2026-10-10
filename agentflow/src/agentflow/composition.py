"""组装文件的解析与接线：组装行 `name` → 注册函数（`draft/103` §4.1/§4.1b）。

## 为什么要这一层

DSH 的组装行名字解析成 Cordis 插件；我们没有插件系统。按业主 2026-10-11 的口径
（逐字）「如果 dsh 的架构无法容纳系统设计，请直接改造从 dsh 那儿搬来的架构」，
这里就是那处改造：一张显式的解析表，每个名字对应一个注册函数
`(reg, role, config, base) -> Iterable[str]`，`base` 是组装文件所在目录
（`file:` 相对它解析）。

## 本轮只落两行（其余按需加，不留死表）

`draft/103` §4.1 列了 12 行。先落地的只有有用户的那两行：

| 行名 | 干什么 | 谁在用（今天） |
|---|---|---|
| `agentflow.text_blocks` | 把 `file:` / `text:` 给的正文注册成具名段 | A 的预设：新增块 `A_SEARCH_STYLE` |
| `agentflow.brief_blocks` | 把六格身份文本（真身 = `specs/<role>.py`）注册成段 | 预留：给"想显式列出这六格、但不抄第二份"的预设用 |

其余 10 行（现算块：官能/工具/动作/伙伴/任务框/循环协议/事实/上下文…）现在没有用户 ——
写出来就是死表（本仓对死表的纪律：不留；`CONTEXT_ORDERS` 与 `RESERVED_VALUES` 那两课）。
它们按需加，而"名字不认识"这件事已经有一条判据兜着：`presets._read_rows` 的 `resolve`
抛 ⇒ 那一行坏、带行号与名字，整个预设不可挂。

## 与 `presets.py` 的分工

`presets.py` 管发现/优先级/挂载/创作（机制），本模块管行名怎么落到注册上（接线）。
两边都不解释"这一行是谁"以外的东西 —— 与 DSH 的 `dsh-agent-presets` × 插件的分工同形。

## 三态（一条纪律，写在这里免得接线层忘掉）

预设坏（读不成 / 行名不认识 / 文件缺）⇒ 回落内置注册，并把"为什么回落"记进
`prompt_audit["preset"]`。不许半组装：`apply_preset()` 一旦抛，调用方必须丢掉那个注册表
重新开始（`role_prompt_registry` 就是这么做的）。
"""
from __future__ import annotations

import pathlib
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import presets as PR
from .promptkit import PromptRegistry, Section, SECTION_ORDERS

#: 解析函数的形状：注册若干段，返回它接管的段名（调用方据此跳过自己的同名注册）。
Resolver = Callable[[PromptRegistry, str, Mapping[str, Any], pathlib.Path], Iterable[str]]

#: 行名：`file:` / `text:` 给的正文 → 具名段（`draft/103` §4.1 的第一行）。
TEXT_BLOCKS = "agentflow.text_blocks"
#: 行名：五格身份文本 → 段。真身是 `specs/<role>.py`（业主裁定 I-1），这里不抄第二份。
#: 为什么是五格不是六格：第六格 `AGENT_IDENTITY` 是模板（插值 `{{task_id}}` 这些当次事实），
#: 它的渲染属于拥有那些事实的代码 ⇒ 不在这条路上。
BRIEF_BLOCKS = "agentflow.brief_blocks"

#: `composition.py` 在 `<repo>/agentflow/src/agentflow/` ⇒ 上溯三级就是 `<repo>/agentflow`。
def shipped_root() -> pathlib.Path:
    """随包预设根 = `agentflow/presets/roles/`（仓库层，不进 wheel ⇒ 不动 `pyproject.toml`）。
    理由见 `draft/106` §2 的裁定 E 与 `draft/103` §3.2 的目录树。

    为什么根是 `roles/` 而不是 `presets/`：`presets.discover()` 把根的每一个直接子目录
    当成一个预设。根若给 `presets/`，那 `roles/` 本身会被读成一个坏预设行（它没有组装文件），
    于是名册上多一条永远修不掉的坏行。共享块因此放在名册之外（`presets/shared/`），
    由各角色的组装文件用相对路径引用 —— 于是名册里不会多出一个"共享块目录"的坏行
    （设计稿里那个目录名以下划线开头，按预设 id 的字符集它也不合法）。
    """
    return pathlib.Path(__file__).resolve().parents[2] / "presets" / "roles"


# ------------------------------------------------------------------ 两个解析函数


def _as_blocks(config: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    """`config["blocks"]` 读成一段列表（形状不对 ⇒ 抛，让那一行坏）。"""
    raw = config.get("blocks")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise PR.PresetError("blocks 必须是一段列表（每项 {section, file|text, order?}）")
    out: list[Mapping[str, Any]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise PR.PresetError(f"blocks[{i}] 不是对象")
        if not str(item.get("section") or "").strip():
            raise PR.PresetError(f"blocks[{i}] 缺 section（段名）")
        has_file = bool(str(item.get("file") or "").strip())
        has_text = item.get("text") is not None
        if has_file == has_text:
            raise PR.PresetError(
                f"blocks[{i}]（{item.get('section')}）必须**恰好给一个** `file` 或 `text`"
                "（两个都给会让'这一段是谁写的'没有答案；都不给则是空段，空段应当整块不出现）")
        out.append(item)
    return out


def _order_of(item: Mapping[str, Any], section: str) -> int:
    """段的 order：块里给了就用它，否则查集中分配的 `SECTION_ORDERS`。

    为什么不许随便给一个数：号段是集中分配的（`promptkit` 的 docstring 逐字：
    免得两个模块各自写 `order=500` 而顺序随加载顺序漂移）。给了就照给的用 ——
    预设是部署面，它有权改顺序；但查得到就必须给得出理由。
    """
    got = item.get("order")
    if got is not None:
        if isinstance(got, bool) or not isinstance(got, int):
            raise PR.PresetError(f"{section} 的 order 必须是 int，收到 {got!r}")
        return got
    if section not in SECTION_ORDERS:
        raise PR.PresetError(
            f"{section} 不在 `SECTION_ORDERS` 里 ⇒ 必须在块里显式给 `order`"
            "（否则它没有位置，而位置没有默认值）")
    return SECTION_ORDERS[section]


def _register_text_blocks(reg: PromptRegistry, role: str, config: Mapping[str, Any],
                          base: pathlib.Path) -> tuple[str, ...]:
    """`agentflow.text_blocks`：把文件/内联正文注册成具名段，返回接管的段名。"""
    provided: list[str] = []
    for i, item in enumerate(_as_blocks(config)):
        section = str(item["section"]).strip()
        rel = str(item.get("file") or "").strip()
        if rel:
            path = (base / rel).resolve()
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise PR.PresetError(
                    f"blocks[{i}]（{section}）的文件读不成：{rel}（{type(exc).__name__}: {exc}）"
                ) from exc
        else:
            text = str(item["text"])
        text = _as_block_text(text)
        reg.section(Section(section, _order_of(item, section), text))
        provided.append(section)
    return tuple(provided)


def _as_block_text(text: str) -> str:
    """一段正文的规范形状：去掉首尾空行（段间由装配层用一个空行连接）。

    为什么必须做：文件末尾那个换行是编辑器给的，不是内容的一部分。留着它，
    `"\n\n".join(...)` 会在这一段与下一段之间拼出两个空行 —— 文件块与
    内联的 `text:` 块于是对同样的内容渲染出不同的东西（实测：`search_style.md`
    末尾带换行 ⇒ A 的提示词里那一段后面多一个空行，字符数 17394 而不是 17393）。
    只去首尾空行，正文内部一个字符都不动。
    """
    return text.strip("\n")


def _register_brief_blocks(reg: PromptRegistry, role: str, config: Mapping[str, Any],
                           base: pathlib.Path) -> tuple[str, ...]:
    """`agentflow.brief_blocks`：把五格身份文本注册成段 —— 内容仍从真身读，不抄第二份。

    业主裁定（`draft/107` §5-I-1）逐字：「`specs/<role>.py::SPEC.brief` 是唯一真身；
    `agent_prompts.ROLE_BRIEFS` 改成它的视图」。所以这一行的存在意义只有一个：
    让预设可以显式声明"这五格由我列出"（于是顺序/取舍写在组装文件里），
    而正文一个字都不许在预设里重写 —— 那是第二份副本，唯一性裁定不允许。

    为什么是五格而不是六格：`AGENT_IDENTITY` 那一段是模板（它插值
    `{{task_id}}` / `{{depth}}` / `{{children}}` 这些这一次运行的事实），
    它的渲染属于"拥有那些事实"的代码 ⇒ 不在这条路上（写进预设就得把变量也搬过去，
    而变量的值来自 `role_prompt_registry` 的当次入参）。

    `config`：`{"sections": ["ROLE_BOUNDARY", ...]}`（省略 = 五格全要，各段按真身渲染）。
    """
    from . import agent_prompts as AP          # 局部导入：避免与 agent_prompts 形成环

    want = config.get("sections")
    allow = (tuple(str(x) for x in want)
             if isinstance(want, Sequence) and not isinstance(want, (str, bytes)) else None)
    provided: list[str] = []
    for name, order, text in AP.brief_sections(role):
        if allow is not None and name not in allow:
            continue
        if not text:
            continue                      # 这一格这个角色本来就没有（空段不出现）
        reg.section(Section(name, order, text))
        provided.append(name)
    return tuple(provided)


#: 解析表（今天两行；`draft/103` §4.1 的其余 10 行按需加）。
RESOLVERS: dict[str, Resolver] = {
    TEXT_BLOCKS: _register_text_blocks,
    BRIEF_BLOCKS: _register_brief_blocks,
}


def _resolvable(name: str) -> Any:
    """给 `presets.discover(resolve=…)` 用的探针：名字不认识就抛（那一行坏）。"""
    if name not in RESOLVERS:
        raise PR.PresetError(f"组装行名字不认识：{name!r}（已知 {tuple(RESOLVERS)}）")
    return RESOLVERS[name]


# ------------------------------------------------------------------ 对外三件


def preset_id_of(role: str) -> str:
    """角色 id → 预设 id：小写化（`A` → `a`）。

    为什么需要一层映射：预设 id 的字符集由 `presets.PRESET_ID` 定死
    （`^[a-z0-9][a-z0-9-]*$`，照抄 `presetkit` 的口径：它同时是目录名、
    是 URL 里的一段、也是名册上的行标识），而角色 id 在本仓是大写单字母
    （`schema.ROLES` 的 `A`…`H`、`V`、`M`）。实测：目录叫 `A` 时预设读出来是
    "目录名不是合法 id：'A'" ⇒ 静默回落内置那份，而这种失败没有任何别的读数
    （除了 `prompt_audit["preset"]["problem"]`）。

    映射只有这一处，且加了判据（`tests/test_composition.py` 里逐角色对账）：
    映射一旦与目录名错开，读数上就只是"哪个角色的预设找不着"，
    没有判据的话它会以"内置那份照跑"的形态一直藏着。
    小写化对现有十个角色（单字母）是一一映射；以后若出现小写后不合法 id 的角色名，
    这里会返回一个非法 id ⇒ `discover` 判它坏、读数里写明，不会静默。
    """
    return role.strip().lower()


def role_preset(role: str, *, root: pathlib.Path | None = None) -> PR.Preset | None:
    """找某个角色的预设；没有 ⇒ None（调用方回落内置注册）。

    只管随包根（`include_user=False`）：用户自写的预设要生效得先有一条裁定
    （"用户能改提示词"这件事本身是部署面决策，`draft/103` §4.5 的不做清单里）。
    """
    base = pathlib.Path(root) if root is not None else shipped_root()
    want = preset_id_of(role)
    for preset in PR.discover(shipped_root=base, include_user=False, resolve=_resolvable):
        if preset.id == want:
            return preset
    return None


def preset_reading(role: str, *, root: pathlib.Path | None = None) -> dict[str, Any]:
    """这个角色这一次的预设读数（给 `prompt_audit` 用）：`id / path / trust / rows / problem`。

    `problem` 涵盖两档，因为它们对读的人意义不同却都表现为"内置那份在跑"：
      - 发现期：`preset.broken`（缺组装文件 / YAML 读不成 / 行名不认识 / 非法 id…）；
      - 组装期：`apply_preset()` 抛出的异常（文件不见了、`file` 与 `text` 同时给…）。
    只报第一档会让"预设明明在盘上、却静默用了内置那份"没有读数。

    它不改任何东西：那次组装跑在一个丢弃的注册表上（与真装配同一段代码 ⇒ 同一个结论）。
    """
    preset = role_preset(role, root=root)
    if preset is None:
        return {"id": "", "path": "", "trust": "", "rows": 0, "problem": ""}
    fact: dict[str, Any] = {"id": preset.id, "path": str(preset.path),
                            "trust": preset.trust, "rows": len(preset.rows),
                            "problem": preset.broken}
    if not preset.broken:
        try:
            apply_preset(PromptRegistry(), preset, role=role)
        except Exception as exc:  # noqa: BLE001 —— 这里就是要把它翻成读数
            fact["problem"] = f"{type(exc).__name__}: {exc}"
    return fact


def apply_preset(reg: PromptRegistry, preset: PR.Preset, *, role: str) -> set[str]:
    """按组装文件的顺序注册它声明的段，返回接管的段名集合。

    坏行（解析函数抛）⇒ 异常往上走：调用方必须丢掉这个注册表重新开始
    （半组装的提示词比没有提示词坏得多 —— `draft/101` §6.1 的 P16 形态）。
    `disabled` 那一档：`presets.PresetRow.state` 明确 `enabled` 才挂；
    `conditional`（`!!js` 这种求值不了的门）不挂，因为"没求值"不许读成"生效"。
    """
    provided: set[str] = set()
    if preset.broken:
        # 坏预设当面拒（不半组装）：调用方据此回落内置注册，理由进 `preset_reading`。
        raise PR.PresetError(f"预设 {preset.id!r} 不能挂：{preset.broken}")
    for row in preset.rows:
        if row.state != PR.GATE_ENABLED:
            continue
        resolver = RESOLVERS.get(row.name)
        if resolver is None:
            raise PR.PresetError(f"组装行 {row.id!r} 的名字不认识：{row.name!r}")
        cfg = row.config if isinstance(row.config, Mapping) else {}
        provided.update(resolver(reg, role, cfg, preset.path))
    return provided


def selftest() -> int:
    """自检：解析表、文件块、坏形状、provided 集合、三态（坏预设不半组装）。"""
    import tempfile

    problems: list[str] = []

    def check(ok: bool, what: str) -> None:
        if not ok:
            problems.append(what)

    with tempfile.TemporaryDirectory(prefix="compose-") as td:
        base = pathlib.Path(td)
        (base / "blocks").mkdir()
        (base / "blocks" / "one.md").write_text("第一段的正文", encoding="utf-8")

        # 正控：file: 与 text: 两种来源、order 显式给与查表给
        reg = PromptRegistry()
        got = _register_text_blocks(reg, "A", {"blocks": [
            {"section": "ROLE_POLICY", "file": "blocks/one.md"},
            {"section": "EVIDENCE_RULES", "text": "内联的正文", "order": 3010},
        ]}, base)
        check(set(got) == {"ROLE_POLICY", "EVIDENCE_RULES"}, f"provided 不对：{got}")
        names = reg.assemble().names
        check("ROLE_POLICY" in names and "EVIDENCE_RULES" in names, names)

        # 负控一：一个块同时给 file 与 text ⇒ 抛（"这一段是谁写的"没有答案）
        for bad_cfg, why in (
            ({"blocks": [{"section": "X", "file": "a", "text": "b"}]}, "同时给 file/text"),
            ({"blocks": [{"section": "X"}]}, "两个都不给"),
            ({"blocks": [{"file": "a"}]}, "缺 section"),
            ({"blocks": {"section": "X", "file": "a"}}, "blocks 不是列表"),
            ({"blocks": [{"section": "X", "file": "a", "order": "1"}]}, "order 不是 int"),
            ({"blocks": [{"section": "不存在的段", "text": "x"}]}, "段名不在表里且没给 order"),
        ):
            try:
                _register_text_blocks(PromptRegistry(), "A", bad_cfg, base)
                problems.append(f"没有拒绝：{why}")
            except PR.PresetError:
                pass  # 期望它抛

        # 负控二：文件不存在 ⇒ 抛（带路径）
        try:
            _register_text_blocks(PromptRegistry(), "A",
                                  {"blocks": [{"section": "ROLE_POLICY", "file": "没有这个文件"}]},
                                  base)
            problems.append("文件不存在却没有抛")
        except PR.PresetError as exc:
            check("没有这个文件" in str(exc), f"抛出的理由没带路径：{exc}")

        # 正控：坏预设 apply_preset ⇒ 抛（调用方据此丢掉注册表回落）
        broken = PR.Preset(id="A", root=base, trust=PR.TRUST_SYSTEM, path=base,
                           broken="组装文件读不了")
        try:
            apply_preset(PromptRegistry(), broken, role="A")
        except PR.PresetError as exc:
            check("不能挂" in str(exc), f"坏预设抛的理由没说清：{exc}")
        else:
            problems.append("坏预设居然组装成功")

    if problems:
        print("SELF-CHECK FAILED")
        for p in problems:
            print("  -", p)
        return 1
    print("SELF-CHECK DONE（composition 正控 3 条 + 负控 7 条）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(selftest())
