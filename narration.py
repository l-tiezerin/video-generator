"""
Resolve o narration.mp3 de um projeto.

Suporta dois formatos de entrada:
1. narration.mp3 unico direto na pasta do projeto (fluxo original).
2. narration-parts/NN.mp3 -- varias partes numeradas, quando o audio precisou
   ser gerado em pedacos (ex: limite de caracteres do ElevenLabs). As partes
   sao concatenadas em ordem numerica com 1s de silencio entre elas, gerando
   narration.mp3 (sobrescrito sempre que narration-parts/ existir -- ela e a
   fonte da verdade nesse caso).

Concatenacao via concat demuxer + stream copy (mesmo principio do render.py):
nao re-codifica os mp3s, so intercala com um arquivo de silencio do mesmo
sample rate/canais do primeiro part, gerado sob demanda.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SILENCE_SECONDS = 1.0


def probe_audio_params(path: Path) -> tuple[int, int]:
    """Retorna (sample_rate, channels) do primeiro stream de audio do arquivo."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate,channels",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, check=True,
    ).stdout
    stream = json.loads(out)["streams"][0]
    return int(stream["sample_rate"]), int(stream["channels"])


def make_silence(duration: float, sample_rate: int, channels: int, out_path: Path) -> None:
    ch_layout = "stereo" if channels == 2 else "mono"
    cmd = [
        "ffmpeg", "-y", "-nostdin",
        "-f", "lavfi", "-i", f"anullsrc=r={sample_rate}:cl={ch_layout}",
        "-t", f"{duration:.3f}",
        "-c:a", "libmp3lame", "-q:a", "2",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def concat_narration_parts(parts_dir: Path, out_path: Path) -> None:
    parts = sorted(
        (p for p in parts_dir.glob("*.mp3") if p.stem.isdigit()),
        key=lambda p: int(p.stem),
    )
    if not parts:
        sys.exit(f"Pasta {parts_dir} existe mas nao tem arquivos NN.mp3")

    print(f"Encontradas {len(parts)} partes de narracao em {parts_dir}, concatenando...")
    sample_rate, channels = probe_audio_params(parts[0])

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        silence_path = tmp_dir / "silence.mp3"
        make_silence(SILENCE_SECONDS, sample_rate, channels, silence_path)

        list_file = tmp_dir / "concat_list.txt"
        lines = []
        for i, part in enumerate(parts):
            lines.append(f"file '{part.resolve()}'")
            if i < len(parts) - 1:
                lines.append(f"file '{silence_path.resolve()}'")
        list_file.write_text("\n".join(lines), encoding="utf-8")

        cmd = [
            "ffmpeg", "-y", "-nostdin",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy",
            str(out_path),
        ]
        subprocess.run(cmd, check=True)

    print(f"narration.mp3 gerado a partir de {len(parts)} partes: {out_path}")


def ensure_narration(project_dir: Path) -> Path:
    """Garante que project_dir/narration.mp3 existe e esta atualizado.

    Se narration-parts/ existir, ela manda -- narration.mp3 e sempre
    regenerado a partir dela. Caso contrario, exige narration.mp3 direto.
    """
    narration_path = project_dir / "narration.mp3"
    parts_dir = project_dir / "narration-parts"

    if parts_dir.is_dir():
        concat_narration_parts(parts_dir, narration_path)
    elif not narration_path.exists():
        sys.exit(
            f"Nao encontrei {narration_path} nem a pasta {parts_dir}. "
            "Coloque o audio unico em narration.mp3 ou as partes numeradas "
            "(01.mp3, 02.mp3, ...) em narration-parts/."
        )
    return narration_path