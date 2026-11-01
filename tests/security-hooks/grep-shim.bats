#!/usr/bin/env bats
#
# The grep shim runs the real grep and skips *.sops.* files whatever options the caller passes.

# shellcheck disable=SC2030,SC2031
bats_require_minimum_version 1.5.0
load helpers

REPO_ROOT="${BATS_TEST_DIRNAME}/../.."
SHIM_DIR="${REPO_ROOT}/security-hooks/shim"

setup() {
  ORIG_PATH="${PATH}"
  REAL_GREP="$(real_grep_path)"
  TMP="$(mktemp -d)"
  mkdir -p "${TMP}/tree/sub" "${TMP}/plain/sub"
  for f in a.sops.yaml b.yaml sub/c.sops.json sub/c.txt; do
    printf 'needle\n--\n' >"${TMP}/tree/${f}"
  done
  printf 'two words\n' >"${TMP}/tree/words.txt"
  printf 'needle\n--\n' >"${TMP}/plain/one.txt"
  printf 'other\n' >"${TMP}/plain/two.txt"
  printf 'needle three\n' >"${TMP}/plain/sub/three.txt"
  export PATH="${SHIM_DIR}:${PATH}"
  hash -r
  cd "${TMP}/tree" || return 1
}

teardown() {
  cd /
  rm -rf "${TMP}"
}

sorted() {
  printf '%s\n' "$1" | LC_ALL=C sort
}

real_grep() {
  bash -c 'exec -a grep "$@"' _ "${REAL_GREP}" "$@"
}

@test "skips *.sops.* files in a recursive search" {
  run grep -rl needle .
  [ "${status}" -eq 0 ]
  [ "$(sorted "${output}")" = "$(printf './b.yaml\n./sub/c.txt')" ]
}

@test "skips a *.sops.* file named on the command line" {
  run grep -l needle a.sops.yaml
  [ "${status}" -eq 1 ]
  [ -z "${output}" ]
  run grep -l needle a.sops.yaml b.yaml sub/c.sops.json
  [ "${status}" -eq 0 ]
  [ "${output}" = "b.yaml" ]
}

@test "a later --include cannot bring them back" {
  run grep -rl --include='*.yaml' needle .
  [ "${output}" = "./b.yaml" ]
  run grep -rl --include='*' needle .
  [ "$(sorted "${output}")" = "$(printf './b.yaml\n./sub/c.txt')" ]
  run grep -l --include='*.yaml' needle a.sops.yaml b.yaml
  [ "${output}" = "b.yaml" ]
}

@test "still skips them when a -- ends the options" {
  run grep -rl --include='*.yaml' -- needle .
  [ "${output}" = "./b.yaml" ]
  run grep -l -- needle a.sops.yaml b.yaml
  [ "${output}" = "b.yaml" ]
}

@test "keeps the words after -- as operands" {
  run grep -rl --include='*.yaml' -- '--' .
  [ "${output}" = "./b.yaml" ]
}

@test "-e -- searches for -- and still skips them" {
  for shape in "-rl --include=*.yaml -e -- ." "-rl --include=*.yaml -e-- ." "-rl --include=*.yaml -rle -- ." \
    "-rl --include=*.yaml --regexp -- ." "-rl --include=*.yaml --regexp=-- ." "-rl --include=*.yaml --regex -- ."; do
    read -ra words <<<"${shape}"
    run grep "${words[@]}"
    if [ "${output}" != "./b.yaml" ]; then
      echo "grep ${shape}: ${output}" >&2
      return 1
    fi
  done
}

@test "behaves like the real grep when no *.sops.* file is involved" {
  cd "${TMP}/plain"
  for shape in "-rn needle ." "-rn -- needle ." "-rl -e -- ." "-rl -e-- ." "-rle -- ." "--regexp -- -r ." "--regexp=-- -r ." \
    "--regex -- -r ." "-e needle -e -- -r ." "-A 1 -- needle one.txt" "-A1 -- needle one.txt" "-m 1 -- needle one.txt" \
    "--max-count 1 -- needle one.txt" "--max=1 -- needle one.txt" "-f one.txt -- two.txt" "--file -- one.txt" \
    "-r --include=*.txt -- needle ." "-r --include=-- needle ." "--colo=always -- needle one.txt" "-- needle one.txt two.txt" \
    "needle one.txt -n" "-- -- one.txt" "-c needle -r ." "-hc needle one.txt two.txt" "-e needle -e -- --" "-C 1 -- needle one.txt" \
    "--label -- -H needle one.txt" "-rl -f one.txt ." "-X grep -- needle one.txt" "-D read -- needle one.txt" \
    "--files-with=x needle one.txt" "-e"; do
    for mode in gnu posix; do
      if [ "${mode}" = posix ]; then export POSIXLY_CORRECT=1; else unset POSIXLY_CORRECT; fi
      read -ra words <<<"${shape}"
      run grep "${words[@]}"
      shim_status="${status}"
      shim_output="$(sorted "${output}")"
      run real_grep "${words[@]}"
      if [ "${shim_status}" != "${status}" ] || [ "${shim_output}" != "$(sorted "${output}")" ]; then
        echo "${mode}: grep ${shape}: shim ${shim_status} '${shim_output}', real ${status} '${output}'" >&2
        return 1
      fi
    done
  done
}

