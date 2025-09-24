import asyncio
import json
import os
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()


class AzureDevOpsMCPAgent:
    """Interactive agent using AzureDevOps MCP server with PAT authentication"""

    def __init__(self):
        # Load Azure AI configuration from environment
        self.azure_endpoint = os.getenv("AZURE_AI_ENDPOINT")
        self.azure_key = os.getenv("AZURE_AI_KEY")
        self.deployment_name = os.getenv("AZURE_AI_DEPLOYMENT")
        self.api_version = os.getenv("AZURE_API_VERSION")

        # Load Azure DevOps configuration from environment
        self.organization_url = os.getenv("AZURE_DEVOPS_ORG_URL")
        self.pat_token = os.getenv("AZURE_DEVOPS_PAT")
        self.default_project = os.getenv("AZURE_DEVOPS_PROJECT")
        self.auth_method = os.getenv("AZURE_DEVOPS_AUTH_METHOD", "pat")

        # Validate required environment variables
        self._validate_config()

        # Azure AI Foundry client
        self.ai_client = AzureOpenAI(
            azure_endpoint=self.azure_endpoint,
            api_key=self.azure_key,
            api_version=self.api_version
        )

        self.mcp_process = None
        self.mcp_stdin = None
        self.mcp_stdout = None
        self.request_id = 1
        self.available_tools = []

    def _validate_config(self):
        """Validate that all required environment variables are set"""
        required_vars = {
            "AZURE_AI_ENDPOINT": self.azure_endpoint,
            "AZURE_AI_KEY": self.azure_key,
            "AZURE_DEVOPS_ORG_URL": self.organization_url,
            "AZURE_DEVOPS_PAT": self.pat_token
        }

        missing_vars = [var for var, value in required_vars.items() if not value]

        if missing_vars:
            print("Missing required environment variables:")
            for var in missing_vars:
                print(f"   - {var}")
            print("\nPlease check your .env file.")
            raise ValueError(f"Missing required environment variables: {missing_vars}")

        print("All required environment variables loaded")

    async def start_azure_devops_mcp(self):
        """Start Azure DevOps MCP server"""

        print(f"Starting Azure DevOps MCP server")
        print(f"Organization: {self.organization_url}")
        print(f"Project: {self.default_project}")

        env_vars = {
            **os.environ,
            "AZURE_DEVOPS_ORG_URL": self.organization_url,
            "AZURE_DEVOPS_AUTH_METHOD": self.auth_method,
            "AZURE_DEVOPS_PAT": self.pat_token,
            "AZURE_DEVOPS_DEFAULT_PROJECT": self.default_project
        }

        # Start MCP server
        self.mcp_process = await asyncio.create_subprocess_exec(
            "npx", "-y", "@tiberriver256/mcp-server-azure-devops",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env_vars
        )

        self.mcp_stdin = self.mcp_process.stdin
        self.mcp_stdout = self.mcp_process.stdout

        # Initialize MCP connection
        await self._init_mcp()
        print("AzureDevOps MCP server ready!")

        # Load available tools
        self.available_tools = await self.list_available_tools()
        return True

    async def _init_mcp(self):
        """Initialize MCP connection"""
        init_request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "tiberriver-mcp-agent", "version": "1.0.0"}
            }
        }

        await self._send_mcp_message(init_request)
        init_response = await self._read_mcp_message()

        server_info = init_response.get('result', {}).get('serverInfo', {})
        print(f"MCP Server: {server_info.get('name')} v{server_info.get('version')}")

        # Send initialized notification
        initialized = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }
        await self._send_mcp_message(initialized)
        self.request_id += 1

    async def _send_mcp_message(self, message):
        """Send message to MCP"""
        message_str = json.dumps(message) + "\n"
        self.mcp_stdin.write(message_str.encode())
        await self.mcp_stdin.drain()

    async def _read_mcp_message(self):
        """Read message from MCP"""
        line = await self.mcp_stdout.readline()
        return json.loads(line.decode().strip())

    async def list_available_tools(self):
        """List available tools from AzureDevOps MCP server"""
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": "tools/list"
        }

        await self._send_mcp_message(request)
        response = await self._read_mcp_message()
        self.request_id += 1

        if "result" in response:
            tools = response["result"].get("tools", [])
            print(f"Available tools ({len(tools)}):")

            # Show first 10 tools
            for tool in tools:
                print(f"   - {tool['name']}")
            return tools
        return []

    async def call_mcp_tool(self, tool_name, arguments):
        """Generic method to call any MCP tool"""
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }

        await self._send_mcp_message(request)
        response = await self._read_mcp_message()
        self.request_id += 1

        return response

    async def analyze_user_question(self, user_question):
        """Use AI to analyze user question and determine what MCP tools to use"""

        # Create list of available tool names for the AI
        tool_list = "\n".join([f"- {tool['name']}: {tool.get('description', 'No description')}"
                               for tool in self.available_tools[:20]])

        system_prompt = f"""You are an Azure DevOps assistant with access to MCP tools.

            AVAILABLE TOOLS:
            {tool_list}
            
            Your job is to:
            1. Analyze the user's question
            2. Determine which MCP tools to call and in what order
            3. Specify the exact arguments for each tool call
            
            For AzureDevOps MCP server, common tool patterns:
            - list_projects: List all projects
            - get_work_item: Get work item details (needs workItemId)
            - create_work_item: Create new work item (needs project, workItemType, title)
            - list_work_items: List work items (can filter by project)
            
            Respond in JSON format:
            {{
                "analysis": "What the user is asking for",
                "tool_calls": [
                    {{
                        "tool_name": "exact_tool_name",
                        "arguments": {{"param": "value"}},
                        "reason": "Why this tool is needed"
                    }}
                ],
                "response_plan": "How you'll present the results to the user"
            }}
            
            Default Project: {self.default_project}"""

        try:
            response = self.ai_client.chat.completions.create(
                model=self.deployment_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_question}
                ],
                temperature=0.1,
                max_tokens=1000
            )

            ai_response = response.choices[0].message.content

            # Try to parse JSON response
            if "```json" in ai_response:
                json_start = ai_response.find("```json") + 7
                json_end = ai_response.find("```", json_start)
                json_str = ai_response[json_start:json_end].strip()
            else:
                json_start = ai_response.find("{")
                json_end = ai_response.rfind("}") + 1
                json_str = ai_response[json_start:json_end] if json_start != -1 else ai_response

            return json.loads(json_str)

        except json.JSONDecodeError:
            return {
                "analysis": "Could not parse AI response",
                "tool_calls": [],
                "response_plan": f"AI response: {ai_response}",
                "error": "JSON parsing failed"
            }
        except Exception as e:
            return {
                "analysis": "AI analysis failed",
                "tool_calls": [],
                "response_plan": f"Error: {str(e)}",
                "error": str(e)
            }

    async def execute_tool_calls(self, tool_calls):
        """Execute the planned tool calls"""
        results = []

        for tool_call in tool_calls:
            tool_name = tool_call["tool_name"]
            arguments = tool_call["arguments"]
            reason = tool_call.get("reason", "No reason provided")

            print(f"Calling {tool_name}: {reason}")

            try:
                result = await self.call_mcp_tool(tool_name, arguments)
                results.append({
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "result": result,
                    "success": "result" in result
                })

                if "result" in result:
                    print(f"   Success")
                else:
                    print(f"   Failed: {result.get('error', 'Unknown error')}")

            except Exception as e:
                print(f"   Error: {str(e)}")
                results.append({
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "error": str(e),
                    "success": False
                })

        return results

    async def format_response(self, user_question, analysis, tool_results):
        """Use AI to format the final response based on tool results"""

        system_prompt = """You are an Azure DevOps assistant. Format the tool results into a clear, helpful response for the user.

            Guidelines:
            - Be concise but informative
            - Use bullet points or tables for lists
            - Highlight important information
            - If tools failed, explain what went wrong
            - If no results found, suggest alternatives"""

        # Prepare tool results summary
        results_summary = ""
        for result in tool_results:
            if result["success"]:
                results_summary += f"\n{result['tool_name']}: SUCCESS\n"
                results_summary += f"Data: {json.dumps(result['result'].get('result', {}), indent=2)}\n"
            else:
                results_summary += f"\n{result['tool_name']}: FAILED\n"
                results_summary += f"Error: {result.get('error', 'Unknown error')}\n"

        user_prompt = f"""
            USER QUESTION: {user_question}
            
            ANALYSIS: {analysis.get('analysis', 'No analysis')}
            
            TOOL RESULTS:
            {results_summary}
            
            Please format this into a helpful response for the user."""

        try:
            response = self.ai_client.chat.completions.create(
                model=self.deployment_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=1500
            )

            return response.choices[0].message.content

        except Exception as e:
            return f"Failed to format response: {str(e)}\n\nRaw results: {results_summary}"

    async def process_user_question(self, user_question):
        """Main method to process a user question end-to-end"""

        print(f"\nUser Question: {user_question}")
        print("=" * 60)

        # Step 1: Analyze question with AI
        print("Analyzing question...")
        analysis = await self.analyze_user_question(user_question)

        if "error" in analysis:
            return f"Analysis failed: {analysis['error']}"

        print(f"Analysis: {analysis.get('analysis', 'No analysis')}")
        print(f"Plan: {len(analysis.get('tool_calls', []))} tool calls planned")

        # Step 2: Execute tool calls
        print("\nExecuting tool calls...")
        tool_results = await self.execute_tool_calls(analysis.get('tool_calls', []))

        # Step 3: Format response
        print("\nFormatting response...")
        final_response = await self.format_response(user_question, analysis, tool_results)

        return final_response

    async def interactive_session(self):
        """Run an interactive session where user can ask questions"""

        print(f"\nInteractive Azure DevOps Assistant")
        print("=" * 50)
        print("Ask me anything about your Azure DevOps organization!")
        print("Examples:")
        print("  - 'List all projects'")
        print("  - 'Show me work items in project X'")
        print("  - 'Create a new feature called User Authentication'")
        print("  - 'What repositories do we have?'")
        print("\nType 'quit' to exit.")
        print("=" * 50)

        while True:
            try:
                user_input = input("\nYour question: ").strip()

                if user_input.lower() in ['quit', 'exit', 'q']:
                    print("Goodbye!")
                    break

                if not user_input:
                    print("Please enter a question.")
                    continue

                # Process the question
                response = await self.process_user_question(user_input)

                print(f"\nResponse:")
                print("-" * 40)
                print(response)
                print("-" * 40)

            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"Error: {str(e)}")

    async def cleanup(self):
        """Clean up MCP server"""
        if self.mcp_process:
            print("Stopping AzureDevOps MCP server...")
            self.mcp_process.terminate()
            await self.mcp_process.wait()


async def main():
    """Main function with interactive session"""

    print("INTERACTIVE AZURE DEVOPS MCP AGENT")
    print("=" * 60)

    agent = None
    try:
        # Initialize agent
        agent = AzureDevOpsMCPAgent()

        # Start MCP server
        if await agent.start_azure_devops_mcp():
            # Run interactive session
            await agent.interactive_session()
        else:
            print("Failed to start MCP server")

    except Exception as e:
        print(f"Unexpected error: {str(e)}")
    finally:
        if agent:
            await agent.cleanup()


if __name__ == "__main__":
    print("IMPORTANT: Make sure you have:")
    print("   1. Created a .env file with your Azure DevOps PAT token")
    print("   2. Installed python-dotenv: pip install python-dotenv")

    asyncio.run(main())