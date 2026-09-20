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

---

# AITrans Settings independent scrolling QA

Date: 2026-09-18

## Interaction target

- Settings right column scrolls independently with the mouse wheel.
- The left Settings navigation stays fixed while the right content moves.
- The active navigation item follows the section crossing the top activation line and selects Advanced at the scroll boundary.
- The right column uses a thin neutral scrollbar that matches the monochrome token system.

## Browser evidence

- Preview: `http://127.0.0.1:5173/#/settings` in Chrome at 1707×925 CSS pixels.
- Before the route fix, the Settings route wrapper expanded to 1687px and the right column had no scroll range.
- After marking `/settings` as an internal-scroll route, the right column measured `clientHeight=881`, `scrollHeight=1687`, and reached `scrollTop=806` at the bottom.
- Wheel scrolling moved the right column while the left navigation remained in place; the active item changed to Browser integration mid-scroll and Advanced at the bottom.
- Clean reload starts at the top with General active.

## Automated verification

- `npm exec tsc -- --noEmit` passed.
- `npm run typecheck:test` passed.
- `npm run lint` passed with only existing non-Settings warnings.
- `npx vitest run src/features/settings` passed: 1 file, 4 tests.
- `npm run build` passed, including the PDF.js offline guard and bundle report.
- Chrome preview console errors: none returned during the verification.

## Final result

final result: passed

---

# AITrans Settings reference rebuild QA

Date: 2026-09-18

## Comparison targets

- Source visual target: `C:/Users/huaqi/AppData/Local/Temp/codex-clipboard-a8a305bd-9648-4a88-bcd9-9c04f0559b93.png` (1586×992 source pixels; desktop Settings reference).
- Implementation: `http://127.0.0.1:5173/#/settings` in the user Chrome preview tab `1029376118` (1707×926 CSS pixels, density 1; browser-rendered screenshot captured inline during this pass).

## State and evidence

- Fresh Settings load with General selected, local runtime enabled, the active provider model loaded, available-model probe completed, browser bridge disconnected, and local model storage path visible.
- Full-view comparison checked the black workspace rail, secondary Settings navigation, right-aligned mantra, section separators, row controls, monochrome palette, and sticky bottom actions.
- Focused interaction states checked: AI model connection drawer, Browser integration drawer, Research data/model manager drawer, Advanced controls drawer, Escape close, category scroll positioning, model catalog loading, and browser console errors.
- The reference and implementation use different desktop aspect ratios, so the comparison was normalized by CSS layout regions rather than raw pixel coordinates. No source imagery is present; all visible marks use the existing Lucide icon library.

## Findings and fixes

- [P2, fixed] The Settings content column now owns its scroll range, and active navigation is derived from a stable top activation line rather than intersection timing. General remains active at the top, section labels follow wheel scrolling, and Advanced is selected at the bottom boundary.
- [P3, accepted] The existing global workspace rail keeps AITrans' real routes (Chat, Translation, Reading, Research, Knowledge, Agent) instead of the reference's illustrative Search, Library, Projects and Insights labels. The Settings surface itself preserves the real app navigation and its existing sidebar behavior; changing those route semantics was outside this Settings-only pass.
- [P3, accepted] Context length, temperature, theme and typography are shown as runtime-managed read-only controls because no corresponding persistence API exists. Provider/API-key/model changes remain fully interactive through the existing settings API and credential vault drawer.

## Required fidelity surfaces

- Typography: black high-weight section titles, compact gray descriptions, uppercase micro-labels, and neutral system font hierarchy match the source direction; long row labels truncate without widening the control column.
- Spacing and layout rhythm: the desktop shell uses the source's dark rail / Settings navigation / content proportions, thin row dividers, right-aligned controls, sticky action bar, and independent content/drawer scrolling.
- Colors and visual tokens: white canvas, #111 primary controls, light gray borders, neutral disabled controls, and green connection/status dot follow the monochrome reference.
- Image quality and asset fidelity: no raster artwork is used; icons come from the existing Lucide library and no visible icon was replaced by a CSS or text approximation.
- Copy and content: supported settings are data-backed; unavailable settings explicitly say they are managed by the runtime rather than presenting fictional editable state.

## Automated verification

- `npx tsc --noEmit` passed.
- `npm run typecheck:test` passed.
- `npm run lint` passed with only existing Reading/Knowledge/Research/Agent warnings.
- `npx vitest run src/features/settings` passed: 1 file, 4 tests.
- `npm run build` passed, including the PDF.js offline guard and bundle report.
- Chrome preview console errors: none returned by the browser connector.

## Final result

final result: passed

---

# AITrans Knowledge inspector overflow fix QA

Date: 2026-09-18

## Comparison targets

