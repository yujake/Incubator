"""判据：文件"读后写"（业主 2026-10-10 裁定 9甲；DSH `dsh-fs-observation-policy` 的搬运）。

## 这一批判的是什么

改前 `fs.write` / `fs.edit` 没有任何"你读过它吗"这一格 ⇒ 静默覆盖一个从没看过的文件是被允许的。
这是本文具面上唯一"代价不可逆"的坏法（`draft/100` S-A 把它排在第一批）。

## 读数（本文件写之前先手跑了一遍，红/绿对照）

    没读过就 edit                ⇒ not_observed（改前是绿的：闸生效）
    write 覆盖已存在、没读过      ⇒ not_observed
    读 → edit                    ⇒ ok
    新文件 write                 ⇒ ok（created=True）
    清表（换一趟）后没读就 edit   ⇒ not_observed（反真空）
"""

from __future__ import annotations

import pathlib

from agentflow import conductor as C
from agentflow import fs_observation as OBS
from agentflow.tools import fs_tools as FS


def _ctx(root: pathlib.Path) -> FS.FsContext:
    return FS.FsContext(root=root)


def _ws(tmp_path: pathlib.Path, name: str = "a.txt", text: str = "hello world\n") -> pathlib.Path:
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text, encoding="utf-8")
    return root


# --------------------------------------------------------------- 闸本身

def test_editing_without_reading_is_refused(tmp_path: pathlib.Path) -> None:
    """正控（本批的核心）：没读过就编辑 ⇒ `not_observed`，且文案是归一化那一句。

    改前这一条是绿的（工具照改）—— 这就是本批要堵的那件事。
    """
    root = _ws(tmp_path)
    with C.calling_as("t-1", "M"):
        res = FS.fs_edit(_ctx(root), path="a.txt", old_string="world", new_string="there")
    assert res.ok is False and res.meta["kind"] == OBS.CODE_NOT_OBSERVED, res.to_dict()
    assert "还没被读过" in res.error and "先读一次" in res.error, res.error
    assert (root / "a.txt").read_text(encoding="utf-8") == "hello world\n", "被拒的编辑不许落盘"


def test_reading_then_editing_passes(tmp_path: pathlib.Path) -> None:
    """正控：先读后改 ⇒ 过（闸不是"一律拒"）。"""
    root = _ws(tmp_path)
    with C.calling_as("t-1", "M"):
        ctx = _ctx(root)
        assert FS.fs_read(ctx, path="a.txt").ok is True
        res = FS.fs_edit(ctx, path="a.txt", old_string="world", new_string="there")
    assert res.ok is True, res.to_dict()
    assert (root / "a.txt").read_text(encoding="utf-8") == "hello there\n"


def test_overwriting_an_unread_file_is_refused_and_creating_a_new_one_is_not(
        tmp_path: pathlib.Path) -> None:
    """负控 + 正控（两档必须分开）：已存在且没读过 ⇒ 拒；不存在 ⇒ 允许创建。

    DSH 的这两支是分开的（`FSL:826-828`）：`createIfAbsent` + 目标已存在 = 想覆盖没读过的；
    目标不在 = 正当创建。折成一档就会把"新建"也堵死。
    """
    root = _ws(tmp_path)
    with C.calling_as("t-1", "M"):
        ctx = _ctx(root)
        blocked = FS.fs_write(ctx, path="a.txt", content="x", overwrite=True)
        fresh = FS.fs_write(ctx, path="b.txt", content="new")
    assert blocked.ok is False and blocked.meta["kind"] == OBS.CODE_NOT_OBSERVED, blocked.to_dict()
    assert (root / "a.txt").read_text(encoding="utf-8") == "hello world\n", "被拒的覆盖不许落盘"
    assert fresh.ok is True and fresh.data["created"] is True, fresh.to_dict()


def test_two_not_observed_sources_share_one_sentence(tmp_path: pathlib.Path) -> None:
    """归一化（照 DSH `TFS:547`）：两个出处（edit 未读 / write 未读覆盖）给模型的同一句话。"""
    root = _ws(tmp_path)
    with C.calling_as("t-1", "M"):
        ctx = _ctx(root)
        a = FS.fs_edit(ctx, path="a.txt", old_string="world", new_string="there")
        b = FS.fs_write(ctx, path="a.txt", content="x", overwrite=True)
    assert a.error == b.error, (a.error, b.error)


def test_a_stale_read_is_refused_and_the_remedy_is_attached(tmp_path: pathlib.Path) -> None:
    """正控（陈旧）：读之后文件被旁路改过 ⇒ `stale_version`，且保留理由 + 追加补救句。"""
    root = _ws(tmp_path)
    with C.calling_as("t-1", "M"):
        ctx = _ctx(root)
        assert FS.fs_read(ctx, path="a.txt").ok is True
    # 旁路改（模拟"别人动过"）：绕过工具层，版本必然变化。
    (root / "a.txt").write_text("changed from outside\n", encoding="utf-8")
    with C.calling_as("t-1", "M"):
        res = FS.fs_edit(_ctx(root), path="a.txt", old_string="outside", new_string="inside")
    assert res.ok is False and res.meta["kind"] == OBS.CODE_STALE_VERSION, res.to_dict()
    assert "重新读一遍，再重试" in res.error, res.error
    assert res.meta["observed_version"] and res.meta["version_now"], res.meta
    assert res.meta["observed_version"] != res.meta["version_now"], res.meta


