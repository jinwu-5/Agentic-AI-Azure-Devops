import asyncio
import json
import os
from openai import AzureOpenAI
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()


class AzureDevOpsMCPAgent:
    """Agentic Azure DevOps agent with iterative implementation"""

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

        # Azure DevOps MCP
        self.mcp_process = None
        self.mcp_stdin = None
        self.mcp_stdout = None
        self.request_id = 1
        self.available_tools = []

        # Filesystem MCP
        self.filesystem_mcp_process = None
        self.filesystem_mcp_stdin = None
        self.filesystem_mcp_stdout = None
        self.fs_request_id = 1
        self.filesystem_available = False

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

    async def start_filesystem_mcp(self):
        """Start Filesystem MCP server"""

        print("Starting Filesystem MCP server...")

        try:
            # Start filesystem MCP server pointing to current directory
            self.filesystem_mcp_process = await asyncio.create_subprocess_exec(
                "npx", "-y", "@modelcontextprotocol/server-filesystem", os.getcwd(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            self.filesystem_mcp_stdin = self.filesystem_mcp_process.stdin
            self.filesystem_mcp_stdout = self.filesystem_mcp_process.stdout

            # Initialize filesystem MCP connection
            await self._init_filesystem_mcp()

            self.filesystem_available = True
            print("Filesystem MCP server ready!")
            return True

        except Exception as e:
            print(f"Failed to start Filesystem MCP server: {e}")
            print("File operations will not be available.")
            print("Install with: npm install -g @modelcontextprotocol/server-filesystem")
            self.filesystem_available = False
            return False

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

    async def _init_filesystem_mcp(self):
        """Initialize Filesystem MCP connection"""
        init_request = {
            "jsonrpc": "2.0",
            "id": self.fs_request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "filesystem-agent", "version": "1.0.0"}
            }
        }

        await self._send_filesystem_message(init_request)
        init_response = await self._read_filesystem_message()

        server_info = init_response.get('result', {}).get('serverInfo', {})
        print(f"Filesystem MCP Server: {server_info.get('name')} v{server_info.get('version')}")

        # Send initialized notification
        initialized = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }
        await self._send_filesystem_message(initialized)
        self.fs_request_id += 1

    async def _send_mcp_message(self, message):
        """Send message to Azure DevOps MCP"""
        message_str = json.dumps(message) + "\n"
        self.mcp_stdin.write(message_str.encode())
        await self.mcp_stdin.drain()

    async def _read_mcp_message(self):
        """Read message from Azure DevOps MCP"""
        line = await self.mcp_stdout.readline()
        return json.loads(line.decode().strip())

    async def _send_filesystem_message(self, message):
        """Send message to Filesystem MCP"""
        message_str = json.dumps(message) + "\n"
        self.filesystem_mcp_stdin.write(message_str.encode())
        await self.filesystem_mcp_stdin.drain()

    async def _read_filesystem_message(self):
        """Read message from Filesystem MCP"""
        line = await self.filesystem_mcp_stdout.readline()
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
            print(f"Available Azure DevOps tools ({len(tools)}):")

            # Show first 10 tools
            for tool in tools[:10]:
                print(f"   - {tool['name']}")
            return tools
        return []

    async def call_mcp_tool(self, tool_name, arguments):
        """Generic method to call any Azure DevOps MCP tool"""
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

    async def call_filesystem_tool(self, tool_name, arguments):
        """Call Filesystem MCP tool"""
        if not self.filesystem_available:
            return {"error": "Filesystem MCP not available"}

        request = {
            "jsonrpc": "2.0",
            "id": self.fs_request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }

        await self._send_filesystem_message(request)
        response = await self._read_filesystem_message()
        self.fs_request_id += 1

        return response

    async def ai_decide_next_action(self, work_item, current_state, iteration, action_history):
        """AI decides the next action in implementation"""

        # Summarize what's been done so far
        history_summary = "\n".join([
            f"- {action['decision']['action']}: {action['decision'].get('target', 'N/A')} ({action['result']})"
            for action in action_history[-3:]  # Last 3 actions
        ])

        prompt = f"""You are implementing a feature step by step. Decide the next small, specific action.

Work Item: {work_item.get('title', 'Untitled')}
Description: {work_item.get('description', 'No description')}

Current State: {current_state}
Iteration: {iteration}/10

Recent Actions Taken:
{history_summary if history_summary else "None yet"}

Available actions:
- "analyze": Think about requirements and plan approach
- "create_file": Create a new file (must provide exact path and complete content)
- "read_file": Read an existing file to understand current code
- "complete": Implementation is finished
- "error": Cannot proceed (explain why)

IMPORTANT:
- Focus on ONE small, specific step at a time
- Be concrete: provide actual file paths and real code content
- Create simple, working implementations
- Don't overthink - make progress with each step

Respond with JSON:
{{
    "action": "analyze|create_file|read_file|complete|error",
    "target": "exact file path (e.g., 'src/theme.css')",
    "content": "complete file content if creating",
    "reason": "brief explanation",
    "next_state": "what state after this action"
}}"""

        try:
            response = self.ai_client.chat.completions.create(
                model=self.deployment_name,
                messages=[
                    {"role": "system",
                     "content": "You are a practical software engineer. Make steady progress. Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=2000
            )

            ai_response = response.choices[0].message.content

            # Extract JSON
            if "```json" in ai_response:
                json_start = ai_response.find("```json") + 7
                json_end = ai_response.find("```", json_start)
                json_str = ai_response[json_start:json_end].strip()
            else:
                json_start = ai_response.find("{")
                json_end = ai_response.rfind("}") + 1
                json_str = ai_response[json_start:json_end]

            decision = json.loads(json_str)
            return decision

        except Exception as e:
            print(f"AI decision error: {e}")
            return {
                "action": "error",
                "reason": f"AI decision failed: {str(e)}",
                "next_state": "failed"
            }

    async def execute_action(self, decision):
        """Execute the decided action"""

        action = decision.get("action")
        target = decision.get("target", "")
        content = decision.get("content", "")

        print(f"  Action: {action}")
        print(f"  Target: {target}")
        print(f"  Reason: {decision.get('reason', 'No reason')}")

        try:
            if action == "create_file":
                if not target or not content:
                    return {"success": False, "message": "Missing file path or content"}

                result = await self.call_filesystem_tool("write_file", {
                    "path": target,
                    "content": content
                })

                if "result" in result:
                    return {"success": True, "message": f"Created {target}"}
                else:
                    return {"success": False,
                            "message": f"Failed to create {target}: {result.get('error', 'Unknown error')}"}

            elif action == "read_file":
                result = await self.call_filesystem_tool("read_file", {"path": target})
                if "result" in result:
                    file_content = result["result"].get("content", "")
                    return {"success": True, "message": f"Read {target}", "content": file_content[:200]}
                else:
                    return {"success": False, "message": f"Failed to read {target}"}

            elif action == "analyze":
                return {"success": True, "message": "Analysis complete"}

            elif action == "complete":
                return {"success": True, "message": "Implementation complete"}

            elif action == "error":
                return {"success": False, "message": decision.get("reason", "Unknown error")}

            else:
                return {"success": False, "message": f"Unknown action: {action}"}

        except Exception as e:
            return {"success": False, "message": f"Error executing {action}: {str(e)}"}

    async def implement_work_item_agentically(self, work_item_id):
        """Main agentic implementation loop"""

        if not self.filesystem_available:
            return "Filesystem MCP not available. Cannot implement work items. Please install: npm install -g @modelcontextprotocol/server-filesystem"

        print(f"\nStarting agentic implementation of work item {work_item_id}")
        print("=" * 60)

        # Get work item from Azure DevOps
        try:
            work_item_result = await self.call_mcp_tool("get_work_item", {"workItemId": work_item_id})
            if not work_item_result.get("result"):
                return f"Could not find work item {work_item_id}"

            work_item_data = work_item_result["result"]

            # Extract work item details from the content array
            work_item = {}
            if "content" in work_item_data and isinstance(work_item_data["content"], list):
                for item in work_item_data["content"]:
                    if item.get("type") == "text":
                        text = item.get("text", "")
                        # Parse the text for title and description
                        if "Title:" in text:
                            lines = text.split("\n")
                            for line in lines:
                                if line.startswith("Title:"):
                                    work_item["title"] = line.replace("Title:", "").strip()
                                elif line.startswith("Description:"):
                                    work_item["description"] = line.replace("Description:", "").strip()

            title = work_item.get('title', 'Untitled')
            description = work_item.get('description', 'No description')

            print(f"Work Item: {title}")
            print(f"Description: {description[:100]}...")
            print("=" * 60)

        except Exception as e:
            return f"Error getting work item: {str(e)}"

        # Implementation loop
        max_iterations = 10
        current_state = "starting"
        action_history = []

        for iteration in range(1, max_iterations + 1):
            print(f"\nIteration {iteration}/{max_iterations}")
            print("-" * 40)

            # AI decides next action
            decision = await self.ai_decide_next_action(work_item, current_state, iteration, action_history)

            # Execute the action
            result = await self.execute_action(decision)

            # Log this iteration
            action_log = {
                "iteration": iteration,
                "decision": decision,
                "result": result["message"],
                "success": result["success"]
            }
            action_history.append(action_log)

            print(f"  Result: {result['message']}")

            # Check if we should stop
            if decision["action"] == "complete":
                print("\nImplementation completed!")
                break
            elif decision["action"] == "error" or not result["success"]:
                print(f"\nImplementation stopped: {result['message']}")
                break

            # Update state for next iteration
            current_state = decision.get("next_state", current_state)

            # Small delay to avoid rate limiting
            await asyncio.sleep(1)

        # Generate summary
        summary = self.generate_summary(work_item, action_history)
        return summary

    def generate_summary(self, work_item, action_history):
        """Generate implementation summary"""

        successful = [a for a in action_history if a["success"]]
        failed = [a for a in action_history if not a["success"]]
        files_created = [a for a in successful if a["decision"]["action"] == "create_file"]

        summary = f"""
Implementation Summary
{'=' * 60}
Work Item: {work_item.get('title', 'Untitled')}

Statistics:
- Total iterations: {len(action_history)}
- Successful actions: {len(successful)}
- Failed actions: {len(failed)}
- Files created: {len(files_created)}

Actions Taken:"""

        for action in action_history:
            status = "✓" if action["success"] else "✗"
            action_type = action["decision"]["action"]
            target = action["decision"].get("target", "N/A")
            summary += f"\n{status} {action_type}: {target}"

        if files_created:
            summary += "\n\nFiles Created:"
            for action in files_created:
                summary += f"\n- {action['decision']['target']}"

        if failed:
            summary += "\n\nIssues:"
            for action in failed:
                summary += f"\n- {action['result']}"

        return summary

    async def test_filesystem(self):
        """Test filesystem operations"""
        if not self.filesystem_available:
            print("Filesystem MCP not available - skipping test")
            return

        print("\nTesting filesystem operations...")

        # Test: Write a file
        print("Test: Creating test file...")
        write_result = await self.call_filesystem_tool("write_file", {
            "path": "agent_test.txt",
            "content": "Hello from Azure DevOps Agent!\nThis is a test file."
        })

        if "result" in write_result:
            print("   Success: File created")
        else:
            print(f"   Failed: {write_result.get('error', 'Unknown error')}")
            return

        # Test: Read the file
        print("Test: Reading test file...")
        read_result = await self.call_filesystem_tool("read_file", {
            "path": "agent_test.txt"
        })

        if "result" in read_result:
            content = read_result["result"].get("content", "")
            print(f"   Success: Read {len(content)} characters")
        else:
            print(f"   Failed: {read_result.get('error', 'Unknown error')}")

        print("\nFilesystem test complete!")

    async def analyze_user_question(self, user_question):
        """Use AI to analyze user question and determine what MCP tools to use"""

        tool_list = "\n".join([f"- {tool['name']}: {tool.get('description', 'No description')}"
                               for tool in self.available_tools[:20]])

        system_prompt = f"""You are an Azure DevOps assistant with access to MCP tools.

AVAILABLE TOOLS:
{tool_list}

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

Default Project: {self.default_project}

IMPORTANT: When the user asks about work items (stories, tasks, bugs), use "get_work_item" with workItemId parameter."""

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

            if "```json" in ai_response:
                json_start = ai_response.find("```json") + 7
                json_end = ai_response.find("```", json_start)
                json_str = ai_response[json_start:json_end].strip()
            else:
                json_start = ai_response.find("{")
                json_end = ai_response.rfind("}") + 1
                json_str = ai_response[json_start:json_end] if json_start != -1 else ai_response

            return json.loads(json_str)

        except Exception as e:
            print(f"Analysis error: {e}")
            return {"analysis": "Could not parse", "tool_calls": [], "error": f"JSON parsing failed: {str(e)}"}

    async def execute_tool_calls(self, tool_calls):
        """Execute the planned tool calls and return detailed results"""
        results = []

        for tool_call in tool_calls:
            tool_name = tool_call["tool_name"]
            arguments = tool_call["arguments"]

            print(f"Calling {tool_name} with args: {arguments}")

            try:
                result = await self.call_mcp_tool(tool_name, arguments)

                # Store the full result
                results.append({
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "result": result,
                    "success": "result" in result
                })

            except Exception as e:
                results.append({
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "error": str(e),
                    "success": False
                })

        return results

    async def format_response(self, user_question, analysis, tool_results):
        """Use AI to format the final response with actual data"""

        # Build a detailed summary with actual results
        results_text = ""
        for result in tool_results:
            results_text += f"\n\n=== Tool: {result['tool_name']} ==="
            results_text += f"\nArguments: {json.dumps(result.get('arguments', {}), indent=2)}"

            if result["success"]:
                # Include the actual result data
                result_data = result.get("result", {})
                if "result" in result_data:
                    results_text += f"\nData:\n{json.dumps(result_data['result'], indent=2)[:2000]}"  # Limit size
                else:
                    results_text += f"\nRaw Response:\n{json.dumps(result_data, indent=2)[:2000]}"
            else:
                results_text += f"\nError: {result.get('error', 'Unknown error')}"

        prompt = f"""Format this Azure DevOps data for the user in a clear, readable way.

User Question: {user_question}

Tool Results:{results_text}

Instructions:
- Present the actual data from the results, not just status messages
- Format work items with their key fields (ID, Title, State, Description, etc.)
- Be concise but include all important information
- If there's an error, explain what went wrong
- Use bullet points or formatting to make it readable"""

        try:
            response = self.ai_client.chat.completions.create(
                model=self.deployment_name,
                messages=[
                    {"role": "system",
                     "content": "You are a helpful assistant that formats Azure DevOps data clearly."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=2000
            )

            return response.choices[0].message.content

        except Exception as e:
            print(f"Formatting error: {e}")
            # Fallback: return raw results
            return f"Raw Results:\n{results_text}"

    async def process_user_question(self, user_question):
        """Process a user question"""
        print(f"\nProcessing: {user_question}")
        print("-" * 60)

        # Analyze what the user wants
        analysis = await self.analyze_user_question(user_question)
        if "error" in analysis:
            return f"Analysis failed: {analysis['error']}"

        print(f"Analysis: {analysis.get('analysis', 'N/A')}")
        print(f"Planned tool calls: {len(analysis.get('tool_calls', []))}")

        # Execute the tools
        tool_results = await self.execute_tool_calls(analysis.get('tool_calls', []))

        # Format and return response
        final_response = await self.format_response(user_question, analysis, tool_results)

        return final_response

    async def interactive_session(self):
        """Interactive session"""

        print(f"\nAgentic Azure DevOps Assistant")
        print("=" * 50)
        print("Commands:")
        print("  - 'implement <work_item_id>' - Agentically implement a work item")
        print("  - 'test filesystem' - Test file operations")
        print("  - Any question about Azure DevOps")
        print("  - 'quit' - Exit")
        print("=" * 50)

        while True:
            try:
                user_input = input("\nYour command: ").strip()

                if user_input.lower() in ['quit', 'exit', 'q']:
                    print("Goodbye!")
                    break

                if not user_input:
                    continue

                # Test filesystem
                if user_input.lower() == 'test filesystem':
                    await self.test_filesystem()
                    continue

                # Implement work item
                if user_input.lower().startswith('implement '):
                    try:
                        work_item_id = user_input.split()[1]
                        result = await self.implement_work_item_agentically(work_item_id)
                        print("\n" + result)
                    except IndexError:
                        print("Usage: implement <work_item_id>")
                    continue

                # Regular question
                response = await self.process_user_question(user_input)
                print(f"\n{'=' * 60}")
                print("RESPONSE:")
                print('=' * 60)
                print(response)

            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"Error: {str(e)}")

    async def cleanup(self):
        """Clean up MCP servers"""
        if self.mcp_process:
            self.mcp_process.terminate()
            await self.mcp_process.wait()

        if self.filesystem_mcp_process:
            self.filesystem_mcp_process.terminate()
            await self.filesystem_mcp_process.wait()


async def main():
    """Main function"""

    print("AGENTIC AZURE DEVOPS AGENT - FIXED VERSION")
    print("=" * 60)

    agent = None
    try:
        agent = AzureDevOpsMCPAgent()

        if not await agent.start_azure_devops_mcp():
            return

        await agent.start_filesystem_mcp()
        await agent.interactive_session()

    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        if agent:
            await agent.cleanup()


if __name__ == "__main__":
    print("Run from your project directory")
    asyncio.run(main())