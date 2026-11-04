# -*- coding: utf-8 -*-
"""判据 C-③：E 的提示词说清「V 签的真凭据是 V 台账那一行」，并点名 `proof_manuscript`。

## 业主裁定（2026-11-04 ③，口径见 `draft/178`）

`specs/e.py` 的三段与实现分家了：

| # | 改前的写法 | 实现里的真身 |
|---|---|---|
| 1 | 「三态结论」 | `verifications.VERDICTS` 早已两态（`有毛病` / `成立`） |
| 2 | 「签名者是 V」 | 手稿签块的 `签名者=` 是收方秘书（`vsigns.SECRETARY_OF` 里的 `secretary:E`；`vsigns.land` 的 `by=` 只认那三个） |
| 3 | 「`signed_by=V` 那三格是唯一凭据」 | 真凭据是 V 台账那一行（`verifications/pending/<对象sha>.jsonl` 或 `verifications/<号>.jsonl`）；`observations.e_signature` 只是 E 自己写的结构标记，不算第三方签字（`numericproof.suspect_self_signed` 读的就是它） |

第 3 段还漏了入口那一格：E 送审必须把 `proof_manuscript`（手稿路径）交上去 ——
`agent_v.core._review_unregistered_prose` 的入口守卫只认它；不带它，`verify_proof`
只会把判词落进 pending，稿上永远没有签块。

## 判据怎么判

只钉 E 的渲染提示词（`agent_prompts.system_prompt("E")`）：
- 五条新口径必须出现（两态 / 签名者=收方秘书 / 真凭据是 V 台账那一行 /
  `e_signature` 只是结构标记 / `proof_manuscript` 与「不带它只落 pending」）；
- 四条旧口径一个字都不许留（`三态结论落` / `签名者是 V` / `signed_by=V` /
  `成立的唯一凭据`）。

每条都带反真空：文本长度锚 + 把旧口径塞回去必须当场报出来；另核三条代码真身
（`VERDICTS` 两态、`SECRETARY_OF` 含 `secretary:E`、pending 目录名），
免得判据钉的是一句与实现无关的散文。
"""
from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import agent_prompts as AP  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow import vsigns as VS  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402


#: 新口径必须出现在 E 的提示词里的那几句（每一句都对着实现里的一个名字）。
NEEDLES: tuple[str, ...] = (
    "两态结论（成立 / 有毛病）",
    "签名者=收方秘书（`secretary:E`）",
    "真凭据是 **V 台账那一行**",
    "verifications/pending/<对象sha>.jsonl",
    "observations.e_signature",
    "结构标记",
    "proof_manuscript",
    "不带它只会落 pending",
    "稿上永远没有签块",
)

#: 旧口径的判别式：改后一个字都不许留（不再是"凭据"的说法）。
GONE: tuple[str, ...] = (
    "三态结论落",
    "签名者是 V",
    "signed_by=V",
    "成立的唯一凭据",
)


def _e_prompt() -> str:
    """E 的渲染提示词（`specs/e.py` 的 brief 六格 + 索引）。"""
    return AP.system_prompt("E", registry=build_registry().registry)


def _problems(text: str) -> list[str]:
    """缺哪几条 / 旧口径还剩哪几条（空清单 = 这一格干净）。"""
    bad: list[str] = []
    for needle in NEEDLES:
        if needle not in text:
            bad.append(f"E 的提示词里缺 {needle!r}")
    for old in GONE:
        if old in text:
            bad.append(f"旧口径 {old!r} 还在 E 的提示词里")
    return bad


def test_e_prompt_names_the_v_ledger_row_as_the_true_credential() -> None:
    """正控：E 的提示词写清两态、收方秘书、V 台账那一行与 `proof_manuscript`。"""
    # 代码真身先核一遍：判据钉的那几句若在实现里不成立，就是判据自己在说谎。
    assert VR.VERDICTS == ("有毛病", "成立"), VR.VERDICTS
    assert "secretary:E" in VS.SECRETARY_OF, VS.SECRETARY_OF
    assert VR.PENDING_DIR_NAME == "pending", VR.PENDING_DIR_NAME

    text = _e_prompt()
    assert len(text) > 5000, len(text)      # 反真空①：真的是那一份渲染提示词

    bad = _problems(text)
    assert bad == [], "\n".join(bad)


def test_putting_the_old_sentences_back_makes_it_red() -> None:
    """反真空②：把改前那三句塞回同一份文本 ⇒ 同一个算式必须当场报出来。"""
    text = _e_prompt()
    old = ("\n- 再请 V 用 `verify_proof` 逐行走查 —— 三态结论落 "
           "`verifications/<命题号>.jsonl`，是这一档唯一的「审过」凭据。"
           "你这一岗产 `proof` 档只有一条路：穷举（签名者是 V）。"
           "\n- 那一签（`signed_by=V`、`proof_authors` 含 E）是这份证明成立的唯一凭据。")
    hit = _problems(text + old)
    assert hit, "把旧口径塞回去之后判据没报 ⇒ 它只量了『文本很长』"
    for old_fragment in GONE:
        assert any(old_fragment in x for x in hit), (old_fragment, hit)
