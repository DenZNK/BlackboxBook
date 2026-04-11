# ГЛАВА 21. SERVING И RUNTIME LLM-СИСТЕМ

---

Модель — это двигатель. Можно иметь лучший двигатель в мире, но без шасси, подвески и трансмиссии он не повезёт ни одного пассажира. Serving — это всё, что превращает веса на диске в ответ с предсказуемым latency и стоимостью.

В 2024–2025 serving перестал быть заботой ML-инженеров и стал частью продуктовой архитектуры. Решения о batching, caching, routing и quantization определяют latency, throughput и cost-per-query так же сильно, как выбор модели. Два одинаковых по весам deployment одной и той же модели способны отличаться по стоимости в 5–10× — только из-за разницы в serving stack. В этой главе — инженерный обзор serving: от управления GPU-памятью до capacity planning.

---

## 21.1. Две фазы inference: prefill и decode

LLM inference — не один монолитный процесс. Это две фазы с принципиально разным compute profile, и понимание этой границы — ключ к оптимизации.

**Prefill** — обработка всего input prompt. Все входные токены проходят через трансформер параллельно, модель вычисляет attention и заполняет KV-кэш. Эта фаза compute-bound: нагрузка на вычислительные ядра GPU максимальна. Latency на этой фазе определяет TTFT (Time to First Token) — сколько пользователь ждёт до первого символа ответа.

**Decode** — авторегрессионная генерация. Модель выдаёт по одному токену за шаг, каждый раз читая весь накопленный KV-кэш. Эта фаза memory-bound: bottleneck — не вычисления, а скорость чтения данных из GPU-памяти. Throughput на этой фазе определяет, сколько tokens/sec пользователь видит в стриминге.

Почему это важно: оптимизации для prefill (tensor parallelism, prefix caching) не помогают decode, и наоборот. Когда инженер жалуется на «медленный inference», первый вопрос — какая именно фаза тормозит. TTFT высокий — проблема в prefill. Стриминг медленный — проблема в decode. Разные фазы → разные инструменты.

Подробнее о KV-кэше как ресурсе — в главе 5, о метриках TTFT и throughput — в главе 24 (§24.9).

## 21.2. KV-кэш как центральный ресурс

KV-кэш (Key-Value cache) — это intermediate state, который модель хранит для каждого attention-слоя и каждого токена в контексте. Во время decode-фазы модель не пересчитывает attention заново для всех предыдущих токенов — она читает результаты из KV-кэша.

Размер KV-кэша пропорционален: layers × heads × head_dim × seq_len × 2 (K и V) × batch_size. Для 70B-модели на 32K контексте при batch=1 это уже десятки гигабайт. При batch из 50 concurrent запросов — сотни гигабайт, что часто превышает объём GPU-памяти, доступный для самих весов.

Наивная аллокация — выделить для каждого запроса максимальный блок — фрагментирует GPU-память и резко снижает concurrency. **PagedAttention** (Kwon et al., SOSP 2023) решает эту проблему по аналогии с виртуальной памятью в ОС: KV-кэш делится на блоки фиксированного размера (pages), маршрутизация через таблицу страниц, аллокация — по мере необходимости. Это устраняет фрагментацию и позволяет достичь near-zero waste. vLLM — engine, построенный на PagedAttention, — стал де-факто стандартом open-source serving.

### Prefix caching

Если несколько запросов разделяют общий prefix (system prompt, few-shot примеры), KV-кэш для этого prefix можно вычислить один раз и переиспользовать. Это радикально ускоряет TTFT в multi-turn conversations, где system prompt одинаков для тысяч запросов.

Prefix caching доступен и на стороне провайдеров: Anthropic prompt caching (до 90% снижения стоимости префикса), OpenAI cached prompt tokens. Для self-hosted — vLLM и SGLang поддерживают automatic prefix caching.

### Cross-request KV sharing

Более продвинутый вариант: tree-structured caching, когда несколько ветвей генерации (beam search, parallel sampling) разделяют общие поддеревья KV-кэша. Это уменьшает memory footprint при multi-hypothesis генерации (см. главу 8).

