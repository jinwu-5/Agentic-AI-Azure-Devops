import asyncio
from openai import AzureOpenAI
from config import SystemConfig
from core import MCPConnectionManager, WorkflowContext
from agents import OrchestratorAgent, DevOpsAgent, CodeAgent
from services import CodebaseRAG

class MultiAgentSystem:
    """Main multi-agent orchestration system"""
    
    def __init__(self, config: SystemConfig):
        self.config = config
        self.mcp_manager = MCPConnectionManager()
        
        self.ai_client = AzureOpenAI(
            azure_endpoint=config.azure_endpoint,
            api_key=config.azure_key,
            api_version=config.api_version
        )
        
        # Initialize RAG first
        self.rag = CodebaseRAG(
            config.repository_path,
            self.ai_client,
            config.rag_persist_directory
        )
        
        # Initialize agents
        self.orchestrator = OrchestratorAgent(
            self.ai_client,
            config.deployment_name,
            self.mcp_manager
        )
        
        self.devops_agent = DevOpsAgent(
            self.ai_client,
            config.deployment_name,
            self.mcp_manager,
            config.repository_path
        )
        
        self.code_agent = CodeAgent(
            self.ai_client,
            config.deployment_name,
            self.mcp_manager,
            self.rag,
            config.repository_path  # Pass repository path
        )
    
    async def initialize(self):
        """Initialize the system"""
        print("\n" + "="*60)
        print("MULTI-AGENT SYSTEM - FULL WORKFLOW TEST")
        print("="*60 + "\n")
        
        await self.mcp_manager.start_azure_devops_mcp(
            self.config.organization_url,
            self.config.pat_token,
            self.config.default_project
        )
        
        await self.mcp_manager.start_filesystem_mcp(
            self.config.repository_path
        )
        
        print("Indexing codebase...")
        self.rag.index_repository()
        
        print("\n✓ All agents initialized")
    
    async def implement_work_item(self, work_item_id: str):
        """Full workflow"""
        print(f"\n{'='*60}")
        print(f"IMPLEMENTING WORK ITEM {work_item_id}")
        print('='*60 + '\n')
        
        context = WorkflowContext()
        context.work_item_id = work_item_id
        context.repository_path = self.config.repository_path
        
        # Step 1: Orchestrator
        print("STEP 1: Orchestrator")
        print("-" * 40)
        if not await self.orchestrator.execute(context):
            return context
        
        # Step 2: DevOps creates branch
        print("\nSTEP 2: DevOps Agent")
        print("-" * 40)
        if not await self.devops_agent.create_feature_branch(context):
            return context
        
        # Step 3: Code Agent (first 2 steps)
        print("\nSTEP 3: Code Agent")
        print("-" * 40)
        plan = context.execution_plan.get("implementation", {})
        steps = plan.get("implementation_steps", [])
        
        code_steps = [s for s in steps if s.get("agent") == "CodeAgent"][:2]
        
        for step in code_steps:
            print(f"\n  Step {step.get('step')}...")
            if not await self.code_agent.execute_step(context, step):
                print(f"  ✗ Failed")
                break
        
        # Verify files
        print(f"\n{'='*60}")
        print("VERIFICATION")
        print('='*60)
        import os
        for file_path in context.implementation_files.keys():
            full_path = os.path.join(self.config.repository_path, file_path)
            exists = os.path.exists(full_path)
            status = "✓" if exists else "✗"
            print(f"{status} {file_path}: {'EXISTS' if exists else 'NOT FOUND'}")
        
        return context
    
    async def cleanup(self):
        """Clean up resources"""
        await self.mcp_manager.cleanup()


async def main():
    """Main entry point"""
    try:
        config = SystemConfig()
        system = MultiAgentSystem(config)
        await system.initialize()
        
        context = await system.implement_work_item("9")
        
        print("\n✓ Test complete!")
        print("\n[Press Ctrl+C to exit]")
        await asyncio.Event().wait()
        
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if 'system' in locals():
            await system.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
