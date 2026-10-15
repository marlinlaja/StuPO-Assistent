FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
# Wenige malloc-Arenen, damit der Speicher nach Anfragen nicht fragmentiert
ENV MALLOC_ARENA_MAX=2

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Nur die Int8-ONNX-Gewichte und den Tokenizer beim Build laden, damit der Container ohne Internet startet
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('jinaai/jina-embeddings-v5-text-nano-retrieval', local_dir='/app/model', allow_patterns=['tokenizer.json', 'onnx/model_quantized.onnx', 'onnx/model_quantized.onnx_data'])"

COPY main.py ./

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
