import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// ---------- 场景基础 ----------
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xf4f6f9);

const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.05, 100);
camera.position.set(2.2, 2.4, 3.4);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(window.devicePixelRatio);
document.body.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(1, 0, 0);
controls.enableDamping = true;

scene.add(new THREE.AmbientLight(0xffffff, 0.85));
const dirLight = new THREE.DirectionalLight(0xffffff, 0.7);
dirLight.position.set(3, 5, 4);
scene.add(dirLight);
const rimLight = new THREE.DirectionalLight(0x2f6fed, 0.25);
rimLight.position.set(-3, 2, -3);
scene.add(rimLight);

const grid = new THREE.GridHelper(10, 20, 0xc7d0dc, 0xe6eaf0);
grid.rotation.x = Math.PI / 2; // 网格对齐机构所在的 XY 平面
scene.add(grid);

window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

// ---------- 运动学：平面四连杆位置解算 ----------
// 固定铰点 A=(0,0)，D=(d,0)；求解 B（由曲柄角驱动）、C（B、D 圆相交）
function solveThirdPoint(P, Q, rP, rQ, prevGuess) {
  // 已知两定点 P、Q，求一点 X 满足 |X-P|=rP，|X-Q|=rQ
  const dx = Q.x - P.x, dy = Q.y - P.y;
  const dist = Math.hypot(dx, dy);
  if (dist === 0 || dist > rP + rQ || dist < Math.abs(rP - rQ)) return null;

  const a = (rP * rP - rQ * rQ + dist * dist) / (2 * dist);
  const hh = rP * rP - a * a;
  if (hh < 0) return null;
  const h = Math.sqrt(hh);

  const xm = P.x + (a * dx) / dist;
  const ym = P.y + (a * dy) / dist;

  const sol1 = { x: xm + (h * dy) / dist, y: ym - (h * dx) / dist };
  const sol2 = { x: xm - (h * dy) / dist, y: ym + (h * dx) / dist };

  if (!prevGuess) return sol1;
  const d1 = Math.hypot(sol1.x - prevGuess.x, sol1.y - prevGuess.y);
  const d2 = Math.hypot(sol2.x - prevGuess.x, sol2.y - prevGuess.y);
  return d1 <= d2 ? sol1 : sol2;
}

// Grashof 判定：a=曲柄侧AB，b=连杆BC，c=摇杆侧CD，d=机架AD
function classify(a, b, c, d) {
  const links = [
    { name: 'ground', label: '机架', len: d },
    { name: 'crank', label: '曲柄侧杆(AB)', len: a },
    { name: 'coupler', label: '连杆(BC)', len: b },
    { name: 'rocker', label: '摇杆侧杆(CD)', len: c },
  ];
  const sorted = [...links].sort((x, y) => x.len - y.len);
  const s = sorted[0], l = sorted[3];
  const sumOthers = sorted[1].len + sorted[2].len;
  const grashof = s.len + l.len <= sumOthers + 1e-9;

  if (!grashof) return { text: '双摇杆机构（非Grashof，全部杆件只能摆动）' };
  if (s.name === 'ground') return { text: '双曲柄机构（机架最短，两侧杆均可整周转动）' };
  if (s.name === 'crank') return { text: '曲柄摇杆机构（AB为曲柄，与机架相邻的最短杆）' };
  if (s.name === 'rocker') return { text: '曲柄摇杆机构（CD为曲柄，与机架相邻的最短杆）' };
  return { text: '双摇杆机构（连杆BC最短，双侧杆均不能整周转动）' };
}

// ---------- 3D 杆件渲染 ----------
const LINK_THICKNESS = 0.09;
const JOINT_RADIUS = 0.075;

function makeLinkMesh(color, opacity = 1) {
  const geo = new THREE.CylinderGeometry(LINK_THICKNESS / 2, LINK_THICKNESS / 2, 1, 16);
  const mat = new THREE.MeshPhysicalMaterial({
    color, roughness: 0.35, metalness: 0.05,
    transparent: opacity < 1, opacity, transmission: opacity < 1 ? 0.4 : 0, thickness: 0.3,
  });
  return new THREE.Mesh(geo, mat);
}
function makeJointMesh(color, opacity = 1) {
  const geo = new THREE.SphereGeometry(JOINT_RADIUS, 20, 16);
  const mat = new THREE.MeshPhysicalMaterial({
    color, roughness: 0.3, metalness: 0.05,
    transparent: opacity < 1, opacity, transmission: opacity < 1 ? 0.4 : 0, thickness: 0.3,
  });
  return new THREE.Mesh(geo, mat);
}

function placeLink(mesh, p1, p2) {
  const v1 = new THREE.Vector3(p1.x, p1.y, 0);
  const v2 = new THREE.Vector3(p2.x, p2.y, 0);
  const mid = v1.clone().add(v2).multiplyScalar(0.5);
  const dir = v2.clone().sub(v1);
  const len = dir.length();
  mesh.position.copy(mid);
  mesh.scale.set(1, Math.max(len, 0.001), 1);
  const quat = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize());
  mesh.setRotationFromQuaternion(quat);
}
function placeJoint(mesh, p) {
  mesh.position.set(p.x, p.y, 0);
}

