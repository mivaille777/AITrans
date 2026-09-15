import { copyFileSync, cpSync, mkdirSync, readFileSync, rmSync } from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"
import { fileURLToPath } from "node:url"

const EXPECTED_VERSION = "6.3.289"
const ASSET_DIRECTORIES = ["cmaps", "standard_fonts", "iccs", "wasm"]
const require = createRequire(import.meta.url)
const packageJsonPath = require.resolve("pdfjs-dist/package.json")
const packageRoot = path.dirname(packageJsonPath)
const packageJson = JSON.parse(readFileSync(packageJsonPath, "utf8"))
const desktopRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const publicRoot = path.join(desktopRoot, "public")
const outputRoot = path.join(publicRoot, "pdfjs")

if (packageJson.version !== EXPECTED_VERSION) {
  throw new Error(`Expected pdfjs-dist ${EXPECTED_VERSION}, found ${packageJson.version}.`)
}
if (path.dirname(outputRoot) !== publicRoot) {
  throw new Error(`Refusing to replace unexpected PDF.js asset directory: ${outputRoot}`)
}

rmSync(outputRoot, { recursive: true, force: true })
mkdirSync(outputRoot, { recursive: true })

for (const directory of ASSET_DIRECTORIES) {
  cpSync(path.join(packageRoot, directory), path.join(outputRoot, directory), {
    recursive: true,
    force: true,
  })
}

copyFileSync(path.join(packageRoot, "LICENSE"), path.join(outputRoot, "LICENSE.pdfjs-dist"))
console.log(`Synced pdfjs-dist ${EXPECTED_VERSION} offline assets to ${outputRoot}.`)
