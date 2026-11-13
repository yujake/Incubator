# -*- coding: utf-8 -*-
"""彩排判据 C6：同一命题的第二 / 第三份稿 —— B 按语义二态收成第 N 条路径或拒收。

## 业主口径（逐字）

> 「先录入的那份稿子 B 秘书执行了注册命题号并录入，后录入的稿子 B 秘书识别到是同一命题，
>   在对比证明方法后发现几乎一致，于是不收录；另一种情况：对比证明方法后发现有很大差别
>   （语义判别，千万别做任何机械闸，结论是二态的：一致/不同），于是注册了该命题号下的
>   第 2 路径，录入了该稿。」

## 这一条链钉的五段

| 段 | 造什么 | 终态读数（台账 + 盘上） |
|---|---|---|
| a | 第 1 份稿（`mode=register`） | 命题拿到号；证明清单 `[1]`；依赖行 `used_by=stmt:<号>`（不带 `#p1`）；`verifications` 第 1 号；`path_reading=1` |
| b | 第 2 份稿：同一命题、证法与第 1 条路径语义一致 | 拒收 `proof_same_kind`，点名「第 1 条路径」；四处计数仍是 1（证明清单 / 依赖组 / 路径读数 / `statements` 行） |
| c | 第 3 份稿：同一命题、证法语义不同 | 收为第 2 条路径：`path_group=2`；依赖行 `used_by=stmt:<号>#p2`；`verifications` 第 2 号；证明清单 `[1, 2]` |
| d | 第 4 份稿：与第 2 条路径语义一致 | 拒收，点名「第 2 条路径」；路径数仍是 2 |
| e | 反真空：缝恒 `same` / 恒 `different` | 恒 `same` ⇒ c 必红；恒 `different` ⇒ b 必红 |

## 二态从哪里来（桩，不是机械闸）

`_Seam.ask_json` 只读正文里写明的「证法编号：<X>」查剧本表：
`A1/A1 ⇒ same`、`A1/B1 ⇒ different`、`B1/B1 ⇒ same`。它不做任何相似度、长度、
关键词命中计算 —— 判据里的 `same` / `different` 只可能来自这张剧本。

## 计数读数（第三条要求）

`statements` 行数（被引引理 + 这一条命题 = 2）、`dependencies` 行数（每条路径一行）、
`manuscriptpaths` 的 `path_reading.count`。没有模型花费可读（判定面是替身），
所以这一条链的账是计数。

## 不做什么

- 不测命题形态闸（C5 的对象；这里用 `conftest.b_form_gate_ok` 把那一格钉成放行）；
- 不新增动作、不改产品代码；不跑全量。
"""
from __future__ import annotations

import json
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
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.secretary import Secretary  # noqa: E402
from agentflow.store import Store  # noqa: E402

#: 被引的那条在册命题（手稿依赖段的引用门槛：`pre_theorem` 及以上）。
DEP_SID = "000000"
#: 四份稿的 `## 命题` 逐字相同（语义二态判的是证明，不是命题）。
PROPOSITION = "设 G 是有限群，p 是素数；若 p^a 整除 |G|，则 G 存在 p^a 阶子群。"

#: 第 1 / 2 份稿：同一套类方程证法（A1）；第 3 / 4 份：归纳写法（B1）。
P1 = ("证明（类方程）：让 G 以共轭作用作用在它的 p-子群族上，写出类方程；每个轨道长"
      "写成正规化子指数，用强归纳说明只有一个共轭类，故个数模 p 余 1。"
      "\n〔证法编号：A1〕\n引 stmt:000000。")
P2 = ("证明（换一套写法）：合 G 作用在 Sylow 子群集合上，考虑中心与各共轭轨道的分解式，"
      "把每一项写成 |G|/|N_G(Q)|，选一个 Q 使之为 p-自由，再对群的阶递降。"
      "\n〔证法编号：A1〕\n引 stmt:000000。")
P3 = ("证明（归纳路线）：对 |G| 作强归纳；取中心，若中心含 p 元就与商群的归纳假设拼起来，"
      "否则每个共轭轨道长都被 p 整除，再对商群用归纳假设并提升回 G。"
      "\n〔证法编号：B1〕\n引 stmt:000000。")
P4 = ("证明（另一种归纳写法）：考察满足 x^{p^k}=1 的元素个数，用群在自身的左乘作用计数；"
      "设 N 是阶为 p^a 的子群，把它的作用写成不动点计数，递推得到阶为 p 的元素。"
      "\n〔证法编号：B1〕\n引 stmt:000000。")

