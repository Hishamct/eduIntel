# Implementation Plan - EduIntel UI Component Library

Implement 10 reusable React components in `src/components/ui/` based on the Stitch **Institutional Components** showcase design system (`EduIntel AI Component Library`).

## Styling & Architecture Decisions

1. **Styling Approach**:
   - `package.json` does not currently include Tailwind CSS.
   - We will implement a dedicated CSS file `src/components/ui/ui.css` containing design tokens (CSS custom properties matching Stitch specs for colors, typography, border-radii, and spacing) and utility classes.
   - Google Fonts (`Space Grotesk`, `IBM Plex Sans`, `IBM Plex Mono`, `Lexend`, `Inter`, `Material Symbols Outlined`) will be imported in `ui.css` and `index.html`.

2. **Component Directory Structure**:
   ```
   frontend/src/components/ui/
   ├── ui.css                 # Design system tokens and component styles
   ├── Sidebar.jsx            # Role-aware, collapsible sidebar navigation
   ├── TopBar.jsx             # Top app bar with search, notifications, profile dropdown
   ├── DataTable.jsx          # Sortable, filterable, paginated high-density data table
   ├── KpiCard.jsx            # Metric/stat card with trend indicator & accent progress
   ├── StatusBadge.jsx        # Solid filled status pill (on-track, needs-attention, flagged-at-risk)
   ├── FormInputs.jsx         # TextField, SelectInput, DatePicker, FileDropzone
   ├── Modal.jsx              # Overlay dialog with close action & button pair
   ├── EmptyState.jsx         # Icon, title, message & optional action button
   ├── ChatBubbles.jsx        # Dual-sender chat message bubble pair
   ├── StudyMaterialCard.jsx  # Card with title, subject tag, file-type icon, date & CTA
   └── index.js               # Barrel export for all UI components
   ```

## Design Specifications & Tokens

- **Background**: `#FAFAF7` (Soft paper)
- **Primary Navy**: `#26415E`
- **Accent Marigold**: `#C97A2B` (Used sparingly for standout CTAs)
- **Text Main**: `#1B2330`
- **Status Colors**:
  - `on-track`: `#3C8C5D`
  - `needs-attention`: `#D9922E`
  - `flagged-at-risk`: `#B23A2E`
  - *Note*: All 3 variants are identical solid filled pills (structurally uniform, differing only in color).
- **Typography**:
  - Headings: `Space Grotesk` / `Lexend`
  - Body: `IBM Plex Sans` / `Inter`
  - Tabular & Numeric: `IBM Plex Mono`

---

## Proposed Changes

### Frontend Component Directory

#### [NEW] [ui.css](file:///home/dell/projects/eduIntel/frontend/src/components/ui/ui.css)
- Define CSS custom properties for palette colors, fonts, spacing, shadows, and clip paths.
- Define styles for interactive components, hover states, badge variants, file dropzone drag states, and modal overlays.

#### [NEW] [Sidebar.jsx](file:///home/dell/projects/eduIntel/frontend/src/components/ui/Sidebar.jsx)
- Props: `userRole`, `navItems`, `activeId`, `onSelect`, `isCollapsed`, `onToggleCollapse`, `onPrimaryAction`.
- Collapsible sidebar supporting 260px (expanded) and 64px (icon-only collapsed) states.

#### [NEW] [TopBar.jsx](file:///home/dell/projects/eduIntel/frontend/src/components/ui/TopBar.jsx)
- Props: `onSearch`, `notificationsCount`, `onNotificationClick`, `userProfile`, `profileMenuItems`.
- Contains search input, bell button with unread counter dot, and interactive profile dropdown menu.

#### [NEW] [DataTable.jsx](file:///home/dell/projects/eduIntel/frontend/src/components/ui/DataTable.jsx)
- Props: `columns`, `data`, `pageSize`, `title`, `actions`.
- Features interactive column sorting, inline column filtering, hover row states, and pagination controls.

#### [NEW] [KpiCard.jsx](file:///home/dell/projects/eduIntel/frontend/src/components/ui/KpiCard.jsx)
- Props: `title`, `value`, `trend`, `trendDirection` ('up' | 'down'), `progressPercent`, `progressColor`.
- Displays headline numeric figures, trend indicators, and bottom accent progress bars.

#### [NEW] [StatusBadge.jsx](file:///home/dell/projects/eduIntel/frontend/src/components/ui/StatusBadge.jsx)
- Props: `variant` ('on-track' | 'needs-attention' | 'flagged-at-risk'), `label`.
- Solid filled pills matching exact Stitch hex colors (`#3C8C5D`, `#D9922E`, `#B23A2E`).

#### [NEW] [FormInputs.jsx](file:///home/dell/projects/eduIntel/frontend/src/components/ui/FormInputs.jsx)
- Exports `TextField`, `SelectInput`, `DatePicker`, `FileDropzone`.
- FileDropzone supports active drag-and-drop state, file format requirements, and file selection.

#### [NEW] [Modal.jsx](file:///home/dell/projects/eduIntel/frontend/src/components/ui/Modal.jsx)
- Props: `isOpen`, `onClose`, `title`, `description`, `icon`, `primaryLabel`, `onPrimary`, `secondaryLabel`, `onSecondary`, `footerNote`.
- Includes backdrop blur, keyboard ESC detection, close button, and primary/secondary CTA pair.

#### [NEW] [EmptyState.jsx](file:///home/dell/projects/eduIntel/frontend/src/components/ui/EmptyState.jsx)
- Props: `icon`, `title`, `message`, `actionLabel`, `onAction`.
- Dotted container icon display with message text and CTA.

#### [NEW] [ChatBubbles.jsx](file:///home/dell/projects/eduIntel/frontend/src/components/ui/ChatBubbles.jsx)
- Props: `messages` (array of message objects with sender role, text, timestamp, avatar/icon).
- Displays visually distinct student vs. institution chat bubbles.

#### [NEW] [StudyMaterialCard.jsx](file:///home/dell/projects/eduIntel/frontend/src/components/ui/StudyMaterialCard.jsx)
- Props: `title`, `subject`, `fileType`, `date`, `fileSize`, `onDownload`, `onView`.
- Displays subject tag badge, file format icon (PDF/DOCX/Video/Slide), metadata, and action buttons.

#### [NEW] [index.js](file:///home/dell/projects/eduIntel/frontend/src/components/ui/index.js)
- Barrel export file for convenient imports (`import { Sidebar, TopBar, DataTable, ... } from './components/ui'`).

#### [MODIFY] [index.html](file:///home/dell/projects/eduIntel/frontend/index.html)
- Add Google Fonts stylesheet link for `Space Grotesk`, `IBM Plex Sans`, `IBM Plex Mono`, `Lexend`, `Inter`, and `Material Symbols Outlined`.

---

## Verification Plan

### Automated Verification
- Run `npm run build` inside `frontend/` to ensure all React JSX components syntax-check and compile cleanly.

### Manual Verification
- Review resulting directory layout under `src/components/ui/`.
- Ensure all 10 requested components are modular, properly typed/propped, and match the specified color palette and design system.
