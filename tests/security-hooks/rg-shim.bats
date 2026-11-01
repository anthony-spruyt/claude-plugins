#!/usr/bin/env bats
#
# The rg shim runs the real rg and skips the secret files listed in shim/secret-globs, and .git/, whatever globs the caller passes.

# shellcheck disable=SC2030,SC2031
bats_require_minimum_version 1.5.0
load helpers

REPO_ROOT="${BATS_TEST_DIRNAME}/../.."
SHIM_DIR="${REPO_ROOT}/security-hooks/shim"

setup() {
  ORIG_PATH="${PATH}"
  unset RIPGREP_CONFIG_PATH SECURITY_HOOKS_GREP_SHIM
  require_rg
  TMP="$(mktemp -d)"
  mkdir -p "${TMP}/tree/sub" "${TMP}/plain/sub"
  for f in a.sops.yaml b.yaml sub/c.sops.json sub/c.txt; do
    printf 'needle\n--\n' >"${TMP}/tree/${f}"
  done
  printf 'two words\n' >"${TMP}/tree/words.txt"
  printf 'needle\n--\n' >"${TMP}/plain/one.txt"
  printf 'other\n' >"${TMP}/plain/two.txt"
  printf 'needle three\n' >"${TMP}/plain/sub/three.txt"
  make_secret_tree "${TMP}/secrets"
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

# make_cased_tree DIR: files that match a listed glob only when case is ignored, each holding needle and a line that looks like a flag
make_cased_tree() {
  local root="$1" glob path name kube=Kube host=Hosts server=Server env=Envi
  local names=("${kube}Config.java" "${env}ron" "${host}.yml" "${server}.KEY")
  while IFS= read -r glob; do
    [[ -n "${glob}" ]] || continue
    path="${glob//\*/x}"
    path="${path^^}"
    [[ "${glob}" != */ ]] || path="${path}inner.txt"
    names+=("${path}")
  done <"${SHIM_DIR}/secret-globs"
  for name in "${names[@]}"; do
    mkdir -p "$(dirname -- "${root}/${name}")"
    printf 'needle\n--iglob\n' >"${root}/${name}"
  done
}

# expect_rg WANT ARGS...: runs rg with ARGS and checks its sorted output
expect_rg() {
  local want="$1"
  shift
  run rg "$@"
  if [ "$(sorted "${output}")" != "${want}" ]; then
    echo "rg $*: '${output}', want '${want}'" >&2
    return 1
  fi
}

@test "skips *.sops.* files in a recursive search" {
  run rg -l needle .
  [ "${status}" -eq 0 ]
  [ "$(sorted "${output}")" = "$(printf './b.yaml\n./sub/c.txt')" ]
}

@test "skips secret files and .git/ in a recursive search, and keeps the lookalikes" {
  cd "${TMP}/secrets"
  run rg --hidden --no-ignore -l needle .
  [ "${status}" -eq 0 ]
  [ "$(sorted "${output}")" = "$(kept_listing ./)" ]
}

@test "the caller's -g, --glob and --iglob cannot bring them back" {
  both="$(printf './b.yaml\n./sub/c.txt')"
  expect_rg ./b.yaml -l -g '*.yaml' needle .
  expect_rg ./b.yaml -l -g'*.yaml' needle .
  expect_rg ./b.yaml -l -g '*.yaml' -g '*.json' needle .
  expect_rg ./b.yaml -l -ig '*.yaml' needle .
  expect_rg "${both}" -l --glob='*' needle .
  expect_rg "${both}" -l --glob '*' needle .
  expect_rg "${both}" -l -g '*' needle .
  expect_rg ./b.yaml -l --iglob='*.YAML' needle .
  expect_rg "${both}" -l --iglob '*' needle .
  expect_rg ./b.yaml -l -g '!*.txt' needle .
  expect_rg '' -l -g '*sops*' needle .
  [ "${status}" -eq 1 ]
}

@test "the caller's globs cannot bring secret files and .git/ back" {
  cd "${TMP}/secrets"
  expect_rg "$(kept_listing ./)" --hidden --no-ignore -l -g '*' needle .
  expect_rg "$(kept_listing ./)" --hidden --no-ignore -l --iglob '*' needle .
  expect_rg ./secretary.yaml --hidden --no-ignore -l -g '*.yaml' needle .
  expect_rg ./secretary.yaml --hidden --no-ignore -l --iglob '*.YAML' needle .
  expect_rg "$(kept_listing ./)" -l -g '*' --hidden --no-ignore needle .
}

@test "a search without --iglob keeps files whose names match a listed glob only in another case" {
  make_cased_tree "${TMP}/cased"
  all="$(find "${TMP}/cased" -type f | LC_ALL=C sort)"
  [ "$(printf '%s\n' "${all}" | wc -l)" -gt 30 ]
  expect_rg "${all}" --hidden --no-ignore -l needle "${TMP}/cased"
  expect_rg "${all}" --hidden --no-ignore -l -g '*' needle "${TMP}/cased"
  expect_rg "${all}" --hidden --no-ignore -l --glob='*' needle "${TMP}/cased"
}

@test "a --iglob that is a flag's value or follows a -- does not make the skips ignore case" {
  make_cased_tree "${TMP}/cased"
  all="$(find "${TMP}/cased" -type f | LC_ALL=C sort)"
  expect_rg "${all}" --hidden --no-ignore -l -e --iglob "${TMP}/cased"
  expect_rg "${all}" --hidden --no-ignore -l --regexp --iglob "${TMP}/cased"
  expect_rg "${all}" --hidden --no-ignore -l -- --iglob "${TMP}/cased"
}

@test "skips them when the caller's glob comes after the pattern and the path" {
  expect_rg ./b.yaml -l needle . -g '*.yaml'
  expect_rg ./b.yaml -l needle . --glob='*.yaml'
  expect_rg ./b.yaml -l needle . --iglob '*.yaml'
  expect_rg ./b.yaml needle . -l -g '*.yaml'
}

@test "still skips them when a -- ends the options" {
  expect_rg "$(printf './b.yaml\n./sub/c.txt')" -l -- needle .
  expect_rg ./b.yaml -l -g '*.yaml' -- needle .
  expect_rg ./b.yaml -l --glob='*.yaml' -- needle .
  expect_rg ./b.yaml -l -g'*.yaml' -- needle .
  expect_rg ./b.yaml -lg '*.yaml' -- needle .
  expect_rg ./b.yaml -lg'*.yaml' -- needle .
  expect_rg ./b.yaml -l --iglob '*.yaml' -- needle .
  expect_rg ./b.yaml -l -g '*.yaml' -- '--' .
}

@test "a -- that is the value of a flag does not end the options" {
  for shape in "-l -g *.yaml -e -- ." "-l -g *.yaml -e-- ." "-l -g *.yaml -le -- ." "-l -g *.yaml --regexp -- ." \
    "-l -g *.yaml --regexp=-- ." "-g *.yaml -l -e -- ." "-l -e -- -g *.yaml ."; do
    read -ra words <<<"${shape}"
    expect_rg ./b.yaml "${words[@]}"
  done
}

@test "lists only the kept files with --files" {
  expect_rg ./b.yaml --files -g '*.yaml' .
  expect_rg b.yaml --files -g '*.yaml'
  expect_rg "$(printf './b.yaml\n./sub/c.txt\n./words.txt')" --files -g '*' .
  cd "${TMP}/secrets"
  expect_rg "$(kept_listing ./)" --files --hidden --no-ignore -g '*' .
}

@test "skips a listed folder passed by name, whatever the caller's glob is" {
  cd "${TMP}/secrets"
  for dir in .kube .kube/ ./.kube .aws "${TMP}/secrets/.aws" clusterconfig sub/clusterconfig sub/clusterconfig/deep \
    .git ./.git sub/.git .git/refs .git/refs/heads "${TMP}/secrets/.git" "${TMP}/secrets/.git/refs"; do
    for hidden in "" --hidden; do
      for glob in -g --iglob; do
        run rg ${hidden:+"${hidden}"} "${glob}" '*' -l needle "${dir}"
        if [ "${status}" -ne 1 ] || [ -n "${output}" ]; then
          echo "rg ${hidden} ${glob} ${dir}: status ${status}, output '${output}'" >&2
          return 1
        fi
      done
    done
  done
  run rg --hidden -g '*' -l needle .github
  [ "${output}" = ".github/ci.yml" ]
}

@test "every entry in secret-globs is skipped, as a file or as a directory, also with a caller glob" {
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
  done <"${SHIM_DIR}/secret-globs"
  SECURITY_HOOKS_GREP_SHIM=0 run rg --hidden --no-ignore -l needle "${TMP}/each"
  [ "$(printf '%s\n' "${output}" | wc -l)" -gt 10 ]
  run rg --hidden --no-ignore -l -g '*' needle "${TMP}/each"
  [ "${output}" = "${TMP}/each/kept.txt" ]
  [ "${#dirs[@]}" -gt 3 ]
  for dir in "${dirs[@]}"; do
    run rg --hidden --no-ignore -l -g '*' needle "${dir}"
    if [ "${status}" -ne 1 ] || [ -n "${output}" ]; then
      echo "rg ${dir}: status ${status}, output '${output}'" >&2
      return 1
    fi
  done
}

@test "stops with a clear error when the glob list is missing or empty, unless the shim is off" {
  mkdir "${TMP}/lonely"
  cp "${SHIM_DIR}/rg" "${SHIM_DIR}/shim-common.bash" "${TMP}/lonely/"
  run --separate-stderr "${TMP}/lonely/rg" -l -g '*' needle .
  [ "${status}" -eq 2 ]
  [ -z "${output}" ]
  [[ "${stderr}" == "rg: "*"secret-globs"* ]]
  : >"${TMP}/lonely/secret-globs"
  run --separate-stderr "${TMP}/lonely/rg" -l -g '*' needle .
  [ "${status}" -eq 2 ]
  [ -z "${output}" ]
  [[ "${stderr}" == "rg: "*"secret-globs"* ]]
  rm "${TMP}/lonely/secret-globs"
  SECURITY_HOOKS_GREP_SHIM=0 run "${TMP}/lonely/rg" -l needle b.yaml
  [ "${output}" = "b.yaml" ]
}

@test "stops with a clear error when the helper next to it is missing" {
  mkdir "${TMP}/bare"
  cp "${SHIM_DIR}/rg" "${SHIM_DIR}/secret-globs" "${TMP}/bare/"
  run --separate-stderr "${TMP}/bare/rg" -l needle .
  [ "${status}" -eq 2 ]
  [ -z "${output}" ]
  [[ "${stderr}" == "rg: "*"shim-common.bash"* ]]
}

@test "SECURITY_HOOKS_GREP_SHIM=0 turns it off and any other value leaves it on" {
  SECURITY_HOOKS_GREP_SHIM=0 run rg -l needle .
  [ "$(sorted "${output}")" = "$(printf './a.sops.yaml\n./b.yaml\n./sub/c.sops.json\n./sub/c.txt')" ]
  SECURITY_HOOKS_GREP_SHIM=0 run rg -l -g '*.yaml' needle .
  [ "$(sorted "${output}")" = "$(printf './a.sops.yaml\n./b.yaml')" ]
  SECURITY_HOOKS_GREP_SHIM=0 run rg -l -g '*' needle .
  [ "${#lines[@]}" -eq 4 ]
  SECURITY_HOOKS_GREP_SHIM=1 run rg -l -g '*.yaml' needle .
  [ "${output}" = "./b.yaml" ]
  SECURITY_HOOKS_GREP_SHIM='' run rg -l -g '*.yaml' needle .
  [ "${output}" = "./b.yaml" ]
}

@test "behaves like the real rg when no listed file is involved" {
  cd "${TMP}/plain"
  for shape in "-n needle ." "-n -- needle ." "-l -e -- ." "-l -e-- ." "-le -- ." "--regexp -- -l ." "--regexp=-- -l ." \
    "-e needle -e -- -l ." "-A 1 -- needle one.txt" "-A1 -- needle one.txt" "-m 1 -- needle one.txt" "--max-count 1 -- needle one.txt" \
    "--max-count=1 -- needle one.txt" "-f one.txt -- two.txt" "--file one.txt -- two.txt" "-g *.txt -l -- needle ." \
    "-g *.txt -l needle ." "-l needle . -g *.txt" "--iglob *.TXT -l needle ." "-t txt -l needle ." "-T txt -l needle ." \
    "--type-add zz:*.txt -t zz -l needle ." "needle one.txt -n" "-- -- one.txt" "-c needle one.txt two.txt" "-C 1 -- needle one.txt" \
    "--max-depth 1 -l needle ." "--maxdepth 1 -l needle ." "-d 1 -l needle ." "-r X -- needle one.txt" "--replace X -- needle one.txt" \
    "--pre cat -- needle one.txt" "--sort path -l needle ." "--files" "--files -g *.txt" "--type-list" "--version" "--pcre2-version" \
    "-e" "--frobnicate -- needle one.txt" "-Q needle one.txt" "-g" "needle -g" "-- needle -g"; do
    read -ra words <<<"${shape}"
    run --separate-stderr rg "${words[@]}" </dev/null
    shim_status="${status}"
    shim_output="$(sorted "${output}")"
    shim_stderr="${stderr}"
    run --separate-stderr "${RG}" "${words[@]}" </dev/null
    if [ "${shim_status}" != "${status}" ] || [ "${shim_output}" != "$(sorted "${output}")" ] || [ "${shim_stderr}" != "${stderr}" ]; then
      echo "rg ${shape}: shim ${shim_status} '${shim_output}' '${shim_stderr}', real ${status} '${output}' '${stderr}'" >&2
      return 1
    fi
  done
}

@test "an option without its value gets the real rg's usage error and nothing is searched" {
  local last
  for last in -g -lg --glob --iglob -e --regexp; do
    run --separate-stderr rg -l needle . "${last}" </dev/null
    [ "${status}" -eq 2 ]
    [ -z "${output}" ]
    [[ "${stderr}" == *"missing value for flag"* ]]
  done
}

@test "passes arguments through exactly" {
  run rg -l 'two words' words.txt
  [ "${output}" = "words.txt" ]
  printf 'a b\n' >'spa ce.txt'
  run rg -l 'a b' 'spa ce.txt'
  [ "${output}" = "spa ce.txt" ]
  run rg -c '' b.yaml
  [ "${output}" = "2" ]
}

@test "keeps the exit status, stdout and stdin behaviour of rg" {
  run rg -c needle b.yaml
  [ "${status}" -eq 0 ]
  [ "${output}" = "1" ]
  run rg nomatch b.yaml
  [ "${status}" -eq 1 ]
  run --separate-stderr rg needle missing.txt
  [ "${status}" -eq 2 ]
  [[ "${stderr}" == *"missing.txt"*"No such file or directory"* ]]
  run bash -c "printf 'needle\n' | rg -c needle"
  [ "${output}" = "1" ]
}

@test "an exported errexit changes neither the status nor the message of rg" {
  for shape in "--frobnicate needle b.yaml" "-g" "-c needle b.yaml" "nomatch b.yaml"; do
    read -ra words <<<"${shape}"
    run --separate-stderr env SHELLOPTS=errexit rg "${words[@]}" </dev/null
    shim_status="${status}"
    shim_output="$(sorted "${output}")"
    shim_stderr="${stderr}"
    run --separate-stderr "${RG}" "${words[@]}" </dev/null
    if [ "${shim_status}" != "${status}" ] || [ "${shim_output}" != "$(sorted "${output}")" ] || [ "${shim_stderr}" != "${stderr}" ]; then
      echo "rg ${shape}: shim ${shim_status} '${shim_output}' '${shim_stderr}', real ${status} '${output}' '${stderr}'" >&2
      return 1
    fi
  done
}

@test "an exported xtrace prints nothing extra" {
  run --separate-stderr env SHELLOPTS=xtrace rg -c needle b.yaml
  [ "${status}" -eq 0 ]
  [ "${output}" = "1" ]
  [ -z "${stderr}" ]
}

@test "a BASH_ENV file is not sourced" {
  printf 'touch "%s/sourced"\n' "${TMP}" >"${TMP}/bash_env.sh"
  run env BASH_ENV="${TMP}/bash_env.sh" rg -c needle b.yaml
  [ "${status}" -eq 0 ]
  [ "${output}" = "1" ]
  [ ! -e "${TMP}/sourced" ]
}

@test "does not loop when its directory is on PATH twice or through a link" {
  PATH="${SHIM_DIR}:${SHIM_DIR}:${ORIG_PATH}:${SHIM_DIR}"
  run timeout 10 rg -l -g '*.yaml' needle .
  [ "${status}" -eq 0 ]
  [ "${output}" = "./b.yaml" ]
  mkdir "${TMP}/link"
  ln -s "${SHIM_DIR}/rg" "${TMP}/link/rg"
  PATH="${TMP}/link:${SHIM_DIR}:${ORIG_PATH}"
  hash -r
  run timeout 10 rg -l -g '*.yaml' needle .
  [ "${status}" -eq 0 ]
  [ "${output}" = "./b.yaml" ]
}

@test "does not loop between different copies of itself on PATH" {
  mkdir "${TMP}/copy" "${TMP}/older"
  cp "${SHIM_DIR}/rg" "${SHIM_DIR}/shim-common.bash" "${SHIM_DIR}/secret-globs" "${TMP}/copy/"
  {
    sed -n 1,2p "${SHIM_DIR}/rg"
    printf 'exit 99\n'
  } >"${TMP}/older/rg"
  chmod +x "${TMP}/older/rg"
  PATH="${TMP}/copy:${SHIM_DIR}:${TMP}/older:${ORIG_PATH}"
  hash -r
  run timeout 10 rg -l -g '*.yaml' needle .
  [ "${status}" -eq 0 ]
  [ "${output}" = "./b.yaml" ]
}

@test "stops with a clear error when no other rg is on PATH" {
  mkdir "${TMP}/onlybash"
  ln -s "$(command -v bash)" "${TMP}/onlybash/bash"
  run -127 --separate-stderr timeout 10 env PATH="${SHIM_DIR}:${TMP}/onlybash" rg needle b.yaml
  [ "${status}" -eq 127 ]
  [[ "${stderr}" == "rg: "* ]]
}

@test "its flag table matches the real rg" {
  # shellcheck source=/dev/null
  source "${SHIM_DIR}/rg"
  cd "${TMP}/plain"
  decl_re='^    -'
  short_re='^    -([^-])'
  long_re='--([a-z0-9][a-z0-9-]*)'
  shorts=()
  longs=(maxdepth)
  while IFS= read -r line; do
    if [[ "${line}" =~ ${short_re} ]]; then
      shorts+=("${BASH_REMATCH[1]}")
    fi
    if [[ "${line}" =~ ${decl_re} && "${line}" =~ ${long_re} ]]; then
      longs+=("${BASH_REMATCH[1]}")
    fi
  done < <("${RG}" --help)
  [ "${#shorts[@]}" -gt 20 ]
  [ "${#longs[@]}" -gt 80 ]
  for c in "${shorts[@]}"; do
    msg="$("${RG}" "-${c}" </dev/null 2>&1 || true)"
    want=0
    [[ "${msg}" != *"missing value for flag"* ]] || want=1
    got=0
    ! short_takes_value "${c}" || got=1
    if [ "${got}" != "${want}" ]; then
      echo "-${c}: shim says ${got}, rg says ${want}" >&2
      return 1
    fi
  done
  for name in "${longs[@]}"; do
    msg="$("${RG}" "--${name}" </dev/null 2>&1 || true)"
    want=0
    [[ "${msg}" != *"missing value for flag"* ]] || want=1
    got=0
    ! long_takes_value "${name}" || got=1
    if [ "${got}" != "${want}" ]; then
      echo "--${name}: shim says ${got}, rg says ${want}" >&2
      return 1
    fi
  done
}
