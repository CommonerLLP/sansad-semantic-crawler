import sys
import json
from pathlib import Path
from collections import Counter

# Add crawler to path
sys.path.append("CommonerLLP/commoner-analyse")
from commoner_analyse.discourse import classify_response_llm, DiscourseClassification, _now

def run_batch_llm(out_dir, batch_size=20):
    out_dir = Path(out_dir)
    answers_path = out_dir / "answers.jsonl"
    discourse_path = out_dir / "analysis_discourse.jsonl"
    
    # 1. Load current analysis
    analysis = {}
    with discourse_path.open() as f:
        for line in f:
            rec = json.loads(line)
            analysis[(rec['key'], rec.get('recommendation_no'))] = rec
            
    # 2. Identify UNCLASSIFIED
    unclassified_keys = [k for k, v in analysis.items() if v['label'] == 'UNCLASSIFIED']
    print(f"Total UNCLASSIFIED: {len(unclassified_keys)}")
    
    # 3. Load full text from answers.jsonl
    answers = {}
    with answers_path.open() as f:
        for line in f:
            rec = json.loads(line)
            if (rec['key'], rec.get('recommendation_no')) in analysis:
                 answers[(rec['key'], rec.get('recommendation_no'))] = rec
                 
    # 4. Process a batch
    to_process = unclassified_keys[:batch_size]
    print(f"Processing batch of {len(to_process)}...")
    
    upgraded = 0
    for key in to_process:
        ans_rec = answers[key]
        text = ans_rec.get('response_text') or ans_rec.get('answer_text') or ""
        channel = "committee" if ans_rec.get('kind') == 'atr_response' else "qa"
        
        try:
            result = classify_response_llm(
                text=text,
                channel=channel,
                endpoint="http://localhost:11434/v1/chat/completions",
                model="qwen2.5:3b-instruct",
                timeout_s=60.0
            )
            if result.label != "UNCLASSIFIED":
                old_rec = analysis[key]
                old_rec.update(result.to_dict())
                old_rec['classifier'] = "llm_discourse_v2"
                old_rec['classified_at'] = _now()
                upgraded += 1
                print(f"  Upgraded {key} -> {result.label}")
        except Exception as e:
            print(f"  Error on {key}: {e}")
            
    # 5. Write back
    if upgraded > 0:
        tmp = discourse_path.with_suffix(".jsonl.tmp")
        with tmp.open("w") as f:
            for rec in analysis.values():
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        tmp.replace(discourse_path)
    
    print(f"Batch complete. Upgraded: {upgraded}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 batch_llm_audit.py <out_dir> [batch_size]")
        sys.exit(1)
    
    out_dir = sys.argv[1]
    batch_size = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    run_batch_llm(out_dir, batch_size=batch_size)
