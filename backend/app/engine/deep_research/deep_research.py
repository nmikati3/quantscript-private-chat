"""Main implementation for the Deep Research agent adapted from LangChain open deep research implementation for less powerful models without LangChain dependencies.
Runs a lighter, more deterministic version of the Deep Research agent that is more suitable for less powerful models.
"""

import json
import os
import logging
from typing import Dict, List, Any
from pydantic import BaseModel, model_validator
from app.engine.llm.web_search import web_search_and_fetch_articles_async
from app.engine.llm.inference import (
    get_structured_llm_response,
    get_llm_response_with_tools,
    N_CTX,
    MODEL_TIER,
)
from app.engine.deep_research.utils import (
    get_today_str,
    get_buffer_string,
    is_token_limit_exceeded,
    truncate_preserving_sources,
    build_source_catalog,
    finalize_report_sources,
)
from app.engine.deep_research.prompts import (
    compress_research_simple_human_message,
    compress_research_system_prompt,
    final_report_generation_prompt,
    supervisor_reflect_prompt,
    researcher_decision_prompt,
    transform_messages_into_research_topic_prompt,
)

logger = logging.getLogger(__name__)

# Deep research fires ~25+ model inferences for a single run on the full
# profile. On a memory-constrained tier (8 GB Macs) that volume of work plus the
# large per-call contexts pushes the machine into swap and a decode eventually
# crashes mid-run. So on the low-memory tier we run a lighter profile: fewer
# planning rounds, fewer searches, fewer articles and smaller token budgets.
#
# Precedence: an explicit environment variable always wins; otherwise we pick
# the lite default on a low-memory machine and the full default elsewhere.
_LITE = bool(getattr(MODEL_TIER, "low_memory", False))


