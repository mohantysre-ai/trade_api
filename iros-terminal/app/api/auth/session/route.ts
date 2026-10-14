import { NextResponse } from "next/server";
import { currentAccessSession } from "@/lib/access-auth";

export async function GET() {
  return NextResponse.json(await currentAccessSession(), {
    headers: { "Cache-Control": "no-store" },
  });
}
