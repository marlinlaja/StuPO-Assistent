FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py config.py ./
COPY pipeline/ ./pipeline/
COPY services/ ./services/

CMD ["python", "main.py"]
