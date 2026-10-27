"use strict";

const path = require("path");
const pptxgen = require("pptxgenjs");
const { applyTheme } = require("/home/gris96/.claude/skills/synced/bf159a68-9aa0-4cdd-a6ce-7bc16da2b532_64677eb1-7ccb-4f27-8407-2989b7958351/pptx/scripts/apply_theme.js");

const OUT = path.join(__dirname, "dike-shield.pptx");

const THEME = {
  name: "Dike Shield",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1B1712",
    lt1: "FFFFFF",
    dk2: "3D342C",
    lt2: "F4EFE4",
    accent1: "7A1F1F",
    accent2: "C4A35A",
    accent3: "2F4A3C",
    accent4: "5C4E3A",
    accent5: "8C3A2A",
    accent6: "1F2A44",
    hlink: "7A1F1F",
    folHlink: "5C4E3A",
  },
};

async function main() {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE";
  pres.title = "Dike Shield";
  pres.author = "Open Agent Hackathon 2026";
  pres.subject = "Nemotron cites. Dike proves.";
  pres.company = "Dike Shield";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };

  const C = pres.SchemeColor;

  pres.defineSlideMaster({
    title: "TITLE",
    background: { color: C.text1 },
    objects: [
      {
        placeholder: {
          options: {
            name: "title",
            type: "title",
            x: 0.7,
            y: 2.15,
            w: 11.9,
            h: 1.15,
            fontSize: 44,
            bold: true,
            align: "left",
            color: C.background1,
            margin: 0,
          },
          text: "Title",
        },
      },
      {
        placeholder: {
          options: {
            name: "subtitle",
            type: "body",
            x: 0.7,
            y: 3.4,
            w: 11.9,
            h: 0.7,
            fontSize: 22,
            color: C.accent2,
            margin: 0,
          },
          text: "Subtitle",
        },
      },
    ],
  });

  pres.defineSlideMaster({
    title: "SECTION",
    background: { color: C.text1 },
    objects: [
      {
        placeholder: {
          options: {
            name: "title",
            type: "title",
            x: 0.7,
            y: 3.0,
            w: 11.9,
            h: 1.2,
            fontSize: 36,
            bold: true,
            align: "left",
            color: C.background1,
            margin: 0,
          },
          text: "Section",
        },
      },
    ],
  });

  pres.defineSlideMaster({
    title: "CONTENT",
    background: { color: C.background1 },
    objects: [
      {
        placeholder: {
          options: {
            name: "title",
            type: "title",
            x: 0.5,
            y: 0.32,
            w: 12.3,
            h: 0.62,
            fontSize: 28,
            bold: true,
            align: "left",
            color: C.text1,
            margin: 0,
          },
          text: "Title",
        },
      },
      {
        text: {
          text: "Dike Shield  ·  Open Agent Hackathon 2026",
          options: {
            x: 0.5,
            y: 7.12,
            w: 10.4,
            h: 0.24,
            fontSize: 11,
            color: C.text2,
            margin: 0,
          },
        },
      },
    ],
    slideNumber: { x: 12.35, y: 7.1, fontSize: 11, color: C.text2 },
  });

  pres.addSection({ title: "Open" });
  let slide = pres.addSlide({ masterName: "TITLE", sectionTitle: "Open" });
  slide.addText("Diké Shield", { placeholder: "title" });
  slide.addText("Nemotron cites. Diké proves.", { placeholder: "subtitle" });
  slide.addText("Open Agent Hackathon 2026  ·  The Agent That Can Explain Why", {
    x: 0.7,
    y: 4.35,
    w: 11.9,
    h: 0.4,
    fontSize: 16,
    color: C.background1,
    margin: 0,
    isTextBox: true,
  });
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.7,
    y: 5.15,
    w: 3.4,
    h: 0.55,
    fill: { color: C.accent1 },
    rectRadius: 0.06,
  });
  slide.addText("Chilean labor drafts, proven offline", {
    x: 0.82,
    y: 5.22,
    w: 3.16,
    h: 0.4,
    fontSize: 12,
    color: C.background1,
    margin: 0,
    isTextBox: true,
  });
  slide.addNotes(
    "Open with the sentence: a large model will invent a cite; Diké will catch it; the same family repairs it."
  );

  pres.addSection({ title: "Problem" });
  slide = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Problem" });
  slide.addText("The draft the lawyer cannot send", { placeholder: "title" });
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.5,
    y: 1.15,
    w: 7.6,
    h: 5.55,
    fill: { color: C.background2 },
    rectRadius: 0.08,
  });
  slide.addText("A Chilean labor lawyer needs a dismissal brief that will survive a courtroom, not a chat window.", {
    x: 0.75,
    y: 1.4,
    w: 7.1,
    h: 1.15,
    fontSize: 18,
    color: C.text1,
    margin: 0,
    isTextBox: true,
  });
  const problems = [
    { t: "Invented articles", d: "Nemotron will happily emit artículo 9999 or an ambiguous artículo 14." },
    { t: "No offline proof", d: "A colleague cannot check the model. The file has to carry the evidence." },
    { t: "Memory that forgets", d: "The next session repeats the same refuted cite unless something stores the miss." },
  ];
  problems.forEach((p, i) => {
    const y = 2.7 + i * 1.2;
    slide.addText(p.t, {
      x: 0.75,
      y,
      w: 7.1,
      h: 0.35,
      fontSize: 16,
      bold: true,
      color: C.accent1,
      margin: 0,
      isTextBox: true,
    });
    slide.addText(p.d, {
      x: 0.75,
      y: y + 0.35,
      w: 7.1,
      h: 0.55,
      fontSize: 14,
      color: C.text2,
      margin: 0,
      isTextBox: true,
    });
  });
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 8.35,
    y: 1.15,
    w: 4.45,
    h: 5.55,
    fill: { color: C.text1 },
    rectRadius: 0.08,
  });
  slide.addText("8,544", {
    x: 8.55,
    y: 2.15,
    w: 4.05,
    h: 1.1,
    fontSize: 48,
    bold: true,
    color: C.accent2,
    margin: 0,
    isTextBox: true,
  });
  slide.addText("articles in a dated Chilean corpus. If it is not in the pack, Diké will not bless it.", {
    x: 8.55,
    y: 3.4,
    w: 4.05,
    h: 1.6,
    fontSize: 16,
    color: C.background1,
    margin: 0,
    isTextBox: true,
  });
  slide.addText("pack af1422d66d1e6eee  ·  2026-08-18", {
    x: 8.55,
    y: 5.4,
    w: 4.05,
    h: 0.5,
    fontSize: 12,
    color: C.accent2,
    margin: 0,
    isTextBox: true,
  });
  slide.addNotes("User is a Chilean labor lawyer. Failure mode is a hallucinated cite in a demand for despido.");

  pres.addSection({ title: "Solution" });
  slide = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Solution" });
  slide.addText("Prove every cite, then sign what survived", { placeholder: "title" });
  const steps = [
    { n: "01", t: "Draft", d: "FAST Lightning 30B writes the answer in Diké's citation format." },
    { n: "02", t: "Prove", d: "Diké returns VERIFICADA or FALLO. The loop never reinterprets that verdict." },
    { n: "03", t: "Repair", d: "DEEP Ultra 550B rewrites with verified articles only. Diké runs again." },
    { n: "04", t: "Commit", d: "Ed25519 commitment. Anyone checks it offline, without the Runtime." },
  ];
  steps.forEach((s, i) => {
    const x = 0.5 + (i % 4) * 3.15;
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x,
      y: 1.25,
      w: 2.95,
      h: 4.55,
      fill: { color: C.background2 },
      rectRadius: 0.08,
    });
    slide.addText(s.n, {
      x: x + 0.2,
      y: 1.5,
      w: 2.55,
      h: 0.55,
      fontSize: 22,
      bold: true,
      color: C.accent1,
      margin: 0,
      isTextBox: true,
    });
    slide.addText(s.t, {
      x: x + 0.2,
      y: 2.2,
      w: 2.55,
      h: 0.5,
      fontSize: 22,
      bold: true,
      color: C.text1,
      margin: 0,
      isTextBox: true,
    });
    slide.addText(s.d, {
      x: x + 0.2,
      y: 2.85,
      w: 2.55,
      h: 2.5,
      fontSize: 15,
      color: C.text2,
      margin: 0,
      isTextBox: true,
    });
  });
  slide.addNotes("Walk the four beats. Stress that Diké is the source of truth, not the judge model.");

  pres.addSection({ title: "How" });
  slide = pres.addSlide({ masterName: "CONTENT", sectionTitle: "How" });
  slide.addText("One intercept, two runtimes, one dated corpus", { placeholder: "title" });
  const arch = [
    { t: "Nightshift", d: "Only AI provider. FAST drafts. DEEP judges and repairs. NVIDIA key stays in the Console." },
    { t: "Diké CLI", d: "Isolated HOME under .local/dike-home. Never touches ~/.lexo. 25 statutes, 8,544 articles." },
    { t: "Zetaris", d: "Lightning views over shield-db. The product reads through federation; writes go to Postgres." },
    { t: "H-MEM", d: "Refuted cites persist across sessions. Session B recalls artículo 9999 from session A." },
    { t: "Markovian", d: "Bounded loop. Done on publicar, abstener, escalar, or max_steps." },
    { t: "UI", d: "Spanish labels the contract forbids us to soften. Trace, before/after, bank, commitment ZIP." },
  ];
  arch.forEach((a, i) => {
    const col = i % 3;
    const row = Math.floor(i / 3);
    const x = 0.5 + col * 4.2;
    const y = 1.2 + row * 2.7;
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x,
      y,
      w: 3.95,
      h: 2.45,
      fill: { color: C.background2 },
      rectRadius: 0.08,
    });
    slide.addText(a.t, {
      x: x + 0.22,
      y: y + 0.22,
      w: 3.5,
      h: 0.45,
      fontSize: 18,
      bold: true,
      color: C.accent1,
      margin: 0,
      isTextBox: true,
    });
    slide.addText(a.d, {
      x: x + 0.22,
      y: y + 0.75,
      w: 3.5,
      h: 1.45,
      fontSize: 14,
      color: C.text1,
      margin: 0,
      isTextBox: true,
    });
  });
  slide.addNotes("Architecture in six cards. Mention fail-closed engines: sidecar down still finishes the intercept.");

  slide = pres.addSlide({ masterName: "CONTENT", sectionTitle: "How" });
  slide.addText("Stack on the prize path", { placeholder: "title" });
  const stack = [
    { k: "NVIDIA", v: "Lightning 30B FAST, Ultra 550B DEEP. No meterless/auto." },
    { k: "Meterless", v: "Nightshift Runtime plus H-MEM and Markovian engines in a real loop." },
    { k: "Zetaris", v: "9 Lightning views. 8544 rows proven via SELECT count(*)." },
    { k: "Cursor", v: "Built in the window. CURSOR_LOG is the session record." },
    { k: "Diké", v: "Pre-existing MIT engine, hashed, unmodified." },
    { k: "Postgres", v: "shield-db :55432 on zetaris_default. Writes here, reads through Lightning." },
  ];
  stack.forEach((s, i) => {
    const y = 1.15 + i * 0.88;
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: 0.5,
      y,
      w: 12.3,
      h: 0.78,
      fill: { color: i % 2 === 0 ? C.background2 : C.background1 },
      rectRadius: 0.06,
    });
    slide.addText(s.k, {
      x: 0.7,
      y: y + 0.18,
      w: 2.4,
      h: 0.42,
      fontSize: 16,
      bold: true,
      color: C.accent1,
      margin: 0,
      isTextBox: true,
    });
    slide.addText(s.v, {
      x: 3.2,
      y: y + 0.18,
      w: 9.3,
      h: 0.42,
      fontSize: 16,
      color: C.text1,
      margin: 0,
      isTextBox: true,
    });
  });
  slide.addNotes("Sponsor stack. NVIDIA key never in the repo. Diké is declared preexisting.");

  slide = pres.addSlide({ masterName: "CONTENT", sectionTitle: "How" });
  slide.addText("Zetaris reads. Meterless decides.", { placeholder: "title" });
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.5,
    y: 1.2,
    w: 6.0,
    h: 5.4,
    fill: { color: C.background2 },
    rectRadius: 0.08,
  });
  slide.addText("Zetaris", {
    x: 0.75,
    y: 1.45,
    w: 5.5,
    h: 0.45,
    fontSize: 22,
    bold: true,
    color: C.accent1,
    margin: 0,
    isTextBox: true,
  });
  slide.addText(
    [
      { text: "Datasource shield_pg on the local Lightning install.", options: { bullet: true, breakLine: true } },
      { text: "Views, not REGISTER TABLES: this build's JDBC sees public, not schema shield.", options: { bullet: true, breakLine: true } },
      { text: "SELECT count(*) FROM shield_pg.articulos → 8544.", options: { bullet: true, breakLine: true } },
      { text: "The judge reads article text through Lightning. Writes stay in psycopg.", options: { bullet: true } },
    ],
    {
      x: 0.75,
      y: 2.1,
      w: 5.5,
      h: 4.1,
      fontSize: 15,
      color: C.text1,
      paraSpaceAfter: 10,
      margin: 0,
      isTextBox: true,
    }
  );
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 6.8,
    y: 1.2,
    w: 6.0,
    h: 5.4,
    fill: { color: C.text1 },
    rectRadius: 0.08,
  });
  slide.addText("Meterless", {
    x: 7.05,
    y: 1.45,
    w: 5.5,
    h: 0.45,
    fontSize: 22,
    bold: true,
    color: C.accent2,
    margin: 0,
    isTextBox: true,
  });
  slide.addText(
    [
      { text: "Nightshift is the only AI provider. FAST and DEEP are Nemotron ids.", options: { bullet: true, breakLine: true } },
      { text: "H-MEM remember/recall of refuted cites. Conformance 13/13.", options: { bullet: true, breakLine: true } },
      { text: "Markovian start/step on the intercept. Conformance 8/8.", options: { bullet: true, breakLine: true } },
      { text: "Sidecar down: fail closed. The intercept still finishes.", options: { bullet: true } },
    ],
    {
      x: 7.05,
      y: 2.1,
      w: 5.5,
      h: 4.1,
      fontSize: 15,
      color: C.background1,
      paraSpaceAfter: 10,
      margin: 0,
      isTextBox: true,
    }
  );
  slide.addNotes("This is the sponsor slide. Do not rush it.");

  pres.addSection({ title: "Evidence" });
  slide = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Evidence" });
  slide.addText("What was unique in the window", { placeholder: "title" });
  const uniq = [
    { n: "20/20", t: "Traps fail on purpose", d: "Invented, ambiguous, repealed, wrong-code cites. All FALLO. None collide with the corpus." },
    { n: "A → B", t: "Memory across sessions", d: "H-MEM recalled artículo 9999 in the next session as recordado de la sesión <id>." },
    { n: "0.0", t: "Shielded bank rate", d: "Scripted four-run bank: 0.5 unproven without the shield, 0.0 with it. Live 30-q pending Nightshift." },
    { n: "391", t: "Live Lightning miss", d: "27 Oct run: artículo 14 at position 391 in the FAST draft, gone from the final text." },
  ];
  uniq.forEach((u, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.5 + col * 6.4;
    const y = 1.2 + row * 2.7;
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x,
      y,
      w: 6.1,
      h: 2.5,
      fill: { color: C.background2 },
      rectRadius: 0.08,
    });
    slide.addText(u.n, {
      x: x + 0.3,
      y: y + 0.25,
      w: 5.5,
      h: 0.55,
      fontSize: 28,
      bold: true,
      color: C.accent1,
      margin: 0,
      isTextBox: true,
    });
    slide.addText(u.t, {
      x: x + 0.3,
      y: y + 0.85,
      w: 5.5,
      h: 0.4,
      fontSize: 18,
      bold: true,
      color: C.text1,
      margin: 0,
      isTextBox: true,
    });
    slide.addText(u.d, {
      x: x + 0.3,
      y: y + 1.3,
      w: 5.5,
      h: 0.9,
      fontSize: 14,
      color: C.text2,
      margin: 0,
      isTextBox: true,
    });
  });
  slide.addNotes("Unique: traps, H-MEM, bank, live Lightning miss. Do not claim the live 30-q bank.");

  slide = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Evidence" });
  slide.addText("Unproven citations per lane", { placeholder: "title" });
  slide.addChart(pres.charts.BAR, [
    { name: "Without shield", labels: ["FAST", "DEEP"], values: [50, 50] },
    { name: "With shield", labels: ["FAST", "DEEP"], values: [0, 0] },
  ], {
    x: 0.5,
    y: 1.15,
    w: 7.4,
    h: 5.5,
    barGrouping: "clustered",
    showValue: true,
    dataLabelPosition: "outEnd",
    chartColors: ["7A1F1F", "2F4A3C"],
    showLegend: true,
    legendPos: "b",
    showTitle: false,
    catAxisLabelColor: "3D342C",
    valAxisLabelColor: "3D342C",
    valGridLine: { color: "E8E0D4", size: 0.75 },
    catGridLine: { style: "none" },
    valAxisMaxValue: 60,
    valAxisMinValue: 0,
    catAxisLabelFontFace: "+mn-lt",
    valAxisLabelFontFace: "+mn-lt",
    dataLabelFontFace: "+mn-lt",
  });
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 8.15,
    y: 1.15,
    w: 4.65,
    h: 5.5,
    fill: { color: C.background2 },
    rectRadius: 0.08,
  });
  slide.addText("Percent of extracted cites Diké marked FALLO.", {
    x: 8.4,
    y: 1.45,
    w: 4.15,
    h: 1.2,
    fontSize: 16,
    color: C.text1,
    margin: 0,
    isTextBox: true,
  });
  slide.addText("Measured on 2 synthetic questions × 4 conditions with a scripted LLM. Not a production rate.", {
    x: 8.4,
    y: 2.8,
    w: 4.15,
    h: 1.6,
    fontSize: 15,
    color: C.text2,
    margin: 0,
    isTextBox: true,
  });
  slide.addText("Live 30-question Nightshift bank was skipped: the Windows VM did not accept TCP :8088 at packaging.", {
    x: 8.4,
    y: 4.55,
    w: 4.15,
    h: 1.7,
    fontSize: 14,
    color: C.accent1,
    margin: 0,
    isTextBox: true,
  });
  slide.addNotes("Keep the dashboard disclaimer. Never present 0.0 as a production estimate.");

  pres.addSection({ title: "Close" });
  slide = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Close" });
  slide.addText("Limits we will not paper over", { placeholder: "title" });
  const limits = [
    { t: "Dated corpus", d: "Twenty-five statutes. Municipal, procurement, transparency, traffic and Fintech law: the router abstains." },
    { t: "Proof, not merit", d: "Diké proves the article exists, has citable text, and was in force. It does not prove the argument." },
    { t: "Windows Runtime", d: "No Linux Nightshift. SAMPLE_MODE replays 27 Oct and is labeled in the UI. The prize receipt needs the VM." },
    { t: "Synthetic bank", d: "Dashboard copy is mandatory: figures are measured on synthetic items, not production." },
  ];
  limits.forEach((L, i) => {
    const y = 1.2 + i * 1.3;
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: 0.5,
      y,
      w: 12.3,
      h: 1.15,
      fill: { color: C.background2 },
      rectRadius: 0.08,
    });
    slide.addText(L.t, {
      x: 0.75,
      y: y + 0.18,
      w: 3.2,
      h: 0.8,
      fontSize: 18,
      bold: true,
      color: C.accent1,
      margin: 0,
      isTextBox: true,
    });
    slide.addText(L.d, {
      x: 4.1,
      y: y + 0.22,
      w: 8.4,
      h: 0.75,
      fontSize: 15,
      color: C.text1,
      margin: 0,
      isTextBox: true,
    });
  });
  slide.addNotes("Honesty is part of the product. SAMPLE_MODE banner is not optional.");

  slide = pres.addSlide({ masterName: "TITLE", sectionTitle: "Close" });
  slide.addText("Next: live bank, then the courtroom", { placeholder: "title" });
  slide.addText("Thirty live questions when Nightshift is up. More scenarios. A third party verifying the ZIP with no Runtime.", {
    placeholder: "subtitle",
  });
  slide.addText("Nemotron cites. Diké proves. The lawyer decides if the article supports the claim.", {
    x: 0.7,
    y: 4.4,
    w: 11.9,
    h: 0.8,
    fontSize: 18,
    color: C.background1,
    margin: 0,
    isTextBox: true,
  });
  slide.addNotes("Close on the division of labor. Ask for the NVIDIA prize on the live Lightning receipt.");

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
