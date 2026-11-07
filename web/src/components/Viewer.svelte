<script lang="ts">
  // Live preview on a canvas: wheel to zoom around the cursor, drag to pan, double-click to fit,
  // Shift+drag to draw a ROI. Zoomed in far enough, the raw pixels themselves are drawn (from
  // /api/raw/crop, in DN) with a grid and their values. All drawing happens in one
  // requestAnimationFrame loop outside Svelte's rendering, so mouse moves never re-render the page.
  import { api, type RawCrop } from "../lib/api";
  import { live } from "../lib/live.svelte";

  const RAW_IMAGE_FROM = 6;     // screen px per raw pixel from which the raw crop is drawn
  const GRID_FROM = 14;         // ... the pixel grid
  const VALUES_FROM = 34;       // ... the pixel values
  const MAX_SCREEN_PER_RAW = 96;
  const ROI_COLOURS = ["#9acd56", "#00adfd", "#ffaa00", "#e254ff", "#ff5a5a", "#ffffff"];

  let container: HTMLDivElement;
  let canvas: HTMLCanvasElement;
  let img: HTMLImageElement;
  let streamSrc = $state("/stream.mjpg");
  let readout = $state("");
  let zoomText = $state("fit");
  const coarse = window.matchMedia?.("(pointer: coarse)").matches ?? false;   // touch screen

  // View: preview pixel (u, v) is drawn at screen (ox + u * s, oy + v * s)
  let s = 1, ox = 0, oy = 0, fitted = true;
  let crop: RawCrop | null = null;
  let cropCanvas: HTMLCanvasElement | null = null;
  let drag: { x: number; y: number; mode: "pan" | "roi"; rx: number; ry: number } | null = null;
  let roiDraft: { x: number; y: number; w: number; h: number } | null = null;
  let mouse: { x: number; y: number } | null = null;

  const iw = () => img?.naturalWidth || 1;
  const ih = () => img?.naturalHeight || 1;
  function viewRect(): [number, number, number, number] {
    const v = live.frames?.view;
    if (v) return v;
    const size = live.info?.raw.size ?? [iw(), ih()];
    return [0, 0, size[0], size[1]];
  }
  const rawPerPreview = () => { const v = viewRect(); return (v[2] - v[0]) / iw(); };
  const screenPerRaw = () => s / rawPerPreview();
  function screenToRaw(x: number, y: number): [number, number] {
    const v = viewRect();
    return [v[0] + ((x - ox) / s) * rawPerPreview(), v[1] + ((y - oy) / s) * ((v[3] - v[1]) / ih())];
  }
  function rawToScreen(x: number, y: number): [number, number] {
    const v = viewRect();
    return [ox + ((x - v[0]) / rawPerPreview()) * s, oy + ((y - v[1]) / ((v[3] - v[1]) / ih())) * s];
  }

  function fit() {
    const cw = canvas.width, ch = canvas.height;
    s = Math.min(cw / iw(), ch / ih());
    ox = (cw - iw() * s) / 2;
    oy = (ch - ih() * s) / 2;
    fitted = true;
  }

  function resize() {
    const r = container.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(r.width * dpr));
    canvas.height = Math.max(1, Math.round(r.height * dpr));
    if (fitted) fit();
  }

  function zoomAt(x: number, y: number, factor: number) {
    const minS = Math.min(canvas.width / iw(), canvas.height / ih());
    const maxS = MAX_SCREEN_PER_RAW * rawPerPreview();
    const ns = Math.min(maxS, Math.max(minS, s * factor));
    ox = x - ((x - ox) / s) * ns;
    oy = y - ((y - oy) / s) * ns;
    s = ns;
    fitted = ns <= minS * 1.0001;
    if (fitted) fit();
  }

  const pos = (e: MouseEvent): [number, number] => {
    const r = canvas.getBoundingClientRect(), dpr = canvas.width / r.width;
    return [(e.clientX - r.left) * dpr, (e.clientY - r.top) * dpr];
  };

  function onWheel(e: WheelEvent) {
    e.preventDefault();
    const [x, y] = pos(e);
    zoomAt(x, y, Math.exp(-e.deltaY * 0.0015));
  }

  // Touch: two fingers pinch to zoom around their midpoint and pan with it
  const touches = new Map<number, [number, number]>();
  let pinch: { d: number; mx: number; my: number } | null = null;
  function pinchState() {
    const [[ax, ay], [bx, by]] = [...touches.values()];
    return { d: Math.hypot(bx - ax, by - ay) || 1, mx: (ax + bx) / 2, my: (ay + by) / 2 };
  }

  function onDown(e: PointerEvent) {
    if (e.button !== 0) return;
    try { canvas.setPointerCapture(e.pointerId); } catch { /* pointer already gone */ }
    const [x, y] = pos(e);
    if (e.pointerType === "touch") {
      touches.set(e.pointerId, [x, y]);
      if (touches.size === 2) { pinch = pinchState(); drag = null; roiDraft = null; return; }
      if (touches.size > 2) return;
    }
    const [rx, ry] = screenToRaw(x, y);
    drag = { x, y, mode: e.shiftKey ? "roi" : "pan", rx, ry };
  }

  function onMove(e: PointerEvent) {
    const [x, y] = pos(e);
    if (e.pointerType === "touch" && touches.has(e.pointerId)) {
      touches.set(e.pointerId, [x, y]);
      if (pinch && touches.size >= 2) {
        const p = pinchState();
        ox += p.mx - pinch.mx; oy += p.my - pinch.my;
        fitted = false;
        zoomAt(p.mx, p.my, p.d / pinch.d);
        pinch = p;
        return;
      }
    }
    mouse = { x, y };
    if (drag?.mode === "pan") {
      ox += x - drag.x; oy += y - drag.y;
      drag.x = x; drag.y = y;
      fitted = false;
    } else if (drag?.mode === "roi") {
      const [rx, ry] = screenToRaw(x, y);
      roiDraft = {
        x: Math.round(Math.min(rx, drag.rx)), y: Math.round(Math.min(ry, drag.ry)),
        w: Math.round(Math.abs(rx - drag.rx)), h: Math.round(Math.abs(ry - drag.ry)),
      };
    }
  }

  async function onUp(e: PointerEvent) {
    if (e.pointerType === "touch") {
      touches.delete(e.pointerId);
      if (pinch) {
        // End of a pinch: the finger left on the screen pans on from where it is
        pinch = null;
        const rest = [...touches.values()][0];
        drag = rest ? { x: rest[0], y: rest[1], mode: "pan", rx: 0, ry: 0 } : null;
        return;
      }
    }
    const draft = roiDraft;
    drag = null;
    roiDraft = null;
    if (draft && draft.w >= 2 && draft.h >= 2) {
      const raw = live.info?.raw.size ?? [Infinity, Infinity];
      const r = { name: `ROI${live.rois.length + 1}`, x: Math.max(0, draft.x), y: Math.max(0, draft.y), w: draft.w, h: draft.h };
      if (r.x < raw[0] && r.y < raw[1]) {
        try { live.rois = await api.setRois([...live.rois, r]); } catch (e) { readout = (e as Error).message; }
      }
    }
  }

  // Raw crop of the visible area, a few times a second while zoomed in
  async function fetchCrop() {
    if (!canvas || !live.info || screenPerRaw() < RAW_IMAGE_FROM) { crop = null; return; }
    const [x0, y0] = screenToRaw(0, 0), [x1, y1] = screenToRaw(canvas.width, canvas.height);
    const [rw, rh] = live.info.raw.size;
    const x = Math.max(0, Math.floor(x0)), y = Math.max(0, Math.floor(y0));
    const w = Math.min(rw, Math.ceil(x1) + 1) - x, h = Math.min(rh, Math.ceil(y1) + 1) - y;
    if (w < 1 || h < 1 || w > 128 || h > 128) { crop = null; return; }
    try {
      const c = await api.rawCrop(x, y, w, h);
      // Grey image of the raw values (gamma 1/2.2 to look like the preview), drawn without smoothing
      const full = (1 << c.bits) - 1;
      const cc = cropCanvas ?? document.createElement("canvas");
      cc.width = c.w; cc.height = c.h;
      const ctx = cc.getContext("2d")!, data = ctx.createImageData(c.w, c.h);
      c.values.forEach((v, i) => {
        const g = Math.round(255 * Math.pow(Math.min(1, v / full), 1 / 2.2));
        data.data[4 * i] = data.data[4 * i + 1] = data.data[4 * i + 2] = g;
        data.data[4 * i + 3] = 255;
      });
      ctx.putImageData(data, 0, 0);
      cropCanvas = cc;
      crop = c;
    } catch { crop = null; }
  }

  function draw() {
    const ctx = canvas.getContext("2d")!;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const spr = screenPerRaw();
    ctx.imageSmoothingEnabled = spr < 3;
    if (img.complete && img.naturalWidth) ctx.drawImage(img, ox, oy, iw() * s, ih() * s);

    if (crop && cropCanvas && spr >= RAW_IMAGE_FROM) {
      const [sx, sy] = rawToScreen(crop.x, crop.y);
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(cropCanvas, sx, sy, crop.w * spr, crop.h * spr);
      if (spr >= GRID_FROM) {
        ctx.strokeStyle = "rgba(0,0,0,0.35)"; ctx.lineWidth = 1;
        ctx.beginPath();
        for (let i = 0; i <= crop.w; i++) { const x = Math.round(sx + i * spr) + 0.5; ctx.moveTo(x, sy); ctx.lineTo(x, sy + crop.h * spr); }
        for (let j = 0; j <= crop.h; j++) { const y = Math.round(sy + j * spr) + 0.5; ctx.moveTo(sx, y); ctx.lineTo(sx + crop.w * spr, y); }
        ctx.stroke();
      }
      if (spr >= VALUES_FROM) {
        ctx.font = `${Math.min(16, spr / 3.2)}px sans-serif`;
        ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.lineWidth = 3; ctx.strokeStyle = "rgba(0,0,0,0.8)"; ctx.fillStyle = "#fff";
        for (let j = 0; j < crop.h; j++) for (let i = 0; i < crop.w; i++) {
          const cx = sx + (i + 0.5) * spr, cy = sy + (j + 0.5) * spr;
          if (cx < -spr || cy < -spr || cx > canvas.width + spr || cy > canvas.height + spr) continue;
          const t = String(crop.values[j * crop.w + i]);
          ctx.strokeText(t, cx, cy); ctx.fillText(t, cx, cy);
        }
      }
    }

    // ROIs
    ctx.font = "13px sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "top"; ctx.lineWidth = 2;
    live.rois.forEach((r, i) => {
      const [x0, y0] = rawToScreen(r.x, r.y), [x1, y1] = rawToScreen(r.x + r.w, r.y + r.h);
      const col = ROI_COLOURS[i % ROI_COLOURS.length];
      ctx.strokeStyle = col; ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
      const label = `${r.name}: ${r.mean == null ? "-" : r.mean.toFixed(1)}`;
      ctx.lineWidth = 3; ctx.strokeStyle = "rgba(0,0,0,0.7)"; ctx.strokeText(label, x0 + 4, y0 + 3);
      ctx.fillStyle = col; ctx.fillText(label, x0 + 4, y0 + 3); ctx.lineWidth = 2;
    });
    if (roiDraft) {
      const [x0, y0] = rawToScreen(roiDraft.x, roiDraft.y), [x1, y1] = rawToScreen(roiDraft.x + roiDraft.w, roiDraft.y + roiDraft.h);
      ctx.setLineDash([6, 4]); ctx.strokeStyle = "#fff"; ctx.strokeRect(x0, y0, x1 - x0, y1 - y0); ctx.setLineDash([]);
    }

    // Readout under the cursor (raw pixel and, when known, its value)
    zoomText = fitted ? "fit" : `${spr.toFixed(spr < 10 ? 2 : 0)} px per raw pixel`;
    if (mouse) {
      const [rx, ry] = screenToRaw(mouse.x, mouse.y).map(Math.floor);
      let value = "";
      if (crop && rx >= crop.x && ry >= crop.y && rx < crop.x + crop.w && ry < crop.y + crop.h) {
        value = ` = ${crop.values[(ry - crop.y) * crop.w + (rx - crop.x)]} DN`;
      }
      readout = roiDraft ? `ROI ${roiDraft.x}, ${roiDraft.y}, ${roiDraft.w}x${roiDraft.h}` : `x ${rx}, y ${ry}${value}`;
    }
  }

  // Reconnect the MJPEG stream when the service streams again after a restart
  let lastState = "";
  $effect(() => {
    const st = live.health?.state ?? "offline";
    if (st === "streaming" && lastState && lastState !== "streaming") streamSrc = `/stream.mjpg?${Date.now()}`;
    lastState = st;
  });

  $effect(() => {
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(container);
    let raf = 0;
    const loop = () => { draw(); raf = requestAnimationFrame(loop); };
    raf = requestAnimationFrame(loop);
    const cropTimer = setInterval(fetchCrop, 250);
    return () => { cancelAnimationFrame(raf); clearInterval(cropTimer); ro.disconnect(); };
  });
