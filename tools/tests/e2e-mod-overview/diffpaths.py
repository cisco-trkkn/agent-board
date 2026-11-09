import json,sys,re
def paths(o,p=""):
    t={dict:"object",list:"array",str:"string",bool:"boolean",type(None):"null",int:"number",float:"number"}[type(o)]
    yield p or "$",t
    if isinstance(o,dict):
        for k,v in o.items(): yield from paths(v,f"{p}.{k}")
    elif isinstance(o,list):
        for v in o: yield from paths(v,p+"[]")
def collect(o):
    d={}
    for p,t in paths(o): d.setdefault(p,set()).add(t)
    return d
live,new=(collect(json.load(open(f))) for f in sys.argv[1:3])
# project names differ between two builds taken seconds apart only by content; map keyed paths drop the per-project key
missing=[p for p in live if p not in new]
typediff=[(p,live[p],new[p]) for p in live if p in new and not (live[p]<=new[p] or new[p]<=live[p])]
added=sorted(p for p in new if p not in live)
print("live paths:",len(live),"new paths:",len(new))
print("live paths missing in new:",missing)
print("same-path type changes:",typediff)
print("added paths:",added)
print("projects live/new:",len(json.load(open(sys.argv[1]))["projects"]),len(json.load(open(sys.argv[2]))["projects"]))
