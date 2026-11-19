<script lang="ts">
  // White balance: automatic for a chosen illuminant, or by hand with red and blue gains. Shown only for colour cameras (mono cameras have no AWB controls).
  import { api } from "../lib/api";

  let { remember = false }: { remember?: boolean } = $props();

  // The AwbMode values, in order; Custom is left out, it needs an extra tuning file entry
  const ILLUMINANTS = ["Auto", "Incandescent", "Tungsten", "Fluorescent", "Indoor", "Daylight", "Cloudy"];
  const GAIN_MIN = 0.1, GAIN_MAX = 8;     // ColourGains allows more, but this is the useful range
  const HOLD_MS = 1500;                   // metadata lags new controls: do not snap the sliders back

  let available = $state(false);
  let auto = $state(true);
  let preset = $state(0);
  let red = $state(1), blue = $state(1);
  let applied = $state("");
  let msg = $state(""), error = $state(false);
  let holdUntil = 0;

  const clamp = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, Number.isFinite(x) ? x : lo));
  const round2 = (x: number) => Math.round(x * 100) / 100;

  async function load() {
    const c = await api.controls();
    available = "AwbEnable" in c && "ColourGains" in c;
    auto = Boolean(c.AwbEnable?.value ?? true);
    preset = Number(c.AwbMode?.value ?? c.AwbMode?.default ?? 0);
  }

  async function send(values: Record<string, unknown>, done: string) {
    holdUntil = Date.now() + HOLD_MS;
    try {
      await api.setControls(values, remember);
      msg = done + (remember ? " (kept after a restart)" : ""); error = false;
    } catch (e) { msg = (e as Error).message; error = true; }
  }

  const applyGains = () => {
    red = clamp(red, GAIN_MIN, GAIN_MAX);
    blue = clamp(blue, GAIN_MIN, GAIN_MAX);
    return send({ AwbEnable: false, ColourGains: [red, blue] }, "Manual gains set");
  };

  // Turning auto off keeps the current gains, so the image does not jump
  const applyAuto = () => (auto ? send({ AwbEnable: true }, "Auto white balance on") : applyGains());

  const applyPreset = () => send({ AwbMode: preset }, "Illuminant set");

  // What the camera applies; with auto on, the fields follow it
  $effect(() => {
    if (!available) return;
    const id = setInterval(async () => {
      try {
        const md = await api.metadata();
        const gains = md.ColourGains as number[] | undefined;
        const k = md.ColourTemperature as number | undefined;
        if (!gains) return;
        applied = `Applied: red ${gains[0].toFixed(2)}x, blue ${gains[1].toFixed(2)}x` + (k ? `, ${Math.round(k)} K` : "");
        if (!auto && Date.now() < holdUntil) return;
        red = round2(gains[0]);
        blue = round2(gains[1]);
      } catch { /* shown by the status line */ }
    }, 500);
    return () => clearInterval(id);
  });

  $effect(() => { load().catch((e) => { msg = e.message; error = true; }); });
</script>

{#if available}
  <details open>
    <summary>White balance</summary>

    <div class="row">
      <label for="awb">Auto white balance</label>
      <input id="awb" type="checkbox" bind:checked={auto} onchange={applyAuto} />
    </div>

    <div class="row">
      <label for="awb-preset">Illuminant</label>
      <select id="awb-preset" disabled={!auto} bind:value={preset} onchange={applyPreset}>
        {#each ILLUMINANTS as name, i}<option value={i}>{name}</option>{/each}
      </select>
    </div>

    <div class="row">
      <label for="wb-red">Red gain</label>
      <input type="range" min={GAIN_MIN} max={GAIN_MAX} step="0.01" disabled={auto} bind:value={red} onchange={applyGains} />
      <input id="wb-red" type="number" min={GAIN_MIN} max={GAIN_MAX} step="0.05" disabled={auto} bind:value={red} onchange={applyGains} />
    </div>
    <div class="row">
      <label for="wb-blue">Blue gain</label>
      <input type="range" min={GAIN_MIN} max={GAIN_MAX} step="0.01" disabled={auto} bind:value={blue} onchange={applyGains} />
      <input id="wb-blue" type="number" min={GAIN_MIN} max={GAIN_MAX} step="0.05" disabled={auto} bind:value={blue} onchange={applyGains} />
    </div>

    <p class="note" data-testid="wb-applied">{applied}</p>
    <p class="note">Auto: the camera estimates the light and sets the gains; Illuminant limits its search to
      that kind of light. Manual: green stays at 1x. Raise red if the image looks cyan, raise blue if it looks yellow.
      White balance is applied in the ISP: raw frames are not changed.</p>
    <div class="msg" class:error data-testid="wb-msg">{msg}</div>
  </details>
{/if}
