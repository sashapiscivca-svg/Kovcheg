import pytest
from unittest.mock import MagicMock
from ark_engine.core.rag import ArkRAG
from ark_engine.core.models import ArkModule, ArkHeader, ArkMetadata, ArkContent

@pytest.fixture
def mock_module():
    
    return ArkModule(
        header=ArkHeader(
            id="123", title="Test", author="Me", created_at="Now", 
            version="1.0", checksum="abc", license="MIT"
        ),
        metadata=ArkMetadata(
            language="en", categories=[], tags=[], locale="en", 
            intended_use="test", risk_level="low"
        ),
        content=ArkContent(
            docs=["Apple is a fruit", "Mars is a planet"],
            embeddings=[[1.0, 0.0], [0.0, 1.0]] 
        )
    )

def test_rag_search(mock_module):
    rag = ArkRAG(mock_module)
    
    rag.model = MagicMock()
    rag.model.encode.return_value = [0.9, 0.1] 
    
    results = rag.search("query", top_k=1)
    assert len(results) == 1
    assert results[0][0] == "Apple is a fruit"
