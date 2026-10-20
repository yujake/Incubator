# -*- coding: utf-8 -*-
"""`AgentSpec` 与"今天的几处真相"的逐格对账（`goal-7f5116c1` M2 的判据）。

M2 只做"声明集中到角色自己的模块里"这一步，不接管真相：动作表还在 `capabilities.py`、
构造工厂还在 `host.py`。所以这一步的产物是"第二份声明与第一份逐格相等"的证据 ——
没有它，M3/M4 的接管就是在一个不知道对不对的基线上动刀。

对账的几处：`FACULTY_EMPHASIS` / `FACULTY_LOCAL`、`capabilities.ALLOWED_EDGES` / `WRITE_SETS`、
`tools.READ_ONLY_ROLES`、`capabilities.NON_SUMMONABLE`、以及"`host` 真的会构造出哪个类"。

## 唯一化之后：六格 brief 不再对账（业主 2026-10-11）

原判据还比六格 brief（`duty`/`boundary`/`policy`/`signature_error`/`deliverable`/`stance`）：
`spec.brief` vs `agent_prompts.ROLE_BRIEFS[role]`。业主裁定「保证文本唯一性」+
「I-1 `specs/<role>.py::SPEC.brief` 是唯一真身；`agent_prompts.ROLE_BRIEFS` 改成它的视图」之后，
两者是同一个对象 ⇒ 那一半成了恒真的假绿，按裁定删掉（不是改成别的东西：
它要守的"两份会漂"这件事在唯一化之后不存在了）。
一句话口径：一条判据在它守的东西消失之后仍然亮绿，就是假绿 —— 本仓对死判据一贯是删。
"""
from __future__ import annotations

import dataclasses
import pathlib
import tempfile

import pytest

from agentflow import agent_prompts as AP
from agentflow import capabilities as C
from agentflow.agentspec import AgentRegistry, AgentSpec, builtin_registry
from agentflow.host import build_role_registry
from agentflow.store import Store
from agentflow.tools import READ_ONLY_ROLES, TOOL_ROLES


def _mismatches(spec: AgentSpec) -> list[str]:
    """一份 spec 与今天几处真相不一致的地方（空列表 = 逐格相等）。

    六格 brief（`duty`/`boundary`/`policy`/`signature_error`/`deliverable`/`stance`）
    不在这里比：业主 2026-10-11 裁定"保证文本唯一性"之后，`agent_prompts.ROLE_BRIEFS`
    已经是 `spec.brief` 的视图（`agent_prompts.py` 的 `ROLE_BRIEFS` 那一段），
    再比就是"同一对象与自己比" —— 一条恒真的假绿。那一半判据按同一裁定删掉了
    （见模块 docstring 的"唯一化之后"一节）。
    """
    role = spec.role
    out: list[str] = []
    if dict(spec.emphasis) != dict(AP.FACULTY_EMPHASIS[role]):
        out.append(f"emphasis：spec {sorted(spec.emphasis.items())} ≠ 真相 "
                   f"{sorted(AP.FACULTY_EMPHASIS[role].items())}")
    truth_notes = {f: t for (r, f), t in AP.FACULTY_LOCAL.items() if r == role}
    if dict(spec.local_notes) != truth_notes:
        got, want = set(spec.local_notes), set(truth_notes)
        out.append(f"local_notes：多 {sorted(got - want)} / 少 {sorted(want - got)}")
    if spec.read_only != (role in READ_ONLY_ROLES):
        out.append(f"read_only：spec {spec.read_only} ≠ 真相 {role in READ_ONLY_ROLES}")
    if spec.summonable != (role not in C.NON_SUMMONABLE):
        out.append(f"summonable：spec {spec.summonable} ≠ 真相 {role not in C.NON_SUMMONABLE}")
    if tuple(spec.edges) != tuple(sorted(C.ALLOWED_EDGES.get(role, ()))):
        out.append(f"edges：spec {spec.edges} ≠ 真相 {tuple(sorted(C.ALLOWED_EDGES.get(role, ())))}")
    if frozenset(spec.write_set) != frozenset(C.WRITE_SETS.get(role, frozenset())):
        out.append(f"write_set：spec {sorted(spec.write_set)} ≠ 真相 "
                   f"{sorted(C.WRITE_SETS.get(role, frozenset()))}")
    return out


