# -*- coding: utf-8 -*-
"""R7-⑰ 两条机械改写防线：换行风格 + 底稿与文档不许被脚本改写成"连行 + 去强调"。

治的是本轮施工实测过的三次真事故（不是假想）：

1. 换行风格：`Path.write_text` 的脚本把 7 个文件从 CRLF 翻成 LF
   （`conductor.py` / `test_agent_loop.py` / `test_judges.py` / `test_agent_e_formal_path.py`
   （HEAD 本就是 CRLF，方向相反）/ `secretary.py` / `test_secretary.py` / `draft/46-01`）；
2. 底稿被 R009 族脚本改写：`draft/46-01` 644→550 行、`draft/46-03` 797→556 行
   （连行 + 把强调标记换成空格），两个文件都靠 `git checkout HEAD --` 逐字节还原；
3. 改写后行号锚点漂。

这一条判据守前两条。第三条走既有的两条（`tests/test_reading_map.py` 的行数判据与
`test_r5_orchestration_cost.py` 的 `test_the_stale_line_number_references_are_gone`）——
本文件刻意不新造"扫全仓 `x.py:123`"的通用判据：`test_r5_orchestration_cost.py` 里
逐字记着为什么（全仓三十余处那种引用、多数指向别处的文档，通用判据只会造一盏
靠别人改文件才变绿的灯）。

三态：`draft/` 里有一部分是未跟踪的底稿 —— 它们没有 HEAD 可对拍。那不是"没问题"，
是"这一格覆盖不到"，所以判据把那个份数当读数报出来
（`test_the_untracked_draft_gap_is_a_visible_state`），不许静默跳过。
"""
from __future__ import annotations

import ast
import pathlib
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]      # 交付树（agentflow/）
GIT_ROOT = REPO.parent                                  # `.git` 在上一级

#: 只有文本才有"换行风格"这件事；二进制（PDF、图片）不判。
_TEXT_SUFFIXES = (".py", ".md", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".txt",
                  ".cfg", ".ini", ".sh", ".ps1", ".rst")
_TEXT_NAMES = (".noai-paths", ".gitattributes", ".gitignore")

#: 新文件必须跟随仓约定的面（源码与教人文本）。两类刻意不判：
#:   · `out/` 与 `projects/` 是运行产物（每跑一次就变一次，判它们只会造出假红，
#:     同 `test_r5_orchestration_cost.py` 的 `_REF_SCAN_SKIP_DIRS` 那段理由）；
#:   · `temp/` 是判据的工装（整树副本、负控副本、命令输出捕获）—— 实测那里有
#:     30 个 `.txt` 输出捕获（PowerShell 重定向写出来的是 CRLF）与 1 份整树副本里的
#:     工具文件，它们不是要入仓的文件。判工装的换行只会造出一片没人该去改的红。
_NEW_FILE_SCOPE = ("agentflow/src", "agentflow/tests", "agentflow/docs", "agentflow/tools",
                   "agentflow/scripts", "draft")


def _git(*args: str, data: bytes | None = None) -> bytes:
    """跑一条 git 命令；失败就是判据自己坏了（不许折成"没问题"）。"""
    proc = subprocess.run(["git", "-C", str(GIT_ROOT), *args], input=data,
                          capture_output=True)
    assert proc.returncode == 0, (
        f"`git {' '.join(args)}` 失败（rc={proc.returncode}）："
        f"{proc.stderr.decode('utf-8', 'replace')[:300]} —— 读不到就是 unknown，"
        "不许折成『换行风格没问题』（判据的落点必须在仓里）"
    )
    return proc.stdout


def _paths(*args: str) -> list[str]:
    """`git ls-files` / `git diff --name-only` 的 `-z` 输出 ⇒ 路径清单。

    用 `surrogateescape` 解码：仓里有非 UTF-8 字节的路径时不许抛，也不许静默丢。
    """
    out = _git(*args, "-z").decode("utf-8", "surrogateescape")
    return [x for x in out.split("\0") if x]


def _is_text(rel: str) -> bool:
    return rel.endswith(_TEXT_SUFFIXES) or pathlib.PurePosixPath(rel).name in _TEXT_NAMES


def _style(data: bytes) -> str:
    """一份字节流的换行风格：`lf` / `crlf` / `mixed` / `none`（没有换行符）。"""
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    if crlf and lf:
        return "mixed"
    if crlf:
        return "crlf"
    return "lf" if lf else "none"


