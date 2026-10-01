"""角色 E 的实现核心（`goal-7f5116c1` M6）：其余成员 + 把动作 mixin 装起来。

动作方法一个都没留在这里 —— 它们各自在 `agent_e/<动作>.py`。
这一层与各动作文件共用 `_support.py`（模块级 helper 与常量）。
"""
from __future__ import annotations

from ._support import Any, DeclarationNameError, ExperimentError, Mapping, Path, Sequence, Store, ToolRegistry, _NOT_CHECKED_REASONS, _NO_EVIDENCE_KIND, _declared_name_note, _decode, _digest, _relpath, _result_reason, _which, build_experiment, install_e_tools, os, sole_declaration_name, subprocess, sys, time
from .run_experiment import _RunExperiment
from .check_formal import _CheckFormal
from .evidence_for import _EvidenceFor
from .list_experiments import _ListExperiments
from .run_script_experiment import _RunScriptExperiment


class _Core:
    def __init__(
        self,
        store: Store,
        *,
        config: Mapping[str, Any] | None = None,
        workspace_root: str | Path | None = None,
        log: Any | None = None,
        llm: Any | None = None,
        tools: ToolRegistry | None = None,
        actor: str = "agent-E",
    ) -> None:
        self.store = store
        self.cfg: dict[str, Any] = dict(config or {})
        self.actor = actor
        #: 未使用（见类 docstring 末段）。保留它是为了显式说明 E 不用 LLM，
        #: 而不是让调用方以为"没传 llm 所以功能缺了一块"。
        self.llm = llm
        self.log = log

        # ---- 阈值全部来自 config，不写死在代码里（与 A–D 的既有做法一致）
        #: 默认超时（秒）。调用方可以在 `run_experiment(timeout=...)` 覆盖。
        self.default_timeout = int(self.cfg.get("timeout", 600))
        #: 脚本解释器。默认用当前解释器（`sys.executable`）：
        #: 用 `"python"` 会依赖 PATH，在 CI/虚拟环境里可能解析到另一个 Python
        #: —— 于是"脚本在 E 里跑得通"与"在命令行里跑得通"变成两件事。
        self.python = str(self.cfg.get("python") or sys.executable or "python")
        #: 允许的脚本后缀。不是白名单本身，而是给"我不知道怎么跑它"一个明确说法：
        #: 一个 .jl 文件被当成 Python 跑会得到一个看起来像脚本 bug 的报错。
        self.allowed_suffixes = tuple(self.cfg.get("allowed_suffixes") or (".py", ".ps1"))

        root = workspace_root if workspace_root is not None else self.cfg.get("workspace_root")
        if root is None:
            # 默认以 store.root 为工作区：实验脚本与数据在同一棵树里，
            # 这样"工作区"这个概念在整个框架里只有一个含义。
            root = Path(self.store.root)
        self.workspace_root = Path(root).resolve()

        self.last_run: dict[str, Any] = {}
        #: 工具调用失败记录（与 agent_d 的 `last_tool_errors` 同名同义）。
        self.last_tool_errors: list[dict] = []
        self.tools = tools if tools is not None else install_e_tools(self.store, workspace_root=self.workspace_root)
        # ---- 绑定角色（`P-14`）：注入的注册表同样要绑（`AgentD` 那条注释同族）。
        if self.tools.bound_role is None:
            self.tools.bound_role = "E"
    def _log(self, message: str, **extra: Any) -> None:
        if self.log is not None:
            try:
                self.log(message, **extra)
            except Exception:  # noqa: BLE001 - 日志失败不该打断实验
                pass
    def _resolve(self, rel: str | Path) -> Path:
        """把脚本路径解析到工作区内，越界即拒绝。

        为什么这条闸必须在 `open()` 之前：`script_path` 是本模块唯一的
        "外部输入 → 执行"通道。允许 `../../` 就等于允许框架执行工作区外的
        任意代码，而这不会报任何错 —— 它只会"成功"。
        与 `tools/verify_tools.py::_resolve`、`Store.library_path` 同一判据。
        """
        p = Path(str(rel))
        cand = (p if p.is_absolute() else (self.workspace_root / p)).resolve()
        try:
            cand.relative_to(self.workspace_root)
        except ValueError:
            raise ExperimentError(
                f"script_path 越出工作区：{rel!r}（工作区={self.workspace_root}）。"
                "拒绝执行工作区外的代码"
            ) from None
        return cand
    def _call(self, name: str, **params: Any) -> Any:
        """调工具并解开 `ToolResult`；失败返回 None 并把原因记进 `last_tool_errors`。

        与 `AgentD._call` 同样的取舍：一次工具失败不该打断 E 的流程，
        但原因必须留痕（否则"没查到"与"工具坏了"在调用方眼里长得一样）。
        """
        res = self.tools.call(name, **params)
        if not res.ok:
            self.last_tool_errors.append({"tool": name, "error": res.error, "kind": res.meta.get("kind")})
            return None
        return res.data
    def _command_for(self, path: Path) -> list[str]:
        """按后缀给出命令行。未知后缀直接拒绝，不猜。"""
        suf = path.suffix.lower()
        if suf == ".py":
            return [self.python, str(path)]
        if suf == ".ps1":
            exe = "pwsh" if _which("pwsh") else "powershell"
            return [exe, "-NoProfile", "-NonInteractive", "-File", str(path)]
        raise ExperimentError(
            f"不知道怎么执行 {suf or '（无后缀）'} 文件（已知 {self.allowed_suffixes}）。"
            "拒绝猜：把 .jl 当 Python 跑会得到一个看起来像脚本 bug 的报错，"
            "而真正的错误是调用方给错了文件"
        )
    def _run_script(self, path: Path, *, timeout: int) -> dict:
        """在独立进程里跑脚本，捕获 stdout/stderr/exit_code。

        为什么必须是独立进程（而不是 `exec` 到本进程里）：实验脚本是我们
        不完全信任的代码 —— 它可能死循环、可能 `sys.exit`、可能改全局状态。
        放在子进程里，最坏情况是这一轮实验失败，而不是整个框架被带走。
        超时同理：`subprocess.run(timeout=...)` 之后进程会被杀掉，
        而进程内的 `signal.alarm` 在 Windows 上根本不存在。
        """
        cmd = self._command_for(path)
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUTF8", "1")
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(1, int(timeout)),
                env=env,
            )
        except subprocess.TimeoutExpired as e:
            return {
                "exit_code": None,
                "stdout": _decode(e.stdout),
                "stderr": _decode(e.stderr) + f"\n[超时] 超过 timeout={timeout}s，进程已被杀掉",
                "runtime_sec": round(time.monotonic() - t0, 4),
                "timed_out": True,
                "launch_error": None,
            }
        except OSError as e:
            # 解释器不存在 / 权限不足等：这是没跑起来，不是"跑失败"。
            return {
                "exit_code": None,
                "stdout": "",
                "stderr": f"[无法启动] {type(e).__name__}: {e}",
                "runtime_sec": round(time.monotonic() - t0, 4),
                "timed_out": False,
                "launch_error": f"{type(e).__name__}: {e}",
            }
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "runtime_sec": round(time.monotonic() - t0, 4),
            "timed_out": False,
            "launch_error": None,
        }
    def _record_formal(
        self,
        claim: str,
        claim_key: str,
        path: Path,
        *,
        code_hash: str,
        params: Mapping[str, Any] | None,
        for_question_id: str | None,
        timeout: int,
        name: str | None,
        imports: Sequence[str] | None,
    ) -> dict:
        """形式化路径：真跑一次检查器，按检查器给的结论登记一行 `Experiment`。

        这是 `P-8` 的接线：此前 `run_experiment` 只有"跑脚本 + 读脚本自报的结论"
        一条路径，而 `build_experiment` 一个证据形状字段都不传 ⇒ 走到
        `row.validate()` 必然抛（"evidence_kind='proof' 时必须给出 verifier_output"）
        ⇒ E 登记不了一条 proof 级实验。这里把"一次真实的形式化检查"与
        "一行 proof 级实验记录"接起来，判据一条都没有新发明：

        - "什么算证明"只有一处定义（`formalgw`），本方法只读它的结论；
        - 检查器说 `verified` ⇒ `evidence_kind="proof"`，`verifier_output` 是
          检查器自己的输出，`verifier_subject_key` 逐字等于 `claim_key`；
        - 其余一切状态（跑了没通过 / 没查成）⇒ `inconclusive` + `heuristic`，
          一行都不许标成 proof。为什么不是 `cross_check`：那是"另一个方法旁证过"，
          而"证明没过"给不出旁证（`formalgw.evidence_of` 的 docstring 逐字写了
          同一条理由：把它写成 cross_check 会让一次检查失败变成正面证据）。

        `imports` 直接转发：默认 `None` 表示"用工具层的默认值"，本方法不替调用方
        决定要加载哪个库 —— 这个决定会改变结论（库不可得时 status 是
        `import_unavailable`，而不是"证明没过"），所以它必须是调用方显式给的。
        """
        suffix = path.suffix.lower()
        if suffix != ".lean":
            raise ExperimentError(
                f"method='formal' 的产物必须是 .lean 源文件，收到 {suffix or '（无后缀）'} "
                f"（{path.name!r}）—— 形式化路径的输入是检查器能读的形式化源码，"
                "本方法不会把一段 Python/文本当成 Lean 去核。"
                "数值脚本请用 method='numeric' / 'symbolic' / 'exhaustive_search'；"
                "让脚本冒充形式化产物正是 FC-22 要拦的那种越权"
            )

        rel = _relpath(path, self.workspace_root)
        declared_name = str(name or "")
        if not declared_name:
            # 不拿文件名词干当声明名（`goal-a5334ee8` 的 ④，同 `verify_tools.check_formal`
            # 的理由）：文件名词干与源码里的声明名通常不是一个东西，于是"源码里没有
            # 这个名字"被报成 `decl_mismatch`（读起来像"查了、没通过"），
            # 而真原因是调用方没点名。这里改成从源码认名：恰好一条具名声明就用它，
            # 0 条或多条 ⇒ 如实说"取不到唯一那条"并请调用方点名。
            try:
                declared_name = sole_declaration_name(path.read_text(encoding="utf-8"))
            except DeclarationNameError as exc:
                raise ExperimentError(
                    f"method='formal' 拿不到唯一的声明名（{rel}）：{exc}"
                ) from exc
            except OSError as exc:
                raise ExperimentError(
                    f"method='formal' 读不了 {rel}：{type(exc).__name__}: {exc}"
                ) from exc
        t0 = time.monotonic()
        data = self.check_formal(
            claim,
            script_path=rel,
            name=declared_name,
            imports=imports,
            timeout_sec=float(timeout),
        )
        runtime_sec = round(time.monotonic() - t0, 4)

        status = str(data.get("verifier_status") or "")
        formal_reason = str(data.get("reason") or "")
        output = str(data.get("verifier_output") or "").strip()
        verified = data.get("verified") is True

        notes = [
            f"[formal] 检查器状态 {status!r}（本层受控理由 {formal_reason}）；"
            # "声明名 <X>；"这一段有唯一写法（`_declared_name_note`）与唯一读法
            # （`declared_name_of_notes`）：事后审计（`verify.selfreported_proof`）
            # 按它认"检查器实际检查的是哪条声明"。在这里手写这一段，
            # 改写法的改动就会让读法静默失配（审计悄悄退回 `verifier_subject_key`）。
            f"{_declared_name_note(declared_name)}"
            f"脚本 {rel}（sha256 前 16 位 {code_hash}）；"
            f"imports={list(imports) if imports is not None else '（默认：不注入任何库）'}"
        ]
        detail = _digest(data.get("detail") or "", 400)
        if detail:
            notes.append(f"[formal] 检查器/工具层的说明：{detail}")
        if verified:
            notes.append(f"[formal] 检查器原话：{_digest(output, 400)}")
            notes.append(
                "[formal] ⇒ 本次是 proof 级证据（唯一允许'已证明'的一档）："
                "结论来自检查器，不来自脚本或本模块的推断"
            )
        else:
            notes.append(
                f"[formal] ⇒ 本次不是 proof：status={status!r} ⇒ result=inconclusive、"
                f"evidence_kind={_NO_EVIDENCE_KIND}（没查成与查了没通过都不构成正面证据）"
            )
            if output:
                notes.append(f"[formal] 检查器原始输出：{_digest(output, 400)}")

        derived: dict[str, Any] = {
            "result": "supports" if verified else "inconclusive",
            "evidence_kind": "proof" if verified else _NO_EVIDENCE_KIND,
            "negation_kind": "not_proved" if verified else "no_local_evidence",
            "observations": {
                "verifier_status": status,
                "formal_reason": formal_reason,
                "checked": data.get("checked"),
                "missing_imports": [str(x) for x in (data.get("missing_imports") or [])],
            },
            "counterexample": None,
            "notes": notes,
        }
        # 检查器输出空着时不给 `verifier_subject_key`：绑定一个命题、却没有任何
        # 检查器的话可作为"它管的是这个命题"的依据，那是一条空绑定。
        # `verified=True` 而输出为空是不可能的（`verified` 的定义就包含"输出里
        # 看得到那条声明"）；真出现时让它按 schema 硬约束 2 抛出来，不许在这里兜。
        subject_key = claim_key if output else ""
        # `verified` 只可能在检查器退出码 0 时到达（`formalgw.check_lean` 的
        # 判据顺序：非零退出码全部在前面收口），所以这里记 0 不是编造。
        exit_code = 0 if verified else None

        with self.store.tx("experiments", actor=self.actor, note="e.run_experiment") as tx:
            eid = tx.alloc_id("experiment")
            row = build_experiment(
                eid,
                claim,
                claim_key,
                method="formal",
                code_path=rel,
                code_hash=code_hash,
                derived=derived,
                exit_code=exit_code,
                runtime_sec=runtime_sec,
                params=params,
                for_question_id=for_question_id,
                verifier_output=output,
                verifier_subject_key=subject_key,
                created_by=self.actor,
            )
            tx.upsert("experiments", row.to_dict(), note=f"experiment:{claim_key}")

        out = {
            "experiment_id": eid,
            "recorded": True,
            "result": row.result,
            "evidence_kind": row.evidence_kind,
            "negation_kind": row.negation_kind,
            "exit_code": row.exit_code,
            "runtime_sec": row.runtime_sec,
            "code_hash": row.code_hash,
            "notes": row.notes,
            "reason": _result_reason(row),
        }
        self.last_run = out
        self._log(
            f"formal experiment {eid} recorded",
            **{k: out[k] for k in ("result", "evidence_kind", "exit_code")},
        )
        return out
    def _formal_refusal(self, claim: str, reason: str, detail: str) -> dict:
        """`check_formal` 的受控拒绝形态（路径越界走这一支）。

        为什么单独一个方法而不是内联一个 dict：工具层
        `verify.check_formal` 的契约字符串是
        ``{'checked','verified','claim','reason','detail','verifier_output',
        'missing_imports','verifier_status'}``，
        而 `tests/test_tools_audit_fixes.py` 逐字核对每条分支的键集合。
        把"拒绝"的键集合收在一处，是为了让"多了/少了一个键"在结构上不可能
        只发生在某一条分支里 —— 顺便让下面 `tool_failed` 那一支也用它。

        `verified=None`（不是 `False`）：这次没有查。"查了、没过"是
        `checked=True, verified=False`；把两者折叠，下游会把"路径被拒"
        读成"这个命题被证伪了"。

        ## 为什么要带 `missing_imports`（`G-18` 之后的键集合一致性）

        工具层 `verify.check_formal` 的声明是一个键集合，它对每一条分支都成立
        （`tests/test_tools_audit_fixes.py` 逐字核对每条分支）。`G-18` 给成功分支加了
        `missing_imports`（"哪个包不可得"）之后，本方法这条拒绝分支如果还是 6 个键，
        就会出现"同一个工具的两条分支两个键集合" —— 这正是 `checks` 类契约最容易腐的地方。
        所以这里补一个空列表（拒绝路径上没有"缺哪个包"这回事，空列表是诚实的值：
        "我们没有因为缺包而拒绝"，而不是"我们不知道"）。

        ## 为什么 `verifier_status` 是空串（`G-24①` 的透传字段）

        这一支是"根本没起检查器"（路径被拒 / 工具层返回失败）⇒ 没有检查器的原话可透传，
        空串是诚实的值："这次没有检查器状态"，而不是"我不知道它是什么"。
        校验器原话在 `detail` 里，检查器输出在 `verifier_output` 里。
        """
        return {
            "checked": False,
            "verified": None,
            "claim": claim,
            "reason": reason,
            "detail": detail,
            "verifier_output": "",
            "missing_imports": [],
            "verifier_status": "",
        }


