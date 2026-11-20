<script lang="ts">
  // Preview (MJPEG) quality: standard, high or max. The service stores the choice and configures the
  // camera again (the stream size can change); the controls set are kept.
  import { api, type PreviewQuality } from "../lib/api";
  import { reloadInfo } from "../lib/live.svelte";

  let preview = $state<PreviewQuality | null>(null);
  let busy = $state(false);
  let msg = $state(""), error = $state(false);

  function describe(name: string) {
    const q = preview?.qualities[name];
    if (!q) return name;
    const sub = q.subsampling.split("").join(":");
    return `${name}: ${q.width ? `${q.width} px` : "full width"}, JPEG ${q.q}, ${sub}`;
  }

  async function choose(e: Event) {
    const quality = (e.target as HTMLSelectElement).value;
    busy = true; error = false;
    msg = "Configuring the camera...";
    try {
      preview = await api.setPreview(quality);
      msg = "";
      await reloadInfo();
    } catch (err) {
      msg = (err as Error).message; error = true;
      preview = await api.preview().catch(() => preview);
    }
    busy = false;
  }

  $effect(() => { api.preview().then((p) => (preview = p)).catch(() => {}); });
</script>

{#if preview}
  <div class="row">
    <label for="preview-quality">Preview quality</label>
    <select id="preview-quality" value={preview.quality} disabled={busy} onchange={choose}>
      {#each Object.keys(preview.qualities) as name}
        <option value={name}>{describe(name)}</option>
      {/each}
    </select>
  </div>
  <div class="msg" class:error data-testid="preview-msg">{msg}</div>
  <p class="note">Only the live preview and snapshots: raw captures are never compressed. Higher quality
    costs network bandwidth, more so in a noisy (dark, high gain) scene: at 30 fps about 40 Mbit/s for
    standard, 100 for high and 150 for max. Use standard over Wi-Fi or a VPN.</p>
{/if}
