# Alphix Terminal — Android & iOS (Capacitor)

Native shells that load the live Alphix desk (`https://sigq.in` by default).  
The Next.js app stays the source of truth (APIs, snapshots, UI). This package wraps it for Play Store / App Store.

| Platform | Folder | Open with |
|----------|--------|-----------|
| Android | `mobile/android/` | Android Studio |
| iOS | `mobile/ios/` | Xcode (macOS) |

App ID: `in.sigq.alphix` · Name: **Alphix Terminal**

---

## Prerequisites

- Node 20+
- **Android:** Android Studio (Hedgehog+), JDK 17+, Android SDK 34+
- **iOS:** macOS + Xcode 15+, CocoaPods (`sudo gem install cocoapods`)

This Windows machine can generate both projects; **iOS builds must run on a Mac**.

---

## Quick start

```bat
cd mobile
npm install
npm run sync
```

### Point at production desk (default)

```bat
npm run desk:prod
npm run open:android
```

### Point at local Docker desk (Android emulator)

With stack on `http://localhost:3000`:

```bat
npm run desk:local
npm run open:android
```

`10.0.2.2` is the emulator’s alias for the host PC.  
Physical phone on Wi‑Fi: set `ALPHIX_DESK_URL=http://<your-lan-ip>:3000` then `npx cap sync`.

### iOS (on a Mac)

```bash
cd mobile
npm install
npm run desk:prod
npm run open:ios
```

Then in Xcode: select a team under **Signing & Capabilities**, run on device/simulator.

---

## Scripts

| Script | Action |
|--------|--------|
| `npm run sync` | Copy `www/` + plugins into native projects |
| `npm run open:android` | Open Android Studio |
| `npm run open:ios` | Open Xcode |
| `npm run desk:prod` | Set desk URL → `https://sigq.in` + sync |
| `npm run desk:local` | Set desk URL → emulator localhost + sync |
| `npm run doctor` | Capacitor environment check |

---

## What loads where

`capacitor.config.ts` uses `server.url` so the WebView opens the live desk (same responsive UI you already shipped). Local `www/` holds:

- `index.html` — boot splash (shown briefly / as fallback)
- `offline.html` — network error page (`server.errorPath`)

**Store note:** Apple/Google prefer apps with native value (splash, status bar, offline UX — included). Pure remote WebViews can get extra review scrutiny; keep SplashScreen / StatusBar plugins enabled and avoid shipping an empty wrapper.

---

## Icons & splash

Replace `resources/icon.png` and `resources/splash.png` (512×512+), then:

```bat
npx capacitor-assets generate
```

(or set icons manually in Android Studio / Xcode). Seed copies from the web PWA icons are already in `www/icon.png` and `resources/`.

---

## Release builds

### Android (AAB for Play)

1. `npm run desk:prod && npm run sync`
2. Android Studio → **Build → Generate Signed Bundle / APK**
3. Use your upload keystore (create one if first release)

### iOS (App Store)

1. On Mac: `npm run desk:prod && npm run sync`
2. Xcode → Product → Archive → Distribute App
3. Bundle ID must match `in.sigq.alphix` (or change `appId` in `capacitor.config.ts` before first submit)

---

## Changing the desk URL

```bat
set ALPHIX_DESK_URL=https://sigq.in
npx cap sync
```

Or edit the default in `capacitor.config.ts`.

---

## Layout

```
mobile/
  capacitor.config.ts
  package.json
  www/                 # local shell + offline
  resources/           # icon/splash seeds
  android/             # Android Studio project
  ios/                 # Xcode project
  README.md
```
