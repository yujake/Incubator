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

from agentflow import manuscriptfamily as MFAM  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow import vsigns as VS  # noqa: E402


def test_a_p2_manuscript_splits_id_and_proof_no() -> None:
    """a：`f-proof-000000-p2.md` ⇒ (000000, 2)；第 9 格只拿稿号。"""
    rel = "reports/f-proof-000000-p2.md"
    parsed = VS.parse_manuscript_name(rel)
    assert parsed["checked"] is True and parsed["family"] == "f-proof", parsed
    assert parsed["is_family"] is True, parsed
    assert parsed["manuscript_id"] == "000000", parsed
    assert parsed["proof_no"] == 2, parsed
    assert VS.manuscript_id_of(rel) == "000000", VS.manuscript_id_of(rel)
    assert VS.manuscript_proof_no_of(rel) == 2, VS.manuscript_proof_no_of(rel)


def test_b_a_plain_manuscript_is_proof_no_one() -> None:
    """b：没有 `-pN` 后缀 ⇒ 证明号 1（canonical），不是 0。"""
    for rel, family in (("reports/f-proof-000000.md", "f-proof"),
                        ("reports/b-proof-000000.md", "b-proof"),
                        ("reports/e-proof-000001.md", "e-proof"),
                        ("reports/f-proof-plan-0001.md", "f-proof")):
        parsed = VS.parse_manuscript_name(rel)
        assert parsed["checked"] is True and parsed["family"] == family, (rel, parsed)
        assert parsed["proof_no"] == 1, (rel, parsed)


