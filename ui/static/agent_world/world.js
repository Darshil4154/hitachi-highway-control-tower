import * as THREE from "three";

const params = new URLSearchParams(location.search);
// always = replay ambient + interrupt on Desk/What-if pulses
const MODE = params.get("mode") || "always"; // always | replay | live
const START_EVENT = params.get("event") || "";
const SPEED = Number(params.get("speed") || "1");
const REPLAY = MODE === "always" || MODE === "replay";
const LISTEN_LIVE = MODE === "always" || MODE === "live";

const view = document.getElementById("view");
const cardsEl = document.getElementById("cards");
const detailEl = document.getElementById("detail");
const toast = document.getElementById("toast");
const modePill = document.getElementById("modePill");
const eventPill = document.getElementById("eventPill");
const stagePill = document.getElementById("stagePill");

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0b1220);
scene.fog = new THREE.Fog(0x0b1220, 40, 75);

const aspect = () => view.clientWidth / Math.max(1, view.clientHeight);
const frustum = 18;
const camera = new THREE.OrthographicCamera(
  -frustum * aspect(), frustum * aspect(), frustum, -frustum, 0.1, 120,
);
camera.position.set(26, 28, 26);
camera.lookAt(0, 0, 0);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(view.clientWidth, view.clientHeight);
renderer.shadowMap.enabled = true;
view.appendChild(renderer.domElement);

scene.add(new THREE.AmbientLight(0xb6c2d9, 0.7));
const sun = new THREE.DirectionalLight(0xffffff, 1.05);
sun.position.set(12, 22, 8);
sun.castShadow = true;
scene.add(sun);
const fill = new THREE.DirectionalLight(0x38bdf8, 0.25);
fill.position.set(-10, 8, -6);
scene.add(fill);

const worldGroup = new THREE.Group();
scene.add(worldGroup);

const agentMeshes = new Map();
const plantMeshes = new Map();
const beams = [];
let bootstrap = null;
let playlist = [];
let playIndex = 0;
let stageQueue = [];
let stageIndex = 0;
let stageT0 = 0;
let current = null;
let livePoll = null;
let lastLiveTs = 0;
let sourceMode = "boot"; // replay | live
const clickables = [];
let focusedId = null;
let agentOrder = [];
let workingIds = new Set();

function hexTile(x, z, color = 0x1e293b, y = 0) {
  const geo = new THREE.CylinderGeometry(0.95, 0.95, 0.18, 6);
  const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.75, metalness: 0.1 });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.position.set(x, y, z);
  mesh.receiveShadow = true;
  worldGroup.add(mesh);
  return mesh;
}

function building(kind, color) {
  const g = new THREE.Group();
  const c = new THREE.Color(color);
  if (kind === "hub") {
    const base = new THREE.Mesh(
      new THREE.CylinderGeometry(1.4, 1.6, 0.4, 8),
      new THREE.MeshStandardMaterial({ color: 0xf97316, roughness: 0.4 }),
    );
    base.position.y = 0.2;
    const top = new THREE.Mesh(
      new THREE.CylinderGeometry(1.1, 1.1, 0.35, 8),
      new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: 0.35 }),
    );
    top.position.y = 0.55;
    g.add(base, top);
    for (let i = 0; i < 5; i++) {
      const pole = new THREE.Mesh(
        new THREE.CylinderGeometry(0.04, 0.04, 1.6, 6),
        new THREE.MeshStandardMaterial({ color: 0xcbd5e1 }),
      );
      const a = (i / 5) * Math.PI * 2;
      pole.position.set(Math.cos(a) * 1.1, 1.1, Math.sin(a) * 1.1);
      g.add(pole);
    }
  } else if (kind === "dome") {
    const base = new THREE.Mesh(
      new THREE.CylinderGeometry(0.9, 1.0, 0.35, 16),
      new THREE.MeshStandardMaterial({ color: 0xf1f5f9 }),
    );
    base.position.y = 0.2;
    const dome = new THREE.Mesh(
      new THREE.SphereGeometry(0.85, 16, 12, 0, Math.PI * 2, 0, Math.PI / 2),
      new THREE.MeshStandardMaterial({ color: 0xf97316, metalness: 0.4, roughness: 0.3 }),
    );
    dome.position.y = 0.38;
    g.add(base, dome);
  } else if (kind === "tower" || kind === "gate") {
    const body = new THREE.Mesh(
      new THREE.BoxGeometry(1.2, 1.8, 1.2),
      new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.5 }),
    );
    body.position.y = 1.0;
    const stripe = new THREE.Mesh(
      new THREE.BoxGeometry(1.25, 0.25, 1.25),
      new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: 0.4 }),
    );
    stripe.position.y = 1.5;
    g.add(body, stripe);
  } else if (kind === "plant") {
    const pad = new THREE.Mesh(
      new THREE.BoxGeometry(1.6, 0.2, 1.6),
      new THREE.MeshStandardMaterial({ color: 0x334155 }),
    );
    pad.position.y = 0.1;
    const core = new THREE.Mesh(
      new THREE.BoxGeometry(0.9, 0.9, 0.9),
      new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: 0.2 }),
    );
    core.position.y = 0.65;
    g.add(pad, core);
  } else {
    // station / worker building
    const body = new THREE.Mesh(
      new THREE.BoxGeometry(1.3, 1.1, 1.3),
      new THREE.MeshStandardMaterial({ color: 0xf8fafc }),
    );
    body.position.y = 0.7;
    const band = new THREE.Mesh(
      new THREE.BoxGeometry(1.35, 0.22, 1.35),
      new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: 0.45 }),
    );
    band.position.y = 1.05;
    g.add(body, band);
  }
  g.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
  return g;
}

