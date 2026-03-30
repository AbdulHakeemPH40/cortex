"""
Tool Selection Engine for Cortex AI Agent
Intelligently selects tools based on intent, context, and historical success
"""

import re
from typing import Dict, List, Optional, Any
from collections import defaultdict

from src.ai.tools.selection.types import (
    ToolDefinition, ToolScore, ToolSelection, ToolSelectionContext,
    ExecutionHistory
)
from src.ai.tools.selection.registry import get_tool_registry
from src.ai.intent.types import IntentClassification
from src.utils.logger import get_logger

log = get_logger("tool_selector")


class ToolSelector:
    """
    Selects the most appropriate tools for a given intent.
    Uses scoring based on keywords, context, and historical success.
    """
    
    def __init__(self):
        self.registry = get_tool_registry()
        self._history: List[ExecutionHistory] = []
        self._max_history = 1000
        log.info("ToolSelector initialized")
    
    async def select_tools(
        self,
        intent: IntentClassification,
        context: ToolSelectionContext,
        max_tools: int = 3
    ) -> List[ToolScore]:
        """
        Select the best tools for the given intent and context.
        
        Args:
            intent: Classified user intent
            context: Current execution context
            max_tools: Maximum number of tools to return
            
        Returns:
            List of ToolScore objects, sorted by score
        """
        log.debug("Selecting tools for intent: %s", intent.primary_intent.value)
        
        # Get all available tools
        all_tools = self.registry.list_all()
        
        # Score each tool
        scored_tools = []
        for tool in all_tools:
            score = await self._score_tool(tool, intent, context)
            if score.score > 0.15:  # Only consider tools above threshold (lowered from 0.3)
                scored_tools.append(score)
        
        # Sort by score and limit
        scored_tools.sort(key=lambda x: x.score, reverse=True)
        selected = scored_tools[:max_tools]
        
        log.info(
            "Selected %d tools for %s: %s",
            len(selected),
            intent.primary_intent.value,
            [s.tool.name for s in selected]
        )
        
        return selected
    
    async def _score_tool(
        self,
        tool: ToolDefinition,
        intent: IntentClassification,
        context: ToolSelectionContext
    ) -> ToolScore:
        """
        Calculate a score for a tool based on multiple factors.
        
        Scoring weights:
        - Keyword matching: 40%
        - Context matching: 30%
        - Historical success: 20%
        - Complexity adjustment: 10%
        """
        scores = {}
        
        # 1. Keyword matching (40%)
        scores['keyword'] = self._calculate_keyword_score(tool, intent)
        
        # 2. Context matching (30%)
        scores['context'] = self._calculate_context_score(tool, context)
        
        # 3. Historical success (20%)
        scores['history'] = await self._get_historical_score(tool, intent)
        
        # 4. Complexity adjustment (10%)
        scores['complexity'] = self._calculate_complexity_score(tool, intent)
        
        # Calculate weighted total
        total_score = (
            scores['keyword'] * 0.4 +
            scores['context'] * 0.3 +
            scores['history'] * 0.2 +
            scores['complexity'] * 0.1
        )
        
        # Ensure score is between 0 and 1
        total_score = max(0.0, min(1.0, total_score))
        
        # Generate reasoning
        reasoning = self._generate_reasoning(tool, scores)
        
        # Estimate complexity
        estimated_complexity = self._estimate_tool_complexity(tool, intent)
        
        return ToolScore(
            tool=tool,
            score=total_score,
            reasoning=reasoning,
            estimated_complexity=estimated_complexity,
            confidence=min(scores['keyword'] + 0.3, 0.95)
        )
    
    def _calculate_keyword_score(
        self,
        tool: ToolDefinition,
        intent: IntentClassification
    ) -> float:
        """
        Calculate keyword matching score using Jaccard similarity.
        """
        # Extract keywords from intent
        intent_text = intent.primary_intent.value + " " + " ".join(
            s.value for s in intent.sub_intents
        )
        intent_keywords = self._extract_keywords(intent_text)
        
        # Get tool keywords
        tool_keywords = set(k.lower() for k in tool.keywords)
        
        # Intent-to-tool keyword mappings for better matching
        intent_tool_mappings = {
            "terminal_command": ["bash", "command", "run", "execute", "shell"],
            "system_monitoring": ["bash", "command", "check"],
            "code_generation": ["write", "edit", "file", "create"],
            "code_analysis": ["read", "grep", "lsp", "file"],
            "debugging": ["read", "grep", "edit", "bash"],
            "refactoring": ["edit", "read", "grep"],
            "build_process": ["bash", "task", "command"],
            "research": ["websearch", "webfetch", "grep"],
            "documentation": ["webfetch", "read"],
            "general_conversation": ["question"],
        }
        
        # Add mapped keywords for this intent
        intent_str = intent.primary_intent.value
        if intent_str in intent_tool_mappings:
            mapped_keywords = intent_tool_mappings[intent_str]
            intent_keywords.extend(mapped_keywords)
        
        # Calculate Jaccard similarity
        if not tool_keywords:
            return 0.4  # Base score for tools without keywords (increased)
        
        intent_keyword_set = set(intent_keywords)
        intersection = len(intent_keyword_set & tool_keywords)
        union = len(intent_keyword_set | tool_keywords)
        
        if union == 0:
            return 0.2  # Give a small base score
        
        score = intersection / union
        
        # Boost score if any direct keyword match
        if intersection > 0:
            score = max(score, 0.4)
        
        return score
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from text."""
        # Clean and split text
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        
        # Stop words to filter out
        stop_words = {
            'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all',
            'can', 'had', 'her', 'was', 'one', 'our', 'out', 'day',
            'get', 'has', 'him', 'his', 'how', 'its', 'may', 'new',
            'now', 'old', 'see', 'two', 'who', 'boy', 'did', 'she',
            'use', 'her', 'way', 'many', 'oil', 'sit', 'set', 'run',
            'eat', 'far', 'sea', 'eye', 'ago', 'off', 'too', 'any',
            'say', 'man', 'try', 'ask', 'end', 'why', 'let', 'put',
            'say', 'she', 'try', 'way', 'own', 'say', 'too', 'old'
        }
        
        # Filter stop words and short words
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        
        return keywords
    
    def _calculate_context_score(
        self,
        tool: ToolDefinition,
        context: ToolSelectionContext
    ) -> float:
        """
        Calculate context matching score.
        """
        score = 0.0
        
        # Check workspace type relevance
        if tool.category.value == context.workspace_type:
            score += 0.3
        
        # Check for open files (file operations need open files)
        if tool.category.value == "file" and context.has_open_files:
            score += 0.3
        
        # Check for search patterns
        if tool.name in ["grep", "glob"] and context.search_patterns:
            score += 0.4
        
        # Check for terminal-focused workspace
        if tool.name == "bash" and context.workspace_type == "terminal_focused":
            score += 0.4
        
        # General boosts based on tool utility
        if tool.name in ["read", "grep", "bash"]:
            score += 0.2  # These are commonly used tools
        
        # Base score (increased)
        score += 0.2
        
        return min(score, 1.0)
    
    async def _get_historical_score(
        self,
        tool: ToolDefinition,
        intent: IntentClassification
    ) -> float:
        """
        Calculate score based on historical success rate.
        """
        # Find relevant historical executions
        relevant = [
            h for h in self._history
            if h.tool_name == tool.name
            and self._similar_intent(h.intent, intent.primary_intent.value)
        ]
        
        if not relevant:
            return 0.5  # Default score for no history
        
        # Calculate success rate
        successful = sum(1 for h in relevant if h.success)
        success_rate = successful / len(relevant)
        
        # Weight by recency (recent executions count more)
        weighted_score = 0.0
        total_weight = 0.0
        
        for i, history in enumerate(reversed(relevant[-10:])):  # Last 10
            weight = (i + 1) / 10  # More recent = higher weight
            if history.success:
                weighted_score += weight
            total_weight += weight
        
        if total_weight == 0:
            return success_rate
        
        return weighted_score / total_weight
    
    def _similar_intent(self, intent1: str, intent2: str) -> bool:
        """Check if two intents are similar."""
        return intent1.lower() == intent2.lower()
    
    def _calculate_complexity_score(
        self,
        tool: ToolDefinition,
        intent: IntentClassification
    ) -> float:
        """
        Calculate complexity adjustment score.
        """
        # Prefer simpler tools for simple tasks
        if intent.complexity == "simple" and tool.complexity == "simple":
            return 0.8
        
        # Prefer appropriate complexity for complex tasks
        if intent.complexity == "complex" and tool.complexity in ["medium", "complex"]:
            return 0.9
        
        if intent.complexity == "multi_step" and tool.complexity == "complex":
            return 1.0
        
        # Slight penalty for complexity mismatch
        return 0.6
    
    def _generate_reasoning(
        self,
        tool: ToolDefinition,
        scores: Dict[str, float]
    ) -> str:
        """Generate human-readable reasoning for tool selection."""
        reasons = []
        
        if scores['keyword'] > 0.5:
            reasons.append("strong keyword match")
        elif scores['keyword'] > 0.3:
            reasons.append("keyword match")
        
        if scores['context'] > 0.5:
            reasons.append("contextually appropriate")
        
        if scores['history'] > 0.7:
            reasons.append("historically successful")
        elif scores['history'] < 0.3:
            reasons.append("limited historical data")
        
        if scores['complexity'] > 0.8:
            reasons.append("complexity-optimized")
        
        if not reasons:
            reasons.append("general applicability")
        
        return f"Selected due to {', '.join(reasons)}"
    
    def _estimate_tool_complexity(
        self,
        tool: ToolDefinition,
        intent: IntentClassification
    ) -> str:
        """Estimate execution complexity for the tool."""
        if tool.complexity == "complex":
            return "complex"
        elif tool.complexity == "medium":
            return "medium"
        elif intent.complexity == "multi_step":
            return "medium"
        else:
            return "simple"
    
    def record_execution(
        self,
        tool_name: str,
        intent: str,
        success: bool,
        execution_time_ms: int,
        context: Optional[Dict[str, Any]] = None
    ):
        """Record tool execution for learning."""
        history = ExecutionHistory(
            tool_name=tool_name,
            intent=intent,
            success=success,
            execution_time_ms=execution_time_ms,
            context=context or {}
        )
        
        self._history.append(history)
        
        # Limit history size
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        
        log.debug(
            "Recorded execution: %s (success=%s, time=%dms)",
            tool_name, success, execution_time_ms
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get tool selection statistics."""
        if not self._history:
            return {"total_executions": 0}
        
        stats = defaultdict(lambda: {"total": 0, "successful": 0})
        
        for h in self._history:
            stats[h.tool_name]["total"] += 1
            if h.success:
                stats[h.tool_name]["successful"] += 1
        
        return {
            "total_executions": len(self._history),
            "tool_stats": dict(stats)
        }


# Singleton instance
_tool_selector = None


def get_tool_selector() -> ToolSelector:
    """Get singleton instance of ToolSelector."""
    global _tool_selector
    if _tool_selector is None:
        _tool_selector = ToolSelector()
    return _tool_selector


# Convenience function
async def select_tools_for_intent(
    intent: IntentClassification,
    workspace_path: Optional[str] = None,
    max_tools: int = 3
) -> List[ToolScore]:
    """Select tools using the singleton selector."""
    context = ToolSelectionContext(
        workspace_path=workspace_path,
        has_open_files=True  # Assume files are open for now
    )
    return await get_tool_selector().select_tools(intent, context, max_tools)
