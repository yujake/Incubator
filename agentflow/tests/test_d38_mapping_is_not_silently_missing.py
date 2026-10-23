# -*- coding: utf-8 -*-
"""D-38（2026-10-24 两趟真机同时抓到）：论文对应表 MAPPING 从未落。

## 现场（`D:\\Incubator\\cube-ws` 与 `D:\\Incubator\\r34c`，只读）

```
cube：doc.build_document=3, doc.write_mapping=0, doc.paper_compile=0
r34c：doc.build_document=2, doc.write_mapping=0, doc.paper_compile=0
⇒ out/paper 只有 ACCEPTANCE-CHECKS.json / ACCEPTANCE.md，没有 MAPPING.json
```

`doc.build_document` 成功过（documents 表有行）、statements 非空，而对应表一次都没写。
那一趟的对应表格是 unknown（"没有 main.tex ⇒ 不适用"），于是"论文欠一张对应表"
在收工门上完全没有读数 —— 这是静默缺席：提示词要求了、工具调得到、没有报错也没有
blocker。

## 判据（五条主判据，各自的反真空写在同一条里）

| # | 判据 | 改前红在哪 |
|---|---|---|
| ① | 有 statements（>=1）且已成稿（documents 有行）而没有 out/paper/MAPPING.json ⇒ 收工门记一条 blocker（理由码 mapping_not_written），读数为 not pass | 那一格只是 unknown（"没有正文 ⇒ 不适用"），一条 finding 都没有 |
| ② | 有 MAPPING.json 且那三格齐（file / numeric_evidence / exhaustion_note）⇒ 放行（不误报） | readings["mapping"]["mapping_written"] 这一格不存在（不存在就没法说"放行"） |
| ③ | M 的验收表把缺失的 MAPPING 记成「未完成」，且收工门之外的读表工具能读出这一句 | 验收表解析器把「未完成」读成"读不懂"（ok=None），M 的提示词里也没有这一条 |
| ④ | 反真空：只有 statements、还没成稿 ⇒ ① 不许报（不许误伤早期阶段） | 同一条的另一半：补上稿件之后必须立刻报（改前不报，所以这一条红） |
| ⑤ | 反真空：把 MAPPING 存在性检查打桩成恒真 ⇒ ① 必红 | 桩打上之后那条 blocker 必须消失（改前它本来就不在，所以这一条在①上红） |

另有一条 B（G 的成稿流程）的判据：`doc.write_mapping` 必须是动作序列里的一步，
而且那三格齐写进了提示词。它单独编号 ⑥。

## 不碰真机工作区

全部用例都在 `tmp_path` 里自建工作区，一个模型调用都不发；真机那两个工作区只在报告里
以只读探针的方式读（`tests/` 里不读它们）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

import paperfixture as FX
from agentflow import agent_prompts as AP
from agentflow import closing as CL
from agentflow import papercompile as PC
from agentflow import papermapping as PM
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import conductor_tools as CT

#: 与 `tests/conftest.py` 同一条纪律：时间戳写死，不用"现在"。
TS = "2026-10-24T00:00:00+08:00"

#: 那一档的理由码（判据里写死字面量：这条判据钉的就是这个名字）。
CODE = "mapping_not_written"


# ------------------------------------------------------------------ 夹具

def _dump(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _statement_row(stmt_id: str = "000000") -> dict:
    """一条最小但读得动的命题行（收工门只数行数，别的读数不许被它弄崩）。"""
    return {
        "stmt_id": stmt_id, "origin": "own_result", "kind": "conjecture",
        "statement_full": "对任意整数 n >= 0：1^3 + 2^3 + ... + n^3 = (n(n+1)/2)^2。",
        "statement_text": "sum-of-cubes-closed-form",
        "proof_text": "对 n 作归纳：基例 n = 0 两端同为 0；归纳步提出公因式 (n+1)^2 即得。",
        "quote_reason": "我方自产命题，没有外部引文要比对",
        "evidence_kind": "heuristic", "status": "active", "bits": {},
        "created_at": TS, "created_by": "test",
    }


def _document_row(doc_id: str = "000000") -> dict:
    """一份已成稿的稿件（build_document 成功过就会留下这样一行）。"""
    return {
        "doc_id": doc_id, "kind": "note",
        "title": "立方和公式的证明与形式化验证",
        "markdown_path": f"documents/{doc_id}.md",
        "sections": [{"heading": "结论", "body": "命题对一切 n >= 0 成立。"}],
        "claims": [{"claim_id": "claim-1", "text": "命题对一切 n >= 0 成立。",
                    "citations": ["stmt:000000"], "evidence_kind": "heuristic",
                    "section": "结论"}],
        "open_problems": [],
        "status": "accepted", "review_rounds": 1, "review_verdict": "成立",
        "created_at": TS, "created_by": "agent-G",
    }


def _ws(root: pathlib.Path, *, statements: int = 1, documents: int = 1) -> pathlib.Path:
    """造一个工作区：只有台账（没有 out/paper，也没有论文包里的任何东西）。"""
    root = pathlib.Path(root)
    store = Store(root)
    store.init(force=True)
    _dump(root / "data" / str(S.TABLES["statements"]["file"]),
          {"schema_version": 2,
           "rows": [_statement_row(S.format_id(i)) for i in range(statements)]})
    _dump(root / "data" / str(S.TABLES["documents"]["file"]),
          {"schema_version": 2,
           "rows": [_document_row(S.format_id(i)) for i in range(documents)]})
    return root


def _gate(root: pathlib.Path):
    """只跑 paper 那一格（对应表那一格跟着它走），其余格子留空。"""
    return CL.check_closing(Store(root), project_dir=str(root), checks=("paper",))


def _mapping_findings(rep) -> list:
    return [f for f in rep.findings if f.check == "mapping"]


def _codes(rep) -> list[str]:
    return [str(f.code) for f in _mapping_findings(rep)]


def _one_detail(rep) -> str:
    return "；".join(str(f.detail) for f in _mapping_findings(rep))


# ============================================================ ① 有命题 + 已成稿 + 无表 => 拦门


def test_1_statements_and_a_finished_document_without_a_mapping_blocks_the_gate(
        tmp_path: pathlib.Path) -> None:
    """① 两趟真机的形体：statements 非空、documents 有行、out/paper 里没有 MAPPING.json。

    断言四件：理由码就是 `mapping_not_written`；这一条是 blocker；`machine_pass`
    是 False（收工门不能判 pass）；读数里点名"缺对应表 ⇒ 论文无法从稿件追溯到台账"。
    """
    root = _ws(tmp_path / "ws", statements=1, documents=1)
    rep = _gate(root)

    assert _codes(rep) == [CODE], _codes(rep)
    assert [f.level for f in _mapping_findings(rep)] == ["blocker"], _mapping_findings(rep)
    assert rep.machine_pass is False, rep.to_dict()
    assert rep.blockers, "blocker 列表是空的 ⇒ 这一条没有让收工门变红"

    written = rep.readings["mapping"]["mapping_written"]
    assert written["checked"] is True, written
    assert written["missing"] is True, written
    assert written["statements"] == 1 and written["documents"] == 1, written
    assert str(written["mapping_json"]).endswith(PM.MAPPING_JSON_NAME), written

    # 同一处读数也单独读一次（收工门那一格只是把它折成 Finding；判据本体自己也要能读）
    direct = CL.mapping_absence_reading(Store(root), root)
    assert direct["checked"] is True and direct["missing"] is True, direct
    assert direct["by_status"] == {"accepted": 1}, direct["by_status"]

    detail = _one_detail(rep)
    assert "缺对应表" in detail and "论文无法从稿件追溯到台账" in detail, detail
    assert PM.MAPPING_JSON_NAME in detail, detail
    # 处置必须写得出可派的动作（只报错不给路，等于把球踢回给人）
    assert "doc.write_mapping" in detail, detail


# ============================================================ ② 表在且三格齐 => 放行


def _numeric_workspace_with_document(tmp_path: pathlib.Path) -> pathlib.Path:
    """一个三格齐的合规论文包（数值实验定理那一行：file / numeric_evidence / exhaustion_note）。

    行与正文的夹具直接取 `test_numeric_theorem_writing_spec` 的那一份（同一个仓库里
    只留一份"合规数值实验定理"的形状，不在这里抄第二份）。
    """
    from test_numeric_theorem_writing_spec import _row as numeric_row
    from test_numeric_theorem_writing_spec import _workspace as numeric_workspace

    root = numeric_workspace(pathlib.Path(tmp_path) / "ws", rows=[numeric_row()])
    _dump(root / "data" / str(S.TABLES["documents"]["file"]),
          {"schema_version": 2, "rows": [_document_row()]})
    # 封一次：paper 那一格要的是"这份 PDF 是盘上这份 tex 编的"。
    engine = FX.fake_engine(root / "_engine")
    with FX.use_engine(engine):
        PC.compile_paper(root)
    return root


def test_2_a_written_mapping_with_the_three_cells_lets_the_gate_through(
        tmp_path: pathlib.Path) -> None:
    """② 有 MAPPING.json 且三格齐 ⇒ 不许误报（`mapping_written.exists` 为真、无 blocker）。"""
    root = _numeric_workspace_with_document(tmp_path)
    rep = _gate(root)

    written = rep.readings["mapping"]["mapping_written"]
    assert written["checked"] is True, written
    assert written["exists"] is True and written["missing"] is False, written
    assert rep.readings["mapping"]["state"] == "pass", rep.readings["mapping"]
    assert _codes(rep) == [], _codes(rep)
    assert rep.machine_pass is True, rep.to_dict()


# ============================================================ ③ M 的验收表记「未完成」


def _acceptance_md(root: pathlib.Path, verdict: str) -> pathlib.Path:
    """M 写的验收表（人读那一份）：一行「论文对应表」。"""
    p = root / "out" / "paper" / "ACCEPTANCE.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "# 最终验收：逐条读数\n\n结论：逐条见下表\n\n"
        "| 判据 | 名称 | 结论 | 读数 |\n|---|---|---|---|\n"
        "| P1 | 论文正文 | 成立 | out/paper/main.tex 在盘上 |\n"
        f"| P12 | 论文对应表 | {verdict} | 论文包里没有 out/paper/MAPPING.json |\n",
        encoding="utf-8", newline="\n")
    return p


def test_3_m_acceptance_table_records_the_missing_mapping_as_unfinished(
        tmp_path: pathlib.Path) -> None:
    """③ M 的验收表：缺失的 MAPPING 记成「未完成」，而读表那一层真的读得出来。

    两半：
    - 解析：「未完成」是一个认得出的结论格（改前它落"读不懂"，那一行既不算通过也不算
      不成立 —— 记了等于没记）；
    - 读数：`conductor.acceptance` 在无 MAPPING 而台账有命题/稿件时，必须把"验收表里
      那一项记未完成"这句提示给 M（这是 M 唯一看得见论文包缺什么的地方）。
    """
    root = _ws(tmp_path / "ws", statements=1, documents=1)
    _acceptance_md(root, "未完成")
    res = CT.conductor_acceptance(Store(root), project_dir=".")
    assert res.ok is True, res

    row = next(r for r in res.data["rows"] if r["id"] == "P12")
    assert row["ok"] is False, row
    assert res.data["not_ok_count"] == 1, res.data["rows"]
    assert any("未完成" in str(p) and PM.MAPPING_JSON_NAME in str(p)
               for p in res.data["problems"]), res.data["problems"]


def test_3b_with_the_mapping_present_the_hint_disappears(tmp_path: pathlib.Path) -> None:
    """③ 的反真空：表补上之后那条提示必须消失（它不许是一条恒真的句子）。"""
    root = _ws(tmp_path / "ws", statements=1, documents=1)
    _acceptance_md(root, "成立")
    PM.write_package(root, [])
    res = CT.conductor_acceptance(Store(root), project_dir=".")
    assert res.ok is True, res
    assert row_of(res, "P12")["ok"] is True, res.data["rows"]
    assert not [p for p in res.data["problems"] if "未完成" in str(p)], res.data["problems"]


def row_of(res, row_id: str) -> dict:
    """按编号取一行（取不到 ⇒ 判据自己接错了，不是"通过"）。"""
    return next(r for r in res.data["rows"] if r["id"] == row_id)


def test_3c_the_m_prompt_says_how_to_record_the_missing_mapping() -> None:
    """③ 的提示词那一半：M 自己要写得出来这件事（验收表是 M 手写的）。

    读的是渲染后的提示词（纯函数，零模型调用）：论文交付物的构成里必须有对应表，
    而"缺了就记未完成"这句必须写在 M 看得到的地方 —— 否则 M 只会写两份 ACCEPTANCE。
    """
    text = AP.system_prompt("M", registry=build_registry().registry)
    for needle in ("out/paper/MAPPING.json", "未完成", "验收表"):
        assert needle in text, f"M 的提示词里读不到 {needle!r}"


# ============================================================ ④ 反真空：还没成稿 => 不许报


def test_4_statements_without_a_finished_document_are_not_reported(
        tmp_path: pathlib.Path) -> None:
    """④ 反真空：只有 statements、还没成稿 ⇒ ① 不许报（否则会误伤早期阶段）。

    同一条里带上另一半（补上稿件 ⇒ 立刻报）：只有两半都在，才证明这条反真空
    钉的是"成稿"这个前提，而不是"反正都不报"。
    """
    root = _ws(tmp_path / "ws", statements=1, documents=0)
    rep = _gate(root)
    assert _codes(rep) == [], _codes(rep)
    assert rep.readings["mapping"]["mapping_written"]["missing"] is False

    _dump(root / "data" / str(S.TABLES["documents"]["file"]),
          {"schema_version": 2, "rows": [_document_row()]})
    after = _gate(root)
    assert _codes(after) == [CODE], _codes(after)


# ============================================================ ⑤ 反真空：打桩恒真 => ① 必红


def test_5_stubbing_the_existence_check_true_makes_the_blocker_disappear(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤ 反真空：把"MAPPING 在不在盘上"这个检查打桩成恒真 ⇒ ① 必须红。

    两段：先证 ① 在真检查下是红的（这一半在改前就是红的），再打桩、证那条红消失
    且 `exists` 变成 True（桩真的生效了）。没有第二段，① 的绿可能只是"压根没查"。
    """
    root = _ws(tmp_path / "ws", statements=1, documents=1)
    before = _gate(root)
    assert _codes(before) == [CODE], _codes(before)

    monkeypatch.setattr(CL, "_mapping_json_exists", lambda path: True)
    after = _gate(root)
    written = after.readings["mapping"]["mapping_written"]
    assert written["exists"] is True, written
    assert _codes(after) == [], (
        "把存在性检查打桩成恒真之后 blocker 还在 ⇒ 这一条不是靠那个检查在红：" + _one_detail(after))


