/*
 * 本机读数（`draft/74 §3.5` 逐行落）。
 *
 * 输入：`api.getMachine()` → `MachineView`（B 线的 `readers.machine_face`：
 * `toolchain.toolchain_report()` 的键 + 设置三段）。SSE：`state`。
 *
 * 三态纪律在这页上有三条硬要求：
 *
 * 1. 检查器那一栏**必须显示"从哪一档找到的"**（`provers.sources`）——
 *    "配了但找不到"与"没配"是两种不同的处置，读数上必须分得开；`checked=false`
 *    ⇒ 整面 `unreadable`（探测没跑完，不是"一个都没找到"）；
 * 2. 模型那一栏**只显"配没配" + `base_url` / `name`；永远没有 key 的值**
 *    （`settings.model.api_key` 恒为 `***`，这是后端 `ModelSpec.redacted()` 给的）；
 * 3. `lean_ready` / `can_do_formal` 与 `provers.checked` 一样是**三态**：
 *    `null` 渲染成 `unknown`，不许折成 `false`。
 *
 * 一处**已经接上的缺口**（2026-10-12 更正）：`draft/74 §3.5` 第 6 行要的
 * "活着的 loop / 进程"此前没有端点，那一栏渲染成 `not_applicable` 并写明；
 * 现在 `GET /api/live`（在飞面）给了它，卡片改成指路「在飞」页 ——
 * 说明文与读数说同一件事，别留一句"没有端点"的旧话在页面上。
 */
import { useState } from "preact/hooks";

import { api, postSettings, whyOf } from "../api";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { ConfirmButton } from "../components/ConfirmButton";
import { Table, cell } from "../components/Table";
import { TriState, isUnreadable } from "../components/TriState";
import { useFace } from "../live";
import type { SettingsReading } from "../types";

/** 设置窗口里的每一格（`段.键` 形状逐字对应后端 `handle_settings` 读的表单键）。 */
const FIELDS: ReadonlyArray<{ key: string; hint: string }> = [
  { key: "toolchain.lean_bin", hint: "Lean 可执行文件所在目录（例：_env/lean470/.../bin）" },
  { key: "toolchain.mathlib_root", hint: "Mathlib 检出的根目录" },
  { key: "toolchain.coq_bin", hint: "Coq 落点（没有就留空）" },
  { key: "toolchain.isabelle_bin", hint: "Isabelle 落点（没有就留空）" },
  { key: "toolchain.lean_enabled", hint: "true / false —— 缺省 false（省钱档）" },
  { key: "model.vendor", hint: "厂商名（留空 = 按 base_url/内置缺省；例：deepseek）" },
  { key: "model.api_key", hint: "只写不读；写进去之后回执里恒为 *" },
  { key: "model.base_url", hint: "留空 = 用内置缺省端点（给了 vendor 就按它选）" },
  { key: "model.name", hint: "留空 = 用内置缺省模型" },
  { key: "model.reasoning_effort", hint: "off / low / high / max" },
  { key: "secretary.api_key", hint: "所有角色的秘书共用这一把 key（留空 = 秘书沿用它本体那一档）" },
  { key: "secretary.vendor", hint: "秘书那一档的厂商（留空 = 跟随 base_url）" },
  { key: "secretary.base_url", hint: "秘书那一档的端点" },
  { key: "secretary.name", hint: "秘书那一档的模型名" },
  { key: "secretary.reasoning_effort", hint: "off / low / high / max" },
  { key: "workspace.projects_dir", hint: "默认项目目录（留空 = 工作区自己那一个）" },
];

/** 十个角色（`schema.ROLES` 的十个字母；`models.<角色>.<键>` 是三段形状）。 */
const ROLES: readonly string[] = ["A", "B", "C", "D", "E", "F", "G", "H", "V", "M"];