// 苹果系统色配色：机架/连杆用中性灰阶，曲柄用系统蓝，摇杆用系统青——
// 饱和度适中、不刺眼，保留四种杆件的教学区分度（一眼认出哪个是曲柄）
const groundLink = makeLinkMesh(0x8e8e93);        // Apple systemGray，不透明
const crankLink = makeLinkMesh(0x007aff, 0.72);   // Apple systemBlue，玻璃通透感
const couplerLink = makeLinkMesh(0xc7c7cc);       // Apple systemGray4（浅灰，弱化非重点杆件）
const rockerLink = makeLinkMesh(0x30b0c7, 0.72);  // Apple systemTeal，玻璃通透感
scene.add(groundLink, crankLink, couplerLink, rockerLink);

// 固定铰点（机架端 A/D）用深灰不透明，活动铰点（B/C）用系统蓝+玻璃质感，区分"固定 vs 转动"
const jointA = makeJointMesh(0x48484a);           // Apple systemGray2 (dark)
const jointB = makeJointMesh(0x007aff, 0.72);
const jointC = makeJointMesh(0x007aff, 0.72);
const jointD = makeJointMesh(0x48484a);
scene.add(jointA, jointB, jointC, jointD);

// ---------- 交互控件 ----------
const els = {
  d: document.getElementById('d'), a: document.getElementById('a'),
  b: document.getElementById('b'), c: document.getElementById('c'),
  dVal: document.getElementById('dVal'), aVal: document.getElementById('aVal'),
  bVal: document.getElementById('bVal'), cVal: document.getElementById('cVal'),
  typeBadge: document.getElementById('typeBadge'), warn: document.getElementById('warn'),
};

function readParams() {
  return {
    d: parseFloat(els.d.value), a: parseFloat(els.a.value),
    b: parseFloat(els.b.value), c: parseFloat(els.c.value),
  };
}
function syncLabels(p) {
  els.dVal.textContent = p.d.toFixed(2);
  els.aVal.textContent = p.a.toFixed(2);
  els.bVal.textContent = p.b.toFixed(2);
  els.cVal.textContent = p.c.toFixed(2);
}

let theta = 0.4;
let dir = 1;
let prevC = null;

// 预留：将来接入 robot.chaoxing.com 任务流【嵌入】节点时，
// 通过 postMessage 把机构类型/杆长回传给父页面的输出变量
function reportToParent(payload) {
  try {
    window.parent.postMessage({ source: 'four-bar-3d', ...payload }, '*');
  } catch (e) { /* 本地独立打开时没有父窗口，忽略 */ }
}

let lastReportedType = '';

function step(dt) {
  const p = readParams();
  const A = { x: 0, y: 0 };
  const D = { x: p.d, y: 0 };

  const info = classify(p.a, p.b, p.c, p.d);
  if (info.text !== lastReportedType) {
    lastReportedType = info.text;
    els.typeBadge.textContent = info.text;
    reportToParent({ mechanismType: info.text, params: p });
  }

  // 尝试推进曲柄角；若解算失败（超出闭合范围）则反向摆动，
  // 这样无论是曲柄摇杆/双曲柄/双摇杆，都能自动表现出正确的运动形式，不用针对类型分支写不同驱动逻辑
  //
  // 杆长比例极端时，有效摆动角度窗口可能比默认步长还窄（比如1/1/1/2.9这种），
  // 单纯"正向不行就反向"会两个方向都撞墙、卡死不动。这里在两个方向都失败时
  // 逐步把步长减半重试，等于让"触壁"时的反弹幅度自动变小，直到落回有效范围内。
  const baseStep = 0.9 * dt;
  let B = null, C = null, nextTheta = theta;
  let shrink = 1;
  const MAX_SHRINK_TRIES = 8;

  for (let i = 0; i < MAX_SHRINK_TRIES && !C; i++) {
    nextTheta = theta + baseStep * dir * shrink;
    B = { x: A.x + p.a * Math.cos(nextTheta), y: A.y + p.a * Math.sin(nextTheta) };
    C = solveThirdPoint(B, D, p.b, p.c, prevC);
    if (C) break;

    dir *= -1;
    nextTheta = theta + baseStep * dir * shrink;
    B = { x: A.x + p.a * Math.cos(nextTheta), y: A.y + p.a * Math.sin(nextTheta) };
    C = solveThirdPoint(B, D, p.b, p.c, prevC);
    if (C) break;

    shrink *= 0.5; // 两个方向都撞墙，说明步子迈太大，缩小步长再试
  }

  if (!C) {
    els.warn.style.display = 'block';
    return; // 杆长组合本身就无法闭合（比如触发条件不满足），停在原位等待用户调整参数
  }
  els.warn.style.display = 'none';
  theta = nextTheta;
  prevC = C;

  placeLink(groundLink, A, D);
  placeLink(crankLink, A, B);
  placeLink(couplerLink, B, C);
  placeLink(rockerLink, C, D);
  placeJoint(jointA, A);
  placeJoint(jointB, B);
  placeJoint(jointC, C);
  placeJoint(jointD, D);
}

[els.d, els.a, els.b, els.c].forEach((el) => {
  el.addEventListener('input', () => {
    prevC = null; // 杆长改变时不强制沿用旧分支，避免出现不合理的瞬间跳变
    syncLabels(readParams());
  });
});
syncLabels(readParams());

const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  const dt = Math.min(clock.getDelta(), 0.05);
  step(dt);
  controls.update();
  renderer.render(scene, camera);
}
animate();
