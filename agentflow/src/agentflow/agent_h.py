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

from . import schema as S
from .store import Store
from .tools import READONLY_CALL_EXCEPTIONS, SIDE_EFFECTS_WRITE, build_registry
from .tools import review_tools as RV
from .tools.base import ToolRegistry, ToolSpec
from .tools.doc_tools import CROSS_CHECK_DISCLAIMER

__all__ = ["AgentH", "ReviewError", "filter_readonly_h_surface", "install_h_tools"]


class ReviewError(RuntimeError):
    """审校流程本身失败（工具未接线 / 注册表不合规 / 稿件不存在）。"""


#: 默认值哨兵：不传 = "自己去库里读依赖"；显式 `None` = "调用方没给清单 ⇒ 没查"。
_UNSPECIFIED: Any = object()

#: H 允许持有的副作用等级。写成常量而不是散落的字面量：
#: 它是一条结构约束，必须只有一处定义（FC-03）。
_H_READONLY_SIDE_EFFECTS = ("none", "read")

#: H 的落库代理里唯一允许带写副作用的三个工具（落点被钉死在这里）。
#:
#: 注意：它从 `tools/base.READONLY_CALL_EXCEPTIONS["H"]` 派生（`P-14`）：
#: 那张表是同一件事的单一来源，这里只是把它的名字取出来。
#: 早先这里是一份独立的三个字面量 —— 同一个概念两个名字，正是 `G-45` 那一类缺陷
#: （两处可以各自漂移，而且没有任何东西会红）。
#:
#: 为什么本轮多了一个 `review.report`：`draft/17` §8.4 要求 H 产出一份
#: 带版本 hash、带自证数字、带"我这一轮犯的错"一节的审校报告（G11/G13/G15）。
#: 它必须落成 markdown 文件（否则"报告"就只是一段内存里的字符串，
#: 而"审校记录能不能被接手的复核"整件事就没有落点），所以它必然是一个写工具。
#: 它的落点仍然被钉死：一个报告文件，不碰任何数据表、不碰 `claims`
#: （`tests/test_gates.py` 有一条断言：跑完 `review_report` 之后
#: `documents.json` 的 `claims` 逐字节不变）。
_H_WRITABLE_TOOLS: tuple[str, ...] = tuple(
    name for name, _why in READONLY_CALL_EXCEPTIONS["H"]
)


# ---------------------------------------------------------------- 工具装配


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


# ---------------------------------------------------------------- AgentH


