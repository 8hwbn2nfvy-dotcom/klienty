/* Клиенты: переходы между страницами, загрузка данных, радар поиска, карточка заведения.
   Страница никогда не перерисовывается по таймеру: опрос задачи поиска меняет только радар. */
"use strict";

const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const PAGE_MS = REDUCED ? 0 : 280;
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ---------- индикатор прогресса: только если дольше 300 мс ---------- */
let progressCount = 0;
function withProgress(promise) {
  progressCount++;
  const t = setTimeout(() => { $("#progress").hidden = false; }, 300);
  return promise.finally(() => {
    clearTimeout(t);
    if (--progressCount === 0) $("#progress").hidden = true;
  });
}

/* ---------- сообщения ---------- */
let flashTimer = 0;
function flash(text, kind = "ok", keep = false) {
  const box = $("#flash");
  clearTimeout(flashTimer);
  box.className = "flash " + (kind === "ok" ? "" : kind);
  $("p", box).textContent = text;
  box.hidden = false;
  // Успех исчезает сам; предупреждения и ошибки висят, пока их не закроют.
  if (kind === "ok" && !keep) flashTimer = setTimeout(() => { box.hidden = true; }, 4500);
}
function clearFlash() { $("#flash").hidden = true; }

/* ---------- запросы к серверу ---------- */
class ApiError extends Error {
  constructor(message, status, data) { super(message); this.status = status; this.data = data; }
}
async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {}, credentials: "same-origin" };
  if (opts.body !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.body); }
  let res;
  try {
    res = await withProgress(fetch(path, init));
  } catch (e) {
    throw new ApiError("Нет связи с сервером. Проверь интернет; если сайт спал, первое открытие идёт около минуты.", 0);
  }
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; /* не JSON — ниже будет понятная ошибка */ }
  if (res.status === 401 && !opts.allow401) { location.assign("/login"); throw new ApiError("Нужно войти.", 401, data); }
  if (!res.ok) {
    const msg = (data && typeof data.detail === "string") ? data.detail : `Сервер ответил ошибкой ${res.status}.`;
    throw new ApiError(msg, res.status, data);
  }
  return data;
}

/* ---------- тема ---------- */
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem("theme", theme); } catch (e) { /* приватный режим: тема просто не запомнится в браузере */ }
}

/* ---------- переходы между страницами (с предзагрузкой) ---------- */
const prefetched = new Map();
function prefetch(url) {
  if (!prefetched.has(url)) {
    const p = fetch(url, { credentials: "same-origin" }).then((r) => {
      if (r.redirected && new URL(r.url).pathname === "/login") location.assign("/login");
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.text();
    });
    p.catch(() => prefetched.delete(url));
    prefetched.set(url, p);
  }
  return prefetched.get(url);
}

let pageCleanup = null;
let navigating = false;

async function navigate(url, { push = true, notice = null } = {}) {
  const target = new URL(url, location.href);
  if (navigating) return;
  if (push && target.pathname === location.pathname) { closeMenu(); return; }
  navigating = true;
  closeMenu();
  const main = $("#main");
  const htmlP = withProgress(prefetch(target.pathname));
  if (PAGE_MS) { main.classList.remove("entering"); main.classList.add("leaving"); }
  try {
    const [html] = await Promise.all([htmlP, sleep(PAGE_MS)]);
    const doc = new DOMParser().parseFromString(html, "text/html");
    const next = $("#main", doc);
    if (!next) throw new Error("нет содержимого");
    if (pageCleanup) { pageCleanup(); pageCleanup = null; }
    clearFlash();
    main.innerHTML = next.innerHTML;
    main.dataset.page = next.dataset.page;
    document.body.dataset.page = next.dataset.page;
    document.title = doc.title;
    if (push) history.pushState({}, "", target.pathname);
    window.scrollTo(0, 0);
    main.classList.remove("leaving");
    if (PAGE_MS) { void main.offsetWidth; main.classList.add("entering"); }
    prefetched.delete(target.pathname); // в следующий раз — свежая копия
    initPage();
    if (notice) flash(...notice);
  } catch (e) {
    // Мягкий переход не удался — обычная загрузка страницы, чтобы ничего не потерялось.
    if (notice) { try { sessionStorage.setItem("notice", JSON.stringify(notice)); } catch (x) { /* сообщение просто не покажется */ } }
    location.assign(target.pathname);
  } finally {
    navigating = false;
  }
}

document.addEventListener("click", (ev) => {
  const a = ev.target.closest("a[data-link]");
  if (!a || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button !== 0) return;
  ev.preventDefault();
  navigate(a.getAttribute("href"));
});
for (const type of ["pointerenter", "touchstart", "focusin"]) {
  document.addEventListener(type, (ev) => {
    const a = ev.target.closest && ev.target.closest("a[data-link]");
    if (a) prefetch(a.getAttribute("href"));
  }, { capture: true, passive: true });
}
window.addEventListener("popstate", () => navigate(location.pathname, { push: false }));

