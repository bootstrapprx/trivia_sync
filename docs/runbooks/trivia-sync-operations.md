# Operação do Trivia Sync

## Sincronização QAPI

1. Configure base URL e chave em Trivia Sync Onboarding; não coloque a chave em argumentos shell, tickets ou logs.
2. Defina `qapi_max_requests_per_run` como orçamento total em créditos e `qapi_min_credit_reserve` como saldo que deve permanecer disponível. Listagens de provas custam 200 créditos por chamada; outras chamadas conhecidas custam 1. Teto zero desabilita chamadas pagas.
3. Execute dry-run para conferir filtros e custo estimado. Dry-run não grava dados e não consome chamadas pagas.
4. Habilite o agendamento somente quando orçamento, frequência e reserva estiverem revisados. Revise `Trivia Sync Run` para operador, parâmetros, páginas, chamadas, falhas e cursor.
5. Se uma execução parar, corrija a causa, confirme novamente saldo/filtros e retome pelo cursor registrado. Um replay do mesmo payload é idempotente.

## Revisão, licença e projeção

- Trate origem, licença, atribuição e permissão de redistribuição como dados distintos. Se os direitos forem desconhecidos, mantenha a decisão bloqueada.
- Revise conteúdo e metadados; registre aprovação/rejeição e motivo. Alteração em conteúdo avaliável exige nova revisão.
- Projete somente após validação de formato, aprovação editorial, licença e liberação explícita de redistribuição. Falha de projeção é retomável e não apaga a decisão editorial.
- Backfills `v0_2` e `v0_3` são aditivos. Depois de executar migrate, verifique vínculos não resolvidos e duplicados antes de corrigir manualmente.

## Provas e supersessão

Antes de publicar, confirme cargo, curso/aula LMS, tópicos, quantidade elegível e direitos das questões. Se o banco for insuficiente, complete a classificação/revisão antes de tentar novamente. Para alterar prova com submissões, monte e publique nova versão. A versão anterior, suas tentativas e conteúdo não relacionado da aula são preservados.

## Publicação pública e PDFs

- Publique um concurso apenas depois de conferir resumo e curso público associado. `/concursos` retorna somente campos editoriais allowlisted.
- Nunca adicione respostas, explicações, payloads ou dados de aluno ao DTO público.
- Materiais IA começam como rascunho. Revise proveniência e versão antes da aprovação; fontes alteradas exigem regeneração e aprovação nova.
- PDF deve permanecer privado para curso privado, não publicado ou pago. O arquivo pode ser público apenas quando o curso estiver publicado e gratuito.

## Rollback e recuperação

1. Antes de atualizar código/esquema, faça backup do site e confira o espaço disponível.
2. Se migrate ou patch falhar, não remova tabelas, questões, quizzes, arquivos ou submissões. Guarde o traceback e interrompa workers/agendamento se houver risco de chamadas repetidas.
3. Corrija o app, execute novamente `bench --site <site> migrate` e verifique o estado do patch. Os backfills do app devem ser idempotentes.
4. Se for necessário restaurar, restaure o backup validado em um site isolado primeiro e confira questões, vínculos LMS, quizzes e submissões antes de substituir o site operacional.
5. Para interromper gastos imediatamente, defina limite QAPI como zero e desligue o agendamento; isso não apaga os dados importados.

## Verificação antes de release

```bash
bench --site <site> run-tests --app trivia_sync
```

Valide ainda JSON de DocTypes/fixtures, compilação Python, sintaxe JavaScript, compatibilidade aditiva do esquema e `git diff --check`. Migração, ingestão, geração IA e publicação devem ser autorizadas e executadas separadamente em cada site.
