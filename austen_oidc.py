#!/usr/bin/env python3
"""
Microsoft Entra OIDC human login for Austen — Authorization Code + PKCE.

Ported faithfully from surveyor's hardened id_token verifier and auth flow
(ironbridge-ai/surveyor, GUILD-744). Same security mechanics, retargeted at
Austen's Python stdlib http.server and locked to a SINGLE tenant (Ramsac) by
default rather than surveyor's multi-tenant + dual-IdP model.

Design notes
------------
* **Dormant until configured.** `enabled()` is False until `OIDC_CLIENT_ID` is
  set. While dormant, `require_signed_in()` is a no-op so dev and any not-yet-
  provisioned deploy still boot. In production the manifest keeps
  `auth.mode: access` (Cloudflare Access) in front until OIDC is verified, then
  the operator cuts over to `auth.mode: app` + a Cloudflare Access bypass — see
  deploy/austen.container and the PR description. This ordering means the app is
  never simultaneously edge-open AND self-auth-off.
* **Single tenant (Ramsac).** Authority, JWKS, and the tenant allowlist all
  default to Ramsac's tenant GUID, so only Ramsac accounts can even complete the
  authorize step, and the verifier hard-rejects any token whose `tid` isn't
  Ramsac. Override via OIDC_TENANT_ID / OIDC_* env if that ever changes.
* **The verifier is the security core** and mirrors surveyor's exactly:
  RS256 pinned verifier-side (defeats alg-confusion / alg=none), signature
  checked before any claim is trusted, issuer PAIR check (iss built from the
  token's own tid AND tid on the allowlist), aud == our client_id (fail-closed
  if unconfigured), ver == "2.0", exp/iat/nbf with skew, nonce constant-time
  compared against the per-login nonce (replay defence), oid required, optional
  per-tenant email-domain binding.
* Failure detail goes to logs only; callers render a generic page (no oracle).

Env / secrets (read once at import)
-----------------------------------
  OIDC_CLIENT_ID              enable-gate + required `aud`         (non-secret)
  OIDC_CLIENT_SECRET          code-exchange secret                 (SECRET)
    ...or file /run/secrets/oidc_client_secret
  OIDC_TENANT_ID              tenant GUID; default = Ramsac        (non-secret)
  OIDC_REDIRECT_URI           default ramsac-austen callback       (non-secret)
  OIDC_AUTHORITY              default derived from tenant          (non-secret)
  OIDC_JWKS_URL               default derived from tenant          (non-secret)
  OIDC_TENANT_ALLOWLIST       csv of allowed tids; default tenant  (non-secret)
  OIDC_ALLOWED_EMAIL_DOMAINS  csv; e.g. ramsac.com (recommended)   (non-secret)
  OIDC_SCOPES                 default "openid profile email"       (non-secret)
  SESSION_SECRET              HMAC key for the session cookie      (SECRET)
    ...or file /run/secrets/session_secret; ephemeral per-process if unset
"""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from urllib.parse import urlencode

try:
    import jwt
    from jwt.algorithms import RSAAlgorithm
    import requests
    _DEPS_OK = True
except Exception:  # pragma: no cover - deps absent in a bare stdlib dev checkout
    _DEPS_OK = False

# Ramsac's Entra tenant GUID (same value surveyor allowlists as `ramsac` and
# uses for SHAREPOINT_TENANT_ID). Austen is single-tenant against it.
RAMSAC_TENANT_ID = "c1b2eeb7-ce57-4609-9faf-e693d22956eb"


def _csv(name, default=""):
    return [x.strip().lower() for x in os.environ.get(name, default).split(",") if x.strip()]


def _read_secret(file_name, env_name):
    """Secret from /run/secrets/<file_name> (contract-preferred) or env fallback."""
    path = f"/run/secrets/{file_name}"
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    return os.environ.get(env_name)


CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "").strip()
CLIENT_SECRET = _read_secret("oidc_client_secret", "OIDC_CLIENT_SECRET")
TENANT_ID = os.environ.get("OIDC_TENANT_ID", RAMSAC_TENANT_ID).strip().lower()
REDIRECT_URI = os.environ.get(
    "OIDC_REDIRECT_URI", "https://ramsac-austen.ironbridge.tech/auth/microsoft/callback"
)
AUTHORITY = os.environ.get(
    "OIDC_AUTHORITY", f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
)
JWKS_URL = os.environ.get(
    "OIDC_JWKS_URL", f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"
)
SCOPES = os.environ.get("OIDC_SCOPES", "openid profile email")
TENANT_ALLOWLIST = _csv("OIDC_TENANT_ALLOWLIST", TENANT_ID)
ALLOWED_EMAIL_DOMAINS = _csv("OIDC_ALLOWED_EMAIL_DOMAINS", "")

