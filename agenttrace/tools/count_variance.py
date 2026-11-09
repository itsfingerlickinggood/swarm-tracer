"""Spread of the named message count when every estimated time is perturbed.
Usage: python3 -m agenttrace.tools.count_variance DATA [DRAWS] [OUT.json]"""
import os, sys, json, random, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agenttrace.session import Session
from agenttrace import messages
s = Session(); t0=time.time()
s.load(sys.argv[1], "auto")
print("loaded", round(time.time()-t0,1), file=sys.stderr)
ops = messages.channel_ops(s.events, s.pack, s.rec, s.res)
fam = messages.program_prefix(s.events)
def named(dels):
    n = [d for d in dels if not d["from"].startswith("run:") and not d["to"].startswith("run:")]
    return len(n), len({(d["from"], d["to"]) for d in n}), len({d["from"] for d in n} | {d["to"] for d in n})
base = named(messages.deliveries(ops, fam, None)[0])
print("base", base, file=sys.stderr)
out = {"base": base, "runs": {}}
for sigma in (0.12, 1.0, 2.0):
    rng = random.Random(7); vals = []
    for i in range(int(sys.argv[2]) if len(sys.argv) > 2 else 100):
        noise = {}
        def nz(rid):
            if rid not in noise: noise[rid] = rng.gauss(0, sigma) * 3600
            return noise[rid]
        p = [o[:4] + ((o[4] + nz(o[6])) if o[4] is not None else None,) + o[5:] for o in ops]
        vals.append(named(messages.deliveries(p, fam, None)[0]))
    def q(k):
        xs = sorted(v[k] for v in vals); n=len(xs)
        return [xs[0], xs[int(0.025*n)], xs[n//2], xs[min(n-1,int(0.975*n))], xs[-1]]
    out["runs"][sigma] = {"messages": q(0), "pairs": q(1), "tokens": q(2), "draws": len(vals)}
    print(sigma, out["runs"][sigma], file=sys.stderr)
json.dump(out, open(sys.argv[3] if len(sys.argv) > 3 else "count_variance.json", "w"), indent=1)
