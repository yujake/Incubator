# -*- coding: utf-8 -*-
"""D 是想法与收获的作者，不是证明的落稿人（业主 2026-11-04 裁定）。

## 业主裁定（逐字）

「D 侧提示词里明确 D 可提供证明思路，甚至提供依赖面参考，最终的证明落稿拿签必须派给 F 完成，
D 只是提供想法并收获数值实验和理论攻坚的成果，然后再提出新的想法」

同日补充裁定（纠正"不落稿"那句）：「D 侧落的研究手稿就是既有指定形式的那种（收录 F、E 侧成果
以及其他一些东西，具体看已有口径）」⇒ D 的落稿面是既有形式：`reports/RESEARCH.md`（七节、
先读后改）＋ 交 B 时随研究手稿带上的携带单（F 的证明稿 + 文件 sha256，`agent_d/write_report.py`
的 `_carried_manuscripts` / `_carried_missing_reading`）。证明的落稿与拿签仍归 F。

## 真机证据（今晚 81 那趟，必须让教法拦住这个形态）

```text
D 全程没派 F，自己在 out/proofs/ 写了 3 份证明
（B-classical-zerofree 17.9 KB · C-part1 37.5 KB · D-part2 34.6 KB）
它的原话（notes/D.md 23:08:53）：「本轮未派子代理（本方向是自证写作，深度 2、墙钟剩量不足以再开
攻坚链；未派是判断不是遗漏）」
⇒ F/V/B 三条链一次都没启动，statements 0、vsigns 0、dependencies 0
```

## 判据

2026-11-05 收紧（业主口径：D 在任何路径写"带 `## 证明` 的证明正文"都要受控拒，例外只有
`RESEARCH.md` 里引用 F 的稿 —— 教法比实现严，以教法为准）。改前内容闸只查 `out/proofs/`
与 `*research*` 名，于是 `notes/x.md` / `reports/x.md` 带 `## 证明` 一律放行（真机读数：
`temp/audit_d_fs_gate2.py`）。

| 判据 | 它要证明的事 | 落在哪条判据 | 改前红在哪 |
|---|---|---|---|
| a | D 写 `notes/x.md` 带 `## 证明` ⇒ 拒 `reserved_framework_artifact`、detail 指路「要落稿就派 F」、盘上零写入 | `test_f_*` | 改前放行（内容闸只认 `out/proofs/` 与 research 名） |
| b | D 写 `reports/x.md` 带 `## 证明` ⇒ 同上（`fs.edit` 把 `## 思路` 改成带这一节同样拒） | `test_f_*` | 改前放行（同上） |
| c | D 写 `out/proofs/x.md` 带 `## 证明` ⇒ 同上（既有行为不变） | `test_b_*` | 改前写得进去（81 那趟的实际形态） |
| d | `RESEARCH.md` 带 `## 证明`，且点名盘上真有的 `reports/f-proof-<号>.md` 或带那份文件字节的 sha256 ⇒ 通过（例外仍在） | `test_a_*` ③ / `test_g_*` | 改前 `*research*` 名一律例外（比这宽） |
| e | `RESEARCH.md` 带 `## 证明` 但没点名 / 没 sha（或点了一个盘上没有的稿）⇒ 拒 | `test_a_*` ② / `test_g_*` | 改前没有这条内容闸 |
| f | 反真空：把"任何路径"那一步换回旧口径（只查 `out/proofs/` 与 research 名）⇒ a/b 必红 | `test_i_*` | —— |
| g | 不误伤：`## 证明思路` / `## 证明要点` 不是那一行（逐行整行比）⇒ 通过 | `test_h_*` | —— |
| h | `fs.write` / `fs.edit` 的 summary 与 `RESERVED_ARTIFACT_TABLE` 不一致 ⇒ 红（两个方向各一发） | `tests/test_fs_summary_matches_reserved_table.py` | 改前 summary 说 `RESEARCH.md` 对 D 拒写，而表里那一行已删 |
| a2 | D 写 F 的证明稿名字（`f-proof-*` / `*-proof.md`，任何目录）⇒ 拒、指路「要落稿就派 F」 | `test_a2_*` | 改前 D 的手写证明稿就是经 `fs.write` 落进 `out/proofs/` 的（81 那趟 3 份） |
| —— | D 交研究手稿给 B 时没带 F 的证明稿 ⇒ 既有携带单口径报 `缺携带单`，不是静默 | `test_d_*` | 既有口径已在；钉进本组防止 a 被读成"携带单可以不带" |
| —— | 反真空（2026-11-04）：把路径闸与内容闸一起打桩成放行 ⇒ 同一批写入必须成功 | `test_e_*` | —— |

## 收口选层

口径收在 `fs` 的角色-路径规则（`fs_tools.RESERVED_ARTIFACT_TABLE` + `_reserved_refusal`
的 D 内容分支），不收在 `specs/d.py` 的 `write_set`：`write_set` 是表级权限
（`research_questions` / `search_requests`），它对"往哪个文件写、写进去的是什么"一句话都说不了；
而"路径 + 内容"这一档正好是 `fs` 规则能判的。只收一处 —— `write_set` 一个字没动。

## 一件刻意不做的事

"这一节是不是 D 自己写的"无法从字节上判死：内容认得的是引用/转载的标记（F 的稿路径或它的
sha256）。真正的占位判定仍在收方：`reports/f-proof-<号>.md` 由 F 渲染、签由 V 盖、正文 sha 与
B 读到的稿逐字比。本文件守的是"D 有没有把落稿这一步留给自己"。
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import schema as S
from agentflow.agent_d import AgentD
from agentflow.conductor import calling_as
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import fs_tools as FT

#: 受控码（与 `fs` 的保留表同一档）。
KIND = "reserved_framework_artifact"

#: 研究手稿：七节、收录 F/E 的成果；没有 `## 证明` 节。
RESEARCH = (
    "# 研究手稿\n\n"
    "## 成果概述\n\n"
    "- 引 F 的稿，不复制它的证明：见 `reports/f-proof-000001.md`（sha256 由携带单给）。\n\n"
    "## 定义与已知\n\n- 见 `stmt:000000`。\n\n"
    "## 已确定的结论\n\n- 那条命题由 F 落稿、V 签。\n\n"
    "## 尝试与失败\n\n- 无。\n\n"
    "## 例子与反例\n\n- 见 E 的 `out/experiments/000000/exhaustion.md`。\n\n"
    "## 未解问题\n\n- 下一步的那条猜想。\n\n"
    "## 下一步\n\n- 读回 F 的结果，立新猜想，再派 F。\n"
)


def _ws(path: pathlib.Path) -> tuple[pathlib.Path, object]:
    root = path / "ws"
    store = Store(root)
    store.init()
    return root, build_registry(store=store, workspace_root=root).registry


def _call(reg, role: str, tool: str, **params):
    """按某个角色的身份调一次工具（"我是谁"由 `calling_as` 挂上，与真机同一条路）。"""
    with calling_as("t-probe", role):
        return reg.call(tool, role=role, **params)


def _land_f_manuscript(root: pathlib.Path, *, sid: str = "000001",
                       body: str = "1. 由定义直接得到。\n") -> tuple[str, str]:
    """在盘上落一份 F 的证明稿（模拟 F 的 proof 动作产物；直接写盘绕过 fs 闸，这是框架那一侧）。

    返回 `(工作区相对路径, 文件字节的 sha256)` —— 后者就是携带单要转载的那一格。
    """
    rel = f"reports/f-proof-{sid}.md"
    text = (f"# F 的证明手稿\n\n- 命题号：stmt:{sid}\n\n"
            f"## 命题\n\n命题 {sid} 的完整正文（含假设）。\n\n"
            f"## 证明\n\n{body}\n\n"
            "## 依赖\n\n"
            "| 引用 | 命题号 | 用在哪一步 | 路径号 |\n"
            "|---|---|---|---|\n")
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return rel, hashlib.sha256(target.read_bytes()).hexdigest()


# ============================================================ a 研究手稿的既有形式
def test_a_the_research_manuscript_may_be_written_but_not_its_own_proof_section(
        tmp_path: pathlib.Path) -> None:
    """a：`reports/RESEARCH.md` 是 D 的既有交付物（允许）；自己新写 `## 证明` 节 ⇒ 拒。

    三态一起钉：① 没有 `## 证明` 节 ⇒ 放行；② 自己新写一节 ⇒ 受控拒且盘上逐字未动；
    ③ 转载 F 的稿（点名盘上那份 `reports/f-proof-<号>.md` 并带它的文件 sha256）⇒ 放行。
    第三档是"引用者"与"作者"的分界：允许引，不许自己写。
    """
    root, reg = _ws(tmp_path)
    rel = "reports/RESEARCH.md"

    # ① 既有形式：七节研究手稿，没有 `## 证明` 节 ⇒ 允许
    first = _call(reg, "D", "fs.write", path=rel, content=RESEARCH)
    assert first.ok is True, ("D 的研究手稿 `reports/RESEARCH.md` 被拒了 —— 它是既有交付物", first)
    assert (root / rel).is_file()

    # ② D 自己新写一节 `## 证明`（没引用 F 的稿、没转载 F 的 sha）⇒ 受控拒、零改动
    own = RESEARCH + "\n## 证明\n\n1. 由我自己推出来（这一步本该派 F）。\n"
    second = _call(reg, "D", "fs.write", path=rel, content=own, overwrite=True)
    assert second.ok is False, ("D 自己写的 `## 证明` 节被放行了 —— 这就是今晚 81 那趟的形态", second)
    assert second.meta.get("kind") == KIND, second.meta
    detail = str(second.error or "")
    assert "证明要 F 落稿拿签" in detail, detail
    assert "reports/f-proof-<号>.md" in detail, detail
    assert "sha" in detail, detail
    assert (root / rel).read_text(encoding="utf-8") == RESEARCH, "被拒了却改了盘上那一份"

    # ③ 转载 F 的稿（路径 + 那份稿的 sha256 都在手稿里）⇒ 允许
    f_rel, f_sha = _land_f_manuscript(root)
    cited = (RESEARCH + "\n## 证明\n\n"
             f"（转载 F 的 `{f_rel}`，sha256={f_sha}）\n")
    third = _call(reg, "D", "fs.write", path=rel, content=cited, overwrite=True)
    assert third.ok is True, ("引用了盘上 F 的稿与它的 sha，仍被拒 —— 引用者这一档被误伤", third)
    assert (root / rel).read_text(encoding="utf-8") == cited


def test_a2_the_proof_manuscript_names_belong_to_f(tmp_path: pathlib.Path) -> None:
    """a2：F 的证明稿名字（任何目录）不归 D —— 拒、指路「要落稿就派 F」。

    "目录不是判据"（`fs_tools` 2026-10-27 D6 那一段）：换个目录不改名字仍然是 F 的稿。
    """
    root, reg = _ws(tmp_path)
    for rel in ("reports/f-proof-000001.md", "notes/f-proof-plan-000001.md",
                "notes/x-proof.md", "out/proofs/y-proof.md"):
        res = _call(reg, "D", "fs.write", path=rel, content="# 思路\n\n先引那条引理。\n")
        assert res.ok is False, (rel, res)
        assert res.meta.get("kind") == KIND, (rel, res.meta)
        assert "要落稿就派 F" in str(res.error or ""), (rel, res.error)
        assert not (root / rel).exists(), f"{rel} 被拒了却仍落盘"


# ============================================================ b 攻坚过程记录不是证明稿
def test_b_a_proof_section_in_the_attack_record_is_refused(tmp_path: pathlib.Path) -> None:
    """b：`out/proofs/x.md` 含 `## 证明` 节 ⇒ 受控拒（81 那趟的实际形态）。

    `fs.edit` 同一条闸：先写一份只有 `## 思路` 的记录，再想用定点替换补一节 `## 证明`
    —— 能改正文就等于能绕过 `fs.write`。
    """
    root, reg = _ws(tmp_path)
    for rel in ("out/proofs/x.md", "out/proofs/deep/dir/x.md"):
        res = _call(reg, "D", "fs.write", path=rel,
                    content="# 攻坚过程记录\n\n## 证明\n\n1. 我自己写完了。\n")
        assert res.ok is False, (rel, res)
        assert res.meta.get("kind") == KIND, (rel, res.meta)
        assert "要落稿就派 F" in str(res.error or ""), (rel, res.error)
        assert not (root / rel).exists(), f"{rel} 被拒了却仍落盘"

    # fs.edit：同一份记录，从"只有思路"改成"带一节证明" ⇒ 拒，盘上逐字未动
    rel = "out/proofs/x.md"
    seed = "# 攻坚过程记录\n\n## 思路\n\n先试归纳法。\n"
    assert _call(reg, "D", "fs.write", path=rel, content=seed).ok is True
    got = _call(reg, "D", "fs.edit", path=rel, old_string="先试归纳法。",
                new_string="先试归纳法。\n\n## 证明\n\n1. 我自己写完了。")
    assert got.ok is False, got
    assert got.meta.get("kind") == KIND, got.meta
    assert "要落稿就派 F" in str(got.error or ""), got.error
    assert (root / rel).read_text(encoding="utf-8") == seed, "被拒了却改了盘上那一份"


# ============================================================ c 提供想法（正控）
def test_c_thoughts_and_dependency_notes_are_allowed(tmp_path: pathlib.Path) -> None:
    """c：只写 `## 思路` / `## 依赖面参考` ⇒ 允许（业主说的"D 可提供证明思路"）。

    这一条是 a/b 的正控：闸不许扩成"out/proofs/ 里什么都不许写" —— 那会逼模型把想法
    换个更像笔记的名字，绕过口反而更难查。
    """
    root, reg = _ws(tmp_path)
    rel = "out/proofs/x.md"
    content = ("# 攻坚过程记录（D 的想法）\n\n"
               "## 思路\n\n"
               "- 先引 `stmt:000000` 那条已证命题，再按 X → Y → Z 的顺序走。\n\n"
               "## 依赖面参考\n\n"
               "- 必引：`stmt:000000`（先用）、`stmt:000001`（后用）。\n"
               "- 顺序：定义 → 滤环引理 → 主命题；不要先摊开主命题。\n")
    res = _call(reg, "D", "fs.write", path=rel, content=content)
    assert res.ok is True, res
    assert (root / rel).read_text(encoding="utf-8") == content


# ============================================================ d 交 B 时随稿带 F 的证明稿
def _statement(store: Store, stmt_id: str, *, derived_from: list[str] | None = None,
               proof_text: str = "") -> dict:
    """写一条在册命题（只为本组判据造读数；携带单缺口读的是 `derived_from` / `stmt:` 引用）。"""
    row = S.Statement(
        stmt_id=stmt_id, origin="own_result", kind="theorem",
        label=f"在册命题 {stmt_id}",
        statement_text=f"命题 {stmt_id} 的短版",
        statement_full=f"命题 {stmt_id} 的完整正文（含假设）。",
        proof_text=proof_text or f"命题 {stmt_id} 的证明正文（判据夹具）。",
        derived_from=list(derived_from or []),
        evidence_kind="heuristic", status="active", quote_verified=None,
        quote_reason="判据夹具：自产命题，没有外部引文要比对",
        created_at=S.now_iso(), created_by="agent-B")
    row.validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())
    return row.to_dict()


def test_d_the_carried_sheet_reading_speaks_when_fs_proof_is_missing(
        tmp_path: pathlib.Path) -> None:
    """d：交研究手稿给 B 时没带 F 的证明稿 ⇒ 既有携带单口径报"缺携带单"。

    这一条不改 `agent_d/write_report.py`（既有口径已对）：只把它钉进本组，防止
    "a 允许 D 写 RESEARCH.md" 被读成"携带单可以不带"。`carried_missing=True` + 点名
    那几条被引用的在册命题 + 报告正文里真写着这一格。
    """
    store = Store(tmp_path / "ws")
    store.init()
    theorem = S.format_id(0)
    lemma = S.format_id(1)
    _statement(store, theorem)
    _statement(store, lemma, derived_from=[theorem],
               proof_text=f"1. 由在册定理得到（依据：stmt:{theorem}）。")

    d = AgentD(store, config={"workspace_root": store.root})
    report = pathlib.Path(d.write_report())
    delivery = dict(d.last_delivery)
    assert delivery.get("carried_missing") is True, delivery
    reason = str(delivery.get("carried_missing_reason") or "")
    assert "缺携带单" in reason, reason
    assert theorem in reason, reason
    text = report.read_text(encoding="utf-8")
    assert "carried_missing" in text, text[-2000:]
    assert theorem in text, text[-2000:]


# ============================================================ e 反真空
def test_e_stubbing_the_gates_out_turns_a_and_b_green(tmp_path: pathlib.Path,
                                                      monkeypatch) -> None:
    """e（反真空）：把 a/b 的闸打桩成放行 ⇒ 同一批写入必须成功。

    打桩点是这两处：① 表里 D 的证明稿那两行（`FT.D_PROOF_PATH_RULES`）；
    ② `_d_proof_body_refusal`（`## 证明` 那一节的内容闸）。打桩之后 a/b 的写入全都
    成功 ⇒ 它们的"被拒"只能来自这两道闸，不是别处顺手写的判断。
    """
    living = tuple(row for row in FT.RESERVED_ARTIFACT_TABLE
                   if not (row[0] == "D" and row[1] in FT.D_PROOF_PATH_RULES))
    assert len(living) == len(FT.RESERVED_ARTIFACT_TABLE) - len(FT.D_PROOF_PATH_RULES), (
        "表里 D 的证明稿规则数与 `D_PROOF_PATH_RULES` 对不上 ⇒ 打桩点在核一个空集")
    monkeypatch.setattr(FT, "RESERVED_ARTIFACT_TABLE", living)
    monkeypatch.setattr(FT, "_d_proof_body_refusal",
                        lambda rel, role, content, root: None)

    root, reg = _ws(tmp_path)
    a = _call(reg, "D", "fs.write", path="reports/RESEARCH.md",
              content=RESEARCH + "\n## 证明\n\n1. 我自己写的。\n")
    assert a.ok is True, ("闸被打桩成放行之后 a 仍然被拒 ⇒ a 的红不来自这两道闸", a)
    b = _call(reg, "D", "fs.write", path="out/proofs/x.md",
              content="# 记录\n\n## 证明\n\n1. 我自己写的。\n")
    assert b.ok is True, ("闸被打桩成放行之后 b 仍然被拒 ⇒ b 的红不来自这两道闸", b)
    assert (root / "reports" / "RESEARCH.md").is_file()
    assert (root / "out" / "proofs" / "x.md").is_file()


# ============================================================ a / b / c 任何路径都受控拒
#: 一份"可提交的证明稿"正文（`## 证明` 是整行）。
OWN_PROOF = "# 随手记\n\n## 证明\n\n1. 设 G 是 p-群，由归纳法得证。\n"


def test_f_any_path_refuses_d_own_proof_body(tmp_path: pathlib.Path) -> None:
    """a/b/c：内容闸不按目录、不按名字 —— 任何路径上带 `## 证明` 都受控拒。

    改前只有 `out/proofs/` 与 `*research*` 名受这条闸（真机读数
    `temp/audit_d_fs_gate2.py`：`notes/随手记.md` / `reports/随手记.md` 带 `## 证明`
    都放行）⇒ 这两格就是本轮的 a/b。`out/proofs/` 是 c：既有行为不变。
    `fs.edit` 走同一条闸 —— 判的是"改完之后那一份正文"，不是调用方给的那一小段。
    """
    root, reg = _ws(tmp_path)
    for rel in ("notes/x.md", "reports/x.md", "notes/deep/dir/x.md",
                "out/proofs/x.md", "notes/随手记.md"):
        res = _call(reg, "D", "fs.write", path=rel, content=OWN_PROOF)
        assert res.ok is False, (rel, res)
        assert res.meta.get("kind") == KIND, (rel, res.meta)
        detail = str(res.error or "")
        assert "要落稿就派 F" in detail, (rel, detail)
        assert "`## 证明`" in detail, (rel, detail)
        assert not (root / rel).exists(), f"{rel} 被拒了却仍落盘"

    # fs.edit：把"只有思路"的记录改成"带一节证明" —— 能改正文就等于能绕过 fs.write
    rel = "notes/x.md"
    seed = "# 随手记\n\n## 思路\n\n先试归纳法。\n"
    assert _call(reg, "D", "fs.write", path=rel, content=seed).ok is True
    got = _call(reg, "D", "fs.edit", path=rel, old_string="先试归纳法。",
                new_string="先试归纳法。\n\n## 证明\n\n1. 我自己写完了。")
    assert got.ok is False, got
    assert got.meta.get("kind") == KIND, got.meta
    assert "要落稿就派 F" in str(got.error or ""), got.error
    assert (root / rel).read_text(encoding="utf-8") == seed, "被拒了却改了盘上那一份"


# ============================================================ d / e 例外只有 RESEARCH.md
def test_g_the_only_exception_is_a_research_manuscript_citing_a_real_f_proof(
        tmp_path: pathlib.Path) -> None:
    """d/e：例外只属于 `RESEARCH.md` 里引用盘上真有的 F 稿；不点名或点空气稿都拒。

    d 的"点名路径 + 带 sha256"已由 `test_a_*` ③ 钉过；这里补三格：
    ① 只带那份文件字节的 sha256（不点名路径）⇒ 通过；
    ② 点名一个盘上不存在的号 ⇒ 拒（"写了 `f-proof-` 这几个字"不算引用）；
    ③ 同一段引用放进 `notes/other-research.md` ⇒ 拒 —— 例外只有一个落点，
       不是"名字里带 research 就放行"（2026-11-05 把 `_is_research_manuscript`
       从"名字含 research"收窄成"文件名就是 `RESEARCH.md`"）。
    """
    root, reg = _ws(tmp_path)
    f_rel, f_sha = _land_f_manuscript(root)
    # 去掉夹具正文里那句"见 reports/f-proof-000001.md"，让这一组的引用只来自我们加的那一段。
    plain = RESEARCH.replace("见 `reports/f-proof-000001.md`", "见携带单点名的那一份")

    cited_by_sha = plain + f"\n## 证明\n\n（转载 F 的稿，sha256={f_sha}）\n"
    ok = _call(reg, "D", "fs.write", path="reports/RESEARCH.md", content=cited_by_sha)
    assert ok.ok is True, ("只带 F 稿的 sha256 仍被拒 ⇒ 例外被收窄成必须点名路径", ok)

    missing = plain + "\n## 证明\n\n（引用 `reports/f-proof-999999.md`）\n"
    bad = _call(reg, "D", "fs.write", path="reports/RESEARCH.md", content=missing,
                overwrite=True)
    assert bad.ok is False, ("点名了一个盘上不存在的 F 稿却放行", bad)
    assert bad.meta.get("kind") == KIND, bad.meta
    assert "证明要 F 落稿拿签" in str(bad.error or ""), bad.error
    assert (root / "reports" / "RESEARCH.md").read_text(encoding="utf-8") == cited_by_sha

    for rel in ("notes/other-research.md", "notes/RESEARCH-notes.md"):
        res = _call(reg, "D", "fs.write", path=rel,
                    content="# 笔记\n\n## 证明\n\n（引用 `" + f_rel + "`）\n")
        assert res.ok is False, (f"例外被扩到了 {rel}（它不是那份研究手稿）", res)
        assert res.meta.get("kind") == KIND, (rel, res.meta)

    # 目录不是判据（2026-11-04 既有裁定）：同名的研究手稿换个目录仍是那一份。
    anywhere = plain + f"\n## 证明\n\n（引用 `{f_rel}`）\n"
    here = _call(reg, "D", "fs.write", path="notes/RESEARCH.md", content=anywhere)
    assert here.ok is True, ("同名的研究手稿换目录被误伤", here)


# ============================================================ g 不误伤
def test_h_the_proof_section_is_matched_line_by_line(tmp_path: pathlib.Path) -> None:
    """g：`## 证明思路` / `## 证明要点` 不是 `## 证明` 那一行 ⇒ 放行。

    `_has_proof_section` 逐行整行比（与 `depsection.SECTION_PROOF` 同源），不误伤
    "提供证明思路"这一档 —— 那正是业主 2026-11-04 说 D 可以给的东西。
    """
    root, reg = _ws(tmp_path)
    cases = {
        "notes/思路.md": "# 思路\n\n## 证明思路\n\n先引 `stmt:000000`，再按 X → Y 走。\n",
        "reports/要点.md": "# 要点\n\n## 证明要点\n\n- 归纳。\n- 滤环。\n",
        "notes/正文里提一句.md": "# 笔记\n\n正文里提到 `## 证明` 这个词，但它不是一节标题。\n",
    }
    for rel, content in cases.items():
        res = _call(reg, "D", "fs.write", path=rel, content=content)
        assert res.ok is True, (rel, res)
        assert (root / rel).read_text(encoding="utf-8") == content, rel


# ============================================================ f 反真空
def test_i_the_old_scope_lets_notes_and_reports_through(tmp_path: pathlib.Path,
                                                        monkeypatch) -> None:
    """f（反真空）：把"任何路径"那一步换回旧口径 ⇒ a/b 必须放行。

    打桩点就是这一步本身（`_d_proof_body_scope_refused`，2026-11-05 新加的分离层）：
    换成"只查 `out/proofs/` 与 research 名"的旧实现之后，同一批写入必须成功 ——
    于是 a/b 的"被拒"只可能来自"任何路径"这一刀，不是别处顺手写的判断。
    `out/proofs/` 在旧口径下照拒（这一格没被放宽）。
    """
    def _old_scope(rel, content, root):
        if not FT._has_proof_section(content):
            return False
        low = str(rel or "").replace("\\", "/").casefold()
        if low.startswith(FT.D_ATTACK_RECORD_DIR):
            return True
        return bool(FT._is_research_manuscript(rel)
                    and not FT._cites_an_f_manuscript(root, content))

    monkeypatch.setattr(FT, "_d_proof_body_scope_refused", _old_scope)
    root, reg = _ws(tmp_path)
    for rel in ("notes/x.md", "reports/x.md"):
        res = _call(reg, "D", "fs.write", path=rel, content=OWN_PROOF)
        assert res.ok is True, (
            f"旧口径下 {rel} 仍被拒 ⇒ a/b 的红不来自「任何路径」这一刀", res)
        assert (root / rel).is_file(), rel
    still = _call(reg, "D", "fs.write", path="out/proofs/x.md", content=OWN_PROOF)
    assert still.ok is False, still
    assert still.meta.get("kind") == KIND, still.meta
