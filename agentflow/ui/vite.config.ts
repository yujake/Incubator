/**
 * 前端构建配置（裁定 A2：Preact + Vite；裁定 B1：产物入库）。
 *
 * 三处刻意钉住的取值（每一处都有下游判据读它）：
 *
 * 1. `base = "/static/"` —— 与服务端静态路由的前缀逐字一致（`webui/routes.py`
 *    的 `GET /static/{file}`）。两者不一致时，构建能过、页面全白。
 * 2. `outDir = "../src/agentflow/web/static"` —— 产物落进包内（裁定 B1：入库，
 *    于是"clone 下来不需要 node 就能 `agentflow web`"）。`emptyOutDir: true`
 *    是必须的：不清空会留下上一版的哈希文件名，而 `index.html` 只引用当前那一个，
 *    旧文件既不会被删也不会被用 —— 判据"产物自洽"会因此看不出问题。
 * 3. 哈希文件名 + `sourcemap: false` —— 静态路由按"带哈希 ⇒ 可 immutable 缓存"
 *    处理，所以文件名里必须有内容哈希；sourcemap 不进仓（体积 + 它引用的源码
 *    在发布形态下并不存在）。
 */
import { defineConfig } from "vite";
import preact from "@preact/preset-vite";

export default defineConfig({
  base: "/static/",
  plugins: [preact()],
  build: {
    outDir: "../src/agentflow/web/static",
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
    rollupOptions: {
      output: {
        entryFileNames: "assets/[name].[hash].js",
        chunkFileNames: "assets/[name].[hash].js",
        assetFileNames: "assets/[name].[hash][extname]",
      },
    },
  },
});