/** 按角色那一档要填的键（业主 2026-10-14：「允许不同角色智能体用不同模型厂商的不同 api key」）。
 *
 * 只给"换厂商 / 换端点 / 换模型 / 换 key"四格：逐角色配全套等于让人在十个角色上抄五遍
 * 同一份配置，而梯子（`models.<角色>` → `models.default` → `model`）本来就是为"只改一格"
 * 设计的 —— 留空即沿用下一档。
 */
const ROLE_FIELDS: ReadonlyArray<{ key: string; hint: string }> = [
  { key: "vendor", hint: "厂商名（例：deepseek；留空 = 沿用）" },
  { key: "api_key", hint: "这个角色自己的 key（只写不读；留空 = 沿用）" },
  { key: "base_url", hint: "端点（留空 = 沿用）" },
  { key: "name", hint: "模型名（留空 = 沿用）" },
];

/** 某一档的读数（`settings.models.<角色>`）—— **唯一一处**知道那一档形状的地方。 */
function roleCell(settings: SettingsReading, role: string): Record<string, unknown> {
  const models = (settings as unknown as Record<string, unknown>).models;
  if (models === undefined || models === null || typeof models !== "object") {
    return {};
  }
  const seg = (models as Record<string, unknown>)[role];
  if (seg === undefined || seg === null || typeof seg !== "object") {
    return {};
  }
  return seg as Record<string, unknown>;
}

/** 按角色那一档现读的值（`settings.models.<角色>.<键>`）。 */
function roleValue(settings: SettingsReading, role: string, key: string): string {
  const raw = roleCell(settings, role)[key];
  if (raw === undefined || raw === null) {
    return "";
  }
  return typeof raw === "string" ? raw : String(raw);
}

/** 从 `Record<string, unknown>` 里读一格：读不到 ⇒ `unknown`（不是空串、不是 false）。 */
function field(rec: Record<string, unknown>, key: string): string {
  return cell(rec[key]);
}

/** 设置文件里某一格现在的值（按 `段.键` 取；取不到 ⇒ 空串 = 盘上没设过）。
 *
 * 为什么要它（业主 2026-10-13：「设置面板启动后应该同步设置文件里的参数，不然空空的就像
 * 啥都没设置过一样」）：这一格的读数后端早就在给（`GET /api/machine` 的 `settings` 三段），
 * 但输入框初值一直是空串 ⇒ 打开面板看到的永远是"没配"。
 *
 * ⚠️ 2026-10-13（R90）改一处**要命的**地方：这里不许走 `cell()`。`cell("")` 的口径是
 * `unknown`（那一套是给**读数表**用的），可这一格的返回值会直接进输入框的 `value` ——
 * 于是盘上没写的四格（`coq_bin` / `isabelle_bin` / `lean_enabled` / `projects_dir`）
 * 全被填上了字面量 `unknown`，用户一按「写这些设置」就把 `lean_enabled=unknown` 写进盘上：
 * `settings.lean_enabled()` 对词表外的值**抛错**，开关从此读不出来 ——
 * 业主报的「lean 开关网页上没法真的开关」正是这一条。
 * 所以这里读**原值**：缺席 ⇒ 空串（输入框空着、placeholder 说"盘上没设过"），
 * 「空串 = 这一格不动」这条口径也才成立。
 */
function currentOf(settings: SettingsReading, key: string): string {
  const parts = key.split(".");
  const part = parts[0] ?? "";
  const leaf = parts[1] ?? "";
  const seg = (settings as unknown as Record<string, Record<string, unknown>>)[part];
  if (seg === undefined || seg === null) {
    return "";
  }
  const raw = seg[leaf];
  if (raw === undefined || raw === null) {
    return "";
  }
  return typeof raw === "string" ? raw : String(raw);
}

/** 三态布尔：`null` / `undefined` ⇒ `unknown`（不折成 false）。 */
function triBool(value: unknown): string {
  return typeof value === "boolean" ? String(value) : "unknown";
}

/** 把"键值对"渲染成一张两列的表（设置三段与嵌套读数都用它）。
 *
 * `raw` 是原值：设置三段那一张要按"盘上写没写"读（空串 = 没写），不能在这里先被
 * `cell()` 折成 `unknown` —— 折过之后 `settingsCell()` 拿到的已经是词，回不去了。
 */
