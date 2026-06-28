"""ChronoSense Temporal RAG pipeline.

Retrieves clinically relevant Ayushman Bharat guideline chunks from ChromaDB
using a patient's 7-day drift trajectory as the query context, then feeds them
to a multi-agent LLM system (Groq) for an Indian-localized clinical assessment.
"""
