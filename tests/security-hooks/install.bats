#!/usr/bin/env bats
#
# The SessionStart hook installs the grep shim, the secret glob list and the rg config built from it outside the plugin dir
# and writes the lines that make the Bash tool's shell use them.

# shellcheck disable=SC2016,SC2030,SC2031
bats_require_minimum_version 1.5.0
load helpers

REPO_ROOT="${BATS_TEST_DIRNAME}/../.."
PLUGIN="${REPO_ROOT}/security-hooks"
HOOKS="${PLUGIN}/hooks/hooks.json"

setup() {
  ORIG_PATH="${PATH}"
  REAL_GREP="$(real_grep_path)"
  TMP="$(mktemp -d)"
  cp -R "${PLUGIN}" "${TMP}/plugin"
  export CLAUDE_PLUGIN_ROOT="${TMP}/plugin"
  export CLAUDE_PLUGIN_DATA="${TMP}/data"
  export CLAUDE_ENV_FILE="${TMP}/env.sh"
  unset SECURITY_HOOKS_GREP_SHIM RIPGREP_CONFIG_PATH POSIXLY_CORRECT
  mkdir -p "${TMP}/tree/sub"
  printf 'needle\n' >"${TMP}/tree/a.sops.yaml"
  printf 'needle\n' >"${TMP}/tree/b.yaml"
  printf 'needle\n' >"${TMP}/tree/sub/c.sops.json"
  make_secret_tree "${TMP}/secrets"
  printf 'grep() { echo "claude grep function"; }\n' >"${TMP}/function.sh"
  printf 'unset -f grep find 2>/dev/null || true\n' >"${TMP}/restore.sh"
}

teardown() {
  rm -rf "${TMP}"
}

install() {
  run --separate-stderr bash "${CLAUDE_PLUGIN_ROOT}/scripts/install-grep-shim.sh"
}

# Runs a command in a fresh bash after sourcing the env file(s), as the Bash tool's shell does.
in_shell() {
  local files="$1" cmd="$2" tree="${3:-${TMP}/tree}"
  run --separate-stderr env -i HOME="${TMP}" PATH="${ORIG_PATH}" ENV_FILES="${files}" TREE="${tree}" SHIMDIR="${CLAUDE_PLUGIN_DATA}/shim" \
    bash -c '
    for f in ${ENV_FILES}; do . "${f}"; done
    cd "${TREE}" && '"${cmd}"
}

@test "installs the shim, the glob list and the rg config under the data dir and exits quietly" {
  install
  [ "${status}" -eq 0 ]
  [ -z "${output}" ]
  [ -x "${CLAUDE_PLUGIN_DATA}/shim/grep" ]
  cmp "${PLUGIN}/shim/secret-globs" "${CLAUDE_PLUGIN_DATA}/shim/secret-globs"
  [ -f "${CLAUDE_PLUGIN_DATA}/shim/ripgreprc" ]
  [ -s "${CLAUDE_ENV_FILE}" ]
}

@test "installs the helper the shims source next to them, and replaces an older copy" {
  install
  cmp "${PLUGIN}/shim/shim-common.bash" "${CLAUDE_PLUGIN_DATA}/shim/shim-common.bash"
  printf '# newer\n' >>"${CLAUDE_PLUGIN_ROOT}/shim/shim-common.bash"
  install
  cmp "${CLAUDE_PLUGIN_ROOT}/shim/shim-common.bash" "${CLAUDE_PLUGIN_DATA}/shim/shim-common.bash"
}

@test "the env lines never mention the plugin root" {
  install
  [ "${status}" -eq 0 ]
  run grep -F "${CLAUDE_PLUGIN_ROOT}" "${CLAUDE_ENV_FILE}"
  [ "${status}" -eq 1 ]
}

@test "after sourcing the env lines grep skips *.sops.* files" {
  install
  in_shell "${CLAUDE_ENV_FILE}" 'type -t grep; grep -rl needle .'
  [ "${status}" -eq 0 ]
  [ "${lines[0]}" = "file" ]
  [ "${lines[1]}" = "./b.yaml" ]
  [ "${#lines[@]}" -eq 2 ]
}

@test "after sourcing the env lines grep skips secret files and .git/" {
  install
  in_shell "${CLAUDE_ENV_FILE}" 'grep -rl needle . | sort' "${TMP}/secrets"
  [ "${status}" -eq 0 ]
  [ "${output}" = "$(kept_listing ./)" ]
}

