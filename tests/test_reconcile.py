import unittest

from helpers import raven


def fp(sha, kind="file", target=None):
    return raven.Fingerprint(kind=kind, sha256=sha, target=target)


def record(installed, source, kind="file", target=None):
    return raven.ManifestRecord(
        kind=kind, installed_sha256=installed, source_sha256=source, target=target
    )


class ReconcileStateTests(unittest.TestCase):
    """3-way reconcile of a non-managed-block file against its manifest baseline.

    ``installed`` is the destination content Raven last recorded, ``source`` the
    template content at that time, and the fingerprints are the *current*
    destination and template. A baseline where installed != source marks a file
    the user has customized (e.g. an accepted manual merge).
    """

    def test_no_change_since_accept_is_identical(self):
        # Accepted merge: customized baseline, template still matches source.
        self.assertEqual(
            raven.reconcile_state(record("Z", "S1"), fp("Z"), fp("S1")),
            "identical",
        )

    def test_template_change_after_accept_needs_merge(self):
        # Customized baseline, template moved S1 -> S2, user untouched: re-merge.
        self.assertEqual(
            raven.reconcile_state(record("Z", "S1"), fp("Z"), fp("S2")),
            "needs_merge",
        )

    def test_pristine_file_upgrades_on_template_change(self):
        # installed == source (pristine), template moved, user untouched: safe upgrade.
        self.assertEqual(
            raven.reconcile_state(record("S0", "S0"), fp("S0"), fp("S1")),
            "will_upgrade",
        )

    def test_local_edit_without_template_change_needs_merge(self):
        # Pristine baseline, user edited locally, template unchanged: still flagged
        # so an un-accepted local divergence is not silently dropped.
        self.assertEqual(
            raven.reconcile_state(record("S0", "S0"), fp("M"), fp("S0")),
            "needs_merge",
        )

    def test_further_edit_after_accept_needs_merge(self):
        # Accepted baseline (installed != source), then edited again: re-flag.
        self.assertEqual(
            raven.reconcile_state(record("Z", "S1"), fp("Z2"), fp("S1")),
            "needs_merge",
        )

    def test_both_changed_needs_merge(self):
        # Pristine baseline, user edited AND template changed: real conflict.
        self.assertEqual(
            raven.reconcile_state(record("S0", "S0"), fp("M"), fp("S1")),
            "needs_merge",
        )

    def test_missing_source_falls_back_to_two_way_upgrade(self):
        # Legacy manifest without sourceSha256: dest == installed -> upgrade.
        self.assertEqual(
            raven.reconcile_state(record("S0", None), fp("S0"), fp("S1")),
            "will_upgrade",
        )

    def test_missing_source_falls_back_to_two_way_merge(self):
        # Legacy manifest without sourceSha256: dest != installed -> merge.
        self.assertEqual(
            raven.reconcile_state(record("S0", None), fp("M"), fp("S1")),
            "needs_merge",
        )

    def test_symlink_pristine_upgrades_on_target_change(self):
        rec = record("symA", "symA", kind="symlink", target="A")
        self.assertEqual(
            raven.reconcile_state(
                rec, fp("symA", kind="symlink", target="A"), fp("symB", kind="symlink", target="B")
            ),
            "will_upgrade",
        )


if __name__ == "__main__":
    unittest.main()