def test_every_spec_matches_the_six_places_that_define_it_today() -> None:
    """主判据：九个角色的每一格都必须与今天的真相逐字相等。"""
    reg = builtin_registry()
    bad: list[str] = []
    for role in reg.roles():
        bad += [f"[{role}] {m}" for m in _mismatches(reg.get(role))]
    assert not bad, ("AgentSpec 与今天的真相不一致（M2 只搬声明，不许出现第二种值）：\n"
                     + "\n".join(bad))


def test_the_registry_is_not_vacuous() -> None:
    """反真空：十个角色都在、每格都有内容、总数与今天一致。"""
    reg = builtin_registry()
    assert reg.roles() == tuple(TOOL_ROLES), reg.roles()
    assert len(reg.roles()) == 10
    assert reg.read_only_roles() == ("C", "H", "V"), reg.read_only_roles()
    assert "M" not in reg.summonable_roles()
    assert sum(len(v) for v in reg.edges().values()) == 34, (
        # 2026-10-19 业主裁定：C→D 用于把候选路径交给 D 立猜想（33 → 34）。
        "边总数：2026-10-19 业主裁定「C→D 用于把候选路径交给 D 立猜想」（33 → 34）；"
        "2026-10-10 裁定第 4 条去掉 M→B / M→F / M→V 三条（32 → 29）；"
        "2026-10-13 业主裁定「允许 B 唤起 V。理由是 B 需要初步检验收录的证明」（29 → 30）；"
        "2026-10-13 业主裁定「补 M 到 B」（30 → 31）；"
        "2026-10-14 业主裁定「允许 B 和 H 协作，B 唤起 H」＋「回验……保持语义相同即可」（31 → 32）；"
        "2026-10-18 业主裁定「给 M 开 V 出边」（32 → 33，`projects/t3d` 三·1："
        "`reviewed_proof_rows = 0`，V 只能经 F→V）；"
        "文档那一份在 docs/ROLE-SPECS.md §0.5"
    )
    for role in reg.roles():
        spec = reg.get(role)
        assert spec.brief.duty, f"{role} 没有职责一句"
        assert spec.brief.boundary, f"{role} 没有边界"
        assert len(spec.emphasis) == 10, f"{role} 的官能轻重只有 {len(spec.emphasis)} 项"
        assert spec.local_notes, f"{role} 没有自己那几句话"
        assert spec.class_path and ":" in spec.class_path
        assert spec.cls() is not None


def test_the_class_path_is_what_host_actually_builds() -> None:
    """`class_path` 不是自己写的字符串：`host` 的工厂真的会构造出同一个类对象。

    判据比的是身份（`spec.cls() is type(inst)`），不是 `type(inst).__module__` ——
    `goal-7f5116c1` M6 把 `agent_c.py` 拆成包之后，类的 `__module__` 变成了
    `agentflow.agent_c.core`，而 `class_path` 仍然是 `agentflow.agent_c:AgentC`
    （包的入口再导出它）。两者指向同一个对象，这才是要钉的事：
    "spec 说的那个类"与"host 造出来的那个类"必须是一个。
    """
    reg = builtin_registry()
    with tempfile.TemporaryDirectory(prefix="agent-spec-") as td:
        ws = pathlib.Path(td) / "ws"
        ws.mkdir(parents=True)
        st = Store(ws)
        st.init()
        factories = build_role_registry(st, providers=[object()], workspace_root=ws)
        assert set(factories) == set(reg.roles()) - {"M"}, sorted(factories)
        for role, (_kind, factory) in sorted(factories.items()):
            inst = factory(store=st)
            assert reg.get(role).cls() is type(inst), (
                f"{role}：spec 写的是 {reg.get(role).class_path}"
                f"（解析到 {reg.get(role).cls()}），host 构造的是 {type(inst)}")