REL1 = "reports/f-proof-000101.md"
REL2 = "reports/f-proof-000102.md"
REL3 = "reports/f-proof-000103.md"
REL4 = "reports/f-proof-000104.md"


# ============================================================ 假缝
def _tag(text: str) -> str:
    for raw in str(text or "").splitlines():
        line = raw.strip().strip("〔〕")
        if "证法编号：" in line:
            return line.split("证法编号：", 1)[1].strip()
    return ""


def _material(prompt: str) -> dict:
    text = str(prompt or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}


SCRIPT: dict[frozenset[str], str] = {
    frozenset({"A1", "A1"}): "same",
    frozenset({"A1", "B1"}): "different",
    frozenset({"B1", "B1"}): "same",
}


class _Seam:
    """秘书判定面的替身（只实现 `ask_json`）。`mode` 是反真空的两根桩。"""

    class _Call:
        ok = True
        problem = ""
        detail = ""
        text = ""
        model = "fake"
        prompt_version = "t"
        prompt_sha256 = "0" * 64

    def __init__(self, *, mode: str = "normal"):
        self.mode = str(mode)
        self.calls: list[str] = []
        self.kind_calls: list[dict] = []

    def ask_json(self, prompt, **kw):
        note = str(kw.get("note") or "")
        self.calls.append(note)
        data = _material(prompt)
        if note.endswith("statement_keywords"):
            return ({"keywords": ["子群", "Sylow", "共轭", "p 阶元"],
                     "why": "打桩：这几个数学词能把同一条命题捞出来"}, self._Call())
        if note.endswith("proof_kind"):
            got = self._proof_kind(data)
            if got is None:
                return None, self._Call()
            return got, self._Call()
        return self._identity(data), self._Call()

    def _identity(self, data: dict) -> dict:
        full = str(data.get("statement_full") or "")
        candidates = [c for c in (data.get("candidates") or []) if isinstance(c, dict)]
        hit = next((c for c in candidates
                    if str(c.get("statement_full") or "") == full), None)
        label = str(data.get("label") or "Sylow 存在性引理")
        if hit is None:
            return {"decision": "different", "canonical_name": label,
                    "same_as": "", "route": "", "condition": "打桩：条件未读",
                    "conclusion": "打桩：结论未读",
                    "reason": "打桩：在册没有逐字同一条命题", "basis": ["打桩"]}
        return {"decision": "same", "same_as": str(hit.get("stmt_id") or ""),
                "canonical_name": label, "route": "", "condition": "打桩：条件一致",
                "conclusion": "打桩：结论一致", "reason": "打桩：逐字同一条命题",
                "basis": ["打桩"]}

    def _proof_kind(self, data: dict) -> dict | None:
        if self.mode in ("always-same", "always-different"):
            word = "same" if self.mode == "always-same" else "different"
            self.kind_calls.append({"mode": self.mode, "decision": word})
            return {"decision": word, "same_path": 1 if word == "same" else 0,
                    "reason": f"打桩：恒判 {word}"}
        new = _new_text(data)
        known = _known_texts(data)
        if not _tag(new) or not known:
            return None
        new_tag = _tag(new)
        for one in known:
            other = _tag(one.get("text"))
            if not other:
                continue
            word = SCRIPT.get(frozenset({new_tag, other}), "different")
            self.kind_calls.append({"new": new_tag,
                                    "path": int(one.get("path_group") or 0),
                                    "other": other, "decision": word})
            if word == "same":
                return {"decision": "same",
                        "same_path": int(one.get("path_group") or 0),
                        "reason": f"剧本：{new_tag} 与第 {int(one.get('path_group') or 0)} "
                                  f"条路径（{other}）是同一套证法"}
        self.kind_calls.append({"new": new_tag, "path": 0, "other": "",
                                "decision": "different"})
        return {"decision": "different", "same_path": 0,
                "reason": f"剧本：{new_tag} 与在册各路径的证法都不同"}


def _new_text(data: dict) -> str:
    for key in ("proof_text", "proof", "new_proof", "body", "text"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val
        if isinstance(val, dict) and str(val.get("text") or "").strip():
            return str(val.get("text") or "")
    return ""


def _known_texts(data: dict) -> list[dict]:
    for key in ("proofs", "known", "paths", "existing", "candidates"):
        raw = data.get(key)
        if not isinstance(raw, (list, tuple)) or not raw:
            continue
        out: list[dict] = []
        for i, item in enumerate(raw, 1):
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("proof_text") or "")
                no = int(item.get("path_group") or item.get("proof_no") or i)
                if text:
                    out.append({"text": text, "path_group": no})
        if out:
            return out
    return []


