# ГЛАВА 14. ОЦЕНКА КАЧЕСТВА LLM-СИСТЕМ: EVALS, ТЕСТОВЫЕ НАБОРЫ И РЕГРЕССИИ

---

В 2005 году инженер-новичок мог выпустить код без единого теста и сказать: «у меня на машине работает». В 2015-м такое было уже неприлично — CI/CD, юнит-тесты, линтеры стали частью ремесла. В 2026 году LLM-системы находятся на том же перекрёстке. Команды меняют промпт, переключают модель, обновляют retriever — и оценивают результат фразой «вроде стало лучше». Это тот самый «works on my machine» для эпохи фронтирных моделей.

**Evals — это юнит-тесты LLM-инженерии.** Не в метафорическом смысле: eval-набор фиксирует ожидаемое поведение, автоматически прогоняется при каждом изменении и блокирует деплой, если качество упало. Без evals вы ведёте машину с заклеенным спидометром — может быть, хорошо, а может быть, не очень.

В предыдущих главах мы уже касались отдельных элементов оценки: агентные бенчмарки (Глава 10, §10.7), eval-метрики для RAG (Глава 12, §12.8), CoVe как верификация на лету (Глава 13), LDD-дашборды (Глава 13, §13.3). Эта глава собирает разрозненные элементы в **единую eval-дисциплину** — от golden dataset до regression gate в CI/CD.

---

## 14.1. Зачем нужна eval-дисциплина

### Проблема: оценка «на глаз»

Типичный сценарий: техлид просит «улучшить промпт для суммаризации». Инженер меняет системный промпт, прогоняет три примера вручную, видит, что ответы стали длиннее и подробнее, и деплоит. Через неделю приходят жалобы: модель начала галлюцинировать имена авторов. Три ручных примера не покрывали этот кейс.

Без evals вы не можете:
- **Детектировать регрессии**: изменение, улучшившее одну метрику, может ухудшить другую.
- **Сравнивать эксперименты**: «промпт A vs промпт B» без общего набора данных — субъективная оценка.
- **Обосновать выбор модели**: «Claude лучше GPT для нашей задачи» — голословно, если нет числа.

### Eval как контракт

Каждый eval определяет **«что значит хорошо»** для конкретной задачи. Это контракт между командой и системой — аналог интерфейса в typed-языке. Контракт содержит:

1. **Входные данные** — набор примеров (golden dataset).
2. **Ожидаемое поведение** — метрики и пороги (faithfulness ≥ 0.85, format validity = 100%).
3. **Способ проверки** — автоматический скоринг (LLM-judge, regex, schema validation).

### Три уровня оценки

| Уровень | Когда | Что проверяет | Пример |
|---------|-------|--------------|--------|
| **Offline** | До деплоя | Качество на фиксированном наборе | CI/CD regression gate |
| **Online** | В production | Качество на реальном трафике | Мониторинг faithfulness в дашборде |
| **Human review** | По триггеру | Экспертная оценка сложных кейсов | Энтропия LLM-judge > порог → эскалация |

Offline evals ловят грубые регрессии до того, как пользователи их увидят. Online evals обнаруживают drift — медленное ухудшение, незаметное на статичном наборе. Human review замыкает контур: ошибки, пойманные людьми, возвращаются в golden dataset.

---

## 14.2. Golden dataset: строительный материал evals

### Структура golden dataset

Golden dataset — это набор троек `(input, expected_output, context)`, где:

- **input** — запрос пользователя или входные данные для пайплайна.
- **expected_output** — эталонный ответ или набор допустимых ответов.
- **context** — (опционально) документы, которые модель должна использовать (для RAG-сценариев).

```python
# golden_dataset.jsonl — каждая строка — один пример
{
    "input": "Какова максимальная длина контекста Claude Opus 4.6?",
    "expected_output": "200K токенов",
    "context": "Claude Opus 4.6 поддерживает context window до 200K токенов.",
    "tags": ["factual", "model_specs"],
    "difficulty": "easy"
}
```

### Как собирать: правило 50–100

