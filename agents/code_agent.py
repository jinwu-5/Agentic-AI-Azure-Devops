from core import BaseAgent, WorkflowContext, AgentState
from typing import Dict, Any, List
import os


class CodeAgent(BaseAgent):
    """Code Agent - Writes implementation code"""
    
    def __init__(self, ai_client, deployment_name, mcp_manager, rag_service, repository_path: str):
        super().__init__("CodeAgent", ai_client, deployment_name)
        self.mcp_manager = mcp_manager
        self.rag = rag_service
        self.repository_path = repository_path
    
    async def execute(self, context: WorkflowContext) -> bool:
        """Execute full implementation from execution plan"""
        plan = context.execution_plan.get("implementation", {})
        steps = plan.get("implementation_steps", [])
        
        if not steps:
            self.log(context, "No implementation steps", "Plan is empty", False)
            return False
        
        for step in steps:
            if step.get("agent") == "CodeAgent":
                success = await self.execute_step(context, step)
                if not success:
                    return False
        
        return True
    
    async def execute_step(self, context: WorkflowContext, step: Dict) -> bool:
        """Execute a single implementation step"""
        step_num = step.get("step")
        description = step.get("description")
        files_to_create = self._normalize_file_entries(step.get("files_to_create"))
        files_to_update = self._normalize_file_entries(step.get("files_to_update"))

        self.log(context, f"Executing step {step_num}", description)
        context.current_state = AgentState.IMPLEMENTING

        if not files_to_create and not files_to_update:
            self.log(context, "No target files", "Step lacks files_to_create or files_to_update", False)
            return False

        rag_context = await self._get_rag_context(description)

        for entry in files_to_create:
            instructions = entry.get("instructions") or [description]
            success = await self.create_file(
                context,
                entry["path"],
                description,
                instructions,
                rag_context
            )
            if not success:
                return False

        for entry in files_to_update:
            file_path = entry["path"]
            instructions = entry.get("instructions") or [description]

            # Check if file was already modified in this execution
            if file_path in context.implementation_files:
                print(f"⚠️  Warning: {file_path} was already modified in a previous step")
                print(f"  Combining instructions to avoid sequential overwrites")
                # Merge instructions from current and previous modifications
                instructions.append(f"Previous modification in this workflow: {description}")

            success = await self.update_file(
                context,
                file_path,
                description,
                instructions,
                rag_context
            )
            if not success:
                return False

        return True
    
    async def _get_rag_context(self, description: str) -> str:
        """Get relevant code context from RAG"""
        results = self.rag.search(description, n_results=3)
        
        if not results:
            return "No existing code patterns found."
        
        context = "Existing code patterns in the repository:\n\n"
        for i, result in enumerate(results, 1):
            context += f"--- Pattern {i}: {result['file_path']} ---\n"
            context += result['content'][:300] + "...\n\n"
        
        return context
    
    async def create_file(self, context: WorkflowContext,
                         file_path: str, description: str,
                         instructions: List[str],
                         rag_context: str) -> bool:
        """Create a new file with AI-generated content"""
        self.log(context, "Creating file", file_path)

        structure = self.rag.get_project_structure()

        system_prompt = """You are an expert software engineer writing production-quality code.

            Write COMPLETE, working code - not pseudocode or placeholders."""

        instructions_text = '\n'.join(f"- {item}" for item in instructions)

        user_prompt = f"""Create a complete implementation for this file:

            File: {file_path}
            Purpose: {description}
            
            Work Item: {context.work_item_title}
            
            Implementation Notes:
            {instructions_text}
            
            Project Context:
            - File types in project: {list(structure['file_types'].keys())}
            
            {rag_context}
            
            Respond with ONLY the file content, no explanations."""

        try:
            code_content = await self.call_ai(system_prompt, user_prompt,
                                             temperature=0.3, max_tokens=8000)
            code_content = self._clean_ai_response(code_content)

            # Validation: Check basic completeness
            if len(code_content.strip()) < 50:
                self.log(context, "File creation failed", "Generated content too short", False)
                print(f"✗ Generated content is suspiciously short ({len(code_content)} chars)")
                return False

            # Write file directly with Python (bypass MCP)
            full_path = os.path.join(self.repository_path, file_path)
            target_dir = os.path.dirname(full_path) or self.repository_path
            os.makedirs(target_dir, exist_ok=True)

            with open(full_path, 'w') as f:
                f.write(code_content)

            # Verify
            if os.path.exists(full_path):
                context.implementation_files[file_path] = code_content
                self.log(context, "File created", f"{file_path} ({len(code_content)} chars)")
                print(f"✓ Created: {full_path}")
                return True
            else:
                self.log(context, "File creation failed", file_path, False)
                return False
        
        except Exception as e:
            print(f"✗ Error: {e}")
            self.log(context, "Error creating file", str(e), False)
            return False

    async def update_file(self, context: WorkflowContext,
                          file_path: str, description: str,
                          instructions: List[str],
                          rag_context: str) -> bool:
        """Update an existing file using AI-generated changes"""
        self.log(context, "Updating file", file_path)

        full_path = os.path.join(self.repository_path, file_path)
        if not os.path.exists(full_path):
            self.log(context, "File not found", file_path, False)
            return False

        try:
            with open(full_path, 'r') as f:
                current_content = f.read()
        except Exception as e:
            self.log(context, "Failed to read file", f"{file_path}: {e}", False)
            return False

        file_size = len(current_content)

        # Determine best editing strategy
        strategy = self._select_edit_strategy(file_size, description, instructions)

        print(f"  File: {file_size} chars, Strategy: {strategy}")

        if strategy == "diff":
            return await self._update_file_diff_based(
                context, file_path, full_path, current_content,
                description, instructions, rag_context
            )
        else:
            return await self._update_file_full_rewrite(
                context, file_path, full_path, current_content,
                description, instructions, rag_context
            )

    def _select_edit_strategy(self, file_size: int, description: str,
                              instructions: List[str]) -> str:
        """Determine the best editing strategy based on file characteristics"""

        # Check if changes are localized (specific keywords suggest targeted edits)
        instructions_text = ' '.join(instructions).lower()
        localized_keywords = [
            'add function', 'add method', 'add class',
            'update function', 'modify function',
            'add css', 'add style', 'add button',
            'insert', 'append', 'prepend'
        ]

        is_localized = any(keyword in instructions_text for keyword in localized_keywords)

        # Use diff-based for large files OR localized changes
        if file_size > 10000 or is_localized:
            return "diff"

        return "full"

    async def _update_file_diff_based(self, context: WorkflowContext,
                                      file_path: str, full_path: str,
                                      current_content: str, description: str,
                                      instructions: List[str],
                                      rag_context: str) -> bool:
        """Update file using diff/patch approach for targeted changes"""

        instructions_text = '\n'.join(f"- {item}" for item in instructions)
        structure = self.rag.get_project_structure()

        system_prompt = """You are an expert software engineer creating surgical edits to code.

IMPORTANT: Instead of rewriting the entire file, provide SPECIFIC CHANGES in this format:

1. Identify the EXACT location where changes should be made
2. Provide the code to ADD or REPLACE
3. Be precise about insertion points

Response format:
```
CHANGE 1: [Brief description]
LOCATION: [Specific line/section identifier]
ACTION: [INSERT_BEFORE / INSERT_AFTER / REPLACE]
CODE:
[exact code to insert/replace]
---
CHANGE 2: ...
```

Example for adding CSS:
```
CHANGE 1: Add dark theme CSS
LOCATION: After the light theme styles, before </style>
ACTION: INSERT_BEFORE
CODE:
        /* Dark theme styles */
        @media (prefers-color-scheme: dark) {
            body { background: #121212; color: #e0e0e0; }
        }
---
```"""

        # For diff-based, show a preview of the file to help AI locate things
        file_preview = current_content
        if len(current_content) > 3000:
            # For large files, show first 1500 and last 1500 chars
            file_preview = (current_content[:1500] +
                          f"\n\n... ({len(current_content) - 3000} chars omitted) ...\n\n" +
                          current_content[-1500:])

        user_prompt = f"""Make targeted changes to this file:

File: {file_path}
Purpose: {description}

Instructions:
{instructions_text}

Current file is {len(current_content)} characters. DO NOT rewrite the entire file.
Provide ONLY the specific changes needed using the format specified.

CURRENT FILE CONTENT (for reference when specifying LOCATION):
```
{file_preview}
```

Project Context:
{rag_context}

CRITICAL: For LOCATION, copy the EXACT text from the file above where the change should happen.
Focus on making minimal, precise edits."""

        try:
            # Use much smaller token limit since we're not rewriting whole file
            print(f"  Requesting targeted changes from AI (max 4000 tokens)...")
            diff_instructions = await self.call_ai(system_prompt, user_prompt,
                                                   temperature=0.25, max_tokens=4000,
                                                   timeout=60)  # Shorter timeout for diffs
            diff_instructions = self._clean_ai_response(diff_instructions)
            print(f"  ✓ Received diff instructions ({len(diff_instructions)} chars)")

            # Apply the diff instructions to get updated content
            updated_content = self._apply_diff_instructions(
                current_content, diff_instructions, file_path
            )

            if updated_content is None:
                print(f"  ⚠️  Diff strategy failed, falling back to full rewrite")
                return await self._update_file_full_rewrite(
                    context, file_path, full_path, current_content,
                    description, instructions, rag_context
                )

            # Check for no-op changes
            if updated_content == current_content:
                print(f"  ⚠️  Diff produced no changes (content identical)")
                print(f"  This suggests diff strategy failed - falling back to full rewrite")
                return await self._update_file_full_rewrite(
                    context, file_path, full_path, current_content,
                    description, instructions, rag_context
                )

            # Check for minimal changes (less than 0.5% difference)
            change_pct = ((len(updated_content) - len(current_content)) / len(current_content)) * 100
            if abs(change_pct) < 0.5 and len(updated_content) > 1000:
                # For large files, minimal change might indicate failure
                # Check if actual content differs meaningfully
                lines_changed = sum(1 for a, b in zip(current_content.split('\n'),
                                                     updated_content.split('\n')) if a != b)
                if lines_changed < 2:
                    print(f"  ⚠️  Suspiciously small change ({lines_changed} lines changed)")
                    print(f"  This might indicate diff strategy failed - falling back to full rewrite")
                    return await self._update_file_full_rewrite(
                        context, file_path, full_path, current_content,
                        description, instructions, rag_context
                    )

            # Validation
            validation_result = self._validate_file_output(
                file_path, current_content, updated_content
            )

            if not validation_result['valid']:
                error_msg = f"Validation failed: {validation_result['error']}"
                print(f"  ⚠️  {error_msg}, falling back to full rewrite")
                return await self._update_file_full_rewrite(
                    context, file_path, full_path, current_content,
                    description, instructions, rag_context
                )

            with open(full_path, 'w') as f:
                f.write(updated_content)

            context.implementation_files[file_path] = updated_content
            self.log(context, "File updated (diff)",
                    f"{file_path} ({len(updated_content)} chars, {change_pct:+.1f}%)")
            print(f"✓ Updated: {full_path} ({change_pct:+.1f}% change, substantive)")
            return True

        except Exception as e:
            print(f"✗ Diff-based edit error: {e}, falling back to full rewrite")
            return await self._update_file_full_rewrite(
                context, file_path, full_path, current_content,
                description, instructions, rag_context
            )

    async def _update_file_full_rewrite(self, context: WorkflowContext,
                                        file_path: str, full_path: str,
                                        current_content: str, description: str,
                                        instructions: List[str],
                                        rag_context: str) -> bool:
        """Update file by rewriting complete content (original method)"""

        file_size = len(current_content)
        estimated_tokens = file_size // 3
        max_tokens = min(max(8000, estimated_tokens + 2000), 16000)

        instructions_text = '\n'.join(f"- {item}" for item in instructions)
        structure = self.rag.get_project_structure()

        system_prompt = """You are an expert software engineer editing an existing file.
            Apply the requested changes while preserving intended behaviour. Return the full updated file content."""

        user_prompt = f"""Update the existing file according to the following instructions:

            File: {file_path}
            Purpose: {description}

            Work Item: {context.work_item_title}

            Implementation Notes:
            {instructions_text}

            Current Content (MUST preserve ALL content in output):
            {current_content}

            Project Context:
            - File types in project: {list(structure['file_types'].keys())}

            {rag_context}

            CRITICAL: Respond with the COMPLETE file content, no truncation, no placeholders, no explanations."""

        try:
            print(f"  Requesting full file rewrite (max {max_tokens} tokens, ~{max_tokens//100}s)...")
            updated_content = await self.call_ai(system_prompt, user_prompt,
                                                temperature=0.25, max_tokens=max_tokens,
                                                timeout=max(180, max_tokens // 50))  # Dynamic timeout
            updated_content = self._clean_ai_response(updated_content)
            print(f"  ✓ Received updated content ({len(updated_content)} chars)")

            validation_result = self._validate_file_output(
                file_path, current_content, updated_content
            )

            if not validation_result['valid']:
                error_msg = f"Validation failed: {validation_result['error']}"
                self.log(context, "File validation failed", error_msg, False)
                print(f"✗ {error_msg}")
                print(f"  Original size: {len(current_content)} chars")
                print(f"  Generated size: {len(updated_content)} chars")
                return False

            with open(full_path, 'w') as f:
                f.write(updated_content)

            context.implementation_files[file_path] = updated_content
            self.log(context, "File updated", f"{file_path} ({len(updated_content)} chars)")
            print(f"✓ Updated: {full_path}")
            return True

        except Exception as e:
            print(f"✗ Error updating {file_path}: {e}")
            self.log(context, "Error updating file", str(e), False)
            return False

    def _clean_ai_response(self, content: str) -> str:
        """Strip markdown fences from AI responses"""
        if "```" not in content:
            return content

        in_code_block = False
        clean_lines: List[str] = []

        for line in content.splitlines():
            if line.strip().startswith('```'):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                clean_lines.append(line)

        if clean_lines:
            return '\n'.join(clean_lines)

        return content.replace('```', '')

    def _apply_diff_instructions(self, original_content: str,
                                  diff_instructions: str,
                                  file_path: str) -> str:
        """Parse and apply diff-style instructions to modify file content"""

        try:
            # Parse the diff instructions into structured changes
            changes = []
            current_change = {}

            for line in diff_instructions.split('\n'):
                line = line.strip()

                if line.startswith('CHANGE'):
                    if current_change:
                        changes.append(current_change)
                    current_change = {'description': line}
                    current_change['code_lines'] = []
                elif line.startswith('LOCATION:'):
                    current_change['location'] = line.replace('LOCATION:', '').strip()
                elif line.startswith('ACTION:'):
                    current_change['action'] = line.replace('ACTION:', '').strip()
                elif line.startswith('CODE:'):
                    current_change['in_code_block'] = True
                elif line == '---':
                    current_change['in_code_block'] = False
                elif current_change.get('in_code_block'):
                    current_change['code_lines'].append(line)

            if current_change:
                changes.append(current_change)

            if not changes:
                print(f"  ⚠️  No valid changes parsed from diff instructions")
                return None

            print(f"  Parsed {len(changes)} changes from diff instructions")

            # Apply changes to content
            modified_content = original_content
            changes_applied = 0
            changes_skipped = 0

            for i, change in enumerate(changes, 1):
                action = change.get('action', '').upper()
                location = change.get('location', '')
                code = '\n'.join(change.get('code_lines', []))

                print(f"    Change {i}: {action} at '{location[:50]}...'")

                # Try to find location using fuzzy matching
                found_location = self._find_location_fuzzy(modified_content, location)

                if not found_location:
                    print(f"      ⚠️  Location not found (tried exact + fuzzy), skipping")
                    changes_skipped += 1
                    continue

                if action == 'INSERT_BEFORE':
                    # Find location and insert before it
                    modified_content = modified_content.replace(
                        found_location, code + '\n' + found_location, 1
                    )
                    changes_applied += 1
                    print(f"      ✓ Applied")

                elif action == 'INSERT_AFTER':
                    # Find location and insert after it
                    modified_content = modified_content.replace(
                        found_location, found_location + '\n' + code, 1
                    )
                    changes_applied += 1
                    print(f"      ✓ Applied")

                elif action == 'REPLACE':
                    # Replace the location text with new code
                    modified_content = modified_content.replace(
                        found_location, code, 1
                    )
                    changes_applied += 1
                    print(f"      ✓ Applied")
                else:
                    print(f"      ⚠️  Unknown action '{action}', skipping")
                    changes_skipped += 1

            print(f"  Summary: {changes_applied} applied, {changes_skipped} skipped")

            # If no changes were applied, return None to trigger fallback
            if changes_applied == 0:
                print(f"  ⚠️  No changes were applied - diff strategy failed")
                return None

            return modified_content

        except Exception as e:
            print(f"  ⚠️  Error applying diff instructions: {e}")
            return None

    def _find_location_fuzzy(self, content: str, location: str) -> str:
        """Find location in content using exact match first, then fuzzy matching"""

        # Try 1: Exact match
        if location in content:
            return location

        # Try 2: Normalize whitespace and try again
        normalized_location = ' '.join(location.split())
        for line in content.split('\n'):
            normalized_line = ' '.join(line.split())
            if normalized_location in normalized_line:
                return line.strip()

        # Try 3: Find by partial match (first 30 chars)
        if len(location) > 30:
            prefix = location[:30].strip()
            for line in content.split('\n'):
                if prefix in line:
                    return line.strip()

        # Try 4: Find by keywords (extract words, match lines with most keywords)
        words = [w for w in location.split() if len(w) > 3][:5]
        if words:
            best_match = None
            best_score = 0

            for line in content.split('\n'):
                score = sum(1 for word in words if word in line)
                if score > best_score and score >= len(words) // 2:
                    best_score = score
                    best_match = line.strip()

            if best_match:
                return best_match

        return None

    def _validate_file_output(self, file_path: str, original: str, generated: str) -> Dict[str, Any]:
        """Validate that generated file content is complete and not truncated"""

        # Check 1: Minimum size - generated should not be drastically smaller
        size_ratio = len(generated) / max(len(original), 1)
        if size_ratio < 0.5:
            return {
                'valid': False,
                'error': f'Generated content too small ({size_ratio:.1%} of original)'
            }

        # Check 2: Empty or near-empty output
        if len(generated.strip()) < 100:
            return {
                'valid': False,
                'error': 'Generated content is nearly empty'
            }

        # Check 3: File type-specific validation
        if file_path.endswith('.py'):
            # Python files should have proper indentation and structure
            if generated.count('def ') == 0 and original.count('def ') > 0:
                return {
                    'valid': False,
                    'error': 'Python file missing function definitions'
                }
            # Check for incomplete strings
            if generated.rstrip().endswith(('"""', "'''")):
                pass  # Valid docstring ending
            elif generated.rstrip().endswith((':',)):
                return {
                    'valid': False,
                    'error': 'Python file ends with incomplete statement (:)'
                }

        elif file_path.endswith('.html') or file_path.endswith('.htm'):
            # HTML files must have closing tag
            if '</html>' not in generated.lower():
                return {
                    'valid': False,
                    'error': 'HTML file missing closing </html> tag'
                }
            # Check for unclosed tags
            open_tags = generated.count('<')
            close_tags = generated.count('>')
            if abs(open_tags - close_tags) > 2:  # Allow small discrepancy
                return {
                    'valid': False,
                    'error': f'HTML tag mismatch (open:{open_tags}, close:{close_tags})'
                }

        elif file_path.endswith('.json'):
            # JSON should be parseable
            import json
            try:
                json.loads(generated)
            except json.JSONDecodeError as e:
                return {
                    'valid': False,
                    'error': f'Invalid JSON: {str(e)}'
                }

        elif file_path.endswith(('.js', '.ts', '.jsx', '.tsx')):
            # JavaScript/TypeScript should have balanced braces
            open_braces = generated.count('{')
            close_braces = generated.count('}')
            if abs(open_braces - close_braces) > 1:
                return {
                    'valid': False,
                    'error': f'Brace mismatch (open:{open_braces}, close:{close_braces})'
                }

        # Check 4: Detect common truncation patterns
        truncation_indicators = [
            '...',  # Ellipsis at end
            '# ... rest of',
            '// ... rest of',
            '/* ... */',
            '[rest of the code]',
            '[previous code]',
            'max_tokens',  # Literally wrote about hitting limit
        ]

        last_100_chars = generated[-100:].lower()
        for indicator in truncation_indicators:
            if indicator.lower() in last_100_chars:
                return {
                    'valid': False,
                    'error': f'Truncation indicator found: "{indicator}"'
                }

        # All checks passed
        return {'valid': True, 'error': None}

    def _normalize_file_entries(self, files: Any) -> List[Dict[str, Any]]:
        """Normalize file entries from plan step"""
        normalized: List[Dict[str, Any]] = []
        if not files:
            return normalized

        if not isinstance(files, list):
            files = [files]

        for entry in files:
            if isinstance(entry, str):
                normalized.append({"path": entry, "instructions": []})
                continue

            if isinstance(entry, dict):
                path = entry.get("path") or entry.get("file") or entry.get("target")
                if not path:
                    continue
                instructions = entry.get("instructions", [])
                if isinstance(instructions, str):
                    instructions = [instructions]
                normalized.append({
                    "path": path,
                    "instructions": instructions
                })

        return normalized
