const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let jobs = [];
let status = null;

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {},
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    throw new Error(Array.isArray(d) ? d.map((e) => `${e.loc?.slice(-1)[0]}: ${e.msg}`).join(", ") : d || res.statusText);
  }
  return data;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 4000);
}

function formData(form) {
  const out = {};
  for (const el of form.elements) {
    if (!el.name || el.type === "file") continue;
    if (el.type === "checkbox") out[el.name] = el.checked;
    else if (el.value !== "") out[el.name] = el.type === "number" ? Number(el.value) : el.value;
  }
  return out;
}

// ---------- routing
function route() {
  const view = (location.hash.slice(1).split("?")[0]) || "dashboard";
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  $$("nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  if (view === "settings") renderSettings();
  if (location.hash.includes("connected=youtube")) toast("YouTube connected ✓");
  render();
}
window.addEventListener("hashchange", route);

// ---------- uploads
$$("input[data-upload]").forEach((input) => {
  input.addEventListener("change", async () => {
    const hidden = input.closest("form").elements[input.dataset.upload];
    hidden.value = "";
    if (!input.files[0]) return;
    const fd = new FormData();
    fd.append("file", input.files[0]);
    const label = input.closest("label");
    label.dataset.orig ??= label.firstChild.textContent;
    label.firstChild.textContent = `${label.dataset.orig.trim()} — uploading… `;
    try {
      const r = await api("/api/uploads", { method: "POST", body: fd });
      hidden.value = r.path;
      label.firstChild.textContent = `${label.dataset.orig.trim()} — uploaded ✓ `;
    } catch (e) {
      label.firstChild.textContent = `${label.dataset.orig.trim()} — upload failed `;
      toast(e.message);
    }
  });
});

function submitJob(formId, endpoint, clean = (d) => d) {
  $(formId).addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const btn = $("button[type=submit]", ev.target);
    btn.disabled = true;
    try {
      const job = await api(endpoint, { method: "POST", body: JSON.stringify(clean(formData(ev.target))) });
      jobs.unshift(job);
      render();
      toast("Job started — you can leave this page, it keeps rendering on the server.");
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = false;
    }
  });
}
submitJob("#clips-form", "/api/clips");
submitJob("#ugc-form", "/api/ugc");

// ---------- jobs
const KIND = { clips: "Shorts", ugc: "UGC ad", publish: "Publish" };

function jobCard(j) {
  const pct = Math.round((j.progress || 0) * 100);
  let body = "";
  if (j.status === "running" || j.status === "queued") body = `<div class="bar"><i style="width:${pct}%"></i></div>`;
  if (j.status === "error") body = `<div class="error-text">${esc(j.message)}</div>`;
  if (j.status === "done" && j.output) {
    const vids = videosOf(j);
    if (vids.length) body = `<div class="media-grid">${vids.map(mediaCard).join("")}</div>`;
    if (j.kind === "publish") {
      const r = j.output.results || {}, e = j.output.errors || {};
      body = `<div class="job-meta">${Object.entries(r).map(([k, v]) => `✓ ${esc(k)} ${v.url ? `<a href="${esc(v.url)}" target="_blank">${esc(v.url)}</a>` : ""}`).join("<br>")}
              ${Object.entries(e).map(([k, v]) => `<div class="error-text">✗ ${esc(k)}: ${esc(v)}</div>`).join("")}</div>`;
    }
  }
  return `<div class="job" data-id="${j.id}">
    <div class="job-head">
      <div style="min-width:0"><div class="job-title">${esc(j.output?.title || j.title || KIND[j.kind])}</div>
      <div class="job-meta">${KIND[j.kind] || j.kind} · ${new Date(j.created_at * 1000).toLocaleString()} · ${esc(j.status === "done" ? "" : j.message)}</div></div>
      <div style="display:flex;gap:8px;align-items:center"><span class="badge ${j.status}">${j.status}${j.status === "running" ? ` ${pct}%` : ""}</span>
      <button class="small" onclick="deleteJob('${j.id}')" title="Delete">✕</button></div>
    </div>${body}</div>`;
}

function videosOf(j) {
  if (j.status !== "done" || !j.output) return [];
  if (j.kind === "clips") return j.output.clips.map((c) => ({ ...c, caption: `${c.hook}`, tags: c.hashtags }));
  if (j.kind === "ugc") return [{ ...j.output, tags: j.output.hashtags }];
  return [];
}

