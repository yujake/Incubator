# 46 施工级调查 07：角色 A / B / C / D 与 H（条目 D-2 · EE-12/EE-07 · S-01 · S-03 · S-02/S-07/S-08/S-09 · R-04-H）

调查对象：仓库 `D:\Incubator\agentflow`（包 `agentflow`，源码 `src/agentflow/`，测试 `tests/`）。
范围：`agent_b/{core,run_once,register_statement}.py`、`agent_c/`（`hottest`/`gaps`/`cold`/`paths`/`_support`/`core`）、`tools/graph_tools.py`、
`conductor.py`（S-01 的摘要截断那一半）、`agent_a/core.py`、`agent_d/{assess,consider,submit_gaps,research,write_report,core}.py` + `_support.py`、`agent_h/{core,verify_fixes}.py` + `tools/review_tools.py`。
方法：`read` / `grep` / `glob` / `python -B -c`（只读统计）+ 重跑既有探针。**没有修改仓库里任何文件**（只新增本报告）。
「施工单元」= 一个文件，或**同一机制、同一改动**的一组文件（§5/§10/§13 是文件组，已在标题里写明）。
每条结论后给 `file:line` 或命令输出；判定不可行 / 高风险的地方写明并给证据。

## §0 基线与复算命令（全部本次实跑）

**①（B 的租约探针，重跑）** `python -B D:\Incubator\temp\_probe_b_claim.py`：

```text
after run_once #1: failed=1 processed=False claimed_by=None lease_until=None mine_attempts=1
after run_once #2: failed=1 processed=False claimed_by=None mine_attempts=2 last_err='RuntimeError: boom-probe'
after run_once #3: failed=1 processed=False claimed_by=None mine_attempts=3
after run_once #4: failed=0 processed=True skipped_reason='no_claimable_literature' mine_attempts=3
lease still active at this moment: False
```

**②（C 的产物落点）** 两根 `analysis_reports` 行数 **全 0**（文件存在：agentflow 57 份、Incubator 22 份）。C 任务产物 `out/tasks/*.json` 的 `payload_keys`：

```text
agentflow: C 产物 37 份；payload_keys 空的 26 份（hottest 11 / gaps 12 / cold 2 / paths 1），非空 11 份（contradictions 8 / neighbors 1 / relations_between 1 / structural_duplicates 1）
incubator: C 产物 22 份；payload_keys 空的 21 份（hottest 14 / gaps 7），非空 1 份（contradictions 1）
样本：t-0146.json hottest keys=[] bytes=15271 prevlen=2000；t-0148.json gaps keys=[] bytes=65544 prevlen=2000
```

**③（D 的五个核心动作）** 两根**全 0**：`assess` 0 / `submit_gaps` 0 / `adjudicate` 0 / `trace_question` 0 / `trace_l3` 0（`tasks.json` 逐行统计）。同一次统计里 D 的其余动作：agentflow 根 `research` ok=45/refused=25、`run_round` ok=10/refused=8、`write_report` ok=45、`consider` 3、`ingest` 2+`ingest_detailed` 5、`poll` 2、`probe_c` 1、`propose_question` ok=46/refused=43、`register_conjecture` ok=70/refused=52；Incubator 根只有 `poll` 1、`register_conjecture` ok=190/refused=1。

**④（`documents[].claims` 两个正交轴）** 449 条：`status` 有值 **0**、`allowed_use` 有值 **0**、`evidence_kind` 有值 **449**（`cross_check` 289 / `heuristic` 150 / `proof` 10）。

**⑤（`role=C` 的 tasks 行与动作种类）** agentflow 根 46 行：`hottest` 12 / `gaps` 13 / `contradictions` 9 / `cold` 3 / `structural_duplicates` 2 / `paths` 2 / `neighbors` 2 / `relations_between` 2 / `handle` 1；Incubator 根 29 行：`hottest` 14 / `gaps` 14 / `contradictions` 1。

**附加读数（本报告后续要用）**：未闭环检索请求（`done=False` 且 `outcome=None`）agentflow 根 **7** 条（`agent-D` 3、`agent-C` 3、`agent-F` 1）、Incubator 根 **14** 条（全 `agent-F`）；D 的 `write_report` 召唤 45 次而盘上 `<qid>-research.md` 只有 **5** 份（同名覆盖）；`D.trace_l3` 在 `tests/` 的调用点 **0** 处。
**一处悬空引用（顺带发现，不属本条任何条目）**：8 个角色包的动作文件 docstring 都引「拆出来的判据：……（`temp/_m6_verify_verbatim.py`）」或「（`tests/test_agent_split_is_verbatim.py`）」，但这两个文件在全仓都不存在（`Get-ChildItem -Recurse -Filter '*verbatim*'` 无输出）；真身在跑的是 `tests/test_agent_split_is_one_action_one_file.py:17-19`（它只把那次逐字证明写成历史说明，不执行它）。⇒ 结论：**没有判据钉"动作文件内容与拆分前逐字相同"**，改这些文件不会撞门；但"文档说有一个判据、实际没有"本身正是 F-07 元判据要抓的形态，登记时不要写成"有逐字判据守着"。

复算命令（全部只读）：`python -B -c "<内联统计>"`（遍历两根 `data/*.json` 与 `out/tasks/*.json`）；探针 `python -B temp\_probe_b_claim.py`。

---

## §1 `src/agentflow/agent_b/core.py` —— D-2 的判据面

**1 现状**：`_claim()`（`:76-132`）是本条 bug 的判据本体。跳过判据 `if r.get("claimed_by") and not lease_expired(...)`（`:97`）**同时要求 `claimed_by` 非空**；而失败分支写的租约恰好是 `claimed_by=None`。同族的 `_claim_reprocess()`（`:261`）与 `_record_reprocess_failure()`（`:548-560`）同一个形状。`:48-49` 的 `lease_seconds` 缺省 900、`max_attempts` 缺省 3。

**2 逐改动点**（原文）：

```python
# agent_b/core.py:96-99
for r in cands:
    if r.get("claimed_by") and not lease_expired(r.get("lease_until")):
        skipped_lease_active += 1
        continue  # 别人正拿着有效租约
# agent_b/core.py:111-114
r["claimed_by"] = self.actor
r["lease_until"] = make_lease(self.lease_seconds)
r["mine_attempts"] = n + 1
tx.upsert("literature", r, note="claimed")
```

接口级伪码（照 A 的写法搬，`:178-183` 是同一件事的正确实现）：

```text
_claim():
  判据改为「租约是否仍在有效期内」（唯一判据）：if not lease_expired(r["lease_until"])
      非空 claimed_by ⇒ skipped_lease_active += 1
      空   claimed_by ⇒ skipped_lease_backoff += 1   # 新增：自己的退避租约
  取到活时置 claimed_by=self.actor / lease_until=make_lease(self.lease_seconds) / mine_attempts+=1
  四种 skipped_reason 新增 "pending_literature_all_in_backoff"
  _claim_reprocess(): 同一改法，另加 skipped_reason 分档
  BClaimOutcome: 新增字段 skipped_lease_backoff（dataclass 在 agent_b/_support.py）
```

**3 调用面**：`AgentB._claim()` 在 `src/` 里**只有一个调用点**：`agent_b/run_once.py:23`（`grep '_claim\(\)' src/` 的实测结果）；B 的自检（`agent_b/core.py:994`/`:998`/`:1004`）也是经 `b6.run_once()` 间接驱动它，不直接调。`tests/`：`test_agent_b.py`（13 处 `run_once` 驱动）、`test_agent_b_gates.py`（6）、`test_intake_actions.py`（14 处 `register_statement`）、`test_agent_a_backoff.py`/`test_agent_a_priority.py` 是 **A** 的租约测试（可作对照组）。**没有任何测试直接调 `AgentB._claim()`**。

**4 数据结构与历史数据影响**：只改跳过判据与计数，**不改盘上字段**；`mine_attempts` 的推进速度变慢（同一行在同一次 `run()` 里不再被连领）。历史数据：真机 `literature.json` 的 `mine_attempts` 只有 `{0,1}`（`draft/41` §3.2），退避租约在真机上**从未被写过**，因此改后历史行一个字节变化都不会有；新增的 `skipped_reason` 取值只活在返回值里（`BRunResult.to_dict()`），不进表。

**5 可行性与改动量**：**高可行**。判据 +1 个分支、计数 +1、`skipped_reason` +1 取值；`_claim` 约 8 行、`_claim_reprocess` 约 6 行、`BClaimOutcome` +1 字段、自检 +1 段（照 `agent_a/core.py:592-610` 的 8b 段）。`literature` 表结构不动 ⇒ 不碰 `schema.py`。

**6 风险与验证**：风险一 = 改错后 B 真的卡住（退避 900 秒内什么也不干）⇒ 负控必须同时断言"领不到"和"退避一过期就能领到"。风险二 = 把"别人持着"也记成 backoff ⇒ 负控两条分开数（`skipped_lease_active==1` / `skipped_lease_backoff==1`）。负控：`temp/_probe_b_claim.py` 已存在，改前跑出 §0① 的读数；改后必须变成 `#2/#3` 领不到、`mine_attempts` 停在 1。真机回放：`p5-review-t14` 之类有 `no_llm_extractor` 1 行的工作区重跑 `B.run_once`，确认它不再立刻重领（`mine_attempts` 不增）。

**7 不做部分**：不动 `lease_seconds` / `max_attempts` 的缺省值；不给 `literature` 加"退避次数"字段（`schema` 禁改区）；不把 `_claim` 与 `_claim_reprocess` 合成一个函数（两者准入判据不同，合并等于给重抽取加四条无关判据）；不动 `_is_fallback_extractor`。

