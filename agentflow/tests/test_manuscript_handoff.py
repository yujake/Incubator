# -*- coding: utf-8 -*-
"""判据（`draft/37` §134 + `draft/39` §C1–C4）：交接手稿 —— 编号由脚本给、一行一份交接、
留言带编号 + 一句描述。

用户口径（逐字）：

> 我觉得各智能体在互相传递信息时可以借助手稿的方式，即建一个收集手稿的文件夹，
> 每个智能体要交接工作前写一份手稿放在里面，且有标号（这个标号靠脚本拿最新的，从 0000 开始顺次标），
> 传信息时就传手稿编号。这样的话派活也有依据，溯源也很清晰。
> 至于手稿的命名就是标号+谁to谁，特别地如果是给所有人就是谁toALL。手稿格式就用 LLM 最擅长的 markdown。
> 当然就传个编号感觉有点尬，可以再附一句简要描述

2026-10-05 用户裁定：存储从「一份一个 `.md` 文件」改成追加式 JSONL
（`manuscripts/handoffs.jsonl`，一行一份交接），收工门那一档改成数行。

这一组钉七件事：
1. 编号从 `0000` 起顺次、「由脚本分配」（不靠模型记），并发写不撞号；
2. 一份交接 = 账本里一行，必填 `to` / `summary` / `body`；
3. 读得回来（正文 + 那一行）；按收件人/发件人过滤（`to=ALL` 是广播）；
4. `handoff` 这一循环形状：写手稿 「并」发出那条带编号 + 简要描述的留言；空手稿被拒（零写入）；
5. 坏收件人 / 不存在的 refs 被拒（溯源链不许断）；缺 `summary` 也被拒（它要进留言）；
6. 旧格式 `.md` 仍然读得回来（`format=md_legacy`），但不算作账本行；
7. 工具面：`manuscripts.read` / `.list` 对每个角色都可用（写不在工具面上）。
"""
from __future__ import annotations

import json
import pathlib
import threading
from typing import Any

from agentflow import manuscripts as MS
from agentflow import schema as S
from agentflow.agent_loop import LlmBackend, read_messages, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry


def test_ids_start_at_zero_and_every_handoff_is_one_row(tmp_path: pathlib.Path):
    """编号 `0000` 起顺次；一份交接一行；读得回来；`to=ALL` 是广播。"""
    root = tmp_path / "ws"
    root.mkdir()
    a = MS.write(root, sender="D", recipient="F", summary="把猜想交给你", body="证明它。")
    b = MS.write(root, sender="F", recipient=MS.ALL, summary="进展汇报", body="卡在第 3 步。")
    assert a["id"] == "0000" and b["id"] == "0001", (a, b)
    # 一行一份（追加式账本）：两行、编号各一、没有第三个文件
    assert [r["id"] for r in MS.rows(root)] == ["0000", "0001"]
    assert MS.handoffs_path(root).is_file(), MS.handoffs_path(root)
    assert list((root / MS.MANUSCRIPTS_DIR).glob("*.md")) == [], "新格式不再产生 .md 文件"
    got = MS.read(root, "0001")
    assert got and "卡在第 3 步" in got["text"] and got["record"]["to"] == "ALL", got
    # 广播那份，G 也收得到
    assert [r["id"] for r in MS.list_all(root, to="G")] == ["0001"]
    # 那一行必须能回答"谁在什么时候把什么交给了谁"
    row = MS.row_of(root, "0001") or {}
    assert row["sender"] == "F" and row["summary"] == "进展汇报" and row["created_at"], row
    assert row["sha256"] and row["bytes"], row


