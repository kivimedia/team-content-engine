#!/usr/bin/env bash
# Prove the canonical TCE route on bot.kivimedia.co is wired and guarded.
#
# TCE is served at https://bot.kivimedia.co/tce/ (recorder at /tce/record) by
# /etc/nginx/snippets/kmbot-extra-tce.conf, which the KM BOT vhost picks up
# through its `include /etc/nginx/snippets/kmbot-extra-*.conf;` line. KM BOT's
# installer (install/nginx-setup.sh in the kmbot repo) regenerates that vhost
# on every KM BOT deploy, so the two facts this script asserts are exactly the
# two a refresh could break: the include is still there, and the snippet is
# still there and still says what it must. Then it proves the guard from the
# outside: anonymous 401, authenticated 200, on every surface the recorder
# needs.
#
# Run on the VPS as ziv (passwordless sudo):
#   bash scripts/verify-bot-route.sh              # assert the current state
#   bash scripts/verify-bot-route.sh --refresh    # run KM BOT's nginx installer
#                                                 # first, then assert - the
#                                                 # regression check proper
#
# Authenticated probes need the editor's basic-auth pair in the environment as
# TCE_EDITOR_BASIC_AUTH="user:password". Without it they are SKIPPED and the
# script says so; it never prints the pair, the editor key, or any header.
set -uo pipefail

DOMAIN="${TCE_BOT_DOMAIN:-bot.kivimedia.co}"
SITE="/etc/nginx/sites-enabled/kmbot-kivimedia"
SNIPPET="/etc/nginx/snippets/kmbot-extra-tce.conf"
ENV_FILE="${TCE_ENV_FILE:-/home/ziv/team-content-engine/.env}"
KMBOT_HOME="${KMBOT_HOME:-/opt/kmbot}"

PASS=0; FAIL=0; SKIP=0
ok(){ PASS=$((PASS+1)); echo "  ok   $1"; }
bad(){ FAIL=$((FAIL+1)); echo "  FAIL $1 :: ${2:-}"; }
skip(){ SKIP=$((SKIP+1)); echo "  skip $1 :: ${2:-}"; }

if [ "${1:-}" = "--refresh" ]; then
  echo "== refreshing KM BOT nginx configuration first ($KMBOT_HOME/install/nginx-setup.sh)"
  if [ -f "$KMBOT_HOME/install/nginx-setup.sh" ]; then
    if bash "$KMBOT_HOME/install/nginx-setup.sh"; then
      ok "KM BOT nginx-setup.sh completed"
    else
      bad "KM BOT nginx-setup.sh failed" "see its output above"
    fi
  else
    bad "no KM BOT installer at $KMBOT_HOME/install/nginx-setup.sh"
  fi
fi

echo "== the vhost still carries the extension point"
if sudo -n grep -q 'include /etc/nginx/snippets/kmbot-extra-\*\.conf;' "$SITE" 2>/dev/null; then
  ok "$SITE includes kmbot-extra-*.conf"
else
  bad "$SITE does not include kmbot-extra-*.conf" "a KM BOT refresh dropped the include, or the site file moved"
fi

