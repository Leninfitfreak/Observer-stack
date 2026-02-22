import { normalizeSeverity, summarizeNodeStatus } from './transform.js';

export class DependencyMap {
  constructor({ mount, store, config, onFocusService }) {
    this.mount = mount;
    this.store = store;
    this.config = config;
    this.onFocusService = onFocusService;

    this.scale = 1;
    this.tx = 0;
    this.ty = 0;
    this.pointers = new Map();
    this.isPanning = false;
    this.lastPan = null;
    this.data = { nodes: [], edges: [] };
    this.adj = new Map();

    this.root = document.createElement('div');
    this.root.className = 'depmap-root';

    this.toolbar = document.createElement('div');
    this.toolbar.className = 'depmap-toolbar';
    this.fitBtn = this._toolBtn('Fit', () => this.fitToScreen());
    this.resetBtn = this._toolBtn('Reset', () => this.resetView());
    this.focusBtn = this._toolBtn('Reset Focus', () => this.store.setState({ selectedService: 'all', focusMode: false }));
    this.toolbar.append(this.fitBtn, this.resetBtn, this.focusBtn);

    this.svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    this.svg.setAttribute('viewBox', '0 0 1400 900');
    this.svg.classList.add('depmap-svg');

    this.defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
    marker.setAttribute('id', 'arrowhead');
    marker.setAttribute('markerWidth', '8');
    marker.setAttribute('markerHeight', '6');
    marker.setAttribute('refX', '7');
    marker.setAttribute('refY', '3');
    marker.setAttribute('orient', 'auto');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M0,0 L8,3 L0,6 Z');
    path.setAttribute('fill', '#5f7da8');
    marker.appendChild(path);
    this.defs.appendChild(marker);

    this.viewport = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    this.edgesLayer = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    this.nodesLayer = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    this.viewport.append(this.edgesLayer, this.nodesLayer);
    this.svg.append(this.defs, this.viewport);

    this.root.append(this.toolbar, this.svg);
    this.mount.appendChild(this.root);

    this._bindEvents();
    this.unsubscribe = store.subscribe((state) => this._applyState(state));
  }

  destroy() {
    this.unsubscribe?.();
  }

  _toolBtn(label, onClick) {
    const btn = document.createElement('button');
    btn.className = 'depmap-btn';
    btn.type = 'button';
    btn.textContent = label;
    btn.addEventListener('click', onClick);
    return btn;
  }

