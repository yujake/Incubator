"""D-2：B 的租约语义与 A 对齐；租约/尝试阈值住在角色段里（不是一个死块）。

## 这一批修的是什么（两处，形态都是"写了、但没人认"）

(a) 租约语义不对齐。`AgentB._claim` 的跳过判据原先要求 `claimed_by` 非空，而失败分支
    写下的退避租约恰恰是 `claimed_by=None` + 未来的 `lease_until` ⇒ 那条租约写了等于
    没写：失败的行当轮就能被同一次调用重领，`mine_attempts` 在一次调用里烧到上限并把
    它判死。读数（`temp/_probe_b_claim.py`，修复前）：4 次连续 `run_once` 读到
    `mine_attempts` 0→3、第 4 次 `processed=True`；A 在同序列停在 1。

(b) 阈值住在一段死配置里。`config.yaml` 的 `lease:` 块写的是 `seconds: 900`，而代码
    读的键是 `lease_seconds`；正式装配路径（`host.py` 的 `_Builder._cfg_for(role)`）
    根本不看那个块，只把角色自己那一段交给角色 ⇒ 把那个阈值从 900 改成 3，A/B 读到的
    仍是代码默认 900（读数：`temp/_d2_config_probe.py`）。

判据一律是"改一个阈值 ⇒ 行为随之改变"，不是"我改了一个数字"：每个值都在被读走的
那一处断言，并各带一条负控（死键形态改了不生效；租约过期后必须重新可领，别把 B 卡死）。
"""

from __future__ import annotations

from datetime import datetime, timezone
import pathlib

import yaml

from agentflow import schema as S
from agentflow.agent_b import AgentB
from agentflow.agent_b._support import NO_EXTRACTOR_ERROR
from agentflow.llm import RuleExtractor
from agentflow.store import Store, lease_expired

from conftest import add_literature, write_library_file

QUOTE = "An abelian group is a group in which the commutative law holds."
#: 一个确实已经过去的时刻（"租约过期"这个输入的唯一来源；测试不依赖真实时间）。
PAST_LEASE = "2000-01-01T00:00:00+00:00"
TS = "2026-01-01T00:00:00+00:00"

_ROOT = pathlib.Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- 替身与夹具


class _Doc:
    """最小文档替身（`check_quote` 只要求 `pages`）。"""

    pages = [QUOTE]

    def text_at(self, lo, hi):  # pragma: no cover - 抽取器替身不会走到这里
        return QUOTE


def _doc(_path):
    return _Doc()


class _BoomExtractor:
    """确定性失败：抛异常，模拟"这次抽取没成"，不改任何状态。"""

    is_framework_fallback = False

    def extract(self, doc, lit_id, meta):
        raise RuntimeError("boom-d2")


def _agent_b(store, extractor, **cfg) -> AgentB:
    config = {"lease_seconds": 900, "max_attempts": 3, "dup_strong": 0.92, "dup_review": 0.72}
    config.update(cfg)
    return AgentB(store, extractor=extractor, extract_text=_doc, config=config)


def _add_leased_literature(store, lit_id, *, claimed_by=None, lease_until=None,
                           mine_attempts=0, path=None, processed=False,
                           last_mine_error=None) -> None:
    """插一行文献并直接指定租约字段（conftest 的 `add_literature` 不支持它们）。"""
    row = S.Literature(
        lit_id=lit_id, title=f"Leased {lit_id}", type="J", summary="", path=path,
        processed=processed, source_request_ids=[], dedup_key=f"title:leased {lit_id}|*",
        added_at=TS, claimed_by=claimed_by, lease_until=lease_until,
        mine_attempts=mine_attempts, last_mine_error=last_mine_error,
    )
    row.validate()
    with store.tx("literature", actor="test") as tx:
        tx.upsert("literature", row.to_dict(), note="test_leased")


def _row(store, lit_id) -> dict:
    row = next((r for r in store.rows("literature") if r["lit_id"] == lit_id), None)
    assert row is not None, f"文献 {lit_id} 不存在"
    return row