def test_the_reconciliation_catches_a_drifted_spec() -> None:
    """负控：主判据真的在比内容 —— 把 spec 的每一类还在对账的格子各改一格，它都必须报出来。

    刻意不再包含 `brief=...` 那一档：六格 brief 唯一化之后没有"第二份"可漂
    （见模块 docstring 的"唯一化之后"一节），拿它做漂移等于伪造一个不可能发生的形态。
    """
    reg = builtin_registry()
    spec = reg.get("A")
    drift = [
        dataclasses.replace(spec, edges=("B", "Z")),
        dataclasses.replace(spec, read_only=True),
        dataclasses.replace(spec, summonable=False),
        dataclasses.replace(spec, write_set=frozenset({"literature"})),
        dataclasses.replace(spec, emphasis={**spec.emphasis, "眼睛": "minor"}),
        dataclasses.replace(spec, local_notes={}),
    ]
    for bad_spec in drift:
        assert _mismatches(bad_spec), f"这一类漂移没被抓住：{bad_spec!r:.120}"

    # 注册表本身的两条不变式：重复登记必须炸（否则"哪一份是真的"变成运气）
    one = AgentRegistry()
    one.add(spec)
    with pytest.raises(ValueError):
        one.add(spec)
    with pytest.raises(KeyError):
        one.get("Z")


# ---------------------------------------------------------------- `specs/` 与 FC-27 清单


def _manifest_rows(manifest_text: str) -> set[str]:
    """清单里的条目路径（第一栏；`[category: …]` 那一段之后的理由不参与比对）。"""
    out: set[str] = set()
    for line in manifest_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "[category:" not in stripped:
            continue
        if stripped.startswith("[category:"):     # 分组头
            continue
        out.add(stripped.split()[0])
    return out


def _unregistered_specs(manifest_text: str, specs_dir: pathlib.Path) -> list[str]:
    """`specs/` 下没有在清单里的文件（返回项目根相对路径，便于直接贴进清单）。"""
    rows = _manifest_rows(manifest_text)
    out = []
    for path in sorted(specs_dir.glob("*.py")):
        rel = f"src/agentflow/specs/{path.name}"
        if rel not in rows:
            out.append(rel)
    return out


def test_every_spec_file_is_registered_in_the_fc27_manifest() -> None:
    """`specs/` 下每个文件都必须在 FC-27 清单里（`M3` 用 glob 行被打回后留下的那个洞）。

    为什么必须是逐文件的行：`tests/test_noai_gate.py::test_manifest_globs_point_at_real_files`
    要求每一行指向真实存在的文件；而保护面若漏掉一个文件，改权限面就可以不碰禁改区。
    这条判据把"新增一个角色时忘了加清单"变成红 —— 它是 M3/§222 留的那条尾巴。
    """
    proj = pathlib.Path(__file__).resolve().parents[1]
    manifest = (proj / ".noai-paths").read_text(encoding="utf-8")
    missing = _unregistered_specs(manifest, proj / "src" / "agentflow" / "specs")
    assert not missing, (
        "这些 specs 文件不在 `.noai-paths` 里（权限面的落点必须逐文件受保护）：\n  - "
        + "\n  - ".join(missing))


def test_the_manifest_coverage_judge_catches_a_missing_row() -> None:
    """负控：从清单里删掉一行 ⇒ 同一个检查函数必须报出来（否则它是恒真的）。"""
    proj = pathlib.Path(__file__).resolve().parents[1]
    manifest = (proj / ".noai-paths").read_text(encoding="utf-8")
    specs_dir = proj / "src" / "agentflow" / "specs"
    assert _unregistered_specs(manifest, specs_dir) == [], "基线本身就不全"
    dropped = "\n".join(ln for ln in manifest.splitlines()
                        if not ln.startswith("src/agentflow/specs/d.py"))
    assert dropped != manifest
    assert _unregistered_specs(dropped, specs_dir) == ["src/agentflow/specs/d.py"]
