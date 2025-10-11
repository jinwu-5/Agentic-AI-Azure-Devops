from core import BaseAgent, WorkflowContext
from typing import Dict, Any, List


class TestReviewAgent(BaseAgent):
    """Test Review Agent - Validates test quality and coverage"""

    def __init__(self, ai_client, deployment_name):
        super().__init__("TestReviewAgent", ai_client, deployment_name)

    async def review_tests(self, context: WorkflowContext) -> Dict[str, Any]:
        """Review generated tests for quality and completeness"""
        self.log(context, "Reviewing tests", f"Reviewing {len(context.test_files)} test files")

        if not context.test_files:
            return {
                "passed": False,
                "issues": ["No test files generated"],
                "suggestions": []
            }

        # Collect all test content
        test_contents = {}
        for test_file in context.test_files:
            if test_file in context.implementation_files:
                test_contents[test_file] = context.implementation_files[test_file]

        if not test_contents:
            return {
                "passed": False,
                "issues": ["Test files listed but no content found"],
                "suggestions": []
            }

        # Review each test file
        all_issues = []
        all_suggestions = []

        for test_file, content in test_contents.items():
            review = await self._review_test_file(context, test_file, content)
            all_issues.extend(review.get("issues", []))
            all_suggestions.extend(review.get("suggestions", []))

        # Check acceptance criteria coverage
        ac_coverage = await self._check_acceptance_criteria_coverage(context, test_contents)
        all_issues.extend(ac_coverage.get("issues", []))
        all_suggestions.extend(ac_coverage.get("suggestions", []))

        result = {
            "passed": len(all_issues) == 0,
            "issues": all_issues,
            "suggestions": all_suggestions,
            "total_tests_reviewed": len(test_contents)
        }

        # Log results
        print(f"\n{'='*60}")
        print("TEST REVIEW RESULTS")
        print('='*60)
        print(f"Tests Reviewed: {len(test_contents)}")
        print(f"Issues Found: {len(all_issues)}")
        print(f"Suggestions: {len(all_suggestions)}")

        if all_issues:
            print("\n❌ ISSUES:")
            for i, issue in enumerate(all_issues, 1):
                print(f"  {i}. {issue}")

        if all_suggestions:
            print("\n💡 SUGGESTIONS:")
            for i, suggestion in enumerate(all_suggestions, 1):
                print(f"  {i}. {suggestion}")

        if result["passed"]:
            print("\n✓ Test quality review passed")
        else:
            print("\n✗ Test quality review failed - address issues above")

        print('='*60 + '\n')

        self.log(context, "Test review complete",
                f"Passed: {result['passed']}, Issues: {len(all_issues)}")

        return result

    async def _review_test_file(self, context: WorkflowContext,
                                test_file: str, content: str) -> Dict[str, Any]:
        """Review a single test file for quality"""

        system_prompt = """You are a senior QA engineer reviewing test code quality.

Evaluate the test file for:

1. **Edge Case Coverage**: Tests should cover:
   - Happy path (valid inputs)
   - Invalid inputs (None, empty strings, wrong types)
   - Boundary conditions (min/max values, edge cases)
   - Error conditions (exceptions, failures)

2. **Assertion Quality**:
   - Specific assertions (not just "assert result")
   - Meaningful assertion messages
   - Testing expected values, not just existence

3. **Test Independence**:
   - No shared state between tests
   - Each test can run in isolation
   - Proper setup/teardown

4. **Test Naming**:
   - Descriptive test names that explain what's being tested
   - Format: test_<function>_<scenario>_<expected_outcome>

5. **Mock/Fixture Usage**:
   - External dependencies are mocked
   - Fixtures used appropriately for test data

Return JSON:
{
    "issues": ["Critical issue 1", "Critical issue 2"],
    "suggestions": ["Improvement suggestion 1"],
    "edge_cases_covered": ["case1", "case2"],
    "missing_edge_cases": ["missing_case1"]
}"""

        user_prompt = f"""Review this test file:

File: {test_file}

Content:
```python
{content}
```

Provide your review in JSON format."""

        try:
            ai_response = await self.call_ai(system_prompt, user_prompt,
                                            temperature=0.1, max_tokens=2000)
            review = self.extract_json(ai_response)

            if not review:
                return {
                    "issues": [f"Failed to parse AI review for {test_file}"],
                    "suggestions": []
                }

            # Prefix issues with file name
            issues = [f"[{test_file}] {issue}" for issue in review.get("issues", [])]
            suggestions = [f"[{test_file}] {s}" for s in review.get("suggestions", [])]

            return {
                "issues": issues,
                "suggestions": suggestions
            }

        except Exception as e:
            print(f"[TestReviewAgent] Error reviewing {test_file}: {e}")
            return {
                "issues": [f"Exception during review of {test_file}: {str(e)}"],
                "suggestions": []
            }

    async def _check_acceptance_criteria_coverage(self, context: WorkflowContext,
                                                  test_contents: Dict[str, str]) -> Dict[str, Any]:
        """Verify that tests cover all acceptance criteria"""

        if not context.acceptance_criteria:
            return {"issues": [], "suggestions": []}

        system_prompt = """You are a QA engineer verifying test coverage against acceptance criteria.

For each acceptance criterion, determine if the test files contain tests that validate it.

Return JSON:
{
    "coverage": [
        {
            "criterion": "Users can toggle between themes",
            "covered": true,
            "test_location": "test_theme_toggle.py::test_toggle_button_changes_theme"
        },
        {
            "criterion": "Theme persists across requests",
            "covered": false,
            "reason": "No test for localStorage persistence"
        }
    ]
}"""

        criteria_list = '\n'.join(f"{i+1}. {c}" for i, c in enumerate(context.acceptance_criteria))

        test_summary = ""
        for file, content in test_contents.items():
            # Show first 1000 chars of each test file
            preview = content[:1000] + ("..." if len(content) > 1000 else "")
            test_summary += f"\n\n{file}:\n{preview}"

        user_prompt = f"""Check if these tests cover all acceptance criteria:

Acceptance Criteria:
{criteria_list}

Test Files:
{test_summary}

Provide coverage analysis in JSON."""

        try:
            ai_response = await self.call_ai(system_prompt, user_prompt,
                                            temperature=0.1, max_tokens=2000)
            result = self.extract_json(ai_response)

            if not result or "coverage" not in result:
                return {
                    "issues": ["Failed to analyze acceptance criteria coverage"],
                    "suggestions": []
                }

            coverage = result["coverage"]
            uncovered = [c for c in coverage if not c.get("covered", False)]

            issues = []
            suggestions = []

            if uncovered:
                issues.append(f"Missing tests for {len(uncovered)} acceptance criteria:")
                for c in uncovered:
                    criterion = c.get("criterion", "Unknown")
                    reason = c.get("reason", "No reason provided")
                    issues.append(f"  - '{criterion}': {reason}")

            return {
                "issues": issues,
                "suggestions": suggestions
            }

        except Exception as e:
            print(f"[TestReviewAgent] Error checking AC coverage: {e}")
            return {
                "issues": [f"Exception during AC coverage check: {str(e)}"],
                "suggestions": []
            }

    async def improve_tests(self, context: WorkflowContext,
                          review_result: Dict[str, Any]) -> bool:
        """Ask AI to improve tests based on review feedback"""

        if review_result.get("passed", False):
            print("[TestReviewAgent] Tests already passed review, no improvements needed")
            return True

        issues = review_result.get("issues", [])
        suggestions = review_result.get("suggestions", [])

        if not issues and not suggestions:
            return True

        self.log(context, "Improving tests", f"Addressing {len(issues)} issues")

        # For now, we'll just report the issues
        # In a full implementation, this would regenerate tests with feedback
        print(f"[TestReviewAgent] Test improvements needed but auto-fix not implemented")
        print(f"[TestReviewAgent] Developer should address these {len(issues)} issues manually")

        return False