Начните с **50–100 примеров** для каждого core use case. Это минимум, позволяющий получить осмысленную статистику (см. §14.9). Источники:

1. **Ручная курация** — эксперт пишет примеры, покрывающие основные сценарии и edge-кейсы. Это самый дорогой, но самый точный способ.
2. **Production-логи** — берёте реальные запросы из LDD-логов (Глава 13, §13.3), фильтруете по success/failure, добавляете эталонные ответы. Это feedback loop: production → golden dataset → eval → production.
3. **Синтетическая генерация** — используете LLM для создания вариаций существующих примеров. DeepEval и RAGAS поддерживают генерацию синтетических тестовых данных из источников (документов, FAQ).

### Версионирование

Golden dataset эволюционирует вместе с продуктом. Новые кейсы появляются, старые становятся нерелевантными. **Версионируйте golden dataset рядом с промптами** — в том же репозитории, в том же коммите. Diff промпта без diff'а eval-набора — полуслепое изменение.

```
prompts/
├── summarization_v3.txt
├── summarization_v4.txt     # новая версия промпта
evals/
├── summarization_golden_v3.jsonl
├── summarization_golden_v4.jsonl  # обновлённый eval-набор
```

### Анти-паттерн: overfitting на eval-данные

Если вы используете golden dataset для итеративной подстройки промпта, вы рискуете **overfitting'ом**: промпт оптимизирован под конкретные 100 примеров, а не под задачу в целом. Решение: разделите набор на **dev-split** (для итерации) и **test-split** (для финальной оценки). Тестовый split трогается только один раз перед деплоем — точно как в ML.

---

## 14.3. Метрики: что измерять

### Метрики по типам задач

| Тип задачи | Ключевые метрики | Инструмент / источник |
|------------|------------------|----------------------|
| Open-ended QA | G-Eval, Faithfulness, Answer Relevancy | DeepEval, RAGAS |
| RAG | Context Precision, Context Recall, Faithfulness | RAGAS (см. Главу 12) |
| Кодогенерация | pass@k | Chen et al. 2021 |
| Классификация / Извлечение | Exact match, F1, Precision, Recall | Стандартные ML-метрики |
| Суммаризация | Factuality, Conciseness (G-Eval с кастомными критериями) | Liu et al. 2023 |

**Правило**: минимум **одна LLM-judge метрика + одна детерминированная метрика** на каждый eval-прогон. LLM-judge ловит семантические проблемы (ответ не по теме, неполный). Детерминированная метрика ловит структурные (невалидный JSON, превышение длины, отсутствие обязательных полей).

### Классические NLP-метрики: почему их недостаточно

BLEU, ROUGE и BERTScore долго были стандартом для оценки генерации текста. Для современных LLM-систем их **недостаточно** по трём причинам:

1. **Низкая корреляция с человеческой оценкой на открытых задачах.** BLEU измеряет n-gram overlap — два семантически эквивалентных, но по-разному сформулированных ответа получат низкий BLEU.
2. **Неприменимость к задачам с множественными правильными ответами.** На вопрос «Объясни, что такое attention» существует бесконечно много хороших ответов.
3. **Отсутствие оценки фактуальности.** ROUGE не различает грамотный текст с правильными фактами и грамотный текст с галлюцинациями.

Используйте BLEU/ROUGE/BERTScore как **baseline** или для задач с жёстким reference (перевод, извлечение данных), но не как основную метрику для open-ended генерации.

### Пример: комбинированный eval для RAG-пайплайна

```python
from deepeval import evaluate
from deepeval.metrics import (
    FaithfulnessMetric,
    AnswerRelevancyMetric,
    GEval,
)
from deepeval.test_case import LLMTestCase

# Детерминированная проверка: формат
def check_json_format(output: str) -> bool:
    try:
        data = json.loads(output)
        return "answer" in data and "sources" in data
    except json.JSONDecodeError:
        return False

# LLM-judge: faithfulness
faithfulness = FaithfulnessMetric(threshold=0.85, model="gpt-5.4")
relevancy = AnswerRelevancyMetric(threshold=0.8, model="gpt-5.4")

# Кастомный G-Eval: conciseness
conciseness = GEval(
    name="Conciseness",
    criteria="The response is concise and avoids unnecessary repetition.",
    evaluation_params=["actual_output"],
    threshold=0.7,
)

test_case = LLMTestCase(
    input="Как работает Flash Attention?",
    actual_output=pipeline_output,
    retrieval_context=retrieved_docs,
)

# Запуск: все метрики за один прогон
results = evaluate([test_case], [faithfulness, relevancy, conciseness])
```

