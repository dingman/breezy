import time,datetime as dt,urllib.request,urllib.parse,statistics,pathlib,re,csv,io,json,collections
D=pathlib.Path("/tmp/claude-1000/-home-jon-breezy/916712b1-fb88-42b1-b868-e7d1746cff96/scratchpad/station_cadence_temp")
(D/"archive").mkdir(parents=True,exist_ok=True)
OFF={"KATL":-5,"KBOS":-5,"KSDF":-5,"KEWR":-5,"KPHL":-5,"KTTN":-5,"KDCA":-5,"KNYC":-5,
"KAUS":-6,"KDFW":-6,"KHOU":-6,"KMSP":-6,"KMSY":-6,"KOKC":-6,"KSAT":-6,
"KDEN":-7,"KPHX":-7,"KLAS":-8,"KLAX":-8,"KSAN":-8,"KSEA":-8}
STN=["KATL","KAUS","KBOS","KDFW","KDEN","KHOU","KLAS","KSDF","KMSP","KMSY","KEWR","KOKC","KPHL","KPHX","KSAT","KSAN","KSEA","KTTN","KDCA","KLAX","KNYC"]
TG=re.compile(r"\bT[01]\d{3}[01]\d{3}\b")
UA={"User-Agent":"breezy-research/1.0 (jon@gopoint.com)"}
out={}
for s in STN:
    q=urllib.parse.urlencode({"station":s,"data":"metar","data2":"tmpf","year1":2025,"month1":6,"day1":30,
      "year2":2025,"month2":7,"day2":9,"tz":"Etc/UTC","format":"onlycomma","latlon":"no","direct":"no",
      "report_type":"1","report_type_2":"2"}).replace("data2=","data=").replace("report_type_2=","report_type=")
    url=f"https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?{q}"
    txt=None
    for att in range(4):
        try:
            txt=urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=180).read().decode()
            break
        except Exception as e:
            time.sleep(10*(att+1))
    if txt is None:
        out[s]={"err":"UNRESOLVED","url":url};time.sleep(1.1);continue
    (D/"archive"/f"{s}.csv").write_text(txt)
    rows=list(csv.DictReader(io.StringIO(txt)))
    o=OFF[s];perday=collections.defaultdict(list)
    for r in rows:
        try: v=dt.datetime.strptime(r["valid"],"%Y-%m-%d %H:%M").replace(tzinfo=dt.UTC)
        except Exception: continue
        loc=v+dt.timedelta(hours=o)
        if not (dt.date(2025,7,1)<=loc.date()<=dt.date(2025,7,7)): continue
        if not (12<=loc.hour<17): continue
        m=r.get("metar","") or ""
        t=(r.get("tmpf","M") or "M").strip()
        if TG.search(m) or (t not in ("M","")):
            perday[loc.date()].append(v)
    tot=0;gaps=[]
    for d,ts in perday.items():
        ts=sorted(set(ts));tot+=len(ts)
        gaps+= [(b-a).total_seconds()/60 for a,b in zip(ts,ts[1:])]
    out[s]={"days":len(perday),"rows_per_day":round(tot/7,1),"med":round(statistics.median(gaps),2) if gaps else None,"url":url}
    print(s,out[s]["rows_per_day"],out[s]["med"],flush=True)
    time.sleep(1.1)
(D/"archive_summary.json").write_text(json.dumps(out,indent=1))
