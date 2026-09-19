import * as THREE from 'three';
import { setupScene, standardMaterial, GLASS_OPTS } from '../common.js';

const { scene, camera, renderer, controls } = setupScene({ cameraPos: [2, 1.6, 2.5], target: [0, 0.3, 0], gridSize: 6 });

const group = new THREE.Group();
scene.add(group);
let mode = 'bolt';

function buildHelixThread(radius, len, pitchTurns, color) {
  const pts = [];
  const N = 200;
  for (let i = 0; i <= N; i++) {
    const t = i / N;
    const y = -len / 2 + t * len;
    const ang = t * pitchTurns * 2 * Math.PI;
    pts.push(new THREE.Vector3(radius * Math.cos(ang), y, radius * Math.sin(ang)));
  }
  const curve = new THREE.CatmullRomCurve3(pts);
  const geo = new THREE.TubeGeometry(curve, 300, 0.025, 6, false);
  return new THREE.Mesh(geo, standardMaterial(color));
}

function buildBolt(explode) {
  const g = new THREE.Group();
  const plateGap = 0.05 + explode * 0.5;

  const plate1 = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.12, 0.8), standardMaterial(0x30b0c7, GLASS_OPTS));
  plate1.position.y = 0.06;
  const plate2 = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.12, 0.8), standardMaterial(0x30b0c7, GLASS_OPTS));
  plate2.position.y = -0.06 - plateGap;
  g.add(plate1, plate2);

  const boltGroup = new THREE.Group();
  const shank = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 0.9, 24), standardMaterial(0x8e8e93));
  boltGroup.add(shank);
  boltGroup.add(buildHelixThread(0.09, 0.9, 14, 0x007aff));
  const head = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 0.12, 6), standardMaterial(0x48484a));
  head.position.y = 0.45 + 0.06;
  boltGroup.add(head);
  boltGroup.position.y = 0.35 * explode;
  g.add(boltGroup);

  const nut = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 0.16, 6), standardMaterial(0xff9500));
  nut.position.y = -0.45 - plateGap - 0.35 * explode;
  g.add(nut);

  return g;
}

function buildKey(explode) {
  const g = new THREE.Group();
  const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.3, 1.4, 32), standardMaterial(0x8e8e93));
  shaft.rotation.z = Math.PI / 2;
  g.add(shaft);

  const key = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.1, 0.16), standardMaterial(0x007aff, GLASS_OPTS));
  key.position.set(0, 0.3, 0);
  g.add(key);

  const hub = new THREE.Group();
  const hubBody = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.55, 0.4, 32), standardMaterial(0x30b0c7, { ...GLASS_OPTS, ...{ transparent: true, opacity: 0.75 } }));
  hubBody.rotation.z = Math.PI / 2;
  hub.add(hubBody);
  hub.position.x = 0.6 * explode + 0.0;
  g.add(hub);

  return g;
}

function buildPin(explode) {
  const g = new THREE.Group();
  const gap = 0.06 + explode * 0.6;
  const plate1 = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.1, 0.5), standardMaterial(0x30b0c7, GLASS_OPTS));
  plate1.position.x = -0.05 - gap / 2;
  const plate2 = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.1, 0.5), standardMaterial(0x30b0c7, GLASS_OPTS));
  plate2.position.x = 0.05 + gap / 2;
  g.add(plate1, plate2);

  const pin = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 1.3, 20), standardMaterial(0xff9500));
  pin.rotation.z = Math.PI / 2;
  pin.position.y = 0.06;
  g.add(pin);

  return g;
}

const els = {
  explode: document.getElementById('explode'), explodeVal: document.getElementById('explodeVal'),
  info: document.getElementById('info'),
  tabBolt: document.getElementById('tabBolt'), tabKey: document.getElementById('tabKey'), tabPin: document.getElementById('tabPin'),
};

function rebuild() {
  group.clear();
  const e = parseFloat(els.explode.value);
  let mesh;
  if (mode === 'bolt') mesh = buildBolt(e);
  else if (mode === 'key') mesh = buildKey(e);
  else mesh = buildPin(e);
  group.add(mesh);
}

function updateInfo() {
  const texts = {
    bolt: '螺栓从下往上穿过两块被连接件，螺母在下方旋合。拧紧后螺栓杆产生预紧拉力，被连接件间产生预紧压力——这就是"紧螺栓连接"的预紧原理。',
    key: '平键两侧面是工作面（靠挤压传递转矩），上表面与轮毂键槽底面留有间隙，不是工作面。轴上键槽和轮毂键槽装配后，键同时嵌入两者。',
    pin: '圆柱销利用微量过盈固定在两块板的销孔中，主要用于固定零件的相对位置，也可传递不大的载荷。多次装拆会降低定位精度。',
  };
  els.info.textContent = texts[mode];
}

function setMode(m) {
  mode = m;
  els.tabBolt.classList.toggle('active', m === 'bolt');
  els.tabKey.classList.toggle('active', m === 'key');
  els.tabPin.classList.toggle('active', m === 'pin');
  rebuild();
  updateInfo();
}
els.tabBolt.addEventListener('click', () => setMode('bolt'));
els.tabKey.addEventListener('click', () => setMode('key'));
els.tabPin.addEventListener('click', () => setMode('pin'));
els.explode.addEventListener('input', () => {
  els.explodeVal.textContent = parseFloat(els.explode.value) < 0.5 ? '装配' : '分解';
  rebuild();
});

setMode('bolt');

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}
animate();
