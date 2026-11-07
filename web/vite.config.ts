import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// The camera service to develop against: a Pi (PICAM_URL=http://raspberrypi.local) or the
// simulator (python tests/fake/run_fake.py web -> http://127.0.0.1:8080, the default).
const target = process.env.PICAM_URL || "http://127.0.0.1:8080";

export default defineConfig({
  plugins: [svelte()],
  base: "/",                 // served by picam_web/server.py at /
  build: { outDir: "dist", emptyOutDir: true, target: "es2022" },
  server: {
    port: 5173,
    proxy: {
      "/api": target,
      "/stream.mjpg": target,
      "/static": target,
    },
  },
});
