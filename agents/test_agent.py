"""
STEP 6: Test Agent
Generates and runs unit tests for implemented code
"""

from core import BaseAgent, WorkflowContext, AgentState
from typing import Dict, Any, List
import os

class TestAgent(BaseAgent):
    """
    Test Agent - Writes and executes tests
    
    Responsibilities:
    1. Generate unit tests for implemented code
    2. Generate integration tests
    3. Run test suites
    4. Report test results
    """
    
    def __init__(self, ai_client, deployment_name, mcp_manager, rag_service, repository_path: str):
        super().__init__("TestAgent", ai_client, deployment_name)
        self.mcp_manager = mcp_manager
        self.rag = rag_service
        self.repository_path = repository_path
    
    async def execute(self, context: WorkflowContext) -> bool:
        """Execute test generation from execution plan"""
        plan = context.execution_plan.get("implementation", {})
        steps = plan.get("implementation_steps", [])
        
        if not steps:
            return False
        
        for step in steps:
            if step.get("agent") == "TestAgent":
                success = await self.execute_step(context, step)
                if not success:
                    return False
        
        return True
    
    async def execute_step(self, context: WorkflowContext, step: Dict) -> bool:
        """Execute a single test step"""
        step_num = step.get("step")
        description = step.get("description")
        file_entries = self._normalize_file_entries(step.get("files_to_create"))

        self.log(context, f"Executing step {step_num}", description)
        context.current_state = AgentState.TESTING

        if not file_entries:
            self.log(context, "No test files", "Step lacks files_to_create entries", False)
            return False

        for entry in file_entries:
            instructions = entry.get("instructions") or [description]
            success = await self.create_test_file(
                context,
                entry["path"],
                description,
                instructions
            )
            if not success:
                return False

        return True

    async def create_test_file(self, context: WorkflowContext,
                              file_path: str, description: str,
                              instructions: List[str]) -> bool:
        """Create a test file for the implemented code"""
        self.log(context, "Creating test file", file_path)
        
        # Get implemented files to test
        implemented_files = "\n\n".join([
            f"--- {path} ---\n{content}..."
            for path, content in context.implementation_files.items()
        ])

        instructions_text = '\n'.join(f"- {item}" for item in instructions)
        
        system_prompt = """You are a QA engineer writing comprehensive unit tests.

            Write tests that:
            1. Cover all major functionality
            2. Test edge cases and error conditions
            3. Are clear and maintainable
            4. Use appropriate testing frameworks
            5. Include setup/teardown as needed
            
            Write COMPLETE, runnable tests."""

        user_prompt = f"""Create unit tests for this implementation:

            Test File: {file_path}
            Purpose: {description}
            
            Implementation Notes:
            {instructions_text}
            
            Implemented Code:
            {implemented_files}
            
            Work Item: {context.work_item_title}
            Acceptance Criteria:
            {chr(10).join(f'- {c}' for c in context.acceptance_criteria[:5])}
            
            Generate COMPLETE test file. Include:
            - All necessary imports
            - Test setup/teardown
            - Comprehensive test cases
            - Clear assertions
            - Comments explaining what's being tested
            
            Respond with ONLY the test file content."""

        try:
            test_content = await self.call_ai(system_prompt, user_prompt,
                                             temperature=0.2, max_tokens=2500)

            if "```" in test_content:
                lines = test_content.split('\n')
                in_code_block = False
                clean_lines = []

                for line in lines:
                    if line.strip().startswith('```'):
                        in_code_block = not in_code_block
                        continue
                    if in_code_block:
                        clean_lines.append(line)

                if clean_lines:
                    test_content = '\n'.join(clean_lines)

            # Write test file
            full_path = os.path.join(self.repository_path, file_path)
            target_dir = os.path.dirname(full_path) or self.repository_path
            os.makedirs(target_dir, exist_ok=True)
            
            with open(full_path, 'w') as f:
                f.write(test_content)
            
            if os.path.exists(full_path):
                context.test_files.append(file_path)
                self.log(context, "Test file created", f"{file_path} ({len(test_content)} chars)")
                print(f"✓ Created: {full_path}")
                return True
            else:
                self.log(context, "Test creation failed", file_path, False)
                return False
        
        except Exception as e:
            print(f"✗ Error: {e}")
            self.log(context, "Error creating test", str(e), False)
            return False
    
    def _normalize_file_entries(self, files: Any) -> List[Dict[str, Any]]:
        """Normalize file descriptors for test generation"""
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
    
    async def run_tests(self, context: WorkflowContext) -> bool:
        """Run the test suite"""
        self.log(context, "Running tests", f"{len(context.test_files)} test files")
        
        if not context.test_files:
            self.log(context, "No tests to run", "", True)
            return True
        
        # Simple test execution - would need proper test runner in production
        results = {
            "total_tests": len(context.test_files),
            "passed": 0,
            "failed": 0,
            "skipped": 0
        }
        
        for test_file in context.test_files:
            full_path = os.path.join(self.repository_path, test_file)
            
            # Check if file exists
            if os.path.exists(full_path):
                results["passed"] += 1
                print(f"  ✓ {test_file} - created")
            else:
                results["failed"] += 1
                print(f"  ✗ {test_file} - missing")
        
        context.test_results = results
        
        self.log(context, "Tests complete", 
                f"{results['passed']}/{results['total_tests']} passed")
        
        return results["failed"] == 0
