# -*- coding: utf-8 -*-
"""判据（SEEDREADME，2026-11-21）：未声明的文件不许入库 —— 非 dry 档受控拒 `not_declared_reference`。

## 业主口径（逐字裁定）

M 不自己判断哪份文献可靠：
① 只有用户提示词里明确点名的才算可靠参考文献、才可入库；
② 未点名的文件只能当研究参考（可读），不可入库；
③ 默认 fail-closed：没有声明 ⇒ 一律不许入库。

声明真身：工作区根的 `RELIABLE-REFERENCES.json`
（`{"paths": ["a.pdf", "b/"], "verbatim": "<用户原话>"}`）。A 侧两条入库入口
（工具 `search.ingest_local` 与动作 `A.ingest_local`）的非 dry 档都按它核；命中未声明
⇒ 受控拒、零写入，拒信指向"M 先把用户声明记下来"。`dry_run` 是发现档（零写入），
不拦 —— 发现清单本来就是给 M 定声明用的。

## 守的几件事（每件都带反真空）

| # | 判据 | 反真空 |
|---|---|---|
| a | 工作区内、未声明的文件：非 dry 档被拒（`kind=not_declared_reference`、零行、拒信点名声明文件与 M 的动作） | 把声明核打桩成"全放行" ⇒ a 必红 |
| b | 声明覆盖（目录 `source/` / 裸文件名 `paper-0.txt`）⇒ 非 dry 档照常登记 | — |
| c | 声明为空 / 坏掉 ⇒ fail-closed（全拒，坏声明在拒信里点名"读不出来"） | — |
| d | 混进一份未声明的 ⇒ 整笔拒、零写入（不是"只收声明过的"） | — |
| e | `dry_run=True` 对未声明文件照常发现、零写入 | — |
| f | 工作区外的目录不受这份声明管（边界：声明只管辖工作区内的参考材料） | — |
| g | A 的动作（`A.ingest_local`）与工具同一道闸 | — |
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import locallib as LL
from agentflow.agent_a import AgentA
from agentflow.store import Store
from agentflow.tools import build_for_role

#: 一份有正文的本地文件（`.txt` 在抽取支持面内：`test_search_offline` 走的就是这一档）。
_BODY = ("Hyperplane sections of convex bodies and the volume estimate theorem give a "
         "sharp bound for maximal central sections of the unit cube. " * 4)


def _put(root: pathlib.Path, name: str) -> pathlib.Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_BODY, encoding="utf-8")
    return path


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    (st.root / "source").mkdir(parents=True, exist_ok=True)
    return st


def _declare(st: Store, paths: list[str], verbatim: str = "用户点名了这些") -> None:
    (st.root / LL.DECLARATION_NAME).write_text(
        json.dumps({"paths": paths, "verbatim": verbatim}, ensure_ascii=False),
        encoding="utf-8")


def _reg(st: Store):
    registry = build_for_role("A", store=st, workspace_root=st.root).registry
    registry.bound_role = "A"
    return registry


def _problems(res, st: Store) -> list[str]:
    """这一笔"应被拒却入库了"的问题（空 = 拒得对）。"""
    problems: list[str] = []
    if res.ok:
        problems.append("这笔登记成功了 —— 未声明的文件被放进了 literature（fail-closed 没生效）")
    kind = str((res.meta or {}).get("kind") or "")
    if kind != "not_declared_reference":
        problems.append(f"拒信的理由码不是 not_declared_reference（是 {kind!r}）")
    recorded = (res.meta or {}).get("recorded")
    if recorded is not False:
        problems.append(f"拒信没有说 recorded=False（是 {recorded!r}）：零写入这件事要写在读数里")
    if st.rows("literature"):
        problems.append(f"库里有 {len(st.rows('literature'))} 行 literature —— 拒了却写了行")
    error = str(res.error or "")
    for needle in (LL.DECLARATION_NAME, "M 先把用户声明记下来", "研究参考"):
        if needle not in error:
            problems.append(f"拒信没写「{needle}」（读的人不知道下一步该做什么）")
    return problems


# ---------------------------------------------------------------- a 未声明 ⇒ 拒


def test_a_undeclared_workspace_file_is_refused_before_any_write(
        tmp_path: pathlib.Path) -> None:
    """a：工作区内、用户没点名的文件 ⇒ 非 dry 档受控拒、零写入。"""
    st = _store(tmp_path)
    _put(st.root, "source/paper-0.txt")
    res = _reg(st).call("search.ingest_local", books_dir="source", pattern="*.txt")
    assert _problems(res, st) == [], _problems(res, st)


def test_a_the_refusal_names_the_file_so_the_next_step_is_obvious(
        tmp_path: pathlib.Path) -> None:
    """a（读数）：拒信逐份点名未声明的文件（不是只说"有些文件没声明"）。"""
    st = _store(tmp_path)
    _put(st.root, "source/paper-0.txt")
    res = _reg(st).call("search.ingest_local", books_dir="source", pattern="*.txt")
    undeclared = list((res.meta or {}).get("undeclared") or [])
    assert undeclared == ["source/paper-0.txt"], undeclared


def test_a_anti_vacuum_stubbing_out_the_declaration_check_makes_it_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a 的反真空：把声明核打桩成"全放行" ⇒ 同一个检查必须红。"""
    st = _store(tmp_path)
    _put(st.root, "source/paper-0.txt")
    assert _problems(_reg(st).call("search.ingest_local", books_dir="source", pattern="*.txt"),
                     st) == [], "夹具前提：不打桩时这一笔应当被拒得对（problems 为空）"
    monkeypatch.setattr(LL, "undeclared_workspace_books", lambda *_a, **_k: ([], ""))
    res = _reg(st).call("search.ingest_local", books_dir="source", pattern="*.txt")
    assert _problems(res, st), (
        "把声明核打桩成全放行之后判据仍然绿 —— 它没有在读声明（a 是橡皮图章）")


