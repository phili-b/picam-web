// Typed client for the camera service HTTP API (picam_web/server.py, docs at /docs).

export type Size = [number, number];

export interface SensorMode {
  format: string;
  unpacked: string;
  size: Size;
  bit_depth: number;
  fps: number;
  crop_limits: [number, number, number, number];
  exposure_limits?: [number, number, number | null];
}

export interface Info {
  properties: Record<string, unknown> & { Model?: string; PipelineHandler?: string };
  sensor_modes: SensorMode[];
  mode: number;
  raw: { format: string; size: Size; stride: number };
  main: { format: string; size: Size };
  is_mono: boolean;
  tuning_file: string | null;
  sensor: string | null;
  version: string;
  instance: string;
}

export type HealthState = "starting" | "streaming" | "recovering" | "failed" | "stalled";

export interface Health {
  state: HealthState;
  message: string;
  since: number;
  recovery_level: number;
  history: [string, string][];
  kernel: string[];
  auto_reboot: boolean;
  instance: string;
}

export interface Frames {
  error: string | null;
  frames: number;
  dropped: number;
  fps: number;
  expected_fps: number;
  last_gap_ms: number;
  max_gap_ms: number;
  /** Raw area shown by the preview: [x0, y0, x1, y1] in raw pixels. */
  view: [number, number, number, number] | null;
}

export interface Control {
  min: unknown;
  max: unknown;
  default: unknown;
  value: unknown;
}

export interface Roi {
  name: string;
  x: number;
  y: number;
  w: number;
  h: number;
  mean?: number | null;
}

export interface RawCrop {
  x: number;
  y: number;
  w: number;
  h: number;
  bits: number;
  width: number;
  height: number;
  age_s: number;
  values: number[];
}

export interface Histogram {
  bits?: number;
  channels?: Record<string, number[]>;
  mean?: number;
  min?: number;
  max?: number;
  error?: string;
}

/** An error answer of the service, with the HTTP status (503 = camera not delivering frames). */
export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

export function errorText(data: unknown, fallback: string): string {
  const d = (data as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d.map((x: { loc?: unknown[]; msg?: string }) => `${(x.loc ?? []).slice(1).join(".") || "value"}: ${x.msg}`).join("; ");
  }
  return fallback;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = r.headers.get("content-type")?.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new ApiError(errorText(data, r.statusText), r.status);
  return data as T;
}

const get = <T>(path: string) => request<T>("GET", path);
const post = <T>(path: string, body?: unknown) => request<T>("POST", path, body);
const put = <T>(path: string, body?: unknown) => request<T>("PUT", path, body);

export interface Noise {
  frames: number;
  pixels: number;
  mean: number;
  min: number;
  max: number;
  temporal_noise: number | null;
  fpn: number;
  row_fpn: number;
  col_fpn: number;
  row_temporal_noise: number | null;
  col_temporal_noise: number | null;
  format: string;
  bit_depth: number;
  roi: number[] | null;
}

export interface IspStats {
  enabled: boolean;
  error?: string;
  count?: number;
  histogram?: number[];
  zones_mean?: number[][];
  focus?: number[][];
}

export interface KnownRegisters {
  sensor: string | null;
  name: string | null;
  banked: boolean;
  /** Context names of the bank 1 registers, e.g. "AB"; "" without contexts. */
  contexts: string;
  /** "driver": through the driver's register controls; "i2c": directly on the I2C bus. */
  backend: "driver" | "i2c" | null;
  registers: { name: string; address: number; bytes: number }[];
}

/** The driver's context controls (sensors whose profile has contexts). */
export interface Contexts {
  available: boolean;
  contexts?: string;
  /** The context the sensor switches to. */
  context?: string;
  /** The context the sensor uses now; null when not streaming. */
  current?: string | null;
  auto_switch?: boolean;
  auto_switch_to?: string;
  /** The context(s) exposure and frame time go to: "all" or a context. */
  controls_context?: string;
}

