"""The layer's Google Chat app: how the end-of-day review reaches me, and my answers come back.

The app is its own identity, separate from my read-only sign-in (google_signin.py): a service
account in my Google Cloud project, used with two scopes only:
- chat.bot: post and update the app's own messages, only in conversations it's a member of. The
  review uses one: my direct message with the app.
- pubsub: pull the events Google Chat sends the app (a click on a card, the DM being opened) from
  one subscription, where IAM gives the service account the Subscriber role only.
My own account stays read-only. Google Chat publishes the events to a Pub/Sub topic, and the layer
pulls them, so nothing on the laptop listens on the network.

`pwi chat-app connect KEY_JSON` keeps the service account's key in GNOME Keyring (or an owner-only
file without secret-tool); the downloaded file can then be deleted. Access tokens are minted with a
JWT signed here (RS256, standard library only) and kept in memory.
"""

import base64
import hashlib
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import google_signin as google
import paths

CHAT_API = os.environ.get("PWI_GOOGLE_API_URL", "https://chat.googleapis.com/v1")
PUBSUB_API = os.environ.get("PWI_PUBSUB_URL", "https://pubsub.googleapis.com/v1")
TOKEN_URL = os.environ.get("PWI_GOOGLE_OAUTH_URL", "https://oauth2.googleapis.com") + "/token"
AUDIENCE = "https://oauth2.googleapis.com/token"  # what Google expects in the JWT, whatever URL it's sent to
SCOPES = "https://www.googleapis.com/auth/chat.bot https://www.googleapis.com/auth/pubsub"
KEYRING = ["service", "pwi", "account", "chat-app"]
KEY_FILE = paths.DATA_DIR / "chat_app.json"  # only when secret-tool isn't installed
TIMEOUT = 20
DEFAULT_SUBSCRIPTION = "pwi-chat-events"

# DigestInfo prefix for SHA-256 (RFC 8017, section 9.2): what RS256 signs, before the hash.
SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


class AppError(google.GoogleError):
    """Something to tell me in plain words: not connected, refused by Google, unreachable."""


# The service account's private key --------------------------------------------------

def der(data, start):
    """One DER element at start: (tag, first byte of its value, end of its value)."""
    tag, length, i = data[start], data[start + 1], start + 2
    if length & 0x80:
        count = length & 0x7F
        length, i = int.from_bytes(data[i:i + count], "big"), i + count
    if i + length > len(data):
        raise ValueError("truncated key")
    return tag, i, i + length


def children(data, start, end):
    items, i = [], start
    while i < end:
        tag, value, i = der(data, i)
        items.append((tag, value, i))
    return items


def rsa_key(pem):
    """(n, d) from a PEM private key: PKCS#8, as Google issues them, or PKCS#1."""
    lines = [line.strip() for line in pem.strip().splitlines()]
    if not lines or "PRIVATE KEY" not in lines[0]:
        raise ValueError("not a PEM private key")
    body = base64.b64decode("".join(line for line in lines if line and not line.startswith("-----")))
    tag, start, end = der(body, 0)
    parts = children(body, start, end)
    if tag != 0x30 or len(parts) < 3:
        raise ValueError("not a private key")
    if parts[1][0] == 0x30:  # PKCS#8: version, algorithm, then the PKCS#1 key inside an octet string
        if parts[2][0] != 0x04:
            raise ValueError("not an RSA key")
        tag, start, end = der(body, parts[2][1])
        parts = children(body, start, end)
    numbers = [int.from_bytes(body[s:e], "big") for t, s, e in parts if t == 0x02]
    if len(numbers) < 4:
        raise ValueError("not an RSA key")
    return numbers[1], numbers[3]


def sign_rs256(key, message):
    """An RSASSA-PKCS1-v1_5 signature with SHA-256: what Google's JWT bearer flow checks."""
    n, d = key
    size = (n.bit_length() + 7) // 8
    digest = SHA256_PREFIX + hashlib.sha256(message).digest()
    block = b"\x00\x01" + b"\xff" * (size - len(digest) - 3) + b"\x00" + digest
    return pow(int.from_bytes(block, "big"), d, n).to_bytes(size, "big")


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def assertion(record, now=None):
    now = int(now or time.time())
    header = {"alg": "RS256", "typ": "JWT", **({"kid": record["private_key_id"]} if record.get("private_key_id") else {})}
    claims = {"iss": record["client_email"], "scope": SCOPES, "aud": AUDIENCE, "iat": now, "exp": now + 3600}
    signing = f"{b64url(json.dumps(header).encode())}.{b64url(json.dumps(claims).encode())}"
    return f"{signing}.{b64url(sign_rs256(rsa_key(record['private_key']), signing.encode()))}"


