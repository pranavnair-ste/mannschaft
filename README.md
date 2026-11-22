# Magnolia Walkthrough

A true-scale (1 unit = 1 metre) 3D model of the Magnolia 3BHK Premium flat, built from the
builder's floor plan in `reference/floor-plan.jpg`. It exists to try interior colour palettes
on the real room proportions before committing to them.

## Run it

No build step. Serve the folder and open it:

```
python3 -m http.server 8000     # then http://localhost:8000
```

three.js loads from a CDN, so the page needs internet access.

## Using it

- **Dollhouse / Plan / Walk** — orbit the whole flat, look straight down, or walk through it at
  eye height (1.6 m) and real walking pace. Drag to look, `W A S D` to move, double-click a floor
  to jump there. Walls stop you; furniture does not.
- **Click any surface** to recolour that wall, all walls in the room, its floor or its ceiling.
  Click furniture to recolour that material group.
- **Lighting** switches between daylight (sun and shadows through the windows) and evening with
  the ceiling lights on. **Flooring** switches dry rooms between wood planks, large tiles and plain.
  Textures are near-white and tinted by the palette colour, so palettes still drive everything.
- **Enter VR** appears on WebXR headsets and puts you inside the flat at life size.
- Edits are remembered in the browser. **Palette JSON** is the portable form: copy it out to
  keep a palette, paste one in to apply it.

## Adding the real theme palettes

Add an object to `src/themes.js` (format is documented at the top of that file), or paste the
JSON into the app. A palette has whole-home defaults (`base`), furniture groups (`furniture`)
and optional per-room overrides (`rooms`), including single accent walls.

## What is measured and what is assumed

`src/plan.js` holds all geometry in millimetres.

- **From the plan:** every room's printed size, the room adjacencies, furniture positions.
- **Assumed:** ceiling height (2.9 m), wall thicknesses (200 mm outer, 115 mm inner), exact door
  and window positions and sizes, sill and head heights. The plan is marked NTS (not to scale)
  and prints none of these. Check them on site and correct `plan.js` — walls, collisions and
  labels are all generated from it.
- The passage outside the bedrooms (puja niche flanked by the Bedroom 1 and Master bedroom
  doors) is the least legible part of the photo and is the best guess at the layout.

## Files

- `index.html`, `style.css` — page shell
- `src/plan.js` — rooms, openings, furniture
- `src/themes.js` — palettes
- `src/app.js` — builds the model, views, picking and the palette editor
- `tools/bundle.mjs` — writes a single self-contained HTML file for sharing
