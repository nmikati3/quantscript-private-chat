"""Main implementation for the Deep Research agent adapted from LangChain open deep research implementation for less powerful models without LangChain dependencies.
Runs a lighter, more deterministic version of the Deep Research agent that is more suitable for less powerful models.
"""

import json
import os
import logging
from typing import Dict, List, Any
from pydantic import BaseModel, model_validator
from app.engine.llm.web_search import web_search_and_fetch_articles_async
from app.engine.llm.inference import get_structured_llm_response, get_llm_response_with_tools
from app.engine.deep_research.utils import (
    get_today_str,
    get_buffer_string,
    filter_messages,
    remove_up_to_last_ai_message,
    is_token_limit_exceeded,
    get_all_tools,
    think_tool as think_tool_function,
)
from app.engine.deep_research.prompts import (
    compress_research_simple_human_message,
    compress_research_system_prompt,
    final_report_generation_prompt,
    supervisor_reflect_prompt,
    research_system_prompt,
    transform_messages_into_research_topic_prompt,
)

logger = logging.getLogger(__name__)

MAX_TOKENS_COMPRESSION = int(os.environ.get("MAX_TOKENS_COMPRESSION", "8192"))
MAX_TOKENS_FINAL_REPORT = int(os.environ.get("MAX_TOKENS_FINAL_REPORT", "8192"))
MAX_CONCURRENT_RESEARCH_UNITS = int(os.environ.get("MAX_CONCURRENT_RESEARCH_UNITS", "5"))
MAX_RESEARCHER_ITERATIONS = int(os.environ.get("MAX_RESEARCHER_ITERATIONS", "5"))
N_CTX = int(os.environ.get("N_CTX", "32768"))


async def write_research_brief(
    messages: List[Dict[str, Any]]
) -> tuple:
    """Transform user messages into a structured research brief and initialize supervisor.
    
    Args:
        messages: List of message dicts
        
    Returns:
        tuple: (research_question, supervisor_system_prompt, "research_supervisor")
    """
    class TransformMessagesIntoResearchTopic(BaseModel):
        research_question: str

    system_prompt = transform_messages_into_research_topic_prompt.format(
        messages=get_buffer_string(messages),
        date=get_today_str(),
    )
    messages_with_system = messages[:-1] + [{"role": "system", "content": system_prompt}] + messages[-1:]

    response = get_structured_llm_response(TransformMessagesIntoResearchTopic, messages_with_system)
    
    return response.research_question


class SupervisorDecision(BaseModel):
    reflection: str
    is_complete: bool
    research_topic: str

    @model_validator(mode="before")
    @classmethod
    def coerce_missing_fields(cls, data: Any) -> Any:
        """Smaller models often return only ``reflection``; fill required keys so the workflow can continue."""
        if not isinstance(data, dict):
            return data
        if "reflection" not in data:
            raise ValueError("Missing required field: reflection")
        ref = str(data.get("reflection", "")).strip()
        if not ref:
            raise ValueError("reflection must be non-empty")
        out = dict(data)
        out["reflection"] = ref
        filled = False
        if "is_complete" not in out:
            out["is_complete"] = False
            filled = True
        ic = bool(out["is_complete"])
        if "research_topic" not in out:
            out["research_topic"] = (
                ""
                if ic
                else (
                    "Conduct web research to fill the gaps described in the reflection. "
                    "Use specific queries and prefer authoritative, up-to-date sources."
                )
            )
            filled = True
        if filled:
            logger.warning(
                "Supervisor JSON omitted is_complete and/or research_topic; using defaults. "
                "The model should return all three keys per the prompt."
            )
        return out


