<script lang="ts">
  // libcamera's FPN (dark frame) correction on or off; only shown when the service has it set up.
  import { api, type Fpn } from "../lib/api";
  import { reloadInfo } from "../lib/live.svelte";

  let fpn = $state<Fpn | null>(null);
  let busy = $state(false);
  let msg = $state(""), error = $state(false);

  async function toggle(e: Event) {
    const enabled = (e.target as HTMLInputElement).checked;
    busy = true; error = false;
    msg = "Configuring the camera...";
    try {
      fpn = await api.setFpn(enabled);
      await reloadInfo();
      msg = `FPN correction ${fpn.enabled ? "on" : "off"}`;
    } catch (err) {
      msg = (err as Error).message; error = true;
      fpn = await api.fpn().catch(() => fpn);
    }
    busy = false;
  }

  $effect(() => { api.fpn().then((f) => (fpn = f)).catch(() => {}); });
</script>

{#if fpn?.available}
  <div class="row">
    <label for="fpn">FPN correction</label>
    <input id="fpn" type="checkbox" checked={fpn.enabled} disabled={busy} onchange={toggle} />
  </div>
  <div class="msg" class:error data-testid="fpn-msg">{msg}</div>
  <p class="note">Subtracts the dark frame of the sensor from the raw frames. Switching restarts the stream
    (the exposure and gain you set are kept).</p>
{/if}