def _counts(data: bytes) -> dict[str, int]:
    """(行数, 字节数, 强调标记数) —— 事故形态的三个读数。"""
    return {"lines": data.count(b"\n"), "bytes": len(data), "stars": data.count(b"**")}


def _head_shas() -> dict[str, str]:
    """HEAD 那棵树的全量 `路径 ⇒ blob sha`（一次 `ls-tree`，不逐文件起进程）。"""
    out = _git("ls-tree", "-r", "-z", "HEAD")
    got: dict[str, str] = {}
    for rec in out.split(b"\0"):
        if b"\t" not in rec:
            continue
        left, _, path = rec.partition(b"\t")
        parts = left.split()
        if len(parts) >= 3:
            got[path.decode("utf-8", "surrogateescape")] = parts[2].decode()
    assert got, "`git ls-tree -r HEAD` 一个文件都没读到 ⇒ 这一格没查成（不是没问题）"
    return got


def _head_blobs(rels: list[str]) -> dict[str, bytes]:
    """这些路径在 HEAD 里的内容（走 sha 取字节，一次 `cat-file --batch`）。

    为什么按 sha 而不是 `git show HEAD:<path>`：仓里有带全角冒号与中文的底稿名，
    路径一旦进命令行就可能被编码规则改写 ⇒ 取不到内容，而"取不到"会被读成"没改动"。
    sha 是 ASCII，稳。
    """
    shas = _head_shas()
    want = {rel: shas[rel] for rel in rels if rel in shas}
    if not want:
        return {}
    out = _git("cat-file", "--batch", data=("\n".join(want.values()) + "\n").encode())
    got: dict[str, bytes] = {}
    pos = 0
    for rel, _sha in want.items():
        nl = out.index(b"\n", pos)
        size = int(out[pos:nl].split()[2])
        start = nl + 1
        got[rel] = out[start:start + size]
        pos = start + size + 1
    return got


def eol_problem(rel: str, head: bytes | None, work: bytes | None, *,
                convention: str) -> str | None:
    """一个文件的换行风格问题（`None` = 没问题）。

    `head is None` ⇒ 新增文件：必须跟随仓的约定（`convention`）。
    `work is None` ⇒ 文件被删了：不判（那是删除，不是改写）。
    """
    if work is None:
        return None
    if head is None:
        if _style(work) != convention:
            return (f"{rel}: 新增文件的换行风格是 {_style(work)}，而仓的约定是 {convention}"
                    "（新文件按仓的既有约定，不许各写各的）")
        return None
    if _style(head) != _style(work):
        return (f"{rel}: 换行风格 HEAD={_style(head)} / 盘上={_style(work)} —— "
                "内容有改动但换行档位与 HEAD 不同：那是脚本 `write_text` 往返的指纹"
                "（整份文件的 diff 会因此变成全文件改写，行号锚点跟着全漂）")
    return None


def accident_form(before: bytes, after: bytes) -> str | None:
    """"连行 + 去强调"形态的机械判据（两次真事故的共同指纹）。

    命中条件刻意写得窄（宁可漏、不许把合法人工改写判红）：强调标记减少，
    且（行数减少 或 强调标记腰斩）。

    为什么要"强调标记减少"这一条：R009 族脚本的两次事故都是"连行 + 把强调标记换成
    空格"，而合法的人工改写会增加内容（行数与标记一起长） ⇒ 这一条把两者分得开。
    """
    b, a = _counts(before), _counts(after)
    if a["stars"] < b["stars"] and (a["lines"] < b["lines"] or a["stars"] * 2 < b["stars"]):
        return (f"行 {b['lines']}→{a['lines']} 字节 {b['bytes']}→{a['bytes']} "
                f"强调标记 {b['stars']}→{a['stars']}")
    return None


def _convention() -> str:
    """仓对文本文件的换行约定 = 被跟踪文本文件里的多数档（现算，不写死）。"""
    counts: dict[str, int] = {}
    for line in _git("ls-files", "--eol").decode("utf-8", "replace").splitlines():
        parts = line.split()
        if len(parts) < 2 or not parts[1].startswith("w/"):
            continue
        style = parts[1][2:]
        counts[style] = counts.get(style, 0) + 1
    assert counts, "`git ls-files --eol` 一个文件都没读到 ⇒ 这一格没查成（不是没问题）"
    return max(counts, key=lambda k: counts[k])


