<script lang="ts">
  // Sensor registers: read, write, dump, through the driver's register controls when it has them
  // (else directly over I2C), and the driver's context controls (sensors whose profile has contexts).
  import { api, hex, parseNumber, type BankSelect, type Contexts, type ContextsUpdate,
    type KnownRegisters } from "../lib/api";

  let known = $state<KnownRegisters | null>(null);
  let contexts = $state<Contexts | null>(null);
  let address = $state("0x0000");
  let bytes = $state(1);
  let value = $state("0x00");
  let bank = $state<number | null>(null);
  let context = $state<number | null>(null);
  let dumpStart = $state("0x0000");
  let dumpCount = $state(64);
  let log = $state<string[]>([]);

  const names = $derived(known?.contexts ?? "");
  const viaDriver = $derived(known?.backend === "driver");

  const sel = (): BankSelect => ({ bank, context: bank === 1 ? context : null });
  const selText = () => (bank === null ? "" : ` (bank ${bank}${bank === 1 && context !== null ? ", context " + names[context] : ""})`);
  const note = (text: string) => (log = [`${new Date().toLocaleTimeString()}  ${text}`, ...log].slice(0, 200));

  async function run(action: () => Promise<void>) {
    try { await action(); } catch (e) { note("ERROR " + (e as Error).message); }
  }

  function pick(e: Event) {
    const r = known?.registers[Number((e.target as HTMLSelectElement).value)];
    if (r) { address = hex(r.address, 2); bytes = r.bytes; }
  }

  const read = () => run(async () => {
    const a = parseNumber(address), n = bytes, where = selText();
    const r = await api.readRegister(a, n, sel());
    value = hex(r.value, n);
    note(`read  ${hex(a, 2)} = ${value} (${r.value})${where}`);
  });

  const write = () => run(async () => {
    const a = parseNumber(address), v = parseNumber(value), n = bytes, where = selText();
    await api.writeRegister(a, v, n, sel());
    note(`write ${hex(a, 2)} = ${hex(v, n)}${where}`);
  });

  const dump = () => run(async () => {
    const where = selText();
    const d = await api.dumpRegisters(parseNumber(dumpStart), Math.round(dumpCount), sel());
    const lines = [];
    for (let i = 0; i < d.length; i += 16) {
      lines.push(hex(d[i].address, 2) + ": " + d.slice(i, i + 16).map((x) => x.value.toString(16).padStart(2, "0")).join(" "));
    }
    note(`dump${where}\n` + lines.join("\n"));
  });

  const refreshContexts = () => run(async () => { contexts = await api.contexts(); });

  const setContexts = (values: ContextsUpdate) => run(async () => {
    contexts = await api.setContexts(values);
    note("contexts " + Object.entries(values).map(([k, v]) => `${k}=${v}`).join(", "));
  });

  $effect(() => {
    api.knownRegisters().then((k) => {
      known = k;
      if (k.banked) refreshContexts();
    }).catch((e) => note("ERROR " + e.message));
  });
</script>

<div class="msg">
  {known ? (known.sensor ?? "No sensor found on an I2C bus") : ""}
  {#if known?.backend}
    <span class="note">· {viaDriver ? "through the driver" : "directly over I2C (driver without register controls)"}</span>
  {/if}
</div>

{#if known?.sensor}
  {#if contexts?.available}
    <h3>Contexts</h3>
    <div class="row">
      <label for="cur">Current</label>
      <span id="cur" data-testid="ctx-current">{contexts.current ?? "– (not streaming)"}</span>
      <button onclick={refreshContexts}>Refresh</button>
    </div>
    <div class="row">
      <label for="next">Switch to</label>
      <select id="next" value={contexts.context} onchange={(e) => setContexts({ context: (e.target as HTMLSelectElement).value })}>
        {#each names as n}<option value={n}>{n}</option>{/each}
      </select>
    </div>
    <div class="row">
      <label for="auto">Auto switch</label>
      <input id="auto" type="checkbox" checked={contexts.auto_switch}
        onchange={(e) => setContexts({ auto_switch: (e.target as HTMLInputElement).checked })} />
      <select aria-label="auto switch to" value={contexts.auto_switch_to}
        onchange={(e) => setContexts({ auto_switch_to: (e.target as HTMLSelectElement).value })}>
        {#each names as n}<option value={n}>to {n}</option>{/each}
      </select>
    </div>
    <div class="row">
      <label for="cc">Exposure / frame time to</label>
      <select id="cc" value={contexts.controls_context}
        onchange={(e) => setContexts({ controls_context: (e.target as HTMLSelectElement).value })}>
        <option value="all">all contexts</option>
        {#each names as n}<option value={n}>context {n}</option>{/each}
      </select>
    </div>
    <p class="note">The driver writes the ROI and row length to every context and exposure and frame time
      to the contexts chosen here. Program the other settings of a context below with bank 1 and that
      context, then switch to it.</p>
  {/if}

  <h3>Register</h3>
  {#if known.registers.length}
    <div class="row">
      <label for="known">Named register</label>
      <select id="known" onchange={pick}>
        <option value="">(choose)</option>
        {#each known.registers as r, i}<option value={i}>{r.name}  {hex(r.address, 2)}</option>{/each}
      </select>
    </div>
  {/if}
  <div class="row"><label for="addr">Address</label><input id="addr" bind:value={address} /></div>
  <div class="row">
    <label for="bytes">Bytes</label>
    <select id="bytes" bind:value={bytes}>{#each [1, 2, 3, 4] as n}<option value={n}>{n}</option>{/each}</select>
  </div>
  {#if known.banked}
    <div class="row">
      <label for="bank">Bank</label>
      <select id="bank" bind:value={bank}>
        <option value={null}>{viaDriver ? "0 (default)" : "current"}</option>
        <option value={0}>0</option><option value={1}>1 (context registers)</option>
      </select>
    </div>
    {#if bank === 1}
      <div class="row">
        <label for="ctx">Context</label>
        <select id="ctx" bind:value={context}>
          <option value={null}>{viaDriver ? "A (default)" : "current"}</option>
          {#each names as n, i}<option value={i}>{n}</option>{/each}
        </select>
      </div>
    {/if}
  {/if}
  <div class="row"><label for="val">Value</label><input id="val" bind:value={value} /></div>
  <div class="row"><span></span><button onclick={read}>Read</button><button onclick={write}>Write</button></div>

  <h3>Dump</h3>
  <div class="row">
    <label for="ds">From</label>
    <input id="ds" bind:value={dumpStart} />
    <input type="number" min="1" max="4096" bind:value={dumpCount} title="number of 8-bit registers" />
    <button onclick={dump}>Dump</button>
  </div>
  <p class="note">Addresses and values in hex (0x...) or decimal.
    {#if viaDriver}
      The driver selects the bank and context for each access and returns to bank 0 / context A,
      so this does not disturb its own writes. It only accesses registers while the camera streams.
    {:else}
      Bank and context are selected directly on the sensor; they can race with the driver.
    {/if}
    The driver does not know about writes and may overwrite them at a mode switch or exposure change.
    Bankless registers (offsets 0x000–0x005 of each block, such as BANK_SEL) ignore bank and context.</p>
  <pre data-testid="reg-log">{log.join("\n")}</pre>
{/if}
