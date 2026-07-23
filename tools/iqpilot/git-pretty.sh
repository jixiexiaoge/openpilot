# IQ.Pilot pretty git wrappers (gpull/gfetch/gsync/greset/gbv). bash + zsh.
# Source from your shell rc: source .../tools/iqpilot/git-pretty.sh
if [ -n "${BASH_SOURCE:-}" ]; then
  _iq_gp_src="${BASH_SOURCE[0]}"
elif [ -n "${ZSH_VERSION:-}" ]; then
  _iq_gp_src="${(%):-%x}"
else
  _iq_gp_src="$0"
fi
_IQ_GIT_PRETTY="$(cd "$(dirname "$_iq_gp_src")" 2>/dev/null && pwd)/git_pretty.py"
unset _iq_gp_src

if [ -z "${_IQ_GP_PY:-}" ]; then
  if command -v python3 >/dev/null 2>&1; then _IQ_GP_PY=python3
  elif [ -x /usr/bin/python3 ]; then _IQ_GP_PY=/usr/bin/python3
  else _IQ_GP_PY=python; fi
fi

_iq_git_pretty() {
  command git "$@" 2>&1 | "$_IQ_GP_PY" "$_IQ_GIT_PRETTY"
  if [ -n "${ZSH_VERSION:-}" ]; then
    return ${pipestatus[1]}
  else
    return ${PIPESTATUS[0]}
  fi
}

gpull()  { _iq_git_pretty -c color.ui=always pull --progress "$@"; }
gfetch() { _iq_git_pretty -c color.ui=always fetch --progress "$@"; }
gsync()  { _iq_git_pretty -c color.ui=always submodule update --init --recursive --progress "$@"; }
greset() { _iq_git_pretty -c color.ui=always reset "$@"; }
gbv()    { _iq_git_pretty -c color.branch=always branch -v "$@"; }
