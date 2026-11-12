# -*- coding: utf-8 -*-
"""彩排判据：两份 F 稿独立交来同一条命题的证明，B 秘书按「语义同种 / 不同种」收与不收。

## 业主给的原场景（逐字）

    需要彩排：两个 F 分别独立交了关于某个命题的证明，先录入的那份稿子 B 秘书执行了
    注册命题号并录入，后录入的稿子 B 秘书识别到是同一命题，在对比证明方法后发现几乎
    一致，于是不收录；另一种情况：对比证明方法后发现有很大差别（语义判别，千万别做
    任何机械闸，结论是二态的：一致/不同），于是注册了该命题号下的第 2 路径，录入了
    该稿。之后又出现了对该命题的证明，B 秘书比对后发现和第二路径证明几乎一致，拒收。
    录入结束后，B 分别将路径 1 的证明和路径 2 的证明分别优化，拿签，回填。

## 这一份按顺序钉的五段（每段都能单独红）

| 段 | 造什么 | 期望（本判据认定"成功"的那一格） |
|---|---|---|
| a | 第 1 份稿（`f-proof` 族，`mode=register`） | 命题拿到号（`target.stmt_id`）、稿在盘上、`path_group=1`、依赖落表且是第 1 条路径 |
| b | 第 2 份稿：同一命题、证法与第 1 条路径语义一致 | 拒收：`proof_same_kind`，点名"与第 1 条路径同种"；盘上不多出第二条路径（路径数、证明清单、依赖组、`path_reading.count` 四处一起数） |
| c | 第 3 份稿：同一命题、证法语义不同（类方程 vs 归纳构造） | 收录为 `path_group=2`：两份稿各自可读，命题下共 2 条路径 |
| d | 第 4 份稿：与第 2 条路径语义一致 | 拒收，点名"与第 2 条路径同种"；路径数仍是 2 |
| e | 收尾：B 分别对路径 1 / 路径 2 的证明做优化 → 拿 V 签 → 回填 | 两条路径各自留下"签 + 回填"的读数（见 :func:`_e_readings`） |

## "语义一致 / 不同"从哪来（判据内桩，不是机械闸）

两轴都由秘书那一次判定给（`Secretary.judge` 经 `seam.ask_json`）。本文件给秘书装的是
:class:`_Seam`——一张剧本表，按每份证明正文里写明的「证法编号」查二态结论：

- 第 2 份稿与第 1 条路径同为 `A1` ⇒ `same`；
- 第 3 份稿是 `B1`，与第 1 条路径（`A1`）⇒ `different`；
- 第 4 份稿与第 2 条路径同为 `B1` ⇒ `same`。

桩不做任何相似度 / 长度 / 关键词命中计算：它只读 `证法编号：<X>` 这一行去查表（见
:meth:`_Seam._proof_kind`）。判据里的 `same` / `different` 因此只可能来自这个剧本。

## 反真空（五条，证明上面的绿不是恒真）

1. `always-different`：桩恒回 `different` ⇒ b、d 的拒收断言必须红；
2. `always-same`：桩恒回 `same` ⇒ c 的第 2 条路径必须红；
3. `normal`（默认剧本）⇒ 五段全绿；
4. 逐路径解析打桩成"永远 canonical" ⇒ e 的第一条（两条路径各一份改写稿）必红；
5. 关掉 replace（`AgentB._optimization_replace_enabled()` 恒 False）⇒ 回填 2
   必撞 `proof_no_taken`（"能换第 N 份"是 C4 新加的、不是恒真）。

## 与机械闸的关系（读数，不是判据）

业主口径：「千万别做任何机械闸」。旧实现用 `propositionkey.same_kind_proof` 的
Jaccard 阈值（`PROOF_SAME_JACCARD = 0.80`）判"同种"。本文件的 b 刻意让语义与阈值
相反：第 2 份稿与第 1 条路径语义相同（同一套类方程论证，只是换了一套措辞与记号），
机械读数 `different`；而拒收必须发生。于是"这次拒收来自阈值"这条解释当场被排除 ——
拒收只能来自秘书的二态结论。阈值读数仍可以留在回执里给人看（本判据不禁止它出现），
但它一个字节都不能决定收不收。c 的机械读数恰好也是 `different`（与结局同向），所以
c 的绿不能单独证明"语义判别在起作用"；那一半由 `always-same` 的反真空
（:func:`test_always_same_makes_the_second_path_red`）与缝面读数
（:func:`test_the_seam_was_really_asked_about_the_two_proofs`）钉住。

## 位置（2026-11-12 收口：已搬回 `tests/`）

本文件在 `agentflow/tests/` 下，与 `tests/conftest.py` 同一棵树（归档处的夹具桥已不再
需要，也没有搬进来：`tests/conftest.py` 是唯一真身）。文件头仍按"往上找
`pyproject.toml` + `tests/conftest.py`"定位工作区根。

跑法：`cd agentflow && python -B -m pytest tests/test_rehearsal_two_f_independent_proofs.py -q`
（读数：11 passed —— a–e 五段 + 整场 + 五条反真空）。

## 边界

全部 tmp 工作区、零真实模型调用（V 的签走 conftest 的真写口）；不读写 `projects/`。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest


def _agentflow_root() -> pathlib.Path:
    """往上找 `pyproject.toml` + `tests/conftest.py` 都在的那一层（归档处与 tests/ 通用）。"""
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        if ((parent / "pyproject.toml").is_file()
                and (parent / "tests" / "conftest.py").is_file()):
            return parent
    raise RuntimeError(f"找不到 agentflow 根（从 {here} 往上没有 pyproject.toml + tests/conftest.py）")


_ROOT = _agentflow_root()
_SRC = _ROOT / "src"
_TESTS = _ROOT / "tests"
for _path in (_SRC, _TESTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import conftest  # noqa: E402

from agentflow import depsection as DS  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import manuscriptsubmission as MS  # noqa: E402
from agentflow import proofregistry as PR  # noqa: E402
from agentflow import propositionkey as PK  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.secretary import Secretary  # noqa: E402
from agentflow.store import Store  # noqa: E402

#: 被引的那条在册命题（手稿依赖段的引用门槛：`pre_theorem` 及以上）。
DEP_SID = "000000"
#: 这条命题（四份稿的 `## 命题` 逐字相同）。
PROPOSITION = "设 G 是有限群，p 是素数；若 p^a 整除 |G|，则 G 存在 p^a 阶子群。"

# ---- 第 1 份稿：类方程 / 共轭作用（证法编号 A1） -------------------------------
P1 = ("证明（类方程）：让 G 以共轭作用作用在它的 p-子群族上，写出类方程：|G| 等于中心项"
      "加上若干轨道长之和。每个轨道长都写成正规化子指数的形式；取极大 p-子群 P，比较 "
      "|P| 与正规化子的阶的 p-部分，用强归纳说明只有一个共轭类，于是轨道大小就是指数，"
      "故个数模 p 余 1。\n〔证法编号：A1〕\n引 stmt:000000。")
# ---- 第 2 份稿：同一个证法（类方程 / 共轭作用），换一套措辞与记号 --------------
# 它与 P1 的 Jaccard 读数刻意压到阈值以下（见 `test_b_...` 的读数断言）。
P2 = ("证明（换一套写法）：合 G 作用在 Sylow 子群集合上。考虑 G 的中心与各共轭轨道的"
      "分解式，把每一项写成 |G|/|N_G(Q)| 的样子。选一个 Q 使之为 p-自由，用正规化子阶"
      "与群阶的 p 部分相除的整除关系，对群的阶做递降，递降到中心时只剩一个轨道，其余项"
      "都被 p 整除，于是计数同余于 1 成立。\n〔证法编号：A1〕\n引 stmt:000000。")
# ---- 第 3 份稿：归纳构造（证法编号 B1） --------------------------------------
# 它与 P1 的措辞刻意不同（归纳 vs 类方程），机械读数判 `different` —— 所以 c 的绿本身
# 不构成"语义判别"的证据；那一半由 `always-same` 的反真空与缝面读数钉住。
P3 = ("证明（归纳路线）：对 |G| 作强归纳。取 G 的中心，若中心含 p 元则把中心的这个 p 元"
      "与商群的归纳假设拼起来；否则 G 的每个共轭轨道长都被 p 整除。对商群用归纳假设得到 "
      "p 阶元，再把它提升回 G，用轨道长除以正规化子指数得到 p-部分，故个数模 p 余 1。"
      "\n〔证法编号：B1〕\n引 stmt:000000。")
# ---- 第 4 份稿：归纳构造（与第 2 条路径同种），措辞又与 P3 不同 ----------------
P4 = ("证明（另一种归纳写法）：考察满足 x^{p^k}=1 的元素个数，用群在自身的左乘作用计数。"
      "设 N 是阶为 p^a 的子群，把它在子集族上的作用写成不动点计数；不动点集恰好是落在 N "
      "里的元素，所以计数同余于 |S| 的 p 部分，递推得到阶为 p 的元素。\n〔证法编号：B1〕"
      "\n引 stmt:000000。")

#: 四份稿的路径（`f-proof` 族；产出侧一个稿号 = 一份文件 = 一份证明）。
REL1 = "reports/f-proof-000101.md"
REL2 = "reports/f-proof-000102.md"
REL3 = "reports/f-proof-000103.md"
REL4 = "reports/f-proof-000104.md"

#: e 的两份优化稿（各取所长的压缩表述；签盖的是正文，正文换了就要重签）。
#: 优化稿刻意不带 `stmt:` 引用：B 的改写载体（`land_manuscript`）会核"正文引用集合 vs
#: `## 依赖` 表"，那是改写那一层的判据，本段不测它（依赖面已在 a / c 落过了）。
OPT1 = P1.replace("\n引 stmt:000000。", "\n（优化：中心项与轨道长合并成一句。）")
OPT2 = P3.replace("\n引 stmt:000000。", "\n（优化：两支归纳合并成一步。）")


# ============================================================ 假 secret 的缝

def _tag(text: str) -> str:
    """读出一份正文写明的「证法编号」（剧本的键；不是相似度）。"""
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


#: 剧本：证法编号对 ⇒ 二态结论。业主的场景只有这三对。
SCRIPT: dict[frozenset[str], str] = {
    frozenset({"A1", "A1"}): "same",     # 第 2 份稿 vs 第 1 条路径
    frozenset({"A1", "B1"}): "different",  # 第 3 份稿 vs 第 1 条路径
    frozenset({"B1", "B1"}): "same",     # 第 4 份稿 vs 第 2 条路径
}


class _Seam:
    """秘书那一格的假模型缝（只实现 `Secretary.judge` 用到的 `ask_json`）。

    `mode`：`normal` 按剧本判；`always-same` / `always-different` 是反真空的两根桩；
    `off` 复现"没查成"那一档。

    两条判据（`proposition_identity` / `proof_kind`）共用这一个缝：前者看正文是否逐字
    相同（剧本：四份稿的命题正文逐字一样 ⇒ 同一条），后者只查 :data:`SCRIPT`。
    """

    class _Call:
        def __init__(self, ok: bool = True, problem: str = "", detail: str = ""):
            self.ok, self.problem, self.detail = ok, problem, detail

    def __init__(self, *, mode: str = "normal"):
        self.mode = str(mode)
        self.calls: list[str] = []
        #: 每一次证法判定的读数（"缝真的被问到了什么"）：`(新正文的证法, 既有路径, 判词)`。
        self.kind_calls: list[dict] = []

    # ---------------------------------------------------------------- 缝面
    def ask_json(self, prompt, **kw):
        note = str(kw.get("note") or "")
        self.calls.append(note)
        data = _material(prompt)
        if note.endswith("statement_keywords"):
            return ({"keywords": ["子群", "Sylow", "共轭", "p 阶元"],
                     "why": "打桩：这几个数学词能把同一条命题捞出来"}, self._Call())
        if self.mode == "off":
            return None, self._Call(False, "judge_timeout", "打桩：这一趟没查成")
        if note.endswith("proof_kind"):
            got = self._proof_kind(data)
            if got is None:
                return None, self._Call(False, "bad_material", "打桩：材料里没有可比的两份证明")
            return got, self._Call()
        return self._identity(data), self._Call()

    # ---------------------------------------------------------------- 命题同一性
    def _identity(self, data: dict) -> dict:
        full = str(data.get("statement_full") or "")
        candidates = [c for c in (data.get("candidates") or []) if isinstance(c, dict)]
        hit = next((c for c in candidates
                    if str(c.get("statement_full") or "") == full), None)
        label = str(data.get("label") or "Sylow 存在性引理")
        if hit is None:
            return {"decision": "different", "canonical_name": label,
                    "same_as": "", "route": "",
                    "condition": "打桩：条件未读", "conclusion": "打桩：结论未读",
                    "reason": "打桩：在册没有逐字同一条命题", "basis": ["打桩"]}
        return {"decision": "same", "same_as": str(hit.get("stmt_id") or ""),
                "canonical_name": label, "route": "",
                "condition": "打桩：条件一致", "conclusion": "打桩：结论一致",
                "reason": "打桩：逐字同一条命题", "basis": ["打桩"]}

    # ---------------------------------------------------------------- 同种证明
    def _proof_kind(self, data: dict) -> dict | None:
        """二态结论：只按 `证法编号` 查 :data:`SCRIPT`（不做相似度 / 长度 / 关键词）。"""
        if self.mode in ("always-same", "always-different"):
            word = "same" if self.mode == "always-same" else "different"
            self.kind_calls.append({"mode": self.mode, "decision": word})
            return {"decision": word, "same_path": 1 if word == "same" else 0,
                    "reason": f"打桩：恒判 {word}"}
        new = self._new_text(data)
        known = self._known_texts(data)
        if not _tag(new) or not known:
            return None
        new_tag = _tag(new)
        for one in known:
            other = _tag(one.get("text"))
            if not other:
                continue
            word = SCRIPT.get(frozenset({new_tag, other}), "different")
            self.kind_calls.append({
                "new": new_tag, "path": int(one.get("path_group") or 0),
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

    @staticmethod
    def _new_text(data: dict) -> str:
        for key in ("proof_text", "proof", "new_proof", "body", "text"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val
            if isinstance(val, dict) and str(val.get("text") or "").strip():
                return str(val.get("text") or "")
        return ""

    @staticmethod
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
    return AgentB(st, extractor=None, extract_text=None, config={}, secretary=sec)


def _citable(st: Store) -> None:
    """一条够可引档的在册命题（依赖段的引用门槛）。"""
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
    """一份三节稿：`## 命题` / `## 证明` / `## 依赖`（依赖段只写三列）。"""
    deps = ("| 引用 | 命题号 | 步 |\n|---|---|---|\n"
            f"| 引理：p 阶元的存在性 | stmt:{DEP_SID} | 1 |\n")
    head = ("# F 的证明手稿\n\n" + (f"- 命题号：stmt:{sid}\n" if sid else "")
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


def _path_groups(st: Store, sid: str) -> list[int]:
    return sorted({int(d.get("path_group") or 0) for d in st.rows("dependencies")
                   if str(d.get("used_by") or "").split("#", 1)[0] == f"stmt:{sid}"})


def _proof_nos(st: Store, sid: str) -> list[int]:
    return [int(no) for no, _t in VR.proof_list(_row(st, sid))]


def _path_count(st: Store, sid: str) -> int:
    return int(MS.path_reading(st, st.root, statement_id=sid)["count"])


def _deps_of(st: Store, sid: str) -> list[dict]:
    return [dict(r) for r in st.rows("dependencies")
            if str(r.get("used_by") or "").split("#", 1)[0] == f"stmt:{sid}"]


def _sign(st: Store, sid: str, rel: str, proof: str, *, proof_no: int = 1) -> None:
    """V 把签盖在这一份正文上；`proof_no` 是这次送审的路径号（逐路径认签）。"""
    conftest.sign_for_the_gate(st.root, statement_id=sid, proof_text=proof,
                               proof_no=int(proof_no), store=st, manuscript=rel)


def _deliver_register(st: Store, b: AgentB, rel: str, proof: str) -> dict:
    """a：把第 1 份稿交给 B（`mode=register`：秘书从稿里登记命题号）。"""
    _write(st, rel, _manuscript("", proof))
    conftest.sign_before_registration(st.root, proof_text=proof)
    return b.ingest_manuscript(manuscript=rel, mode="register")


def _deliver_apply(st: Store, b: AgentB, sid: str, rel: str, proof: str) -> dict:
    """b/c/d：同一命题的又一份稿（`mode=apply`：录到在册那条命题上）。"""
    _write(st, rel, _manuscript(sid, proof))
    _sign(st, sid, rel, proof)
    return b.ingest_manuscript(manuscript=rel, target_stmt_id=sid,
                               cells=["proof_text", "dependencies"], mode="apply")


# ============================================================ 五段的读数（收在一处）

def _a_problems(st: Store, got: dict) -> list[str]:
    """a 的读数：命题拿到号、稿落盘、第 1 条路径、依赖落表。

    `path_group` 从盘上读（`proof_list` / `dependencies.path_group` /
    `path_reading.count` 三处），不从回执读：`mode=register` 的回执今天没有
    `path_group` 这一格（`_ingest_register` 只把登记回执原样并出去）。盘上是 1 才算数；
    回执少这一格是读数缺陷（单独登记在报告里），不是这一段判据的放宽理由。
    """
    problems: list[str] = []
    if got.get("ok") is not True:
        return [f"第 1 份稿没收录成功：refused={got.get('refused')!r} / "
                f"{str(got.get('reason') or '')[:120]}"]
    sid = str((got.get("target") or {}).get("stmt_id") or "")
    if not sid:
        problems.append(f"回执里没有命题号：{got.get('target')!r}")
        return problems
    if _proof_nos(st, sid) != [1]:
        problems.append(f"第 1 份稿落成的证明清单不是 [1]：{_proof_nos(st, sid)}")
    if _path_groups(st, sid) != [1]:
        problems.append(f"第 1 份稿的依赖路径组不是 [1]：{_path_groups(st, sid)}")
    deps = _deps_of(st, sid)
    if not deps:
        problems.append("第 1 份稿的依赖一行都没落表")
    elif {str(d.get("used_by")) for d in deps} != {f"stmt:{sid}"}:
        problems.append(f"第 1 份稿的 used_by 不对：{[d.get('used_by') for d in deps]}")
    row = _row(st, sid)
    proof_text = str(row.get("proof_text") or "")
    if str(got.get("manuscript", {}).get("proof_sha256") or "") and (
            VR.text_sha(proof_text) != str(got["manuscript"]["proof_sha256"])):
        problems.append("稿里的证明正文与命题行上的 canonical 不是同一份")
    return problems


def _one_path_only_problems(st: Store, sid: str, *, label: str) -> list[str]:
    """b / d 的读数：盘上不许出现第二条路径（四处一起数，缺一处都可能恒真）。"""
    problems: list[str] = []
    if _proof_nos(st, sid) != [1]:
        problems.append(f"{label}：证明清单变成了 {_proof_nos(st, sid)}（应 [1]）")
    if _path_groups(st, sid) != [1]:
        problems.append(f"{label}：依赖路径组变成了 {_path_groups(st, sid)}（应 [1]）")
    if _path_count(st, sid) != 1:
        problems.append(f"{label}：`path_reading.count` = {_path_count(st, sid)}（应 1）")
    return problems


def _refusal_problems(got: dict, *, path_no: int) -> list[str]:
    problems: list[str] = []
    if got.get("ok") is not False:
        problems.append(f"这一份稿被照收了（ok={got.get('ok')!r}）：{str(got.get('path_group'))}")
        return problems
    code = str(got.get("refused") or got.get("kind") or "")
    if code != "proof_same_kind":
        problems.append(f"拒收码不是 proof_same_kind：{code!r} / "
                        f"{str(got.get('reason') or '')[:120]}")
    why = str(got.get("reason") or got.get("error") or "")
    if f"第 {path_no}" not in why:
        problems.append(f"拒信没点名与第 {path_no} 条路径同种：{why[:140]!r}")
    if "同种" not in why:
        problems.append(f"拒信里没有「同种」两个字：{why[:140]!r}")
    if "路径" not in why:
        problems.append(f"拒信用的是证明号词汇、不是「路径」：{why[:140]!r}")
    return problems


def _e_readings(st: Store, sid: str) -> dict:
    """e 的成功格：两条路径各自"签 + 回填"。

    「成功」的定义（读代码后定，逐格可核）：
    - 回填：`proofs` 清单里第 1 / 第 2 条路径的正文分别等于两份优化稿的 `## 证明`；
    - 签：`out/vsigns/<正文 sha>.json` 在两份正文上都成立（`vsigns.sign_path` 存在），
      且命题行的 `evidence.reviewed_by_proof` 两格都是真；
    - 优化态：`evidence.optimized_by_proof` 两格都是真（"洗过一遍"的读数）；
    - 旧正文进 `proof_history`（回填不是静默覆盖）。
    """
    from agentflow import vsigns as VS

    row = _row(st, sid)
    proofs = VR.proof_list(row)
    ev = dict((dict(row.get("bits") or {})).get("evidence") or {})
    history = [dict(h) for h in (row.get("proof_history") or [])]
    return {
        "proofs": [(int(no), VR.text_sha(str(t))) for no, t in proofs],
        "texts": [str(t) for _no, t in proofs],
        "signed": {no: bool(VS.sign_path(st.root, VR.text_sha(str(t))).is_file())
                   for no, t in proofs},
        "reviewed_by_proof": {str(k): bool(v) for k, v in
                              dict(ev.get("reviewed_by_proof") or {}).items()},
        "optimized_by_proof": {str(k): bool(v) for k, v in
                               dict(ev.get("optimized_by_proof") or {}).items()},
        "history": [(int(h.get("proof_no") or 0),
                     str(h.get("sha") or "")) for h in history],
    }


def _rehearse(base: pathlib.Path, *, mode: str = "normal") -> dict:
    """把业主那一场彩排完整跑一遍，返回逐段读数（反真空拿同一份读数打红）。"""
    st = _ws(base)
    _citable(st)
    seam = _Seam(mode=mode)
    b = _agent(st, seam)
    out: dict = {"st": st, "seam": seam, "problems": {k: [] for k in "abcde"}}

    got_a = _deliver_register(st, b, REL1, P1)
    out["a"] = got_a
    out["sid"] = str((got_a.get("target") or {}).get("stmt_id") or "")
    out["problems"]["a"] = _a_problems(st, got_a)
    sid = out["sid"]
    if not sid or out["problems"]["a"]:
        return out

    # ---- b：同一命题、证法语义一致 ⇒ 拒收 ------------------------------------
    got_b = _deliver_apply(st, b, sid, REL2, P2)
    out["b"] = got_b
    out["problems"]["b"] = (_refusal_problems(got_b, path_no=1)
                            + _one_path_only_problems(st, sid, label="b"))

    # ---- c：同一命题、证法语义不同 ⇒ 第 2 条路径 ------------------------------
    got_c = _deliver_apply(st, b, sid, REL3, P3)
    out["c"] = got_c
    if got_c.get("ok") is not True:
        out["problems"]["c"].append(
            f"第 3 份稿没收录成功：refused={got_c.get('refused')!r} / "
            f"{str(got_c.get('reason') or '')[:120]}")
    pg = got_c.get("path_group")
    pg = int((pg or {}).get("path_group") or 0) if isinstance(pg, dict) else int(pg or 0)
    if pg != 2:
        out["problems"]["c"].append(f"第 3 份稿的 path_group 不是 2：{pg!r}")
    if _proof_nos(st, sid) != [1, 2]:
        out["problems"]["c"].append(f"证明清单不是 [1, 2]：{_proof_nos(st, sid)}")
    if _path_groups(st, sid) != [1, 2]:
        out["problems"]["c"].append(f"依赖路径组不是 [1, 2]：{_path_groups(st, sid)}")
    if _path_count(st, sid) != 2:
        out["problems"]["c"].append(f"`path_reading.count` = {_path_count(st, sid)}（应 2）")
    row = _row(st, sid)
    if VR.text_sha(VR.proof_text_of(row, 1)) != VR.text_sha(P1):
        out["problems"]["c"].append("第 1 条路径的正文被第 3 份稿顶掉了")
    if VR.text_sha(VR.proof_text_of(row, 2)) != VR.text_sha(P3):
        out["problems"]["c"].append("第 2 条路径的正文不是第 3 份稿交来的那一份")
    for rel in (REL3,):
        if not (pathlib.Path(st.root) / rel).is_file():
            out["problems"]["c"].append(f"第 3 份稿没在盘上：{rel}")

    # ---- d：与第 2 条路径语义一致 ⇒ 拒收 -------------------------------------
    got_d = _deliver_apply(st, b, sid, REL4, P4)
    out["d"] = got_d
    out["problems"]["d"] = _refusal_problems(got_d, path_no=2)
    if _proof_nos(st, sid) != [1, 2]:
        out["problems"]["d"].append(f"d：证明清单变成了 {_proof_nos(st, sid)}（应 [1, 2]）")
    if _path_groups(st, sid) != [1, 2]:
        out["problems"]["d"].append(f"d：依赖路径组变成了 {_path_groups(st, sid)}（应 [1, 2]）")
    if _path_count(st, sid) != 2:
        out["problems"]["d"].append(f"d：`path_reading.count` = {_path_count(st, sid)}（应 2）")

    # ---- e：两条路径各自优化 → 拿签 → 回填 -----------------------------------
    out["e"] = _optimize_both(st, b, sid)
    out["problems"]["e"] = _e_problems(out["e"])
    return out


def _optimize_both(st: Store, b: AgentB, sid: str) -> dict:
    """e：B 对路径 1 / 路径 2 的证明分别优化、拿 V 签、回填（返回逐格读数）。

    走的正是业主描述的次序：`own.land_manuscript`（B 落一份可签的改写稿）→ V 签
    （`conftest.sign_for_the_gate`，真签）→ `own.ingest_manuscript(apply,
    cells=["proof_text"])`（回填）。两条路径各落一份稿：同一份稿不可能同时是第 1
    条与第 2 条路径的正文，所以 `landed1.path != landed2.path` 是 e 的第一格判据。
    优化线显式带 `(命题号, 路径号)`（业主 2026-11-12：「优化线需指明命题号和路径」）：
    `land_manuscript` / `ingest_manuscript` 都传 `path_group=no`；路径身份不写稿头，
    只落在 `manuscriptpaths` 的逐路径记录里。
    """
    out: dict = {}
    for no, text in ((1, OPT1), (2, OPT2)):
        landed = b.land_manuscript(statement_id=sid, proof_text=text,
                                   proof_no=no, path_group=no)
        rel = str(landed.get("path") or "")
        out[f"landed{no}"] = {"ok": landed.get("ok"), "path": rel,
                              "refused": landed.get("refused") or landed.get("kind") or "",
                              "why": str(landed.get("why") or "")[:200]}
        if not (landed.get("ok") and rel):
            out[f"backfill{no}"] = {"ok": False, "why": "稿没落成 ⇒ 没有可签的载体"}
            continue
        manuscript = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
        body = str(DS.proof_body(manuscript) or "").strip("\n")
        out[f"body{no}"] = body
        _sign(st, sid, rel, body, proof_no=no)
        out[f"backfill{no}"] = b.ingest_manuscript(
            manuscript=rel, target_stmt_id=sid, cells=["proof_text"], mode="apply",
            path_group=no)
    out["readings"] = _e_readings(st, sid)
    return out


def _e_problems(e: dict) -> list[str]:
    """e 的判据本体（正控与整场彩排共用同一份读数）。

    「成功」逐格定义（读代码后定）：

    1. 两条路径各一份改写稿（`landed1.path` / `landed2.path` 都存在且不同）；
    2. 回填各回各的路径：`proofs[0]` 是 OPT1、`proofs[1]` 是 OPT2，不新增第 3 条；
    3. 签：`out/vsigns/<正文 sha>.json` 两份都在，`evidence.reviewed_by_proof` 两格真；
    4. 优化态：`evidence.optimized_by_proof` 两格真；
    5. 旧正文进 `proof_history`（两条路径各一条）。
    """
    problems: list[str] = []
    r = dict(e.get("readings") or {})
    if not (e.get("landed1", {}).get("ok") and e.get("landed2", {}).get("ok")):
        problems.append(f"改写稿没落成：{e.get('landed1')} / {e.get('landed2')}")
        return problems
    p1, p2 = str(e["landed1"]["path"]), str(e["landed2"]["path"])
    if p1 == p2:
        problems.append(f"两条路径只有一份改写稿（{p1}）⇒ 第 2 条路径没有自己的载体")
    for no in (1, 2):
        bf = dict(e.get(f"backfill{no}") or {})
        if bf.get("ok") is not True:
            problems.append(f"第 {no} 条的优化稿没回填成功："
                            f"refused={bf.get('refused')!r} {str(bf.get('why') or '')[:100]}")
    texts = list(r.get("texts") or [])
    if len(texts) != 2:
        problems.append(f"回填之后证明清单不是两条：{len(texts)} 条")
    else:
        if VR.text_sha(texts[0]) != VR.text_sha(OPT1):
            problems.append("第 1 条路径的正文不是它的优化稿")
        if VR.text_sha(texts[1]) != VR.text_sha(OPT2):
            problems.append("第 2 条路径的正文不是它的优化稿")
    if r.get("signed") != {1: True, 2: True}:
        problems.append(f"两条路径没有各自留下签文件：{r.get('signed')}")
    reviewed = dict(r.get("reviewed_by_proof") or {})
    if not (reviewed.get("1") is True and reviewed.get("2") is True):
        problems.append(f"逐条签读数不是两格都真：{reviewed}")
    optimized = dict(r.get("optimized_by_proof") or {})
    if not (optimized.get("1") is True and optimized.get("2") is True):
        problems.append(f"优化态不是两格都真：{optimized}")
    nos = sorted(int(no) for no, _sha in (r.get("history") or []))
    if nos != [1, 2]:
        problems.append(f"旧正文没有按两条路径进 proof_history：{nos}")
    return problems


# ============================================================ a–d（同一场彩排的前四段）

def test_a_the_first_manuscript_registers_the_proposition_and_path_one(
        tmp_path: pathlib.Path) -> None:
    """a：第 1 份稿 ⇒ 命题登记（拿到号）、稿落盘、`path_group=1`、依赖落表。"""
    st = _ws(tmp_path)
    _citable(st)
    seam = _Seam()
    got = _deliver_register(st, _agent(st, seam), REL1, P1)
    assert _a_problems(st, got) == [], (got, _a_problems(st, got))
    sid = str(got["target"]["stmt_id"])
    # 稿在盘上，且稿里的 `## 证明` 就是命题行上的 canonical。
    text = (pathlib.Path(st.root) / REL1).read_text(encoding="utf-8")
    assert DS.proof_body(text).strip("\n") == P1, "稿里的证明正文与交来的不一致"
    assert PR.proof_sha(str(_row(st, sid).get("proof_text") or "")) == PR.proof_sha(P1)
    # 命题只多出一条（另一条是夹具里的引理）。
    assert len(list(st.rows("statements"))) == 2, "第 1 份稿多落了一条命题"


def test_b_the_second_manuscript_is_refused_as_the_same_kind(
        tmp_path: pathlib.Path) -> None:
    """b：第 2 份稿与第 1 条路径语义一致 ⇒ 拒收、点名第 1 条路径、盘上不多出路径。

    反差读数：`PK.same_kind_proof(P2, P1)` 的机械读数判 `different`（字面差得远）——
    所以这一段的红不能靠阈值那条路解释；它只能来自秘书的二态结论 `same`。
    """
    st = _ws(tmp_path)
    _citable(st)
    seam = _Seam()
    b = _agent(st, seam)
    got_a = _deliver_register(st, b, REL1, P1)
    assert got_a.get("ok") is True, got_a
    sid = str(got_a["target"]["stmt_id"])

    # 夹具前提（反差读数）：旧阈值在这对稿上会说"不同"。
    mechanical = PK.same_kind_proof(P2, P1)
    assert mechanical["state"] == PK.STATE_DIFFERENT, (
        "夹具前提不成立：这对稿在旧阈值下已经判同种 ⇒ 本段无法把「拒收来自语义」与"
        f"「拒收来自阈值」分开：{mechanical}")
    assert mechanical.get("checked") is True, mechanical

    got_b = _deliver_apply(st, b, sid, REL2, P2)
    problems = _refusal_problems(got_b, path_no=1) + _one_path_only_problems(
        st, sid, label="b")
    assert problems == [], (problems, {k: got_b.get(k) for k in (
        "ok", "refused", "reason", "path_group")})


def test_c_the_third_manuscript_with_a_different_method_is_path_two(
        tmp_path: pathlib.Path) -> None:
    """c：第 3 份稿的证法语义不同 ⇒ 收录为 `path_group=2`，两份稿各自可读。

    机械读数（`PK.same_kind_proof(P3, P1)`）在这里判 `different` —— 与结局同向，所以
    本段的绿不能单独证明"语义判别在起作用"；那由 `always-same` 的反真空与缝面读数钉。
    这里仍然把这个读数写下来，是为了让读的人一眼看到"阈值会怎么判"，以及 c 没有靠它。
    """
    st = _ws(tmp_path)
    _citable(st)
    seam = _Seam()
    b = _agent(st, seam)
    got_a = _deliver_register(st, b, REL1, P1)
    assert got_a.get("ok") is True, got_a
    sid = str(got_a["target"]["stmt_id"])

    mechanical = PK.same_kind_proof(P3, P1)
    assert mechanical.get("checked") is True, mechanical
    assert mechanical["state"] == PK.STATE_DIFFERENT, (
        "夹具读数变了（这一对稿在旧阈值下变成同种）：请复核 P3 的措辞与 c 的说明",
        mechanical)

    got_c = _deliver_apply(st, b, sid, REL3, P3)
    assert got_c.get("ok") is True, (got_c.get("refused"), got_c.get("reason"))
    row = _row(st, sid)
    assert _proof_nos(st, sid) == [1, 2], _proof_nos(st, sid)
    assert _path_groups(st, sid) == [1, 2], _path_groups(st, sid)
    assert _path_count(st, sid) == 2, _path_count(st, sid)
    assert VR.text_sha(VR.proof_text_of(row, 1)) == VR.text_sha(P1)
    assert VR.text_sha(VR.proof_text_of(row, 2)) == VR.text_sha(P3)
    # 两份稿都在盘上、各自可读（一个稿号 = 一份文件 = 一份证明）。
    for rel, proof in ((REL1, P1), (REL3, P3)):
        text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
        assert DS.proof_body(text).strip("\n") == proof, rel


def test_d_the_fourth_manuscript_is_refused_against_path_two(
        tmp_path: pathlib.Path) -> None:
    """d：第 4 份稿与第 2 条路径语义一致 ⇒ 拒收、点名第 2 条路径、路径数仍是 2。"""
    st = _ws(tmp_path)
    _citable(st)
    seam = _Seam()
    b = _agent(st, seam)
    sid = str(_deliver_register(st, b, REL1, P1)["target"]["stmt_id"])
    assert _deliver_apply(st, b, sid, REL3, P3).get("ok") is True
    got_d = _deliver_apply(st, b, sid, REL4, P4)
    problems = _refusal_problems(got_d, path_no=2)
    # c 已经落成第 2 条路径 ⇒ d 之后仍是两条（不是 [1]：这条判据钉的是"没有第 3 条"）。
    if _proof_nos(st, sid) != [1, 2]:
        problems.append(f"d：证明清单变成了 {_proof_nos(st, sid)}（应 [1, 2]）")
    if _path_groups(st, sid) != [1, 2]:
        problems.append(f"d：依赖路径组变成了 {_path_groups(st, sid)}（应 [1, 2]）")
    if _path_count(st, sid) != 2:
        problems.append(f"d：`path_count` = {_path_count(st, sid)}（应 2）")
    assert problems == [], (problems, {k: got_d.get(k) for k in (
        "ok", "refused", "reason", "path_group")})
    # 第 4 份稿再交一次也不许变成第 3 条路径。
    assert _path_count(st, sid) == 2, _path_count(st, sid)


# ============================================================ e（收尾：优化 → 签 → 回填）

def test_e_both_paths_are_optimized_signed_and_backfilled(
        tmp_path: pathlib.Path) -> None:
    """e：B 分别优化两条路径 → 拿 V 签 → 回填；两条路径各自留下"签 + 回填"的读数。

    「成功」逐格定义在 :func:`_e_problems` / :func:`_e_readings`：
    ① 两条路径各一份改写稿（`landed1.path != landed2.path`）；
    ② 回填各回各的路径（`proofs[0]` 是 OPT1、`proofs[1]` 是 OPT2，不新增第 3 条）；
    ③ 签：`out/vsigns/<正文 sha>.json` 两份都在、`reviewed_by_proof` 两格真；
    ④ 优化态：`optimized_by_proof` 两格真；
    ⑤ 旧正文按两条路径各进一次 `proof_history`。
    """
    st = _ws(tmp_path)
    _citable(st)
    b = _agent(st, _Seam())
    sid = str(_deliver_register(st, b, REL1, P1)["target"]["stmt_id"])
    assert _deliver_apply(st, b, sid, REL3, P3).get("ok") is True
    got = _optimize_both(st, b, sid)
    problems = _e_problems(got)
    assert problems == [], (problems, {k: got.get(k) for k in (
        "landed1", "landed2", "backfill1", "backfill2", "readings")})
    assert _proof_nos(st, sid) == [1, 2], _proof_nos(st, sid)


# ============================================================ 整场彩排 + 反真空

def test_the_whole_rehearsal_runs_end_to_end(tmp_path: pathlib.Path) -> None:
    """正常剧本：a–e 五段一次跑通（业主那一场彩排的完整次序）。"""
    got = _rehearse(tmp_path / "normal", mode="normal")
    problems = {k: v for k, v in got["problems"].items() if v}
    assert not problems, problems


def test_always_different_makes_the_refusals_red(tmp_path: pathlib.Path) -> None:
    """反真空①：缝恒回 `different` ⇒ b、d 的拒收断言必须红。

    否则"拒收"可能只是恒真（谁来都拒）或根本没被这条判据管。
    """
    got = _rehearse(tmp_path / "always-different", mode="always-different")
    assert got["problems"]["b"], (
        "缝恒判 different 之后 b 仍然被拒 ⇒ b 的拒收没有对象（拒的不是「同种」）")
    assert got["problems"]["d"], (
        "缝恒判 different 之后 d 仍然被拒 ⇒ d 的拒收没有对象（拒的不是「同种」）")
    assert any("照收" in p or "proof_same_kind" in p for p in got["problems"]["b"]), (
        got["problems"]["b"])


def test_always_same_makes_the_second_path_red(tmp_path: pathlib.Path) -> None:
    """反真空②：缝恒回 `same` ⇒ c 的第 2 条路径必须红。"""
    got = _rehearse(tmp_path / "always-same", mode="always-same")
    assert got["problems"]["c"], (
        "缝恒判 same 之后第 3 份稿仍然落成第 2 条路径 ⇒ c 的第 2 条路径没有对象")
    assert any("没收录成功" in p or "path_group" in p or "证明清单" in p
               for p in got["problems"]["c"]), got["problems"]["c"]


def test_the_seam_was_really_asked_about_the_two_proofs(tmp_path: pathlib.Path) -> None:
    """反真空③（缝面）：三次证法判定各按剧本问了一对（A1/A1、A1/B1、B1/B1）。

    这一条钉的是"判定真的走了那条缝"：`kind_calls` 为空 ⇒ 上面前四段的绿与语义无关。
    """
    got = _rehearse(tmp_path / "seam", mode="normal")
    calls = [c for c in got["seam"].kind_calls if c.get("other")]
    seen = {(c["new"], c["other"], c["decision"]) for c in calls}
    assert ("A1", "A1", "same") in seen, (calls, seen)
    assert ("B1", "A1", "different") in seen, (calls, seen)
    assert ("B1", "B1", "same") in seen, (calls, seen)


def test_path_resolution_is_what_keeps_the_carriers_apart(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空④（C1 / C2）：逐路径解析永远回 canonical ⇒ e 的第一条必红。

    把 `bmanuscript.manuscript_id_for_path` 打成"永远命中第一份 B 稿"—— 那正是改前
    「一条命题一份 B 稿」的形态。两条路径于是落到同一个稿号：第 2 条覆盖第 1 条的
    载体，`landed1.path == landed2.path`。这一条钉的是"两条路径各一份载体"这件事
    真的来自按路径认稿，不是恒真。
    """
    from agentflow import bmanuscript as BM

    st = _ws(tmp_path)
    _citable(st)
    b = _agent(st, _Seam())
    sid = str(_deliver_register(st, b, REL1, P1)["target"]["stmt_id"])
    assert _deliver_apply(st, b, sid, REL3, P3).get("ok") is True

    monkeypatch.setattr(
        BM, "manuscript_id_for_path",
        lambda root, statement_id, path_group, *, store=None: {
            "checked": True, "found": True, "path_exists": True,
            "path_group": int(path_group or 0), "manuscript_id": "000000",
            "path": "reports/b-proof-000000.md", "candidates": [],
            "basis": "stub", "why": "打桩：永远 canonical（改前形态）"})
    got = _optimize_both(st, b, sid)
    problems = _e_problems(got)
    assert any("只有一份改写稿" in p for p in problems), (
        "按路径认稿被打成恒 canonical 之后，e 仍然落成两份不同载体 ⇒ "
        f"「两条路径各一份」没有对象：{problems}")