function pairs(rec: Record<string, unknown>): Array<{ k: string; v: string; raw: unknown }> {
  return Object.keys(rec)
    .sort()
    .map((k) => ({ k, v: field(rec, k), raw: rec[k] }));
}

/** 设置文件里的一格怎么读（R90）。
 *
 * 为什么不用 `cell()` 的默认读法：它的口径是"空串 ⇒ `unknown`"（三态纪律：读不到 ≠ 空），
 * 可这一格读到的是一个**盘上没写**的键 —— 文件已经读出来了（这一卡只有在
 * `settings_tri` 不是 unreadable 时才渲染）。把"没写"显成 `unknown`，用户看到的就是
 * 「lean_enabled unknown」，像是开关读不出来 —— 业主 2026-10-13 就是这么读的
 * （原话：「lean 开关网页上没法真的开关」）。
 */
function settingsCell(value: unknown): string {
  if (value === "" || value === null || value === undefined) {
    return "（盘上没写）";
  }
  return cell(value);
}

/** 形式化开关的来源（`GET /api/machine` 的 `lean_enabled_source`）。 */
const SWITCH_SOURCES: Record<string, string> = {
  env: "环境变量 AGENTFLOW_LEAN_ENABLED",
  settings: "设置文件 toolchain.lean_enabled",
  "": "缺省（设置文件里没写这一格）",
};

/** 初值：设置文件里的现值；`model.api_key` 例外（读数是 `***`，回填等于写回它）。 */
function presetOf(settings: SettingsReading, key: string): string {
  if (key === "model.api_key") {
    return "";
  }
  return currentOf(settings, key);
}

