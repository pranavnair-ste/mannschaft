// Bundles the app into one self-contained page (CSS and app code inlined, three.js from CDN)
// for publishing as a single file. Usage: node tools/bundle.mjs [out.html]
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = (p) => readFileSync(resolve(root, p), 'utf8');
const out = resolve(process.argv[2] || resolve(root, 'dist/magnolia-walkthrough.html'));

const page = `<title>Magnolia Walkthrough</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
${read('style.css')}
</style>
<div id="app"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
window.SKY_SRC = { day: 'data:image/jpeg;base64,${readFileSync(resolve(root, 'assets/sky-day.jpg')).toString('base64')}', evening: 'data:image/jpeg;base64,${readFileSync(resolve(root, 'assets/sky-evening.jpg')).toString('base64')}' };
${['src/plan.js', 'src/themes.js', 'src/app.js'].map(read).join('\n')}
</script>
`;
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, page);
console.log('wrote', out);
