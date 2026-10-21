# -*- coding: utf-8 -*-
"""工具面的冻结快照（`draft/36` 的 T-8 第 ① 条：动声明数据之前先钉住整张面）。

`T-8` 要动的是 `tools/*.py::register` 里的声明数据 —— 而工具面就是权限面
（`AGENTS.md` 把 `capabilities.py` / `tools/base.py` / `tools/__init__.py` 划进禁改区，
理由正是"改它等于改权限面"）。所以先立尺子：把"今天这张面长什么样"钉成可比较的一份数据。

## 钉住的四层（`draft/36` 给的验收是"工具总数与逐角色面逐字不变"，这里把它拆细）

1. 装配摘要：`build_registry().summary()` —— 工具名全集 / 总数 / 已装模块 / 跳过的模块 /
   `params_checked`（`N-5` 的参数面覆盖率读数：它若不等于工具总数，说明"零违反"是真空的）。
2. 逐工具声明：`ToolSpec.to_dict()` 全字段（名字 / 摘要 / 参数 schema / 副作用 /
   外部性 / 是否需审批 / 角色 / 返回形状）+ 处理器签名（模型看到的就是这两个）。
3. 逐角色面：`TOOL_ROLES` 九个角色各自的工具名单（排序后）+ 只读角色 C/H 的写工具泄漏表。
4. `tools` 子命令的 stdout：`agentflow tools` / `--json` / `--role A`…`--role H`
   —— 这正是 `draft/36` 里 T-8 写的那条判据（"`tools --role X` 输出 diff 为空"）。
   `--role M` 在 CLI 上不可达（argparse 的 choices 是 A–H），所以主控的面靠第 3 条钉。

## 重新生成

```powershell
cd D:\\Incubator\\agentflow
$env:PYTHONUTF8='1'; python -B tests/test_tool_surface_snapshot.py --write
```
生成之后先看 diff：差在哪、为什么。这条命令只该在"权限面确实变了"时用。

⚠️ **环境要和判据同一套**（2026-10-13 实测踩到，与 `test_agent_surface_snapshot.py` 同因）：
`tests/conftest.py` 在导入期把 `AGENTFLOW_LEAN_ENABLED` 钉成 "1"，而工具摘要里
（例如 `verify.check_formal`）就写着形式化开/关的口径。直接重生成会写出一份判据不认的基线。
所以本文件在导入 agentflow 之前自己钉上同一个开关。
"""
from __future__ import annotations

import contextlib
import inspect
import io
import json
import os
import pathlib
import re
import sys
import tempfile

#: 先钉开关，再导入 agentflow（理由见上面 docstring 末尾那一段）。
os.environ.setdefault("AGENTFLOW_LEAN_ENABLED", "1")

import pytest

GOLDEN = pathlib.Path(__file__).resolve().parent / "golden" / "tool_surface_snapshot.json"

#: 对象地址（`<object object at 0x…>`）是内存里的位置，不是声明面的一部分：
#: `review.scan_document` 的形参默认值是一个哨兵对象，它的 repr 带地址 ⇒ 每次都不同。
#: 与临时目录路径同理，钉住它只会让快照每次都红（`_ADDR` 把它遮成 `0x…`）。
_ADDR = re.compile(r"0x[0-9a-fA-F]+")


def _scrub(text: str) -> str:
    return _ADDR.sub("0x…", text)


def _build(tmp: pathlib.Path, roles: tuple[str, ...] | None = None):
    """在临时工作区里装配整张工具面（离线；不碰仓库里的任何工作区）。

    `roles` 缺省是 `ROLES`（A–H）—— 与 `agentflow tools` 这条命令同一个口径，
    因为那条命令的 stdout 就是 `draft/36` 里 T-8 写下的验收判据。
    """
    from agentflow.store import Store
    from agentflow.tools import ROLES, build_registry

    ws = tmp / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    # `strict=True`：任何模块被跳过都抛异常 —— 一份"少装了一半工具"的快照不该被当成基线。
    return build_registry(store=st, workspace_root=ws,
                          roles=tuple(ROLES if roles is None else roles), strict=True)


def _snapshot(tmp: pathlib.Path) -> dict:
    from agentflow.cli import main
    from agentflow.tools import READ_ONLY_ROLES, SIDE_EFFECTS_WRITE, TOOL_ROLES

    build = _build(tmp)
    reg = build.registry
    specs = [reg.get(n) for n in reg.names()]
    # 同一张面在 `roles=TOOL_ROLES`（含主控 M）下的样子：`fs_tools` / `table_tools`
    # 的 roles 是装配时注入的（`_effective_roles`），所以 M 在两种口径下不一样。
    # 这不是缺陷，是"声明式工具 vs 注入式工具"的分界 —— 钉住它，免得有人以为 M 的面漂了。
    with_m = _build(tmp, roles=tuple(TOOL_ROLES)).registry

    cli: dict[str, str] = {}
    for label, extra in [("", []), ("--json", ["--json"])] + \
            [(f"--role {r}", ["--role", r]) for r in "ABCDEFGHV"]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(["--root", str(tmp / "ws"), "tools", *extra])
        assert code == 0, f"`agentflow tools {label}` 退出码 {code}"
        cli[label] = _scrub(buf.getvalue().replace(str(tmp), "<TMP>"))

    return {
        "summary": build.summary(),
        "declarations": {s.name: s.to_dict() for s in specs},
        "signatures": {s.name: _scrub(str(inspect.signature(s.handler))) for s in specs},
        "roles": {r: sorted(s.name for s in reg.for_role(r)) for r in TOOL_ROLES},
        "roles_with_m": {r: sorted(s.name for s in with_m.for_role(r)) for r in TOOL_ROLES},
        "readonly_write_leaks": {
            r: sorted(s.name for s in reg.for_role(r) if s.side_effect in SIDE_EFFECTS_WRITE)
            for r in READ_ONLY_ROLES
        },
        "cli": cli,
    }


