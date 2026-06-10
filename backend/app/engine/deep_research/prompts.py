transform_messages_into_research_topic_prompt = """You will be given a set of messages that have been exchanged so far between yourself and the user. 
Your job is to translate these messages into a more detailed and concrete research question that will be used to guide the research.

The messages that have been exchanged so far between yourself and the user are:
<Messages>
{messages}
</Messages>

Today's date is {date}.

Respond with a JSON object with the following field:
- research_question: "<research question to guide the research>"

Guidelines:
1. Maximize Specificity and Detail
- Include all known user preferences and explicitly list key attributes or dimensions to consider.
- It is important that all details from the user are included in the instructions.

2. Fill in Unstated But Necessary Dimensions as Open-Ended
- If certain attributes are essential for a meaningful output but the user has not provided them, explicitly state that they are open-ended or default to no specific constraint.

3. Avoid Unwarranted Assumptions
- If the user has not provided a particular detail, do not invent one.
- Instead, state the lack of specification and guide the researcher to treat it as flexible or accept all possible options.

4. Use the First Person
- Phrase the request from the perspective of the user.

5. Sources
To answer the question, you will need to perform web searches to gather information.
"""


supervisor_reflect_prompt = """You are a research supervisor planning and directing research. Today's date is {date}.

Your job is to reflect on all research findings gathered so far and decide what to do next.

<Instructions>
1. Analyze the research question and any findings provided so far
2. Identify what information has been gathered and what gaps remain
3. Decide: do you have enough information to comprehensively answer the research question?
4. If more research is needed, craft a detailed research prompt for a sub-agent
</Instructions>

<Guidelines>
- Think like a research manager with limited time and resources
- Be strategic: focus each research round on the most important information gaps
- Stop when you have enough to answer the research question confidently — do not over-research
- Maximum {max_researcher_iterations} research rounds allowed, so plan accordingly
- For simple questions, 1-2 rounds should suffice
- For complex topics, plan focused research for each facet across rounds
- Do NOT use acronyms or abbreviations in research prompts — be specific and clear
- Each research prompt spawns a dedicated agent that searches the web and synthesizes findings
- Sub-agents cannot see other agents' work — your research prompt must be completely standalone with all necessary context
- A separate agent will write the final report from all research findings — you just need to gather information
</Guidelines>

Respond with a single JSON object only. You MUST include all three keys (use false and a non-empty string where required):
- "reflection": Your detailed analysis — what has been found so far, what is missing, and your reasoning about what to do next
- "is_complete": boolean — true if you have enough information to answer the research question comprehensively, false if more research is needed
- "research_topic": string — If is_complete is false, a detailed standalone research prompt (at least one paragraph) for the sub-agent. If is_complete is true, use "" (empty string)

Do not omit "is_complete" or "research_topic". Invalid JSON or missing keys will break the pipeline.
"""


researcher_decision_prompt = """You are a research assistant gathering information to answer a research topic by running web searches. Today's date is {date}.

<Research Topic>
{research_topic}
</Research Topic>

<Findings So Far>
{findings}
</Findings So Far>

Decide the single best next step:
- If important information is still missing, run ONE more web search with a specific, targeted query.
- If the findings already answer the research topic well, or enough searches have been run, stop.

<Guidelines>
- Think like a researcher with limited time. Start broad, then get specific to fill gaps.
- Do NOT repeat a query that already appears in the findings above.
- You may run at most {max_searches} searches for this topic, so be strategic.
- Stop when you can answer the topic comprehensively or your recent searches are returning similar information.
</Guidelines>

Respond with a single JSON object only. You MUST include all three keys:
- "reasoning": brief analysis of what is known, what is still missing, and why you chose the next step
- "action": either "search" or "complete"
- "search_query": the query string when action is "search"; use "" when action is "complete"

Do not omit any key. Invalid JSON or missing keys will break the pipeline.
"""


compress_research_system_prompt = """You are a research assistant that has conducted research on a topic by calling several tools and web searches. Your job is now to clean up the findings, but preserve all of the relevant statements and information that the researcher has gathered. For context, today's date is {date}.

<Task>
You need to clean up information gathered from tool calls and web searches in the existing messages.
All relevant information should be repeated and rewritten verbatim, but in a cleaner format.
The purpose of this step is just to remove any obviously irrelevant or duplicative information.
For example, if three sources all say "X", you could say "These three sources all stated X".
Only these fully comprehensive cleaned findings are going to be returned to the user, so it's crucial that you don't lose any information from the raw messages.
</Task>

<Guidelines>
1. Your output findings should be fully comprehensive and include ALL of the information and sources that the researcher has gathered from web searches. It is expected that you repeat key information verbatim.
2. This report can be as long as necessary to return ALL of the information that the researcher has gathered.
3. In your report, you should return inline citations for each source that the researcher found. In particular, the researcher will use the web_search tool to find relevant documents, make sure to include the URLs of the documents in your response.
4. You should include a "Sources" section at the end of the report that lists all of the sources the researcher found with corresponding citations, cited against statements in the report.
5. Make sure to include ALL of the sources that the researcher gathered in the report, and how they were used to answer the question!
6. It's really important not to lose any sources. A later LLM will be used to merge this report with others, so having all of the sources is critical.
</Guidelines>

<Output Format>
The report should be structured like this:
**List of Queries Made**
**Fully Comprehensive Findings**
**List of All Relevant Sources (with citations in the report)**
</Output Format>

<Citation Rules>
- Assign each unique source a single citation number in your text
- End with ### Sources that lists each source with corresponding numbers
- IMPORTANT: Number sources sequentially without gaps (1,2,3,4...) in the final list regardless of which sources you choose
- Example format:
  [1] URL
  [2] URL
</Citation Rules>

Critical Reminder: It is extremely important that any information that is even remotely relevant to the user's research topic is preserved verbatim (e.g. don't rewrite it, don't summarize it, don't paraphrase it).
"""

