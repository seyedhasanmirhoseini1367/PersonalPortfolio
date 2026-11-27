/* LearningJourney town in 3D: Kenney's City, Car, Nature and Furniture kits drawn by three.js with an
 * isometric (orthographic) camera. One town for all of a learner's subjects.
 *
 * The world only draws and moves things. Everything that counts (answers, XP, coins, quests, purchases) is
 * decided by the server through the same /learn/api/ endpoints as the rest of LearningJourney, so nothing here
 * can earn a reward on its own.
 */
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {OBJLoader} from 'three/addons/loaders/OBJLoader.js';
import {MTLLoader} from 'three/addons/loaders/MTLLoader.js';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';

const CFG = JSON.parse(document.getElementById('t3-config').textContent);
const $ = id => document.getElementById(id);
const root = $('t3');
const CALM = matchMedia('(prefers-reduced-motion: reduce)').matches;
const COARSE = matchMedia('(pointer: coarse)').matches;
const PEOPLE = ['character-female-b', 'character-male-e', 'character-female-d', 'character-male-f', 'character-female-c', 'character-male-b'];
const PERSON_SCALE = 0.3, CAR_SCALE = 0.16;
const W = 18, D = 14;                 // the district, in road tiles
const ROAD_Z = 6, SIDE_X = 10;        // the main street runs along x; a side street goes south at x = 10

// ── the places ────────────────────────────────────────────────────────────
// door: where you stand to go in. c: the colour of the place in labels and panels. tint: a colour wash that
// gives each building its own character. npc: who you talk to there.
const PLACES = [
    {key: 'academy', model: 'commercial/building-j', at: [2.4, 2.85], door: [2.4, 4.35], tint: 0xf6e6cc, title: 'Akatemia',
     sub: 'Academy · every subject you study', icon: 'fa-graduation-cap', c: '#2f8fd8', panel: 'academy'},
    {key: 'library', model: 'commercial/building-k', at: [5.75, 2.95], door: [5.75, 4.35], tint: 0xe6b9a2, title: 'Kirjasto',
     sub: 'Library · your material and notes', icon: 'fa-book', c: '#7a5cc2', panel: 'library'},
    {key: 'cafe', model: 'commercial/building-c', at: [8.55, 3.1], door: [8.55, 4.4], tint: 0xfbefe0, title: 'Kahvila',
     sub: 'Language café · order in Finnish', icon: 'fa-mug-hot', c: '#c9773b', scene: 'cafe',
     npc: {model: 'character-female-c', at: [9.15, 4.25], yaw: .5}},
    {key: 'practice', model: 'commercial/building-e', at: [11.7, 3.0], door: [11.7, 4.35], tint: 0xd8e9ef, title: 'Harjoitus',
     sub: 'Practice centre · today’s review', icon: 'fa-dumbbell', c: '#3fae74', panel: 'practice'},
    {key: 'quests', model: 'commercial/building-d', at: [14.1, 3.1], door: [14.1, 4.4], tint: 0xf3e4bf, title: 'Tehtävät',
     sub: 'Quests and achievements', icon: 'fa-flag', c: '#e0a43a', panel: 'quests'},
    {key: 'bakery', model: 'commercial/building-c', at: [16.4, 3.1], door: [16.4, 4.4], tint: 0xf2cfa8, title: 'Leipomo',
     sub: 'Bakery · buy bread', icon: 'fa-bread-slice', c: '#b5651d', scene: 'bakery',
     npc: {model: 'character-male-b', at: [17.0, 4.25], yaw: -.4}},
    {key: 'market', at: [13.9, 9.6], door: [13.9, 10.55], title: 'Tori', sub: 'Market · fruit and vegetables',
     icon: 'fa-apple-whole', c: '#d9546b', scene: 'market', npc: {model: 'character-male-a', at: [13.9, 9.25], yaw: 0}},
    {key: 'bus', at: [11.05, 8.4], door: [11.25, 9.15], title: 'Bussipysäkki', sub: 'Bus stop · tickets and directions',
     icon: 'fa-bus', c: '#4a86c5', scene: 'bus', npc: {model: 'character-female-d', at: [11.55, 8.55], yaw: -1.2}},
    {key: 'home', model: 'suburban/building-type-h', at: [16.0, 12.55], rot: Math.PI, door: [16.0, 11.25], tint: 0xffffff,
     title: 'Koti', sub: 'Home · you, your progress and your town', icon: 'fa-house', c: '#8a6bd1', panel: 'home'},
];
const BACKDROP = [   // taller buildings behind the street, for a skyline
    ['commercial/building-a', .7, 1.0], ['commercial/building-h', 4.3, 1.0], ['commercial/building-a', 7.4, 1.05],
    ['commercial/building-h', 10.2, 1.0], ['commercial/building-a', 13.0, 1.05], ['commercial/building-h', 17.2, 1.0],
];

// ── server ────────────────────────────────────────────────────────────────
async function post(url, data = {}) {
    const r = await fetch(url, {method: 'POST', credentials: 'same-origin', body: new URLSearchParams(data),
                                headers: {'X-CSRFToken': CFG.csrf, 'Accept': 'application/json'}});
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(body.error || body.message || 'Request failed'), {status: r.status});
    return body;
}
const getJSON = async url => (await fetch(url, {credentials: 'same-origin', headers: {'Accept': 'application/json'}})).json();
const sceneUrl = (key, what) => CFG.scene.replace('KEY', key) + what + '/';
let STATE = null;
const placeInfo = p => ((STATE && STATE.places) || {})[p.key] || {};
const isLocked = p => !!placeInfo(p).locked;

// ── sound: off until turned on ────────────────────────────────────────────
const Sound = {
    on: (() => { try { return localStorage.getItem('t3-sound') === '1'; } catch (e) { return false; } })(), ctx: null,
    tone(f, d, type = 'sine', v = .06, w = 0) {
        if (!this.on) return;
        this.ctx = this.ctx || new (window.AudioContext || window.webkitAudioContext)();
        const t = this.ctx.currentTime + w, o = this.ctx.createOscillator(), g = this.ctx.createGain();
        o.type = type; o.frequency.value = f; g.gain.setValueAtTime(v, t); g.gain.exponentialRampToValueAtTime(.0001, t + d);
        o.connect(g).connect(this.ctx.destination); o.start(t); o.stop(t + d);
    },
    open() { this.tone(660, .12); this.tone(880, .16, 'sine', .05, .08); },
    right() { this.tone(784, .12, 'triangle', .07); this.tone(1175, .18, 'triangle', .06, .09); },
    wrong() { this.tone(220, .2, 'sine', .06); },
    done() { [523, 659, 784, 1047].forEach((f, i) => this.tone(f, .16, 'triangle', .06, i * .1)); },
};
function setSound(on) {
    Sound.on = on;
    try { localStorage.setItem('t3-sound', on ? '1' : '0'); } catch (e) { /* private mode */ }
    const b = $('t3-sound');
    b.setAttribute('aria-pressed', String(on)); b.setAttribute('aria-label', on ? 'Sound on' : 'Sound off');
    b.querySelector('i').className = 'fas ' + (on ? 'fa-volume-high' : 'fa-volume-xmark');
    if (on) Sound.open();
}
$('t3-sound').addEventListener('click', () => setSound(!Sound.on));
setSound(Sound.on);

