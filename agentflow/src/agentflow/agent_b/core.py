"""角色 B 的实现核心（`goal-7f5116c1` M6）：其余成员 + 把动作 mixin 装起来。

动作方法一个都没留在这里 —— 它们各自在 `agent_b/<动作>.py`。
这一层与各动作文件共用 `_support.py`（模块级 helper 与常量）。
"""
from __future__ import annotations

from ._support import Any, BClaimOutcome, D, I, Mapping, NOTE_LIMIT, NO_EXTRACTOR_ERROR, REPROCESS_RESULTS, S, Sequence, Store, T, _passages, check_quote, lease_expired, make_lease
from .. import quoteevidence as _QE   # D1：区间只有一个产出点
from .. import conceptrows as _CR   # 并表过渡层：老表写完同步一份新标准（两处同号）
from ..store import StoreError      # 视图判不了时"再抛一次"（种子读失败必须被看见）
from .run_once import _RunOnce
from .reprocess_once import _ReprocessOnce
from .run_reprocess import _RunReprocess
from .decide_structural_duplicate import _DecideStructuralDuplicate
from .resolve_structural_duplicate import _ResolveStructuralDuplicate
from .register_statement import _RegisterStatement
from .run import _Run
from .proof_research import _ProofResearch


def _give_up_note(row: Mapping[str, Any], *, max_attempts: int) -> str:
    """到达重试上限时的结论：必须分清「真抽过、失败 N 次」与「从未真抽」。
    ## 为什么这不是措辞问题（`D-2` 的第四档，2026-10-02 主控裁定）
    `mine_attempts` 只在 `_claim` 里累加，而「这台机器没有任何够格的抽取器」（`R-56` 的拒抽，
    `last_mine_error == no_llm_extractor`）走的是同一条认领路径⇒ 到上限时那句原本统一写下的「超过最大抽取尝试次数」把「一次都没做」写成了
    「做过并反复失败」。这正是本项目对第三态的全部纪律所禁止的折叠（"没做" != "做了没成"；`draft/28` 的 `#3`）。
    计数语义本身（让领取计数区分这两档）是设计级残余（已登记 `draft/58`），本函数只负责如实说：到上限的是排队次数，不是抽取次数。
    判据在 `tests/test_d2_lease_alignment.py`：- 没有抽取器的那一行 ⇒ 说明里不许出现"超过最大抽取尝试次数"，且必须点出"没有可用的抽取
    器 / 从未真抽"；- 真抽过 3 次失败的那一行 ⇒ 仍是"真抽过失败"那一档（原话与 `上一次错误` 都保留）。
    """
    last = str(row.get("last_mine_error") or "").strip()
    if last == NO_EXTRACTOR_ERROR:
        return (f"从未真抽过：没有可用的抽取器（{NO_EXTRACTOR_ERROR}）⇒ 到上限的是排队次数，"
                f"不是抽取次数，已放弃排队。（`max_attempts`={max_attempts}）")
    if not last:
        return (f"重试次数已用尽（`max_attempts`={max_attempts}），但没有留下任何失败原因"
                "（认领之后、写下错误之前中断过）⇒ 已放弃。")
    return f"超过最大抽取尝试次数 {max_attempts}，已放弃。上一次错误：{last}"