# ============================================================ ⑥ B：G 的成稿流程


def test_6_the_g_prompt_makes_write_mapping_a_step_of_the_manuscript_flow() -> None:
    """⑥ G 的成稿流程：`doc.write_mapping` 是动作序列里的一步，三格齐才算写完。

    判三件：
    - 四步的顺序读得出来（正文 -> 落对应表 -> 核三格齐 -> 编译）；
    - "只写了正文、没调过 doc.write_mapping 等于没成稿"这句话在；
    - 三格齐的口径在（file + numeric_evidence/exhaustion_note，或 Lean 那两格）。
    """
    text = AP.system_prompt("G", registry=build_registry().registry)
    assert len(text) > 5000, f"G 的渲染只有 {len(text)} 字符 ⇒ 这一条没有落脚点"

    for needle in ("成稿是四步动作序列", "没调过 `doc.write_mapping`", CODE,
                   "三格齐", "numeric_evidence", "exhaustion_note",
                   "lean_file", "lean_target"):
        assert needle in text, f"G 的提示词里读不到 {needle!r}"

    marks = ("① 正文用 `fs.write`", "② 调 `doc.write_mapping`", "③ 逐行核",
             "④ 最后调 `doc.paper_compile`")
    pos = [text.find(m) for m in marks]
    assert all(p >= 0 for p in pos), dict(zip(marks, pos))
    assert pos == sorted(pos), f"四步的顺序读不出来：{dict(zip(marks, pos))}"


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
