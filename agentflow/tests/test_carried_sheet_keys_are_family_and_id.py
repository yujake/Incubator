# -*- coding: utf-8 -*-
"""判据：携带单的 `mss:` 键带族 —— 「(族, 稿号)」两份同号的稿各自读各的，老键三态不猜。

## 为什么要有这一条

稿的身份在 `5ccb2041` 统一定成 (族, 稿号)（`manuscriptclosing.signed_candidates` /
`agent_loop._v_wait_gate_reading` / F、B、E 三道门都改了）。四族各有自己的号段、都从
`000000` 起（`manuscriptids` 的四条计数器）⇒ 同一号跨族在真机上是常态：
`projects/lp-ball` 的 `000000/000001/000002` 被 `b-proof` + `e-num` + `f-proof` 三族共用，
`projects/dct-min3-20261111` 的 `000000/000001` 被 `e-num` + `f-proof` 两族共用。

携带单这条路此前漏了：`depsection` 的写侧把键写成 `mss:<稿号>`、读侧按 `mss:<稿号>` 建
索引 ⇒ 同一号两族会撞键：`carried_manuscripts` 的 `seen` 把后到的那一行当"重列"丢掉，
索引里两族的稿只剩一份（读数与"那一条没签"同形，而 B 拿到的可能是另一族的稿）。

## 判据

| # | 造什么 | 期望 |
|---|---|---|
| a | 同一号两族（`f-proof-000000` + `e-num-000000`）各带一行 | 两行都进单、各自读到自己的那份（不撞、不混） |
| b | 单族单号（老形态 `mss:000000`） | 读数与改前逐字相同（只有行身份那一格多了族） |
| c | 只有老键 `mss:<号>` 的历史数据 | 仍读得到（族由载体路径唯一确定） |
| d | 老键 + 该号在两族都存在 | 不许猜：`named=True` + `source=none` + 点名「跨族同号、无法唯一定位」 |
| d2 | 同一张单走 B 的调用点（`register_statement`） | 受控拒 `manuscript_address_unreadable`，不挑一份稿、整笔不写 |
| d3 | 键写甲族、载体路径是乙族的稿 | 整节读不懂（`refused`），不许把乙族的稿读成甲族那一份 |
| e | 反真空：把键退回单号（三处族判定一起退回） | a 必红 |
"""
from __future__ import annotations

import hashlib
import pathlib

import pytest
from agentflow import depsection as DS

F_REL = "reports/f-proof-000000.md"
E_REL = "reports/e-num-000000.md"
REPORT = "reports/000000-research.md"
F_TEXT = ("# F 的证明手稿：甲\n\n- 计划：0001 · 子目标：s1\n\n## 命题\n\n"
          "设 f 在 [0,1] 上连续；则 f 一致连续。\n\n## 证明\n\n"
          "1. 取 delta=eps。\n2. 由第 1 步即一致连续。\n")
E_TEXT = ("# E 的数值手稿：乙\n\n## 命题\n\nlp 球最大中心截面的一个数值读数。\n\n"
          "## 数值结果\n\nA(2)=3.141592653589793\n")


# ------------------------------------------------------------------ 夹具
def _workspace(tmp_path: pathlib.Path, keys: list[tuple[str, str]]) -> pathlib.Path:
    """建一个工作区：两份真稿（f-proof / e-num，同号 000000）+ 一张手写携带单。

    `keys` 是携带单第一格逐行写什么 —— 新写法（`mss:f-proof-000000`）与老写法
    （`mss:000000`）共用这一个夹具，差别只在那一格。
    """
    root = tmp_path / "ws"
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / F_REL).write_text(F_TEXT, encoding="utf-8")
    (root / E_REL).write_text(E_TEXT, encoding="utf-8")
    sha = {rel: hashlib.sha256((root / rel).read_bytes()).hexdigest()
           for rel in (F_REL, E_REL)}
    lines = [
        "## 携带的证明手稿", "",
        "| 命题号（stmt:NNNNNN / exp:NNNNNN / mss:<族>-<号>） | 手稿路径 | sha256 | "
        "证明号（#pN，可空） |",
        "|---|---|---|---|",
    ]
    for key, rel in keys:
        lines.append(f"| {key} | {rel} | {sha[rel]} |  |")
    (root / REPORT).write_text("# D 的研究报告\n\n" + "\n".join(lines) + "\n",
                              encoding="utf-8")
    return root