function closeMenu() {
  const top = $(".top"); top.classList.remove("open");
  $(".menu-toggle").setAttribute("aria-expanded", "false");
}
$(".menu-toggle").addEventListener("click", () => {
  const top = $(".top"); const open = !top.classList.contains("open");
  top.classList.toggle("open", open);
  $(".menu-toggle").setAttribute("aria-expanded", String(open));
});
$(".flash-x").addEventListener("click", clearFlash);

function markMenu() {
  for (const a of $$(".menu a")) {
    if (a.getAttribute("href") === location.pathname) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
}

/* ---------- страницы ---------- */
const PAGES = {};

function initPage() {
  markMenu();
  const page = document.body.dataset.page;
  const fn = PAGES[page];
  if (fn) pageCleanup = fn() || null;
  if (page !== "login") {
    // Заранее подгружаем пункты меню, когда браузер свободен.
    const idle = window.requestIdleCallback || ((f) => setTimeout(f, 800));
    idle(() => $$(".menu a").forEach((a) => prefetch(a.getAttribute("href"))));
  }
}

let cache = null; // настройки + справочники
async function loadSettings(force = false) {
  if (!cache || force) cache = await api("/api/settings");
  applyTheme(cache.settings.theme);
  return cache;
}
const title = (list, id) => (list.find((x) => x.id === id) || {}).title || id;

/* ===== вход ===== */
PAGES.login = () => {
  const card = $(".login-card");
  const show = async () => {
    let st;
    try { st = await api("/api/auth/state", { allow401: true }); }
    catch (e) { showErr(e.message); card.hidden = false; return; }
    if (st.logged_in) { location.assign("/"); return; }
    if (st.configured) { $("#login-form").hidden = false; }
    else {
      $("#setup-form").hidden = false;
      if (st.hash_env_present) $("#setup-reason").textContent =
        "В Render есть PASSWORD_HASH, но строка не похожа на хэш (лишний символ или обрезана). Получи строку заново и замени значение.";
    }
    card.hidden = false;
    const f = $("#pw") && !$("#login-form").hidden ? $("#pw") : $("#pw1");
    if (f && matchMedia("(hover: hover)").matches) f.focus();
  };
  // Точка разворачивается в экран, потом появляется форма.
  setTimeout(show, REDUCED ? 0 : 1050);

  const showErr = (t) => { const e = $("#login-error"); e.textContent = t; e.hidden = !t; };
  $("#login-form").addEventListener("submit", async (ev) => {
    ev.preventDefault(); showErr("");
    const btn = $("#login-form .btn"); btn.disabled = true;
    try { await api("/api/login", { method: "POST", body: { password: $("#pw").value }, allow401: true }); location.assign("/"); }
    catch (e) { showErr(e.message); btn.disabled = false; }
  });
  $("#setup-form").addEventListener("submit", async (ev) => {
    ev.preventDefault(); showErr("");
    try {
      const r = await api("/api/setup/hash", { method: "POST", body: { password: $("#pw1").value, password2: $("#pw2").value } });
      $("#hash-name").textContent = r.name;
      $("#hash-value").textContent = r.value;
      $("#setup-form").hidden = true; $("#setup-result").hidden = false;
    } catch (e) { showErr(e.message); }
  });
  $("#setup-result").addEventListener("click", async (ev) => {
    const b = ev.target.closest("[data-copy]"); if (!b) return;
    const text = $("#" + b.dataset.copy).textContent;
    try { await navigator.clipboard.writeText(text); b.textContent = "Скопировано"; }
    catch (e) {
      const r = document.createRange(); r.selectNodeContents($("#" + b.dataset.copy));
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      b.textContent = "Выделено — скопируй вручную";
    }
  });
};

/* ===== плитки: ниши и города (несколько) / количество (одно) ===== */
function tilesPage() {
  const box = $("#tiles"); const key = box.dataset.key;
  const multi = box.dataset.multi === "1";
  let alive = true;
  let items = [];
  let saved = [];      // что лежит в настройках
  let picked = [];     // что отмечено сейчас (для ниш и городов — до «Готово»)

  const titleOf = (id) => (items.find((x) => x.id === id) || {}).title || id;
  function mark() {
    for (const t of $$(".tile[data-id]", box)) {
      const id = key === "amount" ? Number(t.dataset.id) : t.dataset.id;
      const on = picked.includes(id);
      t.classList.toggle("on", on); t.setAttribute("aria-pressed", String(on));
    }
    if (multi) {
      $("#done").disabled = picked.length === 0;
      $("#picked").textContent = picked.length ? "Выбрано: " + picked.map(titleOf).join(", ") : "Ничего не выбрано — отметь хотя бы одно.";
    }
  }

  (async () => {
    let data;
    try { data = await loadSettings(); } catch (e) { flash(e.message, "err"); return; }
    if (!alive) return;
    items = key === "niches" ? data.catalog.niches : key === "cities" ? data.catalog.cities
      : data.catalog.amounts.map((n) => ({ id: n, title: String(n) }));
    saved = multi ? [...data.settings[key]] : [data.settings[key]];
    picked = [...saved];
    box.innerHTML = items.map((it, i) =>
      `<button type="button" class="tile" data-id="${esc(it.id)}" aria-pressed="false" style="animation-delay:${Math.min(i, 20) * 40}ms">${esc(it.title)}</button>`).join("");
    mark();
  })();

  async function save(value, label) {
    const r = await api("/api/settings", { method: "PUT", body: { [key]: value } });
    cache = { ...cache, settings: r.settings };
    const notice = r.changed.length ? [`Сохранено: ${label}.`] : [`Выбор не поменялся: ${label} — ничего не изменилось.`, "warn"];
    navigate("/", { notice });
  }

  box.addEventListener("click", async (ev) => {
    const b = ev.target.closest(".tile[data-id]"); if (!b) return;
    if (multi) {
      const id = b.dataset.id;
      picked = picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id];
      mark();
      return;
    }
    const id = Number(b.dataset.id);
    picked = [id]; mark();
    try { await save(id, b.textContent); }
    catch (e) { picked = [...saved]; mark(); flash("Не сохранилось, выбор вернулся назад: " + e.message, "err"); }
  });

  if (multi) {
    $("#done").addEventListener("click", async () => {
      const btn = $("#done"); btn.disabled = true;
      try { await save(picked, picked.map(titleOf).join(", ")); }
      catch (e) { btn.disabled = false; flash("Не сохранилось: " + e.message, "err"); }
    });
  }
  return () => { alive = false; };
}
PAGES.niches = tilesPage;
PAGES.cities = tilesPage;
PAGES.amount = tilesPage;