def test_c_an_unparsable_proof_manuscript_name_is_refused() -> None:
    """c：像证明手稿、号却认不出 ⇒ 受控码；`land` 也拒、一个字节都不写。"""
    rel = "reports/f-proof-abc.md"
    parsed = VS.parse_manuscript_name(rel)
    assert parsed["checked"] is False, parsed
    # 四族名字形状仍在（旧读法的 `family=True` 那一档；新读法把它拆成 `is_family`），
    # 但 `tier=bad_name`、族名不成立 —— 受控拒靠的是后面这两格。
    assert parsed["is_family"] is True, parsed
    assert parsed["tier"] == MFAM.TIER_BAD, parsed
    assert parsed["family"] == "", parsed
    assert parsed["code"] == VS.MANUSCRIPT_NAME_BAD, parsed

    # `land` 那一层：签文件在、收方在，但稿名认不出 ⇒ 不落块。
    root = pathlib.Path(__import__("tempfile").mkdtemp(prefix="manuscript-name-"))
    body = "1. 由定义直接得到。"
    # 2026-11-05 晚（业主）：签必须有独立台账背书 —— `issue` 的 `ledger` 指的
    # `verifications/000000.jsonl#v-000003` 那一行要真的在盘上（这里只造这一行）。
    for _ in range(3):
        VR.record_verification(str(root), statement_id="000000", proof_text=body,
                               verdict={"verdict": "成立", "findings": []},
                               verifier="agent-V", flip=False, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
    issued = VS.issue(root, artifact_sha=VR.text_sha(body), streak=3, need=3,
                      artifact_path=rel,
                      ledger="verifications/000000.jsonl#v-000003",
                      statement_id="000000",
                      # 2026-11-05：签的三道必填闸要求 `passes` 逐转带读数。
                      passes=[{"verification_id": f"v-{i:06d}", "at": "t",
                               "proof_sha256": VR.text_sha(body), "why": "夹具"}
                              for i in (1, 2, 3)],
                      by="secretary:F")
    assert issued.get("written") is True, issued
    landed = VS.land(root, artifact_sha=VR.text_sha(body), by="secretary:F",
                     manuscript_path=rel)
    assert landed.get("landed") is False, landed
    assert landed.get("code") == VS.MANUSCRIPT_NAME_BAD, landed
    assert not (root / rel).exists(), "稿名认不出却写了文件"


def test_e_a_v2_manuscript_is_history_not_a_second_proof() -> None:
    """e：`-v2` 读成 `legacy`（`proof_no=0`），不是 `-p2`、也不是受控拒。

    2026-11-09（T2）：这是收编后翻过来的一格（设计 3.2 第 4 处 / §3.3）。
    `manuscript_id_of` 仍读得出号（纯读兼容），但"它不能当第 N 份证明"由
    `proof_no=0` 表达；签载体另判。
    """
    rel = "notes/b-proof-000003-v2.md"
    parsed = VS.parse_manuscript_name(rel)
    assert parsed["checked"] is True, parsed
    assert parsed["tier"] == MFAM.TIER_LEGACY, parsed
    assert parsed["family"] == MFAM.LEGACY_FAMILY, parsed
    assert parsed["proof_no"] == 0, parsed
    assert parsed["code"] == MFAM.CODE_LEGACY, parsed
    assert parsed["canonical"] == "reports/b-proof-000003-p2.md", parsed
    assert VS.manuscript_id_of(rel) == "000003", VS.manuscript_id_of(rel)

    carrier = VS.sign_carrier_reading(rel)
    assert carrier["ok"] is False, carrier
    assert carrier["code"] == MFAM.CODE_LEGACY, carrier


def test_f_e_num_is_a_family_but_not_a_sign_carrier() -> None:
    """f：`e-num-*` 进族（旧 `family=False`），但绿色通道不收签。"""
    rel = "reports/e-num-000012.md"
    parsed = VS.parse_manuscript_name(rel)
    assert parsed["checked"] is True and parsed["family"] == "e-num", parsed
    assert parsed["manuscript_id"] == "000012", parsed
    assert parsed["proof_no"] == 1, parsed
    carrier = VS.sign_carrier_reading(rel)
    assert carrier["ok"] is False, carrier
    assert carrier["code"] == MFAM.CODE_NUMERIC_NOT_SIGN, carrier


def test_g_a_handwritten_name_in_notes_is_legacy_by_directory() -> None:
    """g：`notes/` 下的手稿形名字读成 `legacy`（目录是身份的一部分）。

    同一个名字在 `reports/` 下是 b-proof 族；换到 `notes/` 就是历史档（不可签、
    不可收录）。这是设计 3.1.1 第 1 条；旧读法只看名字，会把它认成正式族。
    """
    canonical = "reports/b-proof-000003.md"
    in_notes = "notes/b-proof-000003.md"
    formal = VS.parse_manuscript_name(canonical)
    legacy = VS.parse_manuscript_name(in_notes)
    assert formal["tier"] == MFAM.TIER_FAMILY and formal["family"] == "b-proof", formal
    assert legacy["tier"] == MFAM.TIER_LEGACY, legacy
    assert legacy["family"] == MFAM.LEGACY_FAMILY, legacy
    assert legacy["proof_no"] == 0, legacy
    assert legacy["canonical"] == canonical, legacy
    assert VS.sign_carrier_reading(in_notes)["ok"] is False, in_notes


def test_d_without_the_pn_rule_the_p2_name_is_no_longer_valid(monkeypatch) -> None:
    """d 反真空：表里摘掉 `-p<N>` 那一段 ⇒ a 那个名字立刻不再合法。

    2026-11-09（T2 收编）：解析已改读 `manuscriptfamily` 那张表，所以反真空打在
    表本体的号形正则上（f-proof 那一支是 `_PROOF_REST_RE`），不再打在 `vsigns` 的
    旧正则上。
    """
    import re

    legacy = re.compile(r"^(?P<id>\d{4,6}|plan-\d+)$")
    monkeypatch.setattr(MFAM, "_PROOF_REST_RE", legacy)
    parsed = VS.parse_manuscript_name("reports/f-proof-000000-p2.md")
    assert parsed["checked"] is False, (
        "把 `-p<N>` 那一段摘掉之后 `f-proof-000000-p2.md` 仍然解析成功 ⇒ "
        "a 那条绿不是由 pN 规则给的", parsed)
    assert parsed["manuscript_id"] == "", parsed
    assert parsed["code"] == VS.MANUSCRIPT_NAME_BAD, parsed