def _changed_new_tracked() -> tuple[list[str], list[str], list[str]]:
    """(相对 HEAD 有改动的被跟踪文本文件, 面上的未跟踪文本新文件, 全部被跟踪文本文件)。"""
    changed = [r for r in _paths("diff", "--name-only", "HEAD") if _is_text(r)]
    untracked = [r for r in _paths("ls-files", "--others", "--exclude-standard")
                 if _is_text(r) and r.startswith(_NEW_FILE_SCOPE)]
    tracked = [r for r in _paths("ls-files") if _is_text(r)]
    return sorted(changed), sorted(untracked), tracked


def _added_to_head_side() -> set[str]:
    """被改了、但 HEAD 里没有这些路径（新增或改名进来的）。

    它们没有 HEAD 可对拍 —— 那不是"取不到"，而是"这一档要按新增文件判"。
    分开这一档是为了不误伤正常动作：把一份文件改名/新增进索引，会让
    `git diff --name-only HEAD` 里多出一个 HEAD 里不存在的路径。
    """
    got: set[str] = set()
    for line in _git("diff", "--name-status", "HEAD").decode("utf-8", "replace").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].startswith("A"):
            got.add(parts[-1])
    return got


def test_the_eol_style_of_changed_files_matches_head() -> None:
    """防线 (a)：被跟踪文件的换行风格必须与 HEAD 一致；新增文件用仓的约定。

    为什么这一条值得有：`Path.write_text` 在 Windows 上按 `os.linesep` 翻译换行，
    于是一份"只改了三行"的文件在 git 眼里变成整文件改写 —— 行号锚点全漂、
    review 的人看不出真改了什么。实测事故：7 个文件被这么翻过（一批 CRLF→LF、
    一个方向相反）。
    """
    _assert_eol_negative_controls()
    changed, new_files, tracked = _changed_new_tracked()
    convention = _convention()
    assert len(tracked) >= 500, (
        f"被跟踪文本文件只读到 {len(tracked)} 个 ⇒ 判据的枚举面坏了（不是没问题）：{tracked[:5]}")

    blobs = _head_blobs(changed)
    # HEAD 里没有这些路径（新增 / 改名进来的）⇒ 按"新增文件"那一档判，
    # 不当成"取不到 HEAD"（把正常动作判红是这套判据最该避免的形态）。
    added = _added_to_head_side()

    bad: list[str] = []
    for rel in changed:
        path = GIT_ROOT / rel
        work = path.read_bytes() if path.is_file() else None
        head = None if rel in added else blobs.get(rel)
        if head is None and work is not None and rel not in added:
            bad.append(f"{rel}: 取不到 HEAD 内容 ⇒ 这一格没查成（不是『风格一致』）")
            continue
        got = eol_problem(rel, head, work, convention=convention)
        if got:
            bad.append(got)
    new_bad: list[str] = []
    for rel in new_files:
        path = GIT_ROOT / rel
        if not path.is_file():
            continue
        got = eol_problem(rel, None, path.read_bytes(), convention=convention)
        if got:
            new_bad.append(got)

    reading = {"changed_text_files": len(changed), "head_compared": len(blobs),
               "added_to_head_side": len(added), "new_text_files": len(new_files),
               "tracked_text_files": len(tracked), "convention": convention,
               "mismatches": len(bad) + len(new_bad)}
    assert not bad and not new_bad, (
        f"被改动的文件与 HEAD 的换行档位不一致（读数 {reading}）：" + "；".join(bad + new_bad))


