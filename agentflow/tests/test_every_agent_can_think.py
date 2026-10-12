"""判据：「所有智能体都要能 thinking，且开默认到 High」（所有者 2026-10-10 裁定）。

## 这一批为什么读"发出去的字节"而不是读配置

改前的缺陷在网线上只有一处证据：`modelgw._payload` 组出来的请求体里没有
`reasoning_effort` 这一栏（全仓 grep `reasoning` 零命中）。因此
"`spec.reasoning_effort == "high"`" 只能证明"想让它开"，只有把
`transport=` 抓到的请求体拆开看，才能证明"真的开了"。每条用例都走后者。

## 真机对照读数（`temp/_thinking_probe.py`，`deepseek-chat`，同一条 prompt）

    裸调                       200 reasoning_chars=absent  tokens_in=13 tokens_out=1
    reasoning_effort=high      200 reasoning_chars=76      tokens_in=39 tokens_out=30
    thinking={type:disabled}   200 reasoning_chars=absent  tokens_in=13 tokens_out=1
    reasoning_effort=medium    200 reasoning_chars=101     tokens_in=39 tokens_out=36

第三行说明 `off` 那条形状端点也认；第四行是这一批里最要紧的一条 ——
端点对词表外的取值不报错（`medium` 照 200 照返回思维链），
所以"拦住拼错的强度"这件事只能由客户端做，判据见
`test_an_effort_outside_the_vocabulary_is_refused_before_any_request`。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import llmseam as LS
from agentflow import modelgw as G
from agentflow import schema as S


def _reply(text: str = "4", reasoning: str = "", tokens_in: int = 11,
           tokens_out: int = 3, finish_reason: str = "stop") -> str:
    """一条 OpenAI 兼容应答；`reasoning` 非空时带上思维链那一栏。"""
    message: dict[str, object] = {"role": "assistant", "content": text}
    if reasoning:
        message["reasoning_content"] = reasoning
    return json.dumps({
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out},
    }, ensure_ascii=False)


def _capture(bodies: list[dict], body: str):
    """把请求体记下来再回固定应答（读"真的发出去了什么"的唯一办法）。"""

    def _t(url: str, headers, data: bytes, timeout_sec: float):
        bodies.append(json.loads(data.decode("utf-8")))
        return 200, body

    return _t


def _gw(bodies: list[dict], body: str = "", **kw) -> G.ModelGateway:
    return G.ModelGateway(G.ModelSpec(api_key="test-key", **kw),
                          transport=_capture(bodies, body or _reply()),
                          sleep=lambda _s: None, clock=lambda: 0.0)


# --------------------------------------------------------------- 默认档：High

def test_the_request_body_carries_high_by_default():
    """正控：什么都不配的时候，请求体里必须有 `reasoning_effort: high`。

    它是"所有智能体"这句话在网线上的形态：没有例外、没有"某些角色不发"。
    """
    bodies: list[dict] = []
    reply = _gw(bodies).complete("1+1=?", scope="reason")
    assert reply.ok, reply.to_dict()
    assert G.DEFAULT_REASONING_EFFORT == "high", "缺省档必须就是 High（裁定逐字）"
    assert bodies[0]["reasoning_effort"] == "high", bodies[0]
    assert "thinking" not in bodies[0], "high 这一档不该同时发 thinking 那一栏"


def test_every_role_asks_with_the_same_thinking_setting(tmp_path: pathlib.Path):
    """正控（逐个角色）：A–H 与主控 M，十条角色路径的请求体上都有那一栏。

    为什么不只判"网关缺省是 high"：角色各自经 `LlmSeam` 走 `ask`，
    中间任何一处（`max_tokens` 那条路、工具面那条路、未来加的第二条装配路）
    都可能另写一份请求体。这一条判的是每个角色那一条路的出口。
    """
    roles = (*S.ROLES, S.CONDUCTOR_ROLE)
    assert len(roles) >= 10, f"角色词表只有 {roles}：判据扫不到全部智能体就是假绿"
    for role in roles:
        bodies: list[dict] = []
        gw = _gw(bodies, _reply("4", reasoning="一加一等于二。"))
        seam = LS.LlmSeam.for_role(role, session_root=tmp_path, gateway=gw)
        call = seam.ask("1+1=?", task_id="t")
        assert bodies, f"{role} 没有发出请求"
        assert bodies[-1].get("reasoning_effort") == "high", (role, bodies[-1])
        assert call.to_dict()["reasoning_effort"] == "high", (role, call.to_dict())
        assert call.to_dict()["reasoning_chars"] == len("一加一等于二。"), (role, call.to_dict())


def test_off_is_serialized_as_thinking_disabled_and_omits_the_effort():
    """正控（`off` 那一档的形状）：发 `thinking: {type: disabled}`，且不发 `reasoning_effort`。

    逐字来自 DSH 的 `dsh-llm-deepseek` README：`off` 不是端点认的强度，
    所以它必须以 `thinking.type` 的形式过线（"对拒绝未知强度取值的网关保持协议拼写有效"）。
    """
    bodies: list[dict] = []
    _gw(bodies, reasoning_effort="off").complete("1+1=?", scope="reason")
    assert bodies[0].get("thinking") == {"type": "disabled"}, bodies[0]
    assert "reasoning_effort" not in bodies[0], bodies[0]


def test_every_effort_in_the_vocabulary_is_accepted_and_one_outside_is_not():
    """正控 + 负控（反真空）：词表里每一档都发得出去；词表外那一档当场被拒。

    只判"high 能过"会留下"词表里其余三档其实没人认"的空白 ——
    所以这里逐档走一遍，并且钉住 `medium` 不在词表里（端点是认它的，
    所以"它在不在词表里"只能由这张表回答）。
    """
    for effort in G.REASONING_EFFORTS:
        bodies: list[dict] = []
        reply = _gw(bodies, reasoning_effort=effort).complete("1+1=?", scope="reason")
        assert reply.ok, (effort, reply.to_dict())
        if effort == "off":
            assert bodies[0]["thinking"] == {"type": "disabled"}, (effort, bodies[0])
        else:
            assert bodies[0]["reasoning_effort"] == effort, (effort, bodies[0])
    assert "medium" not in G.REASONING_EFFORTS, "端点认 medium，所以词表必须显式把它排除在外"


def test_an_effort_outside_the_vocabulary_is_refused_before_any_request():
    """负控：拼错的强度在构造 spec 时就炸，且一次请求都没发出去。

    为什么必须炸而不是回落成缺省（真机读数见模块 docstring 第四行）：
    端点对 `medium` 照 200 照返回思维链 ⇒ 客户端若也静默按缺省跑，
    `settings.json` 里写 `hgih` 与写 `high` 的效果逐位相同，而没有任何读数说得出
    "你那个值没人认"。
    """
    bodies: list[dict] = []
    with pytest.raises(ValueError, match="reasoning_effort"):
        _gw(bodies, reasoning_effort="medium")
    assert bodies == [], "拒绝必须发生在任何网络 I/O 之前"
    with pytest.raises(ValueError, match="reasoning_effort"):
        G.reasoning_body_fields("medium")


def test_the_effort_comes_from_the_same_ladder_as_the_key(tmp_path: pathlib.Path):
    """正控 + 负控（取值梯子）：设置文件能设这一档，环境变量仍然压在最上面。

    改前这一档根本没有取值口（请求体里没有那一栏），所以"所有智能体都按 High"
    这句话当时无从配置也无从推翻；现在它与其他模型配置同一条梯子。
    """
    from agentflow import settings as SET

    p = tmp_path / "settings-real.json"
    p.write_text(json.dumps({"model": {"api_key": "k", "reasoning_effort": "low"}},
                            ensure_ascii=False), encoding="utf-8")
    env = {SET.ENV_SETTINGS: str(p)}
    assert G.spec_from_env(env).reasoning_effort == "low", G.spec_from_env(env).redacted()
    assert G.spec_from_env(env).redacted()["reasoning_effort"] == "low"
    # 负控：环境变量那一档仍然压在上面（CI 与既有脚本靠它）。
    env[G.ENV_EFFORT] = "max"
    assert G.spec_from_env(env).reasoning_effort == "max", G.spec_from_env(env).redacted()
    # 空串 = 未设置（与 `env_or_setting` 的既有口径同）：它不遮住设置文件那一档。
    assert G.spec_from_env({**env, G.ENV_EFFORT: "  "}).reasoning_effort == "low"
    # 两档都空 ⇒ 缺省 High（不是"空档"，也不是"off"）。
    bare = tmp_path / "settings-bare.json"
    bare.write_text(json.dumps({"model": {"api_key": "k"}}), encoding="utf-8")
    assert G.spec_from_env({SET.ENV_SETTINGS: str(bare)}).reasoning_effort == "high"


# --------------------------------------------------------------- 思维链读数

def test_the_reply_keeps_the_thinking_chain_apart_from_the_answer():
    """正控：思维链单独收着，绝不并进答案（并进去下游会把它当正文解析）。"""
    chain = "先想一遍：一加一等于二。"
    bodies: list[dict] = []
    reply = _gw(bodies, _reply("4", reasoning=chain)).complete("1+1=?", scope="reason")
    assert reply.text == "4", reply.text
    assert reply.reasoning == chain, reply.reasoning
    assert chain not in reply.text, "思维链不许出现在答案里"
    assert reply.to_dict()["reasoning_chars"] == len(chain), reply.to_dict()


def test_a_reply_with_thinking_but_no_answer_is_still_not_success():
    """负控：想了却一个字没答 ⇒ 仍然不是成功，但读数要说清"它想了多少字"。

    这一栏的必要性：`content` 被截断（输出上限太小）与"根本没开 thinking"
    是两种不同的病因，折成同一句"空内容"会让排障的人去查错方向。

    批 R62 追加（2026-10-12 真机读数）：还要说清"它是被输出额度截断，
    还是真的没答" —— 严格口径 T1 那 5 次 `ModelReplyNotOk` 就是 `length` 那一档
    （思维链 26215 / 26814 字把 8,192 的输出额度吃满、正文 0 字），
    探针读数见 `temp/_probe_chain.txt`。两种 `finish_reason` 的处方不同
    （抬额度 / 降强度，还是查提示词），所以这里两条都判 —— 只判 `length`
    的话，"这一栏永远等于 length"（读错了）也会绿。
    """
    bodies: list[dict] = []
    reply = _gw(bodies, _reply("", reasoning="想了很多但是没写答案",
                               finish_reason="length")).complete("1+1=?", scope="reason")
    assert reply.ok is False and reply.error_kind == "bad_response", reply.to_dict()
    assert "思维链 10 字" in reply.error_detail, reply.error_detail
    assert "finish_reason=length" in reply.error_detail, reply.error_detail

    # 负控：同一句话在 `stop` 那一档必须长得不一样（否则这一栏等于没读）
    stopped = _gw([], _reply("", reasoning="想了很多但是没写答案")).complete("1+1=?", scope="reason")
    assert "finish_reason=stop" in stopped.error_detail, stopped.error_detail
    assert stopped.error_detail != reply.error_detail


def test_the_session_event_records_both_the_asked_strength_and_the_returned_chain(
        tmp_path: pathlib.Path):
    """正控（审计面）：会话事件里"要求它想多深"与"它想了多少字"两栏都在。

    四种组合各自指向不同的修法（见 `SeamCall.reasoning_effort` 那段 docstring）。
    这里判两条：想了的时候字数 > 0；没想的时候是 0 而不是这一栏不存在 ——
    "读到 0"与"这一栏没有"必须分得开，否则改前的形态（根本没有这一栏）会看起来一样。
    """
    thought: list[dict] = []
    seam = LS.LlmSeam.for_role("F", session_root=tmp_path,
                               gateway=_gw(thought, _reply("4", reasoning="一二三")))
    call = seam.ask("1+1=?", task_id="t")
    got = call.to_dict()
    assert got["reasoning_effort"] == "high" and got["reasoning_chars"] == 3, got

    quiet: list[dict] = []
    seam2 = LS.LlmSeam.for_role("F", session_root=tmp_path, gateway=_gw(quiet, _reply("4")))
    got2 = seam2.ask("1+1=?", task_id="t").to_dict()
    assert "reasoning_chars" in got2 and got2["reasoning_chars"] == 0, got2
    assert got2["reasoning_effort"] == "high", got2
