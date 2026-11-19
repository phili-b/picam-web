<script lang="ts">
  // Sensor mode, auto exposure, exposure time and gain (sliders and number fields).
  import { api } from "../lib/api";
  import { live, reloadInfo } from "../lib/live.svelte";
  import AllControls from "../components/AllControls.svelte";
  import WhiteBalance from "../components/WhiteBalance.svelte";
  import TuningFile from "../components/TuningFile.svelte";
  import CameraModel from "../components/CameraModel.svelte";
  import DenoiseProfile from "../components/DenoiseProfile.svelte";

  let ae = $state(true);
  let exposure = $state(10000);   // us
  let gain = $state(1);           // the total gain asked for: analogue, then digital (see splitGain)
  let applied = $state("");        // the exposure and gains the camera applies (frame metadata)
  const DIGITAL_MAX = 4;          // libcamera's AGC max_digital_gain (tuning file default)
  let remember = $state(false);
  let msg = $state(""), error = $state(false);
  let switching = $state(false);
  let limits = $state({ expMin: 10, expMax: 1_000_000, gainMin: 1, gainMax: 16 });

  // Exposure slider on a log scale: 0..1000 -> expMin..expMax
  const toSlider = (us: number) => 1000 * Math.log(us / limits.expMin) / Math.log(limits.expMax / limits.expMin);
  const fromSlider = (p: number) => Math.round(limits.expMin * Math.pow(limits.expMax / limits.expMin, p / 1000));

  // 12-bit modes of some sensors have a fixed gain: min equals max, nothing to slide
  const gainFixed = $derived(limits.gainMax - limits.gainMin < 0.01);
  // The analogue gains the sensor has, when libcamera lists them (a sensor with discrete gain steps)
  let gainSteps = $state<number[] | null>(null);
  const nearestStep = (g: number) => gainSteps!.reduce((a, b) => (Math.abs(b - g) < Math.abs(a - g) ? b : a));
  // One gain: libcamera has no digital gain control. It is asked for a total gain and fills the
  // analogue gain first, up to its maximum; the rest (up to DIGITAL_MAX more) is digital gain in the
  // ISP. Below the analogue maximum the gain snaps to the sensor's steps (when libcamera lists them)
  const gainTop = $derived(limits.gainMax * DIGITAL_MAX);
  function snapGain(g: number) {
    if (!Number.isFinite(g)) return limits.gainMin;
    g = Math.min(gainTop, Math.max(limits.gainMin, g));
    if (g < limits.gainMax - 1e-3) return gainSteps ? nearestStep(g) : Math.round(g * 100) / 100;
    return Math.round(g * 100) / 100;
  }
  const splitGain = (g: number) => {
    const a = g < limits.gainMax - 1e-3 ? (gainSteps ? nearestStep(g) : g) : limits.gainMax;
    return { analogue: a, digital: g / a };
  };
  const splitText = (g: number) => {
    const s = splitGain(g);
    return s.digital > 1.005 ? `= ${fmtLimit(s.analogue)}x analogue × ${fmtLimit(s.digital)}x digital (ISP)`
      : `= ${fmtLimit(s.analogue)}x analogue`;
  };
  // Gain slider on a log scale: 0..1000 -> gainMin..gainTop
  const gainToSlider = (g: number) => 1000 * Math.log(g / limits.gainMin) / Math.log(gainTop / limits.gainMin);
  const gainFromSlider = (p: number) => limits.gainMin * Math.pow(gainTop / limits.gainMin, p / 1000);
  const fmtLimit = (x: number) => (Math.abs(x) >= 100 ? Math.round(x).toLocaleString("en") : String(Math.round(x * 100) / 100));

  function say(text: string, isError = false) { msg = text; error = isError; }

  async function load() {
    const c = await api.controls();
    const num = (v: unknown, d: number) => (typeof v === "number" ? v : d);
    // The exposure range of the current sensor mode (info) narrows the one libcamera reports
    const info = live.info ?? await api.info();
    const mode = info.sensor_modes?.[info.mode]?.exposure_limits;
    limits = {
      expMin: Math.max(1, num(c.ExposureTime?.min, 10), num(mode?.[0], 0)),
      expMax: Math.min(num(c.ExposureTime?.max, 1_000_000), num(mode?.[1], Infinity)),
      gainMin: num(c.AnalogueGain?.min, 1), gainMax: num(c.AnalogueGain?.max, 16),
    };
    const steps = (c.AnalogueGain?.values ?? []).filter((v): v is number => typeof v === "number");
    gainSteps = steps.length > 1 ? steps : null;
    // Some modes report a nonsense gain maximum (an overflowed 1e28): use a sane one then
    if (!Number.isFinite(limits.gainMax) || limits.gainMax > 1000) limits.gainMax = Math.max(16, limits.gainMin);
    ae = Boolean(c.AeEnable?.value ?? c.AeEnable?.default ?? true);
    // With auto exposure off, show what the camera applies now (the tab starts from scratch after a
    // tab switch; without this the fields fell back to 10000 us and gain 1)
    if (!ae) {
      const md = await api.metadata();
      if (typeof md.ExposureTime === "number") exposure = md.ExposureTime;
      if (typeof md.AnalogueGain === "number") gain = totalOf(md.AnalogueGain, md.DigitalGain);
    }
    exposure = Math.min(limits.expMax, Math.max(limits.expMin, exposure));
    gain = snapGain(gain);
  }

  // The total gain from what the camera applies: the digital gain counts only with the analogue gain
  // at its maximum (below that libcamera's digital gain is only a small exposure correction)
  function totalOf(a: number, d: unknown) {
    return a >= limits.gainMax - 1e-3 && typeof d === "number" ? a * Math.min(DIGITAL_MAX, Math.max(1, d)) : a;
  }

  // The gains the camera applies; with auto exposure on, the fields follow the camera
  $effect(() => {
    const auto = ae;
    const id = setInterval(async () => {
      try {
        const md = await api.metadata();
        const a = typeof md.AnalogueGain === "number" ? md.AnalogueGain : null;
        const d = typeof md.DigitalGain === "number" ? md.DigitalGain : null;
        const t = typeof md.ExposureTime === "number" ? md.ExposureTime : null;
        if (t !== null || a !== null)
          applied = "Applied: " + [t !== null ? `exposure ${t.toLocaleString("en")} µs` : "",
            a !== null ? `analogue gain ${a.toFixed(2)}x (sensor)` : "",
            d !== null ? `digital gain ${d.toFixed(2)}x (ISP: preview and JPEG only, not the raw images)` : ""]
            .filter(Boolean).join(", ");
        if (!auto) return;
        if (typeof md.ExposureTime === "number") exposure = md.ExposureTime;
        if (a !== null) gain = snapGain(totalOf(a, d));
      } catch { /* shown by the status line */ }
    }, 500);
    return () => clearInterval(id);
  });

  async function apply() {
    // A typed value outside the limits is brought back into them
    const clamp = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, Number.isFinite(x) ? x : lo));
    exposure = clamp(exposure, limits.expMin, limits.expMax);
    gain = snapGain(gain);
    const v: Record<string, unknown> = { AeEnable: ae };
    // The total gain goes to libcamera's AnalogueGain: it applies the part above the analogue
    // maximum as digital gain in the ISP
    if (!ae) { v.ExposureTime = Math.round(exposure); v.AnalogueGain = Math.round(gain * 1000) / 1000; }
    try {
      const r = await api.setControls(v, remember);
      say("Set " + r.set.join(", ") + (r.remembered ? " (kept after a restart)" : ""));
    } catch (e) { say((e as Error).message, true); }
  }

  async function forget() {
    try { await api.forgetControls(); say("Kept controls cleared: the defaults apply after a restart."); }
    catch (e) { say((e as Error).message, true); }
  }

  async function setMode(e: Event) {
    const index = Number((e.target as HTMLSelectElement).value);
    switching = true;
    say("Switching sensor mode...");
    try {
      const r = await api.setMode(index);
      live.rois = r.rois;
      await reloadInfo();
      await load();
      say("Sensor mode switched");
    } catch (err) { say((err as Error).message, true); }
    switching = false;
  }

  $effect(() => { load().catch((e) => say(e.message, true)); });

  // Camera model section: opens by itself once when the camera fails (a wrong camera model is the
  // usual reason), otherwise the user opens and closes it. Bound to `open` directly it would be
  // reset by every health poll.
  let modelOpen = $state(false);
  const failed = $derived(live.health?.state === "failed");
  $effect(() => { if (failed) modelOpen = true; });