---

## 14.4. LLM-as-Judge

### Принцип: модель оценивает модель

LLM-as-Judge — подход, при котором сильная модель оценивает output другой модели. Это как рецензирование в науке: автор (generator) пишет статью, рецензент (judge) оценивает качество. Рецензент не обязан быть соавтором — он должен быть **компетентным и незаинтересованным**.

Zheng et al. (2023) показали, что GPT-4 как judge достигает **>80% согласия с человеческими оценками** на MT-Bench — сопоставимо с inter-annotator agreement между людьми-экспертами. Это превратило LLM-as-Judge из эксперимента в production-инструмент.

### G-Eval: CoT + form-filling

**G-Eval** (Liu et al., 2023) — метод, объединяющий chain-of-thought рассуждение с оценкой по заданным критериям. Судья получает набор критериев и инструкцию сначала пошагово обосновать оценку (CoT), затем — выставить числовой балл. G-Eval показал лучшую корреляцию с человеческими оценками на задачах суммаризации по сравнению с предшествующими автоматическими метриками.

Промпт G-Eval для оценки суммаризации:

```
You will be given a source document and a summary.

Evaluation criteria:
- Coherence (1-5): Is the summary well-organized and logically structured?
- Consistency (1-5): Does the summary contain only facts from the source?
- Fluency (1-3): Is the summary grammatically correct and readable?
- Relevance (1-5): Does the summary capture the key information?

Steps:
1. Read the source document carefully.
2. Read the summary.
3. For each criterion, provide a brief justification.
4. Assign a score for each criterion.

Output format: JSON with "coherence", "consistency", "fluency", "relevance" keys.
```

### Известные bias'ы LLM-judge

Использовать модель как судью — мощно, но не безопасно без калибровки. Три основных bias'а задокументированы в литературе:

**1. Position bias.** Порядок ответов влияет на оценку. Wang et al. (2023) показали, что при pairwise comparison Vicuna «побеждает» ChatGPT в 66 из 80 случаев, когда ответ Vicuna стоит первым — и проигрывает при обратном порядке. Судья непропорционально предпочитает первый (или последний) ответ.

**2. Verbosity bias.** Судья предпочитает более длинные ответы, даже если короткий ответ точнее и полнее. Длина воспринимается как «полнота».

**3. Self-enhancement bias.** Модель предпочитает собственные ответы. Если GPT-5.4 оценивает output GPT-5.4 vs Claude Opus 4.6, есть систематический сдвиг в пользу своих текстов.

### Стратегии калибровки

**Balanced Position.** Запускайте каждое pairwise сравнение дважды — с обоими порядками ответов. Агрегируйте: если результат меняется при смене порядка — помечайте как tie.

```python
async def balanced_pairwise(judge, answer_a: str, answer_b: str) -> str:
    """Run pairwise comparison in both orders to counter position bias."""
    result_ab = await judge.compare(first=answer_a, second=answer_b)
    result_ba = await judge.compare(first=answer_b, second=answer_a)
    
    if result_ab == "first" and result_ba == "second":
        return "A"  # A wins in both positions
    elif result_ab == "second" and result_ba == "first":
        return "B"  # B wins in both positions
    else:
        return "tie"  # Inconsistent → position bias detected
```

**Multiple Evidence.** Генерируйте несколько rationale перед выставлением оценки. Среднее по нескольким «мнениям» одной модели более стабильно, чем единичное (аналог self-consistency из Главы 8).

**Human-in-the-Loop.** Вычисляйте entropy оценок судьи. Если для конкретного примера оценки нестабильны (высокая энтропия при multiple evidence) — маршрутизируйте к человеку. Судья обрабатывает 90% случаев, человек — оставшиеся 10% сложных.

