"""证据面工具（`agentflow evidence`）的判据 —— 依据 `draft/30` §T0-7。

这一组守的是"正文搬到产物外面之后，可复核性还在不在"：

- 正控：引用形态的产物能被独立核过（含我方自己的页号复算，不调用被审实现）；
- 负控：删掉 store 文件、把页号写错 ⇒ 必须变红并点名是哪一层坏；
- `store`：空库与"零字节"必须分开说；
- `migrate`：默认 dry-run 绝不动盘；`--apply` 才改写，且逐份备份、改完仍可核。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentflow import cli
from agentflow import fulltextstore as FS

QUOTE = "the identity element is unique"


def _make_run(tmp_path: Path, pages: list[str], *, quote: str = QUOTE,
              rec_page: int = 1) -> tuple[Path, Path]:
    """造一个最小项目 + 一次运行的产物（引用形态）；返回 `(项目根, 运行目录)`。"""
    project = tmp_path / "projects" / "project1"
    run_dir = project / "out" / "run-1"
    run_dir.mkdir(parents=True)
    ref = FS.put(pages, store_dir=FS.store_dir_for(project), pdf_sha256="ab" * 32,
                 pdf_path=str(project / "library" / "x.pdf"), pdf_bytes=3, backend="pdf")
    evidence = {"sources": [{"source_id": "S1", "title": "x",
                             "fulltext": {"status": "ok", "text_ref": ref,
                                          "text_store": "ref", "pages": len(pages),
                                          "sha256": "ab" * 32, "path": ref["path"]}}]}
    (run_dir / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    claims = {"claims": [{"claim_id": "C1", "verdict": "verified", "level": "fulltext",
                          "quote": quote, "locator": {"kind": "page", "page": rec_page}}]}
    (run_dir / "claims.json").write_text(
        json.dumps(claims, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return project, run_dir


def test_verify_on_inline_artifact_says_not_recomputed(tmp_path: Path, capsys: pytest.CaptureFixture):
    """负控（三态）：内联形态的产物 ⇒ 说"未复算"且退出码 0。

    为什么这条必须存在：第一版工具在这里报了"页不符"（它根本没读到页），
    把一次读取能力的缺失记成了产物的缺陷 —— 那是把"没查成"折成"查过了、不符"。
    真实历史产物（内联形态的 evidence.json）当场撞出这个假警报。
    """
    project = tmp_path / "projects" / "project1"
    run_dir = project / "out" / "run-1"
    run_dir.mkdir(parents=True)
    evidence = {"sources": [{"source_id": "S1", "abstract": "x",
                             "fulltext": {"status": "ok", "text_pages": ["a", "b"],
                                          "text_store": "inline"}}]}
    (run_dir / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False) + "\n",
                                           encoding="utf-8", newline="\n")
    claims = {"claims": [{"claim_id": "C1", "quote": QUOTE, "verdict": "verified",
                          "level": "fulltext", "locator": {"kind": "page", "page": 1}}]}
    (run_dir / "claims.json").write_text(json.dumps(claims, ensure_ascii=False) + "\n",
                                         encoding="utf-8", newline="\n")

    rc = cli.main(["--plain", "evidence", "verify", str(run_dir)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "未复算" in out
    assert "页不符" not in out, "没复算过就不许说不符"


def test_verify_ok_reports_page_agreement(tmp_path: Path, capsys: pytest.CaptureFixture):
    """正控：引用可读 + 页号与我方独立搜出来的一致 ⇒ 退出码 0。"""
    _project, run_dir = _make_run(tmp_path, ["page one", f"page two says {QUOTE}"], rec_page=2)
    rc = cli.main(["--plain", "evidence", "verify", str(run_dir)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "页一致" in out and "坏 0 条" in out


def test_verify_flags_missing_store_file(tmp_path: Path, capsys: pytest.CaptureFixture):
    """负控：store 文件被删 ⇒ 退出码 1，且点名 `store_file_missing`（是哪一层坏）。"""
    project, run_dir = _make_run(tmp_path, ["page one"])
    ev = json.loads((run_dir / "evidence.json").read_text(encoding="utf-8"))
    Path(ev["sources"][0]["fulltext"]["text_ref"]["path"]).unlink()
    rc = cli.main(["--plain", "evidence", "verify", str(run_dir)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "store_file_missing" in out


def test_verify_flags_page_mismatch(tmp_path: Path, capsys: pytest.CaptureFixture):
    """负控：`claims.json` 登记的页号与我方搜到的不符 ⇒ 退出码 1 且标"页不符"。"""
    _project, run_dir = _make_run(tmp_path, ["page one", f"page two says {QUOTE}"], rec_page=1)
    rc = cli.main(["--plain", "evidence", "verify", str(run_dir)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "页不符" in out


def test_verify_unreadable_target_is_not_checked(tmp_path: Path, capsys: pytest.CaptureFixture):
    """三态：目标不在 ⇒ 2（没查成），不许折成 1（查过了、有问题）。"""
    rc = cli.main(["--plain", "evidence", "verify", str(tmp_path / "nope")])
    assert rc == 2
    assert "没查成" in capsys.readouterr().err


def test_store_reports_empty_explicitly(tmp_path: Path, capsys: pytest.CaptureFixture):
    """空库与"零字节"必须分开说：空 ⇒ 明说空，退出码 0。"""
    project = tmp_path / "projects" / "project1"
    project.mkdir(parents=True)
    rc = cli.main(["--plain", "evidence", "store", str(project)])
    assert rc == 0
    assert "空" in capsys.readouterr().out


def test_store_counts_references(tmp_path: Path, capsys: pytest.CaptureFixture):
    """有库时要点出"被几份产物引用"——那是"只存一份"这件事的可核读数。"""
    project, _run_dir = _make_run(tmp_path, ["a", "b"])
    rc = cli.main(["--plain", "evidence", "store", str(project)])
    out = capsys.readouterr().out
    assert rc == 0 and "被 1 份产物引用" in out


def test_migrate_dry_run_does_not_touch_the_artifact(tmp_path: Path, capsys: pytest.CaptureFixture):
    """`migrate` 默认 dry-run：产物逐字节不动（改的是历史证据本体，必须人点头）。"""
    project, run_dir = _make_run(tmp_path, ["a", "b"])
    ev_path = run_dir / "evidence.json"
    # 先把这份产物改成"内联形态"，模拟历史产物
    ev = json.loads(ev_path.read_text(encoding="utf-8"))
    ft = ev["sources"][0]["fulltext"]
    pages = FS.load(ft["text_ref"])[0]
    ft.pop("text_ref", None)
    ft["text_pages"] = pages
    ft["text_store"] = "inline"
    ev_path.write_text(json.dumps(ev, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8", newline="\n")
    before = ev_path.read_bytes()

    rc = cli.main(["--plain", "evidence", "migrate", str(project)])
    out = capsys.readouterr().out
    assert rc == 0 and "dry-run" in out
    assert ev_path.read_bytes() == before, "dry-run 绝不许动盘"


def test_migrate_apply_rewrites_and_backs_up(tmp_path: Path, capsys: pytest.CaptureFixture):
    """`--apply` 才改写：产物变成引用形态、有备份，而且改完仍能被 verify 核过。"""
    project, run_dir = _make_run(tmp_path, [f"page one says {QUOTE}"], rec_page=1)
    ev_path = run_dir / "evidence.json"
    ev = json.loads(ev_path.read_text(encoding="utf-8"))
    ft = ev["sources"][0]["fulltext"]
    pages = FS.load(ft["text_ref"])[0]
    ft.pop("text_ref", None)
    ft["text_pages"] = pages
    ft["text_store"] = "inline"
    ev_path.write_text(json.dumps(ev, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8", newline="\n")

    rc = cli.main(["--plain", "evidence", "migrate", str(project), "--apply"])
    out = capsys.readouterr().out
    assert rc == 0 and "已迁移" in out
    after = json.loads(ev_path.read_text(encoding="utf-8"))["sources"][0]["fulltext"]
    assert after["text_store"] == "ref" and "text_ref" in after and "text_pages" not in after

    backups = list((project / "temp").glob("evidence-migrate-*/run-1-evidence.json"))
    assert backups, "改历史证据必须先备份"

    rc2 = cli.main(["--plain", "evidence", "verify", str(run_dir)])
    assert rc2 == 0, capsys.readouterr().out
