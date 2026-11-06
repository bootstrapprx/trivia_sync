# Trivia Sync: camada de concursos para Frappe LMS

## Intenção

Transformar `trivia_sync` de sincronizador QAPI em uma camada editorial e operacional de concursos públicos integrada ao Frappe LMS. A experiência deve cobrir o ciclo de vida da questão e do concurso até a realização de provas e simulados por alunos, usando os modelos nativos do LMS para cursos, aulas, quizzes, tentativas e resultados.

O módulo Aprova em `/mnt/toshiba/kodvs/backend/addons/aprova` é referência de domínio e fluxo: concurso, cargos, ementa hierárquica, revisão de questões, provas com blocos, simulados montados por critérios, conteúdo didático e publicação. O desenho reutiliza esses conceitos e substitui dependências específicas de Odoo por Frappe e LMS.

## Resultado esperado

Um operador consegue importar e organizar um concurso, associar seus cargos a cursos existentes, estruturar a ementa, revisar questões, montar uma prova oficial ou simulado e disponibilizá-lo como Quiz em uma aula escolhida. Um candidato consegue descobrir o concurso no catálogo público, acessar o curso publicado e realizar as avaliações. A operação consegue acompanhar sincronizações, revisão editorial, cobertura de ementa e resultados usando o Trivia Sync para o domínio de concursos e o LMS para entrega e aprendizagem.

## Vocabulário

- **Concurso**: certame com órgão, banca, ano, edital, estado e um ou mais cargos.
- **Cargo do concurso**: posição específica dentro de um concurso, com requisitos, vagas, curso LMS associado e ementa aplicável.
- **Ementa**: árvore versionada de disciplinas e tópicos do edital para um cargo. O texto original e seu caminho na fonte são preservados.
- **Questão editorial**: registro mestre do Trivia Sync, com origem, conteúdo, classificação, revisão e histórico. Não é a questão usada diretamente pelo aluno.
- **Questão LMS**: projeção nativa de uma questão editorial aprovada em `LMS Question`.
- **Prova**: avaliação oficial ou simulado composto por blocos e questões, com regras de pontuação e publicação.
- **Simulado**: prova não oficial composta manualmente ou por um blueprint que seleciona questões aprovadas conforme cargo, tópicos, banca, dificuldade e quantidade.

## Decisões confirmadas

- Questões recebidas de fontes externas entram como pendentes de revisão. Aprovar publica ou atualiza a projeção em `LMS Question`; rejeitar mantém o registro editorial e o motivo.
- Questões sem aprovação não entram nos simulados gerados pelo Trivia Sync.
- Cada cargo do concurso aponta para um `LMS Course` já existente. O app não cria cursos automaticamente durante importação.
- Uma prova publicada no LMS vira `LMS Quiz` colocado na aula escolhida dentro do curso daquele cargo, pela representação nativa suportada por `Course Lesson`, sem substituir conteúdo existente.
- `LMS Quiz Submission` e demais registros de tentativa, nota e progresso continuam sob responsabilidade do LMS.
- O texto de apoio, alternativas, gabarito, explicações e metadados aprovados acompanham a questão LMS; classificações devem ser relacionais e filtráveis, não apenas texto livre.

## Escopo funcional

### 1. Catálogo e relações de concurso

Evoluir os DocTypes já existentes (Banca, Órgão, Cargo, Matéria, Assunto, Concurso, Prova, Disciplina e Conteúdo Programático) para relações canônicas com identidade externa estável, estado ativo/obsoleto, payload de origem e data/hash de sincronização. Evitar uma segunda cópia de cada catálogo.

Adicionar a associação cargo-concurso, pois um cargo não é globalmente o mesmo objeto em todos os certames. Ela contém dados específicos do edital, vagas/requisitos, curso LMS e configuração de ementa. O cargo de catálogo da QAPI pode ser ligado quando a fonte oferecer identidade correspondente; a associação também pode ser criada manualmente.

