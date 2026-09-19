import * as THREE from 'three';
import { setupScene, standardMaterial, GLASS_OPTS } from '../common.js';

const { scene, camera, renderer, controls } = setupScene({ cameraPos: [0, 2.5, 2.5], target: [0, 0, 0], gridSize: 6 });

const R_I = 0.6, R_O = 1.1;
const R_BALL = (R_O - R_I) / 2;
const R_CAGE = (R_I + R_O) / 2;

const outerRing = new THREE.Mesh(new THREE.TorusGeometry(R_O - 0.06, 0.06, 16, 48), standardMaterial(0x8e8e93));
const innerRing = new THREE.Mesh(new THREE.TorusGeometry(R_I + 0.06, 0.06, 16, 48), standardMaterial(0x007aff, GLASS_OPTS));
scene.add(outerRing, innerRing);

let balls = [];
function buildBalls(n) {
  balls.forEach((b) => scene.remove(b.group));
  balls = [];
  for (let i = 0; i < n; i++) {
    const group = new THREE.Group();
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(R_BALL, 20, 16), standardMaterial(0xff9500));
    const marker = new THREE.Mesh(new THREE.SphereGeometry(R_BALL * 0.22, 10, 8), standardMaterial(0x1c1c1e));
    marker.position.set(R_BALL * 0.85, 0, 0);
    mesh.add(marker);
    group.add(mesh);
    scene.add(group);
    balls.push({ group, mesh, baseAngle: (i * 2 * Math.PI) / n });
  }
}

const els = {
  n: document.getElementById('n'), speed: document.getElementById('speed'),
  nVal: document.getElementById('nVal'), speedVal: document.getElementById('speedVal'),
  cageVal: document.getElementById('cageVal'), ballVal: document.getElementById('ballVal'),
};
function syncLabels() {
  els.nVal.textContent = els.n.value;
  els.speedVal.textContent = parseFloat(els.speed.value).toFixed(1) + ' rad/s';
}
els.n.addEventListener('input', () => { syncLabels(); buildBalls(parseInt(els.n.value)); });
els.speed.addEventListener('input', syncLabels);
syncLabels();
buildBalls(parseInt(els.n.value));

let thetaInner = 0, thetaCage = 0, ballSelfSpin = new Map();
const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  const dt = Math.min(clock.getDelta(), 0.05);
  const wi = parseFloat(els.speed.value);
  const wc = (wi * R_I) / (R_I + R_O); // 外圈固定：wc = wi*ri/(ri+ro)
  const wBallRelative = -(wi - wc) * R_I / R_BALL; // 内圈接触点纯滚动约束
  const wBallAbs = wc + wBallRelative;

  els.cageVal.textContent = wc.toFixed(2) + ' rad/s';
  els.ballVal.textContent = wBallAbs.toFixed(2) + ' rad/s';

  thetaInner += wi * dt;
  thetaCage += wc * dt;
  innerRing.rotation.z = thetaInner;

  balls.forEach((b, i) => {
    const orbitAngle = thetaCage + b.baseAngle;
    b.group.position.set(R_CAGE * Math.cos(orbitAngle), R_CAGE * Math.sin(orbitAngle), 0);
    const prevSpin = ballSelfSpin.get(i) || 0;
    const newSpin = prevSpin + wBallAbs * dt;
    ballSelfSpin.set(i, newSpin);
    b.mesh.rotation.z = newSpin;
  });

  controls.update();
  renderer.render(scene, camera);
}
animate();