</script>

<div class="viewer" bind:this={container}>
  <canvas
    bind:this={canvas}
    data-testid="viewer"
    onwheel={onWheel}
    onpointerdown={onDown}
    onpointermove={onMove}
    onpointerup={onUp}
    onpointercancel={onUp}
    onpointerleave={() => { mouse = null; readout = ""; }}
    ondblclick={fit}
  ></canvas>
  <img bind:this={img} src={streamSrc} alt="" class="source" onload={() => fitted && resize()} />
  <div class="hud">
    <span>{zoomText}</span>
    <span data-testid="readout">{readout}</span>
    <span class="hint">{coarse ? "pinch: zoom · drag: pan · double-tap: fit"
      : "wheel: zoom · drag: pan · double-click: fit · Shift+drag: new ROI"}</span>
  </div>
</div>

<style>
  .viewer { position: relative; flex: 1; min-height: 0; min-width: 0; overflow: hidden; background: #000; border-radius: 4px; isolation: isolate; }
  canvas { position: absolute; inset: 0; width: 100%; height: 100%; cursor: crosshair; touch-action: none; }
  /* The MJPEG source must stay in the document, and visible to the browser, to keep decoding it:
     Firefox stops updating a 1px or transparent image. It is full size under the opaque canvas. */
  .source { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; z-index: -1; pointer-events: none; }
  .hud { position: absolute; left: 0; right: 0; bottom: 0; display: flex; gap: 16px; padding: 4px 10px;
    font-size: 12px; color: var(--text); background: rgba(20, 22, 20, 0.7); pointer-events: none; }
  .hint { margin-left: auto; color: var(--grey); }
</style>
