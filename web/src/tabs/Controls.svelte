<script lang="ts">
  // Sensor mode, auto exposure, exposure time, analogue and digital gain (sliders and number fields).
  import { api } from "../lib/api";
  import { live, reloadInfo } from "../lib/live.svelte";
  import AllControls from "../components/AllControls.svelte";
  import TuningFile from "../components/TuningFile.svelte";

  let ae = $state(true);
  let exposure = $state(10000);   // us
  let gain = $state(1);
  let digital = $state(1);       // ISP digital gain on top of the analogue gain
  let applied = $state("");
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
    // Some modes report a nonsense gain maximum (an overflowed 1e28): use a sane one then
    if (!Number.isFinite(limits.gainMax) || limits.gainMax > 1000) limits.gainMax = Math.max(16, limits.gainMin);
    exposure = Math.min(limits.expMax, Math.max(limits.expMin, exposure));
    gain = Math.min(limits.gainMax, Math.max(limits.gainMin, gain));
    ae = Boolean(c.AeEnable?.value ?? c.AeEnable?.default ?? true);
  }

  // The gains the camera applies; with auto exposure on, the fields follow the camera
  $effect(() => {
    const auto = ae;
    const id = setInterval(async () => {
      try {
        const md = await api.metadata();
        const a = typeof md.AnalogueGain === "number" ? md.AnalogueGain : null;
        const d = typeof md.DigitalGain === "number" ? md.DigitalGain : null;
        if (a !== null) applied = `Applied: analogue ${a.toFixed(2)}x` + (d !== null ? ` × digital ${d.toFixed(2)}x` : "");
        if (!auto) return;
        if (typeof md.ExposureTime === "number") exposure = md.ExposureTime;
        if (a !== null) gain = Math.round(a * 100) / 100;
        if (d !== null) digital = Math.round(Math.min(DIGITAL_MAX, Math.max(1, d)) * 100) / 100;
      } catch { /* shown by the status line */ }
    }, 500);
    return () => clearInterval(id);
  });

  async function apply() {
    // A typed value outside the limits is brought back into them
    const clamp = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, Number.isFinite(x) ? x : lo));
    exposure = clamp(exposure, limits.expMin, limits.expMax);
    gain = clamp(gain, limits.gainMin, limits.gainMax);
    digital = clamp(digital, 1, DIGITAL_MAX);
    const v: Record<string, unknown> = { AeEnable: ae };
    // libcamera has no digital gain control: a gain above the analogue maximum is applied
    // as digital gain in the ISP, so the total gain is sent
    if (!ae) { v.ExposureTime = Math.round(exposure); v.AnalogueGain = Math.round(gain * digital * 1000) / 1000; }
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
</script>

<div class="row">
  <label for="mode">Sensor mode</label>
  <select id="mode" disabled={switching || !live.info} onchange={setMode} value={live.info?.mode}>
    {#each live.info?.sensor_modes ?? [] as m, i}
      <option value={i}>{m.unpacked} {m.size[0]}x{m.size[1]} {m.bit_depth}-bit {m.fps.toFixed(1)} fps</option>
    {/each}
  </select>
</div>

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
  <label for="gain">Analogue gain</label>
  <input type="range" min={limits.gainMin} max={limits.gainMax} step="0.05" disabled={ae || gainFixed} bind:value={gain} onchange={apply} />
  <input id="gain" type="number" min={limits.gainMin} max={limits.gainMax} step="0.1" disabled={ae || gainFixed} bind:value={gain} onchange={apply} />
</div>
<div class="row">
  <label for="digital">Digital gain</label>
  <input type="range" min="1" max={DIGITAL_MAX} step="0.05" disabled={ae} bind:value={digital} onchange={apply} />
  <input id="digital" type="number" min="1" max={DIGITAL_MAX} step="0.1" disabled={ae} bind:value={digital} onchange={apply} />
</div>
<p class="note" data-testid="applied">{applied}</p>
<p class="note" data-testid="limits">Limits in this mode: exposure {fmtLimit(limits.expMin)} to {fmtLimit(limits.expMax)} µs,
  analogue gain {gainFixed ? `fixed at ${fmtLimit(limits.gainMin)}` : `${fmtLimit(limits.gainMin)} to ${fmtLimit(limits.gainMax)}`},
  digital gain 1 to {DIGITAL_MAX}. libcamera uses analogue gain first, up to the maximum, then digital gain
  (ISP only: raw frames, DNG/TIFF and noise figures are not scaled by it).</p>

<div class="row">
  <span></span>
  <button onclick={apply}>Apply</button>
  <label class="inline"><input type="checkbox" bind:checked={remember} /> keep after restart</label>
</div>

<div class="msg" class:error data-testid="controls-msg">{msg}</div>
<p class="note">With auto exposure off, slider and field changes apply when released.
  <button class="link" onclick={forget}>Forget kept controls</button></p>

<details>
  <summary>All libcamera controls</summary>
  <AllControls />
</details>

<details>
  <summary>Tuning file</summary>
  <TuningFile />
</details>
