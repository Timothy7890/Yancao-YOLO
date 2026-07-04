import { createApp, reactive, ref, nextTick, onMounted } from "vue";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const CORNER_NAMES = ["左上 TL", "右上 TR", "右下 BR", "左下 BL"];

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) { /* ignore */ }
    throw new Error(msg);
  }
  return r.json();
}

// Three.js (模块级, 不放进 Vue 响应式)
const T = {
  scene: null, camera: null, renderer: null, controls: null,
  meshes: {}, edges: null, imgCache: {}, raf: 0,
};

function orientCanvas(img, rot, flip) {
  const iw = img.naturalWidth || img.width;
  const ih = img.naturalHeight || img.height;
  let cw = iw, ch = ih;
  if (rot === 90 || rot === 270) { cw = ih; ch = iw; }
  const cv = document.createElement("canvas");
  cv.width = cw; cv.height = ch;
  const ctx = cv.getContext("2d");
  ctx.translate(cw / 2, ch / 2);
  ctx.rotate((rot * Math.PI) / 180);
  if (flip) ctx.scale(-1, 1);
  ctx.drawImage(img, -iw / 2, -ih / 2);
  return cv;
}

function loadImage(url) {
  if (T.imgCache[url]) return Promise.resolve(T.imgCache[url]);
  return new Promise((resolve, reject) => {
    const im = new Image();
    im.onload = () => { T.imgCache[url] = im; resolve(im); };
    im.onerror = reject;
    im.src = url;
  });
}

function disposeScene() {
  if (T.raf) cancelAnimationFrame(T.raf);
  if (T.renderer) T.renderer.dispose();
  T.scene = null; T.camera = null; T.renderer = null; T.controls = null;
  T.meshes = {}; T.edges = null;
}

