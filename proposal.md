**Project Proposal: J.A.R.V.I.S.**

**Just-in-time Agent for Research Validation & Ideation Support**

**1\. Project Idea**

J.A.R.V.I.S. is a research ideation support system for researchers who are stuck and do not know what direction to try next. The system is not intended to write code, complete experiments, or give a final research answer. Its purpose is to study what the researcher has already done, compare that history with relevant research literature, and suggest a small set of possible next directions.

The main use case is simple: a researcher gives J.A.R.V.I.S. access to past papers, code, notes, experiment results, and other project records. The system builds a research history of what has already been tried and what happened. It then searches an offline collection of arXiv papers for related methods, limitations, future-work ideas, and approaches used by other researchers. Finally, it compares the outside literature with the user's own history and returns approximately five research directions, with an explanation and supporting papers for each suggestion.

The goal is to provide a backup source of research ideas when the researcher does not immediately know what to try next. It is not a replacement for an advisor. Instead, it can help the researcher prepare better ideas and questions before meeting with an advisor.

**2\. Why This Demonstrates Creativity**

The creative part of this project is the combination of research memory, literature search, and idea generation. Many existing tools can summarize a paper or answer a question about a document. J.A.R.V.I.S. is focused on a different problem: identifying what the researcher has not tried yet and suggesting reasonable directions based on evidence from the literature.

The system should be able to distinguish between an idea that is new to the user and an idea that the user has already tested. It should also avoid giving a random list of generic suggestions. Each proposed direction should be connected to something found in related work, such as a method other researchers used, a limitation they reported, an ablation result, or a future-work statement.

This creates a form of assisted research brainstorming. The creativity comes from finding useful connections between the user's research history and ideas spread across many papers, then presenting those connections as possible directions rather than as final answers.

**3\. Proposed Method**

The project will run the LLM and agent on the BYU Research Computing environment. Because compute nodes may not have internet access, the system will not depend on live web search during normal operation. Instead, we plan to prepare the literature collection ahead of time and make it available locally on RC.

The planned workflow is:

·       Collect the researcher's local project information, including papers, notes, code, experiment logs, results, and previous ideas.

·       Extract useful text and metadata and store it in a local research-memory database.

·       Download an arXiv corpus or a selected subset of arXiv papers before running on the compute node. Store paper text, abstracts, metadata, and embeddings locally.

·       Use an LLM with an agent layer, potentially Hermes or a similar agent framework, to decide what information it needs from the project history and literature database.

·       Retrieve papers and passages that are related to the current research problem.

·       Extract candidate directions from methods, limitations, related work, experiments, and future-work sections.

·       Compare each candidate direction with the user's project history and remove ideas that have already been tried or are obviously irrelevant.

·       Return approximately five suggestions. Each suggestion should include the idea, why it may be relevant, what evidence supports it, and which papers motivated it.

A simple ranking step can be used to order the suggestions. The ranking can consider relevance to the current problem, whether the user has already tried the idea, strength of support in the literature, feasibility, and how much new information the experiment could provide. The rank is only a way to organize the suggestions; the final decision remains with the researcher.

**4\. System Components**

·       Local LLM: runs on RC GPUs and performs reasoning, comparison, summarization, and idea generation.

·       Agent layer: decides when to search project history, search the literature database, compare results, and produce suggestions.

·       Research memory: stores the user's previous papers, code-related notes, experiment records, results, and other project history.

·       Offline arXiv database: contains downloaded papers or extracted text and metadata so the system can search literature without internet access.

·       Retriever / vector index: finds relevant project records and papers using semantic similarity and metadata filters.

·       Idea generator and filter: creates candidate directions, removes duplicates or already-tried ideas, and returns the strongest few suggestions.

**5\. Project Scope and Requirements**

For the class project, the first version will focus on generating research directions rather than building a complete autonomous scientist. The system should satisfy the following requirements:

·       Run locally on Research Computing hardware.

·       Work without internet access during the main LLM/agent run.

·       Use a pre-downloaded arXiv or scientific-paper database for literature retrieval.

·       Accept a researcher's previous work as context, including documents and experiment history.

·       Retrieve relevant papers and identify methods, limitations, and future-work ideas.

·       Compare literature-derived ideas with what the researcher has already tried.

·       Generate a short list of approximately five possible research directions.

·       Provide the supporting papers or passages behind each suggestion.

·       Focus on suggestions only. The system will not automatically write implementation code, run the proposed experiment, or claim that a suggested direction is the correct answer.

**6\. Approach to Evaluation**

We can evaluate the project by giving J.A.R.V.I.S. a research project up to a certain point in time and hiding the later work. We then ask it to suggest what to try next. The suggestions can be compared with directions the researcher actually explored later, and researchers can rate the output for relevance, novelty, feasibility, usefulness, and whether the idea had already been tried.

Another useful measure is the duplicate rate: how often the system recommends something already present in the project history. A lower duplicate rate would show that the research-memory component is working. We can also check whether every suggestion is traceable to real literature instead of being unsupported LLM generation.

**7\. Potentially Useful Resources**

The following resources may be useful for building the prototype:

·       arXiv Bulk Data Access / arXiv Dataset \- source for downloading papers and metadata for offline use. https\://info.arxiv.org/help/bulk\_data/index.html

·       arXiv API \- useful during dataset preparation for metadata and paper discovery when internet access is available. https\://info.arxiv.org/help/api/index.html

·       OpenAlex \- open scholarly metadata that can help with paper relationships, authors, topics, and citations. https\://openalex.org/

·       Semantic Scholar Open Research Corpus (S2ORC) \- large scientific-paper corpus that may be useful as an alternative or supplement to arXiv. https\://www\.semanticscholar.org/product/api\#S2ORC

·       GROBID \- tool for converting scientific PDFs into structured text and metadata. https\://github.com/kermitt2/grobid

·       FAISS \- local vector-similarity search for paper and project embeddings. https\://github.com/facebookresearch/faiss

·       Sentence Transformers \- models and tools for creating text embeddings for semantic retrieval. https\://www\.sbert.net/

·       Hugging Face Transformers \- framework for running local language models on RC. https\://huggingface.co/docs/transformers/

·       vLLM \- potential tool for efficient local GPU inference on RC. https\://docs.vllm.ai/

·       Hermes or another agent framework \- potential controller for coordinating retrieval, comparison, and suggestion generation.

**8\. Expected Result**

At the end of the project, a user should be able to give J.A.R.V.I.S. a research project and ask a question such as, “I am stuck. What are some directions I should investigate next?” J.A.R.V.I.S. should examine the project history and the offline literature collection, then return a small set of evidence-backed ideas. The output is intended to help the researcher think and decide what to investigate, not to replace the researcher or advisor.

