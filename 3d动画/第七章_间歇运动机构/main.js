import * as THREE from 'three';
import { setupScene, standardMaterial, GLASS_OPTS } from '../common.js';

const { scene, camera, renderer, controls } = setupScene({ cameraPos: [0, 3.5, 0.1], target: [0, 0, 0], gridSize: 6 });

const els = {
  n: document.getElementById('n'), speed: document.getElementById('speed'),
  nVal: document.getElementById('nVal'), speedVal: document.getElementById('speedVal'),
  info: document.getElementById('info'), slotRow: document.getElementById('slotRow'),
  tabGeneva: document.getElementById('tabGeneva'), tabRatchet: document.getElementById('tabRatchet'),
};

let mode = 'geneva';
const genevaGroup = new THREE.Group();
const ratchetGroup = new THREE.Group();
scene.add(genevaGroup, ratchetGroup);

// ==================== 槽轮机构（外槽轮，单圆销） ====================
const PIN_R = 0.5; // 主动拨盘销半径
let driverMesh, pinMesh, wheelMesh, lockDisk;
let L = 1; // 中心距，随槽数n变化: L = r/sin(pi/n)

function buildGeneva(n) {
  genevaGroup.clear();
  L = PIN_R / Math.sin(Math.PI / n);

  // 主动拨盘 + 锁止盘
  driverMesh = new THREE.Group();
  const lockGeo = new THREE.CylinderGeometry(PIN_R * 0.55, PIN_R * 0.55, 0.12, 32, 1, false,
    (Math.PI / n) + 0.05, Math.PI * 2 - 2 * ((Math.PI / n) + 0.05)); // 留缺口给槽轮锁止弧配合，示意
  lockDisk = new THREE.Mesh(lockGeo, standardMaterial(0x48484a));
  lockDisk.rotation.x = Math.PI / 2;
  driverMesh.add(lockDisk);
  pinMesh = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.2, 16), standardMaterial(0xff9500));
  pinMesh.position.set(PIN_R, 0, 0);
  driverMesh.add(pinMesh);
  driverMesh.position.set(-L / 2, 0, 0);
  genevaGroup.add(driverMesh);

  // 槽轮：底盘 + n条径向槽（示意用暗色薄片标出槽位置，不做真实布尔切割）
  const wheelR = PIN_R + L * 0.15;
  wheelMesh = new THREE.Group();
  const base = new THREE.Mesh(new THREE.CylinderGeometry(wheelR, wheelR, 0.14, 48), standardMaterial(0x30b0c7, GLASS_OPTS));
  wheelMesh.add(base);
  for (let i = 0; i < n; i++) {
    const slot = new THREE.Mesh(new THREE.BoxGeometry(wheelR * 1.05, 0.16, PIN_R * 0.24), standardMaterial(0x1c1c1e));
    slot.position.x = wheelR * 0.5;
    const g = new THREE.Group();
    g.add(slot);
    g.rotation.y = (i * 2 * Math.PI) / n;
    wheelMesh.add(g);
  }
  const marker = new THREE.Mesh(new THREE.SphereGeometry(0.08, 12, 10), standardMaterial(0xff3b30));
  marker.position.set(wheelR * 0.85, 0.1, 0);
  wheelMesh.add(marker);

  wheelMesh.position.set(L / 2, 0, 0);
  genevaGroup.add(wheelMesh);
}

let genevaBaseAngle = 0; // 槽轮已锁定的累计角度
let genevaEngagedPrev = false;
let thetaDriver = Math.PI; // 从锁止区(远离啮合窗口中点)开始，避免启动瞬间恰好卡在半程啮合的显示误导

function stepGeneva(dt, n, speed) {
  thetaDriver += speed * dt;
  const thetaE = Math.PI / 2 - Math.PI / n; // 啮合半角
  let phi = ((thetaDriver + Math.PI) % (2 * Math.PI)) - Math.PI; // 归一化到(-pi,pi]
  const engaged = Math.abs(phi) <= thetaE;

  if (engaged) {
    const px = PIN_R * Math.cos(thetaDriver), py = PIN_R * Math.sin(thetaDriver);
    const rawAngle = Math.atan2(py, px - L); // 相对槽轮中心G的方向角
    let local = rawAngle - Math.PI;
    if (local > Math.PI) local -= 2 * Math.PI;
    if (local < -Math.PI) local += 2 * Math.PI;
    if (!genevaEngagedPrev) genevaBaseAngle = wheelMesh.rotation.y - 0; // 记录进入啮合前的角度（此时local应接近-thetaE附近的值，用差分方式更稳）
    wheelMesh.rotation.y = genevaBaseAngle + (local - (genevaEngagedPrev ? genevaEntryLocal : local));
    if (!genevaEngagedPrev) genevaEntryLocal = local;
  }
  genevaEngagedPrev = engaged;

  driverMesh.rotation.y = thetaDriver;
  return engaged;
}
let genevaEntryLocal = 0;