createApp({
  setup() {
    const loaded = ref(false);
    const products = ref([]);
    const product = ref("");
    const step = ref(1);
    const busy = ref(false);
    const msg = ref("");
    const msgOk = ref(false);

    const dims = reactive({ length_x: 88, width_y: 22, height_z: 55, units: "mm" });
    const state = reactive({
      raw: [], faces_available: [], face_order: [], faces_meta: {},
    });

    const activeFace = ref("front");
    const rawSel = ref(null);
    const corners = reactive([]);
    const pickCanvas = ref(null);
    const previewVer = reactive({});
    let curImg = null;
    let drawScale = 1;

    const assign = reactive({});
    const view3d = ref(null);

    function setMsg(t, ok = false) { msg.value = t; msgOk.value = ok; }
    function hasState() { return !!product.value && state.face_order.length > 0; }
    function faceStatus(face) {
      return !!(state.faces_meta[face] && state.faces_meta[face].image);
    }

    // ---- 产品 ----
    async function loadProducts() {
      products.value = (await api("/api/products")).products;
    }

    async function newProduct() {
      const name = (window.prompt("新建产品名 (字母/数字/下划线/中文):", "") || "").trim();
      if (!name) return;
      busy.value = true;
      try {
        await api("/api/products", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name }),
        });
        await loadProducts();
        await selectProduct(name);
        setMsg(`已创建产品 ${name}, 请把原图放到 build_yanhe/${name}/raw/ 后刷新`, true);
      } catch (e) { setMsg("新建失败: " + e.message); }
      busy.value = false;
    }

    async function selectProduct(name) {
      product.value = name;
      T.imgCache = {};                 // 换产品清图片缓存 (同名 front.png 但不同图)
      corners.splice(0); rawSel.value = null; curImg = null;
      await loadState();
      if (step.value === 2) { await nextTick(); initThree(); }
    }

    // ---- 状态 ----
    async function loadState() {
      if (!product.value) return;
      const s = await api(`/api/state?product=${encodeURIComponent(product.value)}`);
      Object.assign(state, {
        raw: s.raw, faces_available: s.faces_available,
        face_order: s.face_order, faces_meta: s.faces_meta,
      });
      if (s.dims) {
        dims.length_x = s.dims.length_x; dims.width_y = s.dims.width_y;
        dims.height_z = s.dims.height_z; dims.units = s.dims.units || "mm";
      } else {
        dims.length_x = 88; dims.width_y = 22; dims.height_z = 55; dims.units = "mm";
      }
      for (const f of s.face_order) {
        let a = { image: null, rot: 0, flip: false };
        if (s.model && s.model.faces && s.model.faces[f]) {
          const mf = s.model.faces[f];
          a.image = mf.image ? mf.image.split("/").pop() : (faceStatus(f) ? `${f}.png` : null);
          a.rot = mf.texture_rotation_cw_deg || 0;
          a.flip = !!mf.texture_flip_horizontal;
        } else if (state.faces_meta[f] && state.faces_meta[f].image) {
          a.image = state.faces_meta[f].image;
        }
        assign[f] = a;
        previewVer[f] = (previewVer[f] || 0) + 1;
      }
    }

    async function saveDims() {
      busy.value = true;
      try {
        await api("/api/dims", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ product: product.value, ...dims }),
        });
        await loadState();
        setMsg("尺寸已保存", true);
      } catch (e) { setMsg("保存尺寸失败: " + e.message); }
      busy.value = false;
    }

    // ---- step1 画布 ----
    function faceUrl(face) {
      return `/faces/${encodeURIComponent(product.value)}/${face}.png?v=${previewVer[face] || 0}`;
    }
    function facesFileUrl(name) {
      const f = name.replace(/\.png$/i, "");
      return `/faces/${encodeURIComponent(product.value)}/${name}?v=${previewVer[f] || 0}`;
    }
    function rawUrl(name) {
      return `/raw/${encodeURIComponent(product.value)}/${name}`;
    }

    function drawPick() {
      const cv = pickCanvas.value;
      if (!cv || !curImg) return;
      const maxW = 900, maxH = 620;
      drawScale = Math.min(maxW / curImg.naturalWidth, maxH / curImg.naturalHeight, 1);
      cv.width = Math.round(curImg.naturalWidth * drawScale);
      cv.height = Math.round(curImg.naturalHeight * drawScale);
      const ctx = cv.getContext("2d");
      ctx.clearRect(0, 0, cv.width, cv.height);
      ctx.drawImage(curImg, 0, 0, cv.width, cv.height);
      if (corners.length > 0) {
        ctx.lineWidth = 2; ctx.strokeStyle = "#4c9aff";
        ctx.fillStyle = "rgba(76,154,255,0.15)";
        ctx.beginPath();
        corners.forEach((p, i) => {
          const x = p.x * drawScale, y = p.y * drawScale;
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        if (corners.length === 4) ctx.closePath();
        ctx.stroke();
        if (corners.length === 4) ctx.fill();
      }
      corners.forEach((p, i) => {
        const x = p.x * drawScale, y = p.y * drawScale;
        ctx.fillStyle = "#ffcc33";
        ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = "#000"; ctx.font = "bold 11px sans-serif";
        ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillText(String(i + 1), x, y);
      });
    }

    async function selectRaw(name) {
      rawSel.value = name;
      corners.splice(0);
      curImg = await loadImage(rawUrl(name));
      await nextTick();
      drawPick();
    }

    function onCanvasClick(ev) {
      if (!curImg || corners.length >= 4) return;
      const cv = pickCanvas.value;
      const rect = cv.getBoundingClientRect();
      const x = (ev.clientX - rect.left) * (cv.width / rect.width) / drawScale;
      const y = (ev.clientY - rect.top) * (cv.height / rect.height) / drawScale;
      corners.push({ x, y });
      drawPick();
    }
    function undoCorner() { corners.pop(); drawPick(); }
    function clearCorners() { corners.splice(0); drawPick(); }

    async function selectFace(face) {
      activeFace.value = face;
      corners.splice(0);
      rawSel.value = null; curImg = null;
      await nextTick();
      const cv = pickCanvas.value;
      if (cv) cv.getContext("2d").clearRect(0, 0, cv.width, cv.height);
    }

    async function doRectify() {
      if (corners.length !== 4) { setMsg("请先点满 4 个角"); return; }
      if (!rawSel.value) { setMsg("请先选一张原图"); return; }
      busy.value = true;
      try {
        const r = await api("/api/rectify", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            product: product.value, src: rawSel.value, face: activeFace.value,
            corners: corners.map((p) => [p.x, p.y]),
          }),
        });
        const face = activeFace.value;
        previewVer[face] = (previewVer[face] || 0) + 1;
        state.faces_meta[face].image = r.image;
        if (!state.faces_available.includes(r.image)) state.faces_available.push(r.image);
        assign[face] = { image: r.image, rot: 0, flip: false };
        delete T.imgCache[`/faces/${product.value}/${r.image}`];
        setMsg(`已校正 ${face} 面 (${r.size[0]}x${r.size[1]}px)`, true);
      } catch (e) { setMsg("校正失败: " + e.message); }
      busy.value = false;
    }

    // ---- step2 three ----
    function makeFaceMesh(face) {
      const c = state.faces_meta[face].corners;
      const pos = new Float32Array([
        ...c[0], ...c[1], ...c[2],
        ...c[0], ...c[2], ...c[3],
      ]);
      const uv = new Float32Array([0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1]);
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      g.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
      g.computeVertexNormals();
      const mat = new THREE.MeshBasicMaterial({ color: 0xbfc3cc, side: THREE.DoubleSide });
      return new THREE.Mesh(g, mat);
    }

    async function updateFaceTexture(face) {
      const mesh = T.meshes[face];
      if (!mesh) return;
      const a = assign[face];
      if (!a || !a.image) {
        mesh.material.map = null;
        mesh.material.color.set(0xbfc3cc);
        mesh.material.needsUpdate = true;
        if (T.renderer) T.renderer.render(T.scene, T.camera);
        return;
      }
      const url = `/faces/${encodeURIComponent(product.value)}/${a.image}?v=${previewVer[a.image.replace(/\.png$/i, "")] || 0}`;
      const img = await loadImage(url);
      const cv = orientCanvas(img, a.rot % 360, a.flip);
      const tex = new THREE.CanvasTexture(cv);
      tex.flipY = false;
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.needsUpdate = true;
      mesh.material.map = tex;
      mesh.material.color.set(0xffffff);
      mesh.material.needsUpdate = true;
      if (T.renderer) T.renderer.render(T.scene, T.camera);
    }

    function initThree() {
      disposeScene();
      const host = view3d.value;
      const w = host.clientWidth, h = host.clientHeight;
      T.scene = new THREE.Scene();
      T.scene.background = new THREE.Color(0x0c0e12);
      const maxDim = Math.max(dims.length_x, dims.width_y, dims.height_z);
      T.camera = new THREE.PerspectiveCamera(45, w / h, maxDim * 0.01, maxDim * 100);
      T.camera.up.set(0, 0, 1);
      const midZ = dims.height_z / 2;
      T.camera.position.set(maxDim * 2.2, -maxDim * 1.4, maxDim * 1.2 + midZ);
      T.renderer = new THREE.WebGLRenderer({ antialias: true });
      T.renderer.setPixelRatio(window.devicePixelRatio);
      T.renderer.setSize(w, h);
      host.innerHTML = "";
      host.appendChild(T.renderer.domElement);
      T.controls = new OrbitControls(T.camera, T.renderer.domElement);
      T.controls.target.set(0, 0, midZ);
      T.controls.update();

      const boxGeo = new THREE.BoxGeometry(dims.length_x, dims.width_y, dims.height_z);
      T.edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(boxGeo),
        new THREE.LineBasicMaterial({ color: 0x4c9aff }));
      T.edges.position.z = midZ;
      T.scene.add(T.edges);
      const axes = new THREE.AxesHelper(maxDim * 0.7);
      axes.setColors(new THREE.Color(0xff3b30), new THREE.Color(0x30d158),
                     new THREE.Color(0x0a84ff));
      T.scene.add(axes);

      for (const f of state.face_order) {
        const mesh = makeFaceMesh(f);
        T.meshes[f] = mesh;
        T.scene.add(mesh);
      }
      for (const f of state.face_order) updateFaceTexture(f);

      const animate = () => {
        T.raf = requestAnimationFrame(animate);
        T.controls.update();
        T.renderer.render(T.scene, T.camera);
      };
      animate();
      window.addEventListener("resize", onResize);
    }

    function onResize() {
      if (!T.renderer || !view3d.value) return;
      const w = view3d.value.clientWidth, h = view3d.value.clientHeight;
      T.camera.aspect = w / h; T.camera.updateProjectionMatrix();
      T.renderer.setSize(w, h);
    }

    async function goStep(n) {
      step.value = n;
      if (n === 2) { await nextTick(); initThree(); }
      else { disposeScene(); await nextTick(); if (rawSel.value) drawPick(); }
    }

    function cycleRot(face) {
      assign[face].rot = (assign[face].rot + 90) % 360;
      updateFaceTexture(face);
    }
    function toggleFlip(face) {
      assign[face].flip = !assign[face].flip;
      updateFaceTexture(face);
    }
    function setFaceImage(face, name) {
      assign[face].image = name || null;
      updateFaceTexture(face);
    }

    async function saveModel() {
      busy.value = true;
      try {
        const facesPayload = {};
        for (const f of state.face_order) {
          const a = assign[f] || {};
          facesPayload[f] = { image: a.image || null, rot: a.rot || 0, flip: !!a.flip };
        }
        const r = await api("/api/model", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ product: product.value, dims, faces: facesPayload }),
        });
        setMsg("已保存 -> " + r.path, true);
      } catch (e) { setMsg("保存失败: " + e.message); }
      busy.value = false;
    }

    onMounted(async () => {
      try {
        await loadProducts();
        if (products.value.length) await selectProduct(products.value[0]);
      } catch (e) { setMsg("加载失败: " + e.message); }
      loaded.value = true;
    });

    return {
      loaded, products, product, step, busy, msg, msgOk, dims, state, CORNER_NAMES,
      activeFace, rawSel, corners, pickCanvas, view3d, assign,
      hasState, faceStatus, faceUrl, facesFileUrl, rawUrl,
      loadProducts, newProduct, selectProduct,
      saveDims, selectFace, selectRaw, onCanvasClick, undoCorner, clearCorners,
      doRectify, goStep, cycleRot, toggleFlip, setFaceImage, saveModel,
    };
  },
  template: `
<header>
  <h1>烟盒三维建模</h1>
  <div class="dims">
    <label>产品</label>
    <select :value="product" @change="selectProduct($event.target.value)"
            :style="{minWidth:'110px'}">
      <option v-if="!products.length" value="">（无, 先新建）</option>
      <option v-for="p in products" :key="p" :value="p">{{ p }}</option>
    </select>
    <button @click="newProduct" :disabled="busy">+ 新建</button>
  </div>
  <div class="dims" v-if="product">
    <label>长 X</label><input v-model.number="dims.length_x" />
    <label>宽 Y</label><input v-model.number="dims.width_y" />
    <label>高 Z</label><input v-model.number="dims.height_z" />
    <label>单位</label><input type="text" v-model="dims.units" style="width:44px" />
    <button @click="saveDims" :disabled="busy">保存尺寸</button>
  </div>
  <span class="msg" :class="{ok: msgOk}">{{ msg }}</span>
  <div class="tabs" v-if="product">
    <button :class="{active: step===1}" @click="goStep(1)">① 校正去背景</button>
    <button :class="{active: step===2}" @click="goStep(2)">② 3D 放置</button>
  </div>
</header>

<main v-if="hasState()">
  <template v-if="step===1">
    <div class="left-col col">
      <div class="hint">原图 (raw)</div>
      <div class="thumbs">
        <div v-if="!state.raw.length" class="hint">
          该产品还没有原图。<br/>把照片放到<br/>build_yanhe/{{ product }}/raw/<br/>后刷新页面。
        </div>
        <div v-for="name in state.raw" :key="name" class="thumb"
             :class="{sel: rawSel===name}" @click="selectRaw(name)">
          <img :src="rawUrl(name)" loading="lazy" />
          <div class="cap">{{ name }}</div>
        </div>
      </div>
    </div>

    <div class="center-col col">
      <div class="faces-bar">
        <button v-for="f in state.face_order" :key="f" class="face-btn"
                :class="{active: activeFace===f}" @click="selectFace(f)">
          <span class="dot" :class="{filled: faceStatus(f)}"></span>
          {{ f }} {{ state.faces_meta[f].cn }}
        </button>
      </div>
      <div class="hint">
        为 <b>{{ activeFace }} / {{ state.faces_meta[activeFace].cn }}</b> 面:
        左侧选一张原图 → 在图上按顺序点 4 角
        <b>左上 → 右上 → 右下 → 左下</b>
        （已点 {{ corners.length }}/4<span v-if="corners.length<4">，下一个：{{ CORNER_NAMES[corners.length] }}</span>）
      </div>
      <div class="canvas-wrap">
        <canvas class="pick" ref="pickCanvas" @click="onCanvasClick"></canvas>
      </div>
      <div class="toolbar">
        <button @click="undoCorner" :disabled="!corners.length">撤销上一点</button>
        <button @click="clearCorners" :disabled="!corners.length">清空</button>
        <button class="primary" @click="doRectify" :disabled="busy || corners.length!==4">校正并保存</button>
      </div>
    </div>

    <div class="right-col col">
      <h3>{{ activeFace }} 面预览</h3>
      <img class="preview" v-if="faceStatus(activeFace)" :src="faceUrl(activeFace)" />
      <div v-else class="hint">尚未校正</div>
      <h3 style="margin-top:14px">全部面</h3>
      <div v-for="f in state.face_order" :key="f" style="margin-bottom:6px">
        <span class="dot" :class="{filled: faceStatus(f)}"></span>
        {{ f }} {{ state.faces_meta[f].cn }}
        <span style="color:var(--muted)">{{ faceStatus(f) ? '✓' : '—' }}</span>
      </div>
    </div>
  </template>

  <template v-else>
    <div class="view3d" ref="view3d"></div>
    <div class="side">
      <h3>把图贴到各面 · 拖动旋转视角</h3>
      <div v-for="f in state.face_order" :key="f" class="face-row">
        <div class="head">
          <b>{{ f }} {{ state.faces_meta[f].cn }}</b>
          <span class="sz" v-if="state.faces_meta[f].size_units">
            {{ state.faces_meta[f].size_units[0] }}×{{ state.faces_meta[f].size_units[1] }} {{ dims.units }}
          </span>
        </div>
        <div class="ctrls">
          <img class="mini" v-if="assign[f] && assign[f].image" :src="facesFileUrl(assign[f].image)" />
          <select :value="assign[f] ? assign[f].image : ''"
                  @change="setFaceImage(f, $event.target.value)">
            <option value="">（无）</option>
            <option v-for="n in state.faces_available" :key="n" :value="n">{{ n }}</option>
          </select>
        </div>
        <div class="ctrls" style="margin-top:6px">
          <button @click="cycleRot(f)">旋转90°<span v-if="assign[f]"> ({{ assign[f].rot }}°)</span></button>
          <button @click="toggleFlip(f)">翻转<span v-if="assign[f] && assign[f].flip"> ✓</span></button>
        </div>
      </div>
      <button class="primary" style="width:100%" @click="saveModel" :disabled="busy">
        保存 box_model.json
      </button>
      <div class="footnote">
        约定: X=长 Y=宽 Z=高, 前/后面在 YOZ 平面(正面 front 朝 +X), 原点=底面中心。
        彩色轴: <span style="color:#ff3b30">红X</span>
        <span style="color:#30d158">绿Y</span> <span style="color:#0a84ff">蓝Z</span>。
        导出后用 blender_build.py --product {{ product }} 生成 .blend。
      </div>
    </div>
  </template>
</main>
<div v-else-if="loaded" style="padding:40px;color:var(--muted)">
  {{ product ? '加载中…' : '请在左上角选择或“+ 新建”一个产品(SKU)。' }}
</div>
<div v-else style="padding:40px;color:var(--muted)">加载中…</div>
`,
}).mount("#app");