// ── renderer, scene, camera, light ───────────────────────────────────────
const stage = $('t3-stage');
const renderer = new THREE.WebGLRenderer({antialias: true, alpha: true, powerPreference: 'high-performance'});
renderer.setPixelRatio(Math.min(devicePixelRatio, COARSE ? 1.75 : 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
stage.append(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -100, 200);
const VIEW = new THREE.Vector3(1, 0.95, 1).normalize();    // isometric: 45° round, a little more than 35° down
const focus = new THREE.Vector3(6, 0, 7);
let zoom = 1, overview = false;

const hemi = new THREE.HemisphereLight(0xdfefff, 0xb7a58c, 1.15);
scene.add(hemi);
const sun = new THREE.DirectionalLight(0xfff1dc, 2.4);
sun.position.set(-8, 14, 6);
sun.target.position.set(W / 2, 0, D / 2);
sun.castShadow = true;
sun.shadow.mapSize.set(COARSE ? 1024 : 2048, COARSE ? 1024 : 2048);
Object.assign(sun.shadow.camera, {left: -14, right: 14, top: 14, bottom: -14, near: 1, far: 60});
sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.02;
scene.add(sun, sun.target);

// Time of day: a bright day, a warm late afternoon, and a blue evening with the lamps lit.
const hour = new Date().getHours();
const forced = new URLSearchParams(location.search).get('time');
const WHEN = ['day', 'golden', 'evening'].includes(forced) ? forced : hour >= 7 && hour < 15 ? 'day' : hour >= 15 && hour < 18 ? 'golden' : 'evening';
if (WHEN === 'golden') {
    sun.color.set(0xffc996); sun.intensity = 2.1; sun.position.set(-12, 7, 2); hemi.color.set(0xffe2c4); hemi.intensity = .95;
    root.style.background = 'radial-gradient(120% 90% at 50% 10%,#fdf1e4 0%,#f1dccb 55%,#dcc7bb 100%)';
} else if (WHEN === 'evening') {
    sun.color.set(0x9db4ff); sun.intensity = .55; sun.position.set(-6, 12, 10); hemi.color.set(0x7f95c9); hemi.groundColor.set(0x3a3550); hemi.intensity = .7;
    root.style.background = 'radial-gradient(120% 90% at 50% 10%,#3c4a6b 0%,#27304a 60%,#1b2236 100%)';
}
const EVENING = WHEN === 'evening';

function resize() {
    const w = stage.clientWidth, h = stage.clientHeight;
    renderer.setSize(w, h, false);
    const viewH = (overview ? (w < 700 ? 19 : 15.5) : (w < 700 ? 10.5 : 9.6)) / zoom, aspect = w / h;
    Object.assign(camera, {left: -viewH * aspect / 2, right: viewH * aspect / 2, top: viewH / 2, bottom: -viewH / 2});
    camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(stage);

// ── models ────────────────────────────────────────────────────────────────
const gltfLoader = new GLTFLoader();
const cache = new Map();
function load(name) {
    if (cache.has(name)) return cache.get(name);
    let job;
    if (name.startsWith('furniture/')) {   // the furniture kit comes as OBJ with a material file
        const base = CFG.models + 'furniture/', file = name.slice(10);
        job = new MTLLoader().setPath(base).loadAsync(file + '.mtl').then(m => {
            m.preload();
            return new OBJLoader().setMaterials(m).setPath(base).loadAsync(file + '.obj');
        }).then(obj => ({scene: obj, animations: []}));
    } else job = gltfLoader.loadAsync(CFG.models + name + '.glb');
    cache.set(name, job);
    return job;
}
const BLOCK = [];          // footprints the walker cannot enter: boxes {x, z, hx, hz} or ellipses {x, z, rx, rz, round}
const LAMPS = [];          // lamp heads, lit in the evening
async function put(name, x, z, rot = 0, opts = {}) {
    const gltf = await load(name);
    const obj = gltf.scene.clone(true);
    obj.position.set(x, opts.y || 0, z);
    obj.rotation.y = rot;
    if (opts.scale) obj.scale.setScalar(opts.scale);
    obj.traverse(o => {
        if (!o.isMesh) return;
        o.castShadow = opts.shadow !== false; o.receiveShadow = true;
        // Some kits mark every material fully metallic, which looks black without reflections: make them matte.
        [].concat(o.material).forEach(m => { if (m && m.metalness > .2) { m.metalness = 0; m.roughness = .85; } });
        if (opts.tint != null) {   // each building gets its own colour wash, on its own copy of the material
            o.material = Array.isArray(o.material) ? o.material.map(m => m.clone()) : o.material.clone();
            [].concat(o.material).forEach(m => m.color && m.color.multiply(new THREE.Color(opts.tint)));
        }
    });
    (opts.parent || scene).add(obj);
    if (opts.block !== false) {
        const box = new THREE.Box3().setFromObject(obj);
        const pad = opts.pad ?? .06;
        BLOCK.push({x: (box.min.x + box.max.x) / 2, z: (box.min.z + box.max.z) / 2,
                    hx: (box.max.x - box.min.x) / 2 + pad, hz: (box.max.z - box.min.z) / 2 + pad});
    }
    return obj;
}

// ── the ground ────────────────────────────────────────────────────────────
const mat = c => new THREE.MeshStandardMaterial({color: c, roughness: .95});
function slab() {
    const pc = document.createElement('canvas'); pc.width = pc.height = 256;
    const pg = pc.getContext('2d');
    pg.fillStyle = '#ebe7df'; pg.fillRect(0, 0, 256, 256);
    for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) {
        const shade = 228 + ((x * 7 + y * 13) % 5) * 2;
        pg.fillStyle = `rgb(${shade + 6},${shade + 3},${shade - 3})`;
        pg.fillRect(x * 64 + 1.5, y * 64 + 1.5, 61, 61);
    }
    const paving = new THREE.CanvasTexture(pc);
    paving.wrapS = paving.wrapT = THREE.RepeatWrapping; paving.repeat.set((W + .4) * 2, (D + .4) * 2);
    paving.colorSpace = THREE.SRGBColorSpace; paving.anisotropy = 4;
    const top = new THREE.MeshStandardMaterial({map: paving, roughness: .95});
    const base = new THREE.Mesh(new THREE.BoxGeometry(W + .4, .5, D + .4), [mat(0xcfc6b8), mat(0xcfc6b8), top, mat(0xb8ae9f), mat(0xd9d1c4), mat(0xc6bcad)]);
    base.position.set(W / 2, -.25, D / 2);
    base.receiveShadow = true;
    scene.add(base);
    const c = document.createElement('canvas'); c.width = c.height = 128;
    const g = c.getContext('2d'), grd = g.createRadialGradient(64, 64, 10, 64, 64, 64);
    grd.addColorStop(0, EVENING ? 'rgba(0,0,10,.45)' : 'rgba(20,40,60,.32)'); grd.addColorStop(1, 'rgba(20,40,60,0)');
    g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
    const shade = new THREE.Mesh(new THREE.PlaneGeometry(W * 1.7, D * 1.7), new THREE.MeshBasicMaterial({map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false}));
    shade.rotation.x = -Math.PI / 2; shade.position.set(W / 2 + .8, -.52, D / 2 + .8);
    scene.add(shade);
}
function lawn(x0, z0, x1, z1, color = 0x9cc77f) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(x1 - x0, .06, z1 - z0), mat(color));
    m.position.set((x0 + x1) / 2, .03, (z0 + z1) / 2); m.receiveShadow = true;
    const edge = new THREE.Mesh(new THREE.BoxGeometry(x1 - x0 + .08, .05, z1 - z0 + .08), mat(0xd8d0c2));
    edge.position.set((x0 + x1) / 2, .02, (z0 + z1) / 2); edge.receiveShadow = true;
    scene.add(m, edge);
}
function pond(x, z, rx, rz) {
    const rim = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, .08, 48), mat(0xcfc7ba));
    rim.scale.set(rx + .08, 1, rz + .08); rim.position.set(x, .06, z); rim.receiveShadow = true;
    const water = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, .06, 48),
        new THREE.MeshStandardMaterial({color: EVENING ? 0x3e5f85 : 0x86bfdc, roughness: .12, metalness: .08}));
    water.scale.set(rx, 1, rz); water.position.set(x, .085, z); water.receiveShadow = true;
    scene.add(rim, water);
    BLOCK.push({x, z, rx: rx + .1, rz: rz + .1, round: true});
}
function path(points, width = .26) {   // a gravel path through the park
    const m = mat(0xddd2bd);
    for (let i = 1; i < points.length; i++) {
        const [ax, az] = points[i - 1], [bx, bz] = points[i];
        const len = Math.hypot(bx - ax, bz - az);
        const seg = new THREE.Mesh(new THREE.BoxGeometry(width, .065, len + width), m);
        seg.position.set((ax + bx) / 2, .04, (az + bz) / 2);
        seg.rotation.y = Math.atan2(bx - ax, bz - az);
        seg.receiveShadow = true;
        scene.add(seg);
    }
}

// ── things that show the learner's progress ──────────────────────────────
// One banner per subject in front of the academy: it fills from the bottom as cards are learned.
function subjectBanners() {
    const subs = (STATE.subjects || []).slice(0, 6);
    const colours = [0x2f8fd8, 0x3fae74, 0xd9546b, 0xe0a43a, 0x7a5cc2, 0x2aa198];
    subs.forEach((s, i) => {
        const x = 1.35 + i * .42 + (i >= 2 ? .45 : 0), z = 3.95;   // leave the door free
        const pole = new THREE.Mesh(new THREE.CylinderGeometry(.012, .012, .62, 8), mat(0x6b6f76));
        pole.position.set(x, .31, z); pole.castShadow = true;
        const back = new THREE.Mesh(new THREE.BoxGeometry(.2, .32, .012), mat(0xf4f1ea));
        back.position.set(x + .11, .44, z); back.castShadow = true;
        const share = s.total ? Math.max(.06, s.learned / s.total) : .06;
        const fill = new THREE.Mesh(new THREE.BoxGeometry(.2, .32 * share, .014), mat(colours[i % colours.length]));
        fill.position.set(x + .11, .28 + .32 * share / 2, z + .002);
        scene.add(pole, back, fill);
        BLOCK.push({x: x + .08, z, hx: .14, hz: .06});
    });
}
// What the learner bought in the shop at home, placed in town.
const DECOR = {
    street_trees: () => [[4.15, 4.55], [10.15, 4.6], [15.25, 4.6], [.6, 4.6]].map(([x, z]) => Promise.all([
        put('nature/pot_large', x, z, 0, {scale: .55, pad: .02}), put('nature/tree_small', x, z, 0, {scale: .45, block: false, y: .1})])),
    park_benches: () => [put('furniture/bench', 5.25, 9.0, Math.PI / 2, {scale: .06, pad: .02}), put('furniture/bench', 1.2, 12.6, 0, {scale: .06, pad: .02})],
    park_lamps: () => [[2.0, 8.6], [6.9, 12.0], [5.4, 11.0]].map(([x, z]) => { LAMPS.push([x, z, .7]); return put('roads/light-square', x, z, 0, {pad: .03}); }),
    fairy_lights: () => { fairyLights(); return []; },
    market_stall: () => [put('commercial/detail-parasol-a', 15.6, 8.6, 0, {pad: .03}), put('cars/box', 15.6, 8.95, 0, {scale: .16, pad: .02})],
    flags: () => { flags(); return []; },
};
function fairyLights() {   // a string of small bulbs above the café terrace
    const colours = [0xff7a7a, 0xffd166, 0x7be3a8, 0x7ab8ff];
    const geo = new THREE.SphereGeometry(.022, 8, 6);
    for (let i = 0; i <= 18; i++) {
        const t = i / 18, x = 7.55 + t * 2.0, y = .78 - Math.sin(t * Math.PI) * .12;
        const b = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({color: colours[i % 4]}));
        b.position.set(x, y, 4.95); scene.add(b);
    }
    for (const x of [7.55, 9.55]) {
        const p = new THREE.Mesh(new THREE.CylinderGeometry(.012, .012, .8, 6), mat(0x55585e));
        p.position.set(x, .4, 4.95); p.castShadow = true; scene.add(p);
    }
    if (EVENING) { const l = new THREE.PointLight(0xffd7a0, 1.2, 2.2, 1.6); l.position.set(8.55, .7, 4.95); scene.add(l); }
}
function flags() {   // Finnish flags on the academy roof
    const c = document.createElement('canvas'); c.width = 72; c.height = 44;
    const g = c.getContext('2d');
    g.fillStyle = '#fff'; g.fillRect(0, 0, 72, 44); g.fillStyle = '#1f4fa0'; g.fillRect(20, 0, 12, 44); g.fillRect(0, 16, 72, 12);
    const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
    for (const x of [1.55, 3.25]) {
        const p = new THREE.Mesh(new THREE.CylinderGeometry(.01, .01, .5, 6), mat(0xdadde2));
        p.position.set(x, 1.95, 2.4); p.castShadow = true;
        const f = new THREE.Mesh(new THREE.PlaneGeometry(.26, .16, 6, 1), new THREE.MeshStandardMaterial({map: tex, side: THREE.DoubleSide, roughness: .8}));
        f.position.set(x + .13, 2.1, 2.4); f.castShadow = true;
        f.userData.wave = true;
        scene.add(p, f);
        waving.push(f);
    }
}
const waving = [];

