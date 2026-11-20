# -*- coding: utf-8 -*-
"""秘书的档位读侧（折叠与三态，从 secretary.py 的 U25 中段逐字搬出）。

我保证哪条不变式：一路径一行；命题级读数取该命题全部路径的历史 min（不回升）—— 「曾经判过低」不能被后面的重判抬上去。

## 为什么它能单独成文件（依赖方向）

`secretary_tier_ledger` 只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

（`secretary_tier_ledger` 这一份）类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
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

    业主 2026-11-01 裁定审美轴三格退场之后，写侧与新行只产生 `T0`…`T4` / `null`；
    但 `out/secretary/<角色>.jsonl` 是 append-only 的，旧行里还有三个词。读旧行时按
    这张表折算（这是"旧词"在源码里仅存的落点，判据钉着它只许出现在这里）：

    | 老 `decision` | 折算出的档位 | 判据 |
    |---|---|---|
    | `T0`…`T4` | 同名档位 | 2026-11-01 那一笔的兼容形状 |
    | `太平凡` | T0 | 这个结论只剩"力气小 ⇒ 落 T0"这一层意思 |
    | `合格` | `judge.nontriviality` / 同号 `nontriviality.jsonl` 那一行；都没有 ⇒ 未判 | 它当年只表示"收"，从不携带档位 |
    | `判不了` | 未判（`None`） | 它是"该判而没判"，不是一档 |

    优先级：decision 能解析成档位 ⇒ 用它；否则 `太平凡` ⇒ 0；否则读 `nontriviality`
    （先看行上的 `judge.nontriviality`，再看同级的 `nontriviality`）。新旧两套字段同时
    出现且冲突时 decision 胜 —— 2026-11-01 起它才是唯一的主字段。

    这一格只回答"这一行说的是哪一档"，不回答"这一行是不是判过了"：`None` 既可能是
    "判不了"也可能是"没查成"，那要读 `judge.checked`（新行）或 `fail_open`（旧行），
    不要把两者折成一档。
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


def append_nontriviality(root: str | Path, *, statement_full: str, level: Any,
                         basis: str = "", role: str = "", task_id: str = "",
                         stmt_id: str = "",
                         effort: Mapping[str, Any] | None = None,
                         text_truncated: bool = False,
                         applicable: bool = True,
                         path_group: int = 0,
                         judged_body_sha256: str = "",
                         landed_body_sha256: str = "",
                         scope: str = "") -> None:
    """追加一行档位读数（append-only；显式 LF，Windows 上不留 CRLF）。

    `level` 给 `None`（或缺省/坏值）⇒ 这一行记的是"判不了"：`nontriviality: null`
    且 `label` 空。判不了照旧落一行 —— 它也是读数（"没人判过"与"台账里没这一条"
    在盘上应当分得开）。

    ## 一个路径一行（NT2，2026-11-15 业主裁定）

    业主口径：「非平凡度应该是一个路径一个，现在的实现是一个命题一个需要补加」。
    所以行上多三格：

    | 格 | 含义 |
    |---|---|
    | `path_group` | 这是第几条证明路径的读数（`>=1`）；`0` = statement-scope（概念行的"不适用"） |
    | `scope` | `"path"` / `"statement"`；旧行没有这一格 ⇒ 按旧语义读（无路径维 = 路径 1） |
    | `judged_body_sha256` | 判的那一刻手里的材料（命题 + 空行 + 证明，见 :func:`_judged_body_sha`） |
    | `landed_body_sha256` | 落盘那一行的 `statement_full` 的 sha —— 与上一格分开记，才能回答"判的是不是落的那一版" |

    旧行（没有 `path_group`）由读侧视为路径 1（改前判的就是 canonical 那份证明）。

    ## 为什么带号（2026-10-26，D16）
    这一行说的是"哪个命题的档位"，而命题行的身份是 `stmt_id`。按正文 sha 关联会把
    "改了一个字"读成"没判过"：真机 mp3-r3 的第 1 行（316 字）就是这样 —— 判档用的是
    登记前的入参，落盘行与它不逐字相同，于是那一档从页面上消失。所以新行必须带号；
    旧行没有这一格 ⇒ 读侧那条按 sha 的回退只为读旧行（见 :func:`nontriviality_of`）。

    `stmt_id` 缺省是空串只服务"没有登记这一笔"的旧调用面与测试直调。判/落拆段之后
    生产面只有一个落点（:meth:`Secretary.record_nontriviality`），它在落之前先要求
    号与路径号：拿不到就不落（并留 `unrecorded` 痕迹），不许再落出 `stmt_id` 为空的
    孤儿读数（真机 4 条对不上任何命题行的行就是这么来的）。

    ## `applicable` 为什么是第四根轴（2026-10-26，D15'）
    "判不了"与"不需要判"是两件事：前者说该判而没判（缺正文 / 被截断 / 没缝），
    后者说这一问对这一行不成立（概念行没有证明正文）。改前它们只能靠 `basis` 那句话
    分辨，于是读侧（`nontriviality_of` 与页面）把两者都读成"没有档位"、印同一个"未判"。
    所以这一格显式落进台账：`applicable=False` 的那一行，`level` 恒为 `None`（不适用
    不可能是某一档），`label` 恒为空串，读侧据它把 `tri` 读成 `not_applicable`。
    老行没有这一格 ⇒ 按 `True` 读（与它们写下来时的语义一致）。

    ## `effort` 为什么也落下来（2026-10-24，B2）
    档位从这一天起是"证明花的力气"给的，而力气是四项读数 + 一个分数。只落档位的话，
    读的人（人、页面、复算脚本）无法判断"这一档是读数给的还是模型随口给的"——
    而后者正是改前那个形态。所以四项读数、分数与边界表里的那一档一起落进这一行：
    复算的人拿 `proof_effort_readings` 的几项读数一比，就能看出秘书判档时手里有什么材料。

    `text_truncated` 同理落下来：它是"这一行判不了"的一个具体原因，与"缺某项读数"、
    "判了"三者在盘上必须分得开（三态纪律的第四格：输入不完整也是一种没查成）。
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

    两个索引都把每一行按 append 顺序收进列表（改前是"最后一行胜"的标量）。
    为什么要整串：读侧要按 `(stmt_id, path_group)` 折叠成"路径级最后一行"与
    "命题级 = 各路径的历史最小值"，只留最后一行就把路径/历史两样信息都丢了
    （真机错读数：先 T0 后 T3 读回 T3；多路径互相覆盖）。

    坏行（不是 JSON / 不是对象）跳过，与原来一致；"文件读不出来"如实返回原因，由调用方
    落成"没有这条命题的读数"（不是"这条命题是 T1"）。
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


