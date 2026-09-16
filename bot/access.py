"""Two explicit family identities, persisted by Telegram's numeric user ID."""

import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


def normalize_phone(value):
    return re.sub(r"[^0-9]", "", str(value or ""))


class AccessRegistry:
    def __init__(self, path, owner_username, mother_phone, owner_id=None, member_id=None):
        self.numeric_ids = {"owner": owner_id, "mother": member_id} if owner_id is not None else None
        self.path = Path(path)
        self.owner_username = owner_username.lstrip("@").casefold()
        self.mother_phone = normalize_phone(mother_phone)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
        self.path.chmod(0o600)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS members (
                    user_id INTEGER PRIMARY KEY,
                    role TEXT NOT NULL UNIQUE CHECK(role IN ('owner','mother')),
                    username TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS access_attempts (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    event TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS access_attempts_time ON access_attempts(created_at);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=10000")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def check(self, user_id, username, chat_type, contact=None, event="message"):
        if type(user_id) is not int or not 0 < user_id < 2**63:
            return "denied"
        username = str(username or "")[:64]
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if self.numeric_ids is not None:
                # Rebuild the two-member registry on each check so removed IDs lose access.
                db.execute("DELETE FROM members")
                for role, allowed_id in self.numeric_ids.items():
                    if allowed_id is not None:
                        db.execute("INSERT INTO members(user_id,role,username,created_at) VALUES(?,?,?,?)",
                                   (allowed_id,role,'',int(time.time())))
            members = {row["role"]: row["user_id"] for row in db.execute("SELECT role,user_id FROM members")}
            decision = "denied"
            if chat_type == "private":
                decision = next((role for role, uid in members.items() if uid == user_id), "denied")
                if decision == "denied" and "owner" not in members and self.owner_username:
                    if username.casefold() == self.owner_username:
                        decision = "owner"
                if decision == "denied" and "mother" not in members and self.mother_phone:
                    if contact is None:
                        decision = "needs_contact"
                    elif (type(contact.get("user_id")) is int and contact["user_id"] == user_id
                          and normalize_phone(contact.get("phone_number")) == self.mother_phone):
                        decision = "mother"
                if decision in ("owner", "mother") and decision not in members:
                    db.execute(
                        "INSERT INTO members(user_id,role,username,created_at) VALUES(?,?,?,?)",
                        (user_id, decision, username, int(time.time())),
                    )
            db.execute(
                "INSERT INTO access_attempts(user_id,username,event,decision,created_at) VALUES(?,?,?,?,?)",
                (user_id, username, str(event)[:32], decision, int(time.time())),
            )
            return decision

    def members(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT user_id,role,username FROM members ORDER BY role")]

    def recent_denials(self, limit=20):
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT user_id,username,event,decision,created_at FROM access_attempts "
                "WHERE decision NOT IN ('owner','mother') ORDER BY id DESC LIMIT ?", (min(limit, 50),)
            )]
