import { chromium } from "playwright"
import { mkdir } from "node:fs/promises"
import path from "node:path"
import { fileURLToPath } from "node:url"

const here = path.dirname(fileURLToPath(import.meta.url))
const outputDir = path.resolve(here, "../../../docs/assets/screenshots")
await mkdir(outputDir, { recursive: true })

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({
  viewport: { width: 1680, height: 1050 },
  deviceScaleFactor: 1,
})

async function settle() {
  await page.evaluate(async () => {
    if (document.fonts?.ready) await document.fonts.ready
  })
  await page.waitForTimeout(2200)
}

async function capture(route, filename) {
  await page.goto(`http://127.0.0.1:5173/#${route}`, { waitUntil: "domcontentloaded" })
  await page.locator("body").waitFor({ state: "visible" })
  await settle()
  await page.screenshot({
    path: path.join(outputDir, filename),
    fullPage: false,
    animations: "disabled",
  })
}

await capture("/agent", "agent-workspace.png")
await capture("/reading", "reading-workspace.png")
await capture("/knowledge", "knowledge-workspace.png")

await page.goto("http://127.0.0.1:5173/#/settings", { waitUntil: "domcontentloaded" })
await page.locator("body").waitFor({ state: "visible" })
await settle()
const ragButton = page.getByRole("button", { name: /RAG Debug Studio/i })
await ragButton.click()
await settle()
await page.screenshot({
  path: path.join(outputDir, "rag-debug-studio.png"),
  fullPage: false,
  animations: "disabled",
})

await browser.close()
