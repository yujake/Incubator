/*
 * 本机读数（W0：空壳）。
 *
 * 还缺什么：`readers.machine_readings(root)`（W1，`toolchain.toolchain_report()` 与
 * `settings.load_settings()`，key 走 `ModelSpec.redacted()`）与 `GET /api/machine`；
 * 写设置那一半（裁定 E1：key 只写不读）在 W4。
 */
import { Card } from "../components/Card";
import { TriState } from "../components/TriState";

export function Machine() {
  return (
    <Card title="本机">
      <TriState
        tri="not_applicable"
        label="证明检查器 / Mathlib / 模型"
        reason="这一面要等 W1 的读模型（readers.machine_readings）；写设置在 W4"
      />
    </Card>
  );
}
