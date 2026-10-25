/* Batocera Portal front end. Vanilla JS, no build step. Author: Dan Lee. */
(() => {
'use strict';

// ------------------------------------------------------------ helpers ----
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtBytes = n => { n = Number(n||0); const u=['B','KB','MB','GB','TB']; let i=0; while(n>=1024&&i<u.length-1){n/=1024;i++;} return (i?n.toFixed(1):n)+' '+u[i]; };

async function api(path, opts = {}) {
  const init = { method: opts.method || 'GET', headers: {} };
  if (opts.json !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.json); }
  if (opts.form) init.body = opts.form;
  let res, data;
  try { res = await fetch(path, init); } catch (e) { throw new Error('Portal unreachable: ' + e.message); }
  try { data = await res.json(); } catch { throw new Error(`HTTP ${res.status} with a non-JSON reply`); }
  if (res.status === 401 && data.login) { location.replace('/login#' + (location.hash || '').replace('#', '')); throw new Error('Signed out'); }
  if (!res.ok || data.ok === false) {
    const err = new Error(data.error || `HTTP ${res.status}`);
    err.data = data; throw err;
  }
  return data;
}

function toast(msg, kind = '') {
  const el = document.createElement('div');
  el.className = 'toast ' + kind; el.textContent = msg;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), 4500);
}
const ok = m => toast(m, 'ok');
const err = e => toast(typeof e === 'string' ? e : (e.message || 'Error'), 'err');

function modal(title, bodyHtml) {
  $('#modal-title').textContent = title;
  $('#modal-body').innerHTML = bodyHtml;
  $('#modal').classList.remove('hidden');
  return $('#modal-body');
}
function closeModal() { $('#modal').classList.add('hidden'); }
$('#modal-close').onclick = closeModal;
$('#modal').addEventListener('click', e => { if (e.target.id === 'modal') closeModal(); });

function confirmBox(title, text, okLabel = 'Confirm', danger = true) {
  return new Promise(resolve => {
    const b = modal(title, `<p>${esc(text)}</p><div class="actions"><button class="btn ${danger?'btn-danger':'btn-primary'}" id="cf-ok">${esc(okLabel)}</button><button class="btn" id="cf-no">Cancel</button></div>`);
    $('#cf-ok', b).onclick = () => { closeModal(); resolve(true); };
    $('#cf-no', b).onclick = () => { closeModal(); resolve(false); };
  });
}

function setRing(id, pct) {
  const c = 326.7; const el = $('#' + id);
  if (!el) return;
  const p = Math.max(0, Math.min(100, Number(pct) || 0));
  el.style.strokeDashoffset = (c - c * p / 100).toFixed(1);
}
function bar(pct, label, right) {
  const p = Math.max(0, Math.min(100, Number(pct)||0));
  const cls = p > 90 ? 'danger' : p > 75 ? 'warn' : '';
  return `<div><div class="row"><span>${label}</span><span class="muted small">${right||''}</span></div><div class="bar ${cls}"><i style="width:${p}%"></i></div></div>`;
}

// ------------------------------------------------------------ navigation ----
const TITLES = { dashboard:'Dashboard', systems:'Custom systems', add:'Add / edit system', roms:'ROMs & BIOS', scraper:'Scraper', themes:'Themes & artwork', settings:'Settings' };
const loaders = {};
let currentPanel = 'dashboard';