## 21.3. Continuous batching и scheduling

При static batching serving-система собирает batch из N запросов, обрабатывает их одновременно и ждёт, пока завершится самый длинный. GPU простаивает, пока короткие запросы уже завершены. Это способ гарантированно получить низкий throughput.

**Continuous batching** (iteration-level batching) меняет парадигму: новые запросы добавляются в batch на каждой decode-итерации. Как только запрос завершился — его slot освобождается, и в него тут же вставляется следующий запрос из очереди. GPU загружен всегда.

### Scheduling и admission control

При перегрузке системе приходится выбирать: деградировать latency для всех или ограничить admission. Две основные стратегии:

| Стратегия | Механизм | Когда использовать |
|-----------|----------|-------------------|
| Priority queue | SLO-sensitive запросы обслуживаются первыми, low-priority — в tail | Продукт с разными SLA-тирами |
| Back-pressure | HTTP 429 + client-side retry с exponential backoff | Защита кластера от каскадного overload |

Scheduling policies: FCFS (простой и fair), priority-based (разные SLO-тиры получают разный latency), preemption (прервать длинный decode для urgent prefill, если TTFT SLO под угрозой).

## 21.4. Disaggregated prefill/decode

Prefill compute-bound, decode memory-bound. Объединять их на одном GPU — компромисс: GPU либо недоиспользует compute (во время decode), либо недоиспользует memory bandwidth (во время prefill).

**Disaggregated architecture** разделяет фазы на отдельные GPU-группы. Prefill-nodes обрабатывают входные промпты и передают готовый KV-state на decode-nodes, которые занимаются только генерацией.

Преимущества: prefill-nodes оптимизируются под compute (высокий tensor parallelism), decode-nodes — под memory bandwidth. Каждая фаза масштабируется независимо: всплеск коротких запросов → масштабировать prefill, рост длины ответов → масштабировать decode.

Trade-off: передача KV-state между нодами добавляет latency. Требуется высокоскоростной interconnect (NVLink, InfiniBand). Подход применяется в крупных serving-кластерах (TensorRT-LLM, промышленные vLLM-деплойменты), но не оправдан для single-GPU.

## 21.5. Speculative decoding

Decode фаза memory-bound — GPU ждёт данные из памяти на каждом шаге. Speculative decoding использует это «окно ожидания»: маленькая draft-модель быстро генерирует K токенов-кандидатов, затем target-модель верифицирует их одним forward pass. Принятые токены — финальные, отвергнутые — отбрасываются и генерируются заново.

Метод **lossless**: распределение вероятностей выходных токенов идентично target-модели. Speedup: 2–3× на типичных задачах.

### Инженерные решения

**Выбор draft-модели**: smaller version того же семейства (Llama 70B → Llama 8B как draft), модель после structured pruning, или специально обученная маленькая модель. Self-speculative decoding использует subset слоёв самой target-модели как draft — не требует отдельного deployment.

**Acceptance rate** зависит от задачи: простой текст → высокий AR (80%+), reasoning и code → ниже (50–60%). Чем выше AR, тем больше speedup.

vLLM и TensorRT-LLM поддерживают speculative decoding из коробки. Подробнее о месте speculative decoding в ландшафте — в главе 24 (§24.9).

## 21.6. Quantization: точность vs ресурсы

Quantization уменьшает precision весов (и/или активаций) модели: FP16 → INT8, INT4, реже до предельных значений. Меньше бит → меньше памяти → больше concurrent запросов → ниже стоимость.

| Метод | Что квантизуется | Эффект | Деградация качества |
|-------|-----------------|--------|---------------------|
| GPTQ, AWQ | Только веса (FP16 → INT4) | Memory footprint ×4 ↓ | Минимальная (1–3% на бенчмарках) |
| SmoothQuant | Веса + активации (INT8) | Compute speedup + memory ↓ | Умеренная, зависит от задачи |
| BitNet b1.58 | Ternary weights ({-1, 0, 1}) | CPU inference без GPU | Research frontier, не production-ready |