function workerFigure(color) {
  const g = new THREE.Group();
  const body = new THREE.Mesh(
    new THREE.CapsuleGeometry(0.18, 0.35, 4, 8),
    new THREE.MeshStandardMaterial({ color: 0xf8fafc }),
  );
  body.position.y = 0.55;
  const head = new THREE.Mesh(
    new THREE.SphereGeometry(0.16, 12, 12),
    new THREE.MeshStandardMaterial({ color: 0xe2e8f0 }),
  );
  head.position.y = 1.0;
  const staff = new THREE.Mesh(
    new THREE.CylinderGeometry(0.03, 0.03, 0.9, 6),
    new THREE.MeshStandardMaterial({ color: new THREE.Color(color), emissive: new THREE.Color(color), emissiveIntensity: 0.5 }),
  );
  staff.position.set(0.22, 0.7, 0);
  g.add(body, head, staff);
  g.traverse((o) => { if (o.isMesh) o.castShadow = true; });
  return g;
}

function makeBeam(from, to, color) {
  const points = [from.clone(), to.clone()];
  points[0].y = 0.4; points[1].y = 0.4;
  const geo = new THREE.BufferGeometry().setFromPoints(points);
  const mat = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.85 });
  const line = new THREE.Line(geo, mat);
  worldGroup.add(line);
  const glow = new THREE.Mesh(
    new THREE.SphereGeometry(0.12, 8, 8),
    new THREE.MeshBasicMaterial({ color }),
  );
  glow.position.copy(points[0]);
  worldGroup.add(glow);
  beams.push({ line, glow, from: points[0].clone(), to: points[1].clone(), t: Math.random(), speed: 0.35 + Math.random() * 0.4 });
}

function buildGround() {
  for (let q = -12; q <= 12; q++) {
    for (let r = -12; r <= 12; r++) {
      if (Math.hypot(q, r) > 13.5) continue;
      const x = q * 1.7 + r * 0.85;
      const z = r * 1.5;
      const shade = ((q + r) & 1) ? 0x172033 : 0x1e293b;
      hexTile(x * 0.6, z * 0.6, shade, 0);
    }
  }
  const sand = new THREE.Mesh(
    new THREE.CircleGeometry(40, 48),
    new THREE.MeshStandardMaterial({ color: 0x334155, roughness: 1 }),
  );
  sand.rotation.x = -Math.PI / 2;
  sand.position.y = -0.12;
  worldGroup.add(sand);
}

function initials(name) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
}

function project(pos) {
  const v = pos.clone().project(camera);
  const x = (v.x * 0.5 + 0.5) * view.clientWidth;
  const y = (-v.y * 0.5 + 0.5) * view.clientHeight;
  return { x, y, behind: v.z > 1 };
}

function buildCards(agents) {
  cardsEl.innerHTML = "";
  agentOrder = agents.map((a) => a.id);
  agents.forEach((a) => {
    const el = document.createElement("div");
    el.className = "card";
    el.dataset.id = a.id;
    el.innerHTML = `
      <div class="card-head">
        <div class="avatar" style="background:${a.color}">${initials(a.name)}</div>
        <div>
          <h3>${a.name}</h3>
          <div class="role">${a.role}</div>
        </div>
      </div>
      <div class="status"><span class="dot"></span><span class="label">Idle</span></div>
      <div class="bar"><i></i></div>`;
    el.addEventListener("click", (e) => { e.stopPropagation(); focusAgent(a.id); });
    cardsEl.appendChild(el);
  });
}

