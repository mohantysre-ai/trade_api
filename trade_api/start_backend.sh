#!/bin/bash
cd "$(dirname "$0")/backend/backend"
exec python angel_one_feed.py --serve
