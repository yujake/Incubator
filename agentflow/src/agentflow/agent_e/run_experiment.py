"""角色 E 的动作 `run_experiment`（`goal-7f5116c1` M6：从 `agent_e.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from collections.abc import Mapping

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
        certificate: Mapping[str, Any] | None = None,
        search_bound: Mapping[str, Any] | None = None,
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
        # `certificate` / `search_bound` 只对「穷举/枚举类」方法有意义：
        # `schema.Experiment` 的硬约束 2c 说 `method="exhaustive_search"` 必须给
        # certificate、给了 certificate 必须给 search_bound。与上面 name/imports
        # 同一条纪律：对别的 method 传它们 = 让人以为自己指定了检查条件。
        #
        # 为什么这两格必须存在（2026-10-03，`draft/37` §84 的 D1）：`P-8` 只把通道接到了
        # `_support.build_experiment`，没接到这个公开入口 ⇒ 模型无论怎么调
        # `method="exhaustive_search"` 都必然撞硬约束 2c（实测 T1：三次 failed，
        # 报「必须给出 certificate」而 schema 里根本没有这一格）。
        search_like = method in ("exhaustive_search",)
        if not search_like and (certificate is not None or search_bound is not None):
            raise ExperimentError(
                f"certificate / search_bound 只对穷举/枚举类方法有效（收到 method={method!r}）——"
                "它们是「在 B 内没有反例」这类结论的证书与适用范围；别的 method 的证据等级"
                "由 `_derive` 推导，没有任何地方会读它们"
            )
        if method != "formal" and (name is not None or imports is not None):
            raise ExperimentError(
                f"name / imports 只对 method='formal' 有效（收到 method={method!r}）—— "
                "计算类方法的证据等级由 `_derive` 推导，没有任何检查器会读这两个参数。"
                "静默忽略会让调用方以为自己指定了检查条件（说明了 imports，实际用的是默认值）"
            )

        # ---- [0] 开关（业主 2026-10-12）：`toolchain.lean_enabled=false` 时
        # 形式化这条路整条不走 —— 在跑脚本之前就拒，理由与上面 R-01 那一段同族
        # （形式化实验的产物是一份 `.lean`，它跑起来要起检查器；既然这条路关着，
        # 连脚本都不该被跑）。
        #
        # 为什么在这里拒，而不是只靠 `formalgw.check_lean` 那一层兜：
        # 那一层拒的是"编译"这一步，而这里拒的是"登记一条 method='formal' 的实验"
        # 这件事本身。只靠下游兜的表现是：台账里多一条 inconclusive 的 formal 行、
        # 模型多花一步、而用户看到的是"实验失败"而不是"这条路我关了"。
        # 三态纪律：拒绝要可行动 —— 消息里既说清是哪个开关，也说清替代路线。
        if method == "formal":
            from .. import settings as SET

            if not SET.lean_enabled()[0]:
                raise ExperimentError(
                    "本会话的 Lean 形式化已关闭（`toolchain.lean_enabled=false` 或 "
                    "`AGENTFLOW_LEAN_ENABLED=0`）⇒ 不登记 method='formal' 的实验，"
                    "也不起检查器。改走自然语言证明审阅这条路：把证明过程写进 "
                    "`statements` 的 `proof_text`，再请 V 用 `verify.verify_proof` 逐行走查"
                    "（它的结论进 `verifications` 表，是这条路唯一的'审过'凭据）；"
                    "确需形式化时把设置文件里的 `toolchain.lean_enabled` 改成 true 再重来"
                )

        # ---- R-01（`draft/44`）：这四条不用跑脚本就能判 ⇒ 在起子进程之前判掉。
        #
        # 真机读数：52 次失败 / 110.7 分钟 / 0 行 —— 脚本先跑完（有的跑十分钟），
        # 行才被 `Experiment.validate()` 拒。判据不是新写的一份：
        # `schema.experiment_preflight_problems` 就是 `validate()` 里那一段
        # （口径一处），这里只是把它提前叫一次。
        preflight = S.experiment_preflight_problems(
            method=method, certificate=certificate, search_bound=search_bound,
            for_question_id=for_question_id)
        if preflight:
            raise ExperimentError(
                "实验参数在**跑脚本之前**就不合格（R-01：一分钟都不该花）："
                + "；".join(preflight)
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
        # ---- [4a] 与"同一条 claim_key 上的历史实验"比一比（§133）：
        # 用户口径是"数值实验可以慢，靠发现模式与优化枚举策略把时间压下去"。框架据此做的
        # 不是限时，而是「把这个事实说出来」：这次比上次推进了没有（界 / 耗时 / 策略）。
        repeat = self._progress_note(claim_key=claim_key, code_path=_relpath(path, self.workspace_root),
                                     runtime_sec=run["runtime_sec"], timed_out=bool(run.get("timed_out")),
                                     derived=derived)
        if repeat:
            notes.append(repeat)
        # ---- [4a2] 同一份证据反复支持不同断言（`draft/39` §6.27 的 D39）：说一句话。
        #
        # 真机读数（T2 第 9 趟 `p6k`）：一个脚本被反复派了 9 次、claim 分别是 W(2)/W(3)/W(4)…
        # 而每次都打出逐字相同的 `data`（30 顶点 / 度 3）⇒ 台账上九条 `supports`，
        # 手稿把它们当九条独立证据引 —— 同一份读数被当成了九份。
        # 判据只做"把这件事说出来"：同脚本 + 同 data + 不同 claim ⇒ 记一条 note。
        reused = self._reused_evidence_note(claim_key=claim_key, code_hash=chash, derived=derived)
        if reused:
            notes.append(reused)

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
                # 硬约束 2c/2d 的事实通道（P-8 的另一半）：证书与它的适用范围。
                certificate=(dict(certificate) if isinstance(certificate, Mapping) else None),
                # `search_bound` 的优先级（§133）：调用方显式给 > 脚本在结构化结论里自报的
                # `bound`（落进 `observations["bound"]`）> 无。脚本自报的那份是"这次真搜到哪儿"
                # 的读数，比调用方拍的那个数可信 —— 它让"界有没有往前推"可比较。
                search_bound=(dict(search_bound) if isinstance(search_bound, Mapping)
                              else (dict((derived.get("observations") or {}).get("bound") or {})
                                    or None)),
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

        # ---- 与同一 `claim_key` 上的历史实验比一比（`draft/37` §133）
    def _progress_note(self, *, claim_key: str, code_path: str, runtime_sec: float,
                       timed_out: bool, derived: Mapping[str, Any]) -> str:
        """这次比起同一条 claim 上的历史实验，「推进了什么」（没有推进也照实说）。

        用户口径（2026-08-.. 实为 2026-10-04）："数值实验时间长是正常的……后面逐渐发现模式、
        优化枚举策略才把时间压下去。" 所以框架在这里做三件「只读」的事：

        ① 找出同 `claim_key` 的历史实验（最多最近 5 条），把它们的"界 / 耗时 / 策略"读出来；
        ② 与这一次比：界推了没有、耗电压了没有、策略换了没有；
        ③ 三者都没有推进时，明说"这次与上次同形"—— 那是读者最需要知道的一句话
           （真机里有 8 次同脚本 600 s 超时，台账上只有 8 个"超时"，看不出它们是同一件事）。

        它不拒绝、不拦、不改写结论：慢实验是研究的一部分，只有"没有新读数"才是问题。
        """
        # 按 `claim_key` 找历史（「不限同一个脚本」）：换脚本往往正是"换枚举策略"的形态，
        # 只在同脚本内比较会把最有价值的那次推进藏起来（实测：换成 b.py 之后比较不出来）。
        rows = [dict(r) for r in self.store.rows("experiments")
                if str(r.get("claim_key")) == str(claim_key)]
        if not rows:
            return ""
        prev = rows[-1]
        prev_code = str(prev.get("code_path") or "")
        prev_obs = _as_obs_dict(prev.get("observations"))
        now_obs = dict(derived.get("observations") or {})
        prev_bound = dict(prev.get("search_bound") or prev_obs.get("bound") or {})
        now_bound = dict(now_obs.get("bound") or {})
        prev_rt = _as_float(prev.get("runtime_sec"))
        prev_strategy = str(prev_obs.get("strategy") or "")
        now_strategy = str(now_obs.get("strategy") or "")
        bits = [f"同 claim 历史 {len(rows)} 条（最近一条 {prev.get('experiment_id')}："
                f"{'超时' if prev.get('exit_code') is None else 'exit=' + str(prev.get('exit_code'))}"
                f"，{prev_rt:.1f}s，result={prev.get('result')}）"]
        if prev_bound or now_bound:
            bits.append(f"界：上次 {prev_bound or '(没记)'} → 这次 {now_bound or '(没记)'}")
        if prev_rt and runtime_sec is not None:
            bits.append(f"耗时：上次 {prev_rt:.1f}s → 这次 {float(runtime_sec):.1f}s")
        if prev_strategy or now_strategy:
            bits.append(f"策略：上次 {prev_strategy or '(没记)'} → 这次 {now_strategy or '(没记)'}")
        if prev_code and prev_code != str(code_path):
            bits.append(f"脚本换了：{prev_code} → {code_path}")
        moved = (bool(now_bound) and now_bound != prev_bound) or \
                (bool(now_strategy) and now_strategy != prev_strategy) or \
                (bool(prev_code) and prev_code != str(code_path)) or \
                (prev_rt and runtime_sec is not None and float(runtime_sec) < prev_rt * 0.8)
        if not moved:
            bits.append("这次与上次**同形**（界/策略/耗时都没有推进）⇒ 想要新信息就得换枚举策略"
                        "（规范化、去同构、对称性剪枝、增量+回溯、SAT/ILP 编码、随机+证书）"
                        "或者把界说清（`bound`）——重复同一条超时脚本不算进展")
        else:
            bits.append("这次与上次不同形（有推进读数）")
        if timed_out and not now_obs.get("progress"):
            bits.append("而且这次脚本没有打 `PROGRESS:` 行 ⇒ 被超时杀掉之后连「搜到哪儿」都没有；"
                        "加上它（每完成一个 n 打一行）")
        return "[progress] " + "；".join(bits)

    def _reused_evidence_note(self, *, claim_key: str, code_hash: str,
                              derived: Mapping[str, Any]) -> str:
        """同一份证据（同脚本 + 同 `data`）被用来支持另一条断言时，说一句话。

        `draft/39` §6.27 的 D39（真机读数 T2 第 9 趟 `p6k`）：一个脚本被派了 9 次，
        claim 分别是 W(2)（3-正则）/ W(3)（4-正则）/ W(4)（5-正则）…… 而每次都打出
        逐字相同的 `data`：`{"n_vertices": 30, "degrees": [3], "girth": 8, …}`
        —— 那始终是同一个图（W(2) 的 Tutte–Coxeter 图）。台账上于是有 9 条 `supports`，
        手稿把它们当 9 份独立证据引；同一份读数被当成了九份。
        在此之前这条判据连材料都没有：`data` 根本不进台账（见 `_script_data`）。

        判据只做"把这件事说出来"：不拒绝、不改结论 —— 一个脚本被复用来核同一个对象
        是正当的（重跑复现），它要说清的是"这一次核的还是上一次那个对象吗"。
        """
        now_data = dict((derived.get("observations") or {}).get("data") or {})
        if not now_data:
            return ""
        for row in self.store.rows("experiments"):
            if str(row.get("claim_key") or "") == str(claim_key):
                # 这条断言已经有自己的证据行 ⇒ 这一次是复现（正当），不是"另一条断言拿了同一份证据"。
                return ""
        for row in self.store.rows("experiments"):
            if str(row.get("code_hash") or "") != str(code_hash):
                continue
            old_data = dict((row.get("observations") or {}).get("data") or {})
            if old_data and old_data == now_data:
                return (f"[同一份证据] 这个脚本（sha256 前 16 位 {str(code_hash)[:16]}）"
                        f"在 `exp:{row.get('experiment_id')}` 上给过**逐字相同**的 `data`"
                        f"（{_digest(str(now_data), 160)}），"
                        f"而那一条的断言是另一条（`{row.get('claim_key')}`）⇒ 先确认这次真的换了参数"
                        f"（把参数写进 `params`、把核的对象写进 `data` 的键里），"
                        f"否则这不是第二份独立证据，是同一份读数被算了两次")
        return ""


def _as_float(value: Any) -> float:
    """`runtime_sec` 之类"期望是数"的自由字段（子代理 agents #8）。

    脏值（`"abc"`、`None`、list）⇒ 0.0，**不抛**：这些值来自别的角色写进台账的行，
    `Experiment.validate()` 不校验该字段类型，于是 `float("abc")` 会在**脚本已经跑完之后**
    把整趟打死 —— 副作用发生了、记录却丢了。
    """
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _as_obs_dict(value: Any) -> dict:
    """`observations` 之类"期望是对象"的自由字段（子代理 agents #9）。"""
    if isinstance(value, Mapping):
        return dict(value)
    return {}
