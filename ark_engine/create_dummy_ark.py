import json
import hashlib
from sentence_transformers import SentenceTransformer

# Config
filename = "demo.ark"
docs = [
    "Kovcheg is an offline AI knowledge container system.",
    "The .ark format is designed for long-term data preservation.",
    "Python is the primary language used for the Ark Engine backend.",
    "Week 3 of development focuses on RAG and API integration."
]

print("Generating embeddings...")
model = SentenceTransformer('all-MiniLM-L6-v2')
embeddings = model.encode(docs).tolist()

content = {
    "docs": docs,
    "embeddings": embeddings,
    "media": []
}

# Calculate Checksum
dumped = json.dumps(content, sort_keys=True).encode("utf-8")
checksum = hashlib.sha256(dumped).hexdigest()

ark_data = {
    "header": {
        "id": "mod-001",
        "title": "Kovcheg Manual",
        "author": "Architect",
        "created_at": "2023-10-27T10:00:00Z",
        "version": "1.0.0",
        "checksum": checksum,
        "license": "CC-BY-SA"
    },
    "metadata": {
        "language": "en",
        "categories": ["tech", "ai"],
        "tags": ["documentation", "mvp"],
        "locale": "en_US",
        "intended_use": "reference",
        "risk_level": "low"
    },
    "content": content,
    "signature_block": {},
    "update_manifest": {}
}

with open(filename, "w") as f:
    json.dump(ark_data, f, indent=2)

print(f"Successfully created {filename}")