def _publish(root: pathlib.Path, rows: list[dict]) -> None:
    """按 D 的写侧（`render_carried_section`）把那一节渲染进研究报告。"""
    (root / REPORT).write_text("# D 的研究报告\n\n" + DS.render_carried_section(rows),
                               encoding="utf-8")


def _decode(root: pathlib.Path, rel: str) -> str:
    """按字节解码（保留 `\\r\\n`）—— `depsection` 的读侧就是这么读的，比较口径要对齐。"""
    return (root / rel).read_bytes().decode("utf-8")


def _read(root: pathlib.Path, ids: list[str]) -> dict:
    return DS.read_carried_manuscript(str(root), statement_ids=ids)


def _a_holds(root: pathlib.Path) -> bool:
    """a 的核心：两支都读得到、且各自读到自己的那份。a 与 e 共用这一处判据。"""
    got_f = _read(root, ["f-proof-000000"])
    got_e = _read(root, ["e-num-000000"])
    return (got_f.get("source") == DS.SOURCE_CARRIED
            and got_e.get("source") == DS.SOURCE_CARRIED
            and got_f.get("path") == F_REL and got_e.get("path") == E_REL
            and str(got_f.get("text") or "") == _decode(root, F_REL)
            and str(got_e.get("text") or "") == _decode(root, E_REL))


# ============================================================ a 同一号两族
def test_a_same_number_in_two_families_reads_its_own_copy(
        tmp_path: pathlib.Path) -> None:
    """a：`mss:f-proof-000000` 与 `mss:e-num-000000` 各带一行 ⇒ 两行都在、各读各的。"""
    root = _workspace(tmp_path, [("mss:f-proof-000000", F_REL),
                                 ("mss:e-num-000000", E_REL)])
    parsed = DS.carried_manuscripts((root / REPORT).read_text(encoding="utf-8"))
    assert parsed["refused"] == "" and parsed["problems"] == [], parsed
    assert [(r["family"], r["manuscript_id"], r["key"]) for r in parsed["rows"]] == [
        ("f-proof", "000000", "mss:f-proof-000000"),
        ("e-num", "000000", "mss:e-num-000000"),
    ], parsed["rows"]

    got_f = _read(root, ["f-proof-000000"])
    got_e = _read(root, ["e-num-000000"])
    # 两份稿的正文不同 ⇒ "读到自己的那份"可判：路径、sha、正文三样都对上自己那一份。
    assert got_f.get("source") == DS.SOURCE_CARRIED, got_f
    assert got_e.get("source") == DS.SOURCE_CARRIED, got_e
    assert got_f.get("path") == F_REL and got_e.get("path") == E_REL, (got_f, got_e)
    assert got_f.get("sha256") == hashlib.sha256(
        (root / F_REL).read_bytes()).hexdigest(), got_f
    assert got_e.get("sha256") == hashlib.sha256(
        (root / E_REL).read_bytes()).hexdigest(), got_e
    assert got_f.get("text") == _decode(root, F_REL), got_f
    assert got_e.get("text") == _decode(root, E_REL), got_e
    # 不混：两份正文互不相同，读到 f 的那一次绝不是 e 的那一份（反之亦然）。
    assert got_f.get("text") != got_e.get("text"), (got_f, got_e)
    assert "E 的数值手稿" not in str(got_f.get("text") or ""), got_f
    assert "F 的证明手稿" not in str(got_e.get("text") or ""), got_e
    # 两个读数都给同一个稿号（号是同一号）、族不同 ⇒ 身份是 (族, 号)，不是号。
    assert (got_f.get("manuscript_id"), got_e.get("manuscript_id")) == ("000000", "000000")
    assert _a_holds(root) is True


