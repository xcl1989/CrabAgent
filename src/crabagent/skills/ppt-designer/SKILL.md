---
name: ppt-designer
description: "Create visually compelling PowerPoint presentations with professional design. Includes color palettes, typography rules, layout patterns, and a QA workflow. Use when the user asks to create slides, decks, presentations, pitch decks, or wants to convert content into a polished .pptx file."
---

# PPT Designer Skill

You are now operating with the PPT Designer skill. Create beautiful, professional PowerPoint presentations using CrabAgent's built-in Office tools.

## Quick Reference

| Task | Tool |
|------|------|
| Create empty .pptx | `office_create(file_path)` |
| Add a slide | `office_edit(command="add", element_type="slide")` |
| Add text/shape on a slide | `office_edit(command="add", element_path="/slide[N]", element_type="shape")` |
| Modify element | `office_edit(command="set", element_path="/slide[N]/shape[M]", props={...})` |
| Add a table | `office_edit(command="add", element_path="/slide[N]", element_type="table")` |
| Add a chart | `office_edit(command="add", element_path="/slide[N]", element_type="chart")` |
| Query element structure | `office_query(file_path, path_or_selector="/slide[N]")` |
| Render HTML preview | `office_render(file_path)` |

## Workflow

### Step 1: Plan the Deck

Before touching any tools, decide:

1. **Topic & audience** — What is this about? Who will see it?
2. **Color palette** — Pick ONE palette from [references/color-palettes.md](references/color-palettes.md). Commit to it for every slide.
3. **Font pairing** — Pick ONE header font + ONE body font from [references/typography.md](references/typography.md).
4. **Visual motif** — Pick ONE distinctive element (rounded frames, icons in circles, thick borders) and repeat it across slides.
5. **Slide structure** — Outline all slides. Each slide needs a purpose.

### Step 2: Create and Build

```
1. office_create("presentation.pptx")
2. office_edit → add slide → add shapes → set text/colors/fonts
3. Repeat for each slide
4. office_render → inspect the preview
```

**Slide dimensions:** Standard 16:9 (10in × 5.625in). All positioning uses inches.

**Coordinate system:**
- `x` = horizontal offset from left edge (inches)
- `y` = vertical offset from top edge (inches)
- `width`, `height` = element size (inches)

### Step 3: QA (Required)

**Your first render is almost never correct.** Treat QA as a bug hunt.

1. Call `office_render(file_path)` to get HTML preview
2. Inspect the rendered output critically
3. Check for:
   - Text overflow or cutoff
   - Overlapping elements
   - Insufficient margins (< 0.5")
   - Low contrast (light text on light background)
   - Inconsistent spacing between elements
   - Leftover placeholder text
4. Fix issues with `office_edit(command="set", ...)`
5. Re-render and verify
6. **Do not declare success until you've completed at least one fix-and-verify cycle**

---

## Design Principles

### Color — Bold and Intentional

Read [references/color-palettes.md](references/color-palettes.md) for 10 ready-to-use palettes.

**Rules:**
- ONE color dominates (60-70% visual weight), 1-2 supporting tones, one sharp accent
- Dark backgrounds for title + conclusion slides, light for content ("sandwich" structure)
- NEVER default to generic blue — pick colors that reflect the specific topic
- NEVER use `#` prefix in hex color values passed to `office_edit` props

### Typography — Hierarchy and Contrast

Read [references/typography.md](references/typography.md) for font pairings and size guides.

**Rules:**
- Pick a header font WITH personality, pair with a CLEAN body font
- Title: 36-44pt bold
- Section header: 20-24pt bold
- Body text: 14-16pt
- Captions: 10-12pt muted
- NEVER center body text — left-align paragraphs and lists; center only titles

### Layout — Every Slide Needs a Visual Element

Read [references/layout-patterns.md](references/layout-patterns.md) for 8 layout templates.

**Text-only slides are forgettable.** Every slide needs an image, chart, icon, or shape.

**Preferred layouts:**
- Two-column (text left, illustration right)
- Icon + text rows (icon in colored circle, bold header, description below)
- 2×2 or 2×3 grid (image on one side, grid of content blocks)
- Half-bleed image (full left or right side) with content overlay
- Large stat callouts (big numbers 60-72pt with small labels below)
- Comparison columns (before/after, pros/cons)
- Timeline or process flow (numbered steps, arrows)

**Spacing:**
- 0.5" minimum margins from slide edges
- 0.3-0.5" between content blocks
- Leave breathing room — don't fill every inch
- Choose 0.3" or 0.5" gaps and use consistently

### Common Mistakes to Avoid

- ❌ Repeating the same layout on every slide — vary columns, cards, and callouts
- ❌ Defaulting to blue — choose colors that match the topic
- ❌ Mixing spacing randomly — pick one gap size and use it consistently
- ❌ Styling one slide nicely but leaving the rest plain — commit fully
- ❌ Creating text-only slides — always add visual elements
- ❌ Using accent lines under titles — this is a hallmark of AI-generated slides; use whitespace or background color instead
- ❌ Low-contrast elements — icons AND text need strong contrast against backgrounds