---

## §2 `src/agentflow/agent_b/run_once.py` —— D-2 的写入面（三个失败分支）

**1 现状**：`run_once()`（`:10-312`）里有 **三个**"释放租约"的分支，全部写 `claimed_by=None` + `lease_until=None`，**没有一支写退避租约**：不可读（`:48-59`）、回退抽取器拒抽（`:64-76`）、抽取抛异常（`:83-93`）。对比 A 的同族写入（`agent_a/run_once.py:205` / `:216`）写的是 `retry_backoff_seconds`。

**2 逐改动点**（原文）：

```python
# agent_b/run_once.py:84-90（抽取失败分支）
except Exception as e:
    # 抽取失败：不置 processed，让租约过期后重试
    with self.store.tx("literature", actor=self.actor, note="extract_failed") as tx:
        row = tx.find("literature", lit_id=lit_id) or lit
        row["claimed_by"] = None
        row["lease_until"] = None
        row["last_mine_error"] = f"{type(e).__name__}: {e}"
        tx.upsert("literature", row, note="extract_failed")
```

接口级伪码：

```text
__init__: self.retry_backoff_seconds = int(cfg.get("retry_backoff_seconds", 60))   # 与 A 同口径，get 而非 or
失败三分支统一改为：
    row["claimed_by"] = None
    row["lease_until"] = make_lease(self.retry_backoff_seconds)   # 唯一改动
    row["last_mine_error"] = ...
"不可读"与"回退拒抽"两支：可配置 decision —— 默认也写短退避（否则每次 run 都在队首重领同一行）
不写退避的那一支保留：`processed=True` 的成功路径（:303-309）继续清空租约
```

**3 调用面**：`src/`：`agent_b/run.py:10-43`（循环调 `run_once`）、`agent_b/__main__.py`、`cli.py` 的 B 派发、`host.py` 的实例装配。`tests/`：`test_agent_b.py`（13）、`test_agent_b_gates.py`（6）、`test_core_audit_abc_cli.py`（6）、`test_intake_actions.py`、`test_download_handoff.py`（3）。**没有测试钉"逐字未改"**：动作文件 docstring 里引的 `temp/_m6_verify_verbatim.py` 在一次全仓 `-Filter '*verbatim*'` 扫描下**已不存在**（那是 M6 的一次性证明）；真正在跑的是 `tests/test_agent_split_is_one_action_one_file.py`，它只钉三件事（每个 `handler_name` 有自己的 `<动作>.py`、方法的 `__module__` 是 `agentflow.agent_b.<动作>`、`core.py` 里不定义动作方法）。⇒ 改 `run_once.py` 的内容**不会**撞任何判据；只有"把动作搬回 core"或"删动作文件"才会红。

**4 数据结构与历史数据影响**：写入字段不变（`lease_until` 本来就是字段），只改变它的取值。历史行 `lease_until` 全 `None`（`draft/41`：`mine_attempts ∈ {0,1}`、`last_mine_error` 358 条都是"事先判为不可读"）；没有迁移问题。

**5 可行性与改动量**：**高可行**，3 处各 1 行 + `__init__` 1 行 + 一处常量。风险点只有"哪个分支该退避"：`unreadable`（`:48-59`）已置 `processed=True`，它**不需要**退避（不再会被领到）；`no_llm_extractor`（`:64-76`）**必须**退避（它刻意不置 `processed`，是唯一会被无限重领的一支，也是真机 `no_llm_extractor` 1 行的来源）。

**6 风险与验证**：负控三条：①抽异常 ⇒ 写退避、再领领不到、`mine_attempts` 不增；②`no_llm_extractor` ⇒ 同上；③退避秒数置 0 ⇒ 立刻可重领（三态：0 是合法配置而不是"没配"，与 `agent_a/core.py:45-47` 同口径）。真机回放：`p2-review` 快照（`last_mine_error` 分布最全）跑一次 `B.run()`，确认 `processed` 行数不变、`mine_attempts` 不再跳档。

**7 不做部分**：不改概念/关系/引文回验主链路（`:95-301`）；不改"不可读 ⇒ 置 processed"的处置（那是刻意设计，避免永远堵队首）；不给 `BRunResult` 加新计数以外的字段；不动 `R-56` 拒抽判据。

---

## §3 `src/agentflow/agent_b/register_statement.py` —— EE-12 / EE-07

**1 现状**：唯一语句写者手填 `evidence_kind`（`:80` 缺省 `"cross_check"`、`:97` 兜底 `"heuristic"`、`:98-101` 校验它属于 `S.EVIDENCE_KINDS`、`:192` 写进行里），**构造 `S.Statement` 时没有 `bits=` 参数**（参数表 `:69-86` 里没有 `bits`）。而 `schema.py:1604-1612` 逐字声明 `evidence_kind` 是"派生只读视图"、真正判等级的是 `bits`。三条读它的路径各说各话（`evidencebits.derive_grade` 读 `bits`、`claimanatomy.status_evidence_consistency` 读 `status`×`evidence_kind`、`closing.py:1438` 第④条读 `evidence_kind`）。

**2 逐改动点**（原文）：

```python
# agent_b/register_statement.py:97-101
evidence_kind = str(evidence_kind or "heuristic")
if evidence_kind not in S.EVIDENCE_KINDS:
    return _refuse("bad_evidence_kind",
                   f"evidence_kind 必须是 {S.EVIDENCE_KINDS} 之一，收到 {evidence_kind!r}"
                   "（它是证据**强度**，不是来源；来源走 source_lit_id）")
# agent_b/register_statement.py:180-193
row = S.Statement(
    stmt_id=stmt_id, origin=origin, kind=str(kind or "theorem"), label=str(label or ""),
    statement_text=str(statement_text or ""), statement_full=full,
    proof_text=str(proof_text or ""), source_lit_id=lit_id or None,
    page_range=S.PageRange.from_dict(page_range), quote_verified=quote_verified,
    quote_reason=str(quote_reason or ""), evidence_kind=evidence_kind, status="active",
```

接口级伪码（EE-12 = 补 `bits=`；EE-07 = 单一来源）：

```text
新增参数（都可省略，带默认值）：
    numeric / numeric_evidence / proof / proof_process / reviewed / reviewed_by /
    formal / formal_evidence / audited / audited_by        # 与 evidencebits.bits_of 的形参同名
构造：
    bits = EB.bits_of(origin=origin, source_lit_id=lit_id, quote_verified=quote_verified,
                      numeric=..., proof=..., reviewed=..., formal=..., audited=..., ...)
    evidence_kind = EB.derive_evidence_kind(bits)   # 新增纯函数：把 bits 映射回 EVIDENCE_KINDS
    row = S.Statement(..., bits=bits, evidence_kind=evidence_kind, ...)
写入前：problems = EB.bits_shape_problems(bits) ⇒ 有问题就 refuse("bad_bits", ...)（照 :98-101 的形状）
向后兼容：调用方一个位都不给 ⇒ bits 传 {}（不得写非空 bits），evidence_kind 仍按现口径缺省
```

**3 调用面**：`src/`：`specs/b.py` 的动作声明（`register_statement` 的参数表）、`cli.py` 的 B 派发、`conductor` 经 `backend.call` 转 `handler_name`。`tests/`：`test_intake_actions.py`（14 处）、`test_action_surface_matches_acceptance.py`（6）、`test_review_intake_chain.py`（2）；`tests/test_evidence_bits.py` 与 `test_verifier_role.py:121` 直接测 `bits_of`（**只有测试调用**）。声明层改动落在 `src/agentflow/specs/b.py`（**FC-27 禁改区**）。

**4 数据结构与历史数据影响**：`bits` 字段**已存在**（`schema.py:1613` `bits: dict = field(default_factory=dict)`），加参数是"写一个已有字段"，不是加字段 ⇒ **不违反 §0 前置结论的"不许加必填字段"**。历史数据：`statements` 138 行里 `bits` 有值 **0 行**；`bits={}` 一律按"五位全空"读（`evidencebits.bits_from_row:124-126`）⇒ 旧行等级仍是"猜想"，**改后旧行读数不变**。`evidence_kind` 从手填变派生：`agentflow` 根现有 `proof` 6 行 / `cross_check` 若干；派生口径下，`origin=external_lit` 且 `quote_verified=True` 的行会得 `proof`（`bits_of:80-84` 的 cited 分支把第 2、3 位置真）——**这会改变现有 6 行 `proof` 之外的行的 `evidence_kind` 读数**，属读数口径变更，必须按 §0 前置结论 2 在登记册写明"从哪一趟起口径变了"。

**5 可行性与改动量**：**中高可行**。判据本体（`bits_of` / `derive_grade` / `bits_shape_problems`）已存在且已通过 `schema.py:1684-1696` 的写入期转发；需要新写的只有 `derive_evidence_kind`（`evidencebits.py` 里 5–10 行的映射，`GRADES`×`EVIDENCE_KINDS` 是 4×3）与 `register_statement` 的参数面 / 预检 / 构造。`specs/b.py` 改参数表 ⇒ **禁改区（auth-audit），需 2 名人审**。

