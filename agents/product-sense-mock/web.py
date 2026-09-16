#!/usr/bin/env python3
"""The product sense mock interview in your browser.

    python web.py                 # then open http://127.0.0.1:8765

Standard library only. The server holds the API key and the interview state;
the page in web/ only ever sees questions, events, and the debrief.

Two protections matter here, because this server can spend your API credits:

* It listens on 127.0.0.1 only, so other machines on your network cannot reach
  it.
* It rejects requests whose Host header is not this server, and requires JSON
  for every POST. Together those stop an unrelated website open in your
  browser from quietly driving interviews against your key.
"""

import argparse
import json
import os
import re
import secrets
import threading
import webbrowser
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from interview import DEFAULT_LEVEL, DEFAULT_PROMPT, LEVELS, PROMPTS, STAGES, render_debrief
from offline import OfflineError, OfflineSession, new_state
from session import (
    CONTEXT_DIR,
    MODEL,
    LiveSession,
    SessionError,
    explain_api_error,
    load_context,
    snapshot,
)

WEB_ROOT = Path(__file__).resolve().parent / "web"
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
SESSION_PATH = re.compile(r"^/api/sessions/([A-Za-z0-9_-]+)(?:/(answer|quit|retry|debrief\.md))?$")
MAX_BODY_BYTES = 64 * 1024


class InterviewServer(ThreadingHTTPServer):
    """Holds every session in memory. Restarting the server clears them."""

    daemon_threads = True

    def __init__(
        self, address, model=MODEL, effort="high", client_factory=None, context_dir=CONTEXT_DIR
    ):
        super().__init__(address, InterviewHandler)
        self.model = model
        self.effort = effort
        self.client_factory = client_factory
        self.context_dir = context_dir
        self.sessions = {}
        self.locks = {}
        self.registry_lock = threading.Lock()

    @property
    def allowed_hosts(self):
        port = self.server_address[1]
        return {"127.0.0.1:%d" % port, "localhost:%d" % port}

    def live_available(self):
        """Whether live mode is likely to work, for a warning on the page.

        The SDK can also find credentials elsewhere, so a False here is a hint,
        not a block.
        """
        if self.client_factory is not None:
            return True
        return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))

    def make_client(self):
        if self.client_factory is not None:
            return self.client_factory(), None
        import anthropic  # imported lazily so offline mode works without the SDK

        return anthropic.Anthropic(), anthropic


class HttpError(Exception):
    def __init__(self, status, message, retryable=False):
        super().__init__(message)
        self.status = status
        self.message = message
        self.retryable = retryable


