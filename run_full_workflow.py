"""
Run full workflow and save state at each major step
This is expensive but only needs to run once
"""

import asyncio
from openai import AzureOpenAI
from config import SystemConfig
from core import MCPConnectionManager, WorkflowContext
from agents import OrchestratorAgent, DevOpsAgent, CodeAgent
from services import CodebaseRAG
from utils import StateManager


async def main():
    print("="*60)
    print("FULL WORKFLOW - RUN ONCE, SAVE STATE")
    print("="*60)
    
    config = SystemConfig()
    state_mgr = StateManager()
    mcp_manager = MCPConnectionManager()
    
    ai_client = AzureOpenAI(
        azure_endpoint=config.azure_endpoint,
        api_key=config.azure_key,
        api_version=config.api_version
    )
    
    # Initialize
    rag = CodebaseRAG(config.repository_path, ai_client)
    rag.index_repository()
    
    await mcp_manager.start_azure_devops_mcp(
        config.organization_url,
        config.pat_token,
        config.default_project
    )
    await mcp_manager.start_filesystem_mcp(config.repository_path)
    
    orchestrator = OrchestratorAgent(ai_client, config.deployment_name, mcp_manager)
    devops_agent = DevOpsAgent(ai_client, config.deployment_name, mcp_manager, config.repository_path)
    code_agent = CodeAgent(ai_client, config.deployment_name, mcp_manager, rag, config.repository_path)
    
    # Create context
    context = WorkflowContext()
    context.work_item_id = "9"
    context.repository_path = config.repository_path
    
    # STEP 1: Orchestrator (EXPENSIVE - hits Azure DevOps + AI)
    print("\n[STEP 1] Running Orchestrator...")
    if await orchestrator.execute(context):
        state_mgr.save_context(context, "after_orchestrator")
        print("✓ State saved after orchestration")
    else:
        print("✗ Orchestrator failed")
        await mcp_manager.cleanup()
        return
    
    # STEP 2: DevOps creates branch (CHEAP - just git)
    print("\n[STEP 2] Creating branch...")
    if await devops_agent.create_feature_branch(context):
        state_mgr.save_context(context, "after_branch_creation")
        print("✓ State saved after branch creation")
    else:
        print("✗ Branch creation failed")
        await mcp_manager.cleanup()
        return
    
    print("\n" + "="*60)
    print("WORKFLOW STATE SAVED")
    print("="*60)
    print("\nYou can now test individual agents without re-running orchestrator:")
    print("  python test_code_agent.py")
    print("  python test_devops_agent.py")
    print("\nSaved states:")
    for state in state_mgr.list_saved_states():
        print(f"  - {state['filename']}: {state['work_item']} ({state['state']})")
    
    await mcp_manager.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
