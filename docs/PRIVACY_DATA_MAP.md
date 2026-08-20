# Alphix Terminal privacy data map

Status: implementation inventory  
Owner: sigq.in operator  
Last reviewed: 2026-08-20  
Public notice: `https://sigq.in/privacy`

This document maps data visible in the repository and its default Docker deployment. It is an engineering record, not a claim that every production control is active. Re-check it whenever a route, provider, persistent file, browser store, proxy, or logging destination changes.

## 1. Scope and classification

Alphix Terminal is a market-intelligence application without user accounts, KYC, payments, or broker auto-order execution. Most application records describe listed securities and desk decisions rather than visitors.

| Class | Examples | Personal data? | Sensitivity |
| --- | --- | --- | --- |
| Visitor/request metadata | IP address, user agent, timestamp, URL/path, status code, error trace | Yes when linked or linkable to a person | Medium |
| Browser preferences | Theme, font size, performance mode | Usually not on their own; may become linkable on a shared device | Low |
| Seen-alert state | Up to 200 alert IDs in the current browser session | Usually no; potentially linkable with other device data | Low |
| Market and issuer data | Ticker, OHLC/quotes, volume, corporate news, public filings, promoter/insider information | Usually no visitor data; public filings may name individuals | Low to medium |
| Desk state | Positions, entries, stops, targets, P&L, rankings, session dates, decisions | Operational/confidential; not necessarily personal | High business sensitivity |
| AI inputs and outputs | Ticker, selected news excerpts, metrics, prompt, summary, model/error metadata | Normally no, unless source text contains an identifiable person | Medium |
| Secrets | Broker/API credentials, TOTP secret, OAuth tokens, Cloudflare credentials, shared API secret | Credential/security data; may relate to an individual account | Critical |

Data-minimisation rule: do not send credentials, full raw logs, account identifiers, or unrelated article text to an LLM. Ticker-news prompts should contain only the ticker, bounded factual excerpts, source/date metadata, and the metrics needed for the requested analysis.

## 2. Data flows

| Flow | Source | Data sent | Recipient / destination | Purpose | Persistence |
| --- | --- | --- | --- | --- | --- |
| Page request | Visitor browser | IP and connection metadata, user agent, path, headers | Cloudflare tunnel, frontend server, container/runtime logs | Deliver and secure the site | Host/tunnel/log policy; no repository-enforced period |
| Browser preferences | Visitor choice | Theme, font size, performance mode | Browser `localStorage` only | Remember display preferences | Until site data is cleared |
| Activity alert state | Terminal API output | Alert identifiers | Browser `sessionStorage` only | Avoid repeating alerts in one session | Until the browser session/site data is cleared |
| Offline shell | Application | Same-origin HTML/navigation responses, JS, CSS, manifest, icons | Browser Cache Storage (`alphix-shell-v1`) | Installability and offline shell | Until cache version replacement or site-data clearing; `/api/` is excluded |
| Market feed | Exchanges, broker/market providers | Instrument identifiers and requested market intervals | Backend market services | Quotes, candles, screeners, books, reports | Memory caches and JSON state/archives described below |
| News discovery | Exchanges, Google News/RSS, publisher/search endpoints | Ticker/company search terms and request metadata | The relevant upstream source | Find recent issuer news | Article metadata/excerpts may enter cache and model input |
| AI summarisation | Backend | Ticker, bounded excerpts, selected metrics, prompt instructions | OpenRouter, Google Gemini, or another configured model endpoint | Summarise and classify market evidence | Provider policy plus local cached output/error metadata |
| Embedded research | Visitor browser | IP, browser headers, requested ticker/widget, possible referrer | Trendlyne | Display checklist, SWOT, and technical widgets | Under Trendlyne/browser policy; not controlled by this repository |
| External research link | Visitor click | Normal navigation/request metadata | NSE, Moneycontrol, Google Finance, Lemonn, Trendlyne, publishers, or another linked site | Open source material | Under destination policy |
| Desk persistence | Backend jobs/API | Plans, sessions, alerts, snapshots, outcomes, reports, model commentary | Docker volumes and optional desk-state image/export | Continuity, audit, and reproducibility | Until overwrite/manual deletion; EOD archive accumulates |

Conditional architecture risk: `NEXT_PUBLIC_MARKET_API_URL` allows browser-direct requests to the backend. The default production compose value is empty, but any non-empty deployment value changes the data flow and can bypass protections applied only by frontend server-side proxies. Keep it empty unless the backend is intentionally public and independently secured.

## 3. Browser-side stores and third-party requests

