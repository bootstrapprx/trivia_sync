# Trivia Sync

Camada editorial e de concursos para Frappe LMS. O app importa catálogos e questões da QAPI, organiza concursos, cargos e conteúdo programático, exige revisão e decisão de redistribuição antes de projetar questões no LMS e monta provas preservando quizzes e tentativas anteriores.

## Instalação e configuração

```bash
bench get-app https://github.com/bootstrapprx/trivia_sync --branch main
bench --site <site> install-app trivia_sync
bench --site <site> migrate
```

Abra **Trivia Sync Onboarding** ou **Trivia Sync Settings** para configurar endpoint e chave da QAPI. Segredos são armazenados como Password e não devem ser incluídos em logs, issues ou comandos compartilhados. Faça backup antes de migrar um site existente. A migração adiciona campos e DocTypes; patches legados podem ser repetidos.

## Importação e orçamento

QAPI pode cobrar por chamada: listagens de provas custam 200 créditos; as demais chamadas conhecidas custam 1. `qapi_max_requests_per_run=0` bloqueia a sincronização paga; defina um limite de créditos e `qapi_min_credit_reserve` antes de executar. O modo dry-run estima o custo em créditos sem gravar registros nem chamar endpoints pagos. O agendamento de sincronização paga permanece desativado por padrão; habilite-o apenas depois de configurar limite e reserva. Execuções registram operador, parâmetros, chamadas, créditos consumidos, erros e cursor de retomada. Retome execuções incompletas pelo onboarding/API após conferir saldo e filtros.

Importações usam identidade estável e atualizam apenas campos pertencentes à fonte. Campos editoriais e notas locais são preservados. Quando conteúdo avaliável muda, a aprovação dependente desse conteúdo volta para revisão e o enriquecimento IA fica desatualizado. Correspondências ambíguas de banca, órgão, matéria, assunto ou cargo ficam sem vínculo para reconciliação manual. Nós de ementa ausentes ficam obsoletos; não são apagados.

## Direitos, revisão e projeção LMS

Registro de licença/atribuição e decisão de redistribuição são independentes da revisão editorial. Configure a licença e confirme explicitamente o direito de redistribuir antes de projetar uma questão. Um revisor aprova ou rejeita com motivo; IA nunca aprova conteúdo.

Somente questões válidas, aprovadas, liberadas para redistribuição e com licença registrada podem virar `LMS Question`. Projeções são repetíveis e versionadas por hash de conteúdo. Uma questão LMS já usada em quiz não é alterada quando a fonte muda: uma nova versão é criada. Os patches `v0_2` e `v0_3` fazem backfill aditivo de classificações e vínculos LMS legados; revise contagens de não correspondidos/ambíguos após a migração.

## Cargos, simulados e tentativas

`Concurso Cargo` liga concurso, cargo, curso LMS existente e ementa. A importação não cria cursos nem aulas. A cobertura por cargo separa banco total, questões elegíveis, tópicos, revisão, licença e fonte.

Monte o blueprint da `Prova` com blocos/tópicos e quantidade desejada. A montagem calcula primeiro o conjunto elegível e não grava quiz parcial se o banco for insuficiente. Publicar exige curso e aula existentes e permissão de escrita no curso. O quiz ativo é colocado no conteúdo da aula sem substituir blocos alheios. Alterações após tentativas criam uma versão nova; quizzes antigos e submissões permanecem preservados.

## Catálogo público e materiais assistidos

O catálogo público está em `/concursos`. Só concursos publicados com cursos LMS publicados aparecem. Respostas, explicações, payloads de fonte e dados de aluno não são expostos pelas APIs públicas.

Receitas de aula/apostila usam apenas fontes aprovadas e licenciadas. Geração assistida cria versões em rascunho; aprovação humana é necessária para publicar. Mudança nas fontes invalida a versão. PDFs são privados por padrão e só ficam públicos para curso publicado e gratuito.

## Recuperação e validação

Faça backup do site antes de `bench migrate`. Se migração ou backfill falhar, preserve logs e backup, corrija o app e repita a migração/patch idempotente; não apague questões, quizzes ou tentativas para contornar erro. Falhas de projeção podem ser retomadas sem desfazer a aprovação. Para parar chamadas pagas, zere o limite e desative o agendamento.

Execute a suíte no bench:

```bash
bench --site <site> run-tests --app trivia_sync
```

Ver detalhes de recuperação e publicação em [`docs/runbooks/trivia-sync-operations.md`](docs/runbooks/trivia-sync-operations.md).
