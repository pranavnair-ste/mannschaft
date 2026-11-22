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
    '<label class="row" for="light">Lighting<select id="light"><option value="day">Daylight</option><option value="evening">Evening, lights on</option></select></label>' +
    '<label class="check"><input type="checkbox" id="t-furn" checked> Furniture placeholders</label>' +
    '<label class="check"><input type="checkbox" id="t-cut"> Cut walls at 1.2 m</label>' +
    '<label class="check"><input type="checkbox" id="t-lab" checked> Room labels</label>' +
    '<button id="vr" hidden>Enter VR (life size)</button></section>' +
    '<section><h2>Palette</h2><label class="row" for="theme">Start from<select id="theme"></select></label>' +
    '<p class="note">The four palettes are stand-ins until the real theme palettes arrive.</p></section>' +
    '<section><h2>Selected surface</h2><p id="sel-name" class="sel">Click any wall, floor, ceiling or furniture piece.</p>' +
    '<div id="sel-fields" class="swatches"></div><button id="sel-clear" hidden>Clear this room’s overrides</button></section>' +
    '<section><h2>Whole home</h2><label class="row" for="finish">Flooring<select id="finish"><option value="wood">Wood planks</option><option value="tile">Large tiles</option><option value="plain">Plain</option></select></label><div id="base-fields" class="swatches"></div>' +
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
      case 'reveal': case 'skirt': return b.trim;
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

  var geo = {}, X0 = xs[0], Z0 = zs[0], XW = xs[NX] - xs[0], ZD = zs[NZ] - zs[0];
  // p: 4 corners [x, y, z, shade]. uv = metres (for tiling textures), uv2 = plan position (for the baked floor shading).
  function quad(key, p, n) {
    var g = geo[key] || (geo[key] = { pos: [], nor: [], uv: [], uv2: [], col: [] });
    var ux = p[1][0] - p[0][0], uy = p[1][1] - p[0][1], uz = p[1][2] - p[0][2];
    var vx = p[2][0] - p[0][0], vy = p[2][1] - p[0][1], vz = p[2][2] - p[0][2];
    var d = (uy * vz - uz * vy) * n[0] + (uz * vx - ux * vz) * n[1] + (ux * vy - uy * vx) * n[2];
    var o = d >= 0 ? [0, 1, 2, 0, 2, 3] : [0, 2, 1, 0, 3, 2];
    o.forEach(function (ix) {
      var q = p[ix], s = q[3] === undefined ? 1 : q[3];
      g.pos.push(q[0], q[1], q[2]); g.nor.push(n[0], n[1], n[2]); g.col.push(s, s, s);
      if (n[1]) g.uv.push(q[0], q[2]); else g.uv.push(n[0] ? q[2] : q[0], q[1]);
      g.uv2.push((q[0] - X0) / XW, 1 - (q[2] - Z0) / ZD);
    });
  }
  function flat(key, i, j, y, up) {
    quad(key, [[xs[i], y, zs[j]], [xs[i + 1], y, zs[j]], [xs[i + 1], y, zs[j + 1]], [xs[i], y, zs[j + 1]]], [0, up ? 1 : -1, 0]);
  }
  // Corner darkening baked into wall vertices: walls dim toward the floor, the ceiling and inside corners.
  function shadeY(y) { return 1 - 0.24 * Math.max(0, 1 - y / 0.25) - 0.2 * Math.max(0, 1 - (H - y) / 0.3); }
  function cuts(a, b, list) {
    var r = [a, b];
    list.forEach(function (v) { if (v > a + 1e-4 && v < b - 1e-4) r.push(v); });
    return r.sort(function (p, q) { return p - q; });
  }
  function cornerDist(i, j, d, sgn) { // distance along the wall from this cell's edge to the nearest inside corner
    var dist = 0, a = i, b = j;
    for (var k = 0; k < 40 && dist < 0.3; k++) {
      if (d[0]) b += sgn; else a += sgn;
      var roomSide = cellAt(a + d[0], b + d[1]), wallSide = cellAt(a, b);
      if (roomSide.t === 'wall') return dist;
      if (roomSide.t !== 'room' || wallSide.t === 'room' || wallSide.t === 'void') return Infinity;
      dist += d[0] ? zs[b + 1] - zs[b] : xs[a + 1] - xs[a];
    }
    return Infinity;
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
      var isRoom = n.t === 'room', key = isRoom ? 'wall|' + n.room + '|' + d[2] : n.t === 'open' ? 'reveal' : 'ext';
      var lo = d[0] ? zs[j] : xs[i], len = (d[0] ? zs[j + 1] : xs[i + 1]) - lo;
      var f = d[0] ? (d[0] > 0 ? xs[i + 1] : xs[i]) : (d[1] > 0 ? zs[j + 1] : zs[j]);
      var dl = isRoom ? cornerDist(i, j, d, -1) : Infinity, dh = isRoom ? cornerDist(i, j, d, 1) : Infinity;
      function P(t, y, off) {
        var s = isRoom && !off ? (1 - 0.28 * Math.max(0, 1 - Math.min(dl + t, dh + len - t) / 0.3)) * shadeY(y) : 1;
        return d[0] ? [f + d[0] * (off || 0), y, lo + t, s] : [lo + t, y, f + d[1] * (off || 0), s];
      }
      var nrm = [d[0], 0, d[1]], as = cuts(0, len, [0.3 - dl, len - 0.3 + dh, (len + dh - dl) / 2]);
      minus(mine, solids(n)).forEach(function (s) {
        var ys = cuts(s[0], s[1], [0.25, H - 0.3]);
        for (var a = 0; a < as.length - 1; a++) for (var b = 0; b < ys.length - 1; b++)
          quad(key, [P(as[a], ys[b]), P(as[a + 1], ys[b]), P(as[a + 1], ys[b + 1]), P(as[a], ys[b + 1])], nrm);
        if (isRoom && s[0] === 0 && roomById[n.room].kind === 'dry') { // skirting board
          var o = 0.012, h = 0.08;
          quad('skirt', [P(0, 0, o), P(len, 0, o), P(len, h, o), P(0, h, o)], nrm);
          quad('skirt', [P(0, h, 1e-9), P(len, h, 1e-9), P(len, h, o), P(0, h, o)], [0, 1, 0]);
        }
      });
    });
  }

  // ---------- renderer, sky and light ----------
  var canvas = $('view'), stage = $('stage');
  var coarse = window.matchMedia('(pointer: coarse)').matches;
  var renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputEncoding = THREE.sRGBEncoding;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap; renderer.shadowMap.autoUpdate = false;
  var scene = new THREE.Scene();
  var ctr = new THREE.Vector3((xs[1] + xs[NX - 1]) / 2, 0, (zs[1] + zs[NZ - 1]) / 2);
  var rig = new THREE.Group(); scene.add(rig);
  var camera = new THREE.PerspectiveCamera(60, 1, 0.05, 400); rig.add(camera);
  var orbit = new THREE.OrbitControls(camera, canvas);
  orbit.enableDamping = true; orbit.dampingFactor = 0.12; orbit.maxPolarAngle = Math.PI / 2 - 0.02; orbit.minDistance = 2; orbit.maxDistance = 60;

  var skyCv = document.createElement('canvas'); skyCv.width = 4; skyCv.height = 512;
  var skyTex = new THREE.CanvasTexture(skyCv); skyTex.encoding = THREE.sRGBEncoding;
  var skyMat = new THREE.MeshBasicMaterial({ map: skyTex, side: THREE.BackSide, toneMapped: false, depthWrite: false });
  var dome = new THREE.Mesh(new THREE.SphereGeometry(180, 32, 24), skyMat); dome.position.copy(ctr); scene.add(dome);
  var envScene = new THREE.Scene(); envScene.add(new THREE.Mesh(dome.geometry, skyMat));
  var pmrem = new THREE.PMREMGenerator(renderer), envRT = null;

  var hemi = new THREE.HemisphereLight(0xdfe9ff, 0xb8a890, 0.3); scene.add(hemi);
  var sun = new THREE.DirectionalLight(0xfff0da, 2.6); // low sun from the deck / bedroom-window side
  sun.position.set(ctr.x + 14, 17, ctr.z + 24); sun.target.position.copy(ctr); scene.add(sun); scene.add(sun.target);
  sun.castShadow = true; sun.shadow.mapSize.set(coarse ? 2048 : 4096, coarse ? 2048 : 4096);
  var sc = sun.shadow.camera; sc.left = -13; sc.right = 13; sc.top = 13; sc.bottom = -13; sc.near = 1; sc.far = 80;
  sun.shadow.bias = -0.0002; sun.shadow.normalBias = 0.012;
  var fill = new THREE.DirectionalLight(0xdfe8ff, 0.3); fill.position.set(-8, 9, -12); scene.add(fill); // stands in for bounced daylight

  // ---------- procedural textures (near-white so palette colours tint them) ----------
  var seed = 7; function rnd() { seed = (seed * 16807) % 2147483647; return seed / 2147483647; }
  function tex(size, metres, draw, srgb) {
    var cv = document.createElement('canvas'); cv.width = cv.height = size; draw(cv.getContext('2d'), size);
    var t = new THREE.CanvasTexture(cv); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(1 / metres, 1 / metres);
    t.anisotropy = renderer.capabilities.getMaxAnisotropy(); if (srgb) t.encoding = THREE.sRGBEncoding;
    return t;
  }
  function drawWood(c, S) {
    var rows = 16, ph = S / rows, pl = S / 2;
    for (var r = 0; r < rows; r++) {
      var off = rnd() * pl;
      for (var x = -pl; x < S; x += pl) {
        var g = 224 + rnd() * 28 | 0;
        c.fillStyle = 'rgb(' + g + ',' + (g - 3) + ',' + (g - 8) + ')'; c.fillRect(x + off, r * ph, pl, ph);
        for (var k = 0; k < 14; k++) { c.fillStyle = 'rgba(70,50,30,' + (0.03 + rnd() * 0.06) + ')'; c.fillRect(x + off + rnd() * pl * 0.3, r * ph + rnd() * ph, pl * (0.4 + rnd() * 0.6), 1); }
        c.fillStyle = 'rgba(45,35,25,0.6)'; c.fillRect(x + off, r * ph, 1.5, ph);
      }
      c.fillStyle = 'rgba(45,35,25,0.6)'; c.fillRect(0, r * ph, S, 1.5);
    }
  }
  function drawTile(nx, ny) {
    return function (c, S) {
      var w = S / nx, h = S / ny;
      for (var a = 0; a < nx; a++) for (var b = 0; b < ny; b++) {
        var g = 236 + rnd() * 16 | 0; c.fillStyle = 'rgb(' + g + ',' + g + ',' + (g - 2) + ')'; c.fillRect(a * w, b * h, w, h);
        c.fillStyle = 'rgba(120,120,112,0.9)'; c.fillRect(a * w, b * h, w, 2); c.fillRect(a * w, b * h, 2, h);
      }
    };
  }
  function drawNoise(c, S) {
    for (var x = 0; x < S; x += 2) for (var y = 0; y < S; y += 2) { var g = 112 + rnd() * 32 | 0; c.fillStyle = 'rgb(' + g + ',' + g + ',' + g + ')'; c.fillRect(x, y, 2, 2); }
  }
  var TX = {
    wood: tex(1024, 2.4, drawWood, true), tile: tex(512, 1.2, drawTile(2, 2), true), tileBig: tex(512, 1.6, drawTile(2, 2), true),
    paver: tex(512, 0.6, drawTile(2, 2), true), wallTile: tex(512, 1.2, drawTile(4, 2), true),
    plaster: tex(256, 0.7, drawNoise), fabric: tex(256, 0.25, drawNoise)
  };
  TX.wood.rotation = Math.PI / 2;
  function aoTex(withFurn) { // top-down occlusion: dark along walls and around furniture feet, blurred
    var S = 25, w = Math.ceil(XW * S), h = Math.ceil(ZD * S);
    var cv = document.createElement('canvas'); cv.width = w; cv.height = h; var c2 = cv.getContext('2d');
    c2.fillStyle = '#fff'; c2.fillRect(0, 0, w, h); c2.fillStyle = '#000';
    for (var a = 0; a < NX; a++) for (var b = 0; b < NZ; b++) {
      var q = cells[a][b];
      if (q.t === 'wall' || (q.t === 'open' && q.o.sill > 0)) c2.fillRect((xs[a] - X0) * S - 0.5, (zs[b] - Z0) * S - 0.5, (xs[a + 1] - xs[a]) * S + 1, (zs[b + 1] - zs[b]) * S + 1);
    }
    if (withFurn) { c2.fillStyle = '#3c3c3c'; P.furniture.forEach(function (f) { if (f[5] < 250) c2.fillRect((f[3] / 1000 - X0) * S, (f[1] / 1000 - Z0) * S, (f[4] - f[3]) / 1000 * S, (f[2] - f[1]) / 1000 * S); }); }
    var out = document.createElement('canvas'); out.width = w; out.height = h; var o2 = out.getContext('2d');
    if (o2.filter !== undefined) { o2.filter = 'blur(5px)'; o2.drawImage(cv, 0, 0); }
    else { var sm = document.createElement('canvas'); sm.width = w / 6 | 0; sm.height = h / 6 | 0; sm.getContext('2d').drawImage(cv, 0, 0, sm.width, sm.height); o2.drawImage(sm, 0, 0, w, h); }
    return new THREE.CanvasTexture(out);
  }
  var aoBare = aoTex(false), aoFurn = aoTex(true);

  // ---------- materials and meshes ----------
  var mats = {}, pickables = [], ceilings = [], lamps = [], furn = new THREE.Group(), labels = new THREE.Group();
  var FURN_MAT = {
    wood: { roughness: 0.5 }, fabric: { roughness: 0.95, bumpMap: TX.fabric, bumpScale: 0.004 }, accent: { roughness: 0.95, bumpMap: TX.fabric, bumpScale: 0.004 },
    bedding: { roughness: 0.9, bumpMap: TX.fabric, bumpScale: 0.002 }, stone: { roughness: 0.18 }, cabinet: { roughness: 0.35 },
    sanitary: { roughness: 0.12 }, metal: { roughness: 0.3, metalness: 0.9 }, dark: { roughness: 0.15 }, trim: { roughness: 0.45 }
  };
  function mat(key) {
    if (mats[key]) return mats[key];
    var k = key.split('|'), room = roomById[k[1]], o = { color: 0xffffff, roughness: 0.92, metalness: 0 };
    if (k[0] === 'wall') {
      o.vertexColors = true;
      if (room.kind === 'wet') { o.map = TX.wallTile; o.bumpMap = TX.wallTile; o.bumpScale = 0.003; o.roughness = 0.28; }
      else { o.bumpMap = TX.plaster; o.bumpScale = 0.0012; }
    } else if (k[0] === 'floor') { o.aoMap = aoFurn; o.aoMapIntensity = 0.95; }
    else if (k[0] === 'ceil') { o.aoMap = aoBare; o.aoMapIntensity = 0.8; }
    else if (k[0] === 'ext') { o.bumpMap = TX.plaster; o.bumpScale = 0.0012; }
    else if (k[0] === 'reveal' || k[0] === 'skirt') o.roughness = 0.5;
    else if (k[0] === 'furn') { var fm = FURN_MAT[k[1]] || {}; for (var q in fm) o[q] = fm[q]; }
    return (mats[key] = new THREE.MeshStandardMaterial(o));
  }
  function applyFinish() { // floor finish follows room type; dry rooms follow the palette's floorFinish
    Object.keys(mats).forEach(function (key) {
      var k = key.split('|'); if (k[0] !== 'floor') return;
      var m = mats[key], kind = roomById[k[1]] ? roomById[k[1]].kind : 'dry', fin = theme.base.floorFinish || 'wood', t, r, b = 0.003;
      if (kind === 'wet') { t = TX.tile; r = 0.22; } else if (kind === 'outdoor') { t = TX.paver; r = 0.75; }
      else if (fin === 'tile') { t = TX.tileBig; r = 0.16; } else if (fin === 'plain') { t = null; r = 0.55; } else { t = TX.wood; r = 0.4; b = 0.0015; }
      m.map = t; m.bumpMap = t; m.bumpScale = b; m.roughness = r; m.needsUpdate = true;
    });
  }
  Object.keys(geo).forEach(function (key) {
    var g = new THREE.BufferGeometry(), src = geo[key];
    g.setAttribute('position', new THREE.Float32BufferAttribute(src.pos, 3));
    g.setAttribute('normal', new THREE.Float32BufferAttribute(src.nor, 3));
    g.setAttribute('uv', new THREE.Float32BufferAttribute(src.uv, 2));
    g.setAttribute('uv2', new THREE.Float32BufferAttribute(src.uv2, 2));
    g.setAttribute('color', new THREE.Float32BufferAttribute(src.col, 3));
    var m = new THREE.Mesh(g, mat(key)), k = key.split('|');
    m.userData = { key: key, kind: k[0], room: k[1], side: k[2] };
    m.castShadow = m.receiveShadow = true;
    scene.add(m);
    if (k[0] === 'ceil') ceilings.push(m);
    if ((k[0] === 'wall' || k[0] === 'floor' || k[0] === 'ceil') && k[1] !== '_') pickables.push(m);
  });

  function addBox(group, key, x0, x1, z0, z1, y0, y1, pick) {
    var m = new THREE.Mesh(new THREE.BoxGeometry(x1 - x0, y1 - y0, z1 - z0), mat('furn|' + key));
    m.position.set((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
    m.userData = { key: 'furn|' + key, kind: 'furn', furn: key };
    m.castShadow = m.receiveShadow = true;
    group.add(m);
    if (pick) pickables.push(m);
  }
  P.furniture.forEach(function (f) { addBox(furn, f[0], f[3] / 1000, f[4] / 1000, f[1] / 1000, f[2] / 1000, f[5] / 1000, f[6] / 1000, true); });
  scene.add(furn);

  // door leaves (drawn open at 90°), glazing and window frames
  var glass = new THREE.MeshStandardMaterial({ color: 0xcfe3ea, transparent: true, opacity: 0.16, roughness: 0.03, metalness: 0, side: THREE.DoubleSide, depthWrite: false });
  opens.forEach(function (r) {
    var o = r.o, alongX = (r.x1 - r.x0) > (r.z1 - r.z0);
    if (o.type === 'door') {
      var w = alongX ? r.x1 - r.x0 : r.z1 - r.z0, lo = o.leaf[0] === 'lo', dir = o.leaf[1], t = 0.04;
      if (alongX) { var hx = lo ? r.x0 : r.x1 - t, a = dir > 0 ? r.z1 : r.z0 - w; addBox(scene, 'trim', hx, hx + t, a, a + w, 0, o.head); }
      else { var hz = lo ? r.z0 : r.z1 - t, b = dir > 0 ? r.x1 : r.x0 - w; addBox(scene, 'trim', b, b + w, hz, hz + t, 0, o.head); }
    } else if (o.type === 'window' || o.type === 'slider') {
      var x0 = r.x0, x1 = r.x1, z0 = r.z0, z1 = r.z1, sl = o.type === 'slider', fr = 0.045, mx = (r.x0 + r.x1) / 2, mz = (r.z0 + r.z1) / 2;
      function bar(a0, a1, y0, y1) { if (alongX) addBox(scene, 'metal', a0, a1, mz - 0.03, mz + 0.03, y0, y1); else addBox(scene, 'metal', mx - 0.03, mx + 0.03, a0, a1, y0, y1); }
      var A0 = alongX ? x0 : z0, A1 = alongX ? x1 : z1, AM = (A0 + A1) / 2;
      bar(A0, A1, o.head - fr, o.head); if (!sl) bar(A0, A1, o.sill, o.sill + fr);
      bar(A0, A0 + fr, o.sill, o.head); bar(A1 - fr, A1, o.sill, o.head); bar(AM - fr / 2, AM + fr / 2, o.sill, o.head);
      if (alongX) { z0 = z1 = mz; if (sl) x1 = mx; } else { x0 = x1 = mx; if (sl) z1 = mz; }
      var g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute([x0, o.sill, z0, x1, o.sill, z1, x1, o.head, z1, x0, o.sill, z0, x1, o.head, z1, x0, o.head, z0], 3));
      g.computeVertexNormals();
      scene.add(new THREE.Mesh(g, glass));
    }
  });

  // one ceiling light per room area
  var lampMat = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffd9a8, roughness: 0.4 }), fixtures = new THREE.Group();
  roomRects.forEach(function (r) {
    if (roomById[r.room].id === 'puja') return;
    var x = (r.x0 + r.x1) / 2, z = (r.z0 + r.z1) / 2;
    var d = new THREE.Mesh(new THREE.CylinderGeometry(0.11, 0.11, 0.015, 24), lampMat); d.position.set(x, H - 0.008, z); fixtures.add(d);
    var l = new THREE.PointLight(0xffd2a0, 1, 8.5, 2); l.position.set(x, H - 0.35, z); scene.add(l); lamps.push(l);
  });
  scene.add(fixtures);

  var LIGHTING = {
    day: { sky: [[0, '#2f6fc0'], [0.4, '#9ec4e8'], [0.495, '#eef3f4'], [0.51, '#bdb8ab'], [1, '#8d887d']], sun: 2.4, hemi: 0.95, fill: 0.3, lamp: 0, glow: 0.2, exp: 0.95 },
    evening: { sky: [[0, '#060a1a'], [0.38, '#1a2142'], [0.48, '#7a4a52'], [0.5, '#d27a3c'], [0.52, '#1c1c24'], [1, '#101014']], sun: 0, hemi: 0.1, fill: 0, lamp: 1.25, glow: 4, exp: 1.05 }
  };
  function setLighting(name) {
    var L = LIGHTING[name] || LIGHTING.day, c2 = skyCv.getContext('2d'), g = c2.createLinearGradient(0, 0, 0, 512);
    L.sky.forEach(function (s) { g.addColorStop(s[0], s[1]); });
    c2.fillStyle = g; c2.fillRect(0, 0, 4, 512); skyTex.needsUpdate = true;
    if (envRT) envRT.dispose();
    envRT = pmrem.fromScene(envScene, 0.02); scene.environment = envRT.texture;
    sun.visible = L.sun > 0; sun.intensity = L.sun; hemi.intensity = L.hemi; fill.intensity = L.fill;
    lamps.forEach(function (l) { l.visible = L.lamp > 0; l.intensity = L.lamp; });
    lampMat.emissiveIntensity = L.glow; renderer.toneMappingExposure = L.exp;
    renderer.shadowMap.needsUpdate = true;
  }

  // room labels
  P.rooms.forEach(function (r) {
    var cv = document.createElement('canvas'); cv.width = 512; cv.height = 160;
    var c2 = cv.getContext('2d');
    c2.fillStyle = 'rgba(20,24,28,0.82)'; c2.fillRect(0, 0, 512, 160);
    c2.fillStyle = '#fff'; c2.textAlign = 'center';
    c2.font = '600 54px "IBM Plex Sans", system-ui, sans-serif'; c2.fillText(r.name, 256, 68);
    c2.font = '40px "IBM Plex Mono", ui-monospace, monospace'; c2.fillStyle = '#c9d3da'; c2.fillText(r.size, 256, 126);
    var tx = new THREE.CanvasTexture(cv); tx.encoding = THREE.sRGBEncoding;
    var s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tx, depthTest: false, toneMapped: false }));
    var a = R(r.rects[0]), w = Math.min(1.7, (a.x1 - a.x0) * 0.85);
    s.scale.set(w, w * 160 / 512, 1); s.position.set((a.x0 + a.x1) / 2, 1.0, (a.z0 + a.z1) / 2); s.renderOrder = 10;
    labels.add(s);
  });
  scene.add(labels);

  function applyTheme() {
    Object.keys(mats).forEach(function (key) { mats[key].color.set(colorFor(key)).convertSRGBToLinear(); });
    applyFinish();
  }

  // ---------- views ----------
  var mode = 'doll', yaw = 0, pitch = 0, cutPlane = [new THREE.Plane(new THREE.Vector3(0, -1, 0), CUT)];
  function refresh() {
    var walk = mode === 'walk', cut = !walk && (mode === 'plan' || $('t-cut').checked);
    ceilings.forEach(function (m) { m.visible = walk; });
    labels.visible = !walk && $('t-lab').checked;
    furn.visible = $('t-furn').checked; fixtures.visible = walk;
    Object.keys(mats).forEach(function (key) { if (key.indexOf('floor|') === 0) mats[key].aoMap = furn.visible ? aoFurn : aoBare; });
    renderer.shadowMap.needsUpdate = true;
    renderer.clippingPlanes = cut ? cutPlane : [];
    orbit.enabled = !walk; orbit.enableRotate = mode === 'doll';
    $('stick').hidden = !(walk && coarse);
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
    $('finish').value = theme.base.floorFinish || 'wood';
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
  $('light').addEventListener('change', function () { setLighting($('light').value); });
  $('finish').addEventListener('change', function () { theme.base.floorFinish = $('finish').value; applyTheme(); save(); syncJson(); });
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

  setLighting('day'); applyTheme(); buildGlobals(); syncJson(); resize(); setMode('doll');
  window.__apt = { setMode: setMode, rig: rig, cells: cells }; // handy in the console
})();
