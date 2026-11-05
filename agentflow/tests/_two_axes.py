# -*- coding: utf-8 -*-
"""「等级 → 档位」三张表的唯一现算处（`docs/TWO-AXES-GRADE-AND-KIND.md` 的那三张表）。

> 2026-11-05 业主裁定之后，这里只剩一根轴：等级。档位是等级的历史反算名
> （`evidencebits.kind_from_grade`）。文件名与标记名保留（文档 §历史 仍引用它们），
> 但它们钉的不再是"两个轴"。

## 这个模块为什么在 `tests/` 下、而不是 `src/`
三张表是文档的读数，不是框架的行为：框架不读它们、运行期用不到它们。
它们只要在"文档 ↔ 代码 ↔ 冻结现场"之间当那条可复跑的链子，所以跟
`tests/_skeleton.py` / `tests/_proof_manuscript_fixture.py` 一样放在判据这一侧。
`python -X utf8 tests/_two_axes.py` 会把三段 markdown 原文打出来（文档里那三张表
可以整段粘贴回去）—— 这是文档 §8「复跑」那一条命令的真身。

## 三张表各自钉什么
- 表一 `表一行()`：32 组五元位 ⇒ `evidencebits.derive_grade` 的真输出 + `audited_badge`；
- 表二 `表二行()`：同一批 32 组 ⇒ 五元位唯一能决定的两格：`signed`（来自
  `secretary._manuscript_upgrade_basis`，那条 lane 未动）与档位反算名
  （`evidencebits.kind_from_bits`）—— 后者 2026-11-05 之前写的是"不由五元位决定"，
  裁定之后它是五元位的函数；
- 表三 `表三行()` / `表三夹具行()`：把冻结现场的 `(等级, 历史档位)` 横表算出来 ——
  它现在是一条审计读数（存量档位与现算等级差多少），不再是"两轴"的证据。

## 现场从哪来
`tests/fixtures/two_axes_scene.json` 是 `projects/*/data/statements.json` 的频次快照
（`projects/` 被 `.gitignore` 排除，判据不能直接读它）。快照只留重算等级需要的四格：
`kind` / `evidence_kind` / 五位 / 条数。刷新方式见 `docs/TWO-AXES-GRADE-AND-KIND.md` §8。
"""
from __future__ import annotations

import collections
import itertools
import json
import pathlib
from typing import Any, Iterable, Mapping

REPO = pathlib.Path(__file__).resolve().parents[1]

import sys

_SRC = REPO / "src"
if str(_SRC) not in sys.path:  # pragma: no cover - 判据侧运行时 conftest 已注入
    sys.path.insert(0, str(_SRC))

from agentflow import evidencebits as EB  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402

#: 冻结现场（频次快照 + 证人行）。
SCENE_PATH = REPO / "tests" / "fixtures" / "two_axes_scene.json"
#: 夹具侧现场（与快照不同源：那份夹具是一个工作区的逐行快照）。
FIXTURE_WORKSPACE_PATH = REPO / "tests" / "fixtures" / "paper_rewrite_86_reviewed_bit.json"

#: 表二那一列的表头（2026-11-05 之前它是"不由五元位决定"；裁定之后它是反算名）。
LEGACY_TIER_FROM_BITS = "档位（= 等级反算名）"

#: 32 组枚举里每一位取的"就绪/未就绪"代表值。
#: `numeric` 取 `verified` / `pending`（四态里只有 `verified` 抬等级，见 `numeric_states()`）；
#: `formal` 取二维的 `{"1": "verified"}` 与标量 `pending`（第 4 位是二维的，两种形状都要在表里）。
COMBO_GRID: tuple[tuple[Any, ...], ...] = tuple(itertools.product(
    ("verified", "pending"), (True, False), (True, False),
    ({"1": "verified"}, "pending"), (True, False),
))

#: 表头（文档里的表头必须逐字相同 ⇒ 判据按它找表）。
TABLE1_HEADER: tuple[str, ...] = ("#", "numeric", "proof", "reviewed", "formal", "audited",
                                  "等级", "`audited_badge`")
TABLE2_HEADER: tuple[str, ...] = ("#", "numeric", "proof", "reviewed", "formal", "audited",
                                  "`signed`（五元位唯一能决定的那一格）", LEGACY_TIER_FROM_BITS)
