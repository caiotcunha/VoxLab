/* VoxLab dashboard: static, no dependencies. Data: window.VOXLAB (site/data.js). */
(function () {
  "use strict";
  const D = window.VOXLAB;
  const state = { model: "qwen", cond: "fala" };
  const view = document.getElementById("view");
  const tip = document.getElementById("tip");
  const SVGNS = "http://www.w3.org/2000/svg";

  const PERIOD = { BOLSONARO: "Governo Bolsonaro", LULA: "Governo Lula" };
  const BLOC = { GOVERNMENT: "Governo", PIVOT: "Pivô", OPPOSITION: "Oposição" };
  const BLOC_CLASS = { GOVERNMENT: "c-gov", PIVOT: "c-piv", OPPOSITION: "c-opp" };
  const BLOC_VAR = { GOVERNMENT: "var(--s1)", PIVOT: "var(--s2)", OPPOSITION: "var(--s3)" };
  const GOV = {
    SUPPORT: ["Apoia", "c-pos"], CRITICIZE: ["Critica", "c-neg"], MIXED: ["Misto", "c-mid"],
    NEUTRAL: ["Neutro", "c-mid"], NOT_ADDRESSED: ["Não aborda", "c-none"], "": ["Inválido", "c-none"],
  };
  const PROP = {
    F: ["A favor", "c-pos"], A: ["Contra", "c-neg"], U: ["Direção incerta", "c-mid"],
    "-": ["Não se posiciona", "c-none"], "?": ["Incerto", "c-none"], x: ["Inválido", "c-none"],
  };
  const TYPE = {
    DEPUTY: "Deputado(a) federal", FEDERAL_EXECUTIVE: "Executivo federal", CIVIL_SOCIETY_OR_OTHER: "Sociedade civil / outro",
    SUBNATIONAL_OR_OTHER_STATE: "Outro órgão público", SUBNATIONAL_POLITICIAN: "Político(a) subnacional",
  };
  const GROUP_LABEL = (g) => g.startsWith("PARTY:") ? g.slice(6) : (TYPE[g] || g);

  // ---------- helpers ----------
  const run = () => `${state.model}|${state.cond}`;
  const R = () => D.results.runs[run()];
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (x, d = 2) => x == null ? "—" : (x > 0 && d ? "+" : "") + x.toFixed(d).replace(".", ",");
  const fmtp = (x, d = 2) => x == null ? "—" : x.toFixed(d).replace(".", ",");
  const pval = (p) => p == null ? "—" : p < 0.001 ? "< 0,001" : p.toFixed(3).replace(".", ",");
  const chip = (label, cls) => `<span class="chip ${cls}">${esc(label)}</span>`;
  const govChip = (g) => chip(...(GOV[g] || GOV[""]));
  const blocChip = (b) => b ? chip(BLOC[b], BLOC_CLASS[b]) : "";
  const fmtDate = (iso) => iso ? iso.split("-").reverse().join("/") : "—";

  function el(tag, attrs = {}, parent) {
    const node = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  }
  const MAIN_PARTIES = ["PT", "PSOL", "PCDOB", "PSB", "PDT", "MDB", "PSD", "UNIAO", "PP", "REPUBLICANOS", "PL", "NOVO"];
  const width = (node) => Math.max(260, Math.round(node.clientWidth - 28));
  function scale(d0, d1, r0, r1) { return (v) => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0); }
  function svg(w, h, label) {
    const s = el("svg", { viewBox: `0 0 ${w} ${h}`, class: "chart", role: "img", "aria-label": label });
    return s;
  }
  function text(parent, x, y, str, attrs = {}) {
    const t = el("text", { x, y, ...attrs }, parent);
    t.textContent = str;
    return t;
  }
  function yGrid(s, y, ticks, x0, x1, f = (v) => fmtp(v)) {
    const g = el("g", { class: "grid" }, s);
    for (const v of ticks) {
      el("line", { x1: x0, x2: x1, y1: y(v), y2: y(v) }, g);
      text(s, x0 - 6, y(v) + 4, f(v), { "text-anchor": "end" });
    }
  }
  function hover(node, html) {
    node.addEventListener("mousemove", (e) => {
      tip.innerHTML = html; tip.style.display = "block";
      const x = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
      tip.style.left = x + "px"; tip.style.top = (e.clientY + 14) + "px";
    });
    node.addEventListener("mouseleave", () => { tip.style.display = "none"; });
  }
  function tableView(headers, rows) {
    return `<details class="table-view"><summary>Ver como tabela</summary><div class="table-scroll"><table>
      <thead><tr>${headers.map((h) => `<th${h.num ? ' class="num"' : ""}>${esc(h.t ?? h)}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((r) => `<tr>${r.map((c, i) => `<td${headers[i].num ? ' class="num"' : ""}>${c}</td>`).join("")}</tr>`).join("")}</tbody>
      </table></div></details>`;
  }
  const blocOf = (v) => v == null ? "" : v >= D.results.bloc_thresholds[1] ? "GOVERNMENT" : v < D.results.bloc_thresholds[0] ? "OPPOSITION" : "PIVOT";
  const stanceOf = (h, a) => (D.stances[`${h}_${a}`] || {})[run()];

  // ---------- charts ----------
  function chartSlope(node) {
    const pg = D.results.party_governism;
    // Main parties only: the small ones crowd the labels and have few hearing appearances.
    const parties = MAIN_PARTIES.filter((p) => pg[`${p}|BOLSONARO`] != null && pg[`${p}|LULA`] != null);
    const W = width(node), H = 380, x0 = 44, x1 = W - 110, y = scale(0, 1, H - 30, 16);
    const s = svg(W, H, "Governismo por partido nas votações nominais, Bolsonaro e Lula");
    yGrid(s, y, [0, 0.25, 0.5, 0.75, 1], x0 - 10, x1 + 10);
    text(s, x0, H - 8, "Bolsonaro", { "text-anchor": "middle" });
    text(s, x1, H - 8, "Lula", { "text-anchor": "middle" });
    const ends = [];
    for (const p of parties) {
      const a = pg[`${p}|BOLSONARO`], b = pg[`${p}|LULA`], bloc = blocOf(b), col = BLOC_VAR[bloc];
      el("line", { x1: x0, x2: x1, y1: y(a), y2: y(b), stroke: col, "stroke-width": 2 }, s);
      el("circle", { cx: x0, cy: y(a), r: 4, fill: col }, s);
      el("circle", { cx: x1, cy: y(b), r: 4, fill: col }, s);
      const hit = el("line", { x1: x0, x2: x1, y1: y(a), y2: y(b), stroke: "transparent", "stroke-width": 12, class: "hit" }, s);
      hover(hit, `<b>${esc(p)}</b>Bolsonaro: ${fmtp(a)} · Lula: ${fmtp(b)}<br>Bloco sob Lula: ${BLOC[bloc]}`);
      ends.push({ p, b, ly: y(b) });
    }
    ends.sort((m, n) => m.ly - n.ly);
    for (let i = 1; i < ends.length; i++) ends[i].ly = Math.max(ends[i].ly, ends[i - 1].ly + 12);
    for (const e of ends) {
      el("line", { x1: x1 + 5, x2: x1 + 14, y1: y(e.b), y2: e.ly, stroke: "var(--grid)" }, s);
      text(s, x1 + 17, e.ly + 4, e.p);
    }
    node.appendChild(s);
    node.insertAdjacentHTML("beforeend", legendBlocs() + tableView(
      ["Partido", { t: "Bolsonaro", num: 1 }, { t: "Lula", num: 1 }, "Bloco sob Lula"],
      parties.map((p) => [esc(p), fmtp(pg[`${p}|BOLSONARO`]), fmtp(pg[`${p}|LULA`]), BLOC[blocOf(pg[`${p}|LULA`])]])));
  }
  function legendBlocs() {
    return `<div class="legend">${Object.keys(BLOC).map((b) => `<span><i style="background:${BLOC_VAR[b]}"></i>${BLOC[b]} (sob Lula)</span>`).join("")}</div>`;
  }

  function chartIntervals(node, cells, opts) {
    // cells: [{group, period, net, ci, n}]
    const groups = opts.groups, W = width(node), H = 60 + groups.length * 48, x0 = opts.labelWidth || 120, x1 = W - 20;
    const x = scale(-1, 1, x0, x1);
    const s = svg(W, H, opts.label);
    const g = el("g", { class: "grid" }, s);
    for (const v of [-1, -0.5, 0, 0.5, 1]) {
      el("line", { x1: x(v), x2: x(v), y1: 8, y2: H - 26 }, g);
      text(s, x(v), H - 10, fmt(v, v % 1 ? 1 : 0), { "text-anchor": "middle" });
    }
    el("line", { x1: x(0), x2: x(0), y1: 8, y2: H - 26, stroke: "var(--axis)", "stroke-width": 1.5 }, s);
    groups.forEach((grp, i) => {
      const yc = 30 + i * 48;
      text(s, x0 - 8, yc + 4, opts.groupLabel(grp), { "text-anchor": "end" });
      ["BOLSONARO", "LULA"].forEach((per, j) => {
        const c = cells.find((k) => k.group === grp && k.period === per);
        if (!c || c.net == null) return;
        const yy = yc + (j ? 8 : -8), col = j ? "var(--s2)" : "var(--s1)", faded = c.n < 5;
        if (c.ci) el("line", { x1: x(c.ci[0]), x2: x(c.ci[1]), y1: yy, y2: yy, stroke: col, "stroke-width": 2, opacity: faded ? 0.35 : 1 }, s);
        el("circle", { cx: x(c.net), cy: yy, r: 5, fill: col, stroke: "var(--surface)", "stroke-width": 2, opacity: faded ? 0.35 : 1 }, s);
        const hit = el("rect", { x: x0, y: yy - 7, width: x1 - x0, height: 14, class: "hit" }, s);
        hover(hit, `<b>${esc(opts.groupLabel(grp))} · ${PERIOD[per]}</b>Apoio líquido: ${fmt(c.net)}` +
          (c.ci ? `<br>IC 95%: ${fmt(c.ci[0])} a ${fmt(c.ci[1])}` : "") + `<br>n = ${c.n}${faded ? " (poucos casos)" : ""}`);
      });
    });
    node.appendChild(s);
    node.insertAdjacentHTML("beforeend",
      `<div class="legend"><span><i style="background:var(--s1)"></i>${PERIOD.BOLSONARO}</span><span><i style="background:var(--s2)"></i>${PERIOD.LULA}</span><span class="muted">esmaecido: n &lt; 5</span></div>` +
      tableView(["Grupo", "Período", { t: "Apoio líquido", num: 1 }, "IC 95%", { t: "n", num: 1 }],
        cells.filter((c) => c.net != null).map((c) => [esc(opts.groupLabel(c.group)), PERIOD[c.period], fmt(c.net),
          c.ci ? `${fmt(c.ci[0])} a ${fmt(c.ci[1])}` : "—", c.n])));
  }
  function cellsFrom(obj, keep) {
    return Object.entries(obj).map(([k, v]) => {
      const [group, period] = k.split("|");
      return { group, period, net: v.net_support, ci: v.ci95, n: v.n_addressed };
    }).filter((c) => !keep || keep(c));
  }

  function chartScatter(node, period) {
    const W = Math.max(260, node.clientWidth), H = 320, x0 = 44, x1 = W - 16, yTop = 14, yBot = H - 40;
    const x = scale(0, 1, x0, x1), y = scale(-1, 1, yBot, yTop);
    const s = svg(W, H, "Postura sobre o governo nas audiências versus governismo nas votações, por deputado");
    yGrid(s, y, [-1, -0.5, 0, 0.5, 1], x0, x1, (v) => fmt(v, v % 1 ? 1 : 0));
    for (const v of [0, 0.25, 0.5, 0.75, 1]) text(s, x(v), H - 22, fmtp(v), { "text-anchor": "middle" });
    text(s, (x0 + x1) / 2, H - 4, "Governismo nas votações nominais", { "text-anchor": "middle" });
    const rows = [];
    for (const d of Object.values(D.deputies)) {
      const sc = (d.scores[run()] || {})[period], per = d.periods[period];
      if (!sc || !per || per.governism == null) continue;
      rows.push({ d, sc, per });
      const bloc = blocOf(per.governism);
      const c = el("circle", { cx: x(per.governism), cy: y(sc.score), r: 3 + Math.min(sc.n, 6), fill: BLOC_VAR[bloc],
        "fill-opacity": 0.75, stroke: "var(--surface)", "stroke-width": 1.5, class: "hit" }, s);
      c.style.fill = BLOC_VAR[bloc];
      hover(c, `<b>${esc(d.name)} (${esc(per.party)})</b>Postura nas audiências: ${fmt(sc.score)} (${sc.n} aud.)<br>Governismo: ${fmtp(per.governism)} (${per.rollcall_n} votos)`);
      c.addEventListener("click", () => { location.hash = `#deputados/${d.id}`; });
    }
    node.appendChild(s);
    const st = ((R().rq2 || {}).speech_vs_vote_governism || {})[period] || {};
    node.insertAdjacentHTML("afterbegin", `<p class="muted" style="margin:0 0 4px">Spearman ρ = <b>${fmtp(st.rho)}</b> · n = ${st.n ?? "—"} · p ${pval(st.p)}</p>`);
    node.insertAdjacentHTML("beforeend", legendBlocs().replace(/ \(sob Lula\)/g, "") + tableView(
      ["Deputado", "Partido", { t: "Postura", num: 1 }, { t: "Audiências", num: 1 }, { t: "Governismo", num: 1 }],
      rows.sort((a, b) => a.d.name.localeCompare(b.d.name)).map((r) => [esc(r.d.name), esc(r.per.party), fmt(r.sc.score), r.sc.n, fmtp(r.per.governism)])));
  }

  function chartAgreement(node) {
    const rq1 = R().rq1, groups = [["party", "Partido"], ["bloc", "Bloco"]];
    const W = width(node), H = 240, x0 = 40, y = scale(0, 1, H - 40, 14), step = (W - x0) / 2;
    const s = svg(W, H, "Concordância entre pares de deputados na mesma proposição");
    yGrid(s, y, [0, 0.25, 0.5, 0.75, 1], x0, W - 10);
    const rows = [];
    groups.forEach(([key, label], i) => {
      const c = rq1[key]; if (!c) return;
      const cx = x0 + step * (i + 0.5);
      [["agreement_same_group", "n_pairs_same_group", "Mesmo", "var(--s1)"], ["agreement_diff_group", "n_pairs_diff_group", "Diferente", "var(--s2)"]]
        .forEach(([k, n, lab, col], j) => {
          const bx = cx + (j ? 4 : -60), v = c[k];
          const r = el("rect", { x: bx, y: y(v), width: 56, height: y(0) - y(v), rx: 4, fill: col, class: "hit" }, s);
          r.style.fill = col;
          hover(r, `<b>${label}: ${lab.toLowerCase()}</b>Concordância: ${fmtp(v)}<br>${c[n]} pares`);
        });
      text(s, cx, H - 22, label, { "text-anchor": "middle" });
      text(s, cx, H - 8, `p = ${pval(c.permutation_p)}`, { "text-anchor": "middle" });
      rows.push([label, fmtp(c.agreement_same_group), c.n_pairs_same_group, fmtp(c.agreement_diff_group), c.n_pairs_diff_group, pval(c.permutation_p)]);
    });
    node.appendChild(s);
    node.insertAdjacentHTML("beforeend",
      `<div class="legend"><span><i style="background:var(--s1)"></i>Mesmo grupo</span><span><i style="background:var(--s2)"></i>Grupos diferentes</span></div>` +
      tableView(["Grupo", { t: "Mesmo", num: 1 }, { t: "pares", num: 1 }, { t: "Diferente", num: 1 }, { t: "pares", num: 1 }, "p (permutação)"], rows));
  }

  // ---------- views ----------
  function viewGeral() {
    const nActors = D.hearings.reduce((a, h) => a + h.actors.length, 0);
    view.innerHTML = `
      <div class="kpis">
        <div class="card kpi"><div class="v">${D.hearings.length}</div><div class="l">audiências</div></div>
        <div class="card kpi"><div class="v">${nActors.toLocaleString("pt-BR")}</div><div class="l">participações</div></div>
        <div class="card kpi"><div class="v">${Object.keys(D.deputies).length}</div><div class="l">deputados com postura e votos</div></div>
        <div class="card kpi"><div class="v">${D.meta.calls.toLocaleString("pt-BR")}</div><div class="l">chamadas de LLM · US$ ${fmtp(D.meta.cost_usd)}</div></div>
      </div>
      <div class="grid">
        <section class="card" id="c-slope"><h2>Os partidos trocam de papel em 2023</h2><p class="note" style="margin:0 0 6px">Governismo nas votações nominais (votos iguais à orientação do governo). Não depende do modelo.</p></section>
        <section class="card" id="c-bloc"><h2>A postura sobre o governo se inverte</h2><p class="note" style="margin:0 0 6px">Apoio líquido ao governo vigente nas audiências (+1 apoia, −1 critica), por bloco do partido sob Lula; IC 95% por bootstrap de audiências.</p></section>
        <section class="card" id="c-scatter"><h2>A fala acompanha o voto</h2>
          <div class="seg" id="sc-period" style="margin-bottom:6px"><button data-v="LULA" aria-pressed="true">Lula</button><button data-v="BOLSONARO" aria-pressed="false">Bolsonaro</button></div>
          <div id="sc-body"></div><p class="note">Cada ponto é um deputado; tamanho = nº de audiências. Clique para abrir o perfil.</p></section>
        <section class="card" id="c-agree"><h2>Nas proposições em pauta, o partido pesa pouco</h2><p class="note" style="margin:0 0 6px">Concordância entre pares de deputados que se posicionaram sobre a mesma proposição na mesma audiência.</p></section>
      </div>`;
    chartSlope(document.getElementById("c-slope"));
    chartIntervals(document.getElementById("c-bloc"), cellsFrom(R().rq3.government_stance_by_lula_bloc || {}),
      { groups: ["GOVERNMENT", "PIVOT", "OPPOSITION"], groupLabel: (g) => BLOC[g], label: "Apoio líquido ao governo por bloco e período", labelWidth: 80 });
    const body = document.getElementById("sc-body");
    const seg = document.getElementById("sc-period");
    const draw = (p) => { body.innerHTML = ""; chartScatter(body, p); };
    seg.addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      seg.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b));
      draw(b.dataset.v);
    });
    draw("LULA");
    chartAgreement(document.getElementById("c-agree"));
  }

  function viewAudiencias(id) {
    view.innerHTML = `<div class="split">
      <div><input class="search" id="q" type="search" placeholder="Buscar por assunto ou participante" aria-label="Buscar audiência">
        <div class="filters"><select id="fp" aria-label="Período"><option value="">Todos os períodos</option><option value="BOLSONARO">Bolsonaro</option><option value="LULA">Lula</option></select></div>
        <div class="list" id="hl"></div></div>
      <div id="hd"></div></div>`;
    const q = document.getElementById("q"), fp = document.getElementById("fp"), list = document.getElementById("hl");
    const current = id || D.hearings[D.hearings.length - 1].id;
    function renderList() {
      const term = q.value.trim().toLowerCase();
      const items = D.hearings.filter((h) => (!fp.value || h.period === fp.value) &&
        (!term || h.topic.toLowerCase().includes(term) || h.actors.some((a) => a.name.toLowerCase().includes(term))));
      list.innerHTML = items.slice().reverse().map((h) => `<button data-id="${h.id}" aria-current="${h.id === current}">
        ${esc(h.topic)}<div class="sub">${fmtDate(h.date)} · ${h.actors.length} participantes</div></button>`).join("") ||
        `<p class="muted" style="padding:10px">Nenhuma audiência encontrada.</p>`;
    }
    list.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) location.hash = `#audiencias/${b.dataset.id}`; });
    q.addEventListener("input", renderList); fp.addEventListener("change", renderList);
    renderList();
    renderHearing(D.hearings.find((h) => h.id === current));
  }

  function renderHearing(h) {
    const other = state.model === "qwen" ? "llama" : "qwen";
    const rows = h.actors.map((a) => {
      const st = stanceOf(h.id, a.i), alt = (D.stances[`${h.id}_${a.i}`] || {})[`${other}|${state.cond}`];
      const props = h.propositions.map((p) => {
        const code = st ? st.p[p.id] : null;
        const differs = st && alt && alt.p[p.id] !== code;
        return code == null ? '<span class="muted">—</span>' : `<span class="${differs ? "diff" : ""}" title="${differs ? "O outro modelo discorda" : ""}">${chip(...PROP[code])}</span>`;
      });
      const gov = st ? `<span class="${alt && alt.g !== st.g ? "diff" : ""}">${govChip(st.g)}</span>` : '<span class="muted">sem fala</span>';
      const who = a.dep ? `<a href="#deputados/${a.dep}">${esc(a.name)}</a>` : esc(a.name);
      const party = a.party ? `${esc(a.party)} ${blocChip(a.bloc)}` : "";
      const text = state.cond === "fala" ? (a.speech ? esc(a.speech) + (a.speech_chars > a.speech.length ? ` <span class="muted">[… ${a.speech_chars.toLocaleString("pt-BR")} caracteres no total]</span>` : "") : '<span class="muted">Turnos não localizados na transcrição.</span>') : esc(a.summary);
      return `<tr><td>${who}<div class="muted" style="font-size:12px">${esc(TYPE[a.type] || a.type)}${a.cargo ? " · " + esc(a.cargo) : ""}</div>${party}
        <details><summary class="muted" style="font-size:12px;cursor:pointer">${state.cond === "fala" ? "Trecho da fala" : "Resumo da notícia"}</summary><div class="speech">${text}</div></details></td>
        ${props.map((p) => `<td>${p}</td>`).join("")}<td>${gov}</td></tr>`;
    });
    document.getElementById("hd").innerHTML = `<div class="card">
      <h2>${esc(h.topic)}</h2><p class="muted" style="margin:0 0 8px">${fmtDate(h.date)} (data da notícia) · ${PERIOD[h.period]} · audiência ${esc(h.id)}</p>
      <h3>Proposições extraídas</h3><ol class="props">${h.propositions.map((p) => `<li><b>${p.id}</b> ${esc(p.text)}</li>`).join("")}</ol>
      <div class="table-scroll"><table><thead><tr><th>Participante</th>${h.propositions.map((p) => `<th>${p.id}</th>`).join("")}<th>Governo vigente</th></tr></thead>
      <tbody>${rows.join("")}</tbody></table></div>
      <p class="note">Contorno tracejado: o outro modelo (${other === "qwen" ? "Qwen" : "Llama"}) deu rótulo diferente. Proposições extraídas por Qwen2.5-72B a partir da notícia.</p></div>`;
  }

  function deputyIndex() {
    const idx = {};
    for (const h of D.hearings) for (const a of h.actors) {
      if (a.type !== "DEPUTY") continue;
      const key = a.dep || `n:${a.id}`;
      (idx[key] = idx[key] || { key, dep: a.dep, name: a.name, party: a.party, apps: [] }).apps.push({ h, a });
    }
    for (const d of Object.values(idx)) d.both = new Set(d.apps.map((x) => x.h.period)).size === 2;
    return idx;
  }

  function viewDeputados(id) {
    const idx = deputyIndex();
    const all = Object.values(idx).sort((a, b) => (b.both - a.both) || (b.apps.length - a.apps.length) || a.name.localeCompare(b.name));
    const current = idx[id] || idx[`n:${id}`] || all[0];
    view.innerHTML = `<div class="split">
      <div><input class="search" id="q" type="search" placeholder="Buscar deputado ou partido" aria-label="Buscar deputado">
        <div class="list" id="dl"></div></div><div id="dd"></div></div>`;
    const q = document.getElementById("q"), list = document.getElementById("dl");
    function renderList() {
      const term = q.value.trim().toLowerCase();
      list.innerHTML = all.filter((d) => !term || d.name.toLowerCase().includes(term) || (d.party || "").toLowerCase() === term)
        .map((d) => `<button data-k="${esc(d.key)}" aria-current="${d === current}">${esc(d.name)} <span class="muted">${esc(d.party)}</span>
          <div class="sub">${d.apps.length} audiência(s)${d.both ? " · presente nos dois governos" : ""}</div></button>`).join("");
    }
    list.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) location.hash = `#deputados/${b.dataset.k.replace(/^n:/, "")}`; });
    q.addEventListener("input", renderList);
    renderList();
    renderDeputy(current);
  }

  function renderDeputy(d) {
    const info = D.deputies[d.dep] || { periods: {}, scores: {} };
    const apps = d.apps.slice().sort((x, y) => x.h.date.localeCompare(y.h.date));
    const periods = ["BOLSONARO", "LULA"].map((p) => {
      const per = info.periods[p], sc = (info.scores[run()] || {})[p];
      return `<tr><td>${PERIOD[p]}</td><td>${per ? esc(per.party) : "—"}</td><td class="num">${per ? fmtp(per.governism) : "—"}</td><td class="num">${sc ? fmt(sc.score) : "—"}</td><td class="num">${sc ? sc.n : "—"}</td></tr>`;
    }).join("");
    const box = document.getElementById("dd");
    box.innerHTML = `<div class="card"><h2>${esc(d.name)}</h2>
      <p class="muted" style="margin:0 0 8px">${d.dep ? `ID Câmara ${esc(d.dep)}` : "Não casado com a base da Câmara"}</p>
      <div class="table-scroll"><table><thead><tr><th>Período</th><th>Partido</th><th class="num">Governismo (votos)</th><th class="num">Postura nas audiências</th><th class="num">Audiências</th></tr></thead><tbody>${periods}</tbody></table></div>
      <h3 style="margin-top:14px">Postura sobre o governo vigente, audiência a audiência</h3><div id="tl"></div>
      <div class="table-scroll"><table><thead><tr><th>Data</th><th>Audiência</th><th>Governo vigente</th><th>Governo anterior</th></tr></thead><tbody>
      ${apps.map(({ h, a }) => { const st = stanceOf(h.id, a.i); return `<tr><td>${fmtDate(h.date)}</td><td><a href="#audiencias/${h.id}">${esc(h.topic)}</a></td><td>${st ? govChip(st.g) : '<span class="muted">sem fala</span>'}</td><td>${st ? govChip(st.pg) : ""}</td></tr>`; }).join("")}
      </tbody></table></div></div>`;
    timeline(document.getElementById("tl"), apps);
  }

  function timeline(node, apps) {
    const W = Math.max(260, node.clientWidth), H = 170, x0 = 86, x1 = W - 14;
    const t = (iso) => Date.parse(iso);
    const lo = t("2021-10-01"), hi = t("2024-06-30"), x = scale(lo, hi, x0, x1);
    const levels = [["SUPPORT", "Apoia"], ["MIXED", "Misto/neutro"], ["CRITICIZE", "Critica"], ["NOT_ADDRESSED", "Não aborda"]];
    const yOf = (g) => 20 + 32 * (g === "NEUTRAL" ? 1 : levels.findIndex((l) => l[0] === g));
    const s = svg(W, H, "Postura sobre o governo em cada audiência ao longo do tempo");
    const g = el("g", { class: "grid" }, s);
    levels.forEach(([k, lab]) => { el("line", { x1: x0, x2: x1, y1: yOf(k), y2: yOf(k) }, g); text(s, x0 - 8, yOf(k) + 4, lab, { "text-anchor": "end" }); });
    const tr = x(t("2023-01-01"));
    el("line", { x1: tr, x2: tr, y1: 8, y2: H - 30, stroke: "var(--axis)", "stroke-dasharray": "4 3" }, s);
    text(s, tr + 4, H - 34, "posse de Lula");
    for (const yr of [2022, 2023, 2024]) text(s, x(t(`${yr}-01-01`)), H - 10, String(yr), { "text-anchor": "middle" });
    for (const { h, a } of apps) {
      const st = stanceOf(h.id, a.i); if (!st || !st.g) continue;
      const cls = (GOV[st.g] || GOV[""])[1];
      const c = el("circle", { cx: x(t(h.date)), cy: yOf(st.g), r: 6, class: "hit", "stroke-width": 2, stroke: "var(--surface)" }, s);
      c.style.fill = cls === "c-pos" ? "var(--pos)" : cls === "c-neg" ? "var(--neg)" : cls === "c-mid" ? "var(--mid)" : "var(--surface)";
      if (cls === "c-none") c.setAttribute("stroke", "var(--muted)");
      hover(c, `<b>${fmtDate(h.date)}</b>${esc(h.topic)}<br>${(GOV[st.g] || GOV[""])[0]}`);
      c.addEventListener("click", () => { location.hash = `#audiencias/${h.id}`; });
    }
    node.appendChild(s);
  }

  function viewPartidos() {
    const by = R().rq3.government_stance_by_group;
    const groups = [...new Set(Object.keys(by).map((k) => k.split("|")[0]))]
      .filter((g) => Object.entries(by).some(([k, v]) => k.startsWith(g + "|") && v.n_addressed >= 5))
      .sort((a, b) => ((by[`${b}|LULA`] || {}).net_support ?? -9) - ((by[`${a}|LULA`] || {}).net_support ?? -9));
    view.innerHTML = `<div class="card" id="pp"><h2>Apoio líquido ao governo vigente, por partido e grupo</h2>
      <p class="note" style="margin:0 0 6px">Deputados agrupados pelo partido na data da audiência; demais participantes pelo tipo. Mostra grupos com n ≥ 5 em algum período.</p></div>
      <div class="card" style="margin-top:16px"><h2>Postura sobre o governo anterior (sob Lula)</h2><div id="prev"></div></div>`;
    chartIntervals(document.getElementById("pp"), cellsFrom(by, (c) => groups.includes(c.group)),
      { groups, groupLabel: GROUP_LABEL, label: "Apoio líquido ao governo por partido e período", labelWidth: 150 });
    const prev = R().rq3.previous_government_stance_by_group;
    document.getElementById("prev").innerHTML = `<div class="table-scroll"><table><thead><tr><th>Grupo</th><th class="num">Apoio líquido ao governo anterior</th><th class="num">n</th></tr></thead><tbody>${
      Object.entries(prev).filter(([k, v]) => k.endsWith("|LULA") && v.n_addressed >= 5).sort((a, b) => a[1].net_support - b[1].net_support)
        .map(([k, v]) => `<tr><td>${esc(GROUP_LABEL(k.split("|")[0]))}</td><td class="num">${fmt(v.net_support)}</td><td class="num">${v.n_addressed}</td></tr>`).join("")}</tbody></table></div>`;
  }

  function viewMetodologia() {
    const rq4 = D.results.rq4, k = (o) => o ? `${fmtp(o.cohens_kappa)} (n = ${o.n})` : "—";
    view.innerHTML = `<div class="grid">
      <section class="card"><h2>Como os dados foram produzidos</h2><ol>
        <li>Para cada audiência, 1–3 <b>proposições centrais</b> foram extraídas da notícia por Qwen2.5-72B (prompt congelado).</li>
        <li>Para cada participante, a <b>fala literal</b> (seus turnos na transcrição) ou o <b>resumo da notícia</b> foi classificada por dois modelos: postura em cada proposição e em relação ao governo federal vigente e aos anteriores. O modelo não recebe nome, partido nem cargo.</li>
        <li>Deputados foram casados com a base da Câmara; partido datado e <b>governismo</b> vêm das votações nominais 2022–2024.</li>
        <li>Temperatura 0, respostas brutas em cache, ${D.meta.calls.toLocaleString("pt-BR")} chamadas, custo real US$ ${fmtp(D.meta.cost_usd)}.</li></ol>
        <p class="muted" style="font-size:12px">SHA-256 dos prompts: proposições <code>${D.meta.prompt_sha256.propositions.slice(0, 12)}…</code>, postura <code>${D.meta.prompt_sha256.stance.slice(0, 12)}…</code></p></section>
      <section class="card"><h2>Robustez</h2><div class="table-scroll"><table><thead><tr><th>Comparação</th><th class="num">κ governo</th><th class="num">κ proposições</th></tr></thead><tbody>
        <tr><td>Qwen × Llama, fala</td><td class="num">${k(rq4["models|speech"].government_stance)}</td><td class="num">${k(rq4["models|speech"].proposition_stance)}</td></tr>
        <tr><td>Qwen × Llama, resumo</td><td class="num">${k(rq4["models|lds_summary"].government_stance)}</td><td class="num">${k(rq4["models|lds_summary"].proposition_stance)}</td></tr>
        ${Object.entries(D.meta.models).map(([key, m]) => `<tr><td>Fala × resumo, ${key === "qwen" ? "Qwen" : "Llama"}</td><td class="num">${k(rq4[`conditions|${m}`].government_stance)}</td><td class="num">${k(rq4[`conditions|${m}`].proposition_stance)}</td></tr>`).join("")}
        </tbody></table></div><p class="note">Resumos jornalísticos raramente registram a postura sobre o governo; a validação externa (votações) favorece a fala literal.</p></section>
      <section class="card"><h2>Limites</h2><ul>
        <li>Sem anotação humana para estes alvos: todos os rótulos são previsões de modelo.</li>
        <li>Apenas 35 das 206 audiências são anteriores a 2023; poucos deputados de oposição e pivô nesse período.</li>
        <li>Data da notícia, não da audiência; audiências selecionadas pela cobertura da Agência Câmara.</li>
        <li>A própria fala pode revelar a filiação do orador mesmo com o nome ocultado.</li>
        <li>Convidados são escolhidos por requerimento dos parlamentares (viés de convite).</li></ul></section>
      <section class="card"><h2>Fontes</h2><ul>
        <li>PublicHearingBR (Fernandes et al., 2024), <a href="https://arxiv.org/abs/2410.07495">arXiv:2410.07495</a>.</li>
        <li>Câmara dos Deputados, <a href="https://dadosabertos.camara.leg.br/swagger/api.html">Dados Abertos</a>: votações, votos e orientações 2022–2024.</li>
        <li>Documentação completa: <code>docs/party_alignment.md</code> e <code>docs/literature_review.md</code> no repositório.</li></ul></section></div>`;
  }

  // ---------- routing & controls ----------
  const ROUTES = { geral: viewGeral, audiencias: viewAudiencias, deputados: viewDeputados, partidos: viewPartidos, metodologia: viewMetodologia };
  function route() {
    const [name, arg] = (location.hash.slice(1) || "geral").split("/");
    const fn = ROUTES[name] || viewGeral;
    document.querySelectorAll("nav.tabs a").forEach((a) => a.setAttribute("aria-current", a.getAttribute("href") === `#${ROUTES[name] ? name : "geral"}` ? "page" : "false"));
    tip.style.display = "none";
    fn(arg ? decodeURIComponent(arg) : undefined);
  }
  function bindSeg(id, key) {
    const seg = document.getElementById(id);
    seg.addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      state[key] = b.dataset.v;
      seg.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b));
      route();
    });
  }
  bindSeg("ctl-model", "model");
  bindSeg("ctl-cond", "cond");
  window.addEventListener("hashchange", route);
  let resizeTimer, lastWidth = window.innerWidth;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (window.innerWidth !== lastWidth) { lastWidth = window.innerWidth; route(); } }, 200);
  });
  route();
})();
