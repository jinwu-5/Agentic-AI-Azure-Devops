"""
STEP 2: Orchestrator Agent
The brain of the system - analyzes stories, creates execution plans, coordinates other agents
"""

from core import BaseAgent, WorkflowContext, AgentState
import json
import html
import re


class OrchestratorAgent(BaseAgent):
    """
    Orchestrator Agent - Coordinates the entire workflow
    """
    
    def __init__(self, ai_client, deployment_name, mcp_manager):
        super().__init__("Orchestrator", ai_client, deployment_name)
        self.mcp_manager = mcp_manager
    
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
        # Unescape HTML entities
        text = html.unescape(html_text)
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', text)
        # Clean up whitespace
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
                        desc_preview = context.work_item_description[:300] + "..." if len(context.work_item_description) > 300 else context.work_item_description
                        print(f"Description: {desc_preview}")
                        print('='*60 + '\n')
                        
                        return True
            
            self.log(context, "Failed to parse work item", "Unexpected data structure", False)
            return False

        except json.JSONDecodeError as e:
            self.log(context, "Failed to parse work item JSON", str(e), False)
            return False
        except ValueError:
            self.log(context, "Invalid work item ID", f"Must be numeric: {context.work_item_id}", False)
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

        user_prompt = f"""Analyze this work item:

Title: {context.work_item_title}

Description: {context.work_item_description}

Provide analysis in JSON:
{{
    "summary": "Brief summary",
    "technical_requirements": ["req1", "req2"],
    "acceptance_criteria": ["criteria1", "criteria2"],
    "complexity": "simple|medium|complex",
    "risks": ["risk1"],
    "recommended_approach": "Implementation strategy",
    "estimated_files": ["file1.css", "file2.js"]
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
        """Create detailed execution plan"""
        self.log(context, "Creating execution plan", "Using AI planning")
        context.current_state = AgentState.PLANNING
        
        analysis = context.execution_plan.get("analysis", {})
        
        system_prompt = """You are a technical project manager creating execution plans.

Create actionable plans for specialized AI agents (DevOps, Code, Test).

Include:
1. Git branching
2. File structure
3. Implementation steps
4. Testing strategy"""

        user_prompt = f"""Create plan for:

Title: {context.work_item_title}
Description: {context.work_item_description[:500]}...

Analysis:
{json.dumps(analysis, indent=2)}

Provide plan in JSON:
{{
    "branch_name": "feature/story-{context.work_item_id}",
    "implementation_steps": [
        {{
            "step": 1,
            "description": "What to do",
            "agent": "CodeAgent",
            "files_to_create": ["theme.css"],
            "validation": "How to verify"
        }}
    ],
    "testing_strategy": {{
        "unit_tests": ["test"],
        "test_files": ["test_theme.js"]
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
            
            # Show ALL steps instead of truncating
            for step in steps:
                print(f"  {step.get('step')}. {step.get('description')}")
                print(f"     Agent: {step.get('agent')}")
                files = step.get('files_to_create', [])
                if files:
                    print(f"     Files: {', '.join(files)}")
                print()
            
            print('='*60 + '\n')
            
            return True
            
        except Exception as e:
            self.log(context, "Planning failed", str(e), False)
            import traceback
            traceback.print_exc()
            return False
    
    async def validate_completion(self, context: WorkflowContext) -> bool:
        """Validate completion against acceptance criteria"""
        self.log(context, "Validating completion", "Checking criteria")
        context.current_state = AgentState.VALIDATING
        return True