@test "skips them with POSIXLY_CORRECT set" {
  export POSIXLY_CORRECT=1
  run grep -rl needle .
  [ "$(sorted "${output}")" = "$(printf './b.yaml\n./sub/c.txt')" ]
  run grep -rl --include='*.yaml' needle .
  [ "${output}" = "./b.yaml" ]
  run grep -rl --include='*.yaml' -e -- .
  [ "${output}" = "./b.yaml" ]
  run grep -l needle a.sops.yaml b.yaml
  [ "${output}" = "b.yaml" ]
  run grep -l -- needle a.sops.yaml b.yaml
  [ "${output}" = "b.yaml" ]
}

@test "with POSIXLY_CORRECT an option after the first operand stays an operand" {
  export POSIXLY_CORRECT=1
  run grep needle b.yaml -n
  [ "${status}" -eq 2 ]
  [[ "${output}" == *"-n: No such file"* ]]
  [[ "${output}" == *"b.yaml:needle"* ]]
}

@test "stops with a clear error when it cannot tell where the options end" {
  run --separate-stderr grep --frobnicate -- needle .
  [ "${status}" -eq 2 ]
  [ -z "${output}" ]
  [[ "${stderr}" == "grep: cannot tell where the options end"*"--frobnicate"* ]]
  export POSIXLY_CORRECT=1
  run --separate-stderr grep -Q needle .
  [ "${status}" -eq 2 ]
  [ -z "${output}" ]
  [[ "${stderr}" == "grep: cannot tell where the options end"*"-Q"* ]]
}

@test "leaves an unknown option to the real grep when nothing hangs on the options end" {
  run --separate-stderr grep --frobnicate needle b.yaml
  [ "${status}" -eq 2 ]
  [[ "${stderr}" == *"unrecognized option"* ]]
}

@test "an option without its argument gets the real grep's usage error and nothing is searched" {
  run --separate-stderr grep -r -e </dev/null
  [ "${status}" -eq 2 ]
  [ -z "${output}" ]
  [[ "${stderr}" == *"requires an argument"* ]]
}

@test "passes arguments through exactly" {
  run grep -l 'two words' words.txt
  [ "${output}" = "words.txt" ]
  run grep -c '' b.yaml
  [ "${output}" = "2" ]
  printf 'a b\n' >'spa ce.txt'
  run grep -l 'a b' 'spa ce.txt'
  [ "${output}" = "spa ce.txt" ]
}

@test "keeps the exit status, stdout and stdin behaviour of grep" {
  run grep -c needle b.yaml
  [ "${status}" -eq 0 ]
  [ "${output}" = "1" ]
  run grep nomatch b.yaml
  [ "${status}" -eq 1 ]
  run --separate-stderr grep needle missing.txt
  [ "${status}" -eq 2 ]
  [[ "${stderr}" == "grep: missing.txt: No such file or directory" ]]
  run bash -c "printf 'needle\n' | grep -c needle"
  [ "${output}" = "1" ]
}

@test "an exported errexit changes neither the status nor the message of grep" {
  for shape in "--frobnicate needle b.yaml" "-r -e" "-c needle b.yaml" "nomatch b.yaml"; do
    read -ra words <<<"${shape}"
    run --separate-stderr env SHELLOPTS=errexit grep "${words[@]}" </dev/null
    shim_status="${status}"
    shim_output="$(sorted "${output}")"
    shim_stderr="${stderr}"
    run --separate-stderr real_grep "${words[@]}" </dev/null
    if [ "${shim_status}" != "${status}" ] || [ "${shim_output}" != "$(sorted "${output}")" ] || [ "${shim_stderr}" != "${stderr}" ]; then
      echo "grep ${shape}: shim ${shim_status} '${shim_output}' '${shim_stderr}', real ${status} '${output}' '${stderr}'" >&2
      return 1
    fi
  done
}

