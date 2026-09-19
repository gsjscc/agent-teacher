import * as THREE from 'three';
import { setupScene, standardMaterial, GLASS_OPTS } from '../common.js';

const { scene, camera, renderer, controls } = setupScene({ cameraPos: [0, 0, 3], target: [0, 0, 0], gridSize: 6 });

const R_BEARING = 1.0;
const CLEARANCE_C = 0.15; // 间隙 c = R轴承 - R轴颈
const R_SHAFT = R_BEARING - CLEARANCE_C;

const bushing = new THREE.Mesh(new THREE.RingGeometry(R_BEARING - 0.08, R_BEARING, 64), standardMaterial(0x8e8e93, { side: THREE.DoubleSide }));
scene.add(bushing);

const shaftGroup = new THREE.Group();
const shaft = new THREE.Mesh(new THREE.CircleGeometry(R_SHAFT, 48), standardMaterial(0x007aff, { ...GLASS_OPTS, ...{ side: THREE.DoubleSide } }));
const marker = new THREE.Mesh(new THREE.CircleGeometry(0.06, 12), standardMaterial(0x1c1c1e, { side: THREE.DoubleSide }));
marker.position.set(R_SHAFT * 0.75, 0, 0.01);
shaftGroup.add(shaft, marker);
scene.add(shaftGroup);

const els = {
  eps: document.getElementById('eps'), speed: document.getElementById('speed'),
  epsVal: document.getElementById('epsVal'), speedVal: document.getElementById('speedVal'),
};
function syncLabels() {
  els.epsVal.textContent = parseFloat(els.eps.value).toFixed(2);
  els.speedVal.textContent = parseFloat(els.speed.value).toFixed(1) + ' rad/s';
}
els.eps.addEventListener('input', syncLabels);
els.speed.addEventListener('input', syncLabels);
syncLabels();

let theta = 0;
const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  const dt = Math.min(clock.getDelta(), 0.05);
  const speed = parseFloat(els.speed.value);
  const eps = parseFloat(els.eps.value);
  theta += speed * dt;

  const e = eps * CLEARANCE_C;
  // 偏心方向固定朝下（重力/载荷方向示意），轴颈中心偏移，油膜最薄处在偏移方向对侧的间隙里
  shaftGroup.position.set(0, -e, 0);
  shaftGroup.rotation.z = theta;

  controls.update();
  renderer.render(scene, camera);
}
animate();
