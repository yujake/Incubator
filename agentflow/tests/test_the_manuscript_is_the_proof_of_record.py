# -*- coding: utf-8 -*-
"""亲跑通道暴露的两处（2026-11-09，业主令「亲自扮演各角色接力跑通」）。

## 现场（我在 `temp/_handrun.py` 里逐角色跑，都走真身）

### D14 参数正文与稿只差前后换行 ⇒ 被当成"不是同一份"
`_manuscript_gate` 里 `given = text`、`body = 稿里那一节 .strip("\\n")`，
再拿 `text_sha` 原样比 ⇒ 调用方照 `manuscripts.read` 抄下正文（带前导空行）时
内容完全一样也判 `proof_text_mismatch`。判据的本意是"内容是不是同一份"，
不是"末尾有几个换行"。

### D15 给了正文 ⇒ 台账记了参数那份的 sha，签落不下去
`verify_proof` 改前只在 `not text.strip()` 时才取稿里那一节。于是"给了正文"
那一支把参数的 sha 记进台账（实测 `d2e27457…`），而签块 / 签文件按稿那一节算
（`172e01fb…`）⇒ V 判「成立」、签落不到稿上、B 收录受控拒 `proof_without_v_sign`，
三处读数互相矛盾，而没有任何一处报"签没落"。
稿是正文的权威：内容核对过之后，一律以稿里 `## 证明` 那一节为准。

## 判据
| # | 造什么 | 期望 |
|---|---|---|
| a | 参数正文 = 稿里那一节 + 前后各加空行 | 收；台账 `proof_sha256` == 稿那一节的 sha；稿上有签块 |
| b | 参数正文与稿里那一节内容不同 | 拒 `proof_text_mismatch` |
| c | 反真空：把"以稿为准"换成"参数优先" | a 红（台账 sha 变回参数那份） |
"""

from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import depsection as _DS
from agentflow import proofregistry as _PR
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow.agent_v import AgentV
from agentflow.store import Store

STATEMENT = "设 G 是有限群，p 是整除 |G| 的最小素因子。则 G 的任一 p-Sylow 子群正规。"
PROOF = ("第一步：设 P 是 Sylow p-子群，N = N_G(P)。\n"
         "第二步：由 Sylow 定理，[G : N] 整除 |G|。\n"
         "第三步：[G : N] 的素因子都不小于 p，故与 p 互素。\n"
         "第四步：于是 [G : N] = 1，P 正规。\n")
SID = "000000"


class _Call:
    ok = True
    problem = ""
    detail = ""
    text = ""
    model = "fake"
    prompt_version = "t"
    prompt_sha256 = "0" * 64


class _ReviewSeam:
    wired = True

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)

    def ask(self, prompt: str = "", **_kw) -> _Call:
        call = _Call()
        call.text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return call


class _Seam:
    wired = True

    def __init__(self, answers: dict[str, list] | None = None) -> None:
        self.answers = {k: list(v) for k, v in (answers or {}).items()}

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = "") -> tuple[dict, _Call]:
        kind = note.split(":", 1)[-1]
        queue = self.answers.get(kind) or [{}]
        doc = queue.pop(0) if len(queue) > 1 else queue[0]
        return dict(doc), _Call()


CLEAN_REPLY = json.dumps({"verdict": "成立", "findings": [],
                          "summary": "四步都成立。"}, ensure_ascii=False)


def _axis(answer: str) -> dict:
    return {"checked": True, "decision": answer, "reason": "夹具", "basis": ["夹具"]}


def _ws(tmp_path: pathlib.Path) -> Store:
    from agentflow.tools.conductor_tools import conductor_for

    st = Store(tmp_path / "ws")
    st.init()
    conductor_for(st)
    return st


def _manuscript(st: Store) -> str:
    rel = f"reports/f-proof-{SID}.md"
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# F 的证明手稿\n\n\n## 命题\n\n{STATEMENT}\n\n"
                    f"## 证明\n\n{PROOF}\n\n" + _DS.render_dependency_section([]),
                    encoding="utf-8")
    return rel


def _verify(st: Store, text: str) -> dict:
    sec = SEC.Secretary("V", root=st.root, store=st,
                        seam=_Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                                    "sign_issuance": [_axis(SEC.SIGN_ISSUE)]}),
                        enable_model=True)
    agent = AgentV(st, workspace_root=st.root, llm=_ReviewSeam(CLEAN_REPLY), secretary=sec)
    from agentflow import conductor as _CND

    with _CND.calling_as("t-v", "V", parent_task_id="t-b", parent_role="B"):
        return agent.verify_proof(SID, proof_text=text, proof_manuscript=_manuscript(st))


def _section_sha(st: Store) -> str:
    raw = (pathlib.Path(st.root) / f"reports/f-proof-{SID}.md").read_text(encoding="utf-8")
    return _PR.proof_sha(raw)


def test_a_text_that_differs_only_in_surrounding_newlines_is_the_same_proof(
        tmp_path: pathlib.Path) -> None:
    """a. 参数正文与稿里那一节只差前后空行 ⇒ 收；台账 sha 是稿那一节的 sha。"""
    st = _ws(tmp_path)
    given = "\n\n" + PROOF + "\n\n"          # 内容一样，前后多了空行
    out = _verify(st, given)
    assert out.get("checked") is True, out
    assert out.get("verdict") == "成立", out
    want = _section_sha(st)
    assert str(out.get("proof_sha256") or "") == want, (
        "台账那一行必须记稿里那一节的 sha（签按它算）", out.get("proof_sha256"), want)
    body = (pathlib.Path(st.root) / f"reports/f-proof-{SID}.md").read_text(encoding="utf-8")
    assert "- V 签：" in body, "签必须落到稿上（否则 B 收录会拒）"
    rows, problems = VR.list_verifications(st.root, statement_id=SID, limit=None)
    assert not problems, problems
    assert str(rows[-1].get("proof_sha256") or "") == want, rows[-1]


def test_b_a_text_with_different_content_is_refused(tmp_path: pathlib.Path) -> None:
    """b. 内容不同 ⇒ 拒 `proof_text_mismatch`（这一条不许因为 a 的放宽而松掉）。"""
    st = _ws(tmp_path)
    other = PROOF.replace("P 正规", "P 交换")
    assert other != PROOF
    out = _verify(st, other)
    assert out.get("checked") is False, out
    assert out.get("reason") == "proof_text_mismatch", out


def test_c_forcing_the_parameter_text_back_makes_a_red(tmp_path: pathlib.Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """c. 反真空：把"以稿为准"换回"参数优先" ⇒ a 的主断言（台账 sha == 稿 sha）红。"""
    import agentflow.agent_v.core as _CORE

    real = _CORE.AgentV.verify_proof

    def param_first(self, *a, **kw):  # noqa: ANN001, ANN002, ANN003
        out = real(self, *a, **kw)
        given = str(kw.get("proof_text") or "")
        if out.get("checked") and given.strip():
            out["proof_sha256"] = VR.text_sha(given)   # 旧口径：参数优先
        return out

    monkeypatch.setattr(_CORE.AgentV, "verify_proof", param_first)
    st = _ws(tmp_path)
    given = "\n\n" + PROOF + "\n\n"
    out = _verify(st, given)
    assert str(out.get("proof_sha256") or "") != _section_sha(st), (
        "反真空没打中：把口径换回参数优先之后，台账 sha 仍等于稿 sha")
