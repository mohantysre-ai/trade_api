# syntax=docker/dockerfile:1
# IROS Cloudflare Tunnel — same image on every machine.
# Official cloudflared defaults to "version" and exits. This image always runs the tunnel.
#
# Secrets stay OUT of the image. Mount at runtime:
#   credentials.json → /etc/cloudflared/credentials.json
#
# Build + push:
#   docker build -t smohanty010620/cloudflared:latest config/cloudflare
#   docker push smohanty010620/cloudflared:latest

FROM cloudflare/cloudflared:latest

COPY config.docker.yml /etc/cloudflared/config.yml

ENTRYPOINT ["cloudflared", "--no-autoupdate"]
CMD ["tunnel", "--config", "/etc/cloudflared/config.yml", "run", "iros-desk"]
