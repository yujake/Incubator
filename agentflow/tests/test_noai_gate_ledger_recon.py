# -*- coding: utf-8 -*-
"""`--check-ledger`（清单 ↔ 台账非对称对账，`H-11`）的判据。

这一节守的是三件套里此前没有任何命令覆盖的那一对：
`--check-consistency` 只比对清单的两个落位（`.noai-paths` 与 `AGENTS.md`），
`--check-approvals` 只在命中禁改区之后、且只针对本次改动集逐条判 ——
于是"清单里有一条路径从来没有被登记过"这件事没有任何地方会响。

口径（`H-11` 裁决 = 选项 A）：

- 只查一个方向：清单里的每条唯一路径，台账里要有条目；台账里那些清单外的
  历史条目不进判据（历史记录只增，保护范围会收窄，两者本来就不该相等）；
- 差集分两类：盘上不存在 ⇒ 刻意预登记（正常状态）；盘上存在 ⇒ 漏登记（非零退出）；
- 三态与退出码：0 = 干净；1 = 有漏登记；2 = 没查成（清单或台账读不到 / 解析不了）。
  这套码只属于本命令，改动集判定模式的 0 / 1 / 2 一个都没动（本文件末尾有一条用例钉它）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

#: 把仓库根注入 `sys.path`（`scripts` 是顶层包；conftest.py 只注入了 `src/`）。
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts import noai_gate as G  # noqa: E402

#: 真实清单与真实台账（正控的对象就是它们）。
REAL_MANIFEST = _ROOT / G.MANIFEST_NAME
REAL_LEDGER = _ROOT / G.LEDGER_NAME

#: 今天唯一那条刻意预登记的路径（`src/agentflow/release_check.py` 的登记理由逐字
#: 就是"登记时并不存在：先登记路径，一旦有人在这里新建它，它会自动落入本清单"）。
#: 它是本条判据"落地即绿"的那一格：差集非空而退出码仍是 0。
KNOWN_PRE_REGISTRATION = "src/agentflow/release_check.py"


def _make_root(
    tmp_path: Path,
    *,
    on_disk: tuple[str, ...] = (),
    in_manifest: tuple[str, ...] = (),
    in_ledger: tuple[str, ...] = (),
) -> Path:
    """造一个小世界：盘上文件 / 清单条目 / 台账条目三组各自独立给出。

    三组分开是刻意的：本判据要区分的正是"盘上有没有"与"台账里有没有"这两件事，
    夹具若把它们绑在一起，就测不出预登记与漏登记的区别了。
    """
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    for rel in on_disk:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x = 1\n", encoding="utf-8", newline="\n")

    lines = ["[category: auth-audit] 七、权限与审计（夹具）"]
    for rel in in_manifest:
        lines.append(f"{rel}  [category: auth-audit]  夹具理由：为什么它属于禁改区")
    (root / G.MANIFEST_NAME).write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )

    entries = [
        {
            "path": rel,
            "glob": rel,
            "category": "auth-audit",
            "sha256": G.sha256_file(root / rel) if (root / rel).is_file() else "0" * 64,
            "authored": "unknown",
            "authored_basis": "inferred",
            "change_note": "夹具",
            "changed_this_session": None,
            "reviewers": [],
        }
        for rel in in_ledger
    ]
    (root / G.LEDGER_NAME).write_text(
        json.dumps(
            {
                "ledger_version": G.LEDGER_VERSION,
                "generated_at": "2026-09-27T00:00:00+08:00",
                "entries": entries,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return root


# ============================================================ 正控：真实仓库落地即绿


def test_real_repo_reconciliation_is_clean_and_names_the_pre_registration() -> None:
    """正控：今天的真实清单与真实台账对账干净，且那条预登记被逐字点名。

    只钉不变量、不抄数字：清单会继续长（它是保护范围），而"抄下来的条数"
    下一次就会变成一条假的读数（本仓在别处已被这种"抄定值"咬过）。
    """
    rec = G.check_manifest_ledger()
    assert rec.verdict == "clean", rec.explanation
    assert rec.exit_code == 0
    assert rec.missing_registration == (), f"今天不该有漏登记：{rec.missing_registration}"
    assert len(rec.manifest_paths) >= 20, f"清单只解析出 {len(rec.manifest_paths)} 条唯一路径"
    assert len(rec.manifest_paths) == len(set(rec.manifest_paths)), "唯一路径里有重复"

    pre = [r["path"] for r in rec.pre_registered]
    assert KNOWN_PRE_REGISTRATION in pre, f"今天那条刻意预登记不见了：{pre}"
    for row in rec.pre_registered:
        assert row["kind"] == G.RECON_PRE_REGISTERED
        assert row["on_disk"] is False, f"{row['path']} 在盘上存在，那它不该算预登记"

    # 台账侧的读数必须与台账自己一致（不是从清单推出来的）。
    ledger = G.load_ledger()
    assert set(rec.ledger_entries) == {e.path for e in ledger.entries}


def test_real_repo_check_ledger_cli_is_green_and_lists_the_path(capsys) -> None:
    """正控（CLI）：`--check-ledger` 退出码 0，输出里逐字列出那条预登记路径。"""
    code = G.main(["--check-ledger"])
    out = capsys.readouterr().out
    assert code == 0, f"当前字节上 `--check-ledger` 必须是 0：\n{out}"
    assert KNOWN_PRE_REGISTRATION in out, f"预登记路径必须被点名：\n{out}"
    assert "刻意预登记" in out, out
    assert "[clean]" in out, out


def test_real_repo_check_ledger_writes_nothing() -> None:
    """只读：跑一次对账之后，清单与台账的字节与 sha256 都不许变。

    这条不是形式主义：`--check-ledger` 与 `--baseline` / `--approve` 同住一个脚本，
    而"读命令顺手写了点什么"在这个仓库里是可复现的一族（台账的 hash 一漂，
    所有批准读数当场作废）。
    """
    before = {p: (p.read_bytes(), G.sha256_file(p)) for p in (REAL_MANIFEST, REAL_LEDGER)}
    assert G.main(["--quiet", "--check-ledger"]) == 0
    for p, (raw, digest) in before.items():
        assert p.read_bytes() == raw, f"{p.name} 被 `--check-ledger` 改动了"
        assert G.sha256_file(p) == digest, f"{p.name} 的内容 hash 变了"


def test_check_ledger_appears_in_help(capsys) -> None:
    """子命令必须在 `--help` 里出现（否则它只能靠读过源码的人知道）。"""
    with pytest.raises(SystemExit) as ei:
        G.build_parser().parse_args(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "--check-ledger" in out, out


# ============================================================ 两个差集类别必须被区分


def test_missing_registration_is_a_nonzero_verdict(tmp_path: Path, capsys) -> None:
    """漏登记 ⇒ 非零退出：盘上有这个文件、台账里却没有它的条目。

    这是本题要的那条判据（不是一行打印）：一条禁改区路径一次都没有被登记过，
    "改它要 2 名 reviewer"这句话在台账这一层找不到可比的版本。
    """
    root = _make_root(tmp_path, on_disk=("src/a.py",), in_manifest=("src/a.py",))
    rec = G.check_manifest_ledger(root=root)
    assert rec.verdict == "requires_human", rec.explanation
    assert rec.exit_code == 1
    assert [r["path"] for r in rec.missing_registration] == ["src/a.py"]
    assert rec.missing_registration[0]["kind"] == G.RECON_MISSING_REGISTRATION
    assert rec.pre_registered == ()

    code = G.main(["--check-ledger", "--root", str(root)])
    out = capsys.readouterr().out
    assert code == 1, f"漏登记必须非零退出：\n{out}"
    assert "漏登记" in out and "src/a.py" in out, out


def test_pre_registration_is_marked_and_still_exit_zero(tmp_path: Path, capsys) -> None:
    """刻意预登记 ⇒ 标出来但退出码仍是 0（清单开头那句"先登记路径"纪律的落地形态）。"""
    root = _make_root(tmp_path, on_disk=(), in_manifest=("src/ghost.py",))
    rec = G.check_manifest_ledger(root=root)
    assert rec.verdict == "clean", rec.explanation
    assert rec.exit_code == 0
    assert [r["path"] for r in rec.pre_registered] == ["src/ghost.py"]
    assert rec.pre_registered[0]["kind"] == G.RECON_PRE_REGISTERED
    assert rec.missing_registration == ()

    code = G.main(["--check-ledger", "--root", str(root)])
    out = capsys.readouterr().out
    assert code == 0, f"预登记不该让门变红：\n{out}"
    assert "刻意预登记" in out and "src/ghost.py" in out, out


def test_both_kinds_of_difference_are_distinguished_in_one_run(tmp_path: Path) -> None:
    """同一次对账里两类差集必须分开：一条预登记 + 一条漏登记 ⇒ 退出码只由漏登记决定。"""
    root = _make_root(
        tmp_path,
        on_disk=("src/a.py",),
        in_manifest=("src/a.py", "src/ghost.py"),
    )
    rec = G.check_manifest_ledger(root=root)
    assert rec.exit_code == 1
    assert [r["path"] for r in rec.pre_registered] == ["src/ghost.py"]
    assert [r["path"] for r in rec.missing_registration] == ["src/a.py"]


def test_duplicate_manifest_paths_are_counted_once(tmp_path: Path) -> None:
    """同一条路径在清单里出现两次（刻意的重复）只算一条：对账问的是路径有没有被登记。"""
    root = _make_root(
        tmp_path,
        on_disk=("src/a.py",),
        in_manifest=("src/a.py", "src/a.py"),
        in_ledger=("src/a.py",),
    )
    rec = G.check_manifest_ledger(root=root)
    assert rec.manifest_paths == ("src/a.py",)
    assert rec.exit_code == 0


def test_ledger_entries_outside_the_manifest_are_not_a_defect(tmp_path: Path) -> None:
    """反方向的差集不是缺陷：台账里的历史条目不被要求出现在清单里（刻意不要求对称）。"""
    root = _make_root(
        tmp_path,
        on_disk=("src/a.py", "src/old.py"),
        in_manifest=("src/a.py",),
        in_ledger=("src/a.py", "src/old.py"),
    )
    rec = G.check_manifest_ledger(root=root)
    assert rec.verdict == "clean", rec.explanation
    assert rec.exit_code == 0
    assert rec.ledger_only == ("src/old.py",)
    assert rec.missing_registration == ()


# ============================================================ 三态：没查成不是干净


def test_manifest_read_failure_is_unknown_not_clean(tmp_path: Path) -> None:
    """清单读不到 ⇒ unknown(2)，不是 clean：没查成与查过了没问题必须分得开。"""
    root = tmp_path / "empty"
    root.mkdir()
    rec = G.check_manifest_ledger(root=root)
    assert rec.verdict == "unknown"
    assert rec.exit_code == 2
    assert rec.verdict != "clean"
    assert G.main(["--quiet", "--check-ledger", "--root", str(root)]) == 2


def test_ledger_read_failure_is_unknown_not_clean(tmp_path: Path) -> None:
    """台账读不到 ⇒ unknown(2)，不是 clean（也不是"漏登记"那条 1）。"""
    root = _make_root(tmp_path, on_disk=("src/a.py",), in_manifest=("src/a.py",))
    (root / G.LEDGER_NAME).unlink()
    rec = G.check_manifest_ledger(root=root)
    assert rec.verdict == "unknown"
    assert rec.exit_code == 2
    assert rec.verdict != "requires_human"
    assert G.main(["--quiet", "--check-ledger", "--root", str(root)]) == 2


def test_broken_ledger_is_unknown_not_missing_registration(tmp_path: Path) -> None:
    """台账是坏 JSON ⇒ unknown(2)：读不懂的台账不能拿来判"漏登记"。"""
    root = _make_root(tmp_path, on_disk=("src/a.py",), in_manifest=("src/a.py",))
    (root / G.LEDGER_NAME).write_text("{ 这不是 JSON", encoding="utf-8", newline="\n")
    rec = G.check_manifest_ledger(root=root)
    assert rec.verdict == "unknown"
    assert rec.exit_code == 2


# ============================================================ 输出形态与码表


def test_json_output_carries_the_two_sets_and_the_kind(tmp_path: Path, capsys) -> None:
    """`--json` 里两个差集必须分列，且每条带 `kind`（机器读的输出要比人读的更细）。"""
    root = _make_root(
        tmp_path,
        on_disk=("src/a.py", "src/old.py"),
        in_manifest=("src/a.py", "src/ghost.py"),
        in_ledger=("src/old.py",),
    )
    code = G.main(["--check-ledger", "--json", "--root", str(root)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["exit_code"] == 1
    assert payload["verdict"] == "requires_human"
    assert [r["path"] for r in payload["pre_registered"]] == ["src/ghost.py"]
    assert [r["path"] for r in payload["missing_registration"]] == ["src/a.py"]
    assert payload["pre_registered"][0]["kind"] == G.RECON_PRE_REGISTERED
    assert payload["missing_registration"][0]["kind"] == G.RECON_MISSING_REGISTRATION
    assert payload["ledger_only"] == ["src/old.py"]


def test_the_change_set_mode_exit_codes_are_unchanged(capsys) -> None:
    """新子命令不许动既有码表：改动集判定模式仍是 0 / 1 / 2，`--check-consistency` 仍是 0。

    这一条是"加了一个子命令"这类改动最容易踩坏的地方：把新命令的码表写进
    `_VERDICT_EXIT_CODES`，或者让新命令的早返回吞掉后面那几条输入校验。
    """
    assert G.main(["--quiet", "--check-consistency"]) == 0
    assert G.main(["--quiet", "--paths", "README.md"]) == 0
    assert G.main(["--quiet", "--paths", "src/agentflow/capabilities.py"]) == 1
    assert G.main(["--quiet"]) == 2
    out = capsys.readouterr().out
    assert out == "", f"`--quiet` 不许打印：{out!r}"


def test_a_hit_still_requires_two_approvals(capsys) -> None:
    """命中禁改区的读数没变：`requires_human` + `required_approvals=2`。"""
    result = G.check_paths(["src/agentflow/capabilities.py"])
    assert result.verdict == "requires_human"
    assert result.required_approvals == G.REQUIRED_APPROVALS_ON_HIT == 2