def _assert_eol_negative_controls() -> None:
    """防线 (a) 的负控：两个方向都要能红，且"没改动"与"删除"不许红。

    样本用真文件：`tests/test_claimanatomy.py` 的 HEAD 是 CRLF（本轮实测被翻成 LF 过、
    已按 HEAD 那一档还原）；`src/agentflow/closing.py` 的 HEAD 是 LF。
    """
    # 2026-10-21 换轨：负控**不再依赖"仓库里恰好有一个 CRLF 的 HEAD"**。
    # 那次把 219 个文件入库归一成 LF 之后，`test_claimanatomy.py` 的 HEAD 已变成 LF，
    # 旧写法于是把负控自己判红（"样本的档位与登记的不符"）—— 这是**判据依赖可变量**的典型。
    # 现在：`_head_blobs` 只用来证明"HEAD 读得到"（取任意一个被跟踪文件），
    # 两个方向的样本用**内存里的字节**构造（`eol_problem` 本来只吃字节，不吃文件名）。
    crlf_file, lf_file = "agentflow/sample_crlf.py", "agentflow/sample_lf.py"
    probe = "agentflow/src/agentflow/closing.py"
    blobs = _head_blobs([probe])
    assert blobs.get(probe) is not None, "负控取不到 HEAD 内容 ⇒ 这一格没查成（不是『没样本』）"
    crlf_head = b"line one\r\nline two\r\n"
    lf_head = b"line one\nline two\n"
    assert _style(crlf_head) == "crlf" and _style(lf_head) == "lf", (
        f"内存样本的档位构造错了（{_style(crlf_head)} / {_style(lf_head)}）⇒ 负控咬不住")

    flipped = crlf_head.replace(b"\r\n", b"\n")
    got = eol_problem(crlf_file, crlf_head, flipped, convention="lf")
    assert got and "HEAD=crlf" in got, f"CRLF→LF 没被抓到（事故方向一）：{got}"
    back = lf_head.replace(b"\n", b"\r\n")
    got2 = eol_problem(lf_file, lf_head, back, convention="lf")
    assert got2 and "HEAD=lf" in got2, f"LF→CRLF 没被抓到（事故方向二）：{got2}"
    assert eol_problem(crlf_file, crlf_head, crlf_head, convention="lf") is None, \
        "没改动却报了问题 ⇒ 判据会在读一遍自己的时候乱叫"
    assert eol_problem("x.py", None, crlf_head, convention="lf"), "新文件用 CRLF 必须红"
    assert eol_problem("x.py", None, lf_head, convention="lf") is None, "新文件用 LF 不该红"
    assert eol_problem("x.py", lf_head, None, convention="lf") is None, "删除不该被当成改写"


#: 真事故样本（R009 族脚本改写底稿那一次）：HEAD 的 (行数, 字节, 强调标记数)。
_ACCIDENT_SAMPLE = "draft/46-施工级调查-01-schema与store.md"
_ACCIDENT_HEAD = (644, 48646, 336)


def _accident_simulation(head: bytes) -> bytes:
    """真事故的机械形态：连掉空行 + 把强调标记换成空格。"""
    return b"\n".join(line for line in head.replace(b"**", b" ").split(b"\n") if line.strip())


#: 这一族"当前不可判"的逐字理由（`draft/` 不再被 git 跟踪 ⇒ 没有 HEAD 样本可对拍）。
#:
#: 2026-10 业主裁定：`draft/`、`temp/`、`test/` 从 git 索引移除并写进 `.gitignore`，
#: 不许恢复跟踪。于是下面两条判据（真事故样本的负控、未跟踪底稿缺口的读数）
#: **失去了对象**：底稿不在 HEAD 里，就没有"改前"可比。
#:
#: 三态纪律要求这件事显式可见：既不许静默通过（那会把"覆盖不到"读成"没问题"），
#: 也不许把判据删掉（那等于"这一族从此没人看"）。所以两条判据各自
#: `pytest.skip(_draft_family_skip_reason())`，理由逐字出现在 skip 行里；
#: 另一半是 `test_the_draft_family_resumes_as_soon_as_draft_is_tracked_again()`：
#: `draft/` 哪天重新被跟踪，这一族必须真的恢复执行（还挂着 skip 就红）。
_DRAFT_UNJUDGEABLE = ("draft/ 已按业主决定移出仓库：机械改写守卫没有 HEAD 样本，"
                      "这一族当前不可判")


def _draft_family_skip_reason() -> str | None:
    """`draft/` 被跟踪 ⇒ `None`（这一族必须真跑）；不被跟踪 ⇒ 显式不可判的理由。

    判据本体就是 `git ls-files draft`（现算，不写死"这个仓库的 draft/ 一定不在"）——
    写死的话，底稿回来之后这一族仍然睡着，而没有任何东西会红。
    """
    return None if _paths("ls-files", "draft") else _DRAFT_UNJUDGEABLE


