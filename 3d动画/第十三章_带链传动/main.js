import * as THREE from 'three';
import { setupScene, standardMaterial, createGearShape, GLASS_OPTS } from '../common.js';

const { scene, camera, renderer, controls } = setupScene({ cameraPos: [1.5, 0, 4.2], target: [1.5, 0, 0], gridSize: 8 });

const CENTER_DIST = 2.6;
let mode = 'belt';

const group = new THREE.Group();
scene.add(group);

function tangentGeometry(r1, r2, d) {
  const alpha = Math.asin((r1 - r2) / d);
  const topAngle = Math.PI / 2 + alpha;   // 圆1、圆2上侧切点角度（同一方向角，外公切线的性质）
  const botAngle = -Math.PI / 2 - alpha;  // 下侧切点角度
  return { alpha, topAngle, botAngle };
}

function pointOnCircle(cx, cy, r, angle) {
  return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
}

// 皮带用细管沿中心线路径包一圈来表示（而不是填充式Shape——填充会把带轮之间整块区域填满，
// 不是想要的"细带子"效果），中心线路径复用 samplePath() 同一套切线+圆弧几何，保证带/链共用一套正确的路径计算
function buildBeltTube(r1, r2, d) {
  const pts2d = samplePath(r1, r2, d, 80);
  const pts3d = pts2d.map(([x, y]) => new THREE.Vector3(x, y, 0));
  const curve = new THREE.CatmullRomCurve3(pts3d, true, 'catmullrom', 0.05);
  const geo = new THREE.TubeGeometry(curve, 160, 0.045, 8, true);
  return geo;
}

// 采样皮带/链条中心线路径上的点（用于放置链节），沿同样的切线+圆弧几何
function samplePath(r1, r2, d, n) {
  const { topAngle, botAngle } = tangentGeometry(r1, r2, d);
  const pts = [];
  const [p1tx, p1ty] = pointOnCircle(0, 0, r1, topAngle);
  const [p2tx, p2ty] = pointOnCircle(d, 0, r2, topAngle);
  const [p2bx, p2by] = pointOnCircle(d, 0, r2, botAngle);
  const [p1bx, p1by] = pointOnCircle(0, 0, r1, botAngle);

  const lenTopLine = Math.hypot(p2tx - p1tx, p2ty - p1ty);
  const arc2 = r2 * ((topAngle - botAngle + 2 * Math.PI) % (2 * Math.PI)); // 顺时针经过0，跨度
  const lenBotLine = Math.hypot(p1bx - p2bx, p1by - p2by);
  const arc1 = r1 * ((topAngle - botAngle + 2 * Math.PI) % (2 * Math.PI) === 0 ? 0 : (2 * Math.PI - ((topAngle - botAngle + 2 * Math.PI) % (2 * Math.PI))));
  const total = lenTopLine + arc2 + lenBotLine + arc1;

  for (let i = 0; i < n; i++) {
    let s = (total * i) / n;
    if (s < lenTopLine) {
      const t = s / lenTopLine;
      pts.push([p1tx + (p2tx - p1tx) * t, p1ty + (p2ty - p1ty) * t]);
      continue;
    }
    s -= lenTopLine;
    if (s < arc2) {
      const sweep = (topAngle - botAngle + 2 * Math.PI) % (2 * Math.PI);
      const ang = topAngle - (s / arc2) * sweep;
      pts.push(pointOnCircle(d, 0, r2, ang));
      continue;
    }
    s -= arc2;
    if (s < lenBotLine) {
      const t = s / lenBotLine;
      pts.push([p2bx + (p1bx - p2bx) * t, p2by + (p1by - p2by) * t]);
      continue;
    }
    s -= lenBotLine;
    const sweep1 = 2 * Math.PI - ((topAngle - botAngle + 2 * Math.PI) % (2 * Math.PI));
    const ang = botAngle - (s / arc1) * sweep1;
    pts.push(pointOnCircle(0, 0, r1, ang));
  }
  return pts;
}

let pulley1, pulley2, beltMesh, chainLinks = [];