| Store / request | Location | Exact data | Code location | Clearing method |
| --- | --- | --- | --- | --- |
| `iros-desk-theme` | `localStorage` | `dark` or `light` | `iros-terminal/app/components/DeskPrefsProvider.tsx`, `public/theme-boot.js` | Browser site-data controls |
| `iros-desk-font` | `localStorage` | `sm`, `md`, `lg`, or `xl` | Same as above | Browser site-data controls |
| `iros-desk-perf` | `localStorage` | `1` or `0` | `DeskPrefsProvider.tsx` | Browser site-data controls |
| `alphix.deskActivitySeen.v1` | `sessionStorage` | JSON array of at most 200 alert IDs | `DeskActivityAlerts.tsx` | End session or clear site data |
| `alphix-shell-v1` | Cache Storage | Shell/navigation and same-origin static assets | `public/sw.js` | Cache-version activation or clear site data |
| Trendlyne iframe | Network request from browser | Requested ticker/widget plus normal connection metadata | `ConfidenceCheckerPanel.tsx`, `SwotAnalysisPanel.tsx`, `TechnicalAnalysisPanel.tsx` | Block third-party content; no first-party store control |

Verified repository state has no first-party analytics SDK, advertising pixel, account cookie, or payment SDK. Re-run this check before each policy review.

## 4. Server-side stores

Default Docker mounts:

| Volume | Container path | Contents | Retention state |
| --- | --- | --- | --- |
| `iros-backend-data` | `/app/backend/app/data` | Refresh tasks, pre-work/automation stamps, sector and issuer caches, news/model caches, swing prefilter state, supporting market files | No universal expiry or deletion schedule verified |
| `iros-eod-archive` | `/app/backend/app/services/eod_archive` | Date-partitioned EOD payloads, scorecards, counterfactuals, proposals, PM commentary, ticker reports | Accumulates until manual deletion/volume removal |
| `iros-desk-state` | `/app/state` | Swing/intraday sessions, snapshots, fixed plan, alert history | Files are updated/replaced by desk workflows; no formal maximum age verified |

Named state paths configured in `docker-compose.yml`:

- `/app/state/swing_session.json`
- `/app/state/trade_api_snapshot.json`
- `/app/state/last_market_snapshot.json`
- `/app/state/fixed_trade_plan.json`
- `/app/state/alert_history.json`
- `/app/state/intraday_session.json`

Other known operational files include `refresh_tasks.json`, `morning_prework_stamp.json`, `nse_sector_heatmap.json`, `bulk_deals_cache.json`, `promoter_holdings.json`, `desk_automation_stamp.json`, and `swing_prefilter_snapshot.json`. The EOD archive can include `master_eod_payload.json`, `scorecards.json`, `counterfactuals.json`, `proposals.json`, `pm_commentary.json`, and ticker-level JSON.

Operator action: define and automate a retention schedule separately for request logs, volatile caches, desk-state snapshots, alert history, and audit/EOD records. Until it is enforced in code or infrastructure, public wording must remain “until replaced or manually deleted,” not a fixed number of days.

## 5. External recipients and processors

Only enabled/configured providers apply to a given deployment.

| Category | Known integrations in repository | Typical data disclosed |
| --- | --- | --- |
| Market/broker data | Angel One SmartAPI, Dhan/ScanX, NSE, BSE, Yahoo Finance | Instrument/ticker, requested interval, API account metadata and provider credentials server-side |
| News and research | Google News/RSS, Moneycontrol, Economic Times, Zerodha Pulse, Livemint, Indian Express, News18, Inc42, YourStory, Trendlyne, Chartink, Investing.com | Ticker/company search, article URL/date/excerpt, connection metadata |
| Model providers | OpenRouter and its routed models, Google Gemini; other endpoint when configured | Ticker, selected market facts/news excerpts, prompt, generated response, quota/error metadata |
| Network edge | Cloudflare Tunnel | IP/connection data, hostname, route, timing, and security/diagnostic events subject to configuration |
| Linked destinations | NSE, Moneycontrol, Google Finance, Lemonn, Trendlyne, publishers | Data generated by user navigation under the destination's policy |

Do not list every OpenRouter-routed model as a separately guaranteed recipient: the actual downstream model may change under the free-router/failover configuration. Treat OpenRouter and the selected model host as a variable processing chain and review provider settings for training, retention, and region before sending personal data.

## 6. Purpose, access, and disclosure controls

| Data | Purpose | Expected access | Disclosure rule |
| --- | --- | --- | --- |
| Request/security logs | Availability, abuse investigation, debugging | Operators with host/tunnel access | Do not expose publicly; redact secrets and authorization headers |
| Desk state and reports | Session continuity, trade review, reproducibility | Authorised desk/operator and application services | No public bulk export; share minimum evidence needed |
| News/model cache | Reduce quota use, make outputs explainable | Backend services and authorised operator | Send only bounded inputs to model providers |
| Browser preferences | User experience | Same-origin browser scripts on the device | Do not transmit for profiling |
| Credentials | Authenticate server-to-server providers | Runtime process and deployment operator only | Never put in client bundles, URLs, logs, model prompts, images, or repository history |

