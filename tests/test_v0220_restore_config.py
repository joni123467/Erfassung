"""Rücksicherung erhält die aktive Datenbank- und Deploymentkonfiguration."""
import json
import zipfile

from test_v0209 import main


def test_config_restore_preserves_normalized_database_env_and_docker_paths(main, tmp_path):
    from app import paths, restore_manager

    protected = {
        "database.json": b'{"type":"postgresql","name":"active-target"}',
        ".env": b"DB_TYPE=postgresql\n",
        ".env.production": b"DB_HOST=active-target\n",
        "production.env": b"DB_NAME=active-target\n",
        "compose.yaml": b"services: {}\n",
        "docker-compose.override.yml": b"services: {}\n",
        "Dockerfile": b"FROM active-target\n",
    }
    for name, content in protected.items():
        (paths.CONFIG_DIR / name).write_bytes(content)
    allowed = {"system.json": b'{"timezone":"Europe/Berlin"}', "logging.json": b'{"level":"INFO"}', "retention.json": b'{"enabled":false}', "backup.json": b'{"enabled":false}', "timemoto.json": b'{"enabled":false}'}
    archive_path = tmp_path / "settings.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name in protected:
            archive.writestr(f"config/{name}", b"source-must-not-be-activated")
            archive.writestr(f"config/./{name}", b"normalized-source-must-not-be-activated")
        archive.writestr("config/sub/../database.json", b"parent-segment")
        archive.writestr("config/../outside.json", b"outside")
        archive.writestr("config/new-deployment.env", b"DB_TYPE=mysql")
        for name, content in allowed.items():
            archive.writestr(f"config/./{name}", content)
    assert restore_manager._restore_config(archive_path) == len(allowed)
    for name, content in protected.items():
        assert (paths.CONFIG_DIR / name).read_bytes() == content
    for name, content in allowed.items():
        assert (paths.CONFIG_DIR / name).read_bytes() == content
    assert not (paths.CONFIG_DIR / "new-deployment.env").exists()
    assert not (paths.CONFIG_DIR.parent / "outside.json").exists()


def test_allowed_config_symlink_cannot_replace_database_configuration(main, tmp_path):
    from app import paths, restore_manager

    database_path = paths.CONFIG_DIR / "database.json"
    database_path.write_bytes(b"active-target")
    system_path = paths.CONFIG_DIR / "system.json"
    system_path.unlink(missing_ok=True)
    system_path.symlink_to(database_path)
    archive_path = tmp_path / "aliased-settings.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("config/system.json", b"must-not-change-target")
    assert restore_manager._restore_config(archive_path) == 0
    assert database_path.read_bytes() == b"active-target"


def test_full_restore_keeps_active_database_config_and_reverts_business_data(main, tmp_path):
    from app import backup_manager, database, models, paths, restore_manager

    active_config = json.dumps({"type": "sqlite", "sqlite_path": database.engine.url.database}).encode()
    (paths.CONFIG_DIR / "database.json").write_bytes(active_config)
    original = backup_manager.create_safety_backup(prefix="test-original")
    imported_archive = tmp_path / "different-source-config.zip"
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(imported_archive, "w") as target:
        for member in source.infolist():
            if member.filename != "config/database.json":
                target.writestr(member, source.read(member.filename))
        target.writestr("config/./database.json", '{"type":"postgresql","name":"source-database"}')
    with database.SessionLocal() as db:
        db.add(models.Company(name="Nach Sicherung angelegt"))
        db.commit()
    result = restore_manager.perform_restore(imported_archive, username="test", token="config-regression")
    assert result["status"] == "success", result["message"]
    assert result["safety_backup"]
    assert (paths.CONFIG_DIR / "database.json").read_bytes() == active_config
    with database.SessionLocal() as db:
        assert db.query(models.Company).filter_by(name="Nach Sicherung angelegt").first() is None
        assert db.query(models.User).filter_by(username="admin").one()