**Практическое правило**: INT4 weight-only (AWQ/GPTQ) — sweet spot для self-hosted serving. Потеря качества минимальна, memory footprint уменьшается в 4 раза, inference быстрее за счёт сокращения memory transfers.

Важное следствие: quantized 70B-модель часто эффективнее, чем полноразмерная 8B — больше знаний при сопоставимом ресурсном бюджете. Подробнее о SLM и выборе размера модели — в главе 24 (§24.4).

## 21.7. Multi-LoRA serving

LoRA (Low-Rank Adaptation) позволяет дообучить модель под конкретную задачу, добавляя к attention-слоям компактные low-rank матрицы (см. главу 19 для технических деталей). Ключевой вопрос serving: как обслуживать десятки LoRA-адаптеров без десятков копий модели?

**Multi-LoRA serving** загружает одну base-модель и переключает LoRA-адаптеры per-request. KV-кэш и основные веса — общие; адаптер добавляет только несколько мегабайт. Один GPU-кластер обслуживает десятки кастомизированных моделей вместо десятков отдельных deployment.

vLLM и SGLang поддерживают multi-LoRA serving. Переключение между адаптерами — микросекунды, overhead — минимальный. Это архитектурно выгодно для SaaS-платформ, где каждый tenant имеет собственную fine-tuned модель.

## 21.8. Benchmarking и метрики serving

Serving-метрики — это не абстрактные числа, а SLO-контракты с пользователями. Основные:

| Метрика | Что измеряет | Типичные SLO |
|---------|-------------|-------------|
| TTFT (p50, p95, p99) | Время до первого токена | p95 < 500ms (chat), < 2s (batch) |
| Decode throughput | Tokens/sec на один запрос | > 30 tok/s (chat streaming) |
| TPS | Total tokens/sec на кластер | Зависит от capacity |
| End-to-end latency | Полное время ответа | Зависит от output length |
| Queue wait time | Ожидание в очереди | p95 < 100ms |

### Методология тестирования

Тестировать с реалистичными промптами (не "hello"), реалистичным распределением длин input/output, реалистичным concurrency. Pitfalls: не сравнивать TTFT при разных prompt lengths; не сравнивать throughput batch-режима со streaming; учитывать warm-up GPU и заполнение KV-кэша.

> **Промпт для генерации нагрузочного теста:**
> «Напиши Python-скрипт для нагрузочного тестирования OpenAI-совместимого LLM endpoint. Скрипт должен: принимать URL endpoint, число concurrent запросов, и файл с тестовыми промптами; отправлять запросы с заданным concurrency через asyncio + aiohttp; замерять TTFT, decode throughput (tokens/sec) и end-to-end latency для каждого запроса; выводить p50, p95, p99 для каждой метрики. Формат вывода — таблица в stdout.»

## 21.9. GPU capacity planning

Упрощённая формула для оценки:

$$\frac{\text{model\_size\_GB}}{\text{quant\_factor}} + \text{KV\_cache\_per\_request} \times \text{max\_concurrent} \leq \text{total\_GPU\_memory}$$

**Пример**: Llama 70B в INT4 ≈ 35 GB весов. На A100 80 GB остаётся ~45 GB для KV-кэша. При 32K контексте один запрос потребляет ~2–4 GB KV-кэша → максимум 10–20 concurrent запросов на одном GPU. Для 100 concurrent → нужен кластер.

### Parallelism

| Тип | Механизм | Когда использовать |
|-----|----------|-------------------|
| Tensor parallelism | Один запрос на нескольких GPU | Latency ↓ для больших моделей |
| Pipeline parallelism | Разные слои на разных GPU | Throughput ↑ при высоком concurrency |

### Self-hosted vs API vs hybrid

Выбор deployment mode — архитектурное решение (подробнее — в главе 23, «Как начать»):

