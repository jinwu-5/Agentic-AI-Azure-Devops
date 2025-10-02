"""
STEP 2: Orchestrator Agent - With improved file organization
"""

from core import BaseAgent, WorkflowContext, AgentState
from services import CodebaseRAG
from typing import Dict, Any, List, Optional, Set
from pathlib import Path
import json
import html
import re
import os


class OrchestratorAgent(BaseAgent):
    """Orchestrator Agent - Coordinates the entire workflow"""
    
    def __init__(self, ai_client, deployment_name, mcp_manager, rag_service: Optional[CodebaseRAG] = None):
        super().__init__("Orchestrator", ai_client, deployment_name)
        self.mcp_manager = mcp_manager
        self.rag = rag_service
        self._project_context = self._build_project_context()

    def refresh_project_context(self):
        """Recompute project context (call after RAG re-index)"""
        self._project_context = self._build_project_context()

    def _build_project_context(self) -> Dict[str, Any]:
        """Gather repository context from RAG if available"""
        if not self.rag:
            return {
                "primary_language": "unknown",
                "total_files": 0,
                "file_types": {},
                "frameworks": []
            }

        try:
            analysis = self.rag.analyze_project()
            structure = self.rag.get_project_structure()
            file_types = structure.get("file_types", {})

            python_files = sorted({
                chunk['file_path']
                for chunk in self.rag.chunks
                if chunk['file_path'].endswith('.py')
            })
            sample_python_files = python_files[:10]
            python_dirs = sorted({
                str(Path(path).parent)
                for path in python_files
                if '/' in path
            })[:8]

            allowed_extensions = {
                (ext.lower() if isinstance(ext, str) else ext)
                for ext, count in file_types.items() if count > 0 and isinstance(ext, str)
            }

            return {
                "primary_language": analysis.get("primary_language", "unknown"),
                "frameworks": analysis.get("frameworks", []),
                "total_files": analysis.get("total_files", structure.get("total_files", 0)),
                "file_types": file_types,
                "allowed_extensions": allowed_extensions,
                "sample_python_files": sample_python_files,
                "python_directories": python_dirs
            }
        except Exception as exc:
            print(f"[Orchestrator] Failed to build project context: {exc}")
            return {
                "primary_language": "unknown",
                "total_files": 0,
                "file_types": {},
                "frameworks": [],
                "allowed_extensions": set(),
                "sample_python_files": [],
                "python_directories": []
            }
    
    async def execute(self, context: WorkflowContext) -> bool:
        """Main execution flow for orchestrator"""
        try:
            if not await self.fetch_work_item(context):
                return False
            
            if not await self.analyze_work_item(context):
                return False
            
            if not await self.create_execution_plan(context):
                return False
            
            self.log(context, "Orchestration complete", "Ready to execute plan", True)
            return True
            
        except Exception as e:
            self.log(context, "Orchestration failed", str(e), False)
            context.add_error(f"Orchestrator failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _clean_html(self, html_text: str) -> str:
        """Convert HTML to plain text"""
        if not html_text:
            return ""
        text = html.unescape(html_text)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    async def fetch_work_item(self, context: WorkflowContext) -> bool:
        """Fetch work item details from Azure DevOps"""
        self.log(context, "Fetching work item", f"ID: {context.work_item_id}")
        context.current_state = AgentState.ANALYZING
        
        try:
            work_item_id = int(context.work_item_id)
            
            result = await self.mcp_manager.call_tool(
                "azure_devops",
                "get_work_item",
                {"workItemId": work_item_id}
            )
            
            if "result" not in result:
                self.log(context, "Work item not found", context.work_item_id, False)
                return False
            
            mcp_result = result["result"]
            
            if "content" in mcp_result and isinstance(mcp_result["content"], list):
                if len(mcp_result["content"]) > 0:
                    content_item = mcp_result["content"][0]
                    if content_item.get("type") == "text":
                        work_item_json = content_item.get("text", "{}")
                        work_item_data = json.loads(work_item_json)
                        
                        fields = work_item_data.get("fields", {})
                        
                        context.work_item_title = fields.get("System.Title", "Untitled")
                        
                        description_html = fields.get("System.Description")
                        if description_html:
                            context.work_item_description = self._clean_html(description_html)
                        else:
                            context.work_item_description = "No description provided"
                        
                        acceptance_criteria = fields.get("Microsoft.VSTS.Common.AcceptanceCriteria")
                        if acceptance_criteria:
                            clean_ac = self._clean_html(acceptance_criteria)
                            if clean_ac:
                                context.work_item_description += f"\n\nAcceptance Criteria:\n{clean_ac}"
                        
                        created_by = fields.get("System.CreatedBy") or {}
                        assigned_to = fields.get("System.AssignedTo") or {}
                        
                        context.execution_plan["work_item_metadata"] = {
                            "id": work_item_data.get("id"),
                            "state": fields.get("System.State", "Unknown"),
                            "work_item_type": fields.get("System.WorkItemType", "Unknown"),
                            "created_by": created_by.get("displayName", "Unknown"),
                            "assigned_to": assigned_to.get("displayName", "Unassigned"),
                            "priority": fields.get("Microsoft.VSTS.Common.Priority"),
                            "story_points": fields.get("Microsoft.VSTS.Scheduling.StoryPoints"),
                        }
                        
                        self.log(context, "Work item fetched", f"{context.work_item_title}")
                        
                        print(f"\n{'='*60}")
                        print("WORK ITEM DETAILS")
                        print('='*60)
                        print(f"ID: {context.work_item_id}")
                        print(f"Title: {context.work_item_title}")
                        print(f"Type: {context.execution_plan['work_item_metadata']['work_item_type']}")
                        print(f"State: {context.execution_plan['work_item_metadata']['state']}")
                        print(f"Description: {context.work_item_description}")
                        print('='*60 + '\n')
                        
                        return True
            
            self.log(context, "Failed to parse work item", "Unexpected data structure", False)
            return False
            
        except Exception as e:
            self.log(context, "Failed to fetch work item", str(e), False)
            import traceback
            traceback.print_exc()
            return False
    
    async def analyze_work_item(self, context: WorkflowContext) -> bool:
        """Use AI to deeply analyze the work item"""
        self.log(context, "Analyzing work item", "Using AI analysis")
        
        system_prompt = """You are a senior software architect analyzing user stories.

Extract and analyze:
1. Technical requirements
2. Acceptance criteria (specific, testable)
3. Complexity (simple/medium/complex)
4. Risks and challenges
5. Implementation approach"""

        project_summary = (
            f"Primary language: {self._project_context.get('primary_language')}\n"
            f"Frameworks: {', '.join(self._project_context.get('frameworks', [])) or 'None'}\n"
            f"Total files indexed: {self._project_context.get('total_files')}\n"
            f"Common file types: {', '.join(self._project_context.get('file_types', {}).keys()) or 'Unknown'}"
        )

        python_dirs = '\n'.join(
            f"- {d}" for d in self._project_context.get('python_directories', [])
        ) or "- (no python directories detected)"

        user_prompt = f"""Analyze this work item:

Title: {context.work_item_title}

Description: {context.work_item_description}

Project Summary:
{project_summary}

Python module locations:
{python_dirs}

Provide analysis in JSON:
{{
    "summary": "Brief summary",
    "technical_requirements": ["req1", "req2"],
    "acceptance_criteria": ["criteria1", "criteria2"],
    "complexity": "simple|medium|complex",
    "risks": ["risk1"],
    "recommended_approach": "Implementation strategy",
    "estimated_files": ["src/styles/theme.css", "src/utils/themeToggle.js"]
}}"""

        try:
            ai_response = await self.call_ai(system_prompt, user_prompt, temperature=0.2)
            analysis = self.extract_json(ai_response)
            
            if not analysis:
                self.log(context, "Analysis failed", "Could not parse AI response", False)
                return False
            
            context.acceptance_criteria = analysis.get("acceptance_criteria", [])
            context.execution_plan["analysis"] = analysis
            
            self.log(context, "Analysis complete", 
                    f"Complexity: {analysis.get('complexity')}, "
                    f"Criteria: {len(context.acceptance_criteria)}")
            
            return True
            
        except Exception as e:
            self.log(context, "Analysis failed", str(e), False)
            import traceback
            traceback.print_exc()
            return False
    
    async def create_execution_plan(self, context: WorkflowContext) -> bool:
        """Create detailed execution plan with proper file organization"""
        self.log(context, "Creating execution plan", "Using AI planning")
        context.current_state = AgentState.PLANNING
        
        analysis = context.execution_plan.get("analysis", {})
        
        system_prompt = """You are a technical project manager creating execution plans.

Create actionable plans for specialized AI agents (DevOps, Code, Test).

IMPORTANT - File Organization:
- CSS files go in: src/styles/
- JavaScript/React files go in: src/components/ or src/utils/
- Test files go in: tests/
- Always use proper directory structure

Planning Output Requirements:
- Use "files_to_create" for brand new files and include an "instructions" array describing their purpose
- Use "files_to_update" for existing files, provide "path" plus bullet "instructions" outlining the exact edits
- Every CodeAgent step must reference at least one file in "files_to_create" or "files_to_update"""

        allowed_exts: Set[str] = self._project_context.get("allowed_extensions", set())
        if allowed_exts:
            system_prompt += (
                "\n\nProject constraints:\n"
                f"- Repository primary language: {self._project_context.get('primary_language')}\n"
                f"- Only propose changes using existing extensions: {', '.join(sorted(allowed_exts))}\n"
                "- Do not introduce file types or frameworks that are not already present"
            )

        sample_files = '\n'.join(
            f"- {path}" for path in self._project_context.get('sample_python_files', [])
        ) or "- (no python files detected)"
        python_dirs = '\n'.join(
            f"- {d}" for d in self._project_context.get('python_directories', [])
        ) or "- (no python directories detected)"

        user_prompt = f"""Create plan for:

Title: {context.work_item_title}
Description: {context.work_item_description}

Analysis:
{json.dumps(analysis, indent=2)}

Project Summary:
Primary language: {self._project_context.get('primary_language')}
Frameworks: {', '.join(self._project_context.get('frameworks', [])) or 'None'}
Total files indexed: {self._project_context.get('total_files')}
Common file types: {', '.join(self._project_context.get('file_types', {}).keys()) or 'Unknown'}

Python module directories to target:
{python_dirs}

Representative Python files:
{sample_files}

Provide plan in JSON with PROPER FILE PATHS:
{{
    "branch_name": "feature/story-{context.work_item_id}",
    "implementation_steps": [
        {{
            "step": 1,
            "description": "What to do",
            "agent": "CodeAgent",
            "files_to_create": [
                {{
                    "path": "presentation/theme_palettes.py",
                    "instructions": [
                        "Define LIGHT_THEME and DARK_THEME dictionaries with WCAG-compliant colours"
                    ]
                }}
            ],
            "files_to_update": [
                {{
                    "path": "presentation/web_ui.py",
                    "instructions": [
                        "Inject theme resolver helper into render flow",
                        "Add session-backed toggle endpoint"
                    ]
                }}
            ],
            "validation": "How to verify"
        }}
    ],
    "testing_strategy": {{
        "unit_tests": ["tests/test_theme_resolver.py"],
        "integration_tests": ["tests/test_web_ui.py"]
    }},
    "pr_description": "PR description"
}}"""

        try:
            ai_response = await self.call_ai(system_prompt, user_prompt, 
                                            temperature=0.2, max_tokens=3000)
            plan = self.extract_json(ai_response)
            
            if not plan:
                self.log(context, "Planning failed", "Could not parse AI response", False)
                return False

            plan = self._filter_plan_steps(plan)
            context.execution_plan["implementation"] = plan
            context.branch_name = plan.get("branch_name", f"feature/story-{context.work_item_id}")
            
            steps = plan.get("implementation_steps", [])
            self.log(context, "Execution plan created", 
                    f"{len(steps)} steps, Branch: {context.branch_name}")
            
            print(f"\n{'='*60}")
            print("EXECUTION PLAN SUMMARY")
            print('='*60)
            print(f"Branch: {context.branch_name}")
            print(f"Total Steps: {len(steps)}\n")
            
            for step in steps:
                print(f"  {step.get('step')}. {step.get('description')}")
                print(f"     Agent: {step.get('agent')}")
                create_entries = self._normalize_plan_file_entries(step.get('files_to_create'))
                update_entries = self._normalize_plan_file_entries(step.get('files_to_update'))
                if create_entries:
                    paths = ', '.join(entry['path'] for entry in create_entries)
                    print(f"     Create: {paths}")
                if update_entries:
                    paths = ', '.join(entry['path'] for entry in update_entries)
                    print(f"     Update: {paths}")
                print()
            
            print('='*60 + '\n')
            
            return True
            
        except Exception as e:
            self.log(context, "Planning failed", str(e), False)
            import traceback
            traceback.print_exc()
            return False

    def _filter_plan_steps(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Remove implementation steps targeting unsupported file types"""
        allowed_exts: Set[str] = self._project_context.get("allowed_extensions", set())
        steps = plan.get("implementation_steps", [])
        filtered_steps = []
        removed_steps = []
        repo_path = getattr(self.rag, "repository_path", None) if self.rag else None

        for step in steps:
            create_entries = self._normalize_plan_file_entries(step.get("files_to_create"))
            update_entries = self._normalize_plan_file_entries(step.get("files_to_update"))
            invalid_reasons: List[str] = []

            if step.get("agent") == "CodeAgent" and not (create_entries or update_entries):
                invalid_reasons.append("No files_to_create or files_to_update provided")

            for entry in create_entries:
                if not self._is_extension_allowed(entry["path"], allowed_exts):
                    invalid_reasons.append(f"Unsupported extension: {entry['path']}")

            for entry in update_entries:
                path = entry["path"]
                if not self._is_extension_allowed(path, allowed_exts):
                    invalid_reasons.append(f"Unsupported extension: {path}")
                    continue
                if repo_path and not os.path.exists(os.path.join(repo_path, path)):
                    invalid_reasons.append(f"File not found for update: {path}")

            if invalid_reasons:
                removed_steps.append({
                    "step": step.get("step"),
                    "reason": "; ".join(invalid_reasons)
                })
                continue

            filtered_steps.append(step)

        if removed_steps:
            print("[Orchestrator] Removed plan steps due to unsupported file types:")
            for info in removed_steps:
                print(f"  - Step {info['step']}: {info['reason']}")

        plan["implementation_steps"] = filtered_steps

        if not any(step.get("agent") == "CodeAgent" for step in filtered_steps):
            raise ValueError("Planning did not produce any CodeAgent steps within supported file types")

        return plan

    def _normalize_plan_file_entries(self, files: Any) -> List[Dict[str, Any]]:
        """Normalize file descriptors from the execution plan"""
        normalized: List[Dict[str, Any]] = []
        if not files:
            return normalized

        if not isinstance(files, list):
            files = [files]

        for entry in files:
            if isinstance(entry, str):
                normalized.append({"path": entry})
                continue

            if isinstance(entry, dict):
                path = entry.get("path") or entry.get("file") or entry.get("target")
                if not path:
                    continue
                instructions = entry.get("instructions")
                if isinstance(instructions, str):
                    instructions = [instructions]
                normalized.append({
                    "path": path,
                    "instructions": instructions or []
                })

        return normalized

    def _is_extension_allowed(self, path: str, allowed_exts: Set[str]) -> bool:
        if not allowed_exts:
            return True
        ext = os.path.splitext(path)[1].lower()
        if not ext:
            return True
        return ext in allowed_exts
    
    async def validate_completion(self, context: WorkflowContext) -> bool:
        """Validate completion against acceptance criteria"""
        self.log(context, "Validating completion", "Checking criteria")
        context.current_state = AgentState.VALIDATING
        return True
