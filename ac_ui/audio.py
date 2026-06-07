import os, sys, subprocess, json, time, stat, errno, shutil, socket

import ac_ui.colors as _clrs
from ac_ui.town_tune import spawn_town_tune
from ac_ui.constants import (
    MPV, MUTE_MODE, SOFT_MUTE_VOL, LOOPBACK_LATENCY_MSEC,
    CAVA_FRAMERATE, CAVA_AUTOSENS, CAVA_SENSITIVITY, CAVA_LOWER_CUTOFF,
    CAVA_HIGHER_CUTOFF, CAVA_NOISE_REDUCTION_SET, CAVA_NOISE_REDUCTION,
    CAVA_CHANNELS, CAVA_MAX, CAVA_MIN_BARS, CAVA_MARGIN,
    HOUR_CHIME_PATH, TOWN_TUNE_CHIME_ENABLED,
)

def cava_config_text(bars, input_method=None, input_source=None):
    input_block = ""
    if input_method or input_source:
        input_block = "[input]\n"
        if input_method:
            input_block += f"method = {input_method}\n"
        if input_source:
            input_block += f"source = {input_source}\n"
        input_block += "\n"
    smoothing_block = ""
    if CAVA_NOISE_REDUCTION_SET:
        smoothing_block = f"\n[smoothing]\nnoise_reduction = {CAVA_NOISE_REDUCTION:.2f}\n"
    return (
        "[general]\n"
        f"bars = {bars}\n\n"
        f"framerate = {CAVA_FRAMERATE}\n"
        f"autosens = {CAVA_AUTOSENS}\n"
        f"sensitivity = {CAVA_SENSITIVITY}\n"
        f"lower_cutoff_freq = {CAVA_LOWER_CUTOFF}\n"
        f"higher_cutoff_freq = {CAVA_HIGHER_CUTOFF}\n\n"
        + input_block +
        "[output]\n"
        "method = raw\n"
        "raw_target = /dev/stdout\n"
        "data_format = ascii\n"
        f"ascii_max_range = {CAVA_MAX}\n"
        "bar_delimiter = 59\n"
        "frame_delimiter = 10\n"
        f"channels = {CAVA_CHANNELS}\n"
        + smoothing_block
    )

def calc_cava_bars():
    cols = shutil.get_terminal_size(fallback=(80, 24)).columns
    bars = max(CAVA_MIN_BARS, cols - CAVA_MARGIN)
    if CAVA_CHANNELS == "stereo" and bars % 2:
        bars -= 1
    return bars



def pactl(*args):
    # Suppress pactl stderr to avoid noisy "Failure: No such entity"
    try:
        res = subprocess.run(["pactl", *args], text=True, capture_output=True)
        return res.stdout if res.stdout is not None else ""
    except Exception:
        return ""

