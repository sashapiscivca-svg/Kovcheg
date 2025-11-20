# Kovcheg Archive Format (.ark)

**The Universal AI-Native Container for Long-Term Data Preservation**

Проєкт "Ковчег" представляє формат .ark — гібридний бінарний стандарт, розроблений для уніфікації різнорідних даних (текст, документи, медіа) у форму, оптимізовану для RAG (Retrieval-Augmented Generation), навчання LLM та архівного зберігання.

---

## ⚡ Key Features

### Universal Ingestion ("The Monster")

- Поглинає будь-який вхідний формат (DOCX, PDF, HTML, CSV)
- Нормалізує контент у Semantic Markdown — рідну мову LLM
- Зберігає структуру (заголовки, таблиці) та метадані

### AI-Ready Architecture

- **Zero-Copy Embeddings**: Вектори (float32 arrays) зберігаються бінарно та вирівняні для mmap. Завантаження мільйонів векторів у пам'ять займає мілісекунди
- **Knowledge Graph**: Вбудована підтримка семантичних триплетів (Subject-Predicate-Object)

### Immutable & Secure

- **Cryptographic Integrity**: Кожен файл підписаний (Ed25519) і містить SHA-256 хеш контенту
- **Self-Contained**: Ліцензія, мовні теги та provenance-дані "зашиті" у файл. Жодних зовнішніх залежностей

---

## 📐 Logical Data Model

Формат .ark складається з трьох логічних блоків:

```
classDiagram
    class ArkFile {
        +Header header
        +Metadata metadata
        +Content content
    }
    class Header {
        UUID id
        SemVer version
        Timestamp created_at
        SHA256 checksum
        Ed25519Signature signature
    }
    class Metadata {
        BCP47 language
        RiskLevel risk_level
        Provenance source
    }
    class Content {
        List~Doc~ docs
        List~Tensor~ embeddings
        List~Triple~ graph
    }
    ArkFile *-- Header
    ArkFile *-- Metadata
    ArkFile *-- Content
```

- **Header**: Паспорт файлу. Зміна одного байта в контенті інвалідує підпис
- **Metadata**: Контекст для фільтрації (мова, рівень токсичності, джерело)
- **Content**: Payload. Текст (Markdown), Вектори (Binary), Граф (Triples)

---

## 💾 Physical Layout (On-Disk)

Файл оптимізований для швидкого читання. Метадані — це JSON для зручності парсингу людиною/інструментами, а важкі дані — це Raw Binary.

```
+-----------------------+  <-- Offset 0x00
| Magic Bytes (ARK\1)   |
+-----------------------+
| Manifest Length (u64) |
+-----------------------+
|                       |
|    JSON MANIFEST      |  <-- Header + Metadata + Text Content
|  (Canonical Structure)|
|                       |
+-----------------------+
|    Zero Padding       |  <-- Aligns next block to 64-byte boundary
+-----------------------+
|                       |
|    BINARY PAYLOAD     |  <-- Embeddings & Media Blobs
|   (mmap-able area)    |      (Packed Float32 arrays)
|                       |
+-----------------------+  <-- EOF
```

---

## 🚀 Quick Start (Python SDK)

### Installation

```bash
pip install kovcheg-core
```

### Reading an Archive

```python
from kovcheg.core import ArkReader

# Lazy loading: reads only header JSON, maps vectors
with ArkReader("dataset/history_v1.ark") as ark:
    print(f"ID: {ark.header.id}")
    print(f"License: {ark.header.license}")
    
    # Zero-copy access to embeddings (numpy view)
    vectors = ark.content.embeddings.numpy() 
    print(f"Loaded {vectors.shape[0]} vectors instantly.")
```

### Creating an Archive (Ingestion)

```python
from kovcheg.ingest import IngestionEngine, ArkWriter

engine = IngestionEngine()
result = engine.ingest("raw_data/report.docx")

writer = ArkWriter(
    author="Kovcheg Team",
    license="CC-BY-4.0"
)
writer.add_document(result)
writer.compute_embeddings(model="openai/text-embedding-3-small")
writer.save("processed/report.ark")
```

---

## 🛡️ Security Model

- **Validation**: Всі файли валідуються за суворою JSON Schema
- **Sanitization**: Активний контент (`<script>`, макроси) вирізається на етапі Ingestion
- **Trust**: Ланцюжок довіри базується на публічних ключах авторів

---

## 📚 Documentation

- **Specification v0.1 (Full RFC)** — Детальний опис бітів та полів
- **Schema Definitions** — JSON Schema & K8s CRD
- **Ingestion Rules** — Як ми перетворюємо DOCX/PDF у Markdown

---

**Project Kovcheg. Preserving Knowledge. 2025.**