async def supervisor(supervisor_messages: List[Dict[str, Any]], research_brief: str) -> SupervisorDecision:
    """Lead research supervisor that reflects on findings and plans next research step.
    
    Deterministic flow: each call reflects on findings so far and either produces the
    next research topic or signals completion. No tool calling involved.
    
    Args:
        supervisor_messages: Conversation history (alternating assistant reflections
                            and user-role research findings)
        research_brief: The research question/brief
        
    Returns:
        SupervisorDecision with reflection, completion status, and next research topic
    """
    system_prompt = supervisor_reflect_prompt.format(
        date=get_today_str(),
        max_researcher_iterations=MAX_RESEARCHER_ITERATIONS,
    )
    messages =  supervisor_messages + [{"role": "system", "content": system_prompt}]
    messages.append({"role": "user", "content": f"Research question: {research_brief}"})

    logger.debug("Supervisor messages: %d items", len(messages))
    decision = get_structured_llm_response(SupervisorDecision, messages)
    logger.debug("Supervisor decision: is_complete=%s, reflection=%s...", decision.is_complete, decision.reflection[:100])

    return decision


async def researcher(researcher_messages: List[Dict[str, Any]],research_topic: str) -> Dict[str, Any]:
    """Individual researcher that conducts focused research on specific topics.
    
    Args:
        researcher_messages: List of message dicts for researcher conversation
        research_topic: The specific topic to research
        
    Returns:
        Dict with 'response' (message dict) and 'next_step' ('researcher_tools')
    """
    # Get available tools
    tools = get_all_tools()
    if len(tools) == 0:
        raise ValueError(
            "No tools found to conduct research."
        )
    
    # Prepare system prompt
    researcher_prompt = research_system_prompt.format(
        date=get_today_str(),
    )
    
    # Prepare messages
    messages = [{"role": "system", "content": researcher_prompt}] + researcher_messages
    
    # Get response with tools
    response = await get_llm_response_with_tools(
        messages=messages,
        tools=tools
    )
    
    return {
        "response": response,
        "next_step": "researcher_tools"
    }


async def execute_tool_safely(tool_name: str, args: Dict[str, Any]) -> str:
    """Safely execute a tool with error handling.
    
    Args:
        tool_name: Name of the tool to execute
        args: Arguments for the tool
        
    Returns:
        String result from tool execution
    """

    logger.info(f"Executing tool: {tool_name}")
    try:
        if tool_name == "think_tool":
            reflection = args.get("reflection", "")
            return think_tool_function(reflection)

        elif tool_name == "web_search":
            query = args.get("query", "")
            if not query:
                return "Error: web_search tool requires a 'query' parameter"
            
            articles = await web_search_and_fetch_articles_async(query)
            
            if len(articles) == 0:
                return "No relevant articles found for the given query."

            return str(articles)

        else:
            return f"Tool {tool_name} not yet implemented"
    except Exception as e:
        logger.error(f"Error executing tool {tool_name}: {str(e)}", exc_info=True)
        return f"Error executing tool {tool_name}: the operation failed."


