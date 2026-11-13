# -*- coding: utf-8 -*-
"""彩排判据 C8：D 只递指针 —— 携带单 → B 按稿收录（正文 / 依赖 / 路径号都由 B 从稿里读）。

## 业主口径（逐字）

> 「D 对命题台账只有只读权限，D 向 B 提交要登记的命题时都是有证明或数值实验的（即 E 和
>   F 的成果）…B 侧做好适配（应该在手稿里找命题和数值实验程序，不录入其它内容）。」

## 这一条链钉的次序

1. F 落一份已签的 `reports/f-proof-<稿号>.md`：`## 命题` / `## 证明` / `## 依赖` 三节，
   依赖表只有三列（引用 / 命题号 / 步），稿里没有路径号；
2. D 用 `write_report` 写携带单：一行 `| mss:<稿号> | <路径> | <文件 sha> | |`；
   D 不写 `statements`、也不在报告里抄 `## 命题` 的正文；
3. B 只拿到携带单里的 `mss:<稿号>`（指针），用 `depsection.read_carried_manuscript`
   按清单寻址到那份稿，再走 `ingest_manuscript(mode=register)` 收录。

## 终态读数（盘上 / 台账上可查）

| 判据 | 期望 |
|---|---|
| D 那一侧 | `statements` 仍是 1 行（只有夹具里那条被引引理）；D 的 `write_set` 不含 `statements`；报告里有携带单、没有命题正文 |
| 指针 | `read_carried_manuscript(statement_ids=["mss:<稿号>"])` 回 `source=carried_by_D`，`path` 是那份 F 稿 |
| B 那一侧 | 收录成功且 `manuscript_source=carried_by_D`；新行 `statement_full` 逐字等于稿的 `## 命题`；`manuscript_id` 是稿号 |
| 依赖三列 | 依赖行 `source_stmt_id` / `step` / 引用标签三格与稿里那一行逐字一致；`path_group=1`、`used_by=stmt:<新号>` |
| 路径号 | `manuscriptpaths.path_reading` 的 `paths[0].manuscript` 是这份稿（号由秘书在收录事务里分配，D 与稿都没写） |

## 反真空

1. 撤掉携带单那一节 ⇒ 指针寻址不到任何稿（`source != carried_by_D`、`path` 空）；
2. 撤掉稿的 `## 命题` 那一节 ⇒ B 受控拒 `pointer_manuscript_missing_statement`，
   `statements` 零新增（证明命题确实是从稿里读的，不是从 D 的指针里猜的）。

## 计数读数（第三条要求）

`statements` 行数（夹具引理 1 + B 新收 1 = 2）与 `dependencies` 行数（1）。判定面是
替身、没有模型花费，所以这一条链的账是计数。

## 不做什么

- 不测命题形态闸（C5 的对象；这里用 `conftest.b_form_gate_ok` 把那一格钉成放行）；
- 不改 D 的写集、不新增携带单格式；不跑全量。
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
_TESTS = pathlib.Path(__file__).resolve().parent
for _path in (_SRC, _TESTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import conftest  # noqa: E402

from agentflow import depsection as DS  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import manuscriptpaths as MP  # noqa: E402
from agentflow import proofregistry as PR  # noqa: E402
from agentflow import specs  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_d import AgentD  # noqa: E402
from agentflow.secretary import Secretary  # noqa: E402
from agentflow.store import Store  # noqa: E402

#: 被引的那条在册命题（依赖段的引用门槛：`pre_theorem` 及以上）。
DEP_SID = "000000"
#: F 稿里的新命题（B 要从 `## 命题` 这一节读出来的就是它）。
PROPOSITION = "设 n 是偶数；则 n^2 是 4 的倍数。"
PROOF = ("1. 设 n = 2k。\n"
         "2. 则 n^2 = 4k^2，被 4 整除。")
#: F 的稿号（稿名带它；命题号由 B 收录时才发）。
MID = "000201"
REL = f"reports/f-proof-{MID}.md"

DEPS = ("| 引用 | 命题号 | 步 |\n|---|---|---|\n"
        f"| 引理：p 阶元的存在性 | stmt:{DEP_SID} | 1 |\n")


def _manuscript(proposition: str = PROPOSITION) -> str:
    """F 稿：稿头没有命题号，依赖表只有三列；`## 命题` 是这段正文的唯一来源。

    洗稿元信息由 `depsection.mark_washed` 盖（B 对 D 携带来的稿要求这一行；
    本判据不手抄格式）。
    """
    head = ("# F 的证明手稿\n\n"
            "- 计划：000002 · 子目标：S1\n")
    body = (head + "\n## 命题\n\n" + proposition + "\n\n"
            "## 证明\n\n" + PROOF + "\n\n## 依赖\n\n" + DEPS)
    return DS.mark_washed(body, actor="secretary:F")


class _Seam:
    """B 的同一命题检索那一问的替身：回「在册没有逐字同一条」。"""

    class _Call:
        ok = True
        problem = ""
        detail = ""

    def ask_json(self, prompt, **kw):
        note = str(kw.get("note") or "")
        if note.endswith("statement_keywords"):
            return ({"keywords": ["偶数", "平方", "整除"],
                     "why": "打桩：这几个词能把同一条命题捞出来"}, self._Call())
        return ({"decision": "different", "canonical_name": "n^2 是 4 的倍数",
                 "same_as": "", "route": "", "condition": "打桩：n 是偶数",
                 "conclusion": "打桩：n^2 是 4 的倍数",
                 "reason": "打桩：在册没有逐字同一条命题", "basis": ["打桩"]},
                self._Call())


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _citable(st: Store) -> None:
    conftest.seed_statement_row(st, stmt_id=DEP_SID, statement_full="引理：p 阶元的存在性",
                                kind="lemma", proof_text="引理：p 阶元的存在性")
    conftest.sign_for_the_gate(st.root, statement_id=DEP_SID,
                               proof_text="引理：p 阶元的存在性", store=st)
    row = next(dict(r) for r in st.rows("statements")
               if str(r.get("stmt_id")) == DEP_SID)
    bits = dict(row.get("bits") or {})
    bits["proof"] = True
    ev = dict(bits.get("evidence") or {})
    ev.setdefault("proof_process", str(row.get("proof_text") or ""))
    bits["evidence"] = ev
    bits["grade"] = EB.derive_grade(bits, kind="lemma")
    with st.tx("statements", actor="夹具") as tx:
        tx.upsert("statements", dict(row, bits=bits))


def _write_manuscript(st: Store, text: str = "") -> pathlib.Path:
    path = pathlib.Path(st.root) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or _manuscript(), encoding="utf-8")
    return path


def _carried_row(st: Store) -> dict:
    path = pathlib.Path(st.root) / REL
    return {"statement_id": "", "experiment_id": "", "manuscript_id": MID,
            "path": REL, "proof_no": "",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _d_report(st: Store, *, carried: bool = True) -> str:
    """D 的真报告口：把携带单那一行喂给它，由它自己渲染那一节。

    `_carried_manuscripts` 是 D 的「哪些稿要上携带单」来源，本判据把它打桩成
    「已有一份签好的 F 稿」—— 那是本链之前的链路（F 收工自动提交 / F 稿发现），
    不是 C8 的对象；C8 的对象是 D 写出来的那一张单与 B 读它的那一侧。
    """
    d = AgentD(st, config={"workspace_root": st.root})
    row = _carried_row(st)
    d._carried_manuscripts = lambda: ([dict(row)] if carried else [], "")
    out = d.write_report()
    return str(out)


def _b(st: Store) -> AgentB:
    sec = Secretary("B", root=st.root, store=st, seam=_Seam(), enable_model=True)
    return conftest.b_form_gate_ok(
        AgentB(st, extractor=None, extract_text=None, config={}, secretary=sec))


def _deps(st: Store, sid: str) -> list[dict]:
    return [dict(r) for r in st.rows("dependencies")
            if str(r.get("used_by") or "").split("#", 1)[0] == f"stmt:{sid}"]


def _row(st: Store, sid: str) -> dict:
    return next(dict(r) for r in st.rows("statements")
                if str(r.get("stmt_id")) == sid)


def _chain(tmp_path: pathlib.Path) -> dict:
    """正常剧本：F 稿 → D 报告（携带单）→ B 只按指针收录。"""
    st = _ws(tmp_path)
    _citable(st)
    _write_manuscript(st)
    conftest.sign_before_registration(st.root, proof_text=PROOF)
    before_statements = len(list(st.rows("statements")))
    report = _d_report(st, carried=True)
    # D 只递指针：B 手上只有携带单里的 `mss:<稿号>`。
    pointer = DS.read_carried_manuscript(st.root, statement_ids=[f"mss:{MID}"])
    got = {}
    if str(pointer.get("path") or ""):
        got = _b(st).ingest_manuscript(manuscript=str(pointer["path"]),
                                       mode="register")
    return {"st": st, "report": report, "pointer": pointer, "got": got,
            "before_statements": before_statements}


def _chain_problems(data: dict) -> list[str]:
    problems: list[str] = []
    st = data["st"]
    pointer = dict(data.get("pointer") or {})
    if str(pointer.get("source") or "") != DS.SOURCE_CARRIED:
        problems.append(f"携带单没有寻址到 F 稿：source={pointer.get('source')!r} "
                        f"why={str(pointer.get('why') or '')[:120]}")
        return problems
    if str(pointer.get("path") or "") != REL:
        problems.append(f"携带单寻址到的路径不是 {REL}：{pointer.get('path')!r}")
    got = dict(data.get("got") or {})
    if got.get("ok") is not True:
        return problems + [f"B 按稿收录没成功：{got.get('refused')!r} "
                           f"{str(got.get('reason') or '')[:120]}"]
    if str(got.get("manuscript_source") or "") != DS.SOURCE_CARRIED:
        problems.append(f"B 的稿来源不是 carried_by_D：{got.get('manuscript_source')!r}")
    sid = str((got.get("target") or {}).get("stmt_id") or "")
    if not sid:
        return problems + [f"回执里没有命题号：{got.get('target')!r}"]
    row = _row(st, sid)
    if str(row.get("statement_full") or "") != PROPOSITION:
        problems.append(f"落库命题不是稿的 `## 命题`：{row.get('statement_full')!r}")
    if str(row.get("manuscript_id") or "") != MID:
        problems.append(f"行上的稿号不是 {MID}：{row.get('manuscript_id')!r}")
    if PR.proof_sha(str(row.get("proof_text") or "")) != PR.proof_sha(PROOF):
        problems.append("落库的证明正文不是稿的 `## 证明`")
    # B 的逐格回执：命题与依赖三列都是从稿里读出来的（不是 D 在参数里抄的）。
    cells = dict(got.get("cells") or {})
    stmt_cell = dict(cells.get("statement_full") or {})
    if str(stmt_cell.get("value") or "") != PROPOSITION:
        problems.append(f"回执的 statement_full 不是稿的 `## 命题`："
                        f"{str(stmt_cell.get('value') or '')[:80]!r}")
    dep_cell = dict(cells.get("dependencies") or {})
    dep_values = [dict(x) for x in (dep_cell.get("value") or [])]
    if len(dep_values) != 1:
        problems.append(f"回执里依赖段不是 1 行：{dep_values}")
    else:
        one = dep_values[0]
        if str(one.get("quote") or "") != "引理：p 阶元的存在性":
            problems.append(f"回执依赖三列的引用不是稿里那一句：{one!r}")
        if str(one.get("stmt_id") or "") != DEP_SID:
            problems.append(f"回执依赖三列的命题号不是 {DEP_SID}：{one!r}")
        if str(one.get("step") or "") != "1":
            problems.append(f"回执依赖三列的步不是 1：{one!r}")
    deps = _deps(st, sid)
    if len(deps) != 1:
        problems.append(f"依赖行不是 1 行：{len(deps)}")
    else:
        one = deps[0]
        if str(one.get("source_stmt_id") or "") != DEP_SID:
            problems.append(f"依赖三列的命题号不是 {DEP_SID}：{one.get('source_stmt_id')!r}")
        if "p 阶元" not in str(one.get("quote") or ""):
            problems.append(f"依赖三列的引用那一格没有读进台账：{one!r}")
        if int(one.get("path_group") or 0) != 1:
            problems.append(f"依赖行的路径号不是 1：{one.get('path_group')!r}")
        if str(one.get("used_by")) != f"stmt:{sid}":
            problems.append(f"依赖 used_by 不是 stmt:{sid}：{one.get('used_by')!r}")
    reading = MP.path_reading(st, st.root, statement_id=sid)
    if int(reading.get("count") or 0) != 1:
        problems.append(f"path_reading.count 不是 1：{reading.get('count')!r}")
    else:
        by_group = {int(p.get("path_group") or 0): p for p in (reading.get("paths") or [])}
        if str((by_group.get(1) or {}).get("manuscript") or "") != REL:
            problems.append(f"第 1 条路径的载体不是 {REL}：{by_group.get(1)!r}")
    return problems


# ============================================================ 主链
def test_the_carried_sheet_lets_b_ingest_the_manuscript(tmp_path: pathlib.Path) -> None:
    """D 写携带单 → B 只按指针寻址 → 按稿收录；终态从台账读。"""
    data = _chain(tmp_path)
    problems = _chain_problems(data)
    assert problems == [], (problems, data.get("got"), data.get("pointer"))
    st = data["st"]
    # D 没动命题台账：B 收录之前仍是夹具那一条引理。
    assert data["before_statements"] == 1, data["before_statements"]
    # B 收录之后多出这一条（计数读数）。
    assert len(list(st.rows("statements"))) == 2, st.rows("statements")


def test_d_only_has_read_access_to_the_statement_ledger(tmp_path: pathlib.Path) -> None:
    """D 的声明面没有 `statements` 写集：只递指针是结构事实，不是这次恰好没写。"""
    spec = specs.builtin_specs()["D"]
    assert "statements" not in set(spec.write_set), sorted(spec.write_set)
    data = _chain(tmp_path)
    assert _chain_problems(data) == [], _chain_problems(data)


# ============================================================ 反真空一：撤掉携带单
def test_without_the_carried_section_the_pointer_resolves_nothing(
        tmp_path: pathlib.Path) -> None:
    """反真空①：D 没写携带单 ⇒ 指针寻址不到任何稿（链断在第一步）。"""
    st = _ws(tmp_path)
    _citable(st)
    _write_manuscript(st)
    conftest.sign_before_registration(st.root, proof_text=PROOF)
    _d_report(st, carried=False)
    pointer = DS.read_carried_manuscript(st.root, statement_ids=[f"mss:{MID}"])
    assert str(pointer.get("source") or "") != DS.SOURCE_CARRIED, pointer
    assert not str(pointer.get("path") or ""), pointer
    assert "携带的证明手稿" in str(pointer.get("why") or ""), pointer


# ============================================================ 反真空二：撤掉 ## 命题
def test_without_the_proposition_section_b_refuses(tmp_path: pathlib.Path) -> None:
    """反真空②：稿没有 `## 命题` ⇒ B 受控拒、零新增（命题确实从稿里读）。"""
    st = _ws(tmp_path)
    _citable(st)
    text = _manuscript().replace("## 命题", "## 起草说明")
    _write_manuscript(st, text)
    conftest.sign_before_registration(st.root, proof_text=PROOF)
    _d_report(st, carried=True)
    pointer = DS.read_carried_manuscript(st.root, statement_ids=[f"mss:{MID}"])
    assert str(pointer.get("source") or "") == DS.SOURCE_CARRIED, pointer
    got = _b(st).ingest_manuscript(manuscript=str(pointer["path"]), mode="register")
    assert got.get("ok") is False, got
    assert str(got.get("refused") or "") == "pointer_manuscript_missing_statement", got
    assert len(list(st.rows("statements"))) == 1, st.rows("statements")


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