@test "the env lines leave a grep function of the shell alone" {
  install
  in_shell "${TMP}/function.sh ${CLAUDE_ENV_FILE}" 'type -t grep; grep -rl needle .'
  [ "${status}" -eq 0 ]
  [ "${lines[0]}" = "function" ]
  [ "${lines[1]}" = "claude grep function" ]
  [ "${#lines[@]}" -eq 2 ]
}

@test "keeps working after the plugin root is gone" {
  install
  rm -rf "${CLAUDE_PLUGIN_ROOT}"
  in_shell "${CLAUDE_ENV_FILE}" 'grep -rl needle .'
  [ "${output}" = "./b.yaml" ]
  [ -z "${stderr}" ]
  in_shell "${CLAUDE_ENV_FILE}" 'grep -rl needle . | sort' "${TMP}/secrets"
  [ "${output}" = "$(kept_listing ./)" ]
}

@test "the env lines work before or after a file that unsets the grep function, and when sourced twice" {
  install
  for files in "${TMP}/function.sh ${CLAUDE_ENV_FILE} ${TMP}/restore.sh" "${TMP}/function.sh ${TMP}/restore.sh ${CLAUDE_ENV_FILE}" \
    "${TMP}/function.sh ${CLAUDE_ENV_FILE} ${TMP}/restore.sh ${CLAUDE_ENV_FILE}" \
    "${TMP}/function.sh ${TMP}/restore.sh ${CLAUDE_ENV_FILE} ${TMP}/restore.sh ${CLAUDE_ENV_FILE}"; do
    in_shell "${files}" 'type -t grep; command -v grep; grep -rl needle .'
    if [ "${lines[0]}" != "file" ] || [ "${lines[1]}" != "${CLAUDE_PLUGIN_DATA}/shim/grep" ] || [ "${lines[2]}" != "./b.yaml" ] || [ "${#lines[@]}" -ne 3 ]; then
      echo "sourcing: ${files}: ${output}" >&2
      return 1
    fi
  done
}

@test "puts the shim dir on PATH once, however often the lines are sourced" {
  install
  in_shell "${CLAUDE_ENV_FILE} ${CLAUDE_ENV_FILE} ${CLAUDE_ENV_FILE}" 'printf "%s\n" "$PATH" | tr ":" "\n" | grep -cFx "${SHIMDIR}"'
  [ "${output}" = "1" ]
  in_shell "${CLAUDE_ENV_FILE}" 'echo "${PATH%%:*}"'
  [ "${output}" = "${CLAUDE_PLUGIN_DATA}/shim" ]
}

@test "leaves PATH alone when the shim dir is already on it" {
  install
  run --separate-stderr env -i HOME="${TMP}" PATH="${ORIG_PATH}:${CLAUDE_PLUGIN_DATA}/shim" EF="${CLAUDE_ENV_FILE}" \
    bash -c '. "${EF}"; echo "${PATH}"'
  [ "${output}" = "${ORIG_PATH}:${CLAUDE_PLUGIN_DATA}/shim" ]
}

@test "sets RIPGREP_CONFIG_PATH to the installed config only when it is unset" {
  install
  in_shell "${CLAUDE_ENV_FILE}" 'echo "${RIPGREP_CONFIG_PATH-unset}"'
  [ "${output}" = "${CLAUDE_PLUGIN_DATA}/shim/ripgreprc" ]
  run --separate-stderr env -i HOME="${TMP}" PATH="${ORIG_PATH}" RIPGREP_CONFIG_PATH=/their/rc EF="${CLAUDE_ENV_FILE}" \
    bash -c '. "${EF}"; echo "${RIPGREP_CONFIG_PATH}"'
  [ "${output}" = "/their/rc" ]
  run --separate-stderr env -i HOME="${TMP}" PATH="${ORIG_PATH}" RIPGREP_CONFIG_PATH= EF="${CLAUDE_ENV_FILE}" \
    bash -c '. "${EF}"; echo "[${RIPGREP_CONFIG_PATH-unset}]"'
  [ "${output}" = "[]" ]
}