def test_the_surface_is_whole_and_not_vacuous() -> None:
    """反真空：面必须是"装全了"的，各角色都拿得到东西，参数面判据真的走过了每个工具。

    没有这一条，一份"装配时全跳过了"的快照也能当基线 —— 那时"逐字不变"证明的是空集不变。
    """
    with tempfile.TemporaryDirectory(prefix="tools-snapshot-") as td:
        build = _build(pathlib.Path(td))
        reg = build.registry
        assert not build.skipped, f"有模块被跳过（快照不完整）：{build.skipped}"
        assert len(build.loaded) >= 10, f"只装了 {len(build.loaded)} 个模块：{build.loaded}"
        assert len(reg) >= 60, f"工具总数只有 {len(reg)} —— 面不完整"
        assert build.params_checked == len(reg), (
            f"参数面判据只走过 {build.params_checked} / {len(reg)} 个工具 ⇒ "
            "『零违反』是真空的（`N-5`）")
        from agentflow.tools import READ_ONLY_ROLES, SIDE_EFFECTS_WRITE, TOOL_ROLES

        for role in TOOL_ROLES:
            assert reg.for_role(role), f"角色 {role} 一个工具都没有"
            for spec in reg.for_role(role):
                assert spec.params and spec.summary and spec.returns, (
                    f"{role} / {spec.name} 的声明缺字段 ⇒ 快照钉不住东西")
        for role in READ_ONLY_ROLES:
            leaks = [s.name for s in reg.for_role(role) if s.side_effect in SIDE_EFFECTS_WRITE]
            # 2026-10-17（业主裁定「方案 1」）：只读角色**自己的落库代理**是允许的
            from agentflow.tools.base import READONLY_CALL_EXCEPTIONS as _EXC
            _ex = {n for n, _w in _EXC.get(role, ())}
            leaks = [n for n in leaks if n not in _ex]
            assert not leaks, f"只读角色 {role} 拿到写工具：{leaks}"
        # 注入式那一层还活着：`roles=TOOL_ROLES` 时主控多拿到的正是 `fs.*` / `table.*`
        # （`fs_tools._effective_roles` 把装配时的角色集合注进声明）。
        # 两边一旦相等，说明那条注入路径没了 —— 那种"面悄悄变窄"不该无声无息地过去。
        with_m = _build(pathlib.Path(td), roles=tuple(TOOL_ROLES))
        assert set(s.name for s in with_m.registry.for_role("M")) > \
            set(s.name for s in reg.for_role("M")), \
            "`roles=TOOL_ROLES` 与 `roles=ROLES` 的主控面相同 ⇒ 注入式角色那条路断了"


def test_the_tool_surface_matches_the_frozen_snapshot() -> None:
    """核心判据：装配摘要 / 逐工具声明 / 逐角色面 / CLI stdout，都必须与冻结快照逐字相同。"""
    if not GOLDEN.is_file():
        pytest.fail(f"快照不存在：{GOLDEN}\n"
                    "生成：python -B tests/test_tool_surface_snapshot.py --write（先看 diff 再提交）")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="tools-snapshot-") as td:
        live = _snapshot(pathlib.Path(td))

    bad: list[str] = []
    for key in ("summary", "roles", "roles_with_m", "readonly_write_leaks"):
        if live[key] != golden.get(key):
            bad.append(f"[{key}] 快照 {json.dumps(golden.get(key), ensure_ascii=False)[:300]} ≠ "
                       f"实跑 {json.dumps(live[key], ensure_ascii=False)[:300]}")
    for name in sorted(set(golden["declarations"]) | set(live["declarations"])):
        g, l = golden["declarations"].get(name), live["declarations"].get(name)
        if g != l:
            diff = [k for k in sorted(set(g or {}) | set(l or {})) if (g or {}).get(k) != (l or {}).get(k)]
            bad.append(f"[declarations.{name}] 有差异的字段 {diff}")
        if golden["signatures"].get(name) != live["signatures"].get(name):
            bad.append(f"[signatures.{name}] 快照 {golden['signatures'].get(name)} ≠ "
                       f"实跑 {live['signatures'].get(name)}")
    for label in sorted(set(golden["cli"]) | set(live["cli"])):
        if golden["cli"].get(label) != live["cli"].get(label):
            g = (golden["cli"].get(label) or "").splitlines()
            l = (live["cli"].get(label) or "").splitlines()
            first = next((f"第 {i+1} 行：{a!r} ≠ {b!r}" for i, (a, b) in enumerate(zip(g, l)) if a != b),
                         f"行数 {len(g)} ≠ {len(l)}")
            bad.append(f"[cli {'(无参数)' if not label else label}] {first}")
    assert not bad, ("工具面与冻结快照不一致（T-8 只许搬移声明数据，不许改声明）：\n"
                     + "\n".join(bad))


if __name__ == "__main__":  # pragma: no cover - 只在"权限面确实变了"时手动跑
    if "--write" not in sys.argv:
        print(__doc__)
        raise SystemExit(2)
    with tempfile.TemporaryDirectory(prefix="tools-snapshot-") as td:
        snap = _snapshot(pathlib.Path(td))
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                      encoding="utf-8", newline="\n")
    print(f"[ok] 写入快照：{GOLDEN}（{len(snap['declarations'])} 个工具 / "
          f"{len(snap['roles'])} 个角色 / {len(snap['cli'])} 条 CLI 输出）")
