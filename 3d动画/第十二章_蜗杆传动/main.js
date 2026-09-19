import * as THREE from 'three';
import { setupScene, extrudeGear, standardMaterial, GLASS_OPTS } from '../common.js';

const { scene, camera, renderer, controls } = setupScene({ cameraPos: [3.5, 3, 4.5], target: [1.2, 0, 0], gridSize: 10 });

const MODULE = 0.06;
const WORM_PITCH_R = 0.3; // 蜗杆分度圆半径，独立于模数选取（工程上由蜗杆直径系数q决定），示意固定值
const WORM_LEN = 1.6;

let wormMesh, wheelGear, wheelPivot;

function buildWorm(z1) {
  if (wormMesh) scene.remove(wormMesh);
  wormMesh = new THREE.Group();
  const core = new THREE.Mesh(new THREE.CylinderGeometry(WORM_PITCH_R * 0.6, WORM_PITCH_R * 0.6, WORM_LEN, 24),
    standardMaterial(0x8e8e93));
  core.rotation.z = Math.PI / 2;
  wormMesh.add(core);

  // 螺旋齿：每个头(start)画一条沿螺旋线的管状体，头数=z1，起始相位均分360°/z1
  const turns = 5; // 螺旋圈数，示意值
  for (let k = 0; k < z1; k++) {
    const phase = (k * 2 * Math.PI) / z1;
    const pts = [];
    const N = 200;
    for (let i = 0; i <= N; i++) {
      const t = i / N;
      const x = -WORM_LEN / 2 + t * WORM_LEN;
      const ang = phase + t * turns * 2 * Math.PI;
      pts.push(new THREE.Vector3(x, WORM_PITCH_R * Math.cos(ang), WORM_PITCH_R * Math.sin(ang)));
    }
    const curve = new THREE.CatmullRomCurve3(pts);
    const tubeGeo = new THREE.TubeGeometry(curve, 400, 0.05, 8, false);
    const thread = new THREE.Mesh(tubeGeo, standardMaterial(0x007aff, GLASS_OPTS));
    wormMesh.add(thread);
  }
  scene.add(wormMesh);
}

function buildWheel(z2) {
  if (wheelPivot) scene.remove(wheelPivot);
  wheelGear = extrudeGear(z2, MODULE, 0.28, 0x30b0c7, 1, 1.25, GLASS_OPTS);
  const a = WORM_PITCH_R + wheelGear.pitchRadius;
  // 用一个固定倾斜的父级Group承载"蜗轮轴线与蜗杆轴线垂直交错"这个静态朝向，
  // 齿轮自身只负责绕自己局部Y轴自转，两者分离，避免欧拉角复合顺序搞错自转轴方向
  wheelPivot = new THREE.Group();
  wheelPivot.rotation.x = Math.PI / 2;
  wheelPivot.position.set(a, 0, 0);
  wheelPivot.add(wheelGear.mesh);
  scene.add(wheelPivot);
}

const els = {
  z1: document.getElementById('z1'), z2: document.getElementById('z2'), speed: document.getElementById('speed'),
  z1Val: document.getElementById('z1Val'), z2Val: document.getElementById('z2Val'), speedVal: document.getElementById('speedVal'),
  ratioVal: document.getElementById('ratioVal'), wheelSpeedVal: document.getElementById('wheelSpeedVal'),
};
function syncLabels() {
  els.z1Val.textContent = els.z1.value;
  els.z2Val.textContent = els.z2.value;
  els.speedVal.textContent = parseFloat(els.speed.value).toFixed(1) + ' rad/s';
  const z1 = parseInt(els.z1.value), z2 = parseInt(els.z2.value);
  els.ratioVal.textContent = (z2 / z1).toFixed(1);
}
[els.z1].forEach((el) => el.addEventListener('input', () => { syncLabels(); buildWorm(parseInt(els.z1.value)); }));
[els.z2].forEach((el) => el.addEventListener('input', () => { syncLabels(); buildWheel(parseInt(els.z2.value)); }));
els.speed.addEventListener('input', syncLabels);
syncLabels();
buildWorm(parseInt(els.z1.value));
buildWheel(parseInt(els.z2.value));

let thetaWorm = 0, thetaWheel = 0;
const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  const dt = Math.min(clock.getDelta(), 0.05);
  const z1 = parseInt(els.z1.value), z2 = parseInt(els.z2.value);
  const w1 = parseFloat(els.speed.value);
  const w2 = (w1 * z1) / z2; // i=z2/z1 => w2=w1*z1/z2

  thetaWorm += w1 * dt;
  thetaWheel += w2 * dt;
  els.wheelSpeedVal.textContent = w2.toFixed(2) + ' rad/s';

  if (wormMesh) wormMesh.rotation.x = thetaWorm;
  if (wheelGear) wheelGear.mesh.rotation.y = thetaWheel;

  controls.update();
  renderer.render(scene, camera);
}
animate();
