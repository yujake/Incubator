"""渲染锚 + 编译回执（`renderanchor`）与只读核对路径（`doc.paper_state`）（`draft/28` §191）。

## 这一组守什么

`draft/28` §188.3 实测出来的装置缺陷：锚原先把编译产物（`main.pdf`）也收进同一张
哈希表，而锚是渲染那一刻写的 ⇒ 先写锚、后编译必然报漂移，"0 漂移"在物理上不可达。
用户批准的四条里第一条就是修它：

1. 锚只管渲染产出的源文件；PDF 由编译回执管（记录它由哪一个 tex 哈希编出）⇒
   `build()` 只需 渲染 → 编译 → 核对 三步，且"PDF 是从旧 tex 编的"可被精确判出；
2. 只读角色也要能核：判据是框架里的纯函数，`doc.paper_state` 是 `read` 工具，
   H（只读）拿得到；`doc.paper_anchor` 仍是 `exec`（它跑项目脚本）。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import paperbuild as PB
from agentflow import renderanchor as RA
from agentflow.store import Store
from agentflow.tools import build_registry

# ============================================================ 锚的格式不对 ⇒ 没查成（不是漂移）
def test_a_hand_made_anchor_is_unknown_not_drifted(tmp_path: pathlib.Path) -> None:
    """判据（2026-10-13，无 Lean T2 的真机）：锚的格式不对属于"没查成"，不是"漂了"。

    真机现场（`projects/p6t2-research-20261012b/out/paper/RENDER-ANCHOR.json`）：
    那份锚由项目自己补写的 `code/compile_paper.py` 产，两个毛病同时存在 ——

    ① 表哈希是 12 位（框架写 64 位；前 12 位逐字相同 ⇒ 规范化口径一致，只是被截断）；
    ② `files` 的键是项目相对（`out/paper/main.tex`），而框架按包相对读（`main.tex`），
       还把编译产物 `main.pdf` 也塞进了 `files`。

    旧判据的后果：verdict 是 `drifted`，而漂移行把两侧都截到 12 位 ⇒
    「表 documents：锚 3 行/695d20acca07 ≠ 现在 3 行/695d20acca07」，读的人只会以为判据坏了；
    文件那一维则报「锚里有、盘上没了」×2 +「盘上有、锚里没有」×1（三条都是基准不同）。
    把"这份锚读不了"折成"包确实漂了"，正是三态纪律要挡的那一档。
    """
    root = tmp_path / "proj"
    st = _sealed_project(root)
    out = root / "out" / "paper"

    # 把基准那份锚改成"手写风格"：表哈希截到 12 位、文件键改项目相对、再把 PDF 塞进去
    anchor = json.loads((out / RA.ANCHOR_NAME).read_text(encoding="utf-8"))
    anchor["tables"] = {k: {"rows": v["rows"], "sha256": str(v["sha256"])[:12]}
                        for k, v in anchor["tables"].items()}
    anchor["files"] = {"out/paper/main.tex": RA.file_digest(out / "main.tex"),
                       "out/paper/main.pdf": RA.file_digest(out / "main.pdf")}
    (out / RA.ANCHOR_NAME).write_text(json.dumps(anchor), encoding="utf-8")

    got = RA.check_package(root, store=st)
    assert got["verdict"] == "unknown", got
    assert got["dimensions"]["tables"] == "unknown", got["dimensions"]
    assert got["dimensions"]["files"] == "unknown", got["dimensions"]
    assert got["drift"] == [], f"格式不对不该产出漂移行：{got['drift']}"
    joined = "；".join(got["problems"])
    assert "12 位" in joined and "64 位" in joined, joined
    assert "项目相对" in joined and "包相对" in joined, joined

    # 反负控：把锚按框架口径重写一遍 ⇒ 必须回到一致（否则上面那条可能只是"永远 unknown"）
    (out / RA.ANCHOR_NAME).write_text(json.dumps(RA.build_anchor(st, out)), encoding="utf-8")
    again = RA.check_package(root, store=st)
    assert again["verdict"] == "consistent", (again["dimensions"], again["drift"])




def _sealed_project(root: pathlib.Path, *, tex: str = "\\date{2026-01-01}\nbody\n",
                    store: Store | None = None) -> Store:
    """造一个"锚与回执都齐"的论文包项目（走 `renderanchor` 的公开函数）。"""
    out = root / "out" / "paper"
    out.mkdir(parents=True, exist_ok=True)
    st = store or Store(root)
    st.init(force=True)
    (out / "main.tex").write_text(tex, encoding="utf-8")
    (out / "main.pdf").write_bytes(b"%PDF-1.4 fake")
    (out / RA.ANCHOR_NAME).write_text(json.dumps(RA.build_anchor(st, out)), encoding="utf-8")
    (out / RA.RECEIPT_NAME).write_text(json.dumps(RA.build_receipt(
        out, tex_sha256=RA.file_digest(out / "main.tex"), pages=21, markers_missing=[],
        pdf_bytes=13, compiler_exit_codes=[0])), encoding="utf-8")
    return st


def _fake_scripts(root: pathlib.Path) -> None:
    """假渲染/编译脚本：自己调 `renderanchor` 写锚与回执（与真项目脚本同一条路）。"""
    src = str(pathlib.Path(RA.__file__).resolve().parents[1])
    code = root / "code"
    code.mkdir(parents=True, exist_ok=True)
    (code / "make_paper.py").write_text(
        "import json, pathlib, sys\n"
        f"sys.path.insert(0, {src!r})\n"
        "from agentflow import renderanchor as RA\n"
        "from agentflow.store import Store\n"
        "root = pathlib.Path('.')\n"
        "out = root / 'out' / 'paper'\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "if '--check' in sys.argv:\n"
        "    got = RA.check_package(root)\n"
        "    sys.exit({'consistent': 0, 'drifted': 1}.get(got['verdict'], 2))\n"
        "(out / 'main.tex').write_text(chr(10).join(['\\\\date{2026-01-01}', 'body'])"
        " + chr(10), encoding='utf-8')\n"
        "st = Store(root); st.init(force=True)\n"
        "(out / RA.ANCHOR_NAME).write_text(json.dumps(RA.build_anchor(st, out)),"
        " encoding='utf-8')\n"
        "print('REPRO_RESULT: ' + json.dumps({'claims': 24}))\n",
        encoding="utf-8")
    (code / "compile_paper.py").write_text(
        "import json, pathlib, sys\n"
        f"sys.path.insert(0, {src!r})\n"
        "from agentflow import renderanchor as RA\n"
        "out = pathlib.Path('out/paper')\n"
        "(out / 'main.pdf').write_bytes(b'%PDF-1.4 fake')\n"
        "rec = RA.build_receipt(out, tex_sha256=RA.file_digest(out / 'main.tex'), pages=21,"
        " markers_missing=[], pdf_bytes=13, compiler_exit_codes=[0])\n"
        "(out / RA.RECEIPT_NAME).write_text(json.dumps(rec), encoding='utf-8')\n"
        "print('REPRO_RESULT: ' + json.dumps({'ok': True, 'pages': 21,"
        " 'markers_missing': [], 'pdf': 'main.pdf', 'pdf_bytes': 13, 'pdf_header': '%PDF-',"
        " 'text_extractor': 'stub', 'runs': [], 'compiler_exit_codes': [0],"
        " 'log_tail': 'stub', 'note': '夹具'}))\n",
        encoding="utf-8")


# ============================================================ 三维核对


def test_a_sealed_package_is_consistent(tmp_path: pathlib.Path):
    """正控：锚 + 回执 + 库都没动 ⇒ consistent（三维各自都是）。"""
    root = tmp_path / "proj"
    _sealed_project(root)
    got = RA.check_package(root)
    assert got["verdict"] == "consistent", (got["drift"], got["problems"])
    assert set(got["dimensions"].values()) == {"consistent"}, got["dimensions"]
    assert got["anchor_present"] and got["receipt_present"], got


def test_a_missing_anchor_is_not_checked(tmp_path: pathlib.Path):
    """负控（三态）：锚不在 ⇒ unknown（绝不写成一致）。"""
    root = tmp_path / "proj"
    (root / "out" / "paper").mkdir(parents=True)
    got = RA.check_package(root)
    assert got["verdict"] == "unknown" and got["problems"], got


def test_the_store_changing_makes_it_drifted(tmp_path: pathlib.Path):
    """负控（要抓的形态）：库长了行 ⇒ 表那一维 drifted（包不再是库里现在的样子）。"""
    root = tmp_path / "proj"
    st = _sealed_project(root)
    with st.tx("conjectures", actor="test") as tx:
        tx.upsert("conjectures", {"conjecture_id": "0001", "statement": "x", "form": "universal",
                                  "status": "proposed", "origin": "test", "testable": True,
                                  "negation_statement": "非 x", "experiment_ids": [],
                                  "created_at": "2026-01-01T00:00:00", "created_by": "test"})
    got = RA.check_package(root)
    assert got["dimensions"]["tables"] == "drifted" and got["verdict"] == "drifted", got


def test_a_hand_edited_source_file_makes_it_drifted(tmp_path: pathlib.Path):
    """负控：渲染之后有人改了源文件 ⇒ 文件那一维 drifted。"""
    root = tmp_path / "proj"
    _sealed_project(root)
    (root / "out" / "paper" / "main.tex").write_text("\\date{2026-01-02}\nbody\n",
                                                     encoding="utf-8")
    got = RA.check_package(root)
    assert got["dimensions"]["files"] == "drifted", got


def test_a_pdf_built_from_a_stale_tex_is_reported(tmp_path: pathlib.Path):
    """正控（这一条是本次要买的能力）：编译之后改了 tex ⇒ 回执那一维报「旧 tex」。

    旧锚做不到这件事：它只知道"PDF 的字节与渲染时不同"，而那个信号在每次重编时
    都会亮（PDF 内嵌时间戳），于是真漂移与假漂移分不开。
    """
    root = tmp_path / "proj"
    _sealed_project(root)
    (root / "out" / "paper" / "main.tex").write_text("\\date{2026-01-01}\nbody changed\n",
                                                     encoding="utf-8")
    got = RA.check_package(root)
    assert got["dimensions"]["receipt"] == "drifted", got
    assert any("旧 tex" in d for d in got["drift"]), got["drift"]


def test_a_pdf_swapped_after_compile_is_reported(tmp_path: pathlib.Path):
    """负控：tex 没变、但 PDF 被换过 ⇒ 也用回执判出来（pdf_sha256 对不上）。"""
    root = tmp_path / "proj"
    _sealed_project(root)
    (root / "out" / "paper" / "main.pdf").write_bytes(b"%PDF-1.4 other")
    got = RA.check_package(root)
    assert got["dimensions"]["receipt"] == "drifted", got
    assert any("与编译回执不符" in d for d in got["drift"]), got["drift"]


def test_the_anchor_does_not_cover_the_compile_products(tmp_path: pathlib.Path):
    """判据（本次修的核心）：锚里不许有 PDF 与编译中间产物 —— 否则"重编一次必报漂移"。"""
    root = tmp_path / "proj"
    out = root / "out" / "paper"
    _sealed_project(root)
    for junk in ("main.aux", "main.log", "main.out", "compile.log"):
        (out / junk).write_text("x", encoding="utf-8")
    anchor = json.loads((out / RA.ANCHOR_NAME).read_text(encoding="utf-8"))
    bad = [k for k in anchor["files"]
           if k in RA.COMPILE_PRODUCTS or any(k.endswith(s) for s in RA.COMPILE_SUFFIXES)]
    assert bad == [], bad


def test_the_module_selftest_passes():
    """判据：模块自检必须过（它是 `python -m agentflow.renderanchor` 的内容）。"""
    assert RA.selftest() == 0


# ============================================================ 构建历史（§193）


def test_history_records_renders_and_compiles(tmp_path: pathlib.Path):
    """正控（§193）：渲染与编译各追加一行，`history()` 分开数得清。"""
    root = tmp_path / "proj"
    out = root / "out" / "paper"
    _sealed_project(root)
    assert RA.append_history(out, {"event": "render", "files": 15}) == ""
    assert RA.append_history(out, {"event": "compile", "pages": 21}) == ""
    got = RA.history(out)
    assert got["total"] == 2 and got["renders"] == 1 and got["compiles"] == 1, got
    assert got["problems"] == [], got
    assert [e["event"] for e in got["events"]] == ["render", "compile"], got["events"]
    assert got["last_render_at"] and got["last_compile_at"], got


def test_history_does_not_enter_the_anchor(tmp_path: pathlib.Path):
    """判据（本次要防的坑）：历史自己每写一行就变 ⇒ 它绝不能进锚。

    否则每次构建都会报"文件 BUILD-HISTORY.jsonl 与渲染时不同" —— 与 PDF 当年那个坑同形。
    """
    root = tmp_path / "proj"
    out = root / "out" / "paper"
    _sealed_project(root)
    assert RA.append_history(out, {"event": "render"}) == ""
    got = RA.check_package(root)
    assert got["verdict"] == "consistent", (got["drift"], got["problems"])
    anchor = json.loads((out / RA.ANCHOR_NAME).read_text(encoding="utf-8"))
    assert RA.HISTORY_NAME not in anchor["files"], anchor["files"]


def test_a_bad_history_line_is_reported_not_skipped(tmp_path: pathlib.Path):
    """负控（三态）：坏行必须出现在 `problems` 里 —— 历史是审计材料，读不出来要看得见。"""
    root = tmp_path / "proj"
    out = root / "out" / "paper"
    _sealed_project(root)
    assert RA.append_history(out, {"event": "render"}) == ""
    with (out / RA.HISTORY_NAME).open("a", encoding="utf-8") as fh:
        fh.write("这不是 JSON\n")
    got = RA.history(out)
    assert got["total"] == 1 and any("不是合法 JSON" in p for p in got["problems"]), got


def test_a_missing_history_is_not_an_error(tmp_path: pathlib.Path):
    """边界：没有历史文件 ⇒ `present=False` + 一条 problems（"没有历史"要看得见）。"""
    got = RA.history(tmp_path / "nope")
    assert got["present"] is False and got["total"] == 0 and got["problems"], got


def test_the_check_reading_includes_the_history_summary(tmp_path: pathlib.Path):
    """判据（读数进核对）：`check_package` 带上历史摘要，但判定不看它。"""
    root = tmp_path / "proj"
    out = root / "out" / "paper"
    _sealed_project(root)
    assert RA.append_history(out, {"event": "render"}) == ""
    assert RA.append_history(out, {"event": "compile", "pages": 21}) == ""
    got = RA.check_package(root)
    assert got["history"]["total"] == 2 and got["history"]["compiles"] == 1, got["history"]
    assert got["verdict"] == "consistent", got["drift"]


def test_the_checker_does_not_write_anything(tmp_path: pathlib.Path):
    """判据（只读纪律）：核对一行都不写 —— 它要能被只读角色反复跑。"""
    root = tmp_path / "proj"
    _sealed_project(root)
    out = root / "out" / "paper"
    before = RA.history(out)["total"]
    RA.check_package(root)
    PB.state(root)
    assert RA.history(out)["total"] == before, "核对动作写了盘（历史被追加了）"


def test_a_missing_anchor_names_the_path_it_looked_at(tmp_path: pathlib.Path):
    """判据（§195 真机逼出来的）："找不到"必须写出它去哪儿找过。

    实测：H 把包目录 `out/paper` 当成 `project` 传进来（工具要的是项目根），
    旧消息只说"读不到 RENDER-ANCHOR.json" —— H 读不出到底找了哪，只能自己推断
    "是路径拼接缺陷"，并把这条推断写进了交付说明。路径写出来，一眼可见双重拼接。
    """
    root = tmp_path / "proj"
    (root / "out" / "paper").mkdir(parents=True)
    got = RA.check_package(root)
    assert got["verdict"] == "unknown", got
    joined = " ".join(got["problems"])
    assert str(root / "out" / "paper" / RA.ANCHOR_NAME) in joined, joined
    assert "这里找过" in joined, joined


# ============================================================ 三步序列（真机契约）


def test_build_runs_three_steps_and_ends_at_zero_drift(tmp_path: pathlib.Path):
    """正控（§191 的核心）：渲染 → 编译 → 核对 三步，不再需要"再渲染一次"。"""
    root = tmp_path / "proj"
    _fake_scripts(root)
    got = PB.build(root, render_script="code/make_paper.py",
                   compile_script="code/compile_paper.py", timeout_sec=60)
    assert [s["step"] for s in got["steps"]] == ["render", "compile", "anchor_check"], got["steps"]
    assert got["ok"] is True, (got["problem"], got["anchor"])
    assert got["anchor"]["verdict"] == "consistent"
    assert got["receipt"].get("tex_sha256"), got["receipt"]
    for step in got["steps"]:
        assert isinstance(step.get("ok"), bool), step
        assert {"step", "ok"} <= set(step), sorted(step)


def test_build_reports_the_stale_tex_after_a_hand_edit(tmp_path: pathlib.Path):
    """负控（真机口径）：build 之后手改 tex ⇒ `state()` 报 receipt drifted。"""
    root = tmp_path / "proj"
    _fake_scripts(root)
    assert PB.build(root, timeout_sec=60)["ok"] is True
    (root / "out" / "paper" / "main.tex").write_text("\\date{2026-01-01}\nchanged\n",
                                                     encoding="utf-8")
    got = PB.state(root)
    assert got["verdict"] == "drifted" and got["dimensions"]["receipt"] == "drifted", got


def test_build_stops_at_the_step_that_failed(tmp_path: pathlib.Path):
    """负控（不许假装走完）：编译脚本失败 ⇒ 只跑到 compile。"""
    root = tmp_path / "proj"
    _fake_scripts(root)
    (root / "code" / "compile_paper.py").write_text(
        "import sys\nprint('编译炸了')\nsys.exit(1)\n", encoding="utf-8")
    got = PB.build(root, timeout_sec=60)
    assert got["ok"] is False
    assert [s["step"] for s in got["steps"]] == ["render", "compile"], got["steps"]
    assert "compile" in got["problem"], got["problem"]


# ============================================================ 工具面（只读角色拿得到）


def _registry(tmp_path: pathlib.Path):
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    built = build_registry(store=st, workspace_root=ws, roles=("G", "H"), strict=True)
    built.registry.bound_role = "H"          # H 是只读角色：这一组要证它能核
    return built.registry, ws


def test_h_can_check_the_package_without_exec(tmp_path: pathlib.Path):
    """正控（本次要买的能力）：H 拿到 `doc.paper_state`（read），核得动一份包。"""
    registry, ws = _registry(tmp_path)
    _sealed_project(ws / "projects" / "p2")
    res = registry.call("doc.paper_state", project="projects/p2")
    assert res.ok, (res.error, res.meta)
    data = res.unwrap()
    assert data["verdict"] == "consistent" and set(data["dimensions"]) == {"tables", "files",
                                                                          "receipt"}, data


def test_h_cannot_get_the_exec_tools(tmp_path: pathlib.Path):
    """负控（权限面不许放宽）：另外四件是 `exec`，H 一件也拿不到。"""
    registry, _ws = _registry(tmp_path)
    names = {s.name for s in registry.for_role("H") if s.name.startswith("doc.paper")}
    assert names == {"doc.paper_state"}, names
    for name in ("doc.paper_render", "doc.paper_compile", "doc.paper_build", "doc.paper_anchor"):
        assert registry.get(name).external == "exec", name


def test_the_state_tool_separates_drift_from_unknown(tmp_path: pathlib.Path):
    """负控（三态进工具层）：漂移与"没查成"在同一件工具上是两个结论。"""
    registry, ws = _registry(tmp_path)
    drifted = ws / "projects" / "p3"
    st = _sealed_project(drifted)
    with st.tx("conjectures", actor="test") as tx:
        tx.upsert("conjectures", {"conjecture_id": "0001", "statement": "x", "form": "universal",
                                  "status": "proposed", "origin": "t", "testable": True,
                                  "negation_statement": "非 x", "experiment_ids": [],
                                  "created_at": "2026-01-01T00:00:00", "created_by": "t"})
    got = registry.call("doc.paper_state", project="projects/p3").unwrap()
    assert got["verdict"] == "drifted", got
    empty = ws / "projects" / "p4"
    (empty / "out" / "paper").mkdir(parents=True)
    unknown = registry.call("doc.paper_state", project="projects/p4").unwrap()
    assert unknown["verdict"] == "unknown" and unknown["problems"], unknown


def test_the_state_reading_is_json_serializable(tmp_path: pathlib.Path):
    """判据（可审计）：读数必须能原样落盘。"""
    registry, ws = _registry(tmp_path)
    _sealed_project(ws / "projects" / "p2")
    data: dict[str, Any] = registry.call("doc.paper_state", project="projects/p2").unwrap()
    assert "receipt" in json.dumps(data, ensure_ascii=False) or "tables" in json.dumps(
        data, ensure_ascii=False)


@pytest.mark.parametrize("bad", ["../outside", "/abs/path", "没有这个目录"])
def test_a_project_outside_the_workspace_is_refused(tmp_path: pathlib.Path, bad: str):
    """负控（越界）：`project` 跳出工作区 ⇒ `bad_project`，不起子进程、不读盘。"""
    registry, _ws = _registry(tmp_path)
    res = registry.call("doc.paper_state", project=bad)
    assert not res.ok and res.meta.get("kind") == "bad_project", (bad, res.meta)


# ============================================================ E-08：锚与验收表解耦

def test_editing_the_acceptance_table_does_not_drift_the_anchor(tmp_path: pathlib.Path):
    """E-08（`draft/52` D5 族）：交付时改一次验收表不许把锚打红。

    真机读数（`draft/46-04` §2.4）：32 份锚里 10 份的 `files` 含
    `ACCEPTANCE-CHECKS.json`；在 `p5-review-t17` 上把验收表 sha 改掉后
    `verdict=drifted`、`dims.files=drifted` —— 而"交付前补一行 `na` + 理由"
    是合法的流程动作（不是包坏了）。

    改前的负控是这条：改验收表 ⇒ drifted。现在两侧对称过滤流程产物（写入侧
    `package_files` + 校验侧 `files_was`），两件事都要成立：

    - 新渲染的锚里不含流程产物（写入侧过滤）；
    - 老锚（`files` 里还记着它）改验收表之后仍 `consistent`（校验侧过滤）——
      这一条是"10 份老锚不许集体漂移"的机器证据。
    """
    ws = tmp_path / "ew"
    _sealed_project(ws)
    out = ws / "out" / "paper"
    checks = out / "ACCEPTANCE-CHECKS.json"
    checks.write_text(json.dumps({"checks": []}), encoding="utf-8")

    # ① 重渲染：流程产物不进锚
    anchor = RA.build_anchor(Store(ws), out)
    assert not any(pathlib.Path(k).name in RA.PROCESS_PRODUCTS for k in anchor["files"]), \
        sorted(anchor["files"])

    # ② 老锚（手工把它记进 files 里，模拟"改前渲染的那 10 份"）
    anchor["files"]["ACCEPTANCE-CHECKS.json"] = RA.file_digest(checks)
    (out / RA.ANCHOR_NAME).write_text(json.dumps(anchor), encoding="utf-8")
    res = RA.check_package(ws)
    assert res["verdict"] == "consistent", res["drift"]
    assert res["excluded_process_products"] == ["ACCEPTANCE-CHECKS.json"], res

    # ③ 交付时改一次验收表 ⇒ 仍然 consistent（这就是 E-08 要的那条）
    checks.write_text(json.dumps({"checks": [{"id": "P1", "kind": "document_rows",
                                              "na": True, "note": "交付前补的一行"}]}),
                      encoding="utf-8")
    res2 = RA.check_package(ws)
    assert res2["verdict"] == "consistent", res2["drift"]

    # 反真空：别的源文件被手改照旧 drifted（过滤只针对流程产物这一族）
    (out / "main.tex").write_text("\\date{2026-01-01}\n手改了\n", encoding="utf-8")
    res3 = RA.check_package(ws)
    assert res3["verdict"] in ("drifted", "unknown"), res3
    assert any("main.tex" in d for d in res3["drift"]) or res3["problems"], res3