function showPanel(name) {
  $$('.panel').forEach(p => p.classList.toggle('active', p.id === 'panel-' + name));
  $$('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.panel === name));
  $('#panel-title').textContent = TITLES[name] || name;
  $('#sidebar').classList.remove('open');
  currentPanel = name;
  if (loaders[name]) loaders[name]().catch(err);
  location.hash = name;
}
$$('.nav-item').forEach(b => b.onclick = () => showPanel(b.dataset.panel));
$('#menu-open').onclick = () => $('#sidebar').classList.add('open');
$('#menu-close').onclick = () => $('#sidebar').classList.remove('open');
$$('.tabs').forEach(tabs => {
  $$('.tab', tabs).forEach(t => t.onclick = () => {
    $$('.tab', tabs).forEach(x => x.classList.toggle('active', x === t));
    const parent = tabs.parentElement;
    $$('.tab-body', parent).forEach(b => b.classList.toggle('active', b.id === t.dataset.tab));
    if (t.dataset.tab === 'bios-tab') loadBios().catch(err);
    if (t.dataset.tab === 'scrape-batch') loadJobs().catch(err);
  });
});

// ------------------------------------------------------------ ES status ----
async function pollEs() {
  try {
    const d = await api('/api/es/status');
    const pill = $('#es-pill');
    pill.classList.toggle('on', d.running); pill.classList.toggle('off', !d.running);
    $('#es-pill-text').textContent = d.running ? `EmulationStation · PID ${d.pid}` : 'EmulationStation stopped';
    $('#es-restart-btn').classList.toggle('hidden', !d.restart_pending);
  } catch { /* quiet */ }
}
async function restartEs() {
  if (!await confirmBox('Restart EmulationStation', 'Any game running right now will be closed. Continue?', 'Restart')) return;
  try { await api('/api/es/restart', { method:'POST' }); ok('EmulationStation restarted'); pollEs(); } catch (e) { err(e); }
}
$('#es-restart-btn').onclick = restartEs;
$('#svc-es-restart').onclick = restartEs;
$('#logout-btn').onclick = async () => { try { await api('/api/logout', { method:'POST' }); } catch {} location.replace('/login'); };

// ------------------------------------------------------------ dashboard ----
let dashTimer = null;
async function loadDashboard() {
  const d = await api('/api/dashboard');
  $('#hero-host').textContent = d.hostname || 'Batocera';
  $('#hero-sub').textContent = `Batocera ${d.batocera_version} · up ${d.uptime_h} · ${d.ip}`;
  $('#host-line').textContent = `${d.hostname} · ${d.ip}`;
  setRing('ring-cpu', d.cpu.usage); $('#cpu-usage').textContent = `${d.cpu.usage}%`;
  $('#cpu-model').textContent = d.cpu.model; $('#cpu-cores').textContent = d.cpu.cores;
  $('#cpu-temp').textContent = d.cpu.temp != null ? `${d.cpu.temp}°C` : 'no temp sensor';
  const g = d.gpu;
  setRing('ring-gpu', g.usage ?? 0); $('#gpu-usage').textContent = g.usage != null ? `${g.usage}%` : 'n/a';
  $('#gpu-model').textContent = g.model || 'Not detected';
  $('#gpu-meta').textContent = [g.vram_total ? `VRAM ${fmtBytes(g.vram_used)} / ${fmtBytes(g.vram_total)}` : null, g.temp != null ? `${g.temp}°C` : null].filter(Boolean).join(' · ') || '—';
  setRing('ring-mem', d.memory.percent); $('#mem-usage').textContent = `${d.memory.percent}%`;
  $('#mem-detail').textContent = `${d.memory.used_h} of ${d.memory.total_h}`;
  $('#load-avg').textContent = (d.load || []).map(x => x.toFixed(2)).join(' / ');
  $('#disk-list').innerHTML = d.disks.map(x => bar(x.percent, `${x.label} <span class="muted small">${x.path}</span>`, `${x.used_h} / ${x.total_h} · ${x.free_h} free`)).join('') || '<div class="muted">No disks</div>';
  $('#fan-list').innerHTML = d.fans.length ? d.fans.map(f => `<div class="row"><span>${esc(f.label)} <span class="muted small">${esc(f.source)}</span></span><b>${f.rpm} rpm</b></div>`).join('') : '<div class="muted">No fan sensors found.</div>';
  $('#battery-line').textContent = d.battery.present ? `Battery ${d.battery.percent}% · ${d.battery.status}` : '';
  const es = d.es || {};
  $('#es-card').innerHTML = `<div class="row"><span>Status</span><span class="badge ${es.running?'ok':'danger'}">${es.running?'running':'stopped'}</span></div>
    <div class="row"><span>PID</span><b>${es.pid ?? '—'}</b></div>
    <div class="row"><span>Uptime</span><b>${es.uptime != null ? Math.floor(es.uptime/60)+' min' : '—'}</b></div>
    ${es.restart_pending ? '<div class="notice warn">Configuration changed. Restart EmulationStation to apply it.</div>' : ''}
    <div class="actions"><button class="btn btn-sm btn-warn" onclick="window.__restartEs()">Restart EmulationStation</button></div>`;
}
window.__restartEs = restartEs;

async function loadStats() {
  const s = await api('/api/stats');
  $('#kpi-plays').textContent = s.total_plays; $('#kpi-hours').textContent = s.total_hours;
  $('#top-played').innerHTML = s.top.length ? s.top.slice(0, 8).map((g, i) => `<div class="row"><span>${i+1}. ${esc(g.title)} <span class="muted small">${esc(g.system)}</span></span><span class="muted small">${g.gametime_h} · ${g.playcount}×</span></div>`).join('') : '<div class="muted">No play statistics yet.</div>';
  $('#last-played').textContent = s.last_played ? `Last played: ${s.last_played.title} (${s.last_played.system})` : '';
}
async function loadInfo() {
  const i = await api('/api/info');
  $('#kpi-systems').textContent = i.rom_systems; $('#kpi-custom').textContent = i.custom_systems;
  state.info = i;
}
async function loadRandom() {
  const d = await api('/api/random-game');
  const g = d.game;
  if (!g) { $('#random-game').innerHTML = '<div class="muted">No games with a gamelist.xml yet. Run the scraper first.</div>'; return; }
  $('#random-game').innerHTML = `${g.image ? `<img src="${esc(g.image)}&t=${Date.now()}" alt="">` : '<div class="random-noimg"></div>'}
    <div><div class="t">${esc(g.title)}</div><div class="muted small">${esc(g.system_name)} · ${esc(g.genre||'')} ${g.players?'· '+esc(g.players)+' players':''} ${g.releasedate?'· '+g.releasedate.slice(0,4):''}</div><div class="d">${esc(g.desc||'No description')}</div></div>`;
}
$('#random-again').onclick = () => loadRandom().catch(err);
async function loadRA() {
  const r = await api('/api/retroachievements');
  const c = $('#ra-card');
  if (!r.enabled) { c.innerHTML = '<div class="muted">Add your username and API key in Settings.</div>'; return; }
  if (r.error) { c.innerHTML = `<div class="muted">${esc(r.error)}</div>`; return; }
  c.innerHTML = `<div class="ra-head">${r.avatar?`<img src="${esc(r.avatar)}" alt="">`:''}<div><b>${esc(r.user)}</b><div class="muted small">${r.points} points · ${r.true_points} RetroPoints</div>${r.rich_presence?`<div class="small">${esc(r.rich_presence)}</div>`:''}</div></div>
    <div class="ra-list">${(r.recent||[]).slice(0,6).map(a => `<div>${a.badge?`<img src="${esc(a.badge)}" alt="">`:''}${esc(a.title)} <span class="muted">· ${esc(a.game)} · ${a.points} pts</span></div>`).join('') || '<div class="muted">No achievements in the last week.</div>'}</div>`;
}
async function loadNews() {
  const n = await api('/api/news');
  $('#news-list').innerHTML = n.items.length ? n.items.slice(0,6).map(i => `<div class="row"><a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.title)}</a><span class="muted small">${esc(i.date)}</span></div>`).join('') : '<div class="muted">Offline or no releases found.</div>';
}
loaders.dashboard = async () => {
  await Promise.allSettled([loadDashboard(), loadInfo(), loadStats(), loadRandom(), loadRA(), loadNews()]);
  clearInterval(dashTimer);
  if ($('#auto-refresh').checked) dashTimer = setInterval(() => { if (currentPanel === 'dashboard' && $('#auto-refresh').checked) loadDashboard().catch(()=>{}); }, 5000);
};
$('#auto-refresh').onchange = () => loaders.dashboard();

// ------------------------------------------------------------ systems ----
const state = { info: null, catalogue: null, custom: [], editing: null, romSystems: [], romFilter: 'all', romBrowser: null, scrapeResult: null };

async function loadCatalogue() {
  if (state.catalogue) return state.catalogue;
  const d = await api('/api/systems/catalogue');
  state.catalogue = d.systems;
  const sel = $('#f-reference');
  sel.innerHTML = '<option value="">— pick one to prefill the form —</option>' + Object.values(d.systems).sort((a,b)=>a.fullname.localeCompare(b.fullname)).map(s => `<option value="${esc(s.name)}">${esc(s.fullname)} (${esc(s.name)})</option>`).join('');
  return d.systems;
}
loaders.systems = async () => {
  const d = await api('/api/systems');
  state.custom = d.systems;
  const tb = $('#systems-table tbody');
  tb.innerHTML = d.systems.map(s => `<tr>
    <td><b>${esc(s.fullname)}</b><div class="muted small">${esc(s.manufacturer||'')} ${s.release?'· '+esc(s.release):''}</div></td>
    <td><code>${esc(s.name)}</code></td>
    <td class="small">${esc(s.path)} ${s.roms_dir_exists?'':'<span class="badge warn">missing folder</span>'}</td>
    <td class="small">${esc(s.extensions)}</td>
    <td class="small">${s.emulators.map(e => esc(e.name)+(e.default_core?' / '+esc(e.default_core):'')).join('<br>')}</td>
    <td><button class="btn btn-sm" data-act="edit" data-slug="${esc(s.name)}">Edit</button> <button class="btn btn-sm" data-act="xml" data-slug="${esc(s.name)}">XML</button> <button class="btn btn-sm btn-danger" data-act="del" data-slug="${esc(s.name)}">Delete</button></td></tr>`).join('');
  $('#systems-empty').classList.toggle('hidden', d.systems.length > 0);
  $$('button[data-act]', tb).forEach(b => b.onclick = () => systemAction(b.dataset.act, b.dataset.slug));
};
$('#systems-refresh').onclick = () => loaders.systems().catch(err);
$('#systems-new').onclick = () => { resetForm(); showPanel('add'); };

async function systemAction(act, slug) {
  if (act === 'xml') {
    const d = await api('/api/systems/' + encodeURIComponent(slug));
    modal(`es_systems_${slug}.cfg`, `<pre class="xml">${esc(d.system.xml)}</pre>`);
  } else if (act === 'edit') {
    const d = await api('/api/systems/' + encodeURIComponent(slug));
    fillForm(d.system, slug); showPanel('add');
  } else if (act === 'del') {
    if (!await confirmBox('Delete system', `Delete the configuration for "${slug}"? ROM files are kept. Emulator lines for it are removed from batocera.conf.`, 'Delete')) return;
    try { const r = await api('/api/systems/' + encodeURIComponent(slug), { method:'DELETE' }); ok(r.log.join(' ')); loaders.systems(); pollEs(); } catch (e) { err(e); }
  }
}

// ------------------------------------------------------------ add/edit form ----
const F = id => $('#f-' + id);
function resetForm() {
  state.editing = null;
  $('#system-form').reset();
  $('#form-title').textContent = 'New system'; $('#form-editing').classList.add('hidden');
  $('#f-log').classList.add('hidden'); $('#f-xml').classList.add('hidden');
}
function fillForm(s, slug) {
  resetForm();
  state.editing = slug;
  $('#form-title').textContent = 'Edit system'; $('#form-editing').textContent = slug; $('#form-editing').classList.remove('hidden');
  F('fullname').value = s.fullname||''; F('name').value = s.name||''; F('manufacturer').value = s.manufacturer||'';
  F('release').value = s.release||''; F('hardware').value = s.hardware||''; F('theme').value = s.theme||'';
  F('rompath').value = s.path||''; F('extensions').value = s.extensions||''; F('platform').value = s.platform||'';
  F('command').value = s.command && !/emulatorlauncher/.test(s.command) ? s.command : '';
  F('description').value = s.description||'';
  const emu = (s.emulators||[])[0];
  F('emulator').value = emu ? emu.name : ''; F('core').value = emu ? emu.default_core : '';
  F('extra-cores').value = emu ? emu.cores.filter(c => c !== emu.default_core).join(', ') : '';
  F('create-roms').checked = true; F('conf-entry').checked = false;
}
function formPayload() {
  return {
    fullname: F('fullname').value.trim(), name: F('name').value.trim(), manufacturer: F('manufacturer').value.trim(),
    release: F('release').value.trim(), hardware: F('hardware').value, theme: F('theme').value.trim(),
    rompath: F('rompath').value.trim(), extensions: F('extensions').value.trim(), platform: F('platform').value.trim(),
    emulator: F('emulator').value.trim(), core: F('core').value.trim(), extra_cores: F('extra-cores').value.trim(),
    command: F('command').value.trim(), description: F('description').value.trim(),
    create_roms_dir: F('create-roms').checked, batocera_conf_entry: F('conf-entry').checked,
  };
}
$('#f-reference').onchange = async e => {
  const s = (await loadCatalogue())[e.target.value]; if (!s) return;
  F('extensions').value = s.extensions; F('platform').value = s.platform || s.name; F('theme').value = s.theme || s.name;
  F('manufacturer').value = s.manufacturer || ''; F('release').value = s.release || ''; F('hardware').value = s.hardware || '';
  const emu = (s.emulators||[])[0];
  if (emu) { F('emulator').value = emu.name; F('core').value = emu.default_core || emu.cores[0] || ''; F('extra-cores').value = emu.cores.filter(c => c !== (emu.default_core||emu.cores[0])).join(', '); }
  if (!F('fullname').value) F('fullname').value = s.fullname + ' (custom)';
  if (!F('name').value) F('name').value = s.name + '-custom';
  if (!F('rompath').value) F('rompath').value = romsBase() + '/' + F('name').value;
};
const romsBase = () => ((state.info && state.info.roms_base) || '/userdata/roms').replace(/\/$/, '');
F('name').oninput = () => { if (!state.editing && (!F('rompath').value || F('rompath').value.startsWith(romsBase() + '/'))) F('rompath').value = romsBase() + '/' + F('name').value; };
$('#f-ext-preset').onchange = e => { if (e.target.value) F('extensions').value = e.target.value; e.target.value = ''; };
function showLog(lines, xml) {
  const l = $('#f-log'); l.textContent = (lines||[]).join('\n'); l.classList.toggle('hidden', !lines || !lines.length);
  const x = $('#f-xml'); if (xml) { x.textContent = xml; x.classList.remove('hidden'); }
}
$('#f-preview').onclick = async () => {
  try { const r = await api('/api/systems/preview', { method:'POST', json: formPayload() }); showLog(r.errors.length ? r.errors.map(e=>'⚠ '+e) : ['Preview only. Nothing was written.'], r.xml); } catch (e) { err(e); }
};
async function submitSystem(dry) {
  const payload = { ...formPayload(), dry_run: dry };
  try {
    const r = state.editing ? await api('/api/systems/' + encodeURIComponent(state.editing), { method:'PUT', json: payload })
                            : await api('/api/systems', { method:'POST', json: payload });
    showLog(r.log, r.xml);
    if (!dry) { ok('System saved'); state.editing = payload.name; $('#form-editing').textContent = payload.name; $('#form-editing').classList.remove('hidden'); $('#form-title').textContent = 'Edit system'; pollEs(); }
  } catch (e) { showLog((e.data && e.data.errors) || [e.message]); err(e); }
}
$('#f-dryrun').onclick = () => submitSystem(true);
$('#system-form').onsubmit = e => { e.preventDefault(); submitSystem(false); };
$('#f-cancel').onclick = () => { resetForm(); showPanel('systems'); };
loaders.add = async () => {
  await loadCatalogue();
  if (!$('#f-hardware').options.length && state.info) {
    $('#f-hardware').innerHTML = '<option value="">—</option>' + state.info.hardware_types.map(h => `<option>${h}</option>`).join('');
    $('#f-ext-preset').innerHTML = '<option value="">Presets…</option>' + Object.entries(state.info.ext_presets).map(([k,v]) => `<option value="${esc(v)}">${esc(k)}</option>`).join('');
  }
};

// ------------------------------------------------------------ ROMs ----
const HW_LABEL = { console:'Consoles', portable:'Handhelds', computer:'Computers', arcade:'Arcade', engine:'Engines', fantasy:'Fantasy', other:'Other' };
loaders.roms = async (force) => {
  const d = await api('/api/roms' + (force ? '?force=1' : ''));
  state.romSystems = d.systems; renderRoms();
  fillScraperSystems();
};
$('#roms-refresh').onclick = () => loaders.roms(true).catch(err);
$('#roms-search').oninput = renderRoms;
function renderRoms() {
  const q = $('#roms-search').value.toLowerCase();
  const types = {}; state.romSystems.forEach(s => types[s.hardware] = (types[s.hardware]||0)+1);
  $('#roms-chips').innerHTML = [`<span class="chip ${state.romFilter==='all'?'on':''}" data-f="all">All (${state.romSystems.length})</span>`].concat(Object.keys(types).sort().map(t => `<span class="chip ${state.romFilter===t?'on':''}" data-f="${t}">${HW_LABEL[t]||t} (${types[t]})</span>`)).join('');
  $$('#roms-chips .chip').forEach(c => c.onclick = () => { state.romFilter = c.dataset.f; renderRoms(); });
  const list = state.romSystems.filter(s => (state.romFilter==='all' || s.hardware===state.romFilter) && (!q || s.slug.includes(q) || s.fullname.toLowerCase().includes(q) || (s.manufacturer||'').toLowerCase().includes(q)));
  $('#roms-grid').innerHTML = list.map(s => `<div class="sys-card ${s.known?'':'unknown'}" data-slug="${esc(s.slug)}"><div class="t">${esc(s.fullname)}</div><div class="m">${esc(s.slug)} ${s.manufacturer?'· '+esc(s.manufacturer):''} ${s.custom?'· <span class="badge">custom</span>':''}${s.known?'':'· <span class="badge warn">unknown system</span>'}</div><div class="n">${s.rom_count} <span class="muted small">ROMs · ${s.size_h}</span></div><div class="m">${s.gamelist_entries} in gamelist · ${s.extensions.join(' ')||'—'}</div></div>`).join('') || '<div class="muted">No ROM folders match.</div>';
  $$('#roms-grid .sys-card').forEach(c => c.onclick = () => openRomBrowser(c.dataset.slug, ''));
}
async function openRomBrowser(slug, sub) {
  const d = await api(`/api/roms/${encodeURIComponent(slug)}?path=${encodeURIComponent(sub)}`);
  state.romBrowser = { slug, sub };
  $('#rom-browser').classList.remove('hidden');
  $('#rom-browser-title').textContent = `${d.fullname} (${slug})`;
  $('#rom-browser-path').textContent = '/' + (sub || '');
  $('#rom-files tbody').innerHTML = d.entries.map(e => e.is_dir
    ? `<tr><td colspan="5"><a href="#" data-dir="${esc(e.rel)}">📁 ${esc(e.name)}</a></td><td></td></tr>`
    : `<tr><td class="ellipsis" style="max-width:260px" title="${esc(e.name)}">${esc(e.name)}</td><td>${esc(e.title||'')} ${e.favorite?'★':''}</td><td class="small">${e.size_h}</td><td class="small">${e.playcount||''}</td><td>${e.has_image?'<span class="badge ok">art</span>':'<span class="badge">none</span>'}</td>
       <td><button class="btn btn-sm" data-act="meta" data-rel="${esc(e.rel)}">Edit</button> <button class="btn btn-sm" data-act="media" data-rel="${esc(e.rel)}">Media</button> <button class="btn btn-sm" data-act="rename" data-rel="${esc(e.rel)}">Rename</button> <button class="btn btn-sm" data-act="scrape" data-rel="${esc(e.rel)}">Scrape</button></td></tr>`).join('') || '<tr><td colspan="6" class="muted">Empty folder.</td></tr>';
  $$('#rom-files a[data-dir]').forEach(a => a.onclick = ev => { ev.preventDefault(); openRomBrowser(slug, a.dataset.dir); });
  $$('#rom-files button[data-act]').forEach(b => b.onclick = () => romAction(b.dataset.act, slug, b.dataset.rel, d.entries.find(x => x.rel === b.dataset.rel)));
  $('#rom-browser').scrollIntoView({ behavior:'smooth', block:'start' });
}
$('#rom-browser-close').onclick = () => $('#rom-browser').classList.add('hidden');
$('#rom-browser-up').onclick = () => { const b = state.romBrowser; if (!b) return; const parts = b.sub.split('/').filter(Boolean); parts.pop(); openRomBrowser(b.slug, parts.join('/')); };

async function romAction(act, slug, rel, entry) {
  if (act === 'rename') {
    const b = modal('Rename ROM', `<div class="form-grid"><label class="span2">New file name <input id="rn-name" value="${esc(entry.name)}"></label></div><div class="actions"><button class="btn btn-primary" id="rn-ok">Rename</button></div>`);
    $('#rn-ok', b).onclick = async () => { try { await api(`/api/roms/${encodeURIComponent(slug)}/rename`, { method:'POST', json:{ rom: rel, new_name: $('#rn-name', b).value.trim() } }); closeModal(); ok('Renamed'); openRomBrowser(slug, state.romBrowser.sub); } catch (e) { err(e); } };
  } else if (act === 'meta') {
    const fields = ['name','desc','genre','developer','publisher','players','rating','releasedate'];
    const b = modal(`Edit metadata · ${entry.name}`, `<div class="form-grid">${fields.map(f => f==='desc' ? `<label class="span2">${f}<textarea id="m-${f}" rows="4">${esc(entry[f==='name'?'title':f]||'')}</textarea></label>` : `<label>${f}<input id="m-${f}" value="${esc(entry[f==='name'?'title':f]||'')}"></label>`).join('')}
      <label class="check"><input type="checkbox" id="m-favorite" ${entry.favorite?'checked':''}> Favourite</label><label class="check"><input type="checkbox" id="m-hidden" ${entry.hidden?'checked':''}> Hidden</label></div>
      <div class="actions"><button class="btn btn-primary" id="m-ok">Save</button></div>`);
    $('#m-ok', b).onclick = async () => {
      const meta = {}; fields.forEach(f => meta[f] = $('#m-'+f, b).value); meta.favorite = $('#m-favorite', b).checked ? 'true' : ''; meta.hidden = $('#m-hidden', b).checked ? 'true' : '';
      try { await api(`/api/roms/${encodeURIComponent(slug)}/meta`, { method:'POST', json:{ rom: rel, meta } }); closeModal(); ok('gamelist.xml updated'); openRomBrowser(slug, state.romBrowser.sub); } catch (e) { err(e); }
    };
  } else if (act === 'media') {
    const d = await api(`/api/roms/${encodeURIComponent(slug)}/media?rom=${encodeURIComponent(rel)}`);
    const b = modal(`Media · ${entry.name}`, `<div class="sc-media">${d.media.map(m => `<figure><img src="/api/roms/${encodeURIComponent(slug)}/file?path=${encodeURIComponent(m.rel)}" alt=""><figcaption>${m.type} · ${m.size_h} <button class="btn btn-sm btn-danger" data-del="${esc(m.rel)}">✕</button></figcaption></figure>`).join('') || '<div class="muted">No media yet.</div>'}</div>
      <h3 style="margin-top:16px">Upload</h3><form id="mu-form" class="form-grid"><label>Type <select id="mu-type">${['image','box','box3d','marquee','wheel','fanart','titleshot','thumbnail','video','manual'].map(t=>`<option>${t}</option>`).join('')}</select></label><label>File <input type="file" id="mu-file" required></label><div class="actions"><button class="btn btn-primary">Upload</button></div></form>`);
    $$('button[data-del]', b).forEach(x => x.onclick = async () => { if (!await confirmBox('Delete media', `Delete ${x.dataset.del}?`, 'Delete')) return; try { await api(`/api/roms/${encodeURIComponent(slug)}/media?path=${encodeURIComponent(x.dataset.del)}`, { method:'DELETE' }); ok('Deleted'); romAction('media', slug, rel, entry); } catch (e) { err(e); } });
    $('#mu-form', b).onsubmit = async ev => { ev.preventDefault(); const fd = new FormData(); fd.append('rom', rel); fd.append('type', $('#mu-type', b).value); fd.append('file', $('#mu-file', b).files[0]); try { await api(`/api/roms/${encodeURIComponent(slug)}/media`, { method:'POST', form: fd }); ok('Uploaded'); romAction('media', slug, rel, entry); } catch (e) { err(e); } };
  } else if (act === 'scrape') {
    showPanel('scraper');
    await fillScraperSystems();
    $('#sc-system').value = slug; await fillScraperRoms(); $('#sc-rom').value = rel;
  }
}

// ------------------------------------------------------------ BIOS ----
async function loadBios() {
  const only = $('#bios-installed-only').checked;
  const d = await api(only ? '/api/bios/missing' : '/api/bios');
  $('#bios-source').textContent = `BIOS list source: ${d.source}`;
  const s = d.summary;
  $('#bios-summary').innerHTML = `<div class="kpi"><div class="kpi-val">${s.systems}</div><div class="kpi-lbl">systems checked</div></div><div class="kpi"><div class="kpi-val">${s.complete}</div><div class="kpi-lbl">complete</div></div><div class="kpi"><div class="kpi-val" style="color:var(--danger)">${s.missing_files}</div><div class="kpi-lbl">missing files</div></div><div class="kpi"><div class="kpi-val" style="color:var(--warn)">${s.mismatched_files}</div><div class="kpi-lbl">bad checksum</div></div>`;
  $('#bios-list').innerHTML = d.systems.map(sys => `<details class="bios-sys" ${sys.complete?'':'open'}><summary><span><b>${esc(sys.name)}</b> <span class="muted small">${esc(sys.slug)}</span></span><span>${sys.complete?'<span class="badge ok">complete</span>':`<span class="badge danger">${sys.missing} missing</span> ${sys.mismatch?`<span class="badge warn">${sys.mismatch} bad</span>`:''}`}</span></summary>
    ${sys.files.map(f => `<div class="bios-file"><span><code>${esc(f.file)}</code> ${f.optional?'<span class="muted small">optional</span>':''}</span><span class="st ${f.skipped?'skipped':f.status}">${f.skipped?'skipped':f.status}</span><span>
      ${f.status!=='ok' ? `<button class="btn btn-sm" data-up="${esc(f.file)}">Upload</button> <button class="btn btn-sm" data-dl="${esc(f.file)}">From URL</button> <button class="btn btn-sm" data-skip="${esc(f.key)}" data-skipped="${f.skipped?1:0}">${f.skipped?'Unskip':'Skip'}</button>` : ''}</span></div>`).join('')}</details>`).join('') || '<div class="muted">Everything is in place. 🎉</div>';
  $$('#bios-list [data-up]').forEach(b => b.onclick = () => biosUpload(b.dataset.up));
  $$('#bios-list [data-dl]').forEach(b => b.onclick = () => biosDownload(b.dataset.dl));
  $$('#bios-list [data-skip]').forEach(b => b.onclick = async () => { try { await api('/api/bios/skip', { method:'POST', json:{ key: b.dataset.skip, skipped: b.dataset.skipped !== '1' } }); loadBios(); } catch (e) { err(e); } });
}
$('#bios-refresh').onclick = () => loadBios().catch(err);
$('#bios-installed-only').onchange = () => loadBios().catch(err);
function biosUpload(file) {
  const b = modal(`Upload ${file}`, `<form id="bu-form"><input type="file" id="bu-file" required><div class="actions"><button class="btn btn-primary">Upload</button></div></form>`);
  $('#bu-form', b).onsubmit = async ev => { ev.preventDefault(); const fd = new FormData(); fd.append('file', file); fd.append('data', $('#bu-file', b).files[0]); try { const r = await api('/api/bios/upload', { method:'POST', form: fd }); closeModal(); r.verified === false ? toast('Saved, but the MD5 does not match the expected one', 'err') : ok('BIOS saved'); loadBios(); } catch (e) { err(e); } };
}
function biosDownload(file) {
  const b = modal(`Download ${file}`, `<div class="form-grid"><label class="span2">URL <input id="bd-url" placeholder="https://…"><span class="hint">The file is verified against the expected MD5 and discarded if it does not match.</span></label></div><div class="actions"><button class="btn btn-primary" id="bd-ok">Download</button></div>`);
  $('#bd-ok', b).onclick = async () => { try { await api('/api/bios/download', { method:'POST', json:{ file, url: $('#bd-url', b).value.trim() } }); closeModal(); ok('BIOS downloaded and verified'); loadBios(); } catch (e) { err(e); } };
}

// ------------------------------------------------------------ scraper ----
const MEDIA_TYPES = ['image','box','box3d','marquee','wheel','fanart','titleshot','mix','video','manual'];
const DEFAULT_TYPES = ['image','box','marquee'];
async function fillScraperSystems() {
  if (!state.romSystems.length) { const d = await api('/api/roms'); state.romSystems = d.systems; }
  const opts = state.romSystems.filter(s => s.rom_count > 0).map(s => `<option value="${esc(s.slug)}">${esc(s.fullname)} (${s.rom_count})</option>`).join('');
  if ($('#sc-system').innerHTML !== opts) { $('#sc-system').innerHTML = opts; await fillScraperRoms(); }
  $('#batch-systems').innerHTML = state.romSystems.filter(s => s.rom_count > 0).map(s => `<span class="chip" data-slug="${esc(s.slug)}">${esc(s.fullname)} (${s.rom_count})</span>`).join('');
  $$('#batch-systems .chip').forEach(c => c.onclick = () => c.classList.toggle('on'));
  if (!$('#batch-types').children.length) { $('#batch-types').innerHTML = MEDIA_TYPES.map(t => `<span class="chip ${DEFAULT_TYPES.includes(t)?'on':''}" data-t="${t}">${t}</span>`).join(''); $$('#batch-types .chip').forEach(c => c.onclick = () => c.classList.toggle('on')); }
}
async function fillScraperRoms() {
  const slug = $('#sc-system').value; if (!slug) return;
  const d = await api(`/api/roms/${encodeURIComponent(slug)}`);
  const files = d.entries.filter(e => !e.is_dir);
  $('#sc-rom').innerHTML = files.map(e => `<option value="${esc(e.rel)}">${esc(e.name)}${e.has_image?' ✓':''}</option>`).join('') || '<option value="">(no ROMs in root folder)</option>';
}
$('#sc-system').onchange = () => fillScraperRoms().catch(err);
loaders.scraper = async () => {
  await fillScraperSystems();
  const d = await api('/api/scraper/config'); const c = d.config;
  $('#cfg-ss-user').value = c.ss_user; $('#cfg-ss-pass').value = c.ss_pass; $('#cfg-ss-devid').value = c.ss_devid; $('#cfg-ss-devpass').value = c.ss_devpassword;
  $('#cfg-tgdb').value = c.tgdb_key; $('#cfg-source').value = c.default_source; $('#cfg-region').value = c.region; $('#cfg-lang').value = c.language;
  $('#sc-source').value = c.default_source; $('#batch-source').value = c.default_source;
  if (!c.has_ss_creds && !c.has_tgdb_key) toast('No scraper credentials yet. Fill in the Credentials tab first.');
};
$('#scraper-config-form').onsubmit = async e => {
  e.preventDefault();
  try { await api('/api/scraper/config', { method:'POST', json:{ ss_user: $('#cfg-ss-user').value, ss_pass: $('#cfg-ss-pass').value, ss_devid: $('#cfg-ss-devid').value, ss_devpassword: $('#cfg-ss-devpass').value, tgdb_key: $('#cfg-tgdb').value, default_source: $('#cfg-source').value, region: $('#cfg-region').value, language: $('#cfg-lang').value } }); ok('Credentials saved to batocera.conf'); loaders.scraper(); } catch (e2) { err(e2); }
};
$('#sc-search').onclick = async () => {
  const btn = $('#sc-search'); btn.disabled = true; btn.textContent = 'Searching…';
  try {
    const d = await api('/api/scraper/search', { method:'POST', json:{ system: $('#sc-system').value, rom: $('#sc-rom').value, source: $('#sc-source').value } });
    state.scrapeResult = d.result; const r = d.result;
    $('#sc-result').classList.remove('hidden');
    $('#sc-name').textContent = r.name || '(no title)'; $('#sc-desc').textContent = r.desc || '';
    $('#sc-fields').innerHTML = [['Source', r.source],['Genre', r.genre],['Developer', r.developer],['Publisher', r.publisher],['Players', r.players],['Rating', r.rating],['Released', r.releasedate && r.releasedate.slice(0,8)], d.quota ? ['Quota', `${d.quota.requests_today||'?'} / ${d.quota.max_per_day||'?'} today`] : null].filter(x => x && x[1]).map(([k,v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('');
    const media = Object.entries(r.media || {});
    $('#sc-media').innerHTML = media.map(([t, m]) => `<figure>${/video|manual/.test(t) ? `<div style="height:120px;display:flex;align-items:center;justify-content:center" class="muted">${t}</div>` : `<img src="${esc(m.url)}" alt="" loading="lazy">`}<figcaption>${t} (${esc(m.format||'')})</figcaption></figure>`).join('') || '<div class="muted">No media offered.</div>';
    $('#sc-types').innerHTML = media.map(([t]) => `<span class="chip ${DEFAULT_TYPES.includes(t)?'on':''}" data-t="${t}">${t}</span>`).join('');
    $$('#sc-types .chip').forEach(c => c.onclick = () => c.classList.toggle('on'));
    $('#sc-log').classList.add('hidden');
  } catch (e) { err(e); }
  btn.disabled = false; btn.textContent = 'Search';
};
$('#sc-apply').onclick = async () => {
  const types = $$('#sc-types .chip.on').map(c => c.dataset.t);
  try {
    const r = await api('/api/scraper/apply', { method:'POST', json:{ system: $('#sc-system').value, rom: $('#sc-rom').value, result: state.scrapeResult, types, overwrite: $('#sc-overwrite').checked, write_meta: $('#sc-meta-write').checked } });
    const l = $('#sc-log'); l.classList.remove('hidden');
    l.textContent = [...Object.entries(r.saved).map(([t,p]) => `✔ ${t}: ${p}`), ...Object.entries(r.errors).map(([t,e]) => `✖ ${t}: ${e}`), r.meta.length ? `✔ gamelist.xml: ${r.meta.join(', ')}` : ''].filter(Boolean).join('\n');
    ok('Saved'); pollEs();
  } catch (e) { err(e); }
};
$('#batch-start').onclick = async () => {
  const systems = $$('#batch-systems .chip.on').map(c => c.dataset.slug);
  const types = $$('#batch-types .chip.on').map(c => c.dataset.t);
  if (!systems.length) return err('Pick at least one system');
  try { await api('/api/scraper/jobs', { method:'POST', json:{ systems, types, source: $('#batch-source').value, overwrite: $('#batch-overwrite').checked, skip_existing: $('#batch-skip').checked } }); ok('Batch started'); loadJobs(); } catch (e) { err(e); }
};
let jobTimer = null;
async function loadJobs() {
  const d = await api('/api/scraper/jobs');
  $('#batch-jobs').innerHTML = d.jobs.slice().reverse().map(j => `<div class="job"><div class="row"><b>${esc(j.systems.join(', '))}</b><span class="badge ${j.status==='completed'?'ok':j.status==='failed'?'danger':''}">${j.status}</span></div>
    <div class="bar"><i style="width:${j.progress}%"></i></div>
    <div class="row small muted"><span>${j.done}/${j.total} · ok ${j.ok} · failed ${j.fail} · skipped ${j.skip}</span><span>${j.current_rom ? esc(j.current_system + '/' + j.current_rom) : ''}</span></div>
    ${j.errors.length ? `<details><summary class="small">${j.errors.length} error(s)</summary><pre class="log">${esc(j.errors.slice(-50).join('\n'))}</pre></details>` : ''}
    ${['pending','running'].includes(j.status) ? `<div class="actions"><button class="btn btn-sm btn-danger" data-cancel="${j.id}">Cancel</button></div>` : ''}</div>`).join('') || '<div class="muted">No jobs yet.</div>';
  $$('#batch-jobs [data-cancel]').forEach(b => b.onclick = () => api('/api/scraper/jobs/' + b.dataset.cancel, { method:'DELETE' }).then(loadJobs).catch(err));
  clearInterval(jobTimer);
  if (d.jobs.some(j => ['pending','running'].includes(j.status))) jobTimer = setInterval(() => { if (currentPanel === 'scraper') loadJobs().catch(()=>{}); else clearInterval(jobTimer); }, 2000);
}

// ------------------------------------------------------------ themes ----
loaders.themes = async () => {
  const [t, s] = await Promise.all([api('/api/themes'), api('/api/systems')]);
  $('#theme-active').textContent = t.active;
  $('#theme-list').innerHTML = t.themes.map(x => `<div class="row"><span><b>${esc(x.name)}</b> <span class="muted small">${x.origin}</span></span>${x.name===t.active?'<span class="badge ok">active</span>':''}</div>`).join('') || '<div class="muted">No themes found.</div>';
  $('#logo-theme').innerHTML = t.themes.filter(x => x.origin === 'user').map(x => `<option ${x.name===t.active?'selected':''}>${esc(x.name)}</option>`).join('') || '<option value="">(no user themes: copy one to /userdata/themes first)</option>';
  const slugs = [...new Set([...s.systems.map(x => x.name), ...state.romSystems.map(x => x.slug)])].sort();
  $('#logo-system').innerHTML = slugs.map(x => `<option>${esc(x)}</option>`).join('');
  showLogoPreview();
};
function showLogoPreview() {
  const slug = $('#logo-system').value, theme = $('#logo-theme').value;
  $('#logo-preview').innerHTML = slug ? `<img src="/api/themes/logo/${encodeURIComponent(slug)}?theme=${encodeURIComponent(theme)}&t=${Date.now()}" alt="no logo yet" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'muted',textContent:'No logo found for this system in that theme.'}))">` : '';
}
$('#logo-system').onchange = showLogoPreview; $('#logo-theme').onchange = showLogoPreview;
$('#logo-form').onsubmit = async e => {
  e.preventDefault(); const f = $('#logo-file').files[0]; if (!f) return err('Choose a file first');
  const fd = new FormData(); fd.append('system', $('#logo-system').value); fd.append('theme', $('#logo-theme').value); fd.append('file', f);
  try { const r = await api('/api/themes/logo', { method:'POST', form: fd }); ok('Saved to ' + r.path); showLogoPreview(); } catch (e2) { err(e2); }
};
$('#logo-placeholder').onclick = async () => {
  const fd = new FormData(); fd.append('system', $('#logo-system').value); fd.append('theme', $('#logo-theme').value); fd.append('placeholder', '1'); fd.append('label', $('#logo-system').value);
  try { const r = await api('/api/themes/logo', { method:'POST', form: fd }); ok('Placeholder saved to ' + r.path); showLogoPreview(); } catch (e2) { err(e2); }
};

// ------------------------------------------------------------ settings ----
const SETTING_KEYS = ['es_cfg_dir','roms_base','bios_dir','themes_user','themes_sys','batocera_conf','custom_sh','configgen_path','server_port','ra_user','ra_api_key'];
loaders.settings = async () => {
  const [s, svc] = await Promise.all([api('/api/settings'), api('/api/service/status')]);
  SETTING_KEYS.forEach(k => { const el = $('#s-' + k); if (el) el.value = s.settings[k] ?? ''; });
  $('#default-pw-notice').classList.toggle('hidden', !s.settings.password_is_default);
  $('#manual-notice').classList.toggle('hidden', !svc.process.manual_mode);
  $('#autostart-toggle').checked = svc.autostart.registered;
  $('#service-info').innerHTML = [['PID', svc.process.pid],['Port', svc.process.port],['Mode', svc.process.manual_mode ? 'manual (no autostart)' : 'autostart via custom.sh'],['Command', svc.autostart.cmd || svc.suggested_cmd],['custom.sh', svc.autostart.file]].map(([k,v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('');
};
$('#settings-form').onsubmit = async e => {
  e.preventDefault(); const data = {}; SETTING_KEYS.forEach(k => { const el = $('#s-' + k); if (el) data[k] = el.value; });
  try { await api('/api/settings', { method:'POST', json: data }); ok('Settings saved'); state.catalogue = null; loaders.settings(); } catch (e2) { err(e2); }
};
$('#password-form').onsubmit = async e => {
  e.preventDefault();
  const cur = $('#pw-current').value, nw = $('#pw-new').value, cf = $('#pw-confirm').value;
  if (nw !== cf) return err('New passwords do not match');
  try { await api('/api/password', { method:'POST', json:{ current: cur, new: nw, confirm: cf } }); ok('Password changed'); $('#password-form').reset(); loaders.settings(); } catch (e2) { err(e2); }
};
$('#ra-test').onclick = async () => { try { const r = await api('/api/retroachievements/test', { method:'POST', json:{ user: $('#s-ra_user').value, api_key: $('#s-ra_api_key').value } }); ok(`Connected as ${r.user} (${r.points} points)`); } catch (e) { err(e); } };
async function setAutostart(enabled) { try { await api('/api/service/autostart', { method:'POST', json:{ enabled } }); ok(enabled ? 'Autostart enabled' : 'Autostart removed'); loaders.settings(); } catch (e) { err(e); } }
$('#autostart-toggle').onchange = e => setAutostart(e.target.checked);
$('#manual-enable').onclick = () => setAutostart(true);
$('#svc-customsh').onclick = async () => { const d = await api('/api/service/custom-sh'); const v = $('#customsh-view'); v.textContent = d.exists ? d.content : `(${d.path} does not exist yet)`; v.classList.toggle('hidden'); };
$('#svc-restart').onclick = async () => { if (!await confirmBox('Restart portal', 'The web interface will drop for a second or two.', 'Restart', false)) return; try { await api('/api/service/restart', { method:'POST' }); toast('Restarting… reloading in 3 s'); setTimeout(() => location.reload(), 3000); } catch (e) { err(e); } };
$('#svc-reboot').onclick = async () => { if (!await confirmBox('Reboot machine', 'Reboot the whole Batocera machine now?', 'Reboot')) return; try { await api('/api/service/power', { method:'POST', json:{ action:'reboot' } }); toast('Rebooting…'); } catch (e) { err(e); } };
$('#svc-shutdown').onclick = async () => { if (!await confirmBox('Shut down', 'Power off the Batocera machine now?', 'Shut down')) return; try { await api('/api/service/power', { method:'POST', json:{ action:'shutdown' } }); toast('Shutting down…'); } catch (e) { err(e); } };

// ------------------------------------------------------------ boot ----
(async () => {
  try { await loadInfo(); } catch (e) { err(e); }
  pollEs(); setInterval(pollEs, 15000);
  const start = location.hash.replace('#', '');
  showPanel(TITLES[start] ? start : 'dashboard');
  if (start === 'add' || start === 'themes') loaders.roms().catch(()=>{});
})();
})();
