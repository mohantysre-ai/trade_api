# Next.js 16 production image (standalone output)
# Build stages can contain development tooling; only the minimal distroless
# runtime stage is shipped to production.
FROM node:24.20.0-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

FROM node:24.20.0-bookworm-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Browser stays same-origin; BFF talks to market-api via MARKET_API_URL at runtime.
ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_MARKET_API_URL=
RUN npm run build \
    && mkdir -p /app/.sparkline-cache \
    && chown -R 65532:65532 /app/.sparkline-cache

# Runtime contains Node and only the libraries required to execute it. No shell,
# apt, npm, yarn, perl, systemd or other general-purpose OS tooling is shipped.
FROM gcr.io/distroless/nodejs24-debian13:nonroot AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    MARKET_API_URL=http://market-api:8000

COPY --from=builder --chown=65532:65532 /app/public ./public
COPY --from=builder --chown=65532:65532 /app/.next/standalone ./
COPY --from=builder --chown=65532:65532 /app/.next/static ./.next/static
COPY --from=builder --chown=65532:65532 /app/.sparkline-cache ./.sparkline-cache
COPY --chown=65532:65532 server-cluster.js ./server-cluster.js

USER 65532:65532
EXPOSE 3000

# Distroless has no shell. Use the Node executable directly for health checks.
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD ["/nodejs/bin/node", "-e", "fetch('http://127.0.0.1:3000/').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"]

# nodejs distroless images already provide the Node executable as ENTRYPOINT.
CMD ["server-cluster.js"]
