---
name: Kinetic Intelligence
colors:
  surface: '#f9f9f9'
  surface-dim: '#dadada'
  surface-bright: '#f9f9f9'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f3f3f3'
  surface-container: '#eeeeee'
  surface-container-high: '#e8e8e8'
  surface-container-highest: '#e2e2e2'
  on-surface: '#1a1c1c'
  on-surface-variant: '#4c4546'
  inverse-surface: '#2f3131'
  inverse-on-surface: '#f1f1f1'
  outline: '#7e7576'
  outline-variant: '#cfc4c5'
  surface-tint: '#5e5e5e'
  primary: '#000000'
  on-primary: '#ffffff'
  primary-container: '#1b1b1b'
  on-primary-container: '#848484'
  inverse-primary: '#c6c6c6'
  secondary: '#5e5e5e'
  on-secondary: '#ffffff'
  secondary-container: '#e1dfdf'
  on-secondary-container: '#626262'
  tertiary: '#000000'
  on-tertiary: '#ffffff'
  tertiary-container: '#1b1b1b'
  on-tertiary-container: '#848484'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#e2e2e2'
  primary-fixed-dim: '#c6c6c6'
  on-primary-fixed: '#1b1b1b'
  on-primary-fixed-variant: '#474747'
  secondary-fixed: '#e4e2e2'
  secondary-fixed-dim: '#c7c6c6'
  on-secondary-fixed: '#1b1c1c'
  on-secondary-fixed-variant: '#464747'
  tertiary-fixed: '#e2e2e2'
  tertiary-fixed-dim: '#c6c6c6'
  on-tertiary-fixed: '#1b1b1b'
  on-tertiary-fixed-variant: '#474747'
  background: '#f9f9f9'
  on-background: '#1a1c1c'
  surface-variant: '#e2e2e2'
typography:
  headline-lg:
    fontFamily: Geist
    fontSize: 32px
    fontWeight: '600'
    lineHeight: '1.2'
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Geist
    fontSize: 24px
    fontWeight: '600'
    lineHeight: '1.2'
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Geist
    fontSize: 18px
    fontWeight: '600'
    lineHeight: '1.4'
  body-lg:
    fontFamily: Geist
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.5'
  body-md:
    fontFamily: Geist
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.5'
  body-sm:
    fontFamily: Geist
    fontSize: 12px
    fontWeight: '400'
    lineHeight: '1.4'
  data-lg:
    fontFamily: JetBrains Mono
    fontSize: 18px
    fontWeight: '500'
    lineHeight: '1'
  data-md:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: '500'
    lineHeight: '1'
  data-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '400'
    lineHeight: '1'
  headline-lg-mobile:
    fontFamily: Geist
    fontSize: 24px
    fontWeight: '600'
    lineHeight: '1.2'
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  base: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 40px
  gutter: 16px
  margin: 24px
---

## Brand & Style

This design system is built for high-stakes decision-making environments. The aesthetic is a fusion of **Minimalism** and **Modern Corporate**, focusing on extreme clarity, data density, and an "authoritative paper" feel. The UI recedes to prioritize information, using white space not just for aesthetics but as a functional separator for complex datasets.

The target audience consists of analysts and operators who require a "cockpit" experience: immediate legibility, zero decorative distraction, and a clear hierarchy of urgency. The emotional response should be one of calm control, precision, and absolute reliability.

## Colors

The palette is strictly functional. The foundation is built on **Pure White (#FFFFFF)** and **Ghost Grey (#F8F8F8)** to simulate a high-grade paper surface. 

- **Primary & Neutral:** Black is reserved for primary text and critical UI anchors. Greys are used for structural borders and secondary metadata.
- **Traffic Light System:** Pure, high-chroma Red, Amber, and Green are used exclusively for status signaling. They must never be used decoratively.
- **Classification Tags:** Soft, low-saturation pastel tints (Blue, Purple, Grey) provide a subtle background for categorizing data without competing with the primary status signals.

## Typography

The typographic system utilizes a dual-font strategy to separate narrative content from technical data.

- **Geist (Sans):** Used for all interface labels, headlines, and instructional text. It provides a modern, neutral, and highly legible tone.
- **JetBrains Mono (Monospace):** Used strictly for metrics, coordinates, timestamps, and technical readouts. The fixed-width nature ensures that shifting numerical values do not cause layout "jitter" and allows for easy vertical scanning of data columns.

All headings use tight tracking and leading to maintain a compact, high-density feel.

## Layout & Spacing

This design system employs a **Fixed Grid** philosophy for desktop layouts to ensure that information appears in the same location for muscle-memory recall. A 12-column system is used with a strict 4px baseline grid.

- **Density:** Padding is intentionally tight (8px-16px) to allow for maximum information "above the fold."
- **Breakpoints:**
  - **Desktop (1440px+):** Full 12-column display with persistent side-panels.
  - **Tablet (768px-1439px):** 8-column display, side-panels collapse into icons.
  - **Mobile (<767px):** 4-column fluid display, technical data stacks vertically.

## Elevation & Depth

To maintain the "paper-like" digital feel, this design system avoids traditional shadows. Depth is communicated through **Tonal Layers** and **Precise Outlines**.

- **Level 0 (Background):** #FFFFFF.
- **Level 1 (Sub-panels/Cards):** #F8F8F8 background with a 1px solid #E5E5E5 border.
- **Active States:** Elements that are focused or active use a 1.5px Black border.
- **Depth:** No blur is used. Instead, "stacking" is visualized by nesting light grey containers within white surfaces, or vice versa. High-density data tables use subtle horizontal dividers (#F0F0F0) rather than alternating row colors.

## Shapes

The shape language is disciplined and geometric. A "Soft" rounding (4px) is applied to primary UI components to prevent the interface from feeling aggressive, but it remains sharp enough to feel professional and technical. 

- **Containers & Inputs:** 4px radius.
- **Action Buttons:** 4px radius.
- **Classification Tags:** 2px radius (near-sharp) to distinguish them from interactive buttons.
- **Status Indicators:** Small circles (8px x 8px) for "traffic light" signals.

## Components

- **Buttons:** Primary buttons are Solid Black with White Geist Medium text. Secondary buttons are Ghost Grey (#F8F8F8) with a 1px border. No gradients or shadows.
- **Data Cards:** White background, 1px grey border, 4px corner radius. Headlines in Geist, primary metrics in JetBrains Mono.
- **Input Fields:** Rectangular with a 1px #D1D1D1 border. On focus, the border thickens to 1.5px Black. Labels are positioned above the field in 11px JetBrains Mono.
- **Status Chips:** Small, high-contrast dots paired with bold label text. Red chips use #E02424, Green chips use #059669.
- **Classification Tags:** Subtle background fills (e.g., #EBF5FF) with slightly darker text of the same hue.
- **Data Tables:** High-density. Header row is #F8F8F8 with JetBrains Mono 11px uppercase labels. Cell text is Geist 14px for strings and JetBrains Mono 14px for numbers.
- **Command Bar:** A persistent, centered floating input for quick actions, styled with a distinct 2px Black border to denote "Global Control."