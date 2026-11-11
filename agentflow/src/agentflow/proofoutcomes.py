"""登记 / 重写这两档的「结局读数」（2026-11-11 从 `proofregistry.py` 拆出）。

## 为什么有这一份

`proofregistry.py` 正好落在 `>800` 那条线上（800 行），而 `register_or_rewrite` 又越过
200 行 —— 业主口径是基线不许抬，所以不往那份文件里加东西：把 `register_or_rewrite`
里两段「不碰稿件字节、只决定这一笔怎么读」的逻辑搬到本模块：

1. `form_gate_reading` —— 新命题登记前跑一次 F 秘书的形态闸，把「放行 / 受控拒 /
   闸自己炸了（fail-closed）」解释成同一形状的读数；
2. `preserved_reading` —— 幂等那一格：同一份正文再挂一次 ⇒ 一个字节都不动（版本号也
   不涨），读数说 `preserved=True`。

受控码也在这里定义（`REFUSED_*` 六格）：它们只被这两段用来拼读数 —— 搬出去之后
`proofregistry` 仍然 `from .proofoutcomes import ...` 回引同样的名字，公开面与
受控码字符串一个字没变（其他模块按 `proofregistry.REFUSED_*` 取用的写法照旧可读）。

## 依赖方向

本模块不在顶层 import `proofregistry`：`preserved_reading` 只在需要时（真的幂等那一
刻）惰性取 `proof_sha` / `section_hashes` 的既有实现 —— 那是同一把尺，不另写一份。
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

#: 受控码（写读两侧共用，不另起第二套词；定义点 2026-11-11 从 `proofregistry` 搬来）。
REFUSED_TEXT_CHANGED = "proposition_text_changed"
REFUSED_GATE = "proposition_form_refused"
REFUSED_PATH = "manuscript_path_unavailable"
REFUSED_READ = "manuscript_unreadable"
REFUSED_WRITE = "manuscript_write_failed"
REFUSED_SHAPE = "manuscript_shape_refused"


def form_gate_reading(
    gate: Callable[..., Mapping[str, Any]], *, proposition: Any, kind: Any,
    proof_text: Any, label: Any, entry: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """跑一次 F 秘书的形态闸 ⇒ `(闸读数, 拒收时的那几格)`；放行时第二格是 `None`。

    闸自己抛了 = 没判成（fail-closed），不是"没问题"：这一格换成一条
    `checked=False` 的拒收读数。为什么值得单独一格：`register_or_rewrite` 已经两百行，
    这段"跑闸 / 解释拒收"是其中唯一不碰稿件字节的一段，搬成纯函数后
    `register_or_rewrite` 只保留"调用它、拿到拒收就返回"。
    """
    try:
        reading = dict(gate(statement_full=str(proposition or ""),
                            kind=str(kind or ""), body=str(proof_text or ""),
                            label=str(label or "")) or {})
    except Exception as exc:  # noqa: BLE001 —— 闸自己炸了 = 没判成（fail-closed）
        reading = {"checked": False, "well_formed": False, "submittable": False,
                   "refused": REFUSED_GATE,
                   "reason": f"形态闸抛了（{type(exc).__name__}: {exc}）⇒ 没判成",
                   "problems": []}
    if reading.get("submittable"):
        return reading, None
    problems = [str(x) for x in (reading.get("problems") or [])]
    refusal = {
        "checked": bool(reading.get("checked", False)),
        "refused": REFUSED_GATE,
        "problems": problems,
        "why": ("命题形态闸没放行 ⇒ 这一条不登记、不落盘（手稿一个字节都没写）："
                + str(reading.get("reason") or "形态不合规")
                + ("；逐条缺什么：" + "；".join(problems[:4])
                   if problems else "")),
        "entry": dict(entry),
    }
    return reading, refusal


def preserved_reading(
    entry: Mapping[str, Any], *, mode: str, rewritten: bool, new_fp: str,
    proof_text: Any, old_text: str,
    dependency_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any] | None:
    """幂等那一格：同一份正文再挂一次 ⇒ `register_or_rewrite` 要 `out.update(...)` 的键。

    三条判据（`MODE_REWRITTEN` ＋ 命题指纹 ＋ 正文 sha）都成立 ⇒ 一个字节都不动、
    `preserved=True`；否则 `None`（调用方照常往下走）。

    为什么 `section_hashes` / `proof_sha` 惰性取：它们是 `proofregistry` 的公开名
    （同一把尺），顶层 import 会把依赖方向倒过来；这一刻真的幂等，取一次不贵。
    """
    from . import proofregistry as _PR  # 惰性：依赖方向 proofregistry → 本模块

    if not (rewritten
            and str(entry.get("fingerprint") or "") == str(new_fp or "")
            and _PR.proof_sha(proof_text) == str(entry.get("sha256") or "")):
        return None
    return {
        "ok": True, "checked": True, "mode": mode,
        "proof_no": int(entry.get("proof_no") or 1),
        "sha256": str(entry.get("sha256") or ""),
        "deps_rows": [dict(r) for r in (dependency_rows or [])],
        "written": False, "preserved": True, "entry": dict(entry),
        "section_hashes": _PR.section_hashes(old_text), "why": "",
    }
