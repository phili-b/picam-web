<script lang="ts">
  // Denoise profiles: tuning files named <sensor model>_tdn_<profile>.json (for example
  // poncha110_tdn_medium.json). Picking one restarts the service with that tuning file, as the Tuning
  // file section does: libcamera reads the denoise settings only when the camera opens. Only shown
  // when the sensor has such files.
  import { api, reloadWhenRestarted } from "../lib/api";
  import { live } from "../lib/live.svelte";

  const ORDER = ["light", "medium", "strong", "max"];   // weakest first; other names follow, sorted
  let files = $state<string[]>([]);
  let current = $state<string | null>(null);
  let busy = $state(false);
  let msg = $state(""), error = $state(false);

  const base = (f: string) => f.split("/").pop()!.toLowerCase();
  const model = () => String(live.info?.properties.Model ?? "").toLowerCase();
  const profileOf = (f: string) => base(f).match(new RegExp(`^${model()}_tdn_([a-z0-9]+)\\.json$`))?.[1] ?? null;
  const rank = (p: string) => (ORDER.includes(p) ? ORDER.indexOf(p) : ORDER.length);

  // One file per profile name: the first in the list, which the service gives /usr/local first
  const profiles = $derived.by(() => {
    const seen = new Map<string, string>();
    for (const f of files) {
      const p = profileOf(f);
      if (p && !seen.has(p)) seen.set(p, f);
    }
    return [...seen].sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b));
  });
  const other = $derived(current && !profileOf(current) ? current : null);   // a tuning file that is no profile

  async function load() {
    const t = await api.tuning();
    files = t.files;
    current = t.current;
  }

  async function choose(e: Event) {
    const path = (e.target as HTMLSelectElement).value || null;
    if (path === current) return;
    busy = true; error = false;
    msg = `Restarting with ${path ? `the ${profileOf(path)} denoise profile` : "the default tuning"}...`;
    try {
      const r = await api.setTuning(path);
      await reloadWhenRestarted(r.instance);
    } catch (err) {
      msg = (err as Error).message; error = true; busy = false;
      load().catch(() => {});
    }
  }

  $effect(() => { if (live.info) load().catch(() => {}); });
</script>

{#if profiles.length}
  <div class="row">
    <label for="denoise">Denoise profile</label>
    <select id="denoise" value={current ?? ""} disabled={busy} onchange={choose}>
      <option value="">off (default tuning)</option>
      {#each profiles as [p, f]}
        <option value={f}>{p}</option>
      {/each}
      {#if other}<option value={other}>other: {base(other)}</option>{/if}
    </select>
  </div>
  <div class="msg" class:error data-testid="denoise-msg">{msg}</div>
  <p class="note">Temporal denoise of the processed image (preview, JPEG, video), not of the raw frames.
    A stronger profile removes more noise but follows movement more slowly; max is for still scenes
    (moving things leave trails). Switching restarts the camera (a few seconds).</p>
{/if}
