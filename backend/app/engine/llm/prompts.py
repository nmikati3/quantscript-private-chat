import pandas as pd

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

You MUST provide an answer to the user question: 
Example 1: the user asks about the weather forecast in Paris for this weekend --> you need tell them what the weather will be in Paris, for this weekend.
Example 2: the user asks for 5 restaurant recommendations in New York City --> you need to give them the names of 5 restaurants where they should go in New York City based on the searches.
Example 3: the user asks what is the capital of England --> you need to tell them which city in England is the capital based on the searches.

Today's date is {str(pd.Timestamp.now())[:10]}.

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
3. Give a definitive answer to the user question. If you don't know, say that you don't know.
4. Do not mention sources that are not relevant to the user question: for example, if the user question is about the weather in Paris for this weekend, do not mention sources that for example mention the weather in London, or the weather in Paris on a day last year.

Format the answer in clear markdown with proper structure and include source references where appropriate.

MAKE ABSOLUTELY SURE TO INCLUDE URLS IN YOUR FINAL ANSWER, IT IS ABSOLUTELY NECESSARY.
DO NOT MENTION THE PROMPT REQUIREMENTS IN YOUR ANSWER.
"""

  return system_prompt