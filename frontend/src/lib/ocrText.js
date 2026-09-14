/**
 * Milestone 7C — OCR text handling + upload validation (pure helpers).
 *
 * The classifier stays text-only:  image -> OCR -> THIS module normalizes and
 * gates the extracted text -> existing validate_job_text() (backend) ->
 * existing predict_one(). Nothing here invents content; it only trims,
 * normalizes whitespace and rejects unusable OCR output before prediction.
 */

export const ACCEPTED_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp']
export const ACCEPTED_IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.webp']
export const MAX_IMAGE_MB = 8
export const MAX_IMAGE_BYTES = MAX_IMAGE_MB * 1024 * 1024

export const IMAGE_FORMAT_MESSAGE =
  'Unsupported file type. Please upload a PNG, JPG or WEBP screenshot.'
export const IMAGE_SIZE_MESSAGE =
  `That image is too large (max ${MAX_IMAGE_MB} MB). Please upload a smaller screenshot.`
export const IMAGE_CORRUPT_MESSAGE =
  "That file doesn't look like a readable image. Please try a different screenshot."
export const OCR_TEXT_MESSAGE =
  "We couldn't extract enough readable job text from this image. Try a clearer screenshot or paste the job description instead."
export const OCR_FAILURE_MESSAGE =
  'The image text reader failed to start. Refresh the page and try again, or paste the job description instead.'

// Client-side minimums before anything is sent to the backend. The backend's
// existing validate_job_text() remains the authoritative gate.
const MIN_TEXT_CHARS = 60
const MIN_TEXT_WORDS = 12
const MIN_ALPHA_RATIO = 0.25

// Characters that carry no meaning for the classifier.
const INVISIBLE_CHARS = /[\u200b-\u200f\u202a-\u202e\u2060\ufeff\u00ad\x00-\x08\x0b\x0c\x0e-\x1f]/g

/**
 * Normalize raw OCR output without inventing words:
 * strip control/zero-width characters, normalize newlines, collapse runs of
 * whitespace to single spaces (OCR rows often split sentences), trim edges.
 */
export function normalizeOcrText(rawText) {
  if (typeof rawText !== 'string') return ''
  return rawText
    .replace(INVISIBLE_CHARS, '')
    .replace(/\r\n?/g, '\n')
    .replace(/[ \t\u00a0]+/g, ' ')
    .replace(/ ?\n ?/g, '\n')
    .replace(/\n{2,}/g, '\n')
    .trim()
}

function countWords(text) {
  return text.split(/\s+/).filter(Boolean).length
}

function alphaRatio(text) {
  if (!text.length) return 0
  const letters = text.replace(/[^A-Za-z]/g, '').length
  return letters / text.length
}

/**
 * Gate for OCR output: rejects empty, tiny or garbage (mostly non-alphabetic)
 * text BEFORE prediction. Returns { ok: true, text } or { ok: false, reason }.
 */
export function evaluateOcrText(normalizedText) {
  const text = (normalizedText || '').trim()
  if (!text) return { ok: false, reason: 'empty' }
  if (text.length < MIN_TEXT_CHARS) return { ok: false, reason: 'too_short' }
  if (countWords(text) < MIN_TEXT_WORDS) return { ok: false, reason: 'too_few_words' }
  if (alphaRatio(text) < MIN_ALPHA_RATIO) return { ok: false, reason: 'mostly_not_text' }
  return { ok: true, text }
}

/** History title: first meaningful line of the text (same rule as JobInput). */
export function derivedTitleFromText(text) {
  const firstLine = (text || '')
    .split('\n')
    .map((line) => line.trim())
    .find(Boolean)
  return (firstLine || 'Job posting from screenshot').slice(0, 120)
}

/**
 * Validate a selected image file (format + size). Decodability is checked
 * separately by the preview <img> onError handler.
 * Returns { ok: true } or { ok: false, message }.
 */
export function validateImageFile(file) {
  if (!file || typeof file.name !== 'string') {
    return { ok: false, message: IMAGE_CORRUPT_MESSAGE }
  }
  const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
  const typeOk = ACCEPTED_IMAGE_TYPES.includes(file.type)
  const extOk = ACCEPTED_IMAGE_EXTENSIONS.includes(extension)
  if (!typeOk && !extOk) return { ok: false, message: IMAGE_FORMAT_MESSAGE }
  if (file.size > MAX_IMAGE_BYTES) return { ok: false, message: IMAGE_SIZE_MESSAGE }
  if (file.size <= 0) return { ok: false, message: IMAGE_CORRUPT_MESSAGE }
  return { ok: true }
}