- Source visual target: `C:/Users/huaqi/AppData/Local/Temp/codex-clipboard-b1bfc6a4-f750-47a0-8646-97c1214939de.png` (661×1412 focused crop of the Knowledge right inspector).
- Implementation: `http://127.0.0.1:5173/#/knowledge`, Chrome preview at 1707×926 CSS pixels, density 1; focused `.knowledge-inspector-pane` region measured 388×718 CSS pixels in the active preview session.

## State and evidence

- Knowledge → Canvas, AI suggestion inbox visible, the PID research insight selected, four relations rendered.
- Before the fix, the inspector measured `scrollWidth=888` against `clientWidth=383`; relation cards and Edit/Delete controls extended beyond the visible pane.
- After the fix, `scrollWidth=383` equals `clientWidth=383`; the relation card measured 346.7px wide inside the 388px pane, and the Edit control remained inside the pane. The revised Chrome capture showed all relation cards and controls without horizontal clipping.

## Findings and fixes

- [P2, fixed] Long relation titles expanded the grid item's intrinsic width and pushed the relation actions outside the right sidebar. The inspector now has an explicit shrink/overflow boundary, relation-list children are width-constrained, and relation cards cannot exceed the pane.
- [P3, accepted] The supplied source is a focused crop while the implementation evidence is a full desktop capture plus measured inspector region; the comparison was limited to the right inspector state and overflow behavior.

## Required fidelity surfaces

- Typography: existing black/gray hierarchy and compact relation metadata are unchanged.
- Spacing/layout: relation cards now fit the inspector width while preserving existing padding and vertical rhythm.
- Colors/tokens: no token or color changes.
- Image/assets: no image assets are involved in this fix.
- Copy/content: no copy or API data changes.

## Automated verification

- `npm run typecheck:test` passed.
- `npx vitest run src/features/knowledge` passed: 13 files, 51 tests.
- `git diff --check` passed.

## Final result

final result: passed

---

# AITrans Research workspace redesign QA

Date: 2026-09-17

## Comparison targets

- Main visual target: `C:/Users/huaqi/AppData/Local/Temp/codex-clipboard-cf192d01-c870-4535-bd6c-dbfcbcd64bfa.png` (1600×1000).
- Design-system target: `C:/Users/huaqi/AppData/Local/Temp/codex-clipboard-851a82ab-fb64-43c4-ba86-475769360b65.png`.
- Responsive and density regression captures: `C:/Users/huaqi/AppData/Local/Temp/codex-clipboard-dec64022-e449-4348-aba5-b149a9fd4bfd.png` and `C:/Users/huaqi/AppData/Local/Temp/codex-clipboard-5a5d9b85-4814-484f-8f62-d9c671b1768c.png` (original wide capture: 2560×1570).
- Removed legacy surface reference: `C:/Users/huaqi/AppData/Local/Temp/codex-clipboard-d99e420e-58a9-4d7c-8ef1-5359ff30d73a.png`.

## Implementation and evidence

- Preview: `http://127.0.0.1:5173/#/research`.
- Browser-rendered capture: in-app Browser, the same route and empty-data state, checked at 1280×800, 1980×1080, and 2560×1570 CSS viewports (density 1; browser capture is retained in the active preview session).
- Full-view comparison: the dark sidebar, research header/metrics, plan, evidence, writing, activity, and bottom composer remain in the desktop frame; the off-white paper canvas and black/white token system match the provided direction.
- Focused regions compared: empty evidence, new source inventory, draft creation, and the compact agent panel. Focused review was necessary because their density changes by viewport height.

## Findings and fixes

- [P1, fixed] A fixed equal-height grid produced blank card interiors on wide displays; content now uses the available frame while the plan distributes its steps, empty evidence is centered and surfaces a real saved-source shortcut, and the draft form is vertically balanced.
- [P1, fixed] Low-height windows allowed plan/draft content to overrun the composer. Cards now have bounded internal scrolling, reduced short-window spacing, and a compact activity region; 1280×800 keeps the composer visible.
- [P1, fixed] The legacy “Notes & source records” page was removed. Its required read path is condensed into the Evidence card’s Sources view: source search, source metrics, opening the stored locator, and project-scope access remain available. The obsolete ResearchWorkspace, source-profile, and workspace-filter UI modules were deleted.
- [P2, accepted] The active project has zero review entries and no writing project, so live empty/start states are shown instead of reference-only sample evidence.

## Browser verification

- Verified project selection, source/evidence counters, evidence filters/search, Sources ↔ Evidence view switching, stored-source opening, scope access, draft form, document/outline control, and the persistent Research Agent composer.
- Browser console errors and warnings: none in a clean preview session.

## Automated verification

- `npx tsc -b --pretty false` passed.
- `npm run build` passed, including the PDF.js offline guard and bundle report.

## Final result

final result: passed
