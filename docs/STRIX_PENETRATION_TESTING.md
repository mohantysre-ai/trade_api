# Strix Penetration Testing

SIGQ integrates [Strix](https://github.com/usestrix/strix) for authorized,
non-destructive repository and web-application security assessments.

## GitHub configuration

Add these repository **Actions secrets**:

| Secret | Required | Purpose |
| --- | --- | --- |
| `STRIX_LLM_API_KEY` | Yes | Dedicated LLM API key used only by Strix |
| `STRIX_TEST_USERNAME` | Authenticated scans only | Non-production SIGQ test account |
| `STRIX_TEST_PASSWORD` | Authenticated scans only | Test-account password |

Optional **Actions variables**:

| Variable | Default | Purpose |
| --- | --- | --- |
| `STRIX_LLM` | `openai/gpt-5.4` | Strix model identifier |
| `STRIX_WEB_TARGET` | `https://sigq.in` | Default deployed application |
| `STRIX_ALLOWED_HOSTS` | `sigq.in,www.sigq.in` | Exact comma-separated web host allowlist |
| `STRIX_LOGIN_URL` | Empty | Test-account login page |

Use a dedicated, low-privilege test user. Never configure a broker, admin,
production trading, or personal account for automated penetration testing.

## Workflow behavior

- Pull requests from branches in this repository receive a budget-limited quick
  diff scan of the checked-out source.
- A standard full repository scan runs every Sunday at 03:30 UTC.
- Manual runs support `repository`, `web`, and `multi` target modes.
- Web targets must use HTTPS port 443 and exactly match `STRIX_ALLOWED_HOSTS`.
- Authenticated testing reads credentials from secrets and never places them in
  command-line arguments.
- Reports are scrubbed for configured credentials and retained as private
  workflow artifacts for 14 days.
- Strix headless mode exits non-zero when it validates vulnerabilities, so the
  workflow becomes a security gate.

The rules of engagement are maintained in
`.strix/pentest-instructions.md`. Do not weaken the target restrictions or
non-destructive controls for production scans.

## Manual GitHub run

Open **Actions → Strix authorized penetration testing → Run workflow** and
choose:

- `repository`: source-aware scan only;
- `web`: black-box scan of the allowlisted deployment;
- `multi`: repository plus allowlisted deployment;
- `authenticated`: use the dedicated test-account secrets.

Start with `quick`. Use `standard` or `deep` only during an approved testing
window because they take longer and can cost more.

## Local use

Strix requires Docker and an LLM key. Install the same pinned version used by
CI, then call the guarded wrapper:

```bash
python -m pip install 'strix-agent==1.5.3'
export STRIX_LLM='openai/gpt-5.4'
export LLM_API_KEY='your-dedicated-key'

# Source repository
bash scripts/run-strix.sh repository

# Allowlisted black-box target
STRIX_WEB_TARGET='https://sigq.in' bash scripts/run-strix.sh web

# Source plus deployed app
STRIX_WEB_TARGET='https://sigq.in' bash scripts/run-strix.sh multi
```

For an authenticated local test, provide only a dedicated test account through
environment variables:

```bash
export STRIX_AUTHENTICATED=true
export STRIX_TEST_USERNAME='security-test@example.com'
export STRIX_TEST_PASSWORD='use-a-secret-manager'
export STRIX_LOGIN_URL='https://sigq.in/login'
STRIX_WEB_TARGET='https://sigq.in' bash scripts/run-strix.sh web
```

Do not commit credentials, generated runtime instruction files, or Strix
reports.