**6 风险与验证**：风险一 = 派生出的 `evidence_kind` 与 `claimanatomy` 的 `status×evidence_kind` 交叉门不一致 ⇒ 真机 `documents.claims` 的 `status` 轴本来就是 0/449，交叉门只会返回"未知"，不会因此变红，但必须配一条负控（`bits.proof=True` + `status="证"` ⇒ 两侧一致；`bits` 全空 + `status="证"` ⇒ 报不一致）。风险二 = `quote_verified is True` 被当成"逐字核过"就抬到 proof 位（`bits_of:80`），而 `quote_verified` 只证明"这句话在文件里"（`agent_b/core.py:39-43` 的原文）⇒ 派生口径要么只取 `cross_check`，要么在 `evidence_kind` 的映射里把 cited 分支封在 `cross_check`。负控两条必须都能红。真机回放：`p2-review`（`statements` 最多的工作区）逐行比对改前/改后的 `evidence_kind` 与现算 `grade`，确认"变了的正是该变的"。

**7 不做部分**：不改 `schema.py`（`Statement.bits` 与 `evidence_kind` 的字段定义、`SCHEMA_VERSION`）；不改 `closing.py:1438` 第④条（那属 E-05 读数口径，另一批）；不改 `claimanatomy` 的交叉门；**不**顺手把 `documents[].claims` 的 `status`/`allowed_use` 一起填（那是 EE-06，`schema` 禁改区且是另一条产线）。

---

## §4 `src/agentflow/agent_c/_support.py` —— S-01 的落盘机制

**1 现状**：`AnalysisReport` 是 dataclass（`:204-252`），`persist()`（`:256-324`）是**唯一**把 markdown 写进 `<ws>/reports/<rid>-<kind>.md` 并把登记行 upsert 进 `analysis_reports` 的地方。四道硬校验：`kind ∈ S.REPORT_KINDS`（`:284`）、markdown 非空（`:289`）、summary 非空（`:291`）、payload 可 JSON 序列化（`:293-298`）。`S.REPORT_KINDS = ("hottest","paths","cold","gaps")`（`schema.py:442`）。

**2 逐改动点**（原文）：

```python
# agent_c/_support.py:300-306
who = actor or self.created_by or "agent-C"
out_dir = Path(reports_dir) if reports_dir else (Path(st.root) / "reports")
with st.tx("analysis_reports", actor=who, note=f"analysis_report:{self.kind}") as tx:
    rid = tx.alloc_id("report")
    rel_name = f"reports/{rid}-{self.kind}.md"
    abs_path = out_dir / f"{rid}-{self.kind}.md"
    _atomic_write_text(abs_path, self.markdown)
```

接口级伪码（S-01 的落盘半边）：

```text
persist() 保持不变（它是唯一的写入口，位置与顺序已经是对的：先写文件、再落登记行，理由在 :263-277）
新增：AnalysisReport.to_task_payload() -> dict     # 供 conductor 的摘要用（§8）：返回 to_dict() 并保证可 json.dumps
新增：AgentC._finish_report(rep) -> AnalysisReport  # 统一收口：
        if rep.ok and rep.kind in S.REPORT_KINDS and rep.markdown.strip():
            rep.persist()          # 失败不抛给调用方：记进 rep.warnings 并保留 ok=False + error
        return rep
把 ::256 的 persist() 从"调用方负责"改成"_finish_report 负责"（§5 §6 的四个动作各调一次）
```

**3 调用面**：`src/`：`cli.py:481`（`analyze` 人工命令）、`pipeline.py:87-148`（`_persist_report`，L-03 已判退场）、`agent_c/__main__.py:381-398`（自检）、`agent_d/core.py:1426`/`:1474`（D 自检里的假 C 报告）。`tests/`：`test_agent_c.py:485-522`（persist 双份落盘 + 三类拒绝）、`test_core_audit_abc_cli.py:425-434`、`test_pipeline.py:48/91/117`、`test_agent_d.py`（5 处 `persist`）。**新增自动落盘会让下面两条现有断言语义变化**：`tests/test_agent_c_service.py:641` 逐字写着 `assert kn.rows("analysis_reports") == [], "gaps 不落报告表（要落盘必须显式 persist）"`；`tests/test_agent_c.py:522` 同类。这两条是"S-01 改前必红"的现成负控（把它们的期望反向即可），**不能靠删测试绕过**。

**4 数据结构与历史数据影响**：`analysis_reports` 表**早已存在且结构不变**（`schema.py:826-854`：`report_id`/`kind`/`request`/`params`/`summary`/`payload`/`markdown_path`/`created_at`/`created_by`），只是从来没有生产写者。历史数据：两根 **0 行** ⇒ 双写不会污染任何历史行，但读数会**首次非 0**（`closing.py:165-169` 的 `analysis_report_rows` 档会第一次有读数；`draft/44` S-07 要求写清"从这一批起 `analysis_reports` 才有产出方"）。`reports/` 目录里会新增 markdown 文件（盘上原来只有 `pipeline`/`cli` 路径写过的少量文件）。

**5 可行性与改动量**：**中**。落盘半边（`_finish_report` + 四个动作各一行）改动量小；难点全在 §5（dataclass 返回值要能被 conductor 摘要）与 §8（`payload_keys`）。

**6 风险与验证**：风险一 = `alloc_id("report")` 在事务里 ⇒ 每次 C 分析都吃一个号、写两个落点（文件 + 行），失败面从 0 变 2；处置：文件写失败（`_atomic_write_text` 抛）必须让整笔回滚（现在 `persist` 的顺序已经保证了"最坏只留孤儿文件"，见 `:263-272`）。风险二 = 真机 45 次 `write_report`、37 份 C 产物意味着一次真机趟次会多出几十行 `analysis_reports` 与几十个 markdown ⇒ 磁盘与读数都要有上限意识（`reports/` 无清理机制）。负控：①`kind="unknown"`（`handle` 分派失败）⇒ **不许落盘**且 `analysis_reports` 仍为 0；②markdown 为空 ⇒ 不许落行（`persist` 会抛，`_finish_report` 必须接住并保留 `ok=False`）；③同一份报告 persist 两次 ⇒ 两个 report_id、两行（这是既有语义，不是 bug）。真机回放：`p6j-research-from-zero`（C 被召唤最多）跑一次 `C.gaps`，确认 `analysis_reports` 首次非 0 且 `reports/<rid>-gaps.md` 存在。

**7 不做部分**：不改 `S.REPORT_KINDS`（`schema.py` 禁改区）⇒ **`contradictions`/`neighbors`/`relations_between`/`structural_duplicates`/`handle` 这五个动作仍然不能落盘**（它们的产物只活在返回值与 `out/tasks` 摘要里，见 §5/§8）；不删 `pipeline._persist_report`（L-03 是另一条）；不改 `persist()` 的校验（那是"拒绝登记半个报告"的判据）。

---

## §5 `agent_c/{hottest,gaps,cold,paths}.py`（文件组，同一改动） —— S-01 的返回值形状

**1 现状**：这四个动作返回 `AnalysisReport` **dataclass 实例**（`hottest.py:10`、`gaps.py:10`、`cold.py:10`、`paths.py:19`），构造统一走 `_report()`（`agent_c/core.py:75-103`，`:102` 挂 `rep._store = self.store` 让 `persist()` 免参可用）。因此经 `conductor.summon` 时 `isinstance(payload, Mapping)` 为假 ⇒ `payload_keys=[]`、`payload_preview` 是 `repr` 的前 2000 字节（§0②的读数）。

**2 逐改动点**（原文）：

```python
# agent_c/core.py:89-103
rep = AnalysisReport(
    kind=kind, request=request, params=dict(params), summary=summary,
    payload=dict(payload), markdown=markdown, warnings=list(warnings),
    truncated=bool(truncated), ok=ok_, error=error, created_by=self.actor,
)
rep._store = self.store  # type: ignore[attr-defined]  让 report.persist() 免参数可用
return rep
# agent_c/hottest.py:108-116（四个动作同形）
return self._report(
    "hottest", request, {"top_n": top_n},
    summary=f"最热门的 {len(entries)} 个概念：" + "、".join(...),
    payload=payload, markdown="\n".join(md) + "\n", warnings=warnings,
)
```

接口级伪码（**不改四个动作的签名**，只在 `_report()` 一处收口）：

```text
_report(...) -> AnalysisReport:
    rep = AnalysisReport(...)                    # 不动
    rep._store = self.store                      # 不动
    if self.auto_persist:                        # 新增开关，缺省 False（先只落盘、不改 D）
        rep = self._finish_report(rep)           # §4：ok 且 kind ∈ REPORT_KINDS 才落
    return rep
四个动作文件本身 0 行改动（这正是"改动面小"的地方）
```

**3 调用面**：`src/`：`agent_c/core.py:960-1018` 的 `_register(...)` 四个 lambda 都调 `.to_dict()`（所以**工具面**拿到的已经是 dict，`payload_keys` 在那里是有的）；`agent_c/handle.py` 经 `ANALYZERS` 分派（`_support.py` 的 `ANALYZERS`）；`cli.py:463-481`；`pipeline.py`。`tests/`：`test_agent_c.py`、`test_agent_c_service.py`、`test_core_audit_abc_cli.py:771-793`（`test_agent_c_writes_only_analysis_reports_and_never_the_knowledge_tables` 断言 `len(st.rows("analysis_reports")) == 3` —— **自动落盘后这个数会变**）、`test_agent_split_is_one_action_one_file.py`（只钉"一个动作一个文件 + 方法的 `__module__` + core 里不定义动作方法"，**不钉内容逐字**）。

**4 数据结构与历史数据影响**：不改返回对象字段（`to_dict()` 的形状不变）；新增的是"副作用"（落盘）与"`out/tasks` 摘要变完整"（§8）。历史 `out/tasks/*.json` 26 份 `payload_keys=[]` 已经是既成事实，**不改写历史文件**（摘要只在召唤时写一次）。