def get_default_sink():
    try:
        out = pactl("info")
        for line in out.splitlines():
            if line.startswith("Default Sink:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        return None
    return None

def find_loopback_input_ids(loopback_module_id, sink_name):
    if not loopback_module_id and not sink_name:
        return []
    try:
        out = pactl("list", "sink-inputs")
    except Exception:
        return []
    current_id = None
    module_id = None
    source = None
    media_name = None
    app_name = None
    matches = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Sink Input #"):
            current_id = line.split("#", 1)[1].strip()
            module_id = None
            source = None
            media_name = None
            app_name = None
        elif line.startswith("Module:") or line.startswith("Owner Module:"):
            module_id = line.split(":", 1)[1].strip()
        elif line.startswith("Source:"):
            source = line.split(":", 1)[1].strip()
        elif line.startswith("media.name ="):
            media_name = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("application.name ="):
            app_name = line.split("=", 1)[1].strip().strip('"')
        if not current_id:
            continue
        if loopback_module_id and module_id == str(loopback_module_id):
            matches.append(current_id)
        elif sink_name and source == f"{sink_name}.monitor":
            matches.append(current_id)
        elif media_name and "loopback" in media_name.lower():
            matches.append(current_id)
        elif app_name and "loopback" in app_name.lower():
            matches.append(current_id)
    return list(dict.fromkeys(matches))

def set_loopback_volume(loopback_module_id, sink_name, vol_percent):
    input_ids = find_loopback_input_ids(loopback_module_id, sink_name)
    if not input_ids:
        return False
    ok = False
    for input_id in input_ids:
        try:
            pactl("set-sink-input-volume", input_id, f"{vol_percent}%")
            ok = True
        except Exception:
            pass
    return ok

def set_loopback_mute(loopback_module_id, sink_name, mute_on):
    input_ids = find_loopback_input_ids(loopback_module_id, sink_name)
    if not input_ids:
        return False
    ok = False
    for input_id in input_ids:
        try:
            pactl("set-sink-input-mute", input_id, "1" if mute_on else "0")
            # also force volume to 0 on mute for stubborn backends
            if mute_on:
                pactl("set-sink-input-volume", input_id, "0%")
            ok = True
        except Exception:
            pass
    return ok

def list_sinks():
    if not shutil.which("pactl"):
        return []
    try:
        out = pactl("list", "short", "sinks")
    except Exception:
        return []
    sinks = []
    for line in out.splitlines():
        cols = line.split("\t")
        if len(cols) > 1:
            sinks.append(cols[1].strip())
    return [s for s in sinks if s]

def list_loopback_modules(sink_name):
    if not shutil.which("pactl") or not sink_name:
        return []
    try:
        out = pactl("list", "short", "modules")
    except Exception:
        return []
    needle = f"source={sink_name}.monitor"
    matches = []
    for line in out.splitlines():
        cols = line.split("\t", 2)
        if len(cols) < 2:
            continue
        module_id = cols[0].strip()
        module_name = cols[1].strip()
        module_args = cols[2].strip() if len(cols) > 2 else ""
        if module_name == "module-loopback" and needle in module_args:
            matches.append(module_id)
    return matches

def list_null_sink_modules(sink_name):
    if not shutil.which("pactl") or not sink_name:
        return []
    try:
        out = pactl("list", "short", "modules")
    except Exception:
        return []
    needle = f"sink_name={sink_name}"
    matches = []
    for line in out.splitlines():
        cols = line.split("\t", 2)
        if len(cols) < 2:
            continue
        module_id = cols[0].strip()
        module_name = cols[1].strip()
        module_args = cols[2].strip() if len(cols) > 2 else ""
        if module_name == "module-null-sink" and needle in module_args:
            matches.append(module_id)
    return matches

def get_sink_id(sink_name):
    if not shutil.which("pactl") or not sink_name:
        return None
    try:
        out = pactl("list", "short", "sinks")
    except Exception:
        return None
    for line in out.splitlines():
        cols = line.split("\t")
        if len(cols) > 1 and cols[1].strip() == sink_name:
            try:
                return int(cols[0].strip())
            except Exception:
                return None
    return None

def sink_has_inputs(sink_id):
    if sink_id is None or not shutil.which("pactl"):
        return False
    try:
        out = pactl("list", "short", "sink-inputs")
    except Exception:
        return False
    target = str(sink_id)
    for line in out.splitlines():
        cols = line.split("\t")
        if len(cols) > 1 and cols[1].strip() == target:
            return True
    return False

def cleanup_stale_socket(path):
    if not path or not os.path.exists(path):
        return
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return
    if not stat.S_ISSOCK(mode):
        return
    import socket
    sock = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.1)
        sock.connect(path)
        return
    except OSError as e:
        if e.errno not in (errno.ENOENT, errno.ECONNREFUSED, errno.EPERM):
            return
    except Exception:
        pass
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
    try:
        os.unlink(path)
    except Exception:
        pass

def cleanup_legacy_runtime_artifacts():
    legacy_sink = "acui"
    sink_id = get_sink_id(legacy_sink)
    if sink_id is not None and not sink_has_inputs(sink_id):
        for module_id in list_loopback_modules(legacy_sink):
            try:
                pactl("unload-module", module_id)
            except Exception:
                pass
        for module_id in list_null_sink_modules(legacy_sink):
            try:
                pactl("unload-module", module_id)
            except Exception:
                pass
    legacy_base = f"/tmp/ac-mpv-{os.getuid()}"
    cleanup_stale_socket(f"{legacy_base}.a.sock")
    cleanup_stale_socket(f"{legacy_base}.b.sock")
    legacy_cava_conf = f"/tmp/ac-cava-{os.getuid()}.conf"
    try:
        if os.path.exists(legacy_cava_conf):
            os.unlink(legacy_cava_conf)
    except Exception:
        pass

