# -*- coding: utf-8 -*-
"""agent 面的冻结快照（`goal-7f5116c1` M1 的尺子：动"模块化"之前先钉住今天这张面）。

要动的是"一个 agent 由六处共同定义"这件事（角色词表 / 工具角色表 / 权限面 / 提示词 /
host 接线 / 文档）。动之前先把今天这张面钉成可比较的一份数据，否则"我重构了"
与"我改坏了"分不开。钉六层：

1. 动作表：`capabilities.CAPABILITIES` 里每个角色每条 `ActionSpec` 的全字段
   （role / action / summary / params / returns / side_effect / handler_name / external），
   按 action 排序；
2. 召唤面：`ALLOWED_EDGES[role]`（排序）、是否可被召唤（`NON_SUMMONABLE`）、
   `WRITE_SETS[role]`、是否只读角色；
3. 工具面：`build_for_role(role, store=…, workspace_root=…)` 的工具名清单
   （逐工具的全字段声明已由 `tests/test_tool_surface_snapshot.py` 钉住，这里只钉"每个角色拿到哪些"）；
4. 提示词：`system_prompt(role, registry=…)` 的逐字文本——"调整 agent 行为"最常改的就是它；
5. 接线：`wiring_status(store)`、`build_role_registry(store)` 里每个角色拿到几个实例/什么类、
   每个 `AgentX.__init__` 的签名（钉住"构造期要什么依赖"）；
6. 动作级实现签名：每条 `ActionSpec.handler_name` 在对应 agent 类上的方法签名
   （钉住"动作的对外形状"，重构分文件时不许变）。

## 重新生成

```powershell
cd D:\\Incubator\\agentflow
$env:PYTHONUTF8='1'; python -B tests/test_agent_surface_snapshot.py --write
```
生成之后先看 diff：差在哪、为什么。
"""
from __future__ import annotations

import dataclasses
import inspect
import json
import pathlib
import re
import sys
import tempfile

import pytest

GOLDEN = pathlib.Path(__file__).resolve().parent / "golden" / "agent_surface_snapshot.json"

#: 角色 ⇒ 它的实现类所在的模块与类名。这张表本身就是"今天 agent 由谁实现"的事实，
#: 快照把它钉住（模块化之后应当由注册表给出，那时这张表会换成从注册表读）。
AGENT_CLASSES: dict[str, tuple[str, str]] = {
    "A": ("agentflow.agent_a", "AgentA"),
    "B": ("agentflow.agent_b", "AgentB"),
    "C": ("agentflow.agent_c", "AgentC"),
    "D": ("agentflow.agent_d", "AgentD"),
    "E": ("agentflow.agent_e", "AgentE"),
    "F": ("agentflow.agent_f", "AgentF"),
    "G": ("agentflow.agent_g", "AgentG"),
    "H": ("agentflow.agent_h", "AgentH"),
    # V（F-02 起）：证明级验证（只读）。它是第 9 个角色包，2026-10-06 落地。
    "V": ("agentflow.agent_v", "AgentV"),
    "M": ("agentflow.conductor", "Conductor"),
}

_ADDR = re.compile(r"0x[0-9a-fA-F]+")


def _scrub(text: str, tmp: pathlib.Path) -> str:
    """遮掉随机临时目录与对象地址（它们不是"面"的一部分）。"""
    return _ADDR.sub("0x…", text.replace(str(tmp), "<TMP>"))


def _cls(role: str) -> type:
    import importlib

    module, name = AGENT_CLASSES[role]
    return getattr(importlib.import_module(module), name)


def _build(tmp: pathlib.Path):
    from agentflow.store import Store
    from agentflow.tools import ROLES, build_for_role, build_registry

    ws = tmp / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    full = build_registry(store=st, workspace_root=ws, roles=tuple(ROLES),
                          strict=True).registry
    per_role = {r: build_for_role(r, store=st, workspace_root=ws) for r in (*ROLES, "M")}
    return st, ws, full, per_role


