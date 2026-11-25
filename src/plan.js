/* Magnolia 3BHK Premium — geometry transcribed from the builder's plan.
 *
 * All plan coordinates are millimetres in (u, v):
 *   u runs down the photographed sheet, v runs across it. World x = v, world z = u, so the
 *   3D top view matches the builder's plan sheet as photographed (not kept in this repo).
 *   u = 0 is the foyer/living boundary, v = 0 is the inside face of the long living-room wall.
 *
 * Room sizes are the figures printed on the plan. Wall thicknesses, door and window positions
 * and all heights are NOT on the plan — they are estimates. Edit them here; everything else
 * (walls, collisions, labels) is generated from this file.
 */
var PLAN = (function () {
  var rooms = [
    // id, name, printed size (u x v), kind, rects [u0, u1, v0, v1]
    { id: 'foyer',   name: 'Foyer',        size: '2200 × 1475', kind: 'dry',     rects: [[-2200, 0, 0, 1475]] },
    { id: 'living',  name: 'Living',       size: '4975 × 3560', kind: 'dry',     rects: [[0, 4975, 0, 3560]] },
    { id: 'dining',  name: 'Dining',       size: '3200 × 3650', kind: 'dry',     rects: [[0, 3200, 3560, 7210]] },
    { id: 'puja',    name: 'Puja',         size: 'niche',       kind: 'dry',     rects: [[1600, 2200, 7210, 7910]] },
    { id: 'kitchen', name: 'Kitchen',      size: '2595 × 3050', kind: 'wet',     rects: [[-2710, -115, 1675, 4725]] },
    { id: 'utility', name: 'Utility',      size: '1450 × 3050', kind: 'outdoor', rects: [[-4275, -2825, 1675, 4725]] },
    { id: 'bath1',   name: 'Common bath',  size: '2600 × 1675', kind: 'wet',     rects: [[-2715, -115, 4925, 6600]] },
    { id: 'bath2',   name: 'Bed 1 bath',   size: '2600 × 1675', kind: 'wet',     rects: [[-2715, -115, 6715, 8390]] },
    { id: 'bed1',    name: 'Bedroom 1',    size: '3840 × 3290', kind: 'dry',     rects: [[-1725, 2115, 8590, 11880], [0, 1500, 7325, 8590]] },
    { id: 'bed2',    name: 'Bedroom 2',    size: '3650 × 3350', kind: 'dry',     rects: [[3315, 6965, 3760, 7110]] },
    { id: 'mbed',    name: 'Master bedroom', size: '4750 × 3690', kind: 'dry',   rects: [[2315, 7065, 9165, 12855], [2315, 3315, 7325, 9165]] },
    { id: 'bath3',   name: 'Master bath',  size: '2750 × 1725', kind: 'wet',     rects: [[3430, 6180, 7325, 9050]] },
    { id: 'deck',    name: 'Deck',         size: '1975 × 3550', kind: 'outdoor', rects: [[5175, 7150, 0, 3550]] }
  ];

  // Openings cut through the generated walls. rect = [u0, u1, v0, v1] and must span the wall thickness.
  // sill/head in metres. type: door (leaf drawn open), arch (no leaf), window, slider, open (parapet, no glass).
  // leaf: hinge at the 'lo' or 'hi' end of the opening, swinging toward +1 / -1 across the wall.
  var D = 2.1;
  var openings = [
    { id: 'entry',        type: 'door',   rect: [-2400, -2200, 240, 1240],   sill: 0, head: D, leaf: ['lo', 1] },
    { id: 'kitchen',      type: 'arch',   rect: [-115, 0, 3800, 4600],       sill: 0, head: D },
    { id: 'utility',      type: 'door',   rect: [-2825, -2710, 3900, 4600],  sill: 0, head: D, leaf: ['hi', -1] },
    { id: 'kitchen-win',  type: 'window', rect: [-2825, -2710, 2400, 3600],  sill: 1.05, head: D },
    { id: 'bath1',        type: 'door',   rect: [-115, 0, 5800, 6500],       sill: 0, head: D, leaf: ['hi', -1] },
    { id: 'bath2',        type: 'door',   rect: [-1000, -300, 8390, 8590],   sill: 0, head: D, leaf: ['lo', -1] },
    { id: 'bed1',         type: 'door',   rect: [300, 1200, 7210, 7325],     sill: 0, head: D, leaf: ['lo', 1] },
    { id: 'mbed',         type: 'door',   rect: [2400, 3200, 7210, 7325],    sill: 0, head: D, leaf: ['hi', 1] },
    { id: 'bath3',        type: 'door',   rect: [3315, 3430, 8250, 8950],    sill: 0, head: D, leaf: ['hi', 1] },
    { id: 'bed2',         type: 'door',   rect: [3200, 3315, 6150, 7000],    sill: 0, head: D, leaf: ['hi', 1] },
    { id: 'deck',         type: 'slider', rect: [4975, 5175, 0, 3550],     sill: 0, head: 99 },
    { id: 'bed1-win',     type: 'window', rect: [-700, 1100, 11880, 12080],  sill: 0.9, head: D },
    { id: 'bed2-win',     type: 'window', rect: [6965, 7165, 3760, 7110],    sill: 0, head: 99 },
    { id: 'mbed-win',     type: 'window', rect: [7065, 7265, 9165, 12855],   sill: 0, head: 99 },
    { id: 'bath1-vent',   type: 'window', rect: [-2915, -2715, 5450, 6050],  sill: 1.8, head: 2.25 },
    { id: 'bath2-vent',   type: 'window', rect: [-2915, -2715, 7250, 7850],  sill: 1.8, head: 2.25 },
    { id: 'bath3-vent',   type: 'window', rect: [6180, 6380, 7900, 8500],    sill: 1.8, head: 2.25 },
    { id: 'utility-rail', type: 'open',   rect: [-4475, -4275, 1675, 4725],  sill: 1.05, head: 2.4 },
    { id: 'deck-rail',    type: 'open',   rect: [7150, 7350, 0, 3550],       sill: 1.05, head: 99 }
  ];

  // Placeholder furniture: [material, u0, u1, v0, v1, y0, y1] in mm. Positions follow the plan's furniture symbols.
  var F = [];
  function box(m, u0, u1, v0, v1, y0, y1) { F.push([m, u0, u1, v0, v1, y0, y1]); }
  function bed(u0, u1, v0, v1, head) { // head: 'u' = headboard on the u0 side, 'v' = on the v0 side
    box('wood', u0, u1, v0, v1, 0, 300);
    box('bedding', u0 + 30, u1 - 30, v0 + 30, v1 - 30, 300, 540);
    if (head === 'u') {
      box('fabric', u0, u0 + 60, v0, v1, 0, 1050);
      var w = (v1 - v0) / 2;
      box('accent', u0 + 120, u0 + 520, v0 + 100, v0 + w - 50, 540, 660);
      box('accent', u0 + 120, u0 + 520, v0 + w + 50, v1 - 100, 540, 660);
    } else {
      box('fabric', u0, u1, v0, v0 + 60, 0, 1050);
      var w2 = (u1 - u0) / 2;
      box('accent', u0 + 100, u0 + w2 - 50, v0 + 120, v0 + 520, 540, 660);
      box('accent', u0 + w2 + 50, u1 - 100, v0 + 120, v0 + 520, 540, 660);
    }
  }
  function chair(u, v) { box('fabric', u - 220, u + 220, v - 220, v + 220, 0, 450); }

  // Living: TV wall on v = 0, sofa backing the dining side
  box('wood', 1900, 3700, 0, 400, 150, 550);
  box('dark', 2150, 3450, 0, 60, 900, 1650);
  box('fabric', 1750, 3750, 2600, 3500, 0, 420);
  box('fabric', 1750, 3750, 3300, 3500, 420, 850);
  box('fabric', 1750, 1950, 2600, 3300, 420, 620);
  box('fabric', 3550, 3750, 2600, 3300, 420, 620);
  box('accent', 1050, 1750, 1700, 2400, 0, 420); box('accent', 1050, 1200, 1700, 2400, 420, 800);
  box('accent', 3950, 4650, 1700, 2400, 0, 420); box('accent', 4500, 4650, 1700, 2400, 420, 800);
  box('wood', 2300, 3200, 1450, 2050, 0, 400);
  // Dining: six-seater
  box('wood', 850, 2350, 5150, 6050, 720, 760);
  [[900, 5200], [2260, 5200], [900, 5960], [2260, 5960]].forEach(function (p) { box('wood', p[0], p[0] + 40, p[1], p[1] + 40, 0, 720); });
  chair(1250, 4900); chair(1950, 4900); chair(1250, 6300); chair(1950, 6300); chair(550, 5600); chair(2650, 5600);
  // Puja unit
  box('wood', 1650, 2150, 7450, 7910, 0, 900);
  box('wood', 1650, 2150, 7700, 7910, 900, 1900);
  // Kitchen: L counter, sink side on the foyer wall, hob on the dining wall
  box('cabinet', -2710, -115, 1675, 2275, 0, 850); box('stone', -2710, -115, 1675, 2295, 850, 890);
  box('cabinet', -715, -115, 2275, 3600, 0, 850);  box('stone', -735, -115, 2295, 3600, 850, 890);
  box('cabinet', -2710, -115, 1675, 2025, 1450, 2150);
  box('dark', -600, -200, 2750, 3350, 890, 910);
  box('metal', -2300, -1500, 1780, 2180, 880, 895);
  // Utility: washing machine
  box('sanitary', -4200, -3600, 1750, 2350, 0, 850);
  // Bedrooms
  bed(-1725, 275, 9200, 10700, 'u');
  box('cabinet', 1515, 2115, 8590, 10390, 0, 2400);
  bed(4700, 6200, 3760, 5760, 'v');
  box('cabinet', 3315, 3915, 3810, 6000, 0, 2400);
  bed(4300, 6100, 9165, 11215, 'v');
  box('cabinet', 3300, 5300, 12255, 12855, 0, 2400);
  // Baths: WC on the far wall, vanity near the door
  function wc(uWall, dir, vc) {
    var a = uWall, b = uWall + dir * 180, c = uWall + dir * 700;
    box('sanitary', Math.min(a, b), Math.max(a, b), vc - 200, vc + 200, 0, 780);
    box('sanitary', Math.min(b, c), Math.max(b, c), vc - 180, vc + 180, 0, 400);
  }
  function vanity(u0, u1, v0) { box('cabinet', u0, u1, v0, v0 + 450, 0, 820); box('sanitary', u0, u1, v0, v0 + 470, 820, 870); }
  wc(-2715, 1, 5500); vanity(-1100, -500, 4925);
  wc(-2715, 1, 7550); vanity(-1100, -500, 6715);
  wc(6180, -1, 8200); vanity(3700, 4300, 7325);

  // Bedroom 1 display pieces: floating shelves beside the wardrobe and an open stand in each window-side corner.
  [900, 1300, 1700].forEach(function (y) { box('wood', 1915, 2115, 10550, 11350, y, y + 30); });
  function stand(u0, v0) {
    [[0, 0], [375, 0], [0, 375], [375, 375]].forEach(function (p) { box('metal', u0 + p[0], u0 + p[0] + 25, v0 + p[1], v0 + p[1] + 25, 0, 1830); });
    [100, 550, 1000, 1450, 1800].forEach(function (y) { box('wood', u0, u0 + 400, v0, v0 + 400, y, y + 25); });
  }
  stand(-1725, 11480); stand(1715, 11480);

  // Fixed-colour decor (not palette-driven): [colour, u0, u1, v0, v1, y0, y1, shape]. Club items use the
  // blue-and-garnet colours only — no crest or wordmark.
  var DEC = [], BLUE = '#004d98', GARNET = '#a50044', GOLD = '#edbb00', BRASS = '#c9a227';
  function dec(c, u0, u1, v0, v1, y0, y1, shape) { DEC.push([c, u0, u1, v0, v1, y0, y1, shape || 'box']); }
  var POTS = ['#c46a4a', '#f1ede4', '#3b3b3b'], GREENS = ['#6f9a6a', '#8fb89a', '#4f7f5f', '#a8c48f'], sn = 0;
  function succulent(u, v, y) {
    sn++;
    dec(POTS[sn % 3], u - 45, u + 45, v - 45, v + 45, y, y + 70, 'cyl');
    dec(GREENS[sn % 4], u - 58, u + 58, v - 58, v + 58, y + 50, y + 135, 'sph');
  }
  function ball(u, v, y) { dec('#f4f4f1', u - 105, u + 105, v - 105, v + 105, y, y + 210, 'sph'); }
  function cup(u, v, y) {
    dec('#2b2019', u - 45, u + 45, v - 45, v + 45, y, y + 25);
    dec(BRASS, u - 14, u + 14, v - 14, v + 14, y + 25, y + 90, 'cyl');
    dec(BRASS, u - 50, u + 50, v - 50, v + 50, y + 90, y + 210, 'cyl');
  }
  function stripes(u0, u1, v0, v1, y0, y1, n, alongV) { // alternating blue / garnet bands
    for (var i = 0; i < n; i++) {
      var c = i % 2 ? GARNET : BLUE;
      if (alongV) dec(c, u0, u1, v0 + (v1 - v0) * i / n, v0 + (v1 - v0) * (i + 1) / n, y0, y1);
      else dec(c, u0, u1, v0, v1, y0 + (y1 - y0) * i / n, y0 + (y1 - y0) * (i + 1) / n);
    }
  }
  // shelves beside the wardrobe (south wall)
  ball(2010, 10670, 930); succulent(2010, 10900, 930); stripes(1935, 2095, 11020, 11300, 930, 1020, 3); dec(GOLD, 1935, 2095, 11020, 11300, 1020, 1045);
  cup(2010, 10680, 1330); succulent(2000, 10880, 1330); succulent(2030, 11030, 1330); stripes(2085, 2105, 11130, 11330, 1330, 1600, 4, true);
  stripes(1950, 2090, 10600, 10900, 1730, 1790, 6, true); succulent(2010, 11040, 1730); succulent(2000, 11230, 1730);
  // scarf pinned above the shelves
  dec(GOLD, 2100, 2115, 10530, 10560, 2080, 2260); stripes(2100, 2115, 10560, 11340, 2080, 2260, 8, true); dec(GOLD, 2100, 2115, 11340, 11370, 2080, 2260);
  // corner stands
  succulent(-1525, 11680, 125); ball(-1525, 11680, 575); succulent(-1600, 11600, 1025); succulent(-1440, 11760, 1025); cup(-1525, 11680, 1475); succulent(-1525, 11680, 1825);
  succulent(1915, 11680, 125); stripes(1790, 2040, 11560, 11800, 575, 700, 4, true); succulent(1915, 11680, 1025); ball(1915, 11680, 1475); succulent(1850, 11620, 1825); succulent(1990, 11750, 1825);
  // framed striped shirt over the headboard
  dec('#2b2019', -1725, -1695, 9650, 10250, 1250, 2050); dec('#f3f0e8', -1695, -1688, 9690, 10210, 1290, 2010);
  stripes(-1688, -1680, 9775, 10125, 1400, 1880, 5, true);
  dec(GARNET, -1688, -1680, 9695, 9775, 1740, 1880); dec(GARNET, -1688, -1680, 10125, 10205, 1740, 1880);

  // Panel mouldings, shown only by themes with base.moulding. Wall plane `at`, panels between from..to (mm), room on the +dir side.
  var mouldings = [
    { room: 'bed1', side: 'N', at: -1725, from: 8590, to: 11880, dir: 1, panels: 3 },
    { room: 'bed2', side: 'W', at: 3760, from: 3315, to: 6965, dir: 1, panels: 3 },
    { room: 'mbed', side: 'W', at: 9165, from: 3315, to: 7065, dir: 1, panels: 3 },
    { room: 'living', side: 'W', at: 0, from: 0, to: 4975, dir: 1, panels: 4 }
  ];

  return {
    name: 'Magnolia 3BHK Premium',
    carpetArea: '105.35 m² / 1134 sq ft',
    height: 2.9,      // floor to ceiling, metres — assumed, not on the plan
    wallT: 200,       // outer wall thickness, mm — assumed
    eye: 1.6,         // walk-mode eye height, metres
    outside: { height: 78 }, // floor level above the ground, metres — drives the view from the windows
    rooms: rooms, openings: openings, furniture: F, decor: DEC, mouldings: mouldings
  };
})();
