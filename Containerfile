FROM python:3.11-slim

WORKDIR /app

COPY feedback_server.py .
COPY index.html glossary.html battlecards.html ./
COPY fonts/ fonts/

EXPOSE 8080

CMD ["python3", "feedback_server.py", "8080"]
