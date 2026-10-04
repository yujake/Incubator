"""`AgentD.write_report`（等级 1 写盘）与 `demo.build_fixtures`（等级 1 写盘）的判据测试。

## 这两个函数各自的关键判据

| 函数 | 判据 | 为什么必须打在判据上 |
|---|---|---|
| `AgentD.write_report` | "没做"与"做了但没结果"必须分开写 | 报告里断言一个从未做过的查询没有结果就是"在报告里造假"（docstring 逐字点出这个坑，且已修） |
| `demo.build_fixtures` | 候选清单里的三对刻意构造的重复样本必须在位 | 少了任何一条，`run_demo` 的"去重/判重/幂等"三件事就从"验证过"变成"没验证过" |

`build_fixtures` 是 `run_demo` 内部调用的，所以它此前从未被直接调用过 ——
一个"少写一条候选"的实现能让 `run_demo` 照常返回 0（只是少验证一件事），
而 `test_demo_end_to_end.py` 的既有断言看不出来。这就是零直接测试的代价。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentflow import schema as S
from agentflow.agent_d import AgentD
from agentflow.demo import DOCS, build_fixtures, run_demo
from agentflow.store import Store

from conftest import TS, add_concept, add_literature, add_relation, sync_counters


# ============================================================ 辅助


def _add_question(st: Store, qid: str, **kw) -> dict:
    """插入一条合法的 `research_questions` 行。

    `priority` 从 `schema.PRIORITIES` 取（§5.3：夹具不写死受控词表的取值）。
    """
    row = S.ResearchQuestion(
        question_id=qid,
        question=kw.get("question", "这是一个研究问题"),
        origin=kw.get("origin", "C:paths:0000:0000"),
        related_concept_ids=list(kw.get("related_concept_ids", [])),
        related_relation_ids=list(kw.get("related_relation_ids", [])),
        status=kw.get("status", S.QUESTION_STATUSES[0]),
        priority=kw.get("priority", S.PRIORITIES[1]),
        evidence_lit_ids=list(kw.get("evidence_lit_ids", [])),
        waiting_request_ids=list(kw.get("waiting_request_ids", [])),
        notes=kw.get("notes", ""),
        created_at=TS,
        updated_at=TS,
    )
    row.validate()
    with st.tx("research_questions", actor="test", note="fixture") as tx:
        tx.upsert("research_questions", row.to_dict())
    return row.to_dict()


def _graph(st: Store) -> None:
    """一条关系 + 两个概念，供 write_report 的溯源引用。"""
    add_literature(st, "0000", path="0000/s.txt")
    add_concept(st, "0000", "group", related_concepts=["0001"])
    add_concept(st, "0001", "abelian group", related_concepts=["0000"])
    add_relation(st, "0000", ["0000", "0001"], "0000", quote="q", quote_verified=True)
    sync_counters(st)


# ============================================================ write_report


def test_write_report_writes_a_file_whose_path_is_the_return_value(tmp_path: Path):
    """正向：返回的路径真的存在，且内容是那份研究报告。

    断言打在判据上：不是"返回了一个字符串"，而是
    "返回的路径可读、且里面是 §4.5 结构的那份报告（含阅读须知与逐问题两节）"。
    只断言返回类型会让一个"算了半天但没落盘"的实现通过。
    """
    st = Store(tmp_path / "ws")
    st.init()
    _graph(st)
    _add_question(st, "0000", related_concept_ids=["0000", "0001"], related_relation_ids=["0000"])

    out = AgentD(st).write_report()

    p = Path(out)
    assert p.exists() and p.is_file(), out
    text = p.read_text(encoding="utf-8")
    assert text.startswith("# D 初步研究报告"), text[:80]
    assert "## 0. 阅读须知" in text and "## 1. 问题台账总览" in text
    assert "## 2. 逐个问题" in text
    assert "0000" in text


def test_write_report_marks_evidence_as_backfilled_only_when_research_was_not_run(
    tmp_path: Path,
):
    """判据："没做"与"做了但没结果"必须分开写（docstring 逐字记的坑）。

    ## 实测到的两个可区分态（这是本断言的事实基础）

    `research()` 生产路径总是把 `evidence` 放进取值结果的（`agent_d.py:3133`），
    所以"研究过了但 `evidence` 是 `None`" 不是一个可达的状态。可达的两态是：

    - 态 A = 没做：`last_research` 里没有这个问题 ⇒ `write_report` 就地补取
      一次溯源，并必须写明"本问题本轮未进入研究步骤 + 报告期补取"；
    - 态 B = 做了有结果：`last_research` 里有它（由真实 `research()` 写入）⇒
      报告用那份记录里的证据，不得出现"报告期补取"这个标记。

    只断言"文件里有 0000"会让"两态写成同一句话"的实现照样通过 ——
    而那正是被修掉的那个缺陷，也正是 `DEVELOPMENT.md` §3 纪律 1 的形态。
    """
    st = Store(tmp_path / "ws")
    st.init()
    _graph(st)
    _add_question(st, "0000", related_concept_ids=["0000", "0001"],
                  related_relation_ids=["0000"], waiting_request_ids=[])

    # 态 B 先做：走真实的 research()，于是 last_research 由生产路径填充。
    d = AgentD(st)
    d.research("0000")
    assert "0000" in getattr(d, "last_research", {}), "research() 没登记取值结果 ⇒ 态 B 造不出来"
    done = Path(d.write_report(out_path=tmp_path / "ws" / "done.md")).read_text(encoding="utf-8")

    # 态 A：换一个干净的 AgentD（last_research 为空 = 没做过研究）。
    fresh = AgentD(st)
    assert not getattr(fresh, "last_research", {}), "新建的 AgentD 不该带研究记录"
    not_done = Path(fresh.write_report(out_path=tmp_path / "ws" / "not_done.md")
                    ).read_text(encoding="utf-8")

    assert not_done != done, "两态写出了逐字相同的报告 ⇒ 没做/做了有结果被折叠了"
    assert "（报告期补取）" in not_done, (
        "态 A（本轮没做过研究）的结论区没有标注『报告期补取』⇒ 读者会把补取的证据"
        "误读成本轮的研究结论"
    )
    assert "（报告期补取）" not in done, "态 B（本轮真的研究过）不该标注补取"
    # 态 A 还必须说明这一轮没做过研究，而不是只留一个标记 ——
    # "没做"必须有一句话解释它为什么没有结论（`DEVELOPMENT.md` §3 纪律 1）。
    assert "还没进入研究步骤" in not_done, not_done[-1500:]
    assert "还没进入研究步骤" not in done, "态 B 有研究记录，不该说它没进入研究步骤"


def test_write_report_on_empty_store_still_writes_and_says_no_conclusions(tmp_path: Path):
    """三态纪律（第 3 态 = 做了有结果的反面）：零问题时也要落盘并如实说没有结论。

    零问题是合法的"做了、结论是空"——它不许被折叠成"没做"（抛异常/不写文件），
    也不许伪装成"研究了但没有发现"。
    """
    st = Store(tmp_path / "ws")
    st.init()
    out = AgentD(st).write_report(out_path=(tmp_path / "ws" / "empty.md"))
    text = Path(out).read_text(encoding="utf-8")
    assert "问题总数：0" in text, text[:400]
    assert "本轮尚未形成任何结论" in text, text[:400]


def test_write_report_honours_explicit_out_path_and_creates_parent_dirs(tmp_path: Path):
    """负控（防误伤）：显式 `out_path` 必须被尊重，且父目录会被创建。

    为什么是负控：默认路径依赖 `_reports_dir()`。若实现把 `out_path` 吞掉
    （例如总是写默认位置），人给的路径会被静默忽略 —— 而"调用方以为文件在 A、
    实际在 B"是典型的静默失败。深一层的父目录顺便测了 `mkdir(parents=True)`。

    `out_path` 必须在「工作区内」（`draft/37` §118）：相对路径按工作区根解析，
    跳到工作区外的绝对路径一律拒 —— 后者的判据在
    `tests/test_write_report_path.py`（T2 第 1 趟的泄漏就是那么发生的）。
    """
    st = Store(tmp_path / "ws")
    st.init()
    _graph(st)
    target = tmp_path / "ws" / "deep" / "nested" / "r.md"
    out = AgentD(st).write_report(out_path=target)
    assert Path(out) == target.resolve()
    assert target.exists()


# ============================================================ build_fixtures


def test_build_fixtures_writes_sources_manifest_and_returns_candidates_json(tmp_path: Path):
    """正向：返回的 `candidates.json` 存在、可解析，且每个素材文件都写出来了。

    素材文件清单从 `demo.DOCS` 反查（§5.3：夹具不许写死清单）。

    只有 `sources/` 下有素材文件 —— `fixtures/` 里只有 `candidates.json`。
    第一版断言写成了"fixtures/ 下也有素材"，实测为假（`build_fixtures` 只往
    `sources/` 写正文，`fixtures/` 是清单目录）。那是我的假设错，不是 src 的缺陷；
    这里按实测改正，并把 `fixtures/` 的恰好一件也钉住（多出文件是信号）。
    """
    cpath = build_fixtures(tmp_path)

    assert cpath.name == "candidates.json" and cpath.exists()
    assert cpath.parent.name == "fixtures"
    payload = json.loads(cpath.read_text(encoding="utf-8"))
    assert isinstance(payload["candidates"], list) and payload["candidates"]
    for name in DOCS:
        assert (tmp_path / "demo" / "sources" / name).exists(), f"{name} 没被写出"
    assert sorted(p.name for p in cpath.parent.iterdir()) == ["candidates.json"]


def test_build_fixtures_keeps_the_two_deliberate_duplicate_samples(tmp_path: Path):
    """判据：两种不同的重复样本都必须在位（少一条 = 少验证一件事）。

    `demo.py` 的模块 docstring 逐字列出三个理由，前两个各靠一对特定重叠触发，
    而这两对的重叠方式不同（实测清单已核对）：

    | 对 | 素材 | 重叠在哪 | 触发什么 |
    |---|---|---|---|
    | 元数据重复 | 两条候选都指向 `abelian_group_reprint.txt` | `(title, doi, year)` 全同 | 文献去重（应复用既有 lit_id） |
    | 正文重复 | `abelian_group.txt` 与 `abelian_group_reprint.txt` | 正文逐字相同，元数据不同 | 关系判重（同一概念组 + 同一引文 ⇒ 拒绝写入） |

    断言这两件事同时成立（而不是"候选数 >= 5"）：只数条数的话，
    把这两对样本删掉、随手加两条新候选也能通过 —— 而 demo 会照常返回 0，
    于是"去重与判重验证过"变成一句没有依据的话。
    """
    payload = json.loads(build_fixtures(tmp_path).read_text(encoding="utf-8"))
    cands = payload["candidates"]

    # ---- (1) 元数据重复：清单里至少两条候选的 (doi, title, year) 逐字段相同
    #      ⇒ 文献去重（应复用既有 lit_id，而不是新建一行）。
    #      实测修正：不能把"共用同一素材路径"当成元数据重复的判据 ——
    #      重印那一条故意用了不同的 title/doi/year，它测的是正文重复
    #      （见下一条）。第一版把两件事混成一条，被实测推翻。
    meta_keys = [(str(c["doi"]), str(c["title"]), c["year"]) for c in cands]
    meta_dup = [k for k in set(meta_keys) if meta_keys.count(k) >= 2]
    assert meta_dup, (
        "清单里没有任何两条候选的 (doi, title, year) 完全相同 ⇒ "
        "文献去重这条路径在 demo 里跑不到，而 demo 的 docstring 声称它被验证过"
    )
    # 占位键（doi=None）不算：`_candidate` 允许 doi 为空，那时代码走标题/年份判重。
    assert any(k[0] for k in meta_dup), f"重复的判重键全是空 DOI：{meta_dup}"

    # ---- (2) 正文重复：两篇不同路径的素材正文逐字相同 ⇒ 关系判重
    #      （同一概念组 + 同一句引文 ⇒ 应被拒绝写入）。
    texts = {n: "\n\n".join(pages) for n, pages in DOCS.items()}
    dup_text = sorted(n for n in DOCS if list(texts.values()).count(texts[n]) >= 2)
    assert len(dup_text) >= 2, f"没有两篇不同素材的正文逐字相同：{dup_text}"

    # ---- (3) 那两篇正文相同的素材必须都被某条候选引用，否则正文重复到不了数据层。
    used_paths = {str(c["path"]) for c in cands}
    assert set(dup_text) <= used_paths, f"正文重复的素材没被任何候选引用：{set(dup_text) - used_paths}"

    # ---- (4) 那对正文相同的候选，其元数据必须不同（这是刻意的）：
    #      若元数据也相同，它们会先被文献去重吃掉 —— 关系判重这条路径就永远跑不到，
    #      而 demo 的 docstring 声称它验证过关系判重。
    #      一个素材路径可以被多条候选引用（实测：重印那一条被 2 条引用），
    #      所以这里按候选而不是按路径索引。
    first_path = dup_text[0]
    a = next(c for c in cands if str(c["path"]) == first_path)
    b = next(c for c in cands if str(c["path"]) == dup_text[1])
    assert (str(a["doi"]), a["title"], a["year"]) != (str(b["doi"]), b["title"], b["year"]), (
        "正文相同的两条候选元数据也相同 ⇒ 它们会先被文献去重吃掉，关系判重跑不到"
    )


def test_build_fixtures_is_idempotent_on_rerun(tmp_path: Path):
    """负控（防误伤）：重复调用必须覆盖而不是追加/报错。

    为什么是负控：`run_demo(reset=...)` 的幂等性建立在这件事上。
    一个用 `open(..., "x")` 或"已存在就跳过"的实现会在第二次调用时
    表现不同（抛错，或留下第一次的陈旧清单）—— 而陈旧清单会让 demo
    "看起来跑了"但验证的是旧数据。
    """
    first = json.loads(build_fixtures(tmp_path).read_text(encoding="utf-8"))
    second = json.loads(build_fixtures(tmp_path).read_text(encoding="utf-8"))
    assert first == second


def test_run_demo_rebuilds_the_manifest_so_external_edits_cannot_redirect_it(tmp_path: Path):
    """负控（我原来的假设被实测推翻，这里如实记下来）。

    ## 原来的假设与实测结果

    我原本假设 `run_demo` 会消费调用方已经写好的 `candidates.json`，
    于是写了"把它清空后 `run_demo` 应当失败"这条断言。实测：它仍然返回 0。
    读代码后确认原因：`demo.py:214` 的 `run_demo` 第一件事就是
    `cpath = build_fixtures(root)` —— 它无条件重新生成清单，从不读现成的。

    ## 所以这里改测实际成立的那条性质

    无条件重建 ⇒ 调用方外部改清单不能改变 demo 的行为。这是一条真实的
    （虽然更弱的）保证：它意味着 demo 的输入不可被"上游残留状态"污染。
    断言写成"篡改清单后 `run_demo` 依然成功，且篡改被覆盖回正确的清单"。

    这条不是"`build_fixtures` 的产物被消费"的证据 —— 那条证据本文件里
    没有，我没有做到。它被记进了 `docs/PROPOSALS.md` 的 G-4 条。
    """
    build_fixtures(tmp_path)
    cpath = tmp_path / "demo" / "fixtures" / "candidates.json"
    cpath.write_text(json.dumps({"candidates": []}, ensure_ascii=False), encoding="utf-8")

    rc = run_demo(tmp_path, reset=False, verbose=False)

    assert rc == 0, rc
    restored = json.loads(cpath.read_text(encoding="utf-8"))
    assert restored["candidates"], "run_demo 没有重建清单：被清空的 candidates.json 原样留着"
    assert restored == json.loads(build_fixtures(tmp_path).read_text(encoding="utf-8"))