// ── building the district ────────────────────────────────────────────────
async function buildDistrict(progress) {
    slab();
    lawn(.25, .25, W - .25, 1.75);                 // green behind the shops
    lawn(.3, 7.05, 9.3, D - .25);                  // the park
    lawn(14.2, 11.0, W - .25, D - .25, 0xa6cd8a);  // the garden at home
    pond(2.9, 10.3, 1.35, .85);
    path([[4.0, 7.1], [4.6, 9.0], [5.8, 10.4], [7.6, 12.6], [7.6, D - .3]]);
    path([[4.6, 9.0], [7.9, 8.4], [9.25, 8.4]]);
    path([[5.8, 10.4], [4.2, 11.6], [1.0, 12.4]]);
    const jobs = [];
    const add = j => { jobs.push(j); return j; };
    // streets: the main street with two zebra crossings, and the side street south
    for (let x = 0; x < W; x++) {
        const name = x === SIDE_X ? 'roads/road-intersection' : (x === 4 || x === 14) ? 'roads/road-crossing' : 'roads/road-straight';
        add(put(name, x + .5, ROAD_Z + .5, x === SIDE_X ? Math.PI : (x === 4 || x === 14) ? Math.PI / 2 : 0, {block: false, shadow: false}));
    }
    for (let z = ROAD_Z + 1; z < D; z++) add(put(z === D - 1 ? 'roads/road-end' : 'roads/road-straight', SIDE_X + .5, z + .5, Math.PI / 2, {block: false, shadow: false}));
    // the places, each with its own colour, and the skyline behind them
    for (const p of PLACES) if (p.model) add(put(p.model, p.at[0], p.at[1], p.rot || 0, {pad: .1, tint: p.tint}).then(o => { o.userData.place = p; p.obj = o; }));
    for (const [m, x, z] of BACKDROP) add(put(m, x, z, 0, {pad: .1, tint: 0xe9ecef}));
    // café and bakery fronts
    add(put('commercial/detail-awning-wide', 8.55, 3.57, 0, {block: false}));
    add(put('commercial/detail-awning-wide', 16.4, 3.57, 0, {block: false, tint: 0xffd2a8}));
    for (const [x, z] of [[7.75, 4.9], [9.35, 4.9]]) {
        add(put('furniture/tableRound', x, z, 0, {scale: .06, pad: .02}));
        add(put('furniture/chairRounded', x - .22, z, Math.PI / 2, {scale: .06, block: false}));
        add(put('furniture/chairRounded', x + .22, z, -Math.PI / 2, {scale: .06, block: false}));
    }
    add(put('commercial/detail-parasol-a', 7.75, 4.9, 0, {block: false}));
    add(put('commercial/detail-parasol-b', 9.35, 4.9, 0, {block: false}));
    // the market square: stalls under parasols, crates of fruit
    const market = new THREE.Group(); market.userData.place = PLACES.find(p => p.key === 'market'); scene.add(market);
    market.userData.place.obj = market;
    for (const [x, z, m] of [[12.9, 9.0, 'a'], [14.9, 9.0, 'b']]) {
        add(put('commercial/detail-parasol-' + m, x, z, 0, {pad: .05, parent: market}));
        add(put('cars/box', x - .12, z + .05, .3, {scale: .16, block: false, parent: market}));
        add(put('cars/box', x + .14, z + .02, -.2, {scale: .16, block: false, parent: market}));
    }
    for (const [x, z, f] of [[13.5, 8.7, 'flower_redA'], [14.3, 8.7, 'flower_yellowA']]) add(put('nature/' + f, x, z, 0, {scale: .5, block: false, parent: market}));
    // the bus stop on the side street
    const bus = new THREE.Group(); bus.userData.place = PLACES.find(p => p.key === 'bus'); scene.add(bus); bus.userData.place.obj = bus;
    add(put('roads/road-sign-street', 11.0, 8.05, Math.PI / 2, {pad: .03, parent: bus}));
    add(put('furniture/bench', 11.15, 8.6, -Math.PI / 2, {scale: .06, pad: .02, parent: bus}));
    add(put('commercial/detail-overhang', 11.3, 8.6, -Math.PI / 2, {block: false, parent: bus}));
    // lamps along the main street, facing the road
    for (const x of [1, 3.6, 7.0, 13.0, 17.2]) { add(put('roads/light-curved', x, ROAD_Z - .38, Math.PI, {pad: .03})); LAMPS.push([x, ROAD_Z - .2, .62]); }
    for (const x of [2.6, 6.2, 12.0, 15.8]) { add(put('roads/light-curved', x, ROAD_Z + 1.38, 0, {pad: .03})); LAMPS.push([x, ROAD_Z + 1.2, .62]); }
    add(put('roads/traffic-light', SIDE_X - .38, ROAD_Z - .38, Math.PI, {pad: .03}));
    // the park: trees, bushes, flower beds, a monument, lilies on the pond
    const trees = [[.9, 7.6, 'tree_default'], [1.9, 8.0, 'tree_fat'], [.8, 11.6, 'tree_oak'], [6.4, 7.6, 'tree_detailed'],
                   [8.6, 7.7, 'tree_default'], [8.7, 10.2, 'tree_fat'], [8.5, 13.2, 'tree_oak'], [5.9, 12.9, 'tree_small'],
                   [2.6, 13.1, 'tree_detailed'], [7.2, 9.6, 'tree_oak'], [4.0, 13.4, 'tree_fat'],
                   [11.9, 13.3, 'tree_default'], [13.2, 12.4, 'tree_small'], [17.4, 11.5, 'tree_fat'],
                   [1.5, .8, 'tree_default'], [5.9, .75, 'tree_oak'], [8.9, .8, 'tree_fat'], [11.7, .75, 'tree_detailed'], [15.4, .8, 'tree_oak']];
    for (const [x, z, t] of trees) add(put('nature/' + t, x, z, Math.random() * 6, {scale: .5, pad: .02}));
    const bushes = [[1.4, 9.2], [4.6, 8.0], [6.5, 11.6], [3.3, 12.2], [7.9, 11.2], [12.2, 11.4], [16.9, 13.5], [14.6, 13.5], [.6, 9.9]];
    bushes.forEach(([x, z], i) => add(put('nature/' + ['plant_bushLarge', 'plant_bush', 'plant_bushSmall'][i % 3], x, z, i, {scale: .6, pad: .0})));
    const flowerBed = (x, z) => ['flower_redA', 'flower_yellowA', 'flower_purpleA', 'flower_redB', 'flower_yellowB'].forEach((f, i) =>
        add(put('nature/' + f, x + (i % 3) * .14 - .14, z + Math.floor(i / 3) * .14, i, {scale: .45, block: false})));
    flowerBed(5.0, 7.55); flowerBed(6.7, 10.9); flowerBed(2.2, 11.95); flowerBed(15.2, 11.6);
    add(put('nature/statue_column', 5.85, 10.4, 0, {scale: .38, pad: .05}));
    for (const [x, z, l] of [[2.3, 10.0, 'lily_large'], [3.4, 10.6, 'lily_small'], [3.1, 9.8, 'lily_small']]) add(put('nature/' + l, x, z, x, {scale: .5, block: false, y: .09}));
    for (const [x, z] of [[1.2, 4.55], [3.6, 4.55], [13.0, 4.6], [17.6, 4.6]]) add(put('suburban/planter', x, z, 0, {pad: .02}));
    // home: fence, drive, a parked car
    add(put('suburban/fence-1x4', 16.1, 10.95, 0, {pad: .02}));
    add(put('suburban/driveway-short', 14.6, 11.9, Math.PI / 2, {block: false}));
    add(put('cars/hatchback-sports', 14.6, 12.4, 0, {scale: CAR_SCALE, pad: .03}));
    // the learner's decorations
    for (const code of (STATE.decor && STATE.decor.codes) || []) if (DECOR[code]) [].concat(DECOR[code]()).forEach(j => j && add(j));
    let done = 0;
    jobs.forEach(j => j.then(() => progress(++done / jobs.length)));
    await Promise.all(jobs);
    subjectBanners();
    if (EVENING) {
        const bulb = new THREE.MeshBasicMaterial({color: 0xffe2a8});
        for (const [x, z, y] of LAMPS) {
            const l = new THREE.PointLight(0xffc77a, 2.2, 2.4, 1.6);
            l.position.set(x, y, z); scene.add(l);
            const b = new THREE.Mesh(new THREE.SphereGeometry(.035, 12, 8), bulb);
            b.position.set(x, y + .02, z); scene.add(b);
        }
    }
}

