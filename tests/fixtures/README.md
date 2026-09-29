# Reader test fixtures

Saved pdf.js text layers (`getTextContent` items, plus the page's pictures), one entry
per page. Modules 2 and 3 (re-captured 2026-09-28 with pdf.js 3.11.174, text unchanged) are
`{items, imgs, view, images}`: `imgs` = image paint operations, `view` = page box,
`images` = the transform [a,b,c,d,e,f] at each image paint, so the test can tell a
full-slide background (Module 3's Canva pages) from a real picture. Each has a matching golden file in `tests/golden/`.

| Fixture | What it is |
|---|---|
| `module2-text.json` | Real text layer of IA Module 2 |
| `module3-text.json` | Real text layer of IA Module 3 (every page has one full-slide background image) |
| `synthetic-activity-text.json` | **SYNTHETIC — hand-built, not a real module.** Invented text only (no course content, no personal data). |

## synthetic-activity-text.json

Added 2026-09-28 (approved) because neither real module has an activity slide, so
nothing checked that `setAsideActivities` actually sets activity slides aside.

Six pages, same shape as `module2-text.json` (`{page: {items: [{str, transform}], imgs}}`):

1. cover, 2. divider "SAMPLE MACHINE PARTS", 3–4 and 6. one made-up term each
(Widget, Gadget, Sprocket), 5. **"ACTIVITY 1"**, with the instructions "Answer the questions below in your notebook." / "Submit your answers before Friday.".
The reader makes a term of slide 5; `setAsideActivities` must set it aside.
`tests/golden/synthetic-activity.expected.json` pins both the three kept terms and the
set-aside slide (its `setAside` field).
