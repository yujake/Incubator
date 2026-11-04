# -*- coding: utf-8 -*-
"""判据（⑥-2）：正常夹具的"先签后登记"必须落一份真手稿；不落盘只许叫 legacy。

业主 2026-11-04 裁定：正常夹具必须写一份真手稿文件（`reports/f-proof-<号>.md`
或 `reports/f-proof-pending-<sha>.md`）；"不落盘也能签"的夹具只许以
`sign_before_registration_legacy` 这种名字里带 legacy 的形式存在，并在文件头写清
这是旧形态、只用于测历史行读法。

三条判据：
| # | 判什么 | 反真空 |
|---|---|---|
| a | 正常夹具调用后盘上真有一份 `reports/*.md`，且 `## 证明` 就是那一份正文 | 改回"只写 object_path" ⇒ a 必红 |
| b | legacy 夹具名字里必须有 `legacy`，且它一个文件都不落 | 把 legacy 实现改名成正常名 ⇒ b 必红 |
| c | 正常夹具的 pending 行 `object_path` 指向那份真文件 | 指向不存在的路径 ⇒ c 必红 |
"""
from __future__ import annotations

import pathlib

import conftest as C
from agentflow.store import Store


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _reports(st: Store) -> list[pathlib.Path]:
    base = pathlib.Path(str(st.root)) / "reports"
    return sorted(base.glob("*.md")) if base.is_dir() else []


def test_a_normal_fixture_writes_a_real_manuscript(tmp_path):
    st = _ws(tmp_path)
    text = "证明（夹具）：由定义直接得到。∎"
    got = C.sign_before_registration(st.root, proof_text=text)
    files = _reports(st)
    assert files, "正常夹具一个手稿文件都没落（还是旧的不落盘形态）"
    content = files[0].read_text(encoding="utf-8")
    assert "## 证明" in content and text in content, content
    # c：pending 行必须指向这份真文件。
    path = str(got.get("object_path") or "")
    assert path, got
    assert (pathlib.Path(str(st.root)) / path).is_file(), (path, files)


def test_b_legacy_fixture_is_named_legacy_and_writes_nothing(tmp_path):
    st = _ws(tmp_path)
    assert "legacy" in C.sign_before_registration_legacy.__name__
    C.sign_before_registration_legacy(st.root, proof_text="证明（夹具）：旧形态。∎")
    assert _reports(st) == [], [str(p) for p in _reports(st)]
