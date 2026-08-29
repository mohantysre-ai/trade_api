# Next.js 16 production image (standalone output)
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
RUN npm run build

FROM node:24.20.0-bookworm-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    MARKET_API_URL=http://market-api:8000

# Reuse the non-root user supplied by the official Node image. The runtime
# only needs the Node executable, not npm/corepack/yarn. Removing package
# managers also removes their transitive CVE surface from the production image.
RUN rm -rf /usr/local/lib/node_modules/npm \
        /usr/local/lib/node_modules/corepack \
        /opt/yarn-v* \
    && rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack \
        /usr/local/bin/yarn /usr/local/bin/yarnpkg \
    && mkdir -p .sparkline-cache \
    && chown -R node:node .sparkline-cache

COPY --from=builder /app/public ./public
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
COPY --chown=node:node server-cluster.js ./server-cluster.js

USER node
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

CMD ["node", "server-cluster.js"]
