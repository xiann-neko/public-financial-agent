import subprocess
import tempfile
import unittest
from pathlib import Path

from fincore.gitsync import save
from fincore.guard import GuardError

PRIVATE = lambda: "private"  # noqa: E731


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def configure(repo):
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")


class SaveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.origin = root / "origin.git"
        git(root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        seed = root / "seed"
        git(root, "clone", "-q", str(self.origin), str(seed))
        configure(seed)
        git(seed, "checkout", "-q", "-b", "main")
        (seed / "data").mkdir()
        (seed / "data" / "transactions.csv").write_text("id\n")
        (seed / "README.md").write_text("hi\n")
        git(seed, "add", ".")
        git(seed, "commit", "-q", "-m", "seed")
        git(seed, "push", "-q", "origin", "main")
        self.repo = root / "work"
        git(root, "clone", "-q", str(self.origin), str(self.repo))
        configure(self.repo)
        git(self.repo, "checkout", "-q", "-b", "claude/session-branch")
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    def origin_main_files(self):
        return git(self.origin, "show", "--stat", "--format=%s", "main")

    def write_data(self, text="id\n1\n"):
        (self.repo / "data" / "transactions.csv").write_text(text)

    def test_pushes_data_to_main(self):
        self.write_data()
        r = save(self.repo, "logged ₱350 Grab", visibility=PRIVATE)
        self.assertEqual(r.status, "pushed", r.detail)
        self.assertIn("data: logged ₱350 Grab", self.origin_main_files())

    def test_nothing_to_save(self):
        self.assertEqual(save(self.repo, "x", visibility=PRIVATE).status, "nothing")

    def test_only_data_is_committed(self):
        self.write_data()
        (self.repo / "README.md").write_text("changed\n")
        save(self.repo, "x", visibility=PRIVATE)
        self.assertNotIn("README", self.origin_main_files())
        self.assertIn("README.md", git(self.repo, "status", "--porcelain"))

    def test_rebases_when_main_moved(self):
        other = self.root / "other"
        git(self.root, "clone", "-q", str(self.origin), str(other))
        configure(other)
        (other / "README.md").write_text("from phone\n")
        git(other, "commit", "-qam", "other change")
        git(other, "push", "-q", "origin", "main")
        self.write_data()
        r = save(self.repo, "x", visibility=PRIVATE)
        self.assertEqual(r.status, "pushed", r.detail)
        log = git(self.origin, "log", "--format=%s", "main")
        self.assertIn("other change", log)
        self.assertIn("data: x", log)

    def test_falls_back_to_branch_on_permission_error(self):
        def fake_run(args, **kw):
            if "push" in args and "HEAD:main" in args:
                return subprocess.CompletedProcess(args, 1, "", "remote: Permission denied\nerror: 403")
            return subprocess.run(args, **kw)
        self.write_data()
        r = save(self.repo, "x", run=fake_run, visibility=PRIVATE)
        self.assertEqual(r.status, "fallback")
        self.assertIn("claude/session-branch", r.detail)
        self.assertIn("data: x", git(self.origin, "log", "--format=%s", "claude/session-branch"))

    def test_does_not_push_code_commits_to_main(self):
        (self.repo / "README.md").write_text("code change\n")
        git(self.repo, "commit", "-qam", "code change")
        self.write_data()
        r = save(self.repo, "x", visibility=PRIVATE)
        self.assertEqual(r.status, "fallback")
        self.assertNotIn("code change", git(self.origin, "log", "--format=%s", "main"))

    def test_refuses_when_public(self):
        self.write_data()
        with self.assertRaises(GuardError):
            save(self.repo, "x", visibility=lambda: "public")
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s"), "seed")


if __name__ == "__main__":
    unittest.main()
