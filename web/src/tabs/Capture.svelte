<script lang="ts">
  // Downloads to the browser's download folder. Fetched first, so an error shows here instead of
  // opening an error page.
  import { errorText } from "../lib/api";

  let frames = $state(10);
  let busy = $state(false);
  let msg = $state(""), error = $state(false);

  async function download(url: string, fallbackName: string) {
    busy = true; error = false; msg = "Capturing...";
    try {
      const r = await fetch(url);
      if (!r.ok) throw new Error(errorText(await r.json().catch(() => null), r.statusText));
      const blob = await r.blob();
      const name = r.headers.get("content-disposition")?.match(/filename="?([^";]+)"?/)?.[1] ?? fallbackName;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 10000);
      msg = `Saved ${name} (${(blob.size / 1e6).toFixed(1)} MB)`;
    } catch (e) { msg = (e as Error).message; error = true; }
    busy = false;
  }
</script>

<h3>Raw frames, in DN</h3>
<div class="row">
  <label for="frames">Frames</label>
  <input id="frames" type="number" min="1" max="1000" bind:value={frames} />
  <button disabled={busy} onclick={() => download(`/api/capture/raw?format=npz&count=${Math.max(1, Math.round(frames))}`, "raw.npz")}>
    Download .npz</button>
</div>
<p class="note">numpy archive: frames (N x H x W, uint16) and the metadata of each frame.</p>

<h3>One frame</h3>
<div class="buttons">
  <button disabled={busy} onclick={() => download("/api/capture/raw?format=tiff", "frame.tiff")}>Raw .tiff (16-bit, DN)</button>
  <button disabled={busy} onclick={() => download("/api/capture/raw?format=dng", "frame.dng")}>Raw .dng</button>
  <button disabled={busy} onclick={() => download("/api/snapshot.jpg", "snapshot.jpg")}>Preview .jpg</button>
</div>

<div class="msg" class:error data-testid="capture-msg">{msg}</div>
<p class="note">From Python: <code>picam_client.Camera</code>, see the examples folder.</p>

<style>
  .buttons { display: flex; gap: 6px; flex-wrap: wrap; }
</style>