def reload_loopback(loopback_module_id, sink_name, target_sink):
    if not shutil.which("pactl"):
        return loopback_module_id, None
    if not target_sink:
        target_sink = get_default_sink()
    if not target_sink:
        return loopback_module_id, None
    if loopback_module_id:
        try:
            pactl("unload-module", loopback_module_id)
        except Exception:
            pass
    try:
        new_id = pactl(
            "load-module",
            "module-loopback",
            f"source={sink_name}.monitor",
            f"sink={target_sink}",
            f"latency_msec={LOOPBACK_LATENCY_MSEC}",
        ).strip()
    except Exception:
        new_id = None
    if not new_id:
        return None, None
    return new_id, target_sink

def setup_private_sink(output_sink=None, sink_name=None):
    if not shutil.which("pactl"):
        return None, None, None, None
    if not sink_name:
        sink_name = f"acui-{os.getpid()}"
    null_module_id = None
    loopback_module_id = None
    default_sink = get_default_sink()
    target_sink = output_sink if output_sink else default_sink
    try:
        out = pactl("list", "short", "sinks")
        for line in out.splitlines():
            cols = line.split("\t")
            if len(cols) > 1 and cols[1] == sink_name:
                # already exists
                break
        else:
            null_module_id = pactl(
                "load-module",
                "module-null-sink",
                f"sink_name={sink_name}",
                "sink_properties=device.description=AC_UI",
            ).strip()
    except Exception:
        return None, None, None, None

    # Clean up stale loopbacks for this sink so each run owns a single route.
    for module_id in list_loopback_modules(sink_name):
        try:
            pactl("unload-module", module_id)
        except Exception:
            pass

    if target_sink:
        try:
            loopback_module_id = pactl(
                "load-module",
                "module-loopback",
                f"source={sink_name}.monitor",
                f"sink={target_sink}",
                f"latency_msec={LOOPBACK_LATENCY_MSEC}",
            ).strip()
        except Exception:
            loopback_module_id = None

    return sink_name, null_module_id, loopback_module_id, target_sink

def teardown_private_sink(null_module_id, loopback_module_id):
    if loopback_module_id:
        try:
            pactl("unload-module", loopback_module_id)
        except Exception:
            pass
    if null_module_id:
        try:
            pactl("unload-module", null_module_id)
        except Exception:
            pass

def detect_cava_input():
    env_method = os.environ.get("AC_UI_CAVA_INPUT")
    env_source = os.environ.get("AC_UI_CAVA_SOURCE")
    if env_method or env_source:
        return env_method, env_source, "env"

    # Prefer PulseAudio compat when pactl is available (works with PipeWire too)
    method = "pulse" if shutil.which("pactl") else None
    source = None
    if method:
        try:
            out = subprocess.check_output(["pactl", "info"], text=True)
            for line in out.splitlines():
                if line.startswith("Default Sink:"):
                    sink = line.split(":", 1)[1].strip()
                    if sink:
                        source = f"{sink}.monitor"
                    break
        except Exception:
            pass
        if not source:
            source = "@DEFAULT_MONITOR@"
    return method, source, "auto"

def pulse_monitor_source_for_audio_device(audio_device):
    if not audio_device:
        return None
    device = str(audio_device).strip()
    if not device:
        return None
    lower = device.lower()
    if lower.startswith("pulse/"):
        sink = device.split("/", 1)[1].strip()
        if not sink:
            return None
        if sink in ("@default@", "@default_sink@", "@default_sink"):
            return "@DEFAULT_MONITOR@"
        if sink.endswith(".monitor"):
            return sink
        return f"{sink}.monitor"
    return None

