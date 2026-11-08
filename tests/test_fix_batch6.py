import re
import pytest


def test_s01_wissensbibliothek_escapes_title():
    """S-01: wissensbibliothek.js darf book.title nicht unescaped in innerHTML oder title-Attribut rendern."""
    with open("static/js/wissensbibliothek.js", "r", encoding="utf-8") as f:
        content = f.read()

    # Vor dem Fix steht dort unescaped:
    # <span class="truncate max-w-[280px]" title="${book.title}">${book.title}</span>
    assert 'title="${book.title}"' not in content, "S-01 BUG: Unescaped book.title in title attribute"
    assert '>${book.title}</span>' not in content, "S-01 BUG: Unescaped book.title in span innerHTML"
    assert "onclick=\"previewLibraryBook('${book.rel_path}', '${book.title.replace(" not in content, "S-01 BUG: Unsafe string interpolation in onclick"


def test_s02_approval_queue_escapes_title():
    """S-02: approval_policies_controller.js darf r.title nicht unescaped in HTML rendern."""
    with open("static/js/approval_policies_controller.js", "r", encoding="utf-8") as f:
        content = f.read()

    # Vor dem Fix steht dort unescaped:
    # <div class="font-bold text-[var(--foreground)] truncate max-w-[200px]" title="${r.title}">${r.title}</div>
    assert 'title="${r.title}">${r.title}</div>' not in content, "S-02 BUG: Unescaped r.title in approvals queue"


def test_s03_auth_manager_escapes_display_name_and_validates_username(tmp_path, monkeypatch):
    """S-03: auth_manager.js muss display_name escapen und auth_service.py muss boesartige Usernames ablehnen."""
    with open("static/js/auth_manager.js", "r", encoding="utf-8") as f:
        content = f.read()

    assert '<div class="text-[var(--foreground)] font-medium">${u.display_name}</div>' not in content, "S-03 BUG: Unescaped u.display_name in user table"
    assert "handleDeleteUser('${u.id}', '${u.username}')" not in content, "S-03 BUG: Unescaped u.username in onclick"

    # Backend: auth_service.py darf Usernames mit Script/Quotes nicht anlegen
    from backend.auth_service import AuthService
    db_path = tmp_path / "auth_test.db"
    import backend.auth_service as auth_mod
    monkeypatch.setattr(auth_mod, "DB_PATH", str(db_path))

    svc = AuthService()
    with pytest.raises(ValueError, match="Ungueltiger Benutzername"):
        svc.create_user("attacker'<script>", "password123")
