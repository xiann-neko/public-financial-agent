import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ["setup", "log", "check", "import", "review", "debt"]


class ClaudeFilesTest(unittest.TestCase):
    def test_skills_have_frontmatter(self):
        for name in SKILLS:
            with self.subTest(skill=name):
                text = (ROOT / ".claude" / "skills" / name / "SKILL.md").read_text()
                m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
                self.assertIsNotNone(m)
                self.assertRegex(m.group(1), rf"(?m)^name: {name}$")
                self.assertRegex(m.group(1), r"(?m)^description: .{20,}")

    def test_session_start_hook(self):
        settings = json.loads((ROOT / ".claude" / "settings.json").read_text())
        commands = [h["command"] for entry in settings["hooks"]["SessionStart"] for h in entry["hooks"]]
        self.assertTrue(any("fin startup" in c for c in commands))

    def test_claude_md_rules(self):
        text = (ROOT / "CLAUDE.md").read_text()
        for phrase in ["./fin save", "never", "--allow-duplicate", "pay period", "public", "./fin debt",
                       "./fin owed"]:
            self.assertIn(phrase, text)

    def test_no_personal_amounts(self):
        files = [ROOT / "CLAUDE.md", *sorted((ROOT / ".claude").rglob("*.md"))]
        for f in files:
            for line in f.read_text().splitlines():
                if re.search(r"₱\s?\d", line):
                    with self.subTest(file=f.name, line=line):
                        self.assertRegex(line, r"e\.g\.|example|\"")


if __name__ == "__main__":
    unittest.main()


class ExampleDataTest(unittest.TestCase):
    def test_example_has_a_card_and_a_loan(self):
        accts = json.loads((ROOT / "data.example" / "accounts.json").read_text())["accounts"]
        self.assertEqual({a.get("kind") for a in accts} >= {"credit_card", "loan"}, True)
        self.assertTrue((ROOT / "data.example" / "installments.json").exists())