// ── walking: a grid over the district, A* with corner checks, then straightened ──
const CELL = .25, GW = Math.round(W / CELL), GD = Math.round(D / CELL);
let grid = null;
function buildGrid() {
    grid = new Uint8Array(GW * GD);
    for (let gz = 0; gz < GD; gz++) for (let gx = 0; gx < GW; gx++) {
        const x = (gx + .5) * CELL, z = (gz + .5) * CELL;
        grid[gz * GW + gx] = BLOCK.some(b => b.round ? ((x - b.x) / b.rx) ** 2 + ((z - b.z) / b.rz) ** 2 < 1
                                               : Math.abs(x - b.x) < b.hx && Math.abs(z - b.z) < b.hz) ? 1 : 0;
    }
    for (const p of PLACES) {   // the doorstep is always walkable
        const gx = Math.floor(p.door[0] / CELL), gz = Math.floor(p.door[1] / CELL);
        for (let dz = -1; dz <= 1; dz++) for (let dx = -1; dx <= 1; dx++) if (gx + dx >= 0 && gz + dz >= 0) grid[(gz + dz) * GW + gx + dx] = 0;
    }
}
const free = (gx, gz) => gx >= 0 && gz >= 0 && gx < GW && gz < GD && !grid[gz * GW + gx];
function nearestFree(gx, gz) {
    for (let r = 0; r < 12; r++) for (let dz = -r; dz <= r; dz++) for (let dx = -r; dx <= r; dx++)
        if (free(gx + dx, gz + dz)) return [gx + dx, gz + dz];
    return null;
}
function findPath(from, to) {
    let [sx, sz] = [Math.floor(from.x / CELL), Math.floor(from.z / CELL)];
    let goal = [Math.floor(to.x / CELL), Math.floor(to.z / CELL)];
    if (!free(sx, sz)) [sx, sz] = nearestFree(sx, sz) || [sx, sz];
    if (!free(...goal)) goal = nearestFree(...goal);
    if (!goal) return [];
    const key = (x, z) => z * GW + x, start = key(sx, sz), end = key(...goal);
    const g = new Map([[start, 0]]), prev = new Map(), open = [[0, sx, sz]], closed = new Set();
    const h = (x, z) => Math.hypot(x - goal[0], z - goal[1]);
    while (open.length) {
        let bi = 0;
        for (let i = 1; i < open.length; i++) if (open[i][0] < open[bi][0]) bi = i;
        const [, x, z] = open.splice(bi, 1)[0], k = key(x, z);
        if (k === end) break;
        if (closed.has(k)) continue;
        closed.add(k);
        for (const [dx, dz] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]]) {
            const nx = x + dx, nz = z + dz;
            if (!free(nx, nz) || (dx && dz && (!free(x + dx, z) || !free(x, z + dz)))) continue;
            const nk = key(nx, nz), ng = g.get(k) + (dx && dz ? 1.414 : 1);
            if (ng < (g.get(nk) ?? Infinity)) { g.set(nk, ng); prev.set(nk, k); open.push([ng + h(nx, nz), nx, nz]); }
        }
    }
    if (!prev.has(end) && end !== start) return [];
    const cells = [];
    for (let k = end; k !== undefined && k !== start; k = prev.get(k)) cells.unshift(k);
    const pts = cells.map(k => new THREE.Vector3((k % GW + .5) * CELL, 0, (Math.floor(k / GW) + .5) * CELL));
    const clear = (a, b) => {
        const n = Math.ceil(a.distanceTo(b) / (CELL / 3));
        for (let i = 1; i < n; i++) { const p = a.clone().lerp(b, i / n); if (!free(Math.floor(p.x / CELL), Math.floor(p.z / CELL))) return false; }
        return true;
    };
    const out = [];
    let cur = from.clone().setY(0);
    for (let i = 0; i < pts.length;) {
        let j = pts.length - 1;
        while (j > i && !clear(cur, pts[j])) j--;
        out.push(pts[j]); cur = pts[j]; i = j + 1;
    }
    if (out.length && free(Math.floor(to.x / CELL), Math.floor(to.z / CELL))) out[out.length - 1] = to.clone().setY(0);
    return out;
}

// ── people and cars ───────────────────────────────────────────────────────
class Person {
    constructor(gltf, x, z) {
        this.obj = SkeletonUtils.clone(gltf.scene);
        this.obj.scale.setScalar(PERSON_SCALE);
        this.obj.position.set(x, 0, z);
        this.obj.traverse(o => { if (o.isMesh) o.castShadow = true; });
        scene.add(this.obj);
        this.mixer = new THREE.AnimationMixer(this.obj);
        this.actions = Object.fromEntries(gltf.animations.map(a => [a.name, this.mixer.clipAction(a)]));
        this.state = null; this.play('idle');
        this.path = []; this.speed = 1.05; this.yaw = 0;
    }
    play(name, fade = .2) {
        if (this.state === name || !this.actions[name]) return;
        const next = this.actions[name];
        next.reset().fadeIn(fade).play();
        if (this.state && this.actions[this.state]) this.actions[this.state].fadeOut(fade);
        this.state = name;
    }
    gesture(name) {   // a one-off movement, then back to standing
        const a = this.actions[name];
        if (!a) return;
        a.reset().setLoop(THREE.LoopOnce, 1).fadeIn(.15).play(); a.clampWhenFinished = false;
        setTimeout(() => a.fadeOut(.3), (a.getClip().duration - .3) * 1000);
    }
    face(dx, dz) { this.yaw = Math.atan2(dx, dz); }
    update(dt) {
        if (this.path.length) {
            const p = this.obj.position, t = this.path[0], d = new THREE.Vector3(t.x - p.x, 0, t.z - p.z), dist = d.length();
            if (dist < .04) { this.path.shift(); if (!this.path.length && this.arrived) this.arrived(); }
            else { p.addScaledVector(d.normalize(), Math.min(dist, this.speed * dt)); this.face(d.x, d.z); this.play('walk'); }
        } else if (this.state === 'walk') this.play('idle');
        let diff = this.yaw - this.obj.rotation.y;
        diff = Math.atan2(Math.sin(diff), Math.cos(diff));
        this.obj.rotation.y += diff * Math.min(1, dt * 10);
        this.mixer.update(dt);
    }
}
let me = null;
const townsfolk = [], npcs = {}, cars = [];
async function addPeople() {
    const loop = async (model, pts, delay) => {
        const p = new Person(await load('people/' + model), pts[0][0], pts[0][1]);
        p.speed = .65;
        let i = 0;
        const next = () => { i = (i + 1) % pts.length; p.path = [new THREE.Vector3(pts[i][0], 0, pts[i][1])]; };
        p.arrived = () => setTimeout(next, 900 + Math.random() * 2500);
        setTimeout(next, delay);
        townsfolk.push(p);
    };
    const jobs = [
        loop('character-male-e', [[.6, 5.15], [9.4, 5.15], [9.4, 5.3], [.6, 5.3]], 600),
        loop('character-female-a', [[11.0, 7.1], [17.6, 7.1], [17.6, 7.2], [11.0, 7.2]], 1600),
        loop('character-male-f', [[4.1, 7.3], [4.6, 9.0], [5.8, 10.4], [7.5, 12.5], [5.8, 10.4], [4.6, 9.0]], 2600),
    ];
    for (const p of PLACES) if (p.npc) jobs.push(load('people/' + p.npc.model).then(g => {
        const n = new Person(g, p.npc.at[0], p.npc.at[1]); n.yaw = n.obj.rotation.y = p.npc.yaw; npcs[p.key] = n; townsfolk.push(n);
    }));
    await Promise.all(jobs);
}
async function addCars() {
    const models = ['cars/sedan', 'cars/taxi', 'cars/van', 'cars/suv'];
    for (let i = 0; i < 4; i++) {
        const east = i % 2 === 0;
        const car = await put(models[i], east ? -1 : W + 1, ROAD_Z + (east ? .72 : .28), east ? Math.PI / 2 : -Math.PI / 2, {scale: CAR_SCALE, block: false});
        cars.push({obj: car, east, speed: .9 + i * .12, wait: 2 + i * 3.5});
    }
}
function driveCars(dt) {
    for (const c of cars) {
        if (c.wait > 0) { c.wait -= dt; c.obj.visible = false; continue; }
        c.obj.visible = true;
        // slow down near the zebra crossings when someone is on them
        let v = c.speed;
        if (me) for (const cx of [4.5, 14.5]) {
            const ahead = c.east ? cx - c.obj.position.x : c.obj.position.x - cx;
            if (ahead > 0 && ahead < 1.1 && Math.abs(me.obj.position.x - cx) < .55 && Math.abs(me.obj.position.z - (ROAD_Z + .5)) < .55) v = 0;
        }
        c.obj.position.x += (c.east ? 1 : -1) * v * dt;
        if (c.east ? c.obj.position.x > W + .6 : c.obj.position.x < -.6) {
            c.obj.position.x = c.east ? -.6 : W + .6;
            c.wait = 3 + Math.random() * 6;
        }
    }
}

