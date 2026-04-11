# ГЛАВА 22. DURABLE ORCHESTRATION И ЖИЗНЕННЫЙ ЦИКЛ АГЕНТА

---

Глава 10 описывает, как агент *мыслит* — выбирает tool, строит план, рефлексирует. Но production-агент не живёт внутри одного HTTP-запроса. Он может работать минуты, часы, дни. Его прерывает пользователь, его останавливает approval checkpoint, он теряет соединение, его нужно перезапустить после падения сервера. Предыдущая глава — про serving: как LLM отвечает быстро и дёшево. Эта глава — про слой выше: runtime, в котором агент существует *во времени*, а не только думает.

Контекст 2026: фронтирные платформы (OpenAI Codex background tasks, Anthropic Claude Code headless sessions, Google ADK) документируют background execution, conversation state и long-running task lifecycle как production-норму. Агент, который не умеет пережить разрыв соединения, — это демо, а не система.

---

## 22.1. Синхронный агент vs background execution

Простейший агент работает синхронно: запрос → agent loop → ответ. Всё в рамках одного HTTP-соединения. Это подходит для задач, укладывающихся в 10–30 секунд, — ответ на вопрос, вызов одного-двух tools, форматирование результата.

Но code agent, анализирующий репозиторий на 500 файлов, или research agent, проходящий через 20 источников, работает минуты и часы. HTTP timeout браузера — 60–120 секунд. Мобильный клиент ещё менее толерантен. А в середине выполнения агент может потребовать human approval — и ждать ответа часами.

**Background execution** решает эту проблему: клиент ставит задачу, получает `202 Accepted` с task ID и уходит. Агент работает в фоне. Статус доступен через polling (`GET /tasks/{id}`) или push-уведомление (webhook, WebSocket).

Паттерн: `start_task(prompt, config)` → `task_id` → `poll(task_id)` / `subscribe(webhook_url)` → `get_result(task_id)`.

| Характеристика | Синхронный | Background |
|----------------|-----------|-----------|
| Время выполнения | < 30 сек | Минуты — часы |
| Протокол | HTTP request/response | 202 Accepted + polling/webhook |
| Human-in-the-loop | Невозможен в середине | Approval checkpoints |
| Fault tolerance | Потеря при timeout | Возможен resume |
| UX | Мгновенный ответ | Progressive output |

Это уже стандарт: OpenAI Codex выполняет задачи в фоновом sandbox-окружении, Claude Code поддерживает headless background sessions, Google ADK документирует long-running task lifecycle. Синхронный вызов остаётся для лёгких задач; тяжёлые — только background.

### Sandbox-изоляция background agents

Background agent работает без прямого контроля пользователя — значит, его среда должна быть изолирована. Типовой подход: каждая задача запускается в одноразовом контейнере (sandbox) с ограниченными правами: доступ только к нужным файлам, сети, API-ключам. Sandbox решает две задачи: (1) безопасность — agent с ошибкой в reasoning не может повредить хост-систему; (2) воспроизводимость — snapshot sandbox-среды можно сохранить для debugging. Codex использует именно такой паттерн: каждая задача получает изолированный cloud sandbox с клоном репозитория.

## 22.2. Event loop и conversation state

Agent loop — это event-driven state machine: получить событие (user message, tool result, timeout) → принять решение → выполнить действие → ожидать следующее событие. Между итерациями loop хранит состояние: историю сообщений, результаты tool calls, промежуточные планы, метаданные.

**Conversation state** — серверный объект, инкапсулирующий это состояние. Два уровня persistence:

- **Session-level** — текущий запуск, то, что помещается в context window. Volatile: при падении процесса теряется.
- **Conversation-level** — вся история взаимодействия, включая предыдущие сессии. Durable: хранится на сервере, доступен через API, переживает разрывы соединения и server restart.

Для background agents conversation state — единственный способ передать контекст между фазами выполнения. Если агент поставлен на паузу (approval checkpoint), его session-level state сериализуется в conversation object. При resume — десериализуется и восстанавливается.

Аналогия: conversation state для агента — как файл сохранения в игре. Можно выйти, перезагрузить машину, вернуться через день — и продолжить с того же места. Без сохранения — начинать сначала.

### Что хранить в conversation state

Минимальный набор: (1) system prompt и pinned constraints; (2) полная последовательность messages (user, assistant, tool); (3) tool call results с metadata (timestamp, latency, cost); (4) текущий статус задачи (running, paused, completed, failed); (5) checkpoint counter и compaction history. Без этих данных resume после паузы или crash невозможен.

Подробнее о memory architectures (session, episodic, semantic) — в главе 10, §10.5.