# ============================================================ b 单族单号：逐字相同
def test_b_a_single_family_single_number_reads_byte_for_byte_as_before(
        tmp_path: pathlib.Path) -> None:
    """b：老形态（单族单号）的读数与改前逐字相同 —— 只多了 `ambiguous` 这一格空值。

    期望值是照改前的实现（`a038e6e1` 的 `depsection.py`）跑出来的那一份逐格抄下来的：
    `source` / `text` / `path` / `sha256` / `carried_by` / `tried` / `why` / `named` /
    `address` / `item` / `list_report` / `list_line` / `list_sha256` / `proof_no` /
    `matched_by` / `manuscript_id` 十六格一个不差。
    """
    root = _workspace(tmp_path, [("mss:000000", F_REL)])
    f_sha = hashlib.sha256((root / F_REL).read_bytes()).hexdigest()
    got = _read(root, ["000000"])
    want = {
        "checked": True, "source": DS.SOURCE_CARRIED,
        "text": _decode(root, F_REL),
        "path": F_REL, "sha256": f_sha, "carried_by": REPORT,
        "tried": [{"report": REPORT, "present": True, "rows": 1, "problems": 0}],
        "why": "", "named": True, "address": F_REL, "item": 1,
        "list_report": REPORT, "list_line": 7, "list_sha256": f_sha,
        "proof_no": 1, "matched_by": "statement_id", "manuscript_id": "000000",
        "ambiguous": {},
    }
    assert got == want, (got, want)
    # 行身份那一格按新约定带族（这是形状变更本身；上面那十六格是"读行为没变"）。
    parsed = DS.carried_manuscripts((root / REPORT).read_text(encoding="utf-8"))
    assert parsed["rows"][0]["key"] == "mss:f-proof-000000", parsed["rows"][0]
    assert parsed["rows"][0]["family"] == "f-proof", parsed["rows"][0]
    # 同一份稿写成新形态 ⇒ 读数与老形态逐格相同（写侧换键不改读行为）。
    new_root = _workspace(tmp_path / "new", [("mss:f-proof-000000", F_REL)])
    assert _read(new_root, ["000000"]) == got


# ============================================================ c 老键仍读得到
def test_c_a_legacy_bare_key_still_reads_when_the_family_is_in_the_carrier_path(
        tmp_path: pathlib.Path) -> None:
    """c：只有老键 `mss:<号>` 的历史数据 ⇒ 族由载体路径唯一确定后照读。"""
    root = _workspace(tmp_path, [("mss:000000", F_REL)])
    parsed = DS.carried_manuscripts((root / REPORT).read_text(encoding="utf-8"))
    row = parsed["rows"][0]
    assert (row["manuscript_id"], row["family"]) == ("000000", "f-proof"), row
    # 按裸号读（老调用方的读法）与按带族号读（新写法）都命中同一份。
    by_bare = _read(root, ["000000"])
    by_family = _read(root, ["f-proof-000000"])
    assert by_bare.get("source") == DS.SOURCE_CARRIED, by_bare
    assert by_family.get("source") == DS.SOURCE_CARRIED, by_family
    assert by_bare.get("path") == by_family.get("path") == F_REL, (by_bare, by_family)
    assert by_bare.get("text") == by_family.get("text"), (by_bare, by_family)


