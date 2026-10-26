(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const page = $("#page-content");
  const labels = {
    overview: "개요", materials: "자료 라이브러리", retrieval: "근거 검색",
    graph: "지식 그래프", decisions: "설계 판단", experiments: "실험 기록", system: "시스템 상태"
  };
  const decisionKinds = {
    hardware: { label: "하드웨어", eyebrow: "HARDWARE REVIEW", fields: [
      ["target", "검토 대상", "text", "비교할 장치·구성·토폴로지"],
      ["workload", "워크로드", "text", "모델, 배치, 시퀀스 길이 등"],
      ["constraints", "제약 조건", "textarea", "예산, 전력, 메모리, 냉각 등 알려진 조건"]
    ] },
    kernel: { label: "커널", eyebrow: "KERNEL REVIEW", fields: [
      ["operation", "연산", "text", "예: attention, reduction, GEMM"],
      ["dtype", "데이터 형식", "text", "알려진 입력·누산 자료형"],
      ["layout", "메모리 배치", "text", "텐서 차원, stride, 정렬 등"],
      ["constraints", "제약 조건", "textarea", "ISA·정확도·성능 목표 등"]
    ] },
    experiment: { label: "실험", eyebrow: "EXPERIMENT REVIEW", fields: [
      ["hypothesis", "가설", "text", "확인하려는 변경과 기대 효과"],
      ["workload", "워크로드", "text", "실험에 사용할 실제 입력·모델"],
      ["metrics", "측정 지표", "text", "예: latency, throughput, power"],
      ["constraints", "통제 조건", "textarea", "비교 시 고정할 환경·방법"]
    ] },
    knowledge: { label: "지식 질문", eyebrow: "KNOWLEDGE REVIEW", fields: [
      ["topic", "주제", "text", "검토할 구성 요소나 주장"],
      ["known_evidence", "알고 있는 근거", "textarea", "관련 자료, 버전, 관찰을 적어 주세요"],
      ["decision_needed", "필요한 판단", "text", "답을 얻은 뒤 결정할 사항"]
    ] }
  };
  let metricRowCounter = 0;

  const state = {
    view: "overview", stats: null, statsError: null, capabilities: null, capabilitiesError: null, overviewDecisionsLoading: false,
    overviewMaterials: { items: [], total: null, loading: false, error: null },
    materials: { items: [], total: null, offset: 0, limit: 10, query: "", category: "", loading: false, error: null },
    materialDetail: null, selectedMaterialId: null, materialDetailLoading: false, materialDetailError: null,
    retrieval: { query: "", category: "", purpose: "auto", mode: "", loading: false, error: null, response: null },
    graph: { query: "", loading: false, error: null, response: null, selectedId: null },
    decisions: { items: [], loading: false, error: null, selectedId: null, detail: null, detailError: null, loadingDetail: false },
    decisionKind: "hardware", jobs: readStoredJobs(), jobResult: null,
    experiments: { items: [], loading: false, error: null, compare: null, compareLoading: false, compareError: null, baselineId: "", candidateId: "" },
    hardwareValidation: { result: null, error: null, loading: false },
    health: null, healthError: null
  };

  function el(tag, className = "", text = undefined) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined && text !== null) item.textContent = String(text);
    return item;
  }
  function add(parent, ...children) { children.flat().filter(Boolean).forEach(child => parent.append(child)); return parent; }
  function text(tag, value, className = "") { return el(tag, className, value); }
  function isObject(value) { return value !== null && typeof value === "object" && !Array.isArray(value); }
  function listOf(value) {
    if (Array.isArray(value)) return value;
    if (isObject(value) && Array.isArray(value.items)) return value.items;
    return [];
  }
  function valueAt(object, ...keys) {
    if (!isObject(object)) return undefined;
    for (const key of keys) if (object[key] !== undefined && object[key] !== null && object[key] !== "") return object[key];
    return undefined;
  }
  function asText(value, fallback = "—") {
    if (value === undefined || value === null || value === "") return fallback;
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
    return safeJson(value);
  }
  function safeJson(value, spaces = 2) {
    try {
      return JSON.stringify(value, (key, item) => /(?:api.?key|secret|token|password|credential|authorization)/i.test(key) ? "[redacted]" : item, spaces) ?? "";
    } catch (_) { return String(value); }
  }
  function safeError(error) {
    let message = error instanceof Error ? error.message : String(error ?? "요청에 실패했습니다.");
    message = message.replace(/\bBearer\s+[A-Za-z0-9._~+/-]+=*/gi, "Bearer [redacted]")
      .replace(/\b(sk-[A-Za-z0-9_-]{8,}|hf_[A-Za-z0-9]{8,}|AIza[\w-]{15,})\b/g, "[redacted]")
      .replace(/((?:api[_-]?key|secret|token|password|credential|authorization)\s*[:=]\s*)[^,\s]+/gi, "$1[redacted]");
    return message.slice(0, 520) || "요청에 실패했습니다.";
  }
  function safeUrl(value) {
    if (typeof value !== "string" || !value.trim()) return null;
    try {
      const parsed = new URL(value, window.location.origin);
      return (parsed.protocol === "http:" || parsed.protocol === "https:") && !parsed.username && !parsed.password ? parsed.href : null;
    } catch (_) { return null; }
  }
  function link(label, url, className = "external-link") {
    const href = safeUrl(url);
    if (!href) return text("span", label || url || "출처 링크 없음", "muted small");
    const anchor = el("a", className, label || href);
    anchor.href = href;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    return anchor;
  }
  function apiError(payload, status) {
    const detail = valueAt(payload, "detail", "message", "error");
    if (Array.isArray(detail)) return detail.map(item => typeof item === "string" ? item : asText(item)).join(" · ").slice(0, 520);
    if (detail !== undefined) return asText(detail).slice(0, 520);
    return `HTTP ${status}`;
  }
  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set("Accept", "application/json");
    if (options.body !== undefined) headers.set("Content-Type", "application/json");
    let response;
    try {
      response = await fetch(path, { ...options, headers, body: options.body === undefined ? undefined : JSON.stringify(options.body) });
    } catch (error) {
      throw new Error(error instanceof TypeError ? "서비스에 연결할 수 없습니다. 실행 상태를 확인해 주세요." : safeError(error));
    }
    const raw = await response.text();
    let payload = null;
    if (raw) {
      try { payload = JSON.parse(raw); }
      catch (_) {
        const snippet = raw.trim();
        payload = { detail: snippet.startsWith("<") ? `HTTP ${response.status}: 읽을 수 있는 응답이 아닙니다.` : snippet.slice(0, 360) };
      }
    }
    if (!response.ok) throw new Error(apiError(payload, response.status));
    return payload;
  }
  function fmtCount(value) {
    if (value === undefined || value === null || value === "") return "—";
    const number = Number(value);
    return Number.isFinite(number) ? new Intl.NumberFormat("ko-KR").format(number) : "—";
  }
  function fmtDate(value) {
    if (!value) return "날짜 없음";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value) : new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(parsed);
  }
  function positiveStatus(value) {
    if (typeof value === "string" && negativeStatus(value)) return false;
    if (value === true) return true;
    return typeof value === "string" && /^(ready|available|configured|connected|enabled|active|valid|ok|success|succeeded|complete|completed|indexed|ingested|true)(?:\b.*)?$/i.test(value.trim());
  }
  function negativeStatus(value) {
    if (value === false) return true;
    if (typeof value !== "string") return false;
    const status = value.trim().replaceAll("_", " ").replaceAll("-", " ");
    return /\b(?:missing|unavailable|disabled|inactive|invalid|off|unsupported|unimplemented|failed|false)\b/i.test(status)
      || /\bnot\s+(?:yet\s+)?(?:configured|implemented|available|enabled|supported|active|valid|ready)\b/i.test(status);
  }
  function providerRows(providers) {
    const rows = el("div", "provider-list");
    const entries = isObject(providers) ? Object.entries(providers) : [];
    if (!entries.length) { rows.append(emptyState("Provider 설정이 없습니다", "서버가 제공자 설정 정보를 반환하지 않았습니다.")); return rows; }
    entries.forEach(([name, value]) => {
      const row = el("div", "provider-row");
      const hasModelId = typeof value === "string";
      const statusValue = isObject(value) ? valueAt(value, "status", "state", "available", "configured") : undefined;
      const detailValue = isObject(value) ? valueAt(value, "provider", "model", "name", "detail", "message") ?? safeJson(value, 0) : value;
      const stateText = hasModelId ? (value ? "model ID 선택됨" : "model ID 없음") : statusValue === undefined ? "상태 미확인" : typeof statusValue === "boolean" ? (statusValue ? "사용 가능" : "사용 불가") : asText(statusValue);
      const tone = hasModelId ? "" : positiveStatus(statusValue) ? " is-ready" : negativeStatus(statusValue) ? " is-off" : "";
      add(row, text("span", name, "provider-name"), text("span", asText(detailValue), "provider-value"), text("span", stateText, `provider-state${tone}`));
      rows.append(row);
    });
    return rows;
  }
  function shortText(value, max = 180) {
    const str = asText(value, "");
    return str.length > max ? `${str.slice(0, max - 1)}…` : str;
  }
  function statValue(data, key) { return isObject(data) && data[key] !== undefined && data[key] !== null ? fmtCount(data[key]) : "—"; }
  function pageHeading(kicker, title, description, actions = []) {
    const wrap = el("div", "page-heading");
    const copy = el("div", "page-heading-copy");
    add(copy, text("span", kicker, "eyebrow"), text("h1", title), text("p", description));
    wrap.append(copy);
    if (actions.length) {
      const actionBox = el("div", "heading-actions");
      actions.forEach(action => actionBox.append(action));
      wrap.append(actionBox);
    }
    return wrap;
  }
  function button(label, onClick, className = "button button-secondary", type = "button") {
    const item = el("button", className, label);
    item.type = type;
    if (onClick) item.addEventListener("click", onClick);
    return item;
  }
  function surface(title, subtitle = "", className = "surface") {
    const card = el("section", className);
    const header = el("div", "surface-header");
    const copy = el("div");
    add(copy, text("h2", title), subtitle ? text("p", subtitle) : null);
    header.append(copy);
    card.append(header);
    return { card, header, body: el("div", "surface-body") };
  }
  function loadingState(message = "실제 데이터를 불러오는 중입니다.") {
    const box = el("div", "loading-state");
    add(box, el("span", "loading-dot"), text("strong", "불러오는 중"), text("p", message));
    return box;
  }
  function emptyState(title, description, action = null) {
    const box = el("div", "empty-state");
    const glyph = el("span", "empty-glyph");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", "M5 5.75A1.75 1.75 0 0 1 6.75 4h7.1L19 9.15v9.1A1.75 1.75 0 0 1 17.25 20h-10A2.25 2.25 0 0 1 5 17.75zM13.5 4v5.5H19M8.5 13h7M8.5 16h5");
    svg.append(path); glyph.append(svg);
    add(box, glyph, text("strong", title), text("p", description));
    if (action) box.append(action);
    return box;
  }
  function errorState(message, retry) {
    const box = el("div", "error-state");
    add(box, text("span", "!", "error-icon"), text("strong", "요청을 완료하지 못했습니다."), text("p", safeError(message)));
    if (retry) box.append(button("다시 시도", retry, "button button-secondary button-small"));
    return box;
  }
  function setConnection(online) {
    const pill = $("#connection-state");
    pill.classList.toggle("is-online", online === true);
    pill.classList.toggle("is-offline", online === false);
    pill.classList.toggle("is-pending", online === null);
    $("#connection-label").textContent = online === true ? "데이터 연결됨" : online === false ? "데이터 연결 확인 필요" : "데이터 연결 확인 중";
  }
  function toast(message, error = false) {
    const item = text("div", safeError(message), `toast${error ? " is-error" : ""}`);
    $("#toast-region").append(item);
    window.setTimeout(() => item.remove(), 4300);
  }
  function goTo(view, updateHash = true) {
    if (!labels[view]) return;
    if (updateHash && window.location.hash !== `#${view}`) window.history.pushState(null, "", `#${view}`);
    state.view = view;
    $$("[data-view]").forEach(item => {
      const active = item.dataset.view === view;
      item.classList.toggle("is-active", active);
      if (item.matches(".nav-item")) {
        if (active) item.setAttribute("aria-current", "page");
        else item.removeAttribute("aria-current");
      }
    });
    $("#view-label").textContent = labels[view];
    closeMobileNav();
    renderCurrentView();
    page.focus({ preventScroll: true });
  }
  function closeMobileNav() {
    $("#sidebar").classList.remove("is-open");
    $("#mobile-backdrop").hidden = true;
    $("#mobile-menu").setAttribute("aria-expanded", "false");
    $("#mobile-menu").setAttribute("aria-label", "탐색 메뉴 열기");
  }
  function openMaterialFromSearch(id) {
    state.selectedMaterialId = String(id);
    state.materialDetail = null;
    state.materialDetailError = null;
    state.materialDetailLoading = true;
    goTo("materials");
    loadMaterialDetail(String(id));
  }

  async function loadOverview() {
    state.statsError = null;
    state.capabilitiesError = null;
    state.overviewDecisionsLoading = true;
    state.overviewMaterials.loading = true; state.overviewMaterials.error = null;
    renderOverview();
    const [statsResult, capsResult, decisionsResult, materialsResult] = await Promise.allSettled([
      api("/api/stats"), api("/api/capabilities"), api("/api/decisions"), api("/api/materials?offset=0&limit=4")
    ]);
    if (statsResult.status === "fulfilled") { state.stats = statsResult.value; state.statsError = null; }
    else state.statsError = safeError(statsResult.reason);
    if (capsResult.status === "fulfilled") { state.capabilities = capsResult.value; state.capabilitiesError = null; }
    else state.capabilitiesError = safeError(capsResult.reason);
    if (decisionsResult.status === "fulfilled") { state.decisions.items = listOf(decisionsResult.value); state.decisions.error = null; }
    else { state.decisions.items = []; state.decisions.error = safeError(decisionsResult.reason); }
    state.overviewDecisionsLoading = false;
    if (materialsResult.status === "fulfilled") {
      state.overviewMaterials.items = listOf(materialsResult.value);
      const total = materialsResult.value?.total;
      state.overviewMaterials.total = total !== undefined && total !== null && total !== "" && Number.isFinite(Number(total)) ? Number(total) : null;
      state.overviewMaterials.error = null;
    } else { state.overviewMaterials.items = []; state.overviewMaterials.error = safeError(materialsResult.reason); }
    state.overviewMaterials.loading = false;
    setConnection(statsResult.status === "fulfilled");
    if (state.view === "overview") renderOverview();
  }
  function renderOverview() {
    page.replaceChildren();
    const hero = el("section", "overview-hero");
    const copy = el("div", "hero-copy");
    add(copy, text("span", "HARDWARE · KERNEL · EXPERIMENT", "hero-kicker"),
      text("h1", "출처에서 근거를 거쳐\n설계 판단까지"),
      text("p", "실제 DSE 자료와 인용을 확인하고, 하드웨어·커널·실험 질문의 판단 과정을 기록합니다. 근거가 부족한 지점은 모르는 항목과 지식 공백으로 남깁니다."));
    const aside = el("div", "hero-aside");
    add(aside, text("span", "P1 · MATERIAL PILOT", "hero-aside-label"),
      text("strong", "자료 파일럿 범위의 검토 보조"),
      text("p", "인용은 자료 속 주장을 추적합니다. 독립 검증, 실제 하드웨어 실행, B300 성능 측정을 대신하지 않습니다."));
    add(hero, copy, aside);
    page.append(hero);

    const statGrid = el("div", "stat-grid");
    const metrics = [
      ["materials", "자료", "출처 등록 수", "#0969da"],
      ["chunks", "근거 조각", "검색 가능한 구간", "#8250df"],
      ["claims", "주장", "자료 구간과 연결된 주장", "#1a7f37"],
      ["entities", "엔티티", "typed graph entity", "#bf8700"],
      ["edges", "관계", "typed graph relation", "#0969da"],
      ["decisions", "설계 판단", "기록된 판단", "#8250df"],
      ["gaps", "지식 공백", "기록된 gap", "#9a6700"],
      ["jobs", "작업", "job queue 항목", "#59636e"],
      ["experiments", "실험", "등록된 실험", "#1a7f37"]
    ];
    metrics.forEach(([key, label, foot, accent]) => {
      const card = el("div", "stat-card"); card.style.setProperty("--stat-accent", accent);
      const value = state.stats ? statValue(state.stats, key) : state.statsError ? "—" : null;
      add(card, text("div", label, "stat-label"), value === null ? el("span", "stat-value stat-skeleton") : text("strong", value, "stat-value"), text("div", foot, "stat-foot"));
      statGrid.append(card);
    });
    page.append(statGrid);

    const categoryPanel = surface("자료 범위와 분포", "등록한 자료의 주제 분포와 수집 범위를 살펴봅니다.");
    categoryPanel.body.className = "surface-body";
    if (state.statsError) categoryPanel.body.append(errorState(state.statsError, loadOverview));
    else if (!state.stats) categoryPanel.body.append(loadingState("개요 통계를 확인하고 있습니다."));
    else {
      const categories = Array.isArray(state.stats.category_counts) ? state.stats.category_counts : [];
      if (!categories.length) categoryPanel.body.append(emptyState("표시할 자료가 없습니다", "자료가 등록되면 실제 분류와 범위가 여기에 나타납니다."));
      else {
        const rows = el("div", "category-list");
        const maximum = Math.max(1, ...categories.map(item => Number(item.count) || 0));
        categories.forEach(item => {
          const row = el("div", "category-row");
          const name = text("span", asText(item.category), "category-name");
          const track = el("span", "category-track");
          const fill = el("span", "category-fill");
          fill.style.width = `${Math.max(0, Math.min(100, ((Number(item.count) || 0) / maximum) * 100))}%`;
          track.append(fill);
          add(row, name, track, text("span", fmtCount(item.count), "category-count")); rows.append(row);
        });
        categoryPanel.body.append(rows);
      }
      const scopes = Array.isArray(state.stats.scope_counts) ? state.stats.scope_counts : [];
      if (scopes.length) {
        categoryPanel.body.append(text("h3", "수집 범위", "detail-section-title"));
        const scopeRows = el("div", "category-list");
        const scopeMax = Math.max(1, ...scopes.map(item => Number(item.count) || 0));
        scopes.forEach(item => {
          const row = el("div", "category-row"); const track = el("span", "category-track"); const fill = el("span", "category-fill");
          fill.style.width = `${Math.max(0, Math.min(100, ((Number(item.count) || 0) / scopeMax) * 100))}%`; track.append(fill);
          add(row, text("span", asText(item.scope), "category-name"), track, text("span", fmtCount(item.count), "category-count")); scopeRows.append(row);
        });
        categoryPanel.body.append(scopeRows);
      }
    }
    categoryPanel.card.append(categoryPanel.body);

    const providerPanel = surface("Provider 설정", "선택된 model ID를 표시합니다. provider 연결 상태는 여기서 확인되지 않습니다.");
    const providerBody = providerPanel.body;
    if (state.statsError) providerBody.append(errorState(state.statsError, loadOverview));
    else if (!state.stats) providerBody.append(loadingState("provider 상태를 확인하고 있습니다."));
    else {
      providerBody.append(providerRows(state.stats.providers));
    }
    providerPanel.card.append(providerBody);
    const provenancePanel = surface("자료 출처와 상태", state.overviewMaterials.total === null ? "보관 자료 일부와 원문 연결" : `${fmtCount(state.overviewMaterials.total)}건 보관 · 일부 자료 표시`);
    if (state.overviewMaterials.loading) provenancePanel.body.append(loadingState("자료 출처와 처리 상태를 불러옵니다."));
    else if (state.overviewMaterials.error) provenancePanel.body.append(errorState(state.overviewMaterials.error, loadOverview));
    else if (!state.overviewMaterials.items.length) provenancePanel.body.append(emptyState("자료 출처가 없습니다", "현재 보관된 자료가 없습니다."));
    else {
      const sourceRows = el("div", "overview-sources");
      state.overviewMaterials.items.forEach(material => {
        const row = el("article", "overview-source");
        const title = el("button", "overview-source-title", asText(valueAt(material, "title", "name"), "제목 없음")); title.type = "button";
        const id = valueAt(material, "id");
        title.disabled = id === undefined;
        title.addEventListener("click", () => { if (id !== undefined) openMaterialFromSearch(id); });
        add(row, title, text("span", `${asText(valueAt(material, "category"), "category 없음")} · ${asText(valueAt(material, "status"), "처리 상태 없음")}`, "overview-source-meta"));
        const summary = valueAt(material, "summary"); if (summary) row.append(text("p", shortText(summary, 125), "overview-source-summary"));
        const source = valueAt(material, "source");
        const sourceUrl = valueAt(material, "url", "source_url") ?? valueAt(source, "url") ?? (typeof source === "string" && safeUrl(source) ? source : undefined);
        if (sourceUrl) row.append(link("원문 출처", sourceUrl));
        sourceRows.append(row);
      });
      provenancePanel.body.append(sourceRows);
    }
    provenancePanel.card.append(provenancePanel.body);
    const overviewGrid = el("div", "grid-three");
    overviewGrid.append(categoryPanel.card, providerPanel.card, provenancePanel.card);
    page.append(overviewGrid);

    const history = surface("최근 설계 판단", "최근 질문과 판단 시점", "surface overview-section");
    const historyBody = history.body;
    const recent = state.decisions.items.slice(0, 4);
    if (state.overviewDecisionsLoading) historyBody.append(loadingState("최근 판단 이력을 확인하고 있습니다."));
    else if (state.decisions.error) historyBody.append(errorState(state.decisions.error, loadOverview));
    else if (!recent.length) historyBody.append(emptyState("기록된 판단이 없습니다", "설계 질문을 실행하면 처리 상태와 근거가 기록됩니다.", button("판단 시작하기", () => goTo("decisions"), "button button-secondary button-small")));
    else {
      const list = el("div", "history-list");
      recent.forEach(item => {
        const id = valueAt(item, "id", "decision_id");
        const entry = el("button", "history-item"); entry.type = "button";
        add(entry, text("span", `${asText(valueAt(item, "kind"), "판단")} · ${fmtDate(valueAt(item, "created_at", "createdAt"))}`, "history-topline"), text("span", shortText(valueAt(item, "question", "title"), 150), "history-question"));
        entry.addEventListener("click", () => { goTo("decisions"); if (id !== undefined) loadDecisionDetail(id); });
        list.append(entry);
      });
      historyBody.append(list);
    }
    history.card.append(historyBody); page.append(history.card);

    const note = el("div", "scope-note");
    add(note, text("span", "i", "scope-mark"), text("span", "결과의 범위를 확인하세요. 인용된 논문·문서 주장은 출처의 주장으로 남습니다. HAT의 허용 여부는 buildability를 뜻하지 않고, 시뮬레이터 결과는 측정값이 아닙니다.", ""));
    page.append(note);
  }

  function categoryOptions(select, selected = "", includeAll = true) {
    const categories = Array.isArray(state.stats?.category_counts) ? state.stats.category_counts.map(item => asText(item.category, "")).filter(Boolean) : [];
    if (!categories.length) return;
    select.replaceChildren();
    if (includeAll) select.append(new Option("전체", ""));
    categories.forEach(category => select.append(new Option(category, category)));
    select.value = categories.includes(selected) ? selected : "";
  }

  async function loadMaterials() {
    const model = state.materials;
    model.loading = true; model.error = null;
    if (state.view === "materials") renderMaterials();
    const params = new URLSearchParams({ offset: String(model.offset), limit: String(model.limit) });
    if (model.query.trim()) params.set("q", model.query.trim());
    if (model.category) params.set("category", model.category);
    try {
      const response = await api(`/api/materials?${params.toString()}`);
      model.items = listOf(response);
      const total = response?.total;
      model.total = total !== undefined && total !== null && total !== "" && Number.isFinite(Number(total)) ? Number(total) : null;
      model.error = null;
    } catch (error) { model.error = safeError(error); model.items = []; }
    finally { model.loading = false; if (state.view === "materials") renderMaterials(); }
  }
  async function loadMaterialDetail(id) {
    state.materialDetailLoading = true; state.materialDetailError = null;
    if (state.view === "materials") renderMaterials();
    try {
      state.materialDetail = await api(`/api/materials/${encodeURIComponent(id)}`);
      state.materialDetailError = null;
    } catch (error) { state.materialDetailError = safeError(error); state.materialDetail = null; }
    finally { state.materialDetailLoading = false; if (state.view === "materials") renderMaterials(); }
  }
  function renderMaterials() {
    page.replaceChildren();
    page.append(pageHeading("SOURCE LIBRARY", "자료 라이브러리", "보관 자료의 출처, 원문 연결, 검색 구간과 인용 주장을 확인합니다."));
    const layout = el("div", "library-layout");
    const listPanel = el("section", "surface library-panel");
    const toolbar = el("form", "library-toolbar"); toolbar.addEventListener("submit", event => {
      event.preventDefault(); state.materials.query = $("#material-query").value; state.materials.category = $("#material-category").value; state.materials.offset = 0; loadMaterials();
    });
    const controls = el("div", "library-controls");
    const query = el("input", "input"); query.id = "material-query"; query.type = "search"; query.maxLength = 2000; query.placeholder = "자료 제목 또는 요약 검색"; query.value = state.materials.query; query.setAttribute("aria-label", "자료 검색어");
    const category = el("select", "select"); category.id = "material-category"; category.setAttribute("aria-label", "자료 category"); categoryOptions(category, state.materials.category);
    const searchButton = button("검색", null, "button", "submit"); searchButton.disabled = state.materials.loading;
    add(controls, query, category, searchButton);
    add(toolbar, controls, text("div", state.materials.total === null ? "보관 자료" : `보관 자료 ${fmtCount(state.materials.total)}건`, "library-count"));
    listPanel.append(toolbar);
    const list = el("div", "material-list"); list.setAttribute("aria-live", "polite");
    if (state.materials.loading) list.append(loadingState("검색 조건에 맞는 실제 자료를 불러옵니다."));
    else if (state.materials.error) list.append(errorState(state.materials.error, loadMaterials));
    else if (!state.materials.items.length) list.append(emptyState("자료가 없습니다", state.materials.query ? "검색어 또는 category를 바꿔 다시 확인해 보세요." : "현재 보관된 자료가 없습니다."));
    else state.materials.items.forEach((material, index) => {
      const id = valueAt(material, "id");
      const item = el("button", "material-item"); item.type = "button";
      if (id !== undefined && String(id) === String(state.selectedMaterialId)) item.setAttribute("aria-current", "true");
      const body = el("span");
      const title = text("span", asText(valueAt(material, "title", "name"), "제목 없음"), "material-item-title");
      const source = valueAt(material, "source", "url", "source_name");
      const meta = el("span", "material-item-meta");
      add(meta, text("span", asText(valueAt(material, "category"), "category 없음")), text("span", "·"), text("span", asText(valueAt(material, "material_type", "type"), "유형 없음")));
      const sourceLabel = isObject(source) ? valueAt(source, "name", "title", "publisher", "url") : source;
      if (sourceLabel) add(meta, text("span", "·"), text("span", shortText(sourceLabel, 100)));
      add(body, title, meta);
      const materialStatus = valueAt(material, "status");
      const status = text("span", asText(materialStatus, "상태 없음"), `tag material-item-status${positiveStatus(materialStatus) ? " tag-green" : negativeStatus(materialStatus) ? " tag-amber" : ""}`);
      add(item, body, status);
      item.setAttribute("aria-label", `${asText(valueAt(material, "title", "name"), "자료")}, ${index + 1}번째`);
      item.addEventListener("click", () => {
        if (id === undefined) { toast("자료 ID가 없어 상세 자료를 열 수 없습니다.", true); return; }
        state.selectedMaterialId = String(id); state.materialDetail = null; state.materialDetailError = null; state.materialDetailLoading = true; renderMaterials(); loadMaterialDetail(id);
      });
      list.append(item);
    });
    listPanel.append(list);
    const pager = el("div", "library-pagination");
    const start = state.materials.total === 0 ? 0 : state.materials.offset + (state.materials.items.length ? 1 : 0);
    const end = state.materials.offset + state.materials.items.length;
    pager.append(text("span", state.materials.total === null ? `${start}–${end}건` : `${start}–${end} / ${fmtCount(state.materials.total)}`, "small muted"));
    const pagerActions = el("span", "heading-actions");
    const previous = button("이전", () => { state.materials.offset = Math.max(0, state.materials.offset - state.materials.limit); loadMaterials(); }, "button button-secondary button-small");
    previous.disabled = state.materials.loading || state.materials.offset <= 0;
    const next = button("다음", () => { state.materials.offset += state.materials.limit; loadMaterials(); }, "button button-secondary button-small");
    next.disabled = state.materials.loading || state.materials.items.length < state.materials.limit || (state.materials.total !== null && state.materials.offset + state.materials.items.length >= state.materials.total);
    add(pagerActions, previous, next); pager.append(pagerActions); listPanel.append(pager);
    layout.append(listPanel, renderMaterialDetail()); page.append(layout);
  }
  function renderMaterialDetail() {
    const panel = el("section", "surface detail-panel");
    if (state.materialDetailLoading) { panel.append(loadingState("자료 상세와 인용 위치를 불러옵니다.")); return panel; }
    if (state.materialDetailError) { panel.append(errorState(state.materialDetailError, () => loadMaterialDetail(state.selectedMaterialId))); return panel; }
    if (!state.materialDetail) {
      const empty = el("div", "detail-empty");
      const glyph = el("span", "empty-glyph");
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"); svg.setAttribute("viewBox", "0 0 24 24");
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path"); path.setAttribute("d", "M5 5.75A1.75 1.75 0 0 1 6.75 4h7.1L19 9.15v9.1A1.75 1.75 0 0 1 17.25 20h-10A2.25 2.25 0 0 1 5 17.75zM13.5 4v5.5H19M8.5 13h7M8.5 16h5"); svg.append(path); glyph.append(svg);
      add(empty, glyph, text("h3", "자료를 선택해 주세요"), text("p", "원문 링크, 저장 상태, 검색 구간과 자료에 연결된 인용 주장을 여기서 확인합니다."));
      panel.append(empty); return panel;
    }
    const data = state.materialDetail;
    const material = isObject(data.material) ? data.material : data;
    const chunks = listOf(data.chunks);
    const claims = listOf(data.claims);
    const body = el("div", "material-detail");
    const sourceField = valueAt(material, "source");
    const sourceUrl = valueAt(material, "url", "source_url") ?? valueAt(sourceField, "url") ?? (typeof sourceField === "string" && safeUrl(sourceField) ? sourceField : undefined);
    add(body, text("span", `${asText(valueAt(material, "category"), "자료")} · ${asText(valueAt(material, "material_type", "type"), "유형 미지정")}`, "detail-eyebrow"),
      text("h2", asText(valueAt(material, "title", "name"), "제목 없음")),
      text("p", asText(valueAt(material, "summary", "description"), "이 자료에 등록된 요약이 없습니다."), "material-summary"));
    if (sourceUrl) body.append(link("원문 자료 열기", sourceUrl));
    const meta = el("dl", "detail-meta");
    [["자료 ID", valueAt(material, "id")], ["상태", valueAt(material, "status")], ["출처", valueAt(material, "source")], ["범위", valueAt(material, "scope")], ["자료 역할", retrievalRoleLabel(material.role)]].forEach(([label, value]) => {
      if (value === undefined) return;
      const group = el("div"); add(group, text("dt", label), text("dd", asText(value))); meta.append(group);
    });
    body.append(meta);
    body.append(text("p", "자료 역할은 활용 목적의 분류입니다. 원문의 주장·수치·적용 조건은 독립 검증이 필요합니다.", "small muted"));
    if (isObject(data.annotation_coverage)) {
      const coverage = data.annotation_coverage;
      body.append(text("p", `Claim 문맥 annotation · ${fmtCount(coverage.claims_annotated)} / ${fmtCount(coverage.claims_total)}${coverage.status === "needs_review" ? " · 추가 검토 필요" : ""}. 추출 범위는 원문의 일부 구간이며 전체 지식의 완전성을 뜻하지 않습니다.`, "small muted"));
    }
    const claimSection = el("section", "detail-section");
    const claimTitle = el("h3", "detail-section-title"); add(claimTitle, text("span", "인용 주장"), text("span", `${claims.length}개 인용`)); claimSection.append(claimTitle);
    if (!claims.length) claimSection.append(text("p", "연결된 인용 주장이 없습니다.", "small muted"));
    claims.forEach(claim => {
      const card = el("article", "evidence-card");
      const heading = text("strong", asText(valueAt(claim, "summary", "claim"), "요약 없음"), "small");
      const triple = [valueAt(claim, "subject"), valueAt(claim, "predicate"), valueAt(claim, "object")].filter(value => value !== undefined).map(asText).join(" → ");
      const quote = valueAt(claim, "quote", "text", "evidence");
      const metadata = valueAt(claim, "metadata");
      const sourceStart = valueAt(claim, "source_start", "start") ?? valueAt(metadata, "source_start");
      const sourceEnd = valueAt(claim, "source_end", "end") ?? valueAt(metadata, "source_end");
      const footer = el("div", "evidence-footer");
      add(footer, text("span", `${asText(valueAt(claim, "kind"), "claim")} · chunk ${asText(valueAt(claim, "chunk_id"), "ID 없음")} · rev ${asText(valueAt(claim, "revision_id"), "ID 없음")}`), text("span", sourceStart !== undefined || sourceEnd !== undefined ? `source span ${asText(sourceStart, "?")}–${asText(sourceEnd, "?")}` : "source span 없음"));
      add(card, heading, triple ? text("p", triple, "small muted") : null, quote ? text("blockquote", quote, "evidence-quote") : text("p", "인용 원문이 응답에 포함되지 않았습니다.", "muted"), footer);
      claimSection.append(card);
    });
    body.append(claimSection);
    const chunkSection = el("section", "detail-section");
    const chunkTitle = el("h3", "detail-section-title"); add(chunkTitle, text("span", "검색 구간"), text("span", `${chunks.length}개 구간`)); chunkSection.append(chunkTitle);
    if (!chunks.length) chunkSection.append(text("p", "저장된 검색 구간이 없습니다.", "small muted"));
    chunks.forEach((chunk, index) => {
      const card = el("details", "evidence-card");
      const summary = el("summary"); add(summary, text("strong", `구간 ${index + 1}`, "small"), text("span", ` · ${asText(valueAt(chunk, "id"), "ID 없음")}`, "small muted"));
      const content = text("p", asText(valueAt(chunk, "text"), "본문 없음"), "evidence-quote");
      const footer = el("div", "evidence-footer"); add(footer, text("span", `source span ${asText(valueAt(chunk, "start"), "?")}–${asText(valueAt(chunk, "end"), "?")}`), text("span", `revision ${asText(valueAt(chunk, "revision_id"), "ID 없음")}`));
      add(card, summary, content, renderClaimContexts(chunk, 32), footer); chunkSection.append(card);
    });
    body.append(chunkSection); panel.append(body); return panel;
  }

  async function runRetrieval() {
    const model = state.retrieval;
    if (!model.query.trim()) { toast("검색어를 입력해 주세요.", true); return; }
    model.loading = true; model.error = null; model.response = null;
    renderRetrieval();
    const body = { query: model.query.trim(), limit: 12, purpose: model.purpose || "auto" };
    if (model.category) body.category = model.category;
    if (model.mode && state.capabilities?.retrieval?.allow_mode_override === true) body.retrieval_mode = model.mode;
    try { model.response = await api("/api/search", { method: "POST", body }); }
    catch (error) { model.error = safeError(error); }
    finally { model.loading = false; if (state.view === "retrieval") renderRetrieval(); }
  }
  function populateRetrievalModes(select) {
    const selected = state.retrieval.mode;
    select.replaceChildren();
    const defaults = text("option", "서버 기본 구성"); defaults.value = ""; select.append(defaults);
    const config = state.capabilities?.retrieval;
    if (config?.allow_mode_override === true) {
      const names = { baseline: "기본 검색", contextual: "문맥 보강 검색", rerank: "재정렬 검색", contextual_rerank: "문맥 보강 + 재정렬" };
      for (const value of config.available_modes || []) {
        if (!names[value]) continue;
        const option = text("option", names[value]); option.value = value; select.append(option);
      }
    }
    select.value = [...select.options].some(option => option.value === selected) ? selected : "";
  }
  function renderRetrieval() {
    page.replaceChildren();
    page.append(pageHeading("HYBRID RETRIEVAL", "근거 검색", "자료 검색 구간과 검색 trace를 함께 확인합니다. 답변의 근거가 부족하면 부족한 상태를 그대로 보여줍니다."));
    const formPanel = el("section", "surface form-card");
    const form = el("form", "form-grid");
    const queryField = el("div", "field span-full");
    const queryLabel = text("label", "설계 질문 또는 검색어"); queryLabel.htmlFor = "retrieval-query";
    const query = el("textarea", "textarea"); query.id = "retrieval-query"; query.required = true; query.maxLength = 2000; query.placeholder = "예: HBM 대역폭 제약이 attention kernel의 타일 크기에 주는 영향"; query.value = state.retrieval.query;
    queryField.append(queryLabel, query, text("span", "자료에 실제로 있는 근거를 찾아 인용 구간을 표시합니다.", "field-hint"));
    const categoryField = el("div", "field");
    const categoryLabel = text("label", "Category (선택)"); categoryLabel.htmlFor = "retrieval-category";
    const category = el("select", "select"); category.id = "retrieval-category"; categoryOptions(category, state.retrieval.category);
    categoryField.append(categoryLabel, category);
    const purposeField = el("div", "field");
    const purposeLabel = text("label", "검색 목적"); purposeLabel.htmlFor = "retrieval-purpose";
    const purpose = el("select", "select"); purpose.id = "retrieval-purpose";
    [["auto", "자동 분류 (auto)"], ["design", "설계 근거 (design)"],
      ["operations", "설치·설정·운영 (operations)"], ["discovery", "자료 탐색 (discovery)"]].forEach(([value, label]) => {
      const option = text("option", label); option.value = value; purpose.append(option);
    });
    purpose.value = ["auto", "design", "operations", "discovery"].includes(state.retrieval.purpose) ? state.retrieval.purpose : "auto";
    purposeField.append(purposeLabel, purpose, text("span", "자동은 질문 표현으로 목적을 정하고 불명확하면 역할 상한을 유지합니다.", "field-hint"));
    const limitField = el("div", "field");
    const limitLabel = text("label", "결과 수"); limitLabel.htmlFor = "retrieval-limit";
    const limit = el("input", "input"); limit.id = "retrieval-limit"; limit.type = "text"; limit.value = "12"; limit.readOnly = true; limit.setAttribute("aria-describedby", "retrieval-limit-note");
    limitField.append(limitLabel, limit, text("span", "한 번에 표시하는 결과 수", "field-hint"));
    const modeField = el("div", "field");
    const modeLabel = text("label", "검색 구성"); modeLabel.htmlFor = "retrieval-mode";
    const mode = el("select", "select"); mode.id = "retrieval-mode";
    populateRetrievalModes(mode);
    modeField.append(modeLabel, mode, text("span", "문맥 보강과 재정렬을 비교할 수 있습니다. 검색 점수는 답변 가능성의 확률이 아닙니다.", "field-hint"));
    const actions = el("div", "form-actions span-full");
    const submit = button("근거 검색", null, "button", "submit");
    submit.disabled = state.retrieval.loading;
    actions.append(submit);
    form.addEventListener("submit", event => {
      event.preventDefault(); state.retrieval.query = query.value; state.retrieval.category = category.value;
      state.retrieval.purpose = purpose.value; state.retrieval.mode = mode.value; runRetrieval();
    });
    add(form, queryField, categoryField, purposeField, modeField, limitField, actions); formPanel.append(form);
    const results = el("section", "surface overview-section");
    const header = el("div", "surface-header"); add(header, text("div", "검색 결과", ""));
    const heading = el("div"); add(heading, text("h2", "검색 결과"), text("p", "원문 인용 구간과 검색 순위")); header.replaceChildren(heading);
    results.append(header);
    const body = el("div", "surface-body");
    if (state.retrieval.loading) body.append(loadingState("검색 제공자가 자료와 근거를 찾고 있습니다."));
    else if (state.retrieval.error) body.append(errorState(state.retrieval.error, runRetrieval));
    else if (!state.retrieval.response) body.append(emptyState("검색어를 입력해 주세요", "질문을 입력한 다음 근거 검색을 실행하면 검색 결과와 trace가 표시됩니다."));
    else renderRetrievalResponse(body, state.retrieval.response);
    results.append(body);
    page.append(formPanel, results);
  }
  function retrievalRoleLabel(role) {
    return ({
      core_technical: "핵심 기술",
      supporting_method: "보조 방법",
      integration_operations: "통합·운영",
      source_navigation: "자료 위치",
      out_of_scope: "범위 밖",
      unclassified: "미분류"
    })[role] || "미분류";
  }
  function valueWithUnit(value, unit, fallback = "값 미지정") {
    const renderedValue = value === undefined ? fallback : asText(value, fallback);
    const renderedUnit = unit === undefined ? "" : ` ${asText(unit, "")}`;
    return `${renderedValue}${renderedUnit}`;
  }
  function appendContextProof(container, evidence) {
    if (!isObject(evidence)) return;
    const proofChunk = valueAt(evidence, "chunk_id", "evidence_chunk_id");
    const start = valueAt(evidence, "source_start", "start_offset", "start");
    const end = valueAt(evidence, "source_end", "end_offset", "end");
    const revision = valueAt(evidence, "revision_id", "revision_sha256");
    const refs = [];
    if (proofChunk !== undefined) refs.push(`proof chunk ${asText(proofChunk)}`);
    if (start !== undefined || end !== undefined) refs.push(`source span ${asText(start, "?")}–${asText(end, "?")}`);
    if (revision !== undefined) refs.push(`revision ${asText(revision)}`);
    if (refs.length) container.append(text("div", refs.join(" · "), "evidence-footer"));
    const quote = valueAt(evidence, "quote", "proof_quote");
    if (quote !== undefined) container.append(text("blockquote", asText(quote), "evidence-quote"));
  }
  function renderClaimContexts(item, maxItems = 2) {
    const contexts = listOf(valueAt(item, "claim_contexts"));
    if (!contexts.length) return null;
    const section = el("section", "detail-section");
    const heading = el("h4", "detail-section-title");
    add(heading, text("span", "Claim 문맥"), text("span", `${fmtCount(contexts.length)}개 annotation${contexts.length > maxItems ? ` · 최대 ${maxItems}개 표시` : ""}`));
    section.append(heading);
    contexts.slice(0, maxItems).forEach(context => {
      if (!isObject(context)) return;
      const card = el("article", "evidence-card");
      const annotationId = valueAt(context, "annotation_id", "id");
      const claimId = valueAt(context, "claim_id");
      const version = valueAt(context, "version", "schema_version");
      const identifiers = [
        annotationId !== undefined ? `annotation ${asText(annotationId)}` : "annotation ID 없음",
        claimId !== undefined ? `Claim ${asText(claimId)}` : null,
        version !== undefined ? `v${asText(version)}` : null
      ].filter(Boolean).join(" · ");
      card.append(text("strong", identifiers, "small"));
      const revision = valueAt(context, "revision_sha256");
      if (revision !== undefined) card.append(text("div", `proof revision ${asText(revision)}`, "evidence-footer"));

      const parameters = listOf(valueAt(context, "parameters"));
      if (parameters.length) {
        card.append(text("h5", `Parameter · ${fmtCount(parameters.length)}`, "detail-section-title"));
        parameters.forEach(parameter => {
          if (!isObject(parameter)) return;
          const row = el("div", "evidence-card");
          const name = valueAt(parameter, "name", "metric_or_parameter_name");
          const rawValue = valueAt(parameter, "value_raw", "value");
          const rawUnit = valueAt(parameter, "unit_raw", "unit");
          const normalized = valueAt(parameter, "normalized", "normalized_value");
          const rawLine = text("p", `원문 값 · ${asText(name, "Parameter")} · ${valueWithUnit(rawValue, rawUnit)}`);
          row.append(rawLine);
          if (isObject(normalized)) {
            const normalizedValue = valueAt(normalized, "value");
            const normalizedUnit = valueAt(normalized, "unit");
            const status = valueAt(normalized, "status");
            row.append(text("p", `정규화 값 · ${valueWithUnit(normalizedValue, normalizedUnit)}${status !== undefined ? ` · 상태 ${asText(status)}` : ""}`));
          } else if (normalized !== undefined) {
            row.append(text("p", `정규화 값 · ${asText(normalized)}`));
          } else row.append(text("p", "정규화 값 또는 단위 상태가 제공되지 않았습니다."));
          appendContextProof(row, valueAt(parameter, "evidence", "proof"));
          card.append(row);
        });
      }

      const conditions = listOf(valueAt(context, "conditions"));
      if (conditions.length) {
        card.append(text("h5", `Source 조건 · ${fmtCount(conditions.length)}`, "detail-section-title"));
        conditions.forEach(condition => {
          if (!isObject(condition)) return;
          const row = el("div", "evidence-card");
          const dimension = valueAt(condition, "dimension", "name");
          const operator = valueAt(condition, "operator");
          const rawValue = valueAt(condition, "value_raw", "value", "values");
          const rawUnit = valueAt(condition, "unit_raw", "unit");
          row.append(text("p", `${asText(dimension, "조건 차원")} ${asText(operator, "operator 미지정")} · 원문 조건 ${valueWithUnit(rawValue, rawUnit)}`));
          appendContextProof(row, valueAt(condition, "evidence", "proof"));
          card.append(row);
        });
      }

      const scopeNote = valueAt(context, "source_scope_note");
      if (scopeNote !== undefined) card.append(text("p", `자료 적용 범위 메모 · ${asText(scopeNote)}`, "small muted"));
      if (context.projection?.truncated) card.append(text("p", "검색용으로 일부 값·조건을 표시합니다. 자료 상세의 해당 구간에서 전체 annotation을 확인할 수 있습니다.", "small muted"));
      const usePolicy = valueAt(context, "use_policy");
      const validation = valueAt(context, "validation");
      const validationText = validation === "literal_grounded_unverified_association"
        ? "원문 literal에 연결된 문맥입니다. 주장과 조건의 의미상 연관 또는 적용 가능성을 독립 검증한 결과가 아닙니다."
        : "Claim 문맥은 별도 과학 검증을 뜻하지 않습니다.";
      card.append(text("p", `사용 정책 · ${asText(usePolicy, "source_assertion_only")}. ${validationText}`, "small muted"));
      section.append(card);
    });
    return section;
  }
  function renderNeighborEvidence(item) {
    const neighbors = listOf(valueAt(item, "neighbor_evidence"));
    if (!neighbors.length) return null;
    const section = el("section", "detail-section");
    const heading = el("h4", "detail-section-title");
    add(heading, text("span", "이웃 문맥 (별도 인용 ID)"), text("span", `${fmtCount(neighbors.length)}개 chunk`));
    section.append(heading);
    neighbors.forEach(neighbor => {
      if (!isObject(neighbor)) return;
      const card = el("article", "evidence-card");
      const id = valueAt(neighbor, "chunk_id");
      const start = valueAt(neighbor, "start_offset", "start");
      const end = valueAt(neighbor, "end_offset", "end");
      add(card, text("strong", `${asText(valueAt(neighbor, "relation"), "neighbor")} · chunk ${asText(id, "ID 없음")}`, "small"),
        text("p", asText(valueAt(neighbor, "text", "excerpt"), "이웃 본문 없음"), "evidence-quote"),
        text("div", `material ${asText(valueAt(neighbor, "material_id"), "ID 없음")} · revision ${asText(valueAt(neighbor, "revision_id"), "ID 없음")} · source span ${asText(start, "?")}–${asText(end, "?")}`, "evidence-footer"));
      section.append(card);
    });
    return section;
  }
  function renderRetrievalItem(item, index, locatorOnly = false) {
    const row = el("article", "result-row");
    const head = el("div", "result-row-head");
    const copy = el("div");
    const title = el("h3", "result-title");
    const titleValue = asText(valueAt(item, "title"), "자료 제목 없음");
    const materialId = valueAt(item, "material_id");
    if (materialId !== undefined) {
      const open = el("button", "", titleValue); open.type = "button"; open.addEventListener("click", () => openMaterialFromSearch(materialId)); title.append(open);
    } else title.append(text("span", titleValue));
    const meta = el("div", "result-meta");
    const chunkId = valueAt(item, "chunk_id");
    const revisionId = valueAt(item, "revision_id");
    const role = asText(valueAt(item, "role"), "unclassified");
    const rolePolicy = valueAt(item, "role_policy");
    const isLocator = locatorOnly || valueAt(item, "result_kind") === "locator"
      || role === "source_navigation" || (isObject(rolePolicy) && valueAt(rolePolicy, "is_locator") === true);
    add(meta, text("span", asText(valueAt(item, "category"), "category 없음")), text("span", "·"),
      text("span", `chunk ${asText(chunkId, "ID 없음")}`), text("span", "·"), text("span", `revision ${asText(revisionId, "ID 없음")}`),
      text("span", "·"), text("span", retrievalRoleLabel(role), "tag tag-blue"));
    if (isLocator) meta.append(text("span", "locator · evidence authority 0 · source assertion 아님", "tag tag-amber"));
    else if (isObject(rolePolicy) && rolePolicy.needs_review) meta.append(text("span", "검토 필요", "tag tag-amber"));
    const url = valueAt(item, "url", "source_url");
    if (url && safeUrl(url)) { meta.append(text("span", "·")); meta.append(link("원문", url)); }
    add(copy, title, meta);
    const rank = valueAt(item, "rank");
    const rerankScore = valueAt(valueAt(item, "trace"), "reranker_relevance_score");
    const scoreLabel = typeof rerankScore === "number" ? `관련도 ${rerankScore.toFixed(4)}`
      : rank === undefined ? `#${index + 1}` : `검색 점수 ${asText(rank)}`;
    head.append(copy, text("span", scoreLabel, "rank-pill"));
    row.append(head);
    row.append(text("p", asText(valueAt(item, "text", "excerpt"), "검색 구간 본문이 없습니다."), "result-excerpt"));

    const start = valueAt(item, "start_offset", "start");
    const end = valueAt(item, "end_offset", "end");
    const useCeiling = isObject(rolePolicy) ? valueAt(rolePolicy, "use_ceiling", "evidence_ceiling") : undefined;
    const policyLine = el("div", "trace-line");
    add(policyLine, text("strong", "ROLE / SCOPE"),
      text("span", `${retrievalRoleLabel(role)} · ${asText(useCeiling, isLocator ? "locator only" : "상한 미지정")}`),
      text("span", `chunk ${asText(chunkId, "ID 없음")} · source span ${asText(start, "?")}–${asText(end, "?")}`));
    row.append(policyLine);
    if (isObject(valueAt(item, "role_metadata"))) {
      const metadata = item.role_metadata;
      row.append(text("div", `역할 판정 metadata · ${shortText(safeJson(metadata, 0), 320)}`, "trace-line"));
    }
    if (isLocator) row.append(text("p", "이 구간은 자료를 찾기 위한 locator입니다. Claim quote로 확인되기 전에는 설계·운영 주장의 근거로 사용하지 않습니다.", "small muted"));
    const scores = valueAt(item, "scores");
    if (scores !== undefined) row.append(text("div", `채널 점수 · ${shortText(safeJson(scores, 0), 220)}`, "trace-line"));
    const trace = valueAt(item, "trace");
    if (trace !== undefined) row.append(text("div", `검색 trace · ${shortText(safeJson(trace, 0), 360)}`, "trace-line"));
    const contexts = renderClaimContexts(item);
    const neighbors = renderNeighborEvidence(item);
    if (contexts) row.append(contexts);
    if (neighbors) row.append(neighbors);
    return row;
  }
  function renderRetrievalResponse(body, response) {
    const items = listOf(valueAt(response, "items") ?? response);
    const locators = listOf(valueAt(response, "locators"));
    const sourceResultsValue = valueAt(response, "source_results");
    const hasSourceResults = Array.isArray(sourceResultsValue);
    const sourceResults = hasSourceResults ? sourceResultsValue : [];
    const purposeTrace = valueAt(response, "purpose_trace");
    const resolvedPurpose = valueAt(response, "purpose") ?? valueAt(purposeTrace, "resolved");
    const selectedPurpose = valueAt(purposeTrace, "requested") ?? state.retrieval.purpose ?? "auto";
    const purposeBox = el("div", "trace-line");
    const modeNames = { baseline: "기본 검색", contextual: "문맥 보강", rerank: "재정렬", contextual_rerank: "문맥 보강 + 재정렬" };
    const returnedMode = valueAt(response, "retrieval_mode");
    if (modeNames[returnedMode]) {
      const configuration = el("div", "trace-line");
      configuration.append(text("strong", "검색 구성"), text("span", modeNames[returnedMode]));
      const model = valueAt(valueAt(response, "reranker_trace"), "model");
      if (model) configuration.append(text("span", asText(model)));
      body.append(configuration);
    }
    add(purposeBox, text("strong", "PURPOSE"),
      text("span", `${asText(selectedPurpose)} → ${asText(resolvedPurpose, "분류 없음")}`),
      text("span", `policy ${asText(valueAt(response, "policy_version"), asText(valueAt(purposeTrace, "version"), "버전 없음"))}`),
      text("span", `rule ${asText(valueAt(purposeTrace, "rule"), "rule 없음")}`));
    body.append(purposeBox);
    if (valueAt(purposeTrace, "uncertain") === true) {
      body.append(text("p", "자동 목적 분류가 불명확해 설계 기본 정책을 적용했습니다. source role별 사용 상한과 검토 표시를 확인해 주세요.", "small muted"));
    }
    const trace = el("div", "trace-line");
    add(trace, text("strong", "TRACE"), text("span", asText(valueAt(response, "trace_id"), "trace ID 없음")));
    const channels = valueAt(response, "channels");
    if (channels !== undefined) {
      const channelBox = el("div", "trace-line"); channelBox.append(text("strong", "CHANNELS"));
      const channelItems = Array.isArray(channels) ? channels : isObject(channels) ? Object.entries(channels).map(([name, value]) => ({ name, value })) : [channels];
      channelItems.forEach(channel => {
        const label = isObject(channel) ? `${asText(valueAt(channel, "name", "channel", "kind"), "channel")}${valueAt(channel, "count", "value") !== undefined ? ` · ${fmtCount(valueAt(channel, "count", "value"))}` : ""}` : asText(channel);
        channelBox.append(text("span", label, "tag tag-blue"));
      });
      body.append(channelBox);
    }
    const embeddingCacheHit = valueAt(response, "query_embedding_cache_hit");
    if (embeddingCacheHit !== undefined) trace.append(text("span", `query embedding cache · ${embeddingCacheHit ? "hit · provider usage 0" : "miss"}`));
    body.append(trace);
    const limitations = valueAt(response, "limitations");
    if (limitations) {
      const list = el("ul", "limitation-list");
      (Array.isArray(limitations) ? limitations : [limitations]).forEach(item => list.append(text("li", asText(item))));
      body.append(list);
    }
    const answer = valueAt(response, "answer", "summary");
    if (answer !== undefined) {
      const answerPanel = el("section", "evidence-card");
      add(answerPanel, text("strong", "검색 응답", "small"), text("p", asText(answer), "result-excerpt"));
      body.append(answerPanel);
    }
    if (hasSourceResults) {
      if (!sourceResults.length && !items.length && !locators.length) {
        body.append(emptyState("검색 근거가 없습니다", "이 질문에 맞는 검색 구간이나 자료 위치가 없습니다. 검색어를 조정하거나 자료 상태를 확인해 주세요."));
        return;
      }
      if (!items.length && locators.length) {
        body.append(emptyState("Locator만 있습니다", "인용 가능한 source assertion은 없고 자료 위치만 반환됐습니다. locator를 Claim 근거로 취급하지 마세요."));
      }
      if (sourceResults.length) {
        const toolbar = el("div", "results-toolbar");
        add(toolbar,
          text("span", `${fmtCount(sourceResults.length)}개 혼합 source 결과`),
          text("span", `evidence items ${fmtCount(items.length)} · locators ${fmtCount(locators.length)}`),
          text("span", "locator 권위 0 · 원문 링크는 http(s)만 열립니다."));
        const results = el("div", "results-list");
        sourceResults.forEach((item, index) => results.append(renderRetrievalItem(item, index)));
        body.append(toolbar, results);
      }
    } else {
      if (!items.length && !locators.length) {
        body.append(emptyState("검색 근거가 없습니다", "이 질문에 맞는 검색 구간이나 자료 위치가 없습니다. 검색어를 조정하거나 자료 상태를 확인해 주세요."));
        return;
      }
      if (items.length) {
        const toolbar = el("div", "results-toolbar");
        add(toolbar, text("span", `${fmtCount(items.length)}개 검색 근거`), text("span", "원문 링크는 http(s) 주소만 열립니다."));
        const results = el("div", "results-list");
        items.forEach((item, index) => results.append(renderRetrievalItem(item, index, false)));
        body.append(toolbar, results);
      } else if (locators.length) {
        body.append(emptyState("Locator만 있습니다", "인용 가능한 source assertion은 없고 자료 위치만 반환됐습니다. locator를 Claim 근거로 취급하지 마세요."));
      }
      if (locators.length) {
        const locatorSection = el("section", "detail-section");
        const heading = el("h3", "detail-section-title");
        add(heading, text("span", "자료 위치만 (locator)"), text("span", `${fmtCount(locators.length)}개 · 주장 근거 사용 금지`));
        locatorSection.append(heading, text("p", "이 항목은 위치 탐색 또는 역할 검토용입니다. source assertion 근거가 아닙니다.", "small muted"));
        const results = el("div", "results-list");
        locators.forEach((item, index) => results.append(renderRetrievalItem(item, index, true)));
        locatorSection.append(results);
        body.append(locatorSection);
      }
    }
  }

  async function loadGraph() {
    const model = state.graph;
    model.loading = true; model.error = null; model.response = null; model.selectedId = null;
    renderGraph();
    const params = new URLSearchParams({ limit: "80" });
    if (model.query.trim()) params.set("query", model.query.trim());
    try { model.response = await api(`/api/graph?${params.toString()}`); }
    catch (error) { model.error = safeError(error); }
    finally { model.loading = false; if (state.view === "graph") renderGraph(); }
  }
  function renderGraph() {
    page.replaceChildren();
    page.append(pageHeading("TYPED KNOWLEDGE GRAPH", "지식 그래프", "실제 typed entity와 relation을 탐색합니다. 노드와 관계는 검색·추출 결과의 투영이며 그 자체가 독립 검증을 뜻하지 않습니다."));
    const panel = el("section", "surface graph-panel");
    const form = el("form", "graph-toolbar");
    const query = el("input", "input"); query.type = "search"; query.id = "graph-query"; query.maxLength = 1000; query.placeholder = "엔티티 또는 관계 검색"; query.value = state.graph.query; query.setAttribute("aria-label", "그래프 검색어");
    const submit = button("검색", null, "button button-small", "submit"); submit.disabled = state.graph.loading;
    form.addEventListener("submit", event => { event.preventDefault(); state.graph.query = query.value; loadGraph(); });
    add(form, query, submit); panel.append(form);
    if (state.graph.loading) panel.append(loadingState("지식 그래프의 노드와 관계를 불러옵니다."));
    else if (state.graph.error) panel.append(errorState(state.graph.error, loadGraph));
    else if (!state.graph.response) panel.append(emptyState("그래프를 검색해 주세요", "검색어를 비워 두고 검색하면 연결된 노드를 표시합니다."));
    else {
      const nodes = listOf(state.graph.response.nodes);
      const edges = listOf(state.graph.response.edges);
      panel.append(text("div", `${fmtCount(nodes.length)} nodes · ${fmtCount(edges.length)} edges · 요청 한도 80`, "graph-stats"));
      if (!nodes.length) panel.append(emptyState("표시할 노드가 없습니다", "현재 검색과 연결된 typed entity가 없습니다."));
      else {
        const layout = el("div", "graph-layout");
        const viz = el("div", "graph-canvas"); viz.append(buildGraphSvg(nodes, edges));
        const legend = el("div", "graph-legend");
        legend.setAttribute("role", "group"); legend.setAttribute("aria-label", "노드 유형과 relation 근거 범례");
        Array.from(new Set(nodes.map(node => asText(valueAt(node, "kind"), "type 미지정")))).forEach(kind => {
          const entry = el("span", "legend-item"); const swatch = el("span", "legend-swatch"); swatch.style.background = colorForKind(kind).stroke;
          add(entry, swatch, text("span", kind)); legend.append(entry);
        });
        [
          ["assertion", "source assertion · Claim quote reference"],
          ["topic", "topic mention · quote-grounded; not causality or inheritance"]
        ].forEach(([kind, description]) => {
          const entry = el("span", "legend-item");
          const sample = document.createElementNS("http://www.w3.org/2000/svg", "svg");
          sample.setAttribute("viewBox", "0 0 28 10"); sample.setAttribute("width", "28"); sample.setAttribute("height", "10"); sample.setAttribute("aria-hidden", "true");
          const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
          line.setAttribute("x1", "1"); line.setAttribute("y1", "5"); line.setAttribute("x2", "27"); line.setAttribute("y2", "5");
          line.setAttribute("stroke", "#7d8590"); line.setAttribute("stroke-width", "1.6");
          if (kind === "topic") line.setAttribute("stroke-dasharray", "4 3");
          sample.append(line);
          add(entry, sample, text("span", kind, `tag ${kind === "topic" ? "tag-amber" : "tag-blue"}`), text("span", description));
          legend.append(entry);
        });
        const graphSurface = el("section", "surface graph-panel");
        graphSurface.append(viz, legend);
        layout.append(graphSurface, renderGraphDetail(nodes, edges));
        panel.append(layout);
      }
    }
    page.append(panel);
  }
  function idOf(value) { return isObject(value) ? String(valueAt(value, "id") ?? "") : String(value ?? ""); }
  function colorForKind(kind) {
    const colors = [
      { fill: "#ddf4ff", stroke: "#0969da" }, { fill: "#dafbe1", stroke: "#1a7f37" },
      { fill: "#fff8c5", stroke: "#9a6700" }, { fill: "#fbefff", stroke: "#8250df" },
      { fill: "#ffebe9", stroke: "#cf222e" }, { fill: "#f0f3f6", stroke: "#59636e" }
    ];
    let hash = 0; for (const char of String(kind)) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
    return colors[hash % colors.length];
  }
  function buildGraphSvg(nodes, edges) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    const cols = 7, nodeWidth = 124, nodeHeight = 46, gapX = 17, gapY = 15, padX = 42, padY = 26;
    const rows = Math.ceil(nodes.length / cols);
    const width = padX * 2 + cols * nodeWidth + (cols - 1) * gapX;
    const height = padY * 2 + Math.max(1, rows) * nodeHeight + Math.max(0, rows - 1) * gapY;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`); svg.setAttribute("role", "group"); svg.setAttribute("aria-label", `지식 그래프 ${nodes.length}개 노드, ${edges.length}개 관계`);
    const positions = new Map();
    nodes.forEach((node, index) => {
      const x = padX + (index % cols) * (nodeWidth + gapX);
      const y = padY + Math.floor(index / cols) * (nodeHeight + gapY);
      positions.set(idOf(node), { x: x + nodeWidth / 2, y: y + nodeHeight / 2 });
    });
    const lines = document.createElementNS(ns, "g"); lines.setAttribute("aria-hidden", "true");
    edges.forEach(edge => {
      const from = positions.get(idOf(edge.source)), to = positions.get(idOf(edge.target));
      if (!from || !to) return;
      const line = document.createElementNS(ns, "line");
      line.setAttribute("x1", String(from.x)); line.setAttribute("y1", String(from.y)); line.setAttribute("x2", String(to.x)); line.setAttribute("y2", String(to.y)); line.setAttribute("class", `graph-edge${state.graph.selectedId && (idOf(edge.source) === state.graph.selectedId || idOf(edge.target) === state.graph.selectedId) ? " is-related" : ""}`);
      if (valueAt(edge, "relation_kind") === "topic") line.setAttribute("stroke-dasharray", "4 3");
      const title = document.createElementNS(ns, "title"); title.textContent = asText(edge.relation, "relation"); line.append(title); lines.append(line);
    });
    svg.append(lines);
    const group = document.createElementNS(ns, "g");
    nodes.forEach((node, index) => {
      const x = padX + (index % cols) * (nodeWidth + gapX), y = padY + Math.floor(index / cols) * (nodeHeight + gapY);
      const id = idOf(node); const label = asText(valueAt(node, "label", "name", "title"), "이름 없음"); const kind = asText(valueAt(node, "kind"), "type 미지정");
      const colors = colorForKind(kind);
      const entry = document.createElementNS(ns, "g");
      entry.setAttribute("class", `graph-node${id && state.graph.selectedId === id ? " is-selected" : ""}`);
      entry.setAttribute("role", "button"); entry.setAttribute("tabindex", "0"); entry.setAttribute("aria-label", `${label}, 유형 ${kind}`);
      const tip = document.createElementNS(ns, "title"); tip.textContent = `${label} · ${kind}`; entry.append(tip);
      const rect = document.createElementNS(ns, "rect"); rect.setAttribute("x", String(x)); rect.setAttribute("y", String(y)); rect.setAttribute("width", String(nodeWidth)); rect.setAttribute("height", String(nodeHeight)); rect.setAttribute("rx", "8"); rect.setAttribute("fill", colors.fill); rect.setAttribute("stroke", colors.stroke); entry.append(rect);
      const name = document.createElementNS(ns, "text"); name.setAttribute("x", String(x + nodeWidth / 2)); name.setAttribute("y", String(y + 19)); name.setAttribute("text-anchor", "middle"); name.textContent = label.length > 22 ? `${label.slice(0, 21)}…` : label; entry.append(name);
      const type = document.createElementNS(ns, "text"); type.setAttribute("class", "graph-kind"); type.setAttribute("x", String(x + nodeWidth / 2)); type.setAttribute("y", String(y + 35)); type.setAttribute("text-anchor", "middle"); type.textContent = kind.length > 25 ? `${kind.slice(0, 24)}…` : kind; entry.append(type);
      const select = () => { state.graph.selectedId = id; renderGraph(); };
      entry.addEventListener("click", select);
      entry.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); } });
      group.append(entry);
    });
    svg.append(group); return svg;
  }
  function renderGraphDetail(nodes, edges) {
    const panel = el("section", "surface graph-detail");
    const header = el("div", "surface-header"); const title = el("div"); add(title, text("h2", "선택한 노드"), text("p", "연결된 실제 relation")); header.append(title); panel.append(header);
    const body = el("div", "graph-detail-body");
    const node = nodes.find(item => idOf(item) === state.graph.selectedId);
    if (!node) body.append(emptyState("노드를 선택하세요", "노드를 선택하면 type과 연결된 방향 관계를 확인할 수 있습니다."));
    else {
      const id = idOf(node); const label = asText(valueAt(node, "label", "name", "title"), "이름 없음"); const kind = asText(valueAt(node, "kind"), "type 미지정");
      add(body, text("span", kind, "tag tag-blue"), text("h3", label), text("p", `node ID · ${id}`, "small muted"));
      const relations = [];
      edges.forEach(edge => {
        const source = idOf(edge.source), target = idOf(edge.target);
        if (source !== id && target !== id) return;
        const other = nodes.find(candidate => idOf(candidate) === (source === id ? target : source));
        relations.push({
          incoming: target === id,
          relation: valueAt(edge, "relation"),
          relationKind: valueAt(edge, "relation_kind") ?? "assertion",
          other: other ? valueAt(other, "label", "name", "title") : (source === id ? target : source),
          kind: other ? valueAt(other, "kind") : undefined,
          claimId: valueAt(edge, "claim_id"), evidenceChunkId: valueAt(edge, "evidence_chunk_id"),
          materialId: valueAt(edge, "material_id"), metadata: valueAt(edge, "metadata")
        });
      });
      body.append(text("h4", `연결 관계 ${fmtCount(relations.length)}`, "detail-section-title"));
      if (!relations.length) body.append(text("p", "이 응답 범위에서 연결된 relation이 없습니다.", "small muted"));
      else {
        const list = el("div", "relation-list");
        relations.slice(0, 60).forEach(item => {
          const row = el("div", "relation-item");
          if (item.incoming) add(row, text("strong", asText(item.other)), text("span", ` → ${asText(item.relation, "relation")} → `, "relation-arrow"), text("strong", label));
          else add(row, text("strong", label), text("span", ` → ${asText(item.relation, "relation")} → `, "relation-arrow"), text("strong", asText(item.other)));
          if (item.kind) row.append(text("span", ` · ${asText(item.kind)}`, "soft"));
          const isTopic = item.relationKind === "topic";
          row.append(text("span", `${isTopic ? "Topic mention" : "Source assertion"} · relation_kind ${asText(item.relationKind)}`, `tag ${isTopic ? "tag-amber" : "tag-blue"}`));
          const proofRefs = [];
          if (item.claimId !== undefined) proofRefs.push(`Claim ${asText(item.claimId)}`);
          if (item.evidenceChunkId !== undefined) proofRefs.push(`evidence chunk ${asText(item.evidenceChunkId)}`);
          if (item.materialId !== undefined) proofRefs.push(`material ${asText(item.materialId)}`);
          const proofStart = valueAt(item.metadata, "source_start");
          const proofEnd = valueAt(item.metadata, "source_end");
          if (proofStart !== undefined || proofEnd !== undefined) proofRefs.push(`source span ${asText(proofStart, "?")}–${asText(proofEnd, "?")}`);
          const proofRevision = valueAt(item.metadata, "revision_sha256");
          if (proofRevision !== undefined) proofRefs.push(`revision ${asText(proofRevision)}`);
          row.append(text("div", `Source proof · ${proofRefs.join(" · ") || "proof reference 없음"}`, "trace-line"));
          const proofScope = valueAt(item.metadata, "scope");
          if (proofScope !== undefined) row.append(text("div", `proof scope · ${asText(proofScope)}`, "trace-line"));
          const proofQuote = valueAt(item.metadata, "quote", "proof_quote");
          if (proofQuote !== undefined) row.append(text("blockquote", asText(proofQuote), "evidence-quote"));
          list.append(row);
        });
        body.append(list);
        if (relations.length > 60) body.append(text("p", `세부 목록은 첫 60개 관계만 표시합니다. 응답 관계 ${relations.length}개`, "small muted"));
      }
    }
    panel.append(body); return panel;
  }

  function readStoredJobs() {
    try {
      const value = JSON.parse(window.localStorage.getItem("dse-kg-pending-jobs") || "[]");
      if (!Array.isArray(value)) return [];
      return value.filter(item => isObject(item) && typeof item.id === "string" && item.id.length < 240)
        .map(item => ({ id: item.id, kind: "", question: "", status: String(item.status || "pending"), createdAt: String(item.createdAt || "") })).slice(0, 12);
    } catch (_) { return []; }
  }
  function saveStoredJobs() {
    try { window.localStorage.setItem("dse-kg-pending-jobs", JSON.stringify(state.jobs.slice(0, 12).map(({ id, status, createdAt }) => ({ id, status, createdAt })))); }
    catch (_) { /* Browser storage is optional; the API job remains available for this session. */ }
  }
  function jobState(job) {
    const status = String(valueAt(job, "status") ?? "pending").toLowerCase();
    if (valueAt(job, "error")) return { terminal: true, failed: true, label: "실패" };
    if (["done", "complete", "completed", "success", "succeeded", "finished", "완료"].includes(status)) return { terminal: true, failed: false, label: "완료" };
    if (["failed", "error", "cancelled", "canceled", "실패"].includes(status)) return { terminal: true, failed: true, label: "실패" };
    if (["queued", "pending", "waiting", "accepted", "대기"].includes(status)) return { terminal: false, failed: false, label: "대기" };
    if (["running", "processing", "started", "처리 중", "연결 재시도"].includes(status)) return { terminal: false, failed: false, label: "처리 중" };
    return { terminal: false, failed: false, label: status || "상태 확인 중" };
  }
  const pollingJobs = new Set();
  async function pollJob(id, attempt = 0) {
    if (pollingJobs.has(id) || attempt > 300) return;
    pollingJobs.add(id);
    try {
      const response = await api(`/api/jobs/${encodeURIComponent(id)}`);
      const job = isObject(response) ? response : {};
      const result = valueAt(job, "result");
      const meta = jobState(job);
      const stored = state.jobs.find(item => item.id === String(id));
      if (stored) { stored.status = meta.label; saveStoredJobs(); }
      if (meta.terminal) {
        if (meta.failed) {
          const error = valueAt(job, "error");
          if (stored) stored.status = "실패";
          state.jobResult = { status: "failed", error: error ?? "작업이 실패했습니다.", question: stored?.question, kind: stored?.kind };
          saveStoredJobs();
        } else {
          if (stored) stored.status = "완료";
          state.jobResult = result ?? job;
          saveStoredJobs();
          const decisionId = valueAt(result, "decision_id", "decisionId") ?? (valueAt(result, "id") && String(valueAt(result, "id")) !== String(id) ? result.id : undefined);
          if (decisionId !== undefined) await loadDecisionDetail(decisionId, false);
          await loadDecisionList(false);
        }
        if (state.view === "decisions") renderDecisionPanels();
      } else {
        if (state.view === "decisions") renderJobsPanel();
        window.setTimeout(() => { pollingJobs.delete(id); pollJob(id, attempt + 1); }, 2300);
        return;
      }
    } catch (error) {
      const stored = state.jobs.find(item => item.id === String(id));
      if (stored && !jobState({ status: stored.status }).terminal) stored.status = "연결 재시도";
      saveStoredJobs();
      if (state.view === "decisions") renderJobsPanel();
      window.setTimeout(() => { pollingJobs.delete(id); pollJob(id, attempt + 1); }, 4200);
      return;
    }
    pollingJobs.delete(id);
  }
  function renderDecisions() {
    page.replaceChildren();
    page.append(pageHeading("DECISION WORKBENCH", "설계 판단", "하드웨어·커널·실험·지식 질문을 검토하고, 출처 근거·미확인 항목·다음 행동을 확인합니다."));
    const layout = el("div", "decision-layout");
    const formPanel = el("section", "surface decision-form-card");
    const header = el("div", "surface-header"); const heading = el("div"); add(heading, text("h2", "새 판단 요청"), text("p", "질문과 알려진 조건을 입력합니다.")); header.append(heading); formPanel.append(header);
    const form = el("form", "decision-form-body"); form.id = "decision-form";
    form.append(text("p", "DECISION TYPE", "decision-kind-label"));
    const choices = el("div", "choice-row");
    Object.entries(decisionKinds).forEach(([kind, config]) => {
      const choice = button(config.label, () => { state.decisionKind = kind; renderDecisions(); }, "choice-button");
      choice.setAttribute("aria-pressed", String(state.decisionKind === kind)); choices.append(choice);
    });
    form.append(choices);
    const questionField = el("div", "field"); questionField.style.marginTop = "15px";
    const questionLabel = text("label", "질문"); questionLabel.htmlFor = "decision-question";
    const question = el("textarea", "textarea"); question.id = "decision-question"; question.required = true; question.maxLength = 4000; question.placeholder = "지금 결정해야 할 내용을 구체적으로 적어 주세요.";
    add(questionField, questionLabel, question, text("span", "답변보다 판단에 필요한 근거·제약·미확인 항목을 명확히 하는 데 사용됩니다.", "field-hint"));
    form.append(questionField);
    const typedFields = el("div", "form-grid"); typedFields.style.marginTop = "13px";
    const config = decisionKinds[state.decisionKind];
    config.fields.forEach(([key, label, type, hint]) => {
      const field = el("div", `field${type === "textarea" ? " span-full" : ""}`);
      const labelNode = text("label", label); labelNode.htmlFor = `decision-${key}`;
      const control = el(type === "textarea" ? "textarea" : "input", type === "textarea" ? "textarea" : "input");
      control.id = `decision-${key}`; control.dataset.inputKey = key;
      if (type !== "textarea") control.type = "text";
      control.placeholder = hint;
      add(field, labelNode, control);
      if (type !== "textarea") field.append(text("span", hint, "field-hint"));
      typedFields.append(field);
    });
    form.append(typedFields);
    const contextDetails = el("details", "decision-context");
    contextDetails.append(text("summary", "추가 JSON context (선택)"));
    const contextBody = el("div", "decision-context-body");
    const contextLabel = text("label", "Context object"); contextLabel.htmlFor = "decision-context-json";
    const contextInput = el("textarea", "textarea code"); contextInput.id = "decision-context-json"; contextInput.maxLength = 12000; contextInput.placeholder = "{}";
    add(contextBody, contextLabel, contextInput, text("span", "JSON object로 추가 조건을 전달합니다. 위의 유형별 입력과 key가 겹치면 유형별 입력값이 우선합니다.", "field-hint"));
    contextDetails.append(contextBody); form.append(contextDetails);
    const caveat = el("div", "decision-caveat");
    const caveatMark = text("span", "!", "scope-mark"); caveatMark.style.background = "#fff1a5"; caveatMark.style.color = "#7d4e00";
    add(caveat, caveatMark, text("span", "자료가 뒷받침하지 않는 값은 unknown/gap으로 남깁니다. HAT 결과는 permission과 buildability를 혼동하지 않으며, 시뮬레이션은 실측값이 아닙니다.")); form.append(caveat);
    const actions = el("div", "form-actions"); const submit = button("판단 작업 시작", null, "button", "submit"); submit.id = "decision-submit";
    const status = text("span", "", "form-status"); status.id = "decision-form-status";
    status.setAttribute("aria-live", "polite");
    add(actions, submit, status); form.append(actions);
    form.addEventListener("submit", event => { event.preventDefault(); submitDecision(form); });
    formPanel.append(form); layout.append(formPanel);

    const right = el("div", "stack");
    const jobs = surface("작업 상태", "요청한 판단의 진행 상황"); jobs.body.id = "jobs-body"; jobs.card.id = "jobs-panel";
    const result = surface("판단 결과와 근거", "결론, 인용 자료, 미확인 항목"); result.body.id = "decision-result-body"; result.card.id = "decision-result-panel";
    const history = surface("판단 이력", "이전 질문과 출처를 다시 확인합니다."); history.body.id = "decision-history-body"; history.card.id = "decision-history-panel";
    [jobs, result, history].forEach(panel => panel.card.append(panel.body));
    add(right, jobs.card, result.card, history.card); layout.append(right); page.append(layout);
    renderDecisionPanels();
  }
  async function submitDecision(form) {
    const question = $("#decision-question", form).value.trim();
    if (!question) { $("#decision-question", form).focus(); return; }
    let context = {};
    const contextText = $("#decision-context-json", form).value.trim();
    if (contextText) {
      try { context = JSON.parse(contextText); }
      catch (error) { toast(`JSON context를 확인해 주세요: ${safeError(error)}`, true); $("#decision-context-json", form).focus(); return; }
      if (!isObject(context)) { toast("JSON context는 object 형식이어야 합니다.", true); $("#decision-context-json", form).focus(); return; }
    }
    const typedInput = {};
    $$('[data-input-key]', form).forEach(control => { const value = control.value.trim(); if (value) typedInput[control.dataset.inputKey] = value; });
    const input = { ...context, ...typedInput };
    const submit = $("#decision-submit", form), status = $("#decision-form-status", form);
    submit.disabled = true; status.classList.remove("is-error", "is-success"); status.textContent = "판단 작업을 등록하고 있습니다…";
    try {
      const response = await api("/api/decisions", { method: "POST", body: { kind: state.decisionKind, question, input } });
      const id = valueAt(response, "job_id", "id");
      if (id === undefined) throw new Error("작업 ID를 확인하지 못했습니다.");
      const jobId = String(id);
      const job = { id: jobId, kind: state.decisionKind, question, status: "대기", createdAt: new Date().toISOString() };
      state.jobs = [job, ...state.jobs.filter(item => item.id !== jobId)].slice(0, 12);
      state.jobResult = null; state.decisions.detail = null; state.decisions.selectedId = null;
      saveStoredJobs(); status.classList.add("is-success"); status.textContent = "작업을 등록했습니다. 진행 상태를 확인합니다.";
      renderDecisionPanels(); pollJob(jobId);
    } catch (error) { status.classList.add("is-error"); status.textContent = safeError(error); }
    finally { submit.disabled = false; }
  }
  async function loadDecisionList(showLoading = true) {
    state.decisions.loading = showLoading; state.decisions.error = null;
    if (showLoading && state.view === "decisions") renderDecisionPanels();
    try {
      const response = await api("/api/decisions");
      state.decisions.items = listOf(response); state.decisions.error = null;
    } catch (error) { state.decisions.error = safeError(error); }
    finally { state.decisions.loading = false; if (state.view === "decisions") renderDecisionPanels(); }
  }
  async function loadDecisionDetail(id, showLoading = true) {
    state.decisions.selectedId = String(id); state.decisions.loadingDetail = showLoading; state.decisions.detailError = null;
    if (showLoading && state.view === "decisions") renderDecisionDetailPanel();
    try {
      state.decisions.detail = await api(`/api/decisions/${encodeURIComponent(id)}`);
      state.decisions.detailError = null;
    } catch (error) { state.decisions.detailError = safeError(error); state.decisions.detail = null; }
    finally { state.decisions.loadingDetail = false; if (state.view === "decisions") renderDecisionDetailPanel(); }
  }
  function renderDecisionPanels() { renderJobsPanel(); renderDecisionDetailPanel(); renderDecisionHistoryPanel(); }
  function renderJobsPanel() {
    const body = $("#jobs-body"); if (!body) return; body.replaceChildren();
    const jobs = state.jobs;
    if (!jobs.length) { body.append(emptyState("진행 중인 작업이 없습니다", "판단 요청을 제출하면 job 상태가 여기에 표시됩니다.")); return; }
    const list = el("div", "job-list");
    jobs.forEach(job => {
      const meta = jobState({ status: job.status });
      const row = el("div", "job-row");
      add(row, el("span", `job-dot${meta.terminal && !meta.failed ? " is-done" : meta.failed ? " is-error" : ""}`), text("span", job.question ? shortText(job.question, 90) : `job ${shortText(job.id, 36)}`, "job-question"), text("span", job.status, "job-status"));
      list.append(row);
    });
    body.append(list);
  }
  function renderDecisionHistoryPanel() {
    const body = $("#decision-history-body"); if (!body) return; body.replaceChildren();
    if (state.decisions.loading) { body.append(loadingState("판단 이력을 불러옵니다.")); return; }
    if (state.decisions.error) { body.append(errorState(state.decisions.error, () => loadDecisionList())); return; }
    if (!state.decisions.items.length) { body.append(emptyState("아직 판단 기록이 없습니다", "질문을 실행하면 처리 결과와 근거가 여기에 나타납니다.")); return; }
    const list = el("div", "history-list");
    state.decisions.items.forEach(item => {
      const id = valueAt(item, "id", "decision_id");
      const row = el("button", "history-item"); row.type = "button";
      if (id !== undefined && String(id) === state.decisions.selectedId) row.setAttribute("aria-current", "true");
      add(row, text("span", `${asText(valueAt(item, "kind"), "판단")} · ${fmtDate(valueAt(item, "created_at", "createdAt"))}`, "history-topline"), text("span", shortText(valueAt(item, "question", "title"), 150), "history-question"));
      row.addEventListener("click", () => { if (id !== undefined) loadDecisionDetail(id); });
      list.append(row);
    });
    body.append(list);
  }
  function renderDecisionDetailPanel() {
    const body = $("#decision-result-body"); if (!body) return; body.replaceChildren();
    if (state.decisions.loadingDetail) { body.append(loadingState("판단 상세와 출처 근거를 불러옵니다.")); return; }
    if (state.decisions.detailError) { body.append(errorState(state.decisions.detailError, () => loadDecisionDetail(state.decisions.selectedId))); return; }
    const detail = state.decisions.detail ?? state.jobResult;
    if (!detail) { body.append(emptyState("표시할 판단 결과가 없습니다", "작업을 시작하거나 이력에서 판단 항목을 선택해 주세요.")); return; }
    const question = valueAt(detail, "question") ?? state.jobs.find(job => job.id === state.decisions.selectedId)?.question;
    const kind = valueAt(detail, "kind") ?? state.jobs.find(job => job.id === state.decisions.selectedId)?.kind;
    add(body, text("span", `${asText(kind, "판단")} · ${fmtDate(valueAt(detail, "created_at", "createdAt"))}`, "detail-eyebrow"), text("h3", asText(question, "판단 결과")));
    const result = valueAt(detail, "result") ?? detail;
    const summary = isObject(result) ? valueAt(result, "answer", "summary", "recommendation", "verdict") : result;
    if (summary !== undefined && (typeof summary === "string" || typeof summary === "number")) body.append(text("p", String(summary), "result-excerpt"));
    body.append(text("pre", safeJson(result), "json-result"));
    const evidence = valueAt(detail, "evidence") ?? (isObject(result) ? valueAt(result, "evidence", "citations") : undefined);
    if (evidence) {
      const section = el("section", "detail-section"); const evidenceItems = Array.isArray(evidence) ? evidence : [evidence];
      const title = el("h4", "detail-section-title"); add(title, text("span", "근거 출처"), text("span", `${evidenceItems.length}개 인용`)); section.append(title);
      const list = el("div", "decision-evidence");
      evidenceItems.forEach(item => {
        const card = el("article", "evidence-card");
        add(card, text("strong", asText(valueAt(item, "title", "material_title", "source"), "근거 자료"), "small"));
        const quote = valueAt(item, "quote", "text", "excerpt", "snippet");
        if (quote) card.append(text("blockquote", quote, "evidence-quote"));
        const url = valueAt(item, "url", "source_url"); if (url && safeUrl(url)) card.append(link("원문", url));
        const location = [valueAt(item, "chunk_id"), valueAt(item, "start"), valueAt(item, "end")].filter(value => value !== undefined).map(asText).join(" · ");
        if (location) card.append(text("div", location, "evidence-footer"));
        list.append(card);
      }); section.append(list); body.append(section);
    }
    const selectedId = valueAt(detail, "id", "decision_id") ?? state.decisions.selectedId;
    if (selectedId !== undefined) {
      const feedback = el("section", "feedback-panel");
      add(feedback, text("h4", "이 판단에 대한 피드백"));
      const note = el("textarea", "textarea feedback-notes"); note.rows = 2; note.maxLength = 8000; note.placeholder = "근거가 부족하거나 잘못된 부분을 적어 주세요 (선택)";
      const controls = el("div", "feedback-controls");
      [["useful", "도움 됨"], ["incorrect", "잘못됨"], ["needs_evidence", "근거 필요"]].forEach(([verdict, label]) => {
        controls.append(button(label, () => sendFeedback(selectedId, verdict, note.value), "button button-secondary button-small"));
      });
      const status = text("p", "피드백은 보조 기록이며 Melete searchable 완료를 뜻하지 않습니다.", "field-hint");
      add(feedback, note, controls, status); body.append(feedback);
    }
  }
  async function sendFeedback(decisionId, verdict, notes) {
    try {
      const result = await api("/api/feedback", { method: "POST", body: { decision_id: decisionId, verdict, notes: notes.trim() } });
      const melete = valueAt(result, "melete");
      toast(melete === undefined ? `피드백이 기록되었습니다 (${asText(valueAt(result, "status"), "상태 확인 불가")}).` : `피드백 기록 완료 · Melete 상태: ${asText(melete)}`);
    } catch (error) { toast(safeError(error), true); }
  }

  async function loadExperiments(showLoading = true) {
    state.experiments.loading = showLoading; state.experiments.error = null;
    if (showLoading && state.view === "experiments") renderExperimentPanels();
    try {
      const response = await api("/api/experiments");
      state.experiments.items = listOf(response); state.experiments.error = null;
    } catch (error) { state.experiments.error = safeError(error); }
    finally { state.experiments.loading = false; if (state.view === "experiments") renderExperimentPanels(); }
  }
  function renderExperiments() {
    page.replaceChildren();
    page.append(pageHeading("EXPERIMENT LEDGER", "실험 기록", "실험 조건과 MetricVector를 기록하고 비교합니다. 측정·시뮬레이션 여부는 선택한 방법과 기록 범위에 한정됩니다."));
    const layout = el("div", "experiment-grid");
    const formPanel = el("section", "surface");
    const header = el("div", "surface-header"); const title = el("div"); add(title, text("h2", "새 실험 등록"), text("p", "측정값과 비교 방향을 그대로 기록합니다.")); header.append(title); formPanel.append(header);
    const form = el("form", "form-card form-grid"); form.id = "experiment-form";
    const fields = [
      ["experiment-name", "실험 이름", "name", "text", "비교 실험의 구분 이름", true],
      ["experiment-cohort", "Cohort", "cohort", "text", "동일 조건 비교를 위한 cohort", true]
    ];
    fields.forEach(([id, label, name, type, placeholder, required]) => {
      const field = el("div", "field"); const labelNode = text("label", label); labelNode.htmlFor = id;
      const input = el("input", "input"); input.id = id; input.name = name; input.type = type; input.placeholder = placeholder; input.required = required;
      input.maxLength = 200;
      field.append(labelNode, input); form.append(field);
    });
    const methodField = el("div", "field span-full");
    const methodLabel = text("label", "방법"); methodLabel.htmlFor = "experiment-method";
    const method = el("select", "select"); method.id = "experiment-method"; method.name = "method"; method.required = true;
    method.append(new Option("실제 방법 선택", ""));
    [["measured", "Measured · 실측"], ["analytical", "Analytical · 해석식"], ["simulated", "Simulated · 시뮬레이션"], ["replay", "Replay · 재생"], ["imported", "Imported · 외부 결과 가져오기"]].forEach(([value, label]) => method.append(new Option(label, value)));
    add(methodField, methodLabel, method, text("span", "측정·해석식·시뮬레이션·재생·가져오기 중 실제로 사용한 방법을 선택합니다.", "field-hint")); form.append(methodField);
    const metricField = el("div", "field span-full");
    const metricHead = el("div", "section-heading"); add(metricHead, text("span", "측정 지표", "field-label"), button("+ 지표 추가", () => addMetricRow($("#metric-rows")), "button button-secondary button-small"));
    const metricRows = el("div", "metric-table"); metricRows.id = "metric-rows"; addMetricRow(metricRows);
    metricField.append(metricHead, metricRows, text("span", "값은 숫자로 기록합니다. 각 지표에 개선 방향(min 또는 max)을 선택해 주세요.", "field-hint")); form.append(metricField);
    const contextField = el("div", "field span-full");
    const contextLabel = text("label", "실험 context (JSON, 선택)"); contextLabel.htmlFor = "experiment-context";
    const context = el("textarea", "textarea code"); context.id = "experiment-context"; context.maxLength = 50000; context.placeholder = '{\n  "workload": "실제 입력 조건",\n  "environment": "실행 환경 식별 정보"\n}';
    add(contextField, contextLabel, context, text("span", "환경·입력 조건을 JSON 객체로 적습니다. 민감 정보는 입력하지 마세요.", "field-hint")); form.append(contextField);
    const actions = el("div", "form-actions span-full"); const submit = button("실험 기록 저장", null, "button", "submit"); submit.id = "experiment-submit";
    const status = text("span", "", "form-status"); status.id = "experiment-form-status"; status.setAttribute("aria-live", "polite"); add(actions, submit, status); form.append(actions);
    form.addEventListener("submit", event => { event.preventDefault(); submitExperiment(form); });
    formPanel.append(form); layout.append(formPanel);
    const right = el("div", "stack");
    const list = surface("등록된 실험", "실제 저장된 조건과 측정 지표"); list.card.id = "experiment-list-card"; list.body.id = "experiment-list-body";
    const compare = surface("두 실험 비교", "같은 cohort와 방법을 사용한 실험의 공통 지표를 비교합니다."); compare.card.id = "experiment-compare-card"; compare.body.id = "experiment-compare-body";
    add(right, list.card, compare.card); layout.append(right); page.append(layout); renderExperimentPanels();
  }
  function addMetricRow(container) {
    if ($$(".metric-row", container).length >= 50) { toast("실험당 지표는 최대 50개까지 기록할 수 있습니다.", true); return; }
    metricRowCounter += 1;
    const row = el("div", "metric-row");
    const fields = [
      ["지표명", "name", "input", "예: latency"], ["값", "value", "input", "숫자"], ["단위", "unit", "input", "예: ms"], ["방향", "direction", "select", ""]
    ];
    fields.forEach(([label, key, type, placeholder]) => {
      const field = el("div", "field"); const labelNode = text("label", label); labelNode.htmlFor = `metric-${metricRowCounter}-${key}`;
      const control = el(type, type === "select" ? "select" : "input"); control.dataset.metricKey = key; control.id = labelNode.htmlFor;
      if (type === "input") { control.type = key === "value" ? "number" : "text"; if (key === "value") control.step = "any"; else control.maxLength = key === "name" ? 80 : 50; control.placeholder = placeholder; }
      else { control.required = true; control.append(new Option("방향 선택", ""), new Option("낮을수록 좋음 · min", "min"), new Option("높을수록 좋음 · max", "max")); }
      field.append(labelNode, control); row.append(field);
    });
    const remove = button("×", () => {
      if ($$(".metric-row", container).length <= 1) { toast("MetricVector에 지표가 하나 이상 필요합니다.", true); return; }
      row.remove();
    }, "metric-remove"); remove.setAttribute("aria-label", "이 지표 제거"); row.append(remove); container.append(row);
  }
  async function submitExperiment(form) {
    const name = $("[name=name]", form).value.trim();
    const cohort = $("[name=cohort]", form).value.trim();
    const method = $("[name=method]", form).value.trim();
    const metrics = [];
    for (const row of $$(".metric-row", form)) {
      const metric = {};
      row.querySelectorAll("[data-metric-key]").forEach(control => { metric[control.dataset.metricKey] = control.value.trim(); });
      if (!metric.name || !metric.value || !metric.unit || !metric.direction) { toast("각 MetricVector 지표의 이름, 숫자 값, 단위, 방향을 입력해 주세요.", true); return; }
      const value = Number(metric.value);
      if (!Number.isFinite(value)) { toast("지표 값은 유한한 숫자여야 합니다.", true); return; }
      metrics.push({ name: metric.name, value, unit: metric.unit, direction: metric.direction });
    }
    let context = {};
    const contextText = $("#experiment-context", form).value.trim();
    if (contextText) {
      try { context = JSON.parse(contextText); }
      catch (error) { toast(`context JSON을 확인해 주세요: ${safeError(error)}`, true); $("#experiment-context", form).focus(); return; }
      if (!isObject(context)) { toast("context에는 JSON object를 입력해 주세요.", true); return; }
    }
    const submit = $("#experiment-submit", form), status = $("#experiment-form-status", form);
    submit.disabled = true; status.classList.remove("is-error", "is-success"); status.textContent = "실험 데이터를 저장하고 있습니다…";
    try {
      const result = await api("/api/experiments", { method: "POST", body: { name, cohort, method, metrics, context } });
      status.classList.add("is-success"); status.textContent = `실험이 등록되었습니다 · ID ${asText(valueAt(result, "id"), "응답 ID 없음")}`;
      form.reset(); const rows = $("#metric-rows"); rows.replaceChildren(); addMetricRow(rows);
      await loadExperiments(false); toast("실험 기록을 저장했습니다.");
    } catch (error) { status.classList.add("is-error"); status.textContent = safeError(error); }
    finally { submit.disabled = false; }
  }
  function renderExperimentPanels() { renderExperimentList(); renderExperimentCompare(); }
  function renderExperimentList() {
    const body = $("#experiment-list-body"); if (!body) return; body.replaceChildren();
    if (state.experiments.loading) { body.append(loadingState("등록된 실험을 확인하고 있습니다.")); return; }
    if (state.experiments.error) { body.append(errorState(state.experiments.error, () => loadExperiments())); return; }
    if (!state.experiments.items.length) { body.append(emptyState("등록된 실험이 없습니다", "저장된 실험과 MetricVector가 여기에 나타납니다.")); return; }
    const list = el("div", "experiment-list");
    state.experiments.items.forEach(item => {
      const row = el("article", "experiment-item");
      const select = el("input"); select.type = "checkbox"; select.value = String(valueAt(item, "id") ?? ""); select.setAttribute("aria-label", `${asText(valueAt(item, "name"), "실험")} 비교 선택`);
      const selector = el("label", "experiment-selector"); selector.append(select);
      select.checked = [state.experiments.baselineId, state.experiments.candidateId].includes(select.value) && Boolean(select.value);
      select.addEventListener("change", () => {
        if (select.checked) {
          if (!state.experiments.baselineId || state.experiments.baselineId === state.experiments.candidateId) state.experiments.baselineId = select.value;
          else if (!state.experiments.candidateId || state.experiments.candidateId === state.experiments.baselineId) state.experiments.candidateId = select.value;
          else { select.checked = false; toast("비교를 위해 두 개의 실험만 선택해 주세요.", true); }
        } else {
          if (state.experiments.baselineId === select.value) state.experiments.baselineId = "";
          if (state.experiments.candidateId === select.value) state.experiments.candidateId = "";
        }
        renderExperimentCompare();
      });
      const copy = el("div");
      add(copy, text("h4", asText(valueAt(item, "name"), "이름 없음")), text("div", `${asText(valueAt(item, "cohort"), "cohort 없음")} · ${asText(valueAt(item, "method"), "방법 없음")} · ${fmtDate(valueAt(item, "created_at", "createdAt"))}`, "experiment-meta"));
      const metrics = listOf(valueAt(item, "metrics"));
      if (metrics.length) {
        const chips = el("div", "metric-chips");
        metrics.forEach(metric => chips.append(text("span", `${asText(valueAt(metric, "name"))} ${asText(valueAt(metric, "value"))} ${asText(valueAt(metric, "unit"))} · ${asText(valueAt(metric, "direction"))}`, "metric-chip")));
        copy.append(chips);
      }
      add(row, selector, copy); list.append(row);
    });
    body.append(list);
  }
  async function compareExperiments() {
    const model = state.experiments;
    if (!model.baselineId || !model.candidateId) { toast("비교할 baseline과 candidate 두 실험을 선택해 주세요.", true); return; }
    if (model.baselineId === model.candidateId) { toast("서로 다른 두 실험을 선택해 주세요.", true); return; }
    model.compare = null; model.compareError = null; model.compareLoading = true; renderExperimentCompare();
    try { model.compare = await api("/api/experiments/compare", { method: "POST", body: { baseline_id: model.baselineId, candidate_id: model.candidateId } }); }
    catch (error) { model.compareError = safeError(error); }
    finally { model.compareLoading = false; if (state.view === "experiments") renderExperimentCompare(); }
  }
  function renderExperimentCompare() {
    const body = $("#experiment-compare-body"); if (!body) return; body.replaceChildren();
    const choices = el("div", "compare-selectors");
    [["baseline", "Baseline", "baselineId"], ["candidate", "Candidate", "candidateId"]].forEach(([id, label, key]) => {
      const field = el("div", "field"); const caption = text("label", label); caption.htmlFor = `compare-${id}`;
      const select = el("select", "select"); select.id = `compare-${id}`; select.append(new Option("실험 선택", ""));
      state.experiments.items.forEach(item => select.append(new Option(`${asText(valueAt(item, "name"), "이름 없음")} · ${asText(valueAt(item, "cohort"), "cohort 없음")}`, String(valueAt(item, "id") ?? ""))));
      select.value = state.experiments[key] || ""; select.addEventListener("change", () => { state.experiments[key] = select.value; renderExperimentList(); });
      field.append(caption, select); choices.append(field);
    });
    body.append(choices);
    const actionLine = el("div", "form-actions"); actionLine.style.padding = "0 15px 13px";
    const compareButton = button("실험 비교", compareExperiments, "button button-secondary button-small");
    compareButton.disabled = state.experiments.loading || state.experiments.compareLoading || !state.experiments.items.length;
    actionLine.append(compareButton); body.append(actionLine);
    if (state.experiments.loading) { body.append(loadingState("비교 조건을 불러옵니다.")); return; }
    if (state.experiments.error) return;
    if (state.experiments.compareLoading) { body.append(loadingState("실험 지표를 비교하고 있습니다.")); return; }
    if (state.experiments.compareError) { body.append(errorState(state.experiments.compareError, compareExperiments)); return; }
    if (!state.experiments.compare) { body.append(text("p", "두 실험을 선택하면 공통 지표와 비교에서 제외된 항목을 확인할 수 있습니다.", "comparison-summary")); return; }
    const response = state.experiments.compare;
    const comparisons = listOf(response.comparisons);
    if (comparisons.length) {
      const list = el("div", "comparison-list");
      comparisons.forEach(item => {
        const row = el("div", "comparison-item"); const copy = el("div");
        const baselineUnit = valueAt(item, "baseline_unit", "unit");
        const candidateUnit = valueAt(item, "candidate_unit", "unit");
        const values = `Baseline ${asText(valueAt(item, "baseline", "baseline_value"), "—")}${baselineUnit ? ` ${asText(baselineUnit)}` : ""} · Candidate ${asText(valueAt(item, "candidate", "candidate_value"), "—")}${candidateUnit ? ` ${asText(candidateUnit)}` : ""}`;
        const result = asText(valueAt(item, "status", "result"), "상태 미제공");
        const resultLabel = ({ improved: "개선", regressed: "악화", equivalent: "동일" })[result] || result;
        add(copy, text("div", asText(valueAt(item, "name", "metric"), "metric"), "comparison-name"), text("div", values, "comparison-values"));
        add(row, copy, text("span", resultLabel, `tag${result === "improved" ? " tag-green" : result === "regressed" ? " tag-red" : ""}`));
        list.append(row);
      }); body.append(list);
    }
    const summary = el("div", "comparison-summary");
    const dominance = valueAt(response, "dominance"); const exclusions = valueAt(response, "exclusions");
    const statusLabels = { comparable: "비교 가능", not_comparable: "조건 불일치", incomplete: "비교 정보 부족" };
    const dominanceLabels = { candidate_dominates: "후보 실험 우위 (기록 지표상)", baseline_dominates: "기준 실험 우위 (기록 지표상)", tradeoff: "지표별 상충 관계", equivalent: "기록 값 동일", unknown: "우위 판정 없음" };
    add(summary, text("p", `비교 상태 · ${statusLabels[valueAt(response, "status")] || asText(valueAt(response, "status"), "상태 미제공")}`));
    if (dominance !== undefined) summary.append(text("p", `결과 · ${dominanceLabels[dominance] || asText(dominance)}`));
    if (exclusions !== undefined) {
      const labels = Array.isArray(exclusions) ? exclusions.map(item => {
        const value = String(item);
        if (value === "cohort_mismatch") return "Cohort가 달라 비교할 수 없습니다.";
        if (value === "method_mismatch") return "실험 방법이 달라 비교할 수 없습니다.";
        if (value.startsWith("missing_required_metric:")) return `공통 지표가 없습니다: ${value.slice("missing_required_metric:".length)}`;
        if (value.startsWith("metric_definition_mismatch:")) return `지표 정의가 다릅니다: ${value.slice("metric_definition_mismatch:".length)}`;
        return value;
      }) : [asText(exclusions)];
      labels.forEach(label => summary.append(text("p", `비교 제외 · ${label}`)));
    }
    const limitations = valueAt(response, "limitations");
    if (limitations) (Array.isArray(limitations) ? limitations : [limitations]).forEach(item => {
      const value = asText(item);
      summary.append(text("p", value === "Point values only; confidence intervals and physical feasibility are not established." ? "단일 기록값만 비교합니다. 신뢰 구간과 물리적 구현 가능성은 확인하지 않습니다." : value));
    });
    body.append(summary);
    const rawDetails = el("details", "evidence-card");
    add(rawDetails, text("summary", "상세 비교 값"), text("pre", safeJson(response), "json-result")); body.append(rawDetails);
  }

  async function loadSystem() {
    state.capabilitiesError = null; state.statsError = null; state.healthError = null;
    renderSystem();
    const [caps, stats, health] = await Promise.allSettled([api("/api/capabilities"), api("/api/stats"), api("/api/health")]);
    if (caps.status === "fulfilled") { state.capabilities = caps.value; state.capabilitiesError = null; }
    else state.capabilitiesError = safeError(caps.reason);
    if (stats.status === "fulfilled") { state.stats = stats.value; state.statsError = null; }
    else state.statsError = safeError(stats.reason);
    if (health.status === "fulfilled") { state.health = health.value; state.healthError = null; }
    else state.healthError = safeError(health.reason);
    setConnection(stats.status === "fulfilled");
    if (state.view === "system") renderSystem();
  }
  function capabilityCards(value) {
    const container = el("div", "capability-grid");
    let entries = [];
    if (Array.isArray(value)) entries = value.map((item, index) => [asText(valueAt(item, "name", "id"), `Capability ${index + 1}`), item]);
    else if (isObject(value) && Array.isArray(value.capabilities)) entries = value.capabilities.map((item, index) => [asText(valueAt(item, "name", "id"), `Capability ${index + 1}`), item]);
    else if (isObject(value) && isObject(value.capabilities)) entries = Object.entries(value.capabilities);
    else if (isObject(value)) {
      if (isObject(value.native)) entries.push(...Object.entries(value.native).map(([key, item]) => [`Native · ${key}`, item]));
      entries.push(...Object.entries(value).filter(([key]) => key !== "native"));
    }
    entries = entries.filter(([key]) => !/(?:api.?key|secret|token|password|credential|authorization)/i.test(String(key)));
    if (!entries.length) { container.append(emptyState("Capability 정보가 없습니다", "현재 연결에서 확인된 capability가 없습니다.")); return container; }
    entries.forEach(([key, raw]) => {
      const card = el("article", "capability-card");
      const primitiveStatus = typeof raw === "boolean" || (typeof raw === "string" && (positiveStatus(raw) || negativeStatus(raw) || /^(supported|native)(?:\b.*)?$/i.test(raw.trim())));
      const statusValue = isObject(raw) ? valueAt(raw, "status", "state", "available", "enabled", "configured") : primitiveStatus ? raw : undefined;
      const detail = isObject(raw) ? valueAt(raw, "description", "detail", "message", "reason") : primitiveStatus ? undefined : raw;
      const off = negativeStatus(statusValue);
      const ready = !off && (positiveStatus(statusValue) || (typeof statusValue === "string" && /^(supported|native)(?:\b.*)?$/i.test(statusValue.trim())));
      const statusLabel = statusValue === undefined ? (detail === undefined ? "상태 미표시" : "설명") : typeof statusValue === "boolean" ? (statusValue ? "사용 가능" : "사용 불가") : asText(statusValue);
      const status = text("span", statusLabel, `tag${ready ? " tag-green" : off ? " tag-amber" : ""}`);
      const title = el("h3"); add(title, text("span", key), status); card.append(title);
      if (detail !== undefined) card.append(text("p", asText(detail)));
      const excluded = new Set(["status", "state", "available", "enabled", "configured", "description", "detail", "message", "reason"]);
      const details = isObject(raw) ? Object.entries(raw).filter(([name]) => !excluded.has(name) && !/(?:api.?key|secret|token|password|credential)/i.test(name)) : [];
      if (details.length) {
        const list = el("div", "capability-details");
        details.slice(0, 8).forEach(([name, item]) => {
          const row = el("div", "capability-detail-row"); add(row, text("span", name), text("strong", asText(item))); list.append(row);
        }); card.append(list);
      } else if (detail !== undefined) card.append(text("p", asText(detail)));
      container.append(card);
    });
    return container;
  }
  function renderSystem() {
    page.replaceChildren();
    page.append(pageHeading("RUNTIME & INTEGRATION", "시스템 상태", "실행 환경과 실제 연결 상태를 API에서 확인합니다. 표시되지 않은 capability는 미확인 상태로 취급합니다."));
    const healthPanel = surface("서비스와 저장소", "서버 응답·PostgreSQL 연결·TLS 상태");
    if (state.healthError) healthPanel.body.append(errorState(state.healthError, loadSystem));
    else if (!state.health) healthPanel.body.append(loadingState("서버와 데이터베이스 연결 상태를 확인합니다."));
    else {
      const rows = el("div", "provider-list");
      const tls = state.health.client_pooler_tls;
      [["서비스", valueAt(state.health, "status")], ["데이터베이스", valueAt(state.health, "database")], ["DB 연결 암호화", tls === true ? "TLS 사용 중" : tls === false ? "TLS 미사용" : undefined], ["버전", valueAt(state.health, "version")]].forEach(([name, value]) => {
        if (value === undefined || value === null) return;
        const good = name === "서비스" ? String(value).toLowerCase() === "ok" : name === "데이터베이스" ? String(value).toLowerCase() === "connected" : name === "DB 연결 암호화" ? value === "TLS 사용 중" : false;
        const needsAttention = name === "서비스" ? !good : name === "데이터베이스" ? !good : name === "DB 연결 암호화" ? value === "TLS 미사용" : false;
        const row = el("div", "provider-row"); add(row, text("span", name, "provider-name"), text("span", asText(value), "provider-value"), text("span", good ? "확인됨" : needsAttention ? "확인 필요" : "상태", `provider-state${good ? " is-ready" : needsAttention ? " is-off" : ""}`)); rows.append(row);
      });
      healthPanel.body.append(rows);
    }
    healthPanel.card.append(healthPanel.body);
    const providerPanel = surface("Provider model 설정", "선택된 chat·embedding model ID입니다. 제공자 연결 상태와 요청 성공 여부는 별도 지표입니다.");
    if (state.statsError) providerPanel.body.append(errorState(state.statsError, loadSystem));
    else if (!state.stats) providerPanel.body.append(loadingState("선택된 model ID를 확인합니다."));
    else {
      providerPanel.body.append(providerRows(state.stats.providers));
    }
    providerPanel.card.append(providerPanel.body);
    const capsPanel = surface("Runtime capabilities", "GET /api/capabilities 응답 · 확인되지 않은 기능은 지원으로 표시하지 않습니다.", "surface overview-section");
    if (state.capabilitiesError) capsPanel.body.append(errorState(state.capabilitiesError, loadSystem));
    else if (!state.capabilities) capsPanel.body.append(loadingState("API가 반환하는 capability 상태를 확인합니다."));
    else capsPanel.body.append(capabilityCards(state.capabilities));
    capsPanel.card.append(capsPanel.body);
    page.append(healthPanel.card, providerPanel.card, capsPanel.card);

    const validatePanel = surface("Native hardware validation", "POST /api/validate/hardware · 실제 연결된 validator 결과만 표시", "surface overview-section");
    const form = el("form", "form-card");
    const field = el("div", "field"); const label = text("label", "검증할 source"); label.htmlFor = "hardware-source";
    const source = el("textarea", "textarea"); source.id = "hardware-source"; source.required = true; source.maxLength = 200000; source.placeholder = "validator가 받는 source 내용 또는 식별자를 입력합니다.";
    add(field, label, source, text("span", "외부에서 제공된 source를 입력할 때는 지시문으로 실행되지 않습니다. 실제 validator에 전달할 데이터만 입력하세요.", "field-hint"));
    const actions = el("div", "form-actions"); const submit = button("Native 검증 실행", null, "button", "submit"); submit.disabled = state.hardwareValidation.loading; actions.append(submit);
    const status = text("span", "", "form-status"); status.setAttribute("aria-live", "polite");
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const value = source.value.trim(); if (!value) return;
      state.hardwareValidation.loading = true; state.hardwareValidation.result = null; state.hardwareValidation.error = null; submit.disabled = true; status.textContent = "Native validator 실행 중…"; status.className = "form-status";
      try { state.hardwareValidation.result = await api("/api/validate/hardware", { method: "POST", body: { source: value } }); status.classList.add("is-success"); status.textContent = "Validator가 응답했습니다. 아래 verdict를 확인해 주세요."; }
      catch (error) { state.hardwareValidation.error = safeError(error); status.classList.add("is-error"); status.textContent = safeError(error); }
      finally { state.hardwareValidation.loading = false; submit.disabled = false; renderHardwareValidationResult(resultBox); }
    });
    add(actions, status); const resultBox = el("div", "overview-section");
    form.append(field, actions, resultBox); validatePanel.body.append(form); validatePanel.card.append(validatePanel.body); page.append(validatePanel.card);
    renderHardwareValidationResult(resultBox);
    const note = el("div", "scope-note"); add(note, text("span", "i", "scope-mark"), text("span", "HAT schema의 구조 검증은 physical feasibility나 buildability를 입증하지 않습니다. Validator를 사용할 수 없거나 검증이 실패하면 그 상태와 진단을 그대로 표시합니다.")); page.append(note);
  }
  function renderHardwareValidationResult(container) {
    if (!container) return; container.replaceChildren();
    if (state.hardwareValidation.loading) container.append(loadingState("Native validator 응답 대기 중입니다."));
    else if (state.hardwareValidation.error) container.append(errorState(state.hardwareValidation.error));
    else if (state.hardwareValidation.result) {
      const result = state.hardwareValidation.result;
      const verdict = valueAt(result, "verdict", "status");
      if (verdict !== undefined) container.append(text("div", `Native verdict · ${asText(verdict)}`, "tag tag-blue"));
      container.append(text("pre", safeJson(result), "json-result"));
    }
  }

  function renderCurrentView() {
    if (state.view === "overview") { renderOverview(); loadOverview(); }
    else if (state.view === "materials") { renderMaterials(); loadMaterials(); }
    else if (state.view === "retrieval") {
      renderRetrieval();
      if (!state.capabilities) api("/api/capabilities").then(capabilities => {
        state.capabilities = capabilities;
        const mode = $("#retrieval-mode");
        if (state.view === "retrieval" && mode) populateRetrievalModes(mode);
      }).catch(error => { state.capabilitiesError = safeError(error); });
    }
    else if (state.view === "graph") { renderGraph(); loadGraph(); }
    else if (state.view === "decisions") { renderDecisions(); loadDecisionList(); state.jobs.filter(job => !jobState({ status: job.status }).terminal).forEach(job => pollJob(job.id)); }
    else if (state.view === "experiments") { renderExperiments(); loadExperiments(); }
    else { renderSystem(); loadSystem(); }
  }

  $$("[data-view]").forEach(item => item.addEventListener("click", event => {
    event.preventDefault(); goTo(item.dataset.view);
  }));
  $("#mobile-menu").addEventListener("click", () => {
    const open = !$("#sidebar").classList.contains("is-open");
    $("#sidebar").classList.toggle("is-open", open); $("#mobile-backdrop").hidden = !open;
    $("#mobile-menu").setAttribute("aria-expanded", String(open)); $("#mobile-menu").setAttribute("aria-label", open ? "탐색 메뉴 닫기" : "탐색 메뉴 열기");
  });
  $("#mobile-backdrop").addEventListener("click", closeMobileNav);
  document.addEventListener("keydown", event => { if (event.key === "Escape") closeMobileNav(); });
  window.addEventListener("hashchange", () => {
    const view = window.location.hash.slice(1);
    if (labels[view] && view !== state.view) goTo(view, false);
  });
  $("#refresh-button").addEventListener("click", () => renderCurrentView());

  const initialView = window.location.hash.slice(1);
  saveStoredJobs();
  if (labels[initialView]) goTo(initialView, false);
  else renderCurrentView();
})();
