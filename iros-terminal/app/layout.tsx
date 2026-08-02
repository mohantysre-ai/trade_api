import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Script from "next/script";
import { DeskPrefsProvider } from "./components/DeskPrefsProvider";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "Alphix Terminal | Desk",
    template: "Alphix Terminal | %s",
  },
  description: "Institutional NSE/BSE trading desk — market snapshot, asset matrix, and forensic intelligence.",
  applicationName: "Alphix Terminal",
  metadataBase: new URL("https://sigq.in"),
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Alphix",
  },
  formatDetection: {
    telephone: false,
    email: false,
    address: false,
  },
  other: {
    "mobile-web-app-capable": "yes",
  },
  icons: {
    icon: [
      { url: "/alphix-logo.svg", type: "image/svg+xml" },
      { url: "/alphix-logo.png", type: "image/png" },
    ],
    apple: [{ url: "/alphix-logo.png" }],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#07111f" },
    { media: "(prefers-color-scheme: light)", color: "#f4f7fb" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      data-theme="dark"
      data-font="md"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        <Script src="/theme-boot.js" strategy="beforeInteractive" />
      </head>
      <body className="min-h-full min-h-[100dvh] flex flex-col overflow-x-hidden overscroll-none" suppressHydrationWarning>
        <DeskPrefsProvider>{children}</DeskPrefsProvider>
      </body>
    </html>
  );
}
