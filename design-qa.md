# AITrans Chat UI design QA

Date: 2026-09-17

## Reference targets

- Chat workspace reference: `C:/Users/huaqi/AppData/Local/Temp/codex-clipboard-7eee61dc-68df-48a6-a033-eca41ad5fd2c.png`
- Knowledge toggle reference: `C:/Users/huaqi/AppData/Local/Temp/codex-clipboard-e7915a70-8a76-4699-a2e7-67713719b98e.png`
- Knowledge scope reference: `C:/Users/huaqi/AppData/Local/Temp/codex-clipboard-8c7acffd-f1c9-46f5-9d83-62e5139de4e7.png`

## Implemented surface

- Preview route: `http://127.0.0.1:4173/#/chat`
- Desktop structure: conversation history / primary chat / context inspector.
- Visual language: white canvas, black primary controls, gray dividers, neutral pills, compact uppercase section eyebrows, and no cyan/amber primary accents.
- Preserved interactions: new chat, conversation search/open/rename/delete, General/Reading context switching, Knowledge switch, Knowledge scope open/close, document selection, Cancel, Apply, message edit/resend, regenerate/retry, stop, and send.
- Global navigation remains Translation-free, keeps the unified sidebar, and keeps the collapse/expand control without bottom profile/login information.

## Browser verification

- Chrome preview opened at the Chat route and visually checked at desktop width.
- Three-column layout, left search/header, center conversation header/composer, right context sections, and neutral Knowledge empty state were visible.
- Browser console errors and warnings: none reported by the preview session.
- The local preview had no live conversation/document records, so the empty conversation and empty Knowledge states were used for the visual pass. Populated message/source cards use the same semantic classes and retain the existing runtime data path.

## Automated verification

- `npm run typecheck:test` passed.
- `npm run lint` passed; only pre-existing Reading/PDF warnings remain.
- `npm test -- --run` passed: 70 files, 284 tests.
- `npm run build` passed, including the PDF.js offline guard and bundle report.