// ── labels over places ────────────────────────────────────────────────────
const labels = new Map();
function makeLabels() {
    const box = $('t3-labels'); box.innerHTML = '';
    for (const p of PLACES) {
        const el = document.createElement('div');
        el.className = 't3-label';
        el.style.setProperty('--c', p.c);
        el.innerHTML = '<i class="fas"></i><span><b></b><small></small></span>';
        box.append(el);
        const top = p.obj ? new THREE.Box3().setFromObject(p.obj).max.y : .9;
        labels.set(p.key, {el, pos: new THREE.Vector3(p.at[0], Math.max(top, .9) + .18, p.at[1])});
    }
    updateLabels();
}
function updateLabels() {
    for (const p of PLACES) {
        const l = labels.get(p.key);
        if (!l) continue;
        const info = placeInfo(p);
        l.el.classList.toggle('locked', !!info.locked);
        l.el.querySelector('i').className = 'fas ' + (info.locked ? 'fa-lock' : p.icon);
        l.el.querySelector('b').textContent = p.title;
        l.el.querySelector('small').textContent = info.locked ? `Opens at level ${info.level}` : info.done_today ? p.sub.split(' · ')[0] + ' · done today' : p.sub;
    }
}
const v3 = new THREE.Vector3();
function placeLabels() {
    const w = stage.clientWidth, h = stage.clientHeight;
    $('t3-labels').classList.toggle('compact', overview || zoom < .9 || w < 700);
    for (const [key, l] of labels) {
        v3.copy(l.pos).project(camera);
        l.el.style.left = ((v3.x + 1) / 2 * w) + 'px';
        l.el.style.top = ((1 - v3.y) / 2 * h) + 'px';
        l.el.classList.toggle('hot', !!hovered && hovered.key === key);
    }
}

// ── input ─────────────────────────────────────────────────────────────────
const ray = new THREE.Raycaster(), ptr = new THREE.Vector2();
const ground = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
let hovered = null, goal = null, panelOpen = false;
function pick(ev) {
    const r = renderer.domElement.getBoundingClientRect();
    ptr.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ptr, camera);
    const hit = ray.intersectObjects(PLACES.map(p => p.obj).filter(Boolean), true)[0];
    let place = null;
    if (hit) for (let o = hit.object; o; o = o.parent) if (o.userData.place) { place = o.userData.place; break; }
    const at = new THREE.Vector3();
    ray.ray.intersectPlane(ground, at);
    return {place, at};
}
const doorOf = p => new THREE.Vector3(p.door[0], 0, p.door[1]);
function walkTo(point, place = null) {
    if (!me) return;
    goal = place;
    me.path = findPath(me.obj.position, point);
    if (!me.path.length && place && me.obj.position.distanceTo(doorOf(place)) < .6) enter(place);
    $('t3-hint').classList.add('gone');
}
let downAt = null;
const canvas = renderer.domElement;
const touches = new Map();
canvas.addEventListener('pointerdown', e => { downAt = [e.clientX, e.clientY]; touches.set(e.pointerId, [e.clientX, e.clientY]); });
canvas.addEventListener('pointerup', e => {
    touches.delete(e.pointerId);
    if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 8 || (panelOpen && innerWidth < 700)) return;
    const {place, at} = pick(e);
    if (place) walkTo(doorOf(place), place);
    else if (at.x > 0 && at.z > 0 && at.x < W && at.z < D) { walkTo(at); marker(at); }
});
canvas.addEventListener('pointercancel', e => touches.delete(e.pointerId));
canvas.addEventListener('pointermove', e => {
    if (touches.size === 2 && touches.has(e.pointerId)) {   // pinch to zoom
        const [a, b] = [...touches.values()], before = Math.hypot(a[0] - b[0], a[1] - b[1]);
        touches.set(e.pointerId, [e.clientX, e.clientY]);
        const [c, d] = [...touches.values()], after = Math.hypot(c[0] - d[0], c[1] - d[1]);
        if (before) { zoom = THREE.MathUtils.clamp(zoom * after / before, .7, 2.2); resize(); downAt = null; }
        return;
    }
    if (e.pointerType !== 'mouse') return;
    hovered = pick(e).place;
    stage.classList.toggle('pointing', !!hovered);
});
canvas.addEventListener('wheel', e => { e.preventDefault(); zoom = THREE.MathUtils.clamp(zoom * (e.deltaY > 0 ? .9 : 1.1), .7, 2.2); resize(); }, {passive: false});
const keys = new Set();
const typing = el => el && el.matches && el.matches('input, textarea, select, [contenteditable="true"]');
addEventListener('keydown', e => {
    if (typing(document.activeElement)) return;
    if (e.key === 'Escape' && panelOpen) { closePanel(); return; }
    if (panelOpen) return;
    const k = e.key.toLowerCase();
    if (['arrowup', 'arrowdown', 'arrowleft', 'arrowright', 'w', 'a', 's', 'd'].includes(k)) { keys.add(k); e.preventDefault(); }
    if ((k === 'e' || k === 'enter') && nearby) { e.preventDefault(); enter(nearby); }
});
addEventListener('keyup', e => keys.delete(e.key.toLowerCase()));
addEventListener('blur', () => keys.clear());
let markerMesh = null;
function marker(at) {
    if (!markerMesh) {
        markerMesh = new THREE.Mesh(new THREE.RingGeometry(.08, .13, 32), new THREE.MeshBasicMaterial({color: 0x2f8fd8, transparent: true}));
        markerMesh.rotation.x = -Math.PI / 2; scene.add(markerMesh);
    }
    markerMesh.position.set(at.x, .1, at.z); markerMesh.scale.setScalar(1); markerMesh.material.opacity = 1; markerMesh.visible = true;
}

// ── panels ────────────────────────────────────────────────────────────────
const panel = $('t3-panel');
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
const icon = name => { const i = document.createElement('i'); i.className = 'fas ' + name; i.setAttribute('aria-hidden', 'true'); return i; };
function openPanel(place, title, sub, build) {
    $('t3-p-icon').style.setProperty('--c', place ? place.c : '#2f8fd8');
    $('t3-p-icon').replaceChildren(icon(place ? place.icon : 'fa-map'));
    $('t3-p-title').textContent = title;
    $('t3-p-sub').textContent = sub;
    const body = $('t3-p-body'); body.replaceChildren();
    build(body);
    panel.hidden = false; panelOpen = true;
    Sound.open();
    setTimeout(() => (panel.querySelector('.t3-p-body button, .t3-p-body a') || panel.querySelector('[data-close]')).focus({preventScroll: true}), 40);
}
function closePanel() {
    panel.hidden = true; panelOpen = false;
    clearInterval(Talk.typing);
}
panel.addEventListener('click', e => { if (e.target.closest('[data-close]')) closePanel(); });
panel.addEventListener('keydown', e => {   // keep keyboard focus inside the panel
    if (e.key !== 'Tab') return;
    const f = [...panel.querySelectorAll('button:not([disabled]), a[href]')].filter(n => n.offsetParent !== null);
    const i = f.indexOf(document.activeElement);
    if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus(); }
});
let toastTimer = 0;
function toast(text) {
    const t = $('t3-toast'); t.textContent = text; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 3000);
}
function item(iconName, title, small, action, done = false, colour = null) {
    const li = el('li', 't3-item' + (done ? ' done' : ''));
    const ic = el('span', 'ic'); ic.append(icon(iconName)); if (colour) ic.style.color = colour;
    const main = el('span', 'main'); main.append(el('b', '', title), el('small', '', small));
    li.append(ic, main);
    if (action) li.append(action);
    return li;
}
const linkBtn = (text, href, cls = 't3-btn sm') => { const a = el('a', cls, text); a.href = href; return a; };
const btn = (text, onClick, cls = 't3-btn') => { const b = el('button', cls, text); b.type = 'button'; b.addEventListener('click', onClick); return b; };
const bar = share => { const b = el('span', 't3-bar'); const f = el('i'); f.style.width = Math.round(share * 100) + '%'; b.append(f); return b; };