export type ContextsUpdate = Partial<Pick<Contexts, "context" | "auto_switch" | "auto_switch_to" | "controls_context">>;

/** Bank and context of a banked register map; null = bank 0 / context A through the
 * driver, leave as it is over I2C. */
export interface BankSelect {
  bank: number | null;
  context: number | null;
}

const query = (params: Record<string, number | null>) =>
  Object.entries(params).filter(([, v]) => v !== null).map(([k, v]) => `${k}=${v}`).join("&");

export const api = {
  info: () => get<Info>("/api/info"),
  health: () => get<Health>("/api/health"),
  reset: (action: "stream" | "camera" | "reboot") => post<{ action: string }>("/api/reset", { action }),
  setAutoReboot: (enabled: boolean) => post<{ auto_reboot: boolean }>("/api/auto_reboot", { enabled }),
  frames: () => get<Frames>("/api/frames"),
  resetFrames: () => post<Frames>("/api/frames/reset"),

  controls: () => get<Record<string, Control>>("/api/controls"),
  setControls: (values: Record<string, unknown>, remember = false) =>
    post<{ set: string[]; remembered: boolean }>(`/api/controls?remember=${remember}`, values),
  forgetControls: () => request<unknown>("DELETE", "/api/controls/remembered"),
  metadata: () => get<Record<string, unknown>>("/api/metadata"),
  setMode: (index: number) => post<{ mode: number; rois: Roi[] }>("/api/mode", { index }),
  tuning: () => get<{ current: string | null; files: string[] }>("/api/tuning"),
  setTuning: (path: string | null) => post<{ instance: string }>("/api/tuning", { path }),

  rois: () => get<Roi[]>("/api/rois"),
  setRois: (rois: Roi[]) => put<Roi[]>("/api/rois", rois.map(({ name, x, y, w, h }) => ({ name, x, y, w, h }))),
  noise: (frames: number, roi: number[] | null) => post<Noise>("/api/noise", { frames, roi }),
  histogram: () => get<Histogram>("/api/histogram"),
  rawCrop: (x: number, y: number, w: number, h: number) =>
    get<RawCrop>(`/api/raw/crop?x=${x}&y=${y}&w=${w}&h=${h}`),
  ispStats: () => get<IspStats>("/api/isp_stats"),
  enableIspStats: (enabled: boolean) => post<{ enabled: boolean }>("/api/isp_stats/enable", { enabled }),

  knownRegisters: () => get<KnownRegisters>("/api/registers/known"),
  readRegister: (address: number, nbytes: number, sel: BankSelect) =>
    get<{ value: number }>(`/api/registers/${address}?${query({ nbytes, ...sel })}`),
  writeRegister: (address: number, value: number, nbytes: number, sel: BankSelect) =>
    put<unknown>(`/api/registers/${address}`, { value, nbytes, ...sel }),
  dumpRegisters: (start: number, count: number, sel: BankSelect) =>
    get<{ address: number; value: number }[]>(`/api/registers/dump?${query({ start, count, ...sel })}`),
  contexts: () => get<Contexts>("/api/sensor/contexts"),
  setContexts: (values: ContextsUpdate) => put<Contexts>("/api/sensor/contexts", values),
};

/** After a camera reset or tuning switch: wait for the new service process, then reload the page. */
export async function reloadWhenRestarted(oldInstance: string | undefined, timeoutMs = 60000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    await new Promise((r) => setTimeout(r, 1000));
    try {
      if ((await api.health()).instance !== oldInstance) { location.reload(); return; }
    } catch { /* not answering yet */ }
  }
  throw new Error("The service did not come back within a minute.");
}

/** "0x1A" or "26" -> 26; throws on anything else. */
export function parseNumber(text: string): number {
  const t = text.trim().toLowerCase();
  const v = t.startsWith("0x") ? parseInt(t, 16) : Number(t);
  if (t === "" || Number.isNaN(v)) throw new Error(`'${text}' is not a number`);
  return v;
}

export const hex = (v: number, bytes = 1) => "0x" + v.toString(16).padStart(2 * bytes, "0");
