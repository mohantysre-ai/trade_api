from pathlib import Path


def test_compose_uses_docker_named_volume_for_state_dir():
    compose = Path(__file__).resolve().parents[2] / "docker-compose.yml"
    text = compose.read_text(encoding="utf-8")

    assert "iros-desk-state:/app/state" in text
    assert "- ./:/app/state" not in text
    assert "iros-backend-data:/app/backend/app/data" in text


def test_pack_and_seed_scripts_reconcile_docker_and_native_state():
    root = Path(__file__).resolve().parents[2]
    pack = (root / "config" / "startup" / "pack-desk-state.ps1").read_text(encoding="utf-8")
    seed = (root / "config" / "startup" / "seed-desk-state-from-hub.ps1").read_text(encoding="utf-8")
    start = (root / "config" / "startup" / "start_docker.bat").read_text(encoding="utf-8")
    assert "docker cp" in pack
    assert "PSNativeCommandUseErrorActionPreference" in pack
    assert "Successfully copied" in pack
    assert "/app/state" in pack
    assert "/app/backend/app/data" in pack
    assert 'Reset-SeedDir "state"' in pack
    assert 'Reset-SeedDir "data"' in pack
    assert "PSNativeCommandUseErrorActionPreference" in seed
    assert "/app/state/" in seed
    assert "/app/backend/app/data/" in seed
    assert "Join-Path $Root" not in seed
    assert "intraday_session.json" in pack
    assert "swing_session.json" in pack
    native_apply = (root / "config" / "startup" / "apply-packed-desk-state-native.ps1").read_text(encoding="utf-8")
    native_sync = (root / "config" / "startup" / "sync-state-before-native.ps1").read_text(encoding="utf-8")
    assert "intraday_session.json" in native_apply
    assert "swing_session.json" in native_apply
    assert "pack-desk-state.ps1" in native_sync
    assert "apply-packed-desk-state-native.ps1" in native_sync
    assert "up --no-start" in start
    assert "seed-desk-state-from-hub.ps1" in start