/* ===== карты ===== */
PAGES.sources = () => {
  const ul = $("#sources");
  const draw = (data) => {
    ul.innerHTML = data.catalog.sources.map((s, i) => `
      <li class="source${s.available ? "" : " soon"}" style="animation-delay:${i * 40}ms">
        <div class="src-main">
          <div class="src-name"><b>${esc(s.title)}</b><small>${esc(s.available ? (s.note || "Работает") : (s.note || "Подключим позже"))}</small></div>
          ${s.available ? "" : `<span class="soon-badge">${s.checkable ? "Нет ключа" : "Скоро"}</span>`}
          <label class="switch" aria-label="${esc(s.title)}"><input type="checkbox" data-id="${esc(s.id)}" ${data.settings.sources[s.id] ? "checked" : ""} ${s.available ? "" : "disabled"}><span></span></label>
        </div>
        ${s.checkable ? `<div class="src-check"><button class="btn small ghost" type="button" data-check="${esc(s.id)}">Проверить ключ</button><p class="src-result" role="status" hidden></p></div>` : ""}
      </li>`).join("");
  };
  loadSettings(true).then(draw).catch((e) => flash(e.message, "err"));
  ul.addEventListener("click", async (ev) => {
    const b = ev.target.closest("button[data-check]"); if (!b) return;
    const out = $(".src-result", b.parentElement);
    b.disabled = true; b.textContent = "Проверяю…"; out.hidden = true;
    try {
      const r = await api(`/api/sources/${b.dataset.check}/check`, { method: "POST" });
      out.textContent = r.message; out.className = "src-result " + (r.ok ? "ok" : "err");
    } catch (e) {
      out.textContent = "Проверка не прошла: " + e.message; out.className = "src-result err";
    }
    out.hidden = false; b.disabled = false; b.textContent = "Проверить ключ";
  });
  ul.addEventListener("change", async (ev) => {
    const input = ev.target.closest("input[data-id]"); if (!input) return;
    const next = { ...cache.settings.sources, [input.dataset.id]: input.checked };
    try {
      const r = await api("/api/settings", { method: "PUT", body: { sources: next } });
      cache = { ...cache, settings: r.settings };
      const name = title(cache.catalog.sources, input.dataset.id);
      if (!r.changed.length) flash("Ничего не изменилось.", "warn");
      else if (!Object.values(r.settings.sources).some(Boolean)) flash(`${name} выключена. Ни одна карта не включена — поиск не запустится.`, "warn");
      else flash(`${name}: ${input.checked ? "включена" : "выключена"}.`);
    } catch (e) {
      input.checked = !input.checked; // откат: показываем, что не сохранилось
      flash("Не сохранилось, переключатель вернулся назад: " + e.message, "err");
    }
  });
};

