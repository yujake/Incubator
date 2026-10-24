# -*- coding: utf-8 -*-
"""判据：一条定理的三种证法，不许被登记成三条定理（业主 2026-10-24）。

## 业主的原话（唯一权威）

业主逐字：「现在三路径证明被注册成了三个定理，后面打括号是路线几，这很不好。」
以及后来补的两句准绳：

- 「不用机械判据，让秘书洗定理名，让秘书判。」
- 「定理描述一致（什么条件推出什么结论），就是一个定理」。

## 真机读数（`projects/sylow4`，只读复算，本文件不碰那个工作区）

```
000001 | conjecture | proof_no=None | proofs=0 | label「Sylow 三定理（路线一：类方程/强归纳 + 共轭作用，自证草稿，待 V 审签）」
000002 | theorem    | proof_no=None | proofs=0 | label「Sylow 三定理（McKay p-元组不动点计数 + 极大 p-子群正规化子路线，独立证明…）」
000003 | conjecture | proof_no=None | proofs=0 | label「Sylow 定理（路线三：Wielandt p^a-子集计数；S1+S2+S3…）」
```

⇒ 同一条定理被拆成三条命题；"路线"写进了命题标签；三条的 `proof_no` 都不是"第几份证明"。

## 这一份钉的五条（外加两条护栏）

| 条 | 它要证明的事 | 改前（这一笔之前）为什么是红的 |
|---|---|---|
| a | 带「（路线一：…）」的 label 进去之后变成干净的定理名，且那段路线落在证明那一层 | 改前没有洗名这一步：label 原样落盘（真机 sylow4 三行就是这么来的） |
| b | 三次不同路线的同一条命题 ⇒ 一条 `stmt` + `proof_no` 1..3 | 改前"同一命题"只按 `statement_full` 的键/相似度判：三种写法（类方程 / McKay / Wielandt）词面相似度 0.35–0.44 < 0.85 ⇒ 三条命题 |
| c | 判不了（unknown）⇒ 不并、留 basis（负控：判不了不许猜） | 改前没有这一档，机械相似度达阈值就并 |
| d | 同一条正文进来两次 ⇒ 只调用模型一次（按正文 sha256 缓存） | 改前没有这个缓存：每交一次就是一次调用（真机 sylow4 = 三笔钱买同一句话） |
| e | 反真空：判据打桩成恒 same ⇒ 真正不同的两条定理被错并 ⇒ 必红；恒 different ⇒ b 必红 | 这一条不靠改前代码：它证明 a–d 的绿有对象（判据真的在判） |
| 护栏① | 三条证明的依赖各落 `#p1/#p2/#p3`（并在单笔三证明里落 `path_group` 1/2/3） | 正控：既有机制不许被这一笔改坏 |
| 护栏② | 秘书没接上（没缝 / 超时）⇒ 退回既有机械判据，写入路不瘫 | 正控：既有判据保留在兜底那一档 |

## "改前红"怎么可复现

改前的行为就是"没有这道判定"。把
`Secretary.adjudicate_proposition` 打桩成"没查成"（`checked=False`）就精确复现了改前：
`test_before_this_feature_exists_the_three_rows_come_back` 用同一组读数断言 a 与 b 当场
变红（三行命题、label 里还带着"路线一"）。

## 边界

全部 tmp 工作区、零真实模型调用（秘书那一次调用由 `_FakeSeam` 顶替，它只做两件假事：
把标签里的括号内容挪到 `route`、按定理名判 same / different —— 真判据是提示词里的那条
准绳，见 `secretary._judge_system("proposition_identity")`）。不读写 `projects/`。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

# 与 `tests/conftest.py` 同一个注入方式（这一份也要能在一棵临时源码树上单独跑）。
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import propositionkey as PK
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.agent_c.proof_chain import _DepGraph
from agentflow.secretary import Secretary
from agentflow.store import Store

#: 第一条命题落盘时的号（store 从 0 开始发号）。
SID = S.format_id(0)
#: 三条证明各自引一份文献（依赖要落得下来，才看得见"按证明号分开"）。
LIT_1 = S.format_id(9)
LIT_2 = S.format_id(8)
LIT_3 = S.format_id(7)

#: sylow4 那三条标签（逐字取自真机读数，唯一的改动是把截断的省略号补成完整的一句）。
LABEL_1 = "Sylow 三定理（路线一：类方程/强归纳 + 共轭作用，自证草稿，待 V 审签）"
LABEL_2 = "Sylow 三定理（McKay p-元组不动点计数 + 极大 p-子群正规化子路线，独立证明）"
LABEL_3 = "Sylow 定理（路线三：Wielandt p^a-子集计数；S1+S2+S3）"
#: 洗过之后应当长成的那个定理名（业主的例子里就是这一句）。
CLEAN_NAME = "Sylow 三定理"

#: 一条命题的三种写法（类方程版 / McKay 版 / Wielandt 版）。
#: 它们是同一个数学命题的三种表述 —— 词面相似度 0.35–0.44（低于 0.85），所以改前的
#: 机械判据抓不到，这正是业主说的"词面相似度抓不到"。
FULL_1 = ("设 G 是有限群，p 是素数；则 G 的 Sylow p-子群存在，任意两个 Sylow p-子群共轭，"
          "且 Sylow p-子群的个数 ≡ 1 (mod p) 并整除 |G| 中 p 的幂次。")
FULL_2 = ("设 G 是有限群，p 是素数，且 p^a 整除 |G|；则 G 存在阶为 p^a 的子群，"
          "且所有 p^a 阶子群两两共轭，其个数模 p 余 1。")
FULL_3 = ("设有限群 G 的阶写成 p^a m，其中 p 不整除 m；则在 G 里 p^a 阶子群的个数 "
          "≡ 1 (mod p)，并且 p^a 阶子群恰好构成一个共轭类。")

#: 三条截然不同的证法（类方程 / McKay 不动点计数 / Wielandt 子集计数）。
#: 互相似度 0.15–0.23（低于 0.80）⇒ 它们不是"同种证明"，不许被 `proof_same_kind` 拒掉。
PROOF_1 = ("证明（类方程）：让 G 以共轭作用作用在 Sylow p-子群族上，写出类方程，"
           "把轨道长写成正规化子指数的形式。取极大 p-子群，用正规化子的阶与 |G| 的 "
           "p-部分比较，强归纳说明共轭类只有一族，轨道大小即指数，故个数 ≡ 1 (mod p)。"
           "见 lit:000009。")
PROOF_2 = ("证明（McKay）：数集合，取所有满足乘积为单位的 a 元组。由整除关系得这个集合的"
           "大小被 p 整除。让 p-群逐坐标共轭作用上去，不动点恰是取值在该子群里的元组，"
           "于是不动点数是 p 的幂的倍数，并且与集合大小同余。见 lit:000008。")
PROOF_3 = ("证明（Wielandt）：把指定大小的子集全体记为 S，令 G 按左乘作用在 S 上。"
           "先算 |S| 的 p-部分等于指定大小的 p-部分，取一条轨道使轨道长不被 p 整除，"
           "其主子便是所求子群；再把任意同阶子群与它比较，得共轭与计数。见 lit:000007。")

#: 负控用的一对"真正不同的定理"（Sylow 定理 vs 中心引理）。
FULL_CENTER = "设 G 是有限群；则 G 的中心含有一个非平凡的 p-子群，且该 p-子群在 G 中正规。"
PROOF_CENTER = ("证明：让 G 以共轭作用作用在自身，中心是不动点全体。按类方程把 |G| 拆成"
                "中心与若干个大小被 p 整除的轨道，p-群的中心因此非平凡，取其 p-部分即得。")

#: c 用的那一对：两条表述不同、机械判据判"同一条"的写法（引导词不同、内容相同）。
#: 这一对是 sharp 的样本 —— 秘书判 unknown 时必须压过机械判据（否则"不并"这句话没对象）。
FULL_A = "设 G 是 3-正则群；则弦长函数不是常值。"
FULL_A_KEY = "假设 G 为 3-正则群，于是弦长函数不是常值。"
PROOF_A = ("证明：把弦长函数记为 f，由定义直接计算每个顶点的邻域大小，弦长只依赖邻域结构，"
           "故 f 在正则性下取常值，与假设矛盾。")
PROOF_D = ("证明：对顶点数作强归纳。取一条最长路径，把端点邻域配对，再以诱导子图归结到"
           "更小的图，最终得到递推，导出非常值。")


# ------------------------------------------------------------------ 小工具

def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _put_lit(st: Store, lit_id: str) -> None:
    row = S.Literature(lit_id=lit_id, title=f"文献 {lit_id}", type="J", summary="夹具",
                       path=None, added_at=S.now_iso())
    row.validate()
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", row.to_dict())


def _rows(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("statements")]


def _deps(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("dependencies")]


def _proof_nos(row: dict) -> list[int]:
    return [int(no) for no, _t in VR.proof_list(row)]


def _own(full: str, label: str) -> dict:
    """自产命题的必填件（`doc_id` + `quote_reason`；B-2 之后首登按猜想）。"""
    return {"statement_full": full, "statement_text": full[:24], "label": label,
            "origin": "own_result", "kind": "conjecture",
            "doc_id": S.format_id(0), "quote_reason": "我方自产命题，没有外部引文要比对"}


#: 假秘书的那一句判定：它不看数学，只看定理名（`_name_key`）与标签里的括号。
#:
#: 为什么桩可以这么做：这一份钉的是"秘书说了算"这条路（`adjudicate_proposition` 的三态
#: 落到哪、标签洗没洗、缓存没缓存），不是模型本身的智能。真判据在提示词里
#: （`secretary._judge_system("proposition_identity")`：条件 → 结论一致就是同一个定理）。
_PARENS = re.compile(r"[（(][^（()）]*[）)]")
_ORDINAL_THEOREM = re.compile(r"[一二三四五六七八九十]+(?:个)?定理")


def _clean_name(label: str) -> str:
    """把标签洗成定理名：去掉括号里的修饰（路线 / 草稿 / 待审都不进名字）。"""
    text = _PARENS.sub(" ", str(label or ""))
    return re.sub(r"\s+", " ", text).strip(" ·—-")


def _name_key(name: str) -> str:
    """判"是不是同一个名字"用的键：`三定理` 与 `定理` 是同一个名字的两种写法。"""
    text = _ORDINAL_THEOREM.sub("定理", _clean_name(name)).lower()
    return re.sub(r"\s+", " ", text).strip()


def _route(label: str) -> str:
    """标签里被洗掉的那段（路线 / 草稿状态）：它要挪到证明那一层，不许丢。"""
    found = _PARENS.search(str(label or ""))
    return found.group(0).strip("（）()") if found else ""


def _material(prompt: str) -> dict:
    """从 `_judge_material` 渲染出的那条 user 消息里把材料 JSON 读回来。"""
    text = str(prompt or "")
    start, end = text.find("{"), text.rfind("}")
    assert start >= 0 and end > start, f"材料里没有 JSON：{text[:200]!r}"
    return json.loads(text[start:end + 1])


class _FakeSeam:
    """假秘书的模型缝（只实现 `Secretary.judge` 用到的 `ask_json`）。"""

    class _Call:
        def __init__(self, ok: bool = True, problem: str = "", detail: str = ""):
            self.ok, self.problem, self.detail = ok, problem, detail

    def __init__(self, *, mode: str = "name"):
        #: `name` 按定理名判（默认）；`same` / `different` / `unknown` 是反真空的三根桩；
        #: `off` 复现"缝没查成"（超时那一档）。
        self.mode = str(mode)
        self.calls: list[str] = []

    def ask_json(self, prompt, **kw):
        self.calls.append(str(kw.get("note") or ""))
        if self.mode == "off":
            return None, self._Call(False, "judge_timeout", "打桩：这一趟没查成")
        return self._reply(_material(prompt)), self._Call()

    def _reply(self, data: dict) -> dict:
        label = str(data.get("label") or "")
        candidates = [c for c in (data.get("candidates") or []) if isinstance(c, dict)]
        name = _clean_name(label)
        route = _route(label)
        if self.mode in ("same", "different", "unknown"):
            # 反真空的三根桩：恒判同一个 / 恒判不同 / 恒判不了。
            word = self.mode
            same_as = str(candidates[0]["stmt_id"]) if candidates else ""
            return {"decision": word, "same_as": same_as if word == "same" else "",
                    "canonical_name": name, "route": route,
                    "condition": "打桩：条件未读", "conclusion": "打桩：结论未读",
                    "reason": f"打桩：恒判 {word}", "basis": [f"打桩：{word}"]}
        if not name:
            return {"decision": "unknown", "canonical_name": "", "route": route,
                    "reason": "标签里读不出定理名", "basis": ["条件：标签为空"]}
        hit = next((c for c in candidates
                    if _name_key(str(c.get("label") or "")) == _name_key(name)), None)
        if hit is None:
            return {"decision": "different", "canonical_name": name, "route": route,
                    "condition": f"{name} 的条件组（与在册候选不同）",
                    "conclusion": f"{name} 的结论组（与在册候选不同）",
                    "reason": "候选表里没有同一个定理名", "basis": ["条件：不同名", "结论：不同名"]}
        return {"decision": "same", "same_as": str(hit.get("stmt_id") or ""),
                "canonical_name": name, "route": route,
                "condition": f"条件：都是 {name} 的条件组，一致",
                "conclusion": f"结论：都是 {name} 的结论组，一致",
                "reason": "条件与结论都一致", "basis": ["条件：一致", "结论：一致"]}


def _agent(st: Store, seam: _FakeSeam) -> AgentB:
    """B 的真实现 + 一名"有缝"的秘书（零真实模型调用）。"""
    sec = Secretary("B", root=st.root, store=st, seam=seam, enable_model=True)
    return AgentB(st, extractor=None, extract_text=None, config={}, secretary=sec)


def _register(b: AgentB, full: str, label: str, proof: str) -> dict:
    return b.register_statement(**_own(full, label), proof_text=proof)


def _three_routes(base: pathlib.Path, *, mode: str = "name"):
    """把 sylow4 那三条按三种路线各登记一次 ⇒ `(store, seam, got1, got2, got3)`。"""
    st = _ws(base)
    for lit in (LIT_1, LIT_2, LIT_3):
        _put_lit(st, lit)
    seam = _FakeSeam(mode=mode)
    b = _agent(st, seam)
    got1 = _register(b, FULL_1, LABEL_1, PROOF_1)
    got2 = _register(b, FULL_2, LABEL_2, PROOF_2)
    got3 = _register(b, FULL_3, LABEL_3, PROOF_3)
    return st, seam, got1, got2, got3


def _one_statement_problems(base: pathlib.Path, *, mode: str = "name") -> list[str]:
    """a + b 的读数：一条 `stmt` + 三条证明 + 定理名洗过、路线没丢。

    收在一处是为了让反真空那两条拿同一份读数打红（判据不经两套口径）。
    """
    st, _seam, got1, got2, got3 = _three_routes(base, mode=mode)
    problems: list[str] = []
    for i, got in enumerate((got1, got2, got3), 1):
        if not got.get("ok"):
            problems.append(f"第 {i} 条登记被拒：{got.get('kind')} / {str(got.get('error'))[:120]}")
    rows = _rows(st)
    if len(rows) != 1:
        problems.append(f"同一条定理的三种路线落成了 {len(rows)} 条命题行（应 1 条）")
        return problems
    row = rows[0]
    if _proof_nos(row) != [1, 2, 3]:
        problems.append(f"证明号不是 [1, 2, 3]：{_proof_nos(row)}")
    if VR.proof_text_of(row, 1) != PROOF_1:
        problems.append("canonical 那一格被后来的证明顶掉了")
    if VR.proof_text_of(row, 2) != PROOF_2 or VR.proof_text_of(row, 3) != PROOF_3:
        problems.append("第 2 / 3 份证明的正文不是交来的那一份")
    if str(row.get("label")) != CLEAN_NAME:
        problems.append(f"定理名没洗干净：{row.get('label')!r}（应 {CLEAN_NAME!r}）")
    if re.search(r"路线[一二三]", str(row.get("label") or "")):
        problems.append(f"label 里还带着路线：{row.get('label')!r}")
    routes = SEC.proof_routes_of(row)
    if sorted(routes) != [1, 2, 3]:
        problems.append(f"路线说明没按证明号落全：{routes}")
    else:
        for no, needle in ((1, "类方程"), (2, "McKay"), (3, "Wielandt")):
            if needle not in routes[no]:
                problems.append(f"第 {no} 份证明的路线说明里没有 {needle!r}：{routes[no]!r}")
    if int(got2.get("proof_no") or 0) != 2 or int(got3.get("proof_no") or 0) != 3:
        problems.append(f"第 2 / 3 条没被读成第 2 / 3 份证明："
                        f"{got2.get('proof_no')!r} / {got3.get('proof_no')!r}")
    return problems


def _center_problems(base: pathlib.Path, *, mode: str = "name") -> list[str]:
    """d 的读数：真正不同的两条定理仍然落两条（负控：别把误并当成功）。"""
    st = _ws(base)
    seam = _FakeSeam(mode=mode)
    b = _agent(st, seam)
    got1 = _register(b, FULL_1, "Sylow 定理", PROOF_1)
    got2 = _register(b, FULL_CENTER, "中心引理", PROOF_CENTER)
    problems: list[str] = []
    if not (got1.get("ok") and got2.get("ok")):
        problems.append(f"两条不同的定理有一条没写成：{got1.get('kind')} / {got2.get('kind')}")
        return problems
    rows = _rows(st)
    if len(rows) != 2:
        problems.append(f"两条真正不同的定理落成了 {len(rows)} 条命题行（应 2 条）")
    if got2.get("merged"):
        problems.append(f"中心引理被并进了 Sylow 定理（proof_no={got2.get('proof_no')!r}）")
    if len(rows) == 2 and [str(r.get("label")) for r in rows] != ["Sylow 定理", "中心引理"]:
        problems.append(f"两条的定理名不对：{[r.get('label') for r in rows]}")
    return problems


# ============================================================ a) 路线离开 label，落进证明层

def test_a_the_route_leaves_the_label_and_lands_on_the_proof(tmp_path: pathlib.Path) -> None:
    """a：带「（路线一：…）」的 label 进去之后变成定理名，路线落进第 1 份证明。

    改前红：没有洗名这一步 —— label 原样落盘，于是同一条定理的三种写法永远认不出来
    （真机 sylow4 的三行就是这么来的）。这里同时钉住"洗名不是丢信息"：被洗掉的那段
    路线必须能在证明那一层读回来（`secretary.proof_routes_of`）。
    """
    st = _ws(tmp_path)
    _put_lit(st, LIT_1)
    seam = _FakeSeam()
    got = _register(_agent(st, seam), FULL_1, LABEL_1, PROOF_1)
    assert got.get("ok") is True, got
    assert got.get("merged") is not True, got
    assert got.get("stmt_id") == SID, got
    assert got.get("canonical_name") == CLEAN_NAME, got.get("canonical_name")
    assert got.get("label_washed") == {"from": LABEL_1, "to": CLEAN_NAME}, got.get("label_washed")
    assert "类方程" in str(got.get("proof_route") or ""), got.get("proof_route")
    # 判定读数：三态、判词、是否花钱，三样都在返回值里。
    adj = dict(got.get("adjudication") or {})
    assert adj.get("checked") is True and adj.get("verdict") == "different", adj
    assert adj.get("condition") and adj.get("conclusion"), adj
    assert adj.get("cached") is True and adj.get("reused") is False, adj
    assert len(seam.calls) == 1 and seam.calls[0] == "secretary:proposition_identity", seam.calls

    rows = _rows(st)
    assert len(rows) == 1, rows
    row = rows[0]
    assert str(row.get("label")) == CLEAN_NAME, row.get("label")
    assert "路线" not in str(row.get("label")), "命题的 label 里还留着路线"
    routes = SEC.proof_routes_of(row)
    assert sorted(routes) == [1], routes
    assert "类方程" in routes[1] and "路线一" in routes[1], routes
    assert SEC.proof_route_of(row, 1) == routes[1]
    # 盘上那一次判定也要读得回来（"判过了、判的是不同"不许只活在返回值里）。
    trace = dict(row.get("_proposition_adjudication") or {})
    assert trace.get("verdict") == "different" and trace.get("basis"), trace
    assert trace.get("canonical_name") == CLEAN_NAME, trace


# ============================================================ b) 三种路线 ⇒ 一条 + 三份证明

def test_b_three_routes_become_one_statement_with_three_proofs(
        tmp_path: pathlib.Path) -> None:
    """b：三次不同路线的同一条命题 ⇒ 一条 `stmt` + `proof_no` 1..3。

    夹具就是 sylow4 那三条标签（三种表述不同、同一个定理）。改前红：改前只按
    `statement_full` 的键与词面相似度判（这三种写法 0.35–0.44，抓不到）⇒ 三条命题。
    """
    st, seam, got1, got2, got3 = _three_routes(tmp_path)
    assert got1.get("ok") is True and got1.get("merged") is not True, got1
    for got, no in ((got2, 2), (got3, 3)):
        assert got.get("ok") is True, got
        assert got.get("new_row") is False and got.get("merged") is True, got
        assert int(got.get("proof_no") or 0) == no, got
        assert got.get("matched_by") == SEC.MERGED_BY_ADJUDICATION, got
        assert got.get("stmt_id") == SID, got
        assert "并入已有命题" in str(got.get("note") or ""), got.get("note")
    # 三次判定三次调用（三条正文各不相同 ⇒ 缓存不该命中）；每一次都留了凭据。
    assert len(seam.calls) == 3, seam.calls
    rows = _rows(st)
    assert len(rows) == 1, f"同一条定理的三种路线落成了 {len(rows)} 条命题行"
    row = rows[0]
    assert _proof_nos(row) == [1, 2, 3], _proof_nos(row)
    assert str(row.get("label")) == CLEAN_NAME, row.get("label")
    routes = SEC.proof_routes_of(row)
    assert sorted(routes) == [1, 2, 3], routes
    assert "类方程" in routes[1] and "McKay" in routes[2] and "Wielandt" in routes[3], routes
    # 变体留痕：三种写法各留一条（盘上要读得出"这三种写法被判成了同一条"）。
    matches = [dict(m) for m in (row.get("_proposition_matches") or [])]
    assert len(matches) == 2, matches
    assert [m.get("basis") for m in matches] == [SEC.MERGED_BY_ADJUDICATION] * 2, matches
    assert [int(m.get("proof_no") or 0) for m in matches] == [2, 3], matches
    assert "McKay" in str([m.get("route") for m in matches][0]), matches


def test_b2_the_three_routes_share_one_proof_face_but_do_not_share_dependencies(
        tmp_path: pathlib.Path) -> None:
    """护栏①：三条证明的依赖各落 `#p1/#p2/#p3`（既有机制，不许被这一笔改坏）。"""
    st, _seam, got1, got2, got3 = _three_routes(tmp_path)
    for got in (got1, got2, got3):
        assert got.get("ok") is True, got
    tails = sorted(str(d.get("used_by")) for d in _deps(st))
    assert tails == [f"stmt:{SID}", f"stmt:{SID}#p2", f"stmt:{SID}#p3"], tails
    graph = _DepGraph(stmts=_rows(st), deps=_deps(st), exps=[], lits=[])
    two_d = graph.groups_of(SID)
    assert sorted(two_d) == [1, 2, 3], f"`groups_of` 第一层不是证明号：{sorted(two_d)}"
    labels = {no: [str(d.get("label")) for g in two_d[no].values() for d in g]
              for no in two_d}
    assert labels[1] == ["lit:000009"], labels
    assert labels[2] == ["lit:000008"], labels
    assert labels[3] == ["lit:000007"], labels


def test_b3_one_payload_with_three_proofs_still_lands_path_groups_one_two_three(
        tmp_path: pathlib.Path) -> None:
    """护栏①续：单笔三证明的 `path_group` 仍是 1/2/3（老机制逐字不变）。"""
    st = _ws(tmp_path)
    for lit in (LIT_1, LIT_2, LIT_3):
        _put_lit(st, lit)
    sec = Secretary("B", root=st.root, store=st)
    got = sec.record_statement(
        {**_own(FULL_1, CLEAN_NAME), "proof_text": "",
         "proofs": [{"proof_no": 1, "text": PROOF_1},
                    {"proof_no": 2, "text": PROOF_2},
                    {"proof_no": 3, "text": PROOF_3}]}, role="B")
    assert got.get("checked") is True and got.get("created") is True, got
    deps = _deps(st)
    assert sorted((int(d.get("path_group") or 0)) for d in deps) == [1, 2, 3], deps
    assert sorted(str(d.get("used_by")) for d in deps) == [
        f"stmt:{SID}", f"stmt:{SID}#p2", f"stmt:{SID}#p3"], deps


# ============================================================ c) unknown ⇒ 不并、留 basis

def test_c_unknown_never_merges_and_leaves_its_basis(tmp_path: pathlib.Path) -> None:
    """c：判不了 ⇒ 不并（负控：判不了不许猜），而且凭据留在盘上。

    这一对写法（`FULL_A` / `FULL_A_KEY`）的 `proposition_key` 相同 —— 机械判据会并。
    所以"不并"这句话在这里是有对象的：秘书判 unknown 必须压过机械判据。
    """
    st = _ws(tmp_path)
    seam = _FakeSeam(mode="unknown")
    b = _agent(st, seam)
    first = _register(b, FULL_A, "弦长引理", PROOF_A)
    second = _register(b, FULL_A_KEY, "弦长引理", PROOF_D)
    assert first.get("ok") is True, first
    assert second.get("ok") is True, second
    assert PK.proposition_key(FULL_A) == PK.proposition_key(FULL_A_KEY), (
        "夹具前提：这一对在机械判据下是同一个键（否则 c 不 sharp）")
    rows = _rows(st)
    assert len(rows) == 2, f"判不了却被并进了 {2 - len(rows)} 条（应 2 条独立命题）"
    assert second.get("merged") is not True, second
    assert int(second.get("proof_no") or 1) == 1, second
    adj = dict(second.get("adjudication") or {})
    assert adj.get("checked") is True, "判不了是'查过了'，不是'没查成'（三态不许折平）"
    assert adj.get("verdict") == "unknown", adj
    assert str(adj.get("basis") or "").strip(), "判不了也必须留一句凭据"
    trace = dict(rows[1].get("_proposition_adjudication") or {})
    assert trace.get("verdict") == "unknown" and str(trace.get("basis") or ""), trace
    assert _proof_nos(rows[0]) == [1] and _proof_nos(rows[1]) == [1], (
        [_proof_nos(r) for r in rows])


# ============================================================ d) 缓存：一条正文只判一次

def test_d_the_same_body_is_judged_once(tmp_path: pathlib.Path) -> None:
    """d：同一条正文进来两次 ⇒ 只调用模型一次（按正文 sha256 缓存）。

    改前红：没有这个缓存，每交一次就是一次调用 —— 真机 sylow4 的形态正是"同一条定理
    连交了三遍"，三笔钱买同一句话。第二趟连缝都不该碰（`seam.calls` 停在 1）。
    """
    st = _ws(tmp_path)
    seam = _FakeSeam()
    sec = Secretary("B", root=st.root, store=st, seam=seam, enable_model=True)
    first = sec.record_statement(_own(FULL_1, LABEL_1), role="B")
    assert first.get("checked") is True and first.get("created") is True, first
    assert len(seam.calls) == 1, seam.calls
    # 同一个秘书：第二次判同一段正文 ⇒ 沿用缓存，一次调用都不发。
    again = sec.adjudicate_proposition({"statement_full": FULL_1, "label": LABEL_1,
                                        "kind": "conjecture"})
    assert again.get("reused") is True and again.get("checked") is True, again
    assert again.get("verdict") == "different", again
    assert again.get("cost", {}).get("ledger") == "", again.get("cost")
    assert len(seam.calls) == 1, f"第二次判定又发了调用：{seam.calls}"
    # 换一名秘书（新实例、新缝）⇒ 盘上那份台账仍然让它不花钱。
    seam2 = _FakeSeam()
    sec2 = Secretary("B", root=st.root, store=st, seam=seam2, enable_model=True)
    third = sec2.adjudicate_proposition(FULL_1)
    assert third.get("reused") is True, third
    assert seam2.calls == [], f"新实例仍然发了调用：{seam2.calls}"
    # 台账落盘了，而且只落了一行（缓存不重复记账）。
    ledger = SEC.proposition_verdicts_path(st.root)
    assert ledger.is_file(), ledger
    lines = [line for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1, lines
    row = json.loads(lines[0])
    assert row.get("verdict") == "different", row
    assert row.get("canonical_name") == CLEAN_NAME, row
    assert row.get("route") and "类方程" in row["route"], row
    assert row.get("statement_sha256") == SEC._proposition_verdict_key(FULL_1), row


# ============================================================ e) 反真空

def test_e_stubbing_the_judge_to_same_merges_two_real_theorems(
        tmp_path: pathlib.Path) -> None:
    """e：把判据打桩成恒 same ⇒ 真正不同的两条定理被错并 ⇒ d 的负控必红。

    打桩的是同一处判据（秘书那一次模型调用的结论），不是另写一份假代码：
    `_center_problems` 与 d 的正控用的是同一组读数。
    """
    assert _center_problems(tmp_path / "baseline") == [], "夹具前提：注入之前 d 应当是绿的"
    problems = _center_problems(tmp_path / "always-same", mode="same")
    assert problems, "把判据打桩成恒 same 之后，两条不同的定理仍然分开 ⇒ 那组断言没有对象"
    assert any("落成了 1 条" in p or "被并进" in p for p in problems), problems


def test_e2_stubbing_the_judge_to_different_keeps_three_rows(tmp_path: pathlib.Path) -> None:
    """e：把判据打桩成恒 different ⇒ b 必红（否则"并成一条"可能只是恒真）。"""
    assert _one_statement_problems(tmp_path / "baseline") == [], (
        "夹具前提：注入之前 b 应当是绿的")
    problems = _one_statement_problems(tmp_path / "always-different", mode="different")
    assert problems, "把判据打桩成恒 different 之后 b 仍然全绿 ⇒ 那组断言没有对象"
    assert any("条命题行" in p for p in problems), problems
    assert len(_rows(Store(tmp_path / "always-different" / "ws"))) == 3, (
        "恒 different 之后应当退回改前的形态：三条命题行")


# ============================================================ 改前红

def test_before_this_feature_exists_the_three_rows_come_back(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """改前红：把判定入口打桩成"没查成"（= 改前没有这道判定）⇒ a 与 b 当场变红。

    这不是"另写一份假代码"：`adjudicate_proposition` 就是这一笔新加的判定入口，
    把它退回 `checked=False` 精确等于改前的形态（那时秘书不判同一性）。
    """
    def _no_judge(self, stmt_like, **kw):
        return {"checked": False, "verdict": PK.STATE_UNKNOWN, "canonical_name": "",
                "same_as": "", "route": "", "condition": "", "conclusion": "",
                "basis": "", "reason": "打桩：改前没有这道判定", "label": "",
                "kind": "", "candidates": [], "cost": {"ledger": "", "reason": "没发调用"},
                "reused": False, "cached": False, "statement_sha256": ""}

    monkeypatch.setattr(Secretary, "adjudicate_proposition", _no_judge)
    problems = _one_statement_problems(tmp_path / "before")
    assert problems, "判定入口退回改前，a / b 仍然全绿 ⇒ 这组断言没有钉住新判据"
    assert any("条命题行" in p for p in problems), problems
    rows = _rows(Store(tmp_path / "before" / "ws"))
    assert len(rows) == 3, f"改前的形态应当是三条命题：{len(rows)}"
    assert any("路线" in str(r.get("label") or "") for r in rows), (
        "改前的形态应当是 label 里带着路线")


# ============================================================ 护栏②：没查成退回机械判据

def test_a_missing_model_falls_back_to_the_old_judge_and_still_writes(
        tmp_path: pathlib.Path) -> None:
    """护栏②：缝没查成（超时）⇒ 退回既有机械判据，写入路不瘫。

    这一条守的是"新判据不是单点故障"：模型没接上时，两条表述几乎相同的命题仍然并成
    一条 + 第 2 份证明（老口径），而返回值把这一档如实标成"没查成"（`checked=False`），
    不许冒充"判过了、不同"。
    """
    st = _ws(tmp_path)
    seam = _FakeSeam(mode="off")
    b = _agent(st, seam)
    first = _register(b, FULL_A, "弦长引理", PROOF_A)
    second = _register(b, FULL_A_KEY, "弦长引理", PROOF_D)
    assert first.get("ok") is True, first
    assert second.get("ok") is True, second
    assert second.get("merged") is True and int(second.get("proof_no") or 0) == 2, second
    assert second.get("matched_by") == PK.BASIS_KEY, second
    adj = dict(second.get("adjudication") or {})
    assert adj.get("checked") is False, "没查成不许标成判过了"
    assert str(adj.get("reason") or ""), adj
    assert len(_rows(st)) == 1, _rows(st)
    # 没有缝（默认的 Secretary）也是同一档：不写坏、不冒充。
    sec = Secretary("B", root=st.root, store=st)
    got = sec.record_statement(_own("设 H 是交换群；则 H 的每个子群都正规。", "交换群引理"),
                               role="B")
    assert got.get("checked") is True and got.get("created") is True, got
    assert dict(got.get("adjudication") or {}).get("checked") is False, got.get("adjudication")

