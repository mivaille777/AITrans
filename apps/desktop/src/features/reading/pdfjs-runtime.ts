const PDFJS_VERSION = "6.3.289"
const PDFJS_WORKER_URL = `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${PDFJS_VERSION}/pdf.worker.min.mjs`

let pdfJsPromise: Promise<typeof import("pdfjs-dist")> | null = null

export function loadPdfJs(): Promise<typeof import("pdfjs-dist")> {
  if (!pdfJsPromise) {
    pdfJsPromise = import("pdfjs-dist").then((pdfjs) => {
      pdfjs.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_URL
      return pdfjs
    })
  }
  return pdfJsPromise
}
