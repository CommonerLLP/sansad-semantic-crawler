import json
from pathlib import Path

def generate_defaults_report(data_dir, out_path):
    data_dir = Path(data_dir)
    analysis = [json.loads(l) for l in open(data_dir / "analysis_discourse.jsonl")]
    answers = {(r['key'], r.get('recommendation_no')): r for r in (json.loads(l) for l in open(data_dir / "answers.jsonl"))}
    defaults = [r for r in analysis if r['label'] == 'CONSTITUTIONAL_DEFAULT']
    
    with open(out_path, "w") as f:
        f.write('# Systemic Audit: Constitutional Defaults in Recruitment ATRs\n\n')
        f.write('## Article 16 Compliance Audit\n\n')
        for d in defaults:
            key = d['key']
            rec_no = d.get('recommendation_no')
            ans = answers.get((key, rec_no), {})
            f.write(f'### Record: {key} (Rec #{rec_no})\n')
            f.write(f'**Matched Pattern:** `{d["matched_pattern"]}`\n')
            f.write(f'**Institutional Meaning:** {d["audit_description"]}\n\n')
            f.write('#### Recommendation\n')
            f.write(f'{ans.get("recommendation_text", "(Missing text)")[:1500]}\n\n')
            f.write('#### Ministry Reply\n')
            f.write(f'{ans.get("response_text", "(Missing text)")[:1500]}\n\n')
            f.write('---\n\n')

if __name__ == "__main__":
    generate_defaults_report("CommonerLLP/commoner-analyse/data/atr-test", "CommonerLLP/notes/research/audits/reconstruction-recruitment-defaults.md")