function focusAgent(id) {
  const agent = (bootstrap?.agents || []).find((a) => a.id === id);
  if (!agent) return;
  focusedId = id;
  for (const card of cardsEl.querySelectorAll(".card")) {
    card.classList.toggle("focused", card.dataset.id === id);
  }
  syncFocusedCardStatus();
  showDetail(agent);
  toast.textContent = `${agent.name} highlighted - Next walks the roster`;
  layoutCards();
}

function clearFocus() {
  focusedId = null;
  cardsEl.querySelectorAll(".card").forEach((c) => c.classList.remove("focused"));
  detailEl.style.display = "none";
  toast.textContent = "All tags visible. Pipeline keeps running.";
  layoutCards();
}

function stepFocus(delta) {
  if (!agentOrder.length) return;
  let idx = focusedId ? agentOrder.indexOf(focusedId) : -1;
  idx = (idx + delta + agentOrder.length) % agentOrder.length;
  focusAgent(agentOrder[idx]);
}

function syncFocusedCardStatus() {
  for (const card of cardsEl.querySelectorAll(".card")) {
    const on = workingIds.has(card.dataset.id);
    card.classList.toggle("working", on);
    card.querySelector(".label").textContent = on ? "Working" : "Idle";
    const dot = card.querySelector(".dot");
    dot.classList.toggle("working", on);
    card.querySelector(".bar > i").style.width = on ? "70%" : "0%";
  }
}

function showDetail(agent, extra = {}) {
  detailEl.style.display = "block";
  const event = current || {};
  const working = workingIds.has(agent.id) || (event.active_agents || []).includes(agent.id);
  detailEl.innerHTML = `
    <h2>${agent.name}</h2>
    <p>${agent.role}</p>
    <div class="chip">${extra.status || (working ? "Working" : "Idle")}</div>
    <div class="chip">${event.event_id || extra.label || "—"}</div>
    <p style="margin-top:10px">${event.summary || extra.summary || "Waiting for the next stage."}</p>
    <div>${Object.entries(event.tools || extra.tools || {}).map(([k, v]) => `<span class="chip">${k} × ${v}</span>`).join("")}</div>
  `;
}

function setAgentActive(ids, progress = 0.4) {
  workingIds = new Set(ids || []);
  for (const [id, mesh] of agentMeshes) {
    const on = workingIds.has(id);
    const matBand = mesh.userData.pulse;
    if (matBand) matBand.emissiveIntensity = on ? 0.85 : 0.12;
    if (mesh.userData.figure) {
      mesh.userData.figure.visible = true;
      mesh.userData.figure.scale.setScalar(on ? 1.15 : 1);
    }
  }
  syncFocusedCardStatus();
}

function layoutCards() {
  const W = 200, H = 92, pad = 10;
  const items = [];
  for (const [id, mesh] of agentMeshes) {
    const card = cardsEl.querySelector(`.card[data-id="${id}"]`);
    if (!card) continue;
    const anchor = project(mesh.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0, 1.8, 0)));
    let x = Math.min(view.clientWidth - W / 2 - 12, Math.max(W / 2 + 12, anchor.x));
    let y = Math.min(view.clientHeight - 70, Math.max(70, anchor.y - 70));
    items.push({ id, card, anchor, x, y });
  }
  // Separate overlapping tags
  for (let iter = 0; iter < 18; iter++) {
    for (let i = 0; i < items.length; i++) {
      for (let j = i + 1; j < items.length; j++) {
        const a = items[i], b = items[j];
        const dx = b.x - a.x, dy = b.y - a.y;
        const minX = W + pad, minY = H + pad;
        if (Math.abs(dx) < minX && Math.abs(dy) < minY) {
          const pushX = (minX - Math.abs(dx)) / 2 + 1;
          const pushY = (minY - Math.abs(dy)) / 2 + 1;
          const sx = dx === 0 ? (i % 2 ? 1 : -1) : Math.sign(dx);
          const sy = dy === 0 ? (j % 2 ? 1 : -1) : Math.sign(dy);
          a.x -= sx * pushX * 0.55;
          b.x += sx * pushX * 0.55;
          a.y -= sy * pushY * 0.55;
          b.y += sy * pushY * 0.55;
        }
      }
      items[i].x = Math.min(view.clientWidth - W / 2 - 8, Math.max(W / 2 + 8, items[i].x));
      items[i].y = Math.min(view.clientHeight - 56, Math.max(64, items[i].y));
    }
  }
  const leaders = document.getElementById("leaders");
  if (leaders) {
    let svg = "";
    for (const it of items) {
      it.card.style.display = "block";
      it.card.style.left = `${it.x}px`;
      it.card.style.top = `${it.y}px`;
      const x2 = it.x, y2 = it.y;
      svg += `<line x1="${it.anchor.x}" y1="${it.anchor.y}" x2="${x2}" y2="${y2}"
        stroke="#64748b" stroke-width="1.2" stroke-dasharray="3 3" opacity="0.75"/>`;
      svg += `<circle cx="${it.anchor.x}" cy="${it.anchor.y}" r="2.5" fill="#94a3b8"/>`;
    }
    leaders.innerHTML = svg;
  }
}

