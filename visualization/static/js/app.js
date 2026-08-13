/* app.js — 前端应用逻辑。
 *
 * 连接仪表盘：创建/控制社会、通过 WebSocket 实时刷新状态、渲染指标、
 * Agent 详情、事件时间线与因果链。界面文案为中文。
 */
(function () {
  'use strict';

  // 意识形态 / 事件类型的显示名（与后端 engine/agent/ideology.py 保持一致）。
  const IDEO_LABELS = {
    liberal: '自由派', conservative: '保守派', socialist: '社会主义',
    libertarian: '自由意志', authoritarian: '威权主义',
    communitarian: '社群主义', anarchist: '无政府主义', centrist: '中间派',
  };
  const EVENT_LABELS = {
    economic_crisis: '经济危机', food_shortage: '粮食短缺', market_panic: '市场恐慌',
    unemployment: '失业上升', protest: '抗议', government_response: '政府应对',
    political_movement: '政治运动', leadership_change: '领导更替', alliance: '结盟',
    conflict: '冲突', resource_boom: '资源繁荣', scandal: '丑闻',
    natural_disaster: '自然灾害', technology_breakthrough: '技术突破',
    migration: '迁移', election: '选举', war: '战争',
  };
  const STATUS_LABELS = { created: '已创建', running: '运行中', paused: '已暂停', finished: '已结束' };

  const state = {
    societyId: null,
    ws: null,
    agents: [],
    colorMap: {},
    metricsHistory: [],
    events: [],
    currentTab: 'timeline',
    ideologies: [],
    prevMetrics: null,
  };

  const spectrum = new Spectrum3D(document.getElementById('spectrum-canvas'));
  spectrum.onSelect = (id) => selectAgent(id);

  // ---- DOM 工具 ---------------------------------------------------------
  const $ = (id) => document.getElementById(id);
  const api = async (path, opts) => {
    const r = await fetch(path, opts || {});
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  };

  // ---- 意识形态分布配置输入 ---------------------------------------------
  const IDEOLOGIES = ['liberal', 'conservative', 'socialist', 'libertarian', 'authoritarian'];
  const IDEOLOGY_DEFAULT_PCT = { liberal: 30, conservative: 30, socialist: 20, libertarian: 10, authoritarian: 10 };

  function buildIdeologyDist() {
    const grid = $('ideology-dist');
    grid.innerHTML = '';
    IDEOLOGIES.forEach((id) => {
      const label = document.createElement('span');
      label.textContent = IDEO_LABELS[id] || id;
      const input = document.createElement('input');
      input.type = 'number';
      input.min = '0';
      input.max = '100';
      input.value = IDEOLOGY_DEFAULT_PCT[id] || 0;
      input.dataset.ideology = id;
      input.className = 'ideology-input';
      grid.appendChild(label);
      grid.appendChild(input);
    });
  }
  buildIdeologyDist();

  function collectConfig() {
    const dist = {};
    document.querySelectorAll('.ideology-input').forEach((inp) => {
      dist[inp.dataset.ideology] = Number(inp.value || 0) / 100;
    });
    const total = Object.values(dist).reduce((a, b) => a + b, 0);
    if (total > 0) {
      Object.keys(dist).forEach((k) => (dist[k] = dist[k] / total));
    }
    const highAgree = Number($('cfg-pers-high').value || 0) / 100;
    const highRisk = Number($('cfg-pers-risk').value || 0) / 100;
    return {
      seed: Number($('cfg-seed').value || 42),
      population: {
        count: Number($('cfg-agents').value || 1000),
        age_range: [18, 75],
        ideology_distribution: dist,
        personality_distribution: {
          agreeableness: { high: highAgree, neutral: 1 - highAgree, low: 0 },
          risk_tolerance: { high: highRisk, neutral: 1 - highRisk, low: 0 },
        },
      },
      economy: { tax_rate: Number($('cfg-tax').value || 0.08) },
      events: { frequency: Number($('cfg-event-freq').value || 0.02) },
      model: {
        provider: $('cfg-provider').value,
        base_url: $('cfg-baseurl').value,
      },
    };
  }

  // ---- 创建 / 控制 ------------------------------------------------------
  function fmtTime(clock) {
    return `第 ${clock.year} 年 | 第 ${clock.day} 日 | Tick ${clock.tick}`;
  }

  async function createSociety() {
    const cfg = collectConfig();
    try {
      const s = await api('/api/society/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config: cfg }),
      });
      state.societyId = s.society_id;
      connectWS(s.society_id);
      await loadAgents();
      await loadMetrics();
      await loadEvents();
      setStatus(s.status);
      $('sim-time').textContent = fmtTime(s.clock);
    } catch (e) {
      alert('创建失败：' + e.message);
    }
  }

  function setStatus(status) {
    const el = $('sim-status');
    el.textContent = STATUS_LABELS[status] || status;
    el.className = 'status ' + status;
  }

  async function loadAgents() {
    const r = await api(`/api/society/${state.societyId}/agents?brief=true&limit=20000`);
    state.agents = r.agents;
    spectrum.setAgents(r.agents);
  }

  async function loadMetrics() {
    const r = await api(`/api/society/${state.societyId}/metrics`);
    renderMetrics(r.current);
  }

  async function loadEvents() {
    const r = await api(`/api/society/${state.societyId}/events?limit=300`);
    state.events = r.events;
    renderTimeline();
  }

  async function selectAgent(id) {
    const r = await api(`/api/agent/${id}?society_id=${state.societyId}`);
    renderInspector(r);
    const hist = await api(`/api/agent/${id}/history?society_id=${state.societyId}&limit=500`);
    renderHistory(hist.history);
  }

  // ---- WebSocket --------------------------------------------------------
  function connectWS(societyId) {
    if (state.ws) state.ws.close();
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/ws/simulation/${societyId}`);
    state.ws = ws;
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      handleWS(msg);
    };
    ws.onclose = () => { setStatus('paused'); };
  }

  function handleWS(msg) {
    if (msg.type === 'tick' && msg.clock) {
      $('sim-time').textContent = fmtTime(msg.clock);
      if (msg.metrics) renderMetrics(msg.metrics);
      if (msg.collapse_flags) renderCollapse(msg.collapse_flags);
      if (msg.new_events && msg.new_events.length) {
        state.events = state.events.concat(msg.new_events).slice(-500);
        renderTimeline();
      }
      // 周期性刷新 Agent 位置（节流）。
      if (msg.clock.tick % 50 === 0) refreshAgentPositions();
    }
  }

  async function refreshAgentPositions() {
    try {
      const r = await api(`/api/society/${state.societyId}/agents?brief=true&limit=20000`);
      state.agents = r.agents;
      spectrum.setAgents(r.agents);
    } catch (e) { /* ignore */ }
  }

  // ---- 渲染 -------------------------------------------------------------
  function renderMetrics(m) {
    if (!m) return;
    const prev = state.prevMetrics || {};
    const trend = (key, v) => {
      const p = prev[key];
      if (p === undefined) return '';
      const d = v - p;
      if (Math.abs(d) < 0.0005) return '<span class="tr">→</span>';
      return d > 0 ? '<span class="tr up">↑</span>' : '<span class="tr down">↓</span>';
    };
    const items = [
      ['人口', m.population, null],
      ['社会温度', m.social_temperature, 'social_temperature'],
      ['X 极化', m.x_polarization, 'x_polarization'],
      ['Y 极化', m.y_polarization, 'y_polarization'],
      ['Z 极化', m.z_polarization, 'z_polarization'],
      ['政治多样性', m.political_diversity, 'political_diversity'],
      ['系统稳定度', m.system_stability, 'system_stability'],
      ['边界集中', m.boundary_concentration, 'boundary_concentration'],
      ['事件持续', m.event_persistence, 'event_persistence'],
      ['平均财富', m.average_wealth, null],
      ['不平等（基尼）', m.resource_inequality, null],
      ['社会信任', m.social_trust, null],
    ];
    $('metrics-list').innerHTML = items
      .map(([k, v, tk]) => {
        const val = typeof v === 'number' ? (v >= 100 ? v : Number(v).toFixed(3)) : v;
        return `<div class="metric"><span class="k">${k}</span><span class="v">${val} ${tk ? trend(tk, v) : ''}</span></div>`;
      })
      .join('');
    state.prevMetrics = m;
    renderDominance(m);
  }

  function renderCollapse(flags) {
    const el = $('collapse-banner');
    if (!flags) { el.style.display = 'none'; return; }
    const msgs = [];
    if (flags.collapse_warning) msgs.push('⚠ 社会系统崩溃风险');
    if (flags.boundary_critical) msgs.push('⚠ 政治边界集中（临界）');
    else if (flags.boundary_warning) msgs.push('⚠ 政治边界集中');
    if (msgs.length) { el.textContent = msgs.join(' · '); el.style.display = 'inline'; }
    else el.style.display = 'none';
  }

  const DOMINANCE_LABELS = {
    'X_DOMINANT': 'X 轴主导', 'Y_DOMINANT': 'Y 轴主导', 'Z_DOMINANT': 'Z 轴主导',
    '3D_DYNAMICS': '三维动力学', 'STATIC': '静态',
  };

  function renderDominance(m) {
    const el = $('axis-dominance');
    if (!m || !m.axis_dominance) { el.textContent = ''; return; }
    el.textContent = '当前动力学：' + (DOMINANCE_LABELS[m.axis_dominance] || m.axis_dominance);
  }

  function renderInspector(a) {
    if (!a) return;
    const el = $('agent-inspector');
    const p = a.personality || {};
    const id = a.ideology || {};
    const r = a.resources || {};
    el.innerHTML = `
      <div id="inspector-title">Agent ${a.id}</div>
      <div class="kv"><span class="k">年龄</span><span>${a.age}</span></div>
      <div class="kv"><span class="k">初始流派</span><span>${IDEO_LABELS[id.origin_label] || id.origin_label}</span></div>
      <div class="kv"><span class="k">智能等级</span><span>${a.ai_level}</span></div>
      <div class="section-title">政治立场</div>
      <div class="kv"><span class="k">X（经济）</span><span>${id.x?.toFixed(3)}</span></div>
      <div class="kv"><span class="k">Y（权威）</span><span>${id.y?.toFixed(3)}</span></div>
      <div class="kv"><span class="k">Z（集体）</span><span>${id.z?.toFixed(3)}</span></div>
      <div class="section-title">资源</div>
      <div class="kv"><span class="k">金钱</span><span>${r.money?.toFixed(1)}</span></div>
      <div class="kv"><span class="k">食物</span><span>${r.food?.toFixed(1)}</span></div>
      <div class="kv"><span class="k">影响力</span><span>${r.influence?.toFixed(1)}</span></div>
      <div class="section-title">人格</div>
      <div class="kv"><span class="k">开放性</span><span>${p.openness?.toFixed(2)}</span></div>
      <div class="kv"><span class="k">风险偏好</span><span>${p.risk_tolerance?.toFixed(2)}</span></div>
      <div class="kv"><span class="k">信任</span><span>${p.trust?.toFixed(2)}</span></div>
      <div class="kv"><span class="k">同理心</span><span>${p.empathy?.toFixed(2)}</span></div>
      <div class="section-title">状态</div>
      <div class="kv"><span class="k">愤怒</span><span>${(a.status?.anger || 0).toFixed(3)}</span></div>
      <div class="kv"><span class="k">政府信任</span><span>${(a.status?.trust_in_government || 0).toFixed(3)}</span></div>
      ${forceBreakdownHtml(a)}
    `;
  }

  const FORCE_NAMES = {
    economic: '经济', authority: '权威', community: '社区', event: '事件',
    social: '社会', anchor: '锚点', center: '中心', coupling: '耦合', noise: '噪声',
  };

  function forceBreakdownHtml(a) {
    const f = a.forces;
    if (!f || !f.x) return '';
    const axisLabel = { x: 'X（经济）', y: 'Y（权威）', z: 'Z（集体）' };
    let html = '<div class="section-title">力分解（v0.3）</div>';
    for (const ax of ['x', 'y', 'z']) {
      const parts = [];
      for (const [src, val] of Object.entries(f[ax])) {
        if (Math.abs(val) < 1e-6) continue;
        const nm = FORCE_NAMES[src] || src;
        const sign = val > 0 ? '+' : '';
        parts.push(`${nm} ${sign}${val.toFixed(3)}`);
      }
      html += `<div class="kv"><span class="k">${axisLabel[ax]}</span><span>${parts.join(' · ') || '—'}</span></div>`;
    }
    return html;
  }

  function renderHistory(hist) {
    if (!hist || hist.length === 0) {
      const insp = $('agent-inspector');
      if (insp) insp.insertAdjacentHTML('beforeend', '<div class="section-title">历史轨迹</div><div style="color:var(--muted)">暂无历史记录。</div>');
      return;
    }
    const first = hist[0];
    const last = hist[hist.length - 1];
    const dx = (last.x - first.x).toFixed(3);
    const dy = (last.y - first.y).toFixed(3);
    const dz = (last.z - first.z).toFixed(3);
    const html = `
      <div class="section-title">历史轨迹（${hist.length} 个采样点）</div>
      <div class="kv"><span class="k">起始坐标</span><span>(${first.x.toFixed(2)}, ${first.y.toFixed(2)}, ${first.z.toFixed(2)})</span></div>
      <div class="kv"><span class="k">当前坐标</span><span>(${last.x.toFixed(2)}, ${last.y.toFixed(2)}, ${last.z.toFixed(2)})</span></div>
      <div class="kv"><span class="k">位移 (x,y,z)</span><span>(${dx}, ${dy}, ${dz})</span></div>
    `;
    const insp = $('agent-inspector');
    if (insp) insp.insertAdjacentHTML('beforeend', html);
  }

  function evLabel(e) {
    return EVENT_LABELS[e.type] || e.type;
  }

  function renderTimeline() {
    if (state.currentTab === 'graph') { renderGraph(); return; }
    if (state.currentTab === 'distribution') { renderDistribution(); return; }
    if (state.currentTab === 'clusters') { renderClusters(); return; }
    const el = $('timeline-list');
    const evs = state.events.slice().reverse();
    el.innerHTML = evs.length
      ? evs
          .map(
            (e) =>
              `<div class="event-item ${e.type}" data-event="${e.event_id}">
                 <span class="tick">[${e.tick}]</span>
                 <span class="etype">${evLabel(e)}</span>
                 <span class="sev">${(e.severity || 0).toFixed(2)}</span>
               </div>`
          )
          .join('')
      : '<div style="color:var(--muted);padding:8px">暂无事件。</div>';

    el.querySelectorAll('.event-item').forEach((node) => {
      node.addEventListener('click', () => showEventChain(node.dataset.event));
    });
  }

  function showEventChain(eventId) {
    const ev = state.events.find((e) => e.event_id === eventId);
    if (!ev) return;
    const chain = buildChain(ev);
    renderChainView(ev, chain);
  }

  function buildChain(root) {
    const children = state.events.filter((e) => e.cause_event_id === root.event_id);
    return { event: root, children: children.map(buildChain) };
  }

  function renderChainView(root, chain) {
    const el = $('timeline-list');
    el.innerHTML = `<div style="color:var(--muted);font-size:11px;margin-bottom:6px">事件因果链 — 点击事件查看后续</div>`;
    el.appendChild(chainNode(chain));
  }

  function chainNode(node) {
    const div = document.createElement('div');
    div.className = 'chain-node';
    div.innerHTML = `<span class="etype">${evLabel(node.event)}</span>
      <span style="color:var(--muted);font-size:11px"> [tick ${node.event.tick}] · ${node.event.description || ''}</span>`;
    node.children.forEach((c) => div.appendChild(chainNode(c)));
    return div;
  }

  function renderGraph() {
    const el = $('timeline-list');
    const causes = {};
    state.events.forEach((e) => {
      if (e.cause_event_id) {
        (causes[e.cause_event_id] = causes[e.cause_event_id] || []).push(e);
      }
    });
    const roots = state.events.filter((e) => !e.cause_event_id).slice(-20);
    const html = roots
      .map(
        (r) =>
          `<div class="chain-node"><span class="etype">${evLabel(r)}</span>
           <span style="color:var(--muted);font-size:11px">[tick ${r.tick}]</span>
           ${(causes[r.event_id] || []).map((c) => `<div class="chain-node"><span class="etype">${evLabel(c)}</span> <span style="color:var(--muted);font-size:11px">[tick ${c.tick}]</span></div>`).join('')}
           </div>`
      )
      .join('');
    el.innerHTML = html || '<div style="color:var(--muted);padding:8px">暂无因果链。</div>';
  }

  function renderDistribution() {
    if (!state.societyId) return;
    const el = $('timeline-list');
    el.innerHTML = '<div style="color:var(--muted)">加载中…</div>';
    api(`/api/society/${state.societyId}/politics/distribution?bins=20`)
      .then((r) => {
        el.innerHTML = '';
        const names = { x: 'X（经济自由↔管控）', y: 'Y（自由↔权威）', z: 'Z（个体↔集体）' };
        for (const axis of ['x', 'y', 'z']) {
          el.appendChild(histogramBlock(axis, names[axis], r[axis]));
        }
      })
      .catch(() => { el.innerHTML = '<div style="color:var(--muted)">加载失败</div>'; });
  }

  function histogramBlock(axis, name, d) {
    const div = document.createElement('div');
    div.style.marginBottom = '12px';
    const max = Math.max(...d.counts, 1);
    const color = axis === 'x' ? '#f85149' : axis === 'y' ? '#3fb950' : '#58a6ff';
    const w = 100 / d.counts.length;
    const bars = d.counts.map((c) => {
      const h = Math.round((c / max) * 60);
      return `<div style="display:inline-block;width:${w}%;text-align:center;vertical-align:bottom">
        <div style="height:${h}px;background:${color};margin:0 1px;border-radius:1px;opacity:.8" title="${c}"></div>
      </div>`;
    }).join('');
    div.innerHTML = `<div style="color:var(--muted);font-size:11px;margin-bottom:4px">${name} 分布</div>
      <div style="display:flex;align-items:flex-end;height:64px">${bars}</div>
      <div style="display:flex;justify-content:space-between;color:var(--muted);font-size:10px"><span>-1</span><span>0</span><span>+1</span></div>`;
    return div;
  }

  function renderClusters() {
    if (!state.societyId) return;
    const el = $('timeline-list');
    el.innerHTML = '<div style="color:var(--muted)">加载中…</div>';
    api(`/api/society/${state.societyId}/politics/clusters?min_size=15`)
      .then((r) => {
        if (!r.clusters.length) {
          el.innerHTML = '<div style="color:var(--muted);padding:8px">未检测到明显政治簇。</div>';
          return;
        }
        el.innerHTML = r.clusters.map((c, i) => `
          <div class="event-item">
            <span class="tick">#${i + 1}</span>
            <span class="etype">人口 ${(c.ratio * 100).toFixed(0)}%</span>
            <span class="sev">中心 (${c.center[0]}, ${c.center[1]}, ${c.center[2]})</span>
          </div>`).join('');
      })
      .catch(() => { el.innerHTML = '<div style="color:var(--muted)">加载失败</div>'; });
  }

  // ---- 控件绑定 ---------------------------------------------------------
  $('btn-create').addEventListener('click', createSociety);
  $('btn-play').addEventListener('click', async () => {
    if (!state.societyId) { alert('请先创建社会'); return; }
    const speed = Number($('speed-select').value);
    await api(`/api/society/${state.societyId}/start?speed=${speed}`, { method: 'POST' });
    setStatus('running');
  });
  $('btn-pause').addEventListener('click', async () => {
    if (!state.societyId) return;
    await api(`/api/society/${state.societyId}/pause`, { method: 'POST' });
    setStatus('paused');
  });
  $('btn-step').addEventListener('click', async () => {
    if (!state.societyId) { alert('请先创建社会'); return; }
    await api(`/api/society/${state.societyId}/step?ticks=1`, { method: 'POST' });
    await loadMetrics();
    await loadEvents();
    await refreshAgentPositions();
  });
  $('btn-reset').addEventListener('click', async () => {
    if (!state.societyId) return;
    await api(`/api/society/${state.societyId}/reset`, { method: 'POST' });
    await loadAgents();
    await loadMetrics();
    await loadEvents();
    setStatus('created');
  });
  $('speed-select').addEventListener('change', async () => {
    if (!state.societyId) return;
    const speed = Number($('speed-select').value);
    $('sim-speed').textContent = `速度 ×${speed}`;
    await api(`/api/society/${state.societyId}/speed?speed=${speed}`, { method: 'POST' });
  });

  // 显示模式按钮
  document.querySelectorAll('.mode-bar button').forEach((b) => {
    b.addEventListener('click', () => {
      document.querySelectorAll('.mode-bar button').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      spectrum.setMode(b.dataset.mode);
      if (b.dataset.mode === 'trajectory') loadTrajectories();
    });
  });

  async function loadTrajectories() {
    if (!state.societyId) return;
    try {
      const r = await api(`/api/society/${state.societyId}/trajectory?agents=50&limit=500`);
      spectrum.history = {};
      for (const [id, pts] of Object.entries(r.trajectories)) {
        spectrum.history[id] = pts;
      }
      spectrum.draw();
    } catch (e) { /* 暂无历史 */ }
  }

  // 速度向量开关（§28, §29）
  $('btn-velocity').addEventListener('click', () => {
    const on = $('btn-velocity').classList.toggle('active');
    spectrum.setVelocity(on);
  });

  // 投影切换（§17）
  document.querySelectorAll('.mode-bar [data-proj]').forEach((b) => {
    b.addEventListener('click', () => {
      document.querySelectorAll('.mode-bar [data-proj]').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      spectrum.setProjection(b.dataset.proj);
    });
  });

  // 底部标签栏
  document.querySelectorAll('.tab-bar button').forEach((b) => {
    b.addEventListener('click', () => {
      document.querySelectorAll('.tab-bar button').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      state.currentTab = b.dataset.tab;
      renderTimeline();
    });
  });

  // 提供方切换
  $('cfg-provider').addEventListener('change', () => {
    $('cfg-baseurl-wrap').style.display = $('cfg-provider').value === 'rule_based' ? 'none' : 'block';
  });

  // ---- 加载意识形态配色 + 坐标轴定义 ------------------------------------
  async function loadColors() {
    const r = await api('/api/config/ideologies');
    const cm = {};
    for (const [k, v] of Object.entries(r.templates)) cm[k] = v.color;
    spectrum.setColors(cm);
    spectrum.setAxes(r.axes || {});
    const legend = $('spectrum-legend');
    legend.innerHTML = Object.entries(r.templates)
      .map(
        ([k, v]) =>
          `<div class="legend-item"><span class="dot" style="background:${v.color}"></span>${IDEO_LABELS[k] || k}</div>`
      )
      .join('');
  }
  loadColors();

  spectrum.draw();
})();
