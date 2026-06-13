# IROS Terminal - Completed Tasks

## ✅ Completed
- [x] Update iros-terminal/next.config.ts to allow localhost and 127.0.0.1 dev origins
- [x] Fix launcher frontend paths in start-services.bat, start_app.bat, and start-persistent.ps1
- [x] Restart app services
- [x] Verify frontend is reachable on localhost:3000
- [x] Verify backend is reachable on localhost:8000

## ✅ On-Demand Refresh Implementation
- [x] Analyze codebase structure (frontend pages, API routes, hooks, components)
- [x] Fix ForensicPanel refresh to trigger backend on-demand refresh endpoint (POST /api/refresh-data-on-demand)
- [x] Wire parent `invalidateKey` to propagate invalidation to ForensicPanel's SWR cache
- [x] Update page.tsx to pass `invalidateKey` prop to ForensicPanel
- [x] Fix pre-existing TypeScript error in DrawerContent (missing `snapshot` property)
- [x] Build compiles without errors (`next build` passes)
- [x] Backend service running on port 8000
- [x] Frontend service running on port 3000
- [x] Test /api/market-data returns 200 ✓
- [x] Test /api/refresh-data-on-demand returns 200 ✓ (forced live refresh)
- [x] Verify data renders properly

## How Refresh Works Now

### Header "Snapshot" Button (App-wide refresh)
1. Clicks → calls `refreshOnDemand()` from `useMarketData` hook
2. Hook sends `POST /api/refresh-data-on-demand` to the Next.js proxy
3. Next.js proxies to `POST http://127.0.0.1:8000/api/refresh-data-on-demand`
4. Backend forces live refresh with `force_refresh=True`, writes to `last_market_snapshot.json`
5. Hook sets new parent state and bumps `invalidateKey`
6. `ForensicPanel` detects `invalidateKey` change via useEffect → calls `mutate()` → re-fetches fresh data from GET endpoint

### Asset Matrix "Refresh" Button (Panel-specific refresh)
1. Clicks → calls `refresh()` in ForensicPanel
2. Sends `POST /api/refresh-data-on-demand` to trigger backend refresh
3. Then calls `mutate()` to revalidate SWR cache
4. Panel shows fresh data

### Key Files Modified
- `iros-terminal/app/components/ForensicPanel.tsx` → Added `invalidateKey` prop, useEffect listener, POST call in refresh
- `iros-terminal/app/page.tsx` → Passes `invalidateKey` to ForensicPanel, fixed DrawerContent type