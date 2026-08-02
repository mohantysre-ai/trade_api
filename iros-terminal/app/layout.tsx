import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
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
  title: "Alphix Terminal | sigq.in",
  description: "Institutional NSE/BSE trading desk — market snapshot, asset matrix, and forensic intelligence.",
  metadataBase: new URL("https://sigq.in"),
  icons: {
    icon: [{ url: "/alphix-logo.png", type: "image/png" }, { url: "/alphix-logo.svg", type: "image/svg+xml" }],
    apple: [{ url: "/alphix-logo.png" }],
  },
};

const themeBootScript = `
(function(){
  try {
    var t = localStorage.getItem('iros-desk-theme');
    if (t !== 'light' && t !== 'dark') {
      t = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    }
    var f = localStorage.getItem('iros-desk-font');
    if (f !== 'sm' && f !== 'md' && f !== 'lg' && f !== 'xl') f = 'md';
    document.documentElement.setAttribute('data-theme', t);
    document.documentElement.setAttribute('data-font', f);
    document.documentElement.style.colorScheme = t;
  } catch (e) {}
})();
`;

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
        <script dangerouslySetInnerHTML={{ __html: themeBootScript }} />
      </head>
      <body className="min-h-full flex flex-col">
        <DeskPrefsProvider>{children}</DeskPrefsProvider>
      </body>
    </html>
  );
}
