/**
 * DESIGN.md start/step surface, translated onto the Markovian reference.
 * Shield owns Diké/judge/repairer; this only bounds carryover state.
 */
import { randomUUID } from "node:crypto";

import { CarryoverService, canonicalBlock, resolveConfig } from "./markovian.ts";
import type { ChunkConfig } from "./markovian.ts";

const TERMINAL = new Set(["publicar", "abstener", "escalar"]);

export type MarkovianState = {
  run_id: string;
  task: string;
  step: number;
  max_steps: number;
  carryover: string;
  last_decision: string | null;
};

type Run = MarkovianState & { config: ChunkConfig };

export class MarkovianHttp {
  private runs = new Map<string, Run>();
  private carryover = new CarryoverService();

  start(body: Record<string, unknown>): { run_id: string; state: MarkovianState } {
    const task = String(body.task ?? "").trim();
    const maxSteps = Math.max(1, Math.min(32, Number(body.max_steps ?? 3) || 3));
    if (!task) {
      throw Object.assign(new Error("task is required"), { status: 400 });
    }
    const config = resolveConfig({ maxChunks: maxSteps, overlapTokens: 0 });
    const run_id = randomUUID();
    const carryover = canonicalBlock({
      completed: "shield run started",
      remaining: "draft, verify with Diké, judge",
      decisions: "none",
      context: task.slice(0, 400),
    });
    const state: MarkovianState = {
      run_id,
      task: task.slice(0, 500),
      step: 0,
      max_steps: maxSteps,
      carryover,
      last_decision: null,
    };
    this.runs.set(run_id, { ...state, config });
    return { run_id, state };
  }

  async step(body: Record<string, unknown>): Promise<{ state: MarkovianState; done: boolean }> {
    const run_id = String(body.run_id ?? "");
    const observation = (body.observation ?? {}) as Record<string, unknown>;
    const run = this.runs.get(run_id);
    if (!run) {
      throw Object.assign(new Error("unknown run_id"), { status: 404 });
    }
    const decision = String(observation.decision ?? "").trim();
    const veredicto = String(observation.veredicto ?? "");
    const texto = String(observation.texto ?? "");
    const iteracion = Number(observation.iteracion ?? run.step + 1) || run.step + 1;
    const marker = canonicalBlock({
      completed: `iter ${iteracion} decision ${decision || "pendiente"} veredicto ${veredicto || "n/a"}`,
      remaining: TERMINAL.has(decision) ? "none" : "continue shield loop",
      decisions: decision || "pendiente",
      context: texto.slice(0, 400) || run.task,
    });
    const chunkText = `${marker}\n[STATE_CHECKPOINT]\n${marker}`;
    const next = await this.carryover.next({
      markerState: marker,
      previousCarryover: run.carryover,
      chunkText,
      config: run.config,
    });
    run.step += 1;
    run.carryover = next.carryover;
    run.last_decision = decision || run.last_decision;
    const done = TERMINAL.has(decision) || run.step >= run.max_steps;
    const state: MarkovianState = {
      run_id: run.run_id,
      task: run.task,
      step: run.step,
      max_steps: run.max_steps,
      carryover: run.carryover,
      last_decision: run.last_decision,
    };
    return { state, done };
  }
}
