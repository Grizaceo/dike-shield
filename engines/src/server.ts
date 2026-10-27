/**
 * DESIGN.md HTTP surface, translated onto Meterless H-MEM and Markovian references.
 */
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { HMEM } from "./hmem.ts";
import type { MemoryRecord } from "../hmem/reference/src/index.ts";
import { MarkovianHttp } from "./markovianHttp.ts";

const HOST = process.env.ENGINES_HOST ?? "127.0.0.1";
const NAMESPACES = new Set(["refutadas", "trampas"]);

function repoRoot(): string {
  return path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
}

function persistDir(): string | undefined {
  if (process.env.ENGINES_TEST === "1") return undefined;
  if (process.env.HMEM_PERSIST_DIR === "") return undefined;
  if (process.env.HMEM_PERSIST_DIR) return process.env.HMEM_PERSIST_DIR;
  return path.join(repoRoot(), ".local", "hmem");
}

export function createHmem(opts?: { persist?: boolean }): HMEM {
  const dir = opts?.persist === false ? undefined : persistDir();
  return new HMEM({ actor: "dike-shield", persistDir: dir });
}

function nsTag(namespace: string): string {
  return `ns:${namespace}`;
}

function json(res: http.ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

function readBody(req: http.IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let total = 0;
    req.on("data", (chunk: Buffer) => {
      total += chunk.length;
      if (total > 1_000_000) {
        reject(new Error("body too large"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

function metadataOf(memory: MemoryRecord): Record<string, unknown> {
  const sesionTag = memory.tags.find((t) => t.startsWith("sesion:"));
  const resolTag = memory.tags.find((t) => t.startsWith("resolucion:"));
  const ns = memory.tags.find((t) => t.startsWith("ns:"));
  return {
    sesion_id: memory.chatId ?? (sesionTag ? sesionTag.slice("sesion:".length) : undefined),
    resolucion: resolTag ? resolTag.slice("resolucion:".length) : undefined,
    razon: memory.provenance?.label,
    namespace: ns ? ns.slice(3) : memory.namespace,
  };
}

function remember(hmem: HMEM, body: Record<string, unknown>): { id: string } {
  const namespace = String(body.namespace ?? "");
  const content = String(body.content ?? "");
  const metadata = (body.metadata ?? {}) as Record<string, unknown>;
  if (!NAMESPACES.has(namespace)) {
    throw Object.assign(new Error("namespace must be refutadas|trampas"), { status: 400 });
  }
  if (!content.trim()) {
    throw Object.assign(new Error("content is required"), { status: 400 });
  }
  const sesionId = metadata.sesion_id != null ? String(metadata.sesion_id) : undefined;
  const resolucion = metadata.resolucion != null ? String(metadata.resolucion) : undefined;
  const razon = metadata.razon != null ? String(metadata.razon) : "";
  const tags = [nsTag(namespace)];
  if (sesionId) tags.push(`sesion:${sesionId}`);
  if (resolucion) tags.push(`resolucion:${resolucion}`);
  const rec = hmem.add({
    content,
    type: "factual",
    layer: "long_term",
    tags,
    confidence: 0.95,
    source: `dike-shield:${namespace}`,
    provenance: {
      origin: "user_correction",
      learnedAt: Date.now(),
      label: razon || `refuted by Diké (${namespace})`,
      refs: sesionId ? [sesionId] : undefined,
    },
    chatId: sesionId,
  });
  return { id: rec.id };
}

function recall(hmem: HMEM, body: Record<string, unknown>): {
  items: Array<{ id: string; content: string; score: number; metadata: Record<string, unknown> }>;
} {
  const namespace = String(body.namespace ?? "");
  const query = String(body.query ?? "");
  const k = Math.max(1, Number(body.k ?? 5) || 5);
  const tag = nsTag(namespace);
  const result = hmem.query(query, { topN: Math.max(k * 5, 20), threshold: 0 });
  let picked = result.memories.filter((x) => x.memory.tags.includes(tag));
  if (picked.length < k) {
    const have = new Set(picked.map((x) => x.memory.id));
    const extra = hmem.store
      .all()
      .filter((m) => m.tags.includes(tag) && !have.has(m.id))
      .map((m) => ({ memory: m, relevance: hmem.retrieval.scoreOne(m, query) }))
      .sort((a, b) => b.relevance - a.relevance || a.memory.id.localeCompare(b.memory.id));
    picked = picked.concat(extra);
  }
  picked = picked.slice(0, k);
  return {
    items: picked.map((x) => ({
      id: x.memory.id,
      content: x.memory.content,
      score: x.relevance,
      metadata: metadataOf(x.memory),
    })),
  };
}

export function createEnginesServer(
  hmem: HMEM = createHmem(),
  markovian: MarkovianHttp = new MarkovianHttp(),
): http.Server {
  return http.createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", `http://${HOST}`);
    try {
      if (req.method === "GET" && url.pathname === "/healthz") {
        json(res, 200, { ok: true, hmem: true, markovian: true });
        return;
      }
      if (req.method === "POST" && (url.pathname === "/hmem/remember" || url.pathname === "/hmem/recall")) {
        const raw = await readBody(req);
        let body: Record<string, unknown> = {};
        try {
          body = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
        } catch {
          json(res, 400, { error: "invalid json" });
          return;
        }
        if (url.pathname === "/hmem/remember") {
          json(res, 200, remember(hmem, body));
          return;
        }
        json(res, 200, recall(hmem, body));
        return;
      }
      if (req.method === "POST" && (url.pathname === "/markovian/start" || url.pathname === "/markovian/step")) {
        const raw = await readBody(req);
        let body: Record<string, unknown> = {};
        try {
          body = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
        } catch {
          json(res, 400, { error: "invalid json" });
          return;
        }
        if (url.pathname === "/markovian/start") {
          json(res, 200, markovian.start(body));
          return;
        }
        json(res, 200, await markovian.step(body));
        return;
      }
      json(res, 404, { error: "not found" });
    } catch (err) {
      const status = Number((err as { status?: number }).status ?? 500);
      json(res, status, { error: (err as Error).message });
    }
  });
}

