"""`docs/ROLE-SPECS.md` 的结构完整性门 + 与实时工具普查的对账。

## 这个文件在测什么，为什么它值得存在

用户对正式版的要求里有两条是文档要求：

1. "为 A–H 八个角色各写详细规格说明书"，并逐字点名了小节
   （职责 / 明确不负责 / 逐个工具的契约 / 状态机 / 预算与终止 / 三态与失败模式 / 不变式 / 接口）；
2. 审计判据里有 "docstring 与实现一致"。

一份 2000+ 行的规格最容易的坏法不是写错，而是写漏 —— 少写一节，没有任何东西会变红，
而读者会以为"这一节大概没有那些内容"。本文件把"写漏"变成红点。

## 三态（本文件的负控重点）

`tools/verify_role_specs.py` 有三个结论，本文件对三个都有断言：

- `ok`（结构完整）/ `incomplete`（查过、有缺失）/ `unknown`（没查成：文档不存在、
  读不到、或一个角色节都没匹配到）。

`unknown` 绝不能等于 `ok` —— 文档被改名或格式被改坏时，
"什么都没读到"必须报"没查成"，而不是"通过"。这是本项目反复踩过的坑
（`DEVELOPMENT.md` §3 纪律 1）。
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "ROLE-SPECS.md"
#: N/O/Q 三角色的草稿（登记前不进 `docs/ROLE-SPECS.md`，由 `--roles` 单独查）。
DRAFT_NOQ = REPO / "docs" / "ROLE-SPECS-DRAFT-N-O-Q.md"


def _load_gate():
    """按路径导入 `tools/verify_role_specs.py`（`tools/` 不是包）。"""
    spec = importlib.util.spec_from_file_location(
        "_verify_role_specs_under_test", REPO / "tools" / "verify_role_specs.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


G = _load_gate()


# ============================================================ 正向：真实文档


def test_real_role_specs_are_structurally_complete():
    """正向：真实文档里 9 个角色节（A–H + M）各 8 个必备子节齐全，顺序也对。"""
    result = G.check(DOC)
    assert result["verdict"] == "ok", result["reason"]
    assert [s["role"] for s in result["sections"]] == list(G.EXPECTED_ROLES)


def test_every_role_section_has_ten_numbered_subsections():
    """正向：每节 10 个编号子节（8 个必备 + 「一句话定位」+「自检入口」）。"""
    result = G.check(DOC)
    bad = {s["role"]: s["subsections"] for s in result["sections"] if s["subsections"] < 10}
    assert not bad, f"这些角色节的编号子节少于 10 个：{bad}"


def test_cli_gate_exits_zero_on_the_real_document():
    """端到端：门脚本本身以退出码 0 结束（不是只有函数返回对）。"""
    p = subprocess.run(
        [sys.executable, str(REPO / "tools" / "verify_role_specs.py")],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )
    assert p.returncode == 0, p.stdout + p.stderr


# ============================================================ 负控：三态都必须可达


def _mutate(tmp_path: Path, transform) -> Path:
    lines = DOC.read_text(encoding="utf-8").splitlines()
    out = tmp_path / "ROLE-SPECS.md"
    out.write_text("\n".join(transform(lines)), encoding="utf-8")
    return out


def test_negative_control_missing_subsection_is_incomplete(tmp_path):
    """负控（最关键的一条）：删掉某角色的「明确不负责」子节 ⇒ 必须报 `incomplete`。

    没有这一条，这道门就可能是"永远通过"的橡皮图章 —— 而永远通过的文档门
    比没有文档门更糟（它把"没人检查"伪装成"检查过了"）。
    """
    def drop(lines: list[str]) -> list[str]:
        return [ln for ln in lines if not ln.startswith("### D.3 明确不负责")]

    result = G.check(_mutate(tmp_path, drop))
    assert result["verdict"] == "incomplete"
    assert any("D" in p and "不负责" in p for p in result["reason"].split("；")), result["reason"]


def test_negative_control_dropped_role_is_incomplete(tmp_path):
    """负控：整个角色节被删掉 ⇒ `incomplete`（且原因里点名集合不符）。"""
    def drop(lines: list[str]) -> list[str]:
        out, skipping = [], False
        for ln in lines:
            if ln.startswith("## G "):
                skipping = True
            elif ln.startswith("## ") and skipping:
                skipping = False
            if not skipping:
                out.append(ln)
        return out

    result = G.check(_mutate(tmp_path, drop))
    assert result["verdict"] == "incomplete"
    assert "期望" in result["reason"]


def test_negative_control_doc_without_role_headings_is_unknown_not_ok(tmp_path):
    """负控（三态的核心）：一个角色节都匹配不到 ⇒ `unknown`，不是 `ok`。

    这是"文档被改名 / 格式被改坏"的形态。把它报成 `ok` 就是把"没查成"
    读成"结构完整" —— 本项目最贵的那类静默兜底。
    """
    bad = tmp_path / "ROLE-SPECS.md"
    bad.write_text("# 一份别的东西\n\n没有任何角色节标题。\n", encoding="utf-8")
    result = G.check(bad)
    assert result["verdict"] == "unknown"


def test_negative_control_missing_document_is_unknown_not_ok(tmp_path):
    """负控：文档不存在 ⇒ `unknown`（路径写错时必须报"没查成"）。"""
    result = G.check(tmp_path / "does-not-exist.md")
    assert result["verdict"] == "unknown"


def test_gate_exit_codes_are_three_valued(tmp_path):
    """端到端：三个结论对应三个不同的退出码（`ok`=0 / `incomplete`=1 / `unknown`=2）。"""
    ok = subprocess.run([sys.executable, str(REPO / "tools" / "verify_role_specs.py"), "--json"],
                        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=120)
    assert ok.returncode == 0
    assert json.loads(ok.stdout)["verdict"] == "ok"

    root = tmp_path / "empty"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "ROLE-SPECS.md").write_text("# 空\n", encoding="utf-8")
    unknown = subprocess.run(
        [sys.executable, str(REPO / "tools" / "verify_role_specs.py"), "--root", str(root)],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )
    assert unknown.returncode == 2, unknown.stdout + unknown.stderr


# ============================================================ --roles / --doc（可选参数）


def test_default_role_set_is_unchanged_and_blind_to_n_o_q():
    """默认行为一字不变：不传 `--roles` 时判据仍是 A–H + M。

    这条同时是缺口本身的记录：草稿里的 N/O/Q 节在默认判据下一个都匹配不到，
    于是门报 `unknown`（"没查成"）而不是"发现三个新角色缺规格"。
    新角色登记后若没有人显式传 `--roles`，这道门就看不见它们。
    """
    assert G.EXPECTED_ROLES == ("A", "B", "C", "D", "E", "F", "G", "H", "M")
    assert G.DEFAULT_ROLES is None
    default = G.check(DRAFT_NOQ)
    assert default["verdict"] == "unknown"
    assert default["sections"] == [], "默认判据不该看见 N/O/Q"
    assert G.check(DOC)["roles"] == list(G.EXPECTED_ROLES)


def test_cli_roles_flag_checks_the_n_o_q_draft():
    """正向：`--roles N,O,Q --doc <草稿>` ⇒ 三个角色节各 8 个必备子节齐全，退出码 0。"""
    p = subprocess.run(
        [sys.executable, str(REPO / "tools" / "verify_role_specs.py"),
         "--roles", "N,O,Q", "--doc", "docs/ROLE-SPECS-DRAFT-N-O-Q.md", "--json"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    data = json.loads(p.stdout)
    assert data["verdict"] == "ok", data["reason"]
    assert [s["role"] for s in data["sections"]] == ["N", "O", "Q"]


def test_cli_roles_flag_can_report_the_draft_as_incomplete(tmp_path):
    """负控（有牙）：在草稿的副本上删掉 `O.3 明确不负责` ⇒ 传了 `--roles` 门必须报 `incomplete`。

    没有这一条，"`--roles` 能检查那份草稿"就只是"门退 0"——而退 0 也可能因为
    它其实把整份文档跳过了（`unknown` 与 `ok` 混淆是同一族的假绿）。
    """
    body = DRAFT_NOQ.read_text(encoding="utf-8").replace("### O.3 明确不负责", "### O.3 别的")
    doc = tmp_path / "draft.md"
    doc.write_text(body, encoding="utf-8")
    result = G.check(doc, roles=("N", "O", "Q"))
    assert result["verdict"] == "incomplete", result["reason"]
    assert any("O" in p and "不负责" in p for p in result["reason"].split("；")), result["reason"]


def test_cli_roles_flag_rejects_a_malformed_role_set(tmp_path):
    """负控：`--roles` 写法非法时不许静默回落到默认集合，必须明确报错并退非零。

    否则 `--roles N;O;Q`（打错分隔符）会变成"用默认集合查了另一份东西"的假绿。
    """
    p = subprocess.run(
        [sys.executable, str(REPO / "tools" / "verify_role_specs.py"),
         "--roles", "N;O;Q", "--doc", "docs/ROLE-SPECS-DRAFT-N-O-Q.md"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )
    assert p.returncode == 2, p.stdout + p.stderr
    assert "--roles 非法" in (p.stdout + p.stderr)

    missing_doc = subprocess.run(
        [sys.executable, str(REPO / "tools" / "verify_role_specs.py"),
         "--roles", "N,O,Q", "--doc", "docs/no-such-draft.md"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )
    assert missing_doc.returncode == 2, "文档不存在必须是 unknown(2)，不是通过"
    assert G.check(tmp_path / "gone.md", roles=("N",))["verdict"] == "unknown"


# ============================================================ 与实时普查对账


def test_role_tool_counts_in_the_doc_match_the_live_census():
    """正向（文档 ↔ 实现一致）：文档每节标题里的工具条数 == `cli tools` 的实测普查。

    这条断言的价值全在"实测"两个字：硬编码一份 `{'A':20,…}` 只会把测试绑死在
    当前状态上（任何正当的工具增减都会让它红，而红了之后人会去改数字而不是看文档）。
    所以这里真的跑一次 `python -m agentflow.cli tools` 并解析它的输出 ——
    于是"文档里写的条数"与"实际能拿到几个工具"由同一次运行保证一致。
    """
    p = subprocess.run(
        [sys.executable, "-m", "agentflow.cli", "tools"],
        cwd=str(REPO / "src"), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300,
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )
    assert p.returncode == 0, p.stdout + p.stderr
    line = next(ln for ln in p.stdout.splitlines() if "各角色工具数" in ln)
    census = json.loads(re.search(r"\{.*\}", line).group(0).replace("'", '"'))

    result = G.check(DOC)
    # 文档标题里每一节可能读到多个数字（例如 §C 提到"两层"与"17"），
    # 所以判据是"普查的那个数在该节读到的数字集合里"，而不是"恰好只有一个数字"。
    bad: dict[str, str] = {}
    for s in result["sections"]:
        role = s["role"]
        if role not in census:  # M 不进普查
            continue
        if census[role] not in s["tool_counts_in_titles"]:
            bad[role] = f"普查 {census[role]}，文档标题里读到 {s['tool_counts_in_titles']}"
    assert not bad, f"文档与实测普查不一致：{bad}"


def test_unknown_role_in_census_would_be_caught(tmp_path):
    """负控：把文档里 A 的条数改错 ⇒ 上面那条对账会红（证明它有牙）。"""
    def bump(lines: list[str]) -> list[str]:
        return [ln.replace("工具面（20 个，实测）", "工具面（21 个，实测）")
                if ln.startswith("### A.4") else ln for ln in lines]

    doc = _mutate(tmp_path, bump)
    result = G.check(doc)
    assert 20 not in result["counts_by_role"]["A"] and 21 in result["counts_by_role"]["A"]


# ============================================================ 逐个工具的契约


def _registered_tool_names() -> list[str]:
    """从真实装配里取全部工具名（与 `cli tools` 用的是同一条路径）。

    为什么不解析 `cli tools` 的 stdout：那个命令默认只打印各角色的条数，
    要拿 55 个名字得逐个角色跑一次并解析。直接调 `build_registry` 更直接，
    而且它与 `cli.cmd_tools:335` 是同一个调用（含 `roles=tuple(ROLES)`）。
    """
    import os
    import tempfile
    sys.path.insert(0, str(REPO / "src"))
    from agentflow import store as _store  # noqa: PLC0415
    from agentflow.tools import ROLES, build_registry  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="role_specs_reg_") as td:
        st = _store.Store(Path(td))
        st.init()
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        build = build_registry(store=st, workspace_root=Path(td), roles=tuple(ROLES))
        return sorted(build.registry.names())


def test_every_registered_tool_has_a_contract_row_in_role_specs():
    """正向（逐个工具的契约）：装配出来的每一个工具都必须在 `ROLE-SPECS.md` 里出现。

    用户点名要"逐个工具的契约"。一份"工具总表"最容易的坏法是漏行 ——
    新增一个工具而忘了写进去，没有任何东西会变红，而读文档的人会以为
    "这个工具大概不需要契约"。这条断言把"漏行"变成红点。

    它判的是"名字出现过"，不判那一行写得好不好（后者只能人看）。
    假阴性在哪：把工具名写进一句无关的话里也能通过；代价是它永远不会误报 ——
    对一条"防漏行"的门来说，这个方向是对的（宁可漏报，不要假报警）。
    """
    doc = DOC.read_text(encoding="utf-8")
    names = _registered_tool_names()
    assert names, "装配出 0 个工具 —— 这不是'契约齐全'，而是没查成"
    missing = [n for n in names if f"`{n}`" not in doc]
    assert not missing, f"这些工具在 docs/ROLE-SPECS.md 里找不到契约行：{missing}"


def test_tool_count_in_the_gate_matches_the_live_census():
    """正向（文档 ↔ 实现一致）：`ROLE-SPECS.md` §R0 标题里的工具总数 == 实时装配数。

    这条与上面那条互补：上面查"每个工具都有行"，这条查"总数没写错"。
    两条一起才能挡住"删了一个工具的契约行、但总数没改"与"加了工具、总数没改"两种漏法。
    """
    doc = DOC.read_text(encoding="utf-8")
    m = re.search(r"##\s*R0\.\s*全局工具总表（(\d+)\s*个", doc)
    assert m, "§R0 的标题里读不出工具总数 —— 判据本身失效了（没查成，不是通过）"
    stated = int(m.group(1))
    names = _registered_tool_names()
    assert stated == len(names), f"§R0 说 {stated} 个，实时装配是 {len(names)} 个"


# ============================================================ §R0 三列 ↔ 实时注册表


def _r0_rows() -> list[dict[str, str]]:
    """解析 §R0 的 55 行表，取出机械可比的三列：`side_effect` / 审批 / roles。

    只解析这三列是刻意的：它们是机器可判定的（注册表里有同名事实）。
    其余列（summary / 参数 / 返回结构 / 已知问题）是人写给人看的，
    机械比对只会制造假报警 —— 而假报警会训练人忽略整张表（`DEVELOPMENT.md` §6 的 P15）。

    解析必须只取紧挨着表头的那张连续表：`§R0.2` 小节里还有别的表，
    其中一行的第 2 列是 `` `agent_c.py:2538-2737` ``（那是"代码位置"而不是工具名）——
    把子小节的表一起扫进来会得到一条名叫 `agent_c.py:2538-2737` 的假工具，
    然后在下游 `registry.get()` 上炸。第一版就是这么错的，所以这里按"表头 + 连续 `|` 行"取。
    """
    lines = DOC.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("| # | 工具 |"))
    rows: list[dict[str, str]] = []
    for line in lines[start + 1:]:
        if not line.startswith("|"):
            break                      # 表结束 —— 后面的小节是别的表
        if set(line) <= set("|-: "):
            continue                   # 分隔行
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6:
            continue
        m = re.fullmatch(r"`([^`]+)`", cells[1])
        if not m:
            continue
        rows.append({
            "tool": m.group(1),
            "side_effect": cells[3].strip("`").strip(),
            "needs_approval": cells[4],
            "roles": cells[5],
        })
    return rows


def test_r0_table_lists_every_tool_exactly_once():
    """正向：§R0 的行与实时注册表一一对应（不重不漏）。"""
    rows = _r0_rows()
    listed = [r["tool"] for r in rows]
    assert len(listed) == len(set(listed)), f"§R0 有重复行：{sorted(x for x in listed if listed.count(x) > 1)}"
    assert sorted(listed) == _registered_tool_names()


def test_r0_side_effect_column_matches_the_registry():
    """正向（文档 ↔ 实现一致）：§R0 的 `side_effect` 列必须等于注册表里的声明。

    为什么值得一条门：`side_effect` 是审批的唯一可信判据（`DEVELOPMENT.md` §6 的 P7）。
    文档里写 `read` 而代码里是 `network`，读者就会以为"这个工具不需要审批" ——
    而没有任何东西会因此变红。本轮的 `returns=` 真空通过（PROPOSALS G-4）
    是同一族缺陷，所以这里把"文档里那一列"也钉住。
    """
    import tempfile as _tf

    import os
    sys.path.insert(0, str(REPO / "src"))
    from agentflow import store as _store  # noqa: PLC0415
    from agentflow.tools import ROLES, build_registry  # noqa: PLC0415

    with _tf.TemporaryDirectory(prefix="r0_table_") as td:
        st = _store.Store(Path(td))
        st.init()
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        reg = build_registry(store=st, workspace_root=Path(td), roles=tuple(ROLES)).registry
        bad: dict[str, str] = {}
        for r in _r0_rows():
            live = reg.get(r["tool"]).side_effect
            if r["side_effect"] != live:
                bad[r["tool"]] = f"文档={r['side_effect']!r} 实际={live!r}"
        assert not bad, f"§R0 的 side_effect 列与注册表不一致：{bad}"


def test_r0_approval_and_roles_columns_match_the_registry():
    """正向：§R0 的"审批"列与"roles"列也必须与注册表一致。

    - 审批列是 `是` / `否` 的自由写法，只判"是否提到需要审批"这一个布尔；
    - roles 列是 `A B C` 这种以空格分隔的角色字母。
    """
    import os
    import tempfile as _tf

    sys.path.insert(0, str(REPO / "src"))
    from agentflow import store as _store  # noqa: PLC0415
    from agentflow.tools import ROLES, build_registry  # noqa: PLC0415

    with _tf.TemporaryDirectory(prefix="r0_roles_") as td:
        st = _store.Store(Path(td))
        st.init()
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        reg = build_registry(store=st, workspace_root=Path(td), roles=tuple(ROLES)).registry
        bad: dict[str, str] = {}
        for r in rows_to_check(reg, _r0_rows()):
            bad.update(r)
        assert not bad, f"§R0 的审批/roles 列与注册表不一致：{bad}"


def rows_to_check(reg, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """逐行比对审批列与 roles 列，返回 `{工具: 问题描述}` 的列表（空 = 全对）。"""
    out: list[dict[str, str]] = []
    for r in rows:
        spec = reg.get(r["tool"])
        problems: list[str] = []
        doc_says_approval = "是" in r["needs_approval"]
        if doc_says_approval != bool(spec.needs_approval):
            problems.append(f"审批 文档={r['needs_approval']!r} 实际={spec.needs_approval}")
        doc_roles = [x for x in re.findall(r"\b([A-H])\b", r["roles"])]
        if sorted(doc_roles) != sorted(spec.roles):
            problems.append(f"roles 文档={sorted(doc_roles)} 实际={sorted(spec.roles)}")
        if problems:
            out.append({r["tool"]: "；".join(problems)})
    return out
