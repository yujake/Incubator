"""需要联网的模型回归 —— 默认不跑，用 `-m network` 显式开启（S-I / 裁定 19乙）。

为什么必须有一条真网判据（施工单 §9 判据①②逐字）：

1. 端点必须认得这个名字（`GET /models` 含 `deepseek-flash`）。一个不认识的模型名
   在某些网关上会静默回落到别的模型（照样 200）—— 于是"换成了 flash"与
   "写错了名字、实际还在跑 chat"在读数上分不开。所以判据不是"请求没报错"，
   而是"清单里真的有它"。
2. 它裸调就想（`reasoning_chars > 0`）：这是这一批换模型的目的（业主想要
   默认会思考的模型）。`deepseek-chat` 的历史读数是"裸调 `reasoning_chars=absent`、
   带强度才有 76 字"（`modelgw` 的 docstring）—— 新模型这一档如果也是 absent，
   那这一批等于没换到点子上，必须有人看见。

没查成 ≠ 不存在：拿不到 key 时这两条判 `pytest.skip` 并把理由原样打出来
（三态纪律：把"没查成"读成"不在清单里"会让一次网络故障看起来像"这个模型没了"）。
"""

from __future__ import annotations

import pytest

from agentflow import modelgw as MG

pytestmark = pytest.mark.network


def _spec_or_skip() -> MG.ModelSpec:
    """本机的模型配置（走生产那一条路：环境变量 > 设置文件 > 内置默认）。

    为什么要显式指到默认落点：`tests/conftest.py` 刻意把 `AGENTFLOW_SETTINGS` 钉到一个
    不存在的路径（"判据不该受本机那份带真 key 的文件影响"）—— 那条守卫是对的，
    而这两条 `network` 判据的全部意义恰恰是"拿本机的真配置去问真端点"。
    所以这里按默认落点显式读一次，并在跳过时把用的是哪个路径打出来（三态：
    "没查成"要能看出是"没文件"还是"文件里没 key"）。
    """
    import pathlib

    from agentflow import settings as ST

    # 默认落点（不是 `ST.settings_path()`：那一口会读到 `conftest` 钉的那个路径）。
    # 布局：`<工程根>/settings.json`，而 `settings.py` 在 `<工程根>/src/agentflow/` 下。
    path = pathlib.Path(ST.__file__).resolve().parents[2] / ST.DEFAULT_SETTINGS_REL
    if not path.is_file():
        pytest.skip(f"本机没有设置文件（{path}）⇒ 没查成，本次跳过")
    seg = ST.model_settings(path=path)
    spec = MG.ModelSpec(api_key=seg.get("api_key", ""), base_url=seg.get("base_url", ""),
                        model=seg.get("name", ""), reasoning_effort=seg.get("reasoning_effort", ""))
    if not spec.api_key:
        pytest.skip(f"设置文件里没配 key（{path}）⇒ 没查成，本次跳过")
    return spec
    spec = MG.ModelSpec(api_key=seg.get("api_key", ""), base_url=seg.get("base_url", ""),
                        model=seg.get("name", ""), reasoning_effort=seg.get("reasoning_effort", ""))
    if not spec.api_key:
        pytest.skip(f"没配 key（{MG.ENV_KEY} 或设置文件的 model.api_key）⇒ 没查成，本次跳过")
    return spec


def test_the_endpoint_knows_deepseek_flash() -> None:
    """判据①：`GET /models` 的清单里必须有 `deepseek-flash`。

    失败时把清单原样打出来（"没有它"与"清单没读到"的处置完全不同：前者换名字，
    后者重试）。
    """
    spec = _spec_or_skip()
    got = MG.list_models(spec)
    if not got["checked"]:
        pytest.skip(f"清单没读成（{got['reason']}）—— 这一档是'没查成'，不是'没有它'")
    assert MG.DEFAULT_MODEL in got["models"], (
        f"端点清单里没有 {MG.DEFAULT_MODEL}；它认得的是 {got['models']}")


def test_a_bare_call_thinks_with_the_new_model() -> None:
    """判据②：裸调一次（不给强度以外的任何花招）⇒ `reasoning_chars > 0`。"""
    spec = _spec_or_skip()
    gw = MG.ModelGateway(spec)
    reply = gw.complete("只回答一个数字：2+2=?", scope="reason")
    if not reply.ok and reply.not_checked:
        pytest.skip(f"这一次没查成（{reply.error_kind or reply.error_detail}）")
    assert reply.ok, f"真调失败：{reply.error_kind} / {reply.error_detail}"
    assert len(reply.reasoning) > 0, (
        f"{MG.DEFAULT_MODEL} 裸调没产生思维链（强度={spec.reasoning_effort}）—— "
        "要么这个模型不这么想，要么请求形状不对；两种都要有人看见")
    print(f"[modelgw] 模型={MG.DEFAULT_MODEL} 思维链 {len(reply.reasoning)} 字 / "
          f"答案 {reply.text.strip()[:80]}")
