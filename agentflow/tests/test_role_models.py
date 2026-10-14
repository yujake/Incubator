# -*- coding: utf-8 -*-
"""按角色用不同厂商的 key + 秘书另共用一把（业主 2026-10-14）。

原话：「允许不同角色智能体用不同模型厂商的不同 api key（所有智能体的秘书另外共用一个
api key）」。

## 这一组要钉住的三件事

1. **梯子**：`models.<角色>` → `models.default` → `model` 段 → 环境变量 → 内置缺省。
   逐键取（不是整段覆盖）—— "只给 A 换一把 key"是最常见的写法，整段覆盖会把
   `base_url`/`name` 一起清空，症状是"A 那一路突然按缺省端点跑"，且不报错。
2. **秘书那把 key 真的被用上**：进了 `secretary` 档就换缝（`secretary:<本体角色>`），
   没进就退回本体的缝；两条路都有读数（`Secretary.model_source`）。
3. **key 只写不读**：`models` 的**每一个槽**、`secretary` 那一档都只回显掩码 ——
   漏掩一个槽就等于把那把 key 回显出来了。
"""

from __future__ import annotations

import json
import pathlib

from agentflow import modelgw as MG
from agentflow import settings as SET


def _write(tmp_path: pathlib.Path, values: dict) -> pathlib.Path:
    p = tmp_path / "settings.json"
    got = SET.write_settings(values, path=p)
    assert got["tri"] == "written", got
    return p


def test_the_chain_is_role_then_default_then_model_section(tmp_path):
    """三个槽各给一格 ⇒ 每一格都按最近的来源取（逐键合并），并报出来源。"""
    p = _write(tmp_path, {
        "model": {"api_key": "k-base", "base_url": "https://base/v1", "name": "m-base"},
        "models": {"default": {"name": "m-default", "base_url": "https://def/v1"},
                   "A": {"vendor": "deepseek", "api_key": "k-A"}},
    })
    a, src_a = SET.model_settings_for("A", path=p)
    assert (a["api_key"], a["name"], a["base_url"], a["vendor"]) == \
        ("k-A", "m-default", "https://def/v1", "deepseek"), a
    assert src_a == "models.A", src_a
    b, src_b = SET.model_settings_for("B", path=p)
    assert (b["api_key"], b["name"], b["base_url"]) == ("k-base", "m-default", "https://def/v1"), b
    assert src_b == "models.default", src_b
    # 只配了 `model` 段的老工作区：来源是 `model`，逐字等于老行为
    p2 = _write(tmp_path / "old", {"model": {"api_key": "k-only"}}) \
        if (tmp_path / "old").mkdir(parents=True, exist_ok=True) is None else None
    c, src_c = SET.model_settings_for("C", path=p2)
    assert c["api_key"] == "k-only" and src_c == "model", (c, src_c)


def test_the_env_var_still_wins_over_every_slot(tmp_path):
    """环境变量压在最上面（CI 与既有脚本不许被这次改动弄坏）。"""
    p = _write(tmp_path, {"models": {"A": {"api_key": "k-A", "name": "m-A"}}})
    spec, where = MG.spec_for("A", path=p, env={"AGENTFLOW_MODEL_API_KEY": "k-env"})
    assert spec.api_key == "k-env", spec.redacted()
    assert spec.model == "m-A", spec.redacted()
    assert where == "models.A", where


def test_vendor_picks_the_endpoint_only_when_base_url_is_missing(tmp_path):
    """`vendor` 只做一件事：`base_url` 没给时按它选端点；给了就以给的那个为准。"""
    p = _write(tmp_path, {"models": {"A": {"vendor": "deepseek", "api_key": "k"}}})
    spec, _ = MG.spec_for("A", path=p)
    assert spec.base_url == MG.VENDOR_BASE_URLS["deepseek"], spec.base_url
    p2 = _write(tmp_path / "two", {"models": {"A": {"vendor": "deepseek", "api_key": "k",
                                                    "base_url": "https://mine/v1/"}}})
    spec2, _ = MG.spec_for("A", path=p2)
    assert spec2.base_url == "https://mine/v1", spec2.base_url


def test_the_secretary_slot_is_shared_by_every_role(tmp_path):
    """秘书那一档**全角色共用**：换一个本体角色，取到的还是同一把 key / 同一个模型。

    这一条是业主那句话的机器形态：秘书的模型配置与本体无关。
    """
    p = _write(tmp_path, {
        "model": {"api_key": "k-body"},
        "models": {"A": {"api_key": "k-A"}},
        "secretary": {"api_key": "k-sec", "name": "m-sec"},
    })
    one, src1 = SET.secretary_settings(path=p)
    assert (one["api_key"], one["name"]) == ("k-sec", "m-sec"), one
    assert src1 == "secretary", src1
    spec_a, _ = MG.spec_for("A", path=p)
    spec_sec, where_sec = MG.spec_for(secretary=True, path=p)
    assert spec_a.api_key == "k-A", spec_a.redacted()
    assert spec_sec.api_key == "k-sec", spec_sec.redacted()
    assert where_sec == "secretary", where_sec


