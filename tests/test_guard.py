import unittest
from unittest import mock
from urllib.error import HTTPError, URLError

from fincore.guard import parse_github_repo, repo_visibility

URL = "https://github.com/a/b"


def fake(result=None, exc=None):
    def f(url):
        if exc:
            raise exc
        return result
    return f


class VisibilityTest(unittest.TestCase):
    def test_public(self):
        self.assertEqual(repo_visibility(URL, fetch=fake({"private": False})), "public")

    def test_private(self):
        self.assertEqual(repo_visibility(URL, fetch=fake({"private": True})), "private")

    def test_404_means_private(self):
        err = HTTPError(URL, 404, "Not Found", None, None)
        self.assertEqual(repo_visibility(URL, fetch=fake(exc=err)), "private")

    def test_network_error_is_unknown(self):
        self.assertEqual(repo_visibility(URL, fetch=fake(exc=URLError("down"))), "unknown")

    def test_non_github_remote_is_unknown(self):
        self.assertEqual(repo_visibility("https://gitlab.com/a/b", fetch=fake({"private": False})), "unknown")

    def test_parses_https_and_ssh(self):
        self.assertEqual(parse_github_repo("git@github.com:a/b.git"), "a/b")
        self.assertEqual(parse_github_repo("https://github.com/a/b"), "a/b")
        self.assertEqual(parse_github_repo("http://local_proxy@127.0.0.1:1234/git/a/b"), None)


if __name__ == "__main__":
    unittest.main()