export function Machine() {
  const face = useFace(() => api.getMachine());
  const [values, setValues] = useState<Record<string, string>>({});
  const [writeResult, setWriteResult] = useState("");
  const [switchResult, setSwitchResult] = useState("");

  if (face.data === null) {
    return (
      <Card
        title="本机"
        tone={face.problem === "" ? "plain" : "problem"}
        right={face.problem === "" ? null : <TriState tri="unreadable" reason={face.problem} label="本机面" />}
      >
        <span class="readings">{face.problem === "" ? "正在读盘……" : face.problem}</span>
      </Card>
    );
  }

  const m = face.data;
  const settings = m.settings;
  const provers = m.provers;
  const mathlib = m.mathlib;
  // 开关的读数（三态）：`null` = 这一格没读成，不许折成"关"。
  const leanOn: boolean | null = typeof m.lean_enabled === "boolean" ? m.lean_enabled : null;

  /** 翻这个开关：写 `toolchain.lean_enabled` 那一格（`postSettings` 自带 `confirm=1`）。 */
  const flipLean = (want: boolean): void => {
    setSwitchResult("");
    postSettings({ "toolchain.lean_enabled": want ? "true" : "false" })
      .then((got) => {
        setSwitchResult(
          `${got.ok ? "成了" : "没成"}（tri=${got.tri}）：${got.reason}` +
            (got.ok ? " —— 新起的循环按新开关走；正在跑的那一趟按它自己那份跑。" : ""));
        face.reload();
      })
      .catch((exc: unknown) => {
        setSwitchResult(`写请求失败：${whyOf(exc)}`);
      });
  };

  return (
    <>
      <Card
        title="本机"
        subtitle={`整面 tri=${m.tri}`}
        tone={isUnreadable(m.tri) ? "problem" : "plain"}
        right={<TriState tri={m.tri} label="本机面" reason={m.reason} />}
      >
        <div class="readings">
          一处定义：工具链在哪、用哪个模型 —— 都来自机器级设置文件（
          <span class="mono">{settings.path === "" ? "unknown（落点没读到）" : settings.path}</span>
          ，在盘上 <span class="mono">{String(settings.exists)}</span>）。
        </div>
      </Card>

      <Card
        title="证明检查器"
        subtitle={`checked=${field(provers, "checked")}`}
        tone={provers.checked === false ? "problem" : "plain"}
      >
        <div class="readings">
          探测结论：<span class="mono">{field(provers, "reason")}</span> · 找到的：
          <span class="mono">{field(provers, "available_names")}</span>
        </div>
        <div class="readings">
          从哪一档找到的（这一栏是"配了找不到"与"没配"的分水岭）：
        </div>
        <Table
          rows={pairs(provers)}
          empty="探测读数里一格都没有（读到了空对象 —— 不是「没查成」）。"
          columns={[
            { key: "k", title: "键" },
            { key: "v", title: "值", render: (r) => <span class="mono">{r.v}</span> },
          ]}
        />
        <div class="readings">
 checked=false ⇒ 上面那些是"探测没跑完"：整面记 unreadable，
          不是"一个检查器都没找到"。
        </div>
      </Card>

      <Card
        title="Lean / Mathlib"
        subtitle={`lean_ready=${triBool(m.lean_ready)} · can_do_formal=${triBool(m.can_do_formal)}`}
      >
        {/* 开关那一行（R90）：业主 2026-10-13「lean 开关网页上没法真的开关」。
            原先这一页只显示 `lean_ready`（这台机器装没装 Lean）与 `can_do_formal`
            （装了能不能用），**不显示 `lean_enabled`（用户设的开关）** —— 于是页面上
            根本看不出开关是开是关，改它只能去下面那个自由文本框里手打 true/false。
            两条事实必须同框（`readers.py` 里写过同一句：只看后者会把"关掉了"读成"没装"）。 */}
        <div class="readings">
          形式化开关{" "}
          <b>{leanOn === null ? "unknown（这一格没查成）" : leanOn ? "开" : "关"}</b>
          {" "}· 来源 <span class="mono">
            {SWITCH_SOURCES[m.lean_enabled_source] ?? m.lean_enabled_source}
          </span>
          {" "}· 当前模式 <span class="mono">{m.formal_mode === "" ? "unknown" : m.formal_mode}</span>
        </div>
        <div class="readings">
          关掉时全员不做形式化：证明核验走 V 的自然语言逐行走查（`verifications` 表签「成立」），
          检查器如实回 `lean_disabled` —— 它不是"这台机器上没有 Lean"，也不是"证明没过"。
          {/* 环境变量压着设置文件时，写文件不生效 —— 这件事必须在页面上说出来，
              否则用户改了设置文件、读数不动，只会以为"这个开关坏了"。 */}
          {m.lean_enabled_source === "env" ? (
            <span class="tri-reason">
              {" "}注意：现在压着它的是环境变量，改设置文件不会改变这一档 ——
              要么去掉那个环境变量再起服务，要么就按它跑。
            </span>
          ) : null}
        </div>
        <div class="readings">
          <ConfirmButton
            action="打开形式化"
            impact="会把设置文件 toolchain.lean_enabled 写成 true（下一趟起按它走）"
            onConfirm={() => {
              flipLean(true);
            }}
            disabled={leanOn !== false}
            note={
              leanOn === null
                ? "开关读数没查成 —— 先解决上面那条 reason，别蒙着写"
                : leanOn
                  ? "已经是开的"
                  : "写面没开（agentflow web --allow-writes）时后端回 403，回执如实显示"
            }
          />
        </div>
        <div class="readings">
          <ConfirmButton
            action="关闭形式化"
            impact="会把设置文件 toolchain.lean_enabled 写成 false（省钱档；证明核验改走 V 逐行走查）"
            onConfirm={() => {
              flipLean(false);
            }}
            disabled={leanOn !== true}
            note={
              leanOn === null
                ? "开关读数没查成 —— 先解决上面那条 reason，别蒙着写"
                : leanOn
                  ? "写面没开（agentflow web --allow-writes）时后端回 403，回执如实显示"
                  : "已经是关的（缺省就是关）"
            }
          />
        </div>
        {switchResult === "" ? null : <div class="readings">{switchResult}</div>}
        <div class="readings">
          lean 落点 <span class="mono">{m.lean_path === "" ? "unknown（没读到）" : m.lean_path}</span> ·
          版本 <span class="mono">{m.lean_version === "" ? "unknown（没读到）" : m.lean_version}</span>
        </div>
        <Table
          rows={pairs(mathlib)}
          empty="Mathlib 读数里一格都没有（读到了空对象）。"
          columns={[
            { key: "k", title: "键" },
            { key: "v", title: "值", render: (r) => <span class="mono">{r.v}</span> },
          ]}
        />
      </Card>

      <Card
        title="模型 key（只显配没配）"
        right={
          <Badge
            kind={settings.model.configured ? "badge-pass" : "badge-na"}
            text={settings.model.configured ? "配了" : "没配"}
          />
        }
      >
        <div class="readings">
          vendor <span class="mono">{settings.model.vendor === "" ? "unknown（没配）" : settings.model.vendor}</span> ·
          base_url <span class="mono">{settings.model.base_url === "" ? "unknown（没配）" : settings.model.base_url}</span> ·
          name <span class="mono">{settings.model.name === "" ? "unknown（没配）" : settings.model.name}</span> ·
          api_key <span class="mono">{settings.model.api_key === "" ? "（空）" : settings.model.api_key}</span>
        </div>
        <div class="readings">
          推理强度 <span class="mono">{settings.model.reasoning_effort}</span>（所有智能体都按这一档 thinking；
 settings.json 的 model.reasoning_effort 留空 = 内置默认 High）·
          key 来源 <span class="mono">{settings.model.key_source === ""
            ? "没取到（环境变量与设置文件都没有）"
            : settings.model.key_source}</span>
          {settings.model.key_source === "settings"
            ? "（从 config 取到的）"
            : settings.model.key_source === "env"
              ? "（一个环境变量盖住了 config —— 写错了也不会有人发现）"
              : ""}
        </div>
        <div class="readings">
 这一页永远不显示 key 的值：后端 ModelSpec.redacted() 给的就是 *
          （裁定 E1：key 只写不读）。这里是同一句话的机器读数。
        </div>
      </Card>

      <Card
        title="设置三段"
        subtitle={`落点在盘上：${String(settings.exists)}`}
        right={<TriState tri={m.settings_tri} label="设置" reason={m.settings_reason} />}
      >
        {isUnreadable(m.settings_tri) ? (
          <span class="empty">设置没查成（不是"什么都没配"）。</span>
        ) : (
          <>
            <div class="readings">
              盘上见过的顶层键：<span class="mono">{cell(settings.raw_keys)}</span>
            </div>
            <Table
              rows={[
                ...pairs(settings.toolchain).map((p) => ({ ...p, part: "toolchain" })),
                ...pairs(settings.model as unknown as Record<string, unknown>).map((p) => ({
                  ...p,
                  part: "model",
                })),
                ...pairs(settings.workspace).map((p) => ({ ...p, part: "workspace" })),
              ]}
              empty="三段里一个键都没有（读到了空对象）。"
              columns={[
                { key: "part", title: "段" },
                { key: "k", title: "键" },
                { key: "v", title: "值", render: (r) => <span class="mono">{settingsCell(r.raw)}</span> },
              ]}
            />
          </>
        )}
      </Card>

      <Card title="设置窗口（写设置）">
        <div class="readings">
 写的是机器级设置文件（上面那一格里的路径）。每一格的初值就是设置文件里的现值（打开即可见；model.api_key 只写不读，
 所以那一格不回填）。逐格改，清空某一格表示"这一格不动"
 （settings.write_settings 的口径是只写给了值的键）。model.api_key 落盘、
 回执里恒为 *（key 只写不读）。lean_enabled 那一格是业主 2026-10-12 的
 省钱开关，取值只认 true / false；缺省是关。
        </div>
        <div class="readings">
          {FIELDS.map((field) => (
            <label class="opt" key={field.key}>
              <span class="mono">{field.key}</span>
              <input
                type={field.key === "model.api_key" ? "password" : "text"}
                placeholder={
                  field.key === "model.api_key"
                    ? field.hint
                    : currentOf(settings, field.key) === ""
                      ? `${field.hint}（盘上没设过）`
                      : field.hint
                }
                value={values[field.key] ?? presetOf(settings, field.key)}
                onInput={(ev) => {
                  const v = ev.currentTarget.value;
                  setValues((old) => ({ ...old, [field.key]: v }));
                }}
              />
            </label>
          ))}
        </div>
        {/* 按角色那一档（业主 2026-10-14）：十个角色各四格，留空 = 沿用下一档。
            表单键是三段的 `models.<角色>.<键>` —— 后端 `handle_settings` 对
            `models` 那段再切一刀（`writes.py`），其余段仍是两段。 */}
        <div class="readings">
          按角色配模型（留空 = 沿用 `models.default` / `model` 那两档；号与键都由后端现取）
        </div>
        {ROLES.map((role) => {
          // 那一档"配了没配 + 从哪一档取到的"现算（读数由后端给：
          // `settings.models.<角色>.configured` / `.source`）。为什么要显出来：
          // 不显的话，只有点开每一格才知道哪个角色真的配了自己的 key ——
          // 而"哪个角色在用哪一把"正是这一页要回答的问题。
          const cell = roleCell(settings, role);
          const configured = cell["configured"] === true;
          const src = typeof cell["source"] === "string" ? (cell["source"] as string) : "";
          return (
            <div class="readings" key={role}>
              <span class="mono">models.{role}</span>
              <Badge
                kind={configured ? "badge-pass" : "badge-na"}
                text={configured ? `配了（${src === "" ? "来源没读到" : src}）` : "沿用下一档"}
              />
              {ROLE_FIELDS.map((rf) => (
                <label class="opt" key={rf.key}>
                  <span class="mono">{rf.key}</span>
                  <input
                    type={rf.key === "api_key" ? "password" : "text"}
                    placeholder={
                      roleValue(settings, role, rf.key) === ""
                        ? `${rf.hint}（盘上没设过）`
                        : rf.hint
                    }
                    value={values[`models.${role}.${rf.key}`] ?? roleValue(settings, role, rf.key)}
                    onInput={(ev) => {
                      const v = ev.currentTarget.value;
                      setValues((old) => ({ ...old, [`models.${role}.${rf.key}`]: v }));
                    }}
                  />
                </label>
              ))}
            </div>
          );
        })}
        <ConfirmButton
          action="写这些设置"
          impact={`会改盘上那份设置文件（${settings.path === "" ? "落点没读到" : settings.path}）：
            只写填了值的 ${Object.values(values).filter((v) => v !== "").length} 格`}
          onConfirm={() => {
            postSettings(values)
              .then((got) => {
                setWriteResult(`${got.ok ? "成了" : "没成"}（tri=${got.tri}）：${got.reason}`);
                face.reload();
              })
              .catch((exc: unknown) => {
                setWriteResult(`写请求失败：${whyOf(exc)}`);
              });
          }}
          disabled={Object.values(values).every((v) => v === "")}
          note={
            Object.values(values).every((v) => v === "")
              ? "一格都没填 —— 按钮点不动（不假装成功）"
 : "写面没开（agentflow web --allow-writes）时后端会回 403，回执如实显示"
          }
        />
        {writeResult === "" ? null : <div class="readings">{writeResult}</div>}
      </Card>

      <Card
        title="停机 / 进程"
        right={<Badge kind="badge-pass" text="已接线：见「在飞」页" />}
      >
        <div class="readings">
          活着的循环与进程、停机开关与历史、状态报告、用量拆解 —— 都在
          <a class="nav-link" href="/live">
            「在飞」
          </a>
 那一页（GET /api/live / /api/status-reports / /api/usage 三条只读端点）。
 这一张卡片此前渲染的是 not_applicable 加一句"没有端点给它"——
          那在今天是错的，所以改成指路。
        </div>
      </Card>
    </>
  );
}
