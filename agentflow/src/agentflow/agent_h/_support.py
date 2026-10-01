"""智能体 H：审校（只读）。

## 为什么 H 必须是只读的

若审校者能直接改稿，它就同时是"发现者"与"修正者"，于是
"发现问题"与"掩盖问题"在结构上无法区分 —— 这不是分工洁癖，
而是"审校记录能不能被信任"的前提。把这条做成结构约束（而不是写在提示词里），
是它唯一可靠的落地方式。

## "H 只读"在这里由三件事共同保证（缺一条就只剩口号）

1. 工具面只读：`install_h_tools()` 只把 `side_effect in ("none","read")`
   的工具放进 H 的自由工具箱，并在构造时断言这一点（拿到不合规的注册表
   就 fail-closed 拒绝启动）。被拒的写工具会记进 `registry.refused_write_tools`，
   不静默丢弃。
2. 落库代理被钉死：H 唯一会写盘的动作（写 `review_findings`、
   改 `documents.status`）走的是显式的"代理注册表"（`self.writers`，
   `include_writers=True`），而这两个工具的落点固定：不碰 `claims`，
   不碰任何知识表。
3. 可核对的运行期断言：审校前后 `concepts/relations/literature` 逐字节不变；
   `documents.json` 的唯一变化点是 `status`（连 `updated_at` 都不碰）。

## H 的三态纪律

`dependencies` 没查（显式 `None`）与"查了、依赖都闭合"是两件事：
前者必须报 `dep_check.checked is False` 且不许判 `accepted`。
AgentD 的 `_UNSPECIFIED` 哨兵在这里沿用同一种语义。
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from .. import schema as S
from ..store import Store
from ..tools import READONLY_CALL_EXCEPTIONS, SIDE_EFFECTS_WRITE, build_registry
from ..tools import review_tools as RV
from ..tools.base import ToolRegistry, ToolSpec
from ..tools.doc_tools import CROSS_CHECK_DISCLAIMER
from ..agentspec import AgentBrief, AgentSpec
__all__ = ["AgentH", "ReviewError", "filter_readonly_h_surface", "install_h_tools"]
class ReviewError(RuntimeError):
    """审校流程本身失败（工具未接线 / 注册表不合规 / 稿件不存在）。"""
_UNSPECIFIED: Any = object()
_H_READONLY_SIDE_EFFECTS = ("none", "read")
_H_WRITABLE_TOOLS: tuple[str, ...] = tuple(
    name for name, _why in READONLY_CALL_EXCEPTIONS["H"]
)
def filter_readonly_h_surface(
    specs: Iterable[ToolSpec],
) -> tuple[list[ToolSpec], list[dict]]:
    """把 H 的角色面裁成"只读面"，并把被拒的写工具记录下来。

    ## 这一层与工具层那一层的关系（`roles-7`：两处注释此前互相否认）

    工具层已经有一道只读过滤：`tools/base.ToolRegistry._role_surface` 在角色命中
    `READ_ONLY_ROLES` 时剥掉"写副作用 或 `external == "exec"`"的工具 —— 它看两根轴。
    本函数是 H 装配路径上的第二道，判据更窄：只看 `side_effect` 属不属于
    `_H_READONLY_SIDE_EFFECTS`（`none` / `read`）—— 它不看 `external`，也不认 `unknown`。
    于是在"写"这根轴上本层不会比工具层更宽；子集关系由下面那条可执行的断言钉住
    （不是只写在注释里），并写明它唯一可能不成立的那一格
    （`side_effect` 属 none/read 加 `external == "exec"` 加 roles 含 H）。

    两处判据不同这件事本身无害，有害的是"两处注释互相否认对方存在"：读代码的人会得出
    "工具层没有只读过滤"而另行加固（制造第三份判据），或者反过来把本层删掉。

    本层仍然必须保留，理由不是"它今天拦到了什么"，而是两个报告字段只在它这里有：
    `refused_write_tools`（显式拒绝清单）与 `raw_surface_size`（裁剪前的面有多大）。
    有了它们，"静默丢弃"与"显式拒绝"在报告里才是两件事（FC-08）。

    历史留痕：本函数写在工具层的只读过滤之前，当时 `table.create` / `table.update` /
    `table.delete` / `fs.write` / `fs.delete` / `fs.move` 这些 `write_local` 工具确实会
    出现在按角色过滤得到的 H 工具面里；工具层补上 `_role_surface` 之后，本层实测
    拒不到东西（`refused` 为空），它的价值从"拦刀"变成"留痕"（见 `D-6`）。
    """
    # 先物化成一份列表：下面要用同一批 specs 跑两遍（本层过滤 + 工具层判据的交叉断言），
    # 而 `specs` 的形参类型是 `Iterable` —— 生成器在第一遍之后就走空了。
    items = list(specs)
    kept: list[ToolSpec] = []
    refused: list[dict] = []
    for s in items:
        if s.side_effect in _H_READONLY_SIDE_EFFECTS:
            kept.append(s)
        else:
            refused.append(
                {
                    "name": s.name,
                    "side_effect": s.side_effect,
                    "reason": "H 的工具面必须全部 none/read：能改表的工具会让审校者同时成为修正者",
                }
            )

    # ---- `roles-7`：本层判据是工具层判据的子集（交叉断言，不是注释）
    #
    # 判据差异逐字写在这里：工具层的 `_role_surface` 剥掉"写副作用 或
    # external == 'exec'"（两根轴都看），本函数只看 `side_effect`（少看 external）。
    # 在 side_effect 这根轴上本层更窄；对 external 这根轴它是盲的 —— 所以下面的子集
    # 关系不是形式定理，而是对声明表的一条不变量：真实表上今天成立（实测 H 的工具面
    # 里没有任何 external == 'exec' 的 spec），而"read + external=exec + roles 含 H"
    # 那种 spec 会让它当场红。那一格确实必须由人看：工具层会拒绝它、本层会保留它，
    # 于是它的名字出现在 H 的自由工具箱里，而每次 `call` 都被拒绝。
    # 断言的做法是让工具层那个唯一的判据实现自己说话（`_role_surface`），
    # 而不是在这里重写一遍"哪些算写工具"的名单 —— 那会是 FC-03 禁止的第二份实现。
    probe = ToolRegistry(name="agent-H:readonly-invariant")
    for spec in items:
        probe.register(spec)
    tool_layer, _ = probe._role_surface("H", filter_readonly=True, call_surface=False)
    allowed = {s.name for s in tool_layer}
    leaked = sorted(s.name for s in kept if s.name not in allowed)
    assert not leaked, (
        f"filter_readonly_h_surface 放行了工具层不会给 H 的工具 {leaked} —— "
        "本层判据（只看 side_effect 属不属于 none/read）必须是 "
        "base._role_surface('H', filter_readonly=True, call_surface=False) 判据的子集。"
        "最可能的成因是某个 spec 声明了 side_effect ∈ {none, read} 加 external='exec' "
        "且 roles 含 H（本层对 external 是盲的）：要么它的 roles/external 声明是错的，"
        "要么本层必须补看 external。无论哪一种，它的名字都会留在 H 的自由工具箱里而"
        "每次 call 都被拒绝 —— 这一格必须由人看，不许静默通过"
    )
    return kept, refused
def install_h_tools(
    store: Store, *, workspace_root: str | Path | None = None
) -> ToolRegistry:
    """装配 H 的只读工具栏（并把被拒的写工具记录在注册表上）。"""
    root = Path(workspace_root).resolve() if workspace_root else Path(store.root).resolve()
    build = build_registry(store=store, workspace_root=root)
    raw = build.registry.for_role("H")
    kept, refused = filter_readonly_h_surface(raw)
    # 这张表登记的是只读工具面（`kept`），并绑定角色（`P-14`）：此后每次 `call`
    # 都会再判一次"H 拿不拿得到这个工具"。刻意不用 `scoped_to` 拿"可调用面" ——
    # 那会把 18 个写工具也登记进来，"H 的工具栏全是只读"这条断言当场失效
    # （H 自己的落库代理是另一张注册表：`self.writers`）。
    reg = ToolRegistry(name="agent-H")
    reg.bound_role = "H"
    for spec in kept:
        reg.register(spec)
    # 留痕：降级/拒绝必须是可观测的事实，而不是"少几个工具没人知道"。
    setattr(reg, "refused_write_tools", refused)
    #: 裁剪前的角色面大小。有了它，"拒绝清单 + 保留清单 == 原面"这条不变量才能被断言
    #: （否则"静默丢弃"与"显式拒绝"在断言里长得一模一样）。
    setattr(reg, "raw_surface_size", len(raw))
    setattr(reg, "assembly_skipped", build.skipped)
    return reg
_SELFTEST_HARNESS = ("_seed_document", "_inject_raw_document", "_selftest")
def _seed_document(
    st: Store,
    *,
    doc_id: str,
    claims: Sequence[Mapping[str, Any]],
    status: str = "draft",
) -> dict:
    """在自检里直接写一行 schema 合法的稿件（不经过 G，保持 H 的自检自足）。

    `T4-A`：内容哈希由写侧在每一行稿件上钉住（G 就是这样），所以这里也照做 ——
    不能只在 `status="accepted"` 时补：H 会稍后把 draft 置成 accepted，而
    `_set_doc_status` 只改 status（连 `updated_at` 都不碰）⇒ 那时再来补哈希就晚了。
    """
    row = S.Document(
        doc_id=doc_id,
        kind="paper",
        title="自检稿件",
        markdown_path=None,
        claims=[dict(c) for c in claims],
        status=status,
        created_at=S.now_iso(),
        updated_at=S.now_iso(),
    )
    if not row.content_sha256:
        from .. import signatures as _SIG

        row.content_sha256 = _SIG.content_sha256_of(row.to_dict())
    row.validate()
    with st.tx("documents", actor="seed", note="selftest") as tx:
        tx.upsert("documents", row.to_dict())
    return row.to_dict()
def _inject_raw_document(st: Store, row: Mapping[str, Any]) -> None:
    """绕过 store 校验直接改盘（自检用）。

    为什么需要它：schema 会拒绝"无引用断言"这类行，所以那些坏数据不可能
    经由 `store.tx` 写入。而 H 要面对的恰恰包括"盘上已经存在的坏行"
    （手工改坏的、旧版本写的、rebuild 之前的残骸）—— 那正是 FC-09 关心的场景：
    后面的闸门不能假设前面的闸门一定跑过。
    """
    import json

    p = st.data / "documents.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["rows"] = [r for r in doc["rows"] if r.get("doc_id") != row["doc_id"]] + [dict(row)]
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
from ..specs.h import SPEC  # noqa: E402,F401