# Where the key lives -----------------------------------------------------------------

def load():
    return google.lookup_secret(KEYRING, KEY_FILE)


def subscription_path(name, project):
    name = name.strip()
    return name if name.startswith("projects/") else f"projects/{project}/subscriptions/{name}"


def read_key_file(key_json):
    try:
        data = json.loads(open(key_json, encoding="utf-8").read())
    except (OSError, ValueError) as e:
        raise AppError(f"{key_json} couldn't be read as JSON: {e}") from None
    if data.get("type") != "service_account" or not data.get("client_email") or not data.get("private_key"):
        raise AppError(f"{key_json} isn't a service account key. In Google Cloud: IAM & Admin, Service accounts, "
                       "the app's account, Keys, Add key, JSON.")
    try:
        rsa_key(data["private_key"])
    except (ValueError, IndexError) as e:
        raise AppError(f"The key in {key_json} can't be used: {e}.") from None
    return data


def connect(key_json, subscription=DEFAULT_SUBSCRIPTION):
    """Checks the key works (Google mints a token with it), then keeps it. Returns what was stored."""
    data = read_key_file(key_json)
    record = {"client_email": data["client_email"], "private_key": data["private_key"],
              "private_key_id": data.get("private_key_id"), "project_id": data.get("project_id"),
              "subscription": subscription_path(subscription, data.get("project_id"))}
    App(record).token()  # fails here, before anything is stored, if Google refuses the key
    stored = google.store_secret(KEYRING, "Work layer Chat app key", record, KEY_FILE)
    return {"client_email": record["client_email"], "subscription": record["subscription"], "stored_in": stored}


def disconnect():
    had = load() is not None
    google.clear_secret(KEYRING, KEY_FILE)
    return had


def connected():
    try:
        return load() is not None
    except (OSError, ValueError):
        return False


# Talking to Google ---------------------------------------------------------------------

def call(method, url, token=None, body=None, timeout=TIMEOUT, form=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    data = None
    if form is not None:
        data, headers["Content-Type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    elif body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise AppError(f"Google answered {e.code}: {detail}") from None
    except (TimeoutError, socket.timeout):
        raise
    except urllib.error.URLError as e:
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            raise TimeoutError(str(e.reason)) from None
        raise AppError(f"Google couldn't be reached: {e.reason}") from None


class App:
    """The Chat app, as the layer uses it: a token kept in memory, the review's messages, and the
    events Google Chat sends it."""

    def __init__(self, record=None):
        self.record = record
        self.lock = threading.Lock()
        self.access_token, self.expires = None, 0

    def key(self):
        if self.record is None:
            self.record = load()
            if not self.record:
                raise AppError("The Chat app isn't connected. Run: pwi chat-app connect KEY_JSON")
        return self.record

    def token(self):
        with self.lock:
            if self.access_token and time.time() < self.expires - 60:
                return self.access_token
            answer = call("POST", TOKEN_URL, form={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                                    "assertion": assertion(self.key())})
            if not answer.get("access_token"):
                raise AppError("Google didn't return a token for the Chat app.")
            self.access_token, self.expires = answer["access_token"], time.time() + answer.get("expires_in", 3600)
            return self.access_token

    def post(self, space, body, message_id=None):
        """Posts a message as the app. A message id makes a retry land on the same message."""
        query = f"?messageId={urllib.parse.quote(message_id)}" if message_id else ""
        return call("POST", f"{CHAT_API}/{space}/messages{query}", self.token(), body)

    def update(self, name, body, mask="text,cardsV2"):
        return call("PATCH", f"{CHAT_API}/{name}?updateMask={mask}", self.token(), body)

    def pull(self, wait=True, timeout=30, most=20):
        """Events waiting in the subscription, as (ack id, event, message id). With wait, Pub/Sub holds the
        request open until one arrives, so a click reaches the layer in about a second; a quiet spell just
        ends the request."""
        url = f"{PUBSUB_API}/{self.key()['subscription']}:pull"
        try:
            answer = call("POST", url, self.token(), {"maxMessages": most, "returnImmediately": not wait},
                          timeout=timeout)
        except TimeoutError:
            return []
        events = []
        for received in answer.get("receivedMessages", []):
            try:
                event = json.loads(base64.b64decode(received["message"].get("data", "")) or b"{}")
            except (ValueError, KeyError):
                event = {}
            events.append((received["ackId"], event, received["message"].get("messageId") or received["ackId"]))
        return events

    def ack(self, ack_ids):
        if ack_ids:
            call("POST", f"{PUBSUB_API}/{self.key()['subscription']}:acknowledge", self.token(), {"ackIds": list(ack_ids)})
