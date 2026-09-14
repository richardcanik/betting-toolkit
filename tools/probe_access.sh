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

echo "=== čím sa dopytujeme: curl vs Python ==="
# Cloudflare rozlišuje klientov aj podľa TLS odtlačku, nie iba podľa hlavičiek.
# Ak curl prejde a urllib nie z tej istej IP, príčinou je klient, nie krajina.
U="https://m.nike.sk/api/v1/client-config"
echo "curl                : $(curl -s -m 20 -o /dev/null -w '%{http_code}' -A "$UA" "$U")"
python3 - "$U" "$UA" <<'PY'
import sys, urllib.request, urllib.error
url, ua = sys.argv[1], sys.argv[2]
def get(name, headers):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=25) as r:
            print(f"{name:20s}: {r.status}")
    except urllib.error.HTTPError as e:
        print(f"{name:20s}: {e.code}")
    except Exception as e:
        print(f"{name:20s}: {type(e).__name__}")
get("urllib (naše hl.)", {"User-Agent": ua, "Accept": "application/json",
                          "Accept-Encoding": "gzip", "Referer": "https://m.nike.sk/"})
get("urllib (plné hl.)", {
    "User-Agent": ua,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "sk-SK,sk;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none", "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
})
PY

echo
echo "=== dosiahne sa ponuka pri mitigation BLOCK? ==="
for q in "/api-gw/nikeone/v1/menu?live=true&prematch=true&showMatchCounts=true&channel=Mobile" \
         "/api-gw/nikeone/v1/boxes/search/mobile?boxId=bi-7-18-157&prematch=true&live=false&results=false&channel=Mobile"
do
  n=$(curl -s -m 25 -A "$UA" -H 'Content-Language: sk' "https://m.nike.sk$q" | wc -c)
  echo "   ${q:0:46}...  $n B"
done