def test_concurrent_writers_do_not_collide(tmp_path: pathlib.Path):
    """并发写不撞号（`conductor.summon_many` 是并发的：撞号的表现是后者覆盖前者）。"""
    root = tmp_path / "ws"
    root.mkdir()
    got: list[str] = []
    lock = threading.Lock()

    def one(i: int) -> None:
        rec = MS.write(root, sender="C", recipient="D", summary=f"第 {i} 份", body=f"内容 {i}")
        with lock:
            got.append(rec["id"])

    threads = [threading.Thread(target=one, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(got)) == 8, f"撞号了：{sorted(got)}"
    assert sorted(got) == [f"{i:04d}" for i in range(8)], sorted(got)
    # 8 份 = 8 行（不是 8 个文件）：追加写不会互相覆盖
    assert len(MS.rows(root)) == 8, MS.rows(root)
    assert len({str(r.get("id")) for r in MS.rows(root)}) == 8


def test_empty_or_unknown_recipient_is_refused_with_zero_writes(tmp_path: pathlib.Path):
    """负控：空正文 / 缺一句话 / 坏收件人 / 坏发件人 ⇒ 拒绝，且一行都不写。"""
    root = tmp_path / "ws"
    root.mkdir()
    for kwargs, why in (
        (dict(sender="D", recipient="F", summary="空", body="   "), "空正文"),
        (dict(sender="D", recipient="F", body="有正文但没那一句话"), "缺 summary"),
        (dict(sender="D", recipient="Z", summary="坏收件人", body="x"), "坏收件人"),
        (dict(sender="Q", recipient="F", summary="坏发件人", body="x"), "坏发件人"),
    ):
        try:
            MS.write(root, **kwargs)
            raise AssertionError(f"{why} 没有被拒")
        except ValueError:
            pass
    assert MS.rows(root) == [], "被拒的那几次不许留下行"


def test_a_dangling_ref_is_recorded_and_visible_not_refused(tmp_path: pathlib.Path):
    """D10（`draft/52:103` 逐字："改成『建议』+ 一条读数"）：悬空 `refs` 不拒写。

    为什么改（真机读数）：D10 之前 `refs` 在 1542 行手稿里全空 —— "引用一错、
    整份交接就写不进去"这条判据在真机上的效果不是"引用得更准"，而是"没人敢引用"。
    新形态要求三件同时在位：

    1. 不拒：这一笔写得进去（旧判据在这里必红）；
    2. 记录了：行里 `ref_problems` 逐条写清哪一条引用立不住、为什么；
    3. 读数可见：`ref_readings()` 数得到"有引用的行数"与"立不住的那些引用"
       （D10 之前这一栏恒为 0，正是"判据从拒写降成标记之后没人说话"的形态）。
    """
    root = tmp_path / "ws"
    root.mkdir()
    good = MS.write(root, sender="D", recipient="F", summary="先来一份没人引的", body="x")
    rec = MS.write(root, sender="D", recipient="F", summary="引一份在的与一份不在的",
                   body="y", refs=[good["id"], "0099", "stmt:0007"])
    assert rec["id"] != good["id"], rec
    assert set(rec["ref_problems"]) == {"0099", "stmt:0007"}, rec
    assert "悬空" in rec["ref_problems"]["0099"] or "不在盘上" in rec["ref_problems"]["0099"], rec
    # 行真的落进账本（不是"报了错但文件里没有"）
    assert len(MS.rows(root)) == 2, MS.rows(root)
    got = MS.read(root, rec["id"])
    assert got and "引一份在的与一份不在的" in got["text"], got
    # 读数：有引用的行 1、立不住的引用 2 条
    rd = MS.ref_readings(root)
    assert rd["checked"] is True and rd["rows"] == 2, rd
    assert rd["rows_with_refs"] == 1, rd
    assert rd["count"] == 2 and {p["ref"] for p in rd["problems"]} == {"0099", "stmt:0007"}, rd
    assert {p["id"] for p in rd["problems"]} == {rec["id"]}, rd
    # 三态：引用都立得住时不多那个键（"没问题"与"没检查"不许长成同一个样子）
    assert "ref_problems" not in MS.row_of(root, good["id"]), MS.row_of(root, good["id"])
    # 读数里 `rows_with_refs` 不是 0 —— D10 之前这一栏在真机上恒为 0（1542 行全空）
    assert rd["rows_with_refs"] > 0, rd


def test_legacy_md_manuscripts_are_still_readable_but_not_counted_as_rows(tmp_path: pathlib.Path):
    """旧格式（`<编号>-<From>to<To>.md`）读得回来，带 `format=md_legacy` —— 但不算账本行。

    为什么必须显式测（三态纪律）：迁移期两种格式同时在盘上是真实情形；
    "旧文件还算数"会让迁移永远做不完，而"旧文件读不出来"会让历史交接当场消失。
    这条钉的是中间那条路：读得到、标得清、不计入新口径。
    """
    root = tmp_path / "ws"
    d = root / MS.MANUSCRIPTS_DIR
    d.mkdir(parents=True)
    (d / MS.name_for("0000", "D", "F")).write_text(
        "# 0000｜D → F\n\n- 标题：旧的交接\n\n## 正文\n\n旧格式的正文。\n", encoding="utf-8")

    got = MS.read(root, "0000")
    assert got and got["record"]["format"] == "md_legacy", got
    assert got["record"]["sender"] == "D" and got["record"]["to"] == "F", got
    assert got["record"]["summary"] == "旧的交接", got
    assert "旧格式的正文" in got["text"], got
    # 列为手稿时两种格式都出来
    assert [r["id"] for r in MS.list_all(root)] == ["0000"]
    # 但账本行是空 —— 新口径数的是行
    assert MS.rows(root) == []
    # 新写的一份接在旧编号之后（不撞号：编号扫的是"行 + 旧文件"的并集）
    rec = MS.write(root, sender="F", recipient="D", summary="新的交接", body="x")
    assert rec["id"] == "0001", rec


def test_query_filters_by_id_recipient_sender_time_and_refs(tmp_path: pathlib.Path):
    """`query` 是脚本那一层的唯一实现：六个过滤器各自单独有用（判据逐档钉）。"""
    root = tmp_path / "ws"
    root.mkdir()
    MS.write(root, sender="D", recipient="F", summary="第一份", body="x")
    MS.write(root, sender="F", recipient="ALL", summary="第二份", body="y", refs=["0000"])
    MS.write(root, sender="F", recipient="D", summary="第三份", body="z")

    assert [r["id"] for r in MS.query(root, mid="0001")[0]] == ["0001"]
    # `to=F` 含广播给所有人的那份（与 `list_all` 同一口径）；`to=ALL` 只给广播
    assert [r["id"] for r in MS.query(root, to="F")[0]] == ["0000", "0001"]
    assert [r["id"] for r in MS.query(root, to="ALL")[0]] == ["0001"]
    # `to=G` 能收到广播那份（与 list_all 同一口径）
    assert [r["id"] for r in MS.query(root, to="G")[0]] == ["0001"]
    assert [r["id"] for r in MS.query(root, sender="F")[0]] == ["0001", "0002"]
    assert [r["id"] for r in MS.query(root, refs="0000")[0]] == ["0001"]
    assert MS.query(root, limit=1)[0][-1]["id"] == "0002"
    # `since` 用 ISO 前缀比：未来时间 ⇒ 空（"没有"不等于"查不成"）
    assert MS.query(root, since="2999-01-01")[0] == []
    assert MS.query(root, since="2000-01-01")[0][-1]["id"] == "0002"


def test_missing_fields_names_what_a_row_lacks():
    """必填字段的判据是"缺哪一个"，不是"合不合格"（收工门读明细时要能点名）。"""
    assert MS.missing_fields({"to": "F", "summary": "一句话", "body": "正文"}) == []
    assert MS.missing_fields({"to": "F", "summary": "", "body": "正文"}) == ["summary"]
    assert MS.missing_fields({}) == ["to", "summary", "body"]


class _Scripted:
    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        got = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": json.dumps(got, ensure_ascii=False),
                                  "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _run_loop(tmp_path: pathlib.Path, replies: list[dict[str, Any]], *, role: str = "D"):
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    gw = _Scripted(replies)
    backend = LlmBackend(inner=LocalBackend({}), loops={}, session_root=ws,
                         seam_factory=lambda r: LlmSeam(role=r, session_root=ws, gateway=gw,
                                                        price=(0.0, 0.0), sid="h1"),
                         max_steps=4, store=st, sid="h1")
    cond = Conductor(st, backend=backend)
    backend.conductor = cond
    reg = build_registry(store=st, conductor=cond).registry
    backend.registry = reg
    run = run_role(role, "交接", store=st, registry=reg, conductor=cond,
                   seam=LlmSeam(role=role, session_root=ws, gateway=gw, price=(0.0, 0.0), sid="h1"),
                   session_root=ws, workspace_root=str(ws), sid="h1", max_steps=4, from_env=False)
    return ws, run, reg


def test_the_handoff_shape_writes_the_manuscript_and_sends_the_brief(tmp_path: pathlib.Path):
    """`handoff` 形状：写手稿 + 一条带「编号 + 简要描述」的留言（用户点名的"别只传编号"）。"""
    ws, run, _reg = _run_loop(tmp_path, [
        {"handoff": {"to": "F", "summary": "猜想 0000 交给你攻坚",
                     "body": "## 我做了什么\n立了三行问题。\n## 要你做什么\n攻它。",
                     "refs": [], "why": "你负责攻坚"}},
        {"final": "交接完了", "evidence": []},
    ])
    step = next(s for s in run.steps if s.shape == "handoff")
    res = step.result
    assert res.get("ok") is True, res
    assert res["id"] == "0000", res
    # 盘上就一行（账本就是"哪一份"的真相），正文与摘要都在那一行里
    rows = MS.rows(ws)
    assert [r["id"] for r in rows] == ["0000"], rows
    assert rows[0]["summary"] == "猜想 0000 交给你攻坚", rows[0]
    assert "攻它" in rows[0]["body"], rows[0]
    msgs, problems = read_messages(ws, "F", sid="h1")
    assert not problems, problems
    mine = [m for m in msgs if "手稿 0000" in str(m.get("body"))]
    assert mine, msgs
    assert "猜想 0000 交给你攻坚" in str(mine[0]["body"]), mine[0]
    assert "manuscripts.read" in str(mine[0]["body"]), mine[0]


def test_the_old_brief_and_title_names_still_work_in_the_loop_shape(tmp_path: pathlib.Path):
    """旧名（`title` / `brief`）仍然接受：都当 `summary` 用 —— 迁移期两种写法都写得进去。

    为什么留着：提示词改了，模型的历史习惯与旧工作区的会话记录里全是 `title`/`brief`；
    一律拒掉会让"手稿写不进去"以"这一步 invalid"的形态出现（而那看起来像模型不会用工具）。
    """
    ws, run, _reg = _run_loop(tmp_path, [
        {"handoff": {"to": "F", "title": "旧名标题", "brief": "旧名的一句话",
                     "body": "正文。", "refs": []}},
        {"final": "完", "evidence": []},
    ])
    step = next(s for s in run.steps if s.shape == "handoff")
    assert step.result.get("ok") is True, step.result
    assert MS.rows(ws)[0]["summary"] == "旧名的一句话", MS.rows(ws)


def test_a_handoff_without_a_body_is_refused_as_an_invalid_step(tmp_path: pathlib.Path):
    """负控：空正文的 handoff 判 `invalid`（不是"写了一份空手稿"）。"""
    ws, run, _reg = _run_loop(tmp_path, [
        {"handoff": {"to": "F", "summary": "空的", "body": "   "}},
        {"final": "改了", "evidence": []},
    ])
    bad = run.steps[0]
    assert bad.shape == "invalid" and "空手稿" in str(bad.result.get("problem", "")), bad.to_dict()
    assert MS.rows(ws) == []


def test_every_role_can_read_and_list_but_writing_is_a_loop_shape(tmp_path: pathlib.Path):
    """工具面：`read`/`list` 八个角色都有；「写」不在工具面上（它是 `handoff` 形状）。

    为什么写不做成工具（设计取舍，判据把两半都钉住）：文件名要写"谁给谁"，
    而工具层拿不到 per-call 的身份（注入的 deps 是装配期的）—— 在那里放一个 write
    只会产出"不知道谁写的交接手稿"。循环形状知道 `self.role`，所以写放在那里。

    主控 M 不在这张读面上（第二个断言）：M 的读面是"编排面 + `fs.*` 白名单"
    （`draft/37` §38/§57），而 `manuscripts/*.md` 就在工作区里 —— M 用 `fs.read`
    读同一批文件，不必为它扩这条边界（扩了要裁定，`tests/test_conductor_tools.py`
    的 `M_TOOL_FACE` 相等断言也会红）。
    """
    (tmp_path / "ws" / "data").mkdir(parents=True)
    st = Store(tmp_path / "ws")
    st.init()
    reg = build_registry(store=st, conductor=Conductor(st)).registry
    for role in sorted(S.ROLES):
        names = {t.name for t in reg.for_role(role)}
        assert {"manuscripts.read", "manuscripts.list"} <= names, (role, sorted(names))
        assert "manuscripts.write" not in names, (role, "写手稿不该在工具面上")
    m_names = {t.name for t in reg.for_role(S.CONDUCTOR_ROLE)}
    assert not ({"manuscripts.read", "manuscripts.list"} & m_names), sorted(m_names)
