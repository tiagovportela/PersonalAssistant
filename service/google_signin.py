"""The layer's own Google sign-in: my user account, read-only, standard library only.

`pwi google connect CLIENT_JSON` runs the OAuth flow for installed apps: a
loopback page on 127.0.0.1 receives the code, PKCE protects it, and only
read-only scopes are requested. If Google grants anything that can write, the
sign-in is revoked and refused. The refresh token is kept in GNOME Keyring
through `secret-tool` (package libsecret-tools), or, if that isn't installed,
in an owner-only file. Access tokens live in memory only.

Phase 3's Calendar reading uses this same sign-in, adding its own read-only scope.
"""

import base64
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import paths

AUTH_URL = os.environ.get("PWI_GOOGLE_AUTH_URL", "https://accounts.google.com/o/oauth2/v2/auth")
OAUTH_URL = os.environ.get("PWI_GOOGLE_OAUTH_URL", "https://oauth2.googleapis.com")
SCOPES = ["openid", "email",
          "https://www.googleapis.com/auth/chat.spaces.readonly",
          "https://www.googleapis.com/auth/chat.messages.readonly",
          "https://www.googleapis.com/auth/chat.memberships.readonly"]
# Google may report these in another form; all of them only identify me or read.
READ_ONLY = set(SCOPES) | {"https://www.googleapis.com/auth/userinfo.email"}
CLIENT_PATH = paths.DATA_DIR / "google_client.json"
TOKEN_FILE = paths.DATA_DIR / "google_token.json"  # only when secret-tool isn't installed
KEYRING = ["service", "pwi", "account", "google"]
TIMEOUT = 20


class GoogleError(Exception):
    """Something to tell me in plain words: not connected, refused, Google unreachable."""


# Where the refresh token lives ---------------------------------------------------------

def keyring_available():
    return os.environ.get("PWI_SECRET_STORE") != "file" and shutil.which("secret-tool") is not None


def save_token(record):
    data = json.dumps(record)
    if keyring_available():
        done = subprocess.run(["secret-tool", "store", "--label=Work layer Google sign-in", *KEYRING],
                              input=data, capture_output=True, text=True, timeout=TIMEOUT)
        if done.returncode == 0:
            TOKEN_FILE.unlink(missing_ok=True)
            return "GNOME Keyring"
    paths.DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(data)
    return str(TOKEN_FILE)


def load_token():
    if keyring_available():
        found = subprocess.run(["secret-tool", "lookup", *KEYRING], capture_output=True, text=True, timeout=TIMEOUT)
        if found.returncode == 0 and found.stdout.strip():
            return json.loads(found.stdout)
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text())
    return None


def forget_token():
    if keyring_available():
        subprocess.run(["secret-tool", "clear", *KEYRING], capture_output=True, timeout=TIMEOUT)
    TOKEN_FILE.unlink(missing_ok=True)


def client():
    """The OAuth client from the Google Cloud project: {client_id, client_secret}."""
    if not CLIENT_PATH.exists():
        raise GoogleError("The layer isn't signed in to Google. Run: pwi google connect CLIENT_JSON")
    data = json.loads(CLIENT_PATH.read_text())
    return data.get("installed") or data.get("web") or data


# Talking to Google --------------------------------------------------------------------