class AgentE(_RunExperiment, _CheckFormal, _EvidenceFor, _ListExperiments, _RunScriptExperiment, _Core):
    """数值实验与形式化验证智能体。

    每个方法都可以被独立调用与单测：

    - :meth:`run_experiment` —— 执行脚本 + 登记一行 Experiment；
    - :meth:`check_formal` —— 转发到形式化检查器（无后端时如实返回"没做"）；
    - :meth:`evidence_for` —— 三态查询：没查 / 查了没有 / 查到了什么；
    - :meth:`list_experiments` —— 只读列表。

    LLM：没有。数值实验的判读必须是确定性的（FC-16）。构造签名保留 `llm`
    位置参数只是为了与 A–D 的构造习惯一致。
    """



def selftest() -> int:
    """离线自检：不联网、不依赖仓库里的任何外部文件，返回失败数。

    运行方式::

        cd D:\\Incubator\\test\\test1\\src
        $env:PYTHONIOENCODING='utf-8'; python -m agentflow.agent_e

    覆盖的核心性质（每一条都对应一个"如果错了会很安静"的失败模式）：

    1. 正常脚本 ⇒ 登记成功，exit_code=0，code_hash 非空；
    2. 脚本自报 proof ⇒ 被降级为 cross_check，且 notes 里记了这件事；
    3. 脚本崩溃 ⇒ inconclusive + no_local_evidence（崩溃不得写成支持）；
    4. 脚本不打印 REPRO_RESULT ⇒ inconclusive + no_local_evidence；
    5. 路径越界 ⇒ 拒绝；
    6. 超时 ⇒ inconclusive 且原因可见；
    7. evidence_for 三态：没查 / 查了没有 / 查到了什么；
    8. 只写一行 experiments（事务性）；
    9. `check_formal` 的受控理由：无后端 ⇒ `no_backend`；有后端但没给源码
       ⇒ `no_script`（两者都是"没查成"，但理由不同，不可折叠）；
    10. 形式化路径（`P-8`）：`.lean` 产物真的走检查器那一条 —— 检查器给
        `verified` 时登记的行必须是 `evidence_kind="proof"` 且
        `verifier_subject_key == claim_key`；否则一行都不许标成 proof。
        本机没有 Lean 时这一段的期望值自动降级成"不是 proof"，仍然核对
        "没查成不许登记成 proof"（三态纪律）。
    """
    import sys as _sys
    import tempfile

    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # 有些 stdout 替身没有 reconfigure；切编码失败不该让自检本身挂掉
        pass

    failures = 0

    def check(label: str, cond: bool, extra: str = "") -> None:
        nonlocal failures
        okk = bool(cond)
        if not okk:
            failures += 1
        print(f"    [{'PASS' if okk else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    print("=" * 72)
    root = Path(tempfile.mkdtemp(prefix="agentflow-agente-"))
    st = Store(root)
    st.init()
    print(f"[0] 临时工作区：{root}")

    def put_script(name: str, body: str) -> str:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        return name

    e = AgentE(st, workspace_root=root)
    print(f"[1] 工具栏：{e.tools.names()}")

    # ---- 1. 正常脚本
    s1 = put_script(
        "ok_probe.py",
        "import json\n"
        "print('REPRO_RESULT: ' + json.dumps({'result':'supports','evidence_kind':'cross_check',\n"
        "  'observations':{'grid':64,'max_err':1e-9},'counterexample':None,'negation_kind':'not_proved'}))\n",
    )
    r1 = e.run_experiment("对 n<=64 的网格，Spec K(m)=[-m,m]", "SpecK(m)=[-m,m]", s1)
    print(f"[2] 正常脚本 ⇒ {r1['result']} / {r1['evidence_kind']} / exit={r1['exit_code']}")
    check("登记成功且 recorded=True", r1["recorded"] is True)
    check("exit_code==0", r1["exit_code"] == 0)
    check("code_hash 非空", bool(r1["code_hash"]))
    check("result=supports ⇒ negation_kind=not_proved", r1["negation_kind"] == "not_proved")

    # ---- 2. 脚本自报 proof（负控）
    s2 = put_script(
        "lying_probe.py",
        "import json\n"
        "print('REPRO_RESULT: ' + json.dumps({'result':'supports','evidence_kind':'proof',\n"
        "  'observations':{},'counterexample':None,'negation_kind':'not_proved'}))\n",
    )
    r2 = e.run_experiment("脚本自报 proof 的命题", "selfclaimed-proof", s2)
    print(f"[3] 脚本自报 proof ⇒ 实际 {r2['evidence_kind']}")
    check("脚本自报 proof 被降级为 cross_check", r2["evidence_kind"] == "cross_check")
    check("notes 里记下了这次越权", "proof" in r2["notes"] and "拒绝" in r2["notes"])

    # ---- 3. 崩溃（负控）
    s3 = put_script("crash_probe.py", "raise SystemExit(3)\n")
    r3 = e.run_experiment("崩溃脚本不得被写成支持", "crash", s3)
    print(f"[4] 崩溃 ⇒ {r3['result']} / {r3['negation_kind']} / exit={r3['exit_code']}")
    check("崩溃 ⇒ inconclusive", r3["result"] == "inconclusive")
    check("崩溃 ⇒ no_local_evidence", r3["negation_kind"] == "no_local_evidence")

    # ---- 4. 不打印 REPRO_RESULT
    s4 = put_script("silent_probe.py", "print('hello')\n")
    r4 = e.run_experiment("没有结构化结论", "silent", s4)
    print(f"[5] 无结论行 ⇒ {r4['result']} / notes={_digest(r4['notes'], 80)!r}")
    check("无结论行 ⇒ inconclusive + no_local_evidence",
          r4["result"] == "inconclusive" and r4["negation_kind"] == "no_local_evidence")
    check("notes 写明脚本未给出结构化结论", "未给出结构化结论" in r4["notes"])

    # ---- 5. 路径越界
    escaped = False
    try:
        e.run_experiment("越界脚本", "escape", "../outside.py")
    except Exception as ex:  # noqa: BLE001
        escaped = isinstance(ex, ExperimentError)
    check("路径越界被拒绝", escaped)

    # ---- 6. 超时
    s6 = put_script("slow_probe.py", "import time\ntime.sleep(30)\n")
    r6 = e.run_experiment("超时脚本", "slow", s6, timeout=1)
    print(f"[6] 超时 ⇒ {r6['result']} / exit={r6['exit_code']} / notes={_digest(r6['notes'], 70)!r}")
    check("超时 ⇒ inconclusive + no_local_evidence",
          r6["result"] == "inconclusive" and r6["negation_kind"] == "no_local_evidence")

    # ---- 7. evidence_for 三态
    q = e.evidence_for()
    hit = e.evidence_for("SpecK(m)=[-m,m]")
    miss = e.evidence_for("完全不存在的命题")
    print(f"[7] evidence_for：没查 checked={q['checked']}；命中 {len(hit['experiments'])} 条 "
          f"proved={hit['proved']}；未命中 checked={miss['checked']}")
    check("两个参数都不给 ⇒ checked=False（没查）", q["checked"] is False)
    check("给了参数且命中 ⇒ checked=True", hit["checked"] is True and len(hit["experiments"]) == 1)
    check("命中但没有 proof ⇒ proved=False", hit["proved"] is False)
    check("给了参数但没有 ⇒ checked=True 且 experiments=[]",
          miss["checked"] is True and miss["experiments"] == [] and miss["proved"] is False)
    check("'查了没有' 与 '没查' 的 reason 不同", "没有" in miss["reason"] and "没查" in q["reason"])

    # ---- 8. 事务性：一轮实验只写一行
    before = len(st.rows("experiments"))
    e.run_experiment("再来一条", "again", s1)
    after = len(st.rows("experiments"))
    print(f"[8] 事务性：experiments {before} -> {after}")
    check("一次 run_experiment 只多一行", after == before + 1)

    # ---- 9. check_formal 的三态（无后端时是'没做'，不是'没过'）
    #
    # 判据是具体理由，不是 `checked is False`：`checked=False` 有两种完全不同的来源
    # ——"没查成"（`no_backend` / `timeout` / `tool_crashed`，环境的锅）与
    # "调用方没给源码"（`no_script`，调用方的锅）。把它们折叠成一个判据之后，
    # 有后端时拿不到源码（`no_script`）会被读成"本机没有证明检查器"，
    # 于是这条断言在有后端的环境里必然失败（而且它失败得很安静）。
    # `no_script` 单独走下面第 10 段，形态与 `no_backend` 分别核对。
    cf = e.check_formal("1+1=2")
    print(f"[9] check_formal ⇒ checked={cf.get('checked')} reason={cf.get('reason')!r} "
          f"verified={cf.get('verified')!r}")
    if cf.get("reason") == "no_backend":
        check("无后端 ⇒ reason='no_backend' 且 verified 为 None（不是 False），"
              "且 checked=False",
              cf.get("checked") is False and cf.get("verified") is None)
    elif cf.get("reason") in _NOT_CHECKED_REASONS:
        # 环境侧"没查成"的另两种：`timeout` / `tool_crashed`。
        check(f"没查成（{cf.get('reason')}）⇒ checked=False 且 verified 为 None，"
              "且理由不是 no_script",
              cf.get("checked") is False and cf.get("verified") is None)
    else:
        # 有后端、没给源码 ⇒ 受控的 `no_script`（不是"没后端"）：
        # 这是本段收紧判据后新增的那一态，它必须在这里被单独核对。
        check("有后端但没给源码 ⇒ 受控的 no_script（不是 no_backend），"
              "且 verified 为 None",
              cf.get("reason") == "no_script" and cf.get("checked") is False
              and cf.get("verified") is None)
        # 同一环境里给一份源码：这次真的会去跑检查器，于是"有后端"这件事
        # 不只是从 reason 推出来的。`imports=()` 是为了不依赖 Mathlib 全库编完。
        src9 = "theorem selfcheck_one_plus_one : 1 + 1 = 2 := rfl\n"
        cf2 = e.check_formal("1+1=2", source=src9, name="selfcheck_one_plus_one",
                             imports=())
        print(f"[10] 有后端 + 给源码 ⇒ checked={cf2.get('checked')} "
              f"reason={cf2.get('reason')!r} verified={cf2.get('verified')!r}")
        check("有后端 + 给源码 ⇒ verified=True（检查器这一段真的接上了）",
              cf2.get("reason") == "verified" and cf2.get("verified") is True
              and cf2.get("checked") is True)
        check("`reason` 的收口与透传同时成立（G-24①）",
              cf2.get("reason") == "verified"
              and cf2.get("verifier_status") == cf2.get("reason"),
              f"verifier_status={cf2.get('verifier_status')!r}")

    # ---- 10. 形式化路径（P-8）：`.lean` 产物真的走检查器那一条
    #
    # 判据与"本机有没有 Lean"解耦：有检查器且命题为真 ⇒ 必须是 proof；
    # 否则必须是"不是 proof"（没查成不许登记成 proof）。
    # 两个方向都不许把 `heuristic` 写成 `proof`，所以这条检查在任何环境下都有信息量。
    lean_src = (
        "theorem selfcheck_formal_proof : 1 + 1 = 2 := rfl\n"
    )
    s10 = put_script("selfcheck_formal_proof.lean", lean_src)
    r10 = e.run_experiment(
        "内核级命题：1+1=2", "selfcheck-formal", s10,
        method="formal", imports=(),
    )
    print(f"[11] formal 路径 ⇒ evidence_kind={r10['evidence_kind']} "
          f"result={r10['result']} reason={_digest(r10['reason'], 90)!r}")
    if r10["evidence_kind"] == "proof":
        row10 = st.rows("experiments")[-1]
        check("proof 行必须由检查器背书：verifier_subject_key == claim_key",
              row10["verifier_subject_key"] == "selfcheck-formal")
        check("proof 行必须有检查器原话（verifier_output 非空）",
              bool(str(row10["verifier_output"]).strip()))
        check("proof 行不许出现在非 formal 方法上", row10["method"] == "formal")
    else:
        check("检查器没给出 verified 时，一行都不许标成 proof（三态纪律）",
              r10["evidence_kind"] != "proof" and r10["result"] == "inconclusive")
        check("没查成/没通过都必须写清检查器状态",
              "检查器状态" in r10["reason"] or "检查器状态" in r10["notes"])

    # ---- 11. 形式化路径的负控：非 .lean 产物当场拒绝（不留半条记录）
    before11 = len(st.rows("experiments"))
    refused = False
    try:
        e.run_experiment("用 Python 冒充形式化产物", "formal-python", s1, method="formal")
    except Exception as ex:  # noqa: BLE001
        refused = isinstance(ex, ExperimentError)
    check("method='formal' + 非 .lean 产物 ⇒ 当场拒绝", refused)
    check("被拒绝的形式化实验不得留下任何行", len(st.rows("experiments")) == before11)

    # ---- 12. 计算类方法不许收 name / imports（静默忽略是假话）
    ignored = False
    try:
        e.run_experiment("数值方法不许收 imports", "numeric-imports", s1, imports=())
    except Exception as ex:  # noqa: BLE001
        ignored = isinstance(ex, ExperimentError)
    check("计算类方法收到 imports ⇒ 拒绝而不是静默忽略", ignored)

    print("=" * 72)
    print(f"SELF-CHECK {'DONE' if failures == 0 else 'FAILED'}（agent_e）：失败 {failures} 项")
    return failures
