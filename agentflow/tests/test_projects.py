"""`projects` 的判据：一个项目一个文件夹、默认命名、冷/热启动按文件夹在不在。

本文件里每一条"允许"的旁边都有一条"必须报错"：冷/热两档如果互相顶替，
用户说的"这次冷启动"就会被静默改成"在旧项目里又跑了一遍"，而产物上看不出来。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentflow import projects as P


def test_first_project_is_project1_and_names_increase(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    assert P.next_name(root) == "project1"
    P.create_project(P.resolve(root, None, start="auto"))
    assert P.next_name(root) == "project2"
    P.create_project(P.resolve(root, None, start="auto"))
    assert P.next_name(root) == "project3"


def test_deleted_number_is_not_reused(tmp_path: Path) -> None:
    """负控：删掉中间那个号之后，下一个名字不许回填它。

    回填会让两次不同的运行共用同一个路径，而"这个项目的历史"就再也说不清了。
    """
    root = tmp_path / "projects"
    P.create_project(P.resolve(root, None, start="auto"))   # project1
    second = P.resolve(root, None, start="auto")
    P.create_project(second)                                # project2
    import shutil
    shutil.rmtree(second.path)
    assert P.next_name(root) == "project3", "删掉的号不许重用"


def test_auto_uses_existence_as_the_criterion(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    cold = P.resolve(root, "project1", start="auto")
    assert cold.mode == "cold" and not cold.exists
    P.create_project(cold)
    warm = P.resolve(root, "project1", start="auto")
    assert warm.mode == "warm" and warm.exists
    assert "工作区" in warm.reason


def test_explicit_cold_refuses_an_existing_workspace(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    ref = P.resolve(root, "project1", start="auto")
    P.create_project(ref)
    with pytest.raises(P.ProjectExists) as exc:
        P.resolve(root, "project1", start="cold")
    assert "--start warm" in str(exc.value), "报错必须给出下一步，而不只是说不行"


def test_explicit_warm_refuses_a_missing_project(tmp_path: Path) -> None:
    with pytest.raises(P.ProjectMissing):
        P.resolve(tmp_path / "projects", "project1", start="warm")


def test_a_foreign_directory_is_neither_cold_nor_warm(tmp_path: Path) -> None:
    """负控：别人的目录不许被当成工作区初始化进去（那会往里写一堆表文件）。"""
    root = tmp_path / "projects"
    junk = root / "project1"
    junk.mkdir(parents=True)
    (junk / "我的资料.txt").write_text("don't touch", encoding="utf-8")
    with pytest.raises(P.ProjectNotAWorkspace):
        P.resolve(root, "project1", start="auto")
    assert (junk / "我的资料.txt").read_text(encoding="utf-8") == "don't touch"


def test_empty_existing_folder_counts_as_cold(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    (root / "project1").mkdir(parents=True)
    ref = P.resolve(root, "project1", start="auto")
    assert ref.mode == "cold" and "空" in ref.reason


def test_plan_writes_nothing(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    info = P.plan(root, None, start="auto", books_dir="D:\\books", topic="t")
    assert info["project"]["name"] == "project1" and info["will_create"] is True
    assert list(root.iterdir()) == [], "plan 只说明会怎么跑，不许建目录"


def test_run_project_records_cold_then_warm(tmp_path: Path, monkeypatch) -> None:
    """冷启动建工作区 + 登记书；热启动复用同一个工作区且不重复登记。"""
    root = tmp_path / "projects"
    books = tmp_path / "books"
    books.mkdir()
    fitz = pytest.importorskip("fitz", reason="没有 fitz 就造不出带文本层的 PDF")
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "A group is a set with an operation.")
    doc.save(str(books / "甲书.pdf"))
    doc.close()

    calls: list[dict] = []

    def _fake_run_topic(store, **kw):
        calls.append(kw)
        out = Path(kw["out_dir"])
        out.mkdir(parents=True, exist_ok=True)
        for name in ("run-manifest.json", "claims.json", "evidence.json",
                     "cost.json", "report.md", "model-transcript.jsonl"):
            (out / name).write_text("{}", encoding="utf-8")
        return {"exit_code": 0, "reason": "success", "calls": 1,
                "spent_usd_this_run": 0.0, "artifacts": [
                    "run-manifest.json", "claims.json", "evidence.json",
                    "cost.json", "report.md", "model-transcript.jsonl"]}

    cold = P.run_project(root, name="project1", start="cold", topic="t",
                         books_dir=books, run_topic_fn=_fake_run_topic,
                         now="2026-01-01T00:00:00+08:00")
    assert cold["project"]["mode"] == "cold"
    assert cold["run"]["ingest"]["counts"]["ingested"] == 1
    assert Path(cold["run"]["out_dir"]).name == "run-1"

    warm = P.run_project(root, name="project1", start="warm", topic="t",
                         books_dir=books, run_topic_fn=_fake_run_topic,
                         now="2026-01-02T00:00:00+08:00")
    assert warm["project"]["mode"] == "warm"
    assert warm["run"]["ingest"]["counts"]["already_present"] == 1
    assert warm["run"]["ingest"]["counts"]["ingested"] == 0, "热启动不许重复登记"
    assert Path(warm["run"]["out_dir"]).name == "run-2"

    card = json.loads((root / "project1" / "project.json").read_text(encoding="utf-8"))
    assert card["cold_runs"] == 1 and card["warm_runs"] == 1
    assert [r["mode"] for r in card["runs"]] == ["cold", "warm"]
    assert card["last_mode"] == "warm"

    # 检索接缝必须真的传给了 run_topic：本地源的名字与两个函数都要在。
    assert calls and calls[0]["search_fn"] and "localpdf" in calls[0]["search_fn"]
    assert callable(calls[0]["fetch_fn"]) and callable(calls[0]["extract_fn"])


def test_run_project_without_topic_does_not_call_the_model(tmp_path: Path) -> None:
    """没给主题 ⇒ 只登记 + 冷启动，一次模型都不调（也就一分钱都不花）。"""
    called: list[int] = []

    def _never(store, **kw):
        called.append(1)
        return {}

    res = P.run_project(tmp_path / "projects", name="project1", start="cold",
                        topic="", run_topic_fn=_never)
    assert called == []
    assert res["result"] == {}
    assert any("没给 --topic" in n for n in res["run"]["notes"])


def test_registration_only_run_does_not_consume_a_run_number_or_make_an_out_dir(
        tmp_path: Path) -> None:
    """负控（`R-25`）：不给主题的那次调用不许占运行号、不许建空的 `out/run-N/`。

    改前它会占一个号并建出一个没有六件产物的空目录 —— 读到那个目录的人会问
    "它的产物呢"。数据本身没错（卡里 topic/result 都是空），但那是个可被误读的形态。
    """
    root = tmp_path / "projects"
    P.run_project(root, name="project1", start="cold", topic="",
                  run_topic_fn=lambda store, **kw: {})
    project = root / "project1"
    assert not (project / "out").exists(), "只登记的那次不许建 out 目录"
    card = json.loads((project / "project.json").read_text(encoding="utf-8"))
    assert card["runs"][-1]["run_index"] is None
    assert card["runs"][-1]["out_dir"] == "", "没跑模型时卡里写空串，不写字符串 'None'"

    # 正控：给了主题之后，运行号从 1 开始（上面那次没有把号占掉）。
    seen: dict = {}

    def _fake(store, **kw):
        seen.update(kw)
        Path(kw["out_dir"]).mkdir(parents=True, exist_ok=True)
        return {"exit_code": 0}

    res = P.run_project(root, name="project1", start="warm", topic="t",
                        run_topic_fn=_fake)
    assert res["run"]["run_index"] == 1, f"只登记那次不该占号：{res['run']}"
    assert Path(res["run"]["out_dir"]).name == "run-1"


def test_the_lean_switch_is_passed_through_to_run_topic(tmp_path: Path) -> None:
    """`--lean` 必须透传：不透传时这条主路径上永远拿不到 proof 级证据。

    实测（2026-09-28）：`project run --lean` 曾直接报 `unrecognized arguments`，
    于是每次项目运行的 `not_wired` 里都挂着 lean。
    """
    seen: dict = {}
    P.run_project(tmp_path / "projects", name="project1", start="cold", topic="t",
                  lean=True, run_topic_fn=lambda store, **kw: seen.update(kw) or {})
    assert seen.get("lean") is True
    seen.clear()
    P.run_project(tmp_path / "projects", name="project1", start="warm", topic="t",
                  run_topic_fn=lambda store, **kw: seen.update(kw) or {})
    assert seen.get("lean") is False, "缺省必须是关（与 run 那个动词同口径）"


def test_list_projects_reports_state(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    P.create_project(P.resolve(root, None, start="auto"))
    rows = P.list_projects(root)
    assert len(rows) == 1 and rows[0]["name"] == "project1"
    assert rows[0]["state"] == "workspace"


def test_run_project_passes_the_project_store_dir(tmp_path: Path) -> None:
    """项目路径必须把逐页正文的落点传下去：`<项目根>/.fulltext`（依据 `draft/30` §T0-6）。

    为什么钉在 `run_project` 这一层：裸 `run` 那个动词没有项目根，所以它刻意不
    默认开引用形态；而项目路径是主路径，默认就该让"同一本书的正文只存一份"成立。
    """
    seen: dict = {}
    P.run_project(tmp_path / "projects", name="project1", start="cold", topic="t",
                  run_topic_fn=lambda store, **kw: seen.update(kw) or {"exit_code": 0})
    assert seen.get("text_store_dir") == str(
        tmp_path / "projects" / "project1" / ".fulltext")
