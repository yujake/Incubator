# -*- coding: utf-8 -*-
"""判据（D5）：`init` / `run-agent` 认得"这个目录里已经有用户的投料"。

## 改前是什么样（业主的原话）

    里面有 2 个不属于我们的条目：[...]

用户把一篇 PDF（外加它自己的附件）丢进一个文件夹，再 `agentflow --root <那个文件夹> init`
进去 —— `store.Store.init()` 的 `R-32` 判据（`_foreign_dir_guard_should_refuse`）
按"既没有 `data/`、又不是空目录、也不是工作区标记"拒绝。那条判据本身是对的
（它挡的是"在别人的目录里凭空建库"，见 `draft/28` §136.3 事故 B），缺的是
一条由用户明说的出口：`init --force` 是"清空重建"，不该被拿来当"我认这个目录"用。

## 这一份守什么（两条成对，缺一条就没有判别力）

| 判据 | 落点 |
|---|---|
| ① 带 `--allow-foreign-entries` ⇒ init 成功，用户的文件一个字节不动 | `cli.main(["init", ...])` 退出码 0 + `data/` 齐 + `.agentflow-workspace` 落盘 |
| ② 不带这个开关 ⇒ 仍然拒绝，且拒绝文案里教这条开关 | 退出码 2 + stderr 里有 `--allow-foreign-entries` |

`run-agent` 那一侧：同一份初始化助手 + 同一个开关名（`--allow-foreign-entries`
在它的 `--help` 里），且它先落标记再 init。那一条不走真模型调用（会花钱）：
把 `_agent_seam_factory` 换成一个哨兵异常，证明"init 已经成功、然后才走到接模型那一步"。

## 为什么不动 `store.py`

`R-32` 的判据本体是禁改区（`schema-migration`）。这一批只在它的三条出路之外
补第四条命令行路子 —— 落 `.agentflow-workspace`（`store.init` 自己的白名单出口，
`store.py:_foreign_dir_guard_should_refuse` 明写着它）之后再 init，判据一个字没改。
"""

from __future__ import annotations

import pathlib

import pytest

from agentflow import cli

#: 那个"用户的文件夹"里的两样东西（业主原话里的 2 个条目）。
PDF = b"%PDF-1.7\n% not a real pdf, just bytes\n"
NOTE = "这篇我先放这儿，等会再让系统读。\n"


class _StopAtSeam(RuntimeError):
    """哨兵：走到"接模型"那一步就停（证明 init 已经跑完了，而且没有花一分钱）。"""


def _user_folder(tmp_path: pathlib.Path) -> pathlib.Path:
    """造一个"人的文件夹"：一篇 PDF + 一张便签，没有 `data/`。"""
    d = tmp_path / "投料"
    d.mkdir()
    (d / "paper.pdf").write_bytes(PDF)
    (d / "note.txt").write_text(NOTE, encoding="utf-8")
    return d


def _tree(d: pathlib.Path) -> dict[str, bytes]:
    """这棵树里每个文件的字节（判"一个字节都不许动"用）。"""
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in d.rglob("*") if p.is_file()}


