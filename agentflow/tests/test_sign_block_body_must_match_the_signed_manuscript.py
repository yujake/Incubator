# -*- coding: utf-8 -*-
"""落块前核 `body_mismatch`：稿的「## 证明」sha != 被签 sha ⇒ 不盖块（业主 2026-11-02）。

## 口径（逐字）

```text
落块前要核实「这份稿的正文 == 被签的那一份」。84 的 `f-proof-000000.md` 现在正是
「块盖 #p3、文件正文 #p2」⇒ 这种情况不盖块，读数落 `body_mismatch`（诚实，不写假块）。
```

## 为什么这一条必须挡在"写块"这一口上

`正文sha` 那一格只说明"V 签的是哪一份正文"，它不保证眼前这份稿的正文还是那一份。
签名之后 F 又改过稿（84 就是这样：块盖的是 `#p3` 的 sha，文件里现在是 `#p2` 的正文），
再盖一块就等于把一份没被审过的正文盖成"签过"。所以判据放在 :func:`vsigns.land` /
:func:`vsigns.write_manuscript_sign` 这一口：一个字节都不写，读数落 `body_mismatch`。

## 判据

| # | 造什么 | 期望 |
|---|---|---|
| a | 正文与 sha 相符 | 块写成（反真空：这一条不许"什么都不写"就能绿） |
| b | 签完改一个字再落块 | `state=failed` + `code=body_mismatch`，稿逐字节不变 |
| c | 稿里没有「## 证明」那一节 | 同 b（不许拿空正文冒充"签过空集"） |
| d | 84 的 `f-proof-000000.md`（只读） | `body_mismatch=True`：块盖 `dcb988fa`、正文是 `de0d4076` |
| e | 块盖住之后改正文 | 读数翻成 `body_mismatch`（判据不是"永远假"的摆设） |
"""
from __future__ import annotations

import pathlib

from agentflow import verifications as VR
from agentflow import vsigns as VS

FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
PROOF = ("1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
         "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。")
SHA = VR.text_sha(PROOF)
MANUSCRIPT = ("# F 的证明手稿：一致连续\n\n"
              "- 命题号：stmt:（还没落号）\n"
              "- 计划：0000 · 子目标：s1\n\n"
              "## 命题\n\n"
              f"{FULL}\n\n"
              "## 证明\n\n"
              f"{PROOF}\n\n"
              "## 依赖\n\n"
              "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")
REL = "reports/f-proof-000000.md"
PROJ84 = pathlib.Path(__file__).resolve().parents[1] / "projects" / "paper-rewrite-84"


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "ws"
    (root / "reports").mkdir(parents=True)
    (root / REL).write_text(MANUSCRIPT, encoding="utf-8")
    return root


def _stamp(root: pathlib.Path, *, sha: str = SHA) -> dict:
    return VS.write_manuscript_sign(
        root, REL, proof_sha=sha, streak=3, need=3, verdict="成立", signer="V",
        at="2026-11-02T10:00:00+08:00", ledger=f"{REL}#V签", statement_id="")


# ====================================================================== a 相符
def test_a_a_matching_body_is_stamped(tmp_path: pathlib.Path) -> None:
    """正文 == 被签的那一份 ⇒ 块写成（反真空）。"""
    root = _ws(tmp_path)
    got = _stamp(root)
    assert got["state"] == "written" and got["written"] is True, got
    assert got["body_mismatch"] is False, got
    text = (root / REL).read_text(encoding="utf-8")
    assert text.count(VS.SIGN_MARK) == 1, text
    standing = VS.manuscript_sign_standing(text, proof_sha=SHA, manuscript_path=REL)
    assert standing["body_mismatch"] is False and standing["state"] == "signed", standing


