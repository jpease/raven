from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import (
    REPO_ROOT,
    attribution_line,
    load_script_module,
    push_plan_line,
    trailer_line,
)


class AiAttributionContentHookTests(unittest.TestCase):
    SCRIPT_PATH = (
        REPO_ROOT / "common" / ".raven" / "git-hooks" / "lib" / "check-ai-attribution-content.py"
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "t@example.com"], check=True
        )
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Test"], check=True)

    def _commit(self, path: str, content: str, message: str = "commit") -> None:
        file_path = self.repo / path
        file_path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", path], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", message], check=True)

    def _stage(self, path: str, content: str) -> None:
        (self.repo / path).write_text(content, encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", path], check=True)

    def _run(self, mode: str, config_text: str | None = None) -> tuple[int, str]:
        if config_text is not None:
            raven_dir = self.repo / ".raven"
            raven_dir.mkdir(exist_ok=True)
            (raven_dir / "config.toml").write_text(config_text, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT_PATH), mode],
            capture_output=True,
            text=True,
            cwd=str(self.repo),
        )
        return result.returncode, result.stderr

    def test_blocks_staged_content_mentioning_claude(self):
        self._commit("README.md", "# repo\n")
        self._stage("notes.py", attribution_line("Claude") + "print('hi')\n")
        rc, err = self._run("staged")
        self.assertEqual(rc, 1)
        self.assertIn("staged diff", err)

    def test_allows_staged_clean_content(self):
        self._commit("README.md", "# repo\n")
        self._stage("notes.py", "# written by the platform team\nprint('hi')\n")
        rc, _ = self._run("staged")
        self.assertEqual(rc, 0)

    def test_outbound_blocks_content_against_origin_main(self):
        self._commit("README.md", "# repo\n")
        base_sha = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "-C", str(self.repo), "update-ref", "refs/remotes/origin/main", base_sha],
            check=True,
        )
        self._commit(
            "notes.py",
            attribution_line("Copilot", verb="Implemented", prep="with") + "print('hi')\n",
        )
        rc, err = self._run("outbound")
        self.assertEqual(rc, 1)
        self.assertIn("origin/main..HEAD", err)

    def test_outbound_allows_clean_content(self):
        self._commit("README.md", "# repo\n")
        base_sha = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "-C", str(self.repo), "update-ref", "refs/remotes/origin/main", base_sha],
            check=True,
        )
        self._commit("notes.py", "print('hi')\n")
        rc, _ = self._run("outbound")
        self.assertEqual(rc, 0)

    def test_outbound_skips_when_no_base_ref(self):
        self._commit("notes.py", attribution_line("Claude") + "print('hi')\n")
        rc, _ = self._run("outbound")
        self.assertEqual(rc, 0)

    def test_respects_block_ai_attribution_content_false_in_config(self):
        self._commit("README.md", "# repo\n")
        self._stage("notes.py", attribution_line("Claude") + "print('hi')\n")
        rc, _ = self._run(
            "staged", config_text="[git_hooks]\nblock_ai_attribution_content = false\n"
        )
        self.assertEqual(rc, 0)

    def test_default_blocks_when_no_config(self):
        self._commit("README.md", "# repo\n")
        self._stage("notes.py", attribution_line("Claude") + "print('hi')\n")
        rc, _ = self._run("staged")
        self.assertEqual(rc, 1)

    _ZERO_SHA = "0" * 40

    def _run_plan(self, plan: str, remote: str = "origin") -> tuple[int, str]:
        # `outbound --push-plan` reads Git's pre-push plan from stdin. The flag
        # makes reading stdin opt-in, so a bare `outbound` never blocks on a tty.
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT_PATH), "outbound", "--push-plan", "--remote", remote],
            input=plan,
            capture_output=True,
            text=True,
            cwd=str(self.repo),
        )
        return result.returncode, result.stderr

    def _rev_parse(self, rev: str = "HEAD") -> str:
        return subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", rev],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def _git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)

    def test_push_plan_scans_the_pushed_ref_not_head(self):
        # Issue #126: with `main` checked out, pushing `feature` must scan
        # `feature`. The old HEAD-relative range saw nothing here.
        self._commit("README.md", "# repo\n")
        base = self._rev_parse()
        self._git("update-ref", "refs/remotes/origin/main", base)
        self._git("checkout", "-q", "-b", "feature")
        self._commit("notes.py", attribution_line("Claude") + "print('hi')\n")
        feature = self._rev_parse()
        self._git("checkout", "-q", "-")

        rc, err = self._run_plan(push_plan_line("refs/heads/feature", feature, self._ZERO_SHA))

        self.assertEqual(rc, 1, err)
        self.assertIn("refs/heads/feature", err)

    def test_push_plan_skips_deletion_lines(self):
        self._commit("README.md", "# repo\n")
        base = self._rev_parse()
        self._git("update-ref", "refs/remotes/origin/main", base)
        self._commit("notes.py", attribution_line("Claude") + "print('hi')\n")

        rc, err = self._run_plan(push_plan_line("(delete)", self._ZERO_SHA, self._rev_parse()))

        self.assertEqual(rc, 0, err)

    def test_push_plan_skips_unresolvable_local_sha(self):
        # Fail-open: an object this repo cannot resolve cannot be evaluated, and
        # must not fall back to a HEAD-relative range (HEAD would be flagged).
        self._commit("README.md", "# repo\n")
        self._git("update-ref", "refs/remotes/origin/main", self._rev_parse())
        self._commit("notes.py", attribution_line("Claude") + "print('hi')\n")

        rc, err = self._run_plan(push_plan_line("refs/heads/main", "1" * 40, self._ZERO_SHA))

        self.assertEqual(rc, 0, err)

    def test_push_plan_with_no_usable_refs_does_not_fall_back_to_head(self):
        self._commit("README.md", "# repo\n")
        self._git("update-ref", "refs/remotes/origin/main", self._rev_parse())
        self._commit("notes.py", attribution_line("Claude") + "print('hi')\n")

        rc, err = self._run_plan("")

        self.assertEqual(rc, 0, err)

    def test_push_plan_new_branch_is_bounded_by_remote_tracking_refs(self):
        self._commit("README.md", "# repo\n")
        self._commit("legacy.py", attribution_line("Gemini") + "print('legacy')\n")
        self._git("update-ref", "refs/remotes/origin/main", self._rev_parse())
        self._git("checkout", "-q", "-b", "brand-new")
        self._commit("clean.py", "print('ok')\n")

        rc, err = self._run_plan(
            push_plan_line("refs/heads/brand-new", self._rev_parse(), self._ZERO_SHA)
        )

        self.assertEqual(rc, 0, err)
        self.assertNotIn("Gemini", err)

    def test_push_plan_uses_the_named_remote_for_bounding(self):
        self._commit("README.md", "# repo\n")
        self._commit("legacy.py", attribution_line("Gemini") + "print('legacy')\n")
        self._git("update-ref", "refs/remotes/fork/main", self._rev_parse())
        self._git("checkout", "-q", "-b", "brand-new")
        self._commit("clean.py", "print('ok')\n")

        rc, err = self._run_plan(
            push_plan_line("refs/heads/brand-new", self._rev_parse(), self._ZERO_SHA),
            remote="fork",
        )

        self.assertEqual(rc, 0, err)
        self.assertNotIn("Gemini", err)

    def test_push_plan_scans_all_refs_and_reports_each_hit(self):
        self._commit("README.md", "# repo\n")
        base = self._rev_parse()
        self._git("update-ref", "refs/remotes/origin/main", base)
        self._git("checkout", "-q", "-b", "one")
        self._commit("one.py", "print('ok')\n")
        one = self._rev_parse()
        self._git("checkout", "-q", base)
        self._git("checkout", "-q", "-b", "two")
        self._commit("two.py", attribution_line("Codex") + "print('hi')\n")
        two = self._rev_parse()

        rc, err = self._run_plan(
            push_plan_line("refs/heads/one", one, self._ZERO_SHA)
            + push_plan_line("refs/heads/two", two, self._ZERO_SHA)
        )

        self.assertEqual(rc, 1, err)
        self.assertIn("refs/heads/one", err)
        self.assertIn("refs/heads/two", err)
        self.assertIn("Codex", err)

    def test_push_plan_respects_disabled_config(self):
        self._commit("README.md", "# repo\n")
        self._git("update-ref", "refs/remotes/origin/main", self._rev_parse())
        raven_dir = self.repo / ".raven"
        raven_dir.mkdir(exist_ok=True)
        (raven_dir / "config.toml").write_text(
            "[git_hooks]\nblock_ai_attribution_content = false\n", encoding="utf-8"
        )
        self._commit("notes.py", attribution_line("Claude") + "print('hi')\n")

        rc, err = self._run_plan(push_plan_line("refs/heads/main", self._rev_parse(), "0" * 40))

        self.assertEqual(rc, 0, err)

    def test_push_plan_falls_back_to_tracking_refs_when_remote_sha_is_unresolvable(self):
        # Common in practice: the remote ref points at a commit this clone has
        # never fetched. That tip cannot bound the scan, so the remote's tracking
        # refs must -- the new commit is still caught, the published one is not.
        self._commit("README.md", "# repo\n")
        self._commit("legacy.py", attribution_line("Gemini") + "print('legacy')\n")
        self._git("update-ref", "refs/remotes/origin/main", self._rev_parse())
        self._commit("notes.py", attribution_line("Claude") + "print('hi')\n")

        rc, err = self._run_plan(push_plan_line("refs/heads/main", self._rev_parse(), "1" * 40))

        self.assertEqual(rc, 1, err)
        self.assertIn("Claude", err)
        self.assertNotIn("Gemini", err)

    def test_push_plan_with_nothing_known_on_any_remote_scans_full_history(self):
        # Deliberate: with no remote SHA and no tracking refs anywhere, nothing is
        # known to be published, so every reachable commit genuinely is leaving
        # the machine for the first time and scanning all of it is correct rather
        # than a false positive. Pinned so it cannot change by accident.
        self._commit("README.md", "# repo\n")
        self._commit("legacy.py", attribution_line("Gemini") + "print('legacy')\n")
        self._git("checkout", "-q", "-b", "brand-new")
        self._commit("clean.py", "print('ok')\n")

        rc, err = self._run_plan(
            push_plan_line("refs/heads/brand-new", self._rev_parse(), self._ZERO_SHA)
        )

        self.assertEqual(rc, 1, err)
        self.assertIn("Gemini", err)

    def test_push_plan_force_push_scans_rewritten_commits(self):
        self._commit("README.md", "# repo\n")
        base = self._rev_parse()
        self._commit("notes.py", "print('hi')\n")
        published = self._rev_parse()
        self._git("update-ref", "refs/remotes/origin/main", published)
        self._git("reset", "-q", "--hard", base)
        self._commit("notes.py", attribution_line("Claude") + "print('hi')\n")
        rewritten = self._rev_parse()
        self.assertNotEqual(rewritten, published)

        rc, err = self._run_plan(push_plan_line("refs/heads/main", rewritten, published))

        self.assertEqual(rc, 1, err)
        self.assertIn("Claude", err)

    def test_push_plan_blocks_attribution_trailer_in_commit_message(self):
        # The commit-msg hook strips these, but stripping only happens when that
        # hook ran. `--no-verify`, `git cherry-pick`, `git rebase` reapplying
        # pre-hook commits, and clones made before install all put a trailer into
        # history that never passed strip-time; pre-push is where that surfaces.
        self._commit("README.md", "# repo\n")
        base = self._rev_parse()
        self._git("update-ref", "refs/remotes/origin/main", base)
        self._commit("notes.py", "print('hi')\n", message="feat: thing\n\n" + trailer_line())

        rc, err = self._run_plan(push_plan_line("refs/heads/main", self._rev_parse(), base))

        self.assertEqual(rc, 1, err)
        self.assertIn("Claude", err)
        self.assertIn("commit message", err)

    def test_push_plan_blocks_bare_noreply_trailer_in_commit_message(self):
        # The `<noreply@...>` arm catches bots this pattern does not name.
        self._commit("README.md", "# repo\n")
        base = self._rev_parse()
        self._git("update-ref", "refs/remotes/origin/main", base)
        self._commit(
            "notes.py",
            "print('hi')\n",
            message="feat: thing\n\n" + trailer_line(tool="Some Bot", email="noreply@example.test"),
        )

        rc, err = self._run_plan(push_plan_line("refs/heads/main", self._rev_parse(), base))

        self.assertEqual(rc, 1, err)

    def test_push_plan_allows_clean_commit_message(self):
        # Negative control for the message gate: an ordinary human co-author
        # trailer and an ordinary subject must not trip it.
        self._commit("README.md", "# repo\n")
        base = self._rev_parse()
        self._git("update-ref", "refs/remotes/origin/main", base)
        self._commit(
            "notes.py",
            "print('hi')\n",
            message="feat: thing\n\n" + trailer_line(tool="A Human", email="human@example.com"),
        )

        rc, err = self._run_plan(push_plan_line("refs/heads/main", self._rev_parse(), base))

        self.assertEqual(rc, 0, err)

    def test_push_plan_message_scan_is_bounded_by_remote_tracking_refs(self):
        # The message scan reuses the patch scan's revision bounds, so a trailer
        # in an already-published ancestor is not re-reported on every later push.
        self._commit("README.md", "# repo\n", message="old\n\n" + trailer_line())
        published = self._rev_parse()
        self._git("update-ref", "refs/remotes/origin/main", published)
        self._commit("notes.py", "print('hi')\n", message="feat: clean")

        rc, err = self._run_plan(push_plan_line("refs/heads/main", self._rev_parse(), published))

        self.assertEqual(rc, 0, err)

    def test_push_plan_scans_merge_commit_messages(self):
        # A merge contributes no patch of its own, so the content scan cannot see
        # it; the message scan is the only gate on a trailer in a merge message.
        self._commit("README.md", "# repo\n")
        base = self._rev_parse()
        self._git("update-ref", "refs/remotes/origin/main", base)
        self._git("checkout", "-q", "-b", "side")
        self._commit("side.py", "print('side')\n")
        self._git("checkout", "-q", "-")
        self._commit("main.py", "print('main')\n")
        self._git(
            "merge",
            "--no-ff",
            "-q",
            "-m",
            "merge: side\n\n" + trailer_line(),
            "side",
        )

        rc, err = self._run_plan(push_plan_line("refs/heads/merged", self._rev_parse(), base))

        self.assertEqual(rc, 1, err)

    def test_push_plan_unbounded_scan_explains_the_missing_remote_baseline(self):
        # Behaviour stays as pinned by the full-history test above: scanning
        # everything is correct when nothing is known to be published. What was
        # missing is *why*, on the one push where a block is least actionable.
        self._commit("README.md", "# repo\n")
        self._commit("legacy.py", attribution_line("Gemini") + "print('legacy')\n")

        rc, err = self._run_plan(
            push_plan_line("refs/heads/brand-new", self._rev_parse(), self._ZERO_SHA)
        )

        self.assertEqual(rc, 1, err)
        self.assertIn("no remote baseline", err)
        self.assertIn("block_ai_attribution_content", err)

    def test_bounded_scan_does_not_print_the_unbounded_notice(self):
        # Negative control: the notice must not appear on an ordinary push.
        self._commit("README.md", "# repo\n")
        base = self._rev_parse()
        self._git("update-ref", "refs/remotes/origin/main", base)
        self._commit("notes.py", attribution_line("Claude") + "print('hi')\n")

        rc, err = self._run_plan(push_plan_line("refs/heads/main", self._rev_parse(), base))

        self.assertEqual(rc, 1, err)
        self.assertNotIn("no remote baseline", err)

    def test_message_pattern_matches_the_commit_msg_hook_pattern(self):
        # The two gates must agree on what a forbidden trailer is. They are
        # deliberately not shared by import: commit-msg has no dependency on
        # lib/, so a partial install cannot break it. This pins them instead.
        lib = load_script_module("ai_attribution_content_lib_for_pattern_check", self.SCRIPT_PATH)
        hook = load_script_module(
            "commit_msg_hook_for_pattern_check",
            REPO_ROOT / "common" / ".raven" / "git-hooks" / "commit-msg",
        )
        self.assertEqual(lib._MESSAGE_PATTERN.pattern, hook._AI_TRAILER.pattern)
        self.assertEqual(lib._MESSAGE_PATTERN.flags, hook._AI_TRAILER.flags)

    def test_script_is_executable(self):
        self.assertTrue(self.SCRIPT_PATH.stat().st_mode & 0o111)


if __name__ == "__main__":
    unittest.main()
