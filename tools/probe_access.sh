#!/usr/bin/env bash
# Characterises how Nike responds from wherever this runs.
#
# A 403 alone does not say why. Geo-blocking, datacenter-IP blocking and bot
# defence all look the same from a status code, and they have different
# remedies: a Slovak VPS fixes the first, only a residential proxy fixes the
# second, and the third may just need the browser handshake. The response
# headers and body usually distinguish them, so they are printed.
set -u
UA='Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'

echo "odchádzajúca IP: $(curl -s -m 15 https://api.ipify.org || echo '?')"
echo "geo:             $(curl -s -m 15 https://ipinfo.io/json 2>/dev/null \
    | tr -d '{}", ' | grep -E '^(country|org|region):' | tr '\n' ' ' || echo '?')"
echo

for url in \
  "https://m.nike.sk/" \
  "https://m.nike.sk/api/v1/client-config" \
  "https://m.nike.sk/api-gw/nikeone/v1/init-data/mobile" \
  "https://www.nike.sk/robots.txt"
do
  echo "── $url"
  code=$(curl -s -m 25 -o /tmp/probe.body -D /tmp/probe.head -A "$UA" \
         -H 'Accept-Language: sk-SK,sk;q=0.9' -w '%{http_code}' "$url" || echo 000)
  echo "   status: $code"
  grep -iE '^(server|x-|cf-ray|via|set-cookie: TS)' /tmp/probe.head \
    | head -4 | sed 's/^/   /'
  head -c 220 /tmp/probe.body | tr -d '\n' | sed 's/^/   telo: /'
  echo; echo
done
