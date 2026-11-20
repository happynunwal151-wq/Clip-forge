from __future__ import annotations
import json, os, re, shutil, subprocess, threading, time, uuid
from pathlib import Path
from typing import Any
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFilesknha
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from store import init_db, save_job, load_jobs, list_creators, add_creator, delete_creator, list_queue, add_queue, delete_queue

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'; UPLOADS = DATA / 'uploads'; OUTPUTS = DATA / 'outputs'
for p in (UPLOADS, OUTPUTS): p.mkdir(parents=True, exist_ok=True)
load_dotenv(ROOT / '.env')
MAX_UPLOAD = int(os.getenv('MAX_UPLOAD_MB', '2048')) * 1024 * 1024
JOBS: dict[str, dict[str, Any]] = {}
LOCK = threading.Lock()
init_db()
JOBS.update(load_jobs())

app = FastAPI(title='ClipForge AI', version='1.1.0', description='Local-first AI short-form video clipping studio')
(ROOT / 'static').mkdir(parents=True, exist_ok=True)
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.webm', '.m4v', '.avi'}

def run(cmd: list[str], timeout: int = 3600) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True)
    except FileNotFoundError:
        raise RuntimeError('FFmpeg is not installed or not on PATH. Install FFmpeg, then restart ClipForge.')
    except subprocess.CalledProcessError as e:
        raise RuntimeError((e.stderr or e.stdout or 'Media processing failed')[-1800:])

def ffprobe(path: Path) -> dict[str, Any]:
    raw = run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,width,height','-of','json',str(path)], 60).stdout
    d=json.loads(raw); duration=float(d.get('format',{}).get('duration') or 0)
    v=next((s for s in d.get('streams',[]) if s.get('codec_type')=='video'),{})
    return {'duration':duration,'width':v.get('width'),'height':v.get('height')}

def safe_name(name: str) -> str:
    stem=re.sub(r'[^a-zA-Z0-9_-]+','_',Path(name).stem).strip('_')[:60] or 'video'
    return stem

def set_job(jid: str, **kwargs):
    with LOCK:
        JOBS[jid].update(kwargs, updated_at=time.time())
        save_job(JOBS[jid])

def parse_subtitle_file(path: Path) -> list[dict[str, Any]]:
    text=path.read_text(encoding='utf-8-sig',errors='replace').replace('\r','')
    blocks=re.split(r'\n\s*\n',text.strip())
    def seconds(stamp: str) -> float:
        stamp=stamp.strip().replace(',', '.')
        parts=stamp.split(':')
        if len(parts)==3: return int(parts[0])*3600+int(parts[1])*60+float(parts[2])
        if len(parts)==2: return int(parts[0])*60+float(parts[1])
        raise ValueError('Invalid subtitle timestamp')
    rows=[]
    for block in blocks:
        lines=block.splitlines()
        idx=next((i for i,line in enumerate(lines) if '-->' in line),None)
        if idx is None: continue
        match=re.search(r'([^ ]+)\s+-->\s+([^ ]+)',lines[idx])
        if not match: continue
        try: start=seconds(match.group(1)); end=seconds(match.group(2))
        except Exception: continue
        content=' '.join(lines[idx+1:])
        content=re.sub(r'<[^>]+>','',content).strip()
        if content and end>start: rows.append({'start':start,'end':end,'text':content,'words':[]})
    return rows

def transcribe(path: Path) -> list[dict[str, Any]]:
    try:
        from faster_whisper import WhisperModel
    except Exception:
        return []
    model_name=os.getenv('WHISPER_MODEL','small')
    model=WhisperModel(model_name, device='cpu', compute_type='int8')
    segments, _ = model.transcribe(str(path), word_timestamps=True, vad_filter=True)
    rows=[]
    for seg in segments:
        words=[]
        for w in (seg.words or []):
            words.append({'text':w.word.strip(),'start':float(w.start),'end':float(w.end)})
        rows.append({'start':float(seg.start),'end':float(seg.end),'text':seg.text.strip(),'words':words})
    return rows

