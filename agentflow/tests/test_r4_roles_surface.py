"""`roles-1` / `roles-3` / `roles-4` 的回归判据（都在 `tools/base.py`，FC-27 禁改区）。
改前备份：`temp/zone-backup-r4-src_agentflow_tools_base.py`（sha256 `256D231F1B6415FCBDF834654A0CED0852CF2681225EB80C74AE4C52F20E7043`）。
| 条目 | 缺陷 | 本文件里"改前必红"的那条 |
|---|---|---|
| `roles-1` | `_callable_for` 的 docstring 声称 `for_role` 也走它；`include_registered_writers=False` 那一支是死代码 |
`test_the_dead_branch_is_gone_and_the_docstring_says_who_calls_this` |
| `roles-3` | `role` 消歧用 `setdefault` + 置空 ⇒ 位置映射里的 `role` 被 `None` 反向覆盖（参数静默丢失），且拒因与事实相反 |
`test_a_role_in_the_position_map_reaches_the_tool` |
| `roles-4` | `for_role` 每次调用都往 `role_filter_notes` 追加 ⇒ 留痕自相矛盾且线性膨胀 | `test_for_role_notes_are_idempotent` |
第 6 轮修复批（`F4`）在这一批上补了 5 条第 6 轮重审 finding 的回归判据（本文件是本批的测试落点，备份在 `temp/FIX6-F4-before_tests_test_r4_roles_surface.py`）：
| finding | 缺陷 | 本文件里守着它的那条 |
|---|---|---|
| `R4-AN-4`（medium = `N-5`） | 写等级登记表 × 第一根轴词表没有导入期交叉断言 | `test_the_write_level_register_is_cross_checked_at_import` |
| `R4-AN-5`（low） | "负控 2" 两重空转（monkeypatch 打错命名空间 + 真表 H 面没有 exec 工具） | `test_for_role_notes_follow_the_current_state` |
| `R4-AN-1`（low） | 理由串两句与事实相反（说已被对上、援引已撤回的 [7c]） | `test_the_review_report_reason_matches_todays_facts` |
| `R4-AN-2`（low） | 对账面数字手抄过期（48/16/32 实测 49/16/33） | `test_the_reconciliation_numbers_in_the_source_match_the_live_reading` |
| `R4-AN-3`（low） | `if STRICT_DECLARATIONS: pass` 是空转开关 | `test_strict_declarations_switch_is_not_a_no_op` |
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from agentflow.tools.base import ToolRegistry, ToolSpec, ok

BASE = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow" / "tools" / "base.py"
CAPABILITIES = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow" / "capabilities.py"


def _role_echo(*, roles: tuple[str, ...] = ("A",), needs_role: bool = True) -> ToolSpec:
    props: dict = {"n": {"type": "integer"}}
    if needs_role:
        props["role"] = {"type": "string"}
    return ToolSpec(
        name="demo.rollcall",
        summary="回显它收到的 role 与 n",
        params={"type": "object", "properties": props, "additionalProperties": False},
        handler=lambda n=0, role=None: ok({"n": n, "role": role}),
        returns="{'n','role'}",
        roles=roles,
    )


# ============================================================ roles-3


def test_a_role_in_the_position_map_reaches_the_tool():
    """负控（核心）：`call(name, {"role": "X"})` ⇒ 工具必须收到 `X`。

    改前工具收到 `None`（`params.setdefault("role", None)` 把位置映射里那一份盖掉了）。
    """
    reg = ToolRegistry(name="t")
    reg.bound_role = "A"
    reg.register(_role_echo())
    res = reg.call("demo.rollcall", {"n": 1, "role": "X"})
    assert res.ok is True, res
    assert res.data == {"n": 1, "role": "X"}, res.data


def test_an_explicit_keyword_role_wins_over_the_position_map():
    """优先级：显式关键字 > 位置映射（`role="Y"` 必须赢过 args 里的 `"X"`）。"""
    reg = ToolRegistry(name="t")
    reg.bound_role = "A"
    reg.register(_role_echo())
    res = reg.call("demo.rollcall", {"n": 2, "role": "X"}, role="Y")
    assert res.ok is True, res
    assert res.data == {"n": 2, "role": "Y"}, res.data


def test_consuming_role_as_a_param_does_not_change_the_identity_check():
    """身份声明回退到 `bound_role`：把 `role` 让给工具不等于放弃身份判据。

    绑定 `A` 的注册表上调一个只给 `A` 的工具 ⇒ 仍然通过（身份来自绑定值）；
    而这不是"谁都能调"—— 下面那条负控钉住另一半。
    """
    reg = ToolRegistry(name="t")
    reg.bound_role = "A"
    reg.register(_role_echo())
    assert reg.call("demo.rollcall", {"role": "X"}).ok is True


def test_a_tool_that_does_not_declare_role_still_treats_role_as_identity():
    """负控：工具没有声明 `role` ⇒ 它仍是身份声明，冒充另一个角色必须被拒。

    没有这一条，"把 role 无脑让给工具"也能让上面三条通过 —— 那会把
    `P-14` 的身份判据一起拆掉（`test_registry_param_errors_…` 的 `role="H"` 那一格就是它）。
    """
    reg = ToolRegistry(name="t")
    reg.bound_role = "A"
    reg.register(_role_echo(needs_role=False))
    forged = reg.call("demo.rollcall", n=3, role="H")
    assert forged.ok is False and forged.meta.get("kind") == "role_denied", forged
    assert "'H'" in (forged.error or ""), forged.error


def test_the_position_map_form_of_role_gets_the_same_identity_check():
    """`R4-1` 负控（第一次重审实测的那条分叉）：位置映射里的 `role` 也必须过身份判据。

    改前（`roles-3` 那次修法引入的形态）：工具没有声明 `role`、schema 又是宽的
    （`additionalProperties=True`）时，`call(name, {"role": "H"})` 的 `role` 只从
    `args` 里来 ⇒ 触发条件里的 `role is not None` 为假 ⇒ 身份判据被整格跳过，
    工具真的收到 `{'n': 1, 'role': 'H'}` 并返回 `ok=True`；
    而同一个 `role="H"` 用关键字形态传却报 `role_denied`。
    改前两种形态都拒，所以这是修复引入的分叉。

    判据的可判定形式：两种形态的 `(ok, kind)` 必须逐字相同，且 handler 都没有被调用。
    """
    called: list[dict] = []

    def _wide() -> ToolSpec:
        return ToolSpec(
            name="demo.wide",
            summary="宽 schema + 不声明 role（重审实测的那个形态）",
            params={"type": "object", "properties": {"n": {"type": "integer"}},
                    "additionalProperties": True},
            handler=lambda **kw: (called.append(dict(kw)), ok(kw))[1],
            returns="{'收到的参数'}",
            roles=("A",),
        )

    reg_a = ToolRegistry(name="t")
    reg_a.bound_role = "A"
    reg_a.register(_wide())
    via_map = reg_a.call("demo.wide", {"n": 1, "role": "H"})

    reg_b = ToolRegistry(name="t")
    reg_b.bound_role = "A"
    reg_b.register(_wide())
    via_kw = reg_b.call("demo.wide", {"n": 1}, role="H")

    assert (via_map.ok, via_map.meta.get("kind")) == (via_kw.ok, via_kw.meta.get("kind")), (
        f"两种形态结论不同：位置映射 {via_map.ok}/{via_map.meta.get('kind')} vs "
        f"关键字 {via_kw.ok}/{via_kw.meta.get('kind')}"
    )
    assert via_map.ok is False and via_map.meta.get("kind") == "role_denied", via_map
    assert called == [], f"被拒的调用却进了 handler：{called}"
    assert "'H'" in (via_map.error or ""), via_map.error


def test_the_denial_reason_does_not_lie_about_a_declared_role():
    """`roles-3` 的第二形态：拒因不许说"调用方没有声明角色"而事实相反。

    造法：工具声明了 `role`（于是调用方那一份被工具收下），而注册表没绑定角色
    ⇒ 身份声明两边都没有 ⇒ 必须拒。但拒因说的是"没声明角色"这件事是真的
    （显式那份已归工具）—— 所以判据落在"拒绝理由与 `identity_role` 留痕一致"上。
    """
    reg = ToolRegistry(name="t")
    reg.log_calls = True
    reg.register(_role_echo())
    res = reg.call("demo.rollcall", {"role": "X"})
    assert res.ok is False and res.meta.get("kind") == "role_denied", res
    assert "没有声明角色" in (res.error or ""), res.error
    # 留痕必须说清"那份 role 去哪了"：否则读日志的人无法自证这句话是对的
    entry = reg.call_log()[-1]
    assert entry.get("role_consumed_as_param") is True, entry
    assert entry.get("identity_role") is None, entry
    assert entry["params"]["role"] == "X", entry


# ============================================================ roles-4


def test_for_role_notes_are_idempotent(store) -> None:
    """负控（核心）：连续两次 `for_role("H")` ⇒ 留痕逐字相同（不再追加）。

    改前每次调用都追加，第二次就多出重复条目；而"同一角色名下同时留着互相矛盾的
    两条（剥掉 X / 放行 X）"正是审计者 A 实测到的形态。
    """
    from agentflow.tools import build_registry

    reg = build_registry(store=store, workspace_root=store.root, strict=True).registry
    reg.for_role("H")
    first = list(reg.role_filter_notes.get("H", []))
    reg.for_role("H")
    second = list(reg.role_filter_notes.get("H", []))
    assert first == second, f"留痕不幂等：第一次 {first} / 第二次 {second}"


def test_for_role_notes_do_not_accumulate_across_many_calls(store) -> None:
    """判据的规模面：调 5 次不许让条目变多（旧实现是线性的）。"""
    from agentflow.tools import build_registry

    reg = build_registry(store=store, workspace_root=store.root, strict=True).registry
    reg.for_role("C")
    n1 = len(reg.role_filter_notes.get("C", []))
    for _ in range(5):
        reg.for_role("C")
    assert len(reg.role_filter_notes.get("C", [])) == n1, reg.role_filter_notes.get("C")


def _surface_probe(name: str, *, side_effect: str = "read", external: str = "none") -> ToolSpec:
    """合成探针：`for_role` 的剥除/放行两条留痕都要真的被走到（`R4-AN-5`）。"""
    return ToolSpec(
        name=name,
        summary=f"探针 {name}（只为把 H 的 exec 放行分支真的走一遍）",
        params={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda: ok({}),
        returns="{'ok'}",
        roles=("H",),
        side_effect=side_effect,
        declared_external=external,
    )


def test_for_role_notes_follow_the_current_state(monkeypatch) -> None:
    """    负控 2：状态变了 ⇒ 留痕只保留与当前状态一致的那一条。

    审计者 A 的实测：`SANDBOX_AVAILABLE` 从 `None` 改成 `True` 之后再调一次，旧实现里 `notes['H']` 同时留着"剥掉了含 `probe.exec_read` 的 2
    个工具"与"放行了 `probe.exec_read`" —— 前一条与当前状态相反。`R4-AN-5`：改前这条用例有两重空转，本版两处都修掉（否则它是恒真断言）：

    1. `monkeypatch.setattr(T, 'SANDBOX_AVAILABLE', True)` 打在 `agentflow.tools`
    包命名空间上，而 `_role_surface` 读的是 `tools/base.py` 的模块全局⇒ 打不打都一样（实测两次 `for_role('H')` 逐字相同）。现在打在 `base` 上。
    2. 真表的 H 工具面里一个 `external=exec` 的工具都没有
    （`verify.check_formal` / `run_experiment` 的 roles 是 ('E','F','G')）⇒ "放行了"那一句永远不会出现，两条断言恒真。
    现在用一张真的含`read + exec` 探针的合成注册表，并按工具名核对两句话，而不是"有没有这两句话"。
    """
    from agentflow.tools import base as B

    reg = ToolRegistry(name="sandbox-probe")
    reg.register(_surface_probe("probe.exec", side_effect="read", external="exec"))
    reg.register(_surface_probe("probe.write", side_effect="write_local"))

    # 当前环境：沙箱未声明可用 ⇒ exec 探针必须被剥掉、不许出现在任何放行句里
    monkeypatch.setattr(B, "SANDBOX_AVAILABLE", None)
    reg.for_role("H")
    before = list(reg.role_filter_notes.get("H", []))
    assert any("剥掉了" in s and "probe.exec" in s for s in before), before
    assert not any("放行了" in s for s in before), before

    with monkeypatch.context() as m:
        m.setattr(B, "SANDBOX_AVAILABLE", True)
        reg.for_role("H")
        during = list(reg.role_filter_notes.get("H", []))

    # 按工具名核对（这才是 roles-4 的判据）：同一个工具不许同时出现在两句里
    assert any("放行了" in s and "probe.exec" in s for s in during), during
    assert not any("剥掉了" in s and "probe.exec" in s for s in during), (
        f"exec 探针同时被剥掉与被放行（旧实现的自相矛盾留痕）：{during}"
    )
    assert any("剥掉了" in s and "probe.write" in s for s in during), during
    assert not any("放行了" in s and "probe.write" in s for s in during), during
    # 追加形态的指纹：`before` 里那条"剥掉了 probe.exec"必须已经被换掉
    stale = [s for s in before if "probe.exec" in s]
    assert stale and not any(s in during for s in stale), (before, during)

    # 上下文退出 ⇒ 回到 None；再重算一次必须与第一次逐字相同（重算而不是追加）
    reg.for_role("H")
    restored = list(reg.role_filter_notes.get("H", []))
    assert restored == before, (before, restored)


def test_the_sandbox_monkeypatch_is_pinned_to_the_base_module_namespace(monkeypatch) -> None:
    """    `N-2` 的反空转指纹：那个 monkeypatch 必须打在 `tools/base.py` 的模块全局上。

    批 C（观测 2026-09-26，证据 `temp/batchC-axes5-vacuous-monkeypatch.txt`）
    实测的原始缺陷：`monkeypatch.setattr(T, "SANDBOX_AVAILABLE", True)`（`T` = `agentflow.tools` 包对象）打在没人读的命名空间上 ——
    `_role_surface` 读的是 `base` 模块自己的全局，所以那一次patch 不改变任何判据：整条负控恒真，而它看上去在跑（"判据看起来在跑、实际没接上"）。`F4`（第 6 轮重审 finding
    `R4-AN-5` 的第一半）把注入点改成了 `base`，上面那条用例因此真的在咬。本用例把这件事钉成断言，而不是"碰巧打对了"：包对象上确实有这个属性（`tools/__init__.py` 的再导出）⇒ 打错命名空间时
    既不报 `AttributeError`、也不改变判据 —— 这正是最容易被读成"负控跑了"的形态；
    2. 把包对象上那个属性改成 `True`（也就是改前那一版做的事）⇒ `for_role("H")`
    仍然剥掉 exec 探针。这一条一旦不成立，说明判据读了另一处名字（`N-2` 的形态变了），必须回头看上面那条用例的注入点与 `tools/__init__.py` 的再导出注释。负控（整树副本注入：把
    `_role_surface` 的读取点改成从包对象取同名属性⇒ 本用例必须红）见交付报告；仓内不落那种注入。
    """
    from agentflow import tools as T
    from agentflow.tools import base as B

    assert hasattr(T, "SANDBOX_AVAILABLE"), (
        "前提变了：`agentflow.tools` 顶层不再有这个名字 —— 本用例的『打错命名空间』"
        "这一档就没法造了，请连同 `temp/batchC-axes5-vacuous-monkeypatch.txt` 的结论一起更新"
    )
    reg = ToolRegistry(name="sandbox-probe-n2")
    reg.register(_surface_probe("probe.exec", side_effect="read", external="exec"))

    monkeypatch.setattr(T, "SANDBOX_AVAILABLE", True)      # 改前那一版做的事：空转
    assert B.SANDBOX_AVAILABLE is not True, (
        "前提：包对象与 `base` 模块是两个独立的绑定（否则『打错命名空间』不再是空转）"
    )
    reg.for_role("H")
    notes = list(reg.role_filter_notes.get("H", []))
    assert any("剥掉了" in s and "probe.exec" in s for s in notes), (
        f"包对象上的 setattr 竟然移动了判据 ⇒ 判据读的不是 `base` 的模块全局（`N-2`）：{notes}"
    )
    assert not any("放行了" in s for s in notes), notes


def test_for_role_keeps_the_assembly_time_notes(store) -> None:
    """`R4-2` 负控：`for_role` 的重算不许把装配期留痕一起抹掉。

    造法（与重审实测同形）：用一个不含 `review.*` 代理的最小注册表
    ⇒ `scoped_to("H")` 的第二步 `_attach_registered_writers` 记下一条装配事实
    （"已登记的落库代理没有装配进这张表"）。再调一次 `for_role("H")`：
    - 改后：那条装配事实仍在（它描述的是装配，不是工具面重算的结果）；
    - 改前：`for_role` 里一句 `pop(role, None)` 把整个列表清空 ⇒ 记录消失，
      而事实没有任何变化。
    """
    from agentflow.tools.base import READONLY_CALL_EXCEPTIONS, ToolSpec

    def _spec(name: str, side_effect: str) -> ToolSpec:
        return ToolSpec(
            name=name, summary=f"探针 {name}",
            params={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda: {"ok": True}, returns="{'ok'}", roles=("H",),
            side_effect=side_effect,
        )

    reg = ToolRegistry(name="tiny")
    reg.register(_spec("demo.read", "read"))
    reg.register(_spec("demo.write", "write_local"))
    scoped = reg.scoped_to("H")
    assert READONLY_CALL_EXCEPTIONS.get("H"), "前提：H 有已登记的落库代理"

    before = list(scoped.role_filter_notes.get("H", []))
    assert any("落库代理" in m for m in before), before

    scoped.for_role("H")
    after = list(scoped.role_filter_notes.get("H", []))
    assert any("落库代理" in m for m in after), (
        f"装配期留痕被 for_role 抹掉了：before={before} after={after}"
    )
    # `roles-4` 的幂等不许因此回归：重算来源的条目仍然稳定
    scoped.for_role("H")
    assert list(scoped.role_filter_notes.get("H", [])) == after, "重算来源的条目不再幂等"


# ============================================================ roles-1


def test_the_dead_branch_is_gone_and_the_docstring_says_who_calls_this() -> None:
    """判据的文本级守卫：死分支必须删掉，docstring 必须说清"谁走这里"。

    为什么用文本级断言：那一支结构上不可达（唯一调用点传 `True`），
    所以任何行为测试都碰不到它；而它留着的代价是"读起来像有第二条判据"。
    这类"文档承诺 + 不可达分支"的组合，只有文本判据能钉住。
    """
    text = BASE.read_text(encoding="utf-8")
    assert "本方法的行为不因" in text  # 定位：我们读的是 base.py 里那份 docstring
    assert "旧 docstring 逐字写着" in text, "修改说明不见了（判据的落点变了，请更新本用例）"
    assert "**只有 `call` 走这里。**" in text, "docstring 必须显式说清谁走 _callable_for"
    assert "include_registered_writers=True）才是它的通路" not in text, \
        "死分支的拒绝理由还在（它永不执行，留着会让人以为有第二条判据）"


def test_the_parameter_is_still_load_bearing() -> None:
    """    正控：`include_registered_writers` 这个参数不能一起删掉。

    它真正的作用在 `_role_surface(..., call_surface=include_registered_writers)` 那一句里（可调用面是否含已登记的落库代理）。删掉它会静默改变 `call` 的行为
    ——而"删死代码时顺手删掉一个活参数"正是这类清理最容易犯的错。

    `FINAL-R4-02`：这一条改前是文本级断言（在 `base.py` 全文里找子串`call_surface=include_registered_writers`），而那个子串在文件里出现两处（活跃调用点 +
    一条注释）⇒ 只把活跃调用点改成 `call_surface=False` 时它不响（实测：只改活跃点 ⇒ 111 passed / 0 failed）。现在改成 AST 级：解析`_callable_for`（或
    `call`）里那次 `_role_surface(...)` 调用，断言它的 `call_surface` 关键字实参就是那个形参名。
    """
    tree = ast.parse(BASE.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "_role_surface":
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        value = kwargs.get("call_surface")
        if value is None:
            continue
        if isinstance(value, ast.Name) and value.id == "include_registered_writers":
            hits.append("ok")
        else:
            hits.append(ast.unparse(value))
    assert hits, (
        "没有任何 `_role_surface(call_surface=...)` 调用 —— 判据的落点变了，"
        "先确认 `tools/base.py` 的可调用面判据还在"
    )
    assert "ok" in hits, (
        f"可调用面不再由形参 `include_registered_writers` 决定（实参：{hits}）"
        "⇒ H 的三个 review.* 会失效；注意本判据是 AST 级的，注释里写着这个子串不算数"
    )


# ============================================================ R4-AN-4（medium = N-5）


def test_the_write_level_register_is_cross_checked_at_import() -> None:
    """    写等级登记表与第一根轴的词表必须互相穷举（`R4-AN-4` / 台账 `N-5`）。

    缺陷：`tools/base.SIDE_EFFECTS` 与 `tools/__init__.SIDE_EFFECTS_WRITE` 之间此前没有任何导入期判据。只读角色的结构性剥离读的是
    `SIDE_EFFECTS_WRITE`（`for_role` / `call` / `_callable_for` 三处共用 `_role_surface`），于是"往词表加一个写等级、忘了登记进这张表"的后果是静默的：
    只读角色 C/H 拿到那个写工具，而导入成功、测试全绿。

    正控：真表上这条判据不抛（`agentflow.tools` 一被导入就已经跑过一次模块级调用）。负控（本用例，内存注入）：往词表加一个没登记的假轴 ⇒ 同一条判据必须抛。更强的负控（副本注入：两处
    `SIDE_EFFECTS` 同步加 `write_remote` ⇒ 导入即抛，带副本 sha256 指纹与改前副本的对照读数）在 `temp/FIX6-F4.md` 的探针读数里。
    """
    from agentflow.tools import SIDE_EFFECTS_WRITE, _check_write_levels_are_registered
    from agentflow.tools.base import SIDE_EFFECTS

    assert set(SIDE_EFFECTS_WRITE) <= set(SIDE_EFFECTS)  # 正控：登记表取自词表
    _check_write_levels_are_registered()  # 正控：真表上不抛

    with pytest.raises(AssertionError):
        _check_write_levels_are_registered(side_effects=(*SIDE_EFFECTS, "write_remote"))
    with pytest.raises(AssertionError):
        _check_write_levels_are_registered(write_levels=(*SIDE_EFFECTS_WRITE, "write_remote"))
    with pytest.raises(AssertionError):
        _check_write_levels_are_registered(non_write=("none", "read", "write_local"))


# ============================================================ R4-AN-1 / -2 / -3（capabilities）


def test_the_review_report_reason_matches_todays_facts() -> None:
    """`R4-AN-1`：那条理由串不许再说两句与事实相反的话。

    改前的两句（重审逐字点名）：说 `review.report` 已经被 `matching_tool_name`
    唯一对上 `H.review_report`（实测返回 `None`），以及把已经撤回的第 [7c] 条
    称作"真正的反方向判据"（那条断言不存在，撤回说明就在同文件下方）。
    """
    from agentflow import capabilities as C

    spec = C.find_action("H", "review_report")
    assert spec is not None, "前提：H.review_report 在能力表里"
    assert C.matching_tool_name(spec) is None, (
        "前提变了：`matching_tool_name` 一旦真的对上 H.review_report，"
        "`_NO_ACTION_YET` 里那条登记就该删掉，本用例也要跟着改"
    )
    assert "H.review_report" in C._KNOWN_UNMATCHED_ACTIONS

    text = CAPABILITIES.read_text(encoding="utf-8")
    # 判据的落点是那条理由串本身：整份源码里"唯一对上"这四个字在别处有正当用法
    # （`two_layer_reconciliation` 的 docstring 讲 `compared` 那一格），所以这里
    # 把 `_NO_ACTION_YET` 那一段切出来再判，而不是对整份文件做子串断言。
    start = text.index("_NO_ACTION_YET = {")
    end = text.index("_covered: set[str] = set()", start)
    block = text[start:end]
    assert block.count('"review.report"') == 1, block
    assert "唯一对上" not in block, "理由串仍在说 review.report 被唯一对上（实测返回 None）"
    assert "真正的反方向判据" not in block, "[7c] 已撤回，理由串不许再把它当判据"


def test_the_reconciliation_numbers_in_the_source_match_the_live_reading() -> None:
    """`R4-AN-2`：源码注释里的对账数字必须等于实跑读数（手抄的数字会过期）。

    改前写的是"48 个动作 = 16 compared + 32 unmatched + 0 ambiguous"，
    实测（含 `D-5` 落地的 `H.review_report`）是 49 / 16 / 33 / 0。
    本用例不手抄 49：它把实跑读数拼成那句话再去源码里找 —— 数字漂了任一处都红。
    """
    from agentflow import capabilities as C

    recon = C.two_layer_reconciliation()
    expected = (
        f"{recon['total']} 个动作 = {len(recon['compared'])} compared + "
        f"{len(recon['unmatched'])} unmatched + {len(recon['ambiguous'])} ambiguous"
    )
    text = CAPABILITIES.read_text(encoding="utf-8")
    assert expected in text, f"源码注释与实跑读数不符：找不到 {expected!r}"
    assert "48 个动作" not in text, "旧数字 48 还在（它是手抄漂移的样本）"
    assert ": 32}" not in text, "旧数字 32 还在（Counter 那一段）"


def test_strict_declarations_switch_is_not_a_no_op(monkeypatch) -> None:
    """`R4-AN-3`：`STRICT_DECLARATIONS` 必须真的把 warning 升成导入期断言。

    改前实现是 `if STRICT_DECLARATIONS: pass` —— 一个空转开关（docstring 承诺
    "True 时把 warning 升为导入期断言"，而 True/False 两种取值下
    `assert_capabilities()` 都正常返回，重审用合成 warning 实测）。

    注入点：把 `capabilities.declaration_divergences` 换成"真读数 + 一条合成 warning"，
    于是同一个开关的两种取值落在同一批 divergence 上（注入不会被下一行覆盖：
    待测函数每次调用都现取这个名字）。
    """
    from agentflow import capabilities as C

    real = C.declaration_divergences()
    assert not [d for d in real if d.level == "error"], "前提：真实树今天没有 error 级不一致"
    synth = C.DeclarationDivergence(
        code="two_layer_external_imprecise",
        level="warning",
        where="probe.synthetic",
        message="F4 的注入 warning（证明开关真的接在 divergence 清单上）",
    )
    monkeypatch.setattr(C, "declaration_divergences", lambda: [*real, synth])

    monkeypatch.setattr(C, "STRICT_DECLARATIONS", False)
    assert C.assert_capabilities() is None, "默认档不许对 warning 级炸（否则导入永远失败）"

    monkeypatch.setattr(C, "STRICT_DECLARATIONS", True)
    with pytest.raises(AssertionError) as err:
        C.assert_capabilities()
    assert "probe.synthetic" in str(err.value), (
        f"抛的不是那条 warning 判据（开关仍可能空转）：{err.value}"
    )