function enter(place) {
    if (!me) return;
    me.path = []; goal = null;
    me.face(place.at[0] - me.obj.position.x, place.at[1] - me.obj.position.z);
    const info = placeInfo(place);
    if (info.locked) { toast(`${place.title} opens at level ${info.level}. Practise and talk in town to level up.`); Sound.wrong(); return; }
    if (place.scene) return Talk.start(place);
    ({academy: showAcademy, library: showLibrary, practice: showPractice, quests: showQuests, home: showHome})[place.panel](place);
}

function showAcademy(place) {
    openPanel(place, place.title, 'The academy · every subject you study', body => {
        body.append(el('p', 't3-muted', 'The banners outside are your subjects: each one fills as you learn its cards.'));
        const ul = el('ul', 't3-list');
        if (!STATE.subjects.length) ul.append(item('fa-plus', 'No subjects yet', 'Add a subject and your first lesson in Subjects.'));
        for (const s of STATE.subjects) {
            const li = item(s.icon, s.name, `${s.subject} · ${s.learned} of ${s.total} cards learned · ${s.kept} kept long-term`, linkBtn('Open', s.url));
            li.querySelector('.main').append(bar(s.total ? s.learned / s.total : 0));
            ul.append(li);
        }
        body.append(ul, el('h3', '', 'Lessons'));
        const ls = el('ul', 't3-list');
        if (!STATE.lessons.length) ls.append(item('fa-book-open', 'No lessons yet', 'Photos, a PDF or typed text become a lesson in a minute.'));
        for (const l of STATE.lessons) {
            const acts = el('span', 't3-row');
            acts.append(btn('Here', () => Drill.start({lesson: l.id, title: l.title}), 't3-btn sm ghost'), linkBtn('Practise', l.practise));
            ls.append(item(l.icon || 'fa-book', l.title, `${l.subject} · ${l.due ? l.due + ' due' : l.new ? l.new + ' new' : 'up to date'}`, acts));
        }
        const row = el('div', 't3-row'); row.append(linkBtn('All subjects', STATE.links.subjects, 't3-btn ghost'));
        body.append(ls, row);
    });
}
function showLibrary(place) {
    openPanel(place, place.title, 'The library · your material, cards and notes', body => {
        body.append(el('p', 't3-muted', 'Everything you added: open a lesson to read its material again, or search all of it.'));
        const ul = el('ul', 't3-list');
        for (const l of STATE.lessons) ul.append(item('fa-file-lines', l.title, `${l.subject} · ${l.total} cards`, linkBtn('Read', l.open, 't3-btn sm ghost')));
        if (!STATE.lessons.length) ul.append(item('fa-file-circle-plus', 'The shelves are empty', 'Your lessons will be here.'));
        const row = el('div', 't3-row');
        row.append(linkBtn('Search the library', STATE.links.library, 't3-btn'), linkBtn('Add a lesson', STATE.links.subjects, 't3-btn ghost'));
        body.append(ul, row);
    });
}
function showPractice(place) {
    const d = STATE.due || {due: 0, new: 0};
    openPanel(place, place.title, 'The practice centre · today’s review', body => {
        const s = el('div', 't3-stats');
        for (const [big, small] of [[String(d.due), 'cards due now'], [String(d.new), 'new cards for today']]) { const c = el('div'); c.append(el('b', '', big), el('small', '', small)); s.append(c); }
        body.append(s, el('p', 't3-muted', 'A quick round here is multiple choice. For typing and verb forms, use all practice modes.'));
        const row = el('div', 't3-row');
        row.append(btn('Practise here', () => Drill.start({title: 'Today’s review'})), linkBtn('All practice modes', STATE.links.review, 't3-btn ghost'));
        body.append(row);
    });
}
function showQuests(place) {
    openPanel(place, place.title, 'Quests and achievements · from your own learning', body => {
        const ul = el('ul', 't3-list');
        if (!STATE.quests.length) ul.append(item('fa-flag', 'No quests yet', 'Quests come once you have lessons to practise or have talked in town.'));
        for (const q of STATE.quests) {
            const li = item(q.done ? 'fa-check' : q.week ? 'fa-calendar-week' : 'fa-flag', q.title,
                            `${q.done ? 'Done' : q.progress + ' of ' + q.target}${q.week ? ' · this week' : ''} · +${q.xp} XP, ${q.coins} coins`, null, q.done);
            li.querySelector('.main').append(bar(q.progress / q.target));
            ul.append(li);
        }
        body.append(ul, el('h3', '', `Achievements · ${STATE.achievements.unlocked} of ${STATE.achievements.total}`));
        const tr = el('ul', 't3-list');
        const tierColour = {bronze: '#b0703f', silver: '#7f8a97', gold: '#c8962e'};
        for (const a of STATE.achievements.recent) tr.append(item(a.icon, a.name, a.tier[0].toUpperCase() + a.tier.slice(1), null, false, tierColour[a.tier]));
        if (!STATE.achievements.recent.length) tr.append(item('fa-trophy', 'None yet', 'Your first answer unlocks the first one.'));
        const row = el('div', 't3-row'); row.append(linkBtn('All achievements', STATE.links.progress, 't3-btn ghost'));
        body.append(tr, row);
    });
}
function showHome(place) {
    openPanel(place, place.title, 'Home · you, your progress and your town', body => {
        const s = el('div', 't3-stats');
        for (const [big, small] of [['Level ' + STATE.me.level, STATE.me.rank], [STATE.me.xp + ' XP', `${STATE.me.into} of ${STATE.me.span} to the next level`],
                                    [String(STATE.me.streak), 'days in a row'], [String(STATE.me.coins), 'coins']]) {
            const c = el('div'); c.append(el('b', '', big), el('small', '', small)); s.append(c);
        }
        const row = el('div', 't3-row');
        row.append(btn('Change character', async () => { closePanel(); await pickCharacter(); }), linkBtn('Progress', STATE.links.progress, 't3-btn ghost'));
        body.append(s, row, el('h3', '', 'Make the town yours'),
                    el('p', 't3-muted', 'Coins come from finished lessons, quests, achievements and new levels, never from clicking around.'));
        const ul = el('ul', 't3-list');
        for (const it of STATE.shop) {
            let action;
            if (it.owned) action = el('span', 't3-tag', 'In town');
            else {
                action = btn(it.locked ? `Level ${it.level}` : `${it.price}`, async () => {
                    action.disabled = true;
                    try { const r = await post(CFG.buy, {item: it.code}); Sound.done(); toast(r.message + ' Look around town.'); await refresh(); location.reload(); }
                    catch (e) { toast(e.message); action.disabled = false; }
                }, 't3-btn sm' + (it.locked || !it.afford ? ' ghost' : ''));
                if (!it.locked) action.prepend(icon('fa-coins'));
                action.disabled = it.locked || !it.afford;
            }
            ul.append(item(it.owned ? 'fa-check' : it.locked ? 'fa-lock' : 'fa-tree', it.name, it.desc, action, it.owned));
        }
        body.append(ul);
    });
}
function showPlaces() {
    openPanel(null, 'The town', 'Pick a place to walk there', body => {
        const row = el('div', 't3-row');
        row.append(btn(overview ? 'Follow me again' : 'See the whole town', () => { overview = !overview; resize(); closePanel(); }, 't3-btn ghost'));
        const ul = el('ul', 't3-list');
        for (const p of PLACES) {
            const info = placeInfo(p);
            ul.append(item(info.locked ? 'fa-lock' : p.icon, p.title, info.locked ? `${p.sub} · opens at level ${info.level}` : p.sub,
                           btn('Go', () => { closePanel(); overview = false; resize(); walkTo(doorOf(p), p); }, 't3-btn sm ghost'), false, p.c));
        }
        body.append(row, ul);
    });
}
$('t3-places-btn').addEventListener('click', () => STATE && showPlaces());
$('t3-quests-btn').addEventListener('click', () => STATE && showQuests(PLACES.find(p => p.key === 'quests')));
$('t3-me').addEventListener('click', () => STATE && showHome(PLACES.find(p => p.key === 'home')));
$('t3-full').addEventListener('click', () => (document.fullscreenElement ? document.exitFullscreen() : root.requestFullscreen?.()));