class AgentH:
    """审校智能体。

    两个注册表是刻意分开的，它们的区别就是"H 只读"这条约束本身：

    - `self.tools`：H 的自由工具箱（只读）。H 可以任意反复调用，不需要审批。
    - `self.writers`：H 的落库代理（`write_local`）。只在固定流程里被调用，
      落点被钉死在 `review_findings` 与 `documents.status` 上。
    """

    def __init__(
        self,
        store: Store,
        *,
        config: Mapping[str, Any] | None = None,
        log: Callable[[str], None] | None = None,
        tools: ToolRegistry | None = None,
        writers: ToolRegistry | None = None,
        # LLM 判定缝（`draft/30` §T0-8）：默认 None = 不接线 ⇒ 本角色一个 LLM 调用都不发。
        # 判定必须走 `judge.judge_json`（唯一缝协议），失败落 `judge_*` 词表，
        # 绝不许折成"没找到"。本批只插插座，接线在各条目的伪代码下进行。
        llm: Any | None = None,
    ) -> None:
        self.store = store
        self.cfg: dict[str, Any] = dict(config or {})
        self.actor = str(self.cfg.get("actor", "agent-H"))
        self.llm = llm
        self.workspace_root = Path(store.root).resolve()
        self.log = log
        self.logs: list[str] = []
        self.tool_calls: list[dict] = []

        #: 复审轮数上限。必须有上限：没有它，"error 一直不修"会变成一个
        #: 无限循环（FC-18 的同族要求）。到顶不是继续跑，而是标 unresolved_review 交人。
        self.max_review_rounds = int(self.cfg.get("max_review_rounds", 2))
        if self.max_review_rounds < 1:
            raise ReviewError(f"max_review_rounds 至少为 1，收到 {self.max_review_rounds}")

        self.tools = tools if tools is not None else install_h_tools(self.store)
        # ---- 装配期断言（FC-03 的形态）：拿不到合规的注册表就拒绝启动。
        # 审校者手里若有一把能改稿的刀，整套"发现/掩盖可区分"的设计就当场失效，
        # 而它不会报任何错 —— 所以这里必须 fail-closed。
        bad = [t for t in self.tools.describe() if t["side_effect"] not in _H_READONLY_SIDE_EFFECTS]
        if bad:
            raise ReviewError(
                "H 的工具栏里出现了非只读工具："
                + "、".join(f"{t['name']}({t['side_effect']})" for t in bad)
                + "。审校者必须只能提发现，不能改稿 —— 若它能改，"
                "'发现问题'与'掩盖问题'在结构上就无法区分"
            )

        self.writers = writers if writers is not None else ToolRegistry(name="agent-H:writers")
        # ---- 落库代理绑定角色（`P-14`）：`self.writers` 代表 H，
        # 且它的可调用面就是 `READONLY_CALL_EXCEPTIONS["H"]` 那张表。
        # 不绑的话 `_writer` 的每次 `call` 都会被"调用方没声明角色"拒掉 ——
        # 那会把 H 写审校发现与报告的能力一起砍掉（`_H_WRITABLE_TOOLS` 的落点也就没了）。
        if self.writers.bound_role is None:
            self.writers.bound_role = "H"
        if writers is None:
            # `draft/28` §196：有 `llm` 就把它接成语义判据（"结论是否强于引文"），
            # 一路传给 `review.review_document` / `review.review_report`。
            # 没有 `llm` ⇒ 传 None ⇒ 报告里那一格是 `checked=False` + 逐字理由（没查），
            # 不是"判过、没问题"。默认路径（`llm=None`）一个 LLM 调用都不发。
            judge = None
            if self.llm is not None:
                from . import judges as JG

                judge = JG.semantic_judge_for(self.llm)
            RV.register(self.writers, store=self.store, include_writers=True, actor=self.actor,
                        semantic_judge=judge)
        # ---- 落库代理的装配期断言（本次审计补上的缺口）。
        #
        # `tools` 上面已有一条 fail-closed 断言，而 `writers` 作为构造参数此前
        # 完全没有校验 —— 传进来一个带 `table.update` 的注册表，"落点被钉死
        # 在 review_findings 与 documents.status 上"就只剩一句注释。
        # （上面那条断言查的是 `self.tools`，结构上覆盖不到 `self.writers`。）
        # 判据复用工具层的 `SIDE_EFFECTS_WRITE`，不另写一份"哪些算写"。
        bad_writers = [
            t["name"]
            for t in self.writers.describe()
            if t["side_effect"] in SIDE_EFFECTS_WRITE and t["name"] not in _H_WRITABLE_TOOLS
        ]
        if bad_writers:
            raise ReviewError(
                "H 的落库代理里出现了不该有的写工具："
                + "、".join(bad_writers)
                + f"。只允许 {_H_WRITABLE_TOOLS} —— 否则 H 就能改稿，"
                "'发现问题'与'掩盖问题'在结构上再次无法区分"
            )

    # ------------------------------------------------------------ 小工具

    def _emit(self, message: str, **extra: Any) -> None:
        line = message if not extra else f"{message} {extra}"
        self.logs.append(line)
        if callable(self.log):
            try:
                self.log(line)
            except Exception:  # noqa: BLE001 - 日志钩子坏了不该打断审校
                pass

    def _writer(self, name: str, /, **params: Any) -> dict:
        #: 这张注册表在 `__init__` 里已绑定 `bound_role="H"`（`P-14` 的调用期判据），
        #: 所以这里不必逐次传 `role=` —— 逐次传反而会让"它到底代表谁"有两个来源。
        res = self.writers.call(name, **params)
        self.tool_calls.append({"tool": name, "ok": res.ok, "error": res.error})
        if not res.ok:
            # 不可静默：审校动作没做成，调用方必须知道（否则会以为"审过了、没问题"）。
            raise ReviewError(f"{name} 调用失败：{res.error}")
        return res.data

    # ------------------------------------------------------------ 审校

    def review(
        self,
        doc_id: str,
        *,
        round_no: int | None = None,
        dependencies: Any = _UNSPECIFIED,
    ) -> dict:
        """审一份稿件：落发现 + 更新文档状态（转发 `review.review_document`）。

        返回 ``{"doc_id","checked","round","new_findings","duplicate_skipped",
        "reopened","error_count","warning_count","info_count","dep_check","status",
        "status_updated","status_error","verdict","reason"}``。

        `dependencies` 三态：不传 = 从库里读该稿件的依赖；显式 `None` = 没查
        （此时 `dep_check["checked"] is False`，verdict 是 `"unverified"` ——
        「依赖都闭合」这句话在没有查过的情况下不许说出口）。
        """
        params: dict[str, Any] = {"doc_id": str(doc_id)}
        if round_no is not None:
            params["round_no"] = int(round_no)
        if dependencies is not _UNSPECIFIED:
            params["dependencies"] = None if dependencies is None else [dict(d) for d in dependencies]
        data = self._writer("review.review_document", **params)
        self._emit(
            f"审校 doc:{doc_id} round={data.get('round')}：verdict={data.get('verdict')}，"
            f"新增 {len(data.get('new_findings') or [])} 条、跳过重复 "
            f"{data.get('duplicate_skipped')} 条，error={data.get('error_count')}，"
            f"status={data.get('status')}"
            + ("" if data.get("status_updated") else f"（状态未更新：{data.get('status_error')}）")
        )
        return data

    def verify_fixes(self, doc_id: str, *, round_no: int, dependencies: Any = _UNSPECIFIED) -> dict:
        """复审：重跑检查判 `fixed` / 仍 `open`（转发 `review.verify_fixes`）。

        `error` 级发现一直不修、且已到 `max_review_rounds` ⇒ 文档置
        `unresolved_review`，并且返回值里 `unresolved_findings` 明确列出
        未解决的发现（不许隐藏）。

        `dependencies` 与 :meth:`review` 同一套三态：不传 = 从库里读该稿件的依赖；
        显式 `None` = 没查（复审结论不覆盖依赖闭合这一维）；显式给行序列 = 按给的清单查。

        ## 为什么这个参数必须能传进来（此前缺口）

        下游 `review.verify_fixes` 一直收 `dependencies`，而本方法与
        `capabilities` 的声明都不收 —— 于是复审永远退回"从库里读该稿件的依赖"，
        而 `dependencies_for_doc` 只认 `used_by` 的 `doc:` 前缀。一条挂在
        别的锚点上的依赖（实测：`paper/main.tex#prop:step`）在复审眼里根本不存在，
        于是上一轮如实报出的 `dangling_dep`（`external_unavailable`）
        会被判成 `resolved ⇒ fixed` —— 那是把一个"已知拿不到的前提"
        静默宣告成"已经解决"。修好之后，复审能拿到同一份清单，
        判据与 `review` 逐字一致（实测 2026-09-29：P3 台账的 13 条未刊依赖）。
        """
        params: dict[str, Any] = {
            "doc_id": str(doc_id),
            "round_no": int(round_no),
            "max_review_rounds": self.max_review_rounds,
        }
        if dependencies is not _UNSPECIFIED:
            params["dependencies"] = None if dependencies is None else [dict(d) for d in dependencies]
        data = self._writer("review.verify_fixes", **params)
        self._emit(
            f"复审 doc:{doc_id} round={round_no}：verdict={data.get('verdict')}，"
            f"resolved={len(data.get('resolved') or [])}，still_open={len(data.get('still_open') or [])}，"
            f"未解决(error)={len(data.get('unresolved_findings') or [])}"
        )
        return data

    def list_findings(self, **filters: Any) -> dict:
        """只读列举发现（走 H 的自由工具箱）。"""
        res = self.tools.call("review.list_findings", **filters)
        self.tool_calls.append({"tool": "review.list_findings", "ok": res.ok, "error": res.error})
        if not res.ok:
            raise ReviewError(f"review.list_findings 调用失败：{res.error}")
        return res.data

    def review_report(
        self,
        doc_id: str,
        *,
        own_errors: Any = None,
        round_no: int = 1,
        dependencies: Any = _UNSPECIFIED,
        run_evidence: Mapping[str, Any] | None = None,
        banned_words: Any = None,
        claim_counts: Mapping[str, Any] | None = None,
    ) -> dict:
        """产出 G1–G15 的完整审校报告（markdown 落盘，转发 `review.report`）。

        ## 这份报告必须以三样东西为骨架（`draft/17` §8.4）

        1. 被审版本的内容 hash（G11）：报告头写 `revision_hash`。没有它，
           报告里的"第几行/第几条"在稿件被改过之后全部失效。
        2. 零发现自证（G13）：每道报"零发现"的门都必须带"我用了什么过程、
           数出了什么数字"。只写"无问题"不合规 —— 参考体例的实测范例
           （`p6_..._REFEREE.md:48-56`）逐字写出了它扫了什么、数出了什么。
        3. 『我这一轮犯的错』一节（G15）：在报告头里，缺失则退回。

        ## `own_errors` 的三态（这是本方法最要紧的一处）

        ==================  ==========================================================
        传什么                行为
        ==================  ==========================================================
        `None`（默认/不传）  不替调用方编造：传空列表让报告生成，但在日志与返回值里
                             显式登记"本轮没有登记自身错误"（`own_errors_registered=False`）
        `[]`                 合法：显式声明"本轮零自身错误"
        非空列表              逐条写进报告头
        ==================  ==========================================================

        为什么不把 `None` 直接当成 `[]`：那会让"我没写"与"我写了『没有』"
        在报告里长得一模一样 —— 而 G15 的全部意义就是让前者不可接受。
        这里选择"生成报告 + 显式留痕"而不是抛异常，是因为 H 的审校流程
        （`review` / `verify_fixes`）不该因为报告元数据没填就整个跑不动；
        但报告里与返回值里必须看得见这件事没填。
        """
        registered = own_errors is not None
        errs = [str(x) for x in (own_errors or [])]
        params: dict[str, Any] = {
            "doc_id": str(doc_id),
            "own_errors": errs,
            "round_no": int(round_no),
        }
        if dependencies is not _UNSPECIFIED:
            params["dependencies"] = None if dependencies is None else [dict(d) for d in dependencies]
        if run_evidence is not None:
            params["run_evidence"] = dict(run_evidence)
        if claim_counts is not None:
            params["claim_counts"] = dict(claim_counts)
        if banned_words is not None:
            params["banned_words"] = [str(x) for x in banned_words]
        data = self._writer("review.report", **params)
        data["own_errors_registered"] = registered
        self._emit(
            f"审校报告 doc:{doc_id} → {data.get('report_path')}："
            f"verdict={data.get('verdict')}（pass={data.get('pass_count')}、fail={data.get('fail_count')}、"
            f"unknown={data.get('unknown_count')}、not_applicable={data.get('not_applicable_count')}），"
            f"被审版本 hash={data.get('revision_hash')}，"
            + (f"自身错误已登记 {len(errs)} 条" if registered else "自身错误未登记（own_errors 缺失）")
            + f"；没查成的门={data.get('unknown_gates')}"
        )
        return data

    # ------------------------------------------------------------ 自检

    def selftest(self) -> int:
        """对当前 store 做一次最小自检：工具面是否只读、发现是否可写。

        返回 0（成功）/ 1（失败）。
        """
        try:
            surface = self.tools.describe()
            ok_surface = bool(surface) and all(
                t["side_effect"] in _H_READONLY_SIDE_EFFECTS for t in surface
            )
            rows = self.store.rows("documents")
            ok_write = True
            if rows:
                data = self.review(str(rows[0].get("doc_id")), dependencies=None)
                ok_write = data.get("checked") is True and data.get("dep_check", {}).get("checked") is False
            ok = ok_surface and ok_write
            self._emit(
                f"selftest：{'通过' if ok else '失败'}（自由工具箱 {len(surface)} 个只读工具；"
                f"拒绝的写工具 {len(getattr(self.tools, 'refused_write_tools', []))} 个）"
            )
            return 0 if ok else 1
        except Exception as e:  # noqa: BLE001 - 自检要给出结论，而不是把异常抛给调用方
            self._emit(f"selftest 失败：{type(e).__name__}: {e}")
            return 1


