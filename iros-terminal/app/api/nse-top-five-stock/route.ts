import { NextResponse } from "next/server";

export const runtime = "nodejs";

const NSE_INDEX = "NIFTY 500";
const NSE_FLAGS = new Set(["G", "L", "MAVA", "MAVO"]);

function getFlag(requestUrl: URL) {
  const flag = requestUrl.searchParams.get("flag");
  return flag && NSE_FLAGS.has(flag) ? flag : null;
}

export async function GET(request: Request) {
  const requestUrl = new URL(request.url);
  const flag = getFlag(requestUrl);

  if (!flag) {
    return NextResponse.json(
      { error: "Missing or invalid flag. Use G, L, MAVA, or MAVO." },
      { status: 400 }
    );
  }

  try {
    const nseUrl = new URL(
      "https://www.nseindia.com/api/NextApi/apiClient/indexTrackerApi"
    );
    nseUrl.searchParams.set("functionName", "getTopFiveStock");
    nseUrl.searchParams.set("flag", flag);
    nseUrl.searchParams.set("index", NSE_INDEX);

    const res = await fetch(nseUrl.toString(), {
      cache: "no-store",
      headers: {
        Accept: "application/json, text/plain, */*",
        Referer: "https://www.nseindia.com/",
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      },
    });

    if (!res.ok) {
      const detail = await res.text();
      return NextResponse.json(
        { error: detail || `NSE API HTTP ${res.status}` },
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
