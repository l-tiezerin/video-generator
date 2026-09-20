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
  faster-whisper (CTranslate2, otimizado pra CPU) em vez de whisper padrao. Isso tambem
  molda o design do render (ver Estado atual): nada de processar todas as imagens de uma vez
  em memoria.
- **Contagem de imagens por video**: dinamica, nao fixa. Um JSON por video lista
  indice + arquivo + start + duration de cada imagem.
- **Legendas**: geradas direto do `words.json` (forced alignment contra o roteiro conhecido),
  sem etapa de transcricao/correcao -- nao ha erro de ASR pra corrigir, diferente do fluxo
  antigo (Vosk + script de correcao).
- **Musica de fundo**: decisao consciente de nao ter, por enquanto. Geracao via IA contraria o
  motivo do pipeline local existir (custo/dependencia externa); sintese algoritmica pura
  arrisca soar barata demais pra um componente que so se nota quando fica ruim. Se voltar a
  entrar, e via pool de faixas da YouTube Audio Library + a tecnica de loop validada no
  Video 6 (`dynaudnorm` + corte por stream copy + `-stream_loop`), nao asplit/acrossfade
  (deu bug de duracao).

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

`render.py` cobre o estagio final: junta `narration.mp3` + imagens do manifesto de timing +
legenda com efeito karaoke em um `final.mp4`. Validado ponta a ponta no Video 7.

**Importante -- por que o design e em tres passadas e nao um filter_complex unico**: a
primeira versao processava as N imagens em paralelo num unico grafo de filtros. Em hardware
sem GPU dedicada isso estourou memoria (OOM kill confirmado via `journalctl`, `ffmpeg` sozinho
consumindo ~6GB de RSS com 26 imagens). A versao atual processa uma imagem por vez (clipe
`.mp4` temporario, memoria liberada entre uma e outra), depois concatena por stream copy (sem
re-decodificar), e so na passada final entra legenda + audio, que le um unico stream de video
ja concatenado. Nunca ha mais de 1-2 streams reais decodificados ao mesmo tempo. Se voltar a
reescrever esse script, manter esse principio -- e a diferenca entre rodar e travar o sistema
inteiro no hardware atual.

Outras notas de implementacao:
- Fonte (`Montserrat ExtraBold`) e isolada num diretorio temporario proprio antes de passar
  pro filtro `ass` -- apontar o diretorio de fontes do sistema inteiro pro libass tambem
  estoura memoria. Cai pra `DejaVu Sans Bold` automaticamente se a fonte preferida nao for
  encontrada via `fc-match`.
- `-nostdin` em toda chamada de ffmpeg, pra nunca travar esperando entrada interativa.
- `print(..., flush=True)` em todo o progresso -- sem isso, a saida fica bufferizada quando
  redirecionada pra arquivo/pipe e nao aparece em tempo real.
- Imagens estaticas com fade curto (0.3s in/out), sem Ken Burns/zoompan -- mais leve e mais
  previsivel.
- Ultima imagem segura 3 segundos extras (silencio + imagem parada no final, sem corte seco);
  o audio ganha o mesmo padding via `apad` pra nao ser cortado pelo `-shortest`.

## Uso

```bash
uv run align.py projects/<slug-do-video>
uv run render.py projects/<slug-do-video>
```

`align.py` requer `script.txt` (roteiro com tags) e `narration.mp3` (audio baixado do
ElevenLabs) dentro da pasta do projeto.

`render.py` requer, na mesma pasta: `narration.mp3`, `words.json` (saida do `align.py`),
`image_manifest.json` (index/file/start/duration) e uma subpasta `images/` com os arquivos
referenciados no manifesto.

## Ressalvas tecnicas conhecidas

- `stable_whisper.WhisperResult.all_words()` funcionou na pratica (versao instalada), mas nao
  foi confirmado contra doc oficial. Se quebrar em outra versao da lib, checar
  `dir(stable_whisper.WhisperResult)` pra achar o metodo certo.
- `SyntaxWarning` que aparece ao importar `stable_whisper` no Python 3.14 e inofensivo, vem do
  codigo-fonte da propria lib (regex com escape antigo). Nao afeta o resultado.
- Primeiro carregamento do modelo (import + load) leva alguns segundos -- overhead fixo do
  backend, nao e bug.
- Preview de video do VSCode as vezes nao decodifica audio AAC corretamente -- antes de
  suspeitar de bug no render, conferir em outro player (mpv, VLC) ou via
  `ffprobe -show_streams`.

## Proximas etapas (ainda nao construidas)

1. **Manifesto de imagens + prompts** -- NAO e um script. E trabalho de conteudo: a partir do
   `words.json` + o roteiro, decidir onde cada imagem comeca/termina (por virada de ideia, nao
   por tempo fixo) e gerar os prompts de imagem + um JSON de timing. Acontece em chat, com o
   `words.json` colado/anexado. Ja exercitado uma vez (Video 7).
2. **Geracao de imagem** -- manual (Meta AI / Gemini), fora do pipeline.
3. **Musica de fundo (opcional)** -- pool de faixas + script que aplica a tecnica validada no
   Video 6 sobre o `final.mp4`, ajustando duracao. Ver "Decisoes de arquitetura" acima. Nao
   construido, nao e prioridade no momento.

## Fora do escopo deste repo

Definicao de tema, roteiro e o resto do processo editorial do Wealth Bounds seguem a skill
`wealth-bounds-video-creator` -- **sempre em chat separado por video**, nao nesta thread de
engenharia de pipeline. Este README documenta so a parte tecnica.