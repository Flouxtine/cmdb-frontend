/* OpsScope M1 前端 */
const $ = (s, r = document) => r.querySelector(s);
const el = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c; if (h !== undefined) e.innerHTML = h; return e; };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtTime = (t) => (t ? String(t).replace("T", " ").slice(0, 19) : "-");
const RES_TYPES = { ecs: "云服务器", disk: "云盘", security_group: "安全组", oss: "对象存储" };
const PROV_NAMES = { demo: "演示环境", aliyun: "阿里云" };
const state = {
  view: "overview", providers: [], projects: [],
  resFilter: { credential_id: "", resource_type: "", keyword: "" }, resPage: 1, resTotal: 0, resSize: 30,
  svcFilter: { project: "", type: "" },
};

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) { let m = `HTTP ${res.status}`; try { m = (await res.json()).detail || m; } catch (e) {} throw new Error(m); }
  return res.json();
}
const get = (p) => api(p);
const post = (p, b) => api(p, { method: "POST", body: b ? JSON.stringify(b) : undefined });
const del = (p) => api(p, { method: "DELETE" });
function toast(msg, err = false) {
  const t = el("div", "", esc(msg));
  Object.assign(t.style, { position: "fixed", top: 18, right: 18, zIndex: 200, background: err ? "#f56c6c" : "#52c41a", color: "#fff", padding: "9px 16px", borderRadius: 6, fontSize: 13, boxShadow: "0 3px 12px rgba(0,0,0,.18)" });
  document.body.appendChild(t); setTimeout(() => t.remove(), 3000);
}

/* ---------------- Drawer ---------------- */
function openDrawer(title, bodyNode) {
  const mask = el("div", "drawer-mask");
  const drawer = el("div", "drawer");
  const head = el("div", "drawer-head", `<h2>${esc(title)}</h2><span style="cursor:pointer;color:#909399">✕</span>`);
  head.lastChild.onclick = close;
  const body = el("div", "drawer-body"); body.appendChild(bodyNode);
  drawer.append(head, body);
  document.body.appendChild(mask); document.body.appendChild(drawer);
  function close() { mask.remove(); drawer.remove(); }
  mask.onclick = close;
  return { body, close };
}
function sec(title, node) { const s = el("div", "drawer-sec"); s.appendChild(el("h4", "", esc(title))); s.appendChild(node); return s; }
function kvHtml(pairs) {
  const g = el("div", "kv");
  pairs.forEach(([k, v]) => { g.append(el("div", "k", esc(k)), el("div", "v", v !== undefined && v !== null && v !== "" ? v : "-")); });
  return g;
}

/* ---------------- 导航 ---------------- */
function switchView(name) {
  state.view = name;
  document.querySelectorAll(".nav-item").forEach((n) => n.classList.toggle("active", n.dataset.view === name));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
  const T = { overview: "概览", credentials: "云账号", resources: "云资源 CMDB", services: "业务服务", alerts: "告警分析" };
  $("#page-title").textContent = T[name];
  ({ overview: loadOverview, credentials: loadCredentials, resources: loadResources, services: loadServices, alerts: loadAlerts })[name]();
}
document.querySelectorAll(".nav-item").forEach((n) => n.addEventListener("click", () => switchView(n.dataset.view)));

