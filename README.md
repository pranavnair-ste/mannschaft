# Magnolia Walkthrough

A true-scale (1 unit = 1 metre) 3D model of the Magnolia 3BHK Premium flat, built from the
builder's floor plan (the plan sheet itself is deliberately not kept in this repo). It exists to try interior colour palettes
on the real room proportions before committing to them.

## Run it

No build step. Serve the folder and open it:

```
python3 -m http.server 8000     # then http://localhost:8000
```

three.js loads from a CDN, so the page needs internet access.

## Host it publicly (GitHub Pages)

The site is static, so GitHub Pages can serve it straight from a branch:

1. Repo **Settings → Pages**.
2. Under **Build and deployment**, set **Source** to *Deploy from a branch*.
3. Pick the branch that holds this app and the `/ (root)` folder, then **Save**.
4. After a minute or two the page shows the public URL.

Pages on a private repository needs a paid GitHub plan; the published site is public either
way. Anyone with the URL can see the floor plan and unit details.

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

## Theme palettes

The built-in themes are derived from the interior styles on the designer's site,
[CeeBee Design Studio](https://www.ceebeedesignstudio.com/interior-styles), and carry the studio's
own style names. The site publishes no colour codes, so the colours were sampled from each project's
photographs (following any colours and materials the project page names) and are approximations to
check against real samples. Each theme records the page it came from in `source`. **Bare shell** is
kept as a neutral baseline.

To add or change a palette, edit `src/themes.js` (format is documented at the top of that file), or paste the
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

## The view outside

The flat is modelled high in its tower (`outside.height` in `src/plan.js`). The sky is a
photographed panorama; the city below is generic modelled geometry, not the real surroundings.
Sky photographs are CC0 from Poly Haven (`kloofendal_38d_partly_cloudy_puresky`,
`qwantani_dusk_2_puresky`), resized into `assets/`.

## Files

- `index.html`, `style.css` — page shell
- `src/plan.js` — rooms, openings, furniture
- `src/themes.js` — palettes
- `src/app.js` — builds the model, views, picking and the palette editor
- `tools/bundle.mjs` — writes a single self-contained HTML file for sharing