function mediaCard(v) {
  const payload = encodeURIComponent(JSON.stringify({ video: v.video, title: v.title, caption: v.caption || "", tags: v.tags || [] }));
  return `<div class="media">
    <video src="${esc(v.video)}" poster="${esc(v.thumbnail || "")}" controls preload="none" playsinline></video>
    <div class="info"><b>${esc(v.title)}</b>
      <small>${v.virality_score != null ? `<span class="score">${v.virality_score}</span> virality · ` : ""}${v.duration ?? ""}s</small>
      <div class="actions"><a href="${esc(v.video)}" download><button class="small">Download</button></a>
      <button class="small primary" onclick="openPublish('${payload}')">Publish</button></div>
    </div></div>`;
}

window.deleteJob = async (id) => {
  if (!confirm("Delete this job and its files?")) return;
  await api(`/api/jobs/${id}`, { method: "DELETE" });
  jobs = jobs.filter((j) => j.id !== id);
  render();
};

function render() {
  $("#job-list").innerHTML = jobs.slice(0, 15).map(jobCard).join("") || `<p class="hint">No jobs yet.</p>`;
  $("#clips-jobs").innerHTML = jobs.filter((j) => j.kind === "clips").map(jobCard).join("");
  $("#ugc-jobs").innerHTML = jobs.filter((j) => j.kind === "ugc").map(jobCard).join("");
  const vids = jobs.flatMap(videosOf);
  $("#library").innerHTML = vids.map(mediaCard).join("") || `<p class="hint">Finished videos show up here.</p>`;
}

async function refresh() {
  try {
    const fresh = await api("/api/jobs");
    const changed = JSON.stringify(fresh.map((j) => [j.id, j.status, j.progress, j.message])) !==
      JSON.stringify(jobs.map((j) => [j.id, j.status, j.progress, j.message]));
    jobs = fresh;
    if (changed) render();
  } catch (e) { /* server restarting */ }
  const active = jobs.some((j) => j.status === "running" || j.status === "queued");
  setTimeout(refresh, active ? 2500 : 10000);
}

// ---------- publish
window.openPublish = (payload) => {
  const v = JSON.parse(decodeURIComponent(payload));
  const f = $("#publish-form");
  f.elements.file.value = v.video;
  f.elements.title.value = v.title || "";
  f.elements.caption.value = v.caption || "";
  f.elements.tags.value = (v.tags || []).map((t) => (t.startsWith("#") ? t : `#${t}`)).join(" ");
  $("#publish-preview").src = v.video;
  const p = status?.publish || {};
  for (const k of ["youtube", "tiktok", "instagram"]) {
    f.elements[k].disabled = !p[k];
    f.elements[k].checked = false;
    f.elements[k].parentElement.title = p[k] ? "" : "Not connected — see Settings";
    f.elements[k].parentElement.style.opacity = p[k] ? 1 : 0.45;
  }
  $("#publish-dialog").showModal();
};

$("#publish-dialog").addEventListener("close", async () => {
  const dlg = $("#publish-dialog");
  $("#publish-preview").pause();
  if (dlg.returnValue !== "publish") return;
  const f = $("#publish-form");
  const platforms = ["youtube", "tiktok", "instagram"].filter((k) => f.elements[k].checked);
  if (!platforms.length) return toast("Pick at least one connected platform.");
  try {
    const job = await api("/api/publish", {
      method: "POST",
      body: JSON.stringify({
        file: f.elements.file.value, platforms, title: f.elements.title.value, caption: f.elements.caption.value,
        tags: f.elements.tags.value.split(/\s+/).filter(Boolean), privacy: f.elements.privacy.value,
      }),
    });
    jobs.unshift(job);
    render();
    toast(`Publishing to ${platforms.join(", ")}… track it on the Dashboard.`);
  } catch (e) { toast(e.message); }
});