async def researcher_tools(researcher_messages: List[Dict[str, Any]],tool_call_iterations: int, progress_callback=None) -> Dict[str, Any]:
    """Execute tools called by the researcher, including search tools and strategic thinking.
    
    Args:
        researcher_messages: List of message dicts including the latest assistant response
        tool_call_iterations: Current iteration count
        progress_callback: Optional callback for progress updates
        
    Returns:
        Dict with 'next_step' ('researcher', 'compress_research') and state updates
    """
    if not researcher_messages:
        return {"next_step": "compress_research", "researcher_messages": []}
    
    most_recent_message = researcher_messages[-1]
    
    # Check early exit conditions
    tool_calls = most_recent_message.get("tool_calls", [])
    has_tool_calls = bool(tool_calls)
    
    if not has_tool_calls:
        return {"next_step": "compress_research", "researcher_messages": []}
    
    # Execute all tool calls
    tool_outputs = []
    for tool_call in tool_calls:
        function_info = tool_call.get("function", {})
        tool_name = function_info.get("name", "")
        
        try:
            args = json.loads(function_info.get("arguments", "{}"))
        except json.JSONDecodeError:
            args = {}
        
        # Report tool usage
        if progress_callback:
            try:
                if tool_name == "web_search":
                    query = args.get("query", "")
                    progress_callback(f"🔍 Searching the web: {query[:150]}...")
                elif tool_name == "think_tool":
                    reflection = args.get("reflection", "")
                    progress_callback(f"💭 Researcher thinking: {reflection[:200]}...")
                else:
                    progress_callback(f"🔧 Using tool: {tool_name}")
            except Exception as e:
                logger.error(f"Error calling progress_callback researcher_tools: {e}")
                pass
        
        observation = await execute_tool_safely(tool_name, args)
        
        # Report tool results
        if progress_callback:
            try:
                if tool_name == "web_search":
                    if "articles" in observation:
                        progress_callback(f"✅ {observation.split(chr(10))[0]}")
            except Exception as e:
                logger.error(f"Error calling progress_callback researcher_tools: {e}")
                pass
        
        tool_outputs.append({
            "role": "tool",
            "content": observation,
            "tool_call_id": tool_call["id"]
        })
    
    # Check late exit conditions
    exceeded_iterations = tool_call_iterations >= 3
    research_complete_called = any(
        tool_call.get("function", {}).get("name") == "ResearchComplete"
        for tool_call in tool_calls
    )
    
    if exceeded_iterations or research_complete_called:
        return {
            "next_step": "compress_research",
            "researcher_messages": tool_outputs
        }
    
    return {
        "next_step": "researcher",
        "researcher_messages": tool_outputs
    }


async def compress_research(
    researcher_messages: List[Dict[str, Any]],
    progress_callback=None,
) -> Dict[str, Any]:
    """Compress and synthesize research findings into a concise, structured summary.
    
    Args:
        researcher_messages: List of message dicts from researcher
        progress_callback: Optional callback for progress updates
        
    Returns:
        Dict with 'compressed_research' and 'raw_notes'
    """
    # Prepare messages for compression
    messages = researcher_messages.copy()
    messages.append({"role": "user", "content": compress_research_simple_human_message})

    # Attempt compression with retry logic
    synthesis_attempts = 0
    max_attempts = 3
    
    while synthesis_attempts < max_attempts:
        try:
            compression_prompt = compress_research_system_prompt.format(date=get_today_str())
            messages_with_system = [{"role": "system", "content": compression_prompt}] + messages
            
            response = await get_llm_response_with_tools(
                messages=messages_with_system,
                max_tokens=MAX_TOKENS_COMPRESSION
            )
            
            # Extract raw notes
            raw_notes_content = "\n".join([
                str(msg.get("content", ""))
                for msg in filter_messages(researcher_messages, include_types=["tool", "assistant"])
            ])
            
            compressed = response.get("content", "")
            if progress_callback:
                try:
                    progress_callback(f"✅ Research compressed: {len(compressed)} characters")
                except Exception as e:
                    logger.error(f"Error calling progress_callback compress_research: {e}")
                    pass
            
            return {
                "compressed_research": compressed,
                "raw_notes": [raw_notes_content] if raw_notes_content else []
            }
            
        except Exception as e:
            logger.error(f"Error in compress_research: {str(e)}")
            synthesis_attempts += 1
            
            if is_token_limit_exceeded(e):
                # Convert to list of dicts for remove_up_to_last_ai_message
                messages = remove_up_to_last_ai_message(messages)
                continue
            
            if synthesis_attempts >= max_attempts:
                break
    
    # Return error result
    raw_notes_content = "\n".join([
        str(msg.get("content", ""))
        for msg in filter_messages(researcher_messages, include_types=["tool", "assistant"])
    ])
    
    return {
        "compressed_research": "Error synthesizing research report: Maximum retries exceeded",
        "raw_notes": [raw_notes_content] if raw_notes_content else []
    }


