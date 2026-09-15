import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url"

const LOCAL_ASSET_ROOT = "pdfjs"

let pdfJsPromise: Promise<typeof import("pdfjs-dist")> | null = null

export interface LocalPdfDocumentSource {
  url: string
  cMapUrl: string
  cMapPacked: true
  standardFontDataUrl: string
  iccUrl: string
  wasmUrl: string
}

function localAssetDirectory(name: string): string {
  const applicationRoot = new URL(import.meta.env.BASE_URL, document.baseURI)
  return new URL(`${LOCAL_ASSET_ROOT}/${name}/`, applicationRoot).href
}

export function createLocalPdfDocumentSource(url: string): LocalPdfDocumentSource {
  return {
    url,
    cMapUrl: localAssetDirectory("cmaps"),
    cMapPacked: true,
    standardFontDataUrl: localAssetDirectory("standard_fonts"),
    iccUrl: localAssetDirectory("iccs"),
    wasmUrl: localAssetDirectory("wasm"),
  }
}

export function loadPdfJs(): Promise<typeof import("pdfjs-dist")> {
  if (!pdfJsPromise) {
    pdfJsPromise = import("pdfjs-dist").then((pdfjs) => {
      pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl
      return pdfjs
    })
  }
  return pdfJsPromise
}
