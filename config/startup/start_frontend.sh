#!/bin/bash
cd "$(dirname "$0")/iros-terminal/iros-terminal"
exec npm run dev -- -p 5000