// ── conversations ─────────────────────────────────────────────────────────
const Talk = {
    async start(place) {
        let data;
        try { data = await post(sceneUrl(place.scene, 'start')); }
        catch (e) { toast(e.status === 403 ? e.message : 'Could not start the conversation. Try again.'); return; }
        Object.assign(this, {place, data, turn: 0, busy: false, npc: npcs[place.key]});
        if (this.npc) { this.npc.face(me.obj.position.x - this.npc.obj.position.x, me.obj.position.z - this.npc.obj.position.z); this.npc.gesture('interact-right'); }
        openPanel(place, data.title, place.sub, body => {
            const npc = el('div', 't3-npc');
            const img = el('img'); img.alt = '';
            if (place.npc) portrait(place.npc.model).then(u => { img.src = u; });
            const who = el('span'); who.append(el('b', '', data.npc.name), el('br'), el('small', 't3-muted', data.npc.role));
            this.steps = el('span', 't3-steps'); data.turns.forEach(() => this.steps.append(el('i')));
            npc.append(img, who, this.steps);
            const goalText = el('p', 't3-muted', data.goal + (data.done_today ? ' Already rewarded today: this round is practice.' : ''));
            const bubble = el('div', 't3-bubble'); this.line = el('p'); this.line.lang = 'fi';
            const listen = btn('', () => this.say(), ''); listen.setAttribute('aria-label', 'Listen'); listen.append(icon('fa-volume-high'));
            bubble.append(this.line, listen);
            this.en = el('p', 't3-en'); this.en.hidden = true;
            const show = btn('Show in English', () => { this.en.hidden = !this.en.hidden; show.textContent = this.en.hidden ? 'Show in English' : 'Hide English'; }, 't3-link');
            this.opts = el('div', 't3-options'); this.fb = el('p', 't3-feedback'); this.result = el('div', 't3-done'); this.result.hidden = true;
            body.append(npc, goalText, bubble, show, this.en, this.opts, this.fb, this.result);
        });
        this.show();
    },
    say() {
        if (!('speechSynthesis' in window)) return;
        const u = new SpeechSynthesisUtterance(this.data.turns[this.turn].say); u.lang = this.data.speech || 'fi-FI'; u.rate = .92;
        speechSynthesis.cancel(); speechSynthesis.speak(u);
    },
    show() {
        const t = this.data.turns[this.turn];
        [...this.steps.children].forEach((s, i) => { s.className = i < this.turn ? 'done' : i === this.turn ? 'now' : ''; });
        clearInterval(this.typing);
        let i = CALM ? t.say.length - 1 : 0;
        this.line.textContent = '';
        this.typing = setInterval(() => { this.line.textContent = t.say.slice(0, ++i); if (i >= t.say.length) clearInterval(this.typing); }, 26);
        this.en.textContent = t.en;
        this.fb.textContent = ''; this.fb.className = 't3-feedback';
        this.opts.replaceChildren();
        t.options.forEach((o, n) => {
            const b = btn('', () => this.answer(n, b), 't3-opt'); b.lang = 'fi';
            b.append(el('kbd', '', String(n + 1)), el('span', '', o));
            this.opts.append(b);
        });
    },
    async answer(n, b) {
        if (this.busy) return;
        this.busy = true;
        let r;
        try { r = await post(sceneUrl(this.place.scene, 'answer'), {turn: this.turn, choice: n}); }
        catch (e) { this.busy = false; toast(e.status === 409 ? 'The conversation started again.' : 'No connection. Try again.'); if (e.status === 409) this.start(this.place); return; }
        const meaning = r.meaning.replace(/[.!?]$/, '');
        if (!r.right) {
            Sound.wrong(); b.classList.add('wrong'); b.disabled = true;
            this.fb.className = 't3-feedback bad'; this.fb.textContent = `That means “${meaning}”. Try another reply.`;
            this.npc && this.npc.gesture('emote-no');
            this.busy = false; return;
        }
        Sound.right(); b.classList.add('right');
        this.opts.querySelectorAll('button').forEach(x => { x.disabled = true; });
        this.fb.className = 't3-feedback ok'; this.fb.textContent = `${['Hyvä!', 'Selvä!', 'Juuri niin!'][this.turn % 3]} “${meaning}”`;
        this.npc && this.npc.gesture('emote-yes');
        setTimeout(() => { this.busy = false; r.done ? this.finish(r) : (this.turn++, this.show()); }, 900);
    },
    async finish(r) {
        Sound.done();
        [...this.steps.children].forEach(s => { s.className = 'done'; });
        this.opts.hidden = true; this.fb.textContent = '';
        const rw = r.reward;
        this.result.append(el('h3', '', 'Conversation complete'), el('p', 't3-muted', `${r.first_try} of ${r.turns} replies right the first time.`));
        const ul = el('ul');
        ul.append(el('li', '', rw && rw.paid ? `+${rw.xp} XP and ${rw.coins} coins` : 'Already rewarded today. Practice still helps you remember.'));
        (rw?.quests || []).forEach(q => ul.append(el('li', '', 'Quest done: ' + q)));
        (rw?.unlocked || []).forEach(a => ul.append(el('li', '', 'Achievement: ' + a.name)));
        if (rw?.level_up) ul.append(el('li', '', 'Level ' + rw.level_up.level + ' reached'));
        const row = el('div', 't3-row');
        const save = btn('Save the phrases as cards', async () => {
            save.disabled = true;
            try { const s = await post(sceneUrl(this.place.scene, 'save')); save.textContent = s.created ? `Saved: ${s.count} cards` : 'Already in your cards'; }
            catch (e) { save.disabled = false; toast(e.message); }
        });
        const leave = btn('Leave', () => {}, 't3-btn ghost'); leave.setAttribute('data-close', '');
        row.append(save, leave);
        this.result.append(ul, row); this.result.hidden = false;
        await refresh();
    },
};

// ── a quick round of the learner's own cards (multiple choice) ───────────
const Drill = {
    ask: {word: 'What does it mean?', concept: 'What does it mean?', phrase: 'Which phrase means this?', sentence: 'Which word fills the gap?', question: 'Choose the answer.'},
    task(c) {
        if (c.kind === 'question') return c.options?.length ? {front: c.front, options: c.options, right: c.options[c.answer]} : null;
        const field = {word: 'en', concept: 'en', phrase: 'front', sentence: 'cloze'}[c.kind];
        if (!field || !c[field]) return null;
        const pool = [...new Set(this.cards.filter(o => o.id !== c.id && o[field] && (o.kind === c.kind || field === 'cloze' && o.kind === 'word'))
            .map(o => field === 'cloze' && o.kind === 'word' ? o.front : o[field]))].filter(x => x.toLowerCase() !== c[field].toLowerCase());
        if (pool.length < 2) return null;
        const options = [...pool.sort(() => Math.random() - .5).slice(0, 2), c[field]].sort(() => Math.random() - .5);
        const front = c.kind === 'phrase' ? c.en : c.kind === 'sentence' ? c.front.split(c.cloze).join('____') : c.front;
        return {front, options, right: c[field], hint: c.kind === 'sentence' ? c.en : ''};
    },
    async start(scope) {
        let d;
        try { d = await getJSON(CFG.due + (scope.lesson ? '?lesson=' + scope.lesson : '')); }
        catch (e) { toast('Could not load your cards.'); return; }
        this.cards = d.cards || []; this.extra = !!d.extra;
        this.queue = this.cards.filter(c => this.task(c)).slice(0, 10);
        if (!this.queue.length) { toast(this.cards.length ? 'These cards need typing or flashcards: use all practice modes.' : 'Nothing to practise right now. Come back later.'); return; }
        this.done = 0; this.xp = 0; this.scope = scope;
        const place = PLACES.find(p => p.key === 'practice');
        openPanel(place, scope.title, this.extra ? 'An extra round · your schedule stays as it is' : 'Multiple choice · graded like any practice', body => {
            this.steps = el('span', 't3-steps'); this.queue.forEach(() => this.steps.append(el('i')));
            this.q = el('p', 't3-muted'); const bubble = el('div', 't3-bubble'); this.front = el('p'); bubble.append(this.front);
            this.hint = el('p', 't3-en'); this.opts = el('div', 't3-options'); this.fb = el('p', 't3-feedback'); this.result = el('div', 't3-done'); this.result.hidden = true;
            const head = el('div', 't3-npc'); head.append(el('b', '', 'Round'), this.steps);
            body.append(head, this.q, bubble, this.hint, this.opts, this.fb, this.result);
        });
        this.next();
    },
    next() {
        [...this.steps.children].forEach((s, i) => { s.className = i < this.done ? 'done' : i === this.done ? 'now' : ''; });
        this.cur = this.queue[this.done];
        if (!this.cur) return this.finish();
        const t = this.cur.t = this.task(this.cur);
        this.q.textContent = this.ask[this.cur.kind] || '';
        this.front.textContent = t.front; this.front.lang = this.cur.kind === 'phrase' ? 'en' : (this.cur.tl || '');
        this.hint.textContent = t.hint || '';
        this.fb.textContent = ''; this.fb.className = 't3-feedback';
        this.opts.replaceChildren();
        t.options.forEach((o, n) => { const b = btn('', () => this.answer(o, b), 't3-opt'); b.append(el('kbd', '', String(n + 1)), el('span', '', o)); this.opts.append(b); });
    },
    async answer(given, b) {
        if (this.busy) return;
        this.busy = true;
        const right = given === this.cur.t.right;
        this.opts.querySelectorAll('button').forEach(x => { x.disabled = true; if (x.lastChild.textContent === this.cur.t.right) x.classList.add('right'); });
        if (!right) b.classList.add('wrong');
        right ? Sound.right() : Sound.wrong();
        this.fb.className = 't3-feedback ' + (right ? 'ok' : 'bad');
        this.fb.textContent = right ? 'Oikein!' : `The answer is “${this.cur.t.right}”.`;
        try {
            const r = await post(CFG.grade, {item: this.cur.id, grade: right ? 'good' : 'again', mode: 'choice', given, ...(this.extra ? {extra: '1'} : {})});
            if (r.reward && r.reward.xp) this.xp += r.reward.xp;
        } catch (e) { /* the round goes on; this answer is just not saved */ }
        setTimeout(() => { this.busy = false; this.done += 1; this.next(); }, right ? 650 : 1500);
    },
    async finish() {
        Sound.done();
        this.opts.hidden = true; this.q.textContent = ''; this.hint.textContent = ''; this.front.textContent = 'Valmis!';
        this.result.append(el('h3', '', 'Round complete'), el('p', 't3-muted', `${this.queue.length} cards practised${this.xp ? ', +' + this.xp + ' XP' : ''}. ` +
                           (this.extra ? 'Extra rounds do not change your review schedule.' : 'Your next reviews are planned.')));
        const row = el('div', 't3-row');
        row.append(btn('Another round', () => this.start(this.scope)));
        const leave = btn('Leave', () => {}, 't3-btn ghost'); leave.setAttribute('data-close', ''); row.append(leave);
        this.result.append(row); this.result.hidden = false;
        await refresh();
    },
};
addEventListener('keydown', e => {   // 1, 2, 3 answer in whichever round is open
    if (!panelOpen) return;
    const box = [Talk.opts, Drill.opts].find(b => b && b.isConnected && !b.hidden);
    const b = box && box.children[{'1': 0, '2': 1, '3': 2}[e.key]];
    if (b && !b.disabled) { e.preventDefault(); b.click(); }
});

