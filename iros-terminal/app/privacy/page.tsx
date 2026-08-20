import type { Metadata } from "next";
import Link from "next/link";

const PRIVACY_EMAIL = process.env.PRIVACY_CONTACT_EMAIL?.trim() || "privacy@sigq.in";

export const metadata: Metadata = {
  title: "Privacy & Data Use",
  description: "How Alphix Terminal handles browser, operational, market, news, and AI-processing data.",
};

const Section = ({
  number,
  title,
  children,
}: {
  number: string;
  title: string;
  children: React.ReactNode;
}) => (
  <section className="grid gap-3 border-t border-[var(--terminal-line)] py-7 md:grid-cols-[7rem_1fr]">
    <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.2em] text-[var(--terminal-cyan)]">
      {number}
    </p>
    <div className="space-y-4">
      <h2 className="text-xl font-semibold tracking-tight text-[var(--fg-strong)]">{title}</h2>
      {children}
    </div>
  </section>
);

const DataCard = ({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) => (
  <div className="rounded-2xl border border-[var(--terminal-line)] bg-[var(--glass-flat)] p-4">
    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--fg-subtle)]">{label}</p>
    <p className="mt-2 font-semibold text-[var(--fg-strong)]">{value}</p>
    <p className="mt-1 text-sm leading-6 text-[var(--fg-muted)]">{detail}</p>
  </div>
);