async def researcher_workflow(research_topic: str, progress_callback=None) -> Dict[str, Any]:
    """Complete workflow for a single researcher.
    
    Args:
        research_topic: The topic to research
        progress_callback: Optional callback for progress updates
        
    Returns:
        Dict with 'compressed_research' and 'raw_notes'
    """
    researcher_messages = [{"role": "user", "content": research_topic}]
    tool_call_iterations = 0
    
    # Research loop
    while tool_call_iterations < MAX_RESEARCHER_ITERATIONS:
        # Get researcher response
        researcher_result = await researcher(researcher_messages, research_topic)
        researcher_messages.append(researcher_result["response"])
        tool_call_iterations += 1
        
        # Execute tools
        if researcher_result["next_step"] == "researcher_tools":
            tools_result = await researcher_tools(
                researcher_messages,
                tool_call_iterations,
                progress_callback,
            )
            researcher_messages.extend(tools_result.get("researcher_messages", []))
            
            if tools_result["next_step"] == "compress_research":
                if progress_callback:
                    try:
                        progress_callback("📝 Compressing research findings...")
                    except Exception as e:
                        logger.error(f"Error calling progress_callback researcher_workflow: {e}")
                        pass
                break
        
        if tool_call_iterations >= MAX_RESEARCHER_ITERATIONS:
            break
    
    # Compress research
    compression_result = await compress_research(researcher_messages, progress_callback)
    return compression_result


async def final_report_generation(
    notes: List[str],
    research_brief: str,
    messages: List[Dict[str, Any]],
    progress_callback=None,
) -> Dict[str, Any]:
    """Generate the final comprehensive research report with retry logic for token limits.
    
    Args:
        notes: List of research notes/findings
        research_brief: The original research brief
        messages: Original user messages
        progress_callback: Optional callback for progress updates
        
    Returns:
        Dict with 'final_report' and 'messages'
    """
    findings = "\n".join(notes)
    
    # Attempt report generation with token limit retry logic
    max_retries = 3
    current_retry = 0
    findings_token_limit = None
    
    while current_retry <= max_retries:
        try:
            final_report_prompt = final_report_generation_prompt.format(
                research_brief=research_brief,
                messages=get_buffer_string(messages),
                findings=findings,
                date=get_today_str(),
            )
            
            if progress_callback:
                try:
                    progress_callback("✍️ Writing final report...")
                except Exception as e:
                    logger.error(f"Error calling progress_callback final_report_generation: {e}")
                    pass
            
            response = await get_llm_response_with_tools(
                messages=[{"role": "user", "content": final_report_prompt}],
                max_tokens=MAX_TOKENS_FINAL_REPORT
            )
            
            final_report = response.get("content", "")
            if progress_callback:
                try:
                    progress_callback(f"📝 Report written: {len(final_report)} characters")
                except Exception as e:
                    logger.error(f"Error calling progress_callback final_report_generation: {e}")
                    pass
            
            return {
                "final_report": final_report,
                "messages": [response]
            }
            
        except Exception as e:
            logger.error(f"Error generating final report: {e}")
            if is_token_limit_exceeded(e):
                current_retry += 1
                
                if current_retry == 1:
                    model_token_limit = 8192
                    if not model_token_limit:
                        return {
                            "final_report": "Error generating final report: Token limit exceeded and the model's maximum context length could not be determined.",
                            "messages": [{"role": "assistant", "content": "Report generation failed due to token limits"}]
                        }
                    findings_token_limit = model_token_limit * 4
                else:
                    findings_token_limit = int(findings_token_limit * 0.9)
                
                findings = findings[:findings_token_limit]
                continue
            else:
                return {
                    "final_report": "Error generating final report. Please try again.",
                    "messages": [{"role": "assistant", "content": "Report generation failed due to an error"}]
                }
    
    return {
        "final_report": "Error generating final report: Maximum retries exceeded",
        "messages": [{"role": "assistant", "content": "Report generation failed after maximum retries"}]
    }