function placeAgents(agents) {
  agents.forEach((a) => {
    const b = building(a.kind, a.color);
    b.position.set(a.x, 0, a.z);
    b.userData.agent = a;
    // find emissive band for pulse
    b.traverse((o) => {
      if (o.isMesh && o.material && o.material.emissive) b.userData.pulse = o.material;
    });
    const fig = workerFigure(a.color);
    fig.position.set(a.x + 0.9, 0, a.z + 0.9);
    fig.userData.agent = a;
    fig.userData.kind = "worker";
    b.userData.figure = fig;
    worldGroup.add(b, fig);
    agentMeshes.set(a.id, b);
    clickables.push(b, fig);
    hexTile(a.x, a.z, 0x0ea5e9, 0.02);
  });
}

function placePlants(plants) {
  plants.forEach((p) => {
    const b = building("plant", "#64748b");
    b.position.set(p.x, 0, p.z);
    b.userData.plant = p;
    b.userData.kind = "plant";
    worldGroup.add(b);
    plantMeshes.set(p.id, b);
    clickables.push(b);
  });
}

function wireBeams(agents) {
  const hub = agents.find((a) => a.id === "coordinator");
  if (!hub) return;
  const hubPos = new THREE.Vector3(hub.x, 0.4, hub.z);
  agents.forEach((a) => {
    if (a.id === "coordinator") return;
    makeBeam(hubPos, new THREE.Vector3(a.x, 0.4, a.z), a.color);
  });
}

function stagesFor(event) {
  const order = ["extract", "resolve", "gate", "plan", "verify", "twin", "execute", "readback"];
  const s = event.stages_s || {};
  const out = [];
  for (const name of order) {
    const dur = Number(s[name] || 0);
    // Always show a beat even when timing is 0, so replay stays readable
    out.push({ name, dur: Math.max(0.35, dur > 0 ? Math.min(2.8, dur * 40) : 0.55) });
  }
  return out;
}

function beginEvent(event) {
  current = event;
  stageQueue = stagesFor(event);
  stageIndex = 0;
  stageT0 = performance.now();
  eventPill.innerHTML = `Event <b>${event.event_id || event.label || "live"}</b>`;
  toast.textContent = event.summary || event.banner || "Working…";
  // light plants mentioned in summary
  for (const [pid, mesh] of plantMeshes) {
    const on = (event.summary || "").includes(pid);
    mesh.traverse((o) => {
      if (o.isMesh && o.material && o.material.emissive) {
        o.material.emissiveIntensity = on ? 0.7 : 0.05;
      }
    });
  }
}

function advanceReplay() {
  if (!REPLAY || !playlist.length) return;
  // After a live pulse, wait ~8s before ambient replay resumes
  if (sourceMode === "live" && performance.now() - (current?._liveAt || 0) < 8000) return;
  sourceMode = "replay";
  modePill.innerHTML = `Mode <b>always</b> · replay`;
  playIndex = (playIndex + 1) % playlist.length;
  beginEvent(playlist[playIndex]);
}

function tickStages(now) {
  if (!stageQueue.length) return;
  const stage = stageQueue[stageIndex];
  if (!stage) {
    advanceReplay();
    return;
  }
  const elapsed = ((now - stageT0) / 1000) * SPEED;
  const progress = Math.min(1, elapsed / stage.dur);
  stagePill.innerHTML = `Stage <b>${stage.name}</b>`;
  const ids = (bootstrap.stage_agents[stage.name] || ["coordinator"]).slice();
  if (stage.name === "plan" && current?.active_agents?.length) {
    current.active_agents.forEach((id) => { if (!ids.includes(id)) ids.push(id); });
  }
  setAgentActive(ids, progress);
  if (elapsed >= stage.dur) {
    stageIndex += 1;
    stageT0 = now;
    if (stageIndex >= stageQueue.length) {
      stageQueue = [];
      setAgentActive(current?.active_agents || [], 1);
      setTimeout(advanceReplay, 700 / SPEED);
    }
  }
}