**5 可行性与改动量**：**高可行（落盘半边）**。`_report()` 是唯一收口点，四个动作文件零改动；代价是 `_report()` 要能拿到"这次是经 conductor 召唤还是直接调用"——**这是本条的真正难点**：`auto_persist` 缺省 False 时 S-01 的"落盘"不会在真机上发生（因为真机的调用方是 conductor，它不会传这个开关）。所以要么缺省 True（则 `test_agent_c_service.py:641` 与 `test_agent_c.py:522` 必改），要么在 `host.py`/`specs/c.py` 的构造配置里打开（`_config_for(role)` 一类），后者不碰禁改区。

**6 风险与验证**：风险一 = 只读角色"读动作写盘"的语义（见 §6 的权限面）。风险二 = `gaps` 在真机 14 次召唤里 7 次因 `top_n` 被拒（`draft/41` §3.6），若自动落盘，这 7 次**不会**落盘（它们根本没进 handler）⇒ 落盘数 ≠ 召唤数，读数解释要写清。负控：①`ok=False`（关系表为空，`hottest.py:37-50`）⇒ 落盘与否必须显式定档（建议**落**，因为它带完整 markdown 与 `error`，是"这次没能给出结论"的证据）；②`handle` 的 `kind="unknown"` ⇒ 绝不落（`persist` 会抛，`_finish_report` 接住）；③`submit_requests=True` 的 `gaps` ⇒ 落盘 + 写 `search_requests` 两件事都要在返回值里可见。真机回放：`p2-review` 的两次 `gaps`（`t-0203.json`，65544 字节）改后应各产生一行 `analysis_reports` 与一份 markdown。

**7 不做部分**：不改四个动作的参数表（`specs/c.py` 禁改区）；不把 dataclass 直接写进 `analysis_reports`（表里的行必须是 `schema.AnalysisReport`，两回事，见 `_support.py:206-211`）；不做"落盘后回读再返回"（会让 D 读到上一次的快照，语义漂移）。

---

## §6 `src/agentflow/agent_c/core.py` —— S-01 的工具面与 I3 写入面

**1 现状**：`register_tools`（`:916-1129`）把 9 个动作注册成 `graph.*`，**全部 `side_effect="read"`、`roles=("C","D")`**（`:956`）；`graph.gaps` 刻意不暴露 `submit_requests`（`:1019-1023`）。`_submit_gap_requests`（`:541-698`）是 C 唯一的确定性写入路径（三条闸门 + 单事务）。`WRITE_SETS["C"] = {"analysis_reports","search_requests"}` 已登记在 `READ_ONLY_WRITE_EXCEPTIONS`（`capabilities.py:1137`）。

**2 逐改动点**（原文）：

```python
# agent_c/core.py:956-958
wrapped = tool(name, summary, params, side_effect="read", roles=("C", "D"), returns=returns)(fn)
registry.register_function(wrapped)
added.append(name)
# agent_c/core.py:969
lambda top_n=5: self.hottest(int(top_n)).to_dict(),
```

接口级伪码：

```text
工具面不动（side_effect="read" 是正确声明，理由见 capabilities.py:1086-1099 —— 改它会
  让 ToolRegistry.for_role 把 graph.gaps 从 C 的工具面里滤掉，是"照字面修反而更坏"）
落盘发生在方法层（§5），不在工具面；工具面返回的仍是 rep.to_dict()（形状不变）
唯一需要动的是把"这次调用落过盘"暴露出来：
    rep.to_dict() 增加 "report_id" / "markdown_path"（persist 后回填，非持久字段，形状是增量）
```

**3 调用面**：`src/`：`host.py` 的角色装配、`conductor` 经 `backend.call` 派动作、`agent_d/probe_c.py`（D 侧点菜，走 `graph.svc_*`）。`tests/`：`test_agent_c_service.py`（含 `:641` 的反向断言）、`test_agent_c.py`、`test_capabilities.py` / `test_capabilities_two_layer.py`（两层动作表对账）、`test_tool_surface_snapshot.py` + `tests/golden/tool_surface_snapshot.json`（`returns` 串逐字钉在快照里，**改 returns 必须重冻快照**）。

**4 数据结构与历史数据影响**：`analysis_reports` 见 §4；`search_requests` 侧不动。历史影响面：真机 `search_requests` 里 `submitted_by` **没有一行是 `agent-C`**，`params` 含 `submit_requests` 的 tasks 行 **0**（`draft/41` §3.3）⇒ I3 这条路真机从未走过，改它对历史读数零影响。

**5 可行性与改动量**：**高可行**。权限面**不需要动**：`WRITE_SETS["C"]` 已含 `analysis_reports`，`assert_capabilities` 的 [6] 条（`capabilities.py:1939-1948`）会先减掉已登记例外再判，因此"只读角色 + `read` 动作 + 写自己的产出表"是这套设计**已经承认**的形态。要动 `specs/c.py` 的只有"给动作表加一句参数/摘要"这类。

**6 风险与验证**：风险一 = 工具的 `returns` 串与实现分家（`tool_surface_snapshot.json` 会红）⇒ 顺手重冻即可，但必须与 `answer` 的 `tests/test_agent_spec_reconciliation.py` 一起跑。风险二 = 落盘在 `_report()` 里做，会让 `D.probe_c` 那类"服务面"调用也落盘（`graph.svc_*` 返回 dict，不走 `_report()` ⇒ 实际不受影响，但要有负控钉住）。负控：①`graph.gaps` 的 `side_effect` 仍是 `read`（防有人图省事改成 `write_local`，那会砍掉 C 的工具面）；②`graph.gaps` 的返回值里**不得**出现 `submit_requests`（防 I3 后门）。真机回放：跑一次 `python -B -c "import agentflow.capabilities as C; C.assert_capabilities()"`，确认 177/177 与 80 对不变。

**7 不做部分**：不改 `graph.*` 的名字与参数（9 个动作名与 `specs/c.py` 逐个对齐，改名要动禁改区）；不给 `graph.gaps` 加 `submit_requests`；不把 `_submit_gap_requests` 的闸门挪到工具层（理由在 `:566-569`）；不做 C 的"自动消费检索请求"（那是 §9）。

---

## §7 `src/agentflow/tools/graph_tools.py` —— 低层图查询（S-01 的邻居面）

**1 现状**：`graph.build` / `graph.stats` / `graph.neighbors` / `graph.relations_between` 四个低层工具，全 `read`，**无 `store.tx`、无文件写**；`RelationGraph.from_store`（`:354-358`）无锁快照读 `concepts`/`relations`/`literature`；`graph.build` 只把图缓存在内存（`:829`）。

**2 逐改动点**（原文）：

```python
# tools/graph_tools.py:354-358
@classmethod
def from_store(cls, store: Any, *, service: bool = False) -> "RelationGraph":
    return cls(concepts=store.rows("concepts"), relations=store.rows("relations"),
               literature=store.rows("literature"), service=service)
```

接口级伪码：**本文件不需要改**。S-01 的落盘与摘要都不经过它；它唯一的风险是"有人为了让 C 落盘而在这里加写"——那是把只读工具变成写工具，会撞 `tools/__init__.py:104` 的 `READ_ONLY_ROLES` 与 `tools/base.py` 的 `_role_surface` 三处判据（`AGENTS.md` 的 auth-audit 版块逐字登记了这三处必须同时人审）。

**3 调用面**：`src/`：`agent_c/core.py` 的 `build_graph`/`_g`（`RelationGraph` 的真身）、`agent_c/_support.py`、`agent_d/probe_c.py`（经 `graph.svc_*`，不是这四个）。`tests/`：`test_graph_tools.py` 一类（`tools/graph_tools.py` 有独立测试）。真机：43-F 记 `graph` 族工具**真机 0 次调用**（48 件零调用工具里的一部分）。

**4 数据结构与历史数据影响**：无。它只读三张表，不落任何产物。

**5 可行性与改动量**：**无需改动**（改动量 0）。写进本报告的理由是：S-01 的"或等价落点"若被理解为"在 `graph_tools` 里落盘"，那是错的落点 —— 这里没有 `store.tx`、也没有角色身份（`roles=("C","D")` 两个角色共用），落盘会失去"谁产的"这一栏。

**6 风险与验证**：风险 = 误把它当落盘点。负控：断言 `tools/graph_tools.py` 源码里仍然没有 `store.tx(` 与文件写（现有测试与 lint 已覆盖一部分）。真机回放：不适用。

**7 不做部分**：不改 `RelationGraph` 的读法（它是 `_support.py` 与 `core.py` 共用的图本体）；不给它加 `side_effect="write_local"`；不把 `analysis_reports` 的写入口放到工具层。

---

## §8 `src/agentflow/conductor.py` —— S-01 的摘要截断那一半

**1 现状**：`_end_from_payload`（`:1059-1159`）对非 Mapping 的返回值走 `:1159` `payload=raw`（dataclass 原样）；`_write_task_digest`（`:1184-1223`）用 `json.dumps(payload, default=str)`（`:1200`）得到 repr 串，`payload_keys` 只在 `isinstance(payload, Mapping)` 时非空（`:1213`），`payload_preview = blob[:2000]`（`:1214`）。`tools/conductor_tools.py:95-116` 是另一份同口径实现（M 看到的 `payload_preview`）。

**2 逐改动点**（原文）：

```python
# conductor.py:1200-1214
blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
doc = {
    ...
    "payload_keys": sorted(str(k) for k in payload) if isinstance(payload, Mapping) else [],
    "payload_preview": blob[:2000],
}
# conductor.py:1159
return self._end(tid, status="done", outcome="ok", detail="执行完成", payload=raw)
```

