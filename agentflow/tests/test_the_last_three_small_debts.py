# -*- coding: utf-8 -*-
"""三处小账：F 的档位探针、读侧的证明号折平、注释里的装饰（R009）。

## 这一份钉的是什么（业主 2026-10-22 收尾的三笔）

| 判据 | 改前红在哪（`git archive HEAD` 整树副本里实跑） |
|---|---|
| ① `#p1` 未签、`#p2` 已签 ⇒ `_proof_tier` 给 `proof_review` | 交给 `proof_review_gap` 的探针行只有 `stmt_id` / `proof_text` / `evidence_kind`，看不见行 JSON 的 `proofs` 清单 ⇒ 只落 `heuristic` |
| ② 一份都没签 ⇒ 仍是 `heuristic` | 负控：①不许靠"永远给强档"过。改前也绿，所以它与①同处一个函数：①红 ⇒ 整条红 |
| ③ `proof_no='abc'` ⇒ 读侧不按 `#p1` 读 | 三处读口都写 `as_proof_no(x) or 1`：坏号被静默折成 canonical |
| ④ 证明号缺失（参数没给 / `None` / 老行没有这一格）⇒ 仍按 `#p1` 读 | 正控：向后兼容不许破。与③同处一个函数 |
| ⑤ 那位新测试文件的注释/docstring 里没有 R009 装饰 | 该文件不在 HEAD 上（`git archive` 里没有它）⇒ 文件都不在，判据红 |

## 判据本体不在这里

- ①②读的是 `verifications.proof_review_gap`（"任一份 signed"的唯一读法，见
  `verifications.statement_review_reading`）；这一份只断言 F 的档位与写入期那道闸给出
  同一个答案 —— 改前它们给出两个答案，而差的那一个正好是"论文的强度声明"。
- ③④读的是 `verifications` 的三个读口（`proof_text_of` / `proof_label` /
  `review_standing`）；认不出与缺失是两档，不许折平。
- ⑤读的是 `scripts/lint_rules.py` 的 R009 扫描器（判据本体，这一份不复制一份判据）。

## 环境

全部 tmp 工作区、零模型调用（V 的签名走它的写入口 `record_verification`，不经模型），
不读写 `projects/`；`git status -- projects/` 为空。
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

# 与 `tests/conftest.py` 同一个注入方式（这一份也要能在一棵临时源码树上单独跑：
# "改前红"就是把 `git archive HEAD` 的旧文件铺到临时树里、再把这一份放进去跑）。
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import schema as S  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_f import AgentF  # noqa: E402
from agentflow.store import Store  # noqa: E402

#: 一条定理的两份证明：`#p1` 是 canonical（落 `proof_text`），`#p2` 落行 JSON 的清单。
P1 = "1. 由定义直接得到。\n2. 由 1 与假设 n ≥ 3 得结论。"
P2 = "另一条路线：\n1. 先证引理。\n2. 由引理得结论。"

#: 自产命题的两件式（定理内容 + 出处理由是这个写入口的硬要求）。
#:
#: 2026-10-22（业主裁定 B-2「没有引文 / 自己编的命题必须从『猜想』注册」）：加了
#: `kind="conjecture"` —— 这一组测的是多证明的档位读数（`#p2` 签了没有），与入口
#: 声明成哪一种 kind 无关。
_OWN = {
    "statement_full": "设 G 是 3-正则群；则弦长函数不是常值。",
    "statement_text": "弦长函数不是常值",
    "origin": "own_result",
    "kind": "conjecture",
    "doc_id": S.format_id(0),
    "quote_reason": "我方自产命题，没有外部引文要比对",
}
_OK = {"verdict": "成立", "findings": []}


# ------------------------------------------------------------------ 小工具

def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _register(store: Store) -> str:
    """登记一条带两份证明的命题，返回命题号（`#p1` 在 `proof_text`，`#p2` 在清单里）。"""
    out = AgentB(store, extractor=None, extract_text=None, config={}).register_statement(
        **_OWN, proofs=[{"proof_no": 1, "text": P1}, {"proof_no": 2, "text": P2}])
    assert out["ok"] is True, out
    sid = str(store.rows("statements")[0]["stmt_id"])
    # 夹具自证：两份证明都在行上（否则 ① 的"#p2 已签"没有落脚点）。
    assert [no for no, _ in VR.proof_list(dict(store.rows("statements")[0]))] == [1, 2]
    return sid


def _sign(store: Store, sid: str, text: str, proof_no: int) -> dict:
    """V 的签名写入口（`verify_proof` 走的就是它；这里不经模型）。"""
    return VR.record_verification(
        store.root, statement_id=sid, proof_text=text, verdict=dict(_OK),
        verifier="agent-V", store=store, proof_no=proof_no)


def _tier(store: Store, sid: str, text: str) -> dict:
    """F 的档位读数（这一份只读它，不改任何东西）。"""
    return AgentF(store, config={"workspace_root": store.root})._proof_tier(sid, text)


# ============================================================ ① / ② F 的档位

def test_a_signed_second_proof_is_reviewed_and_nothing_signed_stays_heuristic(
        tmp_path: pathlib.Path) -> None:
    """① 正控：`#p1` 未签、`#p2` 已签 ⇒ `proof_review`；② 负控：一份都没签 ⇒ `heuristic`。

    改前（HEAD）红在 ①：`_proof_tier` 交给 `proof_review_gap` 的是一张只有三格的探针行，
    读侧只看得见 canonical 那一份 ⇒ 同一条命题在写入期闸（`proof_review_gaps` 的"任一份
    signed"）与 F 的档位上给出两个答案，而 F 这一侧是更弱的那一个。
    """
    # ---- ① 正控：canonical 未签、#p2 已签
    signed = _ws(tmp_path / "signed_p2")
    sid = _register(signed)
    _sign(signed, sid, P2, 2)
    tier = _tier(signed, sid, P1)
    assert tier["kind"] == VR.PROOF_REVIEW_KIND, (
        f"`#p2` 已签，F 这一侧却落 {tier['kind']!r}（读数：{tier['why']}）")
    assert tier["checked"] is True, tier
    assert tier["gap"].get("state") == "signed", tier["gap"]
    assert tier["gap"].get("proof_no") == 2, tier["gap"]
    # 只看 canonical 的读数是"没签过" —— 这正是改前 F 读到的那个答案，差别就在这一格。
    canon = VR.review_standing(signed.root, statement_id=sid, proof_text=P1, proof_no=1)
    assert canon["checked"] is True and canon["state"] == "unsigned", canon
    # 判据只有一处：写入期那道闸对同一行判"够"。两个答案必须一致（改前它们不一致）。
    row = dict(signed.rows("statements")[0])
    probe = dict(row, evidence_kind=VR.PROOF_REVIEW_KIND)
    assert VR.proof_review_gaps(signed.root, [probe]) == [], (
        "闸门判「够」而 F 判弱档（或反过来）⇒ 判据有两处")

    # ---- ② 负控：一份都没签 ⇒ heuristic（档位不是恒强）
    fresh = _ws(tmp_path / "nothing_signed")
    sid2 = _register(fresh)
    tier2 = _tier(fresh, sid2, P1)
    assert tier2["kind"] == "heuristic", f"一份都没签却落了 {tier2['kind']!r}：{tier2}"
    assert tier2["checked"] is True, tier2
    assert tier2["gap"].get("ok") is False, tier2["gap"]


# ============================================================ ③ / ④ 读侧的证明号

def test_an_unreadable_proof_number_is_not_folded_and_a_missing_one_still_is_p1(
        tmp_path: pathlib.Path) -> None:
    """③ 认不出 ⇒ 0（不按 `#p1` 读）；④ 缺失 ⇒ 仍按 `#p1` 读（向后兼容不许破）。

    改前（HEAD）红在 ③：三个读口都写 `as_proof_no(x) or 1`，于是 `'abc'` / `0` 这类
    "这不是一个证明号"的值被读成 canonical —— `proof_text_of(row, 'abc')` 端出的是
    `#p1` 的正文，`proof_label` 写的是 `#p1`，读数里看不出"号给错了"。
    """
    st = _ws(tmp_path / "read_side")
    sid = _register(st)
    row = dict(st.rows("statements")[0])

    # ---- ③ 认不出（三处读口各判一次）
    assert VR.proof_text_of(row, "abc") != P1, (
        "认不出的证明号被读成了 canonical ⇒ 坏号拿到的是 #p1 的正文")
    assert VR.proof_text_of(row, "abc") == "", VR.proof_text_of(row, "abc")
    assert VR.proof_text_of(row, 0) == "", VR.proof_text_of(row, 0)
    label = VR.proof_label(sid, "abc")
    assert "认不出" in label, f"读数里看不出这个号认不出：{label}"
    assert "#p1" not in label, f"坏号被写成了 #p1：{label}"
    bad = VR.review_standing(st.root, statement_id=sid, proof_text=P1, proof_no="abc")
    assert bad["checked"] is False, f"号认不出被报成了「查过了」：{bad}"
    assert bad["state"] == "unreadable", bad
    assert bad["ok"] is False and bad["proof_no"] == 0, bad
    assert "认不出" in bad["why"], bad["why"]

    # ---- ④ 缺失那一档（正控：老调用方一个字都不用改）
    assert VR.proof_text_of(row) == P1, "参数没给时不再按 #p1 读了（向后兼容破了）"
    assert VR.proof_text_of(row, None) == P1
    assert VR.proof_text_of(row, 1) == P1 and VR.proof_text_of(row, 2) == P2
    assert VR.proof_label(sid) == f"{sid}#p1", VR.proof_label(sid)
    assert VR.proof_label(sid, None) == f"{sid}#p1", VR.proof_label(sid, None)
    assert VR.proof_label(sid, 2) == f"{sid}#p2", VR.proof_label(sid, 2)

    # 老签名行（没有 `proof_no` 这一格，只有 `statement_id`）：读侧仍按 #p1 认。
    legacy = _ws(tmp_path / "legacy_row")
    sid2 = _register(legacy)
    path = VR.verification_ledger_path(legacy.root, sid2)
    path.parent.mkdir(parents=True, exist_ok=True)
    old_row = {
        "verification_id": "v-0001", "statement_id": sid2, "verifier": "V",
        "verdict": "成立", "defect_step": None, "quote": "", "why": "",
        "findings": [], "unresolved_errors": 0,
        "proof_sha256": VR.proof_sha(P1), "proof_chars": len(P1),
        "round": 1, "used_faces": [], "submission_id": "",
        "at": "2026-01-01T00:00:00+00:00",
    }
    assert "proof_no" not in old_row, "这一条判的就是「行上没有这一格」"
    path.write_text(json.dumps(old_row, ensure_ascii=False) + "\n", encoding="utf-8")
    assert VR.proof_no_of(old_row) == 1, "老行的证明号读不成 #p1"
    got = VR.review_standing(legacy.root, statement_id=sid2, proof_text=P1, proof_no=None)
    assert got["checked"] is True and got["state"] == "signed", got
    assert got["ok"] is True and got["proof_no"] == 1, got


# ============================================================ ⑤ R009

_SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
_TESTS = pathlib.Path(__file__).resolve().parent


def _load_linter():
    """按路径导入 `scripts/lint_rules.py`（`scripts/` 不是包，不能普通 import）。"""
    spec = importlib.util.spec_from_file_location(
        "_lint_rules_for_the_last_three", _SCRIPTS / "lint_rules.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def r009_scan():
    """R009 的扫描器（注释与 docstring 区间 + 其中的装饰）。"""
    return _load_linter()._r009_scan


def test_the_new_two_layer_file_carries_no_decoration_in_its_comments(r009_scan) -> None:
    """⑤ 那位新测试文件的注释/docstring 里没有星号强调或 emoji。

    为什么这条判据对它有信息量：它里面有四颗 `**`，但那是 Python 语法
    （`**overrides` 关键字透传、`{**C.CAPABILITIES, ...}` 字典合并），不是装饰 ——
    谁把它们当装饰"清掉"，谁就把文件改成语法错误。所以这里判两件事：R009 一处也没
    命中，且文件仍然解析得动（四颗星号还在代码里）。

    三态：扫描器一个区间都没读到（`regions == 0`）⇒ 这一条报"没查成"，不许当成干净。
    """
    path = _TESTS / "test_two_layer_constraints_really_match.py"
    assert path.is_file(), (
        f"{path.name} 不见了 ⇒ 这一条没有对象（改前红：HEAD 上确实没有这个文件）")
    text = path.read_text(encoding="utf-8")
    found, regions = r009_scan(text)
    assert regions > 0, (
        "R009 扫描器没读到任何注释/docstring 区间 ⇒ 这一次没查成（不是「干净」）")
    assert found == [], f"R009 命中：{found}"
    # 反真空：它不是一棵"没有注释所以没命中"的文件，也没有被"清"成语法错误。
    assert "**" in text, "四颗星号（Python 语法）不见了：是不是被当装饰清掉了？"
    compile(text, str(path), "exec")
