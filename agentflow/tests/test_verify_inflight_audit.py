"""`verify` 对 I7 在途上限的事后读数（CS-1 的乙半边，批 R19）。

为什么这条判据必须存在：闸门（`interactions.admit_search_request`）只装在角色面的
入队口上；人工面（CLI `submit`、WebUI `/api/submit`）刻意不过闸门 —— 理由逐字写在
`agent_a/core.py:60-63`（"CLI 那条人工路径不闸（人自己知道自己在提交什么）"）。
于是"在途超过上限"在盘上是一个合法状态，而合法不等于不必看见：上限是 A 的产能约束，
超了就意味着 A 的队列比设计的更长，而在此之前没有任何地方会说出这件事
（角色面被闸门挡住 ⇒ 没有读数；人工面不闸 ⇒ 也没有读数）。

两个方向都钉（FC-09）：
- 在途 ≤ 上限 ⇒ 一条都不报（防误伤）；
- 越过去 ⇒ 恰好一条 warning，且消息里点出谁把它排长的（数量 + 上限 + 逐提交方计数）。

级别刻意是 `warning` 而不是 `error`：人有权把队列排长（他可能正要手工塞一批），
机器要做的是把事实记下来，而不是替人决定不许。

第二条读数（`unregistered_submitter`）读的是另一件事：`schema.py:46-49` 逐字要求
"本框架自己的角色必须显式登记，不能靠'未登记 ⇒ low'这条兜底"。登记面漂了不会让任何
判据变红，所以在审计里读一次 —— 只读在途行（请求结束之后 `priority` 已是历史）。
"""

from __future__ import annotations

from agentflow import interactions as IX
from agentflow import schema as S
from agentflow.store import Store
from agentflow.verify import verify_all

TS = "2026-01-01T00:00:00+00:00"


def _warehouse(root) -> Store:
    st = Store(root)
    st.init()
    return st


def _queue(st: Store, n: int, *, by: str = "agent-C", start: int = 1, done: bool = False) -> None:
    """塞 n 条请求行（缺省是在途：`done=False`）。编号从 `start` 起，避免撞号。"""
    with st.tx("search_requests", actor="fixture", note="fixture") as tx:
        for i in range(start, start + n):
            row = S.SearchRequest(
                request_id=f"r-{i:04d}", timestamp=TS, topic=f"占位主题{i}", mode="topical",
                content_description="", done=done, submitted_by=by,
                outcome=("no_results" if done else None),
            )
            row.validate()
            tx.upsert("search_requests", row.to_dict(), note="fixture")


def _of(store, code: str) -> list:
    return [i for i in verify_all(store).issues if i.code == code]


def test_the_queue_within_the_limit_is_not_reported(tmp_path):
    """在途 == 上限 ⇒ 一条都不报（防误伤）；读数格必须记下查了多少条在途。"""
    st = _warehouse(tmp_path / "ws")
    limit = IX.DEFAULTS["max_inflight_requests"]
    _queue(st, limit)

    rep = verify_all(st)
    assert rep.checked["inflight_requests"] == limit, rep.checked
    assert not [i for i in rep.issues if i.code == "inflight_over_limit"], (
        "在途刚好到上限是合法状态（闸门判据是 `>= limit` 才拒），不该报")
    assert not [i for i in rep.issues if i.code == "unregistered_submitter"]


def test_one_row_over_the_limit_is_reported_with_the_submitters(tmp_path):
    """越过一格 ⇒ 恰好一条 warning，且消息里同时有：实际条数、上限、逐提交方计数。"""
    st = _warehouse(tmp_path / "ws")
    limit = IX.DEFAULTS["max_inflight_requests"]
    _queue(st, limit)
    # 这一条来自"人工面"（`human` 在登记表里，所以另一条读数不参与本用例）
    _queue(st, 1, by="human", start=900)

    got = _of(st, "inflight_over_limit")
    assert len(got) == 1, f"应当恰好一条读数，实得 {[i.code for i in got]}"
    issue = got[0]
    assert issue.level == "warning", "合法状态不该报 error（人有权把队列排长）"
    assert str(limit + 1) in issue.message, issue.message
    assert f"上限 {limit}" in issue.message, issue.message
    assert "agent-C×" in issue.message and "human×1" in issue.message, issue.message


def test_an_unregistered_submitter_in_flight_is_named(tmp_path):
    """在途行里有没登记的提交方 ⇒ 点名报出来；同一批数据换个登记过的名字就不报。"""
    st = _warehouse(tmp_path / "ws")
    _queue(st, 1, by="agent-X")
    got = _of(st, "unregistered_submitter")
    assert len(got) == 1, f"没登记的提交方必须报出来，实得 {[i.code for i in got]}"
    assert "agent-X" in got[0].message, got[0].message
    assert got[0].level == "warning"

    # 负控：只换一个名字（`human` 在 `SUBMITTER_DEFAULT_PRIORITY` 里）⇒ 同一条判据闭嘴
    st2 = _warehouse(tmp_path / "ws2")
    _queue(st2, 1, by="human")
    assert not _of(st2, "unregistered_submitter")


def test_finished_requests_are_not_in_flight_and_are_not_reported(tmp_path):
    """三条读数的口径只有一条：在途 = `done` 为假。结束的请求既不占配额，也不进读数。

    为什么这条反真空必须有：把"没登记的提交方"判成"所有请求行"也能让上一条通过，
    代价是历史数据永远报红 —— 而那正是"假报警比不校验更糟"的形态（FC-11）。
    """
    st = _warehouse(tmp_path / "ws")
    limit = IX.DEFAULTS["max_inflight_requests"]
    _queue(st, limit + 5, by="agent-X", done=True)

    rep = verify_all(st)
    assert rep.checked["inflight_requests"] == 0, rep.checked
    assert not [i for i in rep.issues if i.code in ("inflight_over_limit", "unregistered_submitter")]
