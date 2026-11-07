<script lang="ts">
  import { api } from "../lib/api";
  import { live } from "../lib/live.svelte";

  const h = $derived(live.health);
  async function reset(action: "camera" | "reboot") {
    if (action === "reboot" && !confirm("Reboot the Raspberry Pi? The page reconnects when it is back.")) return;
    try { await api.reset(action); } catch { /* the service is restarting */ }
  }
</script>

{#if !live.connected && live.error}
  <div class="banner recovering">Waiting for the camera service: {live.error}</div>
{:else if h && h.state !== "streaming"}
  <div class="banner {h.state}" data-testid="health">
    <b>{h.state}</b>: {h.message}
    {#if h.kernel.length}<br /><small>kernel: {h.kernel[h.kernel.length - 1]}</small>{/if}
    {#if h.state === "failed"}
      <button onclick={() => reset("camera")}>Reset camera</button>
      <button onclick={() => reset("reboot")}>Reboot Pi</button>
    {/if}
  </div>
{/if}

<style>
  .banner { padding: 6px 10px; margin-bottom: 6px; border-radius: 4px; background: #4a4020; border: 1px solid #c8a030; }
  .banner.failed { background: #4a2020; border-color: #ff7070; }
  button { margin-left: 8px; }
</style>
