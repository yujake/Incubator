# -*- coding: utf-8 -*-
"""`R6-R1d-3` 的接线判据（`R7-R1d-2`）：时间戳次序的判定侧与写入侧两处都要有测试守着。

## 为什么这条用例必须存在（`R7-R1d-2` 的实测）

`R6-R1d-3`（时间戳次序判据）当时没有任何测试守着它的接线：`R1d` 把整棵`agentflow/` 复制到 temp、只把判定侧那一处 `if order_problem:` 改成 `if False:`，
同一批四个冻结测试文件跑出 159 passed。也就是说那一处接线可以被整段删掉而测试全绿—— 形态与 `R6-R1d-1`（库函数有牙、入口没人跑）同族，也与 `R6-AN-1`（判据可以静默变真空）同族。

本文件给两处各一条：

- 判定侧：手写台账里三条 `at` 倒挂（03:00 → 02:00 → 01:00）⇒
`unapproved` / `REASON_AUDIT_TIMESTAMPS_ORDER`；三条递增 ⇒ `approved`（不误伤）；
- 写入侧：向已有审计的条目追加一条更早的 `at` ⇒ `LedgerError`（`record_audit` 拒收）；
- 以及一条注入负控（本仓的硬要求）：把整棵树复制到 `tmp_path`，只把判定侧那两行
改成 `if False:`，用子进程跑本文件本身 ⇒ 上面那两条断言必须变红，并打印副本 sha256与"锚点恰好命中 1 次"的断言（防"锚点漂了却静默通过"）。

`tmp_path` 下的整树副本用已收集的文件清单来复制（不写死目录名）：漏掉一整个目录时，子进程 `pytest` 会在"收集不到测试"上报错退出（非 0）⇒ 那条注入负控会以"预期红"的面目假绿。
清单法把这件事变成"复制了什么就是什么"。
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts import noai_gate as G  # noqa: E402

#: 本文件的 pytest 节点 id（注入负控要用子进程只跑这一条）。
_NODE = "tests/test_noai_gate_timestamp_order.py::test_descending_audit_timestamps_are_rejected"

#: 倒挂与递增两组 `at`（同一批审计者/维度/scope，唯一变量是次序）。
_DESCENDING = ("2026-09-27T03:00:00+08:00", "2026-09-27T02:00:00+08:00", "2026-09-27T01:00:00+08:00")
_ASCENDING = ("2026-09-27T01:00:00+08:00", "2026-09-27T02:00:00+08:00", "2026-09-27T03:00:00+08:00")

_AT = "2026-09-27T00:00:00+08:00"
_SCOPES = ("src/a.py alpha", "src/a.py beta", "src/a.py gamma")
_SHA = "a" * 64
_NC = ("负控：拿改前那一版（`git show HEAD:src/a.py`）跑同一套判据 —— "
       "改前那一版没有 `alpha` 这个符号，判据必须报红，否则说明它没有分辨力。")
_INDEP = "我是子审计代理 R7，与该条目的作者不是同一主体（署名者未知）"
_TARGET_SRC = (
    '"""R7 测试的被审对象：定义了 alpha / beta / gamma / delta。"""\n'
    "\n"
    "alpha = 1\n"
    "beta = 2\n"
    "gamma = 3\n"
    "delta = 4\n"
    "\n"
    "\n"
    "def total() -> int:\n"
    "    return alpha + beta + gamma + delta\n"
)


def _root(tmp_path: pathlib.Path):
    """合成小世界：真实可解析的被审对象 + 清单 + 三条证据文件。"""
    root = tmp_path / "repo"
    rel = "src/a.py"
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_TARGET_SRC, encoding="utf-8", newline="\n")
    (root / G.MANIFEST_NAME).write_text(
        "[category: auth-audit] 夹具用的分组\n\n"
        f"{rel}  [category: auth-audit]  夹具用的条目\n",
        encoding="utf-8", newline="\n",
    )
    return root, rel


def _audit(root: pathlib.Path, sha: str, *, auditor: str, dimension: str, scope: str,
           at: str, tag: str) -> dict:
    ev = root / "temp" / f"ev-{tag}.txt"
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text(
        f"审计者标识（独立词）：{auditor}\n开审版本 sha256 = {sha}\n"
        f"覆盖 scope 符号：{scope}\n{_NC}\n（这条证据属于 {tag}）\n",
        encoding="utf-8", newline="\n",
    )
    return {
        "auditor": auditor, "dimension": dimension, "at": at, "sha256": sha,
        "evidence": f"temp/ev-{tag}.txt", "negative_control": _NC, "findings": [],
        "scope": scope, "evidence_path": str(ev), "evidence_sha256": G.sha256_file(ev),
        "audit_started_sha256": sha, "independence": _INDEP,
    }


def _judge(root: pathlib.Path, rel: str, audits: list[dict]) -> dict:
    """把台账手写到盘上（+ 真回执链），再走真判定侧读回来判。"""
    import json

    sha = G.sha256_file(root / rel)
    (root / G.LEDGER_NAME).write_text(json.dumps({
        "ledger_version": G.LEDGER_VERSION, "generated_at": _AT,
        "entries": [{"path": rel, "glob": rel, "category": "auth-audit", "sha256": sha,
                     "authored": "unknown", "authored_basis": "inferred",
                     "change_note": "夹具", "reviewers": [], "audits": audits}],
    }, ensure_ascii=False), encoding="utf-8", newline="\n")
    receipt = root / G.AUDIT_RECEIPT_NAME
    receipt.unlink(missing_ok=True)
    for a in audits:
        G.append_receipt(action="record_audit", path=rel, entry_sha256=sha,
                         detail=f"{a['auditor']}/{a['dimension']}", log_path=receipt, root=root)
    return G.evaluate_approval(
        rel, entry=G.load_ledger(root / G.LEDGER_NAME).entry_for(rel), current_sha256=sha,
        is_ledger_itself=False, repo=root, receipt_log=receipt,
    )


def _three(root: pathlib.Path, sha: str, ats: tuple[str, ...]) -> list[dict]:
    return [
        _audit(root, sha, auditor=f"r7-T{i}", dimension=d, scope=sc, at=at, tag=f"{d}")
        for i, (d, sc, at) in enumerate(zip(("axes", "roles", "errors"), _SCOPES, ats))
    ]


def test_descending_audit_timestamps_are_rejected(tmp_path: pathlib.Path) -> None:
    """判定侧正控：三条 `at` 倒挂 ⇒ 不放行，理由码是次序那一条。

    与它成对的是同一条用例里的递增形态（必须 `approved`）：只测"倒挂被拒"会漏掉
    "判据把一切时间戳都拒了"这个方向。
    """
    root, rel = _root(tmp_path)
    sha = G.sha256_file(root / rel)

    ok = _judge(root, rel, _three(root, sha, _ASCENDING))
    assert ok["approval_status"] == "approved", ok.get("detail")
    assert ok["approval_reason"] == G.REASON_APPROVED

    bad = _judge(root, rel, _three(root, sha, _DESCENDING))
    assert bad["approval_status"] == "unapproved", bad.get("detail")
    assert bad["approval_reason"] == G.REASON_AUDIT_TIMESTAMPS_ORDER, bad["approval_reason"]
    assert "倒挂" in bad["detail"], bad["detail"]
    # 判据本体也要有名字（这一条与接线分开：函数对、接线没接的情形由注入负控守）
    assert G.audit_timestamps_not_monotonic(
        tuple(G.ReviewAudit(**a) for a in _three(root, sha, _DESCENDING))) != ""
    assert G.audit_timestamps_not_monotonic(
        tuple(G.ReviewAudit(**a) for a in _three(root, sha, _ASCENDING))) == ""


def test_record_audit_refuses_to_append_an_earlier_timestamp(tmp_path: pathlib.Path) -> None:
    """写入侧正控：向已有审计的条目追加一条更早的 `at` ⇒ `LedgerError`（`R6-R1d-3`）。

    这一半此前同样没有测试守着（`R7-R1d-2` 的 `fix` 字段点名了它）。
    """
    import json

    root, rel = _root(tmp_path)
    sha = G.sha256_file(root / rel)
    first = _audit(root, sha, auditor="r7-W1", dimension="axes", scope=_SCOPES[0],
                   at="2026-09-27T02:00:00+08:00", tag="w1")
    (root / G.LEDGER_NAME).write_text(json.dumps({
        "ledger_version": G.LEDGER_VERSION, "generated_at": _AT,
        "entries": [{"path": rel, "glob": rel, "category": "auth-audit", "sha256": sha,
                     "authored": "unknown", "authored_basis": "inferred",
                     "change_note": "夹具", "reviewers": [], "audits": [first]}],
    }, ensure_ascii=False), encoding="utf-8", newline="\n")
    receipt = root / G.AUDIT_RECEIPT_NAME
    receipt.unlink(missing_ok=True)

    later = _audit(root, sha, auditor="r7-W2", dimension="roles", scope=_SCOPES[1],
                   at="2026-09-27T03:00:00+08:00", tag="w2")
    earlier = _audit(root, sha, auditor="r7-W3", dimension="errors", scope=_SCOPES[2],
                     at="2026-09-27T01:00:00+08:00", tag="w3")

    def _append(a: dict, now: "G._dt.datetime"):
        return G.record_audit(
            G.load_ledger(root / G.LEDGER_NAME), rel, auditor=a["auditor"],
            dimension=a["dimension"], evidence=a["evidence"], negative_control=_NC,
            evidence_path=a["evidence_path"], scope=a["scope"],
            audit_started_sha256=sha, independence=_INDEP, root=root, receipt_log=receipt,
            now=now,
        )

    tz = G._dt.timezone(G._dt.timedelta(hours=8))
    # 正控：`now` 比台账里最后一条更晚 ⇒ 写得进去
    _led, info = _append(later, G._dt.datetime(2026, 9, 27, 4, 0, 0, tzinfo=tz))
    assert info["audits"] == 2
    # 负控：`now` 比台账里最后一条更早（01:00 < 04:00）⇒ 被拒
    # （写侧与判定侧共用同一处口径：`audit_timestamps_not_monotonic`）
    with pytest.raises(G.LedgerError) as exc:
        _append(earlier, G._dt.datetime(2026, 9, 27, 1, 0, 0, tzinfo=tz))
    assert "倒挂" in str(exc.value), str(exc.value)


# --------------------------------------------------------------------- 注入负控

def _source_files(root: pathlib.Path) -> list[str]:
    """整树的已收集文件清单（相对路径，正斜杠）。

    用清单法而不是写死目录名：漏掉一整个目录时，下面那个子进程 pytest 会在
    "收集不到测试"上以非 0 退出 ⇒ 注入负控会以"预期红"的面目假绿。
    """
    out: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        parts = p.relative_to(root).parts
        if any(seg in {".git", "__pycache__", ".pytest_cache", "node_modules"} for seg in parts):
            continue
        out.append(p.relative_to(root).as_posix())
    return out


def test_injection_negative_control_severing_the_wiring_turns_this_file_red(
    tmp_path: pathlib.Path,
) -> None:
    """负控（证明接线被测到）：把判定侧那两行注入成 `if False:` ⇒ 本文件必须变红。

    形态照本仓惯例：盘外整树副本 + 打印副本 sha256 + 断言"注入点恰好命中 1 次"。
    子进程跑的是本文件，所以"接线被撤掉"这件事的结果就是"本文件里那两条断言红"。
    """
    src_root = _ROOT
    dst_root = tmp_path / "tree"
    files = _source_files(src_root)
    assert "scripts/noai_gate.py" in files and _NODE.split("::")[0] in files, files[:5]
    for rel in files:
        src = src_root / rel
        dst = dst_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())

    gate = dst_root / "scripts" / "noai_gate.py"
    old = ('    order_problem = audit_timestamps_not_monotonic(entry.counted_audits)\n'
           "    if order_problem:\n")
    new = ('    order_problem = audit_timestamps_not_monotonic(entry.counted_audits)\n'
           "    if False:\n")
    text = gate.read_text(encoding="utf-8")
    assert text.count(old) == 1, (
        f"注入锚点在 noai_gate.py 里出现 {text.count(old)} 次（期望恰好 1 次）—— "
        "锚点漂了就不能静默通过"
    )
    gate.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
    injected_sha = hashlib.sha256(gate.read_bytes()).hexdigest()
    assert injected_sha != hashlib.sha256(
        (src_root / "scripts" / "noai_gate.py").read_bytes()).hexdigest(), "注入没生效"

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONPATH", None)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", _NODE, "-q", "-p", "no:cacheprovider"],
        cwd=str(dst_root), capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env,
    )
    blob = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode != 0, (
        f"注入副本（sha256 {injected_sha[:16]}）里本文件仍然全绿 ⇒ 这一处接线没有测试守着"
        f"（`R7-R1d-2` 的形态）：{blob[-600:]}"
    )
    assert "test_descending_audit_timestamps_are_rejected" in blob, blob[-600:]