export default function PrivacyPage() {
  return (
    <main className="terminal-shell min-h-[100dvh] px-4 py-6 sm:px-6 lg:px-8">
      <div className="relative z-10 mx-auto max-w-5xl">
        <nav className="mb-8 flex items-center justify-between gap-4" aria-label="Privacy page navigation">
          <Link
            href="/"
            className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-[var(--fg-muted)] transition-colors hover:text-[var(--terminal-cyan)] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--terminal-cyan)]"
          >
            <span aria-hidden>←</span> Alphix Terminal
          </Link>
          <span className="rounded-full border border-[var(--terminal-line)] bg-[var(--glass-flat)] px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--fg-subtle)]">
            Updated 20 Aug 2026
          </span>
        </nav>

        <header className="glass-shell mb-7 overflow-hidden rounded-[var(--radius-card)] p-6 sm:p-9">
          <div className="max-w-3xl">
            <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--terminal-cyan)]">
              Privacy notice · sigq.in
            </p>
            <h1 className="mt-4 text-4xl font-semibold tracking-[-0.04em] text-[var(--fg-strong)] sm:text-5xl">
              Your market view should not become a user profile.
            </h1>
            <p className="mt-5 max-w-2xl text-base leading-7 text-[var(--fg-muted)]">
              Alphix Terminal is a market-intelligence interface. It does not provide user accounts, accept payments,
              place broker orders, or run first-party advertising analytics. This notice explains the limited browser and
              operational data used to deliver and secure the service, plus the market, news, and AI data processed by the desk.
            </p>
          </div>

          <div className="mt-7 grid gap-3 sm:grid-cols-3">
            <DataCard label="Accounts" value="Not collected" detail="No registration profile, password, KYC, or payment details." />
            <DataCard label="Browser storage" value="Local only" detail="Display preferences and seen-alert identifiers stay in your browser." />
            <DataCard label="Market research" value="Operational data" detail="Ticker, price, news, model output, and desk-state records support the product." />
          </div>
        </header>

        <div className="glass-shell rounded-[var(--radius-card)] px-6 sm:px-9">
          <Section number="01 / Scope" title="Who this notice covers">
            <p className="text-sm leading-7 text-[var(--fg-muted)]">
              This notice covers the Alphix Terminal website at sigq.in and the supporting market-data, news, model,
              cache, and operations services controlled by the site operator. Third-party websites and embedded widgets
              have their own privacy terms.
            </p>
          </Section>

          <Section number="02 / Data" title="What is processed">
            <div className="grid gap-3 sm:grid-cols-2">
              <DataCard
                label="Connection & security"
                value="Request metadata"
                detail="IP address, timestamp, requested path, response status, user agent, and error details may appear in web-server, tunnel, proxy, or container logs."
              />
              <DataCard
                label="Device preferences"
                value="Theme, text size, performance mode"
                detail="Stored in localStorage. Seen desk-alert identifiers are stored in sessionStorage. No account is created from these values."
              />
              <DataCard
                label="Offline shell"
                value="Same-origin static files"
                detail="A service worker caches the application shell, manifest, icons, styles, and scripts. Live /api responses are excluded from its cache."
              />
              <DataCard
                label="Desk operations"
                value="Market and model records"
                detail="Symbols, quotes, candles, scores, news links and excerpts, session books, alerts, outcomes, model prompts/outputs, and refresh status may be persisted."
              />
            </div>
            <p className="text-sm leading-7 text-[var(--fg-muted)]">
              Market and company records normally describe listed instruments, not an identifiable visitor. They can
              become personal data only when combined with information that identifies an individual—for example, a
              named insider disclosed in a public filing or a visitor identifier included in a diagnostic record.
            </p>
          </Section>

          <Section number="03 / Purpose" title="Why the data is used">
            <ul className="list-disc space-y-2 pl-5 text-sm leading-7 text-[var(--fg-muted)] marker:text-[var(--terminal-cyan)]">
              <li>Deliver live and cached terminal views, maintain sessions, and remember display choices.</li>
              <li>Fetch, rank, summarize, and explain market, issuer, and news information.</li>
              <li>Detect failures, control upstream quotas, investigate abuse, and protect the service.</li>
              <li>Maintain desk audit history, reproduce calculations, and improve data quality.</li>
              <li>Comply with applicable legal duties and respond to valid requests.</li>
            </ul>
            <p className="text-sm leading-7 text-[var(--fg-muted)]">
              We process personal data only for a lawful, stated purpose. Where consent is legally required, it must be
              requested through a clear affirmative action and may be withdrawn for future processing.
            </p>
          </Section>

          <Section number="04 / Sharing" title="Providers and external destinations">
            <p className="text-sm leading-7 text-[var(--fg-muted)]">
              The terminal uses market and issuer sources such as exchange/broker feeds and financial publishers; news
              discovery sources; AI/model providers such as OpenRouter or Google Gemini when configured; Cloudflare for
              tunnel and edge delivery; and Trendlyne widgets for selected research cards. Only the data needed for the
              requested function should be sent—for example, a ticker and a bounded news excerpt for summarization.
            </p>
            <p className="text-sm leading-7 text-[var(--fg-muted)]">
              Loading an embedded third-party widget or following an external link can disclose your IP address, browser
              details, the requested ticker/widget, and possibly the referring page to that third party. Their policies
              govern their subsequent processing. The operator does not sell personal data or use it for targeted advertising.
            </p>
          </Section>

          <Section number="05 / Retention" title="How long data remains">
            <p className="text-sm leading-7 text-[var(--fg-muted)]">
              Browser preferences remain until you clear site data; session alert identifiers normally disappear when
              the browser session is cleared. Operational JSON state is retained until it is replaced or manually deleted.
              End-of-day archives can accumulate until an operator deletes them. Infrastructure-log retention depends on
              the active host, tunnel, and container configuration. No fixed retention period is claimed where one is not
              technically enforced.
            </p>
            <p className="text-sm leading-7 text-[var(--fg-muted)]">
              Personal data should be erased when its purpose is no longer served, consent is withdrawn, or a valid erasure
              request is completed, unless continued retention is required by law, security, or a legal claim.
            </p>
          </Section>

          <Section number="06 / Choices" title="Your controls and rights">
            <ul className="list-disc space-y-2 pl-5 text-sm leading-7 text-[var(--fg-muted)] marker:text-[var(--terminal-cyan)]">
              <li>Clear localStorage, sessionStorage, and cached site files using your browser controls.</li>
              <li>Block third-party content using browser or network privacy controls.</li>
              <li>Ask whether personal data about you is processed and request a summary of that processing.</li>
              <li>Request correction, completion, updating, or erasure where applicable.</li>
              <li>Withdraw consent for future consent-based processing and raise a privacy grievance.</li>
              <li>Nominate another individual to exercise applicable rights in the event of death or incapacity.</li>
            </ul>
            <p className="text-sm leading-7 text-[var(--fg-muted)]">
              Send a private request to <a className="font-semibold text-[var(--terminal-cyan)] underline-offset-4 hover:underline" href={`mailto:${PRIVACY_EMAIL}`}>{PRIVACY_EMAIL}</a>.
              Include enough detail to locate the relevant record, but do not send broker passwords, API keys, TOTP seeds,
              PAN, Aadhaar, or other unnecessary credentials. Identity may be verified before a request is fulfilled.
            </p>
          </Section>

          <Section number="07 / Children" title="Not intended for children">
            <p className="text-sm leading-7 text-[var(--fg-muted)]">
              Alphix Terminal is a professional market-intelligence tool and is not directed to anyone under 18. The
              service does not knowingly request a child&apos;s personal data. Contact the operator if you believe such data
              has been processed so it can be reviewed and removed where required.
            </p>
          </Section>

          <Section number="08 / Security" title="Security and incident handling">
            <p className="text-sm leading-7 text-[var(--fg-muted)]">
              The operator should apply access controls, secret isolation, origin restrictions, transport security,
              request limits, secure headers, backups, and log redaction appropriate to the deployment. No internet service
              is risk-free. If a personal-data breach creates a risk to you, notice will be provided as required by applicable law.
            </p>
          </Section>

          <Section number="09 / Contact" title="Questions and grievances">
            <p className="text-sm leading-7 text-[var(--fg-muted)]">
              The sigq.in operator is responsible for this notice. Privacy questions and rights requests can be sent to
              {" "}<a className="font-semibold text-[var(--terminal-cyan)] underline-offset-4 hover:underline" href={`mailto:${PRIVACY_EMAIL}`}>{PRIVACY_EMAIL}</a>.
              We aim to acknowledge requests promptly and respond within 30 calendar days, unless applicable law requires
              a shorter period. If a
              grievance is not resolved after using this channel, you may use the complaint process available under applicable law.
            </p>
          </Section>
        </div>

        <footer className="py-8 text-center text-[10px] uppercase tracking-[0.16em] text-[var(--fg-subtle)]">
          This notice describes data handling; it is not a trading recommendation or a certification of legal compliance.
        </footer>
      </div>
    </main>
  );
}