# ============================================================ d 跨族同号：不许猜
def test_d_a_cross_family_bare_number_is_not_guessed(tmp_path: pathlib.Path) -> None:
    """d：老键 + 该号在两族都存在 ⇒ 不挑一份，按三态给"点名但定位不到唯一一份"。

    两件事一起量：① 解析阶段不许把两族折成一行（那是"混"）；② 读的阶段不许挑第一行
    （那是"猜"）。
    """
    root = _workspace(tmp_path, [("mss:000000", F_REL), ("mss:000000", E_REL)])
    parsed = DS.carried_manuscripts((root / REPORT).read_text(encoding="utf-8"))
    assert parsed["refused"] == "" and parsed["problems"] == [], parsed
    assert [(r["family"], r["manuscript_id"], r["path"]) for r in parsed["rows"]] == [
        ("f-proof", "000000", F_REL), ("e-num", "000000", E_REL)], parsed["rows"]

    got = _read(root, ["000000"])
    # 不猜：既不是 f 那一份、也不是 e 那一份；落在"没取到"这一档，但不是"单里没这一笔"
    # （`named=True` 是调用点受控拒的那一格判据，见 `agent_b/register_statement.py`
    #  的 `elif bool(manuscript_carried.get("named")): return _refuse(REFUSED_ADDRESS, ...)`）。
    assert got.get("source") == DS.SOURCE_NONE, got
    assert got.get("text") == "" and got.get("path") == "", got
    assert got.get("named") is True, got
    assert "跨族同号、无法唯一定位" in str(got.get("why") or ""), got
    amb = dict(got.get("ambiguous") or {})
    assert amb.get("manuscript_id") == "000000", amb
    assert amb.get("families") == ["f-proof", "e-num"], amb
    assert amb.get("keys") == ["mss:f-proof-000000", "mss:e-num-000000"], amb
    assert amb.get("paths") == [F_REL, E_REL], amb
    # 读数里点名了（`tried` 也留一格，排障时看得见是哪两份）。
    assert any("跨族同号、无法唯一定位" in str(t.get("why") or "")
               for t in got.get("tried") or ()), got.get("tried")
    # 同一张单按带族号读 ⇒ 各自读得到（歧义只属于"裸号"那一档，不是单坏了）。
    assert _read(root, ["f-proof-000000"]).get("path") == F_REL
    assert _read(root, ["e-num-000000"]).get("path") == E_REL


def test_d2_the_call_point_refuses_instead_of_picking(tmp_path: pathlib.Path) -> None:
    """d2：同一张单走 B 的调用点 ⇒ 受控拒、整笔不写（不是挑一份稿、也不是崩）。

    夹具借 `test_dependency_wiring_is_live`（那一份已经把 B 的收录面装好了）：
    `derived_from` 让 `read_carried_manuscript` 拿到裸稿号 `000000` 这个候选。
    """
    import test_dependency_wiring_is_live as W

    store = W._ws(tmp_path)
    W._library(store)
    root = pathlib.Path(store.root)
    (root / "reports").mkdir(parents=True, exist_ok=True)
    for rel, text in ((F_REL, F_TEXT), (E_REL, E_TEXT)):
        (root / rel).write_text(text, encoding="utf-8")
    lines = ["## 携带的证明手稿", "",
             "| 命题号（stmt:NNNNNN / exp:NNNNNN / mss:<稿号>） | 手稿路径 | sha256 | "
             "证明号（#pN，可空） |", "|---|---|---|---|"]
    for rel in (F_REL, E_REL):
        sha = hashlib.sha256((root / rel).read_bytes()).hexdigest()
        lines.append(f"| mss:000000 | {rel} | {sha} |  |")
    (root / REPORT).write_text("# D 的研究报告\n\n" + "\n".join(lines) + "\n",
                               encoding="utf-8")
    before = len(list(store.rows("statements")))
    got = W._register(store, statement_full="新命题：跨族同号（判据夹具）。",
                      proof_text="1. 由第 1 步得结论（判据夹具）。",
                      derived_from=[W.THEOREM_A])
    assert got.get("ok") is not True, got
    assert got.get("kind") == DS.REFUSED_ADDRESS, got
    text = f"{got.get('error') or ''}{got.get('reason') or ''}"
    assert "跨族同号、无法唯一定位" in text, text
    addr = dict(got.get("addressing") or {})
    assert addr.get("refusal") == DS.REFUSED_ADDRESS, addr
    assert addr.get("mode") == "auto" and addr.get("hit") is False, addr
    # 整笔不写：没有拿其中一份稿去登记（两族的稿一份都没被收成这一条命题的证明）。
    assert len(list(store.rows("statements"))) == before, list(store.rows("statements"))


