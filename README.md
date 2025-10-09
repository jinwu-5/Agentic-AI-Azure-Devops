# Multi-Agent Azure DevOps System

An AI-powered system that automates software development workflows by orchestrating specialized agents to transform Azure DevOps work items into tested, production-ready code with automated PR creation.

## Overview

This system uses multiple AI agents working together to:
1. Fetch work items from Azure DevOps  
2. Analyze requirements and create execution plans  
3. Generate implementation code matching your project's language and style  
4. Write unit tests  
5. Commit changes and create pull requests  

## Components

### Agents
- **Orchestrator Agent** - Fetches work items, analyzes requirements, creates detailed execution plans  
- **DevOps Agent** - Manages Git operations (branching, commits, push, PR creation)  
- **Code Agent** - Generates implementation code based on requirements and existing patterns  
- **Test Agent** - Generates unit and integration tests  

### Services
- **RAG System** - Indexes codebase to provide context-aware code generation  
- **MCP Manager** - Manages connections to Azure DevOps and filesystem MCP servers  
- **State Manager** - Saves/loads workflow state for cost-efficient testing  

## Setup

### Prerequisites
- Python 3.10+  
- Azure OpenAI API access  
- Azure DevOps account with PAT token  
- Node.js (for MCP servers)  


## Components

### Agents
- **Orchestrator Agent** - Fetches work items, analyzes requirements, creates detailed execution plans  
- **DevOps Agent** - Manages Git operations (branching, commits, push, PR creation)  
- **Code Agent** - Generates implementation code based on requirements and existing patterns  
- **Test Agent** - Generates unit and integration tests  

### Services
- **RAG System** - Indexes codebase to provide context-aware code generation  
- **MCP Manager** - Manages connections to Azure DevOps and filesystem MCP servers  
- **State Manager** - Saves/loads workflow state for cost-efficient testing  

## Setup

### Prerequisites
- Python 3.13+  
- Azure OpenAI API access  
- Azure DevOps account with PAT token  
- Node.js (for MCP servers)  

### Installation

    # Clone repository
    cd Agentic-AI-Azure-Devops

    # Create virtual environment
    python -m venv .venv
    source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows

    # Install dependencies
    pip install -r requirements.txt

### Configuration
Create a `.env` file:

    # Azure AI
    AZURE_AI_ENDPOINT=your_endpoint
    AZURE_AI_KEY=your_key
    AZURE_AI_DEPLOYMENT=your_deployment_name
    AZURE_API_VERSION=2024-02-15-preview

    # Azure DevOps
    AZURE_DEVOPS_ORG_URL=https://dev.azure.com/your_org
    AZURE_DEVOPS_PAT=your_personal_access_token
    AZURE_DEVOPS_PROJECT=your_project_name

    # Repository (optional, defaults to current directory)
    REPOSITORY_PATH=/path/to/your/project

## Usage

### Full Workflow

    python run_complete_workflow.py

This will:
- Fetch work item from Azure DevOps  
- Analyze and create execution plan  
- Create feature branch  
- Generate all implementation files  
- Generate test files  
- Commit changes locally  
- Push to remote (with confirmation)  
- Create pull request (with confirmation)  

### Test Individual Agents (Cost Efficient)

    # Save initial state once (expensive)
    python run_complete_workflow.py

    # Manage saved states
    python manage_states.py list
    python manage_states.py delete state_name


## Key Features

### State Management
- Saves workflow state at each phase  
- Enables cheap iteration without re-running expensive operations  
- Persists context across sessions  

### RAG Integration
- Indexes existing codebase  
- Provides relevant code patterns to agents  
- Ensures generated code matches project style  

### Multi-Agent Orchestration
- Each agent specializes in specific tasks  
- Shared context enables agent coordination  
- Modular architecture for easy extension  

## Limitations

### Current Issues
- **Language Detection** - May generate code in wrong language if work item is frontend-focused but project is backend (needs improvement)  
- **RAG** - Uses simple keyword search instead of semantic embeddings  
- **File Paths** - Requires proper MCP configuration for correct file placement  

### Cost Considerations
- Each full workflow run costs ~$0.50–2.00 in Azure OpenAI API calls  
- Use state management to avoid repeated expensive operations  
- Test with smaller work items first  

## Troubleshooting
- **Files created in wrong location** → Verify `REPOSITORY_PATH` in `.env`, run from correct directory  
- **Authentication errors** → Verify PAT token has required permissions, check Azure OpenAI credentials  
- **MCP connection failures** → Ensure Node.js is installed, MCP servers install automatically via `npx`  

## Future Enhancements
- Add LangGraph for complex workflow orchestration to try to improve code generation quality
- Complete flow end to end (PR creation) and remove all human-in-the-loop approval gates unless unresolvable error occurs
- Pull the code repo directly from Azure DevOps 
- Implement test driven development as an option 
- Move agent interactions creation into docker