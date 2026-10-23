# -*- coding: utf-8 -*-
"""`scripts/noai_batch_sign.py` 的判据：批量签字只许走门自己的 `--approve` 通路。

六条判据与工具的安全阀一一对应：
- ① `--list` 的两种读数（已有 1 名 / 还差 1 名，以及 0/2 与 2/2）；
- ② 跨批次：先一名 reviewer 签 3 条（各 1 名，退出码 1），换另一名再签一次（3 条都 2/2，退出码 0）；
- ③ 同一批里重名 ⇒ 拒绝（退出码 2），台账一字未动；
- ④ 缺 `--yes` 且 stdin 非终端 ⇒ 拒绝（退出码 2），台账一字未动；
- ⑤ `--dry-run` ⇒ 台账 sha256 不变；
- ⑥ 反真空：把"签完回读"打桩成恒满足 ⇒ ② 里只签 1 名的那一步仍然必须报未满足。

夹具纪律：一律落在 `tmp_path` —— 假清单 + 假路径 + 假台账。台账由门自己的 `--baseline`
写出来（不手搓 JSON：手搓的夹具只能证明"这个脚本会读我手搓的形状"），核对时也用门的读函数
`noai_gate.load_ledger`。真 `.noai-approvals.json` 一个字节都不碰，也不拿真台账跑 `--approve`。
"""

from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path

import pytest

#: 把仓库根注入 sys.path（`scripts` 与 `tests` 是顶层包；conftest.py 只注入了 `src/`）。
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts import noai_batch_sign as B  # noqa: E402
from scripts import noai_gate as G  # noqa: E402

#: 夹具里的假路径（都不是真清单里的条目）。
FILES = ("a.py", "b.py", "c.py")

#: 夹具里那条"逐行走查"的 scope（门要求它具体、非空）。
SCOPE = "逐行走查 a.py / b.py / c.py 的全文（夹具）"


def _ledger_sha256(root: Path) -> str:
    """夹具台账的内容 sha256（"一字未动"按内容判，不按 mtime 判）。"""
    return hashlib.sha256((root / G.LEDGER_NAME).read_bytes()).hexdigest()


def _names(root: Path, key: str) -> list[str]:
    """用门自己的读函数核对台账：这一条现在记了哪些 reviewer（按记录顺序）。"""
    ledger = G.load_ledger(G.ledger_default_path(root))
    entry = ledger.entry_for(key)
    assert entry is not None, f"台账里应该有 {key} 这一条"
    return [r.name for r in entry.reviewers]


def _make_ws(tmp_path: Path, *, signers: dict[str, list[str]] | None = None) -> Path:
    """造一个只有假路径与假台账的工位。

    台账由门自己的 `--baseline` 写出来，需要"已经有人签过"的状态时再用 `--approve` 补 ——
    两条都是门自己的写通路，于是夹具的形状与真台账同源。
    """
    root = tmp_path / "ws"
    root.mkdir()
    (root / G.MANIFEST_NAME).write_text(
        "[category: solver-core] 夹具：假清单（判据不碰真清单）\n\n"
        + "".join(f"{n}  [category: solver-core] 夹具假路径 {n}（判据用）\n" for n in FILES),
        encoding="utf-8",
    )
    for i, n in enumerate(FILES, start=1):
        (root / n).write_text(f"# 夹具 {i}\nX = {i}\n", encoding="utf-8")

    assert G.main(["--baseline", "--paths", *FILES, "--root", str(root), "--quiet"]) == 0
    for key, people in (signers or {}).items():
        for who in people:
            code = G.main([
                "--approve", key, "--reviewer", who, "--scope", SCOPE,
                "--root", str(root), "--quiet",
            ])
            assert code == 0, f"夹具前提：{key} 的 --approve 要成功"
    return root


# --------------------------------------------------------------------------- 判据①：读数


def test_list_shows_existing_names_and_how_many_are_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """判据①：`--list` 同时给出"已有 1 名 / 还差 1 名"与"0/2、2/2"这些读数。"""
    root = _make_ws(tmp_path, signers={"a.py": ["甲"], "b.py": ["乙", "丙"]})

    code = B.main(["--list", "--root", str(root)])
    out = capsys.readouterr().out

    assert code == 1, f"有待签的条目 ⇒ 退出码 1（不是 0）：\n{out}"
    # 读数一：已有 1 名、还差 1 名
    assert "a.py（1/2，还差 1 名不同 reviewer）" in out, out
    assert "已有 1 名：甲" in out, out
    # 读数二：已满 2 名（还差 0）
    assert "b.py（2/2）" in out, out
    assert "已有 2 名：乙、丙" in out, out
    # 读数三：还没人签
    assert "c.py（0/2，还差 2 名不同 reviewer）" in out, out
    # 每条的 sha256 前 12 位（读数必须来自台账，不是"看起来像 hash"）
    ledger = G.load_ledger(G.ledger_default_path(root))
    for name in FILES:
        entry = ledger.entry_for(name)
        assert entry is not None
        assert entry.sha256[:12] in out, f"{name} 的 sha256 前 12 位要打在清单里：\n{out}"


# --------------------------------------------------------------------------- 判据②：跨批次


