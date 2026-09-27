# Music Library Diff

Ferramenta local para Windows que compara duas bibliotecas de música guardadas em dois PCs da mesma rede, sem copiar, mover, renomear ou apagar nenhum arquivo.

## Requisitos

- Windows 10/11
- Python 3.10 ou superior
- (Opcional — apenas para os testes de formatos comprimidos) [ffmpeg](https://ffmpeg.org/) no PATH

## Instalação

```powershell
git clone https://github.com/elfo170/music-library-diff.git
cd music-library-diff
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Executar

```powershell
python run.py
```

Abra `http://127.0.0.1:5000` no navegador. Informe:

- **Biblioteca A**: uma pasta local, ex. `D:\Music`
- **Biblioteca B**: uma pasta local ou um compartilhamento de rede já acessível pelo Windows, ex. `\\PC-DESKTOP\Music`

Clique em **Analisar** e acompanhe o progresso. Ao final, os resultados aparecem em 5 categorias: Em ambas, Apenas A, Apenas B, Duplicatas e Arquivos diferentes.

## Como funciona a comparação

1. As duas pastas são escaneadas recursivamente, ignorando qualquer arquivo que não seja de áudio suportado (MP3, FLAC, WAV, AIFF, M4A/AAC, OGG/Opus).
2. Para cada arquivo é calculado um hash (BLAKE2b) e extraída a metadata disponível (artista, título, álbum, duração, bitrate, sample rate, bit depth).
3. A comparação segue uma abordagem híbrida, em ordem de prioridade:
   - **Em ambas** (`IDENTICAL`): hash idêntico dos dois lados → mesmo arquivo, byte a byte.
   - **Arquivos diferentes** (`SAME_SONG_DIFFERENT_FILE`): artista+título normalizados batem e a duração é compatível (tolerância de 2s), mas o hash difere → mesma música, arquivo/formato diferente.
   - **Duplicatas** (`POSSIBLE_DUPLICATE`): artista+título normalizados batem, mas a duração diverge além da tolerância → correspondência incerta, que merece revisão manual.
   - **Apenas A / Apenas B**: nenhuma correspondência encontrada do outro lado.
4. Versões/remixes (ex. `(Extended Mix)`, `(Radio Edit)`) são tratados como músicas diferentes propositalmente — nenhum agrupamento automático é feito no MVP, para reduzir falsos positivos.
5. Nenhum arquivo é alterado, movido, copiado ou apagado em nenhuma etapa (há um teste automatizado que verifica isso).

## Análise incremental

O hash e a metadata de cada arquivo escaneado ficam guardados em cache local (SQLite, em `data/music_library_diff.db`, criado automaticamente). Em análises futuras, se um arquivo não mudou (mesmo tamanho e mesma data de modificação), o hash e a metadata são reaproveitados do cache em vez de recalculados — o que torna novas análises bem mais rápidas em bibliotecas grandes.

## Rodar os testes

```powershell
pip install -r requirements-dev.txt
pytest
```

Os testes de `.wav` (incluindo os testes de integração ponta a ponta) sempre rodam, pois dependem apenas da biblioteca padrão do Python. Os testes parametrizados para MP3/FLAC/AIFF/M4A/OGG/Opus usam `ffmpeg` para gerar arquivos de teste reais; se `ffmpeg` não estiver disponível, esses casos são pulados automaticamente (`SKIPPED`), sem quebrar a suíte.

## Decisões e suposições de escopo

- **Duplicatas vs. Arquivos diferentes**: o PRD original cita "Diferenças" como uma categoria à parte de "Mesma música, arquivos diferentes", mas o mockup da tela de resultados (seção 14 do PRD) mostra apenas 5 categorias: Todas, Ambas, Apenas A, Apenas B, Duplicatas, Arquivos diferentes. A implementação segue esse mockup como fonte da verdade — "Diferenças" e "Arquivos diferentes" foram tratados como a mesma categoria (`SAME_SONG_DIFFERENT_FILE`).
- **Hash**: BLAKE2b (biblioteca padrão do Python, sem dependência externa), por ser rápido e confiável o suficiente para detectar arquivos idênticos.
- **UNC / SMB**: o código usa `pathlib`/`os` de forma genérica — o próprio Windows resolve caminhos `\\PC\Music` nativamente quando a aplicação roda nele. Este projeto foi desenvolvido e testado num ambiente Linux (sem acesso a um compartilhamento SMB real); vale validar o acesso de rede após clonar o repositório num PC Windows real.
- **Caminhos longos** (>260 caracteres): não tratados explicitamente neste MVP.
- **WAV/AIFF**: esses dois formatos guardam tags como ID3 "cru" no mutagen (diferente do wrapper simplificado usado para os demais formatos) — o extrator de metadata trata esse caso especificamente.

## Arquitetura

```
backend/
├── scanner.py             # SCAN — percorre as pastas, somente leitura
├── metadata_extractor.py  # extração de metadata (mutagen)
├── hasher.py               # hash dos arquivos (BLAKE2b)
├── normalizer.py           # normalização de artista/título para comparação
├── comparator.py           # COMPARE — classifica cada par em uma categoria
├── db.py                   # persistência SQLite + cache incremental
├── scan_service.py         # orquestra SCAN -> COMPARE em background, com progresso
└── app.py                  # DISPLAY — API HTTP (Flask) + serve o frontend
frontend/                   # UI web local (HTML/CSS/JS puro, sem build step)
tests/                      # testes automatizados (pytest)
```

O domínio separa claramente SCAN / COMPARE / DISPLAY de uma futura camada **SYNC** (não implementada neste MVP). Cada análise fica registrada no banco (`scans` / `scan_matches`) de forma que uma futura tela de sincronização (`PC A → PC B`, `PC B → PC A`, bidirecional) possa ser construída sobre os resultados já classificados, sem reescrever o núcleo de comparação.

## Segurança

- O MVP é somente leitura: nenhum arquivo de música é alterado, movido, renomeado, copiado ou apagado.
- Nenhuma credencial de rede é solicitada ou armazenada; a aplicação usa o acesso SMB que o Windows já tiver configurado.
- Nenhum arquivo de música ou metadata é enviado para servidores externos; toda a análise roda localmente.
