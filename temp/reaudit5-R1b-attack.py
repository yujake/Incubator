# -*- coding: utf-8 -*-
"""R1b 攻击探针：上一轮 7 种攻击的独立重跑 + 新绕过尝试。

## 探针设计（第一版错在这里，写下来免得再犯）

每个场景跑两组，每组落在各自独立的工作区里：
  [G1 正控] 同场景的合规三连 ⇒ 门应当 approved（证明场景本身能过）；
  [G2 攻击] 只有攻击提交 ⇒ 门应当非 approved（否则攻击成立）。
第一版把两组塞进同一个工作区 ⇒ 正控先凑够 3×3，后面攻击再怎么写，
门都报 approved（它在数前三条）—— 读数全是"approved"，等于什么都没测。

另外单独记录写入侧：每条 `--record-audit` 的 exit 与首行（exit=2 = 拒写）。

只读 agentflow/；一切写入落在 temp/reaudit5-R1b-atk2/ 下。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(r"D:\Incubator\agentflow")
GATE = REPO / "scripts" / "noai_gate.py"
BASE = Path(r"D:\Incubator\temp\reaudit5-R1b-atk2")
WS = BASE / "ws"
LEDGER = WS / ".noai-approvals.json"
TARGET_REL = "src/target.py"

MANIFEST = (
    "[category: auth-audit] 七、权限与审计（谁能做什么，以及谁做过了什么）\n"
    "\n"
    "src/target.py  [category: auth-audit] 合成工作区的被审对象：符号 VALUE / bump / helper\n"
)

TARGET_SRC = (
    '"""合成被审对象。"""\n'
    "\n"
    "import math\n"
    "\n"
    "VALUE = 1\n"
    "\n"
    "\n"
    "def helper(x: int) -> int:\n"
    "    return math.floor(x)\n"
    "\n"
    "\n"
    "def bump() -> int:\n"
    "    return VALUE + 1\n"
)

NC = ("负控：拿同一套判据去审改前那一版（`git show HEAD:src/target.py`）—— "
      "改前那一版没有 `bump` 这个符号，判据必须报红，否则说明它没有分辨力。")

#: 零宽空格（`Cf`）。Python 3.11 的 f-string 表达式里不许出现反斜杠，
#: 所以带它的字符串必须在这里拼好再用（这一条我自己踩过一次）。
ZWSP = "\u200b"
ZW_NAME = "reaudit5" + ZWSP + "-N1"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


def run(*argv: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(GATE), *argv],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(REPO),
    )
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or ""))


def first_line(out: str) -> str:
    return out.strip().splitlines()[0] if out.strip() else ""


def ev_text(who: str, digest: str, scope_line: str = "target.py VALUE bump",
            nc: str = NC, extra: str = "") -> str:
    return (f"审计者标识（独立词）：{who}\n"
            f"开审版本 sha256 = {digest}\n"
            f"覆盖 scope 符号：{scope_line}\n"
            f"{nc}\n{extra}")


def group(label: str, specs: list[dict], *, authored: str = "",
          pre_files: dict[str, str] | None = None) -> dict:
    """在一个全新工作区里跑一组提交，返回写入侧 + 判定侧读数。"""
    if WS.exists():
        shutil.rmtree(WS)
    (WS / "src").mkdir(parents=True)
    (WS / "temp").mkdir(parents=True)
    target = WS / TARGET_REL
    target.write_text(TARGET_SRC, encoding="utf-8", newline="\n")
    (WS / ".noai-paths").write_text(MANIFEST, encoding="utf-8", newline="\n")
    digest = sha256_file(target)
    for rel, raw in (pre_files or {}).items():
        p = WS / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(raw, encoding="utf-8", newline="\n")

    argv = ["--root", str(WS), "--paths", TARGET_REL, "--baseline"]
    if authored:
        argv += ["--authored", authored, "--authored-basis", "inferred"]
    rc0, out0 = run(*argv)

    writes = []
    for s in specs:
        rel = s["evidence_path"]
        if s.get("_raw") is not None:
            p = WS / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(s["_raw"], encoding="utf-8", newline="\n")
        rc, out = run(
            "--root", str(WS), "--record-audit", TARGET_REL,
            "--auditor", s["auditor"], "--dimension", s["dimension"],
            "--evidence", s.get("evidence", rel), "--evidence-path", rel,
            "--negative-control", s.get("negative_control", NC),
            "--audit-scope", s.get("scope", "target.py VALUE bump"),
            "--audit-started-sha256", s.get("started", digest),
            "--independence", s.get("independence",
                                    "我是子审计代理，与该条目的作者不是同一主体"),
        )
        writes.append({"who": s["auditor"], "dim": s["dimension"], "exit": rc,
                       "first": first_line(out)})

    entry = json.loads(LEDGER.read_text(encoding="utf-8"))["entries"][0]
    rc1, out1 = run("--root", str(WS), "--paths", TARGET_REL,
                    "--check-approvals", "--json")
    j = json.loads(out1)
    ap = j["approvals"][0]
    read = {
        "label": label, "baseline_exit": rc0, "digest": digest,
        "write": writes,
        "ledger_audits": [f"{a['auditor']}/{a['dimension']}" for a in entry["audits"]],
        "exit": rc1, "verdict": j["verdict"],
        "status": ap["approval_status"], "reason": ap["approval_reason"],
        "clean": len(ap.get("clean_audits") or []),
        "auditors": ap.get("distinct_auditors"),
        "dims": len(ap.get("distinct_dimensions") or []),
    }
    print(f"  [{label}] baseline={rc0} 写入侧 exit="
          + ",".join(str(w["exit"]) for w in writes)
          + f"  盘上 audits={read['ledger_audits']}")
    for w in writes:
        if w["exit"] != 0:
            print(f"      拒写 {w['who']!r}/{w['dim']}：{w['first'][:120]}")
    print(f"      ⇒ 判定侧 exit={read['exit']} {read['verdict']} "
          f"{read['status']}/{read['reason']} clean={read['clean']} "
          f"aud={read['auditors']} dim={read['dims']}")
    return read


def control_trio(prefix: str, ev_dir: str = "temp") -> list[dict]:
    specs = []
    for dim, tag in zip(("axes", "roles", "errors"), ("A1", "A2", "A3")):
        who = f"{prefix}-{tag}"
        specs.append({"auditor": who, "dimension": dim,
                      "evidence_path": f"{ev_dir}/{prefix}-{dim}.txt"})
    return specs


def main() -> int:
    BASE.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(REPO / "scripts"))
    import noai_gate as G  # noqa: E402
    cur = GATE.read_text(encoding="utf-8")
    print("#" * 78)
    print("# 指纹：我跑的是当前实现")
    print("#" * 78)
    print(f"  module.__file__ = {G.__file__}")
    print(f"  gate sha256     = {sha256_bytes(cur.encode('utf-8'))}")
    print(f"  gate 行数        = {len(cur.splitlines())}")
    print(f"  MIN_INDEPENDENT_AUDITORS={G.MIN_INDEPENDENT_AUDITORS} "
          f"MIN_DISTINCT_DIMENSIONS={G.MIN_DISTINCT_DIMENSIONS} "
          f"NEGCTL_MIN_CHARS={G.NEGCTL_MIN_CHARS}")
    print(f"  AUDIT_DIMENSIONS={list(G.AUDIT_DIMENSIONS)}")

    # 合成工作区固定，先算一次 digest 供证据正文用
    tmp = BASE / "digestprobe"
    if tmp.exists():
        shutil.rmtree(tmp)
    (tmp / "src").mkdir(parents=True)
    (tmp / "src" / "target.py").write_text(TARGET_SRC, encoding="utf-8", newline="\n")
    D = sha256_file(tmp / "src" / "target.py")
    print(f"  合成被审对象 sha256（各场景相同，因为内容相同）= {D}")

    def ctl(prefix: str) -> list[dict]:
        specs = control_trio(prefix)
        for s in specs:
            s["_raw"] = ev_text(s["auditor"], D)
        return specs

    def atk(entries: list[tuple[str, str, str]], **kw) -> list[dict]:
        """entries = [(auditor, dim, raw)]"""
        return [{"auditor": a, "dimension": d, "evidence_path": f"temp/{p}-{d}.txt",
                 "_raw": raw} for p, (a, d, raw) in zip("abcdefgh", entries)]

    results: dict[str, dict] = {}

    # ------------------------------------------------------------------ 自校
    print()
    print("#" * 78)
    print("# 0. 探针自校：一个必然成功 + 一个必然失败（各自独立工作区）")
    print("#" * 78)
    results["self_ctrl"] = group("自校·正控", ctl("ok"))
    bad = ctl("bad")
    bad[2] = dict(bad[2], negative_control="n/a",
                  _raw=ev_text(bad[2]["auditor"], D, nc="n/a"))
    results["self_bad"] = group("自校·负控(n/a)", bad)
    calib = (results["self_ctrl"]["status"] == "approved"
             and results["self_bad"]["status"] == "unapproved")
    print(f"  >>> 自校：正控={results['self_ctrl']['status']} "
          f"负控={results['self_bad']['status']} ⇒ "
          f"{'探针有分辨力' if calib else '探针没有分辨力（读数不可信）'}")

    # ---------------------------------------------------------------- 攻击 1
    print()
    print("#" * 78)
    print("# 攻击 1（R1-AN-2 本命）：盘上只有 1 个证据文件，路径写 3 种等价形态")
    print("#" * 78)
    results["a1_ctl"] = group("攻击1·正控", ctl("c1"))
    variants = ["temp/one.txt", "./temp/one.txt", "temp/./one.txt"]
    a1 = [{"auditor": "reaudit5-X1", "dimension": dim, "evidence_path": rel}
          for dim, rel in zip(("axes", "roles", "errors"), variants)]
    results["a1_atk"] = group("攻击1·同一证据三种路径写法", a1,
                              pre_files={"temp/one.txt": ev_text("reaudit5-X1", D)})
    print(f"  盘上 temp/ 下物理证据文件 = "
          f"{sorted(p.name for p in (WS / 'temp').glob('*.txt'))}")
    for v in variants:
        print(f"    _norm_evidence_rel({v!r}) = {G._norm_evidence_rel(v)!r}")
    print(f"  归一化后全部相同 ? "
          f"{len({G._norm_evidence_rel(v) for v in variants}) == 1}")

    # ---------------------------------------------------------------- 攻击 2
    print()
    print("#" * 78)
    print("# 攻击 2（c-17）：同一份观察复制 3 份、每份改一个字节（hash 各不相同）")
    print("#" * 78)
    results["a2_ctl"] = group("攻击2·正控", ctl("c2"))
    a2 = []
    for i, dim in enumerate(("axes", "roles", "errors")):
        raw = ev_text("reaudit5-Y1", D, extra=f"（同一份观察，只多打了 {i} 个空格）   \n")
        a2.append({"auditor": "reaudit5-Y1", "dimension": dim,
                   "evidence_path": f"temp/copy{i}.txt", "_raw": raw})
    print(f"  三份 evidence_sha256 = "
          f"{[sha256_bytes(s['_raw'].encode())[:12] for s in a2]}（互不相同 ⇒ "
          f"{len({sha256_bytes(s['_raw'].encode()) for s in a2}) == 3}）")
    results["a2_atk"] = group("攻击2·同一观察复制三份", a2)

    # ---------------------------------------------------------------- 攻击 3
    print()
    print("#" * 78)
    print("# 攻击 3（H-1a / c-16）：同形字 / 零宽字符 / 变体选择符")
    print("#" * 78)
    named = ["reaudit5-A1", "ｒｅａｕｄｉｔ５-Ａ１", "ＲＥＡＵＤＩＴ５-ａ１",
             "reaudit5-A1\u200b", "reaudit5-A1\u200d", "reaudit5-A1\u2060",
             "reaudit5-A1\ufe0f", "reaudit5-A1\u00a0", "reaudit5-A1 ",
             "reaudit5-A1\ufeff"]
    base_norm = G.normalize_subject(named[0])
    for n in named:
        got = G.normalize_subject(n)
        print(f"    {n!r:<30} -> {got!r}  == 原名? {got == base_norm}")
    results["a3_ctl"] = group("攻击3a·正控", ctl("c3"))
    a3 = atk([(who, dim, ev_text(who, D)) for who, dim
              in zip(("reaudit5-Z1", "ｒｅａｕｄｉｔ５-Ｚ１", "reaudit5-Z1\u200b"),
                     ("axes", "roles", "errors"))])
    results["a3_atk"] = group("攻击3a·同一实体三种同形写法", a3)

    print("  -- 攻击 3b：`c-16` same_author 写入侧（authored=ai-agent）--")
    results["a3b_atk"] = group(
        "攻击3b·同一署名者同形写法",
        atk([(who, "axes", ev_text(who, D)) for who in
             ("ai-agent", "ａｉ－ａｇｅｎｔ", "ai-agent\u200b")]),
        authored="ai-agent")

    # ---------------------------------------------------------------- 攻击 4
    print()
    print("#" * 78)
    print("# 攻击 4（R1-AN-4③）：scope 放短词 / 放被审对象里真实存在但无关的标识符")
    print("#" * 78)
    idents = G._identifiers_of(TARGET_SRC)
    print(f"  _identifiers_of(被审对象) = {sorted(idents)}")
    for scope in ("the", "and", "import", "math", "helper", "VALUE",
                  "return int", "target.py VALUE bump", "def math.floor"):
        toks = [t for t in scope.replace(",", " ").split() if len(t) >= 3]
        print(f"    scope={scope!r:<24} tokens={toks}  落在被审对象上 = "
              f"{[t for t in toks if t in idents]}")
    results["a4_ctl"] = group("攻击4·正控", ctl("c4"))
    a4 = []
    for dim, scope in zip(("axes", "roles", "errors"),
                          ("the", "and", "import return int")):
        raw = ev_text("reaudit5-W1", D, scope_line=scope)
        a4.append({"auditor": "reaudit5-W1", "dimension": dim,
                   "evidence_path": f"temp/sc-{dim}.txt", "scope": scope, "_raw": raw})
    results["a4_atk"] = group("攻击4·scope 放无关短词/关键字", a4)

    # ---------------------------------------------------------------- 攻击 5
    print()
    print("#" * 78)
    print("# 攻击 5（H-1b①②③）：证据里缺自己的标识 / 缺版本 sha / 缺负控字样")
    print("#" * 78)
    for tag, mutate in (
        ("缺 auditor 标识", lambda s: s.replace("审计者标识（独立词）：reaudit5-V1\n", "")),
        ("缺版本 sha", lambda s: s.replace(f"开审版本 sha256 = {D}\n", "")),
        ("缺负控字样", lambda s: s.replace("负控", "记录").replace("改前", "之前")),
    ):
        results[f"a5_{tag}"] = group(f"攻击5·{tag}", atk(
            [("reaudit5-V1", dim, mutate(ev_text("reaudit5-V1", D)))
             for dim in ("axes", "roles", "errors")]))

    # ---------------------------------------------------------------- 攻击 6
    print()
    print("#" * 78)
    print("# 攻击 6（c-20）：audit_started_sha256 与台账/磁盘那一版不符")
    print("#" * 78)
    results["a6_ctl"] = group("攻击6·正控", ctl("c6"))
    a6 = atk([("reaudit5-U1", dim, ev_text("reaudit5-U1", D))
              for dim in ("axes", "roles", "errors")])
    a6[2] = dict(a6[2], started="0" * 64)
    results["a6_atk"] = group("攻击6·第三条 started 给另一个 sha", a6)

    # ---------------------------------------------------------------- 新绕过
    print()
    print("#" * 78)
    print("# 新绕过 N1：证据文件里用零宽字符拼出审计者标识（骗过『独立词』词边界）")
    print("#" * 78)
    print("  思路：`_mentions_word` 是裸文本词边界判定；把 auditor 写成带零宽空格的形态，")
    print("        证据里也只有这个形态 —— 归一化后与不带零宽的写法是同一个名字。")
    print(f"  带零宽的名字 = {ZW_NAME!r}，normalize_subject 后 = "
          f"{G.normalize_subject(ZW_NAME)!r}（与 'reaudit5-n1' 相同 ? "
          f"{G.normalize_subject(ZW_NAME) == G.normalize_subject('reaudit5-N1')}）")
    results["n1_ctl"] = group("N1·正控", ctl("n1"))
    a_n1 = atk([("reaudit5-N1a", dim, ev_text("reaudit5-N1a", D))
                for dim in ("axes", "roles", "errors")])
    results["n1_atk"] = group("N1·正常名字（对照组，应通过）", a_n1)
    print(f"  词边界读数：证据里写带零宽的形态、声明用不带零宽的名字 ⇒ "
          f"{G._mentions_word('审计者标识（独立词）：' + ZW_NAME, 'reaudit5-n1')}")
    print(f"  词边界读数：两边都不带零宽 ⇒ "
          f"{G._mentions_word('审计者标识（独立词）：reaudit5-N1', 'reaudit5-n1')}")
    a_n1b = [{"auditor": "reaudit5-N1", "dimension": dim,
              "evidence_path": f"temp/zw-{dim}.txt",
              "_raw": ev_text(ZW_NAME, D)} for dim in ("axes", "roles", "errors")]
    results["n1_zw_atk"] = group("N1b·声明不带零宽、证据只写带零宽（应拒写）", a_n1b)

    # ---------------------------------------------------------------- 新绕过 N2
    print()
    print("#" * 78)
    print("# 新绕过 N2：negative_control 用 40+ 字符空话（只有标记词、没有可核对内容）")
    print("#" * 78)
    for text in ("n/a " + " " * 40 + " HEAD " + " " * 10,
                 "改前" + "啊" * 60,
                 "negative " + "x" * 60,
                 "负控：（此栏无内容）" + "占位" * 20 + " 改前"):
        prob = G.negative_control_problem(text)
        print(f"    长度 {len(text.strip()):>3}  problem={'空(通过)' if not prob else prob[:60]!r}")
    empty = "改前" + "占位" * 30
    results["n2_atk"] = group("N2·负控是 40+ 字符空话", atk(
        [("reaudit5-M1", dim, ev_text("reaudit5-M1", D, nc=empty))
         for dim in ("axes", "roles", "errors")]))

    # ---------------------------------------------------------------- 新绕过 N3
    print()
    print("#" * 78)
    print("# 新绕过 N3：independence / scope 写一个字（判据只看 non-empty）")
    print("#" * 78)
    a_n3 = atk([("reaudit5-K1", dim, ev_text("reaudit5-K1", D))
                for dim in ("axes", "roles", "errors")])
    for s in a_n3:
        s["independence"] = "x"
    results["n3_indep"] = group("N3·independence 只写一个 x", a_n3)
    a_n3b = atk([("reaudit5-K2", dim, ev_text("reaudit5-K2", D, scope_line="VALUE"))
                 for dim in ("axes", "roles", "errors")])
    for s in a_n3b:
        s["scope"] = "VALUE"
    results["n3_scope"] = group("N3b·scope 只写一个符号 VALUE", a_n3b)

    # ---------------------------------------------------------------- 新绕过 N4
    print()
    print("#" * 78)
    print("# 新绕过 N4：同一个 auditor 在同一 sha 上提交 3 个不同维度（同证据不同副本）")
    print("#" * 78)
    a_n4 = []
    for i, dim in enumerate(("axes", "roles", "errors")):
        a_n4.append({"auditor": "reaudit5-SOLO", "dimension": dim,
                     "evidence_path": f"temp/solo{i}.txt",
                     "_raw": ev_text("reaudit5-SOLO", D, extra=f"副本{i}   \n")})
    results["n4_atk"] = group("N4·同一 auditor 三个维度三份副本", a_n4)

    # ---------------------------------------------------------------- 新绕过 N5
    print()
    print("#" * 78)
    print("# 新绕过 N5：2 名 auditor，其中 1 名独占 2 个维度（同证据两份副本）")
    print("#" * 78)
    a_n5 = []
    for i, dim in enumerate(("axes", "roles", "errors")):
        who = "reaudit5-P1" if i < 2 else "reaudit5-P2"
        a_n5.append({"auditor": who, "dimension": dim,
                     "evidence_path": f"temp/p{i}.txt",
                     "_raw": ev_text(who, D, extra=f"副本{i}   \n")})
    results["n5_atk"] = group("N5·2 名 auditor、P1 独占两维度", a_n5)

    print()
    print("=" * 78)
    print("读数汇总")
    print("=" * 78)
    for k, r in results.items():
        print(f"  {k:<22} exit={r['exit']} {r['verdict']:<15} "
              f"{r['status']}/{r['reason']:<24} clean={r['clean']:<2} "
              f"aud={r['auditors']} dim={r['dims']}")
    print()
    print("判据：凡是标注为攻击/负控的行，status 必须是 unapproved 或 unknown；")
    print("      写成 approved 的那些就是绕过成立（要报 finding）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