def _snapshot(tmp: pathlib.Path) -> dict:
    from agentflow import capabilities as C
    from agentflow import schema as S
    from agentflow.agent_prompts import system_prompt
    from agentflow.host import build_role_registry, wiring_status
    from agentflow.tools import READ_ONLY_ROLES, SIDE_EFFECTS_WRITE, TOOL_ROLES

    st, ws, full, per_role = _build(tmp)
    roles: dict[str, dict] = {}
    for role in TOOL_ROLES:
        cls = _cls(role)
        actions = []
        for spec in sorted(C.CAPABILITIES.get(role, ()), key=lambda s: s.action):
            actions.append({f.name: getattr(spec, f.name) for f in dataclasses.fields(spec)})
        handlers = {}
        for spec in C.CAPABILITIES.get(role, ()):
            fn = getattr(cls, spec.handler_name, None)
            handlers[spec.action] = _scrub(str(inspect.signature(fn)), tmp) if callable(fn) \
                else "（类上没有这个方法）"
        specs = per_role[role].registry
        roles[role] = {
            "actions": actions,
            "edges": sorted(C.ALLOWED_EDGES.get(role, ())),
            "summonable": role not in C.NON_SUMMONABLE,
            "write_set": sorted(C.WRITE_SETS.get(role, frozenset())),
            "read_only": role in READ_ONLY_ROLES,
            "tools": specs.names(),
            "write_tools": sorted(s.name for s in (specs.get(n) for n in specs.names())
                                  if s.side_effect in SIDE_EFFECTS_WRITE),
            "prompt": _scrub(system_prompt(role, registry=full), tmp),
            "handler_signatures": handlers,
            "init_signature": _scrub(str(inspect.signature(cls.__init__)), tmp),
        }

    # 注入一个假 provider：A 的接线态是"有没有检索后端"的函数，不注入的话
    # `wiring_status` 会给 A 记 `no_provider`、`role_registry` 里干脆没有 A ——
    # 那样这一层就钉不住 A 的接线（与 `tests/test_host_wiring.py` 用 `[object()]` 同一手法）。
    reg = build_role_registry(st, providers=[object()])
    return {
        "roles": roles,
        "role_count": len(roles),
        "schema_roles": list(S.ROLES),
        "tool_roles": list(TOOL_ROLES),
        "read_only_roles": sorted(READ_ONLY_ROLES),
        "non_summonable": sorted(C.NON_SUMMONABLE),
        "wiring_status": dict(sorted(wiring_status(st, providers=[object()]).items())),
        "role_registry": {
            role: [type(x).__name__ for x in (v if isinstance(v, (list, tuple)) else [v])]
            for role, v in sorted(reg.items())
        },
    }


def test_the_surface_is_whole_and_not_vacuous() -> None:
    """反真空：九个角色、每角色都有工具与提示词、每条动作都有实现、条数不许缩水。

    没有这一条，一份"什么都没扫到"的快照也能当基线——那时"逐字不变"证明的是空集不变。

    动作总数这一格不再写死（原先写 `== 51`，2026-10-02 加两条动作时它就红了）：
    真正要防的"真空"是缩水，而"数字该是多少"由 `capabilities` 说话（§0.7 的标题
    是那个数字的文档落点，由 `tests/test_role_specs_action_table.py` 盯着）。所以这里：
    ① 与现场的 `CAPABILITIES` 逐数相等（快照没漏扫）；② 不许低于加动作之前的 54（不缩水）。
    """
    from agentflow import capabilities as C
    from agentflow import schema as S
    from agentflow.tools import READ_ONLY_ROLES, TOOL_ROLES

    with tempfile.TemporaryDirectory(prefix="agent-surface-") as td:
        snap = _snapshot(pathlib.Path(td))

    assert snap["role_count"] == 10, snap["role_count"]
    assert snap["schema_roles"] == list(S.ROLES) == list("ABCDEFGHV")
    total_actions = sum(len(v["actions"]) for v in snap["roles"].values())
    live_actions = sum(len(v) for v in C.CAPABILITIES.values())
    assert total_actions == live_actions, (
        f"快照扫到 {total_actions} 条动作，而现场 `CAPABILITIES` 是 {live_actions} 条"
        "（快照漏扫了某些角色）")
    assert total_actions >= 54, f"动作总数缩到 {total_actions} 条（加动作之前是 54）"
    # 边总数不写死（原先写 `== 32`）：真身是 `capabilities.ALLOWED_EDGES`，
    # 而它在"B/F/V 不许直连 M"（`draft/106` §2 口径 B）那批里被有意减掉了三条
    # ⇒ 写死的那个数变成了一句陈旧计数，判据随之恒红。与上面动作总数同一条纪律：
    # 数字从代码现算，判据只留一个防真空的下界。
    live_edges = sum(len(v) for v in C.ALLOWED_EDGES.values())
    assert sum(len(v["edges"]) for v in snap["roles"].values()) == live_edges, (
        f"快照扫到的边总数与现场 `capabilities.ALLOWED_EDGES`（{live_edges} 条）对不上"
        "（快照漏扫了某些角色的边）")
    assert live_edges >= 25, f"边总数缩到 {live_edges} 条 ⇒ 先查是不是扫了个空集"
    for role, got in snap["roles"].items():
        assert got["tools"], f"{role} 一个工具都没有"
        assert len(got["prompt"]) > 5000, f"{role} 的提示词只有 {len(got['prompt'])} 字符"
        if role in READ_ONLY_ROLES:
            assert not got["write_tools"], (
                f"只读角色 {role} 的工具面里有写工具：{got['write_tools']}")
        if role in C.CAPABILITIES:
            missing = [a for a, sig in got["handler_signatures"].items()
                       if sig == "（类上没有这个方法）"]
            assert not missing, f"{role} 的动作在类上找不到实现：{missing}"
    assert set(snap["role_registry"]) <= set(TOOL_ROLES)
    assert snap["wiring_status"], "接线态是空的"