def _expire_lease(store, lit_id) -> None:
    """把租约改成"已经过去"。

    不 sleep：测试不许依赖真实时间；"租约过期"这件事本身由 `store.lease_expired` 判定，
    这里只是把那个输入换成过去时刻（与 `test_agent_a_backoff._expire_lease` 同一手法）。
    """
    with store.tx("literature", actor="test", note="test_expire") as tx:
        row = tx.find("literature", lit_id=lit_id)
        assert row is not None
        row["lease_until"] = PAST_LEASE
        tx.upsert("literature", row, note="test_expire")


def _seconds_left(lease_until: str) -> float:
    return (datetime.fromisoformat(lease_until) - datetime.now(timezone.utc)).total_seconds()


# ============================================ (a2) "从未真抽"与"真抽过失败"必须分得开
#
# `D-2` 的第四档（主控 2026-10-02 裁定：先治"如实说"这一半，计数语义留残余）。
# 缺陷形态：`mine_attempts` 只在 `_claim` 里累加，而"这台机器没有够格的抽取器"走的是
# 同一条认领路径 ⇒ 到上限时那句统一写下的"超过最大抽取尝试次数"把"一次都没做"
# 写成了"做过并反复失败"（本项目 #3 那一档：把"没做"写成"做了没成"）。


def test_a_never_attempted_row_is_not_reported_as_repeated_failures(store):
    """`R3-⑩` 之后：拒抽那一档不烧抽取预算 ⇒ 领 4 窗也不判死（改前：第 4 窗判死）。

    同时保留 `D-2` 那一半的判据：旧行（盘上的计数已经烧到上限，改前的历史数据里
    就有一批）再被判死时，那句话必须如实写"从未真抽"而不是"抽过 N 次都失败"。
    两半都要在：前一半管"以后不再烧"，后一半管"已经烧上去的那些行话还说得对"。
    """
    write_library_file(store, "0000/a.txt", QUOTE)
    add_literature(store, "0000", title="A", path="0000/a.txt")
    b = _agent_b(store, RuleExtractor())          # 框架回退抽取器 ⇒ `R-56` 拒抽

    for window in range(4):                        # 4 个租约窗口，每窗一次认领
        out = b.run_once()
        assert out.skipped_no_extractor == 1, f"第 {window + 1} 窗该报拒抽，实得 {out.to_dict()}"
        assert out.processed == 0, "拒抽不等于处理完了"
        assert out.gave_up == 0, "从未真抽的行不许因为排队次数被判死"
        row = _row(store, "0000")
        assert row["mine_attempts"] == 0, "一次都没抽过 ⇒ 抽取预算不许被算掉"
        assert row["processed"] is False
        _expire_lease(store, "0000")

    # `D-2` 那一半：把计数摆成"旧行已经烧到上限"（改前历史数据的形态），
    # 放弃那一支的话必须说得对。
    with store.tx("literature", actor="test") as tx:
        legacy = tx.find("literature", lit_id="0000")
        legacy["mine_attempts"] = b.max_attempts
        tx.upsert("literature", legacy, note="simulate_legacy_burn")

    gave = b.run_once()                            # 旧行：到上限就该判死
    assert gave.gave_up == 1
    row = _row(store, "0000")
    assert row["processed"] is True
    msg = str(row["last_mine_error"])
    assert "超过最大抽取尝试次数" not in msg, f"从未真抽的行不许说'抽过 N 次都失败'：{msg}"
    assert "从未真抽" in msg and "没有可用的抽取器" in msg, msg
    assert NO_EXTRACTOR_ERROR in msg, "要说清是哪一档（否则读的人还得去猜）"


def test_a_really_attempted_row_keeps_the_repeated_failure_wording(store):
    """反负控：真抽过 3 次都失败的那一行，仍必须是"真抽过失败"那一档。

    没有这一条，上面那条可以被"把所有放弃都写成从未真抽"骗过。
    """
    write_library_file(store, "0000/a.txt", QUOTE)
    add_literature(store, "0000", title="A", path="0000/a.txt")
    b = _agent_b(store, _BoomExtractor())

    for _ in range(3):
        assert b.run_once().failed == 1
        _expire_lease(store, "0000")

    assert b.run_once().gave_up == 1
    msg = str(_row(store, "0000")["last_mine_error"])
    assert "超过最大抽取尝试次数" in msg, f"真抽过失败的行要保留原话：{msg}"
    assert "boom-d2" in msg, "并且要把上一次错误留下来（不然事后没法复盘）：" + msg
    assert "从未真抽" not in msg, "它明明抽过三次"