# ====================================================================== b 改过
def test_b_a_rewritten_body_is_refused_with_body_mismatch(tmp_path: pathlib.Path) -> None:
    """签完改一个字再落块 ⇒ `code=body_mismatch`，稿逐字节不变（一个字节都不写）。"""
    root = _ws(tmp_path)
    first = _stamp(root)
    assert first["state"] == "written", first
    before = (root / REL).read_bytes()

    # F 又改过正文：块里那个 sha 现在盖的是另一份正文。
    (root / REL).write_text(MANUSCRIPT.replace("取 δ=ε", "取 δ=2ε"), encoding="utf-8")
    edited = (root / REL).read_bytes()

    again = _stamp(root)
    assert again["state"] == "failed", again
    assert again["written"] is False, again
    assert again["code"] == "body_mismatch", again
    assert again["body_mismatch"] is True, again
    assert "正文" in again["why"] and "不是同一份" in again["why"], again["why"]
    assert (root / REL).read_bytes() == edited, "被拒的那一块把稿写动了"
    assert edited != before, "夹具没有真的改稿 ⇒ 这一条判据量不到东西"


# ====================================================================== c 没有那一节
def test_c_a_manuscript_without_a_proof_section_is_refused(tmp_path: pathlib.Path) -> None:
    """稿里没有「## 证明」⇒ 同 `body_mismatch`（不拿空正文冒充"签过空集"）。"""
    root = tmp_path / "ws"
    (root / "reports").mkdir(parents=True)
    (root / REL).write_text("# 空稿\n\n- 计划：0000\n\n## 命题\n\n只有命题。\n",
                            encoding="utf-8")
    got = _stamp(root)
    assert got["state"] == "failed" and got["code"] == "body_mismatch", got
    assert "证明" in got["why"], got["why"]
    assert VS.SIGN_MARK not in (root / REL).read_text(encoding="utf-8")


# ====================================================================== d 84 定格
def test_d_the_84_manuscript_is_a_body_mismatch() -> None:
    """84 的 `f-proof-000000.md`：块盖 #p3（`dcb988fa`），文件正文是 #p2（`de0d4076`）。"""
    if not PROJ84.is_dir():
        return
    rel = "reports/f-proof-000000.md"
    text = (PROJ84 / rel).read_text(encoding="utf-8")
    body_sha = VR.text_sha(VS.manuscript_proof_body(text))
    block = VS.manuscript_sign_reading(text, manuscript_path=rel)
    assert block["proof_sha256"].startswith("dcb988fa"), block["proof_sha256"]
    assert body_sha.startswith("de0d4076"), (
        f"84 的正文 sha 变了（{body_sha[:12]}）⇒ 这条定格读数要重取")
    assert body_sha != block["proof_sha256"], "84 这一份现在竟然块与正文相符 ⇒ 判据失去现场"
    got = VS.manuscript_body_matches(text, artifact_sha=block["proof_sha256"])
    assert got["matches"] is False and got["body_mismatch"] is True, got
    assert body_sha == got["body_sha256"], got

    standing = VS.manuscript_sign_standing(text, proof_sha=body_sha, manuscript_path=rel)
    assert standing["body_mismatch"] is True, standing
    assert standing["state"] == "stale", standing
    # 只读纪律：写块那一口对同一份材料也必须拒绝（这里只调纯判据，不碰 projects/ 下）。
    assert (PROJ84 / rel).read_text(encoding="utf-8") == text


# ====================================================================== e 反真空
def test_e_editing_after_the_stamp_flips_the_reading(tmp_path: pathlib.Path) -> None:
    """块盖住之后改正文 ⇒ 读数翻成 `body_mismatch`（判据不是摆设）。"""
    root = _ws(tmp_path)
    assert _stamp(root)["state"] == "written"
    text = (root / REL).read_text(encoding="utf-8")
    assert VS.manuscript_sign_standing(text, proof_sha=SHA,
                                       manuscript_path=REL)["body_mismatch"] is False
    changed = text.replace("第 1 步的 δ", "第 1 步里的 δ")
    standing = VS.manuscript_sign_standing(changed, proof_sha=SHA, manuscript_path=REL)
    assert standing["body_mismatch"] is True, standing
    assert standing["state"] == "stale", standing
