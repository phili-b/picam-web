// Live state shared by all components: one poll loop, components only read it.
import { api, type Frames, type Health, type Info, type Roi } from "./api";

export const live = $state({
  info: null as Info | null,
  health: null as Health | null,
  frames: null as Frames | null,
  rois: [] as Roi[],
  connected: false,
  error: "",
});

let busy = false;

/** One round of polling; skipped while the previous one is still running (slow link). */
async function poll() {
  if (busy) return;
  busy = true;
  try {
    const health = await api.health();
    if (live.health && health.instance !== live.health.instance) live.info = null; // service restarted
    live.health = health;
    live.connected = true;
    live.error = "";
    if (health.state === "failed" && !live.info) return;
    if (!live.info) live.info = await api.info();
    const [frames, rois] = await Promise.all([api.frames(), api.rois()]);
    live.frames = frames;
    live.rois = rois;
  } catch (e) {
    live.connected = false;
    live.error = (e as Error).message;
  } finally {
    busy = false;
  }
}

export async function reloadInfo() {
  live.info = await api.info();
}

export function startPolling(periodMs = 500) {
  poll();
  const id = setInterval(poll, periodMs);
  return () => clearInterval(id);
}
