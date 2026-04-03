"""
Intent Classifier for Cortex AI Agent
Analyzes user messages to determine intent and routing decisions
"""

import re
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

from src.ai.intent.types import (
    IntentType, SubIntent, IntentClassification,
    INTENT_PATTERNS, COMPLEXITY_INDICATORS, 
    TERMINAL_SUB_PATTERNS, CODE_SUB_PATTERNS,
    PatternMatch
)
from src.utils.logger import get_logger

log = get_logger("intent_classifier")


class IntentClassifier:
    """
    Classifies user messages into intents for agent routing.
    Uses regex pattern matching and keyword analysis.
    """
    
    def __init__(self):
        self._compile_patterns()
        self._history: List[IntentClassification] = []
        log.info("IntentClassifier initialized")
    
    def _compile_patterns(self):
        """Compile regex patterns for performance."""
        self._compiled_patterns: Dict[IntentType, List[re.Pattern]] = {}
        
        for intent, patterns in INTENT_PATTERNS.items():
            self._compiled_patterns[intent] = [
                re.compile(pattern, re.IGNORECASE) for pattern in patterns
            ]
        
        # Compile complexity patterns
        self._complexity_patterns = {
            level: [re.compile(p, re.IGNORECASE) for p in patterns]
            for level, patterns in COMPLEXITY_INDICATORS.items()
        }
        
        # Compile sub-intent patterns
        self._terminal_sub_patterns = {
            sub_intent: [re.compile(p, re.IGNORECASE) for p in patterns]
            for sub_intent, patterns in TERMINAL_SUB_PATTERNS.items()
        }
        
        self._code_sub_patterns = {
            sub_intent: [re.compile(p, re.IGNORECASE) for p in patterns]
            for sub_intent, patterns in CODE_SUB_PATTERNS.items()
        }
    
    def classify(self, message: str) -> IntentClassification:
        """
        Classify a user message into intent categories.
        
        Args:
            message: The user's input message
            
        Returns:
            IntentClassification with primary intent, sub-intents, and metadata
        """
        log.debug(f"Classifying message: {message[:100]}...")
        
        # Extract patterns and matches
        matches = self._extract_patterns(message)
        
        # Determine primary intent based on matches
        primary_intent = self._determine_primary_intent(matches)
        
        # Extract sub-intents
        sub_intents = self._extract_sub_intents(message, primary_intent)
        
        # Calculate confidence
        confidence = self._calculate_confidence(matches, primary_intent)
        
        # Detect requirements
        requires_terminal = self._detect_terminal_intent(message, matches)
        requires_code_tools = self._detect_code_intent(message, matches)
        requires_web_search = self._detect_web_search_intent(message)
        
        # Determine complexity
        complexity = self._determine_complexity(message)
        
        # Build metadata
        metadata = {
            "pattern_matches": len(matches),
            "matched_patterns": [m.pattern for m in matches[:5]],  # Top 5
            "message_length": len(message),
            "word_count": len(message.split()),
        }
        
        classification = IntentClassification(
            primary_intent=primary_intent,
            sub_intents=sub_intents,
            confidence=confidence,
            requires_terminal=requires_terminal,
            requires_code_tools=requires_code_tools,
            requires_web_search=requires_web_search,
            complexity=complexity,
            metadata=metadata
        )
        
        # Store in history
        self._history.append(classification)
        if len(self._history) > 100:
            self._history.pop(0)
        
        log.info(
            f"Classified as {primary_intent.value} "
            f"(confidence: {confidence:.2f}, "
            f"terminal: {requires_terminal}, "
            f"code: {requires_code_tools})"
        )
        
        return classification
    
    def _extract_patterns(self, message: str) -> List[PatternMatch]:
        """Extract all matching patterns from message."""
        matches = []
        
        for intent, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                match = pattern.search(message)
                if match:
                    matches.append(PatternMatch(
                        pattern=pattern.pattern,
                        intent=intent,
                        confidence=0.8,  # Base confidence for pattern match
                        matched_text=match.group(0)
                    ))
        
        return matches
    
    def _determine_primary_intent(self, matches: List[PatternMatch]) -> IntentType:
        """Determine primary intent from pattern matches."""
        if not matches:
            return IntentType.GENERAL_CONVERSATION
        
        # Count matches per intent
        intent_counts: Dict[IntentType, int] = {}
        for match in matches:
            intent_counts[match.intent] = intent_counts.get(match.intent, 0) + 1
        
        # Get intent with most matches
        primary_intent = max(intent_counts.items(), key=lambda x: x[1])[0]
        
        return primary_intent
    
    def _extract_sub_intents(self, message: str, primary_intent: IntentType) -> List[SubIntent]:
        """Extract sub-intents based on primary intent."""
        sub_intents = []
        
        # Check terminal sub-intents
        if primary_intent in [IntentType.TERMINAL_COMMAND, IntentType.SYSTEM_MONITORING]:
            for sub_intent, patterns in self._terminal_sub_patterns.items():
                for pattern in patterns:
                    if pattern.search(message):
                        sub_intents.append(sub_intent)
                        break
        
        # Check code sub-intents
        if primary_intent in [IntentType.CODE_GENERATION, IntentType.CODE_ANALYSIS]:
            for sub_intent, patterns in self._code_sub_patterns.items():
                for pattern in patterns:
                    if pattern.search(message):
                        sub_intents.append(sub_intent)
                        break
        
        # Check complexity sub-intents
        if self._complexity_patterns["complex"]:
            for pattern in self._complexity_patterns["complex"]:
                if pattern.search(message):
                    sub_intents.append(SubIntent.COMPLEX)
                    break
        
        if self._complexity_patterns["multi_step"]:
            for pattern in self._complexity_patterns["multi_step"]:
                if pattern.search(message):
                    sub_intents.append(SubIntent.MULTI_STEP)
                    break
        
        return list(set(sub_intents))  # Remove duplicates
    
    def _calculate_confidence(self, matches: List[PatternMatch], primary_intent: IntentType) -> float:
        """Calculate confidence score for classification."""
        if not matches:
            return 0.3  # Low confidence for no matches
        
        # Base confidence from number of matches
        base_confidence = min(0.5 + (len(matches) * 0.1), 0.9)
        
        # Boost if multiple matches for same intent
        intent_matches = [m for m in matches if m.intent == primary_intent]
        if len(intent_matches) > 1:
            base_confidence += 0.1
        
        return min(base_confidence, 1.0)
    
    def _detect_terminal_intent(self, message: str, matches: List[PatternMatch]) -> bool:
        """Detect if message requires terminal access."""
        # Check if any terminal-related intent matched
        terminal_intents = [
            IntentType.TERMINAL_COMMAND,
            IntentType.SYSTEM_MONITORING,
            IntentType.BUILD_PROCESS,
        ]
        
        for match in matches:
            if match.intent in terminal_intents:
                return True
        
        # Check for explicit terminal commands
        terminal_keywords = [
            r'\brun\b', r'\bexecute\b', r'\bcommand\b', r'\bterminal\b',
            r'\bshell\b', r'\bbash\b', r'\bcmd\b', r'\bconsole\b',
        ]
        
        for keyword in terminal_keywords:
            if re.search(keyword, message, re.IGNORECASE):
                return True
        
        return False
    
    def _detect_code_intent(self, message: str, matches: List[PatternMatch]) -> bool:
        """Detect if message requires code tools."""
        code_intents = [
            IntentType.CODE_GENERATION,
            IntentType.CODE_ANALYSIS,
            IntentType.DEBUGGING,
            IntentType.REFACTORING,
        ]
        
        for match in matches:
            if match.intent in code_intents:
                return True
        
        # Check for code-related keywords
        code_keywords = [
            r'\bcode\b', r'\bfunction\b', r'\bclass\b', r'\bmethod\b',
            r'\bfile\b', r'\bwrite\b', r'\bedit\b', r'\bmodify\b',
            r'\bcreate\b.*\bfile\b', r'\bread\b.*\bfile\b',
            r'\bindex\b', r'\bexplore\b', r'\bscan\b', r'\bmap\b',
            r'\bproject\b', r'\bcodebase\b', r'\bstructure\b',
        ]
        
        for keyword in code_keywords:
            if re.search(keyword, message, re.IGNORECASE):
                return True
        
        return False
    
    def _detect_web_search_intent(self, message: str) -> bool:
        """Detect if message requires web search."""
        web_patterns = [
            r'\bsearch\b.*\bonline\b', r'\bgoogle\b', r'\blook\s+up\b',
            r'\bfind\b.*\bonline\b', r'\bweb\b.*\bsearch\b',
            r'\bdocumentation\b.*\bfor\b', r'\bwhat\s+is\b.*\b(API|library)\b',
        ]
        
        for pattern in web_patterns:
            if re.search(pattern, message, re.IGNORECASE):
                return True
        
        return False
    
    def _determine_complexity(self, message: str) -> str:
        """Determine task complexity."""
        # Check for multi-step indicators
        for pattern in self._complexity_patterns.get("multi_step", []):
            if pattern.search(message):
                return "multi_step"
        
        # Check for complex indicators
        for pattern in self._complexity_patterns.get("complex", []):
            if pattern.search(message):
                return "complex"
        
        return "simple"
    
    def get_recent_classifications(self, count: int = 10) -> List[IntentClassification]:
        """Get recent classifications for analysis."""
        return self._history[-count:]
    
    def analyze_conversation_context(self) -> Dict[str, Any]:
        """Analyze recent conversation for context."""
        if not self._history:
            return {"context": "new_conversation"}
        
        recent = self._history[-5:]
        intents = [c.primary_intent for c in recent]
        
        # Check for repeated intents
        intent_counts = {}
        for intent in intents:
            intent_counts[intent] = intent_counts.get(intent, 0) + 1
        
        most_common = max(intent_counts.items(), key=lambda x: x[1])
        
        return {
            "context": "ongoing" if len(recent) > 2 else "new",
            "dominant_intent": most_common[0].value if most_common[1] > 2 else None,
            "recent_complexity": [c.complexity for c in recent],
            "terminal_usage": sum(1 for c in recent if c.requires_terminal),
        }


# Singleton instance
_intent_classifier = None


def get_intent_classifier() -> IntentClassifier:
    """Get singleton instance of IntentClassifier."""
    global _intent_classifier
    if _intent_classifier is None:
        _intent_classifier = IntentClassifier()
    return _intent_classifier


# Convenience function
def classify_intent(message: str) -> IntentClassification:
    """Classify a message using the singleton classifier."""
    return get_intent_classifier().classify(message)
