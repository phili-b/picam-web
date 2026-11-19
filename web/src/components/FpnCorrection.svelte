<script lang="ts">
  // libcamera's FPN (dark frame) correction: on or off, column or full frame, and its calibration; only
  // shown when the service has it set up.
  import { api, type Fpn, type FpnCalibration } from "../lib/api";
  import { reloadInfo } from "../lib/live.svelte";

  const MIN_FRAMES = 10;
  let fpn = $state<Fpn | null>(null);
  let busy = $state(false);
  let frames = $state(16);
  let electricalBlack = $state(true);
  let msg = $state(""), error = $state(false);

  async function run(start: string, action: () => Promise<string>) {
    busy = true; error = false;
    msg = start;
    try {
      msg = await action();
      await reloadInfo();
    } catch (err) {
      msg = (err as Error).message; error = true;
      fpn = await api.fpn().catch(() => fpn);
    }
    busy = false;
  }

  function toggle(e: Event) {
    const enabled = (e.target as HTMLInputElement).checked;
    run("Configuring the camera...", async () => {
      fpn = await api.setFpn({ enabled });
      return `FPN correction ${fpn.enabled ? "on" : "off"}`;
    });
  }

  function setMode(e: Event) {
    const mode = (e.target as HTMLSelectElement).value as Fpn["mode"];
    run("Configuring the camera...", async () => {
      fpn = await api.setFpn({ mode });
      return `FPN correction: ${fpn.mode === "full" ? "full frame" : "column"}`;
    });
  }

  function calibrate() {
    const n = Math.max(MIN_FRAMES, Math.round(frames));
    run(`Calibrating: ${n} ${electricalBlack ? "electrical black" : "dark"} frames per gain...`, async () => {
      fpn = await api.calibrateFpn(n, electricalBlack);
      return "";
    });
  }

  // The last calibration of the service (also the automatic one at start)
  function describe(c: FpnCalibration | null | undefined) {
    if (!c) return "";
    const when = new Date(c.time * 1000).toLocaleTimeString();
    if (c.error) return `${c.auto ? "Automatic calibration at start" : "Calibration"} failed (${when}): ${c.error}`;
    const lines = c.maps.map((m) => `gain ${m.gain}: column FPN ${m.column_fpn} (16-bit DN)`);
    return `${c.auto ? "Calibrated automatically at start" : "Calibrated"} ${when}, ${c.source}, ${c.frames} frames at `
      + `${(c.exposure_us / 1000).toFixed(2)} ms:\n${lines.join("\n")}`;
  }

  $effect(() => { api.fpn().then((f) => (fpn = f)).catch(() => {}); });
</script>

{#if fpn?.available}
  <div class="row">
    <label for="fpn">FPN correction</label>
    <input id="fpn" type="checkbox" checked={fpn.enabled} disabled={busy} onchange={toggle} />
    <select id="fpn-mode" value={fpn.mode} disabled={busy} onchange={setMode} title="What is subtracted">
      <option value="column">column</option>
      <option value="full">full frame</option>
    </select>
  </div>
  {#if fpn.can_calibrate}
    <div class="row">
      <label for="fpn-frames">FPN calibration</label>
      <input id="fpn-frames" type="number" min={MIN_FRAMES} max="256" bind:value={frames} disabled={busy}
        style="width: 5em" title="Frames averaged per gain" />
      <button onclick={calibrate} disabled={busy}>Calibrate</button>
      <label class="inline"><input type="checkbox" bind:checked={electricalBlack} disabled={busy} /> electrical black</label>
    </div>
  {/if}
  <div class="msg" class:error data-testid="fpn-msg">{msg}</div>
  <div class="msg" data-testid="fpn-last">{describe(fpn.last_calibration)}</div>
  <p class="note">Subtracts the dark frame of the sensor from the image going to the ISP (raw captures are
    not corrected): only its column pattern, or the full frame. Switching restarts the stream (the exposure
    and gain you set are kept).
    {#if fpn.can_calibrate}The service calibrates at every start. Calibrate captures new dark frames at every
      gain and the current exposure; with electrical black the sensor reads its pixels without their charge, so
      the lens can stay open, but these maps hold the column pattern only. For the full frame mode switch the
      light off (or cover the lens) and calibrate without electrical black.{/if}</p>
{/if}