MATRIX_HEADER: tuple[str, ...] = ("档位 \\ 等级", *EB.GRADES, EB.GRADE_NOT_APPLICABLE, "合计")


# ------------------------------------------------------------------ 现场


#: 快照里的证人（工作区, 命题, 反例组）：三组"两轴不是同一个轴"的现场。
#: A/A2 = 五元位逐字相同而档位不同；B = 同一个档位而等级不同；C = 可引而不硬。
#: 为什么写死这份清单：证人是文档 §5.4 那三组读法的唯一出处，换掉它们要连读法一起改，
#: 而"自动挑证人"会让反例随盘上数据漂走（那时反例就不再是一条可复核的读数了）。
WITNESSES: tuple[tuple[str, str, str], ...] = (
    ("R-mk-infinite-90", "000013", "A"),
    ("R-mk-infinite-90", "000014", "A"),
    ("R-mk-infinite-90", "000015", "A2"),
    ("R-mk-infinite-90", "000020", "A2"),
    ("R-mk-infinite-90", "000003", "B"),
    ("R-mk-infinite-90", "000018", "B"),
    ("ramsey-4-4-87", "000001", "C"),
    ("mp3-r3", "000000", "C"),
)


def 刷新现场(*, path: Any = None, projects: Any = None) -> dict[str, Any]:
    """只读扫描 `projects/*/data/statements.json`，重写冻结现场（人手动跑，判据不调它）。

    `projects/` 在 `.gitignore` 里，所以判据读的是这份快照；新增工作区之后跑一次
    `python -X utf8 tests/_two_axes.py --refresh-scene`，把 diff 看一眼，文档里的表会跟着红
    一次（那是"表过期"该有的样子），改完再绿。
    """
    target = pathlib.Path(path) if path is not None else SCENE_PATH
    root = pathlib.Path(projects) if projects is not None else REPO / "projects"
    sig: dict[tuple[str, str, tuple[str, ...]], int] = collections.Counter()
    witness: dict[tuple[str, str], dict[str, Any]] = {}
    rows_total = 0
    workspaces = 0
    for p in sorted(root.glob("*/data/statements.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        rows = data.get("rows") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            continue
        ws = p.parent.parent.name
        workspaces += 1
        for row in rows:
            bits = _五位(row.get("bits") or {})
            sig[_签名键(str(row.get("kind") or ""),
                        str(row.get("evidence_kind") or ""), bits)] += 1
            rows_total += 1
            sid = str(row.get("stmt_id") or "")
            for w_ws, w_sid, pair in WITNESSES:
                if (ws, sid) == (w_ws, w_sid) and (ws, sid) not in witness:
                    witness[(ws, sid)] = {
                        "pair": pair, "workspace": ws, "stmt_id": sid,
                        "kind": str(row.get("kind") or ""),
                        "evidence_kind": str(row.get("evidence_kind") or ""),
                        "bits": bits}
    missing = [f"{w}/{s}" for w, s, _ in WITNESSES if (w, s) not in witness]
    if missing:
        raise SystemExit(f"证人行在盘上找不到：{missing}（先确认工作区还在，再改 WITNESSES）")
    import datetime

    scene = {
        "schema": "two-axes-scene/1",
        "captured_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "command": "python -X utf8 tests/_two_axes.py --refresh-scene",
        "scope": "agentflow/projects/*/data/statements.json（不含 data/.backup-*；只读扫描）",
        "workspaces": workspaces,
        "rows_total": rows_total,
        "signatures": [
            {"kind": k, "evidence_kind": ek,
             "bits": {name: json.loads(v) for name, v in zip(EB.BIT_NAMES, bt)},
             "count": sig[(k, ek, bt)]}
            for k, ek, bt in sorted(sig)
        ],
        "witnesses": [witness[k] for k in sorted(witness)],
    }
    target.write_text(json.dumps(scene, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return scene


def 现场() -> dict[str, Any]:
    """冻结现场（频次快照）。文件不在 / 形状不对 ⇒ 抛（判据要红，不许静默空表）。"""
    data = json.loads(SCENE_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("signatures"):
        raise AssertionError(f"`{SCENE_PATH}` 不是一份现场快照（缺 signatures）")
    return data


def 夹具工作区() -> dict[str, Any]:
    """夹具侧现场（`paper_rewrite_86_reviewed_bit.json` 的 `statements`）。"""
    data = json.loads(FIXTURE_WORKSPACE_PATH.read_text(encoding="utf-8"))
    rows = data.get("statements")
    if not isinstance(rows, list) or not rows:
        raise AssertionError(f"`{FIXTURE_WORKSPACE_PATH}` 里没有 statements")
    return data


def _五位(bits: Mapping[str, Any]) -> dict[str, Any]:
    return {name: bits.get(name) for name in EB.BIT_NAMES}


def 等级(row: Mapping[str, Any]) -> str:
    """一行现在的等级（`derive_grade` 现算；行上的 `bits.grade` 只是缓存，不读它）。"""
    return EB.derive_grade(_五位(row.get("bits") or {}), kind=str(row.get("kind") or ""))


def _签名键(kind: str, ek: str, bits: Mapping[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    return (kind, ek, tuple(json.dumps(bits.get(name), ensure_ascii=False, sort_keys=True)
                            for name in EB.BIT_NAMES))


# ------------------------------------------------------------------ 表一


def 表一行() -> list[tuple[str, ...]]:
    """32 组五元位 ⇒ 等级（`derive_grade` 真跑）+ 第 5 位的真实落点（`audited_badge`）。"""
    out: list[tuple[str, ...]] = []
    for i, (numeric, proof, reviewed, formal, audited) in enumerate(COMBO_GRID):
        bits = EB.bits_of(numeric=numeric, proof=proof, reviewed=reviewed, formal=formal,
                          audited=audited,
                          audited_by={"rounds": 1} if audited else None)
        out.append((
            f"{i:02d}", str(numeric), _bool(proof), _bool(reviewed),
            "verified" if isinstance(formal, Mapping) else str(formal),
            _bool(audited), str(bits["grade"]), _bool(bool(bits.get("audited_badge"))),
        ))
    return out


def 表二行() -> list[tuple[str, ...]]:
    """32 组五元位 ⇒ `signed` + 档位反算名（`kind_from_bits` = 等级的同一个函数）。"""
    out: list[tuple[str, ...]] = []
    for i, (numeric, proof, reviewed, formal, audited) in enumerate(COMBO_GRID):
        bits = EB.bits_of(numeric=numeric, proof=proof, reviewed=reviewed, formal=formal,
                          audited=audited)
        got = SEC._manuscript_upgrade_basis(root=None, bits=bits)
        out.append((
            f"{i:02d}", str(numeric), _bool(proof), _bool(reviewed),
            "verified" if isinstance(formal, Mapping) else str(formal),
            _bool(audited), _bool(bool(got.get("signed"))),
            EB.kind_from_bits(bits),
        ))
    return out


# ------------------------------------------------------------------ 表三


def _矩阵(条目: Iterable[tuple[str, str, int]]) -> dict[tuple[str, str], int]:
    grid: dict[tuple[str, str], int] = collections.Counter()
    for grade, ek, n in 条目:
        grid[(grade, ek)] += n
    return dict(grid)


def 表三行() -> list[tuple[str, ...]]:
    """真机现场（77 工作区 / 3,627 行的频次快照）的 `(等级, 档位)` 横表。"""
    scene = 现场()
    条目 = []
    for sig in scene["signatures"]:
        bits = _五位(sig.get("bits") or {})
        grade = EB.derive_grade(bits, kind=str(sig.get("kind") or ""))
        条目.append((grade, str(sig.get("evidence_kind") or ""), int(sig.get("count") or 0)))
    return _横表(_矩阵(条目), 档位序=_现场档位序(scene))


def 表三夹具行() -> list[tuple[str, ...]]:
    """夹具侧现场（`paper_rewrite_86_reviewed_bit.json` 的两行）的同一张横表。"""
    scene = 夹具工作区()
    条目 = []
    for row in scene["statements"]:
        条目.append((等级(row), str(row.get("evidence_kind") or ""), 1))
    return _横表(_矩阵(条目), 档位序=list(S.EVIDENCE_KINDS))


def _现场档位序(scene: Mapping[str, Any]) -> list[str]:
    """现场出现过的档位 + 词表里剩下的（表要每一档一行，缺行会让"0"看不出来）。"""
    seen = [str(s.get("evidence_kind") or "") for s in scene["signatures"]]
    ordered = [ek for ek in S.EVIDENCE_KINDS if ek in seen]
    ordered += sorted({ek for ek in seen if ek not in S.EVIDENCE_KINDS})
    return ordered


def _横表(grid: Mapping[tuple[str, str], int], *, 档位序: list[str]) -> list[tuple[str, ...]]:
    grades = [*EB.GRADES, EB.GRADE_NOT_APPLICABLE]
    rows: list[tuple[str, ...]] = []
    for ek in [*档位序, *[k for k in S.EVIDENCE_KINDS if k not in 档位序]]:
        cells = [str(grid.get((g, ek), 0)) for g in grades]
        rows.append((ek, *cells, str(sum(grid.get((g, ek), 0) for g in grades))))
    totals = [str(sum(grid.get((g, ek), 0) for ek in 档位序)) for g in grades]
    rows.append(("合计", *totals, str(sum(int(t) for t in totals))))
    return rows


def 证人表行() -> list[tuple[str, ...]]:
    """§5.4 的三组反例（逐格可由现场复核）。"""
    rows: list[tuple[str, ...]] = []
    for row in 现场()["witnesses"]:
        bits = _五位(row.get("bits") or {})
        rows.append((
            str(row.get("pair") or ""), str(row.get("workspace") or ""),
            str(row.get("stmt_id") or ""),
            str(bits["numeric"]), _bool(bool(bits["proof"])), _bool(bool(bits["reviewed"])),
            "verified" if isinstance(bits["formal"], Mapping) else _formal_字面量(bits["formal"]),
            _bool(bool(bits["audited"])), 等级(row), str(row.get("evidence_kind") or ""),
        ))
    return rows


def _formal_字面量(value: Any) -> str:
    return "pending" if value in (None, "", "pending") else str(value)


def _bool(value: Any) -> str:
    return "true" if value else "false"


# ------------------------------------------------------------------ 渲染


def _表头(header: tuple[str, ...]) -> str:
    return "| " + " | ".join(header) + " |"


def _分隔(header: tuple[str, ...]) -> str:
    return "| " + " | ".join("---" for _ in header) + " |"


def _块(rows: Iterable[tuple[str, ...]], header: tuple[str, ...]) -> list[str]:
    return [_表头(header), _分隔(header), *("| " + " | ".join(r) + " |" for r in rows)]


#: 标记块名 → (表头, 行)。文档里那几段表的唯一期望值。
def 期望块() -> dict[str, tuple[tuple[str, ...], list[tuple[str, ...]]]]:
    return {
        "TABLE1": (TABLE1_HEADER, 表一行()),
        "TABLE2": (TABLE2_HEADER, 表二行()),
        "TABLE3": (MATRIX_HEADER, 表三行()),
        "TABLE3F": (MATRIX_HEADER, 表三夹具行()),
        "TABLE3X": (("反例", "工作区", "命题", "numeric", "proof", "reviewed", "formal",
                     "audited", "等级", "档位"), 证人表行()),
    }


def 渲染() -> dict[str, list[str]]:
    """五段表原文（键与文档里的标记同名）。"""
    return {name: _块(rows, header) for name, (header, rows) in 期望块().items()}


if __name__ == "__main__":  # pragma: no cover - 复跑入口（文档 §8 那两条命令）
    import sys as _sys

    if "--refresh-scene" in _sys.argv[1:]:
        scene = 刷新现场()
        print(f"重写 `{SCENE_PATH}`：{scene['workspaces']} 个工作区 / "
              f"{scene['rows_total']} 行 / {len(scene['signatures'])} 个签名 / "
              f"{len(scene['witnesses'])} 个证人")
    else:
        for name, lines in 渲染().items():
            print(f"<!-- TWO-AXES:{name}:BEGIN -->")
            print("\n".join(lines))
            print(f"<!-- TWO-AXES:{name}:END -->")
            print()
