from __future__ import annotations

from app.data.session import list_local_sqlite_database_urls


def test_local_sqlite_sources_do_not_scan_nested_backup_dirs(tmp_path):
    top = tmp_path / "crispy.db"
    nested_dir = tmp_path / "test_backups"
    nested = nested_dir / "old.db"
    top.write_bytes(b"")
    nested_dir.mkdir()
    nested.write_bytes(b"")

    urls = list_local_sqlite_database_urls(search_root=tmp_path)

    assert any(url.endswith("/crispy.db") for url in urls)
    assert not any(url.endswith("/test_backups/old.db") for url in urls)