def test_a_row_with_no_recorded_reason_says_so_instead_of_a_fake_last_error(store):
    """同一半的第三条：认领之后、写下错误之前中断过的行，不许印一句"上一次错误：None"。"""
    write_library_file(store, "0000/a.txt", QUOTE)
    _add_leased_literature(store, "0000", mine_attempts=3, path="0000/a.txt")

    assert _agent_b(store, _BoomExtractor()).run_once().gave_up == 1
    msg = str(_row(store, "0000")["last_mine_error"])
    assert "上一次错误" not in msg, f"没有上一次错误就别说有：{msg}"
    assert "没有留下任何失败原因" in msg, msg


# ============================================================ (a) 租约语义与 A 对齐


def test_b_honours_its_own_backoff_lease(store):
    """(a) 抽取失败后写下的退避租约必须被自己认：当轮不许再领，预算不许被烧。

    修复前这里读到的是 `lease_until=None`（失败分支把租约一起清空），而跳过判据要求
    `claimed_by` 非空 ⇒ 第二次 `run_once` 又领到同一行、`mine_attempts` 变 2。
    """
    write_library_file(store, "0000/a.txt", QUOTE)
    add_literature(store, "0000", title="A", path="0000/a.txt")
    b = _agent_b(store, _BoomExtractor())

    first = b.run_once()
    assert first.failed == 1 and first.processed == 0
    row = _row(store, "0000")
    assert row["claimed_by"] is None, "持有者要放开：这条活现在不属于任何实例"
    assert row["lease_until"], "退避租约必须真的被写下来（写了才有人认它）"
    assert not lease_expired(row["lease_until"]), "退避租约当场有效"
    assert row["mine_attempts"] == 1

    second = b.run_once()
    assert second.failed == 0, "退避期内不许再抽一次"
    assert second.skipped_lease_backoff == 1, "被跳过的那条记进'我们自己的退避'"
    assert second.skipped_lease_active == 0, "它不是'别人持着'（两个计数分开数）"
    assert second.skipped_reason == "pending_literature_all_in_backoff"
    assert _row(store, "0000")["mine_attempts"] == 1, "退避期内不许烧重试预算"


def test_backoff_expiry_makes_the_row_claimable_again(store):
    """(a) 的另一半负控：退避一过期必须能重新领到 —— 否则修法会把 B 卡死。"""
    write_library_file(store, "0000/a.txt", QUOTE)
    add_literature(store, "0000", title="A", path="0000/a.txt")
    b = _agent_b(store, _BoomExtractor())
    b.run_once()

    _expire_lease(store, "0000")
    again = b.run_once()
    assert again.failed == 1, "租约过期 ⇒ 这一条重新可领（它仍然是失败，但确实被处理了）"
    assert _row(store, "0000")["mine_attempts"] == 2


def test_the_two_skip_kinds_are_counted_separately(store):
    """'别人持着'与'我们自己在退避'不能折成一个计数：要等的对象不同。"""
    write_library_file(store, "0000/a.txt", QUOTE)
    write_library_file(store, "0001/a.txt", QUOTE)
    _add_leased_literature(store, "0000", claimed_by="agent-B-other",
                           lease_until="2099-01-01T00:00:00+00:00", path="0000/a.txt")
    _add_leased_literature(store, "0001", claimed_by=None,
                           lease_until="2099-01-01T00:00:00+00:00", path="0001/a.txt",
                           mine_attempts=1)

    out = _agent_b(store, _BoomExtractor()).run_once()
    assert out.skipped_lease_active == 1, "别人持着的算 active"
    assert out.skipped_lease_backoff == 1, "claimed_by 为空的那条算我们自己退避"
    assert out.skipped_reason == "no_claimable_literature", "混合情形不许谎报成其中一类"
    assert _row(store, "0000")["mine_attempts"] == 0 and _row(store, "0001")["mine_attempts"] == 1