class _Core:
    def __init__(
        self,
        store: Store,
        *,
        extractor: Any,
        extract_text: Any,
        config: dict | None = None,
        actor: str = "agent-B",
        secretary: Any = None,
        auto_secretary: bool = True,
    ):
        self.store = store
        self.extractor = extractor
        self.extract_text = extract_text
        # ---- 业主 2026-10-09：「写入侧应该都是B的活，让B的秘书帮它洗格式、拿编号、改表、
        # 查重，即B不直接用增工具，秘书实际操作增、改、查工具，B纯粹负责消化理解。」
        # ⇒ 命题的写盘从这里挪到秘书（`Secretary.record_statement`）。
        # 装配口径与 `AgentLoop` 同一套（T14：「每唤起一个智能体就自带一个秘书」）：
        # 给了就用；`auto_secretary=False` 只留给单测造"没有秘书"那一态；
        # 否则按 B 现派生一个（不抛：派生失败 ⇒ 写路径关闭，但这件事在返回值里读得到）。
        self.secretary = secretary
        self.auto_secretary = bool(auto_secretary)
        self.secretary_problem = ""
        # ---- `R-56`（`draft/28` §156）：回退抽取器必须拒抽。
        #
        # 判据刻意打在"抽取器是不是框架的规则回退"上，而不是"有没有接 LLM"：
        # 单测与自检会故意注入替身抽取器来测流水线（那时不该拒），
        # 而真正灌碎片的是 `llm.RuleExtractor` 这个回退实现 —— 实测它把网页/PDF
        # 的碎片当成概念与关系（概念名 `ANU` / `tingled property` /
        # `promote \tsm to this status)`），而引文回验全真（那句话确实在文件里）
        # ⇒ 在表里看起来像"有逐字引文的证据"。引文回验只证明"这句话在文件里"，
        # 不证明"这是一个概念/关系"。
        #
        # 处置选"拒抽"而不是"标 suspect"：概念表没有可疑档（relations 有，
        # concepts 没有），而给概念图灌碎片是不可逆的污染（下游 C/D 都会读到）。
        # 拒抽时不置 `processed`（与"抽取失败"同一口径），于是接线 LLM 之后
        # 那一轮还会重新领到这些行。
        self.extractor_is_fallback = self._is_fallback_extractor(extractor)
        self.cfg = config or {}
        self.actor = actor
        self.lease_seconds = int(self.cfg.get("lease_seconds", 900))
        self.max_attempts = int(self.cfg.get("max_attempts", 3))
        self.dup_strong = float(self.cfg.get("dup_strong", 0.92))
        self.dup_review = float(self.cfg.get("dup_review", 0.72))
        self.widen_pages = int(self.cfg.get("quote_widen_pages", 1))
        self.allow_fulltext_fallback = bool(self.cfg.get("allow_fulltext_quote_fallback", False))
        # ---- `R2b-⑫`：无文本层时的 OCR 回退
        #: `ocr.*` 的工具面句柄。`None` ⇒ 真要用时按角色 B 现取一次（`_ocr_call`）。
        #: 留这个口子不是图省事：`ocr.*` 要走「工具面」（谁调得到、参数怎么校验都由
        #: 它管），而 `AgentB` 这一层此前没有工具句柄 —— 现取一个注册表比直接 import
        #: handler 诚实，后者会绕开权限面与参数校验（`P-14` / `H-4` 的同族）；
        #: `_ocr_surface` 是给夹具的注入口，生产路径上恒为 `None`。
        self._ocr_surface: Any = None
        self._ocr_registry: Any = None
        #: OCR 尝试的读数（每次 `_ocr_retry` 追加一条）：`checked` 是"试没试"，
        #: `via` 是"走到哪一步"，`reason` 是"没做到的原因"。单列成表是为了让
        #: "试过 OCR 但没成"在运行后看得见 —— 只写在 `result_note` 里会被下游截断。
        self.ocr_readings: list[dict[str, Any]] = []
        # ---- I4 定向重抽取
        #: "等价表述"的相似度下限。低于它就不认（宁可报 not_found 也不猜）：
        #: 转写与原文的 token Jaccard 在阈值以下时，"找没找到"就变成了掷骰子，
        #: 而 I4 的全部价值在于"它说的话可以被核实"。
        self.reprocess_min_similarity = float(self.cfg.get("reprocess_min_similarity", 0.5))
        #: 在声明页码两侧多看几页（页码常常只错一页；与引文回验的 ±widen 同思路）。
        self.reprocess_context_pages = int(self.cfg.get("reprocess_context_pages", 1))
        #: 一次 `run()` 里最多处理多少条重抽取请求（有界：不许无限循环）。
        self.max_reprocess_per_run = int(self.cfg.get("max_reprocess_per_run", 10))
    def _statement_secretary(self) -> Any:
        """B 的秘书（命题写入代理）；`None` ⇒ 这一趟写不了（原因见 `secretary_problem`）。

        为什么在 AgentB 这一层也要派生：`AgentLoop` 那条路（LLM 循环）会注入一个，
        而 `AgentB` 也被直接调用（工具层、单测、离线脚本）—— 两条路上"B 的写入都经秘书"
        这条口径必须是同一件事。派生失败不抛（与 `AgentLoop.__post_init__` 同一条理由：
        工厂坏了是环境问题），但"没有秘书"这件事落在 `secretary_problem` 里，
        于是它在返回值里读得到（`register_statement` 会把它写成受控拒绝）。

        ## 2026-10-26（真机 sylow5）：现派生的那一条必须带缝

        改前这里走 `for_role("B", root=..., store=...)` —— 没传 `seam=`、也没开
        `enable_model`，于是这一名秘书的命题同一性判定（`record_statement` →
        `adjudicate_proposition` → `judge`）在第二道闸上永远折成
        `checked=False`：真机 sylow5 的 `out/secretary/proposition_verdicts.jsonl`
        一次都没被建出来，9 条命题里 `proof_no` 非 None 的 0 条，同一条定理被登记
        2–3 次（`Sylow I（存在性）` 与 `命题 1（Sylow I 存在性）` 各自成行）。

        单测一直是绿的，因为每一处判据都自己塞了一条 `_FakeSeam` —— 断的正是这一根
        装配线。`for_role_wired` 在造秘书之前先把缝拿来（`llmseam.LlmSeam.for_secretary`，
        业主 2026-10-14：「所有智能体的秘书另外共用一个 api key」），拿不到就把
        "为什么"写进 `model_source`，于是 `judge` 的 `checked=False` 与
        `record_statement` 的 `proposition_adjudication` 都带着那句原因。

        缝的派生本身不惜代价地 fail-open：`seam_for_secretary` 自己把"拿不到缝"
        （没装 llmseam / 造缝抛异常 / 秘书档没配 key）都折成 `None` + 一句读数，
        所以造缝失败不会把整条写路径关掉 —— 写入仍然要能发生，判词那一格如实报判不了。
        """
        if self.secretary is not None or not self.auto_secretary:
            return self.secretary
        try:
            from ..secretary import for_role_wired

            self.secretary = for_role_wired("B", root=self.store.root, store=self.store)
        except Exception as exc:  # noqa: BLE001 —— 派生失败 ⇒ 写路径关闭，但不许静默
            self.secretary = None
            self.secretary_problem = (f"秘书派生失败（{type(exc).__name__}: {exc}）⇒ "
                                      "命题的写路径整体关闭")
        return self.secretary

    def _conflict_scope(self, tx) -> list[dict] | None:
        """把"图里已有的关系"交给 I6 闸门 —— 从当前事务里读，不新开事务。

        为什么单独一个方法：`interactions.check_conflict` 的硬约束是"调用方在
        自己的事务内把已有关系读好传进去，闸门自己绝不拿锁"。
        把"从哪读"收敛到唯一一处，这条约束才有落点（评审时只看这一个方法即可）。

        返回 `None` 的语义是"本次没有能力检查"（`check_conflict` 会返回
        `checked=False`），它与空列表（"读了，图里确实没有可比的关系"）完全是两回事。
        生产路径永远返回 `tx.rows("relations")`；测试与将来的降级路径可以显式返回
        `None`，让"没检查"这条分支可被触发、可被观察，而不是停留在纸面上。
        """
        return tx.rows("relations")
    def _claim(self) -> BClaimOutcome:
        """在锁内领一条未处理文献：置 `claimed_by` / `lease_until` / `mine_attempts+=1`。
        返回 :class:`BClaimOutcome` 而不是 `dict | None` —— 理由见那个类的 docstring："队列空了" / "全被别人持着" / "
        全被放弃" 必须能被区分，`skipped_reason` 逐个命名（``no_unprocessed_literature`` / 
        ``pending_literature_all_leased`` /``no_claimable_literature``）。
        顺序即优先级：先判租约、再判 attempts。一条正被别人跑着的文献不该由我们来"放弃"（各有各的 `mine_attempts` 计数），否则会把别人手上的活单方面判死。
        `R3-⑩` 的计数语义：`mine_attempts` 记的是「真抽次数」（真正调用抽取器的次数），领取本身不计。于是它读起来是"抽取质量"而不是"排队长度"，而"从未真
        抽"那一档（本机没有够格的抽取器 ⇒ `run_once` 直接拒抽）在数据面上就是`mine_attempts == 0` + 
        `last_mine_error == no_llm_extractor` —— 不再需要靠`_give_up_note` 的文字去分辨。旧行里的这个数记的是"领取次数"（改
        前的口径），比真抽次数大，是上界而不是等值。
        """
        with self.store.tx("literature", actor=self.actor, note="claim") as tx:
            rows = tx.rows("literature")
            cands = sorted(
                (r for r in rows if not r.get("processed")),
                key=lambda r: (r.get("added_at") or "", r.get("lit_id") or ""),
            )
            pending = len(cands)
            skipped_lease_active = 0
            skipped_lease_backoff = 0
            gave_up = 0
            for r in cands:
                # 认租约只看租约本身是否仍在有效期内，不附加 `claimed_by` 非空这个条件
                # （`D-2`，2026-10-02 与 `agent_a/core.py` 的同族判据对齐）。修复前这里
                # 两个条件都要成立，而失败分支写下的退避租约正是 `claimed_by=None` +
                # 未来的 `lease_until` ⇒ 那条租约写了等于没写：同一趟里立刻重领，
                # `mine_attempts` 一路烧到上限并在一次调用里把这一行判死
                # （读数见 `temp/_probe_b_claim.py`：4 次连续 `run_once` 读到 0→3 当场判死）。
                # `claimed_by` 只决定这条被跳过的活记进哪个计数（别人 / 我们自己）。
                if not lease_expired(r.get("lease_until")):
                    if r.get("claimed_by"):
                        skipped_lease_active += 1  # 别人正在做
                    else:
                        skipped_lease_backoff += 1  # 我们自己上次失败留下的退避
                    continue
                n = int(r.get("mine_attempts") or 0)
                if n >= self.max_attempts:
                    r["processed"] = True
                    # 结论必须分清"真抽过失败"与"从未真抽"（见 `_give_up_note`）：
                    # 没有抽取器的机器上，到上限的是排队次数，不是抽取次数。
                    r["last_mine_error"] = _give_up_note(r, max_attempts=self.max_attempts)
                    r["claimed_by"] = None
                    r["lease_until"] = None
                    tx.upsert("literature", r, note="give_up")
                    gave_up += 1
                    continue
                r["claimed_by"] = self.actor
                r["lease_until"] = make_lease(self.lease_seconds)
                # `R3-⑩`：领取不计一次抽取尝试 —— 这一步只说明"这条活归我们了"，
                # 而 `mine_attempts` 问的是"我们真抽过几次"。+1 现在发生在真正调抽取器
                # 的那一刻（`run_once` 的成功提交与 `extract_failed` 两处）。
                #
                # 改前这里是无条件 `+= 1`，于是"这台机器没有够格的抽取器"那一档
                # （`run_once` 里 `extractor_is_fallback` 的拒抽）会把「排队次数」烧成
                # 抽取次数：领满 `max_attempts` 次就判死（`processed=True`），而那一行
                # 一次都没被真抽过 —— 与 `run_once` 那句"刻意不置 processed：接线 LLM
                # 之后这一行还要被重新领到"当场相反。判据见
                # `tests/test_r3_mine_counting.py`。
                tx.upsert("literature", r, note="claimed")
                return BClaimOutcome(
                    literature=dict(r),
                    pending=pending,
                    skipped_lease_active=skipped_lease_active,
                    skipped_lease_backoff=skipped_lease_backoff,
                    gave_up=gave_up,
                )
            if pending == 0:
                reason = "no_unprocessed_literature"
            elif skipped_lease_active == pending:
                reason = "pending_literature_all_leased"
            elif skipped_lease_backoff == pending:
                # 不能并进上面那一类：那句诊断说的是"别人持着"，
                # 而这里的活全是我们自己上次失败留下的退避（`D-2` 之后这一类才可能出现）。
                reason = "pending_literature_all_in_backoff"
            else:
                reason = "no_claimable_literature"
            return BClaimOutcome(
                pending=pending,
                skipped_lease_active=skipped_lease_active,
                skipped_lease_backoff=skipped_lease_backoff,
                gave_up=gave_up,
                skipped_reason=reason,
            )
    @staticmethod
    def _is_fallback_extractor(extractor: Any) -> bool:
        """这个抽取器是不是框架的回退（`R-56`）？
        ## 判据是声明，不是类名（`draft/28` §172 的更正）
        第一版按类名判（`type(extractor).__name__ == "RuleExtractor"`）。它有两个问题：
        1. 一个"改个名字的复制品"就能绕过它 —— 而绕过的人不需要撒谎，只需要重命名； 2. 更糟的是误伤：演示与单测明确点名要用离线基线（它们需要一个确定性抽取器），却和"
        框架偷偷回退"被同一个判据一起挡住 ⇒`demo` 与 `tests/test_demo_end_to_end.py` 当场变红（§172 的读数）。
        现在读类属性 `is_framework_fallback`：`llm.RuleExtractor` 声明 `True`（它就是回退）；
        `llm.OfflineFixtureExtractor`声明 `False`（同一个实现，但调用方点名要它）。没有这个属性的第三方抽取器一律按"调用方自己给的"处理（`getattr(..., False)`）。
        判据仍然不 import `llm`：不去拖 LLM 那一层的依赖进 B 的 import 图。
        """
        return bool(getattr(extractor, "is_framework_fallback", False))
    def _extraction_meta(self, lit: dict) -> dict:
        """构造传给抽取器的元数据。
        
        为什么要塞 `seed_concepts`：规则抽取器（以及多数 LLM 提示词）判断"这句话还提到了哪些概念"时，需要一个"已知概念"的参照集合。最自然的参照集合就是概念
        表当前的内容 —— 因为 B 的目标恰恰是把新文献接到已有概念网络上。不传它，定义句就只会产出一个概念名，关系因 `len(concept_ids) < 2` 被全部丢弃，
        表现为"抽取器什么都抽不到"，而真正的原因在调用方没给上下文。
        
        种子是提示而非权威：这里允许读无锁快照，因为种子只影响召回率，不影响正确性（概念的唯一性仍由提交事务内的锁保证）。
        
        但"读不到概念表"是另一回事，必须显式传给抽取器（`seed_concepts_error`）：读不到 ⇒ 种子退化成"只有配置里那几个" ⇒ 定义句只产出一个概念名 ⇒所
        有关系因 `len(concept_ids) < 2` 被丢弃，而症状是"文献处理完了、却一条关系都没新增"，没有任何报错。静默失败比崩溃更危险，所以这里不吞。
        """
        meta = {
            "title": lit.get("title"),
            "venue": lit.get("venue"),
            "year": lit.get("year"),
            "authors": lit.get("authors") or [],
            "lit_id": lit.get("lit_id"),
        }
        seeds: list[dict] = list(self.cfg.get("seed_concepts") or [])
        limit = int(self.cfg.get("seed_concept_limit", 300))
        seeds_error: str | None = None
        try:
            # 概念行读合成视图（并表过渡期：老表 + 新标准同号去重）——
            # 这一格是"种子概念"，读一边会让另一边的概念当不上种子（召回静默塌）。
            _cv = _CR.view(self.store, shape="legacy")
            if not _cv.get("checked"):
                # 视图把底层读失败收成三态（`checked=False` + 理由），所以这里要再抛一次：
                # 不抛的话，"读不到"就退化成了空种子，而空种子的后果正是下面注释里
                # 那条静默塌陷链。判据：`test_agent_b_seed_read_failure_is_visible_to_the_extractor`。
                raise StoreError(f"概念合成视图没读成：{_cv.get('reason')}")
            known = _cv["rows"]
        except Exception as e:  # noqa: BLE001
            # 这里不许静默吞掉。概念表读不出来时，种子会退化成"只有配置里那几个"，
            # 而本函数的 docstring 自己说了：没有种子的后果是"定义句只产出一个概念名，
            # 关系因 len(concept_ids) < 2 被全部丢弃，表现为'抽取器什么都抽不到'"。
            # 也就是说：一次读取失败会让召回率静默塌掉，而正确性判据（唯一性靠锁）
            # 照样成立 —— 症状是"文献处理完了、但一条关系都没有"，没人能看出为什么。
            # 种子的内容确实只是提示（无锁快照可以接受），但"读不到"这件事本身
            # 是一个必须被看见的事实，所以把它作为显式字段传下去，而不是吞掉。
            known = []
            seeds_error = f"{type(e).__name__}: {e}"
        for c in known[-limit:]:
            seeds.append(
                {
                    "name": c.get("name"),
                    "definition": c.get("definition") or "",
                    "aliases": list(c.get("aliases") or []),
                }
            )
        if seeds:
            meta["seed_concepts"] = seeds
        if seeds_error is not None:
            # 只在读不到时才出现这个键：它的存在本身就是一个告警信号，
            # 消费方不需要区分"None 表示没问题"还是"None 表示没查"。
            meta["seed_concepts_error"] = (
                f"概念表读不出来（{seeds_error}）⇒ 本次只用了配置里的种子，"
                "召回率会下降（**不是**'没有已有概念'）"
            )
        return meta
    @staticmethod
    def _quota_rows(rows: Sequence[Mapping[str, Any]], current_id: str) -> list[dict]:
        """配额统计用的行集合：排除正在被受理的这一条。

        `interactions.reprocess_counts` 的口径是"pending + done 都算已受理"。
        提交方（C/D）是在插入请求之前调用 `admit_reprocess_request` 的，
        那时新请求还没进表；而 B 是在"请求已经在表里"的前提下复核。
        若把这一条 pending 也算进去，同一次受理会被数两次，
        `max_reprocess_per_relation=2` 实际只允许 1 次 —— 闸门比设计更严，
        而且是静默变严。排除自身后语义回到"同一关系最多被受理 max 次"。
        """
        return [dict(r) for r in rows if str(r.get("reprocess_id") or "") != str(current_id)]
    def _reject_reprocess(self, row: dict, why: str, tx) -> None:
        """标 `rejected`（不是 done）并写清理由。

        为什么与 `done` 分开：`done` = "B 处理过了，结论是 result"；
        `rejected` = "B 判定根本不该处理它"。混成一个状态后，配额统计
        （`reprocess_counts` 只数 pending+done）会把"我拒绝过"当成"我做过了"，
        于是一个从未被处理过的关系被拒两次就再也进不来。
        """
        row["status"] = "rejected"
        row["result"] = "rejected_target"
        row["result_note"] = T.clip(why, NOTE_LIMIT)
        row["claimed_by"] = None
        row["lease_until"] = None
        tx.upsert("reprocess_requests", row, note="reprocess_rejected")
    def _claim_reprocess(self) -> tuple[dict | None, list[dict]]:
        """认领一条 pending 的重抽取请求（与 literature 同样的租约模式）。
        
        准入的四条判据在这里一次做完（顺序即优先级）：
        
        1. 尝试次数 —— 超限就放弃（标 rejected，而不是永远挂着）； 2. 目标非空 —— 无目标的重抽取会退化成全量重抽（I4 明写的幂等陷阱）； 3. 目标存在
        —— 关系可能已被删除、或已被 I5 合并（此时候选应转到 survivor）； 4. 配额（`interactions.admit_reprocess_request`）
        —— 同一关系最多被受理`DEFAULTS["max_reprocess_per_relation"]` 次，被拒的不计入。
        
        为什么在"认领"这一步做完而不是在收尾时做：被拒的请求根本不该进入重活阶段（读全文、重新抽取可能几十秒）。四条判据用的都是同一个事务里读到的行，因此不存在"A 看到还有额度、
        B 看到没有了"的窗口。
        """
        rejected: list[dict] = []
        with self.store.tx("reprocess_requests", "relations", actor=self.actor, note="reprocess_claim") as tx:
            rows = tx.rows("reprocess_requests")
            known_relations = {str(r.get("relation_id")) for r in tx.rows("relations")}
            cands = sorted(
                (r for r in rows if str(r.get("status") or "") == "pending"),
                key=lambda r: (r.get("timestamp") or "", r.get("reprocess_id") or ""),
            )
            for row in cands:
                # 同 D-2：租约仍在走就不可领，不附加 `claimed_by` 非空 ——
                # 失败释放后的那条行写的是 `claimed_by=None` + 未来的租约（见
                # `_record_reprocess_failure`），旧写法会把它当成没人管而当场重领。
                if not lease_expired(row.get("lease_until")):
                    continue  # 租约仍在走（别人持着，或我们自己上次失败留下的退避）
                rid = str(row.get("reprocess_id") or "")
                n = int(row.get("attempts") or 0)
                if n >= self.max_attempts:
                    self._reject_reprocess(
                        row,
                        f"超过最大处理尝试次数 {self.max_attempts}，已放弃。"
                        f"上一次错误：{row.get('last_error')}（失败是环境问题，不是结论，所以标 rejected 而不是 done）",
                        tx,
                    )
                    rejected.append({"reprocess_id": rid, "reason": row["result_note"]})
                    continue
                targets = [str(x) for x in (row.get("relation_ids") or []) if x]
                if not targets:
                    self._reject_reprocess(
                        row, "目标关系为空 ⇒ **无目标的重抽取会退化成全量重抽**，拒绝", tx
                    )
                    rejected.append({"reprocess_id": rid, "reason": row["result_note"]})
                    continue
                missing = [t for t in targets if t not in known_relations]
                if missing:
                    self._reject_reprocess(
                        row,
                        f"目标关系不存在：{'、'.join(missing)}（可能已被删除或被 I5 合并到 survivor 上）"
                        "⇒ 不做任何猜测性重抽",
                        tx,
                    )
                    rejected.append({"reprocess_id": rid, "reason": row["result_note"]})
                    continue
                reason = str(row.get("reason") or "")
                if reason == "structural_duplicate":
                    # I5 的合并决定需要"C 的候选"（概念对 + 名字证据 + 邻域），
                    # 仅凭 relation_ids 无法判定两个概念是否同义。猜一个合并就是绕过
                    # "两路独立证据"这条规则，所以拒绝，并把请求交回候选路径。
                    self._reject_reprocess(
                        row,
                        "reason=structural_duplicate 无法用 relation_ids 判定：合并必须走 "
                        "decide_structural_duplicate(candidate)（候选里有概念对与名字证据）"
                        "⇒ 拒绝，不做猜测性合并",
                        tx,
                    )
                    rejected.append({"reprocess_id": rid, "reason": row["result_note"]})
                    continue
                adm = I.admit_reprocess_request(
                    self._quota_rows(rows, rid), relation_ids=targets, reason=reason
                )
                if not adm.get("admitted"):
                    self._reject_reprocess(row, f"准入闸门拒绝：{adm.get('reason')}", tx)
                    rejected.append({"reprocess_id": rid, "reason": row["result_note"]})
                    continue
                row["claimed_by"] = self.actor
                row["lease_until"] = make_lease(self.lease_seconds)
                row["attempts"] = n + 1
                tx.upsert("reprocess_requests", row, note="reprocess_claimed")
                return dict(row), rejected
        return None, rejected
    def _load_doc_for(self, lit: Mapping[str, Any] | None) -> tuple[Any, str]:
        """重新打开目标文献，返回 `(doc, 不可用原因)`；原因非空时 doc 为 `None`。

        为什么把"原因"作为返回值而不是抛异常：I4 的每一次"没做到"都必须落成
        一行可读的证据（`result_note`）。抛异常会把它变成一次失败重试，最后变成
        `rejected` —— 看起来像 B 做错了事，而事实是"这份文献本来就无法逐字定位"
        （扫描件、没下载到 PDF）。静默失败比崩溃更危险，所以这里要的是"说出来"。
        """
        if lit is None:
            return None, "文献不在文献表里（关系指向了一个不存在的 lit_id）"
        lid = str(lit.get("lit_id") or "")
        try:
            path = self.store.library_path(lit.get("path"))
        except Exception as e:
            return None, f"文献路径非法：{e}"
        if path is None:
            return None, f"文献 {lid} 没有本地文件（path=null，通常是没有下载到 PDF）"
        if not path.exists():
            return None, f"文献 {lid} 的本地文件不存在：{path.name}"
        try:
            doc = self.extract_text(path)
        except Exception as e:
            return None, f"文献 {lid} 重新抽取失败：{type(e).__name__}: {e}"
        if not list(getattr(doc, "pages", None) or []):
            # `R2b-⑫`：这里此前是「直接放弃」，理由写作"无文本层（扫描版？）"——
            # 而"扫描版"恰恰是 `ocr.*` 这三件工具存在的理由。文档一直在教 B 用
            # `ocr.detect_text_layer` / `ocr.backends` / `ocr.run`（`docs/READING-MAP.md`
            # §0.1 记的"生产面 0 次"欠账），生产代码却从不调用它们 ⇒ 689 份里那唯一
            # 一份扫描件在报告里长得像"这份文献本来就无法逐字定位"，而事实是
            # "我们没试过 OCR"。静默失败比崩溃更危险，这里补上试过的那一步。
            return self._ocr_retry(path, lid)
        return doc, ""

    # ---------------------------------------------------------------- `R2b-⑫`
    def _ocr_call(self, name: str, **params: Any) -> tuple[dict[str, Any], str]:
        """经「工具面」调一件 `ocr.*`，返回 `(payload, 不可用原因)`；原因非空 ⇒ payload 空。

        为什么不直接 import handler：`ocr.*` 的"谁调得到"与参数校验都在
        `tools/base.py` 的注册表里。绕过它去调 handler，会让"这一支到底有没有权限"
        变成没人值守的假设 —— 而权限面被静默放宽正是本仓库反复登记的那类洞。
        """
        try:
            if self._ocr_surface is not None:
                # 夹具注入口：单测用假工具面，既不起真 OCR 也不碰真注册表。
                res = self._ocr_surface(name, params)
            else:
                if self._ocr_registry is None:
                    from ..tools import build_registry

                    # 角色取字面量 `"B"` 而不是 `self.actor`：调用期判据比的是角色名
                    # （`role or bound_role`），而 `actor` 是审计用的名字（`agent-B`），
                    # 拿它去比会得到一次 fail-closed 的拒绝 —— 那会被下面的 `except`
                    # 折成一句"调用失败"，看起来像工具坏了。
                    self._ocr_registry = build_registry(store=self.store).registry
                res = self._ocr_registry.call(name, role="B", **params)
        except Exception as e:  # noqa: BLE001
            # 调不动也必须是"说出来的读数"：抛出去会让 I4 的一次"没做到"变成一次
            # 失败重试（与 `_load_doc_for` 的口径相反）。
            return {}, f"{name} 调用失败（{type(e).__name__}: {e}）"
        if getattr(res, "ok", False):
            data = getattr(res, "data", None)
            return (dict(data) if isinstance(data, Mapping) else {}), ""
        why = getattr(res, "error", None) or "工具面没给原因（`ok=False` 且 `error` 为空）"
        return {}, f"{name} 报告失败：{why}"

    def _ocr_doc(self, got: Mapping[str, Any]) -> Any:
        """把 `ocr.run` 的逐页文本包成与 `extract_text` 同型的文档对象。
        
        为什么要包成 `DocumentText` 而不是自造一个：下游（`_candidate_passages` /`text_at` / 引文回验）读的是 `pages` 与
        `text_at` 这一对契约，同型才不会让"OCR 来的文本"在下游变成另一种东西。
        
        页号按 OCR 自己报的 `page`（1-based）落位，不按列表下标：`ocr.run` 有`max_pages` 截断与逐页失败，下标当页号会把"第 5 页的内容"
        写成第 1 页 ——那是逐字引文回验里最难查的一种错（页码错、字面全对）。
        
        `source_kind` 仍记 `"pdf"`：来源确实是 PDF（只是文本来自栅格化后识别）。`DocumentText` 的字段注释把取值定死在 
        `pdf | txt | md | html`，而那个文件在禁改区里 —— 自造第五个取值会悄悄改掉一个受控词表，所以 OCR 这件事记在`ocr_readings` 里，
        不塞进 `source_kind`。
        """
        from ..extract import DocumentText

        items = [i for i in (got.get("pages") or []) if isinstance(i, Mapping)]
        top = max((int(i.get("page") or 0) for i in items), default=len(items))
        pages = [""] * top
        for item in items:
            idx = int(item.get("page") or 0)
            if 1 <= idx <= top:
                pages[idx - 1] = str(item.get("text") or "")
        return DocumentText(text="\n".join(pages), pages=pages, source_kind="pdf", encoding=None)

    def _ocr_retry(self, path: Any, lid: str) -> tuple[Any, str]:
        """无文本层时的 OCR 回退：返回 `(doc, 不可用原因)`，两者互斥。

        三态（不把"没查"折成"查过了没问题"）：
        - 后端可用且识别出字符 ⇒ 返回 OCR 文本，读数记 `via=ocr`；
        - 本机没有可用后端 ⇒ 原因是 `unavailable`，不是"无文本层"，也不是静默放弃；
        - 后端真实执行过但产出为空 ⇒ 明说"试了还是没有"（`ran_empty`）。

        为什么先问 `detect_text_layer` 再问 `backends`：探测器读的是文件本身，
        与抽取器是两条独立的读法。它若说"有文本层"，那么"`extract_text` 抽不出字"
        的原因在别处（例如逐页异常），此时 OCR 是错的药 —— 这一支只如实报矛盾。
        """
        det, why = self._ocr_call("ocr.detect_text_layer", path=str(path))
        if why:
            self._ocr_readings(lid, checked=False, via="detect", reason=why)
            return None, f"文献 {lid} 无文本层；{why} ⇒ 没做成 OCR"
        if det.get("has_text_layer"):
            reason = (f"文献 {lid}：抽取器读到 pages=[]，但 ocr.detect_text_layer 读出 "
                      f"has_text_layer=True（pages={det.get('pages')}，chars={det.get('chars')}）"
                      "—— 两条读法互相矛盾，此时做 OCR 是错的药 ⇒ 不擅自 OCR，交人工看")
            self._ocr_readings(lid, checked=True, via="detect", reason=reason)
            return None, reason
        bk, why_bk = self._ocr_call("ocr.backends", refresh=False)
        if why_bk:
            self._ocr_readings(lid, checked=False, via="backends", reason=why_bk)
            return None, f"文献 {lid} 无文本层；{why_bk} ⇒ 没做成 OCR"
        if not bk.get("any_ocr_backend_available"):
            reason = (f"文献 {lid} 无文本层，且本机没有可用的 OCR 后端（unavailable）"
                      f"⇒ 无从逐字定位。先装后端再谈：{str(bk.get('verdict') or '')[:200]}")
            self._ocr_readings(lid, checked=True, via="backends", reason=reason, payload=bk)
            return None, reason
        got, why_run = self._ocr_call("ocr.run", path=str(path))
        if why_run:
            self._ocr_readings(lid, checked=True, via="run", reason=why_run)
            return None, f"文献 {lid} 无文本层；试过 OCR 但没做成：{why_run}"
        doc = self._ocr_doc(got)
        if not list(doc.pages) or not any(p.strip() for p in doc.pages):
            reason = (f"文献 {lid} 无文本层，试过 OCR（backend={got.get('backend')}）"
                      f"但产出为空（ran_empty）：{str(got.get('note') or '')[:160]}"
                      "⇒ 无从逐字定位")
            self._ocr_readings(lid, checked=True, via="run", reason=reason, payload=got)
            return None, reason
        self._ocr_readings(lid, checked=True, via="ocr", reason="", payload=got)
        return doc, ""

    def _ocr_readings(self, lid: str, *, checked: bool, via: str, reason: str,
                      payload: Mapping[str, Any] | None = None) -> None:
        """记一条 OCR 读数。`checked` 是"试没试"，不是"成没成"。"""
        item: dict[str, Any] = {"lit_id": lid, "checked": checked, "via": via, "reason": reason}
        if payload is not None:
            item["reading"] = {
                k: payload.get(k)
                for k in ("backend", "has_text_layer", "total_chars", "pages_processed",
                          "pages_failed", "truncated_pages", "any_ocr_backend_available")
                if k in payload
            }
        self.ocr_readings.append(item)
    def _candidate_passages(self, doc, pr, *, fulltext: bool) -> list[tuple[int, str]]:
        """候选片段 `(页号, 片段)`。先看声明页附近，需要时再看全文。"""
        pages = list(getattr(doc, "pages", None) or [])
        if not pages:
            return []
        if fulltext or pr is None or not getattr(pr, "known", False):
            rng = list(range(1, len(pages) + 1))
        else:
            lo = max(1, int(pr.start) - self.reprocess_context_pages)
            hi = min(len(pages), int(pr.end) + self.reprocess_context_pages)
            rng = list(range(lo, hi + 1))
        out: list[tuple[int, str]] = []
        for p in rng:
            for seg in _passages(pages[p - 1]):
                out.append((p, seg))
        return out
    def _context_passage(self, doc, pr) -> tuple[str, str]:
        """`need_context` 用的原文片段（只读）：返回 `(取自哪里, 片段)`。

        优先用 `extract.py` 已经提供的 `DocumentText.text_at`（1-based 闭区间）：
        B 不该自己再拼一遍页码语义 —— 拼错了会给出错误页的"上下文"，
        而 D 会把它当成 L3 溯源的证据（那正是最不该出错的地方）。
        """
        pages = list(getattr(doc, "pages", None) or [])
        if pr is not None and getattr(pr, "known", False):
            lo = max(1, int(pr.start) - self.reprocess_context_pages)
            hi = min(len(pages), int(pr.end) + self.reprocess_context_pages)
            where = f"声明页码 {pr.label or f'{pr.start}-{pr.end}'}（实际取第 {lo}-{hi} 页）"
        else:
            lo, hi = 1, len(pages)
            where = f"页码未知（实际取全文第 {lo}-{hi} 页）"
        at = getattr(doc, "text_at", None)
        text = at(lo, hi) if callable(at) else "\n".join(pages[lo - 1 : hi])
        return where, text
    def _find_equivalent_quote(self, doc, rel: Mapping[str, Any], pr) -> tuple[str, str, dict | None]:
        """`quote_unverifiable`：回原文找该陈述的等价表述，并重跑既有回验。

        两道闸门，缺一不可：

        1. 相似度闸门 —— 候选片段必须与关系的 `statement`/`description` 足够像
           （token Jaccard ≥ `reprocess_min_similarity`）。低于阈值就报 `not_found`：
           宁可不改，也不把"随便一句像的话"塞进 `quote`。
        2. 既有回验闸门 —— 选中的片段必须再走一遍 `check_quote`（复用
           quoteverify 的同一份实现，不另写判据）。它是原页的连续切片，正常必然通过；
           若不通过，就说明"看着像"并不等于"逐字在原文里"，此时不算找到。
        """
        statement = str(rel.get("statement") or rel.get("description") or "") or str(rel.get("quote") or "")
        if not statement.strip():
            return "not_found", "关系既无 statement 也无 description，无法判断何为'等价表述'，未改动", None
        best_score, best = 0.0, None
        scope_text = ""
        for scope_text, fulltext in (("声明页附近", False), ("全文", True)):
            for page, seg in self._candidate_passages(doc, pr, fulltext=fulltext):
                score = T.similarity(seg, statement)
                if score > best_score:
                    best_score, best = score, (page, seg)
            if best is not None and best_score >= self.reprocess_min_similarity:
                break
        if best is None or best_score < self.reprocess_min_similarity:
            return (
                "not_found",
                f"在{scope_text or '原文'}的候选片段里，与陈述最相似的片段相似度仅 {best_score:.2f}"
                f"（阈值 {self.reprocess_min_similarity:.2f}）⇒ 不认定存在等价表述，**未改动引文**",
                None,
            )
        page, seg = best
        chk = check_quote(
            doc,
            seg,
            S.PageRange(page, page, f"p. {page}"),
            widen=self.widen_pages,
            allow_fulltext_fallback=self.allow_fulltext_fallback,
        )
        if chk.verified is not True:
            return (
                "not_found",
                f"找到候选片段（第 {page} 页，相似度 {best_score:.2f}），但**既有的引文回验**未通过"
                f"（{chk.reason}）⇒ 不写入：'看起来像'不等于'逐字在原文里'",
                None,
            )
        return (
            "found",
            f"在第 {page} 页找到与陈述相似度 {best_score:.2f} 的等价表述，已更新 "
            f"quote/quote_normalized/page_range，并通过既有引文回验（{chk.reason}；窗口 {chk.window}）",
            {
                "quote": seg,
                "quote_normalized": T.normalize_for_quote(seg),
                "page_range": S.PageRange(page, page, f"p. {page}").to_dict(),
                "quote_verified": True,
                # 这一档走的是 `quoteverify.check_quote`（逐字）⇒ 方式写实（R95）
                "quote_mode": "verbatim",
                # D1（2026-10-22）：说"逐字通过"就必须留下核了哪一段、在第几页。
                # 这里拿的就是判它的那一份文档与那一页，所以区间当场能算出来；
                # 算不出来就给空串（宁可没有，也不编一个页码 —— 区间只有一个产出点：
                # `quoteevidence.locate_span`）。
                "quote_span": _QE.locate_span(doc, seg, page=page),
                "_quote_check": chk.to_dict(),
            },
        )
    def _expand_statement(self, doc, rel: Mapping[str, Any], pr) -> tuple[str, str, dict | None]:
        """`low_information`：回到文献该页附近，把陈述换成包含它的更长片段。

        判据是"字面锚点 + 严格更长"，不用相似度：这里是扩展而不是检索，
        扩展的合法性来自"新片段确实包含旧陈述"—— 那是一个可逐字核实的事实。
        找不到锚点就报 `unchanged`：不臆造一个"更完整的陈述"
        （那正是"把没做到写成做成了"的经典形态）。
        """
        cur = str(rel.get("statement") or rel.get("description") or "")
        anchor = cur.strip() or str(rel.get("quote") or "").strip()
        if not anchor:
            return "unchanged", "关系没有 statement/description/quote 可作锚点，无法定位到原文段落，未改动", None
        na = T.normalize_for_quote(anchor)
        best: tuple[int, str] | None = None
        for page, seg in self._candidate_passages(doc, pr, fulltext=True):
            if na and na in T.normalize_for_quote(seg):
                if best is None or len(seg) > len(best[1]):
                    best = (page, seg)
        if best is None:
            return (
                "unchanged",
                f"在文献原文里找不到当前陈述的字面锚点（{T.clip(anchor, 80)!r}）"
                "⇒ 不臆造'更完整的陈述'，未改动",
                None,
            )
        page, seg = best
        if len(seg.strip()) <= len(cur.strip()):
            return (
                "unchanged",
                f"第 {page} 页所在片段并不比当前陈述更完整（{len(seg.strip())} ≤ {len(cur.strip())} 字符），未改动",
                None,
            )
        return (
            "improved",
            f"在第 {page} 页找到包含当前陈述的更长片段（{len(cur.strip())} → {len(seg.strip())} 字符），"
            "已更新 statement/description",
            {"statement": seg, "description": seg},
        )
    def _perform_reprocess(self, req: Mapping[str, Any]) -> dict:
        """重活（回原文重新定位/抽取）—— 在事务外做。

        为什么不放在事务里：抽取一篇 PDF 可能几秒到几十秒，而事务要持有
        relations / reprocess_requests 的锁；把重活放进去等于推翻 store 的"锁内短"
        （见 store.py 的模块 docstring）。代价是必须在收尾时再核对一次
        "A 阶段读到的那一行有没有被别人改过" —— 见 `_finish_reprocess`。

        返回的 `result` 一定是 :data:`REPROCESS_RESULTS` 里的词；
        "做不到"必须显式落成 `not_found` / `unchanged` + 理由。
        """
        reason = str(req.get("reason") or "")
        targets = [str(x) for x in (req.get("relation_ids") or []) if x]
        rel_index = {str(r.get("relation_id")): r for r in self.store.rows("relations")}
        lit_index = {str(l.get("lit_id")): l for l in self.store.rows("literature")}

        docs: dict[str, tuple[Any, str]] = {}

        def doc_for(lit_id: str) -> tuple[Any, str]:
            # 同一篇文献在一次请求里只抽一次（一次请求可以针对多条关系）。
            if lit_id not in docs:
                docs[lit_id] = self._load_doc_for(lit_index.get(lit_id))
            return docs[lit_id]

        lines: list[str] = []
        words: list[str] = []
        updates: dict[str, dict] = {}
        fingerprints: dict[str, dict] = {}
        for rid in targets:
            rel = rel_index.get(rid)
            if rel is None:
                words.append("not_found")
                lines.append(f"[{rid}] not_found：目标关系已不存在（可能刚被删除或被 I5 合并），未改动任何数据")
                continue
            lit_id = str(rel.get("lit_id") or "")
            doc, why = doc_for(lit_id)
            if doc is None:
                # "无法真正重抽"的唯一合法表达：结果 + 明确的原因。
                word = "unchanged" if reason == "low_information" else "not_found"
                words.append(word)
                lines.append(f"[{rid}] {word}：无法真正重抽 —— {why}；关系保持原样（不假装成功）")
                continue
            pr = S.PageRange.from_dict(rel.get("page_range"))
            if reason == "need_context":
                where, passage = self._context_passage(doc, pr)
                words.append("found")
                lines.append(
                    f"[{rid}] found：{where}原文片段（逐字，供 D 做 L3 溯源；**只读**，未改动关系）：\n{passage}"
                )
                continue
            if reason == "quote_unverifiable":
                word, note, upd = self._find_equivalent_quote(doc, rel, pr)
            else:  # low_information（其余取值已在认领阶段被拒）
                word, note, upd = self._expand_statement(doc, rel, pr)
            words.append(word)
            lines.append(f"[{rid}] {note}")
            if upd:
                updates[rid] = upd
                fingerprints[rid] = {
                    "quote": rel.get("quote"),
                    "statement": rel.get("statement"),
                    "description": rel.get("description"),
                }
        if reason in ("need_context", "quote_unverifiable"):
            result = "found" if "found" in words else "not_found"
        else:
            result = "improved" if "improved" in words else "unchanged"
        return {
            "result": result,
            "note": f"reason={reason}；目标 {len(targets)} 条\n" + "\n".join(lines),
            "touched": sorted(updates),
            "updates": updates,
            "fingerprints": fingerprints,
        }
    def _record_reprocess_failure(self, req: Mapping[str, Any], error: str) -> None:
        """处理失败：记 `last_error` 并写下退避租约，状态仍为 `pending`。

        为什么不标 `done` + `result="not_found"`：`not_found` 的含义是
        "我看过了，原文里没有" —— 那是一个结论；这里发生的是"我压根没看成"。
        把后者写成前者，正是 DESIGN-INTERACTIONS.md §3.4 点名禁止的形态。

        为什么写的是退避租约而不是把 `lease_until` 清空（`D-2`，2026-10-02）：
        清空等于"没人持着、可以立刻再领"，于是失败会当轮重来 —— 而这一条重试的
        合理间隔是租约长度。清空之后 `claimed_by is None` + 无租约的行在任何判据下
        都是"可领"，`attempts` 会在同一趟里烧到上限。
        """
        with self.store.tx("reprocess_requests", actor=self.actor, note="reprocess_failed") as tx:
            row = tx.find("reprocess_requests", reprocess_id=req.get("reprocess_id")) or dict(req)
            row["last_error"] = T.clip(error, 500)
            row["claimed_by"] = None
            row["lease_until"] = make_lease(self.lease_seconds)
            tx.upsert("reprocess_requests", row, note="reprocess_failed")
    def _finish_reprocess(self, req: Mapping[str, Any], outcome: Mapping[str, Any]) -> dict:
        """收尾（短事务）：写入目标关系的新字段 + 请求的终局结果。

        这里刻意不声明 `literature` 表：重抽取是"重新看已有的"，不是
        "当作没看过"。把 `processed` 置回 `False` 会触发全量重抽（I4 的幂等陷阱），
        而不声明该表 = 结构上不可能犯这个错（提交只会写 `t._dirty` 里的表）。

        目标行在写入前会核对指纹：A 阶段（锁外）读到的 quote/statement/description
        若已被别人改过，就放弃写入并如实记下来 —— 宁可少改一次，也不要覆盖另一个
        B 实例刚写下的结果（那会是一次静默的丢失更新，store 的模块 docstring
        说的正是这件事）。
        """
        result_word = str(outcome.get("result") or "")
        if result_word not in REPROCESS_RESULTS:
            # 程序错误就该炸：写一个词表外的 result 会让下游统计静默失准。
            raise ValueError(f"I4 的结果必须是 {REPROCESS_RESULTS} 之一，收到 {result_word!r}")
        touched: list[str] = []
        stale: list[str] = []
        with self.store.tx("relations", "reprocess_requests", actor=self.actor, note="reprocess") as tx:
            live = {str(r.get("relation_id")): r for r in tx.rows("relations")}
            for rid, upd in (outcome.get("updates") or {}).items():
                row = live.get(str(rid))
                if row is None:
                    stale.append(f"{rid}（已不存在）")
                    continue
                fp = (outcome.get("fingerprints") or {}).get(rid) or {}
                if any(row.get(k) != v for k, v in fp.items()):
                    stale.append(f"{rid}（处理期间被改动）")
                    continue
                upd = dict(upd)
                if "quote" in upd:
                    # dedup_key 是"概念组 + 引文哈希"的派生字段：改了 quote 必须重算，
                    # 否则索引键与内容漂移，后续判重会按旧键比较（静默失效）。
                    upd["dedup_key"] = D.relation_dedup_key(
                        str(row.get("concept_group_key") or ""), str(upd["quote"])
                    )
                upd["_reprocess"] = {
                    "reason": req.get("reason"),
                    "reprocess_id": req.get("reprocess_id"),
                    "result": result_word,
                    "at": S.now_iso(),
                }
                row.update(upd)
                tx.upsert("relations", row, note=f"reprocess:{req.get('reason')}")
                touched.append(str(rid))
            note = str(outcome.get("note") or "")
            if stale:
                note += f"\n未写入（目标已变，避免覆盖别人的写入）：{'、'.join(stale)}"
            row = tx.find("reprocess_requests", reprocess_id=req.get("reprocess_id")) or dict(req)
            row["status"] = "done"
            row["result"] = result_word
            row["result_note"] = T.clip(note, NOTE_LIMIT)
            row["touched_relation_ids"] = sorted(touched)
            row["claimed_by"] = None
            row["lease_until"] = None
            row["last_error"] = None
            tx.upsert("reprocess_requests", row, note=f"reprocess_done:{result_word}")
        return {
            "handled": True,
            "reprocess_id": str(req.get("reprocess_id") or ""),
            "result": result_word,
            "touched_relation_ids": sorted(touched),
            "stale_targets": stale,
            "note": row["result_note"],
        }
    @staticmethod
    def _id_order(cid: str) -> int:
        """`concept_id` 的可比较次序。非法 ID 排到最后 —— 它不该在 tie-break 里胜出。"""
        return int(cid) if str(cid).isdigit() else 10**9
    @staticmethod
    def _dedup_match(
        rows: Sequence[Mapping[str, Any]],
        *,
        exclude_id: str,
        name: str,
        aliases: Sequence[str],
    ) -> dict | None:
        """在去掉某一行的概念表上跑一次 `dedup.find_concept`（同一套规范化）。

        为什么要去掉自己：`find_concept` 会把行自己的名字算进候选，于是"查自己"
        必然命中自己 —— 复核就退化成恒真。去掉自己之后，"A 的名字解析到 B"
        才真的是"判重索引认为 A 与 B 是同一个概念"。
        """
        rest = [r for r in rows if str(r.get("concept_id")) != str(exclude_id)]
        return D.find_concept(rest, name, list(aliases or []))
    def _apply_merge(self, tx, decision: Mapping[str, Any]) -> dict:
        """在给定事务内执行合并（调用方已完成复核）。见 :meth:`resolve_structural_duplicate`。"""
        survivor_id = str(decision["survivor_id"])
        merged_id = str(decision["merged_id"])
        rel_rows = tx.rows("relations")

        def contains_merged(r: Mapping[str, Any]) -> bool:
            return merged_id in {str(x) for x in (r.get("concept_ids") or [])}

        rewritten: list[str] = []
        rejected: list[str] = []
        skipped: list[str] = []
        # 未被改写的行随时可作判重的对照集（按 relation_id 升序改写，保证结论稳定）
        untouched = [dict(r) for r in rel_rows if not contains_merged(r)]
        accepted: list[dict] = []
        for r in sorted((r for r in rel_rows if contains_merged(r)), key=lambda r: str(r.get("relation_id"))):
            rid = str(r.get("relation_id"))
            new_cids = S.sorted_unique(
                [survivor_id if str(c) == merged_id else str(c) for c in (r.get("concept_ids") or [])]
            )
            if len(new_cids) < 2:
                # 防御分支：候选要求"两者之间无直接关系"（decide 里已复算过），
                # 正常不可达。真到了这里就只标记不改写，绝不静默丢行。
                row = dict(r)
                row["_merge_note"] = (
                    f"I5 合并**未改写**本行：概念组改写后会塌缩成 {new_cids!r}（少于 2 个概念），"
                    "交人工/下一轮处理"
                )
                tx.upsert("relations", row, note="structural_merge_skipped")
                skipped.append(rid)
                continue
            new_key = T.concept_group_key(new_cids)
            d = D.decide_relation(
                untouched + accepted,
                concept_group_key=new_key,
                quote=str(r.get("quote") or ""),
                description=str(r.get("description") or ""),
                dup_strong=self.dup_strong,
                dup_review=self.dup_review,
            )
            row = dict(r)
            row["concept_ids"] = new_cids
            row["concept_group_key"] = new_key
            row["dedup_key"] = D.relation_dedup_key(new_key, str(r.get("quote") or ""))
            if d.kind == "duplicate":
                row["status"] = "rejected"
                row["duplicate_of"] = d.existing_id
                row["_merge_note"] = (
                    f"I5 合并改写后与 {d.existing_id} 同概念组且引文重复（分数 {d.score:.3f}）"
                    "⇒ 交既有判重逻辑处理：本行标 rejected 并保留为证据，指向幸存关系"
                )
                rejected.append(rid)
            elif d.kind == "suspect":
                row["status"] = "suspect"
                row["duplicate_of"] = d.existing_id
                row["_merge_note"] = (
                    f"I5 合并改写后与 {d.existing_id} 高度相似（{d.score:.3f}）⇒ 按既有判重降级为 suspect"
                )
                accepted.append(row)
                rewritten.append(rid)
            else:
                row["_merge_note"] = f"I5 合并改写：概念 {merged_id} → {survivor_id}（关系内容未改动）"
                accepted.append(row)
                rewritten.append(rid)
            tx.upsert("relations", row, note=f"structural_merge:{merged_id}->{survivor_id}")

        # ---- 受影响概念的 related_concepts 整体重算（派生而非增量，漏更新会自愈）
        #
        # 这一格是老表专有的（新标准里"哪些概念相关"由 `relations` 表本身回答，
        # 读侧现算）⇒ 落刀之后整段不跑，否则每一笔合并都会把派生结果又抄一份回
        # 老字段名上（写出来的值与原值等价，但那是"并干净"没做完的形态）。
        final_rels = tx.rows("relations")
        changed = set(rewritten) | set(rejected)
        affected = {survivor_id, merged_id}
        for r in final_rels:
            if str(r.get("relation_id")) in changed:
                affected.update(str(x) for x in (r.get("concept_ids") or []))
        for cid in sorted(affected) if _CR.legacy_present(self.store).get("present") else []:
            row = next((c for c in _CR.view_tx(tx, shape="legacy")["rows"]
                        if str(c.get("concept_id")) == cid), None)
            if row is None:
                continue
            want = D.derive_related_concepts(cid, final_rels, include_suspect=True)
            if row.get("related_concepts") != want:
                row["related_concepts"] = want
                row["updated_at"] = S.now_iso()
                _CR.upsert_legacy_shaped(tx, row, actor=self.actor,
                                         note="related_recomputed")

        # ---- 概念行：survivor 收别名（含被合并方的名字），被合并方立墓碑
        # 读与写都走过渡层：`tx.rows("concepts")` 在落刀之后是受控错，
        # 而"写老表那份 + 同步新标准"两件事合成 `upsert_legacy_shaped` 一处。
        live_concepts = _CR.view_tx(tx, shape="legacy")["rows"]
        survivor = next(c for c in live_concepts if str(c.get("concept_id")) == survivor_id)
        merged = next(c for c in live_concepts if str(c.get("concept_id")) == merged_id)
        own = survivor.get("normalized_name") or T.normalize(str(survivor.get("name") or ""))
        aliases = S.sorted_unique(
            list(survivor.get("aliases") or []) + [str(merged.get("name") or "")] + list(merged.get("aliases") or [])
        )
        aliases = [x for x in aliases if x and T.normalize(x) != own]
        if aliases != (survivor.get("aliases") or []):
            survivor["aliases"] = aliases
        survivor["updated_at"] = S.now_iso()
        _CR.upsert_legacy_shaped(tx, survivor, actor=self.actor, note="alias_merge")

        reason = str(decision.get("reason") or "")
        reason += (
            f"；关系改写：{len(rewritten)} 条改指 {survivor_id}"
            + (
                f"，其中 {len(rejected)} 条改写后与既有关系同组同引文 ⇒ 按既有判重逻辑标 "
                "rejected（保留为证据，未删除）"
                if rejected
                else ""
            )
            + (f"；{len(skipped)} 条因概念组塌缩**未改写**，待人工/下一轮处理" if skipped else "")
        )
        merged["merged_into"] = survivor_id
        merged["merge_reason"] = reason
        merged["merged_at"] = S.now_iso()
        merged["_merge"] = {
            "survivor_id": survivor_id,
            "rewritten_relation_ids": sorted(rewritten),
            "rejected_relation_ids": sorted(rejected),
            "skipped_relation_ids": sorted(skipped),
            "evidence": dict(decision.get("evidence") or {}),
        }
        # 墓碑（`merged_into`）在新标准里映射成 `superseded` + 理由（`sync_from_legacy` 里那一支）：
        # 不映射的话，一次真的合并在新标准那一边完全看不见，下游会继续把被合并的那条当可用命题。
        # 老表还在时也要写那一份（`upsert_legacy_shaped` 一处办两件事）。
        _CR.upsert_legacy_shaped(tx, merged, actor=self.actor, note="merged")
        return {
            "applied": True,
            "survivor_id": survivor_id,
            "merged_id": merged_id,
            "merge_reason": reason,
            "rewritten_relation_ids": sorted(rewritten),
            "rejected_relation_ids": sorted(rejected),
            "skipped_relation_ids": sorted(skipped),
        }


