/**
 * Milestone 7C — Browser-side OCR via Tesseract.js (WASM).
 *
 * Runs entirely in the user's browser: no OS binary, no server round-trip,
 * no paid API. Assets (worker, WASM core, eng.traineddata.gz) are vendored
 * locally by `npm run prepare-ocr` so the demo works offline. If local assets
 * are missing the worker creation fails and the UI shows the OCR failure
 * message instead of silently degrading.
 *
 * The classifier is untouched — this module only turns pixels into text.
 */
let workerPromise = null
let progressListener = null

async function createOcrWorker() {
  const { createWorker } = await import('tesseract.js')
  const base = (import.meta.env.BASE_URL || '/').replace(/\/?$/, '/')
  return createWorker('eng', 1, {
    workerPath: `${base}tesseract/worker.min.js`,
    corePath: `${base}tesseract`,
    langPath: `${base}tessdata`,
    logger: (m) => {
      if (progressListener && m) progressListener(m)
    },
  })
}

function getOcrWorker() {
  if (!workerPromise) {
    workerPromise = createOcrWorker()
    // Allow a retry on the next attempt if creation failed (e.g. assets missing).
    workerPromise.catch(() => {
      workerPromise = null
    })
  }
  return workerPromise
}

/**
 * Recognize text in an image File/Blob.
 * onProgress receives tesseract logger events: { status, progress }.
 * Returns the raw recognized text (may be empty).
 */
export async function runOcr(file, onProgress) {
  const worker = await getOcrWorker()
  progressListener = onProgress || null
  try {
    const result = await worker.recognize(file)
    return (result && result.data && typeof result.data.text === 'string')
      ? result.data.text
      : ''
  } finally {
    progressListener = null
  }
}
