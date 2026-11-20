# -*- coding: utf-8 -*-
"""E9a 判据：`register_statement` 里那句「V 只审在册的命题」已经过期 ⇒ 文案必须改口。

## 为什么这句已经过期（可复算）

| 日期 | 盘上的事实 | 出处 |
|---|---|---|
| 2026-11-02 | 「V 签先放在 F 的手稿里，让 B 录入」 | `agent_v/core.py` 的 `UNREGISTERED_STATEMENT_PAGE` 注释（`git blame` = `6fe67835`） |
| 2026-11-08 | 「V 只对手稿负责」—— 五处 statements 读取下线、签只落稿 | `f0772d4b`（`depsection.manuscript_uncitable_finding` 那一批） |

所以今天的顺序是「V 审手稿（签落在稿上）→ B 在签之后收录」；"V 只审在册的命题"
（它当年成立：`verify_proof` 对不在册的命题直接报 `statement_missing`，那个码
`4967ef82` 2026-10-18 引入）已经不是这条闸的理由。同一句还留在
`agent_v/core.py::_citation_material` 里作三态说明：「`statement_missing` 明确保持
`False` —— V 读不到台账，'不在册'是它没查过的话」。

## 判据钉什么

1. 旧文案（三条逐字）在 `register_statement.py` 里一处都不剩；
2. 新文案在三处都在（两处注释 + 一处运行期 `why` 句子）：V 审的是手稿、签落在稿上，
   在册是 B 在签之后的收录；
3. 运行期那一句（`_self_authored_gate` 对 `kind="conjecture"` 给的 `why`）逐字含新文案
   —— 它是唯一会被模型 / 人读到的那个落点，注释改了它没改等于没改。

反真空：同一个检查器喂一段"旧文案"原文必须报红（不然"旧文案不在"可能只是检查器坏了）。
"""
from __future__ import annotations

import pathlib
import re

from agentflow.agent_b.core import AgentB
from agentflow.store import Store

SRC = (pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"
       / "agent_b" / "register_statement.py")

#: 旧文案（逐字）：① 那句"只审在册"本身；② 它当年的理由句；③ 它引的那个行为。
_OLD_CLAIMS: tuple[str, ...] = (
    "只审在册",
    "先落库才审得动",
    "对不在册的命题直接",
)

#: 新文案（逐字）：V 审的对象是稿、签落稿上；收录在签之后（B 的活）。
#: 比对前把空白折掉（同一句会按行宽折行，折行不是文案差异）。
_NEW_SIGN = "V审的是手稿、签落在稿上"
_NEW_LEDGER = "在册是B在签之后的收录"


def _flat(text: str) -> str:
    return re.sub(r"\s+", "", str(text))


def _expired_claims(text: str) -> list[str]:
    """这段文字里还剩哪些旧文案（空列表 = 一处不剩）。"""
    return [claim for claim in _OLD_CLAIMS if claim in str(text)]


def test_a_the_expired_claim_is_gone_from_the_file() -> None:
    """① 旧文案在 `register_statement.py` 里一处都不剩（注释 + 运行期句子一起算）。"""
    text = SRC.read_text(encoding="utf-8")
    # 反真空：文件读成空串时下面那条"不剩"会假绿 —— 先钉住"读到了东西"。
    assert len(text) > 10_000, f"{SRC} 只读到 {len(text)} 字节 ⇒ 这一条判据在扫空集"
    assert _expired_claims(text) == [], _expired_claims(text)
    # 检查器本身有牙：喂它一段旧文案原文，它必须报得出来。
    stale = ("#   2. `kind=\"conjecture\"` ⇒ 猜想放行（猜想本来就要先落库才审得动："
             "V 只审在册的命题）；\n"
             "    `register_statement` 在写库之前没有号，而 V 只审在册的命题"
             "（`AgentV.verify_proof` 对不在册的命题直接 `statement_missing`）。")
    assert _expired_claims(stale) == list(_OLD_CLAIMS), _expired_claims(stale)


def test_b_the_new_copy_is_written_where_the_old_one_was() -> None:
    """② 新文案写进那几处：V 审的是手稿（签在稿上）+ 在册是 B 在签之后的收录。"""
    text = _flat(SRC.read_text(encoding="utf-8"))
    # 三处文字落点（B-3 的判定顺序 / `_v_signature_for` 的"为什么按正文认命题" /
    # `_self_authored_gate` 的六档说明）+ 运行期那一句 ⇒ 至少 4 次。
    assert text.count(_NEW_SIGN) >= 4, text.count(_NEW_SIGN)
    assert text.count(_NEW_LEDGER) >= 4, text.count(_NEW_LEDGER)


def test_c_the_runtime_reason_says_the_new_thing(tmp_path: pathlib.Path) -> None:
    """③ 运行期那一句（`kind="conjecture"` 的 `why`）逐字含新文案、且没有旧文案。

    这一格是"文案到底改没改"的真正落点：注释读者是开发者，而这一句会被模型与
    人读到 —— 只改注释不改它，读的人照样被告知"V 只审在册的命题"。
    """
    store = Store(tmp_path / "ws")
    store.init()
    agent = AgentB(store, extractor=None, extract_text=None, config={})

    got = agent._self_authored_gate(
        origin="own_result", kind="conjecture", lit_id="",
        statement_full="猜想：这一条按最弱那一档先注册。", proof_text="")

    assert got.get("needs_v") is False, got
    reason = str((got.get("reading") or {}).get("why") or "")
    assert reason, got
    flat = _flat(reason)
    assert _NEW_SIGN in flat, reason
    assert _NEW_LEDGER in flat, reason
    assert _expired_claims(reason) == [], reason
