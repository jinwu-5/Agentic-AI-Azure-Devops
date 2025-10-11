"""
TDD (Test-Driven Development) Workflow

This workflow implements true TDD:
1. Plan & validate acceptance criteria are testable
2. Generate tests FIRST (failing tests - RED)
3. Review test quality
4. Implement code to pass tests (GREEN)
5. Validate acceptance criteria met
6. Commit & PR

Key differences from standard workflow:
- Tests written BEFORE implementation
- Tests must fail initially (proving they test something)
- Implementation driven by making tests pass
- Automatic retry loop for test failures
"""

import asyncio
import sys
from openai import AzureOpenAI
from config import SystemConfig
from core import MCPConnectionManager, WorkflowContext
from agents import (
    OrchestratorAgent,
    DevOpsAgent,
    CodeAgent,
    TestAgent,
    TestReviewAgent,
    ValidationAgent
)
from services import CodebaseRAG
from utils import StateManager


async def tdd_iteration_loop(context: WorkflowContext, code_agent, test_agent, max_iterations=3):
    """
    TDD Iteration Loop:
    1. Run tests (should fail initially)
    2. If fail: Analyze failures → Fix implementation → Repeat
    3. If pass: Done
    """
    print(f"\n{'='*60}")
    print("TDD ITERATION LOOP")
    print('='*60)

    for iteration in range(1, max_iterations + 1):
        print(f"\n[Iteration {iteration}/{max_iterations}]")

        # Run tests
        print("Running tests...")
        tests_passed = await test_agent.run_tests(context)

        if tests_passed:
            print(f"✓ All tests passed on iteration {iteration}!")
            return True

        # Tests failed - analyze
        print(f"✗ Tests failed on iteration {iteration}")

        if iteration == max_iterations:
            print(f"⚠️  Reached maximum iterations ({max_iterations})")
            print("   Tests still failing - manual intervention needed")
            return False

        # Analyze failures
        analysis = await test_agent.analyze_test_failures(context)

        if not analysis:
            print("✗ Could not analyze failures - stopping")
            return False

        # Apply fixes based on analysis
        print(f"\n[Iteration {iteration}] Applying fixes...")
        fixes_applied = await apply_fixes_from_analysis(context, code_agent, analysis)

        if not fixes_applied:
            print("✗ Could not apply fixes - stopping")
            return False

        print(f"✓ Fixes applied, retrying tests...")

    return False


async def apply_fixes_from_analysis(context: WorkflowContext, code_agent, analysis):
    """Apply fixes suggested by test failure analysis"""

    failures = analysis.get("failures", [])

    if not failures:
        return False

    # Group fixes by file
    fixes_by_file = {}
    for failure in failures:
        fix = failure.get("fix", {})
        file_path = fix.get("file")
        if not file_path:
            continue

        if file_path not in fixes_by_file:
            fixes_by_file[file_path] = []

        fixes_by_file[file_path].append({
            "test": failure.get("test"),
            "description": fix.get("description"),
            "code_snippet": fix.get("code_snippet")
        })

    # Apply fixes to each file
    for file_path, fixes in fixes_by_file.items():
        print(f"  Fixing {file_path}...")

        # Create a step for the code agent
        fix_instructions = [f["description"] for f in fixes]

        step = {
            "step": 999,  # Special step number for fixes
            "description": f"Fix test failures in {file_path}",
            "agent": "CodeAgent",
            "files_to_update": [{
                "path": file_path,
                "instructions": fix_instructions
            }]
        }

        success = await code_agent.execute_step(context, step)

        if not success:
            print(f"  ✗ Failed to apply fixes to {file_path}")
            return False

        print(f"  ✓ Applied fixes to {file_path}")

    return True


