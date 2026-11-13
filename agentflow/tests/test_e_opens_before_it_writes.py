# -*- coding: utf-8 -*-
"""E 的开稿接线（2026-11-13 业主裁定 · 统一四步的 E 接线）。

业主口径（逐字）：

> 「统一 B、E、F 注册稿和写稿的流程：写命题 → 命题形式过审 → 拿稿号 → 写稿
> （稿允许慢慢 edit，不必一次成稿）」

## 这个文件钉什么（E 这一族）

| 编号 | 判据 | 用例 |
|---|---|---|
| a | 闸判不过 ⇒ 零字节、号源不动、受控拒写进 `problems`（不抛） | `test_a_*` |
| b | 闸判过 ⇒ 写正文那一刻盘上已经有骨架（`## 命题` 在、分节空） | `test_b_*` |
| c | 同一条实验重落 ⇒ 同一份稿、一个稿号（不新开第二份） | `test_c_*` |
| d | `e-num` 也走开稿口（已有 `## 数值结果` 的族也要有骨架） | `test_d_*` |
| f | 反真空：把开稿口打桩成失败 ⇒ b 红（没有骨架、没有稿） | `test_f_*` |

## 为什么 E 的闸读数要传进来

E 的形态闸在 `run_experiment` 的 [4e]（`store.tx` 之前、写实验行/稿之前）。开稿口
`manuscriptopen.open_manuscript` 拿到的是那份读数的副本（`form_reading=`）—— 判据还是
同一处 `Secretary.judge_proposition_form`，不重复问模型、也不重复写形态台账。
"""
from __future__ import annotations

import pathlib

from agentflow import exhaustionreport as ER
from agentflow import manuscriptids as MID
from agentflow import manuscriptopen as MO

FACTS = {
    "experiment_id": "000001", "claim": "设 n 为偶数；则 n 是偶数。", "claim_key": "k1",
    "script_path": "x.py", "script_sha256": "0" * 64,
    "design": {"方法": "逐项枚举"}, "enumeration": ["n=2", "n=4"],
    "search_space": {"上界": 10}, "result": "ok", "evidence_kind": "proof",
    "kind": "theorem",
}


