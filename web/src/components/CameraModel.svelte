<script lang="ts">
  // The camera model: the sensor overlay (dtoverlay=) in config.txt, with its connector and the
  // mono option. Works without a camera, so a wrong model can be fixed; applies after a reboot.
  import { api, type CameraOverlay } from "../lib/api";

  let status = $state<CameraOverlay | null>(null);
  let overlay = $state(""), port = $state<"cam0" | "cam1">("cam1"), mono = $state(false);
  let busy = $state(false);
  let saved = $state(false);   // saved in this page: a reboot is due even if the check cannot tell
  let msg = $state(""), error = $state(false);

  function say(text: string, isError = false) { msg = text; error = isError; }

  function take(s: CameraOverlay) {
    status = s;
    if (!s.current) return;
    overlay = s.current.overlay ?? "";
    port = s.current.port;
    mono = s.current.mono;
  }

  const changed = $derived(!!status?.current && (overlay !== (status.current.overlay ?? "")
    || port !== status.current.port || mono !== status.current.mono));

  async function save() {
    busy = true;
    try {
      take(await api.setCameraOverlay(overlay, port, mono));
      saved = true;
      say(`Saved: ${status?.current?.line}. Reboot to use it.`);
    } catch (e) { say((e as Error).message, true); }
    busy = false;
  }

  async function reboot() {
    if (!confirm("Reboot the Raspberry Pi now?")) return;
    try { await api.reset("reboot"); say("Rebooting... the page reconnects when the Pi is back."); }
    catch (e) { say((e as Error).message, true); }
  }

  $effect(() => { api.cameraOverlay().then(take).catch((e) => say(e.message, true)); });
</script>

{#if status && !status.current}
  <p class="note">No /boot/firmware/config.txt on this system.</p>
{:else if status?.current}
  <div class="row">
    <label for="overlay">Sensor overlay</label>
    <select id="overlay" bind:value={overlay} disabled={busy}>
      {#if !status.current.overlay}<option value="">(none: auto-detect)</option>{/if}
      {#each status.overlays as o}<option value={o}>{o}</option>{/each}
    </select>
  </div>
  <div class="row">
    <label for="port">Connector</label>
    <select id="port" bind:value={port} disabled={busy}>
      <option value="cam1">CAM1 (default)</option>
      <option value="cam0">CAM0</option>
    </select>
  </div>
  <div class="row">
    <label for="mono">Mono sensor</label>
    <input id="mono" type="checkbox" bind:checked={mono} disabled={busy} />
  </div>
  <div class="row">
    <span></span>
    <button onclick={save} disabled={busy || !overlay || !changed}>Save</button>
    {#if status.reboot_pending || saved}<button onclick={reboot}>Reboot now</button>{/if}
  </div>
  <div class="msg" class:error data-testid="overlay-msg">{msg}</div>
  <p class="note">In config.txt: <code>{status.current.line ?? "no camera overlay"}</code>
    {#if status.reboot_pending} · changed since the last boot: reboot to use it{/if}
    {#if status.current.camera_auto_detect} · camera_auto_detect is on, so official Raspberry Pi cameras are also detected by themselves{/if}.
    Mono only applies to sensors whose overlay has that option.</p>
{/if}
