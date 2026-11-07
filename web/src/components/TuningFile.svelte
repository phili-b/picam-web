<script lang="ts">
  // Choose the libcamera tuning file; the service checks it and restarts with it.
  import { api, reloadWhenRestarted } from "../lib/api";
  import { live } from "../lib/live.svelte";

  let files = $state<string[]>([]);
  let chosen = $state("");
  let busy = $state(false);
  let msg = $state(""), error = $state(false);

  const name = (f: string) => f.split("/").slice(-2).join("/");
  // A file fits when it is for this sensor model, and mono files go with mono sensors
  function mismatch(f: string): string {
    const base = f.split("/").pop()!.toLowerCase(), model = String(live.info?.properties.Model ?? "").toLowerCase();
    if (!base.startsWith(model)) return "other sensor";
    if (live.info && live.info.is_mono !== base.includes("mono")) return live.info.is_mono ? "colour file" : "mono file";
    return "";
  }

  async function load() {
    const t = await api.tuning();
    files = [...t.files.filter((f) => !mismatch(f)), ...t.files.filter((f) => mismatch(f))];
    chosen = t.current ?? "";
  }

  async function restart() {
    const warn = chosen && mismatch(chosen);
    if (warn && !confirm(`This file does not fit the sensor (${warn}). Restart with it anyway?`)) return;
    busy = true; error = false;
    msg = `Restarting with ${chosen ? name(chosen) : "the default tuning"}...`;
    try {
      const r = await api.setTuning(chosen || null);
      await reloadWhenRestarted(r.instance);
    } catch (e) { msg = (e as Error).message; error = true; busy = false; }
  }

  $effect(() => { load().catch((e) => { msg = e.message; error = true; }); });
</script>

<select bind:value={chosen} disabled={busy}>
  <option value="">default (libcamera's file for this sensor)</option>
  {#each files as f}
    <option value={f}>{name(f)}{mismatch(f) ? `  (${mismatch(f)})` : ""}</option>
  {/each}
</select>
<button onclick={restart} disabled={busy}>Restart with this file</button>
<div class="msg" class:error>{msg}</div>
<p class="note">The camera restarts (a few seconds); the page reloads when it is back.</p>

<style>
  select { width: 100%; margin-bottom: 6px; }
</style>