/* ---------------- 概览 ---------------- */
async function loadOverview() {
  const v = $("#view-overview"); v.innerHTML = '<div class="empty">加载中...</div>';
  try {
    const d = await get("/api/overview");
    v.innerHTML = "";
    const stats = el("div", "stat-grid");
    stats.append(
      mkStat(d.credential_count, "云账号", "ok"), mkStat(d.resource_count, "云资源", "ac"),
      mkStat(d.cmdb_item_count, "业务服务", ""), mkStat(d.open_alert_count ?? 0, "未处理告警", (d.open_alert_count || 0) > 0 ? "hl" : ""));
    v.appendChild(stats);

    const card = el("div", "card");
    card.appendChild(el("h3", "", "资源类型分布"));
    const chips = el("div", "chips");
    (d.resource_by_type || []).forEach((x) => chips.appendChild(el("span", "chip", `${(RES_TYPES[x.resource_type] || x.resource_type)} <b>${x.n}</b>`)));
    if (!d.resource_by_type.length) chips.appendChild(el("span", "muted", "暂无资源 —— 先添加云账号并同步"));
    card.appendChild(chips);
    v.appendChild(card);

    const acc = el("div", "card");
    acc.appendChild(el("h3", "", "各账号资源分布"));
    const a2 = el("div", "chips");
    (d.resource_by_account || []).forEach((x) => a2.appendChild(el("span", "chip", `${esc(x.name || "(未命名)")} <b>${x.n}</b>`)));
    if (!d.resource_by_account.length) a2.appendChild(el("span", "muted", "暂无账号资源"));
    acc.appendChild(a2);
    v.appendChild(acc);

    const proj = el("div", "card");
    proj.appendChild(el("h3", "", "业务服务（按项目）"));
    const p2 = el("div", "chips");
    (d.cmdb_by_project || []).forEach((x) => p2.appendChild(el("span", "chip", `${esc(x.project)} <b>${x.n}</b>`)));
    proj.appendChild(p2);
    v.appendChild(proj);
  } catch (e) { v.innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`; }
}
const mkStat = (num, label, cls) => { const s = el("div", `stat ${cls || ""}`); s.append(el("div", "num", String(num)), el("div", "label", esc(label))); return s; };

/* ---------------- 云账号 ---------------- */
async function loadCredentials() {
  const v = $("#view-credentials"); v.innerHTML = '<div class="empty">加载中...</div>';
  try {
    if (!state.providers.length) state.providers = await get("/api/providers");
    const list = await get("/api/credentials");
    v.innerHTML = "";
    const toolbar = el("div", "toolbar");
    toolbar.appendChild(el("button", "btn primary", "＋ 添加云账号")).onclick = () => showCredForm();
    v.appendChild(toolbar);
    if (!list.length) {
      const empty = el("div", "card");
      empty.appendChild(el("div", "tip", "1️⃣ 添加账号（推荐先建<b>演示环境</b>体验）→ 2️⃣ 点击「同步资源」→ 3️⃣ 到「云资源 CMDB」查看归属"));
      empty.appendChild(el("div", "empty", "暂无云账号，点击上方「添加云账号」开始"));
      v.appendChild(empty);
      return;
    }
    const grid = el("div", "svc-grid");
    list.forEach((c) => {
      const card = el("div", "card");
      const head = el("div", "", `<div style="display:flex;justify-content:space-between;align-items:center">
        <b style="font-size:15px">${esc(c.name)}</b>
        <span class="tacc ${esc(c.provider)}">${esc(PROV_NAMES[c.provider] || c.provider)}</span></div>`);
      const meta = el("div", "kv", "");
      meta.append(el("div", "k", "状态"), el("div", "v", stateDot(c.status) + esc(c.status)));
      meta.append(el("div", "k", "AK"), el("div", "v", esc(c.access_key || "-")));
      meta.append(el("div", "k", "Region"), el("div", "v", esc((c.regions || []).join(", ") || "-")));
      meta.append(el("div", "k", "资源数"), el("div", "v", String(c.resource_count ?? 0)));
      meta.append(el("div", "k", "最近同步"), el("div", "v", esc(fmtTime(c.last_sync_at) || "未同步")));
      if (c.last_error) { meta.append(el("div", "k", "错误"), el("div", "v muted", esc(c.last_error))); }
      card.append(head, meta);
      const act = el("div", "", `<div style="margin-top:10px;display:flex;gap:6px">
        <button class="btn sm">测试</button><button class="btn sm primary">同步资源</button><button class="btn sm danger">删除</button></div>`);
      const [t, s, d] = act.querySelectorAll("button");
      t.onclick = () => credOp(c, "test", t, "测试");
      s.onclick = () => credOp(c, "sync", s, "同步资源");
      d.onclick = () => { if (window.confirm(`删除账号「${c.name}」及同步的资源？`)) del(`/api/credentials/${c.id}`).then(() => { toast("已删除"); loadCredentials(); loadOverview(); }); };
      card.appendChild(act);
      grid.appendChild(card);
    });
    v.appendChild(grid);
  } catch (e) { v.innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`; }
}
const stateDot = (s) => ({ ok: '<span style="color:#52c41a">●</span> ', fail: '<span style="color:#f56c6c">●</span> ', untested: '<span style="color:#c0c4cc">●</span> ' }[s] || "");
function credOp(c, op, btn, label) {
  btn.disabled = true; btn.textContent = "执行中...";
  post(`/api/credentials/${c.id}/${op}`).then((r) => {
    if (op === "test") toast(r.message || (r.ok ? "连接成功" : "连接失败"), !r.ok);
    else { toast(`同步完成：拉取 ${r.synced ?? 0} 个，共 ${r.total ?? 0} 个${r.errors && r.errors.length ? `（${r.errors.length} 个错误）` : ""}`); loadOverview(); }
    loadCredentials();
  }).catch((e) => toast("失败：" + e.message, true))
    .finally(() => { btn.disabled = false; btn.textContent = label; });
}
function showCredForm() {
  const body = el("div");
  const f = (label, node) => { const row = el("div", "form-row"); row.append(el("label", "", esc(label)), node); return row; };
  const name = el("input"); name.placeholder = "如：生产环境-主账号";
  const prov = el("select");
  state.providers.forEach((p) => prov.appendChild(new Option(PROV_NAMES[p.provider] || p.display_name, p.provider)));
  const ak = el("input"); ak.placeholder = "AccessKey ID（演示环境无需填写）";
  const sk = el("input"); sk.type = "password"; sk.placeholder = "AccessKey Secret";
  const reg = el("input"); reg.placeholder = "cn-hangzhou,cn-shanghai（留空默认杭州）";
  const remark = el("input"); remark.placeholder = "备注";
  const keyRow = el("div");
  const sync = () => {
    keyRow.innerHTML = "";
    if (prov.value === "aliyun") keyRow.append(f("AccessKey", ak), f("SecretKey", sk));
    else keyRow.appendChild(el("div", "tip", "演示环境无需密钥：保存后点「同步资源」即生成 12 个示例资源。"));
  };
  prov.onchange = sync; sync();
  body.append(f("账号名称", name), f("厂商", prov), keyRow, f("Region", reg), f("备注", remark));
  const foot = el("div");
  const save = el("button", "btn primary", "保存");
  const cancel = el("button", "btn", "取消");
  foot.append(cancel, save);
  const mask = openModal("添加云账号", body, foot);
  cancel.onclick = mask.close;
  save.onclick = () => post("/api/credentials", {
    name: name.value.trim(), provider: prov.value, access_key: ak.value.trim(), secret_key: sk.value.trim(),
    regions: reg.value.split(",").map((s2) => s2.trim()).filter(Boolean), remark: remark.value.trim(),
  }).then(() => { toast("已添加"); mask.close(); loadCredentials(); })
    .catch((e) => toast(e.message, true));
}

