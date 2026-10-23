"""角色 E 的动作 `run_experiment`（`goal-7f5116c1` M6：从 `agent_e.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from collections.abc import Mapping

from ._support import Any, E_NO_FORMAL_REASON, ExperimentError, Mapping, S, Sequence, ToolError, VT, _derive, _digest, _relpath, _result_reason, _write_run_log, build_experiment
from .. import exhaustionreport as _ER
from .. import verifications as VR

#: 「玩具例子」在台账上的落点：`experiments.observations[TOY_EXAMPLE_KEY]`。
#:
#: 为什么落 `observations` 而不是新加一列 / 改声明：`specs/e.py` 的动作声明面与
#: `schema.Experiment` 都是契约（前者在禁改区），而 `observations` 本来就是
#: "这一次到底算了什么"的自由读数格 —— 落在这里不动任何声明面。
#: 判据与三态见 :func:`_toy_example_reading` 的 docstring。
TOY_EXAMPLE_KEY = "toy_example"

#: 「小到能手工核对」的规模上限：`n <= 8`。
#:
#: 业主口径（2026-10，本批的验收词）：「玩具例子」= 「在一个小到能手工核对的情形上，
#: 把断言跑成可复现的读数」 —— 一条最小脚本 ＋ 一次真实执行 ＋ 一个读得出的数。
#: 它「不是」"再跑一遍原脚本"，也「不是」"把界从 n<=8 推到 n<=12"那种扫描清单：
#: 后者的读数是"扫到哪儿"，前者要的是"这一个数对不对，人能手算出来"。
TOY_EXAMPLE_MAX_N = 8

#: 规模读数的键名（受控词表，唯一出处 = 这一处）：脚本自报的
#: `observations` / `bound` / `data` / `scaling` 与调用方的 `params` 里，「只有」这些键
#: 被当作"这一趟算到多大的 n"。
#:
#: 为什么是一张白名单而不是"看着像大小的数都算"：自动判定要在「没有调用方声明」时
#: 替它下一个结论（`params["toy_example"]` 真机里常常没带下来）。收得太宽，一个
#: 大扫描里随便一个计数（`D`、`rank`、`count`）就会被读成规模，于是"扫描清单"被标成
#: 玩具例子 —— 那正是本批的负控要咬住的那一格。
#: `n_values` 这类「列表」形态单独一张表（取最大值：脚本扫了 [1,2,3]，规模就是 3）。
TOY_EXAMPLE_SCALE_KEYS: tuple[str, ...] = (
    "n", "N", "max_n", "n_max", "n_vertices", "n_nodes", "dim",
    "D_max", "M_max", "generator_width_M_max", "degree_max",
)
TOY_EXAMPLE_SCALE_LIST_KEYS: tuple[str, ...] = ("n_values", "ns")

#: 「脚本声明的搜索空间」这一档的键名（穷举/枚举类脚本自报"一共枚举了多少个对象"）。
TOY_EXAMPLE_SPACE_KEYS: tuple[str, ...] = (
    "search_space", "space", "cases", "objects", "enumerated", "combinations",
)

#: 搜索空间的上限：`8! = 40320`。
#:
#: 为什么是这个数（可自证）：`TOY_EXAMPLE_MAX_N = 8` 说的是"n 不超过 8"，
#: 而 n=8 的全排列空间恰好是 8! = 40320 个对象 —— 一个把 `n<=8` 的情形「枚举完」的
#: 脚本，最多也就报出这个数。超过它就不是"枚举了一个小情形"，而是"扫了一大片"。
TOY_EXAMPLE_MAX_SEARCH_SPACE = 40320

#: 脚本「真的给出了结论行」的读数（`observations["conclusion_source"]` 的取值）——
#: 「有结果行」的判据就用它，不另抄一份 `REPRO_RESULT` 解析。
TOY_EXAMPLE_RESULT_SOURCES: tuple[str, ...] = ("line", "json_key", "multiple")


def is_toy_example(reading: object) -> bool:
    """这一格读数「算不算」一个玩具例子 —— 唯一口径（读侧一律调它，不各写一份）。

    三条同时成立才算（少一条都只是"看起来像"）：

    1. `checked is True`：规模真的判过了（`checked=False` 是"判不了"，不是合格）；
    2. `within_limit is True`：规模确实小到能手工核对（超限 / 判不了都是 False）；
    3. `executed is True`：脚本「真跑过」（有退出码，且有结构化结论行）。

    为什么"标没标"要有一个函数而不是让每个读侧自己拼条件：真机里被读的正是
    "有没有玩具例子"这个数字，两份口径一旦分家，同一份台账会被数出两个值，
    而其中一份永远没人复算。
    """
    if not isinstance(reading, Mapping):
        return False
    return (reading.get("checked") is True
            and reading.get("within_limit") is True
            and reading.get("executed") is True)


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
        design: str | None = None,
        enumeration: str | None = None,
        exhaustive: bool | None = None,
        search_space: str | None = None,
    ) -> dict:
        """跑一个实验脚本并登记一条 `Experiment` 行。
        推导规则见模块 docstring（唯一权威表述）：计算类方法的推导在 :func:`_derive`。
        返回 ``{"experiment_id", "recorded", "result", "evidence_kind","negation_kind", "exit_code", "reason"}``。
        schema 校验失败必须让异常冒出来（本方法不做 try/except 兜底）：那说明上面的推导规则与 `Experiment.validate` 不一致，而"推导规则与 schema 打架"正是本项目最该炸的地方。
        形式化不在这一岗（业主 2026-10-23 晚：「E 侧与 Lean 相关的工具和动作都该清干净」）：
        `method="formal"` 在第一句就以受控理由码 `formal_not_in_e` 拒绝，本方法没有 formal 的
        实现路径（那条登记 formal 行的私有路径已随动作面一起删除），也不起检查器 ——
        形式化那一支由 L 承担。
        `name` / `imports` 只服务形式化那一支：本方法保留这两个形参只是为了把"传了也不做"
        变成一句受控拒绝（F 的派活路径会按同一份子目标把它们传下来），不是一条通道；
        动作表与工具 schema 上都没有它们。
        `design` / `enumeration` / `exhaustive` / `search_space` 是穷举证明的凭据（D-33，
        2026-10-23 夜 r34b 真机）：四个都可选，给了就原样进 `observations`（其中 design /
        enumeration / search_space 再经 `exhaustionreport.blocks_from` 落进
        `out/experiments/<实验号>/exhaustion.md` 的那几段）。为什么要从参数面收：
        提示词要求 E「跑之前先报三件套 + 把 exhaustive 写成布尔」，而这三格此前不在任何
        schema 里 ⇒ 模型只能传空 params，报告落不成、4 条 exhaustive_search 全落
        cross_check。等级由 `numericproof` 现算，不由这里判：缺任何一格，
        那一条就是 cross_check（有数值实验支持，不构成证明）。
        调用方显式给的那一格胜过脚本在 REPRO_RESULT 里自报的同名键（与 `search_bound`
        同一个优先级），两者不一致时 `notes` 里留一句话 —— 本方法不替它们折中。
        这里没有 `sleep` 形参，这是刻意的（`D-2`）`capabilities.CAPABILITIES["E"].run_experiment` 的 params 里声明了 `sleep`，而它不在本方法的形参表里，本方法也不收 
        `inspect.Parameter.VAR_KEYWORD`。这不是漏了一个参数，也不是"反正 kwargs 收得住"：`sleep` 只服务替身夹具（`tests/test_conductor.py` / 
        `tests/test_scheduler.py` 的 `FakeE` 按同一份 schema 传它来控制"这次实验跑多久"），已逐条登记在 `capabilities.PARAM_SEAMS`里（键含理由串），并由 
        `capabilities.assert_capabilities()` 第 [8] 条在`import agentflow.capabilities` 时核过：声明了而实现不收、又不登记 ⇒ 导入失败。
        两条不许做的改动：① 把 `sleep` 从能力表里删掉 —— 那会让替身无法按 schema 传参，被测的就不再是那条真实链路；② 在这里补一个具名的 `sleep`，或让它收`inspect.Parameter.VAR_KEYWORD`
        —— 前者是没人读的假承诺，后者把"我传了但它没看"变成静默成功，而 `conductor.LocalBackend.call` 的 docstring 逐字拒绝的正是这个形态。参数门的口径（声明 ∩ 实现签名）见
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
        # certificate、给了 certificate 必须给 search_bound。与下面 name/imports
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

        # ---- [0] 形式化不是 E 的活（业主 2026-10-23 晚裁定：逐字「E 侧与 Lean 相关的
        # 工具和动作都该清干净」）。
        #
        # 改前这一支的形态是"写死关闭"：动作还在，第一句回受控拒绝 `formal_moved_to_l`
        # 并把形式化指向 L。裁定之后那个概念也没了 —— 动作表里没有 `check_formal`，
        # 本方法里没有 formal 的实现路径（那条登记 formal 行的私有路径已删）。所以这一档只剩一句话：
        # E 不做形式化。它不指向任何人（"搬到 L"是那个过时的转述），只如实说这一岗的范围。
        #
        # 为什么仍在跑脚本之前拒：形式化实验的产物是一份 `.lean`，跑起来要起检查器。
        # 只靠下游兜的表现是：台账里多一条 inconclusive 的 formal 行、模型多花一步，
        # 而用户看到的是"实验失败"，不是"这条路不在 E 身上"。
        if method == "formal":
            raise ExperimentError(
                f"E 不做形式化（理由码 {E_NO_FORMAL_REASON}）：本岗的动作面没有 "
                "method='formal'，也不起任何检查器。要跑实验请用 method='numeric' | "
                "'symbolic' | 'exhaustive_search'；一条断言的证明那一档由别的岗承担，"
                "本岗不替它下结论"
            )
        if name is not None or imports is not None:
            raise ExperimentError(
                f"E 不做形式化（理由码 {E_NO_FORMAL_REASON}）⇒ name / imports 没有意义"
                f"（收到 method={method!r}）—— 它们是给检查器的参数，而本岗不起检查器；"
                "证据等级由 `_derive` 推导。静默忽略会让调用方以为自己指定了检查条件"
                "（说明了 imports，实际什么也没发生）"
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

        # ---- [4c] 玩具例子读数（`observations[TOY_EXAMPLE_KEY]`）
        #
        # 业主口径（本批的验收词）：玩具例子 = "在一个小到能手工核对的情形上，把断言跑成
        # 可复现的读数" —— 一条最小脚本 ＋ 一次真实执行 ＋ 一个读得出的数。
        # 落点、上限与三态见 `_toy_example_reading` 的 docstring。
        #
        # 「不让 E 等调用方记得带声明」（本批缺陷二的真机读数）：`projects/mp3` 的两条
        # 实验里，第二条的 claim 自己写着"玩具读数"、`bound` 是 `D<=6 / M<=8 / n<=3`，
        # 而 `observations` 里 `toy_example` 「一条都没有」 —— 因为只有经 `F→E` 且父把
        # `params["toy_example"]` 带下来才会标，而模型不一定会带。所以声明缺席时由 E
        # 「按规模与可手算性自己判」（见 `_auto_toy_example_reading` 的三态）。
        toy = _toy_example_reading(
            params=params, observations=derived.get("observations"),
            exit_code=run["exit_code"],
            code_path=_relpath(path, self.workspace_root), code_hash=chash)
        if toy is not None:
            derived["observations"][TOY_EXAMPLE_KEY] = toy

        # ---- [4b]（在事务内写日志：文件名要用实验号，见 [5]）

        # ---- [4c2] D-33：调用方报的穷举凭据（design / enumeration / exhaustive /
        # search_space）落在 observations 里 —— 下游三处读的是同一份，不各写一份转换。
        #
        # 真机读数（r34b，2026-10-23 夜）：4 条 exhaustive_search 的 observations 里
        # ②③ 一格都没有，exhaustion.md 于是缺三块里的前两块，等级全落 cross_check。
        # 根因不在提示词（它要求 E 跑之前先报三件套），而在工具面收不下那三格 ——
        # 这一轮把参数面补齐之后，它们在这里落到行上：
        #   ① `exhaustionreport.blocks_from` 从这里读 design / enumeration /
        #      search_space 写进报告（报告与台账因此是同一句话）；
        #   ② `numericproof.exhaustion_problems` 从这里读同一批事实判等级；
        #   ③ 读的人打开 experiments 那一行就能看见 E 报了什么。
        # 优先级与下面 [4d] 的 `search_bound` 一致：调用方显式给 > 脚本自报；
        # 两者不一致时留一句 note（不替它们折中 —— 折中会造出第三个值，
        # 而那个值没有出处）。
        for _key, _value in (("design", design), ("enumeration", enumeration),
                             ("exhaustive", exhaustive), ("search_space", search_space)):
            if _value is None:
                continue
            if isinstance(_value, str) and not _value.strip():
                continue
            _had = _key in derived["observations"]
            _old = derived["observations"].get(_key)
            derived["observations"][_key] = _value
            if _had and _old != _value:
                notes.append(
                    f"[{_key}] 调用方给的是 {_value!r}，脚本自报的是 {_old!r} ⇒ 行上记"
                    "调用方那份（与 `search_bound` 同一优先级）；两者不一致这件事留在这里"
                    "给读的人看，不替它们折中")

        # ---- [4d] `search_bound` 的优先级（§133）：调用方显式给 > 脚本在结构化结论里
        # 自报的 `bound`（落进 `observations["bound"]`）> 无。脚本自报的那份是"这次真搜到
        # 哪儿"的读数，比调用方拍的那个数可信 —— 它让"界有没有往前推"可比较。
        #
        # 这一份要在写 ②③ 的读数之前算好：E 写的那份报告里"搜索空间"那一段，
        # 与台账上 `search_bound` 那一列必须是同一个数（两处不一致 = 同一件事两个地址）。
        bound_arg = (dict(search_bound) if isinstance(search_bound, Mapping)
                     else (dict((derived.get("observations") or {}).get("bound") or {})
                           or None))

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
            # ---- [5a] ②③ 落盘（业主 2026-10-23 晚：「E 写的报告要能落下来」）
            #
            # 改前 ②③ 只活在 `observations` 的自由格里：台账上有那两段字，盘上却没有一份
            # 可引用的东西 —— B 登记时只能把文本贴进证明栏，G 在正文里也没法指向一份文件，
            # V 更没有材料可核。现在它们落成 `out/experiments/<实验号>/exhaustion.md`，
            # 并把路径、字节数与 sha256 记进 `observations["exhaustion_report"]`。
            #
            # 落不成就如实降档（不是抛异常）：这一趟实验真的跑过了，报告没落成是
            # "这条证据不够 proof"，而"不太够"由 `numericproof.exhaustion_problems`
            # 单点决定（它会把这一格并进"缺什么"），所以这里只负责写出事实并记一句 note。
            #
            # D-33：`design` / `enumeration` / `search_space` 三格现在可能来自
            # `run_experiment` 的入参（[4c2] 已经把它们并进 observations）—— 所以
            # 这三块的内容既可能是 E 递下来的，也可能是脚本自报的，读口只有一个
            # （`blocks_from` -> `numericproof` 的那几个读函数）。这里刻意不写
            # `design=design or ...`：那会造出第二个读口，两处一旦分家，
            # 报告与证明栏就会说两句不同的话。
            _blocks = _ER.blocks_from(observations=derived.get("observations"),
                                      certificate=certificate, search_bound=bound_arg)
            report = _ER.land_report(
                self.workspace_root, experiment_id=eid, claim=claim, claim_key=claim_key,
                script_path=_relpath(path, self.workspace_root), script_sha256=chash,
                design=_blocks["design"], enumeration=_blocks["enumeration"],
                search_space=_blocks["search_space"],
                environment=_ER.environment_reading(exit_code=run["exit_code"],
                                                    runtime_sec=run["runtime_sec"]),
                result=derived.get("result"), evidence_kind=derived.get("evidence_kind"))
            if report.get("problems"):
                notes.append("[report] ②③ 的读数没有落成："
                             + "；".join(str(p) for p in report.get("problems") or [])
                             + " ⇒ 这一条不许标 proof（最多是「有数值实验支持」）")
            derived["observations"][_ER.REPORT_KEY] = report
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
                search_bound=bound_arg,
                created_by=self.actor,
            )
            tx.upsert("experiments", row.to_dict(), note=f"experiment:{claim_key}")

        # 签名那一格（`observations.e_signature`）：谁签、谁写 ②③ —— 读侧不自己去翻台账。
        # 从 `row` 上读而不是从 `derived` 上读：签名是 `build_experiment` 里现算并写进
        # 那一行的，`derived` 里没有它（读 `derived` 会得到一格空字符串，而看上去像"没签"）。
        _obs = row.observations if isinstance(row.observations, Mapping) else {}
        _sig = _obs.get("e_signature")
        _sig = dict(_sig) if isinstance(_sig, Mapping) else {}
        out = {
            "experiment_id": eid,
            "recorded": True,
            "result": row.result,
            "evidence_kind": row.evidence_kind,
            "negation_kind": row.negation_kind,
            "exit_code": row.exit_code,
            "runtime_sec": row.runtime_sec,
            "code_hash": row.code_hash,
            # ②③ 的落点（业主 2026-10-23 晚：E 写的报告要能落下来；读的人要能拿到路径）：
            # 一份读数里两块都在，`blocks` 说清哪两段真的写了字。B 登记证明栏时指它、
            # G 在正文里引它、V 会审时读它 —— 三处引用的是同一个相对路径。
            "report_path": str(report.get("path") or ""),
            "report_sha256": str(report.get("sha256") or ""),
            "report_bytes": int(report.get("bytes") or 0),
            "report_blocks": dict(report.get("blocks") or {}),
            "report_problems": [str(p) for p in report.get("problems") or []],
            "signed_by": str(_sig.get("signed_by") or ""),
            "proof_authors": [str(a) for a in (_sig.get("proof_authors") or [])],
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
        # "同一份证据"的身份只有一处定义（`verifications.evidence_identity`）：
        # 审计期那条判据（`one_evidence_used_twice`）读的是同一个函数 ⇒
        # "E 在 notes 里点了名"与"审计会报"不会给出两套答案（FC-03）。
        ident = VR.evidence_identity({"code_hash": code_hash,
                                      "observations": {"data": now_data}})
        for row in self.store.rows("experiments"):
            if VR.evidence_identity(row) != ident:
                continue
            return (f"[同一份证据] 这个脚本（sha256 前 16 位 {str(code_hash)[:16]}）"
                    f"在 `exp:{row.get('experiment_id')}` 上给过**逐字相同**的 `data`"
                    f"（{_digest(str(now_data), 160)}），"
                    f"而那一条的断言是另一条（`{row.get('claim_key')}`）⇒ 先确认这次真的换了参数"
                    f"（把参数写进 `params`、把核的对象写进 `data` 的键里），"
                    f"否则这不是第二份独立证据，是同一份读数被算了两次")
        return ""


def _as_float(value: Any) -> float:
    """`runtime_sec` 之类"期望是数"的自由字段（子代理 agents #8）。

    脏值（`"abc"`、`None`、list）⇒ 0.0，「不抛」：这些值来自别的角色写进台账的行，
    `Experiment.validate()` 不校验该字段类型，于是 `float("abc")` 会在「脚本已经跑完之后」
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


def _toy_example_reading(*, params: Mapping[str, Any] | None,
                         observations: Mapping[str, Any] | None = None,
                         exit_code: Any,
                         code_path: str, code_hash: str) -> dict | None:
    """把「这一次跑的是一个玩具例子」落成一格可查的读数（`observations["toy_example"]`）。
        ```python
        {"declared": {"n": 6, "expect": 265, "quantity": "D(6)"},   # 调用方声明，原样
         "checked": True, "within_limit": True, "n": 6, "limit": 8,   # 规模够小
         "executed": True, "exit_code": 0,                            # 真跑过
         "script_path": "code/attack_s1.py",                          # 跑的是哪一份
         "script_sha256": "e86a6c9a16d7d4cf",                          # 与 code_hash 同一份文件
         "why": ""}
        ```
    没声明时 `declared` 那一格由「自动判定」填（`{"auto": True, "source": …}`，`why` 里写清"由规模自动判定"）—— 见 :func:`_auto_toy_example_reading`。
    「这是一个玩具例子」的第一顺位仍是「调用方」的声明：`run_experiment(params=...)`里的 `toy_example` 那一格（F 把子目标的 `params` 原样带下来，一个字不改）。声明在时本函数只做三件「机械的」事
    —— 不替调用方判断"这算不算玩具"，也不相信「脚本的」自我陈述（脚本能自报的只有 `REPRO_RESULT`，它决定不了"这次实验的规模够不够小"）：
    ① 核对声明的规模 `n` 不超过 :data:`TOY_EXAMPLE_MAX_N`：超过 ⇒ `within_limit=False`并把上限写在同一格里（"标了玩具但其实是个扫描清单"是读得出来的，不是被吞掉）；② 贴上"真跑过"的事实：
    `executed`（有没有退出码）、`exit_code`、`script_path`、`script_sha256` —— 于是"只写了脚本"与"真的跑过一次"在行上分得开（反真空）；③ 把声明原样留在 `declared` 里（不改写、不
    解释、不替它补字段）。
    真机（`projects/mp3/data/experiments.json`）：两条实验，`params` 都是 `{}`，而第二条的 claim 逐字写着"玩具读数"、`bound` 是 `D<=6 / M_max<=8 / n<=3`、
    `exit_code=0` —— `observations` 里 `toy_example` 「0 条」。根因是"只有经 `F→E`且父把 `params["toy_example"]` 带下来才会标"，而模型不一定会带。于是这一档改成：声明
    缺席时由 E 在「落库那一刻」按规模与可手算性自动判定（:func:`_auto_toy_example_reading`），并且「不许」把大扫描标成玩具例子。
    三态（`checked`）- `checked=True, within_limit=True/False`：声明/规模成形、判过了；- `checked=False, within_limit=None`：判不了（声明不是对象 / 没有数值 
    `n` /自动判定找不到任何规模读数）—— 「判不了 ≠ 合格」，`why` 里写清缺什么。
    "标没标"的唯一口径是 :func:`is_toy_example`（三条同时成立），不是单独看某一位。
    
    """
    params = dict(params) if isinstance(params, Mapping) else {}
    declared = params.get(TOY_EXAMPLE_KEY)
    if declared is None:
        return _auto_toy_example_reading(
            params=params, observations=observations, exit_code=exit_code,
            code_path=code_path, code_hash=code_hash)
    out: dict[str, Any] = {
        "declared": dict(declared) if isinstance(declared, Mapping) else declared,
        "checked": False,
        "within_limit": None,
        "n": None,
        "limit": TOY_EXAMPLE_MAX_N,
        # 执行事实与"规模判没判成"无关：这两格无论 `checked` 是哪一档都照实给。
        "executed": exit_code is not None,
        "exit_code": exit_code,
        "script_path": str(code_path or ""),
        "script_sha256": str(code_hash or ""),
        "why": "",
    }
    if not isinstance(declared, Mapping):
        out["why"] = (f"`params[{TOY_EXAMPLE_KEY!r}]` 不是对象（{type(declared).__name__}）⇒ "
                      "判不了这一条算不算玩具例子（要 {n, expect, quantity} 这样的对象）")
        return out
    n = declared.get("n")
    if isinstance(n, bool) or not isinstance(n, (int, float)):
        out["why"] = (f"`params[{TOY_EXAMPLE_KEY!r}]` 里没有数值 `n`（收到 {n!r}）⇒ "
                      f"判不了规模有没有小到能手工核对（上限 {TOY_EXAMPLE_MAX_N}）")
        return out
    out["checked"] = True
    out["n"] = n
    out["within_limit"] = bool(float(n) <= TOY_EXAMPLE_MAX_N)
    if not out["within_limit"]:
        out["why"] = (f"声明的规模 n={n} 超过玩具例子的上限 {TOY_EXAMPLE_MAX_N} ⇒ 这一条"
                      "不是玩具例子（它是一份扫描清单：读数是'扫到哪儿'，不是"
                      "'这一个数人能手算出来对不上'）")
    return out


def _scale_numbers(value: Any, *, max_depth: int = 3) -> tuple[float | None, float | None, str]:
    """从一个自由形状的读数里挑出 `(最大 n, 最大搜索空间, 出处)`。
    `observations` / `bound` / `data` / `scaling` 都是「自由格」（脚本自己写的键），形状没有契约，所以这里按「白名单键名」递归找（:data:
    `TOY_EXAMPLE_SCALE_KEYS` 等），并且只认"数值"（布尔、字符串、`None` 一律不认 —— `True` 会被 `float()` 读成 1，悄悄
    造出一个规模）。
    两件事刻意定死：
    1. 「取最大值」（不是第一个命中）：规模由"这一趟算到多大的那一格"决定 ——一个脚本先算了 n=3 再扫到 n=14，它是扫描清单，不是玩具例子； 2. 「递归到有限深
    度」（默认 3 层）：`bound` / `data` / `scaling[]` 都是嵌套形态（真机：
    `bound={"A": {"D_max": 6}, "B": {"n_values": [1,2,3]}}`）。再深就不是"规模声明"，而是数据本身了 —— 那里面任何数
    字都不该被读成规模。
    """
    best_n: float | None = None
    best_space: float | None = None
    src = ""

    def _num(v: Any) -> float | None:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        return float(v)

    def _walk(node: Any, path: str, level: int) -> None:
        nonlocal best_n, best_space, src
        if level > max_depth or not isinstance(node, Mapping):
            return
        for key, val in node.items():
            name = str(key)
            where = f"{path}.{name}" if path else name
            if name in TOY_EXAMPLE_SCALE_KEYS:
                got = _num(val)
                if got is not None and (best_n is None or got > best_n):
                    best_n, src = got, where
                continue
            if name in TOY_EXAMPLE_SCALE_LIST_KEYS and isinstance(val, (list, tuple)):
                nums = [x for x in (_num(v) for v in val) if x is not None]
                if nums and (best_n is None or max(nums) > best_n):
                    best_n, src = max(nums), f"{where}[]"
                continue
            if name in TOY_EXAMPLE_SPACE_KEYS:
                got = _num(val)
                if got is not None and (best_space is None or got > best_space):
                    best_space = got
                    if not src:
                        src = where
                continue
            # 只往下走一层结构（不把 `str` / `bytes` 当结构）
            if isinstance(val, Mapping):
                _walk(val, where, level + 1)
            elif isinstance(val, (list, tuple)):
                for i, item in enumerate(val[:40]):
                    if isinstance(item, Mapping):
                        _walk(item, f"{where}[{i}]", level + 1)

    _walk(value, "", 0)
    return best_n, best_space, src


def _toy_example_executed(*, exit_code: Any,
                          observations: Mapping[str, Any] | None) -> bool:
    """这一趟算不算"「真跑过」"（玩具例子的第 3 条，唯一判据）。
    
    两个条件同时成立：
    
    1. 有退出码（`exit_code is not None`）—— 超时 / 起不来都没有； 2. 有「结构化结论行」（`observations["conclusion_source"]`
    是:data:`TOY_EXAMPLE_RESULT_SOURCES` 之一）—— 脚本跑完却没按协议打出结论，就只是"执行过"，不是"把断言跑成了一个读得出的数"。
    
    为什么单独抽出来：读写两侧都必须问同一个问题（写侧决定标不标，读侧`is_toy_example` 决定算不算），而"没真跑"这一档的负控要能单独注射 ——判据自己的可注射
    性也是它的一部分（不然"这条判据能红"没法被检验）。
    """
    if exit_code is None:
        return False
    src = str((observations or {}).get("conclusion_source") or "")
    return src in TOY_EXAMPLE_RESULT_SOURCES


def _auto_toy_example_reading(*, params: Mapping[str, Any] | None,
                              observations: Mapping[str, Any] | None,
                              exit_code: Any, code_path: str,
                              code_hash: str) -> dict | None:
    """调用方没带 `toy_example` 声明时，由 E 「按规模与可手算性」自己判（本批缺陷二）。
    真机（`projects/mp3/data/experiments.json` 的第二条）：claim 逐字写着"玩具读数"、`bound` 里是 
    `D_max=6 / generator_width_M_max=8 / n_values=[1,2,3]`、`exit_code=0`，而 `observations` 里 `toy_example` 「0 条」
    —— 因为只有父把声明带下来才会标。
    判据（三条同时成立才算"标了"；唯一读法是 :func:`is_toy_example`）1. 「规模小」：从 `params` ＋ 脚本自报的 `observations`（含 `bound` / `data` /
    `scaling`）里按白名单键名找规模读数 —— 有 `n` 类读数就要求`n <= TOY_EXAMPLE_MAX_N`；有搜索空间读数就要求`<= TOY_EXAMPLE_MAX_SEARCH_SPACE`（两者都
    有则都要满足）； 3. 「真跑过」：`exit_code` 非空 「且」 有结构化结果行（`observations["conclusion_source"]` ∈ :data:
    `TOY_EXAMPLE_RESULT_SOURCES`）。只写了脚本、或跑了但没打出结论行 ⇒ `executed=False`，读数照落但「不算」玩具例子。
    | 结局 | 返回 ||---|---|| 找不到任何规模读数 | `None`（这一趟没东西可判，行与从前逐字节相同） || 找到规模读数 | 一格读数：`checked=True`，`within_limit` 按上
    面三条算，`why` 写清"由规模自动判定"+ 依据 || 有规模、但没真跑 | 同一格读数 + `executed=False` + `why` 点名"没真跑"（「不标」，但看得见） |
    为什么"没真跑"也照落一格：`executed` 与"规模判没判成"是两件事（声明那一支也这么分）。
    """
    params = dict(params) if isinstance(params, Mapping) else {}
    obs = dict(observations) if isinstance(observations, Mapping) else {}
    n_params, space_params, src_params = _scale_numbers(params)
    n_obs, space_obs, src_obs = _scale_numbers(obs)
    ns = [x for x in (n_params, n_obs) if x is not None]
    spaces = [x for x in (space_params, space_obs) if x is not None]
    if not ns and not spaces:
        return None
    n = max(ns) if ns else None
    space = max(spaces) if spaces else None
    source = src_obs or src_params
    executed = _toy_example_executed(exit_code=exit_code, observations=obs)
    within = True
    why = ""
    if n is not None and float(n) > TOY_EXAMPLE_MAX_N:
        within = False
        why = (f"由规模自动判定：n={_as_n(n)} 超过玩具例子的上限 {TOY_EXAMPLE_MAX_N}"
               f"（出处 {source}）⇒ 这一条不是玩具例子（它是一份扫描清单：读数是"
               "'扫到哪儿'，不是'这一个数人能手算出来对不上'）")
    elif space is not None and float(space) > TOY_EXAMPLE_MAX_SEARCH_SPACE:
        within = False
        why = (f"由规模自动判定：脚本声明的搜索空间 {_as_n(space)} 超过上限 "
               f"{TOY_EXAMPLE_MAX_SEARCH_SPACE}（出处 {source}）⇒ 这一条不是玩具例子")
    if within and not executed:
        why = ("由规模自动判定：规模够小（n={}），但脚本没有真的跑出结论行"
               "（exit_code={}，结论行={!r}）⇒ 不标玩具例子（没真跑就不算"
               "'把断言跑成可复现的读数'）".format(
                   _as_n(n) if n is not None else "（没报 n）",
                   exit_code, str(obs.get("conclusion_source") or "")))
    elif within:
        bits = [f"n={_as_n(n)}" if n is not None else "",
                f"搜索空间={_as_n(space)}" if space is not None else ""]
        why = ("由规模自动判定：{} 都在上限内（n ≤ {}，搜索空间 ≤ {}，出处 {}）⇒ 这一条"
               "是玩具例子".format("、".join(b for b in bits if b),
                                  TOY_EXAMPLE_MAX_N, TOY_EXAMPLE_MAX_SEARCH_SPACE, source))
    return {
        "declared": {"auto": True, "source": source,
                     **({"n": _as_n(n)} if n is not None else {}),
                     **({"search_space": _as_n(space)} if space is not None else {})},
        "checked": True,
        "within_limit": bool(within),
        "n": _as_n(n),
        "limit": TOY_EXAMPLE_MAX_N,
        "executed": bool(executed),
        "exit_code": exit_code,
        "script_path": str(code_path or ""),
        "script_sha256": str(code_hash or ""),
        "why": why,
    }


def _as_n(value: float | int | None) -> Any:
    """规模读数进台账时的形态：整数就给 `int`（`n=6.0` 与 `n=6` 在 JSON 里是两个值）。"""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return value
    return int(f) if f == int(f) else f
