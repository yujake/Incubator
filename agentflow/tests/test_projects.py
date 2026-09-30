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


def test_extract_step_opens_a_real_task_row_and_leaves_verify_clean(
        tmp_path: Path, monkeypatch) -> None:
    """`--extract` 的花销必须挂在一条真台账号上，且跑完 `verify` 无错无警。

    为什么单钉这一条：抽取的花销按 `task_id` 记进 `usage_ledger`，而花销必须挂得上
    一条 `tasks` 行。曾经这里用的是 `f"{project_name}-extract"`（例如 `project1-extract`）
    —— 既不是台账号格式（`t-NNNN`），台账里也没有对应的行 ⇒ 用户跑完
    `project run --extract` 再自查，会看到两条 `dangling_usage_task`（error）加一条
    `usage_task_total_mismatch`（warning）：刚跑成功的那一跑，自查说数据不一致。

    两处负控：
    - `task_id` 必须是 `t-NNNN` 形态（`alloc_id("task")` 那条歧路实测直接报
      "未知 ID 类别"并以退出码 2 结束）；
    - `input_key` 必须非空（留空会被报 `task_without_input_key` —— 这条是修第一处时
      新撞出来的，第一次修只补了行、没补键）。
    """
    from agentflow import verify as V
    from agentflow.store import Store
    from agentflow.tokenmeter import Charge, TokenMeter

    fitz = pytest.importorskip("fitz", reason="没有 fitz 就造不出带文本层的 PDF")
    books = tmp_path / "books"
    books.mkdir()
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "A group is a set with an operation.")
    doc.save(str(books / "甲书.pdf"))
    doc.close()

    seen: dict = {}

    def _fake_extract(store, **kw):
        tid = str(kw["task_id"])
        seen["task_id"] = tid
        # 真实路径上这一笔由 modelgw 记；这里用同一条公开口记，形状一致。
        TokenMeter(store).charge(Charge(
            role="B", scope="extract", task_id=tid,
            tokens_in=1200, tokens_out=300, usd=0.0042, note="模型读书（测试替身）"))
        return {"processed": 1, "concepts_created": 2, "relations_added": 1,
                "quotes_verified": 1, "rounds_failed": 0}

    monkeypatch.setattr(P, "extract_with_model", _fake_extract)
    root = tmp_path / "projects"
    res = P.run_project(root, name="project1", start="cold", topic="t",
                        books_dir=books, extract=True, extract_rounds=1,
                        run_topic_fn=lambda store, **kw: {"exit_code": 0})

    tid = seen.get("task_id", "")
    assert tid.startswith("t-") and tid[2:].isdigit(), f"必须是真台账号 t-NNNN：{tid!r}"

    store = Store(root / "project1")
    rows = {str(r.get("task_id")): r for r in store.rows("tasks")}
    row = rows[tid]
    assert row["status"] == "done" and row["outcome"] == "ok"
    assert str(row["input_key"]).strip(), "input_key 留空 ⇒ 会被报 task_without_input_key"
    assert str(row["input_key"]) == str(books), "键该是本次读的那一架子书"
    # 花销与台账一致（`tasks.tokens/usd` 是从账本抄回来的，不是各算一遍）
    meter = TokenMeter(store)
    assert int(row["tokens"]) == meter.tokens_for(tid) == 1500
    assert float(row["usd"]) == meter.usd_for(tid) == 0.0042

    rep = V.verify_all(store).to_dict()
    bad = [i for i in rep.get("errors", []) + rep.get("warnings", [])
           if i.get("code") in ("dangling_usage_task", "usage_task_total_mismatch",
                                "task_without_input_key")]
    assert bad == [], f"跑成功的那一跑自查必须干净，却报：{bad}"
    assert rep["errors"] == [], f"不许有 error：{rep['errors']}"
    assert rep["ok"] is True
    assert res["run"]["extraction"]["task_id"] == tid


def test_a_usage_row_with_a_bogus_task_id_is_still_reported(store) -> None:
    """负控：上一条"自查干净"的断言不是空的。

    把花销挂在一个不存在的 `task_id`（正是修复前那种 `project1-extract` 形态）上，
    `verify_all` 必须报 `dangling_usage_task`。没有这一条，上面那半张判据就只是
    "我断言了三个码不在" —— 而它们不在的原因可能是判据根本没跑。
    """
    from agentflow import verify as V
    from agentflow.tokenmeter import Charge, TokenMeter

    TokenMeter(store).charge(Charge(
        role="B", scope="extract", task_id="project1-extract",
        tokens_in=10, tokens_out=5, usd=0.0001, note="旧形态：不是台账号"))
    codes = [i["code"] for i in V.verify_all(store).to_dict()["errors"]]
    assert "dangling_usage_task" in codes, f"这一笔应当被判为悬空花销，却报：{codes}"


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
