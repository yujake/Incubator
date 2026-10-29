# -*- coding: utf-8 -*-
"""采样温度必须是"真发出去的那个请求体"，不许是一条读数里的常量。

## 现场（2026-10-17 长跑预演 → 2026-10-29 业主改口径）

V 的 `verify_proof` 是一次模型调用（`LlmSeam(role="V")`）。同一命题、同一份证明，
实测三次新库得到 `有毛病` / `成立` / `有毛病` —— 判定随采样摆动。

2026-10-17 的处置写在 `modelclient.ModelClient.to_dict()` 里：那一格写着
`"temperature": 0`，本文件当时 grep 的是源码文本里的这八个字符。那是假绿 ——
请求体由 `modelgw.ModelGateway._payload` 组装，用的是 `ModelSpec.temperature`
（缺省 0.2），`to_dict()` 里那个 0 从来没进过网线。于是"采样钉死了"这句话只存在于读数里，
而真正发出去的是 0.2。

2026-10-29 业主改口径：「temperature = 1.0（正常对话的数值）」——只给 V 的审阅调用；
"可复现"这件事改由连续 3 次 + 秘书语义判定承担（`verifications.SIGN_STREAK_NEED`）。

## 判据（全部读真请求体；一条都不读源码文本）

1. 网关发出去的 body 里 `temperature` 等于这一档配置的那个数（缺省 0.2，别的角色不动）；
2. 显式给的温度覆盖配置（`LlmSeam.ask(temperature=…)` 透传进 body）；
3. 读数与 body 同源：`SeamCall.to_dict()["temperature"]` 等于 body 那一格；
   没接线（一个请求都没发）时它是 `None` —— "没查过"不是"0"；
4. `ModelClient.to_dict()` 报的是这一档配置的温度，不是写死的 0；
5. 配置面那一格（`AGENTFLOW_MODEL_TEMPERATURE` > `settings.json` > 缺省）读入即校验：
   区间外/非数当场抛，不许静默按缺省跑。

第 1 条是负控的来源：把 `_payload` 里那一格改回常量、或把 V 的显式温度摘掉，
它会当场红（读数与 body 不再是同一个数）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import llmseam as LS
from agentflow import modelclient as MC
from agentflow import modelgw as G
from agentflow import settings as SET


def _capture(reply_text: str = "{}"):
    """一个把请求体抄下来的 transport（不联网），返回 `(bodies, transport)`。"""
    bodies: list[dict] = []

    def _transport(_url, _headers, data, _timeout):
        bodies.append(json.loads(data.decode("utf-8")))
        return 200, json.dumps({"choices": [{"message": {"content": reply_text}}]},
                               ensure_ascii=False)

    return bodies, _transport


def _gateway(bodies: list[dict], transport, *,
             temperature: float | None = None) -> G.ModelGateway:
    spec = (G.ModelSpec(api_key="k") if temperature is None
            else G.ModelSpec(api_key="k", temperature=temperature))
    return G.ModelGateway(spec, transport=transport, sleep=lambda _s: None,
                          clock=lambda: 0.0)


def test_the_request_body_carries_the_configured_temperature() -> None:
    """正控：body 里的 `temperature` 就是这一档配置的那个数（缺省 0.2）。"""
    bodies, transport = _capture()
    _gateway(bodies, transport).complete("夹具：一次调用", scope="reason")
    assert bodies, "网关一次请求都没发 ⇒ 这一条没测到请求体"
    assert bodies[-1]["temperature"] == G.DEFAULT_TEMPERATURE == 0.2, bodies[-1]
    # 配置面换了值 ⇒ body 跟着换（证明它读的是配置，不是常量）
    bodies2, transport2 = _capture()
    _gateway(bodies2, transport2, temperature=0.7).complete("夹具", scope="reason")
    assert bodies2[-1]["temperature"] == 0.7, bodies2[-1]


def test_the_seam_passes_an_explicit_temperature_through_and_records_it(tmp_path) -> None:
    """透传与读数：显式温度进 body；`SeamCall` 记的是同一个数；没接线时是 None。"""
    bodies, transport = _capture()
    seam = LS.LlmSeam.for_role("F", session_root=tmp_path,
                               gateway=_gateway(bodies, transport))
    call = seam.ask("夹具：显式温度", task_id="t-wire", temperature=0.55)
    assert bodies[-1]["temperature"] == 0.55, bodies[-1]
    assert call.to_dict()["temperature"] == 0.55, call.to_dict()
    # 不显式给 ⇒ 用这一档的配置值，读数与 body 同源（不是各说一个数）
    call2 = seam.ask("夹具：缺省温度", task_id="t-wire")
    assert bodies[-1]["temperature"] == G.DEFAULT_TEMPERATURE, bodies[-1]
    assert call2.to_dict()["temperature"] == bodies[-1]["temperature"], call2.to_dict()
    # 没接线：一个请求都没发 ⇒ temperature=None（"没查过"不是"0"）
    dead = LS.LlmSeam.for_role("F", session_root=tmp_path, from_env=False)
    call3 = dead.ask("夹具：没接线")
    assert call3.requested is False, call3.to_dict()
    assert call3.problem == "judge_not_wired", call3.to_dict()
    assert call3.to_dict()["temperature"] is None, call3.to_dict()


def test_the_model_client_reading_reports_the_live_spec_not_a_dead_constant() -> None:
    """`ModelClient.to_dict()` 那一格必须报这一档配置的温度（改前写死 0，且没进过网线）。"""
    bodies, transport = _capture('{"text": "抽出结果"}')
    client = MC.ModelClient(gateway=_gateway(bodies, transport, temperature=1.0))
    client.complete("夹具：抽取")
    reading = client.to_dict()
    assert bodies[-1]["temperature"] == 1.0, bodies[-1]
    assert reading["temperature"] == bodies[-1]["temperature"], reading
    assert reading["temperature"] != 0, "读数还是那个写死的 0（它与请求体不是同一个数）"


def test_the_temperature_knob_is_validated_and_follows_the_ladder(tmp_path) -> None:
    """配置面：空值=缺省 0.2；区间外/非数当场抛；环境变量压过设置文件。"""
    assert G.normalize_temperature("") == G.DEFAULT_TEMPERATURE == 0.2
    assert G.normalize_temperature(None) == 0.2
    assert G.normalize_temperature("1.0") == 1.0
    assert G.normalize_temperature(1) == 1.0
    for bad in ("abc", "-0.1", "2.5", "nan", "inf"):
        with pytest.raises(ValueError):
            G.normalize_temperature(bad)
    # 设置文件里有这一格 ⇒ 读进来（来源也要报出来）
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"models": {"V": {"temperature": "1.0"}}}), encoding="utf-8")
    spec, where = G.spec_for("V", path=path, env={})
    assert spec.temperature == 1.0 and where == "models.V", (spec.redacted(), where)
    # 环境变量压在最上面
    spec_env, _ = G.spec_for("V", path=path, env={G.ENV_TEMPERATURE: "0.3"})
    assert spec_env.temperature == 0.3, spec_env.redacted()
    # 区间外的值：读进来就抛，不许静默按缺省跑
    badpath = tmp_path / "bad.json"
    badpath.write_text(json.dumps({"model": {"temperature": "9"}}), encoding="utf-8")
    with pytest.raises(ValueError):
        G.spec_for("", path=badpath, env={})
    # 词表那一格只有一个来源：`settings.MODEL_KEYS` 里必须有它（面板按它画输入框）
    assert "temperature" in SET.MODEL_KEYS, SET.MODEL_KEYS
    # `model` 段里这一格没写 ⇒ 空串（"未设置"），按角色的那一档才写着 1.0
    assert SET.model_settings(path=path, env={})["temperature"] == ""
    by_role, where_role = SET.model_settings_for("V", path, env={})
    assert by_role["temperature"] == "1.0" and where_role == "models.V", (by_role, where_role)
