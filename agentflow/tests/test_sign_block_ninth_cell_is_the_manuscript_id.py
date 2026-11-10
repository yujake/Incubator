# -*- coding: utf-8 -*-
"""签块第 9 格 = 裸稿号；读侧三态 resolved / unmatched / legacy（业主 2026-11-02）。

## 口径（逐字，别改解释）

```text
「没有证明号是正常的，除非你用"手稿号"」
```

业主 2026-11-02 的裁定：这一格填裸稿号（`000000` / `plan-0001` / `a`），不填文件名；
写法上要把"哪一种号"带进值里（`plan-0001` 带前缀），避免 `f-proof-plan-0001.md` 与
`f-proof-0001.md` 在数字上撞车。

## 为什么这一格必须能读出三态

签块是"随稿走的那一份"：它会被复制、被改名、被别的稿借走。第 9 格回答的是
"这一块属于哪一份稿"，而这个问题有三个诚实答案，不许折成两个：

| `identity_state` | 什么时候 | 不许读成 |
|---|---|---|
| `resolved` | 格里的裸稿号 == 它所处那份稿的裸稿号 | —— |
| `unmatched` | 格里的号与这份稿对不上（块被搬过 / 格是空的 / 认不出这份稿的号） | 不许读成"签过了" |
| `legacy` | 旧 8 格块（当时还没有这一格） | 绝不许读成"没签"：它是当时真的签过 |

## 判据

| # | 造什么 | 期望 |
|---|---|---|
| a | 写一块 | 第 9 格是裸稿号；`SIGN_BLOCK_KEYS` 有 9 格 |
| b | `f-proof-plan-0001.md` 的块 | 读出 `plan-0001`（带前缀），不是 `0001` |
| c | 同一块搬到 `f-proof-0002.md` | `identity_state=unmatched`，`manuscript_key=0002` |
| d | 旧 8 格块 | `identity_state=legacy`，且 `manuscript_sign_standing` 仍 `signed` |
| e | 84 的两份真稿（只读） | 两份都是 `legacy`（它们写在 2026-11-02 之前），不冒充新格式 |
"""
from __future__ import annotations

import pathlib

from agentflow import verifications as VR
from agentflow import vsigns as VS

FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
PROOF = "1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n2. 按定义即一致连续。"
MANUSCRIPT = ("# F 的证明手稿：一致连续\n\n"
              "- 命题号：stmt:（还没落号）\n"
              "- 计划：0000 · 子目标：s1\n\n"
              "## 命题\n\n"
              f"{FULL}\n\n"
              "## 证明\n\n"
              f"{PROOF}\n\n"
              "## 依赖\n\n"
              "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")
SHA = VR.text_sha(PROOF)
#: 84 的两份真稿（只读证据物：projects/ 下 不许写）。
PROJ84 = pathlib.Path(__file__).resolve().parents[1] / "projects" / "paper-rewrite-84"


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "ws"
    (root / "reports").mkdir(parents=True)
    return root


