"""`draft/37` §60 的判据：相对工作区的路径必须按工作区根解析（不是按进程 cwd）。

第十趟真机（§60）主控按工具描述传 `project_dir="."` 与
`report_path="out/review/REPORT.md"`（描述逐字写的就是"相对工作区"），
却收到一串怪读数：`closing` 报"报告不在盘上"（它刚写完、`fs.stat` 也确认 6,743 字节）、
"锚文件读不到"（文件也在盘上）、`conductor.acceptance(project_dir=".")`
还解析到了工作区上一级。它花了 8 步查这件事。

病因：实现里 `Path(given)` 是按进程当前目录解析的，而契约是"相对工作区"。
"""
from __future__ import annotations

import json
from pathlib import Path

from agentflow import closing as CL
from agentflow import renderanchor as RA
from agentflow import reviewaccept as RA2
from agentflow.store import Store

REPORT = """\
# 交付说明

## 一、任务与范围
读数：1 项。
## 二、逐条读数
读数：P1 成立。
## 三、定理与引理清单
读数：statements 3 行。
## 四、形式化覆盖
读数：formal 实验 0 条。
## 五、引文核验
读数：lit:0000。
## 六、体例与表述
读数：改 2 处。
## 七、我们做的补救
读数：fs.edit 2 次；原文的与 我们补的 已分栏；origin=own_result；依据：如上；sha：abc。
## 八、未决问题
读数：1 条。
## 九、诚实边界
读数：本轮形式化覆盖 0 条，未核到 1 条。
"""


def _ws(tmp_path: Path) -> Path:
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "out" / "paper").mkdir(parents=True)
    (tmp_path / "out" / "review").mkdir(parents=True)
    (tmp_path / "out" / "paper" / "main.tex").write_text("% 主稿\n", encoding="utf-8")
    (tmp_path / "out" / "paper" / "main.pdf").write_bytes(b"%PDF-1.4 x\n")
    (tmp_path / "out" / "review" / "REPORT.md").write_text(REPORT, encoding="utf-8")
    st = Store(tmp_path)
    st.init()
    out = tmp_path / "out" / "paper"
    # 回执必须在锚之前写好（锚的三维之一就是回执；顺序反了锚会报 receipt: unknown）
    rec = RA.build_receipt(out, tex_sha256=RA.file_digest(out / "main.tex"), pages=1,
                           markers_missing=[], pdf_bytes=(out / "main.pdf").stat().st_size,
                           compiler_exit_codes=[])
    (out / RA.RECEIPT_NAME).write_text(json.dumps(rec), encoding="utf-8")
    (out / RA.ANCHOR_NAME).write_text(json.dumps(RA.build_anchor(st, out)), encoding="utf-8")
    return tmp_path


def test_a_relative_report_path_resolves_under_the_workspace(tmp_path: Path, monkeypatch):
    """正控：`report_path="out/review/REPORT.md"`（相对）必须在工作区里找到那份报告。

    夹具把进程 cwd 换到别处（`tmp_path` 的兄弟目录）—— 若实现还按 cwd 解析，
    这条会红。这正是第十趟主控撞上的形态。
    """
    ws = _ws(tmp_path / "ws")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    st = Store(ws)
    st.init()
    rep = CL.check_closing(st, project_dir=".", report_path="out/review/REPORT.md")
    assert rep.status["report_shape"] == "pass", rep.to_dict()
    r = rep.readings["report_shape"]
    assert r["missing_sections"] == [] and r["missing_split_markers"] == [], r
    assert r["chars"] > 100, r


def test_a_relative_project_dir_resolves_under_the_workspace(tmp_path: Path, monkeypatch):
    """正控：`project_dir="."` 必须在工作区根上找锚（第十趟报的"锚文件读不到"）。"""
    ws = _ws(tmp_path / "ws")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    st = Store(ws)
    st.init()
    rep = CL.check_closing(st, project_dir=".", report_path="out/review/REPORT.md")
    assert rep.status["anchor"] == "pass", rep.to_dict()
    assert rep.readings["anchor"]["verdict"] == "consistent", rep.readings["anchor"]


def test_reviewaccept_resolves_the_same_way(tmp_path: Path, monkeypatch):
    """正控（同一口径）：`reviewaccept` 的报告那一格也按工作区根解析。

    §69 的真机读数补上了这一条的最后一格：原先它只断言"报告节数"与"tex sha"，
    而「附件诚实」那一格（`_c_attachment`）自己另用了一份 `Path(report_path)` ——
    于是模型给的相对路径在那里判成"报告不在盘上 ⇒ 没查成"，
    判据没看的那一格正是漏掉的那一格。现在三处共用同一个解析口，都要断言。
    """
    ws = _ws(tmp_path / "ws")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    st = Store(ws)
    st.init()
    acc = RA2.check_review(st, project_dir=".", report_path="out/review/REPORT.md")
    assert acc.criteria["report_sections_have_readings"] == "pass", acc.details
    assert acc.auxiliary["tex_sha256"], acc.auxiliary
    assert acc.criteria["attachment_is_honest"] != "unknown", acc.details
    assert acc.readings["attachment"]["forgery_markers"] == [], acc.readings["attachment"]


def test_a_missing_report_is_still_unknown_not_pass(tmp_path: Path, monkeypatch):
    """负控：真的读不到报告时，那一格必须是 `unknown`（解析路径不许把它变成 pass）。"""
    ws = _ws(tmp_path / "ws")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    st = Store(ws)
    st.init()
    acc = RA2.check_review(st, project_dir=".", report_path="out/review/NOPE.md")
    assert acc.criteria["attachment_is_honest"] == "unknown", acc.details
    assert "不在盘上" in acc.details["attachment_is_honest"], acc.details


def test_an_absolute_path_is_left_alone(tmp_path: Path):
    """负控（不许把绝对路径也拼到工作区上）：给绝对路径时照旧能用。"""
    ws = _ws(tmp_path / "ws")
    st = Store(ws)
    st.init()
    rep = CL.check_closing(st, project_dir=str(ws), report_path=str(ws / "out" / "review" / "REPORT.md"))
    assert rep.status["anchor"] == "pass" and rep.status["report_shape"] == "pass", rep.to_dict()
