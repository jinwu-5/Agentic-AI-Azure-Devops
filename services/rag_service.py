"""
STEP 4: RAG Service - Simplified (No embeddings required)
"""

import os
from typing import List, Dict, Any
from pathlib import Path


class CodebaseRAG:
    """Simplified RAG - just indexes files without embeddings"""
    
    def __init__(self, repository_path: str, azure_client=None, persist_directory: str = None):
        self.repository_path = repository_path
        self.chunks = []
        print("[RAG] RAG System initialized (simplified mode - no embeddings)")
    
    def _should_index_file(self, file_path: str) -> bool:
        """Determine if a file should be indexed"""
        skip_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv'}
        skip_extensions = {'.pyc', '.png', '.jpg', '.pdf'}
        
        path = Path(file_path)
        if any(skip_dir in path.parts for skip_dir in skip_dirs):
            return False
        if path.suffix in skip_extensions:
            return False
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                f.read(100)
            return True
        except:
            return False
    
    def index_repository(self, force_reindex: bool = False) -> int:
        """Index all files"""
        print(f"\n[RAG] Indexing repository: {self.repository_path}")
        
        if self.chunks and not force_reindex:
            print(f"[RAG] Already indexed ({len(self.chunks)} files)")
            return len(self.chunks)
        
        self.chunks = []
        
        for root, dirs, files in os.walk(self.repository_path):
            for file in files:
                file_path = os.path.join(root, file)
                if self._should_index_file(file_path):
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        rel_path = os.path.relpath(file_path, self.repository_path)
                        self.chunks.append({
                            'file_path': rel_path,
                            'content': content,
                            'file_type': Path(rel_path).suffix
                        })
                    except:
                        pass
        
        print(f"[RAG] ✓ Indexed {len(self.chunks)} files")
        return len(self.chunks)
    
    def search(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """Simple keyword search"""
        results = []
        query_lower = query.lower()
        
        for chunk in self.chunks:
            if query_lower in chunk['content'].lower():
                results.append({
                    'content': chunk['content'][:500],
                    'file_path': chunk['file_path'],
                    'file_type': chunk['file_type']
                })
                if len(results) >= n_results:
                    break
        
        return results
    
    def get_project_structure(self) -> Dict[str, Any]:
        """Return project structure"""
        file_types = {}
        for chunk in self.chunks:
            ft = chunk['file_type']
            file_types[ft] = file_types.get(ft, 0) + 1
        
        return {
            "total_files": len(self.chunks),
            "file_types": file_types
        }