// ==================== 棘轮机构 ====================
let ratchetWheel, pawlArm;
const RATCHET_N = 12;
function buildRatchet() {
  ratchetGroup.clear();
  const wheelR = 0.9;
  const shape = new THREE.Shape();
  const step = (Math.PI * 2) / RATCHET_N;
  for (let i = 0; i < RATCHET_N; i++) {
    const a0 = i * step;
    const aTip = a0 + step * 0.15;
    const aBack = a0 + step;
    const pts = [
      [wheelR * 0.6 * Math.cos(a0), wheelR * 0.6 * Math.sin(a0)],
      [wheelR * Math.cos(aTip), wheelR * Math.sin(aTip)],
      [wheelR * 0.6 * Math.cos(aBack), wheelR * 0.6 * Math.sin(aBack)],
    ];
    pts.forEach(([x, y], idx) => {
      if (i === 0 && idx === 0) shape.moveTo(x, y); else shape.lineTo(x, y);
    });
  }
  shape.closePath();
  const geo = new THREE.ExtrudeGeometry(shape, { depth: 0.16, bevelEnabled: false });
  geo.rotateX(Math.PI / 2);
  ratchetWheel = new THREE.Mesh(geo, standardMaterial(0x007aff, GLASS_OPTS));
  ratchetGroup.add(ratchetWheel);

  pawlArm = new THREE.Group();
  const arm = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.08, 0.08), standardMaterial(0x34c759, GLASS_OPTS));
  arm.position.x = 0.35;
  pawlArm.add(arm);
  const tip = new THREE.Mesh(new THREE.ConeGeometry(0.07, 0.2, 12), standardMaterial(0xff9500));
  tip.position.set(wheelR * 0.85, 0, 0);
  tip.rotation.z = Math.PI / 2;
  pawlArm.add(tip);
  pawlArm.position.set(0, 0, 0);
  ratchetGroup.add(pawlArm);
}

let ratchetPrevAlpha = 0, ratchetBaseAngle = 0, ratchetAdvancedThisStroke = false;
function stepRatchet(t, speed) {
  const amplitude = Math.PI / RATCHET_N; // 摆角幅度=半个齿距，保证每次正好前进一个齿
  const alpha = amplitude * Math.sin(speed * t);
  pawlArm.rotation.y = alpha;

  const movingForward = alpha > ratchetPrevAlpha;
  const toothPitch = (2 * Math.PI) / RATCHET_N;
  if (movingForward) {
    const progress = (alpha + amplitude) / (2 * amplitude); // 0~1
    ratchetWheel.rotation.y = ratchetBaseAngle + progress * toothPitch;
    ratchetAdvancedThisStroke = true;
  } else if (ratchetAdvancedThisStroke) {
    ratchetBaseAngle += toothPitch;
    ratchetAdvancedThisStroke = false;
  }
  ratchetPrevAlpha = alpha;
}

// ==================== 交互与主循环 ====================
function syncLabels() {
  els.nVal.textContent = els.n.value;
  els.speedVal.textContent = parseFloat(els.speed.value).toFixed(1) + ' rad/s';
}
function updateInfo() {
  if (mode === 'geneva') {
    const n = parseInt(els.n.value);
    const deg = (180 - 360 / n).toFixed(1);
    els.info.innerHTML = `槽数 n=${n}，单销外槽轮<br>中心距 L=r/sin(π/n)=${L.toFixed(2)}（销半径r=0.5固定）<br>主动件转一圈，槽轮的有效驱动转角=${deg}°，其余为静止（锁止）阶段<br>槽的方向角始终等于销相对槽轮中心的方位角——这是槽轮运动学的核心几何关系`;
  } else {
    els.info.innerHTML = `棘爪往复摆动，摆角=半个齿距<br>正行程（棘爪推动棘轮前进）转过1个齿；反行程棘爪在齿背上滑过，棘轮由止动棘爪锁住不动<br>齿数=${RATCHET_N}（固定），每次动作前进 360°/${RATCHET_N}=${(360/RATCHET_N).toFixed(1)}°`;
  }
}

els.n.addEventListener('input', () => { syncLabels(); buildGeneva(parseInt(els.n.value)); genevaBaseAngle = 0; genevaEngagedPrev = false; updateInfo(); });
els.speed.addEventListener('input', () => { syncLabels(); updateInfo(); });

function setMode(m) {
  mode = m;
  genevaGroup.visible = m === 'geneva';
  ratchetGroup.visible = m === 'ratchet';
  els.slotRow.style.display = m === 'geneva' ? '' : 'none';
  els.tabGeneva.classList.toggle('active', m === 'geneva');
  els.tabRatchet.classList.toggle('active', m === 'ratchet');
  updateInfo();
}
els.tabGeneva.addEventListener('click', () => setMode('geneva'));
els.tabRatchet.addEventListener('click', () => setMode('ratchet'));

syncLabels();
buildGeneva(parseInt(els.n.value));
buildRatchet();
setMode('geneva');

let tTotal = 0;
const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  const dt = Math.min(clock.getDelta(), 0.05);
  tTotal += dt;
  const speed = parseFloat(els.speed.value);

  if (mode === 'geneva') {
    stepGeneva(dt, parseInt(els.n.value), speed);
  } else {
    stepRatchet(tTotal, speed * 2);
  }

  controls.update();
  renderer.render(scene, camera);
}
animate();
