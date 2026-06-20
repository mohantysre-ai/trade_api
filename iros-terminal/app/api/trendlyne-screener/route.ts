import { NextResponse } from "next/server";

export const runtime = "nodejs";

const TRENDLYNE_URLS: Record<string, string> = {
  risingDelivery: "https://trendlyne.com/fundamentals/json-screener/515763/5/0/index/NIFTY500/",
  topLosersVolume: "https://trendlyne.com/fundamentals/json-screener/515761/5/0/index/NIFTY500/",
  volumeShockers: "https://trendlyne.com/fundamentals/json-screener/515758/5/0/index/NIFTY500/",
  highVolumeGain: "https://trendlyne.com/fundamentals/json-screener/515760/5/0/index/NIFTY500/",
  highVolumeLoss: "https://trendlyne.com/fundamentals/json-screener/515761/5/0/index/NIFTY500/",
  outPerformanceWeek: "https://trendlyne.com/fundamentals/json-screener/515755/5/0/index/NIFTY500/",
};

export async function GET(request: Request) {
  const requestUrl = new URL(request.url);
  const screen = requestUrl.searchParams.get("screen");

  if (!screen || !TRENDLYNE_URLS[screen]) {
    return NextResponse.json(
      { error: "Missing or invalid screen. Use: risingDelivery, topLosersVolume, volumeShockers, highVolumeGain, highVolumeLoss, or outPerformanceWeek." },
      { status: 400 }
    );
  }

  try {
    const res = await fetch(TRENDLYNE_URLS[screen], {
      cache: "no-store",
      headers: {
        Accept: "application/json, text/plain, */*",
        Referer: "https://trendlyne.com/",
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      },
    });

    if (!res.ok) {
      const detail = await res.text();
      return NextResponse.json(
        { error: detail || `Trendlyne API HTTP ${res.status}` },
        { status: 502 }
      );
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}