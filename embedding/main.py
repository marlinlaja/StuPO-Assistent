import hmac
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import numpy as np
import onnxruntime
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from tokenizers import Tokenizer



# --- Konstanten ---

API_KEY = os.environ.get("EMBEDDING_API_KEY")
if not API_KEY:
    sys.exit("EMBEDDING_API_KEY fehlt (Key, den Backend und Processing mitschicken)")

# Lizenz des Modells: CC BY-NC 4.0, kommerzielle Nutzung nur nach Absprache mit Jina AI
MODEL_NAME = "jinaai/jina-embeddings-v5-text-nano"
MODEL_DIR = Path(__file__).resolve().parent / "model"
PAD_TOKEN = "<|end_of_text|>"

MAX_TOKENS = 512
MAX_TEXTS = 256
# Wenige Texte pro Durchlauf halten den Speicherbedarf klein
MICRO_BATCH_SIZE = 8
DEFAULT_DIMENSION = 768
MAX_DIMENSION = 768
PROMPTS = {"query": "Query: ", "document": "Document: "}

# Immer nur eine Anfrage gleichzeitig rechnen, sonst addiert sich der Speicher
ENCODE_LOCK = threading.Lock()
MODEL: dict = {}



# --- Datenmodell ---

class EmbeddingRequest(BaseModel):
    input: str | list[str]
    input_type: Literal["query", "document"] = "document"
    output_dimension: int = DEFAULT_DIMENSION



# --- Modell ---

def load_model() -> None:
    tokenizer = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
    tokenizer.enable_truncation(max_length=MAX_TOKENS)
    tokenizer.enable_padding(pad_id=tokenizer.token_to_id(PAD_TOKEN), pad_token=PAD_TOKEN)

    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    # Arena und Speichermuster wachsen sonst mit dem Spitzenbedarf jeder Textlänge
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")

    model_file = str(MODEL_DIR / "onnx" / "model_quantized.onnx")
    MODEL["tokenizer"] = tokenizer
    MODEL["session"] = onnxruntime.InferenceSession(model_file, options, providers=["CPUExecutionProvider"])



def encode_batch(texts: list[str], dimension: int) -> list[list[float]]:
    encodings = MODEL["tokenizer"].encode_batch(texts)
    input_ids = np.array([encoding.ids for encoding in encodings], dtype=np.int64)
    attention_mask = np.array([encoding.attention_mask for encoding in encodings], dtype=np.int64)

    inputs = {"input_ids": input_ids, "attention_mask": attention_mask}
    hidden_states = MODEL["session"].run(["last_hidden_state"], inputs)[0]

    # Last-token Pooling: Zustand des letzten echten Tokens, Padding steht rechts
    last_positions = attention_mask.sum(axis=1) - 1
    pooled = hidden_states[np.arange(len(texts)), last_positions][:, :dimension]

    norms = np.linalg.norm(pooled, axis=1, keepdims=True)
    return (pooled / norms).tolist()



# --- App ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    yield



app = FastAPI(lifespan=lifespan)



def check_api_key(authorization: str = Header(default="")) -> None:
    if not hmac.compare_digest(authorization, f"Bearer {API_KEY}"):
        raise HTTPException(status_code=401, detail="unauthorized")



@app.get("/health")
def get_health() -> dict:
    return {"status": "ok", "ready": "session" in MODEL}



# Normale def-Funktion: FastAPI rechnet sie im Threadpool, der Event Loop bleibt frei
@app.post("/v1/embedding", dependencies=[Depends(check_api_key)])
def create_embedding(request: EmbeddingRequest) -> dict:
    texts = [request.input] if isinstance(request.input, str) else request.input

    if not texts or len(texts) > MAX_TEXTS:
        raise HTTPException(status_code=422, detail=f"input braucht 1 bis {MAX_TEXTS} Texte")

    if not 1 <= request.output_dimension <= MAX_DIMENSION:
        raise HTTPException(status_code=422, detail=f"output_dimension muss zwischen 1 und {MAX_DIMENSION} liegen")

    prompt = PROMPTS[request.input_type]
    vectors = []

    with ENCODE_LOCK:
        for start in range(0, len(texts), MICRO_BATCH_SIZE):
            batch = [prompt + text for text in texts[start:start + MICRO_BATCH_SIZE]]
            vectors += encode_batch(batch, request.output_dimension)

    data = [{"object": "embedding", "index": index, "embedding": vector} for index, vector in enumerate(vectors)]
    return {"object": "list", "data": data, "model": MODEL_NAME}