- **API-first** (OpenAI, Anthropic, Google): для variable/unpredictable нагрузки, быстрого старта, минимального ops overhead.
- **Self-hosted**: для steady-state high-volume нагрузки, data residency requirements, custom моделей. При >N тысяч запросов/день может быть экономичнее, но требует ops capacity.
- **Hybrid**: API для burst capacity, self-hosted для baseline — позволяет оптимизировать и cost, и availability.

Breakeven point зависит от модели, quantization, цены hardware и ops-команды. Универсальной формулы нет — но capacity planning всегда начинается с расчёта memory budget.

---

## Практический вывод

### Чек-лист serving-архитектуры

| # | Пункт | Вопрос |
|---|-------|--------|
| 1 | Deployment target | API, self-hosted или hybrid? |
| 2 | Модель и размер | Какая модель? Нужна ли quantization? |
| 3 | Quantization | INT4 (sweet spot) или INT8? Проведён ли eval на golden set? |
| 4 | KV-кэш strategy | Prefix caching включён? Средняя и максимальная длина контекста? |
| 5 | Batching | Continuous batching настроен? Admission control есть? |
| 6 | Speculative decoding | Применим ли? Есть ли подходящая draft-модель? |
| 7 | Multi-LoRA | Нужны ли per-tenant адаптеры? |
| 8 | Мониторинг | TTFT, throughput, queue wait — замеряются на p95/p99? |
| 9 | Capacity planning | Memory budget рассчитан? Ceiling concurrency определён? |
| 10 | Fallback | Есть ли fallback на API при перегрузке self-hosted? |

### Задания

1. **Memory budget.** Рассчитайте GPU memory budget для модели, которую вы используете: размер весов после quantization + KV-кэш при целевом concurrency. Определите, сколько GPU нужно и какой параллелизм (tensor vs pipeline) оптимален. Ожидаемый результат: таблица с числами — model size, KV per request, max concurrent, total GPU count.

2. **Нагрузочный тест.** Настройте load test для вашего LLM endpoint: замерьте TTFT p50/p95 и decode throughput при 10, 50, 100 concurrent requests. Используйте промпт из §23.8 для генерации скрипта. Ожидаемый результат: отчёт с графиками latency vs concurrency.

3. **Quantization eval.** Сравните INT8 и INT4 quantization для вашей задачи: проведите eval на golden set (см. главу 14) и замерьте разницу в качестве (accuracy/F1) и throughput (tokens/sec). Ожидаемый результат: таблица «precision → quality → speed → cost».

---

## Источники

- Kwon, W. et al. (2023). "Efficient Memory Management for Large Language Model Serving with PagedAttention." SOSP 2023.
- Leviathan, Y. et al. (2023). "Fast Inference from Transformers via Speculative Decoding." ICML 2023.
- Chen, C. et al. (2023). "Accelerating Large Language Model Decoding with Speculative Sampling." DeepMind.
- Frantar, E. et al. (2023). "GPTQ: Accurate Post-Training Quantization for Generative Pre-trained Transformers." ICLR 2023.
- Lin, J. et al. (2024). "AWQ: Activation-aware Weight Quantization for LLM Compression and Acceleration." MLSys 2024.
- Ma, S. et al. (2024). "The Era of 1-bit LLMs: All Large Language Models are in 1.58 Bits." Microsoft Research.
- Gim, I. et al. (2024). "Prompt Cache: Modular Attention Reuse for Low-Latency Inference." MLSys 2024.
- Xiao, G. et al. (2023). "SmoothQuant: Accurate and Efficient Post-Training Quantization for Large Language Models." ICML 2023.
- vLLM Project. "vLLM: Easy, Fast, and Cheap LLM Serving." https://docs.vllm.ai/
- NVIDIA. "TensorRT-LLM." https://github.com/NVIDIA/TensorRT-LLM

---

**Навигация:**
- Назад: [Глава 20. Паттерны проектирования LLM-приложений](20_паттерны_проектирования.md)
- Далее: [Глава 22. Durable orchestration и жизненный цикл агента](22_durable_orchestration_и_жизненный_цикл_агента.md)
