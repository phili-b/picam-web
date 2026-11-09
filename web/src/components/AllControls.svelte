<script lang="ts">
  // Every libcamera control not handled elsewhere, grouped and explained: edit, then "Apply changed"
  // sends only the changed ones. Booleans are check boxes, enums lists, arrays comma-separated numbers.
  import { api, parseNumber, type Control } from "../lib/api";
  import { CONTROL_INFO, GROUPS, type ControlInfo } from "../lib/controlInfo";

  // On their own sliders in the Controls tab and the White balance section, or not editable as text
  const HANDLED = ["AeEnable", "ExposureTime", "AnalogueGain", "AwbEnable", "AwbMode", "ColourGains", "ColourTemperature"];
  const HIDDEN = ["ScalerCrops", "AfWindows"];

  let controls = $state<[string, Control][]>([]);
  let edits = $state<Record<string, string | boolean>>({});
  let msg = $state(""), error = $state(false);

  const info = (name: string): ControlInfo => CONTROL_INFO[name] ?? { label: name, group: "Other", help: "" };
  const inGroup = (group: string) => controls.filter(([n]) => info(n).group === group);

  const isBool = (c: Control) => typeof c.min === "boolean" || typeof c.default === "boolean";
  const isArray = (c: Control) => Array.isArray(c.default) || Array.isArray(c.value) || Array.isArray(c.min);
  const current = (c: Control) => c.value ?? c.default;
  const shown = (c: Control) => {
    const v = current(c);
    return Array.isArray(v) ? v.join(", ") : v == null ? "" : String(v);
  };
  const fmt = (v: unknown) => (typeof v === "number" ? String(Math.round(v * 1000) / 1000) : String(v));
  const range = (c: Control) => (typeof c.min === "number" && typeof c.max === "number"
    ? `Range ${fmt(c.min)} to ${fmt(c.max)}` + (c.default != null ? `, default ${fmt(c.default)}` : "") + "."
    : "");

  // The values of an enum this camera allows; the camera reports them as a min..max range
  const options = (c: Control, names: string[]) => names
    .map((label, value) => ({ label, value }))
    .filter((o) => (typeof c.min !== "number" || o.value >= c.min) && (typeof c.max !== "number" || o.value <= c.max));

  async function load() {
    const all = await api.controls();
    controls = Object.entries(all).filter(([n]) => !HANDLED.includes(n) && !HIDDEN.includes(n));
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

<p class="note">Advanced settings of the camera's image processing. Unless noted they change the processed
  preview and JPEG only, not raw frames. Blank means the camera decides.</p>

{#each GROUPS as group (group)}
  {#if inGroup(group).length}
    <h3>{group}</h3>
    {#each inGroup(group) as [name, c] (name)}
      {@const i = info(name)}
      <div class="row">
        <label for="ctl-{name}">{i.label}</label>
        {#if isBool(c)}
          <input id="ctl-{name}" type="checkbox" checked={Boolean(current(c))}
            onchange={(e) => (edits[name] = (e.target as HTMLInputElement).checked)} />
        {:else if i.options}
          <select id="ctl-{name}" value={current(c)}
            onchange={(e) => (edits[name] = (e.target as HTMLSelectElement).value)}>
            {#each options(c, i.options) as o}<option value={o.value}>{o.label}</option>{/each}
          </select>
        {:else}
          <input id="ctl-{name}" value={shown(c)} placeholder={isArray(c) ? "a, b, ..." : ""}
            onchange={(e) => (edits[name] = (e.target as HTMLInputElement).value)} />
        {/if}
      </div>
      <p class="note help">{i.help} {i.options ? "" : range(c)} <code>{name}</code></p>
    {/each}
  {/if}
{/each}
<div class="row">
  <span></span>
  <button onclick={apply}>Apply changed</button>
  <button onclick={load}>Reload</button>
</div>
<div class="msg" class:error>{msg}</div>

<style>
  .row > label:first-child { width: 190px; }
  .help { margin: -2px 0 10px 198px; }
  code { color: var(--grey); opacity: 0.7; }
  @media (max-width: 900px) { .help { margin-left: 0; } }
</style>
