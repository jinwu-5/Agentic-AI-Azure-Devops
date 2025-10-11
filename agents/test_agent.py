from core import BaseAgent, WorkflowContext, AgentState
from typing import Dict, Any, List, Optional
import os
import subprocess
import re

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
    
    async def run_tests(self, context: WorkflowContext, test_file: Optional[str] = None) -> bool:
        """Execute tests using pytest"""
        test_target = test_file or "tests/"
        self.log(context, "Running tests", test_target)

        if not context.test_files:
            self.log(context, "No tests to run", "", True)
            context.test_results = {"passed": True, "exit_code": 0}
            return True

        print(f"\n{'='*60}")
        print("EXECUTING TESTS")
        print('='*60)

        # Check if pytest is available
        pytest_check = subprocess.run(
            ["python", "-m", "pytest", "--version"],
            cwd=self.repository_path,
            capture_output=True,
            text=True
        )

        if pytest_check.returncode != 0:
            print("⚠️  pytest not installed in target repository")
            print("   Tests created but not executed")
            print(f"   To run tests: cd {self.repository_path} && pip install pytest && pytest")
            context.test_results = {
                "passed": True,  # Don't fail workflow, just skip execution
                "exit_code": 0,
                "skipped": True,
                "message": "pytest not installed"
            }
            self.log(context, "Tests skipped", "pytest not available")
            return True

        # Run pytest
        try:
            # Try pytest first, fall back to python -m pytest
            result = subprocess.run(
                ["pytest", "-v", "--tb=short", "--color=yes", test_target],
                cwd=self.repository_path,
                capture_output=True,
                text=True,
                timeout=120
            )
        except FileNotFoundError:
            # pytest not in PATH, try python -m pytest
            try:
                result = subprocess.run(
                    ["python", "-m", "pytest", "-v", "--tb=short", "--color=yes", test_target],
                    cwd=self.repository_path,
                    capture_output=True,
                    text=True,
                    timeout=120
                )
            except Exception as e:
                print(f"✗ Failed to run pytest: {e}")
                print("  Make sure pytest is installed: pip install pytest")
                context.test_results = {
                    "passed": False,
                    "exit_code": -1,
                    "error": str(e)
                }
                return False
        except subprocess.TimeoutExpired:
            print("✗ Tests timed out after 120 seconds")
            context.test_results = {
                "passed": False,
                "exit_code": -1,
                "error": "Timeout"
            }
            return False
        except Exception as e:
            print(f"✗ Error running tests: {e}")
            context.test_results = {
                "passed": False,
                "exit_code": -1,
                "error": str(e)
            }
            return False

        # Parse results
        stdout = result.stdout
        stderr = result.stderr
        exit_code = result.returncode

        # Extract test counts
        passed_match = re.search(r'(\d+) passed', stdout)
        failed_match = re.search(r'(\d+) failed', stdout)
        error_match = re.search(r'(\d+) error', stdout)

        passed_count = int(passed_match.group(1)) if passed_match else 0
        failed_count = int(failed_match.group(1)) if failed_match else 0
        error_count = int(error_match.group(1)) if error_match else 0

        # Parse failure details
        failed_tests = self._parse_test_failures(stdout)

        context.test_results = {
            "passed": exit_code == 0,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "passed_count": passed_count,
            "failed_count": failed_count,
            "error_count": error_count,
            "failed_tests": failed_tests
        }

        # Print results
        print(stdout)
        if stderr:
            print("STDERR:", stderr)

        print('='*60)
        if exit_code == 0:
            print(f"✓ All tests passed ({passed_count} tests)")
        else:
            print(f"✗ Tests failed: {failed_count} failed, {error_count} errors, {passed_count} passed")
        print('='*60 + '\n')

        self.log(context, "Tests executed",
                f"Exit code: {exit_code}, Passed: {passed_count}, Failed: {failed_count}")

        return exit_code == 0

    def _parse_test_failures(self, pytest_output: str) -> List[Dict[str, Any]]:
        """Parse pytest output to extract failure details"""
        failures = []

        # Look for FAILED test cases
        failed_pattern = r'FAILED (.*?) - (.*?)(?:\n|$)'
        matches = re.finditer(failed_pattern, pytest_output)

        for match in matches:
            test_name = match.group(1)
            error_msg = match.group(2)
            failures.append({
                "test": test_name,
                "error": error_msg
            })

        return failures

    async def analyze_test_failures(self, context: WorkflowContext) -> Optional[Dict[str, Any]]:
        """Use AI to analyze why tests failed and suggest fixes"""
        test_results = context.test_results

        if not test_results or test_results.get("passed", False):
            return None

        failed_tests = test_results.get("failed_tests", [])
        stdout = test_results.get("stdout", "")

        if not failed_tests:
            return None

        self.log(context, "Analyzing failures", f"{len(failed_tests)} failed tests")

        print(f"\n{'='*60}")
        print("ANALYZING TEST FAILURES")
        print('='*60)

        # Get implementation files for context
        impl_summary = "\n\n".join([
            f"--- {path} ---\n{content[:500]}..."
            for path, content in context.implementation_files.items()
        ])

        system_prompt = """You are a senior developer analyzing test failures.

For each failed test, determine:
1. Root cause of the failure
2. Whether it's a bug in the implementation or a bug in the test
3. Specific code changes needed to fix it

Return JSON:
{
    "failures": [
        {
            "test": "test_file.py::test_name",
            "root_cause": "Brief explanation",
            "issue_type": "implementation_bug" | "test_bug" | "missing_feature",
            "fix": {
                "file": "path/to/file.py",
                "description": "Specific change needed",
                "code_snippet": "def fixed_function():\\n    return 'correct'"
            }
        }
    ],
    "summary": "Overall assessment of what went wrong"
}"""

        failures_text = '\n'.join([
            f"- {f['test']}: {f['error']}"
            for f in failed_tests
        ])

        user_prompt = f"""Analyze these test failures:

Failed Tests:
{failures_text}

Pytest Output:
{stdout[-2000:]}

Implementation:
{impl_summary}

Provide your analysis in JSON format."""

        try:
            ai_response = await self.call_ai(system_prompt, user_prompt,
                                            temperature=0.1, max_tokens=2500)
            analysis = self.extract_json(ai_response)

            if not analysis:
                print("✗ Failed to parse AI analysis")
                return None

            # Print analysis
            print(f"\nRoot Cause Analysis:")
            print(f"  {analysis.get('summary', 'No summary provided')}")
            print()

            for failure in analysis.get("failures", []):
                print(f"Test: {failure.get('test', 'Unknown')}")
                print(f"  Cause: {failure.get('root_cause', 'Unknown')}")
                print(f"  Type: {failure.get('issue_type', 'Unknown')}")
                fix = failure.get("fix", {})
                if fix:
                    print(f"  Fix: {fix.get('description', 'No description')}")
                    print(f"  File: {fix.get('file', 'Unknown')}")
                print()

            print('='*60 + '\n')

            self.log(context, "Failure analysis complete",
                    f"Analyzed {len(analysis.get('failures', []))} failures")

            return analysis

        except Exception as e:
            print(f"✗ Error during analysis: {e}")
            import traceback
            traceback.print_exc()
            return None
