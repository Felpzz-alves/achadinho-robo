# Robô do Achadinho

Serviço que roda 24h no Railway e faz o trabalho pesado do app:

1. **Edição**: quando o cliente clica em "Enviar para edição", o robô baixa o vídeo bruto,
   deixa em 9:16 (1080x1920, 30 fps), coloca o gancho no modelo escolhido (10 modelos),
   a marca d'água com o @ do cliente mudando de lugar a cada 2,5 s e entrega a **prévia sem voz**.
2. **Dublagem**: usa a voz gravada pelo cliente, um áudio da biblioteca ou gera com a ElevenLabs
   na conta do próprio cliente (voz padrão Ana Alice). O vídeo final dura narração + 0,4 s,
   repete o bruto se precisar e sai com áudio em -14 LUFS e sem metadados.
3. **Postagem**: vídeos aprovados de quem ligou a postagem automática são agendados como Reels
   no Instagram pelo Zernio, um por horário, nos horários do cliente. Depois de publicado, o app
   mostra "Postado" com o link do Reel.

## Variáveis no Railway (aba Variables)

| Nome | De onde vem |
| --- | --- |
| `SUPABASE_URL` | Lovable → Cloud → configurações do projeto |
| `SUPABASE_SERVICE_ROLE_KEY` | Lovable → Cloud → chaves (service role). Nunca compartilhe. |
| `USER_CREDENTIAL_ENCRYPTION_SECRET` | o mesmo valor salvo nos Secrets do Lovable |
| `ZERNIO_API_KEY` | painel do Zernio → API Keys |
| `POLL_SECONDS` | opcional, padrão 20 |

O Railway detecta o `Dockerfile` sozinho. Não precisa de porta nem domínio: é um worker.

## Rodar localmente

```bash
docker build -t achadinho-robo .
docker run --env-file .env achadinho-robo
```
