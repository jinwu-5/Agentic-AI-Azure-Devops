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
        files_to_create = self._normalize_file_entries(step.get("files_to_create"))
        files_to_update = self._normalize_file_entries(step.get("files_to_update"))

        self.log(context, f"Executing step {step_num}", description)
        context.current_state = AgentState.IMPLEMENTING

        if not files_to_create and not files_to_update:
            self.log(context, "No target files", "Step lacks files_to_create or files_to_update", False)
            return False

        rag_context = await self._get_rag_context(description)

        for entry in files_to_create:
            instructions = entry.get("instructions") or [description]
            success = await self.create_file(
                context,
                entry["path"],
                description,
                instructions,
                rag_context
            )
            if not success:
                return False

        for entry in files_to_update:
            instructions = entry.get("instructions") or [description]
            success = await self.update_file(
                context,
                entry["path"],
                description,
                instructions,
                rag_context
            )
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
                         instructions: List[str],
                         rag_context: str) -> bool:
        """Create a new file with AI-generated content"""
        self.log(context, "Creating file", file_path)
        
        structure = self.rag.get_project_structure()
        
        system_prompt = """You are an expert software engineer writing production-quality code.

Write COMPLETE, working code - not pseudocode or placeholders."""

        instructions_text = '\n'.join(f"- {item}" for item in instructions)

        user_prompt = f"""Create a complete implementation for this file:

File: {file_path}
Purpose: {description}

Work Item: {context.work_item_title}

Implementation Notes:
{instructions_text}

Project Context:
- File types in project: {list(structure['file_types'].keys())}

{rag_context}

Respond with ONLY the file content, no explanations."""

        try:
            code_content = await self.call_ai(system_prompt, user_prompt,
                                             temperature=0.3, max_tokens=2000)
            code_content = self._clean_ai_response(code_content)

            # Write file directly with Python (bypass MCP)
            full_path = os.path.join(self.repository_path, file_path)
            target_dir = os.path.dirname(full_path) or self.repository_path
            os.makedirs(target_dir, exist_ok=True)
            
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

    async def update_file(self, context: WorkflowContext,
                          file_path: str, description: str,
                          instructions: List[str],
                          rag_context: str) -> bool:
        """Update an existing file using AI-generated changes"""
        self.log(context, "Updating file", file_path)

        full_path = os.path.join(self.repository_path, file_path)
        if not os.path.exists(full_path):
            self.log(context, "File not found", file_path, False)
            return False

        try:
            with open(full_path, 'r') as f:
                current_content = f.read()
        except Exception as e:
            self.log(context, "Failed to read file", f"{file_path}: {e}", False)
            return False

        instructions_text = '\n'.join(f"- {item}" for item in instructions)

        structure = self.rag.get_project_structure()

        system_prompt = """You are an expert software engineer editing an existing file.
Apply the requested changes while preserving intended behaviour. Return the full updated file content."""

        user_prompt = f"""Update the existing file according to the following instructions:

File: {file_path}
Purpose: {description}

Work Item: {context.work_item_title}

Implementation Notes:
{instructions_text}

Current Content:
{current_content}

Project Context:
- File types in project: {list(structure['file_types'].keys())}

{rag_context}

Respond with ONLY the updated file content, no explanations."""

        try:
            updated_content = await self.call_ai(system_prompt, user_prompt,
                                                temperature=0.25, max_tokens=2500)
            updated_content = self._clean_ai_response(updated_content)

            with open(full_path, 'w') as f:
                f.write(updated_content)

            context.implementation_files[file_path] = updated_content
            self.log(context, "File updated", f"{file_path} ({len(updated_content)} chars)")
            print(f"✓ Updated: {full_path}")
            return True

        except Exception as e:
            print(f"✗ Error updating {file_path}: {e}")
            self.log(context, "Error updating file", str(e), False)
            return False

    def _clean_ai_response(self, content: str) -> str:
        """Strip markdown fences from AI responses"""
        if "```" not in content:
            return content

        in_code_block = False
        clean_lines: List[str] = []

        for line in content.splitlines():
            if line.strip().startswith('```'):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                clean_lines.append(line)

        if clean_lines:
            return '\n'.join(clean_lines)

        return content.replace('```', '')

    def _normalize_file_entries(self, files: Any) -> List[Dict[str, Any]]:
        """Normalize file entries from plan step"""
        normalized: List[Dict[str, Any]] = []
        if not files:
            return normalized

        if not isinstance(files, list):
            files = [files]

        for entry in files:
            if isinstance(entry, str):
                normalized.append({"path": entry, "instructions": []})
                continue

            if isinstance(entry, dict):
                path = entry.get("path") or entry.get("file") or entry.get("target")
                if not path:
                    continue
                instructions = entry.get("instructions", [])
                if isinstance(instructions, str):
                    instructions = [instructions]
                normalized.append({
                    "path": path,
                    "instructions": instructions
                })

        return normalized