def choose_with_gemini(transcript: list[dict[str,Any]], duration: float, count: int, clip_len: int) -> list[dict[str,Any]]:
    key=os.getenv('GEMINI_API_KEY')
    if not key or not transcript: return []
    try:
        from google import genai
        client=genai.Client(api_key=key)
        compact='\n'.join(f"{s['start']:.1f}-{s['end']:.1f}: {s['text']}" for s in transcript)[:60000]
        prompt=(f"Choose {count} non-overlapping short-video highlights from this transcript. Video duration {duration:.1f}s. "
                f"Target duration about {clip_len}s each. Prefer strong hooks, complete thoughts, emotion, useful insight, humor or surprise. "
                "Return ONLY JSON array objects with start, end, title, reason. Keep times within transcript.\n"+compact)
        response=client.models.generate_content(model=os.getenv('GEMINI_MODEL','gemini-2.5-flash'),contents=prompt)
        txt=response.text or ''
        match=re.search(r'\[.*\]',txt,re.S)
        if not match: return []
        data=json.loads(match.group())
        out=[]
        for x in data:
            s=max(0,float(x['start'])); e=min(duration,float(x['end']))
            if e-s > clip_len + 10:
                mid=(s+e)/2; s=max(0,mid-clip_len/2); e=min(duration,s+clip_len)
            if e-s >= max(10,clip_len*.5):
                out.append({'start':s,'end':e,'title':str(x.get('title','Best moment'))[:80],'reason':str(x.get('reason','AI selected'))[:180],'score':None})
        out.sort(key=lambda x:x['start'])
        non_overlapping=[]
        for item in out:
            if all(item['end']<=old['start'] or item['start']>=old['end'] for old in non_overlapping):
                non_overlapping.append(item)
            if len(non_overlapping)>=count: break
        return non_overlapping
    except Exception:
        return []

def fallback_segments(duration: float, count: int, clip_len: int, transcript: list[dict[str,Any]]) -> list[dict[str,Any]]:
    # Transcript-first heuristic: score self-contained lines using length and hook vocabulary.
    # If no transcript exists, distribute clips across the source instead of pretending AI analysed it.
    length=min(max(clip_len,15),90); candidates=[]
    hooks=re.compile(r'\b(why|how|secret|mistake|never|best|worst|because|truth|actually|insane|important|learn|first|finally|problem|solution)\b',re.I)
    if transcript:
        for seg in transcript:
            text=seg['text']; words=len(text.split());
            if words<5: continue
            score=min(words,45)*0.45 + len(hooks.findall(text))*4
            start=max(0,seg['start']-min(3,length*.08)); end=min(duration,max(seg['end'],start+length))
            if end-start<length*.55: continue
            candidates.append({'start':start,'end':min(duration,start+length),'title':(text[:70]+'…') if len(text)>70 else text,'reason':'Transcript heuristic (add Gemini key for AI ranking)','score':round(score,1)})
    if not candidates:
        step=max(length, duration/max(count,1));
        for i in range(count):
            s=min(max(0,duration-length),i*step + max(0,(step-length)/2))
            candidates.append({'start':s,'end':min(duration,s+length),'title':f'Clip {i+1}','reason':'Evenly spaced fallback — no transcript/AI model available','score':None})
    candidates.sort(key=lambda x: x.get('score') or 0, reverse=True)
    chosen=[]
    for c in candidates:
        if all(c['end']<=x['start'] or c['start']>=x['end'] for x in chosen): chosen.append(c)
        if len(chosen)>=count: break
    return sorted(chosen,key=lambda x:x['start'])

def make_srt(transcript: list[dict[str,Any]], start: float, end: float, dest: Path):
    def stamp(t):
        ms=int(max(0,t)*1000); h=ms//3600000; ms%=3600000; m=ms//60000; ms%=60000; s=ms//1000; ms%=1000
        return f'{h:02}:{m:02}:{s:02},{ms:03}'
    cues=[]
    for seg in transcript:
        if seg['end']<start or seg['start']>end: continue
        words=seg.get('words') or []
        if words:
            for w in words:
                a=max(start,w['start']); b=min(end,w['end'])
                if b>a and w['text'].strip(): cues.append((a-start,b-start,w['text'].strip()))
        else:
            a=max(start,seg['start']); b=min(end,seg['end'])
            if b>a: cues.append((a-start,b-start,seg['text']))
    lines=[]
    for i,(a,b,txt) in enumerate(cues,1): lines += [str(i),f'{stamp(a)} --> {stamp(b)}',txt,'']
    dest.write_text('\n'.join(lines),encoding='utf-8')