/* ---------------- 云资源 CMDB ---------------- */
async function loadResources() {
  const v = $("#view-resources"); v.innerHTML = '<div class="empty">加载中...</div>';
  try {
    const creds = await get("/api/credentials");
    const p = new URLSearchParams({ ...state.resFilter, page: state.resPage, page_size: state.resSize });
    const d = await get(`/api/resources?${p}`);
    state.resTotal = d.total;
    v.innerHTML = "";
    const toolbar = el("div", "toolbar");
    const selAcc = el("select"); selAcc.appendChild(new Option("全部账号", ""));
    creds.forEach((c) => selAcc.appendChild(new Option(c.name, c.id)));
    selAcc.value = state.resFilter.credential_id;
    selAcc.onchange = () => { state.resFilter.credential_id = selAcc.value; state.resPage = 1; loadResources(); };
    const selType = el("select"); selType.appendChild(new Option("全部类型", ""));
    Object.entries(RES_TYPES).forEach(([k, l]) => selType.appendChild(new Option(l, k)));
    selType.value = state.resFilter.resource_type;
    selType.onchange = () => { state.resFilter.resource_type = selType.value; state.resPage = 1; loadResources(); };
    const kw = el("input"); kw.placeholder = "搜索名称 / 资源ID"; kw.style.minWidth = "180px"; kw.value = state.resFilter.keyword;
    kw.onkeydown = (e) => { if (e.key === "Enter") { state.resFilter.keyword = kw.value; state.resPage = 1; loadResources(); } };
    toolbar.append(selAcc, selType, kw, Object.assign(el("button", "btn primary", "查询"), { onclick: () => { state.resFilter.keyword = kw.value; state.resPage = 1; loadResources(); } }));
    v.appendChild(toolbar);

    const t = el("table");
    t.appendChild(el("thead", "", "<tr><th>类型</th><th>名称</th><th>资源ID</th><th>Region</th><th>所属账号</th><th>同步时间</th><th></th></tr>"));
    const tb = el("tbody");
    if (!d.items.length) tb.innerHTML = `<tr><td colspan="7" class="empty">${creds.length ? "该条件下暂无资源，请先同步" : "暂无资源 —— 先到「云账号」添加并同步"}</td></tr>`;
    d.items.forEach((r) => {
      const tr = el("tr");
      tr.innerHTML = `<td><span class="ttype">${RES_TYPES[r.resource_type] || r.resource_type}</span></td>
        <td><b>${esc(r.name)}</b></td><td class="muted">${esc(r.resource_id)}</td><td>${esc(r.region || "-")}</td>
        <td><span class="tacc ${esc(r.provider)}">${esc(r.credential_name || "-")}</span></td>
        <td class="muted">${fmtTime(r.synced_at)}</td>`;
      const view = el("button", "btn sm", "查看归属");
      view.onclick = () => showResourceDrawer(r.id);
      const td = el("td"); td.appendChild(view); tr.appendChild(td);
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    v.appendChild(t);
    v.appendChild(pager(state.resTotal, state.resPage, (pg) => { state.resPage = pg; loadResources(); }));
  } catch (e) { v.innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`; }
}
async function showResourceDrawer(rid) {
  const r = await get(`/api/resources/${rid}`);
  const dlg = openDrawer(`${RES_TYPES[r.resource_type] || r.resource_type} · ${esc(r.name)}`, el("div"));
  const body = dlg.body;
  body.appendChild(sec("所属账号", (() => {
    const card = el("div", "account-card");
    card.innerHTML = `<div style="display:flex;justify-content:space-between"><b>${esc(r.credential_name)}</b><span class="tacc ${esc(r.provider)}">${esc(PROV_NAMES[r.provider] || r.provider)}</span></div>`;
    card.appendChild(kvHtml([["账号ID", esc(r.credential_id || "-")], ["Region", esc(r.region || "-")], ["资源ID", esc(r.resource_id)], ["同步时间", esc(fmtTime(r.synced_at))]]));
    return card;
  })()));
  body.appendChild(sec("资源属性", el("div", "detail-json", esc(JSON.stringify(r.attributes || {}, null, 2)))));
  if (Object.keys(r.tags || {}).length) body.appendChild(sec("标签", el("div", "chips", Object.entries(r.tags).map(([k, val]) => `<span class="chip">${esc(k)}=<b>${esc(val)}</b></span>`).join(""))));
  const linkSec = el("div");
  const items = r.linked_items || [];
  if (items.length) {
    const lt = el("table");
    lt.appendChild(el("thead", "", "<tr><th>业务服务</th><th>项目</th><th>负责人</th></tr>"));
    const ltb = el("tbody");
    items.forEach((it) => ltb.appendChild(el("tr", "", `<td><b>${esc(it.name)}</b></td><td>${esc(it.project)}</td><td>${esc(it.owner || "-")}</td>`)));
    lt.appendChild(ltb);
    linkSec.appendChild(lt);
  } else linkSec.appendChild(el("div", "muted", "未关联业务服务"));
  body.appendChild(sec("关联业务服务", linkSec));
}

/* ---------------- 业务服务 ---------------- */
async function loadServices() {
  const v = $("#view-services"); v.innerHTML = '<div class="empty">加载中...</div>';
  try {
    const items = await get("/api/cmdb/items");
    state.projects = await get("/api/cmdb/projects");
    v.innerHTML = "";
    const toolbar = el("div", "toolbar");
    toolbar.appendChild(el("button", "btn primary", "＋ 新增服务")).onclick = () => showSvcForm();
    const selProj = el("select"); selProj.appendChild(new Option("全部项目", ""));
    state.projects.forEach((p) => selProj.appendChild(new Option(p, p)));
    selProj.value = state.svcFilter.project;
    selProj.onchange = () => { state.svcFilter.project = selProj.value; loadServices(); };
    const selType = el("select"); selType.appendChild(new Option("全部类型", ""));
    ["service", "app", "middleware", "device"].forEach((tp) => selType.appendChild(new Option(tp, tp)));
    selType.value = state.svcFilter.type;
    selType.onchange = () => { state.svcFilter.type = selType.value; loadServices(); };
    toolbar.append(selProj, selType);
    v.appendChild(toolbar);

    const t = el("table");
    t.appendChild(el("thead", "", "<tr><th>名称</th><th>类型</th><th>项目</th><th>负责人</th><th>环境</th><th>关联资源</th><th></th></tr>"));
    const tb = el("tbody");
    const filtered = items.filter((i) => (!state.svcFilter.project || i.project === state.svcFilter.project) && (!state.svcFilter.type || i.type === state.svcFilter.type));
    if (!filtered.length) tb.innerHTML = `<tr><td colspan="7" class="empty">暂无业务服务 —— 新增一个服务，再到资源抽屉里绑定，即可把"服务→资源→账号"串起来</td></tr>`;
    filtered.forEach((i) => {
      const tr = el("tr");
      tr.innerHTML = `<td><b>${esc(i.name)}</b></td><td><span class="ttype">${esc(i.type)}</span></td>
        <td>${esc(i.project)}</td><td>${esc(i.owner || "-")}</td><td>${esc(i.env)}</td><td>${i.resource_count ?? 0}</td>`;
      const td = el("td");
      const vd = el("button", "btn sm primary", "查看");
      vd.onclick = () => showSvcDrawer(i.id);
      const dd = el("button", "btn sm danger", "删除");
      dd.onclick = () => { if (window.confirm(`删除业务服务「${i.name}」？`)) del(`/api/cmdb/items/${i.id}`).then(() => { toast("已删除"); loadServices(); loadOverview(); }); };
      td.append(vd, dd);
      tr.appendChild(td);
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    v.appendChild(t);
  } catch (e) { v.innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`; }
}
function showSvcForm() {
  const body = el("div");
  const f = (label, node) => { const row = el("div", "form-row"); row.append(el("label", "", esc(label)), node); return row; };
  const name = el("input");
  const proj = el("input"); proj.value = state.svcFilter.project || "默认项目";
  const type = el("select"); ["service", "app", "middleware", "device"].forEach((tp) => type.appendChild(new Option(tp, tp)));
  const owner = el("input");
  const env = el("select"); ["prod", "staging", "dev"].forEach((e2) => env.appendChild(new Option(e2, e2)));
  body.append(f("名称", name), f("项目", proj), f("类型", type), f("负责人", owner), f("环境", env));
  const foot = el("div");
  const save = el("button", "btn primary", "创建");
  const cancel = el("button", "btn", "取消");
  foot.append(cancel, save);
  const mask = openModal("新增业务服务", body, foot);
  cancel.onclick = mask.close;
  save.onclick = () => post("/api/cmdb/items", { name: name.value.trim(), project: proj.value.trim() || "默认项目", type: type.value, owner: owner.value.trim(), env: env.value })
    .then(() => { toast("已创建"); mask.close(); loadServices(); loadOverview(); }).catch((e) => toast(e.message, true));
}
async function showSvcDrawer(iid) {
  const i = await get(`/api/cmdb/items/${iid}`);
  const dlg = openDrawer(`${esc(i.name)}（${esc(i.type)}）`, el("div"));
  const body = dlg.body;
  body.appendChild(sec("基本信息", kvHtml([["项目", esc(i.project)], ["负责人", esc(i.owner || "-")], ["环境", esc(i.env)], ["创建时间", esc(fmtTime(i.created_at))]])));
  const resSec = el("div");
  if (i.resources.length) {
    const t = el("table");
    t.appendChild(el("thead", "", "<tr><th>类型</th><th>名称</th><th>所属账号</th><th>Region</th><th></th></tr>"));
    const tb = el("tbody");
    i.resources.forEach((r) => {
      const tr = el("tr");
      tr.innerHTML = `<td><span class="ttype">${RES_TYPES[r.resource_type] || r.resource_type}</span></td><td>${esc(r.name)}</td>
        <td><span class="tacc ${esc(r.provider)}">${esc(r.credential_name || "-")}</span></td><td>${esc(r.region || "-")}</td>`;
      const td = el("td");
      const ub = el("button", "btn sm danger", "解除");
      ub.onclick = () => del(`/api/cmdb/items/${iid}/link/${r.id}`).then(() => { toast("已解除"); showSvcDrawer(iid); });
      td.appendChild(ub);
      tr.appendChild(td);
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    resSec.appendChild(t);
  } else resSec.appendChild(el("div", "muted", "尚未关联资源 —— 在「云资源 CMDB」的资源归属抽屉里执行绑定"));
  body.appendChild(sec("关联云资源", resSec));
}

/* ---------------- 告警分析（M2）---------------- */
const alertFilter = { level: "", status: "open", source: "" };
const LEVEL_LABEL = { high: "高危", medium: "中危", low: "低危" };
const SRC_LABEL = { alertmanager: "Alertmanager", custom: "通用Webhook", internal: "内部规则" };

async function loadAlerts() {
  const v = $("#view-alerts"); v.innerHTML = '<div class="empty">加载中...</div>';
  try {
    const params = new URLSearchParams(Object.entries(alertFilter).filter(([, x]) => x));
    const alerts = await get(`/api/alerts?${params}`);
    v.innerHTML = "";
    const demoBar = el("div", "tip", "🎬 演示：点「模拟外部告警」= 通用 Webhook 推一条告警（resource_ref 匹配到 CMDB 资源）；也可复制 curl 直接调 <b>POST /api/webhooks/generic</b> 或 Alertmanager 标准格式 <b>POST /api/webhooks/alertmanager</b>（配了 WEBHOOK_TOKEN 需带 X-Ops-Scope-Token）。");
    const toolbar = el("div", "toolbar");
    const simBtn = el("button", "btn danger", "🎬 模拟外部告警");
    simBtn.onclick = () => post("/api/demo/alert").then((r) => { toast(r.action === "created" ? "已产生告警" : r.action === "deduped" ? "同 key 告警已去重" : "已入库"); loadAlerts(); loadOverview(); }).catch((e) => toast(e.message, true));
    const selLevel = el("select");
    [["", "全部级别"], ["high", "高危"], ["medium", "中危"], ["low", "低危"]].forEach(([k, l]) => selLevel.appendChild(new Option(l, k)));
    selLevel.value = alertFilter.level;
    selLevel.onchange = () => { alertFilter.level = selLevel.value; loadAlerts(); };
    const selStatus = el("select");
    [["", "全部状态"], ["open", "未解决"], ["resolved", "已解决"], ["expired", "已过期"]].forEach(([k, l]) => selStatus.appendChild(new Option(l, k)));
    selStatus.value = alertFilter.status;
    selStatus.onchange = () => { alertFilter.status = selStatus.value; loadAlerts(); };
    const selSrc = el("select");
    [["", "全部来源"], ["alertmanager", "Alertmanager"], ["custom", "通用Webhook"], ["internal", "内部规则"]].forEach(([k, l]) => selSrc.appendChild(new Option(l, k)));
    selSrc.value = alertFilter.source;
    selSrc.onchange = () => { alertFilter.source = selSrc.value; loadAlerts(); };
    toolbar.append(simBtn, selLevel, selStatus, selSrc);
    v.append(demoBar, toolbar);

    const t = el("table");
    t.appendChild(el("thead", "", "<tr><th>级别</th><th>告警</th><th>来源</th><th>资源 / 业务</th><th>关联发布</th><th>状态</th><th>最近时间</th><th>操作</th></tr>"));
    const tb = el("tbody");
    if (!alerts.length) tb.innerHTML = `<tr><td colspan="8" class="empty">暂无告警 —— 点「模拟外部告警」体验接收流程</td></tr>`;
    alerts.forEach((a) => {
      const tr = el("tr");
      const rel = a.related_deployment_id ? `<span class="rel-tag">⚠️ ${esc(a.deploy_version || "本次发布")}</span>` : '<span class="muted">-</span>';
      const stCls = { open: "st-open", resolved: "st-resolved", expired: "st-expired" }[a.status] || "";
      const stLabel = { open: "未解决", resolved: "已解决", expired: "已过期" }[a.status] || a.status;
      tr.innerHTML = `<td><span class="lvl ${a.level}">${LEVEL_LABEL[a.level] || a.level}</span></td>
        <td><b>${esc(a.title)}</b><div class="muted">${esc(a.detail || "")}</div></td>
        <td><span class="src">${esc(SRC_LABEL[a.source] || a.source)}</span></td>
        <td>${esc(a.item_name || a.resource_ref || "-")}${a.credential_name ? `<div class="muted">账号:${esc(a.credential_name)}</div>` : ""}</td>
        <td>${rel}</td><td class="${stCls}">${stLabel}</td><td class="muted">${fmtTime(a.last_at || a.first_at)}</td>`;
      const act = el("td", "");
      if (a.status === "open") {
        const rb = el("button", "btn sm", "解决");
        rb.onclick = () => post(`/api/alerts/${a.id}/resolve`).then(() => { toast("已解决"); loadAlerts(); loadOverview(); });
        act.appendChild(rb);
      }
      tr.appendChild(act);
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    v.appendChild(t);
  } catch (e) { v.innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`; }
}

/* ---------------- 通用 ---------------- */
function pager(total, page, onChange) {
  const size = state.view === "resources" ? state.resSize : 30;
  const max = Math.max(1, Math.ceil(total / size));
  const w = el("div", "pager");
  w.appendChild(el("span", "muted", `共 ${total} 条`));
  const prev = el("button", "btn sm", "上一页"); prev.disabled = page <= 1; prev.onclick = () => onChange(page - 1);
  const next = el("button", "btn sm", "下一页"); next.disabled = page >= max; next.onclick = () => onChange(page + 1);
  w.append(prev, el("span", "", `${page} / ${max}`), next);
  return w;
}
function openModal(title, bodyNode, foot) {
  const mask = el("div", "modal-mask");
  const modal = el("div", "modal");
  const head = el("div", "modal-head", `<span>${esc(title)}</span><span style="cursor:pointer;color:#909399">✕</span>`);
  head.lastChild.onclick = () => mask.remove();
  const body = el("div", "modal-body"); body.appendChild(bodyNode);
  modal.append(head, body);
  if (foot) { const f = el("div", "modal-foot"); f.appendChild(foot); modal.appendChild(f); }
  mask.appendChild(modal);
  mask.onclick = (e) => { if (e.target === mask) mask.remove(); };
  $("#modal-root").appendChild(mask);
  return { close: () => mask.remove() };
}

switchView("overview");
