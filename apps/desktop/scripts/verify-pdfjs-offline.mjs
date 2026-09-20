import { createHash } from "node:crypto"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"
import process from "node:process"

const inputs = process.argv.slice(2).map((value) => path.resolve(value))
if (inputs.length === 0) {
  throw new Error("Pass one or more local PDF paths to verify.")
}

globalThis.fetch = async (input) => {
  throw new Error(`Offline verification blocked a network fetch: ${String(input)}`)
}

const require = createRequire(import.meta.url)
const pdfPackageRoot = path.dirname(require.resolve("pdfjs-dist/package.json"))
const { DOMMatrix, ImageData, Path2D, createCanvas } = await import("@napi-rs/canvas")
globalThis.DOMMatrix = DOMMatrix
globalThis.ImageData = ImageData
globalThis.Path2D = Path2D
const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs")

function assetDirectory(name) {
  return `${path.join(pdfPackageRoot, name).replaceAll("\\", "/")}/`
}

for (const input of inputs) {
  const bytes = readFileSync(input)
  const task = pdfjs.getDocument({
    data: new Uint8Array(bytes),
    cMapUrl: assetDirectory("cmaps"),
    cMapPacked: true,
    standardFontDataUrl: assetDirectory("standard_fonts"),
    iccUrl: assetDirectory("iccs"),
    wasmUrl: assetDirectory("wasm"),
    useWorkerFetch: false,
  })
  const document = await task.promise
  let textItems = 0
  for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
    const page = await document.getPage(pageNumber)
    const textContent = await page.getTextContent({ includeMarkedContent: true })
    textItems += textContent.items.filter((item) => "str" in item && item.str.trim()).length
    if (pageNumber === 1) {
      const viewport = page.getViewport({ scale: 1 })
      const canvas = createCanvas(Math.ceil(viewport.width), Math.ceil(viewport.height))
      await page.render({ canvas, canvasContext: canvas.getContext("2d"), viewport }).promise
    }
  }
  if (textItems === 0) {
    throw new Error(`${input} has no extractable text items; it cannot verify selection.`)
  }
  const sha256 = createHash("sha256").update(bytes).digest("hex")
  console.log(`${path.basename(input)} pages=${document.numPages} textItems=${textItems} sha256=${sha256}`)
  await task.destroy()
}

console.log("Offline PDF.js parse, text extraction, and first-page canvas rendering passed.")
