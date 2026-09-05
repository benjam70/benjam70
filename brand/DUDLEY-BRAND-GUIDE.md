# Dudley UI / Brand Guide

## Product feel

Dudley is a payment-investigation deputy, not a generic chatbot and not a static analytics dashboard.

The product should feel:
- curious
- methodical
- human
- sharp
- approachable
- trustworthy with real-money investigations

Avoid making Dudley look:
- cyberpunk / neon purple
- sterile enterprise software
- cartoonish or childish
- grim noir / fraud-police software
- like a generic AI assistant

## Core palette

- Navy `#0B2540` — primary brand / structure
- Teal `#00C6B8` — Dudley active state / primary accent
- Aqua `#7EE3E3` — secondary accent / highlights
- Cream `#FAF7EE` — warm light surfaces / brand presentations
- Sand `#EBDCC6` — Dudley coat / soft supporting accent
- Slate `#64748B` — secondary text / inactive UI

## Dark command-center surfaces

- App background `#071724`
- Sidebar `#082033`
- Panel `#0E2436`
- Secondary panel `#122C40`
- Border `#1C3B50`
- Primary text `#F7FAFC`
- Muted text `#94A3B8`
- Input surface `#102A3D`

## Status semantics

Color should mean something.

- Teal `#00C6B8` — Dudley is actively working / selected / live
- Green `#10B981` — completed / confirmed / successful
- Amber `#F59E0B` — needs attention / approval / unresolved warning
- Red `#EF4444` — failed transaction / contradiction / error
- Blue `#38BDF8` — neutral information

Do not use green as decoration. Do not use red unless something has actually failed or conflicts.

## Recommended UI structure

### Left
Cases / investigations only:
- New investigation
- Active / recent cases
- Connected systems
- Settings

Keep this narrow and collapsible.

### Center
The main Dudley conversation:
- human prompt
- Dudley findings
- follow-up questions
- persistent case context

Below the conversation:
- Investigation activity
- observable tool actions only
- approvals when needed

### Right
Evidence desk with tabs:
- Evidence
- Payment
- Logs
- Browser
- Files

This pane should show what Dudley is looking at while he investigates.

## Logo system

Primary current direction:
- full-body Dudley leaning on a strong navy D
- beige trench coat
- navy hat with teal band
- friendly, intelligent expression
- relaxed posture
- no magnifying glass
- no exaggerated cartoon styling

Use the included transparent PNG assets as visual reference.

For small UI use, use the 24–32 px versions only if the full-body mark remains readable. If not, create a separate simplified mark rather than redesigning the full logo.

## Typography

Use a clean modern sans for product UI. Good defaults:
- Inter
- Geist
- SF Pro
- Segoe UI

Use handwritten-style accent copy only in brand/marketing surfaces, not core investigation UI.

## Copy tone

Dudley should sound like a capable colleague:
- concise
- calm
- slightly dry
- never robotic
- never overconfident
- evidence-first

Good:
> I found the refund attempt, but I wouldn't call it successful yet.

Avoid:
> Analysis complete. Transaction anomaly detected.

## Do not change the investigation engine

This style pack is presentation-only.

Do not alter:
- payment investigation logic
- MCPs
- Coralogix behavior
- payment evidence rules
- case history
- prompts/controllers
- workspace data

The UI should expose the existing engine, not reinterpret it.
