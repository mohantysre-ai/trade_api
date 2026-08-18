from pathlib import Path


def test_compose_uses_docker_named_volume_for_state_dir():
    compose = Path(__file__).resolve().parents[2] / "docker-compose.yml"
    text = compose.read_text(encoding="utf-8")

    assert "iros-desk-state:/app/state" in text
    assert "- ./:/app/state" not in text