### Анти-паттерн: circular validation

Использовать **одну и ту же модель как генератор и как судью** — circular validation. Модель склонна подтверждать собственные ответы (self-enhancement bias). Правило: судья должен быть **другой моделью** или **более сильной версией** того же семейства. В production-пайплайне 2026 года типичная пара: generator = GPT-5.3 Instant (быстрый, дешёвый), judge = Claude Opus 4.6 (точный, дорогой).

---

## 14.5. Pairwise comparison и Elo-ranking

### Chatbot Arena: 240K+ голосов

Chatbot Arena (lmarena.ai) — де-факто стандарт для сравнения LLM по человеческим предпочтениям. Пользователи получают анонимные ответы двух моделей и выбирают лучший. К 2026 году платформа собрала более 240 000 голосов (Chiang et al., 2024). Это самая масштабная crowd-sourced оценка LLM в мире.

Почему pairwise comparison надёжнее абсолютных оценок? Людям сложно дать стабильную оценку по 5-балльной шкале: один эксперт ставит 4, другой — 3 за один и тот же ответ. Но при выборе «A лучше B» согласие экспертов значительно выше. Сравнение — более естественная операция для человеческого суждения.

### Elo и Bradley-Terry

Результаты pairwise-сравнений агрегируются в рейтинг через **Elo** — систему, изначально разработанную для шахмат:

$$P(A > B) = \frac{1}{1 + 10^{(R_B - R_A)/400}}$$

Где $R_A$ и $R_B$ — текущие рейтинги моделей. Если модель с рейтингом 1200 побеждает модель с рейтингом 1000, это ожидаемо и рейтинги меняются мало. Если наоборот — изменение большое.

**Bradley-Terry** — статистически более строгая модель, оценивающая $P(A > B) = \frac{\pi_A}{\pi_A + \pi_B}$, где параметры $\pi$ оптимизируются методом максимального правдоподобия. Bradley-Terry даёт confidence intervals для рейтингов — критически важно при малом количестве сравнений.

### Production-применение: A/B-тестирование промптов

Тот же принцип — в вашем проекте. Вместо абсолютных оценок промптов спрашивайте: «какой из двух ответов лучше?» Это работает как для человеческой оценки, так и для LLM-as-Judge.

```python
# Pairwise eval: промпт A vs промпт B
results = []
for example in golden_dataset:
    output_a = await generate(example.input, prompt_version="v3")
    output_b = await generate(example.input, prompt_version="v4")
    
    winner = await judge.compare(
        question=example.input,
        answer_a=output_a,
        answer_b=output_b,
        criteria="accuracy, completeness, conciseness"
    )
    results.append(winner)

# Подсчёт: wins_a, wins_b, ties
print(f"Prompt v4 wins: {wins_b}/{len(results)} ({wins_b/len(results):.0%})")
```

### Evalica: open-source toolkit для pairwise ranking

**Evalica** (Ustalov, COLING 2025) — библиотека на Python и Rust для агрегации pairwise-сравнений. Реализует Elo, Bradley-Terry, PageRank и другие алгоритмы ранжирования. Для небольших eval-наборов — достаточно Elo; для статистической строгости — Bradley-Terry с confidence intervals.

```python
import evalica

# Данные: список pairwise-результатов
data = evalica.load("comparisons.csv")  # columns: winner, loser, tie
ranking = evalica.bradley_terry(data)

for model, score in ranking.items():
    print(f"{model}: {score:.1f}")
```

---

## 14.6. Failure taxonomy

### Девять категорий ошибок

Без классификации ошибок eval — это просто число. «Faithfulness = 0.72» — и что? Какие именно ошибки составляют те 28%? Failure taxonomy превращает число в actionable insights: вы видите, что 15% — hallucinations, 8% — format failures, 5% — retrieval failures, и знаете, что чинить в первую очередь.