def render_clip(source: Path, clip: dict[str,Any], idx: int, jid: str, transcript: list[dict[str,Any]], aspect: str='9:16', burn_captions: bool=True, output_name: str | None=None) -> dict[str,Any]:
    outdir=OUTPUTS/jid; outdir.mkdir(parents=True,exist_ok=True)
    stem=output_name or f'clip_{idx+1:02}'
    target=outdir/f'{stem}.mp4'; srt=outdir/f'{stem}.srt'
    make_srt(transcript,clip['start'],clip['end'],srt)
    if aspect=='1:1': vf='scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080'
    elif aspect=='4:5': vf='scale=1080:1350:force_original_aspect_ratio=increase,crop=1080:1350'
    elif aspect=='16:9': vf='scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080'
    else: vf='scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920'
    # Render without subtitle burn-in if there is no transcript.
    if burn_captions and srt.exists() and srt.stat().st_size:
        srt_arg=str(srt).replace('\\','/').replace(':','\\:').replace("'","\\'")
        vf += f",subtitles='{srt_arg}':force_style='FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=3,Alignment=2,MarginV=150'"
    run(['ffmpeg','-y','-ss',f"{clip['start']:.3f}",'-i',str(source),'-t',f"{clip['end']-clip['start']:.3f}",'-vf',vf,'-c:v','libx264','-preset','veryfast','-crf','22','-c:a','aac','-b:a','160k','-movflags','+faststart',str(target)],timeout=7200)
    thumb=outdir/f'{stem}.jpg'
    try:
        run(['ffmpeg','-y','-ss',f"{max(0,(clip['end']-clip['start'])/2):.3f}",'-i',str(target),'-frames:v','1','-vf','scale=540:-1',str(thumb)],timeout=90)
    except Exception:
        thumb=None
    return {'id':f'{jid}_{idx+1}','title':clip.get('title') or f'Clip {idx+1}','reason':clip.get('reason',''),'score':clip.get('score'),'start':clip['start'],'end':clip['end'],'duration':clip['end']-clip['start'],'url':f'/api/clips/{jid}/{target.name}','srt_url':f'/api/clips/{jid}/{srt.name}','thumbnail_url':f'/api/clips/{jid}/{thumb.name}' if thumb and thumb.exists() else None,'filename':target.name}

def process_job(jid: str, source: Path, count: int, clip_len: int, aspect: str, subtitle_path: Path | None = None):
    try:
        set_job(jid,status='processing',progress=8,stage='Reading video metadata')
        meta=ffprobe(source); duration=meta['duration']
        if duration<=0: raise RuntimeError('Could not read video duration.')
        set_job(jid,progress=18,stage='Transcribing audio (optional local Whisper)')
        transcript=parse_subtitle_file(subtitle_path) if subtitle_path else transcribe(source)
        (OUTPUTS/jid).mkdir(parents=True,exist_ok=True)
        (OUTPUTS/jid/'transcript.json').write_text(json.dumps(transcript,ensure_ascii=False,indent=2),encoding='utf-8')
        set_job(jid,progress=48,stage='Selecting highlight moments')
        clips=choose_with_gemini(transcript,duration,count,clip_len)
        if not clips: clips=fallback_segments(duration,count,clip_len,transcript)
        set_job(jid,progress=58,stage='Rendering vertical clips',transcript_available=bool(transcript),selected=len(clips))
        rendered=[]
        for i,c in enumerate(clips):
            rendered.append(render_clip(source,c,i,jid,transcript,aspect))
            set_job(jid,progress=58+int((i+1)/len(clips)*40),stage=f'Rendering clip {i+1} of {len(clips)}',clips=rendered)
        set_job(jid,status='completed',progress=100,stage='Ready',clips=rendered,metadata=meta,transcript_available=bool(transcript),ai_ranked=bool(os.getenv('GEMINI_API_KEY') and transcript))
    except Exception as e:
        set_job(jid,status='failed',stage='Failed',error=str(e))

@app.get('/', response_class=HTMLResponse)
def home(): return (ROOT/'static'/'index.html').read_text(encoding='utf-8')

