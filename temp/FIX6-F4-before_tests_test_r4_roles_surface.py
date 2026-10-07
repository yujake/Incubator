"""`roles-1` / `roles-3` / `roles-4` 的回归判据（都在 `tools/base.py`，FC-27 禁改区）。

改前备份：`temp/zone-backup-r4-src_agentflow_tools_base.py`
（sha256 `256D231F1B6415FCBDF834654A0CED0852CF2681225EB80C74AE4C52F20E7043`）。

| 条目 | 缺陷 | 本文件里"改前必红"的那条 |
|---|---|---|
| `roles-1` | `_callable_for` 的 docstring 声称 `for_role` 也走它；`include_registered_writers=False` 那一支是死代码 | `test_the_dead_branch_is_gone_and_the_docstring_says_who_calls_this` |
| `roles-3` | `role` 消歧用 `setdefault` + 置空 ⇒ 位置映射里的 `role` 被 `None` 反向覆盖（参数静默丢失），且拒因与事实相反 | `test_a_role_in_the_position_map_reaches_the_tool` |
| `roles-4` | `for_role` 每次调用都往 `role_filter_notes` 追加 ⇒ 留痕自相矛盾且线性膨胀 | `test_for_role_notes_are_idempotent` |
"""
from __future__ import annotations

import pathlib

from agentflow.tools.base import ToolRegistry, ToolSpec, ok

BASE = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow" / "tools" / "base.py"


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


def test_for_role_notes_follow_the_current_state(store, monkeypatch) -> None:
    """负控 2：状态变了 ⇒ 留痕只保留与当前状态一致的那一条。

    审计者 A 的实测：`SANDBOX_AVAILABLE` 从 `None` 改成 `True` 之后再调一次，
    旧实现里 `notes['H']` 同时留着"剥掉了含 `probe.exec_read` 的 2 个工具"
    与"放行了 `probe.exec_read`" —— 前一条与当前状态相反。
    这里用真表把它复现出来（真表里 H 的工具面含 `external=exec` 的工具）。
    """
    from agentflow import tools as T
    from agentflow.tools import build_registry

    reg = build_registry(store=store, workspace_root=store.root, strict=True).registry
    reg.for_role("H")
    before = list(reg.role_filter_notes.get("H", []))
    # 当前环境：沙箱未声明可用 ⇒ 若真有 exec 工具被剥掉，这里应有"剥掉了"的句子
    with monkeypatch.context() as m:
        m.setattr(T, "SANDBOX_AVAILABLE", True)
        reg.for_role("H")
    after = list(reg.role_filter_notes.get("H", []))
    # 不许同时存在"剥掉 X"与"放行 X"两种句子（那正是旧形态）
    assert not (any("剥掉了" in s for s in after) and any("放行了" in s for s in after)), after
    # 也不许把旧句子留在后面（追加形态的指纹：after 是 before 的超集且更长）
    assert len(after) <= max(1, len(before)), (before, after)


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
    """正控：`include_registered_writers` 这个参数不能一起删掉。

    它真正的作用在 `_role_surface(..., call_surface=include_registered_writers)` 那一句里
    （可调用面是否含已登记的落库代理）。删掉它会静默改变 `call` 的行为 ——
    而"删死代码时顺手删掉一个活参数"正是这类清理最容易犯的错。
    """
    text = BASE.read_text(encoding="utf-8")
    assert "call_surface=include_registered_writers" in text, \
        "参数被删掉了：可调用面不再包含已登记的落库代理（H 的三个 review.* 会失效）"