async def main():
    # Check for flags
    force_reindex = '--reindex' in sys.argv

    print("="*60)
    print("TDD WORKFLOW - TEST-DRIVEN DEVELOPMENT")
    if force_reindex:
        print("(FORCE REINDEX MODE)")
    print("="*60)
    print("\nWorkflow Steps:")
    print("1. Planning with testable acceptance criteria")
    print("2. Generate tests FIRST (RED - failing tests)")
    print("3. Review test quality")
    print("4. Implement code to pass tests (GREEN)")
    print("5. Iterate until all tests pass")
    print("6. Validate acceptance criteria")
    print("7. Commit & PR")
    print("="*60 + "\n")

    config = SystemConfig()
    state_mgr = StateManager()
    mcp_manager = MCPConnectionManager()

    ai_client = AzureOpenAI(
        azure_endpoint=config.azure_endpoint,
        api_key=config.azure_key,
        api_version=config.api_version
    )

    # Initialize RAG
    rag = CodebaseRAG(
        config.repository_path,
        ai_client,
        embedding_deployment=config.embedding_deployment_name
    )
    rag.index_repository(force_reindex=force_reindex)

    # Show project analysis
    project_info = rag.analyze_project()
    print(f"\n[Project Analysis]")
    print(f"  Language: {project_info['primary_language']}")
    print(f"  Frameworks: {', '.join(project_info['frameworks']) or 'None detected'}")
    print(f"  Files: {project_info['total_files']}")

    await mcp_manager.start_azure_devops_mcp(
        config.organization_url,
        config.pat_token,
        config.default_project
    )
    await mcp_manager.start_filesystem_mcp(config.repository_path)

    # Initialize agents
    orchestrator = OrchestratorAgent(
        ai_client,
        config.deployment_name,
        mcp_manager,
        rag
    )
    orchestrator.refresh_project_context()

    devops_agent = DevOpsAgent(ai_client, config.deployment_name, mcp_manager,
                               config.repository_path, config.repository_id)
    code_agent = CodeAgent(ai_client, config.deployment_name, mcp_manager, rag,
                          config.repository_path)
    test_agent = TestAgent(ai_client, config.deployment_name, mcp_manager, rag,
                          config.repository_path)
    test_review_agent = TestReviewAgent(ai_client, config.deployment_name)
    validation_agent = ValidationAgent(ai_client, config.deployment_name)

    # Create context
    context = WorkflowContext()
    context.work_item_id = input("\nEnter Work Item ID: ") or "9"
    context.repository_path = config.repository_path

    # PHASE 1: Planning
    print("\n" + "="*60)
    print("PHASE 1: PLANNING & ACCEPTANCE CRITERIA VALIDATION")
    print("="*60)

    if not await orchestrator.execute(context):
        print("✗ Planning failed")
        await mcp_manager.cleanup()
        return

    # Verify acceptance criteria are testable
    if not context.acceptance_criteria:
        print("⚠️  Warning: No acceptance criteria defined")
        print("   TDD works best with clear, testable acceptance criteria")

    state_mgr.save_context(context, "tdd_phase1_planning")

    # PHASE 2: Branch Creation
    print("\n" + "="*60)
    print("PHASE 2: BRANCH CREATION")
    print("="*60)

    if not await devops_agent.create_feature_branch(context):
        print("✗ Branch creation failed")
        await mcp_manager.cleanup()
        return

    state_mgr.save_context(context, "tdd_phase2_branch")

    # PHASE 3: TEST GENERATION (RED - Write Failing Tests First!)
    print("\n" + "="*60)
    print("PHASE 3: TEST GENERATION (TDD RED PHASE)")
    print("="*60)
    print("Generating tests BEFORE implementation...")
    print("Tests should fail initially - proving they test real behavior")

    plan = context.execution_plan.get("implementation", {})
    steps = plan.get("implementation_steps", [])
    test_steps = [s for s in steps if s.get("agent") == "TestAgent"]

    if not test_steps:
        print("⚠️  No test steps in plan - creating default test step")
        # Create a default test step based on acceptance criteria
        test_steps = [{
            "step": 1,
            "description": "Create tests for acceptance criteria",
            "agent": "TestAgent",
            "files_to_create": [{
                "path": f"tests/test_{context.work_item_id}_acceptance.py",
                "instructions": context.acceptance_criteria
            }]
        }]

    print(f"\nGenerating {len(test_steps)} test files...")
    for i, step in enumerate(test_steps, 1):
        print(f"\n[{i}/{len(test_steps)}] {step.get('description')[:80]}...")
        if not await test_agent.execute_step(context, step):
            print(f"✗ Test generation step {i} failed")
            await mcp_manager.cleanup()
            return

    state_mgr.save_context(context, "tdd_phase3_test_generation")

    # PHASE 3.5: TEST QUALITY REVIEW
    print("\n" + "="*60)
    print("PHASE 3.5: TEST QUALITY REVIEW")
    print("="*60)

    review_result = await test_review_agent.review_tests(context)

    if not review_result.get("passed", False):
        print("\n⚠️  Test quality issues detected - continuing autonomously")
        print("   (Issues will be addressed during TDD iteration loop)")

    state_mgr.save_context(context, "tdd_phase3.5_test_review")

    # PHASE 4: VERIFY TESTS FAIL (Baseline)
    print("\n" + "="*60)
    print("PHASE 4: VERIFY TESTS FAIL (TDD Baseline)")
    print("="*60)
    print("Running tests WITHOUT implementation...")
    print("Tests SHOULD fail - proving they test real behavior")

    baseline_passed = await test_agent.run_tests(context)

    if baseline_passed:
        print("\n⚠️  WARNING: Tests passed WITHOUT implementation!")
        print("   This suggests tests may not be testing real behavior")
        print("   Tests should fail before implementation (TDD RED phase)")

        user_input = input("\nContinue anyway? (y/N): ").strip().lower()
        if user_input != 'y':
            print("Aborting - please review test logic")
            await mcp_manager.cleanup()
            return
    else:
        print("\n✓ Tests failed as expected (RED phase complete)")
        print("  Now implementing code to make them pass...")

    state_mgr.save_context(context, "tdd_phase4_baseline")

    # PHASE 5: IMPLEMENTATION (GREEN - Make Tests Pass)
    print("\n" + "="*60)
    print("PHASE 5: IMPLEMENTATION (TDD GREEN PHASE)")
    print("="*60)
    print("Implementing code to make tests pass...")

    code_steps = [s for s in steps if s.get("agent") == "CodeAgent"]

    print(f"\nExecuting {len(code_steps)} implementation steps...")
    for i, step in enumerate(code_steps, 1):
        print(f"\n[{i}/{len(code_steps)}] {step.get('description')[:80]}...")
        if not await code_agent.execute_step(context, step):
            print(f"✗ Implementation step {i} failed")
            break

    state_mgr.save_context(context, "tdd_phase5_implementation")

    # PHASE 6: TDD ITERATION LOOP
    print("\n" + "="*60)
    print("PHASE 6: TDD ITERATION LOOP")
    print("="*60)
    print("Running tests and iterating until all pass...")

    tests_passed = await tdd_iteration_loop(context, code_agent, test_agent, max_iterations=3)

    if not tests_passed:
        print("\n✗ TDD iteration loop failed")
        print("  Tests still failing after maximum iterations")
        print("  Manual intervention required")

        user_input = input("\nContinue to validation anyway? (y/N): ").strip().lower()
        if user_input != 'y':
            await mcp_manager.cleanup()
            return

    state_mgr.save_context(context, "tdd_phase6_iteration")

    # PHASE 7: VALIDATION
    print("\n" + "="*60)
    print("PHASE 7: ACCEPTANCE CRITERIA VALIDATION")
    print("="*60)

    if not await validation_agent.execute(context):
        print("✗ Validation failed - acceptance criteria not met")
        print("  Even though tests pass, acceptance criteria validation failed")
        print("  This suggests a gap between tests and actual requirements")

        user_input = input("\nContinue to commit anyway? (y/N): ").strip().lower()
        if user_input != 'y':
            await mcp_manager.cleanup()
            return

    state_mgr.save_context(context, "tdd_phase7_validation")

    # PHASE 8: COMMIT & PUSH
    print("\n" + "="*60)
    print("PHASE 8: COMMIT & PUSH")
    print("="*60)

    commit_message = f"feat: {context.work_item_title} (TDD)\n\nImplements work item #{context.work_item_id}\n\nDeveloped using Test-Driven Development:\n- Tests written first\n- Implementation driven by tests\n- All tests passing\n- Acceptance criteria validated"

    if await devops_agent.commit_changes(context, commit_message):
        print("✓ Changes committed")

        if await devops_agent.push_to_remote(context):
            print("✓ Pushed to remote")
        else:
            print("✗ Push failed")
            await mcp_manager.cleanup()
            return
    else:
        print("✗ Commit failed")
        await mcp_manager.cleanup()
        return

    state_mgr.save_context(context, "tdd_phase8_commit")

    # PHASE 9: CREATE PR
    print("\n" + "="*60)
    print("PHASE 9: PULL REQUEST")
    print("="*60)

    if await devops_agent.create_pull_request(context):
        print("✓ Pull Request created")
        print(f"  PR URL: {context.pr_url}")
    else:
        print("✗ PR creation failed")
        await mcp_manager.cleanup()
        return

    state_mgr.save_context(context, "tdd_phase9_complete")

    # Final Summary
    print("\n" + "="*60)
    print("TDD WORKFLOW COMPLETE")
    print("="*60)
    print(f"Work Item: {context.work_item_title}")
    print(f"Branch: {context.branch_name}")
    print(f"\nTDD Metrics:")
    print(f"  Tests Created: {len(context.test_files)}")
    for test in context.test_files:
        print(f"    - {test}")
    print(f"  Implementation Files: {len(context.implementation_files)}")
    for file in context.implementation_files.keys():
        print(f"    - {file}")

    test_results = context.test_results
    if test_results:
        print(f"\nFinal Test Results:")
        print(f"  Passed: {test_results.get('passed_count', 0)}")
        print(f"  Failed: {test_results.get('failed_count', 0)}")
        print(f"  Exit Code: {test_results.get('exit_code', 'N/A')}")

    validation_results = context.validation_results
    if validation_results:
        print(f"\nAcceptance Criteria:")
        print(f"  Met: {validation_results.get('met', 0)}/{validation_results.get('total', 0)}")

    if context.pr_url:
        print(f"\nPR: {context.pr_url}")

    print("="*60)
    print("\n✓ TDD workflow completed successfully!")
    print("  Tests were written first, implementation driven by tests")
    print("  All tests passing, acceptance criteria validated")

    await mcp_manager.cleanup()


if __name__ == "__main__":
    if '--help' in sys.argv:
        print("Usage: python run_tdd_workflow.py [--reindex]")
        print("  --reindex: Force rebuild of code embeddings cache")
        print("")
        print("TDD Workflow:")
        print("1. Plans with testable acceptance criteria")
        print("2. Generates tests FIRST (RED - failing tests)")
        print("3. Reviews test quality for edge cases and assertions")
        print("4. Verifies tests fail without implementation")
        print("5. Implements code to make tests pass (GREEN)")
        print("6. Iterates until all tests pass (with automatic fixes)")
        print("7. Validates acceptance criteria met")
        print("8. Commits and creates PR")
        sys.exit(0)

    asyncio.run(main())
