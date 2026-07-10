FROM python:3.11-slim

# Unbuffered stdout/stderr so container logs stream to Loki in real time
# instead of sitting in Python's block buffer until the process exits.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY feedback_server.py .
COPY index.html glossary.html battlecards.html ./
COPY fonts/ fonts/

EXPOSE 8080

CMD ["python3", "feedback_server.py", "8080"]
