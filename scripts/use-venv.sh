# Shared repo venv: prompt name "system-design-interview", directory ".venv".
# Source this file from question scripts after setting REPO_ROOT (and optionally QUESTION_DIR).

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "source this file from a question script; do not execute it" >&2
  exit 1
fi

if [[ -z "${REPO_ROOT:-}" ]]; then
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

SDI_VENV_NAME="system-design-interview"
SDI_VENV="${REPO_ROOT}/.venv"

if [[ ! -x "${SDI_VENV}/bin/python" ]]; then
  echo "Creating ${SDI_VENV_NAME} venv at ${SDI_VENV}"
  python3 -m venv --prompt "${SDI_VENV_NAME}" "${SDI_VENV}"
fi

# shellcheck source=/dev/null
source "${SDI_VENV}/bin/activate"

python -m pip install --upgrade pip >/dev/null
python -m pip install -r "${REPO_ROOT}/requirements.txt" >/dev/null
if [[ -n "${QUESTION_DIR:-}" && -f "${QUESTION_DIR}/requirements.txt" ]]; then
  python -m pip install -r "${QUESTION_DIR}/requirements.txt" >/dev/null
fi

echo "Using ${SDI_VENV_NAME} venv: $(command -v python) ($(python --version 2>&1))"
