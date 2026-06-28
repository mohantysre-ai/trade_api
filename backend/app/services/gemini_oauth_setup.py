"""
One-time Gemini OAuth login.
Shares quota with the Gemini portal (aistudio.google.com).

Usage:
    python gemini_oauth_setup.py                      # interactive
    python gemini_oauth_setup.py --client-secret client_secret.json
    python gemini_oauth_setup.py --headless           # prints URL (step 1)
    python gemini_oauth_setup.py --headless --redirect-uri http://localhost:3000/callback
    python gemini_oauth_setup.py --complete CODE      # finishes with auth code (step 2)
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import sys
import json

import_path = os.path.dirname(os.path.abspath(__file__))
if import_path not in sys.path:
    sys.path.append(import_path)

os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

# Use the Gemini Generative Language API scopes so the token works
# with the Gemini API (shares quota with aistudio.google.com).
SCOPES = [
    "https://www.googleapis.com/auth/generative-language.retriever",
]

TOKEN_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(TOKEN_DIR, "gemini_oauth_token.json")
PKCE_STATE_PATH = os.path.join(TOKEN_DIR, ".gemini_oauth_pkce_state.json")


def _generate_code_verifier() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("utf-8").rstrip("=")


def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def _build_auth_url(client_secrets_file: str, verifier: str, redirect_uri: str | None = None) -> tuple[str, dict]:
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(client_secrets_file, SCOPES)
    flow.redirect_uri = redirect_uri or "urn:ietf:wg:oauth:2.0:oob"
    flow.code_verifier = verifier
    challenge = _code_challenge(verifier)
    auth_url, state = flow.authorization_url(
        prompt="consent",
        access_type="offline",
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    with open(client_secrets_file) as f:
        client_id = json.load(f)["installed"]["client_id"]
    meta = {
        "state": state,
        "code_verifier": verifier,
        "client_id": client_id,
        "redirect_uri": flow.redirect_uri,
    }
    return auth_url, meta


def headless_flow(client_secrets_file: str, redirect_uri: str | None = None) -> None:
    """Print the auth URL and save PKCE verifier for later completion."""
    verifier = _generate_code_verifier()
    auth_url, meta = _build_auth_url(client_secrets_file, verifier, redirect_uri)
    with open(PKCE_STATE_PATH, "w") as f:
        json.dump(meta, f, indent=2)

    print("=" * 70)
    print("Open this URL in your browser (signed in with the same account as AI Studio):")
    print()
    print(auth_url)
    print()
    print("After granting permission, copy the authorisation code from the page")
    print("and run:")
    print(f"  python {sys.argv[0]} --complete <AUTH_CODE>")
    print("=" * 70)


def complete_flow(client_secrets_file: str, auth_code: str) -> dict:
    """Complete the OAuth flow using the authorization code and saved PKCE state."""
    if not os.path.isfile(PKCE_STATE_PATH):
        print(f"ERROR: PKCE state file not found at {PKCE_STATE_PATH}")
        print("Run --headless first to generate the auth URL.")
        sys.exit(1)

    with open(PKCE_STATE_PATH) as f:
        meta = json.load(f)

    verifier = meta["code_verifier"]
    state = meta["state"]
    redirect_uri = meta.get("redirect_uri", "urn:ietf:wg:oauth:2.0:oob")

    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(client_secrets_file, SCOPES)
    flow.redirect_uri = redirect_uri
    flow.code_verifier = verifier

    redirect_uri = f"{redirect_uri}?code={auth_code}&state={state}"
    try:
        flow.fetch_token(authorization_response=redirect_uri)
        creds = flow.credentials
    except Exception as exc:
        print(f"ERROR fetching token: {exc}")
        sys.exit(1)

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }

    with open(TOKEN_PATH, "w") as f:
        json.dump(token_data, f, indent=2)

    # Clean up PKCE state
    try:
        os.remove(PKCE_STATE_PATH)
    except OSError:
        pass

    print(f"\nSUCCESS! Token saved to: {TOKEN_PATH}")
    print("\nAdd this line to your .env (in the backend/app/services folder):")
    print(f"    GEMINI_OAUTH_TOKEN_PATH={TOKEN_PATH}")
    return token_data


def interactive_flow(client_secrets_file: str) -> dict:
    """Open browser for interactive OAuth consent."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("ERROR: google-auth-oauthlib is required. Run: pip install google-auth-oauthlib")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, SCOPES)
    creds = flow.run_local_server(port=0)

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }

    with open(TOKEN_PATH, "w") as f:
        json.dump(token_data, f, indent=2)

    print(f"\nSUCCESS! Token saved to: {TOKEN_PATH}")
    print("\nAdd this line to your .env (in the backend/app/services folder):")
    print(f"    GEMINI_OAUTH_TOKEN_PATH={TOKEN_PATH}")
    return token_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gemini OAuth Setup")
    parser.add_argument("--client-secret", default=None,
                        help="Path to OAuth client_secret.json (default: auto-detect next to this script)")
    parser.add_argument("--headless", action="store_true",
                        help="Print URL instead of opening browser (useful on servers)")
    parser.add_argument("--complete", default=None,
                        help="Authorization code from the OAuth consent page (use after --headless)")
    parser.add_argument("--redirect-uri", default=None,
                        help="OAuth redirect URI (default: urn:ietf:wg:oauth:2.0:oob)")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidate_secret = args.client_secret or os.path.join(script_dir, "client_secret.json")

    if not os.path.isfile(candidate_secret):
        print(f"ERROR: client_secret.json not found at: {candidate_secret}")
        print()
        print("Get it from: https://console.cloud.google.com/apis/credentials")
        print("  1. Create OAuth 2.0 Client ID → Application type: Desktop app")
        print("  2. Download JSON and save it as 'client_secret.json' next to this script.")
        sys.exit(1)

    if args.headless:
        headless_flow(candidate_secret, args.redirect_uri)
    elif args.complete:
        complete_flow(candidate_secret, args.complete.strip())
    else:
        interactive_flow(candidate_secret)