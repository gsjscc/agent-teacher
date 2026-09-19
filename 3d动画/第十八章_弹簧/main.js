import * as THREE from 'three';
import { setupScene, standardMaterial, GLASS_OPTS } from '../common.js';

const { scene, camera, renderer, controls } = setupScene({ cameraPos: [2.2, 1.2, 2.5], target: [0, 0.8, 0], gridSize: 6 });

const COIL_RADIUS = 0.5;
const WIRE_RADIUS = 0.05;

const baseDisc = new THREE.Mesh(new THREE.CylinderGeometry(0.7, 0.7, 0.08, 32), standardMaterial(0x48484a));
scene.add(baseDisc);
const loadDisc = new THREE.Mesh(new THREE.CylinderGeometry(0.65, 0.65, 0.1, 32), standardMaterial(0x007aff, GLASS_OPTS));
scene.add(loadDisc);

let springMesh = null;
function buildSpring(height, turns) {
  if (springMesh) { scene.remove(springMesh); springMesh.geometry.dispose(); }
  const pts = [];
  const N = 300;
  for (let i = 0; i <= N; i++) {
    const t = i / N;
    const y = t * height;
    const ang = t * turns * 2 * Math.PI;
    pts.push(new THREE.Vector3(COIL_RADIUS * Math.cos(ang), y, COIL_RADIUS * Math.sin(ang)));
  }
  const curve = new THREE.CatmullRomCurve3(pts);
  const geo = new THREE.TubeGeometry(curve, 400, WIRE_RADIUS, 8, false);
  springMesh = new THREE.Mesh(geo, standardMaterial(0x30b0c7, GLASS_OPTS));
  scene.add(springMesh);
}

const els = {
  h0: document.getElementById('h0'), n: document.getElementById('n'), speed: document.getElementById('speed'),
  h0Val: document.getElementById('h0Val'), nVal: document.getElementById('nVal'), speedVal: document.getElementById('speedVal'),
};
function syncLabels() {
  els.h0Val.textContent = parseFloat(els.h0.value).toFixed(1);
  els.nVal.textContent = els.n.value;
  els.speedVal.textContent = parseFloat(els.speed.value).toFixed(1) + ' rad/s';
}
[els.h0, els.n].forEach((el) => el.addEventListener('input', syncLabels));
els.speed.addEventListener('input', syncLabels);
syncLabels();

let t = 0;
const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  const dt = Math.min(clock.getDelta(), 0.05);
  const speed = parseFloat(els.speed.value);
  t += speed * dt;

  const H0 = parseFloat(els.h0.value);
  const H1 = H0 * 0.55; // 最大压缩高度（示意值，模拟接近但不到Flim的工作压缩量）
  const compressRatio = (1 - Math.cos(t)) / 2; // 0~1，只压缩不拉伸，模拟Fmin~Fmax往复加载
  const height = H0 - (H0 - H1) * compressRatio;

  buildSpring(height, parseInt(els.n.value));
  loadDisc.position.y = height + 0.05;

  controls.update();
  renderer.render(scene, camera);
}
animate();
