import { NextResponse } from "next/server";
import { gzipSync } from "node:zlib";

// Next's `compress: true` does not compress App Router route-handler responses,
// so a BFF route that re-serializes a large JSON payload hands the browser the
// full uncompressed body even though the backend already gzipped it on the
// upstream hop. This helper re-compresses at the edge of our own app.
//
// Only used past MIN_GZIP_BYTES: below that the header overhead outweighs the
// saving, and the compression cost per request is not worth paying.
const MIN_GZIP_BYTES = 1024;

type JsonInit = {
  status?: number;
  headers?: Record<string, string>;
  /**
   * Incoming request, used to honour the client's Accept-Encoding. Optional:
   * every browser sends the header, and routes that omit it still get gzip.
   * Only pass it when you specifically need to respect a client that opted out.
   */
  request?: Request;
};

/**
 * Serialize `data` as JSON and gzip it when the client supports it and the
 * payload is large enough to be worth compressing. The parsed value a browser
 * receives is identical either way - only the transfer size changes.
 */
export function jsonCompressed(data: unknown, init: JsonInit = {}) {
  const { status = 200, headers = {}, request } = init;
  const body = Buffer.from(JSON.stringify(data));

  const acceptsGzip = request
    ? (request.headers.get("accept-encoding") ?? "").includes("gzip")
    : true;

  const base = {
    ...headers,
    // Body content differs per encoding, so any shared cache must key on it.
    Vary: headers.Vary ? `${headers.Vary}, Accept-Encoding` : "Accept-Encoding",
  };

  if (!acceptsGzip || body.byteLength < MIN_GZIP_BYTES) {
    return new NextResponse(body, {
      status,
      headers: { ...base, "Content-Type": "application/json" },
    });
  }

  const compressed = gzipSync(body, { level: 5 });
  return new NextResponse(new Uint8Array(compressed), {
    status,
    headers: {
      ...base,
      "Content-Type": "application/json",
      "Content-Encoding": "gzip",
    },
  });
}