async def deep_research_workflow(
    messages: List[Dict[str, Any]],
    progress_callback=None,
) -> Dict[str, Any]:
    """Main deep research workflow from user input to final report.
    
    Args:
        messages: List of user message dicts    
        progress_callback: Optional callback function to report progress updates.
                          Should accept a string message as argument.
        
    Returns:
        Dict with 'final_report' and other results
    """
    
    # Step 1: Write research brief
    research_question = await write_research_brief(messages)
    logger.debug("Research question: %s", research_question)
    
    if progress_callback:
        try:
            progress_callback(f"📋 Research Question: {research_question}")
        except Exception as e:
            logger.error(f"Error calling progress_callback deep_research_workflow: {e}")
            pass
    
    # Step 2: Supervisor loop — deterministic think → research alternation
    supervisor_messages = []
    research_iterations = 0
    all_notes = []

    while research_iterations < MAX_RESEARCHER_ITERATIONS:
        logger.info(f"Research iteration {research_iterations + 1}, supervisor context length: {len(supervisor_messages)}")

        # Think phase: supervisor reflects on findings and decides next action
        decision = await supervisor(supervisor_messages, research_question)

        if progress_callback:
            try:
                progress_callback(f"💭 Supervisor Reflection: {decision.reflection}")
            except Exception as e:
                logger.error(f"Error calling progress_callback deep_research_workflow: {e}")

        if decision.is_complete:
            logger.info("Supervisor decided research is complete")
            if progress_callback:
                try:
                    progress_callback("✅ Research phase complete")
                except Exception as e:
                    logger.error(f"Error calling progress_callback deep_research_workflow: {e}")
            break

        supervisor_messages.append({
            "role": "assistant",
            "content": json.dumps({
                "reflection": decision.reflection,
                "is_complete": False,
                "research_topic": decision.research_topic,
            })
        })

        # Research phase: deterministically execute the planned research
        if progress_callback:
            try:
                progress_callback(f"🔬 Starting research on: {decision.research_topic[:200]}...")
            except Exception as e:
                logger.error(f"Error calling progress_callback deep_research_workflow: {e}")

        try:
            research_result = await researcher_workflow(
                research_topic=decision.research_topic,
                progress_callback=progress_callback,
            )

            compressed = research_result.get("compressed_research", "")
            raw_notes = research_result.get("raw_notes", [])
            raw_notes_text = "\n".join(raw_notes)

            # Use raw tool outputs for supervisor context — the compress_research
            # LLM step often fails with weaker models, producing only query metadata
            # instead of actual findings. Raw notes contain the real web search results.
            supervisor_findings = raw_notes_text if raw_notes_text else compressed
            # Keep within a reasonable size for the supervisor's context window
            max_findings_chars = N_CTX * 3
            if len(supervisor_findings) > max_findings_chars:
                supervisor_findings = supervisor_findings[:max_findings_chars] + "\n\n[...truncated for length]"

            all_notes.append(supervisor_findings)

            if progress_callback:
                try:
                    progress_callback(f"✅ Completed research round {research_iterations + 1}")
                except Exception as e:
                    logger.error(f"Error calling progress_callback deep_research_workflow: {e}")

            supervisor_messages.append({
                "role": "user",
                "content": f"Research findings:\n{supervisor_findings}"
            })

        except Exception as e:
            logger.error(f"Error in research workflow: {e}", exc_info=True)
            if is_token_limit_exceeded(e):
                break
            supervisor_messages.append({
                "role": "user",
                "content": "Research encountered an error and could not complete this round."
            })

        research_iterations += 1
    
    # Step 3: Generate final report
    final_notes = all_notes if all_notes else [
        msg["content"] for msg in supervisor_messages
        if msg.get("role") == "user" and msg.get("content", "").startswith("Research findings:")
    ]
    
    if progress_callback:
        try:
            progress_callback(f"📄 Generating final report from {len(final_notes)} research note(s)...")
        except Exception as e:
            logger.error(f"Error calling progress_callback deep_research_workflow: {e}")
            pass
    
    report_result = await final_report_generation(
        final_notes,
        research_question,
        messages,
        progress_callback,
    )
    
    if progress_callback:
        try:
            if report_result.get("final_report"):
                progress_callback("✅ Final report generated successfully!")
        except Exception as e:
            logger.error(f"Error calling progress_callback deep_research_workflow: {e}")
            pass
    
    return report_result
