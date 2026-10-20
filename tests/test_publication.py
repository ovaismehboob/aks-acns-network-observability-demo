from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


class PublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = {
            p.relative_to(ROOT).as_posix(): p
            for p in ROOT.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(ROOT).parts
        }
        with tempfile.TemporaryDirectory(prefix="acns-publication-test-") as directory:
            subprocess.run(["git", "init", "--quiet", directory], check=True, capture_output=True)
            result = subprocess.run(
                ["git", "-C", directory, "-c", "core.excludesFile=" + str(ROOT / ".gitignore"),
                 "check-ignore", "--no-index", "--stdin", "-z"],
                input="\0".join(cls.files) + "\0", capture_output=True, text=True,
            )
            if result.returncode not in (0, 1):
                raise RuntimeError("Unable to evaluate publication exclusions.")
            cls.ignored = set(result.stdout.split("\0"))
        cls.public = {name: p for name, p in cls.files.items() if name not in cls.ignored}

    def test_private_and_generated_assets_are_ignored(self):
        for name, path in self.files.items():
            if (
                ".local" in path.relative_to(ROOT).parts
                or name.startswith(("docs/evidence/", "docs/images/"))
                or name == "docs/live-validation.txt"
                or path.suffix in (".pdf", ".docx", ".html", ".pyc")
            ):
                self.assertIn(name, self.ignored, f"Private/generated file is not ignored: {name}")

    def test_public_markdown_does_not_link_to_private_assets(self):
        for name, path in self.public.items():
            if path.suffix != ".md":
                continue
            text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
            for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", text):
                target = target.strip().strip("<>")
                if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target) or target.startswith("#"):
                    continue
                local = unquote(target.split("#")[0])
                if local:
                    resolved = (path.parent / local).resolve()
                    self.assertTrue(resolved.is_relative_to(ROOT), f"Non-portable link in {name}")
                    self.assertIn(resolved.relative_to(ROOT).as_posix(), self.public, f"Missing/excluded link in {name}")

    def test_public_files_have_no_known_credential_patterns_or_environment_ids(self):
        patterns = {
            "private key": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
            "GitHub token": r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b",
            "JWT token": r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
            "storage key": r"(?i)AccountKey\s*=\s*[A-Za-z0-9+/]{40,}={0,2}",
            "SAS signature": r"(?i)[?&]sig=[A-Za-z0-9%+/=]{20,}",
            "credential assignment": r'''(?i)(?:client_secret|password|api_key|access_token)\s*[:=]\s*["'][^"'\r\n]{16,}["']''',
            "local user path": r"(?i)C:[\\/]Users[\\/][^\s`<>]+",
            "environment account label": r"\bMCAPS-[^`\s|]+",
        }
        for name, path in self.public.items():
            self.assertNotIn(path.suffix, (".png", ".pdf", ".docx", ".pyc"), f"Unreviewed binary: {name}")
            text = path.read_text(encoding="utf-8-sig")
            for category, pattern in patterns.items():
                for match in re.finditer(pattern, text):
                    line = text.count("\n", 0, match.start()) + 1
                    self.fail(f"{category} candidate in {name}:{line}; value withheld")
            for match in re.finditer(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b", text):
                # This is the public Azure Managed Grafana token audience, not a tenant identifier.
                self.assertTrue(match[0] == "ce34e7e5-485f-4d76-964f-b3d2b16d1e4f", f"Environment GUID in {name}; value withheld")
            for hostname in re.findall(r"https://([\w.-]+\.(?:grafana\.azure\.com|prometheus\.monitor\.azure\.com))", text):
                self.assertTrue(hostname == "example.grafana.azure.com", f"Live workspace hostname in {name}; value withheld")


if __name__ == "__main__":
    unittest.main()
