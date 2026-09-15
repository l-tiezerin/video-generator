# video-generator — pipeline local de producao de video (Wealth Bounds)

## Objetivo

Sair do fluxo onde a IA renderiza o video dentro de um sandbox (limitado, caro em uso de IA)
para um pipeline local em Python. IA entra so para: roteiro, prompts de imagem, ajustes finos.
Renderizacao e 100% local via ffmpeg/Python.

## Decisoes de arquitetura ja tomadas

- **ElevenLabs**: geracao manual pela interface web, nao API (diferenca de custo entre API e
  interface pesou na decisao). Isso significa que nao ha timestamps de graca vindos da
  ElevenLabs -- o alinhamento e feito localmente.
- **Alinhamento**: forced alignment local, nao transcricao cega. O texto ja e conhecido (e o
  proprio roteiro), entao so precisamos descobrir ONDE cada palavra fica no tempo, nao
  transcrever de novo. Usamos `stable-ts` com backend `faster-whisper`.
- **Hardware**: CPU only (AMD Ryzen 5 3500U, Vega 8 integrada, sem CUDA). Por isso
  faster-whisper (CTranslate2, otimizado pra CPU) em vez de whisper padrao.
- **Contagem de imagens por video**: dinamica, nao fixa. Um JSON por video lista
  indice + arquivo + start + duration de cada imagem.

## Estado atual (pronto e validado)

`align.py` cobre os estagios 1+2 do pipeline: le `script.txt` + `narration.mp3` de uma pasta
de projeto, remove tags de voz v3 (`[excited]` etc -- nao sao faladas) via regex, roda
alinhamento forcado, e salva tres arquivos:

- `alignment.json` -- saida bruta do stable-ts (debug, verbosa, nao usar direto)
- `alignment_preview.srt` -- so pra conferencia visual rapida
- `words.json` -- formato enxuto: `{"duration": float, "words": [{"word", "start", "end"}]}`,
  e o que alimenta a proxima etapa

Testado ponta a ponta com o roteiro real do Video 6 (Bitconnect) em `projects/teste/` --
281.68s bateram 100% com o audio, timestamps coerentes. Remocao de tags testada isolada
(regex `\[[^\]]*\]`), confirmada limpa.

## Uso

```bash
uv run align.py projects/<slug-do-video>
```

Requer `script.txt` (roteiro com tags) e `narration.mp3` (audio baixado do ElevenLabs) dentro
da pasta do projeto.

## Ressalvas tecnicas conhecidas

- `stable_whisper.WhisperResult.all_words()` funcionou na pratica (versao instalada), mas nao
  foi confirmado contra doc oficial. Se quebrar em outra versao da lib, checar
  `dir(stable_whisper.WhisperResult)` pra achar o metodo certo.
- `SyntaxWarning` que aparece ao importar `stable_whisper` no Python 3.14 e inofensivo, vem do
  codigo-fonte da propria lib (regex com escape antigo). Nao afeta o resultado.
- Primeiro carregamento do modelo (import + load) leva alguns segundos -- overhead fixo do
  backend, nao e bug.

## Proximas etapas (ainda nao construidas)

1. **Manifesto de imagens + prompts** -- NAO e um script. E trabalho de conteudo: a partir do
   `words.json` + o roteiro, decidir onde cada imagem comeca/termina (por virada de ideia, nao
   por tempo fixo) e gerar os prompts de imagem + um JSON de timing. Acontece em chat, com o
   `words.json` colado/anexado.
2. **Geracao de imagem** -- manual (Meta AI / Gemini), fora do pipeline.
3. **Render final** -- script Python/ffmpeg que junta `narration.mp3` + imagens + manifesto de
   timing + legenda em video final. Ainda nao escrito.

## Fora do escopo deste repo

Definicao de tema, roteiro e o resto do processo editorial do Wealth Bounds seguem a skill
`wealth-bounds-video-creator` -- **sempre em chat separado por video**, nao nesta thread de
engenharia de pipeline. Este README documenta so a parte tecnica.