接口级伪码：

```text
新增 _payload_view(payload) -> tuple[dict, dict]        # 唯一口径，conductor 与 conductor_tools 共用
    if hasattr(payload, "to_dict") and callable(payload.to_dict):
        payload = payload.to_dict()                     # dataclass（C 的 AnalysisReport）先投影
    if isinstance(payload, Mapping): keys = sorted(payload); preview = blob[:2000]
    else: keys = []; preview = blob[:2000]              # 保持"不是对象就没有键集"这条语义
写入：payload_keys 用 keys；新增 "payload_class"（payload 的类名）与 "payload_truncated"
调用点：_write_task_digest（:1200）与 conductor_tools._summon_view（:100）改调 _payload_view
不动的部分：payload_preview 的长度 2000（M 的读法已经建立在它上面，见 specs/m.py:68）
```

**3 调用面**：`src/`：`conductor.finish`（`:1345` 调 `_write_task_digest`）、`finish` 之后的 `artifacts.record`（`:1391`）、`tools/conductor_tools.py:95-116`（M 的视野）。`tests/`：`test_conductor.py`、`test_core_audit_efgh.py`、`tests/golden/tool_surface_snapshot.json:589`（`conductor.summon` 的 `returns` 串里逐字列了 `payload_preview`/`payload_bytes`/`payload_keys`/`payload_truncated` —— **改字段集必须重冻**）；真机产物 26 份 C 摘要的 `payload_keys=[]` 是这条口径的直接后果。

**4 数据结构与历史数据影响**：`out/tasks/*.json` 的字段集是**盘上产物契约**（不是 `schema.py` 的表）。新增字段是"放宽"（旧文件缺字段不影响读）；`payload_keys` 由空变非空只对新召唤生效 ⇒ **历史 26 份文件不会被改写**，但"两根 `payload_keys` 恒空"这条读数会从改后那一趟起分裂 ⇒ 读数说明必须写清分界点。

**5 可行性与改动量**：**高可行**（`conductor.py` 不在 `.noai-paths` 里 —— 逐条核对过 `AGENTS.md` 的清单）。改动 = 1 个私有函数 + 2 处调用 + 快照重冻。

**6 风险与验证**：风险一 = `payload_preview` 从 `repr` 变成"投影后的 JSON"，M 读到的内容会变多也可能变少（`to_dict()` 含 markdown 全文 ⇒ 2000 字节会被 markdown 头部吃掉，反而丢了 `payload` 的键值）。处置：摘要里对超长字段做**逐字段**截断（例如 markdown 只留 sha256 + 长度），而不是把整份 `to_dict()` 塞进 preview —— 否则 S-01 的"不截断 `payload_keys`"会以"preview 被 markdown 挤掉"的形式重新出现。风险二 = `conductor_tools` 那份同口径实现漏改 ⇒ M 看到的与盘上写的不一致（这正是"两份口径必然分家"的老形态）⇒ 必须由 `_payload_view` 单一来源。负控：①dataclass 返回值 ⇒ `payload_keys` 非空、`payload_preview` 是合法 JSON 的前缀；②dict 返回值 ⇒ 行为与今天逐字相同（回归）；③`payload=None` ⇒ 不写文件（`:1192-1193` 的既有语义）。真机回放：`p6j-research-from-zero` 派一次 `C.gaps`，读 `out/tasks/<task_id>.json` 确认 `payload_keys` 含 `candidate_gaps`/`verdict`。

**7 不做部分**：不改 `tasks` 表（它在 FC-27 禁改区，且 `payload` 本来就不进表，理由见 `:1339-1344`）；不把整份 payload 落进 `out/tasks`（那是"把产物塞进索引"，与 `:1211-1212` 的注释直接冲突）；不改 `_end_from_payload` 的终态映射（`ok=False` 分档那一大段是另一批）。

---

## §9 `src/agentflow/agent_a/core.py` —— S-03 的队列生产与消费

**1 现状**：队列的生产有 **5 处**：CLI `submit`（`cli.py:125-142`）、A 的 `_enqueue_search`（`:51-81`，过 I7 闸门）、A 的 `search_literature`（`search_literature.py:118`，入队后**同轮自带领跑** `:127-136`）、C 的 `_submit_gap_requests`（`agent_c/core.py:623`）、D 的 `research.submit_gap`（`tools/research_tools.py:272`）与 `adjudicate`（`agent_d/adjudicate.py:313-341`）、F 的 `f.step:submit_search_request`（`agent_f/core.py:671`）。消费入口只有 `run_once`（`:104-234` 的 `_claim` + `run_once.py`）与 `run`（`run.py:10-43`）。

**2 逐改动点**（原文）：

```python
# agent_a/search_literature.py:127-136（这是仓库里唯一"提交即消费"的现成实现）
for _ in range(max(1, int(self.search_max_rounds))):
    res = self.run_once()
    rounds.append(res.to_dict())
    if res.request_id:
        claimed_ids.append(str(res.request_id))
    row = self._request_row(rid)
    if row is not None and (row.get("done") or row.get("outcome")):
        break
    if res.request_id is None:
        break                      # 没有可领的了（原因见 skipped_reason）
# specs/m.py:73（当前的口径：靠主控纪律）
"**请求闭环：别人提交的检索请求要有人去做**…消费这条队列的动作是 A 的 `run_once`（无参）/ `run`…"
```

接口级伪码（两个方案，选一）：

```text
方案甲（编排层收口，不碰权限面）：
  conductor.finish(task_id, …) 末尾：
      if self.auto_consume and role != "A" and _wrote_search_requests(action):
          self.summon("A", "run_once", {}, by="conductor:auto-consume", parent_task_id=task_id)
  _wrote_search_requests(action): 读 capabilities.WRITE_SETS[role] ∋ "search_requests"，且该动作的
      影响面 = D.submit_gaps / D.adjudicate / C.gaps / F.step / CLI submit（名单封闭，写在 conductor 里）
  开关：CLI `--no-auto-consume`（缺省开启）／config `auto_consume_search: true`
方案乙（各提交方自带消费）：给 C/D/F 的提交路径各补一次 `A.run_once` 调用
  ⇒ 需要 C/D/F → A 的边（specs/*.py 的 edges + capabilities.ALLOWED_EDGES，禁改区）⇒ 不选
超时如实记：自动消费后仍 `done=False` 的请求，在交付说明与 `conductor.state` 的
  queues.search_requests.unfinished 上如实留读数（不许吞）
```

**3 调用面**：`src/`：`specs/a.py:31/40`（`run_once`/`run` 的声明）、`specs/m.py:73`（政策）、`agent_a/run.py`、`agent_a/run_once.py`、`agent_a/search_literature.py`、`conductor.py`（派活唯一入口 `:792`）、`tools/conductor_tools.py`（`conductor.summon` / `summon_many` / `conductor.stop`）。`tests/`：`test_agent_a.py`（16 处 `run_once`）、`test_agent_a_backoff.py`（9）、`test_agent_a_priority.py`（9）、`test_agent_a_backfill.py`（6）、`test_conductor.py`、`test_closing_gate.py`（`unfinished_request_rows` 那一档）。

**4 数据结构与历史数据影响**：不改表结构。历史读数：未闭环请求 agentflow 根 **7** 条（`agent-D` 3 / `agent-C` 3 / `agent-F` 1）、Incubator 根 **14** 条（`agent-F`）——这两组数是"改后应当归零"的目标读数，也是回放对比的基线。`specs/m.py` 的 A 侧工具面里 `A.search_literature` 已经存在（`specs/a.py:73-91`），所以自动消费有现成的实现可复用。

**5 可行性与改动量**：**中**。方案甲只在 `conductor.py` + `cli.py` + `host.py`（都不在禁改区）里做，但要在 `finish` 内**再发起一次 summon** ⇒ 触碰三件事：①任务树会多一层（`parent_task_id` / `depth`，43-A 已记 `depth` 全 1、血缘全空，这一改会第一次让深度真的非 1，见 E-02）；②`A.run_once` 带 `external="egress"`（`specs/a.py:36`），一次派活会真的发 HTTP、拉长时延（§45 的"加 `--no-auto-consume` 开关"正是为此）；③`_refuse` 路径不写 `task_end`（E-03），自动消费若被拒会是一条看不见的拒绝。方案乙被权限面挡住（A 的 `edges=('B',)`，`specs/a.py:187`）。

**6 风险与验证**：风险一 = 递归/风暴：M 派 D → D 提交请求 → conductor 自动派 A → A 再提交（`search_literature` 会入队）⇒ 必须只按"这一趟是否写了 `search_requests`"判，且自动消费的任务**不得**再触发自动消费（深度为 1 的封顶）。风险二 = 闸门：自动消费不能让"在途请求上限"失效（`admit_search_request` 在 `_enqueue_search` 里判，自动消费只领不提交 ⇒ 安全）。负控：①`D.submit_gaps` 成功 ⇒ 同轮 `A.run_once` 被召唤且 `search_requests` 出现 `done=True`；②`--no-auto-consume` ⇒ 不召唤且 `unfinished` 仍是 1（这就是今天的行为，是"改前必红"的对照）；③A 自己的 `run_once`/`search_literature` ⇒ 不重复自动消费（幂等）。真机回放：`p8e-fermat-shorter-proof`（`r-0004` 由 F 提交）与 `p6j-research-from-zero`（`r-0004/0005/0006` 由 C 提交）重跑，确认 `unfinished` 从 1/3 归零。