def _fold_nontriviality(rows: Sequence[Mapping[str, Any]], *, matched_by: str,
                        path_group: int | None = None,
                        path_groups: Sequence[Any] | None = None) -> dict[str, Any]:
    """把同一命题的台账行折叠成一条读数（唯一实现；读侧三处读点共用）。

    ## 折叠规则（业主 2026-11-15 的五条硬约束落到读侧）

    | 规则 | 实现 |
    |---|---|
    | 一个路径一行 | 按 `path_group` 分组；旧行（无这一格）= 路径 1 |
    | 路径级 = 该路径最后一行 | 同一路径重判允许升降（T4 造出梯子 ⇒ 降到 T2 是正常路径） |
    | 命题级 = 各路径非平凡度的最小值 | `level = min(min_of)`，`min_of` 是各路径的历史最小值 |
    | 已有值 ⇒ min(原值, 本次) | 取历史最小值 ⇒ 命题级永不回升（新增路径 / 同路径判得更难都抬不上去） |
    | 部分路径未判 ⇒ `partial=true` | `paths_unjudged` 点名；不许把"部分没判"折成"全判了" |

    为什么路径级用"最后一行"、命题级用"历史最小值"：业主口径里这两条要同时成立。
    路径换了一份更难的证明（T1→T3）⇒ 那条路径的当前值该是 T3；而"命题台账已有值取
    min"⇒ 命题级仍是 T1。两者不矛盾：`paths[].level` 给当前值，`min_of` 给命题级
    这个 min 从哪几个值来（每个路径的历史最小值），读的人能逐行复算。

    ## 返回

    `{tri, level, label, applicable, matched_by, basis, at, stmt_id, effort,
    text_truncated}`（旧键逐字不动）+ `paths` / `min_of` / `paths_unjudged` /
    `partial`。`path_group>=1` 时返回该路径的读数（`level` = 该路径最后一行），
    并把命题级另放在 `statement_level`。
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
                "statement_level": None}

    if want_path is not None:
        seq = by_path.get(want_path) or []
        if not seq:
            got = _unjudged(f"第 {want_path} 条路径还没有档位读数")
            got["paths_unjudged"] = [want_path]
            got["partial"] = True
            return got
        last = seq[-1]
        level_here = _level_from_row(last)
        levels = [x for x in (_level_from_row(r) for r in seq) if x is not None]
        floor = min(levels) if levels else None
        floors_all = [min([x for x in (_level_from_row(r) for r in by_path[no])
                           if x is not None] or [None])
                      for no in sorted(by_path)]
        stmt_level = min([x for x in floors_all if x is not None]) if floors_all else None
        return {"tri": ("computed" if level_here is not None else "unknown"),
                "level": level_here, "label": nontriviality_label(level_here),
                "applicable": True, "matched_by": matched_by,
                "stmt_id": str(last.get("stmt_id") or ""),
                "basis": str(last.get("basis") or ""),
                "at": str(last.get("at") or ""),
                "effort": dict(last.get("effort") or {}),
                "text_truncated": bool(last.get("text_truncated")),
                "path_group": want_path,
                "paths": [{"path_group": want_path, "level": level_here,
                           "floor": floor,
                           "label": nontriviality_label(level_here),
                           "at": str(last.get("at") or ""),
                           "stmt_id": str(last.get("stmt_id") or ""),
                           "basis": str(last.get("basis") or ""),
                           "judged_body_sha256": str(last.get("judged_body_sha256") or ""),
                           "landed_body_sha256": str(last.get("landed_body_sha256") or ""),
                           "rows": len(seq)}],
                "min_of": [floor] if floor is not None else [],
                "paths_unjudged": ([] if floor is not None else [want_path]),
                "partial": bool(floor is None), "statement_level": stmt_level}

    if not by_path:
        if concept:
            last = concept[-1]
            return {"tri": "not_applicable", "level": None, "applicable": False,
                    "label": "", "basis": str(last.get("basis") or ""),
                    "at": str(last.get("at") or ""), "matched_by": matched_by,
                    "stmt_id": str(last.get("stmt_id") or ""), "effort": {},
                    "text_truncated": False, "paths": [], "min_of": [],
                    "paths_unjudged": [], "partial": False, "statement_level": None}
        return _unjudged("台账里没有这条命题的档位读数")

    path_floor: dict[int, int | None] = {}
    detail: list[dict[str, Any]] = []
    for no in sorted(by_path):
        seq = by_path[no]
        last = seq[-1]
        levels = [x for x in (_level_from_row(r) for r in seq) if x is not None]
        floor = min(levels) if levels else None
        path_floor[no] = floor
        detail.append({
            "path_group": no, "level": _level_from_row(last), "floor": floor,
            "label": nontriviality_label(_level_from_row(last)),
            "at": str(last.get("at") or ""),
            "stmt_id": str(last.get("stmt_id") or ""),
            "basis": str(last.get("basis") or ""),
            "judged_body_sha256": str(last.get("judged_body_sha256") or ""),
            "landed_body_sha256": str(last.get("landed_body_sha256") or ""),
            "rows": len(seq)})
    judged_floors = [path_floor[no] for no in sorted(by_path)
                     if path_floor[no] is not None]
    unjudged_paths = [no for no in sorted(by_path) if path_floor[no] is None]
    unjudged_paths.extend(no for no in expected
                          if no not in by_path and no not in unjudged_paths)
    level = min(judged_floors) if judged_floors else None
    # `min_of` 升序：于是 `level == min(min_of)` 是一条读得出来的恒等式，
    # 逐行复算的人不必再记得"第几个值才是命题级"。
    min_of = sorted(judged_floors)
    # 陈述这一档读数的"来源行"：取历史最小值那一行里最靠后的一条（同档取最近一次）。
    win: Mapping[str, Any] = by_path[sorted(by_path)[0]][-1]
    if level is not None:
        for no in sorted(by_path):
            for row in by_path[no]:
                if _level_from_row(row) == level:
                    win = row
    return {"tri": ("computed" if level is not None else "unknown"),
            "level": level, "label": nontriviality_label(level),
            "applicable": True, "matched_by": matched_by,
            "stmt_id": str(win.get("stmt_id") or ""),
            "basis": str(win.get("basis") or ""),
            "at": str(win.get("at") or ""),
            "effort": dict(win.get("effort") or {}),
            "text_truncated": bool(win.get("text_truncated")),
            "paths": detail, "min_of": min_of,
            "paths_unjudged": unjudged_paths,
            "partial": bool(unjudged_paths), "statement_level": level}


def nontriviality_rows(root: str | Path, *, stmt_id: str = "") -> dict[str, Any]:
    """这条命题在档位台账里的全部原始行（只读；解析只走 `_nontriviality_index`）。

    ## 它答的那一问

    `nontriviality_of` 折的是"这条命题现在读成哪一档"（命题级取各路径历史 min），
    它答不了"这一份材料判过没有" —— 后者要按 `(stmt_id, judged_body_sha256)`
    逐行看。B 的收录动作在判档之前问的正是这一问（业主 2026-11-19：同一份材料只能
    判一次，见 `agent_b.register_statement._prior_filing_nontriviality`）。

    ## 三态

    | 结局 | 返回 |
    |---|---|
    | 台账读成了（有 / 没有这一条的行都算读成） | `checked=True` + `rows`（append 顺序） |
    | 台账没读成 | `checked=False` + `why`；调用方不许折成"没判过" |

    为什么"没读成"要单列：折成"没判过"会让同一份材料被再判一次（多花钱但读数不丢）；
    折成"判过了"则会让那一笔永远没有档位行（静默丢读数）。前者是可接受的代价，
    后者是这次要修的缺陷 —— 所以调用方拿 `checked=False` 时必须回去正常判一次。
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
                     path_groups: Sequence[Any] | None = None) -> dict[str, Any]:
    """这条命题当前的非平凡性档位（折叠旁支台账里同一号 / 同一 sha 的全部行）。

    ## 三级命中（2026-10-26，D16）

    | 级 | 判据 | `matched_by` |
    |---|---|---|
    | 1 | 行上的 `stmt_id` 等于传入的号 | `"stmt_id"` |
    | 2 | 行上的 `statement_sha256` 等于正文的 sha | `"sha256"` |
    | 3 | 都没有 | `""` |

    第一级是命题行与档位之间唯一的关系真身：正文改一个字，号不变，档位照读得到。
    第二级只为读旧行（那些行写在带号之前，盘上只有 sha）；它命中时 `matched_by`
    必须说清这是回退 —— 否则"按文本兜底"会重新长成第二处真身。

    ## 折叠（NT2，2026-11-15）

    命中之后交给 :func:`_fold_nontriviality`：按 `(stmt_id, path_group)` 折叠，
    命题级 = 当前各路径的最小值（且取历史最小值 ⇒ 永不回升），并返回 `paths` /
    `min_of` / `paths_unjudged` / `partial` 供逐行复算。旧行（没有 `path_group`）
    视为路径 1 —— 迁移不读废历史（判据见 `tests/test_nontriviality_is_per_path.py`）。

    `path_group`（可选）：只问某一条路径的读数（`level` 是该路径最后一行，
    `statement_level` 另给命题级）。`path_groups`（可选）：调用方知道这一条命题
    应该有几条路径（`statements.manuscripts` 的键）⇒ 没判的那几条进 `paths_unjudged`，
    `partial=true`，不许折成"全判了"。

    ## 三态（`tri` 的三个取值不许折平）

    | 结局 | 返回 |
    |---|---|
    | 读到一档 | `{"tri": "computed", "level": 0..4, "label": "T0".."T4", …}` |
    | 该判而没判（没有记录 / 记的是判不了 / 旧刻度的 0） | `{"tri": "unknown", "level": None, "label": "", …}` |
    | 这一问对它不成立（概念行的 `applicable: false`） | `{"tri": "not_applicable", "level": None, "label": "", "applicable": False, …}` |

    `tri="unknown"` 与 `tri="not_applicable"` 在 `level` / `label` 上长得一样，区别只在
    `applicable` 这一格：前者要人再去判一次，后者再判也不会有别的结论（2026-10-26）。
    读侧（页面）据此印两个不同的词（`不适用` / `未判`）。

    ## 台账只解析一次（2026-10-27，R-BE1 的 ⑥-3）

    读盘与逐行解析在 `_nontriviality_index` 一处，索引按 `(st_mtime_ns, st_size)` 缓存：
    收工读数与网页那一栏都是逐条命题问一次的，改前每条命题都把整份台账读一遍。
    三个边界写在那儿：台账一变（追加 / 就地改 + 改 mtime）立刻读到新值；缓存里是解析后的
    行、本函数返回的是新造的 dict（就地改返回值不污染缓存）；绕开本函数去改缓存行
    则会污染"这个进程眼里的台账"（本模块不导出那个索引）。
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
                "partial": bool(path_groups), "statement_level": None}
    by_id, by_sha, why = _nontriviality_index(path)
    if why:
        return {"tri": "unknown", "level": NONTRIVIALITY_UNJUDGED, "label": "", "basis": "",
                "applicable": True, "matched_by": "", "stmt_id": "",
                "at": "", "reason": why, "effort": {}, "text_truncated": False,
                "paths": [], "min_of": [], "paths_unjudged": [], "partial": False,
                "statement_level": None}
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
        got = _fold_nontriviality([], matched_by="")
        got["reason"] = "台账里没有这条命题的档位读数"
        got["paths_unjudged"] = [int(x) for x in (path_groups or ())
                                 if str(x).strip().isdigit()]
        got["partial"] = bool(got["paths_unjudged"])
        return got
    return _fold_nontriviality(hit_rows, matched_by=matched_by,
                               path_group=path_group, path_groups=path_groups)