def _tiered_limit(env_var: str, full: int, lite: int) -> int:
    raw = os.environ.get(env_var, "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            logger.warning("Ignoring invalid %s=%r", env_var, raw)
    return lite if _LITE else full


MAX_TOKENS_COMPRESSION = _tiered_limit("MAX_TOKENS_COMPRESSION", 8192, 2048)
MAX_TOKENS_FINAL_REPORT = _tiered_limit("MAX_TOKENS_FINAL_REPORT", 8192, 4096)
# How many supervisor planning rounds (topics) the workflow runs.
MAX_RESEARCHER_ITERATIONS = _tiered_limit("MAX_RESEARCHER_ITERATIONS", 5, 2)
# How many web searches a single researcher may run for one topic.
MAX_RESEARCHER_SEARCHES = _tiered_limit("MAX_RESEARCHER_SEARCHES", 3, 2)
# How many articles each web search fetches into the model's context.
RESEARCH_ARTICLES_PER_SEARCH = _tiered_limit("RESEARCH_ARTICLES_PER_SEARCH", 3, 2)
# N_CTX is imported from inference so deep research uses the same memory-tiered
# context window (env var N_CTX still overrides it there).
# How many times to re-sample a structured decision when its JSON can't be parsed/validated.
MAX_SUPERVISOR_PARSE_RETRIES = int(os.environ.get("MAX_SUPERVISOR_PARSE_RETRIES", "2"))
# Low sampling temperature for every deep-research model call. Lower precision
# (4-bit QAT) models follow the prompt's citation/language rules far more
# reliably when sampling is near-greedy, which cuts hallucinated URLs and
# wrong-language drift.
DEEP_RESEARCH_TEMPERATURE = float(os.environ.get("DEEP_RESEARCH_TEMPERATURE", "0.1"))
# Maximum number of sources offered to (and citable by) the final report. Bounds
# the catalog the model picks from and the rendered Sources list, so a run with
# many results stays readable and easy for a small model to cite correctly.
MAX_REPORT_SOURCES = int(os.environ.get("MAX_REPORT_SOURCES", "30"))

logger.info(
    "Deep research profile: %s (iterations=%d, searches=%d, articles/search=%d, "
    "compression_tokens=%d, report_tokens=%d)",
    "lite (low-memory tier)" if _LITE else "full",
    MAX_RESEARCHER_ITERATIONS,
    MAX_RESEARCHER_SEARCHES,
    RESEARCH_ARTICLES_PER_SEARCH,
    MAX_TOKENS_COMPRESSION,
    MAX_TOKENS_FINAL_REPORT,
)

# A healthy compression preserves the gathered findings and their sources. Weaker
# models sometimes return only a few words of query metadata or the error string
# below instead of real synthesis, in which case the raw notes are the better
# input for the final report.
_MIN_USABLE_COMPRESSION_CHARS = 200
_COMPRESSION_ERROR_PREFIX = "Error synthesizing research report"


def _compression_is_usable(compressed: str) -> bool:
    """Return True when ``compress_research`` produced a real synthesis.

    Used to decide whether the final report should consume the researcher's
    compressed findings (preferred) or fall back to the raw web search output.
    """
    if not compressed:
        return False
    if compressed.startswith(_COMPRESSION_ERROR_PREFIX):
        return False
    return len(compressed.strip()) >= _MIN_USABLE_COMPRESSION_CHARS


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

    # The prompt already embeds the full conversation, so a single user turn is
    # enough (and Gemma's template would drop a system-role message anyway).
    prompt = transform_messages_into_research_topic_prompt.format(
        messages=get_buffer_string(messages),
        date=get_today_str(),
    )

    response = get_structured_llm_response(
        TransformMessagesIntoResearchTopic,
        [{"role": "user", "content": prompt}],
        temperature=DEEP_RESEARCH_TEMPERATURE,
    )

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
    # Gemma's template ignores system-role messages, so fold the instructions
    # into the user turn that also carries the research question.
    research_message = {
        "role": "user",
        "content": f"{system_prompt}\n\nResearch question: {research_brief}",
    }

    # The supervisor keeps every past reflection and the findings from each round
    # in its context, so the prompt grows with the conversation and can exceed the
    # model's context window after a few iterations. Drop the oldest history
    # entries and retry on a token-limit error so a long run degrades gracefully
    # instead of crashing the whole workflow.
    history = list(supervisor_messages)
    parse_retries = 0
    while True:
        messages = history + [research_message]
        logger.debug("Supervisor messages: %d items", len(messages))
        try:
            decision = get_structured_llm_response(SupervisorDecision, messages, temperature=DEEP_RESEARCH_TEMPERATURE)
            logger.debug("Supervisor decision: is_complete=%s, reflection=%s...", decision.is_complete, decision.reflection[:100])
            return decision
        except Exception as e:
            if is_token_limit_exceeded(e) and history:
                drop = max(1, len(history) // 4)
                logger.warning(
                    "Supervisor context exceeded the window; dropping %d oldest message(s) and retrying",
                    drop,
                )
                history = history[drop:]
                continue
            # Weaker models occasionally emit JSON that fails to parse or validate
            # (often a reflection long enough to be truncated at max_tokens).
            # Re-sample a few times — a fresh, shorter sample usually fits the
            # schema — before letting the error propagate.
            if not is_token_limit_exceeded(e) and parse_retries < MAX_SUPERVISOR_PARSE_RETRIES:
                parse_retries += 1
                logger.warning(
                    "Supervisor response could not be parsed (%s); re-sampling (%d/%d)",
                    e,
                    parse_retries,
                    MAX_SUPERVISOR_PARSE_RETRIES,
                )
                continue
            raise


class ResearcherDecision(BaseModel):
    reasoning: str
    action: str
    search_query: str = ""

    @model_validator(mode="before")
    @classmethod
    def coerce_fields(cls, data: Any) -> Any:
        """Tolerate the loose JSON weaker models emit: fill action/query sensibly."""
        if not isinstance(data, dict):
            return data
        out = dict(data)
        reasoning = str(out.get("reasoning") or out.get("reflection") or "").strip()
        if not reasoning:
            raise ValueError("reasoning must be non-empty")
        out["reasoning"] = reasoning
        query = str(out.get("search_query") or out.get("query") or "").strip()
        out["search_query"] = query
        action = str(out.get("action") or "").strip().lower()
        if action not in ("search", "complete"):
            # Infer from whether a query was supplied so the loop still progresses.
            action = "search" if query else "complete"
        out["action"] = action
        return out


def _format_articles(articles: List[Dict[str, Any]]) -> str:
    """Render structured search results into readable text for the model."""
    blocks = []
    for a in articles:
        title = (a.get("title") or "").strip()
        url = (a.get("url") or "").strip()
        content = (a.get("content") or "").strip()
        header = " — ".join(p for p in (title, url) if p)
        blocks.append(f"{header}\n{content}".strip())
    return "\n\n".join(blocks)


def researcher_decide(research_topic: str, findings_so_far: str) -> ResearcherDecision:
    """Decide the researcher's next step via structured JSON (no tool calling).

    Mirrors the deterministic supervisor: the model reflects on findings gathered
    so far and either requests one more web search or signals it has enough. Runs
    on the model's native template; re-samples a few times on unparseable JSON.
    """
    prompt = researcher_decision_prompt.format(
        date=get_today_str(),
        research_topic=research_topic,
        findings=findings_so_far or "(no searches run yet)",
        max_searches=MAX_RESEARCHER_SEARCHES,
    )
    messages = [{"role": "user", "content": prompt}]
    parse_retries = 0
    while True:
        try:
            return get_structured_llm_response(ResearcherDecision, messages, temperature=DEEP_RESEARCH_TEMPERATURE)
        except Exception as e:
            if not is_token_limit_exceeded(e) and parse_retries < MAX_SUPERVISOR_PARSE_RETRIES:
                parse_retries += 1
                logger.warning(
                    "Researcher decision could not be parsed (%s); re-sampling (%d/%d)",
                    e, parse_retries, MAX_SUPERVISOR_PARSE_RETRIES,
                )
                continue
            raise


async def compress_research(
    transcript: str,
    sources: List[Dict[str, str]],
    progress_callback=None,
) -> Dict[str, Any]:
    """Synthesize the gathered findings into a clean, citation-preserving summary.

    Args:
        transcript: Plain-text record of the searches run and their results.
        sources: Structured ``{"title", "url"}`` records for authoritative citations.
        progress_callback: Optional callback for progress updates

    Returns:
        Dict with 'compressed_research' and 'raw_notes'
    """
    if not transcript.strip():
        return {"compressed_research": "", "raw_notes": []}

    # Gemma ignores system-role messages, so fold the compression instructions
    # and the findings into a single user turn.
    if _LITE:
        findings = truncate_preserving_sources(transcript, 2000, sources=sources)
    else:
        findings = transcript

    synthesis_attempts = 0
    max_attempts = 3

    while synthesis_attempts < max_attempts:
        try:
            prompt = (
                f"{compress_research_system_prompt.format(date=get_today_str())}\n\n"
                f"<RawFindings>\n{findings}\n</RawFindings>\n\n"
                f"{compress_research_simple_human_message}"
            )
            response = await get_llm_response_with_tools(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=MAX_TOKENS_COMPRESSION,
                temperature=DEEP_RESEARCH_TEMPERATURE,
            )

            compressed = response.get("content", "")
            if progress_callback:
                try:
                    progress_callback(f"✅ Research compressed: {len(compressed)} characters")
                except Exception as e:
                    logger.error(f"Error calling progress_callback compress_research: {e}")

            return {
                "compressed_research": compressed,
                "raw_notes": [transcript],
            }

        except Exception as e:
            logger.error(f"Error in compress_research: {str(e)}")
            synthesis_attempts += 1

            if is_token_limit_exceeded(e):
                # Shrink the findings (preserving sources) and retry.
                findings = truncate_preserving_sources(
                    findings, max(2000, len(findings) // 2), sources=sources
                )
                continue

            if synthesis_attempts >= max_attempts:
                break

    return {
        "compressed_research": "Error synthesizing research report: Maximum retries exceeded",
        "raw_notes": [transcript],
    }


async def researcher_workflow(research_topic: str, progress_callback=None) -> Dict[str, Any]:
    """Conduct deterministic, structured research on a single topic.

    Drives a search loop from orchestration code: the model decides (via JSON)
    whether to run another web search or stop, and this function executes the
    searches directly. No function calling involved.

    Args:
        research_topic: The topic to research
        progress_callback: Optional callback for progress updates

    Returns:
        Dict with 'compressed_research', 'raw_notes', and 'sources'
        (structured ``{"title", "url"}`` records from the web searches)
    """
    sources: List[Dict[str, str]] = []
    transcript_parts: List[str] = []
    seen_queries = set()
    # Budget the findings we feed back into the decision prompt so a long topic
    # does not blow the context window.
    decision_context_chars = max(2000, (N_CTX * 2) // MAX_RESEARCHER_SEARCHES)

    for _ in range(MAX_RESEARCHER_SEARCHES):
        findings_so_far = truncate_preserving_sources(
            "\n\n".join(transcript_parts), decision_context_chars, sources=sources
        )
        try:
            decision = researcher_decide(research_topic, findings_so_far)
        except Exception as e:
            logger.warning("Researcher decision failed; ending search loop: %s", e)
            break

        if progress_callback:
            try:
                progress_callback(f"💭 Researcher thinking: {decision.reasoning[:200]}...")
            except Exception as e:
                logger.error(f"Error calling progress_callback researcher_workflow: {e}")

        query = decision.search_query.strip()
        if decision.action == "complete" or not query or query in seen_queries:
            break
        seen_queries.add(query)

        if progress_callback:
            try:
                progress_callback(f"🔍 Searching the web: {query[:150]}...")
            except Exception as e:
                logger.error(f"Error calling progress_callback researcher_workflow: {e}")

        try:
            articles = await web_search_and_fetch_articles_async(
                query, n=RESEARCH_ARTICLES_PER_SEARCH
            )
        except Exception as e:
            logger.error(f"web_search failed for query '{query}': {e}", exc_info=True)
            transcript_parts.append(f"## Search: {query}\n(search failed)")
            continue

        if not articles:
            transcript_parts.append(f"## Search: {query}\nNo relevant articles found.")
            continue

        sources.extend(
            {"title": a.get("title", ""), "url": a.get("url", "")}
            for a in articles
            if a.get("url")
        )
        if progress_callback:
            try:
                progress_callback(f"✅ Found {len(articles)} source(s)")
            except Exception as e:
                logger.error(f"Error calling progress_callback researcher_workflow: {e}")

        transcript_parts.append(f"## Search: {query}\n{_format_articles(articles)}")

    if progress_callback:
        try:
            progress_callback("📝 Compressing research findings...")
        except Exception as e:
            logger.error(f"Error calling progress_callback researcher_workflow: {e}")

    transcript = "\n\n".join(transcript_parts)
    compression_result = await compress_research(transcript, sources, progress_callback)
    compression_result["sources"] = sources
    return compression_result


async def final_report_generation(
    notes: List[str],
    research_brief: str,
    messages: List[Dict[str, Any]],
    progress_callback=None,
    sources: List[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Generate the final comprehensive research report with retry logic for token limits.
    
    Args:
        notes: List of research notes/findings
        research_brief: The original research brief
        messages: Original user messages
        progress_callback: Optional callback for progress updates
        sources: Structured ``{"title", "url"}`` records captured from the web
                 searches. Used to append an authoritative, de-duplicated Sources
                 list to the findings and to preserve URLs on token-limit trims.
        
    Returns:
        Dict with 'final_report' and 'messages'
    """
    notes_text = "\n".join(notes)

    # The model cites sources by number from this catalog and is told not to
    # write URLs; finalize_report_sources() then rebuilds an authoritative,
    # renumbered Sources list from the real fetched records. Cap the catalog so a
    # run with many results stays readable and easy for a small model to cite.
    candidates = (sources or [])[:MAX_REPORT_SOURCES]
    catalog = build_source_catalog(candidates)

    # Attempt report generation with token limit retry logic
    max_retries = 3
    current_retry = 0
    notes_token_limit = None

    while current_retry <= max_retries:
        try:
            findings = f"{notes_text}\n\n{catalog}" if catalog else notes_text
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
                max_tokens=MAX_TOKENS_FINAL_REPORT,
                temperature=DEEP_RESEARCH_TEMPERATURE,
            )

            # Replace the model's citations (often mangled on low-bit models) and
            # any self-written Sources section with an authoritative, renumbered
            # list built from the real fetched URLs.
            final_report = finalize_report_sources(response.get("content", ""), candidates)
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
                    notes_token_limit = 8192 * 4
                else:
                    notes_token_limit = int(notes_token_limit * 0.9)

                # Shrink only the notes; the (small) source catalog is preserved
                # whole so the cited numbers still resolve. No source footer is
                # appended here — the catalog already carries the citable sources.
                notes_text = truncate_preserving_sources(notes_text, notes_token_limit)
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
    # Authoritative source records (deduped by URL), captured structurally from
    # each round's web searches rather than parsed back out of text.
    all_sources: List[Dict[str, str]] = []
    seen_source_urls = set()

    while research_iterations < MAX_RESEARCHER_ITERATIONS:
        logger.info(f"Research iteration {research_iterations + 1}, supervisor context length: {len(supervisor_messages)}")

        # Think phase: supervisor reflects on findings and decides next action
        try:
            decision = await supervisor(supervisor_messages, research_question)
        except Exception as e:
            logger.error(f"Supervisor step failed: {e}", exc_info=True)
            if all_notes:
                # A single failed planning step (e.g. unparseable/truncated JSON
                # from a weak model, or a context-limit error) must not abort the
                # whole run. Stop the loop and write the report from the findings
                # gathered so far.
                if progress_callback:
                    try:
                        progress_callback("⚠️ Planner step failed — finalizing the report with findings so far")
                    except Exception:
                        pass
                break
            # Nothing has been gathered yet; surface the error to the caller.
            raise

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
            round_sources = research_result.get("sources", [])

            # Accumulate this round's structured sources, de-duplicating by URL.
            for src in round_sources:
                url = (src or {}).get("url")
                if url and url not in seen_source_urls:
                    seen_source_urls.add(url)
                    all_sources.append(src)

            # The final report should consume the researcher's synthesized
            # findings, not raw search dumps. Fall back to raw notes only when
            # compression failed (weaker models sometimes emit only query
            # metadata or an error instead of real synthesis).
            if _compression_is_usable(compressed):
                report_findings = compressed
            else:
                logger.warning(
                    "compress_research output unusable for round %d; "
                    "falling back to raw notes for the final report",
                    research_iterations + 1,
                )
                report_findings = raw_notes_text if raw_notes_text else compressed

            # Keep the full synthesis for the final report writer.
            all_notes.append(report_findings)

            # The supervisor keeps the findings from every round in its context,
            # so feed it only a bounded slice of the window (~3 chars/token)
            # instead of letting one round fill it. Pass this round's structured
            # sources so the preserved citation footer is authoritative rather
            # than regex-derived. Accumulated rounds then stay within the context
            # window; the supervisor() retry is the backstop.
            max_findings_chars = max(2000, (N_CTX * 2) // MAX_RESEARCHER_ITERATIONS)
            supervisor_findings = truncate_preserving_sources(
                report_findings, max_findings_chars, sources=round_sources
            )

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
        sources=all_sources,
    )
    
    if progress_callback:
        try:
            if report_result.get("final_report"):
                progress_callback("✅ Final report generated successfully!")
        except Exception as e:
            logger.error(f"Error calling progress_callback deep_research_workflow: {e}")
            pass
    
    return report_result
