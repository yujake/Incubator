"""`python -m agentflow.agent_a` 的自检（2026-10-26 从 `core.py` 搬出来）。

为什么单独一个文件：自检既不是动作也不是装配 —— 它是"这个角色今天还能不能跑"的一次
现场读数。搬出来的直接原因是机器读数（不是口味）：`src_files_gt800_lines` 的基线是 69，
`core.py` 本来 749 行，Q16 之后重写自检那一段把它撑到 866 行，于是基线被越过 1 格
（`tests/test_repo_survey_does_not_get_worse.py`）。放回独立的 `selftest.py` 之后
`core.py` 只剩装配，两份文件都在 800 行以下。

口径（2026-10-26，Q16 之后）写在函数 docstring 里：自动链路只暂存、入库必须逐条判过。
"""
from __future__ import annotations

from ._support import Path, S, Store, X, make_lease
from .core import AgentA


def _selftest() -> int:
    """`python -m agentflow.agent_a` 的自检：跑通主路径并断言关键不变量。

    为什么必须存在（它修的是一个静默空成功）：`scripts/release_check.py` 第 2 项逐个
    `python -m agentflow.agent_<role>` 并看退出码，而 `agent_a` 曾没有 `__main__` 块 ⇒ 那条命令输出
    0 行、退出码 0，旧判据把它记成"自检通过"，其实什么都没检查（`DEVELOPMENT.md` §10-D5 与附录 C
    第 4 条都记着这件事；现在 `release_check.item_selftests` 用 `has_selftest` 判据把它报成 `unknown`）。

    覆盖范围（2026-10-26 按 Q16 之后的口径重写，全部离线、确定性）：I7 优先级；自动链路
    "只暂存、入库 0 条 + 待裁 1 条"与提交闸的两个方向（整批拒 / 逐条放行）；同一篇被第二问
    再检索到不新建行；队列空 / 全被租 / 全在退避 / 全被放弃四态；补下载成功与失败（下载证据
    `path` + `sha256` 随行落库）；下载关闭不伪装成功；搜索失败不置 done 且退避租约被遵守
    （"写了"必须升级成"写了且被读"）；空工作区上 `run()` 与 `run_once()` 都不抛。

    空表纪律：这一段里每一处取"第一行"都走 `_first`（空表给空 dict），绝不对可能为空的列表
    直接下标 —— 改前那句 `lits[0]` 让 `python -m agentflow.agent_a` 以 IndexError 崩、退出码 1。

    退出码：`0` = 全部通过；`1` = 有失败项。
    """
    import hashlib
    import shutil
    import tempfile
    from types import SimpleNamespace

    from .. import litstage as LS
    from ..fetch import FetchResult

    checks: list[tuple[str, bool]] = []

    def check(label: str, cond: bool, extra: str = "") -> None:
        checks.append((label, bool(cond)))
        print(f"    [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    class _StubProvider:
        """确定性替身：不联网。`error` 非空时模拟 provider 抛异常。"""

        name = "selftest-stub"

        def __init__(self, candidates=(), error: BaseException | None = None):
            self.candidates = list(candidates)
            self.error = error

        def search(self, topic, mode, description, limit):
            if self.error is not None:
                raise self.error
            return list(self.candidates)

    class _Downloader:
        """落一个真实文件并给出真实 sha256（不联网）——让"下载证据"这条断言有意义。

        `calls` 记"下载器被真调了几次"：主路径那一格要断言的是"没判过的候选根本没去
        下载"，而 `downloaded == 0` 这个计数分不清"没下载"与"下载了但失败"。
        """

        def __init__(self) -> None:
            self.calls: list[str] = []

        def download(self, url, dest_dir, hint):
            self.calls.append(str(url))
            p = Path(dest_dir) / f"{hint or 'file'}.txt"
            p.write_text("selftest payload", encoding="utf-8")
            data = p.read_bytes()
            return FetchResult(ok=True, path=str(p), http_status=200, bytes=len(data),
                               sha256=hashlib.sha256(data).hexdigest(), error=None)

    class _FailDownloader:
        def download(self, url, dest_dir, hint):
            # `kind` 是 `FetchResult` 的受控失败档（`F-6`）：失败的下载必须
            # 说得出"为什么"是受控词表里的一档，否则失败原因无法按轴统计。
            return FetchResult(ok=False, kind="http_500", path=None, http_status=500,
                               bytes=0, sha256=None, error="selftest boom")

    def _cand(**kw) -> SimpleNamespace:
        """鸭子类型的候选。刻意不 import `providers.Candidate`：这里要验证的是
        `AgentA` 对候选的用法（全是 `getattr` + 默认值），不该被 provider 层的
        字段增删牵着走；用最窄的对象反而把那份契约钉得更死。"""
        base = dict(title="Selftest literature", doi="10.9999/selftest", year=2026,
                    pdf_url="http://example.invalid/selftest.pdf")
        base.update(kw)
        return SimpleNamespace(**base)

    def _add_request(st: Store, rid: str, *, topic: str, priority: str, attempts: int = 0,
                     claimed_by: str | None = None, lease_until: str | None = None) -> None:
        with st.tx("search_requests", actor="selftest") as tx:
            row = S.SearchRequest(request_id=rid, timestamp=S.now_iso(), topic=topic, mode="broad",
                                  content_description="", done=False, submitted_by="selftest",
                                  priority=priority, attempts=attempts,
                                  claimed_by=claimed_by, lease_until=lease_until)
            row.validate()
            tx.upsert("search_requests", row.to_dict(), note="selftest")

    def _drain(st: Store) -> None:
        """把队列清空（每段断言都在一个已知的队列上做，避免段落之间互相干扰）。"""
        with st.tx("search_requests", actor="selftest") as tx:
            for r in tx.rows("search_requests"):
                if not r.get("done"):
                    r["done"] = True
                    r["outcome"] = "no_results"
                    r["claimed_by"] = None
                    r["lease_until"] = None
                    tx.upsert("search_requests", r, note="selftest_drain")

    def _req(st: Store, rid: str) -> dict:
        return next(r for r in st.rows("search_requests") if r.get("request_id") == rid)

    def _first(rows: list[dict]) -> dict:
        """空表上的第一个读法：没有行就给一个空 dict，绝不直接下标。

        为什么要有它（2026-10-26）：Q16 之后自动链路一条都入不了库，`literature`
        在自检里是常态空表。改前自检写的是 `lits[0].get("download")` —— 空列表当非空
        用 ⇒ `IndexError: list index out of range`，`python -m agentflow.agent_a`
        退出码 1，而 `scripts/release_check.py` 第 2 项与 `docs/ROLE-SPECS.md`
        都把"退出码 0"写成契约。判据入口读空表这件事本身也要有判据（"空工作区"那两格）。
        """
        return rows[0] if rows else {}

    def _seed_literature(st: Store, *, title: str, doi: str, year: int) -> str:
        """预先落一行"已登记但没有全文"的文献，返回它的 `lit_id`。

        为什么自检要自己造这一行：Q16 之后自动链路只暂存、不入库（候选没有
        relevance 就进不了库），所以"给已登记的行补上字节"（`draft/30` §T0-10 的补
        下载）这条路的前置状态只能显式造出来。这一段同时把"下载证据随行落库"
        （`path` + `download.sha256`）留在读数里 —— 它原来挂在"新建行"那一支，
        现在挂在唯一还走得通的下载分支上。
        """
        with st.tx("literature", actor="selftest") as tx:
            lit_id = tx.alloc_id("lit")
            row = S.Literature(
                lit_id=lit_id, title=title, type="J", summary="", path=None,
                processed=False,  # 置 true 是 B 的职责
                source_request_ids=["r-seed"], dedup_key=f"doi:{doi}", doi=doi,
                year=year, authors=[], venue="", language="en", added_at=S.now_iso(),
                download={"status": "skipped", "error": "no_pdf_url",
                          "http_status": None, "bytes": 0, "sha256": None},
            )
            row.validate()
            tx.upsert("literature", row.to_dict(), note="selftest_seed")
            return lit_id

    try:
        root = Path(tempfile.mkdtemp(prefix="agentflow_agent_a_selftest_"))
    except OSError:  # pragma: no cover - 沙箱拒绝系统临时目录时退到仓库内
        root = Path(__file__).resolve().parents[2] / "demo" / "agent_a_selftest"
        shutil.rmtree(root, ignore_errors=True)
    try:
        print("[agent_a 自检] 离线、确定性；工作区：", root)
        st = Store(root)
        st.init(force=True)
        cfg = {"download": True, "lease_seconds": 900, "max_attempts": 3, "retry_backoff_seconds": 60}

        # ---- 1) I7：取任务只看 interactions 的排序，high 先于更早提交的 low
        _add_request(st, "r-0001", topic="low topic", priority="low")
        _add_request(st, "r-0002", topic="high topic", priority="high")
        downloader_a = _Downloader()
        a = AgentA(st, providers=[_StubProvider([_cand()])], downloader=downloader_a, config=cfg)
        first = a.run_once()
        check("I7：先取 high（r-0002）而不是先提交的 low（r-0001）",
              first.request_id == "r-0002", f"got={first.request_id}")
        check("I7：优先级与序号被如实暴露（判定'为什么它先被取走'靠次序而非字符串）",
              first.priority == "high" and first.priority_rank == X.priority_rank("high"))
        # 主路径（2026-10-26 Q16 之后）：自动链路只暂存，一条都不入库。
        # 口径的真身在 `run_once.py` 的 Q16 注释与 `litstage.admission_plan`：候选没有
        # relevance（"为什么与本次检索相关"）就进不了库，而自动链路读不懂这一句
        # ⇒ 入库 0 条、候选停在待裁列表。改：这一段的读数跟着口径换（不是把判据放松）。
        lits = st.rows("literature")
        cands = st.rows("lit_candidates")
        first_cand = _first(cands)
        check("主路径：一条都不入库（没有 relevance 的候选不许进 literature）",
              first.registered == 0 and len(lits) == 0, f"registered={first.registered}")
        check("主路径：候选真的进了待裁列表（注册即待裁，不是被丢掉）",
              len(cands) == 1 and first_cand.get("status") == "pending"
              and LS.judged_state(first_cand) == "pending", f"candidates={len(cands)}")
        check("主路径：请求以 no_results 收尾，且读数里写明'待裁 1 条'",
              first.outcome == "no_results"
              and "待裁 1 条" in str(_req(st, "r-0002")["last_error"]),
              f"outcome={first.outcome}")
        check("主路径：没判过的候选根本没去下载（下载器一次都没被调用）",
              first.downloaded == 0 and first.download_failed == 0 and downloader_a.calls == [],
              f"downloaded={first.downloaded} calls={len(downloader_a.calls)}")
        check("主路径：请求终局带空 result_lit_ids 且释放租约",
              _req(st, "r-0002")["result_lit_ids"] == []
              and _req(st, "r-0002")["claimed_by"] is None)

        # ---- 1b) 提交闸的两个方向：整批提交被拦 / 逐条判决那条路放行。
        # 只断言"被拦"的话，"闸永远关着"也能让这一格绿；两向一起才是判据。
        slot = str(first_cand.get("slot") or "")
        check("待裁列表里拿得到一条的槽位号（下面两格要拿它过闸）", bool(slot), f"slot={slot!r}")
        if slot:
            gate_red = LS.admission_plan(st, request_id="r-0002", slots=[slot],
                                         require_judged=True)
            check("提交闸：还有一条没判 ⇒ 整批一条都不许入库（kind=undecided_items）",
                  gate_red.get("ok") is False
                  and gate_red.get("kind") == "undecided_items"
                  and gate_red.get("whole_call_refused") is True)
            with st.tx("lit_candidates", actor="selftest") as tx:
                for row in tx.rows("lit_candidates"):
                    if str(row.get("slot") or "") == slot:
                        row["relevance"] = "自检替身：逐条读过的记录 —— 这一条与本次检索同族"
                        tx.upsert("lit_candidates", row, note="selftest_relevance")
            gate_green = LS.admission_plan(st, request_id="r-0002", slots=[slot])
            check("提交闸：补上 relevance 之后逐条判决那条路放行（闸不是永远关着的）",
                  gate_green.get("ok") is True
                  and [i["slot"] for i in gate_green.get("admitted") or []] == [slot],
                  f"kind={gate_green.get('kind')}")
        else:
            check("提交闸：还有一条没判 ⇒ 整批一条都不许入库（kind=undecided_items）",
                  False, "没有槽位号 ⇒ 这一段没有对象")
            check("提交闸：补上 relevance 之后逐条判决那条路放行（闸不是永远关着的）",
                  False, "没有槽位号 ⇒ 这一段没有对象")

        # ---- 2) 幂等（Q16 口径）：同一篇被第二问再检索到 ⇒ 不新建文献行，
        # 而是多一条待裁 —— "同一篇不许有两个 lit_id"这条不变量没变，变的是
        # "重复命中"落在待裁列表上（改前落在 literature 的 duplicated 计数上）。
        second = a.run_once()
        check("幂等：第二问再检索到同一篇 ⇒ literature 仍是空的（没有静默重复登记）",
              second.request_id == "r-0001" and second.registered == 0
              and len(st.rows("literature")) == 0, f"registered={second.registered}")
        check("幂等：同一篇累积成两条待裁，而不是覆盖掉前一条",
              len(st.rows("lit_candidates")) == 2
              and {str(r.get("title")) for r in st.rows("lit_candidates")}
              == {"Selftest literature"}, f"candidates={len(st.rows('lit_candidates'))}")

        # ---- 3) 队列空 = 三态里的"没做"，理由必须明确
        third = a.run_once()
        check("队列空：skipped_reason=no_pending_request（不是静默的成功）",
              third.request_id is None and third.skipped_reason == "no_pending_request")

        # ---- 4) 三态可区分：'被别人持着' ≠ '队列空了' ≠ '全被放弃'
        _drain(st)
        _add_request(st, "r-0004", topic="exhausted", priority="low", attempts=3)
        _add_request(st, "r-0007", topic="held by another A", priority="high",
                     claimed_by="agent-A-other", lease_until=make_lease(900))
        c = AgentA(st, providers=[_StubProvider([_cand(title="never used")])], downloader=_Downloader(), config=cfg)
        fourth = c.run_once()
        check("超过 max_attempts ⇒ 显式放弃并计入 gave_up（不是静默什么都不做）",
              fourth.gave_up == 1 and fourth.request_id is None and fourth.skipped_reason == "no_claimable_request")
        check("放弃是可读的终局：done=true + outcome=gave_up",
              _req(st, "r-0004")["done"] is True and _req(st, "r-0004")["outcome"] == "gave_up")
        check("'被有效租约占着'单独计数，且与'队列空了'是不同的 skipped_reason",
              fourth.skipped_lease_active == 1 and fourth.skipped_reason != "no_pending_request")
        check("被有效租约占着的行不会被抢走（claimed_by 原样保留）",
              _req(st, "r-0007")["claimed_by"] == "agent-A-other" and _req(st, "r-0007")["done"] is False)

        # ---- 5) 补下载：库里已登记但没有全文的那一篇，这一轮把字节补上。
        # 为什么换到这一支来验下载链路（2026-10-26 Q16）：新建行那一支要求候选先被判过，
        # 而自检里没有模型去写 relevance；补下载是 `run_once` 里唯一还走得到下载的入口
        # （`draft/30` §T0-10），"下载证据随行落库"这条不变量挂在它上面。
        _seed_literature(st, title="Backfill paper", doi="10.9999/backfill", year=2026)
        _add_request(st, "r-0005", topic="backfill me", priority="medium")
        d = AgentA(st, providers=[_StubProvider([_cand(title="Backfill paper", doi="10.9999/backfill")])],
                   downloader=_Downloader(), config=cfg)
        dl_back = d.run_once()
        check("补下载：命中既有的那一行（duplicated=1）、把字节补上（downloaded=1）、不新建行",
              dl_back.duplicated == 1 and dl_back.downloaded == 1
              and len(st.rows("literature")) == 1,
              f"dup={dl_back.duplicated} dl={dl_back.downloaded}")
        row5 = _first([r for r in st.rows("literature") if r.get("title") == "Backfill paper"])
        check("补下载：path 回填、processed 仍是 False（置 true 是 B 的职责）、sha256 随行落库",
              bool(row5.get("path")) and row5.get("processed") is False
              and bool((row5.get("download") or {}).get("sha256"))
              and (row5.get("download") or {}).get("backfilled") is True)

        # ---- 6) 补下载失败：单独计数，证据不丢（path 仍为空、status=failed）
        _seed_literature(st, title="Unreachable paper", doi="10.9999/unreachable", year=2026)
        _add_request(st, "r-0006", topic="download fails", priority="medium")
        f = AgentA(st, providers=[_StubProvider([_cand(title="Unreachable paper", doi="10.9999/unreachable")])],
                   downloader=_FailDownloader(), config=cfg)
        dl_fail = f.run_once()
        check("补下载失败：download_failed=1（'知道有这篇但拿不到'本身是结果，不是整轮失败）",
              dl_fail.download_failed == 1 and dl_fail.downloaded == 0,
              f"failed={dl_fail.download_failed}")
        row6 = _first([r for r in st.rows("literature") if r.get("title") == "Unreachable paper"])
        check("补下载失败：path 仍为空且 download.status=failed（证据不丢）",
              row6.get("path") is None
              and (row6.get("download") or {}).get("status") == "failed")

        # ---- 7) 下载被关闭时不得伪装成"下载成功"
        _seed_literature(st, title="Disabled download", doi="10.9999/disabled", year=2026)
        _add_request(st, "r-0008", topic="download disabled", priority="medium")
        e = AgentA(st, providers=[_StubProvider([_cand(title="Disabled download", doi="10.9999/disabled")])],
                   downloader=_Downloader(), config={**cfg, "download": False})
        off = e.run_once()
        row7 = _first([r for r in st.rows("literature") if r.get("title") == "Disabled download"])
        check("download=False：downloaded 计数为 0，行内也没被写成 ok（不许伪装成下到了）",
              off.downloaded == 0 and (row7.get("download") or {}).get("status") != "ok"
              and row7.get("path") is None)

        # ---- 7b) 只剩"被别人占着"的行时，run() 既不停摆也不谎报"队列空"
        summary = e.run(max_requests=None)
        check("run()：只剩被租约占用的行 ⇒ skipped_reason=pending_requests_all_leased",
              summary["skipped_reason"] == "pending_requests_all_leased",
              f"got={summary['skipped_reason']}")

        # ---- 8) 搜索失败：不置 done，留给租约重试（一次网络抖动不该判死请求）
        _drain(st)
        _add_request(st, "r-0003", topic="network down", priority="high")
        b = AgentA(st, providers=[_StubProvider(error=RuntimeError("selftest network down"))],
                   downloader=_Downloader(), config=cfg)
        failed = b.run_once()
        r3 = _req(st, "r-0003")
        check("搜索失败：请求没有被置 done，且 last_error 留下了原因",
              failed.outcome is None and r3["done"] is False and "network down" in str(r3["last_error"]))
        check("搜索失败：写了退避租约并把 claimed_by 置空（可重试，且在排序里靠后）",
              bool(r3["lease_until"]) and r3["claimed_by"] is None)

        # ---- 8b) "写了"不等于"被遵守"：再领一次必须领不到它。
        # 这是本次修复真正的验收判据。旧自检只断言了"租约被写入"
        # （`bool(r3["lease_until"])`），而一个断言"写入了"的测试无法发现
        # "没有任何地方读它"：`_claim` 的跳过判据曾经额外要求 `claimed_by` 非空，
        # 而失败分支恰好把 `claimed_by` 置成了 None ⇒ 那条租约永远不会被读到，
        # 同一个 A 实例下一轮立刻再领同一条、连打同一个 API。所以这里必须再跑一次
        # `_claim()` 并且断言它没领到（attempts 不增，是最硬的那条证据 ——
        # attempts 只在 `_claim` 里 +1）。
        re_claim = b._claim()
        r3_after = _req(st, "r-0003")
        check("搜索失败后的退避租约被遵守：再领一次领不到它，attempts 不增",
              re_claim.request is None and r3_after["attempts"] == 1,
              f"claimed={re_claim.request and re_claim.request.get('request_id')} "
              f"attempts={r3_after['attempts']}")
        check("退避中与'被别人持着'分开：reason=pending_requests_all_in_backoff 且计数进 backoff",
              re_claim.skipped_reason == "pending_requests_all_in_backoff"
              and re_claim.skipped_lease_backoff == 1 and re_claim.skipped_lease_active == 0,
              f"reason={re_claim.skipped_reason} backoff={re_claim.skipped_lease_backoff} "
              f"active={re_claim.skipped_lease_active}")

        # ---- 9) 空工作区：run() 与 run_once() 都立刻停下，且不许对空表取下标。
        # 这一格守的正是改前那次崩溃的形态：`literature` 是空表时，自检曾经写
        # `lits[0]` ⇒ IndexError ⇒ `python -m agentflow.agent_a` 退出码 1。
        st_empty = Store(Path(root) / "empty")
        st_empty.init()
        none_agent = AgentA(st_empty, providers=[], downloader=None, config=cfg)
        empty_summary = none_agent.run(max_requests=None)
        check("空库 run()：skipped_reason=no_pending_request 且 processed 为 0",
              empty_summary["skipped_reason"] == "no_pending_request" and empty_summary["processed"] == 0)
        empty_once = none_agent.run_once()
        check("空库 run_once()：request_id=None、文献表为空也不抛（这条守的是空表下标）",
              empty_once.request_id is None
              and empty_once.skipped_reason == "no_pending_request"
              and st_empty.rows("literature") == [])
    except Exception as e:  # noqa: BLE001
        # 自检自己炸了也必须报 FAIL，不许把 traceback 当成结论往外抛：
        # 检查器的"没跑成"与"跑成了、发现缺陷"是两件事，但两者都不是"通过"。
        # 没有这一层，一处异常会让退出码变成 1（看起来是失败）却既没有失败项清单、
        # 也看不出是哪一条挂的 —— 与"release_check 把 traceback 记成 unknown"同族。
        checks.append((f"自检执行中断：{type(e).__name__}: {e}", False))
        print(f"    [FAIL] 自检执行中断：{type(e).__name__}: {e}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    bad = [label for label, ok in checks if not ok]
    print(f"[agent_a 自检] {len(checks) - len(bad)}/{len(checks)} 项通过")
    if bad:
        print("[agent_a 自检] 失败项：")
        for label in bad:
            print(f"  - {label}")
        return 1
    return 0