# ---------------------------------------------------------------- b 声明覆盖 ⇒ 放行


@pytest.mark.parametrize("declared", ["source/", "source/paper-0.txt", "paper-0.txt"])
def test_b_a_declared_file_is_ingested(tmp_path: pathlib.Path, declared: str) -> None:
    """b：三种声明写法（目录 / 整条路径 / 裸文件名）都算"用户点名"，非 dry 档照常登记。"""
    st = _store(tmp_path)
    _put(st.root, "source/paper-0.txt")
    _declare(st, [declared])
    res = _reg(st).call("search.ingest_local", books_dir="source", pattern="*.txt")
    assert res.ok, (res.error, dict(res.meta))
    data = res.unwrap()
    assert data["ingested"] == 1, data
    assert len(st.rows("literature")) == 1, st.rows("literature")


# ---------------------------------------------------------------- c fail-closed


def test_c_an_empty_declaration_refuses_everything(tmp_path: pathlib.Path) -> None:
    """c：用户没点名（`paths=[]`）⇒ 一份都不许入库。"""
    st = _store(tmp_path)
    _put(st.root, "source/paper-0.txt")
    _declare(st, [], verbatim="用户这次没点名哪几份")
    res = _reg(st).call("search.ingest_local", books_dir="source", pattern="*.txt")
    assert _problems(res, st) == [], _problems(res, st)


def test_c_a_corrupt_declaration_is_fail_closed(tmp_path: pathlib.Path) -> None:
    """c：声明在盘上但读不出来 ⇒ 仍全拒，拒信点名"读不出来"（不是折成"没声明"）。"""
    st = _store(tmp_path)
    _put(st.root, "source/paper-0.txt")
    (st.root / LL.DECLARATION_NAME).write_text("{not json", encoding="utf-8")
    res = _reg(st).call("search.ingest_local", books_dir="source", pattern="*.txt")
    assert _problems(res, st) == [], _problems(res, st)
    assert "读不出来" in str(res.error or ""), res.error


