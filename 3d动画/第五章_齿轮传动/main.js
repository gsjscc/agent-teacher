import * as THREE from 'three';
import { setupScene, extrudeGear, GLASS_OPTS } from '../common.js';

const { scene, camera, renderer, controls } = setupScene({ cameraPos: [0, 3, 5], target: [0.6, 0, 0] });

let gear1 = null, gear2 = null;

function rebuild() {
  const z1 = parseInt(els.z1.value), z2 = parseInt(els.z2.value), m = parseFloat(els.m.value);
  if (gear1) scene.remove(gear1.mesh);
  if (gear2) scene.remove(gear2.mesh);
  gear1 = extrudeGear(z1, m, 0.3, 0x007aff, 1, 1.25, GLASS_OPTS);
  gear2 = extrudeGear(z2, m, 0.3, 0x30b0c7, 1, 1.25, GLASS_OPTS);
  const a = gear1.pitchRadius + gear2.pitchRadius; // 中心距 = r1+r2
  gear1.mesh.position.set(0, 0, 0);
  gear2.mesh.position.set(a, 0, 0);
  scene.add(gear1.mesh, gear2.mesh);

  els.ratioVal.textContent = (z2 / z1).toFixed(2);
  els.r1Val.textContent = gear1.pitchRadius.toFixed(2);
  els.r2Val.textContent = gear2.pitchRadius.toFixed(2);
  els.aVal.textContent = a.toFixed(2);
  return { z1, z2, a };
}

const els = {
  z1: document.getElementById('z1'), z2: document.getElementById('z2'), m: document.getElementById('m'), speed: document.getElementById('speed'),
  z1Val: document.getElementById('z1Val'), z2Val: document.getElementById('z2Val'), mVal: document.getElementById('mVal'), speedVal: document.getElementById('speedVal'),
  ratioVal: document.getElementById('ratioVal'), r1Val: document.getElementById('r1Val'), r2Val: document.getElementById('r2Val'), aVal: document.getElementById('aVal'),
};
function syncLabels() {
  els.z1Val.textContent = els.z1.value;
  els.z2Val.textContent = els.z2.value;
  els.mVal.textContent = parseFloat(els.m.value).toFixed(2);
  els.speedVal.textContent = parseFloat(els.speed.value).toFixed(1) + ' rad/s';
}
[els.z1, els.z2, els.m].forEach((el) => el.addEventListener('input', () => { syncLabels(); rebuild(); }));
els.speed.addEventListener('input', syncLabels);
syncLabels();
rebuild();

let theta1 = 0;
const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  const dt = Math.min(clock.getDelta(), 0.05);
  const z1 = parseInt(els.z1.value), z2 = parseInt(els.z2.value);
  const w1 = parseFloat(els.speed.value);
  const w2 = w1 * z1 / z2; // 啮合传动：w1*z1 = w2*z2

  theta1 += w1 * dt;
  const theta2 = -(theta1 * z1) / z2; // 外啮合反向；瞬时角位移比=z1/z2的反比关系积分即为 -w1*z1/z2*t

  if (gear1) gear1.mesh.rotation.y = theta1;
  if (gear2) gear2.mesh.rotation.y = theta2;

  controls.update();
  renderer.render(scene, camera);
}
animate();