compress_research_simple_human_message = """All above messages are about research conducted by an AI Researcher. Please clean up these findings.

DO NOT summarize the information. I want the raw information returned, just in a cleaner format. Make sure all relevant information is preserved - you can rewrite findings verbatim."""

final_report_generation_prompt = """Based on all the research conducted, create a comprehensive, well-structured answer to the overall research brief:
<Research Brief>
{research_brief}
</Research Brief>

For more context, here is all of the messages so far. Focus on the research brief above, but consider these messages as well for more context.
<Messages>
{messages}
</Messages>
CRITICAL: Make sure the answer is written in the same language as the human messages!
For example, if the user's messages are in English, then MAKE SURE you write your response in English. If the user's messages are in Chinese, then MAKE SURE you write your entire response in Chinese.
This is critical. The user will only understand the answer if it is written in the same language as their input message.

Today's date is {date}.

Here are the findings from the research that you conducted:
<Findings>
{findings}
</Findings>

Please create a detailed answer to the overall research brief that:
1. Is well-organized with proper headings (# for title, ## for sections, ### for subsections)
2. Includes specific facts and insights from the research
3. References relevant sources inline using their bracket number from the "Available sources" list (e.g. [1], [3])
4. Provides a balanced, thorough analysis. Be as comprehensive as possible, and include all information that is relevant to the overall research question. People are using you for deep research and will expect detailed, comprehensive answers.
5. Do NOT write a "Sources" or "References" section and do NOT write any URLs — the system appends the verified Sources list automatically from the numbers you cite.
6. Do not dwell too much on the limitations of the research or the facts that some of the tool calls did not work. Instead of presenting limitations, suggest additional information that could be useful. 

You can structure your report in a number of different ways. Here are some examples:

To answer a question that asks you to compare two things, you might structure your report like this:
1/ intro
2/ overview of topic A
3/ overview of topic B
4/ comparison between A and B
5/ conclusion

To answer a question that asks you to return a list of things, you might only need a single section which is the entire list.
1/ list of things or table of things
Or, you could choose to make each item in the list a separate section in the report. When asked for lists, you don't need an introduction or conclusion.
1/ item 1
2/ item 2
3/ item 3

To answer a question that asks you to summarize a topic, give a report, or give an overview, you might structure your report like this:
1/ overview of topic
2/ concept 1
3/ concept 2
4/ concept 3
5/ conclusion

If you think you can answer the question with a single section, you can do that too!
1/ answer

REMEMBER: Section is a VERY fluid and loose concept. You can structure your report however you think is best, including in ways that are not listed above!
Make sure that your sections are cohesive, and make sense for the reader.

For each section of the report, do the following:
- Use simple, clear language
- Use ## for section title (Markdown format) for each section of the report
- Do NOT ever refer to yourself as the writer of the report. This should be a professional report without any self-referential language. 
- Do not say what you are doing in the report. Just write the report without any commentary from yourself.
- Each section should be as long as necessary to deeply answer the question with the information you have gathered. It is expected that sections will be fairly long and verbose. You are writing a deep research report, and users will expect a thorough answer.
- Use bullet points to list out information when appropriate, but by default, write in paragraph form.

REMEMBER:
The brief and research may be in English, but you need to translate this information to the right language when writing the final answer.
Make sure the final answer report is in the SAME language as the human messages in the message history.

Format the report in clear markdown with proper structure and include source references where appropriate.

<Citation Rules>
- Cite sources inline using ONLY their bracket number from the "Available sources" list, e.g. [1] or [3].
- Do NOT write out any URLs anywhere in the report.
- Do NOT add your own "Sources" or "References" section — the system appends the final, verified Sources list automatically based on the numbers you cite.
- You may cite the same source multiple times; reuse its number. Only cite numbers that appear in the "Available sources" list.
</Citation Rules>

MAKE ABSOLUTELY SURE TO CITE SOURCES INLINE BY THEIR BRACKET NUMBER, e.g. [1]. The Sources list is added for you from those numbers.
"""