async function loadBootstrap() {
  const res = await fetch("./bootstrap.json?ts=" + Date.now());
  bootstrap = await res.json();
  playlist = bootstrap.playlist || [];
  buildGround();
  placeAgents(bootstrap.agents);
  placePlants(bootstrap.plants || []);
  wireBeams(bootstrap.agents);
  buildCards(bootstrap.agents);
  modePill.innerHTML = `Mode <b>${MODE}</b>`;
  if (START_EVENT) {
    const idx = playlist.findIndex((e) => e.event_id === START_EVENT);
    playIndex = idx >= 0 ? idx : 0;
  }
  if (LISTEN_LIVE && bootstrap.live) {
    applyLive(bootstrap.live, true);
  } else if (REPLAY && playlist[playIndex]) {
    sourceMode = "replay";
    beginEvent(playlist[playIndex]);
    toast.textContent = MODE === "always"
      ? `Always-on · replaying ${playlist.length} events · listening for Desk / What-if`
      : `Replaying ${playlist.length} scored events`;
  } else {
    toast.textContent = "Listening for Live Desk / What-if activity";
  }
  if (LISTEN_LIVE) {
    livePoll = setInterval(pollLive, 1200);
  }
}

async function pollLive() {
  try {
    const res = await fetch("./live_state.json?ts=" + Date.now());
    if (!res.ok) return;
    applyLive(await res.json(), false);
  } catch (_) { /* no live file yet */ }
}

function applyLive(live, force = false) {
  if (!live) return;
  const ts = Number(live.ts || 0);
  if (!force && ts && ts <= lastLiveTs) return;
  if (ts) lastLiveTs = ts;
  sourceMode = "live";
  modePill.innerHTML = `Mode <b>always</b> · live`;
  const ev = {
    event_id: live.label || "LIVE",
    summary: live.summary || live.banner || "",
    tools: live.tools || {},
    active_agents: live.active_agents || [],
    stages_s: { extract: 0.4, plan: 1.0, verify: 0.5, twin: 0.5 },
    banner: live.banner,
    _liveAt: performance.now(),
  };
  beginEvent(ev);
  toast.textContent = live.banner || live.summary || "Live sandbox pulse";
}

function onResize() {
  const w = view.clientWidth, h = view.clientHeight;
  camera.left = -frustum * (w / h);
  camera.right = frustum * (w / h);
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
}
window.addEventListener("resize", onResize);

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
renderer.domElement.addEventListener("pointerdown", (ev) => {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects(clickables, true);
  if (!hits.length) {
    detailEl.style.display = "none";
    return;
  }
  let obj = hits[0].object;
  while (obj && !obj.userData.agent && !obj.userData.plant) obj = obj.parent;
  if (obj?.userData?.agent) {
    focusAgent(obj.userData.agent.id);
    return;
  }
  if (obj?.userData?.plant) {
    clearFocus();
    const p = obj.userData.plant;
    detailEl.style.display = "block";
    detailEl.innerHTML = `<h2>${p.name}</h2><p>Plant node ${p.id}</p>
      <p>Lights up when an event summary mentions this plant.</p>`;
    toast.textContent = `Selected plant ${p.id}`;
  }
});

document.getElementById("btnNext")?.addEventListener("click", () => stepFocus(1));
document.getElementById("btnPrev")?.addEventListener("click", () => stepFocus(-1));
document.getElementById("btnClear")?.addEventListener("click", () => clearFocus());
window.addEventListener("keydown", (e) => {
  if (e.key === "ArrowRight" || e.key === "n") stepFocus(1);
  if (e.key === "ArrowLeft" || e.key === "p") stepFocus(-1);
  if (e.key === "Escape") clearFocus();
});

function animate(now) {
  requestAnimationFrame(animate);
  tickStages(now);
  for (const b of beams) {
    b.t = (b.t + b.speed * 0.016) % 1;
    b.glow.position.lerpVectors(b.from, b.to, b.t);
  }
  // gentle idle bob on figures
  for (const mesh of agentMeshes.values()) {
    if (mesh.userData.figure) {
      mesh.userData.figure.rotation.y += 0.01;
    }
  }
  layoutCards();
  renderer.render(scene, camera);
}

loadBootstrap().then(() => {
  onResize();
  requestAnimationFrame(animate);
}).catch((err) => {
  toast.textContent = "Failed to load world: " + err;
  console.error(err);
});
