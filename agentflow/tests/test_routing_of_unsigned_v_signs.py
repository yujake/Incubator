# -*- coding: utf-8 -*-
"""缺 V 签的责任路由（业主 2026-11-02）：B 不润色 F 的无签证明；M 不代唤 V。

## 口径（逐字）

```text
如果命题在册且缺失V签，这是B侧问题，M应让B处理。
如果F侧产出证明而没有V签，这是F侧工作异常，B不该处理（润色）无签证明。
重点是要F侧拿V签，拿到V签F才能交差。
```

于是三件事各落一处：

| # | 守的是 | 落点 |
|---|---|---|
| a | 收到 F 的无签证明 ⇒ B 受控拒绝，点名"请 F 先拿 V 签"（code + 原因 + 建议） | `register_statement`（`f_proof_needs_v_sign_first`） |
| b | M 的口径：在册缺签 ⇒ 找 B；F 产出无签 ⇒ 让 F 先拿签；不再写"M→B→V 代唤" | `specs/m.py` |
| c | B 的口径：不润色无签的 F 证明；册上已有而缺签才是 B 自己的事 | `specs/b.py` |

判据读的是政策真身（`specs/*.py` 的字符串），不是渲染产物：渲染由
`tests/test_agent_prompts.py` 的十一格摘要钉着。

反真空（d）：把 `_DS.read_carried_manuscript` 打桩成"清单里没有这一条" ⇒ a 的
`f_proof_needs_v_sign_first` 必须消失（它量的是"真的按清单读到 F 的稿"）。
"""
from __future__ import annotations

import pathlib

from agentflow import depsection as _DS
from agentflow.agent_b import AgentB
from agentflow.store import Store

REPO = pathlib.Path(__file__).resolve().parents[1]
PKG = REPO / "src" / "agentflow"
M_SPEC = PKG / "specs" / "m.py"
B_SPEC = PKG / "specs" / "b.py"

FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
PROOF = ("1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
         "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。")
SID = "000011"
REL = "reports/f-proof-000011.md"
REPORT = "reports/000011-research.md"
#: 一份 F 的证明手稿，没有签块（这正是要退回的那一档）。
RAW = ("# F 的证明手稿：一致连续\n\n"
       "- 计划：0011 · 子目标：s1\n"
       "- 依赖面洗稿：已洗=true；执行者=secretary-F\n\n"
       "## 命题\n\n"
       f"{FULL}\n\n"
       "## 证明\n\n"
       f"{PROOF}\n\n"
       "## 依赖\n\n"
       "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
       "|---|---|---|---|\n"
       "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")


def _ws(tmp_path: pathlib.Path) -> Store:
    import hashlib

    st = Store(tmp_path / "ws")
    st.init()
    root = pathlib.Path(st.root)
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / REL).write_text(RAW, encoding="utf-8")
    sha = hashlib.sha256((root / REL).read_bytes()).hexdigest()
    rows = [{"statement_id": SID, "path": REL, "sha256": sha}]
    (root / REPORT).write_text("# D 的研究手稿\n\n" + _DS.render_carried_section(rows),
                               encoding="utf-8")
    return st


def _register(st: Store) -> dict:
    b = AgentB(st, extractor=None, extract_text=None)
    return b.register_statement(
        statement_full=FULL, statement_text=FULL, proof_text=PROOF,
        kind="theorem", label="探针命题", origin="own_result",
        evidence_kind="heuristic", quote_verified=None,
        quote_reason="夹具：自产证明，没有第二份文本可比对",
        line_range={"label": REL})


# ====================================================================== a
def test_a_b_returns_fs_unsigned_proof_and_names_the_next_step(
        tmp_path: pathlib.Path) -> None:
    """a F 的无签证明 ⇒ `f_proof_needs_v_sign_first`：一句原因 + 一句建议。"""
    st = _ws(tmp_path)
    got = _register(st)

    assert got.get("ok") is not True, got
    assert got.get("kind") == "f_proof_needs_v_sign_first", got
    text = f"{got.get('error') or ''}{got.get('reason') or ''}"
    assert "F 侧" in text or "F 产出的" in text, text
    assert "请 F 先拿 V 签" in text, text
    assert "verify.verify_proof" in text and "vsigns.land" in text, text
    assert list(st.rows("statements")) == [], "被退回的那一笔写进了 statements"


# ====================================================================== b
def test_b_m_does_not_route_unsigned_proofs_through_b_to_v() -> None:
    """b M 的口径：在册缺签 ⇒ 找 B；F 产出无签 ⇒ 让 F 先拿签；不再写代唤 V。"""
    text = M_SPEC.read_text(encoding="utf-8")
    assert "命题已在册而缺 V 签" in text and "让 **B** 处理" in text, text[-3000:]
    assert "F 产出但没签" in text and "先拿 V 签" in text, text[-3000:]
    assert "没有 V 签的编辑权" in text and "获取 V 签的义务" in text, text[-3000:]
    # 旧口径必须已经不在：M 代唤 V / 让 B 润色 F 的证明。
    assert "要 V 的签就经 B 走那条路" not in text, "M 的提示词里还留着 M→B→V 代唤那条旧口径"
    assert "F 产出的证明天生带 V 的签字" not in text, "M 的提示词里还留着「天生带签」那句旧话"


# ====================================================================== c
def test_c_b_never_polishes_an_unsigned_f_proof() -> None:
    """c B 的口径：收到无签的 F 证明 ⇒ 不润色、退回；册上已有而缺签才是 B 自己的事。"""
    text = B_SPEC.read_text(encoding="utf-8")
    assert "收到没有 V 签的 F 证明" in text and "不润色" in text, text[-3000:]
    assert "请 F 先拿 V 签" in text, text[-3000:]
    assert "册上已有这一条而缺签时不同" in text, text[-3000:]
    assert "不许推给 F" in text, text[-3000:]


# ====================================================================== d
def test_d_stubbing_the_addressing_removes_the_new_refusal(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """d 反真空：寻址被打桩成空 ⇒ 那个新码不再出现（它量的是"真按清单读到 F 的稿"）。"""

    def _empty(root: object, *, statement_ids=(), proof_text="") -> dict:
        return {"checked": True, "source": _DS.SOURCE_NONE, "text": "", "path": "",
                "sha256": "", "carried_by": "", "tried": [], "why": "夹具：打桩成空",
                "named": False, "address": "", "item": 0, "list_report": "",
                "list_line": 0, "list_sha256": ""}

    monkeypatch.setattr(_DS, "read_carried_manuscript", _empty)
    st = _ws(tmp_path)
    got = _register(st)
    assert got.get("kind") != "f_proof_needs_v_sign_first", got
