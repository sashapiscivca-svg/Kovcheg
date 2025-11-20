import os
import json
import pytest
from pathlib import Path
from ark_engine.core.builder import ArkBuilder
from ark_engine.core.cleaners import TextCleaner
from ark_engine.core.chunker import TextChunker

@pytest.fixture
def raw_data_dir(tmp_path):
    d = tmp_path / "raw_data"
    d.mkdir()
    
    p1 = d / "hello.txt"
    p1.write_text("Hello World! This is a test document.", encoding="utf-8")
    
    p2 = d / "note.md"
    p2.write_text("# Header\n\nSome markdown content here.", encoding="utf-8")
    
    return d

def test_cleaner():
    raw = "Hello   World! \n\n\n Test"
    clean = TextCleaner.normalize(raw)
    assert clean == "Hello World!\n\nTest"

def test_chunker():
    text = "A" * 2000
    chunker = TextChunker(max_chars=1000)
    chunks = chunker.chunk(text)
    assert len(chunks) >= 2

def test_builder_pipeline(raw_data_dir, tmp_path):
    output_file = tmp_path / "test.ark.json"
    
    builder = ArkBuilder(
        input_dir=str(raw_data_dir),
        output_file=str(output_file),
        title="Test Module"
    )
    
    builder.build()
    
    assert output_file.exists()
    
    with open(output_file) as f:
        data = json.load(f)
        
    assert data['header']['title'] == "Test Module"
    assert data['header']['version'] == "1.0"
    assert len(data['header']['checksum']) == 64
    
    docs = data['content']['docs']
    embeddings = data['content']['embeddings']
    
    assert len(docs) > 0
    assert len(embeddings) == len(docs)
    assert len(embeddings[0]) == 384
