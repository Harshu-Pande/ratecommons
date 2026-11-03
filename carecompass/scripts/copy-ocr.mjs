// Self-host the on-device OCR engine so a card scan never calls a third-party CDN.
import { copyFileSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const pkg = (name) => dirname(require.resolve(`${name}/package.json`))
const out = join(process.cwd(), 'public', 'ocr')
mkdirSync(out, { recursive: true })
const files = [
  [join(pkg('tesseract.js'), 'dist', 'worker.min.js'), 'worker.min.js'],
  [join(pkg('tesseract.js-core'), 'tesseract-core-lstm.wasm.js'), 'tesseract-core-lstm.wasm.js'],
  [join(pkg('tesseract.js-core'), 'tesseract-core-simd-lstm.wasm.js'), 'tesseract-core-simd-lstm.wasm.js'],
  [join(pkg('@tesseract.js-data/eng'), '4.0.0_best_int', 'eng.traineddata.gz'), 'eng.traineddata.gz'],
]
for (const [from, to] of files) copyFileSync(from, join(out, to))
console.log(`copied ${files.length} OCR files to public/ocr`)
