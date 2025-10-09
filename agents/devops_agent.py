from core import BaseAgent, WorkflowContext, AgentState
from typing import Dict, Any, List
import git


class DevOpsAgent(BaseAgent):
    """
    DevOps Agent - Manages Git and Azure DevOps operations
    
    Responsibilities:
    1. Create and manage Git branches
    2. Commit code changes
    3. Push to remote repository
    4. Create pull requests
    5. Link commits to work items
    """
    
    def __init__(self, ai_client, deployment_name, mcp_manager, repo_path: str):
        super().__init__("DevOps", ai_client, deployment_name)
        self.mcp_manager = mcp_manager
        self.repo_path = repo_path
        self.repo = None
    
    async def execute(self, context: WorkflowContext) -> bool:
        """Main execution - not used directly, agents call specific methods"""
        return True
    
    def initialize_repo(self) -> bool:
        """Initialize Git repository"""
        try:
            self.repo = git.Repo(self.repo_path)
            print(f"[{self.name}] Git repo initialized: {self.repo_path}")
            return True
        except git.InvalidGitRepositoryError:
            print(f"[{self.name}] Not a git repository: {self.repo_path}")
            print(f"[{self.name}] Run 'git init' in your project directory first")
            return False
        except Exception as e:
            print(f"[{self.name}] Failed to initialize repo: {e}")
            return False
    
    async def create_feature_branch(self, context: WorkflowContext) -> bool:
        """Create a new feature branch for the work item"""
        self.log(context, "Creating feature branch", context.branch_name)
        context.current_state = AgentState.CREATING_BRANCH
        
        try:
            if not self.repo:
                if not self.initialize_repo():
                    return False
            
            # Check if branch already exists
            existing_branches = [b.name for b in self.repo.branches]
            
            if context.branch_name in existing_branches:
                self.log(context, "Branch exists", f"Checking out {context.branch_name}")
                self.repo.git.checkout(context.branch_name)
            else:
                # Create new branch from current HEAD
                self.repo.git.checkout('-b', context.branch_name)
                self.log(context, "Branch created", context.branch_name, True)
            
            return True
            
        except Exception as e:
            self.log(context, "Failed to create branch", str(e), False)
            context.add_error(f"Branch creation failed: {e}")
            return False
    
    async def commit_changes(self, context: WorkflowContext, 
                            commit_message: str = None) -> bool:
        """Commit all staged changes"""
        self.log(context, "Committing changes", "Staging files")
        context.current_state = AgentState.COMMITTING
        
        try:
            if not self.repo:
                if not self.initialize_repo():
                    return False
            
            # Get list of changed files
            changed_files = [item.a_path for item in self.repo.index.diff(None)]
            untracked_files = self.repo.untracked_files
            
            if not changed_files and not untracked_files:
                self.log(context, "No changes to commit", "Working tree clean")
                return True
            
            # Stage all changes
            self.repo.git.add(A=True)
            
            # Generate commit message if not provided
            if not commit_message:
                commit_message = await self._generate_commit_message(
                    context, 
                    changed_files + untracked_files
                )
            
            # Commit with work item reference
            full_message = f"{commit_message}\n\nWork Item: #{context.work_item_id}"
            self.repo.index.commit(full_message)
            
            self.log(context, "Changes committed", 
                    f"{len(changed_files)} modified, {len(untracked_files)} new")
            
            return True
            
        except Exception as e:
            self.log(context, "Failed to commit", str(e), False)
            context.add_error(f"Commit failed: {e}")
            return False
    
    async def _generate_commit_message(self, context: WorkflowContext, 
                                      files: List[str]) -> str:
        """Use AI to generate a descriptive commit message"""
        
        system_prompt = """You are a Git commit message expert.
            Generate clear, concise commit messages following conventional commits format.
            
            Format: <type>: <description>
            
            Types: feat, fix, refactor, docs, test, style, chore
            
            Keep messages under 72 characters for the subject line."""

        file_list = "\n".join([f"- {f}" for f in files[:10]])
        if len(files) > 10:
            file_list += f"\n... and {len(files) - 10} more files"
        
        user_prompt = f"""Generate a commit message for:

            Work Item: {context.work_item_title}
            
            Files changed:
            {file_list}
            
            Description: {context.work_item_description[:200]}
            
            Respond with just the commit message, no explanation."""

        try:
            response = await self.call_ai(system_prompt, user_prompt, temperature=0.3)
            # Extract just the message (remove any markdown or extra text)
            commit_msg = response.strip().split('\n')[0]
            return commit_msg
        except:
            # Fallback message
            return f"feat: implement {context.work_item_title}"
    
    async def push_to_remote(self, context: WorkflowContext, 
                            remote_name: str = "origin") -> bool:
        """Push the feature branch to remote repository"""
        self.log(context, "Pushing to remote", f"{remote_name}/{context.branch_name}")
        
        try:
            if not self.repo:
                if not self.initialize_repo():
                    return False
            
            # Get remote
            remote = self.repo.remote(remote_name)
            
            # Push branch
            push_info = remote.push(context.branch_name)
            
            if push_info:
                self.log(context, "Pushed to remote", 
                        f"{remote_name}/{context.branch_name}", True)
                return True
            else:
                self.log(context, "Push failed", "No push info returned", False)
                return False
            
        except git.GitCommandError as e:
            # Branch might not have remote tracking yet
            if "has no upstream branch" in str(e):
                try:
                    # Set upstream and push
                    self.repo.git.push('--set-upstream', remote_name, context.branch_name)
                    self.log(context, "Pushed with upstream", 
                            f"{remote_name}/{context.branch_name}", True)
                    return True
                except Exception as e2:
                    self.log(context, "Failed to push with upstream", str(e2), False)
                    return False
            else:
                self.log(context, "Push failed", str(e), False)
                return False
        except Exception as e:
            self.log(context, "Failed to push", str(e), False)
            context.add_error(f"Push failed: {e}")
            return False
    
    async def create_pull_request(self, context: WorkflowContext) -> bool:
        """Create a pull request in Azure DevOps"""
        self.log(context, "Creating pull request", "Preparing PR")
        context.current_state = AgentState.CREATING_PR
        
        try:
            # Get PR description from execution plan
            plan = context.execution_plan.get("implementation", {})
            pr_description = plan.get("pr_description", context.work_item_description)
            
            # Generate PR title
            pr_title = f"{context.work_item_title} (Work Item #{context.work_item_id})"
            
            # Call Azure DevOps MCP to create PR
            result = await self.mcp_manager.call_tool(
                "azure_devops",
                "create_pull_request",
                {
                    "title": pr_title,
                    "description": pr_description,
                    "sourceRefName": f"refs/heads/{context.branch_name}",
                    "targetRefName": "refs/heads/main",  # or master
                    "workItemRefs": [
                        {
                            "id": str(context.work_item_id)
                        }
                    ]
                }
            )
            
            if "result" in result:
                # Parse PR response
                pr_data = result["result"]
                context.pr_id = str(pr_data.get("pullRequestId", ""))
                context.pr_url = pr_data.get("url", "")
                
                self.log(context, "Pull request created", 
                        f"PR #{context.pr_id}", True)
                
                print(f"\n{'='*60}")
                print("PULL REQUEST CREATED")
                print('='*60)
                print(f"PR ID: {context.pr_id}")
                print(f"Title: {pr_title}")
                print(f"Branch: {context.branch_name} → main")
                print(f"URL: {context.pr_url}")
                print('='*60 + '\n')
                
                return True
            else:
                error = result.get("error", "Unknown error")
                self.log(context, "PR creation failed", str(error), False)
                context.add_error(f"PR creation failed: {error}")
                return False
            
        except Exception as e:
            self.log(context, "Failed to create PR", str(e), False)
            context.add_error(f"PR creation failed: {e}")
            return False
    
    def get_current_branch(self) -> str:
        """Get the current branch name"""
        if not self.repo:
            self.initialize_repo()
        
        if self.repo:
            return self.repo.active_branch.name
        return "unknown"
    
    def get_repo_status(self) -> Dict[str, Any]:
        """Get repository status"""
        if not self.repo:
            self.initialize_repo()
        
        if not self.repo:
            return {"error": "Repository not initialized"}
        
        return {
            "branch": self.repo.active_branch.name,
            "is_dirty": self.repo.is_dirty(),
            "untracked_files": self.repo.untracked_files,
            "changed_files": [item.a_path for item in self.repo.index.diff(None)]
        }
