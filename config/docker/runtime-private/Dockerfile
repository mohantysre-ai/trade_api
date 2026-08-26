# Private runtime bundle: backend/.env, Cloudflare tunnel credentials, and a
# live snapshot of the desk/backend/eod Docker volumes — staged by
# config/startup/pack-runtime-private.ps1.
#
# THIS IMAGE CONTAINS LIVE SECRETS (Angel One key, Cloudflare tunnel token).
# The Hub repo for this image (smohanty010620/sigq-runtime-private) must be
# created as PRIVATE before the first push, and must stay private forever:
# no flipping it public, no adding outside collaborators, no re-pushing its
# layers to any other registry. If a secret baked in here ever needs to be
# considered compromised, rotate it — deleting/overwriting the tag does not
# remove it from any image someone already pulled.
FROM alpine:3.21
COPY seed/ /runtime-private/
CMD ["true"]