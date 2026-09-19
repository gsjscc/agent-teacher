import * as THREE from 'three';
import { setupScene, standardMaterial, GLASS_OPTS } from '../common.js';

const { scene, camera, renderer, controls } = setupScene({ cameraPos: [2.2, 1.2, 2.6], target: [0, 0, 0], gridSize: 6 });

let mode = 'dog';
let engaged = false;
const group = new THREE.Group();
scene.add(group);

function buildDog() {
  group.clear();
  const drive = new THREE.Group();
  const driveDisc = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 0.2, 32), standardMaterial(0x007aff, GLASS_OPTS));
  driveDisc.rotation.z = Math.PI / 2;
  drive.add(driveDisc);
  for (let i = 0; i < 8; i++) {
    const tooth = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.14, 0.1), standardMaterial(0x48484a));
    const a = (i * 2 * Math.PI) / 8;
    tooth.position.set(0.1, 0.42 * Math.cos(a), 0.42 * Math.sin(a));
    drive.add(tooth);
  }
  drive.position.x = -0.3;
  group.add(drive);

  const driven = new THREE.Group();
  const drivenDisc = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 0.2, 32), standardMaterial(0x30b0c7, GLASS_OPTS));
  drivenDisc.rotation.z = Math.PI / 2;
  driven.add(drivenDisc);
  for (let i = 0; i < 8; i++) {
    const tooth = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.14, 0.1), standardMaterial(0x48484a));
    const a = (i * 2 * Math.PI) / 8;
    tooth.position.set(-0.1, 0.42 * Math.cos(a), 0.42 * Math.sin(a));
    driven.add(tooth);
  }
  group.add(driven);
  return { drive, driven };
}

function buildFriction() {
  group.clear();
  const drive = new THREE.Group();
  const driveDisc = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 0.15, 32), standardMaterial(0x007aff, GLASS_OPTS));
  driveDisc.rotation.z = Math.PI / 2;
  const marker1 = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.4, 0.06), standardMaterial(0x1c1c1e));
  marker1.position.x = 0.08;
  driveDisc.add(marker1);
  drive.add(driveDisc);
  drive.position.x = -0.3;
  group.add(drive);

  const driven = new THREE.Group();
  const drivenDisc = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 0.15, 32), standardMaterial(0x30b0c7, GLASS_OPTS));
  drivenDisc.rotation.z = Math.PI / 2;
  const marker2 = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.4, 0.06), standardMaterial(0x1c1c1e));
  marker2.position.x = -0.08;
  drivenDisc.add(marker2);
  driven.add(drivenDisc);
  group.add(driven);
  return { drive, driven };
}

let parts = buildDog();

const els = {
  speed: document.getElementById('speed'), speedVal: document.getElementById('speedVal'),
  info: document.getElementById('info'), toggleBtn: document.getElementById('toggleBtn'),
  tabDog: document.getElementById('tabDog'), tabFriction: document.getElementById('tabFriction'),
};
function syncLabels() { els.speedVal.textContent = parseFloat(els.speed.value).toFixed(1) + ' rad/s'; }
function updateInfo() {
  els.info.innerHTML = mode === 'dog'
    ? `牙嵌式：靠两个半离合器端面的牙齿啮合传递转矩，接合瞬间是刚性啮合，没有过载打滑保护能力，接合时有冲击，一般只在低速或静止状态下操作。当前：${engaged ? '已接合（从动转速瞬间锁定=主动转速）' : '已分离（从动件依惯性/摩擦逐渐停止）'}`
    : `摩擦式：靠接合元件间的正压力产生摩擦力传递转矩，接合是渐进过程（转速逐渐同步，期间存在打滑），可实现过载打滑保护。当前：${engaged ? '已接合（转速正逐渐同步）' : '已分离（从动件逐渐降速）'}`;
}
els.speed.addEventListener('input', syncLabels);
els.toggleBtn.addEventListener('click', () => { engaged = !engaged; updateInfo(); });
function setMode(m) {
  mode = m;
  parts = m === 'dog' ? buildDog() : buildFriction();
  els.tabDog.classList.toggle('active', m === 'dog');
  els.tabFriction.classList.toggle('active', m === 'friction');
  updateInfo();
}
els.tabDog.addEventListener('click', () => setMode('dog'));
els.tabFriction.addEventListener('click', () => setMode('friction'));
syncLabels();
updateInfo();

let thetaDrive = 0, thetaDriven = 0, wDriven = 0;
let axialPos = 0; // 0=分离, 1=接合
const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  const dt = Math.min(clock.getDelta(), 0.05);
  const wDrive = parseFloat(els.speed.value);

  axialPos += ((engaged ? 1 : 0) - axialPos) * Math.min(1, dt * 6);
  parts.driven.position.x = -0.3 + 0.28 * axialPos + 0.02;

  thetaDrive += wDrive * dt;
  parts.drive.rotation.x = thetaDrive;

  if (mode === 'dog') {
    // 牙嵌式：接合时刚性同步（无滑动过渡），分离时按摩擦阻力衰减到0
    if (engaged && axialPos > 0.9) {
      wDriven = wDrive;
    } else if (!engaged) {
      wDriven += (0 - wDriven) * Math.min(1, dt * 2);
    }
  } else {
    // 摩擦式：接合时按指数趋近主动转速（示意打滑过渡），分离时逐渐衰减到0
    const target = engaged ? wDrive : 0;
    const rate = engaged ? 1.5 : 1.0;
    wDriven += (target - wDriven) * Math.min(1, dt * rate);
  }
  thetaDriven += wDriven * dt;
  parts.driven.rotation.x = thetaDriven;

  controls.update();
  renderer.render(scene, camera);
}
animate();
