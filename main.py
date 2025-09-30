import asyncio
from openai import AzureOpenAI
from config import SystemConfig
from core import MCPConnectionManager, WorkflowContext
from agents import OrchestratorAgent, DevOpsAgent

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
    
    async def initialize(self):
        """Initialize the system"""
        print("\n" + "="*60)
        print("MULTI-AGENT AZURE DEVOPS SYSTEM - STEP 3")
        print("="*60 + "\n")
        
        await self.mcp_manager.start_azure_devops_mcp(
            self.config.organization_url,
            self.config.pat_token,
            self.config.default_project
        )
        
        await self.mcp_manager.start_filesystem_mcp(
            self.config.repository_path
        )
        
        print("\n✓ System initialized")
        print("✓ Orchestrator Agent ready")
        print("✓ DevOps Agent ready")
    
    async def test_step3(self, work_item_id: str):
        """Test Steps 2 & 3 together"""
        print(f"\n{'='*60}")
        print(f"TESTING ORCHESTRATOR + DEVOPS AGENT")
        print('='*60 + '\n')
        
        # Create workflow context
        context = WorkflowContext()
        context.work_item_id = work_item_id
        context.repository_path = self.config.repository_path
        
        # Step 1: Orchestrator analyzes and plans
        print("Step 1: Orchestrator Analysis & Planning")
        print("-" * 40)
        success = await self.orchestrator.execute(context)
        
        if not success:
            print("\n✗ Orchestration failed")
            return context
        
        # Step 2: DevOps Agent creates branch
        print("\nStep 2: DevOps Agent - Create Feature Branch")
        print("-" * 40)
        success = await self.devops_agent.create_feature_branch(context)
        
        if success:
            print(f"✓ Created and checked out branch: {context.branch_name}")
            
            # Show repo status
            status = self.devops_agent.get_repo_status()
            print(f"  Current branch: {status['branch']}")
            print(f"  Working tree clean: {not status['is_dirty']}")
        else:
            print("✗ Branch creation failed")
        
        # Display results
        print(f"\n{'='*60}")
        print("TEST RESULTS")
        print('='*60)
        print(f"Work Item: {context.work_item_title}")
        print(f"Branch: {context.branch_name}")
        print(f"Acceptance Criteria: {len(context.acceptance_criteria)}")
        print(f"\nAgent Actions: {len(context.agent_history)}")
        for log in context.agent_history[-5:]:
            status = "✓" if log["success"] else "✗"
            print(f"  {status} [{log['agent']}] {log['action']}")
        print('='*60 + '\n')
        
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
        
        # Test with work item 9
        context = await system.test_step3("9")
        
        print("\n✓ Step 3 Complete!")
        print("\nNext Steps:")
        print("  Step 4: Implement RAG System")
        print("  Step 5: Implement Code Agent")
        print("  Step 6: Implement Test Agent")
        print("  Step 7: Build LangGraph Workflow")
        
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
