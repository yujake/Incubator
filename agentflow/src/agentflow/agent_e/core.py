"""角色 E 的实现核心（`goal-7f5116c1` M6）：其余成员 + 把动作 mixin 装起来。

动作方法一个都没留在这里 —— 它们各自在 `agent_e/<动作>.py`。
这一层与各动作文件共用 `_support.py`（模块级 helper 与常量）。
"""
from __future__ import annotations

from ._support import Any, E_NO_FORMAL_REASON as _NO_FORMAL_REASON, ExperimentError, Mapping, Path, Store, ToolRegistry, _decode, _digest, _kill_child, _stop_requested, _which, install_e_tools, os, subprocess, sys, time
from .. import schema as S
from .run_experiment import _RunExperiment
from .author_script import _AuthorScript
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
        #: S-10(a) 起它的用途收窄成一句话：只用来写核验脚本（`author_script`）。
        #: 判读那一段一次都不许问模型（FC-16）—— 那条判据由
        #: `tests/test_agent_e_author_script.py::test_the_reading_path_never_calls_the_seam`
        #: 机械守着（把缝换成一个"一叫就记一笔"的假模型，跑一次判读，计数必须是 0）。
        self.llm = llm
        self.log = log

        # ---- 阈值全部来自 config，不写死在代码里（与 A–D 的既有做法一致）
        #: 默认超时（秒）。调用方可以在 `run_experiment(timeout=...)` 覆盖。
        #:
        #: `draft/37` §133（「用户口径，2026-10-04」）："数值实验时间长是正常的，我们团队之前
        #: 做那篇论文时也做了不少数值实验，但后面逐渐发现模式、优化枚举策略才把时间压下去。"
        #: ⇒ 「不给实验设硬上限」（我第一版把默认从 600 收到 120 并打算"连续超时就拒收"，
        #: 那个方向被用户否掉了）。框架该做的是让每次实验都留下「可比较的读数」
        #: （界 / 成本曲线 / 策略名 —— 见 `_search_facts`），并在"同脚本同参数又跑一次"时
        #: 把这个事实说出来（见 `run_experiment._progress_note`），而不是拦住它。
        self.default_timeout = int(self.cfg.get("timeout", 600))
        #: 超时的「可选」上限：`0` = 不设（缺省）。留着它是给"无人值守 + 墙钟很短"的场景用的，
        #: 不是给研究场景用的 —— 研究里的长实验由工作区的墙钟与预算管，不由这里管。
        self.timeout_cap = int(self.cfg.get("timeout_cap", 0))
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
            # 用 `Popen` + 轮询而不是 `subprocess.run(timeout=…)`（`draft/37` §128）：
            # 停机开关（`.agentflow-stop`）一出现就把这条子进程杀掉，并如实记成
            # "用户叫停"而不是"超时"。理由是真机读数：一次 600 s 的枚举实验会把
            # 600 s 跑满 —— 用户叫停之后它照样跑完，那 10 分钟白烧。
            proc = subprocess.Popen(
                cmd,
                cwd=str(self.workspace_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
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
        # ---- 进程树治理（`draft/39` §3.21 五 I13）：把这条实验子进程装进作业对象。
        #
        # 为什么在这里（真机读数）：实验脚本自己会起子进程（并行枚举、调用外部求解器），
        # 而 `_kill_child(proc)` 只杀直接子进程 —— 用户叫停之后那些孙子照旧跑
        # （历史读数：包装进程被杀之后 python 子进程又跑了 12 分钟）。
        # 作业对象把"终止"变成"关句柄"：根与它之后生的后代一起被 OS 收掉，
        # 且不依赖 `taskkill` 能不能成功（受限环境里实测被拒）。
        # 拿不到作业对象（非 Windows / API 缺失）就照旧走 `_kill_child`：
        # 这条改动只增不减，读数里记着走的是哪一路。
        job = None
        try:
            from .. import jobobject as _JO

            if _JO.available():
                job = _JO.create_job(f"agentflow-e-{proc.pid}")
                _JO.assign_tree(job, proc.pid)
        except Exception:  # noqa: BLE001 —— 装不进作业不改变这一趟的结论，照旧走 kill_child
            job = None
        limit = max(1, int(timeout))
        stopped = False
        stopped_note = ""
        while True:
            try:
                out, err = proc.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                pass          # 0.2 s 到点而已：等的是「子进程结束」或「停机开关落盘」
            if _stop_requested(self.workspace_root):
                stopped = True
                if job is not None:
                    _JO.grace_then_kill(job, grace_sec=1.0, poll_sec=0.2)
                else:
                    _kill_child(proc)
                try:
                    out, err = proc.communicate(timeout=15)
                except subprocess.TimeoutExpired:
                    # 杀不掉（极少数：受限环境拒绝终止）也不许把整趟挂在这里 ——
                    # 如实落"用户叫停 + 子进程没能终止"，剩下的事交给人。
                    out, err = "", ""
                    stopped_note = "（子进程在 15 s 内没能终止）"
                break
            if time.monotonic() - t0 > limit:
                if job is not None:
                    _JO.grace_then_kill(job, grace_sec=0.5, poll_sec=0.2)
                else:
                    _kill_child(proc)
                out, err = proc.communicate()
                return {
                    "exit_code": None,
                    "stdout": _decode(out),
                    "stderr": _decode(err) + f"\n[超时] 超过 timeout={timeout}s，进程已被杀掉",
                    "runtime_sec": round(time.monotonic() - t0, 4),
                    "timed_out": True,
                    "launch_error": None,
                }
        if job is not None:
            # 关句柄 = OS 收掉整棵传递树（包括实验脚本自己起的那些子进程）。
            _JO.close(job)
        if stopped:
            return {
                "exit_code": None,
                "stdout": _decode(out),
                "stderr": _decode(err) + "\n[用户叫停] 停机开关已落盘 ⇒ 这条子进程被终止"
                                         f"（这不是超时，也不是跑失败）{stopped_note}",
                "runtime_sec": round(time.monotonic() - t0, 4),
                "timed_out": False,
                "stopped_by_user": True,
                "launch_error": None,
                "process_tree": "job" if job is not None else "kill_child",
            }
        return {
            "exit_code": proc.returncode,
            "stdout": _decode(out),
            "stderr": _decode(err),
            "runtime_sec": round(time.monotonic() - t0, 4),
            "timed_out": False,
            "launch_error": None,
            "process_tree": "job" if job is not None else "kill_child",
        }

class AgentE(_RunExperiment, _AuthorScript, _EvidenceFor, _ListExperiments, _RunScriptExperiment, _Core):
    """数值实验与反例智能体。

    每个方法都可以被独立调用与单测：

    - :meth:`run_experiment` —— 执行脚本 + 登记一行 Experiment；
    - :meth:`evidence_for` —— 三态查询：没查 / 查了没有 / 查到了什么；
    - :meth:`list_experiments` —— 只读列表。

    形式化不在本类上（业主 2026-10-23 晚：「E 侧与 Lean 相关的工具和动作都该清干净」）：
    本类没有 `check_formal`，`run_experiment(method="formal")` 由动作面第一句以理由码
    `formal_not_in_e` 拒绝。形式化那一岗的实现体在 :class:`agent_e.check_formal._CheckFormal`
    里、由 L 的 `_CheckFormalL` 继承 —— 那是另一条继承链，本类不再混入它。

    LLM：没有。数值实验的判读必须是确定性的（FC-16）。构造签名保留 `llm`
    位置参数只是为了与 A–D 的构造习惯一致。
    """



def selftest() -> int:
    """离线自检：不联网、不依赖仓库里的任何外部文件，返回 0（全过）/ 1（有失败）。
    退出码与末尾那行汇总「同源」（F-4）：`SELF-CHECK DONE` ⇒ 0；任何一个`[FAIL]`（含主体异常中断）⇒ `SELF-CHECK FAILED` ⇒ 1。汇总行无条件打印（主
    体搬进 `_run_selftest_checks`，外面套 try/except/finally）—— 三态纪律：「没查成」由 `未查 N 段` 单独说，不许折进"通过"或"失败"。
    运行方式::
    cd test/test1/src        # 工作区根相对$env:PYTHONIOENCODING='utf-8'; python -m agentflow.agent_e
    覆盖的核心性质（每一条都对应一个"如果错了会很安静"的失败模式）：
    1. 正常脚本 ⇒ 登记成功，exit_code=0，code_hash 非空； 2. 脚本自报 proof ⇒ 被降级为 cross_check，且 notes 里记了这件事； 3. 脚本崩溃
    ⇒ inconclusive + no_local_evidence（崩溃不得写成支持）； 9. formal 不是 E 的活（业主 2026-10-23 晚）：
    `run_experiment(method="formal")` 当场受控拒绝（理由码 `formal_not_in_e`，且理由不是"搬到 L"）、一行都不落；
    10. 计算类方法收到 `imports` ⇒ 受控拒绝，而不是静默忽略（那两个参数只服务 formal 那一支，而 E 不做形式化）。
    """
    import sys as _sys

    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # 有些 stdout 替身没有 reconfigure；切编码失败不该让自检本身挂掉
        pass

    #: 三个计数器（不是两态）：`skipped` 留给"环境把这一段关着" —— 三态纪律：
    #: 「没查」不许写成"通过"，也不许写成"失败"。
    counts: dict[str, int] = {"passed": 0, "failed": 0, "skipped": 0}

    def check(label: str, cond: bool, extra: str = "") -> None:
        okk = bool(cond)
        counts["passed" if okk else "failed"] += 1
        print(f"    [{'PASS' if okk else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    # 汇总行「无条件」打印 + 退出码与汇总同源（F-4）。两件事都是刻意的：
    #   ① 原先汇总行在函数末尾，而第 9 段会抛 `ExperimentError`（那是对的：
    #      被拒绝的路不许登记 formal 行）—— 自检把它当"不该发生"⇒ 进程崩在汇总行
    #      之前，输出止于 `[9]`、退出码 1，而"0 项失败"这句话根本没被打印过。
    #      读它的人拿到一对自相矛盾的读数。
    #   ② 于是主体搬进 `_run_selftest_checks`，用 try/except/finally 保证「任何」
    #      路径都走到汇总行；主体自己炸了也记成一条"失败"，不冒充"没结论"。
    try:
        _run_selftest_checks(check, counts)
    except Exception as exc:  # noqa: BLE001 —— 自检自己炸了也是"失败"
        import traceback

        traceback.print_exc()
        counts["failed"] += 1
        print(f"    [FAIL] 自检主体异常中断（{type(exc).__name__}: {exc}）"
              "—— 上面的 traceback 是根因；这一条按失败计，不按'没结论'")
    finally:
        print("=" * 72)
        skipped = f" / 未查 {counts['skipped']} 段" if counts["skipped"] else ""
        print(f"SELF-CHECK {'DONE' if counts['failed'] == 0 else 'FAILED'}（agent_e）："
              f"{counts['passed']} 项通过 / {counts['failed']} 项失败{skipped}")
    return 0 if counts["failed"] == 0 else 1


def _run_selftest_checks(check, counts: dict[str, int]) -> None:
    """自检主体（第 0–10 段）：只打印与计数，「汇总行与退出码在 `selftest()` 里」。

    把它拆成独立函数的唯一理由就是"汇总行无条件"：只要主体里有一处会抛
    （第 9 段那条受控拒绝就是有意抛的），留在 `selftest` 末尾的汇总行就永远走不到。
    """
    import tempfile

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

    # ---- 9. formal 不是 E 的活（业主 2026-10-23 晚：「E 侧与 Lean 相关的工具和动作都该清干净」）
    #
    # 改前这一段核的是"写死关闭"（受控拒绝 + 替代路线 + 一行都不落）。裁定之后这一支
    # 连动作都没有了：`method='formal'` 在动作面第一句就以理由码 `formal_not_in_e`
    # 拒绝，`AgentE` 上也没有 `check_formal` 这个方法。这里三条一起核：
    # 受控拒绝（不抛栈）/ 理由说得清（不是"搬到 L"）/ 一行都不落。
    lean_src = (
        "theorem selfcheck_formal_proof : 1 + 1 = 2 := rfl\n"
    )
    s9 = put_script("selfcheck_formal_proof.lean", lean_src)
    before9 = len(st.rows("experiments"))
    refused9 = ""
    try:
        e.run_experiment("内核级命题：1+1=2", "selfcheck-formal", s9, method="formal")
    except ExperimentError as exc:
        refused9 = str(exc)
    print(f"[9] formal 路径 ⇒ 受控拒绝（{_digest(refused9, 120)!r}）")
    check("method='formal' 当场受控拒绝（不是静默登记一条 inconclusive）",
          _NO_FORMAL_REASON in refused9)
    check("拒绝理由是「E 不做形式化」（不是「搬到 L」）",
          "不做形式化" in refused9 and "formal_moved_to_l" not in refused9)
    check("被拒绝的形式化实验一行都不许落（没做 ≠ 登记成 inconclusive）",
          len(st.rows("experiments")) == before9)

    # ---- 10. 计算类方法不许收 name / imports（静默忽略是假话）
    #
    # 这两个参数只服务 formal 那一支，于是它们已经不在动作表与工具 schema 上（工具面
    # 因此传不进来）。方法层仍然收着它们 —— 因为 F 的派活路径会按同一份子目标传下来，
    # 而"传了也不做"必须是一句受控拒绝：让它 TypeError 会把"调用方多给了一个参数"
    # 读成"E 内部有 bug"。
    ignored = False
    try:
        e.run_experiment("数值方法不许收 imports", "numeric-imports", s1, imports=())
    except ExperimentError as exc:
        ignored = _NO_FORMAL_REASON in str(exc)
    check("计算类方法收到 imports ⇒ 受控拒绝（理由码与 formal 那一档同源）", ignored)