## 22.3. Pause, resume и approval checkpoints

Не все шаги agent loop безопасно выполнять автоматически. Перед необратимым действием — deploy в production, платёж, отправка email, push в main — агент должен остановиться и запросить подтверждение.

**Approval checkpoint** работает так: agent выдаёт событие `approval_required(action, context)` → orchestrator ставит задачу на паузу → notification пользователю (email, Slack, dashboard) → человек нажимает approve или reject → при approve — resume, при reject — abort или compensating action.

Это уже стандартная практика: GitHub Copilot Coding Agent запрашивает approval перед push; Claude Code имеет настраиваемые permission tiers (read / write / execute); OpenAI Codex ждёт user review перед применением изменений к репозиторию.

**Архитектурное следствие**: состояние агента в момент паузы должно быть serializable. Пауза = сериализация state → persist в хранилище → десериализация при resume. Если state содержит несериализуемые объекты (open connections, file handles, locks), checkpoint невозможен. Отсюда checkpoint discipline: проектировать agent state без привязки к runtime-ресурсам.

**Anti-pattern: approval gate без timeout.** Если человек не ответил за N часов, задача должна автоматически отменяться или эскалироваться. Бесконечное ожидание — это утечка ресурсов и забытая задача, которая при случайном approve через неделю выполнит устаревшее действие.

### Permission tiers как альтернатива approval на каждый шаг

Approval на каждое действие убивает скорость. Практичный компромисс — permission tiers: пользователь заранее определяет, какие категории действий агент выполняет автономно, какие — с подтверждением, какие — запрещены. Пример: read — автономно, write files — автономно, execute commands — с approval, network access — запрещено. Это позволяет агенту быстро выполнять безопасные шаги и останавливаться только на критичных. Подробнее о безопасности agent-действий — глава 15.

## 22.4. Partial streaming и progressive output

Long-running агент может генерировать промежуточные результаты задолго до финального ответа. Research agent нашёл три из десяти источников — пользователю полезно увидеть их сейчас, а не через 15 минут.

**Partial streaming** — отправка промежуточных шагов по мере выполнения: план, каждый tool result, прогресс, промежуточные выводы. Зачем:

- **UX** — пользователь видит прогресс, а не вращающийся spinner в тишине.
- **Early termination** — пользователь может остановить агента, если видит, что он пошёл не туда. Это экономит и токены, и время.
- **Real-time debugging** — разработчик видит trace агента в реальном времени, не дожидаясь завершения.

Протоколы доставки: Server-Sent Events (SSE) для однонаправленного потока, WebSocket для двунаправленного, polling endpoint с cursor для простых клиентов.

**Structured progress** — не просто текстовый стрим, а типизированные события: `{type: "tool_call", tool: "search", status: "running"}`, `{type: "step_complete", step: 3, total: 7}`, `{type: "approval_required", action: "deploy"}`. Это позволяет UI отрисовывать progress bar, показывать timeline шагов и реагировать на события (например, рендерить approval-кнопку).

**Anti-pattern: silent long-running agent.** Агент работает 10 минут, пользователь не видит ни одного промежуточного результата, не знает — работает агент или завис. Результат: пользователь отменяет задачу и перезапускает, создавая дублирующую нагрузку. Правило: любой агент, работающий более 30 секунд, должен отправлять structured progress events.

## 22.5. Compaction и контекстное окно long-running агента

Агент, работающий десятки и сотни шагов, неизбежно выходит за context window. У 128K-модели при активном tool use бюджет контекста заканчивается за 30–50 шагов: system prompt + plan + tool calls + tool results + reasoning = тысячи токенов на каждый шаг.

**Compaction strategies:**

- **Sliding window** — отбрасывать старейшие сообщения. Просто, но рискованно: ранние constraints и решения теряются.
- **Summarization** — LLM сжимает блок истории в краткое резюме. Сохраняет смысл, но добавляет latency и стоимость (дополнительный LLM-вызов).
- **Selective retention** — system prompt + план + последние N шагов + все tool results сохраняются дословно, reasoning между ними сжимается.

**Риски compaction**: потеря критического контекста. Ранние constraints («не трогай файл X», «бюджет 50 токенов на запрос») могут быть сжаты и забыты. Mitigation: **pinned messages** — сообщения, помеченные как несжимаемые. System prompt и ключевые constraints никогда не compactируются.

**Оптимальная стратегия для production**: system prompt + pinned constraints (never compacted) + sliding window последних N turns + summarized earlier turns + semantic recall из long-term memory при необходимости (см. §10.5, MemGPT).

