<script lang="ts">
  // The live raw histogram, and the ISP's own statistics (Raspberry Pi 5) when switched on.
  import { api, type Histogram, type IspStats } from "../lib/api";
  import HistogramPlot from "../components/HistogramPlot.svelte";
  import Heatmap from "../components/Heatmap.svelte";

  let raw = $state<Histogram | null>(null);
  let isp = $state<IspStats | null>(null);
  let log = $state(true);
  let error = $state("");

  async function refresh() {
    try {
      raw = await api.histogram();
      isp = await api.ispStats();
      error = "";
    } catch (e) { error = (e as Error).message; }
  }

  async function toggleIsp(e: Event) {
    const on = (e.target as HTMLInputElement).checked;
    try { await api.enableIspStats(on); await refresh(); } catch (err) { error = (err as Error).message; }
  }

  $effect(() => {
    refresh();
    const timer = setInterval(refresh, 400);
    return () => clearInterval(timer);
  });
</script>

<h3>Raw histogram</h3>
{#if raw?.channels && raw.bits !== undefined}
  <HistogramPlot channels={raw.channels} fullScale={1 << raw.bits} {log} />
  <div class="msg" data-testid="hist-info">
    {raw.bits}-bit: mean {raw.mean?.toFixed(1)}, min {raw.min}, max {raw.max} DN
  </div>
{:else}
  <div class="msg">{raw?.error ?? ""}</div>
{/if}
<label class="inline"><input type="checkbox" bind:checked={log} /> logarithmic counts</label>

<h3>ISP statistics</h3>
<label class="inline">
  <input type="checkbox" checked={isp?.enabled ?? false} onchange={toggleIsp} data-testid="isp-enable" /> on
</label>
{#if isp?.histogram && isp.zones_mean && isp.focus}
  <HistogramPlot channels={{ Y: isp.histogram }} fullScale={isp.histogram.length} {log} xLabel="bin" />
  <div class="maps">
    <Heatmap rows={isp.zones_mean} title="Zone means 32x32" />
    <Heatmap rows={isp.focus} title="Focus 8x8" />
  </div>
  <div class="msg" data-testid="isp-msg">{isp.count} statistics frames received</div>
{:else if isp?.enabled}
  <div class="msg" data-testid="isp-msg">{isp.error}</div>
{/if}

<div class="msg error">{error}</div>

<style>
  .maps { display: flex; gap: 14px; margin-top: 8px; }
</style>