/* ===== настройки ===== */
PAGES.settings = () => {
  const seg = $("#theme");
  const mark = (t) => $$("button", seg).forEach((b) => { b.classList.toggle("on", b.dataset.theme === t); b.setAttribute("aria-pressed", String(b.dataset.theme === t)); });
  loadSettings().then((d) => mark(d.settings.theme)).catch((e) => flash(e.message, "err"));
  fetch("/api/health").then((r) => r.json()).then((h) => {
    $("#about").textContent = `Версия ${h.version}. База: ${h.db === "ok" ? "работает" : h.db}.`;
  }).catch(() => { $("#about").textContent = "Не удалось узнать состояние сервера."; });
  seg.addEventListener("click", async (ev) => {
    const b = ev.target.closest("button[data-theme]"); if (!b) return;
    const prev = document.documentElement.dataset.theme || "light";
    applyTheme(b.dataset.theme); mark(b.dataset.theme);
    try {
      const r = await api("/api/settings", { method: "PUT", body: { theme: b.dataset.theme } });
      cache = cache && { ...cache, settings: r.settings };
      if (r.changed.length) flash(`Оформление: ${b.textContent.trim().toLowerCase()}.`);
      else flash("Это оформление уже выбрано — ничего не изменилось.", "warn");
    } catch (e) {
      applyTheme(prev); mark(prev);
      flash("Оформление не сохранилось, вернул прежнее: " + e.message, "err");
    }
  });
  $("#logout").addEventListener("click", async () => {
    try { await api("/api/logout", { method: "POST" }); } catch (e) { /* выход всё равно: cookie удалится на /login */ }
    try { localStorage.removeItem("theme"); } catch (e) { /* не важно */ }
    location.assign("/login");
  });
};

/* ===== история поиска ===== */
PAGES.history = () => {
  let alive = true;
  const STATUS = { done: ["Готово", "ok"], error: ["Ошибка", "err"], cancelled: ["Отменён", "warn"],
                   running: ["Идёт", "run"], queued: ["Идёт", "run"] };
  (async () => {
    let r;
    try { r = await api("/api/jobs"); } catch (e) { $("#history").innerHTML = ""; flash("История не загрузилась: " + e.message, "err"); return; }
    if (!alive) return;
    $("#history-empty").hidden = r.jobs.length > 0;
    $("#history").innerHTML = r.jobs.map((j, i) => {
      const [label, kind] = STATUS[j.status] || [j.status, ""];
      const when = new Date(j.created_at).toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
      const result = j.status === "done" ? `Найдено на карте: ${j.found}, в выдаче: ${j.result_count}`
        : j.status === "error" ? j.error : j.status === "cancelled" ? "Отменён, в список ничего не добавлено" : "Поиск ещё идёт";
      const data = j.map_data_at ? ` · данные карты на ${new Date(j.map_data_at).toLocaleDateString("ru-RU")}` : "";
      const body = `
        <div class="hist-top"><b>№${j.id} · ${esc(when)}</b><span class="hist-status ${kind}">${esc(label)}</span></div>
        <p>${esc(j.niche_title)} · ${esc(j.city_title)}</p>
        <p class="muted">Искал: ${esc(j.categories_title.toLowerCase())} · сколько: ${j.amount}${esc(data)}</p>
        <p class="hist-result">${esc(result)}</p>`;
      const open = j.status === "done" && j.result_count > 0;
      return `<li class="hist" style="animation-delay:${Math.min(i, 20) * 40}ms">${open
        ? `<a class="hist-open" href="/search/${j.id}" data-link>${body}<span class="hist-go">Открыть итог →</span></a>`
        : body}</li>`;
    }).join("");
  })();
  return () => { alive = false; };
};

