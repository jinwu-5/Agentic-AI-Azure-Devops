import asyncio
import json
from config import SystemConfig
from core import MCPConnectionManager

async def debug_work_item():
    """Debug what Azure DevOps MCP returns"""
    config = SystemConfig()
    mcp = MCPConnectionManager()
    
    await mcp.start_azure_devops_mcp(
        config.organization_url,
        config.pat_token,
        config.default_project
    )
    
    print("\n" + "="*60)
    print("DEBUGGING WORK ITEM 9 - RAW DATA")
    print("="*60 + "\n")
    
    # FIX: Convert to integer
    result = await mcp.call_tool(
        "azure_devops",
        "get_work_item",
        {"workItemId": 9}  # <-- INTEGER, not string!
    )
    
    print("Full Response:")
    print(json.dumps(result, indent=2))
    
    if "result" in result:
        print("\n" + "="*60)
        print("PARSED RESULT:")
        print("="*60)
        work_item = result["result"]
        
        # Check if it has content array
        if "content" in work_item:
            print(f"\nContent type: {type(work_item['content'])}")
            print(f"Content: {json.dumps(work_item['content'], indent=2)}")
        
        # Check for direct fields
        print(f"\nDirect fields:")
        print(f"  title: {work_item.get('title', 'NOT FOUND')}")
        print(f"  description: {work_item.get('description', 'NOT FOUND')}")
        print(f"  state: {work_item.get('state', 'NOT FOUND')}")
        
        # Show all keys
        print(f"\nAll keys in result: {list(work_item.keys())}")
    
    await mcp.cleanup()

if __name__ == "__main__":
    asyncio.run(debug_work_item())