def test_every_slot_masks_its_key_in_the_readback(tmp_path):
    """key 只写不读：`models.<每个槽>` 与 `secretary` 都必须只回显掩码。

    负控形态（改起来一眼能看见）：把 `_masked_model_cell` 的掩码那一行删掉，
    这条断言会当场红 —— 它是"按角色配 key"这件事唯一的安全阀。
    """
    p = tmp_path / "settings.json"
    got = SET.write_settings({
        "model": {"api_key": "k-base"},
        "models": {"A": {"api_key": "k-A"}, "default": {"api_key": "k-D"}},
        "secretary": {"api_key": "k-sec"},
    }, path=p)
    values = got["values"]
    assert values["model"]["api_key"] == SET.MASKED_KEY, values["model"]
    assert values["models"]["A"]["api_key"] == SET.MASKED_KEY, values["models"]
    assert values["models"]["default"]["api_key"] == SET.MASKED_KEY, values["models"]
    assert values["secretary"]["api_key"] == SET.MASKED_KEY, values["secretary"]
    # 盘上是真值（"不回显"不等于"没写"）
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["models"]["A"]["api_key"] == "k-A", on_disk
    assert on_disk["secretary"]["api_key"] == "k-sec", on_disk
    # 非 key 的格子照旧回显
    assert values["models"]["A"]["vendor"] == "" and values["secretary"]["name"] == ""


def test_an_unknown_slot_or_key_is_refused_with_zero_writes(tmp_path):
    """负控：槽/键拼错一律拒，且盘上那份一个字节没动（免得写进没人读的配置）。"""
    p = _write(tmp_path, {"models": {"A": {"api_key": "k-A"}}})
    before = p.read_bytes()
    bad_slot = SET.write_settings({"models": {"Z": {"api_key": "x"}}}, path=p)
    assert bad_slot["tri"] == "refused" and "Z" in bad_slot["reason"], bad_slot
    bad_key = SET.write_settings({"models": {"A": {"apikey": "x"}}}, path=p)
    assert bad_key["tri"] == "refused" and "apikey" in bad_key["reason"], bad_key
    assert p.read_bytes() == before, "被拒的那次写了盘（它必须零写入）"


def test_the_slot_level_merge_keeps_other_slots(tmp_path):
    """槽级合并：改 A 不许动 B 与 `secretary`（整段覆盖会把没提过的角色抹掉）。"""
    p = _write(tmp_path, {"models": {"A": {"api_key": "k-A"}, "B": {"api_key": "k-B"}},
                          "secretary": {"api_key": "k-sec"}})
    SET.write_settings({"models": {"A": {"name": "m-A2"}}}, path=p)
    a, _ = SET.model_settings_for("A", path=p)
    b, _ = SET.model_settings_for("B", path=p)
    sec, _ = SET.secretary_settings(path=p)
    assert (a["api_key"], a["name"]) == ("k-A", "m-A2"), a
    assert b["api_key"] == "k-B", b
    assert sec["api_key"] == "k-sec", sec


def test_the_loop_gives_the_secretary_its_own_seam_when_configured(tmp_path, monkeypatch):
    """端到端（装配那一层）：配了 `secretary` 档 ⇒ 秘书拿到的**是另一把 key** 的缝。

    判据走的是生产路径上的那个装配口 `agent_loop._secretary_seam`
    （`--root`/`AGENTFLOW_SETTINGS` 那一档不另写一份）：把设置文件指到临时文件，
    看它给秘书的是哪个缝、以及那个缝的 `role` 与 key。
    """
    from agentflow import agent_loop as AL

    p = _write(tmp_path, {"model": {"api_key": "k-body"},
                          "secretary": {"api_key": "k-sec", "name": "m-sec"}})
    monkeypatch.setenv(SET.ENV_SETTINGS, str(p))
    body = MG.ModelSpec(api_key="k-body", model="m-body")
    body_seam = MG.ModelGateway(body)
    seam, source = AL._secretary_seam("B", root=tmp_path, seam=type("S", (), {
        "usd_budget": 1.5, "price": None, "meter": None, "budget_of": None,
        "gateway": body_seam})(), sid="t", mg=MG)
    assert seam is not None and seam is not body_seam, source
    spec = seam.gateway.spec
    assert spec.api_key == "k-sec" and spec.model == "m-sec", spec.redacted()
    assert seam.role == "secretary:B", seam.role
    assert seam.usd_budget == 1.5, "预算窗口必须与本体共用同一份（换的只是 key/端点/模型）"
    assert source.startswith("secretary"), source


def test_without_the_secretary_slot_the_secretary_keeps_the_body_seam(tmp_path, monkeypatch):
    """反负控：`secretary` 档没配 ⇒ **退回本体那一个缝**（老行为逐字不变）。"""
    from agentflow import agent_loop as AL

    p = _write(tmp_path, {"model": {"api_key": "k-body"}})
    monkeypatch.setenv(SET.ENV_SETTINGS, str(p))
    body = object()
    seam, source = AL._secretary_seam("A", root=tmp_path, seam=body, sid="t", mg=MG)
    assert seam is body, source
    assert source.startswith("body"), source