#: 快照里逐字比较的顶层键（`roles` 单独按角色/字段展开报差异，见 `_differences`）。
_KEYS = ("roles", "role_count", "schema_roles", "tool_roles", "read_only_roles",
         "non_summonable", "wiring_status", "role_registry")


def _differences(golden: dict, live: dict) -> list[str]:
    """把"快照 ≠ 实跑"拆成人话（逐角色、逐字段、逐行指到第一个不同处）。"""
    bad: list[str] = []
    for key in _KEYS:
        if live[key] == golden.get(key):
            continue
        if key != "roles":
            bad.append(f"[{key}] 快照 {json.dumps(golden.get(key), ensure_ascii=False)[:240]}"
                       f" ≠ 实跑 {json.dumps(live[key], ensure_ascii=False)[:240]}")
            continue
        for role in sorted(set(golden["roles"]) | set(live["roles"])):
            g, l = golden["roles"].get(role, {}), live["roles"].get(role, {})
            for field in sorted(set(g) | set(l)):
                if g.get(field) == l.get(field):
                    continue
                gv = json.dumps(g.get(field), ensure_ascii=False)
                lv = json.dumps(l.get(field), ensure_ascii=False)
                where = next((f"第 {i + 1} 行" for i, (a, b) in
                              enumerate(zip(gv.split("\n"), lv.split("\n"))) if a != b), "整体")
                bad.append(f"[roles.{role}.{field}]（{where}）快照 {gv[:180]} ≠ 实跑 {lv[:180]}")
    return bad


def test_the_agent_surface_matches_the_frozen_snapshot() -> None:
    """核心判据：六层读数都必须与冻结快照逐字相同。"""
    if not GOLDEN.is_file():
        pytest.fail(f"快照不存在：{GOLDEN}\n"
                    "生成：python -B tests/test_agent_surface_snapshot.py --write（先看 diff 再提交）")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="agent-surface-") as td:
        live = _snapshot(pathlib.Path(td))

    bad = _differences(golden, live)
    assert not bad, ("agent 面与冻结快照不一致（模块化重构只许搬移，不许改声明/行为）：\n"
                     + "\n".join(bad))


def test_the_comparison_actually_sees_a_change() -> None:
    """负控：上面那条判据真的在比内容，不是"永远绿"。

    把快照里三处（动作表 / 提示词 / 接线）各改一个字节再喂给同一个比较函数，
    它必须分别报出来 —— 没有这一条，"快照不一致"与"比较函数坏了"分不开。
    """
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="agent-surface-") as td:
        live = _snapshot(pathlib.Path(td))
    assert not _differences(golden, live), "基线本身对不上 ⇒ 先跑 --write"

    def doctored(**mutations) -> dict:
        import copy

        g = copy.deepcopy(golden)
        for path, value in mutations.items():
            role, field = path.split("::") if "::" in path else (None, path)
            if role:
                g["roles"][role][field] = value
            else:
                g[field] = value
        return g

    assert _differences(doctored(**{"A::handler_signatures": {"run": "(self) -> 'dict'"}}), live), \
        "动作级签名被改坏了，比较函数没报"
    assert _differences(doctored(**{"C::prompt": golden["roles"]["C"]["prompt"] + "x"}), live), \
        "提示词被改坏了，比较函数没报"
    assert _differences(doctored(**{"wiring_status": {"B": "unwired"}}), live), \
        "接线态被改坏了，比较函数没报"


if __name__ == "__main__":  # pragma: no cover - 只在"面确实变了"时手动跑
    if "--write" not in sys.argv:
        print(__doc__)
        raise SystemExit(2)
    with tempfile.TemporaryDirectory(prefix="agent-surface-") as td:
        snap = _snapshot(pathlib.Path(td))
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                      encoding="utf-8", newline="\n")
    print(f"[ok] 写入快照：{GOLDEN}（{snap['role_count']} 个角色，"
          f"{sum(len(v['actions']) for v in snap['roles'].values())} 条动作）")
