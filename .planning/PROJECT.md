# tech-news-synth

## What This Is

Agente Python automatizado que, a cada 2 horas, coleta notícias de tecnologia de múltiplas fontes públicas (RSS e APIs), agrupa notícias relacionadas por similaridade de título, sintetiza o tema de maior cobertura via Claude Haiku em um post único em português, e publica no X na conta **@ByteRelevant**. Volume-alvo: ~12 posts/dia, operando dentro do tier Free da API do X.

## Core Value

Transformar ruído de feeds de tecnologia em **um post por ciclo que destaca o tema com mais cobertura e o ângulo único de cada fonte** — sem repetir o mesmo assunto em 48h.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Coleta periódica (cron interno, default 2h, configurável) de múltiplas fontes públicas
- [ ] Lista de fontes totalmente configurável (adicionar/editar/remover) — inicial: TechCrunch RSS, The Verge RSS, Ars Technica RSS, Hacker News API, Reddit r/technology JSON
- [ ] Deduplicação + clusterização por similaridade de títulos (TF-IDF + cosine via scikit-learn)
- [ ] Seleção do "tema vencedor" = cluster com maior cobertura na janela das últimas 6h
- [ ] Síntese via Claude Haiku (SDK oficial `anthropic`) em PT, tom **jornalístico neutro**, 3–5 artigos de entrada
- [ ] Respeitar limite de 280 chars do X considerando link encurtado (~23 chars) + 1–2 hashtags
- [ ] Publicação no X (@ByteRelevant) via tweepy API v2 (OAuth 1.0a User Context)
- [ ] Persistência em Postgres do histórico de posts com janela anti-repetição de 48h (mesmo tema)
- [ ] Mesmo quando não há cluster forte, publicar o melhor disponível (garante cadência de 12 posts/dia)
- [ ] Docker Compose com serviços separados: app + postgres, com volumes persistentes
- [ ] Secrets via `.env` + `env_file` no compose; `.env.example` versionado
- [ ] Logs estruturados (JSON) em volume Docker para consulta posterior
- [ ] Executável localmente (`docker compose up`) e em VPS Ubuntu própria

### Out of Scope

- Alertas ativos em tempo real (Discord/Telegram/email/Sentry) — logs em arquivo são suficientes na v1
- Threads no X (múltiplos tweets encadeados) — um post por ciclo
- Fontes pagas ou scraping de sites sem API/RSS — só fontes públicas estruturadas
- Tradução / publicação em outros idiomas além de PT
- Dashboard/UI web — operação headless via logs e DB
- Docker secrets / Vault — `.env` cobre o caso v1
- Deploy gerenciado (Kubernetes, ECS) — VPS Ubuntu com docker compose

## Context

- **Handle X:** @ByteRelevant (tier Free — ~500 posts/mês cabem com folga em 12/dia)
- **Domínio:** curadoria automatizada de notícias tech, distinto de agregadores manuais
- **Fontes iniciais:** TechCrunch RSS, The Verge RSS, Ars Technica RSS, Hacker News (API Firebase `topstories`), Reddit r/technology (`.json` público)
- **Usuário operador:** o próprio dono do projeto, com VPS Ubuntu. Deploy esperado: `git pull` + `docker compose up -d`

## Constraints

- **Tech stack:** Python 3.11+, scikit-learn (TF-IDF/cosine), feedparser, anthropic SDK, tweepy, psycopg/SQLAlchemy, Postgres 16
- **Infra:** Docker Compose, execução em VPS Ubuntu, cron **dentro** do container principal
- **API X:** tier Free — ~17 posts/dia permitidos; meta de 12/dia mantém margem
- **Limite de post:** 280 chars totais, incluindo URL encurtada (~23 chars) e hashtags
- **Janela anti-repetição:** 48h em Postgres por hash semântico do tema
- **Janela de cluster:** 6h de histórico ao montar clusters (configurável)
- **Idioma de saída:** PT-BR, tom jornalístico neutro
- **Secrets:** `.env` local, `.env.example` versionado, `.env` em `.gitignore`

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Clustering por TF-IDF + cosine (scikit-learn) | Simples, determinístico, sem dependência de embeddings pagos | — Pending |
| Síntese com Claude Haiku (não Sonnet/Opus) | Custo baixo, latência boa; síntese curta não exige modelo maior | — Pending |
| Cron **dentro** do container | Container único sempre up; orquestração simples em compose | — Pending |
| Janela de cluster = 6h | Equilíbrio entre frescor e massa crítica por cluster | — Pending |
| Postar mesmo sem cluster forte | Cadência é prioridade; qualidade via síntese, não via threshold | — Pending |
| Tom jornalístico neutro | Marca @ByteRelevant foco em relevância factual | — Pending |
| Post = síntese + link + hashtags | Dá crédito à fonte principal + discoverability via hashtags | — Pending |
| `.env` + `env_file` para secrets | Padrão da comunidade; suficiente para v1 em VPS própria | — Pending |
| Logs estruturados em arquivo (sem alertas ativos) | Reduz escopo v1; alertas podem vir depois se necessário | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-12 after initialization*
