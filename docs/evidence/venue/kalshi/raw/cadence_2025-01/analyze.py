import csv,statistics,sys
from datetime import datetime
from zoneinfo import ZoneInfo
TZ={'ATL':'America/New_York','AUS':'America/Chicago','BOS':'America/New_York','DFW':'America/Chicago','DEN':'America/Denver','HOU':'America/Chicago','LAS':'America/Los_Angeles','SDF':'America/Kentucky/Louisville','MSP':'America/Chicago','MSY':'America/Chicago','EWR':'America/New_York','OKC':'America/Chicago','PHL':'America/New_York','PHX':'America/Phoenix','SAT':'America/Chicago','SAN':'America/Los_Angeles','SEA':'America/Los_Angeles','TTN':'America/New_York','DCA':'America/New_York','LAX':'America/Los_Angeles','NYC':'America/New_York'}
UTC=ZoneInfo('Etc/UTC')
def run(path,loc,drop_missing):
    tz=ZoneInfo(TZ[loc]); byday={}
    with open(path) as f:
        for r in csv.DictReader(f):
            v=r.get('valid');
            if not v: continue
            if drop_missing and r.get('tmpf','M').strip() in ('M',''): continue
            t=datetime.strptime(v.strip(),'%Y-%m-%d %H:%M').replace(tzinfo=UTC).astimezone(tz)
            if 12<=t.hour<17: byday.setdefault(t.date(),set()).add(t)
    meds=[]
    for d,s in sorted(byday.items()):
        ts=sorted(s)
        if len(ts)<3: continue
        gaps=[(b-a).total_seconds()/60 for a,b in zip(ts,ts[1:])]
        meds.append(statistics.median(gaps))
    if not meds: return (0,None,None)
    pct=100*sum(1 for m in meds if m<=5)/len(meds)
    return (len(meds),statistics.median(meds),pct)
for loc,path in [('HOU','raw/KHOU_2025-07_validation.csv'),('ATL','raw/KATL_2025-07_validation.csv')]:
    for dm in (False,True):
        print(loc,'drop_missing=',dm,run(path,loc,dm))

print('---')
locs="ATL AUS BOS DFW DEN HOU LAS SDF MSP MSY EWR OKC PHL PHX SAT SAN SEA TTN DCA LAX NYC".split()
for l in locs:
    n,m,p=run(f'raw/K{l}_2025-01.csv',l,False)
    n2,m2,p2=run(f'raw/K{l}_2025-01.csv',l,True)
    print(f'K{l}|2025-01|{n}|{m}|{p:.1f}|withtemp:{m2},{p2:.1f}')
n,m,p=run('raw/KHOU_2025-10.csv','HOU',False); print(f'KHOU|2025-10|{n}|{m}|{p:.1f}')
