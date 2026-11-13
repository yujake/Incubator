# -*- coding: utf-8 -*-
"""手稿产出侧（F）+ 呈递侧退役 `proof_no`：正控 / 老盘兼容 / B 接住 / 反真空。

业主逐字（这一批的总口径，与 `test_v_sign_no_proof_no.py` 同一条）：

```text
「proof_no 确实该退役，因为已经让 B 秘书收录时现看了，手稿产出侧和 V 签侧甚至呈递侧可退役，
  台账不能退役，还要确认 B 秘书确实能接住（也要彩排）。」
```

V 签侧已由 `9484753f` 退役；这一份钉手稿产出侧（F）与呈递侧：

| 面 | 新写不再产生 | 老盘仍读 |
|---|---|---|
| 稿头 | `- 证明号：N`（`manuscriptform.render_proof_manuscript`） | `depsection.manuscript_proof_no` 照旧 |
| 登记条目 | `proof_no` / `versions[].proof_no`（`proofregistry`） | 老 `- 证明号：` / `p<N>@…` 两种格式都读 |
| 稿名 | `-pN` 后缀（新写只按稿号） | 不再认 `…-pN.md`（对齐之后只有一种名字） |
| F 读数 | `_hand_proof` / `step` / `history` 里的 `proof_no` | 老计划台账里的那一格不删 |
| 呈递侧 | 携带行里的 `proof_no`、`mss:` 记号里的 `#proof_no=` | 老记号 / 老携带行照读 |

## 判据（每条都带"它能怎么红"）

| # | 造什么 | 期望 | 它能怎么红 |
|---|---|---|---|
| a | 同一份稿连交两次（改正文） | 稿头没有 `- 证明号：`、登记条目没有 `proof_no`、版本段没有 `pN@`；两次同一路径、盘上一份 | 写侧回潮（谁再写一格 / 谁把 `-pN` 加回）⇒ 红 |
| b | 一份已登记的 F 稿走 D 的携带单；一份 `mss:` 记号 | 携带行没有 `proof_no` 键；记号里没有 `#proof_no=`（老记号照读） | 呈递侧回潮 ⇒ 红 |
| c | F 交卷 → V 未在册签 → B 收录（彩排） | B 认签 `applied=True`；行上 `manuscript_id` / `reviewed` / `grade=pre_theorem` 都对 | B 依赖 `proof_no` 才接得住 ⇒ 红 |
| d | 老稿：`reports/f-proof-000012.md` + 稿头 `- 证明号：2` | 仍能分类、读正文；稿头那一行仍读得出 | 读侧把 `- 证明号：` 删掉 ⇒ 红 |
| e | 反真空：把 `- 证明号：` 加回渲染 / 把 `proof_no` 加回携带行 | a 的读数、b 的读数当场红 | 那两条"没有这一格"只是恒真 ⇒ 红 |

零模型调用（F 的形态闸、V 的审阅、B 的秘书都用预置回复 / 替身）；不读写 `projects/`。
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from agentflow import conductor as CND
from agentflow import depsection as _DS
from agentflow import manuscriptform as MF
from agentflow import proofregistry as R
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.agent_d import AgentD
from agentflow.agent_f import AgentF
from agentflow.agent_v import AgentV
from agentflow.store import Store

from test_one_manuscript_id_is_one_file import _agent, _plan, _submit
from test_v_reviews_three_times_before_signing import CLEAN_REPLY, _ReviewSeam
from test_unregistered_sign_is_the_main_path import _clean_secretary

TS = "2026-11-11T00:00:00+08:00"
SID = "000042"
FULL = "设 G 是 3-正则群；则弦长函数不是常值。"
PROOF = ("1. 取 G = C_n（n ≥ 3）：它是 2-正则、围长为 n。\n"
         "2. 由第 1 步直接得到结论。")
_CLEAN = {"checked": True, "axis": "clean", "decision": "没问题", "reason": "判据：clean"}


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


# ============================================================ a 正控：新写不产生
def _a_problems(root: pathlib.Path, rounds: list[dict]) -> list[str]:
    """a 的机器判据（正控与反真空共用同一份读数，避免两处各说各的）。"""
    problems: list[str] = []
    rows = R.entries_on_disk(root)
    if len(rows) != 1:
        problems.append(f"登记条目不是恰好 1 条：{len(rows)}")
    for one in rounds:
        rel = str(one.get("manuscript_path") or "")
        if not rel:
            problems.append("这一轮没有手稿路径")
            continue
        text = (root / rel).read_text(encoding="utf-8")
        if "- 证明号：" in text:
            problems.append(f"稿头仍写着 `- 证明号：`（{rel}）")
        if re.search(r"(?m)^- 版本：p\d+@", text):
            problems.append(f"版本段仍是 `p<N>@…`（{rel}）")
        entry = R.parse_entry(text)
        if int(entry.get("proof_no") or 0):
            problems.append(f"登记条目读到 proof_no={entry.get('proof_no')!r}（{rel}）")
        if len(entry.get("versions") or []) != 1:
            problems.append(f"版本历史不是恰好 1 条：{entry.get('versions')!r}")
        for version in entry.get("versions") or []:
            if int(version.get("proof_no") or 0):
                problems.append(f"versions[].proof_no 仍是 {version.get('proof_no')!r}")
        if "proof_no" in one:
            problems.append(f"F 的读数里仍有 proof_no={one.get('proof_no')!r}")
    return problems


def test_a_new_manuscripts_carry_no_proof_no_and_stay_in_one_file(
        tmp_path: pathlib.Path) -> None:
    """a：连交两次 ⇒ 没有 `- 证明号：` / `proof_no`；同一路径、盘上一份。"""
    st = _ws(tmp_path)
    f = _agent(st)
    pid = _plan(f)
    rounds = [_submit(f, pid, tag) for tag in ("v1", "v2")]

    paths = [str(r.get("manuscript_path") or "") for r in rounds]
    ids = [str(r.get("manuscript_id") or "") for r in rounds]
    assert len(set(paths)) == 1 and all(paths), ("改正文换了路径", paths)
    assert ids == [ids[0]] * 2, ("改正文不许换稿号", ids)
    assert paths[0] == f"reports/f-proof-{ids[0]}.md", (paths[0], ids[0])
    assert "-p" not in pathlib.PurePosixPath(paths[0]).stem.partition("f-proof-")[2], (
        "新写路径不该带 `-pN`", paths[0])
    files = sorted(p.name for p in (pathlib.Path(st.root) / "reports").glob("f-proof-*.md"))
    assert files == [f"f-proof-{ids[0]}.md"], ("盘上必须恰好一份", files)

    assert _a_problems(pathlib.Path(st.root), rounds) == []


# ============================================================ b 正控：呈递侧
def _b_problems(rows: list[dict]) -> list[str]:
    """b 的机器判据（正控与反真空共用）：携带行里不许有 `proof_no` 键。"""
    problems: list[str] = []
    for one in rows:
        if "proof_no" in one:
            problems.append(f"携带行仍带 proof_no={one.get('proof_no')!r}（{one.get('path')!r}）")
    return problems


def _registered_f(st: Store, mid: str = SID) -> str:
    """落一份 F 的登记条目（不经模型：`gate=None` = 没有形态闸）。"""
    got = R.register_or_rewrite(
        st.root, family="F", label=f"F 攻坚 0001 子目标 S1", proposition=FULL,
        proof_text=PROOF, manuscript_id=mid,
        dependency_rows=[])
    assert got.get("ok") is True, got
    return str(got.get("manuscript_path") or "")


def test_b_the_carried_row_and_the_submission_token_carry_no_proof_no(
        tmp_path: pathlib.Path) -> None:
    """b：D 的携带行没有 `proof_no` 键；`mss:` 记号没有 `#proof_no=`（老记号照读）。"""
    st = _ws(tmp_path)
    rel = _registered_f(st)
    assert rel == f"reports/f-proof-{SID}.md", rel

    rows, _note = AgentD(st)._carried_manuscripts()
    assert len(rows) == 1, rows
    assert rows[0]["manuscript_id"] == SID and rows[0]["path"] == rel, rows[0]
    assert _b_problems(rows) == []

    from agentflow.agent_f import delivery as FD

    fresh = FD.submission_token(
        manuscript_id=SID, path=rel, body_sha="a" * 64, sign_sha="b" * 64,
        file_sha="c" * 64, proof_no=1, statement_id="", at=TS, submitted_at=TS)
    assert "#proof_no=" not in fresh and "proof_no=" not in fresh, fresh
    assert FD.parse_submission(fresh)["manuscript_id"] == SID, fresh
    # 老记号（2026-11-11 之前写的）仍读得出那一格 —— 读能力不删。
    old = f"mss:{SID}#path={rel}#body_sha={'a' * 64}#proof_no=2#at={TS}"
    assert int(FD.parse_submission(old)["proof_no"]) == 2, old
    # 老携带行（第四列有号）仍读得出 —— 同上。
    old_row = {"manuscript_id": SID, "path": rel, "sha256": "d" * 64, "proof_no": 2}
    section = _DS.render_carried_section([old_row])
    parsed = _DS.carried_manuscripts(section)
    assert [int(r["proof_no"]) for r in parsed["rows"]] == [2], parsed


# ============================================================ c B 接住（彩排）
def test_c_b_catches_the_new_manuscript_without_any_proof_no(tmp_path: pathlib.Path) -> None:
    """c：F 交卷 → V 未在册签 → B 收录；行上 `manuscript_id` / `reviewed` / `grade` 都对。

    这一条量的是「B 不靠手稿产出侧 / 呈递侧的 `proof_no` 也能接住」：稿头没有那一行、
    登记条目里没有那一格、也没有 `-pN`；B 只按正文 sha 从 pending 台账认领。
    """
    st = _ws(tmp_path)
    f = AgentF(st, config={"workspace_root": str(st.root)})
    man = f.proof_manuscript(
        {"kind": "proof", "proposition": FULL, "label": "彩排",
         "steps": [{"text": "取 G = C_n。", "cites": []},
                   {"text": "由第 1 步得结论。", "cites": []}]},
        sg={"sid": "S1", "text": FULL}, plan={"plan_id": "0001"},
        manuscript_id=SID)
    assert man.get("ok") is True, man
    rel = str(man.get("path") or "")
    assert rel == f"reports/f-proof-{SID}.md", man
    registered = _registered_f(st, mid=SID)
    assert registered == rel, (registered, rel)

    text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    assert "- 证明号：" not in text, text[:600]
    assert re.search(r"(?m)^- 版本：p\d+@", text) is None, text[:600]
    body = str(_DS.proof_body(text)).strip("\n")

    # ---- V 未在册签：三转干净 + 收方秘书落块 ----
    v = AgentV(st, workspace_root=st.root, llm=_ReviewSeam([CLEAN_REPLY]),
               secretary=_clean_secretary(st))
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001", parent_role="F"):
        signed = v.verify_proof(proof_manuscript=rel)
    assert signed.get("kind") == "proof_unregistered_signed", signed
    assert signed.get("verdict") == "成立", signed
    sha = VR.text_sha(body)
    sign = json.loads(VS.sign_path(st.root, sha).read_text(encoding="utf-8"))
    assert "proof_no" not in sign, sign

    # ---- B 收录：从稿拿签 ----
    b = AgentB(st, extractor=None, extract_text=None)
    got = b.register_statement(
        statement_full=FULL, statement_text=FULL, proof_text=body,
        proof_manuscript=rel, kind="theorem",
        label="彩排命题", origin="own_result", evidence_kind="heuristic",
        quote_verified=None,
        quote_reason="判据：自产证明，没有第二份文本可比对",
        line_range={"label": rel})
    assert got.get("ok") is True, got
    v_sign = dict(got.get("v_sign") or {})
    assert v_sign.get("applied") is True, v_sign

    rows = [dict(r) for r in st.rows("statements")]
    assert len(rows) == 1, rows
    row = rows[0]
    assert str(row.get("manuscript_id") or "") == VS.manuscript_id_of(rel), row
    assert dict(row.get("bits") or {}).get("reviewed") is True, row.get("bits")
    assert str(dict(row.get("bits") or {}).get("grade") or "") == "pre_theorem", row.get("bits")
    # 台账不能退役：B 的 statements 行仍可记它自己的证明号（本判据不要求它消失）。
    assert int(VR.proof_no_of(row) or 0) in (0, 1), row.get("proof_no")


# ============================================================ d 稿头老行仍读
def test_d_an_old_manuscript_header_line_still_reads(tmp_path: pathlib.Path) -> None:
    """d：稿头老行 `- 证明号：2` 仍读得出（只停写、不停读）；名字只有一种形式。"""
    st = _ws(tmp_path)
    rel = "reports/f-proof-000012.md"
    text = ("# F 的证明手稿：老盘的第二份证明\n\n"
            "- 计划：000004 · 子目标：S1\n"
            "- 证明号：2\n\n## 命题\n\n老盘那一份的命题。\n\n"
            "## 证明\n\n" + PROOF + "\n\n" + _DS.render_dependency_section([]))
    target = pathlib.Path(st.root) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")

    from agentflow import manuscriptfamily as MFAM

    reading = MFAM.classify_manuscript(rel)
    assert reading["tier"] == MFAM.TIER_FAMILY, reading
    assert reading["manuscript_id"] == "000012", reading
    # 名字里没有 `-pN` ⇒ 证明号那一格在"名字"这一侧恒 1；老稿头那一行是另一处读数。
    assert int(reading["proof_no"] or 0) == 1, reading
    assert MFAM.sign_carrier(rel)["ok"] is True, MFAM.sign_carrier(rel)

    # 读正文：`## 证明` 那一节照旧（与 V 签同一把尺）。
    proof = _DS.read_proof_body(st.root, rel)
    body = str(proof.get("body") or "").strip("\n")
    assert proof.get("state") == _DS.PROOF_PRESENT and body == PROOF, proof

    # 稿头那一行读得出（读能力不删）。
    assert int(R.parse_entry(text)["proof_no"]) == 2
    assert int(_DS.manuscript_proof_no(text)) == 2


# ============================================================ e 反真空
def test_e_putting_the_retired_cells_back_turns_a_and_b_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e：把 `- 证明号：` 加回渲染 / 把 `proof_no` 加回携带行 ⇒ a、b 当场红。"""
    # ---- ① 渲染回潮 ----
    real = MF.render_proof_manuscript

    def _with_the_retired_line(*args, **kwargs):  # noqa: ANN002, ANN003 - 打桩
        out = real(*args, **kwargs)
        lines = out.split("\n")
        at = next(i for i, line in enumerate(lines) if line.startswith("# "))
        lines.insert(at + 1, "- 证明号：1")   # 改前的页头（业主 2026-11-11 已作废）
        return "\n".join(lines)

    monkeypatch.setattr(MF, "render_proof_manuscript", _with_the_retired_line)
    st = _ws(tmp_path)
    f = _agent(st)
    pid = _plan(f)
    rounds = [_submit(f, pid, "v1")]
    problems = _a_problems(pathlib.Path(st.root), rounds)
    assert any("证明号" in one for one in problems), (
        "把 `- 证明号：` 加回渲染之后 a 仍然全绿 ⇒ 「没有这一格」是恒真", problems)

    # ---- ② 呈递侧回潮 ----
    monkeypatch.undo()
    st2 = _ws(tmp_path)
    rel = _registered_f(st2)
    rows, _note = AgentD(st2)._carried_manuscripts()
    assert _b_problems(rows) == []
    injected = [{**dict(one), "proof_no": 1} for one in rows]
    problems_b = _b_problems(injected)
    assert problems_b, (
        "把 `proof_no` 加回携带行之后 b 仍然全绿 ⇒ 那一条判据是恒真")