class InterviewHandler(BaseHTTPRequestHandler):
    server_version = "ProductSenseMock"

    # --- plumbing ----------------------------------------------------------

    def log_message(self, fmt, *args):
        # Default logging prints every request. Keep the terminal readable.
        pass

    def _send(self, status, body, content_type, extra_headers=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status, payload):
        self._send(status, json.dumps(payload), "application/json; charset=utf-8")

    def _check_host(self):
        if self.headers.get("Host", "") not in self.server.allowed_hosts:
            raise HttpError(HTTPStatus.FORBIDDEN, "Requests must come from this machine.")

    def _read_json(self):
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            raise HttpError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Send JSON.")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise HttpError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "That answer is too long.")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HttpError(HTTPStatus.BAD_REQUEST, "Request body is not valid JSON.")
        if not isinstance(payload, dict):
            raise HttpError(HTTPStatus.BAD_REQUEST, "Request body must be a JSON object.")
        return payload

    def _handle(self, method):
        try:
            self._check_host()
            method()
        except HttpError as exc:
            self._json(exc.status, {"error": exc.message, "retryable": exc.retryable})
        except Exception as exc:  # last resort: never leave the browser hanging
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "Unexpected server error: %s" % exc, "retryable": False},
            )

    def do_GET(self):
        self._handle(self._get)

    def do_POST(self):
        self._handle(self._post)

    # --- routes ------------------------------------------------------------

    def _get(self):
        path = self.path.split("?", 1)[0]
        if path in STATIC:
            name, content_type = STATIC[path]
            self._send(HTTPStatus.OK, (WEB_ROOT / name).read_bytes(), content_type)
            return
        if path == "/api/config":
            self._json(
                HTTPStatus.OK,
                {
                    "prompts": [
                        {"key": key, "question": PROMPTS[key].question} for key in PROMPTS
                    ],
                    "default_prompt": DEFAULT_PROMPT,
                    "levels": [{"key": l.key, "label": l.label} for l in LEVELS.values()],
                    "default_level": DEFAULT_LEVEL,
                    "stages": [
                        {"key": s.key, "label": s.label, "dimension": s.focus[0]}
                        for s in STAGES
                    ],
                    # File names only, so the page can confirm what the interviewer reads.
                    "context_files": [
                        name for name, _ in load_context(self.server.context_dir)
                    ],
                    "live_available": self.server.live_available(),
                    "model": self.server.model,
                },
            )
            return
        match = SESSION_PATH.match(path)
        if match and match.group(2) == "debrief.md":
            session = self._session(match.group(1))
            if not session.done:
                raise HttpError(HTTPStatus.CONFLICT, "The interview is not over yet.")
            report = render_debrief(session.state, when=date.today().isoformat())
            self._send(
                HTTPStatus.OK,
                report + "\n",
                "text/markdown; charset=utf-8",
                {
                    "Content-Disposition": 'attachment; filename="product-sense-debrief-%s.md"'
                    % session.state.prompt.key
                },
            )
            return
        raise HttpError(HTTPStatus.NOT_FOUND, "Not found.")

    def _post(self):
        path = self.path.split("?", 1)[0]
        body = self._read_json()

        if path == "/api/sessions":
            self._create(body)
            return

        match = SESSION_PATH.match(path)
        if not match or match.group(2) in (None, "debrief.md"):
            raise HttpError(HTTPStatus.NOT_FOUND, "Not found.")

        session_id, action = match.group(1), match.group(2)
        session = self._session(session_id)
        lock = self.server.locks[session_id]
        if not lock.acquire(blocking=False):
            raise HttpError(HTTPStatus.CONFLICT, "Still working on your last message.")
        try:
            if action == "answer":
                events = self._run(session, session.answer, body.get("text", ""))
            elif action == "quit":
                events = self._run(session, session.quit)
            else:
                events = self._run(session, session.resume)
        finally:
            lock.release()
        self._json(HTTPStatus.OK, {"id": session_id, "events": events, "session": snapshot(session)})

    def _create(self, body):
        prompt_key = body.get("prompt", DEFAULT_PROMPT)
        if prompt_key not in PROMPTS:
            raise HttpError(HTTPStatus.BAD_REQUEST, "Unknown prompt: %r" % prompt_key)
        level_key = body.get("level", DEFAULT_LEVEL)
        if level_key not in LEVELS:
            raise HttpError(HTTPStatus.BAD_REQUEST, "Unknown level: %r" % level_key)
        mode = body.get("mode", "live")
        state = new_state(prompt_key, level_key)

        if mode == "offline":
            session = OfflineSession(state)
        elif mode == "live":
            try:
                client, anthropic = self.server.make_client()
            except ImportError:
                raise HttpError(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "The anthropic package is not installed. Run "
                    "pip install -r requirements.txt, or use offline mode.",
                )
            # Read per interview, so edits to context files apply without a restart.
            session = LiveSession(
                state,
                client,
                model=self.server.model,
                effort=self.server.effort,
                context=load_context(self.server.context_dir),
            )
            session.anthropic = anthropic
        else:
            raise HttpError(HTTPStatus.BAD_REQUEST, "Mode must be 'live' or 'offline'.")

        session_id = secrets.token_urlsafe(12)
        with self.server.registry_lock:
            self.server.sessions[session_id] = session
            self.server.locks[session_id] = threading.Lock()

        try:
            with self.server.locks[session_id]:
                events = self._run(session, session.start)
        except Exception:
            # The page never received this id, so nothing can use the session.
            with self.server.registry_lock:
                self.server.sessions.pop(session_id, None)
                self.server.locks.pop(session_id, None)
            raise
        self._json(
            HTTPStatus.CREATED, {"id": session_id, "events": events, "session": snapshot(session)}
        )

    # --- helpers -----------------------------------------------------------

    def _session(self, session_id):
        session = self.server.sessions.get(session_id)
        if session is None:
            raise HttpError(
                HTTPStatus.NOT_FOUND,
                "That interview no longer exists. The server may have restarted.",
            )
        return session

    def _run(self, session, action, *args):
        try:
            return action(*args)
        except (SessionError, OfflineError) as exc:
            raise HttpError(HTTPStatus.CONFLICT, str(exc))
        except Exception as exc:
            anthropic = getattr(session, "anthropic", None)
            explained = anthropic and explain_api_error(anthropic, exc, self.server.model)
            if not explained:
                raise
            message, retryable = explained
            raise HttpError(HTTPStatus.BAD_GATEWAY, message, retryable)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the interview in your browser.")
    parser.add_argument("--port", type=int, default=8765, help="default: %(default)s")
    parser.add_argument("--model", default=MODEL, help="default: %(default)s")
    parser.add_argument(
        "--effort",
        default="high",
        choices=["low", "medium", "high", "xhigh", "max"],
        help="thinking effort for live interviews (default: %(default)s)",
    )
    parser.add_argument(
        "--no-open", action="store_true", help="do not open a browser tab automatically"
    )
    args = parser.parse_args(argv)

    server = InterviewServer(("127.0.0.1", args.port), model=args.model, effort=args.effort)
    url = "http://127.0.0.1:%d" % args.port
    print("Product Sense Mock is running at %s" % url)
    if not server.live_available():
        print(
            "No ANTHROPIC_API_KEY found in this terminal. Offline mode works; for live "
            "interviews, stop the server, set the key, and start it again."
        )
    print("Press Ctrl+C to stop.")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
