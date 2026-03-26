"""Tests for backup/DR (PRD Section 43.5)."""

import tempfile

from tce.services.backup import (
    RETENTION_DAYS,
    RPO_HOURS,
    RTO_HOURS,
    BackupService,
)


def test_rto_rpo_targets():
    """PRD Section 43.5: RTO=4h, RPO=24h."""
    assert RTO_HOURS == 4
    assert RPO_HOURS == 24


def test_retention_days():
    """PRD Section 43.5: 7 days retention."""
    assert RETENTION_DAYS == 7


def test_create_backup():
    with tempfile.TemporaryDirectory() as tmpdir:
        service = BackupService(backup_dir=tmpdir)
        result = service.create_backup()
        assert result["status"] == "success"
        assert "file" in result


def test_list_backups():
    with tempfile.TemporaryDirectory() as tmpdir:
        service = BackupService(backup_dir=tmpdir)
        service.create_backup()
        backups = service.list_backups()
        assert len(backups) >= 1


def test_cleanup_old_backups():
    with tempfile.TemporaryDirectory() as tmpdir:
        service = BackupService(backup_dir=tmpdir)
        result = service.cleanup_old_backups()
        assert "removed_count" in result


def test_recovery_runbook():
    runbook = BackupService.get_recovery_runbook()
    assert runbook["rto_hours"] == RTO_HOURS
    assert runbook["rpo_hours"] == RPO_HOURS
    assert len(runbook["steps"]) >= 5
    assert "s3_versioning" in runbook
    assert "prompt_backup" in runbook
