"""Toolkit-independent desktop job coordination for the Qt interface."""
from __future__ import annotations
import datetime as dt
import json
import queue
import threading
import time
import sys
from pathlib import Path

import dashcam_process as subprocess
from dashcam_paths import APP_DIR, DATA_DIR
from dashcam_connect import CameraConnection, ConnectionCancelled
from dashcam_live import CaptureSession, media_tool, input_options, read_capabilities, inspect_stream, validate_stream
from dashcam_render import BackgroundRenderer
from dashcam_finalize import CaptureFinalizer
from dashcam_history import DownloadHistory
from dashcam_jobs import OwnedCommand
from dashcam_stitch import scan_clips, group_drives, output_name


class Preview:
    def __init__(self, url):
        self.url = url
        self.frames = queue.Queue(maxsize=1)
        self.process = None
        self.stopped = threading.Event()
        self.state = 'starting'
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            command = [media_tool('ffmpeg'), '-hide_banner', '-loglevel', 'error', *input_options(self.url),
                '-i', self.url, '-an', '-vf', 'fps=10,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2',
                '-threads', '2', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1']
            self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            self.state = 'playing'
            if self.stopped.is_set(): self.process.terminate()
            while not self.stopped.is_set():
                data = bytearray()
                while len(data) < 1280*720*3:
                    chunk = self.process.stdout.read(1280*720*3-len(data))
                    if not chunk: return
                    data.extend(chunk)
                if self.frames.empty(): self.frames.put(b'P6\n1280 720\n255\n'+data)
        finally:
            if self.process:
                if self.process.poll() is None:
                    self.process.terminate()
                    try: self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired: self.process.kill(); self.process.wait()
                self.process.stdout.close()
            self.state = 'stopped'

    def stop(self):
        self.stopped.set()
        if self.process and self.process.poll() is None: self.process.terminate()

    def wait(self):
        self.thread.join(6)
        if self.thread.is_alive(): raise TimeoutError('Preview is still stopping.')


class Desktop:
    def __init__(self, data_dir=DATA_DIR, *, auto_connect=True):
        self.data_dir = Path(data_dir)
        self.capture_dir = self.data_dir/'Captures'
        self.transfer_dir = self.data_dir/'Transfers'
        self.music_dir = self.data_dir/'Music'
        self.channel_title = 'My Drive'
        self.route_info = ''
        self.crossfade = 3.0
        self.end_card = 20.0
        self.video_encoder = 'auto'
        self.target = 'original'
        self.capture_quality = 720
        self.render_enabled = False
        self.skip_newest = 2
        self.redownload = False
        self.gap_minutes = 5.0
        self.camera = ''
        self.stream = ''
        self.report = None
        self.capabilities = {}
        self.candidates = []
        self.capture = self.renderer = self.finalizer = self.preview = self.connection = None
        self.process = None
        self.command = None
        self.operation = ''
        self.pending_export = None
        self.last_capture = self.last_export = None
        self.live_status = 'Connecting to camera' if auto_connect else 'Camera not connected'
        self.transfer_status = 'Ready to copy stored front-camera clips.'
        self.studio_status = ''
        self.export_percent = self.transfer_percent = 0
        self.events = queue.Queue()
        self.logs = []
        try:
            with (self.transfer_dir/'dashcam_transfer.log').open('rb') as previous:
                previous.seek(0,2);previous.seek(max(0,previous.tell()-100000))
                self.logs=previous.read().decode('utf-8','replace').splitlines()[-2000:]
        except OSError:pass
        self.auto_connect = auto_connect
        self.preview_enabled = auto_connect
        self.retry_count = 0
        self.retry_at = time.monotonic()+.75 if auto_connect else None
        self.healthy_preview = None
        self.closed = False
        self.refresh_needed = True
        self.command_kind = ''
        self._cancel_commands = threading.Event()
        self._capture_cancel = threading.Event()
        self._workers = []
        self._render_observed = None

    @property
    def media_busy(self):
        return bool(self.operation or self.pending_export or self.process or any(j and j.active for j in (self.capture,self.renderer,self.finalizer)))

    @property
    def awake_reasons(self):
        reasons = {name for name, job in (('capture',self.capture),('render',self.renderer),('export',self.finalizer)) if job and job.active}
        if self.operation == 'studio': reasons.add('studio export')
        return reasons

    def log(self, message):
        line = dt.datetime.now().strftime('%H:%M:%S')+'  '+str(message)
        self.logs.append(line)
        if len(self.logs)>2000: del self.logs[:1000]
        try:
            self.transfer_dir.mkdir(parents=True,exist_ok=True)
            with (self.transfer_dir/'dashcam_transfer.log').open('a',encoding='utf-8') as out: out.write(line+'\n')
        except OSError: pass

    def _worker(self, operation, function):
        if self.operation: raise RuntimeError('Wait for the current task to finish.')
        self.operation = operation
        def run():
            try: self.events.put(('result',operation,function()))
            except Exception as exc: self.events.put(('error',operation,str(exc) or 'Task cancelled.'))
        thread=threading.Thread(target=run,daemon=True);self._workers.append(thread);thread.start()

    def _stop_preview(self):
        preview,self.preview=self.preview,None
        if preview:
            preview.stop();preview.wait()

    def _resume_preview(self):
        if self.preview_enabled and self.report and not self.preview and not self.operation and not (self.capture and self.capture.active) and not self.closed:
            self.preview=Preview(self.stream);self.healthy_preview=None

    def connect(self, base=None, *, automatic=False):
        if self.media_busy: raise RuntimeError('Finish the current media task before reconnecting.')
        self.preview_enabled=True
        self.retry_at=None
        if not automatic:self.retry_count=0
        self.report=None
        self.live_status='Looking for camera'
        self.connection=job=CameraConnection(lambda text:self.events.put(('live_status','connection',text)))
        def run():
            self._stop_preview()
            return job.run(base)
        self._worker('connection',run)

    def cancel_connection(self):
        self.retry_at=None
        if self.connection:self.connection.cancel()
        self.live_status='Connection cancelled'

    def _retry(self):
        if self.auto_connect and self.retry_count<3 and not self.closed and not self.media_busy:
            self.retry_count+=1;delay=min(2**self.retry_count,8)
            self.retry_at=time.monotonic()+delay
            self.live_status=f'Camera unavailable. Retrying in {delay}s ({self.retry_count}/3).'
        else:self.live_status='Camera disconnected. Connect to its Wi-Fi, then choose Reconnect.'

    def identify(self, base):
        if self.media_busy:raise RuntimeError('Finish the current media task first.')
        self.connection=job=CameraConnection()
        self._worker('identify',lambda:read_capabilities(base,check=job.check))

    def measure(self, stream):
        if self.media_busy:raise RuntimeError('Finish the current media task first.')
        stream=validate_stream(stream)
        self.preview_enabled=True
        self.connection=job=CameraConnection();self.report=None
        def run():
            self._stop_preview();job.check()
            return stream,inspect_stream(stream,runner=job.run_process)
        self._worker('measure',run)

    def start_capture(self):
        if self.media_busy:raise RuntimeError('Finish the current task first.')
        if not self.report:raise RuntimeError('Connect and measure the camera before capturing.')
        if self.render_enabled and not self.music_dir.is_dir():raise ValueError('Choose a music folder in Studio settings.')
        self.retry_at=None
        self._capture_cancel.clear()
        def run():
            self._stop_preview()
            if self.closed or self._capture_cancel.is_set():raise RuntimeError('Capture start cancelled.')
            capture=CaptureSession(self.stream,self.capture_dir,self.report,quality=self.capture_quality,preview=True,reconnect_attempts=3)
            self.capture=capture
            capture.start()
            self.last_capture=capture.directory
            if self.closed or self._capture_cancel.is_set():capture.stop();return capture.directory
            if self.render_enabled:
                try:
                    self.renderer=renderer=BackgroundRenderer(capture,self.music_dir,self.channel_title,self.route_info,self.crossfade,target_size=self.target)
                    self._render_observed=None
                    renderer.start()
                    if self.closed or self._capture_cancel.is_set():capture.stop()
                except Exception as exc:self.events.put(('log','render','Rendering could not start; raw capture continues: '+str(exc)))
            return capture.directory
        self._worker('capture_start',run)
        self.live_status='Starting capture'

    def stop_capture(self):
        self._capture_cancel.set()
        if self.capture:
            self.capture.stop();self.live_status='Stopping capture and closing the current segment.'
            self.log('Capture stop requested.')

    def export_capture(self, session):
        session=Path(session)
        if self.operation or self.pending_export or self.capture and self.capture.active or self.finalizer and self.finalizer.active:
            raise RuntimeError('Stop capture and wait for the current task first.')
        if self.renderer and self.renderer.active:
            if self.renderer.capture.directory != session:raise RuntimeError('Finish rendering the current capture first.')
            self.pending_export=(session,self.target)
            self.studio_status='Export queued. Finishing background rendering.'
            self.export_percent=0
            return
        self.finalizer=CaptureFinalizer(session,recover=True,raw_only=not(session/'Rendered'/'render.json').exists(),
            target_size=self.target,output_root=session.parent/'Exports'/session.name,cleanup=True)
        self.finalizer.start();self.export_percent=0;self.studio_status='Checking capture segments.'

    def cancel_export(self):
        if self.pending_export:self.pending_export=None;self.studio_status='Queued export cancelled. Rendering continues.'
        if self.finalizer:self.finalizer.stop()
        if self.operation=='studio':self.cancel_command()

    def transfer(self, *, scan=False):
        command=[sys.executable,'-u','-B',str(APP_DIR/'dashcam_downloader.py'),'--output',str(self.transfer_dir),
                 '--history',str(self.transfer_dir/'.dashcam_history.sqlite3'),'--skip-newest',str(self.skip_newest),
                 '--quiet-list' if scan else '--download']
        if self.camera:command+=['--camera',self.camera]
        if self.redownload and not scan:command+=['--redownload-missing']
        self._commands([command],'transfer')

    def render_drives(self, drives):
        if not self.music_dir.is_dir():raise ValueError('Choose a music folder in Studio settings.')
        if not self.channel_title.strip() or self.crossfade<=0 or self.end_card<=0:raise ValueError('Check title and presentation timing in Studio settings.')
        commands=[]
        for drive in drives:
            commands.append([sys.executable,'-u','-B',str(APP_DIR/'dashcam_stitch.py'),'--source',str(self.transfer_dir),
                '--output',str(self.transfer_dir/'Drives'),'--gap-minutes',str(self.gap_minutes),
                '--drive-start',drive[0].started.strftime('%Y-%m-%d_%H-%M-%S'),'--music-dir',str(self.music_dir),
                '--crossfade-seconds',str(self.crossfade),'--channel-title',self.channel_title,'--route-info',self.route_info,
                '--end-card-seconds',str(self.end_card),'--video-encoder',self.video_encoder,'--target-size',self.target,'--overwrite','--stitch'])
        self._commands(commands,'studio')

    def _commands(self, commands, kind):
        if self.media_busy:raise RuntimeError('Finish the current media task first.')
        self.command_kind=kind;self._cancel_commands.clear()
        if kind=='transfer':self.transfer_percent=0;self.transfer_status='Preparing camera transfer'
        else:self.studio_status='Rendering selected drives'
        def run():
            self._stop_preview()
            for command in commands:
                if self._cancel_commands.is_set():return 'Task cancelled. Partial files retained.'
                self.events.put(('log',kind,'Starting '+Path(command[3]).name))
                self.command=owned=OwnedCommand(command)
                self.process=owned.process
                try:
                    if self._cancel_commands.is_set():owned.cancel()
                    for line in self.process.stdout:
                        self.events.put(('command',kind,line.rstrip()))
                        if self._cancel_commands.is_set():owned.cancel()
                    code=owned.wait()
                finally:
                    owned.close();self.command=None;self.process=None
                if self._cancel_commands.is_set():return 'Task cancelled. Partial files retained.'
                if code:raise RuntimeError(f'Task failed (exit {code}). See Logs; source files retained.')
            return 'Transfer finished' if kind=='transfer' else 'Render finished'
        self._worker(kind,run)

    def cancel_command(self):
        self._cancel_commands.set()
        command=self.command
        if command:command.cancel()

    def poll(self):
        while True:
            try:kind,operation,value=self.events.get_nowait()
            except queue.Empty:break
            if kind=='live_status':self.live_status=value;continue
            if kind=='log':self.log(value);continue
            if kind=='command':
                if value.startswith('PROGRESS '):
                    try:
                        progress=json.loads(value[9:]);self.transfer_percent=progress['percent']
                        eta=progress.get('eta_seconds');self.transfer_status=f"{progress['percent']:.1f}% · {progress['done']/1048576:.1f} / {progress['total']/1048576:.1f} MiB"+(f' · {int(eta)//60}m {int(eta)%60:02}s remaining' if eta is not None else '')
                    except (ValueError,KeyError):pass
                else:self.log(value)
                continue
            self.operation=''
            if operation in ('connection','identify','measure') and (self.closed or self.connection and self.connection.cancelled.is_set()):
                self.connection=None;self.live_status='Connection cancelled';continue
            if kind=='error':
                self.refresh_needed=True
                self.log(operation+': '+value)
                if operation in ('connection','identify','measure','capture_start'):
                    self.live_status=value
                    self.connection=None
                    if operation=='connection':
                        self.connection=None
                        if 'cancel' not in value.lower():self._retry()
                elif operation=='transfer':self.transfer_status=value
                else:self.studio_status=value
                self._resume_preview();continue
            if operation=='connection':
                self.connection=None
                if 'candidates' in value:self.candidates=value['candidates'];self.live_status='Multiple cameras found. Choose one in Live settings.'
                else:
                    self.camera=value['address'];self.stream=value['url'];self.report=value['report'];self.capabilities=value['capabilities'];self.candidates=[]
                    self.live_status='Connected';self._resume_preview()
            elif operation=='identify':
                self.connection=None;self.capabilities=value;self.live_status='Device information updated. Camera settings are read-only.'
                advertised=(value.get('media') or {}).get('rtsp')
                if advertised:
                    try:
                        stream=validate_stream(advertised)
                        if stream!=self.stream:self.report=None
                        self.stream=stream
                    except ValueError:pass
            elif operation=='measure':self.connection=None;self.stream,self.report=value;self.live_status='Stream measured';self._resume_preview()
            elif operation=='capture_start':self.log('Capture started: '+str(value));self.refresh_needed=True
            else:
                if operation=='transfer':self.transfer_status=value
                else:self.studio_status=value
                self.log(value);self.refresh_needed=True;self._resume_preview()
        if self.capture and self.operation!='capture_start':
            if self.capture.active:
                elapsed=int(time.monotonic()-self.capture.started)
                self.live_status=self.capture.reason if self.capture.state=='reconnecting' else f'Capturing · {elapsed//60:02}:{elapsed%60:02} · {self.capture.byte_count/1048576:.1f} MiB'
            else:
                self.live_status=self.capture.reason or 'Capture stopped. Open Studio to export.'
                self.log(self.live_status);self.capture=None;self.refresh_needed=True;self._resume_preview()
        if self.renderer and self.operation!='capture_start':
            if self.renderer.active:
                completed=self.renderer.completed
                phase={'preparing':'Preparing music',
                       'waiting':'Waiting for the next closed capture segment',
                       'rendering':f'Rendering segment {completed+1}'}.get(self.renderer.state,'Starting background rendering')
                status=f'{phase} · {completed} completed'
                observed=(self.renderer.state,completed)
                if observed!=self._render_observed:
                    self.log('Background render: '+status);self._render_observed=observed
                self.studio_status=('Export queued · ' if self.pending_export else '')+status
            else:
                self.studio_status=self.renderer.reason or f'Rendering {self.renderer.state}. Select the capture to export.'
                self.log(self.studio_status);self.renderer=None;self.refresh_needed=True
        if self.pending_export and not self.renderer:
            session,target=self.pending_export;self.pending_export=None
            previous=self.target;self.target=target
            try:self.export_capture(session)
            except Exception as exc:self.studio_status=str(exc)
            finally:self.target=previous
        if self.finalizer:
            while True:
                try:self.log('Export: '+self.finalizer.logs.get_nowait())
                except queue.Empty:break
            self.export_percent=self.finalizer.percent;self.studio_status=self.finalizer.message
            if not self.finalizer.active:
                job=self.finalizer;self.finalizer=None
                if job.output:self.last_export=job.output
                self.studio_status=job.reason or ('Final MP4 ready. Working media recycled.' if job.output else 'Export cancelled. Sources retained.')
                self.refresh_needed=True
        if self.preview and self.preview.state=='stopped':
            ended=self.preview;self.preview=None
            if not ended.stopped.is_set():self.report=None;self._retry()
        if self.retry_at and time.monotonic()>=self.retry_at and not self.media_busy:
            self.retry_at=None;self.connect(automatic=True)
        self._workers=[w for w in self._workers if w.is_alive()]

    def frame(self):
        source=self.capture.frames if self.capture and self.capture.active else self.preview.frames if self.preview else None
        if source:
            try:
                frame=source.get_nowait()
                if self.preview:
                    self.healthy_preview=self.healthy_preview or time.monotonic()
                    if time.monotonic()-self.healthy_preview>=30:self.retry_count=0
                return frame
            except queue.Empty:pass
        return None

    def close(self):
        self.closed=True;self.retry_at=None;self.pending_export=None
        self._capture_cancel.set()
        if self.connection:self.connection.cancel()
        self.cancel_command()
        for job in (self.capture,self.renderer,self.finalizer):
            if job:job.stop()
        self._stop_preview()
        for job in (self.capture,self.renderer,self.finalizer):
            if job:job.wait()
        for worker in self._workers:worker.join(1)
        if any(w.is_alive() for w in self._workers):raise TimeoutError('Waiting for the current request to stop.')
        for job in (self.capture,self.renderer,self.finalizer):
            if job:job.stop();job.wait()


def inventory(desktop):
    """Read library metadata; never remove or rewrite media."""
    rows=[]
    def file_row(path,kind,session=None):
        return {'name':path.name,'kind':kind,'status':'Ready','size':path.stat().st_size,'path':path,'session':session,'children':[]}
    for session in sorted(desktop.capture_dir.glob('Capture_*'),reverse=True):
        if not session.is_dir():continue
        raw=sorted(session.glob('part_*.mkv'));rendered=sorted(session.glob('Rendered/part_*.mp4'));old=sorted(session.glob('Finalized_*/Capture.mp4'))
        try:state=json.loads((session/'session.json').read_text())['state']
        except (OSError,ValueError,KeyError):state='Unknown'
        if not raw and not rendered and not old and list((desktop.capture_dir/'Exports'/session.name).glob('Finalized_*/Capture.mp4')):continue
        children=[file_row(p,'Raw segment',session) for p in raw]+[file_row(p,'Rendered segment',session) for p in rendered]+[file_row(p,'Final MP4',session) for p in old]
        rows.append({'name':session.name.removeprefix('Capture_'),'kind':'Capture','status':state,'size':sum(r['size'] for r in children),'path':session,'session':session,'children':children})
    for path in sorted(desktop.capture_dir.glob('Exports/Capture_*/Finalized_*/Capture*.mp4'),reverse=True):
        row=file_row(path,'Final MP4' if path.name=='Capture.mp4' else 'Partial export',desktop.capture_dir/path.parent.parent.name)
        row['name']=path.parent.parent.name.removeprefix('Capture_');rows.append(row)
    represented=set()
    for drive in group_drives(scan_clips(desktop.transfer_dir),dt.timedelta(minutes=desktop.gap_minutes)):
        outputs=sorted(p for p in (desktop.transfer_dir/'Drives').glob('Drive_'+drive[0].started.strftime('%Y-%m-%d_%H-%M-%S')+'*.mp4') if '.mp4.part' not in p.name)
        represented.update(outputs)
        children=[file_row(c.path,'SD source') for c in drive]+[file_row(p,'Drive MP4') for p in outputs]
        rows.append({'name':drive[0].started.strftime('%Y-%m-%d %H:%M:%S'),'kind':'Transferred drive','status':f'{len(drive)} clips','size':sum(c.path.stat().st_size for c in drive),'path':desktop.transfer_dir,'drive':drive,'children':children})
    for path in sorted((desktop.transfer_dir/'Drives').glob('*.mp4')):
        if path not in represented and '.mp4.part' not in path.name:rows.append(file_row(path,'Drive MP4'))
    for path in sorted((desktop.transfer_dir/'Drives').glob('*.mp4.part*')):rows.append(file_row(path,'Partial render'))
    return rows