| Категория | Описание | Метод детекции |
|-----------|----------|---------------|
| **Hallucination** | Фактически неверный контент | Faithfulness, Factuality |
| **Format non-compliance** | Невалидный JSON/XML/schema | Schema validation, regex |
| **Instruction non-following** | Игнорирование части инструкций | G-Eval с кастомными критериями |
| **Retrieval failure** | Неверный или неполный контекст | Context Precision, Context Recall |
| **Attribution error** | Ответ не подтверждается источниками | Faithfulness, entity recall |
| **Safety violation** | Токсичный, вредный, предвзятый контент | Moderation API, LLM Guard |
| **Verbosity / compression** | Слишком длинный или слишком короткий ответ | Token count, Conciseness |
| **Reasoning error** | Неверная цепочка рассуждений | pass@k, CoT verification |
| **Multi-turn inconsistency** | Противоречия между репликами в диалоге | Conversational metrics |

### Как использовать таксономию

1. **Тегируйте ошибки** в golden dataset — каждый пример с `"expected_failure_types"`.
2. **Классифицируйте отказы** при eval-прогоне — не просто «fail», а «fail: hallucination».
3. **Трекайте распределение** ошибок по категориям во времени. Если после обновления промпта hallucinations снизились, но instruction non-following вырос — это не улучшение, а перераспределение.
4. **Приоритизируйте** по impact: safety violation > hallucination > format non-compliance > всё остальное.

### Пример: тегирование при eval-прогоне

```python
@dataclass
class EvalResult:
    test_case_id: str
    passed: bool
    score: float
    failure_categories: list[str]  # ["hallucination", "verbosity"]
    details: str

def classify_failure(test_case, actual_output, metrics) -> list[str]:
    """Classify failure into taxonomy categories."""
    failures = []
    if metrics.faithfulness < 0.7:
        failures.append("hallucination")
    if not validate_schema(actual_output):
        failures.append("format_non_compliance")
    if metrics.answer_relevancy < 0.5:
        failures.append("instruction_non_following")
    if len(actual_output) > 2 * len(test_case.expected_output):
        failures.append("verbosity")
    return failures
```

---

## 14.7. Eval-фреймворки: ландшафт 2026

### Обзор инструментов

К 2026 году eval-фреймворки стали зрелой категорией. Выбор зависит от задачи: RAG-specific eval, general-purpose eval + CI/CD, pairwise ranking.

| Фреймворк | Язык | Фокус | Stars (GitHub) | Ключевая особенность |
|-----------|------|-------|----------------|---------------------|
| **Promptfoo** | TypeScript | Red-team + eval | ~20K | CI/CD gates, YAML-конфиг. Приобретён OpenAI (2025) |
| **DeepEval** | Python | Full eval | ~14.7K | Pytest-интеграция, G-Eval, DAG, agentic metrics |
| **RAGAS** | Python | RAG eval | ~13.3K | Context precision/recall, faithfulness |
| **Braintrust (Autoevals)** | Python/JS | Eval + observability | — | LLM-as-judge, heuristic, statistical scorers |
| **Evalica** | Python/Rust | Pairwise ranking | 62 | Elo, Bradley-Terry, PageRank. Быстрый (Rust core) |

### Promptfoo

Самый популярный eval-фреймворк общего назначения. Конфигурация через YAML, встроенная поддержка CI/CD gates, red-teaming (генерация adversarial-примеров). В 2025 году приобретён OpenAI, что не помешало ему остаться open-source. Подходит для команд, которым нужен eval + red-team в одном инструменте.

Репозиторий: https://github.com/promptfoo/promptfoo

### DeepEval

Python-native eval-фреймворк с интеграцией в pytest — eval-тесты запускаются так же, как обычные тесты. Поддерживает G-Eval, faithfulness, answer relevancy, DAG-based metrics для агентных пайплайнов. Идеален для Python-команд, которые хотят evals как часть тестового пайплайна.

```bash
# Запуск evals как тестов
deepeval test run test_eval.py
# Exit code = количество failures → CI/CD gate из коробки
```

Репозиторий: https://github.com/confident-ai/deepeval

### RAGAS

Специализированный фреймворк для оценки RAG-пайплайнов. Реализует context precision, context recall, faithfulness, answer relevancy. Подробно разобран в Главе 12, §12.8. Для RAG-системы RAGAS — обязательный инструмент.

