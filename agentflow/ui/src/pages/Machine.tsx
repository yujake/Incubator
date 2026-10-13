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

/** 设置窗口里的每一格（`段.键` 形状逐字对应后端 `handle_settings` 读的表单键）。 */
const FIELDS: ReadonlyArray<{ key: string; hint: string }> = [
  { key: "toolchain.lean_bin", hint: "Lean 可执行文件所在目录（例：_env/lean470/.../bin）" },
  { key: "toolchain.mathlib_root", hint: "Mathlib 检出的根目录" },
  { key: "toolchain.coq_bin", hint: "Coq 落点（没有就留空）" },
  { key: "toolchain.isabelle_bin", hint: "Isabelle 落点（没有就留空）" },
  { key: "toolchain.lean_enabled", hint: "true / false —— 缺省 false（省钱档）" },
  { key: "model.api_key", hint: "只写不读；写进去之后回执里恒为 ***" },
  { key: "model.base_url", hint: "留空 = 用内置缺省端点" },
  { key: "model.name", hint: "留空 = 用内置缺省模型" },
  { key: "model.reasoning_effort", hint: "off / low / high / max" },
  { key: "workspace.projects_dir", hint: "默认项目目录（留空 = 工作区自己那一个）" },
];

/** 从 `Record<string, unknown>` 里读一格：读不到 ⇒ `unknown`（不是空串、不是 false）。 */
function field(rec: Record<string, unknown>, key: string): string {
  return cell(rec[key]);
}

/** 三态布尔：`null` / `undefined` ⇒ `unknown`（不折成 false）。 */
function triBool(value: unknown): string {
  return typeof value === "boolean" ? String(value) : "unknown";
}

/** 把"键值对"渲染成一张两列的表（设置三段与嵌套读数都用它）。 */
function pairs(rec: Record<string, unknown>): Array<{ k: string; v: string }> {
  return Object.keys(rec)
    .sort()
    .map((k) => ({ k, v: field(rec, k) }));
}

export function Machine() {
  const face = useFace(() => api.getMachine());
  const [values, setValues] = useState<Record<string, string>>({});
  const [writeResult, setWriteResult] = useState("");

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
          `checked=false` ⇒ 上面那些是"探测没跑完"：整面记 `unreadable`，
          不是"一个检查器都没找到"。
        </div>
      </Card>

      <Card
        title="Lean / Mathlib"
        subtitle={`lean_ready=${triBool(m.lean_ready)} · can_do_formal=${triBool(m.can_do_formal)}`}
      >
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
          base_url <span class="mono">{settings.model.base_url === "" ? "unknown（没配）" : settings.model.base_url}</span> ·
          name <span class="mono">{settings.model.name === "" ? "unknown（没配）" : settings.model.name}</span> ·
          api_key <span class="mono">{settings.model.api_key === "" ? "（空）" : settings.model.api_key}</span>
        </div>
        <div class="readings">
          推理强度 <span class="mono">{settings.model.reasoning_effort}</span>（所有智能体都按这一档 thinking；
          `settings.json` 的 `model.reasoning_effort` 留空 = 内置默认 High）·
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
          这一页永远不显示 key 的值：后端 `ModelSpec.redacted()` 给的就是 `***`
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
                { key: "v", title: "值", render: (r) => <span class="mono">{r.v}</span> },
              ]}
            />
          </>
        )}
      </Card>

      <Card title="设置窗口（写设置）">
        <div class="readings">
          写的是**机器级**设置文件（上面那一格里的路径）。逐格填，空着表示"这一格不动"
          （`settings.write_settings` 的口径是只写给了值的键）。`model.api_key` 落盘、
          回执里恒为 `***`（key 只写不读）。`lean_enabled` 那一格是业主 2026-10-12 的
          省钱开关，取值只认 `true` / `false`；缺省是**关**。
        </div>
        <div class="readings">
          {FIELDS.map((field) => (
            <label class="opt" key={field.key}>
              <span class="mono">{field.key}</span>
              <input
                type="text"
                placeholder={field.hint}
                value={values[field.key] ?? ""}
                onInput={(ev) => {
                  const v = ev.currentTarget.value;
                  setValues((old) => ({ ...old, [field.key]: v }));
                }}
              />
            </label>
          ))}
        </div>
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
              : "写面没开（`agentflow web --allow-writes`）时后端会回 403，回执如实显示"
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
          那一页（`GET /api/live` / `/api/status-reports` / `/api/usage` 三条只读端点）。
          这一张卡片此前渲染的是 `not_applicable` 加一句"没有端点给它"——
          那在今天是错的，所以改成指路。
        </div>
      </Card>
    </>
  );
}