echo "== the TCE snippet is present, private, and says what it must"
if sudo -n test -f "$SNIPPET"; then
  ok "$SNIPPET exists"
  MODE="$(sudo -n stat -c '%a %U' "$SNIPPET")"
  [ "$MODE" = "600 root" ] && ok "mode 600 root (it carries the editor key)" || bad "mode is '$MODE', wanted '600 root'"
  for needle in \
    'location ^~ /tce/' \
    'auth_basic_user_file /etc/nginx/tce.htpasswd;' \
    'rewrite ^/tce(/.*)$ $1 break;' \
    'proxy_pass http://127.0.0.1:8200;' \
    'proxy_set_header Authorization "";' \
    'proxy_set_header X-TCE-Editor-Key' \
    'client_max_body_size 2g;' \
    'proxy_request_buffering off;' \
    'proxy_read_timeout 300s;'
  do
    if sudo -n grep -qF -- "$needle" "$SNIPPET"; then ok "snippet has: $needle"; else bad "snippet lacks: $needle"; fi
  done
  # The injected key must be the one the app checks. Compare digests, never values.
  if [ -r "$ENV_FILE" ] || sudo -n test -r "$ENV_FILE"; then
    ENV_KEY_SUM="$(sudo -n grep -E '^TCE_PRIVATE_ACCESS_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d "\"'" | sha256sum | cut -c1-16)"
    SNIP_KEY_SUM="$(sudo -n grep -E 'X-TCE-Editor-Key' "$SNIPPET" | head -1 | sed -E 's/.*X-TCE-Editor-Key[[:space:]]+"?([^";]*)"?;.*/\1/' | sha256sum | cut -c1-16)"
    if [ -n "$ENV_KEY_SUM" ] && [ "$ENV_KEY_SUM" = "$SNIP_KEY_SUM" ]; then
      ok "snippet injects the same editor key the app checks"
    else
      bad "snippet editor key differs from TCE_PRIVATE_ACCESS_KEY in $ENV_FILE" "authenticated requests would reach the app and be refused"
    fi
  else
    skip "editor key comparison" "$ENV_FILE not readable"
  fi
else
  bad "$SNIPPET is missing" "the /tce/ route is gone"
fi

echo "== no backups where nginx would load them"
STRAY_SITES="$(ls /etc/nginx/sites-enabled/ 2>/dev/null | grep -E '\.(bak|orig|old|save)' || true)"
[ -z "$STRAY_SITES" ] && ok "sites-enabled has no backup files" || bad "backup files in sites-enabled" "$STRAY_SITES"
STRAY_SNIPS="$(sudo -n ls /etc/nginx/snippets/ 2>/dev/null | grep '^kmbot-extra-' | grep -v '\.conf$' || true)"
[ -z "$STRAY_SNIPS" ] && ok "no backup files in the wildcard snippet dir" || bad "backup-looking files next to the extras" "$STRAY_SNIPS"

echo "== nginx accepts the whole configuration"
if sudo -n nginx -t >/tmp/tce-verify-nginx-t.log 2>&1; then ok "nginx -t"; else bad "nginx -t" "$(tail -2 /tmp/tce-verify-nginx-t.log | tr '\n' ' ')"; fi

echo "== the guard, from the outside"
code_anon(){ curl -s -o /dev/null -w '%{http_code}' -m 20 "https://$DOMAIN$1" 2>/dev/null || echo 000; }
code_auth(){ curl -s -o /dev/null -w '%{http_code}' -m 20 -u "$TCE_EDITOR_BASIC_AUTH" "https://$DOMAIN$1" 2>/dev/null || echo 000; }
redir(){ curl -s -o /dev/null -w '%{http_code} %{redirect_url}' -m 20 "https://$DOMAIN$1" 2>/dev/null || echo 000; }

R="$(redir /tce)";  [ "$R" = "301 https://$DOMAIN/tce/" ] && ok "/tce -> 301 /tce/" || bad "/tce" "$R"
R="$(redir /tce/)"; [ "$R" = "302 https://$DOMAIN/tce/record" ] && ok "/tce/ -> 302 /tce/record" || bad "/tce/" "$R"

SURFACES="/tce/record /tce/recording.css /tce/recording.js /tce/dashboard /tce/api/v1/production/recording-queue /tce/api/v1/content-runs /tce/api/v1/health"
for p in $SURFACES; do
  C="$(code_anon "$p")"
  [ "$C" = "401" ] && ok "anonymous $p -> 401" || bad "anonymous $p -> $C, wanted 401" "the guard is off or the route is gone"
done
if [ -n "${TCE_EDITOR_BASIC_AUTH:-}" ]; then
  for p in $SURFACES; do
    C="$(code_auth "$p")"
    [ "$C" = "200" ] && ok "authenticated $p -> 200" || bad "authenticated $p -> $C, wanted 200"
  done
  # The recorder must not reference a root favicon: that request would leave the
  # /tce/ prefix and hit the KM BOT guard with the wrong realm.
  if curl -s -m 20 -u "$TCE_EDITOR_BASIC_AUTH" "https://$DOMAIN/tce/record" 2>/dev/null | grep -q 'rel="icon" href="data:,"'; then
    ok "recorder ships an inline (data:) favicon, no root request"
  else
    bad "recorder favicon is not inline" "a /favicon.ico request would 401 against the KM BOT realm"
  fi
else
  skip "authenticated probes" "set TCE_EDITOR_BASIC_AUTH=user:password in the environment"
fi

echo
echo "passed $PASS, failed $FAIL, skipped $SKIP"
[ "$FAIL" -eq 0 ]