Репозиторий: https://github.com/explodinggradients/ragas

### Braintrust (Autoevals)

Библиотека eval-scorer'ов от Braintrust: LLM-as-judge, heuristic (Levenshtein, JSON diff), statistical. Лёгкий, без фреймворк-оверхеда — можно интегрировать отдельные scorer'ы в любой пайплайн.

Репозиторий: https://github.com/braintrustdata/autoevals

### Evalica

Минималистичная библиотека для pairwise ranking, описанная в §14.5. Rust-core обеспечивает скорость на больших наборах сравнений.

Репозиторий: https://github.com/dustalov/evalica

---

## 14.8. Regression gates: evals в CI/CD

### Паттерн: prompt change → eval → gate → deploy

Regression gate — это автоматическая проверка качества, блокирующая деплой при падении метрик. Точно как CI/CD pipeline не пропускает код с красными тестами, regression gate не пропускает промпт с упавшим faithfulness.

```
[Prompt change] → [Git push] → [CI: run evals] → [JSON results]
                                                      │
                                               ┌──────┴──────┐
                                               │             │
                                          [Pass ✓]     [Fail ✗]
                                               │             │
                                          [Deploy]    [Block + alert]
```

### Три стратегии gate'ов

**1. Hard fail.** Любой провалившийся тест блокирует деплой. Подходит для safety-критичных кейсов (медицина, финансы). Строго, но хрупко — один flaky-тест блокирует всё.

**2. Threshold.** Pass rate < X% блокирует деплой. Например: «не менее 90% test cases проходят faithfulness ≥ 0.8». Устойчивее к шуму, но требует калибровки порога.

**3. Comparison.** Текущий эксперимент сравнивается с baseline (предыдущая версия). Блокировка, если метрики ухудшились статистически значимо. Самая надёжная стратегия, но требует хранения baseline-результатов.

### GitHub Actions: Promptfoo

```yaml
name: Eval Gate
on:
  pull_request:
    paths:
      - 'prompts/**'
      - 'evals/**'

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Install Promptfoo
        run: npm install -g promptfoo
      
      - name: Run evals
        run: npx promptfoo eval --output results.json
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      
      - name: Check quality gate
        run: |
          FAILURES=$(jq '.results.stats.failures' results.json)
          echo "Failures: $FAILURES"
          if [ "$FAILURES" -gt 0 ]; then
            echo "::error::Eval gate failed: $FAILURES test(s) failed"
            exit 1
          fi
```

### DeepEval: pytest-интеграция

```yaml
      - name: Run DeepEval tests
        run: deepeval test run tests/test_eval.py --verbose
        # Exit code != 0 при failures → CI блокирует PR автоматически
```

DeepEval работает через pytest — exit code = количество провалившихся тестов. Стандартный pytest + CI/CD = regression gate без дополнительной обвязки.

### Анти-паттерн: evals только в production

Запускать evals только на production-трафике — значит ждать, пока регрессия дойдёт до пользователей. Evals в CI/CD ловят проблему **до** деплоя. Production evals — дополнительный слой, а не замена.

---

## 14.9. Статистическая значимость

### Проблема малых выборок

С eval-набором из 30 примеров вы получаете «90% accuracy». Звучит хорошо. Но какова реальная точность? Доверительный интервал для пропорции:

$$p \pm z_{\alpha/2}\sqrt{\frac{p(1-p)}{n}}$$

При $n = 30$, $p = 0.9$, $\alpha = 0.05$ ($z_{0.025} = 1.96$):

$$0.9 \pm 1.96\sqrt{\frac{0.9 \cdot 0.1}{30}} = 0.9 \pm 0.107$$

Доверительный интервал: **[79.3%, 100%]**. Разброс в 21 процентный пункт — решать на основании такого числа нельзя.

При $n = 100$:

$$0.9 \pm 1.96\sqrt{\frac{0.9 \cdot 0.1}{100}} = 0.9 \pm 0.059$$

Доверительный интервал: **[84.1%, 95.9%]**. Уже actionable — если порог 85%, результат близок к границе, но осмысленный.