def test_an_exhausted_row_in_backoff_is_not_judged_dead(store):
    """先判租约、再判 attempts：正被有效租约盖住的行不该由我们来判死。

    这一条是 `(a)` 造成的最贵的一档：修复前这种行（`claimed_by=None` +
    有效租约 + 次数已满）是可领的，于是它当场被判 `processed=True`，
    理由写"超过最大抽取尝试次数" —— 而它可能一次都没真抽过。
    """
    write_library_file(store, "0000/a.txt", QUOTE)
    _add_leased_literature(store, "0000", claimed_by=None,
                           lease_until="2099-01-01T00:00:00+00:00", path="0000/a.txt",
                           mine_attempts=3)

    out = _agent_b(store, _BoomExtractor()).run_once()
    row = _row(store, "0000")
    assert out.gave_up == 0, "租约仍在走 ⇒ 不许判死"
    assert out.skipped_lease_backoff == 1
    assert row["processed"] is False, "它还在队列里，只是到点才会被重试"
    assert not row["last_mine_error"], "连尝试都没发生，不该写'超过最大尝试次数'"


def test_run_does_not_burn_the_retry_budget_in_one_pass(store):
    """(a) 的整机读数：`run()` 一遍下来 `mine_attempts` 必须停在 1。

    修复前 `run()` 会当场把这一行读到 3、判死并停下（`skipped_reason` 是队列空那一类），
    于是"三次重试"名存实亡、上游也可能被立刻重打。
    """
    write_library_file(store, "0000/a.txt", QUOTE)
    add_literature(store, "0000", title="A", path="0000/a.txt")

    out = _agent_b(store, _BoomExtractor()).run()
    row = _row(store, "0000")
    assert row["mine_attempts"] == 1, "一整趟 run 只许消耗一次预算"
    assert row["processed"] is False
    assert out["skipped_lease_backoff"] == 1
    assert out["skipped_reason"] == "pending_literature_all_in_backoff"
    assert out["gave_up"] == 0


def test_no_extractor_leaves_a_backoff_lease_and_keeps_the_row(store):
    """没有够格的抽取器 != 这一行处理完了：它要留在队列里，但不许当轮反复重领。

    修复前这条路上的租约也是 None，且 `_claim` 每次都给它 `mine_attempts += 1`
    ⇒ `run()` 转几圈就把它因"超过最大抽取尝试次数"判死（一次都没真抽过）。
    `R3-⑩` 之后这一格恒为 0（计数点挪到了真正调抽取器的那两处）——
    于是"从未真抽"在数据面上自己就站得住，不必再靠结论那句话去分辨。
    """
    write_library_file(store, "0000/a.txt", QUOTE)
    add_literature(store, "0000", title="A", path="0000/a.txt")

    out = _agent_b(store, RuleExtractor()).run()
    row = _row(store, "0000")
    assert out["skipped_no_extractor"] == 1
    assert row["last_mine_error"] == "no_llm_extractor"
    assert row["processed"] is False, "接线 LLM 之后它还要被领到"
    assert row["lease_until"] and not lease_expired(row["lease_until"]), "要有退避租约"
    assert row["mine_attempts"] == 0, "一次都没抽过 ⇒ 抽取预算不许被算掉（`R3-⑩` 起恒为 0）"
    assert out["skipped_reason"] == "pending_literature_all_in_backoff"


def test_reprocess_request_in_its_own_backoff_is_not_reclaimed(store):
    """重抽取请求那一半同形：失败写下的租约（`claimed_by=None`）也必须被认。

    修复前它会被当成"没人管"而当场重走准入链，目标关系不存在时还会被标 `rejected`
    —— 一次环境故障因此变成一个"B 判定不该处理它"的结论。
    """
    row = S.ReprocessRequest(
        reprocess_id="p-0001", timestamp=TS, reason="quote_unverifiable",
        submitted_by="agent-C", relation_ids=["0000"], status="pending",
        claimed_by=None, lease_until="2099-01-01T00:00:00+00:00", attempts=1,
    )
    row.validate()
    with store.tx("reprocess_requests", actor="test") as tx:
        tx.upsert("reprocess_requests", row.to_dict(), note="test_reprocess_backoff")

    got, rejected = _agent_b(store, _BoomExtractor())._claim_reprocess()
    assert got is None and rejected == [], "租约未过期的行不许被认领，也不许因此被拒"
    live = next(r for r in store.rows("reprocess_requests") if r["reprocess_id"] == "p-0001")
    assert live["status"] == "pending", "状态不许被这一次尝试改写"
    assert live["lease_until"] == "2099-01-01T00:00:00+00:00"