@app.get('/api/health')
def health():
    ff=shutil.which('ffmpeg'); fp=shutil.which('ffprobe')
    try:
        import faster_whisper  # noqa
        whisper=True
    except Exception: whisper=False
    return {'ok':True,'version':'1.1.0','ffmpeg':bool(ff),'ffprobe':bool(fp),'whisper_installed':whisper,'gemini_configured':bool(os.getenv('GEMINI_API_KEY'))}

@app.post('/api/jobs')
async def create_job(background: BackgroundTasks, video: UploadFile=File(...), transcript_file: UploadFile | None=File(None), count: int=Form(3), clip_length: int=Form(40), aspect: str=Form('9:16')):
    ext=Path(video.filename or '').suffix.lower()
    if ext not in VIDEO_EXTS: raise HTTPException(400,'Upload an MP4, MOV, MKV, WebM, M4V or AVI video.')
    if count<1 or count>10: raise HTTPException(400,'Choose between 1 and 10 clips.')
    if clip_length<15 or clip_length>90: raise HTTPException(400,'Clip length must be 15–90 seconds.')
    if aspect not in {'9:16','1:1','4:5','16:9'}: raise HTTPException(400,'Unsupported aspect ratio.')
    jid=uuid.uuid4().hex[:12]; dest=UPLOADS/f'{jid}_{safe_name(video.filename)}{ext}'
    size=0
    with dest.open('wb') as f:
        while chunk:=await video.read(1024*1024):
            size+=len(chunk)
            if size>MAX_UPLOAD:
                f.close(); dest.unlink(missing_ok=True); raise HTTPException(413,f'File exceeds {MAX_UPLOAD//(1024*1024)} MB limit.')
            f.write(chunk)
    if not size: dest.unlink(missing_ok=True); raise HTTPException(400,'The uploaded file is empty.')
    subtitle_path=None
    if transcript_file and transcript_file.filename:
        sub_ext=Path(transcript_file.filename).suffix.lower()
        if sub_ext not in {'.srt','.vtt'}:
            dest.unlink(missing_ok=True); raise HTTPException(400,'Transcript must be an SRT or VTT file.')
        subtitle_path=UPLOADS/f'{jid}_captions{sub_ext}'
        raw=await transcript_file.read()
        if len(raw)>20*1024*1024:
            dest.unlink(missing_ok=True); raise HTTPException(413,'Transcript file exceeds 20 MB.')
        subtitle_path.write_bytes(raw)
    JOBS[jid]={'id':jid,'filename':video.filename,'source_path':str(dest),'status':'queued','progress':0,'stage':'Queued','clips':[],'created_at':time.time()}
    save_job(JOBS[jid])
    background.add_task(process_job,jid,dest,count,clip_length,aspect,subtitle_path)
    return {'id':jid,'status':'queued'}

@app.get('/api/jobs')
def list_jobs(): return sorted(JOBS.values(),key=lambda x:x.get('created_at',0),reverse=True)

@app.get('/api/jobs/{jid}')
def get_job(jid: str):
    if jid not in JOBS: raise HTTPException(404,'Job not found.')
    return JOBS[jid]

@app.get('/api/clips/{jid}/{filename}')
def get_clip(jid: str, filename: str):
    if not re.fullmatch(r'[a-f0-9]{12}',jid): raise HTTPException(400,'Invalid job id.')
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+',filename): raise HTTPException(400,'Invalid filename.')
    p=OUTPUTS/jid/filename
    if not p.exists() or not p.is_file(): raise HTTPException(404,'Clip not found.')
    return FileResponse(p, filename=filename)

@app.get('/api/jobs/{jid}/transcript')
def get_transcript(jid: str):
    if not re.fullmatch(r'[a-f0-9]{12}',jid): raise HTTPException(400,'Invalid job id.')
    p=OUTPUTS/jid/'transcript.json'
    if not p.exists(): raise HTTPException(404,'Transcript is not available yet.')
    return json.loads(p.read_text(encoding='utf-8'))


class CreatorInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    platform: str = Field(min_length=1, max_length=30)
    handle: str = Field(default='', max_length=80)

