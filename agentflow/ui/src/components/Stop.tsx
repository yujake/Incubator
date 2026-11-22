/*
 * 叫停按钮（`POST /api/stop`）—— 「一趟详情」与「在飞」两页用的是**同一套**。
 *
 * 为什么抽出来：叫停的语义只有一种
 * （优雅停：落一个停机开关，在飞的循环在下一个检查点收工；强制停：连子孙进程一起杀，
 * 不可逆），两页各写一份文案与动作，迟早漂成两套说法；而这一对按钮此前**只**长在
 * 「一趟详情」里 —— 用户要叫停时待的却是「在飞」那一页。
 *
 * 两次确认由 `ConfirmButton` 负责（第一次点击只"上膛"并把影响写给人看）；回执按
 * 三态原样显示，不折成"成功"。只读档（没开 `--allow-writes`）时两个按钮直接禁用，
 * 理由写在按钮旁（`writes_reason`，后端逐字给）—— 不许让人按出 403 才知道没权限。
 */
import { useState } from "preact/hooks";

import { postStop, postStopClear } from "../api";
import { ErrorBlock, faceOfError, faceOfWrite } from "./ErrorBlock";
import type { ErrorFace } from "./ErrorBlock";
import { ConfirmButton } from "./ConfirmButton";
import { useLive } from "../live";

/**
 * 「撤销叫停」按钮（`POST /api/stop/clear`，2026-11-21 WEBFIX2 F9）。
 *
 * 为什么它必须与叫停按钮摆在一起：叫停之后那把开关会**一直留在盘上**
 * （没有在跑的循环去消费它），于是用户"叫停 → 改主意 → 再起一趟"时，
 * 新起的那一趟第一步就被旧开关停掉 —— 白起一趟，而页面上此前没有任何地方能撤掉它
 * （`stopctl.clear_stop` 只有 CLI 一个调用者）。幂等：本来就没有开关时回 200 +
 * `cleared=false`，回执那句会说"当前没有叫停"。
 */
export function ClearStopButton(props: { onDone?: () => void }) {
  const live = useLive();
  const [feed, setFeed] = useState<ErrorFace | null>(null);
  const readOnly = live.writesAllowed === false;
  const why = readOnly ? live.writesReason : "";
  return (
    <>
      <div class="readings">
        <ConfirmButton
          action="撤销叫停"
          impact="撤掉盘上那把停机开关，于是再起一趟不会被它停掉（上一趟已经停下的事实不变）"
          onConfirm={() => {
            setFeed(null);
            postStopClear()
              .then((got) => {
                setFeed(faceOfWrite(got));
                if (props.onDone !== undefined) {
                  props.onDone();
                }
              })
              .catch((exc: unknown) => {
                setFeed(faceOfError(exc));
              });
          }}
          disabled={readOnly}
          note={readOnly ? why : "盘上本来就没有开关时也安全：回执会说「当前没有叫停」"}
        />
      </div>
      {feed === null ? null : <ErrorBlock face={feed} />}
    </>
  );
}

export function StopButtons(props: { onDone?: () => void }) {
  const live = useLive();
  const [feed, setFeed] = useState<ErrorFace | null>(null);
  const readOnly = live.writesAllowed === false;
  const why = readOnly ? live.writesReason : "";

  const fire = (force: boolean): void => {
    setFeed(null);
    postStop({ reason: "user", force })
      .then((got) => {
        setFeed(faceOfWrite(got));
        if (props.onDone !== undefined) {
          props.onDone();
        }
      })
      .catch((exc: unknown) => {
        setFeed(faceOfError(exc));
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
          disabled={readOnly}
          note={readOnly ? why : "优雅停：正在跑的活收尾、没做完的标成「停在这里」"}
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
          disabled={readOnly}
          note={readOnly ? why : "不可逆：要勾选确认才允许按第二次"}
        />
      </div>
      {feed === null ? null : <ErrorBlock face={feed} />}
    </>
  );
}