_SESSION_SECRET = _read_secret("session_secret", "SESSION_SECRET")
_SESSION_EPHEMERAL = _SESSION_SECRET is None
if _SESSION_EPHEMERAL:
    # No configured key: sign with a per-process random key. Sessions then don't
    # survive a restart/redeploy (everyone re-auths, which is cheap/silent) and
    # wouldn't be shared across replicas — fine for a single-container deploy.
    _SESSION_SECRET = secrets.token_urlsafe(48)

COOKIE_NAME = "austen_session"
_IAT_SKEW = 300      # iat may be up to 5 min in the future (surveyor parity)
_CLOCK_SKEW = 120    # exp/nbf tolerance for a node clock ahead of Entra

# --- module-level JWKS cache (thread-safe) ---------------------------------
_jwks_lock = threading.Lock()
_jwks_cache = {}  # url -> (keys_by_kid: dict, expires_at_monotonic: float)


class VerifyError(Exception):
    pass


def enabled():
    """True only when deps are importable AND both the client_id and the client
    secret are configured. Requiring the SECRET (not just the id) means the
    non-secret OIDC_CLIENT_ID can be committed to the Quadlet while OIDC stays
    dormant — it activates on its own once austen_oidc_client_secret lands in
    ai-guild-infra. So a half-configured deploy never gates users out."""
    return _DEPS_OK and bool(CLIENT_ID) and bool(CLIENT_SECRET)


def status_line():
    if not _DEPS_OK:
        return "Entra OIDC: deps missing (PyJWT/requests) — login DISABLED"
    if not CLIENT_ID:
        return "Entra OIDC: dormant (set OIDC_CLIENT_ID to enable in-app login)"
    if not CLIENT_SECRET:
        return (f"Entra OIDC: client_id set but client secret MISSING — dormant. "
                f"Add austen_oidc_client_secret (ai-guild-infra secrets) to activate.")
    key_note = "ephemeral session key" if _SESSION_EPHEMERAL else "configured session key"
    return (
        f"Entra OIDC: ENABLED — tenant {TENANT_ID}, redirect {REDIRECT_URI}, "
        f"domains={ALLOWED_EMAIL_DOMAINS or 'any-in-tenant'}, {key_note}"
    )


# --- authority-derived endpoints -------------------------------------------

def _base_authority():
    return re.sub(r"/v2\.0$", "", AUTHORITY.rstrip("/"))


def _authorize_url():
    return _base_authority() + "/oauth2/v2.0/authorize"


def _token_url():
    return _base_authority() + "/oauth2/v2.0/token"


def _end_session_url():
    return _base_authority() + "/oauth2/v2.0/logout"


# --- signed session cookie (HMAC-SHA256, base64url) ------------------------

def _sign(payload_b):
    return hmac.new(_SESSION_SECRET.encode(), payload_b, hashlib.sha256).digest()


