# -*- coding: utf-8 -*-
"""判据：多证明的手稿名把「稿号」与「证明号」分开（2026-11-04 业主裁定）。

## 为什么要有这一条

改前 `vsigns.manuscript_id_of` 只认 `*-proof-<号>.md` 的末段：

- `reports/f-proof-000000-p2.md` ⇒ 裸稿号被读成 `000000-p2`；
- B 的签块闸拿这个号去 `statements` 里找，永远对不上 ⇒ 第 2 份证明的签
  「签了也认不了」。

裁定给的显式规则：`<prefix>-proof-<号>[-p<N>].md` ⇒ `(号, proof_no=N)`；
缺省 `N=1`；认不出号就受控拒绝（`bad_manuscript_name`），不许猜。

## 判据

| # | 输入 | 期望 |
|---|---|---|
| a | `reports/f-proof-000000-p2.md` | 稿号 `000000`、证明号 `2`（`manuscript_id_of` 也只回 `000000`） |
| b | `reports/f-proof-000000.md` | 稿号 `000000`、证明号 `1` |
| c | `reports/f-proof-abc.md` | `checked=False, code=bad_manuscript_name`；`vsigns.land` 也拒（零字节，稿上不长块） |
| d | 反真空：把 `-p<N>` 那一段从正则里摘掉 | a 必须红（`000000-p2` 不再是合法号） |

零模型调用、全部 tmp 工作区。
"""
from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import verifications as VR  # noqa: E402
from agentflow import vsigns as VS  # noqa: E402


def test_a_p2_manuscript_splits_id_and_proof_no() -> None:
    """a：`f-proof-000000-p2.md` ⇒ (000000, 2)；第 9 格只拿稿号。"""
    rel = "reports/f-proof-000000-p2.md"
    parsed = VS.parse_manuscript_name(rel)
    assert parsed["checked"] is True and parsed["family"] is True, parsed
    assert parsed["manuscript_id"] == "000000", parsed
    assert parsed["proof_no"] == 2, parsed
    assert VS.manuscript_id_of(rel) == "000000", VS.manuscript_id_of(rel)
    assert VS.manuscript_proof_no_of(rel) == 2, VS.manuscript_proof_no_of(rel)


def test_b_a_plain_manuscript_is_proof_no_one() -> None:
    """b：没有 `-pN` 后缀 ⇒ 证明号 1（canonical），不是 0。"""
    for rel in ("reports/f-proof-000000.md", "reports/b-proof-000000.md",
                "reports/e-proof-000001.md", "reports/f-proof-plan-0001.md"):
        parsed = VS.parse_manuscript_name(rel)
        assert parsed["checked"] is True and parsed["family"] is True, (rel, parsed)
        assert parsed["proof_no"] == 1, (rel, parsed)


def test_c_an_unparsable_proof_manuscript_name_is_refused() -> None:
    """c：像证明手稿、号却认不出 ⇒ 受控码；`land` 也拒、一个字节都不写。"""
    rel = "reports/f-proof-abc.md"
    parsed = VS.parse_manuscript_name(rel)
    assert parsed["checked"] is False, parsed
    assert parsed["family"] is True, parsed
    assert parsed["code"] == VS.MANUSCRIPT_NAME_BAD, parsed

    # `land` 那一层：签文件在、收方在，但稿名认不出 ⇒ 不落块。
    root = pathlib.Path(__import__("tempfile").mkdtemp(prefix="manuscript-name-"))
    body = "1. 由定义直接得到。"
    issued = VS.issue(root, artifact_sha=VR.proof_sha(body), streak=3, need=3,
                      artifact_path=rel, by="secretary:F")
    assert issued.get("written") is True, issued
    landed = VS.land(root, artifact_sha=VR.proof_sha(body), by="secretary:F",
                     manuscript_path=rel)
    assert landed.get("landed") is False, landed
    assert landed.get("code") == VS.MANUSCRIPT_NAME_BAD, landed
    assert not (root / rel).exists(), "稿名认不出却写了文件"


def test_d_without_the_pn_rule_the_p2_name_is_no_longer_valid(monkeypatch) -> None:
    """d 反真空：正则里摘掉 `-p<N>` 那一段 ⇒ a 那个名字立刻不再合法。"""
    import re

    legacy = re.compile(r"^(?P<prefix>.*?)-proof-(?P<id>\d{4,6}|plan-\d+)$")
    monkeypatch.setattr(VS, "_MANUSCRIPT_NAME_RE", legacy)
    parsed = VS.parse_manuscript_name("reports/f-proof-000000-p2.md")
    assert parsed["checked"] is False, (
        "把 `-p<N>` 那一段摘掉之后 `f-proof-000000-p2.md` 仍然解析成功 ⇒ "
        "a 那条绿不是由 pN 规则给的", parsed)
    assert parsed["manuscript_id"] == "", parsed
    assert parsed["code"] == VS.MANUSCRIPT_NAME_BAD, parsed
