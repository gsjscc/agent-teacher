import * as THREE from 'three';
import { setupScene, standardMaterial, GLASS_OPTS } from '../common.js';

const { scene, camera, renderer, controls } = setupScene({ cameraPos: [2.5, 2, 3], target: [0, 0.4, 0] });

// ---------- 运动规律：推程(简谐)-远休止-回程(简谐)-近休止，四段角度固定 ----------
const PHASE = { rise: 100, farDwell: 40, ret: 100, nearDwell: 120 }; // 度，合计360
function displacement(thetaDeg, h) {
  const t = ((thetaDeg % 360) + 360) % 360;
  if (t < PHASE.rise) {
    return (h / 2) * (1 - Math.cos((Math.PI * t) / PHASE.rise));
  }
  const t2 = t - PHASE.rise;
  if (t2 < PHASE.farDwell) return h;
  const t3 = t2 - PHASE.farDwell;
  if (t3 < PHASE.ret) {
    return (h / 2) * (1 + Math.cos((Math.PI * t3) / PHASE.ret));
  }
  return 0;
}

// ---------- 凸轮轮廓（示意：按 r(theta)=r0+s(theta) 生成实体，尖顶从动件直接读这个轮廓） ----------
let camMesh = null;
function buildCamProfile(r0, h) {
  const shape = new THREE.Shape();
  const N = 240;
  for (let i = 0; i <= N; i++) {
    const deg = (360 * i) / N;
    const r = r0 + displacement(deg, h);
    const rad = (deg * Math.PI) / 180;
    const x = r * Math.cos(rad), y = r * Math.sin(rad);
    if (i === 0) shape.moveTo(x, y); else shape.lineTo(x, y);
  }
  const geo = new THREE.ExtrudeGeometry(shape, { depth: 0.25, bevelEnabled: false, curveSegments: 2 });
  geo.rotateX(Math.PI / 2);
  geo.translate(0, -0.125, 0);
  if (camMesh) { scene.remove(camMesh); camMesh.geometry.dispose(); }
  camMesh = new THREE.Mesh(geo, standardMaterial(0x007aff, GLASS_OPTS));
  scene.add(camMesh);
}

// 从动件：竖直导轨 + 滚子（示意尖顶从动件直接贴合轮廓，运动规律与从动件形式无关）
const guide = new THREE.Mesh(new THREE.BoxGeometry(0.08, 2, 0.08), standardMaterial(0x48484a));
guide.position.set(0, 1, 0);
scene.add(guide);

const follower = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 0.5, 20), standardMaterial(0x34c759, GLASS_OPTS));
scene.add(follower);
const roller = new THREE.Mesh(new THREE.SphereGeometry(0.1, 20, 16), standardMaterial(0xff9500));
scene.add(roller);

const shaftAxis = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.6, 12), standardMaterial(0x8e8e93));
shaftAxis.rotation.x = Math.PI / 2;
scene.add(shaftAxis);

const els = {
  r0: document.getElementById('r0'), h: document.getElementById('h'), speed: document.getElementById('speed'),
  r0Val: document.getElementById('r0Val'), hVal: document.getElementById('hVal'), speedVal: document.getElementById('speedVal'),
};
function syncLabels() {
  els.r0Val.textContent = parseFloat(els.r0.value).toFixed(2);
  els.hVal.textContent = parseFloat(els.h.value).toFixed(2);
  els.speedVal.textContent = parseFloat(els.speed.value).toFixed(1) + ' rad/s';
}
[els.r0, els.h].forEach((el) => el.addEventListener('input', () => {
  buildCamProfile(parseFloat(els.r0.value), parseFloat(els.h.value));
  syncLabels();
}));
els.speed.addEventListener('input', syncLabels);
syncLabels();
buildCamProfile(parseFloat(els.r0.value), parseFloat(els.h.value));

let theta = 0;
const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  const dt = Math.min(clock.getDelta(), 0.05);
  const speed = parseFloat(els.speed.value);
  theta += speed * dt * (180 / Math.PI); // 弧度/秒 -> 度/秒

  const r0 = parseFloat(els.r0.value), h = parseFloat(els.h.value);
  if (camMesh) camMesh.rotation.y = (theta * Math.PI) / 180;

  const s = displacement(theta, h);
  const followerY = r0 + s;
  follower.position.set(0, followerY / 2 + 0.25, 0);
  follower.scale.y = followerY / 0.5;
  roller.position.set(0, followerY + 0.1, 0);

  controls.update();
  renderer.render(scene, camera);
}
animate();
