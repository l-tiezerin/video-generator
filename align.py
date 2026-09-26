"""
Estagio 1: alinhamento forcado do roteiro conhecido ao audio gerado no ElevenLabs.
Nao transcreve -- so descobre ONDE cada palavra do roteiro comeca/termina no audio.

Uso:
    uv run align.py projects/<slug-do-video>

Aceita tanto um narration.mp3 unico quanto varias partes numeradas em
narration-parts/NN.mp3 (concatenadas automaticamente com 1s de silencio
entre elas -- ver narration.py).
"""

import json
import re
import sys
from pathlib import Path

import stable_whisper

from narration import ensure_narration

TAG_PATTERN = re.compile(r"\[[^\]]*\]")


def strip_voice_tags(text: str) -> str:
    """Remove tags de voz v3 (ex: [excited]) que nao sao faladas."""
    clean = TAG_PATTERN.sub(" ", text)
    return re.sub(r"\s+", " ", clean).strip()


def main(project_dir: Path) -> None:
    script_path = project_dir / "script.txt"

    if not script_path.exists():
        sys.exit(f"Nao encontrei {script_path}")

    audio_path = ensure_narration(project_dir)

    raw_text = script_path.read_text(encoding="utf-8")
    clean_text = strip_voice_tags(raw_text)

    print("Carregando modelo (faster-whisper, small.en)...")
    model = stable_whisper.load_faster_whisper("small.en")

    print("Alinhando roteiro ao audio (isso nao transcreve, so localiza no tempo)...")
    result = model.align(str(audio_path), clean_text, language="en")

    alignment_path = project_dir / "alignment.json"
    result.save_as_json(str(alignment_path))

    srt_path = project_dir / "alignment_preview.srt"
    result.to_srt_vtt(str(srt_path), word_level=False)

    # Versao enxuta: so palavra + inicio + fim, para alimentar as proximas etapas
    # (prompts de imagem, manifesto de timing). Extrai do objeto em memoria,
    # nao reparseia o alignment.json (evita depender do formato bruto do stable-ts).
    words = [
        {"word": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)}
        for w in result.all_words()
    ]
    words_path = project_dir / "words.json"
    words_path.write_text(
        json.dumps(
            {"duration": words[-1]["end"], "words": words},
            indent=2,
            ensure_ascii=False,
        )
    )

    print(f"\nAlinhamento bruto (debug) salvo em: {alignment_path}")
    print(f"Preview em SRT (confira visualmente antes de seguir): {srt_path}")
    print(f"Palavras (enxuto, para as proximas etapas): {words_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Uso: uv run align.py <pasta_do_projeto>")
    main(Path(sys.argv[1]))