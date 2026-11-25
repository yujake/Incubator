# -*- coding: utf-8 -*-
"""秘书的档位读侧（折叠、版本闸与三态，从 secretary.py 的 U25 中段逐字搬出）。

我保证哪条不变式：一路径一行；命题级读数取该命题全部路径的历史 min（不回升）——
「曾经判过低」不能被后面的重判抬上去。

## 依赖方向

本文件只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），不许出现
`from .secretary import ...`（那一句就是「组装层 <-> 混入层」的真 import 环）。
方法之间只经 `self.xxx` 互相调用（走 MRO，不产生 import），所以一个方法搬进混入类
与留在 `class Secretary` 里 AST dump 完全相同 —— 「搬」不算「改」
（`temp/secsplit/bodies_all.py` 逐名可复算）。类由 `secretary.py` 组装，`secretary.py`
对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from typing import Mapping
import hashlib
import json

from .secretary_decl import (  # noqa: F401 — 这些名字由 secretary_decl 定义
    NONTRIVIALITY_SCALE,
    NONTRIVIALITY_UNJUDGED,
)


class TierLedgerMixin:
    """档位读侧（折叠与三态）的混入类：本模块今天没有方法，类在这里是为了组装口一致。"""

from .secretary_ledger import (  # noqa: F401 — 这些名字由 secretary_ledger 定义
    nontriviality_path,
)

from .secretary_time import (  # noqa: F401 — 这些名字由 secretary_time 定义
    _now_iso,
)

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    _nontriviality_level,
    nontriviality_label,
)


def _statement_sha(statement_full: str) -> str:
    return hashlib.sha256(str(statement_full or "").strip().encode("utf-8")).hexdigest()


def _tier_from_judge_reply(got: Mapping[str, Any]) -> int | None:
    """从一趟判词里读档位（2026-11-01 起 `decision` 是唯一的主字段）。

    `decision` 可解析 ⇒ 就是它（数字 `2` / `"2"` / `"T2"` 都收敛到 2）；它不是档位时
    才退到 `nontriviality` —— 那是 2026-11-01 之前"两字段两轴"形状的读别名（老结果、
    替身、历史台账），不再向模型索取。两个都读不出来 ⇒ `None` = 判不了（不是 0）。
    """
    level = _nontriviality_level(got.get("decision"))
    if level is not None:
        return level
    return _nontriviality_level(got.get("nontriviality"))


def _tier_from_legacy_decision(row: Mapping[str, Any]) -> int | None:
    """一行旧台账折算出的档位（2026-11-01 词表退场后读旧行的唯一口径）。

    `out/secretary/<角色>.jsonl` 是 append-only 的，旧行里还有三个旧词。按这张表折算
    （这是"旧词"在源码里仅存的落点，判据钉着它只许出现在这里）：

    | 老 `decision` | 折算出的档位 |
    |---|---|
    | `T0`…`T4` | 同名档位（2026-11-01 那一笔的兼容形状） |
    | `太平凡` | T0（"力气小 ⇒ 落 T0"） |
    | `合格` | `judge.nontriviality` / 同号档位行那一行；都没有 ⇒ 未判 |
    | `判不了` | 未判（`None`）：它是"该判而没判"，不是一档 |

    优先级：decision 能解析 ⇒ 用它；否则 `太平凡` ⇒ 0；否则读 `nontriviality`
    （先 `judge.nontriviality` 再同级）。两套字段冲突时 decision 胜。

    这一格只回答"这一行说的是哪一档"，不回答"是不是判过了"：`None` 既可能"判不了"
    也可能"没查成"，后者要读 `judge.checked`（新行）或 `fail_open`（旧行）。
    """
    decision = str(row.get("decision") or "")
    level = _nontriviality_level(decision)
    if level is not None:
        return level
    if decision.strip() == "太平凡":
        return 0
    judge = row.get("judge")
    if isinstance(judge, Mapping):
        level = _nontriviality_level(judge.get("nontriviality"))
        if level is not None:
            return level
    return _nontriviality_level(row.get("nontriviality"))


def _level_from_row(row: Mapping[str, Any]) -> int | None:
    """从一行台账读档位（含旧刻度的兼容，唯一读口）。

    旧行（没有 `scale` 标记）里 `0` 是"判不了"；新行（有标记）里 `0` 是 T0。
    这一区分只在这里做一次，理由见 :data:`NONTRIVIALITY_SCALE`。
    """
    level = _nontriviality_level(row.get("nontriviality"))
    if not str(row.get("scale") or "").strip():
        return level if level else None
    return level


def _judged_body_sha(statement_full: str, proof_text: str = "") -> str:
    """判档材料（命题 + 空行 + 证明）的 sha256 —— "判的是哪一版"的唯一算法。

    与 `record_nontriviality` 落进台账的 `judged_body_sha256` 同一个公式（这里是唯一
    实现）：复核的人拿同一份稿按它重算，就能核对那一行判的到底是哪一版材料。
    它不参与关联（关联仍按 `stmt_id` / 旧行回退 sha）—— 只回答"这一次判的是哪一版"。
    """
    return hashlib.sha256(
        (str(statement_full or "") + "\n\n" + str(proof_text or "")).encode("utf-8")
    ).hexdigest()


#: 版本闸的结局（`nontriviality_of` 返回的 `version` 这一格）。
#:
#: 业主 2026-11-25：档位 = `(stmt_id, path_group)` 上「最后一次研判」的结论；B 的二阶段
#: 优化是定点直接提交（不过秘书、不写档位行、不改路径号）⇒ 它不改该路径的档位。
#:
#: | 结局 | 判据 | 档位 |
#: |---|---|---|
#: | `checked` | 判料 sha 与依赖指纹都与现盘一致 | 沿用 |
#: | `text_drift` | 判过之后正文被优化过（sha 不同） | 沿用（信息读数） |
#: | `needs_rejudge` | 现盘依赖集与研判那一刻不同（见 :func:`deps_sha256`） | 不沿用（要重判） |
#: | `unchecked` | 行上没有 `judged_deps_sha`（旧行）/ 读侧没交出现盘材料 | 沿用，但记「没核过」 |
#: | `unversioned` | 行上没有 `judged_body_sha256`（2026-11-15 之前的行） | 沿用（无从核） |
NT_VERSION_CHECKED = "checked"
NT_VERSION_TEXT_DRIFT = "text_drift"
NT_VERSION_NEEDS_REJUDGE = "needs_rejudge"
NT_VERSION_UNVERSIONED = "unversioned"
NT_VERSION_UNCHECKED = "unchecked"

#: 依赖集指纹只认「依赖了哪些东西」，不认台账行的 id / 摘录 / 状态：同一份依赖重新
#: 登记一次、摘录换一行、状态从 open 变 closed，都不是"换了论证"。
_DEP_IDENTITY_FIELDS = ("kind", "source_stmt_id", "source_lit_id",
                        "source_experiment_id")


def deps_sha256(*, derived_from: Sequence[Any] = (),
                dependency_rows: Iterable[Mapping[str, Any]] = (),
                stmt_id: str = "") -> str:
    """这条命题的依赖集指纹（研判那一刻与现在各算一次，比它是否相同）。

    数据从既有读口来：`statements.derived_from` ＋ `dependencies` 表里
    `used_by == "stmt:<号>"` 的那些行。每个依赖只取 `(kind, source_stmt_id,
    source_lit_id, source_experiment_id, path_group)`；`dep_id` / `label` / `quote` /
    `status` 不进指纹（理由见 :data:`_DEP_IDENTITY_FIELDS`）。

    纯函数是刻意的："依赖变没变"是这条闸里唯一会改判档结论的判据（`needs_rejudge`），
    写入侧（`record_nontriviality`）与读侧（收工读数）必须用同一个公式。
    """
    want = str(stmt_id or "").strip()
    derived = sorted({str(x).strip() for x in (derived_from or ())
                      if str(x).strip()})
    deps: set[tuple[str, str, str, str, int]] = set()
    if want:
        for row in (dependency_rows or ()):
            used_by = str(row.get("used_by") or "").strip()
            if used_by not in (want, f"stmt:{want}"):
                continue
            try:
                no = int(row.get("path_group") or 1)
            except (TypeError, ValueError):
                no = 1
            ident = tuple(str(row.get(k) or "") for k in _DEP_IDENTITY_FIELDS)
            deps.add(ident + (no,))
    payload = json.dumps({"derived_from": derived,
                          "deps": [list(x) for x in sorted(deps)]},
                         ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _tier_reading(row: Mapping[str, Any], *, expected_judged_sha: str | None,
                  expected_deps_sha: str | None) -> dict[str, Any]:
    """这一行的档位对现在这盘材料还成不成立（版本闸的唯一判据）。

    两根轴各判各的，把"没核过"与"核过了、一致"分开：

    | 轴 | 行上缺这一格 | 读侧没给现盘材料 | 相等 | 不等 |
    |---|---|---|---|---|
    | 正文 / 依赖 | `unversioned` | `unchecked` | `same` | `drift` / `changed` |

    结局优先级：依赖变 ⇒ `needs_rejudge`（不沿用旧档）；正文变 ⇒ `text_drift`（信息读数，
    档位沿用）；没有正文戳 ⇒ `unversioned`；依赖没核过 ⇒ `unchecked`；都一致 ⇒ `checked`。
    旧行没有 `judged_deps_sha` ⇒ 不判 `needs_rejudge`（不许当成"依赖没变"），也不算 `checked`。
    """
    recorded_text = str(row.get("judged_body_sha256") or "")
    recorded_deps = str(row.get("judged_deps_sha") or "")
    if not recorded_text:
        text = "unversioned"
    elif not expected_judged_sha:
        text = "unchecked"
    else:
        text = "same" if recorded_text == expected_judged_sha else "drift"
    if not recorded_deps:
        deps = "unversioned"
    elif not expected_deps_sha:
        deps = "unchecked"
    else:
        deps = "same" if recorded_deps == expected_deps_sha else "changed"
    if deps == "changed":
        version = NT_VERSION_NEEDS_REJUDGE
    elif text == "drift":
        version = NT_VERSION_TEXT_DRIFT
    elif text == "unversioned":
        version = NT_VERSION_UNVERSIONED
    elif deps in ("unversioned", "unchecked"):
        version = NT_VERSION_UNCHECKED
    else:
        version = NT_VERSION_CHECKED
    return {"version": version, "text": text, "deps": deps,
            "text_drift": text == "drift",
            "judged_body_sha256": recorded_text,
            "current_judged_body_sha256": str(expected_judged_sha or ""),
            "judged_deps_sha256": recorded_deps,
            "current_deps_sha256": str(expected_deps_sha or ""),
            "at": str(row.get("at") or "")}


def append_nontriviality(root: str | Path, *, statement_full: str, level: Any,
                         basis: str = "", role: str = "", task_id: str = "",
                         stmt_id: str = "",
                         effort: Mapping[str, Any] | None = None,
                         text_truncated: bool = False,
                         applicable: bool = True,
                         path_group: int = 0,
                         judged_body_sha256: str = "",
                         judged_deps_sha: str = "",
                         landed_body_sha256: str = "",
                         scope: str = "") -> None:
    """追加一行档位读数（append-only；显式 LF，Windows 上不留 CRLF）。

    `level` 给 `None`（或缺省/坏值）⇒ 这一行记的是"判不了"：`nontriviality: null` 且
    `label` 空。判不了照旧落一行 —— "没人判过"与"台账里没这一条"在盘上要分得开。

    ## 行上那几格（每一格都是一次判据分开的产物）

    | 格 | 含义 |
    |---|---|
    | `path_group` | 第几条证明路径的读数（`>=1`）；`0` = statement-scope（概念行的"不适用"）。旧行没有这一格 ⇒ 读侧视为路径 1 |
    | `scope` | `"path"` / `"statement"` |
    | `judged_body_sha256` | 判的那一刻的材料（命题 + 空行 + 证明，见 :func:`_judged_body_sha`） |
    | `judged_deps_sha` | 判的那一刻的依赖集指纹（见 :func:`deps_sha256`）—— 现盘变了 ⇒ `needs_rejudge` |
    | `landed_body_sha256` | 落盘那一行的 `statement_full` 的 sha —— 与判料分开记，才答得出"判的是不是落的那一版" |
    | `applicable` | `False` = 这一问对它不成立（概念行没有证明正文）；`level` 恒 `None`、`label` 恒空。老行没有这一格 ⇒ 按 `True` 读 |
    | `effort` / `text_truncated` | 判档时手里的力气读数 / 输入是否被截断（"缺读数"与"判了"必须分得开） |

    `stmt_id` 必须带号：按正文 sha 关联会把"改了一个字"读成"没判过"（真机 mp3-r3 的
    第 1 行就是这样）。缺省空串只服务旧调用面与测试直调；生产面只有一个落点
    （`Secretary.record_nontriviality`），拿不到号就不落并留 `unrecorded` 痕迹。
    """
    path = nontriviality_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 不适用的那一档不许同时带档位（两件事折进一行就等于把"不存在这一问"读成"判了"）
    got = _nontriviality_level(level) if applicable else None
    no = int(path_group or 0)
    row = {"at": _now_iso(), "stmt_id": str(stmt_id or ""),
           "statement_sha256": _statement_sha(statement_full),
           "statement_chars": len(str(statement_full or "")),
           # 刻度标记：读侧靠它区分"0 = T0"与旧行的"0 = 判不了"（见 NONTRIVIALITY_SCALE）
           "scale": NONTRIVIALITY_SCALE,
           "nontriviality": got, "label": nontriviality_label(got),
           # 判档这一格对这一行适不适用（见上面那一段）；缺省 True = 与老行同一读法
           "applicable": bool(applicable),
           # 路径维（见上面那一段）：0 = statement-scope；>=1 = 第几条证明路径
           "path_group": no,
           "scope": str(scope or ("path" if no >= 1 else "statement")),
           "judged_body_sha256": str(judged_body_sha256 or ""),
           "judged_deps_sha": str(judged_deps_sha or ""),
           "landed_body_sha256": str(landed_body_sha256 or ""),
           "basis": str(basis or ""),
           "effort": dict(effort or {}), "text_truncated": bool(text_truncated),
           "role": str(role or ""), "task_id": str(task_id or "")}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        # `default=str` 与全仓同一口径（`tests/test_json_dumps_has_a_default.py`）：这一行是
        # append-only 档位台账的唯一写口，它抛出去会丢一行读数而调用方看不出来。
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def _row_matches_stmt_id(row: Mapping[str, Any], stmt_id: str) -> bool:
    """按号关联的唯一判据：号非空且与这一行的 `stmt_id` 相同（空号永不命中）。

    为什么单独一格：读侧"按号查"必须是一个能被打桩的判据（反真空判据把它打桩成
    恒不命中，看"正文一改档位还在不在"那条会不会红）；而空号不许命中空号 ——
    旧行没有 `stmt_id`，把它们当成"号为空的那一条"会让所有旧行并成一条。
    """
    want = str(stmt_id or "").strip()
    if not want:
        return False
    return str(row.get("stmt_id") or "").strip() == want


#: 路径号的读法（唯一一处）：新行读 `path_group`；旧行没有这一格 ⇒ 视为路径 1
#: （改前判的就是 canonical 那份证明）。`0` 是 statement-scope（概念行的"不适用"），
#: 它不参与命题级的 min —— 这一格的语义由调用方（`_fold_nontriviality`）先按
#: `applicable` 分出去，本函数只回答"这一行属于第几条路径"。
def _row_path_group(row: Mapping[str, Any]) -> int:
    raw = row.get("path_group")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return 1
    try:
        no = int(raw)
    except (TypeError, ValueError):
        return 1
    return no if no >= 1 else 0


#: 档位台账的进程内索引：`路径 -> (键, (按号, 按 sha))`，键 = `(st_mtime_ns, st_size)`。
#:
#: 为什么要有它（2026-10-27，R-BE1 的 ⑥-3）：`nontriviality_of` 是逐条命题调的（收工读数与
#: 网页那一栏都是逐条问），而它每次都把整份 `out/secretary/nontriviality.jsonl` 读一遍、
#: 逐行 `json.loads` —— 400 条命题 × 400 行台账 = 每条命题 400 次解析。
#:
#: 键取 `(st_mtime_ns, st_size)`：`append_nontriviality` 是追加写 ⇒ 台账一变键就变，下一次
#: 调用立刻读到新值（判据 `tests/test_nontriviality_ledger_is_read_once.py` 两个方向都钉着）。
#: 每个路径只留最新一版（不按"每一版"累积），所以长跑里它不会无限长大。
#:
#: 两个索引都存整串行（按 append 顺序）：读侧要按 `(stmt_id, path_group)` 折叠，
#: "最后一行胜"只是折叠规则的一部分（见 `_fold_nontriviality`），不是索引的语义。
#:
#: 已知边界（刻意的）：缓存里放的是解析后的行。`nontriviality_of` 只读它，返回的 dict
#: 是新造的（`effort` 那一格也复制了），所以调用方就地改返回值不会污染缓存；但谁要是绕过
#: 本函数直接拿缓存里的行去改（本模块不导出它），改的就是"这个进程眼里的台账"。
_NT_INDEX_CACHE: dict[str, tuple[tuple[int, int],
                                tuple[dict[str, list[dict[str, Any]]],
                                      dict[str, list[dict[str, Any]]]]]] = {}


def _nontriviality_index(path: Path
                         ) -> tuple[dict[str, list[dict[str, Any]]],
                                    dict[str, list[dict[str, Any]]], str]:
    """把台账读成 `(按号, 按 sha, 读不成原因)` —— 同一份文件只解析一次（`mtime_ns+size` 键）。

    两个索引都把每一行按 append 顺序收进列表：读侧要按 `(stmt_id, path_group)` 折叠成
    "路径级最后一行"与"命题级 = 各路径历史最小值"，只留最后一行会把路径 / 历史都丢掉。
    坏行（不是 JSON / 不是对象）跳过；"文件读不出来"如实返回原因，由调用方落成
    "没有这条命题的读数"（不是"这条命题是 T1"）。
    """
    try:
        st = path.stat()
        key = (int(st.st_mtime_ns), int(st.st_size))
    except OSError as exc:
        return {}, {}, f"{path} 读不到（{type(exc).__name__}: {exc}）"
    hit = _NT_INDEX_CACHE.get(str(path))
    if hit is not None and hit[0] == key:
        return hit[1][0], hit[1][1], ""
    by_id: dict[str, list[dict[str, Any]]] = {}
    by_sha: dict[str, list[dict[str, Any]]] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {}, {}, f"{path} 读不到（{type(exc).__name__}: {exc}）"
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, Mapping):
            continue
        sid = str(row.get("stmt_id") or "").strip()
        if sid:
            by_id.setdefault(sid, []).append(row)
        sha = str(row.get("statement_sha256") or "")
        if sha:
            by_sha.setdefault(sha, []).append(row)
    _NT_INDEX_CACHE[str(path)] = (key, (by_id, by_sha))
    return by_id, by_sha, ""


def _fold_path(no: int, seq: Sequence[Mapping[str, Any]], *,
               statement_full: str,
               proofs_by_path: Mapping[int, str] | None,
               expected_deps_sha: str | None
               ) -> tuple[dict[str, Any], dict[str, Any], int | None]:
    """折叠一条证明路径（逐路径那一半；`_fold_nontriviality` 是唯一调用方）。

    返回 `(闸读数, paths[] 那一行, 该路径历史最小值)`。只有 `needs_rejudge` 才把
    `level` / `floor` 读成 `None`；`text_drift` 是信息读数（档位跟路径走，洗稿不改档）。
    """
    last = seq[-1]
    proof = None if proofs_by_path is None else proofs_by_path.get(no)
    gate = _tier_reading(
        last,
        expected_judged_sha=("" if proof is None
                            else _judged_body_sha(statement_full, str(proof))),
        expected_deps_sha=expected_deps_sha)
    blocked = gate["version"] == NT_VERSION_NEEDS_REJUDGE
    levels = [] if blocked else [x for x in (_level_from_row(r) for r in seq)
                                 if x is not None]
    floor = min(levels) if levels else None
    level_here = None if blocked else _level_from_row(last)
    entry = {"path_group": no, "level": level_here, "floor": floor,
             "label": nontriviality_label(level_here),
             "at": str(last.get("at") or ""),
             "stmt_id": str(last.get("stmt_id") or ""),
             "basis": str(last.get("basis") or ""),
             "judged_body_sha256": gate["judged_body_sha256"],
             "judged_deps_sha": gate["judged_deps_sha256"],
             "landed_body_sha256": str(last.get("landed_body_sha256") or ""),
             "version": gate["version"], "text_drift": gate["text_drift"],
             "deps": gate["deps"], "rows": len(seq)}
    return {**gate, "path_group": no}, entry, floor


def _statement_version(gates: Sequence[Mapping[str, Any]]) -> str:
    """命题级的版本结局：任一路径要重判 ⇒ `needs_rejudge`；任一路径正文漂移 ⇒
    `text_drift`；只有每条都 `checked` 才是 `checked`，混合取最弱（没核 ≠ 核过了）。
    """
    versions = [str(g.get("version") or "") for g in gates]
    if NT_VERSION_NEEDS_REJUDGE in versions:
        return NT_VERSION_NEEDS_REJUDGE
    if NT_VERSION_TEXT_DRIFT in versions:
        return NT_VERSION_TEXT_DRIFT
    if versions and all(v == NT_VERSION_CHECKED for v in versions):
        return NT_VERSION_CHECKED
    if NT_VERSION_UNVERSIONED in versions:
        return NT_VERSION_UNVERSIONED
    return NT_VERSION_UNCHECKED


def _deps_state(gates: Sequence[Mapping[str, Any]]) -> str:
    """命题级的依赖集核对结局（`same` / `changed` / `unversioned` / `unchecked`）。"""
    states = [str(g.get("deps") or "") for g in gates]
    if "changed" in states:
        return "changed"
    if states and all(x == "same" for x in states):
        return "same"
    if "unversioned" in states:
        return "unversioned"
    return "unchecked"


def _fold_paths(by_path: Mapping[int, Sequence[Mapping[str, Any]]], *,
                statement_full: str,
                proofs_by_path: Mapping[int, str] | None,
                expected_deps_sha: str | None
                ) -> tuple[list[dict[str, Any]], list[dict[str, Any]],
                           dict[int, int | None], list[dict[str, Any]],
                           list[dict[str, Any]]]:
    """把每条路径折成五张平行表（按路径号升序）：闸读数 / `paths[]` / 历史最小值 /
    要重判的明细 / 正文漂移的明细。"""
    gates: list[dict[str, Any]] = []
    detail: list[dict[str, Any]] = []
    floors: dict[int, int | None] = {}
    needs: list[dict[str, Any]] = []
    drift: list[dict[str, Any]] = []
    for no in sorted(by_path):
        last = by_path[no][-1]
        gate, entry, floor = _fold_path(no, by_path[no], statement_full=statement_full,
                                        proofs_by_path=proofs_by_path,
                                        expected_deps_sha=expected_deps_sha)
        gates.append(gate)
        detail.append(entry)
        floors[no] = floor
        if gate["version"] == NT_VERSION_NEEDS_REJUDGE:
            needs.append(dict(gate, recorded_level=_level_from_row(last)))
        if gate["text_drift"]:
            drift.append(dict(gate, recorded_level=_level_from_row(last)))
    return gates, detail, floors, needs, drift


def _fold_nontriviality(rows: Sequence[Mapping[str, Any]], *, matched_by: str,
                        path_group: int | None = None,
                        path_groups: Sequence[Any] | None = None,
                        statement_full: str = "",
                        proofs_by_path: Mapping[int, str] | None = None,
                        expected_deps_sha: str | None = None) -> dict[str, Any]:
    """把同一命题的台账行折叠成一条读数（唯一实现；读侧三处读点共用）。

    ## 折叠规则（业主 2026-11-15 的五条硬约束落到读侧）

    | 规则 | 实现 |
    |---|---|
    | 一个路径一行 | 按 `path_group` 分组；旧行（无这一格）= 路径 1 |
    | 路径级 = 该路径最后一行 | 同一路径重判允许升降（T4 造出梯子 ⇒ 降到 T2 是正常路径） |
    | 命题级 = 各路径非平凡度的最小值 | `level = min(min_of)`，`min_of` 是各路径的历史最小值 |
    | 已有值 ⇒ min(原值, 本次) | 取历史最小值 ⇒ 命题级永不回升（新增路径 / 同路径判得更难都抬不上去） |
    | 部分路径未判 ⇒ `partial=true` | `paths_unjudged` 点名；不许把"部分没判"折成"全判了" |

    路径级用"最后一行"、命题级用"历史最小值"是业主口径的两条硬约束：路径换了一份更难的
    证明（T1→T3）⇒ 那条路径的当前值是 T3，而命题级仍取各路径历史最小。

    ## 版本闸与依赖守卫（2026-11-25，TIER-VERSION 问题②）

    业主口径逐字：「非平凡度跟随路径而不跟随稿」。档位 = `(stmt_id, path_group)` 上
    「最后一次研判」的结论；研判只在经 B 秘书入库那一刻发生，B 的二阶段优化不过秘书、
    不改路径号 ⇒ 正文变了不改这一档。判据在 :func:`_tier_reading`：

    | 结局 | 这一条读成什么 |
    |---|---|
    | `checked` | 判料 sha 与依赖指纹都与现盘一致 ⇒ 档位沿用 |
    | `text_drift` | 正文变了（判过之后被优化过）⇒ 信息读数，档位照旧沿用 |
    | `needs_rejudge` | 依赖集变了 ⇒ 该路径 `level` / `floor` 读成 `None`，不沿用旧档 |
    | `unversioned` / `unchecked` | 没有版本戳 / 依赖没核过 / 读侧没交材料 ⇒ 沿用，但记"没核过" |

    任一路径要重判 ⇒ 整条 `tri="unknown"` + `level=None`（命题级 min 依赖每一条路径）。
    `paths_needs_rejudge` / `paths_text_drift` 点名是哪几条，`*_detail` 列出"行上记的 sha /
    现盘重算的 sha / 那一行原来读成第几档" —— 旧档只在 `needs_rejudge_detail` 里可见。

    ## 返回

    旧键逐字不动，另加 `paths` / `min_of` / `paths_unjudged` / `partial` 与版本闸那几格
    （`version` / `deps_state` / `text_drift` / `*_detail` / `paths_needs_rejudge`）。
    `path_group>=1` 时返回该路径的读数，命题级另放在 `statement_level`。
    """
    want_path: int | None = None
    if path_group not in (None, "", 0):
        try:
            want_path = int(path_group)
        except (TypeError, ValueError):
            want_path = None
    expected: list[int] = []
    for raw in (path_groups or ()):
        try:
            no = int(raw)
        except (TypeError, ValueError):
            continue
        if no >= 1 and no not in expected:
            expected.append(no)
    concept: list[Mapping[str, Any]] = []
    by_path: dict[int, list[Mapping[str, Any]]] = {}
    for row in rows:
        # 老行没有 `applicable` 这一格 ⇒ 按 True 读（与它们写下来时的语义一致）
        if not bool(row.get("applicable", True)):
            concept.append(row)
            continue
        no = _row_path_group(row)
        if no < 1:
            # `path_group=0` 却标着 applicable：落行方把 statement-scope 用错了。
            # 读侧按路径 1 处置并留一个可核的读数，不静默丢掉它。
            no = 1
        by_path.setdefault(no, []).append(row)

    def _unjudged(reason: str) -> dict[str, Any]:
        return {"tri": "unknown", "level": NONTRIVIALITY_UNJUDGED, "label": "",
                "applicable": True, "matched_by": matched_by, "stmt_id": "",
                "at": "", "reason": reason, "effort": {}, "text_truncated": False,
                "paths": [], "min_of": [],
                "paths_unjudged": list(expected), "partial": bool(expected),
                "statement_level": None,
                "version": NT_VERSION_UNCHECKED, "deps_state": "unchecked",
                "text_drift": False, "paths_text_drift": [],
                "text_drift_detail": [], "paths_needs_rejudge": [],
                "needs_rejudge_detail": []}

    if want_path is not None:
        seq = by_path.get(want_path) or []
        if not seq:
            got = _unjudged(f"第 {want_path} 条路径还没有档位读数")
            got["paths_unjudged"] = [want_path]
            got["partial"] = True
            return got
        last = seq[-1]
        gate, entry, floor = _fold_path(
            want_path, seq, statement_full=statement_full,
            proofs_by_path=proofs_by_path, expected_deps_sha=expected_deps_sha)
        level_here = entry["level"]
        blocked = gate["version"] == NT_VERSION_NEEDS_REJUDGE
        _gates, _detail, folded_floors, folded_needs, _drift = _fold_paths(
            by_path, statement_full=statement_full, proofs_by_path=proofs_by_path,
            expected_deps_sha=expected_deps_sha)
        floors = [folded_floors[no] for no in sorted(by_path)]
        stmt_level = (None if folded_needs
                      else (min([x for x in floors if x is not None]) if floors else None))
        return {"tri": ("computed" if level_here is not None else "unknown"),
                "level": level_here, "label": nontriviality_label(level_here),
                "applicable": True, "matched_by": matched_by,
                "stmt_id": str(last.get("stmt_id") or ""),
                "basis": "" if blocked else str(last.get("basis") or ""),
                "at": "" if blocked else str(last.get("at") or ""),
                "effort": {} if blocked else dict(last.get("effort") or {}),
                "text_truncated": (False if blocked
                                   else bool(last.get("text_truncated"))),
                "path_group": want_path,
                "paths": [entry],
                "min_of": [floor] if floor is not None else [],
                "paths_unjudged": ([] if blocked or floor is not None else [want_path]),
                "partial": bool(blocked or floor is None),
                "statement_level": stmt_level,
                "version": gate["version"], "deps_state": gate["deps"],
                "text_drift": bool(gate["text_drift"]),
                "paths_text_drift": [want_path] if gate["text_drift"] else [],
                "text_drift_detail": ([dict(gate, recorded_level=_level_from_row(last))]
                                      if gate["text_drift"] else []),
                "paths_needs_rejudge": [want_path] if blocked else [],
                "needs_rejudge_detail": ([dict(gate, recorded_level=_level_from_row(last))]
                                         if blocked else [])}

    if not by_path:
        if concept:
            last = concept[-1]
            return {"tri": "not_applicable", "level": None, "applicable": False,
                    "label": "", "basis": str(last.get("basis") or ""),
                    "at": str(last.get("at") or ""), "matched_by": matched_by,
                    "stmt_id": str(last.get("stmt_id") or ""), "effort": {},
                    "text_truncated": False, "paths": [], "min_of": [],
                    "paths_unjudged": [], "partial": False, "statement_level": None,
                    # 概念行的"不适用"与版本无关：它没有证明正文可判，也没有档位可过期
                    "version": NT_VERSION_UNCHECKED, "deps_state": "unchecked",
                    "text_drift": False, "paths_text_drift": [],
                    "text_drift_detail": [], "paths_needs_rejudge": [],
                    "needs_rejudge_detail": []}
        return _unjudged("台账里没有这条命题的档位读数")

    gates, detail, path_floor, needs_detail, drift_detail = _fold_paths(
        by_path, statement_full=statement_full, proofs_by_path=proofs_by_path,
        expected_deps_sha=expected_deps_sha)
    needs_rejudge_paths = [int(x["path_group"]) for x in needs_detail]
    text_drift_paths = [int(x["path_group"]) for x in drift_detail]
    judged_floors = [path_floor[no] for no in sorted(by_path)
                     if path_floor[no] is not None]
    unjudged_paths = [no for no in sorted(by_path)
                      if path_floor[no] is None and no not in needs_rejudge_paths]
    unjudged_paths.extend(no for no in expected
                          if no not in by_path and no not in unjudged_paths)
    # 任一路径要重判 ⇒ 命题级不给值（min 依赖每一条路径；少一条就不该报"最小值"）
    level = (None if needs_rejudge_paths
             else (min(judged_floors) if judged_floors else None))
    # `min_of` 升序：于是 `level == min(min_of)` 是一条读得出来的恒等式，
    # 逐行复算的人不必再记得"第几个值才是命题级"。
    min_of = sorted(judged_floors) if level is not None else []
    version = _statement_version(gates)
    # 陈述这一档读数的"来源行"：取历史最小值那一行里最靠后的一条（同档取最近一次）。
    win: Mapping[str, Any] = by_path[sorted(by_path)[0]][-1]
    if level is not None:
        for no in sorted(by_path):
            for row in by_path[no]:
                if _level_from_row(row) == level:
                    win = row
    blocked = bool(needs_rejudge_paths)
    return {"tri": ("computed" if level is not None else "unknown"),
            "level": level, "label": nontriviality_label(level),
            "applicable": True, "matched_by": matched_by,
            "stmt_id": str(win.get("stmt_id") or ""),
            "basis": "" if blocked else str(win.get("basis") or ""),
            "at": "" if blocked else str(win.get("at") or ""),
            "effort": {} if blocked else dict(win.get("effort") or {}),
            "text_truncated": (False if blocked
                               else bool(win.get("text_truncated"))),
            "paths": detail, "min_of": min_of,
            "paths_unjudged": unjudged_paths,
            "partial": bool(unjudged_paths or needs_rejudge_paths),
            "statement_level": level,
            "version": version,
            "deps_state": _deps_state(gates),
            "text_drift": bool(text_drift_paths),
            "paths_text_drift": text_drift_paths,
            "text_drift_detail": drift_detail,
            "paths_needs_rejudge": needs_rejudge_paths,
            "needs_rejudge_detail": needs_detail}


def nontriviality_rows(root: str | Path, *, stmt_id: str = "") -> dict[str, Any]:
    """这条命题在档位台账里的全部原始行（只读；解析只走 `_nontriviality_index`）。

    `nontriviality_of` 折的是"现在读成哪一档"，答不了"这一份材料判过没有" —— 后者要按
    `(stmt_id, judged_body_sha256)` 逐行看（B 的收录动作在判档之前问的正是这一问，
    见 `agent_b.register_statement._prior_filing_nontriviality`）。

    | 结局 | 返回 |
    |---|---|
    | 台账读成了（有 / 没有这一条的行都算读成） | `checked=True` + `rows`（append 顺序） |
    | 台账没读成 | `checked=False` + `why`；调用方不许折成"没判过" |

    "没读成"必须单列：折成"没判过"会让同一份材料被再判一次（多花钱但读数不丢），
    折成"判过了"会让那一笔永远没有档位行（静默丢读数）。所以调用方拿 `checked=False`
    时必须回去正常判一次。
    """
    out: dict[str, Any] = {"checked": False, "rows": [], "why": ""}
    path = nontriviality_path(root)
    if not path.is_file():
        out.update(checked=True, why=f"{path} 不在盘上 ⇒ 这条命题还没有档位行")
        return out
    by_id, _by_sha, why = _nontriviality_index(path)
    if why:
        out["why"] = why
        return out
    want = str(stmt_id or "").strip()
    out.update(checked=True, rows=[dict(r) for r in (by_id.get(want) or [])] if want else [])
    return out


def nontriviality_of(root: str | Path, statement_full: str, *,
                     stmt_id: str = "",
                     path_group: int | None = None,
                     path_groups: Sequence[Any] | None = None,
                     proofs_by_path: Mapping[int, str] | None = None,
                     current_deps_sha: str | None = None) -> dict[str, Any]:
    """这条命题当前的非平凡性档位（折叠旁支台账里同一号 / 同一 sha 的全部行）。

    ## 三级命中（2026-10-26，D16）

    | 级 | 判据 | `matched_by` |
    |---|---|---|
    | 1 | 行上的 `stmt_id` 等于传入的号 | `"stmt_id"` |
    | 2 | 行上的 `statement_sha256` 等于正文的 sha | `"sha256"` |
    | 3 | 都没有 | `""` |

    第一级是命题行与档位之间唯一的关系真身（正文改一个字，号不变，档位照读得到）；
    第二级只为读旧行（写在带号之前、盘上只有 sha），命中时必须自报这是回退。

    ## 折叠（NT2，2026-11-15）

    命中之后交给 :func:`_fold_nontriviality`：按 `(stmt_id, path_group)` 折叠，命题级 =
    各路径的最小值（取历史最小值 ⇒ 永不回升），返回 `paths` / `min_of` /
    `paths_unjudged` / `partial` 供逐行复算。旧行（没有 `path_group`）视为路径 1。
    `path_groups` 是"这一条应该有几条路径"（`statements.manuscripts` 的键）⇒ 没判的
    那几条进 `paths_unjudged`、`partial=true`。

    ## 三态（`tri` 的三个取值不许折平）

    | 结局 | 返回 |
    |---|---|
    | 读到一档 | `{"tri": "computed", "level": 0..4, "label": "T0".."T4", …}` |
    | 该判而没判（没有记录 / 记的是判不了 / 旧刻度的 0） | `{"tri": "unknown", "level": None, "label": "", …}` |
    | 这一问对它不成立（概念行的 `applicable: false`） | `{"tri": "not_applicable", "level": None, "label": "", "applicable": False, …}` |

    `tri="unknown"` 与 `tri="not_applicable"` 在 `level` / `label` 上长得一样，区别只在
    `applicable`：前者要人再去判一次，后者再判也不会有别的结论。页面据此印两个词。

    ## 版本闸与依赖守卫（2026-11-25，TIER-VERSION 问题②）

    业主口径逐字：「非平凡度跟随路径而不跟随稿」。每一行记着判料 sha
    （`judged_body_sha256` = `statement_full + "\\n\\n" + proof`）与研判那一刻的依赖
    指纹（`judged_deps_sha`）；闸在 :func:`_tier_reading` 一处：

    | 轴 | 变了会怎样 |
    |---|---|
    | 正文（按路径的现盘证明） | `text_drift`：信息读数，档位照旧沿用 |
    | 依赖（现盘 vs 研判那一刻） | `needs_rejudge`：不沿用旧档，要重判一次 |

    `proofs_by_path` 是"每条路径现在盘上的证明正文"（`{路径号: 正文}`）：不传、或缺某条
    路径 ⇒ 该路径 `unchecked`（沿用旧档但记"没核过"）。为什么不折成空串：那会把"还没
    读出来"读成"盘上那份证明是空的"。`current_deps_sha` 是现盘依赖集指纹；传 `None`
    ⇒ 没核过依赖 ⇒ `unchecked`（绝不读成"依赖没变"；旧行没有 `judged_deps_sha` 同理）。

    ## 台账只解析一次

    读盘与解析在 `_nontriviality_index` 一处（按 `(st_mtime_ns, st_size)` 缓存）：台账一变
    立刻读到新值，本函数返回新造的 dict（就地改返回值不污染缓存）。
    """
    path = nontriviality_path(root)
    sha = _statement_sha(statement_full)
    if not path.is_file():
        return {"tri": "unknown", "level": NONTRIVIALITY_UNJUDGED, "label": "", "basis": "",
                "applicable": True, "matched_by": "", "stmt_id": "",
                "at": "", "reason": f"{path} 不在盘上 ⇒ 这条命题还没有档位读数",
                "paths": [], "min_of": [],
                "paths_unjudged": [int(x) for x in (path_groups or ())
                                   if str(x).strip().isdigit()],
                "partial": bool(path_groups), "statement_level": None,
                "version": NT_VERSION_UNCHECKED, "deps_state": "unchecked",
                "text_drift": False, "paths_text_drift": [],
                "text_drift_detail": [], "paths_needs_rejudge": [],
                "needs_rejudge_detail": []}
    by_id, by_sha, why = _nontriviality_index(path)
    if why:
        return {"tri": "unknown", "level": NONTRIVIALITY_UNJUDGED, "label": "", "basis": "",
                "applicable": True, "matched_by": "", "stmt_id": "",
                "at": "", "reason": why, "effort": {}, "text_truncated": False,
                "paths": [], "min_of": [], "paths_unjudged": [], "partial": False,
                "statement_level": None,
                "version": NT_VERSION_UNCHECKED, "deps_state": "unchecked",
                "text_drift": False, "paths_text_drift": [],
                "text_drift_detail": [], "paths_needs_rejudge": [],
                "needs_rejudge_detail": []}
    want = str(stmt_id or "").strip()
    hit_rows = list(by_id.get(want) or []) if want else []
    # 按号那一支仍过 `_row_matches_stmt_id`：它是"按号关联"的唯一判据，也是反真空判据
    # （`tests/test_nontriviality_is_joined_by_stmt_id.py` 的 e 条）打桩的那一格。索引只是
    # "读盘/解析一次"的缓存，不许把这条判据绕过去。
    if hit_rows and not any(_row_matches_stmt_id(r, stmt_id) for r in hit_rows):
        hit_rows = []
    matched_by = "stmt_id" if hit_rows else ""
    if not hit_rows:
        cand = list(by_sha.get(sha) or [])
        if cand:
            hit_rows, matched_by = cand, "sha256"
    if not hit_rows:
        got = _fold_nontriviality([], matched_by="", statement_full=statement_full,
                                  proofs_by_path=proofs_by_path,
                                  expected_deps_sha=current_deps_sha)
        got["reason"] = "台账里没有这条命题的档位读数"
        got["paths_unjudged"] = [int(x) for x in (path_groups or ())
                                 if str(x).strip().isdigit()]
        got["partial"] = bool(got["paths_unjudged"])
        return got
    return _fold_nontriviality(hit_rows, matched_by=matched_by,
                               path_group=path_group, path_groups=path_groups,
                               statement_full=statement_full,
                               proofs_by_path=proofs_by_path,
                               expected_deps_sha=current_deps_sha)