def test_a_script_rewrite_of_a_draft_or_a_doc_is_caught() -> None:
    """防线 (b)：`draft/` 下与一切 `.md` 都不许被脚本改写成"连行 + 去强调"。

    为什么要单独一条：那种改写不是语法错误（`.md` 与底稿都不进编译），全量门照样
    全绿、条数也不变 —— 它只把行号锚点与史实一起弄没。真事故两次
    （`draft/46-01` 644→550、`draft/46-03` 797→556），都靠 `git checkout HEAD --` 还原。
    """
    _skip = _draft_family_skip_reason()
    if _skip:
        # 三态：不可判要显式说出来（理由见 `_DRAFT_UNJUDGEABLE` 上那段注释）。
        pytest.skip(_skip)
    _assert_accident_negative_controls()
    changed, _new, _tracked = _changed_new_tracked()
    watch = [r for r in changed if r.startswith("draft/") or r.endswith(".md")]
    blobs = _head_blobs(watch)
    hits: list[str] = []
    skipped = 0
    for rel in watch:
        path = GIT_ROOT / rel
        if rel not in blobs or not path.is_file():
            # HEAD 里没有它（新增/改名进来的）或盘上已经删了：没有可比对象，
            # 计进 `skipped` 当读数（不是"没问题"，也不该把正常动作判红）。
            skipped += 1
            continue
        got = accident_form(blobs[rel], path.read_bytes())
        if got:
            hits.append(f"{rel}: {got}")

    # 三态：未跟踪的底稿没有 HEAD 可对拍 —— 那是"这一格覆盖不到"，要报出来。
    draft_tracked = _paths("ls-files", "draft")
    draft_disk = [p for p in (GIT_ROOT / "draft").rglob("*") if p.is_file()]
    untracked_drafts = len(draft_disk) - len(draft_tracked)
    reading = {"draft_tracked": len(draft_tracked), "draft_disk": len(draft_disk),
               "untracked_drafts": untracked_drafts, "watched_changed": len(watch),
               "compared": len(blobs), "skipped_no_head": skipped,
               "accident_hits": len(hits),
               "untracked_drafts_reason": (
                   f"draft/ 下 {untracked_drafts} 份未跟踪底稿没有 HEAD 可对拍 ⇒ "
                   "本判据覆盖不到它们（不是『它们没问题』）")}
    assert not hits, (
        f"底稿/文档被改写成『连行 + 去强调』形态（读数 {reading}）：" + "；".join(hits))


def _assert_accident_negative_controls() -> None:
    """防线 (b) 的负控：真事故样本必须能红；合法改写与"没动"不许红。"""
    head = _head_blobs([_ACCIDENT_SAMPLE]).get(_ACCIDENT_SAMPLE)
    assert head is not None, f"真事故样本取不到 HEAD 内容：{_ACCIDENT_SAMPLE}"
    got_counts = _counts(head)
    assert (got_counts["lines"], got_counts["bytes"], got_counts["stars"]) == _ACCIDENT_HEAD, (
        f"真事故样本的 HEAD 读数变了（{got_counts}）⇒ 负控的锚不再是那次事故："
        "要么换样本、要么在报告里更新锚（不许直接把数字改成新读数了事）")

    simulated = _accident_simulation(head)
    hit = accident_form(head, simulated)
    assert hit, "真事故的机械形态没被抓到 ⇒ 这条负控是空转"
    assert "336→0" in hit, f"命中的读数与那次事故不符：{hit}"
    assert accident_form(head, head) is None, "同内容不该报"
    added = head + b"\n\n## xin-zhang\n\n**zhong-dian**\n"
    assert accident_form(head, added) is None, (
        "合法的人工改写（追加内容、强调标记一起长）被误判成事故形态 ⇒ 判据会把正常工作判红")


