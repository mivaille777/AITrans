# Chat UI reference refactor — visual QA

**Findings**

No actionable P0/P1/P2 findings remain within the user-confirmed scope. The independent right context/run inspector is retained, and only existing product functions are exposed. This is a reference-guided refactor of the existing application, not a replacement of its data or desktop runtime.

**Comparison target and evidence**

- Source visual truth: `C:/Users/huaqi/Desktop/AITrans本地资料库对话界面.png`; actual image dimensions: 1586 × 992 px.
- Implementation: `http://127.0.0.1:5173/#/chat?conversation=f7dcad4ec8b944ae86463501ed3ce772`.
- Final desktop capture: `D:/AITrans/.cache/chat-ui/final-desktop.png`; 1588 × 992 px, CSS viewport 1588 × 992, devicePixelRatio 1. Source density is unspecified; its dimensions are treated as the desktop target. No density scaling was applied. The two-pixel width difference is insignificant and appears as blank padding in the comparison canvas.
- Full-view evidence: `D:/AITrans/.cache/chat-ui/comparison-desktop.png`, source on the left and implementation on the right. Both original images were also inspected together in the same tool input.
- Focused evidence: `D:/AITrans/.cache/chat-ui/comparison-message.png` (source left, implementation right), and `D:/AITrans/.cache/chat-ui/comparison-composer.png` (source above, implementation below). Crops come from the actual reference and final capture. Browser capture uses JPEG compression, so screenshot sharpness is not evidence of a different rendered font.
- State: light theme, selected persisted conversation “本地资料库有哪些内容？”, scrolled to the Measurement chapter question and its stored answer. Right inspector open, no popup/dialog open, draft empty. Content is read from the local backend. Conversation history metadata, current source counts and message controls reflect the existing application. The screenshot's data was not copied into runtime state.
- Responsive evidence: `D:/AITrans/.cache/chat-ui/phone-final.png` at 390 × 800. Additional rendered checks at 1280 × 800, 1024 × 768 and 640 × 800. Temporary viewport override was reset after QA; preview tab remains open. `final-preview.jpg` records the default preview viewport.

**Required fidelity surfaces**

- Fonts/typography: retained the existing Windows/Segoe UI font stack and CJK fallback. Main heading 25 px/700; history title 14 px/650; answer text 16 px/400 with 28.8 px line height. Bold chapter headings, muted blue body copy and cyan citation labels follow the reference hierarchy. The narrower answer wrapping is expected with the user-retained right inspector. History titles truncate within their column; message content wraps without horizontal page overflow.
- Spacing/layout rhythm: distinct rounded history, conversation and inspector panels on a pale canvas, 12 px panel gaps, dark global navigation, compact toolbar above the unified input/send row. Removed the redundant workspace title header. History, messages and inspector scroll independently; composer remains visible. Small windows use an independent inspector drawer; phone layout stacks bounded history above chat and keeps existing navigation available.
- Colors/tokens: dark sidebar `#101211`, user bubble `#191c1a`, assistant body `#405c87`, strong text `#233e69`, pale borders `#e7ebf2`/`#edf0f5`, cyan citation foreground `#159bce`. Active, disabled and focus states remain distinct. Styles are scoped to the chat route.
- Image quality/assets: reference contains interface text and line icons rather than photographic assets. Existing product branding and the existing Lucide library are retained; the assistant avatar uses its Bot icon. No screenshot is used as a rendered UI, and no generated or placeholder imagery was introduced. Browser-capture compression is confined to QA artifacts.
- Copy/content: retained real conversation, citation, model, knowledge and run data. Removed the unsupported slash-command hint and decorative attachment affordance. History falls back to the real conversation type because the current summary API has no last-message preview. Send/stop, model selection, context selection, knowledge scope, citation details and tool review use existing handlers.

**Intentional product constraints**

- User answered “1.不用。2，只重构已有的功能”: do not move the independent context/run inspector into the top Sources block; limit changes to existing capabilities.
- Inspector width reduces the center column relative to the supplied screenshot. This approved structure causes different line wrapping and visible answer depth.
- Existing desktop titlebar and window controls remain. The reference's thinner chrome and top icon row do not define new app functions.
- Sources retain the existing answer-associated behavior. No attachment, microphone, voice or slash-command feature is added.
- Existing edit/resend controls and real retrieval metadata remain, so the displayed message is not pixel-identical to the static reference.

**Comparison history and resolved findings**

1. Initial empty-state capture could not support a populated-state comparison; the backend was started and the existing reference conversation loaded. The initial report remained blocked until scope and populated-state evidence were available.
2. [P1] Composer clipping: chat route frame did not establish a bounded flex layout. Added full-height/min-height-zero flex framing and bounded chat grid rows. Final desktop capture shows the complete toolbar and input/send row.
3. [P2] Typography and inspector density: initial answer text and small controls lacked the reference hierarchy; right inspector had duplicated run padding. Applied scoped font sizes, blue body/strong text, citation styling and single inspector padding. Focused message/composer evidence shows the corrected hierarchy.
4. [P2] Narrow navigation hidden: existing global media styles hid navigation while retaining its grid track. Restored a compact horizontal navigation row specifically for the chat shell. Phone-final capture shows visible navigation and usable chat content.
5. [P2] Phone horizontal overflow: existing global message width overrides expanded the assistant card beyond its avatar margin. Scoped mobile maximum widths to the available space. Post-fix DOM check: message clientWidth = scrollWidth = 356 px at a 390 px viewport; page width = 390 px.
6. Final full-view and focused comparisons found no additional actionable P0/P1/P2 drift within the agreed scope. Final browser console check returned no errors or warnings.

**Interaction and regression validation**

- Opened the persisted conversation, searched history including no-match state, and cleared the filter.
- Closed/reopened the right inspector; existing draft survived the switch. Cleared the draft without sending a live LLM request.
- Opened conversation actions and closed with Escape; opened Tools/model menus, citation [42] details and knowledge-scope dialog.
- Checked independent inspector drawer behavior and responsive navigation/composer at desktop, intermediate and phone widths.
- 7 test files / 36 tests passed across companion, history, layout, retrieval controls, workspace and evidence.
- `npm run typecheck:test` and `npm run build` passed, including the PDF.js offline guard.
- Full lint completed with pre-existing warnings elsewhere; targeted lint of edited TSX files passed with no warnings. `git diff --check` passed.
- Existing automated tests cover send/stop/streaming, Chinese IME and failure states. Manual QA did not create a new model completion or modify knowledge data.

**Open Questions**

None required for the agreed refactor.

**Follow-up Polish**

- [P3] Reference-style last-message previews would require additional API data; conversation-type fallback is retained for this UI-only scope.
- [P3] Further visual tuning can be assessed with the user's actual Electron window dimensions, where native chrome and text antialiasing differ from browser capture.

**Implementation Checklist**

- [x] Retain independent inspector and existing functional scope.
- [x] Compare reference and rendered populated chat together, including focused regions.
- [x] Resolve clipping, responsive overflow and typography findings; recapture.
- [x] Verify existing interactions and required regression checks.
- [x] Keep local preview running/open; reset temporary viewport override.

final result: passed
