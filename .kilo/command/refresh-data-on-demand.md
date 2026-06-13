---
description: Refresh all backend API data on demand and save the updated state to a snapshot file.
agent: code
---
Trigger a synchronous live refresh of all backend API data when the user says "refresh the data on demand".

Optional arguments:
- `--pool <name>`: pass a pool override to the backend refresh endpoint.
- `--prompt <text>`: pass a custom filter prompt to the backend refresh endpoint.

!`powershell -NoProfile -ExecutionPolicy Bypass -File ".kilo/scripts/refresh-data-on-demand.ps1" $ARGUMENTS`