def _b64u_encode(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def _b64u_decode(s):
    return base64.urlsafe_b64decode(s + b"=" * (-len(s) % 4))


def encode_session(data):
    body = _b64u_encode(json.dumps(data, separators=(",", ":")).encode())
    sig = _b64u_encode(_sign(body))
    return (body + b"." + sig).decode()


def decode_session(cookie):
    try:
        body, sig = cookie.encode().split(b".", 1)
        if not hmac.compare_digest(sig, _b64u_encode(_sign(body))):
            return {}
        data = json.loads(_b64u_decode(body))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _read_cookie(handler):
    raw = handler.headers.get("Cookie", "")
    for part in raw.split(";"):
        name, _, value = part.strip().partition("=")
        if name == COOKIE_NAME:
            return value
    return ""


def _get_session(handler):
    return decode_session(_read_cookie(handler))


def _set_session_header(handler, data):
    cookie = encode_session(data)
    handler.send_header(
        "Set-Cookie",
        f"{COOKIE_NAME}={cookie}; Path=/; HttpOnly; Secure; SameSite=Lax",
    )


def _clear_session_header(handler):
    handler.send_header(
        "Set-Cookie",
        f"{COOKIE_NAME}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0",
    )


# --- JWKS resolution (cache per cache-control max-age; refresh once on kid) --

def _load_jwks(url):
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    keys = {k["kid"]: k for k in r.json().get("keys", []) if k.get("kid")}
    if not keys:
        raise ValueError("empty JWKS")
    ttl = 300
    m = re.search(r"max-age=(\d+)", r.headers.get("cache-control", ""))
    if m:
        ttl = int(m.group(1))
    return keys, ttl


def _jwks_keys(force):
    now = time.monotonic()
    with _jwks_lock:
        cached = None if force else _jwks_cache.get(JWKS_URL)
        if cached and cached[1] > now:
            return cached[0]
        keys, ttl = _load_jwks(JWKS_URL)
        _jwks_cache[JWKS_URL] = (keys, now + ttl)
        return keys


def _get_key(kid):
    # key rollover: bypass the cache and refresh once on an unknown kid
    jwk = _jwks_keys(force=False).get(kid)
    if jwk is None:
        jwk = _jwks_keys(force=True).get(kid)
    return jwk


# --- id_token verification (mirrors surveyor's IdTokenVerifier) -------------

def verify_id_token(token, expected_nonce):
    """Return {email, oid, tid, name, exp} on success, else raise VerifyError."""
    if not isinstance(token, str) or token.count(".") != 2:
        raise VerifyError("malformed_jwt")

    header = jwt.get_unverified_header(token)
    if header.get("alg") != "RS256":  # RS256 pinned verifier-side
        raise VerifyError("bad_alg")
    kid = header.get("kid")
    if not kid:
        raise VerifyError("missing_kid")

    jwk = _get_key(kid)
    if jwk is None:
        raise VerifyError("unknown_kid")

    if not CLIENT_ID:  # refuse to run aud-unchecked — misconfig fails closed
        raise VerifyError("aud_unconfigured")

    public_key = RSAAlgorithm.from_jwk(json.dumps(jwk))
    # PyJWT verifies signature (RS256 only), aud==CLIENT_ID, exp, nbf. We turn
    # off iss (dynamic, tid-derived) and iat (custom skew) and check them below.
    claims = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        audience=CLIENT_ID,
        leeway=_CLOCK_SKEW,
        options={
            "require": ["exp", "iat", "aud"],
            "verify_iss": False,
            "verify_iat": False,
        },
    )

    now = time.time()

    if claims.get("ver") != "2.0":
        raise VerifyError("invalid_version")

    # Issuer PAIR check: template built from the token's OWN tid, AND tid on the
    # allowlist. Template-only accepts any tenant; allowlist-only accepts a
    # forged issuer string — both are required.
    tid = claims.get("tid")
    if not isinstance(tid, str) or not tid:
        raise VerifyError("invalid_issuer")
    iss = str(claims.get("iss", "")).rstrip("/")
    if iss != f"https://login.microsoftonline.com/{tid}/v2.0":
        raise VerifyError("invalid_issuer")
    tid_lc = tid.lower()
    if tid_lc not in TENANT_ALLOWLIST:
        raise VerifyError("tenant_not_allowed")

    iat = claims.get("iat")
    if not isinstance(iat, (int, float)) or iat > now + _IAT_SKEW:
        raise VerifyError("invalid_issued_at")

    # azp == client_id when present (cheap defence-in-depth; tolerate absence)
    azp = claims.get("azp")
    if azp is not None and azp != CLIENT_ID:
        raise VerifyError("invalid_azp")

    # nonce: mandatory constant-time replay defence
    nonce = claims.get("nonce", "")
    if not (nonce and expected_nonce and hmac.compare_digest(str(nonce), str(expected_nonce))):
        raise VerifyError("nonce_mismatch")

    oid = claims.get("oid")
    if not isinstance(oid, str) or not oid:
        raise VerifyError("missing_oid")

    email = (claims.get("email") or claims.get("preferred_username") or "").strip().lower()

    # Optional per-tenant email-domain binding: the email/preferred_username
    # claim is otherwise shapeable by a tenant admin.
    if ALLOWED_EMAIL_DOMAINS:
        domain = email.split("@")[-1] if "@" in email else ""
        if not domain or domain not in ALLOWED_EMAIL_DOMAINS:
            raise VerifyError("email_domain_not_allowed")

    return {
        "email": email,
        "oid": oid,
        "tid": tid_lc,
        "name": claims.get("name") or claims.get("preferred_username"),
        "exp": claims.get("exp"),
    }


# --- request-side helpers (used by feedback_server.DigestHandler) -----------

def _b64url_rand(n):
    return base64.urlsafe_b64encode(secrets.token_bytes(n)).rstrip(b"=").decode()


