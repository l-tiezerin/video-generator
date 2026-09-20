"""
Estagio final: junta narration.mp3 + imagens do manifesto de timing + legenda
em um video final.

Reescrito para processar uma imagem por vez (clipe temporario) em vez de um
filter_complex unico com todas as imagens -- a versao anterior decodificava
as 26 imagens em paralelo na mesma passada e estourava memoria em hardware
sem GPU dedicada. Agora: 1) um clipe .mp4 por imagem, 2) concat por stream
copy (sem re-decodificar), 3) legenda + audio soh na passada final, que le
um unico stream de video ja concatenado.

Sem musica nesta versao (nenhuma trilha fornecida) -- ver add_music() para
o ponto de entrada caso um projeto futuro tenha musica.

Uso:
    uv run render.py projects/<slug-do-video>

Espera dentro da pasta do projeto:
    narration.mp3
    words.json          (saida do align.py)
    image_manifest.json (lista index/file/start/duration)
    images/NN.jpg        (uma por entrada do manifesto)
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FONT_NAME = "Montserrat ExtraBold"
FONT_FALLBACK = "DejaVu Sans Bold"
ASS_STYLE = (
    "Style: Default,{font},54.00,&H00FFFFFF,&H000000FF,"
    "&H00000000,&H00000000,-1,0,0,0,100.00,100.00,0.00,0.00,1,3.20,1.20,2,60,60,54,1"
)
RESOLUTION = (1920, 1080)
FPS = 30
IMAGE_FADE = 0.3  # segundos de fade in/out por imagem
END_HOLD_SECONDS = 3.0  # segura a ultima imagem + silencio no final, sem corte seco
MAX_WORDS_PER_CAPTION = 7
CAPTION_GAP_BREAK = 0.35  # pausa (s) que forca quebra de linha de legenda


def find_font() -> str:
    try:
        out = subprocess.run(
            ["fc-match", FONT_NAME], capture_output=True, text=True, check=True
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(f"fc-match indisponivel, usando fallback: {FONT_FALLBACK}")
        return FONT_FALLBACK
    if FONT_NAME.split()[0].lower() not in out.lower():
        print(f"'{FONT_NAME}' nao encontrada, usando fallback: {FONT_FALLBACK}")
        return FONT_FALLBACK
    return FONT_NAME


def prepare_font_dir(font_name: str, tmp_dir: Path) -> Path:
    """Copia so o arquivo da fonte resolvida para um diretorio isolado --
    passar o diretorio de fontes do sistema inteiro pro libass estoura memoria."""
    font_dir = tmp_dir / "fonts"
    font_dir.mkdir()
    out = subprocess.run(
        ["fc-match", "-f", "%{file}", font_name], capture_output=True, text=True, check=True
    ).stdout
    src = Path(out.strip())
    shutil.copy(src, font_dir / src.name)
    return font_dir


def build_captions(words_path: Path, font_name: str, ass_path: Path) -> None:
    data = json.loads(words_path.read_text(encoding="utf-8"))
    words = data["words"]

    lines = []
    current = []
    for i, w in enumerate(words):
        current.append(w)
        is_last = i == len(words) - 1
        gap = (words[i + 1]["start"] - w["end"]) if not is_last else 0
        if is_last or len(current) >= MAX_WORDS_PER_CAPTION or gap >= CAPTION_GAP_BREAK:
            lines.append(current)
            current = []

    def ts(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        return f"{h:d}:{m:02d}:{s:05.2f}"

    dialogue = []
    for line in lines:
        start, end = line[0]["start"], line[-1]["end"]
        parts = []
        for w in line:
            dur_cs = max(1, round((w["end"] - w["start"]) * 100))
            parts.append(f"{{\\k{dur_cs}}}{w['word']}")
        text = " ".join(parts)
        dialogue.append(
            f"Dialogue: 0,{ts(start)},{ts(end)},Default,,0,0,0,,{text}"
        )

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {RESOLUTION[0]}
PlayResY: {RESOLUTION[1]}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{ASS_STYLE.format(font=font_name)}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ass_path.write_text(header + "\n".join(dialogue) + "\n", encoding="utf-8")


def render_image_clip(img_path: Path, duration: float, out_path: Path) -> None:
    """Renderiza UMA imagem como clipe de video. So essa imagem fica
    decodificada na memoria durante essa chamada."""
    w, h = RESOLUTION
    fade_out_start = max(0, duration - IMAGE_FADE)
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},"
        f"fade=t=in:st=0:d={IMAGE_FADE},"
        f"fade=t=out:st={fade_out_start:.3f}:d={IMAGE_FADE},"
        f"setsar=1,fps={FPS}"
    )
    cmd = [
        "ffmpeg", "-y", "-nostdin",
        "-loop", "1", "-t", f"{duration:.3f}", "-i", str(img_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def concat_clips(clip_paths: list[Path], list_file: Path, out_path: Path) -> None:
    """Concatena os clipes por stream copy (rapido, sem re-decodificar)."""
    list_file.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in clip_paths), encoding="utf-8"
    )
    cmd = [
        "ffmpeg", "-y", "-nostdin",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def finalize(concat_path: Path, narration_path: Path, ass_path: Path, font_dir: Path, out_path: Path) -> None:
    """Passada final: soh esse video ja concatenado + audio + legenda.
    Um unico stream de video real sendo decodificado, nao 26."""
    cmd = [
        "ffmpeg", "-y", "-nostdin",
        "-i", str(concat_path),
        "-i", str(narration_path),
        "-vf", f"ass={ass_path}:fontsdir={font_dir}",
        "-af", f"apad=pad_dur={END_HOLD_SECONDS}",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def main(project_dir: Path) -> None:
    words_path = project_dir / "words.json"
    manifest_path = project_dir / "image_manifest.json"
    narration_path = project_dir / "narration.mp3"
    images_dir = project_dir / "images"

    for p in (words_path, manifest_path, narration_path):
        if not p.exists():
            sys.exit(f"Nao encontrei {p}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    font_name = find_font()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        font_dir = prepare_font_dir(font_name, tmp_dir)
        ass_path = tmp_dir / "captions.ass"
        build_captions(words_path, font_name, ass_path)

        clip_paths = []
        for i, item in enumerate(manifest):
            img_path = images_dir / item["file"]
            if not img_path.exists():
                sys.exit(f"Imagem faltando: {img_path}")
            clip_path = tmp_dir / f"clip_{item['index']:03d}.mp4"
            duration = item["duration"]
            if i == len(manifest) - 1:
                duration += END_HOLD_SECONDS
            print(f"[{item['index']}/{len(manifest)}] renderizando {item['file']} ...", flush=True)
            render_image_clip(img_path, duration, clip_path)
            clip_paths.append(clip_path)

        print("Concatenando clipes ...", flush=True)
        concat_path = tmp_dir / "concat.mp4"
        concat_clips(clip_paths, tmp_dir / "concat_list.txt", concat_path)

        print("Passada final (legenda + audio) ...", flush=True)
        out_path = project_dir / "final.mp4"
        finalize(concat_path, narration_path, ass_path, font_dir, out_path)

    print(f"\nVideo final: {out_path}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Uso: uv run render.py <pasta_do_projeto>")
    main(Path(sys.argv[1]))
