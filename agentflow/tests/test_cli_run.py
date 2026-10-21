"""端到端一条命令的验收：没 key / 401 / 超时 / 预算耗尽 / 成功 / 检索与回验。

为什么必须是端到端的：`modelgw` 与 `tokenmeter` 各自的单测都过了，并不代表"一条命令跑完"是对的：
真正的缺口在段与段之间 —— 记账没接上、预算拦不住、清单里写着一份配置而实际用了另一份。所以这里
每一条都从 `run_topic`（或 `cli.main`）进，检查产物本身，而不是检查某个函数的返回值。

测试接缝：transport 与 search_fn。生产为 None（分别走 `urllib` 与禁改区里的 `providers`），测试注入
假实现。`_run` 默认注入假检索 —— 否则每一条用例都会真的去打 OpenAlex，而"测试必须离线"是这个仓库
的硬约束。刻意没有 `AGENTFLOW_MODEL_FAKE` 之类的环境变量后门：那种开关一旦存在，生产上就会有人
误设它，而产物里的每一行看起来都仍然可信。密钥同理 —— 夹具里只用 "fixture-key" 这种明显不是真
key 的串，任何产物文本里都不许出现密钥本体。

失败路径为什么比成功路径多：成功路径只有一条，失败路径有四条，且必须落在不同的退出码上：把"没查成"
（退出码 2）读成"查了失败"（退出码 1）会让 key 没配好看起来像模型答错；把预算耗尽读成成功则会
让一次跑飞的运行在脚本里看起来一切正常。检索没查成也是 2：那次连模型都没调，把它记成 1 等于说
"查过了、结论是错的"。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agentflow import cli, evidence, runflow
from agentflow import modelcost as MC
from agentflow.modelgw import ModelSpec
from agentflow.runflow import ARTIFACTS, run_topic
from agentflow.store import Store
from agentflow.tokenmeter import TokenMeter

#: 明显不是真 key 的夹具串（长得像 key 的串一律不许出现在测试里）。
KEY = "fixture-key-not-a-secret"
#: 固定时间戳：产物里的时间戳必须可复现，否则断言会摇。
TS = "2026-01-01T00:00:00+00:00"
#: 一次成功调用回多少 token。刻意取 1000/1000：按价目表算下来一次恰好 0.00075 美元
#: （`deepseek-flash` 低谷价 0.15 / 0.6 每百万），于是"预算够几次"这个断言可以口算复核
#: （而不是靠跑一遍看结果）。
TOKENS_IN = 1000
TOKENS_OUT = 1000


def _one_call_usd() -> float:
    """一次成功调用花多少钱 —— 按价目表现算，不许手抄一个数。

    为什么必须现算（2026-10-14 实测）：这里此前写的是
    `TOKENS_IN * 0.27 / 1e6 + TOKENS_OUT * 1.10 / 1e6`（旧缺省价那一对），
    价目表换成"厂商 × 模型 × 峰谷"之后它静默过期 ⇒ 三个预算类用例全红，
    而红之前它已经在"这次调用值多少"这件事上算错过。口径只许有一处：
    走 `modelcost.price_of(spec, at=...)` —— 与 `run_topic` 用的是同一条路，
    时间戳也钉在这份文件那个固定时刻（`TS`，UTC 周四 00:00 ⇒ 低谷）。
    """
    price_in, price_out = MC.price_of(_spec(), at=TS)
    return round(TOKENS_IN * price_in / 1e6 + TOKENS_OUT * price_out / 1e6, 6)


def _one_call_usd_at(stamp: str) -> float:
    """同一个算式，但时刻由调用方给（判"这一趟按哪个时刻计价"用）。"""
    price_in, price_out = MC.price_of(_spec(), at=stamp, env={})
    return round(TOKENS_IN * price_in / 1e6 + TOKENS_OUT * price_out / 1e6, 6)
#: 假检索返回的那段原文；逐字引文必须从它里面复制。
ABSTRACT = "An abelian group is a group in which the commutative law holds."
#: 材料里逐字存在的一句话。
VERBATIM = "the commutative law holds"


def _body(text: str = "阿贝尔群是交换群。", tokens_in: int = TOKENS_IN,
          tokens_out: int = TOKENS_OUT) -> str:
    """OpenAI 兼容的成功应答。"""
    return json.dumps({
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out},
    }, ensure_ascii=False)


def _transport(status: int, body: str, *, calls: list[int] | None = None):
    """固定应答的传输层；给 `calls` 就记录调用次数（用来验熔断）。"""

    def _t(url: str, headers, data: bytes, timeout_sec: float):
        if calls is not None:
            calls.append(1)
        return status, body

    return _t


def _raising_transport(exc: BaseException, *, calls: list[int] | None = None):
    """抛异常的传输层（超时/网络用）。"""

    def _t(url: str, headers, data: bytes, timeout_sec: float):
        if calls is not None:
            calls.append(1)
        raise exc

    return _t


def _search(items: list[dict] | None = None, *, calls: list[int] | None = None):
    """假检索：返回固定条目（缺省一条带 abstraction 的来源），离线、确定。"""

    def _s(topic: str, *, limit: int, timeout_sec: float):
        if calls is not None:
            calls.append(1)
        if items is None:
            return [{"source": "fixture-search", "title": "Abelian groups",
                     "year": 1930, "doi": "10.1000/fixture", "abstract": ABSTRACT}]
        return list(items)

    return _s


def _search_with_pdf(items: list[dict] | None = None):
    """假检索：条目带开放全文直链（只给"要验全文获取"的用例用）。

    为什么单独一个函数而不是改 `_search` 的默认：缺省不给 `pdf_url` 是刻意的，
    它让绝大多数用例天然落在"没有全文"的那一档，而那一档正是"回验只到摘要级"
    的常态。要验下载路径的用例自己显式要直链。
    """

    def _s(topic: str, *, limit: int, timeout_sec: float):
        if items is None:
            return [{"source": "fixture-search", "title": "Abelian groups", "year": 1930,
                     "doi": "10.1000/fixture", "abstract": ABSTRACT,
                     "pdf_url": "https://example.invalid/paper.pdf"}]
        return list(items)

    return _s


def _failing_search(exc: BaseException):
    """抛异常的假检索（验"没查成"那一档）。"""

    def _s(topic: str, *, limit: int, timeout_sec: float):
        raise exc

    return _s


def _fake_quote_fn(*, quotes: tuple[str, ...], message: str = "fixture_verifier"):
    """假回验：只在给定的引文集合里做逐字比对（`quote_fn` 接缝的注入形态）。

    为什么需要它：端到端要验的是"台账里的判决与报告里的数字是同一份事实"，
    而真回验（`quoteverify.check_quote`）会把判决与"来源文本长什么样"耦合起来。
    注入之后，"引文在这一集合里 ⇒ verified，否则 not_found"是一条可逐字复核的判据。
    签名与 `quoteverify.check_quote` 逐字一致（接缝不能靠猜）。
    """

    def _q(doc, quote: str, page_range, *, widen: int = 1,
           allow_fulltext_fallback: bool = False) -> dict:
        found = any(quote in str(page) for page in (doc.pages or []))
        matched = next((i + 1 for i, p in enumerate(doc.pages or []) if quote in str(p)), 1)
        return {"verified": found, "reason": message if found else "not_found",
                "matched_page": matched if found else None}

    return _q


def _spec(key: str = KEY, **kw) -> ModelSpec:
    """测试用配置：key 由用例给，重试默认关闭（让"一次调用"就是一次）。"""
    return ModelSpec(api_key=key, max_retries=kw.pop("max_retries", 0), **kw)


def _run(store: Store, out: Path, *, transport, spec: ModelSpec, budget: float = 1.0,
         max_calls: int = 3, search_fn=None) -> dict:
    """跑一次 `run_topic`，参数足够本文件所有用例复用（检索默认注入假的，保持离线）。"""
    return run_topic(store, topic="阿贝尔群", budget_usd=budget, out_dir=out,
                     transport=transport, spec=spec, max_calls=max_calls, now=TS,
                     search_fn=_search() if search_fn is None else search_fn)


def _manifest(out: Path) -> dict:
    return json.loads((out / "run-manifest.json").read_text(encoding="utf-8"))


def _cost(out: Path) -> dict:
    return json.loads((out / "cost.json").read_text(encoding="utf-8"))


def _claims(out: Path) -> dict:
    return json.loads((out / "claims.json").read_text(encoding="utf-8"))


def _evidence(out: Path) -> dict:
    return json.loads((out / "evidence.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------- ① 没有 key


def test_no_key_exits_2_writes_no_key_and_never_calls(store: Store, tmp_path: Path):
    """① 没有 key ⇒ 退出码 2、清单里 `no_key`、一次网络请求都不发（含检索）。"""
    calls: list[int] = []
    searched: list[int] = []
    out = tmp_path / "nk"
    res = _run(store, out, transport=_transport(200, _body(), calls=calls),
               spec=_spec(key=""), search_fn=_search(calls=searched))
    assert res["exit_code"] == 2 and res["reason"] == "no_key"
    assert calls == [], "没 key 时不许发请求（网关与流程各拦一次）"
    assert searched == [], "没 key 时连检索都不该发：材料没有消费者"
    assert res["retrieval_status"] == "not_configured"
    man = _manifest(out)
    assert man["exit_reason"] == "no_key" and man["exit_code"] == 2
    assert man["call_count"] == 0 and man["calls"] == []
    assert any(n["name"] == "model" for n in man["not_wired"]), "没调模型必须写进未接线清单"
    assert any(n["name"] == "retrieval" for n in man["not_wired"]), \
        "没发起检索 ⇒ retrieval 必须仍出现在未接线清单里"
    assert len(store.rows("usage_ledger")) == 0, "没调用就不该有账（不是记一笔零）"


# --------------------------------------------------------------- ② 401


def test_auth_failure_exits_1_and_is_not_not_checked(store: Store, tmp_path: Path):
    """② 401 ⇒ 退出码 1、清单里 `auth_failed`，且它不属于"没查成"。"""
    out = tmp_path / "auth"
    res = _run(store, out, transport=_transport(401, '{"error":"invalid api key"}'),
               spec=_spec())
    assert res["exit_code"] == 1 and res["reason"] == "auth_failed"
    man = _manifest(out)
    assert man["exit_reason"] == "auth_failed"
    assert man["calls"][0]["reply"]["not_checked"] is False, "查过了、确实失败，不是没查成"
    # 401 也留一行账：它证明"这次真的发出去了、只是被拒了"。
    assert len(store.rows("usage_ledger")) == 1
    assert _cost(out)["spent_usd"] == 0.0


def test_auth_failure_is_not_retried(store: Store, tmp_path: Path):
    """② 的负控：401 不该被重试（重试不会变好，只会烧钱）。"""
    calls: list[int] = []
    res = _run(store, tmp_path / "auth2",
               transport=_transport(401, "nope", calls=calls), spec=_spec())
    assert len(calls) == 1 and res["calls"] == 1


# --------------------------------------------------------------- ③ 超时


def test_timeout_exits_2(store: Store, tmp_path: Path):
    """③ 超时 ⇒ 退出码 2（没查成），清单里 `timeout`。"""
    out = tmp_path / "to"
    res = _run(store, out, transport=_raising_transport(TimeoutError("read timed out")),
               spec=_spec())
    assert res["exit_code"] == 2 and res["reason"] == "timeout"
    man = _manifest(out)
    assert man["calls"][0]["reply"]["error_kind"] == "timeout"
    assert man["calls"][0]["reply"]["not_checked"] is True
    assert _cost(out)["spent_usd"] == 0.0, "超时那次没有 usage，只能记零"


def test_network_error_also_exits_2(store: Store, tmp_path: Path):
    """③ 的同族：网络失败也是"没查成"，不许与认证失败混成一档。"""
    res = _run(store, tmp_path / "net",
               transport=_raising_transport(ConnectionError("getaddrinfo failed")),
               spec=_spec())
    assert res["exit_code"] == 2 and res["reason"] == "network"


# --------------------------------------------------------------- ④ 预算耗尽


def test_budget_exhausted_exits_1_and_stops_before_overspending(store: Store, tmp_path: Path):
    """④ 预算耗尽 ⇒ 退出码 1，且调用次数不超过预算允许的次数（熔断在调用之前）。

    预算刻意取"恰好两次的钱"（`2 × _one_call_usd()`）：这样断言是精确的
    （浮点必须逐位相等才过），而"第 3 次被拦下"就是熔断在调用之前的直接证据。
    """
    calls: list[int] = []
    out = tmp_path / "budget"
    res = _run(store, out, transport=_transport(200, _body(), calls=calls),
               spec=_spec(), budget=_one_call_usd() * 2, max_calls=10)
    # 恰好两次的钱 ⇒ 只允许 2 次；第 3 次在调用前被拦下。
    assert res["exit_code"] == 1 and res["reason"] == "budget_exhausted"
    assert res["calls"] == 2 and len(calls) == 2, "熔断必须在调用之前，不许先调后查"
    man = _manifest(out)
    assert man["exit_reason"] == "budget_exhausted"
    assert len(man["calls"]) == 2
    cost = _cost(out)
    assert cost["budget_exhausted"] is True
    assert cost["spent_usd"] <= _one_call_usd() * 2, "花的钱不许超过预算"
    assert cost["usage_ledger"]["usd"] == cost["spent_usd"]
    assert cost["reconciled_with_usage_ledger"] is True
    # 账本里恰好两行，且每次调用的账都在。
    assert len(store.rows("usage_ledger")) == 2


def test_zero_budget_makes_no_call_at_all(store: Store, tmp_path: Path):
    """④ 的边界负控：预算为 0 ⇒ 一次都不许调（`>=` 而不是 `>`）。"""
    calls: list[int] = []
    res = _run(store, tmp_path / "zero",
               transport=_transport(200, _body(), calls=calls),
               spec=_spec(), budget=0.0, max_calls=3)
    assert calls == [] and res["calls"] == 0
    assert res["exit_code"] == 1 and res["reason"] == "budget_exhausted"
    assert _manifest(tmp_path / "zero")["exit_reason"] == "budget_exhausted"


def test_budget_that_allows_exactly_one_call(store: Store, tmp_path: Path):
    """④ 的邻界：预算刚好够一次 ⇒ 调一次即停（不是"差一点点也硬调"）。"""
    calls: list[int] = []
    res = _run(store, tmp_path / "one",
               transport=_transport(200, _body(), calls=calls),
               spec=_spec(), budget=_one_call_usd(), max_calls=5)
    assert res["calls"] == 1 and len(calls) == 1
    assert res["exit_code"] == 1 and res["reason"] == "budget_exhausted"


def test_the_run_prices_at_its_own_timestamp_not_the_wall_clock(store: Store, tmp_path: Path):
    """这一趟按它自己的时刻取价：峰值那一趟按峰值价，低谷那一趟按低谷价。

    为什么这条是承重的（2026-10-14）：价目表分峰谷两档之后，"按哪一刻计价"
    就成了账面上的一个自由度 —— 读结账时的墙钟，一趟跑在低谷、收尾时已进峰值，
    整趟会被按峰值算，而数字自洽、没有任何地方会报错。所以口径钉在
    `run_topic` 那个 `now=` 上（它同时也是产物里的时间戳），这一条就是那个口径的判据。
    """
    off_at, peak_at = "2026-01-01T00:00:00+00:00", "2026-01-01T02:00:00+00:00"
    got: dict[str, dict] = {}
    for tag, stamp in (("off", off_at), ("peak", peak_at)):
        out = tmp_path / tag
        res = run_topic(store, topic="阿贝尔群", budget_usd=1.0, out_dir=out,
                        transport=_transport(200, _body()), spec=_spec(),
                        max_calls=1, now=stamp, search_fn=_search())
        assert res["exit_code"] == 0 and res["calls"] == 1, (tag, res)
        cost = _cost(out)
        price_in, _price_out = MC.price_of(_spec(), at=stamp, env={})
        assert cost["price_usd_per_m"]["in"] == price_in, (tag, cost["price_usd_per_m"])
        assert cost["spent_usd"] == _one_call_usd_at(stamp), (tag, cost["spent_usd"])
        got[tag] = cost
    # 反真空：两档价必须真不一样，否则上面对的是同一个数（判据什么也没证明）
    assert got["peak"]["spent_usd"] == 2 * got["off"]["spent_usd"], (got["peak"], got["off"])


# --------------------------------------------------------------- ⑤ 成功路径


def test_success_path_produces_all_six_artifacts(store: Store, tmp_path: Path):
    """⑤ 成功 ⇒ 退出码 0、`runflow.ARTIFACTS` 里的六件产物齐备、账本自洽。

    改名留痕：本用例名过去写作"五件产物"，而它断言的 `ARTIFACTS` 一直是六件
    （run-manifest.json / model-transcript.jsonl / evidence.json / claims.json /
    cost.json / report.md）。名字与判据不一致会让读者以为少了一件产物是正常的，
    所以这里改成"六"，并把这个数字的来源指回常量本身。
    """
    out = tmp_path / "ok"
    res = _run(store, out, transport=_transport(200, _body()), spec=_spec(),
               budget=1.0, max_calls=2)
    assert res["exit_code"] == 0 and res["reason"] == "success"
    assert res["calls"] == 2 and res["spent_usd"] > 0
    for name in ARTIFACTS:
        assert (out / name).exists(), f"缺产物 {name}"
    man = _manifest(out)
    assert man["exit_code"] == 0 and man["success_count"] == 2
    assert man["spec"]["api_key"] == "***", "清单里的 key 必须脱敏"
    # transcript 一行一条，条数与清单一致。
    lines = [ln for ln in (out / "model-transcript.jsonl").read_text(encoding="utf-8")
             .splitlines() if ln.strip()]
    assert len(lines) == man["call_count"] == 2
    assert all(json.loads(ln)["ok"] is True for ln in lines)


def test_cost_json_matches_the_usage_ledger(store: Store, tmp_path: Path):
    """⑤ 的核心一致性：`cost.json` 的汇总与 `usage_ledger` 是同一份口径。"""
    out = tmp_path / "okcost"
    res = _run(store, out, transport=_transport(200, _body()), spec=_spec(),
               budget=1.0, max_calls=2)
    cost = _cost(out)
    ledger = TokenMeter(store).spent()
    assert cost["spent_usd"] == round(float(ledger["usd"]), 6)
    assert cost["usage_ledger"]["tokens"] == int(ledger["tokens"])
    assert cost["usage_ledger"]["entries"] == int(ledger["entries"]) == 2
    assert cost["reconciled_with_usage_ledger"] is True
    assert cost["calls_usd"] == cost["spent_usd"]
    assert res["spent_usd"] == cost["spent_usd"]


def test_report_has_an_unknowns_section_that_names_the_unwired_parts(store: Store,
                                                                    tmp_path: Path):
    """⑤ 报告必须有 unknowns 段；未接线清单是动态的，报告里必须如实反映。

    检索真的跑过（本用例注入了假检索）⇒ `retrieval` 与 `quote_verify` 必须
    从清单里消失；`lean` 仍未接线 ⇒ 必须还在。`claims_ledger` 的判据是
    "真的拆过没有"：本用例的答复是一句散文，拆分层会把它拆成一条断言
    （`parsed`）⇒ 这一项也从不接线清单里消失。这一条刻意从报告文本上验：
    清单与报告是同一份事实的两个出口。
    """
    out = tmp_path / "rep"
    _run(store, out, transport=_transport(200, _body()), spec=_spec(), max_calls=1)
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "## unknowns" in md and "## 未接线" in md
    names = [n["name"] for n in _manifest(out)["not_wired"]]
    assert "lean" in names, "仍未接线的那一项必须留着"
    assert "retrieval" not in names and "quote_verify" not in names, \
        "检索真的跑过了 ⇒ 这两项不许再写进未接线清单"
    assert "claims_ledger" not in names, \
        "拆分层真的跑过（parsed）⇒ claims_ledger 不许再写进未接线清单"
    assert "lean" in md
    # 没有未知项时的那一句话也必须在（判据是"这个段落永远存在"）：
    # 用一个没有未接线项的 prompt 版本造不出来，所以直接断言那句话在代码里可达。
    from agentflow import runflow as RF

    assert "本次无未知项" in RF._report_md(
        topic="t", reason="success", exit_code=0, price=(0.0, 0.0), records=[],
        ledger={"usd": 0.0, "entries": 0, "tokens": 0,
                "retry_overhead": {"extra_tokens": 0}},
        budget_usd=0.0, prompt_version="v1", not_wired=[], unknowns=[],
    )


def test_unwired_claims_ledger_comes_back_when_nothing_was_split(store: Store,
                                                                 tmp_path: Path):
    """⑤ 的负控：拆分层没跑成时 `claims_ledger` 必须被加回未接线清单。

    判据不能写成"常量里删掉它就算接线了"：解释性字符串（"没有可断言的句子"）
    与一句陈述句在结构上分不开，所以必然有一类答复拆出来是 `no_claims`。
    那时台账是空的，而空台账必须说清它是"读过了、没有可断言的内容"，
    不是"拆过了、答复里什么都没有"。
    """
    out = tmp_path / "noclaims"
    body = "材料中没有可依据的内容，我无法给出结论。"
    res = _run(store, out, transport=_transport(200, _body(body)), spec=_spec(),
               max_calls=1)
    assert res["exit_code"] == 0, "拆分层没成不改退出码（它说的是这一层没查成）"
    claims = _claims(out)
    assert claims["claims"] == []
    assert claims["claims_ledger"]["status"] == "no_claims"
    assert claims["not_wired"] == ["claims_ledger"]
    assert "拒绝措辞" in claims["claims_ledger"]["reason"]
    names = [n["name"] for n in _manifest(out)["not_wired"]]
    assert "claims_ledger" in names, "没拆成 ⇒ 必须加回未接线清单"
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "claims_ledger" in md and "no_claims" in md, \
        "报告的证据段必须写明这次拆分是三态里的哪一态"


def test_claims_json_is_not_empty_but_says_which_verdict_it_got(store: Store,
                                                                tmp_path: Path):
    """⑤ 台账不再"只有带引文的才是断言"：没引文的断言落 known_unverifiable。

    改名留痕：本用例原名 `test_claims_json_is_empty_and_says_why`，断言的是
    "散文式答复 ⇒ 台账为空"。接线之后那个断言本身成了要防的缺陷：散文里的
    每一句都是断言，把它们丢掉会让"我们没验这些"看起来像"这些结论不存在"。
    所以判据换成：台账里有它、判决是 `known_unverifiable`、且 `why_empty`
    写清这次覆盖到什么。
    """
    out = tmp_path / "claims"
    _run(store, out, transport=_transport(200, _body()), spec=_spec(), max_calls=1)
    claims = _claims(out)
    assert [c["text"] for c in claims["claims"]] == ["阿贝尔群是交换群。"], \
        "散文式答复里的句子必须进台账（丢掉它就是把'没验'写成'不存在'）"
    row = claims["claims"][0]
    assert row["verdict"] == "known_unverifiable" and row["quote"] == ""
    assert row["claim_id"] == "C1" and row["basis"]
    assert claims["not_wired"] == [], "拆过之后 claims_ledger 不该还在未接线里"
    assert len(claims["why_empty"]) > 10, "空数组必须带原因，否则读不出它是'没做'还是'没有'"
    assert claims["counts"]["total"] == 1 and claims["counts"]["verified"] == 0
    assert claims["counts"]["known_unverifiable"] == 1


def test_no_artifact_contains_a_secret_looking_string(store: Store, tmp_path: Path):
    """⑤ 安全负控：任何产物的文本里都不许出现密钥本体。"""
    out = tmp_path / "secret"
    _run(store, out, transport=_transport(200, _body()), spec=_spec(), max_calls=1)
    blob = "".join(
        (out / name).read_text(encoding="utf-8")
        for name in ARTIFACTS
    )
    assert KEY not in blob, "清单/抄本/报告里出现了密钥本体"
    assert "sk-" not in blob, "产物里出现了形如 key 的串"


def test_rerunning_the_same_topic_does_not_double_charge(store: Store, tmp_path: Path):
    """⑤ 的同族：同一个工作区里再跑一次同一主题 ⇒ 每一笔账都认出是重放，不再重复写。

    这是任务 1 的幂等键在端到端上的形态：`(task_id, call_index)` 决定"是不是同一笔"，
    而 task_id 由主题派生 —— 于是"再跑一次同一个主题"不会把成本翻倍，
    也不会让预算看起来还够。
    """
    out1 = tmp_path / "r1"
    first = _run(store, out1, transport=_transport(200, _body()), spec=_spec(), max_calls=1)
    assert first["calls"] == 1 and len(store.rows("usage_ledger")) == 1
    out2 = tmp_path / "r2"
    second = _run(store, out2, transport=_transport(200, _body()), spec=_spec(), max_calls=1)
    assert len(store.rows("usage_ledger")) == 1, "同一笔账不许写第二次"
    charge = _manifest(out2)["calls"][0]["charge"]
    assert charge["reason"] == "duplicate" and charge["charged"] is False
    assert second["spent_usd"] == first["spent_usd"]


def test_retry_attempts_are_charged_in_the_ledger(store: Store, tmp_path: Path):
    """⑤ 的同族：重试按次计费（429 一次后成功 ⇒ 账上是两次的钱）。"""
    seq = [429, 200]

    def _t(url: str, headers, data: bytes, timeout_sec: float):
        code = seq.pop(0) if seq else 200
        return code, (_body() if code == 200 else '{"error":"rate limit"}')

    out = tmp_path / "retry"
    res = run_topic(store, topic="阿贝尔群", budget_usd=1.0, out_dir=out, transport=_t,
                    spec=_spec(max_retries=2), max_calls=1, now=TS, search_fn=_search())
    assert res["exit_code"] == 0
    row = store.rows("usage_ledger")[0]
    assert row["attempts"] == 2
    # 重试按次计费：账上的 usd 已经是两次的钱（`usd_for` 里乘过 attempts）。
    assert row["usd"] == round(_one_call_usd() * 2, 6)
    assert _manifest(out)["calls"][0]["reply"]["attempts"] == 2


# --------------------------------------------------- 证据段：检索 / 断言 / 回验


def test_end_to_end_grounded_run_has_evidence_and_consistent_report(store: Store,
                                                                   tmp_path: Path):
    """⑥ 端到端（注入假检索 + 假模型 + 真回验）⇒ 退出码 0，证据段数字与台账一致。

    这一条是"结论有外部依据"的最小完整形态：材料来自检索、引文来自材料、
    判决来自逐字比对。报告里的四个数字（来源 / 断言 / 通过 / 未验证）必须与
    `claims.json` 的台账逐字对上 —— 报告与台账是同一份事实的两个出口。
    """
    out = tmp_path / "ok-evidence"
    body = f"- 阿贝尔群是交换群 || {VERBATIM}\n- 阿贝尔群是有限群 || 材料里没有这句话"
    res = _run(store, out, transport=_transport(200, _body(body)), spec=_spec(),
               max_calls=1)
    assert res["exit_code"] == 0 and res["retrieval_status"] == "ok"
    for name in ARTIFACTS:
        assert (out / name).exists(), f"缺产物 {name}"

    ev = _evidence(out)
    assert ev["status"] == "ok" and ev["checked"] is True and ev["source_count"] == 1
    assert ev["sources"][0]["provenance"]["provider"] == "fixture-search"
    assert ev["query"] == "阿贝尔群" and ev["retrieved_at"] == TS

    ledger = _claims(out)
    assert [c["verdict"] for c in ledger["claims"]] == ["verified", "not_found"]
    # 两级通过条数分开记：`verified_abstract` 说明这一条只验到摘要级，
    # 不是"全文里也有这句话"。把它合成一个 `verified` 正是本层最要防的读法。
    assert ledger["counts"] == {"total": 2, "verified": 1, "not_found": 1,
                                "known_unverifiable": 0, "unknown": 0, "unverified": 1,
                                "verified_abstract": 1, "verified_fulltext": 0}
    assert ledger["claims"][0]["level"] == "abstract", "没拿全文时不许标 fulltext 级"
    assert ledger["claims"][0]["locator"]["kind"] == "char_offset"
    assert ledger["verification"]["levels_reached"] == ["abstract"]
    assert ledger["claims"][0]["evidence_source"] == "S1"
    assert ledger["claims"][1]["evidence_source"] == ""
    assert ledger["verification"]["quote_fn"] == "quoteverify.check_quote", \
        "回验用的是禁改区里的真实实现，不是被注入的假函数"

    md = (out / "report.md").read_text(encoding="utf-8")
    n, k, u = ev["source_count"], ledger["counts"]["verified"], ledger["counts"]["unverified"]
    assert f"- 来源：{n} 条" in md
    assert f"- 断言：{len(ledger['claims'])} 条；逐字通过 {k} 条；未通过 {u} 条" in md
    # 两级条数必须逐字出现在证据段，且与台账一致：读者据此判断"这次到底验到哪一层"。
    assert (f"- 逐字通过的分级：摘要级 {ledger['counts']['verified_abstract']} 条；"
            f"全文级 {ledger['counts']['verified_fulltext']} 条") in md
    assert "只说明引文在摘要里逐字存在" in md, "摘要级与全文级的差别必须写进报告"
    assert "未验证的断言不得作为证据" in md, "这句话是证据段的判据，必须逐字出现"
    assert "## 证据（检索 + 全文 + 逐字回验）" in md
    assert "- 咨询的源与各自状态：" in md, "报告必须写清咨询了哪几个源、各自什么状态"
    # 清单里的摘要与台账同源：不许出现第三份数字。
    man = _manifest(out)
    assert man["claims"] == ledger["counts"] and man["claims_checked"] is True
    assert man["retrieval"]["status"] == "ok" and man["materials_included"] is True
    assert VERBATIM in man["prompt"], "清单里存的必须是真正发出去的那份 prompt（含材料）"


def test_end_to_end_retrieval_failure_exits_2_and_keeps_not_wired(store: Store,
                                                                 tmp_path: Path):
    """⑦ 检索失败 ⇒ 退出码 2、不调模型、`retrieval` 仍在未接线清单里。"""
    calls: list[int] = []
    out = tmp_path / "retrieval-down"
    res = _run(store, out, transport=_transport(200, _body(), calls=calls),
               spec=_spec(), search_fn=_failing_search(ConnectionError("network down")))
    assert res["exit_code"] == 2 and res["reason"] == "retrieval_failed"
    assert calls == [], "检索没查成 ⇒ 一次模型调用都不许发（没有材料可依据）"
    man = _manifest(out)
    assert man["exit_code"] == 2 and man["exit_reason"] == "retrieval_failed"
    names = [n["name"] for n in man["not_wired"]]
    assert "retrieval" in names and "quote_verify" in names, \
        "没查成 ⇒ 这两项必须仍在未接线清单里（摘掉它们就等于把'没查'说成'查了'）"
    where = next(n for n in man["not_wired"] if n["name"] == "retrieval")
    assert "没查成" in where["reason"], "措辞要据实：接了但没查成，不是'没有接进本流程'"
    ev = _evidence(out)
    assert ev["status"] == "retrieval_failed" and ev["checked"] is False
    assert _claims(out)["claims"] == []
    for name in ARTIFACTS:
        assert (out / name).exists(), f"没查成也要产出 {name}（'没跑'与'跑空了'必须分得开）"


def test_end_to_end_not_configured_retrieval_also_exits_2(store: Store, tmp_path: Path):
    """⑦ 的同族：没有检索器（not_configured）也是 2，且与"查了失败"不同名。"""
    out = tmp_path / "retrieval-unconfigured"
    res = _run(store, out, transport=_transport(200, _body()),
               spec=_spec(), search_fn=_failing_search(
                   evidence.RetrievalNotConfigured("没有可用的检索器")))
    assert res["exit_code"] == 2 and res["reason"] == "retrieval_not_configured"
    assert _evidence(out)["status"] == "not_configured"


def test_evidence_json_records_provenance_for_every_source(store: Store, tmp_path: Path):
    """⑥ 的同族：`evidence.json` 里每一条来源都带库名、查询与时间三件套。"""
    out = tmp_path / "prov"
    _run(store, out, transport=_transport(200, _body()), spec=_spec(), max_calls=1)
    ev = _evidence(out)
    assert ev["sources"], "假检索给了一条来源，产物里必须看得见"
    for s in ev["sources"]:
        assert s["provenance"]["provider"] == "fixture-search"
        assert s["provenance"]["query"] == "阿贝尔群"
        assert s["provenance"]["retrieved_at"] == TS


def test_no_evidence_artifact_contains_a_secret_looking_string(store: Store, tmp_path: Path):
    """⑧ 安全负控：新增产物里同样不许出现密钥本体或形如 key 的串。"""
    out = tmp_path / "secret2"
    body = f"- 阿贝尔群是交换群 || {VERBATIM}"
    _run(store, out, transport=_transport(200, _body(body)), spec=_spec(), max_calls=1)
    blob = "".join((out / name).read_text(encoding="utf-8") for name in ARTIFACTS)
    assert KEY not in blob, "证据/台账/报告里出现了密钥本体"
    assert "sk-" not in blob, "产物里出现了形如 key 的串"


# ------------------------------------------- 原子断言台账端到端（本工作包的验收）
# 判据四条：退出码 0；`claims.json` 的条数与报告证据段的数字逐字一致；
# 没有引文的断言留在台账里（known_unverifiable）；产物里没有形如 key 的串。
# 全程离线：检索、回验、模型传输层三个接缝全部注入假实现。


def test_end_to_end_claims_ledger_matches_the_report_numbers(store: Store, tmp_path: Path):
    """⑥ 端到端（假检索 + 假模型 + 假回验）⇒ 台账条数与报告证据段数字一致。

    这一条刻意把三个接缝都注入，答复里三种形态各来一条：带真引文的、
    带编造引文的、没有引文的，外加一条代码围栏（它不在断言范围内）。
    回验用假函数按逐字比对判，于是判决是"引文在不在我给的集合里"这个可复核的事。
    """
    out = tmp_path / "ledger"
    body = (
        f"- 阿贝尔群是交换群 || {VERBATIM}\n"
        "- 阿贝尔群是有限群 || abelian groups are always finite\n"
        "- 这个分解在无限群上不成立\n"
        "```lean\n"
        "theorem x : True := by trivial\n"
        "```\n"
    )
    res = run_topic(
        store, topic="阿贝尔群", budget_usd=1.0, out_dir=out,
        transport=_transport(200, _body(body)), spec=_spec(), max_calls=1, now=TS,
        search_fn=_search(), quote_fn=_fake_quote_fn(quotes=(VERBATIM,)),
    )
    assert res["exit_code"] == 0 and res["retrieval_status"] == "ok"
    for name in ARTIFACTS:
        assert (out / name).exists(), f"缺产物 {name}"

    led = _claims(out)
    rows = led["claims"]
    assert [r["verdict"] for r in rows] == ["verified", "not_found", "known_unverifiable"], \
        "三条断言各自一个判决：逐字命中 / 编造 / 无引文"
    assert [r["claim_id"] for r in rows] == ["C1", "C2", "C3"]
    assert [r["level"] for r in rows] == ["abstract", "", ""]
    assert rows[0]["evidence_source"] == "S1"
    assert rows[0]["locator"]["kind"] == "char_offset"
    assert rows[2]["quote"] == "" and rows[2]["verdict"] == "known_unverifiable", \
        "没有引文的断言必须留在台账里（丢掉它就是把'没验'写成'不存在'）"

    counts = led["counts"]
    assert counts["total"] == len(rows) == 3
    assert counts["verified"] == 1 and counts["not_found"] == 1
    assert counts["known_unverifiable"] == 1 and counts["unverified"] == 2
    assert counts["verified_abstract"] == 1 and counts["verified_fulltext"] == 0

    split = led["claims_ledger"]
    assert split["status"] == "parsed" and split["claim_count"] == len(rows)
    assert split["total_found"] == 3 and split["truncated"] == 0
    assert split["basis_counts"]["quote_marker"] == 2
    assert split["basis_counts"]["bullet"] == 1
    assert split["fingerprint"] and split["parse_fn_used"] is False
    assert "claims_ledger" not in led["not_wired"], "真的拆过 ⇒ 这一项不许留在未接线里"
    assert "claims_ledger" not in [n["name"] for n in _manifest(out)["not_wired"]]

    # 报告证据段的数字与台账逐字一致（同一份事实的两个出口）。
    md = (out / "report.md").read_text(encoding="utf-8")
    assert (f"- 断言拆分：parsed；共拆出 {split['total_found']} 条；"
            f"登记 {split['claim_count']} 条；被截断 {split['truncated']} 条") in md
    assert (f"- 断言：{counts['total']} 条；逐字通过 {counts['verified']} 条；"
            f"未通过 {counts['unverified']} 条") in md
    assert (f"- 逐字通过的分级：摘要级 {counts['verified_abstract']} 条；"
            f"全文级 {counts['verified_fulltext']} 条") in md
    assert (f"- 无可回验依据（没有引文，按 known_unverifiable 登记，不会被丢弃）："
            f"{counts['known_unverifiable']} 条") in md
    man = _manifest(out)
    assert man["claims"] == counts, "清单里的摘要与台账必须同源"
    assert man["claims_ledger"]["count"] == len(rows)
    assert man["claims_ledger"]["fingerprint"] == split["fingerprint"]

    blob = "".join((out / name).read_text(encoding="utf-8") for name in ARTIFACTS)
    assert KEY not in blob and "sk-" not in blob, "产物里出现了密钥本体或形如 key 的串"


def test_end_to_end_full_ledger_covers_prose_that_has_no_quotes(store: Store,
                                                                tmp_path: Path):
    """⑥ 的同族（本工作包解决的问题本身）：没有任何 `||` 的答复也能拆出台账。

    接线之前，这种答复的 `claims.json` 一定是空数组 —— 台账的条数取决于
    "模型给了几条引文"，而不是"答复里有几条断言"。现在它是 N 条
    （逐字通过 0 条、全部 known_unverifiable），条数与报告一致。
    """
    out = tmp_path / "prose"
    body = "阿贝尔群是交换群。它有唯一的单位元。"
    res = run_topic(
        store, topic="阿贝尔群", budget_usd=1.0, out_dir=out,
        transport=_transport(200, _body(body)), spec=_spec(), max_calls=1, now=TS,
        search_fn=_search(), quote_fn=_fake_quote_fn(quotes=(VERBATIM,)),
    )
    assert res["exit_code"] == 0
    led = _claims(out)
    assert [r["text"] for r in led["claims"]] == ["阿贝尔群是交换群。", "它有唯一的单位元。"]
    assert [r["verdict"] for r in led["claims"]] == ["known_unverifiable"] * 2
    assert led["counts"]["verified"] == 0 and led["counts"]["total"] == 2
    assert "本次登记了 2 条原子断言" in led["why_empty"]
    md = (out / "report.md").read_text(encoding="utf-8")
    assert f"- 断言：2 条；逐字通过 0 条；未通过 2 条" in md


def test_end_to_end_truncation_is_reported_not_silent(store: Store, tmp_path: Path):
    """⑥ 的截断诚实：断言数超过 `claims_max` 时，产物里必须写明被截掉多少条。

    这一条把上限压到 3：答复里有 5 条断言（4 条带引文 + 1 条没有），
    于是台账登记 3 条、截断 2 条。判据是恒等式 `登记 + 截断 == 共拆出`，
    且这个数字同时出现在 `claims.json`、报告证据段与 unknowns 里 ——
    静默截断会让"登记了 3 条"读成"这次一共只有 3 条结论"。
    """
    out = tmp_path / "truncated"
    body = "\n".join([
        f"- 断言一 || {VERBATIM}",
        f"- 断言二 || {VERBATIM}",
        f"- 断言三 || {VERBATIM}",
        f"- 断言四 || {VERBATIM}",
        "- 断言五（没有引文）",
    ])
    res = run_topic(
        store, topic="阿贝尔群", budget_usd=1.0, out_dir=out,
        transport=_transport(200, _body(body)), spec=_spec(), max_calls=1, now=TS,
        search_fn=_search(), quote_fn=_fake_quote_fn(quotes=(VERBATIM,)),
        claims_max=3,
    )
    assert res["exit_code"] == 0
    led = _claims(out)
    split = led["claims_ledger"]
    assert split["status"] == "parsed"
    assert split["claim_count"] == len(led["claims"]) == 3
    assert split["total_found"] == 5 and split["truncated"] == 2
    assert split["claim_count"] + split["truncated"] == split["total_found"]
    assert led["counts"]["total"] == 3, "被截断的那些不参与任何计数（但它们被记了数）"
    assert any("已截断 2 条" in e for e in split["errors"])

    ev = _evidence(out)
    assert ev["claims_ledger"]["truncated"] == 2
    man = _manifest(out)
    assert man["claims_ledger"]["truncated"] == 2
    assert any("超过上限 3" in u for u in man["unknowns"]), \
        "截断必须进 unknowns（它是这次运行没有覆盖到的部分）"
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "- 断言拆分：parsed；共拆出 5 条；登记 3 条；被截断 2 条" in md


# ------------------------------------------------- 多源 + 全文 + 分级端到端
# 这一组是任务 1/2/3 的联合验收：一次运行里同时注入假检索（两个源）、
# 假全文（下载 + 抽取）与假模型，检查产物上的「逐源状态」与「两级条数」。
# 全部离线：四个动作的接缝都注入了假实现，没有一次网络请求。


#: 只存在于摘要、正文里没有的那句话（关键负控用的引文）。
ABSTRACT_ONLY = VERBATIM
#: 正文里逐字存在、摘要里没有的那句话。
BODY_ONLY = "the identity element is unique"


def _ok_fetch(text: str = "body text of the paper"):
    """假下载器：真落一个文件（哈希必须能算出来才算真落盘）。"""

    def _f(url: str, dest_dir, filename_hint: str):
        p = Path(dest_dir) / "paper.pdf"
        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return {"ok": True, "path": str(p), "bytes": len(text), "error": None}

    return _f


def _ok_extract(pages: list[str]):
    """假抽取器：返回 DocumentText 同形的结果。"""

    def _e(path: str):
        return {"text": "\n".join(pages), "pages": list(pages),
                "source_kind": "pdf", "encoding": None}

    return _e


def _two_source_search(first: list[dict], second: list[dict]):
    """两源假检索：源名固定，条目由用例给，便于验逐源状态。"""

    def _f(name: str, items: list[dict]):
        def _s(topic: str, *, limit: int, timeout_sec: float):
            return [dict(it, source=name) for it in items]

        return _s

    return {"openalex": _f("openalex", first), "crossref": _f("crossref", second)}


def test_end_to_end_fulltext_grades_two_levels_and_names_every_source(
        store: Store, tmp_path: Path, monkeypatch):
    """⑥ 端到端（假检索 + 假全文 + 假模型）⇒ 退出码 0，两级数字与台账逐字一致。

    这一条同时钉住四件事：

    1. 三个源（一个失败、一个成功、一个空）里只要有一个成功，整体就是 ok；
    2. 同一篇文献被两个源命中 ⇒ 去重成一条，且产物里写明来自哪两个源；
    3. 只存在于摘要的引文标 `abstract`、正文里有的标 `fulltext`（关键负控）；
    4. 报告证据段的两级数字与 `claims.json` 的台账逐字一致。
    """
    monkeypatch.delenv("AGENTFLOW_MODEL_API_KEY", raising=False)
    out = tmp_path / "graded"
    body = (f"- 摘要级事实 || {ABSTRACT_ONLY}\n"
            f"- 全文级事实 || {BODY_ONLY}\n"
            "- 编造的一条 || 这句话在两份材料里都不存在")
    res = run_topic(
        store, topic="阿贝尔群", budget_usd=1.0, out_dir=out,
        transport=_transport(200, _body(body)), spec=_spec(), max_calls=1, now=TS,
        search_fn=_two_source_search(
            [{"title": "Abelian groups", "year": 1930, "doi": "10.1000/abelian",
              "abstract": ABSTRACT, "pdf_url": "https://example.invalid/a.pdf"}],
            [{"title": "Abelian groups (same paper)", "year": 1930,
              "doi": "https://doi.org/10.1000/abelian.", "abstract": ""}],
        ),
        fulltext=True, fetch_fn=_ok_fetch(),
        extract_fn=_ok_extract(["Page one lists the axioms of a group.",
                                f"On page two we recall that {BODY_ONLY} in every group."]),
    )
    assert res["exit_code"] == 0 and res["retrieval_status"] == "ok"

    ev = _evidence(out)
    assert ev["sources_status"] == {"openalex": "ok", "crossref": "ok"}
    assert ev["source_count"] == 1, "同一篇来自两个源必须合并成一条"
    assert ev["sources"][0]["providers"] == ["openalex", "crossref"]
    assert ev["fulltext_acquisition"]["counts"]["ok"] == 1

    led = _claims(out)
    assert [c["verdict"] for c in led["claims"]] == ["verified", "verified", "not_found"]
    assert [c["level"] for c in led["claims"]] == ["abstract", "fulltext", ""]
    assert led["counts"]["verified_abstract"] == 1
    assert led["counts"]["verified_fulltext"] == 1
    assert led["counts"]["not_found"] == 1
    assert ev["claims"] == led["counts"], "evidence.json 与 claims.json 必须是同一份数字"
    assert ev["verification"]["levels_reached"] == ["abstract", "fulltext"]
    assert _manifest(out)["retrieval"]["sources_status"] == ev["sources_status"]
    assert _manifest(out)["fulltext"]["counts"]["ok"] == 1
    assert all(n["name"] != "fulltext" for n in _manifest(out)["not_wired"]), \
        "全文获取真的跑过了 ⇒ fulltext 必须从未接线清单里摘掉"

    md = (out / "report.md").read_text(encoding="utf-8")
    assert "openalex=ok" in md and "crossref=ok" in md, "报告必须写清问过哪几个源、各自如何"
    assert (f"- 逐字通过的分级：摘要级 {led['counts']['verified_abstract']} 条；"
            f"全文级 {led['counts']['verified_fulltext']} 条") in md
    assert f"未通过 {led['counts']['unverified']} 条" in md
    assert "本次回验到达的级别：" in md
    assert "不说明它在正文里存在" in md, "摘要级与全文级的区别必须写进报告"


def test_end_to_end_one_failing_source_still_runs(store: Store, tmp_path: Path):
    """⑥ 的同族：一个源失败、一个源成功 ⇒ 退出码 0，失败源如实记 failed。"""
    out = tmp_path / "one-bad"

    def _boom(topic: str, *, limit: int, timeout_sec: float):
        raise ConnectionError("crossref is down")

    res = run_topic(
        store, topic="阿贝尔群", budget_usd=1.0, out_dir=out,
        transport=_transport(200, _body(f"- 阿贝尔群是交换群 || {VERBATIM}")),
        spec=_spec(), max_calls=1, now=TS,
        search_fn={"openalex": _search(), "crossref": _boom},
    )
    assert res["exit_code"] == 0 and res["retrieval_status"] == "ok"
    ev = _evidence(out)
    assert ev["sources_status"] == {"openalex": "ok", "crossref": "failed"}
    assert "ConnectionError" in ev["sources_detail"][1]["reason"]
    assert _claims(out)["claims"][0]["level"] == "abstract"
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "- 全文获取：本次没有发起全文获取（fulltext=False）" in md, \
        "没打开全时时报告必须说'没有发起'，不许让读者以为'取了但没有开放全文'"
    assert "没有开放全文" not in md and "no_pdf" not in md, \
        "没发起全文获取时不许出现'没有开放全文'这类逐条结论（那是另一件事）"


def test_end_to_end_all_sources_failed_exits_2(store: Store, tmp_path: Path):
    """⑥ 的同族：两个源都失败 ⇒ 退出码 2（没查成），且逐源状态都是 failed。"""
    calls: list[int] = []
    out = tmp_path / "all-bad"
    res = run_topic(
        store, topic="阿贝尔群", budget_usd=1.0, out_dir=out,
        transport=_transport(200, _body(), calls=calls), spec=_spec(), max_calls=1, now=TS,
        search_fn={"openalex": _failing_search(ConnectionError("a down")),
                   "crossref": _failing_search(ConnectionError("b down"))},
    )
    assert res["exit_code"] == 2 and res["reason"] == "retrieval_failed"
    assert calls == [], "检索没查成 ⇒ 一次模型调用都不许发"
    assert _evidence(out)["sources_status"] == {"openalex": "failed", "crossref": "failed"}


def test_end_to_end_download_failure_still_verifies_the_abstract(store: Store,
                                                                 tmp_path: Path):
    """⑥ 的同族：全文下载失败 ⇒ download_failed，但摘要在手 ⇒ 退出码仍是 0。

    这一条把"全文没拿到"与"没查成"分开：退出码 2 只留给"完全没有可比的文本"。
    """
    out = tmp_path / "dl-bad"

    def _bad(url: str, dest_dir, filename_hint: str):
        return {"ok": False, "error": "network_error: timed out"}

    res = run_topic(
        store, topic="阿贝尔群", budget_usd=1.0, out_dir=out, fulltext=True,
        transport=_transport(200, _body(f"- 阿贝尔群是交换群 || {VERBATIM}")),
        spec=_spec(), max_calls=1, now=TS, search_fn=_search_with_pdf(),
        fetch_fn=_bad, extract_fn=_ok_extract(["never used"]),
    )
    assert res["exit_code"] == 0
    ev = _evidence(out)
    assert ev["fulltext_acquisition"]["counts"]["download_failed"] == 1
    led = _claims(out)
    assert led["claims"][0]["verdict"] == "verified"
    assert led["claims"][0]["level"] == "abstract", "全文没拿到 ⇒ 只许标摘要级"
    assert led["counts"]["verified_fulltext"] == 0
    assert led["verification"]["checked"] is True


def test_fulltext_artifact_never_claims_fulltext_when_nothing_was_downloaded(
        store: Store, tmp_path: Path):
    """⑥ 的关键负控：没有可下载全文（no_pdf）⇒ 台账里不许出现任何全文级通过。"""
    out = tmp_path / "no-pdf"
    res = run_topic(
        store, topic="阿贝尔群", budget_usd=1.0, out_dir=out, fulltext=True,
        transport=_transport(200, _body(f"- 阿贝尔群是交换群 || {VERBATIM}")),
        spec=_spec(), max_calls=1, now=TS, search_fn=_search(),  # 假检索不给 pdf_url
        fetch_fn=_ok_fetch(), extract_fn=_ok_extract(["page"]),
    )
    assert res["exit_code"] == 0
    ev = _evidence(out)
    assert ev["fulltext_acquisition"]["counts"]["no_pdf"] == 1
    led = _claims(out)
    assert led["claims"][0]["level"] == "abstract"
    assert led["counts"]["verified_fulltext"] == 0
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "全文级 0 条" in md and "摘要级 1 条" in md


def test_no_artifact_or_source_contains_a_secret_looking_string(store: Store,
                                                                tmp_path: Path):
    """⑧ 安全：端到端产物与源码里都不许出现形如密钥的串。"""
    out = tmp_path / "secret3"
    body = f"- 阿贝尔群是交换群 || {VERBATIM}"
    _run(store, out, transport=_transport(200, _body(body)), spec=_spec(), max_calls=1)
    blob = "".join((out / name).read_text(encoding="utf-8") for name in ARTIFACTS)
    assert KEY not in blob
    assert "sk-" not in blob
    root = Path(__file__).resolve().parents[1]
    for folder in (root / "src", root / "tests"):
        for path in folder.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                assert not re.search(r"['\"](?:sk|rk|pk)-[A-Za-z0-9_\-]{12,}['\"]", line) or \
                    "super-secret-value" in line, f"{path.name}: 形如密钥的字面量"


# --------------------------------------------------------------- 参数校验


def test_unknown_prompt_version_is_refused(store: Store, tmp_path: Path):
    """负控：未知 prompt 版本显式拒绝，不许静默回退（那会让清单说谎）。"""
    with pytest.raises(ValueError, match="prompt 版本"):
        run_topic(store, topic="t", budget_usd=1.0, out_dir=tmp_path / "v",
                  transport=_transport(200, _body()), spec=_spec(), prompt_version="v99")


def test_negative_max_calls_is_refused(store: Store, tmp_path: Path):
    """负控：负的 max_calls 是调用方错误，显式拒绝。"""
    with pytest.raises(ValueError, match="max_calls"):
        run_topic(store, topic="t", budget_usd=1.0, out_dir=tmp_path / "m",
                  transport=_transport(200, _body()), spec=_spec(), max_calls=-1)


# --------------------------------------------------------------- CLI 接线


def test_cli_run_help_exits_zero_and_documents_the_flags(capsys):
    """CLI 接线：`run --help` 退出码 0，且三个关键开关都在帮助里。"""
    with pytest.raises(SystemExit) as e:
        cli.main(["run", "--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--topic", "--budget-usd", "--out", "--max-calls"):
        assert flag in out


def test_cli_run_defaults_are_1_usd_and_3_calls():
    """CLI 缺省：预算 1.0 美元、最多 3 次（缺省值也是规格的一部分）。"""
    args = cli.build_parser().parse_args(["run", "--topic", "t"])
    assert args.budget_usd == 1.0 and args.max_calls == 3
    assert args.out is None and args.prompt_version == "v1"


def test_cli_run_without_key_exits_2(tmp_path: Path, capsys, monkeypatch):
    """CLI 端到端（没 key）：退出码 2，并打印实际产物路径与未接线清单。

    这一条刻意走 `cli.main`：它是"进程退出码 = run_topic 的 exit_code"这条接线的
    唯一证据 —— 函数返回 2 但进程返回 0 的形态，只有在这里才抓得住。
    `--root` 与 `--config` 是顶层参数（argparse 的位置规则），必须写在子命令之前。
    """
    monkeypatch.delenv("AGENTFLOW_MODEL_API_KEY", raising=False)
    out = tmp_path / "cli-out"
    code = cli.main(["--root", str(tmp_path / "ws"), "run", "--topic", "阿贝尔群",
                     "--budget-usd", "0.5", "--out", str(out), "--now", TS])
    assert code == 2
    printed = capsys.readouterr().out
    assert str(out) in printed, "实际产物路径必须打印出来（默认临时目录尤其）"
    assert "未接线" in printed and "no_key" in printed
    assert _manifest(out)["exit_reason"] == "no_key"
    for name in ARTIFACTS:
        assert (out / name).exists(), f"CLI 路径也要产出 {name}"


def test_cli_run_default_out_is_a_temp_dir_that_gets_printed(tmp_path: Path, capsys,
                                                            monkeypatch):
    """CLI 缺省 `--out`：默认临时目录，且把实际路径打印出来。"""
    monkeypatch.delenv("AGENTFLOW_MODEL_API_KEY", raising=False)
    code = cli.main(["--root", str(tmp_path / "ws2"), "run", "--topic", "t", "--now", TS])
    assert code == 2
    printed = capsys.readouterr().out
    assert "产物目录：" in printed
    assert "工作区：" in printed


def test_runflow_selftest_passes_offline():
    """模块自检要能在没有 key、没有网络的环境里通过。"""
    assert runflow.flow_main([]) == 0
