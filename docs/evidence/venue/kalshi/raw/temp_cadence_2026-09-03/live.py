import json,time,datetime as dt,urllib.request,urllib.parse,statistics,pathlib,sys
D=pathlib.Path("/tmp/claude-1000/-home-jon-breezy/916712b1-fb88-42b1-b868-e7d1746cff96/scratchpad/station_cadence_temp")
(D/"live").mkdir(parents=True,exist_ok=True)
OFF={"KATL":-5,"KBOS":-5,"KSDF":-5,"KEWR":-5,"KPHL":-5,"KTTN":-5,"KDCA":-5,"KNYC":-5,
"KAUS":-6,"KDFW":-6,"KHOU":-6,"KMSP":-6,"KMSY":-6,"KOKC":-6,"KSAT":-6,
"KDEN":-7,"KPHX":-7,"KLAS":-8,"KLAX":-8,"KSAN":-8,"KSEA":-8}
STN=["KATL","KAUS","KBOS","KDFW","KDEN","KHOU","KLAS","KSDF","KMSP","KMSY","KEWR","KOKC","KPHL","KPHX","KSAT","KSAN","KSEA","KTTN","KDCA","KLAX","KNYC"]
DAY=dt.date(2026,9,3)
UA={"User-Agent":"breezy-research/1.0 (jon@gopoint.com)","Accept":"application/geo+json"}
out={}
for s in STN:
    o=OFF[s]
    st=dt.datetime.combine(DAY,dt.time(12,0),dt.timezone(dt.timedelta(hours=o)))
    en=dt.datetime.combine(DAY,dt.time(17,0),dt.timezone(dt.timedelta(hours=o)))
    q=urllib.parse.urlencode({"start":st.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                              "end":en.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),"limit":500})
    url=f"https://api.weather.gov/stations/{s}/observations?{q}"
    body=None
    for att in range(4):
        try:
            r=urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=60)
            body=r.read();break
        except Exception as e:
            code=getattr(e,'code',None)
            if code in (429,502,503,504) or code is None:
                time.sleep(5*(att+1));continue
            out[s]={"err":f"{code} {e}"};break
    if body is None:
        out.setdefault(s,{"err":"UNRESOLVED"});time.sleep(0.6);continue
    (D/"live"/f"{s}.json").write_bytes(body)
    j=json.loads(body)
    ts=[]
    for f in j.get("features",[]):
        p=f["properties"]
        if p.get("temperature",{}).get("value") is not None:
            ts.append(dt.datetime.fromisoformat(p["timestamp"].replace("Z","+00:00")))
    ts=sorted(set(ts))
    ts=[t for t in ts if st<=t<en]
    gaps=[(b-a).total_seconds()/60 for a,b in zip(ts,ts[1:])]
    out[s]={"n":len(ts),"med":round(statistics.median(gaps),2) if gaps else None,"url":url}
    print(s,out[s]["n"],out[s]["med"],flush=True)
    time.sleep(0.6)
(D/"live_summary.json").write_text(json.dumps(out,indent=1))
