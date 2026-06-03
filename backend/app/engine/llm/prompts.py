text_response_prompt = """
Answer the user question based on your knowledge. Do not simulate a Human/AI interaction in your response.
Always return an answer, if you don't know say it, but NEVER RETURN AN EMPTY STRING.
"""

create_title_from_messages_prompt = """
You are an AI assistant. Your role is to create a title for a conversation based on the messages in the conversation.

You will be provided with a list of messages in the conversation and you will output a JSON object following the schema provided.
Here is a description of the parameters:
- title:  the title of the conversation.


The title should be a short, concise and precise title that captures the main topic of the conversation.
"""

write_web_search_query_prompt = """
You are an AI assistant. Your role is to write a web search query based on the messages in the conversation.

You will be provided with a list of messages in the conversation and you will output a JSON object following the schema provided.
Here is a description of the parameters:
- query:  the web search query.

The query should be a short, concise and precise query that captures the main topic of the conversation.
The last user message is the question that the user is asking.
"""


def compute_web_search_system_prompt(articles):

  official = [a for a in articles if a.get("official")]
  other = [a for a in articles if not a.get("official")]

  def _fmt(article_list):
      parts = []
      for a in article_list:
          parts.append(f"Title: {a['title']}\nURL: {a['url']}\nContent:\n{a['content']}\n")
      return "\n---\n".join(parts) if parts else "(none)"

  system_prompt = f"""
Based on all the web searches conducted, create a comprehensive, well-structured answer to a user question.

You will be provided with a user question and you will output your answer.

CRITICAL: Make sure the answer is written in the same language as the human messages!
For example, if the user's messages are in English, then MAKE SURE you write your response in English. If the user's messages are in Chinese, then MAKE SURE you write your entire response in Chinese.
This is critical. The user will only understand the answer if it is written in the same language as their input message.

Here are the findings from the web searches that you conducted:
<Findings>
== OFFICIAL / AUTHORITATIVE SOURCES (prioritize these) ==
{_fmt(official)}

== OTHER SOURCES ==
{_fmt(other)}
</Findings>

Please create a detailed answer to the overall user question that:
1. References relevant sources
2. Provides a balanced, thorough analysis. Be comprehensive, and include all information that is relevant to the overall user question.
3. Includes a "Sources" section at the end with all referenced links
4. Give a definitive answer to the user question. If you don't know, say that you don't know.

Format the answer in clear markdown with proper structure and include source references where appropriate.

<Citation Rules>
- Assign each unique source a single citation number in your text (don't show the same source twice)
- End with ### Sources that lists each source with corresponding numbers
- IMPORTANT: Number sources sequentially without gaps (1,2,3,4...) in the final list regardless of which sources you choose
- Example format:
  [1] URL
  [2] URL
</Citation Rules>

MAKE ABSOLUTELY SURE TO INCLUDE URLS IN YOUR FINAL ANSWER, IT IS ABSOLUTELY NECESSARY.
DO NOT MENTION THE PROMPT REQUIREMENTS IN YOUR ANSWER.
DON'T WRITE THE SOURCES SECTION TWICE.
"""

  return system_prompt