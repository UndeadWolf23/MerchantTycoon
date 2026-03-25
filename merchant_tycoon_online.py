"""
merchant_tycoon_online.py  —  Online Services Framework for Merchant Tycoon
═══════════════════════════════════════════════════════════════════════════════

Provides all online features via Supabase (https://supabase.com):
    authentication, cloud saves, global leaderboard, player profiles,
    earned titles, friends list, and merchant guilds.

Architecture:
    OnlineClient           — low-level HTTP wrapper; stdlib urllib only, zero
                             extra dependencies required.
    AuthManager            — sign-up / sign-in / sign-out / password-reset;
                             persists JWT session so players stay logged in.
    ProfileManager         — public player profiles: username, active title,
                             lifetime stats, and the earned-title collection.
    CloudSaveManager       — upload and download save-game JSON blobs.
    SyncManager            — non-blocking auto-sync with offline queue & retry.
    LeaderboardManager     — lifetime-gold leaderboard with username + title.
    FriendsManager         — friend requests, friend list, block.
    GuildManager           — create, join, invite, roster, guild score.
    OnlineServices         — single façade; attach to GameApp as  app.online.

Non-blocking pattern:
    Every public method accepts an optional  callback(result: OnlineResult)
    parameter.  When provided, the network call runs on a daemon thread and
    the callback is invoked there on completion.

    GUI callers MUST wrap callbacks with  app.after(0, ...)  before touching
    any Tkinter widget:

        def _on_sign_in(result: OnlineResult):
            app.after(0, lambda: _update_ui(result))

        app.online.auth.sign_in(email, password, callback=_on_sign_in)

Offline safety:
    Every method returns  OnlineResult(success=False, error="...")  when the
    player is offline or unauthenticated.  The game never depends on these
    calls succeeding.

Credential management (dotenv):
    In development: create a .env file in the project root containing
        SUPABASE_URL=https://...
        SUPABASE_ANON_KEY=sb_publishable_...
    and run  pip install python-dotenv  to load it automatically.
    In production / shipped builds the baked-in constants are used.
    NOTE: dotenv / Streamlit are NOT used at runtime — this is a Tkinter
    desktop application.  dotenv is development tooling only.

Supabase tables (SQL schema in each manager's docstring):
    profiles, earned_titles, title_definitions,
    cloud_saves, leaderboard,
    friends,
    guilds, guild_members, guild_invites
"""

import http.server
import json
import os
import socketserver
import sys
import threading
import urllib.request
import urllib.error
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# SUPABASE CONNECTION
# In development, override via .env (pip install python-dotenv):
#     SUPABASE_URL=https://your-project.supabase.co
#     SUPABASE_ANON_KEY=sb_publishable_...
# The anon (publishable) key is safe to ship — Supabase RLS policies enforce
# per-user data isolation server-side.  Never put the service_role key here.
# ─────────────────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — use baked-in defaults

SUPABASE_URL: str      = os.environ.get(
    "SUPABASE_URL", "https://bshhjvxbrheheofcdsbw.supabase.co")
SUPABASE_ANON_KEY: str = os.environ.get(
    "SUPABASE_ANON_KEY", "sb_publishable_sIWaf4GR_x9hL9Lg1Z6Ahg_6Sh4QZ0v")

# ─────────────────────────────────────────────────────────────────────────────
# VERIFICATION SERVER  —  local HTTP server for email-verification redirect
# ─────────────────────────────────────────────────────────────────────────────

# HTML file lives next to this module in the same directory
_SCRIPTS_DIR      = os.path.dirname(os.path.abspath(__file__))
_VERIF_HTML_PATH  = os.path.join(_SCRIPTS_DIR, "VerificationSuccess.html")