**7 不做部分**：不给 A 加边（`specs/a.py` 禁改区）；不改 `_claim` 的四态与退避（§1/§2 之外的 A 侧行为不动）；不在 `admit_search_request` 里做"提交即消费"（闸门是纯函数，理由见 `AGENTS.md` 的 auth-audit 版块）；不给 `B` 的重抽取队列做同样的自动认领（那是另一条队列，`reprocess_requests`，见 L-05g）。

---

## §10 `agent_d/{assess,consider,submit_gaps,research}.py` + `_support.analyze_gaps`（文件组） —— S-02 / S-08

**1 现状**：判据本体只有一份（`_support.py:241-330` 的 `analyze_gaps`，三条可核实判据 a/b/c；置信度在 `:331-368` 的 `evidence_confidence`），但**调用链有四处各自重算**：`assess`（`assess.py:36-43`）、`consider`（`consider.py:24-25`）、`submit_gaps`（`submit_gaps.py:28-30`）、`research`（`research.py:29-32`）。五个核心动作真机 **0 次**（§0③），而 `research`/`run_round` 真机各 45/10 次成功调用 —— 它们内部已经跑过 `trace_question` + `assess`。`D.trace_l3` 需要 `evidence` 参数（`trace_l3.py:10`），而 `evidence` 的唯一生产者是 `trace_question` 的返回值（只经 `payload_preview` 露出）⇒ **M 结构上造不出这个参数**。

**2 逐改动点**（原文）：

```python
# agent_d/consider.py:24-25 与 submit_gaps.py:28-30（同一问题算两遍）
ev = self.trace_question(qid)
verdict = self.assess(qid, ev)
# agent_d/assess.py:36-43
verdict = analyze_gaps([c["relation_id"] for c in ev.get("claims") or []], ev.get("claims") or [],
                       keywords=keywords, degree=degree, degree_threshold=self.degree_threshold,
                       concept_count=len(concepts))
# agent_d/submit_gaps.py:30-31（互补字段分别被两处读）
if not verdict["insufficient"]:
    return []
```

接口级伪码：

```text
单一来源（S-02 的"减"那半边）：
  AgentD._verdict(qid, evidence=None) -> (ev, verdict, cached: bool)
      缓存键 = (qid, 关系表 sha / 行数, 概念表行数)；同一轮内同一个 qid 只 trace+assess 一次
      consider / submit_gaps / research 全部改调它；assess 动作本身保留（它是对外入口）
  对外动作面不变（specs/d.py 的 12 个动作一个不动）
trace_l3 的可召唤性（S-02 的"接通"那半边，二选一）：
  甲：trace_l3(qid: str) —— 内部自取证据包（签名改动，specs/d.py 的 params 要改 ⇒ 禁改区）
  乙：trace_l3 保持 evidence 参数，但 evidence 允许是 {"qid_from": "<qid>"} 的引用形状（向后兼容）
采信口径（S-08，改判据而不是改措辞）：
  analyze_gaps 新增可选输入 `trusted: Sequence[str] = ()`（D 自己读过的 proof/引文关系 id）
  判据 b（度数低且无 quote_verified）增加"但 trusted 非空 ⇒ 不触发"这一支
  置信度上限：evidence_confidence 的输入从"关系行"改成"行 + trusted"，
      但**上限不抬高**（`_rank_min` 那条不许松）：采信只影响"方向"，不影响数字
```

**3 调用面**：`src/`：`agent_d/run_round.py:43/55-63`（逐问题 trace→assess→consider，`consider` 内再算一遍）、`agent_d/ingest.py`（吃 C 报告）、`agent_d/adjudicate.py`（矛盾闭环，真机 0 次）、`agent_d/_support.py:374-419`（trace 工具的降级替身）。`tests/`：`test_agent_d.py`（`assess` 2 / `submit_gaps` 3 / `trace_question` 1）、`test_agent_d_interactions.py`（`adjudicate` 10 / `write_report` 3）、`test_dup_consolidation.py`（`submit_gaps` 1 / `trace_question` 1）、`test_coverage_agent_d_demo.py`（`write_report` 5）。**`trace_l3` 在 `tests/` 是 0 处调用**（与 L-07 的"零调用零测试"一致）。

**4 数据结构与历史数据影响**：`research_questions` 表结构不动；S-08 若新增 `trusted` 的**持久化**（把"我采信了哪几条"写进行里）就是加字段 ⇒ 违反"不许加必填字段"，必须带默认值（建议改成"只进返回值与 notes，不落新字段"）。历史数据：`research_questions.json` 在 22 个工作区**都不存在**（`draft/41` §1.4）⇒ 改判据对历史读数**零影响**，这也是"S-02/S-08 无法用真机证伪"的原因。

**5 可行性与改动量**：**中**。"单一来源"是纯重构（四处改调一个私有函数 + 一个缓存），风险在缓存失效口径；"trace_l3 接通"要动 `specs/d.py` 的 param 声明（**禁改区**）⇒ 建议走方案乙（向后兼容形状，不动声明）；"采信口径"只动 `_support.py` 一个函数（不在禁改区），但**它改的是判据** ⇒ 按 `draft/45` §3 第 2 条，必须写清"从哪一趟起口径变了"。

**6 风险与验证**：风险一（S-02）= `consider` 与 `submit_gaps` 之间表被改动 ⇒ 缓存过期会给出"足够"但其实不足 ⇒ 缓存必须绑定"关系表行数 + 一个内容指纹"。风险二（S-08）= `trusted` 一旦来自 D 自己（"我看了一遍没毛病"），就**等于把"自证"重新引入**，而本节整套设计的核心是"自报不算凭据"（`evidencebits.py:118-120` 逐字）⇒ 必须给 `trusted` 定义**可复核的来源**（例如"引文 `quote_verified is True` 且被 D 在报告里逐条点名"），并在 `draft/44` 写清"这是用户点名的那条口径，与 §3.14 的位机制不冲突"。负控：①同一 qid 一轮内 `trace_question` 只调 1 次（计数可观测）；②改前必红：`analyze_gaps` 的判据 b 在 `trusted` 非空时不再触发，而**没有** `trusted` 时行为与今天逐字相同；③`_rank_min` 仍然只降不升（`test_agent_d.py` 已有类似断言）。真机回放：**做不到**（D 这五个动作真机 0 次、`research_questions` 表不存在）⇒ 只能靠单测与自检，且必须在 `draft/44` 记"本条无法用真机证伪"。

**7 不做部分**：不动 `evidence_confidence` 的评分档（≥3/≥1.5 是用户口径）；不合并 `judge.py`/`judges.py`（L-05b 是另一条）；不改 `ingest` 的三级去重与 `enabled_kinds`；不给 D 加写 `analysis_reports` 的动作（S-01 的落盘方是 C，见 §4/§11）。

---

## §11 `src/agentflow/agent_d/write_report.py` —— S-07 的报告双写

**1 现状**：`write_report(out_path=None) -> str`（`:10`）只做两件事：渲染 markdown（`:51-405`）与 `path.write_text(...)`（`:408`），随后 `self.last_report_path = path`（`:409`）并返回绝对路径。**没有任何落库**。真机：`write_report` 召唤 **45** 次全 `ok`，而 `analysis_reports` **0 行**（§0②）；盘上 `<qid>-research.md` 只有 **5** 份（同名覆盖）。`closing.py:170-175` 的 `report_files` 档就是为这件事单独设的（"D 的动作只写文件、不落表"）。

**2 逐改动点**（原文）：

```python
# agent_d/write_report.py:38-45
rows = sorted(self.store.rows("research_questions"), key=lambda r: str(r.get("question_id")))
analyses = getattr(self, "last_research", {}) or {}
run_id = rows[-1]["question_id"] if rows else "0000"
from ..tools.doc_tools import resolve_out_path
_rel, path = resolve_out_path(Path(self.store.root).resolve(), out_path,
                              f"{run_id}-research", self.reports_subdir)
path.parent.mkdir(parents=True, exist_ok=True)
# agent_d/write_report.py:407-410
text = "\n".join(lines) + "\n"
path.write_text(text, encoding="utf-8")
self.last_report_path = path
return str(path)
```

接口级伪码：

```text
write_report(): 渲染 → 写文件 → **新增** 落一行 analysis_reports：
    with self.store.tx("analysis_reports", actor=self.actor, note="d.write_report") as tx:
        rid = tx.alloc_id("report")
        row = S.AnalysisReport(report_id=rid, kind=??? , request=…, summary=…,
                               payload={"qids": [...], "confidence": {...}, "path": rel},
                               markdown_path=rel, created_at=S.now_iso(), created_by=self.actor)
        row.validate(); tx.upsert("analysis_reports", row.to_dict(), note="d.write_report")
落库前必须先拿到相对路径（resolve_out_path 已经给了 rel）——顺序与 C 的 persist 相同
kind 必须是 S.REPORT_KINDS 之一（schema.py:442 = hottest/paths/cold/gaps）
   ⇒ **本文件没有可用的 kind**：这是 S-07 的硬卡点（见 5）
返回值：保持 str（既有签名与 test_write_report_path.py 逐字依赖），落库信息进 self.last_report_row
```

**3 调用面**：`src/`：`specs/d.py:134-142`（动作声明，`side_effect="write_local"`、`returns="写出文件的路径（绝对）"`）、`conductor` 的派活、`tools/doc_tools.resolve_out_path`（`write_report.py:41`）、`closing.py:170-175`（`report_files` 读数档）。`tests/`：`test_write_report_path.py`（4 处，专测"相对路径按工作区根解析、越界拒绝"）、`test_coverage_agent_d_demo.py`（5）、`test_agent_d_interactions.py`（3）。

