"""判据：缺省模型是 `deepseek-flash`（S-I / 裁定 19乙），且这次换模型在读数上留了痕。

## 三条判据（施工单 §9 的判据①③ + 一条"别伪造读数"的反真空）

1. 正控（缺省真的换了）：`modelgw.DEFAULT_MODEL` 是 flash，而且没有配置时走出来的
   就是它（`spec_from_env({})` 与设置文件 `name` 留空那两条路都要给同一个答案 ——
   只改常量而某条路仍写着旧名字，是这一批最可能的错法）。
2. 反真空（规范面与历史面分开）：写着"缺省"的地方必须是 flash；而
   `deepseek-chat` 只允许出现在标了历史读数的那几行（把旧的实测改写成新模型名
   是伪造读数 —— 那些数是在 chat 上取的）。
3. 三态（端点清单读不到 ≠ 模型不存在）：`list_models` 在没 key / 非 200 / 空清单时
   一律 `checked=False`（离线判据守的就是这一档 —— "没查成"绝不许折成"不在清单里"）。

联网那两条（端点真的含它、裸调真的会想）在
`tests/test_the_new_model_is_reachable_online.py` 里（`-m network` 显式开启）。
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from agentflow import modelgw as MG
from agentflow import settings as ST

SRC = pathlib.Path(MG.__file__).resolve().parent.parent.parent      # agentflow/
#: 标了"这是历史读数"的词（`deepseek-chat` 只许出现在带这些词的同一行/同一段里）。
HISTORY_MARKERS = ("历史", "真机", "读数", "对照", "裁定 19乙")


def test_the_default_model_is_deepseek_flash() -> None:
    """正控：常量与两条取值路都要给 flash（改一处漏一处是这一批最可能的错法）。"""
    assert MG.DEFAULT_MODEL == "deepseek-flash", MG.DEFAULT_MODEL
    # ① 环境变量一条都没给 ⇒ 缺省那一条路
    assert MG.spec_from_env({}).model == "deepseek-flash", MG.spec_from_env({}).model
    # ② 设置文件里 `model.name` 留空 ⇒ 也必须是它（这条路上游是 `settings`）
    got = ST.load_settings(path=_write_settings(tmp_path_settings(), name=""), env={})
    assert (got.get("model") or {}).get("name", "") == "", got
    # ③ 显式给了名字 ⇒ 尊重配置（内置默认不许盖掉本机设置）
    named = ST.load_settings(path=_write_settings(tmp_path_settings(), name="deepseek-chat"),
                             env={})
    assert (named.get("model") or {}).get("name") == "deepseek-chat", named


def tmp_path_settings() -> str:
    """一个空设置文件（只为让 `load_settings` 有东西可读）。"""
    import tempfile

    path = pathlib.Path(tempfile.mkdtemp()) / "settings.json"
    path.write_text(json.dumps({"model": {"name": ""}}), encoding="utf-8")
    return str(path)


def _write_settings(path: str, *, name: str) -> str:
    body = {"model": {"name": name}}
    if not name:
        body["model"] = {}
    pathlib.Path(path).write_text(json.dumps(body), encoding="utf-8")
    return path


def test_the_normative_text_says_flash_and_history_stays_chat() -> None:
    """反真空：规范面（写着"缺省"的地方）必须是 flash；`deepseek-chat` 只许留在历史读数行。

    两半一起判的理由：只判前半 ⇒ 有人可以把旧读数整段改写成 flash（那是最省事的"过"法）；
    只判后半 ⇒ 缺省那几行可以继续写着旧名字而没人发现。
    """
    sample = (SRC / "settings.example.json").read_text(encoding="utf-8")
    assert "deepseek-flash" in sample, "示例设置文件里没写新缺省名"
    assert "deepseek-chat" not in sample, "示例设置文件里还写着旧缺省名"
    settings_doc = (SRC / "src" / "agentflow" / "settings.py").read_text(encoding="utf-8")
    row = [ln for ln in settings_doc.splitlines() if "`model` | `name`" in ln]
    assert row and "deepseek-flash" in row[0], row
    # `deepseek-chat` 的每一处出现必须在带历史标记的那一行里
    for path in sorted((SRC / "src").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if "deepseek-chat" not in line:
                continue
            assert any(m in line for m in HISTORY_MARKERS), (
                f"{path.name}:{i} 里的 `deepseek-chat` 没有标成历史读数：{line.strip()[:80]}")
    # `modelgw` 里那几处是实测读数，必须还在（别为了"过判据"把它们删掉）
    gw_src = (SRC / "src" / "agentflow" / "modelgw.py").read_text(encoding="utf-8")
    assert gw_src.count("deepseek-chat") >= 4, "历史读数被删了？那些数是 chat 上取的，别删"


def test_the_endpoint_list_is_three_valued() -> None:
    """三态：清单读不到（没 key / 非 200 / 空清单）⇒ `checked=False`，绝不折成"不存在"。"""
    assert MG.list_models(MG.ModelSpec(api_key=""))["checked"] is False
    assert "没配 key" in MG.list_models(MG.ModelSpec(api_key=""))["reason"]

    def fake(status: int, body: str):
        """GET 那一口的替身：`(url, headers, timeout) -> (status, text)`。"""
        return lambda url, headers, timeout: (status, body)

    spec = MG.ModelSpec(api_key="k")
    ok = MG.list_models(spec, get=fake(200, '{"data":[{"id":"deepseek-flash"}]}'))
    assert ok["checked"] is True and ok["models"] == ["deepseek-flash"], ok
    # `{}`（没有 data 键）与 `{"data":[]}` 都是"没读到任何模型名" ⇒ 同一档"空清单"；
    # 只有"整个 body 不是 JSON"才落"形状不对"那一档（两档分开写，判据才有分辨率）。
    for status, body, needle in ((404, "nope", "HTTP 404"),
                                 (200, "{}", "空清单"),
                                 (200, '{"data":[]}', "空清单"),
                                 (200, "不是 JSON", "形状")):
        got = MG.list_models(spec, get=fake(status, body))
        assert got["checked"] is False and needle in got["reason"], (status, body, got)
    # 网络异常也是"没查成"（不是"没有这个模型"）
    def boom(url, headers, timeout):
        raise OSError("网线被拔了")

    assert MG.list_models(spec, get=boom)["checked"] is False
    assert "没读成" in MG.list_models(spec, get=boom)["reason"]


def test_the_model_name_reaches_the_readings() -> None:
    """正控（读数面）：模型名进得了审计记录（换模型之后"这一趟是谁跑的"要查得到）。"""
    spec = MG.ModelSpec(api_key="k")
    assert spec.redacted()["model"] == "deepseek-flash", spec.redacted()
    # 不传 `model` ⇒ dataclass 的默认值就是新缺省（`spec_from_env` 那条路另判了"空串回落"）
    assert MG.ModelSpec(api_key="k").redacted()["model"] == "deepseek-flash"
    assert MG.spec_from_env({"AGENTFLOW_MODEL_NAME": ""}).model == "deepseek-flash"
    # 词表里没有"deepseek-flash"这种拼写检查：名字是自由字符串（模型会换代），
    # 但强度词表是封闭的 —— 这两件事刻意不同（一个会变、一个是协议）。
    with pytest.raises(ValueError, match="reasoning_effort"):
        MG.ModelSpec(api_key="k", reasoning_effort="fast")
    assert re.fullmatch(r"deepseek-[a-z]+", MG.DEFAULT_MODEL), MG.DEFAULT_MODEL
