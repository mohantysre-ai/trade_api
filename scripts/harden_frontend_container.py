from pathlib import Path

root = Path(__file__).resolve().parents[1]
dockerfile = root / "iros-terminal" / "Dockerfile"
text = dockerfile.read_text(encoding="utf-8")

text = text.replace("FROM node:20-bookworm-slim AS deps", "FROM node:24.20.0-bookworm-slim AS deps")
text = text.replace("FROM node:20-bookworm-slim AS builder", "FROM node:24.20.0-bookworm-slim AS builder")
text = text.replace("FROM node:20-bookworm-slim AS runner", "FROM node:24.20.0-bookworm-slim AS runner")

old = '''RUN apt-get update \\
    && apt-get install -y --no-install-recommends curl \\
    && rm -rf /var/lib/apt/lists/* \\
    && groupadd --system --gid 1001 nodejs \\
    && useradd --system --uid 1001 --gid nodejs nextjs
'''
new = '''# Reuse the non-root user supplied by the official Node image. The runtime\n# only needs the Node executable, not npm/corepack/yarn. Removing package\n# managers also removes their transitive CVE surface from the production image.\nRUN rm -rf /usr/local/lib/node_modules/npm \\
        /usr/local/lib/node_modules/corepack \\
        /opt/yarn-v* \\
    && rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack \\
        /usr/local/bin/yarn /usr/local/bin/yarnpkg \\
    && mkdir -p .sparkline-cache \\
    && chown -R node:node .sparkline-cache\n'''
if old not in text:
    raise SystemExit("Expected runtime apt/user block not found; Dockerfile changed unexpectedly")
text = text.replace(old, new)
text = text.replace("COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./", "COPY --from=builder --chown=node:node /app/.next/standalone ./")
text = text.replace("COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static", "COPY --from=builder --chown=node:node /app/.next/static ./.next/static")
text = text.replace("COPY --chown=nextjs:nodejs server-cluster.js ./server-cluster.js", "COPY --chown=node:node server-cluster.js ./server-cluster.js")
text = text.replace("\nRUN mkdir -p .sparkline-cache && chown -R nextjs:nodejs .sparkline-cache\n\nUSER nextjs", "\nUSER node")
text = text.replace("CMD curl -fsS http://127.0.0.1:3000/ || exit 1", "CMD node -e \"fetch('http://127.0.0.1:3000/').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))\"")

dockerfile.write_text(text, encoding="utf-8")
print("Hardened iros-terminal Dockerfile for Node 24 LTS with package managers removed from runtime")
