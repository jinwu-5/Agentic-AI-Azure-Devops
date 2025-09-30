from typing import Optional, Dict, Any
from openai import AzureOpenAI
import json

class BaseAgent:
    """Base class for all agents"""
    
    def __init__(self, name: str, ai_client: AzureOpenAI, deployment_name: str):
        self.name = name
        self.ai_client = ai_client
        self.deployment_name = deployment_name
    
    async def execute(self, context) -> bool:
        """Execute the agent's main task"""
        raise NotImplementedError("Subclasses must implement execute()")
    
    def log(self, context, action: str, result: Any, success: bool = True):
        """Helper to log actions"""
        context.add_log(self.name, action, result, success)
        print(f"[{self.name}] {action}: {result}")
    
    async def call_ai(self, system_prompt: str, user_prompt: str, 
                      temperature: float = 0.1, max_tokens: int = 2000) -> str:
        """Call Azure OpenAI"""
        try:
            response = self.ai_client.chat.completions.create(
                model=self.deployment_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"[{self.name}] AI call failed: {e}")
            return ""
    
    def extract_json(self, ai_response: str) -> Optional[Dict]:
        """Extract JSON from AI response"""
        try:
            if "```json" in ai_response:
                json_start = ai_response.find("```json") + 7
                json_end = ai_response.find("```", json_start)
                json_str = ai_response[json_start:json_end].strip()
            else:
                json_start = ai_response.find("{")
                json_end = ai_response.rfind("}") + 1
                json_str = ai_response[json_start:json_end]
            
            return json.loads(json_str)
        except Exception as e:
            print(f"[{self.name}] JSON extraction failed: {e}")
            return None
