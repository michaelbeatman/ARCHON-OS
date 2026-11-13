#!/usr/bin/env python3
"""
Batch-translate locale JSON files (it.json, nl.json) from German (de.json) using OmniRoute.
Preserves structure, only translates values that differ from German.
"""

import json
import requests
import time
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple
import hashlib

# Config
LOCALES_DIR = Path("/mnt/raid/AgenticOS-2026/static/locales")
SOURCE_LANG = "de"
TARGET_LANGS = ["it", "nl"]
OMNIROUTE_URL = "http://localhost:20128/v1/chat/completions"
MODEL = "meta/muse-spark-1.3-contributor"  # bezahltes Modell über OpenRouter
BATCH_SIZE = 30  # smaller batches for reliability
DELAY_BETWEEN_CALLS = 1.0  # seconds
MAX_RETRIES = 3


def load_json(path: Path) -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path: Path, data: Dict[str, Any]):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def flatten_dict(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """Flatten nested dict to dot-notation keys."""
    result = {}
    for k, v in d.items():
        new_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result.update(flatten_dict(v, new_key))
        else:
            result[new_key] = v
    return result


def unflatten_dict(flat: Dict[str, Any]) -> Dict[str, Any]:
    """Convert dot-notation keys back to nested dict."""
    result = {}
    for key, value in flat.items():
        parts = key.split('.')
        target = result
        for part in parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]
        target[parts[-1]] = value
    return result


def get_translatable_keys(source: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, str]:
    """Find keys where target still equals source (needs translation)."""
    source_flat = flatten_dict(source)
    target_flat = flatten_dict(target)
    
    to_translate = {}
    for key, src_val in source_flat.items():
        if key in target_flat:
            tgt_val = target_flat[key]
            # Only translate if target equals source (still German) and is a string
            if isinstance(src_val, str) and isinstance(tgt_val, str) and src_val == tgt_val:
                to_translate[key] = src_val
    return to_translate


def build_prompt(values: Dict[str, str], target_lang: str) -> str:
    """Build translation prompt for a batch of values."""
    lang_names = {"it": "Italian", "nl": "Dutch"}
    lang_name = lang_names.get(target_lang, target_lang)
    
    return f"""Translate these German UI strings to {lang_name}. Return ONLY valid JSON with the same keys.

Rules:
- Keep placeholders like {{count}}, {{role}}, {{e}} exactly as-is
- Keep technical terms (API keys, tool names, skill IDs, MCP server names) in English
- Keep section references like § 8 AGG, Art. 6 DSGVO as-is
- Natural, professional UI language (not literal)
- Plural forms: {{count}} Element/e → {{count}} elemento/i (it), {{count}} element/en (nl)

Source:
{json.dumps(values, ensure_ascii=False)}"""


def translate_batch(values: Dict[str, str], target_lang: str) -> Dict[str, str]:
    """Translate a batch of values via OmniRoute."""
    prompt = build_prompt(values, target_lang)
    
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": f"You are a professional UI translator. Translate German to {target_lang}. Return ONLY valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 4000
    }
    
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(OMNIROUTE_URL, json=payload, timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                content = data['choices'][0]['message']['content'].strip()
                
                # Extract JSON from response (handle potential markdown)
                if content.startswith('```json'):
                    content = content[7:-3].strip()
                elif content.startswith('```'):
                    content = content[3:-3].strip()
                
                result = json.loads(content)
                # Validate all keys present
                if set(result.keys()) == set(values.keys()):
                    return result
                else:
                    print(f"  ⚠ Key mismatch: got {set(result.keys()) - set(values.keys())} extra, missing {set(values.keys()) - set(result.keys())}")
            else:
                print(f"  ⚠ HTTP {resp.status_code}: {resp.text[:200]}")
        except json.JSONDecodeError as e:
            print(f"  ⚠ JSON decode error (attempt {attempt+1}): {e}")
            print(f"  Response: {content[:500]}")
        except Exception as e:
            print(f"  ⚠ Error (attempt {attempt+1}): {e}")
        
        if attempt < MAX_RETRIES - 1:
            time.sleep(2 ** attempt)
    
    # Fallback: return original values (mark as untranslated)
    print(f"  ❌ FAILED after {MAX_RETRIES} attempts, keeping German")
    return values


def translate_locale(source: Dict[str, Any], target: Dict[str, Any], target_lang: str) -> Dict[str, Any]:
    """Translate all untranslated keys in target locale."""
    to_translate = get_translatable_keys(source, target)
    total = len(to_translate)
    print(f"\n{'='*60}")
    print(f"Translating {target_lang}: {total} keys to translate")
    print(f"{'='*60}")
    
    if total == 0:
        print("Nothing to translate!")
        return target
    
    target_flat = flatten_dict(target)
    keys_list = list(to_translate.items())
    
    # Checkpoint file for resume
    checkpoint_file = LOCALES_DIR / f".{target_lang}_translation_checkpoint.json"
    target_file = LOCALES_DIR / f"{target_lang}.json"
    if checkpoint_file.exists():
        with open(checkpoint_file, 'r') as f:
            checkpoint = json.load(f)
            done_count = checkpoint.get('done', 0)
            if done_count > 0:
                print(f"  Resuming from checkpoint: {done_count} keys already done")
                keys_list = keys_list[done_count:]
    
    # Process in batches
    for i in range(0, len(keys_list), BATCH_SIZE):
        batch = dict(keys_list[i:i+BATCH_SIZE])
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (len(keys_list) + BATCH_SIZE - 1) // BATCH_SIZE
        
        print(f"\nBatch {batch_num}/{total_batches} ({len(batch)} keys)...")
        translated = translate_batch(batch, target_lang)
        
        # Update target_flat
        for k, v in translated.items():
            target_flat[k] = v
        
        # Save checkpoint AND persist to file every batch
        done = i + len(batch)
        checkpoint = {'done': done, 'lang': target_lang}
        with open(checkpoint_file, 'w') as f:
            json.dump(checkpoint, f)
        
        # Persist to actual locale file (atomic write)
        temp_file = target_file.with_suffix('.json.tmp')
        save_json(temp_file, unflatten_dict(target_flat))
        temp_file.replace(target_file)
        
        # Progress
        print(f"  Progress: {done}/{total} ({done/total*100:.1f}%)")
        
        time.sleep(DELAY_BETWEEN_CALLS)
    
    # Clean up checkpoint on success
    if checkpoint_file.exists():
        checkpoint_file.unlink()
    
    # Final save
    save_json(target_file, unflatten_dict(target_flat))
    return unflatten_dict(target_flat)


def main():
    print("Loading source locale...")
    source = load_json(LOCALES_DIR / f"{SOURCE_LANG}.json")
    
    for lang in TARGET_LANGS:
        target_path = LOCALES_DIR / f"{lang}.json"
        print(f"\nLoading {lang}.json...")
        target = load_json(target_path)
        
        # Backup
        backup_path = LOCALES_DIR / f"{lang}.json.backup_{int(time.time())}"
        save_json(backup_path, target)
        print(f"Backup: {backup_path}")
        
        # Translate
        translated = translate_locale(source, target, lang)
        
        # Save
        save_json(target_path, translated)
        print(f"\n✅ Saved {target_path}")
        
        # Verify
        src_flat = flatten_dict(source)
        tgt_flat = flatten_dict(translated)
        still_german = sum(1 for k, v in src_flat.items() 
                          if k in tgt_flat and isinstance(v, str) and isinstance(tgt_flat[k], str) 
                          and v == tgt_flat[k])
        print(f"  Remaining German keys: {still_german}/{len(src_flat)}")


if __name__ == "__main__":
    main()