# ============================================================ 工作区 / 读数
def _ws(base: pathlib.Path) -> Store:
    st = Store(base / "ws")
    st.init()
    return st


def _agent(st: Store, seam: _Seam) -> AgentB:
    sec = Secretary("B", root=st.root, store=st, seam=seam, enable_model=True)
    return conftest.b_form_gate_ok(
        AgentB(st, extractor=None, extract_text=None, config={}, secretary=sec))


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


def _manuscript(sid: str, proof: str) -> str:
    deps = ("| 引用 | 命题号 | 步 |\n|---|---|---|\n"
            f"| 引理：p 阶元的存在性 | stmt:{DEP_SID} | 1 |\n")
    head = ("# F 的证明手稿\n\n" + (f"" if sid else "")
            + f"- 命题键：{PROPOSITION}\n")
    return (head + "\n## 命题\n\n" + PROPOSITION + "\n\n## 证明\n\n" + proof
            + "\n\n## 依赖\n\n" + deps)


def _write(st: Store, rel: str, text: str) -> pathlib.Path:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _row(st: Store, sid: str) -> dict:
    return next(dict(r) for r in st.rows("statements")
                if str(r.get("stmt_id")) == sid)


def _proof_nos(st: Store, sid: str) -> list[int]:
    return [int(no) for no, _t in VR.proof_list(_row(st, sid))]


def _deps(st: Store, sid: str) -> list[dict]:
    return [dict(r) for r in st.rows("dependencies")
            if str(r.get("used_by") or "").split("#", 1)[0] == f"stmt:{sid}"]


def _dep_groups(st: Store, sid: str) -> list[int]:
    return sorted({int(d.get("path_group") or 0) for d in _deps(st, sid)})


def _path_count(st: Store, sid: str) -> int:
    return int(MP.path_reading(st, st.root, statement_id=sid)["count"])


def _ver_groups(st: Store, sid: str, text: str) -> list[int]:
    rows, bad = VR.list_verifications(st.root, statement_id=sid, limit=None)
    assert bad == [], bad
    sha = PR.proof_sha(text)
    return [int(r.get("path_group") or 0) for r in rows
            if str(r.get("proof_sha256") or "") == sha]


def _sign(st: Store, sid: str, rel: str, proof: str) -> None:
    conftest.sign_for_the_gate(st.root, statement_id=sid, proof_text=proof,
                               proof_no=1, store=st, manuscript=rel)


def _deliver_register(st: Store, b: AgentB, rel: str, proof: str) -> dict:
    _write(st, rel, _manuscript("", proof))
    conftest.sign_before_registration(st.root, proof_text=proof)
    return b.ingest_manuscript(manuscript=rel, mode="register")


def _deliver_apply(st: Store, b: AgentB, sid: str, rel: str, proof: str) -> dict:
    _write(st, rel, _manuscript(sid, proof))
    _sign(st, sid, rel, proof)
    return b.ingest_manuscript(manuscript=rel, target_stmt_id=sid,
                               cells=["proof_text", "dependencies"], mode="apply")


def _first_path_problems(st: Store, got: dict) -> list[str]:
    problems: list[str] = []
    if got.get("ok") is not True:
        return [f"第 1 份稿没收录：{got.get('refused')!r} "
                f"{str(got.get('reason') or '')[:120]}"]
    sid = str((got.get("target") or {}).get("stmt_id") or "")
    if not sid:
        return [f"回执里没有命题号：{got.get('target')!r}"]
    if _proof_nos(st, sid) != [1]:
        problems.append(f"证明清单不是 [1]：{_proof_nos(st, sid)}")
    if _dep_groups(st, sid) != [1]:
        problems.append(f"依赖路径组不是 [1]：{_dep_groups(st, sid)}")
    if {str(d.get("used_by")) for d in _deps(st, sid)} != {f"stmt:{sid}"}:
        problems.append(f"第 1 条路径的 used_by 不是 stmt:{sid}："
                        f"{[d.get('used_by') for d in _deps(st, sid)]}")
    if set(_ver_groups(st, sid, P1)) != {1}:
        problems.append(f"verifications 不是第 1 号：{_ver_groups(st, sid, P1)}")
    if _path_count(st, sid) != 1:
        problems.append(f"path_reading.count 不是 1：{_path_count(st, sid)}")
    return problems


