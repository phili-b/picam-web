<script lang="ts">
  // Every libcamera control not on the basic controls: edit, then "Apply changed" sends only the
  // changed ones. Booleans are check boxes, arrays comma-separated numbers.
  import { api, parseNumber, type Control } from "../lib/api";

  const BASIC = ["AeEnable", "ExposureTime", "AnalogueGain"];
  const HIDDEN = ["ScalerCrops", "AfWindows"];

  let controls = $state<[string, Control][]>([]);
  let edits = $state<Record<string, string | boolean>>({});
  let msg = $state(""), error = $state(false);

  const isBool = (c: Control) => typeof c.min === "boolean" || typeof c.default === "boolean";
  const isArray = (c: Control) => Array.isArray(c.default) || Array.isArray(c.value) || Array.isArray(c.min);
  const current = (c: Control) => c.value ?? c.default;
  const shown = (c: Control) => {
    const v = current(c);
    return Array.isArray(v) ? v.join(", ") : v == null ? "" : String(v);
  };

  async function load() {
    const all = await api.controls();
    controls = Object.entries(all).filter(([n]) => !BASIC.includes(n) && !HIDDEN.includes(n));
    edits = {};
  }

  function convert(c: Control, v: string | boolean): unknown {
    if (typeof v === "boolean") return v;
    if (isArray(c)) return v.split(",").filter((s) => s.trim()).map(parseNumber);
    const n = parseNumber(v);
    return Number.isInteger(c.min) && Number.isInteger(c.max) ? Math.round(n) : n;
  }

  async function apply() {
    try {
      const all = Object.fromEntries(controls);
      const values = Object.fromEntries(Object.entries(edits).map(([n, v]) => [n, convert(all[n], v)]));
      if (!Object.keys(values).length) { msg = "Nothing changed."; error = false; return; }
      const r = await api.setControls(values);
      msg = "Set " + r.set.join(", "); error = false;
      edits = {};
    } catch (e) { msg = (e as Error).message; error = true; }
  }

  $effect(() => { load().catch((e) => { msg = e.message; error = true; }); });
</script>

{#each controls as [name, c] (name)}
  <div class="row" title="min {c.min}, max {c.max}, default {c.default}">
    <label for="ctl-{name}">{name}</label>
    {#if isBool(c)}
      <input id="ctl-{name}" type="checkbox" checked={Boolean(current(c))}
        onchange={(e) => (edits[name] = (e.target as HTMLInputElement).checked)} />
    {:else}
      <input id="ctl-{name}" value={shown(c)} placeholder={isArray(c) ? "a, b, ..." : ""}
        onchange={(e) => (edits[name] = (e.target as HTMLInputElement).value)} />
    {/if}
  </div>
{/each}
<div class="row">
  <span></span>
  <button onclick={apply}>Apply changed</button>
  <button onclick={load}>Reload</button>
</div>
<div class="msg" class:error>{msg}</div>

<style>
  .row > label:first-child { width: 190px; }
</style>
