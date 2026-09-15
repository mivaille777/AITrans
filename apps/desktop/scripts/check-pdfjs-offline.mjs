import { existsSync, readFileSync, readdirSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const desktopRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const sourceRoot = path.join(desktopRoot, "src")
const distRoot = path.join(desktopRoot, "dist")
const manifestPath = path.join(distRoot, ".vite", "manifest.json")
const forbiddenPdfCdn = [
  /cdnjs\.cloudflare\.com\/ajax\/libs\/pdf\.js/i,
  /unpkg\.com\/pdfjs-dist/i,
  /cdn\.jsdelivr\.net\/npm\/pdfjs-dist/i,
]

function filesBelow(root) {
  return readdirSync(root, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile())
    .map((entry) => path.join(entry.parentPath, entry.name))
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

function assertNoPdfCdn(root) {
  for (const file of filesBelow(root)) {
    if (!/\.(?:css|html|js|json|mjs|ts|tsx)$/.test(file)) continue
    const content = readFileSync(file, "utf8")
    const match = forbiddenPdfCdn.find((pattern) => pattern.test(content))
    assert(!match, `Forbidden PDF.js CDN reference ${match} found in ${file}.`)
  }
}

function assertAssetClass(directory, extensionPattern) {
  const assetRoot = path.join(distRoot, "pdfjs", directory)
  assert(existsSync(assetRoot), `Missing PDF.js ${directory} directory in dist.`)
  const matches = filesBelow(assetRoot).filter((file) => extensionPattern.test(file))
  assert(matches.length > 0, `No expected PDF.js ${directory} assets found in dist.`)
  return matches.length
}

assert(existsSync(manifestPath), "Vite manifest is missing; run this check after vite build.")
assertNoPdfCdn(sourceRoot)
assertNoPdfCdn(distRoot)

const packageJson = JSON.parse(readFileSync(path.join(desktopRoot, "package.json"), "utf8"))
assert(packageJson.dependencies?.["pdfjs-dist"] === "6.3.289", "pdfjs-dist must stay pinned to 6.3.289.")

const manifest = JSON.parse(readFileSync(manifestPath, "utf8"))
const runtime = manifest["node_modules/pdfjs-dist/build/pdf.mjs"]
const worker = manifest["node_modules/pdfjs-dist/build/pdf.worker.min.mjs"]
assert(runtime?.isDynamicEntry === true, "PDF.js runtime is missing or no longer a lazy Vite entry.")
assert(worker?.file, "PDF.js worker is missing from the Vite manifest.")
assert(existsSync(path.join(distRoot, runtime.file)), `PDF.js runtime file is missing: ${runtime.file}`)
assert(existsSync(path.join(distRoot, worker.file)), `PDF.js worker file is missing: ${worker.file}`)

const applicationJavaScript = filesBelow(path.join(distRoot, "assets"))
  .filter((file) => file.endsWith(".js"))
  .map((file) => readFileSync(file, "utf8"))
  .join("\n")
assert(applicationJavaScript.includes(path.basename(worker.file)), "Built application does not reference the emitted PDF.js worker.")

const counts = {
  cmaps: assertAssetClass("cmaps", /\.bcmap$/),
  standardFonts: assertAssetClass("standard_fonts", /\.(?:pfb|ttf)$/),
  iccs: assertAssetClass("iccs", /\.icc$/),
  wasm: assertAssetClass("wasm", /\.wasm$/),
}
assert(existsSync(path.join(distRoot, "pdfjs", "LICENSE.pdfjs-dist")), "PDF.js license was not copied to dist.")

console.log(`PDF.js offline guard passed: runtime=${runtime.file}, worker=${worker.file}, assets=${JSON.stringify(counts)}.`)