def _refusal_problems(got: dict, *, path_no: int) -> list[str]:
    problems: list[str] = []
    if got.get("ok") is not False:
        problems.append(f"这一份稿被照收了（ok={got.get('ok')!r}）")
        return problems
    code = str(got.get("refused") or got.get("kind") or "")
    if code != "proof_same_kind":
        problems.append(f"拒收码不是 proof_same_kind：{code!r} / "
                        f"{str(got.get('reason') or '')[:120]}")
    why = str(got.get("reason") or got.get("error") or "")
    if f"第 {path_no}" not in why:
        problems.append(f"拒信没点名第 {path_no} 条路径：{why[:140]!r}")
    for word in ("同种", "路径"):
        if word not in why:
            problems.append(f"拒信里没有「{word}」：{why[:140]!r}")
    return problems


def _rehearse(base: pathlib.Path, *, mode: str = "normal") -> dict:
    st = _ws(base)
    _citable(st)
    seam = _Seam(mode=mode)
    b = _agent(st, seam)
    out: dict = {"st": st, "seam": seam, "problems": {k: [] for k in "abcd"}}

    got_a = _deliver_register(st, b, REL1, P1)
    out["a"] = got_a
    out["problems"]["a"] = _first_path_problems(st, got_a)
    sid = str((got_a.get("target") or {}).get("stmt_id") or "")
    out["sid"] = sid
    if not sid or out["problems"]["a"]:
        return out

    got_b = _deliver_apply(st, b, sid, REL2, P2)
    out["b"] = got_b
    out["problems"]["b"] = _refusal_problems(got_b, path_no=1)
    if _proof_nos(st, sid) != [1]:
        out["problems"]["b"].append(f"证明清单变成了 {_proof_nos(st, sid)}（应 [1]）")
    if _dep_groups(st, sid) != [1]:
        out["problems"]["b"].append(f"依赖路径组变成了 {_dep_groups(st, sid)}（应 [1]）")
    if _path_count(st, sid) != 1:
        out["problems"]["b"].append(f"path_reading.count={_path_count(st, sid)}（应 1）")

    got_c = _deliver_apply(st, b, sid, REL3, P3)
    out["c"] = got_c
    if got_c.get("ok") is not True:
        out["problems"]["c"].append(f"第 3 份稿没收录：{got_c.get('refused')!r} "
                                    f"{str(got_c.get('reason') or '')[:120]}")
    else:
        pg = got_c.get("path_group")
        pg = int((pg or {}).get("path_group") or 0) if isinstance(pg, dict) else int(pg or 0)
        if pg != 2:
            out["problems"]["c"].append(f"第 3 份稿的 path_group 不是 2：{pg!r}")
        if _proof_nos(st, sid) != [1, 2]:
            out["problems"]["c"].append(f"证明清单不是 [1, 2]：{_proof_nos(st, sid)}")
        if _dep_groups(st, sid) != [1, 2]:
            out["problems"]["c"].append(f"依赖路径组不是 [1, 2]：{_dep_groups(st, sid)}")
        used = {str(d.get("used_by")) for d in _deps(st, sid)}
        if used != {f"stmt:{sid}", f"stmt:{sid}#p2"}:
            out["problems"]["c"].append(f"依赖 used_by 不是 {{stmt:{sid}, stmt:{sid}#p2}}："
                                        f"{sorted(used)}")
        if set(_ver_groups(st, sid, P1)) != {1}:
            out["problems"]["c"].append(f"第 1 条路径的 verifications 不是第 1 号："
                                        f"{_ver_groups(st, sid, P1)}")
        if set(_ver_groups(st, sid, P3)) != {2}:
            out["problems"]["c"].append(f"第 2 条路径的 verifications 不是第 2 号："
                                        f"{_ver_groups(st, sid, P3)}")
        if _path_count(st, sid) != 2:
            out["problems"]["c"].append(f"path_reading.count={_path_count(st, sid)}（应 2）")

    got_d = _deliver_apply(st, b, sid, REL4, P4)
    out["d"] = got_d
    out["problems"]["d"] = _refusal_problems(got_d, path_no=2)
    if _proof_nos(st, sid) != [1, 2]:
        out["problems"]["d"].append(f"证明清单变成了 {_proof_nos(st, sid)}（应 [1, 2]）")
    if _path_count(st, sid) != 2:
        out["problems"]["d"].append(f"path_reading.count={_path_count(st, sid)}（应 2）")
    return out