Questões editoriais devem ligar, quando resolvidas, a banca, órgão, cargo do concurso, concurso, prova, matéria, assunto e tópicos da ementa. Campos textuais atuais permanecem como snapshot legado/fonte durante a migração; os novos vínculos passam a guiar filtros, relatório e montagem de provas.

### 2. Ementa versionada

Reutilizar `Conteúdo Programático` como registro de tópico, acrescentando relação ao cargo do concurso, pai/filhos, caminho estável na fonte, texto original, hash, versão, estado ativo/obsoleto e ordem. Uma atualização da árvore deve reconciliar por caminho/identidade estável, incrementar a versão quando o texto-fonte mudar e marcar tópicos ausentes como obsoletos; nunca apagar tópicos com questões ou enriquecimentos ligados.

Questões podem ser associadas a mais de um tópico se a avaliação exigir. A cobertura de ementa deve ser consultável por cargo, disciplina, tópico e estado de revisão, servindo de filtro para provas e relatórios.

### 3. Banco editorial e fluxo de revisão

Adicionar a `Trivia Question` estados pendente, aprovada e rejeitada, responsável/data da decisão, observação editorial, tipo de questão, dificuldade de fonte e ligações relacionais. As permissões distinguem administrador de integração, editor e revisor.

Uma sincronização idempotente atualiza os campos de origem sem apagar anotações locais. Se o hash de conteúdo avaliável mudar (enunciado, alternativas, gabarito, explicação ou texto de apoio), a questão volta a pendente e seu enriquecimento fica marcado como desatualizado. Mudanças de metadados não devem apagar a decisão editorial. O versionamento nativo do Frappe e o payload bruto preservam auditoria; rejeições não são excluídas.

O fluxo aprovar/rejeitar é explícito. Aprovar valida enunciado, tipo, alternativas e resposta conforme o tipo; cria/atualiza `LMS Question`, grava o vínculo de origem e a hash da projeção. Rejeitar exige motivo e não publica. Erros de projeção deixam a questão aprovada no editorial com erro visível/reexecutável, sem perder dados.

Questões antigas já copiadas para LMS não serão apagadas. No backfill, as que têm `trivia_qcode` são ligadas ao registro editorial correspondente e marcadas pendentes para revisão; questões sem origem Trivia Sync permanecem intocadas. A montagem de simulados só consulta estado aprovado no registro editorial.

### 4. Tipos e conteúdo didático

Preservar o tipo de questão da fonte e mapear formatos compatíveis com LMS: escolha única, certo/errado, múltiplas corretas (quando ambas as plataformas suportarem) e texto de apoio. Questões incompatíveis ficam pendentes com erro de validação legível, em vez de serem convertidas silenciosamente.

O enriquecimento IA atual passa a ser um conjunto de dados auxiliares com estado/hash baseado no conteúdo. A próxima etapa editorial comporta explicações em níveis, objetivo de aprendizagem e tópicos, inspirados nos níveis Mais/180/360 do Aprova. IA não aprova questões nem publica material automaticamente. Cada execução registra modelo, horário, hash de entrada e erro por item; os resultados só são projetados no LMS após aprovação.

### 5. Provas e simulados

Evoluir `Prova` para diferenciar prova oficial importada, prova montada e simulado; incluir cargo(s), curso/aula alvo, estado de rascunho/pronta/publicada/arquivada, duração, data, fonte/PDF e vínculo ao LMS Quiz.

Criar linhas/blocos de prova com ordem, peso/pontuação, nota mínima, tópicos de ementa e critérios opcionais. Uma questão só pode estar uma vez na mesma prova, precisa estar aprovada e deve pertencer a um cargo/tópico compatível. O blueprint valida previamente se há quantidade suficiente de questões elegíveis; se não houver, retorna quais critérios faltaram e não cria prova parcialmente montada.

