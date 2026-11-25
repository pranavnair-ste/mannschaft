/* Theme palettes. Add a new object here (or paste one into the app's "Palette JSON" box).
 * Every colour is a hex string.
 *
 * The themes after "Bare shell" are derived from the interior styles shown on CeeBee Design
 * Studio's site (https://www.ceebeedesignstudio.com/interior-styles and the project pages it links
 * to). Names are the studio's own. The site states no colour values; where a project page names
 * colours or materials in words (noted per theme) those were followed, and everything else was
 * sampled from the project photographs (colour quantisation, then assigned to surfaces by eye and
 * corrected for the warm photo lighting). `source` is the page each theme came from.
 *
 * base       — whole-home defaults; optional floorFinish: 'wood' | 'tile' | 'plain';
 *              optional moulding: true shows panel mouldings on the feature walls
 * furniture  — placeholder furniture groups
 * rooms      — optional per-room overrides, keyed by room id from plan.js:
 *              { wall, floor, ceiling, walls: { N, E, S, W } }   (walls.* = one accent wall;
 *              N/E/S/W are plan directions: N = top of the plan as photographed.
 *              Living TV wall = W; headboard walls: bed1 N, bed2 W, mbed W)
 */
var THEMES = [
  {
    id: 'shell', name: 'Bare shell',
    base: { wall: '#f1f0ea', wallWet: '#e3e7e8', ceiling: '#f8f8f4', floor: '#c7c3b8', floorWet: '#b5babc', floorOutdoor: '#a5a299', trim: '#dedbd1', exterior: '#d3d0c6' },
    furniture: { wood: '#d6d2c7', fabric: '#dbd8cf', accent: '#cdc9be', stone: '#dfddd6', cabinet: '#e4e1d8', bedding: '#eeece5', sanitary: '#ffffff', metal: '#b6b6b1', dark: '#5a5d5f' },
    rooms: {}
  },
  { // cream panelling and cabinetry, light oak, a deep-blue study, lavender kids' room
    id: 'english-country', name: 'English Country Style',
    source: 'https://www.ceebeedesignstudio.com/projects/english-country-style',
    base: { wall: '#efe6d2', wallWet: '#ece8de', ceiling: '#f7f3ea', floor: '#cfa874', floorWet: '#d9d2c4', floorOutdoor: '#a89a86', trim: '#f3ecdc', exterior: '#ddd4c3', floorFinish: 'wood' },
    furniture: { wood: '#c9a06a', fabric: '#e6dcc8', accent: '#d8a49b', stone: '#f1ece2', cabinet: '#f2e6c8', bedding: '#f7f3ea', sanitary: '#ffffff', metal: '#3a3632', dark: '#2a2a2c' },
    rooms: { living: { walls: { W: '#e6d8bc' } }, bed2: { wall: '#1f5d84' }, bed1: { walls: { N: '#c8c2e0' } } }
  },
  { // warm cream walls, wood-plank ceilings, stone cladding, tan leather, charcoal kitchen
    id: 'european-country', name: 'European Country Style',
    source: 'https://www.ceebeedesignstudio.com/projects/bhk2-apartment-in-kolkata-european-country-style',
    base: { wall: '#ede4cf', wallWet: '#e2ddd2', ceiling: '#f4efe6', floor: '#8c6a4a', floorWet: '#b08a62', floorOutdoor: '#9a7350', trim: '#6b4a2e', exterior: '#d8cfbf', floorFinish: 'wood' },
    furniture: { wood: '#7a5a3c', fabric: '#c9a672', accent: '#d8cdb8', stone: '#3a3836', cabinet: '#4a4d4a', bedding: '#efe9dc', sanitary: '#ffffff', metal: '#8a7a5a', dark: '#1e1a16' },
    rooms: { living: { ceiling: '#7e5a3e', walls: { W: '#cfc6b6' } }, mbed: { ceiling: '#7e5a3e', walls: { W: '#e3d2a8' } } }
  },
  { // page describes pastels with colour accents; white tile floor, teak, dark beams
    id: 'scandinavian', name: 'Scandinavian',
    source: 'https://www.ceebeedesignstudio.com/projects/scandinavian',
    base: { wall: '#f2f0ea', wallWet: '#e6e6e2', ceiling: '#f7f6f2', floor: '#e9e5dc', floorWet: '#d6d4ce', floorOutdoor: '#b0aba1', trim: '#6b4e34', exterior: '#dedbd3', floorFinish: 'tile' },
    furniture: { wood: '#7a5434', fabric: '#d08c78', accent: '#6f9fa8', stone: '#efece6', cabinet: '#b9c0b6', bedding: '#4a5672', sanitary: '#ffffff', metal: '#b8a17a', dark: '#2a2b2d' },
    rooms: { living: { walls: { W: '#e9e4da' } }, bed1: { walls: { N: '#a3abb0' } }, bed2: { walls: { W: '#c9d3cf' } } }
  },
  { // white walls, beige marble, walnut, grey sofa with powder-blue chair, blue patterned tiles
    id: 'eclectic', name: 'An Eclectic Home',
    source: 'https://www.ceebeedesignstudio.com/projects/an-eclectic-home',
    base: { wall: '#f5f2ec', wallWet: '#ece9e4', ceiling: '#fbfaf7', floor: '#dccab0', floorWet: '#d9d1c4', floorOutdoor: '#a69d90', trim: '#8a5a3a', exterior: '#ddd6cb', floorFinish: 'tile' },
    furniture: { wood: '#6e4630', fabric: '#7d756c', accent: '#9cc0cc', stone: '#2b2a2a', cabinet: '#f4f1ea', bedding: '#f3efe8', sanitary: '#ffffff', metal: '#c9a45a', dark: '#1f1c1a' },
    rooms: { dining: { walls: { N: '#6f93ad' } }, kitchen: { wall: '#d3dde3' } }
  },
  { // cream-yellow walls, rich carved teak, royal-blue upholstery, brass
    id: 'ethnic-penthouse', name: 'Ethnic Interior Penthouse',
    source: 'https://www.ceebeedesignstudio.com/projects/bhk3-home-design-interior-design',
    base: { wall: '#efe2bf', wallWet: '#e6dccb', ceiling: '#f6f0e0', floor: '#9a6a44', floorWet: '#cdb79a', floorOutdoor: '#9a8a76', trim: '#5a3620', exterior: '#d9cdb4', floorFinish: 'wood' },
    furniture: { wood: '#6b3f22', fabric: '#2c3a6e', accent: '#c9b48a', stone: '#1e1c1c', cabinet: '#8a5e3a', bedding: '#efe4cf', sanitary: '#ffffff', metal: '#b58a3c', dark: '#1a1412' },
    rooms: { living: { walls: { W: '#e6cf98' } }, puja: { wall: '#d9a441' } }
  },
  { // cream walls, wenge woodwork, dark wood floors, stacked-stone and red-brick walls, butter sofas
    id: 'kerala', name: 'Kerala Style Bungalow',
    source: 'https://www.ceebeedesignstudio.com/projects/interior-design-project-in-kerala-style',
    base: { wall: '#f1e8d6', wallWet: '#e7e0d3', ceiling: '#f7f2e8', floor: '#6a3d28', floorWet: '#d8cbb8', floorOutdoor: '#9c5a3a', trim: '#2f2119', exterior: '#d8cdb9', floorFinish: 'wood' },
    furniture: { wood: '#3b2a20', fabric: '#e2cc96', accent: '#a5464a', stone: '#2a2725', cabinet: '#4a3326', bedding: '#efe6dc', sanitary: '#ffffff', metal: '#b88a3a', dark: '#1b1514' },
    rooms: { living: { walls: { W: '#8f6a52' } }, dining: { walls: { N: '#9a4a32' } } }
  },
  { // off-white, walnut laminate, white marble, sandstone cladding, brown sofa, yellow accents
    id: 'contemporary-indian', name: 'Contemporary Indian Home',
    source: 'https://www.ceebeedesignstudio.com/projects/contemporary-indian-home',
    base: { wall: '#f4f1ea', wallWet: '#e9e5dd', ceiling: '#f8f7f3', floor: '#ddd3c0', floorWet: '#d3cbbd', floorOutdoor: '#a49c8f', trim: '#5a4436', exterior: '#ddd7cb', floorFinish: 'tile' },
    furniture: { wood: '#5e4537', fabric: '#5a4234', accent: '#e2c66a', stone: '#2a2624', cabinet: '#8a7765', bedding: '#efe1b8', sanitary: '#ffffff', metal: '#c9a24a', dark: '#1e1c1c' },
    rooms: { living: { walls: { W: '#d9c9a8' } }, dining: { walls: { N: '#d9c9a8' } }, bed1: { wall: '#ecd98e' }, mbed: { walls: { W: '#cfc0a0' } } }
  },
  { // page describes few materials and neutral colours; grey, white, black, light oak
    id: 'modern-minimal', name: 'Modern Minimal Home',
    source: 'https://www.ceebeedesignstudio.com/projects/modern-minimal-home',
    base: { wall: '#f3f1ed', wallWet: '#e7e7e5', ceiling: '#fafaf8', floor: '#d9d7d3', floorWet: '#cfcfcd', floorOutdoor: '#a3a3a0', trim: '#e8e6e2', exterior: '#dcdcd8', floorFinish: 'tile' },
    furniture: { wood: '#c8a477', fabric: '#8a8c8f', accent: '#566b5c', stone: '#f2f1ee', cabinet: '#f1f0ec', bedding: '#f5f4f1', sanitary: '#ffffff', metal: '#2b2b2b', dark: '#1d1d1f' },
    rooms: { dining: { walls: { N: '#2f3133' } }, mbed: { walls: { W: '#d6d4d0' } } }
  },
  { // page names pastels with olive and blue accents, a blue kitchen, a pale-blue living
    // room, wood, rattan and terracotta
    id: 'close-to-earth', name: 'Close To Earth',
    source: 'https://www.ceebeedesignstudio.com/projects/close-to-earth',
    base: { wall: '#f3efe6', wallWet: '#e9e7e1', ceiling: '#f8f6f1', floor: '#e0d1b9', floorWet: '#d0d3cc', floorOutdoor: '#b0704a', trim: '#7a5236', exterior: '#ddd6c8', floorFinish: 'tile' },
    furniture: { wood: '#7a5236', fabric: '#c9d3d6', accent: '#c9a97a', stone: '#f0ede6', cabinet: '#2f5089', bedding: '#eef0ee', sanitary: '#ffffff', metal: '#b08a4a', dark: '#232528' },
    rooms: { living: { walls: { W: '#a9c6c8' } }, bed2: { walls: { W: '#6f7d4e' } }, bed1: { walls: { N: '#bcd3cd' } }, bath3: { wall: '#a7b8ac' } }
  },
  { // cream-white rooms, teal velvet, mustard, gold; mint and salmon bedroom walls
    id: 'contemporary-blues', name: 'Contemporary Blues',
    source: 'https://www.ceebeedesignstudio.com/modern-contemporary',
    base: { wall: '#f4efe6', wallWet: '#ece8e0', ceiling: '#faf8f4', floor: '#e3d6c2', floorWet: '#ddd6ca', floorOutdoor: '#aaa194', trim: '#efe9df', exterior: '#ddd6ca', floorFinish: 'tile' },
    furniture: { wood: '#a0703e', fabric: '#3e8496', accent: '#d9b23a', stone: '#f2eee8', cabinet: '#f3eee4', bedding: '#efe2d9', sanitary: '#ffffff', metal: '#c9a24a', dark: '#1f2224' },
    rooms: { dining: { walls: { N: '#bcd6e0' } }, bed1: { walls: { N: '#cad4ba' } }, mbed: { walls: { W: '#edae9b' } } }
  },
  { // page names rich wood, green chairs and a light green dining wall
    id: 'indian-traditional', name: 'Indian Traditional Interiors',
    source: 'https://www.ceebeedesignstudio.com/projects/classic-timeless-and-traditional',
    base: { wall: '#f5f2ea', wallWet: '#e8e4dc', ceiling: '#faf8f2', floor: '#e2d8c4', floorWet: '#d8d1c3', floorOutdoor: '#a39a8a', trim: '#5b3218', exterior: '#dcd4c4', floorFinish: 'tile' },
    furniture: { wood: '#6a3a1c', fabric: '#e9e2d2', accent: '#7fae7a', stone: '#2b2826', cabinet: '#4b3121', bedding: '#efe8da', sanitary: '#ffffff', metal: '#b8913f', dark: '#1c1714' },
    rooms: { living: { walls: { W: '#c49a8a' } }, dining: { walls: { N: '#b9c8a8' } }, mbed: { walls: { W: '#8a8a86' } } }
  },
  { // peach walls, rust textured cladding, honey oak, navy bedroom, grey sofa, cream marble
    id: 'warm-earthy', name: 'Warm Earthy Tone Duplex',
    source: 'https://www.ceebeedesignstudio.com/projects/warm-earthy-tone-duplex',
    base: { wall: '#efd2b2', wallWet: '#eadfd1', ceiling: '#f8efe4', floor: '#e9d8c2', floorWet: '#ddd0bf', floorOutdoor: '#a98e72', trim: '#c18a4e', exterior: '#e0d0bd', floorFinish: 'tile' },
    furniture: { wood: '#c68a48', fabric: '#bdb6ac', accent: '#a8442a', stone: '#efe6d8', cabinet: '#c99254', bedding: '#e8cfb6', sanitary: '#ffffff', metal: '#b8893c', dark: '#231a16' },
    rooms: { living: { walls: { W: '#8e5a3c' } }, mbed: { walls: { W: '#2d3657' } }, bed2: { walls: { W: '#8f97a6' } } }
  },
  { // page names cream, tan and white with wood, stone and leather
    id: 'vintage-vibrant', name: 'Vintage & Vibrant Vibes',
    source: 'https://www.ceebeedesignstudio.com/projects/vintage-and-vibrant-vibes-home',
    base: { wall: '#f1ede5', wallWet: '#d9d6cf', ceiling: '#faf8f3', floor: '#d8c9b0', floorWet: '#c9c5bd', floorOutdoor: '#a49a8a', trim: '#efe9df', exterior: '#ddd5c7', floorFinish: 'tile' },
    furniture: { wood: '#6e4a30', fabric: '#bdb8b1', accent: '#a87a4e', stone: '#ece6da', cabinet: '#cfccc4', bedding: '#b3c3d6', sanitary: '#ffffff', metal: '#b8913f', dark: '#1f1d1c' },
    rooms: { dining: { walls: { N: '#d7c6a8' } }, mbed: { walls: { W: '#e6d9bf' } } }
  },
  { // NOT taken from a studio page (none found for this style): the usual Modern Victorian vocabulary —
    // panel mouldings, deep navy and green feature walls, walnut floor, brass, velvet, marble
    id: 'modern-victorian', name: 'Modern Victorian',
    base: { wall: '#e4dfd4', wallWet: '#e8e6e1', ceiling: '#f6f3ec', floor: '#7a5a3c', floorWet: '#d9d6d0', floorOutdoor: '#8b8478', trim: '#f1ede3', exterior: '#d5cfc3', floorFinish: 'wood', moulding: true },
    furniture: { wood: '#3f2c1f', fabric: '#2f4a44', accent: '#7b1e3a', stone: '#ece9e2', cabinet: '#26324a', bedding: '#f2eee6', sanitary: '#ffffff', metal: '#b08d3c', dark: '#17171a' },
    rooms: { living: { walls: { W: '#26324a' } }, dining: { walls: { N: '#2f4a44' } }, bed1: { walls: { N: '#1d2b4a' } }, bed2: { walls: { W: '#2f4a44' } }, mbed: { walls: { W: '#26324a' } } }
  }
];
