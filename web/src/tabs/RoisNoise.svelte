<script lang="ts">
  // ROIs (raw pixels) with their live means, and the noise measurement for the full frame or a ROI.
  import { api, type Noise, type Roi } from "../lib/api";
  import { live } from "../lib/live.svelte";

  // The table edits its own copy, taken again when ROIs are added or removed elsewhere (the preview)
  let rows = $state<Roi[]>([]);
  $effect(() => {
    if (live.rois.length !== rows.length) rows = live.rois.map((r) => ({ ...r }));
  });
  let roiMsg = $state(""), roiError = $state(false);

  async function save(next: Roi[]) {
    try {
      const saved = await api.setRois(next);
      live.rois = saved;
      rows = saved.map((r) => ({ ...r }));
      roiMsg = ""; roiError = false;
    } catch (e) { roiMsg = (e as Error).message; roiError = true; }
  }

  function add() {
    const [w, h] = live.info?.raw.size ?? [640, 480];
    const s = Math.max(16, Math.floor(Math.min(w, h) / 8));
    // New ROIs go along the diagonal from the centre, so they do not cover each other
    const step = (rows.length % 4) * s;
    const x = Math.min(w - s, Math.floor((w - s) / 2) + step), y = Math.min(h - s, Math.floor((h - s) / 2) + step);
    save([...rows, { name: `ROI${rows.length + 1}`, x, y, w: s, h: s }]);
  }

  // Noise
  let frames = $state(16);
  let roiIndex = $state(-1);   // -1 = full frame
  let result = $state<Noise | null>(null);
  let running = $state(false);
  let noiseMsg = $state(""), noiseError = $state(false);

  const FIGURES: [keyof Noise, string][] = [
    ["mean", "Mean"], ["temporal_noise", "Temporal noise"], ["fpn", "Total FPN"], ["row_fpn", "Row FPN"],
    ["col_fpn", "Column FPN"], ["row_temporal_noise", "Row temporal noise"], ["col_temporal_noise", "Column temporal noise"],
    ["min", "Min"], ["max", "Max"],
  ];
  const fmt = (v: unknown) => (typeof v === "number" ? v.toFixed(3) : "-");

  async function measure() {
    const r = live.rois[roiIndex];
    running = true; noiseError = false; noiseMsg = `Capturing ${frames} frames...`;
    try {
      result = await api.noise(Math.max(1, Math.round(frames)), r ? [r.x, r.y, r.w, r.h] : null);
      noiseMsg = `${result.frames} frames, ${result.bit_depth}-bit, ${result.pixels} pixels` +
        (r ? ` in ${r.name}` : ", full frame");
    } catch (e) { noiseMsg = (e as Error).message; noiseError = true; }
    running = false;
  }
</script>

<h3>ROIs</h3>
<table>
  <thead><tr><th>Name</th><th>x</th><th>y</th><th>w</th><th>h</th><th class="num">Mean [DN]</th><th></th></tr></thead>
  <tbody>
    {#each rows as r, i}
      <tr>
        <td><input bind:value={r.name} class="name" /></td>
        <td><input type="number" min="0" bind:value={r.x} /></td>
        <td><input type="number" min="0" bind:value={r.y} /></td>
        <td><input type="number" min="1" bind:value={r.w} /></td>
        <td><input type="number" min="1" bind:value={r.h} /></td>
        <td class="num">{live.rois[i]?.mean?.toFixed(1) ?? "-"}</td>
        <td><button title="Remove" onclick={() => save(rows.filter((_, j) => j !== i))}>✕</button></td>
      </tr>
    {:else}
      <tr><td colspan="7" class="note">No ROIs. Add one, or Shift+drag on the preview.</td></tr>
    {/each}
  </tbody>
</table>
<button onclick={add}>Add</button>
<button onclick={() => save(rows)} disabled={!rows.length}>Apply edits</button>
<div class="msg" class:error={roiError}>{roiMsg}</div>

<h3>Noise</h3>
<div class="row">
  <label for="nf">Frames</label>
  <input id="nf" type="number" min="1" max="1000" bind:value={frames} />
</div>
<div class="row">
  <label for="nr">Area</label>
  <select id="nr" bind:value={roiIndex}>
    <option value={-1}>full frame</option>
    {#each live.rois as r, i}<option value={i}>{r.name} ({r.x}, {r.y}, {r.w}x{r.h})</option>{/each}
  </select>
</div>
<div class="row"><span></span><button onclick={measure} disabled={running}>Measure</button></div>
<div class="msg" class:error={noiseError} data-testid="noise-msg">{noiseMsg}</div>
{#if result}
  <table><tbody>
    {#each FIGURES as [key, label]}
      <tr><th>{label} [DN]</th><td class="num">{fmt(result[key])}</td></tr>
    {/each}
  </tbody></table>
{/if}

<style>
  td input { width: 64px; padding: 2px 4px; }
  td input.name { width: 90px; }
</style>
