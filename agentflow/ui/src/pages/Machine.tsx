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
 * 一处**如实标注的缺口**：`draft/74 §3.5` 第 6 行（活着的 loop / 进程）要
 * `stopctl.live_pids` / `running_loops` 的读数，而 `MachineView` 里没有这一栏，
 * 今天也没有别的端点给它 ⇒ 渲染 `not_applicable` 并写明。
 */
import { api } from "../api";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { ConfirmButton } from "../components/ConfirmButton";
import { Table, cell } from "../components/Table";
import { TriState, isUnreadable } from "../components/TriState";
import { useFace } from "../live";

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

      <Card title="写设置（缺口）">
        <div class="readings">
          `POST /api/settings` 属于 C 线 W4，后端今天没有这条路由 ⇒ 按钮点不动；
          key 只写不读（裁定 E1）那一条要等它上线才有东西可判。
        </div>
        <ConfirmButton
          action="写机器级设置"
          impact="会改这台机器的 settings.json（工具链落点 / 模型接线）"
          onConfirm={() => undefined}
          requireForce
          disabled
          note="写端点还没上线（C 线 W4）—— 点不动，也不假装成功"
        />
      </Card>

      <Card
        title="停机 / 进程（缺口）"
        right={
          <TriState
            tri="not_applicable"
            label="live_pids / running_loops"
            reason="draft/74 说这一栏读 stopctl.live_pids 与 running_loops，而 MachineView 里没有这一栏，今天也没有别的端点给它"
          />
        }
      >
        <div class="readings">
          这一栏要一条读 `stopctl` 的只读端点才能给读数。工作区根在首页的「落点」那一格里。
        </div>
      </Card>
    </>
  );
}
