import * as THREE from "three";

const params = new URLSearchParams(location.search);
const MODE = params.get("mode") || "replay"; // replay | live
const START_EVENT = params.get("event") || "";
const SPEED = Number(params.get("speed") || "1");

const view = document.getElementById("view");
const cardsEl = document.getElementById("cards");
const detailEl = document.getElementById("detail");
const toast = document.getElementById("toast");
const modePill = document.getElementById("modePill");
const eventPill = document.getElementById("eventPill");
const stagePill = document.getElementById("stagePill");

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0b1220);
scene.fog = new THREE.Fog(0x0b1220, 28, 55);

const aspect = () => view.clientWidth / Math.max(1, view.clientHeight);
const frustum = 12;
const camera = new THREE.OrthographicCamera(
  -frustum * aspect(), frustum * aspect(), frustum, -frustum, 0.1, 100,
);
camera.position.set(18, 20, 18);
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
  for (let q = -8; q <= 8; q++) {
    for (let r = -8; r <= 8; r++) {
      if (Math.hypot(q, r) > 9.5) continue;
      const x = q * 1.7 + r * 0.85;
      const z = r * 1.5;
      const shade = ((q + r) & 1) ? 0x172033 : 0x1e293b;
      hexTile(x * 0.55, z * 0.55, shade, 0);
    }
  }
  const sand = new THREE.Mesh(
    new THREE.CircleGeometry(28, 48),
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
  agents.forEach((a) => {
    const el = document.createElement("div");
    el.className = "card idle";
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
    el.addEventListener("click", () => showDetail(a));
    cardsEl.appendChild(el);
  });
}

function showDetail(agent, extra = {}) {
  detailEl.style.display = "block";
  const event = current || {};
  detailEl.innerHTML = `
    <h2>${agent.name}</h2>
    <p>${agent.role}</p>
    <div class="chip">${extra.status || (event.active_agents || []).includes(agent.id) ? "Working" : "Idle"}</div>
    <div class="chip">${event.event_id || extra.label || "—"}</div>
    <p style="margin-top:10px">${event.summary || extra.summary || "Waiting for the next stage."}</p>
    <div>${Object.entries(event.tools || extra.tools || {}).map(([k, v]) => `<span class="chip">${k} × ${v}</span>`).join("")}</div>
  `;
}

function setAgentActive(ids, progress = 0.4) {
  const set = new Set(ids || []);
  for (const [id, mesh] of agentMeshes) {
    const card = cardsEl.querySelector(`.card[data-id="${id}"]`);
    const on = set.has(id);
    const matBand = mesh.userData.pulse;
    if (matBand) matBand.emissiveIntensity = on ? 0.8 : 0.15;
    if (card) {
      card.classList.toggle("active", on);
      card.classList.toggle("idle", !on);
      card.querySelector(".label").textContent = on ? "Working" : "Idle";
      card.querySelector(".bar > i").style.width = on ? `${Math.round(progress * 100)}%` : "0%";
    }
    if (mesh.userData.figure) {
      mesh.userData.figure.visible = true;
      mesh.userData.figure.position.y = on ? Math.sin(performance.now() / 200) * 0.05 : 0;
    }
  }
}

function layoutCards() {
  for (const [id, mesh] of agentMeshes) {
    const card = cardsEl.querySelector(`.card[data-id="${id}"]`);
    if (!card) continue;
    const p = project(mesh.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0, 2.2, 0)));
    if (p.behind) { card.style.display = "none"; continue; }
    card.style.display = "block";
    card.style.left = `${p.x}px`;
    card.style.top = `${p.y}px`;
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
    b.userData.figure = fig;
    worldGroup.add(b, fig);
    agentMeshes.set(a.id, b);
    hexTile(a.x, a.z, 0x0ea5e9, 0.02);
  });
}

function placePlants(plants) {
  plants.forEach((p) => {
    const b = building("plant", "#64748b");
    b.position.set(p.x, 0, p.z);
    worldGroup.add(b);
    plantMeshes.set(p.id, b);
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

function tickStages(now) {
  if (!stageQueue.length) return;
  const stage = stageQueue[stageIndex];
  if (!stage) {
    // advance playlist
    if (MODE === "replay") {
      playIndex = (playIndex + 1) % Math.max(1, playlist.length);
      if (playlist[playIndex]) beginEvent(playlist[playIndex]);
    }
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
      setTimeout(() => {
        if (MODE === "replay" && playlist.length) {
          playIndex = (playIndex + 1) % playlist.length;
          beginEvent(playlist[playIndex]);
        }
      }, 700 / SPEED);
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
  if (MODE === "replay") {
    if (START_EVENT) {
      const idx = playlist.findIndex((e) => e.event_id === START_EVENT);
      playIndex = idx >= 0 ? idx : 0;
    }
    if (playlist[playIndex]) beginEvent(playlist[playIndex]);
    toast.textContent = `Replaying ${playlist.length} scored events`;
  } else {
    toast.textContent = "Listening for Live Desk / What-if activity";
    applyLive(bootstrap.live);
    livePoll = setInterval(pollLive, 1500);
  }
}

async function pollLive() {
  try {
    const res = await fetch("./live_state.json?ts=" + Date.now());
    if (!res.ok) return;
    applyLive(await res.json());
  } catch (_) { /* no live file yet */ }
}

function applyLive(live) {
  if (!live) return;
  modePill.innerHTML = `Mode <b>live</b>`;
  beginEvent({
    event_id: live.label || "LIVE",
    summary: live.summary || live.banner || "",
    tools: live.tools || {},
    active_agents: live.active_agents || [],
    stages_s: { [live.stage || "plan"]: 1.2 },
    banner: live.banner,
  });
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
  const hits = raycaster.intersectObjects([...agentMeshes.values()], true);
  if (!hits.length) return;
  let obj = hits[0].object;
  while (obj && !obj.userData.agent) obj = obj.parent;
  if (obj?.userData?.agent) showDetail(obj.userData.agent);
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
