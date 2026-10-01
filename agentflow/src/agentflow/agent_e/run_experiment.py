"""角色 E 的动作 `run_experiment`（`goal-7f5116c1` M6：从 `agent_e.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import Any, ExperimentError, Mapping, S, Sequence, ToolError, VT, _derive, _digest, _relpath, _result_reason, _write_run_log, build_experiment

class _RunExperiment:
    def run_experiment(
        self,
        claim: str,
        claim_key: str,
        script_path: str,
        *,
        params: Mapping[str, Any] | None = None,
        method: str = "numeric",
        for_question_id: str | None = None,
        timeout: int = 600,
        name: str | None = None,
        imports: Sequence[str] | None = None,
    ) -> dict:
        """跑一个实验脚本并登记一条 `Experiment` 行。

        推导规则见模块 docstring（唯一权威表述）：计算类方法在 :func:`_derive`，
        形式化方法在 :meth:`_record_formal`。

        返回 ``{"experiment_id", "recorded", "result", "evidence_kind",
        "negation_kind", "exit_code", "reason"}``。

        schema 校验失败必须让异常冒出来（本方法不做 try/except 兜底）：
        那说明上面的推导规则与 `Experiment.validate` 不一致，
        而"推导规则与 schema 打架"正是本项目最该炸的地方。

        ## 形式化路径（`P-8`）

        `method="formal"` 时登记的不是"这个脚本说了什么"，而是"检查器核了什么"：

        - 产物必须是工作区里的 `.lean` 文件（别的后缀当场拒绝，见模块 docstring）；
        - `name` / `imports` 只对这条路径有意义，它们是给检查器的参数
          （`name` 不给时由工具层按其声明取文件名词干，本方法不另猜一次）；
        - 只有检查器给出 `verified` 才登记 `evidence_kind="proof"`，
          `verifier_output` 与 `verifier_subject_key` 都来自那一次真实检查。

        计算类方法给了 `name` / `imports` 会被拒绝（不是静默忽略）：
        静默忽略会让调用方以为自己指定了检查条件，而实际用的是默认值 ——
        这种假话没有任何地方会报出来。

        ## 这里没有 `sleep` 形参，这是刻意的（`D-2`）

        `capabilities.CAPABILITIES["E"].run_experiment` 的 params 里声明了 `sleep`，
        而它不在本方法的形参表里，本方法也不收 `inspect.Parameter.VAR_KEYWORD`。
        这不是漏了一个参数，也不是"反正 kwargs 收得住"：`sleep` 只服务替身夹具
        （`tests/test_conductor.py` / `tests/test_scheduler.py` 的 `FakeE` 按同一份
        schema 传它来控制"这次实验跑多久"），已逐条登记在 `capabilities.PARAM_SEAMS`
        里（键含理由串），并由 `capabilities.assert_capabilities()` 第 [8] 条在
        `import agentflow.capabilities` 时核过：声明了而实现不收、又不登记 ⇒ 导入失败。

        两条不许做的改动：① 把 `sleep` 从能力表里删掉 —— 那会让替身无法按 schema
        传参，被测的就不再是那条真实链路；② 在这里补一个具名的 `sleep`，或让它收
        `inspect.Parameter.VAR_KEYWORD` —— 前者是没人读的假承诺，后者把
        "我传了但它没看"变成静默成功，而 `conductor.LocalBackend.call` 的 docstring
        逐字拒绝的正是这个形态。参数门的口径（声明 ∩ 实现签名）见
        `capabilities.gate_params` / `capabilities.check_params`。
        """
        if not str(claim).strip():
            raise ExperimentError("claim 不能为空（没有命题就没有实验）")
        if not str(claim_key).strip():
            raise ExperimentError("claim_key 不能为空（没有它就无法回答'这条实验检验的是哪个命题'）")
        if method not in S.EXPERIMENT_METHODS:
            raise ExperimentError(f"method 必须是 {S.EXPERIMENT_METHODS} 之一，收到 {method!r}")
        if method != "formal" and (name is not None or imports is not None):
            raise ExperimentError(
                f"name / imports 只对 method='formal' 有效（收到 method={method!r}）—— "
                "计算类方法的证据等级由 `_derive` 推导，没有任何检查器会读这两个参数。"
                "静默忽略会让调用方以为自己指定了检查条件（说明了 imports，实际用的是默认值）"
            )

        # ---- [1] 路径解析（越界即拒绝）
        path = self._resolve(script_path)
        if not path.is_file():
            raise ExperimentError(f"脚本不存在：{script_path!r}（解析为 {path}）")

        # ---- [2] 可复现性绑定：复用 verify_tools.code_hash，不另写一份
        try:
            chash = VT.code_hash(path)
        except ToolError as e:
            raise ExperimentError(f"计算 code_hash 失败：{e}") from e

        # ---- [2b] 形式化路径：判据来自检查器，而不是来自脚本的自我陈述
        if method == "formal":
            return self._record_formal(
                claim,
                claim_key,
                path,
                code_hash=chash,
                params=params,
                for_question_id=for_question_id,
                timeout=timeout if timeout is not None else self.default_timeout,
                name=name,
                imports=imports,
            )

        # ---- [3] 独立进程执行 + 超时
        run = self._run_script(path, timeout=timeout if timeout is not None else self.default_timeout)

        # ---- [4] 推导 result / evidence_kind / negation_kind（规则见模块 docstring）
        derived = _derive(run["exit_code"], run["stdout"] or "", method=method)

        notes = list(derived.pop("notes", []) or [])
        head = f"exit_code={run['exit_code']}"
        if run.get("timed_out"):
            head += f"，超时（timeout={timeout}s）"
        if run.get("launch_error"):
            head += f"，启动失败（{run['launch_error']}）"
        notes.insert(0, f"[run] {head}，runtime={run['runtime_sec']}s，脚本 {script_path}（sha256 前 16 位 {chash}）")
        if run.get("stderr"):
            notes.append(f"[stderr] {_digest(run['stderr'])}")
        if run.get("stdout") and derived["result"] != "supports":
            # 只有在"结论不是支持"时才附 stdout 摘要：支持类结论已经有
            # 结构化 observations 可读，再贴一段原始输出只是噪声。
            notes.append(f"[stdout] {_digest(run['stdout'])}")

        # ---- [4b]（在事务内写日志：文件名要用实验号，见 [5]）

        # ---- [5] 一个事务：alloc_id + 写 experiments
        #
        # `alloc_id` 必须在持锁事务内进行，否则两个 E 实例会拿到同一个
        # experiment_id，而按主键 upsert 会静默互相覆盖（ID 发号与建行必须同锁）。
        with self.store.tx("experiments", actor=self.actor, note="e.run_experiment") as tx:
            eid = tx.alloc_id("experiment")
            # 原始输出落成产物文件（`draft/30` §T0-12）：上面那条"支持类不贴
            # stdout 摘要"是刻意的（噪声），但 P4/P5 要求"每条带 code_hash + 退出码 +
            # 原始输出，且能重跑得到同一读数"。摘要不进 notes，原始输出落文件；
            # 文件名用实验号 —— 同一脚本跑两次（不同种子）输出不同，按脚本哈希命名会撞。
            log_rel = f"out/experiments/{eid}.log"
            log_error = _write_run_log(self.workspace_root / log_rel, claim=claim,
                                       claim_key=claim_key, script_path=script_path,
                                       chash=chash, run=run)
            if log_error:
                notes.append(f"[log] 原始输出未能落盘（{log_error}）—— 实验行本身照样写")
                log_rel = ""
            row = build_experiment(
                eid,
                claim,
                claim_key,
                method=method,
                code_path=_relpath(path, self.workspace_root),
                code_hash=chash,
                derived=derived,
                exit_code=run["exit_code"],
                runtime_sec=run["runtime_sec"],
                params=params,
                artifact_paths=([log_rel] if log_rel else []),
                for_question_id=for_question_id,
                extra_notes=notes,
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
        self._log(f"experiment {eid} recorded", **{k: out[k] for k in ("result", "evidence_kind", "exit_code")})
        return out
