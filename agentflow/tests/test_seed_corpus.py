"""SEEDCORPUS 判据：种子包可复算、投放只放文件不写台账、开关默认关。

四条（与交付的 a–d 对应）：

a. 建工作区 + 开种子 ⇒ `library/` 有文件、`data/literature.json` 0 行、
   `SEED-README.md` 在盘上；
b. 不开开关 ⇒ 什么都不投（正控）；
c. manifest 与盘上 sha256 一致；`--verify` 抓得出被改坏的字节；
d. 反真空：把"不许写台账"打桩掉（伪 seeder 往台账写一行）⇒ a 必红。

这里的种子都是临时造的（`tmp_path`），不复制真机那 17 MB；真种子包的清单
一致性另有一条只算 sha256 的轻判据。
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from agentflow import projects as P
from agentflow import seedinject as SI

_PDF_TEXT = (
    "Hyperplane sections of convex bodies and the volume estimate theorem "
    "give a sharp bound for maximal central sections of the unit cube. "
    "The argument uses Brascamp-Lieb inequalities, rearrangement, and a "
    "careful approximation of the body by polytopes with many facets. "
)


def _load_script():
    """把 `scripts/seed_corpus.py` 当模块加载（它自己会注入 src/）。"""
    path = Path(__file__).resolve().parents[1] / "scripts" / "seed_corpus.py"
    spec = importlib.util.spec_from_file_location("seed_corpus_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_pdf(text: str) -> bytes:
    """造一份有文本层的真 PDF（按页切开，避免文本框溢出丢字）。"""
    import fitz

    doc = fitz.open()
    rect = fitz.Rect(50, 50, 550, 790)
    for start in range(0, max(len(text), 1), 2000):
        page = doc.new_page()
        page.insert_textbox(rect, text[start:start + 2000], fontsize=8)
    data = doc.tobytes()
    doc.close()
    return data


def _blank_pdf() -> bytes:
    """造一份没有文本层的 PDF（扫描件的读数形态：pages=[]、text=""）。"""
    import fitz

    doc = fitz.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def _sha256(data: bytes) -> str:
    """一段字节的 sha256（测试内部用，判据与产品实现各算各的）。"""
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _seed_package(tmp_path: Path, *, count: int = 1) -> Path:
    """造一个最小种子包：files/ + MANIFEST.json + README.md。"""
    seed = tmp_path / "seed" / "literature"
    files = seed / "files"
    files.mkdir(parents=True)
    entries = []
    for index in range(count):
        data = _make_pdf(_PDF_TEXT * (2 + index))
        name = f"{_sha256(data)[:12]}-seed-{index}.pdf"
        (files / name).write_bytes(data)
        entries.append({
            "path": f"files/{name}",
            "sha256": _sha256(data),
            "bytes": len(data),
            "title": f"Seed paper {index}",
            "doi": f"10.1000/seed.{index}",
            "year": 2020 + index,
            "source": {"workspace": "lp-ball-99", "lit_id": f"{index:06d}",
                       "path": f"library/{index:06d}/{name}"},
            "extract": {"chars": len(_PDF_TEXT * (2 + index))},
        })
    manifest = {
        "format": SI.FORMAT, "version": SI.VERSION,
        "scope": "test", "criteria": {"min_chars": 1},
        "count": len(entries), "total_bytes": sum(e["bytes"] for e in entries),
        "files": entries,
    }
    (seed / SI.MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    (seed / "README.md").write_text("# test seed\n", encoding="utf-8", newline="\n")
    return seed


def _write_workspace(project: Path, rows: list[dict]) -> None:
    """造一个带 `data/literature.json` 与 `library/` 的最小工作区。"""
    (project / "data").mkdir(parents=True, exist_ok=True)
    (project / "library").mkdir(parents=True, exist_ok=True)
    (project / "data" / "literature.json").write_text(
        json.dumps({"schema_version": 2, "rows": rows}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")


def _lit_row(project: Path, lit_id: str, title: str, doi: str,
             filename: str, data: bytes | None, *, year: int = 2020) -> dict:
    """一行"下载成功"的台账（data 为 None 表示盘上故意缺文件）。"""
    rel = f"{lit_id}/{filename}"
    if data is not None:
        (project / "library" / lit_id).mkdir(parents=True, exist_ok=True)
        (project / "library" / rel).write_bytes(data)
    return {
        "lit_id": lit_id, "title": title, "doi": doi, "year": year, "path": rel,
        "download": {"status": "ok", "bytes": len(data) if data is not None else 123,
                     "sha256": _sha256(data) if data is not None else "0" * 64},
    }


def _literature_rows(project: Path) -> list[dict]:
    """读工作区台账的行（不折成"没有文件就是 0 行"）。"""
    path = project / "data" / "literature.json"
    assert path.is_file(), "工作区连 data/literature.json 都没有"
    return list(json.loads(path.read_text(encoding="utf-8")).get("rows") or [])


def _criterion_a(project: Path) -> None:
    """判据 a 的三格：有文件 / 台账 0 行 / SEED-README 在。"""
    files = sorted((project / "library").glob("*.pdf"))
    assert files, "library/ 里没有种子文件"
    rows = _literature_rows(project)
    assert rows == [], f"种子被直接写进了台账：{len(rows)} 行"
    marker = project / "SEED-README.md"
    assert marker.is_file(), "工作区根没有 SEED-README.md"
    text = marker.read_text(encoding="utf-8")
    assert "未入库" in text, "SEED-README 必须说清这些种子未入库"


def test_a_cold_workspace_with_seed_lands_files_only(tmp_path: Path, monkeypatch) -> None:
    """a：建工作区 + 开种子 ⇒ 有文件、台账 0 行、README 在。"""
    seed = _seed_package(tmp_path)
    monkeypatch.setenv(SI.ENV_SEED_DIR, str(seed))
    root = tmp_path / "projects"
    ref = P.resolve(root, "seeded", start="cold")
    P.create_project(ref, seed_literature=True, now="2026-01-01T00:00:00+08:00")
    _criterion_a(ref.path)
    assert len(list((ref.path / "library").glob("*.pdf"))) == 1


def test_b_without_the_switch_nothing_is_landed(tmp_path: Path, monkeypatch) -> None:
    """b：不开开关 ⇒ 不投文件、不落 README（正控）。"""
    monkeypatch.setenv(SI.ENV_SEED_DIR, str(_seed_package(tmp_path)))
    root = tmp_path / "projects"
    ref = P.resolve(root, "plain", start="cold")
    P.create_project(ref, now="2026-01-01T00:00:00+08:00")
    assert not list((ref.path / "library").glob("*.pdf"))
    assert not (ref.path / "SEED-README.md").exists()
    assert _literature_rows(ref.path) == []


def test_seed_is_idempotent_and_reports_already(tmp_path: Path, monkeypatch) -> None:
    """再投一次不会重复复制（SEED-README 就是"投过了"的标记）。"""
    seed = _seed_package(tmp_path)
    monkeypatch.setenv(SI.ENV_SEED_DIR, str(seed))
    root = tmp_path / "projects"
    ref = P.resolve(root, "twice", start="cold")
    P.create_project(ref, seed_literature=True, now="2026-01-01T00:00:00+08:00")
    first = len(list((ref.path / "library").glob("*.pdf")))
    got = SI.seed_workspace(ref.path, seed_dir=seed)
    assert got["already"] is True and got["copied"] == 0
    assert len(list((ref.path / "library").glob("*.pdf"))) == first


def test_c_build_dedups_and_verify_catches_tampered_bytes(tmp_path: Path) -> None:
    """c：build 按判据收种子；verify 绿；改一个字节 ⇒ verify 红。"""
    script = _load_script()
    projects = tmp_path / "projects"
    project = projects / "lp-ball-99"
    good_short = _make_pdf(_PDF_TEXT * 2)
    good_long = _make_pdf(_PDF_TEXT * 6)
    rows = [
        _lit_row(project, "000000", "Same Paper", "10.1000/same", "short.pdf", good_short),
        _lit_row(project, "000001", "Same Paper", "10.1000/same", "long.pdf", good_long),
        _lit_row(project, "000002", "Scanned", "10.1000/scan", "scan.pdf", _blank_pdf()),
        _lit_row(project, "000003", "Missing", "10.1000/missing", "gone.pdf", None),
    ]
    _write_workspace(project, rows)
    html = (b"<!DOCTYPE html><html><body>" + b"<p>" + _PDF_TEXT.encode() * 8 + b"</p></body></html>")
    html_row = _lit_row(project, "000004", "Landing", "10.1000/landing", "landing.html", None)
    (project / "library" / "000004").mkdir(parents=True, exist_ok=True)
    (project / "library" / "000004" / "landing.html").write_bytes(html)
    html_row["download"] = {"status": "ok", "bytes": len(html), "sha256": _sha256(html)}
    with (project / "data" / "literature.json").open("w", encoding="utf-8", newline="\n") as fh:
        json.dump({"schema_version": 2, "rows": rows + [html_row]}, fh,
                  ensure_ascii=False, indent=1)
        fh.write("\n")

    seed = tmp_path / "seed"
    built = script.build_seed(projects, seed, include_all=False)
    assert built["ok"] is True
    manifest = json.loads((seed / "MANIFEST.json").read_text(encoding="utf-8"))
    # 同一篇（同 DOI）只留一份：留抽读字数多的 long.pdf。
    assert manifest["count"] == 1
    assert manifest["files"][0]["sha256"] == _sha256(good_long)
    assert len(manifest["files"][0]["duplicates"]) == 1
    # 扫描件 / 缺文件 / 非 PDF 都没进种子。
    assert all("scan" not in e["path"] and "gone" not in e["path"]
               and "landing" not in e["path"] for e in manifest["files"])

    assert script.verify_seed(seed)["ok"] is True

    target = seed / manifest["files"][0]["path"]
    data = bytearray(target.read_bytes())
    data[0] ^= 0xFF
    target.write_bytes(bytes(data))
    result = script.verify_seed(seed)
    assert result["ok"] is False
    assert "sha256" in "；".join(result["files"][0]["problems"])


def test_c_the_repo_seed_manifest_matches_the_disk() -> None:
    """c（真种子）：清单里每一份的 sha256 / 字节数都与盘上一致。"""
    seed = SI.default_seed_dir()
    manifest, problem = SI.read_manifest(seed)
    assert problem == "", problem
    assert manifest["count"] >= 1
    for entry in manifest["files"]:
        path = seed / entry["path"]
        assert path.is_file(), f"清单里有、盘上没有：{entry['path']}"
        assert _sha256(path.read_bytes()) == entry["sha256"]
        assert path.stat().st_size == entry["bytes"]


def test_d_anti_vacuum_a_stub_that_writes_the_ledger_turns_a_red(
        tmp_path: Path, monkeypatch) -> None:
    """d：反真空 —— 伪 seeder 往台账写一行 ⇒ 判据 a 必红。"""
    seed = _seed_package(tmp_path)
    monkeypatch.setenv(SI.ENV_SEED_DIR, str(seed))
    real_seed = SI.seed_workspace

    def bad_seed(project, *, seed_dir=None, force=False):
        """故意违反"不写台账"：复制文件之后又往 literature.json 写了一行。"""
        ws = Path(project)
        destination = ws / "library"
        destination.mkdir(parents=True, exist_ok=True)
        source = sorted((seed / "files").glob("*.pdf"))[0]
        shutil.copyfile(source, destination / source.name)
        (ws / "SEED-README.md").write_text("未入库（其实是假的）", encoding="utf-8", newline="\n")
        ledger = ws / "data" / "literature.json"
        blob = json.loads(ledger.read_text(encoding="utf-8"))
        blob.setdefault("rows", []).append(
            {"lit_id": "000000", "title": "stub", "download": {"status": "ok"}})
        ledger.write_text(json.dumps(blob, ensure_ascii=False, indent=1) + "\n",
                          encoding="utf-8", newline="\n")
        return {"enabled": True, "copied": 1, "skipped": 0, "problem": "", "files": []}

    monkeypatch.setattr(SI, "seed_workspace", bad_seed)
    root = tmp_path / "projects"
    ref = P.resolve(root, "victim", start="cold")
    P.create_project(ref, seed_literature=True, now="2026-01-01T00:00:00+08:00")
    with pytest.raises(AssertionError, match="台账"):
        _criterion_a(ref.path)

    # 同一判据打在真 seeder 上必须是绿的：红不是因为它永远红。
    monkeypatch.setattr(SI, "seed_workspace", real_seed)
    real = P.resolve(root, "control", start="cold")
    P.create_project(real, seed_literature=True, now="2026-01-01T00:00:00+08:00")
    _criterion_a(real.path)


def test_the_start_switch_is_explicit_and_default_off(tmp_path: Path) -> None:
    """开关是显式参数：--dry-run 收下它，但一个字节都不写；不给就不投。"""
    from agentflow import cli

    projects = tmp_path / "projects"
    rc = cli.main(["start", "--project", "dry", "--mode", "cold", "--task", "probe",
                   "--seed-literature", "--dry-run", "--projects-dir", str(projects)])
    assert rc == 0
    assert not (projects / "dry").exists()
    rc_bad = cli.main(["start", "--mode", "topic", "--task", "probe",
                       "--seed-literature", "--dry-run", "--projects-dir", str(projects)])
    assert rc_bad == 2, "只对 project / research 两档有意义的旗标要被拒收"
