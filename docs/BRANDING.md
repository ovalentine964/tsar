# TSAR — Branding & Icon Guide

## Brand Identity

**TSAR** — *Trading Super Agent for Returns*

An autonomous AI-powered crypto trading superagent. The name evokes the Russian emperor — a sovereign ruler with absolute authority. In the context of TSAR, the AI is sovereign over market decisions, exercising precision and intelligence on behalf of the user.

### Brand Values
- **Intelligence** — AI-driven, autonomous decision-making
- **Sovereignty** — Authority over market chaos, mastery of execution
- **Precision** — Every trade calculated, every entry timed
- **Trust** — Institutional-grade reliability for retail traders
- **Growth** — From $10 capital upward, compounding returns

---

## App Icon Design

### Concept

The icon is a **stylized imperial crown merged with circuit board / neural network patterns**, rendered in gold on a deep navy background.

**Symbolism:**
| Element | Meaning |
|---|---|
| **Crown (5 points)** | Sovereignty, authority, the "Tsar" identity |
| **Circuit traces** | AI, neural networks, autonomous intelligence |
| **Gold gradient** | Wealth, returns, premium quality |
| **Deep navy background** | Trust, depth, institutional-grade seriousness |
| **Emerald jewels** | Growth, positive returns, the "green" of profitable trades |
| **Neural network overlay** | Machine learning, adaptive intelligence |

### Color Palette

| Color | Hex | Usage |
|---|---|---|
| **Imperial Gold** | `#FFD700` | Primary — crown, highlights |
| **Amber Gold** | `#F5A623` | Secondary — crown body |
| **Deep Gold** | `#D4920B` | Accents, strokes |
| **Navy Dark** | `#0B1628` | Background (deepest) |
| **Navy Mid** | `#1A2744` | Background (lighter center) |
| **Navy Blue** | `#3D5A99` | Circuit traces |
| **Emerald** | `#50C878` | Jewels — growth accent |

### Typography

- Crown-integrated text uses **Georgia / Times New Roman** (serif) — authoritative, classic
- App name "TSAR" uses **letter-spacing: 6** for premium feel
- UI typography should pair with a modern sans-serif (Inter, SF Pro, or similar)

---

## Icon Specifications

### Master Icon
- **File**: `assets/tsar_icon.svg`
- **Format**: SVG (vector, scales to any size)
- **Base dimensions**: 512 × 512 viewport
- **Safe zone**: Content centered with ~5% margin

### Sizes Required

| Platform | Size | File |
|---|---|---|
| **App Store (iOS)** | 1024 × 1024 px | Export from SVG |
| **Play Store (Android)** | 512 × 512 px | Export from SVG |
| **Android (xxxhdpi)** | 192 × 192 px | `mipmap-xxxhdpi/ic_launcher.png` |
| **Android (xxhdpi)** | 144 × 144 px | `mipmap-xxhdpi/ic_launcher.png` |
| **Android (xhdpi)** | 96 × 96 px | `mipmap-xhdpi/ic_launcher.png` |
| **Android (hdpi)** | 72 × 72 px | `mipmap-hdpi/ic_launcher.png` |
| **Android (mdpi)** | 48 × 48 px | `mipmap-mdpi/ic_launcher.png` |
| **Favicon** | 32 × 32 px | `favicon.ico` |
| **Web manifest** | 192, 512 px | PNG exports |

### Android Adaptive Icon

The Android implementation uses the **adaptive icon** format (API 26+):

- **Foreground**: `drawable/ic_launcher_foreground.xml` — Crown + circuits vector
- **Background**: `drawable/ic_launcher_background.xml` — Deep navy solid
- **Adaptive definition**: `mipmap-anydpi-v26/ic_launcher.xml` and `ic_launcher_round.xml`
- **Legacy fallback**: Existing `mipmap-*/ic_launcher.png` files (pre-API 26)

The adaptive icon follows the 108dp canvas with 66dp safe zone (21dp inset on each side). All meaningful content is within the safe zone to ensure proper rendering across OEM launchers.

---

## Icon Principles

### Do
- ✅ Use the icon on dark or neutral backgrounds
- ✅ Maintain the gold-on-navy color relationship
- ✅ Scale proportionally — never stretch or distort
- ✅ Use the SVG master for any new exports
- ✅ Keep the crown silhouette recognizable at small sizes

### Don't
- ❌ Place the icon on busy or colorful backgrounds without contrast padding
- ❌ Change the crown geometry or point proportions
- ❌ Use flat gold without the gradient (loses depth)
- ❌ Remove circuit elements at larger sizes (they're part of identity)
- ❌ Use alternative color schemes without brand review

---

## Brand Voice (for icon-adjacent marketing)

> *Sovereign intelligence for autonomous trading.*

> *Your capital, crowned.*

> *AI authority. Retail accessible. Institutional precision.*

---

## File Manifest

```
assets/
  tsar_icon.svg                              # Master vector icon

mobile/android/app/src/main/res/
  drawable/
    ic_launcher_foreground.xml               # Adaptive icon foreground (vector)
    ic_launcher_background.xml               # Adaptive icon background (vector)
  mipmap-anydpi-v26/
    ic_launcher.xml                          # Adaptive icon definition
    ic_launcher_round.xml                    # Round adaptive icon definition
  mipmap-mdpi/ic_launcher.png                # Legacy 48px
  mipmap-hdpi/ic_launcher.png                # Legacy 72px
  mipmap-xhdpi/ic_launcher.png               # Legacy 96px
  mipmap-xxhdpi/ic_launcher.png              # Legacy 144px
  mipmap-xxxhdpi/ic_launcher.png             # Legacy 192px
```

---

*Last updated: 2026-08-03*