</script>

<div class="row">
  <label for="mode">Sensor mode</label>
  <select id="mode" disabled={switching || !live.info} onchange={setMode} value={live.info?.mode}>
    {#each live.info?.sensor_modes ?? [] as m, i}
      <option value={i}>{m.unpacked} {m.size[0]}x{m.size[1]} {m.bit_depth}-bit {m.fps.toFixed(1)} fps</option>
    {/each}
  </select>
</div>

<DenoiseProfile />

<div class="row">
  <label for="ae">Auto exposure</label>
  <input id="ae" type="checkbox" bind:checked={ae} onchange={() => ae && apply()} />
</div>

<div class="row">
  <label for="exp">Exposure [µs]</label>
  <input type="range" min="0" max="1000" disabled={ae} value={toSlider(exposure)}
    oninput={(e) => (exposure = fromSlider(Number((e.target as HTMLInputElement).value)))} onchange={apply} />
  <input id="exp" type="number" min={limits.expMin} max={limits.expMax} disabled={ae} bind:value={exposure} onchange={apply} />
</div>

<div class="row">
  <label for="gain">Gain</label>
  <input type="range" min="0" max="1000" disabled={ae} value={gainToSlider(gain)}
    oninput={(e) => (gain = snapGain(gainFromSlider(Number((e.target as HTMLInputElement).value))))} onchange={apply} />
  <input id="gain" type="number" min={limits.gainMin} max={gainTop} step="0.1" disabled={ae} bind:value={gain} onchange={apply} />
</div>
<p class="note" data-testid="gain-split">{splitText(gain)}</p>
<p class="note" data-testid="applied">{applied}</p>
<p class="note" data-testid="limits">Limits in this mode: exposure {fmtLimit(limits.expMin)} to {fmtLimit(limits.expMax)} µs;
  analogue gain {gainSteps ? gainSteps.length <= 12 ? gainSteps.map((g) => `${fmtLimit(g)}x`).join(", ")
    : `${fmtLimit(gainSteps[0])} to ${fmtLimit(gainSteps[gainSteps.length - 1])} in ${gainSteps.length} steps` : gainFixed ? `fixed at ${fmtLimit(limits.gainMin)}` : `${fmtLimit(limits.gainMin)} to ${fmtLimit(limits.gainMax)}`},
  then digital gain up to {DIGITAL_MAX}x more ({fmtLimit(gainTop)}x in total). libcamera fills the analogue gain
  first; the digital gain is applied in software by the ISP to the preview and JPEG only (raw frames, DNG/TIFF and
  noise figures are not scaled by it).</p>

<div class="row">
  <span></span>
  <button onclick={apply}>Apply</button>
  <label class="inline"><input type="checkbox" bind:checked={remember} /> keep after restart</label>
</div>

<div class="msg" class:error data-testid="controls-msg">{msg}</div>
<p class="note">With auto exposure off, slider and field changes apply when released.
  <button class="link" onclick={forget}>Forget kept controls</button></p>

<WhiteBalance {remember} />

<details>
  <summary>Advanced controls (libcamera)</summary>
  <AllControls />
</details>

<details>
  <summary>Tuning file</summary>
  <TuningFile />
</details>

<details bind:open={modelOpen}>
  <summary>Camera model (dtoverlay)</summary>
  <CameraModel />
</details>