def test_a_successful_mutation_observes_its_own_new_version(tmp_path: pathlib.Path) -> None:
    """正控（写后观察）：同一步里"写 → 再写同一个文件" ⇒ 不拒（照 DSH 取写后版本）。"""
    root = _ws(tmp_path)
    with C.calling_as("t-1", "M"):
        ctx = _ctx(root)
        assert FS.fs_read(ctx, path="a.txt").ok is True
        first = FS.fs_write(ctx, path="a.txt", content="one", overwrite=True)
        second = FS.fs_write(ctx, path="a.txt", content="two", overwrite=True)
        edited = FS.fs_edit(ctx, path="a.txt", old_string="two", new_string="three")
    assert first.ok is True and second.ok is True, (first.to_dict(), second.to_dict())
    assert edited.ok is True, edited.to_dict()


# --------------------------------------------------------------- 反真空 / 边界

def test_a_restored_run_starts_with_no_observation(tmp_path: pathlib.Path) -> None:
    """反真空：清表（换一趟）之后同一个文件又要重读一次才许改。

    "没观察过"绝不许被当成"观察过且没变"（DSH：观察不持久化，恢复的会话必须重读）。
    """
    root = _ws(tmp_path)
    with C.calling_as("t-1", "M"):
        ctx = _ctx(root)
        assert FS.fs_read(ctx, path="a.txt").ok is True
        assert FS.fs_edit(ctx, path="a.txt", old_string="world", new_string="there").ok is True
    OBS.clear()
    with C.calling_as("t-2", "M"):
        res = FS.fs_edit(_ctx(root), path="a.txt", old_string="there", new_string="x")
    assert res.ok is False and res.meta["kind"] == OBS.CODE_NOT_OBSERVED, res.to_dict()


def test_calls_outside_a_delegation_share_one_bucket(tmp_path: pathlib.Path) -> None:
    """适应（与 DSH 的一处刻意差异）：不在委托里的调用者仍然"先读后改"，但共用一格。

    DSH 那条路上没有"委托之外的调用者"（工具只从 agent 的 exec 里进），所以它把
    "没有 owner"处理成丢弃观察 + 编辑一律拒（`POL:73-74`/`:67`）。
    我们有这种调用者（模块自检 / 发布门 / `cli` 直调 / 本判据）⇒ 丢弃会让它们
    连先读后改都做不到，那不是本裁定要的。于是退化成一个桶：纪律照旧、隔离照旧
    （见下一条：不同委托互不可见），只是"没有身份"共用一格。
    """
    root = _ws(tmp_path)
    assert OBS.current_owner() == OBS.DIRECT_OWNER, "本用例要在没有委托上下文时跑"
    ctx = _ctx(root)
    blocked = FS.fs_edit(ctx, path="a.txt", old_string="world", new_string="there")
    assert blocked.ok is False and blocked.meta["kind"] == OBS.CODE_NOT_OBSERVED, blocked.to_dict()
    assert FS.fs_read(ctx, path="a.txt").ok is True
    assert FS.fs_edit(ctx, path="a.txt", old_string="world", new_string="there").ok is True


def test_two_delegations_do_not_see_each_others_reads(tmp_path: pathlib.Path) -> None:
    """正控（隔离）：甲委托读过的，乙委托不算读过 ⇒ 乙仍然要自己读一次。

    这一条是"按委托记账"的判据本体：观察若退化成全局缓存，一个从没读过文件的孩子
    就能白拿别人的授权（那正是本裁定要防的事的另一种形态）。
    """
    root = _ws(tmp_path)
    with C.calling_as("t-1", "M"):
        assert FS.fs_read(_ctx(root), path="a.txt").ok is True
    with C.calling_as("t-2", "M"):
        res = FS.fs_edit(_ctx(root), path="a.txt", old_string="world", new_string="there")
    assert res.ok is False and res.meta["kind"] == OBS.CODE_NOT_OBSERVED, res.to_dict()


def test_stat_and_list_do_not_grant_the_observation(tmp_path: pathlib.Path) -> None:
    """负控（不许偷偷放宽）：`fs.stat` / `fs.list` 不登记观察（照 DSH 只有读/写/改五处 emit）。

    今天 `fs_stat` 自己会算 sha256（很容易顺手在那里也记一笔）—— 那会让"看一眼大小"变成改写授权。
    """
    root = _ws(tmp_path)
    with C.calling_as("t-1", "M"):
        ctx = _ctx(root)
        assert FS.fs_stat(ctx, path="a.txt").ok is True
        assert FS.fs_list(ctx, path=".").ok is True
        res = FS.fs_edit(ctx, path="a.txt", old_string="world", new_string="there")
    assert res.ok is False and res.meta["kind"] == OBS.CODE_NOT_OBSERVED, res.to_dict()


def test_a_directory_cannot_be_edited_even_after_reading(tmp_path: pathlib.Path) -> None:
    """边界：读成功的只有文件；目录仍然走"不能当文件改"那条（闸不改变既有的类型判据）。"""
    root = _ws(tmp_path)
    (root / "sub").mkdir(exist_ok=True)
    with C.calling_as("t-1", "M"):
        res = FS.fs_edit(_ctx(root), path="sub", old_string="a", new_string="b")
    assert res.ok is False, res.to_dict()
