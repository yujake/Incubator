/*
 * 叫停按钮（`POST /api/stop`）—— 「一趟详情」与「在飞」两页用的是**同一套**。
 *
 * 为什么抽出来（业主 2026-10-13：「网页中没找到停机开关」）：叫停的语义只有一种
 * （优雅停：落一个停机开关，在飞的循环在下一个检查点收工；强制停：连子孙进程一起杀，
 * 不可逆），两页各写一份文案与动作，迟早漂成两套说法；而这一对按钮此前**只**长在
 * 「一趟详情」里 —— 用户要叫停时待的却是「在飞」那一页。
 *
 * 两次确认由 `ConfirmButton` 负责（第一次点击只"上膛"并把影响写给人看）；回执按
 * 三态原样显示，不折成"成功"。
 */
import { useState } from "preact/hooks";

import { postStop, whyOf } from "../api";
import { ConfirmButton } from "./ConfirmButton";

export function StopButtons(props: { onDone?: () => void }) {
  const [result, setResult] = useState("");

  const fire = (force: boolean): void => {
    setResult("");
    postStop({ reason: "user", force })
      .then((got) => {
        setResult(`${got.ok ? "成了" : "没成"}（tri=${got.tri}）：${got.reason}`);
        if (props.onDone !== undefined) {
          props.onDone();
        }
      })
      .catch((exc: unknown) => {
        setResult(`写请求失败：${whyOf(exc)}`);
      });
  };

  return (
    <>
      <div class="readings">
        <ConfirmButton
          action="叫停这一趟"
          impact="会给工作区落一个停机开关，并请求正在跑的循环在下一个检查点收尾"
          onConfirm={() => {
            fire(false);
          }}
          note="优雅停：正在跑的活收尾、没做完的标成「停在这里」；写面没开时后端回 403"
        />
      </div>
      <div class="readings">
        <ConfirmButton
          action="强制停（连子孙进程）"
          impact="先落停机开关，再按进程登记把在跑的循环连同子孙进程一起杀掉 —— 不可逆"
          onConfirm={() => {
            fire(true);
          }}
          requireForce
          note="不可逆：要勾选确认才允许按第二次"
        />
      </div>
      {result === "" ? null : <div class="readings">{result}</div>}
    </>
  );
}