Связь с memory: compaction может автоматически пополнять long-term memory — факты, извлечённые при сжатии, сохраняются для будущего retrieval. Это превращает «мусорную» операцию (выбрасывание старого контекста) в полезную (обучение агента на собственном опыте).

### Когда запускать compaction

Два подхода: (1) threshold-based — compaction запускается, когда context usage превышает X% от window (типично 70–80%); (2) step-based — compaction после каждых N шагов. Threshold-based точнее, но требует подсчёта токенов на каждом шаге. Step-based проще, но может запускать compaction слишком рано или слишком поздно. Компромисс: step-based с проверкой threshold — compaction через каждые N шагов, но только если usage > X%.

## 22.6. Rollback и compensation logic

В агентных workflow шаги часто имеют побочные эффекты: файл создан, API-вызов отправлен, запись в БД, commit в репозиторий, email послан. При ошибке на шаге N возникает вопрос: можно ли откатить шаги 1..N-1?

**Rollback** — обратная операция: удалить файл, revert commit, отменить заказ. Возможен не всегда: нельзя отменить отправленный email или опубликованный tweet.

**Compensation** — компенсирующее действие, когда точный откат невозможен: отправить email с коррекцией, закрыть ошибочно открытый тикет, выпустить hotfix.

**Saga pattern** из микросервисной архитектуры применим к agent workflow: каждый шаг определяет forward action и compensating action. При ошибке — compensating actions выполняются в обратном порядке. Для агента это означает: при проектировании tool набора для каждого tool с side-effects нужно определить, существует ли compensating action.

Практическое правило: если compensation невозможна → этот шаг требует approval checkpoint (§22.3). Необратимые действия без human approval — рецепт для инцидентов.

**Anti-pattern: retry without idempotency.** Если tool call не идемпотентен, retry может создать дубли — два платежа, два одинаковых email, два commit с одинаковым содержимым. Каждый tool call с side-effects должен принимать idempotency key. При retry с тем же ключом — операция не повторяется, возвращается результат предыдущего выполнения.

### Классификация tools по обратимости

При проектировании tool набора полезно классифицировать каждый tool:

| Категория | Примеры | Стратегия |
|-----------|---------|----------|
| Read-only | search, read_file, list_dir | Retry безопасен, compensation не нужна |
| Reversible | create_file, create_branch, open_pr | Rollback через обратную операцию |
| Compensatable | send_email, post_comment | Точный откат невозможен, но compensation есть |
| Irreversible | deploy_to_prod, publish, payment | Approval checkpoint обязателен |

Эта классификация определяет, где ставить approval gates и как проектировать recovery.

## 22.7. Fault tolerance и recovery

Агент может упасть в произвольный момент: OOM, server restart, LLM-провайдер вернул 503, network partition, истёк timeout.

**Наивный подход** — перезапуск с начала. Для задачи на 200 шагов, которая упала на шаге 180, это потеря времени и денег (повторные LLM-вызовы, повторные tool calls с side-effects).

**Durable execution** решает эту проблему: runtime (Temporal, Inngest, Restate) сохраняет каждый шаг в durable log. При restart агент resume с последнего зафиксированного шага, не повторяя предыдущие. Для LLM-агентов это означает: tool results и LLM responses персистируются. При replay используются сохранённые результаты — LLM не вызывается повторно.

**Проблема недетерминизма при replay.** LLM-вызовы недетерминистичны даже при temperature=0 (batching, floating-point порядок). Durable execution frameworks решают это, записывая *результат* каждого недетерминистичного вызова. При replay используется записанный результат, а не повторный вызов. Это принципиальное отличие от replay в детерминистичных workflow: записываются не только входы, но и выходы каждого шага.

**Circuit breaker для LLM-вызовов**: если провайдер отвечает ошибками N раз подряд → открыть circuit → fallback (переключение на другого провайдера, degraded response, постановка в очередь для отложенного retry). Без circuit breaker агент будет бесконечно биться в недоступный endpoint, тратя время и увеличивая задержку.

**Checkpoint granularity** — компромисс между safety и performance:

- Checkpoint после каждого tool call — максимальная безопасность, минимальная потеря при crash, но overhead на каждый шаг.
- Checkpoint после каждого agent step (решение + tool call + обработка результата) — быстрее, но при crash внутри step теряется больше работы.
- Выбор зависит от стоимости повторного выполнения: если tool call — это запрос к поисковику (дёшево), checkpoint после step достаточен. Если tool call — это deploy (дорого и с side-effects), checkpoint нужен до и после.

## 22.8. Observability long-running агентов

