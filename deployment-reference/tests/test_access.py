import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from bot.access import AccessRegistry


class AccessTests(unittest.TestCase):
    def test_only_owner_and_verified_mother_can_register_and_rejection_is_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.db"
            access = AccessRegistry(path, "owner", "+70000000002")
            self.assertEqual(access.check(10, "Owner", "private"), "owner")
            self.assertEqual(access.check(20, "", "private"), "needs_contact")
            self.assertEqual(
                access.check(20, "", "private", {"user_id": 20, "phone_number": "+7 000 000-00-02"}),
                "mother",
            )
            self.assertEqual(access.check(30, "stranger", "private"), "denied")
            self.assertEqual(access.check(10, "renamed_owner", "private"), "owner")
            self.assertEqual(access.check(40, "owner", "private"), "denied")
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM members").fetchone()[0], 2)
                self.assertEqual(
                    db.execute("SELECT decision FROM access_attempts WHERE user_id=30").fetchone()[0],
                    "denied",
                )

    def test_forwarded_contact_and_group_cannot_grant_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            access = AccessRegistry(Path(tmp) / "state.db", "owner", "+70000000002")
            self.assertEqual(access.check(10, "owner", "group"), "denied")
            self.assertEqual(
                access.check(30, "stranger", "private", {"user_id": 20, "phone_number": "+70000000002"}),
                "denied",
            )


if __name__ == "__main__":
    unittest.main()