## 7. Rights-request and deletion runbook

Public contact: `privacy@sigq.in`, overridable at build time with `PRIVACY_CONTACT_EMAIL`.

Before publishing the page, provision and monitor that mailbox or set a verified alternative. Never direct a person to open a public GitHub issue containing personal data.

1. Record the request privately and acknowledge it.
2. Verify identity proportionately; never ask for broker credentials, TOTP seeds, API keys, PAN, or Aadhaar unless a specific legal need has been established.
3. Search only locations likely to contain the identifier: edge/host logs, application logs, incident records, and any submitted support material. The product has no account database by default.
4. Provide access/correction/erasure or explain the lawful reason for refusal/retention.
5. Propagate erasure to processors where required and technically possible.
6. Record completion without retaining the deleted content itself.
7. Respond within the public 30-calendar-day commitment unless applicable law requires a shorter period.

Browser-only preferences cannot be remotely tied to or erased for a visitor because the server does not receive an account identifier for them. Instruct the requester to clear site data locally.

## 8. Security and privacy risks requiring owner action

| Priority | Risk | Verified repository condition on 2026-08-20 | Required action |
| --- | --- | --- | --- |
| Critical | API access control drift | The privacy review branch does not contain the separately reported auth patch | Merge/deploy the reviewed server-side auth change; fail closed when unset; test every route without publishing route details |
| High | Origin-policy drift | The privacy review branch does not contain the separately reported explicit allow-list | Deploy the reviewed origin allow-list and verify credential/origin behavior |
| High | Secret leakage in logs | A third-party SDK was reported to emit private request headers on error | Add a process-wide logging filter/redactor before persistent handlers; test representative errors |
| High | Credentials in Git history | Historical secret exposure was reported but not verified as purged | Rotate affected credentials, purge history using an approved procedure, coordinate the rewrite, and verify remote objects/caches |
| High | Missing contact | `privacy@sigq.in` is the public fallback but repository cannot prove it is monitored | Provision the mailbox or set `PRIVACY_CONTACT_EMAIL` to a monitored private channel before deployment |
| Medium | Undefined retention | Most JSON/archive/log data has no formal maximum | Approve a schedule, implement deletion, and test restoration/expiry behavior |
| Medium | Third-party embeds | Trendlyne iframes load from the visitor's browser | Decide whether to gate embeds behind an explicit load action/consent and document provider terms |
| Medium | Cross-border/model processing | OpenRouter/Gemini provider region and model host vary | Review contracts/settings and keep personal data out of prompts by default |
| Medium | Direct backend URL | Public env can switch client traffic away from the server proxy | Keep empty by default; add a deployment test that fails if unintentionally set |
| Medium | Floating Python dependencies | No verified dependency lock was reported | Produce pins from a tested environment and add vulnerability/update review |

This table intentionally distinguishes “reported fixed elsewhere” from what is visible on the current branch. Keep detailed vulnerability evidence in a restricted security record; do not publish exploit instructions in this data map. Move an item to “implemented” only after the control and its tests exist in the deployed commit.

## 9. Change checklist

For every feature or provider change, answer:

- Does it introduce a new identifier, form field, account, cookie, browser store, log field, iframe, analytics SDK, processor, or cross-border transfer?
- Is the data necessary, bounded, and excluded from URLs/logs where sensitive?
- Does the public notice still name the data, purpose, recipient category, retention behavior, rights method, and contact?
- Is deletion technically possible across primary storage, caches, exports, backups, and processors?
- Are secrets redacted and server-side access controls tested on both read and write routes?
- Does `NEXT_PUBLIC_MARKET_API_URL` remain empty in the intended proxy architecture?
- Has `privacy@sigq.in` (or `PRIVACY_CONTACT_EMAIL`) been tested and assigned an owner?

## 10. Evidence references

- [Digital Personal Data Protection Act, 2023](https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf): notice contents, clear consent, fiduciary safeguards, erasure, contact publication, access/correction/erasure/grievance rights.
- [Digital Personal Data Protection Rules, 2025](https://www.meity.gov.in/static/uploads/2025/11/53450e6e5dc0bfa85ebd78686cadad39.pdf): prominent business contact, published rights-request method, and grievance-response period.
- Repository evidence: `docker-compose.yml`, `iros-terminal/public/sw.js`, `DeskPrefsProvider.tsx`, `DeskActivityAlerts.tsx`, `market-api.ts`, Trendlyne panel components, backend provider/config modules, and EOD/state services.

Legal requirements and commencement dates can change. Recheck the official Ministry of Electronics and Information Technology publications before treating this engineering map as a compliance decision.