@test "does not point RIPGREP_CONFIG_PATH at a config that is gone" {
  install
  rm -rf "${CLAUDE_PLUGIN_DATA}"
  in_shell "${CLAUDE_ENV_FILE}" 'echo "${RIPGREP_CONFIG_PATH-unset}"'
  [ "${output}" = "unset" ]
}

@test "the rg config makes rg skip *.sops.* files when it walks a directory" {
  require_rg
  install
  run env RIPGREP_CONFIG_PATH="${CLAUDE_PLUGIN_DATA}/shim/ripgreprc" "${RG}" -l needle "${TMP}/tree"
  [ "${status}" -eq 0 ]
  [ "$(printf '%s\n' "${output}" | sort)" = "${TMP}/tree/b.yaml" ]
}

@test "the rg config makes rg skip secret files and .git/ even with --hidden" {
  require_rg
  install
  run "${RG}" --hidden --no-ignore -l needle "${TMP}/secrets"
  [ "$(printf '%s\n' "${output}" | wc -l)" -eq $((${#KEPT_FILES[@]} + ${#SKIPPED_FILES[@]})) ]
  run env RIPGREP_CONFIG_PATH="${CLAUDE_PLUGIN_DATA}/shim/ripgreprc" "${RG}" --hidden --no-ignore -l needle "${TMP}/secrets"
  [ "${status}" -eq 0 ]
  [ "$(printf '%s\n' "${output}" | LC_ALL=C sort)" = "$(kept_listing "${TMP}/secrets/")" ]
}

@test "rg skips a listed folder passed by name: relative, with ./, absolute, nested or a subfolder" {
  require_rg
  install
  cd "${TMP}/secrets"
  export RIPGREP_CONFIG_PATH="${CLAUDE_PLUGIN_DATA}/shim/ripgreprc"
  for dir in .kube .kube/ ./.kube .aws "${TMP}/secrets/.aws" clusterconfig sub/clusterconfig sub/clusterconfig/deep \
    .git ./.git sub/.git .git/refs .git/refs/heads "${TMP}/secrets/.git" "${TMP}/secrets/.git/refs"; do
    for hidden in "" --hidden; do
      run "${RG}" ${hidden:+"${hidden}"} -l needle "${dir}"
      if [ "${status}" -ne 1 ] || [ -n "${output}" ]; then
        echo "rg ${hidden} ${dir}: status ${status}, output '${output}'" >&2
        return 1
      fi
    done
  done
  run "${RG}" --hidden -l needle .github
  [ "${output}" = ".github/ci.yml" ]
}

@test "every entry in secret-globs is skipped by rg, as a file or as a directory, also when a directory is passed by name" {
  require_rg
  install
  mkdir "${TMP}/each"
  printf 'needle\n' >"${TMP}/each/kept.txt"
  dirs=()
  while IFS= read -r glob; do
    [[ -n "${glob}" ]] || continue
    if [[ "${glob}" == */ ]]; then
      path="${glob%/}"
      path="${path//\*/x}"
      dirs+=("${TMP}/each/${path}")
      path="${path}/inner.txt"
    else
      path="${glob//\*/x}"
    fi
    mkdir -p "$(dirname -- "${TMP}/each/${path}")"
    printf 'needle\n' >"${TMP}/each/${path}"
  done <"${PLUGIN}/shim/secret-globs"
  run "${RG}" --hidden --no-ignore -l needle "${TMP}/each"
  [ "$(printf '%s\n' "${output}" | wc -l)" -gt 10 ]
  export RIPGREP_CONFIG_PATH="${CLAUDE_PLUGIN_DATA}/shim/ripgreprc"
  run "${RG}" --hidden --no-ignore -l needle "${TMP}/each"
  [ "${output}" = "${TMP}/each/kept.txt" ]
  [ "${#dirs[@]}" -gt 3 ]
  for dir in "${dirs[@]}"; do
    run "${RG}" --hidden --no-ignore -l needle "${dir}"
    if [ "${status}" -ne 1 ] || [ -n "${output}" ]; then
      echo "rg ${dir}: status ${status}, output '${output}'" >&2
      return 1
    fi
  done
}

@test "the rg config has a --glob=! line for each entry of the glob list, and a second one for each folder" {
  install
  rc="${CLAUDE_PLUGIN_DATA}/shim/ripgreprc"
  list="${PLUGIN}/shim/secret-globs"
  [ "$(wc -l <"${rc}")" -eq $(($(grep -c . "${list}") + $(grep -c '/$' "${list}"))) ]
  while IFS= read -r glob; do
    grep -qxF -- "--glob=!${glob}" "${rc}"
    if [[ "${glob}" == */ ]]; then
      grep -qxF -- "--glob=!**/${glob}**" "${rc}"
    fi
  done <"${list}"
}

@test "leaves the shim it had in place when the glob list or the rg config cannot be installed" {
  install
  cp "${CLAUDE_PLUGIN_DATA}/shim/grep" "${TMP}/grep.before"
  printf '# newer\n' >>"${CLAUDE_PLUGIN_ROOT}/shim/grep"
  printf 'extra-name\n' >>"${CLAUDE_PLUGIN_ROOT}/shim/secret-globs"
  real_cp="$(command -v cp)"
  mkdir "${TMP}/failcp" "${TMP}/rgtmp"
  printf '#!/bin/sh\ncase $1 in */secret-globs|%s/*) exit 1 ;; *) ;; esac\nexec %s "$@"\n' "${TMP}/rgtmp" "${real_cp}" >"${TMP}/failcp/cp"
  chmod +x "${TMP}/failcp/cp"
  PATH="${TMP}/failcp:${ORIG_PATH}"
  TMPDIR="${TMP}/rgtmp" install
  [ "${status}" -eq 0 ]
  cmp "${TMP}/grep.before" "${CLAUDE_PLUGIN_DATA}/shim/grep"
  printf '#!/bin/sh\ncase $1 in %s/*) exit 1 ;; *) ;; esac\nexec %s "$@"\n' "${TMP}/rgtmp" "${real_cp}" >"${TMP}/failcp/cp"
  TMPDIR="${TMP}/rgtmp" install
  [ "${status}" -eq 0 ]
  cmp "${TMP}/grep.before" "${CLAUDE_PLUGIN_DATA}/shim/grep"
  [ "$(tail -n1 "${CLAUDE_PLUGIN_DATA}/shim/secret-globs")" = "extra-name" ]
}

@test "leaves the shim it had in place when the helper cannot be installed" {
  install
  cp "${CLAUDE_PLUGIN_DATA}/shim/grep" "${TMP}/grep.before"
  printf '# newer\n' >>"${CLAUDE_PLUGIN_ROOT}/shim/grep"
  printf '# newer\n' >>"${CLAUDE_PLUGIN_ROOT}/shim/shim-common.bash"
  real_cp="$(command -v cp)"
  mkdir "${TMP}/failcp"
  printf '#!/bin/sh\ncase $1 in */shim-common.bash) exit 1 ;; *) ;; esac\nexec %s "$@"\n' "${real_cp}" >"${TMP}/failcp/cp"
  chmod +x "${TMP}/failcp/cp"
  PATH="${TMP}/failcp:${ORIG_PATH}"
  install
  [ "${status}" -eq 0 ]
  cmp "${TMP}/grep.before" "${CLAUDE_PLUGIN_DATA}/shim/grep"
}

@test "a changed glob list reaches the installed list and the rg config" {
  install
  printf 'extra-name\n' >>"${CLAUDE_PLUGIN_ROOT}/shim/secret-globs"
  install
  [ "${status}" -eq 0 ]
  cmp "${CLAUDE_PLUGIN_ROOT}/shim/secret-globs" "${CLAUDE_PLUGIN_DATA}/shim/secret-globs"
  [ "$(tail -n1 "${CLAUDE_PLUGIN_DATA}/shim/ripgreprc")" = "--glob=!extra-name" ]
}

@test "running it again leaves the env file byte for byte the same" {
  install
  cp "${CLAUDE_ENV_FILE}" "${TMP}/first.sh"
  install
  [ "${status}" -eq 0 ]
  cmp "${CLAUDE_ENV_FILE}" "${TMP}/first.sh"
}

@test "appends to an env file that already has content, with or without a trailing newline" {
  printf 'export OTHER=1\n' >"${CLAUDE_ENV_FILE}"
  install
  [ "$(head -n1 "${CLAUDE_ENV_FILE}")" = "export OTHER=1" ]
  in_shell "${CLAUDE_ENV_FILE}" 'grep -rl needle .'
  [ "${output}" = "./b.yaml" ]
  rm "${CLAUDE_ENV_FILE}"
  printf 'export OTHER=1' >"${CLAUDE_ENV_FILE}"
  install
  [ "$(head -n1 "${CLAUDE_ENV_FILE}")" = "export OTHER=1" ]
  in_shell "${CLAUDE_ENV_FILE}" 'grep -rl needle .'
  [ "${output}" = "./b.yaml" ]
}

@test "replaces an older copy of the shim with the new one" {
  install
  printf '# newer\n' >>"${CLAUDE_PLUGIN_ROOT}/shim/grep"
  install
  [ "$(tail -n1 "${CLAUDE_PLUGIN_DATA}/shim/grep")" = "# newer" ]
  [ -x "${CLAUDE_PLUGIN_DATA}/shim/grep" ]
  [ "$(find "${CLAUDE_PLUGIN_DATA}/shim" -type f | wc -l)" -eq 4 ]
}

@test "a data dir with a space and a quote in its name works" {
  export CLAUDE_PLUGIN_DATA="${TMP}/da ta's \$HOME"
  install
  [ "${status}" -eq 0 ]
  in_shell "${CLAUDE_ENV_FILE} ${CLAUDE_ENV_FILE}" 'command -v grep; grep -rl needle .; echo "${RIPGREP_CONFIG_PATH}"'
  [ "${lines[0]}" = "${CLAUDE_PLUGIN_DATA}/shim/grep" ]
  [ "${lines[1]}" = "./b.yaml" ]
  [ "${lines[2]}" = "${CLAUDE_PLUGIN_DATA}/shim/ripgreprc" ]
}

@test "installs nothing when there is no GNU grep" {
  mkdir "${TMP}/bsd"
  printf '#!/bin/sh\nif [ "$1" = --version ]; then echo "grep (BSD grep, GNU compatible) 2.6.0-FreeBSD"; exit 0; fi\nexec %s "$@"\n' "${REAL_GREP}" >"${TMP}/bsd/grep"
  chmod +x "${TMP}/bsd/grep"
  PATH="${TMP}/bsd:${ORIG_PATH}"
  install
  [ "${status}" -eq 0 ]
  [ -z "${output}" ]
  [ ! -e "${CLAUDE_ENV_FILE}" ]
}

@test "installs nothing when grep does not honour --exclude" {
  mkdir "${TMP}/odd"
  printf '#!/bin/sh\nfor a; do shift; case $a in --exclude=*) ;; *) set -- "$@" "$a" ;; esac; done\nexec %s "$@"\n' "${REAL_GREP}" >"${TMP}/odd/grep"
  chmod +x "${TMP}/odd/grep"
  PATH="${TMP}/odd:${ORIG_PATH}"
  install
  [ "${status}" -eq 0 ]
  [ ! -e "${CLAUDE_ENV_FILE}" ]
}

@test "installs nothing when grep honours --exclude only in a recursive search" {
  mkdir "${TMP}/odd"
  printf '#!/bin/sh\nrec=0; for a; do case $a in -r*) rec=1 ;; esac; done\nif [ $rec = 0 ]; then for a; do shift; case $a in --exclude=*) ;; *) set -- "$@" "$a" ;; esac; done; fi\nexec %s "$@"\n' "${REAL_GREP}" >"${TMP}/odd/grep"
  chmod +x "${TMP}/odd/grep"
  PATH="${TMP}/odd:${ORIG_PATH}"
  install
  [ "${status}" -eq 0 ]
  [ ! -e "${CLAUDE_ENV_FILE}" ]
}

@test "SECURITY_HOOKS_GREP_SHIM=0 installs nothing" {
  export SECURITY_HOOKS_GREP_SHIM=0
  install
  [ "${status}" -eq 0 ]
  [ ! -e "${CLAUDE_ENV_FILE}" ]
  [ ! -e "${CLAUDE_PLUGIN_DATA}" ]
}

@test "SECURITY_HOOKS_GREP_SHIM=0 set after the install leaves rg and grep alone" {
  install
  run --separate-stderr env -i HOME="${TMP}" PATH="${ORIG_PATH}" SECURITY_HOOKS_GREP_SHIM=0 EF="${CLAUDE_ENV_FILE}" TREE="${TMP}/tree" \
    bash -c '. "${EF}"; echo "${RIPGREP_CONFIG_PATH-unset}"; cd "${TREE}" && grep -rl needle . | sort'
  [ "${status}" -eq 0 ]
  [ "${output}" = "$(printf 'unset\n./a.sops.yaml\n./b.yaml\n./sub/c.sops.json')" ]
}

@test "does nothing without an env file or a data dir" {
  unset CLAUDE_ENV_FILE
  install
  [ "${status}" -eq 0 ]
  [ ! -e "${CLAUDE_PLUGIN_DATA}" ]
  export CLAUDE_ENV_FILE="${TMP}/env.sh"
  unset CLAUDE_PLUGIN_DATA
  install
  [ "${status}" -eq 0 ]
  [ ! -e "${CLAUDE_ENV_FILE}" ]
}

@test "hooks.json runs the installer on every SessionStart source, compact included" {
  [ "$(jq -r '.hooks | keys | join(" ")' "${HOOKS}")" = "SessionStart" ]
  [ "$(jq -r '.hooks.SessionStart | length' "${HOOKS}")" -eq 1 ]
  [ "$(jq -r '.hooks.SessionStart[0].hooks[0].command' "${HOOKS}")" = 'bash "${CLAUDE_PLUGIN_ROOT}/scripts/install-grep-shim.sh"' ]
  [ "$(jq -r '.hooks.SessionStart[0].hooks[0].timeout' "${HOOKS}")" -gt 0 ]
  matcher="$(jq -r '.hooks.SessionStart[0].matcher // ""' "${HOOKS}")"
  for source_ in startup resume clear compact fork; do
    if [ -n "${matcher}" ] && [ "${matcher}" != "*" ]; then
      [[ "${source_}" =~ ^(${matcher})$ ]]
    fi
  done
}

@test "the installed shim runs on its own and skips *.sops.* files" {
  install
  run "${CLAUDE_PLUGIN_DATA}/shim/grep" -rl needle "${TMP}/tree"
  [ "${status}" -eq 0 ]
  [ "${output}" = "${TMP}/tree/b.yaml" ]
}

@test "the installed shim runs on its own and skips secret files and .git/" {
  install
  run "${CLAUDE_PLUGIN_DATA}/shim/grep" -rl needle "${TMP}/secrets"
  [ "${status}" -eq 0 ]
  [ "$(printf '%s\n' "${output}" | LC_ALL=C sort)" = "$(kept_listing "${TMP}/secrets/")" ]
}

@test "installs nothing when grep does not honour --exclude-dir" {
  mkdir "${TMP}/odd"
  printf '#!/bin/sh\nfor a; do shift; case $a in --exclude-dir=*) ;; *) set -- "$@" "$a" ;; esac; done\nexec %s "$@"\n' "${REAL_GREP}" >"${TMP}/odd/grep"
  chmod +x "${TMP}/odd/grep"
  PATH="${TMP}/odd:${ORIG_PATH}"
  install
  [ "${status}" -eq 0 ]
  [ ! -e "${CLAUDE_ENV_FILE}" ]
}

@test "installs nothing when grep does not skip a file named inside a listed folder" {
  mkdir "${TMP}/odd"
  printf '#!/bin/sh\nfor a; do shift; case $a in --exclude=.git/*) ;; *) set -- "$@" "$a" ;; esac; done\nexec %s "$@"\n' "${REAL_GREP}" >"${TMP}/odd/grep"
  chmod +x "${TMP}/odd/grep"
  PATH="${TMP}/odd:${ORIG_PATH}"
  install
  [ "${status}" -eq 0 ]
  [ ! -e "${CLAUDE_ENV_FILE}" ]
}

@test "installs nothing when the helper is missing" {
  rm "${CLAUDE_PLUGIN_ROOT}/shim/shim-common.bash"
  install
  [ "${status}" -eq 0 ]
  [ ! -e "${CLAUDE_ENV_FILE}" ]
  [ ! -e "${CLAUDE_PLUGIN_DATA}" ]
}

@test "installs nothing when the glob list is missing" {
  rm "${CLAUDE_PLUGIN_ROOT}/shim/secret-globs"
  install
  [ "${status}" -eq 0 ]
  [ ! -e "${CLAUDE_ENV_FILE}" ]
  [ ! -e "${CLAUDE_PLUGIN_DATA}" ]
}
