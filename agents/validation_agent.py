from core import BaseAgent, WorkflowContext, AgentState
from typing import Dict, Any, List


class ValidationAgent(BaseAgent):
    """Validation Agent - Validates implementations against acceptance criteria"""

    def __init__(self, ai_client, deployment_name):
        super().__init__("ValidationAgent", ai_client, deployment_name)

    async def execute(self, context: WorkflowContext) -> bool:
        """Validate implementation against acceptance criteria"""
        self.log(context, "Validating implementation", "Checking acceptance criteria")
        context.current_state = AgentState.VALIDATING

        if not context.acceptance_criteria:
            print("[ValidationAgent] No acceptance criteria defined - skipping validation")
            return True

        if not context.implementation_files:
            print("[ValidationAgent] No implementation files - skipping validation")
            return True

        # Prepare implementation summary
        files_summary = self._summarize_implementation(context)

        # Use AI to validate each criterion
        validation_results = await self._validate_criteria(context, files_summary)

        if not validation_results:
            self.log(context, "Validation failed", "Could not parse AI response", False)
            return False

        # Check results
        met_criteria = [r for r in validation_results if r['status'] == 'MET']
        unmet_criteria = [r for r in validation_results if r['status'] == 'NOT_MET']
        partial_criteria = [r for r in validation_results if r['status'] == 'PARTIAL']

        print(f"\n{'='*60}")
        print("ACCEPTANCE CRITERIA VALIDATION")
        print('='*60)
        print(f"Total Criteria: {len(validation_results)}")
        print(f"✓ Met: {len(met_criteria)}")
        print(f"⚠ Partial: {len(partial_criteria)}")
        print(f"✗ Not Met: {len(unmet_criteria)}")
        print()

        for result in validation_results:
            status_symbol = "✓" if result['status'] == 'MET' else "⚠" if result['status'] == 'PARTIAL' else "✗"
            print(f"{status_symbol} {result['criterion']}")
            print(f"   {result['explanation']}")
            print()

        print('='*60 + '\n')

        # Store results in context
        context.validation_results = {
            'total': len(validation_results),
            'met': len(met_criteria),
            'partial': len(partial_criteria),
            'unmet': len(unmet_criteria),
            'details': validation_results
        }

        # Fail if any criteria are not met
        if unmet_criteria:
            self.log(context, "Validation failed",
                    f"{len(unmet_criteria)} criteria not met", False)
            return False

        # Warn if partial
        if partial_criteria:
            self.log(context, "Validation partial",
                    f"{len(partial_criteria)} criteria partially met")

        self.log(context, "Validation passed",
                f"{len(met_criteria)}/{len(validation_results)} criteria met")
        return True

    def _summarize_implementation(self, context: WorkflowContext) -> str:
        """Create a summary of implementation changes"""
        summary = "Implementation Changes:\n\n"

        # Include implementation files
        for file_path, content in context.implementation_files.items():
            summary += f"File: {file_path}\n"
            summary += f"Size: {len(content)} characters\n"

            # Show first 500 and last 500 chars
            if len(content) > 1000:
                preview = content[:500] + f"\n\n... ({len(content) - 1000} chars omitted) ...\n\n" + content[-500:]
            else:
                preview = content

            summary += f"Content:\n{preview}\n"
            summary += "---\n\n"

        # Include test files
        if context.test_files:
            summary += "\nTest Files Created:\n"
            for test_file in context.test_files:
                summary += f"  - {test_file}\n"
            summary += "\n"

        return summary

    async def _validate_criteria(self, context: WorkflowContext,
                                 files_summary: str) -> List[Dict[str, str]]:
        """Use AI to validate each acceptance criterion"""

        system_prompt = """You are a QA engineer validating implementations against acceptance criteria.

For each acceptance criterion, determine if the implementation meets it.

CRITICAL: Respond with ONLY valid JSON. No explanations before or after the JSON.

Response format - valid JSON array:
[
  {
    "criterion": "Users can toggle between dark and light themes via UI",
    "status": "MET",
    "explanation": "Brief explanation of why it's met/not met"
  }
]

Status values (use exactly one):
- "MET" - Implementation fully satisfies the criterion
- "NOT_MET" - Implementation does not address the criterion
- "PARTIAL" - Implementation partially addresses the criterion but is incomplete

Return ONLY the JSON array, nothing else."""

        criteria_list = '\n'.join(f"{i+1}. {c}" for i, c in enumerate(context.acceptance_criteria))

        user_prompt = f"""Validate this implementation against the acceptance criteria:

Work Item: {context.work_item_title}

Acceptance Criteria:
{criteria_list}

{files_summary}

For each criterion, determine if the implementation meets it and provide your response in JSON format."""

        try:
            ai_response = await self.call_ai(system_prompt, user_prompt,
                                            temperature=0.1, max_tokens=2000)

            # Extract JSON from response (handle markdown code blocks)
            import json
            import re

            # Try to extract JSON from markdown code blocks
            json_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', ai_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find JSON array directly
                json_match = re.search(r'(\[.*\])', ai_response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_str = ai_response

            # Parse JSON
            try:
                results = json.loads(json_str)
            except json.JSONDecodeError as je:
                print(f"[ValidationAgent] JSON parsing error: {je}")
                print(f"[ValidationAgent] AI Response: {ai_response[:500]}")
                return []

            if not results or not isinstance(results, list):
                print(f"[ValidationAgent] Response is not a valid list")
                print(f"[ValidationAgent] Type: {type(results)}")
                return []

            return results

        except Exception as e:
            print(f"[ValidationAgent] Error during validation: {e}")
            import traceback
            traceback.print_exc()
            return []