class VerificationServer:
    """
    Minimal single-file HTTP server that serves VerificationSuccess.html
    on  http://localhost:3000/VerificationSuccess.html

    Runs on a daemon thread — completely invisible to the player.
    Supabase email verification links redirect to this URL, so the
    landing page is styled to match the game rather than Supabase's default.

    Usage:
        server = VerificationServer()   # or OnlineServices().verification
        server.start()                  # begin hosting
        server.stop()                   # shut down (port freed immediately)
    """

    PORT        = 3000
    FILENAME    = "VerificationSuccess.html"
    REDIRECT_URL = f"http://localhost:{PORT}/{FILENAME}"

    def __init__(self, html_path: str = _VERIF_HTML_PATH) -> None:
        self._html_path = html_path
        self._server:  Optional[socketserver.TCPServer] = None
        self._thread:  Optional[threading.Thread]       = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Start the server; returns True on success, False if already running
        or the port is in use."""
        if self._server is not None:
            return True   # already running

        html_path = self._html_path
        filename  = self.FILENAME

        class _Handler(http.server.BaseHTTPRequestHandler):
            """Serves only VerificationSuccess.html; silences all log output."""

            def do_GET(self) -> None:  # noqa: N802
                req_path = self.path.split("?")[0].lstrip("/")
                if req_path == filename:
                    try:
                        with open(html_path, "rb") as fh:
                            data = fh.read()
                        self.send_response(200)
                        self.send_header("Content-Type",   "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                    except Exception:
                        self.send_response(500)
                        self.end_headers()
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *_args) -> None:  # suppress all console output
                pass

        try:
            # allow_reuse_address prevents "address already in use" on quick restart
            socketserver.TCPServer.allow_reuse_address = True
            srv = socketserver.TCPServer(("127.0.0.1", self.PORT), _Handler)
            self._server = srv
            self._thread = threading.Thread(
                target=srv.serve_forever, daemon=True, name="verif-server")
            self._thread.start()
            return True
        except OSError:
            # Port 3000 already in use — not a fatal error
            self._server = None
            self._thread = None
            return False

    def stop(self) -> None:
        """Shut down the server and free the port."""
        srv = self._server
        if srv is not None:
            try:
                srv.shutdown()       # signals serve_forever() to exit
                srv.server_close()   # closes the socket
            except Exception:
                pass
            self._server = None
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._server is not None

# ─────────────────────────────────────────────────────────────────────────────
# LOCAL SESSION STORAGE  —  same user-data directory as the main game
# ─────────────────────────────────────────────────────────────────────────────

def _get_user_data_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(base, "MerchantTycoon")
    return os.path.join(os.path.expanduser("~"), ".config", "MerchantTycoon")


_USER_DATA_DIR: str = _get_user_data_dir()
_SESSION_FILE:  str = os.path.join(_USER_DATA_DIR, "online_session.json")

# ─────────────────────────────────────────────────────────────────────────────
# RESULT TYPE
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class OnlineResult:
    """Returned by every public OnlineServices / manager method."""
    success: bool
    data: Any = None
    error: str = ""

    def __bool__(self) -> bool:
        return self.success


# ─────────────────────────────────────────────────────────────────────────────
# LOW-LEVEL HTTP CLIENT
# ─────────────────────────────────────────────────────────────────────────────

_TIMEOUT: int = 12  # seconds


class OnlineClient:
    """
    Thin wrapper around urllib for Supabase REST / Auth HTTP calls.
    Handles JSON serialisation, common headers, and error normalisation.
    Uses only the Python standard library — zero extra dependencies required.
    """

    def __init__(self, access_token: Optional[str] = None) -> None:
        self._access_token: Optional[str] = access_token
        self._lock = threading.Lock()

    def set_token(self, token: Optional[str]) -> None:
        with self._lock:
            self._access_token = token

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        with self._lock:
            token = self._access_token
        h: Dict[str, str] = {
            "Content-Type":  "application/json",
            "apikey":        SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {token or SUPABASE_ANON_KEY}",
        }
        if extra:
            h.update(extra)
        return h

    def request(
        self,
        method: str,
        path: str,
        body: Optional[Dict] = None,
        params: Optional[Dict[str, str]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> OnlineResult:
        """
        Make an HTTP request to the Supabase project.

        path          — e.g. "/auth/v1/signup"  or  "/rest/v1/leaderboard"
        body          — JSON-serialisable dict; sent as request body
        params        — URL query-string parameters
        extra_headers — merged on top of the default auth headers

        Returns OnlineResult with .data set to the parsed JSON response.
        """
        url = SUPABASE_URL + path
        if params:
            url += "?" + urllib.parse.urlencode(params)

        data_bytes = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers=self._headers(extra_headers),
            method=method,
        )

        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw) if raw.strip() else {}
                return OnlineResult(success=True, data=data)

        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8") if exc.fp else ""
            try:
                detail = json.loads(raw)
                msg = (detail.get("msg")
                       or detail.get("message")
                       or detail.get("error_description")
                       or str(detail))
            except Exception:
                msg = raw or str(exc)
            return OnlineResult(success=False, error=f"HTTP {exc.code}: {msg}")

        except urllib.error.URLError as exc:
            return OnlineResult(success=False, error=f"Network error: {exc.reason}")

        except Exception as exc:
            return OnlineResult(success=False, error=f"Unexpected error: {exc}")

    # ── Convenience wrappers ──────────────────────────────────────────────────

    def get(self, path: str,
            params: Optional[Dict] = None,
            extra_headers: Optional[Dict] = None) -> OnlineResult:
        return self.request("GET",    path, params=params, extra_headers=extra_headers)

    def post(self, path: str,
             body: Optional[Dict] = None,
             params: Optional[Dict] = None,
             extra_headers: Optional[Dict] = None) -> OnlineResult:
        return self.request("POST",   path, body=body, params=params, extra_headers=extra_headers)

    def patch(self, path: str,
              body: Optional[Dict] = None,
              params: Optional[Dict] = None) -> OnlineResult:
        return self.request("PATCH",  path, body=body, params=params)

    def put(self, path: str,
            body: Optional[Dict] = None,
            params: Optional[Dict] = None) -> OnlineResult:
        return self.request("PUT",    path, body=body, params=params)

    def delete(self, path: str,
               params: Optional[Dict] = None) -> OnlineResult:
        return self.request("DELETE", path, params=params)


# ─────────────────────────────────────────────────────────────────────────────
# THREADING HELPER
# ─────────────────────────────────────────────────────────────────────────────

def _run_async(fn: Callable[[], OnlineResult],
               callback: Optional[Callable[[OnlineResult], None]]) -> None:
    """Run *fn* on a daemon thread; invoke *callback* with the result."""
    def _worker() -> None:
        result = fn()
        if callback is not None:
            callback(result)
    threading.Thread(target=_worker, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# AUTH MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class AuthManager:
    """
    Handles player authentication via Supabase Auth (email + password).

    Session persistence:
        The JWT access_token + refresh_token are stored in online_session.json
        in the user-data directory.  Call  load_session()  at app startup to
        automatically restore a previous login.
    """

    def __init__(self, client: OnlineClient) -> None:
        self._client  = client
        self._session: Dict = {}
        self._lock    = threading.Lock()

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_authenticated(self) -> bool:
        with self._lock:
            return bool(self._session.get("access_token"))

    @property
    def user_id(self) -> Optional[str]:
        with self._lock:
            return (self._session.get("user") or {}).get("id")

    @property
    def email(self) -> Optional[str]:
        with self._lock:
            return (self._session.get("user") or {}).get("email")

    @property
    def username(self) -> Optional[str]:
        """Display name from user_metadata; falls back to email prefix."""
        with self._lock:
            user = self._session.get("user") or {}
            meta = user.get("user_metadata") or {}
            name = meta.get("username")
        return name or (self.email or "").split("@")[0] or "Merchant"

    # ── Session file I/O ──────────────────────────────────────────────────────

    def load_session(self) -> bool:
        """
        Load a previously saved session from disk.
        Returns True if a session file was found and parsed successfully.
        (The token's validity is not verified here — call refresh_session
        to silently renew it.)
        """
        try:
            if not os.path.exists(_SESSION_FILE):
                return False
            with open(_SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                self._session = data
            token = data.get("access_token")
            if token:
                self._client.set_token(token)
                return True
        except Exception:
            pass
        return False

    def _save_session(self) -> None:
        os.makedirs(_USER_DATA_DIR, exist_ok=True)
        with self._lock:
            snapshot = dict(self._session)
        with open(_SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)

    def _clear_session(self) -> None:
        with self._lock:
            self._session = {}
        self._client.set_token(None)
        try:
            if os.path.exists(_SESSION_FILE):
                os.remove(_SESSION_FILE)
        except Exception:
            pass

    def _apply_session(self, data: Dict) -> None:
        """Store an auth response dict and update the shared HTTP client token."""
        with self._lock:
            self._session = {
                "access_token":  data.get("access_token"),
                "refresh_token": data.get("refresh_token"),
                "token_type":    data.get("token_type", "bearer"),
                "expires_in":    data.get("expires_in"),
                "user":          data.get("user"),
            }
        self._client.set_token(data.get("access_token"))
        self._save_session()

    # ── Public API ────────────────────────────────────────────────────────────

    def sign_up(
        self,
        email: str,
        password: str,
        username: str = "",
        redirect_to: str = "",
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """
        Register a new account.
        username is stored in user_metadata and used as the display name.
        redirect_to, when set, tells Supabase where to redirect the player
        after they click the verification link in their email.
        If the Supabase project requires email confirmation, result.data will
        contain {"action": "confirm_email"} and no session is started yet.
        """
        def _do() -> OnlineResult:
            body: Dict = {"email": email, "password": password}
            if username:
                body["data"] = {"username": username}
            params: Optional[Dict] = None
            if redirect_to:
                params = {"redirect_to": redirect_to}
            result = self._client.post("/auth/v1/signup", body, params=params)
            if result.success:
                if result.data.get("access_token"):
                    self._apply_session(result.data)
                    result.data = {"action": "signed_up", "user": result.data.get("user")}
                else:
                    result.data = {"action": "confirm_email"}
            return result

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def sign_in(
        self,
        email: str,
        password: str,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Sign in with email and password."""
        def _do() -> OnlineResult:
            result = self._client.post(
                "/auth/v1/token",
                body={"email": email, "password": password, "grant_type": "password"},
                params={"grant_type": "password"},
            )
            if result.success:
                self._apply_session(result.data)
                result.data = {"action": "signed_in", "user": result.data.get("user")}
            return result

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def sign_out(
        self, callback: Optional[Callable] = None
    ) -> Optional[OnlineResult]:
        """Sign out and clear the local session."""
        def _do() -> OnlineResult:
            self._client.post("/auth/v1/logout")   # best-effort; clear locally regardless
            self._clear_session()
            return OnlineResult(success=True, data={"action": "signed_out"})

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def refresh_session(
        self, callback: Optional[Callable] = None
    ) -> Optional[OnlineResult]:
        """Exchange the stored refresh token for a new access token."""
        def _do() -> OnlineResult:
            with self._lock:
                refresh_token = self._session.get("refresh_token")
            if not refresh_token:
                return OnlineResult(success=False, error="No refresh token available.")
            result = self._client.post(
                "/auth/v1/token",
                body={"refresh_token": refresh_token, "grant_type": "refresh_token"},
                params={"grant_type": "refresh_token"},
            )
            if result.success:
                self._apply_session(result.data)
                result.data = {"action": "refreshed"}
            return result

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def get_current_user(
        self, callback: Optional[Callable] = None
    ) -> Optional[OnlineResult]:
        """Fetch the authenticated user record from the server."""
        def _do() -> OnlineResult:
            if not self.is_authenticated:
                return OnlineResult(success=False, error="Not authenticated.")
            result = self._client.get("/auth/v1/user")
            if result.success:
                with self._lock:
                    self._session["user"] = result.data
                self._save_session()
            return result

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def update_username(
        self,
        username: str,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Update the display name stored in user_metadata."""
        def _do() -> OnlineResult:
            if not self.is_authenticated:
                return OnlineResult(success=False, error="Not authenticated.")
            result = self._client.put(
                "/auth/v1/user",
                body={"data": {"username": username}},
            )
            if result.success:
                with self._lock:
                    self._session["user"] = result.data
                self._save_session()
            return result

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def clear_saved_session(self) -> None:
        """
        Delete the on-disk session file without disturbing the in-memory JWT.
        Call after sign_in when 'Remember Me' is unchecked — the player stays
        authenticated for this session but will be asked to sign in again next
        time the game is launched.
        """
        try:
            if os.path.exists(_SESSION_FILE):
                os.remove(_SESSION_FILE)
        except Exception:
            pass

    def request_password_reset(
        self,
        email: str,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """
        Send a password-reset email via Supabase Auth.
        The player clicks the link in the email to set a new password.
        Does NOT require the player to be authenticated.
        """
        def _do() -> OnlineResult:
            result = self._client.post(
                "/auth/v1/recover",
                body={"email": email},
            )
            if result.success:
                result.data = {"action": "reset_email_sent"}
            return result

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# CLOUD SAVE MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class CloudSaveManager:
    """
    Stores and retrieves save-game JSON blobs in Supabase.

    Required Supabase SQL:
    ─────────────────────
        create table cloud_saves (
            id           uuid primary key default gen_random_uuid(),
            user_id      uuid references auth.users not null,
            slot         int  not null default 1,
            save_data    jsonb not null,
            day          int  not null default 0,
            gold         float not null default 0,
            reputation   int  not null default 0,
            version      text not null default '1.0',
            created_at   timestamptz default now(),
            updated_at   timestamptz default now(),
            unique (user_id, slot)
        );
        alter table cloud_saves enable row level security;
        create policy "owner only" on cloud_saves
            using  (auth.uid() = user_id)
            with check (auth.uid() = user_id);
    """

    def __init__(self, client: OnlineClient, auth: AuthManager) -> None:
        self._client = client
        self._auth   = auth

    def upload_save(
        self,
        save_data: Dict,
        slot: int = 1,
        meta: Optional[Dict] = None,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """
        Upload (upsert) a save into the given slot.
        meta dict may contain: {"day": int, "gold": float, "reputation": int, "version": str}
        """
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            m = meta or {}
            payload = {
                "user_id":    self._auth.user_id,
                "slot":       slot,
                "save_data":  save_data,
                "day":        m.get("day", 0),
                "gold":       m.get("gold", 0.0),
                "reputation": m.get("reputation", 0),
                "version":    m.get("version", "1.0"),
            }
            return self._client.post(
                "/rest/v1/cloud_saves",
                body=payload,
                params={"on_conflict": "user_id,slot"},
                extra_headers={"Prefer": "resolution=merge-duplicates,return=representation"},
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def download_save(
        self,
        slot: int = 1,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Download the most recent save from the given slot."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            result = self._client.get(
                "/rest/v1/cloud_saves",
                params={
                    "select":  "save_data,day,gold,reputation,version,updated_at",
                    "user_id": f"eq.{self._auth.user_id}",
                    "slot":    f"eq.{slot}",
                    "order":   "updated_at.desc",
                    "limit":   "1",
                },
            )
            if result.success:
                rows = result.data if isinstance(result.data, list) else []
                if not rows:
                    return OnlineResult(success=False,
                                        error=f"No cloud save found in slot {slot}.")
                result.data = rows[0]
            return result

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def list_saves(
        self, callback: Optional[Callable] = None
    ) -> Optional[OnlineResult]:
        """List all save slots for the current player (metadata only, no raw save_data)."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            return self._client.get(
                "/rest/v1/cloud_saves",
                params={
                    "select":  "slot,day,gold,reputation,version,updated_at",
                    "user_id": f"eq.{self._auth.user_id}",
                    "order":   "slot.asc",
                },
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def delete_save(
        self,
        slot: int = 1,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Delete a cloud save slot permanently."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            return self._client.delete(
                "/rest/v1/cloud_saves",
                params={
                    "user_id": f"eq.{self._auth.user_id}",
                    "slot":    f"eq.{slot}",
                },
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# LEADERBOARD MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class LeaderboardManager:
    """
    Global leaderboard — one row per player, ranked by net worth.

    Required Supabase SQL (migration from old schema):
    ──────────────────────────────────────────────────
        -- Add new columns (safe to run on existing table)
        alter table leaderboard
            add column if not exists net_worth   float  not null default 0.0,
            add column if not exists player_name text   not null default '',
            add column if not exists guild_name  text   not null default '',
            add column if not exists title       text   not null default '',
            add column if not exists lifetime_gold float not null default 0.0;

        -- Performance index for ranking queries
        create index if not exists leaderboard_net_worth_idx
            on leaderboard (net_worth desc nulls last);

        -- RLS (unchanged)
        alter table leaderboard enable row level security;
        create policy "read all"   on leaderboard for select using (true);
        create policy "insert own" on leaderboard for insert
            with check (auth.uid() = user_id);
        create policy "update own" on leaderboard for update
            using (auth.uid() = user_id);

    Full schema (fresh install):
    ────────────────────────────
        create table leaderboard (
            id            uuid primary key default gen_random_uuid(),
            user_id       uuid references auth.users not null unique,
            username      text   not null default '',
            player_name   text   not null default '',
            title         text   not null default '',
            guild_name    text   not null default '',
            net_worth     float  not null default 0.0,
            score         bigint not null default 0,
            day           int    not null default 0,
            gold          float  not null default 0.0,
            lifetime_gold float  not null default 0.0,
            reputation    int    not null default 0,
            area          text   not null default '',
            updated_at    timestamptz not null default now()
        );
        alter table leaderboard enable row level security;
        create policy "read all"   on leaderboard for select using (true);
        create policy "insert own" on leaderboard for insert
            with check (auth.uid() = user_id);
        create policy "update own" on leaderboard for update
            using (auth.uid() = user_id);
        create index leaderboard_net_worth_idx
            on leaderboard (net_worth desc nulls last);
    """

    def __init__(self, client: OnlineClient, auth: AuthManager) -> None:
        self._client = client
        self._auth   = auth

    @staticmethod
    def compute_score(lifetime_gold: float, reputation: int, day: int) -> int:
        """
        Composite scoring formula  (lifetime_gold is the primary driver since
        it can only grow, unlike current gold which fluctuates):
            score = lifetime_gold  +  reputation × 100  +  day × 10
        """
        return int(lifetime_gold + reputation * 100 + day * 10)

    def submit_score(
        self,
        gold: float,
        reputation: int,
        day: int,
        net_worth: float = 0.0,
        lifetime_gold: float = 0.0,
        title: str = "",
        player_name: str = "",
        guild_name: str = "",
        area: str = "",
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """
        Upsert the player's entry on the global leaderboard.
        net_worth     — primary ranking metric (total assets − liabilities).
        lifetime_gold — monotonically increasing, used for secondary score.
        title         — currently equipped earned title (display name).
        player_name   — in-game merchant name (may differ from login username).
        guild_name    — display name of the player's current guild, or "".
        """
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            score    = self.compute_score(lifetime_gold, reputation, day)
            username = self._auth.username or "Unknown Merchant"
            payload  = {
                "user_id":       self._auth.user_id,
                "username":      username,
                "player_name":   player_name or username,
                "title":         title,
                "guild_name":    guild_name,
                "net_worth":     net_worth,
                "score":         score,
                "day":           day,
                "gold":          gold,
                "lifetime_gold": lifetime_gold,
                "reputation":    reputation,
                "area":          area,
                "updated_at":    "now()",
            }
            result = self._client.post(
                "/rest/v1/leaderboard",
                body=payload,
                params={"on_conflict": "user_id"},
                extra_headers={"Prefer": "resolution=merge-duplicates,return=representation"},
            )
            if result.success:
                result.data = {"score": score, "net_worth": net_worth, "action": "submitted"}
            return result

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def fetch_top_scores(
        self,
        limit: int = 100,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Fetch the top *limit* entries ordered by net_worth descending."""
        def _do() -> OnlineResult:
            return self._client.get(
                "/rest/v1/leaderboard",
                params={
                    "select": "user_id,username,player_name,title,guild_name,"
                              "net_worth,score,lifetime_gold,day,reputation,area,updated_at",
                    "order":  "net_worth.desc.nullsfirst",
                    "limit":  str(limit),
                },
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def fetch_my_rank(
        self, callback: Optional[Callable] = None
    ) -> Optional[OnlineResult]:
        """Return {"rank": int, "net_worth": float} for the current player."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")

            my_result = self._client.get(
                "/rest/v1/leaderboard",
                params={"select": "net_worth",
                        "user_id": f"eq.{self._auth.user_id}", "limit": "1"},
            )
            if not my_result.success:
                return my_result
            rows = my_result.data if isinstance(my_result.data, list) else []
            if not rows:
                return OnlineResult(success=False, error="No leaderboard entry found.")
            my_nw = rows[0].get("net_worth", 0.0)

            above_result = self._client.get(
                "/rest/v1/leaderboard",
                params={"select": "user_id", "net_worth": f"gt.{my_nw}"},
            )
            if not above_result.success:
                return above_result

            above_count = len(above_result.data) if isinstance(above_result.data, list) else 0
            return OnlineResult(success=True,
                                data={"rank": above_count + 1, "net_worth": my_nw})

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# GUILD MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class GuildManager:
    """
    Merchant guilds — players can create, browse, join, and leave guilds.

    Required Supabase SQL:
    ─────────────────────
        create table guilds (
            id           uuid primary key default gen_random_uuid(),
            name         text not null unique,
            description  text not null default '',
            owner_id     uuid references auth.users not null,
            member_count int  not null default 1,
            created_at   timestamptz default now()
        );
        alter table guilds enable row level security;
        create policy "read all"     on guilds for select using (true);
        create policy "insert own"   on guilds for insert
            with check (auth.uid() = owner_id);
        create policy "owner update" on guilds for update
            using (auth.uid() = owner_id);
        create policy "owner delete" on guilds for delete
            using (auth.uid() = owner_id);

        create table guild_members (
            guild_id  uuid references guilds(id) on delete cascade not null,
            user_id   uuid references auth.users not null,
            username  text not null,
            role      text not null default 'member',  -- 'owner' | 'officer' | 'member'
            joined_at timestamptz default now(),
            primary key (guild_id, user_id)
        );
        alter table guild_members enable row level security;
        create policy "read all"     on guild_members for select using (true);
        create policy "insert self"  on guild_members for insert
            with check (auth.uid() = user_id);
        create policy "delete self"  on guild_members for delete
            using (auth.uid() = user_id);

        create table guild_invites (
            id          uuid primary key default gen_random_uuid(),
            guild_id    uuid references guilds(id) on delete cascade not null,
            from_user   uuid references auth.users not null,
            to_user     uuid references auth.users not null,
            status      text not null default 'pending',  -- 'pending'|'accepted'|'declined'
            created_at  timestamptz default now(),
            unique (guild_id, to_user)
        );
        alter table guild_invites enable row level security;
        create policy "read involved" on guild_invites for select
            using (auth.uid() = from_user or auth.uid() = to_user);
        create policy "insert member" on guild_invites for insert
            with check (auth.uid() = from_user);
        create policy "update invited" on guild_invites for update
            using (auth.uid() = to_user);
    """

    def __init__(self, client: OnlineClient, auth: AuthManager) -> None:
        self._client = client
        self._auth   = auth

    def create_guild(
        self,
        name: str,
        description: str = "",
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Create a new guild and automatically join it as owner."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")

            # Insert the guild row
            guild_result = self._client.post(
                "/rest/v1/guilds",
                body={
                    "name":         name,
                    "description":  description,
                    "owner_id":     self._auth.user_id,
                    "member_count": 1,
                },
                extra_headers={"Prefer": "return=representation"},
            )
            if not guild_result.success:
                return guild_result

            # Parse returned guild (may be a list or dict depending on Prefer header)
            rows = guild_result.data
            guild = (rows[0] if isinstance(rows, list) and rows
                     else rows if isinstance(rows, dict) else None)
            if not guild or not guild.get("id"):
                return OnlineResult(success=False,
                                    error="Guild created but response was unexpected.")

            # Auto-join as owner
            self._client.post(
                "/rest/v1/guild_members",
                body={
                    "guild_id": guild["id"],
                    "user_id":  self._auth.user_id,
                    "username": self._auth.username or "Unknown Merchant",
                    "role":     "owner",
                },
            )
            return OnlineResult(success=True, data=guild)

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def join_guild(
        self,
        guild_id: str,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Join an existing guild as a member."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            return self._client.post(
                "/rest/v1/guild_members",
                body={
                    "guild_id": guild_id,
                    "user_id":  self._auth.user_id,
                    "username": self._auth.username or "Unknown Merchant",
                    "role":     "member",
                },
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def leave_guild(
        self,
        guild_id: str,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Leave a guild.  Does not disband it — owner must transfer or delete manually."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            return self._client.delete(
                "/rest/v1/guild_members",
                params={
                    "guild_id": f"eq.{guild_id}",
                    "user_id":  f"eq.{self._auth.user_id}",
                },
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def list_guilds(
        self,
        search: str = "",
        limit: int = 30,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """List guilds ordered by member count, optionally filtered by name."""
        def _do() -> OnlineResult:
            params: Dict[str, str] = {
                "select": "id,name,description,member_count,created_at",
                "order":  "member_count.desc",
                "limit":  str(limit),
            }
            if search:
                params["name"] = f"ilike.*{search}*"
            return self._client.get("/rest/v1/guilds", params=params)

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def get_my_guild(
        self, callback: Optional[Callable] = None
    ) -> Optional[OnlineResult]:
        """Return the guild the current player belongs to, or None if not in one."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")

            member_result = self._client.get(
                "/rest/v1/guild_members",
                params={
                    "select":  "guild_id,role",
                    "user_id": f"eq.{self._auth.user_id}",
                    "limit":   "1",
                },
            )
            if not member_result.success:
                return member_result

            rows = member_result.data if isinstance(member_result.data, list) else []
            if not rows:
                return OnlineResult(success=True, data=None)  # not in any guild

            guild_id = rows[0]["guild_id"]
            guild_result = self._client.get(
                "/rest/v1/guilds",
                params={
                    "select": "id,name,description,member_count,owner_id,created_at",
                    "id":     f"eq.{guild_id}",
                    "limit":  "1",
                },
            )
            if not guild_result.success:
                return guild_result

            guild_rows = guild_result.data if isinstance(guild_result.data, list) else []
            return OnlineResult(success=True, data=guild_rows[0] if guild_rows else None)

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def get_guild_members(
        self,
        guild_id: str,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Fetch the member roster for a guild ordered by role then join date."""
        def _do() -> OnlineResult:
            return self._client.get(
                "/rest/v1/guild_members",
                params={
                    "select":   "username,role,joined_at",
                    "guild_id": f"eq.{guild_id}",
                    "order":    "role.asc,joined_at.asc",
                },
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def send_invite(
        self,
        guild_id: str,
        to_user_id: str,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Invite another player to your guild (you must be a member)."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            return self._client.post(
                "/rest/v1/guild_invites",
                body={
                    "guild_id":  guild_id,
                    "from_user": self._auth.user_id,
                    "to_user":   to_user_id,
                    "status":    "pending",
                },
                params={"on_conflict": "guild_id,to_user"},
                extra_headers={"Prefer": "resolution=ignore-duplicates"},
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def respond_to_invite(
        self,
        invite_id: str,
        accept: bool,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Accept or decline a pending guild invite."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            status = "accepted" if accept else "declined"
            result = self._client.patch(
                "/rest/v1/guild_invites",
                body={"status": status},
                params={
                    "id":      f"eq.{invite_id}",
                    "to_user": f"eq.{self._auth.user_id}",
                    "status":  "eq.pending",
                },
            )
            # If accepted, auto-join the guild
            if result.success and accept:
                inv_result = self._client.get(
                    "/rest/v1/guild_invites",
                    params={"select": "guild_id", "id": f"eq.{invite_id}", "limit": "1"},
                )
                if inv_result.success:
                    rows = inv_result.data if isinstance(inv_result.data, list) else []
                    if rows:
                        self.join_guild(rows[0]["guild_id"])
            return result

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def list_my_invites(
        self, callback: Optional[Callable] = None
    ) -> Optional[OnlineResult]:
        """Return pending guild invites addressed to the current player."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            return self._client.get(
                "/rest/v1/guild_invites",
                params={
                    "select":  "id,guild_id,from_user,created_at,guilds(name)",
                    "to_user": f"eq.{self._auth.user_id}",
                    "status":  "eq.pending",
                },
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# PROFILE MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class ProfileManager:
    """
    Public player profiles: username, active title, lifetime stats.

    Required Supabase SQL:
    ───────────────────
        create table profiles (
            id            uuid primary key references auth.users on delete cascade,
            username      text not null unique,
            title         text not null default '',   -- active earned-title key
            avatar_url    text not null default '',
            lifetime_gold float not null default 0.0,
            best_day      int  not null default 0,
            best_rep      int  not null default 0,
            created_at    timestamptz default now(),
            updated_at    timestamptz default now()
        );
        alter table profiles enable row level security;
        create policy "read all"   on profiles for select using (true);
        create policy "insert own" on profiles for insert
            with check (auth.uid() = id);
        create policy "update own" on profiles for update
            using (auth.uid() = id);

        -- All title definitions (populate via SQL / admin panel)
        create table title_definitions (
            key         text primary key,
            name        text not null,
            description text not null default '',
            icon        text not null default '🏅',
            rarity      text not null default 'common'  -- common|rare|epic|legendary
        );
        alter table title_definitions enable row level security;
        create policy "read all" on title_definitions for select using (true);

        -- Titles earned by each player
        create table earned_titles (
            user_id   uuid references auth.users on delete cascade not null,
            title_key text references title_definitions(key) not null,
            earned_at timestamptz default now(),
            primary key (user_id, title_key)
        );
        alter table earned_titles enable row level security;
        create policy "read all"   on earned_titles for select using (true);
        create policy "insert own" on earned_titles for insert
            with check (auth.uid() = user_id);

        -- Achievements earned by each player
        create table if not exists earned_achievements (
            user_id   uuid references auth.users on delete cascade not null,
            ach_key   text not null,
            earned_at timestamptz default now(),
            primary key (user_id, ach_key)
        );
        alter table earned_achievements enable row level security;
        create policy "read all"   on earned_achievements for select using (true);
        create policy "insert own" on earned_achievements for insert
            with check (auth.uid() = user_id);
    """

    def __init__(self, client: OnlineClient, auth: AuthManager) -> None:
        self._client = client
        self._auth   = auth

    def create_profile(
        self,
        username: str,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Create the public profile row after a new account is registered.

        Required additional columns on the profiles table (run in Supabase SQL editor):
            alter table profiles
                add column if not exists discriminator integer not null default 0,
                add column if not exists last_seen     timestamptz default now(),
                add column if not exists last_networth float not null default 0,
                add column if not exists last_area     text  not null default '';
        """
        import random
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            discriminator = random.randint(1000, 9999)
            return self._client.post(
                "/rest/v1/profiles",
                body={
                    "id":            self._auth.user_id,
                    "username":      username,
                    "discriminator": discriminator,
                },
                extra_headers={"Prefer": "return=representation"},
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def get_profile(
        self,
        user_id: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Fetch a profile row; defaults to the current player."""
        def _do() -> OnlineResult:
            uid = user_id or self._auth.user_id
            if not uid:
                return OnlineResult(success=False, error="No user ID.")
            result = self._client.get(
                "/rest/v1/profiles",
                params={"id": f"eq.{uid}", "limit": "1"},
            )
            if result.success:
                rows = result.data if isinstance(result.data, list) else []
                result.data = rows[0] if rows else None
            return result

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def update_profile(
        self,
        updates: Dict,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """
        Patch the current player's profile.
        Accepted keys: username, title, lifetime_gold, best_day, best_rep, avatar_url
        """
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            return self._client.patch(
                "/rest/v1/profiles",
                body={**updates, "updated_at": "now()"},
                params={"id": f"eq.{self._auth.user_id}"},
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def set_active_title(
        self,
        title_key: str,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Set the player's displayed title (must be already earned)."""
        return self.update_profile({"title": title_key}, callback=callback)

    def award_title(
        self,
        title_key: str,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Award a title to the current player (idempotent; safe to call again)."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            return self._client.post(
                "/rest/v1/earned_titles",
                body={"user_id": self._auth.user_id, "title_key": title_key},
                params={"on_conflict": "user_id,title_key"},
                extra_headers={"Prefer": "resolution=ignore-duplicates"},
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def award_achievement(
        self,
        ach_key: str,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Award an achievement to the current player (idempotent; safe to call again)."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            return self._client.post(
                "/rest/v1/earned_achievements",
                body={"user_id": self._auth.user_id, "ach_key": ach_key},
                params={"on_conflict": "user_id,ach_key"},
                extra_headers={"Prefer": "resolution=ignore-duplicates"},
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def get_earned_titles(
        self,
        user_id: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Return all titles earned by this player with definition info joined."""
        def _do() -> OnlineResult:
            uid = user_id or self._auth.user_id
            if not uid:
                return OnlineResult(success=False, error="No user ID.")
            return self._client.get(
                "/rest/v1/earned_titles",
                params={
                    "select":  "title_key,earned_at,title_definitions(name,icon,rarity,description)",
                    "user_id": f"eq.{uid}",
                    "order":   "earned_at.asc",
                },
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def get_all_titles(
        self, callback: Optional[Callable] = None
    ) -> Optional[OnlineResult]:
        """Fetch the master list of every title definition."""
        def _do() -> OnlineResult:
            return self._client.get(
                "/rest/v1/title_definitions",
                params={"order": "rarity.asc,name.asc"},
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def search_players(
        self,
        query: str,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """
        Search for players by merchant name or UUID.
        Supported query formats:
          "GoldMerchant"         — partial username search (ILIKE)
          "GoldMerchant #4291"   — exact name + 4-digit discriminator tag
          "550e8400-e29b-..."    — UUID exact match (36 chars)
        Returns a list of matching profile rows.
        """
        def _do() -> OnlineResult:
            q = (query or "").strip()
            if not q:
                return OnlineResult(success=True, data=[])

            _fields = "id,username,discriminator,last_seen,last_networth"

            # UUID detection: 36 chars with 4 dashes
            if len(q) == 36 and q.count("-") == 4:
                result = self._client.get(
                    "/rest/v1/profiles",
                    params={"id": f"eq.{q}", "select": _fields, "limit": "1"},
                )
                if result.success:
                    rows = result.data if isinstance(result.data, list) else \
                           ([result.data] if result.data else [])
                    result.data = rows
                return result

            # Name#tag detection
            name_part: str       = q
            tag_part:  Optional[int] = None
            if "#" in q:
                parts = q.rsplit("#", 1)
                name_part = parts[0].strip()
                try:
                    tag_part = int(parts[1].strip())
                except ValueError:
                    pass

            params: Dict[str, str] = {"select": _fields, "limit": "10"}
            if tag_part is not None:
                params["username"]      = f"ilike.{name_part}"
                params["discriminator"] = f"eq.{tag_part}"
            else:
                params["username"] = f"ilike.%{name_part}%"

            result = self._client.get("/rest/v1/profiles", params=params)
            if result.success:
                result.data = result.data if isinstance(result.data, list) else []
            return result

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def update_presence(
        self,
        networth: float,
        area: str = "",
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """
        Update the player's online status: last_seen timestamp and current networth.
        Intended to be called every few minutes while the player is in-game.
        """
        import datetime
        now_str = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        updates: Dict = {
            "last_seen":     now_str,
            "last_networth": round(networth, 2),
        }
        if area:
            updates["last_area"] = area
        return self.update_profile(updates, callback=callback)


# ─────────────────────────────────────────────────────────────────────────────
# FRIENDS MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class FriendsManager:
    """
    Friend requests, accepted friends list, and block.

    Required Supabase SQL:
    ───────────────────
        create table friends (
            id            uuid primary key default gen_random_uuid(),
            requester_id  uuid references auth.users not null,
            addressee_id  uuid references auth.users not null,
            status        text not null default 'pending',
            -- 'pending' | 'accepted' | 'declined' | 'blocked'
            created_at    timestamptz default now(),
            updated_at    timestamptz default now(),
            unique (requester_id, addressee_id)
        );
        alter table friends enable row level security;
        create policy "read own" on friends for select
            using (auth.uid() = requester_id or auth.uid() = addressee_id);
        create policy "insert own" on friends for insert
            with check (auth.uid() = requester_id);
        create policy "update involved" on friends for update
            using (auth.uid() = requester_id or auth.uid() = addressee_id);
        create policy "delete own" on friends for delete
            using (auth.uid() = requester_id or auth.uid() = addressee_id);
    """

    def __init__(self, client: OnlineClient, auth: AuthManager) -> None:
        self._client = client
        self._auth   = auth

    def send_request(
        self,
        addressee_id: str,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Send a friend request to another player."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            return self._client.post(
                "/rest/v1/friends",
                body={
                    "requester_id": self._auth.user_id,
                    "addressee_id": addressee_id,
                    "status":       "pending",
                },
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def respond_to_request(
        self,
        requester_id: str,
        accept: bool,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Accept or decline an incoming friend request."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            return self._client.patch(
                "/rest/v1/friends",
                body={"status": "accepted" if accept else "declined",
                      "updated_at": "now()"},
                params={
                    "requester_id": f"eq.{requester_id}",
                    "addressee_id": f"eq.{self._auth.user_id}",
                    "status":       "eq.pending",
                },
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def remove_friend(
        self,
        other_user_id: str,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Remove a friend or cancel a pending request (both directions)."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            uid = self._auth.user_id
            self._client.delete("/rest/v1/friends",
                params={"requester_id": f"eq.{uid}", "addressee_id": f"eq.{other_user_id}"})
            self._client.delete("/rest/v1/friends",
                params={"requester_id": f"eq.{other_user_id}", "addressee_id": f"eq.{uid}"})
            return OnlineResult(success=True, data={"action": "removed"})

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def block_player(
        self,
        target_id: str,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Block a player — removes any existing friendship first."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            uid = self._auth.user_id
            self._client.delete("/rest/v1/friends",
                params={"requester_id": f"eq.{uid}", "addressee_id": f"eq.{target_id}"})
            self._client.delete("/rest/v1/friends",
                params={"requester_id": f"eq.{target_id}", "addressee_id": f"eq.{uid}"})
            return self._client.post(
                "/rest/v1/friends",
                body={"requester_id": uid, "addressee_id": target_id, "status": "blocked"},
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def list_friends(
        self, callback: Optional[Callable] = None
    ) -> Optional[OnlineResult]:
        """Return all accepted friends (both directions joined)."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            uid = self._auth.user_id
            return self._client.get(
                "/rest/v1/friends",
                params={
                    "select": "requester_id,addressee_id,updated_at",
                    "status": "eq.accepted",
                    "or":     f"(requester_id.eq.{uid},addressee_id.eq.{uid})",
                },
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def list_pending_requests(
        self, callback: Optional[Callable] = None
    ) -> Optional[OnlineResult]:
        """Return incoming pending friend requests addressed to the current player."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            return self._client.get(
                "/rest/v1/friends",
                params={
                    "select":       "requester_id,created_at,profiles(username,discriminator,last_networth)",
                    "addressee_id": f"eq.{self._auth.user_id}",
                    "status":       "eq.pending",
                },
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def list_friends_with_profiles(
        self, callback: Optional[Callable] = None
    ) -> Optional[OnlineResult]:
        """
        Return all accepted friends enriched with their profile data.

        Each item in the list:
            {
                "friend_id":  str,
                "profile":    {username, discriminator, last_seen, last_networth},
                "updated_at": str,
            }
        Max 100 friends returned (matches the 100-friend cap).
        """
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            uid = self._auth.user_id

            # Step 1 — get accepted rows (both directions, up to 100)
            fr = self._client.get(
                "/rest/v1/friends",
                params={
                    "select": "requester_id,addressee_id,updated_at",
                    "status": "eq.accepted",
                    "or":     f"(requester_id.eq.{uid},addressee_id.eq.{uid})",
                    "limit":  "100",
                },
            )
            if not fr.success:
                return fr

            rows = fr.data if isinstance(fr.data, list) else []
            if not rows:
                return OnlineResult(success=True, data=[])

            # Step 2 — extract the other person's UUID for each row
            friend_ids = [
                row["addressee_id"] if row["requester_id"] == uid
                else row["requester_id"]
                for row in rows
            ]

            # Step 3 — batch-fetch profiles in a single request
            ids_csv = ",".join(friend_ids)
            pr = self._client.get(
                "/rest/v1/profiles",
                params={
                    "select": "id,username,discriminator,last_seen,last_networth",
                    "id":     f"in.({ids_csv})",
                    "limit":  "100",
                },
            )
            profiles_by_id: Dict[str, Dict] = {}
            if pr.success and isinstance(pr.data, list):
                for p in pr.data:
                    profiles_by_id[p["id"]] = p

            # Step 4 — combine into unified records
            combined = [
                {
                    "friend_id":  fid,
                    "profile":    profiles_by_id.get(fid, {}),
                    "updated_at": row.get("updated_at"),
                }
                for row, fid in zip(rows, friend_ids)
            ]
            return OnlineResult(success=True, data=combined)

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# INBOX MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class InboxManager:
    """
    Player inbox: system mail, admin rewards, seasonal rewards, notifications.
    Only service-role / admins can INSERT messages; players may read, mark,
    claim, and delete their own messages.

    Required Supabase SQL:
    ───────────────────
        create table inbox_messages (
            id                 bigserial   primary key,
            recipient_id       uuid        references auth.users on delete cascade not null,
            sender_id          uuid        references auth.users on delete set null,
            msg_type           text        not null default 'mail',
            -- 'mail' | 'notification' | 'reward' | 'maintenance' | 'seasonal'
            subject            text        not null default '',
            body               text        not null default '',
            reward_gold        numeric     not null default 0,
            reward_items       jsonb       not null default '{}',
            reward_title       text        not null default '',
            reward_description text        not null default '',
            is_read            boolean     not null default false,
            reward_claimed     boolean     not null default false,
            created_at         timestamptz not null default now(),
            expires_at         timestamptz
        );
        alter table inbox_messages enable row level security;
        create policy "read own"   on inbox_messages for select
            using  (auth.uid() = recipient_id);
        create policy "update own" on inbox_messages for update
            using  (auth.uid() = recipient_id);
        create policy "delete own" on inbox_messages for delete
            using  (auth.uid() = recipient_id);
        -- INSERT requires the service-role key (admin-only).
        -- Use the Supabase Dashboard or a server function with the
        -- service-role key to send in-game messages to players.
    """

    def __init__(self, client: "OnlineClient", auth: "AuthManager") -> None:
        self._client = client
        self._auth   = auth

    # ── Fetch ──────────────────────────────────────────────────────────────────

    def list_messages(
        self,
        limit: int = 50,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Fetch up to *limit* inbox messages for the current player, newest first."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            result = self._client.get(
                "/rest/v1/inbox_messages",
                params={
                    "recipient_id": f"eq.{self._auth.user_id}",
                    "order":        "created_at.desc",
                    "limit":        str(limit),
                    "select": (
                        "id,msg_type,subject,body,reward_gold,"
                        "reward_items,reward_title,reward_description,"
                        "is_read,reward_claimed,created_at,expires_at"
                    ),
                },
            )
            if result.success:
                result.data = result.data if isinstance(result.data, list) else []
            return result

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def get_unread_count(
        self,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Return the number of unread messages as OnlineResult.data (int)."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=True, data=0)
            result = self._client.get(
                "/rest/v1/inbox_messages",
                params={
                    "recipient_id": f"eq.{self._auth.user_id}",
                    "is_read":      "eq.false",
                    "select":       "id",
                    "limit":        "100",
                },
            )
            count = (len(result.data)
                     if (result.success and isinstance(result.data, list))
                     else 0)
            return OnlineResult(success=result.success, data=count,
                                error=result.error)

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    # ── Mark ──────────────────────────────────────────────────────────────────

    def mark_read(
        self,
        msg_id: int,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Mark a single message as read."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            return self._client.patch(
                "/rest/v1/inbox_messages",
                body={"is_read": True},
                params={
                    "id":           f"eq.{msg_id}",
                    "recipient_id": f"eq.{self._auth.user_id}",
                },
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    def mark_all_read(
        self,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Mark all unread messages as read for the current player."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            return self._client.patch(
                "/rest/v1/inbox_messages",
                body={"is_read": True},
                params={
                    "recipient_id": f"eq.{self._auth.user_id}",
                    "is_read":      "eq.false",
                },
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    # ── Claim Reward ──────────────────────────────────────────────────────────

    def claim_reward(
        self,
        msg_id: int,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """
        Mark a reward message as claimed and return its reward payload.
        Returns OnlineResult.data = {
            reward_gold, reward_items, reward_title, reward_description
        } on success.  Returns success=False if already claimed or not found.
        """
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            uid = self._auth.user_id
            # Fetch to verify ownership and unclaimed state
            fetch = self._client.get(
                "/rest/v1/inbox_messages",
                params={
                    "id":           f"eq.{msg_id}",
                    "recipient_id": f"eq.{uid}",
                    "select": (
                        "reward_gold,reward_items,reward_title,"
                        "reward_description,reward_claimed"
                    ),
                    "limit": "1",
                },
            )
            if not fetch.success:
                return fetch
            rows = fetch.data if isinstance(fetch.data, list) else []
            if not rows:
                return OnlineResult(success=False, error="Message not found.")
            row = rows[0]
            if row.get("reward_claimed"):
                return OnlineResult(
                    success=False,
                    error="Reward already claimed.",
                    data={"already_claimed": True},
                )
            # Mark claimed + read atomically
            patch = self._client.patch(
                "/rest/v1/inbox_messages",
                body={"reward_claimed": True, "is_read": True},
                params={
                    "id":           f"eq.{msg_id}",
                    "recipient_id": f"eq.{uid}",
                },
            )
            if not patch.success:
                return patch
            return OnlineResult(success=True, data={
                "reward_gold":        float(row.get("reward_gold")        or 0),
                "reward_items":       dict(row.get("reward_items")        or {}),
                "reward_title":       str(row.get("reward_title")         or ""),
                "reward_description": str(row.get("reward_description")   or ""),
            })

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None

    # ── Delete ────────────────────────────────────────────────────────────────

    def delete_message(
        self,
        msg_id: int,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Permanently delete an inbox message owned by the current player."""
        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in.")
            return self._client.delete(
                "/rest/v1/inbox_messages",
                params={
                    "id":           f"eq.{msg_id}",
                    "recipient_id": f"eq.{self._auth.user_id}",
                },
            )

        if callback is None:
            return _do()
        _run_async(_do, callback)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# SYNC MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class SyncManager:
    """
    Non-blocking background sync with offline queue + retry.

    Usage:
        app.online.sync.push(save_dict, meta)    # call after every save
        app.online.sync.pull(slot, callback)     # download a cloud save

    push() behaviour:
        1. Authenticated + reachable  → upload immediately on daemon thread.
        2. Not signed in / offline    → enqueue; retry on the next push().
        Only the latest save per slot is queued (old pending entries replaced).
    """

    def __init__(self, saves: CloudSaveManager, auth: AuthManager) -> None:
        self._saves = saves
        self._auth  = auth
        self._queue: List[Dict] = []
        self._lock  = threading.Lock()

    def push(
        self,
        save_data: Dict,
        meta: Optional[Dict] = None,
        slot: int = 1,
        callback: Optional[Callable] = None,
    ) -> None:
        """
        Queue a cloud save push; drains any previous pending entries first.
        *callback* is invoked with the final OnlineResult on the worker thread.
        """
        entry = {"save_data": save_data, "meta": meta, "slot": slot}
        with self._lock:
            self._queue = [q for q in self._queue if q["slot"] != slot]
            self._queue.append(entry)

        def _do() -> OnlineResult:
            if not self._auth.is_authenticated:
                return OnlineResult(success=False, error="Not signed in — save queued locally.")
            with self._lock:
                snapshot, self._queue[:] = list(self._queue), []
            last: OnlineResult = OnlineResult(success=True, data={"action": "nothing_queued"})
            for item in snapshot:
                res = self._saves.upload_save(item["save_data"], item["slot"], item["meta"])
                last = res or OnlineResult(success=False, error="upload_save returned None")
                if not last.success:
                    with self._lock:     # re-queue failed item
                        self._queue.insert(0, item)
                    break
            return last

        _run_async(_do, callback)

    def pull(
        self,
        slot: int = 1,
        callback: Optional[Callable] = None,
    ) -> Optional[OnlineResult]:
        """Download the cloud save for the given slot."""
        return self._saves.download_save(slot, callback=callback)

    @property
    def queue_depth(self) -> int:
        """Number of uploads still pending in the offline queue."""
        with self._lock:
            return len(self._queue)
# ─────────────────────────────────────────────────────────────────────────────

class OnlineServices:
    """
    Single entry point for all online functionality.
    Attach to GameApp at startup:  app.online = OnlineServices()

    Subsystems:
        app.online.auth         — AuthManager
        app.online.profile      — ProfileManager
        app.online.saves        — CloudSaveManager
        app.online.sync         — SyncManager  (use this for auto-sync)
        app.online.leaderboard  — LeaderboardManager
        app.online.friends      — FriendsManager
        app.online.guilds       — GuildManager
        app.online.inbox        — InboxManager (mail, rewards, notifications)

    All callbacks receive OnlineResult on a daemon thread.
    Wrap with  app.after(0, ...)  before touching Tkinter widgets.
    """

    def __init__(self) -> None:
        self._http        = OnlineClient()
        self.auth         = AuthManager(self._http)
        self.profile      = ProfileManager(self._http, self.auth)
        self.saves        = CloudSaveManager(self._http, self.auth)
        self.sync         = SyncManager(self.saves, self.auth)
        self.leaderboard  = LeaderboardManager(self._http, self.auth)
        self.friends      = FriendsManager(self._http, self.auth)
        self.guilds       = GuildManager(self._http, self.auth)
        self.inbox        = InboxManager(self._http, self.auth)
        self.verification = VerificationServer()

    def startup(self) -> bool:
        """
        Call once at application launch.
        Restores any saved session; silently refreshes the JWT on a background
        thread.  Returns True if a previous session was found ("remember me").
        """
        had_session = self.auth.load_session()
        if had_session:
            self.auth.refresh_session()   # fire-and-forget
        return had_session

    @property
    def is_online(self) -> bool:
        return self.auth.is_authenticated

    def __repr__(self) -> str:
        status = f"signed in as {self.auth.email!r}" if self.is_online else "offline"
        return f"<OnlineServices {status}>"


# ─────────────────────────────────────────────────────────────────────────────
# CONNECTIVITY CHECK  —  optional sanity ping before showing login UI
# ─────────────────────────────────────────────────────────────────────────────

def check_connectivity(
    callback: Optional[Callable[[bool], None]] = None
) -> Optional[bool]:
    """
    Ping the Supabase project to confirm reachability.
    Returns True / False synchronously if no callback is supplied,
    otherwise runs the check on a daemon thread and calls callback(bool).
    """
    def _do() -> bool:
        try:
            req = urllib.request.Request(
                SUPABASE_URL + "/rest/v1/",
                headers={"apikey": SUPABASE_ANON_KEY},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=5):
                return True
        except Exception:
            return False

    if callback is None:
        return _do()
    threading.Thread(target=lambda: callback(_do()), daemon=True).start()
    return None