Na publicação, criar/atualizar um `LMS Quiz` e `LMS Quiz Question` para cada item, preservando ordem e pontuação; então colocar o quiz na aula por meio do bloco de avaliação nativo em `Course Lesson.content` ou mecanismo suportado pela versão instalada. A gravação deve mesclar o bloco sem sobrescrever conteúdo, quizzes ou avaliações já colocados na aula. O app não altera respostas/tentativas já submetidas. Se uma prova com tentativas precisar de nova composição, a versão anterior fica marcada como superada, é retirada da colocação ativa na aula e permanece intacta com suas submissões para consulta; a nova versão recebe um Quiz separado. O LMS não deve permitir novas tentativas na versão superada por acesso direto; se não houver suporte nativo, implementar a menor extensão compatível no Trivia Sync.

### 6. Conteúdo didático e páginas públicas

O catálogo público apresenta concursos publicados, edital, status, datas, cargos, cursos associados, ementas resumidas e provas/simulados liberados. Conteúdo não publicado ou pertencente a curso/aula privado não pode ser exposto. Respostas, gabaritos, explicações, payloads de origem, dados pessoais e conteúdo restrito de instrutor nunca entram na resposta pública. Rotas montam respostas por allowlist, falham fechadas sem publicação/configuração válida e verificam o estado/permissão do curso vinculado. Usar página/website Frappe e navegação nativa do LMS, sem dependência do Website do Odoo.

Planejamento de aulas, metodologias e receitas de apostila inspirados em `Aprova Aula`, `Aprova Metodologia` e `Aprova Apostila Recipe` fazem parte do escopo completo. Receitas podem definir atividades e durações e produzir níveis de explicação Mais/180/360 vinculados aos tópicos, questões e aulas existentes. Geração por IA é assistida, versionada e sempre cria rascunho para revisão humana. Materiais aprovados podem ser colocados na aula LMS associada e exportados como PDF. Acesso público/premium deve respeitar matrícula e permissões do LMS; conteúdo restrito de instrutor nunca é incluído em respostas públicas.

### 7. Ingestão e operação

QAPI, GitHub (QuestõesDeConcursoBot) e datasets Hugging Face são as fontes do escopo completo, cada uma implementando o mesmo contrato de adaptador e chegando à mesma fila editorial. Cada item guarda ID/URL/licença/atribuição da fonte e uma decisão explícita de redistribuição. A aplicação não interpreta termos jurídicos automaticamente: direitos pendentes ou negados impedem publicação no LMS e no catálogo. O estado aprovado registra quem confirmou o direito, a referência dos termos e a atribuição obrigatória. A lista de licenças aceitas é política administrativa configurável, sem allowlist codificada no app. A ingestão deve ter dry-run, filtros por concurso/cargo/banca/matéria/ano, limites explícitos de páginas, resumo de criados/atualizados/duplicados/pendências/erros e retomada segura.

Chamadas QAPI são pagas e ficam desligadas no scheduler por padrão. O operador configura um teto local de chamadas/créditos por execução e uma reserva mínima; sem teto positivo a sincronização paga é recusada. Se a API expuser saldo remoto, ele funciona como uma segunda trava, nunca substituindo o teto local. Fontes gratuitas podem ser agendadas separadamente. Cada adapter precisa declarar custo, disponibilidade, autenticação e capacidade de dry-run.

Cada execução registra origem, escopo/parâmetros, operador, início/fim, página/offset, resultados e erros. Falha em um registro não descarta os demais; falha global deixa a execução retomável e identificável. Os segredos permanecem nos campos Password do Frappe.

### 8. Navegação e indicadores

O workspace do Trivia Sync organiza Concurso, Cargo, Ementa, Questões pendentes, Banco aprovado, Provas/Simulados e Execuções. O dashboard destaca revisões pendentes, falhas de publicação no LMS, cobertura da ementa, banco elegível por cargo e sincronização. Os relatórios de tentativas/resultados consomem os dados do LMS, sem criar cópias locais de submissões.

