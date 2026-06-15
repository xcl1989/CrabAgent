# Layout Patterns

8 battle-tested slide layouts. Mix and vary them across your deck — never repeat the same layout on consecutive slides.

## Slide Dimensions

- Standard 16:9: **10in wide × 5.625in tall**
- Safe margins: 0.5in from all edges
- Usable area: ~9in × ~4.6in

---

## 1. Title Slide (Dark Background)

```
┌─────────────────────────────────────┐
│  [DARK BACKGROUND - full slide]     │
│                                     │
│         MAIN TITLE (44pt)           │
│         Subtitle (20pt)             │
│                                     │
│         [Accent shape/bar]          │
└─────────────────────────────────────┘
```

| Element | x | y | width | height | Props |
|---------|---|---|-------|--------|-------|
| Background shape | 0 | 0 | 10 | 5.625 | background=primary color |
| Title text | 1.0 | 2.0 | 8.0 | 1.2 | size=44, bold, color=white |
| Subtitle text | 1.0 | 3.2 | 8.0 | 0.6 | size=20, color=secondary |

---

## 2. Section Divider (Dark Background)

```
┌─────────────────────────────────────┐
│  [DARK BACKGROUND]                  │
│                                     │
│  01  Section Title (36pt)           │
│      Brief description (14pt)       │
│                                     │
└─────────────────────────────────────┘
```

| Element | x | y | width | height | Props |
|---------|---|---|-------|--------|-------|
| Background shape | 0 | 0 | 10 | 5.625 | background=primary color |
| Number "01" | 0.8 | 2.0 | 1.5 | 1.0 | size=48, bold, color=accent |
| Section title | 2.3 | 2.1 | 6.5 | 0.8 | size=36, bold, color=white |
| Description | 2.3 | 3.0 | 6.5 | 0.5 | size=14, color=secondary |

---

## 3. Two-Column (Text + Visual)

```
┌─────────────────────────────────────┐
│  Slide Title (36pt)                 │
│─────────────────────────────────────│
│                  │                  │
│  Body text       │   [Shape/Image]  │
│  or bullet       │   or chart       │
│  points          │                  │
│                  │                  │
└─────────────────────────────────────┘
```

| Element | x | y | width | height | Props |
|---------|---|---|-------|--------|-------|
| Title | 0.5 | 0.3 | 9.0 | 0.8 | size=36, bold |
| Left text | 0.5 | 1.4 | 4.2 | 3.5 | size=16 |
| Right visual area | 5.0 | 1.4 | 4.5 | 3.5 | (shape/image/chart) |

---

## 4. Icon + Text Rows

```
┌─────────────────────────────────────┐
│  Slide Title (36pt)                 │
│─────────────────────────────────────│
│  ⬤  Header 1          Description 1 │
│  ⬤  Header 2          Description 2 │
│  ⬤  Header 3          Description 3 │
└─────────────────────────────────────┘
```

| Element | x | y | width | height | Props |
|---------|---|---|-------|--------|-------|
| Title | 0.5 | 0.3 | 9.0 | 0.8 | size=36, bold |
| Icon circle 1 | 0.5 | 1.5 | 0.5 | 0.5 | shape=oval, background=accent |
| Header 1 | 1.2 | 1.4 | 3.0 | 0.4 | size=18, bold |
| Desc 1 | 1.2 | 1.8 | 7.5 | 0.4 | size=14 |
| Icon circle 2 | 0.5 | 2.5 | 0.5 | 0.5 | shape=oval, background=accent |
| Header 2 | 1.2 | 2.4 | 3.0 | 0.4 | size=18, bold |
| Desc 2 | 1.2 | 2.8 | 7.5 | 0.4 | size=14 |
| (repeat for row 3...) | | | | | |

---

## 5. Big Number / KPI Callout

```
┌─────────────────────────────────────┐
│  Slide Title (36pt)                 │
│─────────────────────────────────────│
│    ┌────────┐  ┌────────┐           │
│    │  98%   │  │ 2.5M   │           │
│    │ (72pt) │  │ (72pt) │           │
│    │ Label  │  │ Label  │           │
│    └────────┘  └────────┘           │
│    ┌────────┐  ┌────────┐           │
│    │  340K  │  │  15x   │           │
│    └────────┘  └────────┘           │
└─────────────────────────────────────┘
```

