"""
tests/test_auth_rbac.py
Unit-Tests für Meilenstein 4: Multi-User-Architektur & Rollenbasierte Zugriffskontrolle (RBAC).
"""

import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.auth_service import AuthService


class TestAuthRBAC(unittest.TestCase):
    def setUp(self):
        self.auth = AuthService()

    def test_01_default_admin_seeded(self):
        users = self.auth.list_users()
        admin = next((u for u in users if u["role"] == "admin"), None)
        self.assertIsNotNone(admin)
        self.assertEqual(admin["username"], "admin")
        self.assertEqual(admin["display_name"], "Michael Keller")

    def test_02_authenticate_success_and_session(self):
        session = self.auth.authenticate("admin", "archon2026")
        self.assertIsNotNone(session)
        self.assertTrue(session["token"].startswith("tok_"))
        self.assertEqual(session["user"]["role"], "admin")

        # Session validieren
        verified = self.auth.verify_session(session["token"])
        self.assertIsNotNone(verified)
        self.assertEqual(verified["username"], "admin")
        self.assertTrue(verified["permissions"]["can_manage_settings"])

    def test_03_authenticate_failure(self):
        session = self.auth.authenticate("admin", "wrongpassword")
        self.assertIsNone(session)

    def test_04_create_operator_and_viewer(self):
        import uuid
        uid = uuid.uuid4().hex[:6]
        # Operator anlegen
        op = self.auth.create_user(
            username=f"lisa_ops_{uid}",
            password="securepassword123",
            role="operator",
            display_name="Lisa Schmidt",
            email=f"lisa_{uid}@archon.local"
        )
        self.assertEqual(op["role"], "operator")

        # Viewer anlegen
        vw = self.auth.create_user(
            username=f"auditor_max_{uid}",
            password="securepassword123",
            role="viewer",
            display_name="Max Prüfer",
            email=f"max_{uid}@audit.local"
        )
        self.assertEqual(vw["role"], "viewer")

        # Permissions prüfen
        op_perms = self.auth.get_permissions_for_role("operator")
        self.assertTrue(op_perms["can_edit_tasks"])
        self.assertFalse(op_perms["can_manage_settings"])

        vw_perms = self.auth.get_permissions_for_role("viewer")
        self.assertTrue(vw_perms["can_view"])
        self.assertFalse(vw_perms["can_edit_tasks"])
        self.assertFalse(vw_perms["can_manage_settings"])

    def test_05_prevent_deleting_last_admin(self):
        users = self.auth.list_users()
        admins = [u for u in users if u["role"] == "admin"]
        self.assertEqual(len(admins), 1)

        admin_id = admins[0]["id"]
        with self.assertRaises(ValueError):
            self.auth.delete_user(admin_id)

        with self.assertRaises(ValueError):
            self.auth.update_user(admin_id, role="operator")

    def test_06_logout_invalidates_session(self):
        session = self.auth.authenticate("admin", "archon2026")
        token = session["token"]
        self.assertIsNotNone(self.auth.verify_session(token))

        logged_out = self.auth.logout(token)
        self.assertTrue(logged_out)
        self.assertIsNone(self.auth.verify_session(token))


if __name__ == "__main__":
    unittest.main()