def build_cava_input_candidates(base_method, base_source, detect_mode, audio_device=None, private_sink=None, output_sink=None):
    candidates = []
    seen = set()

    def add(method, source, label):
        method = (method or "").strip() or None
        source = (source or "").strip() or None
        if not method and not source:
            return
        key = (method, source)
        if key in seen:
            return
        seen.add(key)
        candidates.append({
            "method": method,
            "source": source,
            "label": label,
        })

    # Always try the currently selected route first.
    add(base_method, base_source, detect_mode or "configured")
    if detect_mode == "env":
        return candidates

    override_source = pulse_monitor_source_for_audio_device(audio_device)
    if override_source:
        add("pulse", override_source, "audio-device")
    if private_sink:
        add("pulse", f"{private_sink}.monitor", "private-sink")
    if output_sink:
        add("pulse", f"{output_sink}.monitor", "output-sink")

    default_sink = get_default_sink()
    if default_sink:
        add("pulse", f"{default_sink}.monitor", "default-sink")
    add("pulse", "@DEFAULT_MONITOR@", "default-monitor")
    return candidates

def mpv_start(track, ipc_path, audio_device=None, volume=None, loop_file=False):
    # Start mpv with IPC server so we can query time-pos/duration, and quit on demand.
    # --no-video avoids cover art display.
    cmd = [
        MPV,
        "--no-video",
        "--quiet",
        f"--input-ipc-server={ipc_path}",
    ]
    if loop_file:
        cmd.append("--loop-file=inf")
    if audio_device:
        cmd.append(f"--audio-device={audio_device}")
    if volume is not None:
        cmd.append(f"--volume={int(max(0, min(100, volume)))}")
    cmd.append(track)
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def mpv_command(ipc_path, command):
    # Send a command via unix socket (best-effort)
    import socket
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.2)
        s.connect(ipc_path)
        s.sendall((json.dumps({"command": command}) + "\n").encode("utf-8"))
        s.close()
        return True
    except Exception:
        return False

def mpv_query(ipc_path, prop):
    # Query via unix socket using python's socket module (reliable)
    import socket
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.2)
        s.connect(ipc_path)
        s.sendall((json.dumps({"command": ["get_property", prop]}) + "\n").encode("utf-8"))
        data = s.recv(4096).decode("utf-8", errors="ignore")
        s.close()
        # mpv can return multiple JSON lines; parse last valid line
        lines = [ln for ln in data.splitlines() if ln.strip().startswith("{")]
        for ln in reversed(lines):
            try:
                obj = json.loads(ln)
                if obj.get("error") == "success":
                    return obj.get("data")
            except Exception:
                pass
        return None
    except Exception:
        return None

def mpv_query_props(ipc_path, props):
    import socket
    if not props:
        return {}
    sock = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.2)
        sock.connect(ipc_path)
        pending = {}
        for request_id, prop in enumerate(props, 1):
            pending[request_id] = prop
            payload = {"command": ["get_property", prop], "request_id": request_id}
            sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        results = {}
        buffer = ""
        deadline = time.monotonic() + 0.25
        while pending and time.monotonic() < deadline:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="ignore")
            lines = buffer.split("\n")
            buffer = lines.pop()
            for line in lines:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                request_id = obj.get("request_id")
                prop = pending.pop(request_id, None)
                if prop is None:
                    continue
                results[prop] = obj.get("data") if obj.get("error") == "success" else None
        return results
    except Exception:
        return {}
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def get_mute_volume():
    return SOFT_MUTE_VOL if MUTE_MODE == "soft" else 0


def play_chime(audio_device=None):
    if not HOUR_CHIME_PATH:
        return
    if not os.path.exists(HOUR_CHIME_PATH):
        return
    cmd = [
        MPV,
        "--no-video",
        "--quiet",
        "--no-terminal",
    ]
    if audio_device:
        cmd.append(f"--audio-device={audio_device}")
    cmd.append(HOUR_CHIME_PATH)
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def start_hour_chime(audio_device=None):
    if TOWN_TUNE_CHIME_ENABLED:
        proc, tmp = spawn_town_tune(audio_device)
        if proc:
            return proc, "town tune", tmp
    if not HOUR_CHIME_PATH:
        return None, None, None
    if not os.path.exists(HOUR_CHIME_PATH):
        return None, None, None
    cmd = [
        MPV,
        "--no-video",
        "--quiet",
        "--no-terminal",
    ]
    if audio_device:
        cmd.append(f"--audio-device={audio_device}")
    cmd.append(HOUR_CHIME_PATH)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return proc, "hour chime", None
    except Exception:
        return None, None, None


# Differential render: only rewrite lines that changed (btop pattern)
_render_prev_lines: list = []


