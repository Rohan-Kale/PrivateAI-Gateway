"""Human-in-the-loop trial. Never substitutes program runtime for human triage time."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import statistics
import time
from agents.issue_triage import triage
from experiments.common import provenance,write_report

# Matched pairs have related complexity but different wording. Labels are explicit
# synthetic ground truth; no participant responses are pre-populated.
PAIRS=[
 ("security",("Authentication bypass exposes another tenant's jobs","Cross-tenant request returns someone else's private result")),
 ("security",("PII leak in provider requests","Private email is forwarded without its required replacement")),
 ("security",("Credential leak through verbose logs","Raw customer token appears in application logs")),
 ("bug",("Gateway crashes when the detector disconnects","Worker fails to retry after an upstream timeout")),
 ("bug",("Cache returns an error for an empty response","Expired jobs remain visible after their retention period")),
 ("bug",("Streaming response has broken Unicode","Response emits its final event twice")),
 ("documentation",("Docs omit the policy version field","Explain the policy update format in the README")),
 ("documentation",("Documentation has the wrong Redis hostname","Deployment guide points at an obsolete service address")),
 ("documentation",("Docs need a troubleshooting example","Describe what to do when readiness checks fail")),
 ("enhancement",("Add a second provider adapter","Support selecting a different inference backend")),
 ("enhancement",("Expose a request cost estimate","Add an estimated token-cost field to responses")),
 ("enhancement",("Offer a dashboard for policy changes","Add a small user interface to edit tenant rules")),
]


def assignment(participant):
    seed=int.from_bytes(hashlib.sha256(participant.encode()).digest()[:8],"big")
    rng=random.Random(seed);cases=[]
    for pair,(label,titles) in enumerate(PAIRS):
        modes=["manual","assisted"];rng.shuffle(modes)
        for index,(title,mode) in enumerate(zip(titles,modes)):
            cases.append({"pair":pair,"id":f"{pair}-{index}","title":title,"body":"","expected_label":label,"expected_priority":"high" if label=="security" else "normal","mode":mode})
    rng.shuffle(cases);return cases


def summarize(rows,complete):
    result={"complete":complete,"reviewed_cases":len(rows),"wrong_attempts":sum(r["wrong_attempts"] for r in rows)}
    if not complete:return result
    manual=[r["seconds"] for r in rows if r["mode"]=="manual"]
    assisted=[r["seconds"] for r in rows if r["mode"]=="assisted"]
    m=statistics.median(manual);a=statistics.median(assisted)
    result.update(manual_median_seconds=m,assisted_median_seconds=a,median_reduction_percent=100*(m-a)/m if m else None,participant_sample_size=1)
    return result


def run(participant,output):
    path=Path(output)
    if path.exists():raise ValueError("choose a fresh output file; previous trials cannot be overwritten")
    rows=[];cases=assignment(participant);metadata={**provenance(),"experiment":"human-triage-v2","participant":participant,"assistance":"deterministic Python issue agent with review rationale","protocol":"Randomized matched issue pairs. Participant rubric is separate from agent issue input. Timer includes reading, proposal generation, decisions, and corrections. Accuracy is checked against synthetic gold labels.","limitations":"One participant, synthetic development examples, possible learning/order effects; not a blinded holdout or real issue-tracker productivity estimate."}
    print("24 cases. Enter: LABEL PRIORITY. Labels: security, bug, documentation, enhancement. Priorities: high, normal.")
    print("Classify the reported behavior and assign high priority only to security reports.")
    input("Press Enter when ready. The next case starts the clock.")
    try:
        for case in cases:
            start=time.perf_counter();proposal=triage(case) if case["mode"]=="assisted" else None
            print(f"\n[{case['mode']}] {case['title']}\n{case['body']}")
            if proposal:
                print("Agent suggestion:",proposal["labels"][0],proposal["priority"])
                print("Matched signals:",json.dumps(proposal["matched_signals"]))
                print("Review:"," ".join(proposal["review_steps"]))
            mistakes=0
            while True:
                answer=input("Your reviewed classification: ").strip().lower().split()
                if answer==[case["expected_label"],case["expected_priority"]]:break
                mistakes+=1;print("Does not match the study's gold classification. Review and correct; timer continues.")
            rows.append({"case":case["id"],"pair":case["pair"],"mode":case["mode"],"seconds":time.perf_counter()-start,"wrong_attempts":mistakes,"reviewed_correct":True,"agent_proposal":proposal})
            write_report(path,{**metadata,"summary":summarize(rows,len(rows)==len(cases)),"trials":rows})
    except (KeyboardInterrupt,EOFError):
        write_report(path,{**metadata,"summary":summarize(rows,False),"trials":rows});print("Incomplete trial saved; no speedup claimed.");return
    print(json.dumps(summarize(rows,True),indent=2))


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--participant",required=True,help="pseudonym, not your email");p.add_argument("--output",default="work/evidence/triage.json");a=p.parse_args();run(a.participant,a.output)