# ============================================================ a：第 1 条路径
def test_a_the_first_manuscript_registers_path_one(tmp_path: pathlib.Path) -> None:
    """a：第 1 份稿登记成功，第 1 条路径的四处读数一起成立。"""
    st = _ws(tmp_path)
    _citable(st)
    got = _deliver_register(st, _agent(st, _Seam()), REL1, P1)
    problems = _first_path_problems(st, got)
    assert problems == [], (problems, got)
    sid = str(got["target"]["stmt_id"])
    # 计数读数：一条命题 + 一条被引引理；依赖一行。
    assert len(list(st.rows("statements"))) == 2, st.rows("statements")
    assert len(_deps(st, sid)) == 1, _deps(st, sid)


# ============================================================ b：同种 ⇒ 拒
def test_b_the_second_manuscript_is_refused_as_same_kind(tmp_path: pathlib.Path) -> None:
    """b：第 2 份稿的证法与第 1 条路径同种 ⇒ 拒收并点名第 1 条路径，计数不动。"""
    got = _rehearse(tmp_path)
    assert got["problems"]["a"] == [], got["problems"]["a"]
    assert got["problems"]["b"] == [], (got["problems"]["b"], got.get("b"))


# ============================================================ c：不同种 ⇒ 第 2 条
def test_c_the_third_manuscript_becomes_path_two(tmp_path: pathlib.Path) -> None:
    """c：第 3 份稿的证法不同 ⇒ 收为第 2 条路径（`#p2` + verifications 第 2 号）。"""
    got = _rehearse(tmp_path)
    assert got["problems"]["a"] == [] and got["problems"]["b"] == [], got["problems"]
    assert got["problems"]["c"] == [], (got["problems"]["c"], got.get("c"))
    st = got["st"]
    sid = got["sid"]
    assert _proof_nos(st, sid) == [1, 2], _proof_nos(st, sid)
    assert len(list(st.rows("statements"))) == 2, st.rows("statements")


# ============================================================ d：与第 2 条同种 ⇒ 拒
def test_d_the_fourth_manuscript_is_refused_against_path_two(
        tmp_path: pathlib.Path) -> None:
    """d：第 4 份稿与第 2 条路径同种 ⇒ 拒收并点名第 2 条路径；路径数仍是 2。"""
    got = _rehearse(tmp_path)
    assert got["problems"]["d"] == [], (got["problems"]["d"], got.get("d"))
    assert _path_count(got["st"], got["sid"]) == 2, _path_count(got["st"], got["sid"])


# ============================================================ e：反真空
def test_e_always_same_makes_the_second_path_red(tmp_path: pathlib.Path) -> None:
    """e1（反真空）：缝恒回 `same` ⇒ c 的第 2 条路径必须红。"""
    got = _rehearse(tmp_path, mode="always-same")
    assert got["problems"]["c"], (
        "缝恒判 same 之后第 3 份稿仍然落成第 2 条路径 ⇒ c 的第 2 条路径没有对象")
    assert any("没收录" in p or "path_group" in p or "证明清单" in p or "依赖路径组" in p
               for p in got["problems"]["c"]), got["problems"]["c"]


def test_e2_always_different_makes_the_refusal_red(tmp_path: pathlib.Path) -> None:
    """e2（反真空）：缝恒回 `different` ⇒ b 的拒收必须红（谁来都收）。"""
    got = _rehearse(tmp_path, mode="always-different")
    assert got["problems"]["b"], (
        "缝恒判 different 之后 b 仍然被拒 ⇒ b 的拒收没有对象（拒的不是「同种」）")
    assert any("照收" in p or "proof_same_kind" in p for p in got["problems"]["b"]), (
        got["problems"]["b"])


def test_f_the_seam_was_really_asked_about_the_pairs(tmp_path: pathlib.Path) -> None:
    """缝面读数：三次证法判定各按剧本问了一对（A1/A1、A1/B1、B1/B1）。"""
    got = _rehearse(tmp_path)
    calls = [c for c in got["seam"].kind_calls if c.get("other")]
    seen = {(c["new"], c["other"], c["decision"]) for c in calls}
    assert ("A1", "A1", "same") in seen, (calls, seen)
    assert ("B1", "A1", "different") in seen, (calls, seen)
    assert ("B1", "B1", "same") in seen, (calls, seen)


pytestmark = pytest.mark.usefixtures("signed_v_handoffs")


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
