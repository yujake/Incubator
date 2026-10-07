"""只读探针：用真 Store + 真 AgentB/AgentA，观察 (1) B 的失败后租约是否被遵守
(2) B.run 在抽取一直失败时会不会立刻重打同一行 / 耗尽 attempts。
不写仓库里任何文件；工作区建在 temp 下。"""
import sys, tempfile, shutil
from pathlib import Path

sys.path.insert(0, r"D:\Incubator\agentflow\src")
from agentflow.store import Store
from agentflow import schema as S
from agentflow.agent_b import AgentB


class _Doc:
    pages = ["hello world"]

    def text_at(self, lo, hi):
        return "hello world"


def extract(_path):
    return _Doc()


class _Boom:
    def extract(self, doc, lit_id, meta):
        raise RuntimeError("boom-probe")


def main():
    root = Path(tempfile.mkdtemp(prefix="probe_b_claim_"))
    try:
        st = Store(root)
        st.init(force=True)
        d = st.library / "0000"
        d.mkdir(parents=True, exist_ok=True)
        (d / "x.txt").write_text("hello world", encoding="utf-8")
        with st.tx("literature", actor="probe") as tx:
            row = S.Literature(lit_id="0000", title="probe", type="J", summary="", path="0000/x.txt",
                               processed=False, source_request_ids=[], dedup_key="title:probe|*",
                               added_at=S.now_iso())
            row.validate()
            tx.upsert("literature", row.to_dict(), note="probe")

        b = AgentB(st, extractor=_Boom(), extract_text=extract,
                   config={"lease_seconds": 900, "max_attempts": 3})
        r1 = b.run_once()
        lit = st.rows("literature")[0]
        print("after run_once #1: failed=%s processed=%s claimed_by=%r lease_until=%r mine_attempts=%s"
              % (r1.failed, lit.get("processed"), lit.get("claimed_by"), lit.get("lease_until"),
                 lit.get("mine_attempts")))
        # 关键判据：同进程立刻再跑，能不能立刻再领到同一行？
        r2 = b.run_once()
        lit = st.rows("literature")[0]
        print("after run_once #2: failed=%s processed=%s claimed_by=%r mine_attempts=%s last_err=%r"
              % (r2.failed, lit.get("processed"), lit.get("claimed_by"), lit.get("mine_attempts"),
                 str(lit.get("last_mine_error"))[:60]))
        r3 = b.run_once()
        lit = st.rows("literature")[0]
        print("after run_once #3: failed=%s processed=%s claimed_by=%r mine_attempts=%s"
              % (r3.failed, lit.get("processed"), lit.get("claimed_by"), lit.get("mine_attempts")))
        r4 = b.run_once()
        lit = st.rows("literature")[0]
        print("after run_once #4: failed=%s processed=%s skipped_reason=%r mine_attempts=%s"
              % (r4.failed, lit.get("processed"), r4.skipped_reason, lit.get("mine_attempts")))
        # 租约时间戳仍然在未来吗？（写了租约但它是否参与跳过判据）
        from agentflow.store import lease_expired
        print("lease still active at this moment:", not lease_expired(lit.get("lease_until")))
    finally:
        shutil.rmtree(root, ignore_errors=True)


main()