# ======================================================== (b) 阈值住在角色段里（不是死块）


def _cfg() -> dict:
    return yaml.safe_load((_ROOT / "config.yaml").read_text(encoding="utf-8"))


def test_lease_thresholds_live_in_the_role_sections():
    """(b) 判据：两个阈值住在 `agent_a:` / `agent_b:` 两段里 —— 那才是正式路径读的地方。"""
    cfg = _cfg()
    for role in ("agent_a", "agent_b"):
        section = cfg.get(role) or {}
        for key in ("lease_seconds", "max_attempts"):
            assert key in section, f"config.yaml 的 {role}: 段里没有 {key}"
        assert isinstance(section["lease_seconds"], int) and section["lease_seconds"] > 0
        assert isinstance(section["max_attempts"], int) and section["max_attempts"] > 0
    assert not (cfg.get("lease") or {}), (
        "`lease:` 块不许再承载任何生效键：阈值只能有一个落点，否则又是'两处答案'"
    )


def test_no_module_still_reads_the_dead_lease_block():
    """(b) 的机械半：全仓不再有 `cfg.get("lease")` 这种读法（旧拼接已撤）。"""
    src = _ROOT / "src" / "agentflow"
    hits = [p.name for p in src.rglob("*.py") if 'get("lease")' in p.read_text(encoding="utf-8")]
    assert hits == [], f"这些文件还在读那个死块：{hits}"


def test_the_formal_path_reads_that_section(tmp_path):
    """正式路径 = 只把该角色自己那一段交给角色（`host.py` 的 `_cfg_for(role)`）。

    断言的是"被读走的那一处"：`AgentB.__init__` 拿到的 `lease_seconds` / `max_attempts`
    就是段里的数（不是代码默认值）。
    """
    cfg = _cfg()
    section = cfg["agent_b"]
    st = Store(tmp_path / "ws")
    st.init()
    b = AgentB(st, extractor=_BoomExtractor(), extract_text=_doc, config=section)
    assert b.lease_seconds == section["lease_seconds"]
    assert b.max_attempts == section["max_attempts"]


def test_tuning_the_threshold_changes_the_written_lease(tmp_path):
    """(b) 的意义所在：改一个阈值 ⇒ 行为随之改变（这里是写下的退避租约的长度）。"""
    cfg = _cfg()
    for lease_seconds, lower, upper in ((3, 0.0, 120.0), (900, 600.0, 1200.0)):
        section = {**cfg["agent_b"], "lease_seconds": lease_seconds}
        st = Store(tmp_path / f"ws{lease_seconds}")
        st.init()
        write_library_file(st, "0000/a.txt", QUOTE)
        add_literature(st, "0000", title="A", path="0000/a.txt")
        b = AgentB(st, extractor=_BoomExtractor(), extract_text=_doc, config=section)
        b.run_once()
        left = _seconds_left(_row(st, "0000")["lease_until"])
        assert lower <= left <= upper, (
            f"lease_seconds={lease_seconds} 写下的租约还剩 {left:.1f}s —— 阈值没有真的生效"
        )


def test_the_old_dead_key_form_changes_nothing(tmp_path):
    """负控：修复前那种形态读不到 —— 所以路线①/③治不了正式路径，只有路线②能。

    注意这条测试说的不是"数值"（900 恰好与代码默认相同），而是"读的是哪个键"：
    `seconds` 这个键没有任何读者，把它设成 3 也换不来 3。
    """
    st = Store(tmp_path / "ws")
    st.init()
    assert AgentB(st, extractor=_BoomExtractor(), extract_text=_doc,
                  config={}).lease_seconds == 900, "段里没有该键 ⇒ 落在代码默认值上"
    assert AgentB(st, extractor=_BoomExtractor(), extract_text=_doc,
                  config={"seconds": 3}).lease_seconds == 900, "死键：改了也不生效"
    assert AgentB(st, extractor=_BoomExtractor(), extract_text=_doc,
                  config={"lease_seconds": 3}).lease_seconds == 3, "活的键：改了立刻生效"
