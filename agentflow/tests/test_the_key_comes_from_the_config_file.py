"""判据：「key 从 config 里面接」（所有者 2026-10-10 裁定逐字：

    key 从 config 里面接 / 我是说我们系统的 key 在 config 里面设置的

## 这一批判的是什么

取值梯子是 `环境变量 AGENTFLOW_MODEL_API_KEY > agentflow/settings.json 的
model.api_key > 内置默认（空）`。梯子本身没改（改它会弄坏 CI 与既有脚本）；
这一批补的是来源读数：`ModelSpec.key_source`（`"env"` / `"settings"` / 空串）。

为什么这个读数不是装饰：没有它，"我以为它在 config 里"与"它其实来自一个残留的
环境变量"在其余所有读数上完全一样 —— `configured` 都是 `True`、请求都发得出去。
唯一的区别是来源这一格。少了它，config 写错了也不会有人发现。

判据里的 key 一律是假 key（`sk-...-不许出现`），并且逐字符断言它没进读数。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import modelgw as G
from agentflow import settings as SET
from agentflow.webui import readers as R

SECRET = "sk-假key-绝不许出现在读数里-0123456789"


def _settings_file(tmp_path: pathlib.Path, **model: str) -> pathlib.Path:
    """写一份临时设置文件（只填 `model` 段，其余段缺席 = 用默认值）。"""
    p = tmp_path / "settings-real.json"
    p.write_text(json.dumps({"model": model}, ensure_ascii=False), encoding="utf-8")
    return p


# --------------------------------------------------------------- 正控：从 config 接

def test_the_key_is_read_from_the_settings_file(tmp_path: pathlib.Path) -> None:
    """正控（端到端）：环境里没有 key 时，key 来自设置文件，且来源读数写 `settings`。"""
    p = _settings_file(tmp_path, api_key=SECRET, name="m1")
    spec = G.spec_from_env({SET.ENV_SETTINGS: str(p)})
    assert spec.configured is True, spec.redacted()
    assert spec.api_key == SECRET, "设置文件里的 key 必须真的被读到（否则后面全是假绿）"
    red = spec.redacted()
    assert red["key_source"] == "settings", red
    assert red["api_key"] == "***" and SECRET not in json.dumps(red, ensure_ascii=False), red


def test_the_standalone_source_reading_says_the_same_thing(tmp_path: pathlib.Path) -> None:
    """正控：只问来源的那一口（`modelgw.key_source`）与 spec 上的那一格必须一致。

    它是给机器面用的（只看来源、拿不到 key 本体）—— 两口分叉的话，
    网页上写"从 config 接的"而真跑那一趟从 env 接，正是最难查的那种不一致。
    """
    p = _settings_file(tmp_path, api_key=SECRET)
    env = {SET.ENV_SETTINGS: str(p)}
    assert G.key_source(env) == "settings", G.key_source(env)
    assert G.key_source(env) == G.spec_from_env(env).key_source


# --------------------------------------------------------------- 负控：环境变量不许冒充

def test_a_stale_environment_variable_cannot_masquerade_as_the_config(
        tmp_path: pathlib.Path) -> None:
    """负控：有人 export 过 key ⇒ 来源读数必须变成 `env`（于是"config 没接上"会被看见）。

    这一条正是加 `key_source` 的理由：不说出来的话，config 里写错/没填
    都会被那个环境变量盖住，而台面上一切正常。
    """
    p = _settings_file(tmp_path, api_key=SECRET)
    env = {SET.ENV_SETTINGS: str(p), G.ENV_KEY: "sk-来自环境变量"}
    spec = G.spec_from_env(env)
    assert spec.api_key == "sk-来自环境变量", "环境变量仍然压在最上面（CI 与既有脚本靠它）"
    assert spec.redacted()["key_source"] == "env", spec.redacted()


def test_a_key_that_is_nowhere_is_not_read_as_a_config_key() -> None:
    """负控（三态）：两档都没有 ⇒ `configured=False` 且来源是空串，不是 `settings`。

    注入环境（`env={}`）时按既有口径不读盘（判据与本机解耦，见 `settings.settings_path`）。
    "没配"与"从 config 读到空"必须分得开 —— 折成一个会让"文件不在盘上"看起来像
    "文件里填了空"。
    """
    spec = G.spec_from_env({})
    assert spec.configured is False, spec.redacted()
    assert spec.redacted()["key_source"] == "", spec.redacted()


# --------------------------------------------------------------- 机器面（网页那一格）

def test_the_machine_face_reports_where_the_key_came_from(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控 + 负控（网页那一面）：`machine_face` 报出来源，且 key 本体永不出现在读数里。

    先清掉可能残留的 `AGENTFLOW_MODEL_API_KEY`：否则开发机上跑这一条时，
    来源会随那台机器的环境变 —— 判据必须自己控制这两档。
    """
    monkeypatch.delenv(G.ENV_KEY, raising=False)
    p = _settings_file(tmp_path, api_key=SECRET, base_url="http://127.0.0.1:9", name="m1")
    monkeypatch.setenv(SET.ENV_SETTINGS, str(p))

    face = R.machine_face(tmp_path)
    model = face["settings"]["model"]
    assert model["key_source"] == "settings", model
    assert model["api_key"] == "***" and model["configured"] is True, model
    assert face["settings_tri"] == R.TRI_COMPUTED, face["settings_tri"]
    assert SECRET not in json.dumps(face, ensure_ascii=False), "真 key 出现在读数里了"

    # 负控那半句：同一份设置文件在，只要环境变量被设上，来源那一格就必须翻。
    monkeypatch.setenv(G.ENV_KEY, "sk-来自环境变量")
    shadowed = R.machine_face(tmp_path)["settings"]["model"]
    assert shadowed["key_source"] == "env", shadowed
    assert "sk-来自环境变量" not in json.dumps(shadowed, ensure_ascii=False), shadowed


def test_the_settings_reading_shows_the_effort_that_is_actually_configured(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控 + 负控（设置那一段的读数）：报生效的那一档，词表外的值判 `unreadable`。

    照抄缺省会撒一个谎：文件里写着 `off`（关掉 thinking）而台面上写 `high`。
    这一条走设置段本身（`_settings_reading`）而不是整个 `machine_face`：
    后者会顺带探一遍 Lean（几十秒），而这里要判的东西与工具链无关。
    """
    monkeypatch.delenv(G.ENV_KEY, raising=False)
    p = _settings_file(tmp_path, api_key=SECRET, reasoning_effort="low")
    monkeypatch.setenv(SET.ENV_SETTINGS, str(p))
    reading, tri, reason = R._settings_reading()
    assert tri == R.TRI_COMPUTED and reason == "", (tri, reason)
    assert reading["model"]["reasoning_effort"] == "low", reading["model"]

    # 负控：词表外的值不许静默按缺省显示 —— 这一段判成 unreadable，且原值原样回显。
    bad = _settings_file(tmp_path, api_key=SECRET, reasoning_effort="hgih")
    monkeypatch.setenv(SET.ENV_SETTINGS, str(bad))
    reading, tri, reason = R._settings_reading()
    assert tri == R.TRI_UNREADABLE, (tri, reason)
    assert "reasoning_effort" in reason, reason
    assert reading["model"]["reasoning_effort"] == "hgih", reading["model"]
    assert SECRET not in json.dumps(reading, ensure_ascii=False), "真 key 出现在读数里了"
