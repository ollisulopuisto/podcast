# autoraffkat Automation & API Specification (v1)

This document specifies the automation interfaces for `autoraffkat`:
1. The versioned HTTP REST API (`/api/v1/...`).
2. The headless command-line interface (`autoraffkat inspect`, `autoraffkat edit`).
3. Standardized structured output protocols, validation rules, and platform constraints.

---

## 1. Design & Platform Boundaries

- **Cross-Platform Headless Execution:** Loading FCPXML timelines, envelope analysis, speaker grid construction, decision cuts (`decide`), and XML export run on any supported Python platform (macOS, Linux, Windows) with `ffmpeg`.
- **macOS / Final Cut Pro Constraints:**
  - Launching Final Cut Pro (`open -a "Final Cut Pro"`) requires macOS and an installed Final Cut Pro application.
  - Native file picker dialogs require macOS or graphical environments. Headless commands must take explicit paths and never open pickers or browsers.
  - Hardware-accelerated GPU export rendering (`render_av.py` via AVFoundation) requires macOS Apple Silicon / Metal; non-macOS platforms fall back to `ffmpeg` rendering.

---

## 2. Headless CLI Automation

Headless commands do not launch web servers, browsers, or GUI windows, and output exit code `0` on success and non-zero (`1` or `2`) on failure.

### 2.1 `autoraffkat inspect`
Inspects a project timeline, track metadata, and loaded or default settings without running full analysis or launching a server.

```bash
autoraffkat inspect <project.fcpxml | project.fcpxmld> [--json]
```

- **Arguments:**
  - `xml`: Path to an `.fcpxml` file or `.fcpxmld` bundle directory.
  - `--json`: Output full project details as formatted JSON to stdout. Without `--json`, prints a readable summary table of tracks, media, frame rates, and durations.

### 2.2 `autoraffkat edit`
Runs a non-interactive editing, decision, and export workflow.

```bash
autoraffkat edit <project.fcpxml | project.fcpxmld> [options]
```

- **Options:**
  - `--settings <file.json>`: Path to a custom settings JSON file (matching `ProjectSettings` schema).
  - `--set <key=value>`: Inline setting override (e.g. `--set globals.rhythm=hectic` or `--set globals.min_shot=3.0`).
  - `--export`: Write the exported cut FCPXML to disk.
  - `--output <path>`: Explicit destination path for exported FCPXML (default: auto-incremented `-cut.fcpxml` next to source).
  - `--render`: Also render full video MP4 beside the exported XML.
  - `--progress`: Emit standard progress lines `PROGRESS <0-100> <message>` on stdout.
  - `--json`: Emit the final result (cuts, paths, warnings, statistics) as JSON on stdout.

---

## 3. Versioned HTTP API (`/api/v1/`)

The v1 REST API uses explicit request and response schemas. All responses return JSON with HTTP status codes indicating outcome.

### 3.1 Error Envelope Schema
When an error occurs (`4xx` or `5xx`), the response body follows this schema:

```json
{
  "error": {
    "code": "PROJECT_NOT_LOADED",
    "message": "Project timeline has not been loaded.",
    "details": {}
  }
}
```

Standard error codes:
- `BAD_REQUEST`: Invalid payload, unparseable parameters, or schema validation failure.
- `PROJECT_NOT_LOADED`: Endpoint requires an active loaded project.
- `ANALYSIS_NOT_READY`: Audio envelopes or speaker analysis have not completed.
- `FILE_NOT_FOUND`: Target source or export file does not exist.
- `EXPORT_ERROR`: Timeline generation or XML writing failed.
- `PLATFORM_UNSUPPORTED`: Requested feature requires macOS (e.g., launching Final Cut Pro).

---

### 3.2 Endpoints

#### `GET /api/v1/status`
Returns service status, host capabilities, and currently loaded project state.

**Response `200 OK`:**
```json
{
  "service": "autoraffkat",
  "version": "1.0",
  "platform": "darwin",
  "loaded": true,
  "xml_path": "/path/to/project.fcpxmld",
  "analysis_ready": true,
  "video_measured": false
}
```

#### `GET /api/v1/project/inspect`
Returns comprehensive timeline metadata, track roles, audio/video specs, and current settings.

**Response `200 OK`:**
```json
{
  "xml_path": "/path/to/project.fcpxmld",
  "name": "Interview",
  "kind": "multicam",
  "fps": 25.0,
  "tracks": [
    {
      "key": "A-cam Track1",
      "name": "Host Cam",
      "kind": "video",
      "has_video": true,
      "has_audio": false,
      "config": {
        "role": "shot",
        "covers": ["Host"],
        "context": false
      }
    }
  ],
  "settings": {
    "globals": {},
    "audio": {},
    "tracks": {}
  }
}
```

#### `POST /api/v1/project/settings`
Updates track configurations or global parameters. Computes and returns cut preview and status.

**Request Body:**
```json
{
  "tracks": {
    "A-cam Track1": {
      "role": "shot",
      "covers": ["Host"],
      "context": false
    }
  },
  "globals": {
    "rhythm": "broadcast",
    "min_shot": 2.5
  },
  "audio": {
    "enabled": true,
    "debleed": true
  }
}
```

**Response `200 OK`:**
```json
{
  "ok": true,
  "problems": [],
  "cuts_count": 42,
  "output_path": "/path/to/project-cut.fcpxml"
}
```

#### `POST /api/v1/project/cut`
Computes cut decisions on demand and returns the full cut list and timeline segments.

**Response `200 OK`:**
```json
{
  "ok": true,
  "segments": [
    {
      "start": 0.0,
      "end": 3.5,
      "duration": 3.5,
      "label": "Host",
      "angle": "A-cam Track1"
    }
  ],
  "counts": {
    "Host": 24,
    "Guest": 18
  },
  "problems": []
}
```

#### `POST /api/v1/project/export`
Exports cut timeline to FCPXML (and optional MP4 render).

**Request Body:**
```json
{
  "render": false,
  "settings": {}
}
```

**Response `200 OK`:**
```json
{
  "ok": true,
  "path": "/path/to/project-cut.fcpxml",
  "cuts": 42,
  "mixed": 2,
  "warnings": [],
  "render": null
}
```