# ---------------------------------------------------------------- 自检（模块级）
#
# 本段全部是自检夹具，不属于 H 的运行路径：`_selftest()` 在一个临时工作区里
# 造数据、跑一遍完整审校、然后退出。它写"知识表"（concepts/relations/literature/
# dependencies）是为了让"审校前后逐字节不变"这条运行期只读断言非空、有意义 ——
# 空表与空表相等说明不了任何事。
#
# 但"夹具"不能是口头豁免：`tests/test_core_audit_efgh.py` 会扫本文件的 AST，
# 要求所有写盘调用（`store.tx(...)` 与绕过 store 的 `write_text`/`_atomic_write`）
# 要么落在下面这个清单里的函数内，要么根本不存在；并且在 `AgentH` 类体内
# 一个都不许有（H 只能通过 `self.writers` 落库），也不许出现任何一处
# `X["claims"] = ...`（改稿是 G 的职责）。
# 新增任何一处写入都会让那几条测试变红 —— 包括想"顺手在自检里再改一下数据"的改动。
#
#: 允许直接写盘的自检夹具函数（穷举，新增必须同步改这里并说明理由）。
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
        from . import signatures as _SIG

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


def _selftest() -> int:
    # 运行方式：在 src/ 下执行 `python -m agentflow.agent_h`（或设 PYTHONPATH=src 后在任意目录执行）
    import json
    import sys
    import tempfile

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # 有些 stdout 替身没有 reconfigure；切编码失败不该让自检本身挂掉
        pass

    print("=" * 72)
    root = Path(tempfile.mkdtemp(prefix="agentflow-agenth-"))
    st = Store(root)
    st.init()
    print(f"[0] 临时工作区：{root}")

    # ---- 知识表（用于"运行期只读"的逐字节比对）
    with st.tx("concepts", "relations", "literature", actor="seed", note="fixture") as tx:
        tx.upsert("concepts", S.Concept(concept_id="0000", name="谱", definition="d", created_at=S.now_iso(), updated_at=S.now_iso()).to_dict())
        tx.upsert("concepts", S.Concept(concept_id="0001", name="区间", definition="d", created_at=S.now_iso(), updated_at=S.now_iso()).to_dict())
        tx.upsert(
            "literature",
            S.Literature(lit_id="0000", title="Spec S̃_m", type="J", summary="s", path=None, processed=True, added_at=S.now_iso()).to_dict(),
        )
        tx.upsert(
            "relations",
            S.Relation(
                relation_id="0000", concept_ids=["0000", "0001"], description="谱落在区间内",
                lit_id="0000", page_range=S.PageRange(12, 13, "pp. 12-13"), quote="Spectrum lies in the interval",
                statement="谱落在区间内", concept_group_key="0000|0001", dedup_key="k0", status="active",
                quote_verified=True, created_at=S.now_iso(),
            ).to_dict(),
        )
    print("[1] 造数据：概念 2 个、文献 1 篇、关系 1 条")

    # ---- 干净稿件（防误伤，schema 合法且审校也该干净）
    #
    # `evidence_kind` 是 `cross_check` 而不是 `proof`：这条断言的引文只有
    # `rel:0000`（一条关系）与 `lit:0000#p.12-13`（一页文献），没有形式化检查器
    # 参与过。标成 `proof` 是误标，而 `D-1` 的写入期判据（`doc_tools.check_proofs`）
    # 会在改写这条稿件的路径上拒绝它 —— 自检第 [7] 步就是这么红的。
    # 降级之后它仍然是"干净稿件"：审校判 `accepted`、`error=0`（见本自检第 [4] 步）。
    # `disclaimer` 必须跟着填：`cross_check` 的「不构成证明」声明是结构强制的。
    clean = _seed_document(
        st,
        doc_id="0000",
        claims=[
            {
                "claim_id": "claim-1", "section": "主要结果", "text": "谱落在区间内。",
                "evidence_kind": "cross_check", "citations": ["rel:0000", "lit:0000#p.12-13"],
                "is_negative": False, "negation_kind": None,
                "disclaimer": CROSS_CHECK_DISCLAIMER,
            }
        ],
    )
    # ---- 第二份：schema 合法但审校不合规（把 cross_check 说成"已证明"）。
    # 它存在的意义：坏数据并不总能被 schema 拦住，而也只有这样的稿件才允许
    # 状态真正被写进 unresolved_review（schema 不合法的稿件连状态都写不进去）。
    _seed_document(
        st,
        doc_id="0002",
        claims=[
            {
                "claim_id": "claim-1", "section": "数值证据",
                "text": "数值抽样支持该结论，因此我们已证明它成立。",
                "evidence_kind": "cross_check", "citations": ["lit:0000"],
                "is_negative": False, "negation_kind": None,
                "disclaimer": CROSS_CHECK_DISCLAIMER,
            }
        ],
    )
    # ---- 依赖：一条已知边界（external_unavailable）+ 一条悬空
    with st.tx("dependencies", actor="seed", note="fixture") as tx:
        for dep_id, status, reason in (
            ("0000", "external_unavailable", "companion book 不在本项目可得范围内（已知边界）"),
            ("0001", "dangling", "尚未找到来源"),
        ):
            row = S.Dependency(
                dep_id=dep_id, used_by="doc:0001#claim-9", kind="theorem",
                label=f"依赖 {dep_id}", status=status, status_reason=reason,
                created_at=S.now_iso(),
            )
            row.validate()
            tx.upsert("dependencies", row.to_dict())
    print("[2] 稿件 2 份（干净 1 份、把 cross_check 说成证明的 1 份）、依赖 2 条")

    h = AgentH(st, config={"max_review_rounds": 2})
    print(f"[3] H 的自由工具箱（{len(h.tools)} 个，全部应为 none/read）：")
    for t in h.tools.describe():
        print(f"      {t['name']:<28} side_effect={t['side_effect']}")
    refused = getattr(h.tools, "refused_write_tools", [])
    print(f"    被**显式拒绝**的写工具 {len(refused)} 个（H 若持有它们就能改稿）：")
    for r in refused[:8]:
        print(f"      ✗ {r['name']}（{r['side_effect']}）")

    print("[4] 干净稿件：防误伤（好数据必须过）+ 运行期只读的可核对形式")
    before = {n: (st.data / n).read_bytes() for n in ("concepts.json", "relations.json", "literature.json")}
    docs_before = json.loads((st.data / "documents.json").read_text(encoding="utf-8"))
    r0 = h.review("0000", dependencies=[])
    docs_after = json.loads((st.data / "documents.json").read_text(encoding="utf-8"))
    max_round = docs_before["rows"][0].get("review_rounds")
    print(f"    verdict={r0['verdict']} error={r0['error_count']} warning={r0['warning_count']} "
          f"status={r0['status']} dep_checked={r0['dep_check']['checked']}")
    same = all((st.data / n).read_bytes() == before[n] for n in before)
    changed = []
    for rb, ra in zip(docs_before["rows"], docs_after["rows"]):
        diff = sorted({k for k in set(rb) | set(ra) if rb.get(k) != ra.get(k)})
        if diff:
            changed.append((rb.get("doc_id"), diff))
    print(f"    知识表逐字节不变={same}；documents.json 变化点={changed}（应只有 status）")
    if r0["error_count"] or r0["verdict"] != "accepted" or r0["status"] != "accepted":
        print("    ❌ 干净稿件被误伤（或没有被接受）")
        return 1
    if not same or changed != [("0000", ["status"])]:
        print("    ❌ 运行期只读被破坏（或变化点不止 status）")
        return 1
    _ = max_round

    print("[5] 终止性 + 状态落地（schema 合法但把 cross_check 说成证明）")
    b0 = h.review("0002")
    print(f"    review：verdict={b0['verdict']} error={b0['error_count']} status={b0['status']} "
          f"status_updated={b0['status_updated']}")
    for f in b0["new_findings"]:
        print(f"      [{f['level']}] {f['kind']} @{f['target']}：{f['message'][:40]}；evidence={f['evidence'][:70]!r}")
    b1 = h.verify_fixes("0002", round_no=2)
    now_status = next(r["status"] for r in st.rows("documents") if r["doc_id"] == "0002")
    print(f"    不修 → 复审 verdict={b1['verdict']} 未解决(error)={len(b1['unresolved_findings'])} 库中状态={now_status}")
    if b1["verdict"] != "unresolved_review" or now_status != "unresolved_review" or not b1["unresolved_findings"]:
        print("    ❌ 未到 unresolved_review（或状态没落地 / 未解决项被隐藏）")
        return 1
    for f in b1["unresolved_findings"]:
        print(f"      未解决：✗ {f['finding_id']} {f['kind']} @{f['target']} level={f['level']}")
    # 改稿是 G 的职责，不是 H 的。
    #
    # 这里此前直接 `st.tx("documents")` 改 `row["claims"]`（actor 写成 "fake-G"）。
    # 那是本模块最不该出现的东西：一份明文可抄的"绕过 H 只读"的写法，
    # 就写在"证明 H 只读"的那个文件里。FC-27 的教训正是"测试全绿、上线即越权" ——
    # 一句 `row["claims"] = ...` 加一个自嘲的 actor 名，足够让任何人以为这条约束
    # 只是建议。改成调用真正的改写方（`AgentG.revise`）：自检照样走完闭环，
    # 而 agent_h.py 里再也没有任何一处碰过 `documents.claims`。
    try:
        from .agent_g import AgentG

        AgentG(st, config={"docs_subdir": "documents"}).revise(
            "0002",
            new_claims=[dict(c) for c in clean["claims"]],
            note="自检：由 G（稿件的所有者）按审校意见改稿",
        )
    except Exception as e:  # noqa: BLE001 - 拿不到 G 时必须显式失败，不许静默跳过
        print(f"    ❌ 拿不到 G（{type(e).__name__}: {e}）⇒ '修好后复审'这一步**未验证**")
        return 1
    b2 = h.verify_fixes("0002", round_no=3)
    print(f"    修好后 → 复审 verdict={b2['verdict']} resolved={len(b2['resolved'])} "
          f"still_open={len(b2['still_open'])} 库中状态={b2['status']}")
    # ---- `R-59`（`draft/28` §161.4 的口径 ②）之后的期望值。
    #
    # 本自检原来断言 `b2["status"] == "accepted"` —— 那正是被修掉的那个形态：
    # G 改稿之后内容哈希变了，而签名还钉着旧版本，复审却把状态置回 accepted
    # ⇒ `verify_all` 报 `stale_signature`（"改稿之后旧审批不许沿用"）。
    # 现在 `verify_fixes` 只在"台账里有签名钉住当前这一版"时才置 accepted；
    # 否则置 `in_review` 并在 reason 里点名要重新 review。
    #
    # 所以这一步拆成两条更强的断言：
    #   ① 复审判 accepted（判断本身没变），但状态停在 `in_review` 且理由写明；
    #   ② 再走一次 `review`（H 的唯一签发入口）⇒ 状态 accepted 且签名钉在这一版上。
    # ② 此前没有任何地方验过，而它恰是"接受 = 有一次针对这一版的审+签"的机器判据。
    if b2["verdict"] != "accepted" or b2["status"] != "in_review":
        print("    ❌ 修好后应判 accepted、状态停在 in_review（等一次针对这一版的审+签）")
        return 1
    if "不置 `accepted`" not in str(b2.get("reason") or ""):
        print("    ❌ 复审理由里没有逐字写明'不置 accepted'的原因 ⇒ 读者看不出状态为什么没回去")
        return 1
    from . import signatures as _SIG

    b3 = h.review("0002", dependencies=[])
    _doc2 = next(r for r in st.rows("documents") if r["doc_id"] == "0002")
    _recs, _bad = _SIG.read_ledger(_SIG.ledger_path(root))
    _pinned = _SIG.signed_revision(_doc2, _recs) is not None
    print(f"    重新审一次 → verdict={b3['verdict']} 状态={b3['status']} "
          f"签名钉住这一版={_pinned}")
    if b3["verdict"] != "accepted" or b3["status"] != "accepted":
        print("    ❌ 重新审一次应判 accepted 并把状态落到 accepted")
        return 1
    if not _pinned:
        print("    ❌ 接受了却没有签名钉在当前这一版上 ⇒ 旧审批被沿用了（R-59 的形态）")
        return 1

    # ---- 最后才把"schema 不合法的坏行"注入盘上。
    # 顺序很重要：`store.tx` 提交时会校验整张表，一条坏行会让之后所有对
    # documents 的写入都失败。这本身就是一条值得展示的事实 —— 而 H 正是要在
    # 这种局面下仍然能把发现落库（发现写的是另一张表）。
    #
    # 这里写成一整行字面量，而不是"拿一份合法稿件把它的 claims 换掉"。
    # 后者（`bad = dict(clean); bad["claims"] = ...`）在源码里与
    # "绕过 H 只读、偷偷改稿"长得一模一样 —— 而这个文件是用来证明 H 只读的。
    # 我们现在要造的是"一份坏输入喂给 H"，不是"改动一行已有稿件"，
    # 字面量把这件事写清楚；同时 `tests/test_core_audit_efgh.py` 会扫源码，
    # 断言本文件里一处 `X["claims"] = ...` 都没有。
    bad = {
        "doc_id": "0001",
        "kind": "paper",
        "title": "自检坏稿件（绕过 schema 直接改盘）",
        "markdown_path": None,
        "sections": [],
        "claims": [
            {"claim_id": "claim-9", "section": "x", "text": "这是一条没有任何引用的断言。",
             "evidence_kind": "heuristic", "citations": [], "is_negative": False,
             "negation_kind": None, "disclaimer": ""},
            {"claim_id": "claim-10", "section": "x", "text": "该推广不成立。",
             "evidence_kind": "heuristic", "citations": ["lit:0000"], "is_negative": True,
             "negation_kind": None, "disclaimer": ""},
        ],
        "open_problems": [],
        "status": "draft",
        "review_rounds": 0,
        "created_at": S.now_iso(),
        "updated_at": S.now_iso(),
    }
    _inject_raw_document(st, bad)

    print("[6] 坏稿件（绕过 schema 直接改盘）：无引用 / 否定未分类 / 依赖分级")
    r1 = h.review("0001")
    print(f"    verdict={r1['verdict']} error={r1['error_count']} warning={r1['warning_count']} "
          f"status_updated={r1['status_updated']}")
    if not r1["status_updated"]:
        print(f"    （状态未更新，**如实记录**而不是假装成功：{str(r1['status_error'])[:90]}）")
    for f in r1["new_findings"]:
        print(f"      [{f['level']:^7}] {f['kind']:<22} @{f['target']:<10} {f['message'][:34]}")
        print(f"                 evidence = {f['evidence'][:88]}")
    f_rows = [f for f in st.rows("review_findings") if str(f["doc_id"]) == "0001"]
    lvl = {f["target"]: f["level"] for f in f_rows if f["kind"] == "dangling_dep"}
    uv = next((f for f in f_rows if f["kind"] == "unsupported_claim"), None)
    print(f"    依赖分级（FC-13）：external_unavailable={lvl.get('0000')}（应为 warning）、"
          f"dangling={lvl.get('0001')}（应为 error）")
    print(f"    unsupported_claim 的 evidence（必须含实际值）：{str(uv and uv['evidence'])[:80]!r}")
    if lvl.get("0000") != "warning" or lvl.get("0001") != "error" or uv is None or "citations" not in uv["evidence"]:
        print("    ❌ 依赖分级或发现证据不对")
        return 1

    print("[7] 去重：同一份坏稿件再审一次")
    n_before = len(st.rows("review_findings"))
    r3 = h.review("0001")
    n_after = len(st.rows("review_findings"))
    print(f"    新增={len(r3['new_findings'])} 重复跳过={r3['duplicate_skipped']} "
          f"finding 行数 {n_before} → {n_after}")
    if r3["duplicate_skipped"] <= 0 or n_after != n_before:
        print("    ❌ 去重失效")
        return 1

    print("[8] 复审：error 一直不修 ⇒ 到轮数上限必须置 unresolved_review 并列出未解决项")
    v1 = h.verify_fixes("0001", round_no=2)
    print(f"    verdict={v1['verdict']} resolved={len(v1['resolved'])} still_open={len(v1['still_open'])} "
          f"未解决(error)={len(v1['unresolved_findings'])} status={v1['status']}"
          + ("" if v1["status_updated"] else f"（状态未更新：{str(v1['status_error'])[:70]}）"))
    if v1["verdict"] != "unresolved_review" or not v1["unresolved_findings"]:
        print("    ❌ 到轮数上限仍未解决时应置 unresolved_review 并**列出**未解决发现")
        return 1

    print("[9] 三态：显式 dependencies=None ⇒ 依赖闭合**没查**，不许判 accepted")
    r2 = h.review("0002", dependencies=None)
    print(f"    dep_check.checked={r2['dep_check']['checked']} verdict={r2['verdict']} status={r2['status']}")
    print(f"    reason={r2['reason'][:170]}")
    if r2["dep_check"]["checked"] is not False or r2["verdict"] == "accepted":
        print("    ❌ 把'没查'当成了'依赖都闭合'")
        return 1

    print("=" * 72)
    print("SELF-CHECK DONE（agent_h）")
    return 0


if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    raise SystemExit(_selftest())