def current_user(handler):
    """Resolve the signed-in identity: OIDC session (primary) then the
    Cloudflare-Access header (redundancy). Returns a lowercased email or None."""
    sess = _get_session(handler)
    email = sess.get("email")
    exp = sess.get("exp")
    if email and (not exp or exp > time.time()):
        return email
    hdr = handler.headers.get("Cf-Access-Authenticated-User-Email")
    if hdr:
        return hdr.strip().lower()
    return None


def require_signed_in(handler, path):
    """Gate a request. Return True to proceed; otherwise write a 302 to the
    login route and return False. No-op (returns True) while OIDC is dormant —
    edge Cloudflare Access is the gate until the operator cuts over."""
    if not enabled():
        return True
    if path == "/healthz" or path.startswith("/auth/"):
        return True
    if current_user(handler):
        return True
    handler.send_response(302)
    handler.send_header("Location", "/auth/microsoft")
    handler.end_headers()
    return False


def handle_login(handler):
    if not enabled():
        _send_html(handler, 503, _not_configured_html())
        return
    verifier = _b64url_rand(32)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    state = _b64url_rand(24)
    nonce = _b64url_rand(24)
    query = urlencode({
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "response_mode": "query",
        "scope": SCOPES,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    handler.send_response(302)
    handler.send_header("Location", _authorize_url() + "?" + query)
    _set_session_header(handler, {"pkce": verifier, "state": state, "nonce": nonce})
    handler.end_headers()


def handle_callback(handler, params):
    """params: dict of str->str parsed from the callback query string."""
    sess = _get_session(handler)
    try:
        if params.get("error"):
            raise VerifyError("idp_error:" + params.get("error", ""))

        state = params.get("state", "")
        expected_state = sess.get("state", "")
        if not (state and expected_state and hmac.compare_digest(state, expected_state)):
            raise VerifyError("bad_state")

        code = params.get("code", "")
        if not code:
            raise VerifyError("missing_code")

        resp = requests.post(
            _token_url(),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET or "",
                "code_verifier": sess.get("pkce", ""),
            },
            timeout=10,
        )
        if resp.status_code != 200:
            raise VerifyError(f"token_endpoint:{resp.status_code}")
        id_token = resp.json().get("id_token")
        if not isinstance(id_token, str):
            raise VerifyError("no_id_token")

        claims = verify_id_token(id_token, sess.get("nonce", ""))
        email = claims["email"]
        if not email:
            raise VerifyError("no_email_claim")
    except Exception as e:
        print(f"  OIDC login failed: {e}")
        _send_html(handler, 401, _login_failed_html(), clear_session=True)
        return

    print(f"  OIDC login ok: {email} (oid={claims['oid']} tid={claims['tid']})")
    handler.send_response(302)
    handler.send_header("Location", "/")
    # Renew the session: drop the transient pkce/state/nonce, write identity.
    _set_session_header(handler, {"email": email, "oid": claims["oid"],
                                  "tid": claims["tid"], "exp": claims["exp"]})
    handler.end_headers()


def handle_logout(handler):
    handler.send_response(302)
    handler.send_header("Location", _end_session_url() if enabled() else "/")
    _clear_session_header(handler)
    handler.end_headers()


def _send_html(handler, status, html, clear_session=False):
    body = html.encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    if clear_session:
        _clear_session_header(handler)
    handler.end_headers()
    handler.wfile.write(body)


_PAGE = (
    '<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>'
    '<style>body{{font-family:Inter,system-ui,sans-serif;max-width:520px;'
    "margin:96px auto;padding:0 24px;color:#18181b}}h1{{font-size:18px;"
    "margin:0 0 8px}}p{{color:#52525b;font-size:14px;line-height:1.6}}"
    "code{{background:#f4f4f5;padding:1px 6px;border-radius:4px;"
    "font-family:ui-monospace,monospace}}a{{color:#2563eb;text-decoration:none}}"
    "a:hover{{text-decoration:underline}}</style></head><body>"
    "<h1>{title}</h1><p>{body}</p></body></html>"
)


def _not_configured_html():
    return _PAGE.format(
        title="Sign-in not configured",
        body=("Microsoft sign-in is not configured on this server. Set "
              "<code>OIDC_CLIENT_ID</code> (and the related OIDC_* env) to enable it."),
    )


def _login_failed_html():
    return _PAGE.format(
        title="Sign-in failed",
        body=('We could not complete your Microsoft sign-in. This can happen if the '
              'request expired or was tampered with. <a href="/auth/microsoft">Try again &rarr;</a>'),
    )