/* ===== главная: поиск и список ===== */
PAGES.list = () => {
  let alive = true;
  // /search/N — итог одного поиска: только его заведения, без панели поиска
  const resultMatch = location.pathname.match(/^\/search\/(\d+)$/);
  const resultJob = resultMatch ? Number(resultMatch[1]) : null;
  let pollTimer = 0;
  let places = [];
  let cats = ["site", "card", "upgrade", "manual"]; // что ищем (и показываем); берётся из настроек
  let showSkipped = false;
  let shownDots = 0;
  let currentJobId = null;

  const stageNames = ["search", "check", "score"];

  function drawChips(d) {
    const s = d.settings, c = d.catalog;
    const src = c.sources.filter((x) => s.sources[x.id]).map((x) => x.title).join(", ") || "ни одной";
    const vals = [s.niches.map((x) => title(c.niches, x)).join(", "), s.cities.map((x) => title(c.cities, x)).join(", "), String(s.amount), src];
    $$("#chips .chip").forEach((chip, i) => { chip.classList.remove("skel"); $("b", chip).textContent = vals[i]; });
    $("#search-btn").disabled = false;
  }

  function rowHtml(p, i) {
    const cats = cache.catalog.categories, st = cache.catalog.statuses;
    const badge = p.status === "new" ? "" : `<span class="badge ${p.status}">${esc(st[p.status])}</span>`;
    const stale = p.stale ? `<span class="badge stale" title="Запись на карте давно не обновлялась">${p.source_updated_at ? "карта " + p.source_updated_at.slice(0, 4) : "старая запись"}</span>` : "";
    const addr = [p.city_title, [p.street, p.housenumber].filter(Boolean).join(", ")].filter(Boolean).join(" · ");
    const contacts = [];
    if (p.category === "manual") contacts.push('<span class="muted">контакты — в карточке 2ГИС</span>');
    else if (p.phone) contacts.push(`<a href="tel:${esc(p.phone.replace(/[^\d+]/g, ""))}">${esc(p.phone)}</a>`);
    for (const l of p.links) contacts.push(`<a href="${esc(l.url)}" target="_blank" rel="noopener nofollow">${esc(l.label)}</a>`);
    return `<li class="row${p.status === "skipped" ? " is-skipped" : ""}" tabindex="0" data-id="${p.id}" style="animation-delay:${Math.min(i, 25) * 40}ms">
      <div class="row-name"><b>${esc(p.name)}${badge}${stale}</b>${addr ? `<small>${esc(addr)}</small>` : ""}
        <span class="row-contacts">${contacts.length ? contacts.join("") : '<span class="muted">контактов на карте нет</span>'}</span></div>
      <span class="cat">${esc(cats[p.category] || "")}</span>
      ${p.category === "manual"
        ? '<span class="score manual" title="Без оценки: контакты не известны">?</span>'
        : `<span class="score${p.score >= 60 ? " hi" : ""}" title="Оценка">${p.score}</span>`}</li>`;
  }

  function drawResultHead(job) {
    const when = new Date(job.created_at).toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
    const data = job.map_data_at ? ` · данные карты на ${new Date(job.map_data_at).toLocaleDateString("ru-RU")}` : "";
    $("#result-title").textContent = `Итог поиска №${job.id}`;
    $("#result-meta").textContent = `${when} · ${job.niche_title} · ${job.city_title} · искал: ${job.categories_title.toLowerCase()}${data}. Найдено на карте: ${job.found}, в выдаче: ${job.result_count}.`;
    $("#list-title").textContent = "Что выдал этот поиск";
  }

  function drawRows() {
    // в итоге поиска показываем всё, что он выдал, независимо от «Что ищу»
    const visible = places.filter((p) => (resultJob || cats.includes(p.category)) && (showSkipped || p.status !== "skipped"));
    $("#rows").innerHTML = visible.map(rowHtml).join("");
    const empty = $("#empty");
    if (!places.length) {
      empty.textContent = resultJob ? "Этот поиск ничего не выдал: новых подходящих заведений не нашлось." : "Пока пусто. Нажми «Найти клиентов».";
      empty.hidden = false;
    }
    else if (!visible.length) {
      const hiddenSkipped = places.filter((p) => p.status === "skipped" && cats.includes(p.category)).length;
      empty.textContent = hiddenSkipped ? `В выбранных категориях только пропущенные (${hiddenSkipped}). Включи «Показывать пропущенные».` : "В выбранных категориях пока никого нет. Нажми «Найти клиентов».";
      empty.hidden = false;
    } else empty.hidden = true;
  }

  async function loadPlaces() {
    try {
      if (resultJob) {
        const r = await api(`/api/jobs/${resultJob}/places`);
        if (!alive) return;
        places = r.places;
        drawResultHead(r.job);
        drawRows();
        return;
      }
      const r = await api("/api/places");
      if (!alive) return;
      places = r.places;
      $("#list-title").textContent = `${r.niche} · ${r.city}`;
      drawRows();
    } catch (e) {
      $("#rows").innerHTML = "";
      flash("Список не загрузился: " + e.message, "err");
    }
  }

  /* --- радар --- */
  function radarPoints(job) {
    const dots = $("#radar-dots");
    if (!job.points.length) return;
    const [lat0, lon0] = job.center || [
      job.points.reduce((a, p) => a + p[0], 0) / job.points.length,
      job.points.reduce((a, p) => a + p[1], 0) / job.points.length];
    const k = Math.cos(lat0 * Math.PI / 180);
    const xy = job.points.map(([lat, lon]) => [(lon - lon0) * k, lat - lat0]);
    const maxR = Math.max(1e-6, ...xy.map(([x, y]) => Math.hypot(x, y)));
    for (let i = shownDots; i < xy.length; i++) {
      const [x, y] = xy[i];
      const d = document.createElement("span");
      d.className = "dot";
      d.style.left = (50 + (x / maxR) * 44) + "%";
      d.style.top = (50 - (y / maxR) * 44) + "%";
      d.style.animationDelay = REDUCED ? "0ms" : Math.min(i - shownDots, 60) * 35 + "ms";
      dots.appendChild(d);
    }
    shownDots = xy.length;
  }

  function drawJob(job) {
    const running = job.status === "queued" || job.status === "running";
    // Радар виден, пока поиск идёт, и после завершения поиска, за которым следила эта страница.
    $("#job").hidden = !(running || (job.status === "done" && currentJobId === job.id));
    $("#radar").classList.toggle("done", !running);
    const idx = stageNames.indexOf(job.stage);
    $$("#stages li").forEach((li, i) => {
      li.classList.toggle("active", running && i === idx);
      li.classList.toggle("done", job.status === "done" || i < idx);
    });
    let count = job.found, label = "найдено на карте", sub = `${job.niche_title} · ${job.city_title} · ищу: ${job.categories_title.toLowerCase()}`;
    if (job.stage === "check") { count = job.checked; label = `из ${job.to_check} сайтов проверено`; sub += ` · найдено ${job.found}`; }
    if (job.stage === "score") { count = job.scored; label = `из ${job.found} оценено`; }
    if (job.status === "done") { count = job.result_count; label = "в списке"; }
    $("#job-count").textContent = count;
    $("#job-count-label").textContent = label;
    $("#job-sub").textContent = sub;
    radarPoints(job);
    $("#search-btn").disabled = running;
    $("#search-btn").textContent = running ? "Идёт поиск…" : "Найти клиентов";
    const cancelBtn = $("#cancel-btn");
    cancelBtn.hidden = !running;
    cancelBtn.disabled = !!job.cancel_requested;
    cancelBtn.textContent = job.cancel_requested ? "Останавливаю…" : "Отменить поиск";

    const errBox = $("#job-error");
    if (job.status === "error") {
      $("#job").hidden = true;
      $("#job-error-text").textContent = `Поиск №${job.id} (${job.niche_title}, ${job.city_title}) не завершён: ${job.error}`;
      errBox.hidden = false; errBox.dataset.job = job.id;
    } else errBox.hidden = true;
  }

  async function poll(jobId) {
    if (!alive) return;
    let job;
    try { job = (await api(`/api/jobs/${jobId}`)).job; }
    catch (e) {
      flash("Не удаётся узнать, как идёт поиск: " + e.message + " Пробую ещё раз…", "warn");
      pollTimer = setTimeout(() => poll(jobId), 4000); return;
    }
    if (!alive) return;
    drawJob(job);
    if (job.status === "queued" || job.status === "running") { pollTimer = setTimeout(() => poll(jobId), 1200); return; }
    currentJobId = null;
    if (job.status === "done") {
      const dataNote = job.map_data_at ? ` Данные карты на ${new Date(job.map_data_at).toLocaleDateString("ru-RU")}.` : "";
      const notice = [job.message + dataNote, job.result_count ? "ok" : "warn", true]; // итог не прячется сам
      $("#job-count-label").textContent = "в выдаче — готово";
      $("#job").classList.add("finished");
      await sleep(REDUCED ? 0 : 900);          // дать увидеть итоговое число
      if (!alive) return;
      const panel = $("#job");
      if (!REDUCED) {
        panel.style.height = panel.offsetHeight + "px";
        void panel.offsetHeight;
        panel.classList.add("collapsing");      // плавно сворачивается
        await sleep(320);
      }
      if (!alive) return;
      navigate(`/search/${job.id}`, { notice });
    } else if (job.status === "cancelled") {
      $("#job").hidden = true;
      flash(job.message || "Поиск отменён. В список ничего не добавлено.", "warn", true);
    }
  }

  async function startSearch() {
    clearFlash();
    $("#search-btn").disabled = true;
    shownDots = 0; $("#radar-dots").innerHTML = "";
    try {
      const r = await api("/api/search", { method: "POST" });
      currentJobId = r.job_id;
    } catch (e) {
      if (e.status === 409 && e.data && e.data.job_id) { currentJobId = e.data.job_id; flash(e.message, "warn"); }
      else { flash("Поиск не запустился: " + e.message, "err"); $("#search-btn").disabled = false; return; }
    }
    $("#job-error").hidden = true;
    $("#job").hidden = false;
    poll(currentJobId);
  }

  $("#search-btn").addEventListener("click", startSearch);
  $("#cancel-btn").addEventListener("click", async () => {
    const id = currentJobId; if (!id) return;
    const btn = $("#cancel-btn"); btn.disabled = true; btn.textContent = "Останавливаю…";
    try { await api(`/api/jobs/${id}/cancel`, { method: "POST" }); }
    catch (e) {
      // 409 — поиск успел закончиться сам; опрос покажет итог
      flash((e.status === 409 ? "" : "Отмена не сработала: ") + e.message, "warn");
      btn.disabled = false; btn.textContent = "Отменить поиск";
    }
  });
  $("#retry-btn").addEventListener("click", async () => {
    const id = $("#job-error").dataset.job;
    shownDots = 0; $("#radar-dots").innerHTML = "";
    try {
      const r = await api(`/api/jobs/${id}/retry`, { method: "POST" });
      currentJobId = r.job_id;
    } catch (e) {
      if (e.status === 409 && e.data && e.data.job_id) currentJobId = e.data.job_id;
      else { flash("Повтор не запустился: " + e.message, "err"); return; }
    }
    $("#job-error").hidden = true; $("#job").hidden = false;
    poll(currentJobId);
  });

  const ALL_CATS = ["site", "card", "upgrade", "manual"];
  function markCats() {
    for (const b of $$("#cat-filter button")) {
      const on = b.dataset.cat === "*" ? cats.length === ALL_CATS.length : cats.includes(b.dataset.cat);
      b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on));
    }
  }
  $("#cat-filter").addEventListener("click", async (ev) => {
    const b = ev.target.closest("button[data-cat]"); if (!b) return;
    const prev = cats;
    let next;
    if (b.dataset.cat === "*") next = [...ALL_CATS];
    else next = cats.includes(b.dataset.cat) ? cats.filter((x) => x !== b.dataset.cat) : [...cats, b.dataset.cat];
    if (!next.length) { flash("Нужна хотя бы одна категория — эту не выключаю.", "warn"); return; }
    if (next.length === prev.length && next.every((x) => prev.includes(x))) { flash("Уже выбраны все категории — ничего не изменилось.", "warn"); return; }
    cats = ALL_CATS.filter((x) => next.includes(x));
    markCats(); drawRows();
    try {
      const r = await api("/api/settings", { method: "PUT", body: { categories: cats } });
      cache = { ...cache, settings: r.settings };
      loadPlaces(); // сервер отдаёт заведения только выбранных категорий
      flash("Следующий поиск будет искать: " + cats.map((c) => cache.catalog.categories[c].toLowerCase()).join(", ") + ".");
    } catch (e) {
      cats = prev; markCats(); drawRows();
      flash("Фильтр не сохранился, вернул прежний: " + e.message, "err");
    }
  });
  $("#show-skipped").addEventListener("change", (ev) => { showSkipped = ev.target.checked; drawRows(); });

  /* --- карточка --- */
  let openId = null;
  let lastFocus = null;
  const layer = $("#card-layer");

  function closeCard() {
    layer.hidden = true; openId = null;
    if (lastFocus) lastFocus.focus();
  }

  function cardHtml(p) {
    const cats = cache.catalog.categories, st = cache.catalog.statuses;
    const addr = [p.street, p.housenumber].filter(Boolean).join(", ") || "улица не указана на карте";
    const contacts = [];
    for (const ph of p.phones) contacts.push(`<li>Телефон: <a href="tel:${esc(ph.replace(/[^\d+]/g, ""))}">${esc(ph)}</a></li>`);
    if (p.website) contacts.push(`<li>Сайт: <a href="${esc(p.website)}" target="_blank" rel="noopener nofollow">${esc(p.website)}</a></li>`);
    for (const c of p.channels) contacts.push(`<li>${esc(c.label)}: ${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener nofollow">${esc(c.value)}</a>` : esc(c.value)}</li>`);
    const parts = p.score_parts.map((x) => `<li><span>${esc(x.label)}</span><b>${x.points > 0 ? "+" : ""}${x.points}</b></li>`).join("");
    let site = "";
    if (p.website && p.site_check) {
      const s = p.site_check;
      site = s.opened
        ? `Открылся (код ${s.status_code}${s.final_url && s.final_url !== s.url ? `, переадресация на ${esc(s.final_url)}` : ""}). https: ${s.https ? "да" : "нет"}, мобильная версия: ${s.viewport ? "да" : "нет"}, год в подвале: ${s.footer_year || "не найден"}, текста на главной: ${s.text_len} симв., ссылок на другие страницы: ${s.internal_links}, битых из проверенных: ${s.broken_links} из ${s.tested_links}.`
        : `Сайт не открывается: ${esc(s.error)}${s.status_code ? ` (код ${s.status_code})` : ""}.`;
    }
    const manual = p.category === "manual";
    const fromOsm = p.contacts_from === "osm" ? '<p class="muted small">Контакты взяты из OpenStreetMap: 2ГИС их не отдаёт.</p>' : "";
    return `
      <h2 id="pc-name">${esc(p.name)}</h2>
      ${manual ? `<p><a class="btn full" href="${esc(p.object_url)}" target="_blank" rel="noopener">Открыть в 2ГИС: телефон и сайт</a></p>` : ""}
      <p class="muted">${esc(p.city_title)}, ${esc(addr)}</p>
      <p><b>${esc(cats[p.category] || "")}</b> · ${manual ? "без оценки" : `оценка <b>${p.score}</b> из 100`} · статус: <b id="pc-status">${esc(st[p.status])}</b></p>
      <section class="pc-sec"><h3>Что предложить</h3><p>${esc(p.offer)}</p></section>
      ${manual ? `<section class="pc-sec"><h3>Почему без оценки</h3><p>Оценку считают по сайту и контактам, а их карта не отдала. Посмотри в 2ГИС и реши сам.</p></section>`
        : `<section class="pc-sec"><h3>Из чего сложилась оценка</h3><ul class="parts">${parts}<li class="total"><span>Итого (от 0 до 100)</span><b>${p.score}</b></li></ul></section>`}
      ${site ? `<section class="pc-sec"><h3>Проверка сайта</h3><p>${site}</p></section>` : ""}
      <section class="pc-sec"><h3>Контакты</h3>${manual ? "<p class='muted'>2ГИС не отдал контакты, в OpenStreetMap этого заведения нет — смотри карточку в 2ГИС.</p>"
        : contacts.length ? `<ul class="contacts">${contacts.join("")}</ul>${fromOsm}` : "<p class='muted'>На карте контактов нет.</p>"}</section>
      <section class="pc-sec"><h3>На карте</h3><p>${p.source_updated_at
        ? `Запись обновлена или проверена: <b>${new Date(p.source_updated_at).toLocaleDateString("ru-RU")}</b>${p.stale ? " — давно, проверь по телефону, работает ли." : "."}`
        : "Дата обновления записи неизвестна — проверь по телефону, работает ли."}<br>
        <a href="${esc(p.object_url)}" target="_blank" rel="noopener">Открыть объект в ${esc(p.source_title)}</a><br><small class="muted">${esc(p.attribution)}</small></p></section>
      <div class="pc-actions">
        <button class="btn" type="button" data-status="work">1 — беру в работу</button>
        <button class="btn ghost" type="button" data-status="skipped">2 — пропускаю</button>
        <button class="btn ghost reset" type="button" data-status="new" ${p.status === "new" ? "hidden" : ""}>Вернуть в «новое»</button>
      </div>
      <p class="pc-status error" id="pc-error" role="alert" hidden></p>`;
  }

  async function openCard(id, rowEl) {
    lastFocus = rowEl;
    openId = id;
    $("#pc-body").innerHTML = '<div class="skel" style="height:28px;width:70%;border-radius:8px;margin-bottom:12px"></div><div class="skel" style="height:16px;width:50%;border-radius:6px;margin-bottom:24px"></div><div class="skel" style="height:120px;border-radius:12px"></div>';
    layer.hidden = false;
    $("#place-card").focus();
    try {
      const p = await api(`/api/places/${id}`);
      if (openId !== id) return;
      $("#pc-body").innerHTML = cardHtml(p);
    } catch (e) {
      $("#pc-body").innerHTML = `<p class="error">Карточка не открылась: ${esc(e.message)}</p>`;
    }
  }

  async function setStatus(status) {
    const id = openId; if (!id) return;
    const err = $("#pc-error"); if (err) err.hidden = true;
    const st = cache.catalog.statuses;
    try {
      const r = await api(`/api/places/${id}/status`, { method: "POST", body: { status } });
      const p = places.find((x) => x.id === id);
      if (!r.changed) { flash(`Статус уже «${st[status]}» — ничего не изменилось.`, "warn"); return; }
      if (p) p.status = status;
      flash(`«${p ? p.name : "Запись"}»: ${st[status].toLowerCase()}.`);
      closeCard();
      const row = $(`.row[data-id="${id}"]`);
      if (row && status === "skipped" && !showSkipped && !REDUCED) {
        row.classList.add("fade-out");
        await sleep(220);
      }
      drawRows();
    } catch (e) {
      if (err) { err.textContent = "Статус не сохранился: " + e.message; err.hidden = false; }
      else flash("Статус не сохранился: " + e.message, "err");
    }
  }

  $("#rows").addEventListener("click", (ev) => {
    if (ev.target.closest(".row-contacts a")) return; // звонок или соцсеть, а не карточка
    const row = ev.target.closest(".row[data-id]"); if (row) openCard(Number(row.dataset.id), row);
  });
  $("#rows").addEventListener("keydown", (ev) => {
    const row = ev.target.closest(".row[data-id]");
    if (row && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); openCard(Number(row.dataset.id), row); }
  });
  layer.addEventListener("click", (ev) => {
    if (ev.target.closest("[data-close]")) closeCard();
    const b = ev.target.closest("button[data-status]"); if (b) setStatus(b.dataset.status);
  });
  const onKey = (ev) => {
    if (layer.hidden) return;
    if (ev.key === "Escape") closeCard();
    else if (ev.key === "1") setStatus("work");
    else if (ev.key === "2") setStatus("skipped");
  };
  document.addEventListener("keydown", onKey);

  /* --- старт страницы --- */
  if (resultJob) {
    $("#result-head").hidden = false;
    $(".search-bar").hidden = true;
    $("#job").hidden = true;
    $("#job-error").hidden = true;
    (async () => {
      try { await loadSettings(true); } catch (e) { flash(e.message, "err"); return; }
      loadPlaces();
    })();
    return () => { alive = false; clearTimeout(pollTimer); document.removeEventListener("keydown", onKey); };
  }
  (async () => {
    try { const d = await loadSettings(true); drawChips(d); cats = [...d.settings.categories]; markCats(); }
    catch (e) { flash(e.message, "err"); return; }
    loadPlaces();
    try {
      const { job } = await api("/api/jobs/latest");
      if (!alive || !job) return;
      if (job.status === "queued" || job.status === "running") {
        currentJobId = job.id; $("#job").hidden = false; poll(job.id);
      } else if (job.status === "error") drawJob(job);
    } catch (e) { flash("Не удалось узнать состояние поиска: " + e.message, "warn"); }
  })();

  return () => { alive = false; clearTimeout(pollTimer); document.removeEventListener("keydown", onKey); };
};

initPage();
try {
  const n = sessionStorage.getItem("notice");
  if (n) { sessionStorage.removeItem("notice"); flash(...JSON.parse(n)); }
} catch (e) { /* хранилище недоступно — сообщение после полной перезагрузки не покажется */ }
