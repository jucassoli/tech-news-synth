# tech-news-synth

## What This Is

Agente Python automatizado que, a cada 2 horas, coleta notícias de tecnologia de múltiplas fontes públicas (RSS e APIs), agrupa notícias relacionadas por similaridade de título, sintetiza o tema de maior cobertura via Claude Haiku 4.5 em um post único em português, e publica no X na conta **@ByteRelevant**. Volume-alvo: ~12 posts/dia, operando em **tier pay-per-use** da API do X (Free tier antigo foi descontinuado em 2026-02-06 para contas novas).

## Core Value

Transformar ruído de feeds de tecnologia em **um post por ciclo que destaca o tema com mais cobertura e o ângulo único de cada fonte** — sem repetir o mesmo assunto em 48h.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Coleta periódica (APScheduler em-processo, default 2h, configurável) de múltiplas fontes públicas
- [ ] Lista de fontes totalmente configurável (adicionar/editar/remover) — inicial: TechCrunch RSS, The Verge RSS, Ars Technica RSS, Hacker News API, Reddit r/technology JSON
- [ ] Deduplicação + clusterização por similaridade de títulos (TF-IDF + cosine via scikit-learn)
- [ ] Seleção do "tema vencedor" = cluster com maior cobertura na janela das últimas 6h
- [ ] Síntese via Claude Haiku 4.5 (modelo `claude-haiku-4-5`, SDK oficial `anthropic`) em PT, tom **jornalístico neutro**, 3–5 artigos de entrada
- [ ] Respeitar limite de 280 chars do X considerando link encurtado (~23 chars) + 1–2 hashtags (weighted char count, não `len()`)
- [ ] Publicação no X (@ByteRelevant) via tweepy API v2 (OAuth 1.0a User Context)
- [ ] Persistência em Postgres do histórico de posts com janela anti-repetição de 48h (mesmo tema)
- [ ] Mesmo quando não há cluster forte, publicar o melhor disponível (garante cadência de 12 posts/dia)
- [ ] Docker Compose com serviços separados: app + postgres, com volumes persistentes
- [ ] Secrets via `.env` + `env_file` no compose; `.env.example` versionado
- [ ] Logs estruturados (JSON via structlog) em volume Docker para consulta posterior
- [ ] Gate de validação inicial: verificar permissão de posting da conta de dev X e custo por tweet no tier atual antes de implementar pipeline completo
- [ ] Executável localmente (`docker compose up`) e em VPS Ubuntu própria

### Out of Scope

- Alertas ativos em tempo real (Discord/Telegram/email/Sentry) — logs em arquivo são suficientes na v1
- Threads no X (múltiplos tweets encadeados) — um post por ciclo
- Fontes pagas ou scraping de sites sem API/RSS — só fontes públicas estruturadas
- Tradução / publicação em outros idiomas além de PT
- Dashboard/UI web — operação headless via logs e DB
- Docker secrets / Vault — `.env` cobre o caso v1
- Deploy gerenciado (Kubernetes, ECS) — VPS Ubuntu com docker compose
- System cron dentro do container — substituído por APScheduler (env stripping e logs invisíveis)

## Context

- **Handle X:** @ByteRelevant — conta de dev **nova** (pós-2026-02-06), opera em **pay-per-use**. Premissa de custo: ~$20–50/mês para 12 posts/dia (a confirmar no gate inicial)
- **Modelo LLM:** Claude Haiku 4.5 (`claude-haiku-4-5`) — Haiku 3 aposenta em 2026-04-19, Haiku 4.5 é o substituto direto
- **Domínio:** curadoria automatizada de notícias tech, distinto de agregadores manuais
- **Fontes iniciais:** TechCrunch RSS, The Verge RSS, Ars Technica RSS, Hacker News (API Firebase `topstories`), Reddit r/technology (`.json` público)
- **Usuário operador:** o próprio dono do projeto, com VPS Ubuntu. Deploy esperado: `git pull` + `docker compose up -d`

## Constraints

- **Tech stack:** Python 3.12, scikit-learn (TF-IDF/cosine), feedparser, `anthropic` SDK, tweepy v2, psycopg 3 + SQLAlchemy 2.0 + alembic, Postgres 16, APScheduler, structlog, pydantic-settings, httpx, ruff, pytest
- **Infra:** Docker Compose (base `python:3.12-slim-bookworm`), execução em VPS Ubuntu, APScheduler em-processo (PID 1) no container app
- **API X:** tier pay-per-use (posting pago) — meta 12/dia; gate de validação inicial confirma cap e custo real
- **Limite de post:** 280 chars totais (weighted char count), incluindo URL encurtada t.co (~23 chars) e hashtags
- **Janela anti-repetição:** 48h em Postgres — **por similaridade cosseno de centroide de cluster**, não hash de string (paraphrase-safe)
- **Janela de cluster:** 6h de histórico ao montar clusters (configurável)
- **Idioma de saída:** PT-BR, tom jornalístico neutro; grounding obrigatório (não inventar stats/citações)
- **Timezone:** UTC everywhere (`TIMESTAMPTZ` em Postgres, `datetime.now(timezone.utc)` em Python)
- **Secrets:** `.env` local, `.env.example` versionado, `.env` em `.gitignore`; pre-commit hook para detectar vazamento

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Clustering por TF-IDF + cosine (scikit-learn) | Simples, determinístico, sem dependência de embeddings pagos; migrar pra embeddings só se qualidade falhar empiricamente | — Pending |
| Síntese com Claude Haiku 4.5 (`claude-haiku-4-5`) | Custo baixo, latência boa; síntese curta não exige modelo maior; Haiku 3 é EOL em 2026-04-19 | — Pending |
| **APScheduler em-processo** (não cron-in-container, não supercronic) | 3 pesquisas independentes convergiram: env `.env` chega nativo, logs vão pro structlog, 1 processo = 1 container, testável | — Pending (revised) |
| Janela de cluster = 6h | Equilíbrio entre frescor e massa crítica por cluster | — Pending |
| Postar mesmo sem cluster forte | Cadência é prioridade; qualidade via síntese, não via threshold | — Pending |
| Tom jornalístico neutro | Marca @ByteRelevant foco em relevância factual | — Pending |
| Post = síntese + link + hashtags (allowlist) | Dá crédito à fonte principal + discoverability; allowlist previne drift pra hashtags spammy | — Pending |
| `.env` + `env_file` para secrets | Padrão da comunidade; suficiente para v1 em VPS própria | — Pending |
| Logs estruturados em arquivo (sem alertas ativos) | Reduz escopo v1; alertas podem vir depois se necessário | — Pending |
| **X pay-per-use aceito** (conta nova, pós-fev/2026) | Tier Free antigo indisponível; custo ~$20–50/mês é aceitável para o projeto | — Pending (confirm in gate) |
| **Anti-repetição por similaridade de centroide** (não hash de string) | Hash de título falha em paráfrase; cosseno ≥ 0.5 vs centroides de posts nas últimas 48h | — Pending |
| Base image `python:3.12-slim-bookworm` (não Alpine) | Alpine quebra wheels de scikit-learn/lxml (musl vs glibc) | — Pending |
| psycopg 3 + SQLAlchemy 2.0 typed + alembic | Stack moderno, ~4x mais eficiente em memória que psycopg2 | — Pending |

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
*Last updated: 2026-04-12 after research phase revisions (X pay-per-use, Haiku 4.5, APScheduler)*