class QueueInput(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    clip_url: str = Field(min_length=1, max_length=300)
    platform: str = Field(min_length=1, max_length=30)
    scheduled_at: str = Field(default='', max_length=40)

@app.get('/api/creators')
def creators_list(): return list_creators()

@app.post('/api/creators')
def creators_add(data: CreatorInput):
    allowed={'Instagram','YouTube Shorts','TikTok','Facebook','Other'}
    if data.platform not in allowed: raise HTTPException(400,'Unsupported platform.')
    return add_creator(data.name.strip(),data.platform,data.handle.strip())

@app.delete('/api/creators/{cid}')
def creators_remove(cid: str):
    if not re.fullmatch(r'[a-f0-9]{12}',cid): raise HTTPException(400,'Invalid creator id.')
    if not delete_creator(cid): raise HTTPException(404,'Creator not found.')
    return {'deleted':True}

@app.get('/api/publishing-queue')
def publishing_queue(): return list_queue()

@app.post('/api/publishing-queue')
def publishing_queue_add(data: QueueInput):
    allowed={'Instagram','YouTube Shorts','TikTok','Facebook','Other'}
    if data.platform not in allowed: raise HTTPException(400,'Unsupported platform.')
    match=re.fullmatch(r'/api/clips/([a-f0-9]{12})/([a-zA-Z0-9_.-]+)',data.clip_url)
    if not match: raise HTTPException(400,'Only ClipForge-generated clip URLs can be queued.')
    clip_path=OUTPUTS/match.group(1)/match.group(2)
    if not clip_path.is_file(): raise HTTPException(404,'Selected clip does not exist.')
    if data.scheduled_at:
        from datetime import datetime
        try: datetime.fromisoformat(data.scheduled_at.replace('Z','+00:00'))
        except ValueError: raise HTTPException(400,'Use an ISO date/time for scheduling.')
    return add_queue(data.title.strip(),data.clip_url,data.platform,data.scheduled_at)

@app.delete('/api/publishing-queue/{qid}')
def publishing_queue_remove(qid: str):
    if not re.fullmatch(r'[a-f0-9]{12}',qid): raise HTTPException(400,'Invalid queue id.')
    if not delete_queue(qid): raise HTTPException(404,'Queue item not found.')
    return {'deleted':True}

class RemixInput(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    aspect: str = Field(default='9:16')
    burn_captions: bool = True

@app.post('/api/jobs/{jid}/remix')
def remix_clip(jid: str, data: RemixInput):
    job=JOBS.get(jid)
    if not job: raise HTTPException(404,'Project not found.')
    if job.get('status')!='completed': raise HTTPException(409,'Wait until the source project has completed.')
    source_value=job.get('source_path')
    source=Path(source_value) if source_value else None
    if not source or not source.is_file(): raise HTTPException(410,'Original source video is no longer available. Re-upload it to create a new edit.')
    if data.aspect not in {'9:16','1:1','4:5','16:9'}: raise HTTPException(400,'Unsupported aspect ratio.')
    try: duration=ffprobe(source)['duration']
    except Exception as e: raise HTTPException(422,str(e))
    if data.start>=duration or data.end>duration or data.end-data.start<1 or data.end-data.start>600:
        raise HTTPException(400,'Choose a range within the source video, at least 1 second and no more than 10 minutes.')
    transcript=[]
    tp=OUTPUTS/jid/'transcript.json'
    if tp.exists(): transcript=json.loads(tp.read_text(encoding='utf-8'))
    remix_id=uuid.uuid4().hex[:8]
    clip={'start':data.start,'end':data.end,'title':f'Custom edit {remix_id}','reason':'Manually trimmed in ClipForge editor','score':None}
    try:
        result=render_clip(source,clip,0,jid,transcript,data.aspect,data.burn_captions,f'remix_{remix_id}')
    except Exception as e:
        raise HTTPException(500,f'Render failed: {e}')
    result.update({'aspect':data.aspect,'burn_captions':data.burn_captions,'custom_edit':True})
    job.setdefault('remixes',[]).append(result)
    set_job(jid,remixes=job['remixes'])
    return result

@app.get('/api/analytics')
def analytics():
    completed=[j for j in JOBS.values() if j.get('status')=='completed']
    clips=[c for j in completed for c in (j.get('clips',[])+j.get('remixes',[]))]
    queued=list_queue()
    return {'projects':len(JOBS),'completed_projects':len(completed),'clips':len(clips),'clip_seconds':round(sum(float(c.get('duration',0)) for c in clips),1),'queue_items':len(queued),'platforms':{p:sum(1 for q in queued if q['platform']==p) for p in {q['platform'] for q in queued}}}
