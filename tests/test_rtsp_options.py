"""Local-only RTSP handshake regression; never contacts camera hardware."""
import os
import socket
import subprocess
import threading
import unittest
from types import SimpleNamespace

from dashcam_live import input_options, media_tool, probe_failure, run_probe, ProbeError


class ProbeDiagnostics(unittest.TestCase):
    def test_errors_classify_stderr_without_exposing_private_values(self):
        private = 'rtsp://private-host/secret?token=private C:\\Users\\private\\sample.mkv'
        for detail, expected in [('Option rw_timeout not found.', 'rejected a stream option'),
                                 ('Connection refused', 'refused the connection'),
                                 ('Permission denied', 'Access was denied'),
                                 ('No space left on device', 'disk is full'),
                                 ('unknown failure', 'could not read')]:
            error = probe_failure('Video-only measurement', SimpleNamespace(returncode=1, stderr=(detail + private).encode()))
            self.assertIn(expected, str(error))
            self.assertNotIn('private', str(error))
            self.assertIn('exit 1', str(error))

    def test_timeout_is_actionable_and_does_not_expose_command(self):
        def timed_out(*args, **kwargs):
            raise subprocess.TimeoutExpired(['rtsp://secret'], 20)
        with self.assertRaisesRegex(ProbeError, 'Stream measurement timed out') as caught:
            run_probe(timed_out, 'Stream measurement', ['rtsp://secret'])
        self.assertNotIn('secret', str(caught.exception))

    def test_http_retains_protocol_timeout(self):
        self.assertIn('-rw_timeout', input_options('http://localhost/stream'))
        self.assertNotIn('-rtsp_transport', input_options('http://localhost/stream'))


@unittest.skipUnless(os.environ.get('DASHGO_MEDIA_TESTS') == '1', 'Enable local media integration tests')
class RtspOptions(unittest.TestCase):
    def test_ffmpeg_accepts_real_rtsp_input_options(self):
        # SDP is sufficient to reproduce FFmpeg's input-option validation. No
        # RTP packets are emitted, so output-header failure is expected later.
        sdp = ('v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=Test\r\n'
               'c=IN IP4 127.0.0.1\r\nt=0 0\r\na=control:*\r\n'
               'm=video 0 RTP/AVP 96\r\na=rtpmap:96 H264/90000\r\n'
               'a=fmtp:96 packetization-mode=1;profile-level-id=64001f\r\na=control:track1\r\n')
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen()
            server.settimeout(5)
            port = server.getsockname()[1]
            methods = []
            def serve():
                try:
                    connection, _ = server.accept()
                    with connection:
                        connection.settimeout(3)
                        data = b''
                        while True:
                            while b'\r\n\r\n' not in data:
                                part = connection.recv(4096)
                                if not part:
                                    return
                                data += part
                            request, data = data.split(b'\r\n\r\n', 1)
                            lines = request.decode().split('\r\n')
                            method = lines[0].split()[0]
                            methods.append(method)
                            seq = next(line.split(':', 1)[1].strip() for line in lines if line.lower().startswith('cseq:'))
                            extra, body = '', ''
                            if method == 'OPTIONS':
                                extra = 'Public: OPTIONS, DESCRIBE, SETUP, PLAY, TEARDOWN\r\n'
                            elif method == 'DESCRIBE':
                                extra = f'Content-Type: application/sdp\r\nContent-Base: rtsp://127.0.0.1:{port}/\r\n'
                                body = sdp
                            elif method == 'SETUP':
                                extra = 'Transport: RTP/AVP/TCP;unicast;interleaved=0-1\r\nSession: localtest\r\n'
                            elif method == 'PLAY':
                                extra = 'Session: localtest\r\nRange: npt=0.000-\r\n'
                            connection.sendall(f'RTSP/1.0 200 OK\r\nCSeq: {seq}\r\n{extra}Content-Length: {len(body)}\r\n\r\n{body}'.encode())
                            if method == 'PLAY':
                                return
                except (OSError, StopIteration):
                    pass
            worker = threading.Thread(target=serve, daemon=True)
            worker.start()
            url = f'rtsp://127.0.0.1:{port}'
            try:
                result = subprocess.run([media_tool('ffmpeg'), '-hide_banner', '-loglevel', 'error',
                                         *input_options(url), '-i', url, '-t', '1', '-map', '0:v:0',
                                         '-an', '-c:v', 'copy', '-f', 'null', '-'], capture_output=True, timeout=8)
            finally:
                worker.join(5)
            stderr = result.stderr.decode(errors='replace').lower()
            self.assertNotIn('option not found', stderr)
            self.assertNotIn('option rw_timeout not found', stderr)
            self.assertIn('PLAY', methods)
            self.assertIn('dimensions not set', stderr)
