"""角色 E 的动作 `check_formal`（`goal-7f5116c1` M6：从 `agent_e.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import ExperimentError, Sequence, VT, _FORMAL_REASON_BY_TOOL_REASON, _relpath

class _CheckFormal:
    def check_formal(
        self,
        claim: str,
        *,
        script_path: str | None = None,
        source: str | None = None,
        name: str | None = None,
        imports: Sequence[str] | None = None,
        timeout_sec: float | None = None,
    ) -> dict:
        """转发到 `tools/verify_tools.check_formal`（唯一实现）。
        无后端时必须返回 ``checked=False, reason="no_backend"``。它与 ``verified=False`` 是两件事：后者是"验证没过"（命题可疑），前者是"我们没验证"（命题未被检验）。
        参数透传（本方法此前只暴露 `claim` / `script_path`）工具层 `verify.check_formal` 早就收 `source` / `checker_name` / `imports` /`timeout_sec`（工
        具层的形参名是 `checker_name` 而非 `name`，理由见`verify_tools.check_formal` 的 docstring；本方法自己的形参仍叫 `name`：它不是经 `ToolRegistry.call` 调用的，
        不受那个撞名影响），而本方法只转发前两个 —— 于是"给一段内存里的 Lean 源码"、"指定要核对的声明名"、"换 imports"、"给这次检查一个更短的时限"这四件事到不了 E：调用方写得出参数，E 收不到，而且不会报错（多给的键被
        Python 静默吃掉或直接 TypeError）。
        向后兼容：旧调用方写的是 `check_formal(claim)` 或`check_formal(claim, script_path=...)`。新增的四个一律是关键字参数且默认 None⇒ 旧调用点逐字节不受影响（既有用例
        `test_check_formal_without_backend_is_not_checked_not_failed` 未改一字）。
        `reason` 的收口与透传（`G-24①`）`reason` 取本模块的局部受控词表 :data:`FORMAL_REASONS`，映射表是`_FORMAL_REASON_BY_TOOL_REASON`：工具层给的每一个 `reason` 
        都必须在那张表里被显式列出，表外的值落到 `status_unregistered`（而不是伪装成 `tool_crashed`—— 那是一句具体的假话："桥接层自己出错"与"我不认识这个状态"是两件事）。
        收口必须有配套的透传，否则收口就是删信息：工具层原样报的那个值逐字放进`verifier_status`，检查器自己的话在 `verifier_output` 与 `detail` 里。透传字段也是"多值不许压成一个模糊值"（`N-5`）在本层
        的落地形态。
        `script_path` 的路径守卫（本轮补上）工具层 `verify.check_formal` 把 `script_path` 原样交给`formalgw.check_lean` 的 `source_path` 入口（它刻意不自己读文件，
        理由是"读不到的收口方式必须与声明名核对同处"）。那个入口会`open()` 调用方给的路径 ⇒ 在本方法收口之前，工具的 `script_path`是一条能读工作区外任意文件的通道（`verify.run_experiment` 那条路径有 
        `AgentE._resolve`，这条没有）。
        所以这里用本模块既有的 `_resolve` 收口（与 `run_experiment`第一段同一份判据，不另写一份），并且不把越界变成异常 ——它返回与 `no_backend` / `no_script` 同形的受控三态 dict：
        `checked=False, verified=None, reason="path_outside_workspace"`。为什么不是抛异常：工具化调用（`registry.call`）会把异常兜成`kind="unexpected"`，于
        是"调用方指了一个越界路径"与"E 内部有 bug"在下游长得一模一样。为什么 `verified` 必须是 `None` 而不是 `False`：这次没有查，不是"查了没通过"。
        """
        # ---- 路径守卫：越界即拒绝，且失败形态与本方法的其它受控状态同形
        #
        # 判据只有一条、且永远执行（即使同时给了 source）：给了 source 时工具层
        # 以 source 为准、不会去读这个文件，但"调用方以为自己能读那儿"这件事仍然成立，
        # 而它正是要被拦下的那个想法。这里复用 `run_experiment` 用的同一份 `_resolve`，
        # 不另写一份路径判据。
        safe_script: str | None = None
        if script_path is not None:
            try:
                resolved = self._resolve(str(script_path))
                safe_script = _relpath(resolved, self.workspace_root)
            except ExperimentError as exc:
                return self._formal_refusal(claim, "path_outside_workspace", str(exc))

        res = VT.check_formal(
            claim,
            script_path=safe_script,
            source=source,
            # 本方法的形参叫 name，工具层的形参叫 checker_name（`C3`：工具层是经
            # `ToolRegistry.call` 调用的，而它的第一个形参就叫 `name`，工具再声明
            # 一个 `name` 会抛 `got multiple values for argument 'name'`）。
            # 这一格是两套名字之间的唯一映射点，改工具层形参名时必须同轮改这里。
            checker_name=name,
            imports=imports,
            timeout_sec=timeout_sec,
            # 工作区只有 E 知道：工具层拿到相对路径后要把它解析到「工作区」，
            # 而不是解析到进程的 CWD。不给这个参数时，"工作区 ≠ CWD"的环境里
            # 那个 .lean 文件会被报成"读不了 ⇒ decl_mismatch"（实测：
            # `FileNotFoundError: 'p8_probe.lean'`）—— 一次路径解析问题
            # 被说成"你证的东西不在文件里"。
            root=str(self.workspace_root),
        )
        if not res.ok:
            # 传递失败也带上三态位，避免调用方只看 ok 就当成"没验证过"。
            # 键集合与"路径越界"那一支共用 `_formal_refusal`（见它的理由）。
            #
            # `reason` 只写受控值 `tool_failed`：失败种类（`param_error` /
            # `check_failed` / …）拼进 reason 会造出一个词表外的复合值
            # （`tool_failed:xxx`），于是"有哪些可能的 reason"这个问题的答案
            # 就没有边界了。种类改放 `detail`，它照样可见。
            kind = str(res.meta.get("kind") or "error")
            return self._formal_refusal(claim, "tool_failed", f"[{kind}] {res.error or ''}")
        data = dict(res.data or {})
        raw_reason = str(data.get("reason") or "")
        data["reason"] = _FORMAL_REASON_BY_TOOL_REASON.get(raw_reason, "status_unregistered")
        #: 逐字透传：收口之后，调用方仍然拿得到工具层/检查器原样报的那个值。
        data["verifier_status"] = raw_reason
        return data
