#!/usr/bin/env python3
import json
import sys
from pathlib import Path
import jsonschema
import yaml

BASE = Path(__file__).resolve().parent.parent

SCHEMA_JSON = BASE / "spec" / "schema.json"

def load_schema():
    with open(SCHEMA_JSON, "r", encoding="utf-8") as f:
        return json.load(f)

def load_file(path):
    if path.endswith(".json"):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    if path.endswith(".yaml") or path.endswith(".yml"):
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    raise ValueError("Unsupported format")

def main():
    if len(sys.argv) != 2:
        print("Usage: validate.py file.ark.json")
        return 1

    file = sys.argv[1]
    schema = load_schema()
    data = load_file(file)

    try:
        jsonschema.validate(data, schema)
        print("VALID ✔")
    except jsonschema.ValidationError as e:
        print("INVALID ✖")
        print(e)
        return 2

if __name__ == "__main__":
    main()
