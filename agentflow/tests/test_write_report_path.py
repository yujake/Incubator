# -*- coding: utf-8 -*-
"""判据（`draft/37` §118）：D 的报告落在「工作区里」，读数也去「同一个落位」数。

真机读数（T2 第 1 趟）：主控 `summon("D", "write_report", {"out_path": "out\\review\\D-analysis.md"})`
八次全部记 `outcome=ok`、报告里写着"执行完成" —— 而工作区里「一个报告文件都没有」：
`Path(out_path)` 按「进程当前目录」解析，2282 字节的报告写到了
`D:\\Incubator\\agentflow\\out\\review\\D-analysis.md`（进程 cwd），整个交付物静默离开工作区。

两条判据：① 相对 `out_path` 按工作区根解析、越界拒绝；② 验收那一档
（`report_files`）按写者用的落位数（`agent_d.reports_subdir`）。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import closing as CL
from agentflow.agent_d import AgentD
from agentflow.store import Store


def _ws(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Store]:
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    st = Store(ws)
    st.init()
    return ws, st


def test_the_out_path_rule_itself_is_pinned(tmp_path, monkeypatch):
    """直接判那条规则本体（`doc_tools.resolve_out_path`）：四条口径各一条断言。

    为什么直接判它（`tools/coverage_zero_test.py` 的等级 2 判据）：它是「相对路径按谁
    解析、越界怎么办」的「唯一实现」——工具层与 `D.write_report` 都走它，而一条规则
    没被直接测过，就等于「它哪天被改宽了也没有一处会响」。

    四条：① 相对 → 拼在工作区根下；② 绝对且在工作区内 → 原样（相对化）；
    ③ 缺省落位也按工作区根拼（不是按进程 cwd）；④ 越界 → 拒（含「越界」字样）。
    """
    from agentflow.tools.doc_tools import resolve_out_path

    root = tmp_path / "ws"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)          # 进程 cwd 故意不是工作区

    rel, absolute = resolve_out_path(root, "out/reports/x.md", "0000", "reports")
    assert rel == "out/reports/x.md", (rel, absolute)
    assert absolute == (root / "out" / "reports" / "x.md").resolve(), absolute

    rel2, absolute2 = resolve_out_path(root, str(root / "a.md"), "0000", "reports")
    assert rel2 == "a.md" and absolute2 == (root / "a.md").resolve(), (rel2, absolute2)

    rel3, absolute3 = resolve_out_path(root, None, "0007", "reports")
    assert rel3 == "reports/0007.md", (rel3, absolute3)
    assert absolute3 == (root / "reports" / "0007.md").resolve(), absolute3

    with pytest.raises(ValueError) as exc:
        resolve_out_path(root, str(elsewhere / "x.md"), "0000", "reports")
    assert "越界" in str(exc.value), exc.value


def test_a_relative_out_path_lands_under_the_workspace_not_the_cwd(tmp_path, monkeypatch):
    """正控 + 那次泄漏的负控：换个 cwd 跑，文件仍然必须落在工作区里。"""
    ws, st = _ws(tmp_path)
    elsewere = tmp_path / "somewhere-else"
    elsewere.mkdir()
    monkeypatch.chdir(elsewere)          # 进程 cwd 故意不是工作区

    d = AgentD(st)
    out = d.write_report("out/review/D-analysis.md")
    written = pathlib.Path(out)
    assert written.is_file(), out
    assert written.resolve().is_relative_to(ws.resolve()), \
        f"报告写到工作区外面去了：{written}（T2 第 1 趟就是这么丢的）"
    assert written.resolve() == (ws / "out" / "review" / "D-analysis.md").resolve()
    assert not (elsewere / "out").exists(), "不许在进程 cwd 那边留下任何东西"


def test_the_default_landing_spot_is_the_configured_reports_subdir(tmp_path):
    """缺省落位：`<工作区>/<agent_d.reports_subdir>`（缺省 `reports`）。"""
    ws, st = _ws(tmp_path)
    d = AgentD(st)
    out = pathlib.Path(d.write_report())
    assert out.resolve() == (ws / "reports" / "0000-research.md").resolve(), out
    assert out.name == "0000-research.md", out.name


def test_an_out_path_outside_the_workspace_is_refused(tmp_path):
    """负控：跳到工作区外的绝对路径一律拒（边界是契约，不是建议）。"""
    ws, st = _ws(tmp_path)
    outside = tmp_path / "outside.md"
    d = AgentD(st)
    with pytest.raises(ValueError) as exc:
        d.write_report(str(outside))
    assert "越界" in str(exc.value), exc.value
    assert not outside.exists(), "被拒的那一次不许留下文件"


def test_the_report_files_leg_counts_where_the_writer_actually_writes(tmp_path):
    """验收读数与写者同口径：`reports/`（写者缺省落位）与 `out/reports/` 都算。"""
    ws, st = _ws(tmp_path)
    rows = [{"id": "R4", "kind": "report_files", "min": 1}]
    (ws / "out" / "paper").mkdir(parents=True, exist_ok=True)
    (ws / "out" / "paper" / "ACCEPTANCE-CHECKS.json").write_text(
        __import__("json").dumps({"checks": rows}, ensure_ascii=False), encoding="utf-8")

    d = AgentD(st)
    d.write_report()                                   # 写者缺省落位：reports/
    got, detail = CL._leg_reading(st, "report_files", ws)
    assert got == 1, detail
    assert detail["dirs"].get("reports") == 1, detail
    assert detail["files"] == ["reports/0000-research.md"], detail

    (ws / "out" / "reports").mkdir(parents=True)
    (ws / "out" / "reports" / "extra.md").write_text("另一份\n", encoding="utf-8")
    got2, detail2 = CL._leg_reading(st, "report_files", ws)
    assert got2 == 2, detail2

    rep = CL.check_closing(st, project_dir=str(ws))
    r4 = next(r for r in rep.readings["acceptance"]["rows"] if r["id"] == "R4")
    assert r4["got"] == 2 and r4["ok"] is True, r4
