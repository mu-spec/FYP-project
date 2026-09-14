/**
 * Milestone 7C — Prepare local Tesseract.js OCR assets.
 *
 * Copies the WASM OCR engine + web worker from node_modules into public/
 * and downloads the English traineddata file once, so the app's OCR runs
 * fully locally (no CDN dependency at demo time, works offline, nothing
 * OS-level to install — it is all browser-side WASM).
 *
 * These assets are gitignored (frontend/public/tesseract, frontend/public/tessdata);
 * re-running `npm install` restores them.
 */
import { copyFileSync, existsSync, mkdirSync, statSync } from 'node:fs'
import { createWriteStream } from 'node:fs'
import path from 'node:path'
import { Readable } from 'node:stream'
import { pipeline } from 'node:stream/promises'
import { fileURLToPath } from 'node:url'

const frontendRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const coreSrc = path.join(frontendRoot, 'node_modules', 'tesseract.js-core')
const workerSrc = path.join(frontendRoot, 'node_modules', 'tesseract.js', 'dist', 'worker.min.js')
const coreDest = path.join(frontendRoot, 'public', 'tesseract')
const langDest = path.join(frontendRoot, 'public', 'tessdata')

mkdirSync(coreDest, { recursive: true })
mkdirSync(langDest, { recursive: true })

// 1) Web worker (glue between the page and the WASM core).
if (!existsSync(workerSrc)) {
  console.error('✗ tesseract.js is not installed. Run: npm install')
  process.exit(1)
}
copyFileSync(workerSrc, path.join(coreDest, 'worker.min.js'))

// 2) WASM cores. createWorker(..., OEM.LSTM_ONLY) loads one of these three
//    variants depending on the browser's SIMD support.
let copied = 0
for (const name of [
  'tesseract-core-relaxedsimd-lstm.wasm.js',
  'tesseract-core-relaxedsimd-lstm.wasm',
  'tesseract-core-simd-lstm.wasm.js',
  'tesseract-core-simd-lstm.wasm',
  'tesseract-core-lstm.wasm.js',
  'tesseract-core-lstm.wasm',
]) {
  const src = path.join(coreSrc, name)
  if (existsSync(src)) {
    copyFileSync(src, path.join(coreDest, name))
    copied += 1
  } else {
    console.warn(`  ! optional core variant missing, skipped: ${name}`)
  }
}
console.log(`  ✓ worker + ${copied} WASM core variants copied to public/tesseract/`)

// 3) English language data (downloaded once, ~11 MB).
const traineddata = path.join(langDest, 'eng.traineddata.gz')
const TRAINEDDATA_MIN_BYTES = 1_000_000
if (existsSync(traineddata) && statSync(traineddata).size >= TRAINEDDATA_MIN_BYTES) {
  console.log('  ✓ eng.traineddata.gz already present (public/tessdata/)')
} else {
  const url = 'https://tessdata.projectnaptha.com/4.0.0/eng.traineddata.gz'
  console.log(`  … downloading eng.traineddata.gz (once) from ${url}`)
  const res = await fetch(url)
  if (!res.ok) {
    console.error(`✗ traineddata download failed (HTTP ${res.status}).`)
    console.error('  OCR assets are incomplete — re-run: npm run prepare-ocr')
    process.exit(1)
  }
  await pipeline(Readable.fromWeb(res.body), createWriteStream(traineddata))
  console.log(`  ✓ saved ${(statSync(traineddata).size / 1e6).toFixed(1)} MB → public/tessdata/eng.traineddata.gz`)
}

console.log('✅ OCR assets ready — Tesseract.js will run fully locally.')