## Fora do escopo desta camada

- Portar APIs, models ou dependências de Odoo, Knowledge, `project.task`, `res.company` ou a implementação do website Odoo.
- Criar automaticamente `LMS Course` ou `Course Lesson` ao importar catálogos.
- Duplicar submissões, resultados, progresso ou controle de matrícula mantidos pelo LMS.
- Aprovar ou publicar conteúdo por decisão automática da IA.
- Ingerir fontes além de QAPI, GitHub (QuestõesDeConcursoBot) e Hugging Face nesta iniciativa.
- Converter automaticamente questões legadas sem gabarito/alternativas válidos.

## Migração e compatibilidade

- Preservar todos os DocTypes e campos existentes; ampliar os modelos com campos relacionais em vez de renomear/remover campos usados pela instalação.
- Fazer backfill por `qapi_id`/`qcode` e outros IDs estáveis. Correspondências ambíguas permanecem sem vínculo e aparecem em relatório de reconciliação para decisão humana.
- Não excluir nem despublicar `LMS Question`, cursos, aulas, quizzes ou submissões existentes. A revisão pendente dos registros legados afeta a elegibilidade no novo gerador, não apaga dados do LMS.
- Alterações de fixtures e permissões precisam funcionar em instalação nova e migração de site existente.
- Toda escrita no LMS ocorre por APIs/modelos Frappe em `trivia_sync`; nenhuma alteração direta no app Frappe ou LMS.

## Fases de entrega propostas

1. **Fundação editorial e fontes**: relações de catálogo, cargos por concurso, ementa versionada, estados de revisão, permissões, reconciliação legada e adapters QAPI/GitHub/Hugging Face.
2. **Provas e simulados**: blocos/linhas, blueprint com filtros, validação de disponibilidade, publicação/posicionamento no LMS Quiz e proteção após tentativas.
3. **Operação e distribuição pública**: workspace, dashboard/relatórios, catálogo público seguro de concursos e cursos.
4. **Conteúdo didático**: metodologias, explicações em níveis, plano de aula e receitas de apostila, geração assistida, revisão, publicação em aulas LMS e exportação PDF.

## Critérios de aceite

- Uma importação repetida não duplica concurso, cargo, tópico, questão ou prova.
- Alterar conteúdo avaliável de uma questão importada mantém histórico, invalida a aprovação anterior e não apaga anotação local.
- Somente questão aprovada e válida é criada/atualizada no banco LMS por esta integração.
- Um cargo é associado a curso existente; prova exige aula pertencente a esse curso.
- Blueprint seleciona somente questões aprovadas e compatíveis, relata falta de cobertura sem criar resultado parcial e publica um LMS Quiz utilizável.
- Questões antigas permanecem no LMS, recebem reconciliação explícita e podem ser aprovadas sem nova importação duplicada.
- Questões publicadas, quizzes já tentados e submissões não são apagados nem alterados de modo a reescrever resultado histórico.
- Conteúdo não publicado não aparece no catálogo público; dados do aluno continuam protegidos pelas permissões LMS.
- Execuções QAPI respeitam limites configurados, registram consumo/resultados e não iniciam chamada paga automaticamente sem consentimento configurado.

## Suposições para aprovação

- “Completo” significa cobrir o ciclo de concurso descrito acima, incluindo catálogo público e conteúdo didático assistido, mas entregá-lo em fases para preservar migrações e validar o fluxo central cedo.
- Catálogo público é composto com website Frappe e páginas/cursos LMS existentes; não será um frontend separado.
- Metadados importados são aproveitados automaticamente quando o vínculo externo é inequívoco; o restante exige reconciliação ou edição humana.
- As regras de aprovação são globais por questão neste primeiro corte, sem workflow distinto por empresa/tenant.
- O mapeamento de tipos se limita a tipos que o LMS atual consiga executar; formatos não suportados permanecem editoriais até decisão específica.
