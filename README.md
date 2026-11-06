# Trivia Sync

Aplicativo Frappe para sincronizar a QAPI com o Frappe LMS. O app usa REST por padrão (`https://qapi.otunac.com/api`) e suporta fallback MCP (`https://qapi.otunac.com/mcp`) quando habilitado nas configurações.

## Cobertura

A sincronização completa cobre questões, textos de apoio vinculados por código, bancas, órgãos, cargos, matérias, assuntos, provas, concursos, status de concursos, disciplinas, conteúdos planos, árvore de conteúdos e flashcards. Listagens são paginadas com no máximo 10 itens por chamada. Provas ficam desabilitadas por padrão porque a QAPI cobra 200 cotas por chamada.

Cada recurso é persistido em um DocType próprio com `qapi_id`/código, payload bruto, hash idempotente e timestamp. Questões com texto de apoio chamam `GET /textos/:codigo` durante a ingestão e gravam o Link `Trivia Question.texto_apoio`; o campo equivalente `LMS Question.trivia_texto_apoio` é incluído por fixture.

## Instalação

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/bootstrapprx/trivia_sync --branch main
bench --site $SITE install-app trivia_sync
bench --site $SITE migrate
```

Em **Trivia Sync Settings**, configure o Q-Api-Key como campo Password. A chave nunca é enviada ao frontend nem armazenada no código. Ative `sync_catalogs`, `sync_support_texts` e, conscientemente, `sync_exams` se quiser consumir as chamadas caras de provas.

## Workers

O scheduler enfileira `trivia_sync.integrations.sync.sync_qapi_full` na fila `long`. Também é possível usar `trivia_sync.api.enqueue_qapi_sync` ou `trivia_sync.api.run_qapi_sync_now` como System Manager.

## Adaptador IA

O módulo `trivia_sync.integrations.ai_enricher` usa qualquer endpoint compatível com `POST /v1/chat/completions` e saída `json_schema`. Ele classifica questões de 1 a 5 estrelas, produz um rótulo em português, justifica a classificação, sugere um objetivo de aprendizagem e extrai tópicos. Os campos ficam no DocType `Trivia Question` e são somente leitura para usuários.

O padrão recomendado é o modelo `gpt-6-luna`, escolhido por ter suporte a JSON Schema e menor custo no catálogo disponível. O provedor, modelo, timeout e lote são configuráveis em `Trivia Sync Settings`; a chave é armazenada como Password. O recurso é opt-in (`ai_enabled=1`) e usa hash do conteúdo para não cobrar novamente por uma questão que não mudou.

Depois de configurar a chave, o administrador pode usar o botão **Enriquecer questões com IA** ou chamar `trivia_sync.api.enqueue_ai_enrichment`. O lote padrão é de 10 questões por execução e falhas individuais são registradas sem interromper o restante do lote.
