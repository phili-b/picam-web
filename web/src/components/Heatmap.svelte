<script lang="ts">
  // A small 2D array as a grey image, scaled to its maximum.
  let { rows, title }: { rows: number[][]; title: string } = $props();
  let canvas: HTMLCanvasElement;

  $effect(() => {
    const h = rows.length, w = rows[0]?.length ?? 0;
    if (!w) return;
    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext("2d")!, img = ctx.createImageData(w, h);
    const top = Math.max(...rows.flat(), 1e-9);
    rows.flat().forEach((v, i) => {
      const g = Math.round((v / top) * 255);
      img.data.set([g, g, g, 255], i * 4);
    });
    ctx.putImageData(img, 0, 0);
  });
</script>

<figure>
  <canvas bind:this={canvas}></canvas>
  <figcaption>{title}</figcaption>
</figure>

<style>
  figure { margin: 0; }
  canvas { width: 180px; height: 180px; image-rendering: pixelated; background: #141614; }
  figcaption { color: var(--grey); font-size: 12px; }
</style>
