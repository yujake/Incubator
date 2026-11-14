"""登记 / 重写这两档的「结局读数」。

`register_or_rewrite` 里有三段「不碰稿件字节、只决定这一笔怎么读」的逻辑：

1. :func:`form_gate_reading` —— 新命题登记前跑一次 F 秘书的形态闸，把
   「放行 / 受控拒 / 闸自己炸了（fail-closed）」解释成同一形状的读数；
2. :func:`manuscript_artifact` —— 稿落盘之后补一条产物归属（`ARTIFACTS.jsonl`）；
   失败时把「写成了、没归属」写进调用方的读数（`ok=False`，但 `written=True`）；
3. :func:`preserved_reading` —— 幂等那一格：同一份正文再挂一次 ⇒ 一个字节都不动
   （版本号也不涨），读数说 `preserved=True`。

受控码 `REFUSED_*` 六格也只在这里定义，`proofregistry` 按名字回引它们 ——
公开面与受控码字符串不变。

依赖方向：本模块不 import `proofregistry`；`preserved_reading` 只在真到幂等那一刻
惰性取 `proof_sha` / `section_hashes`，同一把尺不另写一份。
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


def manuscript_artifact(out: dict[str, Any], root: Any, *, rel: Any, family: Any,
                        mode: Any) -> bool:
    """把刚落盘的手稿登进 `<工作区>/ARTIFACTS.jsonl`；返回"登记成了吗"。

    失败时把该写进调用方读数的那几格直接更新到 `out` 上（`ok=False` /
    `refused=REFUSED_WRITE` / `written=True` / `why` 点名），调用方只需
    `if not ...: return out`。`written=True` 是刻意的：稿真的在盘上，缺的是归属 ——
    把它折成"没写成"会让下一个人去查一件没发生的事。

    为什么住在 `proofoutcomes` 而不是 `proofregistry`：它是"登记这一步的结局读数"
    （与 :func:`form_gate_reading` / :func:`preserved_reading` 同族），而
    `proofregistry` 的体量软基线不许因为补一条读数往上抬
    （`tests/test_repo_survey_does_not_get_worse.py`）。

    `family` 在调用方是 `manuscriptform.FAMILY_F` / `FAMILY_B`（"F" / "B"）；
    台账的 `kind` 用族名（`f-proof-manuscript`）—— 读台账的人按族筛，不按那个
    内部字母筛。`sha256` 由 `artifacts.record` 从盘上现算，不接收调用方手里那把
    正文尺（「## 证明」的 sha 与整份文件的 sha 不相等是对的）。
    """
    from . import artifacts as A

    name = {"F": "f-proof", "B": "b-proof"}.get(str(family or ""), str(family or ""))
    role = {"f-proof": "F", "b-proof": "B", "e-proof": "E", "e-num": "E"}.get(name, "") or "M"
    _entry, problem = A.record_or_problem(
        root, path=rel, producer=role,
        kind=f"{name}-manuscript" if name else "manuscript",
        note=f"手稿 `{rel}`（proofregistry.register_or_rewrite，mode={mode}）")
    if not problem:
        return True
    out.update(checked=True, ok=False, refused=REFUSED_WRITE, written=True,
               manuscript_path=str(rel), why=(
                   f"手稿写成了（{rel}），但产物归属没登记成：{problem} "
                   "⇒ 这一笔按失败报：没有归属的稿不进收工链。"
                   f"补登记：`agentflow artifacts record {rel} --producer {role}`"))
    return False


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
