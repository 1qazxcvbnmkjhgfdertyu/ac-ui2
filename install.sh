#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
YES=0
SKIP_DEPS=0
WITH_OPTIONAL=0
FORCE_VENV=0

usage() {
  cat <<'EOF'
Usage: ./install.sh [--yes] [--skip-deps] [--with-optional] [--venv]

  --yes            run package-manager commands without prompting
  --skip-deps      do not install system packages
  --with-optional  include optional helpers such as figlet/fluidsynth
  --venv           force a per-user venv install even if pipx is available
EOF
}

version_ok() {
  "$1" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
}

pick_python() {
  local candidate
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && version_ok "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

prompt_yes() {
  local prompt="${1:-Continue?}"
  if (( YES )); then
    return 0
  fi
  read -r -p "$prompt [Y/n] " reply
  case "${reply:-y}" in
    n|N|no|NO) return 1 ;;
    *) return 0 ;;
  esac
}

while (($#)); do
  case "$1" in
    --yes) YES=1 ;;
    --skip-deps) SKIP_DEPS=1 ;;
    --with-optional) WITH_OPTIONAL=1 ;;
    --venv) FORCE_VENV=1 ;;
    -h|--help) usage; exit 0 ;;
    *)
      printf 'Unknown option: %s\n\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

PYTHON_BIN="$(pick_python || true)"
if [[ -z "${PYTHON_BIN}" ]]; then
  printf 'Python 3.11+ is required. Install a newer Python, then rerun ./install.sh\n' >&2
  exit 1
fi

printf 'Using %s (%s)\n' "$PYTHON_BIN" "$("$PYTHON_BIN" -V 2>&1)"

if (( ! SKIP_DEPS )); then
  DOCTOR_ARGS=(doctor --install-commands)
  if (( WITH_OPTIONAL )); then
    DOCTOR_ARGS+=(--with-optional)
  fi
  mapfile -t SYSTEM_CMDS < <(cd "$ROOT" && "$PYTHON_BIN" -m ac_ui "${DOCTOR_ARGS[@]}")
  if ((${#SYSTEM_CMDS[@]})); then
    printf '\nSuggested system dependency commands:\n'
    printf '  %s\n' "${SYSTEM_CMDS[@]}"
    if prompt_yes "Run these commands now?"; then
      local_cmd=""
      for local_cmd in "${SYSTEM_CMDS[@]}"; do
        bash -lc "$local_cmd"
      done
    fi
  fi
fi

INSTALLED_BIN=""
if command -v pipx >/dev/null 2>&1 && (( ! FORCE_VENV )); then
  printf '\nInstalling with pipx\n'
  pipx install --force "$ROOT"
  INSTALLED_BIN="$(command -v ac-ui || true)"
  if [[ -z "${INSTALLED_BIN}" && -x "$HOME/.local/bin/ac-ui" ]]; then
    INSTALLED_BIN="$HOME/.local/bin/ac-ui"
  fi
else
  INSTALL_HOME="${AC_UI_HOME:-$HOME/.local/share/ac-terminal-radio}"
  VENV_DIR="$INSTALL_HOME/venv"
  printf '\nInstalling into %s\n' "$VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools
  "$VENV_DIR/bin/pip" install --upgrade "$ROOT"
  mkdir -p "$HOME/.local/bin"
  ln -sf "$VENV_DIR/bin/ac-ui" "$HOME/.local/bin/ac-ui"
  INSTALLED_BIN="$VENV_DIR/bin/ac-ui"
fi

printf '\nInstall complete.\n'
if [[ -n "${INSTALLED_BIN}" && -x "${INSTALLED_BIN}" ]]; then
  printf 'Installed command: %s\n' "$INSTALLED_BIN"
  printf '\nRunning ac-ui doctor\n'
  "$INSTALLED_BIN" doctor || true
fi

case ":${PATH}:" in
  *":$HOME/.local/bin:"*) ;;
  *)
    printf '\nAdd %s to PATH if you want to run ac-ui directly:\n' "$HOME/.local/bin"
    printf '  export PATH="$HOME/.local/bin:$PATH"\n'
    ;;
esac
