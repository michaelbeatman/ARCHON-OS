# Modell-Feintuning Pipeline Guide (Archon OS 2026)

Dieser Leitfaden dokumentiert die Ende-zu-Ende-Pipeline zum Feintuning kompakter Open-Source-Modelle (wie Qwen 2.5 7B, Llama 3.1 8B oder Mistral NeMo 12B) für Routineaufgaben (Triage, Intent-Klassifikation, Tool-Routing und Tagging).

---

## 1. Architekturübersicht

```
[ Human-in-the-Loop Feedback ]       [ Agent Learnings ]
  (human_feedback: Korrekturen)       (learnings: Regeln)
                 │                             │
                 ▼                             ▼
       ┌──────────────────────────────────────────────┐
       │   scripts/prepare_finetuning_dataset.py      │
       │   - Secrets Scrubbing & Sanitization         │
       │   - Chat / Alpaca / ShareGPT Formate         │
       │   - Deterministischer 90/10 Train/Eval Split │
       └──────────────────────┬───────────────────────┘
                              ▼
        [ train_chat.jsonl ]      [ eval_chat.jsonl ]
                              │
                              ▼
       ┌──────────────────────────────────────────────┐
       │   LoRA Training (Unsloth / SFTTrainer)       │
       │   - Config: config/finetuning/lora_config.yml│
       │   - QLoRA 4-bit (12-24 GB VRAM)              │
       │   - Rank 16, Alpha 32, Cosine LR 2e-4        │
       └──────────────────────┬───────────────────────┘
                              ▼
       ┌──────────────────────────────────────────────┐
       │   Export & Serving                           │
       │   - GGUF Quantisierung (Q4_K_M)              │
       │   - Bereitstellung via Ollama / Omniroute    │
       └──────────────────────────────────────────────┘
```

---

## 2. Datensatz-Extraktion

### CLI-Befehl
```bash
python scripts/prepare_finetuning_dataset.py --format chat --split 0.9
```

Optionen:
- `--format`: `chat` (OpenAI / TRL messages Standard), `alpaca` (`instruction`, `input`, `output`) oder `sharegpt`.
- `--min-score`: Filtert Feedback-Einträge nach Mindestbewertung (`-1` = alle Korrekturen, `0` = neutral/korrigiert, `1` = nur explizit positive).
- `--output-dir`: Zielverzeichnis für generierte `.jsonl`-Dateien (Standard: `data/finetuning/`).

### REST-API
```http
POST /api/operations/finetuning/prepare-dataset
Content-Type: application/json

{
  "format": "chat",
  "min_score": 0,
  "include_learnings": true,
  "split_ratio": 0.9
}
```

---

## 3. Training mit Unsloth oder Hugging Face TRL

Mit den Parametern aus `config/finetuning/lora_config.yml`:

```python
from unsloth import FastLanguageModel
from trl import SFTTrainer, SFTConfig
from datasets import load_dataset

# 1. Modell und Tokenizer laden (4-bit QLoRA)
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="Qwen/Qwen2.5-7B-Instruct",
    max_seq_length=2048,
    load_in_4bit=True
)

# 2. LoRA-Adapter konfigurieren
model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_alpha=32,
    lora_dropout=0.05,
    bias="none"
)

# 3. Datensatz laden
dataset = load_dataset("json", data_files={
    "train": "data/finetuning/train_chat.jsonl",
    "test": "data/finetuning/eval_chat.jsonl"
})

# 4. Trainer initialisieren
trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset["train"],
    eval_dataset=dataset["test"],
    args=SFTConfig(
        output_dir="models/archon-router-lora-v1",
        per_device_train_batch_size=4,
        gradient_accumulation_steps=4,
        warmup_ratio=0.05,
        max_steps=200,
        learning_rate=2e-4,
        fp16=False,
        bf16=True,
        logging_steps=10
    )
)

trainer.train()

# 5. GGUF exportieren für lokale Inferenz
model.save_pretrained_gguf("models/archon-router-gguf", tokenizer, quantization_method="q4_k_m")
```

---

## 4. Bereitstellung in Archon OS

1. **In Ollama registrieren:**
   Erstelle eine Datei `Modelfile`:
   ```dockerfile
   FROM ./models/archon-router-gguf/unsloth.Q4_K_M.gguf
   SYSTEM "Du bist Archon OS, ein hochkompetenter, autonomer Agent für Systemarchitektur, Code-Audit und Betriebsführung."
   PARAMETER temperature 0.2
   ```
   Ausführen: `ollama create archon-routine:7b -f Modelfile`

2. **Omniroute / Hardware-Abstraction anbinden:**
   In `config/agent_router_rules.json` den Modell-Tag `local_routine` auf `archon-routine:7b` mappen, um Routine-Klassifikationen ohne Cloud-API-Kosten lokal abzuwickeln.
