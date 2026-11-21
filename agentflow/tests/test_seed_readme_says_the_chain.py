# -*- coding: utf-8 -*-
"""判据（SEEDREADME，2026-11-21）：工作区根的 `SEED-README.md` 必须写正确的收编链。

## 改前为什么红

改前 `seedinject._readme_text` 的「怎么用」写着「`search.ingest_local`
（`books_dir="library"`）把盘上文件登记成候选」—— 那是假的：非 dry 档直接
`tx.upsert("literature", …)` 写行、跳过判收。下一趟真机 A 照这份 README 做，
就会把整批种子当成已入库（业主明令：不许直接入库）。同一句还抄在
`seed/literature/README.md` 里 —— 两处不同真身，改一处另一处不会变。

## 判据（a / b 两条，都断言盘上的产物而不是源码串）

| # | 判据 | 反真空 |
|---|---|---|
| a | 真的建一个工作区，读它根上的 `SEED-README.md`：四步按 发现 → 建候选 → 抽读 → 判收 → 提交 的次序写全，且明写「dry_run=True 只发现」与「非 dry 档跳过判收、不要用」 | 把「怎么用」换成改前那句「把盘上文件登记成候选」⇒ a 必红 |
| b | `seed/literature/README.md` 与生成器逐字同一句（同一真身，不许两处不同） | 把那段链从 README 里抠掉 ⇒ b 必红 |

a 的那两格是工作区里 A 真会读到的文件内容（不是只查 `seedinject.py` 的源码串）：
判据走 `projects.create_project(seed_literature=True)` 的真路径，读回来的是落到
盘上的那一份。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentflow import projects as P
from agentflow import seedinject as SI

import test_seed_corpus as TSC

#: 改前那句假话（判据要它「不在」，反真空要把它放回去看 a 变红）。
_OLD_CLAIM = "把盘上文件登记成候选"

#: 「怎么用」那一节的标题（a 只在这一节里读，免得别处的工具名混进顺序）。
_HOWTO_HEAD = "## 怎么用"

#: 这条链的五环。`lit.admit(` 带左括号：`lit.admit_all` 是它的前缀，裸串会把两环读成
#: 同一个位置 —— 那样「判收」与「提交」的顺序就永远成立（假绿）。
_CHAIN: tuple[tuple[str, str], ...] = (
    ("发现", "dry_run=True"),
    ("建候选", "lit.stage_add"),
    ("抽读", "text.extract"),
    ("判收", "lit.admit("),
    ("提交", "lit.admit_all"),
)

#: 两句逐字要求（业主口径）。
_REQUIRED: tuple[str, ...] = (
    "dry_run=True 只发现",
    "非 dry 档跳过判收",
    "不要用",
    # 业主 2026-11-21 的入库白名单：只有用户点名的才可入库，声明真身是这份文件。
    "RELIABLE-REFERENCES.json",
    "只有清单里的才可入库",
    "not_declared_reference",
)

#: 收进 literature 之后那一步（④）。
_NEXT_STEP = "下一步派 B 的 `run_once` 整理"


def _howto_section(text: str) -> str:
    """README 里「怎么用」那一节（到下一个二级标题为止）。"""
    start = text.find(_HOWTO_HEAD)
    if start < 0:
        return ""
    rest = text[start + len(_HOWTO_HEAD):]
    nxt = rest.find("\n## ")
    return _HOWTO_HEAD + (rest if nxt < 0 else rest[:nxt])


def _chain_problems(text: str) -> list[str]:
    """链的问题（空 = 四步写全、按次序、两句禁令都在、且没有改前那句假话）。"""
    problems: list[str] = []
    if _OLD_CLAIM in text:
        problems.append(
            f"还在说「{_OLD_CLAIM}」—— 那是非 dry 档的行为（直接写 literature 行、跳过判收），"
            "下一趟真机 A 照它做就会把种子当已入库")
    for needle in _REQUIRED:
        if needle not in text:
            problems.append(f"没写「{needle}」")
    if _NEXT_STEP not in text:
        problems.append(f"没写收编之后的下一步：{_NEXT_STEP}")
    positions = [(name, text.find(token)) for name, token in _CHAIN]
    missing = [f"缺「{name}」（`{token}`）这一环" for (name, pos), (_n, token)
               in zip(positions, _CHAIN) if pos < 0]
    if missing:
        return problems + missing
    for (prev_name, prev), (name, pos) in zip(positions, positions[1:]):
        if pos <= prev:
            problems.append(f"顺序不对：「{name}」出现在「{prev_name}」之前（或同一处）")
    return problems


def _readme_text_of(project: Path) -> str:
    """工作区根上那份 `SEED-README.md` 的全文（读不到 = 空串，判据会点名）。"""
    marker = project / "SEED-README.md"
    assert marker.is_file(), f"工作区根没有 SEED-README.md：{marker}"
    return marker.read_text(encoding="utf-8")


# ---------------------------------------------------------------- a 生成的产物


def test_a_the_rendered_seed_readme_carries_the_chain(tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """a：建一个真工作区，读根上那份 SEED-README，链按次序写全。"""
    monkeypatch.setenv(SI.ENV_SEED_DIR, str(TSC._seed_package(tmp_path)))
    ref = P.resolve(tmp_path / "projects", "seeded", start="cold")
    P.create_project(ref, seed_literature=True, now="2026-01-01T00:00:00+08:00")

    text = _readme_text_of(ref.path)
    section = _howto_section(text)
    assert section, "SEED-README 里没有「怎么用」那一节（A 读不到这条路）"
    problems = _chain_problems(section)
    assert problems == [], (
        "SEED-README 的「怎么用」不是在写正确的收编链：\n  - " + "\n  - ".join(problems))
    # 反真空：五环真的各在不同的位置（不是五个词恰好挤在同一处被读成有序）。
    positions = [section.find(token) for _name, token in _CHAIN]
    assert len(set(positions)) == len(_CHAIN), positions


def _with_the_old_claim(text: str) -> str:
    """把「怎么用」那一节换成改前那句「把盘上文件登记成候选」（反真空用）。"""
    start = text.find(_HOWTO_HEAD)
    assert start >= 0, "夹具前提：生成的 README 里没有「怎么用」一节"
    rest = text[start + len(_HOWTO_HEAD):]
    nxt = rest.find("\n## ")
    assert nxt >= 0, "夹具前提：生成的 README 里「怎么用」不是中间那一节"
    old = (
        _HOWTO_HEAD + "\n\n"
        "这批文件不是已入库的文献，A 必须走候选链：\n\n"
        "1. `search.ingest_local`（`books_dir=\"" + SI.LIB_SUBDIR + "\"`）"
        + _OLD_CLAIM + "；\n"
        "2. `lit.stage_add` → `extract` → `fs.read` → `lit.admit` → `lit.admit_all` 逐条判收。\n"
    )
    return text[:start] + old + rest[nxt:]


def test_a_anti_vacuum_the_old_claim_turns_it_red(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """a 的反真空：把正确链换成改前那句假的 ⇒ 同一个检查必须红。"""
    real = SI._readme_text
    monkeypatch.setattr(SI, "_readme_text",
                        lambda manifest, seeded: _with_the_old_claim(real(manifest, seeded)))
    monkeypatch.setenv(SI.ENV_SEED_DIR, str(TSC._seed_package(tmp_path)))
    ref = P.resolve(tmp_path / "projects", "victim", start="cold")
    P.create_project(ref, seed_literature=True, now="2026-01-01T00:00:00+08:00")

    section = _howto_section(_readme_text_of(ref.path))
    problems = _chain_problems(section)
    assert problems, (
        "把「怎么用」换回改前那句假话之后判据仍然绿 —— a 是橡皮图章，"
        "它抓不住「非 dry 档登记成候选」这条 P0")
    assert any(_OLD_CLAIM in one or "dry_run=True" in one for one in problems), problems


# ---------------------------------------------------------------- b 同一真身


def _repo_seed_readme() -> Path:
    return Path(__file__).resolve().parents[1] / "seed" / "literature" / "README.md"


def _manual_problems(text: str) -> list[str]:
    """种子包 README 与生成器是不是逐字同一句（空 = 一致）。"""
    chain = SI.candidate_chain_lines(SI.LIB_SUBDIR)
    problems = [f"缺生成器同款那一步：{line}" for line in chain if line not in text]
    warning = SI.candidate_chain_warning()
    if warning not in text:
        problems.append("缺生成器同款那句「非 dry 档跳过判收、不要用」：" + warning)
    if _OLD_CLAIM in text:
        problems.append(f"还在说「{_OLD_CLAIM}」")
    return problems


def test_b_the_repo_seed_readme_is_the_same_true_body() -> None:
    """b：`seed/literature/README.md` 与生成器逐字同一句（同一真身，不许两处不同）。"""
    path = _repo_seed_readme()
    assert path.is_file(), f"种子包 README 不在盘上：{path}"
    text = path.read_text(encoding="utf-8")
    problems = _manual_problems(text)
    assert problems == [], (
        "种子包 README 与 SEED-README 生成器不是同一句（两处不同 ⇒ 模型照哪一处做取决于它读哪份）："
        "\n  - " + "\n  - ".join(problems))


def test_b_anti_vacuum_dropping_the_chain_turns_it_red() -> None:
    """b 的反真空：把那段链从 README 里抠掉 ⇒ 同一检查必红。"""
    text = _repo_seed_readme().read_text(encoding="utf-8")
    assert _manual_problems(text) == [], "夹具前提：改后这一面应当先绿"
    stripped = text
    for line in SI.candidate_chain_lines(SI.LIB_SUBDIR):
        stripped = stripped.replace(line, "")
    stripped = stripped.replace(SI.candidate_chain_warning(), "")
    problems = _manual_problems(stripped)
    assert problems, "把那段链抠掉之后判据仍然绿 —— b 是橡皮图章"