def post(url, fields):
    request = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise GoogleError(f"Google refused the request ({e.code}): {detail}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise GoogleError(f"Google couldn't be reached: {e}") from None


def get_json(url, token, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        if e.code in (401, 403):
            raise GoogleError(f"Google refused access ({e.code}). If this keeps happening, sign in again with: "
                              f"pwi google connect CLIENT_JSON. {detail}") from None
        raise GoogleError(f"Google answered {e.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise GoogleError(f"Google couldn't be reached: {e}") from None


def identity(id_token):
    """The email and account id inside Google's id token. It came straight from Google over TLS,
    so its payload is read without checking the signature."""
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return {"email": claims.get("email"), "sub": claims.get("sub")}
    except (IndexError, ValueError, AttributeError):
        return {"email": None, "sub": None}


class Session:
    """Access tokens, refreshed when needed and kept in memory only."""

    def __init__(self):
        self.lock = threading.Lock()
        self.access_token, self.expires = None, 0
        self.record = None

    def token(self):
        with self.lock:
            if self.access_token and time.time() < self.expires - 60:
                return self.access_token
            record = load_token()
            if not record:
                raise GoogleError("The layer isn't signed in to Google. Run: pwi google connect CLIENT_JSON")
            c = client()
            answer = post(f"{OAUTH_URL}/token", {"client_id": c["client_id"], "client_secret": c.get("client_secret", ""),
                                                  "refresh_token": record["refresh_token"], "grant_type": "refresh_token"})
            self.access_token, self.expires, self.record = answer["access_token"], time.time() + answer.get("expires_in", 3600), record
            return self.access_token

    def me(self):
        self.token()
        return self.record


# Signing in ---------------------------------------------------------------------------

def check_scopes(granted):
    extra = set(granted.split()) - READ_ONLY
    if extra:
        raise GoogleError(f"Google granted more than read access ({', '.join(sorted(extra))}), so the sign-in "
                          "was revoked. Remove those scopes from the OAuth consent screen and connect again.")


def connect(client_json, open_browser, wait=300):
    """Signs in as me, read-only. Returns {email, stored_in}. `open_browser(url)` shows Google's consent page."""
    data = json.loads(open(client_json, encoding="utf-8").read())
    c = data.get("installed") or data.get("web") or data
    if not c.get("client_id"):
        raise GoogleError(f"{client_json} isn't an OAuth client file: it has no client_id. Download it from "
                          "Google Cloud: APIs & Services, Credentials, OAuth client ID of type Desktop app.")
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    received = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if query.get("state", [""])[0] == state:
                received.update({k: v[0] for k, v in query.items()})
                message = ("Signed in. You can close this tab." if "code" in query
                           else "Sign-in was cancelled. You can close this tab.")
            else:
                message = "This sign-in link doesn't match. Run pwi google connect again."
            body = f"<!doctype html><meta charset=utf-8><title>Work layer</title><p>{message}</p>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Callback)
    redirect = f"http://127.0.0.1:{server.server_address[1]}"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": c["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": " ".join(SCOPES),
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        "access_type": "offline", "prompt": "consent"})
    server.timeout = 1
    deadline = time.time() + wait
    threading.Thread(target=open_browser, args=(url,), daemon=True).start()
    try:
        while "code" not in received and "error" not in received and time.time() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if "code" not in received:
        raise GoogleError("Sign-in didn't finish: " + (received.get("error") or "no answer from the browser in time") + ".")
    answer = post(f"{OAUTH_URL}/token", {"client_id": c["client_id"], "client_secret": c.get("client_secret", ""),
                                         "code": received["code"], "code_verifier": verifier,
                                         "redirect_uri": redirect, "grant_type": "authorization_code"})
    try:
        check_scopes(answer.get("scope", ""))
    except GoogleError:
        revoke(answer.get("refresh_token") or answer.get("access_token"))
        raise
    if not answer.get("refresh_token"):
        raise GoogleError("Google didn't return a refresh token. Remove the layer's access at "
                          "myaccount.google.com/permissions, then connect again.")
    paths.DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(CLIENT_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"client_id": c["client_id"], "client_secret": c.get("client_secret", "")}, f)
    who = identity(answer.get("id_token", ""))
    stored = save_token({"refresh_token": answer["refresh_token"], "scope": answer.get("scope", ""), **who})
    return {"email": who["email"], "stored_in": stored, "scopes": answer.get("scope", "").split()}


def revoke(token):
    if token:
        try:
            post(f"{OAUTH_URL}/revoke", {"token": token})
        except GoogleError:
            pass  # already invalid, or offline: forgetting it locally still matters


def disconnect():
    record = load_token()
    if record:
        revoke(record.get("refresh_token"))
    forget_token()
    CLIENT_PATH.unlink(missing_ok=True)
    return bool(record)


def status():
    record = load_token()
    return {"connected": bool(record), "email": record.get("email") if record else None,
            "keyring": keyring_available(), "scopes": record.get("scope", "").split() if record else []}