// ── portraits: the 3D characters rendered once into small pictures ──────
const portraits = new Map();
async function portrait(model) {
    if (portraits.has(model)) return portraits.get(model);
    const job = (async () => {
        const r = new THREE.WebGLRenderer({antialias: true, alpha: true, preserveDrawingBuffer: true});
        r.setSize(160, 160); r.outputColorSpace = THREE.SRGBColorSpace; r.toneMapping = THREE.ACESFilmicToneMapping;
        const s = new THREE.Scene();
        s.add(new THREE.HemisphereLight(0xffffff, 0xb7a58c, 1.6));
        const l = new THREE.DirectionalLight(0xffffff, 2); l.position.set(2, 3, 4); s.add(l);
        const gltf = await load('people/' + model);
        const o = SkeletonUtils.clone(gltf.scene);
        const idle = gltf.animations.find(a => a.name === 'idle');
        if (idle) { const m = new THREE.AnimationMixer(o); m.clipAction(idle).play(); m.update(.1); }
        s.add(o);
        const c = new THREE.Box3().setFromObject(o).getCenter(new THREE.Vector3());
        const cam = new THREE.PerspectiveCamera(26, 1, .1, 50);
        cam.position.set(c.x + .9, c.y + .55, c.z + 2.2); cam.lookAt(c.x, c.y + .05, c.z);
        r.render(s, cam);
        const url = r.domElement.toDataURL('image/png');
        r.dispose();
        return url;
    })();
    portraits.set(model, job);
    return job;
}

// ── HUD ───────────────────────────────────────────────────────────────────
async function refresh() {
    STATE = await getJSON(CFG.state);
    STATE.decor = STATE.decor || {tiles: [], fx: []};
    STATE.decor.codes = (STATE.shop || []).filter(i => i.owned).map(i => i.code);
    $('t3-name').textContent = STATE.name;
    $('t3-level').textContent = 'Level ' + STATE.me.level;
    $('t3-rank').textContent = STATE.me.rank;
    $('t3-xp').style.width = STATE.me.pct + '%';
    $('t3-xpbar').setAttribute('aria-valuenow', STATE.me.into); $('t3-xpbar').setAttribute('aria-valuemax', STATE.me.span);
    $('t3-coins').textContent = STATE.me.coins;
    $('t3-streak').textContent = STATE.me.streak;
    $('t3-qdot').hidden = !STATE.quests.some(q => !q.done);
    if (STATE.sprite != null) portrait(PEOPLE[STATE.sprite]).then(u => { $('t3-face').src = u; });
    if (labels.size) updateLabels();
    return STATE;
}
async function pickCharacter() {
    const row = $('t3-pick-row'); row.replaceChildren();
    const urls = await Promise.all(PEOPLE.map(portrait));
    return new Promise(resolve => {
        PEOPLE.forEach((m, i) => {
            const b = el('button'); b.type = 'button'; b.setAttribute('aria-label', 'Character ' + (i + 1));
            const img = el('img'); img.src = urls[i]; img.alt = ''; b.append(img);
            b.addEventListener('click', async () => {
                try { await post(CFG.avatar, {sprite: i}); } catch (e) { /* keep the choice for this visit */ }
                $('t3-pick').hidden = true;
                await setAvatar(i); await refresh(); resolve(i);
            });
            row.append(b);
        });
        $('t3-pick').hidden = false;
        setTimeout(() => row.querySelector('button')?.focus(), 40);
    });
}
async function setAvatar(i) {
    const pos = me ? me.obj.position.clone() : new THREE.Vector3(4.3, 0, 7.5);
    if (me) scene.remove(me.obj);
    me = new Person(await load('people/' + PEOPLE[i]), pos.x, pos.z);
    me.arrived = () => { if (goal) { const g = goal; goal = null; enter(g); } };
}

// ── the loop ──────────────────────────────────────────────────────────────
let nearby = null;
const clock = new THREE.Clock();
function frame() { tick(Math.min(clock.getDelta(), .05)); requestAnimationFrame(frame); }
function tick(dt) {
    if (me && !panelOpen) {   // arrow keys and WASD walk directly
        let dx = 0, dz = 0;
        if (keys.has('arrowleft') || keys.has('a')) { dx -= 1; dz += 1; }
        if (keys.has('arrowright') || keys.has('d')) { dx += 1; dz -= 1; }
        if (keys.has('arrowup') || keys.has('w')) { dx -= 1; dz -= 1; }
        if (keys.has('arrowdown') || keys.has('s')) { dx += 1; dz += 1; }
        if (dx || dz) {
            const step = new THREE.Vector3(dx, 0, dz).normalize().multiplyScalar(me.speed * dt), p = me.obj.position;
            if (free(Math.floor((p.x + step.x) / CELL), Math.floor(p.z / CELL))) p.x += step.x;
            if (free(Math.floor(p.x / CELL), Math.floor((p.z + step.z) / CELL))) p.z += step.z;
            me.path = []; goal = null; me.face(step.x, step.z); me.play('walk');
            $('t3-hint').classList.add('gone');
        } else if (!me.path.length && me.state === 'walk') me.play('idle');
    }
    if (me) me.update(dt);
    townsfolk.forEach(p => p.update(dt));
    driveCars(dt);
    for (const f of waving) f.rotation.y = Math.sin(performance.now() / 500 + f.position.x) * .25;
    if (markerMesh?.visible) { markerMesh.scale.multiplyScalar(1 + dt * 1.5); markerMesh.material.opacity -= dt * 1.6; if (markerMesh.material.opacity <= 0) markerMesh.visible = false; }
    if (overview) focus.lerp(new THREE.Vector3(W / 2, 0, D / 2), Math.min(1, dt * 3));
    else if (me) {
        const t = me.obj.position;
        focus.lerp(new THREE.Vector3(THREE.MathUtils.clamp(t.x, 3.5, W - 3.5), 0, THREE.MathUtils.clamp(t.z, 3.5, D - 2.5)), Math.min(1, dt * 3));
    }
    camera.position.copy(focus).addScaledVector(VIEW, 40);
    camera.lookAt(focus);
    let near = null;
    if (me) for (const p of PLACES) if (me.obj.position.distanceTo(doorOf(p)) < .55) near = p;
    const a = $('t3-action');
    if (near !== nearby) {
        nearby = near;
        if (near) {
            const locked = isLocked(near);
            a.replaceChildren(icon(locked ? 'fa-lock' : near.icon), document.createTextNode(locked ? ` ${near.title} · opens at level ${placeInfo(near).level}` : ` Enter ${near.title} `));
            if (!locked) a.append(el('kbd', '', 'E'));
        }
    }
    a.hidden = !nearby || panelOpen;
    renderer.render(scene, camera);
    placeLabels();
}
$('t3-action').addEventListener('click', () => nearby && enter(nearby));

// ── start ─────────────────────────────────────────────────────────────────
async function boot() {
    resize();
    const state = await refresh();
    await buildDistrict(f => { $('t3-load-text').textContent = `Building the town… ${Math.round(f * 100)}%`; });
    buildGrid();
    await Promise.all([addPeople(), addCars()]);
    makeLabels();
    await setAvatar(state.sprite ?? 0);
    $('t3-loading').classList.add('gone');
    requestAnimationFrame(frame);
    if (COARSE) $('t3-hint').textContent = 'Tap to walk. Tap a building to go in. Pinch to zoom.';
    setTimeout(() => $('t3-hint').classList.add('gone'), 10000);
    if (CFG.debug) window.t3 = {scene, camera, me: () => me, walkTo, PLACES, enter, findPath, grid: () => grid, doorOf,
                                step: n => { for (let i = 0; i < n; i++) tick(1 / 30); }, portrait, PEOPLE,
                                // a picture of the whole town, for the Home page
                                shot: (w, h) => { overview = true; renderer.setSize(w, h, false); resize(); renderer.setSize(w, h, false);
                                                  const vh = 12.5, a = w / h; Object.assign(camera, {left: -vh * a / 2, right: vh * a / 2, top: vh / 2, bottom: -vh / 2});
                                                  camera.updateProjectionMatrix(); focus.set(W / 2, 0, D / 2 + .3);
                                                  camera.position.copy(focus).addScaledVector(VIEW, 40); camera.lookAt(focus);
                                                  renderer.render(scene, camera); return renderer.domElement.toDataURL('image/jpeg', .86); }};
    if (state.sprite == null) await pickCharacter();
}
boot().catch(err => { console.error(err); $('t3-load-text').textContent = 'The town could not load. Reload the page to try again.'; });