def test_replace_is_what_makes_the_second_path_optimizable(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空⑤（C4）：关掉 replace ⇒ 回填 2 必撞 `proof_no_taken`。

    优化线那扇门（`_optimization_replace_enabled`）是 C4 的唯一打桩点：打 False 之后
    第 1 条（canonical）仍能换（那是既有口径），第 2 条必须回到"同号不同正文整笔拒"
    —— 证明"能换第 N 份"是这一笔新加的、不是恒真。
    """
    from agentflow.agent_b import AgentB

    st = _ws(tmp_path)
    _citable(st)
    b = _agent(st, _Seam())
    sid = str(_deliver_register(st, b, REL1, P1)["target"]["stmt_id"])
    assert _deliver_apply(st, b, sid, REL3, P3).get("ok") is True
    monkeypatch.setattr(AgentB, "_optimization_replace_enabled",
                        lambda self: False)
    got = _optimize_both(st, b, sid)
    assert dict(got.get("backfill1") or {}).get("ok") is True, got.get("backfill1")
    bf2 = dict(got.get("backfill2") or {})
    assert bf2.get("refused") == "proof_no_taken", (
        "replace 关掉之后回填 2 没有撞 proof_no_taken ⇒ 「能换第 N 份」不来自 C4："
        f"{bf2}")


#: 2026-11-02 准入闸默认 strict 之后，本文件的夹具一律先给"B 即将写进台账的那一份
#: 证明正文"补一签（真签：在册走台账、未在册走 pending）。见 conftest 的同名 fixture。
pytestmark = pytest.mark.usefixtures("signed_v_handoffs")
