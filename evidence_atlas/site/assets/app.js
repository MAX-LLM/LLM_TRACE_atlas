(() => {
  "use strict";

  const data = window.ATLAS_DATA;
  if (!data) throw new Error("Atlas data bundle was not loaded");

  const PAGE_SIZE = 50;
  const TYPE_ORDER = [
    "dataset_provenance", "dataset_validation_level", "clinical_translation_stage",
    "outcome", "safety", "oversight", "trial_evidence", "human_evidence",
    "clinical_specialty", "llm_use_mode", "model", "model_access",
    "public_dataset", "synthetic_data"
  ];

  const studyById = new Map(data.studies.map(study => [study.id, study]));
  const entityById = new Map(data.entities.map(entity => [entity.id, entity]));
  const state = {
    view: "map",
    search: "",
    year: "all",
    level: "all",
    stage: "all",
    provenance: "all",
    access: "all",
    includePreprints: false,
    showLowInformation: false,
    page: 1,
    selectedStudy: data.studies.find(study => study.publication_status !== "Preprint")?.id || null,
    selectedEntity: null,
    wikiType: "synthesis",
  };

  const el = id => document.getElementById(id);
  const escapeHtml = value => String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  const shortLabel = value => String(value)
    .replace(/^Level \d:\s*/, "")
    .replace(/^Stage [A-C]:\s*/, "");
  const pct = (value, total = state.includePreprints ? data.meta.total_with_preprints : data.meta.study_count) => `${(value / total * 100).toFixed(1)}%`;

  function fillSelect(select, values, allLabel) {
    select.innerHTML = "";
    select.add(new Option(allLabel, "all"));
    values.forEach(value => select.add(new Option(shortLabel(value), value)));
  }

  function uniqueValues(field) {
    return [...new Set(data.studies.map(study => study[field]).filter(Boolean))].sort((a, b) => String(a).localeCompare(String(b)));
  }

  function initializeControls() {
    el("headerCount").textContent = data.meta.study_count.toLocaleString();
    el("headerMeta").textContent = `${data.meta.publication_window} · title-and-abstract evidence profiles`;
    el("disclaimer").textContent = data.meta.disclaimer;
    fillSelect(el("yearFilter"), uniqueValues("year").sort((a, b) => b - a), "All years");
    fillSelect(el("levelFilter"), uniqueValues("dataset_validation_level"), "All validation levels");
    fillSelect(el("stageFilter"), uniqueValues("clinical_translation_stage"), "All translation stages");
    fillSelect(el("provenanceFilter"), uniqueValues("dataset_provenance"), "All provenance categories");
    fillSelect(el("accessFilter"), uniqueValues("model_access_group"), "All model-access categories");

    const wikiTypes = [{ value: "synthesis", label: "Synthesis" }]
      .concat(TYPE_ORDER.map(type => ({ value: type, label: data.type_labels[type] })));
    el("wikiType").innerHTML = "";
    wikiTypes.forEach(item => el("wikiType").add(new Option(item.label, item.value)));

    el("searchInput").addEventListener("input", event => {
      state.search = event.target.value.trim().toLowerCase();
      state.page = 1;
      renderAll();
    });
    [
      ["yearFilter", "year"], ["levelFilter", "level"], ["stageFilter", "stage"],
      ["provenanceFilter", "provenance"], ["accessFilter", "access"]
    ].forEach(([id, key]) => el(id).addEventListener("change", event => {
      state[key] = event.target.value;
      state.page = 1;
      renderAll();
    }));
    document.querySelectorAll(".tab-button").forEach(button => button.addEventListener("click", () => setView(button.dataset.view)));
    el("resetButton").addEventListener("click", resetFilters);
    el("includePreprints").addEventListener("change", event => {
      state.includePreprints = event.target.checked;
      state.page = 1;
      renderAll();
    });
    el("showLowInformation").addEventListener("change", event => {
      state.showLowInformation = event.target.checked;
      updateGraph(filteredStudies());
    });
    el("exportButton").addEventListener("click", exportCsv);
    el("previousPage").addEventListener("click", () => { state.page -= 1; renderStudies(); });
    el("nextPage").addEventListener("click", () => { state.page += 1; renderStudies(); });
    el("wikiType").addEventListener("change", event => {
      state.wikiType = event.target.value;
      state.selectedEntity = null;
      renderWiki();
    });
  }

  function matchesSearch(study) {
    if (!state.search) return true;
    const haystack = [
      study.id, study.title, study.journal, study.model_names,
      study.model_names_normalized.join(" "), study.named_dataset_or_setting,
      study.clinical_task, study.clinical_specialty.join(" "), study.rationale
    ].join(" ").toLowerCase();
    return haystack.includes(state.search);
  }

  function filteredStudies() {
    return data.studies.filter(study =>
      (state.includePreprints || study.publication_status !== "Preprint") &&
      matchesSearch(study) &&
      (state.year === "all" || String(study.year) === String(state.year)) &&
      (state.level === "all" || study.dataset_validation_level === state.level) &&
      (state.stage === "all" || study.clinical_translation_stage === state.stage) &&
      (state.provenance === "all" || study.dataset_provenance === state.provenance) &&
      (state.access === "all" || study.model_access_group === state.access)
    );
  }

  function setView(view) {
    state.view = view;
    document.querySelectorAll(".tab-button").forEach(button => button.classList.toggle("active", button.dataset.view === view));
    document.querySelectorAll(".view").forEach(viewElement => viewElement.classList.remove("active"));
    el(`${view}View`).classList.add("active");
    if (view === "map") window.setTimeout(() => cy.resize(), 0);
    if (view === "studies") renderStudies();
    if (view === "wiki") renderWiki();
  }

  function resetFilters() {
    state.search = "";
    state.year = state.level = state.stage = state.provenance = state.access = "all";
    state.includePreprints = false;
    state.showLowInformation = false;
    state.page = 1;
    el("searchInput").value = "";
    el("includePreprints").checked = false;
    el("showLowInformation").checked = false;
    ["yearFilter", "levelFilter", "stageFilter", "provenanceFilter", "accessFilter"].forEach(id => { el(id).value = "all"; });
    renderAll();
  }

  function deterministicPositions(nodes) {
    const grouped = new Map(TYPE_ORDER.map(type => [type, []]));
    nodes.forEach(node => {
      if (!grouped.has(node.data.type)) grouped.set(node.data.type, []);
      grouped.get(node.data.type).push(node);
    });
    const activeTypes = [...grouped.entries()].filter(([, items]) => items.length).map(([type]) => type);
    const positions = {};
    activeTypes.forEach((type, typeIndex) => {
      const angle = -Math.PI / 2 + typeIndex * (Math.PI * 2 / activeTypes.length);
      const centerX = 620 * Math.cos(angle);
      const centerY = 390 * Math.sin(angle);
      grouped.get(type).sort((a, b) => b.data.count - a.data.count || a.data.label.localeCompare(b.data.label));
      grouped.get(type).forEach((node, index) => {
        const columns = Math.ceil(Math.sqrt(grouped.get(type).length));
        const row = Math.floor(index / columns);
        const column = index % columns;
        positions[node.data.id] = {
          x: centerX + (column - (columns - 1) / 2) * 90,
          y: centerY + (row - 1) * 70,
        };
      });
    });
    return positions;
  }

  const graphElements = [
    ...data.graph.nodes.map(node => ({ group: "nodes", data: { ...node, activeCount: node.count } })),
    ...data.graph.edges.map(edge => ({ group: "edges", data: { ...edge, activeWeight: edge.weight } })),
  ];
  const positions = deterministicPositions(graphElements.filter(item => item.group === "nodes"));
  graphElements.filter(item => item.group === "nodes").forEach(item => { item.position = positions[item.data.id]; });

  const cy = cytoscape({
    container: el("cy"),
    elements: graphElements,
    layout: { name: "preset", fit: true, padding: 55 },
    minZoom: 0.25,
    maxZoom: 2.3,
    wheelSensitivity: 0.18,
    style: [
      {
        selector: "node",
        style: {
          "background-color": "data(color)",
          "width": `mapData(activeCount, 1, ${data.meta.study_count}, 20, 62)`,
          "height": `mapData(activeCount, 1, ${data.meta.study_count}, 20, 62)`,
          "label": "data(label)",
          "font-family": "Arial, Helvetica, sans-serif",
          "font-size": 10,
          "color": "#20252b",
          "text-wrap": "wrap",
          "text-max-width": 115,
          "text-valign": "bottom",
          "text-margin-y": 7,
          "border-width": 1,
          "border-color": "#ffffff",
          "overlay-opacity": 0,
        }
      },
      {
        selector: "edge",
        style: {
          "line-color": "#adb6c0",
          "width": "mapData(activeWeight, 1, 800, 0.5, 8)",
          "opacity": 0.32,
          "curve-style": "bezier",
          "overlay-opacity": 0,
        }
      },
      { selector: ".inactive", style: { "display": "none" } },
      { selector: "node:selected", style: { "border-width": 4, "border-color": "#20252b" } },
      { selector: ".faded", style: { "opacity": 0.08 } },
      { selector: ".highlighted", style: { "opacity": 1, "z-index": 999 } },
    ]
  });

  cy.on("tap", "node", event => {
    state.selectedEntity = event.target.id();
    renderEntityDetail(entityById.get(state.selectedEntity));
    cy.elements().addClass("faded");
    event.target.closedNeighborhood().removeClass("faded").addClass("highlighted");
  });
  cy.on("tap", event => {
    if (event.target === cy) {
      cy.elements().removeClass("faded highlighted");
      state.selectedEntity = null;
      renderMapOverview();
    }
  });

  function updateGraph(studies) {
    const activeIds = new Set(studies.map(study => study.id));
    let visibleNodes = 0;
    let visibleEdges = 0;
    cy.batch(() => {
      cy.nodes().forEach(node => {
        const count = node.data("study_ids").reduce((sum, id) => sum + (activeIds.has(id) ? 1 : 0), 0);
        const label = String(node.data("label") || "").trim().toLowerCase();
        const lowInformation = label.startsWith("unclear") || label === "not reported" || label === "no use reported" || label === "none stated";
        const hidden = count === 0 || (!state.showLowInformation && lowInformation);
        node.data("activeCount", count);
        node.toggleClass("inactive", hidden);
        if (!hidden) visibleNodes += 1;
      });
      cy.edges().forEach(edge => {
        const weight = edge.data("study_ids").reduce((sum, id) => sum + (activeIds.has(id) ? 1 : 0), 0);
        edge.data("activeWeight", weight);
        const hidden = weight === 0 || edge.source().hasClass("inactive") || edge.target().hasClass("inactive");
        edge.toggleClass("inactive", hidden);
        if (!hidden) visibleEdges += 1;
      });
    });
    el("graphEmpty").hidden = visibleNodes > 0;
    el("graphNodeCount").textContent = `${visibleNodes.toLocaleString()} entities`;
    el("graphEdgeCount").textContent = `${visibleEdges.toLocaleString()} relationships`;
    cy.elements().removeClass("faded highlighted");
    if (visibleNodes) cy.fit(cy.elements(":visible"), 50);
  }

  function renderLegend() {
    const graphTypes = [...new Set(data.graph.nodes.map(node => node.type))]
      .sort((a, b) => TYPE_ORDER.indexOf(a) - TYPE_ORDER.indexOf(b));
    el("legend").innerHTML = graphTypes.map(type => `
      <span class="legend-item"><span class="legend-swatch" style="background:${data.type_colors[type]}"></span>${escapeHtml(data.type_labels[type])}</span>
    `).join("");
  }

  function profileRows(study) {
    return [
      ["Publication status", study.publication_status],
      ["Dataset validation", shortLabel(study.dataset_validation_level)],
      ["Clinical translation", shortLabel(study.clinical_translation_stage)],
      ["Dataset provenance", study.dataset_provenance],
      ["Models", study.model_names],
      ["Model access", study.model_access_group],
      ["LLM use mode", study.llm_use_mode.join("; ")],
      ["Clinical specialty", study.clinical_specialty.join("; ")],
      ["Named dataset or setting", study.named_dataset_or_setting],
      ["Clinical task", study.clinical_task],
      ["Trial evidence (title/abstract)", study.trial_evidence],
      ["Human evaluation", study.human_evidence.join("; ")],
      ["Synthetic data", study.synthetic_data],
      ["Oversight and governance", study.oversight.join("; ")],
      ["Safety evaluation", study.safety.join("; ")],
      ["Outcomes", study.outcomes.join("; ")],
    ];
  }

  function sourceActions(study) {
    const links = [];
    if (study.doi_url) links.push(`<a href="${escapeHtml(study.doi_url)}" target="_blank" rel="noopener">Open DOI</a>`);
    if (study.pubmed_url) links.push(`<a href="${escapeHtml(study.pubmed_url)}" target="_blank" rel="noopener">Open PubMed</a>`);
    return links.length ? `<div class="source-actions">${links.join("")}</div>` : "";
  }

  function studyHtml(study) {
    return `
      <p class="eyebrow">${escapeHtml(study.id)} · ${escapeHtml(study.year)}</p>
      <h2>${escapeHtml(study.title)}</h2>
      <p class="lede">${escapeHtml(study.journal)}</p>
      <dl class="profile-list">${profileRows(study).map(([label, value]) => `
        <div class="profile-row"><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>
      `).join("")}</dl>
      <h3>Profile rationale</h3>
      <p class="lede">${escapeHtml(study.rationale)}</p>
      ${sourceActions(study)}
    `;
  }

  function renderStudyDetail(studyId, targetId = "studyPanel") {
    const study = studyById.get(studyId);
    if (!study) return;
    state.selectedStudy = studyId;
    el(targetId).innerHTML = studyHtml(study);
    document.querySelectorAll("#studyTableBody tr").forEach(row => row.classList.toggle("selected", row.dataset.studyId === studyId));
  }

  function distributionFor(entity, field, studyIds = entity.study_ids) {
    const counts = new Map();
    studyIds.forEach(id => {
      const value = studyById.get(id)?.[field] || "Unclear";
      counts.set(value, (counts.get(value) || 0) + 1);
    });
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }

  function miniBars(items, total) {
    const maximum = Math.max(...items.map(([, count]) => count), 1);
    return `<div class="mini-bars">${items.map(([label, count]) => `
      <div class="mini-bar-row">
        <span>${escapeHtml(shortLabel(label))}</span>
        <span class="mini-bar-track"><span class="mini-bar-fill" style="width:${count / maximum * 100}%"></span></span>
        <span class="mini-bar-count">${count.toLocaleString()}</span>
      </div>
    `).join("")}</div>`;
  }

  function linkedStudyList(studyIds, limit = 12) {
    const studies = studyIds.map(id => studyById.get(id)).filter(Boolean)
      .sort((a, b) => b.year - a.year || a.id.localeCompare(b.id));
    return `<ul class="study-links">${studies.slice(0, limit).map(study => `
      <li><button type="button" data-open-study="${study.id}">${escapeHtml(study.title)}</button><small>${study.year} · ${study.id}</small></li>
    `).join("")}</ul>${studies.length > limit ? `<p class="lede">Showing ${limit} of ${studies.length.toLocaleString()} linked reports.</p>` : ""}`;
  }

  function bindStudyLinks(container) {
    container.querySelectorAll("[data-open-study]").forEach(button => button.addEventListener("click", () => {
      state.selectedStudy = button.dataset.openStudy;
      setView("studies");
      renderStudies();
      renderStudyDetail(state.selectedStudy);
    }));
  }

  function renderEntityDetail(entity) {
    if (!entity) return;
    const visibleIds = new Set(filteredStudies().map(study => study.id));
    const activeIds = entity.study_ids.filter(id => visibleIds.has(id));
    const activeCount = activeIds.length;
    const panel = el("detailPanel");
    panel.innerHTML = `
      <p class="eyebrow">${escapeHtml(entity.type_label)}</p>
      <h2>${escapeHtml(entity.label)}</h2>
      <div class="metric-large"><strong>${activeCount.toLocaleString()}</strong><span>linked reports · ${pct(activeCount)}</span></div>
      <h3>Dataset validation</h3>
      ${miniBars(distributionFor(entity, "dataset_validation_level", activeIds), activeCount)}
      <h3>Clinical translation</h3>
      ${miniBars(distributionFor(entity, "clinical_translation_stage", activeIds), activeCount)}
      <h3>Recent linked studies</h3>
      ${linkedStudyList(activeIds)}
      <div class="source-actions"><button id="openWikiEntity" class="command-button" type="button">Open wiki entry</button></div>
    `;
    bindStudyLinks(panel);
    el("openWikiEntity").addEventListener("click", () => {
      state.wikiType = entity.type;
      state.selectedEntity = entity.id;
      el("wikiType").value = entity.type;
      setView("wiki");
    });
  }

  function renderMapOverview() {
    const panel = el("detailPanel");
    const m = data.metrics;
    panel.innerHTML = `
      <p class="eyebrow">Evidence synthesis</p>
      <h2>Validation and clinical translation remain weakly connected</h2>
      <p class="lede">The network compiles controlled evidence fields across ${data.meta.study_count.toLocaleString()} included reports.</p>
      <div class="metric-large"><strong>${m.broader_stage_c.toLocaleString()}</strong><span>reports combined broader validation with Stage C evidence</span></div>
      <dl class="profile-list">
        <div class="profile-row"><dt>Retrospective or offline</dt><dd>${m.stage_a.toLocaleString()} reports (${pct(m.stage_a)})</dd></div>
        <div class="profile-row"><dt>Single dataset or setting</dt><dd>${m.level_1.toLocaleString()} reports (${pct(m.level_1)})</dd></div>
        <div class="profile-row"><dt>Local or institutional data only</dt><dd>${m.local_only.toLocaleString()} reports (${pct(m.local_only)})</dd></div>
        <div class="profile-row"><dt>Patient outcomes or experience</dt><dd>${m.patient_outcome.toLocaleString()} reports (${pct(m.patient_outcome)})</dd></div>
      </dl>
    `;
  }

  function renderStudies() {
    const studies = filteredStudies().sort((a, b) => b.year - a.year || a.id.localeCompare(b.id));
    const pages = Math.max(1, Math.ceil(studies.length / PAGE_SIZE));
    state.page = Math.min(Math.max(state.page, 1), pages);
    const start = (state.page - 1) * PAGE_SIZE;
    const pageStudies = studies.slice(start, start + PAGE_SIZE);
    el("studyTableBody").innerHTML = pageStudies.map(study => `
      <tr data-study-id="${study.id}">
        <td>${study.year}</td>
        <td><div class="study-title">${escapeHtml(study.title)}</div><div class="study-meta">${study.id} · ${escapeHtml(study.publication_status)} · ${escapeHtml(study.journal)}</div></td>
        <td>${escapeHtml(shortLabel(study.dataset_validation_level))}</td>
        <td>${escapeHtml(shortLabel(study.clinical_translation_stage))}</td>
        <td>${escapeHtml(study.dataset_provenance)}</td>
      </tr>
    `).join("");
    el("pageStatus").textContent = `Page ${state.page} of ${pages} · ${studies.length.toLocaleString()} reports`;
    el("previousPage").disabled = state.page <= 1;
    el("nextPage").disabled = state.page >= pages;
    el("studyTableBody").querySelectorAll("tr").forEach(row => row.addEventListener("click", () => renderStudyDetail(row.dataset.studyId)));
    const selectedIsVisible = pageStudies.some(study => study.id === state.selectedStudy);
    if (!selectedIsVisible && pageStudies.length) state.selectedStudy = pageStudies[0].id;
    if (state.selectedStudy) renderStudyDetail(state.selectedStudy);
  }

  const synthesisEntries = [
    { id: "field-overview", label: "Field overview" },
    { id: "clinical-translation-gap", label: "Clinical translation gap" },
    { id: "dataset-transportability", label: "Dataset transportability" },
    { id: "outcomes-safety-governance", label: "Outcomes, safety, and governance" },
    { id: "model-ecosystem", label: "Model ecosystem" },
  ];

  function renderSynthesis(id = "field-overview") {
    const m = data.metrics;
    const entries = {
      "field-overview": [
        "Field overview",
        `The atlas contains ${m.total.toLocaleString()} included reports. ${m.from_2024.toLocaleString()} (${pct(m.from_2024)}) were published from 2024 onwards, but evidence maturity remains concentrated in single-setting retrospective evaluation.`,
        `${m.stage_a.toLocaleString()} reports (${pct(m.stage_a)}) were retrospective or offline, and ${m.level_1.toLocaleString()} (${pct(m.level_1)}) evaluated one EHR dataset, cohort, institution, or health system.`
      ],
      "clinical-translation-gap": [
        "Clinical translation gap",
        `Only ${m.broader_stage_c.toLocaleString()} reports (${pct(m.broader_stage_c)}) combined broader dataset validation with integrated, interventional, or outcome-impact evidence.`,
        `Only ${m.mixed_stage_c.toLocaleString()} combined Stage C evidence with both public and local data. Dataset breadth and translation stage answer different questions and should not be collapsed into one hierarchy.`
      ],
      "dataset-transportability": [
        "Dataset transportability",
        `${m.local_only.toLocaleString()} reports (${pct(m.local_only)}) used only local or institutional EHR data, while provenance was unclear in ${m.provenance_unclear.toLocaleString()} (${pct(m.provenance_unclear)}).`,
        "Local data can capture authentic workflows, but independently sourced evaluation is needed to establish transportability. Public datasets improve reproducibility but are not inherently representative."
      ],
      "outcomes-safety-governance": [
        "Outcomes, safety, and governance",
        `Task performance was reported in ${m.task_performance.toLocaleString()} reports (${pct(m.task_performance)}), compared with patient outcomes or experience in ${m.patient_outcome.toLocaleString()} (${pct(m.patient_outcome)}).`,
        `Governance was not described in ${m.governance_unreported.toLocaleString()} reports and safety evaluation was not described in ${m.safety_unreported.toLocaleString()}. These are reporting signals rather than proof of absence.`
      ],
      "model-ecosystem": [
        "Model ecosystem",
        "Model pages connect normalised model families to access categories, use modes, specialties, and translation stages.",
        "Edges show study-level co-reporting, not an intrinsic access property of every model in a multi-model report. Ambiguous model names and access routes remain labelled as unclear rather than being inferred."
      ]
    };
    const [title, finding, interpretation] = entries[id] || entries["field-overview"];
    el("wikiArticle").innerHTML = `
      <p class="eyebrow">Synthesis</p><h1>${escapeHtml(title)}</h1>
      <div class="finding-band">${escapeHtml(finding)}</div>
      <p>${escapeHtml(interpretation)}</p>
      <h2>Scope</h2><p class="lede">${escapeHtml(data.meta.disclaimer)}</p>
    `;
  }

  function renderWikiEntity(entity) {
    const visibleIds = new Set(filteredStudies().map(study => study.id));
    const activeIds = entity.study_ids.filter(id => visibleIds.has(id));
    el("wikiArticle").innerHTML = `
      <p class="eyebrow">${escapeHtml(entity.type_label)}</p>
      <h1>${escapeHtml(entity.label)}</h1>
      <div class="finding-band"><strong>${activeIds.length.toLocaleString()} linked reports</strong> (${pct(activeIds.length)} of the included evidence base).</div>
      <h2>Dataset validation</h2>${miniBars(distributionFor(entity, "dataset_validation_level", activeIds), activeIds.length)}
      <h2>Clinical translation</h2>${miniBars(distributionFor(entity, "clinical_translation_stage", activeIds), activeIds.length)}
      <h2>Linked studies</h2>${linkedStudyList(activeIds, 40)}
      <h2>Scope</h2><p class="lede">${escapeHtml(data.meta.disclaimer)}</p>
    `;
    bindStudyLinks(el("wikiArticle"));
  }

  function renderWiki() {
    const type = state.wikiType;
    let entries;
    if (type === "synthesis") {
      entries = synthesisEntries;
    } else {
      const visibleIds = new Set(filteredStudies().map(study => study.id));
      entries = data.entities.filter(entity => entity.type === type)
        .map(entity => ({
          id: entity.id,
          label: entity.label,
          count: entity.study_ids.filter(id => visibleIds.has(id)).length,
        }))
        .filter(entity => entity.count > 0)
        .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
    }
    el("wikiEntityList").innerHTML = entries.map(entry => `
      <button type="button" class="wiki-entity-button ${state.selectedEntity === entry.id ? "active" : ""}" data-wiki-id="${entry.id}">
        <span>${escapeHtml(entry.label)}</span><span>${entry.count ? entry.count.toLocaleString() : ""}</span>
      </button>
    `).join("");
    el("wikiEntityList").querySelectorAll("button").forEach(button => button.addEventListener("click", () => {
      state.selectedEntity = button.dataset.wikiId;
      if (type === "synthesis") renderSynthesis(state.selectedEntity);
      else renderWikiEntity(entityById.get(state.selectedEntity));
      renderWikiListSelection();
    }));
    if (type === "synthesis") {
      if (!synthesisEntries.some(entry => entry.id === state.selectedEntity)) state.selectedEntity = "field-overview";
      renderSynthesis(state.selectedEntity);
    } else {
      if (!entries.some(entry => entry.id === state.selectedEntity)) state.selectedEntity = entries[0]?.id || null;
      if (state.selectedEntity) renderWikiEntity(entityById.get(state.selectedEntity));
    }
    renderWikiListSelection();
  }

  function renderWikiListSelection() {
    el("wikiEntityList").querySelectorAll("button").forEach(button => button.classList.toggle("active", button.dataset.wikiId === state.selectedEntity));
  }

  function csvCell(value) {
    const text = Array.isArray(value) ? value.join("; ") : String(value ?? "");
    return `"${text.replaceAll('"', '""')}"`;
  }

  function exportCsv() {
    const rows = filteredStudies();
    const fields = ["id", "publication_status", "year", "title", "journal", "doi", "dataset_validation_level", "clinical_translation_stage", "dataset_provenance", "model_names", "model_access_group", "llm_use_mode", "clinical_specialty", "clinical_task", "trial_evidence", "safety", "outcomes"];
    const csv = [fields.join(","), ...rows.map(study => fields.map(field => csvCell(study[field])).join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "llm_ehr_evidence_atlas_filtered.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  function renderAll() {
    const studies = filteredStudies();
    const headlineCount = state.includePreprints ? data.meta.total_with_preprints : data.meta.study_count;
    el("headerCount").textContent = headlineCount.toLocaleString();
    el("headerLabel").textContent = state.includePreprints ? "reports including preprints" : "peer-reviewed reports";
    el("headerMeta").textContent = state.includePreprints
      ? `${data.meta.publication_window} · ${data.meta.preprint_count.toLocaleString()} additional preprints shown`
      : `${data.meta.publication_window} · peer-reviewed primary evidence map`;
    el("filteredCount").textContent = studies.length.toLocaleString();
    updateGraph(studies);
    if (state.selectedEntity) renderEntityDetail(entityById.get(state.selectedEntity));
    else renderMapOverview();
    if (state.view === "studies") renderStudies();
  }

  initializeControls();
  renderLegend();
  renderMapOverview();
  renderAll();
})();
