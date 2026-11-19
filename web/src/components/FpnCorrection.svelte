<script lang="ts">
  // libcamera's FPN (dark frame) correction on or off, and its calibration; only shown when the service
  // has it set up.
  import { api, type Fpn } from "../lib/api";
  import { reloadInfo } from "../lib/live.svelte";

  const MIN_FRAMES = 10;
  let fpn = $state<Fpn | null>(null);
  let busy = $state(false);
  let frames = $state(16);
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
      fpn = await api.setFpn(enabled);
      return `FPN correction ${fpn.enabled ? "on" : "off"}`;
    });
  }

  function calibrate() {
    const n = Math.max(MIN_FRAMES, Math.round(frames));
    run(`Calibrating: ${n} electrical black frames per gain...`, async () => {
      const c = await api.calibrateFpn(n);
      fpn = c;
      const lines = c.maps.map((m) => `gain ${m.gain}: column FPN ${m.column_fpn} (16-bit DN)`);
      return `New maps (${c.frames} frames at ${(c.exposure_us / 1000).toFixed(2)} ms):\n${lines.join("\n")}`;
    });
  }

  $effect(() => { api.fpn().then((f) => (fpn = f)).catch(() => {}); });
</script>

{#if fpn?.available}
  <div class="row">
    <label for="fpn">FPN correction</label>
    <input id="fpn" type="checkbox" checked={fpn.enabled} disabled={busy} onchange={toggle} />
  </div>
  {#if fpn.can_calibrate}
    <div class="row">
      <label for="fpn-frames">FPN calibration</label>
      <input id="fpn-frames" type="number" min={MIN_FRAMES} max="256" bind:value={frames} disabled={busy}
        style="width: 5em" title="Frames averaged per gain" />
      <button onclick={calibrate} disabled={busy}>Calibrate</button>
    </div>
  {/if}
  <div class="msg" class:error data-testid="fpn-msg">{msg}</div>
  <p class="note">Subtracts the dark frame of the sensor from the raw frames. Switching restarts the stream
    (the exposure and gain you set are kept).
    {#if fpn.can_calibrate}Calibrate captures new dark frames at every gain and the current exposure with the
      sensor's electrical black readout, so the lens can stay open.{/if}</p>
{/if}
