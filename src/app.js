/* Builds the apartment from PLAN at 1 unit = 1 metre and wires up views, picking and palettes. */
(function () {
  'use strict';
  var P = PLAN, H = P.height, WT = P.wallT / 1000, EYE = P.eye, CUT = 1.2;
  var SIDES = { N: 'top', E: 'right', S: 'bottom', W: 'left' };

  // ---------- UI shell ----------
  var app = document.getElementById('app');
  app.innerHTML =
    '<div id="stage"><canvas id="view" aria-label="3D model of the apartment"></canvas>' +
    '<div id="where" class="chip"></div>' +
    '<div id="hint" class="chip"></div>' +
    '<div id="stick" hidden><i></i></div></div>' +
    '<aside id="panel">' +
    '<header><h1>' + P.name + '</h1><p class="sub">Unit 07 · ' + P.carpetArea + ' carpet · modelled 1:1 in metres</p></header>' +
    '<section><h2>View</h2><div class="seg" id="views">' +
    '<button data-v="doll">Dollhouse</button><button data-v="plan">Plan</button><button data-v="walk">Walk</button></div>' +
    '<label class="row" for="goto">Stand in<select id="goto"></select></label>' +
    '<label class="check"><input type="checkbox" id="t-furn" checked> Furniture placeholders</label>' +
    '<label class="check"><input type="checkbox" id="t-cut"> Cut walls at 1.2 m</label>' +
    '<label class="check"><input type="checkbox" id="t-lab" checked> Room labels</label>' +
    '<button id="vr" hidden>Enter VR (life size)</button></section>' +
    '<section><h2>Palette</h2><label class="row" for="theme">Start from<select id="theme"></select></label>' +
    '<p class="note">The four palettes are stand-ins until the real theme palettes arrive.</p></section>' +
    '<section><h2>Selected surface</h2><p id="sel-name" class="sel">Click any wall, floor, ceiling or furniture piece.</p>' +
    '<div id="sel-fields" class="swatches"></div><button id="sel-clear" hidden>Clear this room’s overrides</button></section>' +
    '<section><h2>Whole home</h2><div id="base-fields" class="swatches"></div>' +
    '<h3>Furniture</h3><div id="furn-fields" class="swatches"></div></section>' +
    '<section><h2>Palette JSON</h2><p class="note">Copy this to save a palette, or paste one in and apply it.</p>' +
    '<textarea id="json" spellcheck="false" rows="6"></textarea>' +
    '<div class="btns"><button id="json-copy">Copy</button><button id="json-apply">Apply pasted JSON</button></div>' +
    '<p id="json-msg" class="note" role="status"></p></section></aside>';
  var $ = function (id) { return document.getElementById(id); };

  // ---------- theme state ----------
  var theme;
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function save() { try { localStorage.setItem('magnolia.theme', JSON.stringify(theme)); } catch (e) {} }
  (function () {
    try { var s = JSON.parse(localStorage.getItem('magnolia.theme')); if (s && s.base && s.furniture) theme = s; } catch (e) {}
    if (!theme) theme = clone(THEMES[1]);
    theme.rooms = theme.rooms || {};
  })();
  var roomById = {};
  P.rooms.forEach(function (r) { roomById[r.id] = r; });

  function colorFor(key) {
    var k = key.split('|'), b = theme.base, r = theme.rooms[k[1]] || {}, room = roomById[k[1]];
    switch (k[0]) {
      case 'wall': return (r.walls && r.walls[k[2]]) || r.wall || (room.kind === 'wet' && b.wallWet) || (room.kind === 'outdoor' && b.exterior) || b.wall;
      case 'floor': return r.floor || (room && room.kind === 'wet' && b.floorWet) || (room && room.kind === 'outdoor' && b.floorOutdoor) || b.floor;
      case 'ceil': return r.ceiling || b.ceiling;
      case 'ext': return b.exterior;
      case 'reveal': return b.trim;
      case 'cap': return '#2a2d30';
      case 'furn': return k[1] === 'trim' ? b.trim : (theme.furniture[k[1]] || '#999999');
    }
    return '#ff00ff';
  }

  // ---------- grid: rooms -> cells -> wall faces ----------
  function R(a) { return { z0: a[0] / 1000, z1: a[1] / 1000, x0: a[2] / 1000, x1: a[3] / 1000 }; }
  var roomRects = [];
  P.rooms.forEach(function (r) { r.rects.forEach(function (a) { var q = R(a); q.room = r.id; roomRects.push(q); }); });
  var opens = P.openings.map(function (o) { var q = R(o.rect); q.o = o; return q; });

  function axis(get0, get1) {
    var s = {};
    function add(v) { s[Math.round(v * 1000)] = 1; }
    roomRects.forEach(function (r) { add(get0(r)); add(get1(r)); add(get0(r) - WT); add(get1(r) + WT); });
    opens.forEach(function (r) { add(get0(r)); add(get1(r)); });
    var a = Object.keys(s).map(Number).sort(function (p, q) { return p - q; });
    a.unshift(a[0] - 1000); a.push(a[a.length - 1] + 1000);
    return a.map(function (v) { return v / 1000; });
  }
  var xs = axis(function (r) { return r.x0; }, function (r) { return r.x1; });
  var zs = axis(function (r) { return r.z0; }, function (r) { return r.z1; });
  var NX = xs.length - 1, NZ = zs.length - 1;
  function inside(r, x, z, t) { return x > r.x0 - t && x < r.x1 + t && z > r.z0 - t && z < r.z1 + t; }

  var cells = [];
  for (var i = 0; i < NX; i++) {
    cells.push([]);
    for (var j = 0; j < NZ; j++) {
      var cx = (xs[i] + xs[i + 1]) / 2, cz = (zs[j] + zs[j + 1]) / 2, c = { t: 'void' }, k;
      for (k = 0; k < roomRects.length; k++) if (inside(roomRects[k], cx, cz, 0)) { c = { t: 'room', room: roomRects[k].room }; break; }
      if (c.t === 'void') for (k = 0; k < opens.length; k++) if (inside(opens[k], cx, cz, 0)) { c = { t: 'open', o: opens[k].o }; break; }
      if (c.t === 'void') for (k = 0; k < roomRects.length; k++) if (inside(roomRects[k], cx, cz, WT)) { c = { t: 'wall' }; break; }
      cells[i].push(c);
    }
  }
  // enclosed voids (shafts, thick masonry) become solid
  (function () {
    var q = [[0, 0]]; cells[0][0].out = true;
    while (q.length) {
      var p = q.pop();
      [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(function (d) {
        var a = p[0] + d[0], b = p[1] + d[1];
        if (a < 0 || b < 0 || a >= NX || b >= NZ) return;
        var n = cells[a][b];
        if (n.t === 'void' && !n.out) { n.out = true; q.push([a, b]); }
      });
    }
    cells.forEach(function (col) { col.forEach(function (n) { if (n.t === 'void' && !n.out) n.t = 'wall'; }); });
  })();

  var VOID = { t: 'void' };
  function cellAt(i, j) { return (i < 0 || j < 0 || i >= NX || j >= NZ) ? VOID : cells[i][j]; }
  function solids(c) {
    if (c.t === 'wall') return [[0, H]];
    if (c.t !== 'open') return [];
    var a = [];
    if (c.o.sill > 0) a.push([0, c.o.sill]);
    if (c.o.head < H) a.push([c.o.head, H]);
    return a;
  }
  function minus(A, B) {
    var out = A.slice();
    B.forEach(function (b) {
      var nx = [];
      out.forEach(function (a) {
        if (b[1] <= a[0] || b[0] >= a[1]) { nx.push(a); return; }
        if (b[0] > a[0]) nx.push([a[0], b[0]]);
        if (b[1] < a[1]) nx.push([b[1], a[1]]);
      });
      out = nx;
    });
    return out;
  }

  var geo = {};
  function quad(key, p, n) { // p: 4 corners in order; winding fixed to match normal n
    var g = geo[key] || (geo[key] = { pos: [], nor: [] });
    var ux = p[1][0] - p[0][0], uy = p[1][1] - p[0][1], uz = p[1][2] - p[0][2];
    var vx = p[2][0] - p[0][0], vy = p[2][1] - p[0][1], vz = p[2][2] - p[0][2];
    var d = (uy * vz - uz * vy) * n[0] + (uz * vx - ux * vz) * n[1] + (ux * vy - uy * vx) * n[2];
    var o = d >= 0 ? [0, 1, 2, 0, 2, 3] : [0, 2, 1, 0, 3, 2];
    o.forEach(function (ix) { g.pos.push(p[ix][0], p[ix][1], p[ix][2]); g.nor.push(n[0], n[1], n[2]); });
  }
  function flat(key, i, j, y, up) {
    quad(key, [[xs[i], y, zs[j]], [xs[i + 1], y, zs[j]], [xs[i + 1], y, zs[j + 1]], [xs[i], y, zs[j + 1]]], [0, up ? 1 : -1, 0]);
  }
  var DIRS = [[1, 0, 'W'], [-1, 0, 'E'], [0, 1, 'N'], [0, -1, 'S']]; // side = which wall of the facing room this is
  for (i = 0; i < NX; i++) for (j = 0; j < NZ; j++) {
    c = cells[i][j];
    if (c.t === 'room') { flat('floor|' + c.room, i, j, 0, true); flat('ceil|' + c.room, i, j, H, false); continue; }
    if (c.t === 'void') continue;
    if (c.t === 'wall') { flat('cap', i, j, H, true); flat('cap', i, j, 0.002, true); }
    else {
      if (c.o.sill > 0) flat('reveal', i, j, c.o.sill, true); else flat('floor|_', i, j, 0, true);
      if (c.o.head < H) flat('reveal', i, j, c.o.head, false);
    }
    var mine = solids(c);
    DIRS.forEach(function (d) {
      var n = cellAt(i + d[0], j + d[1]);
      if (n.t === 'wall') return;
      var key = n.t === 'room' ? 'wall|' + n.room + '|' + d[2] : n.t === 'open' ? 'reveal' : 'ext';
      minus(mine, solids(n)).forEach(function (s) {
        if (d[0]) { var x = d[0] > 0 ? xs[i + 1] : xs[i]; quad(key, [[x, s[0], zs[j]], [x, s[0], zs[j + 1]], [x, s[1], zs[j + 1]], [x, s[1], zs[j]]], [d[0], 0, 0]); }
        else { var z = d[1] > 0 ? zs[j + 1] : zs[j]; quad(key, [[xs[i], s[0], z], [xs[i + 1], s[0], z], [xs[i + 1], s[1], z], [xs[i], s[1], z]], [0, 0, d[1]]); }
      });
    });
  }

  // ---------- scene ----------
  var canvas = $('view'), stage = $('stage');
  var renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputEncoding = THREE.sRGBEncoding;
  var scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0xb9b2a6, 0.82));
  var sun = new THREE.DirectionalLight(0xffffff, 0.34); sun.position.set(6, 10, 3); scene.add(sun);
  var fill = new THREE.DirectionalLight(0xffffff, 0.14); fill.position.set(-5, 4, -7); scene.add(fill);
  var rig = new THREE.Group(); scene.add(rig);
  var camera = new THREE.PerspectiveCamera(60, 1, 0.05, 200); rig.add(camera);
  var orbit = new THREE.OrbitControls(camera, canvas);
  orbit.enableDamping = true; orbit.dampingFactor = 0.12; orbit.maxPolarAngle = Math.PI / 2 - 0.02; orbit.minDistance = 2; orbit.maxDistance = 60;

  var mats = {}, pickables = [], ceilings = [], furn = new THREE.Group(), labels = new THREE.Group();
  function mat(key) {
    if (!mats[key]) mats[key] = new THREE.MeshLambertMaterial({ color: 0xffffff });
    return mats[key];
  }
  Object.keys(geo).forEach(function (key) {
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(geo[key].pos, 3));
    g.setAttribute('normal', new THREE.Float32BufferAttribute(geo[key].nor, 3));
    var m = new THREE.Mesh(g, mat(key)), k = key.split('|');
    m.userData = { key: key, kind: k[0], room: k[1], side: k[2] };
    scene.add(m);
    if (k[0] === 'ceil') ceilings.push(m);
    if ((k[0] === 'wall' || k[0] === 'floor' || k[0] === 'ceil') && k[1] !== '_') pickables.push(m);
  });

  function addBox(group, key, x0, x1, z0, z1, y0, y1, pick) {
    var m = new THREE.Mesh(new THREE.BoxGeometry(x1 - x0, y1 - y0, z1 - z0), mat('furn|' + key));
    m.position.set((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
    m.userData = { key: 'furn|' + key, kind: 'furn', furn: key };
    group.add(m);
    if (pick) pickables.push(m);
  }
  P.furniture.forEach(function (f) { addBox(furn, f[0], f[3] / 1000, f[4] / 1000, f[1] / 1000, f[2] / 1000, f[5] / 1000, f[6] / 1000, true); });
  scene.add(furn);

  // door leaves (drawn open at 90°) and glazing
  var glass = new THREE.MeshLambertMaterial({ color: 0xbfd9e6, transparent: true, opacity: 0.28, side: THREE.DoubleSide, depthWrite: false });
  opens.forEach(function (r) {
    var o = r.o, alongX = (r.x1 - r.x0) > (r.z1 - r.z0);
    if (o.type === 'door') {
      var w = alongX ? r.x1 - r.x0 : r.z1 - r.z0, lo = o.leaf[0] === 'lo', dir = o.leaf[1], t = 0.04;
      if (alongX) { var hx = lo ? r.x0 : r.x1 - t, a = dir > 0 ? r.z1 : r.z0 - w; addBox(scene, 'trim', hx, hx + t, a, a + w, 0, o.head); }
      else { var hz = lo ? r.z0 : r.z1 - t, b = dir > 0 ? r.x1 : r.x0 - w; addBox(scene, 'trim', b, b + w, hz, hz + t, 0, o.head); }
    } else if (o.type === 'window' || o.type === 'slider') {
      var x0 = r.x0, x1 = r.x1, z0 = r.z0, z1 = r.z1;
      if (alongX) { z0 = z1 = (r.z0 + r.z1) / 2; if (o.type === 'slider') x1 = (x0 + x1) / 2; }
      else { x0 = x1 = (r.x0 + r.x1) / 2; if (o.type === 'slider') z1 = (z0 + z1) / 2; }
      var g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute([x0, o.sill, z0, x1, o.sill, z1, x1, o.head, z1, x0, o.sill, z0, x1, o.head, z1, x0, o.head, z0], 3));
      g.computeVertexNormals();
      scene.add(new THREE.Mesh(g, glass));
    }
  });

  // room labels
  P.rooms.forEach(function (r) {
    var cv = document.createElement('canvas'); cv.width = 512; cv.height = 160;
    var c2 = cv.getContext('2d');
    c2.fillStyle = 'rgba(20,24,28,0.82)'; c2.fillRect(0, 0, 512, 160);
    c2.fillStyle = '#fff'; c2.textAlign = 'center';
    c2.font = '600 54px "IBM Plex Sans", system-ui, sans-serif'; c2.fillText(r.name, 256, 68);
    c2.font = '40px "IBM Plex Mono", ui-monospace, monospace'; c2.fillStyle = '#c9d3da'; c2.fillText(r.size, 256, 126);
    var tex = new THREE.CanvasTexture(cv); tex.encoding = THREE.sRGBEncoding;
    var s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false }));
    var a = R(r.rects[0]), w = Math.min(1.7, (a.x1 - a.x0) * 0.85);
    s.scale.set(w, w * 160 / 512, 1); s.position.set((a.x0 + a.x1) / 2, 1.0, (a.z0 + a.z1) / 2); s.renderOrder = 10;
    labels.add(s);
  });
  scene.add(labels);

  function applyTheme() {
    Object.keys(mats).forEach(function (key) { mats[key].color.set(colorFor(key)).convertSRGBToLinear(); });
  }

  // ---------- views ----------
  var mode = 'doll', yaw = 0, pitch = 0, cutPlane = [new THREE.Plane(new THREE.Vector3(0, -1, 0), CUT)];
  var ctr = new THREE.Vector3((xs[1] + xs[NX - 1]) / 2, 0, (zs[1] + zs[NZ - 1]) / 2);
  function refresh() {
    var walk = mode === 'walk', cut = !walk && (mode === 'plan' || $('t-cut').checked);
    ceilings.forEach(function (m) { m.visible = walk; });
    labels.visible = !walk && $('t-lab').checked;
    furn.visible = $('t-furn').checked;
    renderer.clippingPlanes = cut ? cutPlane : [];
    orbit.enabled = !walk; orbit.enableRotate = mode === 'doll';
    $('stick').hidden = !(walk && window.matchMedia('(pointer: coarse)').matches);
    $('t-cut').disabled = mode !== 'doll';
    Array.prototype.forEach.call($('views').children, function (b) { b.setAttribute('aria-pressed', b.dataset.v === mode); });
    $('hint').textContent = walk ? 'Drag to look · W A S D or arrows to walk · double-click a floor to jump there'
      : mode === 'plan' ? 'Drag to pan · scroll or pinch to zoom · click a surface to recolour it'
      : 'Drag to orbit · scroll or pinch to zoom · double-click a floor to stand there';
    $('where').hidden = !walk;
  }
  function setMode(m, at) {
    mode = m;
    if (m === 'walk') {
      var p = at || rig.userData.last || { x: 0.74, z: -1.3, yaw: Math.PI };
      rig.position.set(p.x, 0, p.z); camera.position.set(0, EYE, 0);
      if (p.yaw !== undefined) { yaw = p.yaw; pitch = 0; }
      camera.fov = 72;
    } else {
      if (rig.position.lengthSq()) rig.userData.last = { x: rig.position.x, z: rig.position.z };
      rig.position.set(0, 0, 0); camera.fov = m === 'plan' ? 30 : 50;
      orbit.target.copy(ctr);
      if (m === 'plan') camera.position.set(ctr.x, 38, ctr.z + 0.01); else camera.position.set(ctr.x - 9, 15, ctr.z + 14);
      camera.up.set(0, 1, 0); orbit.update();
    }
    camera.updateProjectionMatrix(); refresh();
  }

  // ---------- walking ----------
  function blocked(x, z) {
    var i = 0, j = 0;
    while (i < NX && xs[i + 1] < x) i++;
    while (j < NZ && zs[j + 1] < z) j++;
    var c = cellAt(i, j);
    return c.t === 'wall' || c.t === 'void' || (c.t === 'open' && c.o.sill > 0.2);
  }
  function free(x, z) { var r = 0.22; return !(blocked(x - r, z - r) || blocked(x + r, z - r) || blocked(x - r, z + r) || blocked(x + r, z + r)); }
  function roomAt(x, z) { for (var k = 0; k < roomRects.length; k++) if (inside(roomRects[k], x, z, 0)) return roomById[roomRects[k].room]; return null; }
  var keys = {}, stickV = { x: 0, y: 0 };
  window.addEventListener('keydown', function (e) { if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return; keys[e.code] = true; if (mode === 'walk' && /^Arrow/.test(e.code)) e.preventDefault(); });
  window.addEventListener('keyup', function (e) { keys[e.code] = false; });
  function step(dt) {
    var f = (keys.KeyW || keys.ArrowUp ? 1 : 0) - (keys.KeyS || keys.ArrowDown ? 1 : 0) - stickV.y;
    var s = (keys.KeyD ? 1 : 0) - (keys.KeyA ? 1 : 0) + stickV.x;
    if (keys.ArrowLeft) yaw += 1.8 * dt; if (keys.ArrowRight) yaw -= 1.8 * dt;
    var xr = renderer.xr.isPresenting, heading = yaw;
    if (xr) {
      var ses = renderer.xr.getSession();
      ses.inputSources.forEach(function (src) { var a = src.gamepad && src.gamepad.axes; if (a && a.length >= 4) { s += a[2]; f -= a[3]; } });
      var dv = new THREE.Vector3(); renderer.xr.getCamera(camera).getWorldDirection(dv); heading = Math.atan2(-dv.x, -dv.z);
    } else camera.rotation.set(pitch, yaw, 0, 'YXZ');
    var len = Math.hypot(f, s); if (!len) return;
    var sp = (keys.ShiftLeft || keys.ShiftRight ? 2.8 : 1.4) * dt / Math.max(1, len); // 1.4 m/s = real walking pace
    var dx = (-Math.sin(heading) * f + Math.cos(heading) * s) * sp, dz = (-Math.cos(heading) * f - Math.sin(heading) * s) * sp;
    var p = rig.position;
    if (free(p.x + dx, p.z)) p.x += dx;
    if (free(p.x, p.z + dz)) p.z += dz;
  }

  // ---------- pointer: look, pick, teleport ----------
  var ray = new THREE.Raycaster(), down = null;
  function hit(e) {
    var b = canvas.getBoundingClientRect();
    ray.setFromCamera({ x: (e.clientX - b.left) / b.width * 2 - 1, y: -(e.clientY - b.top) / b.height * 2 + 1 }, camera);
    var cut = renderer.clippingPlanes.length, hs = ray.intersectObjects(pickables);
    for (var k = 0; k < hs.length; k++) {
      var o = hs[k].object;
      if (!o.visible || (o.userData.kind === 'furn' && !furn.visible) || (cut && hs[k].point.y > CUT + 0.001)) continue;
      return hs[k];
    }
    return null;
  }
  canvas.addEventListener('pointerdown', function (e) { down = { x: e.clientX, y: e.clientY, moved: 0 }; if (mode === 'walk') canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener('pointermove', function (e) {
    if (!down) return;
    var dx = e.clientX - down.x, dy = e.clientY - down.y;
    down.moved += Math.abs(dx) + Math.abs(dy); down.x = e.clientX; down.y = e.clientY;
    if (mode === 'walk') { yaw += dx * 0.004; pitch = Math.max(-1.3, Math.min(1.3, pitch + dy * 0.004)); }
  });
  canvas.addEventListener('pointerup', function (e) {
    var d = down; down = null;
    if (!d || d.moved > 6) return;
    var h = hit(e); if (h) select(h.object.userData);
  });
  canvas.addEventListener('pointercancel', function () { down = null; });
  canvas.addEventListener('dblclick', function (e) {
    var h = hit(e);
    if (h && h.object.userData.kind === 'floor' && free(h.point.x, h.point.z)) setMode('walk', { x: h.point.x, z: h.point.z, yaw: mode === 'walk' ? undefined : Math.atan2(camera.position.x - h.point.x, camera.position.z - h.point.z) + Math.PI });
  });
  (function () { // touch joystick
    var el = $('stick'), nub = el.firstChild, id = null;
    function mv(e) {
      var b = el.getBoundingClientRect(), x = (e.clientX - b.left) / b.width * 2 - 1, y = (e.clientY - b.top) / b.height * 2 - 1, l = Math.max(1, Math.hypot(x, y));
      stickV.x = x / l; stickV.y = y / l; nub.style.transform = 'translate(' + stickV.x * 30 + 'px,' + stickV.y * 30 + 'px)';
    }
    el.addEventListener('pointerdown', function (e) { id = e.pointerId; el.setPointerCapture(id); mv(e); });
    el.addEventListener('pointermove', function (e) { if (e.pointerId === id) mv(e); });
    function end() { id = null; stickV.x = stickV.y = 0; nub.style.transform = ''; }
    el.addEventListener('pointerup', end); el.addEventListener('pointercancel', end);
  })();

  // ---------- palette editing ----------
  var sel = null;
  function field(host, id, label, value, onInput) {
    var l = document.createElement('label'); l.className = 'sw';
    var inp = document.createElement('input'); inp.type = 'color'; inp.id = id; inp.value = value;
    var sp = document.createElement('span'); sp.textContent = label;
    var code = document.createElement('code'); code.textContent = value;
    inp.addEventListener('input', function () { code.textContent = inp.value; onInput(inp.value); applyTheme(); save(); syncJson(); });
    l.appendChild(inp); l.appendChild(sp); l.appendChild(code); host.appendChild(l);
  }
  var BASE_LABELS = { wall: 'Walls', wallWet: 'Kitchen & bath walls', ceiling: 'Ceilings', floor: 'Floors', floorWet: 'Kitchen & bath floors', floorOutdoor: 'Deck & utility floors', trim: 'Doors & reveals', exterior: 'Exterior' };
  var FURN_LABELS = { wood: 'Wood', fabric: 'Upholstery', accent: 'Accent fabric', stone: 'Countertops', cabinet: 'Cabinets & wardrobes', bedding: 'Bedding', sanitary: 'Sanitaryware', metal: 'Metal', dark: 'Screens & hob' };
  function buildGlobals() {
    var b = $('base-fields'), f = $('furn-fields'); b.innerHTML = ''; f.innerHTML = '';
    Object.keys(BASE_LABELS).forEach(function (k) { field(b, 'b-' + k, BASE_LABELS[k], theme.base[k] || theme.base.wall, function (v) { theme.base[k] = v; }); });
    Object.keys(FURN_LABELS).forEach(function (k) { field(f, 'f-' + k, FURN_LABELS[k], theme.furniture[k] || '#999999', function (v) { theme.furniture[k] = v; }); });
  }
  function select(u) {
    sel = u; var host = $('sel-fields'); host.innerHTML = '';
    if (!u) { $('sel-name').textContent = 'Click any wall, floor, ceiling or furniture piece.'; $('sel-clear').hidden = true; return; }
    var m = mats[u.key]; m.emissive.setHex(0x3a4a12); setTimeout(function () { m.emissive.setHex(0); }, 450);
    if (u.kind === 'furn') {
      $('sel-name').textContent = 'Furniture · ' + (FURN_LABELS[u.furn] || u.furn);
      field(host, 's-furn', 'All ' + (FURN_LABELS[u.furn] || u.furn).toLowerCase(), colorFor(u.key), function (v) { theme.furniture[u.furn] = v; buildGlobals(); });
      $('sel-clear').hidden = true; return;
    }
    var room = roomById[u.room], r = function () { return theme.rooms[u.room] || (theme.rooms[u.room] = {}); };
    $('sel-name').textContent = room.name + (u.kind === 'wall' ? ' · ' + SIDES[u.side] + ' wall (' + u.side + ')' : u.kind === 'floor' ? ' · floor' : ' · ceiling');
    if (u.kind === 'wall') field(host, 's-this', 'This wall only', colorFor(u.key), function (v) { var q = r(); (q.walls || (q.walls = {}))[u.side] = v; });
    field(host, 's-wall', 'All walls in ' + room.name, colorFor('wall|' + u.room + '|_'), function (v) { r().wall = v; });
    field(host, 's-floor', room.name + ' floor', colorFor('floor|' + u.room), function (v) { r().floor = v; });
    field(host, 's-ceil', room.name + ' ceiling', colorFor('ceil|' + u.room), function (v) { r().ceiling = v; });
    $('sel-clear').hidden = false;
  }
  $('sel-clear').addEventListener('click', function () { if (!sel || !sel.room) return; delete theme.rooms[sel.room]; applyTheme(); save(); syncJson(); select(sel); });
  function syncJson() { $('json').value = JSON.stringify(theme, null, 1); }
  function loadTheme(t) { theme = clone(t); theme.rooms = theme.rooms || {}; applyTheme(); buildGlobals(); select(null); syncJson(); save(); }
  THEMES.forEach(function (t) { var o = document.createElement('option'); o.value = t.id; o.textContent = t.name; $('theme').appendChild(o); });
  $('theme').value = theme.id || '';
  $('theme').addEventListener('change', function () { loadTheme(THEMES.filter(function (t) { return t.id === $('theme').value; })[0]); });
  $('json-apply').addEventListener('click', function () {
    try {
      var t = JSON.parse($('json').value);
      if (!t.base || !t.furniture) throw new Error('needs "base" and "furniture" objects');
      loadTheme(t); $('json-msg').textContent = 'Palette applied.';
    } catch (e) { $('json-msg').textContent = 'Could not apply: ' + e.message; }
  });
  $('json-copy').addEventListener('click', function () {
    var done = function () { $('json-msg').textContent = 'Copied.'; };
    try { navigator.clipboard.writeText($('json').value).then(done, function () { $('json').select(); $('json-msg').textContent = 'Selected — press Ctrl/Cmd+C.'; }); }
    catch (e) { $('json').select(); $('json-msg').textContent = 'Selected — press Ctrl/Cmd+C.'; }
  });

  // ---------- controls ----------
  $('views').addEventListener('click', function (e) { if (e.target.dataset.v) setMode(e.target.dataset.v); });
  ['t-furn', 't-cut', 't-lab'].forEach(function (id) { $(id).addEventListener('change', refresh); });
  var go = $('goto'); go.innerHTML = '<option value="">Choose a room…</option>';
  P.rooms.forEach(function (r) { var o = document.createElement('option'); o.value = r.id; o.textContent = r.name; go.appendChild(o); });
  go.addEventListener('change', function () {
    var r = roomById[go.value]; if (!r) return;
    var a = R(r.rects[0]), x = (a.x0 + a.x1) / 2, z = (a.z0 + a.z1) / 2, best = null;
    for (var t = 0; t < 200 && !best; t++) { var px = a.x0 + 0.3 + Math.random() * (a.x1 - a.x0 - 0.6), pz = a.z0 + 0.3 + Math.random() * (a.z1 - a.z0 - 0.6); if (t === 0) { px = x; pz = z; } if (free(px, pz)) best = { x: px, z: pz }; }
    best = best || { x: x, z: z }; best.yaw = Math.atan2(best.x - x, best.z - z) || 0;
    setMode('walk', best); go.value = '';
  });
  if (navigator.xr && navigator.xr.isSessionSupported) navigator.xr.isSessionSupported('immersive-vr').then(function (ok) {
    if (!ok) return; renderer.xr.enabled = true; $('vr').hidden = false;
    $('vr').addEventListener('click', function () {
      navigator.xr.requestSession('immersive-vr', { optionalFeatures: ['local-floor'] }).then(function (s) {
        setMode('walk'); camera.position.set(0, 0, 0); camera.rotation.set(0, 0, 0);
        renderer.xr.setReferenceSpaceType('local-floor'); renderer.xr.setSession(s);
        s.addEventListener('end', function () { setMode('walk'); });
      }).catch(function () { $('vr').textContent = 'VR could not start'; });
    });
  }).catch(function () {});

  function resize() {
    var w = stage.clientWidth, h = stage.clientHeight; if (!w || !h) return;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  window.addEventListener('resize', resize);
  if (window.ResizeObserver) new ResizeObserver(resize).observe(stage);

  var last = performance.now();
  renderer.setAnimationLoop(function (now) {
    var dt = Math.min(0.1, (now - last) / 1000); last = now;
    if (mode === 'walk') {
      step(dt);
      var r = roomAt(rig.position.x, rig.position.z);
      $('where').textContent = r ? r.name + ' · ' + r.size + ' mm · eye height ' + EYE + ' m' : 'Doorway';
    } else orbit.update();
    renderer.render(scene, camera);
  });

  applyTheme(); buildGlobals(); syncJson(); resize(); setMode('doll');
  window.__apt = { setMode: setMode, rig: rig, cells: cells }; // handy in the console
})();
