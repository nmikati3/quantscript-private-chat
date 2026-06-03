"""BM25 keyword search for tabular data."""

import os
from rank_bm25 import BM25Okapi
import logging

logger = logging.getLogger(__name__)


K_KEYWORD_SEARCH = int(os.environ.get("K_KEYWORD_SEARCH", "200"))


def keyword_search(data,user_prompt,n=K_KEYWORD_SEARCH):

  corpus = data.to_dict(orient='records')

  tokenized_corpus = [(str(doc)).split(" ") for doc in corpus]

  bm25 = BM25Okapi(tokenized_corpus)

  tokenized_query = user_prompt.split(" ")

  relevant_documents = bm25.get_top_n(tokenized_query, corpus, n=n)

  return relevant_documents
