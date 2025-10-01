"""
STEP 5: Code Agent - Using direct file operations instead of MCP
"""

from core import BaseAgent, WorkflowContext, AgentState
from typing import Dict, Any, List
import os


class CodeAgent(BaseAgent):
    """Code Agent - Writes implementation code"""
    
    def __init__(self, ai_client, deployment_name, mcp_manager, rag_service, repository_path: str):
        super().__init__("CodeAgent", ai_client, deployment_name)
        self.mcp_manager = mcp_manager
        self.rag = rag_service
        self.repository_path = repository_path
    
    async def execute(self, context: WorkflowContext) -> bool:
        """Execute full implementation from execution plan"""
        plan = context.execution_plan.get("implementation", {})
        steps = plan.get("implementation_steps", [])
        
        if not steps:
            self.log(context, "No implementation steps", "Plan is empty", False)
            return False
        
        for step in steps:
            if step.get("agent") == "CodeAgent":
                success = await self.execute_step(context, step)
                if not success:
                    return False
        
        return True
    
    async def execute_step(self, context: WorkflowContext, step: Dict) -> bool:
        """Execute a single implementation step"""
        step_num = step.get("step")
        description = step.get("description")
        files_to_create = step.get("files_to_create", [])
        
        self.log(context, f"Executing step {step_num}", description)
        context.current_state = AgentState.IMPLEMENTING
        
        rag_context = await self._get_rag_context(description)
        
        for file_path in files_to_create:
            success = await self.create_file(context, file_path, description, rag_context)
            if not success:
                return False
        
        return True
    
    async def _get_rag_context(self, description: str) -> str:
        """Get relevant code context from RAG"""
        results = self.rag.search(description, n_results=3)
        
        if not results:
            return "No existing code patterns found."
        
        context = "Existing code patterns in the repository:\n\n"
        for i, result in enumerate(results, 1):
            context += f"--- Pattern {i}: {result['file_path']} ---\n"
            context += result['content'][:300] + "...\n\n"
        
        return context
    
    async def create_file(self, context: WorkflowContext, 
                         file_path: str, description: str, 
                         rag_context: str) -> bool:
        """Create a new file with AI-generated content"""
        self.log(context, "Creating file", file_path)
        
        structure = self.rag.get_project_structure()
        
        system_prompt = """You are an expert software engineer writing production-quality code.

Write COMPLETE, working code - not pseudocode or placeholders."""

        user_prompt = f"""Create a complete implementation for this file:

File: {file_path}
Purpose: {description}

Work Item: {context.work_item_title}

Project Context:
- File types in project: {list(structure['file_types'].keys())}

{rag_context}

Respond with ONLY the file content, no explanations."""

        try:
            code_content = await self.call_ai(system_prompt, user_prompt, 
                                             temperature=0.3, max_tokens=2000)
            
            # Clean up markdown code blocks
            if "```" in code_content:
                lines = code_content.split('\n')
                in_code_block = False
                clean_lines = []
                
                for line in lines:
                    if line.strip().startswith('```'):
                        in_code_block = not in_code_block
                        continue
                    if in_code_block or not code_content.count('```'):
                        clean_lines.append(line)
                
                code_content = '\n'.join(clean_lines)
            
            # Write file directly with Python (bypass MCP)
            full_path = os.path.join(self.repository_path, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            
            with open(full_path, 'w') as f:
                f.write(code_content)
            
            # Verify
            if os.path.exists(full_path):
                context.implementation_files[file_path] = code_content
                self.log(context, "File created", f"{file_path} ({len(code_content)} chars)")
                print(f"✓ Created: {full_path}")
                return True
            else:
                self.log(context, "File creation failed", file_path, False)
                return False
        
        except Exception as e:
            print(f"✗ Error: {e}")
            self.log(context, "Error creating file", str(e), False)
            return False
