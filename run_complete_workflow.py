"""
Complete end-to-end workflow:
Orchestrate → Branch → Implement → Test → Commit → Push → PR
"""

import asyncio
from openai import AzureOpenAI
from config import SystemConfig
from core import MCPConnectionManager, WorkflowContext
from agents import OrchestratorAgent, DevOpsAgent, CodeAgent, TestAgent
from services import CodebaseRAG
from utils import StateManager


async def main():
    print("="*60)
    print("COMPLETE WORKFLOW - ORCHESTRATE TO PR")
    print("="*60)
    
    config = SystemConfig()
    state_mgr = StateManager()
    mcp_manager = MCPConnectionManager()
    
    ai_client = AzureOpenAI(
        azure_endpoint=config.azure_endpoint,
        api_key=config.azure_key,
        api_version=config.api_version
    )
    
    # Initialize services
    rag = CodebaseRAG(config.repository_path, ai_client)
    rag.index_repository()
    
    await mcp_manager.start_azure_devops_mcp(
        config.organization_url,
        config.pat_token,
        config.default_project
    )
    await mcp_manager.start_filesystem_mcp(config.repository_path)
    
    # Initialize agents
    orchestrator = OrchestratorAgent(ai_client, config.deployment_name, mcp_manager)
    devops_agent = DevOpsAgent(ai_client, config.deployment_name, mcp_manager, config.repository_path)
    code_agent = CodeAgent(ai_client, config.deployment_name, mcp_manager, rag, config.repository_path)
    test_agent = TestAgent(ai_client, config.deployment_name, mcp_manager, rag, config.repository_path)
    
    # Create context
    context = WorkflowContext()
    context.work_item_id = input("Enter Work Item ID: ") or "9"
    context.repository_path = config.repository_path
    
    # PHASE 1: Planning
    print("\n" + "="*60)
    print("PHASE 1: PLANNING")
    print("="*60)
    if not await orchestrator.execute(context):
        print("✗ Planning failed")
        await mcp_manager.cleanup()
        return
    state_mgr.save_context(context, "phase1_planning")
    
    # PHASE 2: Branch Creation
    print("\n" + "="*60)
    print("PHASE 2: BRANCH CREATION")
    print("="*60)
    if not await devops_agent.create_feature_branch(context):
        print("✗ Branch creation failed")
        await mcp_manager.cleanup()
        return
    state_mgr.save_context(context, "phase2_branch")
    
    # PHASE 3: Implementation
    print("\n" + "="*60)
    print("PHASE 3: IMPLEMENTATION")
    print("="*60)
    
    plan = context.execution_plan.get("implementation", {})
    steps = plan.get("implementation_steps", [])
    code_steps = [s for s in steps if s.get("agent") == "CodeAgent"]
    
    print(f"Executing {len(code_steps)} implementation steps...")
    for i, step in enumerate(code_steps, 1):
        print(f"\n[{i}/{len(code_steps)}] {step.get('description')[:80]}...")
        if not await code_agent.execute_step(context, step):
            print(f"✗ Step {i} failed")
            break
    
    state_mgr.save_context(context, "phase3_implementation")
    
    # PHASE 4: Testing
    print("\n" + "="*60)
    print("PHASE 4: TESTING")
    print("="*60)
    
    test_steps = [s for s in steps if s.get("agent") == "TestAgent"]
    print(f"Executing {len(test_steps)} test steps...")
    for i, step in enumerate(test_steps, 1):
        print(f"\n[{i}/{len(test_steps)}] {step.get('description')[:80]}...")
        if not await test_agent.execute_step(context, step):
            print(f"✗ Test step {i} failed")
            break
    
    await test_agent.run_tests(context)
    state_mgr.save_context(context, "phase4_testing")
    
    # PHASE 5: Commit & Push
    print("\n" + "="*60)
    print("PHASE 5: COMMIT & PUSH")
    print("="*60)
    
    commit_message = f"feat: {context.work_item_title}\n\nImplements work item #{context.work_item_id}"
    if await devops_agent.commit_changes(context, commit_message):
        print("✓ Changes committed")
        
        # Ask before pushing
        response = input("\nPush to remote? (y/n): ")
        if response.lower() == 'y':
            if await devops_agent.push_to_remote(context):
                print("✓ Pushed to remote")
            else:
                print("✗ Push failed")
    else:
        print("✗ Commit failed")
    
    state_mgr.save_context(context, "phase5_commit")
    
    # PHASE 6: Create PR
    print("\n" + "="*60)
    print("PHASE 6: PULL REQUEST")
    print("="*60)
    
    response = input("\nCreate Pull Request? (y/n): ")
    if response.lower() == 'y':
        if await devops_agent.create_pull_request(context):
            print("✓ Pull Request created")
            print(f"  PR URL: {context.pr_url}")
        else:
            print("✗ PR creation failed")
    
    state_mgr.save_context(context, "phase6_complete")
    
    # Final Summary
    print("\n" + "="*60)
    print("WORKFLOW COMPLETE")
    print("="*60)
    print(f"Work Item: {context.work_item_title}")
    print(f"Branch: {context.branch_name}")
    print(f"Files Created: {len(context.implementation_files)}")
    for file in context.implementation_files.keys():
        print(f"  - {file}")
    print(f"Tests Created: {len(context.test_files)}")
    for test in context.test_files:
        print(f"  - {test}")
    if context.pr_url:
        print(f"PR: {context.pr_url}")
    print("="*60)
    
    await mcp_manager.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