| Element | x | y | width | height | Props |
|---------|---|---|-------|--------|-------|
| Title | 0.5 | 0.3 | 9.0 | 0.8 | size=36, bold |
| KPI 1 number | 0.5 | 1.5 | 4.0 | 1.2 | size=72, bold, color=primary |
| KPI 1 label | 0.5 | 2.8 | 4.0 | 0.5 | size=14, muted |
| KPI 2 number | 5.2 | 1.5 | 4.0 | 1.2 | size=72, bold, color=accent |
| KPI 2 label | 5.2 | 2.8 | 4.0 | 0.5 | size=14, muted |
| KPI 3 number | 0.5 | 3.5 | 4.0 | 1.2 | size=72, bold, color=primary |
| KPI 3 label | 0.5 | 4.8 | 4.0 | 0.5 | size=14, muted |

---

## 6. Comparison (Two Sides)

```
┌─────────────────────────────────────┐
│  Slide Title (36pt)                 │
│─────────────────────────────────────│
│   LEFT COLUMN   │   RIGHT COLUMN    │
│   [Color A]     │   [Color B]       │
│   • Point 1     │   • Point 1       │
│   • Point 2     │   • Point 2       │
│   • Point 3     │   • Point 3       │
└─────────────────────────────────────┘
```

| Element | x | y | width | height | Props |
|---------|---|---|-------|--------|-------|
| Title | 0.5 | 0.3 | 9.0 | 0.8 | size=36, bold |
| Left header | 0.5 | 1.4 | 4.2 | 0.6 | size=22, bold, background=secondary |
| Left content | 0.5 | 2.1 | 4.2 | 3.0 | size=16 |
| Right header | 5.3 | 1.4 | 4.2 | 0.6 | size=22, bold, background=accent |
| Right content | 5.3 | 2.1 | 4.2 | 3.0 | size=16 |

---

## 7. Timeline / Process Flow

```
┌─────────────────────────────────────┐
│  Slide Title (36pt)                 │
│─────────────────────────────────────│
│                                     │
│  ●──────●──────●──────●            │
│  Step1  Step2  Step3  Step4        │
│  Desc1  Desc2  Desc3  Desc4        │
│                                     │
└─────────────────────────────────────┘
```

| Element | x | y | width | height | Props |
|---------|---|---|-------|--------|-------|
| Title | 0.5 | 0.3 | 9.0 | 0.8 | size=36, bold |
| Step 1 circle | 0.8 | 2.0 | 0.6 | 0.6 | shape=oval, background=primary |
| Step 1 number | 0.8 | 2.0 | 0.6 | 0.6 | size=20, bold, color=white (centered) |
| Step 1 title | 0.4 | 2.8 | 2.0 | 0.5 | size=16, bold (centered) |
| Step 1 desc | 0.4 | 3.3 | 2.0 | 0.8 | size=12 (centered) |
| Connector line | 1.7 | 2.3 | 1.8 | 0.03 | background=secondary |
| Step 2 circle | 3.2 | 2.0 | 0.6 | 0.6 | shape=oval, background=primary |
| (repeat pattern...) | | | | | |

---

## 8. Closing Slide (Dark Background)

```
┌─────────────────────────────────────┐
│  [DARK BACKGROUND]                  │
│                                     │
│         Thank You (44pt)            │
│         Contact info (16pt)         │
│                                     │
│         [Q&A / Next steps]          │
└─────────────────────────────────────┘
```

| Element | x | y | width | height | Props |
|---------|---|---|-------|--------|-------|
| Background shape | 0 | 0 | 10 | 5.625 | background=primary color |
| "Thank You" | 1.0 | 1.8 | 8.0 | 1.2 | size=44, bold, color=white |
| Contact info | 1.0 | 3.2 | 8.0 | 0.6 | size=16, color=secondary |

---

## Tips

- **Vary layouts**: Never use the same layout for more than 2 consecutive slides
- **Consistent motif**: Pick one visual element (e.g., circles around icons) and repeat across all slides
- **Breathing room**: Don't fill every inch — empty space improves readability
- **Text box padding**: When aligning shapes with text, account for ~0.1in text box internal padding
