"""
Test Code Agent - Execute ALL code steps
"""

import asyncio
from openai import AzureOpenAI
from config import SystemConfig
from core import MCPConnectionManager
from agents import CodeAgent
from services import CodebaseRAG
from utils import StateManager


async def main():
    print("="*60)
    print("TEST CODE AGENT - All Steps")
    print("="*60)
    
    config = SystemConfig()
    state_mgr = StateManager()
    mcp_manager = MCPConnectionManager()
    
    print("\nLoading saved state...")
    context = state_mgr.load_context("after_orchestrator")
    
    ai_client = AzureOpenAI(
        azure_endpoint=config.azure_endpoint,
        api_key=config.azure_key,
        api_version=config.api_version
    )
    
    rag = CodebaseRAG(config.repository_path, ai_client)
    rag.index_repository()
    
    await mcp_manager.start_filesystem_mcp(config.repository_path)
    
    code_agent = CodeAgent(ai_client, config.deployment_name, mcp_manager, rag, config.repository_path)
    
    # Get ALL code steps
    plan = context.execution_plan.get("implementation", {})
    steps = plan.get("implementation_steps", [])
    code_steps = [s for s in steps if s.get("agent") == "CodeAgent"]
    
    print(f"\nFound {len(code_steps)} code steps to execute\n")
    
    successful = 0
    failed = 0
    
    for i, step in enumerate(code_steps, 1):
        print(f"\n{'='*60}")
        print(f"STEP {i}/{len(code_steps)}")
        print('='*60)
        print(f"Description: {step.get('description')[:100]}...")
        print(f"Files: {', '.join(step.get('files_to_create', []))}")
        
        success = await code_agent.execute_step(context, step)
        
        if success:
            successful += 1
            print(f"✓ Step {i} completed")
        else:
            failed += 1
            print(f"✗ Step {i} failed")
            
            # Ask if user wants to continue
            response = input("\nContinue to next step? (y/n): ")
            if response.lower() != 'y':
                break
    
    # Save final state
    state_mgr.save_context(context, "after_all_code_steps")
    
    # Summary
    print(f"\n{'='*60}")
    print("EXECUTION SUMMARY")
    print('='*60)
    print(f"Total steps: {len(code_steps)}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"\nFiles created:")
    for file_path in context.implementation_files.keys():
        print(f"  ✓ {file_path}")
    print('='*60)
    
    await mcp_manager.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