class AgentB(_RunOnce, _ReprocessOnce, _RunReprocess, _DecideStructuralDuplicate, _ResolveStructuralDuplicate, _RegisterStatement, _Run, _ProofResearch, _Core):
    """文献整理智能体。extractor / extract_text 由外部注入，便于离线测试。"""



def _selftest() -> int:
    """`python -m agentflow.agent_b` 的自检：跑通主路径并断言关键不变量。
    ## 为什么这个函数必须存在（它修的是一个静默空成功）
    `scripts/release_check.py` 第 2 项会逐个 `python -m agentflow.agent_<role>` 并看退出码。在本次修复之前，
    `agent_b` 没有 `__main__` 块，于是那条命令输出 0 行、退出码 0—— 旧判据会把它记成"自检通过"，而它其实什么都没检查。这正是本项目最忌讳的形态：
    "没做"被读成"通过"（`DEVELOPMENT.md` §10-D5 / 附录 C 第 4 条；`release_check.item_selftests` 现在专门用 
    `has_selftest` 把这种情况报成 `unknown`）。
    自检只覆盖离线、确定性的路径：概念复用与别名合并、引文回验失败的降级（suspect 而不是丢弃）、`processed` 的语义（抽取失败不置）、I6 闸门的三态计数、结
    构重复的保守否决、以及取文献侧的三态（队列空 / 全被别人占着 / 全被放弃）。
    退出码：`0` = 全部通过；`1` = 有失败项。
    """
    import shutil
    import tempfile
    from pathlib import Path

    checks: list[tuple[str, bool]] = []

    def check(label: str, cond: bool, extra: str = "") -> None:
        checks.append((label, bool(cond)))
        print(f"    [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    class _Concept:
        def __init__(self, name, definition="", aliases=()):
            self.name, self.definition, self.aliases = name, definition, list(aliases)

    class _Relation:
        def __init__(self, concept_names, quote, description="", page_range=None):
            self.concept_names, self.quote = list(concept_names), quote
            self.description = description or quote
            # 引文回验只有在声明了页码（或显式开启 fulltext 兜底）时才会去扫原文；
            # 默认给已知页码，好让"逐字核实通过"这条主路径真的被走到。
            self.page_range = page_range or S.PageRange(1, 1, "p. 1")

    class _Extractor:
        """确定性抽取器替身：返回预先给好的概念/关系（不联网、不过模型）。"""

        def __init__(self, concepts=(), relations=()):
            self.concepts, self.relations = list(concepts), list(relations)
            self.seen_meta: list[dict] = []

        def extract(self, doc, lit_id, meta):
            self.seen_meta.append(dict(meta))
            return list(self.concepts), list(self.relations)

    class _FailingExtractor:
        def extract(self, doc, lit_id, meta):
            raise RuntimeError("selftest extractor boom")

    TEXT = "An abelian group is a group in which the commutative law holds. 群论里的交换律。"

    class _Doc:
        """最小文档替身：刻意不 import `extract.DocumentText`。

        契约是鸭子类型的，而且只有两条：`pages`（逐页文本）与 `text_at`（1-based 闭区间）。
        用最窄的替身把这两条钉死，比依赖 `extract.py` 的字段增删更稳
        （它也确实是 `quoteverify.check_quote` 实际读的全部）。
        """

        def __init__(self, text: str = TEXT, extra_pages: tuple[str, ...] = ()):
            #: `pages[0]` 是第 1 页。`extra_pages` 是给"页码写错"那一段用的：
            #: 引文落在第 2 页，而关系声明的是第 1 页（`E-11` 那一档）。
            self.pages = [text, *extra_pages]

        def text_at(self, lo: int, hi: int) -> str:
            return "\n".join(self.pages[lo - 1: hi])

    def _extract(_path) -> _Doc:
        return _Doc()

    def _write_lit(st: Store, lit_id: str, name: str) -> None:
        d = st.library / lit_id
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.txt").write_text(TEXT, encoding="utf-8")

    def _add_lit(st: Store, lit_id: str, *, path: str | None, processed: bool = False,
                 claimed_by: str | None = None, lease_until: str | None = None,
                 mine_attempts: int = 0) -> None:
        with st.tx("literature", actor="selftest") as tx:
            row = S.Literature(lit_id=lit_id, title=f"Selftest {lit_id}", type="J", summary="",
                               path=path, processed=processed, source_request_ids=[],
                               dedup_key=f"title:selftest {lit_id}|*", added_at=S.now_iso(),
                               claimed_by=claimed_by, lease_until=lease_until,
                               mine_attempts=mine_attempts)
            row.validate()
            tx.upsert("literature", row.to_dict(), note="selftest")

    def _lit(st: Store, lit_id: str) -> dict:
        return next(r for r in st.rows("literature") if r.get("lit_id") == lit_id)

    def _drain(st: Store) -> None:
        """把文献队列清空（每段断言都在一个已知的队列上做，段落之间不互相干扰）。"""
        with st.tx("literature", actor="selftest") as tx:
            for r in tx.rows("literature"):
                if not r.get("processed"):
                    r["processed"] = True
                    r["claimed_by"] = None
                    r["lease_until"] = None
                    tx.upsert("literature", r, note="selftest_drain")

    def _mk(root: Path, *, extractor=None, config=None) -> AgentB:
        cfg = {"lease_seconds": 900, "max_attempts": 3}
        cfg.update(config or {})
        return AgentB(Store(root), extractor=extractor or _Extractor(), extract_text=_extract, config=cfg)

    try:
        root = Path(tempfile.mkdtemp(prefix="agentflow_agent_b_selftest_"))
    except OSError:  # pragma: no cover - 沙箱拒绝系统临时目录时退到仓库内
        root = Path(__file__).resolve().parents[2] / "demo" / "agent_b_selftest"
        shutil.rmtree(root, ignore_errors=True)
    try:
        print("[agent_b 自检] 离线、确定性；工作区：", root)

        # ---- 1) 主路径：概念复用 + 引文逐字核实 + related_concepts 由关系表派生
        st = Store(root)
        st.init(force=True)
        _write_lit(st, "0000", "selftest")
        _add_lit(st, "0000", path="0000/selftest.txt")
        quote = "An abelian group is a group in which the commutative law holds."
        ext = _Extractor(
            concepts=[_Concept("group", "群"), _Concept("abelian group", "交换群")],
            relations=[_Relation(["group", "abelian group"], quote, "交换群是群")],
        )
        b = AgentB(st, extractor=ext, extract_text=_extract, config={"lease_seconds": 900, "max_attempts": 3})
        res = b.run_once()
        check("主路径：处理 1 篇、建 2 个概念、写 1 条关系",
              res.processed == 1 and res.concepts_created == 2 and res.relations_added == 1)
        check("引文逐字核实通过（quotes_verified=1）且行内 quote_verified=True",
              res.quotes_verified == 1
              and st.rows("relations")[0].get("quote_verified") is True)
        check("processed 语义：处理完成后置 True 并释放租约",
              _lit(st, "0000")["processed"] is True and _lit(st, "0000")["claimed_by"] is None)
        # 并表之后"哪些概念相关"没有可写的列：真相在 `relations` 表里，读侧现算
        # （`dedup.derive_related_concepts` 是唯一实现，`verify` 的 drift 判据也用它）。
        # 这一格原先断言"老表的 `related_concepts` 等于别号的全集" —— 那一列已随表退役，
        # 断言它只会变成"`[] == 别号全集"，即一条恒假的假红。
        _concepts_now = _CR.view(st, shape="legacy")["rows"]
        _rels_now = st.rows("relations")
        check("概念之间的关联由关系表**派生**（从 relations 现算，各自指向对方、不留空）",
              all(sorted(D.derive_related_concepts(c["concept_id"], _rels_now, include_suspect=True))
                  == sorted(x["concept_id"] for x in _concepts_now
                            if x["concept_id"] != c["concept_id"])
                  for c in _concepts_now))

        # ---- 2) 概念复用而不是重复建：同名概念走 find_concept，只在歧义时建新的
        _write_lit(st, "0001", "selftest")
        _add_lit(st, "0001", path="0001/selftest.txt")
        ext2 = _Extractor(concepts=[_Concept("group", ""), _Concept("交换群", "", ["abelian group"])], relations=[])
        b2 = AgentB(st, extractor=ext2, extract_text=_extract, config={"lease_seconds": 900, "max_attempts": 3})
        res2 = b2.run_once()
        check("概念名复用：'group' 走既有代号、'交换群' 以别名并入 'abelian group'，都不新建概念",
              res2.concepts_created == 0 and res2.concepts_reused == 2
              and len(_CR.view(st, shape="legacy")["rows"]) == 2,
              f"created={res2.concepts_created} reused={res2.concepts_reused}")
        check("别名合并写回概念行（否则后续同义名会各自建一份概念）",
              any("交换群" in (c.get("aliases") or []) for c in _CR.view(st, shape="legacy")["rows"]))
        check("抽取器拿到了概念表种子，且没有 seed_concepts_error（种子只影响召回率，不是权威）",
              bool(ext2.seen_meta[0].get("seed_concepts")) and "seed_concepts_error" not in ext2.seen_meta[0])

        # ---- 3) 引文回验失败 ⇒ 落库但降级 suspect（不丢弃证据）
        _write_lit(st, "0002", "selftest")
        _add_lit(st, "0002", path="0002/selftest.txt")
        ext3 = _Extractor(relations=[_Relation(["group", "abelian group"], "这句话原文里根本没有。", "幻觉引文")])
        b3 = AgentB(st, extractor=ext3, extract_text=_extract, config={"lease_seconds": 900, "max_attempts": 3})
        res3 = b3.run_once()
        check("引文找不到：仍然落库（不丢证据）但 status=suspect，且 quote_verified=False",
              res3.relations_suspect == 1 and res3.suspect_by_quote == 1
              and any(r.get("status") == "suspect" and r.get("quote_verified") is False
                      for r in st.rows("relations")))
        check("I6 闸门计数可观察：跑了就计 conflict_checks_run，没跑就计 skipped（三态不折叠）",
              res3.conflict_checks_run + res3.conflict_checks_skipped >= 1)

        # ---- 3b) `E-11`：引文逐字存在、但页码写错 ⇒ 单独可数（不折进 verified）
        _drain(st)
        _write_lit(st, "0005", "selftest")
        _add_lit(st, "0005", path="0005/selftest.txt")
        ext3b = _Extractor(relations=[
            _Relation(["group", "abelian group"], TEXT, "页码写错",
                      page_range=S.PageRange(1, 1, "p. 1")),
        ])
        # 引文在第 2 页，而上面声明的页码是第 1 页；widen=1 ⇒ 落在扩展窗口里命中。
        # 第 1 页刻意给一段不含引文的文本：`_Doc` 的默认页就是 TEXT，直接用默认
        # 会让声明窗口内直接命中（`substring_match`），根本走不到"页码写错"那一档。
        b3b = AgentB(st, extractor=ext3b,
                     extract_text=lambda _p: _Doc(text="第一页：这里没有那句话。",
                                                  extra_pages=(TEXT,)),
                     config={"lease_seconds": 900, "max_attempts": 3, "quote_widen_pages": 1})
        res3b = b3b.run_once()
        check("页码写错：引文仍计 quotes_verified（逐字可达是真的），"
              "但必须**另计** quotes_out_of_declared_range=1（`E-11`）",
              res3b.quotes_verified == 1 and res3b.quotes_out_of_declared_range == 1,
              f"verified={res3b.quotes_verified} out_of_range={res3b.quotes_out_of_declared_range}")

        # ---- 4) 抽取失败 ⇒ 不置 processed（留给租约到期重试）
        _write_lit(st, "0003", "selftest")
        _add_lit(st, "0003", path="0003/selftest.txt")
        b4 = AgentB(st, extractor=_FailingExtractor(), extract_text=_extract,
                    config={"lease_seconds": 900, "max_attempts": 3})
        res4 = b4.run_once()
        check("抽取抛异常：failed=1 且文献**没有**被置 processed、last_mine_error 留下原因",
              res4.failed == 1 and _lit(st, "0003")["processed"] is False
              and "boom" in str(_lit(st, "0003")["last_mine_error"]))

        # ---- 5) 无本地文件 ⇒ 标为已处理并记明原因（否则永远堵在队首）
        # 先把上一段留下的"仍在队列里"的行清掉，让这一段的队列是已知的。
        _drain(st)
        _add_lit(st, "0004", path=None)
        b5 = AgentB(st, extractor=_Extractor(), extract_text=_extract, config={"lease_seconds": 900, "max_attempts": 3})
        res5 = b5.run_once()
        check("没有本地文件：unreadable=1、置 processed=True 并写明 no_local_file",
              res5.unreadable == 1 and _lit(st, "0004")["processed"] is True
              and "no_local_file" in str(_lit(st, "0004")["last_mine_error"]))

        # ---- 6) 取文献侧的三态：'队列空了' / '全被别人占着' / '全被放弃'
        st6 = Store(Path(root) / "claim")
        st6.init()
        b6 = AgentB(st6, extractor=_Extractor(), extract_text=_extract, config={"lease_seconds": 900, "max_attempts": 3})
        empty = b6.run_once()
        check("队列空：skipped_reason=no_unprocessed_literature（不是静默的成功）",
              empty.skipped_reason == "no_unprocessed_literature")
        _add_lit(st6, "0000", path=None, claimed_by="agent-B-other", lease_until=make_lease(900))
        leased = b6.run_once()
        check("全都被人持着有效租约 ⇒ **不是**'队列空了'，而是 pending_literature_all_leased",
              leased.skipped_reason == "pending_literature_all_leased" and leased.skipped_lease_active == 1)
        check("被有效租约占着的行不会被抢走（claimed_by 原样保留）",
              _lit(st6, "0000")["claimed_by"] == "agent-B-other" and _lit(st6, "0000")["processed"] is False)
        _add_lit(st6, "0001", path=None, mine_attempts=3)
        gave = b6.run_once()
        check("超过 max_attempts ⇒ 显式放弃（gave_up=1）且 reason 与'全被租'可区分",
              gave.gave_up == 1 and gave.skipped_reason == "no_claimable_literature"
              and _lit(st6, "0001")["processed"] is True)
        check("三种 skipped_reason 互不相同（三态不许压成一个）",
              len({empty.skipped_reason, leased.skipped_reason, gave.skipped_reason}) == 3)

        # ---- 7) I5：结构重复必须有两路独立证据才合并，否则否决并给理由
        st7 = Store(Path(root) / "i5")
        st7.init()
        with st7.tx(*_CR.tables_for_concept_write(), actor="selftest") as tx:
            for cid, name, definition in (("0000", "群", "群的定义"), ("0001", "group", "")):
                row = S.Concept(concept_id=cid, name=name, definition=definition, related_concepts=[],
                                normalized_name=T.normalize(name), aliases=[],
                                created_at=S.now_iso(), updated_at=S.now_iso())
                row.validate()
                _CR.upsert_legacy_shaped(tx, row.to_dict(), actor="selftest", note="selftest")
        b7 = AgentB(st7, extractor=_Extractor(), extract_text=_extract, config={"lease_seconds": 900, "max_attempts": 3})
        no_ev = b7.decide_structural_duplicate(
            {"concept_ids": ["0000", "0001"], "name_evidence": "none", "neighbors": []}
        )
        check("名字侧无证据 ⇒ reject（'结构等价 ≠ 同义'，只有一路证据不得合并）",
              no_ev["verdict"] == "reject" and no_ev["survivor_id"] is None)
        row = b7.resolve_structural_duplicate({"concept_ids": ["0000", "0001"], "name_evidence": "none"})
        check("reject 时**一行数据都不写**（applied=False，概念行一个墓碑都没有）",
              row["applied"] is False
              and all(c.get("status") != "superseded"
                      for c in _CR.view(st7, shape="legacy")["rows"]))
    except Exception as e:  # noqa: BLE001
        # 自检自己炸了也必须报 FAIL（理由同 `agent_a._selftest`）：检查器"没跑成"
        # 不是"通过"，而 traceback 会让失败项清单为空、看不出挂在哪一条。
        checks.append((f"自检执行中断：{type(e).__name__}: {e}", False))
        print(f"    [FAIL] 自检执行中断：{type(e).__name__}: {e}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    bad = [label for label, ok in checks if not ok]
    print(f"[agent_b 自检] {len(checks) - len(bad)}/{len(checks)} 项通过")
    if bad:
        print("[agent_b 自检] 失败项：")
        for label in bad:
            print(f"  - {label}")
        return 1
    return 0
