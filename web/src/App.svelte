<script lang="ts">
  import Viewer from "./components/Viewer.svelte";
  import HealthBanner from "./components/HealthBanner.svelte";
  import Controls from "./tabs/Controls.svelte";
  import Capture from "./tabs/Capture.svelte";
  import Histograms from "./tabs/Histograms.svelte";
  import RoisNoise from "./tabs/RoisNoise.svelte";
  import Registers from "./tabs/Registers.svelte";
  import Status from "./tabs/Status.svelte";
  import { live, startPolling } from "./lib/live.svelte";

  const TABS = { "Controls": Controls, "Capture": Capture, "Histograms": Histograms, "ROIs & Noise": RoisNoise,
    "Registers": Registers, "Status": Status };
  type TabName = keyof typeof TABS;
  let tab = $state<TabName>("Controls");
  const Tab = $derived(TABS[tab]);

  $effect(() => startPolling());

  const f = $derived(live.frames);
  const model = $derived(live.info?.properties.Model ?? "");
  $effect(() => { document.title = `Picam-web${model ? " - " + model : ""}`; });
</script>

<header>
  <img src="/static/icon.png" alt="" class="icon" />
  <div class="title">Picam-web</div>
  {#if live.info}
    <div class="sub" data-testid="sensor">{model} · {live.info.raw.format} {live.info.raw.size.join("x")}</div>
  {/if}
  <div class="spacer"></div>
  <a href="https://phili-b.github.io/picam-web/" target="_blank" rel="noopener" class="sub">Docs</a>
  <a href="/docs" target="_blank" class="sub">API</a>
</header>

<main>
  <section class="view">
    <HealthBanner />
    <Viewer />
    <div class="status" class:error={!!f?.error} data-testid="status">
      {#if f}{f.error ?? `${f.fps.toFixed(1)} fps · ${f.frames} frames · ${f.dropped} dropped`}{/if}
    </div>
  </section>
  <aside>
    <nav>
      {#each Object.keys(TABS) as t}
        <button class:active={tab === t} onclick={() => (tab = t as TabName)}>{t}</button>
      {/each}
    </nav>
    <div class="tab"><Tab /></div>
  </aside>
</main>

<style>
  header { display: flex; align-items: center; gap: 12px; padding: 6px 14px; background: var(--base); border-bottom: 1px solid var(--green); }
  .icon { height: 32px; }
  .title { font-size: 17px; }
  .spacer { flex: 1; }
  header a { flex: none; }
  main { flex: 1; display: flex; min-height: 0; }
  .view { flex: 1; display: flex; flex-direction: column; padding: 10px; min-width: 0; }
  .status { color: var(--grey); font-size: 13px; margin-top: 6px; }
  aside { width: 470px; background: var(--base); display: flex; flex-direction: column; border-left: 1px solid var(--button); }
  nav { display: flex; flex-wrap: wrap; gap: 2px; padding: 6px; border-bottom: 1px solid var(--button); }
  nav button { background: transparent; border: none; padding: 5px 8px; font-size: 13px; }
  nav button.active { color: var(--green); background: var(--button); }
  .tab { padding: 10px 14px; overflow-y: auto; flex: 1; }
  /* Narrow window or phone: one scrolling page, the preview on top, the panel under it */
  @media (max-width: 900px) {
    main { flex-direction: column; flex: none; }
    .view { flex: none; height: min(70vw, 55vh); min-height: 220px; padding: 6px; }
    aside { width: auto; border-left: none; border-top: 1px solid var(--button); }
    .tab { overflow: visible; flex: none; padding: 10px; }
    header { padding: 6px 10px; gap: 8px; }
    .title { font-size: 15px; }
    .sub { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
    /* tabs in one swipeable line */
    nav { flex-wrap: nowrap; overflow-x: auto; -webkit-overflow-scrolling: touch; }
    nav button { flex: none; padding: 10px 12px; font-size: 14px; white-space: nowrap; }
  }
</style>