**4 数据结构与历史数据影响**：`analysis_reports` 见 §4。**权限面**：D 的写集是 `frozenset({"research_questions","search_requests"})`（`specs/d.py:232-235`），**不含 `analysis_reports`** ⇒ 必须改 `specs/d.py`（**禁改区 auth-audit**）+ 让 `assert_capabilities` 的 [6] 条继续成立（`write_report` 已是 `write_local`，所以轴那一侧不用新增）。副作用：`analysis_reports` 会**同时**出现在 C 与 D 的写集里 ⇒ 调度分波会把并发的 C 与 D 排成两波（判据在 `test_scheduler.py:828-839`，那里正是用 `WRITE_SETS` 相交观察分波的）。

**5 可行性与改动量**：**低（当前形态下不可行）**。两个硬卡点，各有直接证据：①`kind` 只能是 `hottest`/`paths`/`cold`/`gaps`（`schema.py:442` + `schema.AnalysisReport.validate:842-843`）——D 的研究报告**没有合法 kind**，写进去等于对一个表外 kind 撒谎，而 `closing.py:165-169` 的 `analysis_report_rows` 会把"C 的产出"与"D 的报告"混成一档；②`WRITE_SETS["D"]` 要加一张表 ⇒ 改 `specs/d.py`（禁改区）。因此 S-07 的正确落点**不是** `analysis_reports`，而是**新增一张 D 自己的报告表**（或把 `write_report` 的结果登记进 `documents`/`manuscripts`），两者都要动 `schema.py`（禁改区）。

**6 风险与验证**：风险一 = 若强行复用 `analysis_reports` 并给 `kind` 编一个表外值 ⇒ `S.AnalysisReport.validate` 当场抛（`validate` 是真判据，不是注释）；若从四个合法 kind 里挑一个（例如 `gaps`）⇒ 读数说谎。风险二 = 写入手顺序：文件与行不在同一原子边界（与 `draft/41` §3.7 的 A 侧同族问题），顺序必须是"先写文件、再落行"（照 C 的 `persist` 的理由 `_support.py:263-272`）。负控：①文件写成 ⇒ 行写成；②行写成失败（schema 拒收）⇒ 不许留下"行指向不存在文件"（顺序保证最坏是孤儿文件）；③`resolve_out_path` 越界 ⇒ 一行都不写（既有行为，回归）。真机回放：`p8-fermat-shorter-proof` / `p8g-fermat-shorter-proof`（各有 1 份报告、45 次召唤里的一部分）重跑 `write_report`，确认"文件数不变、表里出现对应行"。

**7 不做部分**：不改 `write_report` 的签名（返回值是 `str`，`test_write_report_path.py` 逐字依赖）；不把整篇 markdown 塞进 `payload`（`schema.AnalysisReport.payload` 是对象，塞全文会让表膨胀，且 `_write_task_digest` 的 2000 字节会把键集挤掉）；不改 `closing.py` 的 `report_files` 档（它是对的读数，S-07 落地后仍然要留）。

---

## §12 `src/agentflow/agent_d/core.py` —— S-09 的 `conclusion` 与数字一致性（含 S-08 的代码侧边界）

**1 现状**：`_compose`（`:1145-1159`）在 `llm is not None` 时直接采用 LLM 的三段文本（`:1152-1156`）；`_llm_refine`（`:1208-1269`）**只**对 `confidence` 做 `_rank_min` 夹取（`:1256-1264`），`conclusion` 走 `payload.setdefault("conclusion","")` 原样返回（`:1265-1269`）。确定性分支 `_deterministic_compose`（`:1160-1207`）里，措辞强度**是**由 `conf` 决定的（`:1184-1192`，低档逐字写"本节的措辞刻意停在「可能存在/尚未证实」"）。`write_report.py:296-299` 把 `res["conclusion"]` 原样写进报告。

**2 逐改动点**（原文）：

```python
# agent_d/core.py:1152-1156
if self.llm is not None:
    try:
        out = self._llm_refine(ev, verdict)
        if out is not None:
            return out["analysis"], out["conclusion"], out["suggestions"], True
# agent_d/core.py:1256-1264
forced = _rank_min(str(payload.get("confidence") or "low"), verdict.get("confidence") or "low")
if forced != payload.get("confidence"):
    self.last_tool_errors.append({"tool": "llm", "error": f"LLM 试图把置信度从 … 已强制降回 {forced}"})
payload["confidence"] = forced
```

接口级伪码（S-09 的做法：文本由等级渲染，不由模型渲染）：

```text
_llm_refine 返回前：
    payload["conclusion_body"] = payload.get("conclusion", "")     # 保留模型原话（审计用）
    payload["conclusion"] = _conclusion_for(forced, body=payload["conclusion_body"], verdict=verdict)
_conclusion_for(conf, *, body, verdict) -> str:      # 新增纯函数（唯一渲染点）
    head = _CONF_HEAD[conf]        # 与 _deterministic_compose:1184-1192 逐字相同的那三句
    tail = "（模型原话保留在 conclusion_body；本节措辞由置信度档位渲染）" —— 只在 body 与 head 明显不一致时加
    return head + ("\n\n" + body if body else "")
另外两处一致化：
    ①research.py:72 的 result["confidence"] 与 result["conclusion"] 都取自同一 verdict ⇒ 已一致，不动
    ②write_report.py:296-299 不动（它只写 conclusion；一致性由上游保证）
```

**3 调用面**：`src/`：`agent_d/research.py:38`（`_compose` 的唯一生产调用点）、`agent_d/core.py:1154`、`:1250-1255`（解析失败退回确定性结论）。`tests/`：`test_agent_d.py`、`test_coverage_agent_d_demo.py`、`tests/test_semantic_review.py`（LLM 缝的替身写法可照抄：`_Model` 返回合规 JSON）。真机：**D 从未接 LLM**（45 次 `research` 全走 `_deterministic_compose`）⇒ 这条改动真机上**看不到变化**。

**4 数据结构与历史数据影响**：`conclusion` 只在返回值与 markdown 里，不落表（`research.py:44-62` 只落 `evidence_lit_ids`/`status`/`notes`）⇒ 零历史影响。新增的 `conclusion_body` 是返回值里的新键（放宽，不是加必填字段）。

**5 可行性与改动量**：**高可行、改动量小**（`conductor.py`/`agent_d/core.py` 都不在禁改区；一个 `_CONF_HEAD` 常量 + 一个纯函数 + `_llm_refine` 末尾两行）。真正的工作量在**负控**：需要一个"模型写出高置信度口吻、数字是 low"的替身，断言最终 `conclusion` 以"置信度：低"开头。

**6 风险与验证**：风险一 = 把模型的原话整段替换掉 ⇒ 丢信息 ⇒ 必须保留 `conclusion_body`（并让 `write_report` 有一处能读它，或明确"原话只进返回值"）。风险二 = 与 `_deterministic_compose` 的措辞分家（两处各写一套"低/中/高"的话）⇒ 必须抽成同一份常量，负控要断言两个分支的低档结论文本**逐字相同**（这正是 `draft/45` §3 第 3 条要防的"两份判据必然分家"）。负控：①LLM 报 high 而确定性是 low ⇒ 文本以"置信度：低"开头且 `confidence=="low"`；②LLM 解析失败（`_parse_json_block` 返回 None）⇒ 走确定性结论（既有行为，回归）；③`llm=None` ⇒ 输出与今天逐字相同（回归，可用现有 `test_agent_d.py` 的固定串做快照）。真机回放：**做不到**（未接 LLM）⇒ 在 `draft/44` 写明"本条只能用替身模型验证"。

**7 不做部分**：不动 `_deterministic_compose` 的三句正文（它们是"低就是低"的唯一落点）；不动 `_rank_min`（S-08 的"只降不升"是它的职责）；不给 `conclusion` 加"必须包含某个词"的机械判据（那是把措辞判据做成形式主义）；不改 `write_report` 的结论小节结构（九节/五段的结构属 closing 读数，另一批）。

---

## §13 `agent_h/{core,verify_fixes}.py` + `tools/review_tools.py`（文件组） —— R-04 的 H 侧

**1 现状**：语义判据（`judges.semantic_judge_for`）**只**被 `review.review_document` 拿到：装配期 `_WRITE_TOOL_FUNCTIONS` 里 `_review_review_document_tool` 的注入名含 `semantic_judge`（`review_tools.py:1738`），而 `_review_verify_fixes_tool` 的注入名**只有** `('_not_wired','store','actor')`（`:1739`）。工具层 `verify_fixes` 复扫时调 `scan_document(doc, dependencies=deps)`（`:1215`）—— **不传 `semantic_judge`**。于是上一轮由语义判据落下的 `overclaim`（warning 级，`scan_document:600-619`）在复审里**不可能复现** ⇒ `key not in current` ⇒ 进 `resolved`（`:1237-1238`）⇒ `_apply_finding_status` 写 `status="fixed"`（`:1259-1266`）。`AgentH.verify_fixes`（`agent_h/verify_fixes.py:31-43`）是从角色层到工具层的纯转发。

**2 逐改动点**（原文）：

```python
# tools/review_tools.py:1737-1741
_WRITE_TOOL_FUNCTIONS: tuple[tuple[Callable[..., Any], tuple[str, ...]], ...] = (
    (_review_review_document_tool, ('_not_wired', 'store', 'actor', 'semantic_judge')),
    (_review_verify_fixes_tool, ('_not_wired', 'store', 'actor')),
    (_review_report_tool, ('_not_wired', 'store', 'actor', 'semantic_judge')),
)
# tools/review_tools.py:1213-1216
doc = _doc_of(store, doc_id)
deps, dep_checked = _resolve_deps(store, doc_id, dependencies)
scan = scan_document(doc, dependencies=deps)
current = {_dedup_key(f): f for f in scan["findings"]}
```

