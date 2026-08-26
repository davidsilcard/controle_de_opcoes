from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_dockerfile_caches_dependencies_and_browser_before_application_source() -> None:
    dockerfile = _read("Dockerfile")
    pyproject = _read("pyproject.toml")

    metadata_copy = dockerfile.index("COPY pyproject.toml uv.lock ./")
    dependency_sync = dockerfile.index("uv sync --frozen --no-dev --no-install-project")
    browser_install = dockerfile.index("playwright install --with-deps chromium")
    readme_copy = dockerfile.index("COPY README.md ./")
    source_copy = dockerfile.index("COPY opcoes ./opcoes")
    project_sync = dockerfile.rindex("uv sync --frozen --no-dev")

    assert metadata_copy < dependency_sync < browser_install < readme_copy < source_copy < project_sync
    assert '"gunicorn==23.0.0"' in pyproject
    assert "uv pip install" not in dockerfile


def test_deploy_checks_space_and_only_prunes_project_dangling_images() -> None:
    script = _read("deploy/scripts/update-vps.sh")

    assert 'DOCKER_MIN_FREE_KB="${DOCKER_MIN_FREE_KB:-5242880}"' in script
    assert "docker_root_dir=\"$(docker info --format '{{.DockerRootDir}}')\"" in script
    assert 'docker image prune -f --filter "label=${DOCKER_IMAGE_PRUNE_LABEL}"' in script
    assert "com.docker.compose.project=controle_de_opcoes" in script
    assert "docker system df" in script
    assert "docker system prune" not in script
    assert "docker volume prune" not in script
    assert "docker container prune" not in script

    build = script.index('/bin/bash "$COMPOSE_HELPER" build')
    down = script.index('/bin/bash "$COMPOSE_HELPER" down --remove-orphans')
    up = script.index('/bin/bash "$COMPOSE_HELPER" up -d --no-build --remove-orphans')
    edge_smoke = script.index('wait_for_url "edge"')
    image_prune = script.index("docker image prune")
    cache_prune = script.index("docker builder prune")
    assert build < down < up < edge_smoke < image_prune < cache_prune


def test_readme_requires_root_cause_instead_of_vps_git_bypass() -> None:
    readme = _read("README.md")

    assert "Não use `git checkout`, `safe.directory`" in readme
    assert "git checkout -- deploy/scripts/opcoes-compose-vps.sh" not in readme
