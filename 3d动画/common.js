// 3D动画公共工具模块——被各章节的 main.js 引入，避免每个机构重复写一遍
// 场景/相机/光照/网格/控制器的样板代码，也避免各自实现的齿轮外形不一致。
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

export function setupScene({ cameraPos = [3, 2.5, 4], target = [0, 0, 0], gridSize = 12 } = {}) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xf4f6f9);

  const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.05, 200);
  camera.position.set(...cameraPos);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(window.devicePixelRatio);
  document.body.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(...target);
  controls.enableDamping = true;

  scene.add(new THREE.AmbientLight(0xffffff, 0.85));
  const dirLight = new THREE.DirectionalLight(0xffffff, 0.7);
  dirLight.position.set(3, 5, 4);
  scene.add(dirLight);
  const rimLight = new THREE.DirectionalLight(0x007aff, 0.25);
  rimLight.position.set(-3, 2, -3);
  scene.add(rimLight);

  const grid = new THREE.GridHelper(gridSize, gridSize * 2, 0xc7d0dc, 0xe6eaf0);
  scene.add(grid);

  window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  return { scene, camera, renderer, controls };
}

// 苹果系统色 + 哑光磨砂质感的默认材质。opts 里传 transparent/opacity/transmission
// 可以做出跟四连杆模拟器一致的玻璃通透效果（用于曲柄/驱动件等重点强调部件）。
export function standardMaterial(color, opts = {}) {
  return new THREE.MeshPhysicalMaterial({ color, roughness: 0.5, metalness: 0.1, ...opts });
}

// 苹果系统色板，供各章节 main.js 统一引用，避免颜色语义在文件间漂移
export const APPLE_COLORS = {
  gray: 0x8e8e93,        // 中性结构件（机架/静止部分）
  grayDark: 0x48484a,    // 深色结构件（基座/固定端）
  grayLight: 0xc7c7cc,   // 浅灰（弱化的次要部件）
  blue: 0x007aff,        // 主强调色（驱动/主动件），常配合玻璃质感使用
  teal: 0x30b0c7,        // 副强调色（从动/次要重点件），常配合玻璃质感使用
  green: 0x34c759,       // 第三强调色（用于需要三色区分的场景，如行星轮）
  orange: 0xff9500,      // 高亮标记（销/球/指示点）
  red: 0xff3b30,         // 警示/参考标记点
};
// 玻璃质感的标准 opts，配合 APPLE_COLORS.blue/teal/green 等强调色使用
export const GLASS_OPTS = { transparent: true, opacity: 0.72, transmission: 0.4, thickness: 0.3 };

/**
 * 生成一个"示意性"齿轮外形（梯形齿近似渐开线，不是真实渐开线曲线）。
 * 目的是让齿数、模数、分度圆半径这些运动学参数正确、啮合传动比正确，
 * 齿形本身做示意化处理——跟四连杆模拟器用圆柱体表示杆件、不做真实截面是同一个简化原则。
 *
 * teeth: 齿数, module: 模数(决定分度圆直径 d=m*z), addendumCoef/dedendumCoef: 齿顶高/齿根高系数(标准值1/1.25)
 */
export function createGearShape(teeth, module, addendumCoef = 1, dedendumCoef = 1.25) {
  const pitchR = (module * teeth) / 2;
  const addR = pitchR + module * addendumCoef;
  const dedR = pitchR - module * dedendumCoef;
  const shape = new THREE.Shape();
  const step = (Math.PI * 2) / teeth;
  const toothWidthRatio = 0.5; // 齿宽占一个齿距的比例（含齿槽），示意值

  for (let i = 0; i < teeth; i++) {
    const a0 = i * step;
    const a1 = a0 + step * toothWidthRatio * 0.5;
    const a2 = a0 + step * toothWidthRatio;
    const a3 = a0 + step;
    const pts = [
      [dedR * Math.cos(a0), dedR * Math.sin(a0)],
      [addR * Math.cos(a1), addR * Math.sin(a1)],
      [addR * Math.cos(a2), addR * Math.sin(a2)],
      [dedR * Math.cos(a3), dedR * Math.sin(a3)],
    ];
    pts.forEach(([x, y], idx) => {
      if (i === 0 && idx === 0) shape.moveTo(x, y);
      else shape.lineTo(x, y);
    });
  }
  shape.closePath();
  return { shape, pitchRadius: pitchR, addendumRadius: addR, dedendumRadius: dedR };
}

export function extrudeGear(teeth, module, thickness = 0.3, color = 0x007aff, addendumCoef = 1, dedendumCoef = 1.25, matOpts = {}) {
  const { shape, pitchRadius } = createGearShape(teeth, module, addendumCoef, dedendumCoef);
  const geo = new THREE.ExtrudeGeometry(shape, { depth: thickness, bevelEnabled: false, curveSegments: 4 });
  geo.rotateX(Math.PI / 2); // 让齿轮平面朝向XZ，轴线沿Y，方便水平放置的轮系
  geo.translate(0, -thickness / 2, 0);
  const mesh = new THREE.Mesh(geo, standardMaterial(color, matOpts));
  return { mesh, pitchRadius };
}

/** 计算两圆外公切线（皮带/链条包角几何），返回两侧切线在两圆上的切点角度。
 * r1,r2: 两圆半径, d: 圆心距。用于带传动/链传动的皮带路径绘制。 */
export function externalTangentAngles(r1, r2, d) {
  const alpha = Math.asin((r1 - r2) / d); // 两圆心连线与切线的夹角
  return {
    // 切线1（"上方"）在圆1、圆2上的角度；切线2（"下方"）对称
    circle1Top: Math.PI / 2 + alpha,
    circle2Top: Math.PI / 2 + alpha,
    circle1Bottom: -Math.PI / 2 - alpha,
    circle2Bottom: -Math.PI / 2 - alpha,
  };
}