При $n = 200$:

$$0.9 \pm 1.96\sqrt{\frac{0.9 \cdot 0.1}{200}} = 0.9 \pm 0.042$$

Доверительный интервал: **[85.8%, 94.2%]**. Надёжно выше порога 85%.

### Практические рекомендации

| Контекст использования | Минимум примеров | Почему |
|-----------------------|-----------------|--------|
| Локальная итерация (dev) | 50 | Быстрая обратная связь, допустим широкий CI |
| CI/CD regression gate | 100–200 | Actionable CI, блокировка по порогу |
| Финальная валидация / A/B-тест | 200+ | Узкий CI, статистическая значимость |

### Сравнение двух промптов

Для сравнения двух промптов (A vs B) используйте McNemar's test или paired proportions test. При 100 примерах разница в 5% (90% vs 85%) может быть незначимой — нужно 200+ примеров, чтобы различить с уверенностью 95%.

**Правило большого пальца**: если вы не можете позволить себе 100+ примеров — используйте pairwise comparison (§14.5) вместо абсолютных метрик. Pairwise более чувствителен к различиям при малых выборках.

---

## Практический вывод

### Чек-лист eval-дисциплины

| # | Действие | Детали |
|---|----------|--------|
| 1 | **Соберите golden dataset** | 50–100 примеров на каждый core use case. Dev-split + test-split |
| 2 | **Выберите метрики** | Минимум 1 LLM-judge + 1 детерминированная метрика на задачу |
| 3 | **Автоматизируйте** | Evals в CI/CD как regression gates. Promptfoo или DeepEval |
| 4 | **Классифицируйте ошибки** | 9 категорий failure taxonomy. Трекайте распределение |
| 5 | **Версионируйте всё** | Промпты, golden datasets, eval-конфиги — в Git, в одном коммите |
| 6 | **Калибруйте судей** | Balanced position, multiple evidence для LLM-as-Judge |
| 7 | **Обеспечьте значимость** | $n \geq 100$ для CI gates, $n \geq 200$ для финальной валидации |
| 8 | **Замкните feedback loop** | Production failures → golden dataset → eval → production |

### Минимальный старт за один день

Если вы ещё не используете evals — начните с малого:

1. Вручную соберите 50 примеров из production-логов.
2. Добавьте одну метрику (faithfulness или exact match).
3. Напишите один `test_eval.py` для DeepEval.
4. Добавьте `deepeval test run` в CI.

Это не идеальная система — но это уже лучше, чем «вроде стало лучше».

---

## Источники

- Zheng, L., et al. (2023). "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena." NeurIPS 2023. arXiv:2306.05685
- Liu, Y., et al. (2023). "G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment." arXiv:2303.16634
- Wang, P., et al. (2023). "Large Language Models are not Fair Evaluators." arXiv:2305.17926
- Shankar, S., et al. (2024). "Who Validates the Validators? Aligning LLM-Assisted Evaluation of LLM Outputs." arXiv:2404.12272
- Yu, T., et al. (2025). "Self-Generated Critiques Boost Reward Modeling." NAACL 2025. arXiv:2411.16646
- Chiang, W., et al. (2024). "Chatbot Arena: An Open Platform for Evaluating LLMs by Human Preference." arXiv:2403.04132
- Ustalov, D. (2025). "Reliable, Reproducible, and Really Fast Leaderboards with Evalica." COLING 2025. arXiv:2412.11314
- Chen, M., et al. (2021). "Evaluating Large Language Models Trained on Code." arXiv:2107.03374
- Promptfoo. https://github.com/promptfoo/promptfoo
- DeepEval. https://github.com/confident-ai/deepeval
- RAGAS. https://github.com/explodinggradients/ragas
- Braintrust Autoevals. https://github.com/braintrustdata/autoevals

---

**Навигация:**
- Назад: [Глава 13. Антигаллюцинационный контур и защита от деградации](13_антигаллюцинационный_контур.md)
- Далее: [Глава 15. Безопасность LLM-систем](15_безопасность_llm_систем.md)