function rebuild() {
  group.clear();
  const r1 = parseFloat(els.r1.value), r2 = parseFloat(els.r2.value);
  const d = CENTER_DIST;

  if (mode === 'belt') {
    pulley1 = new THREE.Mesh(new THREE.CylinderGeometry(r1, r1, 0.25, 32), standardMaterial(0x007aff, GLASS_OPTS));
    pulley2 = new THREE.Mesh(new THREE.CylinderGeometry(r2, r2, 0.25, 32), standardMaterial(0x30b0c7, GLASS_OPTS));
    pulley1.rotation.x = Math.PI / 2;
    pulley2.rotation.x = Math.PI / 2;
    pulley2.position.x = d;
    group.add(pulley1, pulley2);

    const geo = buildBeltTube(r1 * 1.02, r2 * 1.02, d);
    beltMesh = new THREE.Mesh(geo, standardMaterial(0x48484a));
    group.add(beltMesh);
  } else {
    const { shape: s1 } = createGearShape(16, r1 * 2 / 16 * 1.0, 1, 1.25); // 用齿数16近似示意链轮，齿数与半径挂钩不必严格
    const geo1 = new THREE.ExtrudeGeometry(s1, { depth: 0.15, bevelEnabled: false });
    pulley1 = new THREE.Mesh(geo1, standardMaterial(0x007aff, GLASS_OPTS));
    const { shape: s2 } = createGearShape(Math.round(16 * r2 / r1), r1 * 2 / 16 * 1.0, 1, 1.25);
    const geo2 = new THREE.ExtrudeGeometry(s2, { depth: 0.15, bevelEnabled: false });
    pulley2 = new THREE.Mesh(geo2, standardMaterial(0x30b0c7, GLASS_OPTS));
    pulley2.position.x = d;
    group.add(pulley1, pulley2);

    const n = 60;
    const pts = samplePath(r1, r2, d, n);
    chainLinks = pts.map(([x, y]) => {
      const link = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.08, 0.1), standardMaterial(0x8e8e93));
      link.position.set(x, y, 0);
      group.add(link);
      return link;
    });
  }
}

const els = {
  r1: document.getElementById('r1'), r2: document.getElementById('r2'), speed: document.getElementById('speed'), slip: document.getElementById('slip'),
  r1Val: document.getElementById('r1Val'), r2Val: document.getElementById('r2Val'), speedVal: document.getElementById('speedVal'), slipVal: document.getElementById('slipVal'),
  info: document.getElementById('info'), slipRow: document.getElementById('slipRow'),
  tabBelt: document.getElementById('tabBelt'), tabChain: document.getElementById('tabChain'),
};
function syncLabels() {
  els.r1Val.textContent = parseFloat(els.r1.value).toFixed(2);
  els.r2Val.textContent = parseFloat(els.r2.value).toFixed(2);
  els.speedVal.textContent = parseFloat(els.speed.value).toFixed(1) + ' rad/s';
  els.slipVal.textContent = els.slip.value + '%';
}
function updateInfo() {
  const r1 = parseFloat(els.r1.value), r2 = parseFloat(els.r2.value);
  if (mode === 'belt') {
    els.info.innerHTML = `理想传动比 i=r2/r1=${(r2/r1).toFixed(2)}<br>摩擦型带传动存在弹性滑动，实际从动轮转速会比理论值略低（拖动上方滑块示意打滑影响），链传动无此现象`;
  } else {
    els.info.innerHTML = `链传动靠链轮轮齿与链节啮合，无弹性滑动，传动比准确=r2/r1=${(r2/r1).toFixed(2)}<br>瞬时传动比因链节多边形效应并不恒定，但平均传动比精确`;
  }
}
[els.r1, els.r2].forEach((el) => el.addEventListener('input', () => { syncLabels(); rebuild(); updateInfo(); }));
[els.speed, els.slip].forEach((el) => el.addEventListener('input', syncLabels));

function setMode(m) {
  mode = m;
  els.slipRow.style.display = m === 'belt' ? '' : 'none';
  els.tabBelt.classList.toggle('active', m === 'belt');
  els.tabChain.classList.toggle('active', m === 'chain');
  rebuild();
  updateInfo();
}
els.tabBelt.addEventListener('click', () => setMode('belt'));
els.tabChain.addEventListener('click', () => setMode('chain'));

syncLabels();
setMode('belt');

let theta1 = 0;
const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  const dt = Math.min(clock.getDelta(), 0.05);
  const r1 = parseFloat(els.r1.value), r2 = parseFloat(els.r2.value);
  const w1 = parseFloat(els.speed.value);
  const slip = mode === 'belt' ? parseFloat(els.slip.value) / 100 : 0;
  const w2 = (w1 * r1 / r2) * (1 - slip); // 无滑动时线速度相等 w1r1=w2r2；打滑时从动轮打折

  theta1 += w1 * dt;
  const theta2Delta = w2 * dt;

  if (pulley1) pulley1.rotation.z += (mode === 'belt' ? w1 * dt : w1 * dt);
  if (pulley2) pulley2.rotation.z += theta2Delta;

  if (mode === 'chain') {
    // 链节沿路径整体平移示意运动（近似：按线速度让采样点索引整体偏移，简化处理，不做逐链节精确相位）
    const speedAlong = w1 * r1;
    chainLinks.forEach((link) => {
      link.position.x += 0; // 链轮啮合位置已由sprocket旋转体现，链节此处仅作静态示意点缀，不额外平移避免与sprocket旋转不同步造成穿模观感
    });
  }

  controls.update();
  renderer.render(scene, camera);
}
animate();
