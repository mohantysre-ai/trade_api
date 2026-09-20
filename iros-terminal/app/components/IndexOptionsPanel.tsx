'use client';

// V1 presentation has been retired. Keep this stable import path so the
// terminal page does not need a routing migration while Quant V2 becomes the
// sole Index Options desk.
// NOTE: wrapper (not `export ... from`) — bare re-exports break Turbopack's
// client module factory in dev and surface as "module factory is not available".
import QuantIndexOptionsPanel from './QuantIndexOptionsPanel';

export default function IndexOptionsPanel({
  refreshToken = 0,
  sessionDate,
}: {
  refreshToken?: number;
  sessionDate?: string;
}) {
  return <QuantIndexOptionsPanel refreshToken={refreshToken} sessionDate={sessionDate} />;
}
