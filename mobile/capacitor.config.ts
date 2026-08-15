import type { CapacitorConfig } from "@capacitor/cli";

/**
 * Alphix Terminal native shell.
 *
 * Loads the live Next.js desk (API + snapshots) from ALPHIX_DESK_URL.
 * Local Android emulator → http://10.0.2.2:3000
 * Physical device on LAN → http://<your-pc-lan-ip>:3000
 * Production → https://sigq.in
 *
 * Note: server.url is a live WebView load (needs network). Ship offline.html
 * as errorPath. For store review, keep Splash/StatusBar plugins + this shell.
 */
const deskUrl = (process.env.ALPHIX_DESK_URL || "https://sigq.in").replace(/\/$/, "");

const config: CapacitorConfig = {
  appId: "in.sigq.alphix",
  appName: "Alphix Terminal",
  webDir: "www",
  backgroundColor: "#07111f",
  server: {
    url: deskUrl,
    cleartext: deskUrl.startsWith("http://"),
    allowNavigation: [
      "sigq.in",
      "www.sigq.in",
      "*.sigq.in",
      "localhost",
      "127.0.0.1",
      "10.0.2.2",
    ],
    errorPath: "offline.html",
  },
  plugins: {
    SplashScreen: {
      launchShowDuration: 1800,
      launchAutoHide: true,
      backgroundColor: "#07111f",
      androidSplashResourceName: "splash",
      showSpinner: false,
      splashFullScreen: true,
      splashImmersive: true,
    },
    StatusBar: {
      style: "DARK",
      backgroundColor: "#07111f",
    },
  },
  android: {
    allowMixedContent: deskUrl.startsWith("http://"),
    backgroundColor: "#07111f",
    webContentsDebuggingEnabled: process.env.ALPHIX_DESK_DEBUG === "1",
  },
  ios: {
    contentInset: "automatic",
    backgroundColor: "#07111f",
    preferredContentMode: "mobile",
    scrollEnabled: true,
    allowsLinkPreview: false,
  },
};

export default config;
