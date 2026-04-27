"""
VisionAgentTool - Specialized agent tool for image analysis and OCR.

This tool processes images, extracts text via OCR, and stores structured
results in shared agent memory for multi-agent collaboration.
"""

from __future__ import annotations

import os
import logging
from typing import Dict, Any, Optional
from datetime import datetime

log = logging.getLogger(__name__)


class VisionAgentTool:
    """Specialized tool for image analysis and OCR."""
    
    name = "VisionAgent"
    description = "Analyze images, perform OCR, and extract structured visual data for use by other agents"
    
    async def execute(
        self,
        image_data: str,
        analysis_type: str = "full",
        store_in_memory: bool = True,
        session_id: Optional[str] = None,
        vision_model: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute vision analysis.
        
        Args:
            image_data: Base64 encoded image or file path
            analysis_type: Type of analysis (ocr, description, object_detection, full)
            store_in_memory: Whether to store results in shared memory
            session_id: Session identifier for memory storage
            vision_model: Mistral model to use (mistral-small-latest, mistral-medium-latest, mistral-large-latest)
            **kwargs: Additional parameters
            
        Returns:
            Dictionary with vision analysis results
        """
        try:
            log.info(f"VisionAgentTool executing: analysis_type={analysis_type}, store={store_in_memory}")
            
            # Import here to avoid circular dependencies
            from src.core.memory_types import VisionContext
            from src.core.agent_memory import get_memory_manager
            
            # Step 1: Call vision API (Mistral or SiliconFlow)
            result = await self._call_vision_api(image_data, analysis_type, vision_model)
            
            if not result.get("success"):
                log.error(f"Vision API call failed: {result.get('error')}")
                return {
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                    "vision_context": None
                }
            
            # Step 2: Structure the results
            vision_context = VisionContext(
                image_path=image_data[:50] + "..." if len(image_data) > 50 else image_data,
                ocr_text=result.get("ocr_text", ""),
                image_description=result.get("description", ""),
                detected_objects=result.get("objects", []),
                analysis_timestamp=datetime.now().isoformat(),
                vision_model_used=result.get("model_used", "mistral"),
                confidence_score=result.get("confidence", 0.0),
                analysis_type=analysis_type,
                session_id=session_id or ""
            )
            
            # Step 3: Store in shared memory if requested
            if store_in_memory and session_id:
                try:
                    memory_manager = get_memory_manager()
                    success = memory_manager.store_vision_context(vision_context)
                    if success:
                        log.info(f"Vision context stored for session {session_id}")
                except Exception as e:
                    log.error(f"Failed to store vision context: {e}")
            
            # Step 4: Return structured result
            return {
                "success": True,
                "vision_context": vision_context.to_dict(),
                "memory_stored": store_in_memory and session_id is not None,
                "session_id": session_id
            }
            
        except Exception as e:
            log.error(f"VisionAgentTool execution failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "vision_context": None
            }
    
    async def _call_vision_api(
        self,
        image_data: str,
        analysis_type: str,
        vision_model: Optional[str] = None
    ) -> Dict[str, Any]:
        """Call vision-capable API for image analysis.
        
        Uses Mistral or SiliconFlow vision APIs based on availability.
        
        Args:
            image_data: Base64 encoded image or file path
            analysis_type: Type of analysis requested
            vision_model: Mistral model to use (small/medium/large)
            
        Returns:
            Dictionary with API response
        """
        try:
            # Determine which provider to use
            provider = os.getenv("VISION_PROVIDER", "mistral").lower()
            
            if provider == "mistral":
                return await self._call_mistral_vision(image_data, analysis_type, vision_model)
            elif provider == "siliconflow":
                return await self._call_siliconflow_vision(image_data, analysis_type)
            else:
                # Default to Mistral
                return await self._call_mistral_vision(image_data, analysis_type, vision_model)
                
        except Exception as e:
            log.error(f"Vision API call failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _call_mistral_vision(
        self,
        image_data: str,
        analysis_type: str,
        vision_model: Optional[str] = None
    ) -> Dict[str, Any]:
        """Call Mistral vision API.
        
        Args:
            image_data: Base64 encoded image
            analysis_type: Type of analysis
            vision_model: Mistral model to use (default: mistral-large-latest)
            
        Returns:
            Parsed vision analysis result
        """
        import aiohttp
        
        api_key = os.getenv("MISTRAL_API_KEY", "")
        if not api_key:
            return {
                "success": False,
                "error": "MISTRAL_API_KEY not set"
            }
        
        # Use specified model or default to large
        model = vision_model or "mistral-large-latest"
        
        # Build prompt based on analysis type
        prompt = self._build_vision_prompt(analysis_type)
        
        # Prepare messages
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": image_data if image_data.startswith("data:") else f"data:image/png;base64,{image_data}"
                    }
                ]
            }
        ]
        
        # Call API
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.mistral.ai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": 0.1,
                        "max_tokens": 4000
                    }
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        
                        # Parse the structured response
                        parsed = self._parse_vision_response(content)
                        parsed["model_used"] = "mistral"
                        return parsed
                    else:
                        error_text = await response.text()
                        return {
                            "success": False,
                            "error": f"Mistral API error {response.status}: {error_text[:200]}"
                        }
                        
        except Exception as e:
            return {
                "success": False,
                "error": f"Mistral API call failed: {str(e)}"
            }
    
    async def _call_siliconflow_vision(
        self,
        image_data: str,
        analysis_type: str
    ) -> Dict[str, Any]:
        """Call SiliconFlow vision API (Qwen-VL).
        
        Args:
            image_data: Base64 encoded image
            analysis_type: Type of analysis
            
        Returns:
            Parsed vision analysis result
        """
        import aiohttp
        
        api_key = os.getenv("SILICONFLOW_API_KEY", "")
        if not api_key:
            return {
                "success": False,
                "error": "SILICONFLOW_API_KEY not set"
            }
        
        prompt = self._build_vision_prompt(analysis_type)
        
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data if image_data.startswith("data:") else f"data:image/png;base64,{image_data}"}
                    }
                ]
            }
        ]
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.siliconflow.cn/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "Qwen/Qwen3-VL-32B-Instruct",
                        "messages": messages,
                        "temperature": 0.1,
                        "max_tokens": 4000
                    }
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        
                        parsed = self._parse_vision_response(content)
                        parsed["model_used"] = "siliconflow"
                        return parsed
                    else:
                        error_text = await response.text()
                        return {
                            "success": False,
                            "error": f"SiliconFlow API error {response.status}: {error_text[:200]}"
                        }
                        
        except Exception as e:
            return {
                "success": False,
                "error": f"SiliconFlow API call failed: {str(e)}"
            }
    
    def _build_vision_prompt(self, analysis_type: str) -> str:
        """Build analysis prompt based on type.
        
        Args:
            analysis_type: Type of analysis
            
        Returns:
            Prompt string
        """
        if analysis_type == "ocr":
            return "Extract ALL text from this image. Preserve formatting and structure. Return only the extracted text."
        elif analysis_type == "description":
            return "Describe this image in detail. Include layout, objects, colors, and relationships between elements."
        elif analysis_type == "object_detection":
            return "List all objects and elements visible in this image. Include their positions and descriptions."
        else:  # full
            return """Analyze this image comprehensively and return structured results in this exact format:

## Vision Analysis Results

### OCR Text
[All extracted text]

### Image Description
[Detailed description]

### Detected Objects
- Object 1 (location, description)
- Object 2 (location, description)

### Key Findings
- Finding 1
- Finding 2

### Confidence
Overall confidence: 0.XX

### Notes
[Any uncertainties or special observations]
"""
    
    def _parse_vision_response(self, content: str) -> Dict[str, Any]:
        """Parse structured vision analysis response.
        
        Args:
            content: Raw API response text
            
        Returns:
            Parsed dictionary
        """
        result = {
            "success": True,
            "ocr_text": "",
            "description": "",
            "objects": [],
            "confidence": 0.0,
            "raw_response": content
        }
        
        try:
            # Simple parsing - extract sections
            lines = content.split("\n")
            current_section = None
            objects = []
            
            for line in lines:
                line = line.strip()
                
                if "### OCR Text" in line:
                    current_section = "ocr"
                elif "### Image Description" in line:
                    current_section = "description"
                elif "### Detected Objects" in line:
                    current_section = "objects"
                elif "### Key Findings" in line:
                    current_section = "findings"
                elif "Overall confidence:" in line:
                    # Extract confidence value
                    try:
                        conf_str = line.split(":")[1].strip()
                        result["confidence"] = float(conf_str)
                    except:
                        pass
                elif line.startswith("- ") and current_section == "objects":
                    objects.append(line[2:])
                elif current_section == "ocr" and line:
                    result["ocr_text"] += line + "\n"
                elif current_section == "description" and line:
                    result["description"] += line + " "
            
            result["objects"] = objects
            
        except Exception as e:
            log.error(f"Failed to parse vision response: {e}")
            # Return raw content if parsing fails
            result["description"] = content
        
        return result


# Tool definition for registration
VISION_AGENT_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "VisionAgent",
        "description": "Analyze images, perform OCR, and extract structured visual data. Results are stored in shared agent memory for collaboration.",
        "parameters": {
            "type": "object",
            "properties": {
                "image_data": {
                    "type": "string",
                    "description": "Base64 encoded image data or file path"
                },
                "analysis_type": {
                    "type": "string",
                    "enum": ["ocr", "description", "object_detection", "full"],
                    "description": "Type of analysis to perform",
                    "default": "full"
                },
                "store_in_memory": {
                    "type": "boolean",
                    "description": "Store results in shared agent memory",
                    "default": True
                },
                "session_id": {
                    "type": "string",
                    "description": "Session identifier for memory storage"
                }
            },
            "required": ["image_data"]
        }
    }
}
