# -*- coding: utf-8 -*-
"""判据：攻坚手稿（`notes/…`）被签过 ⇒ 转成 `reports/f-proof-<号>.md` 正式稿。

## 为什么要有这一份（真机读数，2026-11-04 `projects/paper-rewrite-big`）

F 的稿落在 `notes/F-conj000000-proof.md`（14 KB，F 自己 `fs.write` 写的攻坚手稿），
而 `reports/f-proof-*.md` 0 份。追下去不是"没人写稿"，是没有一条代码把
"盘上已经存在的一份稿"转成按号命名的正式稿：

- `AgentF.proof_manuscript` 只写 `reports/f-proof-plan-<计划>.md`；
- `AgentF.publish_manuscript` 只改名它自己手上那一份（`agent_f/core.py` 的 proof
  档），盘上已有的 `notes/…` 稿它一个字节都读不到；
- 于是 `publish_manuscript` 一次都没被调用过，按号命名的稿 0 份，B 的兜底读盘
  （`depsection.read_manuscript`，只扫 `reports/`）也读不到 F 的稿。

## 这一份钉的五条（b 的触发另有一份判据）

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a | `promote_manuscript(notes/稿, 号)` ⇒ `reports/f-proof-<号>.md` 生成、稿头写号、签块跟着搬、第 9 格手稿号=号 | 没有这个函数：盘上那份稿与正式稿之间没有代码 |
| c | 多命题的攻坚稿（两个 `## 命题`）不许被机械转正 ⇒ 受控拒绝 `multiple_propositions`、零写入 | 没有判据；硬转会产出一份"只属于第一条、却带着别条证明"的正式稿 |
| d | 没有 `## 证明` 的稿 ⇒ 受控拒绝 `no_proof_section` | 同上 |
| e | 正式稿已经签住另一版正文时，没签的草稿不许覆盖它 | 转正会毁掉已有的签（"签另算"不是"毁签"） |
| f | 没洗过（缺 `- 依赖面洗稿：`）的稿不许转正 | 否则转正就是绕过 B 的洗稿闸的第二条入口 |

全部 tmp 工作区，不读写 `projects/`（真机工作区只读）。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import depsection as DS
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_f.manuscript import promote_manuscript
from agentflow.store import Store

SID = "000011"
NOTES_REL = "notes/F-conj000000-proof.md"
FORMAL_REL = f"reports/f-proof-{SID}.md"
FULL = "设 d = 1、σ 有界 Borel 可测、两端极限存在且不等；则 N_σ ∩ L^p(R) 在 L^p(R) 中稠密。"
PROOF = ("1. 对 c < d、λ > 0 取 f_λ := [σ(λ(x−c)) − σ(λ(x−d))]/(L+ − L−) ∈ N_σ。\n"
         "2. f_λ 逐点收敛到 1_{(c,d)}，三个区域分别估计 ⇒ L^p 收敛。\n"
         "3. 紧支阶梯函数在 L^p(R) 稠密 ⇒ 闭包是 L^p(R)。")
DEP_TABLE = (
    "## 依赖\n\n"
    "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
    "|---|---|---|---|\n"
    "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n"
)


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _draft(*, number_line: str = "- 命题号：stmt:（还没落号）",
           more_propositions: bool = False, with_proof: bool = True,
           washed: bool = True) -> str:
    """一份攻坚手稿（`notes/…` 的形状：页头 + 命题 + 证明 + 依赖）。"""
    parts = [
        "# F 的证明手稿：conj:000000 攻坚（P1）\n",
        f"{number_line}\n",
        "- 计划：000000 · 子目标：s1\n",
        "\n## 命题\n\n",
        f"{FULL}\n",
    ]
    if more_propositions:
        parts += ["\n## 命题 P2（高维：交集为零）\n\n",
                  "设 d ≥ 2；则 N_σ ∩ L^p(R^d) = {0}。\n"]
    if with_proof:
        parts += ["\n## 证明\n\n", f"{PROOF}\n"]
    parts.append("\n" + DEP_TABLE)
    text = "".join(parts)
    return DS.mark_washed(text, actor="secretary-F") if washed else text


def _write(st: Store, rel: str, text: str) -> pathlib.Path:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _sign(st: Store, rel: str, *, sha: str = "") -> str:
    """给盘上那份稿盖一块「已签」的块（sha 相符；第 9 格按稿名现算）。"""
    text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    want = sha or VR.text_sha(VS.manuscript_proof_body(text))
    stamped = VS.stamp_manuscript_sign(
        text, proof_sha=want, streak=3, need=3, verdict="成立",
        at="2026-11-04T15:00:00+08:00", ledger="verifications/pending/probe.jsonl#v-000001",
        statement_id="", manuscript_id=VS.manuscript_id_of(rel))
    _write(st, rel, stamped)
    return want


def _read(st: Store, rel: str) -> str:
    return (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")


def _block(st: Store, rel: str) -> dict:
    return VS.manuscript_sign_reading(_read(st, rel), manuscript_path=rel)


# ============================================================ a 机制
def test_a_a_signed_notes_draft_becomes_the_numbered_manuscript(tmp_path):
    """a：`notes/` 攻坚稿 + 签 ⇒ `reports/f-proof-<号>.md`（签块跟着搬、手稿号=号）。"""
    st = _ws(tmp_path)
    _write(st, NOTES_REL, _draft())
    sha = _sign(st, NOTES_REL)
    before = _read(st, NOTES_REL)

    out = promote_manuscript(st.root, statement_id=SID, source=NOTES_REL)

    assert out.get("promoted") is True, out
    assert out.get("path") == FORMAL_REL, out
    assert out.get("sign_moved") is True, out
    assert dict(out.get("problem") or {}) == {}, out
    # 攻坚稿留着（它是作者的草稿；正式稿是复制过去的那一份，不是"把草稿弄丢"）。
    assert out.get("source_kept") is True, out
    assert _read(st, NOTES_REL) == before, "转正改了攻坚稿（应一个字节都不动）"

    final = _read(st, FORMAL_REL)
    assert f"- 命题号：stmt:{SID}" in final, final
    block = _block(st, FORMAL_REL)
    assert block.get("found") is True, block
    assert block.get("signed") is True, block
    assert block.get("proof_sha256") == sha, block
    assert block.get("manuscript_id") == SID, block
    assert block.get("identity_state") == "resolved", block


def test_a2_promotion_is_idempotent(tmp_path):
    """a2：同一份再转一次 —— 字节不变、不产生第二份。"""
    st = _ws(tmp_path)
    _write(st, NOTES_REL, _draft())
    _sign(st, NOTES_REL)
    first = promote_manuscript(st.root, statement_id=SID, source=NOTES_REL)
    once = _read(st, FORMAL_REL)
    second = promote_manuscript(st.root, statement_id=SID, source=NOTES_REL)
    assert second.get("promoted") is True, second
    assert _read(st, FORMAL_REL) == once, "第二次转正改动了正式稿"
    assert first.get("path") == second.get("path") == FORMAL_REL


# ============================================================ c/d 负控（形状）
def test_c_a_multi_proposition_draft_is_refused_not_half_promoted(tmp_path):
    """c：多命题的攻坚稿不许机械转正（今晚那份稿就是两节 `## 命题`）。"""
    st = _ws(tmp_path)
    _write(st, NOTES_REL, _draft(more_propositions=True))
    _sign(st, NOTES_REL)

    out = promote_manuscript(st.root, statement_id=SID, source=NOTES_REL)
    assert out.get("promoted") is False, out
    assert dict(out.get("problem") or {}).get("kind") == "multiple_propositions", out
    assert not (pathlib.Path(st.root) / FORMAL_REL).exists(), "被拒了却仍写出正式稿"


def test_d_a_draft_without_a_proof_section_is_refused(tmp_path):
    """d：没有 `## 证明` 的稿 ⇒ 没有可签的正文，不许转正。"""
    st = _ws(tmp_path)
    _write(st, NOTES_REL, _draft(with_proof=False))
    out = promote_manuscript(st.root, statement_id=SID, source=NOTES_REL)
    assert out.get("promoted") is False, out
    assert dict(out.get("problem") or {}).get("kind") == "no_proof_section", out
    assert not (pathlib.Path(st.root) / FORMAL_REL).exists()


# ============================================================ f 洗稿
def test_f_an_unwashed_draft_is_refused(tmp_path):
    """f：没经过 F 的秘书洗稿的稿不许转正 —— 否则就是绕过 B 的洗稿闸的第二条入口。"""
    st = _ws(tmp_path)
    _write(st, NOTES_REL, _draft(washed=False))
    out = promote_manuscript(st.root, statement_id=SID, source=NOTES_REL)
    assert out.get("promoted") is False, out
    assert dict(out.get("problem") or {}).get("kind") == "not_washed", out
    assert not (pathlib.Path(st.root) / FORMAL_REL).exists()


# ============================================================ e 不毁签
def test_e_an_unsigned_draft_does_not_overwrite_a_signed_formal_version(tmp_path):
    """e：正式稿已经签住另一版正文 ⇒ 没签的草稿不许覆盖它（签另算不是毁签）。"""
    st = _ws(tmp_path)
    # 正式稿：签住的旧版。
    old = _draft()
    _write(st, FORMAL_REL, old)
    _sign(st, FORMAL_REL)
    signed_formal = _read(st, FORMAL_REL)
    # 攻坚稿：不同正文、没有签。
    new_text = _draft().replace("3. 紧支阶梯函数在 L^p(R) 稠密 ⇒ 闭包是 L^p(R)。",
                                "3. 这一版换了一条推理（还没有签）。")
    _write(st, NOTES_REL, new_text)

    out = promote_manuscript(st.root, statement_id=SID, source=NOTES_REL)
    assert out.get("promoted") is False, out
    assert dict(out.get("problem") or {}).get(
        "kind") == "target_holds_a_signed_version", out
    assert _read(st, FORMAL_REL) == signed_formal, "已签的正式稿被没签的草稿覆盖了"