def test_d3_a_key_naming_another_family_is_refused(tmp_path: pathlib.Path) -> None:
    """d3：键写甲族、载体却是乙族的稿 ⇒ 整节读不懂（不许把乙族的稿读成甲族那一份）。"""
    root = _workspace(tmp_path, [("mss:e-num-000000", F_REL)])
    parsed = DS.carried_manuscripts((root / REPORT).read_text(encoding="utf-8"))
    assert parsed["rows"] == [], parsed["rows"]
    assert parsed["refused"] == DS.REFUSED_SECTION, parsed
    assert any("稿的族对不上" in str(p.get("why") or "")
               for p in parsed.get("problems") or ()), parsed
    got = _read(root, ["e-num-000000"])
    assert got.get("source") == DS.SOURCE_NONE and got.get("text") == "", got
    # 同一份稿换成键与载体一致的写法 ⇒ 读得到（拒的是"对不上"，不是这一号）。
    ok_root = _workspace(tmp_path / "ok", [("mss:f-proof-000000", F_REL)])
    assert _read(ok_root, ["f-proof-000000"]).get("path") == F_REL


# ============================================================ e 反真空
def test_e_reverting_the_key_to_the_bare_number_turns_a_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e：把 `mss:` 键退回单号（写、解析、补族三处一起退回）⇒ a 必红。

    退回的是"族这一格"整条链路：写侧不写族、解析不拆族、老键不从载体路径补族
    —— 合起来就是改前那一套单号键。a 的判据必须因此翻假（否则 a 量的不是这个键）。
    """
    root = _workspace(tmp_path, [("mss:f-proof-000000", F_REL),
                                 ("mss:e-num-000000", E_REL)])
    assert _a_holds(root) is True, "正控没成立：a 的判据在打桩之前就是假的"

    monkeypatch.setattr(DS, "_mss_key", lambda family, mid: f"mss:{mid}")
    monkeypatch.setattr(DS, "_mss_split", lambda text: ("", str(text or "").strip()))
    monkeypatch.setattr(DS, "_family_of_carrier", lambda rel: "")

    # 打桩之后要用打桩后的写侧重造那张单：D 的写侧就是 `render_carried_section`
    # （改前它写的就是单号），只改解析不改单，就不是"退回单号"那一态。
    sha = {rel: hashlib.sha256((root / rel).read_bytes()).hexdigest()
           for rel in (F_REL, E_REL)}
    _publish(root, [{"manuscript_id": "000000", "path": F_REL, "sha256": sha[F_REL]},
                    {"manuscript_id": "000000", "path": E_REL, "sha256": sha[E_REL]}])
    section = (root / REPORT).read_text(encoding="utf-8")
    # 打桩生效的证据：写侧退回单号、单上两行成了同一个键。
    assert section.count("| mss:000000 |") == 2, section
    assert "mss:f-proof" not in section and "mss:e-num" not in section, section

    assert _a_holds(root) is False, (
        "键退回单号之后 a 仍然是绿的 ⇒ a 量的不是「(族, 稿号)」这个键")
    # 红的原因就是撞键：两行折成一行（解析阶段），于是有两支里至少一支读不到。
    parsed = DS.carried_manuscripts(section)
    assert len(parsed["rows"]) == 1, parsed["rows"]
    assert _read(root, ["e-num-000000"]).get("source") != DS.SOURCE_CARRIED


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
