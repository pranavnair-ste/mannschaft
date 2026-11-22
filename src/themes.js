/* Theme palettes. Add a new object here (or paste one into the app's "Palette JSON" box) when
 * the designer's palettes arrive. Every colour is a hex string.
 *
 * base       — whole-home defaults
 * furniture  — placeholder furniture groups
 * rooms      — optional per-room overrides, keyed by room id from plan.js:
 *              { wall, floor, ceiling, walls: { N, E, S, W } }   (walls.* = one accent wall;
 *              N/E/S/W are plan directions: N = top of the plan as photographed)
 */
var THEMES = [
  {
    id: 'shell', name: 'Bare shell',
    base: { wall: '#f1f0ea', wallWet: '#e3e7e8', ceiling: '#f8f8f4', floor: '#c7c3b8', floorWet: '#b5babc', floorOutdoor: '#a5a299', trim: '#dedbd1', exterior: '#d3d0c6' },
    furniture: { wood: '#d6d2c7', fabric: '#dbd8cf', accent: '#cdc9be', stone: '#dfddd6', cabinet: '#e4e1d8', bedding: '#eeece5', sanitary: '#ffffff', metal: '#b6b6b1', dark: '#5a5d5f' },
    rooms: {}
  },
  {
    id: 'oak-linen', name: 'Oak & linen',
    base: { wall: '#ece4d6', wallWet: '#e9e6df', ceiling: '#f7f4ee', floor: '#c49a6c', floorWet: '#cfc8bb', floorOutdoor: '#9c8f7d', trim: '#7b5b3c', exterior: '#d8cfc0' },
    furniture: { wood: '#9a6f45', fabric: '#d9cdb8', accent: '#b5651d', stone: '#e8e2d6', cabinet: '#f0ebe1', bedding: '#f6f1e7', sanitary: '#ffffff', metal: '#a8a297', dark: '#2f2a25' },
    rooms: { living: { walls: { W: '#c9a27c' } }, mbed: { walls: { N: '#b98b6b' } } }
  },
  {
    id: 'slate-walnut', name: 'Slate & walnut',
    base: { wall: '#dfe2e4', wallWet: '#cfd5d8', ceiling: '#f3f4f4', floor: '#6f5645', floorWet: '#7d8589', floorOutdoor: '#5f6466', trim: '#3c3f44', exterior: '#b9bec2' },
    furniture: { wood: '#5a4030', fabric: '#56616b', accent: '#c58b3e', stone: '#2f3438', cabinet: '#e9ebec', bedding: '#eef0f1', sanitary: '#ffffff', metal: '#8d9499', dark: '#1e2124' },
    rooms: { living: { walls: { W: '#4a5560' } }, dining: { walls: { N: '#4a5560' } }, mbed: { walls: { N: '#39424b' } } }
  },
  {
    id: 'sage-terrazzo', name: 'Sage & terrazzo',
    base: { wall: '#e7eadf', wallWet: '#dfe6e0', ceiling: '#f6f7f1', floor: '#d5d0c4', floorWet: '#c3cbc3', floorOutdoor: '#a7ab9d', trim: '#f4f2ea', exterior: '#cfd4c5' },
    furniture: { wood: '#b88f62', fabric: '#8fa087', accent: '#c9735a', stone: '#ebe7dc', cabinet: '#6f8369', bedding: '#f3f1e8', sanitary: '#ffffff', metal: '#b7a36a', dark: '#2c332c' },
    rooms: { living: { walls: { W: '#8fa087' } }, bed1: { walls: { N: '#c7d1bd' } }, bed2: { wall: '#eadfd3' } }
  }
];
