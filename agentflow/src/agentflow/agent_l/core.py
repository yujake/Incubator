# -*- coding: utf-8 -*-
"""智能体 L（Lean 形式化者）：公共骨架（构造期 / 路径守卫 / 自检闸 / 结论形状）。

## L 是谁（业主 2026-10-22 的施工单）

照 E 的 Lean 面复制出来的一个可运行角色：E 里与 Lean 开关 / 形式化有关的实现
搬过来，E 一行不删、行为不改。

协作面（业主 2026-10-22 晚的最终裁定，逐字）：只有 B 可以派 L，L 允许派 C 来梳理
证明链，消费 B 的定理证明库，可向 B 汇报形式化过程中遇到的困难、要求 B 完善证明并重新
得到 V 签，若缺陷严重，B 应通知 D 开展研究处理证明难点。三个读数都由声明派生
（`specs/l.py` + `specs/b.py` → `capabilities`）：入边恰好 `B → L`、出边恰好
`L → C`、可召唤。越权一律 `forbidden_edge`；Lean 关着时 L 连角色都不存在
（`leanscope`），那一条边也看不见。

## 与 E 的关系：抄的是"面"，不是"桥"

`verify.check_formal`（桥接层，FC-27 禁改区）是唯一实现，L 直接调它。
所以"E 会怎么读检查器"与"L 会怎么读检查器"结构化地不可能分家 —— L 抄的是
E 在 Agent 这一层的收口逻辑（路径守卫、理由折叠、三态形状），桥接只有一份。

`_CheckFormal` 也是这样复用的：L 的 `_CheckFormalL` 继承 E 的那个混入，
只在前面加一道自检闸（`leantoolchain`），其它逐字走 E 的实现。这样
"E 的行为改不改"这件事不需要靠人记得 —— 它压根没有第二份。

## 自检闸（业主第二句话："别一堆报错，很久没测了"）

任何 Lean 调用之前先过 `leantoolchain.lean_selfcheck_reading()`。它不是 `usable`
时，L 的一切形式化结论记 `unknown`，并把原因压成一行：

- 不起检查器（不 spawn `lean`、不写临时文件）；
- 不抛栈：返回的还是一个形状固定的 dict（与受控拒绝同形）；
- 不连撞同一条错误：同一份自检读数在一个 AgentL 实例里只取一次，
  失败说明也只报一行（`one_line`）。

`usable` 时：L 必须真的把 `.lean` 写到盘上（`formalize`），并且真的调用检查器；
结论三态由检查器的原话与真实退出码推出，不由模型的自我陈述推出。

## 三处刻意的取舍

- `_resolve` 从 E 的实现逐字搬来（`agent_e/core.py`），不抽公共函数：抽出去就得改
  E 的 import，而"不许改 E 的行为"这条纪律最便宜的守法就是"E 的文件一个字节都不动"。
  `_formal_refusal` 是同名的转发口，不是第二份实现（E 的 `check_formal` 调的就是
  这个名字；漏了它，一次受控拒绝会在工具面上变成 `kind="unexpected"`，
  见 :meth:`_Core._formal_refusal` 的 docstring 与被接住的 `draft/146` D29）。
- `install_l_tools` 只装 L 自己的 `formal.*`：L 不经过 `verify.*` 的工具面，
  它是直接调桥接层函数的（与 `AgentE.check_formal` 同一条路）。
- `llm` 参数只保留在签名里（与 E 一致）：形式化这一路一次模型调用都没有，
  判读必须由检查器决定（FC-16）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .. import leantoolchain as LT
from .. import schema as S
from ..agent_e._support import ExperimentError
from ..store import Store
from ..tools import ToolRegistry
from ._support import SELFCHECK_REASONS, one_line
from .check_formal import _CheckFormalL
from .formalize import _Formalize
from .record import _Record
from .report import _Report


#: 受控拒绝的理由码（派发层只认 `schema.REFUSAL_REASONS` 里的取值）。
#: L 自己的理由码（`path_outside_workspace` / `tool_failed` …）留在 `reason` 与
#: `detail` 里，不进这一格 —— 两套词表不许折叠（`draft/146` D25 ③ 的口径）。
_REFUSAL_REASON_FOR_FORMAL = "invalid_params"
assert _REFUSAL_REASON_FOR_FORMAL in S.REFUSAL_REASONS, (
    "受控拒绝的理由码必须来自 schema.REFUSAL_REASONS")


def _formal_face(reading: Mapping[str, Any] | None) -> dict[str, Any]:
    """自检读数里"该给调用方看的那几格"（不把整份读数塞进每一次结论）。

    读不到读数时给一个空壳 + `state=""`：那件事本身是"没读到"，不是"可用"。
    """
    got = reading if isinstance(reading, Mapping) else {}
    negative = got.get("negative")
    return {
        "state": str(got.get("state") or ""),
        "checked": bool(got.get("checked")),
        "enabled": bool(got.get("enabled")),
        "enabled_source": str(got.get("enabled_source") or ""),
        "source": str(got.get("source") or ""),
        "lean_path": str(got.get("lean_path") or ""),
        "version": str(got.get("version") or ""),
        "sha256": str(got.get("sha256") or ""),
        "negative_exit_code": (negative.get("exit_code")
                               if isinstance(negative, Mapping) else None),
        "note": one_line(got.get("note")),
    }


class _Core:
    """L 的构造期与三件骨架（日志 / 路径守卫 / 受控结论形状）。"""

    def __init__(
        self,
        store: Store,
        *,
        config: Mapping[str, Any] | None = None,
        workspace_root: str | Path | None = None,
        log: Any | None = None,
        llm: Any | None = None,
        tools: ToolRegistry | None = None,
        actor: str = "agent-L",
    ) -> None:
        self.store = store
        self.cfg: dict[str, Any] = dict(config or {})
        self.actor = actor
        #: 与 E 同一条纪律：形式化这一路一次模型调用都没有。留着它（而不是删掉）
        #: 是为了让 `host` 的装配面对所有角色是同一个形状（少一个形参就得在装配层写分支）。
        self.llm = llm
        self.log = log
        self.default_timeout = int(self.cfg.get("timeout", 600))
        root = workspace_root if workspace_root is not None else self.cfg.get("workspace_root")
        if root is None:
            root = Path(self.store.root)
        self.workspace_root = Path(root).resolve()
        self.last_run: dict[str, Any] = {}
        self.last_tool_errors: list[dict] = []
        #: 这一趟的自检读数（同一实例只取一次：`leantoolchain` 自己也缓存，
        #: 这里再存一份是为了让"同一条失败只报一行"不依赖下游的缓存行为）。
        self._lean_reading: dict[str, Any] | None = None
        self._lean_checked = False
        self.tools = (tools if tools is not None
                      else install_l_tools(self.store, workspace_root=self.workspace_root))
        if self.tools.bound_role is None:
            self.tools.bound_role = "L"

    # ------------------------------------------------------------ 日志
    def _log(self, message: str, **extra: Any) -> None:
        if self.log is not None:
            try:
                self.log(message, **extra)
            except Exception:  # noqa: BLE001 - 日志失败不该打断形式化
                pass

    # ------------------------------------------------------------ 路径守卫
    def _resolve(self, rel: str | Path) -> Path:
        """把相对路径解析到工作区内，越界即拒绝（与 `agent_e/core.py` 逐字同一判据）。

        为什么这条闸必须在 `open()` 之前：`script_path` 与 `formalize` 的目标路径
        都是"外部输入 -> 读写磁盘"的通道。允许 `../` 就等于允许框架读写工作区外的
        任意文件，而这不会报任何错 —— 它只会"成功"。
        """
        p = Path(str(rel))
        cand = (p if p.is_absolute() else (self.workspace_root / p)).resolve()
        try:
            cand.relative_to(self.workspace_root)
        except ValueError:
            raise ExperimentError(
                f"路径越出工作区：{rel!r}（工作区={self.workspace_root}）。"
                "拒绝读写工作区外的文件"
            ) from None
        return cand

    # ------------------------------------------------------------ 自检
    def _lean_reading_now(self, *, refresh: bool = False) -> dict[str, Any]:
        """取这一趟的 Lean 自检读数（同一实例只取一次；`refresh=True` 强制重查）。

        为什么在 Agent 这一层再缓存一次：`leantoolchain.lean_selfcheck_reading`
        是模块级缓存（跨实例共享），而"同一个失败在一个实例里被报了几次"是
        调用方视角的事实 —— 这一层要能保证"这一趟只问一次、只报一行"。
        """
        if refresh or not self._lean_checked:
            self._lean_reading = LT.lean_selfcheck_reading(root=self.workspace_root)
            self._lean_checked = True
        return dict(self._lean_reading or {})

    def _lean_selfcheck(self) -> tuple[str, str]:
        """`(state, 一行原因)`。state 是 `leantoolchain` 的四档之一。

        刻意保持"无参、可替换"：判据要 monkeypatch 的正是"读自检结论"这一步
        （`tests/test_l_formalizes_what_b_says.py` 的反真空那一条），
        所以它必须是这个类上一个可被替换的方法，而不是内联在两处调用点。
        """
        reading = self._lean_reading_now()
        state = str(reading.get("state") or "") or "unknown"
        if state == "usable":
            return "usable", ""
        if state == "off":
            why = ("Lean 形式化这一趟是关着的（toolchain.lean_enabled=false 或 "
                   "AGENTFLOW_LEAN_ENABLED=0）：自检没跑，也没起子进程")
        elif state == "unusable":
            why = one_line(_first_problem(reading) or "自检结论 unusable")
        elif state == "unknown":
            why = one_line(_first_problem(reading) or "自检没查成")
        else:
            why = "没有自检读数（读不到它不等于通过）"
        return state, why

    def _selfcheck_reason(self, state: str) -> str:
        """自检状态 -> L 的理由码（三档各自有码，见 `_support.SELFCHECK_REASONS`）。"""
        return SELFCHECK_REASONS.get(state, SELFCHECK_REASONS["unknown"])

    # ------------------------------------------------------------ 结论形状
    def _refusal(self, claim: str, reason: str, detail: str, *,
                 status: str = "unknown") -> dict[str, Any]:
        """受控结论形态（未查成 / 被拒都走它）。

        为什么单独一个方法：键集合必须在每一条分支上都成立（E 的
        `_formal_refusal` 逐字论证过这件事：键集合随分支变，判据就在那条分支上失效）。
        L 在 E 的九个键之外只加四格（`status` / `problems` / `lean` / `lean_path`），
        于是"E 的键还在不在"可以被逐键比对。
        """
        face = _formal_face(self._lean_reading)
        return {
            "checked": False,
            "verified": None,
            "claim": claim,
            "reason": reason,
            "detail": detail,
            "verifier_output": "",
            "missing_imports": [],
            "verifier_status": "",
            "exit_code": None,
            "status": status,
            "problems": [detail] if detail else [],
            "lean": face,
            "lean_path": face["lean_path"],
        }

    def _formal_refusal(self, claim: str, reason: str, detail: str, *,
                        refusal_reason: str = _REFUSAL_REASON_FOR_FORMAL) -> dict[str, Any]:
        """受控拒绝口（E 的 `check_formal` 调的就是这个名字，见 `_CheckFormalL`）。

        为什么必须有这个名字（`draft/146` D29）：`_CheckFormalL` 继承 E 的
        `check_formal`，而 E 那两条拒绝分支（路径越界 / 桥接层 `not res.ok`）调的是
        `self._formal_refusal(...)`。L 原来只定义了 `_refusal`，于是 `formal.check_formal`
        走到那条分支时抛 `AttributeError`，被 `ToolRegistry.call` 兜成
        `kind="unexpected"`：调用方指了一个越界路径、或同时给了两份具名声明，
        在下游读起来与"L 内部有 bug"一模一样 —— 而前者本该是一句读得懂的话。

        为什么是转发而不是复制一份体：拒绝体只有一处（:meth:`_refusal`），
        键集合随分支变，判据就会在缺的那条分支上失效。这里只补三格，使形状与
        `draft/146` D25 的第三档一致：`refused=True` 是第三态位，
        `refusal_reason` 是派发层认的那一格受控理由码，`status="unknown"` 说的是
        "这一趟没有结论"。L 自己的理由码仍留在 `reason` 与 `detail` 里（它不在
        `REFUSAL_REASONS` 里），行上的受控理由与角色的原话因此各占一格
        （见 `conductor._end_from_payload` 的 D25 ③）。

        与自检闸那一支的分工：闸门拦下来的是"没查成"（:meth:`_refusal`，
        它不带 `refused` 那一格 ⇒ 派发层读成"没声明拒绝"，落 `no_result`），
        这里拒绝的是"这次调用本身不成立"（路径越界 / 桥接层受控失败），
        两者不是同一件事 —— 把前者也标成拒绝，"Lean 没装好"就会被记成"框架说了不"。
        """
        out = self._refusal(claim, reason, detail)
        out.update({
            "refused": True,
            "refusal_reason": refusal_reason,
            "status": "unknown",
        })
        return out

    def _finalize(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """把桥接层的原样回答折叠成三态结论（只加四格，不改 E 给的九个键）。

        三态只由受控理由给出：`verified` 是检查器说通过；`failed` 是检查器说了不通过
        （`FAILED_REASONS` 那一族）；其余一律 `unknown`。刻意不从 `verified is False`
        推 `failed` —— 那会把"没查成"读成"命题可疑"，而那正是 E 的 docstring 里
        反复登记过的那一种折叠。
        """
        from ._support import FAILED_REASONS

        out = dict(data)
        reason = str(out.get("reason") or "")
        if reason == "verified":
            status = "verified"
        elif reason in FAILED_REASONS:
            status = "failed"
        else:
            status = "unknown"
        face = _formal_face(self._lean_reading)
        problems: list[str] = []
        if status == "unknown":
            problems.append(one_line(out.get("detail") or f"没查成：{reason or '未知理由'}"))
        out.update({"status": status, "problems": problems, "lean": face,
                    "lean_path": face["lean_path"]})
        return out


def _first_problem(reading: Mapping[str, Any]) -> str:
    """读数里第一条不是卫生问题的说明（`[卫生]` 前缀说的是这次自检留下的垃圾）。"""
    for item in (reading.get("problems") or []):
        text = str(item or "")
        if not text.startswith("[卫生]"):
            return text
    note = str(reading.get("note") or "")
    return "" if note.startswith("[卫生]") else note


def install_l_tools(
    store: Store,
    *,
    registry: ToolRegistry | None = None,
    workspace_root: str | Path | None = None,
) -> ToolRegistry:
    """装配 L 的工具栏（`formal.*`）。

    与 E 的 `install_e_tools` 同一个形状：工具 handler 惰性构造一个 AgentL，
    于是"工具入口"与"AgentL 方法"共用同一份实现（两套会写出字段口径不同的记录）。
    """
    from ..tools import formal_tools as FT

    reg = registry if registry is not None else ToolRegistry(name="agent-L")
    root = Path(workspace_root) if workspace_root is not None else Path(store.root)
    FT.register(reg, store=store, root=root)
    if reg.bound_role is None:
        reg.bound_role = "L"
    return reg


class AgentL(_Record, _Formalize, _CheckFormalL, _Report, _Core):
    """Lean 形式化者。

    每个方法都能被独立调用与单测：

    - :meth:`formalize` —— 写 `.lean` 落盘 + 交给检查器真跑，结论三态；
    - :meth:`check_formal` —— 转发到 `verify.check_formal`（唯一实现），前置自检闸；
    - :meth:`record` —— 把一次形式化检查登记成一行 `experiments`（`method="formal"`），
      并不动 `statements`（形式化 ≠ 审过，见 `agent_l/record.py` 的 docstring）；
    - :meth:`report_to_b` —— 把形式化困难按受控形态投进 B 的收件箱
      （业主 2026-10-22 晚裁定："可向 B 汇报形式化过程中遇到的困难"）。

    与 E 的分工：E 做实验与形式化两件事，L 只做形式化这一件；两侧共用同一个桥接层。
    协作面（2026-10-22 晚的最终裁定）：唯一入口是 B（`B → L`），L 只派 C
    （`L → C`，梳理证明链）；两个读数都由 `capabilities` 从声明派生。
    """
