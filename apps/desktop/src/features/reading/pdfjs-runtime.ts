import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url"

let pdfJsPromise: Promise<typeof import("pdfjs-dist")> | null = null

export function loadPdfJs(): Promise<typeof import("pdfjs-dist")> {
  if (!pdfJsPromise) {
    pdfJsPromise = import("pdfjs-dist").then((pdfjs) => {
      pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl
      return pdfjs
    })
  }
  return pdfJsPromise
}