@test "an exported xtrace prints nothing extra" {
  run --separate-stderr env SHELLOPTS=xtrace grep -c needle b.yaml
  [ "${status}" -eq 0 ]
  [ "${output}" = "1" ]
  [ -z "${stderr}" ]
}

@test "a BASH_ENV file is not sourced" {
  printf 'touch "%s/sourced"\n' "${TMP}" >"${TMP}/bash_env.sh"
  run env BASH_ENV="${TMP}/bash_env.sh" grep -c needle b.yaml
  [ "${status}" -eq 0 ]
  [ "${output}" = "1" ]
  [ ! -e "${TMP}/sourced" ]
}

@test "does not loop when its directory is on PATH twice or through a link" {
  PATH="${SHIM_DIR}:${SHIM_DIR}:${ORIG_PATH}:${SHIM_DIR}"
  run timeout 10 grep -rl needle .
  [ "${status}" -eq 0 ]
  [ "$(sorted "${output}")" = "$(printf './b.yaml\n./sub/c.txt')" ]
  mkdir "${TMP}/link"
  ln -s "${SHIM_DIR}/grep" "${TMP}/link/grep"
  PATH="${TMP}/link:${SHIM_DIR}:${ORIG_PATH}"
  hash -r
  run timeout 10 grep -rl needle .
  [ "${status}" -eq 0 ]
  [ "$(sorted "${output}")" = "$(printf './b.yaml\n./sub/c.txt')" ]
}

@test "does not loop between different copies of itself on PATH" {
  mkdir "${TMP}/copy" "${TMP}/older"
  cp "${SHIM_DIR}/grep" "${TMP}/copy/grep"
  {
    sed -n 1,2p "${SHIM_DIR}/grep"
    printf 'exit 99\n'
  } >"${TMP}/older/grep"
  chmod +x "${TMP}/older/grep"
  PATH="${TMP}/copy:${SHIM_DIR}:${TMP}/older:${ORIG_PATH}"
  hash -r
  run timeout 10 grep -rl needle .
  [ "${status}" -eq 0 ]
  [ "$(sorted "${output}")" = "$(printf './b.yaml\n./sub/c.txt')" ]
}

@test "stops with a clear error when no other grep is on PATH" {
  mkdir "${TMP}/onlybash"
  ln -s "$(command -v bash)" "${TMP}/onlybash/bash"
  run -127 --separate-stderr timeout 10 env PATH="${SHIM_DIR}:${TMP}/onlybash" grep needle b.yaml
  [ "${status}" -eq 127 ]
  [[ "${stderr}" == "grep: "* ]]
}

@test "SECURITY_HOOKS_GREP_SHIM=0 turns it off and any other value leaves it on" {
  SECURITY_HOOKS_GREP_SHIM=0 run grep -rl needle .
  [ "$(sorted "${output}")" = "$(printf './a.sops.yaml\n./b.yaml\n./sub/c.sops.json\n./sub/c.txt')" ]
  SECURITY_HOOKS_GREP_SHIM=0 run grep -l needle a.sops.yaml
  [ "${output}" = "a.sops.yaml" ]
  SECURITY_HOOKS_GREP_SHIM=1 run grep -rl needle .
  [ "$(sorted "${output}")" = "$(printf './b.yaml\n./sub/c.txt')" ]
  SECURITY_HOOKS_GREP_SHIM='' run grep -rl needle .
  [ "$(sorted "${output}")" = "$(printf './b.yaml\n./sub/c.txt')" ]
}

@test "its option table matches the real grep" {
  # shellcheck source=/dev/null
  source "${SHIM_DIR}/grep"
  for c in {a..z} {A..Z} {0..9} '?'; do
    msg="$(real_grep "-${c}" </dev/null 2>&1 || true)"
    case "${msg}" in
    *"invalid option"*) want=unknown ;;
    *"requires an argument"*) want=1 ;;
    *) want=0 ;;
    esac
    ARITY=unknown
    short_arity "${c}" || true
    if [ "${ARITY}" != "${want}" ]; then
      echo "-${c}: shim says ${ARITY}, grep says ${want}" >&2
      return 1
    fi
  done
  for name in $(real_grep --help | grep -oE -- '--[a-z][a-z-]*' | sort -u | cut -c3-) colour silent fixed-regexp unix-byte-offsets exclude-from dereference-recursive; do
    msg="$(real_grep "--${name}" </dev/null 2>&1 || true)"
    case "${msg}" in
    *"requires an argument"*) want=1 ;;
    *) want=0 ;;
    esac
    ARITY=unknown
    long_arity "${name}" || true
    if [ "${ARITY}" != "${want}" ]; then
      echo "--${name}: shim says ${ARITY}, grep says ${want}" >&2
      return 1
    fi
  done
}