def _root(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _ok(**kw) -> dict:
    return {"checked": True, "well_formed": True, "submittable": True,
            "problems": [], "refused": "", "reason": "夹具：形态合规"}


def _bad(**kw) -> dict:
    return {"checked": True, "well_formed": False, "submittable": False,
            "problems": ["不是从条件导出结论的数学命题"],
            "refused": "proposition_form_refused", "reason": "夹具：形态不合规"}


def _files(root: pathlib.Path, family: str) -> list[pathlib.Path]:
    base = root / "reports"
    prefix = "e-proof-" if family == "e-proof" else "e-num-"
    return sorted(base.glob(f"{prefix}*.md")) if base.is_dir() else []


def _section(text: str, name: str) -> str:
    lines = str(text).splitlines()
    for i, line in enumerate(lines):
        if line.strip() == f"## {name}":
            out: list[str] = []
            for nxt in lines[i + 1:]:
                if nxt.startswith("## "):
                    break
                out.append(nxt)
            return "\n".join(out).strip()
    return ""


# ---------------------------------------------------------------- a：闸在前
def test_a_a_bad_gate_reading_lands_nothing_and_keeps_the_counter(
        tmp_path: pathlib.Path) -> None:
    """闸判不过 ⇒ 不落稿、号源不动、受控拒在 `problems` 里（E 的写口不抛异常）。"""
    root = _root(tmp_path)
    out = ER.land_manuscript(root, form_reading=_bad(), **FACTS)
    assert out["ok"] is False, out
    assert out["path"] == "" and out["manuscript_id"] == "", out
    assert any("proposition_form_refused" in str(p) for p in out["problems"]), out
    assert _files(root, "e-proof") == [], "闸判不过 ⇒ 盘上零字节"
    assert MID.peek_manuscript_counter(root, family="e-proof") == 0, "号源一个字节都不动"


# ---------------------------------------------------------------- b：骨架在正文之前
def test_b_the_skeleton_is_on_disk_before_the_proof_is_composed(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """写正文（compose）那一刻：盘上已经有骨架（`## 命题` 在、`## 证明` 还空）。"""
    root = _root(tmp_path)
    seen: dict[str, object] = {}
    real = ER.compose_manuscript

    def _spy(**kw):  # noqa: ANN003 - 探针
        files = _files(root, "e-proof")
        seen["names"] = [p.name for p in files]
        seen["text"] = files[0].read_text(encoding="utf-8") if files else ""
        return real(**kw)

    monkeypatch.setattr(ER, "compose_manuscript", _spy)
    out = ER.land_manuscript(root, form_reading=_ok(), **FACTS)

    assert seen["names"] == ["e-proof-000000.md"], (
        "写正文之前必须先有骨架（开稿口在正文写口之前）", seen["names"])
    assert _section(str(seen["text"]), "命题").strip() == FACTS["claim"]
    assert _section(str(seen["text"]), "证明").strip() == "", "那一刻 `## 证明` 还是空的"
    assert out["ok"] is True, out
    text = (root / out["path"]).read_text(encoding="utf-8")
    assert _section(text, "命题").strip() == FACTS["claim"]
    assert "n=2" in _section(text, "证明"), "正文（穷举论证）写进去了"
    assert "- 实验号：exp:000001" in text, "稿头那一行要留住（重落时靠它找回这份稿）"
    assert out["proof_sha256"], out


# ---------------------------------------------------------------- c：重落同一份
def test_c_relanding_the_same_experiment_reuses_the_same_manuscript(
        tmp_path: pathlib.Path) -> None:
    """同一条实验重落 ⇒ 同一个稿号、盘上一份稿（find_manuscript_relpath 按稿头找回）。"""
    root = _root(tmp_path)
    first = ER.land_manuscript(root, form_reading=_ok(), **FACTS)
    second = ER.land_manuscript(root, form_reading=_ok(), **FACTS)
    assert first["ok"] and second["ok"], (first, second)
    assert first["path"] == second["path"], (first["path"], second["path"])
    assert first["manuscript_id"] == second["manuscript_id"], (first, second)
    assert [p.name for p in _files(root, "e-proof")] == ["e-proof-000000.md"]


# ---------------------------------------------------------------- d：e-num 也开稿
def test_d_numeric_manuscript_also_opens_a_skeleton(tmp_path: pathlib.Path,
                                                    monkeypatch) -> None:
    """`e-num` 也走开稿口：骨架有 `## 命题` + 空的 `## 数值结果`，号走自家号段。"""
    root = _root(tmp_path)
    seen: dict[str, object] = {}
    real = ER.compose_numeric_manuscript

    def _spy(**kw):  # noqa: ANN003 - 探针
        files = _files(root, "e-num")
        seen["names"] = [p.name for p in files]
        seen["text"] = files[0].read_text(encoding="utf-8") if files else ""
        return real(**kw)

    monkeypatch.setattr(ER, "compose_numeric_manuscript", _spy)
    out = ER.land_numeric_manuscript(root, form_reading=None,
                                     **{**FACTS, "experiment_id": "000002",
                                        "claim": "数值命题：n 增大时比值趋近 1。",
                                        "evidence_kind": "cross_check"})
    assert seen["names"] == ["e-num-000000.md"], seen["names"]
    assert _section(str(seen["text"]), "命题").strip().startswith("数值命题")
    assert _section(str(seen["text"]), "数值结果").strip() == ""
    assert out["ok"] is True, out
    text = (root / out["path"]).read_text(encoding="utf-8")
    assert _section(text, "数值结果").strip(), "数值结果那一节写进去了"
    assert _files(root, "e-proof") == [], "两族各记各的号（e-num 不碰 e-proof 号段）"


# ---------------------------------------------------------------- f：反真空
def test_f_without_the_open_port_the_skeleton_is_missing(tmp_path: pathlib.Path,
                                                         monkeypatch) -> None:
    """把开稿口打桩成失败 ⇒ b 那一条红（盘上没有骨架、也没有稿）。"""
    root = _root(tmp_path)

    def _no_open(*_a, **_kw):
        return {"ok": False, "refused": "manuscript_id_unavailable",
                "why": "夹具：号源不发号", "path": "", "manuscript_id": "",
                "problems": [], "form": {}}

    monkeypatch.setattr(ER, "_open_skeleton", _no_open)
    out = ER.land_manuscript(root, form_reading=_ok(), **FACTS)
    assert out["ok"] is False and out["path"] == "", out
    assert any("manuscript_id_unavailable" in str(p) for p in out["problems"]), out
    assert _files(root, "e-proof") == [], "开稿口没成 ⇒ 也不许整份写一份没有身份的稿"