  _bindEvents() {
    this.svg.addEventListener('wheel', (ev) => {
      ev.preventDefault();
      const factor = ev.deltaY > 0 ? 1 / this.config.map.zoomStep : this.config.map.zoomStep;
      this.zoomAt(ev.offsetX, ev.offsetY, factor);
    }, { passive: false });

    this.svg.addEventListener('dblclick', (ev) => {
      ev.preventDefault();
      this.zoomAt(ev.offsetX, ev.offsetY, this.config.map.zoomStep);
    });

    this.svg.addEventListener('pointerdown', (ev) => {
      this.svg.setPointerCapture(ev.pointerId);
      this.pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
      if (this.pointers.size === 1) {
        this.isPanning = true;
        this.lastPan = { x: ev.clientX, y: ev.clientY };
      }
    });

    this.svg.addEventListener('pointermove', (ev) => {
      if (!this.pointers.has(ev.pointerId)) return;
      const prev = this.pointers.get(ev.pointerId);
      this.pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });

      if (this.pointers.size === 2) {
        const pts = [...this.pointers.values()];
        const d1 = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
        const d0 = Math.hypot((pts[0].x - (prev?.x ?? pts[0].x)), (pts[0].y - (prev?.y ?? pts[0].y)));
        if (d0 > 0) {
          const factor = d1 > d0 ? 1.01 : 0.99;
          this.zoomAt(ev.offsetX, ev.offsetY, factor);
        }
        return;
      }

      if (this.isPanning && this.lastPan) {
        this.tx += ev.clientX - this.lastPan.x;
        this.ty += ev.clientY - this.lastPan.y;
        this.lastPan = { x: ev.clientX, y: ev.clientY };
        this._applyTransform();
      }
    });

    const stopPointer = (ev) => {
      this.pointers.delete(ev.pointerId);
      if (this.pointers.size === 0) {
        this.isPanning = false;
        this.lastPan = null;
      }
    };
    this.svg.addEventListener('pointerup', stopPointer);
    this.svg.addEventListener('pointercancel', stopPointer);

    window.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape') {
        this.store.setState((s) => ({ ...s, fullscreenPanel: null }));
      }
    });
  }

  zoomAt(x, y, factor) {
    const minScale = this.config.map.minScale;
    const maxScale = this.config.map.maxScale;
    const next = Math.max(minScale, Math.min(maxScale, this.scale * factor));
    const ratio = next / this.scale;
    this.tx = x - (x - this.tx) * ratio;
    this.ty = y - (y - this.ty) * ratio;
    this.scale = next;
    this._applyTransform();
  }

  fitToScreen() {
    if (!this.data.nodes.length) return;
    const xs = this.data.nodes.map((n) => n.x);
    const ys = this.data.nodes.map((n) => n.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const contentW = Math.max(1, maxX - minX + 160);
    const contentH = Math.max(1, maxY - minY + 120);
    const vw = this.svg.clientWidth || 1200;
    const vh = this.svg.clientHeight || 700;
    this.scale = Math.max(this.config.map.minScale, Math.min(this.config.map.maxScale, Math.min(vw / contentW, vh / contentH)));
    this.tx = (vw - contentW * this.scale) / 2 - (minX - 80) * this.scale;
    this.ty = (vh - contentH * this.scale) / 2 - (minY - 60) * this.scale;
    this._applyTransform();
  }

  resetView() {
    this.scale = 1;
    this.tx = 0;
    this.ty = 0;
    this._applyTransform();
  }

  _applyTransform() {
    this.viewport.setAttribute('transform', `translate(${this.tx}, ${this.ty}) scale(${this.scale})`);
    this.store.setState((s) => ({ ...s, zoomState: { ...s.zoomState, map: { scale: this.scale, tx: this.tx, ty: this.ty } } }));
  }

  _layout(nodes, edges, expanded) {
    const serviceNodes = nodes.filter((n) => n.kind === 'service');
    const podNodes = nodes.filter((n) => n.kind === 'pod');
    const columns = expanded ? 4 : 3;
    const hGap = expanded ? 260 : 210;
    const vGap = expanded ? 150 : 120;

    serviceNodes.forEach((n, i) => {
      n.x = 120 + (i % columns) * hGap;
      n.y = 100 + Math.floor(i / columns) * vGap;
    });

    const byService = new Map();
    edges.forEach((e) => {
      if (!byService.has(e.from)) byService.set(e.from, []);
      byService.get(e.from).push(e.to);
    });

    podNodes.forEach((n, i) => {
      let attachedService = null;
      for (const [svc, pods] of byService.entries()) {
        if (pods.includes(n.id)) {
          attachedService = serviceNodes.find((x) => x.id === svc);
          break;
        }
      }
      if (attachedService) {
        n.x = attachedService.x + ((i % 2) ? 90 : -90);
        n.y = attachedService.y + 70 + Math.floor(i / 2) * 40;
      } else {
        n.x = 900 + (i % 2) * 120;
        n.y = 120 + Math.floor(i / 2) * 45;
      }
    });
  }

  setData({ wiring, metricsByService = {}, anomalyService }) {
    const nodes = (wiring?.nodes || []).map((n) => ({ ...n, status: normalizeSeverity(n.status) }));
    const edges = (wiring?.edges || []).map((e) => ({ ...e }));
    this.data = { nodes, edges, metricsByService, anomalyService };
    this._layout(nodes, edges, this.store.getState().fullscreenPanel === 'dependency-map');
    this._buildAdj();
    this.render(this.store.getState());
    if (anomalyService) this._autoZoomCluster(anomalyService);
  }

  _buildAdj() {
    this.adj = new Map();
    this.data.nodes.forEach((n) => this.adj.set(n.id, { in: new Set(), out: new Set() }));
    this.data.edges.forEach((e) => {
      if (this.adj.has(e.from)) this.adj.get(e.from).out.add(e.to);
      if (this.adj.has(e.to)) this.adj.get(e.to).in.add(e.from);
    });
  }

  _activeCluster(selected) {
    if (!selected || selected === 'all' || !this.adj.has(selected)) return null;
    const active = new Set([selected]);
    const q = [selected];
    while (q.length) {
      const cur = q.shift();
      const links = this.adj.get(cur);
      [...links.out, ...links.in].forEach((n) => {
        if (!active.has(n)) {
          active.add(n);
          q.push(n);
        }
      });
    }
    return active;
  }

  _autoZoomCluster(service) {
    const active = this._activeCluster(service);
    if (!active) return;
    const nodes = this.data.nodes.filter((n) => active.has(n.id));
    if (!nodes.length) return;
    const xs = nodes.map((n) => n.x);
    const ys = nodes.map((n) => n.y);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
    const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    this.scale = Math.min(this.config.map.maxScale, 1.6);
    const vw = this.svg.clientWidth || 1200;
    const vh = this.svg.clientHeight || 700;
    this.tx = vw / 2 - cx * this.scale;
    this.ty = vh / 2 - cy * this.scale;
    this._applyTransform();
  }

  _applyState(state) {
    this.root.classList.toggle('is-fullscreen', state.fullscreenPanel === 'dependency-map');
    this.render(state);
  }

  render(state) {
    const { nodes, edges, metricsByService } = this.data;
    const activeCluster = state.focusMode ? this._activeCluster(state.selectedService) : null;

    while (this.edgesLayer.firstChild) this.edgesLayer.removeChild(this.edgesLayer.firstChild);
    while (this.nodesLayer.firstChild) this.nodesLayer.removeChild(this.nodesLayer.firstChild);

    edges.forEach((e) => {
      const from = nodes.find((n) => n.id === e.from);
      const to = nodes.find((n) => n.id === e.to);
      if (!from || !to) return;

      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', String(from.x));
      line.setAttribute('y1', String(from.y));
      line.setAttribute('x2', String(to.x));
      line.setAttribute('y2', String(to.y));
      line.setAttribute('class', 'dep-edge');
      line.setAttribute('marker-end', 'url(#arrowhead)');

      if (activeCluster && (!activeCluster.has(from.id) || !activeCluster.has(to.id))) {
        line.classList.add('dimmed');
      } else if (state.focusMode && activeCluster) {
        line.classList.add('active');
      }
      this.edgesLayer.appendChild(line);
    });

    nodes.forEach((node) => {
      const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      group.classList.add('dep-node');
      group.dataset.nodeId = node.id;
      group.setAttribute('transform', `translate(${node.x}, ${node.y})`);

      const radius = node.kind === 'service' ? this.config.map.nodeRadius.service : this.config.map.nodeRadius.pod;
      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('r', String(radius));
      circle.setAttribute('class', `severity-${node.status || 'unknown'}`);

      if (node.id === this.data.anomalyService) {
        circle.classList.add('pulse');
      }

      const name = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      name.setAttribute('y', String(radius + 13));
      name.setAttribute('text-anchor', 'middle');
      name.setAttribute('class', 'dep-label');
      name.textContent = node.id;

      group.append(circle, name);

      if (node.kind === 'service') {
        const mini = summarizeNodeStatus(node, metricsByService);
        const t1 = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        t1.setAttribute('y', '-4');
        t1.setAttribute('text-anchor', 'middle');
        t1.setAttribute('class', 'dep-mini');
        t1.textContent = `p95 ${mini.p95}ms`;

        const t2 = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        t2.setAttribute('y', '8');
        t2.setAttribute('text-anchor', 'middle');
        t2.setAttribute('class', 'dep-mini');
        t2.textContent = `err ${mini.err}% cpu ${mini.cpu}%`;
        group.append(t1, t2);
      }

      group.addEventListener('click', () => {
        this.store.setState((s) => ({ ...s, selectedService: node.id, focusMode: true }));
        this.onFocusService?.(node.id);
      });

      if (activeCluster && !activeCluster.has(node.id)) {
        group.classList.add('dimmed');
      }
      if (state.selectedService === node.id) {
        group.classList.add('selected');
      }

      this.nodesLayer.appendChild(group);
    });
  }
}