# ====================================================================== ① 带开关 ⇒ 成
def test_init_with_the_switch_accepts_a_folder_holding_user_files(
        tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    """判据 ①：只放一篇 PDF 的目录 + `--allow-foreign-entries` ⇒ init 成功。

    改前红：`init` 没有这个开关 ⇒ argparse 以退出码 2 拒绝（"unrecognized arguments"），
    目录里一个 `data/` 都不会出现。
    """
    d = _user_folder(tmp_path)
    before = _tree(d)

    code = cli.main(["--root", str(d), "init", "--allow-foreign-entries"])

    out = capsys.readouterr()
    assert code == 0, (code, out.err, out.out)
    assert (d / "data" / "counters.json").is_file(), "init 没有建出 data/"
    assert (d / "library").is_dir(), "init 没有建出 library/"
    marker = d / ".agentflow-workspace"
    assert marker.is_file(), (
        "没有落工作区标记：`store` 的白名单出口是 `.agentflow-workspace`，"
        "不落它就只能靠 `--force`（那是清空重建，不是'我认这个目录'）")
    text = marker.read_text(encoding="utf-8")
    assert text.startswith("agentflow workspace"), text
    assert "accepted_foreign_entries=2" in text, text

    after = _tree(d)
    for name, body in before.items():
        assert after.get(name) == body, f"用户的文件被动了：{name}"
    assert "[init] 已初始化" in out.out, out.out


# ====================================================================== ② 不带 ⇒ 仍拒，且教开关
def test_without_the_switch_it_still_refuses_and_teaches_the_switch(
        tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    """判据 ②（同一条边界的另一侧）：不给开关 ⇒ 仍拒，且拒绝文案里教这条开关。

    没有这一条，"把守卫放宽到一切目录"也能让①通过 —— 两条必须成对存在。
    改前红：文案里只有 `--force` 与 `projects.ensure_project` 两条出路，
    没有一个字提到 `--allow-foreign-entries`（那个开关当时还不存在）。
    """
    d = _user_folder(tmp_path)
    before = _tree(d)

    code = cli.main(["--root", str(d), "init"])

    out = capsys.readouterr()
    assert code == 2, (code, out.err, out.out)
    assert "--allow-foreign-entries" in out.err, (
        "拒绝文案里没有教这条开关 —— 用户只能看到'里面有 2 个不属于我们的条目'，"
        f"然后自己去猜该怎么办。stderr 全文：\n{out.err}")
    assert "不属于我们的条目" in out.err, out.err
    assert "拒绝 init" in out.err, out.err
    assert not (d / "data").exists(), "拒绝之后不许留下 data/"
    assert _tree(d) == before, "拒绝之后文件集合/内容必须逐字节不变"


# ====================================================================== run-agent 那一侧
def test_run_agent_takes_the_same_switch_and_initializes_before_asking_for_a_model(
        tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """`run-agent` 也有这个开关：先落标记 + init，再走到"接模型"那一步。

    为什么把接缝换掉：这条判据只关心"init 认了这个目录"，不该真的打模型
    （`settings.json` 里可能有真 key ⇒ 一次真调用就是钱）。哨兵异常证明顺序：
    init 已经成功，然后才轮到接模型。
    """
    d = _user_folder(tmp_path)
    # 解析层：这个开关是 run-agent 自己认识的（不是全局参数）。
    parser = cli.build_parser()
    args = parser.parse_args(["--root", str(d), "run-agent", "M", "--task", "读一下那篇 PDF",
                              "--allow-foreign-entries"])
    assert args.allow_foreign_entries is True

    def _boom(*_a, **_k):
        raise _StopAtSeam("走到接模型这一步就停")

    monkeypatch.setattr(cli, "_agent_seam_factory", _boom)
    with pytest.raises(_StopAtSeam):
        cli.main(["--root", str(d), "run-agent", "M", "--task", "读一下那篇 PDF",
                  "--allow-foreign-entries"])
    assert (d / "data" / "counters.json").is_file(), "run-agent 那条路上 init 没成功"
    assert (d / ".agentflow-workspace").is_file()
    assert (d / "paper.pdf").read_bytes() == PDF


def test_run_agent_without_the_switch_says_the_same_thing(
        tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """负控：`run-agent` 不给开关 ⇒ 同样以 2 停下，并教这条开关（且没接到模型）。"""
    d = _user_folder(tmp_path)

    def _boom(*_a, **_k):  # pragma: no cover - 这条路径不该走到这里
        raise _StopAtSeam("不该走到接模型")

    monkeypatch.setattr(cli, "_agent_seam_factory", _boom)
    code = cli.main(["--root", str(d), "run-agent", "M", "--task", "读一下那篇 PDF"])
    out = capsys.readouterr()
    assert code == 2, (code, out.err, out.out)
    assert "--allow-foreign-entries" in out.err, out.err
    assert not (d / "data").exists()