// ---------- studio
$("#ideas-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const btn = $("button[type=submit]", ev.target);
  btn.disabled = true;
  btn.textContent = "Thinking…";
  try {
    const r = await api("/api/studio/ideas", { method: "POST", body: JSON.stringify(formData(ev.target)) });
    $("#ideas-out").innerHTML = `
      <h3 style="margin-top:10px">Titles</h3><div class="idea-list">${r.titles.map((t) =>
        `<div class="idea" onclick="navigator.clipboard.writeText(this.dataset.t);toast('Copied')" data-t="${esc(t.title)}">
          <div>${esc(t.title)}<small>${esc(t.angle)}</small></div><span class="score">${t.score}</span></div>`).join("")}</div>
      <h3 style="margin-top:14px">Thumbnail concepts</h3><div class="idea-list">${r.thumbnails.map((t) =>
        `<div class="idea" onclick="useConcept(this)" data-text="${esc(t.text)}" data-hl="${esc(t.highlight_word)}" data-color="${esc(t.accent_color)}">
          <div><b style="color:${esc(t.accent_color)}">${esc(t.text)}</b><small>${esc(t.visual)}</small></div><span>use →</span></div>`).join("")}</div>
      <h3 style="margin-top:14px">Description</h3><textarea rows="6">${esc(r.description)}</textarea>
      <h3 style="margin-top:14px">Tags</h3><textarea rows="2">${esc(r.tags.join(", "))}</textarea>`;
  } catch (e) { toast(e.message); }
  btn.disabled = false;
  btn.textContent = "Generate ideas";
});

window.useConcept = (el) => {
  const f = $("#thumb-form");
  f.elements.text.value = el.dataset.text;
  f.elements.highlight_word.value = el.dataset.hl;
  if (/^#[0-9a-f]{6}$/i.test(el.dataset.color)) f.elements.accent_color.value = el.dataset.color;
  toast("Concept loaded into the thumbnail maker");
};

$("#thumb-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const d = formData(ev.target);
  if (!d.background_path) return toast("Upload a background image or video first.");
  const btn = $("button[type=submit]", ev.target);
  btn.disabled = true;
  try {
    const r = await api("/api/studio/thumbnails", { method: "POST", body: JSON.stringify(d) });
    $("#thumbs-out").innerHTML = r.images.map((u) => `<a href="${u}" download><img src="${u}" alt="Thumbnail" /></a>`).join("");
  } catch (e) { toast(e.message); }
  btn.disabled = false;
});

// ---------- settings
async function loadStatus() {
  try {
    status = await api("/api/status");
    $("#model-badge").textContent = `AI: ${status.model}`;
  } catch (e) { /* ignore */ }
}

async function renderSettings() {
  await loadStatus();
  if (!status) return;
  const s = status, p = s.publish;
  const row = (on, title, sub, action = "") =>
    `<div class="settings-row"><div><span class="dot ${on ? "on" : ""}"></span><b>${title}</b><small>${sub}</small></div>${action}</div>`;
  $("#settings").innerHTML = [
    row(s.llm, "Claude (scripts, highlights, titles)", s.llm ? s.model : "Set ANTHROPIC_API_KEY"),
    row(true, "Transcription", `faster-whisper · ${esc(s.whisper)} (local)`),
    row(s.tts_ready, "Voiceover", `${esc(s.tts)}${s.tts_ready ? "" : " — missing API key"}`),
    row(true, "AI presenter", `${esc(s.avatar)}${s.avatar === "photo" ? " — animated photo, no lip-sync. Set AVATAR_PROVIDER=did or lipsync_http for talking heads." : ""}`),
    row(s.broll, "B-roll (Pexels)", s.broll ? "Connected" : "Set PEXELS_API_KEY — otherwise product photos are used"),
    row(p.youtube, "YouTube", p.youtube ? "Connected" : p.youtube_configured ? "Ready to connect" : "Set YOUTUBE_CLIENT_ID / SECRET",
      p.youtube_configured ? (p.youtube ? `<button class="small" onclick="ytDisconnect()">Disconnect</button>` : `<a href="/api/oauth/youtube/start"><button class="small primary">Connect YouTube</button></a>`) : ""),
    row(p.tiktok, "TikTok", p.tiktok ? "Token configured" : "Set TIKTOK_ACCESS_TOKEN"),
    row(p.instagram, "Instagram Reels", p.instagram ? "Token configured" : "Set IG_USER_ID / IG_ACCESS_TOKEN"),
    row(!s.public_base_url.includes("localhost"), "Public URL", `${esc(s.public_base_url)} — must be public https for Instagram, D-ID and YouTube OAuth`),
  ].join("");
}
window.ytDisconnect = async () => { await api("/api/oauth/youtube/disconnect", { method: "POST" }); renderSettings(); };

loadStatus();
route();
refresh();