接口级伪码：

```text
tools/review_tools.py：
  _review_verify_fixes_tool(_not_wired, store, actor, semantic_judge, **kw)
  _WRITE_TOOL_FUNCTIONS 的 verify_fixes 那一项注入名加 'semantic_judge'
  verify_fixes(store, doc_id, *, round_no, dependencies, max_review_rounds, actor, semantic_judge=None)
      scan = scan_document(doc, dependencies=deps, semantic_judge=semantic_judge)   # 与 review_document 同口径
  三态（缺一不可）：
      ①判据没接线（None）⇒ 这一维"没查"：**不许**把上一轮的语义 finding 判成 resolved
          处置：这类 finding 进 still_open 且标 source="not_rechecked"（新增取值），
          并在 reason 里逐字写"语义判据这次没跑 ⇒ 不许当已修好"
      ②判据跑了且不再复现 ⇒ 才允许 resolved ⇒ fixed
      ③判据跑了但答 unknown / 抛异常（checker_errors）⇒ 同样不许 resolved（照 scan_document:566-595 的处置）
agent_h/verify_fixes.py：签名加 semantic_judge: Any = _UNSPECIFIED（或让 self 的装配期注册表带它）
  角色层不给参数时，由 self.writers 的 partial 注入（`semantic_judge` 已在 register 里绑定，
  见 review_tools.py:1774）—— 所以角色层可能不需要改签名
claims_hash 差分（可选，45 号施工单提到）：只对"改稿后新增/修改的断言"重跑语义判据
```

**3 调用面**：`src/`：`agent_h/core.py:74-75`（`RV.register(self.writers, …, semantic_judge=judge)`，`:69-73` 只在 `llm is not None` 时建判据）、`agent_h/core.py:83-94`（`_H_WRITABLE_TOOLS` 装配期断言）、`agent_h/review.py:32`、`agent_h/verify_fixes.py:38`、`agent_h/review_report.py`、`agent_h/list_findings.py`、`agent_f/core.py:396`（F 的 `judge_json`，另一条缝）。`tests/`：`test_agent_h.py`（7 处 `verify_fixes`：`:474` 真修好、`:524` 没修、`:542` 终止性、`:558` 谎报重开、`:589` 依赖清单）、`test_coverage_agent_h.py`（2，转发层）、`test_core_audit_efgh.py:724`、`test_semantic_review.py`（全 8 例，**没有一例覆盖 `verify_fixes` 的语义维**）、`test_r4_readonly_exceptions_tables.py:53-247`（`review.verify_fixes` 的写集逐工具登记）。

**4 数据结构与历史数据影响**：`review_findings.status` 的取值不动；新增 `still_open` 项的 `source="not_rechecked"` 是**返回值**取值（不落表）。历史影响面：真机 `review_findings` agentflow 根 **13 行**（全 `overclaim`，warning 级）、Incubator 根 **1771 行**（`scope_drift` 1680 + `dangling_dep` 91）。**这 13 行正是本条要保护的对象**：改后复审若没接判据，它们**不再**能被自动置 `fixed`（改前它们可以）⇒ 这是一次"历史行状态不再被静默改写"的行为变更，`draft/44` 要写清。

**5 可行性与改动量**：**高可行**。改动 = `_WRITE_TOOL_FUNCTIONS` 一项 + 工具体签名一个注入参数 + `verify_fixes` 签名一个可选参数 + `scan_document` 调用加一个实参 + 一处三分支判定（"没查"这一支是新增语义，必须显式做，否则等于没修）。`tools/review_tools.py` **不在 `.noai-paths`**（逐条核对过清单），但它在 **auth-audit 的相邻面**：`_H_WRITABLE_TOOLS` 是从 `READONLY_CALL_EXCEPTIONS` 派生的（`capabilities.py:1919-1925` 的断言），**只要不改工具名与写集**就不会碰权限面。`TOOL_WRITE_SETS["review.verify_fixes"] == ["documents","review_findings"]`（`test_r4_readonly_exceptions_tables.py:247`）—— 本改动不改写集。

**6 风险与验证**：风险一 = 让 `verify_fixes` 变得"永远修不好"（判据没接线时把 warning 也留在 still_open）⇒ 会把 `accepted_with_warnings` 的正常收尾卡住。处置：只对**上一轮由语义判据产生的 finding**（`kind="overclaim"` 且 evidence 里带"语义判据（…）"字样）应用"没查就不算修好"，其余仍按现口径；并给 `overclaim` 的**机械**那一支留一条路（`OVERCLAIM_MARKERS` 命中的 finding 与语义的那一支必须能分开——判据在 `evidence` 串里，`review_tools.py:605-609` 逐字给了"语义判据（<judge>）判定结论强于引文"这个前缀）。风险二 = 复审变慢/变贵（每条断言一次模型调用）⇒ 用 `claims_hash` 差分，只跑改动过的断言。负控（**这是 R-04 的核心，必须每条都能红**）：①接判据 + 模型仍判 `overclaimed` ⇒ finding **不许** `resolved`、`status` 保持 `open`/`fixed`→重开（今天的反例是它会变 `fixed`）；②不接判据（`semantic_judge=None`）⇒ 上一轮的语义 finding 进 `still_open` 且 `source="not_rechecked"`、verdict **不是** `accepted`；③`llm=None` 的默认路径 ⇒ `review` 那一维 `checked=False`（`scan_document:547-555`），复审同样"没查就是没查"；④正控：G 真的把那条断言改弱了 ⇒ 语义判据答 `within_evidence` ⇒ 才允许 `fixed`。真机回放：`p8e-fermat-shorter-proof` / `p8g-fermat-shorter-proof`（有 `H.review` 与改稿的历史）重跑 `review → verify_fixes`，对比改前/改后 `resolved` 里 `overclaim` 的条数（改前应能复现 R-04 探针的 `resolved=[overclaim]`，改后应为 0）。

**7 不做部分**：不动 `scan_document` 的机械判据与三态排序（`:528-625`）；不动 `_apply_finding_status` 的重开逻辑（`:1267-1282`）与 `verdict/target_status` 映射（`:1287-1304`）；不动 `R-59` 的签名门（`:1305` 起）；不改 `agent_h/core.py:48-55` 与 `:83-94` 两条装配期断言；不把语义判据升到 error 级（`review_tools.py:543-546` 逐字说"要不要升到 error 是口径问题，属 FC-27 的 eval-criteria 类 ⇒ 留给人裁"）。

---

## §14 汇总：可行性 / 必须人审的禁改区 / 真机可证伪性

| 条目 | 施工单元 | 可行性 | 禁改区（需 2 名人审） | 真机可证伪 |
|---|---|---|---|---|
| D-2 | §1 `agent_b/core.py` + §2 `agent_b/run_once.py` | 高 | 无 | 探针可证（已有） |
| EE-12 | §3 `agent_b/register_statement.py`（补 `bits=`） | 高 | `specs/b.py`（参数表） | 可（`statements.bits` 首次非 0） |
| EE-07 | §3（`evidence_kind` 派生） | 中高 | `specs/b.py`；口径变更要在册 | 可（逐行比对 `evidence_kind`） |
| S-01 | §4 §5 §6 §8 | 中 | `schema.py:442 REPORT_KINDS`（若要覆盖 9 个动作） | 可（`analysis_reports` 首次非 0） |
| S-03 | §9 `agent_a/core.py` + `conductor.py` | 中 | `specs/*.edges`（若走方案乙，已否） | 可（`unfinished` 归零） |
| S-02 | §10 | 中 | `specs/d.py`（`trace_l3` 签名，若走方案甲） | **不可**（表不存在、动作 0 次） |
| S-07 | §11 | **低（当前形态不可行）** | `specs/d.py` WRITE_SETS + `schema.py`（kind/新表） | 部分（文件数 vs 表行数） |
| S-08 | §10 | 中 | 无（判据在 `_support.py`） | **不可**（同上） |
| S-09 | §12 | 高 | 无 | **不可**（未接 LLM，只能替身） |
| R-04-H | §13 | 高 | 无（`review_tools.py` 不在清单） | 可（13 行 `overclaim` 的 `resolved` 数） |

三条必须写进 `draft/44` 的口径分界：①`analysis_reports` 从 S-01 落地那一趟起**才有产出方**；②`statements.evidence_kind` 从 EE-07 落地那一趟起由 `bits` 派生（历史行的读数会变，`bits={}` 的旧行仍按"五位全空"读）；③`review_findings` 的语义级 `overclaim` 从 R-04-H 落地那一趟起**不再**能被自动置 `fixed`。

两处"施工单需要改口径"的地方（本报告的证据都指向这里）：`draft/45` §1.4 把 S-07 写成"`write_report` 也落台账"，但 `analysis_reports` 的 `kind` 词表（`schema.py:442`）里没有 D 的研究报告种类，且 `WRITE_SETS["D"]` 不含该表 ⇒ 这条路在当前结构下**不可行**，应改判为"新增 D 自己的报告落点"或"随 L-01/L-03 一起让 D 的报告走 `documents`"；`draft/45` §1.4 把 S-01 写成"落盘形态一变，D.ingest 与读数都要跟着改"，但 `D.ingest` 的 `enabled_kinds` 默认等于 `S.REPORT_KINDS`（`agent_d/core.py:66`）⇒ 只有那四个 kind 会被 D 吸收，其余五个动作落盘也不会进 D，这一点要在下一批的施工单里写明。
