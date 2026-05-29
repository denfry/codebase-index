#!/usr/bin/env python3
"""bootstrap.py — пост-установочный bootstrap для skill codebase-index.

Запускается инсталлятором (install.sh / install.ps1) после раскладки файлов.
Задачи:
  * проверить версию Python (минимум 3.9);
  * при наличии Python создать локальный .venv внутри директории skill;
  * установить зависимости из requirements.txt, если файл существует;
  * записать runtime-метаданные (runtime.json);
  * при наличии install_manifest.json — дополнить его python_version
    и bootstrap_status (если манифест ещё не создан, инсталлятор сделает это сам).

Без внешних зависимостей — только стандартная библиотека.

Коды возврата:
  0  — успех (или безопасный пропуск)
  1  — критическая ошибка bootstrap
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import venv
from datetime import datetime, timezone
from pathlib import Path

MIN_PYTHON = (3, 9)

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)
log = logging.getLogger("bootstrap")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap codebase-index skill (создание venv и метаданных)."
    )
    parser.add_argument(
        "--skill-dir",
        required=True,
        type=Path,
        help="Директория установленного skill (куда скопирован SKILL.md).",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Путь к install_manifest.json для дополнения (если уже существует).",
    )
    parser.add_argument(
        "--target",
        default="unknown",
        help="Целевой CLI (claude|codex|opencode).",
    )
    parser.add_argument(
        "--no-venv",
        action="store_true",
        help="Не создавать venv (только записать метаданные).",
    )
    return parser.parse_args(argv)


def check_python_version() -> None:
    if sys.version_info[: len(MIN_PYTHON)] < MIN_PYTHON:
        log.error(
            "Требуется Python >= %s, текущий — %s",
            ".".join(map(str, MIN_PYTHON)),
            ".".join(map(str, sys.version_info[:3])),
        )
        raise SystemExit(1)


def create_venv(skill_dir: Path) -> Path:
    """Создаёт .venv внутри skill_dir и возвращает путь к нему."""
    venv_dir = skill_dir / ".venv"
    if venv_dir.exists():
        log.info("venv уже существует: %s", venv_dir)
        return venv_dir
    log.info("Создаю venv: %s", venv_dir)
    venv.create(venv_dir, with_pip=True)
    return venv_dir


def venv_python(venv_dir: Path) -> Path:
    """Путь к интерпретатору внутри venv (кросс-платформенно)."""
    if (venv_dir / "Scripts" / "python.exe").exists():
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def install_requirements(venv_dir: Path, skill_dir: Path) -> bool:
    """Устанавливает requirements.txt, если он есть. True если установка прошла."""
    req = skill_dir / "requirements.txt"
    if not req.is_file():
        log.info("requirements.txt не найден — пропуск установки зависимостей.")
        return True
    py = venv_python(venv_dir)
    log.info("Устанавливаю зависимости из %s", req)
    try:
        subprocess.run(
            [str(py), "-m", "pip", "install", "-r", str(req)],
            check=True,
        )
        return True
    except subprocess.CalledProcessError as exc:
        log.warning("Установка зависимостей не удалась: %s", exc)
        return False


def write_runtime_metadata(
    skill_dir: Path, venv_dir: Path | None, target: str
) -> Path:
    """Пишет runtime.json с метаданными окружения."""
    meta = {
        "skill_dir": str(skill_dir),
        "target": target,
        "python_executable": sys.executable,
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "venv": str(venv_dir) if venv_dir else None,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    out = skill_dir / "runtime.json"
    out.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Записаны runtime-метаданные: %s", out)
    return out


def augment_manifest(manifest: Path | None, status: str) -> None:
    """Дополняет существующий манифест (если он уже создан инсталлятором)."""
    if not manifest or not manifest.is_file():
        return
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Не удалось прочитать манифест %s: %s", manifest, exc)
        return
    data["python_version"] = ".".join(map(str, sys.version_info[:3]))
    data["bootstrap_status"] = status
    manifest.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info("Манифест дополнен: %s", manifest)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    check_python_version()

    skill_dir: Path = args.skill_dir.resolve()
    if not skill_dir.is_dir():
        log.error("Директория skill не найдена: %s", skill_dir)
        return 1

    venv_dir: Path | None = None
    status = "ok"
    if args.no_venv:
        log.info("Создание venv отключено (--no-venv).")
        status = "skipped"
    else:
        try:
            venv_dir = create_venv(skill_dir)
            if not install_requirements(venv_dir, skill_dir):
                status = "deps-failed"
        except Exception as exc:  # noqa: BLE001 — bootstrap не должен падать жёстко
            log.warning("Создание venv не удалось: %s", exc)
            status = "venv-failed"

    write_runtime_metadata(skill_dir, venv_dir, args.target)
    augment_manifest(args.manifest, status)

    log.info("Bootstrap завершён со статусом: %s", status)
    # Возвращаем 0 даже при мягких сбоях — инсталлятор зафиксирует статус в манифесте.
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
