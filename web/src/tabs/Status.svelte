<script lang="ts">
  // Health and recovery, frame counters, camera properties and the latest metadata.
  import { api, reloadWhenRestarted } from "../lib/api";
  import { live } from "../lib/live.svelte";

  const CFA: Record<number, string> = { 0: "RGGB", 1: "GRBG", 2: "GBRG", 3: "BGGR", 4: "RGB", 5: "mono" };
  let metadata = $state("");
  let msg = $state(""), error = $state(false);

  async function reset(action: "stream" | "camera" | "reboot") {
    if (action === "reboot" && !confirm("Reboot the Raspberry Pi? The page reconnects when it is back.")) return;
    const before = live.health?.instance;
    error = false;
    msg = { stream: "Restarting the stream...", camera: "Reopening the camera...", reboot: "Rebooting..." }[action];
    try {
      await api.reset(action);
      if (action !== "stream") await reloadWhenRestarted(before, action === "reboot" ? 180000 : 60000);
      else msg = "";
    } catch (e) { msg = (e as Error).message; error = true; }
  }

  async function setAutoReboot(e: Event) {
    try { await api.setAutoReboot((e.target as HTMLInputElement).checked); }
    catch (err) { msg = (err as Error).message; error = true; }
  }

  async function resetFrames() {
    try { live.frames = await api.resetFrames(); } catch (e) { msg = (e as Error).message; error = true; }
  }

  async function loadMetadata() {
    try { metadata = JSON.stringify(await api.metadata(), null, 1); } catch (e) { metadata = (e as Error).message; }
  }

  const h = $derived(live.health);
  const f = $derived(live.frames);
  const info = $derived(live.info);
  const p = $derived(info?.properties ?? {});
  const size = (s?: number[]) => (s ? s.join("x") : "-");
</script>

<h3>Health</h3>
{#if h}
  <div class="msg"><b>{h.state}</b>: {h.message}</div>
{/if}
<div class="buttons">
  <button onclick={() => reset("stream")} title="Stop and start the stream (about 1 s)">Restart stream</button>
  <button onclick={() => reset("camera")} title="Reopen the camera in a new service process (about 5 s)">Reset camera</button>
  <button onclick={() => reset("reboot")} title="Power-cycles the sensor">Reboot Pi</button>
</div>
<label class="inline">
  <input type="checkbox" checked={h?.auto_reboot ?? false} onchange={setAutoReboot} />
  Reboot automatically when the camera cannot be recovered
</label>
<div class="msg" class:error>{msg}</div>
{#if h?.history.length}
  <details>
    <summary>History{h.kernel.length ? " and kernel warnings" : ""}</summary>
    <pre>{[...h.history].reverse().map((x) => x.join(" ")).join("\n")}{h.kernel.length ? "\n\nKernel:\n" + h.kernel.join("\n") : ""}</pre>
  </details>
{/if}

<h3>Frames</h3>
{#if f}
  <table data-testid="frames-table"><tbody>
    <tr><th>Received</th><td class="num">{f.frames}</td></tr>
    <tr><th>Dropped</th><td class="num">{f.dropped}</td></tr>
    <tr><th>Measured fps</th><td class="num">{f.fps.toFixed(2)}</td></tr>
    <tr><th>Expected fps</th><td class="num">{f.expected_fps.toFixed(2)}</td></tr>
    <tr><th>Last / max gap</th><td class="num">{f.last_gap_ms.toFixed(2)} / {f.max_gap_ms.toFixed(2)} ms</td></tr>
  </tbody></table>
{/if}
<button onclick={resetFrames}>Reset counters</button>
<p class="note">Drops are gaps in SensorTimestamp longer than 1.5 frame durations.</p>

<h3>Camera</h3>
{#if info}
  <table><tbody>
    <tr><th>Model</th><td>{p.Model}</td></tr>
    <tr><th>Sensor (I2C)</th><td>{info.sensor ?? "-"}</td></tr>
    <tr><th>Pipeline</th><td>{p.PipelineHandler}</td></tr>
    <tr><th>Pixel array</th><td>{size(p.PixelArraySize as number[])}</td></tr>
    <tr><th>Unit cell</th><td>{p.UnitCellSize ? (p.UnitCellSize as number[]).join(" x ") + " nm" : "-"}</td></tr>
    <tr><th>Colour filter</th><td>{CFA[p.ColorFilterArrangement as number] ?? "-"}</td></tr>
    <tr><th>Raw stream</th><td>{info.raw.format} {size(info.raw.size)}, stride {info.raw.stride}</td></tr>
    <tr><th>Preview stream</th><td>{info.main.format} {size(info.main.size)}</td></tr>
    <tr><th>Tuning file</th><td>{info.tuning_file ?? "default"}</td></tr>
    <tr><th>Service</th><td>version {info.version}</td></tr>
  </tbody></table>
  <details>
    <summary>Sensor modes</summary>
    <table><tbody>
      <tr><th>Format</th><th>Size</th><th>Bits</th><th>Max fps</th></tr>
      {#each info.sensor_modes as m}
        <tr><td>{m.unpacked}</td><td>{size(m.size)}</td><td>{m.bit_depth}</td><td>{m.fps.toFixed(1)}</td></tr>
      {/each}
    </tbody></table>
  </details>
{/if}
<details ontoggle={(e) => (e.target as HTMLDetailsElement).open && loadMetadata()}>
  <summary>Metadata of the latest frame</summary>
  <button onclick={loadMetadata}>Refresh</button>
  <pre>{metadata}</pre>
</details>

<style>
  .buttons { display: flex; gap: 6px; flex-wrap: wrap; margin: 6px 0; }
</style>
