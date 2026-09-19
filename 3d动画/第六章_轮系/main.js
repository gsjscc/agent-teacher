import * as THREE from 'three';
import { setupScene, extrudeGear, standardMaterial, GLASS_OPTS } from '../common.js';

const { scene, camera, renderer, controls } = setupScene({ cameraPos: [0, 6, 0.1], target: [0, 0, 0], gridSize: 6 });

const MODULE = 0.18;
const N_PLANETS = 3;

let sunGear = null, planetGears = [], ringMesh = null, carrierMesh = null;

function rebuild() {
  const zs = parseInt(els.zs.value), zp = parseInt(els.zp.value);
  const zr = zs + 2 * zp; // 同心条件

  if (sunGear) scene.remove(sunGear.mesh);
  planetGears.forEach((p) => scene.remove(p.mesh));
  if (ringMesh) scene.remove(ringMesh);
  if (carrierMesh) scene.remove(carrierMesh);

  sunGear = extrudeGear(zs, MODULE, 0.3, 0x007aff, 1, 1.25, GLASS_OPTS);
  scene.add(sunGear.mesh);

  const orbitR = sunGear.pitchRadius + (MODULE * zp) / 2; // 太阳轮+行星轮分度圆半径
  planetGears = [];
  const carrierGroup = new THREE.Group();
  for (let i = 0; i < N_PLANETS; i++) {
    const g = extrudeGear(zp, MODULE, 0.3, 0x34c759, 1, 1.25, GLASS_OPTS);
    planetGears.push(g);
    scene.add(g.mesh);
  }

  const ringR = (MODULE * zr) / 2;
  const ringGeo = new THREE.TorusGeometry(ringR, 0.03, 8, 64);
  ringMesh = new THREE.Mesh(ringGeo, standardMaterial(0x8e8e93));
  ringMesh.rotation.x = Math.PI / 2;
  scene.add(ringMesh);

  const carrierGeo = new THREE.CylinderGeometry(0.06, 0.06, 0.35, 12);
  carrierMesh = new THREE.Group();
  for (let i = 0; i < N_PLANETS; i++) {
    const arm = new THREE.Mesh(carrierGeo, standardMaterial(0xff9500));
    const a = (i * 2 * Math.PI) / N_PLANETS;
    arm.position.set(orbitR * Math.cos(a), 0, orbitR * Math.sin(a));
    carrierMesh.add(arm);
  }
  scene.add(carrierMesh);

  els.zrVal.textContent = zr;
  const ratio = (zs + zr) / zs;
  els.ratioVal.textContent = ratio.toFixed(2);
  return { zs, zp, zr, orbitR, ratio };
}

const els = {
  zs: document.getElementById('zs'), zp: document.getElementById('zp'), speed: document.getElementById('speed'),
  zsVal: document.getElementById('zsVal'), zpVal: document.getElementById('zpVal'), speedVal: document.getElementById('speedVal'),
  zrVal: document.getElementById('zrVal'), ratioVal: document.getElementById('ratioVal'), carrierSpeedVal: document.getElementById('carrierSpeedVal'),
};
function syncLabels() {
  els.zsVal.textContent = els.zs.value;
  els.zpVal.textContent = els.zp.value;
  els.speedVal.textContent = parseFloat(els.speed.value).toFixed(1) + ' rad/s';
}
[els.zs, els.zp].forEach((el) => el.addEventListener('input', () => { syncLabels(); rebuild(); }));
els.speed.addEventListener('input', syncLabels);
syncLabels();
let params = rebuild();

let thetaSun = 0, thetaCarrier = 0, thetaPlanetSelf = new Array(N_PLANETS).fill(0);
const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  const dt = Math.min(clock.getDelta(), 0.05);
  const ws = parseFloat(els.speed.value);
  const wc = ws * params.zs / (params.zs + params.zr); // 内齿圈固定时：wc = ws * Zs/(Zs+Zr)
  els.carrierSpeedVal.textContent = wc.toFixed(2) + ' rad/s（' + (wc >= 0 ? '同向' : '反向') + '）';

  thetaSun += ws * dt;
  thetaCarrier += wc * dt;

  if (sunGear) sunGear.mesh.rotation.y = thetaSun;
  if (carrierMesh) carrierMesh.rotation.y = thetaCarrier;

  // 行星轮：随系杆公转 + 自转（相对系杆的自转由太阳轮啮合决定：w'_p = -(ws-wc)*Zs/Zp，绝对自转=wc+w'_p）
  const wpRelative = -(ws - wc) * params.zs / params.zp;
  const wpAbsolute = wc + wpRelative;
  for (let i = 0; i < N_PLANETS; i++) {
    thetaPlanetSelf[i] += wpAbsolute * dt;
    const orbitAngle = thetaCarrier + (i * 2 * Math.PI) / N_PLANETS;
    const g = planetGears[i];
    g.mesh.position.set(params.orbitR * Math.cos(orbitAngle), 0, params.orbitR * Math.sin(orbitAngle));
    g.mesh.rotation.y = thetaPlanetSelf[i];
  }

  controls.update();
  renderer.render(scene, camera);
}
animate();