def test_the_untracked_draft_gap_is_a_visible_state() -> None:
    """三态：未跟踪底稿"覆盖不到"必须是一档可见状态，不许静默跳过。

    这一条判的是读数本身：两份底稿计数要在同一个面上（跟踪 <= 盘上），
    并且那个缺口必须带着"没有 HEAD 可对拍 / 覆盖不到"的说法报出来。
    """
    _skip = _draft_family_skip_reason()
    if _skip:
        # `draft/` 整族不在索引里 ⇒ "跟踪 vs 盘上"这个读数没有第二个面可比
        # （100% 未跟踪不是缺口，是这一族整体不可判）。理由见 `_DRAFT_UNJUDGEABLE`。
        pytest.skip(_skip)
    draft_tracked = _paths("ls-files", "draft")
    draft_disk = [p for p in (GIT_ROOT / "draft").rglob("*") if p.is_file()]
    assert draft_disk, "draft/ 下一份底稿都没有 ⇒ 判据的落点不对（不是没问题）"
    assert draft_tracked, "draft/ 下一份被跟踪的底稿都没有 ⇒ git 那一半坏了"
    assert len(draft_tracked) <= len(draft_disk), (
        f"跟踪 {len(draft_tracked)} > 盘上 {len(draft_disk)} ⇒ 两个读数不是同一个面")
    gap = len(draft_disk) - len(draft_tracked)
    reason = (f"draft/ 下 {gap} 份未跟踪底稿没有 HEAD 可对拍 ⇒ "
              "本判据覆盖不到它们（不是『它们没问题』）")
    assert "没有 HEAD 可对拍" in reason and "覆盖不到" in reason, reason
    assert isinstance(gap, int) and gap >= 0, gap


def test_the_draft_family_resumes_as_soon_as_draft_is_tracked_again() -> None:
    """守卫：`draft/` 一旦重新被跟踪，这一族的 skip 必须立刻收回。

    为什么需要它：`pytest.skip` 是"这一族当前不可判"的**临时**形态，不是常态 ——
    没有这条守卫，`draft/` 哪天被重新跟踪（或换个名字重新入库），上面两条判据会
    继续 skip，而"整族睡着"与"整族绿着"在报告里长得一样（本仓库反复踩的坑）。

    它钉两件事，缺一件就会变成橡皮图章：
    - **状态**：`git ls-files draft` 非空 ⇒ 那个不可判的理由必须自己消失，
      且真事故样本必须取得到 HEAD 内容（底稿回来了、判据没回来 ⇒ 红）；
      为空 ⇒ 理由必须逐字带出来（"不可判"不许静默变"没问题"）。
    - **接线**：上面两条判据必须仍然经过同一个 `_draft_family_skip_reason()` 与
      `pytest.skip(...)`（读本文件源码判）。把 skip 写死进函数体、或把判据从
      理由上摘下来，都会在这里红 —— 那正是"未来被跟踪却仍然 skip"的形态。
    """
    src = pathlib.Path(__file__).resolve().read_text(encoding="utf-8")
    tree = ast.parse(src)
    family = ("test_a_script_rewrite_of_a_draft_or_a_doc_is_caught",
              "test_the_untracked_draft_gap_is_a_visible_state")
    for fn in family:
        node = next((n for n in tree.body
                     if isinstance(n, ast.FunctionDef) and n.name == fn), None)
        assert node is not None, f"这一族少了一条判据：{fn}（删判据不是处置不可判的形态）"
        body = ast.get_source_segment(src, node) or ""
        assert "_draft_family_skip_reason()" in body, (
            f"{fn} 不再问 `_draft_family_skip_reason()` ⇒ 它要么被写死成 skip、"
            "要么把不可判折成了通过")
        assert "pytest.skip(" in body, f"{fn} 不再显式 skip ⇒ 不可判会被读成通过"

    tracked = _paths("ls-files", "draft")
    reason = _draft_family_skip_reason()
    if not tracked:
        assert reason == _DRAFT_UNJUDGEABLE, (
            f"`draft/` 不在索引里，却给不出那条逐字理由（实得 {reason!r}）⇒ "
            "这一族的 skip 理由被改过，请把理由与 `_DRAFT_UNJUDGEABLE` 对齐")
        return
    assert reason is None, (
        f"`draft/` 已被重新跟踪（{len(tracked)} 份），这一族却仍报不可判 ⇒ "
        "把 `_draft_family_skip_reason()` 的 skip 收回、让两条判据恢复执行")
    assert _head_blobs([_ACCIDENT_SAMPLE]).get(_ACCIDENT_SAMPLE) is not None, (
        f"`draft/` 已被重新跟踪，但真事故样本 {_ACCIDENT_SAMPLE} 取不到 HEAD 内容 ⇒ "
        "换样本、或把 `_ACCIDENT_SAMPLE` 指向那份底稿的新落点")
