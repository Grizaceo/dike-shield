import assert from "node:assert/strict";
import type { AddressInfo } from "node:net";
import { test } from "node:test";

import { HMEM } from "../src/hmem.ts";
import { createEnginesServer } from "../src/server.ts";

test("healthz is honest and remember/recall round-trip a refuted cite", async () => {
  const hmem = new HMEM({ clock: () => 1_750_000_000_000, actor: "test" });
  const server = createEnginesServer(hmem);
  await new Promise<void>((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve());
  });
  const { port } = server.address() as AddressInfo;
  const base = `http://127.0.0.1:${port}`;
  try {
    const hz = (await (await fetch(`${base}/healthz`)).json()) as {
      ok: boolean;
      hmem: boolean;
      markovian: boolean;
    };
    assert.equal(hz.ok, true);
    assert.equal(hz.hmem, true);
    assert.equal(hz.markovian, true);

    const rem = (await (
      await fetch(`${base}/hmem/remember`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          namespace: "refutadas",
          content: "artículo 9999 del Código del Trabajo",
          metadata: {
            sesion_id: "sess-a",
            resolucion: "UNRESOLVABLE",
            razon: "UNRESOLVABLE",
          },
        }),
      })
    ).json()) as { id: string };
    assert.ok(rem.id);

    const rec = (await (
      await fetch(`${base}/hmem/recall`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          namespace: "refutadas",
          query: "plazo para reclamar un despido artículo Código del Trabajo",
          k: 5,
        }),
      })
    ).json()) as {
      items: Array<{ content: string; metadata: { sesion_id?: string } }>;
    };
    assert.ok(rec.items.length >= 1);
    assert.ok(rec.items[0].content.includes("9999"));
    assert.equal(rec.items[0].metadata.sesion_id, "sess-a");

    const trampas = (await (
      await fetch(`${base}/hmem/recall`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ namespace: "trampas", query: "9999", k: 5 }),
      })
    ).json()) as { items: unknown[] };
    assert.equal(trampas.items.length, 0);

    const started = (await (
      await fetch(`${base}/markovian/start`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ task: "verificar citas de un despido", max_steps: 3 }),
      })
    ).json()) as { run_id: string; state: { step: number } };
    assert.ok(started.run_id);
    assert.equal(started.state.step, 0);
    const stepped = (await (
      await fetch(`${base}/markovian/step`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          run_id: started.run_id,
          observation: {
            iteracion: 1,
            decision: "publicar",
            veredicto: "TODAS_VERIFICADAS",
            texto: "artículo 168 del Código del Trabajo",
          },
        }),
      })
    ).json()) as { done: boolean; state: { step: number } };
    assert.equal(stepped.done, true);
    assert.equal(stepped.state.step, 1);
  } finally {
    await new Promise<void>((resolve, reject) => {
      server.close((err) => (err ? reject(err) : resolve()));
    });
  }
});
