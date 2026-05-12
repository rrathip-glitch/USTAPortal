#!/bin/bash
# Bright Data Web Unlocker probe helper. Usage:
#   ./probe.sh GET <url> <outfile>
#   ./probe.sh POST <url> <outfile> <body-json>
# Requires BRIGHT_DATA_API_KEY in environment.

set -e

METHOD="$1"
URL="$2"
OUT="$3"
BODY="$4"

if [ -z "$BRIGHT_DATA_API_KEY" ]; then
  export BRIGHT_DATA_API_KEY=$(grep -E "^BRIGHT_DATA_API_KEY=" /home/user/USTAPortal/.env | cut -d= -f2-)
fi
if [ -z "$BRIGHT_DATA_API_KEY" ]; then
  echo "Missing BRIGHT_DATA_API_KEY" >&2
  exit 1
fi

if [ "$METHOD" = "GET" ]; then
  PAYLOAD=$(jq -nc --arg url "$URL" '{zone:"web_unlocker1",url:$url,format:"raw",country:"us",method:"GET"}')
else
  PAYLOAD=$(jq -nc --arg url "$URL" --arg body "$BODY" '{zone:"web_unlocker1",url:$url,format:"raw",country:"us",method:"POST",body:$body,headers:{"Content-Type":"application/json"}}')
fi

curl -sS -k -X POST https://api.brightdata.com/request \
  -H "Authorization: Bearer $BRIGHT_DATA_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" -o "$OUT" -w "%{http_code} %{size_download}\n"
