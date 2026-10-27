const PACK = "af1422d66d1e6eee";
const AS_OF = "2026-08-18";
let last = null;
let lastTrace = [];
let lastBefore = "";

function go(id) {
  document.querySelectorAll("section").forEach((s) => s.classList.toggle("active", s.id === id));
}

document.querySelectorAll("nav button").forEach((btn) => {
  btn.addEventListener("click", () => go(btn.dataset.go));
});

async function loadSample(name) {
  const res = await fetch(`/samples/${name}`);
  document.getElementById("entrada").value = await res.text();
  document.getElementById("modo").value = "auditoria";
}

document.getElementById("load-despido").onclick = () => loadSample("despido_01.md");
document.getElementById("load-finiquito").onclick = () => loadSample("finiquito_01.md");

function citeClass(c) {
  if (c.estado === "VERIFICADA" && c.accion === "mantener") return "verificada";
  if (c.accion === "reparar") return "reparada";
  if (c.accion === "retirar") return "retirada";
  if (c.estado === "FALLO") return "retirada";
  return "abstencion";
}

function renderResult(data, before) {
  last = data;
  lastBefore = before;
  document.getElementById("decision").textContent = `Decisión: ${data.decision}`;
  document.getElementById("final").textContent = data.respuesta_final || data.texto_reparado || "";
  const box = document.getElementById("citas");
  box.innerHTML = "";
  for (const c of data.citas || []) {
    const el = document.createElement("div");
    el.className = `cite ${citeClass(c)}`;
    const tag = document.createElement("div");
    tag.className = "tag";
    tag.textContent = `${c.accion} · ${c.estado || ""} · ${c.resolucion || ""}`;
    const raw = document.createElement("p");
    raw.textContent = c.cita_raw;
    el.appendChild(tag);
    el.appendChild(raw);
    if (c.estado === "VERIFICADA") {
      const lab = document.createElement("p");
      lab.textContent = `Probado por Diké: existe, tiene texto citable y estaba vigente al ${AS_OF} en el corpus ${PACK}`;
      el.appendChild(lab);
    }
    box.appendChild(el);
  }
  const modelo = (data.modelos && (data.modelos.juez || data.modelos.borrador)) || "Nemotron";
  document.getElementById("opinion-modelo").textContent =
    `Opinión del modelo ${modelo}, no verificada`;
  const a = document.getElementById("commitment");
  const receta = document.getElementById("receta");
  if (data.commitment_disponible) {
    a.hidden = false;
    receta.hidden = false;
    a.href = `/v1/commitments/${data.intercepcion_id}`;
  } else {
    a.hidden = true;
    receta.hidden = true;
  }
  document.getElementById("before").textContent = before;
  document.getElementById("after").textContent = data.respuesta_final || "";
}

async function loadTrace(id) {
  const res = await fetch(`/v1/traces/${id}`);
  const data = await res.json();
  lastTrace = data.eventos || [];
  document.getElementById("trace-body").textContent = lastTrace
    .map((e) => `${e.paso}\t${e.agente}\t${e.accion}\t${e.lane || ""}\t${e.modelo || ""}\t${e.latencia_ms}ms\t${e.salida_resumen || ""}`)
    .join("\n");
}

document.getElementById("enviar").onclick = async () => {
  const err = document.getElementById("ask-err");
  err.textContent = "";
  const entrada = document.getElementById("entrada").value.trim();
  const escenario = document.getElementById("escenario").value;
  const modo = document.getElementById("modo").value;
  if (!entrada) {
    err.textContent = "Escribe una pregunta o pega un texto.";
    return;
  }
  const url = modo === "auditoria" ? "/v1/shield/audit" : "/v1/shield/answer";
  const body = modo === "auditoria" ? { texto: entrada, escenario } : { pregunta: entrada, escenario };
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);
    renderResult(data, entrada);
    await loadTrace(data.intercepcion_id);
    go("result");
  } catch (e) {
    err.textContent = String(e.message || e);
  }
};

async function loadDash() {
  const res = await fetch("/v1/bench/latest");
  const data = await res.json();
  document.getElementById("dash-label").textContent =
    data.etiqueta ||
    "Cifras medidas sobre 0 preguntas sintéticas; no son una estimación de la tasa en producción";
  const tb = document.getElementById("dash-body");
  tb.innerHTML = "";
  for (const r of data.corridas || []) {
    const tr = document.createElement("tr");
    const tasa = typeof r.tasa === "number" ? r.tasa : 0;
    tr.innerHTML = `<td>${r.lane}</td><td>${r.con_escudo ? "con" : "sin"}</td><td>${r.n_preguntas}</td><td>${r.citas_total}</td><td>${r.citas_no_probadas}</td><td>${(tasa * 100).toFixed(1)}%</td><td>${r.modelo || ""}</td>`;
    tb.appendChild(tr);
  }
}

document.getElementById("run-bench").onclick = async () => {
  const err = document.getElementById("dash-err");
  err.textContent = "";
  try {
    await fetch("/v1/bench/run", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ n_preguntas: 2, lanes: ["FAST"], con_escudo: [false, true] }),
    });
    await loadDash();
  } catch (e) {
    err.textContent = String(e.message || e);
  }
};

(async function boot() {
  try {
    const hz = await (await fetch("/healthz")).json();
    const banner = document.getElementById("sample-banner");
    if (hz.sample_mode) {
      const fecha = hz.sample_recorded_at || "fecha no registrada";
      banner.textContent = `Modo muestra: respuestas grabadas de una corrida real del ${fecha}`;
      banner.hidden = false;
    }
  } catch {
    /* ignore */
  }
  try {
    await loadDash();
  } catch {
    /* ignore */
  }
})();
