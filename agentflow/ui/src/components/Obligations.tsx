/*
 * 板上的义务（`GET /api/obligations`，2026-11-19 的 ⑥）。
 *
 * 族名从 payload 的 `families[]` 现取（今天四族：b-register / v-resubmit / b-awake /
 * d-handoff —— 真身在 `obligations` 的四个前缀常量），**不写死**：产品侧加一族时
 * 这一页的标题与计数跟着 payload 走，不会再把族数写死。标题与空态的真身在
 * `obligationsState.ts`（纯函数，可由判据直接喂人造数组）。
 *
 * 名册的收件箱按 `parent_task_id`（父台账号）分，而一条板项可以只带**收件实例**
 * （板项行的 `instance` 列）—— 父为空的项不挂在任何人的收件箱上，页面上就看不见它。
 * 这一块把两条轴分开摆：
 *
 * - 收件实例 = `recipient_instance`（口径：`obligations.recipient_reading` ——
 *   调用方点名 > 命题登记实例 > 角色地址；`Conductor.open_items_for` 就按它取件）；
 * - 父台账号 = `parent_task_id`（名册收件箱那一轴）。
 *
 * 两轴都空 ⇒ `addressed="unowned"`：这不是"没有义务"，是"这条义务没人收"。
 * 只读：销号只发生在 conductor 的写路径上，网页不提供销号按钮。
 */
import { api } from "../api";
import { Card } from "./Card";
import { PagedTable } from "./PagedTable";
import { cell } from "./Table";
import { TriState, isUnreadable } from "./TriState";
import { useFace } from "../live";
import { emptyWord, familiesTitle } from "../obligationsState";

export function ObligationsPanel() {
  const face = useFace(() => api.getObligations());
  if (face.data === null) {
    return (
      <Card
        title="义务"
        tone={face.problem === "" ? "plain" : "problem"}
        right={face.problem === "" ? null : (
          <TriState tri="unreadable" reason={face.problem} label="义务" />
        )}
      >
        <span class="readings">{face.problem === "" ? "正在读盘……" : face.problem}</span>
      </Card>
    );
  }
  const ob = face.data;
  return (
    <Card
      title={familiesTitle(ob.families)}
      subtitle="族名与数量由 `/api/obligations` 的 families[] 现取；收件实例轴与父台账号轴是两回事，两轴都空 = 没人收"
      tone={isUnreadable(ob.tri) ? "problem" : "plain"}
      right={<TriState tri={ob.tri} label="义务" reason={ob.reason} />}
    >
      {ob.tri === "not_applicable" ? (
        <span class="empty">{ob.reason || "还没有这张表（这个工作区还没开过板项）。"}</span>
      ) : (
        <>
          <div class="readings">
            {ob.families.map((f) => (
              <span key={f.name} class="mono">
                {f.name}：开 {cell(f.open)}（没人收 {cell(f.unowned)}）·{" "}
              </span>
            ))}
          </div>
          <div class="readings tri-reason">{ob.recipient_rule}</div>
          <PagedTable
            rows={ob.rows}
            empty={emptyWord(ob.families)}
            columns={[
              { key: "family", title: "族" },
              { key: "key", title: "幂等键", render: (r) => <span class="mono">{r.key}</span> },
              {
                key: "recipient_instance",
                title: "收件实例",
                render: (r) => (
                  <span class="mono">{r.recipient_instance === "" ? "—（角色地址）" : r.recipient_instance}</span>
                ),
              },
              {
                key: "parent_task_id",
                title: "父台账号",
                render: (r) => (
                  <span class="mono">{r.parent_task_id === "" ? "—（没有父）" : r.parent_task_id}</span>
                ),
              },
              { key: "item_state", title: "项状态" },
              { key: "item_close", title: "收口", render: (r) => (r.item_close === "" ? "—" : r.item_close) },
              {
                key: "wake_task_id",
                title: "叫醒行",
                render: (r) => (
                  <span class="mono">{r.wake_task_id === "" ? "—（没叫醒过）" : r.wake_task_id}</span>
                ),
              },
              { key: "addressed", title: "投给谁" },
              { key: "detail", title: "说明", render: (r) => (r.detail === "" ? "—" : r.detail) },
            ]}
          />
        </>
      )}
    </Card>
  );
}
