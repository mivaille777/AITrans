import type { MouseEventHandler, PointerEventHandler, ReactNode } from "react"

type OverlayWindowShellProps = {
  contextId: string
  nearCursor: boolean
  onBackgroundPointerDown: PointerEventHandler<HTMLElement>
  onContextMenu: MouseEventHandler<HTMLElement>
  children: ReactNode
  menu?: ReactNode
}

export default function OverlayWindowShell({
  contextId,
  nearCursor,
  onBackgroundPointerDown,
  onContextMenu,
  children,
  menu,
}: OverlayWindowShellProps) {
  return (
    <main
      className="ait-overlay-root h-screen w-screen overflow-hidden bg-transparent text-slate-100"
      onContextMenu={onContextMenu}
      onPointerDown={onBackgroundPointerDown}
    >
      <section
        data-overlay-context-id={contextId}
        className={`ait-overlay-shell flex h-full flex-col overflow-hidden rounded-[24px] border border-white/10 shadow-2xl ${
          nearCursor ? "ait-overlay-near-enter" : ""
        }`}
      >
        {children}
      </section>
      {menu}
    </main>
  )
}
