"""Back up the private context folder to its own private GitHub repository.

This runs the same three commands you would run by hand inside
``context/private``: ``git add -A``, ``git commit``, ``git push``.

The one check that matters most: the folder must be a Git repository in its
own right. ``context/private`` sits inside the public learn-by-building
checkout, and Git looks upward for a repository. Without the check, a missing
private repo would make ``git add`` and ``git commit`` land in the *public*
repository. So ``is_repo`` requires a ``.git`` inside the folder itself and
confirms Git agrees that the folder is the top of its own repository.
"""

import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from session import CONTEXT_DIR

PRIVATE_DIR = CONTEXT_DIR / "private"
GIT_TIMEOUT_SECONDS = 60


class PrivateRepo:
    def __init__(self, directory=PRIVATE_DIR):
        self.directory = Path(directory)
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self.last = None
        self.pending = False

    # --- inspection --------------------------------------------------------

    def is_repo(self):
        if not (self.directory / ".git").exists():
            return False
        result = self._git("rev-parse", "--show-toplevel")
        if result is None or result.returncode != 0:
            return False
        try:
            return Path(result.stdout.strip()).resolve() == self.directory.resolve()
        except OSError:
            return False

    def changed_files(self):
        """Paths with uncommitted changes, or None if this is not a usable repo."""
        if not self.is_repo():
            return None
        result = self._git("status", "--porcelain")
        if result is None or result.returncode != 0:
            return None
        return [line[3:] for line in result.stdout.splitlines() if line.strip()]

    def status(self):
        changes = self.changed_files()
        with self._state_lock:
            return {
                "is_repo": changes is not None,
                "changes": len(changes) if changes is not None else 0,
                "changed_files": (changes or [])[:20],
                "pending": self.pending,
                "last": self.last,
            }

    # --- saving ------------------------------------------------------------

    def save(self, message):
        """Commit everything and push. Returns a result dict; never raises for git failures."""
        with self._lock:
            result = self._save(message)
        with self._state_lock:
            self.last = dict(result, at=datetime.now().isoformat(timespec="seconds"))
            return self.last

    def save_in_background(self, message):
        with self._state_lock:
            self.pending = True

        def work():
            try:
                self.save(message)
            finally:
                with self._state_lock:
                    self.pending = False

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        return thread

    def _save(self, message):
        if not self.is_repo():
            return {
                "status": "not_a_repo",
                "detail": "context/private is not its own Git repository, so results were "
                "saved on this computer only.",
            }

        status = self._git("status", "--porcelain")
        if status is None or status.returncode != 0:
            return self._failure("Could not read the folder's Git status.", status)

        committed = False
        if status.stdout.strip():
            add = self._git("add", "-A")
            if add is None or add.returncode != 0:
                return self._failure("git add failed.", add)
            commit = self._git("commit", "-m", message)
            if commit is None or commit.returncode != 0:
                return self._failure("git commit failed.", commit)
            committed = True

        if not committed and not self._has_unpushed_commits():
            return {"status": "nothing", "detail": "Everything was already saved to GitHub."}

        push = self._git("push", "-u", "origin", "HEAD")
        if push is None or push.returncode != 0:
            detail = "Saved on this computer, but the upload to GitHub failed."
            if push is not None and "Authentication" in (push.stderr or "") + (push.stdout or ""):
                detail += " GitHub login needed: run git push once inside context/private."
            return self._failure(detail, push)
        return {"status": "saved", "detail": "Saved to GitHub."}

    def _has_unpushed_commits(self):
        result = self._git("rev-list", "--count", "@{u}..HEAD")
        if result is None:
            return False
        if result.returncode != 0:
            # No upstream yet: anything committed has never been pushed.
            head = self._git("rev-parse", "--verify", "HEAD")
            return head is not None and head.returncode == 0
        return result.stdout.strip() not in ("", "0")

    def _failure(self, detail, result):
        output = ""
        if result is not None:
            output = (result.stderr or result.stdout or "").strip().splitlines()
            output = output[-1] if output else ""
        return {"status": "failed", "detail": detail, "git": output}

    def _git(self, *args):
        env = dict(os.environ)
        # Fail fast instead of waiting on a login prompt nobody can see: this
        # can run from a background thread of the web server.
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GCM_INTERACTIVE"] = "never"
        try:
            return subprocess.run(
                ["git", "-C", str(self.directory), *args],
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT_SECONDS,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
