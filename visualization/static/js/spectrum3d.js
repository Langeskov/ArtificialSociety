/* spectrum3d.js — self-contained 3D scatter renderer (Canvas 2D).
 *
 * Renders the 3D political spectrum (x,y,z ∈ [-1,1]) with orbit controls,
 * click selection, and four display modes. No external libraries.
 */
(function (global) {
  'use strict';

  const TAU = Math.PI * 2;

  function Spectrum3D(canvas, opts) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.opts = opts || {};

    // Camera
    this.yaw = 0.6;        // rotation around Y
    this.pitch = -0.35;    // rotation around X
    this.dist = 4.2;       // zoom (distance)
    this.panX = 0;
    this.panY = 0;

    // Data
    this.agents = [];      // {id, x, y, z, origin_label, money, food, influence, group, alive, anger}
    this.colorMap = {};    // origin_label -> color
    this.axes = null;      // {x:{positive,negative}, y:{...}, z:{...}}
    this.mode = 'individual';
    this.selectedId = null;
    this.history = {};     // agent_id -> [{x,y,z,tick}, ...] for trajectory mode
    this.showVelocity = false;  // v0.2: 速度向量开关 (§28, §29)
    this.projection = '3d';     // v0.3: 3d | xy | xz | yz (§17)

    this.onSelect = null;  // callback(agentId)
    this._dragging = false;
    this._panning = false;
    this._lastX = 0;
    this._lastY = 0;
    this._projected = [];  // cache for hit-testing

    this._bindEvents();
    this.resize();
  }

  Spectrum3D.prototype.resize = function () {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.w = rect.width;
    this.h = rect.height;
    this.canvas.width = this.w * dpr;
    this.canvas.height = this.h * dpr;
    this.canvas.style.width = this.w + 'px';
    this.canvas.style.height = this.h + 'px';
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.draw();
  };

  Spectrum3D.prototype._bindEvents = function () {
    const c = this.canvas;
    const self = this;

    c.addEventListener('mousedown', (e) => {
      self._dragging = true;
      self._panning = (e.button === 2);
      self._lastX = e.clientX;
      self._lastY = e.clientY;
    });
    window.addEventListener('mousemove', (e) => {
      if (!self._dragging) return;
      const dx = e.clientX - self._lastX;
      const dy = e.clientY - self._lastY;
      self._lastX = e.clientX;
      self._lastY = e.clientY;
      if (self._panning) {
        self.panX += dx * 0.005;
        self.panY -= dy * 0.005;
      } else {
        self.yaw += dx * 0.008;
        self.pitch += dy * 0.008;
        self.pitch = Math.max(-1.5, Math.min(1.5, self.pitch));
      }
      self.draw();
    });
    window.addEventListener('mouseup', () => { self._dragging = false; self._panning = false; });

    c.addEventListener('wheel', (e) => {
      e.preventDefault();
      self.dist *= (1 + Math.sign(e.deltaY) * 0.08);
      self.dist = Math.max(1.5, Math.min(12, self.dist));
      self.draw();
    }, { passive: false });

    c.addEventListener('click', (e) => {
      if (self._panning) return;
      const rect = c.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const hit = self._hitTest(mx, my);
      if (hit) {
        self.selectedId = hit;
        if (self.onSelect) self.onSelect(hit);
        self.draw();
      }
    });

    c.addEventListener('contextmenu', (e) => e.preventDefault());

    window.addEventListener('resize', () => self.resize());
  };

  Spectrum3D.prototype.setAgents = function (agents) {
    this.agents = agents;
    this.draw();
  };

  Spectrum3D.prototype.setColors = function (colorMap) {
    this.colorMap = colorMap || {};
    this.draw();
  };

  Spectrum3D.prototype.setAxes = function (axes) {
    this.axes = axes || null;
    this.draw();
  };

  Spectrum3D.prototype.setMode = function (mode) {
    this.mode = mode;
    this.draw();
  };

  Spectrum3D.prototype.setVelocity = function (on) {
    this.showVelocity = !!on;
    this.draw();
  };

  Spectrum3D.prototype.setProjection = function (proj) {
    this.projection = proj || '3d';
    this.draw();
  };

  Spectrum3D.prototype.setSelected = function (id) {
    this.selectedId = id;
    this.draw();
  };

  Spectrum3D.prototype.pushHistory = function (agentId, x, y, z, tick) {
    if (!this.history[agentId]) this.history[agentId] = [];
    const h = this.history[agentId];
    h.push({ x, y, z, tick });
    if (h.length > 200) h.shift();
  };

  // --- projection --------------------------------------------------------
  Spectrum3D.prototype._project = function (x, y, z) {
    // v0.3: 2D 投影（§17）——直接忽略第三个轴
    if (this.projection === 'xy') {
      const s = this.h * 0.4;
      return { sx: this.w / 2 + x * s, sy: this.h / 2 - y * s, z: z, persp: 1 };
    }
    if (this.projection === 'xz') {
      const s = this.h * 0.4;
      return { sx: this.w / 2 + x * s, sy: this.h / 2 - z * s, z: y, persp: 1 };
    }
    if (this.projection === 'yz') {
      const s = this.h * 0.4;
      return { sx: this.w / 2 + y * s, sy: this.h / 2 - z * s, z: x, persp: 1 };
    }
    // World coords: x,y,z ∈ [-1,1] scaled to [-1,1] cube, Y up.
    const cosY = Math.cos(this.yaw), sinY = Math.sin(this.yaw);
    const cosP = Math.cos(this.pitch), sinP = Math.sin(this.pitch);

    // Rotate around Y, then around X.
    let x1 = x * cosY - z * sinY;
    let z1 = x * sinY + z * cosY;
    let y1 = y * cosP - z1 * sinP;
    let z2 = y * sinP + z1 * cosP;

    // Camera sits at distance `dist` along +Z (after transform).
    const scale = this.h * 0.35;
    const f = this.dist;
    const camZ = f;
    const persp = camZ / (camZ - z2);   // perspective factor
    const sx = this.w / 2 + (x1 + this.panX) * scale * persp;
    const sy = this.h / 2 - (y1 + this.panY) * scale * persp;
    return { sx, sy, z: z2, persp };
  };

  // --- drawing -----------------------------------------------------------
  Spectrum3D.prototype.draw = function () {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.w, this.h);

    // Background axes (cube wireframe)
    this._drawAxes(ctx);

    const pts = [];
    for (const a of this.agents) {
      if (a.alive === false) continue;
      const p = this._project(a.x, a.y, a.z);
      pts.push({ a, ...p });
    }

    // Depth sort (far first)
    pts.sort((p, q) => q.z - p.z);

    if (this.mode === 'density') {
      this._drawDensity(ctx, pts);
    } else if (this.mode === 'trajectory') {
      this._drawTrajectories(ctx);
      this._drawPoints(ctx, pts);
    } else {
      this._drawPoints(ctx, pts);
    }

    // v0.2: 速度向量叠加（§28, §29）
    if (this.showVelocity) {
      this._drawVelocity(ctx, pts);
    }

    this._projected = pts.map((p) => ({ id: p.a.id, sx: p.sx, sy: p.sy, z: p.z }));
  };

  Spectrum3D.prototype._drawAxes = function (ctx) {
    const corners = [
      [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
      [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1],
    ];
    const proj = corners.map((c) => this._project(c[0], c[1], c[2]));
    const edges = [
      [0, 1], [1, 2], [2, 3], [3, 0],
      [4, 5], [5, 6], [6, 7], [7, 4],
      [0, 4], [1, 5], [2, 6], [3, 7],
    ];
    ctx.strokeStyle = 'rgba(139,148,158,0.15)';
    ctx.lineWidth = 1;
    for (const [i, j] of edges) {
      ctx.beginPath();
      ctx.moveTo(proj[i].sx, proj[i].sy);
      ctx.lineTo(proj[j].sx, proj[j].sy);
      ctx.stroke();
    }

    // Axis arrows with direction labels (X=red, Y=green, Z=blue).
    const axes = this.axes || {};
    const L = 1.35;  // draw slightly past the [-1,1] cube
    this._drawAxisArrow(ctx, [-L, 0, 0], [L, 0, 0], 'rgba(248,81,73,0.85)', '#f85149');
    this._drawAxisArrow(ctx, [0, -L, 0], [0, L, 0], 'rgba(63,185,80,0.85)', '#3fb950');
    this._drawAxisArrow(ctx, [0, 0, -L], [0, 0, L], 'rgba(88,166,255,0.85)', '#58a6ff');

    this._drawAxisLabel(ctx, L + 0.14, 0, 0, 'X · ' + ((axes.x && axes.x.positive) || '经济自由'), '#f85149');
    this._drawAxisLabel(ctx, -L - 0.14, 0, 0, 'X · ' + ((axes.x && axes.x.negative) || '经济管控'), '#f85149');
    this._drawAxisLabel(ctx, 0, L + 0.14, 0, 'Y · ' + ((axes.y && axes.y.positive) || '权威'), '#3fb950');
    this._drawAxisLabel(ctx, 0, -L - 0.14, 0, 'Y · ' + ((axes.y && axes.y.negative) || '自由'), '#3fb950');
    this._drawAxisLabel(ctx, 0, 0, L + 0.14, 'Z · ' + ((axes.z && axes.z.positive) || '个人主义'), '#58a6ff');
    this._drawAxisLabel(ctx, 0, 0, -L - 0.14, 'Z · ' + ((axes.z && axes.z.negative) || '集体主义'), '#58a6ff');
  };

  Spectrum3D.prototype._drawAxisArrow = function (ctx, from, to, color, headColor) {
    const a = this._project(from[0], from[1], from[2]);
    const b = this._project(to[0], to[1], to[2]);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.moveTo(a.sx, a.sy);
    ctx.lineTo(b.sx, b.sy);
    ctx.stroke();

    // Arrowhead at the + end.
    const ang = Math.atan2(b.sy - a.sy, b.sx - a.sx);
    const size = 6;
    ctx.fillStyle = headColor || color;
    ctx.beginPath();
    ctx.moveTo(b.sx, b.sy);
    ctx.lineTo(b.sx - size * Math.cos(ang - 0.42), b.sy - size * Math.sin(ang - 0.42));
    ctx.lineTo(b.sx - size * Math.cos(ang + 0.42), b.sy - size * Math.sin(ang + 0.42));
    ctx.closePath();
    ctx.fill();
  };

  Spectrum3D.prototype._drawAxisLabel = function (ctx, x, y, z, text, color) {
    const p = this._project(x, y, z);
    ctx.font = '11px "Microsoft YaHei", "Segoe UI", sans-serif';
    const w = ctx.measureText(text).width;
    ctx.fillStyle = 'rgba(13,17,23,0.78)';
    ctx.fillRect(p.sx + 5, p.sy - 9, w + 10, 18);
    ctx.strokeStyle = 'rgba(48,54,61,0.5)';
    ctx.lineWidth = 1;
    ctx.strokeRect(p.sx + 5, p.sy - 9, w + 10, 18);
    ctx.fillStyle = color;
    ctx.fillText(text, p.sx + 10, p.sy + 3);
  };

  Spectrum3D.prototype._drawAxisLine = function (ctx, from, to, color) {
    const a = this._project(from[0], from[1], from[2]);
    const b = this._project(to[0], to[1], to[2]);
    ctx.strokeStyle = color;
    ctx.beginPath();
    ctx.moveTo(a.sx, a.sy);
    ctx.lineTo(b.sx, b.sy);
    ctx.stroke();
  };

  Spectrum3D.prototype._colorFor = function (a) {
    if (this.mode === 'group') {
      const g = a.group || a.origin_label;
      return this.colorMap[g] || '#8b949e';
    }
    // Color by anger severity overlay: blend origin color toward red as anger rises
    const base = this.colorMap[a.origin_label] || '#8b949e';
    const anger = a.anger || 0;
    if (anger > 0.5) {
      return this._mix(base, '#f85149', (anger - 0.5) * 1.4);
    }
    return base;
  };

  Spectrum3D.prototype._mix = function (c1, c2, t) {
    t = Math.max(0, Math.min(1, t));
    const a = this._hexToRgb(c1), b = this._hexToRgb(c2);
    const r = Math.round(a[0] + (b[0] - a[0]) * t);
    const g = Math.round(a[1] + (b[1] - a[1]) * t);
    const bl = Math.round(a[2] + (b[2] - a[2]) * t);
    return `rgb(${r},${g},${bl})`;
  };

  Spectrum3D.prototype._hexToRgb = function (hex) {
    const m = hex.replace('#', '');
    const n = parseInt(m.length === 3 ? m.split('').map(c => c + c).join('') : m, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  };

  Spectrum3D.prototype._drawPoints = function (ctx, pts) {
    for (const p of pts) {
      const r = p.a.id === this.selectedId ? 4.5 : 2.0;
      const color = this._colorFor(p.a);
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.85;
      ctx.beginPath();
      ctx.arc(p.sx, p.sy, r, 0, TAU);
      ctx.fill();
      if (p.a.id === this.selectedId) {
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
  };

  Spectrum3D.prototype._drawVelocity = function (ctx, pts) {
    // 从每个 Agent 当前位置画一条指向政治移动方向的箭头 (§29)
    ctx.lineWidth = 1;
    for (const p of pts) {
      const a = p.a;
      const vx = a.vx || 0, vy = a.vy || 0, vz = a.vz || 0;
      const mag = Math.sqrt(vx * vx + vy * vy + vz * vz);
      if (mag < 1e-5) continue;
      const scale = 20 / mag;  // 速度很小（<=0.03），放大到可见长度
      const ex = a.x + vx * scale;
      const ey = a.y + vy * scale;
      const ez = a.z + vz * scale;
      const q = this._project(ex, ey, ez);
      ctx.strokeStyle = 'rgba(255,255,255,0.55)';
      ctx.beginPath();
      ctx.moveTo(p.sx, p.sy);
      ctx.lineTo(q.sx, q.sy);
      ctx.stroke();
      // 箭头
      const ang = Math.atan2(q.sy - p.sy, q.sx - p.sx);
      const s = 4;
      ctx.fillStyle = 'rgba(255,255,255,0.55)';
      ctx.beginPath();
      ctx.moveTo(q.sx, q.sy);
      ctx.lineTo(q.sx - s * Math.cos(ang - 0.5), q.sy - s * Math.sin(ang - 0.5));
      ctx.lineTo(q.sx - s * Math.cos(ang + 0.5), q.sy - s * Math.sin(ang + 0.5));
      ctx.closePath();
      ctx.fill();
    }
  };

  Spectrum3D.prototype._drawDensity = function (ctx, pts) {
    // Approximate density: draw large soft blobs; nearby points overlap more.
    ctx.globalAlpha = 0.10;
    for (const p of pts) {
      ctx.fillStyle = this._colorFor(p.a);
      ctx.beginPath();
      ctx.arc(p.sx, p.sy, 8, 0, TAU);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  };

  Spectrum3D.prototype._drawTrajectories = function (ctx) {
    const colorById = {};
    for (const a of this.agents) colorById[a.id] = this.colorMap[a.origin_label] || '#8b949e';
    ctx.globalAlpha = 0.5;
    for (const id in this.history) {
      const h = this.history[id];
      if (h.length < 2) continue;
      ctx.strokeStyle = colorById[id] || '#8b949e';
      ctx.lineWidth = 1;
      ctx.beginPath();
      let started = false;
      for (const pt of h) {
        const p = this._project(pt.x, pt.y, pt.z);
        if (!started) { ctx.moveTo(p.sx, p.sy); started = true; }
        else ctx.lineTo(p.sx, p.sy);
      }
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  };

  // --- hit test ----------------------------------------------------------
  Spectrum3D.prototype._hitTest = function (mx, my) {
    let best = null;
    let bestD = 10; // px threshold
    for (const p of this._projected) {
      const dx = p.sx - mx, dy = p.sy - my;
      const d = Math.sqrt(dx * dx + dy * dy);
      if (d < bestD) { bestD = d; best = p.id; }
    }
    return best;
  };

  global.Spectrum3D = Spectrum3D;
})(window);
