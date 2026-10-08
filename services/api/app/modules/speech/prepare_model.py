"""Explicit one-time model download; never called by request handlers."""

import argparse
from pathlib import Path

MODEL_REPOSITORY = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
MODEL_REVISION = "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"


def main() -> None:
    parser = argparse.ArgumentParser(description="Подготовить локальную Whisper large-v3-turbo")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from huggingface_hub import snapshot_download
    args.output.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=MODEL_REPOSITORY, revision=MODEL_REVISION, local_dir=str(args.output),
        allow_patterns=["*.json", "model.bin", "tokenizer.json", "vocabulary.*", "preprocessor_config.json"])
    print("Модель подготовлена. Укажите SPEECH_MODEL_PATH в конфигурации ASR.")


if __name__ == "__main__":
    main()
