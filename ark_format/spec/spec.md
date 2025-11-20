# Kovcheg Archive Format (.ark) Specification

**Status:** Draft / Request for Comments (RFC)  
**Version:** 0.1  
**Date:** 2025-11-19  
**Author:** Principal Architect, Project "Kovcheg"

---

## Table of Contents

1. [Core Data Model & Semantics](#section-1-core-data-model--semantics)
2. [Binary Format Specification](#section-2-binary-format-specification)
3. [Security Model](#section-3-security-model-specification)
4. [Reference Implementation](#section-4-reference-implementation)

---

## Section 1: Core Data Model & Semantics

### 1.1 Abstract & Design Philosophy

Формат `.ark` розроблений як універсальний контейнер ("Digital Ark") для довготривалого зберігання гетерогенних даних, оптимізований для машинного навчання (Machine Learning) та побудови RAG-систем (Retrieval-Augmented Generation).

Філософія формату базується на дихотомії "Монстр/Стандарт":

- **The Monster**: Формат здатний поглинати будь-який контент — від сирого тексту та OCR-сканів до семантичних векторів та графів знань.
- **The Standard**: Внутрішня структура є суворо типізованою. Це гарантує, що будь-який ark-файл, створений сьогодні, буде однозначно інтерпретований через 50 років.

#### Ключові принципи:

1. **Immutability (Незмінність)**: Будь-яка зміна в блоці Content призводить до інвалідації checksum та signature. Версійність досягається створенням нового файлу з посиланням на попередній (через поле provenance), а не модифікацією існуючого.

2. **Self-containment (Самодостатність)**: Файл `.ark` містить усе необхідне для його обробки: метадані, ліцензію, векторні представлення та структурні зв'язки. Зовнішні залежності заборонені для критичних шляхів відтворення (critical rendering path).

3. **AI-readiness (Готовність до ШІ)**: Дані зберігаються не лише як текст, а як тензори та графи. Це дозволяє завантажувати `.ark` файли безпосередньо у векторні бази даних (Vector DBs) без етапу повторного ембеддингу.

---

### 1.2 Detailed Field Specification

Термінологія вимог (MUST, SHOULD, MAY) відповідає RFC 2119.

#### 1.2.1 Header (The Immutable Core)

Ця секція забезпечує ідентифікацію, цілісність та юридичний статус даних.

| Field Name | Data Type | Cardinality | Validation Rules | Description |
|------------|-----------|-------------|------------------|-------------|
| `id` | UUID String | 1 | MUST be a valid UUIDv4 (RFC 4122). Canonical lowercase representation. | Унікальний ідентифікатор архівного об'єкта. Використовується як Primary Key у розподілених сховищах. |
| `version` | String | 1 | MUST follow SemVer 2.0.0 (e.g., "1.0.2"). | Версія схеми `.ark`, яка використовується для валідації цього файлу. |
| `created_at` | String | 1 | MUST be ISO 8601 strict (YYYY-MM-DDThh:mm:ssZ). Always UTC. | Точний час створення ("запечатування") архіву. |
| `checksum` | String | 1 | MUST be a SHA-256 hash (hex-encoded). | Хеш, обчислений тільки від блоку Content (бінарна або канонічна JSON репрезентація). Гарантує цілісність payload. |
| `signature` | Object | 0..1 | Structure: `{ "pub_key": "hex", "sig": "hex", "algo": "ed25519" }`. | Криптографічний підпис блоку checksum власником (автором) архіву. Забезпечує Non-repudiation. |
| `license` | String | 1 | MUST be a valid SPDX Identifier (e.g., "CC-BY-4.0", "MIT", "UNLICENSED"). | Юридичні права на використання вмісту. Парсери MUST перевіряти це поле перед навчанням моделей. |

#### 1.2.2 Metadata (The Context Layer)

Контекст, необхідний для фільтрації, маршрутизації та модерації даних.

| Field Name | Data Type | Cardinality | Validation Rules | Description |
|------------|-----------|-------------|------------------|-------------|
| `language` | String | 1 | MUST be an IETF BCP 47 tag (e.g., "uk", "en-US"). | Основна мова контенту. Для мультимовних документів вказується домінуюча мова. |
| `risk_level` | Enum | 1 | Values: `safe`, `warning`, `restricted`, `toxic`. | Маркер безпеки контенту (див. визначення нижче). |
| `data_provenance` | Object | 1 | Structure defined below. | Ланцюг походження даних (Lineage). |
| `tags` | List<String> | 0..* | Max length per tag: 64 chars. | Ключові слова для швидкого пошуку. |

##### Risk Level Definitions:

- **safe**: Інформація загального призначення, перевірена, безпечна для fine-tuning без фільтрів.
- **warning**: Потребує уваги (наприклад, політично заангажований текст, суб'єктивна думка).
- **restricted**: Містить PII (Personal Identifiable Information) або конфіденційні дані. MUST NOT be indexed publicly.
- **toxic**: Містить мову ворожнечі, дезінформацію або шкідливий код. Зберігається виключно для dataset filtering або research purposes.

##### Data Provenance Structure:

- `source_uri` (String, URL format): Початкове джерело (якщо є).
- `author` (String): Творець контенту.
- `acquisition_method` (Enum: `manual`, `scraper`, `api`, `generated`).
- `scraper_version` (String, optional): Версія інструменту, який зібрав дані.

#### 1.2.3 Content (The Payload)

Основне навантаження. Парсер може завантажувати цю секцію "lazy" (ліниво), якщо потрібен лише заголовок.

| Field Name | Data Type | Cardinality | Validation Rules | Description |
|------------|-----------|-------------|------------------|-------------|
| `docs` | List<Doc> | 1..* | Must contain at least one document representation. | Список нормалізованих текстових блоків. |
| `embeddings` | List<Emb> | 0..* | Dimensions must match the model spec. | Векторні представлення контенту. |
| `knowledge_graph` | List<Triple> | 0..* | Subject/Object strings must not be empty. | Семантичні зв'язки у форматі триплетів. |

##### Sub-structures:

**1. Doc (Document Unit):**
- `mime_type` (String): e.g., `text/markdown`, `text/plain`. HTML дозволений, але `text/markdown` є RECOMMENDED.
- `encoding` (Enum): `utf-8` (default), `base64` (для бінарних вкладень).
- `body` (String): Власне контент.

**2. Emb (Embedding Tensor):**
- `model_id` (String): Унікальний ID моделі (e.g., `openai/text-embedding-3-small`, `huggingface/sentence-transformers/all-MiniLM-L6-v2`).
- `dimensions` (uint32): Розмірність вектора (e.g., 1536).
- `vector` (List<float32>): Масив чисел з плаваючою комою.

**3. Triple (Graph Edge):**
- `subject` (String): Сутність (Entity).
- `predicate` (String): Відношення (Relation).
- `object` (String): Сутність або Літерал.

---

### 1.3 Reference Examples

#### 1.3.1 Complex JSON Reference

Це канонічне представлення (Canonical JSON Representation).

```json
{
  "header": {
    "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "version": "0.1.0",
    "created_at": "2025-11-19T18:30:00Z",
    "checksum": "a1b2c3d4e5f6...", 
    "signature": {
      "pub_key": "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
      "sig": "7a980182b10ab...",
      "algo": "ed25519"
    },
    "license": "CC-BY-4.0"
  },
  "metadata": {
    "language": "uk-UA",
    "risk_level": "safe",
    "tags": ["історія", "кобзарі", "фольклор"],
    "data_provenance": {
      "source_uri": "https://archives.gov.ua/folklore/kobzars.html",
      "author": "Іван Литвин",
      "acquisition_method": "scraper",
      "scraper_version": "kovcheg-spider-v2.4"
    }
  },
  "content": {
    "docs": [
      {
        "mime_type": "text/markdown",
        "encoding": "utf-8",
        "body": "# Кобзарство в Україні\n\nКобзарство — це унікальне явище української культури..."
      }
    ],
    "embeddings": [
      {
        "model_id": "openai/text-embedding-3-small",
        "dimensions": 1536,
        "vector": [0.0123, -0.0456, 0.1021, "...", 0.0054] 
      }
    ],
    "knowledge_graph": [
      {
        "subject": "Кобзарство",
        "predicate": "є_частиною",
        "object": "Українська культура"
      },
      {
        "subject": "Остап Вересай",
        "predicate": "був",
        "object": "Кобзар"
      }
    ]
  }
}
```

#### 1.3.2 Complex YAML Reference

Призначений для ручного редагування конфігурацій або налагодження (debugging), перед компіляцією у бінарний формат (якщо такий буде прийнято пізніше).

```yaml
header:
  id: "f47ac10b-58cc-4372-a567-0e02b2c3d479"
  version: "0.1.0"
  created_at: "2025-11-19T18:30:00Z"
  checksum: "a1b2c3d4e5f6..."
  signature:
    pub_key: "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    sig: "7a980182b10ab..."
    algo: "ed25519"
  license: "CC-BY-4.0"

metadata:
  language: "uk-UA"
  risk_level: "safe"
  tags:
    - "історія"
    - "кобзарі"
    - "фольклор"
  data_provenance:
    source_uri: "https://archives.gov.ua/folklore/kobzars.html"
    author: "Іван Литвин"
    acquisition_method: "scraper"
    scraper_version: "kovcheg-spider-v2.4"

content:
  docs:
    - mime_type: "text/markdown"
      encoding: "utf-8"
      body: |
        # Кобзарство в Україні
        
        Кобзарство — це унікальне явище української культури...
  
  embeddings:
    - model_id: "openai/text-embedding-3-small"
      dimensions: 1536
      vector: 
        - 0.0123
        - -0.0456
        - 0.1021
        # ... truncated for brevity
  
  knowledge_graph:
    - subject: "Кобзарство"
      predicate: "є_частиною"
      object: "Українська культура"
    - subject: "Остап Вересай"
      predicate: "був"
      object: "Кобзар"
```

---

## Section 2: Binary Format Specification

### 2.1 Canonical Binary Layout (The "On-Disk" Format)

Формат `.ark` використовує **Hybrid Container Model**. Метадані зберігаються як структурований текст (JSON) для зручності інспекції, тоді як тензори (embeddings) та бінарні об'єкти зберігаються як Raw Binary Blobs, вирівняні для прямого відображення в пам'ять (mmap).

Файл `.ark` представляє собою конкатенацію наступних блоків у суворій послідовності:

```
[Magic Bytes] + [Manifest Length] + [Manifest JSON] + [Padding] + [Binary Payload]
```

#### 2.1.1 Magic Bytes & Versioning

Кожен файл ПОВИНЕН (MUST) починатися з наступної 8-байтової послідовності. Це запобігає випадковій інтерпретації файлу як тексту.

| Offset | Length | Value (Hex) | Description |
|--------|--------|-------------|-------------|
| 0x00 | 4 | 0x41 0x52 0x4B 0x01 | ASCII string "ARK" + 0x01 (binary control char). |
| 0x04 | 2 | 0x00 0x01 | Major Version (uint16_be). Current: 1. |
| 0x06 | 2 | 0x00 0x00 | Minor Version (uint16_be). Current: 0. |

#### 2.1.2 Manifest Block (Metadata Header)

- Слідує одразу за Magic Bytes.
- **Length Prefix**: 64-bit unsigned integer (Little Endian), що вказує на довжину наступного JSON-блоку в байтах.
- **Body**: UTF-8 encoded JSON, що відповідає схемі з Розділу 1.2.
- **Важлива вимога**: У секції `content.embeddings` поле `vector` у JSON замінюється на посилання `blob_offset` та `blob_length`. Сам масив чисел не серіалізується в JSON.

#### 2.1.3 Zero-Copy Alignment (Padding)

Для забезпечення максимальної продуктивності завантаження векторів (SIMD instructions, GPU DMA transfers), початок блоку Binary Payload ПОВИНЕН бути вирівняний.

- **Alignment Rule**: Початок секції даних (offset першого байта Payload) ПОВИНЕН бути кратним 64 байтам (типовий розмір кеш-лінії CPU).
- **Implementation**: Між кінцем JSON Manifest та початком Payload вставляються 0x00 байти (Null Padding) до досягнення найближчої границі 64 байт.

#### 2.1.4 Binary Payload (The Tensor Storage)

Ця секція містить "сирі" дані (float32 arrays), записані послідовно.

- **Format**: IEEE 754 Little Endian Float32.
- **Structure**: Contiguous memory block.
- **Access**: Парсер зчитує `blob_offset` з JSON маніфесту і робить `seek()` (або `mmap()` + pointer arithmetic) для доступу до вектора без десеріалізації.

---

## Section 3: Security Model Specification

Безпека `.ark` базується на принципі **Cryptographic Binding** між метаданими та контентом.

### 3.1 Digital Signatures (Canonicalization Flow)

Оскільки JSON є невпорядкованим форматом (unordered sets), просте хешування тексту ненадійне. Реалізація ПОВИННА використовувати **RFC 8785 (JSON Canonicalization Scheme - JCS)**.

#### Алгоритм підпису (Signing Flow):

1. **Prune**: Видалити поле `header.signature` з об'єкта (якщо воно існує).

2. **Canonicalize**: Перетворити JSON об'єкт у канонічну форму згідно RFC 8785.
   - Сортування ключів лексикографічно.
   - Видалення whitespace.
   - Серіалізація чисел (e.g., 1.0 → 1, 1e+2 → 100).

3. **Hash Payload**: Обчислити SHA-256 хеш від бінарної секції Content. Вставити цей хеш у поле `header.checksum`.

4. **Hash Manifest**: Обчислити SHA-256 хеш від канонізованого JSON (який вже містить хеш пейлоаду).
   ```
   H_final = SHA256(JCS(Manifest))
   ```

5. **Sign**: Підписати `H_final` приватним ключем Ed25519.
   ```
   S = Sign_priv(H_final)
   ```

6. **Attach**: Додати результат `S` у поле `header.signature.sig`.

### 3.2 Content Sanitization (The Monster Guardrails)

Формат `.ark` може зберігати "токсичний" контент (HTML, JS, Markdown), але парсери ПОВИННІ мати суворі обмеження на виконання.

- **Active Content Ban**: Парсери НЕ ПОВИННІ виконувати JavaScript, VBScript, Java Applets або Flash, знайдений у тілі документів.

- **HTML Rendering**: Якщо споживач (UI) рендерить HTML з `.ark`:
  - MUST використовувати атрибут `sandbox` для iframes.
  - MUST застосовувати Content Security Policy (CSP): `default-src 'none'; style-src 'unsafe-inline'; img-src data:;`.
  - Тег `<script>` повинен бути автоматично екранований (`&lt;script&gt;`) або вирізаний.

### 3.3 Chain of Trust (Author Verification)

Для перевірки автентичності автора (поле `header.signature.pub_key`), система використовує децентралізований підхід:

- **Key Resolution**: Public Key може бути вирішений через DNS TXT record або відомий Key Transparency Log (аналог Certificate Transparency).
- **Format**: `ark-key=<base64-public-key>`.
- Якщо ключ у файлі не співпадає з ключем, опублікованим автором у довіреному джерелі, файл позначається як **UNTRUSTED**.

### 3.4 Update & Patching Mechanism

Файли `.ark` є **Immutable** (незмінними). Зміна одного байта ламає криптографічний підпис. Для оновлення даних використовується механізм **Differential Overlays (Patching)**.

#### 3.4.1 The "Delta Ark" Concept

Замість перезапису гігабайтного файлу, створюється новий, маленький `.ark` файл (Delta), який містить лише зміни.

**Структура Delta-файлу:**

1. **Linkage**: У header додається поле `parent_id` (UUID батьківського архіву).

2. **Sparse Data**:
   - Якщо поле присутнє в Delta, воно перезаписує поле батька.
   - Якщо поле відсутнє, використовується значення батька.
   - Для списків (наприклад, `docs`): Повна заміна (Replace strategy) є дефолтною поведінкою для уникнення конфліктів злиття (merge conflicts) на рівні індексів.

#### 3.4.2 Update Resolution Algorithm

Клієнт (Parser), що відкриває архів, повинен виконати наступне:

1. Завантажити `Base.ark`.
2. Перевірити наявність Update Manifest (зовнішній індекс або локальний файл `Base.ark.patch`).
3. Якщо знайдено `Delta.ark`:
   - Перевірити `Delta.header.parent_id == Base.header.id`.
   - Перевірити підпис Delta.
   - Накласти (Merge) JSON дерево Delta поверх Base в пам'яті.
4. Для векторів: Вектори завантажуються "lazy". Якщо запит йде до вектору ID=5, і він є в Delta — читаємо з Delta. Інакше — з Base.

Це дозволяє випускати "патчі" для RAG-баз (наприклад, "виправлення галюцинацій v1.1") розміром у кілобайти, не пересилаючи гігабайти ембеддингів.

---

## Section 4: Reference Implementation

### 4.1 The Universal Ingestor

Компонент **Universal Ingestion Layer** відповідає за перетворення хаосу зовнішніх форматів у порядок внутрішньої структури `.ark`.

#### 4.1.1 Normalization Philosophy: "Everything is Markdown"

Ми приймаємо аксіому: **Markdown (CommonMark Spec)** є проміжним представленням (IR) для всіх текстових даних.

**Чому не HTML чи XML?**

1. **LLM Native**: Сучасні мовні моделі (GPT-4, Claude, Llama) найкраще розуміють структуру тексту, розміченого саме через Markdown (`#`, `**`, `>`). Це зменшує кількість токенів на 30-40% порівняно з HTML/XML.

2. **Scannability**: Markdown читабельний для людини у "сирому" вигляді, що спрощує аудит даних.

**Правила трансляції:**

- **Structural Hierarchy**: Стилі Heading 1...Heading 6 (DOCX/ODT) або теги `<h1>...<h6>` (HTML) ПОВИННІ (MUST) конвертуватися у `#...######`.
- **Emphasis**: Жирний шрифт та курсив зберігаються. Підкреслення (Underline) конвертується у курсив або ігнорується (оскільки в MD немає нативного підкреслення).
- **Lists**: Вкладеність списків повинна зберігатися (відступи 4 пробіли).
- **Metadata Extraction**: Властивості файлу (Author, CreationDate, LastModified) витягуються з OLE/XML структур та зберігаються в окремий словник, а не в текст.

### 4.2 Architecture: The Driver Pattern

Архітектура базується на патерні **Chain of Responsibility** або **Driver Registry**.

#### 4.2.1 Format Detection Logic

Ми не довіряємо розширенню файлу.

1. **Magic Bytes Check**: Перші 2-16 байтів файлу зчитуються та порівнюються з базою сигнатур (через libmagic).

2. **MIME Normalization**: Отриманий MIME-type (напр. `application/vnd.openxmlformats-officedocument.wordprocessingml.document`) мапиться на внутрішній ідентифікатор драйвера (`docx`).

3. **Extension Fallback**: Тільки якщо MIME-type = `application/octet-stream` або `text/plain`, ми дивимося на розширення файлу як підказку.

4. **Text Fallback**: Якщо формат бінарний і невідомий, намагаємося витягнути printable strings (аналог UNIX команди `strings`).

#### 4.2.2 Robustness Strategy

- **Graceful Degradation**: Якщо драйвер `DocxDriver` не може розпарсити таблицю через битий XML, він повинен пропустити таблицю, залогувати WARNING, але повернути решту тексту. "Краще 90% даних, ніж 0%".

- **Encoding Hell**: Для текстових файлів (CSV, TXT) обов'язковий евристичний детект кодування (chardet). Дефолт `utf-8` працює лише у 50% випадків у реальному світі (legacy системи часто віддають `cp1251` або `latin-1`).

### 4.3 Format-Specific Handling Rules

#### A. Office Documents (DOCX, ODT)

- **Content**: Ітерація по параграфах (`<w:p>`).
- **Styles**: Мапинг внутрішніх назв стилів (які можуть бути локалізовані, напр. "Заголовок 1") на рівні ієрархії.
- **Images**:
  1. Витягнути blob зображення.
  2. Порахувати SHA-256.
  3. Зберегти в assets.
  4. Вставити в Markdown посилання: `![image desc](internal://<sha256>)`.

#### B. Tabular Data (CSV, XLSX)

Стратегія залежить від розміру (**"The 50-Row Rule"**):

- **Small Tables (<50 rows)**: Конвертуються у Markdown Table (`| col | col |`). Це дозволяє LLM бачити таблицю "візуально".

- **Large Tables (>50 rows)**: Markdown таблиці стають нечитабельними для LLM при великій ширині/довжині. Такі дані серіалізуються в список JSON-об'єктів:

```json
[{"col1": "val1", "col2": "val2"}, ...]
```

Цей блок вставляється в Markdown як код-блок: ` ```json ... ``` `.

#### C. Fixed Layout (PDF)

Найскладніший формат.

1. **Hybrid Approach**: Спочатку спробувати витягнути текстовий шар.

2. **Layout Analysis**: Визначити, чи є текст двоколонковим. Просте читання "зліва-направо, зверху-вниз" змішає дві колонки в одну "кашу".

3. **Whitespace preservation**: Надлишковий whitespace (вертикальний) має замінюватися на `\n\n` (новий параграф).

---

## Appendix A: Terminology & Conventions

- **MUST**, **SHOULD**, **MAY**: As per RFC 2119.
- **UUID**: Universally Unique Identifier (RFC 4122).
- **ISO 8601**: International date/time standard.
- **SPDX**: Software Package Data Exchange (license identifiers).
- **CommonMark**: Markdown specification (commonmark.org).
- **mmap**: Memory-mapped file I/O.
- **SIMD**: Single Instruction, Multiple Data.

---

## Appendix B: Future Considerations

1. **Binary Compression**: Optional ZSTD compression layer for Content block.
2. **Streaming API**: Support for progressive loading of large archives.
3. **Multi-signature**: Support for multiple signers (collaborative editing).
4. **Schema Evolution**: Backward-compatible schema versioning mechanism.
