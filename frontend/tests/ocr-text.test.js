/**
 * Milestone 7C — tests for OCR text handling + upload validation helpers.
 *
 * Run from frontend/:
 *     npm test          (node --test tests/)
 *
 * These cover the client-side gates ONLY (normalization, text threshold,
 * file format/size). The authoritative job-text validation and prediction
 * remain the existing backend pipeline, covered by the backend suites.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  normalizeOcrText,
  evaluateOcrText,
  validateImageFile,
  derivedTitleFromText,
  IMAGE_FORMAT_MESSAGE,
  IMAGE_SIZE_MESSAGE,
  IMAGE_CORRUPT_MESSAGE,
  MAX_IMAGE_BYTES,
} from '../src/lib/ocrText.js'

const GOOD_TEXT = (
  'Data Entry Jobs — Earn $3,000 weekly! No experience needed. Work from home, ' +
  'two hours daily. Pay a $50 registration fee via Easypaisa to start immediately. ' +
  'Email fastjobshiring2024@gmail.com now. Limited slots, act fast!'
)

// ---------------------------------------------------------------- normalize
test('normalizeOcrText trims and collapses whitespace without inventing words', () => {
  const raw = '\n\n  Data   Entry   Jobs  \n\n  Earn   $3,000 weekly!  \n\n  '
  assert.equal(normalizeOcrText(raw), 'Data Entry Jobs\nEarn $3,000 weekly!')
})

test('normalizeOcrText strips control and zero-width characters', () => {
  const raw = 'Hiring\u200b now\uFEFF!!!\u0007 Apply\u00ad today'
  const out = normalizeOcrText(raw)
  assert.equal(out, 'Hiring now!!! Apply today')
  assert.ok(!/[\u200b\ufeff\u0007\u00ad]/.test(out))
})

test('normalizeOcrText is safe on non-string input', () => {
  assert.equal(normalizeOcrText(null), '')
  assert.equal(normalizeOcrText(undefined), '')
  assert.equal(normalizeOcrText(42), '')
})

// -------------------------------------------------------------------- gate
test('evaluateOcrText accepts a clear job screenshot text', () => {
  const result = evaluateOcrText(normalizeOcrText(GOOD_TEXT))
  assert.equal(result.ok, true)
})

test('evaluateOcrText rejects empty and whitespace-only OCR output', () => {
  assert.equal(evaluateOcrText('').ok, false)
  assert.equal(evaluateOcrText('   \n  ').ok, false)
  assert.equal(evaluateOcrText(null).ok, false)
})

test('evaluateOcrText rejects too-little text before prediction', () => {
  const result = evaluateOcrText('Hiring now!')
  assert.equal(result.ok, false)
  assert.equal(result.reason, 'too_short')
})

test('evaluateOcrText rejects too-few-words output', () => {
  const result = evaluateOcrText('a'.repeat(80)) // long but a single "word"
  assert.equal(result.ok, false)
  assert.equal(result.reason, 'too_few_words')
})

test('evaluateOcrText rejects garbage that is mostly not alphabetic text', () => {
  const garbage = normalizeOcrText('1234 5678 $$$. !!! ??? 9012 #### @@@@ 3456 %%%% 7890 &&&& 0000 ~~~~')
  const result = evaluateOcrText(garbage)
  assert.equal(result.ok, false)
  assert.equal(result.reason, 'mostly_not_text')
})

test('evaluateOcrText does not send empty OCR output to the classifier', () => {
  // A blank screenshot yields '' -> must be rejected client-side.
  const result = evaluateOcrText(normalizeOcrText(''))
  assert.equal(result.ok, false)
})

// ------------------------------------------------------------- file checks
test('validateImageFile accepts png, jpg, jpeg and webp', () => {
  for (const [name, type] of [
    ['shot.png', 'image/png'],
    ['shot.jpg', 'image/jpeg'],
    ['shot.jpeg', 'image/jpeg'],
    ['shot.webp', 'image/webp'],
    ['shot.PNG', ''], // extension-only fallback
  ]) {
    const result = validateImageFile({ name, type, size: 500_000 })
    assert.equal(result.ok, true, `${name} (${type})`)
  }
})

test('validateImageFile rejects unsupported formats with a clear message', () => {
  for (const file of [
    { name: 'anim.gif', type: 'image/gif', size: 1000 },
    { name: 'scan.bmp', type: 'image/bmp', size: 1000 },
    { name: 'doc.pdf', type: 'application/pdf', size: 1000 },
    { name: 'notes.txt', type: 'text/plain', size: 1000 },
  ]) {
    const result = validateImageFile(file)
    assert.equal(result.ok, false, file.name)
    assert.equal(result.message, IMAGE_FORMAT_MESSAGE)
  }
})

test('validateImageFile enforces the size limit', () => {
  const result = validateImageFile({ name: 'big.png', type: 'image/png', size: MAX_IMAGE_BYTES + 1 })
  assert.equal(result.ok, false)
  assert.equal(result.message, IMAGE_SIZE_MESSAGE)
})

test('validateImageFile rejects empty and unreadable-looking files', () => {
  assert.equal(validateImageFile({ name: 'x.png', type: 'image/png', size: 0 }).message, IMAGE_CORRUPT_MESSAGE)
  assert.equal(validateImageFile(null).message, IMAGE_CORRUPT_MESSAGE)
})

// ------------------------------------------------------------------- title
test('derivedTitleFromText uses the first meaningful line, capped', () => {
  assert.equal(derivedTitleFromText('\n \nSenior React Engineer\nRemote role'), 'Senior React Engineer')
  assert.equal(derivedTitleFromText(''), 'Job posting from screenshot')
  assert.equal(derivedTitleFromText('x'.repeat(300)).length, 120)
})
