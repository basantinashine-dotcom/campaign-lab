"""Tests for backing up the private context folder.

These run real git commands against throwaway repositories in a temp folder:
a bare repository stands in for GitHub, so nothing touches the network.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from sync import PrivateRepo

GIT = shutil.which("git")


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def make_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "commit.gpgsign", "false")
    return path


@unittest.skipUnless(GIT, "git is not installed")
class PrivateRepoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.remote = self.root / "remote.git"
        git(self.root, "init", "-q", "--bare", "-b", "main", str(self.remote))
        self.work = make_repo(self.root / "private")
        git(self.work, "remote", "add", "origin", str(self.remote))
        self.repo = PrivateRepo(self.work)

    def tearDown(self):
        self.tmp.cleanup()

    def remote_commits(self):
        result = subprocess.run(
            ["git", "--git-dir", str(self.remote), "rev-list", "--count", "main"],
            capture_output=True,
            text=True,
        )
        return int(result.stdout.strip()) if result.returncode == 0 else 0

    def test_saves_changes_and_pushes_them(self):
        (self.work / "tips.md").write_text("Anchor to the root problem.", encoding="utf-8")
        self.assertEqual(self.repo.status()["changes"], 1)

        result = self.repo.save("Add tips")

        self.assertEqual(result["status"], "saved", result)
        self.assertEqual(self.remote_commits(), 1)
        self.assertEqual(
            git(self.root, "--git-dir", str(self.remote), "log", "-1", "--format=%s"), "Add tips"
        )
        self.assertEqual(self.repo.status()["changes"], 0)
        self.assertEqual(self.repo.status()["last"]["status"], "saved")

    def test_nothing_to_save(self):
        (self.work / "tips.md").write_text("x", encoding="utf-8")
        self.repo.save("first")
        self.assertEqual(self.repo.save("again")["status"], "nothing")
        self.assertEqual(self.remote_commits(), 1)

    def test_pushes_commits_that_never_made_it_up(self):
        (self.work / "tips.md").write_text("x", encoding="utf-8")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "committed by hand, never pushed")

        result = self.repo.save("nothing new to commit")

        self.assertEqual(result["status"], "saved", result)
        self.assertEqual(self.remote_commits(), 1)

    def test_a_failed_push_keeps_the_commit_and_says_so(self):
        git(self.work, "remote", "set-url", "origin", str(self.root / "missing.git"))
        (self.work / "tips.md").write_text("x", encoding="utf-8")

        result = self.repo.save("Add tips")

        self.assertEqual(result["status"], "failed")
        self.assertIn("upload to GitHub failed", result["detail"])
        self.assertEqual(git(self.work, "log", "-1", "--format=%s"), "Add tips")

    def test_background_save_reports_pending_then_the_result(self):
        (self.work / "tips.md").write_text("x", encoding="utf-8")
        thread = self.repo.save_in_background("Background")
        thread.join(timeout=30)
        self.assertFalse(self.repo.status()["pending"])
        self.assertEqual(self.repo.status()["last"]["status"], "saved")


@unittest.skipUnless(GIT, "git is not installed")
class NotItsOwnRepoTests(unittest.TestCase):
    """The safety check: never commit into whatever repository contains the folder."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_folder_is_not_a_repo(self):
        repo = PrivateRepo(self.root / "private")
        self.assertFalse(repo.is_repo())
        self.assertEqual(repo.save("x")["status"], "not_a_repo")
        self.assertFalse(repo.status()["is_repo"])

    def test_plain_folder_inside_another_repo_is_refused(self):
        public = make_repo(self.root / "public")
        (public / "README.md").write_text("public", encoding="utf-8")
        git(public, "add", "-A")
        git(public, "commit", "-q", "-m", "public start")
        private = public / "agents" / "context" / "private"
        private.mkdir(parents=True)
        (private / "secret.md").write_text("not for the public repo", encoding="utf-8")

        repo = PrivateRepo(private)

        self.assertFalse(repo.is_repo())
        self.assertEqual(repo.save("should not happen")["status"], "not_a_repo")
        self.assertEqual(git(public, "rev-list", "--count", "HEAD"), "1")
        self.assertIn("secret.md", git(public, "status", "--porcelain", "--untracked-files=all"))


if __name__ == "__main__":
    unittest.main()