Long-running agent генерирует traces длиной в сотни span'ов. Стандартные dashboard'ы, рассчитанные на request/response в миллисекунды, не справляются с задачей, работающей часы.

Что нужно для наблюдаемости long-running агентов:

- **Timeline view** — визуализация того, что агент делал в каждый момент времени: какой tool вызывал, сколько ждал approval, когда выполнял compaction.
- **Cost running total** — сколько потрачено к текущему моменту (токены, API-вызовы, время вычислений). Позволяет обнаружить anomaly до завершения задачи.
- **Step success rate** — какие шаги чаще всего fail. Выявляет ненадёжные tools или некачественные промпты.
- **Drift detection** — движется ли агент к цели или зациклился. Метрики: повторяющиеся tool calls, растущий context без прогресса, одни и те же ошибки.

**Алерты для long-running agents:**

| Алерт | Триггер | Действие |
|-------|---------|----------|
| Cost alert | Бюджет превышен на X% | Пауза + notification |
| Loop detection | Один и тот же tool вызван N раз подряд | Пауза + escalation |
| Stuck detection | Нет прогресса за T минут | Timeout + abort |
| Error spike | Более M ошибок за K шагов | Circuit breaker + fallback |

Cross-reference: OpenTelemetry spans и LLM-specific observability — глава 17; trace-level eval — глава 14, §14.10.

### Cost tracking в реальном времени

Long-running agent может потратить сотни тысяч токенов за одну сессию. Без cost tracking команда узнаёт о проблеме из счёта провайдера. Минимум: на каждом шаге логировать input/output токены, считать running total, сравнивать с бюджетом. При превышении — пауза + notification, а не тихая остановка. Пользователь должен решить: увеличить бюджет или остановить задачу.

---

## Практический вывод

### Чек-лист: готовность к длительным агентным задачам

| Аспект | Вопрос | Минимум |
|--------|--------|---------|
| Execution model | Синхронный или background? | Background для задач > 30 сек |
| State persistence | Состояние переживёт restart? | Conversation object или durable execution |
| Approval gates | Где человек должен подтвердить? | Перед каждым необратимым действием |
| Streaming | Пользователь видит прогресс? | Structured events через SSE / WebSocket |
| Compaction | Что делать при выходе за context window? | Summarization + pinned constraints |
| Rollback | Есть compensating action для каждого tool? | Список tools с/без compensation |
| Idempotency | Tool calls можно безопасно retry? | Idempotency key для tools с side-effects |
| Recovery | Агент возобновится после crash? | Durable log или checkpoint |
| Monitoring | Как узнать, что агент завис? | Cost alert + step count + timeout |

### Задания

1. **Approval checkpoint.** Составьте промпт для ИИ, который генерирует agent loop с механизмом pause/resume через callback. Определите, какие действия в вашем контексте требуют approval, и классифицируйте tools на reversible / compensatable / irreversible.

2. **Chaos test.** Остановите агента в середине выполнения (kill process). Проверьте: восстановит ли он состояние при restart? Если нет — определите минимальный набор данных для checkpoint/recovery и реализуйте persist/restore cycle.

3. **Compaction analysis.** Возьмите trace long-running агента (или сгенерируйте синтетический на 50+ шагов). Найдите момент, когда context window заполняется. Сравните три стратегии — sliding window, summarization, selective retention — по потере критического контекста и стоимости.

---

## Источники

- Kwon, W. et al. (2023). "Efficient Memory Management for Large Language Model Serving with PagedAttention." SOSP 2023.
- Packer, C. et al. (2023). "MemGPT: Towards LLMs as Operating Systems." arXiv:2310.08560.
- Park, J. S. et al. (2023). "Generative Agents: Interactive Simulacra of Human Behavior." arXiv:2304.03442.
- OpenAI. (2026). "Codex: Background Tasks and Sandbox Execution." Platform documentation. https://platform.openai.com/docs
- Anthropic. (2026). "Claude Code: Headless and Background Mode." https://docs.anthropic.com/
- Google. (2025). "Agent Development Kit (ADK): Long-Running Tasks." https://google.github.io/adk-docs
- Temporal Technologies. "Durable Execution." https://temporal.io/
- Inngest. "Durable Functions for AI Workflows." https://www.inngest.com/
- Garcia-Molina, H. & Salem, K. (1987). "Sagas." ACM SIGMOD Record, 16(3).

---

**Навигация:**
- Назад: [Глава 21. Serving и runtime LLM-систем](21_serving_и_runtime_llm_систем.md)
- Далее: [Глава 23. Как начать: от первого промпта до рабочего агентного контура](23_как_начать.md)
