# -*- coding: utf-8 -*-
"""浏览器控制台（单页）：入队事件 / 查看待批 / 批准驳回 / 复盘。"""
from __future__ import annotations

UI_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>智能推演指挥台</title>
<style>
  :root { --navy:#101c2e; --teal:#0f7a7a; --line:#dbe2ec; --mut:#64748b; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: "Microsoft YaHei", system-ui, sans-serif; background:#f6f8fb; color:#1e293b; }
  header { background: var(--navy); color:#fff; padding:18px 28px; display:flex; justify-content:space-between; align-items:center; }
  header h1 { font-size:20px; margin:0; font-weight:700; }
  header .meta { font-size:13px; color:#cbd5e1; }
  main { max-width:1100px; margin:24px auto; padding:0 20px; display:grid; gap:20px; }
  section { background:#fff; border:1px solid var(--line); border-radius:12px; padding:18px 20px; }
  section h2 { margin:0 0 12px; font-size:15px; color:var(--navy); }
  .row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
  input, select, textarea { font: inherit; padding:8px 10px; border:1px solid var(--line); border-radius:8px; }
  textarea { width:100%; min-height:64px; font-family: ui-monospace, Consolas, monospace; font-size:12.5px; }
  button { font: inherit; padding:8px 14px; border:0; border-radius:8px; cursor:pointer; background:var(--teal); color:#fff; }
  button.ghost { background:#eef2f7; color:#334155; }
  button.reject { background:#dc2626; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); }
  th { color:var(--mut); font-weight:600; }
  .pill { display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px; }
  .queued { background:#fff7ed; color:#c2410c; }
  .processed { background:#ecfdf5; color:#047857; }
  .pending { background:#fef9c3; color:#854d0e; }
  pre { background:#0f172a; color:#e2e8f0; padding:12px; border-radius:8px; overflow:auto; max-height:320px; font-size:12px; }
  .muted { color:var(--mut); font-size:12.5px; }
</style>
</head>
<body>
<header>
  <h1>智能推演指挥台 · 控制台</h1>
  <div class="meta" id="meta">加载中…</div>
</header>
<main>
  <section>
    <h2>① 注入事件</h2>
    <div class="row">
      <select id="kind">
        <option value="intel_report">intel_report（情报）</option>
        <option value="alert">alert（告警）</option>
        <option value="approval_result">approval_result（批准续跑）</option>
      </select>
      <input id="source" value="radar" style="width:140px" placeholder="source"/>
      <input id="round" type="number" value="1" style="width:90px" placeholder="round"/>
    </div>
    <div style="margin-top:10px">
      <textarea id="payload">{"kind":"strike","order_id":"o2","unit_id":"u1","target_id":"t1","threat":0.9}</textarea>
    </div>
    <div class="row" style="margin-top:10px">
      <button onclick="enqueue()">入队事件</button>
      <span class="muted">高危(threat≥0.6) → 生成待批命令；低危 → 归档</span>
    </div>
  </section>

  <section>
    <h2>② 待批命令（HITL）</h2>
    <div id="approvals" class="muted">加载中…</div>
  </section>

  <section>
    <h2>③ 事件回执</h2>
    <table>
      <thead><tr><th>seq</th><th>ev_id</th><th>kind</th><th>source</th><th>status</th></tr></thead>
      <tbody id="events"></tbody>
    </table>
  </section>

  <section>
    <h2>④ 复盘</h2>
    <div class="row">
      <button class="ghost" onclick="loadReplay()">刷新复盘 timeline</button>
    </div>
    <pre id="replay">（点击按钮加载）</pre>
  </section>
</main>
<script>
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
function esc(s){ return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

async function refresh() {
  try {
    const h = await api('/health');
    document.getElementById('meta').textContent =
      `pump=${h.pump} · queued=${h.queued} · orders=${h.orders}`;
  } catch (e) { document.getElementById('meta').textContent = '健康检查失败: ' + e.message; }

  try {
    const ap = await api('/approvals');
    const list = ap.pending || [];
    const el = document.getElementById('approvals');
    if (!list.length) { el.innerHTML = '<span class="muted">暂无待批命令</span>'; }
    else {
      el.innerHTML = list.map(o => `
        <div class="row" style="justify-content:space-between;border-bottom:1px solid var(--line);padding:8px 0">
          <div><b>${esc(o.order_id)}</b> · ${esc(o.kind)} · 目标 ${esc(o.target_id || '-')}
            <span class="pill pending">${esc(o.approval)}</span></div>
          <div class="row">
            <button onclick="decide('${esc(o.order_id)}', true)">批准</button>
            <button class="reject" onclick="decide('${esc(o.order_id)}', false)">驳回</button>
          </div>
        </div>`).join('');
    }
  } catch (e) { document.getElementById('approvals').textContent = '加载失败: ' + e.message; }

  try {
    const evs = await api('/events');
    document.getElementById('events').innerHTML = (evs.events || []).map(e => `
      <tr><td>${e.seq}</td><td>${esc(e.ev_id)}</td><td>${esc(e.kind)}</td>
      <td>${esc(e.source)}</td><td><span class="pill ${e.status}">${e.status}</span></td></tr>`).join('');
  } catch (e) { /* ignore */ }
}

async function enqueue() {
  const payloadText = document.getElementById('payload').value;
  let payload = {};
  try { payload = JSON.parse(payloadText); } catch (err) { alert('payload 不是合法 JSON: ' + err.message); return; }
  await api('/events', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      kind: document.getElementById('kind').value,
      source: document.getElementById('source').value,
      round: parseInt(document.getElementById('round').value || '1', 10),
      payload
    })
  });
  setTimeout(refresh, 1500);   // 等后台 pump 消费
}

async function decide(orderId, approve) {
  await api('/approvals/' + encodeURIComponent(orderId), {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({approve})
  });
  setTimeout(refresh, 800);
}

async function loadReplay() {
  const data = await api('/games/g1/replay');
  document.getElementById('replay').textContent = JSON.stringify(data, null, 2);
}

refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
"""


def ui_html() -> str:
    return UI_PAGE


__all__ = ["ui_html", "UI_PAGE"]
