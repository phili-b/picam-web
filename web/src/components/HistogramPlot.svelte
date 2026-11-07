<script lang="ts">
  // A histogram: one line per channel. Drag over the plot to zoom in, double-click to zoom out.
  import uPlot from "uplot";
  import "uplot/dist/uPlot.min.css";

  let { channels, fullScale, log = true, xLabel = "DN" }:
    { channels: Record<string, number[]>; fullScale: number; log?: boolean; xLabel?: string } = $props();

  const COLOURS: Record<string, string> = { R: "#ff5a5a", G: "#9acd56", B: "#50a0ff", Y: "#dcdeda" };

  let el: HTMLDivElement;
  let plot: uPlot | null = null;
  let plotKey = "";   // what the plot was made for: channels, range and scale

  function makePlot(names: string[]) {
    plot?.destroy();
    plot = new uPlot({
      width: el.clientWidth || 400,
      height: 220,
      scales: { x: { time: false, range: [0, fullScale] }, y: log ? { distr: 3 } : {} },
      axes: [
        { stroke: "#91969d", grid: { stroke: "#2f322f" }, label: xLabel },
        { stroke: "#91969d", grid: { stroke: "#2f322f" }, size: 60 },
      ],
      series: [{ label: xLabel }, ...names.map((n) => ({ label: n, stroke: COLOURS[n] ?? "#dcdeda", width: 1.5, points: { show: false } }))],
    }, [[]], el);
  }

  $effect(() => {
    const names = Object.keys(channels);
    if (!names.length) return;
    const key = `${names}|${fullScale}|${log}`;
    if (key !== plotKey) { makePlot(names); plotKey = key; }
    const bins = channels[names[0]].length;
    const x = Array.from({ length: bins }, (_, i) => (i + 0.5) * fullScale / bins);
    // A log scale cannot show 0: empty bins are left out
    const ys = names.map((n) => channels[n].map((c) => (log && c === 0 ? null : c)));
    plot!.setData([x, ...ys] as uPlot.AlignedData);
  });

  $effect(() => {
    const resize = new ResizeObserver(() => plot?.setSize({ width: el.clientWidth, height: 220 }));
    resize.observe(el);
    return () => { resize.disconnect(); plot?.destroy(); plot = null; plotKey = ""; };
  });
</script>

<div class="plot" bind:this={el}></div>

<style>
  .plot { width: 100%; min-height: 220px; }
  .plot :global(.u-legend) { color: var(--text); font-size: 12px; }
</style>