# ---------------------------------------------------------------- d 混装 ⇒ 整笔拒


def test_d_one_undeclared_file_refuses_the_whole_batch(tmp_path: pathlib.Path) -> None:
    """d：声明了一份、混进一份没声明的 ⇒ 整笔零写入（不是"只收声明过的"）。"""
    st = _store(tmp_path)
    _put(st.root, "source/paper-0.txt")
    _put(st.root, "source/paper-1.txt")
    _declare(st, ["paper-0.txt"])
    res = _reg(st).call("search.ingest_local", books_dir="source", pattern="*.txt")
    assert _problems(res, st) == [], _problems(res, st)
    assert (res.meta or {}).get("undeclared") == ["source/paper-1.txt"], res.meta


# ---------------------------------------------------------------- e dry_run 是发现档


def test_e_dry_run_discovers_undeclared_files_without_writing(tmp_path: pathlib.Path) -> None:
    """e：`dry_run=True` 只发现、零写入 —— 未声明也照常报清单（M 要拿它定声明）。"""
    st = _store(tmp_path)
    _put(st.root, "source/paper-0.txt")
    res = _reg(st).call("search.ingest_local", books_dir="source", pattern="*.txt",
                        dry_run=True)
    assert res.ok, (res.error, dict(res.meta))
    data = res.unwrap()
    assert data["count"] == 1, data
    assert data["books"][0]["source"].endswith("paper-0.txt"), data["books"]
    assert not st.rows("literature"), "dry_run 写了 literature 行"
    assert not st.rows("lit_candidates"), "dry_run 写了候选行"


# ---------------------------------------------------------------- f 边界：工作区外


def test_f_files_outside_the_workspace_are_not_governed_by_the_declaration(
        tmp_path: pathlib.Path) -> None:
    """f：工作区外的目录不受这份声明管（那是调用方自己点名的外部书架）。

    声明里的 `paths` 是工作区相对路径，表达不了工作区外的文件；把工作区外的目录也
    按"未声明"拒掉，等于让 `A.ingest_local` 再也收不了任何外部目录 —— 那不是业主
    这条规则要挡的路（它挡的是工作区里那批"看起来已在工作区、其实没入库"的材料）。
    """
    st = _store(tmp_path)
    outside = tmp_path / "outside"
    _put(outside, "book.txt")
    res = _reg(st).call("search.ingest_local", books_dir=str(outside), pattern="*.txt")
    assert res.ok, (res.error, dict(res.meta))
    assert res.unwrap()["ingested"] == 1, res.unwrap()


# ---------------------------------------------------------------- g 动作同一道闸


def test_g_the_action_uses_the_same_gate(tmp_path: pathlib.Path) -> None:
    """g：A 的动作（`A.ingest_local`）与工具同一道闸：未声明 ⇒ 同一个理由码、零行。"""
    st = _store(tmp_path)
    _put(st.root, "source/paper-0.txt")
    res = AgentA(st, providers=[]).ingest_local(books_dir="source", pattern="*.txt")
    assert res["ok"] is False, res
    assert res["kind"] == "not_declared_reference", res
    assert res["refusal_reason"] == "invalid_params", res
    assert not st.rows("literature"), "动作拒了却写了 literature 行"
    assert "M 先把用户声明记下来" in res["error"], res["error"]


def test_g_a_declared_file_goes_through_the_action(tmp_path: pathlib.Path) -> None:
    """g（正控）：声明过之后动作照常登记（红不是因为它永远红）。"""
    st = _store(tmp_path)
    _put(st.root, "source/paper-0.txt")
    _declare(st, ["source/"])
    res = AgentA(st, providers=[]).ingest_local(books_dir="source", pattern="*.txt")
    assert res["ok"] is True, res
    assert res["ingested"] == 1, res