def _put(root: pathlib.Path, rel: str, text: str = MANUSCRIPT) -> pathlib.Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _text(root: pathlib.Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


# ====================================================================== a 第 9 格
def test_a_the_ninth_cell_is_the_bare_manuscript_id(tmp_path: pathlib.Path) -> None:
    """写一块 ⇒ 第 9 格写裸稿号（不是文件名），格子表有 9 格。"""
    root = _ws(tmp_path)
    rel = "reports/f-proof-000000.md"
    _put(root, rel)

    got = VS.write_manuscript_sign(
        root, rel, proof_sha=SHA, streak=3, need=3, verdict="成立", signer="V",
        at="2026-11-02T10:00:00+08:00", ledger=f"{rel}#V签", statement_id="")
    assert got["state"] == "written", got
    assert len(VS.SIGN_BLOCK_KEYS) == 9, VS.SIGN_BLOCK_KEYS
    assert VS.SIGN_BLOCK_KEYS[-1] == "手稿号", VS.SIGN_BLOCK_KEYS
    line = next(ln for ln in _text(root, rel).splitlines()
                if ln.strip().startswith(VS.SIGN_MARK))
    assert "；手稿号=000000" in line, line
    assert "手稿号=f-proof-000000.md" not in line, line

    reading = VS.manuscript_sign_reading(_text(root, rel), manuscript_path=rel)
    assert reading["manuscript_id"] == "000000", reading
    assert reading["identity_state"] == "resolved", reading


def test_a2_a_prefixed_manuscript_id_keeps_its_prefix(tmp_path: pathlib.Path) -> None:
    """`f-proof-plan-0001.md` ⇒ `plan-0001`（带前缀，不与 `0001` 撞车）。

    ## 改前钉什么 / 改后钉什么

    改前（业主 2026-11-05 父裁定）：计划稿是合法落稿名，但不是签的载体 ⇒ 第 9 格
    对得上也不许 `resolved`（只到 `unmatched`，真机 883c3097）。

    2026-11-10 业主裁定：「F 的稿自己维护一套号源，不依赖命题号和计划号」「计划不拥有
    稿件」⇒ 老盘上的 `f-proof-plan-*` 是只读兼容名，与数字名同等（可签）⇒ 身份
    `resolved`。强度不降，另加两条反向：
    - 块里第 9 格写 `0001`（裸数字）而稿是 `plan-0001` ⇒ unmatched：前缀不是装饰，
      `plan-0001` 与 `0001` 仍是两个号（否则"同等"就等于"撞车"）；
    - 载体合法不等于这份稿有了命题号：`manuscript_id` 里带的是稿号，不是 `stmt_id`。
    """
    root = _ws(tmp_path)
    rel = "reports/f-proof-plan-0001.md"
    _put(root, rel)
    got = VS.write_manuscript_sign(root, rel, proof_sha=SHA, streak=3, need=3)
    assert got["state"] == "written", got
    reading = VS.manuscript_sign_reading(_text(root, rel), manuscript_path=rel)
    assert reading["manuscript_id"] == "plan-0001", reading
    assert reading["identity_state"] == "resolved", reading
    assert "与这一份稿相同" in str(reading.get("identity_why") or ""), reading
    # 反向 ①：写 `0001` 的块搬到 plan-0001 这份稿上 ⇒ 撞不上车，仍是 unmatched。
    wrong = VS.stamp_manuscript_sign(
        _text(root, rel), proof_sha=SHA, streak=3, need=3, manuscript_id="0001")
    collided = VS.manuscript_sign_reading(wrong, manuscript_path=rel)
    assert collided["manuscript_id"] == "0001", collided
    assert collided["manuscript_key"] == "plan-0001", collided
    assert collided["identity_state"] == "unmatched", collided
    # 反向 ②：载体合法（老盘兼容）≠ plan-0001 成了命题号。
    assert VS.parse_manuscript_name(rel)["family"] == "f-proof", VS.parse_manuscript_name(rel)
    assert reading["statement_id"] == "", reading
    # 反真空：同一份正文换成 `f-proof-0001.md` 时它是另一个号（不许在数字上撞车）。
    assert VS.manuscript_id_of("reports/f-proof-0001.md") == "0001"
    assert VS.manuscript_id_of(rel) == "plan-0001"


# ====================================================================== c unmatched
def test_c_a_block_moved_to_another_manuscript_is_unmatched(tmp_path: pathlib.Path) -> None:
    """块被搬到另一份稿 ⇒ `unmatched`（块说它属于 000000，而它现在在 0002 里）。"""
    root = _ws(tmp_path)
    first = "reports/f-proof-000000.md"
    _put(root, first)
    VS.write_manuscript_sign(root, first, proof_sha=SHA, streak=3, need=3)
    text = _text(root, first)
    other = "reports/f-proof-0002.md"
    _put(root, other, text)

    reading = VS.manuscript_sign_reading(text, manuscript_path=other)
    assert reading["found"] is True, reading
    assert reading["manuscript_id"] == "000000", reading
    assert reading["manuscript_key"] == "0002", reading
    assert reading["identity_state"] == "unmatched", reading
    # 认不出这一份稿的号 ⇒ 也是 unmatched（不许猜一个号填进去）。
    assert VS.manuscript_id_of("reports/notes.md") == ""
    assert VS.manuscript_sign_reading(text, manuscript_path="reports/notes.md")[
        "identity_state"] == "unmatched"


# ====================================================================== d legacy
def test_d_a_legacy_eight_cell_block_is_legacy_not_unsigned(tmp_path: pathlib.Path) -> None:
    """旧 8 格块 ⇒ `legacy`；而"这一份签过没有"仍按 sha 读成 `signed`（不许读成没签）。"""
    root = _ws(tmp_path)
    rel = "reports/f-proof-000000.md"
    # 84 的块形状（2026-11-02 之前写的）：只有 8 格，没有「手稿号」。
    legacy = (f"{VS.SIGN_MARK}已签=true；判词=成立；连续=3/3；正文sha={SHA}；"
              "时间=2026-11-02T16:43:01+08:00；签名者=V；"
              f"台账=verifications/000000.jsonl#v-000010；命题号=000000")
    text = MANUSCRIPT.replace("- 计划：0000 · 子目标：s1\n",
                              "- 计划：0000 · 子目标：s1\n" + legacy + "\n")
    _put(root, rel, text)

    reading = VS.manuscript_sign_reading(_text(root, rel), manuscript_path=rel)
    assert reading["found"] is True and reading["signed"] is True, reading
    assert reading["manuscript_id"] == "", reading
    assert reading["identity_state"] == "legacy", reading

    standing = VS.manuscript_sign_standing(_text(root, rel), proof_sha=SHA,
                                           manuscript_path=rel)
    assert standing["state"] == "signed", standing
    assert standing["identity_state"] == "legacy", standing


# ====================================================================== e 84 定格
def test_e_the_84_manuscripts_read_as_legacy_blocks() -> None:
    """84 的两份真稿里那两块都是旧 8 格 ⇒ `legacy`（只读，不改它们）。"""
    if not PROJ84.is_dir():
        return
    for name, sid in (("f-proof-000000.md", "000000"), ("f-proof-000001.md", "000001")):
        rel = f"reports/{name}"
        text = (PROJ84 / rel).read_text(encoding="utf-8")
        reading = VS.manuscript_sign_reading(text, manuscript_path=rel)
        assert reading["found"] is True, reading
        assert reading["identity_state"] == "legacy", (name, reading)
        assert reading["manuscript_id"] == "", (name, reading)
        assert VS.manuscript_id_of(rel) == sid, rel