def test_one_reviewer_then_another_reaches_two_of_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """判据②：一次签 3 条（各记 1 名），换另一名再签一次（3 条都 2/2、退出码 0）。"""
    root = _make_ws(tmp_path)
    common = ["--all", "--scope", SCOPE, "--verdict", "逐行走查通过",
              "--note", "2026-10-23 第一批", "--yes", "--root", str(root)]

    code = B.main([*common, "--reviewer", "甲"])
    out = capsys.readouterr().out
    assert code == 1, f"只签了 1 名 ⇒ 退出码 1：\n{out}"
    for name in FILES:
        assert _names(root, name) == ["甲"], f"{name} 应该只记了 1 名 reviewer：\n{out}"
        assert f"… {name}（1/2，还差 1 名不同 reviewer）" in out, out

    code = B.main([*common, "--reviewer", "乙"])
    out = capsys.readouterr().out
    assert code == 0, f"两名不同 reviewer 都签了 ⇒ 退出码 0：\n{out}"
    for name in FILES:
        assert _names(root, name) == ["甲", "乙"], f"{name} 应该有 2 名不同 reviewer：\n{out}"
        assert f"✔ {name}（2/2）" in out, out


# --------------------------------------------------------------------------- 判据③：重名


def test_same_reviewer_twice_in_one_batch_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """判据③：同一批里重名 ⇒ 退出码 2，台账一字未动（全角/零宽写法算同一个人）。"""
    root = _make_ws(tmp_path)
    before = _ledger_sha256(root)

    code = B.main([
        "--all", "--reviewer", "张三", "--reviewer", "张三",
        "--scope", SCOPE, "--yes", "--root", str(root),
    ])
    out = capsys.readouterr().out
    assert code == 2, f"重名 ⇒ 拒绝（2）：\n{out}"
    assert _ledger_sha256(root) == before, "拒绝时台账一个字都不许写"

    # 归一化之后是同一个人（零宽字符）也必须拒 —— 门判"同一个姓名"只有一处实现。
    code = B.main([
        "--all", "--reviewer", "张三", "--reviewer", "张三\u200b",
        "--scope", SCOPE, "--yes", "--root", str(root),
    ])
    out = capsys.readouterr().out
    assert code == 2, f"零宽写法是同一个姓名 ⇒ 也要拒（2）：\n{out}"
    assert _ledger_sha256(root) == before, "拒绝时台账一个字都不许写"
    for name in FILES:
        assert _names(root, name) == [], "重名的那一批一条都不该签上"


# --------------------------------------------------------------------------- 判据④：--yes


def test_missing_yes_on_non_interactive_stdin_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """判据④：缺 `--yes` 且 stdin 不是终端 ⇒ 拒绝（2），台账一字未动。

    stdin 里刻意写着 `yes`：判据是"是不是终端"，不是"输入里有没有 yes" ——
    非交互环境里没有人能看见那份清单，所以没有 `--yes` 就不许签。
    """
    root = _make_ws(tmp_path)
    before = _ledger_sha256(root)
    monkeypatch.setattr(sys, "stdin", io.StringIO("yes\n"))

    code = B.main([
        "--all", "--reviewer", "甲", "--scope", SCOPE, "--root", str(root),
    ])
    out = capsys.readouterr().out

    assert code == 2, f"非交互 + 没有 --yes ⇒ 拒绝（2）：\n{out}"
    assert "--yes" in out, f"拒绝的话必须说清缺哪个开关：\n{out}"
    assert _ledger_sha256(root) == before, "拒绝时台账一个字都不许写"
    for name in FILES:
        assert _names(root, name) == []


# --------------------------------------------------------------------------- 判据⑤：dry-run


def test_dry_run_leaves_the_ledger_sha256_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """判据⑤：`--dry-run` 只打印不写 —— 台账 sha256 不变。"""
    root = _make_ws(tmp_path)
    before = _ledger_sha256(root)

    code = B.main([
        "--all", "--reviewer", "甲", "--scope", SCOPE, "--dry-run", "--root", str(root),
    ])
    out = capsys.readouterr().out

    assert "dry-run" in out, f"dry-run 必须自己说出来：\n{out}"
    assert code == 1, f"dry-run 时这 3 条还没满足 2 名 ⇒ 退 1：\n{out}"
    assert _ledger_sha256(root) == before, "dry-run 台账 sha256 必须不变"
    for name in FILES:
        assert _names(root, name) == []


# --------------------------------------------------------------------------- 判据⑥：反真空


def test_stubbed_readback_cannot_relabel_one_reviewer_as_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """判据⑥（反真空）：把"签完回读"打桩成恒满足，只签 1 名的那一步仍然必须报未满足。

    这一条盯的是"结论从哪来"：退出码若由回读的 satisfied 决定，打桩之后这里就会
    得到 0（"签成了"），而盘上只有 1 名 —— 那正是本仓库记过的"读数被当成结论"。
    判据同时看盘上的事实（用门的读函数），不只看退出码。
    """
    root = _make_ws(tmp_path)
    monkeypatch.setattr(
        B, "readback", lambda *a, **k: B.SignState(key="?", names=("甲", "乙"), required=2)
    )

    code = B.main([
        "--all", "--reviewer", "甲", "--scope", SCOPE, "--yes", "--root", str(root),
    ])
    out = capsys.readouterr().out

    assert code == 1, f"打桩的回读说满足，退出码仍须是 1（未满足）：\n{out}"
    for name in FILES:
        assert _names(root, name) == ["甲"], f"{name} 盘上只有 1 名 reviewer：\n{out}"
