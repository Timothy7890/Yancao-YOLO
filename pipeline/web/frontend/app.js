import { createApp, reactive, onMounted } from "vue";

const App = {
  setup() {
    const s = reactive({
      skus: [],                 // [{name, dims_mm, built, count}]
      layers: [1, 2],
      layersText: "1,2",
      yaw: [-25, 25],
      posJitter: 0.008,
      topPower: [150, 260],
      ambient: [0.3, 0.55],
      num: 8,
      saveDir: "output/webset",
      variant: "dist",
      running: false,
      status: null,             // {type, msg}
      images: [],
    });

    async function loadSkus() {
      const r = await fetch("/api/skus");
      const d = await r.json();
      s.skus = d.skus.map((x) => ({ ...x, count: x.name.includes("Huangjinye") ? 1 : 0 }));
      s.layers = d.camera_layers;
      s.layersText = d.camera_layers.join(",");
      s.yaw = d.defaults.yaw;
      s.posJitter = d.defaults.pos_jitter;
      s.topPower = d.defaults.top_power;
      s.ambient = d.defaults.ambient;
    }

    async function render() {
      const skus = s.skus.filter((x) => x.count > 0).map((x) => ({ name: x.name, count: x.count }));
      if (!skus.length) { s.status = { type: "err", msg: "请至少给一种 SKU 设条数>0" }; return; }
      const layers = s.layersText.split(",").map((x) => parseInt(x.trim())).filter((x) => !isNaN(x));
      s.running = true;
      s.status = { type: "run", msg: "渲染中… (调 Blender 无头渲染 + 加畸变 + 写 labelme, 请稍候)" };
      s.images = [];
      try {
        const r = await fetch("/api/render", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            skus, yaw: s.yaw.map(Number), pos_jitter: Number(s.posJitter), layers,
            top_power: s.topPower.map(Number), ambient: s.ambient.map(Number),
            num: Number(s.num), save_dir: s.saveDir, variant: s.variant,
          }),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || "render failed");
        s.status = { type: "ok", msg: `完成 ${d.count} 张 -> ${d.dir}` };
        s.images = d.images;
      } catch (e) {
        s.status = { type: "err", msg: String(e.message || e) };
      } finally {
        s.running = false;
      }
    }

    onMounted(loadSkus);
    return { s, render };
  },
  template: `
  <div class="wrap">
    <h1>烟草合成数据集工具</h1>
    <div class="sub">选品 → 条数 → 变化范围 → 张数 → 保存位置; 后端调 Blender 出图并写 labelme(PNG + JSON)到 &lt;保存位置&gt;/raw_img_json/</div>
    <div class="grid">
      <div>
        <div class="card">
          <h2>SKU 与条数</h2>
          <div v-for="k in s.skus" :key="k.name" class="sku">
            <span class="nm">{{ k.name }}
              <span class="dim" v-if="k.dims_mm">{{ k.dims_mm.join('×') }}mm</span>
              <span class="dim" v-if="!k.built" style="color:#d46b08">(未构建,会自动构建)</span>
            </span>
            <input type="number" min="0" v-model.number="k.count" />
          </div>
          <div class="hint">条数=每张图里各放几条(受该层格位数上限约束)。</div>
        </div>

        <div class="card">
          <h2>变化范围</h2>
          <div class="row"><label>偏航°</label>
            <div class="range"><input class="short" type="number" v-model.number="s.yaw[0]" /><span>~</span>
            <input class="short" type="number" v-model.number="s.yaw[1]" /></div></div>
          <div class="row"><label>平移抖动m</label><input class="short" type="number" step="0.001" v-model.number="s.posJitter" /></div>
          <div class="row"><label>放置层</label><input type="text" v-model="s.layersText" placeholder="如 1,2" /></div>
          <div class="row"><label>顶灯W</label>
            <div class="range"><input class="short" type="number" v-model.number="s.topPower[0]" /><span>~</span>
            <input class="short" type="number" v-model.number="s.topPower[1]" /></div></div>
          <div class="row"><label>环境光</label>
            <div class="range"><input class="short" type="number" step="0.05" v-model.number="s.ambient[0]" /><span>~</span>
            <input class="short" type="number" step="0.05" v-model.number="s.ambient[1]" /></div></div>
        </div>

        <div class="card">
          <h2>输出</h2>
          <div class="row"><label>张数</label><input class="short" type="number" min="1" v-model.number="s.num" /></div>
          <div class="row"><label>保存位置</label><input type="text" v-model="s.saveDir" /></div>
          <div class="row"><label>训练图</label>
            <select v-model="s.variant">
              <option value="dist">加畸变(贴近真实相机)</option>
              <option value="ideal">理想针孔</option>
            </select></div>
          <button class="btn" :disabled="s.running" @click="render">{{ s.running ? '渲染中…' : '开始渲染' }}</button>
        </div>
      </div>

      <div>
        <div v-if="s.status" :class="['status', s.status.type]">{{ s.status.msg }}</div>
        <div class="card">
          <h2>预览 ({{ s.images.length }})</h2>
          <div class="gallery">
            <img v-for="(u,i) in s.images" :key="i" :src="u" />
          </div>
          <div v-if="!s.images.length" class="hint">还没有结果。左侧设置好后点"开始渲染"。</div>
        </div>
      </div>
    </div>
  </div>`,
};

createApp(App).mount("#app");
