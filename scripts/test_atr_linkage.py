import json
from pathlib import Path
from collections import defaultdict

def test_atr_analysis(out_dir):
    out_dir = Path(out_dir)
    
    # 1. Load linkages
    linkages = {}
    linkage_path = out_dir / "atr_linkage.jsonl"
    if linkage_path.exists():
        for line in open(linkage_path):
            rec = json.loads(line)
            # atr_key -> referenced_report_key
            linkages[rec['atr_key']] = rec['references_report_key']
            
    # 2. Load analysis
    analysis = {}
    analysis_path = out_dir / "analysis_discourse.jsonl"
    if analysis_path.exists():
        for line in open(analysis_path):
            rec = json.loads(line)
            # key#rec_no -> label
            if rec.get('kind') == 'qa_response_analysis':
                # Actually for ATR it might be different. Let's checkKind.
                pass
            analysis[(rec['key'], rec.get('recommendation_no'))] = rec
            
    # 3. Load answers
    answers = defaultdict(list)
    answers_path = out_dir / "answers.jsonl"
    if answers_path.exists():
        for line in open(answers_path):
            rec = json.loads(line)
            if rec.get('kind') == 'atr_response':
                answers[rec['key']].append(rec)
                
    # 4. Generate summary
    print("# ATR Linkage and Accountability Audit\n")
    for atr_key, ref_key in linkages.items():
        print(f"## ATR: {atr_key} -> Original Report: {ref_key}")
        recs = answers.get(atr_key, [])
        print(f"Total Recommendations found in ATR: {len(recs)}")
        
        counts = defaultdict(int)
        for r in recs:
            ana = analysis.get((atr_key, r['recommendation_no']))
            label = ana['label'] if ana else "MISSING"
            counts[label] += 1
            
        print("\n### Ministry Response Distribution:")
        for label, count in sorted(counts.items(), key=lambda x: x[1], reverse=True):
            print(f"- **{label}**: {count}")
            
        # Show top example of each category
        seen_labels = set()
        print("\n### Selective Audit of Individual Recommendations:")
        for r in recs:
            ana = analysis.get((atr_key, r['recommendation_no']))
            label = ana['label'] if ana else "MISSING"
            if label in ['CONSTITUTIONAL_DEFAULT', 'SUBSTITUTED', 'ACCEPTED', 'REJECTED'] and label not in seen_labels:
                print(f"\n#### [{label}] Recommendation {r['recommendation_no']}")
                print(f"**Recommendation:** {r['recommendation_text'][:200]}...")
                print(f"**Ministry Reply:** {r['response_text'][:200]}...")
                seen_labels.add(label)
        print("\n---\n")

if __name__ == "__main__":
    test_atr_analysis("CommonerLLP/commoner-analyse/data/atr-test")
