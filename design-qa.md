# AITrans Chat UI design QA

Date: 2026-09-17

## Reference targets

- Chat workspace reference: `C:/Users/huaqi/AppData/Local/Temp/codex-clipboard-7eee61dc-68df-48a6-a033-eca41ad5fd2c.png`
- Knowledge toggle reference: `C:/Users/huaqi/AppData/Local/Temp/codex-clipboard-e7915a70-8a76-4699-a2e7-67713719b98e.png`
- Knowledge scope reference: `C:/Users/huaqi/AppData/Local/Temp/codex-clipboard-8c7acffd-f1c9-46f5-9d83-62e5139de4e7.png`
- Compact conversation list reference: `C:/Users/huaqi/AppData/Local/Temp/codex-clipboard-4e801f38-8721-4997-ba7a-da61cf9a9903.png`
- Conversation context-menu reference: `C:/Users/huaqi/AppData/Local/Temp/codex-clipboard-a7db3af4-3e8e-4582-a1ef-da175c3bccbf.png`

## Implemented surface

- Preview route: `http://127.0.0.1:4173/#/chat`
- Desktop structure: conversation history / primary chat / context inspector.
- Visual language: white canvas, black primary controls, gray dividers, neutral pills, compact uppercase section eyebrows, and no cyan/amber primary accents.
- Preserved interactions: new chat, conversation search/open/rename/delete, General/Reading context switching, Knowledge switch, Knowledge scope open/close, document selection, Cancel, Apply, message edit/resend, regenerate/retry, stop, and send.
- Compact history rows now expose only the conversation title, updated time, and one-line summary. Reading/General/model pills and persistent Rename/Delete controls are hidden.
- Right-clicking a conversation opens the white grouped context menu; Rename and permanent delete use the existing API, Pin/Unread are interactive local list states, and Share/Copy use the clipboard. Unsupported Project/Section/Branch operations are visibly disabled instead of pretending to persist.
- Global navigation remains Translation-free, keeps the unified sidebar, and keeps the collapse/expand control without bottom profile/login information.

## Browser verification

- Chrome preview opened at the Chat route and visually checked at desktop width.
- Three-column layout, left search/header, center conversation header/composer, right context sections, and neutral Knowledge empty state were visible.
- Browser console errors and warnings: none reported by the preview session.
- The local preview had no live conversation/document records, so the empty conversation and empty Knowledge states were used for the visual pass. Populated message/source cards use the same semantic classes and retain the existing runtime data path.
- The populated context-menu state was verified with `ConversationHistoryPanel.test.tsx` because the local preview had no persisted conversation rows to right-click.

## Automated verification

- `npm run typecheck:test` passed.
- `npm run lint` passed; only pre-existing Reading/PDF warnings remain.
- `npm test -- --run` passed: 71 files, 285 tests.
- `npm run build` passed, including the PDF.js offline guard and bundle report.

## Final result

final result: passed
