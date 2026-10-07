"""只读探针 D-2(b)：租约/尝试次数这两个阈值到底住在哪一段，改了它行为变不变？

判据（控制器给的验收口径）：**改一个阈值 ⇒ 行为随之改变**。
- 修复前（`git show HEAD:agentflow/config.yaml`）：`lease:` 块是死键 —— 把 `lease.seconds`
  从 900 改成 3，B 读到的还是代码默认 900 ⇒ 行为不变（红）。
- 修复后（工作区 `config.yaml`）：阈值住在 `agent_b:` 段（正是 `host._cfg_for(role)` 读的那一段）
  ⇒ 把 `agent_b.lease_seconds` 改成 3，B 真的按 3 秒写退避租约（绿）。

只读：不写仓库里任何文件（工作区建在 temp 下）；`git show` 只读出已提交版本，不改工作树。
"""
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import shutil

sys.path.insert(0, r"D:\Incubator\agentflow\src")
from agentflow.store import Store, make_lease, lease_expired
from agentflow import schema as S
from agentflow.agent_b import AgentB

REPO = Path(r"D:\Incubator")
YAML_REL = "agentflow/config.yaml"


def load_committed_config() -> dict:
    """从 git 里读出**修复前**那一版 config.yaml（不改工作树）。"""
    out = subprocess.run(["git", "show", f"HEAD:{YAML_REL}"], cwd=REPO,
                         capture_output=True, text=True, encoding="utf-8", check=True)
    import yaml
    return yaml.safe_load(out.stdout)


def load_worktree_config() -> dict:
    import yaml
    return yaml.safe_load((REPO / YAML_REL).read_text(encoding="utf-8"))


def lease_seconds_seen(cfg: dict, *, legacy_splat: bool) -> int:
    """照两种造法各建一个 AgentB，读它实际生效的 `lease_seconds`。

    - `legacy_splat=True`：`cli.py` / `pipeline.py` 的旧造法 `{**段, **(cfg["lease"] or {})}`
    - `legacy_splat=False`：正式路径（`host.py:292-299` 的 `_cfg_for(role)` 只给角色段）
    """
    section = dict(cfg.get("agent_b") or {})
    if legacy_splat:
        section = {**section, **(cfg.get("lease") or {})}
    root = Path(tempfile.mkdtemp(prefix="d2_cfg_probe_"))
    try:
        st = Store(root)
        st.init(force=True)
        b = AgentB(st, extractor=_Boom(), extract_text=_doc, config=section)
        return int(b.lease_seconds)
    finally:
        shutil.rmtree(root, ignore_errors=True)


class _Doc:
    pages = ["hello world"]

    def text_at(self, lo, hi):
        return "hello world"


def _doc(_path):
    return _Doc()


class _Boom:
    def extract(self, doc, lit_id, meta):
        raise RuntimeError("boom-probe")


def write_lease_reading(cfg: dict, *, tune_to: int | None) -> str:
    """按正式路径造 B（只给角色段），可选地把段里的阈值改成 `tune_to`，
    然后看失败分支写下的 `lease_until` 距今多少秒 —— 这是"行为"那一半。"""
    section = dict(cfg.get("agent_b") or {})
    if tune_to is not None:
        section["lease_seconds"] = tune_to
    root = Path(tempfile.mkdtemp(prefix="d2_cfg_probe_run_"))
    try:
        st = Store(root)
        st.init(force=True)
        d = st.library / "0000"
        d.mkdir(parents=True, exist_ok=True)
        (d / "x.txt").write_text("hello world", encoding="utf-8")
        with st.tx("literature", actor="probe") as tx:
            row = S.Literature(lit_id="0000", title="probe", type="J", summary="",
                               path="0000/x.txt", processed=False, source_request_ids=[],
                               dedup_key="title:probe|*", added_at=S.now_iso())
            row.validate()
            tx.upsert("literature", row.to_dict(), note="probe")
        b = AgentB(st, extractor=_Boom(), extract_text=_doc, config=section)
        b.run_once()
        lit = st.rows("literature")[0]
        lu = lit.get("lease_until")
        if not lu:
            return "lease_until=None（失败分支没写租约 ⇒ 当轮可重领）"
        left = (datetime.fromisoformat(lu) - datetime.now(timezone.utc)).total_seconds()
        return (f"lease_until 距今 {left:6.1f}s（active={not lease_expired(lu)}）"
                f" / mine_attempts={lit.get('mine_attempts')}")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def report(tag: str, cfg: dict) -> None:
    aa = cfg.get("agent_a") or {}
    bb = cfg.get("agent_b") or {}
    lz = cfg.get("lease") or {}
    print(f"\n== {tag} ==")
    print(f"  `lease:` 块的键            : {sorted(lz)}")
    print(f"  `agent_a:` 段里的阈值键    : "
          f"{ {k: v for k, v in aa.items() if k in ('lease_seconds', 'max_attempts')} }")
    print(f"  `agent_b:` 段里的阈值键    : "
          f"{ {k: v for k, v in bb.items() if k in ('lease_seconds', 'max_attempts')} }")
    print(f"  正式路径（只给角色段）读到 : {lease_seconds_seen(cfg, legacy_splat=False)} 秒")
    print(f"  旧路径（段 + lease 块）读到: {lease_seconds_seen(cfg, legacy_splat=True)} 秒")
    # ---- 判据：把阈值调成 3，行为变不变？
    tuned_strict = dict(cfg)
    tuned_strict["agent_b"] = {**bb, "lease_seconds": 3}
    seen_strict = lease_seconds_seen(tuned_strict, legacy_splat=False)
    print(f"  把 `agent_b.lease_seconds` 调成 3 ⇒ 正式路径读到 {seen_strict} 秒 "
          f"{'【活的】' if seen_strict == 3 else '【死键：改阈值行为不变】'}")
    tuned_old = dict(cfg)
    tuned_old["lease"] = {**lz, "seconds": 3}
    seen_old = lease_seconds_seen(tuned_old, legacy_splat=True)
    print(f"  把 `lease.seconds`       调成 3 ⇒ 旧路径读到   {seen_old} 秒 "
          f"{'【活的】' if seen_old == 3 else '【死键：改阈值行为不变】'}")
    print(f"  失败分支写下的租约（阈值=段里的值）: {write_lease_reading(cfg, tune_to=None)}")
    print(f"  失败分支写下的租约（阈值改成 3）    : {write_lease_reading(cfg, tune_to=3)}")


def main() -> int:
    try:
        report("修复前（git HEAD 的 config.yaml）", load_committed_config())
    except Exception as exc:  # noqa: BLE001 —— 探针：读不到就说读不到，不算"没问题"
        print(f"[HEAD] 读不到已提交版本（{type(exc).__name__}: {exc}）⇒ 这一档 unknown")
    report("修复后（工作区 config.yaml）", load_worktree_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
