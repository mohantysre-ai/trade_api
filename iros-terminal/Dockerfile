# Next.js 16 production image (standalone output)
# Build stages can contain development tooling; only the minimal distroless
# runtime stage is shipped to production.
FROM node:24.20.0-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
# Tailwind 4 loads Lightning CSS through a platform-native optional package.
# Docker builds occasionally see transient npm ECONNRESET errors, so make the
# dependency stage retry-safe and avoid audit/fund traffic. npm ci remains the
# authoritative install; the native Lightning CSS package is repaired only if
# npm omitted the optional Linux binary.
RUN npm config set fetch-retries 5 \
    && npm config set fetch-retry-mintimeout 20000 \
    && npm config set fetch-retry-maxtimeout 120000 \
    && npm config set fetch-timeout 300000 \
    && install_deps() { \
         if [ -f package-lock.json ]; then \
           npm ci --include=optional --prefer-offline --no-audit --no-fund; \
         else \
           npm install --include=optional --prefer-offline --no-audit --no-fund; \
         fi; \
       }; \
       n=0; until install_deps; do \
         n=$((n+1)); \
         if [ "$n" -ge 3 ]; then exit 1; fi; \
         echo "npm install failed; retrying attempt $((n+1))/3..."; \
         rm -rf node_modules; \
         sleep $((n*5)); \
       done \
    && if [ ! -f node_modules/lightningcss-linux-x64-gnu/lightningcss.linux-x64-gnu.node ]; then \
         n=0; until npm install --no-save --include=optional --prefer-offline --no-audit --no-fund lightningcss-linux-x64-gnu@1.32.0; do \
           n=$((n+1)); \
           if [ "$n" -ge 3 ]; then exit 1; fi; \
           echo "lightningcss native install failed; retrying attempt $((n+1))/3..."; \
           sleep $((n*5)); \
         done; \
       fi \
    && test -f node_modules/lightningcss-linux-x64-gnu/lightningcss.linux-x64-gnu.node

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
HEALTHCHECK --interval=15s --timeout=10s --start-period=60s --retries=8 \
  CMD ["/nodejs/bin/node", "-e", "fetch('http://127.0.0.1:3000/').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"]

# nodejs distroless images already provide the Node executable as ENTRYPOINT.
CMD ["server-cluster.js"]
